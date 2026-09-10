"""Costruisce l'inventario delle grandi apparecchiature diagnostiche per
struttura, abbinando quando possibile ciascuna struttura ministeriale a uno
dei nostri 49 presidi di pronto soccorso.

    python3 4-src/costruisci_apparecchiature.py            # ricostruisce e scrive
    python3 4-src/costruisci_apparecchiature.py --verifica  # non scrive, solo controlla

PERCHE' L'ABBINAMENTO E' GEOGRAFICO *E* CONFERMATO SUL NOME. Il dataset del
Ministero non condivide nessun codice con i nostri presidi: l'unico terreno
comune sono le coordinate della struttura. Ma la sola distanza non basta a
essere certi di aver trovato lo stesso posto - un ambulatorio e un pronto
soccorso possono stare a duecento metri l'uno dall'altro senza essere la
stessa cosa, e un azzardo qui produrrebbe una dotazione di apparecchiature
attribuita al pronto soccorso sbagliato. Per questo l'abbinamento a un
presidio scatta solo quando VALGONO INSIEME due condizioni indipendenti:

  1. la struttura ministeriale e' a 1 km o meno dal presidio (il piu' vicino,
     se piu' d'uno rientra nel raggio);
  2. il nome della struttura e quello del presidio condividono almeno una
     parola significativa (dopo aver scartato il rumore: "ospedale",
     "pronto soccorso", "san", articoli, eccetera).

Se la distanza e' giusta ma i nomi non si toccano, l'abbinamento resta
INCERTO e non viene usato: va fra i non risolti, con il motivo. Nessun
abbinamento e' mai forzato per somiglianza approssimata - in dubbio, non si
abbina, e la struttura resta con dotazione propria ma senza presidio.

PERCHE' I CODICI RESTANO STRINGHE. "codice_struttura" e
"codice_azienda_sanitaria_asl" sono codici ministeriali con zeri iniziali
(es. "010212"): letti come int diventerebbero "10212", un codice diverso e
inesistente nell'anagrafe. Restano stringhe dalla lettura del CSV fino alla
scrittura del JSON, senza mai passare per int().

UNA STRUTTURA NON E' UN CODICE_STRUTTURA DA SOLO. "codice_struttura" si
ripete su aziende sanitarie diverse per indicare strutture completamente
diverse (es. "001500" e' sia "ARS MEDICA S.P.A" per l'azienda 202 sia
"AMBULATORIO CENTRO DELLA GIOIA" per l'azienda 201: due indirizzi, due
coppie di coordinate). La chiave che identifica davvero una struttura e' la
coppia (codice_azienda_sanitaria_asl, codice_struttura): raggruppando su
questa coppia si ottengono le 340 strutture dichiarate in provenienza.json,
raggruppando sul solo codice_struttura se ne otterrebbe una in meno.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
DIR_APPARECCHIATURE = RADICE / "2-data" / "raw" / "dataset_integrativo" / "nazionale" / "apparecchiature"
CSV_APPARECCHIATURE = DIR_APPARECCHIATURE / "apparecchiature_lazio_20260907.csv"
PROVENIENZA = DIR_APPARECCHIATURE / "provenienza.json"
PRESIDI = RADICE / "2-data" / "derived" / "presidi.json"
USCITA = RADICE / "2-data" / "derived" / "apparecchiature.json"

# Oltre questa distanza una struttura non e' nemmeno candidata: la maggior
# parte delle 340 strutture del CSV non e' affatto un pronto soccorso, quindi
# "nessun presidio nel raggio" e' l'esito normale, non un errore.
DISTANZA_MAX_KM = 1.0

# Parole troppo comuni nei nomi di ospedali italiani per essere indizio di
# identita': condividerle non prova che due nomi indichino lo stesso posto.
RUMORE = {
    "ospedale", "presidio", "po", "azienda", "asl", "casa", "cura", "clinica",
    "istituto", "universitario", "policlinico", "pronto", "soccorso", "di",
    "del", "della", "dei", "delle", "san", "santa", "s", "ss", "sant",
}

# "- 01021 - Acquapendente (VT)": cattura il comune fra il CAP e la sigla
# di provincia, cosi' come compare in indirizzo_struttura.
COMUNE_IN_INDIRIZZO = re.compile(r"-\s*\d{5}\s*-\s*(.+?)\s*\([A-Z]{2}\)\s*$")

LIMITI = [
    "Inventario delle grandi apparecchiature: una riga è una combinazione censita di struttura e dotazione, non necessariamente una singola macchina.",
    "num_app_disponibili non indica slot prenotabili, personale in turno o disponibilità in tempo reale.",
    "Assenza dal dataset non prova assenza della dotazione.",
    "L'abbinamento a un pronto soccorso è geografico e confermato sul nome: le associazioni non risolte sono elencate e non influenzano alcun consiglio.",
]


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza fra due punti sulla Terra (formula dell'emisenoverso)."""
    r = math.radians
    return 2 * 6371.0 * math.asin(math.sqrt(
        math.sin(r(lat2 - lat1) / 2) ** 2
        + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2))


