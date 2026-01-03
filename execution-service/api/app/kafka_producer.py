from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError
import json
import logging
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KafkaManager:
    def __init__(self):
        self.producer = None
        self.connect_producer()
    
    def connect_producer(self):
        try:
            self.producer = KafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                acks='all',
                retries=3
            )
            logger.info("Kafka producer connected")
        except KafkaError as e:
            logger.error(f"Error connecting to Kafka: {e}")
            raise
    
    def send_encargo(self, encargo_data: dict):
        """Enviar encargo a Kafka"""
        try:
            future = self.producer.send(
                settings.kafka_topic_encargos,
                value=encargo_data
            )
            # Esperar confirmación
            record_metadata = future.get(timeout=10)
            logger.info(f"Encargo enviado: {encargo_data['id_encargo']} "
                       f"a partition {record_metadata.partition}")
            return True
        except Exception as e:
            logger.error(f"Error enviando encargo: {e}")
            return False
    
    def get_pending_count(self):
        """Obtener cantidad de encargos pendientes en Kafka"""
        try:
            consumer = KafkaConsumer(
                settings.kafka_topic_encargos,
                bootstrap_servers=settings.kafka_bootstrap_servers,
                auto_offset_reset='earliest',
                enable_auto_commit=False,
                consumer_timeout_ms=1000
            )
            
            # Obtener offsets
            partitions = consumer.partitions_for_topic(settings.kafka_topic_encargos)
            if not partitions:
                return 0
            
            total_lag = 0
            for partition in partitions:
                tp = TopicPartition(settings.kafka_topic_encargos, partition)
                consumer.assign([tp])
                committed = consumer.committed(tp) or 0
                end_offset = consumer.end_offsets([tp])[tp]
                total_lag += end_offset - committed
            
            consumer.close()
            return total_lag
        except Exception as e:
            logger.error(f"Error obteniendo pendientes: {e}")
            return 0
    
    def close(self):
        if self.producer:
            self.producer.close()

kafka_manager = KafkaManager()