from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydub import AudioSegment
from pydub.silence import detect_nonsilent, detect_silence


class ProcessingError(RuntimeError):
    pass


def _run(cmd: List[str]) -> None:
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise ProcessingError(
            f"Falha ao executar comando: {' '.join(cmd)}\n\nSTDERR:\n{e.stderr.decode(errors='ignore')}"
        ) from e


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise ProcessingError(
            "ffmpeg não encontrado no PATH. Instale o ffmpeg no sistema (ou use o Dockerfile fornecido)."
        )


def convert_to_analysis_wav(input_path: Path, out_wav: Path, sample_rate: int = 16000) -> None:
    """Creates a mono WAV for analysis (VAD / silêncio)."""
    ensure_ffmpeg()
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-f", "wav",
        str(out_wav),
    ]
    _run(cmd)


def extract_wav_range(input_wav: Path, start_ms: int, end_ms: int, out_wav: Path) -> None:
    """Extracts a time range from a WAV into another WAV."""
    ensure_ffmpeg()
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    start_s = max(0.0, start_ms / 1000.0)
    dur_s = max(0.0, (end_ms - start_ms) / 1000.0)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-t", f"{dur_s:.3f}",
        "-i", str(input_wav),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        str(out_wav),
    ]
    _run(cmd)


def run_demucs_vocals(input_path: Path, out_vocals_wav: Path, model: str = "htdemucs") -> bool:
    """Attempts to isolate vocals using demucs (optional). Returns True if successful."""
    if shutil.which("demucs") is None and shutil.which("python") is None:
        return False

    # We try invoking the 'demucs' CLI first; if not present, try python -m demucs.
    out_dir = out_vocals_wav.parent / "demucs_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    # demucs outputs into out_dir/separated/{model}/{trackname}/vocals.wav
    # Trackname is the input filename without extension.
    track_name = input_path.stem

    tried = []
    ok = False

    # Try demucs CLI
    if shutil.which("demucs") is not None:
        cmd = [
            "demucs",
            "-n", model,
            "--two-stems", "vocals",
            "-o", str(out_dir),
            str(input_path),
        ]
        tried.append(cmd)
        try:
            _run(cmd)
            ok = True
        except ProcessingError:
            ok = False

    # Try python -m demucs
    if not ok and shutil.which("python") is not None:
        cmd = [
            "python", "-m", "demucs",
            "-n", model,
            "--two-stems", "vocals",
            "-o", str(out_dir),
            str(input_path),
        ]
        tried.append(cmd)
        try:
            _run(cmd)
            ok = True
        except ProcessingError:
            ok = False

    if not ok:
        return False

    candidate = out_dir / "separated" / model / track_name / "vocals.wav"
    if not candidate.exists():
        # Some demucs versions use a slightly different folder name; try searching.
        for p in out_dir.rglob("vocals.wav"):
            candidate = p
            break

    if not candidate.exists():
        return False

    out_vocals_wav.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, out_vocals_wav)
    return True


@dataclass(frozen=True)
class SegmentParams:
    min_silence_ms: int = 450
    keep_silence_ms: int = 150
    merge_gap_ms: int = 200
    min_segment_ms: int = 800
    max_segment_ms: int = 12000
    # If None, we set threshold relative to track dBFS.
    silence_thresh_dbfs: Optional[float] = None


def _auto_silence_thresh(audio: AudioSegment) -> float:
    # Heurística simples: threshold relativo ao nível médio.
    # Ex.: áudio dBFS=-18 => threshold=-34.
    return float(audio.dBFS - 16.0)


def _pad_and_merge(ranges: List[Tuple[int, int]], total_ms: int, keep_silence_ms: int, merge_gap_ms: int) -> List[List[int]]:
    padded = [[max(0, s - keep_silence_ms), min(total_ms, e + keep_silence_ms)] for s, e in ranges]
    padded.sort(key=lambda x: x[0])

    merged: List[List[int]] = []
    for s, e in padded:
        if not merged:
            merged.append([s, e])
            continue
        ps, pe = merged[-1]
        if s - pe <= merge_gap_ms:
            merged[-1][1] = max(pe, e)
        else:
            merged.append([s, e])
    return merged


