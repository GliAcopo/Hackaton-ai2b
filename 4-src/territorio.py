"""Medicina di prossimita': farmacie e strutture accreditate geolocalizzate.

E' il pezzo che la traccia chiede alla lettera — indirizzare i codici a bassa
intensita' verso "strutture territoriali (es. case della comunita' o farmacie
attrezzate)" — e l'unico livello dell'app che parla di dove mandare le persone
invece che di dove sono i problemi.

QUALITA' DEL DATO, dichiarata e non nascosta.
Nell'anagrafe regionale delle farmacie le coordinate non sono tutte affidabili:
161 farmacie su 985 riportano la STESSA identica coppia lat/lon (41.92368,
12.57115), che e' un valore sentinella e non una posizione. Altri gruppi piu'
piccoli ripetono la stessa coordinata. Indirizzare un cittadino a una posizione
inventata e' peggio che non indirizzarlo: queste righe restano nell'elenco ma
sono marcate `posizione_attendibile: false` e non entrano nella ricerca per
prossimita'.
"""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from percorsi import haversine_km

RADICE = Path(__file__).resolve().parent.parent
TERRITORIO = RADICE / "2-data" / "derived" / "territorio.json"
CENTROIDI = RADICE / "2-data" / "cache" / "comuni.json"

# Quante volte una coordinata deve ripetersi per essere considerata sentinella.
# Due o tre farmacie possono davvero stare nello stesso edificio o civico;
# cinque no.
SOGLIA_SENTINELLA = 5

# Secondo tipo di sentinella: la coordinata coincide col centro del comune.
# Succede quando chi ha compilato l'anagrafe non aveva l'indirizzo esatto e ha
# geocodificato solo il comune. Su Roma ne basta una per rovinare la risposta
# "la farmacia piu' vicina", perche' il centro citta' e' il punto da cui
# partono quasi tutte le ricerche.
RAGGIO_CENTROIDE_KM = 0.15


@lru_cache(maxsize=1)
def _centroidi() -> list[tuple[float, float]]:
    """Centri dei comuni gia' geocodificati durante la validazione dei presidi."""
    try:
        dati = json.loads(CENTROIDI.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [(v[0], v[1]) for v in dati.values() if v]


def _sul_centroide(lat: float, lon: float) -> bool:
    return any(haversine_km(lat, lon, a, b) <= RAGGIO_CENTROIDE_KM
               for a, b in _centroidi())


@lru_cache(maxsize=1)
def carica() -> dict:
    """Farmacie e strutture, con la qualita' della posizione gia' valutata."""
    dati = json.loads(TERRITORIO.read_text(encoding="utf-8"))
    esito = {}
    for chiave in ("farmacie", "strutture_accreditate"):
        righe = dati.get(chiave, [])
        conteggio = Counter((round(r["lat"], 5), round(r["lon"], 5))
                            for r in righe if r.get("lat") and r.get("lon"))
        sentinelle = {c for c, n in conteggio.items() if n >= SOGLIA_SENTINELLA}
        for r in righe:
            c = (round(r.get("lat") or 0, 5), round(r.get("lon") or 0, 5))
            attendibile = bool(r.get("lat")) and c not in sentinelle
            if attendibile and _sul_centroide(r["lat"], r["lon"]):
                attendibile = False
            r["posizione_attendibile"] = attendibile
            r["genere"] = "farmacia" if chiave == "farmacie" else "struttura accreditata"
        esito[chiave] = righe
    return esito


def statistiche() -> dict:
    d = carica()
    return {
        chiave: {
            "totale": len(v),
            "con_posizione_attendibile": sum(1 for r in v if r["posizione_attendibile"]),
        }
        for chiave, v in d.items()
    }


def vicini(lat: float, lon: float, raggio_km: float = 3.0,
           quanti: int = 6) -> list[dict]:
    """Presidi territoriali intorno a un punto, i piu' vicini per primi.

    Si filtra in linea d'aria e non su strada: sono migliaia di righe e la
    differenza, entro pochi chilometri di citta', non cambia la scelta. Il
    tempo di percorrenza reale si calcola solo sui pochi che si mostrano.
    """
    d = carica()
    esito = []
    for chiave in ("farmacie", "strutture_accreditate"):
        for r in d[chiave]:
            if not r["posizione_attendibile"]:
                continue
            km = haversine_km(lat, lon, r["lat"], r["lon"])
            if km <= raggio_km:
                esito.append({
                    "nome": r.get("nome"), "genere": r["genere"],
                    "indirizzo": r.get("indirizzo"), "comune": r.get("comune"),
                    "lat": r["lat"], "lon": r["lon"],
                    "distanza_km": round(km, 2),
                })
    esito.sort(key=lambda x: x["distanza_km"])
    return esito[:quanti]


def assorbimento(lat: float, lon: float, raggio_km: float = 3.0) -> dict:
    """Quanti presidi territoriali puo' davvero assorbire una zona.

    Non "nel Lazio ci sono 985 farmacie", ma "da qui, adesso, ce ne sono N
    raggiungibili": e' la differenza fra un numero da slide e un numero
    operativo.
    """
    d = carica()
    conteggi = {}
    for chiave in ("farmacie", "strutture_accreditate"):
        conteggi[chiave] = sum(
            1 for r in d[chiave]
            if r["posizione_attendibile"]
            and haversine_km(lat, lon, r["lat"], r["lon"]) <= raggio_km
        )
    conteggi["raggio_km"] = raggio_km
    return conteggi


if __name__ == "__main__":
    print("qualita' del dato:", json.dumps(statistiche(), ensure_ascii=False, indent=1))
    ROMA = (41.8933, 12.4829)
    print(f"\nassorbimento territoriale entro 3 km dal centro di Roma:")
    print(" ", json.dumps(assorbimento(*ROMA), ensure_ascii=False))
    print("\npresidi territoriali piu' vicini:")
    for v in vicini(*ROMA):
        print(f"  {v['distanza_km']:5.2f} km  {v['genere']:22} {(v['nome'] or '')[:40]:40} {(v['indirizzo'] or '')[:30]}")
