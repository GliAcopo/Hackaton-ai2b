1. Modello di previsione e indirizzamento per quando riguarda le risorse fisiche e umane
    - Per questo ci può essere utile una lista di attesa.
    - Utile sarebbe un interfacciamento con modelli meteo specifici di google in real time per prevedere ondate di calore, inondazioni e altre eventi
        - 
- Concettualmente la risposta del modello meteo sarebbe tipo:
```json
{
  "temperature": {
    "degrees": 31.2,
    "unit": "CELSIUS"
  },
  "feelsLikeTemperature": {
    "degrees": 33.1
  },
  "relativeHumidity": 68,
  "precipitation": {
    "probability": {
      "percent": 75
    }
  },
  "thunderstormProbability": 40,
  "wind": {
    "speed": 18,
    "gust": 35
  }
}
```
- Ma per la gravità del maltempo si può utilizzare una struttura ancora migliore, che ci darebbe direttamente allerte meteo:
```json
{
  "eventType": "FLASH_FLOOD",
  "severity": "SEVERE",
  "certainty": "LIKELY",
  "urgency": "IMMEDIATE",
  "instruction": [
    "..."
  ],
  "safetyRecommendations": [
    ...
  ]
}
```

Google definisce severity come enum:
```
EXTREME
SEVERE
MODERATE
MINOR
UNKNOWN
```
e separatamente:
```
certainty:
OBSERVED
VERY_LIKELY
LIKELY
POSSIBLE
UNLIKELY
UNKNOWN
```
e:
```
urgency:
IMMEDIATE
EXPECTED
FUTURE
PAST
UNKNOWN
```
