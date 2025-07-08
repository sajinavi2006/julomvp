from builtins import str
import json
import logging

from rest_framework.generics import CreateAPIView
from rest_framework.views import APIView
import rest_framework.viewsets as viewsets
from rest_framework.response import Response
from django.conf import settings

from juloserver.grab.authentication import GrabPartnerAuthentication
from juloserver.core.authentication import JWTAuthentication
from juloserver.grab.exceptions import GrabApiException
from juloserver.grab.serializers import *
from juloserver.grab.services.loan_related import (
    process_grab_loan_signature_upload_success,
    is_user_have_active_loans,
    create_fdc_inquiry,
    is_below_allowed_platforms_limit,
    get_fdc_active_loan_check,
)
from juloserver.grab.services.services import *
from juloserver.julo.exceptions import JuloException
from juloserver.loan.serializers import CreateManualSignatureSerializer
from juloserver.partnership.constants import HTTPStatusCode
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    internal_server_error_response,
    forbidden_error_response,
    custom_bad_request_response,
    response_template,
    request_timeout_response,
)
from juloserver.grab.models import GrabCustomerData, GrabAPILog
from juloserver.standardized_api_response.utils import unauthorized_error_response
from juloserver.grab.mixin import GrabStandardizedExceptionHandlerMixin
from juloserver.apiv3.models import CityLookup, DistrictLookup, ProvinceLookup, SubDistrictLookup
from juloserver.apiv3.serializers import (
    AddressInfoSerializer,
    SubDistrictLookupReqSerializer,
    SubDistrictLookupResSerializer,
)
from juloserver.grab.services.loan_related import check_grab_auth_success
from juloserver.grab.services.bank_rejection_flow import GrabChangeBankAccountService
from juloserver.grab.constants import (
    GrabBankValidationStatus,
    GRAB_MAX_CREDITORS_REACHED_ERROR_MESSAGE,
    GrabExperimentConst,
)
from django.db.utils import IntegrityError
from juloserver.grab.segmented_tasks.disbursement_tasks import (
    trigger_create_or_update_ayoconnect_beneficiary,
)
from juloserver.grab.utils import (
    error_response_web_app,
    get_grab_customer_data_anonymous_user
)
from juloserver.grab.services import fdc as grab_fdc
from juloserver.loan.constants import FDCUpdateTypes
from juloserver.core.constants import JWTConstant

logger = logging.getLogger(__name__)


def grab_app_session(function):
    def wrap(view, request, *args, **kwargs):
        paths = [
            "/api/partner/grab/otp_request",
            "/api/partner/grab/otp_confirmation",
            "/api/partner/grab/register",
            "/api/partner/grab/loan_offer",
            "/api/partner/grab/payment_plans",
            "/api/partner/grab/choose_payment_plan",
            "/api/partner/grab/validate-promo-code",
        ]

        verified_paths = [
            "/api/partner/grab/register",
            "/api/partner/grab/loan_offer",
            "/api/partner/grab/payment_plans",
            "/api/partner/grab/choose_payment_plan",
            "/api/partner/grab/validate-promo-code",
            "/api/partner/grab/user-experiment-group",
        ]

        phone_number = None
        if request.path in paths:
            if request.GET.get('phone_number'):
                phone_number = request.GET.get('phone_number')
            elif request.body:
                phone_number = json.loads(request.body).get('phone_number')
            token = request.META.get('HTTP_AUTHORIZATION', None)

            if phone_number and token:
                grab_customer_data = GrabCustomerData.objects.get_or_none(
                    phone_number=phone_number, token=token
                )

                if grab_customer_data:
                    request.grab_customer_data = grab_customer_data
                else:
                    return unauthorized_error_response("Unauthorized request")
            else:
                return unauthorized_error_response("Unauthorized request")

        if request.path in verified_paths:
            if request.GET.get('phone_number'):
                phone_number = request.GET.get('phone_number')
            elif request.body:
                phone_number = json.loads(request.body).get('phone_number')
            token = request.META.get('HTTP_AUTHORIZATION', None)

            if phone_number and token:
                grab_customer_data = GrabCustomerData.objects.get_or_none(
                    phone_number=phone_number,
                    token=token,
                    otp_status=GrabCustomerData.VERIFIED,
                    grab_validation_status=True,
                )

                if grab_customer_data:
                    request.grab_customer_data = grab_customer_data
                else:
                    return unauthorized_error_response("Unauthorized request")
            else:
                return unauthorized_error_response("Unauthorized request")

        return function(view, request, *args, **kwargs)

    wrap.__doc__ = function.__doc__
    wrap.__name__ = function.__name__

    return wrap


def grab_verified_session(function):
    def wrap(view, request, *args, **kwargs):
        customer = request.user.customer
        grab_customer_data = GrabCustomerData.objects.get_or_none(
            customer=customer, otp_status=GrabCustomerData.VERIFIED
        )

        if grab_customer_data:
            request.grab_customer_data = grab_customer_data
        else:
            return unauthorized_error_response("Unauthorized request")

        return function(view, request, *args, **kwargs)

    wrap.__doc__ = function.__doc__
    wrap.__name__ = function.__name__

    return wrap