def _split_long_segment(
    audio: AudioSegment,
    abs_start: int,
    abs_end: int,
    max_segment_ms: int,
    min_segment_ms: int,
    silence_thresh: float,
) -> List[Tuple[int, int]]:
    """Split a long segment by looking for internal silences; fallback to hard splits."""
    out: List[Tuple[int, int]] = []
    segment = audio[abs_start:abs_end]
    seg_len = abs_end - abs_start
    if seg_len <= max_segment_ms:
        return [(abs_start, abs_end)]

    # Find internal silences with a slightly more permissive minimum (helps find micro-pauses).
    silences = detect_silence(segment, min_silence_len=200, silence_thresh=silence_thresh)
    cut_points = []
    for s, e in silences:
        mid = (s + e) // 2
        # Avoid cut too close to borders
        if 250 < mid < seg_len - 250:
            cut_points.append(mid)
    cut_points.sort()

    cursor = 0
    while cursor < seg_len:
        target = cursor + max_segment_ms
        if target >= seg_len:
            out.append((abs_start + cursor, abs_end))
            break

        # choose last cut point <= target and >= cursor + min_segment_ms
        candidate = None
        for cp in cut_points:
            if cursor + min_segment_ms <= cp <= target:
                candidate = cp
        if candidate is None:
            candidate = target  # hard split
        out.append((abs_start + cursor, abs_start + candidate))
        cursor = candidate

    # Final cleanup: drop too-short tails by merging with previous
    cleaned: List[Tuple[int, int]] = []
    for s, e in out:
        if cleaned and (e - s) < min_segment_ms:
            ps, pe = cleaned[-1]
            cleaned[-1] = (ps, e)
        else:
            cleaned.append((s, e))
    return cleaned


def segment_by_pauses(wav_for_analysis: Path, params: SegmentParams) -> List[Dict]:
    """Detects non-silent regions and returns a list of segments with start/end in ms."""
    audio = AudioSegment.from_wav(str(wav_for_analysis))
    total_ms = len(audio)

    silence_thresh = params.silence_thresh_dbfs if params.silence_thresh_dbfs is not None else _auto_silence_thresh(audio)

    nonsilent = detect_nonsilent(
        audio,
        min_silence_len=params.min_silence_ms,
        silence_thresh=silence_thresh,
    )

    merged = _pad_and_merge(
        [(int(s), int(e)) for s, e in nonsilent],
        total_ms=total_ms,
        keep_silence_ms=params.keep_silence_ms,
        merge_gap_ms=params.merge_gap_ms,
    )

    # Enforce min/max
    final: List[Tuple[int, int]] = []
    for s, e in merged:
        dur = e - s
        if dur < params.min_segment_ms:
            # Try merge with previous if close; else drop
            if final and (s - final[-1][1]) <= params.merge_gap_ms:
                ps, pe = final[-1]
                final[-1] = (ps, e)
            continue

        splits = _split_long_segment(
            audio=audio,
            abs_start=s,
            abs_end=e,
            max_segment_ms=params.max_segment_ms,
            min_segment_ms=params.min_segment_ms,
            silence_thresh=silence_thresh,
        )
        final.extend(splits)

    # Build metadata
    out = []
    for i, (s, e) in enumerate(final, start=1):
        out.append({
            "id": f"p{i:04d}",
            "start_ms": int(s),
            "end_ms": int(e),
            "duration_ms": int(e - s),
        })
    return out


def export_segments_to_mp3(
    input_audio: Path,
    segments: List[Dict],
    out_dir: Path,
    mp3_quality_q: int = 4,
) -> None:
    ensure_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)

    for seg in segments:
        seg_id = seg["id"]
        start_s = seg["start_ms"] / 1000.0
        dur_s = (seg["end_ms"] - seg["start_ms"]) / 1000.0
        out_path = out_dir / f"{seg_id}.mp3"
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_s:.3f}",
            "-t", f"{dur_s:.3f}",
            "-i", str(input_audio),
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", str(mp3_quality_q),
            str(out_path),
        ]
        _run(cmd)
        seg["audio_file"] = str(out_path.name)


def make_zip(segments_dir: Path, segments_json: Path, out_zip: Path) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # Add audio files
        for p in sorted(segments_dir.glob("*.mp3")):
            z.write(p, arcname=f"segments/{p.name}")
        # Add metadata
        if segments_json.exists():
            z.write(segments_json, arcname="segments.json")
