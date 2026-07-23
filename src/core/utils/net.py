"""Recovery of the real client IP from behind our own reverse proxy.

The application never observes the client's socket: nginx terminates TLS on the
host and Docker NATs the connection onward, so ``request.client.host`` is always
the bridge gateway. The client address therefore has to be read out of
``X-Forwarded-For`` — but that header is attacker-controlled, because whatever a
client sends is *preserved* and merely appended to by nginx
(``$proxy_add_x_forwarded_for``). Trusting the leftmost hop, as the previous
implementation did, means trusting client input.

Only the hops our own infrastructure appended can be vouched for, which is what
``resolve_client_ip`` implements: entries are consumed from the right while they
fall inside a trusted network, and the first address outside those networks is
the furthest hop still attributable to a proxy we control.

Everything IP-keyed downstream (rate limits, payment-gateway source checks) reads
this, so a wrong answer here silently disables those controls rather than failing
loudly — hence the conservative rules: headers are ignored entirely unless the
direct peer is itself a trusted proxy, and a malformed hop aborts the walk.
"""

from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import Iterable, Optional, Union

# Value accepted for CIDR collections: pydantic hands over a real list once the
# env var is set, but an unvalidated default (validate_default is off) can still
# arrive as the raw comma-separated string.
CidrSource = Union[str, Iterable[str]]

UNKNOWN_IP = "unknown"

# Named here so the web layer and the payment gateways read the same headers; this
# module stays framework-free, so each layer keeps its own thin adapter.
FORWARDED_FOR_HEADER = "x-forwarded-for"
CF_CONNECTING_IP_HEADER = "cf-connecting-ip"


def _normalize_cidrs(cidrs: CidrSource) -> tuple[str, ...]:
    if isinstance(cidrs, str):
        cidrs = cidrs.split(",")
    return tuple(item.strip() for item in cidrs if item and item.strip())


@lru_cache(maxsize=16)
def _parse_networks(cidrs: tuple[str, ...]) -> tuple[Union[IPv4Network, IPv6Network], ...]:
    """Parse once per distinct config tuple — this runs on every request."""
    networks: list[Union[IPv4Network, IPv6Network]] = []
    for cidr in cidrs:
        try:
            networks.append(ip_network(cidr, strict=False))
        except ValueError:
            # A typo in config must not widen trust: skip the entry silently and
            # let the remaining networks decide.
            continue
    return tuple(networks)


def _is_ip(value: str) -> bool:
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def is_ip_in_networks(ip: str, cidrs: CidrSource) -> bool:
    """True when ``ip`` falls inside any of ``cidrs``. Never raises."""
    try:
        address = ip_address(ip.strip())
    except ValueError:
        return False
    # Mismatched address families compare False rather than raising, so a mixed
    # v4/v6 list needs no special casing.
    return any(address in network for network in _parse_networks(_normalize_cidrs(cidrs)))


def resolve_client_ip(
    *,
    peer_ip: Optional[str],
    forwarded_for: Optional[str],
    trusted_proxy_cidrs: CidrSource,
    proxy_header_ip: Optional[str] = None,
    trust_proxy_header: bool = False,
) -> str:
    """Return the client address, or ``UNKNOWN_IP`` when nothing can be attributed.

    ``proxy_header_ip`` (CF-Connecting-IP) is only consulted when
    ``trust_proxy_header`` is set, because nothing strips it when Cloudflare is
    not actually in front — a client could otherwise dictate its own address.
    """
    trusted = _normalize_cidrs(trusted_proxy_cidrs)

    # Forwarding headers mean nothing unless the request genuinely reached us
    # through a proxy we control; on a direct connection the peer is the client.
    if not peer_ip or not is_ip_in_networks(peer_ip, trusted):
        return peer_ip or UNKNOWN_IP

    if trust_proxy_header and proxy_header_ip:
        candidate = proxy_header_ip.strip()
        if _is_ip(candidate):
            return candidate

    for hop in reversed((forwarded_for or "").split(",")):
        candidate = hop.strip()
        if not candidate:
            continue
        if not _is_ip(candidate):
            # Chain integrity is broken; anything further left is unattributable.
            break
        if is_ip_in_networks(candidate, trusted):
            # One of our own proxies — keep walking outward.
            continue
        return candidate

    # Every hop belonged to our infrastructure (or the header was absent): the
    # nearest thing we can attribute is the proxy itself.
    return peer_ip
