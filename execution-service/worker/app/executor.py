import docker
import os
import zipfile
import io
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CodeExecutor:
    def __init__(self, timeout_seconds=30, max_memory_mb=512):
        self.docker_client = docker.from_env()
        self.timeout = timeout_seconds
        self.max_memory = max_memory_mb * 1024 * 1024  # Convertir a bytes
    
    def execute(self, id_encargo: str, codigo_zip: bytes, datos_zip: bytes) -> dict:
        """
        Ejecutar código C en un contenedor Docker aislado.
        """
        work_dir = f"/tmp/faas-exec-{id_encargo}"
        
        try:
            # Crear directorio de trabajo
            Path(work_dir).mkdir(parents=True, exist_ok=True)
            codigo_dir = f"{work_dir}/codigo"
            datos_dir = f"{work_dir}/datos"
            output_dir = f"{work_dir}/output"
            
            Path(codigo_dir).mkdir(exist_ok=True)
            Path(datos_dir).mkdir(exist_ok=True)
            Path(output_dir).mkdir(exist_ok=True)
            
            # Extraer codigo.zip
            with zipfile.ZipFile(io.BytesIO(codigo_zip)) as zf:
                zf.extractall(codigo_dir)
            
            # Extraer datos.zip
            with zipfile.ZipFile(io.BytesIO(datos_zip)) as zf:
                zf.extractall(datos_dir)
            
            # Verificar que existe main.c
            main_c_path = f"{codigo_dir}/main.c"
            if not os.path.exists(main_c_path):
                return {
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "Error: main.c no encontrado en codigo.zip",
                    "execution_time_ms": 0,
                    "output_zip": None
                }
            
            # Crear script de compilación y ejecución
            script_content = f"""#!/bin/bash
set -e
cd /codigo
gcc -o program main.c *.c 2>/output/compile.log || exit 1
cd /datos
timeout {self.timeout}s /codigo/program > /output/stdout.txt 2>/output/stderr.txt
echo $? > /output/exit_code.txt
"""
            
            script_path = f"{work_dir}/run.sh"
            with open(script_path, 'w') as f:
                f.write(script_content)
            os.chmod(script_path, 0o755)
            
            # Ejecutar en Docker
            start_time = time.time()
            
            container = self.docker_client.containers.run(
                "gcc:latest",
                command="/bin/bash /work/run.sh",
                volumes={
                    codigo_dir: {'bind': '/codigo', 'mode': 'ro'},
                    datos_dir: {'bind': '/datos', 'mode': 'rw'},
                    output_dir: {'bind': '/output', 'mode': 'rw'},
                    script_path: {'bind': '/work/run.sh', 'mode': 'ro'}
                },
                mem_limit=self.max_memory,
                network_mode='none',
                remove=False,
                detach=True,
                security_opt=['no-new-privileges'],
                cap_drop=['ALL']
            )
            
            # Esperar a que termine
            result = container.wait(timeout=self.timeout + 5)
            execution_time = int((time.time() - start_time) * 1000)
            
            # Leer resultados
            stdout = self._read_file(f"{output_dir}/stdout.txt")
            stderr = self._read_file(f"{output_dir}/stderr.txt")
            exit_code_str = self._read_file(f"{output_dir}/exit_code.txt")
            
            try:
                exit_code = int(exit_code_str.strip()) if exit_code_str else result['StatusCode']
            except:
                exit_code = result['StatusCode']
            
            # Crear ZIP con resultados
            output_zip = self._create_output_zip(output_dir)
            
            # Limpiar
            container.remove(force=True)
            
            return {
                "success": exit_code == 0,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "execution_time_ms": execution_time,
                "output_zip": output_zip
            }
        
        except docker.errors.ContainerError as e:
            logger.error(f"Container error: {e}")
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Error de contenedor: {str(e)}",
                "execution_time_ms": 0,
                "output_zip": None
            }
        
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Error de ejecución: {str(e)}",
                "execution_time_ms": 0,
                "output_zip": None
            }
        
        finally:
            # Limpiar directorio de trabajo
            import shutil
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except:
                pass
    
    def _read_file(self, path: str) -> str:
        """Leer contenido de un archivo"""
        try:
            with open(path, 'r') as f:
                return f.read()
        except:
            return ""
    
    def _create_output_zip(self, output_dir: str) -> bytes:
        """Crear ZIP con archivos de salida"""
        try:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arc_name = os.path.relpath(file_path, output_dir)
                        zf.write(file_path, arc_name)
            
            return zip_buffer.getvalue()
        except Exception as e:
            logger.error(f"Error creating output zip: {e}")
            return None