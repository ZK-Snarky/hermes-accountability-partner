from datetime import date, datetime, timedelta

import pytest

from accountability_partner import answers, partner
from accountability_partner import __init__ as _unused  # noqa: F401  (package import check)
from accountability_partner.ledger import Ledger

MON = date(2026, 11, 2)


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.db")


def _add(ledger, msg, **args):
    return partner.add(ledger, args, msg, MON)


def test_promise_needs_the_users_own_words(ledger):
    msg = "ok from now on I'll make 40 calls every weekday"
    bad = _add(ledger, msg, what="Calls", cadence="daily", user_quote="I'll make 50 calls")
    assert bad["ok"] is False and ledger.active() == []
    good = _add(ledger, msg, what="Make 40 calls", cadence="daily", user_quote="I'll make 40 calls")
    assert good["ok"] and good["saved"] == "Make 40 calls (daily)"


def test_quote_check_ignores_case_and_punctuation():
    assert partner.said("i'll go to the GYM", "Fine. I’ll go to the gym, 3x!")
    assert not partner.said("gym", "gym")  # too short to prove anything
    assert not partner.said("I'll go to the gym", None)


def test_record_refuses_the_agents_own_judgment(ledger):
    p = _add(ledger, "I will read 20 pages a day", what="Read", cadence="daily",
             user_quote="I will read 20 pages")
    out = partner.record(ledger, {"results": [{"id": p["id"], "kept": True}],
                                  "user_quote": "looks like he read"}, "what's the weather", MON)
    assert out["ok"] is False and ledger.day_report(p["id"], MON) is None


def test_checkin_then_one_tap_answer(ledger):
    a = _add(ledger, "I'll make 40 calls a day or no Netflix", what="Make 40 calls", cadence="daily",
             consequence="no Netflix", user_quote="I'll make 40 calls a day")
    b = _add(ledger, "gym 3x a week, if I miss I owe $20 to charity", what="Gym", cadence="weekly",
             per_week=3, consequence="$20 to charity", user_quote="gym 3x a week")
    text = partner.checkin(ledger, MON)
    assert "1. Make 40 calls?" in text and "2. Gym today? (0 of 3 this week)" in text
    line = partner.answer_from_reply(ledger, "no yes", MON)
    assert ledger.day_report(a["id"], MON) is False and ledger.day_report(b["id"], MON) is True
    assert "no Netflix" in line and ledger.pending() is None


def test_sentences_and_partial_answers_are_left_alone(ledger):
    _add(ledger, "I'll make 40 calls a day", what="Calls", cadence="daily", user_quote="40 calls a day")
    _add(ledger, "and stretch every day", what="Stretch", cadence="daily", user_quote="stretch every day")
    partner.checkin(ledger, MON)
    assert partner.answer_from_reply(ledger, "yes", MON) is None
    assert partner.answer_from_reply(ledger, "yes I think so, mostly", MON) is None
    assert ledger.pending() is not None


def test_nothing_to_ask_is_silent(ledger):
    assert partner.checkin(ledger, MON) == partner.SILENT
    assert partner.weekly_report(ledger, MON) == partner.SILENT


def test_weekly_goal_met_stops_asking(ledger):
    p = _add(ledger, "swim twice a week", what="Swim", cadence="weekly", per_week=2,
             user_quote="swim twice a week")
    for day in (MON, MON + timedelta(days=1)):
        ledger.report(p["id"], day, True, "yes")
    assert partner.to_ask(ledger, MON + timedelta(days=2)) == []
    assert partner.to_ask(ledger, MON + timedelta(days=7))  # new week


def test_streak_and_weekly_receipt(tmp_path):
    ledger = Ledger(tmp_path / "l.db")
    p = ledger.add("Calls", "daily", "40 calls a day", consequence="no Netflix",
                   now=datetime(2026, 11, 2, 9))
    sun = MON + timedelta(days=6)
    for i, kept in enumerate([True, True, False, True, True]):
        ledger.report(p.id, MON + timedelta(days=i), kept, "yes")
    assert ledger.streak(p.id, MON + timedelta(days=4)) == 2
    text = partner.weekly_report(ledger, sun)
    assert "Calls: 4 of 7 days, 2 with no answer" in text
    assert "You said 7, you did 4." in text and "no Netflix" in text


def test_drop_needs_words_too(ledger):
    p = _add(ledger, "I'll meditate daily", what="Meditate", cadence="daily",
             user_quote="I'll meditate daily")
    assert partner.drop(ledger, {"id": p["id"], "user_quote": "drop meditate"}, "hi")["ok"] is False
    assert partner.drop(ledger, {"id": p["id"], "user_quote": "drop meditation"},
                        "please drop meditation for now")["ok"]
    assert ledger.active() == []


@pytest.mark.parametrize("text,count,expected", [
    ("yes no yes", 3, [True, False, True]),
    ("Y, n", 2, [True, False]),
    ("✅❌", 2, [True, False]),
    ("all done!", 3, [True, True, True]),
    ("1 yes 2 no", 2, [True, False]),
    ("didn't", 1, [False]),
    ("yes no", 3, None),
    ("yes but barely", 1, None),
])
def test_parse(text, count, expected):
    assert answers.parse(text, count) == expected


def test_weekdays_skip_the_weekend(ledger):
    p = _add(ledger, "I'll make 40 calls every weekday", what="Calls", cadence="weekdays",
             user_quote="40 calls every weekday")
    fri, sat, mon2 = MON + timedelta(days=4), MON + timedelta(days=5), MON + timedelta(days=7)
    assert partner.to_ask(ledger, sat) == []
    ledger.report(p["id"], fri, True, "yes")
    ledger.report(p["id"], mon2, True, "yes")
    assert ledger.streak(p["id"], mon2, weekdays_only=True) == 2


def test_weekly_day_miss_names_no_consequence(ledger):
    _add(ledger, "gym 3x a week or I owe $20", what="Gym", cadence="weekly", per_week=3,
         consequence="$20", user_quote="gym 3x a week")
    partner.checkin(ledger, MON)
    assert "$20" not in partner.answer_from_reply(ledger, "no", MON)


def test_a_no_cant_be_quoted_into_a_yes(ledger):
    p = _add(ledger, "gym 3x a week", what="Gym", cadence="weekly", per_week=3,
             user_quote="gym 3x a week")
    msg = "I didn't go to the gym today"
    out = partner.record(ledger, {"results": [{"id": p["id"], "kept": True}],
                                  "user_quote": "go to the gym"}, msg, MON)
    assert out["ok"] is False and ledger.day_report(p["id"], MON) is None
    out = partner.record(ledger, {"results": [{"id": p["id"], "kept": False}],
                                  "user_quote": "didn't go to the gym"}, msg, MON)
    assert out["ok"] and ledger.day_report(p["id"], MON) is False
    assert partner.record(ledger, {"results": [{"id": p["id"], "kept": True}],
                                   "user_quote": "went to the gym"}, "went to the gym today",
                          MON)["ok"]


def test_mixed_answer_still_records_the_yes(ledger):
    p = _add(ledger, "40 calls every weekday", what="Calls", cadence="weekdays",
             user_quote="40 calls every weekday")
    msg = "did my 40 calls, but no gym today"
    assert partner.record(ledger, {"results": [{"id": p["id"], "kept": True}],
                                   "user_quote": "did my 40 calls"}, msg, MON)["ok"]
