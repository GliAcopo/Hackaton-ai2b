# Contratto API di SubitoSalute Lazio — v2 (perimetro «valore per il cittadino»)

Congelato il 2026-09-10. Sostituisce il contratto v1 (che aveva `/api/piano`,
`/api/triage`, `/api/simula`: **rimossi**, la gestione operativa del 118, il
dispatch e i piani di deviazione sono fuori perimetro).

Due sole viste: **Rete** (cabina di regia: stato, copertura, freschezza,
bollettino ambientale) e **Cittadino** (orientamento alla cura, dialogo
adattivo, confronto delle opzioni).

## Principi che il contratto impone

1. **Nessun sintomo in URL.** Ogni testo scritto dalla persona viaggia in un
   corpo POST. I GET non portano mai descrizioni cliniche.
2. **Stateless.** Il client rimanda a ogni giro lo stato completo del dialogo.
   Il server non conserva sessioni: niente da cancellare, niente da esporre.
3. **Tre tempi distinti**, mai confusi: `istante_fonte` (quando il dato è vero
   secondo chi lo pubblica; `null` se non pubblicato), `acquisito_il` (quando
   noi lo abbiamo scaricato), `letto_il` (quando questa risposta è stata
   costruita).
4. **Dato mancante ≠ dato negativo.** Ogni affermazione verificabile porta
   `stato ∈ {confermato, escluso, non_verificabile}` più la sua fonte.

---

## GET /api/rete?ordine=<chiave>&fonte=<snapshot|live>

Stato dei 49 pronto soccorso per la cabina di regia.

```jsonc
{
  "meta": {
    "fonte": "open data Regione Lazio (snapshot)",
    "fonte_tipo": "snapshot" | "live",
    "istante_fonte": "2021-07-15T16:58:00" | null,
    "acquisito_il": "2026-09-10T15:02:11",
    "letto_il":     "2026-09-10T15:02:11",
    "eta_dato_s": 0,                 // letto_il - acquisito_il, in secondi
    "da_cache": false,
    "istante_fonte_pubblicato": false,   // la API live NON pubblica un updatedAt
    "presidi": 49, "con_dato": 47, "senza_dato": ["..."],
    "solo_coda": true,               // live: nessun dato su trattamento/osservazione
    "avviso": "…"
  },
  "ordinamenti": { "attesa": "Più pazienti in attesa",
                   "meno_coda": "Meno persone in attesa adesso", "…": "…" },
  "legenda": { /* vedi sotto */ },
  "presidi": [ { /* Indici.to_dict(), vedi sotto */ } ]
}
```

Campi di un presidio rilevanti al frontend:
`codice, nome, tipo, comune, asl, lat, lon, in_attesa, presenti, pressione_relativa,
sofferenza_relativa, attesa_h, attesa_misurata, carico_deviabile, posti_residui,
senza_dato, in_allarme, note[], attesa_livelli`.

`attesa_livelli` **conserva i cinque livelli originali** e non li aggrega:

```jsonc
"attesa_livelli": [
  {"livello":"1","etichetta":"Emergenza","in_attesa":0,"attesa_media_h":0.0,"attesa_max_h":0.0},
  {"livello":"3","etichetta":"Urgenza Differibile","in_attesa":2,"attesa_media_h":0.62,"attesa_max_h":0.98}
]
```

### `legenda` — cosa vuol dire ogni numero

Le soglie e le formule vivono in `4-src/indici.py`; la legenda le espone
insieme ai dati, così una spiegazione non può divergere dal codice che
descrive. Il frontend colora i marcatori leggendo `colori`, non con soglie
proprie.

