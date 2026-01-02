from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID

class LambdaResponse(BaseModel):
    id_lambda: str
    id_owner: str
    descripcion: Optional[str]
    file_size: Optional[int]
    created_at: datetime
    
    class Config:
        from_attributes = True

class LambdaListItem(BaseModel):
    id_lambda: str
    descripcion: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

class EncargoResponse(BaseModel):
    id_encargo: str
    id_lambda: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime]
    exit_code: Optional[int]
    stdout: Optional[str]
    stderr: Optional[str]
    execution_time_ms: Optional[int]
    tiene_resultado: bool
    
    class Config:
        from_attributes = True