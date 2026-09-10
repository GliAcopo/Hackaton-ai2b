"""Modulo per la trascrizione vocale del percorso cittadino.

Consente al cittadino di descrivere a voce il proprio problema di salute dal
browser. L'audio registrato viene convertito in testo e presentato in una
textarea EDITABILE nell'interfaccia utente prima di qualsiasi successiva analisi
o orientamento sanitario.

PERCHÉ QUESTA ARCHITETTURA E SCELTE DI PROGETTO:
1. Controllo al cittadino: una trascrizione automatica non è mai infallibile
   (negazioni, età, numeri, farmaci possono cambiare radicalmente il significato
   clinico). Il testo deve essere editabile prima di inviarlo al motore di dialogo.
2. Integrità ed esclusione categorica di allucinazioni:
   L'ispezione di `agy --help` ha verificato che la CLI di Antigravity non espone
   alcun parametro per allegare o passare un file audio (il sottocomando
   `mic-serve` serve a condividere il microfono di rete per sessioni interattive,
   non per trascrivere file batch). Passare il solo percorso del file nel prompt
   indurrebbe il modello a inventare una trascrizione senza aver mai ascoltato i
   byte: in sanità inventare sintomi è il fallimento peggiore possibile.
   Di conseguenza, il backend agy per file audio NON è disponibile e NON esegue
   alcun sottoprocesso; la costante `AGY_SUPPORTA_AUDIO = False` documenta cosa
   servirebbe per abilitarlo qualora la CLI introducesse un'opzione dedicata.
3. Fallback a cascata senza blocchi:
   Se faster-whisper non è installato nell'ambiente (comportamento atteso qui),
   l'errore viene gestito con grazia e registrato nei tentativi. Se un binario
   esterno (es. whisper.cpp) è configurato via `REGIA_WHISPER_BIN`, viene tentato.
   Se tutti i tentativi falliscono, il sistema restituisce `testo: None`: il frontend
   lascia la casella di testo manuale senza inventare o usare testi segnaposto.
4. Sicurezza:
   - File temporanei con prefisso fisso generati dal server (`tempfile.mkstemp`),
     senza mai usare il nome file fornito dal client.
   - Nessuna interpolazione shell: solo liste di argomenti con `shell=False`.
   - Pulizia dei file temporanei garantita in blocchi `finally`.
   - Limiti espliciti su dimensione (10 MB) e durata massima (120 s).
   - Verifica del formato audio basata sui byte di intestazione (magic number)
     oltre che sull'estensione, perché l'estensione inviata dal browser non è una prova.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import wave
from contextlib import contextmanager
from pathlib import Path

# --- Limiti e configurazione di sicurezza ------------------------------------

# Dimensione massima consentita per il file audio caricato (10 MB).
MAX_BYTES = 10 * 1024 * 1024

# Durata massima predefinita per l'audio del cittadino (2 minuti).
DURATA_MAX_S = 120.0

# Formati audio ammessi per la registrazione da browser e upload.
FORMATI_AMMESSI = frozenset({"webm", "ogg", "wav", "mp3", "m4a", "opus"})

# Stato del supporto audio nella CLI agy.
# FATTO VERIFICATO: `agy --help` non espone alcun argomento per allegare file audio
# (--prompt, --model, --json-schema, ecc. gestiscono solo testo/JSON).
# Se in una versione futura la CLI dovesse aggiungere ad esempio `--audio <file>`,
# basterà impostare AGY_SUPPORTA_AUDIO = True e implementare il passaggio del flag
# nel sottoprocesso. Finché non esiste un flag esplicito, passare il percorso nel
# prompt farebbe allucinare il testo al modello, cosa inaccettabile.
AGY_SUPPORTA_AUDIO = False

# Modello predefinito per faster-whisper (se installato nell'ambiente).
REGIA_WHISPER_MODEL = os.environ.get("REGIA_WHISPER_MODEL", "small")

# faster-whisper non e' installato nell'ambiente che esegue SubitoSalute Lazio: sta in un
# virtualenv separato dell'utente. Importarlo aggiungendo quel site-packages a
# sys.path funzionerebbe finche' le dipendenze binarie (ctranslate2, av,
# onnxruntime) restano compatibili, e smetterebbe di funzionare senza preavviso
# il giorno in cui non lo sono piu'. Lo invochiamo invece nel SUO interprete,
# in un sottoprocesso: l'ambiente resta quello per cui la libreria e' stata
# installata, e un suo crash non porta giu' il server.
#
# Ordine: variabile d'ambiente, poi i percorsi noti, poi niente.
def _interprete_whisper() -> str | None:
    esplicito = os.environ.get("REGIA_WHISPER_PYTHON", "")
    if esplicito and Path(esplicito).exists():
        return esplicito
    for candidato in (Path.home() / "whisper" / ".venv" / "bin" / "python",
                      Path.home() / ".venvs" / "whisper" / "bin" / "python"):
        if candidato.exists():
            return str(candidato)
    return None


WHISPER_PYTHON = _interprete_whisper()

# Quanto si attende una trascrizione prima di rinunciare. Il primo avvio puo'
# includere lo scaricamento del modello: e' lento una volta sola, ma se accade
# davanti a un pubblico e' meglio rinunciare e lasciare il testo manuale che
# restare appesi.
TIMEOUT_TRASCRIZIONE_S = float(os.environ.get("REGIA_WHISPER_TIMEOUT", "180"))

# Il programma eseguito nell'interprete del venv. E' una costante letterale:
# il percorso dell'audio e il nome del modello arrivano da argv, mai
# interpolati nel sorgente ne' passati a una shell.
_PROGRAMMA_WHISPER = """
import json, sys
from faster_whisper import WhisperModel
percorso, modello = sys.argv[1], sys.argv[2]
m = WhisperModel(modello, device="cpu", compute_type="int8")
segmenti, info = m.transcribe(percorso, language="it", vad_filter=True)
testo = " ".join(s.text.strip() for s in segmenti).strip()
print(json.dumps({"testo": testo, "durata": getattr(info, "duration", None)}))
"""

# Percorso o nome dell'eseguibile whisper esterno (es. whisper.cpp / main).
REGIA_WHISPER_BIN = os.environ.get("REGIA_WHISPER_BIN", "")

# Percorso opzionale del modello per il binario whisper esterno.
REGIA_WHISPER_MODEL_PATH = os.environ.get("REGIA_WHISPER_MODEL_PATH", "")


# --- Rilevamento e validazione dei formati (Magic Numbers) --------------------

def _rileva_formato_magic(dati: bytes) -> str | None:
    """Riconosce il formato audio esaminando i primi byte (magic number).

    L'estensione inviata dal client HTTP può essere arbitraria o contraffatta;
    la verifica dei byte iniziali evita di sottoporre ai backend file non audio,
    script o payload non pertinenti.
    """
    if len(dati) < 4:
        return None

    # WAV: RIFF....WAVE
    if dati.startswith(b"RIFF") and len(dati) >= 12 and dati[8:12] == b"WAVE":
        return "wav"

    # Ogg: OggS (usato anche per flussi Opus registrati da Firefox/Chrome)
    if dati.startswith(b"OggS"):
        return "ogg"

    # WebM: EBML header (0x1A 0x45 0xDF 0xA3) tipico di Chrome MediaRecorder
    if dati.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"

    # MP3: tag ID3v2 oppure frame sync MPEG (11 bit a 1)
    if dati.startswith(b"ID3"):
        return "mp3"
    if len(dati) >= 2 and dati[0] == 0xFF and (dati[1] & 0xE0) == 0xE0:
        return "mp3"

    # M4A / MP4 container: 'ftyp' a offset 4
    if len(dati) >= 8 and dati[4:8] == b"ftyp":
        return "m4a"

    # AAC raw con ADTS sync
    if len(dati) >= 2 and dati[:2] in (b"\xff\xf1", b"\xff\xf9"):
        return "m4a"

    return None


def _formati_compatibili(estensione: str, formato_magic: str) -> bool:
    """Verifica la compatibilità tra estensione dichiarata e magic number rilevato."""
    if estensione == formato_magic:
        return True
    # Opus registrato dal browser viaggia spesso in container Ogg o WebM
    if estensione == "opus" and formato_magic in ("ogg", "webm"):
        return True
    if estensione == "ogg" and formato_magic == "ogg":
        return True
    # Container audio MP4 / M4A / AAC
    if estensione in ("m4a", "mp3") and formato_magic in ("m4a", "mp3"):
        return True
    return False


# --- Gestione sicura dei file temporanei --------------------------------------

def salva_temporaneo(dati: bytes, nome_originale: str = "") -> str:
    """Salva i byte audio in un file temporaneo con nome generato dal server.

    Deduce SOLO l'estensione validata contro `FORMATI_AMMESSI` e ignora ogni
    altro elemento del nome originale, neutralizzando tentativi di path traversal
    o caratteri non sicuri. Verifica inoltre dimensione e magic number.

    Ritorna il percorso assoluto del file temporaneo creato. Chi chiama è
    responsabile della rimozione (es. tramite blocco finally o contextmanager).
    """
    if not dati:
        raise ValueError("Dati audio vuoti (0 byte)")

    if len(dati) > MAX_BYTES:
        raise ValueError(
            f"Dimensione audio ({len(dati)} byte) eccede il limite di {MAX_BYTES} byte "
            f"({MAX_BYTES // (1024 * 1024)} MB)"
        )

    formato_magic = _rileva_formato_magic(dati)
    if formato_magic is None:
        raise ValueError(
            "Intestazione del file (magic number) non riconosciuta come formato audio valido. "
            f"Formati ammessi: {', '.join(sorted(FORMATI_AMMESSI))}"
        )

    # Estrazione dell'estensione dal nome originale (se fornito)
    estensione_orig = Path(nome_originale).suffix.lower().lstrip(".") if nome_originale else ""

    if estensione_orig:
        if estensione_orig not in FORMATI_AMMESSI:
            raise ValueError(
                f"Estensione dichiarata '.{estensione_orig}' non consentita. "
                f"Formati ammessi: {', '.join(sorted(FORMATI_AMMESSI))}"
            )
        if not _formati_compatibili(estensione_orig, formato_magic):
            raise ValueError(
                f"Estensione dichiarata '.{estensione_orig}' non coerente con il "
                f"formato binario rilevato (.{formato_magic})"
            )
        estensione_finale = estensione_orig
    else:
        estensione_finale = formato_magic

    # Creazione sicura del file temporaneo: nome randomico generato dal sistema operativo
    fd, percorso = tempfile.mkstemp(prefix="regia_voce_", suffix=f".{estensione_finale}")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dati)
    except Exception:
        try:
            os.unlink(percorso)
        except OSError:
            pass
        raise

    return percorso


@contextmanager
def audio_temporaneo(dati: bytes, nome_originale: str = ""):
    """Context manager per l'uso sicuro di un file audio temporaneo con cleanup garantito."""
    percorso = salva_temporaneo(dati, nome_originale)
    try:
        yield percorso
    finally:
        try:
            if os.path.exists(percorso):
                os.unlink(percorso)
        except OSError:
            pass


