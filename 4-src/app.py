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
import dialogo  # noqa: E402
import opzioni  # noqa: E402
import voce  # noqa: E402
from indici import ORDINAMENTI, rete  # noqa: E402

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


# Tetto al corpo di una richiesta. L'audio ha il suo limite dentro voce.py.
MAX_CORPO = 12 * 1024 * 1024


def _copertura() -> dict:
    """Che dati abbiamo davvero, quanto coprono e cosa NON dicono.

    E' la risposta a «quanto e' solida questa scelta» a livello di sistema: chi
    guarda deve poter vedere dove i dati finiscono, senza doverlo dedurre da
    una risposta che sembra completa.
    """
    sorgenti = []
    try:
        _, meta = rete("attesa", "live")
        sorgenti.append({
            "nome": "Pronto soccorso — stato in tempo reale",
            "stato": "attiva",
            "copertura": f"{meta.get('con_dato')}/{meta.get('presidi')} presidi trasmettono",
            "non_coperti": meta.get("senza_dato") or [],
            "istante_fonte": meta.get("istante_fonte"),
            "istante_fonte_pubblicato": meta.get("istante_fonte_pubblicato"),
            "acquisito_il": meta.get("acquisito_il"),
            "da_cache": meta.get("da_cache"),
            "fonte_url": meta.get("fonte_url"),
            "limiti": meta.get("limiti") or [],
        })
    except Exception as exc:  # noqa: BLE001
        sorgenti.append({"nome": "Pronto soccorso — stato in tempo reale",
                         "stato": "non raggiungibile", "motivo": str(exc)})

    st = territorio.statistiche()
    for chiave, etichetta, fonte in (
            ("farmacie", "Farmacie", "Anagrafe regionale delle farmacie"),
            ("strutture_accreditate", "Strutture private accreditate",
             "Anagrafe regionale delle strutture accreditate")):
        v = st.get(chiave, {})
        sorgenti.append({
            "nome": etichetta, "stato": "parziale",
            "copertura": (f"{v.get('con_posizione_attendibile')}/{v.get('totale')} "
                          "con posizione attendibile"),
            "fonte_url": "https://dati.lazio.it/",
            "limiti": [
                "Le coordinate ripetute o coincidenti col centro del comune sono "
                "marcate come non attendibili ed escluse dalla ricerca per prossimita'.",
                "Orari, turni e prestazioni erogate per sede non sono nel dataset: "
                "vanno verificati sul canale ufficiale.",
            ],
        })
        sorgenti[-1]["fonte"] = fonte

    app = opzioni._apparecchiature()
    r = app.get("riepilogo") or {}
    sorgenti.append({
        "nome": "Grandi apparecchiature sanitarie",
        "stato": "attiva" if r else "assente",
        "copertura": (f"{r.get('righe_lette', 0)} righe, {r.get('strutture', 0)} sedi, "
                      f"{r.get('abbinate_a_un_presidio', 0)} abbinate a un pronto soccorso"),
        "fonte": (app.get("provenienza") or {}).get("fonte"),
        "fonte_url": (app.get("provenienza") or {}).get("pagina"),
        "istante_fonte": (app.get("provenienza") or {}).get("data_dataset"),
        "acquisito_il": (app.get("provenienza") or {}).get("data_download"),
        "limiti": app.get("limiti") or [],
    })

    return {
        "sorgenti": sorgenti,
        "catalogo_domande": dialogo.intestazione(),
        "voce": voce.stato(),
        "non_risolti": {
            "apparecchiature_senza_abbinamento": len(app.get("non_risolti") or []),
            "nota": ("Le associazioni non risolte sono elencate nel file derivato e "
                     "non influenzano alcun consiglio: un abbinamento incerto vale "
                     "come nessun abbinamento."),
        },
    }


def _bollettino(lat: float, lon: float) -> dict:
    """Contesto ambientale, con i tre livelli di prova tenuti separati.

    Se il dato misurato non c'e', NON si genera alcuna interpretazione. Prima
    esisteva un meteo di ripiego con numeri plausibili, e il bollettino usciva
    lo stesso: un'allerta costruita su un dato che nessuno aveva misurato e'
    indistinguibile da una vera, ed e' il motivo per cui e' stata tolta.
    """
    m = meteo.meteo_corrente(lat, lon)
    a = meteo.qualita_aria(lat, lon)
    misurato = bool(m.get("disponibile"))

    esito = {
        "disponibile": misurato,
        "meteo": m,
        "aria": a,
        # Nessun bollettino ufficiale e' integrato: dirlo e' parte del punto.
        "bollettino_ufficiale": {
            "presente": False,
            "nota": ("Il bollettino ufficiale sulle ondate di calore della Regione "
                     "non e' integrato in questo prototipo: quanto segue e' un dato "
                     "meteo da modello e la sua interpretazione, non un'allerta "
                     "ufficiale."),
            "fonte_url": "https://salutelazio.it/it/salute-lazio-comunica/ondate-di-calore-2026",
        },
        "livelli_di_prova": {
            "misurato": (["temperatura_c", "percepita_c", "umidita_pct",
                          "precipitazione_mm", "vento_kmh"] if misurato else []),
            "ufficiale": [],
            "interpretazione": ["rischi", "gruppi_vulnerabili",
                                "azioni_preparatorie", "messaggio_cittadini"],
        },
        "limite": ("Il meteo non spiega la causa di un sintomo. Serve a dare "
                   "contesto territoriale, non a dedurre diagnosi."),
    }
    if misurato:
        esito["interpretazione"] = ai.bollettino_sanitario(m, a if a.get("disponibile") else None)
    else:
        esito["motivo"] = m.get("motivo", "dato ambientale non disponibile")
    return esito


