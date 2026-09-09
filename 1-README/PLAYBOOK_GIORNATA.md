# Playbook della giornata

## Cos'è davvero un hackathon

Non è una gara di programmazione. È una gara di **scelte sotto vincolo di
tempo**. Vince quasi sempre chi ha tagliato prima, non chi ha scritto di più.
La griglia AI2B lo dice esplicitamente: 20 punti su 50 (originalità +
presentazione) non si toccano scrivendo codice.

Il fallimento tipico del primo hackathon è sempre lo stesso: idea troppo
grande, tre ore per far girare l'infrastruttura, niente da mostrare alle 17.

## Timeline (adatta le ore all'orario reale della tappa)

| Ora | Cosa | Documento o prompt pronto | Perché |
| :--- | :--- | :--- | :--- |
| **0:00** | Sorteggio parola. **Non aprire l'editor.** | — | |
| **0:00–0:30** | Raccogliete e inventariate i dati ricevuti, poi guardate colonne, buchi e righe strane | [Prompt 00 — Organizzare i dataset](../../Prompts/PROMPT_00_ORGANIZZA_DATASET.md) | L'idea deve nascere dal dato, non prima |
| **0:30–1:00** | Data analysis: guardiamo i dati e decidiamo sul da farsi.<br>Definire la frase chiave: *"Per [utente], che ha il problema [X], la nostra app fa [Y] usando [dato] e l'IA per [Z]"* | [Prompt 01 — Idea per l'applicazione](../../Prompts/PROMPT_01_IDEA_APPLICAZIONE.md) | Se non entra in una frase non entra nel pitch |
| **1:00** | **Freeze dello scope.** Compilate e ordinate le [user story](USER_STORIES.md); scrivete anche le 3 cose che NON farete | [User story](USER_STORIES.md) | Il taglio deciso a freddo è l'unico che regge |
| **1:00–2:00** | Pipeline dati che gira end-to-end, anche brutta | — | Il rischio va scoperto presto |
| **2:00–3:30** | Integrazione IA: schema, prompt, primo output vero | — | |
| **3:30–4:30** | Interfaccia. Una schermata sola, fatta bene | — | |
| **4:30–5:00** | **Congelate il codice.** Cache degli output della demo | — | |
| **5:00–6:00** | Generate la [scaletta del pitch](SCALETTA_PITCH.md), preparate le slide e provate a voce alta col cronometro | [Prompt 02 — Scaletta del pitch](../../Prompts/PROMPT_02_SCALETTA_PITCH.md)<br>[Prompt 03 — PowerPoint e demo](../../Prompts/PROMPT_03_POWERPOINT_E_DEMO.md) | Mai la prima volta davanti alla giuria |

L'ultima ora sembra sprecata. Non lo è: vale 10 punti su 50.

## Ruoli (se siete in squadra)

- **Dati**: pulizia, join, indicatori. Consegna un JSON pulito, non un notebook.
- **IA**: prompt, schema, gestione errori e latenza.
- **Interfaccia + pitch**: e comincia le slide *presto*, non alle 16:30.

Da solo: stessi blocchi in sequenza, ma dimezza l'ambizione. Una funzione
sola che funziona benissimo batte tre abbozzate — è scritto nella guida
ufficiale, prendila alla lettera.

La traccia dettagliata della presentazione vive nel documento separato
[SCALETTA_PITCH.md](SCALETTA_PITCH.md), così il playbook operativo e il copione
non vengono confusi.

## Domande che la giuria fa quasi sempre

- "Dove finisce il dato e dove comincia l'IA?" → sappiate rispondere in una riga.
- "Cosa succede se il modello sbaglia?" → schema + fallback + il fatto che
  i numeri non passano dall'LLM.
- "Perché non basta una dashboard?" → perché la parola chiave cambia la
  logica, non il colore dei grafici.
- "Chi lo pagherebbe?" → un'ipotesi vale più di un silenzio.

## Checklist delle 9:00

- [ ] `ollama serve` attivo, `python3 4-src/llm.py` dice OK
- [ ] batteria, caricatore, hotspot del telefono
- [ ] repo git inizializzata, primo commit fatto
- [ ] chiesto agli organizzatori se ci sono API key
- [ ] nome del progetto deciso (3 minuti, poi basta)
