# TunaShop

**A Telegram bot for selling VPN subscriptions on [Remnawave](https://remna.st/) — a soft fork of [`snoups/remnashop`](https://github.com/snoups/remnashop) that adds a guided, platform‑aware onboarding funnel.**

TunaShop keeps 100% of upstream Remnashop's functionality (15 payment gateways, trials, referrals, promo codes, broadcasts, the admin dashboard, Remnawave sync) and layers one product idea on top: instead of a single **"Connect"** button, a new user is walked through **pick platform → install the Happ client → add the config in one tap → "It works? / Help" → done**, with optional pre‑connect reminder nudges for people who start but don't finish.

> Fork lineage: upstream is `snoups/remnashop` (MIT). This repository tracks it and adds the onboarding feature as an **isolated, toggle‑able module**. See [Tracking upstream](#tracking-remnashop-upstream).

---

## What this fork adds

A self‑contained **onboarding funnel** (`src/telegram/routers/onboarding/`) plus its supporting pieces:

- **Guided connect flow** — an aiogram‑dialog with `ENTRY → PLATFORM → SETUP → REFRESH_TIP → SUCCESS → HELP → REFRESH_HAPP` states, ported screen‑for‑screen (text, buttons, staged nudges) from the Tuna source bot's `O0–O4` funnel + its "Не получается" branch. `SUCCESS` matches the source (a single "Открыть меню" button — no connect widget); the real connect action lives on `SETUP` step 2 ("Открыть в Happ").
- **Per‑platform install links** — iOS / Android / Windows / macOS Happ links, chosen by the user's platform (config‑driven, no hardcoded URLs in code).
- **One‑tap config delivery** — the personal subscription URL is wrapped into a `happ://add/{sub_url}` import deeplink (template is configurable).
- **Self‑service "not working" branch** — refresh guidance, change‑location hint, and escalation to support.
- **Config‑refresh tip** — the "press ⟳ in Happ to pull the latest fix" screen, with an optional video URL.
- **Pre‑connect follow‑up nudges** — a DB queue (`onboarding_nudges`) + a cron sweeper task that reminds users who opened the funnel but never completed it. Fires at most once per user per step; cancelled the moment they reach success or block the bot.
- **Admin on/off toggle** — Dashboard → Remnashop → Extra → **Пошаговое подключение**. When off, behaviour reverts *exactly* to upstream's single connect button.
- **Per‑page banners** — every funnel screen has its own `BannerName` slot (`ONBOARDING_ENTRY` / `PLATFORM` / `SETUP` / `REFRESH` / `SUCCESS` / `HELP`), so each onboarding page can carry a distinct image. Reuses the stock banner mechanism and its `use_banners` flag; each slot falls back to `default.jpg` until a file is dropped (see [Configuration](#configuration)).

The **trial/subscription lifecycle is unchanged** — the funnel is presentation only. Activating a trial still creates the Remnawave user immediately, exactly as upstream does.

---

## Architectural goals

This fork is written to stay **easy to maintain and to re‑merge with upstream**. The rules we followed:

1. **Additive, not invasive.** New behaviour lives in *new files* (a new router package, use‑case package, config module, model/DAO, `.ftl` file, taskiq task, two migrations). Edits to existing files are single, flag‑guarded lines/blocks.
2. **Feature‑flagged and reversible.** The whole funnel is gated by one runtime flag, `settings.extra.onboarding_enabled`. Flip it off and the bot behaves byte‑for‑byte like stock Remnashop — no redeploy needed.
3. **Config‑driven, never hardcoded.** All links, the deeplink template, the video URL, and the nudge schedule/caps come from an `ONBOARDING_*` env group with safe defaults (`src/core/config/onboarding.py`).
4. **Idiomatic to the host codebase.** We mirror Remnashop's own patterns — aiogram‑dialog windows/getters/handlers, dishka‑injected `Interactor` use‑cases, DAO protocols + DTOs, fluent `.ftl` i18n, numbered Alembic migrations, and a cron‑scheduled taskiq sweeper (the same shape as `cancel_old_transactions_task`).
5. **Clean layering.** No `application → telegram` imports; the routing strings the nudge buttons need live in `core/constants.py` (`ONBOARDING_GOTO_TARGET` / `ONBOARDING_GOTO_HELP`).

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

### Prebuilt Docker image

This fork publishes its own images to **`ghcr.io/nowherewashere/tunashop`**, and the prod compose files (`docker-compose.prod.*.yml`) already point at them — so `make run-prod` runs *this* fork's code:

- **`ghcr.io/nowherewashere/tunashop:latest`** and `:<tag>` — built by `prod-docker-release.yml` on each published GitHub Release.
- **`ghcr.io/nowherewashere/tunashop:dev`** — built by `dev-docker-release.yml` on every push to the `dev` branch.

Both workflows derive the image name from `${{ github.repository }}`, so they follow the repo automatically (no hardcoded owner). **One-time setup:** add a `GHCR_TOKEN` repository secret (a PAT with `write:packages`) so CI can push to GHCR; then publish a Release (or run the release workflow via `workflow_dispatch`) to produce `:latest`. The `Dockerfile` is fork-agnostic and needs no changes.

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

### Banners (optional)

Banners reuse upstream's stock mechanism: each screen resolves an image *by name* and falls back to `default.jpg` when the file is absent, so they are opt‑in per screen. Drop files in `assets/banners/<locale>/<name>.<jpg|png|webp|gif>` (or `assets/banners/<name>.*`).

- Funnel slots: `onboarding_entry`, `onboarding_platform`, `onboarding_setup`, `onboarding_refresh` (shared by the tip + refresh screens), `onboarding_success`, `onboarding_help`.
- Devices screen: `devices` (slot already existed upstream — it just needs a file).

Rendering is gated by the stock `config.bot.use_banners` flag: **off** → the funnel stays plain‑text (byte‑for‑byte the source screens); **on** → each page shows its banner (falling back to `default.jpg` until you add per‑page images).

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
- `src/core/constants.py` — `ONBOARDING_GOTO_TARGET` + `ONBOARDING_GOTO_HELP`.
- `src/core/enums.py` — `BannerName` gains the `ONBOARDING_*` per‑page slots.
- `src/application/dto/settings.py` — `ExtraSettingsDto.onboarding_enabled`.
- `src/application/use_cases/settings/commands/extra.py` (+ its `__init__`) — the `ToggleOnboarding` interactor.
- `src/telegram/states.py` — the `Onboarding` group (`ENTRY → PLATFORM → SETUP → REFRESH_TIP → SUCCESS → HELP → REFRESH_HAPP`) + `RemnashopExtra.ONBOARDING`.
- `src/telegram/keyboards.py` — `onboarding_connect_buttons` (launches at `Onboarding.ENTRY`) + the `~onboarding_enabled` guard on `connect_buttons`.
- `src/telegram/routers/__init__.py` — one router registration.
- `src/telegram/routers/{menu,subscription}/{dialog,getters}.py` — one button + one getter key each.
- `src/telegram/routers/dashboard/remnashop/extra/{dialog,handlers,getters}.py` — the toggle row/window.
- DI + `__init__` aggregators: `di/providers/{use_cases,dao}.py`, dao/model/dto `__init__`.
- `assets/translations/ru/{buttons,messages}.ftl` — the extra‑toggle strings (new copy lives in the standalone `onboarding.ftl`).

Beyond the onboarding feature, two **fork‑maintenance edits** exist for compatibility (not part of the funnel — but they touch upstream files, so keep them in mind when merging):

- `src/infrastructure/taskiq/tasks/update.py` — `_parse_version()` makes the hourly `check_bot_update` task tolerate our non‑PEP 440 fork tag. Our release tag is `0.8.2-tuna.1` (from `BUILD_TAG`), which `packaging.Version()` rejects outright, crashing the task every hour. The helper strips the `-tuna.N`/`+tuna.N` suffix to the upstream base version we compare against, and returns `None` (skip + warn) on any unparseable tag instead of raising. Upstream versions are always clean, so upstream will never add this — **carry it forward**.
- `pyproject.toml` + `uv.lock` — the `remnapy` git pin is bumped from `95e15ed` (contract 2.7.0) to the 2.8.0‑aligned `main` tip `0680253`, because **Remnawave panel 2.8.0** (late Jun 2026) renamed the HWID device `userUuid` field to numeric `userId` and added `requestIp`. remnapy 2.7.0's `HwidDeviceDto` required `userUuid`, so the devices screen 500'd against a 2.8.0 panel. The `0680253` model makes both `user_uuid`/`user_id` optional (backward‑compatible with 2.7.x). This is a **stop‑gap**: once upstream ships its own tested 2.8.0 remnapy pin, take theirs and drop ours (see watch‑outs). Verified the fork's whole remnapy surface — all imports, 24 SDK `controller.method` calls, and every device field it reads — is intact on `0680253`.

### Watch‑outs when merging

- **Migration numbering.** Ours are `0041`/`0042`. If upstream adds migrations with the same numbers, renumber ours (and their `down_revision`) so the Alembic chain stays a single linear head.
- **`connect_buttons` / connect getters.** If upstream refactors the connect widget or its getters, re‑apply the `~F["onboarding_enabled"]` guard and the `onboarding_enabled` getter key.
- **`ONBOARDING_GOTO_TARGET` / `ONBOARDING_GOTO_HELP`.** Must equal the `Onboarding.ENTRY` / `Onboarding.HELP` state strings (`"Onboarding:ENTRY"`, `"Onboarding:HELP"`); the staged nudge buttons rely on Remnashop's `goto` router to reopen the funnel at the start or the fail branch.
- **`ExtraSettingsDto`.** New upstream fields in `extra` merge cleanly (JSONB), but keep `onboarding_enabled` and its `0041` seed.
- **`BannerName` enum.** Our `ONBOARDING_*` members append after upstream's; `StrEnum` values have no positional dependency, so keep both sides on a conflict. The funnel windows reference the slots by name — don't rename them without updating `routers/onboarding/dialog.py`.
- **remnapy pin (guaranteed conflict on the 2.8.0 merge).** Our `[tool.uv.sources] remnapy` rev + the `uv.lock` remnapy block collide 1:1 with upstream's own 2.8.0 bump. Resolve by **taking upstream's pin** (theirs is the version the whole app is tested against — ours was only a stop‑gap), then re‑run `uv lock` to regenerate the lockfile — **never hand‑merge `uv.lock`**. Don't keep `0680253` once upstream has a tested pin. If upstream moves remnapy to a tagged PyPI release, the `[tool.uv.sources]` git override for remnapy goes away entirely.
- **`_parse_version` in `update.py`.** Keep it — it exists for *our* fork tag, not a bug upstream shares, so upstream will never contribute it. Re‑apply if an upstream refactor of `update.py` conflicts. (Alternative once addressed: tag fork releases as `0.8.2+tuna.1` — a PEP 440 local version — which parses natively; the guard then just becomes defensive.)

---

## Credits & license

Built on **[snoups/remnashop](https://github.com/snoups/remnashop)** — full credit to the upstream authors. Licensed under the **MIT License** (see [`LICENSE`](./LICENSE)); the original copyright is retained.
