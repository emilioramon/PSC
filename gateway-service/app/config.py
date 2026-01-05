import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Servicios backend
    storage_service_url: str = os.getenv("STORAGE_SERVICE_URL", "http://localhost:8000")
    execution_service_url: str = os.getenv("EXECUTION_SERVICE_URL", "http://localhost:8001")
    
    # Configuración del gateway
    gateway_timeout: int = 120  # 2 minutos
    max_file_size: int = 100 * 1024 * 1024  # 100MB

settings = Settings()