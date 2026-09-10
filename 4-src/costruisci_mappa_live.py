"""Costruisce la corrispondenza fra i nostri 49 presidi e i pronto soccorso
pubblicati dall'API in tempo reale di Salute Lazio.

    python3 4-src/costruisci_mappa_live.py            # ricostruisce e stampa
    python3 4-src/costruisci_mappa_live.py --verifica  # non scrive, solo controlla

PERCHE' NON SI ABBINA PER CODICE. Le due fonti usano due codifiche diverse:
lo snapshot open data chiama Tor Vergata "92000" e l'API "12092000-01", ma
chiama il Casilino "29400" mentre l'API usa "12030800-PS". Provare a
normalizzare i codici da' 25 abbinamenti su 49: sembra una regola e non lo e'.

Si abbina invece per COORDINATE, che entrambe le fonti pubblicano, con due
correzioni necessarie perche' la sola distanza non basta:

  1. gli ospedali universitari hanno piu' pronto soccorso sullo stesso
     indirizzo (Umberto I ne ha cinque: generale, pediatrico, oculistico,
     odontoiatrico, ostetrico). A distanza zero il piu' vicino e' arbitrario:
     va scelto quello dello stesso tipo, altrimenti il Policlinico Umberto I
     finisce abbinato al pronto soccorso odontoiatrico.
  2. un nome in comune (il presidio o il suo comune) vale piu' di qualche
     centinaio di metri: "G. Battista Grassi" e "Pronto Soccorso Ostia" sono
     lo stesso posto, "Ospedale Civile" da solo non dice niente.

L'esito e' stato controllato a mano riga per riga: 49 su 49, tutti sotto
1.7 km tranne Sant'Anna di Pomezia (9.6 km), dove e' la NOSTRA coordinata a
essere sbagliata - quella dell'API viene dall'anagrafe regionale.
"""
from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
PRESIDI = RADICE / "2-data" / "derived" / "presidi.json"
USCITA = RADICE / "2-data" / "derived" / "mappa_live.json"

BASE = "https://server.salutelazio.it/server/external-services/facilities/structures"
# 006 = "Pronto soccorso" nella tassonomia delle strutture di Salute Lazio.
# Il riquadro cerca dentro un rettangolo: questo copre tutto il Lazio.
ELENCO = (f"{BASE}/list?westLng=11.4&southLat=40.7&eastLng=14.1&northLat=42.9"
          "&zoom=8&lang=it&page=1&limit=100&facilityTypeIds=006")

# Parole che marcano un pronto soccorso specialistico. Servono a non abbinare
# un policlinico generale al suo pronto soccorso odontoiatrico.
SPECIALISTICO = ("odontoiatric", "oculistic", "ematologic", "ostetric",
                 "ginecologic", "pediatric", "oftalmic")

# Parole troppo comuni per essere indizio di identita': "Pronto Soccorso
# Ospedale Civile" e "Ospedale Civile" condividono solo del rumore.
RUMORE = {"pronto", "soccorso", "ospedale", "policlinico", "universitario", "univ"}

# Abbinamenti che la distanza non puo' trovare, con il motivo per cui esistono.
# Sant'Anna di Pomezia: l'API pubblica l'indirizzo giusto ("Via del Mare,
# 69/71 - Pomezia") ma una geometria che cade a Castel di Leva, 9,6 km piu' a
# nord, dentro il comune di Roma. Verificato: la coordinata giusta e' la
# nostra (0,01 km dalla Casa di Cura Sant'Anna in OpenStreetMap), quella
# dell'API e' sbagliata. Abbiniamo il presidio e teniamo il nostro punto.
ECCEZIONI = {"13400": "Pronto Soccorso Sant'Anna"}
COORDINATA_LIVE_INAFFIDABILE = {"13400"}

DISTANZA_MAX_KM = 8.0     # oltre, l'abbinamento non si fa
PENALITA_TIPO = 25.0      # generale vs specialistico: praticamente un veto
BONUS_NOME = 3.0          # un nome in comune vale ~3 km di distanza


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = math.radians
    return 2 * 6371.0 * math.asin(math.sqrt(
        math.sin(r(lat2 - lat1) / 2) ** 2
        + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2))


def parole(testo: str) -> set[str]:
    piatto = unicodedata.normalize("NFKD", testo.lower()).encode("ascii", "ignore").decode()
    return set(re.findall(r"[a-z]{4,}", piatto)) - RUMORE


