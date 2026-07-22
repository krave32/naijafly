import re
from app.models.models import StatusType

class MessageParser:
    @staticmethod
    def parse(text: str):
        text = text.lower()
        status_type = StatusType.OTHER
        gate = None

        # Basic keyword mapping
        if any(kw in text for kw in ["boarding now", "started boarding", "boarding started"]):
            status_type = StatusType.BOARDING
        elif any(kw in text for kw in ["not boarding", "still waiting", "gate closed"]):
            status_type = StatusType.NOT_BOARDING
        elif any(kw in text for kw in ["delay", "delayed", "pushed back"]):
            status_type = StatusType.DELAY
        elif any(kw in text for kw in ["gate changed", "gate change", "new gate"]):
            status_type = StatusType.GATE_CHANGE

        # Extract gate number (e.g. "gate 12", "gate changed to E5")
        # Look for a short alphanumeric code (1-4 chars) following "gate"
        gate_match = re.search(r"gate\s*(?:changed\s*|to\s*|is\s*)*([a-zA-Z0-9]{1,4})\b", text)
        if gate_match:
            gate = gate_match.group(1).upper()

        return status_type, gate