def parole_significative(testo: str) -> set[str]:
    """Minuscole, via accenti e punteggiatura, senza le parole di rumore.

    Scarta anche i token di una sola lettera ("I" di "Umberto I", iniziali
    puntate come "U."): da soli non sono un indizio di identita' e senza
    questo filtro producono abbinamenti per puro caso, come "C.I.D.
    LABORATORI" abbinato a "Pol. Univ. Umberto I" solo perche' entrambi
    contengono, per motivi diversi, il token "i".
    """
    piatto = unicodedata.normalize("NFKD", testo.lower()).encode("ascii", "ignore").decode()
    piatto = re.sub(r"[^a-z0-9]+", " ", piatto)
    return {parola for parola in piatto.split() if len(parola) >= 2} - RUMORE


def numero_o_nessuno(testo: str) -> int | None:
    testo = (testo or "").strip()
    if not testo:
        return None
    try:
        return int(testo)
    except ValueError:
        return None


def coordinata_o_nessuna(testo: str) -> float | None:
    testo = (testo or "").strip()
    if not testo:
        return None
    try:
        return float(testo)
    except ValueError:
        return None


def comune_da_indirizzo(indirizzo: str) -> str | None:
    m = COMUNE_IN_INDIRIZZO.search(indirizzo or "")
    return m.group(1).strip() if m else None


def leggi_righe(percorso_csv: Path) -> list[dict]:
    """Legge il CSV preservando ogni codice come stringa.

    I nomi delle colonne vengono spogliati degli spazi (il CSV ha
    "azienda_sanitaria_ASL " con uno spazio finale) cosi' il resto dello
    script puo' usare nomi puliti senza doverci pensare ogni volta.
    """
    with percorso_csv.open(encoding="utf-8", newline="") as f:
        lettore = csv.DictReader(f, delimiter=";")
        righe = []
        for grezza in lettore:
            riga = {(chiave or "").strip(): (valore or "").strip()
                    for chiave, valore in grezza.items()}
            righe.append(riga)
    return righe


def raggruppa_per_struttura(righe: list[dict]) -> list[tuple[tuple[str, str], list[dict]]]:
    """Raggruppa le righe per (codice_azienda_sanitaria_asl, codice_struttura).

    Vedi il docstring del modulo: il solo codice_struttura non basta, si
    ripete su aziende diverse per strutture diverse.
    """
    gruppi: dict[tuple[str, str], list[dict]] = {}
    ordine: list[tuple[str, str]] = []
    for riga in righe:
        chiave = (riga["codice_azienda_sanitaria_asl"], riga["codice_struttura"])
        if chiave not in gruppi:
            gruppi[chiave] = []
            ordine.append(chiave)
        gruppi[chiave].append(riga)
    return [(chiave, gruppi[chiave]) for chiave in ordine]


def cerca_presidio(lat: float, lon: float, denominazione: str, presidi: list[dict]):
    """Cerca il presidio piu' vicino entro DISTANZA_MAX_KM e ne verifica il nome.

    Ritorna una tupla (esito, distanza, presidio) dove esito e' uno fra:
      "confermato" - distanza nel raggio e almeno una parola in comune;
      "incerto"    - distanza nel raggio ma nessuna parola in comune;
      None         - nessun presidio nel raggio (non e' un errore: la
                     struttura semplicemente non e' un pronto soccorso).
    """
    candidati = []
    for presidio in presidi:
        d = km(lat, lon, presidio["lat"], presidio["lon"])
        if d <= DISTANZA_MAX_KM:
            candidati.append((d, presidio))
    if not candidati:
        return None, None, None

    candidati.sort(key=lambda coppia: coppia[0])
    distanza, presidio = candidati[0]
    comune = parole_significative(denominazione) & parole_significative(presidio["nome"])
    esito = "confermato" if comune else "incerto"
    return esito, distanza, presidio


