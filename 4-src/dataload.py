"""Caricamento e pulizia degli open data della Regione Lazio.

Tutto stdlib: alle 10 del mattino non vuoi litigare con le dipendenze.
Ogni funzione qui esiste per una trappola reale del dataset, documentata
in docs/TRACCIA.md.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, asdict
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

# I file alloggi hanno l'anno nel NOME del file, non (attendibilmente)
# nell'header: l'header di alloggi_2025Q3.csv dice "30 APRILE 2025"
# mentre il resource CKAN si chiama "al 31 Dicembre 2025". Ci fidiamo
# del nome file, che è l'unica cosa coerente.
# Assunzione: un solo file per anno. Se ne scarichi due dello stesso anno
# (due quadrimestri) il secondo sovrascrive il primo senza avvisare:
# rinominali alloggi_2025Q1/Q2 e cambia la chiave in (anno, quadrimestre).
ALLOGGI_GLOB = "alloggi_*.csv"
RESIDENTI = RAW / "residenti_lazio.csv"


def num(value: str) -> float | None:
    """`'1287,3586'` -> 1287.3586. Stringa vuota o sporca -> None."""
    value = (value or "").strip().replace(".", "").replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def norm(name: str) -> str:
    """Chiave di join robusta fra due dataset scritti da uffici diversi."""
    name = name.strip().lower()
    name = name.replace("'", "'")
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def _read_semicolon(path: Path, encoding: str) -> list[dict[str, str]]:
    with path.open(encoding=encoding, newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        # l'header di alloggi_*.csv comincia con uno spazio: " COMUNE"
        reader.fieldnames = [(f or "").strip() for f in reader.fieldnames or []]
        return [{k: (v or "").strip() for k, v in row.items() if k} for row in reader]


def load_alloggi() -> dict[str, dict[int, int]]:
    """{chiave_comune: {anno: numero_alloggi}}"""
    out: dict[str, dict[int, int]] = {}
    for path in sorted(RAW.glob(ALLOGGI_GLOB)):
        year = int(re.search(r"(\d{4})", path.name).group(1))
        for row in _read_semicolon(path, "utf-8"):
            comune = row.get("COMUNE", "")
            # la colonna del conteggio cambia nome in ogni file:
            # prendiamo l'unica che non è COMUNE/PROVINCIA
            count = next(
                (v for k, v in row.items() if k not in ("COMUNE", "PROVINCIA")), ""
            )
            if not comune:
                continue
            out.setdefault(norm(comune), {})[year] = int(num(count) or 0)
    return out


@dataclass
class Comune:
    nome: str
    provincia: str
    popolazione: int | None
    superficie_kmq: float | None
    altitudine_m: float | None
    montano: bool
    alloggi: dict[int, int]

    @property
    def alloggi_ultimo(self) -> int | None:
        return self.alloggi[max(self.alloggi)] if self.alloggi else None

    @property
    def alloggi_per_1000_ab(self) -> float | None:
        n, pop = self.alloggi_ultimo, self.popolazione
        if n is None or not pop:
            return None
        return round(n * 1000 / pop, 2)

    @property
    def crescita_pct(self) -> float | None:
        """Variazione % fra il primo e l'ultimo anno disponibile."""
        if len(self.alloggi) < 2:
            return None
        first, last = min(self.alloggi), max(self.alloggi)
        base = self.alloggi[first]
        if base == 0:
            return None
        return round((self.alloggi[last] - base) * 100 / base, 1)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["alloggi"] = {str(k): v for k, v in sorted(self.alloggi.items())}
        d["alloggi_ultimo"] = self.alloggi_ultimo
        d["alloggi_per_1000_ab"] = self.alloggi_per_1000_ab
        d["crescita_pct"] = self.crescita_pct
        return d


def load_comuni() -> list[Comune]:
    alloggi = load_alloggi()
    comuni: list[Comune] = []
    # latin-1, non UTF-8: "Densità" arriva come byte 0xE0
    for row in _read_semicolon(RESIDENTI, "latin-1"):
        nome = row.get("Descrizione comune", "")
        if not nome:
            continue
        pop = num(row.get("Popolazione residente al 1/1/2018", ""))
        comuni.append(
            Comune(
                nome=nome,
                provincia=row.get("Provincia", ""),
                popolazione=int(pop) if pop else None,
                superficie_kmq=num(row.get("Superficie territoriale (kmq)", "")),
                altitudine_m=num(row.get("Altitudine del centro (metri)", "")),
                # T = totalmente montano, P = parzialmente montano (Roma è "P").
                montano=row.get("Comune Montano", "").upper().startswith(("T", "P")),
                alloggi=alloggi.get(norm(nome), {}),
            )
        )
    return comuni


if __name__ == "__main__":
    comuni = load_comuni()
    senza = [c.nome for c in comuni if not c.alloggi]
    print(f"comuni: {len(comuni)}  senza dato alloggi: {len(senza)} -> {senza[:5]}")
    top = sorted(
        (c for c in comuni if c.alloggi_per_1000_ab),
        key=lambda c: c.alloggi_per_1000_ab,
        reverse=True,
    )[:8]
    for c in top:
        print(
            f"{c.nome:28} {c.provincia}  pop {c.popolazione:>7}  "
            f"alloggi {c.alloggi_ultimo:>5}  /1000ab {c.alloggi_per_1000_ab:>7}  "
            f"crescita {c.crescita_pct}%"
        )
