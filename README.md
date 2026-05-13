# Music Phrase Segmenter API (MVP)

Backend que recebe um arquivo de musica e:

1) segmenta em trechos (MP3) usando pausas (silencio)
2) opcionalmente faz ASR (transcricao) por trecho
3) opcionalmente faz traducao por trecho

## Principais recursos
- Upload via HTTP (multipart/form-data)
- Segmentacao por silencio (pydub)
- ASR local (faster-whisper) com timestamps de palavras (opcional)
- Refino simples de inicio e fim do trecho com base na primeira e ultima palavra reconhecida (opcional)
- Traducao por trecho usando LibreTranslate em container local
- Exporta trechos em `segments/*.mp3` + `segments.json` + `segments.zip`
- Job assincrono simples com FastAPI BackgroundTasks

> Observacao: em musica com instrumental forte, o silencio no mix pode nao existir.
> Para melhorar, voce pode habilitar isolamento vocal via Demucs (opcional).

---

## Rodando com Docker Compose

Esse projeto pode subir com 2 containers:
- `api`: sua API FastAPI
- `libretranslate`: servico local de traducao usado pela API

### 1) Instale o Docker
Verifique se o Docker e o Docker Compose estao instalados e em execucao.

### 2) Ir para a pasta do projeto
Entre na pasta onde estao `Dockerfile`, `docker-compose.yml`, `requirements.txt` e a pasta `app/`.

```bash
ls
# deve mostrar algo como:
# Dockerfile  docker-compose.yml  requirements.txt  app/  README.md
```

### 3) Criar a pasta de dados
Essa pasta sera usada para persistir jobs e arquivos gerados.

```bash
mkdir -p data
```

### 4) Subir os containers
No root do projeto, rode:

```bash
docker compose up --build
```

Isso vai:
- buildar a imagem da API
- subir a API em `http://localhost:8000`
- subir o LibreTranslate em `http://localhost:5000`
- mapear `./data` para `/data` dentro da API

### 5) Testar a API

```bash
curl -s http://localhost:8000/health
```

### Interface web

Acesse `http://localhost:8000/` no navegador para a UI completa: upload, escolha do modo (Lyrics/ASR), tradução, polling de status e preview dos segmentos com player de áudio + downloads (TSV, ZIP, JSON).

Para parar:

```bash
docker compose down
```

---

## Uso da API

### Enviar musica
Os exemplos abaixo assumem que o arquivo `Take_Bow.mp3` esta em `app/input/Take_Bow.mp3`.

Se voce estiver na raiz do projeto (`Dockerfile`, `docker-compose.yml`, `README.md`), use `app/input/Take_Bow.mp3` no `-F "file=@..."`.

Se preferir usar `input/Take_Bow.mp3`, entre primeiro na pasta `app/`:

```bash
cd app
```

Exemplo com ASR e timestamps por palavra:

```bash
curl -X POST "http://localhost:8000/v1/jobs" \
  -F "file=@./app/input/Take_Bow.mp3" \
  -F "do_asr=true" \
  -F "asr_model=base" \
  -F "asr_word_timestamps=true"
```

No PowerShell, a partir da raiz do projeto, use `curl.exe` e continue linha com crase `` ` ``:

```powershell
curl.exe -X POST "http://localhost:8000/v1/jobs" `
  -F "file=@app/input/Take_Bow.mp3" `
  -F "do_asr=true" `
  -F "asr_model=base" `
  -F "asr_word_timestamps=true"
```

Se voce fizer `cd app` antes, ai sim use:

```powershell
curl.exe -X POST "http://localhost:8000/v1/jobs" `
  -F "file=@input/Take_Bow.mp3" `
  -F "do_asr=true" `
  -F "asr_model=base" `
  -F "asr_word_timestamps=true"
```

Ou com idioma e refinamento de trechos:

```bash
curl -X POST "http://localhost:8000/v1/jobs" \
  -F "file=@./app/input/Take_Bow.mp3" \
  -F "do_asr=true" \
  -F "asr_model=base" \
  -F "asr_language=en" \
  -F "asr_context_ms=500" \
  -F "asr_refine_boundaries=true"
```

```powershell
curl.exe -X POST "http://localhost:8000/v1/jobs" `
  -F "file=@app/input/Take_Bow.mp3" `
  -F "do_asr=true" `
  -F "asr_model=base" `
  -F "asr_language=en" `
  -F "asr_context_ms=500" `
  -F "asr_refine_boundaries=true"
