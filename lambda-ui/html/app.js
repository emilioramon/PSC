// Lógica de la aplicación

// Cambiar entre paneles
function showPanel(panelName) {
    // Actualizar botones
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.classList.add('active');

    // Actualizar paneles
    document.querySelectorAll('.panel').forEach(panel => {
        panel.classList.remove('active');
    });
    document.getElementById(`panel-${panelName}`).classList.add('active');

    // Limpiar mensajes de estado
    hideStatus('alta');
    hideStatus('ejecucion');
}

// Mostrar mensaje de estado
function showStatus(panel, message, type = 'info') {
    const statusEl = document.getElementById(`status-${panel}`);
    statusEl.textContent = message;
    statusEl.className = `status ${type} show`;
}

// Ocultar mensaje de estado
function hideStatus(panel) {
    const statusEl = document.getElementById(`status-${panel}`);
    statusEl.classList.remove('show');
}

// Deshabilitar/habilitar botón
function setButtonLoading(buttonId, loading) {
    const btn = document.getElementById(buttonId);
    btn.disabled = loading;
    if (loading) {
        btn.innerHTML = '<span class="loading"></span> Procesando...';
    } else {
        if (buttonId === 'btn-alta') {
            btn.textContent = 'Alta';
        } else if (buttonId === 'btn-ejecutar') {
            btn.textContent = 'Ejecutar';
        }
    }
}

// Mostrar información del archivo seleccionado
document.getElementById('file-lambda').addEventListener('change', function(e) {
    const file = e.target.files[0];
    const info = document.getElementById('file-info-alta');
    if (file) {
        info.textContent = `Archivo: ${file.name} (${formatBytes(file.size)})`;
    } else {
        info.textContent = '';
    }
});

document.getElementById('file-datos').addEventListener('change', function(e) {
    const file = e.target.files[0];
    const info = document.getElementById('file-info-datos');
    if (file) {
        info.textContent = `Archivo: ${file.name} (${formatBytes(file.size)})`;
    } else {
        info.textContent = '';
    }
});

// Formatear bytes
function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// Alta de función lambda
async function altaLambda() {
    const ownerId = document.getElementById('owner-alta').value.trim();
    const nombreLambda = document.getElementById('nombre-lambda').value.trim();
    const fileInput = document.getElementById('file-lambda');
    const file = fileInput.files[0];

    // Validaciones
    if (!ownerId || !nombreLambda || !file) {
        showStatus('alta', 'Por favor, complete todos los campos requeridos', 'error');
        return;
    }

    try {
        setButtonLoading('btn-alta', true);
        hideStatus('alta');

        const response = await apiClient.guardarLambda(ownerId, nombreLambda, file);

        showStatus('alta', 
            `✅ Función Lambda creada exitosamente!\nID: ${response.id_lambda}\nCreada: ${new Date(response.created_at).toLocaleString()}`, 
            'success'
        );

        // Limpiar formulario
        document.getElementById('form-alta').reset();
        document.getElementById('file-info-alta').textContent = '';

    } catch (error) {
        showStatus('alta', `❌ Error al crear función Lambda: ${error.message}`, 'error');
    } finally {
        setButtonLoading('btn-alta', false);
    }
}

// Cargar funciones lambda disponibles
async function cargarLambdas() {
    const ownerId = document.getElementById('owner-ejecucion').value.trim();

    if (!ownerId) {
        showStatus('ejecucion', 'Por favor, ingrese el identificador de usuario', 'error');
        return;
    }

    try {
        showStatus('ejecucion', 'Cargando funciones lambda...', 'info');

        const lambdas = await apiClient.getListLambasDisponibles(ownerId);

        const selectElement = document.getElementById('select-lambda');
        selectElement.innerHTML = '';

        if (lambdas.length === 0) {
            selectElement.innerHTML = '<option value="">No hay funciones disponibles para este usuario</option>';
            selectElement.disabled = true;
            showStatus('ejecucion', 'No se encontraron funciones lambda para este usuario', 'info');
        } else {
            selectElement.innerHTML = '<option value="">Seleccione una función</option>';
            lambdas.forEach(lambda => {
                const option = document.createElement('option');
                option.value = lambda.id_lambda;
                option.textContent = `${lambda.descripcion || lambda.id_lambda}`;
                selectElement.appendChild(option);
            });
            selectElement.disabled = false;
            showStatus('ejecucion', `✅ Se cargaron ${lambdas.length} función(es) lambda`, 'success');
        }

    } catch (error) {
        showStatus('ejecucion', `❌ Error al cargar funciones: ${error.message}`, 'error');
        document.getElementById('select-lambda').disabled = true;
    }
}

// Ejecutar función lambda
async function ejecutarLambda() {
    const ownerId = document.getElementById('owner-ejecucion').value.trim();
    const lambdaId = document.getElementById('select-lambda').value;
    const fileInput = document.getElementById('file-datos');
    const dataFile = fileInput.files[0];

    // Validaciones
    if (!ownerId || !lambdaId || !dataFile) {
        showStatus('ejecucion', 'Por favor, complete todos los campos requeridos', 'error');
        return;
    }

    try {
        setButtonLoading('btn-ejecutar', true);

        // Callback para actualizaciones de progreso
        const onProgress = (message) => {
            showStatus('ejecucion', message, 'info');
        };

        const resultado = await apiClient.evaluar(lambdaId, ownerId, dataFile, onProgress);

        // Mostrar información del resultado
        const info = resultado.encargoInfo;
        let mensaje = `✅ Ejecución completada!\n`;
        mensaje += `Encargo ID: ${resultado.encargoId}\n`;
        mensaje += `Estado: ${info.status}\n`;
        
        if (info.exit_code !== null) {
            mensaje += `Exit Code: ${info.exit_code}\n`;
        }
        
        if (info.execution_time_ms) {
            mensaje += `Tiempo de ejecución: ${info.execution_time_ms}ms\n`;
        }

        if (info.stdout) {
            mensaje += `\nStdout:\n${info.stdout.substring(0, 200)}${info.stdout.length > 200 ? '...' : ''}`;
        }

        if (info.stderr) {
            mensaje += `\n\nStderr:\n${info.stderr.substring(0, 200)}${info.stderr.length > 200 ? '...' : ''}`;
        }

        showStatus('ejecucion', mensaje, info.status === 'completed' ? 'success' : 'error');

        // Descargar el archivo de resultados
        if (resultado.resultadoBlob) {
            const url = window.URL.createObjectURL(resultado.resultadoBlob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `resultado_${resultado.encargoId}.zip`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            showStatus('ejecucion', mensaje + '\n\n📥 Descargando archivo de resultados...', 'success');
        }

    } catch (error) {
        showStatus('ejecucion', `❌ Error en la ejecución: ${error.message}`, 'error');
    } finally {
        setButtonLoading('btn-ejecutar', false);
    }
}

// Health check al cargar la página
window.addEventListener('load', async () => {
    try {
        await apiClient.healthCheck();
        console.log('✅ Conexión con API Gateway establecida');
    } catch (error) {
        console.error('❌ No se pudo conectar con el API Gateway:', error);
    }
});