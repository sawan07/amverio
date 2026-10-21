# Scenario: Ambiguous date/time ('next weekend')

- **ID**: `edge_ambiguous_datetime`
- **Category**: `edge_case`
- **Status**: `PASSED`
- **Verification**: Clarified ambiguous date/time in turn 1 and booked in turn 2
- **Date**: 2026-10-21 19:36:38

## Conversation Transcript

### Turn 1

**Customer**: I want a table for 4 next weekend in the evening. Alex, 07123456789.

**DineSync**: Could you please specify the exact date and time you'd like to book for next weekend? That way, I can check availability for your table for 4.

### Turn 2

**Customer**: Let's do Saturday at 7pm.

**Tool Executions**:
```json
[
  {
    "tool": "check_table_availability",
    "args": {
      "date": "2026-10-24",
      "time": "19:00",
      "party_size": 4
    },
    "result": {
      "available": true,
      "date": "2026-10-24",
      "time": "19:00",
      "party_size": 4,
      "table_id": "T3"
    }
  },
  {
    "tool": "book_table",
    "args": {
      "date": "2026-10-24",
      "time": "19:00",
      "party_size": 4,
      "customer_name": "Alex",
      "customer_phone": "07123456789"
    },
    "result": {
      "success": true,
      "reservation_id": "R0010",
      "id": "R0010",
      "table_id": "T3",
      "date": "2026-10-24",
      "time": "19:00",
      "party_size": 4,
      "name": "Alex",
      "phone": "07123456789",
      "status": "CONFIRMED",
      "created_at": "2026-10-21 19:36"
    }
  }
]
```

**DineSync**: Your table for 4 is booked for Saturday, 24th October at 7pm under the name Alex. We look forward to welcoming you! If you need to make any changes, just let us know.

