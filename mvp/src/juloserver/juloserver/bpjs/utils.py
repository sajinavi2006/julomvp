import logging

from juloserver.bpjs.exceptions import BrickBpjsException
from juloserver.julo.clients import get_julo_sentry_client

sentry = get_julo_sentry_client()
logger = logging.getLogger(__name__)


@sentry.capture_exceptions
def get_http_referrer(request):
    """
    For generate http for logging Brick request.
    """
    try:
        if request.get_host() is None:
            error_message = "Error get host in http_referer."
            raise BrickBpjsException(error_message)

        http_referer = "{0}://{1}{2}".format(request.scheme, request.get_host(), request.path)

        return http_referer

    except Exception as error:
        error_message = str(error)
        logger.error(
            {
                "message": error_message,
                "method": str(__name__),
                "action": "Generate HTTP Referer.",
            }
        )
        raise BrickBpjsException(error_message)
