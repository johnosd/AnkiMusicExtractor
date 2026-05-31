from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .anki import slugify

_client = None


def init_db(url: str, key: str) -> None:
    """Inicializa o cliente Supabase para operações de banco de dados via REST."""
    global _client
    if not url or not key:
        return
    from supabase import create_client
    _client = create_client(url, key)


def is_configured() -> bool:
    return _client is not None


def _position_from_segment_id(segment_id: str) -> int:
    try:
        return int(segment_id.lstrip("p"))
    except (ValueError, AttributeError):
        return 0


def persist_job_to_db(
    job_id: str,
    mode: str,
    song_meta: Dict,
    segments: List[Dict],
) -> int:
    """Insere (ou substitui) uma música e seus cards via Supabase REST API."""
    if not _client:
        raise RuntimeError("DB não inicializado — chame init_db() primeiro.")

    artist = song_meta.get("artist") or ""
    title = song_meta.get("title") or ""
    album = song_meta.get("album") or ""
    now = int(time.time())
    tags = f"artist::{slugify(artist)} song::{slugify(title)}"

    song_data: Dict[str, Any] = {
        "job_id": job_id,
        "artist": artist,
        "title": title,
        "album": album,
        "artist_slug": slugify(artist),
        "title_slug": slugify(title),
        "duration_s": song_meta.get("duration_s"),
        "mode": mode,
        "created_at": now,
    }

    existing = _client.table("songs").select("id").eq("job_id", job_id).execute()
    if existing.data:
        song_id: int = existing.data[0]["id"]
        _client.table("songs").update(song_data).eq("job_id", job_id).execute()
        _client.table("cards").delete().eq("song_id", song_id).execute()
    else:
        result = _client.table("songs").insert(song_data).execute()
        song_id = result.data[0]["id"]

    card_rows = []
    for seg in segments:
        seg_id = seg.get("id", "")
        audio_file = seg.get("audio_file") or (f"{seg_id}.mp3" if seg_id else "")
        card_rows.append({
            "song_id": song_id,
            "segment_id": seg_id,
            "position": _position_from_segment_id(seg_id),
            "start_ms": int(seg.get("start_ms", 0)),
            "end_ms": int(seg.get("end_ms", 0)),
            "duration_ms": int(seg.get("duration_ms", 0)),
            "audio_file": audio_file,
            "audio_url": seg.get("audio_url") or "",
            "l2_text": (seg.get("l2_text") or "").strip(),
            "l2_language": (seg.get("l2_language") or "").strip(),
            "l1_translation": (seg.get("l1_translation") or "").strip(),
            "tags": tags,
            "created_at": now,
        })

    if card_rows:
        _client.table("cards").insert(card_rows).execute()

    return song_id


def find_cached_song(artist_slug: str, title_slug: str) -> Optional[Dict]:
    """Retorna o song mais recente com mesmo artist/title que tenha cards, ou None."""
    if not _client:
        return None
    result = (
        _client.table("songs")
        .select("*")
        .eq("artist_slug", artist_slug)
        .eq("title_slug", title_slug)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    song = result.data[0]
    count_result = (
        _client.table("cards")
        .select("id", count="exact")
        .eq("song_id", song["id"])
        .execute()
    )
    if not (count_result.count and count_result.count > 0):
        return None
    return song


def delete_song_from_db(job_id: str) -> bool:
    """Remove song e cards do banco. Retorna True se a música existia."""
    if not _client:
        return False
    song_result = _client.table("songs").select("id").eq("job_id", job_id).execute()
    if not song_result.data:
        return False
    song_id = song_result.data[0]["id"]
    _client.table("cards").delete().eq("song_id", song_id).execute()
    _client.table("songs").delete().eq("job_id", job_id).execute()
    return True


def list_songs_from_db(limit: int = 50, offset: int = 0) -> List[Dict]:
    if not _client:
        return []
    result = (
        _client.table("songs")
        .select("*")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return result.data or []


def get_song_cards_from_db(job_id: str) -> Optional[Dict]:
    if not _client:
        return None
    song_result = _client.table("songs").select("*").eq("job_id", job_id).execute()
    if not song_result.data:
        return None
    song = song_result.data[0]
    cards_result = (
        _client.table("cards")
        .select("*")
        .eq("song_id", song["id"])
        .order("position")
        .execute()
    )
    return {"song": song, "cards": cards_result.data or []}
