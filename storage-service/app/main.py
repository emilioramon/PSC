from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
from typing import Optional, List
import zipfile
import io
import uuid

from models import Base, Lambda, Encargo
from schemas import LambdaResponse, LambdaListItem, EncargoResponse
from storage import storage_client
from config import settings

# Crear engine de base de datos
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="FaaS Storage Service", version="1.0.0")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def validate_zip_with_main_c(file_content: bytes) -> bool:
    """Validar que el archivo es un ZIP válido y contiene main.c"""
    try:
        with zipfile.ZipFile(io.BytesIO(file_content)) as zf:
            files = zf.namelist()
            return "main.c" in files
    except zipfile.BadZipFile:
        return False

@app.get("/")
def root():
    return {
        "service": "FaaS Storage Service",
        "version": "1.0.0",
        "status": "running"
    }

# 1. Guardar_lambda
@app.post("/api/v1/guardar_lambda", response_model=LambdaResponse)
async def guardar_lambda(
    file: UploadFile = File(..., description="Archivo .zip con main.c"),
    id_owner: str = Form(..., description="ID del propietario"),
    descripcion: Optional[str] = Form(None, description="Descripción de la lambda"),
    db: Session = Depends(get_db)
):
    """
    Guardar una nueva lambda.
    Recibe un archivo .zip que debe contener main.c y devuelve un id_lambda.
    """
    
    # Validar extensión
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="El archivo debe ser .zip")
    
    # Leer contenido
    content = await file.read()
    
    # Validar tamaño
    if len(content) > settings.max_zip_size:
        raise HTTPException(
            status_code=400, 
            detail=f"Archivo demasiado grande. Máximo: {settings.max_zip_size} bytes"
        )
    
    # Validar que es ZIP válido y contiene main.c
    if not validate_zip_with_main_c(content):
        raise HTTPException(
            status_code=400, 
            detail="El archivo debe ser un ZIP válido que contenga main.c"
        )
    
    # Generar ID de lambda
    id_lambda = str(uuid.uuid4())
    
    # Path en MinIO
    codigo_path = f"lambdas/{id_lambda}.zip"
    
    # Subir a MinIO
    if not storage_client.upload_file(settings.lambdas_bucket, codigo_path, content):
        raise HTTPException(status_code=500, detail="Error al guardar el código")
    
    # Guardar en base de datos
    lambda_obj = Lambda(
        id_lambda=id_lambda,
        id_owner=id_owner,
        descripcion=descripcion,
        codigo_path=codigo_path,
        file_size=len(content)
    )
    
    db.add(lambda_obj)
    db.commit()
    db.refresh(lambda_obj)
    
    return LambdaResponse(
        id_lambda=str(lambda_obj.id_lambda),
        id_owner=lambda_obj.id_owner,
        descripcion=lambda_obj.descripcion,
        file_size=lambda_obj.file_size,
        created_at=lambda_obj.created_at
    )

# 2. Get_list_lambdas_disponibles
@app.get("/api/v1/get_list_lambdas_disponibles", response_model=List[LambdaListItem])
def get_list_lambdas_disponibles(
    id_owner: str,
    db: Session = Depends(get_db)
):
    """
    Obtener lista de lambdas asociadas a un owner.
    Devuelve lista de id_lambda con descripción.
    """
    
    lambdas = db.query(Lambda).filter(
        Lambda.id_owner == id_owner
    ).order_by(Lambda.created_at.desc()).all()
    
    return [
        LambdaListItem(
            id_lambda=str(l.id_lambda),
            descripcion=l.descripcion,
            created_at=l.created_at
        )
        for l in lambdas
    ]

# 3. Get_codigo_lambda
@app.get("/api/v1/get_codigo_lambda/{id_lambda}")
def get_codigo_lambda(
    id_lambda: str,
    db: Session = Depends(get_db)
):
    """
    Obtener el código de una lambda en formato .zip.
    Recibe id_lambda y devuelve el archivo .zip.
    """
    
    # Buscar lambda en BD
    lambda_obj = db.query(Lambda).filter(Lambda.id_lambda == id_lambda).first()
    
    if not lambda_obj:
        raise HTTPException(status_code=404, detail="Lambda no encontrada")
    
    # Descargar de MinIO
    content = storage_client.download_file(
        settings.lambdas_bucket, 
        lambda_obj.codigo_path
    )
    
    if not content:
        raise HTTPException(status_code=500, detail="Error al descargar el código")
    
    # Devolver como archivo
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=lambda_{id_lambda}.zip"
        }
    )

