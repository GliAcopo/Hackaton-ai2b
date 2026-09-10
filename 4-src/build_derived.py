#!/usr/bin/env python3
"""Costruisce i JSON derivati che l'app legge a runtime SENZA mai toccare la rete.

Produce:
  - 2-data/derived/presidi.json     (i 49 Pronto Soccorso/DEA del Lazio + storico + coordinate)
  - 2-data/derived/territorio.json  (farmacie attive + strutture sanitarie private accreditate)

Tutto stdlib. L'unico accesso di rete e' qui, in fase di build (geocoding via
Nominatim), con cache su disco: una volta generati i JSON, l'app non fa mai
richieste esterne.

Uso:
    python3 4-src/build_derived.py              # genera i due JSON
    python3 4-src/build_derived.py --verifica   # rilegge i JSON e stampa un report
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "2-data" / "raw" / "dataset_principale" / "lazio"
DERIVED = ROOT / "2-data" / "derived"
CACHE_DIR = ROOT / "2-data" / "cache"
CACHE_FILE = CACHE_DIR / "nominatim.json"

PRESIDI_JSON = DERIVED / "presidi.json"
TERRITORIO_JSON = DERIVED / "territorio.json"

# Bounding box grezzo del Lazio: usato sia per validare il geocoding sia per
# scartare righe di farmacie/strutture con coordinate palesemente sbagliate.
LAT_MIN, LAT_MAX = 40.7, 42.9
LON_MIN, LON_MAX = 11.4, 14.1

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "regia-hackathon-ai2b/1.0"


def in_bbox(lat: float, lon: float) -> bool:
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


# ---------------------------------------------------------------------------
# num(): conversione robusta di numeri scritti con convenzioni miste.
# ---------------------------------------------------------------------------
def num(value: str | None) -> float | None:
    """Converte una stringa numerica in float, gestendo virgola/punto misti.

    Regola (vedi bug in dataload.py da NON replicare: quello fa
    .replace(".", "") su TUTTO, il che in ps_durata_permanenza_storico.csv
    trasforma "96.41" (decimale col punto) in "9641.0"):

    - strip degli spazi
    - se la stringa contiene SIA "." che "," -> il separatore decimale e'
      l'ULTIMO dei due che compare nella stringa; l'altro e' un separatore
      di migliaia e va rimosso
    - se contiene solo "," -> e' il separatore decimale, sostituiscila con "."
    - se contiene solo "." -> e' GIA' un separatore decimale, lasciala stare
    - stringa vuota o non parsabile -> None
    """
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None

    ha_punto = "." in s
    ha_virgola = "," in s

    if ha_punto and ha_virgola:
        ultimo_punto = s.rfind(".")
        ultima_virgola = s.rfind(",")
        if ultima_virgola > ultimo_punto:
            # la virgola e' l'ultimo separatore incontrato -> e' il decimale
            s = s.replace(".", "").replace(",", ".")
        else:
            # il punto e' l'ultimo separatore incontrato -> e' il decimale
            s = s.replace(",", "")
    elif ha_virgola:
        s = s.replace(",", ".")
    # se ha solo il punto (o nessuno dei due) la stringa e' gia' pronta

    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Normalizzazione nomi per il join fra snapshot e storici.
# ---------------------------------------------------------------------------
# Espansioni applicate PRIMA della normalizzazione (sulla stringa minuscola).
# L'ordine conta: le sigle piu' lunghe/specifiche vanno prima di quelle corte
# che le contengono (es. "pol. univ." prima di eventuali "univ." generiche).
ABBREVIAZIONI = [
    ("pol. univ.", "policlinico universitario "),
    ("pol.u.", "policlinico universitario "),
    ("a.o.u.u.", "azienda ospedaliera universitaria "),
    ("a.o.", "azienda ospedaliera "),
    ("osp.c.", "ospedale classificato "),
    ("osp.", "ospedale "),
    ("c.c.a.", "casa di cura accreditata "),
    ("p.o.", "presidio ospedaliero "),
    ("pres.", "presidio "),
    ("irccspr", "irccs "),
    ("ss.", "santi "),
]


def _espandi_abbreviazioni(nome: str) -> str:
    s = nome.lower()
    for sigla, esteso in ABBREVIAZIONI:
        s = s.replace(sigla, esteso)
    return s


def _pulisci(s: str) -> str:
    """Toglie punteggiatura/apostrofi e collassa gli spazi."""
    s = s.replace("'", " ").replace("`", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _pulisci_comune(s: str) -> str:
    """Normalizzazione aggressiva del comune: minuscolo, senza spazi/punteggiatura.
    Serve solo per confrontare "Civitacastellana" con "CIVITA CASTELLANA"."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def varianti_nome(nome: str) -> set[str]:
    """Genera le forme normalizzate candidate per un nome di struttura.

    "S." puo' significare "San", "Santa", "Sant'" o "Santo": proviamo tutte
    e quattro le espansioni, oltre alla forma di base (senza espandere "s.").
    """
    s = _espandi_abbreviazioni(nome)
    varianti = {_pulisci(s)}
    for sostituto in ("san ", "santa ", "sant ", "santo "):
        varianti.add(_pulisci(s.replace("s.", sostituto)))
    return varianti


