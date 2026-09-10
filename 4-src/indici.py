"""Indici deterministici sulla rete dei pronto soccorso.

QUI NON PASSA MAI L'LLM. Ogni numero che l'interfaccia mostra nasce in questo
file, da open data, con una formula scritta e verificabile. Il modello riceve
questi numeri gia' calcolati e li commenta: non li produce e non li ritocca.
E' la risposta in una riga a "dove finisce il dato e dove comincia l'IA".

Le due metriche portanti sono costruite apposta su segnali DIVERSI, perche'
due indici che condividono il normalizzatore collassano sullo stesso
ordinamento e uno dei due diventa decorativo:

  pressione   -> occupazione:  quanti pazienti pesati ci sono rispetto a
                 quanti ce ne stanno normalmente (legge di Little)
  sofferenza  -> smaltimento:  quanto si aspetta adesso rispetto a quanto si
                 aspetta di solito IN QUEL presidio
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict

from feed import COLORI, StatoPS, stato_rete

ORE_ANNO = 365 * 24

# Peso di risorsa per codice colore: un rosso impegna molto piu' di un bianco.
# Scala di buon senso clinico, dichiarata e non nascosta nel codice.
PESO_COLORE = {"rossi": 4.0, "gialli": 2.5, "verdi": 1.0, "bianchi": 0.5}

# Peso di fase. L'osservazione breve pesa piu' del trattamento perche' occupa
# un posto senza scorrere; il ricovero in attesa di letto (boarding) e' il
# vero collo di bottiglia dei pronto soccorso ed e' quello che pesa di piu'.
PESO_ATTESA = 1.0
PESO_TRATTAMENTO = 1.0
PESO_OSSERVAZIONE = 1.5
PESO_BOARDING = 2.0

# Soglie applicate ai valori RELATIVI alla mediana della rete, non a quelli
# assoluti: 1.5 = una volta e mezza il presidio mediano nello stesso istante.
SOGLIA_PRESSIONE = 1.5
SOGLIA_SOFFERENZA = 1.5


def _carico_pesato(s: StatoPS) -> float:
    """Pazienti presenti, pesati per gravita' e per fase."""
    totale = 0.0
    for c in COLORI:
        totale += PESO_COLORE[c] * (
            s.attesa.get(c, 0) * PESO_ATTESA
            + s.trattamento.get(c, 0) * PESO_TRATTAMENTO
            + s.osservazione.get(c, 0) * PESO_OSSERVAZIONE
        )
    # i ricoverati ancora in PS non hanno dettaglio per colore: peso medio alto
    totale += s.tot_ricovero * PESO_BOARDING * PESO_COLORE["gialli"]
    return totale


def _peso_medio_storico(storico: dict) -> float | None:
    """Peso atteso di un paziente medio DI QUEL presidio, dal mix di triage."""
    if not storico:
        return None
    mix = {
        "rossi": storico.get("pct_rossi"),
        "gialli": storico.get("pct_gialli"),
        "verdi": storico.get("pct_verdi"),
        "bianchi": storico.get("pct_bianchi"),
    }
    if any(v is None for v in mix.values()):
        return None
    return sum(PESO_COLORE[c] * (mix[c] / 100.0) for c in COLORI)


