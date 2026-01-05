# Gestor de Funciones Lambda - Interface Web

Interface web con Nginx en Docker para gestionar y ejecutar funciones Lambda a través de un API REST Gateway.

## 📋 Estructura del Proyecto

```
lambda-ui/
├── Dockerfile
├── docker-compose.yml
├── nginx.conf
├── html/
│   ├── index.html
│   ├── api-client.js
│   └── app.js
└── README.md
```

## 🚀 Instalación y Despliegue

### Prerrequisitos

- Docker y Docker Compose instalados
- API REST Gateway corriendo en `http://localhost:8080`

### Paso 1: Crear la estructura de directorios

```bash
mkdir -p lambda-ui/html
cd lambda-ui
```

### Paso 2: Crear los archivos

Copie los siguientes archivos en su ubicación correspondiente:

- `Dockerfile` → raíz del proyecto
- `docker-compose.yml` → raíz del proyecto
- `nginx.conf` → raíz del proyecto
- `index.html` → carpeta `html/`
- `api-client.js` → carpeta `html/`
- `app.js` → carpeta `html/`

### Paso 3: Construir y ejecutar el contenedor

```bash
# Construir la imagen
docker-compose build

# Iniciar el servicio
docker-compose up -d

# Ver logs
docker-compose logs -f
```

### Paso 4: Acceder a la aplicación

Abra su navegador en: `http://localhost`

## 🎯 Funcionalidades

### Panel 1: Alta de Función Lambda

Permite registrar nuevas funciones Lambda en el sistema.

**Campos:**
- **Identificador de Usuario**: ID del propietario de la función
- **Nombre de la Función**: Descripción de la función lambda
- **Archivo**: Fichero .zip o .py con el código de la función

**Endpoint utilizado:** `POST /api/v1/guardar_lambda`

### Panel 2: Ejecución de Función Lambda

Permite ejecutar funciones Lambda registradas con datos de entrada.

**Flujo de trabajo:**
1. Ingrese el ID de usuario
2. Cargue las funciones disponibles
3. Seleccione una función del listado
4. Cargue el archivo de datos de entrada
5. Ejecute la función

**Proceso de ejecución:**
1. Se envía el encargo → `POST /api/v1/dejar_encargo`
2. Se chequea periódicamente el estado → `GET /api/v1/get_encargo/{id_encargo}/info`
3. Se descarga el resultado → `GET /api/v1/get_resultado_encargo/{id_encargo}`

**Endpoints utilizados:**
- `GET /api/v1/get_list_lambdas_disponibles`
- `POST /api/v1/dejar_encargo`
- `GET /api/v1/get_encargo/{id_encargo}/info`
- `GET /api/v1/get_resultado_encargo/{id_encargo}`

## 🔧 Configuración

### Cambiar la URL del API Gateway

Si su API Gateway está en una URL diferente, modifique:

**En `api-client.js`:**
```javascript
const API_BASE_URL = 'http://localhost:8080'; // Cambiar aquí
```

**En `nginx.conf`:**
```nginx
proxy_pass http://host.docker.internal:8080/api/; # Cambiar aquí
```

### Ajustar timeouts

En `nginx.conf` puede modificar los timeouts para operaciones largas:

```nginx
proxy_read_timeout 300s;      # Tiempo máximo de lectura
proxy_connect_timeout 75s;    # Tiempo máximo de conexión
```

## 📡 API Client (Proxy JavaScript)

El cliente JavaScript incluye los siguientes métodos:

- `healthCheck()` - Verificar estado del API
- `guardarLambda(ownerId, descripcion, file)` - Registrar nueva función
- `getListLambasDisponibles(ownerId)` - Obtener funciones del usuario
- `dejarEncargo(lambdaId, ownerId, dataFile)` - Crear encargo de ejecución
- `getEncargoInfo(encargoId)` - Obtener estado del encargo
- `getResultadoEncargo(encargoId)` - Descargar resultados
- `evaluar(lambdaId, ownerId, dataFile, onProgress)` - Proceso completo de ejecución

## 🛠️ Comandos Docker Útiles

```bash
# Detener el servicio
docker-compose down

# Ver logs en tiempo real
docker-compose logs -f nginx-lambda-ui

# Reconstruir después de cambios
docker-compose up -d --build

# Entrar al contenedor
docker exec -it lambda-ui sh

# Ver estado del contenedor
docker-compose ps
```

## 🐛 Troubleshooting

### Error de conexión con el API Gateway

Verifique que:
1. El API Gateway esté ejecutándose en `http://localhost:8080`
2. El firewall permita la conexión
3. En Windows/Mac, `host.docker.internal` resuelve correctamente

### El archivo no se descarga

Revise:
1. Los permisos del archivo en el servidor API
2. Que el encargo haya completado correctamente
3. La consola del navegador para ver errores

### Los archivos no se suben

Verifique:
1. El tamaño máximo permitido por Nginx (por defecto 1MB)
2. Para aumentarlo, agregue en `nginx.conf`:
```nginx
client_max_body_size 100M;
```

## 📝 Notas

- Los estados de encargo pueden ser: `pending`, `running`, `completed`, `failed`, `error`
- El polling se realiza cada 2 segundos por un máximo de 60 intentos (2 minutos)
- Los resultados se descargan automáticamente en formato .zip
- La interface usa almacenamiento en memoria (no localStorage)

## 🔒 Seguridad

Esta es una implementación básica para desarrollo. Para producción considere:
- Implementar autenticación y autorización
- Usar HTTPS
- Validar y sanitizar inputs
- Implementar rate limiting
- Agregar CORS apropiado
