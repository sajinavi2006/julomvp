import logging
import datetime
import json

import pyotp
import time
import pytz
from builtins import str
from rest_framework.parsers import FormParser
from xml.etree import ElementTree as ET
from typing import Any
from dateutil.relativedelta import relativedelta
from urllib.parse import urlparse
import pytz

from django.conf import settings
from django.db import transaction
from django.contrib.auth.models import User
from django.forms import model_to_dict
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_401_UNAUTHORIZED,
    HTTP_402_PAYMENT_REQUIRED,
    HTTP_409_CONFLICT,
)
from rest_framework_xml.parsers import XMLParser
from rest_framework_xml.renderers import XMLRenderer
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from django.views.decorators.csrf import csrf_exempt

from juloserver.account.services.repayment import (
    get_account_from_payment_method
)
from juloserver.account_payment.services.faspay import (
    faspay_payment_inquiry_account,
    faspay_payment_process_account,
    faspay_snap_payment_inquiry_account,
)
from juloserver.disbursement.services.gopay import (
    GopayConst,
    GopayService,
)
from juloserver.integapiv1.authentication import (
    CommProxyAuthentication,
    IsSourceAuthenticated,
)
from juloserver.julo.constants import (
    VoiceTypeStatus,
    VendorConst,
)
from juloserver.julo.models import (
    AutoDialerRecord,
    CashbackTransferTransaction,
    PaymentMethod,
    Skiptrace,
    SkiptraceHistory,
    SmsHistory,
    Disbursement,
    PrimoDialerRecord,
    SepulsaTransaction,
    VoiceCallRecord,
    Payment,
    Autodialer122Queue,
    NexmoAutocallHistory,
    PredictiveMissedCall,
    WhatsappHistory,
    PaybackTransaction,
    Partner,
    OtpRequest,
    Loan,
    FeatureSetting,
    CommsProviderLookup,
)
from juloserver.paylater.models import Statement
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.services import (
    get_oldest_payment_due,
    action_cashback_sepulsa_transaction,
    faspay_payment_inquiry_loan,
    faspay_payment_inquiry_loc,
    faspay_payment_process_loan,
    faspay_payment_process_loc,
    faspay_payment_inquiry_statement,
    faspay_snap_payment_inquiry_loan,
    faspay_snap_payment_inquiry_statement,
    faspay_snap_payment_inquiry_loc,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.exceptions import JuloException, EmailNotSent

import time
from juloserver.julo.utils import (
    generate_sha1_md5,
    format_e164_indo_phone_number,
    display_rupiah,
    decrypt_order_id_sepulsa,
    generate_base64,
)
from .exceptions import TransferflowNotFound


from juloserver.julo.services import update_skiptrace_score
from juloserver.julo.services import process_application_status_change
from juloserver.julo.services import primo_update_skiptrace
from juloserver.julo.services2.sepulsa import SepulsaService
from juloserver.julo.services2.xendit import XenditService
from juloserver.julo.services2.xfers import XfersService
from juloserver.julo.services2.voice import get_voice_template, get_covid_campaign_voice_template
from juloserver.julo.services2.payment_method import get_active_loan
from juloserver.julo.services2.primo import primo_locked_app, primo_unlocked_app
from juloserver.julo.services2.primo import PrimoLeadStatus
from juloserver.julo.services2.primo import process_callback_primo_payment
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.clients import get_julo_sms_client
from juloserver.integapiv1.serializers import (
    CallCustomerAiRudderRequestSerializer,
    CallCustomerCootekRequestSerializer,
    CallCustomerNexmoRequestSerializer,
    PaymentNotificationSerializer,
    AyoconnectDisbursementCallbackSerializer,
)
from juloserver.integapiv1.serializers import PaymentInquirySerializer
from juloserver.integapiv1.serializers import SepulsaTransactionSerializer
from juloserver.integapiv1.serializers import (
    VoiceCallbackResultSerializer,
    VoiceCallRecordingSerializer,
    BeneficiaryCallbackSuccessSerializer,
    BeneficiaryCallbackUnSuccessSerializer,
    SnapBcaInquiryBillsSerializer,
    SnapBcaPaymentFlagSerializer,
    SnapBcaAccessTokenSerializer,
    SnapFaspayInquiryBillsSerializer,
    SnapFaspayPaymentFlagSerializer,
)

from juloserver.integapiv1.services import (
    authenticate_bca_request,
    bca_process_payment,
    generate_description,
    get_bca_payment_bill,
    get_parsed_bca_payload,
    process_assign_agent,
    validate_bca_inquiry_payload,
    validate_bca_payment_payload,
    create_faspay_payback,
    AyoconnectBeneficiaryCallbackService,
    process_inquiry_for_j1,
    process_inquiry_for_escrow,
    authenticate_snap_request,
    process_inquiry_for_mtl_loan,
    get_snap_expiry_token,
    is_expired_snap_token,
    generate_snap_expiry_token,
    is_payment_method_prohibited,
)
from juloserver.integapiv1.security import FaspaySnapAuthentication, APIUnauthorizedError

from juloserver.disbursement.clients import get_bca_client
from juloserver.line_of_credit.services import LineOfCreditPurchaseService
from juloserver.integapiv1.tasks import send_sms_async
from juloserver.ovo.constants import OvoConst, OvoTransactionStatus
from juloserver.ovo.models import OvoRepaymentTransaction
from juloserver.monitors.services import get_channel_name_slack_for_payment_problem
from juloserver.payback.services.payback import (
    create_pbt_status_history,
    check_payment_method_vendor,
)
from juloserver.integapiv1.constants import (
    BcaConst,
    EXPIRY_TIME_TOKEN_BCA_SNAP,
    SnapInquiryResponseCodeAndMessage,
    BcaSnapPaymentResponseCodeAndMessage,
    FaspaySnapInquiryResponseCodeAndMessage,
    SnapTokenResponseCodeAndMessage,
    SnapStatus,
    SnapReasonMultilanguage,
    ErrorDetail,
    SnapVendorChoices,
    FaspaySnapPaymentResponseCodeAndMessage,
    MINIMUM_TRANSFER_AMOUNT,
)
from .tasks2.callback_tasks import (
    update_voice_call_record,
    store_voice_recording_data,
)
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.services2.voice import (
    get_covid_campaign_voice_template,
    get_voice_template,
)
from juloserver.julo.services2.xendit import XenditService
from juloserver.julo.services2.xfers import XfersService
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.utils import (
    decrypt_order_id_sepulsa,
    display_rupiah,
    generate_base64,
    generate_sha1_md5,
)
from juloserver.line_of_credit.services import LineOfCreditPurchaseService
from juloserver.account_payment.models import AccountPayment
from juloserver.loan_refinancing.services.loan_related import (
    get_loan_refinancing_request_info,
    check_eligibility_of_loan_refinancing,
    activate_loan_refinancing,
    get_unpaid_payments,
    regenerate_loan_refinancing_offer,
)
from juloserver.loan_refinancing.services.refinancing_product_related import (
    get_covid_loan_refinancing_request,
    check_eligibility_of_covid_loan_refinancing,
    CovidLoanRefinancing,
)
from django.template.loader import render_to_string
from juloserver.monitors.notifications import notify_failure
from juloserver.ovo.constants import (
    OvoPaymentStatus,
    OvoTransactionStatus,
)
from juloserver.ovo.models import OvoRepaymentTransaction
from juloserver.ovo.services.ovo_push2pay_services import store_transaction_data_history
from juloserver.payback.constants import Messages
from juloserver.payback.services.payback import create_pbt_status_history
from juloserver.paylater.models import Statement
from juloserver.rentee.services import get_deposit_loan
from juloserver.julo.banks import BankCodes
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.account_payment.services.bca import get_snap_bca_rentee_deposit_bill
from juloserver.integapiv1.models import EscrowPaymentMethod

from juloserver.standardized_api_response.utils import (
    success_response,
    not_found_response,
    general_error_response,
)

from juloserver.disbursement.tasks import process_callback_from_ayoconnect
from juloserver.integapiv1.utils import convert_camel_to_snake
from juloserver.grab.models import PaymentGatewayTransaction
from juloserver.integapiv1.utils import verify_asymmetric_signature
from juloserver.julo.services2 import get_redis_client
from juloserver.streamlined_communication.tasks import (
    evaluate_sms_reachability,
    sms_after_robocall_experiment_trigger,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2
from juloserver.streamlined_communication.models import SmsVendorRequest, CommsCampaignSmsHistory
from juloserver.loyalty.services.point_redeem_services import (
    get_loyalty_gopay_transfer_trx,
    process_callback_gopay_transfer,
    check_and_refunded_transfer_dana
)
from juloserver.nexmo.tasks import process_call_customer_via_nexmo
from juloserver.pii_vault.repayment.services import pii_lookup
from juloserver.minisquad.constants import DialerSystemConst
from juloserver.minisquad.models import DialerTask
from juloserver.integapiv1.utils import validate_datetime_within_10_minutes
from juloserver.payback.tasks.payback_tasks import store_payback_callback_log

logger = logging.getLogger(__name__)
xendit_service = XenditService()
sentry_client = get_julo_sentry_client()


class LoggedResponse(Response):
    def __init__(self, **kwargs):
        super(LoggedResponse, self).__init__(**kwargs)
        kwargs['http_status_code'] = self.status_code
        logger.info(kwargs)


class SmsDeliveryCallbackView(APIView):
    """
    Nexmo/Vonage SMS Callback API.
    """
    permission_classes = (AllowAny,)

    def get(self, request, format=None):
        message_id = request.query_params.get('messageId', None)
        if message_id is None:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "messageId": ["This field is required"]
                })

        SmsVendorRequest.objects.create(
            vendor_identifier=message_id,
            phone_number=request.query_params.get('msisdn'),
            comms_provider_lookup_id=CommsProviderLookup.objects.get(
                provider_name=VendorConst.NEXMO.capitalize(),
            ).id,
            payload=dict(request.query_params.lists()),
        )

        status = request.query_params.get('status', None)
        if status is None:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "status": ["This field is required"]
                })

        delivery_error_code = request.query_params.get('err-code', None)
        delivery_error_code = (
            int(delivery_error_code) if delivery_error_code else delivery_error_code
        )
        if delivery_error_code is None:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "err-code": ["This field is required"]
                })

        sms_history = SmsHistory.objects.filter(message_id=message_id).last()
        comms_campaign_sms_history = None
        if sms_history is None:
            comms_campaign_sms_history = CommsCampaignSmsHistory.objects.filter(
                message_id=message_id
            ).last()
            if comms_campaign_sms_history is None:
                return Response(
                    status=HTTP_404_NOT_FOUND, data={"error": f"message_id={message_id} not found"}
                )

        sms_history_to_update = sms_history or comms_campaign_sms_history
        sms_history_to_update.status = status
        sms_history_to_update.delivery_error_code = delivery_error_code
        sms_history_to_update.save()
        evaluate_sms_reachability.delay(
            str(sms_history.to_mobile_phone), VendorConst.NEXMO, sms_history_to_update.customer_id
        )

        if status == 'delivered':
            otp_request = OtpRequest.objects.filter(sms_history_id=sms_history.id)
            otp_request.update(reported_delivered_time=datetime.datetime.now())

        if delivery_error_code != 0:
            logger.warn({
                'message_id': message_id,
                'status': status,
                'delivery_error_code': delivery_error_code
            })

        return LoggedResponse(
            data={
                'sms_history': sms_history_to_update.id,
                'message_id': sms_history_to_update.message_id,
                'status': sms_history_to_update.status,
            }
        )


class WhatsappDeliveryCallbackView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        data = request.data

        if data["status"] is None:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "error": ["The status field is required"]
                })

        wa_history = WhatsappHistory.objects.get_or_none(xid=data["clientMessageId"])
        if wa_history is None:
            return LoggedResponse(
                status=HTTP_404_NOT_FOUND,
                data={
                    "error": "message xid=%s not found" % data["clientMessageId"]
                })

        wa_history.umid = data["umid"]
        wa_history.status = data["status"]
        wa_history.error = data["error"]
        wa_history.save()

        return LoggedResponse(data={
            'wa_history': wa_history.id,
            'status': wa_history.status
        })


class RoboCallEventCallbackView(APIView):
    """endpoint for robocall"""
    permission_classes = (AllowAny,)

    def post(self, request):

        # validate data from post
        # save data as auto dialer record
        # query skiptrace based on data
        # save a new skip trace history
        # skiptrace = update_skiptrace_score(skiptrace, data['start_ts'])
        data = request.data

        logger.info({
            'call_id': data['callid'],
            'skiptrace_id': data['skiptraceid'],
            'time_of_call': data['calltime'],
            'status': data['callstatus'],
            'duration': data['duration'],
            'attempt_number': data['attempt'],
        })

        call_id = data['callid']
        skiptrace_id = data['skiptraceid']
        time_of_call = data['calltime']
        status = data['callstatus']
        duration = data['duration']
        attempt_number = data['attempt']

        skiptrace = Skiptrace.objects.filter(id=skiptrace_id).get()
        autodialer_record_entry = AutoDialerRecord.objects.filter(skiptrace=skiptrace).last()
        autodialer_record_entry.call_id = call_id
        autodialer_record_entry.time_of_call = time_of_call
        autodialer_record_entry.call_status = status
        if duration == '':
            duration = 0
        autodialer_record_entry.call_duration = duration
        autodialer_record_entry.attempt_number = attempt_number
        autodialer_record_entry.save()

        time_of_call_datetime = datetime.datetime.strptime(time_of_call, "%Y-%m-%d %H:%M:%S")
        duration_datetime = datetime.datetime.strptime(
            str(datetime.date.today()) + ' ' + str(duration), "%Y-%m-%d %S")
        time_finish_datetime = time_of_call_datetime + \
                               datetime.timedelta(seconds=duration_datetime.second)

        if status == 'ANSWER':
            SkiptraceHistory.objects.create(start_ts=time_of_call_datetime,
                                            end_ts=time_finish_datetime,
                                            agent_name='robocall',
                                            skiptrace_id=skiptrace_id,
                                            application_id=skiptrace.application_id,
                                            application_status=skiptrace.application.status,
                                            loan_id=skiptrace.application.loan.id,
                                            loan_status=skiptrace.application.loan.status,
                                            payment_id=autodialer_record_entry.payment.id,
                                            payment_status= \
                                                autodialer_record_entry.payment.payment_status_id,
                                            call_result_id=6,
                                            )
        elif status == 'BUSY':
            SkiptraceHistory.objects.create(start_ts=time_of_call_datetime,
                                            end_ts=time_finish_datetime,
                                            agent_name='robocall',
                                            skiptrace_id=skiptrace_id,
                                            application_id=skiptrace.application_id,
                                            application_status=skiptrace.application.status,
                                            loan_id=skiptrace.application.loan.id,
                                            loan_status=skiptrace.application.loan.status,
                                            payment_id=autodialer_record_entry.payment.id,
                                            payment_status= \
                                                autodialer_record_entry.payment.payment_status_id,
                                            call_result_id=3,
                                            )
        elif status == 'INACTIVE':
            SkiptraceHistory.objects.create(start_ts=time_of_call_datetime,
                                            end_ts=time_finish_datetime,
                                            agent_name='robocall',
                                            skiptrace_id=skiptrace_id,
                                            application_id=skiptrace.application_id,
                                            application_status=skiptrace.application.status,
                                            loan_id=skiptrace.application.loan.id,
                                            loan_status=skiptrace.application.loan.status,
                                            payment_id=autodialer_record_entry.payment.id,
                                            payment_status= \
                                                autodialer_record_entry.payment.payment_status_id,
                                            call_result_id=2,
                                            )

        update_skiptrace_score(skiptrace, time_of_call_datetime)

        return LoggedResponse(data={
            'call_id': call_id,
            'skiptrace_id': skiptrace_id,
            'time_of_call': time_of_call,
            'status': status,
            'duration': duration,
            'attempt_number': attempt_number,
        })