@dataclass
class Indici:
    codice: str
    nome: str
    tipo: str
    comune: str
    asl: str
    lat: float | None
    lon: float | None

    presenti: int
    in_attesa: int
    carico_pesato: float

    # --- pressione: occupazione contro capacita' stimata (legge di Little) ---
    occupazione_attesa: float | None      # pazienti simultanei attesi in media
    pressione: float | None               # 1.0 = normale, >1 = sopra il suo normale
    posti_residui: float | None           # quanti pazienti ancora assorbe

    # --- sofferenza: coda contro smaltimento storico ---
    throughput_h: float | None            # pazienti/ora smaltiti in media
    attesa_implicita_h: float | None      # coda attuale / throughput
    sofferenza: float | None              # rapporto con la mediana storica

    # --- deviabilita' ---
    deviabili_osservati: int              # bianchi + verdi in attesa, contati
    quota_strutturale: float | None       # % storica di bianchi+verdi
    carico_deviabile: float | None        # osservati, corretti per la struttura
    ore_paziente_recuperabili: float | None

    # grandezze intermedie, servono a _calibra() per la capacita' residua
    atteso_pesato: float | None = None
    peso_medio: float | None = None

    # L'attesa effettivamente usata per la sofferenza, e da dove viene.
    # Con lo snapshot e' stimata dalla coda; con il feed live e' il tempo medio
    # PUBBLICATO dalla Regione. Il numero cambia significato, quindi si dichiara.
    attesa_h: float | None = None
    attesa_misurata: bool = False
    attesa_storica_h: float | None = None   # mediana storica di quel presidio

    # La fonte non ha dato niente per questo presidio: i suoi zeri non sono
    # misure. Non ordinabile, non proponibile come destinazione.
    senza_dato: bool = False

    # --- calibrazione sulla rete (riempita da rete(), vedi nota sotto) ---
    pressione_relativa: float | None = None   # 1.0 = come il resto della rete ora
    sofferenza_relativa: float | None = None

    in_allarme: bool = False
    note: list[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def calcola(s: StatoPS) -> Indici:
    """Tutti gli indici di un presidio. I campi non calcolabili restano None.

    Un presidio senza storico NON viene scartato: si mostra con gli indici
    assoluti e una nota. Nascondere i buchi e' peggio che dichiararli.
    """
    note: list[str] = []
    st = s.storico or {}
    if not s.dato_disponibile:
        note.append(s.nota_fonte or "nessun dato dalla fonte per questo presidio")
    carico = _carico_pesato(s)

    accessi = st.get("accessi_anno")
    permanenza = st.get("mediana_permanenza_h")
    attesa_storica = st.get("mediana_attesa_h")

    # --- Legge di Little: L = lambda * W ------------------------------------
    # Il numero medio di pazienti contemporaneamente dentro un sistema e' il
    # tasso di arrivo per il tempo medio di permanenza. Con gli accessi annui
    # e la mediana di permanenza otteniamo la capacita' operativa REALE del
    # presidio, senza bisogno del numero di posti letto (che non abbiamo).
    occupazione = None
    pressione = None
    atteso_pesato = None
    peso_medio = None
    if not s.ha_presenti:
        # Fonte live: pubblica solo la coda. Senza chi e' gia' in trattamento
        # o in osservazione, il numeratore dell'occupazione non esiste.
        # Calcolarla lo stesso darebbe un numero piccolo e falso per tutti.
        note.append("fonte live: chi e' gia' dentro non e' pubblicato, "
                    "pressione non calcolabile")
    elif accessi and permanenza:
        occupazione = (accessi / ORE_ANNO) * permanenza
        peso_medio = _peso_medio_storico(st)
        if occupazione > 0 and peso_medio:
            atteso_pesato = occupazione * peso_medio
            pressione = carico / atteso_pesato
            # NB: posti_residui NON si calcola qui. Servirebbe una soglia
            # assoluta, ma la pressione grezza al picco vale 8-15 per tutti
            # (vedi _calibra): con la soglia 1.5 ogni presidio risulterebbe
            # a capacita' zero. Lo calcola _calibra() sulla scala della rete.
    else:
        note.append("storico assente: pressione non calcolabile")

    # --- Sofferenza: segnale diverso, colonne diverse -----------------------
    # Non riusa ne' la permanenza ne' l'occupazione: guarda quanto ci si mette
    # a smaltire la coda ATTUALE rispetto all'attesa mediana storica.
    throughput = None
    attesa_implicita = None
    sofferenza = None
    attesa_usata = None
    misurata = False
    if accessi:
        throughput = accessi / ORE_ANNO
        if throughput > 0:
            attesa_implicita = s.tot_attesa / throughput
    # Se la fonte pubblica il tempo di attesa vero, quello vince sulla stima:
    # non e' un miglioramento cosmetico, e' la differenza fra "quanto ci
    # metterebbe a smaltire questa coda al suo ritmo medio" e "quanto sta
    # aspettando davvero la gente che e' li' adesso".
    if s.attesa_media_h is not None:
        attesa_usata, misurata = s.attesa_media_h, True
    elif attesa_implicita is not None:
        attesa_usata = attesa_implicita
    if attesa_usata is not None:
        if attesa_storica and attesa_storica > 0:
            sofferenza = attesa_usata / attesa_storica
        else:
            note.append("attesa mediana storica assente")

    # --- Deviabilita' -------------------------------------------------------
    # I codici a bassa intensita' gia' in attesa sono il bacino teorico.
    # La correzione: un verde in un presidio dove l'80% degli accessi storici
    # e' bianco/verde e' quasi certamente un caso minore; lo stesso verde in un
    # DEA II dove i verdi sono il 40% ha piu' probabilita' di essere un caso
    # complesso declassato al triage. La quota storica e' un moltiplicatore di
    # confidenza sulla deviabilita', non un conteggio.
    deviabili = s.attesa.get("bianchi", 0) + s.attesa.get("verdi", 0)
    quota = None
    carico_deviabile = None
    ore_paziente = None
    if st.get("pct_bianchi") is not None and st.get("pct_verdi") is not None:
        quota = (st["pct_bianchi"] + st["pct_verdi"]) / 100.0
        carico_deviabile = deviabili * quota
        if permanenza:
            # ore-paziente restituite al presidio se quella quota non entrasse
            ore_paziente = carico_deviabile * permanenza

    return Indici(
        codice=s.codice, nome=s.nome, tipo=s.tipo, comune=s.comune, asl=s.asl,
        lat=s.lat, lon=s.lon,
        presenti=s.presenti, in_attesa=s.tot_attesa,
        carico_pesato=round(carico, 1),
        occupazione_attesa=round(occupazione, 1) if occupazione else None,
        pressione=round(pressione, 2) if pressione else None,
        posti_residui=None,   # lo riempie _calibra()
        atteso_pesato=round(atteso_pesato, 2) if atteso_pesato else None,
        peso_medio=round(peso_medio, 3) if peso_medio else None,
        throughput_h=round(throughput, 2) if throughput else None,
        attesa_implicita_h=round(attesa_implicita, 2) if attesa_implicita is not None else None,
        sofferenza=round(sofferenza, 2) if sofferenza else None,
        attesa_h=round(attesa_usata, 2) if attesa_usata is not None else None,
        attesa_misurata=misurata,
        attesa_storica_h=attesa_storica,
        deviabili_osservati=deviabili,
        quota_strutturale=round(quota, 3) if quota else None,
        carico_deviabile=round(carico_deviabile, 1) if carico_deviabile is not None else None,
        ore_paziente_recuperabili=round(ore_paziente, 1) if ore_paziente is not None else None,
        senza_dato=not s.dato_disponibile,
        in_allarme=False,   # deciso da rete(), serve la mediana della rete
        note=note,
    )


def _mediana(valori: list[float]) -> float | None:
    v = sorted(valori)
    if not v:
        return None
    meta = len(v) // 2
    return v[meta] if len(v) % 2 else (v[meta - 1] + v[meta]) / 2


def _calibra(tutti: list[Indici],
             mediane: tuple[float | None, float | None] | None = None
             ) -> tuple[float | None, float | None]:
    """Normalizza pressione e sofferenza sulla MEDIANA DELLA RETE nello stesso istante.

    Perche' serve. La legge di Little con gli accessi annui restituisce
    l'occupazione media *su tutto l'anno*, notti e mesi vuoti compresi. Lo
    snapshot pero' e' un mercoledi' di luglio alle 16:58, cioe' un picco: se
    confrontassimo il picco con la media annua, ogni presidio risulterebbe
    "in allarme" e la soglia non distinguerebbe piu' niente.

    La rilevazione e' pero' simultanea per tutti i 49 presidi, quindi il
    confronto che conta davvero e' fra presidi nello stesso momento: 1.0
    significa "come il resto della rete adesso", 2.0 "il doppio della mediana".
    Cosi' la soglia si autocalibra e resta valida anche su un feed live.

    ATTENZIONE al parametro `mediane`. Serve alla simulazione controfattuale:
    se si ricalibrasse lo scenario "dopo" sulla sua NUOVA mediana, spostare
    pazienti da un presidio abbasserebbe la mediana di rete e farebbe salire i
    valori relativi di tutti gli altri, facendo sembrare che l'intervento
    peggiori la situazione. Il confronto prima/dopo si fa a scala fissa: si
    passano le mediane dello scenario di partenza.
    """
    if mediane is not None:
        med_p, med_s = mediane
    else:
        med_p = _mediana([i.pressione for i in tutti if i.pressione])
        med_s = _mediana([i.sofferenza for i in tutti if i.sofferenza])
    for i in tutti:
        if i.pressione and med_p:
            i.pressione_relativa = round(i.pressione / med_p, 2)
            # Capacita' residua: quanti pazienti in piu' prima di arrivare alla
            # soglia, espressa sulla scala della rete e non su un assoluto.
            if i.atteso_pesato and i.peso_medio:
                tetto = SOGLIA_PRESSIONE * med_p * i.atteso_pesato
                i.posti_residui = round(max(0.0, (tetto - i.carico_pesato) / i.peso_medio), 1)
        if i.sofferenza and med_s:
            i.sofferenza_relativa = round(i.sofferenza / med_s, 2)
        if (i.posti_residui is None and not i.senza_dato
                and med_s and i.throughput_h and i.attesa_storica_h):
            # Fonte live: senza occupazione non c'e' capacita' residua per
            # posti. Si ripiega su quella della CODA: quante persone possono
            # ancora mettersi in fila prima che l'attesa qui valga una volta e
            # mezza la mediana della rete. E' una grandezza diversa da quella
            # dello snapshot - stessa domanda, altro lato del pronto soccorso -
            # e per questo resta dichiarata nelle note.
            coda_max = (SOGLIA_SOFFERENZA * med_s * i.attesa_storica_h
                        * i.throughput_h)
            i.posti_residui = round(max(0.0, coda_max - i.in_attesa), 1)
            i.note = (i.note or []) + ["capacita' residua stimata sulla coda"]
        i.in_allarme = bool(
            (i.pressione_relativa or 0) >= SOGLIA_PRESSIONE
            or (i.sofferenza_relativa or 0) >= SOGLIA_SOFFERENZA
        )
    return med_p, med_s


# Gli ordinamenti selezionabili dall'interfaccia. Chiave -> (etichetta, campo).
ORDINAMENTI = {
    "pressione":   ("Piu' sotto pressione", "pressione_relativa"),
    "sofferenza":  ("Piu' in sofferenza rispetto al proprio normale", "sofferenza_relativa"),
    "attesa":      ("Piu' pazienti in attesa", "in_attesa"),
    "presenti":    ("Piu' pazienti presenti", "presenti"),
    "deviabile":   ("Maggior carico deviabile", "carico_deviabile"),
    "capienza":    ("Maggior capacita' residua", "posti_residui"),
}


def rete(ordine: str = "pressione", fonte: str = "snapshot") -> tuple[list[Indici], dict]:
    stati, meta = stato_rete(fonte)
    calcolati = [calcola(s) for s in stati]
    _calibra(calcolati)
    etichetta, campo = ORDINAMENTI.get(ordine, ORDINAMENTI["pressione"])
    # i None vanno in fondo in ogni caso, non in cima per caso
    calcolati.sort(
        key=lambda i: (getattr(i, campo) is not None, getattr(i, campo) or 0),
        reverse=True,
    )
    meta = dict(meta)
    meta["ordine"] = {"chiave": ordine, "etichetta": etichetta, "campo": campo}
    meta["in_allarme"] = sum(1 for i in calcolati if i.in_allarme)
    meta["carico_deviabile_totale"] = round(
        sum(i.carico_deviabile or 0 for i in calcolati), 1)
    meta["ore_paziente_recuperabili"] = round(
        sum(i.ore_paziente_recuperabili or 0 for i in calcolati), 1)
    return calcolati, meta


if __name__ == "__main__":
    import sys
    if "--collasso" in sys.argv:
        # LA VERIFICA CHE DECIDE SE "SOFFERENZA" ESISTE DAVVERO.
        # Se i primi 5 per sofferenza coincidono con i primi 5 per attesa,
        # l'indicatore non aggiunge niente e il pitch deve puntare altrove.
        for a in ("pressione", "sofferenza", "attesa", "deviabile"):
            top, _ = rete(a)
            print(f"{a:11} -> " + " | ".join(t.nome[:22] for t in top[:5]))
        s_top = [t.codice for t in rete("sofferenza")[0][:5]]
        a_top = [t.codice for t in rete("attesa")[0][:5]]
        p_top = [t.codice for t in rete("pressione")[0][:5]]
        print(f"\nsovrapposizione sofferenza/attesa:   {len(set(s_top) & set(a_top))}/5")
        print(f"sovrapposizione sofferenza/pressione: {len(set(s_top) & set(p_top))}/5")
        raise SystemExit

    ordine = sys.argv[1] if len(sys.argv) > 1 else "pressione"
    top, meta = rete(ordine)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"\n{'PRESIDIO':30} {'TIPO':8} {'PRESS':>6} {'SOFF':>6} {'ATT':>4} {'DEV':>6} {'ORE':>7}")
    for i in top[:12]:
        f = lambda v, n=1: ("-" if v is None else f"{v:.{n}f}")
        print(f"{i.nome[:30]:30} {i.tipo:8} {f(i.pressione,2):>6} {f(i.sofferenza,2):>6} "
              f"{i.in_attesa:4} {f(i.carico_deviabile):>6} {f(i.ore_paziente_recuperabili):>7}")