```

> Nota: na primeira execucao, o faster-whisper normalmente baixa o modelo e precisa de internet.

### Enviar musica com traducao por trecho
Com o `docker compose` em execucao, a API ja estara configurada para usar o LibreTranslate local.

```bash
curl -X POST "http://localhost:8000/v1/jobs" \
  -F "file=@./app/input/Take_Bow.mp3" \
  -F "do_asr=true" \
  -F "do_translate=true" \
  -F "translate_to=pt" \
  -F "asr_model=base" \
  -F "asr_language=en"
```

```powershell
curl.exe -X POST "http://localhost:8000/v1/jobs" `
  -F "file=@app/input/Take_Bow.mp3" `
  -F "do_asr=true" `
  -F "do_translate=true" `
  -F "translate_to=pt" `
  -F "asr_model=base" `
  -F "asr_language=en"
```

Se quiser forcar explicitamente o provider no request:

```bash
curl -X POST "http://localhost:8000/v1/jobs" \
  -F "file=@./app/input/Take_Bow.mp3" \
  -F "do_asr=true" \
  -F "do_translate=true" \
  -F "translate_provider=libretranslate" \
  -F "translate_to=pt"
```

```powershell
curl.exe -X POST "http://localhost:8000/v1/jobs" `
  -F "file=@app/input/Take_Bow.mp3" `
  -F "do_asr=true" `
  -F "do_translate=true" `
  -F "translate_provider=libretranslate" `
  -F "translate_to=pt"
```

Resposta:
- `job_id`
- URLs para polling e download

### Checar status
```bash
curl "http://localhost:8000/v1/jobs/e1b3c05652fe455486eaa5bdff977a51
```

### Baixar zip com trechos
```bash
curl -L -o segments.zip "http://localhost:8000/v1/jobs/c8764d58999c40ef9db7b9bdaebfbded/segments.zip"
```

---

## Docker Compose

O arquivo `docker-compose.yml`:
- expoe a API na porta `8000`
- expoe o LibreTranslate na porta `5000`
- persiste os jobs em `./data`
- persiste o cache do Hugging Face em um volume nomeado
- configura `TRANSLATE_PROVIDER=libretranslate`
- configura `LIBRETRANSLATE_URL=http://libretranslate:5000`

Assim, a traducao por trecho funciona sem depender de um servico externo hospedado fora da sua maquina.

---

## Modo lyrics (v0.3, recomendado)

Em vez de extrair o texto da musica com ASR (que erra), este modo identifica a musica, baixa a letra sincronizada do LRCLib e corta o audio diretamente pelos timestamps da letra. Saida adicional: `cards.tsv` pronto para importar no Anki.

### Exemplo

```bash
curl -X POST "http://localhost:8000/v1/jobs" \
  -F "file=@./app/input/Love Yourself.mp3" \
  -F "use_lyrics=true" \
  -F "artist=Justin Bieber" \
  -F "title=Love Yourself" \
  -F "do_translate=true" \
  -F "translate_to=pt"
```

Se o arquivo tiver tags ID3 com artista e titulo, `artist`/`title` no form sao opcionais. Voce pode tambem informar so um dos dois para sobrescrever parcialmente o ID3.

### Download dos cards

```bash
curl -L -o cards.tsv "http://localhost:8000/v1/jobs/{job_id}/cards.tsv"
```

No Anki: File -> Import -> escolher o `cards.tsv`, delimitador Tab, mapear colunas `[sound:...]` / texto L2 / traducao L1 / tags. Os MP3 estao no `segments.zip` (extrair em `collection.media` do seu profile Anki).

### Parametros do modo lyrics
- `use_lyrics=true` ativa o pipeline
- `artist`, `title`, `album` (opcionais) sobrescrevem ID3
- `granularity=line` (unico valor no MVP — 1 card por linha da letra)
- `max_line_ms=10000` cap do `end_ms` para nao colar instrumental longo no fim da linha
- `do_translate`, `translate_to` funcionam igual ao modo classico

### Quando isso falha
- Letra nao encontrada no LRCLib → resposta 400 com mensagem clara. Verifique artista/titulo (LRCLib casa por texto + duracao).
- Musica sem letra sincronizada (so plana) → MVP nao alinha; fallback com forced alignment (WhisperX) fica para a v0.4.

---

## Isolamento vocal (opcional)
Se voce quiser tentar usar Demucs, rode com:

- Instalar demucs:
  ```bash
  pip install demucs
  ```
- Habilitar no servidor:
  ```bash
  ENABLE_DEMUCS=1 uvicorn app.main:app --reload
  ```
- No request, enviar `use_vocals=true`:
  ```bash
  -F "use_vocals=true"
  ```