class XenditNameValidateEventCallbackView(APIView):
    """Endpoint for Xendit Name Validate callback"""
    permission_classes = (AllowAny,)

    def post(self, request):

        data = request.data
        logger.info(data)

        validate_status = data['status']
        validation_id = data['id']

        cashback_xendit = CashbackTransferTransaction.objects.get_or_none(
            validation_id=validation_id)
        if cashback_xendit:
            try:
                logger.info({
                    'action': 'process_update_validate_cashback',
                    'validation_id': data['id'],
                    'application_id': cashback_xendit.application.id,
                    'cashback_xendit_transaction_id': cashback_xendit.id
                })
                xendit_service.process_update_validate_cashback(data, cashback_xendit)
            except Exception as e:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                return LoggedResponse(data={
                    'bank_code': data['bank_code'],
                    'bank_account_number': data['bank_account_number'],
                    'status': data['status'],
                    'id': data['id'],
                    'updated': data['updated'],
                })

        disbursement = Disbursement.objects.get_or_none(validation_id=validation_id)
        if disbursement:
            try:
                logger.info({
                    'action': 'process_update_validate_disbursement',
                    'validation_id': data['id'],
                    'application_id': disbursement.loan.application.id,
                    'disbursement_id': disbursement.id
                })
                xendit_service.process_update_validate_disbursement(data, disbursement)
            except Exception as e:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                return LoggedResponse(data={
                    'bank_code': data['bank_code'],
                    'bank_account_number': data['bank_account_number'],
                    'status': data['status'],
                    'id': data['id'],
                    'updated': data['updated'],
                })

        return LoggedResponse(data={
            'bank_code': data['bank_code'],
            'bank_account_number': data['bank_account_number'],
            'status': data['status'],
            'id': data['id'],
            'updated': data['updated'],
        })


class XenditDisburseEventCallbackView(APIView):
    """Endpoint for Xendit Disburse callback"""
    permission_classes = (AllowAny,)

    def post(self, request):
        if request.META['HTTP_X_CALLBACK_TOKEN'] != settings.XENDIT_DISBURSEMENT_VALIDATION_TOKEN:
            try:
                raise JuloException("Failed xendit validation token")
            except JuloException:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
            return LoggedResponse()

        data = request.data
        logger.info(data)

        disburse_id = data['id']
        cashback_xendit = CashbackTransferTransaction.objects.get_or_none(
            transfer_id=disburse_id)
        if cashback_xendit:
            try:
                xendit_service.process_update_cashback_xendit(data, cashback_xendit)
            except Exception as e:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                return LoggedResponse(data={
                    'bank_code': data['bank_code'],
                    'account_holder_name': data['account_holder_name'],
                    'status': data['status'],
                    'id': data['id'],
                    'updated': data['updated'],
                })

        disbursement = Disbursement.objects.get_or_none(disburse_id=disburse_id)
        if disbursement:
            try:
                xendit_service.process_update_disbursement(data, disbursement)
            except Exception as e:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                return LoggedResponse(data={
                    'bank_code': data['bank_code'],
                    'account_holder_name': data['account_holder_name'],
                    'status': data['status'],
                    'id': data['id'],
                    'updated': data['updated'],
                })

        return LoggedResponse(data={
            'bank_code': data['bank_code'],
            'account_holder_name': data['account_holder_name'],
            'status': data['status'],
            'id': data['id'],
            'updated': data['updated'],
        })


class AyoconnectDisbursementCallbackApiView(APIView):
    permission_classes = (AllowAny,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)
    serializer_class = AyoconnectDisbursementCallbackSerializer

    def post(self, request):
        logger.info({
            "action": "AyoconnectDisbursementCallbackApiView.post",
            "payload": request.data
        })
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        response_dict = {
            'success': True,
            'data': None,
            'errors': []
        }
        details = validated_data.get('details')
        if not details:
            response_dict['success'] = False
            response_dict['errors'] = ["details is missing"]
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data=response_dict
            )
        a_correlation_id = details.get("A-Correlation-ID")
        payment_gateway_transaction = PaymentGatewayTransaction.objects.filter(
            correlation_id=a_correlation_id
        ).exists()
        if not payment_gateway_transaction:
            response_dict['success'] = False
            response_dict['errors'] = ["disbursement not found"]
            return LoggedResponse(
                status=HTTP_404_NOT_FOUND,
                data=response_dict
            )
        process_callback_from_ayoconnect.delay(
            data=validated_data
        )
        return LoggedResponse(data=response_dict, status=HTTP_200_OK)


class FaspayTransactionApiView(APIView):
    """This endpoint is a callback for faspay to check customers va everytime
    customer do payment to assigned virtual account, faspay will check the va
    by hitting this endpoint.
    """
    permission_classes = (AllowAny, )
    parser = XMLParser
    parser.media_type = "text/xml"
    parser_classes = (parser,)
    renderer = XMLRenderer
    renderer.root_tag_name = 'faspay'
    renderer.media_type = 'text/xml'
    renderer_classes = (renderer,)

    def get(self, request, va, signature):
        self._pre_log_request(request, va)
        query_filter = {'virtual_account': va}
        response = pii_lookup(va)
        if response:
            query_filter = {'virtual_account_tokenized__in': response}
        payment_method = PaymentMethod.objects.filter(**query_filter).first()
        if is_payment_method_prohibited(payment_method):
            logger.warning(
                {
                    'action': 'juloserver.integapiv1.views.FaspayTransactionApiView',
                    'va': va,
                    'message': 'prohibit va',
                }
            )
            return LoggedResponse(
                data={
                    'response': 'VA Static Response',
                    'response_code': '01',
                    'response_desc': 'va not found',
                }
            )
        if payment_method is None:
            return LoggedResponse(
                data={
                    'response': 'VA Static Response',
                    'response_code': '01',
                    'response_desc': 'va not found'
                }
            )

        faspay_new_user_id = settings.FASPAY_USER_ID_FOR_VA_PHONE_NUMBER
        faspay_new_password = settings.FASPAY_PASSWORD_FOR_VA_PHONE_NUMBER
        faspay_old_user_id = settings.FASPAY_USER_ID
        faspay_old_password = settings.FASPAY_PASSWORD

        signature_old_keystring = '{}{}{}'.format(faspay_old_user_id,
                                                  faspay_old_password,
                                                  va)

        signature_new_keystring = '{}{}{}'.format(faspay_new_user_id,
                                                  faspay_new_password,
                                                  va)

        julo_old_signature = generate_sha1_md5(signature_old_keystring)
        julo_new_signature = generate_sha1_md5(signature_new_keystring)

        if signature not in (julo_old_signature, julo_new_signature):
            return LoggedResponse(
                data={
                    'response': 'VA Static Response',
                    'response_code': '01',
                    'response_desc': 'unauthorize signature'
                }
            )
        loan = get_deposit_loan(payment_method.customer) or get_active_loan(payment_method)

        line_of_credit = payment_method.line_of_credit

        account = get_account_from_payment_method(payment_method)

        response_data = {}

        if account:
            response_data = faspay_payment_inquiry_account(account, payment_method)
        else:
            if loan is not None:
                if loan.__class__ is Loan:
                    response_data = faspay_payment_inquiry_loan(loan, payment_method)
                elif loan.__class__ is Statement:
                    response_data = faspay_payment_inquiry_statement(loan, payment_method)

            if line_of_credit is not None:
                response_data = faspay_payment_inquiry_loc(line_of_credit, payment_method)

        inquiry_type = request.GET.get('type', None)

        if inquiry_type == "inquiry":
            return LoggedResponse(data=response_data)

        if inquiry_type == "payment":
            serializer = PaymentInquirySerializer(data=request.GET)
            if serializer.is_valid():
                data = serializer.data
                payback_transaction = PaybackTransaction.objects.get_or_none(transaction_id=data['trx_uid'])
                if not payback_transaction:
                    create_faspay_payback(data['trx_uid'],data['amount'],payment_method)

                elif payback_transaction.is_processed:
                    response_data.update({
                        'response': 'VA Static Response',
                        'response_code': '01',
                        'response_desc': 'Transaction Id already used'
                    })

                return LoggedResponse(data=response_data)
            else:
                return LoggedResponse(
                    data={
                        'response': 'VA Static Response',
                        'response_code': '01',
                        'response_desc': serializer.errors
                    }
                )

        elif inquiry_type is None:
            return LoggedResponse(
                data={
                    'response': 'VA Static Response',
                    'response_code': '01',
                    'response_desc': 'type is None'
                }
            )
        else:
            return LoggedResponse(
                data={
                    'response': 'VA Static Response',
                    'response_code': '01',
                    'response_desc': 'type invalid'
                }
            )

    def _pre_log_request(
        self,
        request: Request,
        virtual_account,
    ) -> None:
        logger.info(
            {
                "action": "juloserver.integapiv1.views.FaspayTransactionApiView",
                "action_group": "payment_api_requests",
                "endpoint": request.get_full_path(),
                "method": request.method,
                "virtual_account": virtual_account,
                "transaction_id": request.data.get('trx_uid', ''),
            }
        )


