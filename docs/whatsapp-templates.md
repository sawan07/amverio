# WhatsApp 24-Hour Customer Service Window & Template Messaging Guide

This document defines Meta/Twilio 24-hour window constraints, describes the required WhatsApp message templates, and provides submission instructions for the owner.

---

## 1. The 24-Hour Customer Service Window Rule

Under Meta's WhatsApp Business Platform policy:
- **Within 24 Hours (Active Window)**:
  - Whenever a customer messages the business on WhatsApp, a **24-hour customer service window** opens.
  - While this window is open, the business can send **free-form text messages** and interactive responses without pre-approval.
- **Outside 24 Hours (Expired Window / Business-Initiated)**:
  - More than 24 hours after the customer's last incoming message (or when contacting a customer who has never messaged first), businesses **CANNOT** send free-form text.
  - Outbound messages **MUST** use pre-approved WhatsApp templates created in Twilio / Meta Business Manager.
  - Any attempt to send free-form text outside the window is blocked by WhatsApp and rejected in the Amverio codebase with `WhatsAppWindowError`.

```
Customer Message Arrives
        │
        ▼
[Record last_inbound_at in whatsapp_sessions]
        │
        ├── < 24 Hours ──► Free-form text permitted (or templates)
        │
        └── > 24 Hours ──► ONLY pre-approved templates permitted
                            (Free-form text rejected with error)
```

---

## 2. Templates to Submit for Approval (Owner Task)

Template approval in Twilio/Meta is an owner action. The owner (Sawan) can submit these via:
1. **Twilio Console**: **Messaging** > **Content Template Builder** > **Create new Content Template**.
2. **Meta Business Manager**: **WhatsApp Manager** > **Account Tools** > **Message Templates**.

All templates below are classified under the **UTILITY** category (which qualifies for lower messaging rates and faster automated approval).

---

### Template 1: Booking Confirmation

- **Template Name**: `booking_confirmation`
- **Category**: `UTILITY`
- **Language**: English (UK) (`en_GB`) / English (US) (`en_US`)
- **Use Case**: Sent when a customer reserves a table outside the interactive chat window or needs an immutable booking receipt.
- **Variables**:
  - `{{1}}`: Customer First Name
  - `{{2}}`: Party Size (number of guests)
  - `{{3}}`: Date and Time of Reservation
  - `{{4}}`: Reservation Reference ID
- **Body Text**:
  ```text
  Hi {{1}}, your table for {{2}} at The Copper Fork is confirmed for {{3}}. Your booking reference is {{4}}. To change or cancel, reply to this message.
  ```
- **Sample Values**:
  - `{{1}}`: `Alex`
  - `{{2}}`: `4`
  - `{{3}}`: `Friday, 23 October at 19:00`
  - `{{4}}`: `R0015`

---

### Template 2: Booking Reminder (e.g. 3 Hours Before)

- **Template Name**: `booking_reminder`
- **Category**: `UTILITY`
- **Language**: English (UK) (`en_GB`) / English (US) (`en_US`)
- **Use Case**: Automatically dispatched by `reminder_job.py` ~3 hours before a confirmed dining reservation when the customer booked days in advance (>24h).
- **Variables**:
  - `{{1}}`: Customer First Name
  - `{{2}}`: Party Size
  - `{{3}}`: Reservation Time
  - `{{4}}`: Restaurant Name
- **Body Text**:
  ```text
  Hi {{1}}, this is a friendly reminder that your table for {{2}} at {{4}} is booked for today at {{3}}. We look forward to seeing you! Need to adjust? Reply directly to this message.
  ```
- **Sample Values**:
  - `{{1}}`: `Sarah`
  - `{{2}}`: `4`
  - `{{3}}`: `19:00`
  - `{{4}}`: `The Copper Fork`

---

### Template 3: Order Ready

- **Template Name**: `order_ready`
- **Category**: `UTILITY`
- **Language**: English (UK) (`en_GB`) / English (US) (`en_US`)
- **Use Case**: Sent when kitchen staff mark a pickup or delivery order as prepared (`PREPARING` -> `READY`).
- **Variables**:
  - `{{1}}`: Customer First Name
  - `{{2}}`: Order ID
  - `{{3}}`: Order Type (`collection`, `pickup`, or `delivery`)
- **Body Text**:
  ```text
  Hi {{1}}, great news! Your order #{{2}} is ready for {{3}} at The Copper Fork. Thank you for dining with us!
  ```
- **Sample Values**:
  - `{{1}}`: `Sam`
  - `{{2}}`: `O0012`
  - `{{3}}`: `pickup`

---

### Template 4: Booking Cancelled

- **Template Name**: `booking_cancelled`
- **Category**: `UTILITY`
- **Language**: English (UK) (`en_GB`) / English (US) (`en_US`)
- **Use Case**: Sent when a reservation is cancelled either by staff or customer.
- **Variables**:
  - `{{1}}`: Customer First Name
  - `{{2}}`: Original Booking Date & Time
  - `{{3}}`: Reservation Reference ID
- **Body Text**:
  ```text
  Hi {{1}}, your booking #{{3}} for {{2}} at The Copper Fork has been cancelled. If you'd like to reserve another time, just send us a message.
  ```
- **Sample Values**:
  - `{{1}}`: `Jordan`
  - `{{2}}`: `tomorrow at 18:00`
  - `{{3}}`: `R0016`

---

## 3. Environment Variable Configuration

Once templates are approved in Twilio Content Template Builder, Twilio assigns each template a unique Content SID starting with `HX...`. Add them to `.env` or Coolify:

```ini
# Twilio Content Template SIDs
TWILIO_TEMPLATE_BOOKING_CONFIRMATION_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_TEMPLATE_BOOKING_REMINDER_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_TEMPLATE_ORDER_READY_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_TEMPLATE_BOOKING_CANCELLED_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

*Note: In the Twilio WhatsApp Sandbox, Twilio provides sample pre-approved templates (such as `HXb5b62575e6e4ff6129ad7c8efe1f983e`) which are used as fallback defaults in development.*

---

## 4. Code Implementation Architecture

### A. Tracking Inbound Messages (`db.py` & `app.py`)
Every inbound message arriving at `POST /webhooks/twilio/whatsapp` updates `whatsapp_sessions`:
- Table: `whatsapp_sessions` (`phone_number`, `last_inbound_at`, `last_message_text`, `updated_at`).
- Window check function: `db.is_inside_24h_window(phone_number) -> bool`.

### B. Outbound Dispatch (`whatsapp.py`)
The `send_whatsapp()` function strictly enforces the window:
```python
import whatsapp

# Inside 24h window -> Free-form text works:
whatsapp.send_whatsapp(
    to="+447123456789",
    text="Hi Alex, here is an update regarding your table."
)

# Outside 24h window -> Free-form text raises WhatsAppWindowError:
# (Requires pre-approved template)
whatsapp.send_whatsapp(
    to="+447123456789",
    template="booking_reminder",
    variables={"1": "Alex", "2": "4", "3": "19:00", "4": "The Copper Fork"}
)
```

### C. Booking Reminder Runner (`reminder_job.py`)
Can be executed as a CLI tool or scheduled cron job:
```bash
# Check upcoming reservations due in the next 3 hours
python reminder_job.py --hours 3

# Dry-run mode (tests logic without sending live messages or modifying DB)
python reminder_job.py --hours 3 --dry-run
```
- Checks `reminder_sent_at` in `reservations` table (idempotent, never duplicates reminders).
- Automatically selects free-form text if inside 24h, or template if outside 24h.
