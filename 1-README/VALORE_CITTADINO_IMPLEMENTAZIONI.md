# REGIA: valore per il cittadino e lista di implementazioni

Decisioni concordate il 10 settembre 2026. Questo documento specifica il lavoro da fare; le caselle aperte non indicano funzionalità già implementate. Non è una timeline.

## Proposta di valore

REGIA centralizza informazioni sanitarie e territoriali per aiutare il cittadino a trovare un percorso di assistenza appropriato e concretamente accessibile, spiegando le alternative e ciò che resta da verificare.

L'app serve sia chi descrive un sintomo sia chi ha già una prestazione da cercare. È destinata a residenti, visitatori, genitori e caregiver: il contesto individuale modifica le domande, senza restringere il pubblico a una sola categoria.

## Correzioni e cambiamenti necessari

- [ ] Eliminare dal prodotto e dal pitch la gestione operativa del 118, il dispatch e i piani di deviazione. Conservare l'indicazione dei canali di emergenza quando pertinente al percorso del cittadino.
- [ ] Riprogettare completamente le tre schede dell'interfaccia — **Rete**, **Centrale 118** e **Cittadino** — prima di implementare nuove funzionalità:
  - **Rete** deve diventare la dashboard della cabina di regia: raccogliere in modo più pulito e leggibile le informazioni oggi distribuite nell'app, compresi dati di rete, copertura, freschezza e bollettini ambientali.
  - **Cittadino** deve diventare il percorso principale di orientamento alla cura, con un'esperienza tipo **HelpMe**: aiutare la persona a capire quale canale o prestazione può essere appropriato e concretamente accessibile, senza promettere diagnosi o la migliore cura in assoluto.
  - **Centrale 118** deve essere rimossa dall'interfaccia e dal relativo codice: la gestione operativa del 118, il dispatch e i piani di deviazione sono fuori perimetro e ciò che resta non utilizzato va eliminato come dead code. Nel percorso Cittadino si possono mantenere soltanto i riferimenti ai canali di emergenza quando pertinenti.
- [ ] Spostare nella scheda **Rete** le informazioni meteo e sui rischi che oggi vengono mostrate in **Cittadino**. La loro presentazione deve essere riprogettata in una forma più utile al cittadino: indicazione territoriale comprensibile, azioni pratiche e pertinenti, eventuali gruppi vulnerabili e canale da contattare, sempre con fonte, data/ora e distinzione tra bollettino ufficiale, dato meteo e interpretazione. Non usare il meteo per dedurre la causa dei sintomi né per produrre allerte con dati inventati o insufficienti.
- [ ] Aggiornare USER_STORIES.md e PITCH_INTERMEDIO.md coerentemente con questo perimetro prima di implementare le nuove funzionalità.
- [ ] Non promettere diagnosi, codice di triage validato o la migliore cura in assoluto. Distinguere orientamento, prestazione già indicata da un professionista e scelta logistica della struttura.
- [ ] Eliminare la richiesta al modello di quantificare il tempo risparmiato senza dati comparabili. La lunghezza della coda non è il tempo di attesa individuale; una media pubblicata non è una previsione personale.
- [ ] Non interpretare meno pazienti in attesa come maggiore appropriatezza clinica.
- [ ] Correggere il fallback del consiglio: modello non disponibile o informazioni insufficienti non devono produrre automaticamente una destinazione territoriale rassicurante.
- [ ] Validare gli identificativi delle destinazioni dopo l'output del modello; nomi e alternative non devono poter essere inventati.
- [ ] Rivedere il controllo per parole chiave: negazioni, sinonimi, soggetto e temporalità non sono gestiti dalla semplice ricerca di sottostringhe. Nessuna corrispondenza non significa assenza di rischio.
- [ ] Distinguere timestamp della fonte, acquisizione e cache. Il feed attuale assegna l'ora corrente anche a letture recuperate dalla cache.
- [ ] Non usare valori meteo di fallback inventati per produrre consigli o allerte reali. Distinguere bollettino ufficiale, dati da modello meteo e interpretazione dell'IA.
- [ ] Conservare separati i cinque livelli di priorità originali per gli usi nuovi: aggregare livelli 3 e 4 non dimostra che i casi siano trattabili fuori dal PS.
- [ ] Evitare sintomi in URL e registri ordinari; minimizzare e rendere esplicita la conservazione di testo e audio. Il codice corrente registra anche contenuti delle chiamate al modello.

## Dialogo adattivo: domande che cambiano la scelta

