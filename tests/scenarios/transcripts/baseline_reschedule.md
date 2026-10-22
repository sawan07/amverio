# Scenario: Reschedule an existing reservation

- **ID**: `baseline_reschedule`
- **Category**: `baseline`
- **Status**: `PASSED`
- **Verification**: Cancelled old booking and booked new time
- **Date**: 2026-10-22 13:17:49

## Conversation Transcript

### Turn 1

**Customer**: I'd like a table for 4 this Sunday at 8pm. Priya Shah, 07222 333444.

**Tool Executions**:
```json
[
  {
    "tool": "check_table_availability",
    "args": {
      "date": "2026-10-25",
      "time": "20:00",
      "party_size": 4
    },
    "result": {
      "available": true,
      "date": "2026-10-25",
      "time": "20:00",
      "party_size": 4,
      "table_id": "T4"
    }
  },
  {
    "tool": "book_table",
    "args": {
      "date": "2026-10-25",
      "time": "20:00",
      "party_size": 4,
      "customer_name": "Priya Shah",
      "customer_phone": "07222 333444"
    },
    "result": {
      "success": true,
      "reservation_id": "R0007",
      "id": "R0007",
      "table_id": "T4",
      "date": "2026-10-25",
      "time": "20:00",
      "party_size": 4,
      "name": "Priya Shah",
      "phone": "07222 333444",
      "status": "CONFIRMED",
      "created_at": "2026-10-22 13:17"
    }
  }
]
```

**DineSync**: Your table for 4 is booked for this Sunday, 25th October at 8pm under Priya Shah. We look forward to welcoming you! If you need to make any changes, just let us know.

### Turn 2

**Customer**: Actually can you move that to 9pm instead on the same day?

**Tool Executions**:
```json
[
  {
    "tool": "check_table_availability",
    "args": {
      "date": "2026-10-25",
      "time": "21:00",
      "party_size": 4
    },
    "result": {
      "available": true,
      "date": "2026-10-25",
      "time": "21:00",
      "party_size": 4,
      "table_id": "T3"
    }
  },
  {
    "tool": "cancel_reservation",
    "args": {
      "reservation_id": "R0007"
    },
    "result": {
      "success": true,
      "reservation_id": "R0007"
    }
  },
  {
    "tool": "book_table",
    "args": {
      "date": "2026-10-25",
      "time": "21:00",
      "party_size": 4,
      "customer_name": "Priya Shah",
      "customer_phone": "07222 333444"
    },
    "result": {
      "success": true,
      "reservation_id": "R0008",
      "id": "R0008",
      "table_id": "T3",
      "date": "2026-10-25",
      "time": "21:00",
      "party_size": 4,
      "name": "Priya Shah",
      "phone": "07222 333444",
      "status": "CONFIRMED",
      "created_at": "2026-10-22 13:17"
    }
  }
]
```

**DineSync**: Your table is now booked for 4 people at 9pm this Sunday, 25th October, under Priya Shah. The earlier reservation has been cancelled. See you then!

