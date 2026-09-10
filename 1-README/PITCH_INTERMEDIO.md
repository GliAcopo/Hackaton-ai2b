# Pitch intermedio — scaletta per il presentatore

## Cosa stiamo facendo adesso

- Stiamo costruendo la base dati di REGIA, prima di collegare l'intelligenza artificiale.
- Stiamo ripulendo e collegando i dati dei 49 pronto soccorso del Lazio.
- Stiamo controllando per ogni dato: fonte, significato, unità di misura e data di aggiornamento.
- Stiamo aggiungendo coordinate e collegamenti geografici per confrontare strutture vicine.
- Stiamo calcolando con regole verificabili:
  - quali pronto soccorso sono più sotto pressione;
  - quanti accessi a bassa intensità possono essere eventualmente deviati;
  - quali strutture vicine hanno capacità residua;
  - quale sarebbe il costo del non intervenire, in ore di permanenza dei pazienti.
- Il primo risultato concreto è la scheda **Rete**:
  - elenco dei pronto soccorso ordinabile per diversi criteri;
  - dettaglio dei carichi e dei dati storici;
  - proposta di deviazione verso strutture alternative;
  - visualizzazione del percorso sulla mappa.
- Dopo aver reso solida questa base, colleghiamo gli stessi dati alla centrale 118 e alla vista per il cittadino.
- L'IA non inventa numeri e non decide da sola: interpreta testo libero, confronta opzioni già calcolate e spiega il motivo della proposta.
- I dati disponibili sono uno snapshot del 15 luglio 2021: non presentiamo previsioni come se fossero dati reali e mostriamo sempre fonte e timestamp.

## Come vogliamo integrare l'intelligenza artificiale

- **Riconoscimento dei sintomi del paziente**
  - Leggere la descrizione della chiamata o del sintomo scritto.
  - Estrarre i sintomi principali e le informazioni utili: età, condizioni riferite, dinamica e gravità.
  - Restituire un livello di confidenza e segnalare quando le informazioni non bastano.

- **Supporto al triage della centrale 118**
  - In base ai dati inseriti dall'operatore, proporre il codice di priorità e una sintesi della chiamata.
  - Evidenziare i segnali d'allarme, come dolore toracico, difficoltà respiratoria, perdita di coscienza, deficit neurologici o emorragia.
  - Indicare se può servire una struttura con DEA di secondo livello.
  - Ordinare le destinazioni possibili usando solo strutture e tempi già calcolati dal sistema.
  - La decisione resta all'operatore: i segnali d'allarme che impongono di chiamare il 118 sono regole fisse del sistema, non una libera interpretazione del modello.

- **Istruzioni di primo soccorso per l'operatore 118**
  - A partire da ciò che l'operatore sta raccogliendo, suggerire — quando possibile — la procedura immediata da comunicare al chiamante.
  - Esempi: tamponare una ferita con garza sterile, mantenere una posizione sicura, non somministrare cibo o farmaci, attendere i soccorsi.
  - Mostrare il grado di confidenza, le condizioni a cui si applica il consiglio e, quando disponibili, fonti o siti affidabili da consultare.
  - Non sostituire il protocollo del 118: il consiglio è un supporto operativo verificabile dall'operatore sanitario.

- **Piano di deviazione per la cabina di regia**
  - Analizzare il presidio in difficoltà, i candidati già ordinati dal sistema e le condizioni meteo.
  - Proporre quanta parte degli accessi a bassa intensità può essere indirizzata altrove, verso quali strutture e con quale urgenza.
  - Spiegare la motivazione e indicare le azioni operative, compreso l'effetto sulla rete dopo la deviazione.

- **Bollettino meteo-sanitario**
  - Incrociare allerte, meteo, temperatura percepita, qualità dell'aria e pollini.
  - Identificare i gruppi più esposti in quelle condizioni: per esempio over 65 durante il caldo, persone senza dimora durante il freddo, bambini e allergici con pollini elevati.
  - Generare consigli pratici per la protezione dei gruppi vulnerabili e messaggi da comunicare ai cittadini.
  - Suggerire anche la preparazione delle risorse: per esempio più coperte durante il freddo o più scorte di adrenalina e di altri farmaci previsti dai protocolli quando aumentano i pollini.

- **Consiglio personalizzato al cittadino**
  - Leggere il sintomo inserito dal cittadino e considerare la sua posizione.
  - Indicare se rivolgersi a pronto soccorso, struttura territoriale, farmacia o 118.
  - Motivare la scelta e proporre alternative vicine, usando gli indici e la situazione della rete già calcolati.
  - Se compare un segnale d'allarme, mostrare prima l'indicazione di chiamare il 118.

- **Spiegazione e tracciabilità**
  - Per ogni risposta, distinguere i dati numerici calcolati dal sistema dall'interpretazione dell'IA.
  - Registrare input, output, modello, timestamp e latenza, così da poter ricostruire perché è stata generata una proposta.

## Limiti che dichiariamo

- L'IA è un supporto alla decisione, non una diagnosi e non sostituisce il personale sanitario.
- Le soglie di sicurezza e le regole sui segnali d'allarme restano esplicite e controllabili nel codice.
- Se mancano dati o la confidenza è bassa, il sistema deve dirlo e chiedere una verifica umana.
- Nella demo non facciamo previsioni sull'affluenza: il dataset principale è uno snapshot e viene presentato come tale.
