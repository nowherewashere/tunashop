# Remnawave 2.8 → 3.x cutover runbook

Rehearsed end to end on the lab host on 2026-08-05 (panel 2.8.0 → 3.2.1, bot alembic
0051 → 0058). Every command below was run there and is reproduced verbatim; every
"should print" is the output actually observed, not a guess.

The lab differs from prod in exactly one way: the panel is co-located instead of on its
own VPS. That changes only *where* you run the panel commands (`/opt/remnawave` vs the
panel host), never their order.

---

## 0. Read this first — three things that surprised the rehearsal

**The old bot image cannot start once 0055 has run.** Alembic dies with
`Can't locate revision identified by '0055'` and the container crash-loops. 0055 is
therefore the point of no easy return: rolling back needs `alembic downgrade` (or a dump
restore), not just re-pinning the image tag. Everything before 0055 is free.

**`APP_SECRET` on the 3.x panel must be the old `JWT_AUTH_SECRET`, not
`JWT_API_TOKENS_SECRET`.** 3.x collapses both 2.8 secrets into one `APP_SECRET`. Despite
the name, 2.8 signed API tokens with `JWT_AUTH_SECRET` — verified by recomputing the
bot token's HMAC against both candidates. Choosing the plausible-looking one leaves every
API token 401ing (bot *and* subscription page) with nothing in the panel log explaining
why. See §3.

**Retired rows are not what the code expects.** Migration 0056 and the backfill both
document "a retired row's panel user is usually gone". On the lab, both `DELETED` rows'
panel users were alive — the rows share a panel user with a live subscription of the same
person. All 9 rows resolved and **nothing was parked on the sentinel**. Expect the same
shape on prod, and treat a non-empty "retired subscription(s) have no panel user left"
list as something to read, not skip. See §Defects D-1.

---

## 1. Preconditions

- The new image is built and present on the app host. It is used as a **toolbox** for
  steps 2–5 and only becomes the running service in step 7.
- `deploy/backfill_remna_ids.py` ships inside it (`docker run --rm --entrypoint sh
  <image> -c 'ls deploy/'`). Older images do not have it — see D-2.
- Both databases are dumped and a restore is proven (§7).
- You know which compose project owns the panel. On the lab: `/opt/remnawave`
  (project `remnawave`), separate from the bot's `/home/ubuntu/tunashop` (project
  `tunashop`).

Set once, used throughout:

```bash
IMAGE=tunashop:cutover-test; ENVFILE=/home/ubuntu/tunashop/.env; NET=remnawave-network
```

### Why `docker run` and not `docker compose run`

The bot's compose service pins `ipv4_address` (a static IP, so nginx's cached upstream
resolution stays valid). `docker compose run` tries to claim that same address for the
throwaway container and dies:

```
Error response from daemon: failed to set up container networking: Address already in use
```

Plain `docker run --network <net>` takes a free address and works alongside the running
bot. No `--entrypoint ""` is needed either: the Dockerfile sets `CMD`, not `ENTRYPOINT`,
so a command argument replaces `docker-entrypoint.sh` — and with it the unconditional
`alembic upgrade head` that would otherwise run 0056 far too early.

---

## 2. Steps 2–3 run with the bot UP (no downtime yet)

### Step 2 — migrate to 0055 and stop there

```bash
sudo -n docker run --rm --network "$NET" --env-file "$ENVFILE" "$IMAGE" \
  alembic -c src/infrastructure/database/alembic.ini upgrade 0055
```

Should print `Running upgrade 0051 -> 0052` … `0054 -> 0055` and exit 0. Confirm:

```bash
sudo -n docker exec remnashop-db psql -U remnashop -d remnashop -tAc \
  "select version_num from alembic_version"                 # -> 0055
sudo -n docker exec remnashop-db psql -U remnashop -d remnashop -tAc \
  "select count(*) filter (where user_remna_id_bigint is null)||'/'||count(*) from subscriptions"
```

The second must read `N/N` — 0055 only opens the empty column.

**Fails if** the bot is mid-write on a table 0052–0054 alter. Harmless to retry.
**From here the old image can no longer start.**

