"""FX conversion with live-or-cached rates.

Real path: fetch_live_rates() hits the free open.er-api.com endpoint (no key
needed) and caches into the fx_rates table. If offline, falls back to cached
DB rates, then to hardcoded defaults. Inverse and cross rates (via USD) are
derived automatically so any pair among USD/NGN/GHS/XOF converts correctly.
"""
from datetime import datetime

DEFAULT_USD_RATES = {
    "NGN": 1500.0,    # Nigerian Naira
    "GHS": 15.0,      # Ghanaian Cedi
    "XOF": 600.0,     # West African CFA Franc (Senegal, Côte d'Ivoire, Burkina Faso)
    "SLL": 22000.0,   # Sierra Leonean Leone
    "GMD": 68.0,      # Gambian Dalasi
    "LRD": 190.0,     # Liberian Dollar
    "GNF": 8600.0,    # Guinean Franc
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
                # pair stored as USD_NGN etc.
                base, quote = row.pair.split("_")
                if base == "USD":
                    self.usd_rates[quote] = row.rate
        except Exception:
            pass  # table may not exist yet; defaults stand

    def fetch_live_rates(self) -> bool:
        """Refresh rates from open.er-api.com (free, keyless). Returns success."""
        try:
            import requests
            resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
            data = resp.json()
            if data.get("result") != "success":
                return False
            rates = data["rates"]
            for cur in ("NGN", "GHS", "XOF", "SLL", "GMD", "LRD", "GNF"):
                if cur in rates:
                    self.usd_rates[cur] = float(rates[cur])
                    self._cache(f"USD_{cur}", float(rates[cur]))
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
        """Any pair among known currencies, derived via USD."""
        from_curr, to_curr = from_curr.upper(), to_curr.upper()
        if from_curr == to_curr:
            return 1.0
        if from_curr not in self.usd_rates or to_curr not in self.usd_rates:
            raise ValueError(f"Unknown currency pair {from_curr}->{to_curr}")
        # amount_in_usd = amount / usd_rates[from]; result = usd * usd_rates[to]
        return self.usd_rates[to_curr] / self.usd_rates[from_curr]

    def convert(self, amount: float, from_curr: str, to_curr: str) -> float:
        return amount * self.get_rate(from_curr, to_curr)
