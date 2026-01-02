from sqlalchemy import Column, String, BigInteger, Text, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

class Lambda(Base):
    __tablename__ = "lambdas"
    
    id_lambda = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_owner = Column(String(255), nullable=False)
    descripcion = Column(Text)
    codigo_path = Column(String(500), nullable=False)
    file_size = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Encargo(Base):
    __tablename__ = "encargos"
    
    id_encargo = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_lambda = Column(UUID(as_uuid=True), ForeignKey("lambdas.id_lambda", ondelete="CASCADE"), nullable=False)
    datos_entrada_path = Column(String(500))
    resultado_path = Column(String(500))
    status = Column(String(50), default="pending")
    exit_code = Column(Integer)
    stdout = Column(Text)
    stderr = Column(Text)
    execution_time_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))