# --- Misurazione della durata audio ------------------------------------------

def _determina_durata(percorso_audio: str) -> float | None:
    """Calcola la durata in secondi del file audio senza dipendenze esterne obbligatorie.

    Per file WAV usa il modulo `wave` della stdlib. Per altri formati usa `ffprobe`
    se presente nel PATH di sistema, invocato con lista argomenti e shell=False.
    Se non è possibile determinare la durata, ritorna None senza bloccare il flusso.
    """
    # 1. Tentativo nativo stdlib per file WAV
    try:
        with wave.open(percorso_audio, "rb") as wf:
            framerate = wf.getframerate()
            nframes = wf.getnframes()
            if framerate > 0:
                return nframes / float(framerate)
    except Exception:
        pass

    # 2. Tentativo con ffprobe (se installato nel PATH)
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            proc = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    percorso_audio,
                ],
                capture_output=True,
                text=True,
                timeout=5.0,
                shell=False,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                durata = float(proc.stdout.strip())
                if durata >= 0:
                    return durata
        except Exception:
            pass

    return None


# --- Trascrizione e catena dei tentativi --------------------------------------

def trascrivi(percorso_audio: str, durata_max_s: float = DURATA_MAX_S) -> dict:
    """Trascrive un file audio tentando in ordine i backend configurati.

    Rispetta esattamente la forma richiesta dal contratto API `POST /api/voce`:
    {
        "testo": str | None,
        "backend": str | None,
        "tentativi": [{"backend": str, "esito": str}],
        "durata_s": float | None,
        "limite": str,
        "errore": str | None,
    }

    Catena dei tentativi:
    1. agy: non invocato (CLI priva di supporto audio per file, evitata per non allucinare).
    2. faster-whisper: libreria Python opzionale (se installata, con modello REGIA_WHISPER_MODEL).
    3. whisper.cpp / binario esterno: eseguibile indicato da REGIA_WHISPER_BIN se presente in PATH.

    Se tutti i backend falliscono, restituisce testo=None ed errore esplicativo.
    Non inventa MAI trascrizioni di fantasia né testi di prova.
    """
    limite_descrittivo = f"massimo {int(durata_max_s)}s, {MAX_BYTES // (1024 * 1024)} MB"
    tentativi: list[dict[str, str]] = []

    # 1. Verifica esistenza del file
    if not os.path.isfile(percorso_audio):
        return {
            "testo": None,
            "backend": None,
            "tentativi": [],
            "durata_s": None,
            "limite": limite_descrittivo,
            "errore": f"File audio non trovato: {percorso_audio}",
        }

    # 2. Verifica dimensione del file
    try:
        dimensione = os.path.getsize(percorso_audio)
    except OSError as exc:
        return {
            "testo": None,
            "backend": None,
            "tentativi": [],
            "durata_s": None,
            "limite": limite_descrittivo,
            "errore": f"Impossibile leggere la dimensione del file: {exc}",
        }

    if dimensione == 0:
        return {
            "testo": None,
            "backend": None,
            "tentativi": [],
            "durata_s": 0.0,
            "limite": limite_descrittivo,
            "errore": "File audio vuoto (0 byte)",
        }

    if dimensione > MAX_BYTES:
        return {
            "testo": None,
            "backend": None,
            "tentativi": [],
            "durata_s": None,
            "limite": limite_descrittivo,
            "errore": (
                f"Dimensione del file ({dimensione / (1024 * 1024):.1f} MB) "
                f"superiore al limite massimo consentito ({MAX_BYTES // (1024 * 1024)} MB)"
            ),
        }

    # 3. Verifica formato tramite intestazione (magic number) ed estensione
    try:
        with open(percorso_audio, "rb") as f:
            primi_byte = f.read(512)
    except OSError as exc:
        return {
            "testo": None,
            "backend": None,
            "tentativi": [],
            "durata_s": None,
            "limite": limite_descrittivo,
            "errore": f"Impossibile leggere il file audio: {exc}",
        }

    formato_magic = _rileva_formato_magic(primi_byte)
    if formato_magic is None:
        return {
            "testo": None,
            "backend": None,
            "tentativi": [],
            "durata_s": None,
            "limite": limite_descrittivo,
            "errore": (
                "Formato binario non riconosciuto come audio valido. "
                f"Formati ammessi: {', '.join(sorted(FORMATI_AMMESSI))}"
            ),
        }

    estensione = Path(percorso_audio).suffix.lower().lstrip(".")
    if estensione and estensione not in FORMATI_AMMESSI:
        return {
            "testo": None,
            "backend": None,
            "tentativi": [],
            "durata_s": None,
            "limite": limite_descrittivo,
            "errore": (
                f"Estensione '{estensione}' non ammessa. "
                f"Formati ammessi: {', '.join(sorted(FORMATI_AMMESSI))}"
            ),
        }

    if estensione and not _formati_compatibili(estensione, formato_magic):
        return {
            "testo": None,
            "backend": None,
            "tentativi": [],
            "durata_s": None,
            "limite": limite_descrittivo,
            "errore": (
                f"Estensione del file (.{estensione}) non coerente con l'intestazione binaria (.{formato_magic})"
            ),
        }

    # 4. Verifica della durata (se misurabile)
    durata_s = _determina_durata(percorso_audio)
    if durata_s is not None and durata_s > durata_max_s:
        return {
            "testo": None,
            "backend": None,
            "tentativi": [],
            "durata_s": round(durata_s, 2),
            "limite": limite_descrittivo,
            "errore": (
                f"Durata dell'audio ({durata_s:.1f}s) superiore al limite massimo consentito ({durata_max_s:.0f}s)"
            ),
        }

    # 5. Tentativo 1: agy
    # Registrato obbligatoriamente nella catena ma non eseguito come sottoprocesso,
    # perché la CLI non supporta allegati audio e genererebbe testo inventato.
    if not AGY_SUPPORTA_AUDIO:
        tentativi.append({
            "backend": "agy",
            "esito": "non supportato: la CLI non espone un argomento per allegare audio (verificato su agy --help)",
        })
    else:
        # Codice predisposto nel caso in cui un futuro aggiornamento della CLI offra
        # un'opzione dedicata per file audio (es. `agy --audio <file>`).
        try:
            inizio_agy = time.monotonic()
            cmd_agy = [
                "agy",
                "--print",
                "--prompt",
                "Trascrivi fedelmente questo audio in italiano, senza commenti o aggiunte.",
            ]
            proc = subprocess.run(
                cmd_agy,
                capture_output=True,
                text=True,
                timeout=60.0,
                shell=False,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return {
                    "testo": proc.stdout.strip(),
                    "backend": "agy",
                    "tentativi": tentativi + [{"backend": "agy", "esito": "trascrizione completata"}],
                    "durata_s": round(durata_s, 2) if durata_s is not None else None,
                    "limite": limite_descrittivo,
                    "errore": None,
                }
            tentativi.append({
                "backend": "agy",
                "esito": f"terminato con codice {proc.returncode}: {proc.stderr[:200]}",
            })
        except Exception as exc:
            tentativi.append({
                "backend": "agy",
                "esito": f"errore esecuzione agy: {exc}",
            })

    # 6. Tentativo 2a: faster-whisper nel suo virtualenv, via sottoprocesso.
    if WHISPER_PYTHON:
        inizio_fw = time.monotonic()
        try:
            proc = subprocess.run(
                [WHISPER_PYTHON, "-c", _PROGRAMMA_WHISPER,
                 percorso_audio, REGIA_WHISPER_MODEL],
                capture_output=True, text=True, timeout=TIMEOUT_TRASCRIZIONE_S,
                stdin=subprocess.DEVNULL,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                dati = json.loads(proc.stdout.strip().splitlines()[-1])
                testo_trascritto = (dati.get("testo") or "").strip()
                if testo_trascritto:
                    tentativi.append({
                        "backend": "faster-whisper",
                        "esito": (f"trascrizione completata in "
                                  f"{time.monotonic() - inizio_fw:.2f}s "
                                  f"({len(testo_trascritto)} caratteri), "
                                  f"modello {REGIA_WHISPER_MODEL}"),
                    })
                    return {
                        "testo": testo_trascritto,
                        "backend": f"faster-whisper ({REGIA_WHISPER_MODEL})",
                        "tentativi": tentativi,
                        "durata_s": (round(dati["durata"], 2)
                                     if dati.get("durata") else durata_s),
                        "limite": limite_descrittivo,
                        "errore": None,
                    }
                # Audio muto o solo rumore: la trascrizione e' vuota. Non e' un
                # errore, e non va riempita con niente.
                tentativi.append({
                    "backend": "faster-whisper",
                    "esito": "nessun parlato riconosciuto nell'audio",
                })
            else:
                tentativi.append({
                    "backend": "faster-whisper",
                    "esito": (f"uscita {proc.returncode}: "
                              f"{(proc.stderr or '')[-300:].strip()}"),
                })
        except subprocess.TimeoutExpired:
            tentativi.append({
                "backend": "faster-whisper",
                "esito": f"timeout dopo {TIMEOUT_TRASCRIZIONE_S}s",
            })
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            tentativi.append({
                "backend": "faster-whisper",
                "esito": f"risposta non interpretabile: {exc}",
            })

    # 6b. Tentativo 2b: faster-whisper importabile direttamente, se mai lo fosse.
    try:
        from faster_whisper import WhisperModel  # type: ignore

        inizio_fw = time.monotonic()
        modello = WhisperModel(REGIA_WHISPER_MODEL, device="cpu", compute_type="int8")
        segmenti, info = modello.transcribe(
            percorso_audio,
            language="it",
            vad_filter=True,
        )
        testo_trascritto = " ".join(s.text.strip() for s in segmenti).strip()
        durata_rilevata = getattr(info, "duration", None) or durata_s
        tempo_impiegato = time.monotonic() - inizio_fw

        tentativi.append({
            "backend": "faster-whisper",
            "esito": f"trascrizione completata in {tempo_impiegato:.2f}s ({len(testo_trascritto)} caratteri)",
        })
        return {
            "testo": testo_trascritto,
            "backend": "faster-whisper",
            "tentativi": tentativi,
            "durata_s": round(durata_rilevata, 2) if durata_rilevata is not None else None,
            "limite": limite_descrittivo,
            "errore": None,
        }
    except ImportError as exc:
        # Comportamento atteso su questa macchina: libreria non presente.
        tentativi.append({
            "backend": "faster-whisper",
            "esito": f"modulo non installato ({exc})",
        })
    except Exception as exc:
        tentativi.append({
            "backend": "faster-whisper",
            "esito": f"errore durante la trascrizione: {exc}",
        })

    # 7. Tentativo 3: whisper.cpp o binario esterno via REGIA_WHISPER_BIN
    if not REGIA_WHISPER_BIN:
        tentativi.append({
            "backend": "whisper.cpp",
            "esito": "non configurato: variabile d'ambiente REGIA_WHISPER_BIN non impostata",
        })
    else:
        eseguibile = shutil.which(REGIA_WHISPER_BIN)
        if not eseguibile:
            tentativi.append({
                "backend": "whisper.cpp",
                "esito": f"eseguibile '{REGIA_WHISPER_BIN}' non trovato nel PATH",
            })
        else:
            cmd = [eseguibile, "-f", percorso_audio, "-l", "it"]
            if REGIA_WHISPER_MODEL_PATH:
                cmd.extend(["-m", REGIA_WHISPER_MODEL_PATH])

            try:
                inizio_cpp = time.monotonic()
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60.0,
                    shell=False,
                    check=False,
                )
                tempo_impiegato = time.monotonic() - inizio_cpp
                if proc.returncode == 0:
                    testo_trascritto = proc.stdout.strip()
                    tentativi.append({
                        "backend": "whisper.cpp",
                        "esito": f"trascrizione completata in {tempo_impiegato:.2f}s ({len(testo_trascritto)} caratteri)",
                    })
                    return {
                        "testo": testo_trascritto,
                        "backend": "whisper.cpp",
                        "tentativi": tentativi,
                        "durata_s": round(durata_s, 2) if durata_s is not None else None,
                        "limite": limite_descrittivo,
                        "errore": None,
                    }
                stderr_snip = proc.stderr.strip()[:200] if proc.stderr else "nessun output su stderr"
                tentativi.append({
                    "backend": "whisper.cpp",
                    "esito": f"terminato con codice {proc.returncode}: {stderr_snip}",
                })
            except subprocess.TimeoutExpired:
                tentativi.append({
                    "backend": "whisper.cpp",
                    "esito": "timeout durante l'esecuzione del processo (limite 60s)",
                })
            except Exception as exc:
                tentativi.append({
                    "backend": "whisper.cpp",
                    "esito": f"errore durante l'esecuzione: {exc}",
                })

    # 8. Tutti i tentativi sono falliti: restituisce testo None senza inventare nulla
    motivi = "; ".join(f"{t['backend']}: {t['esito']}" for t in tentativi)
    return {
        "testo": None,
        "backend": None,
        "tentativi": tentativi,
        "durata_s": round(durata_s, 2) if durata_s is not None else None,
        "limite": limite_descrittivo,
        "errore": f"Nessun backend di trascrizione disponibile ({motivi})",
    }


# --- Stato dei backend per /api/health ----------------------------------------

def stato() -> dict:
    """Riporta quali backend di trascrizione sono realmente disponibili su questa macchina.

    Progettato per essere esposto dall'endpoint /api/health. Non mente sullo stato:
    se faster-whisper non è installato o agy non supporta audio, lo dichiara esplicitamente.
    """
    fw_disponibile = False
    fw_motivo = ""
    fw_dove = None
    if WHISPER_PYTHON:
        # Non e' importabile da qui, ma e' installato: sta nel virtualenv
        # dell'utente e lo invochiamo nel suo interprete. Dire "non
        # disponibile" sarebbe falso quanto dire che funziona senza averlo
        # verificato, quindi si controlla anche che il modello sia gia' in
        # cache: un primo uso che deve scaricare mezzo giga e' un'altra cosa.
        cache = Path.home() / ".cache" / "huggingface" / "hub"
        scaricato = any(cache.glob(f"*faster-whisper-{REGIA_WHISPER_MODEL}*")) \
            if cache.exists() else False
        fw_disponibile = True
        fw_dove = WHISPER_PYTHON
        fw_motivo = (
            f"disponibile in un interprete separato ({WHISPER_PYTHON}); "
            f"modello '{REGIA_WHISPER_MODEL}' "
            + ("gia' scaricato" if scaricato
               else "NON ancora scaricato: il primo uso richiede rete"))
    else:
        try:
            import faster_whisper  # noqa: F401
            fw_disponibile = True
            fw_dove = "ambiente corrente"
            fw_motivo = f"installato, modello predefinito '{REGIA_WHISPER_MODEL}'"
        except ImportError as exc:
            fw_motivo = f"non installato ({exc})"

    whisper_bin_disponibile = False
    whisper_bin_motivo = ""
    if REGIA_WHISPER_BIN:
        trovato = shutil.which(REGIA_WHISPER_BIN)
        if trovato:
            whisper_bin_disponibile = True
            whisper_bin_motivo = f"trovato in {trovato}"
        else:
            whisper_bin_motivo = f"eseguibile '{REGIA_WHISPER_BIN}' non trovato nel PATH"
    else:
        whisper_bin_motivo = "variabile REGIA_WHISPER_BIN non impostata"

    backend_attivo = None
    if AGY_SUPPORTA_AUDIO:
        backend_attivo = "agy"
    elif fw_disponibile:
        backend_attivo = "faster-whisper"
    elif whisper_bin_disponibile:
        backend_attivo = "whisper.cpp"

    return {
        "disponibile": any([AGY_SUPPORTA_AUDIO, fw_disponibile, whisper_bin_disponibile]),
        "backend_attivo": backend_attivo,
        "agy": {
            "disponibile": AGY_SUPPORTA_AUDIO,
            "motivo": "non supportato: la CLI non espone un argomento per allegare audio (verificato su agy --help)",
        },
        "faster_whisper": {
            "disponibile": fw_disponibile,
            "interprete": fw_dove,
            "modello": REGIA_WHISPER_MODEL,
            "motivo": fw_motivo,
        },
        "whisper_bin": {
            "disponibile": whisper_bin_disponibile,
            "eseguibile": REGIA_WHISPER_BIN or None,
            "motivo": whisper_bin_motivo,
        },
        "limiti": {
            "max_bytes": MAX_BYTES,
            "durata_max_s": DURATA_MAX_S,
            "formati_ammessi": sorted(list(FORMATI_AMMESSI)),
        },
    }


if __name__ == "__main__":
    print(json.dumps(stato(), indent=2, ensure_ascii=False))
