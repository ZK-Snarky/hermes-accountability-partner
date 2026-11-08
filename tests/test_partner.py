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
         consequence="I owe $20", user_quote="gym 3x a week")
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


def test_receipt_must_come_from_a_real_tool_result(ledger):
    p = _add(ledger, "I'll ship code every weekday", what="Ship code", cadence="weekdays",
             proof="GitHub commits today", user_quote="ship code every weekday")
    assert partner.prove_first(ledger, MON) == [{"id": p["id"], "what": "Ship code",
                                                 "proof": "GitHub commits today"}]
    seen = [("github_list_commits", '[{"sha": "a1b2", "message": "Add nightly check-in", "date": "2026-11-02"}]')]
    made_up = partner.prove(ledger, {"id": p["id"], "source_tool": "github_list_commits",
                                     "evidence": "Fix login bug"}, seen, MON)
    wrong_tool = partner.prove(ledger, {"id": p["id"], "source_tool": "strava_activities",
                                        "evidence": "Add nightly check-in"}, seen, MON)
    assert made_up["ok"] is False and wrong_tool["ok"] is False
    good = partner.prove(ledger, {"id": p["id"], "source_tool": "github_list_commits",
                                  "evidence": '"message": "Add nightly check-in"'}, seen, MON)
    assert good["ok"] and ledger.receipt(p["id"], MON) == "github_list_commits"
    assert partner.prove_first(ledger, MON) == []
    text = partner.checkin(ledger, MON)
    assert "✓ Ship code: seen in github list commits" in text and "Everything is proven" in text


def test_receipts_counted_in_weekly_receipt(ledger):
    p = _add(ledger, "run 3x a week", what="Run", cadence="weekly", per_week=3,
             proof="Strava", user_quote="run 3x a week")
    partner.prove(ledger, {"id": p["id"], "source_tool": "strava", "evidence": "Morning Run 5.2 km"},
                  [("strava", "Morning Run 5.2 km 27:10")], MON)
    ledger.report(p["id"], MON + timedelta(days=2), True, "yes")
    assert "You said 3, you did 2 (1 with receipts)." in partner.weekly_report(ledger, MON + timedelta(days=2))


def test_consequence_is_enforced_only_with_proof(ledger):
    p = _add(ledger, "stretch daily or send $20 to charity from my wallet", what="Stretch",
             cadence="daily", consequence="send $20 to charity from my wallet", user_quote="stretch daily")
    partner.checkin(ledger, MON)
    line = partner.answer_from_reply(ledger, "no", MON)
    assert "send $20 to charity" in line and "promise_enforced" in line
    assert partner.owed(ledger, MON) == [{"id": p["id"], "what": "Stretch",
                                          "consequence": "send $20 to charity from my wallet",
                                          "for": MON.isoformat()}]
    wallet = [("wallet_send", '{"status": "sent", "amount": "20.00", "tx": "0x9a3f"}')]
    assert partner.enforced(ledger, {"id": p["id"], "source_tool": "wallet_send",
                                     "evidence": '"tx": "0xdead"'}, wallet, MON)["ok"] is False
    assert "not enforced yet" in partner.weekly_report(ledger, MON)
    ok = partner.enforced(ledger, {"id": p["id"], "source_tool": "wallet_send",
                                   "evidence": '"status": "sent", "amount": "20.00"'}, wallet, MON)
    assert ok["ok"] and partner.owed(ledger, MON) == []
    assert "send $20 to charity from my wallet, done ✓ (wallet send)" in partner.weekly_report(ledger, MON)


def _locked_gym(ledger, tmp_now=None):
    p = _add(ledger, "gym every day, if I miss send $20 to GiveDirectly", what="Gym", cadence="daily",
             consequence="send $20 to GiveDirectly", enforcer_tool="wallet_send", max_amount=20,
             pay_to="GiveDirectly", user_quote="gym every day")
    return p


