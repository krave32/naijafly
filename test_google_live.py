"""Quick smoke test: fetch real Google Flights fares."""
import os
os.environ["FARE_SOURCE"] = "google"

from app.services.fare_ingestor import get_active_ingestor
from datetime import datetime

ingestor = get_active_ingestor("google")
routes = [("LOS", "ABV"), ("LOS", "PHC"), ("ABV", "LOS")]

from datetime import timedelta
# Use a date ~2 weeks out for realistic results
target = datetime.utcnow() + timedelta(days=14)

for origin, dest in routes:
    fares = ingestor.fetch_fares(origin, dest, target)
    print(f"\n{origin} -> {dest}: {len(fares)} fare(s)")
    for f in fares[:3]:
        print(f"  {f['source']}: NGN{f['price']:,.0f}")
    if not fares:
        print("  (no data — fli may need a moment or Google rate-limited)")