### Step 3 — backfill, against the still-2.8 panel

```bash
sudo -n docker run --rm --network "$NET" --env-file "$ENVFILE" "$IMAGE" \
  python deploy/backfill_remna_ids.py --dry-run
```

Should print, for a healthy run:

```
9 subscription(s) need a panel id
would resolve 9, no such panel user 0, unreachable 0
```

Exit 0 and **nothing written**. Then drop `--dry-run` and re-run; it prints
`resolved 9, …` and exits 0.

Read the report rather than the exit code:

- `unreachable N` — the panel never answered. Never proceed; fix connectivity and re-run.
  This is now its own category precisely so it cannot be mistaken for the next one.
- `N retired subscription(s) have no panel user left` — those rows will be parked on
  panel id 0 by 0056. On the lab this list was **empty**. If it is non-empty on prod,
  confirm each row really is retired before continuing.
- `N LIVE subscription(s) could not be resolved` — blocks 0056. Retire or fix by hand
  **now**, while the uuid still exists to look at.

**Capture the mapping before it is destroyed** — 0056 drops the uuid column and the 3.x
panel drops `users.uuid`, so this is the last moment the translation exists anywhere:

```bash
sudo -n docker exec remnashop-db psql -U remnashop -d remnashop -c \
 "copy (select id, user_id, status::text, user_remna_id::text, user_remna_id_bigint
        from subscriptions order by id) to stdout with csv header" > uuid-to-panelid-map.csv
```

---

## 3. Step 4 — downtime starts: stop the bot, upgrade the panel

```bash
sudo -n docker stop remnashop remnashop-taskiq-worker remnashop-taskiq-scheduler
```

The old image speaks the 2.8 uuid API; it must not be running against a 3.x panel.

**Add `APP_SECRET` to the panel env before switching the tag.** Without it 3.x refuses
to boot — every PM2 worker loops on:

```
❌ APP_SECRET: Invalid input: expected string, received undefined
```

and the container sits `unhealthy` indefinitely while *looking* like it is running
(`docker ps` shows `Up`, `RestartCount 0`).

```bash
sudo -n sh -c 'v=$(grep -E "^JWT_AUTH_SECRET=" /opt/remnawave/.env | cut -d= -f2-);
  printf "\n# 3.x: replaces JWT_AUTH_SECRET + JWT_API_TOKENS_SECRET.\nAPP_SECRET=%s\n" "$v" \
  >> /opt/remnawave/.env'
```

`JWT_AUTH_SECRET`, **not** `JWT_API_TOKENS_SECRET` — see §0. To check before restarting,
recompute the bot token's signature locally; only the correct secret reproduces it:

```bash
python3 - <<'PY'
import base64, hmac, hashlib, os
tok = os.environ["TOK"]; h, p, sig = tok.split(".")
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
for name in ("JWT_AUTH_SECRET", "JWT_API_TOKENS_SECRET"):
    calc = b64(hmac.new(os.environ[name].encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    print(name, "MATCH" if calc == sig else "no")
PY
```

Then switch the tag and recreate:

```bash
sudo -n sed -i 's|image: remnawave/backend:2|image: remnawave/backend:3|' \
  /opt/remnawave/docker-compose.yml
cd /opt/remnawave && sudo -n docker compose up -d remnawave
```

Healthy in ~30s once `APP_SECRET` is right. Verify the panel actually migrated —
`users.uuid` is gone and `t_id` has become `id`:

```bash
sudo -n docker exec remnawave-db psql -U postgres -d postgres -c \
  "select id, username, status from users order by id"
```

Those `id` values must equal the `user_remna_id_bigint` you backfilled.

