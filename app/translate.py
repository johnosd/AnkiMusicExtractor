from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class TranslationError(RuntimeError):
    pass


def normalize_lang(code: Optional[str]) -> str:
    if not code:
        return ""
    code = code.strip().lower()
    if code in {"pt-br", "pt_br"}:
        return "pt"
    if "-" in code:
        return code.split("-", 1)[0]
    if "_" in code:
        return code.split("_", 1)[0]
    return code


@dataclass(frozen=True)
class TranslateParams:
    enabled: bool = False
    target_lang: str = "pt"

    # provider: "none" | "libretranslate" | "argos"
    provider: str = "none"

    # LibreTranslate settings
    libre_url: str = ""
    libre_api_key: str = ""


def translate_text(text: str, *, source_lang: str, params: TranslateParams) -> str:
    if not params.enabled:
        return ""
    provider = (params.provider or "none").strip().lower()
    if provider == "none":
        raise TranslationError(
            "Tradução habilitada, mas translate_provider='none'. "
            "Defina translate_provider=libretranslate (recomendado) ou argos."
        )
    if provider == "libretranslate":
        return _translate_libre(text, source_lang=source_lang, target_lang=params.target_lang, url=params.libre_url, api_key=params.libre_api_key)
    if provider == "argos":
        return _translate_argos(text, source_lang=source_lang, target_lang=params.target_lang)
    raise TranslationError(f"Provider de tradução inválido: {params.provider}")


def _translate_libre(text: str, *, source_lang: str, target_lang: str, url: str, api_key: str = "") -> str:
    url = (url or "").rstrip("/")
    if not url:
        raise TranslationError(
            "LIBRETRANSLATE_URL não configurado. "
            "Ex.: http://localhost:5000 (se você estiver rodando LibreTranslate local)."
        )

    try:
        import httpx
    except Exception as e:  # pragma: no cover
        raise TranslationError("Dependência 'httpx' não encontrada. Rode: pip install -r requirements.txt") from e

    src = normalize_lang(source_lang) or "auto"
    tgt = normalize_lang(target_lang)

    payload = {
        "q": text,
        "source": src,
        "target": tgt,
        "format": "text",
    }
    if api_key:
        payload["api_key"] = api_key

    endpoint = f"{url}/translate"

    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(endpoint, json=payload)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        raise TranslationError(f"Falha ao traduzir via LibreTranslate ({endpoint}): {e}") from e

    translated = data.get("translatedText")
    if not isinstance(translated, str):
        raise TranslationError(f"Resposta inesperada do LibreTranslate: {data}")
    return translated


def _translate_argos(text: str, *, source_lang: str, target_lang: str) -> str:
    """Offline translation using Argos Translate (requires language packages installed)."""
    try:
        from argostranslate import translate as argos_translate  # type: ignore
    except Exception as e:  # pragma: no cover
        raise TranslationError(
            "Para usar provider='argos', instale argostranslate e os pacotes de idioma."
        ) from e

    src = normalize_lang(source_lang)
    tgt = normalize_lang(target_lang)
    if not src or not tgt:
        raise TranslationError("Argos precisa de source_lang e target_lang explícitos (ex.: 'en' -> 'pt').")

    try:
        installed = argos_translate.get_installed_languages()
        from_lang = next((l for l in installed if l.code == src), None)
        to_lang = next((l for l in installed if l.code == tgt), None)
        if not from_lang or not to_lang:
            raise TranslationError(
                f"Pacotes Argos não instalados para {src}->{tgt}. "
                "Instale os packages de idioma do Argos Translate antes de usar."
            )
        translation = from_lang.get_translation(to_lang)
        return translation.translate(text)
    except TranslationError:
        raise
    except Exception as e:
        raise TranslationError(f"Falha ao traduzir via Argos: {e}") from e
