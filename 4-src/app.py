"""Server minimo: zero dipendenze, parte sempre.

A un hackathon un `pip install` che fallisce alle 16:00 e' una sconfitta.
Se vuoi FastAPI mettila dopo, quando il flusso gia' gira.

    python3 4-src/app.py                  ->  http://localhost:8000
    python3 4-src/app.py --fonte live     ->  stato dei PS in tempo reale
    python3 4-src/app.py --live           ->  niente cache LLM: modello vero
    python3 4-src/app.py --fonte live --live  ->  tutto vivo, niente precalcolo

DUE COSE DIVERSE, DUE INTERRUTTORI DIVERSI.

`--fonte live` riguarda i DATI: interroga l'API di Salute Lazio invece di
leggere lo snapshot open data del 2021. E' la sorgente che si vuole in gara.

`--live` riguarda l'LLM: ignora la cache delle risposte e interpella davvero
il modello. In demo conviene il contrario (la cache risponde in millisecondi
e non dipende dalla rete), ma serve poterlo dimostrare dal vivo.

La fonte si puo' anche scegliere per singola chiamata: /api/rete?fonte=live.
"""
from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import time
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

# Sorgente predefinita del server, scavalcabile per singola richiesta con
# ?fonte=live. Resta "snapshot" se non si chiede altro: la demo offline deve
# continuare a funzionare identica a prima.
FONTE_DEFAULT = "snapshot"


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
        self.fonte = uno("fonte", FONTE_DEFAULT)
        try:
            return self._instrada(url.path, q, uno)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self._json({"errore": f"{type(exc).__name__}: {exc}"}, 500)

    def _instrada(self, percorso_url: str, q: dict, uno) -> None:
        # ---- stato della rete, con l'ordinamento scelto --------------------
        if percorso_url == "/api/rete":
            indici, meta = rete(uno("ordine", "pressione"), self.fonte)
            # In tempo reale la fonte non pubblica ne' l'occupazione ne' i
            # presenti: offrire quegli ordinamenti darebbe una colonna di zeri
            # sotto un'etichetta che promette altro.
            # NB: "capienza" resta: in live la capacita' residua si calcola
            # sulla coda invece che sui posti (vedi indici._calibra).
            senza = {"pressione", "presenti"} if meta.get("solo_coda") else set()
            return self._json({
                "meta": meta,
                "ordinamenti": {k: v[0] for k, v in ORDINAMENTI.items() if k not in senza},
                "presidi": [i.to_dict() for i in indici],
            })

        # ---- piano di deviazione IA per un presidio ------------------------
        if percorso_url == "/api/piano":
            codice = uno("codice")
            indici, meta = rete("pressione", self.fonte)
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
            indici, meta = rete("pressione", self.fonte)
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
            indici, meta = rete("pressione", self.fonte)
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


PID_FILE = Path(__file__).resolve().parent / ".server.pid"


def _antenati() -> set[int]:
    """Restituisce l'insieme dei PID del processo corrente e di tutti i suoi antenati."""
    pids = {os.getpid()}
    try:
        curr = os.getppid()
        while curr > 1:
            pids.add(curr)
            with open(f"/proc/{curr}/stat") as f:
                curr = int(f.read().split()[3])
    except Exception:
        pass
    return pids