**Fails if** `APP_SECRET` is missing (boot loop, above) or wrong (panel healthy, every
API call 401 — including the bot's, with no panel-side log line).

---

## 4. Step 5 — finish the migrations

```bash
sudo -n docker run --rm --network "$NET" --env-file "$ENVFILE" "$IMAGE" \
  alembic -c src/infrastructure/database/alembic.ini upgrade head
```

Should print:

```
Running upgrade 0055 -> 0056
0056: remapped 82 event user_ref(s) and 0 referrer_ref(s)
Running upgrade 0056 -> 0057
Running upgrade 0057 -> 0058
```

A `0056: parked N retired subscription(s) on panel id 0` line appears **only if** the
backfill left retired rows unresolved. It did not on the lab, and its absence is correct
there — do not treat a missing line as a failure.

**Fails if** the backfill was skipped or left live rows unresolved: 0056's guard raises
`N live subscription(s) still have no panel id`, changes nothing, and the fix is to go
back and run step 3.

> **Prod timing — measure this yourself.** The lab's `events` table is 207 rows / 192 kB,
> so its remap is instant and says nothing about prod. Before the window, run:
> `SELECT count(*), pg_size_pretty(pg_total_relation_size('events')) FROM events;`
> The remap is two full `UPDATE … FROM` passes over `events`; size it accordingly.

---

## 5. Step 6 — verify the data, not the exit code

```bash
sudo -n docker exec remnashop-db psql -U remnashop -d remnashop -c "
  select (select version_num from alembic_version) alembic,
         (select data_type||' null='||is_nullable from information_schema.columns
           where table_name='subscriptions' and column_name='user_remna_id') col,
         (select count(*) from subscriptions where user_remna_id = 0) on_sentinel,
         (select count(*) from events where user_ref ~*
           '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') still_uuid,
         (select count(*) from events where user_ref ~ '^[0-9]+$') numeric_ref"
```

Lab result: `0058 | bigint null=NO | 0 | 0 | 82`.

`still_uuid` should equal the number of event rows whose panel user has no subscription
row left. If you expect zero and get more, the remap missed pairs — investigate before
opening the doors.

---

## 6. Step 7 — start the new bot

```bash
sudo -n sed -i "s|^TUNASHOP_IMAGE=.*|TUNASHOP_IMAGE=$IMAGE|" "$ENVFILE"
cd /home/ubuntu/tunashop && sudo -n docker compose up -d
```

The entrypoint's `alembic upgrade head` is now a no-op. Confirm the panel handshake:

```bash
sudo -n docker logs remnashop 2>&1 | grep -i "connected to Remnawave"
# Successfully connected to Remnawave panel (version: 3.2.1)
```

**Fails if** the panel is below `REMNAWAVE_MIN_VERSION` (3.0.0) — the bot refuses to
start, by design.

### The API token

Panel 3.0.0 renamed the scopes behind the connections endpoints (`ip-control:*` →
`connections:*`). Verified empirically against 3.2.1 by minting one token per scope:

| token scope | `POST /api/connections/drop` |
|---|---|
| `ip-control:drop-connections` | **403 Forbidden** |
| `connections:drop` | passes authorization (400 on body shape) |

A token whose `scopes` column is `{*}` — which is what both lab tokens are — is
unaffected and needs no reissue. **Check yours before planning a reissue:**

```bash
sudo -n docker exec remnawave-db psql -U postgres -d postgres -c \
  "select name, scopes from api_tokens"
```

If a token carries explicit `ip-control:*` scopes, reissue it with `connections:*` from
the panel dashboard — the API-tokens controller rejects API-token auth and requires an
admin session, so this cannot be scripted with the bot's own token.

A missed scope is now loud rather than silent: `drop_connections` re-raises the auth
family, verified by running the bot against a deliberately old-scoped token —

```
ERROR … Not authorised to drop connections for RemnaUser '3': API Error HTTP_403 …
        The panel API token must be valid and hold the 'connections:drop' scope,
        which panel 3.0.0 renamed from 'ip-control:*'.
RAISED ForbiddenError
```

---

## 7. Rollback

Restore is one command per stack (`restore.sh` on the lab, §Phase 0 artefacts):

```bash
/home/ubuntu/cutover-backups/restore.sh /home/ubuntu/cutover-backups/pre-panel-upgrade all
```

Rolling the panel back also needs the image tag re-pinned to `remnawave/backend:2` and
the container recreated; the DB restore alone is not enough.

**`pg_restore --clean` is not sufficient and this bit us in rehearsal.** `--clean` only
drops objects present in the dump, so tables created by newer migrations (0057
`broadcast_bonus_claim`, 0058 `traffic_pools`) survive a "restore" while
`alembic_version` is rewound — and the next `alembic upgrade` then dies on an existing
relation. A correct restore drops every non-system schema first (`public` **and**
`admin` — this install has both) and then restores. Proven by leaving a canary table
behind: it survived `--clean` and was gone after the schema-drop restore.

---

## 8. What broke, by severity

### D-1 · High · Docs and reports describe retired rows wrongly

0056 and the backfill both assert "a retired row's panel user is usually gone", and
0056's `REMAP_CTE` comment claims a uuid→id tie "cannot happen". On the lab neither
holds: both `DELETED` rows share a live panel user with an `ACTIVE` row of the same
person (9 rows → 7 distinct uuids), and all 9 resolved against 2.8.

Nothing malfunctioned — the code handles this correctly, and `min()` is harmless because
duplicate rows carry the same uuid and so the same id. The risk is operator judgement: a
runbook that says "retired rows are expected to be unresolvable" invites skimming past a
list that on this data should be empty. **Not fixed in code** — it is a comment/expectation
mismatch, and the rehearsal's finding is recorded here instead.

### D-2 · High · The backfill could not run at all — four independent reasons *(fixed)*

Each would have stopped the rollout in the window between 0055 and 0056:

1. **`deploy/` was never copied into the image.** The Dockerfile ships `./src`, `./assets`
   and the entrypoint only, so the one script that must run mid-migration was absent from
   the only environment with its `asyncpg`/`httpx` deps.
   → `COPY ./deploy ./deploy`.
2. **Wrong panel port/scheme.** `_panel_base_url()` prepended `http://` and stopped, while
   the app's `RemnawaveConfig.url` appends `:3000` to a portless http host and promotes a
   bare domain to `https`. `REMNAWAVE_HOST=remnawave` — the `.env.example` default — sent
   the backfill to port 80. Diverged on 3 of 6 realistic host forms.
3. **Wrong database variables.** It read `POSTGRES_USER`/`PASSWORD`/`DB`; the bot sets
   `DATABASE_*` and nothing else, so every run died on `KeyError: 'POSTGRES_USER'`.
4. **Missing panel headers.** An internal (`http://`) panel drops requests without
   `x-forwarded-proto`/`-for`; httpx surfaces that as
   `RemoteProtocolError: Server disconnected without sending a response` — no status
   code, nothing resembling an auth or routing fault.

Fixed by deleting the duplicate definitions rather than resyncing them: the script now
reads `DatabaseConfig` and `RemnawaveConfig`, and the header set lives once as
`RemnawaveConfig.client_headers`, used by both the DI provider and the script.

### D-3 · High · A panel blip was reported as a deleted panel user *(fixed)*

Any exception counted as "unresolved", and unresolved + `DELETED` printed as
*"retired subscription(s) have no panel user left (expected — 0056 parks these on panel
id 0)"*. During rehearsal both retired rows were reported exactly that way while their
panel users were alive and answering (ids 3 and 5).

