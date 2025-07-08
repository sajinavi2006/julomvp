import hashlib
import secrets
from google.oauth2 import id_token
from google.auth.transport import requests
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.utils import timezone
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.pin.models import RegisterAttemptLog

sentry_client = get_julo_sentry_client()
logger = JuloLog(__name__)


def generate_email_verify_token(email):
    code = secrets.token_urlsafe(16)
    token = hashlib.sha256((hashlib.sha1(code.encode()).hexdigest() + email).encode()).hexdigest()
    return code, token


def verify_email_token(email, token):
    attempt_log = RegisterAttemptLog.objects.filter(email=email).last()
    if not attempt_log or not attempt_log.is_email_validated:
        return False
    time_now = timezone.localtime(timezone.now())
    last_three_hours = time_now - relativedelta(hours=3)
    if attempt_log.cdate < last_three_hours:
        return False

    return (
        token
        == hashlib.sha256(
            (hashlib.sha1(attempt_log.email_validation_code.encode()).hexdigest() + email).encode()
        ).hexdigest()
    )


def verify_google_access_token(access_token: str, email: str, is_ios_device=False):
    from juloserver.registration_flow.services.v1 import is_mock_google_auth_api

    # check email is registered in whitelist feature setting or not for internal testing
    if is_mock_google_auth_api(email):
        return True, email

    if not access_token:
        logger.warning('verify_google_access_token_empty_token|email={}'.format(email))
        return False, email

    try:

        # Default for Android Device
        google_auth_client_id = settings.GOOGLE_AUTH_CLIENT_ID
        if is_ios_device:
            google_auth_client_id = settings.GOOGLE_AUTH_CLIENT_ID_IOS
            logger.info(
                {
                    'message': 'google_auth_client_id for IOS is active',
                    'email': email,
                }
            )

        # Specify the GOOGLE_AUTH_CLIENT_ID of the app that accesses the backend:
        id_info = id_token.verify_oauth2_token(
            access_token, requests.Request(), google_auth_client_id
        )

        valid_email = id_info.get('email', '')
        if email != valid_email.strip().lower():
            logger.warning(
                {
                    'message': 'verify_google_auth_client_email is not match',
                    'email_payload': email,
                    'valid_email': valid_email,
                }
            )

            return False, valid_email

        return True, email
    except Exception as err:
        sentry_client.captureException()
        logger.warning('verify_google_auth_error|email={}, err={}'.format(email, err))
        return False, email
