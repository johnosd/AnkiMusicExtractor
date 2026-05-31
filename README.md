# Music Phrase Cards

Backend FastAPI que transforma músicas em cards prontos para o Anki.  
Recebe um arquivo de áudio, divide em trechos por linha da letra (modo recomendado) ou por silêncio (modo clássico), faz upload dos MP3 para o Supabase Storage, persiste os cards no banco e entrega um TSV importável no Anki.

---

## Funcionalidades

- **Modo Lyrics** (recomendado): identifica a música pelas tags ID3 ou pelos campos `artist`/`title`, busca a letra sincronizada no [LRCLib](https://lrclib.net) e corta o áudio pelos timestamps — sem ASR, sem erros de transcrição.
- **Modo Clássico**: segmentação por silêncio (pydub) com ASR opcional (faster-whisper) e refinamento de bordas por palavra.
- **Tradução automática** por trecho via Google Translate (sem API key) ou LibreTranslate.
- **Reuso de músicas**: se a mesma música já foi processada, retorna os cards existentes instantaneamente sem reprocessar.
- **Supabase integrado**: MP3s vão para o Storage e cards ficam no banco — acessíveis de qualquer instância.
- **Interface web** em `/` (processar) e `/review` (revisar cards estilo flashcard).
- **Cards Anki** prontos: TSV + ZIP com MP3s.

---

## Pré-requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Conta no [Supabase](https://supabase.com) (plano gratuito basta)

---

## Configuração inicial (Supabase)

### 1. Criar projeto no Supabase

Crie um projeto em [supabase.com](https://supabase.com). Anote o **Project Ref** (ex: `abcxyz123`).

### 2. Criar as tabelas

No **SQL Editor** do Supabase, execute:

```sql
CREATE TABLE songs (
    id         SERIAL PRIMARY KEY,
    job_id     TEXT    NOT NULL UNIQUE,
    artist     TEXT    NOT NULL DEFAULT '',
    title      TEXT    NOT NULL DEFAULT '',
    album      TEXT    NOT NULL DEFAULT '',
    artist_slug TEXT   NOT NULL DEFAULT '',
    title_slug  TEXT   NOT NULL DEFAULT '',
    duration_s  REAL,
    mode        TEXT   NOT NULL DEFAULT 'classic',
    created_at  INTEGER NOT NULL
);

CREATE TABLE cards (
    id             SERIAL  PRIMARY KEY,
    song_id        INTEGER NOT NULL,
    segment_id     TEXT    NOT NULL,
    position       INTEGER NOT NULL,
    start_ms       INTEGER NOT NULL,
    end_ms         INTEGER NOT NULL,
    duration_ms    INTEGER NOT NULL,
    audio_file     TEXT    NOT NULL DEFAULT '',
    audio_url      TEXT    NOT NULL DEFAULT '',
    l2_text        TEXT    NOT NULL DEFAULT '',
    l2_language    TEXT    NOT NULL DEFAULT '',
    l1_translation TEXT    NOT NULL DEFAULT '',
    tags           TEXT    NOT NULL DEFAULT '',
    created_at     INTEGER NOT NULL
);

CREATE INDEX ix_cards_song_position ON cards(song_id, position);
CREATE UNIQUE INDEX ix_cards_song_segment ON cards(song_id, segment_id);
```

### 3. Criar o bucket de Storage

Em **Storage**, crie um bucket chamado `segments` e marque como **público**.

### 4. Configurar o `.env`

Copie `.env.example` para `.env` e preencha:

```bash
cp .env.example .env
```

```env
# Supabase
SUPABASE_URL=https://<seu-project-ref>.supabase.co
SUPABASE_KEY=<service_role key — Settings → API → service_role>
SUPABASE_BUCKET=segments

# Tradução (Google Translate, sem API key)
TRANSLATE_PROVIDER=google
```

> A `SUPABASE_KEY` deve ser a **service_role** key (não a anon key). Encontre em **Settings → API → Project API keys**.

---

## Rodando

```bash
# Subir a API
./start.sh          # Linux/macOS/Git Bash
# ou
docker compose up --build -d

# Parar
./start.sh down
# ou
docker compose down
```

A API fica disponível em **http://localhost:8000**.

---

## Interface web

| URL | Descrição |
|---|---|
| `http://localhost:8000/` | Upload e processamento de músicas |
| `http://localhost:8000/review` | Revisão de cards (estilo flashcard) |
| `http://localhost:8000/health` | Healthcheck |

---

## API

### Processar música — modo Lyrics (recomendado)

```bash
curl -X POST "http://localhost:8000/v1/jobs" \
  -F "file=@musica.mp3" \
  -F "use_lyrics=true" \
  -F "artist=Justin Bieber" \
  -F "title=Love Yourself" \
  -F "do_translate=true" \
  -F "translate_to=pt"
```

Se o arquivo tiver tags ID3, `artist`/`title` são opcionais.

**Parâmetros do modo lyrics:**

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `use_lyrics` | `false` | Ativa o modo lyrics |
| `artist` | — | Sobrescreve tag ID3 |
| `title` | — | Sobrescreve tag ID3 |
| `album` | — | Sobrescreve tag ID3 |
| `do_translate` | `false` | Ativa tradução por trecho |
| `translate_to` | `pt` | Idioma alvo da tradução |
| `translate_provider` | `google` | `google`, `libretranslate` ou `argos` |
| `max_line_ms` | `10000` | Duração máxima de um trecho em ms |
| `padding_ms` | `300` | Margem (ms) adicionada antes e depois de cada trecho |

**Resposta — música nova:**
```json
{
  "job_id": "abc123...",
  "status": "queued",
  "mode": "lyrics",
  "song": { "artist": "...", "title": "...", "album": "..." },
  "poll": "/v1/jobs/abc123...",
  "download_zip": "/v1/jobs/abc123.../segments.zip",
  "download_tsv": "/v1/jobs/abc123.../cards.tsv"
}
```

**Resposta — música já processada (reuso):**
```json
{
  "job_id": "abc123...",
  "status": "done",
  "cached": true,
  "notes": "Música já processada anteriormente — cards reutilizados do banco."
}
```

---

### Processar música — modo Clássico (ASR)

```bash
curl -X POST "http://localhost:8000/v1/jobs" \
  -F "file=@musica.mp3" \
  -F "do_asr=true" \
  -F "asr_model=base" \
  -F "asr_language=en" \
  -F "do_translate=true" \
  -F "translate_to=pt"
```

**Parâmetros do modo clássico:**

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `min_silence_ms` | `450` | Duração mínima de silêncio para corte |
| `keep_silence_ms` | `150` | Silêncio mantido nas bordas do trecho |
| `merge_gap_ms` | `200` | Gap máximo para mesclar trechos consecutivos |
| `min_segment_ms` | `800` | Duração mínima de um trecho |
| `max_segment_ms` | `12000` | Duração máxima de um trecho |
| `use_vocals` | `false` | Isolamento vocal com Demucs (requer `ENABLE_DEMUCS=1`) |
| `do_asr` | `false` | Ativa transcrição com faster-whisper |
| `asr_model` | `base` | Modelo Whisper: `tiny`, `base`, `small`, `medium`, `large` |
| `asr_language` | auto | Código ISO do idioma (ex: `en`, `pt`) |

---

### Checar status do job

```bash
curl "http://localhost:8000/v1/jobs/{job_id}"
```

Status possíveis: `queued` → `processing` → `done` ou `error`.

---

### Listar músicas processadas

```bash
curl "http://localhost:8000/v1/songs?limit=50&offset=0"
```

---

### Buscar cards de uma música

```bash
curl "http://localhost:8000/v1/songs/{job_id}/cards"
```

---

### Excluir música

Remove do banco, do Supabase Storage e do filesystem local.

```bash
curl -X DELETE "http://localhost:8000/v1/songs/{job_id}"
```

---

### Downloads

```bash
# ZIP com todos os MP3s + segments.json (+ cards.tsv no modo lyrics)
curl -L -o segments.zip "http://localhost:8000/v1/jobs/{job_id}/segments.zip"

# TSV para importar no Anki (apenas modo lyrics)
curl -L -o cards.tsv "http://localhost:8000/v1/jobs/{job_id}/cards.tsv"

# Metadados completos
curl "http://localhost:8000/v1/jobs/{job_id}/segments.json"
```

---

## Importar no Anki

1. Extraia o `segments.zip` em `collection.media` do seu perfil Anki.
2. No Anki: **File → Import** → selecione `cards.tsv`.
3. Configure: delimitador **Tab**, mapear colunas:
   - Coluna 1 → campo de áudio (`[sound:p0001.mp3]`)
   - Coluna 2 → frente (texto L2)
   - Coluna 3 → verso (tradução L1)
   - Coluna 4 → tags

---

## Configuração

Todas as variáveis são lidas do `.env` (veja `.env.example`):

| Variável | Padrão | Descrição |
|---|---|---|
| `JOBS_DIR` | `./jobs` | Diretório de jobs (Docker: `/data/jobs`) |
| `LYRICS_CACHE_DIR` | `./data/lyrics_cache` | Cache de letras do LRCLib |
| `MAX_UPLOAD_MB` | `200` | Limite de upload |
| `ENABLE_DEMUCS` | `0` | `1` para habilitar isolamento vocal |
| `ASR_DEVICE` | `cpu` | `cuda` para GPU |
| `ASR_COMPUTE_TYPE` | `int8` | `float16` para GPU |
| `ASR_BEAM_SIZE` | `5` | Beam size do Whisper |
| `TRANSLATE_PROVIDER` | `none` | `google`, `libretranslate` ou `argos` |
| `LIBRETRANSLATE_URL` | `""` | URL do LibreTranslate (se usado) |
| `SUPABASE_URL` | `""` | URL do projeto Supabase |
| `SUPABASE_KEY` | `""` | Service role key do Supabase |
| `SUPABASE_BUCKET` | `segments` | Nome do bucket no Storage |

---

## Arquitetura

```
POST /v1/jobs
    │
    ├─ use_lyrics=true ──► identify() → LRCLib → parse_lrc() → export MP3
    │                                                           → upload Storage
    │                                                           → persist DB
    │
    └─ use_lyrics=false ─► silence segmentation → (ASR) → (translate)
                                                 → export MP3 → upload Storage → persist DB
```

**Módulos principais:**

| Arquivo | Responsabilidade |
|---|---|
| `app/main.py` | Rotas FastAPI + orquestradores de pipeline |
| `app/identify.py` | Identificação da música (ID3 + campos manuais) |
| `app/lyrics.py` | Cliente LRCLib + parser de LRC |
| `app/processing.py` | ffmpeg, segmentação por silêncio, exportação MP3 |
| `app/asr.py` | Wrapper faster-whisper com cache de modelo |
| `app/translate.py` | Dispatch de providers de tradução |
| `app/db.py` | Operações no banco via Supabase REST |
| `app/cloud_storage.py` | Upload/delete de MP3s no Supabase Storage |
| `app/anki.py` | Geração do TSV para Anki |
| `app/config.py` | Settings carregadas de variáveis de ambiente |

**Filesystem por job** (sob `JOBS_DIR/{job_id}/`):

```
input{ext}          # upload original
lyrics.lrc          # letra sincronizada (modo lyrics)
segments/           # MP3s cortados
segments.json       # metadados completos
segments.zip        # bundle para download
cards.tsv           # TSV para Anki (modo lyrics)
status.json         # status do processamento
```

---

## Desenvolvimento local

```bash
pip install -r requirements.txt
# ffmpeg deve estar no PATH

uvicorn app.main:app --reload

# Com Demucs:
ENABLE_DEMUCS=1 uvicorn app.main:app --reload
```

> Na primeira execução com ASR, o modelo Whisper é baixado automaticamente do Hugging Face.
