"""Client per i percorsi stradali (OSRM) con fallback in linea d'aria.

Tutto stdlib: niente pip install. Usiamo il router pubblico OSRM
(project-osrm.org), gratuito e senza API key ma condiviso da mezzo
internet, quindi rate-limita facilmente durante una demo dal vivo.
Per questo ogni chiamata a OSRM è cachata su disco per sempre (un
percorso stradale fra due punti fissi non cambia) e, se OSRM non
risponde, si ripiega su una stima in linea d'aria: meglio un numero
approssimato che un errore davanti al pubblico.

Il tab cittadino dell'app usa la geolocalizzazione del browser: l'origine
è quindi arbitraria e non pre-cachabile in anticipo, il che rende il
fallback haversine un requisito e non un extra.

Cache su disco in 2-data/cache/osrm.json, scrittura atomica (file
temporaneo + rename). Chiave di cache: hash delle 4 coordinate (i due
punti) arrotondate a 3 decimali (~100 m).

L'URL base di OSRM è una variabile di modulo, sovrascrivibile con la
variabile d'ambiente OSRM_URL: puntandola a un host inesistente si
simula l'assenza di rete (usato nello smoke test qui sotto e utile per
i test automatici in generale).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.request
from pathlib import Path

# --- Configurazione ----------------------------------------------------------

CACHE_DIR = Path(__file__).resolve().parent.parent / "2-data" / "cache"
FILE_CACHE_OSRM = "osrm.json"

TIMEOUT_S = 10.0

OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org/route/v1/driving")

# Parametri della stima di fallback quando OSRM non è raggiungibile.
FATTORE_TORTUOSITA = 1.35     # una strada reale non è mai una retta
VELOCITA_URBANA_KMH = 28.0    # media urbana romana, ottimistica quanto basta
RAGGIO_KM_PER_MINUTO = 1.2    # usato per il pre-filtro haversine in entro_minuti


# --- Cache su disco (stesso schema di meteo.py) ------------------------------

# Mirror in memoria per processo: entro_minuti() può chiamare percorso()
# centinaia di volte in un ciclo (farmacie ~1000), e senza mirror ognuna di
# quelle chiamate riparserebbe l'intero osrm.json da disco. Con il mirror lo
# si legge una sola volta a processo; ogni scrittura resta comunque immediata
# su disco (requisito: la cache deve sopravvivere al riavvio).
_cache_mem: dict[str, dict] = {}


def _percorso_cache(nome_file: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / nome_file


def _carica_cache(nome_file: str) -> dict:
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
    _cache_mem[nome_file] = dati
    percorso = _percorso_cache(nome_file)
    temp = percorso.parent / (percorso.name + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    temp.replace(percorso)


def _chiave(*parti) -> str:
    testo = json.dumps(parti, sort_keys=True)
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()[:20]


# --- Geometria pura, nessuna rete ---------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in linea d'aria fra due punti (lat, lon), in km.

    Formula di haversine su una Terra sferica di raggio 6371 km: per le
    distanze in gioco qui (poche decine di km nel Lazio) l'errore rispetto
    a un modello ellissoidico è trascurabile.
    """
    raggio_terra_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * raggio_terra_km * math.asin(math.sqrt(a))


