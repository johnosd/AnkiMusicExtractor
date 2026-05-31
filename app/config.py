from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip() == "1"


@dataclass(frozen=True)
class Settings:
    """Server settings loaded from environment variables."""
    jobs_dir: str = os.getenv("JOBS_DIR", "./jobs")
    max_upload_mb: int = _int_env("MAX_UPLOAD_MB", 200)
    # When True, attempts to run Demucs (if installed) to isolate vocals for segmentation.
    enable_demucs: bool = _bool_env("ENABLE_DEMUCS", False)

    # ASR defaults (local Whisper)
    asr_device: str = os.getenv("ASR_DEVICE", "cpu")
    # Typical values: "int8" (CPU fast), "float16" (GPU), "int8_float16" etc.
    asr_compute_type: str = os.getenv("ASR_COMPUTE_TYPE", "int8")
    asr_beam_size: int = _int_env("ASR_BEAM_SIZE", 5)

    # Translation defaults (LibreTranslate)
    translate_provider: str = os.getenv("TRANSLATE_PROVIDER", "none")
    libretranslate_url: str = os.getenv("LIBRETRANSLATE_URL", "")
    libretranslate_api_key: str = os.getenv("LIBRETRANSLATE_API_KEY", "")

    # Lyrics cache (LRCLib responses)
    lyrics_cache_dir: str = os.getenv("LYRICS_CACHE_DIR", "./data/lyrics_cache")

    # Supabase Storage (upload dos MP3s de cada trecho)
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    supabase_bucket: str = os.getenv("SUPABASE_BUCKET", "segments")


settings = Settings()