def test_lock_needs_explicit_words_and_rails(ledger):
    p = _locked_gym(ledger)
    until = (MON + timedelta(days=30)).isoformat()
    assert partner.lock(ledger, {"id": p["id"], "until": until, "user_quote": "gym every day"},
                        "gym every day", MON)["ok"] is False
    assert partner.lock(ledger, {"id": p["id"], "until": (MON + timedelta(days=200)).isoformat(),
                                 "user_quote": "lock it in"}, "lock it in", MON)["ok"] is False
    out = partner.lock(ledger, {"id": p["id"], "until": until, "user_quote": "lock it in, hold me to it"},
                       "ok lock it in, hold me to it", MON)
    assert out["ok"] and "without asking again" in out["tell_the_user"]


def test_locked_promise_cant_be_dropped_after_cool_off(ledger):
    p = _locked_gym(ledger)
    ledger.lock(p["id"], date.today() + timedelta(days=30), now=datetime.now() - timedelta(hours=25))
    out = partner.drop(ledger, {"id": p["id"], "user_quote": "drop the gym one"}, "drop the gym one")
    assert out["ok"] is False and "locked in" in out["error"]
    q = _add(ledger, "read daily", what="Read", cadence="daily", user_quote="read daily")
    ledger.lock(q["id"], date.today() + timedelta(days=30))  # still in cool-off
    assert partner.drop(ledger, {"id": q["id"], "user_quote": "drop reading"}, "drop reading")["ok"]


def test_guard_holds_the_wallet_to_the_rails(ledger):
    p = _locked_gym(ledger)
    assert partner.guard(ledger, "wallet_send", {"amount": 500, "to": "Bob"}, MON) is None  # nothing owed
    ledger.report(p["id"], MON, False, "no")
    too_much = partner.guard(ledger, "wallet_send", {"amount": "$50", "to": "GiveDirectly"}, MON)
    wrong_payee = partner.guard(ledger, "wallet_send", {"amount": 20, "to": "Bob"}, MON)
    assert too_much["action"] == "block" and wrong_payee["action"] == "block"
    # not locked in: the user's yes is required
    assert partner.guard(ledger, "wallet_send", {"amount": 20, "to": "GiveDirectly"}, MON)["action"] == "approve"
    ledger.lock(p["id"], date.today() + timedelta(days=30), now=datetime.now() - timedelta(hours=25))
    today = date.today()
    ledger.report(p["id"], today, False, "no")
    assert partner.guard(ledger, "wallet_send", {"amount": 20, "to": "GiveDirectly"}, today) is None
    assert partner.owed(ledger, today)[-1]["locked_in"] is True


def test_consequence_must_be_the_users_words(ledger):
    msg = "gym 3x a week. If I miss the gym, send $20 to GiveDirectly."
    out = _add(ledger, msg, what="Gym", cadence="weekly", per_week=3, user_quote="gym 3x a week",
               consequence="$20 for each workout short of three")
    assert out["ok"] is False and ledger.active() == []


def test_hedge_is_not_a_yes(ledger):
    p = _add(ledger, "gym 3x a week", what="Gym", cadence="weekly", per_week=3,
             user_quote="gym 3x a week")
    out = partner.record(ledger, {"results": [{"id": p["id"], "kept": True}],
                                  "user_quote": "did the gym"}, "I basically did the gym, just mark it done", MON)
    assert out["ok"] is False and "hedge" in out["error"]


def test_starts_tomorrow_isnt_asked_tonight(ledger):
    p = _add(ledger, "Starting tomorrow I'll stretch daily", what="Stretch", cadence="daily",
             starts=(MON + timedelta(days=1)).isoformat(), user_quote="I'll stretch daily")
    assert p["saved"] == "Stretch (daily, from Nov 3)"
    assert partner.checkin(ledger, MON) == partner.SILENT
    assert partner.to_ask(ledger, MON + timedelta(days=1))


def test_yes_confirms_the_promise_said_just_before(ledger):
    two = "gym 3x a week, every week\nyes, save it"
    assert _add(ledger, two, what="Gym", cadence="weekly", per_week=3, user_quote="gym 3x a week")["ok"]


