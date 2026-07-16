# Metrics & Analytics Layer — Runbook

Implements `specs/tuna-vpn-metrics-spec-en.md`. One append-only `events` table in
the shared Postgres, written async by bot + site and keyed on `remnawave_uuid`;
business events close the economic hypotheses, and `node_status` rows (from
Remnawave node webhooks) give passive node-health monitoring. Offline computation
only — no live dashboards.

> Note: the in-fork active TCP probe + threshold alert (metrics spec §6.2/§6.5)
> were removed — node health relies on stock Remnawave node webhooks
> (`node.connection_lost/restored/traffic_notify`) → `NodeConnectionLostEvent` /
> `NodeConnectionRestoredEvent` / `NodeTrafficReachedEvent` (admin notifications +
> `node_status` metric rows). Passive `first_connect` from real RU users stays the
> primary viability signal.

## What was built

| Piece | Where |
|---|---|
| `events` table (+ indexes) & `transactions.net_amount` | migration `0047_create_events.py`; model `infrastructure/database/models/event.py` |
| `EventsDao` (append + offline aggregation SQL) | `application/common/dao/event.py`, `infrastructure/database/dao/event.py` |
| `MetricsEventListener` (maps ~7 business + node events) | `infrastructure/services/metrics.py` |
| Metric-signal events (`FunnelStepEvent`, `ReferralCommissionRecordedEvent`) | `application/events/metrics.py` |
| Vocabulary (event types, sources, funnel steps) | `core/metrics.py` |
| `net_rub` capture (**seam only — not wired to a gateway yet**, see TODO) | gateway seam `payment_gateways/base.py` (`settled_amount`); persisted in `web/endpoints/payments.py`; column `transactions.net_amount` |
| `referral_attributed` emit | `use_cases/referral/commands/commission.py` (at the ledger-insert seam) |
| Funnel — site endpoint | `web/endpoints/public/events.py` → `POST /api/v1/public/events/funnel` |
| Funnel — bot emits | `telegram/routers/onboarding/{handlers,getters,metrics}.py` |
| Funnel — site emits | `tuna-site`: `lib/api.ts` `trackFunnel()`, `app/connect/page.tsx` |
| Offline job | `use_cases/metrics/commands/*`; cron in `infrastructure/taskiq/tasks/metrics.py` |

## Event catalog (`events.event_type`)

Business (§4): `trial_started, first_connect, trial_converted, payment,
subscription_renewed, churned, referral_attributed`. Funnel (§5): `funnel_step`.
Health (§6): `node_status` (from Remnawave node webhooks).

`source` ∈ `bot | site | psp`. Business events are backend-origin (`bot`),
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

## Operating

- **Daily business rollup** logs a structured summary at INFO with prefix
  `[metrics] daily business rollup:` (conversion rate, avg paying lifetime, plan mix,
  real net/gross fee curve by ₽ bucket, funnel step counts + drops). No dashboard by
  design; grep the logs or pipe the returned dict to a sink later.
- **Node health** is reported by stock Remnawave node webhooks: `node.connection_lost`
  / `node.connection_restored` / `node.traffic_notify` → admin notifications (routed
  via `SystemNotificationType.NODE_STATUS_CHANGED`, falls back to admins if unrouted)
  + `node_status` metric rows. No in-fork probe or threshold alert.

## Coverage & known limits (honest, per spec)

- **`net_rub` — TODO, not wired to any gateway.** The full pipeline is ready
  (`settled_amount` seam → persist → `transactions.net_amount` → payment event `net`),
  but no gateway sets `settled_amount`, so `net` is currently always NULL (excluded
  from the fee curve, not guessed). The real PSP hasn't been chosen. **To finish:**
  once it is, set `self.settled_amount` inside that provider's `handle_webhook` from
  its raw webhook body (the settled-after-fee amount) — a one-line change; everything
  downstream already works.
- **Node health** comes from stock Remnawave node webhooks only (`node_status` rows +
  admin notifications) — the in-fork active probe + threshold alert were removed. The
  honest limit stands: passive `first_connect` from real RU users is the real ТСПУ
  signal; don't over-weight node-level up/down.
- **Connect dimensions (§6.1)**: the Remnawave `FIRST_CONNECTED` webhook carries no
  node/protocol, so `first_connect` records `outcome=success` without them; the
  node-health signal comes from `node_status` (Remnawave node webhooks).
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

Full offline-job runs need a live Postgres + Redis and are exercised in staging,
not the sandbox.
