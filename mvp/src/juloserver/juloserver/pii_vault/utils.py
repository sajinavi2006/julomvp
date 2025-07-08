from juloserver.julocore.cache_client import get_redis_cache


class CacheUtils:
    class CacheKeyConfig:
        key_value = {
            'key_converter': lambda *args: 'key_value_{}'.format(args[0]),
            'timeout': 300,
        }
        primary = {'key_converter': lambda *args: 'primary_{}'.format(args[0]), 'timeout': 300}

    def __init__(self, cache_client=None):
        self.cache = cache_client or get_redis_cache()
        self.config = {}
        self._get_config()

    def _get_config(self):
        from juloserver.julo.models import FeatureSetting
        from juloserver.julo.constants import FeatureNameConst

        if not self.config:
            fs = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_DETOKENIZATION, is_active=True
            ).last()

            if fs:
                self.config = fs.parameters

    def cache_data(self, key_conf):
        def _cache_data(func):
            def _func(*args, **kwargs):
                if not self.config.get('cache_data'):
                    return func(*args, **kwargs)

                cache_key = key_conf['key_converter'](*args)
                data = self.get(cache_key)
                force_query = kwargs.pop("force_query", False)
                if force_query or data is None:
                    data = func(*args, **kwargs)
                    self.set(cache_key, data, key_conf['timeout'])

                return data

            return _func

        return _cache_data

    def set(self, value, key_conf, *args):
        if not self.config.get('cache_data'):
            return None
        self.cache.set(key_conf['key_converter'](*args), value, timeout=key_conf['timeout'])

    def get(self, key_conf, *args):
        if not self.config.get('cache_data'):
            return None
        return self.cache.get(key_conf['key_converter'](*args))

    def delete(self, key_conf, *args):
        self.cache.delete(key_conf['key_converter'](*args))
