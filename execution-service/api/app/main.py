from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse
import redis
import requests
import uuid
import json
import io
from datetime import datetime
from typing import Optional

from config import settings
from models import EncargoResponse, EncargoResult, WorkerStatus
from kafka_producer import kafka_manager

app = FastAPI(title="FaaS Execution Service", version="1.0.0")

# Conectar a Redis
redis_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    decode_responses=True
)

@app.get("/")
def root():
    return {
        "service": "FaaS Execution Service",
        "version": "1.0.0",
        "status": "running"
    }

# 1. Dejar_encargo
@app.post("/api/v1/dejar_encargo", response_model=EncargoResponse)
async def dejar_encargo(
    id_lambda: str = Form(..., description="ID de la lambda a ejecutar"),
    codigo: UploadFile = File(..., description="codigo.zip con main.c"),
    datos: UploadFile = File(..., description="datos.zip con archivos de entrada")
):
    """
    Crear un nuevo encargo de ejecución.
    Recibe codigo.zip y datos.zip y devuelve id_encargo.
    """
    
    # Validar archivos ZIP
    if not codigo.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="codigo debe ser .zip")
    
    if not datos.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="datos debe ser .zip")
    
    # Leer archivos
    codigo_content = await codigo.read()
    datos_content = await datos.read()
    
    # Validar tamaños
    if len(codigo_content) > settings.max_zip_size:
        raise HTTPException(status_code=400, detail="codigo.zip demasiado grande")
    
    if len(datos_content) > settings.max_zip_size:
        raise HTTPException(status_code=400, detail="datos.zip demasiado grande")
    
    # Generar ID de encargo
    id_encargo = str(uuid.uuid4())
    
    # Guardar en Storage Service (crear encargo con datos de entrada)
    try:
        storage_response = requests.post(
            f"{settings.storage_service_url}/api/v1/crear_encargo",
            files={
                "datos_entrada": ("datos.zip", io.BytesIO(datos_content), "application/zip")
            },
            data={
                "id_lambda": id_lambda,
                "execution_id": id_encargo
            },
            timeout=30
        )
        
        if storage_response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=f"Error guardando en storage: {storage_response.text}"
            )
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Error conectando a storage: {str(e)}")
    
    # Preparar mensaje para Kafka
    encargo_data = {
        "id_encargo": id_encargo,
        "id_lambda": id_lambda,
        "codigo_content": codigo_content.hex(),  # Convertir a hex para serialización
        "datos_content": datos_content.hex(),
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Enviar a Kafka
    if not kafka_manager.send_encargo(encargo_data):
        raise HTTPException(status_code=500, detail="Error enviando a Kafka")
    
    # Guardar estado inicial en Redis
    redis_client.setex(
        f"encargo:{id_encargo}",
        3600 * 24,  # 24 horas TTL
        json.dumps({
            "id_encargo": id_encargo,
            "id_lambda": id_lambda,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        })
    )
    
    return EncargoResponse(
        id_encargo=id_encargo,
        status="pending",
        created_at=datetime.utcnow()
    )

# 2. Get_encargo
@app.get("/api/v1/get_encargo/{id_encargo}")
def get_encargo(id_encargo: str):
    """
    Obtener el resultado de un encargo.
    Devuelve resultado.zip si la ejecución terminó.
    """
    
    # Buscar en Redis
    encargo_data = redis_client.get(f"encargo:{id_encargo}")
    
    if not encargo_data:
        raise HTTPException(status_code=404, detail="Encargo no encontrado")
    
    encargo = json.loads(encargo_data)
    
    # Si no está completado, devolver estado
    if encargo.get("status") != "completed":
        return EncargoResult(
            id_encargo=id_encargo,
            id_lambda=encargo.get("id_lambda"),
            status=encargo.get("status", "pending"),
            resultado_disponible=False
        )
    
    # Si está completado, descargar resultado desde Storage
    try:
        response = requests.get(
            f"{settings.storage_service_url}/api/v1/get_resultado_encargo/{id_encargo}",
            timeout=30
        )
        
        if response.status_code == 404:
            return EncargoResult(
                id_encargo=id_encargo,
                id_lambda=encargo.get("id_lambda"),
                status="completed",
                exit_code=encargo.get("exit_code"),
                stdout=encargo.get("stdout"),
                stderr=encargo.get("stderr"),
                execution_time_ms=encargo.get("execution_time_ms"),
                resultado_disponible=False
            )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail="Error descargando resultado"
            )
        
        # Devolver el archivo ZIP
        return StreamingResponse(
            io.BytesIO(response.content),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=resultado_{id_encargo}.zip"
            }
        )
    
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Error conectando a storage: {str(e)}")

@app.get("/api/v1/get_encargo/{id_encargo}/info", response_model=EncargoResult)
def get_encargo_info(id_encargo: str):
    """
    Obtener información del encargo sin descargar el resultado.
    """
    
    encargo_data = redis_client.get(f"encargo:{id_encargo}")
    
    if not encargo_data:
        raise HTTPException(status_code=404, detail="Encargo no encontrado")
    
    encargo = json.loads(encargo_data)
    
    return EncargoResult(
        id_encargo=id_encargo,
        id_lambda=encargo.get("id_lambda"),
        status=encargo.get("status", "pending"),
        exit_code=encargo.get("exit_code"),
        stdout=encargo.get("stdout"),
        stderr=encargo.get("stderr"),
        execution_time_ms=encargo.get("execution_time_ms"),
        resultado_disponible=encargo.get("status") == "completed"
    )

# 3. Estas_agobiado
@app.get("/api/v1/estas_agobiado", response_model=WorkerStatus)
def estas_agobiado():
    """
    Indica si es necesario crear un nuevo worker.
    Devuelve booleano y métricas del sistema.
    """
    
    # Obtener métricas de Redis
    try:
        # Contar encargos pendientes
        pending_keys = redis_client.keys("encargo:*")
        total_encargos = len(pending_keys)
        
        pending_count = 0
        running_count = 0
        
        for key in pending_keys:
            data = redis_client.get(key)
            if data:
                encargo = json.loads(data)
                status = encargo.get("status", "pending")
                if status == "pending":
                    pending_count += 1
                elif status == "running":
                    running_count += 1
        
        # Obtener cantidad de workers activos
        workers_activos = int(redis_client.get("workers:count") or 2)
        
        # Calcular carga promedio
        if workers_activos > 0:
            carga_promedio = (pending_count + running_count) / workers_activos
        else:
            carga_promedio = 0
        
        # Determinar si está agobiado
        estas_agobiado = carga_promedio > settings.worker_load_threshold * 10
        
        return WorkerStatus(
            estas_agobiado=estas_agobiado,
            workers_activos=workers_activos,
            encargos_pendientes=pending_count,
            carga_promedio=carga_promedio
        )
    
    except Exception as e:
        return WorkerStatus(
            estas_agobiado=False,
            workers_activos=0,
            encargos_pendientes=0,
            carga_promedio=0
        )

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "execution"}

@app.on_event("shutdown")
def shutdown_event():
    kafka_manager.close()