# Pitch intermedio — scaletta per il presentatore

Perimetro aggiornato il 10 settembre 2026: vedi
[VALORE_CITTADINO_IMPLEMENTAZIONI.md](VALORE_CITTADINO_IMPLEMENTAZIONI.md) per
le decisioni e [3-docs/CONTRATTO_API.md](../3-docs/CONTRATTO_API.md) per il
contratto API congelato. La gestione operativa del 118, il dispatch e i piani
di deviazione sono usciti dal perimetro; la scheda «Centrale 118» è stata
rimossa dall'app. Restano due viste: **Rete** e **Cittadino**.

## I limiti, dichiarati prima di tutto

- SubitoSalute Lazio non fa diagnosi e non assegna un codice di triage validato: aiuta a
  capire quale canale può essere appropriato, la decisione clinica resta a un
  professionista.
- Non stimiamo il tempo risparmiato: non abbiamo un dato comparabile per
  farlo onestamente.
- La lunghezza della coda mostrata in **Rete** non è il tempo di attesa
  individuale di nessun cittadino specifico.
- Meno pazienti in attesa in un presidio non significa maggiore appropriatezza
  clinica delle sue prestazioni.
- Dato mancante non significa servizio assente: un presidio che non trasmette
  non è un presidio chiuso, e lo mostriamo distintamente.
- I cinque livelli di priorità dei pronto soccorso restano separati ovunque;
  non li aggreghiamo per farli sembrare più gestibili.
- Non produciamo valori meteo di fallback: se il dato ambientale manca, lo
  diciamo e basta.
- La riduzione di accessi impropri e il beneficio per il sistema sono ipotesi
  di lavoro, non risultati misurati su questo prototipo.

## Il problema e per chi

Una persona con un problema di salute, o con una prestazione già indicata da
un professionista, deve scegliere tra pronto soccorso, farmacia, continuità
assistenziale (116117) o una struttura territoriale. Le informazioni per
decidere esistono ma sono sparse tra fonti diverse, con formati e aggiornamenti
non omogenei. SubitoSalute Lazio le centralizza per spiegare le alternative reali e ciò che
resta da verificare, senza promettere la cura migliore in assoluto. Il
pubblico è chi descrive un sintomo e chi cerca già una prestazione: residenti,
visitatori, genitori e caregiver, con domande che si adattano al contesto
senza restringere l'app a una sola categoria di utenti.

## Le due viste

- **Rete** è il cruscotto della cabina di regia: stato dei 49 pronto soccorso
  del Lazio, copertura e qualità di ogni sorgente dati, freschezza del dato
  (fonte, acquisizione, lettura) e bollettino ambientale con distinzione tra
  bollettino ufficiale, misura e interpretazione. Non propone deviazioni: è
  uno stato leggibile, non uno strumento operativo.
- **Cittadino** è il percorso principale di orientamento alla cura, con
  un'esperienza tipo **HelpMe**: un dialogo che pone solo le domande che
  possono cambiare la scelta, poi un confronto di opzioni reali con «perché
  questa opzione per me».

## Dato contro interpretazione: come lo rendiamo verificabile

Ogni risposta distingue tre tempi — `istante_fonte` (quando il dato è vero
secondo chi lo pubblica), `acquisito_il` (quando lo abbiamo scaricato),
`letto_il` (quando questa risposta è stata costruita) — e, per ogni
affermazione verificabile, uno stato tra `confermato`, `escluso` e
`non_verificabile` più la sua fonte. Il client non porta mai un sintomo in un
URL o in un log: il testo libero viaggia solo nel corpo delle richieste POST,
e il server non conserva sessioni tra un giro di dialogo e l'altro.

## L'effetto wow concordato: «Perché questa opzione per me?»

Il cuore del percorso Cittadino è un confronto tra alternative reali —
prestazione, requisiti, orari documentati, accessibilità, viaggio, fonti —
diviso in tre gruppi: opzioni **compatibili**, **incompatibili** e **non
verificabili**. Un dato mancante non fa scomparire un'opzione né la fa
apparire disponibile: la mette semplicemente nel gruppo giusto, con scritto
cosa manca. Ogni opzione porta il motivo, in una frase, del perché è
compatibile o esclusa, senza esporre il ragionamento interno del modello.

Quando il cittadino aggiunge un vincolo — «non ho un'auto», «è per mio
figlio», «ho già una prescrizione» — il confronto si aggiorna e mostra cosa è
cambiato e quale dato lo ha determinato, non solo il nuovo risultato. Le
opzioni sono ordinate prima per compatibilità del percorso, poi per
preferenze e logistica tra le alternative appropriate: il numero di
apparecchiature di una struttura non viene usato come indicatore generale di
qualità.

