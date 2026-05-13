from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from typing import Dict, List


def slugify(s: str) -> str:
    """ASCII-only slug: lowercase, alphanumerics + dashes, no doubles.

    Strips accents via NFKD so filenames stay portable across Anki on
    Windows/macOS/Linux/Android. Returns "unknown" for empty input.
    """
    normalized = unicodedata.normalize("NFKD", s.strip())
    out = []
    for ch in normalized.lower():
        if ch.isascii() and ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "unknown"


def write_tsv(out_path: Path, segments: List[Dict], song_meta: Dict) -> None:
    """Write an Anki-importable TSV.

    Columns (no header — Anki imports cleaner this way):
      1. audio     -> [sound:p0001.mp3]
      2. l2_text   -> lyric line in the source language
      3. l1_text   -> translation (may be empty)
      4. tags      -> "artist::<slug> song::<slug>"

    On Anki import: configure delimiter=Tab and map columns to Front/Back as desired.
    The audio file is referenced by name only — keep cards.tsv and segments/*.mp3
    together (the segments.zip already bundles both).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    artist_slug = slugify(song_meta.get("artist", ""))
    title_slug = slugify(song_meta.get("title", ""))
    tags = f"artist::{artist_slug} song::{title_slug}"

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        for seg in segments:
            audio_file = seg.get("audio_file", "")
            l2 = (seg.get("l2_text") or "").strip()
            l1 = (seg.get("l1_translation") or "").strip()
            writer.writerow([
                f"[sound:{audio_file}]" if audio_file else "",
                l2,
                l1,
                tags,
            ])


