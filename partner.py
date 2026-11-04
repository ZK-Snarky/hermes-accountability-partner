"""What the tools, the hook and the /promises command do, without any Hermes imports.

The one rule everything here follows: only the user's own words change the ledger. Adding,
dropping and marking a promise all need a quote that appears in the user's current message,
checked in code. The agent can phrase things, but it can't invent a promise or a "done".
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from . import answers
from .ledger import Ledger, Promise, week_start

SILENT = "[SILENT]"


def _norm(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[^\w\s'$%:/+-]", " ", text)
    return " ".join(text.split())


def said(quote: str, message: Optional[str]) -> bool:
    """True when ``quote`` is the user's own words from ``message`` (case and punctuation aside)."""
    q = _norm(quote)
    return len(q) >= 4 and bool(message) and q in _norm(message)


def _need_words(quote: str, message: Optional[str]) -> Optional[dict]:
    if said(quote, message):
        return None
    return {"ok": False, "error": (
        "user_quote must be the user's own words, copied from their current message. "
        "Only the user can make, change or mark a promise; ask them instead of guessing.")}


# --- tools ----------------------------------------------------------------------------------

def add(ledger: Ledger, args: dict, message: Optional[str], today: date) -> dict:
    refused = _need_words(args.get("user_quote", ""), message)
    if refused:
        return refused
    try:
        p = ledger.add(args.get("what", ""), args.get("cadence", "daily"), args["user_quote"],
                       per_week=int(args.get("per_week") or 1), due=args.get("due") or None,
                       consequence=args.get("consequence"), proof=args.get("proof"),
                       now=datetime.combine(today, datetime.now().time()))
    except (ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}
    out = {"ok": True, "id": p.id, "saved": p.label(), "quote": p.quote}
    if p.consequence:
        out["consequence"] = p.consequence
    if p.proof:
        out["proof"] = p.proof
    return out


def drop(ledger: Ledger, args: dict, message: Optional[str]) -> dict:
    refused = _need_words(args.get("user_quote", ""), message)
    if refused:
        return refused
    try:
        p = ledger.drop(int(args.get("id")), args["user_quote"])
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "dropped": p.label()}


_NO_WORDS = re.compile(r"\b(didn't|didnt|did not|not|never|no|skip|skipped|missed|couldn't|couldnt|"
                       r"won't|wont|failed)\b")


def _negated(quote: str, message: str) -> bool:
    """True when the quoted words, or the few words just before them, say no ("didn't go ...")."""
    msg, q = _norm(message), _norm(quote)
    at = msg.find(q)
    return bool(_NO_WORDS.search(msg[max(0, at - 25): at + len(q)]))


def record(ledger: Ledger, args: dict, message: Optional[str], today: date) -> dict:
    refused = _need_words(args.get("user_quote", ""), message)
    if refused:
        return refused
    if any(item.get("kept") for item in args.get("results") or []) and _negated(args["user_quote"], message):
        return {"ok": False, "error": (
            "The quoted words say 'didn't'/'not'/'skipped', so they can't mark anything kept. "
            "Ask the user plainly whether they did it.")}
    day = today
    if args.get("day") == "yesterday":
        day = today - timedelta(days=1)
    results = args.get("results") or []
    if not results:
        return {"ok": False, "error": "results is empty"}
    saved = []
    for item in results:
        try:
            p = ledger.get(int(item["id"]))
            ledger.report(p.id, day, bool(item["kept"]), args["user_quote"])
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc), "saved_so_far": saved}
        saved.append({"id": p.id, "what": p.what, "kept": bool(item["kept"])})
    pending = ledger.pending()
    if pending and pending[0] == day and set(pending[1]) <= {s["id"] for s in saved}:
        ledger.clear_pending()
    return {"ok": True, "day": day.isoformat(), "saved": saved,
            "score": [line_for(ledger, ledger.get(s["id"]), today) for s in saved]}


