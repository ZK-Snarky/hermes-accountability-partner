"""DEMO ONLY. Two stand-in tools for filming: today's commits on a sample repo, and a test-mode
wallet that moves no money. Nothing here touches the network."""

import json
import uuid
from datetime import date


def _commits(args, **_):
    repo = args.get("repo") or "maya/side-project"
    today = date.today().isoformat()
    return json.dumps({"repo": repo, "date": today, "commits": [
        {"sha": "4f2c9a1", "message": "Add streak badge to the dashboard", "time": f"{today}T19:42:10"},
        {"sha": "b81e03d", "message": "Fix timezone bug in reminders", "time": f"{today}T20:15:33"},
    ]})


def _send(args, **_):
    return json.dumps({"status": "sent", "mode": "TEST (no real money)",
                       "amount": args.get("amount"), "to": args.get("to"),
                       "memo": args.get("memo", ""), "tx": "test_" + uuid.uuid4().hex[:10]})


def register(ctx):
    ctx.register_tool(name="demo_github_commits_today", toolset="demo", handler=_commits,
                      description="DEMO: list today's commits on a GitHub repo.", schema={
        "name": "demo_github_commits_today", "description": "DEMO: list today's commits on a GitHub repo.",
        "parameters": {"type": "object", "properties": {"repo": {"type": "string"}}, "required": []}})
    ctx.register_tool(name="demo_wallet_send", toolset="demo", handler=_send,
                      description="DEMO test-mode wallet: send money (no real money moves).", schema={
        "name": "demo_wallet_send", "description": "DEMO test-mode wallet: send money (no real money moves).",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number"}, "to": {"type": "string"}, "memo": {"type": "string"}},
            "required": ["amount", "to"]}})
