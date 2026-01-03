import docker
import os
import zipfile
import io
import time
import logging
import shutil
import tarfile
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
        """Compilar el código C copiando archivos al contenedor"""
        try:
            logger.info("=== INICIANDO COMPILACIÓN ===")
            
            # Listar archivos .c en el HOST
            all_files = os.listdir(codigo_dir)
            c_files = [f for f in all_files if f.endswith('.c')]
            
            if not c_files:
                return {"exit_code": 1, "output": f"No se encontraron archivos .c en: {all_files}"}
            
            logger.info(f"Archivos C en el host: {c_files}")
            
            # Crear tar con todos los archivos
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
                for file in all_files:
                    file_path = os.path.join(codigo_dir, file)
                    if os.path.isfile(file_path):
                        tar.add(file_path, arcname=file)
                        logger.info(f"  Agregando a TAR: {file}")
            
            tar_buffer.seek(0)
            logger.info("✓ Archivos empaquetados en TAR")
            
            # Crear comando de compilación
            c_files_str = ' '.join(c_files)
            
            compile_cmd = f"""#!/bin/bash
set -e
cd /codigo
echo "=== Archivos recibidos ==="
ls -la
echo ""
echo "=== Compilando: {c_files_str} ==="
gcc -o program {c_files_str} 2>&1
echo ""
echo "=== Resultado ==="
if [ -f program ]; then
    echo "✓ Ejecutable creado"
    ls -la program
    chmod +x program
else
    echo "✗ Ejecutable NO creado"
    exit 1
fi
"""
            
            container = None
            try:
                # Crear contenedor SIN iniciarlo
                container = self.docker_client.containers.create(
                    "gcc:latest",
                    command=["/bin/bash", "-c", compile_cmd],
                    network_mode='none',
                    user='root',
                    working_dir='/codigo'
                )
                
                logger.info(f"Contenedor creado: {container.id[:12]}")
                
                # Copiar archivos al contenedor
                container.put_archive('/codigo', tar_buffer.getvalue())
                logger.info("✓ Archivos copiados al contenedor")
                
                # Iniciar contenedor
                container.start()
                logger.info("Contenedor iniciado, esperando compilación...")
                
                # Esperar a que termine
                result = container.wait(timeout=30)
                exit_code = result['StatusCode']
                
                # Obtener logs
                logs = container.logs(stdout=True, stderr=True).decode('utf-8', errors='ignore')
                
                logger.info(f"Compilación terminó con exit code: {exit_code}")
                logger.info(f"Logs:\n{logs}")
                
                if exit_code == 0:
                    # Copiar el ejecutable de vuelta al host
                    try:
                        logger.info("Copiando ejecutable del contenedor al host...")
                        
                        # Obtener el archivo program del contenedor
                        bits, stat = container.get_archive('/codigo/program')
                        
                        # Extraer del tar
                        tar_stream = io.BytesIO()
                        for chunk in bits:
                            tar_stream.write(chunk)
                        tar_stream.seek(0)
                        
                        with tarfile.open(fileobj=tar_stream) as tar:
                            member = tar.getmember('program')
                            program_file = tar.extractfile(member)
                            
                            # Guardar en el host
                            program_path = os.path.join(codigo_dir, 'program')
                            with open(program_path, 'wb') as f:
                                f.write(program_file.read())
                            
                            os.chmod(program_path, 0o755)
                            logger.info("✓ Ejecutable copiado al host exitosamente")
                    
                    except Exception as e:
                        logger.error(f"Error copiando ejecutable: {e}", exc_info=True)
                        exit_code = 1
                        logs += f"\n\nError copiando ejecutable: {str(e)}"
                
                # Limpiar contenedor
                container.remove(force=True)
                logger.info("Contenedor de compilación eliminado")
                
                return {"exit_code": exit_code, "output": logs}
            
            except Exception as e:
                logger.error(f"Error durante compilación: {e}", exc_info=True)
                if container:
                    try:
                        logs = container.logs(stdout=True, stderr=True).decode('utf-8', errors='ignore')
                        container.remove(force=True)
                        return {"exit_code": 1, "output": f"{logs}\n\nException: {str(e)}"}
                    except:
                        pass
                return {"exit_code": 1, "output": str(e)}
        
        except Exception as e:
            logger.error(f"Exception en compilación: {e}", exc_info=True)
            return {"exit_code": 1, "output": str(e)}
    
    def _run_program(self, codigo_dir: str, datos_dir: str, output_dir: str) -> dict:
        """Ejecutar el programa compilado copiando archivos al contenedor"""
        try:
            logger.info("=== INICIANDO EJECUCIÓN ===")
            
            # Crear tar con el ejecutable
            tar_codigo = io.BytesIO()
            with tarfile.open(fileobj=tar_codigo, mode='w') as tar:
                program_path = os.path.join(codigo_dir, 'program')
                if not os.path.exists(program_path):
                    return {
                        "exit_code": -1,
                        "stdout": "",
                        "stderr": "Ejecutable 'program' no encontrado en el host"
                    }
                tar.add(program_path, arcname='program')
                logger.info("Ejecutable agregado a TAR")
            tar_codigo.seek(0)
            
            # Crear tar con los datos
            tar_datos = io.BytesIO()
            with tarfile.open(fileobj=tar_datos, mode='w') as tar:
                for file in os.listdir(datos_dir):
                    file_path = os.path.join(datos_dir, file)
                    if os.path.isfile(file_path):
                        tar.add(file_path, arcname=file)
                        logger.info(f"Dato agregado a TAR: {file}")
            tar_datos.seek(0)
            
            # Comando de ejecución
            exec_cmd = f"""#!/bin/bash
cd /datos
echo "=== Archivos de datos ==="
ls -la
echo ""
echo "=== Verificando programa ==="
ls -la /codigo/program
chmod +x /codigo/program
echo ""
echo "=== Ejecutando programa ==="
timeout {self.timeout}s /codigo/program
EXIT_CODE=$?
echo ""
echo "=== Resultado ==="
echo "Exit code: $EXIT_CODE"
echo "Archivos generados:"
ls -la
exit $EXIT_CODE
"""
            
            container = None
            try:
                # Crear contenedor
                container = self.docker_client.containers.create(
                    "gcc:latest",
                    command=["/bin/bash", "-c", exec_cmd],
                    network_mode='none',
                    user='root',
                    working_dir='/datos'
                )
                
                logger.info(f"Contenedor de ejecución creado: {container.id[:12]}")
                
                # Copiar archivos
                container.put_archive('/codigo', tar_codigo.getvalue())
                container.put_archive('/datos', tar_datos.getvalue())
                logger.info("✓ Archivos copiados al contenedor de ejecución")
                
                # Iniciar
                container.start()
                logger.info("Contenedor iniciado, esperando ejecución...")
                
                # Esperar
                result = container.wait(timeout=self.timeout + 5)
                exit_code = result['StatusCode']
                
                # Obtener logs
                logs = container.logs(stdout=True, stderr=True).decode('utf-8', errors='ignore')
                
                logger.info(f"Ejecución terminó con exit code: {exit_code}")
                logger.info(f"Output:\n{logs}")
                
                # Copiar archivos generados de vuelta
                try:
                    logger.info("Copiando archivos generados del contenedor...")
                    
                    bits, stat = container.get_archive('/datos')
                    tar_stream = io.BytesIO()
                    for chunk in bits:
                        tar_stream.write(chunk)
                    tar_stream.seek(0)
                    
                    # Extraer directamente al datos_dir, sobrescribiendo
                    with tarfile.open(fileobj=tar_stream) as tar:
                        # Extraer cada miembro individualmente
                        for member in tar.getmembers():
                            if member.isfile():
                                # Extraer a datos_dir
                                tar.extract(member, path=datos_dir)
                                logger.info(f"  Archivo copiado: {member.name}")
                    
                    logger.info("✓ Archivos generados copiados al host")
                
                except Exception as e:
                    logger.warning(f"No se pudieron copiar archivos generados: {e}")
                
                # Limpiar
                container.remove(force=True)
                logger.info("Contenedor de ejecución eliminado")
                
                return {
                    "exit_code": exit_code,
                    "stdout": logs,
                    "stderr": "" if exit_code == 0 else f"Exit code: {exit_code}"
                }
            
            except Exception as e:
                logger.error(f"Error durante ejecución: {e}", exc_info=True)
                if container:
                    try:
                        logs = container.logs(stdout=True, stderr=True).decode('utf-8', errors='ignore')
                        container.remove(force=True)
                        return {"exit_code": -1, "stdout": logs, "stderr": str(e)}
                    except:
                        pass
                return {"exit_code": -1, "stdout": "", "stderr": str(e)}
        
        except Exception as e:
            logger.error(f"Exception en ejecución: {e}", exc_info=True)
            return {"exit_code": -1, "stdout": "", "stderr": str(e)}
    
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