def grab_api(function):
    def wrap(view, request, *args, **kwargs):
        return function(view, request, *args, **kwargs)

    wrap.__doc__ = function.__doc__
    wrap.__name__ = function.__name__

    return wrap


# Auth views
class GrabLoginView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabLoginSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def generate_jwt_token(self, result):
        jwt_auth = JWTAuthentication()
        grab_auth_service = GrabAuthService()

        if not result:
            return result

        customer_id = result.get('customer_id')
        grab_customer_data = grab_auth_service.get_grab_customer_data(customer_id)
        grab_customer_data_id = None
        if grab_customer_data:
            grab_customer_data_id = grab_customer_data.id

        application = grab_auth_service.get_application_data(customer_id)
        application_id = None
        if application:
            application_id = application.id

        if not grab_customer_data_id:
            application_id = None
            grab_anonymous_user = get_grab_customer_data_anonymous_user()
            grab_customer_data_id = grab_anonymous_user.id

        payload = {
            "product": str(ProductLineCodes.GRAB),
            "user_identifier_id": grab_customer_data_id,
            "application_id": application_id,
            "expired_at": str(
                timezone.localtime(timezone.now()) + timedelta(days=JWTConstant.EXPIRED_IN_DAYS)),
        }

        jwt_token = jwt_auth.generate_token(payload, settings.GRAB_JWT_SECRET_KEY)
        result.update({"jwt_token": jwt_token})
        return result

    @grab_app_session
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return error_response_web_app(errors=serializer.errors)
            data = serializer.validated_data
            pin = data.get('pin')
            nik = data.get('nik')
            if pin:
                result = GrabAuthService().login(nik, pin)
            else:
                result = GrabAuthService().validate_email_or_nik(nik)

            result = self.generate_jwt_token(result)
            return success_response(result)
        except GrabLogicException as error:
            if 'subtitle' not in str(error):
                error = {"title": str(error), "subtitle": ""}
            return error_response_web_app(str(error))
        except User.pin.RelatedObjectDoesNotExist as dne:
            error = {"title": str(dne), "subtitle": ""}
            return error_response_web_app(str(error))


class GrabRegisterView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabRegisterSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):

        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)

            token = request.META.get('HTTP_AUTHORIZATION', None)
            data = serializer.validated_data

            nik = data['nik']
            phone_number = data["phone_number"]
            pin = data['pin']
            j1_bypass = data['j1_bypass']
            email = data.get('email')

            result = GrabAuthService().register(
                token, nik, phone_number, pin, j1_bypass, email=email
            )

            return success_response(result)
        except GrabLogicException as e:
            logger.info({"view": "GrabRegisterView", "error": str(e)})
            return general_error_response(str(e))
        except ValidationError as ve:
            logger.info({"view": "GrabRegisterView", "error": str(ve)})
            return general_error_response(str(ve))


class GrabReapplyView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_verified_session
    @grab_app_session
    def post(self, request):

        try:
            customer = request.user.customer
            result = GrabAuthService().reapply(customer)

            return success_response(result)
        except GrabLogicException as e:
            logger.info(e)
            return general_error_response(str(e))


class GrabLinkAccountView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabLinkAccountSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def generate_jwt_token(self, result):
        jwt_auth = JWTAuthentication()

        if not result:
            return result

        grab_customer_data_id = result.get("grab_customer_data_id", None)
        if not grab_customer_data_id:
            grab_anonymous_user = get_grab_customer_data_anonymous_user()
            grab_customer_data_id = grab_anonymous_user.id

        payload = {
            "product": str(ProductLineCodes.GRAB),
            "user_identifier_id": grab_customer_data_id,
            "application_id": None,
            "expired_at": str(
                timezone.localtime(timezone.now()) + timedelta(days=JWTConstant.EXPIRED_IN_DAYS)),
        }

        jwt_token = jwt_auth.generate_token(payload, settings.GRAB_JWT_SECRET_KEY)
        result.update({"jwt_token": jwt_token})
        return result

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response_web_app(errors=serializer.errors)

        try:
            phone_number = serializer.validated_data['phone_number']
            device = request.data.get('device', None)
            web_browser = request.data.get('web_browser', None)
            result = GrabAuthService().link_account(phone_number, device, web_browser)

            if result['is_linked']:
                token = result['token']
                request_id = result['request_id']
                result_otp = GrabAuthService().request_otp(phone_number, request_id, token)
                result['request_id'] = result_otp['request_id']
            if 'is_linked' in result:
                result.pop('is_linked')

            result = self.generate_jwt_token(result)
            del result["grab_customer_data_id"]
            return success_response(result)
        except GrabLogicException as e:
            if 'subtitle' not in str(e):
                e = {"title": str(e), "subtitle": ""}
            return error_response_web_app(str(e))


class GrabForgotPasswordView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabForgotPasswordSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            validated_data = serializer.validated_data
            email = validated_data['email'].strip().lower()
            GrabAuthService().forgot_password(email)
            return success_response('A PIN reset email will be sent if the email is registered')
        except Exception as err:
            return internal_server_error_response(str(err))


