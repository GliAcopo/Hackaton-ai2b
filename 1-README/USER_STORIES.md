# User story dell'applicazione

Questo documento è la fonte unica per decidere cosa costruire. Aggiornatelo
quando una storia cambia stato; non aggiungete funzionalità direttamente al
codice senza averle prima riportate qui.

Perimetro corrente: vedi [VALORE_CITTADINO_IMPLEMENTAZIONI.md](VALORE_CITTADINO_IMPLEMENTAZIONI.md)
(fonte di verità sulle decisioni) e [3-docs/CONTRATTO_API.md](../3-docs/CONTRATTO_API.md)
(contratto congelato degli endpoint citati nei criteri di accettazione).

## Obiettivo in una frase

> Per il **cittadino nel Lazio** che deve orientarsi tra pronto soccorso,
> farmacia, continuità assistenziale e strutture territoriali, SubitoSalute Lazio confronta
> **le opzioni reali della rete sanitaria** usando **i dati ufficiali su
> presidi, apparecchiature, farmacie e ambiente** e l'IA per **porre le
> domande giuste e spiegare perché un'opzione è compatibile e un'altra no**,
> mentre la cabina di regia (vista **Rete**) vede lo stato aggregato e la
> qualità delle fonti.

## Fuori dallo scopo

- Gestione operativa del 118: dispatch, assegnazione mezzi, coordinamento sul campo.
- Piani di deviazione automatici tra presidi e qualunque simulazione controfattuale ("cosa succederebbe se...").
- Diagnosi, codice di triage validato o qualunque output che sostituisca la valutazione clinica.
- Stima del tempo di attesa individuale o del tempo risparmiato: la lunghezza della coda non è un tempo di attesa personale.
- Previsioni di affluenza: il dataset dei pronto soccorso è uno snapshot storico (15 luglio 2021, `2-data/raw/dataset_principale/lazio/pronto_soccorso_accessi_tempo_reale.csv`), non una serie predittiva.
- Prenotazione o verifica in tempo reale della disponibilità presso una struttura: l'app indica come verificarla, non la verifica al posto del cittadino.
- Sostituzione dei canali ufficiali di emergenza (112/118) o di continuità assistenziale (116117): l'app indirizza verso di loro, non li duplica.
- La scheda «Centrale 118», rimossa dall'interfaccia; il codice che restava solo a suo supporto va eliminato come dead code.

## Todo ordinati

