# Support SSE stream — edge nginx tuning (prod)

The cabinet support chat now receives operator replies over a **server-sent-events**
stream instead of a 4-second history poll:

```
GET /api/v1/public/support/stream        (text/event-stream, one long-lived request per open chat)
```

This request is long-lived and must **not** be buffered by the front (edge) nginx that
terminates TLS and proxies `/api/v1/(public|connect)` to the app. That config lives on
the edge VPS (not in this repo), so the directives below must be added there by hand.

Cloudflare has been dropped, so there is no CDN buffering to worry about — the edge
nginx is the only hop that can buffer or time out the stream.

## What the app already does

The stream response carries `X-Accel-Buffering: no` and `Cache-Control: no-cache`, and
emits a heartbeat comment (`: keep-alive`) every ~20 s. So even the default 60 s
`proxy_read_timeout` would not fire (data arrives every 20 s). The block below is still
required to guarantee **unbuffered** delivery and to survive slow/idle periods robustly.

## Abuse / DoS caps (defense in depth)

The app already caps SSE abuse per **account** (a valid login is required): a per-user
open-rate limit, a per-user concurrent-stream cap (~5), and a process-wide semaphore,
with the pub/sub connections drawn from a pool separate from the shared one so a breach
can't starve the rate limiter or the operator fan-out. The nginx directives below add a
per-**IP** layer that sheds a flood at the edge — including unauthenticated hammering
that would otherwise reach the app just to get a 401 — before it ever hits the app. Keep
both: they defend different keys (IP at the edge, account in the app).

Add the two shared zones **once**, at `http { … }` level (next to your other
`limit_*_zone` directives). Cloudflare was dropped, so `$binary_remote_addr` is the real
client IP at this edge:

```nginx
# --- Support SSE stream: per-IP abuse zones -------------------------------------
limit_conn_zone $binary_remote_addr zone=support_sse_conn:10m;
limit_req_zone  $binary_remote_addr zone=support_sse_req:10m rate=30r/m;
```

## Add this to the edge nginx `server { … }` for tuna-vpn.com

Place it **before** the generic `location /api/v1/ { … }` block so it wins for this
exact path. Copy your existing `/api/v1/` block's `proxy_pass` target and forwarded
headers; only the SSE-specific directives at the bottom are new.

**The `proxy_pass` target MUST equal your existing `/api/v1/(public|connect)` block** — in
this deployment the app is the Docker service `remnashop:5000` (NOT `127.0.0.1:8000`).
Copy the exact upstream from that block; using the wrong one gives `502 Bad Gateway`
(`connect() failed (111: Connection refused)`).

```nginx
# --- Support SSE stream: unbuffered, long-lived ---------------------------------
location = /api/v1/public/support/stream {
    # Mirror your working /api/v1/(public|connect) block's upstream EXACTLY. Here that
    # is the Docker service `remnashop:5000`, resolved at request time via Docker's
    # embedded DNS (the server-level `resolver 127.0.0.11;` + a variable, so nginx
    # doesn't fail to start if the container is momentarily down).
    set $app remnashop;
    proxy_pass http://$app:5000;

    # Forwarded headers — mirror your existing /api/v1/ block.
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # SSE essentials:
    proxy_http_version 1.1;                # HTTP/1.1 upstream (streaming)
    proxy_set_header Connection "";        # keep upstream conn alive; don't send "close"
    proxy_buffering    off;                # push each frame straight through (no batching)
    proxy_cache        off;
    gzip               off;                # gzip buffers text/event-stream — disable it
    chunked_transfer_encoding on;
    proxy_read_timeout  3600s;             # allow long idle streams (heartbeat is ~20s)
    proxy_send_timeout  3600s;

    # Per-IP abuse caps (zones defined at http{} above). These complement the app's
    # per-account caps — a single IP can't hold many streams open or reopen them in a
    # tight loop, and 429 (not the default 503) matches what the SPA already handles.
    limit_conn support_sse_conn 5;                 # ≤5 concurrent streams per client IP
    limit_req  zone=support_sse_req burst=10 nodelay; # ≤30 opens/min, small burst
    limit_conn_status 429;
    limit_req_status  429;
}
```

`location =` (exact match) already outranks the `~ ^/api/v1/(public|connect)/` regex
block, so ordering doesn't matter. Reload nginx — for the Dockerised edge here:
`docker exec remnawave-nginx nginx -t && docker exec remnawave-nginx nginx -s reload`
(bare-metal: `nginx -t && systemctl reload nginx`).

## Troubleshooting (the chat stays on "обновляем…" = polling fallback)
- **`502 Bad Gateway` on `/support/stream`** → wrong `proxy_pass` upstream. It must be
  the same service:port as your `/api/v1/` block (`remnashop:5000` here), not the
  `127.0.0.1:8000` placeholder.
- **`404 Not Found`** → the app container is running an image without the stream route
  (added 2026-07-14). Rebuild/redeploy `remnashop` from `main`.
- **200 but the client still polls** → buffering/timeout still on: confirm the reload
  applied and no outer block re-enables `proxy_buffering`.
- **`429 Too Many Requests` on `/support/stream`** → an abuse cap tripped (per-IP nginx
  `limit_conn`/`limit_req`, or the app's per-account open-rate / concurrent-stream cap).
  Expected under abuse; the SPA falls back to polling. If a legitimate user hits it,
  raise the nginx `limit_conn`/`rate` here and/or the app constants in
  `src/web/endpoints/public/support.py` (`_MAX_STREAMS_PER_USER`, `_STREAM_OPEN_RATE_LIMIT`).

## Verifying on prod

```bash
# Should stream (stays open), NOT return all-at-once. Expect an immediate ": keep-alive"
# comment within ~20s if idle, and headers with no Content-Length + X-Accel-Buffering: no.
curl -N -H 'Cookie: access_token=<valid>' https://tuna-vpn.com/api/v1/public/support/stream
```

If `curl -N` blocks and then dumps everything only when the connection closes, buffering
is still on — re-check `proxy_buffering off` and that no outer `location` re-enables it.

## Rollback

Fully additive and safe to revert: remove this `location` block (the app keeps
`X-Accel-Buffering: no` + heartbeat, and the site falls back to the history poll if the
stream ever errors). No app redeploy needed to roll back the nginx side.
```
