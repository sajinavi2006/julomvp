from juloserver.api_token.authentication import generate_new_token_and_refresh_token
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.api_token.authentication import is_expired_token
from juloserver.api_token.models import ExpiryToken
from typing import Union

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


def generate_and_convert_auth_key_data(expiry_token: ExpiryToken, app_version: Union[str, None]) \
        -> dict:
    expiry_token_obj = ExpiryToken.objects.get(key=expiry_token)
    # To Ensure 'token_expires_in' does not return null for higher appversion.
    expiry_token_obj.is_active = True
    key, refresh_token = generate_new_token_and_refresh_token(expiry_token_obj.user)
    expiry_token_obj.refresh_from_db()
    is_expired, _expire_on = is_expired_token(expiry_token_obj, app_version)
    auth_data = {
        "token": key,
        "refresh_token": refresh_token,
        "token_expires_in": _expire_on
    }
    return auth_data