# 4. Get_resultado_encargo
@app.get("/api/v1/get_resultado_encargo/{id_encargo}")
def get_resultado_encargo(
    id_encargo: str,
    db: Session = Depends(get_db)
):
    """
    Obtener el resultado de un encargo en formato .zip.
    Recibe id_encargo y devuelve el archivo .zip con el resultado.
    """
    
    # Buscar encargo en BD
    encargo = db.query(Encargo).filter(Encargo.id_encargo == id_encargo).first()
    
    if not encargo:
        raise HTTPException(status_code=404, detail="Encargo no encontrado")
    
    if not encargo.resultado_path:
        raise HTTPException(
            status_code=404, 
            detail="El encargo no tiene resultado aún"
        )
    
    # Descargar de MinIO
    content = storage_client.download_file(
        settings.encargos_result_bucket, 
        encargo.resultado_path
    )
    
    if not content:
        raise HTTPException(status_code=500, detail="Error al descargar el resultado")
    
    # Devolver como archivo
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=resultado_{id_encargo}.zip"
        }
    )

# 5. Guardar_resultado_encargo
@app.post("/api/v1/guardar_resultado_encargo", response_model=EncargoResponse)
async def guardar_resultado_encargo(
    id_encargo: str = Form(..., description="ID del encargo"),
    file: UploadFile = File(..., description="Archivo .zip con el resultado"),
    status: str = Form("completed", description="Estado del encargo"),
    exit_code: Optional[int] = Form(None, description="Código de salida"),
    stdout: Optional[str] = Form(None, description="Salida estándar"),
    stderr: Optional[str] = Form(None, description="Salida de error"),
    execution_time_ms: Optional[int] = Form(None, description="Tiempo de ejecución en ms"),
    db: Session = Depends(get_db)
):
    """
    Guardar el resultado de ejecución de un encargo.
    Recibe id_encargo y archivo .zip con el resultado.
    """
    
    # Buscar encargo
    encargo = db.query(Encargo).filter(Encargo.id_encargo == id_encargo).first()
    
    if not encargo:
        raise HTTPException(status_code=404, detail="Encargo no encontrado")
    
    # Validar extensión
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="El archivo debe ser .zip")
    
    # Leer contenido
    content = await file.read()
    
    # Validar tamaño
    if len(content) > settings.max_zip_size:
        raise HTTPException(status_code=400, detail="Archivo demasiado grande")
    
    # Path en MinIO
    resultado_path = f"results/{id_encargo}.zip"
    
    # Subir a MinIO
    if not storage_client.upload_file(
        settings.encargos_result_bucket, 
        resultado_path, 
        content
    ):
        raise HTTPException(status_code=500, detail="Error al guardar el resultado")
    
    # Actualizar encargo en BD
    encargo.resultado_path = resultado_path
    encargo.status = status
    encargo.exit_code = exit_code
    encargo.stdout = stdout
    encargo.stderr = stderr
    encargo.execution_time_ms = execution_time_ms
    encargo.completed_at = datetime.utcnow()
    
    db.commit()
    db.refresh(encargo)
    
    return EncargoResponse(
        id_encargo=str(encargo.id_encargo),
        id_lambda=str(encargo.id_lambda),
        status=encargo.status,
        created_at=encargo.created_at,
        completed_at=encargo.completed_at,
        exit_code=encargo.exit_code,
        stdout=encargo.stdout,
        stderr=encargo.stderr,
        execution_time_ms=encargo.execution_time_ms,
        tiene_resultado=encargo.resultado_path is not None
    )

# Métodos adicionales útiles

