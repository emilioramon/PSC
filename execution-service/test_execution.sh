#!/bin/bash

echo "=== Prueba completa del sistema FaaS ==="
echo ""

# Limpiar archivos anteriores
rm -rf test_lambda datos lambda.zip datos.zip codigo.zip resultado_*.zip

# PASO 1: Crear la lambda
echo "1. Creando archivo main.c..."
mkdir test_lambda
cat > test_lambda/main.c << 'EOF'
#include <stdio.h>

int main() {
    printf("=== Inicio de ejecución ===\n");
    
    // Leer archivo de entrada
    FILE *input = fopen("/datos/input.txt", "r");
    if (input) {
        char line[256];
        printf("Contenido de input.txt:\n");
        while (fgets(line, sizeof(line), input)) {
            printf("  %s", line);
        }
        fclose(input);
    } else {
        printf("No se encontró input.txt\n");
    }
    
    // Crear archivo de salida
    FILE *output = fopen("/datos/output.txt", "w");
    if (output) {
        fprintf(output, "Resultado: Ejecución exitosa\n");
        fprintf(output, "Código de salida: 0\n");
        fclose(output);
        printf("\nArchivo output.txt creado exitosamente\n");
    }
    
    printf("=== Fin de ejecución ===\n");
    return 0;
}
EOF

# Crear ZIP
cd test_lambda && zip ../lambda.zip main.c && cd ..
echo "✓ Lambda creada"
echo ""

# PASO 2: Guardar lambda en el storage service
echo "2. Guardando lambda en storage..."
LAMBDA_RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/guardar_lambda \
  -F "file=@lambda.zip" \
  -F "id_owner=test_user" \
  -F "descripcion=Lambda de prueba para ejecución")

echo "Respuesta del storage:"
echo "$LAMBDA_RESPONSE" | jq '.'

# Extraer ID de lambda
ID_LAMBDA=$(echo "$LAMBDA_RESPONSE" | jq -r '.id_lambda')

if [ "$ID_LAMBDA" == "null" ] || [ -z "$ID_LAMBDA" ]; then
    echo "❌ Error: No se pudo obtener el ID de lambda"
    exit 1
fi

echo "✓ Lambda guardada con ID: $ID_LAMBDA"
echo ""

# PASO 3: Verificar que la lambda se guardó
echo "3. Verificando lambda..."
curl -s "http://localhost:8000/api/v1/get_list_lambdas_disponibles?id_owner=test_user" | jq '.'
echo ""

# PASO 4: Descargar el código de la lambda
echo "4. Descargando código de lambda..."
curl -s -o codigo.zip "http://localhost:8000/api/v1/get_codigo_lambda/${ID_LAMBDA}"

if [ ! -f codigo.zip ]; then
    echo "❌ Error: No se pudo descargar el código"
    exit 1
fi

echo "✓ Código descargado"
echo ""

# PASO 5: Crear archivo de datos de entrada
echo "5. Creando datos de entrada..."
mkdir datos
cat > datos/input.txt << 'EOF'
Esta es la primera línea de datos
Esta es la segunda línea de datos
Esta es la tercera línea de datos
EOF

cd datos && zip ../datos.zip input.txt && cd ..
echo "✓ Datos creados"
echo ""

# PASO 6: Crear encargo de ejecución
echo "6. Creando encargo de ejecución..."
echo "   Lambda ID: $ID_LAMBDA"
echo "   Enviando a: http://localhost:8001/api/v1/dejar_encargo"
echo ""

EXEC_RESPONSE=$(curl -s -X POST http://localhost:8001/api/v1/dejar_encargo \
  -F "id_lambda=${ID_LAMBDA}" \
  -F "codigo=@codigo.zip" \
  -F "datos=@datos.zip")

echo "Respuesta del execution service:"
echo "$EXEC_RESPONSE" | jq '.'

# Verificar si hay error
if echo "$EXEC_RESPONSE" | grep -q "detail"; then
    echo ""
    echo "❌ Error creando encargo"
    echo ""
    echo "Verificando logs del storage:"
    docker logs faas-storage-api --tail 20
    echo ""
    echo "Verificando logs del execution:"
    docker logs faas-execution-api --tail 20
    exit 1
