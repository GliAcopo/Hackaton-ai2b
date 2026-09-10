"""Server minimo: zero dipendenze, parte sempre.

A un hackathon un `pip install` che fallisce alle 16:00 e' una sconfitta.
Se vuoi FastAPI mettila dopo, quando il flusso gia' gira.

    python3 4-src/app.py     ->  http://localhost:8000
"""
from __future__ import annotations

import json
import sys
import traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai  # noqa: E402
import llm  # noqa: E402
import meteo  # noqa: E402
import percorsi  # noqa: E402
import territorio  # noqa: E402
from indici import ORDINAMENTI, rete, simula  # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "5-web"
ROMA = (41.8933, 12.4829)


def _vicini(lat: float, lon: float, indici: list, quanti: int = 5) -> list[dict]:
    """I presidi piu' vicini, con tempo di percorrenza reale. Deterministico."""
    con_coord = [i for i in indici if i.lat and i.lon]
    con_coord.sort(key=lambda i: percorsi.haversine_km(lat, lon, i.lat, i.lon))
    esito = []
    for i in con_coord[:quanti]:
        p = percorsi.percorso(lat, lon, i.lat, i.lon)
        esito.append({
            "codice": i.codice, "nome": i.nome, "tipo": i.tipo,
            "comune": i.comune, "lat": i.lat, "lon": i.lon,
            "in_attesa": i.in_attesa, "presenti": i.presenti,
            "pressione": i.pressione, "sofferenza": i.sofferenza,
            "durata_min": round(p["durata_min"], 1),
            "distanza_km": round(p["distanza_km"], 1),
            "geometria": p["geometria"],
            "fonte_percorso": p["fonte"],
        })
    esito.sort(key=lambda d: d["durata_min"])
    return esito


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):  # meno rumore nel terminale
        pass

    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return super().do_GET()
        q = parse_qs(url.query)
        uno = lambda k, d="": q.get(k, [d])[0]
        try:
            return self._instrada(url.path, q, uno)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self._json({"errore": f"{type(exc).__name__}: {exc}"}, 500)

    def _instrada(self, percorso_url: str, q: dict, uno) -> None:
        # ---- stato della rete, con l'ordinamento scelto --------------------
        if percorso_url == "/api/rete":
            indici, meta = rete(uno("ordine", "pressione"))
            return self._json({
                "meta": meta,
                "ordinamenti": {k: v[0] for k, v in ORDINAMENTI.items()},
                "presidi": [i.to_dict() for i in indici],
            })

        # ---- piano di deviazione IA per un presidio ------------------------
        if percorso_url == "/api/piano":
            codice = uno("codice")
            indici, meta = rete("pressione")
            critico = next((i for i in indici if i.codice == codice), None)
            if critico is None:
                return self._json({"errore": f"presidio {codice} sconosciuto"}, 404)
            # Un presidio specialistico o pediatrico non assorbe il carico
            # generico a bassa intensita': la deviazione dei codici bianchi e
            # verdi ha senso solo verso pronto soccorso generalisti.
            escludi = ai.SOLO_PEDIATRICI | set(ai.SPECIALISTICI)
            candidati = [i for i in indici
                         if i.codice != codice
                         and i.codice not in escludi
                         and (i.posti_residui or 0) > 0]
            candidati.sort(key=lambda i: -(i.posti_residui or 0))
            m = meteo.meteo_corrente(critico.lat or ROMA[0], critico.lon or ROMA[1])
            return self._json({
                "presidio": critico.to_dict(),
                "candidati": [c.to_dict() for c in candidati[:6]],
                "meteo": m,
                "piano": ai.piano_deviazione(critico, candidati, m),
            })

        # ---- centrale 118: chiamata -> codice -> destinazioni --------------
        if percorso_url == "/api/triage":
            testo = uno("testo")
            if not testo:
                return self._json({"errore": "parametro `testo` mancante"}, 400)
            lat = float(uno("lat", ROMA[0]))
            lon = float(uno("lon", ROMA[1]))
            indici, meta = rete("pressione")
            t = ai.triage_chiamata(testo)
            vicini = _vicini(lat, lon, indici, quanti=6)
            return self._json({
                "meta": meta,
                "triage": t,
                "destinazioni": ai.destinazioni_per_chiamata(t, vicini),
            })

        # ---- cittadino ----------------------------------------------------
        if percorso_url == "/api/cittadino":
            sintomo = uno("sintomo")
            if not sintomo:
                return self._json({"errore": "parametro `sintomo` mancante"}, 400)
            lat = float(uno("lat", ROMA[0]))
            lon = float(uno("lon", ROMA[1]))
            indici, meta = rete("pressione")
            vicini = _vicini(lat, lon, indici, quanti=5)
            terr = territorio.vicini(lat, lon, raggio_km=3.0, quanti=6)
            return self._json({
                "meta": meta,
                "vicini": vicini,
                "territoriali": terr,
                "assorbimento": territorio.assorbimento(lat, lon),
                "qualita_territorio": territorio.statistiche(),
                "consiglio": ai.consiglio_cittadino(sintomo, vicini, terr),
            })

        # ---- bollettino meteo-sanitario -----------------------------------
        if percorso_url == "/api/bollettino":
            lat = float(uno("lat", ROMA[0]))
            lon = float(uno("lon", ROMA[1]))
            m = meteo.meteo_corrente(lat, lon)
            a = meteo.qualita_aria(lat, lon)
            return self._json({
                "meteo": m, "aria": a,
                "storico_snapshot": meteo.meteo_storico(lat, lon, "2021-07-15"),
                "bollettino": ai.bollettino_sanitario(m, a),
            })

        # ---- simulazione controfattuale (deterministica, nessun modello) ---
        if percorso_url == "/api/simula":
            codice = uno("codice")
            quota = int(uno("quota", "0"))
            # destinazioni passate come "codice:quota,codice:quota"
            dest = {}
            for pezzo in uno("destinazioni").split(","):
                if ":" in pezzo:
                    c, n = pezzo.split(":", 1)
                    dest[c.strip()] = int(n)
            return self._json(simula(codice, quota, dest))

        if percorso_url == "/api/health":
            return self._json({"llm": llm.health()})

        return self._json({"errore": "endpoint sconosciuto"}, 404)


if __name__ == "__main__":
    print(llm.health())
    print("\nhttp://localhost:8000   (Ctrl-C per fermare)")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
