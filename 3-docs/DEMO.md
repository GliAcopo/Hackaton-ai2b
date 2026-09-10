# SubitoSalute Lazio — come si avvia e come si mostra

## Avvio

Dalla radice del repo. Non serve `pip install`, non serve rete per la demo.

```bash
python3 4-src/app.py                      # DEMO: snapshot 2021 + cache LLM  ← consigliato
python3 4-src/app.py --fonte live         # dati veri dei pronto soccorso
python3 4-src/app.py --live               # LLM interpellato davvero, cache ignorata
python3 4-src/app.py --fonte live --live  # tutto vivo
```

Poi: **http://localhost:8000** — Ctrl-C per fermare. Se la porta è occupata,
l'app chiude da sola l'istanza precedente.

**Quale usare davanti alla giuria.** `python3 4-src/app.py` senza argomenti: i
dati vengono dallo snapshot e le risposte del modello dalla cache, quindi la
demo gira anche con la rete staccata e risponde in millisecondi. La fonte in
tempo reale si può accendere **dal menù «Fonte rete» nell'interfaccia**, senza
riavviare: è il modo migliore per mostrarla, perché si vede il passaggio.

### Prima di presentare (30 secondi)

```bash
python3 4-src/prepara_demo.py --prova     # deve dire: "gira dalla sola cache"
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/   # 200
```

Se `--prova` fallisce, rigenera con `python3 4-src/prepara_demo.py` (serve rete,
circa un minuto) e ripeti la verifica.

## Il percorso da mostrare

### 1. Scheda Rete — 60 secondi

- I **tre tempi** in alto: dato della fonte / acquisito / letto. Dirlo ad alta
  voce: la fonte in tempo reale **non pubblica** l'istante, e lo dichiariamo
  invece di metterci l'ora nostra.
- **«Dove c'è meno coda»**: la stessa colonna letta dal lato del cittadino.
- **«?»** su una colonna → cosa è e come si calcola. Poi la **legenda dei
  colori** sotto la mappa.
- **«Dove sono io»** → la propria posizione fra i 49 presidi.
- In fondo: **copertura delle sorgenti**, con quante farmacie hanno una
  posizione attendibile e quante no.

### 2. Scheda Cittadino — 2 minuti, è il cuore

1. «Descrivo un problema», eventualmente dettando col microfono.
2. Rispondere alle domande: notare **«Perché me lo chiedi?»** e **«Modifica»**.
3. «Vedi le opzioni» → il confronto in **tre gruppi**: compatibili, **non
   verificabili**, escluse.
4. Aprire **«Fonti»** su una card: ogni affermazione ha origine e data.
5. Cambiare un vincolo («non ho un'auto») → **«Cosa è cambiato»**.

### Il momento da non perdere

Scrivere **«mio padre ha avuto un infarto dieci anni fa»**: nessun allarme, ma
il percorso segnala che il testo parla del **passato** e di **un'altra
persona**. Poi **«non ho dolore al petto»**: la ricerca per parole chiave
troverebbe «dolore al petto», e invece non scatta.

## Se qualcosa va storto

| Sintomo | Cosa fare |
| :--- | :--- |
| Una risposta tarda | Sei in `--live`: riavvia senza quel flag, la cache risponde subito |
| «dato ambientale non disponibile» | È corretto: la rete non c'è e **non inventiamo numeri**. Dillo, è un punto a favore |
| Il microfono non trascrive | Il testo resta scrivibile a mano: `stato()` dice quale backend c'era |
| La mappa non zooma con la rotella | Voluto: usa i bottoni **+** e **−**, o ctrl+rotella |

## Il confine, in una riga

Tutti i numeri sono calcolati in Python dagli open data. Il modello legge testo
libero, sceglie fra opzioni **già calcolate e validate**, e scrive la
motivazione. **Nessun numero mostrato passa dal modello**, e nessuna
destinazione può essere inventata: se il modello nomina una struttura che non
esiste fra le opzioni verificate, la proposta viene scartata e lo si dichiara.
