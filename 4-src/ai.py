"""Il livello IA: quattro compiti, quattro schemi, quattro fallback.

REGOLA DI CONFINE, VALIDA PER TUTTO IL FILE.
Il modello non produce numeri e non li ritocca. Riceve indici gia' calcolati
da `indici.py` e opzioni gia' ordinate da Python, e fa le tre sole cose che
un LLM fa meglio di una formula:
  1. leggere testo libero scritto da un umano sotto stress
  2. scegliere fra alternative gia' selezionate
  3. scrivere una motivazione leggibile

Se il modello non risponde, ogni funzione degrada a un esito costruito in
Python dagli stessi numeri. La demo non si ferma mai.
"""
from __future__ import annotations

import re

from llm import LLMError, complete_json

SISTEMA = (
    "Sei un supporto operativo per la rete di emergenza-urgenza della Regione "
    "Lazio. Rispondi in italiano, conciso e concreto. "
    "NON inventare numeri: usa esclusivamente quelli forniti nel prompt. "
    "Non formulare diagnosi: fornisci supporto alla decisione organizzativa."
)


# ---------------------------------------------------------------------------
# Regola di sicurezza. Cablata in Python, NON affidata al prompt.
#
# Un modello puo' sbagliare, essere lento o non rispondere. Il rinvio al 118
# per i sintomi tempo-dipendenti non puo' dipendere da lui: e' un `if`, viene
# prima di ogni chiamata e vince su qualunque risposta del modello.
# ---------------------------------------------------------------------------

RED_FLAG = {
    "dolore toracico": ("dolore al petto", "dolore toracico", "dolore al torace",
                        "fitta al petto", "oppressione al petto", "peso sul petto"),
    "difficolta respiratoria": ("non respira", "fatica a respirare", "affanno",
                                "dispnea", "manca il fiato", "respiro corto",
                                "soffoca"),
    "deficit neurologico": ("non parla", "bocca storta", "non muove", "paralisi",
                            "afasia", "confuso", "ictus", "formicolio al braccio",
                            "mezza faccia"),
    "perdita di coscienza": ("svenuto", "svenuta", "non risponde", "incosciente",
                             "perdita di coscienza", "non si sveglia", "collasso"),
    "emorragia": ("sangue", "emorragia", "sanguina", "perdita di sangue"),
    "convulsioni": ("convulsioni", "crisi epilettica", "scossa"),
    "trauma maggiore": ("incidente", "caduta dall'alto", "investito", "precipitato"),
}


NEGAZIONI = {"non", "no", "nessun", "nessuna", "niente", "nulla", "senza",
             "mai", "escluso", "negato", "smesso", "passato", "cessato"}

# Parole che CHIUDONO la portata di una negazione: dopo di loro la frase
# ricomincia, e il segnale che segue non e' negato.
STOP_NEGAZIONE = {"ma", "pero", "pero'", "tuttavia", "invece", "anche", "e",
                  "mentre", "adesso", "ora", "improvvisamente"}

# Marcatori che rendono INCERTA l'attribuzione temporale o il soggetto. Non
# spengono il segnale: lo accompagnano, perche' un elenco di parole non puo'
# decidere di chi e di quando si sta parlando.
MARCATORI_PASSATO = ("ieri", "settimana scorsa", "mese scorso", "anni fa",
                     "in passato", "una volta", "da bambino", "storia di",
                     "gia' avuto", "ha avuto")
MARCATORI_TERZI = ("mio padre", "mia madre", "mio nonno", "mia nonna",
                   "in famiglia", "familiare", "parente")


def _finestra_negata(t: str, inizio: int) -> bool:
    """C'e' una negazione che governa la parola che comincia a `inizio`?

    Si guardano le sei parole precedenti. Sei perche' «non ha mai avuto dolore
    al petto» ne ha cinque fra la negazione e il sintomo, e perche' allargando
    ancora si finisce a negare la frase sbagliata in un testo lungo.

    Se fra la negazione e il sintomo c'e' una congiunzione avversativa («non
    respira bene ma il dolore al petto e' passato»), la negazione NON arriva
    fino al sintomo e il segnale resta attivo. Nel dubbio si resta prudenti:
    qui un falso positivo costa un avviso di troppo, un falso negativo costa
    molto di piu'.
    """
    prima = t[:inizio].split()[-6:]
    if not prima:
        return False
    for i in range(len(prima) - 1, -1, -1):
        parola = prima[i].strip(".,;:!?")
        if parola in STOP_NEGAZIONE:
            return False          # l'avversativa chiude la portata della negazione
        if parola in NEGAZIONI:
            return True
    return False


