import os
from dotenv import load_dotenv
load_dotenv()

from twilio.rest import Client

client = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])
msg = client.messages.create(
    from_='whatsapp:+14155238886',
    to='whatsapp:+2348144180146',
    body='Araha is live! Send me a message to check Nigeria flight fares.\n\nTry: "cheap flights from Lagos to Abuja"'
)
print(f'Sent! SID: {msg.sid}')
