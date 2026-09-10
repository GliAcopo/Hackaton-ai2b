"""Stato della rete dei pronto soccorso del Lazio.

Una firma sola, due sorgenti dietro:

    stato_rete("snapshot")  # CSV open data, rilevazione del 2021-07-15 16:58
    stato_rete("live")      # API Salute Lazio, dato vivo di adesso

ONESTA' SULLA FONTE. Il dataset che la Regione pubblica come open data e si
chiama "accessi in tempo reale" e' in realta' congelato: il datastore CKAN
restituisce sempre e solo la rilevazione del 15/07/2021 fra le 16:56 e le
16:58. Non e' un problema da nascondere simulando un orologio: ogni risposta
porta `fonte` e `rilevato_il`, e l'interfaccia li mostra sempre.

Il dato vivo esiste pero' altrove: il portale salutelazio.it interroga
un'API pubblica e senza autenticazione che pubblica, presidio per presidio,
i pazienti in attesa per priorita' e i tempi di attesa medio e massimo.
E' quella che alimenta `fonte="live"`.

LE DUE FONTI NON DICONO LA STESSA COSA, e questo cambia gli indici:

  snapshot -> attesa + trattamento + osservazione + boarding, per colore.
              Si sa chi c'e' DENTRO: la pressione (occupazione) si calcola.
  live     -> solo la CODA, per priorita', piu' i tempi di attesa VERI.
              Non si sa chi e' gia' in trattamento: la pressione non si
              calcola e resta None, dichiarata. In cambio la sofferenza
              smette di essere stimata e diventa misurata.

Meta' degli indici da una fonte e meta' dall'altra sarebbe un pasticcio: chi
guarda deve sapere quale sta guardando. Per questo `meta` porta sempre fonte,
istante e copertura, e l'interfaccia li mostra.

TRE TEMPI, NON UNO. Un errore facile e' scrivere `datetime.now()` accanto a un
numero e chiamarlo "aggiornato adesso". Sono tre cose diverse e vanno tenute
separate perche' rispondono a tre domande diverse:

    istante_fonte  quando il dato e' vero secondo CHI LO PUBBLICA.
                   Lo snapshot ce l'ha (la colonna DATA del CSV).
                   L'API live NON lo pubblica: nessun campo `updatedAt` nella
                   risposta per presidio. Quindi vale None, ed e' dichiarato
                   con `istante_fonte_pubblicato: false`. Mettere l'ora nostra
                   al suo posto sarebbe inventare una garanzia che non abbiamo.
    acquisito_il   quando NOI abbiamo scaricato quel dato dalla rete. Per una
                   lettura da cache resta l'istante dello scaricamento
                   originale, non quello della rilettura: e' esattamente il
                   punto in cui il codice precedente sbagliava.
    letto_il       quando questa risposta e' stata costruita. Serve solo a
                   calcolare `eta_dato_s = letto_il - acquisito_il`.
"""
from __future__ import annotations

import concurrent.futures
import csv
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
SNAPSHOT = RADICE / "2-data" / "raw" / "dataset_principale" / "lazio" / "pronto_soccorso_accessi_tempo_reale.csv"
PRESIDI = RADICE / "2-data" / "derived" / "presidi.json"
MAPPA_LIVE = RADICE / "2-data" / "derived" / "mappa_live.json"
CACHE_LIVE = RADICE / "2-data" / "cache" / "live.json"

STATO_LIVE = ("https://server.salutelazio.it/server/external-services/"
              "facilities/structures/emergency-status?facilityId=")

# Quanto teniamo buona una lettura live prima di richiederla. Non e' pigrizia:
# la coda di un pronto soccorso non cambia in dieci secondi, e senza questo un
# refresh della pagina spara 49 richieste a un server pubblico altrui.
TTL_LIVE_S = 60
PARALLELE = 6      # richieste contemporanee: cortesia verso il server
TIMEOUT_S = 12