class GrabOTPRequestView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabOTPRequestSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            data = serializer.validated_data
            token = request.META.get('HTTP_AUTHORIZATION', None)
            phone_number = data["phone_number"]
            request_id = str(data["request_id"])

            result = GrabAuthService().request_otp(
                phone_number, request_id, token, is_api_request=True
            )

            return success_response(result)
        except GrabLogicException as e:
            str_err_msg = str(e)
            logger.info({"view": "GrabOTPRequestView", "status": "400", "error": str_err_msg})
            if 'subtitle' not in str_err_msg:
                str_err_msg = str({"title": str_err_msg, "subtitle": ""})
            return error_response_web_app(str_err_msg)


class GrabOTPConfirmationView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabOTPConfirmationSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            data = serializer.validated_data
            token = request.META.get('HTTP_AUTHORIZATION', None)
            otp_code = request.data['otp_code']
            request_id = data["request_id"]
            phone_number = data["phone_number"]
            result = GrabAuthService().confirm_otp(token, otp_code, request_id, phone_number)

            return success_response(result)
        except GrabLogicException as e:
            str_err_msg = str(e)
            logger.info({"view": "GrabOTPConfirmationView", "status": "400", "error": str_err_msg})
            if 'subtitle' not in str_err_msg:
                str_err_msg = str({"title": str_err_msg, "subtitle": ""})
            return error_response_web_app(str_err_msg)
        except GrabApiException as e:
            return request_timeout_response(str(e))


# Common views
class GrabHomepageView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            customer = request.user.customer
            user = request.user
            result = GrabCommonService().get_homepage_data(customer, user)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabDropdownDataView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            if 'page' in request.GET:
                page = request.GET['page']
            else:
                raise GrabLogicException('Enter Page Number.')
            result = GrabCommonService().get_dropdown_data(page)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabUploadView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GrabUploadSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            image_type = data["image_type"]
            upload = request.data.get("file")
            customer = request.user.customer
            result = GrabCommonService().upload(image_type, upload, customer)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabOTPMiscallRequestView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabOTPRequestSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            data = serializer.validated_data
            token = request.META.get('HTTP_AUTHORIZATION', None)
            phone_number = data["phone_number"]
            request_id = str(data["request_id"])

            result = GrabAuthService().request_miscall_otp(phone_number, request_id, token)

            return success_response(result)
        except (GrabLogicException, CitcallClientError) as e:
            str_err_msg = str(e)
            if 'subtitle' not in str_err_msg:
                str_err_msg = str({"title": str_err_msg, "subtitle": ""})
            return error_response_web_app(str_err_msg)


# Application views
class GrabSubmitApplicationView(StandardizedExceptionHandlerMixin, APIView):
    model_class = Application
    serializer_class = GrabApplicationSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):

        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            customer = request.user.customer

            data = request.data
            result = GrabApplicationService().submit_grab_application(
                customer, serializer.validated_data, data
            )

            return success_response(result)
        except GrabLogicException as e:
            logger.info(
                {"action": "GrabSubmitApplicationView", "data": str(request.data), "error": str(e)}
            )
            return general_error_response(str(e))
        except GrabApiException as e:
            return response_template(
                None, status=https_status_codes.HTTP_403_FORBIDDEN, message=[str(e)]
            )

    @grab_app_session
    def put(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            validated_data = serializer.validated_data

            customer = request.user.customer
            email = validated_data.get('email', None)
            if not email:
                raise GrabLogicException('Email tidak boleh kosong')
            validate_email(email, customer)
            validate_email_application(email, customer)
            application = customer.application_set.filter(
                product_line__product_line_code__in=ProductLineCodes.grab()
            ).last()
            application.update_safely(email=email)
            customer.update_safely(email=email)
            return success_response(application.email)
        except GrabLogicException as e:
            logger.info(
                {"action": "GrabSubmitApplicationView", "data": str(request.data), "error": str(e)}
            )
            return general_error_response(str(e))


class GrabApplicationReviewView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            customer = request.user.customer
            result = GrabApplicationService().get_application_review(customer)

            return success_response(result)
        except GrabApiException as e:
            return general_error_response(message=str(e), data=e.data)
        except GrabLogicException as e:
            return general_error_response(str(e))


# Loan views
class GrabLoanOfferView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        phone_number = request.GET.get('phone_number')
        grab_loan_service = GrabLoanService()
        grab_loan_service.set_redis_client()

        try:
            token = request.META.get('HTTP_AUTHORIZATION', None)
            result = grab_loan_service.get_loan_offer(token, phone_number)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))
        except GrabApiException as e:
            logger.info(
                {"task": "GrabLoanOfferView", "error": str(e), "phone_number": phone_number}
            )
            return general_error_response(str(e))


