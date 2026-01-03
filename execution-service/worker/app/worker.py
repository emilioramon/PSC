#!/usr/bin/env python3
import sys
import logging

# IMPORTANTE: Configurar logging ANTES de cualquier otra cosa
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

logger.info("Iniciando imports...")

# Imports
from kafka import KafkaConsumer
from kafka.errors import KafkaError
from kafka.structs import TopicPartition
import redis
import requests
import json
import time
import io
from config import settings
from executor import CodeExecutor

logger.info("✓ Imports completados exitosamente")


class ExecutionWorker:
    def __init__(self):
        self.worker_id = settings.worker_id
        self.executor = CodeExecutor(
            timeout_seconds=settings.execution_timeout,
            max_memory_mb=settings.max_memory_mb
        )
        self.redis_client = None
        self.consumer = None
        self.running = True
        
        logger.info(f"=== Worker {self.worker_id} inicializado ===")
        logger.info(f"Kafka: {settings.kafka_bootstrap_servers}")
        logger.info(f"Storage: {settings.storage_service_url}")
        logger.info(f"Redis: {settings.redis_host}:{settings.redis_port}")
    
    def connect_redis(self):
        """Conectar a Redis"""
        max_retries = 10
        for attempt in range(max_retries):
            try:
                self.redis_client = redis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    decode_responses=False,
                    socket_connect_timeout=5
                )
                # Test connection
                self.redis_client.ping()
                logger.info("✓ Conectado a Redis")
                return True
            except Exception as e:
                logger.warning(f"Intento {attempt+1}/{max_retries} Redis: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
        
        logger.error("✗ No se pudo conectar a Redis")
        return False
    
    def connect_kafka(self):
        """Conectar a Kafka"""
        max_retries = 20
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Conectando a Kafka (intento {attempt+1}/{max_retries})...")
                logger.info(f"Bootstrap servers: {settings.kafka_bootstrap_servers}")
                logger.info(f"Topic: {settings.kafka_topic_encargos}")
                logger.info(f"Group: {settings.kafka_group_id}")
                
                self.consumer = KafkaConsumer(
                    settings.kafka_topic_encargos,
                    bootstrap_servers=settings.kafka_bootstrap_servers.split(','),
                    group_id=settings.kafka_group_id,
                    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                    auto_offset_reset='earliest',
                    enable_auto_commit=True,
                    max_poll_interval_ms=300000,
                    session_timeout_ms=30000,
                    heartbeat_interval_ms=10000
                )
                
                # Test connection - obtener particiones
                partitions = self.consumer.partitions_for_topic(settings.kafka_topic_encargos)
                logger.info(f"✓ Conectado a Kafka. Particiones: {partitions}")
                
                # Incrementar contador de workers en Redis
                if self.redis_client:
                    try:
                        self.redis_client.incr("workers:count")
                        logger.info("Worker count incrementado en Redis")
                    except Exception as e:
                        logger.warning(f"No se pudo incrementar contador: {e}")
                
                return True
            
            except KafkaError as e:
                logger.error(f"Kafka error en intento {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Reintentando en {retry_delay} segundos...")
                    time.sleep(retry_delay)
                else:
                    logger.error("✗ No se pudo conectar a Kafka después de todos los intentos")
                    raise
            
            except Exception as e:
                logger.error(f"Error inesperado: {e}", exc_info=True)
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    raise
        
        return False
    
    def process_encargo(self, encargo_data: dict):
        """Procesar un encargo"""
        id_encargo = encargo_data.get('id_encargo')
        id_lambda = encargo_data.get('id_lambda')
        
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"Worker {self.worker_id} procesando encargo {id_encargo}")
        logger.info(f"Lambda: {id_lambda}")
        logger.info(f"{'='*60}")
        
        try:
            # Actualizar estado a 'running' en Redis
            self.update_redis_status(id_encargo, "running", id_lambda=id_lambda)
            
            # Convertir hex a bytes
            logger.info("Convirtiendo codigo y datos de hex a bytes...")
            codigo_zip = bytes.fromhex(encargo_data['codigo_content'])
            datos_zip = bytes.fromhex(encargo_data['datos_content'])
            
            logger.info(f"Codigo size: {len(codigo_zip)} bytes")
            logger.info(f"Datos size: {len(datos_zip)} bytes")
            
            # Ejecutar código
            logger.info("Iniciando ejecución...")
            result = self.executor.execute(id_encargo, codigo_zip, datos_zip)
            
            logger.info(f"Ejecución completada:")
            logger.info(f"  - Success: {result['success']}")
            logger.info(f"  - Exit code: {result['exit_code']}")
            logger.info(f"  - Time: {result['execution_time_ms']}ms")
            logger.info(f"  - Output ZIP: {len(result['output_zip']) if result['output_zip'] else 0} bytes")
            
            # Guardar resultado en Storage Service
            logger.info("Guardando resultado en Storage...")
            self.save_result_to_storage(id_encargo, result)
            
            # Actualizar estado en Redis
            self.update_redis_status(
                id_encargo,
                "completed",
                id_lambda=id_lambda,
                exit_code=result['exit_code'],
                stdout=result['stdout'][:1000],
                stderr=result['stderr'][:1000],
                execution_time_ms=result['execution_time_ms']
            )
            
            logger.info(f"✓ Encargo {id_encargo} completado exitosamente")
            logger.info(f"{'='*60}")
        
        except Exception as e:
            logger.error(f"✗ Error procesando encargo {id_encargo}: {e}", exc_info=True)
            
            # Actualizar estado a 'failed'
            self.update_redis_status(
                id_encargo,
                "failed",
                id_lambda=id_lambda,
                stderr=str(e)
            )
    
    def update_redis_status(self, id_encargo: str, status: str, **kwargs):
        """Actualizar estado del encargo en Redis"""
        if not self.redis_client:
            logger.warning("Redis no disponible, no se puede actualizar estado")
            return
        
        try:
            key = f"encargo:{id_encargo}"
            
            # Intentar obtener datos existentes
            try:
                data = self.redis_client.get(key)
                if data:
                    encargo = json.loads(data.decode('utf-8'))
                else:
                    encargo = {"id_encargo": id_encargo}
            except:
                encargo = {"id_encargo": id_encargo}
            
            encargo["status"] = status
            encargo.update(kwargs)
            
            self.redis_client.setex(
                key,
                3600 * 24,  # 24 horas
                json.dumps(encargo)
            )
            
            logger.info(f"Redis actualizado: {id_encargo} -> {status}")
        
        except Exception as e:
            logger.error(f"Error actualizando Redis: {e}")
    
    def save_result_to_storage(self, id_encargo: str, result: dict):
        """Guardar resultado en Storage Service"""
        try:
            logger.info(f"Guardando resultado para encargo {id_encargo}")
            logger.info(f"  Success: {result['success']}")
            logger.info(f"  Exit code: {result['exit_code']}")
            logger.info(f"  Output ZIP: {len(result['output_zip']) if result['output_zip'] else 0} bytes")
            
            data = {
                "id_encargo": id_encargo,
                "status": "completed" if result['success'] else "failed",
                "exit_code": result['exit_code'],
                "stdout": result['stdout'][:5000],
                "stderr": result['stderr'][:5000],
                "execution_time_ms": result['execution_time_ms']
            }
            
            files = {}
            
            # Si hay output ZIP, agregarlo
            if result['output_zip']:
                logger.info(f"Agregando archivo resultado.zip ({len(result['output_zip'])} bytes)")
                files['file'] = (
                    'resultado.zip',
                    io.BytesIO(result['output_zip']),
                    'application/zip'
                )
            else:
                logger.warning("⚠ No hay output_zip para enviar")
            
            # Enviar a storage
            url = f"{settings.storage_service_url}/api/v1/guardar_resultado_encargo"
            logger.info(f"POST a {url}")
            
            response = requests.post(
                url,
                files=files if files else None,
                data=data,
                timeout=60
            )
            
            logger.info(f"Storage response: {response.status_code}")
            
            if response.status_code == 200:
                logger.info(f"✓ Resultado guardado en storage")
                logger.info(f"  Response: {response.text[:200]}")
            else:
                logger.error(f"✗ Error guardando en storage: {response.status_code}")
                logger.error(f"  Response: {response.text}")
        
        except Exception as e:
            logger.error(f"✗ Error guardando resultado: {e}", exc_info=True)
    
    def run(self):
        """Ejecutar worker"""
        logger.info(f"")
        logger.info(f"{'#'*60}")
        logger.info(f"Worker {self.worker_id} iniciando...")
        logger.info(f"{'#'*60}")
        
        # Conectar a Redis
        if not self.connect_redis():
            logger.error("No se pudo conectar a Redis, continuando sin él...")
        
        # Conectar a Kafka
        if not self.connect_kafka():
            logger.error("No se pudo conectar a Kafka. Abortando.")
            return
        
        logger.info(f"")
        logger.info(f"✓ Worker {self.worker_id} listo para procesar encargos")
        logger.info(f"  Esperando mensajes en topic: {settings.kafka_topic_encargos}")
        logger.info(f"")
        
        try:
            message_count = 0
            for message in self.consumer:
                if not self.running:
                    break
                
                message_count += 1
                logger.info(f"")
                logger.info(f">>> Mensaje #{message_count} recibido <<<")
                logger.info(f"Partition: {message.partition}, Offset: {message.offset}")
                
                encargo_data = message.value
                logger.info(f"Encargo ID: {encargo_data.get('id_encargo')}")
                
                self.process_encargo(encargo_data)
        
        except KeyboardInterrupt:
            logger.info(f"Worker {self.worker_id} interrumpido por usuario")
        
        except Exception as e:
            logger.error(f"Error en worker loop: {e}", exc_info=True)
        
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Apagar worker limpiamente"""
        logger.info(f"")
        logger.info(f"Worker {self.worker_id} apagándose...")
        self.running = False
        
        if self.consumer:
            try:
                self.consumer.close()
                logger.info("Kafka consumer cerrado")
            except:
                pass
        
        # Decrementar contador de workers
        if self.redis_client:
            try:
                self.redis_client.decr("workers:count")
                logger.info("Worker count decrementado")
            except:
                pass
        
        logger.info(f"Worker {self.worker_id} apagado")


if __name__ == "__main__":
    try:
        logger.info("=== Iniciando worker desde __main__ ===")
        worker = ExecutionWorker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Worker interrumpido por usuario")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error fatal en worker: {e}", exc_info=True)
        sys.exit(1)