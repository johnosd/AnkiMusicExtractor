# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

FastAPI backend that ingests a music file and produces phrase-level MP3 snippets. **Two pipelines** coexist:

- **Lyrics mode (`use_lyrics=true`, v0.3, recommended):** identify song (ID3 + manual override) → fetch synced LRC from LRCLib → parse timestamps → cut by line → (optional) LibreTranslate → write `segments/*.mp3` + `segments.json` + `cards.tsv` (Anki-importable) → bundle into `segments.zip`. No ASR involved.
- **Classic ASR mode (default, original v0.2 flow):** convert to analysis WAV → (optional) Demucs vocal isolation → silence-based segmentation (pydub) → (optional) faster-whisper ASR with word timestamps → (optional) refine segment boundaries from word timestamps → (optional) translation → export MP3 from the **original** mix → bundle.

Documentation comments and user-facing strings are in Portuguese.

## Commands

Run the full stack (API + LibreTranslate translator service):
```bash
docker compose up --build
# API → http://localhost:8000  •  LibreTranslate → http://localhost:5000
```

Local dev (requires `ffmpeg` on PATH, plus optional `demucs` for vocal isolation):
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# Enable Demucs vocal isolation:
ENABLE_DEMUCS=1 uvicorn app.main:app --reload
```

Smoke-test faster-whisper independently (downloads `base` model on first run):
```bash
python tests/test_whisper.py app/input/Love\ Yourself.mp3
```

There is no formal test runner, lint config, or type-check configured.

## Architecture

### Request lifecycle
`POST /v1/jobs` (multipart) returns immediately after persisting the upload and queueing work via FastAPI `BackgroundTasks`. The background worker is `_process_job` in [app/main.py](app/main.py) and writes incremental state to `status.json`. Clients poll `GET /v1/jobs/{id}` and fetch `segments.json` / `segments.zip` once status is `done`.

There is no real queue — restarting the process drops in-flight jobs. The README explicitly flags this as MVP and recommends Celery/RQ for production.

### Module boundaries
- [app/main.py](app/main.py) — FastAPI routes + two orchestrators: `_process_lyrics_job` (new) and `_process_job` (classic). `create_job` dispatches on `use_lyrics`. All cross-stage state (segments list with progressive enrichment) lives in these orchestrators.
- [app/identify.py](app/identify.py) — `SongInfo` dataclass + `identify()` cascade: manual artist/title > ID3 (via mutagen, easy mode). Returns `None` when both artist and title are missing.
- [app/lyrics.py](app/lyrics.py) — LRCLib client (`fetch_lyrics`, sha1-cached on disk under `LYRICS_CACHE_DIR`) + `parse_lrc()` (handles `[mm:ss.xx]` and `[mm:ss.xxx]`, multiple stamps per line, metadata stripping, drops empty-text timestamps). `end_ms = min(next_start, start + max_line_ms, total_duration_ms)`. Raises `LyricsError`.
- [app/anki.py](app/anki.py) — `write_tsv()` produces headerless TSV with 4 columns: `[sound:p####.mp3]`, L2 text, L1 translation, tags (`artist::<slug> song::<slug>`).
- [app/processing.py](app/processing.py) — ffmpeg shell-outs, silence detection (`segment_by_pauses`, classic mode only), long-segment splitting via internal silences, optional Demucs CLI invocation, MP3 export, ZIP packaging (`make_zip` accepts `extra_files` for `cards.tsv`). `get_audio_duration_s()` tries mutagen first, falls back to ffprobe. Raises `ProcessingError`.
- [app/asr.py](app/asr.py) — faster-whisper wrapper. Holds a process-wide `_MODEL_CACHE` keyed by `(model, device, compute_type)` so the model is loaded once per worker. Raises `ASRError`. Only used in classic mode.
- [app/translate.py](app/translate.py) — Pluggable provider dispatch (`libretranslate` via httpx, `argos` via optional `argostranslate` lib). `normalize_lang` strips locale suffixes (`pt-br` → `pt`). Raises `TranslationError`.
- [app/config.py](app/config.py) — Frozen `Settings` dataclass instantiated once at import. All env vars are read here; modules consume `settings.*`, not `os.getenv` directly.
- [app/storage.py](app/storage.py) — `JobPaths` layout (`lyrics.lrc` and `cards.tsv` added) + `read_json`/`write_json` helpers.

### Per-job filesystem layout
Under `JOBS_DIR` (default `./jobs`, mapped to `/data/jobs` in Docker):
```
{job_id}/
  input{ext}          # original upload (preserved for final MP3 export)
  analysis.wav        # classic mode only — mono 16kHz for silence/ASR analysis
  vocals.wav          # classic mode only — when Demucs ran successfully
  tmp_asr/{seg_id}.wav # classic mode only — per-segment WAVs fed to Whisper
  lyrics.lrc          # lyrics mode only — raw LRC returned by LRCLib
  cards.tsv           # lyrics mode only — Anki-importable TSV
  segments/{p####}.mp3 # final snippets cut from the ORIGINAL mix
  segments.json       # metadata + segments + (asr/translation)
  segments.zip        # bundle for download (includes cards.tsv in lyrics mode)
  status.json         # {queued|processing|done|error} + stage field
```
Synced lyrics are cached separately under `LYRICS_CACHE_DIR` (`./data/lyrics_cache` local, `/data/lyrics_cache` in Docker), keyed by `sha1(artist|title|album)[:16]` — survives across jobs.
The split between `analysis.wav` (analysis) and `input{ext}` (final cut source) is deliberate: snippets are always exported from the full original mix even when segmentation used the Demucs vocals stem.

### ASR alignment subtlety
`_process_job` does not transcribe each raw segment in isolation. For each segment it extracts a **wider window** (`raw_start − context_ms` to `raw_end + context_ms`), transcribes that, then selects only the words whose timestamps overlap the original segment. When `asr_refine_boundaries=true`, it then snaps the segment's `start_ms`/`end_ms` to the first/last selected word ± `refine_keep_ms`. `raw_start_ms`/`raw_end_ms` are preserved on the segment dict for traceability. If ASR is enabled but **zero** segments transcribe successfully, the job fails with `ProcessingError`.

### Translation flow
Translation runs after ASR, reading `seg["l2_text"]` (built from the word-aligned text, not the raw window text) and writing `seg["l1_translation"]`. Per-segment failures are non-fatal — the error is captured in `seg["translation_error"]` and added to the job-level `warnings` list. Source language comes from `seg["l2_language"]` (Whisper-detected, normalized) and falls back to `auto` for LibreTranslate.

## Configuration

All settings are environment-driven (see [app/config.py](app/config.py)):

| Var | Default | Notes |
|---|---|---|
| `JOBS_DIR` | `./jobs` | Compose overrides to `/data/jobs` |
| `MAX_UPLOAD_MB` | `200` | Enforced in-handler after reading the body |
| `ENABLE_DEMUCS` | `0` | Must be `1` AND `demucs` installed for `use_vocals=true` to take effect |
| `ASR_DEVICE` | `cpu` | `cuda` for GPU |
| `ASR_COMPUTE_TYPE` | `int8` | Use `float16`/`int8_float16` for GPU |
| `ASR_BEAM_SIZE` | `5` | |
| `TRANSLATE_PROVIDER` | `none` | `libretranslate` (default in compose) or `argos` |
| `LIBRETRANSLATE_URL` | `""` | Compose sets `http://libretranslate:5000` |
| `LIBRETRANSLATE_API_KEY` | `""` | |
| `LYRICS_CACHE_DIR` | `./data/lyrics_cache` | Compose sets `/data/lyrics_cache` |

## Gotchas

- `ffmpeg` is a hard runtime requirement — `ensure_ffmpeg()` raises if missing. The Dockerfile installs it; local dev needs it on PATH.
- First ASR call downloads the Whisper model from Hugging Face. The compose file mounts a named volume `hf_cache` to `/home/appuser/.cache/huggingface` so this only happens once.
- Demucs is **not** in `requirements.txt` and is invoked as a subprocess; the function silently returns `False` and falls back to analysis WAV if it's not available.
- Silence threshold defaults to a heuristic `dBFS − 16` (see `_auto_silence_thresh`) — heavily instrumental tracks may have no detectable silences in the mix; that's the case Demucs is meant to address.
- The container runs as non-root `appuser` (UID 10001). Host-mounted `./data` must be writable by that UID.