class FaspayPaymentNotificationView(APIView):
    """This endpoint is a callback for faspay to check customers va everytime
    payment to Notification.
    """

    permission_classes = (AllowAny, )
    parser = XMLParser
    parser.media_type = "text/xml"
    parser_classes = [parser, FormParser]
    renderer = XMLRenderer
    renderer.root_tag_name = 'faspay'
    renderer.media_type = "text/xml"
    renderer_classes = (renderer,)

    def post(self, request):
        self._pre_log_request(request)
        request_data = request.data

        if request.content_type == 'application/x-www-form-urlencoded':
            parser = XMLParser()
            content = request_data['<?xml version']
            content = '<?xml version=' + content
            request_data = parser._xml_convert(ET.fromstring(content))

        serializer = PaymentNotificationSerializer(data=request_data)

        if not serializer.is_valid():
            return LoggedResponse(
                data={
                    'response': 'Payment Notification',
                    'response_code': '01',
                    'response_desc': serializer.errors,
                }
            )

        data = serializer.data

        logger.info(
            {
                'action': 'juloserver.integapiv1.views.FaspayPaymentNotificationView',
                'data': data,
            }
        )
        query_filter = {'virtual_account': data['bill_no']}
        response_pii_lookup = pii_lookup(data['bill_no'])
        if response_pii_lookup:
            query_filter = {'virtual_account_tokenized__in': response_pii_lookup}
        payment_method = (
            PaymentMethod.objects.select_related('customer').filter(**query_filter).first()
        )
        ovo_repayment_transaction = None

        if not payment_method:
            with transaction.atomic():
                ovo_repayment_transaction = OvoRepaymentTransaction.objects.select_for_update().filter(
                    transaction_id=data['trx_id']
                ).last()
                if ovo_repayment_transaction:
                    if 'channel_resp_code' in data:
                        status_description = 'intermittent or timeout on faspay to ovo'

                        if data['channel_resp_code']:
                            status_description = OvoPaymentStatus.RESPONSE_DESCRIPTION[str(
                                data['channel_resp_code'])]

                        ovo_repayment_transaction.status_description = status_description
                        ovo_repayment_transaction.status = 'PAYMENT_FAILED'
                        ovo_repayment_transaction.save()

                    payment_method = (
                        PaymentMethod.objects.select_related('customer')\
                            .filter(customer_id=\
                                ovo_repayment_transaction.account_payment_xid.account.customer_id,
                                payment_method_name='OVO'
                            ).last()
                    )

        if payment_method is None:
            return LoggedResponse(
                data={
                    'response': 'Payment Notification',
                    'response_code': '01',
                    'response_desc': 'va not found'
                }
            )

        faspay_bni_user_id = settings.FASPAY_USER_ID_BNI_VA
        faspay_bni_password = settings.FASPAY_PASSWORD_BNI_VA
        faspay_new_user_id = settings.FASPAY_USER_ID_FOR_VA_PHONE_NUMBER
        faspay_new_password = settings.FASPAY_PASSWORD_FOR_VA_PHONE_NUMBER
        faspay_old_user_id = settings.FASPAY_USER_ID
        faspay_old_password = settings.FASPAY_PASSWORD

        signature_old_keystring = '{}{}{}{}'.format(faspay_old_user_id,
                                                    faspay_old_password,
                                                    data['bill_no'],
                                                    data['payment_status_code'])

        signature_new_keystring = '{}{}{}{}'.format(
            faspay_new_user_id, faspay_new_password, data['bill_no'], data['payment_status_code']
        )

        signature_bni_keystring = '{}{}{}{}'.format(
            faspay_bni_user_id,
            faspay_bni_password,
            data['bill_no'],
            data['payment_status_code'],
        )

        julo_old_signature = generate_sha1_md5(signature_old_keystring)
        julo_new_signature = generate_sha1_md5(signature_new_keystring)
        julo_bni_signature = generate_sha1_md5(signature_bni_keystring)

        if data['signature'] not in (
            julo_old_signature,
            julo_new_signature,
            julo_bni_signature,
        ):
            return LoggedResponse(
                data={
                    'response': 'Payment Notification',
                    'response_code': '01',
                    'response_desc': 'unauthorize signature'
                }
            )
        query_filter = {'virtual_account': data['bill_no'], 'bank_code': BankCodes.BNI}
        response_pii_lookup = pii_lookup(data['bill_no'])
        if response_pii_lookup:
            query_filter = {
                'virtual_account_tokenized__in': response_pii_lookup,
                'bank_code': BankCodes.BNI,
            }
        bni_payment_method = PaymentMethod.objects.filter(**query_filter).last()

        if bni_payment_method:
            loan = get_deposit_loan(payment_method.customer) or get_active_loan(payment_method)
            if not loan:
                msg = "There's error when hit API Faspay: Loan with customer id: {} has no remaining loan".format(
                    bni_payment_method.customer.id)
                channel_name = get_channel_name_slack_for_payment_problem()
                notify_failure(msg, channel=channel_name)
                return LoggedResponse(
                    data={
                        'response': 'Payment Notification',
                        'response_code': '01',
                        'response_desc': 'Loan not found',
                    }
                )
            payment = get_oldest_payment_due(loan)
            PaybackTransaction.objects.create(
                is_processed=False,
                customer=bni_payment_method.customer,
                payback_service='faspay',
                transaction_id=data['trx_id'],
                amount=data['payment_total'],
                account=bni_payment_method.customer.account,
                payment_method=bni_payment_method,
                payment=payment,
                loan=loan,
                virtual_account=data['bill_no'],
            )

        faspay = PaybackTransaction.objects.filter(transaction_id=data['trx_id']).last()

        if faspay is None:
            faspay = create_faspay_payback(data['trx_id'],data['payment_total'],payment_method)

        elif faspay.is_processed:
            return LoggedResponse(
                data={
                    'response': 'Payment Notification',
                    'response_code': '01',
                    'response_desc': 'Transaction Id already used'
                }
            )

        if data['payment_status_code'] == 2:
            note = 'payment with va %s %s' % (
                payment_method.virtual_account, payment_method.payment_method_name)
            process_payment = False

            loan = get_active_loan(payment_method)
            line_of_credit = payment_method.line_of_credit
            account = get_account_from_payment_method(payment_method)

            if account:
                process_payment = faspay_payment_process_account(faspay, data, note)
                if process_payment:
                    if ovo_repayment_transaction:
                        current_repayment_transaction = model_to_dict(ovo_repayment_transaction)
                        with transaction.atomic():
                            ovo_repayment_transaction = OvoRepaymentTransaction.objects.select_for_update().get(
                                pk=ovo_repayment_transaction.id)
                            input_params = dict(status=OvoTransactionStatus.SUCCESS)
                            ovo_repayment_transaction.update_safely(**input_params)
                            store_transaction_data_history(input_params, ovo_repayment_transaction,
                                                        current_repayment_transaction)
                    return LoggedResponse(
                        data={
                            'response': 'Payment Notification',
                            'trx_id': data['trx_id'],
                            'merchant_id': data['merchant_id'],
                            'bill_no': payment_method.virtual_account,
                            'response_code': '00',
                            'response_desc': 'Sukses',
                            'response_date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )

            if loan is not None:
                if loan.__class__ is Loan:
                    payment = loan.payment_set.filter(
                        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)\
                        .order_by('payment_number')\
                        .exclude(is_restructured=True)\
                        .first()
                    payment_date = datetime.datetime.strptime(data['payment_date'], '%Y-%m-%d %H:%M:%S').date()

                    loan_refinancing_request = get_loan_refinancing_request_info(loan)
                    covid_loan_refinancing_request = get_covid_loan_refinancing_request(loan)

                    if loan_refinancing_request and check_eligibility_of_loan_refinancing(
                            loan_refinancing_request, payment_date):
                        if loan_refinancing_request.new_installment != faspay.amount:
                            return LoggedResponse(
                                data={
                                    'response': 'Payment Notification',
                                    'response_code': '13',
                                    'response_desc': 'Payment amount does not match'
                                }, status=HTTP_400_BAD_REQUEST
                            )
                        else:
                            is_loan_refinancing_active = activate_loan_refinancing(
                                payment, loan_refinancing_request)

                            if not is_loan_refinancing_active:
                                return LoggedResponse(
                                    data={
                                        'response': 'Payment Notification',
                                        'response_code': '96',
                                        'response_desc': 'Failed to activate loan refinancing'
                                    }, status=HTTP_500_INTERNAL_SERVER_ERROR
                                ),
                            payment = get_unpaid_payments(loan, order_by='payment_number')[0]
                    elif covid_loan_refinancing_request and \
                            check_eligibility_of_covid_loan_refinancing(
                                covid_loan_refinancing_request, payment_date, faspay.amount):
                        covid_lf_factory = CovidLoanRefinancing(
                            payment, covid_loan_refinancing_request)

                        is_covid_loan_refinancing_active = covid_lf_factory.activate()

                        if not is_covid_loan_refinancing_active:
                            return LoggedResponse(
                                data={
                                    'response': 'Payment Notification',
                                    'response_code': '96',
                                    'response_desc': 'Failed to activate covid loan refinancing'
                                }, status=HTTP_500_INTERNAL_SERVER_ERROR
                            )
                        payment = get_unpaid_payments(loan, order_by='payment_number')[0]
                        payment.refresh_from_db()

                elif loan.__class__ is Statement and \
                        loan.statement_total_due_amount != faspay.amount:
                    return LoggedResponse(
                        data={
                            'response': 'Payment Notification',
                            'response_code': '01',
                            'response_desc': 'Payment amount does not match with statement amount'
                        }
                    )

                process_payment = faspay_payment_process_loan(loan,
                                                              payment_method,
                                                              faspay,
                                                              data,
                                                              note)
                if process_payment:
                    if loan.__class__ is Loan:
                        regenerate_loan_refinancing_offer(loan)
                        if payment.payment_number == 1:
                            send_sms_async.delay(
                                application_id=payment.loan.application_id,
                                template_code=Messages.PAYMENT_RECEIVED_TEMPLATE_CODE,
                                context={'amount': display_rupiah(faspay.amount)}
                            )


                    return LoggedResponse(
                        data={
                            'response': 'Payment Notification',
                            'trx_id': data['trx_id'],
                            'merchant_id': data['merchant_id'],
                            'bill_no': payment_method.virtual_account,
                            'response_code': '00',
                            'response_desc': 'Sukses',
                            'response_date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )

            if line_of_credit is not None:
                process_payment = faspay_payment_process_loc(line_of_credit, faspay, data, note)
                if process_payment:
                    return LoggedResponse(
                        data={
                            'response': 'Payment Notification',
                            'trx_id': data['trx_id'],
                            'merchant_id': data['merchant_id'],
                            'bill_no': payment_method.virtual_account,
                            'response_code': '00',
                            'response_desc': 'Sukses',
                            'response_date': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )

            else:
                return LoggedResponse(
                    data={
                        'response': 'Payment Notification',
                        'response_code': '01',
                        'response_desc': 'Failed',
                        'message': 'Record Payment Notification'
                    }
                )
        else:
            old_status = faspay.status_code
            faspay.status_code = data['payment_status_code']
            faspay.status_desc = data['payment_status_desc']
            faspay.save()
            create_pbt_status_history(faspay, old_status, faspay.status_code)
            return LoggedResponse(
                data={
                    'response': 'Payment Notification',
                    'response_code': '01',
                    'payment_status_code': data['payment_status_code'],
                    'payment_status_desc': data['payment_status_desc'],
                }
            )

    def _pre_log_request(
        self,
        request: Request,
    ) -> None:
        logger.info(
            {
                "action": "juloserver.integapiv1.views.FaspayPaymentNotificationView",
                "action_group": "payment_api_requests",
                "endpoint": request.get_full_path(),
                "method": request.method,
                "virtual_account": request.data.get('bill_no', ''),
                "transaction_id": request.data.get('trx_id', ''),
            }
        )


class SepulsaTransactionView(APIView):

    permission_classes = ()
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)
    serializer_class = SepulsaTransactionSerializer

    def post(self, request, *args, **kwargs):

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        transaction_id = data['transaction_id']
        try:
            order_id = int(decrypt_order_id_sepulsa(data['order_id']).split("-")[0])
        except Exception as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            order_id = 0
        with transaction.atomic():
            sepulsa_transaction = SepulsaTransaction.objects.select_for_update().filter(
                        pk=order_id,
                        transaction_code=transaction_id).last()
        if not sepulsa_transaction:
            return Response(
                data={
                    'message': "Order id not found!.",
                    'data': data,
                },
                status=HTTP_400_BAD_REQUEST)
        if sepulsa_transaction.response_code == data['response_code']:
            return Response(
                status=HTTP_200_OK,
                data={
                    'message': 'Update transaction success.',
                    'data': data,
                })
        try:
            sepulsa_service = SepulsaService()
            sepulsa_transaction = sepulsa_service.update_sepulsa_transaction_with_history_accordingly(
                                        sepulsa_transaction,
                                        'update_transaction_via_callback',
                                        data)
            if sepulsa_transaction.line_of_credit_transaction:
                loc_transaction = LineOfCreditPurchaseService()
                loc = sepulsa_transaction.line_of_credit_transaction.line_of_credit
                loc_transaction.action_loc_sepulsa_transaction(loc, 'update_transaction_via_callback', sepulsa_transaction)
            else:
                if sepulsa_transaction.is_instant_transfer_to_dana:
                    check_and_refunded_transfer_dana(sepulsa_transaction)
                else:
                    action_cashback_sepulsa_transaction('update_transaction_via_callback', sepulsa_transaction)

        except Exception as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()

        return Response(
            status=HTTP_200_OK,
            data={
                'message': 'Update transaction success.',
                'data': data,
            })


class QismoAssignAgentView(APIView):
    permission_classes = (AllowAny, )

    def post(self, request):
        data = request.data
        app_id = data['app_id']

        if app_id != settings.QISMO_APP_ID:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "error": "invalid app_id %s" % app_id
                })

        process_assign_agent(data['room_id'])

        return LoggedResponse(data={'status': 'OK', 'room_id': data['room_id']})


class PrimoCallResultView(APIView):

    permission_classes = (AllowAny, )

    def post(self, request):
        data = request.data
        application_xid = int(data['application_id'])
        lead_id = int(data['lead_id'])
        record = PrimoDialerRecord.objects.filter(
            application__application_xid=application_xid, lead_id=lead_id
        ).last()

        if not record:
            logger.error(data)
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "error": "record_not_found",
                    "application_id": application_xid
                })

        application = record.application
        payment = record.payment

        if payment:

            process_callback_primo_payment(data, record, payment)

            return LoggedResponse(
                status=HTTP_200_OK,
                data={
                    "message": "success_to_save_record",
                    "action": "save_primo_record",
                    "application_id": application_xid
                })
        else:
            if record.application_status.status_code == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:

                if application.is_courtesy_call:
                    return LoggedResponse(
                        status=HTTP_200_OK,
                        data={
                            "message": "courtesy_call_already_done",
                            "application_id": application_xid
                        })

                if data['call_status'] in ['A', 'B', 'DC', 'DEC', 'DNC', 'N']:
                    email_client = get_julo_email_client()
                    try:
                        email_client.email_courtesy(application)
                    except EmailNotSent:
                        logger.warn({
                            'action': 'send_email_courtesy_failed',
                            'application_id': application_xid
                        })

                with transaction.atomic():
                    if data['call_status'] != 'DROP':
                        application.is_courtesy_call = True
                        application.save()
                        record.lead_status = PrimoLeadStatus.COMPLETED

                    record.call_status = data['call_status']
                    record.agent = data['agent_id']
                    record.save()

                return LoggedResponse(
                    status=HTTP_200_OK,
                    data={
                        "message": "success_to_save_record",
                        "action": "courtesy_save_primo_record",
                        "application_id": application_xid
                    })

            ########################################################################

            user = User.objects.filter(username=data['agent_id'].lower()).last()

            with transaction.atomic():
                if user:
                    if data['call_status'] == 'CONNECTED':
                        primo_locked_app(application, user)
                    else:
                        primo_unlocked_app(application, user)
                        primo_update_skiptrace(record, user, data['call_status'])
                        record.lead_status = PrimoLeadStatus.COMPLETED
                else:
                    if data['call_status'] != 'DROP':
                        record.retry_times += 1

                record.call_status = data['call_status']
                record.agent = data['agent_id']
                record.save()

            max_retry_times = 3
            if record.retry_times >= max_retry_times:
                if application.status == ApplicationStatusCodes.DOCUMENTS_VERIFIED:
                    process_application_status_change(
                        application.id, ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
                        "employer not reachable", "Primo Decissions")

            return LoggedResponse(
                status=HTTP_200_OK,
                data={
                    "message": "success_to_save_record",
                    "action": "save_primo_record",
                    "application_id": application_xid
                })


class VoiceCallView(APIView):

    permission_classes = (AllowAny, )

    def get(self, request, voice_type, identifier):
        if voice_type not in [VoiceTypeStatus.PAYMENT_REMINDER,
                              VoiceTypeStatus.APP_CAMPAIGN,
                              VoiceTypeStatus.PTP_PAYMENT_REMINDER,
                              VoiceTypeStatus.COVID_CAMPAIGN]:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "error": "voice type not found for id %s" % identifier
                })
        if voice_type == VoiceTypeStatus.COVID_CAMPAIGN:
            data = get_covid_campaign_voice_template(identifier)
        else:
            streamlined_id = request.GET.get('streamlined_id', None)
            product = request.GET.get('product', False)
            is_j1 = True if product == "J1" else False
            is_grab = True if product == "GRAB" else False
            is_jturbo = True if product == "JTurbo" else False
            data = get_voice_template(
                voice_type, identifier, streamlined_id, is_j1=is_j1, is_grab=is_grab,
                is_jturbo=is_jturbo
            )
        if not data:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "error": "Wrong identifier %s" % identifier
                })

        return LoggedResponse(data=data)

    def post(self, request, voice_type, identifier):
        """ api to update IVR robocall
            request contain "conversation_uuid", "identifier", "dtmf" as answer
        """
        conversation_uuid = request.data["conversation_uuid"]
        voice_call_record = VoiceCallRecord.objects.filter(
            conversation_uuid=conversation_uuid).last()
        if not voice_call_record:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "error": "Wrong conversation uuid %s" % conversation_uuid
                })
        account_payment = AccountPayment.objects.filter(pk=identifier).last()
        payment = Payment.objects.filter(pk=identifier).last()
        if not account_payment and not payment:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "error": "Wrong identifier %s" % identifier
                })
        if account_payment:
            payment_or_account_payment = account_payment
        else:
            payment_or_account_payment = payment

        answer = request.data['dtmf']
        voice_call_record.answer = answer
        voice_call_record.save()
        if answer == '1':
            payment_or_account_payment.is_robocall_active = True
            payment_or_account_payment.is_collection_called = True
            payment_or_account_payment.save(update_fields=['is_robocall_active',
                                        'is_collection_called',
                                        'udate'])
            # since this API have different with duration consider race condition
            sms_after_robocall_experiment_trigger.delay(payment_or_account_payment.id)
        if not answer and answer != 0:
            data = [{
                "action": "talk",
                "voiceName": "Damayanti",
                "text": ""
            }]
            return LoggedResponse(data=data)
        data = [{
                "action": "talk",
                "voiceName": "Damayanti",
                "text": "Terima Kasih"
               }]
        return LoggedResponse(data=data)


class VoiceCallResultView(APIView):
    permission_classes = (AllowAny, )
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)
    serializer_class = VoiceCallbackResultSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = request.data
        logger.info({
            "action": "callback_from_nexmo",
            "data": data
        })

        update_voice_call_record.delay(data)
        return LoggedResponse(data={'success': True})


class VoiceCallRecordingCallback(APIView):
    permission_classes = (AllowAny, )
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)
    serializer_class = VoiceCallRecordingSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = request.data
        logger.info({
            "action": "callback_from_nexmo",
            "data": data
        })

        store_voice_recording_data.delay(data)
        return LoggedResponse(data={'success': True})


