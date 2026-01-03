import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Kafka
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_topic_encargos: str = "encargos-pendientes"
    kafka_topic_resultados: str = "encargos-resultados"
    
    # Storage Service
    storage_service_url: str = os.getenv("STORAGE_SERVICE_URL", "http://localhost:8000")
    
    # Redis
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    
    # Límites
    max_zip_size: int = 100 * 1024 * 1024  # 100MB
    worker_load_threshold: float = 0.8  # 80% de carga

settings = Settings()