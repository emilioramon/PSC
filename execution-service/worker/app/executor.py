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
            
            # Guardar stdout y stderr en output_dir
            with open(f"{output_dir}/stdout.txt", 'w') as f:
                f.write(exec_result['stdout'])
            with open(f"{output_dir}/stderr.txt", 'w') as f:
                f.write(exec_result['stderr'])
            with open(f"{output_dir}/exit_code.txt", 'w') as f:
                f.write(str(exec_result['exit_code']))
            with open(f"{output_dir}/compile.log", 'w') as f:
                f.write(compile_result['output'])
            
            # CRÍTICO: Copiar TODOS los archivos de datos_dir a output_dir
            # Estos archivos fueron actualizados por el programa durante la ejecución
            logger.info(f"Copiando archivos generados de {datos_dir} a {output_dir}...")
            files_copied = 0
            for file in os.listdir(datos_dir):
                src = os.path.join(datos_dir, file)
                if os.path.isfile(src):
                    dst = os.path.join(output_dir, file)
                    try:
                        shutil.copy2(src, dst)
                        files_copied += 1
                        file_size = os.path.getsize(src)
                        logger.info(f"  ✓ Copiado: {file} ({file_size} bytes)")
                    except Exception as e:
                        logger.warning(f"  ✗ No se pudo copiar {file}: {e}")
            
            logger.info(f"✓ {files_copied} archivos copiados a output_dir")
            
            # Verificar qué hay en output_dir antes de crear el ZIP
            output_files = os.listdir(output_dir)
            logger.info(f"Archivos en output_dir antes de crear ZIP: {output_files}")
            
            # Crear ZIP con resultados
            output_zip = self._create_output_zip(output_dir)
            
            if output_zip:
                logger.info(f"✓ ZIP creado exitosamente: {len(output_zip)} bytes")
            else:
                logger.error("✗ ERROR: No se pudo crear el ZIP de salida")
            
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
            c_files_str = ' '.join(c_files)
            
            # Crear tar con todos los archivos CON EL PATH codigo/
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
                for file in all_files:
                    file_path = os.path.join(codigo_dir, file)
                    if os.path.isfile(file_path):
                        # IMPORTANTE: agregar con el prefijo codigo/
                        tar.add(file_path, arcname=f'codigo/{file}')
                        logger.info(f"  Agregando a TAR: codigo/{file}")
            
            tar_buffer.seek(0)
            logger.info("✓ Archivos empaquetados en TAR")
            
            # Comando de compilación
            compile_cmd = f"""#!/bin/bash
set -e
cd /codigo
echo "=== Archivos en /codigo ==="
ls -la
echo ""
echo "=== Compilando: {c_files_str} ==="
gcc -o program {c_files_str} 2>&1
echo ""
echo "=== Verificando resultado ==="
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
                # Crear contenedor
                container = self.docker_client.containers.create(
                    "gcc:latest",
                    command=["/bin/bash", "-c", compile_cmd],
                    network_mode='none',
                    user='root'
                )
                
                logger.info(f"Contenedor creado: {container.id[:12]}")
                
                # Copiar archivos al contenedor
                container.put_archive('/', tar_buffer.getvalue())
                logger.info("✓ Archivos copiados al contenedor en /codigo")
                
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
            
            # Verificar que existe el ejecutable
            program_path = os.path.join(codigo_dir, 'program')
            if not os.path.exists(program_path):
                return {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "Ejecutable 'program' no encontrado en el host"
                }
            
            # Crear tar con el ejecutable CON PATH codigo/
            tar_codigo = io.BytesIO()
            with tarfile.open(fileobj=tar_codigo, mode='w') as tar:
                tar.add(program_path, arcname='codigo/program')
                logger.info("Ejecutable agregado a TAR como codigo/program")
            tar_codigo.seek(0)
            
            # Crear tar con los datos CON PATH datos/
            tar_datos = io.BytesIO()
            with tarfile.open(fileobj=tar_datos, mode='w') as tar:
                for file in os.listdir(datos_dir):
                    file_path = os.path.join(datos_dir, file)
                    if os.path.isfile(file_path):
                        tar.add(file_path, arcname=f'datos/{file}')
                        logger.info(f"Dato agregado a TAR: datos/{file}")
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
                    user='root'
                )
                
                logger.info(f"Contenedor de ejecución creado: {container.id[:12]}")
                
                # Copiar archivos (extraen automáticamente creando /codigo y /datos)
                container.put_archive('/', tar_codigo.getvalue())
                container.put_archive('/', tar_datos.getvalue())
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
                
                # CRÍTICO: Copiar archivos generados de vuelta al host
                logger.info("Copiando archivos generados del contenedor al host...")
                try:
                    bits, stat = container.get_archive('/datos')
                    tar_stream = io.BytesIO()
                    for chunk in bits:
                        tar_stream.write(chunk)
                    tar_stream.seek(0)
                    
                    files_extracted = 0
                    # Extraer archivos del tar directamente a datos_dir
                    with tarfile.open(fileobj=tar_stream) as tar:
                        for member in tar.getmembers():
                            if member.isfile():
                                # El nombre puede venir como 'datos/file' o solo 'file'
                                filename = os.path.basename(member.name)
                                
                                # Extraer el archivo
                                file_content = tar.extractfile(member).read()
                                
                                # Guardar en datos_dir (sobrescribe los originales)
                                output_path = os.path.join(datos_dir, filename)
                                with open(output_path, 'wb') as f:
                                    f.write(file_content)
                                
                                files_extracted += 1
                                logger.info(f"  ✓ Archivo extraído: {filename} ({len(file_content)} bytes)")
                    
                    logger.info(f"✓ {files_extracted} archivos copiados del contenedor al host")
                
                except Exception as e:
                    logger.error(f"✗ Error copiando archivos generados: {e}", exc_info=True)
                
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
            logger.info(f"Archivos disponibles para ZIP: {files_in_dir}")
            
            if not files_in_dir:
                logger.warning("No hay archivos en output_dir, creando ZIP vacío")
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr('empty.txt', 'No output files generated')
                return zip_buffer.getvalue()
            
            zip_buffer = io.BytesIO()
            total_size = 0
            file_count = 0
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arc_name = os.path.relpath(file_path, output_dir)
                        
                        with open(file_path, 'rb') as f:
                            content = f.read()
                            zf.writestr(arc_name, content)
                            total_size += len(content)
                            file_count += 1
                            logger.info(f"  + {arc_name} ({len(content)} bytes)")
            
            zip_bytes = zip_buffer.getvalue()
            logger.info(f"✓ ZIP creado: {file_count} archivos, {total_size} bytes descomprimidos, {len(zip_bytes)} bytes comprimidos")
            
            return zip_bytes
        
        except Exception as e:
            logger.error(f"Error creando ZIP: {e}", exc_info=True)
            return None