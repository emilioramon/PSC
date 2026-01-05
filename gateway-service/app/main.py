from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Optional, List
import requests
import logging
import io

from config import settings
from models import (
    LambdaResponse, 
    LambdaListItem, 
    EncargoResponse, 
    EncargoInfo,
    ErrorResponse
)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="FaaS API Gateway",
    version="1.0.0",
    description="API Gateway para el sistema FaaS - Punto de entrada único"
)

# =============================================================================
# Health Check
# =============================================================================

@app.get("/")
def root():
    return {
        "service": "FaaS API Gateway",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "storage": settings.storage_service_url,
            "execution": settings.execution_service_url
        }
    }

@app.get("/health")
def health_check():
    """Verificar estado del gateway y servicios backend"""
    health_status = {
        "gateway": "healthy",
        "storage_service": "unknown",
        "execution_service": "unknown"
    }
    
    # Verificar storage service
    try:
        response = requests.get(
            f"{settings.storage_service_url}/health",
            timeout=5
        )
        if response.status_code == 200:
            health_status["storage_service"] = "healthy"
        else:
            health_status["storage_service"] = "unhealthy"
    except Exception as e:
        health_status["storage_service"] = f"error: {str(e)}"
    
    # Verificar execution service
    try:
        response = requests.get(
            f"{settings.execution_service_url}/health",
            timeout=5
        )
        if response.status_code == 200:
            health_status["execution_service"] = "healthy"
        else:
            health_status["execution_service"] = "unhealthy"
    except Exception as e:
        health_status["execution_service"] = f"error: {str(e)}"
    
    return health_status

# =============================================================================
# 1. Get_resultado_encargo
# =============================================================================

@app.get("/api/v1/get_resultado_encargo/{id_encargo}")
def get_resultado_encargo(id_encargo: str):
    """
    Obtener el resultado de un encargo desde el servicio de ejecución.
    Devuelve un archivo .zip con los resultados.
    """
    logger.info(f"Gateway: Obteniendo resultado del encargo {id_encargo}")
    
    try:
        # Llamar al servicio de ejecución
        response = requests.get(
            f"{settings.execution_service_url}/api/v1/get_encargo/{id_encargo}",
            timeout=settings.gateway_timeout,
            stream=True
        )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Encargo no encontrado")
        
        if response.status_code != 200:
            logger.error(f"Error desde execution service: {response.status_code}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Error obteniendo resultado: {response.text}"
            )
        
        # Verificar si es un archivo ZIP o JSON (info)
        content_type = response.headers.get('content-type', '')
        
        if 'application/zip' in content_type or 'application/octet-stream' in content_type:
            # Es un archivo ZIP, devolverlo
            return StreamingResponse(
                io.BytesIO(response.content),
                media_type="application/zip",
                headers={
                    "Content-Disposition": f"attachment; filename=resultado_{id_encargo}.zip"
                }
            )
        else:
            # Es JSON (probablemente info del encargo aún no completado)
            return JSONResponse(content=response.json(), status_code=200)
    
    except requests.exceptions.Timeout:
        logger.error(f"Timeout obteniendo resultado del encargo {id_encargo}")
        raise HTTPException(status_code=504, detail="Timeout al obtener resultado")
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error de conexión con el servicio de ejecución"
        )

@app.get("/api/v1/get_encargo/{id_encargo}/info", response_model=EncargoInfo)
def get_encargo_info(id_encargo: str):
    """
    Obtener información del estado de un encargo.
    """
    logger.info(f"Gateway: Obteniendo info del encargo {id_encargo}")
    
    try:
        response = requests.get(
            f"{settings.execution_service_url}/api/v1/get_encargo/{id_encargo}/info",
            timeout=10
        )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Encargo no encontrado")
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Error obteniendo info: {response.text}"
            )
        
        return response.json()
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error de conexión con el servicio de ejecución"
        )

# =============================================================================
# 2. Dejar_encargo
# =============================================================================

