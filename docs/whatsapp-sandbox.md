# Twilio WhatsApp Sandbox Guide & Testing Transcripts

This guide explains how to connect, configure, and test the Amverio restaurant agent (**The Copper Fork**) on the Twilio WhatsApp Sandbox.

---

## 1. Overview

The **Twilio WhatsApp Sandbox** allows testing WhatsApp messaging without waiting for Meta Business verification or dedicated phone number registration.
- **Shared Sandbox Number**: `+1 415 523 8886` (`whatsapp:+14155238886`)
- **Opt-in Requirement**: Testers must opt in once by sending an account-specific join code (e.g., `join <keyword>`).
- **Session Lifespan**: Once joined, the session stays active for 72 hours of inactivity.
- **Branding**: Messages come from Twilio's verified sandbox profile, but the conversational agent behaves as the restaurant (**The Copper Fork**).

---

## 2. How Testers Join the Sandbox

### Step 1: Get the Join Keyword from Twilio Console
1. Log in to the [Twilio Console](https://console.twilio.com).
2. In the left navigation, go to **Messaging** > **Try it out** > **Send a WhatsApp message**.
3. Under **Sandbox Participants**, locate:
   - Twilio Sandbox Number: `+1 415 523 8886`
   - Your account's unique join keyword: e.g. `join <unique-code>` (e.g., `join frog-castle`)

### Step 2: Send the Join Code from WhatsApp
1. Add `+1 415 523 8886` to your WhatsApp contacts (name it "Twilio Sandbox" or "Amverio Agent").
2. Open WhatsApp on your mobile phone or WhatsApp Web.
3. Send the exact message: `join <unique-code>`
4. Twilio will reply with an automated confirmation:
   > *"You are all set! The sandbox will automatically disconnect after 3 days without messages."*

---

## 3. Configuring the Webhook URL

Twilio delivers all incoming messages sent to the sandbox number to the configured **"When a message comes in"** webhook.

### Option A: Local Development (via Tunnel)
Because Twilio cannot reach `localhost:8000` directly, use an HTTPS tunnel:

1. **Start the local server**:
   ```bash
   .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Expose with a tunnel**:
   - **ngrok**:
     ```bash
     ngrok http 8000
     ```
     Copy the HTTPS forwarding address (e.g. `https://xxxx.ngrok-free.app`).
   - **SSH reverse proxy alternative (e.g. localhost.run)**:
     ```bash
     ssh -o StrictHostKeyChecking=no -R 80:localhost:8000 nokey@localhost.run
     ```
     Copy the assigned HTTPS address (e.g. `https://<tunnel-id>.lhr.life`).

3. **Configure Twilio Console**:
   - Navigate to **Messaging** > **Try it out** > **Send a WhatsApp message** > **Sandbox settings**.
   - Under **"When a message comes in"**:
     - URL: `https://<tunnel-domain>/webhooks/twilio/whatsapp`
     - Method: `HTTP POST`
   - Click **Save**.

4. **Set local environment variable (optional but recommended)**:
   In `.env`:
   ```bash
   TWILIO_WEBHOOK_URL=https://<tunnel-domain>/webhooks/twilio/whatsapp
   ```

---

### Option B: Deployed Demo (Staging / Production)

For the deployed staging environment on Coolify:
- **Webhook URL**: `https://staging.amverio.co.uk/webhooks/twilio/whatsapp`
- **Fallback URL**: `http://x3vwpqzxfyw52teo7s5z5qxt.159.69.31.187.sslip.io/webhooks/twilio/whatsapp`

#### Required Environment Variables in Coolify:
```ini
TWILIO_ACCOUNT_SID=ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_WEBHOOK_URL=https://staging.amverio.co.uk/webhooks/twilio/whatsapp
```

> **Important**: Per project rules, do not modify production Coolify configurations or DNS manually unless authorized.

---

## 4. WhatsApp-Specific Behaviors & Optimizations

| Aspect | Behavior / Finding | Implementation in Amverio |
| :--- | :--- | :--- |
| **Formatting** | WhatsApp uses `*bold*` (single asterisk) rather than Markdown `**bold**`. Markdown links `[Text](url)` are not hyperlinked. | `_format_for_whatsapp()` converts `**bold**` to `*bold*`, Markdown headers to `*Header*`, and formats URLs cleanly for native WhatsApp preview/hyperlinking. |
| **Latency** | End-to-end LLM completion + tool invocation takes ~1.5s to 3.5s per turn. | Well within Twilio's 15-second webhook response timeout limit. |
| **Message Length** | WhatsApp limits single messages to 1,600 characters. | `_split_whatsapp_message()` automatically chunks long replies (>1,500 chars) along paragraph (`\n\n`), sentence (`. `), or line breaks without truncating content. |
| **Emojis** | Emojis (🎉, 🍽️, 📅) are rendered natively on iOS, Android, and Desktop WhatsApp clients. | Full UTF-8 support in XML responses. |
| **Media Handling** | Customers may send images, audio, or location pins. | Webhook detects `NumMedia > 0` and returns a friendly prompt asking for text requests. |
| **Idempotency** | Twilio may retry webhooks if network hiccups occur. | Webhook deduplicates by `MessageSid` (1-hour cache), acknowledging duplicates with `<Response/>` without duplicate charges. |

---

## 5. Scripted Scenarios & Execution Transcripts

All 5 core scenarios were executed end-to-end against the webhook endpoint with live tool calls and verified:

### Scenario 1: Table Booking
- **Customer**: Alex Morgan (`whatsapp:+447111222333`)
- **Intent**: Book a table for 4 this Friday at 7pm

```
[Turn 1]
User:  Hi, I'd like to book a table for 4 people this Friday at 7pm please.
Agent (2.17s):
We have a table available for 4 people this Friday at 7pm. May I have your name and a phone number to confirm your booking?

[Turn 2]
User:  My name is Alex Morgan and phone is 07123456789.
Agent (2.11s):
Your table for 4 is booked this Friday at 7pm under the name Alex Morgan. We look forward to welcoming you then! If you have any other requests, just let me know.
```
*Tools invoked*: `check_table_availability({"date": "2026-10-23", "time": "19:00", "party_size": 4})` -> `book_table(...)`.

---

### Scenario 2: Food Order for Pickup
- **Customer**: Sam Lee (`whatsapp:+447222333444`)
- **Intent**: Order 2 Chargrilled Chicken Burgers for pickup with email confirmation and payment link

```
[Turn 1]
User:  Can I order two chargrilled chicken burgers for pickup?
Agent (1.83s):
You can order two Chargrilled Chicken Burgers for pickup—each comes with buttermilk chicken, smoked bacon, and fries at £13.50 each.

Could you please provide your name, phone number, and email address to confirm your order and send your payment link?

[Turn 2]
User:  Yes confirm that please: Sam Lee, 07099 888777, sam@example.com.
Agent (4.12s):
Your order is confirmed: 2 Chargrilled Chicken Burgers for pickup, total £27.00. A receipt has been sent to sam@example.com.

To complete your order, please pay here: https://buy.stripe.com/test_9B65kFakX4XCe06a461kA0R

Thank you, Sam!
```
*Tools invoked*: `get_menu({})` -> `place_order({"items": [{"menu_id": "M1", "quantity": 2}], "order_type": "pickup", ...})` -> Brevo SMTP email dispatched -> Stripe payment link generated.

---

### Scenario 3: Reservation Cancellation
- **Customer**: Jordan (`whatsapp:+447333444555`)
- **Intent**: Book a table, then cancel it

```
[Turn 1]
User:  Book a table for 2 tomorrow at 6pm. Jordan, 07999888777.
Agent (3.06s):
Your table for 2 is booked for tomorrow at 6pm under the name Jordan. If you need anything else, just let me know!

[Turn 2]
User:  Actually I need to cancel that reservation please.
Agent (1.84s):
Your reservation for tomorrow at 6pm has been cancelled. Let me know if you’d like to rebook or need anything else!
```
*Tools invoked*: `check_table_availability` -> `book_table` -> `cancel_reservation({"reservation_id": "..."})`.

---

### Scenario 4: Menu & Allergen Q&A
- **Customer**: Anonymous Guest (`whatsapp:+447444555666`)
- **Intent**: Inquire about vegetarian/gluten-free options and specific dish pricing

```
[Turn 1]
User:  Hi, what vegetarian or gluten-free options do you have on the menu?
Agent (2.38s):
Here are some vegetarian and gluten-free options:

Vegetarian:
- Wild Mushroom Risotto (Main)
- Garlic Flatbread (Starter)
- Many sides and desserts may also be suitable—please ask if you have specific preferences.

Gluten-free:
- Wild Mushroom Risotto (likely gluten-free, but please confirm with staff about cross-contamination).
- Skin-On Fries
- Seasonal Greens

Some dishes may be adapted, but I recommend checking ingredient details with staff for full safety as the kitchen handles gluten. Would you like to place an order or see more details about a dish?

[Turn 2]
User:  How much is the Wild Mushroom Risotto, and what comes with it?
Agent (1.17s):
The Wild Mushroom Risotto is £12.50. It’s a vegetarian main made with arborio rice, wild mushrooms, and parmesan. Would you like to order it for pickup or delivery, or need details on any other dish?
```
*Tools invoked*: `get_menu({})` -> accurate allergen guidance provided without hallucinating unverified items.

---

### Scenario 5: Off-Topic Guardrail
- **Customer**: Guest (`whatsapp:+447555666777`)
- **Intent**: Non-restaurant queries (weather, AI poem)

```
[Turn 1]
User:  Random question, what's today's weather like in London?
Agent (0.97s):
I’m here to help with table bookings, menu questions, and food orders for The Copper Fork, but I don’t have access to weather updates. If you need anything for your visit or order, just let me know!

[Turn 2]
User:  Can you write a poem about artificial intelligence?
Agent (0.93s):
I’m here to help with table bookings or food orders for The Copper Fork—if you need anything related to the restaurant, I’m happy to assist!
```
*Guardrail behavior*: Politely acknowledged boundary, refused non-restaurant tasks, and offered restaurant assistance.

---

## 6. How to Re-run the Scenarios Locally

To verify all 5 scenarios at any time:
```bash
.venv/bin/python tests/test_whatsapp_sandbox_scenarios.py
```
This executes against the live model and tools, verifying signature calculation, TwiML generation, and conversation state management.
