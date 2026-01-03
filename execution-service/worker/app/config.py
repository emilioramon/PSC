import os

class WorkerSettings:
    # Kafka
    kafka_bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_topic_encargos = "encargos-pendientes"
    kafka_topic_resultados = "encargos-resultados"
    kafka_group_id = "execution-workers"
    
    # Storage Service
    storage_service_url = os.getenv("STORAGE_SERVICE_URL", "http://localhost:8000")
    
    # Worker
    worker_id = os.getenv("WORKER_ID", "worker-1")
    execution_timeout = int(os.getenv("EXECUTION_TIMEOUT", "30"))  # segundos
    max_memory_mb = int(os.getenv("MAX_MEMORY_MB", "512"))
    
    # Paths
    work_dir = "/tmp/faas-executions"

settings = WorkerSettings()