class GrabPaymentPlansView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabRepaymentPlanSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        try:
            grab_customer_data = request.grab_customer_data
            if not grab_customer_data:
                raise GrabApiException("Grab customer data doesnt exist for this customer")

            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)

            data = serializer.validated_data
            phone_number = data['phone_number']
            program_id = data['program_id']
            loan_amount = data['loan_amount']
            interest_rate = data['interest_rate']
            upfront_fee = data['upfront_fee']
            min_tenure = data['min_tenure']
            tenure = data['tenure']
            tenure_interval = data['tenure_interval']
            offer_threshold = data['offer_threshold']
            min_loan_amount = data['min_loan_amount']
            max_loan_amount = data['max_loan_amount']
            token = request.META.get('HTTP_AUTHORIZATION', None)
            user_type = data.get('user_type')

            grab_loan_service = GrabLoanService()
            grab_loan_service.set_redis_client()

            result = None
            if not user_type or user_type == GrabExperimentConst.CONTROL_TYPE:
                result = grab_loan_service.get_payment_plans(
                    token,
                    phone_number,
                    program_id,
                    loan_amount,
                    interest_rate,
                    upfront_fee,
                    min_tenure,
                    tenure,
                    tenure_interval,
                    offer_threshold,
                    min_loan_amount,
                    max_loan_amount,
                )
            elif user_type == GrabExperimentConst.VARIATION_TYPE:
                result = grab_loan_service.get_payment_plans_v2(
                    token, phone_number, program_id, tenure
                )

            grab_loan_service.record_payment_plans(
                grab_customer_data_id=request.grab_customer_data.id,
                program_id=program_id,
                payment_plans=result,
            )

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabChoosePaymentPlanView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabChoosePaymentPlanSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            grab_loan_service = GrabLoanService()
            grab_loan_service.set_redis_client()

            token = request.META.get('HTTP_AUTHORIZATION', None)
            result = grab_loan_service.choose_payment_plan(token, serializer.validated_data)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabPreLoanDetailView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            customer = request.user.customer
            result = GrabLoanService().get_pre_loan_detail(customer)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabLoanApplyView(APIView):
    serializer_class = GrabLoanApplySerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get_application(self, customer):
        account = Account.objects.filter(
            customer=customer, account_lookup__workflow__name=WorkflowConst.GRAB
        ).last()
        if not account:
            raise GrabLogicException('Account tidak ditemukan')

        application = account.last_application
        if not application:
            raise GrabLogicException('Application tidak ditemukan')

        return application

    def get_parameters(self):
        from juloserver.loan.services.loan_related import (
            get_parameters_fs_check_other_active_platforms_using_fdc,
        )

        parameters = get_parameters_fs_check_other_active_platforms_using_fdc(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK
        )
        return parameters

    def request_fdc_data_sync(self, application, parameters):
        from juloserver.loan.tasks.lender_related import (
            fdc_inquiry_other_active_loans_from_platforms_task,
        )

        outdated_threshold_days = parameters['fdc_data_outdated_threshold_days']
        number_allowed_platforms = parameters['number_of_allowed_platforms']

        params = dict(
            application_id=application.id,
            loan_id=None,
            fdc_data_outdated_threshold_days=outdated_threshold_days,
            number_of_allowed_platforms=number_allowed_platforms,
            fdc_inquiry_api_config=parameters['fdc_inquiry_api_config'],
        )

        fdc_inquiry, fdc_inquiry_data = create_fdc_inquiry(application.customer, params)
        params['fdc_inquiry_id'] = fdc_inquiry.pk

        is_success = False
        for _ in range(3):
            is_success = fdc_inquiry_other_active_loans_from_platforms_task(
                fdc_inquiry_data=fdc_inquiry_data,
                customer_id=application.customer.id,
                type_update=FDCUpdateTypes.GRAB_SUBMIT_LOAN,
                params=params,
            )
            if is_success:
                break

        return is_success

    def seojk_max_creditors_validation(self, customer):
        parameters = self.get_parameters()
        if not parameters:
            return True, None

        application = self.get_application(customer)
        fdc_inquiry_dict = grab_fdc.get_fdc_inquiry_data(
            application_id=application.id,
            day_diff=parameters.get("fdc_data_outdated_threshold_days"),
        )
        fdc_inquiry = fdc_inquiry_dict.get("fdc_inquiry")
        if not fdc_inquiry:
            # this will create fdc active loan checking
            fdc_active_loan_checking = get_fdc_active_loan_check(customer_id=customer.id)
            # this will update the fdc active loan checking that we create before
            self.request_fdc_data_sync(application=application, parameters=parameters)

        fdc_inquiry = grab_fdc.get_fdc_data_without_expired_rules(parameters, application.id)
        # if there is no fdc data even after 3 time retries, just pass the user
        if not fdc_inquiry:
            return True, application

        fdc_active_loan_checking = get_fdc_active_loan_check(customer_id=customer.id)
        is_eligible = is_below_allowed_platforms_limit(
            number_of_allowed_platforms=parameters['number_of_allowed_platforms'],
            fdc_inquiry=fdc_inquiry,
            fdc_active_loan_checking=fdc_active_loan_checking,
        )
        return is_eligible, application

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            customer = request.user.customer
            user = request.user
            validated_data = serializer.validated_data
            program_id = validated_data['program_id']
            loan_amount = validated_data['loan_amount']
            tenure = validated_data['tenure']
            promo_code = validated_data.get('promo_code', None)

            if not is_user_have_active_loans(customer.id):
                is_dax_eligible, application = self.seojk_max_creditors_validation(customer)
                if not is_dax_eligible:
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                        GRAB_MAX_CREDITORS_REACHED_ERROR_MESSAGE.format(3),
                    )
                    raise GrabLogicException(
                        "Failed Loan Creation related to max creditors compliance"
                    )

            validate_loan_request(customer)
            data = GrabLoanService().apply(customer, user, program_id, loan_amount, tenure)
            if not data or "loan" not in data:
                raise GrabLogicException("Failed Loan Creation")
            loan = data["loan"]
            result = {
                'loan_id': loan.id,
                'loan_status': loan.status,
                'loan_amount': loan.loan_amount,
                'disbursement_amount': data["disbursement_amount"],
                'loan_duration': loan.loan_duration,
                'installment_amount': data["installment_amount"],
                'monthly_interest': data["monthly_interest"],
                'loan_xid': loan.loan_xid,
            }
            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabLoanSignatureUploadView(StandardizedExceptionHandlerMixin, CreateAPIView):
    serializer_class = CreateManualSignatureSerializer

    def create(self, request, *args, **kwargs):
        user = self.request.user
        loan_xid = kwargs.get('loan_xid', None)
        if not loan_xid:
            return general_error_response("loan_xid is required")

        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        if not loan:
            return general_error_response("Loan XID:{} Not found".format(loan_xid))

        is_auth_success = check_grab_auth_success(loan.id)
        if not is_auth_success:
            return general_error_response("Auth not yet successful")
        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        data = request.POST.copy()

        data['image_source'] = loan.id
        data['image_type'] = 'signature'
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
            if (
                loan.account
                and loan.account.is_grab_account()
                and loan.loan_status_id == LoanStatusCodes.INACTIVE
            ):
                process_grab_loan_signature_upload_success(loan)
        except JuloException as je:
            return general_error_response(message=str(je))
        headers = self.get_success_headers(serializer.data)
        response_dict = {'success': True, 'data': serializer.data, 'errors': []}
        return Response(
            data=response_dict, status=https_status_codes.HTTP_201_CREATED, headers=headers
        )


