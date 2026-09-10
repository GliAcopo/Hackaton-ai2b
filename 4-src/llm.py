"""Adattatore LLM: un'interfaccia, tre backend, una catena di fallback.

Perché così: alla tappa non sai in anticipo cosa avrai. Con questo file la
risposta cambia UNA variabile d'ambiente, non l'architettura.

    LLM_BACKEND=agy       # default: Antigravity CLI, JSON Schema nativo
    LLM_BACKEND=ollama    # offline, nessuna rete
    LLM_BACKEND=openai    # qualunque endpoint compatibile, serve LLM_API_KEY

Misurato su questa macchina il giorno della tappa:
    agy gemini-3.8-flash-low  -> 3.4 s di modello, ~7 s wall, ~20k token/chiamata
    ollama llama3.2:3b        -> 68 tok/s, gira staccato dalla rete

I 20k token di overhead fisso per chiamata di `agy` sono la ragione per cui la
cache su disco NON è un optional: è la differenza fra una demo che gira e una
che finisce la quota alle 16:00.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = os.environ.get("LLM_BACKEND", "agy")
MODEL = os.environ.get("LLM_MODEL", "gemini-3.8-flash-low")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
API_BASE = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
API_KEY = os.environ.get("LLM_API_KEY", "")
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "120"))

RADICE = Path(__file__).resolve().parent.parent
CACHE = RADICE / "2-data" / "cache" / "llm.json"
REGISTRO = RADICE / "3-docs" / "decisioni.jsonl"

# Interruttore per la prova "demo con la rete staccata": con LLM_SOLO_CACHE=1
# nessun backend viene interpellato, si risponde solo da cache.
SOLO_CACHE = os.environ.get("LLM_SOLO_CACHE", "") == "1"

# Lo specchio esatto di SOLO_CACHE: con LLM_LIVE=1 (o `--live` sulla riga di
# comando) la cache NON viene letta e il modello risponde davvero, ogni volta.
# Serve a due cose diverse: provare che il sistema funziona anche senza niente
# di precalcolato, e rigenerare risposte diventate vecchie.
# La cache viene comunque SCRITTA: una passata live lascia la demo pronta a
# girare offline subito dopo, che e' esattamente quello che serve al freeze.
LIVE = os.environ.get("LLM_LIVE", "") == "1"


class LLMError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Cache su disco. Chiave = hash(prompt + system + schema): due domande identiche
# non pagano due volte. Sopravvive al riavvio del processo, che e' il punto:
# gli output della demo si precalcolano e poi restano.
# --------------------------------------------------------------------------

def _chiave(prompt: str, schema: dict, system: str) -> str:
    grezzo = json.dumps([system, prompt, schema], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(grezzo.encode("utf-8")).hexdigest()[:32]


def _leggi_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _scrivi_cache(chiave: str, valore: dict) -> None:
    dati = _leggi_cache()
    dati[chiave] = valore
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")


def _registra(backend: str, prompt: str, esito: dict, secondi: float) -> None:
    """Registro delle decisioni: ogni chiamata IA lascia una traccia.

    Non e' cerimonia: e' la risposta a "come tracciate le decisioni del modello?".
    """
    riga = {
        "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "backend": backend,
        "modello": MODEL if backend == "agy" else OLLAMA_MODEL,
        "secondi": round(secondi, 2),
        "prompt": prompt[:400],
        "esito": esito,
    }
    try:
        REGISTRO.parent.mkdir(parents=True, exist_ok=True)
        with REGISTRO.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(riga, ensure_ascii=False) + "\n")
    except OSError:
        pass  # il registro non deve mai far cadere una demo


# --------------------------------------------------------------------------
# Backend
# --------------------------------------------------------------------------

def _post(url: str, payload: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f"{url}: {exc}") from exc


def _via_agy(prompt: str, schema: dict, system: str) -> dict:
    """Antigravity CLI. Ha --json-schema nativo: niente parsing del testo.

    Due dettagli che costano un'ora se non li sai:
      - stdin=DEVNULL e' obbligatorio, altrimenti il CLI aspetta 3 secondi su
        stdin prima di partire.
      - la risposta contiene gia' `structured_output`, un dict conforme allo
        schema. Il campo `response` e' la stessa cosa ma come stringa, e puo'
        contenere chiavi extra: usare `structured_output`.
    """
    completo = f"{system}\n\n{prompt}" if system else prompt
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(schema, fh)
        percorso_schema = fh.name
    try:
        proc = subprocess.run(
            ["agy", "-p", completo,
             "--model", MODEL,
             "--json-schema", percorso_schema,
             "--output-format", "json",
             "--disable-slash-commands"],
            capture_output=True, text=True, timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise LLMError(f"agy: {exc}") from exc
    finally:
        os.unlink(percorso_schema)

    if proc.returncode != 0:
        raise LLMError(f"agy uscita {proc.returncode}: {proc.stderr[:300]}")
    for riga in proc.stdout.splitlines():
        riga = riga.strip()
        if not riga.startswith("{"):
            continue
        try:
            dati = json.loads(riga)
        except json.JSONDecodeError:
            continue
        if isinstance(dati.get("structured_output"), dict):
            return dati["structured_output"]
    raise LLMError(f"agy: nessun structured_output in {proc.stdout[:300]!r}")


def _via_ollama(prompt: str, schema: dict, system: str) -> dict:
    dati = _post(
        f"{OLLAMA_URL}/api/generate",
        {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "format": schema,  # Ollama accetta uno JSON Schema completo
            "options": {"temperature": 0.3, "num_ctx": 4096},
        },
    )
    grezzo = dati.get("response", "")
    try:
        return json.loads(grezzo)
    except json.JSONDecodeError as exc:
        raise LLMError(f"ollama: risposta non JSON: {grezzo[:200]!r}") from exc


def _via_openai(prompt: str, schema: dict, system: str) -> dict:
    if not API_KEY:
        raise LLMError("LLM_BACKEND=openai ma LLM_API_KEY non e' impostata")
    dati = _post(
        f"{API_BASE}/chat/completions",
        {
            "model": MODEL,
            "messages": (([{"role": "system", "content": system}] if system else [])
                         + [{"role": "user", "content": prompt}]),
            "temperature": 0.3,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "risposta", "schema": schema, "strict": True},
            },
        },
        {"Authorization": f"Bearer {API_KEY}"},
    )
    return json.loads(dati["choices"][0]["message"]["content"])


BACKENDS = {"agy": _via_agy, "ollama": _via_ollama, "openai": _via_openai}


# --------------------------------------------------------------------------
# Interfaccia pubblica
# --------------------------------------------------------------------------

def complete_json(prompt: str, schema: dict, system: str = "") -> dict:
    """Genera un oggetto JSON conforme a `schema`.

    Il vincolo di schema e' il punto: l'LLM non e' una chat, e' un componente
    che restituisce un dato tipizzato dentro una pipeline. Se il modello delira,
    delira *dentro* le chiavi che ti aspetti, e il resto dell'app continua.

    Catena: cache -> backend primario -> ollama -> LLMError.
    Chi chiama gestisce LLMError con un fallback statico (vedi ai.py).
    """
    chiave = _chiave(prompt, schema, system)
    cache = _leggi_cache()
    if chiave in cache and not LIVE:
        return cache[chiave]
    if SOLO_CACHE:
        raise LLMError("LLM_SOLO_CACHE=1 e la risposta non e' in cache")

    ordine = [BACKEND] + [b for b in ("ollama",) if b != BACKEND]
    errori = []
    for nome in ordine:
        funzione = BACKENDS.get(nome)
        if funzione is None:
            continue
        inizio = time.monotonic()
        try:
            esito = funzione(prompt, schema, system)
        except LLMError as exc:
            errori.append(f"{nome}: {exc}")
            continue
        secondi = time.monotonic() - inizio
        _scrivi_cache(chiave, esito)
        _registra(nome, prompt, esito, secondi)
        return esito
    raise LLMError(" | ".join(errori) or "nessun backend disponibile")


def health() -> str:
    """Da chiamare all'inizio della giornata, non alle 17:30."""
    righe = []
    try:
        proc = subprocess.run(["agy", "--help"], capture_output=True, text=True,
                              timeout=20, stdin=subprocess.DEVNULL)
        ok = "OK " if proc.returncode == 0 else "KO "
        righe.append(f"{ok} agy model={MODEL}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        righe.append(f"KO  agy non disponibile ({type(exc).__name__})")
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
            nomi = [m["name"] for m in json.loads(r.read())["models"]]
        ok = "OK " if OLLAMA_MODEL in nomi else "KO "
        righe.append(f"{ok} ollama model={OLLAMA_MODEL} disponibili={len(nomi)}")
    except Exception as exc:  # noqa: BLE001
        righe.append(f"KO  ollama non raggiungibile ({exc})")
    modo = ("LIVE (cache ignorata in lettura)" if LIVE
            else "SOLO CACHE (nessun backend)" if SOLO_CACHE
            else "cache, poi modello")
    righe.append(f"--  cache: {len(_leggi_cache())} risposte memorizzate  [{modo}]")
    righe.append(f"--  backend primario: {BACKEND}")
    return "\n".join(righe)


if __name__ == "__main__":
    print(health())
