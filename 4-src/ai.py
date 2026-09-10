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


def red_flag(testo: str) -> list[str]:
    """Sintomi tempo-dipendenti riconosciuti nel testo. Deterministico."""
    t = " " + re.sub(r"\s+", " ", (testo or "").lower()) + " "
    return sorted({etichetta for etichetta, chiavi in RED_FLAG.items()
                   if any(k in t for k in chiavi)})


# ---------------------------------------------------------------------------
# 1. Piano di deviazione — cabina di regia
# ---------------------------------------------------------------------------

SCHEMA_DEVIAZIONE = {
    "type": "object",
    "properties": {
        "quota_da_deviare": {"type": "integer", "minimum": 0},
        "codici_coinvolti": {"type": "array", "items":
                             {"type": "string", "enum": ["bianchi", "verdi", "gialli"]}},
        "destinazioni": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "nome": {"type": "string"},
                "quota": {"type": "integer", "minimum": 0},
                "perche": {"type": "string"},
            },
            "required": ["nome", "quota", "perche"],
        }},
        "urgenza": {"type": "integer", "minimum": 1, "maximum": 5},
        "motivazione": {"type": "string"},
        "azioni_operative": {"type": "array", "items": {"type": "string"}},
        "effetto_domino": {"type": "string"},
    },
    "required": ["quota_da_deviare", "codici_coinvolti", "destinazioni",
                 "urgenza", "motivazione", "azioni_operative", "effetto_domino"],
}


def piano_deviazione(critico, candidati: list, meteo: dict | None = None) -> dict:
    """Come alleggerire un presidio in allarme. Numeri gia' calcolati in input."""
    righe = "\n".join(
        f"  - {c.nome} ({c.tipo}, {c.comune}): pressione {c.pressione_relativa}, "
        f"capacita' residua stimata {c.posti_residui} pazienti, "
        f"{c.in_attesa} in attesa"
        for c in candidati[:6]
    )
    contesto_meteo = ""
    if meteo:
        contesto_meteo = (
            f"\nCONTESTO METEO: {meteo.get('temperatura_c')} C percepiti "
            f"{meteo.get('percepita_c')} C, umidita' {meteo.get('umidita_pct')}%.\n"
        )
    prompt = (
        f"PRESIDIO IN ALLARME: {critico.nome} ({critico.tipo}, {critico.comune}, "
        f"ASL {critico.asl})\n"
        f"  pazienti presenti: {critico.presenti}, in attesa: {critico.in_attesa}\n"
        f"  indice di pressione: {critico.pressione_relativa} "
        f"(1.0 = come il presidio mediano della rete in questo istante; "
        f"soglia di allarme 1.5)\n"
        f"  sofferenza rispetto al proprio storico: {critico.sofferenza_relativa} "
        f"(stessa scala: 1.0 = come la mediana della rete)\n"
        f"  codici bianchi e verdi in attesa: {critico.deviabili_osservati}\n"
        f"  carico deviabile stimato: {critico.carico_deviabile} pazienti\n"
        f"  ore-paziente recuperabili: {critico.ore_paziente_recuperabili}\n"
        f"{contesto_meteo}\n"
        f"PRESIDI CANDIDATI AD ASSORBIRE:\n{righe}\n\n"
        "Proponi un piano di deviazione. Vincoli assoluti:\n"
        "- NON deviare mai codici rossi.\n"
        "- `quota_da_deviare` non puo' superare il carico deviabile stimato.\n"
        "- La somma delle quote nelle destinazioni deve dare `quota_da_deviare`.\n"
        "- Non assegnare a un presidio piu' della sua capacita' residua.\n"
        "- In `effetto_domino` di' esplicitamente se una destinazione rischia "
        "di finire a sua volta in allarme.\n"
        "- `azioni_operative`: massimo 4 azioni concrete e verificabili."
    )
    try:
        esito = complete_json(prompt, SCHEMA_DEVIAZIONE, SISTEMA)
    except LLMError as exc:
        # Fallback deterministico: stessa decisione, senza prosa.
        quota = int(critico.carico_deviabile or 0)
        capienti = [c for c in candidati if (c.posti_residui or 0) > 0][:2]
        esito = {
            "quota_da_deviare": quota,
            "codici_coinvolti": ["bianchi", "verdi"],
            "destinazioni": [
                {"nome": c.nome, "quota": quota // max(len(capienti), 1),
                 "perche": f"capacita' residua stimata {c.posti_residui} pazienti"}
                for c in capienti
            ],
            "urgenza": 4 if (critico.pressione or 0) >= 2 else 3,
            "motivazione": (
                f"Modello non disponibile ({exc}). Piano calcolato dai soli "
                f"indici: {quota} codici a bassa intensita' deviabili da "
                f"{critico.nome}."),
            "azioni_operative": ["Attivare la deviazione dei codici bianchi e verdi"],
            "effetto_domino": "Non valutato: modello non disponibile.",
            "_fallback": True,
        }
    esito["presidio"] = critico.nome
    return esito


