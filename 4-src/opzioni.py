"""«Perche' questa opzione per me?» — il confronto fra alternative reali.

COSA FA. Prende le risposte del dialogo e costruisce l'elenco delle opzioni
concrete: pronto soccorso, farmacie, strutture accreditate, canali telefonici.
Per ognuna dice se e' compatibile con QUESTO percorso, cosa serve per usarla,
quanto e' lontana, e da dove viene ogni affermazione.

TRE ESITI, NON DUE. E' la decisione di progetto piu' importante del file.

    compatibile       i requisiti noti sono soddisfatti
    incompatibile     un requisito noto NON e' soddisfatto
    non_verificabile  non lo sappiamo, e non fingiamo di saperlo

La terza categoria esiste perche' l'alternativa e' mentire in una delle due
direzioni. Se non abbiamo gli orari di una struttura, dire «aperta» e' falso e
dire «chiusa» pure: quello che possiamo dire e' dove si verifica. Dato mancante
non significa servizio assente, e non significa nemmeno servizio presente.

ORDINE DELLE OPZIONI. Prima la compatibilita' del percorso, poi la logistica.
Il tempo di viaggio non promuove mai un'opzione incompatibile sopra una
compatibile: si usa solo per ordinare fra alternative gia' appropriate.

QUELLO CHE NON FACCIAMO, ed e' altrettanto deliberato:
  - Non si stima il tempo risparmiato. La lunghezza della coda di un pronto
    soccorso non e' il tempo di attesa di chi arriva adesso, e una media
    pubblicata non e' una previsione personale. Mostriamo la coda, dichiarata
    per quello che e'.
  - Non si premia il numero di apparecchiature come qualita' generale. Un
    ospedale con tre TAC non e' «migliore»: e' compatibile con una richiesta di
    TAC. La dotazione conta solo rispetto a una prestazione gia' indicata da un
    professionista.
  - Meno pazienti in attesa non significa cure piu' appropriate. Non entra mai
    nel giudizio di compatibilita', solo nell'informazione mostrata.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import percorsi
import territorio
from ai import SOLO_PEDIATRICI, SPECIALISTICI

RADICE = Path(__file__).resolve().parent.parent
APPARECCHIATURE = RADICE / "2-data" / "derived" / "apparecchiature.json"

NON_SO = "non_so"

# Fonti citabili. Ogni affermazione mostrata all'utente deve poterne indicare
# una: e' il requisito «consentire di aprire fonte, data e modalita' di
# verifica per ogni affermazione rilevante».
FONTI = {
    "presidi": {
        "nome": "Elenco strutture e accessi PS, Regione Lazio (open data)",
        "url": "https://dati.lazio.it/",
        "data": "2021-07-15",
        "come_verificato": "anagrafica dei presidi incrociata con l'elenco ospedali regionale",
    },
    "live": {
        "nome": "Stato dei pronto soccorso, Salute Lazio",
        "url": "https://salutelazio.it/pronto-soccorso",
        "data": "in tempo reale",
        "come_verificato": "lettura diretta dell'API pubblica usata dal portale regionale",
    },
    "farmacie": {
        "nome": "Anagrafe delle farmacie, Regione Lazio (open data)",
        "url": "https://dati.lazio.it/",
        "data": "2026",
        "come_verificato": "filtro sulle sole farmacie con validita' aperta e posizione non sentinella",
    },
    "accreditate": {
        "nome": "Strutture sanitarie private accreditate, Regione Lazio",
        "url": "https://dati.lazio.it/",
        "data": "2026",
        "come_verificato": "anagrafica regionale con coordinate e attivita' dichiarata",
    },
    "apparecchiature": {
        "nome": "Apparecchiature sanitarie, Ministero della Salute (IODL 2.0)",
        "url": "https://www.dati.salute.gov.it/it/dataset/apparecchiature-sanitarie/",
        "data": "2026-09-07",
        "come_verificato": "estratto Lazio, abbinato al presidio per coordinate e confermato sul nome",
    },
    "116117": {
        "nome": "116117 — Numero europeo per cure mediche non urgenti, Regione Lazio",
        "url": "https://www.regione.lazio.it/notizie/salute-attivo-in-tutta-la-regione-il-numero-116117",
        "data": "2026",
        "come_verificato": "pagina istituzionale della Regione Lazio",
    },
    "112": {
        "nome": "Numero unico di emergenza 112 / 118",
        "url": "https://www.regione.lazio.it/",
        "data": "—",
        "come_verificato": "numero pubblico di emergenza",
    },
}

# Quale dotazione documentata serve per una prestazione gia' indicata. Solo le
# grandi apparecchiature censite dal Ministero: per tutto il resto l'inventario
# non dice nulla, e non dirlo e' meglio che dedurlo.
PRESTAZIONE_APPARECCHIATURA = {
    "tac": "TAC",
    "rmn": "RMN",
}


@lru_cache(maxsize=1)
def _apparecchiature() -> dict:
    try:
        return json.loads(APPARECCHIATURE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"strutture": [], "non_risolti": [], "riepilogo": {}}


@lru_cache(maxsize=1)
def _dotazione_per_presidio() -> dict[str, list[dict]]:
    """{codice_presidio: [dotazione]} solo per gli abbinamenti CONFERMATI.

    Gli abbinamenti incerti non entrano: un fuzzy match non verificato che
    influenza un consiglio e' esattamente cio' che non deve succedere.
    """
    esito: dict[str, list[dict]] = {}
    for s in _apparecchiature().get("strutture", []):
        if s.get("abbinamento") != "confermato" or not s.get("codice_presidio"):
            continue
        esito.setdefault(str(s["codice_presidio"]), []).extend(s.get("dotazione", []))
    return esito


def _requisito(cosa: str, stato: str, come: str, fonte: str | dict) -> dict:
    return {
        "cosa": cosa,
        "stato": stato,                    # necessario | non_necessario | non_verificabile
        "come_verificare": come,
        "fonte": FONTI.get(fonte) if isinstance(fonte, str) else fonte,
    }


def _viaggio(lat, lon, dlat, dlon, mobilita: str | None) -> dict:
    p = percorsi.percorso(lat, lon, dlat, dlon)
    v = {
        "distanza_km": round(p["distanza_km"], 1),
        "durata_min": round(p["durata_min"], 1),
        "fonte": p["fonte"],
    }
    # La raggiungibilita' senza auto non e' deducibile dai dati che abbiamo:
    # non e' integrato alcun feed GTFS. Si dichiara, non si stima.
    if mobilita in ("mezzi", "piedi", "ridotta"):
        v["senza_auto"] = "non_verificabile"
        v["nota_senza_auto"] = (
            "Il tempo mostrato e' su strada in auto. Senza auto la durata reale "
            "puo' essere molto diversa: nessun dato sul trasporto pubblico e' "
            "integrato in questo prototipo.")
    return v


# ---------------------------------------------------------------------------
# Costruzione delle opzioni
# ---------------------------------------------------------------------------

def _opzione_ps(i, lat, lon, fatti, meta) -> dict:
    """Un pronto soccorso come opzione, con la sua compatibilita' motivata."""
    pediatrico = fatti.get("eta_fascia") in ("0_1", "1_13", "14_17") or \
        fatti.get("destinatario") == "figlio"
    codice = str(i.codice)

    compat, motivo = "compatibile", "Pronto soccorso generalista, accesso diretto senza prescrizione."
    if codice in SOLO_PEDIATRICI and not pediatrico:
        compat, motivo = "incompatibile", "Pronto soccorso pediatrico: non accetta pazienti adulti."
    elif codice in SOLO_PEDIATRICI and pediatrico:
        motivo = "Pronto soccorso pediatrico: e' la destinazione dedicata a questa fascia di eta'."
    elif codice in SPECIALISTICI:
        compat = "incompatibile"
        motivo = (f"Pronto soccorso specialistico ({SPECIALISTICI[codice]}): "
                  "accetta solo quel tipo di problema.")
    elif pediatrico and i.tipo not in ("DEA II", "DEA I"):
        compat = "non_verificabile"
        motivo = ("Non risulta se questo presidio abbia un percorso pediatrico "
                  "dedicato: va verificato prima di andarci.")

    fonti = [FONTI["presidi"]]
    coda = None
    if i.senza_dato:
        coda = {"in_attesa": None, "livelli": [],
                "nota": "Questo presidio non trasmette lo stato: nessun dato sulla coda."}
        if compat == "compatibile":
            compat = "non_verificabile"
            motivo = ("Struttura idonea, ma non trasmette lo stato: non sappiamo "
                      "quante persone ci siano.")
    else:
        coda = {
            "in_attesa": i.in_attesa,
            "livelli": list(i.attesa_livelli or []),
            "attesa_media_pubblicata_h": i.attesa_h if i.attesa_misurata else None,
            "nota": ("Numero di persone in coda al momento della rilevazione. "
                     "Non e' il tempo che aspetterai tu, e la media pubblicata "
                     "non e' una previsione personale."),
        }
        if meta.get("fonte_tipo") == "live":
            fonti = [FONTI["live"], FONTI["presidi"]]

    requisiti = [
        _requisito("prescrizione", "non_necessario",
                   "L'accesso al pronto soccorso non richiede impegnativa.", "presidi"),
        _requisito("orario", "non_necessario",
                   "Il pronto soccorso e' attivo 24 ore su 24.", "presidi"),
    ]
    if fatti.get("mobilita") == "ridotta" and fatti.get("accompagnatore") == "no":
        requisiti.append(_requisito(
            "accompagnamento", "non_verificabile",
            "Chiedi alla struttura se e' previsto un servizio di accoglienza "
            "per chi arriva solo e con difficolta' motorie.", "presidi"))

    return {
        "id": f"ps:{codice}",
        "nome": i.nome,
        "genere": "pronto_soccorso",
        "tipo": i.tipo,
        "comune": i.comune,
        "lat": i.lat, "lon": i.lon,
        "compatibilita": compat,
        "motivo": motivo,
        "requisiti": requisiti,
        "coda": coda,
        "dotazione": _dotazione_per_presidio().get(codice, []),
        "fonti": fonti,
        "viaggio": (_viaggio(lat, lon, i.lat, i.lon, fatti.get("mobilita"))
                    if (i.lat and i.lon and lat and lon) else None),
    }


