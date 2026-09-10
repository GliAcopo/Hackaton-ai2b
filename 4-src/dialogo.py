"""Il dialogo adattivo: quali domande valgono la pena di essere fatte.

L'IDEA. Un questionario che chiede tutto a tutti e' inutile due volte: fa
perdere tempo a chi ha una situazione semplice e non aggiunge niente a chi ne
ha una complicata. Qui si fa il contrario: a ogni giro si sceglie UNA domanda,
e solo se la sua risposta puo' davvero cambiare il percorso.

IL CONFINE FRA REGOLE E MODELLO, che e' il punto delicato di tutto il file.

  Le REGOLE decidono. Il modello propone.

  In Python stanno: quali domande sono applicabili, quali sono obbligatorie,
  quando il percorso si interrompe perche' serve un contatto sanitario, e
  quali conclusioni cadono quando una risposta viene corretta.

  Al modello resta una cosa sola: fra le domande gia' dichiarate applicabili
  dalle regole, quale conviene fare adesso. Sceglie un ID da un elenco
  chiuso, e motiva. Se propone un ID che non e' in quell'elenco - o inventa
  una domanda che nel catalogo non esiste - la proposta viene SCARTATA e si
  torna all'ordine di priorita' del catalogo. Lo scarto viene dichiarato in
  `scarto_modello`, non nascosto: se il modello sbaglia spesso, si deve vedere.

  Il modello non puo' in nessun caso introdurre una regola clinica: non decide
  se il percorso si interrompe, non attribuisce priorita', non aggiunge
  domande. Quelle sono decisioni che stanno nel catalogo, versionato e
  revisionabile da chi ha titolo per farlo.

NIENTE STATO SUL SERVER. Il client rimanda ogni volta l'elenco completo delle
risposte. Cosi' non esistono sessioni da conservare, e i sintomi non restano
da nessuna parte dopo la risposta HTTP.

QUANDO CI SI FERMA. Due condizioni, entrambe esplicite:
  - `sufficiente`: tutte le domande obbligatorie applicabili hanno una
    risposta (anche "non so": e' una risposta, e ha conseguenze).
  - `non_determinabile`: restano informazioni indispensabili che la persona
    non sa dare. Si dichiara, invece di forzare una conclusione.
Non esiste un terzo esito in cui si continua a chiedere all'infinito.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
CATALOGO = RADICE / "2-data" / "catalogo" / "domande.json"

NON_SO = "non_so"

# Oltre questo numero di domande ci si ferma comunque e si lavora con quello
# che si ha. Un orientamento che richiede quindici domande ha gia' fallito.
MASSIMO_DOMANDE = 7


@lru_cache(maxsize=1)
def catalogo() -> dict:
    return json.loads(CATALOGO.read_text(encoding="utf-8"))


def _domande() -> list[dict]:
    return catalogo().get("domande", [])


def per_id(id_domanda: str) -> dict | None:
    return next((d for d in _domande() if d["id"] == id_domanda), None)


def intestazione() -> dict:
    c = catalogo()
    return {
        "versione": c.get("versione"),
        "aggiornato_il": c.get("aggiornato_il"),
        "domande": len(c.get("domande", [])),
        "avvertenza": c.get("avvertenza_generale"),
    }


# ---------------------------------------------------------------------------
# Risposte
# ---------------------------------------------------------------------------

def normalizza_risposte(risposte: list[dict] | None) -> list[dict]:
    """Tiene l'ULTIMA risposta per ogni id e scarta quelle fuori catalogo.

    Tenere l'ultima e' cio' che rende possibile la correzione: il client
    rimanda la stessa lista con un valore diverso e vince quello nuovo, senza
    che il server debba ricordare niente.
    """
    per_chiave: dict[str, dict] = {}
    for r in risposte or []:
        if not isinstance(r, dict):
            continue
        id_d = str(r.get("id") or "")
        d = per_id(id_d)
        if d is None:
            continue          # una risposta a una domanda inesistente non esiste
        valore = r.get("valore")
        if valore is None:
            continue
        valore = str(valore)
        ammessi = {o["valore"] for o in d.get("opzioni", [])}
        if d.get("tipo") == "scelta" and ammessi:
            if valore not in ammessi and not (valore == NON_SO and d.get("ammette_non_so")):
                continue      # valore non ammesso: si ignora, non si indovina
        per_chiave[id_d] = {"id": id_d, "valore": valore}
    return list(per_chiave.values())


def _valori(risposte: list[dict]) -> dict[str, str]:
    return {r["id"]: r["valore"] for r in risposte}


# ---------------------------------------------------------------------------
# Applicabilita' e coerenza
# ---------------------------------------------------------------------------

def _condizione_vera(cond: dict, ingresso: str, valori: dict[str, str]) -> bool:
    campo = cond.get("campo")
    if campo == "ingresso":
        return ingresso == cond.get("uguale")
    if campo == "risposta":
        v = valori.get(cond.get("id"))
        if v is None:
            return False
        if "uguale" in cond:
            return v == cond["uguale"]
        if "in" in cond:
            return v in cond["in"]
    return False


def applicabile(d: dict, ingresso: str, valori: dict[str, str]) -> bool:
    """Una domanda e' applicabile se il suo ingresso e le sue condizioni tengono.

    Le dipendenze contano: non si chiede se qualcuno puo' accompagnarti prima
    di sapere come ti sposti. Una dipendenza senza risposta rende la domanda
    non ancora applicabile, non scartata per sempre.
    """
    if ingresso not in (d.get("ingressi") or ["problema", "prestazione"]):
        return False
    for dip in d.get("dipende_da", []):
        if dip not in valori:
            return False
    for cond in d.get("applicabile_se", []):
        if not _condizione_vera(cond, ingresso, valori):
            return False
    return True


def invalidate_da(id_corretto: str, valori: dict[str, str]) -> list[str]:
    """Risposte che non valgono piu' dopo la correzione di `id_corretto`.

    Se qualcuno cambia «come ti sposti» da «a piedi» a «ho un'auto», la
    risposta su chi puo' accompagnarlo e' stata data rispondendo a una domanda
    che ora non gli verrebbe nemmeno fatta. Lasciarla in giro significa
    concludere su un presupposto che la persona ha appena smentito.

    La ricerca e' transitiva: cadono anche le dipendenze delle dipendenze.
    """
    cadute: list[str] = []
    frontiera = [id_corretto]
    while frontiera:
        corrente = frontiera.pop()
        for d in _domande():
            if d["id"] in cadute or d["id"] == id_corretto:
                continue
            tocca = corrente in d.get("dipende_da", [])
            if not tocca:
                for cond in d.get("applicabile_se", []):
                    if cond.get("campo") == "risposta" and cond.get("id") == corrente:
                        tocca = True
                        break
            if tocca and d["id"] in valori:
                cadute.append(d["id"])
                frontiera.append(d["id"])
    return cadute


# ---------------------------------------------------------------------------
# Interruzione del percorso
# ---------------------------------------------------------------------------

def interruzione(risposte: list[dict]) -> dict | None:
    """Il percorso si ferma qui e serve un contatto sanitario?

    Deterministica e cablata nel catalogo (`interrompe_se`), non affidata al
    modello. Nota che `non_so` interrompe quanto un `no`: se chi guarda la
    persona non sa dire se respira normalmente, non e' una situazione in cui
    proporre una farmacia.
    """
    valori = _valori(risposte)
    for d in _domande():
        regola = d.get("interrompe_se")
        if not regola:
            continue
        v = valori.get(d["id"])
        if v is not None and v in regola.get("valore_in", []):
            return {
                "id_domanda": d["id"],
                "risposta": v,
                "canale": regola.get("canale", "emergenza_112_118"),
                "motivo": d.get("perche", ""),
                "fonte": d.get("fonte", ""),
            }
    return None


# ---------------------------------------------------------------------------
# Il giro di dialogo
# ---------------------------------------------------------------------------

def candidate(ingresso: str, risposte: list[dict]) -> list[dict]:
    """Le domande che ha senso fare adesso, in ordine di priorita' del catalogo.

    Solo domande applicabili e non ancora risposte: non si ripete mai una
    domanda a cui la persona ha gia' risposto, nemmeno con «non so».
    """
    valori = _valori(risposte)
    fatte = set(valori)
    aperte = [d for d in _domande()
              if d["id"] not in fatte and applicabile(d, ingresso, valori)]
    aperte.sort(key=lambda d: (not d.get("obbligatoria"), d.get("priorita", 99)))
    return aperte


def obbligatorie_mancanti(ingresso: str, risposte: list[dict]) -> list[str]:
    valori = _valori(risposte)
    return [d["id"] for d in _domande()
            if d.get("obbligatoria") and d["id"] not in valori
            and applicabile(d, ingresso, valori)]


def descrivi(risposte: list[dict]) -> str:
    """Le risposte in forma leggibile: «domanda -> etichetta della risposta».

    Serve a quello che si passa al modello. Dandogli le coppie grezze
    (`respiro_o_coscienza=si`) non puo' sapere cosa significhi quel «si», e in
    prova ha interpretato una risposta rassicurante come un allarme, scrivendo
    a una persona che erano «segnalate criticita' relative al respiro» quando
    aveva appena detto il contrario. L'identificativo e' una chiave interna:
    al modello va data la frase.
    """
    righe = []
    for r in risposte:
        d = per_id(r["id"])
        if d is None:
            continue
        if r["valore"] == NON_SO:
            etichetta = "non lo sa"
        else:
            etichetta = next((o["etichetta"] for o in d.get("opzioni", [])
                              if o["valore"] == r["valore"]), r["valore"])
        righe.append(f"  - {d['testo']} -> {etichetta}")
    return "\n".join(righe) or "  (nessuna risposta raccolta)"


def _pubblica(d: dict) -> dict:
    """La domanda come la vede il client: nessun campo interno di regola.

    `opzioni` contiene SOLO le risposte di merito. Il «non so» non sta qui: e'
    il flag `ammette_non_so`, e il bottone lo aggiunge il client. Metterlo in
    entrambi i posti lo faceva comparire due volte nell'interfaccia.
    """
    opzioni = list(d.get("opzioni", []))
    return {
        "id": d["id"],
        "testo": d["testo"],
        "tipo": d.get("tipo", "scelta"),
        "opzioni": opzioni,
        "ammette_non_so": bool(d.get("ammette_non_so")),
        "obbligatoria": bool(d.get("obbligatoria")),
        "perche": d.get("perche", ""),
        "chiarisce": d.get("chiarisce", ""),
        "fonte": d.get("fonte", ""),
        "revisione": d.get("revisione", "bozza"),
    }


def passo(ingresso: str, risposte: list[dict],
          scelta_modello: dict | None = None) -> dict:
    """Un giro di dialogo. Ritorna lo stato e, se serve, la prossima domanda.

    `scelta_modello`, se presente, e' {"id": ..., "motivo": ...} e viene
    accettata SOLO se l'id compare fra le candidate calcolate qui. Il modello
    non allarga mai l'insieme delle domande possibili: puo' solo riordinarlo.
    """
    ingresso = ingresso if ingresso in ("problema", "prestazione") else "problema"
    risposte = normalizza_risposte(risposte)
    valori = _valori(risposte)

    stop = interruzione(risposte)
    if stop:
        return {
            "stato": "contatto_sanitario",
            "domanda": None,
            "proposta_da": "regola_obbligatoria",
            "motivo_proposta": "Il percorso si interrompe: serve un contatto sanitario.",
            "scarto_modello": None,
            "interruzione": stop,
            "fatti": valori,
            "restanti_utili": 0,
        }

    aperte = candidate(ingresso, risposte)
    mancanti = obbligatorie_mancanti(ingresso, risposte)

    # Le obbligatorie applicabili vengono prima di qualunque proposta: sono le
    # uniche domande la cui assenza rende il resto poco affidabile.
    obbligatorie_aperte = [d for d in aperte if d["id"] in mancanti]
    insieme_scelta = obbligatorie_aperte or aperte

    if not insieme_scelta:
        return {
            "stato": "sufficiente",
            "domanda": None,
            "proposta_da": "catalogo",
            "motivo_proposta": "Nessuna domanda residua puo' cambiare il percorso.",
            "scarto_modello": None,
            "interruzione": None,
            "fatti": valori,
            "restanti_utili": 0,
        }

    if len(risposte) >= MASSIMO_DOMANDE:
        # Ci si ferma comunque. Se manca ancora qualcosa di obbligatorio, lo
        # si dice: e' un orientamento incompleto, non un orientamento certo.
        return {
            "stato": "non_determinabile" if mancanti else "sufficiente",
            "domanda": None,
            "proposta_da": "regola_obbligatoria",
            "motivo_proposta": (
                f"Raggiunto il limite di {MASSIMO_DOMANDE} domande: si lavora "
                "con le informazioni disponibili."),
            "scarto_modello": None,
            "interruzione": None,
            "fatti": valori,
            "mancanti": mancanti,
            "restanti_utili": 0,
        }

    ammessi = {d["id"] for d in insieme_scelta}
    scelta, proposta_da, motivo, scarto = insieme_scelta[0], "catalogo", "", None
    if obbligatorie_aperte:
        proposta_da = "regola_obbligatoria"
        motivo = "Domanda obbligatoria applicabile non ancora risposta."

    if scelta_modello and scelta_modello.get("id"):
        id_m = str(scelta_modello["id"])
        if id_m in ammessi:
            scelta = next(d for d in insieme_scelta if d["id"] == id_m)
            proposta_da = "modello"
            motivo = str(scelta_modello.get("motivo") or "")
        else:
            proposta_da = "modello_scartato"
            scarto = {
                "id_proposto": id_m,
                "motivo": ("fuori dall'insieme delle domande applicabili: il "
                           "modello non puo' introdurre domande o regole nuove"),
            }
            motivo = "Proposta del modello scartata: si segue l'ordine del catalogo."

    return {
        # «sufficiente» NON significa «non ho altro da chiedere»: significa che
        # tutte le domande OBBLIGATORIE applicabili hanno una risposta, e quindi
        # la scelta si puo' gia' fare. Le facoltative continuano a essere
        # proposte, ma da qui in poi rispondere e' una scelta di chi legge, non
        # un pedaggio. Tenere lo stato a «in_corso» finche' il catalogo non e'
        # esaurito costringerebbe a rispondere a tutto per vedere le opzioni,
        # che e' esattamente il questionario indefinito da evitare.
        "stato": "in_corso" if mancanti else "sufficiente",
        "domanda": _pubblica(scelta),
        "proposta_da": proposta_da,
        "motivo_proposta": motivo,
        "scarto_modello": scarto,
        "interruzione": None,
        "fatti": valori,
        "mancanti": mancanti,
        # Onesto: quante domande utili restano davvero, non una percentuale
        # inventata che sale in modo rassicurante.
        "restanti_utili": min(len(aperte), MASSIMO_DOMANDE - len(risposte)),
        "id_ammessi": sorted(ammessi),
    }


if __name__ == "__main__":
    print(json.dumps(intestazione(), ensure_ascii=False, indent=1))
    for prova in (
        [],
        [{"id": "respiro_o_coscienza", "valore": "si"}],
        [{"id": "respiro_o_coscienza", "valore": "no"}],
        [{"id": "respiro_o_coscienza", "valore": "si"},
         {"id": "destinatario", "valore": "figlio"},
         {"id": "eta_fascia", "valore": "6_13"},
         {"id": "durata", "valore": "oggi"},
         {"id": "gia_valutato", "valore": "no"}],
    ):
        p = passo("problema", prova)
        d = p["domanda"]["testo"] if p["domanda"] else "—"
        print(f"  {len(prova)} risposte -> {p['stato']:22} {p['proposta_da']:22} {d}")
    print("\n  invalidazione: correggere `mobilita` fa cadere",
          invalidate_da("mobilita", {"mobilita": "piedi", "accompagnatore": "no"}))