def costruisci(righe: list[dict], presidi: list[dict]):
    """Costruisce le strutture con dotazione e i casi non risolti."""
    strutture = []
    non_risolti = []

    for (codice_azienda, codice_struttura), righe_struttura in raggruppa_per_struttura(righe):
        prima = righe_struttura[0]
        denominazione = prima["denominazione_struttura"]
        lat = coordinata_o_nessuna(prima["latitudine"])
        lon = coordinata_o_nessuna(prima["longitudine"])

        dotazione = [{
            "tipo": r["tipo_apparecchiatura"],
            "cnd": r["cod_classificazione_cnd"],
            "descrizione_cnd": r["descrizione_cnd"],
            "num": numero_o_nessuno(r["num_apparecchiature"]),
            "num_disponibili": numero_o_nessuno(r["num_app_disponibili"]),
            "caratteristiche": r["caratteristiche"],
        } for r in righe_struttura]

        struttura = {
            "codice_struttura": codice_struttura,
            "denominazione": denominazione,
            "indirizzo": prima["indirizzo_struttura"],
            "comune": comune_da_indirizzo(prima["indirizzo_struttura"]),
            "codice_azienda": codice_azienda,
            "azienda": prima["azienda_sanitaria_ASL"],
            "lat": lat,
            "lon": lon,
            "codice_presidio": None,
            "nome_presidio": None,
            "km_dal_presidio": None,
            "abbinamento": "assente",
            "dotazione": dotazione,
        }

        if lat is None or lon is None:
            non_risolti.append({
                "codice_struttura": codice_struttura,
                "denominazione": denominazione,
                "motivo": "coordinate assenti",
            })
            strutture.append(struttura)
            continue

        esito, distanza, presidio = cerca_presidio(lat, lon, denominazione, presidi)
        if esito == "confermato":
            struttura["codice_presidio"] = presidio["codice"]
            struttura["nome_presidio"] = presidio["nome"]
            struttura["km_dal_presidio"] = round(distanza, 3)
            struttura["abbinamento"] = "confermato"
        elif esito == "incerto":
            non_risolti.append({
                "codice_struttura": codice_struttura,
                "denominazione": denominazione,
                "motivo": "coordinate vicine ma nomi incompatibili",
            })
        # esito None: nessun presidio nel raggio, struttura resta "assente"
        # senza finire fra i non risolti (non e' un'ambiguita', e' la norma).

        strutture.append(struttura)

    return strutture, non_risolti


def riepiloga(righe: list[dict], strutture: list[dict], non_risolti: list[dict]) -> dict:
    tipi: dict[str, int] = {}
    for r in righe:
        tipo = r["tipo_apparecchiatura"]
        tipi[tipo] = tipi.get(tipo, 0) + 1
    abbinate = sum(1 for s in strutture if s["abbinamento"] == "confermato")
    return {
        "righe_lette": len(righe),
        "strutture": len(strutture),
        "abbinate_a_un_presidio": abbinate,
        "non_risolte": len(non_risolti),
        "tipi_apparecchiatura": dict(sorted(tipi.items())),
    }


def main() -> int:
    analizzatore = argparse.ArgumentParser(description=__doc__)
    analizzatore.add_argument("--verifica", action="store_true",
                               help="non riscrive il file, stampa solo il riepilogo e i non risolti")
    argomenti = analizzatore.parse_args()

    righe = leggi_righe(CSV_APPARECCHIATURE)
    presidi = json.loads(PRESIDI.read_text(encoding="utf-8"))
    provenienza = json.loads(PROVENIENZA.read_text(encoding="utf-8"))

    strutture, non_risolti = costruisci(righe, presidi)
    riepilogo = riepiloga(righe, strutture, non_risolti)

    print(f"righe lette: {riepilogo['righe_lette']}   strutture: {riepilogo['strutture']}   "
          f"abbinate a un presidio: {riepilogo['abbinate_a_un_presidio']}   "
          f"non risolte: {riepilogo['non_risolte']}")
    print("tipi apparecchiatura:", riepilogo["tipi_apparecchiatura"])

    if non_risolti:
        print("\nNON RISOLTI:")
        for voce in non_risolti:
            print(f"   {voce['codice_struttura']:>8}  {voce['denominazione'][:45]:45}  {voce['motivo']}")

    if argomenti.verifica:
        return 0

    documento = {
        "provenienza": provenienza,
        "costruito_il": datetime.now().astimezone().isoformat(timespec="seconds"),
        "strutture": strutture,
        "non_risolti": non_risolti,
        "riepilogo": riepilogo,
        "limiti": LIMITI,
    }
    USCITA.write_text(json.dumps(documento, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nscritto {USCITA.relative_to(RADICE)} ({len(strutture)} strutture)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
