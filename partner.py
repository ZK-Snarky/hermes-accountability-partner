"""What the tools, the hook and the /promises command do, without any Hermes imports.

The one rule everything here follows: only the user's own words, or a real result from one of
their tools, change the ledger. Adding, dropping and marking a promise need a quote that appears
in the user's current message; a receipt needs text a tool really returned. Both are checked in
code. The agent can phrase things, but it can't invent a promise or a "done".
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Optional

from . import answers
from .ledger import Ledger, Promise, locked, week_start

SILENT = "[SILENT]"


def _norm(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[^\w\s'$%:/+-]", " ", text)
    text = text.replace(":", " : ")  # so compact and spaced JSON match: "a":1 and "a": 1
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
    if args.get("consequence") and not said(args["consequence"], message):
        return {"ok": False, "error": (
            "consequence must be the user's own words, copied exactly from their message. Don't "
            "reword or add to it; leave it out if they didn't name one.")}
    rule = (args.get("rule") or "").strip() or None
    proof_tool = (args.get("proof_tool") or "").strip() or None
    proof_args = args.get("proof_args") or None
    if proof_args is not None and not isinstance(proof_args, dict):
        return {"ok": False, "error": "proof_args must be an object of the proof tool's arguments."}
    if proof_tool and (proof_tool.startswith("promise_")
                       or proof_tool == (args.get("enforcer_tool") or "").strip()):
        return {"ok": False, "error": (
            f"{proof_tool} can't prove this promise: a promise tool can't be its own receipt, and "
            "the tool that carries out the consequence can't also be its proof.")}
    if args.get("data_decides") and not rule:
        return {"ok": False, "error": "data_decides needs a rule and proof_tool: the data can only decide what a rule checks."}
    if rule:
        if not proof_tool:
            return {"ok": False, "error": "A rule needs proof_tool: the exact name of the tool whose data it checks."}
        try:
            conds = parse_rule(rule)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if all(op == "=" for _, op, _ in conds):
            return {"ok": False, "error": (
                f"'{rule}' only matches labels, so it would pass on a day when nothing happened. "
                "Add what must have happened, e.g. 'commits >= 1' or 'minutes >= 30'.")}
    try:
        p = ledger.add((args.get("what") or "").strip().rstrip("."), args.get("cadence", "daily"), args["user_quote"],
                       per_week=int(args.get("per_week") or 1), due=args.get("due") or None,
                       consequence=args.get("consequence"), proof=args.get("proof"),
                       enforcer=args.get("enforcer_tool"), max_amount=args.get("max_amount"),
                       pay_to=args.get("pay_to"), starts=args.get("starts") or None,
                       proof_tool=proof_tool, rule=rule,
                       proof_args=json.dumps(proof_args, sort_keys=True) if proof_args else None,
                       **({"data_decides": True} if args.get("data_decides") else {}),
                       now=datetime.combine(today, datetime.now().time()))
    except (ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}
    out = {"ok": True, "id": p.id, "saved": p.label(), "quote": p.quote}
    if p.enforcer:
        out["enforcer_tool"] = p.enforcer
    if p.consequence:
        out["consequence"] = p.consequence
    if p.proof:
        out["proof"] = p.proof
    if p.rule:
        out["counts_when"] = f"{p.rule} in {p.proof_tool}"
        out["tell_the_user"] = f"It counts when {_tool_label(p.proof_tool)} shows {rule_words(p.rule)}."
        if getattr(p, "data_decides", False):
            out["tell_the_user"] += (f" The data decides: if {_tool_label(p.proof_tool)} shows it wasn't met at "
                                     "the check-in, it's a miss without asking you.")
    return out


# --- rules: the plugin, not the model, decides whether a tool's data meets the user's rule ----

_COND = re.compile(r"^\s*([\w.]+)\s*(>=|<=|==|=|>|<|contains)\s*(.+?)\s*$", re.I)


def parse_rule(rule: str) -> list[tuple[str, str, object]]:
    """'minutes >= 30', 'sport = running and minutes >= 30', 'message contains fix'."""
    conds = []
    for part in re.split(r"\s+and\s+", (rule or "").strip(), flags=re.I):
        part = re.sub(r"^\s*(?:len|count)\s*\(\s*([\w.]+)\s*\)", r"\1", part, flags=re.I)
        m = _COND.match(part)
        if not m:
            raise ValueError(f"Can't read the rule part {part!r}. Use 'field >= number', "
                             "'field = text' or 'field contains text', joined by 'and'.")
        field, op, value = m.group(1).lower(), m.group(2).lower(), m.group(3).strip().strip("'\"")
        if op in (">=", "<=", ">", "<"):
            try:
                value = float(value)
            except ValueError:
                raise ValueError(f"{field} {op} needs a number, not {value!r}.") from None
        conds.append((field, "=" if op == "==" else op, value))
    return conds


_OP_WORDS = {">=": "at least", ">": "more than", "<=": "at most", "<": "less than",
             "=": "is", "contains": "contains"}


def rule_words(rule: str) -> str:
    """'repo = my-app and commits >= 1' -> 'repo is my-app and commits at least 1'"""
    return " and ".join(f"{f} {_OP_WORDS[op]} {want:g}" if isinstance(want, float)
                        else f"{f} {_OP_WORDS[op]} {want}" for f, op, want in parse_rule(rule))


def _records(data):
    """Every dict inside a tool result, unwrapping JSON held in strings (as MCP text often is)."""
    if isinstance(data, str):
        text = data.strip()
        if text[:1] in "{[":
            try:
                yield from _records(json.loads(text))
            except ValueError:
                pass
    elif isinstance(data, dict):
        yield data
        for v in data.values():
            yield from _records(v)
    elif isinstance(data, list):
        for v in data:
            yield from _records(v)


def _shown(value) -> str:
    """A list reads as its count ('commits 2'), never its raw contents."""
    if isinstance(value, (list, tuple, dict)):
        return str(len(value))
    return str(value)


def _meets(value, op, want) -> bool:
    if isinstance(value, (list, tuple, dict)) and op in (">=", "<=", ">", "<", "="):
        value = len(value)  # 'commits >= 1' counts the items
    if op in (">=", "<=", ">", "<"):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        return {">=": v >= want, "<=": v <= want, ">": v > want, "<": v < want}[op]
    if op == "contains":
        return str(want).lower() in str(value).lower()
    return str(value).strip().lower() == str(want).lower()


def check_rule(rule: str, results: list[str]) -> tuple[Optional[str], Optional[str]]:
    """(evidence, None) when one record in the results meets every part of the rule;
    (None, reading) with what the data showed when none does; (None, None) when there's no data."""
    conds = parse_rule(rule)
    seen = []
    for text in results:
        for rec in _records(text):
            fields = {str(k).lower(): v for k, v in rec.items()}
            if not any(f in fields for f, _, _ in conds):
                continue
            if all(f in fields and _meets(fields[f], op, want) for f, op, want in conds):
                return ", ".join(f"{f} {_shown(fields[f])}" for f, _, _ in conds), None
            seen.append(", ".join(f"{f} {_shown(fields[f])}" for f, _, _ in conds if f in fields))
    return None, ("; ".join(dict.fromkeys(seen)) if seen else None)


