from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Server settings loaded from environment variables."""
    jobs_dir: str = os.getenv("JOBS_DIR", "./jobs")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "200"))
    # When True, attempts to run Demucs (if installed) to isolate vocals for segmentation.
    enable_demucs: bool = os.getenv("ENABLE_DEMUCS", "0").strip() == "1"

    # ASR defaults (local Whisper)
    asr_device: str = os.getenv("ASR_DEVICE", "cpu")
    # Typical values: "int8" (CPU fast), "float16" (GPU), "int8_float16" etc.
    asr_compute_type: str = os.getenv("ASR_COMPUTE_TYPE", "int8")
    asr_beam_size: int = int(os.getenv("ASR_BEAM_SIZE", "5"))

    # Translation defaults (LibreTranslate)
    translate_provider: str = os.getenv("TRANSLATE_PROVIDER", "none")
    libretranslate_url: str = os.getenv("LIBRETRANSLATE_URL", "")
    libretranslate_api_key: str = os.getenv("LIBRETRANSLATE_API_KEY", "")


settings = Settings()
