# WhatsApp Production Checklist

## 1. Meta Business Verification
- [ ] Complete business verification in Meta Business Suite
- [ ] Required: CAC (Corporate Affairs Commission) documents for Nigerian business
- [ ] Required: Valid government-issued ID for business owner
- [ ] Timeline: 2-5 business days for verification

## 2. Twilio WhatsApp Sender Setup
- [ ] Navigate to Twilio Console > Messaging > Senders > WhatsApp Senders
- [ ] Follow the "Self Sign-Up" flow to migrate from sandbox to production
- [ ] Required: Approved Meta Business account
- [ ] Required: Display name matching Meta Business name exactly
- [ ] Required: WhatsApp Business profile (description, email, website)

## 3. Message Template Approval
- [ ] Submit fare-drop alert template as "Utility" category
- [ ] Submit boarding status alert template as "Utility" category
- [ ] Submit welcome/intro template as "Utility" category
- [ ] Submit UNSUBSCRIBE confirmation template as "Utility" category
- [ ] Templates must NOT be marketing-heavy — Meta rejects promotional content
- [ ] All templates must include opt-out instructions
- [ ] Timeline: 1-3 business days per template

## 4. Webhook Configuration
- [ ] Update Twilio WhatsApp Sandbox webhook URL to production URL
- [ ] Configure Opt-out management URL → `/webhook/optout`
- [ ] Configure Opt-in management URL → `/webhook/optin`
- [ ] Verify Twilio Status Callback URL for delivery receipts
- [ ] Test: STOP command triggers opt-out webhook correctly
- [ ] Test: START after opt-out triggers opt-in webhook correctly

## 5. Environment Variables
- [ ] `ADMIN_USER` and `ADMIN_PASSWORD` set in production
- [ ] `FARE_SOURCE` set to `google` or `hybrid` (not `mock`)
- [ ] `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` set
- [ ] `TWILIO_WHATSAPP_NUMBER` set to production number
- [ ] `DATABASE_URL` pointing to production Postgres
- [ ] `AMADEUS_API_KEY` and `AMADEUS_API_SECRET` (if using Amadeus)

## 6. Pre-Launch Verification
- [ ] All 250+ tests passing
- [ ] Admin dashboard accessible with credentials
- [ ] Fare worker running and polling correctly
- [ ] Google Flights ingestor returning real fare data
- [ ] WhatsApp outbound push working (not just console fallback)
- [ ] UNSUBSCRIBE flow deletes/anonymizes data correctly
- [ ] Rate-limit hardening in place (if implemented)

## 7. Cost Considerations
- WhatsApp Business: ~$0.03-0.05 per conversation outside 24-hour window
- Each fare-drop alert starts a new conversation if no recent user interaction
- **Recommendation:** Implement digest mode or >10% price-drop threshold before production scale
- **Recommendation:** Monitor Twilio billing dashboard daily for first week

## 8. Legal & Compliance
- [ ] PRIVACY.md reflects NDPA 2023 compliance
- [ ] WhatsApp opt-out mechanism documented
- [ ] Data deletion/anonymization verified
- [ ] fli library legal review completed (reverse-engineered Google API)