class GrabAgreementSummaryView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            loan_xid = request.GET.get('loan_xid')
            result = GrabLoanService().get_agreement_summary(loan_xid)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabAgreementLetterView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            loan_xid = request.GET.get('loan_xid')
            if not loan_xid:
                raise GrabLogicException('loan_xid is required')
            result = GrabLoanService().get_agreement_letter(loan_xid)
            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabLoansAccountPaymentView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            data_type = request.GET.get('type')
            account_id = request.GET.get('account_id')

            customer = request.user.customer

            result = GrabLoanService().get_loans_account_payment(customer, account_id, data_type)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabLoansPaymentView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            data_type = request.GET.get('type')
            account_id = request.GET.get('account_id')

            customer = request.user.customer

            result = GrabLoanService().get_loans_payment(customer, account_id, data_type)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabLoanPaymentsView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            loan_xid = request.GET.get('loan_xid')

            result = GrabLoanService().get_loan_payments(loan_xid)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabLoanPaymentDetailView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            payment_id = request.GET.get('payment_id')
            result = GrabLoanService().get_loan_payment_detail(request, payment_id)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabLoanDetailView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            loan_xid = request.GET.get('loan_xid')
            result = GrabLoanService().get_loan_detail(loan_xid)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


# API Partner views
class GrabAccountSummaryView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            loan_xid = request.GET.get('loan_xid', None)
            application_xid = request.GET.get("application_xid", None)
            offset = request.GET.get("offset", 0)
            limit = request.GET.get("limit", 10)
            result = GrabAPIService().get_account_summary(loan_xid, application_xid, offset, limit)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabAddRepaymentView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabAddRepaymentSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            application_xid = data['application_xid']
            loan_xid = data['loan_xid']
            deduction_reference_id = data['deduction_reference_id']
            event_date = data['event_date']
            deduction_amount = data['deduction_amount']
            txn_id = data.get('txn_id', None)
            result = GrabAPIService().add_repayment(
                application_xid,
                loan_xid,
                deduction_reference_id,
                event_date,
                deduction_amount,
                txn_id,
            )

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))
        except ValidationError as ve:
            return general_error_response(str(ve))


class GrabHomePageIntegrationApiView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabHomePageSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            data = serializer.validated_data
            offset = data['offset']
            limit = data['limit']
            msg_id = data['msg_id']
            hash_phone_number = data['user_token']
            result = GrabAPIService().get_grab_home_page_data(hash_phone_number, offset, limit)

            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabApplicationStatusView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):

        try:
            customer = request.user.customer
            result = GrabAPIService().application_status_check(customer)
            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabValidateReferralCodeView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY
    serializer_class = GrabValidateReferralCodeSerializer

    @grab_app_session
    def get(self, request):
        serializer = self.serializer_class(data=request.GET)
        serializer.is_valid(raise_exception=True)
        try:
            customer = request.user.customer
            result = GrabAPIService().application_validate_referral_code(
                customer, serializer.validated_data['referral_code']
            )
            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))


# Account page views
class GrabAccountPageView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            customer = request.user.customer
            result = GrabAccountPageService().get_account_page_response(customer)
            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))
        except GrabApiException as e:
            return general_error_response(str(e))


class GrabChangePINView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GrabChangePINSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY
    exclude_field_name_in_error_message = {"current_pin", "new_pin"}

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            customer = request.user.customer
            data = serializer.validated_data
            current_pin = data['current_pin']
            new_pin = data['new_pin']
            result = GrabAccountPageService().process_update_pin_response(
                customer, current_pin, new_pin
            )
            if result.get('updated_status'):
                return success_response(result)
            else:
                return general_error_response(message=result.get('message'))
        except Exception as err:
            return internal_server_error_response(str(err))


