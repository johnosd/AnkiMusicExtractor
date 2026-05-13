from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SongInfo:
    artist: str
    title: str
    album: str = ""
    duration_s: Optional[float] = None
    source: str = "unknown"  # "id3" | "manual" | "id3+manual"


def identify(
    input_file: Path,
    *,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    album: Optional[str] = None,
) -> Optional[SongInfo]:
    """Identify the song. Returns None if artist/title cannot be determined.

    Precedence: manual fields > ID3 tags. Manual fields can partially override ID3.
    """
    manual_artist = (artist or "").strip()
    manual_title = (title or "").strip()
    manual_album = (album or "").strip()

    id3 = _read_id3(input_file)

    final_artist = manual_artist or (id3.artist if id3 else "")
    final_title = manual_title or (id3.title if id3 else "")
    final_album = manual_album or (id3.album if id3 else "")
    duration = id3.duration_s if id3 else None

    if not final_artist or not final_title:
        return None

    if manual_artist or manual_title:
        source = "id3+manual" if id3 else "manual"
    else:
        source = "id3"

    return SongInfo(
        artist=final_artist,
        title=final_title,
        album=final_album,
        duration_s=duration,
        source=source,
    )


def _read_id3(path: Path) -> Optional[SongInfo]:
    try:
        from mutagen import File as MutagenFile  # type: ignore
    except Exception:
        return None

    try:
        mf = MutagenFile(str(path), easy=True)
    except Exception:
        return None

    if mf is None:
        return None

    def _first(key: str) -> str:
        try:
            val = mf.get(key)
            if isinstance(val, list) and val:
                return str(val[0]).strip()
        except Exception:
            pass
        return ""

    artist = _first("artist")
    title = _first("title")
    album = _first("album")
    duration = None
    info = getattr(mf, "info", None)
    if info is not None:
        try:
            duration = float(info.length)
        except Exception:
            duration = None

    if not artist and not title:
        return None

    return SongInfo(artist=artist, title=title, album=album, duration_s=duration, source="id3")
