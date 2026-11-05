# Accountability Partner for Hermes

Hermes does what you ask. This plugin makes it hold you to what **you** said you'd do, and it checks
receipts instead of just taking your word for it.

- **Promises in your own words.** Say "I'll make 40 calls every weekday" or "gym 3x a week, or I owe
  $20 to charity" in any chat. Hermes offers to save it, with your exact quote.
- **A nightly check-in.** One message lists today's promises. You answer with one tap: `yes no`,
  `✅❌` or `all done`.
- **Receipts from whatever you've connected.** A promise can say where proof lives and what counts,
  in your words: "a workout on my WHOOP counts", "a commit to my repo on GitHub", "a Strava run over
  5k", "a visit to the gym" from a location tool. Before
  each check-in, Hermes looks with your connected tools (any MCP server or plugin) and marks what it
  can prove. It only asks you about the rest.
- **Your rule, checked by code.** Say what counts ("a 30-minute WHOOP workout counts") and the
  plugin saves it as a rule (`minutes >= 30`) on that tool's data. At check-in Hermes fetches the
  data and the plugin, not the model, decides. If the data falls short or is missing, nothing is
  marked missed: you're asked, and the check-in shows what the tool saw. The plugin knows nothing about any one service: it works
  with whatever your Hermes can already reach.
- **Consequences that actually happen.** "If I miss the gym, send $20 to charity from my wallet" or
  "block Instagram for a day." On a miss, Hermes carries it out with whatever you've connected: an
  agent wallet, a Screen Time or app-blocking tool, anything with a tool. It only counts as done when
  that tool's result shows it (a transfer id, a block confirmation). Money and phone locks go through
  Hermes's normal approvals like any other tool call. The plugin knows nothing about any one wallet
  or app, so any tool can become an enforcer.
- **Lock it in.** Say "lock it in, hold me to it" and the promise is locked until an end date you
  pick (90 days at most). After a 24-hour cool-off it can't be dropped or softened, and on a miss its
  consequence fires without asking again. The one yes happens at setup: you give the enforcing tool
  a standing OK in Hermes ("always"). Rails are enforced in code on every call to that tool while a
  consequence is owed: never more than the amount you set, never to anyone but the recipient you
  named. A consequence that isn't locked in always asks for your yes first.
- **An honest score.** Streaks, "2 of 3 this week", and a Sunday receipt: *you said 12, you did 9*,
  plus any consequence you chose for a miss.
- **No fudging, enforced in code.** Only your own words (or a real receipt) add, drop or mark a
  promise. Every tool that changes the ledger needs a quote, and the plugin checks that the quote
  really is in your current message. The agent can't invent a promise, can't mark you "done" on its own judgment, and can't
  round a miss up to a win, because every number comes from the ledger rather than the model.
  Receipts follow the same rule: the plugin watches tool results through Hermes's `post_tool_call`
  hook, and `promise_prove` is refused unless its evidence is text that tool really returned in this
  session. The agent can't claim "I saw a run on Strava" without a Strava result that says so.

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
| "Ship code every weekday, check my GitHub" | Proven from your commits each night, no question asked |
| "Gym 3x a week or send $20 to GiveDirectly. Lock it in till New Year." | Locked: a missed week sends $20 (max), only to GiveDirectly, no backing out |
| `yes no` (after a check-in) | Saved by the plugin itself, before the model runs |
| "Went to the gym today" | The agent records it, quoting you |
| "Drop the stretching one" | Removed, with your quote on file |
| `/promises` | Your promises and this week's score, no model call |

A weekly goal's consequence comes due on Sunday, when the week is actually missed, not on the night
of a single skip. Daily, weekday and one-time promises come due on the night of the miss. The Sunday
receipt lists each one as "done ✓" (with the tool that did it) or "not enforced yet".

To mark something kept, the quote must be in the user's message and can't be preceded or carried by
a "didn't / not / skipped" word. So "I didn't go to the gym" can never be quoted into a "done".

## Tools, hooks and commands

| Name | Kind | What it does |
| --- | --- | --- |
| `promise_add` | tool | Save a promise. Needs `user_quote` from the user's current message. |
| `promise_prove` | tool | Mark a promise kept from a tool's result. The evidence must be text that tool returned this session. |
| `promise_enforced` | tool | Record that a missed promise's consequence was carried out. The evidence must be text the tool that did it returned this session. |
| `promise_lock` | tool | Lock a promise in, only on the user's explicit words ("lock it in", "hold me to it"). Needs a consequence, its enforcing tool and, for money, a max amount. |
| `promise_record` | tool | Mark promises kept or missed today or yesterday. Needs `user_quote`. |
| `promise_drop` | tool | Drop a promise. Needs `user_quote`. |
| `promise_list` | tool | Promises with this week's score. |
| `promise_checkin` | tool | Lists promises to look for receipts on, then builds tonight's check-in (used by the nightly blueprint). |
| `promise_report` | tool | Builds the weekly receipt (used by the weekly blueprint). |
| `pre_llm_call` | hook | Remembers the user's current message (in memory only) for the quote check, and saves a clean `yes no` check-in answer. |
| `post_tool_call` | hook | Keeps recent tool results per session in memory (30 minutes, never on disk) so receipts can be checked. |
| `pre_tool_call` | hook | While a consequence is owed through a tool, blocks calls to it over the amount or to another recipient, and asks for the user's yes unless the promise is locked in. Other tool calls are left alone. |
| `/promises` | command | Shows the list without a model call. |

## What it stores, and what it doesn't

- One sqlite file per profile: `<HERMES_HOME>/plugin-data/accountability-partner/ledger.db`. It holds
  your promises, the quotes they came from, and your answers.
- The `pre_llm_call` hook sees each user message so it can check quotes and read check-in answers.
  It keeps the latest message per session **in memory only**, for 15 minutes, and never writes it to
  disk unless it becomes a quote on a promise you saved.
- The `post_tool_call` hook sees tool results so it can check receipts. It keeps the last 40 per
  session in memory for 30 minutes. Only the short evidence quote of a receipt is written to disk.
- The `pre_tool_call` hook sees tool arguments, but only acts on calls to a tool named as a promise's
  enforcer while a consequence is owed.
- No network calls, no shell commands, no background threads, no secrets, no telemetry.
  The plugin never calls your connected tools itself; the agent does, through Hermes, with your
  normal approvals. The schedules are ordinary Hermes cron jobs that you turn on yourself.

## Develop

```bash
python -m pytest tests
hermes plugins validate . --install-deps
```

MIT licensed.
