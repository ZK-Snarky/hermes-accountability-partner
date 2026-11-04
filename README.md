# Accountability Partner for Hermes

Hermes does what you ask. This plugin makes it hold you to what **you** said you'd do.

- **Promises in your own words.** Say "I'll make 40 calls every weekday" or "gym 3x a week, or I owe
  $20 to charity" in any chat. Hermes offers to save it, with your exact quote.
- **A nightly check-in.** One message lists today's promises. You answer with one tap: `yes no`,
  `✅❌` or `all done`.
- **An honest score.** Streaks, "2 of 3 this week", and a Sunday receipt: *you said 12, you did 9*,
  plus any consequence you chose for a miss.
- **No fudging, enforced in code.** Only your own words add, drop or mark a promise. Every tool that
  changes the ledger needs a quote, and the plugin checks that the quote really is in your current
  message. The agent can't invent a promise, can't mark you "done" on its own judgment, and can't
  round a miss up to a win, because every number comes from the ledger rather than the model.

## Install

```bash
hermes plugins install accountability-partner     # once it's in the catalog
# or straight from GitHub:
hermes plugins install https://github.com/ZK-Snarky/hermes-accountability-partner
hermes plugins enable accountability-partner
```

Then turn on the two schedules from the blueprint gallery (`/blueprint`, or the dashboard):

- **Nightly check-in**: default 21:00, delivered to the chat you set it up from.
- **Weekly receipt**: Sundays, default 18:00.

Dates follow the machine's local time. Set `TZ` for another time zone.

## Use

| You say | What happens |
| --- | --- |
| "I'll stretch every day" | Saved as a daily promise, with your quote |
| "Read 20 pages every weekday" | Weekdays only; weekends are never asked or counted |
| "Gym 3x a week. If I miss, no Netflix Sunday" | Weekly goal of 3, with your consequence |
| "Send the deck to Sam by Friday" | One-time promise with a due date |
| `yes no` (after a check-in) | Saved by the plugin itself, before the model runs |
| "Went to the gym today" | The agent records it, quoting you |
| "Drop the stretching one" | Removed, with your quote on file |
| `/promises` | Your promises and this week's score, no model call |

A weekly goal's consequence is named in the Sunday receipt, when the week is actually missed, not
on the night of a single skip. Daily, weekday and one-time promises name it on the night.

To mark something kept, the quote must be in the user's message and can't be preceded or carried by
a "didn't / not / skipped" word. So "I didn't go to the gym" can never be quoted into a "done".

## Tools, hooks and commands

| Name | Kind | What it does |
| --- | --- | --- |
| `promise_add` | tool | Save a promise. Needs `user_quote` from the user's current message. |
| `promise_record` | tool | Mark promises kept or missed today or yesterday. Needs `user_quote`. |
| `promise_drop` | tool | Drop a promise. Needs `user_quote`. |
| `promise_list` | tool | Promises with this week's score. |
| `promise_checkin` | tool | Builds tonight's check-in (used by the nightly blueprint). |
| `promise_report` | tool | Builds the weekly receipt (used by the weekly blueprint). |
| `pre_llm_call` | hook | Remembers the user's current message (in memory only) for the quote check, and saves a clean `yes no` check-in answer. |
| `/promises` | command | Shows the list without a model call. |

## What it stores, and what it doesn't

- One sqlite file per profile: `<HERMES_HOME>/plugin-data/accountability-partner/ledger.db`. It holds
  your promises, the quotes they came from, and your answers.
- The `pre_llm_call` hook sees each user message so it can check quotes and read check-in answers.
  It keeps the latest message per session **in memory only**, for 15 minutes, and never writes it to
  disk unless it becomes a quote on a promise you saved.
- No network calls, no shell commands, no background threads, no secrets, no telemetry.
  The schedules are ordinary Hermes cron jobs that you turn on yourself.

## Develop

```bash
python -m pytest tests
hermes plugins validate . --install-deps
```

MIT licensed.
