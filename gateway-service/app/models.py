from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class LambdaResponse(BaseModel):
    id_lambda: str
    id_owner: str
    descripcion: Optional[str]
    file_size: Optional[int]
    created_at: datetime

class LambdaListItem(BaseModel):
    id_lambda: str
    descripcion: Optional[str]

class EncargoResponse(BaseModel):
    id_encargo: str
    status: str
    created_at: datetime

class EncargoInfo(BaseModel):
    id_encargo: str
    id_lambda: str
    status: str
    exit_code: Optional[int]
    stdout: Optional[str]
    stderr: Optional[str]
    execution_time_ms: Optional[int]
    resultado_disponible: bool

class ErrorResponse(BaseModel):
    error: str
    detail: str
    service: str