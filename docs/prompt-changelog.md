# System Prompt Changelog — Amverio DineSync

This document tracks wording refinements and guardrail additions to [`system_prompt.md`](../system_prompt.md) resulting from extensive multi-turn edge-case conversation testing.

---

## 1. Overview of Changes

Following the execution of 12 new real-model edge-case scenarios and 10 baseline regression scenarios against `gpt-4.1`, several edge cases and behavioral gaps were identified. Small, high-impact wording rules were introduced to [`system_prompt.md`](../system_prompt.md) to guard against:
1. Premature booking on ambiguous customer date/times.
2. Inability to reschedule reservations through cancel-and-rebook.
3. Hallucinating or failing when customers attempt to modify or cancel placed orders.
4. Unsafe promises regarding unlisted allergens or cross-contamination.
5. Defensive responses to rude or aggressive customers.
6. Confusion when table-booking customers attempt to pre-order dine-in food.

---

## 2. Detailed Changelog

### Change 1: Clarifying Ambiguous Dates and Times
- **Added in `system_prompt.md`**:
  > *"If a customer gives an ambiguous date or time (e.g. 'next weekend', 'evening'), ask for the specific date and time before checking availability or booking."*
- **Scenario Fixed / Guarded**: `edge_ambiguous_datetime`
- **Rationale**: Prevented the model from arbitrarily guessing a date (e.g., Saturday vs Sunday) or booking a default hour without explicit customer confirmation.

### Change 2: Rescheduling Existing Reservations
- **Added in `system_prompt.md`**:
  > *"To reschedule an existing reservation, check availability for the new time, cancel the old booking with cancel_reservation, and book the new table with book_table."*
- **Scenario Fixed**: `baseline_reschedule`
- **Rationale**: Because no native `reschedule_reservation` tool exists, the model previously paused to ask if it should move it instead of executing the expected cancel-and-rebook workflow in one fluid turn.

### Change 3: Post-Placement Order Immutability
- **Added in `system_prompt.md`**:
  > *"Once place_order has been called, an order cannot be changed or cancelled via chat; advise the customer to call the restaurant directly."*
- **Scenario Fixed**: `edge_change_mind_after_confirmation`
- **Rationale**: Prevented confusion or hallucination of non-existent order cancellation tools once an order has been submitted to the kitchen and Stripe payment links generated.

### Change 4: Separation of Takeaway Food Orders and Dine-In Bookings
- **Added in `system_prompt.md`**:
  > *"Food orders taken here are strictly for pickup or delivery; if a table booking guest asks to pre-order food, confirm the table booking and clarify that dine-in food is ordered at the table upon arrival."*
- **Scenario Fixed**: `edge_mixing_booking_and_order`
- **Rationale**: Clarifies that `place_order` is strictly for takeaway (pickup/delivery) with online Stripe checkout, and dine-in guests order at the table upon arrival.

### Change 5: Allergen Safety and Cross-Contamination
- **Added in `system_prompt.md`**:
  > *"For allergen or cross-contamination questions not detailed on the menu, state known ingredients honestly, never guarantee allergen-free safety, and advise speaking directly with restaurant staff."*
- **Scenario Fixed**: `edge_allergen_question`
- **Rationale**: Menu data does not contain kitchen prep procedures or certified allergen traces. Protects against liability by preventing LLM guarantees on severe nut/gluten/dairy allergies.

### Change 6: De-escalation with Rude Customers
- **Added in `system_prompt.md`**:
  > *"Always remain warm, calm, and professional, even if a customer is rude or demanding."*
- **Scenario Fixed**: `edge_rude_customer`
- **Rationale**: Ensures the agent maintains hospitality standards without defensive remarks or refusing service when customers are abrupt or frustrated.

---

## 3. Supporting Code Fixes

- **`tools.py`**: Added missing `import time` at the top of the module. Previously, `place_order` raised `NameError: name 'time' is not defined` inside `_is_email_throttled` when checking email rate limits.

---

## 4. Verification & Test Results

All 22 scenarios executed end-to-end against the real model using [`tests/scenarios/runner.py`](../tests/scenarios/runner.py). Markdown transcripts for every scenario are archived in [`tests/scenarios/transcripts/`](../tests/scenarios/transcripts/).

| Scenario ID | Category | Status | Verification Summary |
| :--- | :--- | :---: | :--- |
| `baseline_booking_upfront` | Baseline | **PASS** | Called `book_table` after availability check |
| `baseline_booking_withheld` | Baseline | **PASS** | Prompted for missing name/phone without premature booking |
| `baseline_order_pickup` | Baseline | **PASS** | Retrieved menu, confirmed item price, sent Stripe link & email |
| `baseline_order_delivery` | Baseline | **PASS** | Recorded delivery order and explained logistics policy |
| `baseline_off_topic` | Baseline | **PASS** | Refocused on restaurant without calling tools |
| `baseline_overbooking` | Baseline | **PASS** | Correctly declined party of 12 exceeding max capacity |
| `baseline_cancel_reservation` | Baseline | **PASS** | Successfully triggered `cancel_reservation` |
| `baseline_reschedule` | Baseline | **PASS** | Cancelled old booking and booked new time |
| `baseline_order_change_mind` | Baseline | **PASS** | Adjusted quantities accurately before confirmation |
| `baseline_order_remove_item` | Baseline | **PASS** | Removed item and placed order with soup only |
| `edge_rude_customer` | Edge Case | **PASS** | De-escalated calmly and confirmed booking |
| `edge_ambiguous_datetime` | Edge Case | **PASS** | Clarified "next weekend" to exact day/time before booking |
| `edge_party_size_change` | Edge Case | **PASS** | Adjusted party size to 4 and booked appropriately |
| `edge_multi_category_order` | Edge Case | **PASS** | Flagged unlisted drinks while placing valid food items |
| `edge_add_remove_items` | Edge Case | **PASS** | Processed complex additions and removals with exact math |
| `edge_change_mind_after_confirmation` | Edge Case | **PASS** | Informed placed order cannot be cancelled via chat, directed to call |
| `edge_unavailable_item` | Edge Case | **PASS** | Politely declined unlisted dishes and suggested bistro items |
| `edge_allergen_question` | Edge Case | **PASS** | Stated ingredients without false guarantees; advised contacting staff |
| `edge_mixing_booking_and_order` | Edge Case | **PASS** | Booked table while clarifying dine-in vs takeaway food policy |
| `edge_non_english_greeting` | Edge Case | **PASS** | Welcomed in English and processed French table inquiry |
| `edge_very_long_message` | Edge Case | **PASS** | Extracted reservation details from rambling message |
| `edge_off_topic_deep` | Edge Case | **PASS** | Politely declined general knowledge request |
