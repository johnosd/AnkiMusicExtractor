from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


class LyricsError(RuntimeError):
    pass


@dataclass(frozen=True)
class LyricLine:
    text: str
    start_ms: int
    end_ms: int


_LRC_TS_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
_LRC_META_RE = re.compile(r"^\[[a-zA-Z]{2,}:[^\]]*\]\s*$")


def parse_lrc(
    lrc_text: str,
    *,
    total_duration_ms: Optional[int] = None,
    max_line_ms: int = 10000,
) -> List[LyricLine]:
    """Parse LRC text into a sorted list of LyricLine.

    end_ms of each line is min(next_start, start + max_line_ms, total_duration_ms).
    Lines with empty text are dropped (typical instrumental markers).
    Metadata tags like [ar:...], [ti:...], [length:...] are skipped.
    """
    timed: List[tuple[int, str]] = []
    for raw in lrc_text.splitlines():
        if _LRC_META_RE.match(raw):
            continue
        stamps = list(_LRC_TS_RE.finditer(raw))
        if not stamps:
            continue
        last_end = stamps[-1].end()
        text = raw[last_end:].strip()
        if not text:
            continue
        for m in stamps:
            mins = int(m.group(1))
            secs = int(m.group(2))
            frac = (m.group(3) or "0").ljust(3, "0")[:3]
            ms_frac = int(frac)
            start_ms = (mins * 60 + secs) * 1000 + ms_frac
            timed.append((start_ms, text))

    timed.sort(key=lambda t: t[0])

    out: List[LyricLine] = []
    for i, (start, text) in enumerate(timed):
        if i + 1 < len(timed):
            next_start = timed[i + 1][0]
        else:
            next_start = total_duration_ms if total_duration_ms is not None else (start + max_line_ms)
        end = min(next_start, start + max_line_ms)
        if total_duration_ms is not None:
            end = min(end, total_duration_ms)
        if end <= start:
            end = start + 500  # safety minimum
        out.append(LyricLine(text=text, start_ms=start, end_ms=end))
    return out


def fetch_lyrics(
    artist: str,
    title: str,
    *,
    album: str = "",
    duration_s: Optional[float] = None,
    cache_dir: Optional[Path] = None,
) -> Optional[str]:
    """Fetch synced LRC lyrics. Returns LRC text or None when no synced lyrics exist.

    Disk-cached by sha1(artist|title|album). plainLyrics-only results are NOT cached
    so a later attempt with better metadata can still find synced lyrics.
    """
    cache_key = _cache_key(artist, title, album)
    if cache_dir:
        cached = cache_dir / f"{cache_key}.lrc"
        if cached.exists():
            return cached.read_text(encoding="utf-8")

    lrc = _fetch_lrclib(artist, title, album, duration_s)

    if lrc and cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{cache_key}.lrc").write_text(lrc, encoding="utf-8")

    return lrc


def _fetch_lrclib(
    artist: str,
    title: str,
    album: str,
    duration_s: Optional[float],
) -> Optional[str]:
    try:
        import httpx
    except Exception as e:
        raise LyricsError("Dependência 'httpx' não encontrada. Rode: pip install -r requirements.txt") from e

    headers = {"User-Agent": "music-phrase-segmenter/0.3 (+https://github.com/local)"}

    params = {"artist_name": artist, "track_name": title}
    if album:
        params["album_name"] = album
    if duration_s:
        params["duration"] = int(round(duration_s))

    try:
        with httpx.Client(timeout=30.0, headers=headers) as client:
            r = client.get("https://lrclib.net/api/get", params=params)
            if r.status_code == 200:
                data = r.json()
                synced = (data or {}).get("syncedLyrics")
                if isinstance(synced, str) and synced.strip():
                    return synced

            r = client.get(
                "https://lrclib.net/api/search",
                params={"artist_name": artist, "track_name": title},
            )
            if r.status_code == 200:
                results = r.json() or []
                for item in results:
                    synced = (item or {}).get("syncedLyrics")
                    if isinstance(synced, str) and synced.strip():
                        return synced
    except Exception as e:
        raise LyricsError(f"Falha ao consultar LRCLib: {e}") from e

    return None


def _cache_key(artist: str, title: str, album: str) -> str:
    raw = f"{artist.lower().strip()}|{title.lower().strip()}|{album.lower().strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
