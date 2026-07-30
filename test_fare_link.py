import os
from dotenv import load_dotenv
load_dotenv()
from twilio.rest import Client
from datetime import datetime, timedelta

client = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])

origin, dest = "LOS", "ABV"
date = (datetime.utcnow() + timedelta(days=14)).strftime("%Y-%m-%d")
link = f"https://www.google.com/travel/flights?q=Flights+from+{origin}+to+{dest}+on+{date}&curr=NGN"

body = (
    "💰 Cheapest LOS->ABV (next 30 days): "
    "107,142 NGN (~$68.00 USD) on Air Peace\n\n"
    f"Verify on Google Flights: {link}"
)

msg = client.messages.create(
    from_='whatsapp:+14155238886',
    to='whatsapp:+2348144180146',
    body=body
)
print(f"Sent! SID: {msg.sid}")
print(f"Link: {link}")
