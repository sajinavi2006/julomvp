"""
This is revamped API using standardized response
"""
import logging
import time
from builtins import range, str
from datetime import timedelta

import pyotp
import semver
from django.conf import settings
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.status import HTTP_503_SERVICE_UNAVAILABLE
from rest_framework.views import APIView

from juloserver.apirevampv3.serializers import (
    BankAccountValidationSerializer,
    CashBackToGopaySerializer,
    GopayOtpRequestsSerializer,
    GopayOtpValidationSerializer,
    GopayPhoneNumberValidationSerializer,
)
from juloserver.cashback.constants import CASHBACK_FROZEN_MESSAGE, CashbackMethodName
from juloserver.cashback.services import is_cashback_method_active
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.exceptions import GopayInsufficientError, GopayServiceError
from juloserver.disbursement.services.gopay import GopayService
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import DuplicateCashbackTransaction
from juloserver.julo.models import (
    Application,
    Banner,
    CashbackTransferTransaction,
    MobileFeatureSetting,
    OtpRequest,
    StatusLabel,
)
from juloserver.julo.services import process_bank_account_validation
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tasks import send_sms_otp_token
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)

from .serializers import BannerSerializer

logger = logging.getLogger(__name__)


class StatusLabelsView(StandardizedExceptionHandlerMixin, APIView):
    model_class = StatusLabel

    def get(self, request):
        customer = request.user.customer
        applications = customer.application_set.regular_not_deletes()
        status_labels = []
        for application in applications:
            if application.status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
                status = application.loan.status
            else:
                status = application.status
            status_label = StatusLabel.objects.get_or_none(status=status)
            if status_label:
                if application.product_line:
                    product_name = application.product_line.product_line_type
                else:
                    product_name = None

                if hasattr(application, 'loan'):
                    loan_month_duration = application.loan.loan_duration
                else:
                    loan_month_duration = None
                status_label = {
                    'application_id': application.id,
                    'status_label': status_label.label_name,
                    'status_color': status_label.label_colour,
                    'product_name': product_name,
                    'loan_month_duration': loan_month_duration,
                    'apply_date': application.cdate,
                }
                status_labels.append(status_label)
            else:
                continue
        return success_response({'status_labels': status_labels})


class BankAccountValidationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = BankAccountValidationSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_data = serializer.validated_data
        application_id = request_data['application_id']
        name_in_bank = request_data['name_in_bank']
        bank_account_number = request_data['bank_account_number']
        _status = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
        application = Application.objects.get_or_none(
            pk=application_id,
            application_status_id=_status,
        )
        if not application:
            return general_error_response("Application not found")
        application.name_in_bank = name_in_bank
        application.bank_account_number = bank_account_number
        try:
            process_bank_account_validation(application)
            return success_response(None)
        except Exception as e:
            invalid_message = str(e)
            bank_account_invalid_reason = "Failed to add bank account"
            if bank_account_invalid_reason in invalid_message:
                invalid_message = NameBankValidationStatus.BANK_ACCOUNT_INVALID
            elif invalid_message is None:
                invalid_message = NameBankValidationStatus.NAME_INVALID
            return general_error_response(invalid_message)