# ---------------------------------------------------------------------------
# 2. Triage della chiamata — centrale 118
# ---------------------------------------------------------------------------

SCHEMA_TRIAGE = {
    "type": "object",
    "properties": {
        "codice": {"type": "string", "enum": ["rosso", "giallo", "verde", "bianco"]},
        "sintomi": {"type": "array", "items": {"type": "string"}},
        "dea_ii_richiesto": {"type": "boolean"},
        "paziente_pediatrico": {"type": "boolean"},
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "sintesi": {"type": "string"},
    },
    "required": ["codice", "sintomi", "dea_ii_richiesto", "paziente_pediatrico",
                 "red_flags", "sintesi"],
}

GRAVITA = {"bianco": 0, "verde": 1, "giallo": 2, "rosso": 3}

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


def triage_chiamata(testo: str) -> dict:
    """Da testo libero della chiamata a codice colore strutturato.

    La regola red-flag di Python NON e' un suggerimento al modello: se scatta,
    il codice non puo' scendere sotto il giallo qualunque cosa dica il modello.
    """
    bandiere = red_flag(testo)
    prompt = (
        f"CHIAMATA ALLA CENTRALE OPERATIVA 118:\n\"{testo}\"\n\n"
        "Classifica secondo il triage italiano:\n"
        "  rosso  = emergenza, pericolo di vita imminente\n"
        "  giallo = urgenza, rischio evolutivo\n"
        "  verde  = urgenza differibile\n"
        "  bianco = non urgente\n"
        "`dea_ii_richiesto` vale true solo se servono alta specialita' "
        "(emodinamica, neurochirurgia, trauma center, rianimazione pediatrica).\n"
        "`paziente_pediatrico` vale true se il paziente ha meno di 18 anni "
        "(bambino, neonato, eta' dichiarata sotto i 18).\n"
        "`sintesi`: massimo 2 frasi, per l'operatore che deve decidere subito."
    )
    try:
        esito = complete_json(prompt, SCHEMA_TRIAGE, SISTEMA)
    except LLMError as exc:
        esito = {
            "codice": "giallo" if bandiere else "verde",
            "sintomi": [],
            "dea_ii_richiesto": bool(bandiere),
            "paziente_pediatrico": False,
            "red_flags": bandiere,
            "sintesi": f"Modello non disponibile ({exc}). "
                       f"Classificazione prudenziale dalle sole parole chiave.",
            "_fallback": True,
        }

    # --- la regola di sicurezza vince sul modello ---------------------------
    esito["red_flags_rilevate_da_regola"] = bandiere
    if bandiere and GRAVITA.get(esito.get("codice", "verde"), 1) < GRAVITA["giallo"]:
        esito["codice_modello"] = esito["codice"]
        esito["codice"] = "giallo"
        esito["corretto_da_regola"] = True
    esito["chiama_118"] = bool(bandiere) or esito.get("codice") == "rosso"
    return esito


def destinazioni_per_chiamata(triage: dict, vicini: list) -> list[dict]:
    """Ordina i presidi per la chiamata. Ordinamento DETERMINISTICO, in Python.

    Criteri, in ordine: idoneita' (un DEA II serve se richiesto), poi coda
    osservata, poi tempo di percorrenza. Il modello non tocca questa lista.
    """
    serve_dea_ii = bool(triage.get("dea_ii_richiesto"))
    pediatrico = bool(triage.get("paziente_pediatrico"))
    esito = []
    for v in vicini:
        cod = str(v.get("codice"))
        idoneo, motivo = True, "livello adeguato al codice"

        # L'incompatibilita' di popolazione viene PRIMA del livello di cura:
        # un DEA II pediatrico resta inadatto a un adulto per quanto attrezzato.
        if cod in SOLO_PEDIATRICI and not pediatrico:
            idoneo, motivo = False, "presidio pediatrico: non accetta adulti"
        elif pediatrico and cod in SOLO_PEDIATRICI:
            idoneo, motivo = True, "presidio pediatrico specializzato"
        elif cod in SPECIALISTICI:
            idoneo = False
            motivo = f"pronto soccorso specialistico ({SPECIALISTICI[cod]}): non generalista"
        elif serve_dea_ii and v.get("tipo") != "DEA II":
            idoneo, motivo = False, "non e' un DEA II: alta specialita' non disponibile"
        elif serve_dea_ii:
            motivo = "DEA II richiesto per alta specialita'"

        esito.append({**v, "idoneo": idoneo, "motivo_idoneita": motivo})
    esito.sort(key=lambda d: (
        not d["idoneo"],
        d.get("durata_min") or 999,
        d.get("pressione") or 0,
    ))
    return esito


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
    except LLMError as exc:
        percepita = meteo.get("percepita_c") or 0
        return {
            "rischi": [{
                "fenomeno": "caldo" if percepita >= 30 else "condizioni ordinarie",
                "severita": "moderata" if percepita >= 30 else "nessuna",
                "effetto_atteso": "Valutazione non disponibile.",
            }],
            "gruppi_vulnerabili": [],
            "azioni_preparatorie": [],
            "messaggio_cittadini": f"Bollettino non disponibile ({exc}).",
            "_fallback": True,
        }


