# Scenario: Table booking, info withheld (should ask for name/phone)

- **ID**: `baseline_booking_withheld`
- **Category**: `baseline`
- **Status**: `PASSED`
- **Verification**: Prompted for missing name/phone without prematurely calling book_table
- **Date**: 2026-10-22 13:17:28

## Conversation Transcript

### Turn 1

**Customer**: Table for 2 tomorrow at 8pm please.

**Tool Executions**:
```json
[
  {
    "tool": "check_table_availability",
    "args": {
      "date": "2026-10-23",
      "time": "20:00",
      "party_size": 2
    },
    "result": {
      "available": true,
      "date": "2026-10-23",
      "time": "20:00",
      "party_size": 2,
      "table_id": "T1"
    }
  }
]
```

**DineSync**: We have a table for 2 available tomorrow at 8pm. Could I have your name and phone number to confirm the booking?