class BannersView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        sentry_client = get_julo_sentry_client()

        today = timezone.now()
        banners_data = (
            Banner.objects.filter(is_active=True, is_deleted=False)
            .filter((Q(start_date__lte=today) & Q(end_date__gte=today)) | Q(is_permanent=True))
            .order_by('display_order')
        )

        setting_types = {
            1: {
                "type": "product",
                "model_data": {'var': 'application', 'field': 'product_line_id'},
            },
            2: {"type": "partner", "model_data": {'var': 'application', 'field': 'partner_id'}},
            3: {
                "type": "application_status",
                "model_data": {'var': 'application', 'field': 'application_status_id'},
            },
            4: {"type": "loan_status", "model_data": {'var': 'loan', 'field': 'loan_status_id'}},
            5: {"type": "due_date_payment", "model_data": {'var': 'payment', 'field': 'due_date'}},
            6: {
                "type": "payment_status",
                "model_data": {'var': 'payment', 'field': 'payment_status_id'},
            },
            7: {"type": "dpd_loan", "model_data": {'var': 'first_payment', 'field': 'due_date'}},
            8: {"type": "dpd_payment", "model_data": {'var': 'payment', 'field': 'due_date'}},
            9: {"type": "due_date_month", "model_data": {'var': 'payment', 'field': 'due_date'}},
            10: {"type": "can_reapply", "model_data": {'var': 'application', 'field': 'customer'}},
            11: {"type": "credit_score", "model_data": {'var': 'credit_score', 'field': 'score'}},
            12: {
                "type": "app_version",
                "model_data": {'var': 'application', 'field': 'app_version'},
            },
        }

        check_all = 'All'

        try:
            banners = []
            customer = request.user.customer
            application = customer.application_set.regular_not_deletes().last()
            loan = None
            credit_score = None

            if hasattr(application, 'loan'):
                loan = application.loan
                loan.payment_set.order_by('due_date').first()
                loan.payment_set.not_paid().filter(due_date__year=today.year).order_by(
                    'payment_number'
                ).first()

            if hasattr(application, 'creditscore'):
                credit_score = application.creditscore  # noqa

            for banner in banners_data:
                pass_validation = True

                if banner.bannersetting_set.count() == 0:
                    continue

                for x in range(1, len(setting_types) + 1):
                    if pass_validation:
                        skip_validation = False
                        setting_type = setting_types[x]['type']
                        model_data = setting_types[x]['model_data']

                        settings = banner.get_setting(setting_type)
                        if check_all in settings and not (setting_type == 'due_date_month'):
                            continue
                        if len(settings) > 0:
                            var_string = "{}.{}".format(model_data['var'], model_data['field'])
                            eval_var = eval(model_data['var'])

                            if hasattr(eval_var, model_data['field']):
                                eval_variable = eval(var_string)
                                if setting_type in 'due_date_payment':
                                    eval_variable = eval_variable.day

                                elif setting_type in ('dpd_loan', 'dpd_payment'):
                                    eval_variable = (today.date() - eval_variable).days
                                    if (eval_variable >= 365) and ('365' in settings):
                                        skip_validation = True

                                elif setting_type in 'can_reapply':
                                    eval_variable = eval_variable.can_reapply

                                elif setting_type in 'due_date_month':
                                    due_date_payment_settings = banner.get_setting(
                                        'due_date_payment'
                                    )
                                    if due_date_payment_settings:
                                        if (check_all in due_date_payment_settings) or (
                                            str(eval_variable.day) in due_date_payment_settings
                                        ):
                                            eval_variable = eval_variable.month
                                            skip_validation = check_all in settings

                                elif setting_type in 'app_version' and eval_variable:
                                    if semver.match(eval_variable, ">=%s" % settings[0]):
                                        skip_validation = True

                                if str(eval_variable) in settings or skip_validation:
                                    pass_validation = True

                                else:
                                    pass_validation = False

                            else:
                                pass_validation = False
                    else:
                        break

                if pass_validation:
                    banners.append(banner)

        except Exception as e:
            sentry_client.captureException()
            logger.error({'action': 'apirevampv3_banner', 'errors': str(e)})

        return success_response(BannerSerializer(banners, many=True).data)


