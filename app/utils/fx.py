"""FX conversion with live-or-cached rates.

Nigeria-domestic scope: all fares are in NGN. The only conversion needed is
NGN -> USD for display purposes. Live rates fetched from open.er-api.com
(free, keyless) and cached into the fx_rates table. Falls back to cached
DB rates, then to hardcoded defaults if offline.
"""
from datetime import datetime

DEFAULT_USD_RATES = {
    "NGN": 1500.0,    # Nigerian Naira
    "USD": 1.0,
}


class FXService:
    def __init__(self, db_session=None):
        self.db = db_session
        self.usd_rates = dict(DEFAULT_USD_RATES)  # 1 USD -> X currency
        if self.db is not None:
            self._load_cached()

    def _load_cached(self):
        try:
            from app.models.models import FXRate
            for row in self.db.query(FXRate).all():
                base, quote = row.pair.split("_")
                if base == "USD":
                    self.usd_rates[quote] = row.rate
        except Exception:
            pass  # table may not exist yet; defaults stand

    def fetch_live_rates(self) -> bool:
        """Refresh NGN rate from open.er-api.com (free, keyless). Returns success."""
        try:
            import requests
            resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
            data = resp.json()
            if data.get("result") != "success":
                return False
            rates = data["rates"]
            if "NGN" in rates:
                self.usd_rates["NGN"] = float(rates["NGN"])
                self._cache("USD_NGN", float(rates["NGN"]))
            return True
        except Exception:
            return False

    def _cache(self, pair: str, rate: float):
        if self.db is None:
            return
        try:
            from app.models.models import FXRate
            row = self.db.query(FXRate).filter_by(pair=pair).first()
            if row:
                row.rate = rate
                row.updated_at = datetime.utcnow()
            else:
                self.db.add(FXRate(pair=pair, rate=rate))
            self.db.commit()
        except Exception:
            pass

    def get_rate(self, from_curr: str, to_curr: str) -> float:
        """Convert between NGN and USD (the only pair needed for Nigeria-domestic)."""
        from_curr, to_curr = from_curr.upper(), to_curr.upper()
        if from_curr == to_curr:
            return 1.0
        if from_curr not in self.usd_rates or to_curr not in self.usd_rates:
            raise ValueError(f"Unknown currency pair {from_curr}->{to_curr}")
        return self.usd_rates[to_curr] / self.usd_rates[from_curr]

    def convert(self, amount: float, from_curr: str, to_curr: str) -> float:
        return amount * self.get_rate(from_curr, to_curr)
