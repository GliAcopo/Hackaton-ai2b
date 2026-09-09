"""Dalla parola chiave alla logica dell'app.

Questo è il file che decide se prendi 10 o 4 su "Aderenza al tema".
La parola sorteggiata non deve restare un titolo sulla slide: deve
cambiare *quali comuni l'app tira fuori* e *cosa l'IA dice di loro*.

Struttura:
    parola chiave -> Lens (come leggo i dati)
                  -> ranking dei comuni secondo quella lente
                  -> l'LLM scrive la scheda, vincolata a uno schema
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from dataload import Comune, load_comuni
from llm import LLMError, complete_json

Score = Callable[[Comune], float | None]


@dataclass
class Lens:
    """Una lente = come una parola astratta diventa un ordinamento sui dati."""

    nome: str
    descrizione: str
    score: Score
    domanda: str


def _equilibrio(c: Comune) -> float | None:
    """Alta pressione turistica su poca popolazione = squilibrio."""
    if c.alloggi_per_1000_ab is None or c.crescita_pct is None:
        return None
    return c.alloggi_per_1000_ab * (1 + c.crescita_pct / 100)


# NOTE: Mettere i nomi delle chiavi in small caps
LENSES: dict[str, Lens] = {
    "equilibrio": Lens(
        nome="Equilibrio",
        descrizione=(
            "Comuni dove gli alloggi turistici crescono molto più in fretta "
            "dei residenti: il punto di rottura fra economia turistica e "
            "tenuta della comunità locale."
        ),
        score=_equilibrio,
        domanda=(
            "Questo comune rischia di superare il punto di equilibrio fra "
            "turismo e residenti. Proponi UNA misura concreta e locale."
        ),
    ),
    "infelicità": Lens(
        nome="Infelicità",
        descrizione=(
            "Comune in cui ci sono molti più alloggi che turisti"
        ),
        score=_equilibrio,
        domanda=(
            "Q"
        ),
    ),
}


def keyword_lens(keyword: str) -> Lens:
    """Restituisce la lente da usare per la parola chiave sorteggiata.

    TODO(human)
    """

    # Devo mettere tutto in lower caps perché tutte le lenses sono identificate con stringhe in lower caps
    keyword = keyword.lower()

    if keyword in LENSES:
        return(LENSES[keyword])
    else:
        pass

SCHEMA = {
    "type": "object",
    "properties": {
        "titolo": {"type": "string"},
        "diagnosi": {"type": "string"},
        "azione": {"type": "string"},
        "urgenza": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "required": ["titolo", "diagnosi", "azione", "urgenza"],
}

# System è il system prompt, un prompt ad alta priorità che definisce lo spazio di stato del modello
SYSTEM = (
    "Sei un analista di politiche territoriali del Lazio. Rispondi in italiano, "
    "conciso e concreto. Non inventare numeri: usa solo quelli forniti."
)


def scheda(c: Comune, keyword: str, lens: Lens) -> dict:
    """Fa scrivere all'LLM la scheda di un comune, vincolata allo schema."""
    prompt = (
        f"PAROLA CHIAVE DELLA GIORNATA: {keyword}\n"
        f"LENTE DI LETTURA: {lens.descrizione}\n\n"
        f"COMUNE: {c.nome} (provincia di {c.provincia})\n"
        f"Popolazione residente: {c.popolazione}\n"
        f"Superficie: {c.superficie_kmq} kmq | altitudine {c.altitudine_m} m"
        f"{' | comune montano' if c.montano else ''}\n"
        f"Alloggi privati locati a fini turistici per anno: {dict(sorted(c.alloggi.items()))}\n"
        f"Alloggi ogni 1000 abitanti: {c.alloggi_per_1000_ab}\n"
        f"Crescita sul periodo: {c.crescita_pct}%\n\n"
        f"{lens.domanda}\n"
        f"'urgenza' da 1 (situazione sotto controllo) a 5 (critica)."
    )
    try:
        out = complete_json(prompt, SCHEMA, system=SYSTEM)
    except LLMError as exc:
        # Regola del playbook: mai un prompt sulla strada critica senza
        # fallback. La demo continua anche se il modello non risponde.
        out = {
            "titolo": f"{c.nome}: analisi non disponibile",
            "diagnosi": f"Il modello non ha risposto ({exc}). I dati restano validi.",
            "azione": "Riprova, oppure mostra la scheda in cache.",
            "urgenza": 1,
        }
    out["comune"] = c.nome
    return out


def classifica(keyword: str, n: int = 5) -> tuple[Lens, list[Comune]]:
    lens = keyword_lens(keyword)
    if lens is None:
        raise NotImplementedError(
            "keyword_lens() non è ancora implementata: vedi il TODO(human) "
            "in src/insight.py"
        )

    scored: list[tuple[Comune, float]] = []

    for comune in load_comuni():
        score = lens.score(comune)
        if score is not None:
            scored.append((comune, score))

    scored.sort(key=lambda item: item[1], reverse=True)

    return lens, [comune for comune, _ in scored[:n]]


if __name__ == "__main__":
    import sys

    kw = sys.argv[1] if len(sys.argv) > 1 else "Equilibrio"
    lens, top = classifica(kw, 3)
    print(f"lente: {lens.nome} — {lens.descrizione}\n")
    for c in top:
        print(scheda(c, kw, lens))