Had the live rows resolved and only a retired row blipped, the run would have exited 0,
0056 would have parked a live panel user's row on the sentinel, and the `user_remna_id`
drop would have destroyed the only copy of the mapping — unrecoverable, not merely wrong.
`missing` (the panel answered) and `errored` (it did not) are now separate, and anything
unchecked fails the step.

### D-4 · Medium · A Windows checkout builds a broken image *(fixed)*

With `core.autocrlf=true` and no `.gitattributes`, both `git archive` and a plain
`docker build` ship `#!/bin/sh\r`, and the container crash-loops on:

```
exec ./docker-entrypoint.sh: no such file or directory
```

The file is present and executable; the `\r` is what cannot be resolved as an
interpreter, and the message names the script instead. → `.gitattributes` pinning
`*.sh text eol=lf`.

### D-5 · Medium · Panel upgrade prerequisites are undocumented *(runbook only)*

`APP_SECRET` is required by 3.x, absent from 2.8, and its correct value is the
counter-intuitive one (§0/§3). Missing → boot loop that presents as a healthy-looking
container. Wrong → healthy panel, every API token 401, no explanatory panel log.

### D-6 · Low · `docker compose run` cannot be used for out-of-band steps *(runbook only)*

The app service's pinned `ipv4_address` makes it fail with `Address already in use` while
the bot holds it. Use `docker run --network remnawave-network`. Corrected in the script's
usage block, which previously prescribed the compose form.

