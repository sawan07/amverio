# Scenario: Party size changes mid-conversation

- **ID**: `edge_party_size_change`
- **Category**: `edge_case`
- **Status**: `PASSED`
- **Verification**: Adjusted party size to 4 and checked/booked for 4
- **Date**: 2026-10-22 13:18:11

## Conversation Transcript

### Turn 1

**Customer**: Can I book a table for 2 this Friday at 7pm? Jordan Blake, 07111222333.

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
      "table_id": "T2"
    }
  },
  {
    "tool": "book_table",
    "args": {
      "date": "2026-10-23",
      "time": "19:00",
      "party_size": 2,
      "customer_name": "Jordan Blake",
      "customer_phone": "07111222333"
    },
    "result": {
      "success": true,
      "reservation_id": "R0011",
      "id": "R0011",
      "table_id": "T2",
      "date": "2026-10-23",
      "time": "19:00",
      "party_size": 2,
      "name": "Jordan Blake",
      "phone": "07111222333",
      "status": "CONFIRMED",
      "created_at": "2026-10-22 13:18"
    }
  }
]
```

**DineSync**: Your table for 2 is booked this Friday at 7pm under Jordan Blake. We look forward to welcoming you! If you need to make any changes, just let us know.

### Turn 2

**Customer**: Actually wait, two more friends are joining us, make it 4 people instead please.

**Tool Executions**:
```json
[
  {
    "tool": "check_table_availability",
    "args": {
      "date": "2026-10-23",
      "time": "19:00",
      "party_size": 4
    },
    "result": {
      "available": true,
      "date": "2026-10-23",
      "time": "19:00",
      "party_size": 4,
      "table_id": "T4"
    }
  },
  {
    "tool": "cancel_reservation",
    "args": {
      "reservation_id": "R0011"
    },
    "result": {
      "success": true,
      "reservation_id": "R0011"
    }
  },
  {
    "tool": "book_table",
    "args": {
      "date": "2026-10-23",
      "time": "19:00",
      "party_size": 4,
      "customer_name": "Jordan Blake",
      "customer_phone": "07111222333"
    },
    "result": {
      "success": true,
      "reservation_id": "R0012",
      "id": "R0012",
      "table_id": "T4",
      "date": "2026-10-23",
      "time": "19:00",
      "party_size": 4,
      "name": "Jordan Blake",
      "phone": "07111222333",
      "status": "CONFIRMED",
      "created_at": "2026-10-22 13:18"
    }
  }
]
```

**DineSync**: Your booking is now updated for 4 people this Friday at 7pm, still under Jordan Blake. See you all then!

