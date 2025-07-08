
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': ' '.join([
                '%(asctime)s',
                '%(levelname)s',
                '%(module)s',
                '%(process)d',
                '%(thread)d',
                '%(message)s'
            ])
        },
        'simple': {
            'format': '%(asctime)s %(levelname)s %(message)s'
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
            'formatter': 'verbose'
        },
        'sentry_dogslow': {
            'level': 'WARNING',
            'class': 'raven.contrib.django.handlers.SentryHandler',
        }
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'propagate': True,
            'level': 'INFO',
        },
        'dogslow': {
            'level': 'WARNING',
            'handlers': ['sentry_dogslow'],
            'propagate': True
        }
    },
}