_LOCK_WORDS = re.compile(r"\b(lock|locked|hold me to it|no backing out|no way out|can't back out)\b")
MAX_LOCK_DAYS = 90


def lock(ledger: Ledger, args: dict, message: Optional[str], today: date) -> dict:
    """Lock a promise in: its consequence fires on a miss without asking again, and it can't be
    dropped or softened until ``until``. Only on the user's explicit words, with rails."""
    quote = args.get("user_quote", "")
    refused = _need_words(quote, message)
    if refused:
        return refused
    if not _LOCK_WORDS.search(_norm(quote)):
        return {"ok": False, "error": "Locking needs the user's explicit words, like 'lock it in' "
                                      "or 'hold me to it'. Ask them; never lock on your own."}
    try:
        p = ledger.get(int(args.get("id")))
        until = date.fromisoformat(args.get("until") or "")
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": f"need a promise id and an end date YYYY-MM-DD ({exc})"}
    if not today < until <= today + timedelta(days=MAX_LOCK_DAYS):
        return {"ok": False, "error": f"The end date must be within {MAX_LOCK_DAYS} days."}
    if not (p.consequence and p.enforcer):
        return {"ok": False, "error": "A locked promise needs a consequence and the tool that "
                                      "enforces it (enforcer_tool). Add those first."}
    if p.max_amount is None and re.search(r"[$€£]|\b(usd|eur|send|pay|donate)\b", _norm(p.consequence)):
        return {"ok": False, "error": "A money consequence needs max_amount before it can be locked."}
    p = ledger.lock(p.id, until)
    return {"ok": True, "locked": p.label(), "until": p.locked_until, "cool_off_hours": 24,
            "tell_the_user": (
                f"Locked until {p.locked_until}. For 24 hours you can still undo it; after that it "
                f"can't be dropped or softened. On a miss, Hermes carries out your consequence "
                f"(\"{p.consequence}\") with {p.enforcer} without asking again"
                + (f", never more than {p.max_amount:g} per miss" if p.max_amount else "")
                + (f", only to {p.pay_to}" if p.pay_to else "")
                + f". Give {p.enforcer} a standing OK in Hermes (choose 'always' when it first asks).")}