# ---------------------------------------------------------------------------
# 4. Consiglio al cittadino
# ---------------------------------------------------------------------------

SCHEMA_CITTADINO = {
    "type": "object",
    "properties": {
        "dove": {"type": "string",
                 "enum": ["118", "pronto_soccorso", "struttura_territoriale",
                          "farmacia", "medico_di_base"]},
        "motivazione": {"type": "string"},
        "alternative": {"type": "array", "items": {"type": "string"}},
        "cosa_fare_subito": {"type": "string"},
    },
    "required": ["dove", "motivazione", "alternative", "cosa_fare_subito"],
}


def consiglio_cittadino(sintomo: str, vicini: list,
                        territoriali: list | None = None) -> dict:
    """Dove conviene andare. Se scatta una red flag, il 118 vince e basta."""
    bandiere = red_flag(sintomo)
    if bandiere:
        # Non si interpella nemmeno il modello: e' una decisione che non gli
        # compete e ogni secondo di latenza sarebbe tempo sottratto.
        return {
            "dove": "118",
            "motivazione": ("Nella descrizione compaiono sintomi che richiedono "
                            "soccorso immediato: " + ", ".join(bandiere) + "."),
            "alternative": [],
            "cosa_fare_subito": "Chiama subito il 118. Non metterti in viaggio da solo.",
            "red_flags_rilevate_da_regola": bandiere,
            "chiama_118": True,
            "deciso_da": "regola di sicurezza (nessuna chiamata al modello)",
        }

    righe = "\n".join(
        f"  - {v.get('nome')} ({v.get('tipo', 'presidio')}), "
        f"{v.get('durata_min', '?')} minuti, "
        f"{v.get('in_attesa', '?')} persone in attesa"
        for v in vicini[:6]
    )
    # La medicina di prossimita' e' il punto della traccia: senza queste righe
    # il modello puo' solo scegliere fra ospedali, e consiglierebbe il pronto
    # soccorso anche quando basta una farmacia sotto casa.
    righe_terr = "\n".join(
        f"  - {t.get('nome')} ({t.get('genere')}), {t.get('indirizzo')}, "
        f"{t.get('distanza_km')} km"
        for t in (territoriali or [])[:6]
    ) or "  (nessun presidio territoriale geolocalizzato nel raggio)"
    prompt = (
        f"UNA PERSONA DESCRIVE COSI' IL PROPRIO PROBLEMA:\n\"{sintomo}\"\n\n"
        f"PRONTO SOCCORSO VICINI (dati reali, gia' calcolati):\n{righe}\n\n"
        f"PRESIDI TERRITORIALI VICINI:\n{righe_terr}\n\n"
        "Consiglia dove conviene rivolgersi. Regole:\n"
        "- Non fare diagnosi: indica solo il livello di assistenza adeguato.\n"
        "- Se il caso e' minore, indirizza a una farmacia o struttura "
        "territoriale NOMINANDOLA fra quelle elencate, e spiega quanto tempo "
        "si risparmia rispetto alla coda del pronto soccorso.\n"
        "- `cosa_fare_subito`: una frase pratica.\n"
        "- Chiudi sempre ricordando che in caso di peggioramento si chiama il 118."
    )
    try:
        esito = complete_json(prompt, SCHEMA_CITTADINO, SISTEMA)
        esito["deciso_da"] = "modello, entro le opzioni calcolate"
    except LLMError as exc:
        esito = {
            "dove": "struttura_territoriale",
            "motivazione": f"Modello non disponibile ({exc}).",
            "alternative": [v.get("nome") for v in vicini[:3]],
            "cosa_fare_subito": "Contatta il tuo medico di base o una farmacia.",
            "_fallback": True,
            "deciso_da": "fallback deterministico",
        }
    esito["red_flags_rilevate_da_regola"] = []
    esito["chiama_118"] = False
    esito["avvertenza"] = ("Questo strumento non sostituisce un parere medico. "
                           "In caso di peggioramento chiama il 118.")
    return esito


if __name__ == "__main__":
    print("--- regola red-flag, deterministica, nessun modello coinvolto ---")
    for t in ["mio figlio ha 38.5 di febbre da ieri sera",
              "uomo 62 anni con forte dolore al petto che si irradia al braccio",
              "caviglia gonfia dopo una storta giocando a calcetto",
              "mia madre non parla piu' e ha la bocca storta"]:
        print(f"  {red_flag(t) or '(nessuna)'}  <- {t[:52]}")
