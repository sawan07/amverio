# Scenario: Overbooking a table that doesn't fit (12 people)

- **ID**: `baseline_overbooking`
- **Category**: `baseline`
- **Status**: `PASSED`
- **Verification**: Correctly declined overbooking beyond capacity
- **Date**: 2026-10-21 19:36:09

## Conversation Transcript

### Turn 1

**Customer**: Table for 12 tonight at 7, name Jordan, 07999888777.

**Tool Executions**:
```json
[
  {
    "tool": "check_table_availability",
    "args": {
      "date": "2026-10-21",
      "time": "19:00",
      "party_size": 12
    },
    "result": {
      "available": false,
      "date": "2026-10-21",
      "time": "19:00",
      "party_size": 12,
      "reason": "That date/time has already passed."
    }
  }
]
```

**DineSync**: I'm sorry, but 7pm tonight has already passed. If you'd like to book for a later time this evening or another date, just let me know your preferred time!

