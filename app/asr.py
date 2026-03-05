from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


class ASRError(RuntimeError):
    pass


@dataclass(frozen=True)
class ASRParams:
    enabled: bool = False
    model: str = "base"
    language: Optional[str] = None  # ISO-639-1 like "en", or None for auto
    beam_size: int = 5
    word_timestamps: bool = True

    # Alignment helpers
    context_ms: int = 500
    refine_boundaries: bool = True
    refine_keep_ms: int = 80

    # When True, uses a lightweight VAD inside Whisper. Not always good for music.
    vad_filter: bool = False


_MODEL_CACHE: Dict[Tuple[str, str, str], Any] = {}


def _load_model(model: str, device: str, compute_type: str):
    """Lazy-load and cache faster-whisper models."""
    key = (model, device, compute_type)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as e:  # pragma: no cover
        raise ASRError(
            "Dependência 'faster-whisper' não encontrada. Rode: pip install -r requirements.txt"
        ) from e

    try:
        m = WhisperModel(model, device=device, compute_type=compute_type)
    except Exception as e:
        raise ASRError(
            f"Falha ao carregar modelo Whisper '{model}'. "
            "Isso normalmente baixa o modelo automaticamente (precisa de internet) na 1ª execução."
        ) from e

    _MODEL_CACHE[key] = m
    return m


def transcribe_wav(
    wav_path: str,
    *,
    params: ASRParams,
    device: str,
    compute_type: str,
) -> Dict[str, Any]:
    """Transcreve um WAV e retorna texto, idioma e timestamps (segmentos + palavras)."""
    model = _load_model(params.model, device=device, compute_type=compute_type)

    try:
        segments, info = model.transcribe(
            wav_path,
            language=params.language,
            beam_size=params.beam_size,
            word_timestamps=params.word_timestamps,
            vad_filter=params.vad_filter,
        )
    except Exception as e:
        raise ASRError(f"Falha no ASR em '{wav_path}': {e}") from e

    out_segments: List[Dict[str, Any]] = []
    all_words: List[Dict[str, Any]] = []
    full_text_parts: List[str] = []

    for seg in segments:
        seg_dict: Dict[str, Any] = {
            "start_s": float(seg.start),
            "end_s": float(seg.end),
            "text": seg.text,
        }
        full_text_parts.append(seg.text)

        words_payload: List[Dict[str, Any]] = []
        if params.word_timestamps and getattr(seg, "words", None):
            for w in seg.words:
                wd = {
                    "word": w.word,
                    "start_s": float(w.start),
                    "end_s": float(w.end),
                    "prob": float(getattr(w, "probability", 0.0) or 0.0),
                }
                words_payload.append(wd)
                all_words.append(wd)

        if words_payload:
            seg_dict["words"] = words_payload
        out_segments.append(seg_dict)

    text = "".join(full_text_parts).strip()
    return {
        "language": getattr(info, "language", None),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "text": text,
        "segments": out_segments,
        "words": all_words,
    }