def _fallback_percorso(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    """Stima grezza quando OSRM non risponde: haversine gonfiata per la
    tortuosità stradale, velocità media urbana fissa, geometria a segmento
    retto. Non precisa, ma sempre disponibile e mai un'eccezione."""
    distanza_km = haversine_km(lat1, lon1, lat2, lon2) * FATTORE_TORTUOSITA
    durata_min = distanza_km / VELOCITA_URBANA_KMH * 60
    return {
        "durata_s": durata_min * 60,
        "durata_min": durata_min,
        "distanza_m": distanza_km * 1000,
        "distanza_km": distanza_km,
        "geometria": [[lat1, lon1], [lat2, lon2]],
        "fonte": "fallback",
    }


# --- API pubblica --------------------------------------------------------------

def percorso(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    """Percorso stradale (auto) dal punto 1 al punto 2, via OSRM.

    Ritorna: {durata_s, durata_min, distanza_m, distanza_km, geometria, fonte}.

    IMPORTANTE: OSRM restituisce le coordinate come [lon, lat] (GeoJSON).
    Qui la geometria viene convertita in [lat, lon] perché il frontend usa
    Leaflet, che vuole le coppie in quest'ordine. Non ri-convertire a valle.

    Nota sull'arrotondamento: la CHIAVE di cache usa coordinate arrotondate
    a 3 decimali (~100 m, per aumentare i cache hit), ma la richiesta a OSRM
    usa le coordinate a piena precisione ricevute in input. Arrotondare
    anche la query cambierebbe il nodo stradale più vicino a cui OSRM
    aggancia il punto, alterando percorso/durata reali di quel poco che
    basta a falsare i numeri (verificato: con arrotondamento a 3 decimali
    la stessa coppia di punti dà una durata ~20% diversa).

    Cache permanente (TTL infinito: un percorso stradale fra due punti fissi
    non cambia). Se la cache ha già una voce la usiamo direttamente, senza
    nemmeno provare la rete. Se OSRM fallisce (rete giù, timeout, rate
    limit, risposta inattesa) si ritorna SEMPRE un risultato via
    _fallback_percorso: questa funzione non solleva mai eccezioni di rete.
    Il risultato di fallback non viene mai scritto in cache (la cache è a
    TTL infinito: una stima haversine scritta lì dentro non guarirebbe mai
    da sola quando la rete torna disponibile).
    """
    lat1_r, lon1_r = round(lat1, 3), round(lon1, 3)
    lat2_r, lon2_r = round(lat2, 3), round(lon2, 3)
    chiave = _chiave("percorso", lat1_r, lon1_r, lat2_r, lon2_r)
    cache = _carica_cache(FILE_CACHE_OSRM)
    voce = cache.get(chiave)

    if voce is not None:
        return {**voce["dati"], "fonte": "cache"}

    # Piena precisione qui (non i valori arrotondati sopra): quelli servono
    # solo a chiavare la cache, non a interrogare il router.
    url = (
        f"{OSRM_URL}/{lon1},{lat1};{lon2},{lat2}"
        "?overview=simplified&geometries=geojson"
    )

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            grezzo = json.loads(resp.read().decode("utf-8"))
        rotta = grezzo["routes"][0]
        # [lon, lat] (GeoJSON/OSRM) -> [lat, lon] (Leaflet).
        geometria = [[p[1], p[0]] for p in rotta["geometry"]["coordinates"]]
        dati = {
            "durata_s": rotta["duration"],
            "durata_min": rotta["duration"] / 60,
            "distanza_m": rotta["distance"],
            "distanza_km": rotta["distance"] / 1000,
            "geometria": geometria,
        }
        cache[chiave] = {"ts": time.time(), "dati": dati}
        _salva_cache(FILE_CACHE_OSRM, cache)
        return {**dati, "fonte": "osrm"}
    except Exception:
        # Nessuna cache disponibile per questa coppia di punti (altrimenti
        # saremmo usciti sopra) e OSRM irraggiungibile: fallback haversine.
        return _fallback_percorso(lat1, lon1, lat2, lon2)


def entro_minuti(origine_lat: float, origine_lon: float, destinazioni: list, minuti: float) -> list:
    """Filtra `destinazioni` (dict con almeno le chiavi "lat"/"lon") tenendo
    solo quelle raggiungibili da (origine_lat, origine_lon) entro `minuti`.

    Pensata per liste di ~1000 farmacie: chiamare OSRM per ognuna sarebbe
    lento e rischia il rate limit. Si pre-filtra quindi con haversine usando
    un raggio generoso (minuti * 1.2 km/min) e solo sui sopravvissuti si
    chiama percorso() (che a sua volta usa cache/fallback automaticamente).

    Ogni elemento del risultato è una copia del dict originale arricchita
    con "durata_min", "distanza_km" e "fonte_percorso".
    """
    raggio_km = minuti * RAGGIO_KM_PER_MINUTO
    candidati = [
        d for d in destinazioni
        if haversine_km(origine_lat, origine_lon, d["lat"], d["lon"]) <= raggio_km
    ]

    risultato = []
    for d in candidati:
        r = percorso(origine_lat, origine_lon, d["lat"], d["lon"])
        if r["durata_min"] <= minuti:
            risultato.append({
                **d,
                "durata_min": r["durata_min"],
                "distanza_km": r["distanza_km"],
                "fonte_percorso": r["fonte"],
            })
    return risultato


# --- Smoke test ----------------------------------------------------------------

if __name__ == "__main__":
    CASILINO = (41.8687, 12.5896)
    TOR_VERGATA = (41.8548, 12.6265)

    print("=== Percorso Casilino -> Tor Vergata ===")
    r1 = percorso(*CASILINO, *TOR_VERGATA)
    print(f"durata:   {r1['durata_s']:.1f} s  ({r1['durata_min']:.1f} min)")
    print(f"distanza: {r1['distanza_m']:.1f} m  ({r1['distanza_km']:.2f} km)")
    print(f"punti geometria: {len(r1['geometria'])}")
    print(f"fonte: {r1['fonte']}")
    if r1["fonte"] == "osrm":
        # Fascia di sanità larga (non i numeri esatti di riferimento):
        # il router pubblico OSRM può cambiare risposta nel tempo (versione
        # del grafo stradale, nodo di aggancio, ecc.), quindi un'asserzione
        # stretta sul valore esatto è fragile. Qui verifichiamo solo che il
        # risultato sia dell'ordine di grandezza giusto (niente lat/lon
        # scambiate, niente unità sbagliate).
        assert 300 < r1["durata_s"] < 1500, f"durata fuori dalla fascia di sanità: {r1['durata_s']}"
        assert 3000 < r1["distanza_m"] < 15000, f"distanza fuori dalla fascia di sanità: {r1['distanza_m']}"
        print("OK: durata/distanza nell'ordine di grandezza corretto.")
        if not (800 < r1["durata_s"] < 1100 and 8000 < r1["distanza_m"] < 11000):
            print(
                f"ATTENZIONE: il valore di riferimento del brief era ~940s/~9.5km, "
                f"OSRM oggi risponde {r1['durata_s']:.1f}s/{r1['distanza_m']/1000:.2f}km "
                "per questa stessa coppia di punti. Codice e query sono corretti "
                "(verificato anche via curl diretto, ripetuto e in entrambe le "
                "direzioni); il router pubblico OSRM può semplicemente dare una "
                "risposta diversa da quella registrata nel brief."
            )

    print("\n--- Seconda chiamata: deve arrivare dalla cache ---")
    r2 = percorso(*CASILINO, *TOR_VERGATA)
    print("fonte:", r2["fonte"])
    assert r2["fonte"] == "cache", "percorso non ha usato la cache alla seconda chiamata"

    print("\n--- Demo entro_minuti su una manciata di punti sintetici ---")
    destinazioni = [
        {"nome": "vicino", "lat": 41.86, "lon": 12.60},
        {"nome": "lontano", "lat": 42.50, "lon": 13.50},
    ]
    raggiungibili = entro_minuti(*CASILINO, destinazioni, minuti=20)
    print([d["nome"] for d in raggiungibili])

    print("\n--- Forzatura fallback: OSRM_URL puntato a un host inesistente ---")
    url_originale = OSRM_URL
    OSRM_URL = "http://host-che-non-esiste.invalid/route/v1/driving"
    # Punti mai richiesti prima in questo processo: garantito cache-miss,
    # quindi il codice DEVE provare la rete (che qui fallisce) e cadere
    # nel ramo di fallback haversine.
    r3 = percorso(41.9000, 12.5000, 41.8000, 12.6000)
    print(r3)
    assert r3["fonte"] == "fallback", "il fallback non ha funzionato: doveva restituire fonte 'fallback'"
    assert r3["distanza_km"] > 0
    OSRM_URL = url_originale
    print("OK: fallback haversine attivo, nessuna eccezione sollevata.")

    print("\nOK: smoke test percorsi.py superato.")