def _voce(grezzo: bytes, tipo_contenuto: str) -> dict:
    """Trascrizione di un audio caricato dal browser.

    Il file arriva come multipart. Si estrae la sola parte binaria e la si
    passa a `voce.py`, che genera un nome temporaneo lato server, applica i
    limiti e ripulisce sempre. Il nome originale scelto dal client non viene
    usato per costruire alcun percorso: solo l'estensione, e solo se ammessa.
    """
    if "multipart/form-data" not in tipo_contenuto or "boundary=" not in tipo_contenuto:
        return {"testo": None, "backend": None, "tentativi": [],
                "errore": "atteso multipart/form-data con un campo `audio`"}
    confine = tipo_contenuto.split("boundary=", 1)[1].strip().strip('"')
    sep = ("--" + confine).encode()
    nome_originale = ""
    for parte in grezzo.split(sep):
        if b"\r\n\r\n" not in parte:
            continue
        intestazioni, corpo_parte = parte.split(b"\r\n\r\n", 1)
        testa = intestazioni.decode("utf-8", "replace")
        if 'name="audio"' not in testa:
            continue
        if "filename=" in testa:
            nome_originale = testa.split("filename=", 1)[1].split('"')[1] \
                if '"' in testa.split("filename=", 1)[1] else ""
        dati = corpo_parte.rstrip(b"\r\n-")
        if not dati:
            break
        percorso = None
        try:
            percorso = voce.salva_temporaneo(dati, nome_originale)
            return voce.trascrivi(percorso)
        except Exception as exc:  # noqa: BLE001
            return {"testo": None, "backend": None, "tentativi": [],
                    "errore": f"{type(exc).__name__}: {exc}"}
        finally:
            if percorso:
                try:
                    os.unlink(percorso)
                except OSError:
                    pass
    return {"testo": None, "backend": None, "tentativi": [],
            "errore": "nessun campo `audio` nel corpo della richiesta"}


def _dialogo(corpo: dict) -> dict:
    """Un giro del dialogo adattivo. Nessuno stato conservato sul server."""
    ingresso = str(corpo.get("ingresso") or "problema")
    testo = str(corpo.get("testo") or "")
    risposte = dialogo.normalizza_risposte(corpo.get("risposte"))

    # Il modello propone solo se ci sono candidate e se non e' stato disattivato.
    provvisorio = dialogo.passo(ingresso, risposte)
    scelta = None
    if (corpo.get("usa_modello", True) and provvisorio.get("domanda")
            and provvisorio.get("proposta_da") != "regola_obbligatoria"):
        ammessi = [dialogo.per_id(i) for i in provvisorio.get("id_ammessi", [])]
        scelta = ai.prossima_domanda(testo, [d for d in ammessi if d],
                                     dialogo.descrivi(risposte))

    esito = dialogo.passo(ingresso, risposte, scelta)
    segnali = ai.segnali_emergenza(testo)
    esito["emergenza"] = {
        "attiva": bool(segnali["attivi"]),
        "segnali": segnali["attivi"],
        "negati": segnali["negati"],
        "incerto": segnali["incerto"],
        "avviso": ("Nella descrizione compaiono segnali che richiedono soccorso "
                   "immediato: chiama il 112." if segnali["attivi"] else ""),
        "limite": segnali["limite"],
    }
    esito["catalogo"] = dialogo.intestazione()
    esito["risposte_registrate"] = risposte
    corretto = corpo.get("corretto")
    esito["risposte_invalidate"] = (
        dialogo.invalidate_da(str(corretto), {r["id"]: r["valore"] for r in risposte})
        if corretto else [])
    return esito