```jsonc
"legenda": {
  "colori": [
    {"classe":"ok","colore":"#2e7d32","fino_a":1.0,"etichetta":"Sotto la mediana della rete","significato":"…"},
    {"classe":"medio","colore":"#f9a825","fino_a":1.5,"etichetta":"Intorno alla mediana","significato":"…"},
    {"classe":"alto","colore":"#e53935","fino_a":null,"etichetta":"Sopra la soglia di allarme","significato":"…"},
    {"classe":"assente","colore":"#9e9e9e","fino_a":null,"etichetta":"Nessun dato","significato":"…"}
  ],
  "indicatori": [
    {"chiave":"pressione_relativa","nome":"Pressione","cosa_e":"…","come_si_calcola":"…",
     "come_si_legge":"…","unita":"x mediana della rete","limite":"…","disponibile_in":["snapshot"]}
  ],
  "indicatori_non_disponibili": [{"nome":"Pressione","motivo":"…"}],
  "soglia_allarme": 1.5,
  "nota_scala": "…"
}
```

### Ordinamenti: due lati della stessa colonna

Le chiavi che iniziano per `meno_` ordinano in senso CRESCENTE e rispondono
alla domanda del cittadino («dove conviene andare»), non a quella della cabina
di regia («dove si sta peggio»). Due regole valgono in entrambi i versi:

1. I valori `null` restano in fondo anche in ordine crescente: un campo non
   calcolabile non è il valore più piccolo, è un valore che non c'è.
2. Un presidio con `senza_dato` non compare mai in cima a un ordinamento
   `meno_`: la sua coda è zero perché non trasmette, non perché sia libero.

Gli ordinamenti si filtrano per CAMPO, non per nome: in tempo reale
l'occupazione non è calcolabile, quindi spariscono sia `pressione` sia
`meno_pressione`.

## GET /api/copertura

Qualità e provenienza di ogni sorgente. È la scheda «quanto è solida questa
scelta» a livello di sistema.

```jsonc
{
  "sorgenti": [
    {"nome":"Pronto soccorso — stato","stato":"attiva","copertura":"47/49 trasmettono",
     "istante_fonte":null,"acquisito_il":"…","limite":"…","fonte_url":"…"},
    {"nome":"Farmacie","stato":"parziale","copertura":"824/985 con posizione attendibile", …},
    {"nome":"Grandi apparecchiature","stato":"attiva","copertura":"903 righe, 340 strutture", …}
  ],
  "non_risolti": {"apparecchiature_senza_join": 12, "presidi_senza_coordinate": 0}
}
```

## GET /api/bollettino?lat=&lon=

Contesto ambientale, per la scheda **Rete**. Se il meteo non è disponibile la
risposta **non inventa numeri**: `disponibile:false` e nessun bollettino IA.

```jsonc
{
  "disponibile": true,
  "meteo": {"temperatura_c":29.4, "…":"…", "fonte":"open-meteo"|"cache", "istante_fonte":"…"},
  "aria":  {"pm10":18.0, "…":"…", "fonte":"open-meteo"},
  "bollettino_ufficiale": {"presente":false, "nota":"…", "fonte_url":"…"},
  "interpretazione": { /* output IA, assente se disponibile=false */ },
  "livelli_di_prova": {
     "misurato":       ["temperatura_c","percepita_c","pm10","pm2_5","pollini"],
     "ufficiale":      [],
     "interpretazione":["rischi","gruppi_vulnerabili","azioni_pratiche","messaggio"]
  }
}
```

## POST /api/dialogo

Il dialogo adattivo. Corpo della richiesta = **stato completo**:

```jsonc
{
  "ingresso": "problema" | "prestazione",
  "testo": "descrizione libera, facoltativa",
  "risposte": [ {"id":"destinatario","valore":"figlio"}, {"id":"eta_fascia","valore":"non_so"} ],
  "posizione": {"lat":41.89,"lon":12.48} | null,
  "usa_modello": true
}
```

Risposta:

```jsonc
{
  "catalogo": {"versione":"1.0.0","aggiornato_il":"2026-09-10","domande":24},
  "stato": "in_corso" | "sufficiente" | "non_determinabile" | "contatto_sanitario",
  "domanda": {"id":"durata","testo":"…","tipo":"scelta"|"testo"|"numero",
              "opzioni":[{"valore":"oggi","etichetta":"Da oggi"}],
              "ammette_non_so":true,"perche":"…","chiarisce":"…",
              "fonte":"…","revisione":"…"} | null,
  "proposta_da": "regola_obbligatoria" | "modello" | "modello_scartato" | "catalogo",
  "motivo_proposta": "…",
  "scarto_modello": {"id_proposto":"…","motivo":"fuori catalogo"} | null,
  "fatti": {"destinatario":"figlio","eta_fascia":null},
  "risposte_invalidate": ["mobilita"],       // una correzione ha annullato queste
  "emergenza": {"attiva":false,"segnali":[],"avviso":"…","limite":"…"},
  "restanti_utili": 2
}
```

`stato = "contatto_sanitario"` interrompe il percorso: l'app mostra il canale da
contattare e **non** propone strutture.

## POST /api/orientamento

Stesso corpo di `/api/dialogo`. Produce il confronto «perché questa opzione per me».

```jsonc
{
  "meta": { /* come /api/rete */ },
  "esito": {
    "canale": "emergenza_112_118" | "pronto_soccorso" | "continuita_assistenziale_116117"
            | "struttura_territoriale" | "farmacia" | "medico_di_famiglia" | "non_determinabile",
    "titolo": "…",
    "spiegazione": "…",
    "deciso_da": "regola di sicurezza" | "regole deterministiche" | "modello entro le opzioni",
    "certezza": "alta" | "media" | "dichiaratamente_incerta",
    "cosa_manca": ["…"]
  },
  "opzioni":          [ /* Opzione, compatibili, ordinate per compatibilità poi logistica */ ],
  "non_verificabili": [ /* Opzione */ ],
  "escluse":          [ /* Opzione, con motivo_esclusione */ ],
  "cambiamenti": [ {"vincolo":"senza_auto","effetto":"…","dato_determinante":"…"} ],
  "avvertenze": ["Questo strumento non fa diagnosi…"]
}
```

### Oggetto `Opzione`

```jsonc
{
  "id": "ps:90401",                        // stabile, validato: il modello non può inventarlo
  "nome": "Policlinico Casilino",
  "genere": "pronto_soccorso"|"farmacia"|"struttura_accreditata"|"canale_telefonico"|"medico_di_famiglia",
  "compatibilita": "compatibile"|"incompatibile"|"non_verificabile",
  "motivo": "…",                            // perché sì / perché no, in una frase
  "requisiti": [
    {"cosa":"prescrizione","stato":"necessario"|"non_necessario"|"non_verificabile",
     "come_verificare":"…","fonte":{"nome":"…","url":"…","data":"…"}}
  ],
  "viaggio": {"distanza_km":3.2,"durata_min":11.0,"fonte":"OSRM"|"stima in linea d'aria",
              "senza_auto":"non_verificabile"},
  "coda": {"in_attesa":14,"livelli":[…],"nota":"lunghezza della coda, non tempo di attesa personale"},
  "dotazione": [{"tipo":"TAC","num":2,"fonte":"Ministero della Salute 2026-09-07"}],
  "fonti": [{"nome":"…","url":"…","data":"…","come_verificato":"…"}]
}
```

## POST /api/voce

`multipart/form-data` con un solo campo `audio`. Risposta:

```jsonc
{"testo":"…"|null, "backend":"agy"|"faster-whisper"|null,
 "tentativi":[{"backend":"agy","esito":"non supportato: nessun argomento audio"}],
 "durata_s":4.2, "limite":"…", "errore":null|"…"}
```

Con `testo:null` il frontend **lascia il testo manuale** e non inventa nulla.

## GET /api/health

`{"llm":"…","voce":{"agy":…,"faster_whisper":…,"whisper_bin":…},"catalogo":…}`

`voce.faster_whisper.interprete` dice in QUALE interprete la libreria è
disponibile: su questa macchina è un virtualenv separato
(`~/whisper/.venv`), invocato in un sottoprocesso. `motivo` dichiara anche se
il modello è già scaricato, perché un primo uso che deve scaricarlo richiede
rete e tempo.