def drop(ledger: Ledger, args: dict, message: Optional[str]) -> dict:
    refused = _need_words(args.get("user_quote", ""), message)
    if refused:
        return refused
    try:
        p = ledger.drop(int(args.get("id")), args["user_quote"])
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "dropped": p.label()}


_HEDGE_WORDS = re.compile(r"\b(basically|kind of|kinda|sort of|sorta|mostly|pretty much|almost|"
                          r"nearly|probably|i think|technically|more or less|half|partly|ish)\b")
_NO_WORDS = re.compile(r"\b(didn't|didnt|did not|not|never|no|skip|skipped|missed|couldn't|couldnt|"
                       r"won't|wont|failed)\b")


def _current(message: Optional[str]) -> str:
    """The newest message when the hook passed the last two joined by a newline."""
    return (message or "").split("\n")[-1]


def _negated(quote: str, message: str) -> bool:
    """True when the quoted words, or the few words just before them, say no ("didn't go ...")."""
    msg, q = _norm(message), _norm(quote)
    at = msg.find(q)
    return bool(_NO_WORDS.search(msg[max(0, at - 25): at + len(q)]))


def record(ledger: Ledger, args: dict, message: Optional[str], today: date) -> dict:
    results = args.get("results") or []
    bare = answers.parse(_current(message).strip(), 1)  # a plain "yes" / "no" to a direct question
    if bare and results and all(bool(r.get("kept")) == bare[0] for r in results):
        args = {**args, "user_quote": _current(message).strip()}
    else:
        refused = _need_words(args.get("user_quote", ""), message)
        if refused:
            return refused
    wants_kept = any(item.get("kept") for item in args.get("results") or [])
    if wants_kept and _HEDGE_WORDS.search(_norm(_current(message))):
        return {"ok": False, "error": (
            "The user hedged ('basically', 'mostly', 'kind of'...). A hedge isn't a yes: ask them "
            "plainly whether they did it, and record their answer.")}
    if wants_kept and _negated(args["user_quote"], message):
        return {"ok": False, "error": (
            "The quoted words say 'didn't'/'not'/'skipped', so they can't mark anything kept. "
            "Ask the user plainly whether they did it.")}
    day = today
    if args.get("day") == "yesterday":
        day = today - timedelta(days=1)
    if not results:
        return {"ok": False, "error": "results is empty"}
    saved = []
    for item in results:
        try:
            p = ledger.get(int(item["id"]))
            if p.first_day() > day:
                return {"ok": False, "error": f"{p.what} starts {p.first_day().isoformat()}; nothing "
                                              "to record before then.", "saved_so_far": saved}
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
              **({"proof": p.proof} if p.proof else {}),
              **({"locked_until": p.locked_until} if p.locked_until else {})}
             for p in ledger.active()]
    return {"ok": True, "promises": items} if items else {
        "ok": True, "promises": [], "note": "No promises yet. They start from the user's own words."}


# --- check-in -------------------------------------------------------------------------------

def to_ask(ledger: Ledger, today: date) -> list[Promise]:
    """Tonight's questions: every daily promise, weekly ones not yet met, one-time ones now due."""
    out = []
    for p in ledger.active():
        if p.first_day() > today:
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
    return [{"id": p.id, "what": p.what,
             **({"call": p.proof_tool, "rule": p.rule} if p.rule else {"proof": p.proof})}
            for p in to_ask(ledger, today)
            if (p.proof or p.rule) and ledger.day_report(p.id, today) is None
            and ledger.reading(p.id, today) is None]