class XfersWithdrawCallbackView(APIView):
    permission_classes = (AllowAny, )
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)

    def post(self, request):
        data = request.data
        idempotency_id = data['idempotency_id']
        external_id = idempotency_id[:10]

        logger.info({"action": "XfersWithdrawCallbackView.post", "data": data})

        disbursement = Disbursement.objects.get_or_none(external_id=external_id)
        if not disbursement:
            return LoggedResponse(
                status=HTTP_404_NOT_FOUND,
                data={
                    "error": "withdrawal with idempotency_id %s not found" % (idempotency_id)
                }
            )
        try:
            xfers_service = XfersService()
            xfers_service.process_update_disbursement(disbursement, data)
        except Exception as e:
            return LoggedResponse(
                status=HTTP_500_INTERNAL_SERVER_ERROR,
                data={
                    "error": "withdrawal with idempotency_id %s failed to process" % (idempotency_id)
                }
            )

        return LoggedResponse(
            status=HTTP_200_OK,
            data={
                "message": "successfully process withdrawal %s" % (idempotency_id)
            }
        )


class PingAutoCall(APIView):

    permission_classes = (AllowAny, )

    def get(self, request):
        result = [{
            "action": "stream",
            "streamUrl": [settings.BASE_URL + "/static/audio/2-seconds-of-silence.mp3"]}]

        data = json.loads(json.dumps(result))

        return LoggedResponse(data=data)


class AutoCallEventStatus(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        data = request.data.copy()
        conversation_uuid = data["conversation_uuid"]
        status = data["status"]
        conversation = Autodialer122Queue.objects.get_or_none(conversation_uuid=conversation_uuid)
        if conversation:
            if status != "completed":
                conversation.auto_call_result_status = status
                conversation.save()
            if status in ('unanswered', 'timeout', 'rejected', 'failed',) and conversation.attempt >= 3:
                process_application_status_change(
                    conversation.application_id, ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
                    change_reason="system_triggered_by_ping_auto_call")
        return Response(status=HTTP_200_OK)


class AutoCallEventStatus138(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        data = request.data.copy()
        conversation_uuid = data["conversation_uuid"]
        status = data["status"]
        conversation = NexmoAutocallHistory.objects.get_or_none(conversation_uuid=conversation_uuid)
        if conversation:
            if status != "completed":
                conversation.auto_call_result_status = status
                conversation.save()
            if status in ('unanswered', 'timeout', 'rejected', 'failed', ):
                process_application_status_change(
                    conversation.application_history.application.id,
                    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
                    change_reason="system_triggered_by_ping_auto_call")

        return Response(status=HTTP_200_OK)


class PredictiveMissedCallView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        data = request.data.copy()
        conversation_uuid = data["conversation_uuid"]
        call_status = data["status"]
        conversation = PredictiveMissedCall.objects.get_or_none(conversation_uuid=conversation_uuid)
        if conversation:
            if call_status != "completed":
                conversation.auto_call_result_status = call_status
                conversation.save()
            current_status = conversation.application.application_status_id
            if current_status in PredictiveMissedCall().moved_statuses:
                destination_status = PredictiveMissedCall().moved_status_destinations(current_status)
                if destination_status:
                    if call_status in ('unanswered', 'timeout', 'rejected', 'failed') and conversation.attempt >= 2:
                        process_application_status_change(
                            conversation.application.id,
                            destination_status,
                            change_reason="system_triggered_by_predictive_missed_call")

        return Response(status=HTTP_200_OK)


class SMSMontyMobileView(APIView):
    permission_classes = (AllowAny, )
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)

    def post(self, request, *args, **kwargs):
        response = request.data.get('CallBackResponse', None)
        if response is None:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "error": ["No response passed"]
                })

        message_id = response.get('MessageId', None)

        # handle if callback send 'Guid' instead of MessageId
        gu_id = response.get('Guid', None)
        message_id = message_id or gu_id

        if message_id is None:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "MessageId": ["This field is required"]
                })

        SmsVendorRequest.objects.create(
            phone_number=response.get('MobileNo', None),
            vendor_identifier=message_id,
            comms_provider_lookup_id=CommsProviderLookup.objects.get(
                provider_name=VendorConst.MONTY.capitalize(),
            ).id,
            payload=response,
        )

        status = response.get('Status', None)
        if status is None:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "Status": ["This field is required"]
                })

        delivery_error_code = response.get('StatusId', None)
        if delivery_error_code is None:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "StatusId": ["This field is required"]
                })
        delivery_error_code = int(delivery_error_code)

        sms_history = SmsHistory.objects.filter(message_id=message_id).last()
        comms_campaign_sms_history = None
        if sms_history is None:
            comms_campaign_sms_history = CommsCampaignSmsHistory.objects.filter(
                message_id=message_id
            ).last()
            if comms_campaign_sms_history is None:
                return LoggedResponse(
                    status=HTTP_404_NOT_FOUND,
                    data={"error": "message_id=%s not found" % message_id},
                )

        sms_history_to_update = sms_history or comms_campaign_sms_history
        sms_history_to_update.status = status
        sms_history_to_update.delivery_error_code = delivery_error_code
        sms_history_to_update.save()
        evaluate_sms_reachability.delay(
            response.get('MobileNo'), VendorConst.MONTY, sms_history_to_update.customer_id
        )

        if status == 'delivered':
            otp_request = OtpRequest.objects.filter(sms_history_id=sms_history_to_update.id)
            otp_request.update(reported_delivered_time=datetime.datetime.now())

        if delivery_error_code != 2:
            logger.warn({
                'message_id': message_id,
                'status': status,
                'delivery_error_code': delivery_error_code,
                'response' : response
            })

            if delivery_error_code == 5:
                if sms_history_to_update.is_otp:
                    customer = sms_history_to_update.customer

                    existing_otp = OtpRequest.objects.filter(customer=customer, is_used=False).order_by('id').last()
                    if existing_otp and existing_otp.is_active == True:
                        create_new_otp = False
                        req_id = existing_otp.request_id
                    else:
                        create_new_otp = True

                    if create_new_otp:
                        postfix = int(time.time())
                        postfixed_request_id = str(customer.id) + str(postfix)
                        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
                        otp = str(hotp.at(int(postfixed_request_id)))
                        otp_obj = OtpRequest.objects.create(
                            customer=customer,
                            request_id=postfixed_request_id,
                            otp_token=otp,
                            phone_number=sms_history_to_update.to_mobile_phone,
                        )
                    else:
                        otp = existing_otp.otp_token
                        otp_obj = existing_otp

                    context = {'otp_token': otp}
                    text_message = render_to_string('sms_otp_token.txt', context=context)
                else:
                    text_message = sms_history_to_update.message_content

                message, response = get_julo_sms_client().send_sms_nexmo(
                    sms_history_to_update.to_mobile_phone.__str__(),
                    text_message,
                    is_otp=sms_history_to_update.is_otp,
                )

                if comms_campaign_sms_history:
                    response['messages'][0]['is_comms_campaign_sms'] = True
                    sms = create_sms_history(
                        response=response['messages'][0],
                        message_content=text_message,
                        to_mobile_phone=sms_history_to_update.phone_number,
                        phone_number_type=sms_history_to_update.phone_number_type,
                        template_code="retry_for_id_%s" % (sms_history_to_update.id),
                        application=sms_history_to_update.application,
                        account=sms_history_to_update.account,
                        customer=sms_history_to_update.customer,
                    )
                    sms.campaign = sms_history_to_update.campaign
                    sms.save()
                else:
                    sms = create_sms_history(
                        response=response['messages'][0],
                        payment=sms_history_to_update.payment,
                        application=sms_history_to_update.application,
                        customer=sms_history_to_update.customer,
                        message_content=text_message,
                        template_code="retry_for_id_%s" % (sms_history_to_update.id),
                        to_mobile_phone=sms_history_to_update.to_mobile_phone,
                        phone_number_type=sms_history_to_update.phone_number_type,
                    )

                if sms_history_to_update.is_otp:
                    otp_obj.sms_history = sms
                    otp_obj.save()

                logger.info({
                    "action": "retry_undelivered_monty_to_nexmo",
                    "monty_message_id": message_id,
                    "nexmo_response": response
                })

        logger.info({
            "action": "callback_from_monty_mobile",
            "response": response
        })
        return LoggedResponse(data={'success': True})


#################################### BCA Direct Settlement API #######################################
class BcaAccessTokenView(APIView):
    permission_classes = (AllowAny, )
    serializer_class = []

    def post(self, request, *args, **kwargs):
        req_auth = request.META.get('HTTP_AUTHORIZATION')
        grant_type = request.data.get('grant_type')
        bca_client = get_bca_client()
        bca_auth = 'Basic ' + generate_base64('%s:%s' % (bca_client.client_id,
                                                         bca_client.client_secret))
        logger.info({
            'action': 'api_get_access_token_bca',
            'request': request.__dict__,
        })

        # print self.request.META['Authorization']
        if req_auth != bca_auth:
            return LoggedResponse(status=HTTP_403_FORBIDDEN)

        if grant_type != 'client_credentials':
            return LoggedResponse(status=HTTP_400_BAD_REQUEST, data="invalid grant_type")

        bca_partner = Partner.objects.filter(name=PartnerConstant.BCA_PARTNER).last()
        if not bca_partner:
            return LoggedResponse(status=HTTP_403_FORBIDDEN, data="bca is not registered")

        token = bca_partner.token
        response = JsonResponse(data=bca_client.generate_bca_token_response(token))
        logger.info({
            'action': 'va_bca',
            'method': 'bca_access_token_view_post',
            'request': request.__dict__,
            'response': response.__dict__
        })

        return response


class BcaInquiryBills(APIView):
    permission_classes = (AllowAny, )
    serializer_class = []

    def post(self, request):
        data = get_parsed_bca_payload(request.body, request.META.get('CONTENT_TYPE'))
        relative_url = request.get_full_path()
        access_token = request.META.get('HTTP_AUTHORIZATION')
        bca_partner = Partner.objects.get(name=PartnerConstant.BCA_PARTNER)
        bca_bill = dict(CompanyCode=data.get('CompanyCode'),
                        CustomerNumber=data.get('CustomerNumber'),
                        RequestID=data.get('RequestID'),
                        InquiryStatus=None,
                        InquiryReason=None,
                        CustomerName='',
                        CurrencyCode="IDR",
                        TotalAmount=0.00,
                        SubCompany='00000',
                        DetailBills=[],
                        FreeTexts=[],
                        AdditionalData="")
        if access_token != '{} {}'.format('Bearer', bca_partner.token):
            inquiry_status = '01'
            inquiry_reason = generate_description('access token tidak valid',
                                                  'invalid access token')
            bca_bill['InquiryStatus'] = inquiry_status
            bca_bill['InquiryReason'] = inquiry_reason

            response = JsonResponse(data=bca_bill)
            logger.warn({
                'method': 'bca_inquiry_bills_post',
                'action': 'va_bca',
                'response': response.__dict__,
                'request': request.__dict__
            })

            return response

        content_type = request.META.get('CONTENT_TYPE')
        origin = request.META.get('HTTP_ORIGIN')
        x_bca_key = request.META.get('HTTP_X_BCA_KEY')
        x_bca_timestamp = request.META.get('HTTP_X_BCA_TIMESTAMP')
        x_bca_signature = request.META.get('HTTP_X_BCA_SIGNATURE')
        headers = dict(access_token=access_token,
                       content_type=content_type,
                       origin=origin,
                       x_bca_key=x_bca_key,
                       x_bca_timestamp=x_bca_timestamp,
                       x_bca_signature=x_bca_signature)
        method = request.method

        # authenticate the headers
        is_authenticated = authenticate_bca_request(headers, data, 'POST', relative_url)
        if not is_authenticated:
            inquiry_status = '01'
            inquiry_reason = generate_description('signature tidak valid',
                                                  'invalid signature')
            bca_bill['InquiryStatus'] = inquiry_status
            bca_bill['InquiryReason'] = inquiry_reason
            logger.warning({
                "action": "api_bca_inquiry_bill",
                "status": "invalid signature",
                "body": data,
                "headers": headers
            })
            return JsonResponse(data=bca_bill)

        logger.info({
            "action": "api_bca_inquiry_bill",
            "headers": headers,
            "body": data,
            "method": method
        })
        # payload validation
        status, reason = validate_bca_inquiry_payload(data)
        if status != '00':
            bca_bill['InquiryStatus'] = status
            bca_bill['InquiryReason'] = reason
            response = JsonResponse(data=bca_bill)
            logger.warning({
                "action": "api_bca_inquiry_bill",
                "status": status,
                "reason": reason,
                "body": data,
                "headers": headers,
                "request": request.__dict__,
                "response": response.__dict__
            })
            return response

        # process get bill from data
        bca_bill = get_bca_payment_bill(data, bca_bill)
        response = JsonResponse(data=bca_bill)

        logger.info({
            'method': 'bca_inquiry_bills_post',
            'action': 'va_bca',
            'response': response.__dict__,
            'request': request.__dict__
        })
        return response


