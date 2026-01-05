// Cliente JavaScript para interactuar con el API REST Gateway
// Usar ruta relativa para aprovechar el proxy de Nginx
const API_BASE_URL = '';

class ApiClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }

    // Método auxiliar para hacer peticiones
    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        
        try {
            console.log('Haciendo petición a:', url);
            
            const response = await fetch(url, {
                ...options,
                headers: {
                    ...options.headers,
                }
            });

            console.log('Respuesta recibida:', response.status, response.statusText);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || errorData.error || `Error HTTP: ${response.status}`);
            }

            // Para descargas de archivos
            if (options.responseType === 'blob') {
                return await response.blob();
            }

            return await response.json();
        } catch (error) {
            console.error('Error en la petición:', error);
            throw error;
        }
    }

    // Health check
    async healthCheck() {
        return await this.request('/health');
    }

    // Guardar función lambda
    async guardarLambda(ownerId, descripcion, file) {
        const formData = new FormData();
        formData.append('id_owner', ownerId);
        formData.append('descripcion', descripcion);
        formData.append('file', file);

        return await this.request('/api/v1/guardar_lambda', {
            method: 'POST',
            body: formData
        });
    }

    // Obtener lista de lambdas disponibles
    async getListLambasDisponibles(ownerId) {
        return await this.request(`/api/v1/get_list_lambdas_disponibles?id_owner=${encodeURIComponent(ownerId)}`);
    }

    // Dejar encargo
    async dejarEncargo(lambdaId, ownerId, dataFile) {
        const formData = new FormData();
        formData.append('id_lambda', lambdaId);
        formData.append('id_owner', ownerId);
        formData.append('datos', dataFile);

        return await this.request('/api/v1/dejar_encargo', {
            method: 'POST',
            body: formData
        });
    }

    // Obtener información del encargo
    async getEncargoInfo(encargoId) {
        return await this.request(`/api/v1/get_encargo/${encargoId}/info`);
    }

    // Obtener resultado del encargo
    async getResultadoEncargo(encargoId) {
        return await this.request(`/api/v1/get_resultado_encargo/${encargoId}`, {
            responseType: 'blob'
        });
    }

    // Obtener información de una lambda específica
    async getLambda(lambdaId) {
        return await this.request(`/api/v1/lambda/${lambdaId}`);
    }

    // Método de alto nivel para evaluar (thin client)
    async evaluar(lambdaId, ownerId, dataFile, onProgress) {
        try {
            // Paso 1: Dejar el encargo
            if (onProgress) onProgress('Enviando encargo...');
            const encargoResponse = await this.dejarEncargo(lambdaId, ownerId, dataFile);
            const encargoId = encargoResponse.id_encargo;

            if (onProgress) onProgress(`Encargo creado: ${encargoId}. Esperando ejecución...`);

            // Paso 2: Polling para esperar a que esté listo
            const resultado = await this.waitForEncargo(encargoId, onProgress);

            // Paso 3: Descargar el resultado
            if (resultado.resultado_disponible) {
                if (onProgress) onProgress('Descargando resultado...');
                const blob = await this.getResultadoEncargo(encargoId);
                return {
                    encargoInfo: resultado,
                    resultadoBlob: blob,
                    encargoId: encargoId
                };
            } else {
                throw new Error('Encargo completado pero resultado no disponible');
            }
        } catch (error) {
            console.error('Error en evaluación:', error);
            throw error;
        }
    }

    // Método auxiliar para hacer polling del encargo
    async waitForEncargo(encargoId, onProgress, maxAttempts = 60, intervalMs = 2000) {
        let attempts = 0;

        while (attempts < maxAttempts) {
            attempts++;
            
            try {
                const info = await this.getEncargoInfo(encargoId);

                if (onProgress) {
                    onProgress(`Chequeando encargo... (${attempts}/${maxAttempts}) - Estado: ${info.status}`);
                }

                // Estados finales
                if (info.status === 'completed' || info.status === 'failed' || info.status === 'error') {
                    return info;
                }

                // Esperar antes del siguiente intento
                await this.sleep(intervalMs);
            } catch (error) {
                console.error(`Error al chequear encargo (intento ${attempts}):`, error);
                
                if (attempts >= maxAttempts) {
                    throw new Error('Tiempo máximo de espera excedido');
                }
                
                await this.sleep(intervalMs);
            }
        }

        throw new Error('Tiempo máximo de espera excedido');
    }

    // Utilidad para esperar
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// Instancia global del cliente
const apiClient = new ApiClient(API_BASE_URL);