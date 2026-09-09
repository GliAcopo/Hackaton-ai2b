"""Adattatore LLM: un'interfaccia, due backend.

Perché così: la mattina dell'hackathon non sai ancora se gli organizzatori
ti daranno una API key. Con questo file la risposta cambia UNA variabile
d'ambiente, non l'architettura.

    LLM_BACKEND=ollama                      # default, gira offline
    LLM_BACKEND=openai LLM_API_KEY=sk-...   # qualunque endpoint compatibile

Misurato su questa macchina (RTX 4050, 6 GB):
    llama3.1:8b   ->  6 tok/s   (offload parziale, 30/33 layer: inusabile)
    llama3.2:3b   -> 68 tok/s   (full offload)
Da cui il default.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BACKEND = os.environ.get("LLM_BACKEND", "ollama")
MODEL = os.environ.get("LLM_MODEL", "llama3.2:3b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
API_BASE = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
API_KEY = os.environ.get("LLM_API_KEY", "")
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "90"))


class LLMError(RuntimeError):
    pass


def _post(url: str, payload: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise LLMError(f"{url}: {exc}") from exc


def complete_json(prompt: str, schema: dict, system: str = "") -> dict:
    """Genera un oggetto JSON conforme a `schema`.

    Il vincolo di schema è il punto: l'LLM non è una chat, è un componente
    che restituisce un dato tipizzato dentro una pipeline. Se il modello
    delira, deliria *dentro* le chiavi che ti aspetti, e il resto dell'app
    continua a funzionare.
    """
    if BACKEND == "ollama":
        data = _post(
            f"{OLLAMA_URL}/api/generate",
            {
                "model": MODEL,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "format": schema,  # Ollama accetta uno JSON Schema completo
                "options": {"temperature": 0.4, "num_ctx": 4096},
            },
        )
        raw = data.get("response", "")
    else:
        if not API_KEY:
            raise LLMError("LLM_BACKEND=openai ma LLM_API_KEY non è impostata")
        data = _post(
            f"{API_BASE}/chat/completions",
            {
                "model": MODEL,
                "messages": (
                    ([{"role": "system", "content": system}] if system else [])
                    + [{"role": "user", "content": prompt}]
                ),
                "temperature": 0.4,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "risposta",
                        "schema": schema,
                        "strict": True,
                    },
                },
            },
            {"Authorization": f"Bearer {API_KEY}"},
        )
        raw = data["choices"][0]["message"]["content"]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"risposta non JSON: {raw[:200]!r}") from exc


def health() -> str:
    """Da chiamare all'inizio della giornata, non alle 17:30."""
    if BACKEND == "ollama":
        try:
            with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
                names = [m["name"] for m in json.loads(r.read())["models"]]
        except Exception as exc:  # noqa: BLE001
            return f"KO  ollama non raggiungibile ({exc}) — lancia `ollama serve`"
        ok = "OK " if MODEL in names else "KO "
        return f"{ok} backend=ollama model={MODEL} disponibili={names}"
    return f"{'OK ' if API_KEY else 'KO '} backend={BACKEND} base={API_BASE} model={MODEL}"


if __name__ == "__main__":
    print(health())
