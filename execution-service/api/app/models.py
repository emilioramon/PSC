from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class EncargoCreate(BaseModel):
    id_lambda: str
    codigo_zip: bytes
    datos_zip: bytes

class EncargoResponse(BaseModel):
    id_encargo: str
    status: str
    created_at: datetime

class EncargoResult(BaseModel):
    id_encargo: str
    id_lambda: str
    status: str
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    execution_time_ms: Optional[int] = None
    resultado_disponible: bool = False

class WorkerStatus(BaseModel):
    estas_agobiado: bool
    workers_activos: int
    encargos_pendientes: int
    carga_promedio: float