fi

# Extraer ID de encargo
ID_ENCARGO=$(echo "$EXEC_RESPONSE" | jq -r '.id_encargo')

if [ "$ID_ENCARGO" == "null" ] || [ -z "$ID_ENCARGO" ]; then
    echo "❌ Error: No se pudo obtener el ID de encargo"
    exit 1
fi

echo "✓ Encargo creado con ID: $ID_ENCARGO"
echo ""

# PASO 7: Monitorear el estado del encargo
echo "7. Monitoreando ejecución (máximo 30 segundos)..."
for i in {1..15}; do
    sleep 2
    
    INFO=$(curl -s "http://localhost:8001/api/v1/get_encargo/${ID_ENCARGO}/info")
    STATUS=$(echo "$INFO" | jq -r '.status')
    
    printf "   [%2d/15] Estado: %-12s" "$i" "$STATUS"
    
    if [ "$STATUS" == "completed" ]; then
        echo " ✓"
        break
    elif [ "$STATUS" == "failed" ]; then
        echo " ❌"
        echo ""
        echo "Información del error:"
        echo "$INFO" | jq '.'
        break
    else
        echo ""
    fi
done
echo ""

# PASO 8: Obtener información detallada
echo "8. Información detallada del encargo:"
curl -s "http://localhost:8001/api/v1/get_encargo/${ID_ENCARGO}/info" | jq '.'
echo ""

# PASO 9: Descargar resultado
echo "9. Descargando resultado..."
HTTP_CODE=$(curl -s -w "%{http_code}" -o "resultado_${ID_ENCARGO}.zip" \
  "http://localhost:8001/api/v1/get_encargo/${ID_ENCARGO}")

if [ "$HTTP_CODE" == "200" ]; then
    echo "✓ Resultado descargado: resultado_${ID_ENCARGO}.zip"
    echo ""
    
    echo "Contenido del ZIP:"
    unzip -l "resultado_${ID_ENCARGO}.zip"
    echo ""
    
    echo "=== STDOUT (Salida estándar) ==="
    unzip -p "resultado_${ID_ENCARGO}.zip" stdout.txt 2>/dev/null || echo "(no disponible)"
    echo ""
    
    echo "=== STDERR (Errores) ==="
    unzip -p "resultado_${ID_ENCARGO}.zip" stderr.txt 2>/dev/null || echo "(no disponible)"
    echo ""
    
    echo "=== OUTPUT.TXT (Archivo generado) ==="
    unzip -p "resultado_${ID_ENCARGO}.zip" output.txt 2>/dev/null || echo "(no disponible)"
    echo ""
else
    echo "⚠ Resultado no disponible aún (HTTP $HTTP_CODE)"
    echo "   El encargo puede estar todavía ejecutándose"
    echo "   Puedes consultar el estado con:"
    echo "   curl http://localhost:8001/api/v1/get_encargo/${ID_ENCARGO}/info"
fi

# PASO 10: Estado del sistema
echo "10. Estado del sistema (¿está agobiado?):"
curl -s http://localhost:8001/api/v1/estas_agobiado | jq '.'
echo ""

# Resumen
echo "=== RESUMEN ==="
echo "Lambda ID:  $ID_LAMBDA"
echo "Encargo ID: $ID_ENCARGO"
echo ""
echo "Comandos útiles:"
echo "  Ver info:      curl http://localhost:8001/api/v1/get_encargo/${ID_ENCARGO}/info"
echo "  Descargar:     curl -O -J http://localhost:8001/api/v1/get_encargo/${ID_ENCARGO}"
echo "  Ver lambdas:   curl 'http://localhost:8000/api/v1/get_list_lambdas_disponibles?id_owner=test_user'"
echo ""

# Limpiar archivos temporales (opcional, comentar si quieres conservarlos)
# rm -rf test_lambda datos lambda.zip datos.zip codigo.zip

echo "✓ Test completado"