import re
from app.models.models import StatusType

class MessageParser:
    @staticmethod
    def parse(text: str):
        text = text.lower()
        status_type = StatusType.OTHER
        gate = None

        # Boarding detection — expanded for natural language
        boarding_keywords = [
            "boarding now", "started boarding", "boarding started",
            "boarding has started", "they're boarding", "they are boarding",
            "now boarding", "begin boarding", "began boarding",
            "boarding pass", "boarding the plane", "boarding gate",
            "we're boarding", "we are boarding",
            "passengers boarding", "boarding announced",
        ]
        not_boarding_keywords = [
            "not boarding", "still waiting", "gate closed",
            "no boarding", "hasn't started", "not yet",
            "still at gate", "no movement", "sitting at gate",
            "waiting to board", "haven't started",
            "no announcement", "still on the plane",
        ]
        delay_keywords = [
            "delay", "delayed", "pushed back", "push back",
            "later", "held up", "running late",
            "minutes late", "hour late", "hrs late", "hr late",
            "reschedule", "postpone", "wait",
            "further notice", "indefinite", "standby",
        ]
        gate_change_keywords = [
            "gate changed", "gate change", "new gate",
            "different gate", "gate moved", "gate is now",
            "changed gates", "reassigned", "walk to",
            "go to gate", "new boarding gate",
        ]

        if any(kw in text for kw in not_boarding_keywords):
            status_type = StatusType.NOT_BOARDING
        elif any(kw in text for kw in boarding_keywords):
            status_type = StatusType.BOARDING
        elif any(kw in text for kw in delay_keywords):
            status_type = StatusType.DELAY
        elif any(kw in text for kw in gate_change_keywords):
            status_type = StatusType.GATE_CHANGE

        # Extract gate number (e.g. "gate 12", "gate changed to E5",
        # "gate B3", "at gate 12", "now at E5")
        gate_patterns = [
            r"gate\s*(?:changed\s*(?:to\s*)?|to\s+|is\s+(?:now\s+)?|at\s+|now\s+at\s+)?([a-zA-Z0-9]{1,4})\b",
            r"at\s+([a-zA-Z][0-9]{1,3}|[0-9]{1,3})\b",
        ]
        for pat in gate_patterns:
            gate_match = re.search(pat, text)
            if gate_match:
                gate = gate_match.group(1).upper()
                break

        return status_type, gate
