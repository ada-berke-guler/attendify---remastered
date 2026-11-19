from __future__ import annotations

import ipaddress

from fastapi import Request

from app.core.config import settings

# Where our own proxies (Caddy, cloudflared, Docker networks) live.
PROXY_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7", "fe80::/10")
)


def _is_proxy_hop(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return True  # garbage: skip it
    return any(ip in net for net in PROXY_NETWORKS)


def client_ip(request: Request) -> str:
    """Best-effort client IP.

    Behind Caddy (and optionally cloudflared) the socket peer is a proxy on a private
    network. Walk X-Forwarded-For from the right and return the first address outside our proxy networks,
    so a client cannot pick another bucket by prepending fake entries.
    """
    peer = request.client.host if request.client else "unknown"
    if not settings.TRUST_PROXY_HEADERS:
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _is_proxy_hop(hop):
            return hop
    return hops[0] if hops else peer


def public_base_url(request: Request) -> str:
    """Origin to put in QR links.

    PUBLIC_URL wins when set. Otherwise use the origin the instructor reached us on, so a
    cloudflared tunnel URL works without editing .env.
    """
    if settings.PUBLIC_URL:
        return settings.PUBLIC_URL.rstrip("/")
    proto = request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    if settings.TRUST_PROXY_HEADERS:
        proto = request.headers.get("x-forwarded-proto", proto).split(",")[0].strip()
        host = request.headers.get("x-forwarded-host", host).split(",")[0].strip()
    return f"{proto}://{host}"