def segnali_emergenza(testo: str) -> dict:
    """Segnali tempo-dipendenti riconosciuti nel testo, con i loro limiti.

    PERCHE' NON BASTA CERCARE SOTTOSTRINGHE, ed e' il motivo per cui questa
    funzione restituisce un dict e non una lista.

    La ricerca di sottostringhe non capisce:
      - la NEGAZIONE. «non ha dolore al petto» contiene «dolore al petto».
        Qui si guarda indietro di sei parole e si scarta il segnale se una
        negazione lo governa (vedi _finestra_negata).
      - il SOGGETTO. «mio padre ha avuto un infarto» parla di anamnesi
        familiare, non di adesso. Non e' risolvibile con parole chiave: viene
        DICHIARATO come limite, non silenziosamente ignorato.
      - la TEMPORALITA'. «la settimana scorsa mi mancava il fiato» e «mi manca
        il fiato» hanno lo stesso lessico ed esiti diversi. Si segnalano i
        marcatori di passato trovati, senza decidere al posto di nessuno.
      - i SINONIMI e il parlato. Un elenco finito non li copre tutti.

    Da qui la regola che vale in tutta l'app: NESSUNA CORRISPONDENZA NON
    SIGNIFICA ASSENZA DI RISCHIO. Il campo `limite` lo dice esplicitamente e
    l'interfaccia lo mostra. Il percorso non si chiude mai perche' le parole
    chiave non hanno trovato niente: si chiude solo su una risposta esplicita
    della persona (vedi dialogo.interruzione).
    """
    t = " " + re.sub(r"\s+", " ", (testo or "").lower()) + " "
    attivi, negati = [], []
    for etichetta, chiavi in RED_FLAG.items():
        for k in chiavi:
            pos = t.find(k)
            if pos < 0:
                continue
            (negati if _finestra_negata(t, pos) else attivi).append(etichetta)
            break
    passato = sorted({m for m in MARCATORI_PASSATO if m in t})
    terzi = sorted({m for m in MARCATORI_TERZI if m in t})
    return {
        "attivi": sorted(set(attivi)),
        "negati": sorted(set(negati)),
        "marcatori_passato": passato,
        "marcatori_terzi": terzi,
        "limite": (
            "Riconoscimento per parole chiave: non interpreta in modo affidabile "
            "negazioni complesse, sinonimi, chi e' il soggetto e quando e' "
            "successo. L'assenza di segnali NON significa assenza di rischio."),
        "incerto": bool(passato or terzi),
    }


def red_flag(testo: str) -> list[str]:
    """Compatibilita': solo i segnali attivi, senza il contorno."""
    return segnali_emergenza(testo)["attivi"]


# Presidi che NON accettano il paziente generico adulto. Il dato regionale non
# lo dice: `TIPO` per il Bambino Gesu' vale "DEA II", che e' vero ma solo per
# i bambini. Senza questo elenco l'app manderebbe un infarto di un 62enne al
# pronto soccorso pediatrico: e' il genere di errore che una giuria con dei
# medici dentro nota subito.
SOLO_PEDIATRICI = {"90401", "90402"}        # Bambino Gesu' Roma e Palidoro
SPECIALISTICI = {                            # PS SPEC.: accesso per patologia
    "6602": "ortopedia e traumatologia",
    "3000": "oculistica",
}


# ---------------------------------------------------------------------------
# 3. Bollettino meteo-sanitario
# ---------------------------------------------------------------------------

SCHEMA_BOLLETTINO = {
    "type": "object",
    "properties": {
        "rischi": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "fenomeno": {"type": "string"},
                "severita": {"type": "string",
                             "enum": ["nessuna", "lieve", "moderata", "grave", "estrema"]},
                "effetto_atteso": {"type": "string"},
            },
            "required": ["fenomeno", "severita", "effetto_atteso"],
        }},
        "gruppi_vulnerabili": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "gruppo": {"type": "string"},
                "perche": {"type": "string"},
            },
            "required": ["gruppo", "perche"],
        }},
        "azioni_preparatorie": {"type": "array", "items": {"type": "string"}},
        "messaggio_cittadini": {"type": "string"},
    },
    "required": ["rischi", "gruppi_vulnerabili", "azioni_preparatorie",
                 "messaggio_cittadini"],
}


