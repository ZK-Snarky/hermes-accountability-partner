"""Accountability Partner: Hermes holds you to what you said, in your own words.

Wiring only. The rules live in partner.py and the data in ledger.py.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional

from . import partner
from .ledger import Ledger

logger = logging.getLogger(__name__)

PLUGIN = "accountability-partner"
TOOLSET = "accountability"
_RECENT_SECONDS = 15 * 60

_lock = threading.Lock()
_ledger: Optional[Ledger] = None
_ledger_path: Optional[Path] = None
_last_said: dict[str, list[tuple[str, float]]] = {}  # session id -> last 2 (user's message, when)
_seen: dict[str, list[tuple[str, str, float]]] = {}  # session id -> [(tool, result text, when)]
_SEEN_PER_SESSION = 40
_RESULT_CHARS = 20000

GUIDE = (
    "Accountability Partner is on. When the user commits to something (\"I'll...\", \"I'm going "
    "to...\", \"every day I...\"), save it right away with promise_add, no need to ask first, "
    "quoting their exact words; then say in one line what you saved. If they said when it starts "
    "(\"starting tomorrow\"), set starts. Copy any consequence in their own words, unchanged. If "
    "one of their connected tools could show it happened (a fitness app, GitHub, a calendar, a "
    "location visit), set proof to say where to look and what counts, in the user's own rule if "
    "they gave one (\"a workout on my WHOOP counts\"). Only the user's own words add, drop or mark "
    "a promise, or a real result from one of their tools (promise_prove); never mark one kept or "
    "missed from your own reading of their day. The ledger's numbers are the score: repeat them, "
    "don't round up, and don't add disclaimers (such as what isn't set up)."
)


def _data_dir() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir
        return plugin_data_dir(PLUGIN)
    except ImportError:  # older Hermes without the storage helper
        try:
            from hermes_constants import get_hermes_home
            home = get_hermes_home()
        except ImportError:
            home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        path = Path(home) / "plugin-data" / PLUGIN
        path.mkdir(parents=True, exist_ok=True)
        return path


def ledger() -> Ledger:
    """One ledger per Hermes profile; reopened if the active profile's home changes."""
    global _ledger, _ledger_path
    path = _data_dir() / "ledger.db"
    with _lock:
        if _ledger is None or _ledger_path != path:
            _ledger, _ledger_path = Ledger(path), path
        return _ledger


def today() -> date:
    """The machine's local date (set TZ for another time zone)."""
    return date.today()


def _users_words(session_id: Optional[str]) -> Optional[str]:
    """The user's current message, plus the one before it (so "yes, save it" can confirm a promise
    they spelled out a moment ago). Only messages from the last 15 minutes count."""
    now = time.time()
    if session_id and session_id in _last_said:
        rows = _last_said[session_id]
    elif _last_said:  # no session id passed: the newest session's messages
        rows = max(_last_said.values(), key=lambda r: r[-1][1])
    else:
        return None
    recent = [text for text, at in rows if now - at < _RECENT_SECONDS]
    return "\n".join(recent) or None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


# --- hook -----------------------------------------------------------------------------------

def _last_agent_question(history: Any) -> bool:
    """True when the agent's last message in this chat asked something other than the check-in,
    so a bare "yes" answers that, not the check-in."""
    for msg in reversed(history or []):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        if not isinstance(content, str) or not content.strip():
            continue
        return "?" in content and "Check-in for" not in content
    return False


def on_pre_llm_call(session_id: str = "", user_message: Any = None,
                    conversation_history: Any = None, **_: Any):
    text = user_message if isinstance(user_message, str) else ""
    if session_id and text:
        rows = _last_said.setdefault(session_id, [])
        rows.append((text, time.time()))
        del rows[:-2]
        if len(_last_said) > 200:
            oldest = min(_last_said, key=lambda k: _last_said[k][-1][1])
            _last_said.pop(oldest, None)
    if not text or _last_agent_question(conversation_history):
        return None
    try:
        line = partner.answer_from_reply(ledger(), text, today())
    except Exception:  # noqa: BLE001 - never break a turn over the ledger
        logger.exception("accountability-partner: reading a check-in answer failed")
        return None
    return {"context": line} if line else None


def on_post_tool_call(tool_name: str = "", result: Any = None, session_id: str = "", **_: Any):
    """Keep recent tool results so promise_prove can check a receipt really came from a tool."""
    if not session_id or not tool_name or tool_name.startswith("promise_"):
        return None
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    rows = _seen.setdefault(session_id, [])
    rows.append((tool_name, text[:_RESULT_CHARS], time.time()))
    del rows[:-_SEEN_PER_SESSION]
    if len(_seen) > 200:
        oldest = min(_seen, key=lambda k: _seen[k][-1][2] if _seen[k] else 0)
        _seen.pop(oldest, None)
    return None


