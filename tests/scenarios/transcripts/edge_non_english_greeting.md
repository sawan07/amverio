# Scenario: Non-English greeting and inquiry

- **ID**: `edge_non_english_greeting`
- **Category**: `edge_case`
- **Status**: `PASSED`
- **Verification**: Welcomed politely in English and processed table inquiry
- **Date**: 2026-10-21 19:37:08

## Conversation Transcript

### Turn 1

**Customer**: Bonjour! Avez-vous une table pour 2 ce soir à 19h? Je m'appelle Jean Dupont, 07123456789.

**Tool Executions**:
```json
[
  {
    "tool": "check_table_availability",
    "args": {
      "date": "2026-10-21",
      "time": "19:00",
      "party_size": 2
    },
    "result": {
      "available": false,
      "date": "2026-10-21",
      "time": "19:00",
      "party_size": 2,
      "reason": "That date/time has already passed."
    }
  }
]
```

**DineSync**: Bonsoir Jean, malheureusement il n'est plus possible de réserver pour ce soir à 19h, car l'heure est déjà passée. Souhaitez-vous une table pour plus tard ce soir, ou pour une autre date ?