# ---------------------------------------------------------------------------
# Mappa manuale per i residui che l'algoritmo automatico non risolve.
#
# Costruita a mano dopo aver ispezionato le liste "non risolti" prodotte dal
# matching automatico (vedi sotto): per ciascuno dei 49 presidi del file
# maestro che il matcher (esatto -> contenimento -> difflib) non riusciva ad
# agganciare, e' stato cercato il corrispondente reale nei due file storici,
# usando comune + conoscenza del territorio (es. "Ospedale dei Castelli" di
# Ariccia e' lo stesso ospedale che negli storici e' ancora chiamato con il
# vecchio nome "Ospedale di Albano Laziale"; "P. Colombo" e' l'iniziale di
# "Paolo Colombo"; "OSP. S.GIOVANNI EVENGELISTA" ha un refuso nel CSV
# originale rispetto a "Evangelista", ecc.)
#
# Chiave: CODICE del presidio (file maestro). Valore: nome ESATTO (stringa
# NOME STRUTTURA) nel file storico corrispondente, oppure None se quel
# presidio e' legittimamente assente da quello storico.
# ---------------------------------------------------------------------------
MAPPA_MANUALE: dict[str, dict[str, str | None]] = {
    "92000": {"triage": "A.O.U.U. TOR VERGATA", "permanenza": "A.O.U.U. TOR VERGATA"},
    "91900": {"triage": "A.O.U.U. S.ANDREA", "permanenza": "A.O.U.U. S.ANDREA"},
    # Campus Biomedico: policlinico universitario privato, assente da entrambi
    # gli storici regionali.
    "91500": {"triage": None, "permanenza": None},
    "90600": {"triage": "A.O.U.U. UMBERTO I", "permanenza": "A.O.U.U. UMBERTO I"},
    # Bambino Gesu' Palidoro e' il presidio satellite (non il policlinico
    # principale di Roma, che invece e' agganciato automaticamente): non ha
    # una riga separata negli storici.
    "90402": {"triage": None, "permanenza": None},
    "90100": {"triage": "A.O. S.CAMILLO", "permanenza": "A.O. S.CAMILLO"},
    "29400": {"triage": "PRES. CASILINO", "permanenza": "PRES. CASILINO"},
    "28501": {"triage": "A.O. S.FILIPPO NERI", "permanenza": "A.O. S.FILIPPO NERI"},
    "27100": {"triage": "OSP. DI BELCOLLE", "permanenza": "OSP. DI BELCOLLE"},
    "26700": {"triage": "OSP. S.PERTINI", "permanenza": "OSP. S.PERTINI"},
    "22600": {"triage": "OSP. SS.TRINITA'", "permanenza": "OSP. SS.TRINITA'"},
    "21500": {"triage": "C.C.A. CITTA DI APRILIA", "permanenza": "C.C.A. CITTA DI APRILIA"},
    "18000": {"triage": "C.C.A. AURELIA HOSPITAL", "permanenza": None},
    "7600": {"triage": "OSP.C. G.VANNINI", "permanenza": "OSP.C. G.VANNINI"},
    "7400": {"triage": "OSP.C. CRISTO RE", "permanenza": None},
    "7300": {"triage": "OSP.C. S.CARLO DI NANCY", "permanenza": None},
    "7200": {"triage": "OSP.C. FATEBENEFRATELLI", "permanenza": "OSP.C. FATEBENEFRATELLI"},
    "7100": {
        "triage": "OSP.C. S.PIETRO FATEBENEFRATELLI",
        "permanenza": "OSP.C. S.PIETRO FATEBENEFRATELLI",
    },
    "6602": {"triage": "OSP. CTO ALESINI", "permanenza": "OSP. CTO ALESINI"},
    "6100": {"triage": "OSP. G.GRASSI", "permanenza": "OSP. G.GRASSI"},
    # Refuso nel CSV originale: "EVENGELISTA" invece di "EVANGELISTA".
    "5300": {
        "triage": "OSP. S.GIOVANNI EVENGELISTA",
        "permanenza": "OSP. S.GIOVANNI EVENGELISTA",
    },
    "4900": {"triage": "OSP. SS GONFALONE", "permanenza": None},
    "3000": {"triage": "OSP. REGIONALE OFTALMICO", "permanenza": "OSP. REGIONALE OFTALMICO"},
    "700": {"triage": "OSP. DI TARQUINIA", "permanenza": None},
    "13400": {"triage": "C.C.A.S.ANNA", "permanenza": None},
    "5400": {"triage": "OSP. PAOLO COLOMBO", "permanenza": "OSP. PAOLO COLOMBO"},
    "4700": {"triage": "OSP. S.SEBASTIANO", "permanenza": "OSP. S.SEBASTIANO"},
    "300": {"triage": "OSP. DI CIVITA CASTELLANA", "permanenza": None},
    "200": {"triage": "OSP. DI ACQUAPENDENTE", "permanenza": None},
    # Ospedale dei Castelli (Ariccia): negli storici compare ancora con il
    # vecchio nome "Ospedale di Albano Laziale" (stesso presidio).
    "29200": {"triage": "OSP. ALBANO LAZIALE", "permanenza": "OSP. ALBANO LAZIALE"},
    "4300": {"triage": "OSP. DI ANZIO E NETTUNO", "permanenza": "OSP. DI ANZIO E NETTUNO"},
}


