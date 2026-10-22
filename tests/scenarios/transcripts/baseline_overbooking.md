# Scenario: Overbooking a table that doesn't fit (12 people)

- **ID**: `baseline_overbooking`
- **Category**: `baseline`
- **Status**: `PASSED`
- **Verification**: Correctly declined overbooking beyond capacity
- **Date**: 2026-10-22 13:17:40

## Conversation Transcript

### Turn 1

**Customer**: Table for 12 tonight at 7, name Jordan, 07999888777.

**Tool Executions**:
```json
[
  {
    "tool": "check_table_availability",
    "args": {
      "date": "2026-10-22",
      "time": "19:00",
      "party_size": 12
    },
    "result": {
      "available": false,
      "date": "2026-10-22",
      "time": "19:00",
      "party_size": 12,
      "reason": "No table of sufficient size is free at that time."
    }
  }
]
```

**DineSync**: I'm sorry, we don't have a table available for 12 tonight at 7pm. Would you like to try a different time, or perhaps split into smaller groups? Let me know what works for you!