- [ ] Due ingressi nello stesso percorso: «Descrivo un problema» e «Cerco una prestazione già indicata».
- [ ] Catalogo versionato di domande con ID, testo, risposte ammesse, condizioni di applicabilità, dipendenze, priorità, fonte, stato di revisione e informazione che la risposta chiarisce.
- [ ] Regole deterministiche per domande obbligatorie applicabili, coerenza delle risposte e interruzione del percorso quando occorre contatto sanitario.
- [ ] Modello che propone la prossima domanda tra ID del catalogo, motivandone l'utilità. Una proposta fuori catalogo deve passare validazione; non deve introdurre autonomamente regole cliniche.
- [ ] Non ripetere domande già risposte; permettere «non so», correzione e ritorno indietro. Una risposta corretta invalida le conclusioni dipendenti.
- [ ] Chiedere solo informazioni che possono cambiare il percorso; non sottoporre a tutti l'intero catalogo.
- [ ] Raccogliere, quando pertinenti: destinatario dell'assistenza, età/fascia, durata ed evoluzione del problema, informazioni cliniche previste da protocolli revisionati; per la logistica: posizione, mobilità, lingua, accompagnatore, prescrizione e vincoli di accesso.
- [ ] Fermarsi quando la scelta è sufficientemente definita oppure non è determinabile: niente questionario indefinito e niente risposta forzata.
- [ ] Separare validazione del software da validazione clinica del catalogo e dei percorsi. Testare casi ambigui, negazioni, informazioni mancanti, correzioni e indisponibilità del modello.

## Effetto wow concordato: «Perché questa opzione per me?»

- [ ] Confrontare alternative reali con prestazione, requisiti, orari documentati, accessibilità, viaggio e fonti.
- [ ] Distinguere opzioni compatibili, incompatibili e non verificabili: dato mancante non significa servizio assente o presente.
- [ ] Mostrare motivazione concreta della proposta e dell'esclusione delle alternative, senza esporre ragionamenti interni del modello.
- [ ] Aggiornare il confronto quando il cittadino cambia un vincolo: «non ho un'auto», «è per mio figlio», «ho già una prescrizione».
- [ ] Mostrare cosa è cambiato rispetto alla risposta precedente e quale dato ha determinato il cambiamento.
- [ ] Ordinare prima per compatibilità del percorso; usare preferenze e logistica soltanto tra alternative appropriate. Non premiare il numero di apparecchiature come qualità generale.
- [ ] Consentire di aprire fonte, data e modalità di verifica per ogni affermazione rilevante.

## Altri effetti wow proposti, da distinguere dalle decisioni già approvate

1. **«Cosa mi impedisce di usare questa opzione?»** L'app individua il requisito mancante — prenotazione, prescrizione, conferma dell'orario — e mostra come verificarlo tramite il canale ufficiale. Valore: ridurre viaggi a vuoto. Nessuna prenotazione o disponibilità inventata.
2. **«Quanto è solida questa scelta?»** Confronto che mostra se la proposta dipende da un dato vecchio o mancante, e quale verifica potrebbe cambiarla. Se tutte le opzioni dipendono da informazioni ignote, l'app lo dichiara. Valore: far vedere qualità e limiti della centralizzazione dei dati.
3. **Scheda da portare al professionista.** Sintesi modificabile dei fatti riferiti, risposte, durata del problema e motivo del contatto, esportabile e traducibile senza aggiungere diagnosi. Valore: continuità tra orientamento digitale e assistenza umana.

Non affermare che queste funzioni siano assenti da ogni servizio esistente: dimostrare il comportamento del prototipo e fare confronti circoscritti con funzionalità verificate.

## Voce: agy CLI con fallback faster-whisper

- [ ] Registrazione dal browser e caricamento file; limiti di durata/dimensione, formati ammessi e segnalazione della destinazione dell'audio.
- [ ] Primo backend agy CLI come richiesto dall'utente. La CLI è installata, ma `agy --help` non documenta un argomento audio: verificare il vero meccanismo di allegato prima di dichiarare l'integrazione pronta. Passare solo il percorso nel prompt non prova che il modello abbia ricevuto l'audio.
- [ ] Fallback locale faster-whisper su errore, timeout o input non supportato; verificare ambiente Python, modello disponibile e funzionamento offline su questo PC.
- [ ] File temporanei con nomi generati dal server, nessuna interpolazione shell del testo o nome originale, pulizia anche in caso di errore.
- [ ] Trascrizione visibile e correggibile prima dell'analisi: negazioni, numeri ed età possono cambiare il significato.
- [ ] Mostrare il backend realmente usato; in caso di doppio fallimento lasciare il testo manuale e non inventare una trascrizione.
- [ ] Verificare su audio italiano reale e casi con negazioni; non considerare una risposta plausibile del modello una prova di trascrizione riuscita.