class BcaPaymentFlagInvocationView(APIView):
    permission_classes = (AllowAny, )
    serializer_class = []

    def post(self, request):
        data = get_parsed_bca_payload(request.body, request.META.get('CONTENT_TYPE'))
        relative_url = request.get_full_path()
        access_token = request.META.get('HTTP_AUTHORIZATION')
        bca_partner = Partner.objects.get(name=PartnerConstant.BCA_PARTNER)
        virtual_account = '{}{}'.format(data.get('CompanyCode'),
                                        data.get('CustomerNumber'))
        response_data = dict(CompanyCode=data.get('CompanyCode'),
                             CustomerNumber=data.get('CustomerNumber'),
                             RequestID=data.get('RequestID'),
                             PaymentFlagStatus=None,
                             PaymentFlagReason=None,
                             CustomerName=data.get('CustomerName'),
                             CurrencyCode=data.get('CurrencyCode'),
                             PaidAmount=data.get('PaidAmount'),
                             TotalAmount=data.get('TotalAmount'),
                             TransactionDate=data.get('TransactionDate'),
                             DetailBills=data.get('DetailBills'),
                             FreeTexts=[],
                             AdditionalData='')

        if access_token != '{} {}'.format('Bearer', bca_partner.token):
            payment_flag_status = "01"
            payment_flag_reason = generate_description('access token tidak valid',
                                                       'invalid access_token')
            response_data['PaymentFlagStatus'] = payment_flag_status
            response_data['PaymentFlagReason'] = payment_flag_reason
            response = JsonResponse(data=response_data)

            logger.warning({
                'method': 'api_bca_payment_flag_invocation',
                'action': 'va_bca',
                'virtual_account': virtual_account,
                'status': payment_flag_reason,
                'request': request.__dict__,
                'response': response.__dict__
            })
            return response

        method = request.method
        content_type = request.META.get('CONTENT_TYPE')
        origin = request.META.get('HTTP_ORIGIN')
        x_bca_key = request.META.get('HTTP_X_BCA_KEY')
        x_bca_timestamp = request.META.get('HTTP_X_BCA_TIMESTAMP')
        x_bca_signature = request.META.get('HTTP_X_BCA_SIGNATURE')
        headers = dict(access_token=access_token,
                       content_type=content_type,
                       origin=origin,
                       x_bca_key=x_bca_key,
                       x_bca_timestamp=x_bca_timestamp,
                       x_bca_signature=x_bca_signature)

        logger.info({
            "action": "api_bca_payment_flag_invocation",
            "headers": headers,
            "body": data,
            "method": method,
            "va": virtual_account
        })

        # authenticate the headers
        is_authenticated = authenticate_bca_request(headers, data, method, relative_url)
        if not is_authenticated:
            payment_flag_status = "01"
            payment_flag_reason = generate_description('signature tidak valid',
                                                       'invalid signature')
            response_data['PaymentFlagStatus'] = payment_flag_status
            response_data['PaymentFlagReason'] = payment_flag_reason
            response = JsonResponse(data=response_data)

            logger.warning({
                'method': 'api_bca_payment_flag_invocation',
                'action': 'va_bca',
                'virtual_account': virtual_account,
                'status': payment_flag_reason,
                'data': data,
                'headers': headers,
                'response': response.__dict__,
                'request': request.__dict__
            })
            return response

        # payload validation
        status, reason = validate_bca_payment_payload(data)
        if status != '00':
            response_data['PaymentFlagStatus'] = status
            response_data['PaymentFlagReason'] = reason
            response = JsonResponse(data=response_data)

            logger.warning({
                'method': 'api_bca_payment_flag_invocation',
                'action': 'va_bca',
                'status': status,
                'reason': reason,
                'data': data,
                'headers': headers,
                'request': request.__dict__,
                'response': response.__dict__
            })
            return response

        escrow_payment_method = EscrowPaymentMethod.objects.filter(
            virtual_account=virtual_account,
        )
        if escrow_payment_method:
            response_data['PaymentFlagStatus'] = "00"
            response_data['PaymentFlagReason'] = generate_description('sukses', 'success')
            response = JsonResponse(data=response_data)

            logger.info({
                'method': 'escrow_api_bca_payment_flag_invocation',
                'action': 'va_bca',
                'status': status,
                'reason': reason,
                'data': data,
                'headers': headers,
                'request': request.__dict__,
                'response': response.__dict__
            })
            return response

        payment_method = PaymentMethod.objects.filter(
            virtual_account=virtual_account).last()
        if not payment_method:
            payment_flag_status = "01"
            payment_flag_reason = generate_description('va tidak ditemukan',
                                                       'va not found')
            response_data['PaymentFlagStatus'] = payment_flag_status
            response_data['PaymentFlagReason'] = payment_flag_reason
            response = JsonResponse(data=response_data)

            logger.warning({
                'method': 'api_bca_payment_flag_invocation',
                'action': 'va_bca',
                'virtual_account': virtual_account,
                'status': payment_flag_reason,
                'request': request.__dict__,
                'response': response.__dict__
            })

            return response

        request_id = data.get('RequestID')

        payback_transaction = PaybackTransaction.objects.filter(
            payment_method=payment_method,
            transaction_id=request_id).last()

        if not payback_transaction:
            payment_flag_status = "01"
            payment_flag_reason = generate_description('RequestID tidak ditemukan',
                                                       'RequestID not found')
            msg = "There's error when hit API BCA: RequestID {} not found.".format(request_id)
            channel_name = get_channel_name_slack_for_payment_problem()
            notify_failure(msg, channel=channel_name)
            response_data['PaymentFlagStatus'] = payment_flag_status
            response_data['PaymentFlagReason'] = payment_flag_reason
            response = JsonResponse(data=response_data)
            logger.warning({
                'method': 'api_bca_payment_flag_invocation',
                'action': 'va_bca',
                'virtual_account': virtual_account,
                'status': payment_flag_reason,
                'request': request.__dict__,
                'response': response.__dict__
            })

            return response

        elif payback_transaction.is_processed:
            payment_flag_status = "01"
            payment_flag_reason = generate_description('RequestID sudah digunakan',
                                                       'RequestID already used')
            msg = "There's error when hit API BCA: RequestID {} already used for payment id {}."\
                .format(request_id, payback_transaction.payment_id)
            response_data['PaymentFlagStatus'] = payment_flag_status
            response_data['PaymentFlagReason'] = payment_flag_reason
            response = JsonResponse(data=response_data)

            logger.warning({
                'method': 'api_bca_payment_flag_invocation',
                'action': 'va_bca',
                'virtual_account': virtual_account,
                'status': payment_flag_reason,
                'request': request.__dict__,
                'response': response.__dict__,
                'message': msg
            })

            return response

        if float(data.get("TotalAmount")) < float(BcaConst.MINIMUM_TRANSFER_AMOUNT):
            payment_flag_status = "01"
            payment_flag_reason = generate_description('TotalAmount kurang dari Rp 10,000',
                                                       'TotalAmount less than RP 10,000')
            response_data['PaymentFlagStatus'] = payment_flag_status
            response_data['PaymentFlagReason'] = payment_flag_reason
            response = JsonResponse(data=response_data)

            logger.warning({
                'method': 'api_bca_payment_flag_invocation',
                'action': 'va_bca',
                'virtual account': virtual_account,
                'status': payment_flag_reason,
                'request': request.__dict__,
                'response': response.__dict__
            })
            return response

        # reserve for future use if we decide to transfer  for fixed amount
        # if float(payback_transaction.amount) != float(data.get("TotalAmount")):
        #     payment_flag_status = "01"
        #     payment_flag_reason = generate_description('TotalAmount tidak sesuai',
        #                                                'TotalAmount not match')
        #     response_data['PaymentFlagStatus'] = payment_flag_status
        #     response_data['PaymentFlagReason'] = payment_flag_reason
        #     response = JsonResponse(data=response_data)

        #     logger.warning({
        #         'method': 'api_bca_payment_flag_invocation',
        #         'action': 'va_bca',
        #         'virtual account': virtual_account,
        #         'status': payment_flag_reason,
        #         'request': request.__dict__,
        #         'response': response.__dict__
        #     })

        #     return response
        try:
            bca_process_payment(payment_method, payback_transaction, data)
            payment_flag_status = "00"
            payment_flag_reason = generate_description('sukses', 'success')
        except JuloException as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            payment_flag_status = "01"
            messages = str(e).split(',')
            payment_flag_reason = generate_description(messages[0], messages[1])
        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            payment_flag_status = "01"
            payment_flag_reason = generate_description('ada kesalahan di sistem',
                                                       'something wrong in the system')

        response_data['PaymentFlagStatus'] = payment_flag_status
        response_data['PaymentFlagReason'] = payment_flag_reason
        response = JsonResponse(data=response_data)
        logger.info({
            'method': 'api_bca_payment_flag_invocation',
            'action': 'va_bca',
            'virtual_account': virtual_account,
            'status': payment_flag_reason,
            'request': request.__dict__,
            'response': response.__dict__
        })

        return response


class BaseSnapBcaView(APIView):
    permission_classes = (AllowAny,)

    @csrf_exempt
    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)
        if hasattr(response, 'content'):
            redis_client = get_redis_client()
            response_data = json.loads(response.content)
            external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
            last_path_url = urlparse(request.get_full_path()).path.split('/')[-1]
            key = 'bca_snap:{}:external_id:{}'.format(last_path_url, external_id)
            external_id_redis = redis_client.get(key)
            if external_id and not external_id_redis:
                today_datetime = timezone.localtime(timezone.now())
                tomorrow_datetime = today_datetime + relativedelta(days=1, hour=0, minute=0,
                                                                   second=0)
                redis_client.set(key, json.dumps(response_data), tomorrow_datetime - today_datetime)
        return response

    def _pre_log_request(
        self,
        request: Request,
    ) -> None:
        logger.info(
            {
                "action": "BaseSnapBcaView",
                "action_group": "payment_api_requests",
                "endpoint": request.get_full_path(),
                "method": request.method,
                "virtual_account": request.data.get('virtualAccountNo', ''),
                "transaction_id": request.data.get('inquiryRequestId', '')
                or request.data.get('paymentRequestId', ''),
            }
        )

    def _log_request(
            self,
            request_body: bytes,
            request: Request,
            response: Response,
    ) -> None:
        timestamp = request.META.get('HTTP_X_TIMESTAMP', None)
        signature = request.META.get('HTTP_X_SIGNATURE', None)
        partner_id = request.META.get('HTTP_X_PARTNER_ID', None)
        external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
        channel_id = request.META.get('HTTP_CHANNEL_ID', None)

        headers = {
            'HTTP_X_TIMESTAMP': timestamp,
            'HTTP_X_SIGNATURE': signature,
            'HTTP_X_PARTNER_ID': partner_id,
            'HTTP_X_EXTERNAL_ID': external_id,
            'HTTP_CHANNEL_ID': channel_id,
        }
        data_to_log = {
            "action": "snap_bca_api_view_logs",
            "headers": headers,
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response.__dict__,
        }
        store_payback_callback_log.delay(
            request_data=request_body,
            response_data=response.content,
            http_status_code=response.status_code,
            url='[POST] {}'.format(request.get_full_path()),
            vendor=SnapVendorChoices.BCA,
            customer_id=self.kwargs.get('customer_id', None),
            loan_id=self.kwargs.get('loan_id', None),
            account_payment_id=self.kwargs.get('account_payment_id', None),
            payback_transaction_id=self.kwargs.get('payback_transaction_id', None),
            error_message=self.kwargs.get('error_message', None),
            header=headers,
        )

        if 400 <= response.status_code <= 499:
            logger.warning(data_to_log)
        elif 500 <= response.status_code <= 599:
            logger.error(data_to_log)
        else:
            logger.info(data_to_log)


class BcaSnapAccessTokenView(BaseSnapBcaView):

    def post(self, request, *args, **kwargs):
        client_id = request.META.get('HTTP_X_CLIENT_KEY')
        signature = request.META.get('HTTP_X_SIGNATURE')
        timestamp = request.META.get('HTTP_X_TIMESTAMP')

        serializer = SnapBcaAccessTokenSerializer(data=request.data)
        if not serializer.is_valid():
            response_code = SnapTokenResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
            response_message = "{} {}".format(
                SnapTokenResponseCodeAndMessage.INVALID_FIELD_FORMAT.message,
                '[clientId/clientSecret/grantType]',
            )
            if 'This field is required.' in errors:
                response_code = SnapTokenResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                response_message = "{} {}".format(
                    SnapTokenResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                    key,
                )
            self.kwargs['error_message'] = response_message

            return JsonResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "responseCode": response_code,
                    "responseMessage": response_message,
                },
            )
        if not validate_datetime_within_10_minutes(timestamp):
            response_code = SnapTokenResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
            response_message = "{} {}".format(
                SnapTokenResponseCodeAndMessage.INVALID_FIELD_FORMAT.message, '[X-TIMESTAMP]'
            )

            return JsonResponse(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "responseCode": response_code,
                    "responseMessage": response_message,
                }
            )
        if client_id != settings.BCA_SNAP_CLIENT_ID_INBOUND:
            response_code = SnapTokenResponseCodeAndMessage.UNAUTHORIZED_CLIENT.code
            response_message = SnapTokenResponseCodeAndMessage.UNAUTHORIZED_CLIENT.message
            self.kwargs['error_message'] = response_message

            return JsonResponse(
                status=HTTP_401_UNAUTHORIZED,
                data={
                    "responseCode": response_code,
                    "responseMessage": response_message,
                },
            )
        string_to_sign = '{}|{}'.format(client_id, timestamp)
        public_key = settings.BCA_SNAP_PUBLIC_KEY_INBOUND
        try:
            is_valid_signature = verify_asymmetric_signature(public_key, signature, string_to_sign)
        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            is_valid_signature = False
        if not is_valid_signature:
            response_code = SnapTokenResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code
            response_message = SnapTokenResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message
            self.kwargs['error_message'] = response_message

            return JsonResponse(
                status=HTTP_401_UNAUTHORIZED,
                data={
                    "responseCode": response_code,
                    "responseMessage": response_message,
                },
            )

        expiry_token = generate_snap_expiry_token(SnapVendorChoices.BCA)

        return JsonResponse(
            data={
                "responseCode": SnapTokenResponseCodeAndMessage.SUCCESS.code,
                "responseMessage": SnapTokenResponseCodeAndMessage.SUCCESS.message,
                "accessToken": expiry_token.key,
                "tokenType": "bearer",
                "expiresIn": "{}".format(EXPIRY_TIME_TOKEN_BCA_SNAP),
            }
        )


