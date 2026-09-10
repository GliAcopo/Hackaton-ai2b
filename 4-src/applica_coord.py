"""Applica a presidi.json le coordinate risolte a mano.

Perche' esiste come script e non come patch una tantum: se build_derived.py
viene rieseguito, presidi.json torna senza le 12 coordinate che Nominatim non
sa trovare. Questo script e' rieseguibile e idempotente.

Provenienza delle 12: query Overpass su tutti gli ospedali del Lazio
(amenity=hospital) e match per nome, poi validazione della distanza dal
comune dichiarato nel dataset regionale. Tarquinia e' l'unico presidio senza
un ospedale mappato in OpenStreetMap: usa il centro del comune, ed e'
marcato come tale invece di far finta di essere una posizione esatta.
"""
import json
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
PRESIDI = RADICE / "2-data" / "derived" / "presidi.json"
COORD = RADICE / "2-data" / "cache" / "coord_manuali.json"

# Presidi la cui coordinata e' il centro del comune, non la posizione esatta.
APPROSSIMATI = {"700"}


def main() -> int:
    presidi = json.loads(PRESIDI.read_text(encoding="utf-8"))
    coord = json.loads(COORD.read_text(encoding="utf-8"))
    applicate = 0
    for p in presidi:
        c = coord.get(str(p["codice"]))
        if c and not p.get("lat"):
            p["lat"], p["lon"] = float(c[0]), float(c[1])
            p["fonte_coordinate"] = ("centro del comune (nessun ospedale in OSM)"
                                     if str(p["codice"]) in APPROSSIMATI
                                     else "OpenStreetMap, match per nome")
            applicate += 1
        elif p.get("lat") and "fonte_coordinate" not in p:
            p["fonte_coordinate"] = "Nominatim"
    PRESIDI.write_text(json.dumps(presidi, ensure_ascii=False, indent=1), encoding="utf-8")
    senza = [p["nome"] for p in presidi if not p.get("lat")]
    print(f"coordinate applicate: {applicate}")
    print(f"presidi totali: {len(presidi)}  senza coordinate: {len(senza)} {senza}")
    return 0 if not senza else 1


if __name__ == "__main__":
    raise SystemExit(main())
