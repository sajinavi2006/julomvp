import logging
from datetime import timedelta
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.status import HTTP_401_UNAUTHORIZED
from django.core.exceptions import ObjectDoesNotExist

from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2
)
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    unauthorized_error_response,
)

from juloserver.api_token.authentication import (
    is_expired_token,
)
from juloserver.api_token.authentication import (
    RefreshTokenAuthentication,
    generate_new_token_and_refresh_token,
)
from juloserver.api_token.models import ExpiryToken

from juloserver.registration_flow.services.v5 import generate_and_convert_auth_key_data

from juloserver.julo.models import (
    Device,
    FeatureSetting,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.api_token.models import (
    ProductPickerLoggedOutNeverResolved,
    ProductPickerBypassedLoginUser,
)

logger = logging.getLogger(__name__)


class CheckExpireEarly(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        will_expired = False

        app_version = request.META.get('HTTP_X_APP_VERSION')
        is_expired, expire_on = is_expired_token(request.user.auth_expiry_token, app_version)
        if is_expired is False and expire_on:
            if expire_on < timedelta(minutes=30):
                will_expired = True

        return success_response({"will_expired": will_expired})


class RetrieveNewAccessToken(StandardizedExceptionHandlerMixinV2, APIView):
    """
    To implement a silent authentication feature to get a new user’s token
    if the token is invalid or expired .
    Refresh Token(long-lived token ), will be used to get a new user’s token.
    """
    permission_classes = []
    authentication_classes = [RefreshTokenAuthentication]
    exclude_raise_error_sentry_in_status_code = {HTTP_401_UNAUTHORIZED}

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {
            'header': ('HTTP_AUTHORIZATION',),
            'request': (('password',),),
        },
        'log_success_response': True,
    }

    def post(self, request: Request) -> Response:
        app_version = None
        app_version = request.META.get('HTTP_X_APP_VERSION')
        try:
            data = generate_and_convert_auth_key_data(self.request.auth, app_version)
        except ExpiryToken.DoesNotExist:
            logger.exception(
                'RetrieveNewAccessToken_expiry_token_doesnot_exist'
                '|auth={}'.format(self.request.auth)
            )
            return unauthorized_error_response('Unauthorized')

        return success_response(data=data)


class DeviceVerification(APIView):
    """To implement temporary bypass login to go straight to JULO home screen, for
    customer impacted by product picker issue """

    permission_classes = []
    authentication_classes = []

    def get(self, request):
        android_id = request.META.get('HTTP_X_ANDROID_ID')
        bypass_login = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.PRODUCT_PICKER_BYPASS_LOGIN_CONFIG, is_active=True
        )
        if not bypass_login:
            return general_error_response("Feature Setting is turned off")

        if not android_id:
            return general_error_response("Android id not found")

        try:
            device = (Device.objects.filter(android_id=android_id).select_related('customer__user').
                      last())
            if device:
                user = device.customer.user
                if (ProductPickerLoggedOutNeverResolved.objects.filter(android_id=android_id).
                        exists()):
                    result_obj = ProductPickerLoggedOutNeverResolved.objects.get(
                        android_id=android_id)

                    if ProductPickerBypassedLoginUser.objects.filter(
                        android_id=android_id, original_customer_id=device.customer.id
                    ).exists():
                        return general_error_response("User already bypassed login")

                    product_picker_bypassed_login_user = (
                        ProductPickerBypassedLoginUser.objects.create(
                            android_id=result_obj.android_id,
                            device_brand=result_obj.device_brand,
                            device_model=result_obj.device_model,
                            original_customer_id=result_obj.original_customer_id,
                            last_mobile_user_action_log_id=result_obj.
                            last_mobile_user_action_log_id,
                            last_app_version=result_obj.last_app_version,
                            last_customer_id=result_obj.last_customer_id,
                            last_application_id=result_obj.last_application_id
                        )
                    )

                    key, refresh_token = generate_new_token_and_refresh_token(user)
                    response_data = {
                        "token": key,
                        "refresh_token": refresh_token,
                        "email": user.customer.email
                    }

                    logger.info(
                        {
                            'method': 'Bypass login for product picker issue',
                            'android_id': android_id,
                            'result from analyticsdb': result_obj,
                            'object created': product_picker_bypassed_login_user,
                            'customer_id': result_obj.original_customer_id
                        }
                    )
                    return success_response(data=response_data)
                return general_error_response("Android id not whitelisted",
                                              {'android_id': android_id})
            return general_error_response("Device not found")
        except ObjectDoesNotExist:
            return general_error_response("Device or Customer not found")