def checkin(ledger: Ledger, today: date) -> str:
    due = to_ask(ledger, today)
    seen = [p for p in due if ledger.day_report(p.id, today) is True and ledger.receipt(p.id, today)]
    data_missed = [p for p in due if getattr(p, "data_decides", False) and ledger.day_report(p.id, today) is False
                   and ledger.receipt(p.id, today)]
    asks = [p for p in due if ledger.day_report(p.id, today) is None]
    if not asks and not seen and not data_missed:
        ledger.clear_pending()
        return SILENT
    lines = [f"Check-in for {today.strftime('%a %b')} {today.day}:"]
    for p in seen:
        shown = f" ({ledger.report_quote(p.id, today)}, rule {p.rule})" if p.rule else ""
        lines.append(f"✓ {p.what}: seen in {_tool_label(ledger.receipt(p.id, today))}{shown} "
                     f"({line_for(ledger, p, today)})")
    for p in data_missed:
        lines.append(f"✗ {p.what}: {ledger.report_quote(p.id, today)} (the data decides) "
                     f"({line_for(ledger, p, today)})")
    if not asks:
        ledger.clear_pending()
        lines.append("Nothing to ask tonight. Everything is proven." if not data_missed
                     else "Nothing to ask tonight. The data settled every promise.")
        return "\n".join(lines)
    for n, p in enumerate(asks, 1):
        seen_note = ledger.reading(p.id, today)
        lines.append(f"{n}. {_question(p)} ({line_for(ledger, p, today)})"
                     + (f"\n   {seen_note}" if seen_note else ""))
    example = " ".join(["yes", "no", "yes"][: len(asks)] + ["yes"] * max(0, len(asks) - 3))
    lines.append(f'Reply in order, like "{example}".' if len(asks) > 1 else 'Reply "yes" or "no".')
    ledger.set_pending(today, [p.id for p in asks])
    return "\n".join(lines)


def _tool_label(name: str) -> str:
    """mcp_github_list_commits -> github list commits"""
    name = name[4:] if name.startswith("mcp_") else name
    return name.replace("_", " ").replace("-", " ")


def _tool_said(tool: str, evidence: str, tool_results: list) -> Optional[dict]:
    """None when ``tool`` really returned ``evidence`` in this session; else the refusal."""
    if tool.startswith("promise_"):
        return {"ok": False, "error": "A promise tool can't be its own receipt."}
    if len(_norm(evidence)) < 8:
        return {"ok": False, "error": "evidence must quote at least a few words of the tool's output."}
    if not any(name == tool and _norm(evidence) in _norm(text) for name, text in tool_results):
        return {"ok": False, "error": (
            f"No result from {tool or 'that tool'} in this session contains that evidence. Call the "
            "tool, then quote its output exactly. If there's no proof, say so instead.")}
    return None


def prove(ledger: Ledger, args: dict, tool_results: list, today: date) -> dict:
    """Mark a promise kept from a receipt: ``evidence`` must be text that ``source_tool`` really
    returned in this session (``tool_results`` = [(tool name, result text)], seen by the hook)."""
    tool = (args.get("source_tool") or "").strip()
    evidence = args.get("evidence") or ""
    try:
        ruled = ledger.get(int(args.get("id")))
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    if ruled.rule:
        return _prove_by_rule(ledger, ruled, tool_results, today)
    refused = _tool_said(tool, evidence, tool_results)
    if refused:
        return refused
    try:
        p = ledger.get(int(args.get("id")))
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    ledger.report(p.id, today, True, evidence.strip()[:300], source=tool)
    return {"ok": True, "kept": p.what, "seen_in": tool, "score": line_for(ledger, p, today)}