def test_tools_work_through_the_real_ledger_setup(tmp_path, monkeypatch):
    """The plugin's own handlers, not just partner.py: catches wiring bugs like a name clash."""
    import json
    import accountability_partner as plugin
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(plugin, "_ledger", None)
    plugin.on_pre_llm_call(session_id="s", user_message="I'll read 10 pages every day")
    out = json.loads(plugin._add({"what": "Read", "cadence": "daily",
                                  "user_quote": "read 10 pages every day"}, session_id="s"))
    assert out["ok"], out
    for _name, handler, *_ in plugin.TOOLS:
        json.loads(handler({}, session_id="s"))  # every tool answers, none crashes
    assert "Read" in plugin._promises_command("")


def test_plain_yes_answers_a_direct_question(ledger):
    p = _add(ledger, "gym 3x a week", what="Gym", cadence="weekly", per_week=3,
             user_quote="gym 3x a week")
    ok = partner.record(ledger, {"results": [{"id": p["id"], "kept": True}], "user_quote": "yes"},
                        "I basically did the gym\nyes", MON)
    assert ok["ok"] and ledger.day_report(p["id"], MON) is True
    # a "no" can't be turned into a kept
    assert partner.record(ledger, {"results": [{"id": p["id"], "kept": True}], "user_quote": "no"},
                          "no", MON)["ok"] is False


def test_nothing_recorded_before_a_promise_starts(ledger):
    p = _add(ledger, "starting tomorrow gym 3x a week", what="Gym", cadence="weekly", per_week=3,
             starts=(MON + timedelta(days=1)).isoformat(), user_quote="gym 3x a week")
    out = partner.record(ledger, {"results": [{"id": p["id"], "kept": True}], "user_quote": "yes"},
                         "yes", MON)
    assert out["ok"] is False and ledger.day_report(p["id"], MON) is None


def test_compact_json_quote_matches_spaced_tool_output():
    result = '{"status": "sent", "amount": 20, "ok": true, "tx": "test_e84c91ad92"}'
    quote = '{"status":"sent","amount":20,"ok":true,"tx":"test_e84c91ad92"}'
    assert partner._tool_said("wallet_send", quote, [("wallet_send", result)]) is None
    assert partner._tool_said("wallet_send", '"amount":25', [("wallet_send", result)]) is not None


WHOOP = "whoop_workouts_today"


def _whoop(minutes, sport="Running"):
    import json
    return json.dumps({"date": "2026-11-09", "workouts": [{"sport": sport, "minutes": minutes}]})


def _ruled(ledger, day, rule="minutes >= 30"):
    msg = "I'll work out every day, a 30 minute WHOOP workout counts"
    out = partner.add(ledger, {"what": "Work out", "cadence": "daily", "user_quote": msg,
                               "proof_tool": WHOOP, "rule": rule}, msg, day)
    assert out["ok"], out
    return out["id"]


def test_rule_decides_from_the_tools_data(ledger):
    day = date(2026, 11, 9)
    pid = _ruled(ledger, day)
    out = partner.prove(ledger, {"id": pid}, [(WHOOP, _whoop(42))], day)
    assert out["ok"] and out["evidence"] == "minutes 42"
    assert "seen in whoop workouts today (minutes 42, rule minutes >= 30)" in partner.checkin(ledger, day)


def test_rule_not_met_is_asked_not_missed(ledger):
    day = date(2026, 11, 10)
    pid = _ruled(ledger, day)
    out = partner.prove(ledger, {"id": pid}, [(WHOOP, _whoop(18))], day)
    assert not out["ok"] and "minutes 18" in out["not_proven"]
    assert ledger.day_report(pid, day) is None  # never recorded as a miss
    text = partner.checkin(ledger, day)
    assert "Work out?" in text and "whoop workouts today shows minutes 18; your rule: minutes >= 30" in text


def test_rule_needs_its_tool_called_and_ignores_the_models_quote(ledger):
    day = date(2026, 11, 9)
    pid = _ruled(ledger, day)
    assert not partner.prove(ledger, {"id": pid, "evidence": "minutes 42"}, [], day)["ok"]
    other = partner.prove(ledger, {"id": pid}, [("other_tool", _whoop(42))], day)
    assert not other["ok"]


