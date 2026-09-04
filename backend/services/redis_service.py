import json
import logging
import redis
from backend.config import DEFAULT_REDIS_URL, settings

logger = logging.getLogger(__name__)

# The `or` is load-bearing. A default in config.py covers an unset variable,
# but not one that is declared and left blank -- which is exactly what a
# render.yaml `sync: false` entry produces when nobody fills it in. from_url
# rejects "" outright ("Redis URL must specify one of the following
# schemes"), and this line runs at import, so that took the whole API down
# at startup rather than degrading to uncached.
redis_client = redis.from_url(
    settings.REDIS_URL or DEFAULT_REDIS_URL,
    decode_responses=True,
)

def ping_redis():
    return redis_client.ping()

def cache_set(key: str, value: dict, ttl: int = 300) -> bool:
    """
    Store a dict in Redis as JSON
    ttl = time to live in seconds (default 5 minutes)
    """
    try:
        redis_client.setex(
            name = key,
            time = ttl,
            value = json.dumps(value)
        )
        logger.info(f"[REDIS] Cached: {key} (ttl={ttl}s)")
        return True
    except Exception as e:
        logger.error(f"[REDIS] Cache set failed: {e}")
        return False
    
def cache_get(key: str) -> dict | None:
    """
    Retrieve a cached dict from Redis.
    Returns None if key not found or expired.
    """
    try:
        value = redis_client.get(key)
        if value:
            logger.info(f"[REDIS] Cache hit: {key}")
            return json.loads(value)
        logger.info(f"[REDIS] Cache miss: {key}")
        return None
    except Exception as e:
        logger.error(f"[REDIS] Cache get failed: {e}")
        return None
    
def cache_delete(key: str) -> bool:
    """Delete a key from Redis cache."""
    try:
        redis_client.delete(key)
        return True
    except Exception as e:
        logger.error(f"[REDIS] Cache delete failed: {e}")
        return False
    
def make_cache_key(prefix: str, query: str) -> str:
    """
    Generate a consistent cache key from prefix + query.
    Example: make_cache_key("market", "AAPL,MSFT")
             -> "market:AAPL,MSFT"
    """
    clean = query.strip().upper().replace(" ","_")
    return f"{prefix}:{clean}"