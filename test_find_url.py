import os
from dotenv import load_dotenv
load_dotenv()
from twilio.rest import Client
c = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])

# Check WhatsApp sandbox webhook URL
try:
    sb = c.whatsapp.messaging_products('whatsapp').sandbox().fetch()
    print(f"Sandbox webhook: {sb.webhook_url}")
except:
    pass

# Check message services
for s in c.messaging.v1.services.list():
    print(f"Service: {s.friendly_name}, Inbound: {s.inbound_request_url}")

# Check phone numbers
for n in c.incoming_phone_numbers.list():
    print(f"Number: {n.phone_number}, SMS URL: {n.sms_url}, Voice URL: {n.voice_url}")