# ---------------------------------------------------------------------------
# Coordinate cablate a mano per i presidi che Nominatim non geolocalizza
# (o localizza male). Verificate manualmente e controllate contro il
# bounding box del Lazio.
# ---------------------------------------------------------------------------
COORD_MANUALI: dict[str, tuple[float, float]] = {
    # Tutte verificate manualmente con query Nominatim mirate (indirizzo reale
    # del presidio), perche' le query generiche "<nome> <comune>" non
    # restituivano nulla (o, per Sant'Andrea, restituivano un falso positivo:
    # una via omonima nel centro di Roma invece dell'ospedale a Grottarossa).
    "91900": (41.9830777, 12.4703776),  # Sant'Andrea, Via di Grottarossa, Roma
    "92000": (41.8576274, 12.6309806),  # Policlinico Tor Vergata, Roma
    "90600": (41.9064570, 12.5121255),  # Policlinico Umberto I, Roma
    "90501": (41.9315345, 12.4294393),  # Policlinico Universitario A. Gemelli, Roma
    "7600": (41.8809797, 12.5434057),  # Ospedale Madre Giuseppina Vannini, Roma
    "7200": (41.8909123, 12.4769258),  # San Giovanni Calibita-FBF, Isola Tiberina, Roma
    "6602": (41.8578022, 12.4867694),  # CTO Andrea Alesini, Roma
    "4900": (42.0504267, 12.6214304),  # Ospedale SS. Gonfalone, Monterotondo
    "1901": (42.4225381, 12.9079954),  # San Camillo De Lellis, Rieti
    "700": (42.2511423, 11.7611662),  # Ospedale Civile, Tarquinia (centro cittadino)
    "4700": (41.8091805, 12.6753309),  # San Sebastiano Martire, Frascati
    "300": (42.2904959, 12.4206416),  # Andosilla, Civita Castellana
    "200": (42.7458734, 11.8653758),  # Ospedale Civile (S. Maria della Scala), Acquapendente
    # I 4 seguenti sono stati agganciati dalla pipeline automatica a un
    # falso positivo con lo stesso nome ma nel comune sbagliato (vedi nota
    # in _comune_coerente): individuati ispezionando a mano i display_name
    # salvati in cache, corretti con una query mirata all'indirizzo reale.
    "28501": (41.9477432, 12.4136326),  # San Filippo Neri, Via G. Martinotti, Roma (NON Cecchina/Albano)
    "21601": (41.6378888, 13.3231609),  # Fabrizio Spaziani, Via Armando Fabi, Frosinone (NON Sgurgola)
    "7400": (41.9181322, 12.4210287),  # Cristo Re, Via delle Calasanziane, Primavalle, Roma
    "6100": (41.7282811, 12.3000352),  # G. Battista Grassi, Lido di Ostia, Roma (NON Fiumicino)
}


