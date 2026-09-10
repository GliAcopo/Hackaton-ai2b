"""Client meteo/qualità dell'aria per il monitoraggio dei pronto soccorso del Lazio.

Tutto stdlib (urllib, json, hashlib, time, pathlib): niente pip install,
perché il giorno della demo la rete del venue è la prima cosa che salta.

Tre fonti, tutte Open-Meteo, tutte gratuite e senza API key:
  - forecast (meteo attuale)     -> meteo_corrente()
  - archive  (meteo storico)     -> meteo_storico(), ci serve perché lo
    snapshot dei pronto soccorso è fermo al 2021-07-15 16:58 e vogliamo
    il contesto meteo VERO di quel giorno, non quello di oggi.
  - air-quality (pollini/polveri) -> qualita_aria()

Ogni funzione restituisce sempre un dict con la chiave "fonte" valorizzata
a "open-meteo" (dato fresco dalla rete), "cache" (dato letto dal disco,
fresco o scaduto poco importa) o "non disponibile" (rete giù E cache vuota).
In quest'ultimo caso il dict porta `disponibile: False` e NESSUN numero: non
esistono valori di ripiego inventati, perché finivano nel prompt del bollettino
e ne uscivano allerte costruite su un meteo che nessuno aveva misurato.
La UI mostra "fonte" all'utente, quindi deve essere sempre presente e vera.

Cache su disco in 2-data/cache/meteo.json e 2-data/cache/aria.json, un
file per servizio, scrittura atomica (file temporaneo + rename) così un
crash a metà scrittura non corrompe la cache. La chiave di cache è un
hash stabile delle coordinate arrotondate a 3 decimali (~100 m: più che
sufficiente per un pronto soccorso, e aumenta parecchio i cache hit fra
richieste "quasi uguali").

Le URL di base sono variabili di modulo leggibili da env var
(METEO_FORECAST_URL, METEO_ARCHIVE_URL, METEO_ARIA_URL): puntandole a un
host inesistente si simula un'assenza di rete senza toccare il codice,
utile sia nei test sia se un giorno servisse un mirror/proxy.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

# --- Configurazione -------------------------------------------------------

# Radice del progetto: questo file vive in 4-src/, la cache in 2-data/cache/.
CACHE_DIR = Path(__file__).resolve().parent.parent / "2-data" / "cache"
FILE_CACHE_METEO = "meteo.json"  # meteo corrente + storico, chiavi separate
FILE_CACHE_ARIA = "aria.json"

TIMEOUT_S = 10.0  # oltre i 10s in una demo dal vivo l'attesa è già persa

TTL_CORRENTE_S = 30 * 60  # 30 minuti: il meteo attuale invecchia in fretta
TTL_ARIA_S = 30 * 60
TTL_STORICO_S = float("inf")  # il meteo di un giorno passato non cambia mai

URL_FORECAST = os.environ.get("METEO_FORECAST_URL", "https://api.open-meteo.com/v1/forecast")
URL_ARCHIVE = os.environ.get("METEO_ARCHIVE_URL", "https://archive-api.open-meteo.com/v1/archive")
URL_ARIA = os.environ.get("METEO_ARIA_URL", "https://air-quality-api.open-meteo.com/v1/air-quality")


# --- Cache su disco ---------------------------------------------------------

# Mirror in memoria per processo: evita di riparsare il JSON su disco a ogni
# singola chiamata quando le funzioni vengono invocate ripetutamente nello
# stesso processo (es. tante località in sequenza). Ogni scrittura resta
# comunque immediata su disco (la cache deve sopravvivere al riavvio).
_cache_mem: dict[str, dict] = {}


def _iso(epoch: float | None) -> str | None:
    """Epoch -> ISO 8601. Serve a distinguere quando il dato e' stato
    ACQUISITO da quando lo stiamo rileggendo."""
    from datetime import datetime
    return datetime.fromtimestamp(epoch).isoformat(timespec="seconds") if epoch else None


def _percorso_cache(nome_file: str) -> Path:
    """Ritorna il path del file di cache, creando la cartella se manca."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / nome_file


def _carica_cache(nome_file: str) -> dict:
    """Legge la cache (dal mirror in memoria se già caricata, altrimenti dal
    file su disco). Se il file manca o è corrotto, riparte da vuoto invece
    di sollevare: una cache illeggibile non deve fermare la demo."""
    if nome_file in _cache_mem:
        return _cache_mem[nome_file]
    percorso = _percorso_cache(nome_file)
    if not percorso.exists():
        dati = {}
    else:
        try:
            with percorso.open("r", encoding="utf-8") as f:
                dati = json.load(f)
        except (json.JSONDecodeError, OSError):
            dati = {}
    _cache_mem[nome_file] = dati
    return dati