def _results_this_session(session_id: Optional[str]) -> list[tuple[str, str]]:
    cutoff = time.time() - 2 * _RECENT_SECONDS
    return [(name, text) for name, text, at in _seen.get(session_id or "", []) if at > cutoff]


# --- tools ----------------------------------------------------------------------------------

def _add(args: dict, session_id: str = "", **_: Any) -> str:
    return _json(partner.add(ledger(), args, _users_words(session_id), today()))


def _drop(args: dict, session_id: str = "", **_: Any) -> str:
    return _json(partner.drop(ledger(), args, _users_words(session_id)))


def _record(args: dict, session_id: str = "", **_: Any) -> str:
    return _json(partner.record(ledger(), args, _users_words(session_id), today()))


def _prove(args: dict, session_id: str = "", **_: Any) -> str:
    return _json(partner.prove(ledger(), args, _results_this_session(session_id), today()))


def _lock_in(args: dict, session_id: str = "", **_: Any) -> str:
    return _json(partner.lock(ledger(), args, _users_words(session_id), today()))


def on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any):
    if not tool_name or tool_name.startswith("promise_"):
        return None
    try:
        return partner.guard(ledger(), tool_name, args if isinstance(args, dict) else {}, today())
    except Exception:  # noqa: BLE001 - never hold up an unrelated tool over the ledger
        logger.exception("accountability-partner: consequence guard failed")
        return None


def _enforced(args: dict, session_id: str = "", **_: Any) -> str:
    return _json(partner.enforced(ledger(), args, _results_this_session(session_id), today()))


def _list(args: dict, **_: Any) -> str:
    return _json(partner.listing(ledger(), today()))


def _checkin(args: dict, **_: Any) -> str:
    led, day = ledger(), today()
    if not args.get("send_now"):
        prove = partner.prove_first(led, day)
        if prove:
            return _json({"prove_first": prove, "next": (
                "For each promise, use the user's connected tools to look for proof that it "
                "happened today, as its proof field says. When a tool shows it, call promise_prove "
                "quoting that tool's output. Skip any you can't check. Then call promise_checkin "
                "again with send_now true.")})
    return _json({"message": partner.checkin(led, day)})


def _report(args: dict, **_: Any) -> str:
    led, day = ledger(), today()
    out = {"message": partner.weekly_report(led, day)}
    owe = partner.owed(led, day)
    if owe:
        out["enforce_now"] = owe
        out["next"] = partner.ENFORCE_NOTE + " Then call promise_report again for the final message."
    return _json(out)


_QUOTE = {"type": "string", "description": (
    "The user's exact words from their current message that say this. Checked: a quote they did "
    "not write is refused.")}

