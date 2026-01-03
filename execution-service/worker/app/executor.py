import docker
import os
import zipfile
import io
import time
import logging
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CodeExecutor:
    def __init__(self, timeout_seconds=30, max_memory_mb=512):
        self.docker_client = docker.from_env()
        self.timeout = timeout_seconds
        self.max_memory = max_memory_mb * 1024 * 1024
    
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
            
            for d in [codigo_dir, datos_dir, output_dir]:
                Path(d).mkdir(exist_ok=True)
            
            # Extraer codigo.zip
            logger.info(f"Extrayendo codigo.zip para {id_encargo}")
            with zipfile.ZipFile(io.BytesIO(codigo_zip)) as zf:
                zf.extractall(codigo_dir)
            
            logger.info(f"Archivos extraídos en codigo: {os.listdir(codigo_dir)}")
            
            # Extraer datos.zip
            logger.info(f"Extrayendo datos.zip para {id_encargo}")
            with zipfile.ZipFile(io.BytesIO(datos_zip)) as zf:
                zf.extractall(datos_dir)
            
            logger.info(f"Archivos extraídos en datos: {os.listdir(datos_dir)}")
            
            # Verificar que existe main.c
            main_c_path = f"{codigo_dir}/main.c"
            if not os.path.exists(main_c_path):
                logger.error(f"main.c no encontrado en {codigo_dir}")
                return self._create_error_result("main.c no encontrado en codigo.zip")
            
            logger.info(f"✓ main.c encontrado, iniciando ejecución...")
            start_time = time.time()
            
            # PASO 1: Compilar
            compile_result = self._compile_code(codigo_dir, output_dir)
            if compile_result['exit_code'] != 0:
                execution_time = int((time.time() - start_time) * 1000)
                logger.error(f"Error de compilación: {compile_result['output']}")
                
                # Guardar log de compilación
                with open(f"{output_dir}/compile.log", 'w') as f:
                    f.write(compile_result['output'])
                
                return {
                    "success": False,
                    "exit_code": compile_result['exit_code'],
                    "stdout": "",
                    "stderr": f"Error de compilación:\n{compile_result['output']}",
                    "execution_time_ms": execution_time,
                    "output_zip": self._create_output_zip(output_dir)
                }
            
            logger.info("✓ Compilación exitosa")
            
            # PASO 2: Ejecutar
            exec_result = self._run_program(codigo_dir, datos_dir, output_dir)
            execution_time = int((time.time() - start_time) * 1000)
            
            logger.info(f"✓ Ejecución completada: exit_code={exec_result['exit_code']}")
            
            # Guardar stdout y stderr
            with open(f"{output_dir}/stdout.txt", 'w') as f:
                f.write(exec_result['stdout'])
            with open(f"{output_dir}/stderr.txt", 'w') as f:
                f.write(exec_result['stderr'])
            with open(f"{output_dir}/exit_code.txt", 'w') as f:
                f.write(str(exec_result['exit_code']))
            with open(f"{output_dir}/compile.log", 'w') as f:
                f.write(compile_result['output'])
            
            # Copiar archivos generados en datos_dir a output_dir
            for file in os.listdir(datos_dir):
                src = os.path.join(datos_dir, file)
                if os.path.isfile(src):
                    # Copiar todos los archivos (incluyendo los generados)
                    dst = os.path.join(output_dir, file)
                    try:
                        shutil.copy2(src, dst)
                        logger.info(f"Copiado: {file}")
                    except Exception as e:
                        logger.warning(f"No se pudo copiar {file}: {e}")
            
            # Crear ZIP con resultados
            output_zip = self._create_output_zip(output_dir)
            
            logger.info(f"✓ Ejecución completada: exit_code={exec_result['exit_code']}, time={execution_time}ms, zip_size={len(output_zip) if output_zip else 0}")
            
            return {
                "success": exec_result['exit_code'] == 0,
                "exit_code": exec_result['exit_code'],
                "stdout": exec_result['stdout'],
                "stderr": exec_result['stderr'],
                "execution_time_ms": execution_time,
                "output_zip": output_zip
            }
        
        except Exception as e:
            logger.error(f"Execution error: {e}", exc_info=True)
            return self._create_error_result(str(e))
        
        finally:
            # Limpiar directorio de trabajo
            try:
                logger.info(f"Limpiando directorio {work_dir}")
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f"Error limpiando: {e}")
    
    def _compile_code(self, codigo_dir: str, output_dir: str) -> dict:
        """Compilar el código C"""
        try:
            logger.info("=== INICIANDO COMPILACIÓN ===")
            
            # Listar archivos .c
            all_files = os.listdir(codigo_dir)
            c_files = [f for f in all_files if f.endswith('.c')]
            
            if not c_files:
                return {"exit_code": 1, "output": f"No se encontraron archivos .c en: {all_files}"}
            
            logger.info(f"Archivos C encontrados: {c_files}")
            logger.info(f"Todos los archivos: {all_files}")
            
            # Crear comando de compilación
            c_files_str = ' '.join(c_files)
            
            # Comando multi-línea para mejor debug
            compile_cmd = f"""
set -e
cd /codigo
echo "Directorio actual: $(pwd)"
echo "Archivos disponibles: $(ls -la)"
echo "Compilando: {c_files_str}"
gcc -o program {c_files_str} 2>&1
echo "Compilación completada"
ls -la program
"""
            
            logger.info(f"Ejecutando compilación...")
            
            container = self.docker_client.containers.run(
                "gcc:latest",
                command=["/bin/bash", "-c", compile_cmd],
                volumes={
                    codigo_dir: {'bind': '/codigo', 'mode': 'rw'}
                },
                remove=True,
                detach=False,
                network_mode='none'
            )
            
            output = container.decode('utf-8', errors='ignore')
            logger.info(f"Output de compilación:\n{output}")
            
            # Verificar ejecutable
            program_path = os.path.join(codigo_dir, 'program')
            if os.path.exists(program_path):
                os.chmod(program_path, 0o755)
                logger.info("✓ Ejecutable creado y con permisos")
                return {"exit_code": 0, "output": output}
            else:
                files_after = os.listdir(codigo_dir)
                logger.error(f"✗ Ejecutable NO creado. Archivos después: {files_after}")
                return {"exit_code": 1, "output": f"Ejecutable no creado\nOutput: {output}\nArchivos: {files_after}"}
        
        except docker.errors.ContainerError as e:
            error_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            logger.error(f"ContainerError en compilación: {error_msg}")
            return {"exit_code": e.exit_status, "output": error_msg}
        
        except Exception as e:
            logger.error(f"Exception en compilación: {e}", exc_info=True)
            return {"exit_code": 1, "output": str(e)}
    
    def _run_program(self, codigo_dir: str, datos_dir: str, output_dir: str) -> dict:
        """Ejecutar el programa compilado"""
        try:
            logger.info("=== INICIANDO EJECUCIÓN ===")
            
            exec_cmd = f"""
set -e
cd /datos
echo "Directorio actual: $(pwd)"
echo "Archivos disponibles: $(ls -la)"
echo "Ejecutando programa..."
timeout {self.timeout}s /codigo/program
echo "Programa terminado"
"""
            
            container = self.docker_client.containers.run(
                "gcc:latest",
                command=["/bin/bash", "-c", exec_cmd],
                volumes={
                    codigo_dir: {'bind': '/codigo', 'mode': 'ro'},
                    datos_dir: {'bind': '/datos', 'mode': 'rw'}
                },
                mem_limit=self.max_memory,
                network_mode='none',
                remove=True,
                detach=False,
                security_opt=['no-new-privileges'],
                cap_drop=['ALL']
            )
            
            output = container.decode('utf-8', errors='ignore')
            logger.info(f"✓ Programa ejecutado exitosamente")
            logger.info(f"Output ({len(output)} chars):\n{output}")
            
            return {
                "exit_code": 0,
                "stdout": output,
                "stderr": ""
            }
        
        except docker.errors.ContainerError as e:
            logger.warning(f"Programa terminó con exit code {e.exit_status}")
            stdout = e.stdout.decode('utf-8', errors='ignore') if e.stdout else ""
            stderr = e.stderr.decode('utf-8', errors='ignore') if e.stderr else ""
            
            logger.info(f"STDOUT: {stdout}")
            logger.info(f"STDERR: {stderr}")
            
            return {
                "exit_code": e.exit_status,
                "stdout": stdout,
                "stderr": stderr
            }
        
        except Exception as e:
            logger.error(f"Exception en ejecución: {e}", exc_info=True)
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e)
            }
    
    def _create_error_result(self, error_msg: str) -> dict:
        """Crear resultado de error"""
        return {
            "success": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": error_msg,
            "execution_time_ms": 0,
            "output_zip": None
        }
    
    def _create_output_zip(self, output_dir: str) -> bytes:
        """Crear ZIP con archivos de salida"""
        try:
            if not os.path.exists(output_dir):
                logger.error(f"Output dir {output_dir} no existe")
                return None
            
            files_in_dir = os.listdir(output_dir)
            logger.info(f"Creando ZIP con archivos: {files_in_dir}")
            
            if not files_in_dir:
                logger.warning("No hay archivos para el ZIP")
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr('empty.txt', 'No output files generated')
                return zip_buffer.getvalue()
            
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arc_name = os.path.relpath(file_path, output_dir)
                        
                        with open(file_path, 'rb') as f:
                            content = f.read()
                            zf.writestr(arc_name, content)
                            logger.info(f"  + {arc_name} ({len(content)} bytes)")
            
            zip_bytes = zip_buffer.getvalue()
            logger.info(f"✓ ZIP creado: {len(zip_bytes)} bytes totales")
            
            return zip_bytes
        
        except Exception as e:
            logger.error(f"Error creando ZIP: {e}", exc_info=True)
            return None
        