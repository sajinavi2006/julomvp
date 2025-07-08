import logging

import semver
from django.shortcuts import redirect, render
from django.utils.html import format_html
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from juloserver.customer_module.constants import ChangePhoneLostAccess, RequestPhoneNumber
from juloserver.customer_module.serializers import CustomerDeviceSerializer
from juloserver.customer_module.views.views_api_v2 import (
    BankAccountDestinationView,
    VerifyBankAccountDestination,
)
from juloserver.customer_module.services.customer_related import check_if_phone_exists
from juloserver.julo.models import Customer
from juloserver.otp.constants import (
    SessionTokenAction,
)
from juloserver.otp.services import verify_otp_session
from juloserver.pin.decorators import blocked_session, pin_verify_required
from juloserver.pin.services import (
    get_global_pin_setting,
    get_user_from_username,
)
from juloserver.standardized_api_response.mixin import (
    StrictStandardizedExceptionHandlerMixin,
)
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)
from juloserver.customer_module.services.customer_related import (
    process_incoming_change_phone_number_request,
)
from functools import wraps
from juloserver.pin.constants import VerifyPinMsg
from fuzzywuzzy import fuzz
from juloserver.ratelimit.decorator import rate_limit_incoming_http
from juloserver.ratelimit.constants import RateLimitTimeUnit, RateLimitParameter

logger = logging.getLogger(__name__)


class BankAccountDestinationViewV4(BankAccountDestinationView):
    @verify_otp_session(SessionTokenAction.ADD_BANK_ACCOUNT_DESTINATION)
    @blocked_session()
    def post(self, request, *args, **kwargs):
        return super().post(request)


class VerifyBankAccountDestinationV4(VerifyBankAccountDestination):
    @verify_otp_session(SessionTokenAction.ADD_BANK_ACCOUNT_DESTINATION)
    @blocked_session()
    @rate_limit_incoming_http(
        max_count=10,
        time_unit=RateLimitTimeUnit.Hours,
        parameters=[
            RateLimitParameter.Path,
            RateLimitParameter.HTTPMethod,
            RateLimitParameter.AuthenticatedUser,
        ],
    )
    def post(self, request, *args, **kwargs):
        return super().post(request)


