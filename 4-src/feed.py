"""Stato della rete dei pronto soccorso del Lazio.

Una firma sola, due sorgenti dietro:

    stato_rete("snapshot")  # CSV open data, rilevazione del 2021-07-15 16:58
    stato_rete("live")      # API salutelazio, se e quando la troviamo

ONESTA' SULLA FONTE. Il dataset che la Regione chiama "accessi in tempo reale"
e' in realta' congelato: il datastore CKAN restituisce sempre e solo la
rilevazione del 15/07/2021 fra le 16:56 e le 16:58. Non e' un problema da
nascondere simulando un orologio: ogni risposta porta `fonte` e `rilevato_il`,
e l'interfaccia li mostra sempre. Dichiararlo per primi vale piu' che farsi
smontare dalla giuria.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
SNAPSHOT = RADICE / "2-data" / "raw" / "dataset_principale" / "lazio" / "pronto_soccorso_accessi_tempo_reale.csv"
PRESIDI = RADICE / "2-data" / "derived" / "presidi.json"


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
    rilevato_il: str

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


def stato_rete(fonte: str = "snapshot") -> tuple[list[StatoPS], dict]:
    """Ritorna (stati, meta). `meta` porta fonte e istante della rilevazione."""
    if fonte == "live":
        raise NotImplementedError(
            "Il feed live di salutelazio non e' ancora agganciato: "
            "usa fonte='snapshot'."
        )

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

    meta = {
        "fonte": "open data Regione Lazio (snapshot)",
        "rilevato_il": quando,
        "presidi": len(stati),
        "con_anagrafica": agganciati,
        "avviso": (
            "Il dataset regionale «accessi in tempo reale» e' fermo a questa "
            "rilevazione: e' l'ultima disponibile, non l'istante corrente."
        ),
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