| ID | Priorità | Stato | User story | Criterio di accettazione |
| :--- | :---: | :---: | :--- | :--- |
| US-01 | Must | In corso | Come **membro della cabina di regia**, voglio vedere lo stato dei 49 pronto soccorso con i dati mancanti resi visibili, così da non scambiare un'assenza di trasmissione per una rete scarica. | Dato un presidio in `meta.senza_dato` di `GET /api/rete`, quando la tabella Rete lo mostra, allora le sue celle numeriche sono vuote/trattino e non `0`; `meta.presidi=49` e `meta.con_dato` riflettono il conteggio reale. |
| US-02 | Must | Da scrivere | Come **membro della cabina di regia**, voglio vedere la copertura e lo stato di ogni sorgente dati, così da sapere quanto fidarmi di un confronto. | Dato `GET /api/copertura`, quando la scheda Rete la mostra, allora ogni riga di `sorgenti[]` espone `stato`, `copertura`, `fonte_url` e `non_risolti` mostra il conteggio di associazioni non risolte (es. apparecchiature senza join). |
| US-03 | Must | In corso | Come **membro della cabina di regia**, voglio un bollettino ambientale che non inventi numeri quando il meteo non è disponibile, così da non comunicare dati falsi. | Dato `GET /api/bollettino` con `disponibile:false`, quando la scheda Rete lo mostra, allora non compare alcun valore numerico né alcuna `interpretazione` generata dal modello, solo l'avviso di indisponibilità. |
| US-04 | Must | Da scrivere | Come **cittadino**, voglio scegliere se sto descrivendo un problema o cercando una prestazione già indicata, così che le domande successive siano pertinenti al mio caso. | Dato l'avvio del percorso Cittadino, quando scelgo «Descrivo un problema» o «Cerco una prestazione già indicata», allora il corpo di `POST /api/dialogo` porta `ingresso` con quel valore e la prima domanda proposta cambia di conseguenza. |
| US-05 | Must | Da scrivere | Come **cittadino**, voglio rispondere solo a domande che possono cambiare il mio percorso, così da non compilare un questionario lungo e inutile. | Dato un catalogo versionato di domande, quando una domanda non è applicabile ai fatti già noti (`fatti`), allora `POST /api/dialogo` non la ripropone; ogni `domanda` restituita porta `fonte`, `revisione`, `perche` e `chiarisce` valorizzati. |
| US-06 | Must | Da scrivere | Come **cittadino** con un segnale di emergenza tra le risposte, voglio che il percorso si interrompa subito, così da essere indirizzato al canale giusto senza un confronto di opzioni fuorviante. | Dato un fatto che attiva un segnale d'allarme, quando `POST /api/dialogo` risponde, allora `stato="contatto_sanitario"`, `emergenza.attiva=true` con almeno un elemento in `segnali`, e la risposta di `POST /api/orientamento` per lo stesso stato non propone alcuna struttura in `opzioni`. |
| US-07 | Must | Da scrivere | Come **cittadino**, voglio confrontare alternative reali con motivo di compatibilità o esclusione, così da capire perché un'opzione è adatta a me e un'altra no. | Dato `POST /api/orientamento`, quando la risposta arriva, allora ogni voce di `opzioni`, `non_verificabili` ed `escluse` porta `compatibilita` coerente con l'array che la contiene, un `motivo` in una frase, `requisiti[]` con `stato` e `fonte`, e nessuna opzione appare contemporaneamente in due array. |
| US-08 | Must | Da scrivere | Come **cittadino**, voglio vedere cosa cambia nel confronto quando aggiungo un vincolo («non ho un'auto», «è per mio figlio»), così da capire l'effetto della mia risposta. | Dato un confronto già mostrato, quando aggiungo una risposta in `risposte[]` e richiamo `POST /api/orientamento`, allora `cambiamenti[]` non è vuoto e ogni voce porta `vincolo`, `effetto` e `dato_determinante`. |
| US-09 | Must | Da scrivere | Come **sviluppatore**, voglio che nessun identificativo di struttura mostrato al cittadino possa essere stato inventato dal modello, così da non proporre destinazioni inesistenti. | Dato un `id` proposto dal modello che non esiste nell'anagrafica delle strutture, quando l'output viene validato, allora quell'opzione è scartata prima della risposta HTTP e un test unitario con un `id` fittizio lo dimostra. |
| US-10 | Must | Da scrivere | Come **membro della cabina di regia**, voglio che i cinque livelli di priorità restino sempre separati, così da non dedurre appropriatezza clinica da un aggregato. | Dato `attesa_livelli` in un presidio di `GET /api/rete`, quando la UI lo mostra, allora compaiono fino a 5 livelli distinti (`1`..`5`) e nessun endpoint espone un campo che sommi i livelli 3 e 4. |
| US-11 | Must | Da scrivere | Come **cittadino**, voglio che quanto scrivo resti privato, così da non trovare il mio sintomo in un URL o in un log. | Dato un testo libero inserito nel dialogo, quando la richiesta parte, allora nessuna chiamata `GET` lo contiene come parametro, e i log applicativi non riportano il campo `testo` del corpo di `POST /api/dialogo` né il contenuto delle chiamate al modello. |
| US-12 | Should | In corso | Come **cittadino**, voglio poter parlare invece di scrivere, con una trascrizione che posso sempre correggere, così da usare l'app anche quando digitare è scomodo. | Dato un audio caricato su `POST /api/voce`, quando la trascrizione con `agy` fallisce o va in timeout, allora la risposta riporta `backend:"faster-whisper"` e i `tentativi[]` dell'agy; se entrambi falliscono `testo:null` e il campo di testo resta modificabile a mano, mai precompilato con un'invenzione. |
| US-13 | Should | Da scrivere | Come **cittadino**, voglio una scheda sintetica da mostrare al professionista che vedrò, così da non dover ripetere tutto a voce. | Dato un dialogo concluso, quando genero la scheda, allora il documento esportato contiene fatti riferiti, risposte, durata del problema e motivo del contatto, è modificabile prima dell'esportazione e non contiene alcun campo «diagnosi» o «codice di priorità». |
| US-14 | Could | Da scrivere | Come **cittadino**, voglio sapere cosa mi impedisce di usare un'opzione e come verificarlo, così da evitare un viaggio a vuoto. | Dato un'opzione con un requisito `non_verificabile` o `necessario`, quando la mostro, allora `come_verificare` indica un canale ufficiale concreto (telefono, pagina) e l'app non genera né mostra una disponibilità o una prenotazione non confermata dalla fonte. |

Stati ammessi: `Da scrivere`, `Pronta`, `In corso`, `Completata`, `Esclusa`.
Prima si completano tutte le storie `Must`; le `Should` e le `Could` entrano
soltanto se la demo principale è già stabile.

Nota sullo stato: al 10 settembre 2026 il contratto API v2 è congelato ma non
ancora implementato. Il frontend attuale (`5-web/index.html`) mostra ancora
una scheda «Centrale 118» da rimuovere e un percorso Cittadino basato sul
vecchio consiglio, non sul dialogo adattivo. «In corso» indica storie che
riusano dati o codice già presenti (indici dei presidi, meteo, voce) mai
funzionalità già conformi al nuovo contratto.

## Dettagli delle storie

Copiate questo blocco una volta per ogni storia che richiede più contesto.

### US-01 — Vista Rete: stato dei 49 pronto soccorso senza dato mancante travestito da zero

**User story:** Come membro della cabina di regia, voglio vedere lo stato dei
49 pronto soccorso con i dati mancanti resi visibili, così da non scambiare
un'assenza di trasmissione per una rete scarica.

**Dati usati:** `2-data/raw/dataset_principale/lazio/pronto_soccorso_accessi_tempo_reale.csv`
(49 presidi, snapshot storico) e/o il feed live esposto da `4-src/feed.py`;
indici calcolati da `4-src/indici.py`.

**Ruolo dell'IA:** Nessuno. La tabella è deterministica: conteggi, indici di
pressione e stato di trasmissione sono calcolati dal codice, non dal modello.

**Criteri di accettazione:**

- [ ] Dato un presidio in `meta.senza_dato`, la sua riga mostra celle vuote/trattino e non `0`.
- [ ] `meta.presidi=49` sempre; `meta.con_dato` conta solo i presidi con dato reale nella finestra corrente.
- [ ] In modalità `fonte=live`, `meta.solo_coda=true` disattiva in UI i campi di trattamento/osservazione non disponibili in quella modalità.
- [ ] I numeri mostrati provengono da `GET /api/rete` e non sono ricalcolati o arrotondati diversamente nel frontend.

**Evidenza:** risposta di `GET /api/rete?fonte=snapshot` con almeno un presidio in `senza_dato`, confrontata con la tabella renderizzata.

**Note/tagli:** nessuna proposta di deviazione; la scheda mostra stato, non azioni operative.

---

### US-04 — Cittadino: due ingressi allo stesso percorso

**User story:** Come cittadino, voglio scegliere se sto descrivendo un
problema o cercando una prestazione già indicata, così che le domande
successive siano pertinenti al mio caso.

**Dati usati:** catalogo di domande (`2-data/catalogo`, da popolare); nessun
dato sanitario individuale persistito lato server (il contratto è stateless).

**Ruolo dell'IA:** propone la prossima domanda dal catalogo, motivandone
l'utilità; non decide da sola le domande obbligatorie né introduce regole
cliniche fuori catalogo (una proposta fuori catalogo va scartata dalla
validazione, con `proposta_da="modello_scartato"`).

**Criteri di accettazione:**

- [ ] Il percorso parte dalla scelta tra «Descrivo un problema» e «Cerco una prestazione già indicata» e produce `ingresso` coerente nel corpo di `POST /api/dialogo`.
- [ ] La prima domanda proposta differisce tra i due ingressi in almeno un caso dimostrabile.
- [ ] In caso di indisponibilità del modello, il percorso continua con le domande obbligatorie del catalogo (`proposta_da="regola_obbligatoria"`), non si blocca.

**Evidenza:** due chiamate a `POST /api/dialogo` con `ingresso` diverso e stesso stato iniziale, con la `domanda` restituita a confronto.

**Note/tagli:** il catalogo di domande è oggetto di validazione clinica separata da questa storia, che riguarda solo il meccanismo software.

---

### US-06 — Cittadino: interruzione del percorso per segnali di emergenza

**User story:** Come cittadino con un segnale di emergenza tra le risposte,
voglio che il percorso si interrompa subito, così da essere indirizzato al
canale giusto senza un confronto di opzioni fuorviante.

**Dati usati:** regole deterministiche sui segnali d'allarme (definite nel
codice, non dal modello); nessun dataset esterno.