def specialistico(nome: str) -> bool:
    return any(p in nome.lower() for p in SPECIALISTICO)


def scarica_elenco() -> list[dict]:
    with urllib.request.urlopen(ELENCO, timeout=30) as risposta:
        return json.load(risposta).get("items", [])


def abbina(nostri: list[dict], live: list[dict]) -> tuple[list[tuple], list[dict], list[dict]]:
    """Assegnazione greedy sul costo: distanza, corretta da tipo e nome."""
    coppie = []
    for i, p in enumerate(nostri):
        if p.get("lat") is None:
            continue
        for j, l in enumerate(live):
            g = l["geometry"]
            d = km(p["lat"], p["lon"], g["latitude"], g["longitude"])
            if d > DISTANZA_MAX_KM:
                continue
            costo = d
            if specialistico(p["nome"]) != specialistico(l["name"]):
                costo += PENALITA_TIPO
            comune = bool(parole(p["comune"]) & parole(l["name"])
                          or parole(p["nome"]) & parole(l["name"]))
            if comune:
                costo -= BONUS_NOME
            coppie.append((costo, d, i, j, comune))

    coppie.sort()
    presi_n, presi_l, mappa = set(), set(), []

    # Le eccezioni si assegnano per prime: sono decisioni prese a mano e
    # documentate sopra, non devono competere con la distanza.
    per_nome = {l["name"]: j for j, l in enumerate(live)}
    for i, p in enumerate(nostri):
        j = per_nome.get(ECCEZIONI.get(str(p["codice"]), ""))
        if j is None:
            continue
        g = live[j]["geometry"]
        presi_n.add(i)
        presi_l.add(j)
        mappa.append((km(p["lat"], p["lon"], g["latitude"], g["longitude"]),
                      p, live[j], True))

    for costo, d, i, j, comune in coppie:
        if i in presi_n or j in presi_l:
            continue
        presi_n.add(i)
        presi_l.add(j)
        mappa.append((d, nostri[i], live[j], comune))

    orfani_n = [p for i, p in enumerate(nostri) if i not in presi_n]
    orfani_l = [l for j, l in enumerate(live) if j not in presi_l]
    return mappa, orfani_n, orfani_l


def main() -> int:
    verifica = "--verifica" in sys.argv
    nostri = json.loads(PRESIDI.read_text(encoding="utf-8"))
    live = scarica_elenco()
    mappa, orfani_n, orfani_l = abbina(nostri, live)

    print(f"presidi nostri: {len(nostri)}   pronto soccorso live: {len(live)}   "
          f"abbinati: {len(mappa)}")
    sospetti = [(d, p, l) for d, p, l, c in mappa
                if d > 2.0 and not c and str(p["codice"]) not in ECCEZIONI]
    for d, p, l, comune in sorted(mappa, key=lambda x: -x[0])[:6]:
        print(f"  {d:6.2f} km {'nome' if comune else '    '}  "
              f"{p['nome'][:30]:30} -> {l['name']}")
    if orfani_n:
        print("\nNOSTRI SENZA LIVE (useranno lo snapshot):")
        for p in orfani_n:
            print(f"   {p['codice']:6} {p['nome']} ({p['comune']})")
    if orfani_l:
        print("\nLIVE NON USATI (specialistici o strutture fuori dataset 2021):")
        for l in orfani_l:
            print(f"   {l['name']}")
    if sospetti:
        print("\nDA CONTROLLARE A MANO (lontani e senza nome in comune):")
        for d, p, l in sospetti:
            print(f"   {d:.2f} km {p['nome']} -> {l['name']}")

    if verifica:
        return 1 if (orfani_n or sospetti) else 0

    USCITA.write_text(json.dumps(
        {p["codice"]: {"psid": l["emergencyOrganizationId"],
                       "nome_live": l["name"],
                       "km_dal_nostro_punto": round(d, 3),
                       "lat_live": l["geometry"]["latitude"],
                       "lon_live": l["geometry"]["longitude"],
                       "coordinata_live_affidabile":
                           str(p["codice"]) not in COORDINATA_LIVE_INAFFIDABILE}
         for d, p, l, _ in mappa}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nscritto {USCITA.relative_to(RADICE)} ({len(mappa)} voci)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