def _salva_cache(nome_file: str, dati: dict) -> None:
    """Scrive la cache su disco subito (niente buffer in memoria che si perde
    al riavvio del processo). Scrittura atomica: file temporaneo + rename,
    così un crash a metà non lascia un JSON a metà scritto."""
    _cache_mem[nome_file] = dati
    percorso = _percorso_cache(nome_file)
    temp = percorso.parent / (percorso.name + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    temp.replace(percorso)


def _chiave(*parti) -> str:
    """Hash stabile degli argomenti (già arrotondati dal chiamante), usato
    come chiave nel dizionario di cache."""
    testo = json.dumps(parti, sort_keys=True)
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()[:20]


def _http_get_json(url: str) -> dict:
    """GET generico con timeout, ritorna il body decodificato come JSON.
    Le eccezioni (rete giù, timeout, JSON malformato...) non sono catturate
    qui: la responsabilità di decidere il fallback è di chi chiama."""
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
        corpo = resp.read().decode("utf-8")
    return json.loads(corpo)


# --- Assenza del dato: dichiarata, MAI sostituita con numeri plausibili ----
#
# Qui prima c'erano tre funzioni che restituivano una giornata romana media
# (20 C, PM10 15, pollini a zero) quando rete e cache erano entrambe vuote.
# Serviva a non lasciare l'interfaccia a pezzi, ma il prezzo era troppo alto:
# quei numeri finivano nel prompt del bollettino e ne uscivano gruppi
# vulnerabili e azioni pratiche costruiti su un meteo che nessuno aveva
# misurato. Un'allerta calcolata su un dato inventato e' peggio di nessuna
# allerta, perche' e' indistinguibile da una vera.
#
# Adesso l'assenza si dichiara: `disponibile: False`, nessuna chiave numerica,
# e chi chiama decide cosa mostrare. Il bollettino IA non viene proprio
# generato (vedi app._bollettino).

def _non_disponibile(motivo: str, **extra) -> dict:
    return {"disponibile": False, "fonte": "non disponibile",
            "motivo": motivo, **extra}


# --- API pubblica ------------------------------------------------------------

def meteo_corrente(lat: float, lon: float) -> dict:
    """Meteo attuale per un punto (lat, lon).

    Ritorna: {temperatura_c, percepita_c, umidita_pct, precipitazione_mm,
    vento_kmh, codice_meteo, rilevato_il, fonte}.

    Ordine dei tentativi: cache fresca (< 30 min) -> rete -> cache scaduta
    (se la rete fallisce) -> dato dichiarato NON DISPONIBILE.
    Non esiste piu' un ripiego con valori plausibili: vedi _non_disponibile.
    """
    lat_r, lon_r = round(lat, 3), round(lon, 3)
    chiave = _chiave("corrente", lat_r, lon_r)
    cache = _carica_cache(FILE_CACHE_METEO)
    voce = cache.get(chiave)
    adesso = time.time()

    if voce is not None and (adesso - voce["ts"]) < TTL_CORRENTE_S:
        return {**voce["dati"], "fonte": "cache", "disponibile": True,
                "acquisito_il": _iso(voce["ts"])}

    parametri = urllib.parse.urlencode({
        "latitude": lat_r,
        "longitude": lon_r,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "precipitation,weather_code,wind_speed_10m",
        "timezone": "Europe/Rome",
    })
    url = f"{URL_FORECAST}?{parametri}"

    try:
        grezzo = _http_get_json(url)
        corrente = grezzo["current"]
        dati = {
            "temperatura_c": corrente["temperature_2m"],
            "percepita_c": corrente["apparent_temperature"],
            "umidita_pct": corrente["relative_humidity_2m"],
            "precipitazione_mm": corrente["precipitation"],
            "vento_kmh": corrente["wind_speed_10m"],
            "codice_meteo": corrente["weather_code"],
            "rilevato_il": corrente["time"],
        }
        cache[chiave] = {"ts": adesso, "dati": dati}
        _salva_cache(FILE_CACHE_METEO, cache)
        return {**dati, "fonte": "open-meteo", "disponibile": True,
                "acquisito_il": _iso(time.time())}
    except Exception as exc:
        # Rete giù, timeout, JSON inatteso: un dato vecchio va bene purche'
        # dichiarato tale. Un dato inventato no, a nessuna condizione.
        if voce is not None:
            return {**voce["dati"], "fonte": "cache",
                    "disponibile": True,
                    "acquisito_il": _iso(voce["ts"])}
        return _non_disponibile(f"meteo non raggiungibile e cache vuota ({type(exc).__name__})")


def meteo_storico(lat: float, lon: float, data: str) -> dict:
    """Meteo storico di un giorno preciso, es. data="2021-07-15".

    Ritorna: {t_max_c, t_min_c, percepita_max_c, precipitazione_mm, data, fonte}.
    TTL infinito: il meteo di un giorno passato non cambia più, quindi una
    volta in cache ci resta per sempre (niente ri-chiamate inutili all'API).
    """
    lat_r, lon_r = round(lat, 3), round(lon, 3)
    chiave = _chiave("storico", lat_r, lon_r, data)
    cache = _carica_cache(FILE_CACHE_METEO)
    voce = cache.get(chiave)

    if voce is not None:
        return {**voce["dati"], "fonte": "cache", "disponibile": True,
                "acquisito_il": _iso(voce["ts"])}

    parametri = urllib.parse.urlencode({
        "latitude": lat_r,
        "longitude": lon_r,
        "start_date": data,
        "end_date": data,
        "daily": "temperature_2m_max,apparent_temperature_max,"
                 "temperature_2m_min,precipitation_sum",
        "timezone": "Europe/Rome",
    })
    url = f"{URL_ARCHIVE}?{parametri}"

    try:
        grezzo = _http_get_json(url)
        giorno = grezzo["daily"]
        dati = {
            "t_max_c": giorno["temperature_2m_max"][0],
            "t_min_c": giorno["temperature_2m_min"][0],
            "percepita_max_c": giorno["apparent_temperature_max"][0],
            "precipitazione_mm": giorno["precipitation_sum"][0],
            "data": data,
        }
        cache[chiave] = {"ts": time.time(), "dati": dati}
        _salva_cache(FILE_CACHE_METEO, cache)
        return {**dati, "fonte": "open-meteo", "disponibile": True,
                "acquisito_il": _iso(time.time())}
    except Exception as exc:
        return _non_disponibile(
            f"archivio meteo non raggiungibile ({type(exc).__name__})", data=data)


def qualita_aria(lat: float, lon: float) -> dict:
    """Pollini e polveri sottili per un punto (lat, lon).

    Ritorna: {pm10, pm2_5, aqi_europeo,
              pollini: {graminacee, olivo, ambrosia, ontano, betulla},
              rilevato_il, fonte}.
    Stessa strategia cache/indisponibilita' di meteo_corrente (TTL 30 min).
    """
    lat_r, lon_r = round(lat, 3), round(lon, 3)
    chiave = _chiave("aria", lat_r, lon_r)
    cache = _carica_cache(FILE_CACHE_ARIA)
    voce = cache.get(chiave)
    adesso = time.time()

    if voce is not None and (adesso - voce["ts"]) < TTL_ARIA_S:
        return {**voce["dati"], "fonte": "cache", "disponibile": True,
                "acquisito_il": _iso(voce["ts"])}

    parametri = urllib.parse.urlencode({
        "latitude": lat_r,
        "longitude": lon_r,
        "current": "pm10,pm2_5,grass_pollen,olive_pollen,ragweed_pollen,"
                   "alder_pollen,birch_pollen,european_aqi",
        "timezone": "Europe/Rome",
    })
    url = f"{URL_ARIA}?{parametri}"

    try:
        grezzo = _http_get_json(url)
        corrente = grezzo["current"]
        dati = {
            "pm10": corrente["pm10"],
            "pm2_5": corrente["pm2_5"],
            "aqi_europeo": corrente["european_aqi"],
            "pollini": {
                "graminacee": corrente["grass_pollen"],
                "olivo": corrente["olive_pollen"],
                "ambrosia": corrente["ragweed_pollen"],
                "ontano": corrente["alder_pollen"],
                "betulla": corrente["birch_pollen"],
            },
            "rilevato_il": corrente["time"],
        }
        cache[chiave] = {"ts": adesso, "dati": dati}
        _salva_cache(FILE_CACHE_ARIA, cache)
        return {**dati, "fonte": "open-meteo", "disponibile": True,
                "acquisito_il": _iso(time.time())}
    except Exception as exc:
        if voce is not None:
            return {**voce["dati"], "fonte": "cache",
                    "disponibile": True,
                    "acquisito_il": _iso(voce["ts"])}
        return _non_disponibile(
            f"qualita' dell'aria non raggiungibile e cache vuota ({type(exc).__name__})")


# --- Smoke test --------------------------------------------------------------

if __name__ == "__main__":
    LAT, LON = 41.89, 12.49  # Roma

    print("=== Meteo corrente (Roma) ===")
    m1 = meteo_corrente(LAT, LON)
    print(m1)
    assert m1["fonte"] in ("open-meteo", "cache", "non disponibile")

    print("\n=== Meteo storico 2021-07-15 (Roma) ===")
    s1 = meteo_storico(LAT, LON, "2021-07-15")
    print(s1)
    if s1.get("disponibile"):
        assert abs(s1["t_max_c"] - 28.0) < 3.0, f"t_max fuori range atteso: {s1['t_max_c']}"
        print(f"OK: t_max_c = {s1['t_max_c']} (atteso ~28.0)")

    print("\n=== Qualità aria (Roma) ===")
    a1 = qualita_aria(LAT, LON)
    print(a1)

    print("\n--- Seconda chiamata: deve arrivare dalla cache ---")
    m2 = meteo_corrente(LAT, LON)
    s2 = meteo_storico(LAT, LON, "2021-07-15")
    a2 = qualita_aria(LAT, LON)
    print("meteo_corrente fonte:", m2["fonte"])
    print("meteo_storico fonte:", s2["fonte"])
    print("qualita_aria  fonte:", a2["fonte"])
    assert m2["fonte"] == "cache", "meteo_corrente non ha usato la cache alla seconda chiamata"
    assert s2["fonte"] == "cache", "meteo_storico non ha usato la cache alla seconda chiamata"
    assert a2["fonte"] == "cache", "qualita_aria non ha usato la cache alla seconda chiamata"

    print("\nOK: smoke test meteo.py superato.")