class BcaSnapInquiryBillsView(BaseSnapBcaView):

    def post(self, request):
        bca_bill = {
            "responseCode": "",
            "responseMessage": "",
            "virtualAccountData": {
                "inquiryStatus": "",
                "inquiryReason": {
                    "english": "",
                    "indonesia": ""
                },
                "partnerServiceId": request.data.get('partnerServiceId', ''),
                "customerNo": request.data.get('customerNo', ''),
                "virtualAccountNo": request.data.get('virtualAccountNo', ''),
                "virtualAccountName": "",
                "virtualAccountEmail": "",
                "virtualAccountPhone": "",
                "inquiryRequestId": request.data.get('inquiryRequestId', ''),
                "totalAmount": {
                    "value": "",
                    "currency": ""
                },
                "subCompany": "00000",
                "billDetails": [],
                "freeTexts": [
                    {
                        "english": "",
                        "indonesia": ""
                    }
                ],
                "virtualAccountTrxType": "V",
                "feeAmount": {
                    "value": "",
                    "currency": ""
                },
                "additionalInfo": {

                }
            }
        }
        try:
            self._pre_log_request(request)
            channel_id = request.META.get('HTTP_CHANNEL_ID')
            partner_id = request.META.get('HTTP_X_PARTNER_ID')
            if (
                channel_id != settings.BCA_SNAP_CHANNEL_ID_OUBTOND
                or partner_id != settings.BCA_SNAP_COMPANY_VA_OUTBOND
            ):
                response_data = {
                    'responseCode': (SnapInquiryResponseCodeAndMessage.UNAUTHORIZED_CLIENT.code),
                    'responseMessage': (
                        SnapInquiryResponseCodeAndMessage.UNAUTHORIZED_CLIENT.message
                    ),
                }
                self.kwargs['error_message'] = response_data["responseMessage"]

                return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)
            # check token
            access_token = request.META.get('HTTP_AUTHORIZATION', '').split(' ')[-1]
            snap_expiry_token = get_snap_expiry_token(access_token, SnapVendorChoices.BCA)
            if not snap_expiry_token or is_expired_snap_token(snap_expiry_token,
                                                              EXPIRY_TIME_TOKEN_BCA_SNAP):
                response_data = {
                    'responseCode': (SnapInquiryResponseCodeAndMessage.INVALID_TOKEN.code),
                    'responseMessage': (SnapInquiryResponseCodeAndMessage.INVALID_TOKEN.message),
                }
                self.kwargs['error_message'] = response_data["responseMessage"]

                return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)
            data = request.data
            relative_url = request.get_full_path()
            headers = {
                "access_token": access_token,
                "content_type": request.META.get('CONTENT_TYPE'),
                "origin": request.META.get('HTTP_ORIGIN'),
                "x_key": request.META.get('HTTP_X_TIMESTAMP'),
                "x_timestamp": request.META.get('HTTP_X_TIMESTAMP'),
                "x_signature": request.META.get('HTTP_X_SIGNATURE')
            }
            is_authenticated = authenticate_snap_request(
                headers, data, request.method, settings.BCA_SNAP_CLIENT_SECRET_INBOUND, relative_url
            )
            if not is_authenticated:
                response_data = {
                    'responseCode': (SnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code),
                    'responseMessage': (
                        SnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.message
                    ),
                }
                self.kwargs['error_message'] = response_data["responseMessage"]
                return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

            serializer = SnapBcaInquiryBillsSerializer(data=request.data)
            if not serializer.is_valid():
                key = list(serializer.errors.items())[0][0]
                errors = list(serializer.errors.items())[0][1][0]
                bca_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                if errors in ErrorDetail.mandatory_field_errors():
                    bca_bill[
                        'responseCode'
                    ] = SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                    bca_bill['responseMessage'] = "{} {}".format(
                        SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                        key,
                    )
                    bca_bill['virtualAccountData']['inquiryReason'] = {
                        "english": (
                            SnapReasonMultilanguage.INVALID_MANDATORY_FIELD.english.format(key)
                        ),
                        "indonesia": (
                            SnapReasonMultilanguage.INVALID_MANDATORY_FIELD.indonesia.format(key)
                        ),
                    }
                else:
                    bca_bill[
                        'responseCode'
                    ] = SnapInquiryResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
                    bca_bill['responseMessage'] = "{} {}".format(
                        SnapInquiryResponseCodeAndMessage.INVALID_FIELD_FORMAT.message,
                        key,
                    )
                    bca_bill['virtualAccountData']['inquiryReason'] = {
                        "english": (
                            SnapReasonMultilanguage.INVALID_FIELD_FORMAT.english.format(key)
                        ),
                        "indonesia": (
                            SnapReasonMultilanguage.INVALID_FIELD_FORMAT.indonesia.format(key)
                        ),
                    }
                self.kwargs['error_message'] = bca_bill["responseMessage"]
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=bca_bill)

            external_id = request.META.get('HTTP_X_EXTERNAL_ID')
            if not external_id:
                bca_bill[
                    'responseCode'
                ] = SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                bca_bill['responseMessage'] = "{} X-EXTERNAL-ID".format(
                    SnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message
                )
                bca_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                bca_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.NULL_EXTERNAL_ID.english,
                    "indonesia": SnapReasonMultilanguage.NULL_EXTERNAL_ID.indonesia,
                }
                self.kwargs['error_message'] = bca_bill["responseMessage"]
                return JsonResponse(status=HTTP_409_CONFLICT, data=bca_bill)
            last_path_url = urlparse(request.get_full_path()).path.split('/')[-1]
            key = 'bca_snap:{}:external_id:{}'.format(last_path_url, external_id)
            redis_client = get_redis_client()
            external_id_redis = redis_client.get(key)
            if external_id_redis:
                bca_bill[
                    'responseCode'
                ] = SnapInquiryResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.code
                bca_bill[
                    'responseMessage'
                ] = SnapInquiryResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.message
                bca_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                bca_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.DUPLICATE_EXTERNAL_ID.english,
                    "indonesia": SnapReasonMultilanguage.DUPLICATE_EXTERNAL_ID.indonesia,
                }
                self.kwargs['error_message'] = bca_bill["responseMessage"]
                return JsonResponse(status=HTTP_409_CONFLICT, data=bca_bill)

            payback_transaction = PaybackTransaction.objects.filter(
                transaction_id=data['inquiryRequestId'],
                is_processed=True,
            ).exists()
            if payback_transaction:
                bca_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.code
                bca_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.PAID_BILL.message
                bca_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                bca_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.PAID_BILL.english,
                    "indonesia": SnapReasonMultilanguage.PAID_BILL.indonesia,
                }
                self.kwargs['error_message'] = bca_bill["responseMessage"]
                return JsonResponse(status=HTTP_409_CONFLICT, data=bca_bill)
            virtual_account = data.get('virtualAccountNo').strip()
            query_filter = {'virtual_account': virtual_account}
            response_pii_lookup = pii_lookup(virtual_account)
            if response_pii_lookup:
                query_filter = {'virtual_account_tokenized__in': response_pii_lookup}
            payment_method = PaymentMethod.objects.filter(**query_filter).last()
            escrow_payment_method = None
            if not payment_method:
                escrow_payment_method = EscrowPaymentMethod.objects.filter(
                    virtual_account=virtual_account
                ).last()
            if not payment_method and not escrow_payment_method:
                bca_bill[
                    'responseCode'
                ] = SnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.code
                bca_bill[
                    'responseMessage'
                ] = SnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.message
                bca_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.FAILED
                bca_bill['virtualAccountData']['inquiryReason'] = {
                    "english": SnapReasonMultilanguage.VA_NOT_FOUND.english,
                    "indonesia": SnapReasonMultilanguage.VA_NOT_FOUND.indonesia,
                }
                self.kwargs['error_message'] = bca_bill["responseMessage"]
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=bca_bill)

            # check prohibited
            if is_payment_method_prohibited(payment_method or escrow_payment_method):
                bca_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.GENERAL_ERROR.code
                bca_bill[
                    'responseMessage'
                ] = SnapInquiryResponseCodeAndMessage.GENERAL_ERROR.message
                bca_bill['virtualAccountData']['inquiryStatus'] = ''
                bca_bill['virtualAccountData']['inquiryReason'] = {
                    "english": "",
                    "indonesia": "",
                }
                self.kwargs['error_message'] = bca_bill["responseMessage"]
                return JsonResponse(status=HTTP_500_INTERNAL_SERVER_ERROR, data=bca_bill)

            account = None
            if payment_method:
                account = get_account_from_payment_method(payment_method)

            bca_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.SUCCESS.code
            bca_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.SUCCESS.message
            bca_bill['virtualAccountData']['inquiryStatus'] = SnapStatus.SUCCESS
            bca_bill['virtualAccountData']['inquiryReason'] = {
                "english": SnapReasonMultilanguage.SUCCESS.english,
                "indonesia": SnapReasonMultilanguage.SUCCESS.indonesia,
            }
            bca_bill['virtualAccountData']['totalAmount']['currency'] = 'IDR'
            if account:
                # check deposit for rentee first
                bca_bill_deposit_rentee = get_snap_bca_rentee_deposit_bill(
                    account, payment_method, data, bca_bill
                )
                if bca_bill_deposit_rentee:
                    bca_bill = bca_bill_deposit_rentee
                else:
                    bca_bill = process_inquiry_for_j1(
                        bca_bill,
                        account,
                        payment_method,
                        data.get('inquiryRequestId'),
                        virtual_account,
                    )

            elif escrow_payment_method:
                bca_bill = process_inquiry_for_escrow(bca_bill, escrow_payment_method)
            else:
                bca_bill = process_inquiry_for_mtl_loan(
                    bca_bill, payment_method, virtual_account, data.get('inquiryRequestId')
                )

            payback_transaction = PaybackTransaction.objects.filter(
                transaction_id=data['inquiryRequestId'],
            ).first()
            if payback_transaction:
                self.kwargs['customer_id'] = (
                    payback_transaction.customer.id if payback_transaction.customer else None
                )
                self.kwargs['loan_id'] = (
                    payback_transaction.loan.id if payback_transaction.loan else None
                )
                self.kwargs['payback_transaction_id'] = payback_transaction.id

            return JsonResponse(data=bca_bill)
        except Exception as e:
            sentry_client.captureException()
            bca_bill['responseCode'] = SnapInquiryResponseCodeAndMessage.GENERAL_ERROR.code
            bca_bill['responseMessage'] = SnapInquiryResponseCodeAndMessage.GENERAL_ERROR.message
            bca_bill['virtualAccountData']['inquiryStatus'] = ''
            bca_bill['virtualAccountData']['inquiryReason'] = {
                "english": "",
                "indonesia": "",
            }
            self.kwargs['error_message'] = bca_bill["responseMessage"]
            return JsonResponse(status=HTTP_500_INTERNAL_SERVER_ERROR, data=bca_bill)


class BcaSnapPaymentFlagInvocationView(BaseSnapBcaView):
    permission_classes = (AllowAny,)
    serializer_class = []

    def post(self, request):
        response_data = {
            "responseCode": "",
            "responseMessage": "",
            "virtualAccountData": {
                "paymentFlagReason": {
                    "english": "",
                    "indonesia": ""
                },
                "partnerServiceId": request.data.get('partnerServiceId', ''),
                "customerNo": request.data.get('customerNo', ''),
                "virtualAccountNo": request.data.get('virtualAccountNo', ''),
                "virtualAccountName": request.data.get('virtualAccountName', ''),
                "virtualAccountEmail": request.data.get('virtualAccountEmail', ''),
                "virtualAccountPhone": request.data.get('virtualAccountPhone', ''),
                "trxId": request.data.get('trxId', ''),
                "paymentRequestId": request.data.get('paymentRequestId', ''),
                "paidAmount": {
                    "value": "",
                    "currency": ""
                },
                "paidBills": "",
                "totalAmount": {
                    "value": "",
                    "currency": ""
                },
                "trxDateTime": request.data.get('trxDateTime', ''),
                "referenceNo": request.data.get('referenceNo', ''),
                "journalNum": request.data.get('journalNum', ''),
                "paymentType": request.data.get('paymentType', ''),
                "flagAdvise": request.data.get('flagAdvise', ''),
                "paymentFlagStatus": "",
                "billDetails": [],
                "freeTexts": [
                    {
                        "english": "",
                        "indonesia": ""
                    }
                ]
            },
            "additionalInfo": {}
        }
        self._pre_log_request(request)
        relative_url = request.get_full_path()
        virtual_account = request.data.get('virtualAccountNo', '').strip()
        access_token = request.META.get('HTTP_AUTHORIZATION', '').split(' ')[-1]
        snap_expiry_token = get_snap_expiry_token(access_token, SnapVendorChoices.BCA)
        if not snap_expiry_token or is_expired_snap_token(snap_expiry_token,
                                                          EXPIRY_TIME_TOKEN_BCA_SNAP):
            response_data = {
                'responseCode': (BcaSnapPaymentResponseCodeAndMessage.
                                 INVALID_TOKEN.code),
                'responseMessage': (BcaSnapPaymentResponseCodeAndMessage.
                                    INVALID_TOKEN.message),
            }

            return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

        channel_id = request.META.get('HTTP_CHANNEL_ID')
        partner_id = request.META.get('HTTP_X_PARTNER_ID')
        if (
            channel_id != settings.BCA_SNAP_CHANNEL_ID_OUBTOND
            or partner_id != settings.BCA_SNAP_COMPANY_VA_OUTBOND
        ):
            response_data = {
                'responseCode': BcaSnapPaymentResponseCodeAndMessage.UNAUTHORIZED_CLIENT.code,
                'responseMessage': (
                    BcaSnapPaymentResponseCodeAndMessage.UNAUTHORIZED_CLIENT.message
                ),
            }
            self.kwargs['error_message'] = response_data["responseMessage"]

            return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

        channel_id = request.META.get('HTTP_CHANNEL_ID')
        partner_id = request.META.get('HTTP_X_PARTNER_ID')
        if (
            channel_id != settings.BCA_SNAP_CHANNEL_ID_OUBTOND
            or partner_id != settings.BCA_SNAP_COMPANY_VA_OUTBOND
        ):
            response_data = {
                'responseCode': (BcaSnapPaymentResponseCodeAndMessage.INVALID_TOKEN.code),
                'responseMessage': (BcaSnapPaymentResponseCodeAndMessage.INVALID_TOKEN.message),
            }
            self.kwargs['error_message'] = response_data["responseMessage"]

            return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

        data = request.data
        method = request.method
        x_signature = request.META.get('HTTP_X_SIGNATURE')
        headers = {
            "access_token": access_token,
            "content_type": request.META.get('CONTENT_TYPE'),
            "origin": request.META.get('HTTP_ORIGIN'),
            "x_timestamp": request.META.get('HTTP_X_TIMESTAMP'),
            "x_signature": x_signature
        }
        is_authenticated = authenticate_snap_request(
            headers, data, method, settings.BCA_SNAP_CLIENT_SECRET_INBOUND, relative_url
        )
        if not is_authenticated:
            response_data = {
                'responseCode': (BcaSnapPaymentResponseCodeAndMessage.
                                 UNAUTHORIZED_SIGNATURE.code),
                'responseMessage': (BcaSnapPaymentResponseCodeAndMessage.
                                    UNAUTHORIZED_SIGNATURE.message),
            }
            self.kwargs['error_message'] = response_data["responseMessage"]

            return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

        serializer = SnapBcaPaymentFlagSerializer(data=request.data)
        if not serializer.is_valid():
            key = list(serializer.errors.items())[0][0]
            errors = list(serializer.errors.items())[0][1][0]
            response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
            if errors in ErrorDetail.mandatory_field_errors():
                response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.\
                    INVALID_MANDATORY_FIELD.code
                response_data['responseMessage'] = "{} {}".format(
                    BcaSnapPaymentResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                    key,
                )
                response_data['virtualAccountData']['paymentFlagReason'] = {
                    "english": (
                        SnapReasonMultilanguage.INVALID_MANDATORY_FIELD.english.format(key)
                    ),
                    "indonesia": (
                        SnapReasonMultilanguage.INVALID_MANDATORY_FIELD.indonesia.format(key)
                    ),
                }
            else:
                response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.\
                    INVALID_FIELD_FORMAT.code
                response_data['responseMessage'] = "{} {}".format(
                    BcaSnapPaymentResponseCodeAndMessage.INVALID_FIELD_FORMAT.message,
                    key,
                )
                if key == 'paidAmount' and errors == 'Amount':
                    key = errors
                    response_data['responseMessage'] = "Invalid " + key
                    response_data['responseCode'] = '4042513'
                response_data['virtualAccountData']['paymentFlagReason'] = {
                    "english": SnapReasonMultilanguage.INVALID_FIELD_FORMAT.english.format(key),
                    "indonesia": (
                        SnapReasonMultilanguage.INVALID_FIELD_FORMAT.indonesia.format(key)
                    ),
                }
            self.kwargs['error_message'] = response_data["responseMessage"]
            return JsonResponse(status=HTTP_400_BAD_REQUEST, data=response_data)

        if float(data['paidAmount']['value']) < float(BcaConst.MINIMUM_TRANSFER_AMOUNT):
            response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.INVALID_AMOUNT.code
            response_data[
                'responseMessage'
            ] = BcaSnapPaymentResponseCodeAndMessage.INVALID_AMOUNT.message
            response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
            response_data['virtualAccountData']['paymentFlagReason'] = {
                "english": SnapReasonMultilanguage.INVALID_AMOUNT.english,
                "indonesia": SnapReasonMultilanguage.INVALID_AMOUNT.indonesia,
            }
            self.kwargs['error_message'] = response_data["responseMessage"]

            return JsonResponse(status=HTTP_401_UNAUTHORIZED, data=response_data)

        external_id = request.META.get('HTTP_X_EXTERNAL_ID')
        if not external_id:
            response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.\
                INVALID_MANDATORY_FIELD.code
            response_data['responseMessage'] = "{} X-EXTERNAL-ID".format(
                BcaSnapPaymentResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message
            )
            response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
            response_data['virtualAccountData']['paymentFlagReason'] = {
                "english": SnapReasonMultilanguage.NULL_EXTERNAL_ID.english,
                "indonesia": SnapReasonMultilanguage.NULL_EXTERNAL_ID.indonesia,
            }
            self.kwargs['error_message'] = response_data["responseMessage"]

            return JsonResponse(status=HTTP_409_CONFLICT, data=response_data)
        redis_client = get_redis_client()
        last_path_url = urlparse(request.get_full_path()).path.split('/')[-1]
        key = 'bca_snap:{}:external_id:{}'.format(last_path_url, external_id)
        raw_value = redis_client.get(key)
        if raw_value:
            redis_data = json.loads(raw_value)
            redis_virtual_account_data = redis_data.get('virtualAccountData', {})
            if redis_virtual_account_data.get('paymentRequestId') != data['paymentRequestId']:
                response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.\
                    EXTERNAL_ID_CONFLICT.code
                response_data['responseMessage'] = BcaSnapPaymentResponseCodeAndMessage.\
                    EXTERNAL_ID_CONFLICT.message
                response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
                response_data['virtualAccountData']['paymentFlagReason'] = {
                    "english": SnapReasonMultilanguage.DUPLICATE_EXTERNAL_ID.english,
                    "indonesia": SnapReasonMultilanguage.DUPLICATE_EXTERNAL_ID.indonesia,
                }
            else:
                response_data = redis_data
                response_data[
                    'responseCode'
                ] = BcaSnapPaymentResponseCodeAndMessage.INCONSISTENT_REQUEST.code
                response_data[
                    'responseMessage'
                ] = BcaSnapPaymentResponseCodeAndMessage.INCONSISTENT_REQUEST.message
            self.kwargs['error_message'] = response_data["responseMessage"]
            return JsonResponse(status=HTTP_409_CONFLICT, data=response_data)

        escrow_payment_method = EscrowPaymentMethod.objects.filter(
            virtual_account=virtual_account,
        )
        if escrow_payment_method:
            response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.SUCCESS.code
            response_data['responseMessage'] = BcaSnapPaymentResponseCodeAndMessage.SUCCESS.message
            response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.SUCCESS
            response_data['virtualAccountData']['paymentFlagReason'] = {
                "english": SnapReasonMultilanguage.SUCCESS.english,
                "indonesia": SnapReasonMultilanguage.SUCCESS.indonesia,
            }

            return JsonResponse(data=response_data)
        query_filter = {'virtual_account': virtual_account}
        response_pii_lookup = pii_lookup(virtual_account)
        if response_pii_lookup:
            query_filter = {'virtual_account_tokenized__in': response_pii_lookup}
        payment_method = PaymentMethod.objects.filter(**query_filter).last()
        if not payment_method:
            response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.\
                BILL_OR_VA_NOT_FOUND.code
            response_data['responseMessage'] = BcaSnapPaymentResponseCodeAndMessage.\
                BILL_OR_VA_NOT_FOUND.message
            response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
            response_data['virtualAccountData']['paymentFlagReason'] = {
                "english": SnapReasonMultilanguage.VA_NOT_FOUND.english,
                "indonesia": SnapReasonMultilanguage.VA_NOT_FOUND.indonesia,
            }
            self.kwargs['error_message'] = response_data["responseMessage"]
            return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

        account = payment_method.customer.account_set.last()
        account_payment = None
        if account:
            account_payment = account.get_oldest_unpaid_account_payment()
            if not account_payment:
                response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.PAID_BILL.code
                response_data[
                    'responseMessage'
                ] = BcaSnapPaymentResponseCodeAndMessage.PAID_BILL.message
                response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
                response_data['virtualAccountData']['paymentFlagReason'] = {
                    "english": SnapReasonMultilanguage.VA_NOT_HAVE_BILL.english,
                    "indonesia": SnapReasonMultilanguage.VA_NOT_HAVE_BILL.indonesia,
                }
                self.kwargs['error_message'] = response_data["responseMessage"]
                return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

        payment_request_id = data.get('paymentRequestId', '')
        payback_transaction = PaybackTransaction.objects.filter(
            payment_method=payment_method,
            transaction_id=payment_request_id).last()

        if not payback_transaction:
            msg = "There's error when hit API BCA: paymentRequestId {} not found.".format(
                payment_request_id
            )
            channel_name = get_channel_name_slack_for_payment_problem()
            notify_failure(msg, channel=channel_name)
            response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.\
                BILL_OR_VA_NOT_FOUND.code
            response_data['responseMessage'] = BcaSnapPaymentResponseCodeAndMessage.\
                BILL_OR_VA_NOT_FOUND.message
            response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
            response_data['virtualAccountData']['paymentFlagReason'] = {
                "english": SnapReasonMultilanguage.BILL_NOT_FOUND.english,
                "indonesia": SnapReasonMultilanguage.BILL_NOT_FOUND.indonesia,
            }
            self.kwargs['error_message'] = response_data["responseMessage"]

            return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

        elif payback_transaction.is_processed:
            response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.PAID_BILL.code
            response_data['responseMessage'] = BcaSnapPaymentResponseCodeAndMessage.\
                PAID_BILL.message
            response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.FAILED
            response_data['virtualAccountData']['paymentFlagReason'] = {
                "english": SnapReasonMultilanguage.PAID_BILL.english,
                "indonesia": SnapReasonMultilanguage.PAID_BILL.indonesia,
            }
            self.kwargs['error_message'] = response_data["responseMessage"]

            return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

        http_status_code = HTTP_500_INTERNAL_SERVER_ERROR
        response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.GENERAL_ERROR.code
        response_data['responseMessage'] = BcaSnapPaymentResponseCodeAndMessage.\
            GENERAL_ERROR.message
        response_data['virtualAccountData']['paymentFlagStatus'] = ''
        response_data['virtualAccountData']['paymentFlagReason'] = {
            "english": "",
            "indonesia": "",
        }
        try:
            self.kwargs['customer_id'] = (
                payback_transaction.customer.id if payback_transaction.customer else None
            )
            self.kwargs['loan_id'] = (
                payback_transaction.loan.id if payback_transaction.loan else None
            )
            self.kwargs['payback_transaction_id'] = payback_transaction.id
            self.kwargs['account_payment_id'] = account_payment.id if account_payment else None

            data_process_payment = {
                'PaidAmount': data['paidAmount']['value'],
                'trxDateTime': data['trxDateTime'],
            }
            bca_process_payment(payment_method, payback_transaction, data_process_payment)
            response_data['responseCode'] = BcaSnapPaymentResponseCodeAndMessage.SUCCESS.code
            response_data['responseMessage'] = BcaSnapPaymentResponseCodeAndMessage.SUCCESS.message
            response_data['virtualAccountData']['paymentFlagStatus'] = SnapStatus.SUCCESS
            response_data['virtualAccountData']['paymentFlagReason'] = {
                "english": SnapReasonMultilanguage.SUCCESS.english,
                "indonesia": SnapReasonMultilanguage.SUCCESS.indonesia,
            }
            response_data['virtualAccountData']['freeTexts'] = [
                {
                    "english": SnapReasonMultilanguage.SUCCESS.english,
                    "indonesia": SnapReasonMultilanguage.SUCCESS.indonesia,
                }
            ]
            response_data['virtualAccountData']["totalAmount"]["value"] = data['paidAmount'][
                'value'
            ]
            response_data['virtualAccountData']["totalAmount"]["currency"] = "IDR"
            response_data['virtualAccountData']["paidAmount"]["value"] = data['paidAmount']['value']
            response_data['virtualAccountData']["paidAmount"]["currency"] = "IDR"
            http_status_code = HTTP_200_OK
        except JuloException as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
        except Exception as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            self.kwargs['error_message'] = str(e)

        return JsonResponse(status=http_status_code, data=response_data)


