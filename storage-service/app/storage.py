from minio import Minio
from minio.error import S3Error
import io
from config import settings

class MinIOStorage:
    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure
        )
        self._ensure_buckets()
    
    def _ensure_buckets(self):
        """Crear buckets si no existen"""
        buckets = [
            settings.lambdas_bucket,
            settings.encargos_input_bucket,
            settings.encargos_result_bucket
        ]
        for bucket in buckets:
            try:
                if not self.client.bucket_exists(bucket):
                    self.client.make_bucket(bucket)
            except S3Error as e:
                print(f"Error creating bucket {bucket}: {e}")
    
    def upload_file(self, bucket: str, object_name: str, data: bytes, 
                   content_type: str = "application/zip") -> bool:
        """Subir archivo a MinIO"""
        try:
            self.client.put_object(
                bucket,
                object_name,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type
            )
            return True
        except S3Error as e:
            print(f"Error uploading file: {e}")
            return False
    
    def download_file(self, bucket: str, object_name: str) -> bytes:
        """Descargar archivo de MinIO"""
        try:
            response = self.client.get_object(bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            print(f"Error downloading file: {e}")
            return None
    
    def delete_file(self, bucket: str, object_name: str) -> bool:
        """Eliminar archivo de MinIO"""
        try:
            self.client.remove_object(bucket, object_name)
            return True
        except S3Error as e:
            print(f"Error deleting file: {e}")
            return False

storage_client = MinIOStorage()