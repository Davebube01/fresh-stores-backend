import hashlib
import json

from cachetools import TTLCache

# In-memory, per-process caches for read-heavy, rarely-changing catalog data
# (product/category listings hit the DB on every request otherwise). Same
# trade-off as app/core/limiter.py: fine for a single-process deployment, but
# if this app ever runs multiple worker processes/instances behind a load
# balancer, back these with Redis instead so entries and invalidations are
# shared across processes.
#
# Separate cache instances per resource so one can be cleared without
# touching the others, and so each can carry its own TTL.
product_list_cache: TTLCache = TTLCache(maxsize=256, ttl=60)
product_detail_cache: TTLCache = TTLCache(maxsize=1024, ttl=60)
category_cache: TTLCache = TTLCache(maxsize=32, ttl=300)


def make_cache_key(*parts) -> str:
    """Build a stable cache key from arbitrary JSON-serializable parts."""
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clear_product_caches() -> None:
    """Call after any admin write to products so changes are visible immediately."""
    product_list_cache.clear()
    product_detail_cache.clear()


def clear_category_cache() -> None:
    """Call after any admin write to categories so changes are visible immediately."""
    category_cache.clear()
    # Product detail responses embed the category's name.
    product_detail_cache.clear()
