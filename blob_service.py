from azure.storage.blob import BlobServiceClient, ContentSettings
from config import settings


def _container():
    client = BlobServiceClient.from_connection_string(settings.storage_conn)
    return client.get_container_client(settings.storage_container)


def upload_cv(file_name: str, data: bytes) -> None:
    # overwrite=True بيمسح الـ metadata القديمة، يعني إعادة رفع ملف مرفوض بتفتح له فرصة جديدة
    _container().upload_blob(
        name=file_name,
        data=data,
        overwrite=True,
        content_settings=ContentSettings(content_type="application/pdf"),
    )


def list_cvs() -> list[str]:
    return [b.name for b in _container().list_blobs()]


def download_cv(file_name: str) -> bytes:
    return _container().download_blob(file_name).readall()


# ----- (جديد) إدارة الملفات المرفوضة -----
def list_rejected() -> dict[str, str]:
    """اسم الملف المرفوض ← الـ hash اللي اترفض عليه."""
    out = {}
    for b in _container().list_blobs(include=["metadata"]):
        md = b.metadata or {}
        if md.get("rejected_hash"):
            out[b.name] = md["rejected_hash"]
    return out


def mark_rejected(file_name: str, file_hash: str) -> None:
    _container().get_blob_client(file_name).set_blob_metadata(
        {"rejected_hash": file_hash, "reason": "not_a_cv"}
    )


def clear_rejected(file_name: str) -> None:
    _container().get_blob_client(file_name).set_blob_metadata({})


def delete_cv_blob(file_name: str) -> None:
    _container().delete_blob(file_name)