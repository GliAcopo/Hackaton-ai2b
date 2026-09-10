"""Precalcolo di tutti gli output della demo. Da lanciare al freeze.

Perche' esiste: ogni chiamata ad `agy` costa ~20k token e ~7 secondi, e alle
17:00 davanti alla giuria la rete puo' non esserci. Questo script percorre in
anticipo l'intero percorso della demo e riempie le cache su disco (LLM, meteo,
OSRM). Dopo averlo eseguito, la demo gira anche staccata dalla rete.

    python3 4-src/prepara_demo.py          # riempie le cache
    python3 4-src/prepara_demo.py --prova  # verifica che basti: solo cache
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Casi che verranno mostrati alla giuria. Se cambia la scaletta, cambia qui.
CHIAMATE_118 = [
    "uomo 62 anni, dolore al petto che si irradia al braccio sinistro, "
    "suda freddo, cosciente, zona Torre Angela",
    "donna 34 anni, caviglia gonfia dopo caduta, cammina con difficolta', "
    "zona Tuscolana",
    "bambino 6 anni, febbre 38.5 da ieri sera, beve e gioca, zona Centocelle",
]
SINTOMI_CITTADINO = [
    "mio figlio ha 38.5 di febbre da ieri sera e non trovo il pediatra",
    "mi sono storto la caviglia giocando a calcetto, e' gonfia ma cammino",
]
ROMA = (41.8933, 12.4829)


def main() -> int:
    prova = "--prova" in sys.argv
    if prova:
        # nessun backend interpellato: se qualcosa manca in cache, si vede
        os.environ["LLM_SOLO_CACHE"] = "1"

    import ai, indici, meteo, percorsi  # noqa: E402  (dopo l'env)

    esiti, mancanti = [], []

    def passo(nome, funzione):
        inizio = time.monotonic()
        try:
            r = funzione()
            secondi = time.monotonic() - inizio
            fallback = isinstance(r, dict) and r.get("_fallback")
            esiti.append((nome, secondi, "FALLBACK" if fallback else "ok"))
            if prova and fallback:
                mancanti.append(nome)
        except Exception as exc:  # noqa: BLE001
            esiti.append((nome, time.monotonic() - inizio, f"ERRORE {exc}"))
            mancanti.append(nome)

    # 1. i sei ordinamenti (deterministici, nessun modello)
    for chiave in indici.ORDINAMENTI:
        passo(f"rete/{chiave}", lambda c=chiave: indici.rete(c))

    lista, _ = indici.rete("deviabile")
    critico = lista[0]

    # 2. meteo e aria: della citta' e di ogni presidio che la demo tocca
    passo("meteo/roma", lambda: meteo.meteo_corrente(*ROMA))
    passo("aria/roma", lambda: meteo.qualita_aria(*ROMA))
    passo("meteo/2021-07-15", lambda: meteo.meteo_storico(*ROMA, "2021-07-15"))
    passo("meteo/critico", lambda: meteo.meteo_corrente(critico.lat, critico.lon))

    # 3. percorsi dai punti della demo verso i presidi piu' vicini
    vicini = sorted((i for i in lista if i.lat),
                    key=lambda i: percorsi.haversine_km(*ROMA, i.lat, i.lon))[:8]
    for v in vicini:
        passo(f"percorso/{v.nome[:18]}",
              lambda v=v: percorsi.percorso(*ROMA, v.lat, v.lon))

    # 4. le chiamate al modello: la parte cara
    m = meteo.meteo_corrente(critico.lat, critico.lon)
    escludi = ai.SOLO_PEDIATRICI | set(ai.SPECIALISTICI)
    cand = sorted((i for i in lista
                   if i.codice != critico.codice and i.codice not in escludi
                   and (i.posti_residui or 0) > 0),
                  key=lambda i: -(i.posti_residui or 0))
    passo("ia/piano_deviazione", lambda: ai.piano_deviazione(critico, cand, m))
    passo("ia/bollettino", lambda: ai.bollettino_sanitario(
        meteo.meteo_corrente(*ROMA), meteo.qualita_aria(*ROMA)))
    for t in CHIAMATE_118:
        passo(f"ia/triage: {t[:34]}", lambda t=t: ai.triage_chiamata(t))
    vicini_d = [{"nome": v.nome, "tipo": v.tipo, "codice": v.codice,
                 "in_attesa": v.in_attesa, "durata_min": 10} for v in vicini[:5]]
    for s in SINTOMI_CITTADINO:
        passo(f"ia/cittadino: {s[:32]}", lambda s=s: ai.consiglio_cittadino(s, vicini_d))

    larghezza = max(len(n) for n, _, _ in esiti)
    for nome, secondi, stato in esiti:
        print(f"  {stato[:9]:9} {secondi:6.2f}s  {nome:{larghezza}}")

    if prova:
        if mancanti:
            print(f"\nKO  {len(mancanti)} passi NON coperti dalla cache:")
            for n in mancanti:
                print(f"      - {n}")
            return 1
        print("\nOK  l'intera demo gira dalla sola cache: rete non necessaria.")
    else:
        print(f"\n{len(esiti)} passi precalcolati. "
              f"Ora verifica con: python3 4-src/prepara_demo.py --prova")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
