"""Tests confirming every centralized message template carries its assigned
emoji prefix, and that the scheme is applied consistently."""
import os
import sys

sys.path.append(os.path.abspath(os.getcwd()))

from app.models.models import StatusType
from app.utils import notify_templates as tmpl


def test_subscribed_reply_has_emoji():
    msg = tmpl.subscribed_reply("LOS", "ACC", 80000)
    assert msg.startswith(tmpl.EMOJI_SUBSCRIBED)
    assert "LOS->ACC" in msg
    assert "80,000" in msg


def test_subscribed_reply_no_target_price():
    msg = tmpl.subscribed_reply("LOS", "ACC", None)
    assert msg.startswith(tmpl.EMOJI_SUBSCRIBED)
    assert "any price drop" in msg


def test_tracking_reply_has_emoji():
    msg = tmpl.tracking_reply("P47123")
    assert msg.startswith(tmpl.EMOJI_SUBSCRIBED)
    assert "P47123" in msg


def test_fare_found_reply_has_emoji():
    msg = tmpl.fare_found_reply("LOS", "ACC", 185000, "NGN", 123.45, "Air Peace (mock)")
    assert msg.startswith(tmpl.EMOJI_FARE_FOUND)
    assert "185,000" in msg
    assert "123.45" in msg


def test_no_route_and_no_fare_data_share_the_no_data_emoji():
    msg1 = tmpl.no_route_reply("LOS", "ACC")
    msg2 = tmpl.no_fare_data_reply("LOS", "ACC")
    assert msg1.startswith(tmpl.EMOJI_NO_DATA)
    assert msg2.startswith(tmpl.EMOJI_NO_DATA)
    # ...and are visually distinct from a found fare, so a user never
    # mistakes "no data" for a real price.
    assert not msg1.startswith(tmpl.EMOJI_FARE_FOUND)


def test_report_logged_reply_has_emoji():
    msg = tmpl.report_logged_reply("boarding", "12", "P47123")
    assert msg.startswith(tmpl.EMOJI_REPORT_LOGGED)
    assert "gate 12" in msg
    assert "P47123" in msg


def test_rate_limited_and_unclear_replies_have_distinct_emoji():
    rl = tmpl.rate_limited_reply()
    unclear = tmpl.unclear_report_reply()
    assert rl.startswith(tmpl.EMOJI_RATE_LIMITED)
    assert unclear.startswith(tmpl.EMOJI_UNCLEAR)
    assert rl != unclear


def test_fare_drop_push_has_emoji_distinct_from_fare_found():
    msg = tmpl.fare_drop_push("LOS", "ACC", 70000, "NGN", 46.67, "Air Peace (mock)")
    assert msg.startswith(tmpl.EMOJI_FARE_DROP)
    # Pushes and query replies must look different at a glance.
    assert tmpl.EMOJI_FARE_DROP != tmpl.EMOJI_FARE_FOUND


def test_status_confirmed_push_uses_correct_emoji_per_type():
    boarding = tmpl.status_confirmed_push("P47123", StatusType.BOARDING, "12")
    gate = tmpl.status_confirmed_push("P47123", StatusType.GATE_CHANGE, "B4")
    delay = tmpl.status_confirmed_push("P47123", StatusType.DELAY, None)
    not_boarding = tmpl.status_confirmed_push("P47123", StatusType.NOT_BOARDING, None)
    other = tmpl.status_confirmed_push("P47123", StatusType.OTHER, None)

    assert boarding.startswith(tmpl.STATUS_PUSH_EMOJI[StatusType.BOARDING])
    assert gate.startswith(tmpl.STATUS_PUSH_EMOJI[StatusType.GATE_CHANGE])
    assert delay.startswith(tmpl.STATUS_PUSH_EMOJI[StatusType.DELAY])
    assert not_boarding.startswith(tmpl.STATUS_PUSH_EMOJI[StatusType.NOT_BOARDING])
    assert other.startswith(tmpl.STATUS_PUSH_EMOJI[StatusType.OTHER])

    # Every status type must map to a genuinely distinct emoji.
    emojis = list(tmpl.STATUS_PUSH_EMOJI.values())
    assert len(emojis) == len(set(emojis))

    assert "gate 12" in boarding
    assert "to B4" in gate


def test_help_text_intentionally_has_no_emoji():
    """Plain instructions - see notify_templates.py docstring for why HELP
    is exempt from the scheme."""
    from app.services.bot_router import HELP_TEXT
    first_line = HELP_TEXT.strip().splitlines()[0]
    assert first_line == "NaijaFly commands:"