def _prove_by_rule(ledger: Ledger, p: Promise, tool_results: list, today: date, final: bool = False) -> dict:
    results = [text for name, text in tool_results if name == p.proof_tool]
    if not results:
        return {"ok": False, "error": f"Call {p.proof_tool} first; its data decides this one."}
    evidence, reading = check_rule(p.rule, results)
    if evidence:
        ledger.report(p.id, today, True, evidence[:300], source=p.proof_tool)
        return {"ok": True, "kept": p.what, "seen_in": p.proof_tool, "rule": p.rule,
                "evidence": evidence, "score": line_for(ledger, p, today)}
    shown = f"{_tool_label(p.proof_tool)} shows {reading}" if reading else \
        f"{_tool_label(p.proof_tool)} has nothing for it"
    if final and reading and getattr(p, "data_decides", False):
        # the user chose to let the data decide: at the check-in, real data that fails the rule is a miss
        ledger.report(p.id, today, False, f"{shown}; rule {p.rule}"[:300], source=p.proof_tool)
        return {"ok": True, "missed": p.what, "seen_in": p.proof_tool, "rule": p.rule, "reading": shown}
    ledger.set_reading(p.id, today, f"{shown}; your rule: {p.rule}")
    return {"ok": False, "not_proven": f"{shown}; the rule is {p.rule}. Not marked. Tell the user "
            "what the tool shows and ask them plainly: did they do it today, yes or no? Record "
            "their answer with promise_record. Don't mark it yourself."}


def check_by_fetching(ledger: Ledger, today: date, fetch) -> list[int]:
    """Code, not the model, gets the data: for each promise with a rule still open tonight, call
    ``fetch(tool, args)`` (the host's tool dispatch) and check the rule on what comes back.
    Whether a call may run is the host's decision: Hermes's own approvals gate it exactly as they
    gate the model's calls, and a call they refuse or hold is just a failed fetch (never a miss).
    Returns the ids it couldn't fetch, so the model can try those."""
    failed = []
    for p in to_ask(ledger, today):
        if not (p.rule and p.proof_tool) or ledger.day_report(p.id, today) is not None:
            continue
        try:
            result = fetch(p.proof_tool, json.loads(p.proof_args) if p.proof_args else {})
        except Exception:  # a missing or failing tool is never a miss: the model may try it
            failed.append(p.id)
            continue
        if not isinstance(result, str) or '"error"' in result[:200]:
            failed.append(p.id)
            continue
        _prove_by_rule(ledger, p, [(p.proof_tool, result)], today, final=True)
    return failed


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
    parts = []
    for pid, kept in zip(ids, verdicts):
        try:
            p = ledger.get(pid)
        except KeyError:
            continue
        ledger.report(pid, day, kept, message.strip())
        parts.append(f"{p.what}: {'kept' if kept else 'missed'} ({line_for(ledger, p, today)})")
    ledger.clear_pending()
    text = ("[Accountability ledger] The user's reply was saved as their check-in for "
            f"{day.isoformat()}: " + "; ".join(parts) + ". Acknowledge it in one or two short "
            "lines. Be honest: no praise for a miss, no lecture either.")
    owe = owed(ledger, today)
    if owe:
        text += (" Consequences now owed: " + "; ".join(
            f'#{o["id"]} {o["what"]} -> "{o["consequence"]}"' for o in owe) + ". " + ENFORCE_NOTE)
    return text


def _period(p: Promise, day: date) -> str:
    return f"week of {week_start(day).isoformat()}" if p.cadence == "weekly" else day.isoformat()


def owed(ledger: Ledger, today: date) -> list[dict]:
    """Consequences the user chose for misses this week that haven't been carried out yet."""
    out = []
    start = week_start(today)
    for p in ledger.active(include_finished=True):
        if not p.consequence:
            continue
        if p.cadence == "weekly":
            periods = [_period(p, today)] if (
                today.weekday() == 6 and ledger.kept_between(p.id, start, today) < p.per_week) else []
        else:
            periods = [_period(p, d) for d in ledger.misses(p.id, start, today)]
        for period in periods:
            if ledger.enforced(p.id, period):
                continue
            item = {"id": p.id, "what": p.what, "consequence": p.consequence, "for": period}
            if p.enforcer:
                item["enforcer_tool"] = p.enforcer
            if p.locked_until and locked(p, datetime.now()):
                item["locked_in"] = True
            out.append(item)
    return out


def enforced(ledger: Ledger, args: dict, tool_results: list, today: date) -> dict:
    """Record that a consequence was carried out, from the tool result that shows it."""
    tool = (args.get("source_tool") or "").strip()
    refused = _tool_said(tool, args.get("evidence") or "", tool_results)
    if refused:
        return refused
    due = [o for o in owed(ledger, today) if o["id"] == args.get("id")]
    if not due:
        return {"ok": False, "error": "Nothing is owed on that promise right now."}
    ledger.enforce(due[0]["id"], due[0]["for"], tool, args["evidence"].strip()[:300])
    return {"ok": True, "enforced": f'{due[0]["what"]}: {due[0]["consequence"]}', "for": due[0]["for"],
            "seen_in": tool}


