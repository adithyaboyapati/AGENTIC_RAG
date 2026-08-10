"""Optional Redis-backed response caching."""

from src.cache.redis_cache import (
    build_cache_key,
    flush_answer_cache,
    get_cached_response,
    get_redis_client,
    normalize_question,
    set_cached_response,
    should_use_cache,
)

__all__ = [
    "build_cache_key",
    "flush_answer_cache",
    "get_cached_response",
    "get_redis_client",
    "normalize_question",
    "set_cached_response",
    "should_use_cache",
]