class GrabInfoCardsView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        customer = request.user.customer
        try:
            result = GrabCommonService().get_info_card(customer)
        except GrabApiException as e:
            logger.exception({"status": "Failed", "error": str(e)})
            return general_error_response(str(e))
        return success_response(result)


class GrabBankCheckView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GrabBankCheckSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        serializer = self.serializer_class(data=request.GET)
        serializer.is_valid(raise_exception=True)
        try:
            return_value = {'bank_name_validation': True}
            customer = request.user.customer
            data = serializer.validated_data
            bank_name = data['bank_name']
            bank_account_number = data['bank_account_number']
            result = GrabCommonService().get_bank_check_data(
                customer, bank_name, bank_account_number
            )

        except GrabLogicException as e:
            return_value = {'bank_name_validation': False, 'errors': str(e)}
        except GrabApiException as e:
            return_value = {'bank_name_validation': False, 'errors': str(e)}

        return success_response(return_value)


class GrabBankPredisbursalCheckView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GrabBankCheckSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY
    exclude_field_name_in_error_message = {"bank_account_number"}

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return_value = {'bank_name_validation': True}
            customer = request.user.customer
            data = serializer.validated_data
            bank_name = data['bank_name']
            bank_account_number = data['bank_account_number']
            result = GrabCommonService().get_bank_check_data(
                customer, bank_name, bank_account_number
            )

        except GrabLogicException as e:
            return general_error_response(str(e))
        except GrabApiException as e:
            return general_error_response(str(e))

        return success_response(return_value)


class GrabFeatureSettingView(APIView):
    """
    end point for Mobile feature settings
    """

    permission_classes = []

    def get(self, request, *args, **kwargs):
        try:
            return_value = GrabCommonService.get_grab_feature_setting()
        except GrabLogicException as e:
            return_value = {'grab_modal_registration_ready': False, 'errors': str(e)}

        return success_response(return_value)


class GrabGetReapplyStatusView(APIView):
    """
    end point for Mobile feature settings
    """

    @grab_app_session
    def get(self, request):
        customer = request.user.customer
        try:
            return_value = GrabApplicationService.get_grab_registeration_reapply_status(customer)
            return success_response(return_value)
        except GrabLogicException as e:
            return general_error_response(str(e))


class GrabChangePhoneOTPRequestView(APIView):
    serializer_class = GrabOTPRequestSerializer

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        try:
            data = serializer.validated_data
            phone_number = data["phone_number"]
            request_id = str(data["request_id"])

            result = GrabAuthService().change_phonenumber_request_otp(
                phone_number, request_id, customer
            )

            return success_response(result)
        except GrabLogicException as e:
            logger.info(
                {
                    "action": "GrabChangePhoneOTPRequestView",
                    "customer_id": customer.id,
                    "error": str(e),
                }
            )
            return general_error_response(str(e))


class GrabChangePhoneOTPConfirmationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GrabOTPConfirmationSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        try:

            data = serializer.validated_data
            otp_code = request.data['otp_code']
            request_id = data["request_id"]
            phone_number = data["phone_number"]
            result = GrabAuthService().change_phonenumber_confirm_otp(
                customer, otp_code, request_id, phone_number
            )

            return success_response(result)
        except GrabLogicException as e:
            logger.info(
                {
                    "action": "GrabChangePhoneOTPConfirmationView",
                    "customer_id": customer.id,
                    "error": str(e),
                }
            )
            return general_error_response(str(e))


class GrabCheckPhoneNumberView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        customer = request.user.customer
        try:
            phone_number = request.GET.get('phone_number', None)
            if not phone_number:
                return general_error_response("Phone Number cannot be empty")
            result = GrabLoanService().check_phone_number_change(customer, phone_number)

            return success_response(result)
        except GrabLogicException as e:
            logger.info(
                {"action": "GrabCheckPhoneNumberView", "customer_id": customer.id, "error": str(e)}
            )
            return general_error_response(str(e))
        except GrabApiException as e:
            logger.info(
                {"action": "GrabCheckPhoneNumberView", "customer_id": customer.id, "error": str(e)}
            )
            return general_error_response(str(e))


class GrabChangePhoneNumberView(StandardizedExceptionHandlerMixin, APIView):
    """
    ENDPOINT to update the Phone Number
    """

    serializer_class = GrabPhoneNumberChangeSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        customer = request.user.customer

        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            old_phone_number = data['old_phone_number']
            new_phone_number = data['new_phone_number']
            response = change_phone_number_grab(customer, old_phone_number, new_phone_number)
            return success_response(response)

        except GrabLogicException as e:
            logger.info(
                {"action": "GrabChangePhoneNumberView", "customer_id": customer.id, "error": str(e)}
            )
            return general_error_response(str(e))


