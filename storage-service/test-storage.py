#!/usr/bin/env python3
import requests
import zipfile
import io
import json

BASE_URL = "http://localhost:8000"

def test_storage():
    print("=== Test de Storage Service ===\n")
    
    # 1. Crear ZIP con main.c
    print("1. Creando ZIP con main.c...")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr('main.c', '''#include <stdio.h>

int main() {
    printf("Hello from Lambda!\\n");
    return 0;
}''')
        zip_file.writestr('utils.h', '''#ifndef UTILS_H
#define UTILS_H
void helper();
#endif''')
    
    zip_buffer.seek(0)
    print("✓ ZIP creado\n")
    
    # 2. Subir lambda
    print("2. Subiendo lambda...")
    files = {'file': ('test_lambda.zip', zip_buffer, 'application/zip')}
    data = {
        'id_owner': 'python_test_user',
        'descripcion': 'Lambda de prueba desde Python'
    }
    
    response = requests.post(f"{BASE_URL}/api/v1/guardar_lambda", files=files, data=data)
    
    if response.status_code == 200:
        lambda_data = response.json()
        print(f"✓ Lambda guardada:")
        print(json.dumps(lambda_data, indent=2))
        id_lambda = lambda_data['id_lambda']
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)
        return
    
    print()
    
    # 3. Listar lambdas
    print("3. Listando lambdas del owner...")
    response = requests.get(f"{BASE_URL}/api/v1/get_list_lambdas_disponibles", 
                           params={'id_owner': 'python_test_user'})
    
    if response.status_code == 200:
        lambdas = response.json()
        print(f"✓ Encontradas {len(lambdas)} lambdas:")
        print(json.dumps(lambdas, indent=2))
    
    print()
    
    # 4. Descargar código
    print("4. Descargando código lambda...")
    response = requests.get(f"{BASE_URL}/api/v1/get_codigo_lambda/{id_lambda}")
    
    if response.status_code == 200:
        print("✓ Código descargado")
        
        # Verificar contenido del ZIP
        zip_content = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_content, 'r') as zip_file:
            print("\n5. Contenido del ZIP:")
            for name in zip_file.namelist():
                print(f"  - {name}")
            
            print("\n6. Contenido de main.c:")
            main_c = zip_file.read('main.c').decode('utf-8')
            print(main_c)
        
        print("\n✓ ¡Todo funciona correctamente!")
    else:
        print(f"❌ Error descargando: {response.status_code}")
    
    print("\n=== Test completado ===")

if __name__ == "__main__":
    test_storage()