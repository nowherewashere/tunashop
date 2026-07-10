# Metrics & Analytics Layer — Runbook

Implements `specs/tuna-vpn-metrics-spec-en.md`. One append-only `events` table in
the shared Postgres, written async by bot + site + probes and keyed on
`remnawave_uuid`; business events close the economic hypotheses, dimensioned
connect/probe events give passive VPN-health monitoring. Offline computation only —
no live dashboards.

## What was built

| Piece | Where |
|---|---|
| `events` table (+ indexes) & `transactions.net_amount` | migration `0047_create_events.py`; model `infrastructure/database/models/event.py` |
| `EventsDao` (append + offline aggregation SQL) | `application/common/dao/event.py`, `infrastructure/database/dao/event.py` |
| `MetricsEventListener` (maps ~7 business + node events) | `infrastructure/services/metrics.py` |
| Metric-signal events (`FunnelStepEvent`, `ReferralCommissionRecordedEvent`) | `application/events/metrics.py` |
| Vocabulary (event types, sources, funnel steps, thresholds) | `core/metrics.py` |
| `net_rub` capture | gateway seam `payment_gateways/base.py` (`settled_amount`); YooKassa `income_amount`; persisted in `web/endpoints/payments.py` |
| `referral_attributed` emit | `use_cases/referral/commands/commission.py` (at the ledger-insert seam) |
| Funnel — site endpoint | `web/endpoints/public/events.py` → `POST /api/v1/public/events/funnel` |
| Funnel — bot emits | `telegram/routers/onboarding/{handlers,getters,metrics}.py` |
| Funnel — site emits | `tuna-site`: `lib/api.ts` `trackFunnel()`, `app/connect/page.tsx` |
| Offline jobs + probe | `use_cases/metrics/commands/*`; cron in `infrastructure/taskiq/tasks/metrics.py` |
| Health alert copy | `assets/translations/ru/metrics.ftl` |

## Event catalog (`events.event_type`)

Business (§4): `trial_started, first_connect, trial_converted, payment,
subscription_renewed, churned, referral_attributed`. Funnel (§5): `funnel_step`.
Health (§6): `node_status` (from Remnawave node webhooks), `probe` (active checks).

`source` ∈ `bot | site | probe | psp`. Business events are backend-origin (`bot`),
except `payment`/`subscription_renewed` which are `psp` (PSP-webhook driven). Funnel
rows carry the true surface. Per-user rows are keyed by `user_ref = remnawave_uuid`
(`Subscription.user_remna_id`), resolved from the current subscription.

## Fire-and-forget guarantee (§2, §7)

Every write is off the user's critical path and swallows its own errors:
- `MetricsEventListener._write` wraps the whole unit of work in `try/except` (incl.
  opening it), so a failure never surfaces and never escapes into the bus's
  ErrorEvent fan-out.
- The site endpoint always returns `204`, rate-limited per IP, step-validated.
- `trackFunnel()` on the site never awaits into the UI and never throws.
- `net_rub` persistence and the referral emit are isolated in `try/except`.

## Schedules (taskiq cron, auto-discovered by `--tasks-pattern .../tasks/*.py`)

| Task | Cron | Job |
|---|---|---|
| `compute_daily_business_metrics_task` | `17 3 * * *` | conversion, lifetime cohort, plan mix, fee curve, funnel deltas |
| `compute_node_health_task` | `*/10 * * * *` | (node×protocol×operator) success rate + threshold alert |
| `run_node_probes_task` | `*/5 * * * *` | TCP reachability per node → `probe` rows |

## Operating

- **Daily business rollup** logs a structured summary at INFO with prefix
  `[metrics] daily business rollup:` (conversion rate, avg paying lifetime, plan mix,
  real net/gross fee curve by ₽ bucket, funnel step counts + drops). No dashboard by
  design; grep the logs or pipe the returned dict to a sink later.
- **Health alert** fires to the ops chat when a (node×protocol) slice drops below
  `HEALTH_SUCCESS_THRESHOLD` (80%) over `HEALTH_WINDOW_MINUTES` (15) with ≥
  `HEALTH_MIN_SAMPLES` (3) samples. Copy: `event-metrics-health-alert`
  (`assets/translations/ru/metrics.ftl`); routed via
  `SystemNotificationType.NODE_STATUS_CHANGED` (falls back to admins if unrouted).
  Tune thresholds in `core/metrics.py`.

## Coverage & known limits (honest, per spec)

- **`net_rub`**: implemented for **YooKassa** (`income_amount` = amount − commission).
  Other gateways keep `net = NULL` (excluded from the fee curve, not guessed). To add
  one: set `self.settled_amount` inside that gateway's `handle_webhook` from its raw
  body; the endpoint persists it automatically.
- **Probes** are **node-level TCP reachability** (`address:port`) — the honest limit
  of an external probe ("is the node up at all?", §6.4). `protocol`/`operator` are
  left null; per-protocol probing needs the hosts/inbounds inventory
  (`sdk.hosts`/`sdk.inbounds`) and is a clean follow-up. Don't over-weight external
  probes — passive `first_connect` from real RU users is the real ТСПУ signal.
- **Connect dimensions (§6.1)**: the Remnawave `FIRST_CONNECTED` webhook carries no
  node/protocol, so `first_connect` records `outcome=success` without them; the
  dimensioned health signal comes from `node_status` + `probe`.
- **Funnel**: bot emits `start → device_selected → app_install_shown → config_issued`
  (`device_selected` bot-only; the site auto-detects the device). `first_connect` and
  `trial_converted` complete the funnel as business events — the client never emits
  them and we never double-count.

## Migration numbering (parallel branches)

This branch adds **`0047`** off `0045`. A parallel Telegram-Stars workstream holds
**`0046`**, also off `0045`, so `alembic heads` will show two heads until integration.
At merge: run `alembic merge -m metrics_stars <0046> <0047>` (or renumber `0047` to
follow the Stars head). Both are additive; order is irrelevant.

## Verify (no live DB/nodes needed)

```bash
# lint + types
wsl bash -lc "cd /mnt/c/Users/amdma/claude/tuna/tunashop && uv run ruff check src/ && uv run mypy <touched files>"
# autodiscovery + no-notification-leak + DI wiring smoke test
PYTHONPATH=. uv run python scripts/smoke_metrics.py   # (see the session's scratchpad)
# frontend
cd tuna-site && npx tsc --noEmit && npx eslint src/
```

Full offline-job/probe/health-alert runs need a live Postgres + Redis + Remnawave
nodes and are exercised in staging, not the sandbox.