def listing(ledger: Ledger, today: date) -> dict:
    items = [{"id": p.id, "promise": p.label(), "said": p.quote,
              "this_week": line_for(ledger, p, today),
              **({"consequence": p.consequence} if p.consequence else {}),
              **({"proof": p.proof} if p.proof else {})}
             for p in ledger.active()]
    return {"ok": True, "promises": items} if items else {
        "ok": True, "promises": [], "note": "No promises yet. They start from the user's own words."}


# --- check-in -------------------------------------------------------------------------------

def to_ask(ledger: Ledger, today: date) -> list[Promise]:
    """Tonight's questions: every daily promise, weekly ones not yet met, one-time ones now due."""
    out = []
    for p in ledger.active():
        if date.fromisoformat(p.created[:10]) > today:
            continue
        if p.cadence == "daily" or (p.cadence == "weekdays" and today.weekday() < 5):
            out.append(p)
        elif p.cadence == "weekly":
            if ledger.kept_between(p.id, week_start(today), today) < p.per_week:
                out.append(p)
        elif p.due and date.fromisoformat(p.due) <= today:
            out.append(p)
    return out


def prove_first(ledger: Ledger, today: date) -> list[dict]:
    """Tonight's promises that name a proof and have no answer yet: look for receipts first."""
    return [{"id": p.id, "what": p.what, "proof": p.proof} for p in to_ask(ledger, today)
            if p.proof and ledger.day_report(p.id, today) is None]


def checkin(ledger: Ledger, today: date) -> str:
    due = to_ask(ledger, today)
    seen = [p for p in due if ledger.day_report(p.id, today) is True and ledger.receipt(p.id, today)]
    asks = [p for p in due if ledger.day_report(p.id, today) is None]
    if not asks and not seen:
        ledger.clear_pending()
        return SILENT
    lines = [f"Check-in for {today.strftime('%a %b')} {today.day}:"]
    for p in seen:
        lines.append(f"✓ {p.what}: seen in {_tool_label(ledger.receipt(p.id, today))} "
                     f"({line_for(ledger, p, today)})")
    if not asks:
        ledger.clear_pending()
        lines.append("Nothing to ask tonight. Everything is proven.")
        return "\n".join(lines)
    for n, p in enumerate(asks, 1):
        lines.append(f"{n}. {_question(p)} ({line_for(ledger, p, today)})")
    example = " ".join(["yes", "no", "yes"][: len(asks)] + ["yes"] * max(0, len(asks) - 3))
    lines.append(f'Reply in order, like "{example}".' if len(asks) > 1 else 'Reply "yes" or "no".')
    ledger.set_pending(today, [p.id for p in asks])
    return "\n".join(lines)


def _tool_label(name: str) -> str:
    """mcp_github_list_commits -> github list commits"""
    name = name[4:] if name.startswith("mcp_") else name
    return name.replace("_", " ").replace("-", " ")


def prove(ledger: Ledger, args: dict, tool_results: list, today: date) -> dict:
    """Mark a promise kept from a receipt: ``evidence`` must be text that ``source_tool`` really
    returned in this session (``tool_results`` = [(tool name, result text)], seen by the hook)."""
    tool = (args.get("source_tool") or "").strip()
    evidence = args.get("evidence") or ""
    if tool.startswith("promise_"):
        return {"ok": False, "error": "A promise tool can't be its own receipt."}
    if len(_norm(evidence)) < 8:
        return {"ok": False, "error": "evidence must quote at least a few words of the tool's output."}
    if not any(name == tool and _norm(evidence) in _norm(text) for name, text in tool_results):
        return {"ok": False, "error": (
            f"No result from {tool or 'that tool'} in this session contains that evidence. Call the "
            "tool, then quote its output exactly. If there's no proof, ask the user instead.")}
    try:
        p = ledger.get(int(args.get("id")))
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    ledger.report(p.id, today, True, evidence.strip()[:300], source=tool)
    return {"ok": True, "kept": p.what, "seen_in": tool, "score": line_for(ledger, p, today)}


def _question(p: Promise) -> str:
    if p.cadence == "weekly":
        return f"{p.what} today?"
    if p.cadence == "once":
        return f"{p.what}: done?"
    return f"{p.what}?"


