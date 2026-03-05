from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .config import settings
from .asr import ASRParams, ASRError, transcribe_wav
from .processing import (
    ProcessingError,
    SegmentParams,
    convert_to_analysis_wav,
    extract_wav_range,
    export_segments_to_mp3,
    make_zip,
    run_demucs_vocals,
    segment_by_pauses,
)
from .storage import build_job_paths, read_json, write_json
from .translate import TranslateParams, TranslationError, normalize_lang, translate_text


app = FastAPI(title="Music Phrase Segmenter API", version="0.2.0")


def _jobs_dir() -> Path:
    p = Path(settings.jobs_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _set_status(paths, status: str, extra: Optional[Dict[str, Any]] = None) -> None:
    payload: Dict[str, Any] = {"status": status, "updated_at": int(time.time())}
    if extra:
        payload.update(extra)
    write_json(paths.status_json, payload)


def _process_job(
    job_id: str,
    original_ext: str,
    params: SegmentParams,
    use_vocals: bool,
    asr_params: ASRParams,
    tr_params: TranslateParams,
) -> None:
    jobs_dir = _jobs_dir()
    paths = build_job_paths(jobs_dir, job_id, original_ext)

    try:
        _set_status(paths, "processing", {"job_id": job_id})

        # 1) analysis wav
        convert_to_analysis_wav(paths.input_file, paths.analysis_wav, sample_rate=16000)

        analysis_source = paths.analysis_wav

        # 2) optional vocals
        if use_vocals and settings.enable_demucs:
            ok = run_demucs_vocals(paths.input_file, paths.vocals_wav)
            if ok and paths.vocals_wav.exists():
                analysis_source = paths.vocals_wav

        # 3) segment
        segments = segment_by_pauses(analysis_source, params)

        warnings = []

        # 4) ASR (optional) + alignment
        if asr_params.enabled:
            tmp_dir = paths.job_dir / "tmp_asr"
            tmp_dir.mkdir(parents=True, exist_ok=True)

            ok_count = 0
            for seg in segments:
                raw_start = int(seg["start_ms"])
                raw_end = int(seg["end_ms"])
                seg["raw_start_ms"] = raw_start
                seg["raw_end_ms"] = raw_end

                window_start = max(0, raw_start - asr_params.context_ms)
                window_end = raw_end + asr_params.context_ms

                window_wav = tmp_dir / f"{seg['id']}.wav"
                try:
                    extract_wav_range(Path(analysis_source), window_start, window_end, window_wav)
                    asr = transcribe_wav(
                        str(window_wav),
                        params=asr_params,
                        device=settings.asr_device,
                        compute_type=settings.asr_compute_type,
                    )
                    seg["asr"] = {
                        "language": asr.get("language"),
                        "language_probability": asr.get("language_probability"),
                        "text_window": asr.get("text"),
                    }

                    # Word-level alignment
                    words = asr.get("words") or []
                    # Convert to absolute ms
                    abs_words = []
                    for w in words:
                        try:
                            abs_words.append({
                                "word": w.get("word", ""),
                                "start_ms": int(window_start + float(w.get("start_s", 0.0)) * 1000),
                                "end_ms": int(window_start + float(w.get("end_s", 0.0)) * 1000),
                                "prob": float(w.get("prob", 0.0) or 0.0),
                            })
                        except Exception:
                            continue

                    seg["words"] = abs_words

                    rel_start = raw_start - window_start
                    rel_end = raw_end - window_start
                    # Select words overlapping the original segment window (+/- small margin)
                    selected = [
                        w for w in abs_words
                        if w["end_ms"] >= (raw_start - 50) and w["start_ms"] <= (raw_end + 50)
                    ]

                    # Build text from selected words (preserves spaces as Whisper emits them)
                    if selected:
                        l2_text = "".join([w["word"] for w in selected]).strip()
                    else:
                        l2_text = str(asr.get("text", "") or "").strip()

                    seg["l2_text"] = l2_text
                    seg["l2_language"] = normalize_lang(asr.get("language") or asr_params.language)

                    # Refine boundaries based on first/last selected word
                    if asr_params.refine_boundaries and selected:
                        first_ms = min(w["start_ms"] for w in selected)
                        last_ms = max(w["end_ms"] for w in selected)
                        refined_start = max(0, int(first_ms - asr_params.refine_keep_ms))
                        refined_end = int(last_ms + asr_params.refine_keep_ms)
                        if refined_end > refined_start:
                            seg["start_ms"] = refined_start
                            seg["end_ms"] = refined_end
                            seg["duration_ms"] = int(refined_end - refined_start)

                    ok_count += 1
                except ASRError as e:
                    seg["asr_error"] = str(e)
                    warnings.append(f"ASR falhou no segmento {seg['id']}: {e}")
                except ProcessingError as e:
                    seg["asr_error"] = str(e)
                    warnings.append(f"Falha ao preparar áudio para ASR ({seg['id']}): {e}")
                except Exception as e:
                    seg["asr_error"] = f"Erro inesperado ASR: {e}"
                    warnings.append(f"Erro inesperado no ASR ({seg['id']}): {e}")

            if ok_count == 0:
                raise ProcessingError(
                    "ASR habilitado, mas nenhuma transcrição foi gerada. "
                    "Verifique se as dependências do faster-whisper estão instaladas e se o modelo foi baixado."
                )

        # 5) translation (optional)
        if tr_params.enabled:
            for seg in segments:
                text = str(seg.get("l2_text") or "").strip()
                if not text:
                    continue
                src = normalize_lang(seg.get("l2_language") or "")
                try:
                    seg["l1_translation"] = translate_text(text, source_lang=src, params=tr_params)
                except TranslationError as e:
                    seg["translation_error"] = str(e)
                    warnings.append(f"Tradução falhou no segmento {seg['id']}: {e}")
                except Exception as e:
                    seg["translation_error"] = f"Erro inesperado tradução: {e}"
                    warnings.append(f"Erro inesperado na tradução ({seg['id']}): {e}")

        # 6) export mp3 snippets from ORIGINAL (full mix)
        export_segments_to_mp3(paths.input_file, segments, paths.segments_dir)

        # 7) write metadata + zip
        result = {
            "job_id": job_id,
            "segments_count": len(segments),
            "warnings": warnings,
            "params": {
                "min_silence_ms": params.min_silence_ms,
                "keep_silence_ms": params.keep_silence_ms,
                "merge_gap_ms": params.merge_gap_ms,
                "min_segment_ms": params.min_segment_ms,
                "max_segment_ms": params.max_segment_ms,
                "silence_thresh_dbfs": params.silence_thresh_dbfs,
                "use_vocals": bool(use_vocals and settings.enable_demucs),
                "asr": {
                    "enabled": asr_params.enabled,
                    "model": asr_params.model,
                    "language": asr_params.language,
                    "beam_size": asr_params.beam_size,
                    "word_timestamps": asr_params.word_timestamps,
                    "context_ms": asr_params.context_ms,
                    "refine_boundaries": asr_params.refine_boundaries,
                    "refine_keep_ms": asr_params.refine_keep_ms,
                },
                "translation": {
                    "enabled": tr_params.enabled,
                    "provider": tr_params.provider,
                    "target_lang": tr_params.target_lang,
                    "libre_url": tr_params.libre_url,
                },
            },
            "segments": segments,
        }
        write_json(paths.segments_json, result)
        make_zip(paths.segments_dir, paths.segments_json, paths.segments_zip)

        _set_status(paths, "done", {"job_id": job_id, "segments_count": len(segments), "warnings_count": len(warnings)})
    except ProcessingError as e:
        _set_status(paths, "error", {"job_id": job_id, "error": str(e)})
    except Exception as e:
        _set_status(paths, "error", {"job_id": job_id, "error": f"Erro inesperado: {e}"})


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/v1/jobs")
async def create_job(
    background: BackgroundTasks,
    file: UploadFile = File(...),

    # segmentation params
    min_silence_ms: int = Form(450),
    keep_silence_ms: int = Form(150),
    merge_gap_ms: int = Form(200),
    min_segment_ms: int = Form(800),
    max_segment_ms: int = Form(12000),
    silence_thresh_dbfs: Optional[float] = Form(None),

    # optional vocals (requires ENABLE_DEMUCS=1 and demucs installed)
    use_vocals: bool = Form(False),

    # ASR (optional)
    do_asr: bool = Form(False),
    asr_model: str = Form("base"),
    asr_language: Optional[str] = Form(None),
    asr_word_timestamps: bool = Form(True),
    asr_context_ms: int = Form(500),
    asr_refine_boundaries: bool = Form(True),
    asr_refine_keep_ms: int = Form(80),
    asr_vad_filter: bool = Form(False),

    # Translation (optional)
    do_translate: bool = Form(False),
    translate_to: str = Form("pt"),
    translate_provider: Optional[str] = Form(None),
    libretranslate_url: Optional[str] = Form(None),
    libretranslate_api_key: Optional[str] = Form(None),
):
    # size guard (best-effort; some servers/proxies enforce separately)
    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Arquivo muito grande. Limite: {settings.max_upload_mb} MB.")

    job_id = uuid.uuid4().hex
    ext = os.path.splitext(file.filename or "")[1].lower() or ".bin"

    paths = build_job_paths(_jobs_dir(), job_id, ext)
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    paths.segments_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded file
    paths.input_file.write_bytes(content)

    params = SegmentParams(
        min_silence_ms=min_silence_ms,
        keep_silence_ms=keep_silence_ms,
        merge_gap_ms=merge_gap_ms,
        min_segment_ms=min_segment_ms,
        max_segment_ms=max_segment_ms,
        silence_thresh_dbfs=silence_thresh_dbfs,
    )

    asr_params = ASRParams(
        enabled=bool(do_asr),
        model=asr_model,
        language=normalize_lang(asr_language) if asr_language else None,
        beam_size=settings.asr_beam_size,
        word_timestamps=bool(asr_word_timestamps),
        context_ms=int(asr_context_ms),
        refine_boundaries=bool(asr_refine_boundaries),
        refine_keep_ms=int(asr_refine_keep_ms),
        vad_filter=bool(asr_vad_filter),
    )

    provider = (translate_provider or settings.translate_provider or "none").strip().lower()
    tr_params = TranslateParams(
        enabled=bool(do_translate),
        target_lang=translate_to,
        provider=provider,
        libre_url=(libretranslate_url or settings.libretranslate_url),
        libre_api_key=(libretranslate_api_key or settings.libretranslate_api_key),
    )

    _set_status(paths, "queued", {"job_id": job_id, "filename": file.filename})

    background.add_task(_process_job, job_id, ext, params, use_vocals, asr_params, tr_params)

    return {
        "job_id": job_id,
        "status": "queued",
        "poll": f"/v1/jobs/{job_id}",
        "download_zip": f"/v1/jobs/{job_id}/segments.zip",
        "segments_json": f"/v1/jobs/{job_id}/segments.json",
        "features": {
            "asr": bool(do_asr),
            "translation": bool(do_translate),
            "use_vocals": bool(use_vocals and settings.enable_demucs),
        },
        "notes": "Processamento assíncrono simples (BackgroundTasks). Para produção, use fila (Celery/RQ) e storage persistente.",
    }


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str):
    jobs_dir = _jobs_dir()
    # Find the job directory (we don't know ext here). We'll look for status.json.
    job_dir = jobs_dir / job_id
    status = read_json(job_dir / "status.json")
    if status is None:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    return status


@app.get("/v1/jobs/{job_id}/segments.json")
def get_segments_json(job_id: str):
    jobs_dir = _jobs_dir()
    job_dir = jobs_dir / job_id
    path = job_dir / "segments.json"
    if not path.exists():
        status = read_json(job_dir / "status.json")
        if status and status.get("status") == "error":
            raise HTTPException(status_code=400, detail=status.get("error", "Erro no processamento."))
        raise HTTPException(status_code=404, detail="segments.json ainda não disponível.")
    return JSONResponse(content=read_json(path) or {})


@app.get("/v1/jobs/{job_id}/segments.zip")
def download_segments_zip(job_id: str):
    jobs_dir = _jobs_dir()
    job_dir = jobs_dir / job_id
    path = job_dir / "segments.zip"
    if not path.exists():
        status = read_json(job_dir / "status.json")
        if status and status.get("status") == "error":
            raise HTTPException(status_code=400, detail=status.get("error", "Erro no processamento."))
        raise HTTPException(status_code=404, detail="segments.zip ainda não disponível.")
    return FileResponse(path, media_type="application/zip", filename=f"{job_id}_segments.zip")
