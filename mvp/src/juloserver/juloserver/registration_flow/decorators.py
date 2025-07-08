from functools import wraps

from juloserver.standardized_api_response.utils import (
    general_error_response,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.registration_flow.services.v1 import do_encrypt_or_decrypt_sync_register
from juloserver.pin.constants import RegistrationType


logger = JuloLog(__name__)


def decrypt_pin_parameter(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        pin_decrypted = request.data.get('pin', None)
        if not pin_decrypted:
            logger.error({'message': '[SyncRegistration] Pin parameter is empty'})
            return general_error_response('Invalid request')

        try:
            pin = do_encrypt_or_decrypt_sync_register(pin_decrypted, encrypt=False)
        except Exception as error:
            logger.error(
                {'message': '[SyncRegistration] Decrypt Failed: {}'.format(str(error))},
                request=request,
            )
            return general_error_response('Something problem in process registration')

        # replace previously value
        request.data['pin'] = pin
        request.data['registration_type'] = RegistrationType.PHONE_NUMBER

        return function(view, request, *args, **kwargs)

    return wrapper