@app.post("/api/v1/crear_encargo", response_model=EncargoResponse)
async def crear_encargo(
    id_lambda: str = Form(..., description="ID de la lambda a ejecutar"),
    execution_id: str = Form(..., description="ID del encargo (desde execution-service)"),
    datos_entrada: Optional[UploadFile] = File(None, description="Datos de entrada (.zip)"),
    db: Session = Depends(get_db)
):
    """
    Crear un nuevo encargo para ejecutar una lambda.
    IMPORTANTE: Usa el execution_id que viene del execution-service.
    Opcionalmente puede recibir datos de entrada en .zip.
    """
    
    # Verificar que la lambda existe
    lambda_obj = db.query(Lambda).filter(Lambda.id_lambda == id_lambda).first()
    if not lambda_obj:
        raise HTTPException(status_code=404, detail="Lambda no encontrada")
    
    # CRÍTICO: Usar el execution_id que viene del execution-service
    # NO generar uno nuevo aquí
    id_encargo = execution_id
    
    # Verificar que no exista ya un encargo con ese ID
    existing = db.query(Encargo).filter(Encargo.id_encargo == id_encargo).first()
    if existing:
        # Si ya existe, solo devolverlo (idempotencia)
        return EncargoResponse(
            id_encargo=str(existing.id_encargo),
            id_lambda=str(existing.id_lambda),
            status=existing.status,
            created_at=existing.created_at,
            completed_at=existing.completed_at,
            exit_code=existing.exit_code,
            stdout=existing.stdout,
            stderr=existing.stderr,
            execution_time_ms=existing.execution_time_ms,
            tiene_resultado=existing.resultado_path is not None
        )
    
    datos_entrada_path = None
    
    # Si hay datos de entrada, guardarlos
    if datos_entrada:
        if not datos_entrada.filename.endswith('.zip'):
            raise HTTPException(status_code=400, detail="Los datos de entrada deben ser .zip")
        
        content = await datos_entrada.read()
        
        if len(content) > settings.max_zip_size:
            raise HTTPException(status_code=400, detail="Archivo demasiado grande")
        
        datos_entrada_path = f"inputs/{id_encargo}.zip"
        
        if not storage_client.upload_file(
            settings.encargos_input_bucket, 
            datos_entrada_path, 
            content
        ):
            raise HTTPException(status_code=500, detail="Error al guardar datos de entrada")
    
    # Crear encargo en BD con el ID que vino del execution-service
    encargo = Encargo(
        id_encargo=id_encargo,  # ← Ahora usa el ID correcto
        id_lambda=id_lambda,
        datos_entrada_path=datos_entrada_path,
        status="pending"
    )
    
    db.add(encargo)
    db.commit()
    db.refresh(encargo)
    
    return EncargoResponse(
        id_encargo=str(encargo.id_encargo),
        id_lambda=str(encargo.id_lambda),
        status=encargo.status,
        created_at=encargo.created_at,
        completed_at=None,
        exit_code=None,
        stdout=None,
        stderr=None,
        execution_time_ms=None,
        tiene_resultado=False
    )

@app.get("/api/v1/encargo/{id_encargo}", response_model=EncargoResponse)
def get_encargo_info(
    id_encargo: str,
    db: Session = Depends(get_db)
):
    """
    Obtener información de un encargo.
    """
    encargo = db.query(Encargo).filter(Encargo.id_encargo == id_encargo).first()
    
    if not encargo:
        raise HTTPException(status_code=404, detail="Encargo no encontrado")
    
    return EncargoResponse(
        id_encargo=str(encargo.id_encargo),
        id_lambda=str(encargo.id_lambda),
        status=encargo.status,
        created_at=encargo.created_at,
        completed_at=encargo.completed_at,
        exit_code=encargo.exit_code,
        stdout=encargo.stdout,
        stderr=encargo.stderr,
        execution_time_ms=encargo.execution_time_ms,
        tiene_resultado=encargo.resultado_path is not None
    )

@app.get("/api/v1/lambda/{id_lambda}/encargos")
def get_encargos_by_lambda(
    id_lambda: str,
    db: Session = Depends(get_db)
):
    """
    Listar todos los encargos de una lambda específica.
    """
    encargos = db.query(Encargo).filter(
        Encargo.id_lambda == id_lambda
    ).order_by(Encargo.created_at.desc()).all()
    
    return {
        "id_lambda": id_lambda,
        "total": len(encargos),
        "encargos": [
            {
                "id_encargo": str(e.id_encargo),
                "status": e.status,
                "created_at": e.created_at,
                "completed_at": e.completed_at
            }
            for e in encargos
        ]
    }

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "storage"}