def _opzione_territorio(t, lat, lon, fatti) -> dict:
    farmacia = t.get("genere") == "farmacia"
    prescrizione = fatti.get("prescrizione")

    requisiti = [_requisito(
        "orario di apertura", "non_verificabile",
        "Gli orari e i turni per singola sede non sono integrati in questo "
        "prototipo: verificali sul canale ufficiale della struttura o della ASL.",
        "farmacie" if farmacia else "accreditate")]

    if farmacia:
        compat = "compatibile"
        motivo = ("Farmacia: puo' dare un consiglio e i farmaci da banco, "
                  "senza appuntamento.")
        requisiti.append(_requisito(
            "prescrizione", "non_necessario",
            "Per un consiglio o un farmaco da banco non serve ricetta.", "farmacie"))
    else:
        compat = "non_verificabile"
        motivo = ("Struttura accreditata: l'anagrafe dice che esiste ed e' "
                  "accreditata, non quali prestazioni eroga oggi ne' a chi.")
        if prescrizione == "no":
            compat = "incompatibile"
            motivo = ("Senza impegnativa non e' possibile prenotare in SSN. "
                      "Serve prima il medico che la prescrive.")
        requisiti.append(_requisito(
            "prescrizione", "necessario" if prescrizione != "privato" else "non_necessario",
            "Per il percorso SSN serve l'impegnativa del medico; per l'accesso "
            "privato no, ma il costo e' a carico tuo.", "accreditate"))
        requisiti.append(_requisito(
            "accesso SSN", "non_verificabile",
            "L'accreditamento non dimostra che quella prestazione sia erogata in "
            "SSN in quella sede: chiedilo alla struttura.", "accreditate"))

    return {
        "id": f"{'farmacia' if farmacia else 'struttura'}:{t.get('nome')}|{t.get('lat')},{t.get('lon')}",
        "nome": t.get("nome"),
        "genere": "farmacia" if farmacia else "struttura_accreditata",
        "tipo": t.get("genere"),
        "comune": t.get("comune"),
        "indirizzo": t.get("indirizzo"),
        "lat": t.get("lat"), "lon": t.get("lon"),
        "compatibilita": compat,
        "motivo": motivo,
        "requisiti": requisiti,
        "coda": None,
        "dotazione": [],
        "fonti": [FONTI["farmacie"] if farmacia else FONTI["accreditate"]],
        "viaggio": (_viaggio(lat, lon, t["lat"], t["lon"], fatti.get("mobilita"))
                    if (t.get("lat") and lat) else None),
    }