### D-7 · Low · Update checker mangles version tags *(not fixed — out of scope)*

`src/infrastructure/taskiq/tasks/update.py` normalises both local and remote tags with
`.replace("v", "")`, stripping every `v` rather than a leading prefix: a build tagged
`cutover-test` logs as `cutoer-test`. Harmless for current tags (no interior `v`), wrong
for anything like `v1.0.0-preview`. Unrelated to the cutover; filed separately.

---

## 9. What the rehearsal did *not* cover

Stated plainly so nobody reads this as broader assurance than it is.

- **`referrer_ref` remap.** The lab had 0 `referral_attributed` events carrying the key,
  so that half of 0056's remap ran against nothing (`0 referrer_ref(s)`). The `user_ref`
  half ran over 82 rows and was verified row-by-row.
- **`events` remap duration.** 207 rows / 192 kB. Measure prod separately (§4).
- **A real payment.** Only `TELEGRAM_STARS` is enabled on the lab and it needs a genuine
  Telegram payment. Trial activation, plan change with proration, renewal and status
  toggle were all driven against the live 3.x panel; the paid `PurchaseSubscription`
  entry point was not. Referral **attach** is verified; referral **commission** accrues
  on payment and so is untested.
- **Traffic pools.** Left off (`TRAFFIC_POOLS_ENABLED` unset), per instruction. 0058
  created its tables; nothing exercised them.
- **A token that actually needed reissuing.** Both lab tokens are `{*}`. The scope rename
  was proven by minting tokens with each scope; the dashboard reissue flow was not walked.
- **Support bridge.** `SUPPORT_ENABLED` is not set on the lab.

---

## 10. What was exercised, and passed

Against the live 3.2.1 panel, after the cutover:

- **Sentinel delete regression** — the highest-value test here, and it does not occur
  naturally on this data, so it was constructed. A subscription parked on `user_remna_id
  = 0` deletes cleanly (`panel users removed: 0/0`); a subscription on a real id deletes
  and removes the panel user (`1/1`). Confirmed `GET/DELETE /api/users/0` really does
  return 400 `Too small`, so without the `!= NO_PANEL_USER` filter the first case would
  have raised `UserDeletionPanelError` and refused to delete.
- **Influencer promocodes** — reward applies and the referral attaches to the owner; a
  redeemer who already has an inviter keeps it (`Referral skipped: user '13' already
  referred`); self-referral is refused (`Referral skipped: self-referral by user '11'`);
  the owner's summary shows `invited=1`; deleting the owner leaves the code alive and
  ownerless (`owner_user_id` NULL, `is_active` true) and the dashboard label renders
  `—`; account merge moves an owned code to the survivor.
- **User journey** — trial activation creating panel user id 10, subscription link,
  device list/reset, plan change Trial→Pro with proration, renewal +30d, disable/enable.
  Local and panel expiry agreed at every step.
- **Webhooks** — `user.created`, `user.modified`, `user.traffic_reset`, `user.disabled`,
  `user.enabled`, `user.deleted` all delivered with numeric `"id"` payloads and handled.
  Zero `Unhandled user event`.
- **Web cabinet** — `/api/v1/public/subscription/current` returns the numeric
  `user_remna_id`; `/subscription/devices` returns the device list; 401 without a cookie
  and on a bad signature.
- **Logs** — zero tracebacks and zero `ERROR` lines across app, worker and scheduler for
  the whole run. Every `WARNING` is accounted for: four literal-label translation
  fallbacks and an inline-mode notice (both pre-existing), two "local user not found"
  lines caused by this rehearsal's own cleanup deletes, and D-7.