def bollettino_sanitario(meteo: dict, aria: dict | None = None) -> dict:
    """Dalle condizioni ambientali reali a chi e' a rischio e cosa predisporre."""
    righe_aria = ""
    if aria:
        pollini = aria.get("pollini") or {}
        righe_aria = (
            f"PM10 {aria.get('pm10')} ug/m3, PM2.5 {aria.get('pm2_5')} ug/m3, "
            f"indice AQI europeo {aria.get('aqi_europeo')}\n"
            f"Pollini: " + ", ".join(f"{k} {v}" for k, v in pollini.items()) + "\n"
        )
    prompt = (
        "CONDIZIONI AMBIENTALI RILEVATE NEL LAZIO (dati misurati, non stimati):\n"
        f"Temperatura {meteo.get('temperatura_c')} C, percepita "
        f"{meteo.get('percepita_c')} C\n"
        f"Umidita' {meteo.get('umidita_pct')}%, precipitazioni "
        f"{meteo.get('precipitazione_mm')} mm, vento "
        f"{meteo.get('vento_kmh')} km/h\n"
        f"{righe_aria}\n"
        "Produci il bollettino sanitario per la cabina di regia regionale.\n"
        "- `rischi`: solo i fenomeni effettivamente presenti in questi numeri. "
        "Se le condizioni sono normali, dillo con severita' 'nessuna' invece di "
        "inventare allarmi.\n"
        "- `gruppi_vulnerabili`: chi e' a rischio IN QUESTE condizioni "
        "specifiche, e perche'.\n"
        "- `azioni_preparatorie`: massimo 5 misure organizzative concrete "
        "(scorte, personale, procedure, comunicazione).\n"
        "- `messaggio_cittadini`: 2 frasi, linguaggio semplice."
    )
    try:
        return complete_json(prompt, SCHEMA_BOLLETTINO, SISTEMA)
    except LLMError:
        percepita = meteo.get("percepita_c") or 0
        return {
            "rischi": [{
                "fenomeno": "caldo" if percepita >= 30 else "condizioni ordinarie",
                "severita": "moderata" if percepita >= 30 else "nessuna",
                "effetto_atteso": "Valutazione non disponibile.",
            }],
            "gruppi_vulnerabili": [],
            "azioni_preparatorie": [],
            "messaggio_cittadini": "Interpretazione automatica non disponibile in questa modalita'.",
            "_fallback": True,
        }


# ---------------------------------------------------------------------------
# 3. Quale domanda fare adesso (dialogo adattivo)
# ---------------------------------------------------------------------------
#
# Il modello sceglie un ID da un elenco CHIUSO che gli passa `dialogo.py`, e
# motiva la scelta. Non puo' inventare domande, non puo' introdurre regole
# cliniche, non decide se il percorso si interrompe. Se propone un ID fuori
# elenco, `dialogo.passo()` scarta la proposta e lo dichiara.

SCHEMA_DOMANDA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "motivo": {"type": "string"},
    },
    "required": ["id", "motivo"],
}


def prossima_domanda(testo: str, ammessi: list[dict], fatti: dict) -> dict | None:
    """Quale fra le domande gia' dichiarate applicabili conviene fare adesso."""
    if not ammessi:
        return None
    righe = "\n".join(
        f"  - id: {d['id']}\n    domanda: {d['testo']}\n    chiarisce: {d.get('chiarisce','')}"
        for d in ammessi)
    noti = fatti if isinstance(fatti, str) else (
        ", ".join(f"{k}={v}" for k, v in (fatti or {}).items()) or "niente")
    prompt = (
        "Una persona sta cercando di capire a quale servizio sanitario "
        "rivolgersi. Ha scritto:\n"
        f"\"{(testo or '(nessuna descrizione)')[:600]}\"\n\n"
        f"GIA' NOTO: {noti}\n\n"
        f"DOMANDE CHE E' AMMESSO FARE ADESSO:\n{righe}\n\n"
        "Scegli l'UNICA domanda la cui risposta puo' cambiare di piu' il "
        "percorso di questa persona.\n"
        "- `id` DEVE essere uno degli id elencati sopra, copiato esattamente.\n"
        "- Non proporre domande diverse da queste e non aggiungere criteri "
        "clinici tuoi.\n"
        "- `motivo`: una frase, rivolta alla persona, che spiega a cosa serve.")
    try:
        return complete_json(prompt, SCHEMA_DOMANDA, SISTEMA)
    except LLMError:
        return None      # nessuna proposta: decide l'ordine del catalogo


