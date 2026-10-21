# Scenario: Customer tries to cancel or modify order after placement

- **ID**: `edge_change_mind_after_confirmation`
- **Category**: `edge_case`
- **Status**: `PASSED`
- **Verification**: Explained placed orders cannot be cancelled via chat and directed to call restaurant
- **Date**: 2026-10-21 19:37:01

## Conversation Transcript

### Turn 1

**Customer**: I'll get a chargrilled chicken burger for pickup. Liam, 07123456789, liam@example.com.

**Tool Executions**:
```json
[
  {
    "tool": "get_menu",
    "args": {},
    "result": {
      "restaurant": "The Copper Fork",
      "currency": "GBP",
      "menu": {
        "Starters": [
          {
            "id": "S1",
            "name": "Soup of the Day",
            "price": 6.5,
            "description": "Ask for today's flavour, served with sourdough."
          },
          {
            "id": "S2",
            "name": "Garlic Flatbread",
            "price": 5.5,
            "description": "Stone-baked flatbread, garlic butter, herbs."
          }
        ],
        "Mains": [
          {
            "id": "M1",
            "name": "Chargrilled Chicken Burger",
            "price": 13.5,
            "description": "Buttermilk chicken, smoked bacon, fries."
          },
          {
            "id": "M2",
            "name": "8oz Sirloin Steak",
            "price": 19.0,
            "description": "Chargrilled sirloin, peppercorn sauce, fries."
          },
          {
            "id": "M3",
            "name": "Wild Mushroom Risotto",
            "price": 12.5,
            "description": "Vegetarian. Arborio rice, wild mushrooms, parmesan."
          },
          {
            "id": "M4",
            "name": "Beer-Battered Fish & Chips",
            "price": 14.0,
            "description": "Market fish, mushy peas, tartare sauce."
          }
        ],
        "Sides": [
          {
            "id": "D1",
            "name": "Skin-On Fries",
            "price": 4.0,
            "description": ""
          },
          {
            "id": "D2",
            "name": "Seasonal Greens",
            "price": 4.0,
            "description": ""
          }
        ],
        "Desserts": [
          {
            "id": "P1",
            "name": "Sticky Toffee Pudding",
            "price": 6.0,
            "description": "Butterscotch sauce, vanilla ice cream."
          },
          {
            "id": "P2",
            "name": "Chocolate Brownie",
            "price": 6.0,
            "description": "Warm brownie, vanilla ice cream."
          }
        ]
      }
    }
  }
]
```

**DineSync**: You'd like one Chargrilled Chicken Burger for pickup, under the name Liam. The total is £13.50.

Once I place your order, you'll get a confirmation email and a Stripe payment link here in the chat. Shall I go ahead and place this order for you?

### Turn 2

**Customer**: Yes please place the order now.

**Tool Executions**:
```json
[
  {
    "tool": "place_order",
    "args": {
      "items": [
        {
          "menu_id": "M1",
          "quantity": 1
        }
      ],
      "order_type": "pickup",
      "customer_name": "Liam",
      "customer_phone": "07123456789",
      "customer_email": "liam@example.com"
    },
    "result": {
      "success": true,
      "order_id": "O0009",
      "total": 13.5,
      "payment_link": "https://buy.stripe.com/test_cNi8wR2Sv3Tyg8e0tw1kA0F",
      "email_sent_to": "liam@example.com",
      "order_type": "pickup",
      "items": [
        {
          "menu_id": "M1",
          "name": "Chargrilled Chicken Burger",
          "quantity": 1,
          "unit_price": 13.5,
          "line_total": 13.5
        }
      ],
      "customer_name": "Liam"
    }
  }
]
```

**DineSync**: Your order for 1 Chargrilled Chicken Burger for pickup is placed. The total is £13.50.

A confirmation has been sent to liam@example.com. Please pay using this Stripe link: https://buy.stripe.com/test_cNi8wR2Sv3Tyg8e0tw1kA0F

Thank you, Liam!

### Turn 3

**Customer**: Wait! I changed my mind, can you cancel that order and remove the burger?

**DineSync**: I'm not able to cancel or change orders once they've been placed via chat. Please call the restaurant directly as soon as possible, and they'll assist you with your request.