def _canali(fatti: dict, ingresso: str) -> list[dict]:
    """I canali telefonici. Non sono un ripiego: spesso sono la risposta giusta."""
    esito = [{
        "id": "canale:116117",
        "nome": "116117 — cure mediche non urgenti",
        "genere": "canale_telefonico",
        "compatibilita": "compatibile",
        "motivo": ("Numero gratuito attivo nel Lazio per problemi che non sono "
                   "emergenze: ti mettono in contatto con un medico che valuta "
                   "il caso e indica cosa fare."),
        "requisiti": [
            _requisito("prescrizione", "non_necessario", "E' un numero telefonico.", "116117"),
            _requisito("orario", "non_verificabile",
                       "La copertura oraria del servizio va verificata sulla pagina "
                       "istituzionale della Regione: non e' integrata qui.", "116117"),
        ],
        "coda": None, "dotazione": [], "viaggio": None,
        "fonti": [FONTI["116117"]],
    }]
    if fatti.get("gia_valutato") == "si_indicazione" or ingresso == "prestazione":
        esito.append({
            "id": "canale:medico_di_famiglia",
            "nome": "Il tuo medico di famiglia",
            "genere": "medico_di_famiglia",
            "compatibilita": "non_verificabile",
            "motivo": ("E' chi puo' prescrivere e indirizzare nel percorso SSN. "
                       "Non sappiamo chi sia il tuo medico ne' i suoi orari."),
            "requisiti": [_requisito(
                "iscrizione", "necessario",
                "Serve essere assistiti da quel medico: gli orari di studio sono "
                "sulla sua pagina ASL.", "accreditate")],
            "coda": None, "dotazione": [], "viaggio": None,
            "fonti": [FONTI["accreditate"]],
        })
    return esito


