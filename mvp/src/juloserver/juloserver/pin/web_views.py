import logging

from rest_framework.views import APIView

import juloserver.pin.services as pin_services
from juloserver.julo.models import OtpRequest
from juloserver.julo.services import prevent_web_login_cases_check
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.partnership.constants import ErrorMessageConst, PartnershipFeatureNameConst
from juloserver.partnership.models import PartnershipFeatureSetting
from juloserver.pin.constants import SUSPICIOUS_LOGIN_CHECK_CLASSES, VerifyPinMsg
from juloserver.pin.models import LoginAttempt
from juloserver.pin.utils import check_lat_and_long_is_valid
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    success_response,
    unauthorized_error_response,
)

from .decorators import pin_verify_required
from .serializers import LoginJuloOneWebSerializer, RegisterJuloOneWebUserSerializer

logger = logging.getLogger(__name__)


class LoginJuloOne(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = LoginJuloOneWebSerializer

    @pin_verify_required
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        user = pin_services.get_user_from_username(validated_data['username'])
        if not user or not hasattr(user, 'customer'):
            return general_error_response("Nomor KTP atau email Anda tidak terdaftar.")

        msg = pin_services.exclude_merchant_from_j1_login(user)
        if msg:
            return general_error_response(msg)

        login_check, error_message = prevent_web_login_cases_check(
            user, validated_data['partner_name']
        )

        # PARTNER-1849: need to allow user have multiple application < 190 can login
        # also application status == 190 to redirect to other page continue in JULO apps
        continue_in_apps = False
        if error_message == ErrorMessageConst.APPLIED_APPLICATION:
            application = user.customer.application_set.last()
            if application.status == ApplicationStatusCodes.LOC_APPROVED:
                continue_in_apps = True
            elif application.status < ApplicationStatusCodes.LOC_APPROVED:
                error_message = None
                login_check = True

        is_password_correct = user.check_password(validated_data['pin'])
        if not is_password_correct:
            return unauthorized_error_response("Password Anda masih salah.")

        eligible_access = dict(is_eligible=login_check, error_message=error_message)
        if login_check:
            login_attempt = LoginAttempt.objects.filter(
                customer=user.customer,
                customer_pin_attempt__reason__in=SUSPICIOUS_LOGIN_CHECK_CLASSES,
            ).last()
            response_data = pin_services.process_login(user, validated_data, True, login_attempt)

            response_data['eligible_access'] = eligible_access
            response_data['continue_in_apps'] = continue_in_apps
        else:
            return general_error_response(error_message, {'eligible_access': eligible_access,
                                                          'continue_in_apps': continue_in_apps})

        return success_response(response_data)


class RegisterJuloOneUser(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = RegisterJuloOneWebUserSerializer

    def post(self, request):
        """
        Handles user registration
        """
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        lat, lon = serializer.validated_data['latitude'], serializer.validated_data['longitude']
        if not check_lat_and_long_is_valid(lat, lon):
            return general_error_response(VerifyPinMsg.NO_LOCATION_DATA)

        data = serializer.validated_data
        # Leadgen webapp purpose
        # Check if partner is required to do otp validation before registration
        partner_name = data.get('partner_name')
        if partner_name:
            partnership_feature_setting = PartnershipFeatureSetting.objects.filter(
                feature_name=PartnershipFeatureNameConst.LEADGEN_PARTNER_WEBAPP_OTP_REGISTER,
                is_active=True,
            ).last()
            if partnership_feature_setting:
                partners = partnership_feature_setting.parameters.get('partners', [])
                otp_request = OtpRequest.objects.filter(
                    request_id=data.get('otp_request_id'), is_used=True
                ).last()
                if partner_name in partners:
                    if not otp_request or otp_request.email != data.get('email'):
                        return general_error_response(message='User has not done the OTP process')

        logger.info(
            {
                'action': 'RegisterJuloOneUser',
                'data': data,
                'partner_name': partner_name,
                'message': 'registering for partnership webapp',
            }
        )

        try:
            response_data = pin_services.process_register(serializer.validated_data)
        except Exception as error:
            return general_error_response(str(error))

        return created_response(response_data)
