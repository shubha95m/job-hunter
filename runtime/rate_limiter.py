"""
Async Token-Bucket Rate Limiter with Jitter.
Protects user accounts from platform rate limits and bot-detection blocks.
"""

import asyncio
import random
import time
from typing import Dict


class TokenBucketRateLimiter:
    """
    Thread-safe async token bucket rate limiter.
    Allows bursting up to `capacity`, refilling at `rate_per_sec`.
    """
    def __init__(self, rate_per_sec: float = 2.0, capacity: float = 5.0, jitter_range: tuple = (0.1, 0.4)):
        self.rate = rate_per_sec
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()
        self.jitter_min, self.jitter_max = jitter_range

    async def acquire(self, tokens: float = 1.0):
        """Wait until enough tokens are available, then acquire."""
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens < tokens:
                needed = tokens - self.tokens
                wait_time = needed / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
                self.last_update = time.monotonic()
            else:
                self.tokens -= tokens

            # Add humanized jitter
            jitter = random.uniform(self.jitter_min, self.jitter_max)
            await asyncio.sleep(jitter)


# Pre-configured platform limiters
api_limiter = TokenBucketRateLimiter(rate_per_sec=3.0, capacity=8.0, jitter_range=(0.05, 0.2))
ui_action_limiter = TokenBucketRateLimiter(rate_per_sec=0.2, capacity=1.0, jitter_range=(1.0, 2.5))