ENFORCE_NOTE = (
    "For each one, carry out the consequence the user chose with their connected tools (its "
    "enforcer_tool if named: a wallet, a Screen Time or app-blocking tool). One marked locked_in "
    "was locked in by the user: do it now, don't ask them again or talk them out of it. Hermes's "
    "approvals still apply: never work around them. When a tool's result shows it was done, call "
    "promise_enforced quoting that result. If no connected tool can do it, say plainly it is still owed.")


_AMOUNT_KEY = re.compile(r"amount|value|usd|sum|total|price")
_PAYEE_KEY = re.compile(r"^(to|recipient|address|destination|payee|charity|to_address)$")


def _walk(args, path=()):
    if isinstance(args, dict):
        for k, v in args.items():
            yield from _walk(v, path + (str(k).lower(),))
    elif isinstance(args, list):
        for v in args:
            yield from _walk(v, path)
    else:
        yield path, args


def guard(ledger: Ledger, tool_name: str, args: dict, today: date) -> Optional[dict]:
    """pre_tool_call: while a consequence is owed through ``tool_name``, hold the call to the rails
    set at setup (max amount, recipient). Calls when nothing is owed are none of our business."""
    due = [o for o in owed(ledger, today) if o.get("enforcer_tool") == tool_name]
    if not due:
        return None
    promises = [ledger.get(o["id"]) for o in due]
    caps = [p.max_amount for p in promises if p.max_amount is not None]
    payees = {_norm(p.pay_to) for p in promises if p.pay_to}
    for path, value in _walk(args or {}):
        key = path[-1] if path else ""
        if caps and _AMOUNT_KEY.search(key):
            try:
                amount = float(str(value).replace("$", "").replace(",", ""))
            except ValueError:
                continue
            if amount > max(caps):
                return {"action": "block", "message": (
                    f"Accountability Partner: {amount:g} is over the {max(caps):g} limit the user "
                    "set for this consequence.")}
        if payees and _PAYEE_KEY.match(key) and _norm(str(value)) not in payees:
            return {"action": "block", "message": (
                "Accountability Partner: that recipient isn't the one the user named for this "
                "consequence.")}
    if not any(p.locked_until and locked(p, datetime.now()) for p in promises):
        return {"action": "approve", "message": (
            "Accountability Partner: carrying out a consequence the user chose. It isn't locked "
            "in, so it needs their yes."), "rule_key": "accountability-partner:consequence"}
    return None


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
        created = p.first_day()
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
        elif p.cadence == "weekly":
            kept = ledger.kept_between(p.id, start, today)
            said_n, did_n = said_n + p.per_week, did_n + min(kept, p.per_week)
            proven_n += min(ledger.kept_with_receipts(p.id, start, today), p.per_week)
            lines.append(f"- {p.what}: {kept} of {p.per_week}")
        elif p.due and start <= date.fromisoformat(p.due) <= today:
            verdict = ledger.last_report(p.id)
            said_n, did_n = said_n + 1, did_n + (1 if verdict else 0)
            lines.append(f"- {p.what}: {'done' if verdict else 'not done'}")
    if said_n == 0:
        return SILENT
    proof_note = f" ({proven_n} with receipts)" if proven_n else ""
    lines.append(f"You said {said_n}, you did {did_n}{proof_note}.")
    for p in ledger.active(include_finished=True):
        if not p.consequence:
            continue
        periods = ([_period(p, today)] if p.cadence == "weekly" else
                   [_period(p, d) for d in ledger.misses(p.id, start, today)])
        for period in periods:
            source = ledger.enforced(p.id, period)
            if source:
                consequences.append(f"{p.what}: {p.consequence}, done ✓ ({_tool_label(source)})")
            elif p.cadence != "weekly" or (today.weekday() == 6 and
                                           ledger.kept_between(p.id, start, today) < p.per_week):
                consequences.append(f"{p.what}: {p.consequence}, not enforced yet")
    if consequences:
        lines.append("Consequences: " + "; ".join(consequences) + ".")
    return "\n".join(lines)

