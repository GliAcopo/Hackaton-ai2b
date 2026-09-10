# Catalogo e Documentazione Dataset

## Aggiunta del 10 settembre 2026: grandi apparecchiature

In `raw/dataset_integrativo/nazionale/apparecchiature/` sono disponibili:

- `DISPO_GAP_80_20260907.csv`: originale nazionale, 6.836 righe.
- `apparecchiature_lazio_20260907.csv`: filtro Lazio, 903 righe e 340 coppie azienda/struttura; codici conservati come stringhe.
- `provenienza.json`: URL, versione, licenza IODL 2.0, hash SHA-256 e limiti.

Fonte: [Ministero della Salute](https://www.dati.salute.gov.it/it/dataset/apparecchiature-sanitarie/). Il dato contiene tipologie, numerosità e localizzazione delle grandi apparecchiature. Non indica appuntamenti prenotabili, personale presente o disponibilità in tempo reale. Nessun collegamento automatico ai presidi dell'app è stato ancora eseguito.

La lista di correzioni e integrazioni concordate è in [Valore per il cittadino](../1-README/VALORE_CITTADINO_IMPLEMENTAZIONI.md).

I dataset sono stati organizzati secondo la suddivisione esatta della **Traccia**:

1. **`dataset_principale/`**: Portale Open Data Regione Lazio ([dati.lazio.it](https://dati.lazio.it/dataset/))
2. **`dataset_integrativo/`**: Portale Nazionale Open Data ([dati.gov.it](https://www.dati.gov.it/))

---

## 🏥 1. Dataset Principale: Regione Lazio (`raw/dataset_principale/lazio/`)
*Fonte: [dati.lazio.it](https://dati.lazio.it/dataset/)*  
*Obiettivo da traccia: "Cercare Pronto Soccorso, Posti letto o Strutture sanitarie per il censimento degli ospedali, ASL e carichi operativi."*

| File | Descrizione | Record | Colonne Principali | Finalità |
| :--- | :--- | :---: | :--- | :--- |
| **`pronto_soccorso_accessi_tempo_reale.csv`** | Carichi operativi in tempo reale nei Pronto Soccorso del Lazio | 49 presidi | `CODICE`, `ISTITUTO`, `TIPO`, `COMUNE`, `ASL`, `DATA`, `ROSSI_ATT`, `GIALLI_ATT`, `VERDI_ATT`, `BIANCHI_ATT`, `TOT_ATT`, `ROSSI_TRATT`, `GIALLI_TRATT`, `VERDI_TRATT`, `BIANCHI_TRATT`, `TOT_TRATT`, `ROSSI_OB`, `GIALLI_OB`, `VERDI_OB`, `TOT_OB`, `TOT_RT`, `TUTTI` | Monitoraggio saturazione PS, carichi per codice colore di gravità, tempi di attesa e stima indice di sovraffollamento |
| **`elenco_ospedali_lazio.csv`** | Censimento anagrafico ufficiale degli ospedali e stabilimenti del Lazio | 168 strutture | `Id_struttura`, `nome_struttura`, `comune`, `provincia`, `ASL`, `tipologia` | Mappatura completa della rete ospedaliera pubblica e convenzionata per ASL |
| **`strutture_sanitarie_private_accreditate.csv`** | Censimento delle strutture sanitarie private accreditate | 1.073 presidi | `ID_PR`, `ASL`, `RAGIONE SOCIALE`, `NOME PRESIDIO`, `TIPO DI PROVVEDIMENTO`, `ATTIVITA` | Identificazione dei centri specialistici e ambulatoriali convenzionati per l'assorbimento delle prestazioni |
| **`farmacie_regione_lazio.csv`** | Anagrafe delle farmacie territoriali con coordinate geografiche | 1.546 farmacie | `CODICEIDENTIFICATIVOFARMACIA`, `DESCRIZIONEFARMACIA`, `INDIRIZZO`, `CAP`, `DESCRIZIONECOMUNE`, `LATITUDINE`, `LONGITUDINE`, `CODFARMACIAASSEGNATODAASL` | **Medicina di prossimità**: reindirizzamento dei codici a bassa complessità (bianchi/verdi) verso presidi territoriali geolocalizzati |
| **`parafarmacie_regione_lazio.csv`** | Anagrafe delle parafarmacie territoriali del Lazio | 722 presidi | `CODICEIDENTIFICATIVOSITO`, `DENOMINAZIONESITOLOGISTICO`, `INDIRIZZO`, `CAP`, `DESCRIZIONECOMUNE`, `CODICEPROVINCIAISTAT` | Rete integrativa di presidi farmaceutici di primo intervento |
| **`ps_accessi_triage_storico.csv`** | Serie storica accessi PS per triage P.Re.Val.E. | 49 presidi | `NOME STRUTTURA`, `COMUNE`, `TOTALE ACCESSI`, `TRIAGE BIANCO (%)`, `TRIAGE VERDE (%)`, `TRIAGE GIALLO (%)`, `TRIAGE ROSSO (%)` | Baseline storica e calibrazione modelli di afflusso per codice triage |
| **`ps_durata_permanenza_storico.csv`** | Durata mediana di permanenza e tempi di attesa P.Re.Val.E. | 37 presidi | `NOME STRUTTURA`, `COMUNE`, `totale accessi`, `mediana tempo di permanenza`, `mediana tempo di attesa`, `permanenza < 12h (%)`, `permanenza > 48h (%)` | Efficienza operativa e colli di bottiglia dei presidi |
| **`meteo/termolug22.csv`** | Serie storiche temperature stazioni meteo della Regione Lazio | 5.301 rilievi | `Stazioni`, `Data`, `T-MIN`, `T-MAX` | Correlazione picchi termici estivi con sovraffollamento dei presidi sanitari |

---

## 📊 2. Dataset Integrativo: Portale Nazionale Open Data (`raw/dataset_integrativo/nazionale/`)
*Fonte: [dati.gov.it](https://www.dati.gov.it/)*  
*Obiettivo da traccia: "Cercare Tempi di attesa Lazio o Flussi sanitari regionali per serie storiche sulle prestazioni ambulatoriali."*

| File | Descrizione | Record | Colonne Principali | Finalità |
| :--- | :--- | :---: | :--- | :--- |
| **`tempi_attesa_ambulatoriali_correnti.csv`** | Monitoraggio ufficiale tempi di attesa per prestazioni specialistiche | 145 prestazioni | `prestazione`, `classe_priorita`, `Tempo mediano di attesa(gg)`, `N. prestazioni prenotate`, `performance` | Rispetto soglie massime per classi di priorità: **U** (72h), **B** (10gg), **D** (30/60gg), **P** (programmata) |
| **`tempi_attesa_ambulatoriali_storico.csv`** | Serie storica tempi mediani di attesa per prestazioni specialistiche | 173 prestazioni | `prestazione`, `classe_priorita`, `Tempo mediano di attesa(gg)`, `N. prestazioni prenotate`, `performance` | Analisi di serie storica, trend e stagionalità delle liste d'attesa |
| **`monitoraggio_tempi_attesa_settimanale.csv`** | Monitoraggio per settimana indice, ASL e codice tariffario prestazione | 414 rilevazioni | `ASL`, `ANNO`, `SETTIMANA_INDICE`, `ID_PRESTAZIONE`, `DESC_PRESTAZIONE`, `COD_PRESTAZIONE`, `PRENOTAZIONI`, `PRENOTAZIONI_DAGARANTIRE` | Granularità per ASL territoriale e codice prestazione specialistica |
| **`monitoraggio_tempi_attesa_luglio_2021.csv`** | Monitoraggio settimana indice estiva (luglio) | 414 rilevazioni | `ASL`, `ANNO`, `SETTIMANA_INDICE`, `ID_PRESTAZIONE`, `PRENOTAZIONI_DAGARANTIRE_B_TMAX`, `PRENOTAZIONI_DAGARANTIRE_D_TMAX` | Confronto del carico delle visite specialistiche durante i picchi estivi |
| **`flussi_ambulatoriali_ex_post.csv`** | Flussi sanitari erogazioni ambulatoriali da sistemi CUP | 828 rilevazioni | `REGIONE`, `ASL`, `ANNO`, `PERIODO_DI_RIFERIMENTO`, `DESC_PRESTAZIONE`, `EROGAZIONI` | Serie storiche trimestrali su volumi effettivamente erogati vs attese |
| **`tempi_attesa_presidi_specialistica.csv`** | Serie mensili dei tempi medi di attesa per presidio territoriale (STS) | 2.021 rilievi | `CODICE STS`, `DESCRIZIONE STS`, `CODICE CATALOGO`, `DESCRZIONE CATALOGO`, `GG ATTESA MEDI`, `MESE`, `ANNO` | Mappatura dell'offerta ambulatoriale di prossimità per presidio e giorni di attesa |
| **`catalogo_discipline_ambulatoriali.xlsx`** / **`catalogo_branche_ambulatoriali.xlsx`** | Catalogo e classificazione standard discipline e branche cliniche | - | Tabelle di codifica e decodifica | Nomenclatore e tassonomia delle prestazioni sanitarie ambulatoriali |

---

## ⚙️ Script di Automazione
In [`4-src/download_datasets.py`](../4-src/download_datasets.py) è disponibile lo script Python eseguibile per riscaricare o aggiornare i dati in modo riproducibile.