## Dati da integrare

| Dati | Decisione migliorata | Fonte / stato | Limite da mantenere |
| --- | --- | --- | --- |
| Grandi apparecchiature per struttura | Dotazione documentata pertinente a una prestazione già indicata | Ministero della Salute, scaricato originale e filtro Lazio | Inventario, non slot, personale, urgenza o indicazione clinica |
| Prestazioni per sede, popolazione assistita e modalità di accesso | Compatibilità reale tra bisogno e struttura | Carte dei servizi e pagine ufficiali ASL/strutture; cataloghi già presenti da verificare | Un'anagrafe o accreditamento non basta |
| Orari, turni e contatti di farmacie e servizi territoriali | Evitare strutture chiuse e verificare il servizio | Fonti ufficiali ASL e farmacie; feed da individuare | Nessuna copertura live ancora accertata |
| Case della Comunità e ambulatori effettivamente operativi | Alternative territoriali al PS | Regione/ASL, da censire e verificare per sede | Struttura programmata non equivale a servizio aperto |
| Requisiti: ricetta, prenotazione, SSN/privato, canale ufficiale | Percorso utilizzabile e costi comprensibili | Regione/ASL/struttura | Non dedurre accesso SSN dalla sola proprietà o accreditamento |
| Attese ambulatoriali per sede/prestazione | Confronto informato per prestazioni già indicate | Dataset già presenti in 2-data da ispezionare e collegare | Medie storiche non sono appuntamenti disponibili |
| Accessibilità e trasporti | Opzioni praticabili senza auto o con mobilità limitata | Gestori ufficiali, dati GTFS ove disponibili, schede strutture | Verificare copertura; distanza in linea d'aria non è percorso |
| Bollettini caldo e allerte ufficiali | Contesto territoriale e messaggi pertinenti | Salute Lazio, protezione civile; integrare con meteo già presente | Non dedurre la causa dei sintomi dal meteo |
| Eventi cittadini, chiusure e viabilità | Accessibilità in occasione di grandi eventi | Roma Capitale e gestori mobilità, fonti da individuare | Evento non dimostra un picco sanitario |
| Informazioni ufficiali 116117 e continuità assistenziale | Collegamento a orientamento umano quando necessario | Regione Lazio / Salute Lazio | Non duplicare o simulare il servizio |

L'inventario delle apparecchiature non descrive ogni ospedale né ogni attrezzatura. Il join deve preservare i codici ministeriali come stringhe, distinguere sede e azienda, controllare indirizzi e produrre un elenco di associazioni non risolte. Nessun fuzzy match non verificato deve influenzare consigli.

## Aderenza al territorio ed evidenza per la giuria

- [ ] Dimostrare un caso nel Lazio in cui servizi effettivi, requisiti o mobilità cambiano la risposta. Una mappa con nomi locali da sola non basta.
- [ ] Collegare il bollettino al contesto quando pertinente, senza aggiungerlo artificialmente a ogni risposta.
- [ ] Confrontare il percorso con le funzioni documentate di Salute Lazio e 116117: il beneficio candidato è integrare informazioni, chiarire vincoli e spiegare il confronto.
- [ ] Misurare sul prototipo destinazioni inesistenti, incompatibilità riconosciute, gestione dei dati mancanti, utilità delle domande e latenza; distinguere questi risultati da accuratezza clinica e impatto sanitario reale.
- [ ] Presentare riduzione di accessi impropri, tempo risparmiato e beneficio al sistema come ipotesi finché non misurati.

## Fonti verificate e stato del lavoro

- [Dataset apparecchiature](https://www.dati.salute.gov.it/it/dataset/apparecchiature-sanitarie/), IODL 2.0, versione 07/09/2026.
- [Dizionario apparecchiature](https://www.dati.salute.gov.it/dati/documenti/ID_80_Dataset_Apparecchiature_Sanitarie_v2.0.pdf).
- [116117 nel Lazio](https://www.regione.lazio.it/notizie/salute-attivo-in-tutta-la-regione-il-numero-116117).
- [Ondate di calore 2026](https://salutelazio.it/it/salute-lazio-comunica/ondate-di-calore-2026).

Completato in questo aggiornamento: lista di lavoro, download inventario nazionale (6.836 righe), estratto Lazio (903 righe, 340 coppie azienda/struttura), provenienza e hash. Una riga rappresenta una combinazione censita di struttura e dotazione, non necessariamente una singola macchina. Integrazione nel motore di scelta, dialogo adattivo, UI e voce restano da implementare.
