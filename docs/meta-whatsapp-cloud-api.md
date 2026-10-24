# Meta WhatsApp Cloud API (direct integration)

Amverio can talk to WhatsApp directly through Meta's Cloud API, with no BSP such as Twilio in between. This is the intended production path. The Twilio path stays in the codebase for the Sandbox and as a fallback.

- Webhook (inbound): `GET` + `POST /webhooks/meta/whatsapp` in [`app.py`](../app.py)
- Outbound client: [`meta_whatsapp.py`](../meta_whatsapp.py)
- Shared formatting / templates: [`whatsapp.py`](../whatsapp.py)
- Proactive messages (reminders): [`reminder_job.py`](../reminder_job.py), switched with `WHATSAPP_PROVIDER=meta`
- Tests: `tests/test_meta_whatsapp_webhook.py` (no network needed)

## 1. How it works

```
Customer -> WhatsApp -> Meta -> POST /webhooks/meta/whatsapp   (signed, X-Hub-Signature-256)
                                  |  verify signature, dedupe by message id, record inbound, return 200 fast
                                  v  (background task)
                           chat_engine.respond(session_id="whatsapp:+44...", domain_id="restaurant")
                                  v
                       meta_whatsapp.send_reply -> POST graph.facebook.com/{version}/{phone_number_id}/messages
```

Key differences from Twilio:

- The reply is **not** the HTTP response. The webhook returns `200` immediately and the reply is sent afterwards through the Graph API.
- Requests are authenticated with an HMAC of the raw body using the Meta **App Secret**, not a Twilio auth token.
- Free-text replies are only allowed within 24 hours of the customer's last message. Outside that window only pre-approved **templates** can be sent (Meta error `131047` otherwise). The client checks the window itself (`db.is_inside_24h_window`) and falls back to a template where one exists.
- Session keys keep the `whatsapp:+44...` format, so conversations carry over unchanged between Twilio and Meta.

## 2. Environment variables

| Variable | Purpose |
|---|---|
| `META_WA_PHONE_NUMBER_ID` | ID of the sending phone number (not the number itself) |
| `META_WA_ACCESS_TOKEN` | Permanent System User token (not the 24h test token) |
| `META_WA_VERIFY_TOKEN` | Any random string you choose; must match what you enter in the Meta dashboard |
| `META_APP_SECRET` | App Secret; used to verify `X-Hub-Signature-256` |
| `META_WA_BUSINESS_ACCOUNT_ID` | WhatsApp Business Account ID (needed to manage templates) |
| `META_GRAPH_API_VERSION` | Optional. Default `v23.0` |
| `META_WA_TEMPLATE_LANG` | Optional. Default `en_GB` |
| `WHATSAPP_PROVIDER` | `meta` to send reminders through Meta. Default `twilio` |

Secrets go in Coolify's environment settings, never in the repo.

## 3. One-time Meta setup (also the basis of the customer guide)

1. Create a Meta developer account and a **Business** app at developers.facebook.com. Add the **WhatsApp** product.
2. In *WhatsApp > API Setup* Meta gives you a free **test phone number** and a temporary token. Add up to five recipient numbers (your own, your partner's) and verify them by code.
3. Copy the **Phone number ID** and **WhatsApp Business Account ID** from the same page.
4. App settings > Basic: copy the **App Secret**.
5. Set the env vars above on staging and redeploy.
6. *WhatsApp > Configuration > Webhook*: Callback URL `https://staging.amverio.co.uk/webhooks/meta/whatsapp`, Verify token = your `META_WA_VERIFY_TOKEN`. Click **Verify and save**. Then subscribe to the **messages** field.
7. For anything longer than a day: in Business Settings create a **System User** (admin), assign it the app and the WhatsApp account, and generate a token with `whatsapp_business_messaging` and `whatsapp_business_management`. Use that as `META_WA_ACCESS_TOKEN`.
8. Message the test number from a registered phone and watch the reply arrive.

For a real restaurant number, Meta Business verification and a registered business phone number are required first (production only; the test number needs neither).

## 4. Templates

Templates must be created and approved in WhatsApp Manager (or via the Graph API) before they can be sent outside the 24-hour window. Create these four, category **UTILITY**, language **English (UK)**, with positional variables. The bodies come from `whatsapp.TEMPLATES`:

| Name | Body |
|---|---|
| `booking_confirmation` | Hi {{1}}, your table for {{2}} at The Copper Fork is confirmed for {{3}}. Your booking reference is {{4}}. To change or cancel, reply to this message. |
| `booking_reminder` | Hi {{1}}, this is a friendly reminder that your table for {{2}} at {{4}} is booked for today at {{3}}. We look forward to seeing you! Need to adjust? Reply directly to this message. |
| `order_ready` | Hi {{1}}, great news! Your order #{{2}} is ready for {{3}} at The Copper Fork. Thank you for dining with us! |
| `booking_cancelled` | Hi {{1}}, your booking #{{3}} for {{2}} at The Copper Fork has been cancelled. If you'd like to reserve another time, just send us a message. |

Template names are sent as-is to Meta, so the names in WhatsApp Manager must match exactly. If a template is missing or unapproved, the send fails with a delivery error that is logged; it does not crash the reminder job.

## 5. Testing

Handshake check (replace the token):

```bash
curl -s "https://staging.amverio.co.uk/webhooks/meta/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=12345"
# -> 12345   (a wrong token returns 403)
```

Automated: `pytest tests/test_meta_whatsapp_webhook.py` covers the handshake, signature verification, payload parsing, the inbound-to-reply flow, the Graph client (text, templates, 24h window, error mapping) and the reminder job with `WHATSAPP_PROVIDER=meta`.

Live: message the Meta test number, check Coolify logs for the POST, and confirm the reply and the stored conversation (`/api/whatsapp/sessions/{phone}`).

## 6. Migrating from Twilio

1. Deploy with Meta env vars set; keep `WHATSAPP_PROVIDER` unset (Twilio) until the live test passes.
2. Configure the Meta webhook (section 3).
3. Set `WHATSAPP_PROVIDER=meta` so reminders go out through Meta.
4. The Twilio webhook (`/webhooks/twilio/whatsapp`) can stay until you are happy, then be removed.

## 7. Notes

- Graph API v20.0 reached end of life in September 2026; Meta auto-upgrades old versions but pin a current one with `META_GRAPH_API_VERSION` and review it each quarter.
- Delivery status callbacks (`statuses`) are accepted and ignored for now.
- Unsupported inbound types (images, voice, location) get a polite text-only reply.
- Never log the access token; `meta_whatsapp.py` keeps it out of error messages.