def test_rule_with_two_parts_and_wrapped_json(ledger):
    import json
    day = date(2026, 11, 9)
    pid = _ruled(ledger, day, "sport = running and minutes >= 30")
    walk = json.dumps({"content": [{"type": "text", "text": _whoop(50, "Walking")}]})
    assert not partner.prove(ledger, {"id": pid}, [(WHOOP, walk)], day)["ok"]
    run = json.dumps({"content": [{"type": "text", "text": _whoop(31)}]})
    assert partner.prove(ledger, {"id": pid}, [(WHOOP, run)], day)["ok"]


def test_bad_rule_or_missing_tool_is_refused(ledger):
    day = date(2026, 11, 9)
    msg = "I'll work out every day"
    base = {"what": "Work out", "cadence": "daily", "user_quote": msg}
    assert not partner.add(ledger, {**base, "rule": "minutes >= 30"}, msg, day)["ok"]
    assert not partner.add(ledger, {**base, "proof_tool": WHOOP, "rule": "lots of minutes"}, msg, day)["ok"]
    assert not partner.add(ledger, {**base, "proof_tool": WHOOP, "rule": "minutes >= thirty"}, msg, day)["ok"]


def test_rule_on_a_list_counts_its_items(ledger):
    import json
    day = date(2026, 11, 9)
    msg = "I'll push code every day, a commit to maya/side-project counts"
    pid = partner.add(ledger, {"what": "Push code", "cadence": "daily", "user_quote": msg,
                               "proof_tool": "gh", "rule": "repo = maya/side-project and commits >= 1"},
                      msg, day)["id"]
    none = json.dumps({"repo": "maya/side-project", "commits": []})
    out = partner.prove(ledger, {"id": pid}, [("gh", none)], day)
    assert not out["ok"] and "commits 0" in out["not_proven"] and "[" not in out["not_proven"]
    two = json.dumps({"repo": "maya/side-project", "commits": [{"sha": "a"}, {"sha": "b"}]})
    out = partner.prove(ledger, {"id": pid}, [("gh", two)], day)
    assert out["ok"] and out["evidence"] == "repo maya/side-project, commits 2"


def test_label_only_rule_is_refused_and_rules_read_back_in_words(ledger):
    day = date(2026, 11, 9)
    msg = "I'll push code every day, a commit to my-app counts"
    base = {"what": "Push code", "cadence": "daily", "user_quote": msg, "proof_tool": "gh"}
    out = partner.add(ledger, {**base, "rule": "repo = my-app"}, msg, day)
    assert not out["ok"] and "commits >= 1" in out["error"]
    out = partner.add(ledger, {**base, "rule": "repo = my-app and commits >= 1"}, msg, day)
    assert out["tell_the_user"] == "It counts when gh shows repo is my-app and commits at least 1."


def test_lock_text_quotes_a_sentence_consequence(ledger):
    day = date(2026, 11, 9)
    msg = "I'll push code every day. If I miss a day, send $20 to GiveDirectly. Hold me to it, lock it in"
    pid = partner.add(ledger, {"what": "Push code", "cadence": "daily", "user_quote": msg,
                               "consequence": "If I miss a day, send $20 to GiveDirectly",
                               "enforcer_tool": "wallet_send", "max_amount": 20}, msg, day)["id"]
    out = partner.lock(ledger, {"id": pid, "until": "2026-12-01", "user_quote": "lock it in"}, msg, day)
    assert '("If I miss a day, send $20 to GiveDirectly")' in out["tell_the_user"]


def test_len_or_count_in_a_rule_reads_as_the_list_count():
    assert partner.parse_rule("count(commits) >= 1") == partner.parse_rule("commits >= 1")
    assert partner.parse_rule("len(commits) >= 1") == [("commits", ">=", 1.0)]


def test_not_proven_tells_the_agent_to_ask_now(ledger):
    day = date(2026, 11, 10)
    pid = _ruled(ledger, day)
    out = partner.prove(ledger, {"id": pid}, [(WHOOP, _whoop(18))], day)
    assert "yes or no" in out["not_proven"] and "promise_record" in out["not_proven"]


