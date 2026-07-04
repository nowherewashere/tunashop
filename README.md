# TunaShop

**A Telegram bot for selling VPN subscriptions on [Remnawave](https://remna.st/) — a soft fork of [`snoups/remnashop`](https://github.com/snoups/remnashop) that adds a guided, platform‑aware onboarding funnel.**

TunaShop keeps 100% of upstream Remnashop's functionality (15 payment gateways, trials, referrals, promo codes, broadcasts, the admin dashboard, Remnawave sync) and layers one product idea on top: instead of a single **"Connect"** button, a new user is walked through **pick platform → install the Happ client → add the config in one tap → "It works? / Help" → done**, with optional pre‑connect reminder nudges for people who start but don't finish.

> Fork lineage: upstream is `snoups/remnashop` (MIT). This repository tracks it and adds the onboarding feature as an **isolated, toggle‑able module**. See [Tracking upstream](#tracking-remnashop-upstream).

---

## What this fork adds

A self‑contained **onboarding funnel** (`src/telegram/routers/onboarding/`) plus its supporting pieces:

- **Guided connect flow** — an aiogram‑dialog with `PLATFORM → SETUP → REFRESH_TIP → SUCCESS → HELP` states. `SUCCESS` still surfaces the real Mini App / subscription‑page connect button.
- **Per‑platform install links** — iOS / Android / Windows / macOS Happ links, chosen by the user's platform (config‑driven, no hardcoded URLs in code).
- **One‑tap config delivery** — the personal subscription URL is wrapped into a `happ://add/{sub_url}` import deeplink (template is configurable).
- **Self‑service "not working" branch** — refresh guidance, change‑location hint, and escalation to support.
- **Config‑refresh tip** — the "press ⟳ in Happ to pull the latest fix" screen, with an optional video URL.
- **Pre‑connect follow‑up nudges** — a DB queue (`onboarding_nudges`) + a cron sweeper task that reminds users who opened the funnel but never completed it. Fires at most once per user per step; cancelled the moment they reach success or block the bot.
- **Admin on/off toggle** — Dashboard → Remnashop → Extra → **Пошаговое подключение**. When off, behaviour reverts *exactly* to upstream's single connect button.

The **trial/subscription lifecycle is unchanged** — the funnel is presentation only. Activating a trial still creates the Remnawave user immediately, exactly as upstream does.

---

## Architectural goals

This fork is written to stay **easy to maintain and to re‑merge with upstream**. The rules we followed:

1. **Additive, not invasive.** New behaviour lives in *new files* (a new router package, use‑case package, config module, model/DAO, `.ftl` file, taskiq task, two migrations). Edits to existing files are single, flag‑guarded lines/blocks.
2. **Feature‑flagged and reversible.** The whole funnel is gated by one runtime flag, `settings.extra.onboarding_enabled`. Flip it off and the bot behaves byte‑for‑byte like stock Remnashop — no redeploy needed.
3. **Config‑driven, never hardcoded.** All links, the deeplink template, the video URL, and the nudge schedule/caps come from an `ONBOARDING_*` env group with safe defaults (`src/core/config/onboarding.py`).
4. **Idiomatic to the host codebase.** We mirror Remnashop's own patterns — aiogram‑dialog windows/getters/handlers, dishka‑injected `Interactor` use‑cases, DAO protocols + DTOs, fluent `.ftl` i18n, numbered Alembic migrations, and a cron‑scheduled taskiq sweeper (the same shape as `cancel_old_transactions_task`).
5. **Clean layering.** No `application → telegram` imports; the one routing string the sweeper needs lives in `core/constants.py` (`ONBOARDING_GOTO_TARGET`).

---

## Install

### Local (identical to upstream)

Local install works **the same way as Remnashop** — the funnel needs no external image:

```bash
cp .env.example .env      # fill in the required values
make setup-env            # generate crypt/secret/db/redis secrets
make run-local            # builds from Dockerfile.local + starts db/redis
```

`docker-compose.local.yml` builds the image from source, so your fork's code is what runs. Migrations (`0041`, `0042`) are applied automatically by `docker-entrypoint.sh` (`alembic upgrade head`). Then open the bot, go to **Dashboard → Remnashop → Extra → Пошаговое подключение**, and turn the funnel on.

### Is there a prebuilt Docker image?

**Not yet for this fork.** Upstream ships `ghcr.io/snoups/remnashop:latest`, and the **prod** compose files (`docker-compose.prod.*.yml`) pull *that* upstream image — so as‑is, `make run-prod` would run upstream code, **not** ours. To deploy this fork in production you have two options:

- **Build locally in prod** — point the prod compose `image:`/build at this repo (as the local compose already does), or
- **Publish your own image** to `ghcr.io/nowherewashere/tunashop`:
  1. In `.github/workflows/prod-docker-release.yml`, change the hardcoded `tags:` from `ghcr.io/snoups/remnashop:*` to `ghcr.io/nowherewashere/tunashop:*` (the workflow already computes `IMAGE_REPO` from `${GITHUB_REPOSITORY}` — wire the push `tags` to it).
  2. Update the `image:` line in `docker-compose.prod.external.yml` / `docker-compose.prod.internal.yml` to `ghcr.io/nowherewashere/tunashop:latest`.
  3. Add a `GHCR_TOKEN` repo secret and publish a GitHub Release (or run the workflow via `workflow_dispatch`).

The `Dockerfile` itself is fork‑agnostic and needs no changes.

---

## Configuration

Runtime switch (admin, in the dashboard): `settings.extra.onboarding_enabled`.

Customization via env (`ONBOARDING_*`, all optional — see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `ONBOARDING_HAPP_LINK_IOS` | App Store | iOS Happ download link |
| `ONBOARDING_HAPP_LINK_ANDROID` | Google Play | Android Happ download link |
| `ONBOARDING_HAPP_LINK_WINDOWS` | GitHub releases | Windows Happ download link |
| `ONBOARDING_HAPP_LINK_MAC` | App Store | macOS Happ download link |
| `ONBOARDING_REFRESH_VIDEO_URL` | *(empty)* | "How to refresh" video; the button is hidden when unset |
| `ONBOARDING_HAPP_IMPORT_TEMPLATE` | `happ://add/{sub_url}` | Import deeplink template |
| `ONBOARDING_NUDGE_DELAYS_HOURS` | `0.5,3,24` | Pre‑connect nudge schedule |
| `ONBOARDING_NUDGE_MIN_GAP_MINUTES` | `180` | Min gap between nudges to one user |
| `ONBOARDING_NUDGE_DAILY_CAP` | `4` | Max nudges per user per day |

---

## Tracking Remnashop upstream

This repo is a fork, so keep upstream as a second remote and merge from it periodically.

```bash
# origin  -> git@github.com:nowherewashere/tunashop.git   (this fork)
# upstream-> https://github.com/snoups/remnashop.git       (source)
git remote add upstream https://github.com/snoups/remnashop.git   # if not present
git fetch upstream
git merge upstream/main        # or: git rebase upstream/main
```

Because the feature is additive and flag‑guarded, most merges touch only new files. The **small set of existing files we edit** (keep these in mind when resolving conflicts):

- `src/core/config/app.py` — one field wiring `OnboardingConfig`.
- `src/core/constants.py` — `ONBOARDING_GOTO_TARGET`.
- `src/application/dto/settings.py` — `ExtraSettingsDto.onboarding_enabled`.
- `src/application/use_cases/settings/commands/extra.py` (+ its `__init__`) — the `ToggleOnboarding` interactor.
- `src/telegram/states.py` — the `Onboarding` group + `RemnashopExtra.ONBOARDING`.
- `src/telegram/keyboards.py` — `onboarding_connect_buttons` + the `~onboarding_enabled` guard on `connect_buttons`.
- `src/telegram/routers/__init__.py` — one router registration.
- `src/telegram/routers/{menu,subscription}/{dialog,getters}.py` — one button + one getter key each.
- `src/telegram/routers/dashboard/remnashop/extra/{dialog,handlers,getters}.py` — the toggle row/window.
- DI + `__init__` aggregators: `di/providers/{use_cases,dao}.py`, dao/model/dto `__init__`.
- `assets/translations/ru/{buttons,messages}.ftl` — the extra‑toggle strings (new copy lives in the standalone `onboarding.ftl`).

### Watch‑outs when merging

- **Migration numbering.** Ours are `0041`/`0042`. If upstream adds migrations with the same numbers, renumber ours (and their `down_revision`) so the Alembic chain stays a single linear head.
- **`connect_buttons` / connect getters.** If upstream refactors the connect widget or its getters, re‑apply the `~F["onboarding_enabled"]` guard and the `onboarding_enabled` getter key.
- **`ONBOARDING_GOTO_TARGET`.** Must always equal the `Onboarding.PLATFORM` state string (`"Onboarding:PLATFORM"`); the nudge deeplink relies on Remnashop's `goto` router.
- **`ExtraSettingsDto`.** New upstream fields in `extra` merge cleanly (JSONB), but keep `onboarding_enabled` and its `0041` seed.

---

## Credits & license

Built on **[snoups/remnashop](https://github.com/snoups/remnashop)** — full credit to the upstream authors. Licensed under the **MIT License** (see [`LICENSE`](./LICENSE)); the original copyright is retained.
