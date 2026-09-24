"""
Per-account abuse protection that the per-IP slowapi limits can't give:
escalating lockouts after repeated failed logins, and small "N per window"
counters (e.g. resending a verification email).

State is in-process memory (like the slowapi limiter): correct for one
instance, but each worker/instance would count separately. If the API is ever
scaled out, move this to Redis.
"""
from __future__ import annotations

import time
from cachetools import TTLCache
from fastapi import HTTPException, Request
from slowapi.util import get_remote_address

# Entries expire after 15 idle minutes, which is also when a failure streak
# is forgotten.
_failures: TTLCache = TTLCache(maxsize=50_000, ttl=900)
_hits: TTLCache = TTLCache(maxsize=50_000, ttl=3600)

# (failures before locking, first lock seconds, max lock seconds)
_PER_ACCOUNT_AND_IP = (5, 60, 900)
# Backstop against guessing spread over many IPs. Deliberately high so one
# attacker can't easily lock a real customer out of their own account.
_PER_ACCOUNT = (20, 300, 900)


def _lock_seconds_left(key: str) -> int:
    entry = _failures.get(key)
    if not entry:
        return 0
    return max(0, int(entry["locked_until"] - time.time()) + 1) if entry["locked_until"] > time.time() else 0


def _keys(request: Request, realm: str, email: str) -> list[tuple[str, tuple[int, int, int]]]:
    ip = get_remote_address(request)
    return [
        (f"{realm}:{email}:{ip}", _PER_ACCOUNT_AND_IP),
        (f"{realm}:{email}", _PER_ACCOUNT),
    ]


def enforce_login_allowed(request: Request, realm: str, email: str) -> None:
    """Raises 429 if this account (or this account from this IP) is locked out."""
    wait = max((_lock_seconds_left(k) for k, _ in _keys(request, realm, email)), default=0)
    if wait > 0:
        minutes = max(1, (wait + 59) // 60)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
            headers={"Retry-After": str(wait)},
        )


def record_login_failure(request: Request, realm: str, email: str) -> None:
    now = time.time()
    for key, (threshold, base, cap) in _keys(request, realm, email):
        entry = _failures.get(key) or {"count": 0, "locked_until": 0.0}
        entry["count"] += 1
        if entry["count"] >= threshold:
            entry["locked_until"] = now + min(base * 2 ** (entry["count"] - threshold), cap)
        _failures[key] = entry


def record_login_success(request: Request, realm: str, email: str) -> None:
    # Only the (account, IP) streak is cleared: the account-wide counter is a
    # backstop against distributed guessing, so a lucky success from one IP
    # shouldn't reset it.
    _failures.pop(_keys(request, realm, email)[0][0], None)


def hit_limit(key: str, limit: int, window_seconds: int) -> bool:
    """Records one event; returns False (and doesn't record) if `limit` events already happened in the window."""
    now = time.time()
    recent = [t for t in _hits.get(key, []) if now - t < window_seconds]
    if len(recent) >= limit:
        _hits[key] = recent
        return False
    recent.append(now)
    _hits[key] = recent
    return True