def test_a_host_can_supply_the_ledger(tmp_path, monkeypatch):
    import json
    import accountability_partner as plugin
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    hosted = Ledger(tmp_path / "host.db")
    plugin.use_ledger(lambda: hosted)
    try:
        plugin.on_pre_llm_call(session_id="h", user_message="I'll read 10 pages every day")
        out = json.loads(plugin._add({"what": "Read", "cadence": "daily",
                                      "user_quote": "read 10 pages every day"}, session_id="h"))
        assert out["ok"] and [p.what for p in hosted.active()] == ["Read"]
        assert not (tmp_path / "home" / "plugin-data").exists()
    finally:
        plugin.use_ledger(None)


def test_checkin_fetches_the_data_itself(ledger):
    day = date(2026, 11, 9)
    msg = "I'll work out every day, a 30 minute WHOOP workout counts"
    pid = partner.add(ledger, {"what": "Work out", "cadence": "daily", "user_quote": msg,
                               "proof_tool": WHOOP, "proof_args": {"days": 1},
                               "rule": "minutes >= 30"}, msg, day)["id"]
    calls = []

    def fetch(tool, args):
        calls.append((tool, args))
        return _whoop(42)
    assert partner.check_by_fetching(ledger, day, fetch) == []
    assert calls == [(WHOOP, {"days": 1})]
    assert partner.prove_first(ledger, day) == []
    assert "✓ Work out: seen in whoop workouts today (minutes 42" in partner.checkin(ledger, day)
    assert ledger.day_report(pid, day) is True


def test_short_data_fetched_is_asked_and_a_failing_tool_is_left_to_the_agent(ledger):
    day = date(2026, 11, 10)
    short = _ruled(ledger, day)
    msg = "I'll stretch every day, a 10 minute session counts"
    broken = partner.add(ledger, {"what": "Stretch", "cadence": "daily", "user_quote": msg,
                                  "proof_tool": "stretch_log", "rule": "minutes >= 10"}, msg, day)["id"]

    def fetch(tool, args):
        if tool == "stretch_log":
            raise RuntimeError("not connected")
        return _whoop(18)
    assert partner.check_by_fetching(ledger, day, fetch) == [broken]
    assert [p["id"] for p in partner.prove_first(ledger, day)] == [broken]
    assert ledger.day_report(short, day) is None
    assert "shows minutes 18; your rule: minutes >= 30" in partner.checkin(ledger, day)


def test_a_promise_or_consequence_tool_cant_be_proof(ledger):
    day = date(2026, 11, 9)
    msg = "I'll work out every day"
    base = {"what": "Work out", "cadence": "daily", "user_quote": msg, "rule": "minutes >= 30"}
    assert not partner.add(ledger, {**base, "proof_tool": "promise_list"}, msg, day)["ok"]
    assert not partner.add(ledger, {**base, "proof_tool": "wallet", "enforcer_tool": "wallet"}, msg, day)["ok"]
    assert not partner.add(ledger, {**base, "proof_tool": WHOOP, "proof_args": "days=1"}, msg, day)["ok"]


def test_the_plugin_calls_only_tools_the_user_allowed(tmp_path, monkeypatch):
    import json
    import accountability_partner as plugin

    class Ctx:
        def __init__(self):
            self.settings, self.calls = {}, []

        def get_config(self, key, default=None):
            return self.settings.get(key, default)

        def set_config(self, key, value):
            self.settings[key] = value

        def dispatch_tool(self, name, args):
            self.calls.append(name)
            return _whoop(42)
    ctx = Ctx()
    monkeypatch.setattr(plugin, "_ctx", ctx)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(plugin, "_ledger", None)
    plugin.on_pre_llm_call(session_id="s", user_message="I'll work out every day")
    out = json.loads(plugin._add({"what": "Work out", "cadence": "daily", "user_quote": "work out every day",
                                  "proof_tool": WHOOP, "rule": "minutes >= 30"}, session_id="s"))
    assert f"/promises allow {WHOOP}" in out["tell_the_user_too"]
    first = json.loads(plugin._checkin({}))
    assert ctx.calls == [] and first["prove_first"][0]["call"] == WHOOP
    plugin._promises_command(f"allow {WHOOP}")
    assert ctx.settings["proof_tools"] == [WHOOP]
    assert "✓ Work out" in json.loads(plugin._checkin({}))["message"] and ctx.calls == [WHOOP]
    plugin._promises_command(f"disallow {WHOOP}")
    assert ctx.settings["proof_tools"] == []


