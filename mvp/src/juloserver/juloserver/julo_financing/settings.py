DEFAULT_CACHEOPS_TIMEOUT_SECONDS = 60 * 60

# cache SMALL TABLES that don't change often
JFINANCING_CACHEOPS = {
    'julo_financing.JFinancingCategory': {
        'ops': 'all',
        'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS,
    },
    'julo_financing.JFinancingProduct': {'ops': 'all', 'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS},
    'julo_financing.JFinancingProductSaleTag': {
        'ops': 'all',
        'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS,
    },
    'julo_financing.JFinancingProductSaleTagDetail': {
        'ops': 'all',
        'timeout': DEFAULT_CACHEOPS_TIMEOUT_SECONDS,
    },
}
