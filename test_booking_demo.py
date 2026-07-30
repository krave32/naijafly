import os
from dotenv import load_dotenv
load_dotenv()
from twilio.rest import Client
from urllib.parse import quote_plus

client = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])

# Demo booking deep link
token = '["CAASA05HThoECIbFBiJ2Cl0KWwoDTE9TEhkyMDI2LTA4LTE1VDA2OjMwOjAwKzAxOjAwGgNBQlYiGTIwMjYtMDgtMTVUMDc6NTA6MDArMDE6MDAqAlA0MgQ3MTIwOgJQNEIENzEyMEgBUgM3MzgSBAgDEAEYASgAMgsKCUFpciBQZWFjZQ\u003d\u003d"]'
link = f'https://www.google.com/travel/flights/booking/?token={quote_plus(token)}'

body = (
    '\U0001f4b0 Cheapest LOS->ABV (next 30 days): '
    '107,142 NGN (~$68.00 USD) on Air Peace (P4) via Google Flights\n\n'
    f'View & book this fare: {link}'
)

msg = client.messages.create(
    from_='whatsapp:+14155238886',
    to='whatsapp:+2348144180146',
    body=body
)
print(f'Sent! SID: {msg.sid}')
print(f'Demo link: {link}')
