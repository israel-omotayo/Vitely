import logging
from django.core.cache import cache

#create a logger for this file
logger = logging.getLogger(__name__)

# RateLimitError is raised when the rate limit is exceeded
class RateLimitError(Exception):
    pass


# Atomic rate limiter using Django's cache backend.
#atomic means safe even if many requests happen at the same time
def check_ratelimit(key_prefix: str, limit: int = 5, period: int = 60) -> bool:
    """
    Atomic rate limiter using Django's cache backend.

        Uses two atomic primitives:
        cache.add()   — SET key=1 only if it does NOT already exist (atomic)
        cache.incr()  — atomically increment and return the new value

    Under concurrent load both threads call cache.add(). Exactly one wins
    (Redis SETNX is atomic). The loser proceeds to incr(), which returns the
    correct count with no gap.

    RateLimitError is intentionally NOT caught here — callers must handle it.
    Only genuine cache backend failures are caught and logged.
    """
    #the key is namespaced with "ratelimit:" to avoid collisions with other cache keys
    key = f"ratelimit:{key_prefix}"

    try:
        # Try to initialise the key. Returns True only if key didn't exist.
        # If True, this is the first request in the window — always allow it.
        #cache.add Set this key to 1 only if it does not already exist.
        added = cache.add(key, 1, timeout=period)
        if added:
            return True

        # Key already existed — atomically increment and check the count.
        count = cache.incr(key)

        # If count exceeds the limit, raise a RateLimitError. The key will expire
        if count > limit:
            raise RateLimitError("Too many attempts. Please try again later.")

        return True

    # We only want to catch exceptions from the cache backend, not our own RateLimitError.
    except RateLimitError:
        raise

    except Exception as e:
        # Only real cache backend failures land here (Redis down, timeout, etc.)
        logger.error("Cache backend error in rate limiter (key=%s): %s", key, e)
        # Fail open: better to let a request through than to lock everyone out
        # because Redis is temporarily unreachable.
        return True