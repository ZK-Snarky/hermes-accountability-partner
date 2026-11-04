"""Accountability Partner: Hermes holds you to what you said, in your own words.

Wiring only. The rules live in partner.py and the data in ledger.py.
"""

from __future__ import annotations

import json
import logging
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
_last_said: dict[str, tuple[str, float]] = {}  # session id -> (user's message, when)

GUIDE = (
    "Accountability Partner is on. When the user commits to something (\"I'll...\", \"I'm going "
    "to...\", \"every day I...\"), offer to save it with promise_add, quoting their exact words. "
    "Only the user's own words add, drop or mark a promise; never mark one kept or missed from "
    "your own reading of their day. The ledger's numbers are the score: repeat them, don't round up."
)


def _data_dir() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir
        return plugin_data_dir(PLUGIN)
    except ImportError:  # older Hermes without the storage helper
        from hermes_constants import get_hermes_home
        path = get_hermes_home() / "plugin-data" / PLUGIN
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
    """The user's current message: the one this turn started from."""
    now = time.time()
    if session_id and session_id in _last_said:
        text, at = _last_said[session_id]
        return text if now - at < _RECENT_SECONDS else None
    if _last_said:  # no session id passed: the newest message, if it is recent
        text, at = max(_last_said.values(), key=lambda v: v[1])
        return text if now - at < _RECENT_SECONDS else None
    return None


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
        _last_said[session_id] = (text, time.time())
        if len(_last_said) > 200:
            oldest = min(_last_said, key=lambda k: _last_said[k][1])
            _last_said.pop(oldest, None)
    if not text or _last_agent_question(conversation_history):
        return None
    try:
        line = partner.answer_from_reply(ledger(), text, today())
    except Exception:  # noqa: BLE001 - never break a turn over the ledger
        logger.exception("accountability-partner: reading a check-in answer failed")
        return None
    return {"context": line} if line else None


# --- tools ----------------------------------------------------------------------------------

def _add(args: dict, session_id: str = "", **_: Any) -> str:
    return _json(partner.add(ledger(), args, _users_words(session_id), today()))


def _drop(args: dict, session_id: str = "", **_: Any) -> str:
    return _json(partner.drop(ledger(), args, _users_words(session_id)))


def _record(args: dict, session_id: str = "", **_: Any) -> str:
    return _json(partner.record(ledger(), args, _users_words(session_id), today()))


def _list(args: dict, **_: Any) -> str:
    return _json(partner.listing(ledger(), today()))


def _checkin(args: dict, **_: Any) -> str:
    return _json({"message": partner.checkin(ledger(), today())})


def _report(args: dict, **_: Any) -> str:
    return _json({"message": partner.weekly_report(ledger(), today())})


_QUOTE = {"type": "string", "description": (
    "The user's exact words from their current message that say this. Checked: a quote they did "
    "not write is refused.")}

TOOLS = [
    ("promise_add", _add, "Save a promise the user just made, in their own words.", {
        "what": {"type": "string", "description": "Short name, e.g. 'Gym' or 'Make 40 sales calls'."},
        "cadence": {"type": "string", "enum": ["daily", "weekdays", "weekly", "once"]},
        "per_week": {"type": "integer", "description": "For weekly: times per week (1-7)."},
        "due": {"type": "string", "description": "For once: due date, YYYY-MM-DD."},
        "consequence": {"type": "string", "description": "Only if the user named one themselves."},
        "user_quote": _QUOTE,
    }, ["what", "cadence", "user_quote"]),
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
        "Build tonight's check-in question. Send its message to the user exactly as written; "
        "if it is [SILENT], send nothing."), {}, []),
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
    ctx.register_command("promises", _promises_command,
                         description="Your promises and this week's score")
    ctx.register_system_prompt_section("accountability-partner", GUIDE)
    ctx.register_automation_blueprint(
        "nightly-checkin", title="Nightly check-in",
        description="Each night, ask about today's promises. Answer with one tap, like 'yes no'.",
        category="daily", schedule_template="{minute} {hour} * * *",
        prompt_template=("Call promise_checkin. Send the user its message exactly as written, "
                         "with nothing added. If the message is [SILENT], respond with [SILENT]."),
        slots=[{"name": "time", "type": "time", "label": "What time?", "default": "21:00",
                "help": "24h local time"},
               {"name": "deliver", "type": "enum", "label": "Where to deliver?",
                "default": "origin", "options": ("origin", "telegram", "discord"), "strict": False}],
        tags=("accountability", "daily"))
    ctx.register_automation_blueprint(
        "weekly-receipt", title="Weekly receipt",
        description="Sunday evening: what you said you'd do this week, and what you did.",
        category="weekly", schedule_template="{minute} {hour} * * 0",
        prompt_template=("Call promise_report. Send the user its message exactly as written, "
                         "with nothing added. If the message is [SILENT], respond with [SILENT]."),
        slots=[{"name": "time", "type": "time", "label": "What time on Sunday?",
                "default": "18:00", "help": "24h local time"},
               {"name": "deliver", "type": "enum", "label": "Where to deliver?",
                "default": "origin", "options": ("origin", "telegram", "discord"), "strict": False}],
        tags=("accountability", "weekly"))
