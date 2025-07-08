from django.core.cache import cache, caches


def get_token_cache():
    """use file caching"""
    return caches['token']


def get_redis_cache():
    return caches['redis']


def get_loc_mem_cache():
    """
    Get local memory cache
    """
    return caches['loc_mem']


def get_default_cache():
    """use memory caching"""
    return cache