def num(valore: str | None) -> float | None:
    """Converte un numero scritto all'italiana o all'inglese. Vuoto -> None.

    ATTENZIONE, qui c'e' stato un bug che corrompeva i dati in silenzio.
    La versione precedente faceva `.replace(".", "")` per togliere i separatori
    di migliaia. Ma in `ps_durata_permanenza_storico.csv` la STESSA RIGA mescola
    `"2,46"` (virgola decimale, quotato) e ` 96.41` (punto decimale, non
    quotato): quella regola trasformava 96.41 in 9641.0 senza dire niente.

    Regola corretta: il separatore decimale e' l'ULTIMO fra `.` e `,`.
    """
    if valore is None:
        return None
    v = str(valore).strip().replace("%", "").replace(" ", "")
    if not v:
        return None
    ha_punto, ha_virgola = "." in v, "," in v
    if ha_punto and ha_virgola:
        # l'ultimo dei due e' il decimale, l'altro separa le migliaia
        if v.rfind(",") > v.rfind("."):
            v = v.replace(".", "").replace(",", ".")
        else:
            v = v.replace(",", "")
    elif ha_virgola:
        v = v.replace(",", ".")
    # solo punto: e' gia' decimale, non toccare
    try:
        return float(v)
    except ValueError:
        return None


def intero(valore: str | None) -> int:
    n = num(valore)
    return int(n) if n is not None else 0


def norm(nome: str) -> str:
    """Chiave di join robusta fra dataset scritti da uffici diversi."""
    nome = (nome or "").strip().lower().replace("'", "'")
    return re.sub(r"[^a-z0-9]+", " ", nome).strip()


@dataclass
class StatoPS:
    """Lo stato osservato di un pronto soccorso in un istante."""

    codice: str
    nome: str
    tipo: str          # PS | DEA I | DEA II | PS SPEC.
    comune: str
    asl: str
    rilevato_il: str      # alias storico di istante_fonte, tenuto per compatibilita'

    # in attesa di essere visitati: e' qui che si misura il sovraffollamento
    attesa: dict[str, int] = field(default_factory=dict)
    # gia' in trattamento
    trattamento: dict[str, int] = field(default_factory=dict)
    # in osservazione breve: il boarding, il vero collo di bottiglia
    osservazione: dict[str, int] = field(default_factory=dict)

    tot_attesa: int = 0
    tot_trattamento: int = 0
    tot_osservazione: int = 0
    tot_ricovero: int = 0
    presenti: int = 0

    # Tempi di attesa PUBBLICATI dalla Regione (solo fonte live). Quando ci
    # sono, la sofferenza non va piu' stimata dalla lunghezza della coda:
    # e' il tempo vero, misurato dal presidio.
    attesa_media_h: float | None = None
    attesa_max_h: float | None = None

    # I CINQUE LIVELLI ORIGINALI, non aggregati. La conversione ai quattro
    # colori storici serve a far parlare snapshot e live la stessa lingua negli
    # indici, ma e' una perdita di informazione: aggregare il livello 3
    # (urgenza differibile) col 4 (urgenza minore) non dimostra affatto che i
    # casi siano trattabili fuori dal pronto soccorso. Chi vuole quel giudizio
    # deve poter vedere i livelli separati, quindi li conserviamo qui accanto.
    # Ogni voce: {livello, etichetta, in_attesa, attesa_media_h, attesa_max_h}.
    attesa_livelli: list[dict] = field(default_factory=list)

    # False quando la fonte pubblica solo la coda: chi e' gia' in trattamento
    # o in osservazione non e' noto, quindi l'occupazione non e' calcolabile.
    ha_presenti: bool = True

    # False quando la fonte non ha dato niente per questo presidio. NON e' lo
    # stesso di "zero pazienti": un presidio che non trasmette sembrerebbe
    # vuoto e finirebbe in cima alle destinazioni consigliate. Va escluso.
    dato_disponibile: bool = True
    nota_fonte: str = ""

    # arricchimento da presidi.json (puo' mancare finche' non e' costruito)
    lat: float | None = None
    lon: float | None = None
    storico: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


COLORI = ("rossi", "gialli", "verdi", "bianchi")


def _da_riga(riga: dict[str, str], quando: str) -> StatoPS:
    def gruppo(suffisso: str) -> dict[str, int]:
        return {c: intero(riga.get(f"{c.upper()}_{suffisso}")) for c in COLORI}

    return StatoPS(
        codice=(riga.get("CODICE") or "").strip(),
        nome=(riga.get("ISTITUTO") or "").strip(),
        tipo=(riga.get("TIPO") or "").strip(),
        comune=(riga.get("COMUNE") or "").strip(),
        asl=(riga.get("ASL") or "").strip(),
        rilevato_il=quando,
        attesa=gruppo("ATT"),
        trattamento=gruppo("TRATT"),
        osservazione=gruppo("OB"),
        tot_attesa=intero(riga.get("TOT_ATT")),
        tot_trattamento=intero(riga.get("TOT_TRATT")),
        tot_osservazione=intero(riga.get("TOT_OB")),
        tot_ricovero=intero(riga.get("TOT_RT")),
        presenti=intero(riga.get("TUTTI")),
    )