def test_a_claimed_done_checks_the_data_first(tmp_path, monkeypatch):
    import json
    import accountability_partner as plugin
    readings = {"m": 18}

    class Ctx:
        def get_config(self, key, default=None):
            return [WHOOP] if key == "proof_tools" else default

        def dispatch_tool(self, name, args):
            return _whoop(readings["m"])
    monkeypatch.setattr(plugin, "_ctx", Ctx())
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(plugin, "_ledger", None)
    plugin.on_pre_llm_call(session_id="s", user_message="I'll work out every day")
    pid = json.loads(plugin._add({"what": "Work out", "cadence": "daily", "user_quote": "work out every day",
                                  "proof_tool": WHOOP, "rule": "minutes >= 30"}, session_id="s"))["id"]
    plugin.on_pre_llm_call(session_id="s", user_message="I basically worked out, mark it done")
    out = json.loads(plugin._record({"results": [{"id": pid, "kept": True}],
                                     "user_quote": "I basically worked out"}, session_id="s"))
    assert not out["ok"] and "minutes 18" in out["checked_data"][0]["not_proven"]
    readings["m"] = 45
    out = json.loads(plugin._record({"results": [{"id": pid, "kept": True}],
                                     "user_quote": "I basically worked out"}, session_id="s"))
    assert out["ok"] and out["checked_data"][0]["evidence"] == "minutes 45"


def test_data_decides_makes_a_failing_reading_a_miss_at_the_checkin_only(ledger):
    day = date(2026, 11, 12)
    msg = "Keep dining under 120 this week, the data decides, if I go over send $20 to GiveDirectly"
    base = {"what": "Dining budget", "cadence": "daily", "user_quote": msg, "proof_tool": "budget",
            "rule": "spent <= 120", "data_decides": True, "consequence": "send $20 to GiveDirectly"}
    assert not partner.add(ledger, {**base, "rule": None, "proof_tool": None}, msg, day)["ok"]
    added = partner.add(ledger, base, msg, day)
    assert "the data decides" in added["tell_the_user"].lower() or "data decides" in added["tell_the_user"]
    pid = added["id"]
    over = [("budget", '{"category": "dining", "spent": 142}')]
    assert partner.prove(ledger, {"id": pid}, over, day)["ok"] is False  # mid-day: shown, not missed
    assert ledger.day_report(pid, day) is None
    assert partner.check_by_fetching(ledger, day, lambda t, a: "[]") == []  # no data: never a miss
    assert ledger.day_report(pid, day) is None
    assert partner.check_by_fetching(ledger, day, lambda t, a: over[0][1]) == []
    assert ledger.day_report(pid, day) is False
    text = partner.checkin(ledger, day)
    assert "✗ Dining budget: budget shows spent 142; rule spent <= 120 (the data decides)" in text
    assert [o["id"] for o in partner.owed(ledger, day)] == [pid]


def test_without_data_decides_a_failing_reading_is_still_asked(ledger):
    day = date(2026, 11, 12)
    msg = "Keep dining under 120"
    pid = partner.add(ledger, {"what": "Dining budget", "cadence": "daily", "user_quote": msg,
                               "proof_tool": "budget", "rule": "spent <= 120"}, msg, day)["id"]
    partner.check_by_fetching(ledger, day, lambda t, a: '{"spent": 142}')
    assert ledger.day_report(pid, day) is None
    assert "1. Dining budget?" in partner.checkin(ledger, day)


def test_a_limit_cant_be_a_weekly_promise(ledger):
    day = date(2026, 11, 9)
    msg = "Keep dining under 120 this week"
    base = {"what": "Dining budget", "user_quote": msg, "proof_tool": "budget", "rule": "spent <= 120"}
    refused = partner.add(ledger, {**base, "cadence": "weekly"}, msg, day)
    assert not refused["ok"] and "daily" in refused["error"]
    assert partner.add(ledger, {**base, "cadence": "daily"}, msg, day)["ok"]
