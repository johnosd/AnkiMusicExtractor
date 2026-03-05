# Music Phrase Segmenter API (MVP)

Backend que recebe um arquivo de música e:

1) **segmenta em trechos (MP3)** usando **pausas (silêncio)**
2) (opcional) faz **ASR (transcrição) por trecho**
3) (opcional) faz **tradução por trecho**

## Principais recursos
- Upload via HTTP (multipart/form-data)
- Segmentação por silêncio (pydub)
- ASR local (faster-whisper) com timestamps de palavras (opcional)
- “Alinhamento” simples: refina start/end do trecho com base na primeira/última palavra reconhecida (opcional)
- Tradução via LibreTranslate (opcional)
- Exporta trechos em `segments/*.mp3` + `segments.json` + `segments.zip`
- Job assíncrono simples (FastAPI BackgroundTasks)

> Observação: em música com instrumental forte, o silêncio no mix pode não existir.
> Para melhorar, você pode habilitar isolamento vocal via Demucs (opcional).

---

## Rodando local

### 1) Instale ffmpeg
- Linux: `sudo apt-get install ffmpeg`
- Mac: `brew install ffmpeg`
- Windows: instale via pacote e adicione ao PATH

### 2) Instale dependências
```bash
pip install -r requirements.txt
```

### 3) Suba o servidor
```bash
python -m uvicorn app.main:app --reload
```

Teste:
```bash
curl -s http://localhost:8000/health
```

---

## Uso da API

### Criar job
```bash
curl -X POST "http://localhost:8000/v1/jobs" \
  -F "file=@/caminho/musica.mp3" \
  -F "min_silence_ms=450" \
  -F "keep_silence_ms=150" \
  -F "min_segment_ms=800" \
  -F "max_segment_ms=12000"
```

### Criar job com ASR
```bash
curl -X POST "http://localhost:8000/v1/jobs" \
  -F "file=@/caminho/musica.mp3" \
  -F "do_asr=true" \
  -F "asr_model=base" \
  -F "asr_language=en" \
  -F "asr_context_ms=500" \
  -F "asr_refine_boundaries=true"
```

> Nota: na primeira execução, o faster-whisper normalmente baixa o modelo (precisa de internet).

### Criar job com ASR + Tradução (LibreTranslate)
1) Rode LibreTranslate local (exemplo em Docker):
```bash
docker run -p 5000:5000 libretranslate/libretranslate
```
2) Suba a API com a variável de ambiente:
```bash
LIBRETRANSLATE_URL=http://localhost:5000 python -m uvicorn app.main:app --reload
```
3) Request:
```bash
curl -X POST "http://localhost:8000/v1/jobs" \
  -F "file=@/caminho/musica.mp3" \
  -F "do_asr=true" \
  -F "do_translate=true" \
  -F "translate_provider=libretranslate" \
  -F "translate_to=pt"
```

Resposta:
- `job_id`
- URLs para polling e download

### Checar status
```bash
curl "http://localhost:8000/v1/jobs/<job_id>"
```

### Baixar zip com trechos
```bash
curl -L -o segments.zip "http://localhost:8000/v1/jobs/<job_id>/segments.zip"
```

---

## Isolamento vocal (opcional)
Se você quiser tentar usar Demucs (melhor para separar frases em música com instrumental), rode com:

- Instalar demucs:
  ```bash
  pip install demucs
  ```
- Habilitar no servidor:
  ```bash
  ENABLE_DEMUCS=1 uvicorn app.main:app --reload
  ```
- No request, mandar `use_vocals=true`:
  ```bash
  -F "use_vocals=true"
  ```

---

## Próximos passos sugeridos
1) Adicionar endpoint síncrono (ou websocket de progresso)
2) Ajustar heurísticas de silêncio por faixa vocal (threshold adaptativo)
3) Persistência melhor (S3/MinIO) e fila (Celery/RQ)
4) Export Anki (.apkg)
