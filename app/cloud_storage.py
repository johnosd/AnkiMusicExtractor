from __future__ import annotations

from pathlib import Path
from typing import List, Optional

_client = None
_bucket: str = "segments"


def init_storage(url: str, key: str, bucket: str) -> None:
    """Inicializa o cliente Supabase Storage. Chamado no startup da aplicação."""
    global _client, _bucket
    if not url or not key:
        return
    from supabase import create_client
    _client = create_client(url, key)
    _bucket = bucket


def is_configured() -> bool:
    return _client is not None


def upload_job_segments(segments_dir: Path, segments: List[dict], job_id: str) -> None:
    """
    Faz upload de cada MP3 de segmento para o Supabase Storage.
    Define seg['audio_url'] no dict in-place após upload bem-sucedido.
    Falhas individuais ficam em seg['audio_upload_error'] e não interrompem o job.
    """
    if not is_configured():
        return

    for seg in segments:
        filename = seg.get("audio_file", "")
        if not filename:
            continue
        local = segments_dir / filename
        if not local.exists():
            continue
        storage_path = f"{job_id}/{filename}"
        try:
            with open(local, "rb") as f:
                _client.storage.from_(_bucket).upload(
                    storage_path,
                    f,
                    file_options={"content-type": "audio/mpeg", "upsert": "true"},
                )
            seg["audio_url"] = (
                f"{_client.supabase_url}/storage/v1/object/public/{_bucket}/{storage_path}"
            )
        except Exception as e:
            seg["audio_upload_error"] = str(e)


def delete_job_segments(job_id: str) -> None:
    """Remove todos os arquivos do job no Supabase Storage."""
    if not is_configured():
        return
    try:
        files = _client.storage.from_(_bucket).list(job_id)
        paths = [f"{job_id}/{f['name']}" for f in (files or []) if f.get("name")]
        if paths:
            _client.storage.from_(_bucket).remove(paths)
    except Exception:
        pass
