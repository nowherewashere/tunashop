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

## Add this to the edge nginx `server { … }` for tuna-vpn.com

Place it **before** the generic `location /api/v1/ { … }` block so it wins for this
exact path. Copy your existing `/api/v1/` block's `proxy_pass` target and forwarded
headers; only the SSE-specific directives at the bottom are new.

```nginx
# --- Support SSE stream: unbuffered, long-lived ---------------------------------
location = /api/v1/public/support/stream {
    proxy_pass http://127.0.0.1:8000;      # <-- SAME upstream as your /api/v1/ block

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
}
```

Reload nginx: `nginx -t && systemctl reload nginx`.

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