def _orientamento(corpo: dict, fonte: str) -> dict:
    """Il confronto fra le opzioni, piu' la spiegazione della scelta."""
    ingresso = str(corpo.get("ingresso") or "problema")
    testo = str(corpo.get("testo") or "")
    risposte = dialogo.normalizza_risposte(corpo.get("risposte"))
    fatti = {r["id"]: r["valore"] for r in risposte}
    pos = corpo.get("posizione") or {}
    lat = float(pos.get("lat") or ROMA[0])
    lon = float(pos.get("lon") or ROMA[1])

    segnali = ai.segnali_emergenza(testo)
    stop = dialogo.interruzione(risposte)
    if segnali["attivi"] or stop:
        # La regola di sicurezza viene prima e non interpella il modello.
        return {
            "meta": {"fonte_tipo": fonte},
            "esito": {
                "canale": "emergenza_112_118",
                "titolo": "Chiama il 112",
                "spiegazione": (stop or {}).get("motivo") or
                    ("Nella descrizione compaiono segnali che richiedono soccorso "
                     "immediato: " + ", ".join(segnali["attivi"]) + "."),
                "deciso_da": "regola di sicurezza (nessuna chiamata al modello)",
                "certezza": "alta",
                "cosa_manca": [],
            },
            "opzioni": [], "non_verificabili": [], "escluse": [],
            "cambiamenti": [],
            "emergenza": {"attiva": True, "segnali": segnali["attivi"],
                          "limite": segnali["limite"]},
            "avvertenze": ai.AVVERTENZE,
        }

    lista, meta = rete("attesa", fonte)
    confronto = opzioni.confronta(ingresso, fatti, lista, meta, lat, lon,
                                  corpo.get("precedenti"))
    esito = ai.orientamento(testo, confronto, fatti, segnali,
                            fatti_leggibili=dialogo.descrivi(risposte))
    return {
        "meta": meta,
        "esito": esito,
        **confronto,
        "emergenza": {"attiva": False, "segnali": [], "limite": segnali["limite"]},
        "scheda_professionista": _scheda(ingresso, testo, risposte, esito),
        "avvertenze": ai.AVVERTENZE,
    }


def _scheda(ingresso: str, testo: str, risposte: list, esito: dict) -> dict:
    """La scheda da portare al professionista: fatti riferiti, non conclusioni.

    Contiene solo cio' che la persona ha detto e le risposte che ha dato. Non
    aggiunge diagnosi, ipotesi o codici: e' un promemoria per non dimenticare
    nulla davanti al medico, e resta modificabile dal client.
    """
    return {
        "titolo": "Scheda da portare al professionista",
        "modificabile": True,
        "riferito_dalla_persona": testo,
        "risposte": [
            {"domanda": (dialogo.per_id(r["id"]) or {}).get("testo", r["id"]),
             "risposta": r["valore"]}
            for r in risposte],
        "motivo_del_contatto": esito.get("titolo"),
        "avvertenza": ("Questa scheda riporta quanto dichiarato dalla persona. "
                       "Non contiene una diagnosi ne' una valutazione clinica."),
    }



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

    # ------------------------------------------------------------------
    # POST. Tutto cio' che contiene testo scritto da una persona passa di qui.
    #
    # Non e' formalismo: una query string finisce nei log del server, nella
    # cronologia del browser, nel campo Referer verso terzi e negli strumenti
    # di sviluppo. Una descrizione di un problema di salute non deve stare in
    # nessuno di quei posti. Il corpo di una POST non ci finisce.
    # ------------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self._json({"errore": "endpoint sconosciuto"}, 404)
        try:
            lunghezza = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            lunghezza = 0
        if lunghezza > MAX_CORPO:
            return self._json({"errore": "corpo troppo grande"}, 413)
        grezzo = self.rfile.read(lunghezza) if lunghezza else b""

        try:
            if url.path == "/api/voce":
                return self._json(_voce(grezzo, self.headers.get("Content-Type", "")))
            corpo = json.loads(grezzo or b"{}")
            if not isinstance(corpo, dict):
                return self._json({"errore": "corpo non valido"}, 400)
            self.fonte = str(corpo.get("fonte") or FONTE_DEFAULT)
            if url.path == "/api/dialogo":
                return self._json(_dialogo(corpo))
            if url.path == "/api/orientamento":
                return self._json(_orientamento(corpo, self.fonte))
            return self._json({"errore": "endpoint sconosciuto"}, 404)
        except json.JSONDecodeError:
            return self._json({"errore": "corpo non e' JSON valido"}, 400)
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

        # ---- copertura e qualita' delle sorgenti ---------------------------
        if percorso_url == "/api/copertura":
            return self._json(_copertura())

        # ---- bollettino ambientale (scheda Rete) ---------------------------
        if percorso_url == "/api/bollettino":
            lat = float(uno("lat", ROMA[0]))
            lon = float(uno("lon", ROMA[1]))
            return self._json(_bollettino(lat, lon))

        if percorso_url == "/api/health":
            return self._json({
                "llm": llm.health(),
                "voce": voce.stato(),
                "catalogo": dialogo.intestazione(),
            })

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


