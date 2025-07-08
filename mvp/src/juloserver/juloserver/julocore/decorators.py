import logging
from functools import wraps

from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)


def silent_exception(f):
    """decorator to silent exception and push it to sentry"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.exception('Exception in %s', f.__name__)

    return wrapper
