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

# I percorsi che verranno mostrati alla giuria. Se cambia la scaletta, cambia
# qui. Ogni voce e' un dialogo gia' concluso: testo iniziale piu' le risposte.
PERCORSI_CITTADINO = [
    {
        "nome": "bambino con febbre, a piedi",
        "ingresso": "problema",
        "testo": "mio figlio ha 38.5 di febbre da ieri sera e non trovo il pediatra",
        "risposte": [("respiro_o_coscienza", "si"), ("destinatario", "figlio"),
                     ("eta_fascia", "6_13"), ("durata", "oggi"),
                     ("gia_valutato", "no"), ("mobilita", "piedi")],
    },
    {
        "nome": "caviglia, adulto con auto",
        "ingresso": "problema",
        "testo": "mi sono storto la caviglia giocando a calcetto, e' gonfia ma cammino",
        "risposte": [("respiro_o_coscienza", "si"), ("destinatario", "me"),
                     ("eta_fascia", "18_64"), ("durata", "oggi"),
                     ("gia_valutato", "no"), ("mobilita", "auto")],
    },
    {
        "nome": "prestazione gia' indicata: RMN",
        "ingresso": "prestazione",
        "testo": "il medico mi ha prescritto una risonanza al ginocchio",
        "risposte": [("destinatario", "me"), ("eta_fascia", "18_64"),
                     ("prestazione_cercata", "rmn"), ("prescrizione", "si"),
                     ("mobilita", "auto")],
    },
]
ROMA = (41.8933, 12.4829)


def main() -> int:
    prova = "--prova" in sys.argv
    if prova:
        # nessun backend interpellato: se qualcosa manca in cache, si vede
        os.environ["LLM_SOLO_CACHE"] = "1"

    import ai, dialogo, indici, meteo, opzioni, percorsi  # noqa: E402  (dopo l'env)

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

    lista, meta_rete = indici.rete("attesa")
    critico = lista[0]

    # 2. meteo e aria: della citta' e di ogni presidio che la demo tocca
    passo("meteo/roma", lambda: meteo.meteo_corrente(*ROMA))
    passo("aria/roma", lambda: meteo.qualita_aria(*ROMA))
    passo("meteo/2021-07-15", lambda: meteo.meteo_storico(*ROMA, "2021-07-15"))
    passo("meteo/critico", lambda: meteo.meteo_corrente(critico.lat, critico.lon))
    passo("copertura/territorio", lambda: opzioni._apparecchiature().get("riepilogo"))

    # 3. percorsi dai punti della demo verso i presidi piu' vicini
    vicini = sorted((i for i in lista if i.lat),
                    key=lambda i: percorsi.haversine_km(*ROMA, i.lat, i.lon))[:8]
    for v in vicini:
        passo(f"percorso/{v.nome[:18]}",
              lambda v=v: percorsi.percorso(*ROMA, v.lat, v.lon))

    # 4. le chiamate al modello: la parte cara
    m = meteo.meteo_corrente(*ROMA)
    if m.get("disponibile"):
        a = meteo.qualita_aria(*ROMA)
        passo("ia/bollettino", lambda: ai.bollettino_sanitario(
            m, a if a.get("disponibile") else None))
    else:
        # Nessun meteo misurato: il bollettino non si genera, e non e' un
        # errore da segnare come mancante. E' il comportamento corretto.
        esiti.append(("ia/bollettino", 0.0, "saltato: meteo non disponibile"))

    # 5. i percorsi del cittadino, dal dialogo fino al confronto delle opzioni
    for caso in PERCORSI_CITTADINO:
        risposte = [{"id": i, "valore": v} for i, v in caso["risposte"]]

        # ogni passo intermedio del dialogo: la proposta della prossima domanda
        # e' una chiamata al modello, e in demo deve arrivare dalla cache
        def _dialoghi(caso=caso, risposte=risposte):
            for k in range(len(risposte)):
                parziali = risposte[:k]
                stato = dialogo.passo(caso["ingresso"], parziali)
                if not stato.get("domanda") or stato.get("proposta_da") == "regola_obbligatoria":
                    continue
                ammessi = [dialogo.per_id(x) for x in stato.get("id_ammessi", [])]
                ai.prossima_domanda(caso["testo"], [d for d in ammessi if d],
                                    stato.get("fatti", {}))
            return {"passi": len(risposte)}
        passo(f"dialogo/{caso['nome'][:26]}", _dialoghi)

        def _orienta(caso=caso, risposte=risposte):
            fatti = {r["id"]: r["valore"] for r in risposte}
            confronto = opzioni.confronta(caso["ingresso"], fatti, lista, meta_rete,
                                          *ROMA)
            return ai.orientamento(caso["testo"], confronto, fatti,
                                   ai.segnali_emergenza(caso["testo"]))
        passo(f"ia/orientamento: {caso['nome'][:24]}", _orienta)

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
