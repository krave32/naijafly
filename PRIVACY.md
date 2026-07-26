# Privacy Policy — Araha WhatsApp Bot

Last updated: July 2026

Araha is committed to protecting the privacy of users in compliance with the
**Nigeria Data Protection Act (NDPA) 2023**. This policy explains what data
we collect, why, how long we keep it, and how to have it removed.

## What we collect

| Data | Why | Retention |
|---|---|---|
| **Phone number** (WhatsApp ID) | To identify you, route alerts, and prevent abuse | Until you send STOP |
| **Subscribed routes** | To monitor fares for the routes you've asked about | Until you send STOP |
| **Flight tracking subscriptions** | To send you boarding/gate/delay updates for specific flights | Until you send STOP |
| **Status reports** you send | To aggregate crowd-sourced flight status for other passengers | Anonymized on STOP |
| **Alert history** | To avoid duplicate alerts and track delivery | Anonymized on STOP |
| **Reporter trust score** | To weight status reports and prevent spam/abuse | Anonymized on STOP |

## What we do NOT collect

- Name, email, or any personal details beyond your WhatsApp phone number
- Payment or financial information
- Location data or device information
- Message content beyond the commands and status reports you explicitly send

## How we use your data

- Send you fare-drop alerts for routes you've subscribed to
- Send you boarding, gate, and delay updates for flights you're tracking
- Aggregate status reports from multiple passengers to confirm real-time flight status
- Prevent abuse (rate limiting, spam detection)

## Your rights — send STOP to remove your data

At any time, send **STOP** (or **UNSUBSCRIBE**, **CANCEL**, **QUIT**, **REMOVE**) to the Araha WhatsApp number. This will:

1. **Delete** all your fare subscriptions and flight-tracking subscriptions
2. **Anonymize** your phone number in alert history, status reports, and reporter scores (replaced with `[deleted]`)
3. **Remove** your first-contact record (you'll see the welcome message again if you return)

After STOP, your phone number is no longer tied to any personal data in our system. Anonymized historical records are kept in aggregate form for system integrity (e.g., status report accuracy), but cannot be linked back to you.

If you change your mind, just text **HI** to start using Araha again.

## Data security

- All data is stored in a PostgreSQL database on Railway (EU/US data centers)
- Communication with WhatsApp goes through Twilio's encrypted API
- Admin access to user data is protected by HTTP Basic Auth
- No third parties have access to your data beyond Twilio (message delivery) and Railway (hosting)

## Contact

For privacy-related requests or concerns, contact the Araha team through the WhatsApp bot or via the support channels listed on our website.