class GrabVerifyPINView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GrabVerifyPINSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY
    exclude_field_name_in_error_message = {"pin"}

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            customer = request.user.customer
            data = serializer.validated_data
            pin = data['pin']
            result = GrabAccountPageService().process_verify_pin_response(customer, pin)
            if result.get('locked'):
                return forbidden_error_response(message=result.get('message'))
            elif result.get('verified_status'):
                return success_response(result)
            else:
                return general_error_response(message=result.get('message'))
        except Exception as err:
            return internal_server_error_response(str(err))


class GrabLoanTransactionDetailView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            customer = request.user.customer
            result = GrabApplicationService().get_pre_loan_response(customer)

            return success_response(result)
        except GrabLogicException as e:
            logger.exception(
                {
                    "action": "GrabLoanTransactionDetailView",
                    "data": str(request.data),
                    "error": str(e),
                }
            )
            return general_error_response(str(e))


class GrabReferralInfoView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        customer = request.user.customer
        (
            valid,
            referral_code,
            total_cashback,
            start_time,
            max_limit_current_whitelist,
            referrer_incentive,
            referred_incentive,
        ) = GrabAccountPageService().check_and_generate_referral_code(customer)
        if not valid:
            return general_error_response("customer not eligible to generate referral code")

        data = {
            "referral_code": referral_code,
            "total_cashback": total_cashback,
            "cashback_per_referral": referrer_incentive,
            "cashback_for_friend": referred_incentive,
            "campaign_start_time": start_time,
            "max_limit_current_whitelist": max_limit_current_whitelist,
        }
        return success_response(data)


class GrabGetAuditDataFromOSSView(StandardizedExceptionHandlerMixin, APIView):
    """
    This API is for fetching the presigned URL For a particular event date.
    Based on the event date, It'll return the number of crons run for that date.
    We pass in the event date in 'YYYY-MM-DD' format and the number of files for
    that date is received.
    If the file number is passed as Param the presigned URL is also returned.
    As per current implementation the duration for expiry for the URL is 60sec
    """

    authentication_classes = (GrabPartnerAuthentication,)
    serializer_class = GrabGetAuditDataFromOSSSerializer
    exclude_field_name_in_error_message = {"field_type"}

    def get(self, request):
        try:
            serializer = self.serializer_class(data=request.GET)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            event_date = data.get('event_date')
            file_number = data.get('file_number')
            file_type = data.get('file_type')
            mapped_file_type = mapping_grab_file_transfer_file_type(file_type)
            response_data = get_audit_oss_links(event_date, file_number, mapped_file_type)
        except Exception as err:
            return general_error_response(str(err))
        return success_response(response_data)


class GrabAddressLookupView(StandardizedExceptionHandlerMixin, viewsets.ViewSet):
    def get_provinces(self, request):
        provinces = (
            ProvinceLookup.objects.filter(is_active=True)
            .order_by('province')
            .values_list('province', flat=True)
        )
        return success_response(provinces)

    def get_cities(self, request):
        data = request.GET
        if 'province' not in data:
            return general_error_response('province is required')
        cities = (
            CityLookup.objects.filter(
                province__province__icontains=data['province'], is_active=True
            )
            .order_by('city')
            .values_list('city', flat=True)
        )
        return success_response(cities)

    def get_districts(self, request):
        data = request.GET
        if 'province' not in data:
            return general_error_response('province is required')
        if 'city' not in data:
            return general_error_response('city is required')
        district = (
            DistrictLookup.objects.filter(
                city__city__icontains=data['city'],
                city__province__province__icontains=data['province'],
                is_active=True,
            )
            .order_by('district')
            .values_list('district', flat=True)
        )
        return success_response(district)

    def get_subdistricts(self, request):
        serializer = SubDistrictLookupReqSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        subdistrict = SubDistrictLookup.objects.filter(
            district__district__icontains=data['district'],
            district__city__city__icontains=data['city'],
            district__city__province__province__icontains=data['province'],
            is_active=True,
        ).order_by('sub_district')
        return success_response(SubDistrictLookupResSerializer(subdistrict, many=True).data)

    def get_info(self, request):
        serializer = AddressInfoSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        subdistricts = SubDistrictLookup.objects.filter(zipcode=data['zipcode'], is_active=True)
        if len(subdistricts) > 1:
            filtered_subdistricts = subdistricts.filter(sub_district__icontains=data['subdistrict'])
            if filtered_subdistricts:
                subdistricts = filtered_subdistricts

        subdistrict = subdistricts.first()

        if subdistrict:
            res_data = {
                "province": subdistrict.district.city.province.province,
                "city": subdistrict.district.city.city,
                "district": subdistrict.district.district,
                "subDistrict": subdistrict.sub_district,
                "zipcode": subdistrict.zipcode,
            }

            return success_response(res_data)
        else:
            return general_error_response("Lokasi anda tidak ditemukan")


class GrabPopulateLongFormData(APIView, StandardizedExceptionHandlerMixin):
    def get(self, request):
        try:
            customer = request.user.customer
            if 'step' in request.GET:
                page = request.GET['step']
            else:
                raise GrabLogicException('Enter Step Number.')

            application_service = GrabApplicationService()
            application_service.get_latest_application(customer)
            application_service.save_failed_latest_app_to_new_app(customer)
            response = application_service.get_application_details_long_form(customer, page)
            return success_response(response)
        except GrabLogicException as gle:
            return general_error_response(str(gle))