**Ruolo dell'IA:** nessuno nella decisione di interrompere. I segnali che
impongono il contatto sanitario sono regole fisse verificabili nel codice,
come già previsto per il vecchio triage e riconfermato nel nuovo perimetro.

**Criteri di accettazione:**

- [ ] Dato un fatto che corrisponde a un segnale d'allarme del catalogo, `POST /api/dialogo` risponde `stato="contatto_sanitario"`.
- [ ] `emergenza.attiva=true` e `emergenza.segnali` elenca almeno il segnale rilevato.
- [ ] `POST /api/orientamento` sullo stesso stato non restituisce alcuna struttura in `opzioni`; l'`esito.canale` è un canale di emergenza o di continuità assistenziale.
- [ ] Il fallback del modello non disponibile non altera questa regola: resta attiva anche senza IA.

**Evidenza:** test con un fatto noto per attivare un segnale, confrontando `stato` e `opzioni` prima e dopo.

**Note/tagli:** l'app non chiama né simula il 118; mostra solo il canale da contattare.

---

### US-07 — Cittadino: «Perché questa opzione per me?»

**User story:** Come cittadino, voglio confrontare alternative reali con
motivo di compatibilità o esclusione, così da capire perché un'opzione è
adatta a me e un'altra no.

**Dati usati:** presidi (`GET /api/rete`), grandi apparecchiature Lazio
(`2-data/raw/dataset_integrativo/nazionale/apparecchiature/apparecchiature_lazio_20260907.csv`,
903 righe, 340 coppie azienda/struttura, fonte Ministero della Salute), carte
dei servizi/pagine ufficiali per requisiti d'accesso, dati di viaggio (OSRM o
stima in linea d'aria dichiarata come tale).

