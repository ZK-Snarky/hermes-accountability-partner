"""DEMO ONLY. Stand-in tools for filming: today's commits on a sample repo, today's WHOOP workouts,
and a test-mode wallet that moves no money. Nothing here touches the network.

Demo clock: set DEMO_TODAY=YYYY-MM-DD to film a week in minutes. It sets the Accountability
Partner's today() (its one date source) and the sample commits' date; the real clock, and so the
lock cool-off, stay real. Unset, everything uses the real date. DEMO_GITHUB_EMPTY=1 films a day with no commits."""

import json
import os
import sys
import uuid
from datetime import date


def _today() -> date:
    value = os.environ.get("DEMO_TODAY")
    return date.fromisoformat(value) if value else date.today()


def _set_clock(**_):
    """Point the Accountability Partner's today() at the demo clock (it may load after us)."""
    if not os.environ.get("DEMO_TODAY"):
        return
    for name, mod in list(sys.modules.items()):
        if name.endswith("accountability_partner") and callable(getattr(mod, "ledger", None)):
            mod.today = _today


def _commits(args, **_):
    repo = args.get("repo") or "maya/side-project"
    today = _today().isoformat()
    if os.environ.get("DEMO_GITHUB_EMPTY"):  # film a day with nothing pushed
        return json.dumps({"repo": repo, "date": today, "commits": []})
    return json.dumps({"repo": repo, "date": today, "commits": [
        {"sha": "4f2c9a1", "message": "Add streak badge to the dashboard", "time": f"{today}T19:42:10"},
        {"sha": "b81e03d", "message": "Fix timezone bug in reminders", "time": f"{today}T20:15:33"},
    ]})


def _whoop(args, **_):
    today = _today().isoformat()
    return json.dumps({"source": "WHOOP", "date": today, "workouts": [
        {"sport": "Running", "start": f"{today}T07:12:00", "minutes": 42, "strain": 11.8,
         "avg_hr": 151}]})


def _send(args, **_):
    return json.dumps({"status": "sent", "mode": "TEST (no real money)",
                       "amount": args.get("amount"), "to": args.get("to"),
                       "memo": args.get("memo", ""), "tx": "test_" + uuid.uuid4().hex[:10]})


def register(ctx):
    _set_clock()
    ctx.register_hook("pre_llm_call", _set_clock)
    ctx.register_tool(name="demo_github_commits_today", toolset="demo", handler=_commits,
                      description="DEMO: list today's commits on a GitHub repo.", schema={
        "name": "demo_github_commits_today", "description": "DEMO: list today's commits on a GitHub repo.",
        "parameters": {"type": "object", "properties": {"repo": {"type": "string"}}, "required": []}})
    ctx.register_tool(name="demo_whoop_workouts_today", toolset="demo", handler=_whoop,
                      description="DEMO: list today's workouts from WHOOP.", schema={
        "name": "demo_whoop_workouts_today", "description": "DEMO: list today's workouts from WHOOP.",
        "parameters": {"type": "object", "properties": {}, "required": []}})
    ctx.register_tool(name="demo_wallet_send", toolset="demo", handler=_send,
                      description="DEMO test-mode wallet: send money (no real money moves).", schema={
        "name": "demo_wallet_send", "description": "DEMO test-mode wallet: send money (no real money moves).",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number"}, "to": {"type": "string"}, "memo": {"type": "string"}},
            "required": ["amount", "to"]}})