@app.post("/api/v1/dejar_encargo", response_model=EncargoResponse)
async def dejar_encargo(
    id_lambda: str = Form(..., description="ID de la lambda a ejecutar"),
    datos: UploadFile = File(..., description="Archivo .zip con datos de entrada")
):
    """
    Crear un nuevo encargo de ejecución.
    Recibe id_lambda y datos.zip, devuelve id_encargo.
    """
    logger.info(f"Gateway: Creando encargo para lambda {id_lambda}")
    
    # Validar archivo
    if not datos.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="El archivo de datos debe ser .zip")
    
    # Leer archivo
    datos_content = await datos.read()
    
    if len(datos_content) > settings.max_file_size:
        raise HTTPException(status_code=400, detail="Archivo demasiado grande")
    
    try:
        # Obtener el código de la lambda desde el storage service
        logger.info(f"Obteniendo código de lambda {id_lambda} desde storage")
        
        codigo_response = requests.get(
            f"{settings.storage_service_url}/api/v1/get_codigo_lambda/{id_lambda}",
            timeout=30
        )
        
        if codigo_response.status_code == 404:
            raise HTTPException(status_code=404, detail="Lambda no encontrada")
        
        if codigo_response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=f"Error obteniendo código de lambda: {codigo_response.text}"
            )
        
        codigo_content = codigo_response.content
        logger.info(f"Código de lambda obtenido: {len(codigo_content)} bytes")
        
        # Crear encargo en el servicio de ejecución
        logger.info("Creando encargo en execution service")
        
        files = {
            'codigo': ('codigo.zip', io.BytesIO(codigo_content), 'application/zip'),
            'datos': ('datos.zip', io.BytesIO(datos_content), 'application/zip')
        }
        
        data = {
            'id_lambda': id_lambda
        }
        
        exec_response = requests.post(
            f"{settings.execution_service_url}/api/v1/dejar_encargo",
            files=files,
            data=data,
            timeout=settings.gateway_timeout
        )
        
        if exec_response.status_code != 200:
            logger.error(f"Error desde execution service: {exec_response.text}")
            raise HTTPException(
                status_code=exec_response.status_code,
                detail=f"Error creando encargo: {exec_response.text}"
            )
        
        result = exec_response.json()
        logger.info(f"Encargo creado: {result.get('id_encargo')}")
        
        return result
    
    except requests.exceptions.Timeout:
        logger.error("Timeout creando encargo")
        raise HTTPException(status_code=504, detail="Timeout al crear encargo")
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error de conexión con los servicios backend"
        )

# =============================================================================
# 3. Guardar_lambda
# =============================================================================

@app.post("/api/v1/guardar_lambda", response_model=LambdaResponse)
async def guardar_lambda(
    file: UploadFile = File(..., description="Archivo .zip con main.c"),
    id_owner: str = Form(..., description="ID del propietario"),
    descripcion: Optional[str] = Form(None, description="Descripción de la lambda")
):
    """
    Guardar una nueva lambda en el servicio de almacenamiento.
    Devuelve el id_lambda asignado.
    """
    logger.info(f"Gateway: Guardando lambda para owner {id_owner}")
    
    # Validar archivo
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="El archivo debe ser .zip")
    
    # Leer archivo
    file_content = await file.read()
    
    if len(file_content) > settings.max_file_size:
        raise HTTPException(status_code=400, detail="Archivo demasiado grande")
    
    try:
        # Enviar al servicio de almacenamiento
        files = {
            'file': (file.filename, io.BytesIO(file_content), 'application/zip')
        }
        
        data = {
            'id_owner': id_owner,
            'descripcion': descripcion or ''
        }
        
        response = requests.post(
            f"{settings.storage_service_url}/api/v1/guardar_lambda",
            files=files,
            data=data,
            timeout=settings.gateway_timeout
        )
        
        if response.status_code != 200:
            logger.error(f"Error desde storage service: {response.text}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Error guardando lambda: {response.text}"
            )
        
        result = response.json()
        logger.info(f"Lambda guardada: {result.get('id_lambda')}")
        
        return result
    
    except requests.exceptions.Timeout:
        logger.error("Timeout guardando lambda")
        raise HTTPException(status_code=504, detail="Timeout al guardar lambda")
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error de conexión con el servicio de almacenamiento"
        )

# =============================================================================
# 4. Get_list_lambdas_disponibles
# =============================================================================

@app.get("/api/v1/get_list_lambdas_disponibles", response_model=List[LambdaListItem])
def get_list_lambdas_disponibles(id_owner: str):
    """
    Obtener lista de lambdas disponibles para un owner.
    Devuelve lista de pares (id_lambda, descripcion).
    """
    logger.info(f"Gateway: Obteniendo lambdas para owner {id_owner}")
    
    try:
        response = requests.get(
            f"{settings.storage_service_url}/api/v1/get_list_lambdas_disponibles",
            params={'id_owner': id_owner},
            timeout=30
        )
        
        if response.status_code != 200:
            logger.error(f"Error desde storage service: {response.text}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Error obteniendo lista: {response.text}"
            )
        
        return response.json()
    
    except requests.exceptions.Timeout:
        logger.error("Timeout obteniendo lista de lambdas")
        raise HTTPException(status_code=504, detail="Timeout al obtener lista")
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error de conexión con el servicio de almacenamiento"
        )

# =============================================================================
# Endpoints adicionales útiles
# =============================================================================

@app.get("/api/v1/lambda/{id_lambda}")
def get_lambda_info(id_lambda: str):
    """Obtener información de una lambda específica"""
    try:
        response = requests.get(
            f"{settings.storage_service_url}/api/v1/programs/{id_lambda}",
            timeout=10
        )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Lambda no encontrada")
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Error obteniendo info de lambda: {response.text}"
            )
        
        return response.json()
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error de conexión con el servicio de almacenamiento"
        )

@app.get("/api/v1/estas_agobiado")
def estas_agobiado():
    """Verificar si el sistema de ejecución está agobiado"""
    try:
        response = requests.get(
            f"{settings.execution_service_url}/api/v1/estas_agobiado",
            timeout=5
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail="Error consultando estado del sistema"
            )
        
        return response.json()
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error de conexión: {e}")
        raise HTTPException(
            status_code=503,
            detail="Error de conexión con el servicio de ejecución"
        )