def answer_from_reply(ledger: Ledger, message: str, today: date) -> Optional[str]:
    """If ``message`` cleanly answers the open check-in, record it in code and return the context
    line for the agent. Otherwise None, and nothing is written."""
    pending = ledger.pending()
    if not pending:
        return None
    day, ids = pending
    verdicts = answers.parse(message, len(ids))
    if verdicts is None:
        return None
    parts, misses = [], []
    for pid, kept in zip(ids, verdicts):
        try:
            p = ledger.get(pid)
        except KeyError:
            continue
        ledger.report(pid, day, kept, message.strip())
        parts.append(f"{p.what}: {'kept' if kept else 'missed'} ({line_for(ledger, p, today)})")
        if not kept and p.consequence and p.cadence != "weekly":  # a weekly one fails by the week
            misses.append(f'{p.what} -> "{p.consequence}"')
    ledger.clear_pending()
    text = ("[Accountability ledger] The user's reply was saved as their check-in for "
            f"{day.isoformat()}: " + "; ".join(parts) + ". Acknowledge it in one or two short "
            "lines. Be honest: no praise for a miss, no lecture either.")
    if misses:
        text += " Name the consequence they chose for each miss: " + "; ".join(misses) + "."
    return text


# --- scores ---------------------------------------------------------------------------------

def line_for(ledger: Ledger, p: Promise, today: date) -> str:
    if p.cadence == "weekly":
        done = ledger.kept_between(p.id, week_start(today), today)
        return f"{done} of {p.per_week} this week"
    if p.cadence in ("daily", "weekdays"):
        streak = ledger.streak(p.id, today, weekdays_only=p.cadence == "weekdays")
        return f"{streak}-day streak" if streak else "no streak yet"
    verdict = ledger.last_report(p.id)
    return "open" if verdict is None else ("kept" if verdict else "missed")


def weekly_report(ledger: Ledger, today: date) -> str:
    """Said vs did for the week so far (Monday through today)."""
    start = week_start(today)
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    lines = [f"Your week, {start.strftime('%b')} {start.day} to {today.strftime('%b')} {today.day}:"]
    said_n = did_n = proven_n = 0
    consequences = []
    for p in ledger.active(include_finished=True):
        created = date.fromisoformat(p.created[:10])
        if p.cadence in ("daily", "weekdays"):
            window = [d for d in days if d >= created
                      and (p.cadence == "daily" or d.weekday() < 5)]
            if not window:
                continue
            kept = sum(1 for d in window if ledger.day_report(p.id, d) is True)
            missed = sum(1 for d in window if ledger.day_report(p.id, d) is False)
            silent = len(window) - kept - missed
            said_n, did_n = said_n + len(window), did_n + kept
            proven_n += ledger.kept_with_receipts(p.id, window[0], today)
            extra = f", {silent} with no answer" if silent else ""
            lines.append(f"- {p.what}: {kept} of {len(window)} days{extra}")
            if (missed or silent) and p.consequence:
                consequences.append(f"{p.what}: {p.consequence}")
        elif p.cadence == "weekly":
            kept = ledger.kept_between(p.id, start, today)
            said_n, did_n = said_n + p.per_week, did_n + min(kept, p.per_week)
            proven_n += min(ledger.kept_with_receipts(p.id, start, today), p.per_week)
            lines.append(f"- {p.what}: {kept} of {p.per_week}")
            if kept < p.per_week and today.weekday() == 6 and p.consequence:
                consequences.append(f"{p.what}: {p.consequence}")
        elif p.due and start <= date.fromisoformat(p.due) <= today:
            verdict = ledger.last_report(p.id)
            said_n, did_n = said_n + 1, did_n + (1 if verdict else 0)
            lines.append(f"- {p.what}: {'done' if verdict else 'not done'}")
            if not verdict and p.consequence:
                consequences.append(f"{p.what}: {p.consequence}")
    if said_n == 0:
        return SILENT
    proof_note = f" ({proven_n} with receipts)" if proven_n else ""
    lines.append(f"You said {said_n}, you did {did_n}{proof_note}.")
    if consequences:
        lines.append("Consequences you chose: " + "; ".join(consequences) + ".")
    return "\n".join(lines)

