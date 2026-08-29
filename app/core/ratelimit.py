"""In-process token bucket rate limiter.
Governing spec: BE-14 §4.
"""

import time
from typing import Dict, Tuple
from app.core.errors import RateLimitedError


class TokenBucket:
    def __init__(self, capacity: int, refill_rate_per_sec: float):
        self.capacity = capacity
        self.refill_rate = refill_rate_per_sec
        self.tokens = float(capacity)
        self.last_update = time.monotonic()

    def consume(self, tokens: int = 1) -> Tuple[bool, int]:
        now = time.monotonic()
        elapsed = now - self.last_update
        self.last_update = now
        self.tokens = min(float(self.capacity), self.tokens + elapsed * self.refill_rate)

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True, 0
        else:
            needed = tokens - self.tokens
            retry_after = int(needed / self.refill_rate) + 1
            return False, retry_after


class RateLimiter:
    def __init__(self):
        self._buckets: Dict[str, TokenBucket] = {}

    def check_rate_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int,
        tokens: int = 1,
    ) -> None:
        """Check rate limit for a given key. Raises RateLimitedError on limit breach."""
        refill_rate = limit / window_seconds
        bucket_key = f"{key}:{window_seconds}"
        if bucket_key not in self._buckets:
            self._buckets[bucket_key] = TokenBucket(limit, refill_rate)

        bucket = self._buckets[bucket_key]
        allowed, retry_after = bucket.consume(tokens)
        if not allowed:
            raise RateLimitedError(retry_after=retry_after)


# Global rate limiter instance
limiter = RateLimiter()