TOOLS = [
    ("promise_add", _add, "Save a promise the user just made, in their own words.", {
        "what": {"type": "string", "description": "Short name, e.g. 'Gym' or 'Make 40 sales calls'."},
        "cadence": {"type": "string", "enum": ["daily", "weekdays", "weekly", "once"]},
        "per_week": {"type": "integer", "description": "For weekly: times per week (1-7)."},
        "due": {"type": "string", "description": "For once: due date, YYYY-MM-DD."},
        "starts": {"type": "string", "description": "First day it counts, YYYY-MM-DD, if the user said (e.g. 'starting tomorrow'). Default today."},
        "consequence": {"type": "string", "description": (
            "Only if the user named one themselves, copied in their own words: what happens on a "
            "miss, ideally something a "
            "connected tool can carry out, e.g. 'send $20 to GiveDirectly from my wallet' or "
            "'block Instagram for 24 hours'.")},
        "enforcer_tool": {"type": "string", "description": (
            "Optional: the exact name of the connected tool that carries out the consequence, "
            "e.g. a wallet's send tool or an app blocker.")},
        "max_amount": {"type": "number", "description": "For a money consequence: the most per miss."},
        "pay_to": {"type": "string", "description": "For a money consequence: the only recipient allowed."},
        "proof": {"type": "string", "description": (
            "Optional: which connected tool shows it happened and what counts as a win, in the "
            "user's words, e.g. 'a WHOOP workout of 30+ minutes' or 'a commit to acme/app on "
            "GitHub'.")},
        "user_quote": _QUOTE,
    }, ["what", "cadence", "user_quote"]),
    ("promise_prove", _prove, (
        "Mark a promise kept from a receipt: a result one of the user's connected tools returned "
        "in this session. evidence must be copied exactly from that tool's output; it is checked."), {
        "id": {"type": "integer"},
        "source_tool": {"type": "string", "description": "The name of the tool that returned the proof."},
        "evidence": {"type": "string", "description": "Exact text from that tool's output that shows it happened."},
    }, ["id", "source_tool", "evidence"]),
    ("promise_lock", _lock_in, (
        "Lock a promise in, only when the user explicitly asks ('lock it in', 'hold me to it'): "
        "on a miss its consequence fires without asking again, and it can't be dropped or softened "
        "until the end date (max 90 days, 24-hour cool-off first). Tell the user exactly what "
        "tell_the_user says."), {
        "id": {"type": "integer"},
        "until": {"type": "string", "description": "End date, YYYY-MM-DD."},
        "user_quote": _QUOTE,
    }, ["id", "until", "user_quote"]),
    ("promise_enforced", _enforced, (
        "Record that a missed promise's consequence was carried out, from the result of the tool "
        "that did it (a wallet transfer id, an app-block confirmation). evidence is checked."), {
        "id": {"type": "integer"},
        "source_tool": {"type": "string", "description": "The tool that carried it out."},
        "evidence": {"type": "string", "description": "Exact text from that tool's result."},
    }, ["id", "source_tool", "evidence"]),
    ("promise_record", _record, (
        "Record the user's own word that they kept or missed promises today (or yesterday). "
        "Never use it on your own judgment."), {
        "results": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "integer"}, "kept": {"type": "boolean"}}, "required": ["id", "kept"]}},
        "day": {"type": "string", "enum": ["today", "yesterday"]},
        "user_quote": _QUOTE,
    }, ["results", "user_quote"]),
    ("promise_drop", _drop, "Drop a promise the user said they are letting go of.", {
        "id": {"type": "integer"}, "user_quote": _QUOTE,
    }, ["id", "user_quote"]),
    ("promise_list", _list, "List the user's promises with this week's score.", {}, []),
    ("promise_checkin", _checkin, (
        "Build tonight's check-in. It may first return prove_first: promises to look for receipts "
        "on. Then call it with send_now true and send its message exactly as written; if it is "
        "[SILENT], send nothing."), {
        "send_now": {"type": "boolean", "description": "True once receipts have been looked for."},
    }, []),
    ("promise_report", _report, (
        "Build the weekly 'you said, you did' receipt. Send its message exactly as written; "
        "if it is [SILENT], send nothing."), {}, []),
]


def _promises_command(raw_args: str = "") -> str:
    data = partner.listing(ledger(), today())
    if not data["promises"]:
        return "No promises yet. Tell me what you're committing to, in your own words."
    lines = [f"#{p['id']} {p['promise']}: {p['this_week']}" for p in data["promises"]]
    return "\n".join(lines)


def register(ctx) -> None:
    for name, handler, description, props, required in TOOLS:
        ctx.register_tool(
            name=name, toolset=TOOLSET, handler=handler, description=description, emoji="🤝",
            schema={"name": name, "description": description, "parameters": {
                "type": "object", "properties": props, "required": required}})
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_command("promises", _promises_command,
                         description="Your promises and this week's score")
    ctx.register_system_prompt_section("accountability-partner", GUIDE)
    ctx.register_automation_blueprint(
        "nightly-checkin", title="Nightly check-in",
        description="Each night, ask about today's promises. Answer with one tap, like 'yes no'.",
        category="daily", schedule_template="{minute} {hour} * * *",
        prompt_template=("Call promise_checkin and follow what it returns: if it lists prove_first, "
                         "look for proof with the user's connected tools and call promise_prove for "
                         "each one you find, then call promise_checkin with send_now true. Send the "
                         "user its message exactly as written, with nothing added. If the message "
                         "is [SILENT], respond with [SILENT]."),
        slots=[{"name": "time", "type": "time", "label": "What time?", "default": "21:00",
                "help": "24h local time"},
               {"name": "deliver", "type": "enum", "label": "Where to deliver?",
                "default": "origin", "options": ("origin", "telegram", "discord"), "strict": False}],
        tags=("accountability", "daily"))
    ctx.register_automation_blueprint(
        "weekly-receipt", title="Weekly receipt",
        description="Sunday evening: what you said you'd do this week, and what you did.",
        category="weekly", schedule_template="{minute} {hour} * * 0",
        prompt_template=("Call promise_report and follow what it returns: if it lists enforce_now, "
                         "carry out each consequence with the user's connected tools (normal "
                         "approvals apply) and call promise_enforced for each one done, then call "
                         "promise_report again. Send the user its message exactly as written, with "
                         "nothing added. If the message is [SILENT], respond with [SILENT]."),
        slots=[{"name": "time", "type": "time", "label": "What time on Sunday?",
                "default": "18:00", "help": "24h local time"},
               {"name": "deliver", "type": "enum", "label": "Where to deliver?",
                "default": "origin", "options": ("origin", "telegram", "discord"), "strict": False}],
        tags=("accountability", "weekly"))