# ---------------------------------------------------------------------------
# Prestazione gia' indicata: la dotazione documentata entra in gioco
# ---------------------------------------------------------------------------

def _filtra_per_prestazione(opzioni: list[dict], prestazione: str | None) -> list[dict]:
    """Rende esplicito se una struttura ha la dotazione per QUELLA prestazione.

    Regola: la dotazione non e' un punteggio di qualita'. Serve a rispondere a
    una domanda binaria — questa macchina qui c'e' o non risulta? — e la
    seconda risposta e' «non risulta», non «non c'e'».
    """
    tipo = PRESTAZIONE_APPARECCHIATURA.get(prestazione or "")
    if not tipo:
        return opzioni
    for o in opzioni:
        if o["genere"] not in ("pronto_soccorso", "struttura_accreditata"):
            continue
        posseduta = [d for d in (o.get("dotazione") or []) if d.get("tipo") == tipo]
        if posseduta:
            o["dotazione_pertinente"] = posseduta
            o["motivo"] = (f"L'inventario ministeriale documenta {tipo} in questa "
                           f"sede. Questo dice che l'apparecchiatura esiste, non "
                           f"che ci sia un posto disponibile.")
            if o["compatibilita"] == "compatibile":
                pass
        else:
            o["compatibilita"] = "non_verificabile"
            o["motivo"] = (f"Nessuna {tipo} risulta in questa sede nell'inventario "
                           f"ministeriale. L'assenza dal dataset non prova l'assenza "
                           f"della dotazione: chiedilo alla struttura.")
        o["fonti"] = list(o.get("fonti") or []) + [FONTI["apparecchiature"]]
    return opzioni


# ---------------------------------------------------------------------------
# Confronto
# ---------------------------------------------------------------------------

ORDINE_COMPAT = {"compatibile": 0, "non_verificabile": 1, "incompatibile": 2}