def _registro_presidi() -> dict[str, dict]:
    """presidi.json indicizzato per codice. Vuoto se non e' ancora costruito."""
    try:
        dati = json.loads(PRESIDI.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(p["codice"]): p for p in dati}


# --- Feed live ------------------------------------------------------------
#
# CORRISPONDENZA FRA LE DUE SCALE DI TRIAGE. Lo snapshot 2021 usa i quattro
# colori storici; l'API usa i cinque livelli numerici introdotti dalle linee
# di indirizzo nazionali sul triage (DM 2019). La tabella di conversione:
#
#   1 Emergenza            -> rossi
#   2 Urgenza              -> gialli    (ex arancione)
#   3 Urgenza differibile  -> verdi     (ex azzurro)
#   4 Urgenza minore       -> verdi
#   5 Non urgenza          -> bianchi
#
# LA RIGA CHE DECIDE TUTTO E' IL LIVELLO 3, e la scelta va motivata perche'
# sposta il "carico deviabile" di tutta la rete da 81 a 165 pazienti.
#
# Il codice verde della vecchia scala e' definito come "urgenza minore o
# DIFFERIBILE": copre cioe' entrambi i livelli che la scala a cinque separa in
# azzurro (3, differibile) e verde (4, minore). Mandare l'azzurro fra i gialli
# sembra piu' prudente, ma rende la fonte live incoerente con lo storico usato
# come moltiplicatore: nei dati 2021 i verdi sono il 65-70% degli accessi,
# percentuale che si spiega solo se comprendono anche i differibili.
#
# Resta il fatto che un differibile non e' un codice minore: per questo il
# carico deviabile non e' un conteggio ma resta corretto per la quota storica
# del presidio (vedi indici.calcola), il piano dichiara sempre quali codici
# tocca, e la deviazione riguarda i NUOVI accessi instradati dal 118, non le
# persone gia' in coda.
#
# Per tornare alla lettura prudente basta rimettere "3": "gialli" qui sotto.
LIVELLO_COLORE = {"1": "rossi", "2": "gialli", "3": "verdi",
                  "4": "verdi", "5": "bianchi"}