# ---------------------------------------------------------------------------
# 4. Orientamento del cittadino
# ---------------------------------------------------------------------------

SCHEMA_ORIENTAMENTO = {
    "type": "object",
    "properties": {
        "opzione_id": {"type": "string"},
        "titolo": {"type": "string"},
        "spiegazione": {"type": "string"},
        "cosa_manca": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["opzione_id", "titolo", "spiegazione", "cosa_manca"],
}

CANALE_PER_GENERE = {
    "pronto_soccorso": "pronto_soccorso",
    "farmacia": "farmacia",
    "struttura_accreditata": "struttura_territoriale",
    "canale_telefonico": "continuita_assistenziale_116117",
    "medico_di_famiglia": "medico_di_famiglia",
}

AVVERTENZE = [
    "Questo strumento non fa diagnosi e non attribuisce un codice di triage: "
    "aiuta a capire quale canale puo' essere appropriato e raggiungibile.",
    "Se la situazione peggiora, o se hai un dubbio, chiama il 112.",
    "Un dato mancante non significa che un servizio sia assente: significa che "
    "va verificato sul canale ufficiale indicato.",
]


def orientamento(testo: str, confronto: dict, fatti: dict,
                 segnali: dict | None = None,
                 fatti_leggibili: str = "") -> dict:
    """Sceglie e spiega UNA opzione fra quelle gia' calcolate in Python.

    DUE COSE CHE QUESTA FUNZIONE NON FA, e sono deliberate.

    1. Non inventa destinazioni. Il modello restituisce un `opzione_id`, e
       quell'id viene cercato fra gli id realmente esistenti. Se non c'e' - se
       il modello ha scritto un nome di ospedale che gli e' venuto in mente -
       la scelta viene scartata e si ripiega sulla prima opzione compatibile
       calcolata dalle regole. Nessun nome mostrato all'utente puo' provenire
       dal modello.

    2. Non quantifica il tempo risparmiato. Il prompt lo vieta esplicitamente,
       perche' non abbiamo dati comparabili: la coda di un pronto soccorso non
       si converte nel tempo di attesa di chi arriva adesso.

    IL FALLBACK NON E' RASSICURANTE. Se il modello non risponde, la vecchia
    versione ripiegava su «vai in una struttura territoriale», che e' un
    consiglio sanitario dato da un `except`. Adesso il fallback dichiara di non
    poter concludere e indirizza al 116117, che e' il canale fatto apposta per
    ricevere una domanda a cui questa app non sa rispondere.
    """
    compatibili = confronto.get("opzioni") or []
    validi = {o["id"]: o for gruppo in ("opzioni", "non_verificabili", "escluse")
              for o in confronto.get(gruppo, []) for _ in (0,)}
    validi = {o["id"]: o
              for gruppo in ("opzioni", "non_verificabili", "escluse")
              for o in confronto.get(gruppo, [])}

    def esito(opzione, deciso_da, certezza, titolo, spiegazione, manca):
        return {
            "canale": CANALE_PER_GENERE.get((opzione or {}).get("genere"),
                                            "non_determinabile"),
            "opzione_id": (opzione or {}).get("id"),
            "titolo": titolo,
            "spiegazione": spiegazione,
            "deciso_da": deciso_da,
            "certezza": certezza,
            "cosa_manca": manca,
        }

    if not compatibili:
        return esito(
            next((o for o in confronto.get("non_verificabili", [])
                  if o["genere"] == "canale_telefonico"), None),
            "regole deterministiche", "dichiaratamente_incerta",
            "Non riusciamo a indicarti un'opzione compatibile",
            "Con le informazioni disponibili nessuna delle alternative che "
            "conosciamo risulta compatibile con il tuo percorso. Il 116117 e' "
            "il canale giusto per farsi indicare cosa fare da un medico.",
            ["nessuna opzione compatibile fra quelle note"])

    righe = "\n".join(
        f"  - id: {o['id']}\n    nome: {o['nome']} ({o['genere']})\n"
        f"    perche' compatibile: {o['motivo']}"
        + (f"\n    viaggio: {o['viaggio']['durata_min']} minuti"
           if o.get("viaggio") else "")
        + (f"\n    persone in coda adesso: {o['coda']['in_attesa']}"
           if (o.get("coda") or {}).get("in_attesa") is not None else "")
        for o in compatibili[:6])
    # `fatti` puo' essere gia' la descrizione leggibile costruita da
    # dialogo.descrivi(): in quel caso si usa cosi' com'e'.
    noti = fatti_leggibili if fatti_leggibili else (
        "\n".join(f"  - {k}: {v}" for k, v in (fatti or {}).items()) or "  niente")
    nota_segnali = ""
    if segnali and segnali.get("incerto"):
        nota_segnali = ("\nATTENZIONE: nel testo ci sono riferimenti al passato o "
                        "a un'altra persona. Non dare per scontato che i sintomi "
                        "siano attuali e di chi scrive.\n")

    prompt = (
        f"UNA PERSONA HA DESCRITTO COSI' LA SUA SITUAZIONE:\n"
        f"\"{(testo or '(nessuna descrizione)')[:600]}\"\n\n"
        f"INFORMAZIONI RACCOLTE (domanda -> risposta della persona):\n{noti}\n"
        f"{nota_segnali}\n"
        f"OPZIONI GIA' VERIFICATE COMPATIBILI (scegline UNA):\n{righe}\n\n"
        "Indica quale conviene e spiega perche' a questa persona.\n"
        "VINCOLI ASSOLUTI:\n"
        "- `opzione_id` DEVE essere uno degli id elencati sopra, copiato "
        "esattamente. Non nominare strutture che non compaiono in questo elenco.\n"
        "- NON fare diagnosi e non ipotizzare la causa del problema.\n"
        "- NON stimare quanto tempo si risparmia ne' quanto si aspettera': non "
        "abbiamo dati per dirlo, e la coda non e' il tempo di attesa personale.\n"
        "- NON dire che una struttura e' migliore perche' ha meno gente in "
        "attesa: dice solo che in quel momento c'era meno fila.\n"
        "- `cosa_manca`: le informazioni che, se le sapessimo, potrebbero far "
        "cambiare questa indicazione.\n"
        "- `spiegazione`: massimo 3 frasi, in seconda persona, concrete.")

    try:
        r = complete_json(prompt, SCHEMA_ORIENTAMENTO, SISTEMA)
    except LLMError:
        primo = compatibili[0]
        return esito(
            primo, "regole deterministiche (modello non disponibile)", "media",
            f"Opzione piu' vicina fra quelle compatibili: {primo['nome']}",
            "In modalita' demo l'orientamento personalizzato non era in cache: "
            "viene quindi mostrata la prima opzione compatibile per "
            f"distanza. {primo['motivo']} Se hai un dubbio, chiama il 116117.",
            ["motivazione personalizzata non disponibile"])

    scelto = validi.get(str(r.get("opzione_id") or ""))
    if scelto is None or scelto["compatibilita"] != "compatibile":
        # Il modello ha nominato qualcosa che non esiste o che le regole hanno
        # gia' escluso. Si scarta e lo si dichiara.
        primo = compatibili[0]
        return esito(
            primo, "regole deterministiche (proposta del modello scartata)",
            "media",
            f"Opzione compatibile piu' vicina: {primo['nome']}",
            f"{primo['motivo']} La proposta del modello e' stata scartata perche' "
            f"indicava una destinazione non presente fra le opzioni verificate.",
            ["motivazione personalizzata non disponibile"]) | {
            "scarto_modello": {"opzione_id_proposto": r.get("opzione_id"),
                               "motivo": "identificativo inesistente o gia' escluso"}}

    return esito(scelto, "modello, entro le opzioni verificate", "media",
                 str(r.get("titolo") or scelto["nome"]),
                 str(r.get("spiegazione") or scelto["motivo"]),
                 [str(x) for x in (r.get("cosa_manca") or [])])


if __name__ == "__main__":
    print("--- riconoscimento dei segnali: deterministico, nessun modello ---")
    for frase in ["mio figlio ha 38.5 di febbre da ieri sera",
                  "uomo 62 anni con forte dolore al petto che si irradia al braccio",
                  "non ha dolore al petto e respira bene",
                  "mio padre ha avuto un infarto dieci anni fa",
                  "mia madre non parla piu' e ha la bocca storta"]:
        s = segnali_emergenza(frase)
        print(f"  attivi={s['attivi'] or '—'} negati={s['negati'] or '—'} "
              f"incerto={s['incerto']}  <- {frase[:46]}")
    print("\n  " + segnali_emergenza("")["limite"])