def confronta(ingresso: str, fatti: dict, indici_rete: list, meta: dict,
              lat: float | None, lon: float | None,
              precedente: list[dict] | None = None) -> dict:
    """Costruisce e ordina le opzioni. Nessun modello coinvolto qui dentro."""
    opzioni: list[dict] = []

    if lat and lon:
        con_coord = [i for i in indici_rete if i.lat and i.lon]
        con_coord.sort(key=lambda i: percorsi.haversine_km(lat, lon, i.lat, i.lon))
        for i in con_coord[:4]:
            opzioni.append(_opzione_ps(i, lat, lon, fatti, meta))
        for t in territorio.vicini(lat, lon, raggio_km=3.0, quanti=5):
            opzioni.append(_opzione_territorio(t, lat, lon, fatti))

    opzioni.extend(_canali(fatti, ingresso))
    opzioni = _filtra_per_prestazione(opzioni, fatti.get("prestazione_cercata"))

    # ORDINE: prima la compatibilita', poi - solo fra pari - la logistica.
    def chiave(o):
        v = o.get("viaggio") or {}
        return (ORDINE_COMPAT.get(o["compatibilita"], 3),
                v.get("durata_min") if v.get("durata_min") is not None else 998)
    opzioni.sort(key=chiave)

    return {
        "opzioni": [o for o in opzioni if o["compatibilita"] == "compatibile"],
        "non_verificabili": [o for o in opzioni if o["compatibilita"] == "non_verificabile"],
        "escluse": [o for o in opzioni if o["compatibilita"] == "incompatibile"],
        "cambiamenti": cambiamenti(precedente, opzioni, fatti),
    }


ETICHETTA_VINCOLO = {
    "mobilita": "come ti sposti",
    "prescrizione": "la prescrizione",
    "destinatario": "per chi cerchi assistenza",
    "eta_fascia": "la fascia di eta'",
    "accompagnatore": "la presenza di un accompagnatore",
    "prestazione_cercata": "la prestazione cercata",
}


def cambiamenti(precedente: list[dict] | None, adesso: list[dict],
                fatti: dict) -> list[dict]:
    """Cosa e' cambiato rispetto alla risposta precedente, e per quale dato.

    Senza questo il confronto e' una lista che si riordina da sola sotto gli
    occhi di chi la guarda. Con questo, ogni movimento ha una causa dichiarata.
    """
    if not precedente:
        return []
    prima = {o["id"]: o for o in precedente}
    esito = []
    for o in adesso:
        p = prima.get(o["id"])
        if p is None:
            esito.append({
                "opzione": o["nome"],
                "effetto": "e' comparsa fra le alternative",
                "da": None, "a": o["compatibilita"],
                "dato_determinante": _dato_determinante(fatti),
            })
        elif p["compatibilita"] != o["compatibilita"]:
            esito.append({
                "opzione": o["nome"],
                "effetto": f"da «{p['compatibilita']}» a «{o['compatibilita']}»",
                "da": p["compatibilita"], "a": o["compatibilita"],
                "motivo": o["motivo"],
                "dato_determinante": _dato_determinante(fatti),
            })
    adesso_id = {o["id"] for o in adesso}
    for id_p, p in prima.items():
        if id_p not in adesso_id:
            esito.append({
                "opzione": p["nome"],
                "effetto": "non compare piu' fra le alternative",
                "da": p["compatibilita"], "a": None,
                "dato_determinante": _dato_determinante(fatti),
            })
    return esito


def _dato_determinante(fatti: dict) -> str:
    noti = [ETICHETTA_VINCOLO[k] for k in ETICHETTA_VINCOLO if fatti.get(k)]
    return ", ".join(noti) if noti else "le informazioni raccolte finora"


def ids_validi(risultato: dict) -> set[str]:
    """Gli identificativi realmente esistenti, per validare l'output del modello."""
    return {o["id"] for gruppo in ("opzioni", "non_verificabili", "escluse")
            for o in risultato.get(gruppo, [])}


if __name__ == "__main__":
    import indici as _i
    lista, meta = _i.rete("attesa", "live")
    r = confronta("problema",
                  {"destinatario": "figlio", "eta_fascia": "1_13", "mobilita": "piedi"},
                  lista, meta, 41.8933, 12.4829)
    for g in ("opzioni", "non_verificabili", "escluse"):
        print(f"\n--- {g} ({len(r[g])}) ---")
        for o in r[g][:4]:
            v = o.get("viaggio") or {}
            print(f"  {o['genere']:22} {str(o['nome'])[:34]:34} "
                  f"{str(v.get('durata_min','—')):>6} min  {o['motivo'][:60]}")