def _mappa_live() -> dict[str, dict]:
    try:
        return json.loads(MAPPA_LIVE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _cache_live() -> dict:
    try:
        return json.loads(CACHE_LIVE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _scarica_stato(psid: str) -> dict | None:
    """Stato live di un presidio. None se il presidio non lo pubblica."""
    try:
        with urllib.request.urlopen(STATO_LIVE + psid, timeout=TIMEOUT_S) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        # 422 = il presidio esiste in anagrafe ma non trasmette (Gemelli e
        # Campus Bio-Medico, alla verifica). Non e' un errore nostro.
        if exc.code in (404, 422):
            return None
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _leggi_live(mappa: dict[str, dict]) -> tuple[dict[str, dict], bool, float | None]:
    """Ritorna ({codice: risposta}, da_cache, quando_acquisito).

    `quando_acquisito` e' l'epoch dello SCARICAMENTO, non della rilettura: per
    una risposta servita dalla cache resta l'istante in cui quei numeri sono
    arrivati davvero dalla rete. E' il dato che permette di dire "questa lettura
    ha 4 minuti" invece di spacciarla per corrente.
    """
    cache = _cache_live()
    fresca = cache.get("quando", 0) + TTL_LIVE_S > time.time()
    if fresca and cache.get("dati"):
        return cache["dati"], True, cache.get("quando")

    def uno(voce):
        codice, m = voce
        return codice, _scarica_stato(m["psid"])

    dati: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(PARALLELE) as pool:
        for codice, risposta in pool.map(uno, mappa.items()):
            if risposta:
                dati[codice] = risposta
    if dati:
        adesso = time.time()
        CACHE_LIVE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_LIVE.write_text(json.dumps({"quando": adesso, "dati": dati},
                                         ensure_ascii=False), encoding="utf-8")
        return dati, False, adesso
    # rete giu': meglio una lettura vecchia DICHIARATA VECCHIA che nessun dato
    return cache.get("dati", {}), True, cache.get("quando")


def _stato_rete_live() -> tuple[list[StatoPS], dict]:
    """Coda e tempi di attesa veri, presidio per presidio, adesso."""
    mappa = _mappa_live()
    if not mappa:
        raise FileNotFoundError(
            "manca 2-data/derived/mappa_live.json: "
            "eseguire python3 4-src/costruisci_mappa_live.py")

    dati, da_cache, quando_acq = _leggi_live(mappa)
    registro = _registro_presidi()
    letto_il = datetime.now().isoformat(timespec="seconds")
    acquisito_il = (datetime.fromtimestamp(quando_acq).isoformat(timespec="seconds")
                    if quando_acq else None)
    eta_s = round(time.time() - quando_acq) if quando_acq else None

    stati: list[StatoPS] = []
    senza_dato: list[str] = []
    for codice, p in registro.items():
        risposta = dati.get(codice)
        s = StatoPS(
            codice=codice, nome=p.get("nome", ""), tipo=p.get("tipo", ""),
            comune=p.get("comune", ""), asl=p.get("asl", ""),
            # La fonte live non pubblica un istante proprio: qui va quando NOI
            # abbiamo acquisito il dato, mai l'ora della rilettura.
            rilevato_il=acquisito_il or letto_il,
            attesa={c: 0 for c in COLORI},
            trattamento={c: 0 for c in COLORI},
            osservazione={c: 0 for c in COLORI},
            lat=p.get("lat"), lon=p.get("lon"), storico=p.get("storico"),
            ha_presenti=False,
        )
        if risposta is None:
            senza_dato.append(s.nome)
            s.dato_disponibile = False
            s.nota_fonte = "il presidio non trasmette lo stato in tempo reale"
            stati.append(s)
            continue

        pesi_attesa: list[tuple[int, float]] = []
        for g in risposta.get("groups", []):
            gruppo = g.get("group", {}) or {}
            livello = str(gruppo.get("code"))
            quanti = int(g.get("total") or 0)
            # Prima si conserva il livello ORIGINALE, con la sua etichetta e i
            # suoi tempi: e' l'unica forma in cui il dato non ha perso nulla.
            s.attesa_livelli.append({
                "livello": livello,
                "etichetta": (gruppo.get("labels") or {}).get("it") or livello,
                "in_attesa": quanti,
                "attesa_media_h": round(float(g.get("avgWaitSeconds") or 0) / 3600, 2),
                "attesa_max_h": round(float(g.get("maxWaitSeconds") or 0) / 3600, 2),
            })
            # Solo dopo si aggrega ai quattro colori storici, che serve agli
            # indici per confrontare snapshot e live sulla stessa scala.
            colore = LIVELLO_COLORE.get(livello)
            if not colore or not quanti:
                continue
            s.attesa[colore] += quanti
            pesi_attesa.append((quanti, float(g.get("avgWaitSeconds") or 0)))
        s.tot_attesa = sum(s.attesa.values())
        # `presenti` resta 0 e non copia la coda. Sono due cose diverse: i
        # presenti comprendono chi e' gia' in trattamento o in osservazione, e
        # questa fonte non li pubblica. Copiarci dentro la coda farebbe
        # comparire un numero plausibile e sbagliato in ogni punto che legge
        # `presenti` - l'ordinamento "piu' pazienti presenti" compreso.

        if pesi_attesa and s.tot_attesa:
            # media pesata sui pazienti, non sui gruppi: tre gruppi da 1, 1 e
            # 19 persone non contano un terzo ciascuno.
            s.attesa_media_h = round(
                sum(q * a for q, a in pesi_attesa) / s.tot_attesa / 3600, 2)
        s.attesa_max_h = round(max(
            (float(g.get("maxWaitSeconds") or 0)
             for g in risposta.get("groups", [])), default=0.0) / 3600, 2)
        s.nota_fonte = "coda e tempi di attesa pubblicati dalla Regione"
        stati.append(s)

    meta = {
        "fonte": "API Salute Lazio (tempo reale)",
        "fonte_tipo": "live",
        "fonte_url": STATO_LIVE.split("?")[0],
        # La risposta per presidio non contiene alcun campo di data: la Regione
        # non dichiara a che ora quei numeri erano veri. Lo diciamo invece di
        # sostituirlo con l'ora nostra.
        "istante_fonte": None,
        "istante_fonte_pubblicato": False,
        "acquisito_il": acquisito_il,
        "letto_il": letto_il,
        "eta_dato_s": eta_s,
        "rilevato_il": acquisito_il or letto_il,   # compatibilita'
        "presidi": len(stati),
        "con_dato": len(stati) - len(senza_dato),
        "con_dato_live": len(stati) - len(senza_dato),
        "senza_dato": senza_dato,
        "senza_dato_live": senza_dato,
        "da_cache": da_cache,
        "solo_coda": True,
        "livelli_conservati": True,
        "avviso": (
            "Dato vivo: pazienti in attesa per priorita' e tempi di attesa "
            "pubblicati dalla Regione. La fonte non pubblica chi e' gia' in "
            "trattamento o in osservazione, quindi la PRESSIONE (occupazione) "
            "non e' calcolabile in questa modalita'; la sofferenza invece e' "
            "misurata sui tempi reali, non stimata."
        ),
        "limiti": [
            "La lunghezza della coda non e' il tempo di attesa di chi arriva "
            "adesso, e la media pubblicata non e' una previsione individuale.",
            "Meno pazienti in attesa non significa cure piu' appropriate: "
            "dice solo che in quell'istante c'era meno fila.",
            "I cinque livelli di priorita' restano separati in "
            "`attesa_livelli`: l'aggregazione ai quattro colori serve solo a "
            "confrontare questa fonte con lo storico.",
            "La fonte non dichiara l'istante a cui i numeri si riferiscono.",
        ],
    }
    return stati, meta


def stato_rete(fonte: str = "snapshot") -> tuple[list[StatoPS], dict]:
    """Ritorna (stati, meta). `meta` porta fonte e istante della rilevazione."""
    if fonte == "live":
        return _stato_rete_live()

    with SNAPSHOT.open(encoding="utf-8", newline="") as fh:
        righe = list(csv.DictReader(fh))

    # Il CSV ha tre timestamp a un minuto di distanza (16:56, 16:57, 16:58):
    # e' una sola rilevazione scritta in tre momenti. Prendiamo il piu' recente.
    quando = max((r.get("DATA") or "") for r in righe)
    stati = [_da_riga(r, (r.get("DATA") or quando).strip()) for r in righe]

    registro = _registro_presidi()
    agganciati = 0
    for s in stati:
        p = registro.get(s.codice)
        if not p:
            continue
        s.lat, s.lon, s.storico = p.get("lat"), p.get("lon"), p.get("storico")
        agganciati += 1

    letto_il = datetime.now().isoformat(timespec="seconds")
    try:
        acquisito_il = datetime.fromtimestamp(
            SNAPSHOT.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        acquisito_il = None

    meta = {
        "fonte": "open data Regione Lazio (snapshot)",
        "fonte_tipo": "snapshot",
        "fonte_url": "https://dati.lazio.it/",
        # Qui l'istante della fonte esiste davvero: e' la colonna DATA del CSV.
        "istante_fonte": quando,
        "istante_fonte_pubblicato": True,
        "acquisito_il": acquisito_il,          # quando abbiamo scaricato il CSV
        "letto_il": letto_il,
        "eta_dato_s": None,                    # un file su disco non "invecchia"
        "da_cache": False,
        "rilevato_il": quando,                 # compatibilita'
        "presidi": len(stati),
        "con_dato": len(stati),
        "senza_dato": [],
        "con_anagrafica": agganciati,
        "solo_coda": False,
        "livelli_conservati": False,
        "avviso": (
            "Il dataset regionale «accessi in tempo reale» e' fermo a questa "
            "rilevazione: e' l'ultima disponibile, non l'istante corrente."
        ),
        "limiti": [
            "Rilevazione unica del 15/07/2021: non e' una serie storica e non "
            "consente previsioni di afflusso.",
            "La lunghezza della coda non e' il tempo di attesa individuale.",
            "Meno pazienti in attesa non significa cure piu' appropriate.",
            "Questa fonte pubblica i quattro colori storici, non i cinque "
            "livelli: `attesa_livelli` resta quindi vuoto.",
        ],
    }
    return stati, meta


if __name__ == "__main__":
    stati, meta = stato_rete()
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print()
    peggiori = sorted(stati, key=lambda s: s.tot_attesa, reverse=True)[:8]
    print(f"{'PRESIDIO':32} {'TIPO':9} {'ATT':>4} {'TRATT':>6} {'OB':>4} {'PRES':>5}  attesa per colore")
    for s in peggiori:
        colori = " ".join(f"{c[0].upper()}{s.attesa[c]}" for c in COLORI)
        print(f"{s.nome[:32]:32} {s.tipo:9} {s.tot_attesa:4} {s.tot_trattamento:6} "
              f"{s.tot_osservazione:4} {s.presenti:5}  {colori}")

    # controllo di coerenza: la somma dei colori deve dare il totale dichiarato
    incoerenti = [s.nome for s in stati
                  if sum(s.attesa.values()) > s.tot_attesa]
    print(f"\npresidi: {len(stati)}  incoerenti: {len(incoerenti)}")
