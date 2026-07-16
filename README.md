# TunaShop

**A Telegram bot for selling VPN subscriptions on [Remnawave](https://remna.st/) — a soft fork of [`snoups/remnashop`](https://github.com/snoups/remnashop) that adds a guided, platform‑aware onboarding funnel.**

TunaShop keeps 100% of upstream Remnashop's functionality (15 payment gateways, trials, referrals, promo codes, broadcasts, the admin dashboard, Remnawave sync) and layers a Tuna product idea on top: instead of a single **"Connect"** button, a new user is walked through **pick platform → install the Happ client → add the config in one tap → "It works? / Help" → done**, with optional pre‑connect reminder nudges for people who start but don't finish. A second **retention & UX layer** (built to UX spec v2) adds on‑connect trial‑timer restart, lifecycle followups, hub polish, a website referral link, and adaptive‑friction captcha — see [Retention & spec‑v2 UX](#retention--spec-v2-ux).

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
- **Per‑page banners** — every funnel screen has its own `BannerName` slot (`ONBOARDING_DEVICE` / `CONNECT` / `TV` / `TIPS` / `SUCCESS` / `FAIL`), so each onboarding page can carry a distinct image. Reuses the stock banner mechanism and its `use_banners` flag; each slot falls back to `default.jpg` until a file is dropped (see [Configuration](#configuration)).

---

## Retention & spec v2 UX

A second layer, built to the Tuna UX spec v2 (`specs/tuna-vpn-bot-ux-spec-v2-en.md`) and applied with the same **additive** discipline (new tables / event listeners / cron / middleware; upstream models and flows untouched). All of it is gated so it degrades cleanly.

- **Trial clock starts on first connection.** An additive listener on the existing `UserFirstConnectionEvent` (`src/infrastructure/services/trial_connection.py`) restarts a trial's expiry to `now + granted‑window` the first time the user actually connects, records a local `connected_once` milestone (`user_connection_states` table), and cancels the not‑connected nudge chain. *(This supersedes the old "trial lifecycle is unchanged" behaviour — activation still provisions the Remnawave user immediately, but the countdown is re‑anchored to first connect. Caveat: only fires if the user connects before the initially provisioned window lapses.)*
- **Lifecycle followups (chains C/E).** A unified sweeper (`lifecycle_followups` table + `ProcessDueLifecycleFollowups`, cron `*/10`) sends trial‑ending (−3h) and win‑back (+3d/+2w) touches, re‑validating live state before each send and honouring per‑user frequency caps. **Each chain is admin‑toggleable** in the dashboard (Dashboard → Remnashop → Notifications → user types: `FOLLOWUP_TRIAL_ENDING` / `FOLLOWUP_WINBACK`, default on). All followups — these plus the pre‑connect nudges — share one voice: a **bold headline then a CTA**. The pre‑connect **follow‑up A** ("Happ installed but VPN off") additionally carries a direct **Подключиться** deep link into Happ and its own `followup_connect` card banner. *(A former "habit" chain B was dropped, code and admin toggle alike.)*
- **Hub & purchase screens.** `/start` shows a greeting (`👋 Привет, {name}!`) under the `Tuna VPN 🐟 / Рассекаем волны блокировок` slogan instead of a profile block — the user's Telegram **ID is not shown** — with the active **plan name in the subscription header**. The primary button switches **🚀 Подключиться ↔ ➕ Новое подключение** on `connected_once`; a `💳 Оформить Standard` upsell + coral "trial ending" status appear when a trial has <4h left. The plan‑selection screen renders a **dynamic card per plan** (traffic / devices / shared locations); the duration screen lists every term with its price and an **auto‑computed savings %** (vs the 1‑month rate), one per row. The **Subscription** screen shows the active plan's card above a green **Продлить** / blue **Изменить**; plan buttons are blue. The **devices** screen leads with a bold `Подключено: N/M` count, colours device rows blue, and offers a green **📱 Добавить устройство** that stays available until the device limit — where it flips to a green **💳 Изменить подписку** (→ Subscription), the only way to raise the cap. Device rows drop the add‑date (kept in the per‑device card).
- **Referral screen (spec §4.7).** Rewritten to the spec's money‑model **copy** — «🤝 Реферальная система», the «Приглашай и зарабатывай» value‑props, and a 5‑line stats block — ahead of the payout backend: the ₽ lines (доход / выведено / доступно к выводу) render as `0` placeholders and no withdraw/balance buttons are shown yet. Two links (bot + a `https://{site}/r/{code}` site link when `REFERRAL_SITE_URL` is set). The copy‑link button is gone; **QR** is blue, **Пригласить** green.
- **Onboarding guard & polish.** «🎉 Работает!» won't advance to the success screen until the user has actually connected (`connected_once`); otherwise a branded alert nudges them to finish first. Funnel copy is bolded per spec; the connect CTA reads **➕ Добавить Tuna VPN**, «Не получается» is red, and the iOS store buttons are region‑labelled (App Store вне РФ / App Store РФ). The TV screen moves the Web‑Import fallback into a standalone «Важно:» note.

**Referral rewards backend** stays upstream's points/days engine (no real‑money rebuild yet) — the spec's 50%/payout/balance model is **screen copy only** for now. A few spec items are **admin config, not code**: create a single "Standard" plan with 1/3/6/12‑month durations (249/674/1199/2099 ₽); turn off the `device_all_reset` + `link_reset` flags (leaves per‑device unbind); a 72h referred trial = an `INVITED`‑availability trial plan alongside the 24h base.

> **Button colours.** Telegram inline buttons expose only three styles — blue (`PRIMARY`), green (`SUCCESS`), red (`DANGER`). Custom tints (e.g. yellow `#faab09`, a premium dark‑blue for a future Pro plan) aren't achievable; per‑plan colours would need a colour field on the plan model.

---

## Architectural goals

This fork is written to stay **easy to maintain and to re‑merge with upstream**. The rules we followed:

1. **Additive, not invasive.** New behaviour lives in *new files* (new router / use‑case / service packages, config fields, models + DAOs, `.ftl` files, taskiq tasks, event listeners, middleware, four migrations `0041`–`0044`). Edits to existing files are single, flag‑guarded lines/blocks. The retention layer (above) follows the same rule — additive event listeners + tables, no upstream‑model changes.
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

`docker-compose.local.yml` builds the image from source, so your fork's code is what runs. Migrations (`0041`–`0044`) are applied automatically by `docker-entrypoint.sh` (`alembic upgrade head`) on container start — no manual step. Then open the bot, go to **Dashboard → Remnashop → Extra → Пошаговое подключение**, and turn the funnel on.

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

Separate from the `ONBOARDING_*` group (both `APP_`‑scoped):

- `REFERRAL_SITE_URL` (default empty) — the marketing site base for the second referral link (`{site}/r/{code}`); empty ⇒ only the bot link is shown.

The server‑locations line («Локации») is now a **per‑plan** field edited in the dashboard plan editor (not an env var), so each plan can list its own flags.

### Banners (optional)

Banners reuse upstream's stock mechanism: each screen resolves an image *by name* and falls back to `default.jpg` when the file is absent, so they are opt‑in per screen. Drop files in `assets/banners/<locale>/<name>.<jpg|png|webp|gif>` (or `assets/banners/<name>.*`).

- Funnel slots: `onboarding_device`, `onboarding_connect` (the 3‑step connect screen), `onboarding_tv`, `onboarding_tips`, `onboarding_success`, `onboarding_fail`.
- Retention / purchase slots: `payment_method` (operator‑choice screen), `followup_connect` (the follow‑up A card), `device_remove` (device‑removal confirm screens).
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
- `src/core/enums.py` — `BannerName` gains the `ONBOARDING_*` per‑page slots plus `PAYMENT_METHOD` / `FOLLOWUP_CONNECT` / `DEVICE_REMOVE`; `UserNotificationType` gains the `FOLLOWUP_*` lifecycle types.
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