#################################### END BCA Direct Settlement API ################################

class GopayMidtransEventCallbackView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request, *args, **kwargs):
        callback_data = request.data
        # 1 payout 1 callback
        transfer_id = callback_data['reference_no']
        transfer_status = callback_data['status']
        with transaction.atomic():
            cashback_transfer_transaction = \
                CashbackTransferTransaction.objects.select_for_update().filter(
                    transfer_id=transfer_id).exclude(
                    transfer_status__in=GopayConst.PAYOUT_END_STATUS).last()
            if cashback_transfer_transaction:
                update_data = {
                    'transfer_status': transfer_status
                }
                if transfer_status == GopayConst.PAYOUT_STATUS_COMPLETED:
                    update_data['fund_transfer_ts'] = timezone.now()
                cashback_transfer_transaction.update_safely(**update_data)
                gopay_service = GopayService()
                gopay_service.process_refund_cashback_gopay(
                    transfer_status, cashback_transfer_transaction, callback_data)

        if not cashback_transfer_transaction:
            gopay_transfer = get_loyalty_gopay_transfer_trx(transfer_id)
            if gopay_transfer:
                process_callback_gopay_transfer(gopay_transfer, callback_data)
            else:
                raise TransferflowNotFound

        logger.info({
            "action": "callback_from_midtrans_for_gopay",
            "response": {
                'transfer_id': transfer_id,
                'transfer_status': transfer_status,
            }
        })

        return LoggedResponse(data={'success': True})


class AyoconnectBeneficiaryCallbackView(APIView):
    """Endpoint for ayoconnect beneficiary callback"""
    permission_classes = (AllowAny,)
    svc = AyoconnectBeneficiaryCallbackService()
    serializer_class = BeneficiaryCallbackSuccessSerializer

    def is_successful_callback(self, request_body: dict) -> bool:
        code = int(request_body.get("code", HTTP_500_INTERNAL_SERVER_ERROR))
        if code not in {HTTP_200_OK, HTTP_201_CREATED}:
            return False
        return True

    def get_beneficiary_details(self, request_body: dict) -> dict:
        request_payload = request_body.get("details", {})
        request_payload["customerId"] = request_body.get("customerId", None)
        serializer = self.serializer_class(data=request_payload)
        serializer.is_valid(raise_exception=True)
        return convert_camel_to_snake(serializer.validated_data)

    def post(self, request):
        request_body = json.loads(request.body.decode('utf-8'))
        logger.info({
            "action": "AyoconnectBeneficiaryCallbackView.post",
            "payload": request.data
        })

        # if it's unsuccessful callback,
        # just request to add beneficiary again to ayoconnect
        if not self.is_successful_callback(request_body):
            serializer = BeneficiaryCallbackUnSuccessSerializer(data=request_body)
            serializer.is_valid(raise_exception=True)
            external_customer_id = serializer.data.get('customerId')
            error_code = self.svc.get_error_code_in_unsuccessful_callback(request_body)
            is_processed = self.svc.process_unsuccess_callback(external_customer_id, error_code)
            if not is_processed:
                return not_found_response(
                    message="External customer id {external_customer_id} not found".\
                        format(external_customer_id=external_customer_id))
            return success_response(data=serializer.data)

        self.svc.beneficiary_details = self.get_beneficiary_details(request_body=request_body)

        customer_data = self.svc.is_payment_gateway_customer_data_exists()
        if not customer_data:
            customer_id = self.svc.beneficiary_details.get("customer_id")
            beneficiary_id = self.svc.beneficiary_details.get("beneficiary_id")
            return not_found_response(
                message="payment_gateway_customer_data doesn't exist for customerId : {} and beneficiaryId: {}". \
                    format(customer_id, beneficiary_id))

        is_process_success, msg = self.svc.process_beneficiary(
            payment_gateway_customer_data=customer_data)

        if not is_process_success:
            return general_error_response(message=msg)

        return success_response(data=request_body)


class BaseSnapFaspayView(APIView):
    permission_classes = []
    authentication_classes = [FaspaySnapAuthentication]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, APIUnauthorizedError):
            return Response(status=exc.status_code, data=exc.detail)

        return super().handle_exception(exc)

    @csrf_exempt
    def dispatch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        raw_body = request.body
        response = super().dispatch(request, *args, **kwargs)
        self._log_request(raw_body, request, response)
        if hasattr(response, 'render'):
            response.render()
        if hasattr(response, 'content'):
            redis_client = get_redis_client()
            response_data = json.loads(response.content)
            external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
            last_path_url = urlparse(request.get_full_path()).path.split('/')[-1]
            key = 'faspay_snap:{}:external_id:{}'.format(last_path_url, external_id)
            external_id_redis = redis_client.get(key)
            if external_id and not external_id_redis:
                today_datetime = timezone.localtime(timezone.now())
                tomorrow_datetime = today_datetime + relativedelta(
                    days=1, hour=0, minute=0, second=0
                )
                redis_client.set(key, json.dumps(response_data), tomorrow_datetime - today_datetime)

        tz = pytz.timezone("Asia/Jakarta")
        now = datetime.datetime.now(tz=tz)
        response["X-TIMESTAMP"] = "{}+07:00".format(now.strftime("%Y-%m-%dT%H:%M:%S"))

        return response

    def _pre_log_request(
        self,
        request: Request,
    ) -> None:
        logger.info(
            {
                "action": "BaseSnapFaspayView",
                "action_group": "payment_api_requests",
                "endpoint": request.get_full_path(),
                "method": request.method,
                "virtual_account": request.data.get('virtualAccountNo', ''),
                "transaction_id": request.data.get('inquiryRequestId', '')
                or request.data.get('paymentRequestId', ''),
            }
        )

    def _log_request(
        self,
        request_body: bytes,
        request: Request,
        response: Response,
    ) -> None:
        timestamp = request.META.get('HTTP_X_TIMESTAMP', None)
        signature = request.META.get('HTTP_X_SIGNATURE', None)
        partner_id = request.META.get('HTTP_X_PARTNER_ID', None)
        external_id = request.META.get('HTTP_X_EXTERNAL_ID', None)
        channel_id = request.META.get('HTTP_CHANNEL_ID', None)

        headers = {
            'HTTP_X_TIMESTAMP': timestamp,
            'HTTP_X_SIGNATURE': signature,
            'HTTP_X_PARTNER_ID': partner_id,
            'HTTP_X_EXTERNAL_ID': external_id,
            'HTTP_CHANNEL_ID': channel_id,
        }

        data_to_log = {
            "action": "snap_faspay_api_view_logs",
            "headers": headers,
            "request_body": request_body.decode('utf-8'),
            "endpoint": request.get_full_path(),
            "method": request.method,
            "response_code": response.status_code,
            "response_data": response.__dict__,
        }
        if 400 <= response.status_code <= 499:
            logger.warning(data_to_log)
        elif 500 <= response.status_code <= 599:
            logger.error(data_to_log)
        else:
            logger.info(data_to_log)


