# User story dell'applicazione

Questo documento è la fonte unica per decidere cosa costruire. Aggiornatelo
quando una storia cambia stato; non aggiungete funzionalità direttamente al
codice senza averle prima riportate qui.

## Obiettivo in una frase

> Per **[utente]**, che ha il problema **[X]**, l'applicazione fa **[Y]** usando
> **[dato]** e l'IA per **[Z]**.

## Fuori dallo scopee non chiamarli prompts

- [Da decidere]
- [Da decidere]
- [Da decidere]

## Todo ordinati

| ID | Priorità | Stato | User story | Criterio di accettazione |
| :--- | :---: | :---: | :--- | :--- |
| US-01 | Must | Da scrivere | Come **[utente]**, voglio **[azione]**, così da **[beneficio]**. | Dato **[contesto]**, quando **[azione]**, allora **[risultato osservabile]**. |

Stati ammessi: `Da scrivere`, `Pronta`, `In corso`, `Completata`, `Esclusa`.
Prima si completano tutte le storie `Must`; le `Should` e le `Could` entrano
soltanto se la demo principale è già stabile.

## Dettagli delle storie

Copiate questo blocco una volta per ogni storia che richiede più contesto.

### US-XX — Titolo breve

**User story:** Come **[utente]**, voglio **[azione]**, così da **[beneficio]**.

**Dati usati:** [dataset, file e colonne]

**Ruolo dell'IA:** [cosa decide o genera; cosa invece resta deterministico]

**Criteri di accettazione:**

- [ ] Il percorso parte da [input] e produce [output osservabile].
- [ ] I numeri mostrati provengono dai dati e non sono inventati dal modello.
- [ ] In caso di errore dell'IA, la demo continua con [fallback].

**Evidenza:** [test, comando, schermata o file che dimostra il completamento]

**Note/tagli:** [vincoli, casi esclusi e decisioni]
