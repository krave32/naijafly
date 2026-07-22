import re

# Mocking StatusType for pure python test
class StatusType:
    BOARDING = "boarding"
    GATE_CHANGE = "gate_change"
    DELAY = "delay"
    NOT_BOARDING = "not_boarding"
    OTHER = "other"

class MessageParser:
    @staticmethod
    def parse(text: str):
        text = text.lower()
        status_type = StatusType.OTHER
        gate = None

        if any(kw in text for kw in ["boarding now", "started boarding", "boarding started"]):
            status_type = StatusType.BOARDING
        elif any(kw in text for kw in ["not boarding", "still waiting", "gate closed"]):
            status_type = StatusType.NOT_BOARDING
        elif any(kw in text for kw in ["delay", "delayed", "pushed back"]):
            status_type = StatusType.DELAY
        elif any(kw in text for kw in ["gate changed", "gate change", "new gate"]):
            status_type = StatusType.GATE_CHANGE

        gate_match = re.search(r"gate\s*(?:changed\s*|to\s*|is\s*)*([a-zA-Z0-9]{1,4})\b", text)
        if gate_match:
            gate = gate_match.group(1).upper()

        return status_type, gate

def test_parser():
    parser = MessageParser()
    
    status, gate = parser.parse("Boarding now gate 12")
    assert status == StatusType.BOARDING
    assert gate == "12"
    
    status, gate = parser.parse("Gate changed to E5")
    assert status == StatusType.GATE_CHANGE
    assert gate == "E5"
    
    status, gate = parser.parse("2hr delay announced")
    assert status == StatusType.DELAY
    
    print("Parser tests passed!")

if __name__ == "__main__":
    test_parser()