class CashBackToGopay(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CashBackToGopaySerializer

    def post(self, request):
        gopay_enable = is_cashback_method_active(CashbackMethodName.GOPAY)
        if not gopay_enable:
            return general_error_response(
                'Pencairan cashback melalui metode ini untuk sementara tidak dapat dilakukan'
            )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_data = serializer.validated_data
        customer = request.user.customer
        if customer.is_cashback_freeze:
            return general_error_response(CASHBACK_FROZEN_MESSAGE)

        cashback_nominal = request_data['cashback_nominal']
        mobile_phone_number = request_data['mobile_phone_number']
        sentry_client = get_julo_sentry_client()
        try:
            gopay = GopayService()
            gopay.process_cashback_to_gopay(customer, cashback_nominal, mobile_phone_number)

            return success_response(None)
        except (GopayServiceError, DuplicateCashbackTransaction) as error:
            sentry_client.captureException()
            return general_error_response(str(error))
        except GopayInsufficientError as error:
            return general_error_response(str(error))


class GopayPhoneNumberChangeRequestOTP(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GopayOtpRequestsSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_data = serializer.validated_data
        phone = request_data['mobile_phone_number']
        mfs = MobileFeatureSetting.objects.get_or_none(feature_name='mobile_phone_1_gopay_otp')
        if not mfs or not mfs.is_active:
            message = 'Verifikasi kode tidak aktif'
            return Response(
                status=HTTP_503_SERVICE_UNAVAILABLE,
                data={"success": False, "errors": {message}, "data": None},
            )

        curr_time = timezone.localtime(timezone.now())
        otp_wait_seconds = mfs.parameters['wait_time_seconds']
        otp_resend_time = mfs.parameters['otp_resend_time']
        customer = request.user.customer
        postfixed_request_id = str(customer.id) + str(int(time.time()))
        application = (
            Application.objects.filter(customer=customer, mobile_phone_1=phone)
            .values_list('mobile_phone_1')
            .last()
        )
        if application is None:
            message = 'Nomor telepon belum terdaftar'
            return general_error_response(message)

        existing_otp = (
            OtpRequest.objects.filter(customer=customer, is_used=False, phone_number=phone)
            .order_by('id')
            .last()
        )
        create_new_otp = False if existing_otp and existing_otp.is_active is True else True
        if existing_otp and existing_otp.is_active:
            sms_history = existing_otp.sms_history
            prev_time = sms_history.cdate if sms_history else existing_otp.cdate
            resend_time = timezone.localtime(prev_time) + timedelta(seconds=otp_resend_time)
            if curr_time < resend_time:
                message = 'requested OTP less than resend time'
                return general_error_response(message)

        if create_new_otp:
            hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
            otp = str(hotp.at(int(postfixed_request_id)))
            otp_obj = OtpRequest.objects.create(
                customer=customer,
                request_id=postfixed_request_id,
                otp_token=otp,
                phone_number=phone,
            )
        else:
            otp = existing_otp.otp_token
            otp_obj = existing_otp

        context = {'otp_token': otp}
        text_message = render_to_string(
            'sms_otp_token_phone_number_gopay_change.txt', context=context
        )
        try:
            send_sms_otp_token.delay(phone, text_message, customer.id, otp_obj.id)
        except Exception as e:
            logger.error(
                {
                    "status": "gopay_phone_number_change_sms_not_sent",
                    "customer": customer.id,
                    "phone": phone,
                    "reason": str(e),
                }
            )
            message = 'Kode verifikasi belum dapat dikirim'
            return general_error_response(message)

        data = {
            "message": "OTP sudah dikirim",
            "resend_time": otp_resend_time,
            "expired_time": otp_wait_seconds,
        }
        return success_response(data)


class GopayValidateOTPView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GopayOtpValidationSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_data = serializer.validated_data
        otp_token = request_data['otp_token']
        customer = request.user.customer
        otp_data = (
            OtpRequest.objects.filter(otp_token=otp_token, customer=customer, is_used=False)
            .order_by('id')
            .last()
        )
        if not otp_data:
            logger.error(
                {
                    "status": "gopay_otp_token_not_found",
                    "otp_token": otp_token,
                    "customer": customer.id,
                }
            )
            message = 'Kode verifikasi belum terdaftar'
            return general_error_response(message)

        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        valid_token = hotp.verify(otp_token, int(otp_data.request_id))
        if not valid_token:
            logger.error(
                {
                    "status": "gopay_invalid_token",
                    "otp_token": otp_token,
                    "otp_request": otp_data.id,
                    "customer": customer.id,
                }
            )
            message = 'Kode verifikasi tidak valid'
            return general_error_response(message)

        if not otp_data.is_active:
            logger.error(
                {
                    "status": "gopay_otp_token_expired",
                    "otp_token": otp_token,
                    "otp_request": otp_data.id,
                    "customer": customer.id,
                }
            )
            message = 'Kode verifikasi kadaluarsa'
            return general_error_response(message)

        otp_data.is_used = True
        otp_data.save()
        data = {'token': otp_data.customer.user.auth_expiry_token.key}
        return success_response(data)


class GopayUpdatePhoneNumberView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = GopayPhoneNumberValidationSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_data = serializer.validated_data
        new_phone_number = request_data['new_phone_number']
        customer = request.user.customer
        transaction = (
            CashbackTransferTransaction.objects.filter(customer=customer).values_list('id').last()
        )
        if transaction is None:
            message = 'Nomor telepon belum terdaftar'
            return general_error_response(message)

        CashbackTransferTransaction.objects.filter(customer=customer, id=transaction[0]).update(
            bank_number=new_phone_number
        )
        data = {"message": "Phone number updated successfully"}
        return success_response(data)