class CustomerDeviceView(StrictStandardizedExceptionHandlerMixin, APIView):
    serializer_class = CustomerDeviceSerializer

    def patch(self, request):
        app_version = request.META.get('HTTP_X_APP_VERSION', "")
        try:
            if semver.match(app_version, '<7.7.1'):
                return general_error_response("App version is unsupported.")
        except ValueError:
            logger.warning(
                {
                    "message": "App version is invalid.",
                    "app_version": app_version,
                    "user_id": request.user.id,
                }
            )
            return general_error_response("App version is invalid.")

        customer = request.user.customer
        serializer = self.serializer_class(customer, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response()


class RequestChangePhoneViewSet(APIView):
    permission_classes = []

    def _return_custom_error(func):
        @wraps(func)
        def wrapper(*args, **kwargs):

            resp = func(*args, **kwargs)

            if not resp.data.get('errors'):
                return resp

            err_msg = ChangePhoneLostAccess.ErrorMessages
            err = resp.data.get("errors")[0]

            _, _, _, response_msg = get_global_pin_setting()
            pin_errors = [getattr(VerifyPinMsg, attr) for attr in dir(VerifyPinMsg)]
            credential_errors = [
                const
                for const in pin_errors
                if isinstance(const, str) and fuzz.ratio(err, const) >= 80
            ]
            credential_errors.append(
                [
                    response_msg.get('permanent_locked', VerifyPinMsg.PERMANENT_LOCKED),
                    response_msg.get('temporary_locked', VerifyPinMsg.LOCKED_LOGIN_REQUEST_LIMIT),
                    err_msg.CREDENTIAL_ERROR,
                ]
            )

            if any(
                fuzz.partial_ratio(err, credential_error) >= 80
                for credential_error in credential_errors
            ):
                err_new = '{}:{}'.format(err_msg.TYPE_SNACK_BAR, err_msg.CREDENTIAL_ERROR)
            elif err == err_msg.RATE_LIMIT_ERROR:
                err_new = '{}:{}'.format(err_msg.TYPE_BOTTOM_SHEET, err_msg.RATE_LIMIT_ERROR)
            else:
                err_new = '{}:{}'.format(err_msg.TYPE_BOTTOM_SHEET, err_msg.DEFAULT)

            resp.data.get("errors")[0] = err_new
            return resp

        return wrapper

    def _get_success_message(self, email):
        email_domain = email.split('@')[1]
        first_char_email = email.split('@')[0][0]
        masked_email = first_char_email + '***@' + email_domain

        return ChangePhoneLostAccess.SuccessMessages.DEFAULT.format(email=masked_email)

    # TODO: make sure whether WAF applied
    @_return_custom_error
    @pin_verify_required
    def post(self, request, *args, **kwargs):
        request_data = request.data
        try:
            user = get_user_from_username(request_data.get('username'))
            customer = user.customer
        except Customer.DoesNotExist:  # this case won't ever be reached
            return general_error_response(ChangePhoneLostAccess.ErrorMessages.CREDENTIAL_ERROR)

        if request_data.get('phone') != customer.phone or request_data.get('nik') != customer.nik:
            return general_error_response(ChangePhoneLostAccess.ErrorMessages.CREDENTIAL_ERROR)

        android_id = request.META.get('HTTP_X_ANDROID_ID')

        err = process_incoming_change_phone_number_request(customer, android_id)
        if err:
            return general_error_response(err)

        message = self._get_success_message(customer.email)
        data = {
            "message": message,
        }

        return success_response(data)


class GetFormChangePhoneViewSet(APIView):
    permission_classes = []

    def get(self, request, reset_key):
        customer = Customer.objects.filter(reset_password_key=reset_key).first()
        ctx = {}
        if customer:
            if not customer.has_resetkey_expired():
                template = "reset_phone/change_new_phone_form.html"
                ctx.update(
                    **{
                        "reset_key": reset_key,
                        "phone": customer.phone,
                        "customer_xid": customer.customer_xid,
                    }
                )
            else:
                template = "reset_phone/change_failed.html"
                ctx["title"] = RequestPhoneNumber.PopUpDetail.RESET_KEY_EXPIRED['title']
                ctx["message"] = RequestPhoneNumber.PopUpDetail.RESET_KEY_EXPIRED['message']
        else:
            template = "reset_phone/change_failed.html"
            ctx["title"] = RequestPhoneNumber.PopUpDetail.INVALID_RESET_KEY['title']
            ctx["message"] = RequestPhoneNumber.PopUpDetail.INVALID_RESET_KEY['message']

        return render(request, template, ctx)


class SubmitRequestChangePhoneViewSet(APIView):
    permission_classes = []

    def get(self, request, reset_key):
        customer = Customer.objects.filter(reset_password_key=reset_key).first()
        reset_key_session = self.get_reset_key_session("reset_password_key")
        if reset_key_session != reset_key or (customer and customer.has_resetkey_expired()):
            ctx = {
                "title": RequestPhoneNumber.PopUpDetail.RESET_KEY_EXPIRED['title'],
                "message": RequestPhoneNumber.PopUpDetail.RESET_KEY_EXPIRED['message'],
            }
            template = "reset_phone/change_failed.html"
        else:
            ctx = {}
            template = "reset_phone/change_success.html"

        return render(request, template, ctx)

    def post(self, request, reset_key):
        data = request.data
        render_data_fail = self.get_render_data_fail_change_phone(reset_key, data['phone'])
        if render_data_fail:
            return render(**render_data_fail)

        return redirect(
            reverse('get-otp-verification', args=['sms', data["customer_xid"]])
            + (
                "?action_type="
                + SessionTokenAction.PRE_LOGIN_CHANGE_PHONE
                + "&reset_key="
                + reset_key
                + '&new_phone_number='
                + data['phone']
            )
        )

    def get_render_data_fail_change_phone(self, reset_key, phone):
        title = message = None

        customer = Customer.objects.get(reset_password_key=reset_key)
        if customer and customer.has_resetkey_expired():
            title = RequestPhoneNumber.PopUpDetail.RESET_KEY_EXPIRED["title"]
            message = RequestPhoneNumber.PopUpDetail.RESET_KEY_EXPIRED["message"]

        existing_customer = check_if_phone_exists(phone, customer)
        if existing_customer:
            message = RequestPhoneNumber.PopUpDetail.PHONE_NUMBER_EXISTS["message"]

        # detokenize customer here
        if message:
            if title:
                template = "reset_phone/change_failed.html"
                ctx = {"title": title, "message": message}
            else:
                template = "reset_phone/change_new_phone_form.html"
                ctx = {
                    "reset_key": reset_key,
                    "phone": customer.phone,
                    "customer_xid": customer.customer_xid,
                    "err_message": format_html(
                        "<div class='error' id='warning-phone'>{}</div>", message
                    ),
                }

            return {"request": self.request, "template_name": template, "context": ctx}

        return None

    def get_reset_key_session(self, key):
        if key not in self.request.session:
            return False

        value = self.request.session.get(key)
        del self.request.session["reset_password_key"]
        return value
