from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class JobPaths:
    job_dir: Path
    input_file: Path
    analysis_wav: Path
    vocals_wav: Path
    segments_dir: Path
    segments_json: Path
    segments_zip: Path
    status_json: Path


def build_job_paths(jobs_dir: Path, job_id: str, original_ext: str) -> JobPaths:
    job_dir = jobs_dir / job_id
    return JobPaths(
        job_dir=job_dir,
        input_file=job_dir / f"input{original_ext}",
        analysis_wav=job_dir / "analysis.wav",
        vocals_wav=job_dir / "vocals.wav",
        segments_dir=job_dir / "segments",
        segments_json=job_dir / "segments.json",
        segments_zip=job_dir / "segments.zip",
        status_json=job_dir / "status.json",
    )


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