class GrabSubmitApplicationV2View(GrabStandardizedExceptionHandlerMixin, APIView):
    model_class = Application
    serializer_class = GrabApplicationV2Serializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):

        try:
            customer = request.user.customer
            serializer = self.serializer_class(data=request.data, src_customer_id=customer.id)
            serializer.is_valid(raise_exception=True)

            data = request.data
            result = GrabApplicationService().submit_grab_application(
                customer, serializer.validated_data, data, version=2
            )

            return success_response(result)
        except GrabLogicException as e:
            logger.info(
                {
                    "action": "GrabSubmitApplicationV2View",
                    "data": str(request.data),
                    "error": str(e),
                }
            )
            return general_error_response(str(e))
        except GrabApiException as e:
            return response_template(
                None, status=https_status_codes.HTTP_403_FORBIDDEN, message=[str(e)]
            )

    @grab_app_session
    def patch(self, request):
        try:
            customer = request.user.customer
            data = request.data

            serializer = self.serializer_class(
                data=request.data, src_customer_id=customer.id, is_update=True
            )
            serializer.is_valid(raise_exception=True)

            if 'step' in data:
                step = data['step']
            else:
                raise serializers.ValidationError({'step': 'Enter Step Number.'})

            data = request.data
            result = GrabApplicationService().update_grab_application(
                customer, serializer.validated_data, data, step
            )

            return success_response(result)

        except GrabLogicException as e:
            logger.info(
                {
                    "action": "GrabSubmitApplicationV2View",
                    "data": str(request.data),
                    "error": str(e),
                }
            )
            return custom_bad_request_response({"referral_code": str(e)})
        except GrabApiException as e:
            return response_template(
                None, status=https_status_codes.HTTP_403_FORBIDDEN, message=[str(e)]
            )


class GrabChangeBankAccountView(GrabStandardizedExceptionHandlerMixin, APIView):
    serializer_class = GrabChangeBankAccountSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY
    grab_change_bank_account_service = GrabChangeBankAccountService()

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        application = None
        try:
            application, _ = self.grab_change_bank_account_service.is_valid_application(
                data.get("application_id"), request.user.customer
            )
        except (GrabLogicException, GrabApiException) as err:
            return general_error_response(str(err))

        result = self.grab_change_bank_account_service.trigger_grab_name_bank_validation(
            application, data.get('bank_name'), data.get('bank_account_number')
        )
        return success_response(result)

    @grab_app_session
    def get(self, request):
        request_payload = {
            "name_bank_validation_id": request.GET.get("name_bank_validation_id"),
            "application_id": request.GET.get("application_id"),
        }
        serializer = GrabChangeBankAccountStatusSerializer(data=request_payload)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # check valid app
        application = None
        try:
            application, _ = self.grab_change_bank_account_service.is_valid_application(
                data.get("application_id"), request.user.customer
            )
        except (GrabLogicException, GrabApiException) as err:
            return general_error_response(str(err))

        # get status of validation
        name_bank_validation_id = data.get("name_bank_validation_id")
        try:
            validation_status_data = (
                self.grab_change_bank_account_service.get_name_bank_validation_status(
                    name_bank_validation_id, application.id
                )
            )
        except (GrabLogicException, GrabApiException) as err:
            return general_error_response(str(err))

        # do the rest if name bank validation is success
        if validation_status_data["validation_status"] == GrabBankValidationStatus.SUCCESS:
            try:
                is_success, err_msg = self.grab_change_bank_account_service.update_bank_application(
                    application, validation_status_data
                )

                if not is_success:
                    return general_error_response(err_msg)

                self.grab_change_bank_account_service.create_new_bank_destination(
                    request.user.customer
                )
            except (GrabLogicException, GrabApiException, IntegrityError) as err:
                return general_error_response(str(err))

            # trigger beneficiary
            if application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
                trigger_create_or_update_ayoconnect_beneficiary.delay(
                    customer_id=request.user.customer.id
                )

        return success_response(validation_status_data)


class GrabUserBankAccountDetailsView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            customer = request.user.customer
            result = GrabAccountPageService().get_user_bank_account_details(customer)
            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))
        except GrabApiException as e:
            return general_error_response(str(e))


class GrabValidatePromoCodeView(GrabStandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = GrabValidatePromoCodeSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def post(self, request):
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return error_response_web_app(errors=serializer.errors)

        data = serializer.validated_data

        try:
            token = request.META.get('HTTP_AUTHORIZATION', None)
            result = GrabCommonService.get_grab_promo_code_details(token, data)
            return success_response(result)

        except (GrabLogicException, GrabApiException, NameError) as e:
            if 'subtitle' not in str(e):
                e = {"title": str(e), "subtitle": ""}
            return error_response_web_app(str(e))


class GrabUserExperimentDetailsView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @grab_app_session
    def get(self, request):
        try:
            grab_customer_data = request.grab_customer_data
            if not grab_customer_data:
                raise GrabApiException("Grab customer data doesnt exist for this customer")
            result = GrabUserExperimentService().get_user_experiment_group(grab_customer_data.id)
            return success_response(result)
        except GrabLogicException as e:
            return general_error_response(str(e))
        except GrabApiException as e:
            return general_error_response(str(e))