Due estensioni dello stesso confronto, proposte ma non ancora implementate:
indicare cosa impedisce di usare un'opzione e come verificarlo presso il
canale ufficiale; mostrare quanto una proposta dipende da un dato vecchio o
mancante. Le presentiamo come tali, senza sostenere che manchino da ogni
servizio esistente.

## Dialogo adattivo

Due ingressi nello stesso percorso — «Descrivo un problema» e «Cerco una
prestazione già indicata» — portano a un catalogo versionato di domande, ognuna
con ID, condizioni di applicabilità, fonte e stato di revisione. Il modello
propone la prossima domanda scegliendola dal catalogo e motivandone l'utilità;
una proposta fuori catalogo viene validata e scartata se non è ammessa, senza
introdurre regole cliniche nuove. Non si ripetono domande già risposte, si può
rispondere «non so», correggere e tornare indietro; una correzione invalida
le conclusioni che ne dipendevano. Il percorso si ferma quando la scelta è
sufficientemente definita o quando non è determinabile: niente questionario
indefinito, niente risposta forzata. Un segnale d'allarme interrompe subito il
percorso e indirizza al canale sanitario appropriato, con regola fissa nel
codice, non nel modello.

## Voce

Registrazione dal browser o caricamento file, con limiti dichiarati di durata
e formato. Primo backend `agy` CLI, con fallback locale a `faster-whisper` in
caso di errore, timeout o input non supportato. La trascrizione resta sempre
visibile e correggibile prima dell'analisi — negazioni, numeri ed età possono
cambiarne il significato — e l'app mostra quale backend è stato realmente
usato. Se entrambi i backend falliscono, il testo resta da scrivere a mano:
non generiamo una trascrizione inventata.

## I dati che usiamo

- 49 pronto soccorso del Lazio, snapshot del 15 luglio 2021 (`2-data/raw/dataset_principale/lazio/pronto_soccorso_accessi_tempo_reale.csv`) più un feed live più povero di dettaglio (solo coda, non trattamento/osservazione).
- 903 righe di grandi apparecchiature sanitarie per il Lazio, 340 coppie azienda/struttura, filtrate dal dataset nazionale di 6.836 righe (Ministero della Salute, IODL 2.0, versione 07/09/2026) — un inventario, non slot prenotabili né indicazione clinica.
- 1.546 farmacie e 722 parafarmacie censite, 168 ospedali e 1.073 strutture private accreditate (anagrafiche, `2-data/README.md`) — un'anagrafe non basta da sola a dimostrare compatibilità: servono ancora requisiti e orari verificati.
- Tempi di attesa ambulatoriali storici e correnti (145–173 prestazioni, dataset nazionale) come baseline, non come appuntamenti disponibili.
- Bollettini caldo/ambientali di Salute Lazio e dati meteo/aria (open-meteo), sempre con fonte e distinzione tra ufficiale, misurato e interpretato; nessun valore di fallback inventato quando il dato manca.

Il join tra apparecchiature e presidi non è ancora eseguito: i codici
ministeriali restano stringhe, sede e azienda restano distinte, e le
associazioni non risolte vengono elencate, non nascoste.

## Come useremo l'IA, coerentemente con questi limiti

- Interpreta il testo libero del dialogo per proporre la prossima domanda utile, entro il catalogo validato.
- Spiega un confronto già calcolato dal sistema: non inventa identificativi di strutture, requisiti o fonti; ogni ID di destinazione è validato dopo l'output del modello.
- Interpreta il bollettino ambientale in gruppi vulnerabili e azioni pratiche, solo quando il dato di base è disponibile; se manca, non produce un'interpretazione.
- Non decide da sola le regole di sicurezza: i segnali che impongono il contatto sanitario e i controlli sui dati mancanti sono regole deterministiche nel codice.

## Stato del lavoro

Il contratto API v2 è congelato in `3-docs/CONTRATTO_API.md`. Le due viste
Rete e Cittadino, il dialogo adattivo, il confronto «perché questa opzione per
me» e la voce sono da implementare secondo quel contratto; l'inventario delle
apparecchiature Lazio è scaricato e verificato ma non ancora collegato ai
presidi. `1-README/USER_STORIES.md` elenca le storie ordinate per priorità e
il criterio con cui verificheremo ciascuna.
