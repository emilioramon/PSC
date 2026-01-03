from kafka import KafkaConsumer
import redis
import requests
import json
import logging
import time
import io
from config import settings
from executor import CodeExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ExecutionWorker:
    def __init__(self):
        self.worker_id = settings.worker_id
        self.executor = CodeExecutor(
            timeout_seconds=settings.execution_timeout,
            max_memory_mb=settings.max_memory_mb
        )
        self.redis_client = redis.Redis(host='redis', port=6379, decode_responses=False)
        self.consumer = None
        self.running = True
        
        logger.info(f"Worker {self.worker_id} inicializado")
    
    def connect_kafka(self):
        """Conectar a Kafka"""
        max_retries = 10
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                self.consumer = KafkaConsumer(
                    settings.kafka_topic_encargos,
                    bootstrap_servers=settings.kafka_bootstrap_servers,
                    group_id=settings.kafka_group_id,
                    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                    auto_offset_reset='earliest',
                    enable_auto_commit=True,
                    max_poll_interval_ms=300000  # 5 minutos
                )
                logger.info(f"Worker {self.worker_id} conectado a Kafka")
                
                # Incrementar contador de workers en Redis
                self.redis_client.incr("workers:count")
                return True
            
            except Exception as e:
                logger.error(f"Intento {attempt + 1}/{max_retries} falló: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    raise
        
        return False
    
    def process_encargo(self, encargo_data: dict):
        """Procesar un encargo"""
        id_encargo = encargo_data['id_encargo']
        id_lambda = encargo_data['id_lambda']
        
        logger.info(f"Worker {self.worker_id} procesando encargo {id_encargo}")
        
        try:
            # Actualizar estado a 'running' en Redis
            self.update_redis_status(id_encargo, "running")
            
            # Convertir hex a bytes
            codigo_zip = bytes.fromhex(encargo_data['codigo_content'])
            datos_zip = bytes.fromhex(encargo_data['datos_content'])
            
            # Ejecutar código
            result = self.executor.execute(id_encargo, codigo_zip, datos_zip)
            
            logger.info(f"Encargo {id_encargo} ejecutado: exit_code={result['exit_code']}")
            
            # Guardar resultado en Storage Service
            self.save_result_to_storage(
                id_encargo=id_encargo,
                result=result
            )
            
            # Actualizar estado en Redis
            self.update_redis_status(
                id_encargo,
                "completed",
                exit_code=result['exit_code'],
                stdout=result['stdout'][:1000],  # Limitar tamaño
                stderr=result['stderr'][:1000],
                execution_time_ms=result['execution_time_ms']
            )
            
            logger.info(f"Encargo {id_encargo} completado exitosamente")
        
        except Exception as e:
            logger.error(f"Error procesando encargo {id_encargo}: {e}")
            
            # Actualizar estado a 'failed'
            self.update_redis_status(
                id_encargo,
                "failed",
                stderr=str(e)
            )
    
    def update_redis_status(self, id_encargo: str, status: str, **kwargs):
        """Actualizar estado del encargo en Redis """
        try:   
            key = f"encargo:{id_encargo}"
            data = self.redis_client.get(key)
            if data:
                encargo = json.loads(data.decode('utf-8'))
            else:
                encargo = {"id_encargo": id_encargo}
        
            encargo["status"] = status
            encargo.update(kwargs)
        
            self.redis_client.setex(
               key,
               3600 * 24,  # 24 horas
             json.dumps(encargo)
            )
        except Exception as e: 
            logger.error(f"Error actualizando estado en Redis para {id_encargo}: {e}")
    
    
    def save_result_to_storage(self, id_encargo: str, result: dict):
        """Guardar resultado en Storage Service"""
        try:
            files = {}
            data = {
                "id_encargo": id_encargo,
                "status": "completed" if result['success'] else "failed",
                "exit_code": result['exit_code'],
                "stdout": result['stdout'],
                "stderr": result['stderr'],
                "execution_time_ms": result['execution_time_ms']
            }
            
            # Si hay output ZIP, agregarlo
            if result['output_zip']:
                files['file'] = ('resultado.zip', io.BytesIO(result['output_zip']), 'application/zip')
            
            response = requests.post(
                f"{settings.storage_service_url}/api/v1/guardar_resultado_encargo",
                files=files if files else None,
                data=data,
                timeout=60
            )
            
            if response.status_code == 200:
                logger.info(f"Resultado del encargo {id_encargo} guardado en storage")
            else:
                logger.error(f"Error guardando en storage: {response.status_code} - {response.text}")
        
        except Exception as e:
            logger.error(f"Error guardando resultado: {e}")

    def run(self):
        """Ejecutar worker"""
        logger.info(f"Worker {self.worker_id} iniciando...")
        
        # Conectar a Kafka
        if not self.connect_kafka():
            logger.error("No se pudo conectar a Kafka")
            return
        
        logger.info(f"Worker {self.worker_id} esperando encargos...")
        
        try:
            for message in self.consumer:
                if not self.running:
                    break
                
                encargo_data = message.value
                self.process_encargo(encargo_data)
        
        except KeyboardInterrupt:
            logger.info(f"Worker {self.worker_id} interrumpido por usuario")
        
        except Exception as e:
            logger.error(f"Error en worker loop: {e}")
        
        finally:
            self.shutdown()

    def shutdown(self):
        """Apagar worker limpiamente"""
        logger.info(f"Worker {self.worker_id} apagándose...")
        self.running = False
        
        if self.consumer:
            self.consumer.close()
        
        # Decrementar contador de workers
        try:
            self.redis_client.decr("workers:count")
        except:
            pass
        
        logger.info(f"Worker {self.worker_id} apagado")

if __name__ == "__main__":  
    worker = ExecutionWorker()
    worker.run()