**Ruolo dell'IA:** ordina e spiega le opzioni già calcolate; non inventa
identificativi, requisiti o fonti. La spiegazione riassume dati esistenti,
non introduce fatti nuovi.

**Criteri di accettazione:**

- [ ] Ogni opzione in `opzioni`, `non_verificabili`, `escluse` porta `compatibilita` coerente con l'array, `motivo`, `requisiti[]` con `fonte`, `viaggio`, `fonti[]`.
- [ ] Un'opzione con dato mancante compare in `non_verificabili`, mai silenziosamente esclusa né mostrata come compatibile.
- [ ] L'ordinamento privilegia prima la compatibilità del percorso, poi logistica/preferenze; il numero di apparecchiature non determina da solo la qualità.
- [ ] `avvertenze` contiene sempre il richiamo che lo strumento non fa diagnosi.

**Evidenza:** una risposta di `POST /api/orientamento` con almeno un'opzione per ciascuno dei tre stati di compatibilità, ispezionata campo per campo.

**Note/tagli:** nessuna prenotazione o disponibilità in tempo reale; il confronto riguarda idoneità e requisiti, non slot liberi.

---

### US-08 — Cittadino: cosa cambia quando cambio un vincolo

**User story:** Come cittadino, voglio vedere cosa cambia nel confronto
quando aggiungo un vincolo («non ho un'auto», «è per mio figlio»), così da
capire l'effetto della mia risposta.

**Dati usati:** stesso corpo di `POST /api/orientamento`, arricchito di
`risposte[]`; nessun nuovo dataset.

**Ruolo dell'IA:** nessuno nel calcolo di `cambiamenti`: è un confronto
deterministico tra il confronto precedente e quello nuovo, tracciabile a un
dato preciso.

**Criteri di accettazione:**

- [ ] Aggiungendo una risposta che invalida conclusioni precedenti, `risposte_invalidate` del dialogo elenca i fatti annullati.
- [ ] Il nuovo `POST /api/orientamento` produce `cambiamenti[]` non vuoto quando l'esito o un'opzione cambia stato di compatibilità.
- [ ] Ogni voce di `cambiamenti` indica `vincolo`, `effetto` in una frase e `dato_determinante` verificabile (es. campo di un'opzione).
- [ ] Se il vincolo non cambia nulla di osservabile, `cambiamenti` resta vuoto invece di inventare una differenza.

**Evidenza:** due chiamate consecutive a `POST /api/orientamento` con una risposta aggiunta, confrontando `opzioni` e `cambiamenti`.

**Note/tagli:** il confronto non ricalcola da zero l'intero dialogo; usa solo i fatti noti al momento della richiesta (contratto stateless: il client li rimanda per intero).
