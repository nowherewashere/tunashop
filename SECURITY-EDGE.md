# Edge trust model

How the application decides who a request came from, and what has to stay true for
that answer to mean anything. Written down because the previous version of this
contract lived only as an assumption in a comment — when Cloudflare was dropped, the
assumption went stale, nothing failed loudly, and every IP-keyed control quietly
became bypassable.

## The rule

**The application trusts a forwarding header only when the request reached it through
a proxy listed in `APP_TRUSTED_PROXY_CIDRS`.** Everything else is client input.

Deployed topology: `client → nginx container (TLS) → remnashop:5000`, both on the
`remnawave-network` Docker bridge. Exactly one trusted hop. The app never sees the
client's socket — `request.client.host` is the nginx container's address on that
network — so the client address has to come from `X-Forwarded-For`.

Resolution lives in `src/core/utils/net.py` (`resolve_client_ip`) and works outward:
hops are consumed from the **right** while they fall inside a trusted network, and the
first address outside them is the client. The leftmost hop is whatever the caller sent
and is never authoritative.

Two settings govern it:

| Setting | Default | Meaning |
| --- | --- | --- |
| `APP_TRUSTED_PROXY_CIDRS` | loopback + RFC1918 | Which hops count as "our infrastructure" |
| `APP_TRUST_CF_CONNECTING_IP` | `false` | Whether `CF-Connecting-IP` may be believed |

`CF-Connecting-IP` is ignored by default. With no Cloudflare in front nothing strips
it, so a client can set it freely — which is exactly how the old code was exploitable.

## The edge must hold up its end

`deploy/nginx/nginx.conf` mirrors the deployed `/opt/remnawave/nginx/nginx.conf`. Two
directives are load-bearing:

```nginx
proxy_set_header CF-Connecting-IP "";          # drop whatever the client sent
proxy_set_header X-Forwarded-For  $remote_addr; # overwrite, don't append
```

Emptying a header makes nginx omit it. Overwriting `X-Forwarded-For` (rather than
`$proxy_add_x_forwarded_for`) means exactly one hop — the address nginx actually saw —
reaches the app.

## What depends on this

- Per-IP rate limits on passwordless code requests (`otp_ip`) and on the funnel
  endpoint (`funnel_metrics`).
- Payment-gateway source allowlists (`NETWORKS` in `src/infrastructure/payment_gateways/`).
  Defence in depth only — the per-gateway signature check is the real gate.

None of these fail loudly when attribution is wrong; they just stop limiting. That is
why the caps that do **not** depend on IP matter:

- **Turnstile** on code requests — the only IP-independent gate on that path.
- `EMAIL_CODE_MAX_GLOBAL` — ceiling across all callers, so a spray across many
  addresses is bounded even if per-IP attribution fails.
- `_FUNNEL_GLOBAL_RATE_LIMIT` in `src/web/endpoints/public/events.py` — same idea for
  the unauthenticated endpoint that writes a row per accepted call.

## Adding a CDN in front

Both sides change together, or the CDN's edge becomes "the client" for every rate limit:

1. Add the CDN's egress ranges to `APP_TRUSTED_PROXY_CIDRS`.
2. Switch nginx to `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` so
   the CDN's view of the client survives.
3. Firewall 80/443 on the origin to the CDN's ranges — otherwise attackers simply
   address the origin directly and the CDN protects nothing.

## Known gap: Platega

Platega authenticates webhooks with a static `X-Secret` header rather than a signature
over the body (`src/infrastructure/payment_gateways/platega.py`). No body integrity, no
replay binding: anyone holding that secret can forge any payment. Keep the secret out
of logs and rotate it if there is any doubt.

It also publishes no source ranges, which is why `/api/v1/payments/` carries a rate
limit but **no** allow/deny list: a blanket allowlist there would reject every real
Platega callback. Only `/api/v1/telegram` is allowlisted, where the ranges are
documented and stable.

## Out of scope

This layer bounds cheap L7 floods and junk traffic. It cannot absorb a volumetric
L3/L4 attack — once the pipe is full nothing on the host helps. That needs a CDN or
scrubbing provider in front, with the origin firewalled to its ranges.