def _porta_in_uso(porta: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        try:
            s.bind((host, porta))
            return False
        except OSError:
            return True


def chiudi_istanza_precedente(porta: int = 8000, forzato: bool = False) -> None:
    """Se un'altra istanza sta usando la porta o app.py e' gia' in esecuzione,
    chiude l'istanza precedente per consentire il riavvio pulito."""
    da_escludere = _antenati()
    pids: set[int] = set()

    # 1. PID file
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if pid not in da_escludere:
                pids.add(pid)
        except Exception:
            pass

    # 2. Processi che ascoltano sulla porta via lsof
    try:
        res = subprocess.run(["lsof", "-ti", f":{porta}"], capture_output=True, text=True, timeout=2)
        for linea in res.stdout.strip().split():
            if linea.isdigit():
                pid = int(linea)
                if pid not in da_escludere:
                    pids.add(pid)
    except Exception:
        pass

    # 3. Processi che usano la porta via fuser
    try:
        res = subprocess.run(["fuser", f"{porta}/tcp"], capture_output=True, text=True, timeout=2)
        for parte in (res.stdout + " " + res.stderr).split():
            if parte.isdigit():
                pid = int(parte)
                if pid not in da_escludere:
                    pids.add(pid)
    except Exception:
        pass

    # 4. Altre istanze di 4-src/app.py via pgrep
    try:
        res = subprocess.run(["pgrep", "-f", "4-src/app.py"], capture_output=True, text=True, timeout=2)
        for linea in res.stdout.strip().split():
            if linea.isdigit():
                pid = int(linea)
                if pid not in da_escludere:
                    pids.add(pid)
    except Exception:
        pass


    if not pids and not _porta_in_uso(porta):
        return

    # Invia SIGTERM per chiusura ordinata
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    # Invoca fuser per terminare chiunque occupi la porta
    try:
        subprocess.run(["fuser", "-k", "-TERM", f"{porta}/tcp"], capture_output=True, timeout=2)
    except Exception:
        pass

    # Attendi brevemente che la porta si liberi
    inizio = time.monotonic()
    while time.monotonic() - inizio < 1.5:
        if not _porta_in_uso(porta):
            break
        time.sleep(0.1)

    # Se ancora in uso, escalation a SIGKILL
    if _porta_in_uso(porta):
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        try:
            subprocess.run(["fuser", "-k", "-KILL", f"{porta}/tcp"], capture_output=True, timeout=2)
        except Exception:
            pass
        inizio = time.monotonic()
        while time.monotonic() - inizio < 1.0:
            if not _porta_in_uso(porta):
                break
            time.sleep(0.1)

    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass

    if pids:
        print(f"[avvio] Chiusa istanza precedente (PID: {', '.join(map(str, sorted(pids)))}), porta {porta} liberata.")


class Server(HTTPServer):
    allow_reuse_address = True

    def server_bind(self):
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        super().server_bind()


def avvia_server(host: str = "127.0.0.1", porta: int = 8000) -> None:
    PID_FILE.write_text(str(os.getpid()))

    def _rimuovi_pid():
        try:
            if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
                PID_FILE.unlink()
        except Exception:
            pass

    atexit.register(_rimuovi_pid)

    server = None
    for tentativo in range(3):
        try:
            server = Server((host, porta), Handler)
            break
        except OSError as exc:
            if exc.errno == 98 and tentativo < 2:
                chiudi_istanza_precedente(porta, forzato=True)
                time.sleep(0.5)
            else:
                raise

    server.serve_forever()


if __name__ == "__main__":
    porta = 8000
    if "--porta" in sys.argv:
        porta = int(sys.argv[sys.argv.index("--porta") + 1])
    elif "--port" in sys.argv:
        porta = int(sys.argv[sys.argv.index("--port") + 1])
    elif "PORT" in os.environ:
        porta = int(os.environ["PORT"])

    chiudi_istanza_precedente(porta)

    if "--live" in sys.argv:
        os.environ["LLM_LIVE"] = "1"
    if "--fonte" in sys.argv:
        FONTE_DEFAULT = sys.argv[sys.argv.index("--fonte") + 1]
    import importlib
    importlib.reload(llm)          # rilegge LLM_LIVE dall'ambiente
    print(f"fonte dati: {FONTE_DEFAULT}")
    print(llm.health())

    print("\nModalità di esecuzione:")
    if llm.LIVE and FONTE_DEFAULT == "live":
        print("  ✓ MODALITÀ LIVE COMPLETA ATTIVA (dati Salute Lazio + LLM in tempo reale)")
    elif llm.LIVE:
        print("  ✓ LLM LIVE ATTIVO (modello in tempo reale, cache ignorata)")
        print("  → Per attivare anche i dati PS in tempo reale: python3 4-src/app.py --fonte live --live")
    elif FONTE_DEFAULT == "live":
        print("  ✓ DATI LIVE ATTIVI (Salute Lazio in tempo reale)")
        print("  → Per attivare anche l'LLM live: python3 4-src/app.py --fonte live --live")
    else:
        print("  • Modalità corrente: DEMO (dati snapshot 2021 + cache LLM)")
        print("  • Comandi da terminale per entrare nella modalità live:")
        print("      python3 4-src/app.py --live               # LLM in tempo reale (senza cache)")
        print("      python3 4-src/app.py --fonte live         # dati Pronto Soccorso in tempo reale")
        print("      python3 4-src/app.py --fonte live --live   # tutto in tempo reale (dati + LLM)")

    print(f"\nhttp://localhost:{porta}   (Ctrl-C per fermare)")
    avvia_server("127.0.0.1", porta)