class FaspaySnapInquiry(BaseSnapFaspayView):
    """This endpoint is a callback for faspay SNAP to
    forward user requests to inquire specific VA information.
    """

    def post(self, request):
        faspay_bill = {
            "responseCode": "",
            "responseMessage": "",
            "virtualAccountData": {
                "partnerServiceId": request.data.get('partnerServiceId', ''),
                "customerNo": request.data.get('customerNo', ''),
                "virtualAccountNo": request.data.get('virtualAccountNo', ''),
                "virtualAccountName": "",
                "virtualAccountEmail": "",
                "virtualAccountPhone": "",
                "inquiryRequestId": request.data.get('inquiryRequestId', ''),
                "totalAmount": {"value": "", "currency": ""},
            },
        }

        try:
            self._pre_log_request(request)
            data = request.data

            serializer = SnapFaspayInquiryBillsSerializer(data=data)
            if not serializer.is_valid():
                key = list(serializer.errors.items())[0][0]
                errors = list(serializer.errors.items())[0][1][0]
                if errors in ErrorDetail.mandatory_field_errors():
                    faspay_bill[
                        'responseCode'
                    ] = FaspaySnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                    faspay_bill['responseMessage'] = "{} {}".format(
                        FaspaySnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                        key,
                    )
                else:
                    faspay_bill[
                        'responseCode'
                    ] = FaspaySnapInquiryResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
                    faspay_bill['responseMessage'] = "{} {}".format(
                        FaspaySnapInquiryResponseCodeAndMessage.INVALID_FIELD_FORMAT.message,
                        key,
                    )
                return JsonResponse(status=HTTP_400_BAD_REQUEST, data=faspay_bill)

            is_vendor_match = check_payment_method_vendor(
                request.data.get('virtualAccountNo').strip()
            )

            if not is_vendor_match:
                faspay_bill[
                    'responseCode'
                ] = FaspaySnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.code
                faspay_bill[
                    'responseMessage'
                ] = FaspaySnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.message

                return JsonResponse(status=HTTP_404_NOT_FOUND, data=faspay_bill)

            external_id = request.META.get('HTTP_X_EXTERNAL_ID')
            if not external_id:
                faspay_bill[
                    'responseCode'
                ] = FaspaySnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                faspay_bill['responseMessage'] = "{} X-EXTERNAL-ID".format(
                    FaspaySnapInquiryResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message
                )
                return JsonResponse(status=HTTP_409_CONFLICT, data=faspay_bill)

            last_path_url = urlparse(request.get_full_path()).path.split('/')[-1]
            key = 'faspay_snap:{}:external_id:{}'.format(last_path_url, external_id)
            redis_client = get_redis_client()
            raw_value = redis_client.get(key)
            if raw_value:
                redis_data = json.loads(raw_value)
                redis_virtual_account_data = redis_data.get('virtualAccountData', {})
                if redis_virtual_account_data.get('inquiryRequestId') != data['inquiryRequestId']:
                    faspay_bill[
                        'responseCode'
                    ] = FaspaySnapInquiryResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.code
                    faspay_bill[
                        'responseMessage'
                    ] = FaspaySnapInquiryResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.message
                    return JsonResponse(status=HTTP_409_CONFLICT, data=faspay_bill)

            virtual_account = data.get('virtualAccountNo').strip()
            payment_method = PaymentMethod.objects.filter(virtual_account=virtual_account).first()

            if payment_method is None:
                faspay_bill[
                    'responseCode'
                ] = FaspaySnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.code
                faspay_bill[
                    'responseMessage'
                ] = FaspaySnapInquiryResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.message

                return JsonResponse(status=HTTP_404_NOT_FOUND, data=faspay_bill)

            if is_payment_method_prohibited(payment_method):
                faspay_bill[
                    'responseCode'
                ] = FaspaySnapInquiryResponseCodeAndMessage.GENERAL_ERROR.code
                faspay_bill[
                    'responseMessage'
                ] = FaspaySnapInquiryResponseCodeAndMessage.GENERAL_ERROR.message

                return JsonResponse(status=HTTP_500_INTERNAL_SERVER_ERROR, data=faspay_bill)

            loan = get_deposit_loan(payment_method.customer) or get_active_loan(payment_method)
            line_of_credit = payment_method.line_of_credit
            account = get_account_from_payment_method(payment_method)

            faspay_bill['responseCode'] = FaspaySnapInquiryResponseCodeAndMessage.SUCCESS.code
            faspay_bill['responseMessage'] = FaspaySnapInquiryResponseCodeAndMessage.SUCCESS.message
            faspay_bill['virtualAccountData']['totalAmount']['currency'] = 'IDR'
            amount = 0
            if account:
                faspay_bill, amount = faspay_snap_payment_inquiry_account(
                    account, payment_method, faspay_bill
                )
            else:
                if loan is not None:
                    if loan.__class__ is Loan:
                        faspay_bill, amount = faspay_snap_payment_inquiry_loan(
                            loan, payment_method, faspay_bill
                        )
                    elif loan.__class__ is Statement:
                        faspay_bill, amount = faspay_snap_payment_inquiry_statement(
                            loan, payment_method, faspay_bill
                        )
                if line_of_credit is not None:
                    faspay_bill, amount = faspay_snap_payment_inquiry_loc(
                        line_of_credit, payment_method, faspay_bill
                    )

            if (
                amount == 0
                or faspay_bill['responseCode']
                != FaspaySnapInquiryResponseCodeAndMessage.SUCCESS.code
            ):
                return JsonResponse(status=HTTP_404_NOT_FOUND, data=faspay_bill)

            payback_transaction = PaybackTransaction.objects.get_or_none(
                inquiry_request_id=data['inquiryRequestId']
            )
            if not payback_transaction:
                create_faspay_payback(
                    transaction_id=None,
                    amount=amount,
                    payment_method=payment_method,
                    inquiry_request_id=data['inquiryRequestId'],
                )
            elif payback_transaction.is_processed:
                faspay_bill['responseCode'] = FaspaySnapInquiryResponseCodeAndMessage.BILL_PAID.code
                faspay_bill[
                    'responseMessage'
                ] = FaspaySnapInquiryResponseCodeAndMessage.BILL_PAID.message

                return JsonResponse(status=HTTP_404_NOT_FOUND, data=faspay_bill)

            return JsonResponse(data=faspay_bill)
        except Exception:
            sentry_client.captureException()
            faspay_bill['responseCode'] = FaspaySnapInquiryResponseCodeAndMessage.GENERAL_ERROR.code
            faspay_bill[
                'responseMessage'
            ] = FaspaySnapInquiryResponseCodeAndMessage.GENERAL_ERROR.message
            return JsonResponse(status=HTTP_500_INTERNAL_SERVER_ERROR, data=faspay_bill)


class CommProxyBaseView(StandardizedExceptionHandlerMixinV2, APIView):
    """
    Base class for all views that require CommProxy authentication.
    CommProxy is a middleware API that acts as proxy between the client and
    the 3rd party MVP comm service.
    """

    authentication_classes = [CommProxyAuthentication]
    permission_classes = [IsSourceAuthenticated]


class CallCustomerCootekView(CommProxyBaseView):
    """
    Endpoint to call customer via Cootek.
    """
    serializer_class = CallCustomerCootekRequestSerializer

    def post(self, request):
        from juloserver.cootek.tasks import process_call_customer_via_cootek

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response("invalid request body", data=serializer.errors)

        task = process_call_customer_via_cootek.delay(
            request.request_source,
            serializer.validated_data,
        )
        return success_response({'task_id': task.id})


class CallCustomerNexmoView(CommProxyBaseView):
    """
    Endpoint to call customer via Cootek.
    """
    serializer_class = CallCustomerNexmoRequestSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response("invalid request body", data=serializer.errors)

        now = timezone.localtime(timezone.now())
        task = process_call_customer_via_nexmo.delay(
            now,
            request.request_source,
            serializer.validated_data,
        )
        return success_response({'task_id': task.id})


class CallCustomerAiRudderPDSView(CommProxyBaseView):
    """
    Endpoint to call customer via AiRudder PDS.
    """

    serializer_class = CallCustomerAiRudderRequestSerializer
    REDIS_PREFIX_TEMPORARY_DATA = "comm_proxy::send_airudder_task::"
    REDIS_EXPIRY_DURATION = 6 * 3600  # 6 hours

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response("invalid request body", data=serializer.errors)

        request_data = serializer.validated_data
        dialer_task_type = "{}|{}|{}".format(
            request.request_source,
            request_data.get("bucket_name"),
            request_data.get("batch_number"),
        )

        # Store the data to redis for background process
        redis_key = "{}{}".format(self.REDIS_PREFIX_TEMPORARY_DATA, dialer_task_type)
        redis_client = get_redis_client()
        redis_client.set(redis_key, json.dumps(request.data), ex=self.REDIS_EXPIRY_DURATION)

        # publish async celery task to send data to AiRudder
        dialer_task = DialerTask.objects.create(
            vendor=DialerSystemConst.AI_RUDDER_PDS,
            type=dialer_task_type,
            error='',
        )
        from juloserver.minisquad.tasks2.dialer_system_task import (
            send_airudder_request_data_to_airudder,
        )

        send_airudder_request_data_to_airudder.delay(dialer_task.id, redis_key)

        return success_response({'dialer_task_id': dialer_task.id})


class FaspaySnapPaymentView(BaseSnapFaspayView):
    def post(self, request):
        response_data = {
            "responseCode": "",
            "responseMessage": "",
            "virtualAccountData": {
                "partnerServiceId": request.data.get('partnerServiceId', ''),
                "customerNo": request.data.get('customerNo', ''),
                "virtualAccountNo": request.data.get('virtualAccountNo', ''),
                "virtualAccountName": request.data.get('virtualAccountName', ''),
                "paymentRequestId": request.data.get('paymentRequestId', ''),
                "paidAmount": {"value": "", "currency": ""},
            },
        }

        self._pre_log_request(request)
        data = request.data
        serializer = SnapFaspayPaymentFlagSerializer(data=data)
        if not serializer.is_valid():
            key = list(serializer.errors.items())[0][0]
            errors = list(serializer.errors.items())[0][1][0]
            if errors in ErrorDetail.mandatory_field_errors():
                response_data[
                    'responseCode'
                ] = FaspaySnapPaymentResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
                response_data['responseMessage'] = "{} {}".format(
                    FaspaySnapPaymentResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message,
                    key,
                )
            else:
                response_data[
                    'responseCode'
                ] = FaspaySnapPaymentResponseCodeAndMessage.INVALID_FIELD_FORMAT.code
                response_data['responseMessage'] = "{} {}".format(
                    FaspaySnapPaymentResponseCodeAndMessage.INVALID_FIELD_FORMAT.message,
                    key,
                )
                if key == 'paidAmount' and errors == 'Amount':
                    response_data[
                        'responseMessage'
                    ] = FaspaySnapPaymentResponseCodeAndMessage.INVALID_AMOUNT.message
                    response_data[
                        'responseCode'
                    ] = FaspaySnapPaymentResponseCodeAndMessage.INVALID_AMOUNT.code

            return JsonResponse(status=HTTP_400_BAD_REQUEST, data=response_data)

        external_id = request.META.get('HTTP_X_EXTERNAL_ID')
        if not external_id:
            response_data[
                'responseCode'
            ] = FaspaySnapPaymentResponseCodeAndMessage.INVALID_MANDATORY_FIELD.code
            response_data['responseMessage'] = "{} X-EXTERNAL-ID".format(
                FaspaySnapPaymentResponseCodeAndMessage.INVALID_MANDATORY_FIELD.message
            )
            return JsonResponse(status=HTTP_409_CONFLICT, data=response_data)
        last_path_url = urlparse(request.get_full_path()).path.split('/')[-1]
        key = 'faspay_snap:{}:external_id:{}'.format(last_path_url, external_id)
        redis_client = get_redis_client()
        raw_value = redis_client.get(key)
        if raw_value:
            redis_data = json.loads(raw_value)
            redis_virtual_account_data = redis_data.get('virtualAccountData', {})
            if redis_virtual_account_data.get('paymentRequestId') != data['paymentRequestId']:
                response_data[
                    'responseCode'
                ] = FaspaySnapPaymentResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.code
                response_data[
                    'responseMessage'
                ] = FaspaySnapPaymentResponseCodeAndMessage.EXTERNAL_ID_CONFLICT.message
            else:
                response_data = redis_data
                response_data[
                    'responseCode'
                ] = FaspaySnapPaymentResponseCodeAndMessage.INCONSISTENT_REQUEST.code
                response_data[
                    'responseMessage'
                ] = FaspaySnapPaymentResponseCodeAndMessage.INCONSISTENT_REQUEST.message
            return JsonResponse(status=HTTP_409_CONFLICT, data=response_data)

        virtual_account = request.data.get('virtualAccountNo', '').strip()
        payment_method = PaymentMethod.objects.filter(virtual_account=virtual_account).last()
        if not payment_method:
            response_data[
                'responseCode'
            ] = FaspaySnapPaymentResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.code
            response_data[
                'responseMessage'
            ] = FaspaySnapPaymentResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.message

            return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

        account = payment_method.customer.account_set.last()
        if account:
            response_data['virtualAccountData']['virtualAccountName'] = account.customer.fullname
            account_payment = account.get_oldest_unpaid_account_payment()
            if not account_payment:
                response_data[
                    'responseCode'
                ] = FaspaySnapPaymentResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.code
                response_data[
                    'responseMessage'
                ] = FaspaySnapPaymentResponseCodeAndMessage.BILL_OR_VA_NOT_FOUND.message

                return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

        payment_request_id = data.get('paymentRequestId', '')
        payback_transaction = PaybackTransaction.objects.filter(
            payment_method=payment_method, inquiry_request_id=payment_request_id
        ).last()

        if not payback_transaction:
            msg = "There's error when hit API snap Faspay: paymentRequestId {} not found.".format(
                payment_request_id
            )
            channel_name = get_channel_name_slack_for_payment_problem()
            notify_failure(msg, channel=channel_name)
            response_data[
                'responseCode'
            ] = FaspaySnapPaymentResponseCodeAndMessage.TRANSACTION_NOT_FOUND.code
            response_data[
                'responseMessage'
            ] = FaspaySnapPaymentResponseCodeAndMessage.TRANSACTION_NOT_FOUND.message

            return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)
        elif payback_transaction.is_processed:
            msg = "There's error when hit API snap Faspay: paymentRequestId {} not found.".format(
                payment_request_id
            )
            channel_name = get_channel_name_slack_for_payment_problem()
            notify_failure(msg, channel=channel_name)
            response_data[
                'responseCode'
            ] = FaspaySnapPaymentResponseCodeAndMessage.TRANSACTION_NOT_FOUND.code
            response_data[
                'responseMessage'
            ] = FaspaySnapPaymentResponseCodeAndMessage.TRANSACTION_NOT_FOUND.message

            return JsonResponse(status=HTTP_404_NOT_FOUND, data=response_data)

        try:
            with transaction.atomic():
                payback_transaction.update_safely(
                    transaction_id=data['referenceNo'], amount=float(data['paidAmount']['value'])
                )

            response_data['responseCode'] = FaspaySnapPaymentResponseCodeAndMessage.SUCCESS.code
            response_data[
                'responseMessage'
            ] = FaspaySnapPaymentResponseCodeAndMessage.SUCCESS.message

            response_data['virtualAccountData']["paidAmount"]["value"] = data['paidAmount']['value']
            response_data['virtualAccountData']["paidAmount"]["currency"] = "IDR"
        except Exception as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            response_data[
                'responseCode'
            ] = FaspaySnapPaymentResponseCodeAndMessage.TRANSACTION_NOT_FOUND.code
            response_data[
                'responseMessage'
            ] = FaspaySnapPaymentResponseCodeAndMessage.TRANSACTION_NOT_FOUND.message
            return JsonResponse(data=response_data, status=HTTP_500_INTERNAL_SERVER_ERROR)

        return JsonResponse(data=response_data, status=HTTP_200_OK)
