# Scenario: Customer attempts to pre-order food for dine-in table reservation

- **ID**: `edge_mixing_booking_and_order`
- **Category**: `edge_case`
- **Status**: `PASSED`
- **Verification**: Addressed the table booking while clarifying food ordering policy
- **Date**: 2026-10-21 19:37:06

## Conversation Transcript

### Turn 1

**Customer**: Hi, can I book a table for 2 this Friday at 7pm under Alex, 07123456789? Also can we pre-order two burgers to be on the table when we arrive?

**Tool Executions**:
```json
[
  {
    "tool": "check_table_availability",
    "args": {
      "date": "2026-10-23",
      "time": "19:00",
      "party_size": 2
    },
    "result": {
      "available": true,
      "date": "2026-10-23",
      "time": "19:00",
      "party_size": 2,
      "table_id": "T1"
    }
  },
  {
    "tool": "book_table",
    "args": {
      "date": "2026-10-23",
      "time": "19:00",
      "party_size": 2,
      "customer_name": "Alex",
      "customer_phone": "07123456789"
    },
    "result": {
      "success": true,
      "reservation_id": "R0013",
      "id": "R0013",
      "table_id": "T1",
      "date": "2026-10-23",
      "time": "19:00",
      "party_size": 2,
      "name": "Alex",
      "phone": "07123456789",
      "status": "CONFIRMED",
      "created_at": "2026-10-21 19:37"
    }
  }
]
```

**DineSync**: Your table for 2 is booked this Friday at 7pm under Alex. For dine-in guests, food is ordered at the table upon arrival, so we can't pre-order burgers to be ready on the table. If you have any other requests, just let me know!