# ---------------------------------------------------------------------------
# Caricamento CSV
# ---------------------------------------------------------------------------
def _leggi_csv(path: Path, delimiter: str = ",", encoding: str = "utf-8") -> list[dict[str, str]]:
    with path.open(encoding=encoding, newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        return [dict(row) for row in reader]


def carica_master() -> list[dict[str, str]]:
    righe = _leggi_csv(RAW / "pronto_soccorso_accessi_tempo_reale.csv")
    assert len(righe) == 49, f"attesi 49 presidi nel file maestro, trovati {len(righe)}"
    return righe


def carica_triage() -> list[dict[str, str]]:
    return _leggi_csv(RAW / "ps_accessi_triage_storico.csv")


def carica_permanenza() -> list[dict[str, str]]:
    return _leggi_csv(RAW / "ps_durata_permanenza_storico.csv")


# ---------------------------------------------------------------------------
# Matching nomi: esatto -> contenimento (stesso comune) -> difflib (stesso
# comune, con controllo dell'ultima parola per evitare falsi positivi su
# prefissi generici tipo "Policlinico Universitario ...").
# ---------------------------------------------------------------------------
class RigaStorico:
    __slots__ = ("varianti", "comune", "row")

    def __init__(self, row: dict[str, str], nome_col: str, comune_col: str):
        self.row = row
        self.varianti = varianti_nome(row[nome_col])
        self.comune = _pulisci_comune(row[comune_col])


def _trova_esatto(mv: set[str], pool: list[RigaStorico]) -> RigaStorico | None:
    for cand in pool:
        if mv & cand.varianti:
            return cand
    return None


def _trova_contenimento(mv: set[str], comune: str, pool: list[RigaStorico]) -> RigaStorico | None:
    for cand in pool:
        if cand.comune != comune:
            continue
        for a in mv:
            for b in cand.varianti:
                if len(a) < 6 or len(b) < 6:
                    continue
                corto, lungo = (a, b) if len(a) <= len(b) else (b, a)
                if corto in lungo and len(corto) / len(lungo) >= 0.5:
                    return cand
    return None


def _trova_difflib(mv: set[str], comune: str, pool: list[RigaStorico]) -> RigaStorico | None:
    candidati = [c for c in pool if c.comune == comune]
    if not candidati:
        return None
    piatto = [(v, c) for c in candidati for v in c.varianti]
    for a in mv:
        vicini = difflib.get_close_matches(a, [v for v, _ in piatto], n=1, cutoff=0.75)
        if vicini:
            for v, c in piatto:
                if v == vicini[0]:
                    # guardia: l'ultima parola (di solito la parte piu'
                    # specifica del nome) deve combaciare, altrimenti un
                    # prefisso lungo e generico ("policlinico universitario",
                    # "azienda ospedaliera universitaria") puo' produrre un
                    # punteggio alto fra due ospedali completamente diversi.
                    if a.split()[-1] == v.split()[-1]:
                        return c
    return None


def costruisci_pool(righe: list[dict[str, str]], nome_col: str, comune_col: str) -> list[RigaStorico]:
    return [RigaStorico(r, nome_col, comune_col) for r in righe]


def risolvi_storico(
    master: list[dict[str, str]],
    pool: list[RigaStorico],
    chiave_manuale: str,
    etichetta: str,
) -> dict[str, tuple[dict[str, str], str]]:
    """Associa ogni presidio del file maestro a una riga dello storico.

    Ritorna {codice: (row_storico, fonte_storico)}. I presidi non risolti
    (ne' automaticamente ne' dalla mappa manuale) non compaiono nel dict:
    per loro lo storico sara' "assente".
    """
    pool_residuo = list(pool)
    risultati: dict[str, tuple[dict[str, str], str]] = {}
    pending = list(master)

    fasi = [
        ("match_esatto", lambda row, pd: _trova_esatto(varianti_nome(row["ISTITUTO"]), pd)),
        (
            "match_fuzzy",
            lambda row, pd: _trova_contenimento(
                varianti_nome(row["ISTITUTO"]), _pulisci_comune(row["COMUNE"]), pd
            ),
        ),
        (
            "match_fuzzy",
            lambda row, pd: _trova_difflib(
                varianti_nome(row["ISTITUTO"]), _pulisci_comune(row["COMUNE"]), pd
            ),
        ),
    ]
    for fonte, fn in fasi:
        ancora_da_risolvere = []
        for row in pending:
            cand = fn(row, pool_residuo)
            if cand is not None:
                risultati[row["CODICE"]] = (cand.row, fonte)
                pool_residuo.remove(cand)
            else:
                ancora_da_risolvere.append(row)
        pending = ancora_da_risolvere

    # Diagnostica: stampa i non risolti dall'algoritmo automatico, con i 3
    # candidati piu' vicini (utile per costruire/rivedere MAPPA_MANUALE).
    if pending:
        print(f"\n--- {etichetta}: {len(pending)} presidi non risolti dal matching automatico ---")
        piatto_globale = [(v, c) for c in pool for v in c.varianti]
        for row in pending:
            mv = varianti_nome(row["ISTITUTO"])
            campione = sorted(mv)[0]
            vicini = difflib.get_close_matches(
                campione, [v for v, _ in piatto_globale], n=3, cutoff=0
            )
            righe_vicine = []
            for v in vicini:
                for vv, c in piatto_globale:
                    if vv == v:
                        score = difflib.SequenceMatcher(None, campione, v).ratio()
                        righe_vicine.append(f"{c.row.get('NOME STRUTTURA', '?')} ({score:.2f})")
                        break
            print(f"  {row['CODICE']:>6} {row['ISTITUTO']!r} ({row['COMUNE']}) -> {righe_vicine}")

    # Applica la mappa manuale ai residui.
    manuale_applicati = []
    ancora_assenti = []
    for row in pending:
        codice = row["CODICE"]
        voce = MAPPA_MANUALE.get(codice)
        nome_atteso = voce.get(chiave_manuale) if voce else None
        if nome_atteso is None:
            ancora_assenti.append(row)
            continue
        trovato = None
        for cand in pool_residuo:
            if cand.row.get("NOME STRUTTURA") == nome_atteso:
                trovato = cand
                break
        if trovato is None:
            print(
                f"  ATTENZIONE: mappa manuale per {codice} punta a "
                f"{nome_atteso!r} ma non la trovo (gia' usata? refuso?)"
            )
            ancora_assenti.append(row)
            continue
        risultati[codice] = (trovato.row, "mappa_manuale")
        pool_residuo.remove(trovato)
        manuale_applicati.append(codice)

    if manuale_applicati:
        print(f"{etichetta}: mappa manuale applicata a {len(manuale_applicati)} presidi: {manuale_applicati}")
    if ancora_assenti:
        print(
            f"{etichetta}: {len(ancora_assenti)} presidi restano senza storico "
            f"(legittimamente assenti): "
            f"{[(r['CODICE'], r['ISTITUTO']) for r in ancora_assenti]}"
        )
    righe_non_reclamate = [c.row.get("NOME STRUTTURA") for c in pool_residuo]
    if righe_non_reclamate:
        print(f"{etichetta}: righe storiche non reclamate da nessun presidio: {righe_non_reclamate}")

    return risultati


# ---------------------------------------------------------------------------
# Geocoding via Nominatim, con cache su disco.
# ---------------------------------------------------------------------------
def _carica_cache() -> dict:
    if CACHE_FILE.exists():
        with CACHE_FILE.open(encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _salva_cache(cache: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with CACHE_FILE.open("w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=2)


def _senza_accenti(s: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()


def _query_nominatim(query: str) -> dict | None:
    params = urllib.parse.urlencode(
        {"q": query, "format": "json", "limit": 1, "countrycodes": "it"}
    )
    url = f"{NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            dati = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"  geocoding: errore di rete per {query!r}: {exc}")
        return None
    if not dati:
        return None
    try:
        lat = float(dati[0]["lat"])
        lon = float(dati[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None
    return {"lat": lat, "lon": lon, "display_name": dati[0].get("display_name", "")}


def _comune_coerente(comune: str, display_name: str) -> bool:
    """Il comune cercato deve comparire nel display_name restituito da
    Nominatim: evita di accettare un risultato "nella regione giusta" ma
    nel comune sbagliato (il bbox da solo non lo scoprirebbe).

    ATTENZIONE - limite noto di questo controllo, scoperto verificando a
    mano i display_name di tutti i match automatici: per Roma, Frosinone,
    Viterbo, Rieti e Latina il nome del COMUNE coincide con quello della
    PROVINCIA/citta' metropolitana, che Nominatim include SEMPRE nel
    display_name di qualunque indirizzo di quella provincia (es. "Roma
    Capitale" compare per Fiumicino, Pomezia, Cecchina di Albano Laziale,
    Sgurgola...). Questo controllo quindi non basta da solo a scartare un
    risultato nel comune sbagliato ma nella provincia giusta: ha infatti
    lasciato passare due falsi positivi (San Filippo Neri geolocalizzato a
    Cecchina/Albano Laziale invece che a Roma; F. Spaziani a Sgurgola
    invece che a Frosinone) e altri due dove il nome dell'ospedale ha
    agganciato un posto omonimo nel comune sbagliato (Cristo Re, G.Battista
    Grassi). Questi 4 casi sono stati trovati con un'ispezione manuale dei
    display_name salvati in cache e corretti a mano in COORD_MANUALI: la
    query generica "<nome> <comune>" resta comunque valida per gli altri 32
    presidi auto-geocodificati, dove il display_name e' stato controllato
    e corrisponde davvero al presidio (nome dell'ospedale nel testo, non
    solo comune/provincia)."""
    comune_norm = _pulisci_comune(_senza_accenti(comune))
    display_norm = _pulisci_comune(_senza_accenti(display_name))
    return comune_norm in display_norm


def geocodifica_presidi(master: list[dict[str, str]]) -> dict[str, tuple[float, float]]:
    """Ritorna {codice: (lat, lon)} per tutti i presidi: prima COORD_MANUALI
    per i pochi codici gia' verificati a mano (query generica inaffidabile),
    poi la cache su disco / Nominatim (max 1 richiesta/secondo, con verifica
    di comune e bounding box) per tutti gli altri."""
    cache = _carica_cache()
    coordinate: dict[str, tuple[float, float]] = {}
    nuove_richieste = 0

    for row in master:
        codice = row["CODICE"]
        nome = row["ISTITUTO"]
        comune = row["COMUNE"]

        # Le voci in COORD_MANUALI sono state inserite SOLO dopo aver visto
        # empiricamente che la query generica "<nome> <comune>" o non trova
        # nulla, o (caso di Sant'Andrea, codice 91900) trova con sicurezza un
        # falso positivo con lo stesso nome ma nel posto sbagliato (una via
        # del centro di Roma invece dell'ospedale a Grottarossa) — un caso
        # che il controllo di bbox/comune da solo non intercetta perche' e'
        # comunque dentro Roma. Qui vengono quindi usate come override, non
        # come primo tentativo alla cieca: ogni valore e' stato verificato
        # con una query mirata (indirizzo reale) prima di essere cablato.
        if codice in COORD_MANUALI:
            lat, lon = COORD_MANUALI[codice]
            if in_bbox(lat, lon):
                coordinate[codice] = (lat, lon)
                continue
            print(f"  ATTENZIONE: coordinate manuali per {codice} fuori dal bbox Lazio!")

        varianti_query = [
            f"{nome} {comune}",
            f"Ospedale {nome} {comune}",
            f"{nome} {comune} provincia di Roma" if comune.lower() == "roma" else f"{nome} {comune} Lazio",
        ]

        trovato = None
        for query in varianti_query:
            chiave_cache = f"{query}|it"
            if chiave_cache in cache:
                esito = cache[chiave_cache]
            else:
                # non in cache: interroga Nominatim (max 1 richiesta/sec)
                if nuove_richieste > 0:
                    time.sleep(1.1)
                esito = _query_nominatim(query)
                nuove_richieste += 1
                cache[chiave_cache] = esito
                _salva_cache(cache)

            if not esito:
                continue
            lat, lon = esito["lat"], esito["lon"]
            if not in_bbox(lat, lon):
                print(f"  geocoding: scarto risultato fuori bbox per {query!r}: ({lat}, {lon})")
                continue
            if not _comune_coerente(comune, esito.get("display_name", "")):
                print(
                    f"  geocoding: scarto risultato con comune incoerente per {query!r}: "
                    f"atteso {comune!r}, trovato {esito.get('display_name', '')!r}"
                )
                continue
            trovato = (lat, lon)
            break

        if trovato:
            coordinate[codice] = trovato
        else:
            print(f"  geocoding: NESSUN risultato per {codice} {nome!r} ({comune}) — serve COORD_MANUALI")

    return coordinate


# ---------------------------------------------------------------------------
# Costruzione presidi.json
# ---------------------------------------------------------------------------
def costruisci_storico(row_triage: dict[str, str] | None, row_permanenza: dict[str, str] | None) -> dict:
    storico = {
        "accessi_anno": None,
        "pct_bianchi": None,
        "pct_verdi": None,
        "pct_gialli": None,
        "pct_rossi": None,
        "mediana_permanenza_h": None,
        "mediana_attesa_h": None,
        "pct_permanenza_oltre_48h": None,
    }
    if row_triage is not None:
        accessi = num(row_triage.get("TOTALE ACCESSI"))
        storico["accessi_anno"] = int(accessi) if accessi is not None else None
        storico["pct_bianchi"] = num(row_triage.get("TRIAGE BIANCO (%)"))
        storico["pct_verdi"] = num(row_triage.get("TRIAGE VERDE (%)"))
        storico["pct_gialli"] = num(row_triage.get("TRIAGE GIALLO (%)"))
        storico["pct_rossi"] = num(row_triage.get("TRIAGE ROSSO (%)"))
    if row_permanenza is not None:
        storico["mediana_permanenza_h"] = num(row_permanenza.get("mediana tempo di permanenza"))
        storico["mediana_attesa_h"] = num(row_permanenza.get("mediana tempo di attesa"))
        storico["pct_permanenza_oltre_48h"] = num(row_permanenza.get("permanenza > 48"))
        if storico["accessi_anno"] is None:
            # se manca il triage ma c'e' la permanenza, prendi gli accessi da li'
            # (nota lo spazio finale nel nome colonna, vedi README del task).
            accessi = num(row_permanenza.get("totale accessi "))
            storico["accessi_anno"] = int(accessi) if accessi is not None else None
    return storico


def genera_presidi() -> list[dict]:
    master = carica_master()
    triage_rows = carica_triage()
    permanenza_rows = carica_permanenza()

    pool_triage = costruisci_pool(triage_rows, "NOME STRUTTURA", "COMUNE")
    pool_permanenza = costruisci_pool(permanenza_rows, "NOME STRUTTURA", "COMUNE")

    match_triage = risolvi_storico(master, pool_triage, "triage", "TRIAGE")
    match_permanenza = risolvi_storico(master, pool_permanenza, "permanenza", "PERMANENZA")

    print("\nGeocoding dei 49 presidi (Nominatim, cache su disco, max 1 richiesta/secondo)...")
    coordinate = geocodifica_presidi(master)

    presidi = []
    for row in master:
        codice = row["CODICE"]
        row_tri, fonte_tri = match_triage.get(codice, (None, "assente"))
        row_per, fonte_per = match_permanenza.get(codice, (None, "assente"))

        # fonte_storico complessiva: priorita' esatto > fuzzy > manuale > assente,
        # prendendo la fonte "migliore" fra le due (di solito coincidono).
        priorita = {"match_esatto": 0, "match_fuzzy": 1, "mappa_manuale": 2, "assente": 3}
        fonte = min([fonte_tri, fonte_per], key=lambda f: priorita[f])
        if row_tri is None and row_per is None:
            fonte = "assente"

        lat_lon = coordinate.get(codice)

        presidi.append(
            {
                "codice": codice,
                "nome": row["ISTITUTO"],
                "tipo": row["TIPO"],
                "comune": row["COMUNE"],
                "asl": row["ASL"],
                "lat": lat_lon[0] if lat_lon else None,
                "lon": lat_lon[1] if lat_lon else None,
                "storico": costruisci_storico(row_tri, row_per),
                "fonte_storico": fonte,
            }
        )

    return presidi


# ---------------------------------------------------------------------------
# Costruzione territorio.json
# ---------------------------------------------------------------------------
def genera_territorio() -> dict:
    farmacie_out = []
    scartate_farmacie = 0
    righe = _leggi_csv(RAW / "farmacie_regione_lazio.csv", delimiter=";")
    for row in righe:
        if row.get("DATAFINEVALIDITA", "").strip() != "-":
            continue  # farmacia chiusa/non piu' valida
        lat = num(row.get("LATITUDINE"))
        lon = num(row.get("LONGITUDINE"))
        if lat is None or lon is None or not in_bbox(lat, lon):
            scartate_farmacie += 1
            continue
        # Il CAP nel CSV sorgente perde gli zeri iniziali (es. "153" invece
        # di "00153"): lo ripristiniamo a 5 cifre, formato standard italiano.
        cap = row.get("CAP", "").strip()
        if cap.isdigit():
            cap = cap.zfill(5)
        farmacie_out.append(
            {
                "id": row.get("CODICEIDENTIFICATIVOFARMACIA", "").strip(),
                "nome": row.get("DESCRIZIONEFARMACIA", "").strip(),
                "indirizzo": row.get("INDIRIZZO", "").strip(),
                "comune": row.get("DESCRIZIONECOMUNE", "").strip(),
                "cap": cap,
                "lat": lat,
                "lon": lon,
            }
        )

    strutture_out = []
    scartate_strutture = 0
    righe = _leggi_csv(RAW / "strutture_sanitarie_private_accreditate.csv", delimiter=",")
    for row in righe:
        lat = num(row.get("Latitude"))
        lon = num(row.get("Longitude"))
        if lat is None or lon is None or not in_bbox(lat, lon):
            scartate_strutture += 1
            continue
        strutture_out.append(
            {
                "id": row.get("ID_PR", "").strip(),
                "nome": row.get("RAGIONE SOCIALE", "").strip(),
                "asl": row.get("ASL", "").strip(),
                "indirizzo": row.get("INDIRIZZO", "").strip(),
                "comune": row.get("COMUNE", "").strip(),
                "lat": lat,
                "lon": lon,
                "provvedimento": row.get("TIPO DI PROVVEDIMENTO", "").strip(),
            }
        )

    print(
        f"\nfarmacie: {len(farmacie_out)} tenute, {scartate_farmacie} scartate "
        "(chiuse o coordinate invalide/fuori bbox)"
    )
    print(
        f"strutture accreditate: {len(strutture_out)} tenute, {scartate_strutture} scartate "
        "(coordinate invalide/fuori bbox)"
    )

    return {"farmacie": farmacie_out, "strutture_accreditate": strutture_out}


# ---------------------------------------------------------------------------
# Generazione
# ---------------------------------------------------------------------------
def genera() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)

    presidi = genera_presidi()
    assert len(presidi) == 49, f"attesi 49 presidi in output, trovati {len(presidi)}"
    with PRESIDI_JSON.open("w", encoding="utf-8") as fh:
        json.dump(presidi, fh, ensure_ascii=False, indent=2)
    print(f"\nScritto {PRESIDI_JSON} ({len(presidi)} presidi)")

    territorio = genera_territorio()
    with TERRITORIO_JSON.open("w", encoding="utf-8") as fh:
        json.dump(territorio, fh, ensure_ascii=False, indent=2)
    print(
        f"Scritto {TERRITORIO_JSON} "
        f"({len(territorio['farmacie'])} farmacie, "
        f"{len(territorio['strutture_accreditate'])} strutture accreditate)"
    )


# ---------------------------------------------------------------------------
# --verifica: rilegge i JSON prodotti e stampa un report di sanita' dei dati.
# ---------------------------------------------------------------------------
def verifica() -> None:
    if not PRESIDI_JSON.exists() or not TERRITORIO_JSON.exists():
        print("ERRORE: i JSON derivati non esistono ancora. Esegui prima senza --verifica.")
        sys.exit(1)

    with PRESIDI_JSON.open(encoding="utf-8") as fh:
        presidi = json.load(fh)
    with TERRITORIO_JSON.open(encoding="utf-8") as fh:
        territorio = json.load(fh)

    print("=" * 70)
    print("REPORT DI VERIFICA")
    print("=" * 70)

    print(f"\npresidi.json: {len(presidi)} presidi")

    senza_coord = [p for p in presidi if p["lat"] is None or p["lon"] is None]
    print(f"  senza lat/lon: {len(senza_coord)}")
    for p in senza_coord:
        print(f"    - {p['codice']} {p['nome']}")

    fuori_bbox = [
        p
        for p in presidi
        if p["lat"] is not None and p["lon"] is not None and not in_bbox(p["lat"], p["lon"])
    ]
    print(f"  con coordinate fuori dal bbox Lazio: {len(fuori_bbox)}")
    for p in fuori_bbox:
        print(f"    - {p['codice']} {p['nome']} ({p['lat']}, {p['lon']})")

    senza_storico = [p for p in presidi if p["fonte_storico"] == "assente"]
    print(f"  senza storico (fonte_storico == 'assente'): {len(senza_storico)}")

    from collections import Counter

    distribuzione = Counter(p["fonte_storico"] for p in presidi)
    print(f"  distribuzione fonte_storico: {dict(distribuzione)}")

    print("\nControllo somme percentuali di triage (attese fra 98 e 102):")
    violazioni_somma = []
    for p in presidi:
        s = p["storico"]
        pcts = [s["pct_bianchi"], s["pct_verdi"], s["pct_gialli"], s["pct_rossi"]]
        if any(v is None for v in pcts):
            continue
        somma = sum(pcts)
        if not (98 <= somma <= 102):
            violazioni_somma.append((p["codice"], p["nome"], somma))
    if violazioni_somma:
        print(f"  VIOLAZIONI: {len(violazioni_somma)}")
        for codice, nome, somma in violazioni_somma:
            print(f"    - {codice} {nome}: somma = {somma:.2f}")
    else:
        print("  nessuna violazione")

    print("\nControllo valori assurdi:")
    assurdi = []
    for p in presidi:
        s = p["storico"]
        for campo in ("pct_bianchi", "pct_verdi", "pct_gialli", "pct_rossi", "pct_permanenza_oltre_48h"):
            v = s.get(campo)
            if v is not None and not (0 <= v <= 100):
                assurdi.append(f"{p['codice']} {p['nome']}: {campo} = {v} (fuori [0,100])")
        mp = s.get("mediana_permanenza_h")
        if mp is not None and mp > 100:
            assurdi.append(f"{p['codice']} {p['nome']}: mediana_permanenza_h = {mp} (> 100)")
        if p["lat"] is not None and p["lon"] is not None and not in_bbox(p["lat"], p["lon"]):
            assurdi.append(f"{p['codice']} {p['nome']}: coordinate fuori dal Lazio")
    if assurdi:
        print(f"  VIOLAZIONI: {len(assurdi)}")
        for a in assurdi:
            print(f"    - {a}")
    else:
        print("  nessuna violazione")

    print(f"\nterritorio.json:")
    print(f"  farmacie: {len(territorio['farmacie'])}")
    print(f"  strutture_accreditate: {len(territorio['strutture_accreditate'])}")

    farm_bad = [
        f
        for f in territorio["farmacie"]
        if f["lat"] is None or f["lon"] is None or not in_bbox(f["lat"], f["lon"])
    ]
    strut_bad = [
        s
        for s in territorio["strutture_accreditate"]
        if s["lat"] is None or s["lon"] is None or not in_bbox(s["lat"], s["lon"])
    ]
    print(f"  farmacie con coordinate invalide/fuori bbox: {len(farm_bad)}")
    print(f"  strutture con coordinate invalide/fuori bbox: {len(strut_bad)}")

    print("\n" + "=" * 70)
    problemi = (
        len(senza_coord)
        + len(fuori_bbox)
        + len(violazioni_somma)
        + len(assurdi)
        + len(farm_bad)
        + len(strut_bad)
    )
    if problemi == 0:
        print("VERIFICA OK: nessuna violazione rilevata.")
    else:
        print(f"VERIFICA: {problemi} violazioni totali rilevate (vedi sopra).")
    print("=" * 70)


def main() -> None:
    if "--verifica" in sys.argv:
        verifica()
    else:
        genera()


if __name__ == "__main__":
    main()