# ---------------------------------------------------------------------------
# Simulazione controfattuale
#
# E' la risposta a "perche' non basta una dashboard?". Una dashboard mostra lo
# stato; questa funzione mostra lo stato CHE CI SAREBBE se si agisse, e ne
# misura l'effetto sull'intera rete, effetto domino compreso.
#
# Tutto deterministico: nessun modello coinvolto. L'IA propone il piano, questa
# funzione ne calcola le conseguenze.
# ---------------------------------------------------------------------------

def simula(codice_critico: str, quota: int, destinazioni: dict[str, int]) -> dict:
    """Sposta `quota` codici a bassa intensita' e ricalcola TUTTA la rete.

    destinazioni: {codice_presidio: quanti pazienti assorbe}
    Ritorna prima/dopo per ogni presidio toccato, piu' l'effetto complessivo.
    """
    stati, meta = stato_rete()
    per_codice = {s.codice: s for s in stati}
    prima = {i.codice: i for i in [calcola(s) for s in stati]}
    scala = _calibra(list(prima.values()))

    critico = per_codice.get(codice_critico)
    if critico is None:
        raise KeyError(f"presidio {codice_critico} sconosciuto")

    # Si tolgono prima i bianchi (i piu' deviabili), poi i verdi. Mai i gialli,
    # mai i rossi: e' un vincolo clinico, non un'ottimizzazione.
    restanti = min(quota, critico.attesa.get("bianchi", 0) + critico.attesa.get("verdi", 0))
    tolti = {}
    for colore in ("bianchi", "verdi"):
        n = min(restanti, critico.attesa.get(colore, 0))
        critico.attesa[colore] -= n
        critico.tot_attesa -= n
        critico.presenti -= n
        tolti[colore] = n
        restanti -= n

    # e si aggiungono alle destinazioni, come verdi (ipotesi prudenziale:
    # chi arriva altrove viene ritriagiato al livello piu' alto fra i deviabili)
    assorbito = {}
    for cod, n in destinazioni.items():
        d = per_codice.get(cod)
        if d is None:
            continue
        n = int(n)
        d.attesa["verdi"] = d.attesa.get("verdi", 0) + n
        d.tot_attesa += n
        d.presenti += n
        assorbito[cod] = n

    dopo = {i.codice: i for i in [calcola(s) for s in stati]}
    _calibra(list(dopo.values()), mediane=scala)   # scala fissa: vedi _calibra()

    toccati = [codice_critico] + list(destinazioni)
    confronto = []
    for cod in toccati:
        a, b = prima.get(cod), dopo.get(cod)
        if not a or not b:
            continue
        confronto.append({
            "codice": cod, "nome": a.nome,
            "ruolo": "origine" if cod == codice_critico else "destinazione",
            "prima": {"in_attesa": a.in_attesa, "pressione_relativa": a.pressione_relativa,
                      "in_allarme": a.in_allarme},
            "dopo": {"in_attesa": b.in_attesa, "pressione_relativa": b.pressione_relativa,
                     "in_allarme": b.in_allarme},
            "diventa_critico": (not a.in_allarme) and b.in_allarme,
        })

    ore = prima[codice_critico].ore_paziente_recuperabili
    return {
        "spostati": tolti,
        "assorbiti": assorbito,
        "confronto": confronto,
        "allarmi_prima": sum(1 for i in prima.values() if i.in_allarme),
        "allarmi_dopo": sum(1 for i in dopo.values() if i.in_allarme),
        "effetto_domino": [c["nome"] for c in confronto if c["diventa_critico"]],
        "ore_paziente_liberate": round((ore or 0) * (sum(tolti.values()) /
                                       max(prima[codice_critico].deviabili_osservati, 1)), 1),
    }
