import os
import time
import pyotp
import logging
import binascii
import json
import math
import hashlib
import base64

from dateutil.relativedelta import relativedelta
from requests.exceptions import Timeout
from django.conf import settings
from django.db.utils import IntegrityError
from django.utils import timezone
from django.db import transaction
from django.db.models import (
    Q,
    Prefetch,
    F
)
from juloserver.dana.utils import round_half_up
from django.template import Context, Template
from rest_framework.response import Response
import rest_framework.status as http_status_codes
from datetime import (
    timedelta,
    datetime
)
from babel.dates import format_date, format_datetime
from typing import Dict, List, Tuple
from django.template.loader import render_to_string
from juloserver.julo.tasks import send_sms_otp_token
from juloserver.merchant_financing.web_app.constants import FIXED_DPD
from juloserver.otp.constants import (
    OTPType,
    SessionTokenAction,
    otp_validate_message_map,
    OTPValidateStatus,
    OTPRequestStatus,
)
from juloserver.otp.tasks import send_email_otp_token
from juloserver.otp.services import check_otp_request_is_active
import juloserver.pin.services as pin_services
from juloserver.julo.models import (
    Customer, Application, EmailHistory, FeatureSetting, MobileFeatureSetting, OtpRequest,
    ProductLookup, SmsHistory, Bank, PartnerBankAccount, JobType, Loan
)
from juloserver.julo.constants import (FeatureNameConst, WorkflowConst, VendorConst)
from juloserver.julo.exceptions import SmsNotSent
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.services2 import get_redis_client
from juloserver.customer_module.models import (
    BankAccountDestination, BankAccountCategory)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.disbursement.models import NameBankValidation
from juloserver.partnership.constants import (
    ErrorMessageConst,
    LoanDurationType, PartnershipEmailHistory,
    PartnershipRedisPrefixKey,
    PhoneNumberFormat,
    PaylaterUserAction,
    PartnershipFeatureNameConst,
)
from juloserver.partnership.leadgenb2b.onboarding.services import is_income_in_range_leadgen_partner
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType
from juloserver.standardized_api_response.utils import (general_error_response,
                                                        success_response,
                                                        request_timeout_response,
                                                        created_response)
from juloserver.julo.utils import (
    display_rupiah,
    format_mobile_phone,
    generate_email_key,
    format_nexmo_voice_phone_number
)
from juloserver.partnership.utils import (
    parse_phone_number_format,
    partnership_detokenize_sync_object_model,
    generate_pii_filter_query_partnership,
)
from juloserver.partnership.models import (
    PartnershipCustomerData,
    PartnershipCustomerDataOTP,
    PartnershipSessionInformation,
    PartnershipApplicationData,
    PartnershipLoanExpectation,
    PartnershipTransaction,
    PartnershipUserOTPAction,
    PartnershipConfig,
    PaylaterTransaction,
    PartnershipFeatureSetting,
)
from juloserver.julo.models import Partner
from juloserver.julo.tasks import send_sms_otp_partnership
from juloserver.partnership.exceptions import PartnershipWebviewException
from juloserver.partnership.clients.clients import LinkAjaClient
from juloserver.partnership.services.services import (
    process_create_loan,
    track_partner_session_status,
    is_income_in_range_agent_assisted_partner,
)
from juloserver.partnership.constants import LinkajaPages, j1_reapply_status
from juloserver.julo.services import (prevent_web_login_cases_check,
                                      link_to_partner_if_exists)
from juloserver.standardized_api_response.utils import unauthorized_error_response
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.streamlined_communication.models import StreamlinedCommunication
from juloserver.streamlined_communication.constant import CommunicationPlatform, CardProperty
from juloserver.streamlined_communication.services import process_convert_params_to_data
from juloserver.streamlined_communication.cache import RedisCache
from juloserver.julo.services2.high_score import feature_high_score_full_bypass
from juloserver.apiv2.services import (
    get_eta_time_for_c_score_delay)
from juloserver.income_check.services import is_income_in_range
from juloserver.julo_privyid.services.privy_services import get_info_cards_privy
from juloserver.application_flow.services import (
    JuloOneService
)
from juloserver.streamlined_communication.utils import add_thousand_separator, format_date_indo
from juloserver.streamlined_communication.services import is_info_card_expired, \
    is_already_have_transaction
from juloserver.sdk.services import is_customer_has_good_payment_histories
from juloserver.account.constants import AccountConstant
from juloserver.julo.workflows2.tasks import do_advance_ai_id_check_task
from juloserver.application_flow.services import is_experiment_application
from juloserver.apiv2.services import check_iti_repeat
from juloserver.boost.services import check_scrapped_bank
from juloserver.income_check.services import check_salary_izi_data
from juloserver.apiv2.models import EtlJob
from juloserver.ana_api.models import SdBankAccount, SdBankStatementDetail
from juloserver.monitors.notifications import notify_failed_hit_api_partner
from juloserver.pin.models import LoginAttempt
from juloserver.pin.constants import SUSPICIOUS_LOGIN_CHECK_CLASSES
from juloserver.pin.services import CustomerPinService
from juloserver.pin.tasks import send_reset_pin_email
from juloserver.apiv1.serializers import (CustomerSerializer,
                                          ApplicationSerializer,
                                          PartnerReferralSerializer)
from juloserver.loan.exceptions import LoanDbrException
from juloserver.partnership.tasks import leadgen_send_email_otp_token_register

logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()


def whitelabel_otp_request(email, phone, action_type=SessionTokenAction.PAYLATER_LINKING):
    mfs = MobileFeatureSetting.objects.get_or_none(feature_name='mobile_phone_1_otp')
    if not mfs.is_active:
        return Response(
            data={
                "success": True,
                "content": {
                    "active": mfs.is_active,
                    "parameters": mfs.parameters,
                    "message": "Verifikasi kode tidak aktif"
                }
            }
        )
    change_sms_provide = False
    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = mfs.parameters['wait_time_seconds']
    otp_max_request = mfs.parameters['otp_max_request']
    otp_resend_time = mfs.parameters['otp_resend_time']
    data = {
        "success": True,
        "content": {
            "active": mfs.is_active,
            "parameters": mfs.parameters,
            "message": "sms sent is rejected",
            "expired_time": None,
            "resend_time": None,
            "otp_max_request": otp_max_request,
            "retry_count": 0,
            "current_time": curr_time
        }
    }
    possible_phone_numbers = {
        format_mobile_phone(phone),
        format_nexmo_voice_phone_number(phone),
    }

    customer = Customer.objects.filter(
        email=email.lower(), phone__in=possible_phone_numbers
    ).last()
    if not customer:
        customer = Customer.objects.filter(phone__in=possible_phone_numbers).last()
        if not customer:
            data["success"] = False
            data["content"]["message"] = ErrorMessageConst.CUSTOMER_NOT_FOUND
            return Response(data=data)

    existing_otp_request = (
        OtpRequest.objects.filter(
            customer=customer,
            is_used=False,
            phone_number=phone,
            action_type=action_type,
        )
        .order_by("id")
        .last()
    )

    if existing_otp_request and existing_otp_request.is_active:
        sms_history = existing_otp_request.sms_history
        prev_time = sms_history.cdate if sms_history else existing_otp_request.cdate
        expired_time = timezone.localtime(
            existing_otp_request.cdate) + timedelta(seconds=otp_wait_seconds)
        resend_time = timezone.localtime(prev_time) + timedelta(seconds=otp_resend_time)
        retry_count = SmsHistory.objects.filter(
            customer=customer, cdate__gte=existing_otp_request.cdate
        ).exclude(status='UNDELIV').count()
        retry_count += 1

        data['content']['expired_time'] = expired_time
        data['content']['resend_time'] = resend_time
        data['content']['retry_count'] = retry_count
        if sms_history and sms_history.status == 'Rejected':
            data['content']['resend_time'] = expired_time
            return Response(
                data=data
            )
        if retry_count > otp_max_request:
            data['content']['message'] = "excedded the max request"
            return Response(
                data=data
            )

        if curr_time < resend_time:
            data['content']['message'] = "requested OTP less than resend time"
            return Response(
                data=data
            )

        if curr_time > resend_time and sms_history and \
                sms_history.comms_provider and sms_history.comms_provider.provider_name:
            if sms_history.comms_provider.provider_name.lower() == VendorConst.MONTY:
                change_sms_provide = True

        if not sms_history:
            change_sms_provide = True

        otp_request = existing_otp_request
    else:
        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        postfixed_request_id = str(customer.id) + str(int(time.time()))
        otp = str(hotp.at(int(postfixed_request_id)))

        current_application = Application.objects.regular_not_deletes().filter(
            customer=customer, workflow__name=WorkflowConst.JULO_ONE
        ).last()
        otp_request = OtpRequest.objects.create(
            customer=customer,
            request_id=postfixed_request_id,
            otp_token=otp,
            application=current_application,
            phone_number=phone,
            action_type=action_type,
        )
        data['content']['message'] = "Kode verifikasi sudah dikirim"
        data['content']['expired_time'] = timezone.localtime(otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds)
        data['content']['retry_count'] = 1

    text_message = render_to_string(
        'sms_otp_token_paylater_linking.txt', context={'otp_token': otp_request.otp_token})
    try:
        send_sms_otp_token.delay(
            phone, text_message, customer.id, otp_request.id, change_sms_provide)
        data['content']['resend_time'] = timezone.localtime(timezone.now()) + timedelta(
            seconds=otp_resend_time)
    except SmsNotSent:
        logger.error({
            "status": "sms_not_sent",
            "customer": customer.id,
            "phone": phone,
        })
        return Response(
            status=http_status_codes.HTTP_400_BAD_REQUEST,
            data={
                "success": False,
                "content": {},
                "error_message": "Kode verifikasi belum dapat dikirim"})

    return Response(
        data=data
    )


def whitelabel_otp_validation(
    email: str, otp_token: str, kwargs: dict, phone: str = "", otp_type: str = OTPType.SMS,
    action_type: str = "",
    paylater_transaction_xid: str = "",
) -> Response:
    paylater_transaction = None
    if paylater_transaction_xid:
        paylater_transaction = PaylaterTransaction.objects.filter(
            paylater_transaction_xid=paylater_transaction_xid
        ).last()
    if otp_type == OTPType.SMS:
        feature_setting = MobileFeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.MOBILE_PHONE_1_OTP
        )
        if not feature_setting.is_active:
            return Response(
                data={
                    "success": True,
                    "content": {
                        "active": feature_setting.is_active,
                        "parameters": feature_setting.parameters,
                        "message": "Verifikasi kode tidak aktif",
                    },
                }
            )
        possible_phone_numbers = {
            format_mobile_phone(phone),
            format_nexmo_voice_phone_number(phone),
        }
        customer = Customer.objects.filter(phone__in=possible_phone_numbers).last()
        if not customer:
            customer = Customer.objects.get_or_none(email=email.lower())
        if not customer:
            return Response(
                status=http_status_codes.HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": ErrorMessageConst.CUSTOMER_NOT_FOUND
                }
            )
        phone = format_mobile_phone(phone)
        existing_otp_request = OtpRequest.objects.filter(
            customer=customer,
            is_used=False,
            action_type=SessionTokenAction.PAYLATER_LINKING,
        ).last()
    elif otp_type == OTPType.EMAIL:
        feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.EMAIL_OTP
        )
        if not feature_setting or not feature_setting.is_active:
            return Response(
                data={
                    "success": True,
                    "content": {
                        "active": feature_setting.is_active,
                        "parameters": feature_setting.parameters,
                        "message": "Verifikasi kode tidak aktif",
                    },
                }
            )
        customer = Customer.objects.filter(email=email.lower()).last()
        if not paylater_transaction:
            return Response(
                status=http_status_codes.HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": ErrorMessageConst.INVALID_PAYLATER_TRANSACTION_XID,
                },
            )

        if not customer and not paylater_transaction:
            return Response(
                status=http_status_codes.HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": ErrorMessageConst.CUSTOMER_NOT_FOUND,
                },
            )
        if paylater_transaction:
            otp_request_det = {
                "customer": None,
                "is_used": False,
                "action_type": action_type if action_type else SessionTokenAction.PAYLATER_LINKING,
            }
        else:
            otp_request_det = {
                "customer": customer,
                "email": email,
                "is_used": False,
                "action_type": action_type if action_type else SessionTokenAction.PAYLATER_LINKING,
            }

        existing_otp_request = OtpRequest.objects.filter(**otp_request_det).last()
    else:
        return Response(
            status=http_status_codes.HTTP_400_BAD_REQUEST,
            data={
                "success": False,
                "content": {},
                "error_message": "OTP Type tidak ditemukan"
            }
        )
    error_details = {"otp_token": otp_token, "email": email, "phone": phone, "otp_type": otp_type}

    if paylater_transaction:
        error_details['paylater_transaction'] = paylater_transaction_xid
    else:
        error_details['customer'] = customer.id
    if not existing_otp_request:
        error_details['status'] = "otp_token_not_found"
        logger.error(error_details)
        return Response(
            status=http_status_codes.HTTP_400_BAD_REQUEST,
            data={
                "success": False,
                "content": {},
                "error_message": "Kode verifikasi belum terdaftar",
            },
        )
    if paylater_transaction:
        if str(paylater_transaction.id) not in existing_otp_request.request_id:
            error_details['status'] = "request_id_failed"
            error_details['otp_request'] = existing_otp_request.id
            logger.error(error_details)
            return Response(
                status=http_status_codes.HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Kode verifikasi tidak valid",
                },
            )
    else:
        if customer and str(customer.id) not in existing_otp_request.request_id:
            error_details['status'] = "request_id_failed"
            error_details['otp_request'] = existing_otp_request.id
            logger.error(error_details)
            return Response(
                status=http_status_codes.HTTP_400_BAD_REQUEST,
                data={
                    "success": False,
                    "content": {},
                    "error_message": "Kode verifikasi tidak valid",
                },
            )

    msg = check_is_valid_otp_token_and_retry_attempt(
        existing_otp_request, feature_setting, otp_token
    )
    if msg:
        return Response(
            status=http_status_codes.HTTP_400_BAD_REQUEST,
            data={
                "success": False,
                "content": {},
                "error_message": msg})

    hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
    valid_token = hotp.verify(otp_token, int(existing_otp_request.request_id))
    if not valid_token:
        error_details['status'] = "invalid_token"
        error_details['otp_request'] = existing_otp_request.id
        logger.error(error_details)
        return Response(
            status=http_status_codes.HTTP_400_BAD_REQUEST,
            data={"success": False, "content": {}, "error_message": "Kode verifikasi tidak valid"},
        )

    if not existing_otp_request.is_active:
        error_details['status'] = "otp_token_expired"
        error_details['otp_request'] = existing_otp_request.id
        logger.error(error_details)
        return Response(
            status=http_status_codes.HTTP_400_BAD_REQUEST,
            data={
                "success": False,
                "content": {},
                "error_message": "Waktu sudah habis silahkan kirim ulang kode OTP",
            },
        )
    existing_otp_request.is_used = True
    existing_otp_request.save(update_fields=['is_used'])
    if kwargs['validated_paylater_transaction_xid']:
        partner = Partner.objects.filter(
            name=kwargs['validated_partner_name'], is_active=True
        ).last()
        application = Application.objects.filter(customer=customer).only('application_xid').last()
        if partner and application:
            track_partner_session_status(
                partner,
                PaylaterUserAction.VERIFY_OTP,
                kwargs['validated_partner_reference_id'],
                application.application_xid,
                kwargs['validated_paylater_transaction_xid'],
            )
    return Response(
        data={
            "success": True,
            "content": {
                "active": feature_setting.is_active,
                "parameters": feature_setting.parameters,
                "message": "Kode verifikasi berhasil diverifikasi"
            }
        }
    )


def populate_bank_account_destination(application_id, partner, paylater_transaction_xid=''):
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        raise JuloException("Application Not found for Back account Destination")
    partnership_bank_account = PartnerBankAccount.objects.filter(
        partner=partner
    ).last()
    if partnership_bank_account and partnership_bank_account.name_bank_validation_id:
        data = {
            'category': BankAccountCategoryConst.PARTNER
        }
        if paylater_transaction_xid:
            data['category'] = BankAccountCategoryConst.ECOMMERCE

        partner_category = BankAccountCategory.objects.get(**data)
        name_bank_validation = NameBankValidation.objects.get_or_none(
            pk=partnership_bank_account.name_bank_validation_id
        )
        bank_partner = Bank.objects.get(xfers_bank_code=name_bank_validation.bank_code)
        BankAccountDestination.objects.create(
            bank_account_category=partner_category,
            customer=application.customer,
            bank=bank_partner,
            account_number=partnership_bank_account.bank_account_number,
            name_bank_validation_id=partnership_bank_account.name_bank_validation_id,
            description="{} partner checkout".format(partner.name)
        )


def is_back_account_destination_linked(application, partner, paylater_transaction_xid=''):
    if not application:
        raise JuloException("Application Not found for Back account Destination")
    data = {
        'category': BankAccountCategoryConst.PARTNER
    }
    if paylater_transaction_xid:
        data['category'] = BankAccountCategoryConst.ECOMMERCE

    partner_category = BankAccountCategory.objects.get(**data)
    partnership_bank_account = PartnerBankAccount.objects.filter(
        partner=partner
    ).last()
    if partnership_bank_account and partnership_bank_account.name_bank_validation_id:
        name_bank_validation = NameBankValidation.objects.get_or_none(
            pk=partnership_bank_account.name_bank_validation_id
        )
        bank_partner = Bank.objects.get(xfers_bank_code=name_bank_validation.bank_code)
        return BankAccountDestination.objects.filter(
            bank_account_category=partner_category,
            customer=application.customer,
            bank=bank_partner,
            account_number=partnership_bank_account.bank_account_number,
            name_bank_validation_id=partnership_bank_account.name_bank_validation_id,
            description="{} partner checkout".format(partner.name)
        ).exists()
    return False


def send_otp_webview(phone, partner_name, nik):
    mfs = MobileFeatureSetting.objects.get_or_none(feature_name='mobile_phone_1_otp')
    if not mfs.is_active:
        return success_response(
            data={
                "content": {
                    "message": "Verifikasi kode otp tidak aktif"
                }
            }
        )
    otp_wait_seconds = mfs.parameters['wait_time_seconds']
    otp_max_request = mfs.parameters['otp_max_request']
    otp_resend_time = mfs.parameters['otp_resend_time']
    return_data = {
        "message": None,
        "content": {
            "parameters": {
                "otp_max_request": otp_max_request,
                "otp_wait_seconds": otp_wait_seconds,
                "otp_resend_time": otp_resend_time
            }
        }
    }
    with transaction.atomic():
        phone = format_mobile_phone(phone)
        pii_partner_name_filter_dict = generate_pii_filter_query_partnership(
            Partner, {'name': partner_name}
        )
        partner = Partner.objects.filter(
            **pii_partner_name_filter_dict, is_active=True
        ).only('id').last()
        pii_filter_partnership_customer_data_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData, {
                'phone_number': phone,
                'nik': nik,
            }
        )
        partnership_customer_data_set = PartnershipCustomerData.objects.filter(
            **pii_filter_partnership_customer_data_dict,
            partner=partner,
        )
        if partnership_customer_data_set.exists():
            partnership_customer_data = partnership_customer_data_set.last()
        else:
            partnership_customer_data = PartnershipCustomerData.objects.create(
                phone_number=phone,
                token=generate_token_partnership(),
                partner=partner,
                nik=nik
            )
            PartnershipCustomerDataOTP.objects.create(
                partnership_customer_data=partnership_customer_data
            )

        token = partnership_customer_data.token
        existing_otp_request = OtpRequest.objects.filter(
            partnership_customer_data=partnership_customer_data,
            is_used=False, phone_number=phone).order_by('id').last()

        otp_resend_time = mfs.parameters['otp_resend_time']

        response = trigger_otp_sending(
            existing_otp_request,
            partnership_customer_data,
            token, mfs, phone, partner
        )

        if type(response) == Response:
            return response
        else:
            otp_request, data, change_sms_provide = response

        text_message = render_to_string(
            'sms_otp_token_application.txt', context={'otp_token': otp_request.otp_token})
        try:
            send_sms_otp_partnership.delay(
                phone, text_message, partnership_customer_data.id,
                otp_request.id, change_sms_provide)
            data['content']['resend_time'] = timezone.localtime(timezone.now()) + timedelta(
                seconds=otp_resend_time
            )
        except SmsNotSent:
            logger.error({
                "status": "sms_not_sent",
                "customer": partnership_customer_data.id,
                "phone": phone,
            })
            julo_sentry_client.captureException()
            message = "Kode verifikasi belum dapat dikirim"
            return_data['message'] = message
            return general_error_response(return_data)

    message = "OTP JULO sudah dikirim"
    return_data['message'] = message
    return success_response(return_data)


def otp_validation_webview(otp_token, phone_number, partner_name, nik):
    mfs = MobileFeatureSetting.objects.get_or_none(feature_name='mobile_phone_1_otp')
    if not mfs.is_active:
        return success_response(
            data={
                "success": True,
                "content": {
                    "active": mfs.is_active,
                    "parameters": mfs.parameters,
                    "message": "Verifikasi kode tidak aktif"
                }
            }
        )
    with transaction.atomic():
        otp_token = otp_token
        pii_partner_name_filter_dict = generate_pii_filter_query_partnership(
            Partner, {'name': partner_name}
        )
        partner = (
            Partner.objects.filter(**pii_partner_name_filter_dict, is_active=True).only('id').last()
        )
        partnership_customer_data_otp_prefetch = Prefetch(
            'partnership_customer_data_otps',
            queryset=PartnershipCustomerDataOTP.objects.filter(
                otp_type=PartnershipCustomerDataOTP.PHONE
            ),
            to_attr='partnership_customer_data_otp'
        )
        pii_filter_partnership_customer_data_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData,
            {
                'phone_number': format_mobile_phone(phone_number),
                'nik': nik,
            },
        )
        partnership_customer_data = (
            PartnershipCustomerData.objects.filter(
                partner=partner,
                **pii_filter_partnership_customer_data_dict,
            )
            .prefetch_related(partnership_customer_data_otp_prefetch)
            .last()
        )
        if not partnership_customer_data:
            return general_error_response("Partnership Customer Data tidak ditemukan")
        partnership_customer_data_otp =\
            partnership_customer_data.partnership_customer_data_otp[0]
        existing_otp_request = OtpRequest.objects.filter(
            otp_token=otp_token, partnership_customer_data=partnership_customer_data, is_used=False
        ).order_by('id').last()
        if not existing_otp_request:
            logger.error({
                "status": "otp_token_not_found",
                "otp_token": otp_token,
                "partnership_customer_data": partnership_customer_data.id
            })

            partnership_customer_data_otp.otp_last_failure_time = timezone.localtime(timezone.now())
            partnership_customer_data_otp.otp_latest_failure_count = \
                partnership_customer_data_otp.otp_latest_failure_count + 1
            partnership_customer_data_otp.otp_failure_count = \
                partnership_customer_data_otp.otp_failure_count + 1
            partnership_customer_data_otp.save()
            return general_error_response("Kode verifikasi belum terdaftar")

        if str(partnership_customer_data.id) not in existing_otp_request.request_id:
            logger.error("Kode verifikasi tidak valid")

        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        valid_token = hotp.verify(otp_token, int(existing_otp_request.request_id))
        if not valid_token:
            logger.error({
                "status": "invalid_token",
                "otp_token": otp_token,
                "otp_request": existing_otp_request.id,
                "partnership_customer_data": partnership_customer_data.id
            })
            partnership_customer_data_otp.otp_last_failure_time = \
                timezone.localtime(timezone.now())
            partnership_customer_data_otp.otp_latest_failure_count = \
                partnership_customer_data_otp.otp_latest_failure_count + 1
            partnership_customer_data_otp.save()
            return general_error_response("Kode verifikasi tidak valid")

        if not existing_otp_request.is_active:
            logger.error({
                "status": "otp_token_expired",
                "otp_token": otp_token,
                "otp_request": existing_otp_request.id,
                "partnership_customer_data": partnership_customer_data.id
            })
            return general_error_response("Kode verifikasi kadaluarsa")

        existing_otp_request.is_used = True
        existing_otp_request.save(update_fields=['is_used'])
        return_data = {'secret_key': partnership_customer_data.token}
        partnership_customer_data.update_safely(otp_status=PartnershipCustomerData.VERIFIED)
        partnership_customer_data_otp.otp_latest_failure_count = 0
        partnership_customer_data_otp.save(
            update_fields=['otp_latest_failure_count'])
    return success_response(return_data)


def generate_token_partnership():
    return binascii.b2a_hex(os.urandom(128)).decode('ascii')


def trigger_otp_sending(existing_otp_request, partnership_customer_data,
                        token, mobile_feature_setting, phone, partner):
    change_sms_provide = False
    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = mobile_feature_setting.parameters['wait_time_seconds']
    otp_max_request = mobile_feature_setting.parameters['otp_max_request']
    otp_resend_time = mobile_feature_setting.parameters['otp_resend_time']
    data = {
        "success": True,
        "content": {
            "active": mobile_feature_setting.is_active,
            "parameters": mobile_feature_setting.parameters,
            "message": "sms sent is rejected",
            "expired_time": None,
            "resend_time": None,
            "otp_max_request": otp_max_request,
            "retry_count": 0,
            "current_time": curr_time,
            "token": token
        }
    }
    if existing_otp_request and existing_otp_request.is_active:
        sms_history = existing_otp_request.sms_history
        prev_time = sms_history.cdate if sms_history else existing_otp_request.cdate
        expired_time = timezone.localtime(existing_otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        resend_time = timezone.localtime(prev_time) + timedelta(seconds=otp_resend_time)
        retry_count = SmsHistory.objects.filter(
            partnership_customer_data=partnership_customer_data,
            cdate__gte=existing_otp_request.cdate
        ).exclude(status='UNDELIV').count()
        retry_count += 1

        data['content']['expired_time'] = expired_time
        data['content']['resend_time'] = resend_time
        data['content']['retry_count'] = retry_count
        if sms_history and sms_history.status == 'Rejected':
            data['content']['resend_time'] = expired_time
            return success_response(
                data=data
            )
        if retry_count > otp_max_request:
            data['content']['message'] = "Permohonan otp melebihi batas maksimal," \
                                         " Anda dapat mencoba beberapa saat lagi"
            return success_response(
                data=data
            )

        if curr_time < resend_time:
            data['content']['message'] = "Tidak bisa mengirim ulang kode otp," \
                                         " belum memenuhi waktu yang ditentukan"
            return success_response(
                data=data
            )

        if curr_time > resend_time and sms_history and \
                sms_history.comms_provider and sms_history.comms_provider.provider_name:
            if sms_history.comms_provider.provider_name.lower() == VendorConst.MONTY:
                change_sms_provide = True

        if not sms_history:
            change_sms_provide = True

        otp_request = existing_otp_request
    else:
        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        postfixed_request_id = str(partnership_customer_data.id) + str(int(time.time()))
        otp = str(hotp.at(int(postfixed_request_id)))

        otp_request = OtpRequest.objects.create(
            partnership_customer_data=partnership_customer_data,
            request_id=postfixed_request_id,
            otp_token=otp, application=None, phone_number=phone)
        data['content']['message'] = "Kode verifikasi sudah dikirim"
        data['content']['expired_time'] = timezone.localtime(otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        data['content']['retry_count'] = 1

    if partner:
        partnership_config = PartnershipConfig.objects.filter(partner=partner).last()
        if partnership_config and partnership_config.is_validation_otp_checking:
            PartnershipUserOTPAction.objects.update_or_create(
                otp_request=otp_request.id, is_used=False
            )

    return otp_request, data, change_sms_provide


def webview_registration(nik, email, token, partner,
                         latitude=None, longitude=None, web_version=None):
    partnership_customer_data = PartnershipCustomerData.objects.filter(
        nik=nik,
        partner=partner,
        token=token
    ).only("id").last()
    if not partnership_customer_data:
        raise PartnershipWebviewException("Partnership Customer Data tidak ditemukan")
    partnership_application_data_set = PartnershipApplicationData.objects.filter(
        partnership_customer_data=partnership_customer_data
    ).only("id", "email", "is_submitted")
    if partnership_application_data_set.filter(
        is_submitted=True
    ).exists() and partnership_customer_data.customer is not None:
        partnership_application_data = partnership_application_data_set.filter(
            is_submitted=True
        ).last()
        return_data = {
            "email": partnership_application_data.email,
            "nik": partnership_customer_data.nik,
            "token": token
        }
        return return_data

    if not PartnershipApplicationData.objects.filter(
            partnership_customer_data=partnership_customer_data).exists():
        partnership_application_data = PartnershipApplicationData.objects.create(
            partnership_customer_data=partnership_customer_data,
            email=email,
            latitude=latitude,
            longitude=longitude,
            web_version=web_version
        )
    else:
        partnership_application_data = partnership_application_data_set.filter(
            email=email).last()
        if not partnership_application_data:
            partnership_application_data = PartnershipApplicationData.objects.create(
                partnership_customer_data=partnership_customer_data,
                email=email,
                latitude=latitude,
                longitude=longitude,
                web_version=web_version
            )
        else:
            partnership_application_data.latitude = latitude
            partnership_application_data.longitude = longitude
            partnership_application_data.web_version = web_version
            partnership_application_data.save(update_fields=[
                'latitude', 'longitude', 'web_version'])

    return_data = {
        "email": partnership_application_data.email,
        "nik": partnership_customer_data.nik,
        "token": token
    }
    return return_data


def get_phone_number_linkaja(session_id, partner_name):
    pii_filter_dict = generate_pii_filter_query_partnership(Partner, {'name': partner_name})
    partner = Partner.objects.filter(is_active=True, **pii_filter_dict).last()
    if not partner:
        raise PartnershipWebviewException("Partner {}".format(ErrorMessageConst.INVALID_DATA))

    try:
        process_log = {
            "action": "get_phone_number_linkaja|process",
            "partner": partner_name,
            "session_id": session_id,
        }

        logger.info(process_log)

        response = LinkAjaClient.verify_session_id(session_id, partner.id)
        response_data = json.loads(response.content)
        response_data = response_data.get('data') if response_data.get('data') else response_data
    except Timeout as e:
        error_log = {
            "action": "get_phone_number_linkaja|error",
            "status": "timeout",
            "partner": partner_name,
            "session_id": session_id,
            "error": str(e),
        }

        logger.error(error_log)

        redis_key = '%s_%s' % (
            PartnershipRedisPrefixKey.WEBVIEW_GET_PHONE_NUMBER, session_id)
        redis_cache = RedisCache(key=redis_key, hours=1)
        value = redis_cache.get()
        now = timezone.localtime(timezone.now())
        now_formatted = now.strftime('%Y-%m-%d %H:%M:%S')
        if not value:
            value = '0;%s' % now_formatted
        value_split = value.split(';')
        request_count = int(value_split[0])
        request_count += 1
        redis_cache.set('%s;%s' % (request_count, now_formatted))
        if request_count > 2:
            if e.response:
                notify_failed_hit_api_partner(
                    partner_name,
                    e.request.url,
                    e.request.method,
                    e.request.headers,
                    e.request.body,
                    'TIMEOUT',
                    e.response.status_code,
                    e.response.text,
                )
            else:
                notify_failed_hit_api_partner(
                    partner_name,
                    e.request.url,
                    e.request.method,
                    e.request.headers,
                    e.request.body,
                    'TIMEOUT',
                )
        return request_timeout_response('Request Time Out')
    phone_number = update_session_table(response, partner, session_id)

    success_log = {
        "action": "get_phone_number_linkaja|success",
        "partner": partner_name,
        "session_id": session_id,
        "phone_number": phone_number,
    }

    logger.info(success_log)

    response_data = {
        "phone_number": format_mobile_phone(phone_number)
    }
    return success_response(response_data)


def update_session_table(response, partner, session_id):
    if response.status_code == 200:
        data = json.loads(response.content)['data']
        status = json.loads(response.content)['status']
        if status != '00':
            raise PartnershipWebviewException('Invalid SessionID/Customer Not found')

        partner_id = partner.id
        partnership_session_information = PartnershipSessionInformation.objects.filter(
            partner_id=partner_id,
            session_id=session_id,
            phone_number=data['customerNumber'],
            customer_token=data['customerAccessToken'],
        ).exists()

        if not partnership_session_information:
            PartnershipSessionInformation.objects.create(
                partner_id=partner_id,
                session_id=session_id,
                phone_number=data['customerNumber'],
                customer_token=data['customerAccessToken'],
                time_session_verified=timezone.localtime(timezone.now())
            )
        phone_number = data['customerNumber']
    else:
        raise PartnershipWebviewException("Invalid Response Code")
    return phone_number


def cashin_inquiry_linkaja(application, partner, loan_data):
    customer = application.customer
    partnership_transaction = PartnershipTransaction.objects.create(
        customer=customer, partner=partner
    )
    partnership_customer_data = customer.partnershipcustomerdata_set.filter(
        otp_status='VERIFIED'
    ).last()
    detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
        PiiSource.PARTNERSHIP_CUSTOMER_DATA,
        partnership_customer_data,
        customer.customer_xid,
        ['phone_number'],
    )

    # Since phone number from LinkAja come with 62 format but
    # phone number in partnership_customer_data is 08 we need to
    # change the format from 08 to 62 before querying it to partnership_session_information
    phone_number_e164 = parse_phone_number_format(
        detokenize_partnership_customer_data.phone_number, PhoneNumberFormat.E164
    )
    phone_number_e164 = phone_number_e164.replace('+', '')

    pii_phone_e164_filter_dict = generate_pii_filter_query_partnership(
        PartnershipSessionInformation, {'phone_number': phone_number_e164}
    )

    partner_id = partner.id
    session_information = (
        PartnershipSessionInformation.objects.filter(
            partner_id=partner_id, **pii_phone_e164_filter_dict
        )
        .only('customer_token')
        .last()
    )

    if not session_information:
        # if not found, try query with original value
        pii_phone_filter_dict = generate_pii_filter_query_partnership(
            PartnershipSessionInformation,
            {'phone_number': detokenize_partnership_customer_data.phone_number},
        )
        session_information = (
            PartnershipSessionInformation.objects.filter(
                partner_id=partner_id, **pii_phone_filter_dict
            )
            .only('customer_token')
            .last()
        )

        if not session_information:
            return general_error_response(
                'Partnership Session Information %s' % ErrorMessageConst.NOT_FOUND
            )
    try:
        response = LinkAjaClient.cash_in_inquiry(
            session_information.customer_token,
            loan_data['disbursement_amount'],
            partnership_transaction.transaction_id,
            partner_id=partner_id,
        )
        response_data = json.loads(response.content)
        response_data = response_data.get('data') if response_data.get('data') else response_data
        if response.status_code == 200 and response_data['responseCode'] == '89':
            raise Timeout(response=response, request=response.request)
    except Timeout as e:
        redis_key = '%s_%s' % (
            PartnershipRedisPrefixKey.WEBVIEW_CREATE_LOAN, application.id)
        redis_cache = RedisCache(key=redis_key, hours=1)
        value = redis_cache.get()
        now = timezone.localtime(timezone.now())
        now_formatted = now.strftime('%Y-%m-%d %H:%M:%S')
        if not value:
            value = '0;%s' % now_formatted
        value_split = value.split(';')
        request_count = int(value_split[0])
        request_count += 1
        redis_cache.set('%s;%s' % (request_count, now_formatted))
        if request_count > 2:
            detokenize_partner = partnership_detokenize_sync_object_model(
                PiiSource.PARTNER,
                partner,
                customer_xid=None,
                fields_param=['name'],
                pii_type=PiiVaultDataType.KEY_VALUE,
            )
            if e.response:
                notify_failed_hit_api_partner(
                    detokenize_partner.name,
                    e.request.url,
                    e.request.method,
                    e.request.headers,
                    e.request.body,
                    'TIMEOUT',
                    e.response.status_code,
                    e.response.text,
                )
            else:
                notify_failed_hit_api_partner(
                    detokenize_partner.name,
                    e.request.url,
                    e.request.method,
                    e.request.headers,
                    e.request.body,
                    'TIMEOUT',
                )
        return request_timeout_response('Request Time Out')

    if response.status_code == 200:
        if response_data['responseCode'] == '15':
            return general_error_response(
                'Anda mengajukan pencairan : {}\n'
                'Pastikan jumlah saldo anda saat ini ditambah pengajuan '
                'JULO anda tidak melebihi Rp.20.000.000\n\n'
                'Jika anda ingin mencairkan lebih, silahkan download JULO apps di {}'.format(
                    display_rupiah(loan_data['loan_amount_request']),
                    'https://play.google.com/store/apps/details?id=com.julofinance.juloapp'
                )
            )
        elif response_data['responseCode'] != '00':
            return general_error_response('Invalid Response Code')

        try:
            create_loan_response = process_create_loan(
                loan_data, application, partner, skip_bank_account=True
            )
        except LoanDbrException as e:
            res_data = {'dbr_exceeded': True}
            return general_error_response(
                e.error_msg,
                res_data,
            )

        if create_loan_response.status_code == 200:
            loan = Loan.objects.get(
                loan_xid=create_loan_response.data['data']['loan_xid'])
            partnership_transaction.update_safely(
                partner_transaction_id=response_data['sessionID'],
                is_done_inquiry=True,
                loan=loan
            )

        return create_loan_response
    else:
        return general_error_response('Invalid Response Code')


def cashin_confirmation_linkaja(loan, partner):
    partnership_customer_data = loan.customer.partnershipcustomerdata_set.filter(
        otp_status='VERIFIED'
    ).last()
    detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
        PiiSource.PARTNERSHIP_CUSTOMER_DATA,
        partnership_customer_data,
        loan.customer.customer_xid,
        ['phone_number'],
    )
    # Since phone number from LinkAja come with 62 format but
    # phone number in partnership_customer_data is 08 we need to
    # change the format from 08 to 62 before querying it to partnership_session_information
    phone_number_e164 = parse_phone_number_format(
        detokenize_partnership_customer_data.phone_number, PhoneNumberFormat.E164
    )
    phone_number_e164 = phone_number_e164.replace('+', '')

    pii_phone_e164_filter_dict = generate_pii_filter_query_partnership(
        PartnershipSessionInformation, {'phone_number': phone_number_e164}
    )

    partner_id = partner.id
    session_information = (
        PartnershipSessionInformation.objects.filter(
            partner_id=partner_id, **pii_phone_e164_filter_dict
        )
        .only('customer_token')
        .last()
    )

    if not session_information:
        # if not found, try query with original value
        pii_phone_filter_dict = generate_pii_filter_query_partnership(
            PartnershipSessionInformation,
            {'phone_number': detokenize_partnership_customer_data.phone_number},
        )
        session_information = (
            PartnershipSessionInformation.objects.filter(
                partner_id=partner_id, **pii_phone_filter_dict
            )
            .only('customer_token')
            .last()
        )

        if not session_information:
            return general_error_response(
                'Partnership Session Information %s' % ErrorMessageConst.NOT_FOUND
            )

    parntership_transaction = loan.partnershiptransaction_set.order_by('-id').first()
    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        customer_xid=None,
        fields_param=['name'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )
    try:
        response = LinkAjaClient.cash_in_confirmation(
            session_id=parntership_transaction.partner_transaction_id,
            customer_token=session_information.customer_token,
            amount=loan.loan_disbursement_amount,
            merchant_txn_id=parntership_transaction.transaction_id,
            partner_id=partner.id
        )
        response_data = json.loads(response.content)
        response_data = response_data.get('data') if response_data.get('data') else response_data
        if response.status_code == 200 and response_data.get('responseCode') == '89':
            raise Timeout(response=response, request=response.request)
    except Timeout as e:
        redis_key = '%s_%s' % (
            PartnershipRedisPrefixKey.WEBVIEW_DISBURSEMENT, loan.loan_xid)
        redis_cache = RedisCache(key=redis_key, hours=1)
        value = redis_cache.get()
        now = timezone.localtime(timezone.now())
        now_formatted = now.strftime('%Y-%m-%d %H:%M:%S')
        if not value:
            value = '0;%s' % now_formatted
        value_split = value.split(';')
        request_count = int(value_split[0])
        request_count += 1
        redis_cache.set('%s;%s' % (request_count, now_formatted))
        if request_count > 2:
            if e.response:
                notify_failed_hit_api_partner(
                    detokenize_partner.name,
                    e.request.url,
                    e.request.method,
                    e.request.headers,
                    e.request.body,
                    'TIMEOUT',
                    e.response.status_code,
                    e.response.text,
                )
            else:
                notify_failed_hit_api_partner(
                    detokenize_partner.name,
                    e.request.url,
                    e.request.method,
                    e.request.headers,
                    e.request.body,
                    'TIMEOUT',
                )
        return request_timeout_response('Request Time Out')

    if (response.status_code == 200 and response_data.get('responseCode') == '00') or \
            (response.status_code == 200 and response_data.get('responseCode') == '26'):
        if response_data.get('responseCode') == '00':
            parntership_transaction.update_safely(
                is_done_confirmation=True, reference_num=response_data['linkRefNum']
            )
        return success_response(response_data)
    else:
        notify_failed_hit_api_partner(
            detokenize_partner.name,
            response.request.url,
            response.request.method,
            response.request.headers,
            response.request.body,
            '',
            response.status_code,
            response.text,
        )
        return general_error_response(response_data)


def retry_linkaja_transaction(loan, partner, customer_token):
    customer = loan.customer
    partnership_transaction = PartnershipTransaction.objects.create(
        customer=customer, partner=partner
    )
    cashin_inquiry_response = LinkAjaClient.cash_in_inquiry(
        customer_token, loan.loan_disbursement_amount,
        partnership_transaction.transaction_id, partner.id
    )
    response_data = json.loads(cashin_inquiry_response.content)
    response_data = response_data.get('data') if response_data.get('data') else response_data
    if cashin_inquiry_response.status_code == 200:
        if response_data['responseCode'] != '00':
            return general_error_response('Invalid Response Code when Cashin Inquiry')

        confirmation_response = LinkAjaClient.cash_in_inquiry(
            customer_token,
            loan.loan_disbursement_amount,
            partnership_transaction.transaction_id,
            partner.id
        )
        if confirmation_response.status_code != 200:
            return general_error_response('Invalid Response Code when Cashin Confirmation')

        confirmation_response_data = json.loads(confirmation_response.content)
        confirmation_response_data = confirmation_response_data.get('data')\
            if confirmation_response_data.get('data') else confirmation_response_data
        return check_transaction_linkaja(partnership_transaction.transaction_id, partner.id)


def check_transaction_linkaja(transaction_id, partner_id):
    check_transaction = LinkAjaClient.check_transactional_status(transaction_id, partner_id)
    response_data = json.loads(check_transaction.content)
    response_data = response_data.get('data') if response_data.get('data') else response_data
    return success_response(check_transaction_linkaja)


def is_loan_more_than_one(account):
    loans = account.loan_set.exclude(loan_status__in=(
        LoanStatusCodes.CANCELLED_BY_CUSTOMER,
        LoanStatusCodes.SPHP_EXPIRED,
        LoanStatusCodes.FUND_DISBURSAL_FAILED,
        LoanStatusCodes.PAID_OFF,))
    loan = loans.last()
    if loan and loan.status == LoanStatusCodes.INACTIVE:
        return True

    return False


def webview_save_loan_expectation(token: str, nik: str, loan_amount_req: int,
                                  loan_duration_req: int, partner: int):
    pii_filter_nik__dict = generate_pii_filter_query_partnership(
        PartnershipCustomerData, {'nik': nik}
    )

    partnership_customer_data = PartnershipCustomerData.objects.filter(
        partner=partner, token=token, **pii_filter_nik__dict
    ).last()
    if not partnership_customer_data:
        raise PartnershipWebviewException(ErrorMessageConst.DATA_NOT_FOUND)

    loan_expectation = PartnershipLoanExpectation.objects.filter(
        partnership_customer_data_id=partnership_customer_data.id
    ).last()
    # if loan expectation for related user exist
    # just replace the loan_amount_request and loan_duration_request
    if loan_expectation:
        loan_expectation.loan_amount_request = loan_amount_req
        loan_expectation.loan_duration_request = loan_duration_req
        loan_expectation.save()
    else:
        loan_expectation = PartnershipLoanExpectation.objects.create(
            partnership_customer_data_id=partnership_customer_data.id,
            loan_amount_request=loan_amount_req,
            loan_duration_request=loan_duration_req
        )

    return_data = {
        "nik": nik,
        "loan_amount_request": loan_expectation.loan_amount_request,
        "loan_duration_request": loan_expectation.loan_duration_request
    }

    return return_data


def check_registered_user(token):
    j1_application_flag = False
    partnership_customer_data = PartnershipCustomerData.objects.filter(
        token=token
    ).last()
    if partnership_customer_data.customer:
        customer_xid = partnership_customer_data.customer.customer_xid
        detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            partnership_customer_data,
            customer_xid,
            ['nik'],
        )
        nik = detokenize_partnership_customer_data.nik
    else:
        nik = partnership_customer_data.nik

    return_data = {
        "show_pin_creation_page": True,
        "redirect_to_page": LinkajaPages.LOAN_EXPECTATION_PAGE,
        "verify_pin_j1": False
    }
    j1_application_flag = has_j1_application(nik)
    if check_reject_non_j1_customer(nik):
        return_data = {
            "show_pin_creation_page": False,
            "redirect_to_page": LinkajaPages.REJECT_DUE_TO_NON_J1_CUSTOMER,
            "verify_pin_j1": False,
            'partnership_customer': partnership_customer_data.id
        }
        return return_data

    if partnership_customer_data.partnershipapplicationdata_set.filter(
            is_submitted=True).exists() and partnership_customer_data.customer is not None:
        return_data = {
            "show_pin_creation_page": False,
            "redirect_to_page": LinkajaPages.J1_VERIFiCATION_PAGE,
            "verify_pin_j1": False,
            'partnership_customer': partnership_customer_data.id
        }
        return return_data
    partnership_application_data = partnership_customer_data.partnershipapplicationdata_set.last()
    if not partnership_application_data:
        if j1_application_flag:
            if can_reapply_or_100_application_j1(nik):
                return_data["show_pin_creation_page"] = False
                return_data["redirect_to_page"] = LinkajaPages.LOAN_EXPECTATION_PAGE
                return_data["verify_pin_j1"] = True
            else:
                return_data["show_pin_creation_page"] = False
                return_data["redirect_to_page"] = LinkajaPages.LOAN_EXPECTATION_PAGE
                return_data["verify_pin_j1"] = False
            update_last_j1_status(nik, partnership_customer_data)
        else:
            return_data["show_pin_creation_page"] = True
            return_data["redirect_to_page"] = LinkajaPages.LOAN_EXPECTATION_PAGE
            return_data["verify_pin_j1"] = False
    else:
        if j1_application_flag:
            if not partnership_application_data.is_submitted and \
                    can_reapply_or_100_application_j1(nik):
                return_data["show_pin_creation_page"] = False
                return_data["redirect_to_page"] = LinkajaPages.LONG_FORM_PAGE
                return_data["verify_pin_j1"] = True
            elif not partnership_application_data.is_submitted and not \
                    can_reapply_or_100_application_j1(nik):
                return_data["show_pin_creation_page"] = False
                return_data["redirect_to_page"] = LinkajaPages.LONG_FORM_PAGE
                return_data["verify_pin_j1"] = False
            elif partnership_application_data.is_submitted and \
                    partnership_customer_data.customer is None and \
                    can_reapply_or_100_application_j1(nik):
                return_data["show_pin_creation_page"] = False
                return_data["redirect_to_page"] = LinkajaPages.REGISTRATION_PAGE
                return_data["verify_pin_j1"] = True
            elif partnership_application_data.is_submitted and \
                    partnership_customer_data.customer is None and \
                    not can_reapply_or_100_application_j1(nik):
                return_data["show_pin_creation_page"] = False
                return_data["redirect_to_page"] = LinkajaPages.REGISTRATION_PAGE
                return_data["verify_pin_j1"] = False
            elif partnership_application_data.is_submitted and \
                    partnership_customer_data.customer is not None:
                return_data["show_pin_creation_page"] = False
                return_data["redirect_to_page"] = LinkajaPages.J1_VERIFiCATION_PAGE
                return_data["verify_pin_j1"] = False
            else:
                raise PartnershipWebviewException("Unexpected Condition")
            update_last_j1_status(nik, partnership_customer_data)
        else:
            if not partnership_application_data.is_submitted and \
                    partnership_application_data.encoded_pin is None:
                return_data["show_pin_creation_page"] = True
                return_data["redirect_to_page"] = LinkajaPages.PIN_CREATION_PAGE
                return_data["verify_pin_j1"] = False
            elif not partnership_application_data.is_submitted and \
                    partnership_application_data.encoded_pin is not None:
                return_data["show_pin_creation_page"] = False
                return_data["redirect_to_page"] = LinkajaPages.LONG_FORM_PAGE
                return_data["verify_pin_j1"] = False
            elif partnership_application_data.is_submitted and \
                    partnership_customer_data.customer is None:
                return_data["show_pin_creation_page"] = True
                return_data["redirect_to_page"] = LinkajaPages.REGISTRATION_PAGE
                return_data["verify_pin_j1"] = False
            elif partnership_application_data.is_submitted and \
                    partnership_customer_data.customer is not None:
                return_data["show_pin_creation_page"] = False
                return_data["redirect_to_page"] = LinkajaPages.J1_VERIFiCATION_PAGE
                return_data["verify_pin_j1"] = False
            else:
                raise PartnershipWebviewException("Unexpected Condition")
    return_data['partnership_customer'] = partnership_customer_data.id
    return return_data


def has_j1_application(nik):
    customer = Customer.objects.filter(nik=nik).last()
    if not customer:
        return False

    application_flag = Application.objects.filter(
        customer=customer,
        workflow__name=WorkflowConst.JULO_ONE
    ).exists()
    return application_flag


def can_reapply_or_100_application_j1(nik):
    customer = Customer.objects.filter(nik=nik).last()
    if not customer:
        return False
    reapply_status = j1_reapply_status
    reapply_status.add(ApplicationStatusCodes.FORM_CREATED)
    last_application = Application.objects.filter(
        customer=customer,
        workflow__name=WorkflowConst.JULO_ONE,
        application_status_id__in=reapply_status
    ).last()
    if last_application:
        if last_application.application_status_id != ApplicationStatusCodes.FORM_CREATED:
            if customer.can_reapply:
                return True
        else:
            return True
    return False


def login_partnership_j1(validated_data, token):
    user = pin_services.get_user_from_username(validated_data['nik'])
    if not user or not hasattr(user, 'customer'):
        return general_error_response("NIK Anda tidak terdaftar")
    msg = pin_services.exclude_merchant_from_j1_login(user)
    if msg:
        return general_error_response(msg)

    login_check, error_message = prevent_web_login_cases_check(
        user, validated_data['partner_name']
    )

    is_password_correct = user.check_password(validated_data['pin'])
    if not is_password_correct:
        return unauthorized_error_response("Password Anda masih salah.")

    eligible_access = dict(
        is_eligible=login_check,
        error_message=error_message
    )
    if login_check:
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            token=token,
            otp_status=PartnershipCustomerData.VERIFIED,
            nik=validated_data['nik']
        ).last()
        if not partnership_customer_data:
            raise PartnershipWebviewException("INVALID REQUEST")

        login_attempt = LoginAttempt.objects.filter(
            customer=user.customer,
            customer_pin_attempt__reason__in=SUSPICIOUS_LOGIN_CHECK_CLASSES).last()
        response_data = pin_services.process_login(user, validated_data,
                                                   True, login_attempt, partnership=True)
        response_data['eligible_access'] = eligible_access
        customer = user.customer
        partnership_customer_data.customer = customer
        partnership_customer_data.save()
    else:
        return general_error_response(error_message, {'eligible_access': eligible_access})
    return success_response(response_data)


def check_reject_non_j1_customer(nik):
    customer = Customer.objects.filter(nik=nik).last()
    if not customer:
        return False
    application_flag = Application.objects.filter(
        customer=customer).exclude(
        product_line__product_line_code__in=ProductLineCodes.julo_one()).exists()

    return application_flag


def update_last_j1_status(nik, partnership_customer_data):
    customer = Customer.objects.get_or_none(nik=nik)
    if customer:
        last_application = Application.objects.filter(
            customer=customer,
            workflow__name=WorkflowConst.JULO_ONE
        ).last()
        partnership_customer_data.last_j1_application_status = \
            last_application.application_status_id
        partnership_customer_data.save(update_fields=['last_j1_application_status'])


def get_webview_info_cards(customer):
    empty_data = {'cards': []}
    application = customer.application_set.regular_not_deletes().filter(
        workflow__name=WorkflowConst.JULO_ONE).last()

    application_status_no_need_credit_score = {
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ApplicationStatusCodes.APPLICATION_DENIED,
        ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED
    }
    if not hasattr(application, 'creditscore') and \
            application.application_status_id not in application_status_no_need_credit_score:
        return success_response(empty_data)
    data = dict()
    is_document_submission = False
    card_due_date = '-'
    card_due_amount = '-'
    card_cashback_amount = '-'
    card_cashback_multiplier = '-'
    card_dpd = '-'
    loan = None if not hasattr(application, 'loan') else application.loan
    if application.is_julo_one():
        if application.account:
            loan = application.account.loan_set.last()
            if loan and loan.account:
                oldest_payment = loan.account.accountpayment_set.not_paid_active() \
                    .order_by('due_date') \
                    .first()
                if oldest_payment:
                    card_due_date = format_date_indo(oldest_payment.due_date)
                    card_due_amount = add_thousand_separator(str(oldest_payment.due_amount))
                    card_cashback_amount = oldest_payment.payment_set.last().cashback_earned
                    card_cashback_multiplier = oldest_payment.cashback_multiplier
                    card_dpd = oldest_payment.dpd

    available_context = {
        'card_title': application.bpk_ibu,
        'card_full_name': application.full_name_only,
        'card_first_name': application.first_name_only,
        'card_due_date': card_due_date,
        'card_due_amount': card_due_amount,
        'card_cashback_amount': card_cashback_amount,
        'card_cashback_multiplier': str(card_cashback_multiplier) + 'x',
        'card_dpd': card_dpd
    }
    info_cards = []
    webview_infocards_queryset = StreamlinedCommunication.objects.filter(
        show_in_web=True,
        show_in_android=False
    )

    now = timezone.localtime(timezone.now())

    mandocs_overhaul_105 = False
    mandocs_overhaul_status_code = ApplicationStatusCodes.FORM_PARTIAL
    sonic_pass = False
    salary_izi_data = False
    is_data_check_passed = False
    etl_job = None
    if application.is_julo_one() and \
            is_experiment_application(application.id, 'ExperimentUwOverhaul'):
        if application.application_status_id == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
            mandocs_overhaul_status_code = ApplicationStatusCodes.DOCUMENTS_SUBMITTED
            sonic_pass = check_iti_repeat(application.id)
            customer_high_score = feature_high_score_full_bypass(application)

            is_scrapped_bank = check_scrapped_bank(application)

            success_status = ['auth_success', 'done', 'initiated', 'load_success', 'scrape_success']

            etl_job = EtlJob.objects.filter(application_id=application.id).last()

            if etl_job:
                if etl_job.status in success_status:
                    is_data_check_passed = True

            if is_scrapped_bank:
                sd_bank_account = SdBankAccount.objects.filter(application_id=application.id).last()
                if sd_bank_account:
                    sd_bank_statement_detail = SdBankStatementDetail.objects.filter(
                        sd_bank_account=sd_bank_account).last()
                    if sd_bank_statement_detail:
                        is_data_check_passed = True

            if not is_data_check_passed:
                from juloserver.bpjs.services import Bpjs
                is_data_check_passed = Bpjs(application).is_scraped

            if not customer_high_score:
                if not sonic_pass:
                    if not is_data_check_passed:
                        salary_izi_data = check_salary_izi_data(application)
        elif application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL:
            mandocs_overhaul_105 = True
    if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL:
        if mandocs_overhaul_105:
            is_c_score = JuloOneService.is_c_score(application)
            if is_c_score:
                eta_time = get_eta_time_for_c_score_delay(application)
                if now > eta_time:
                    info_cards = list(webview_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C,  # noqa
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                else:
                    info_cards = list(webview_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DELAY,  # noqa
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
            else:
                info_cards = list(webview_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_WAITING_SCORE,
                    is_active=True
                ).select_related('message', 'message__info_card_property',
                                 'message__info_card_property__card_order_number')
                 .order_by('message__info_card_property__card_order_number'))
    if application.application_status_id == mandocs_overhaul_status_code:
        customer_high_score = feature_high_score_full_bypass(application)
        customer_with_high_c_score = JuloOneService.is_high_c_score(application)
        is_c_score = JuloOneService.is_c_score(application)
        if is_c_score:
            eta_time = get_eta_time_for_c_score_delay(application)
            if now > eta_time:
                info_cards = list(webview_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C,  # noqa
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
            else:
                info_cards = list(webview_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DELAY,  # noqa
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
        elif customer_high_score:
            info_cards = list(webview_infocards_queryset.filter(
                communication_platform=CommunicationPlatform.INFO_CARD,
                status_code_id=application.application_status_id,
                extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_HIGH_SCORE,
                is_active=True
            ).order_by('message__info_card_property__card_order_number'))
        elif customer_with_high_c_score:
            if sonic_pass:
                julo_one_service = JuloOneService()
                if not julo_one_service.check_affordability_julo_one(application):
                    info_cards = list(webview_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C,  # noqa
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                else:
                    info_cards = list(webview_infocards_queryset.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=CardProperty.CUSTOMER_HAVE_HIGH_SCORE,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
            else:

                if etl_job:
                    if mandocs_overhaul_status_code == \
                            ApplicationStatusCodes.DOCUMENTS_SUBMITTED and \
                            etl_job.status == 'load_success':
                        do_advance_ai_id_check_task.delay(application.id)

                card_property = CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_HIGH_SCORE

                job_type = JobType.objects.get_or_none(
                    job_type=application.job_type)
                is_salaried = job_type.is_salaried if job_type else None
                passes_income_check = salary_izi_data and is_salaried
                if (
                    not is_data_check_passed
                    or mandocs_overhaul_status_code == ApplicationStatusCodes.FORM_PARTIAL
                ) and (
                    not passes_income_check
                    or (
                        passes_income_check
                        and (
                            not is_income_in_range(application)
                            or not is_income_in_range_leadgen_partner(application)
                            or not is_income_in_range_agent_assisted_partner(application)
                        )
                    )
                ):
                    is_document_submission = True
                    card_property = CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_HIGH_C_SCORE
                info_cards = list(webview_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=card_property,
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
        elif not is_c_score:
            if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL and \
                    is_experiment_application(application.id, 'ExperimentUwOverhaul'):
                info_cards = list(webview_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_WAITING_SCORE,
                    is_active=True
                ).select_related('message', 'message__info_card_property',
                                 'message__info_card_property__card_order_number')
                 .order_by('message__info_card_property__card_order_number'))
            else:
                # Medium because not meet customer high score and not meet
                # high c score also not meet c
                is_document_submitted = (mandocs_overhaul_status_code == ApplicationStatusCodes.
                                         DOCUMENTS_SUBMITTED)
                if etl_job and (is_document_submitted and etl_job.status == 'load_success'):
                    do_advance_ai_id_check_task.delay(application.id)

                card_property = CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_HIGH_SCORE

                job_type = JobType.objects.get_or_none(
                    job_type=application.job_type)
                is_salaried = job_type.is_salaried if job_type else None
                passes_income_check = salary_izi_data and is_salaried
                if (
                    not sonic_pass
                    and (
                        not is_data_check_passed
                        or mandocs_overhaul_status_code == ApplicationStatusCodes.FORM_PARTIAL
                    )
                    and (
                        not passes_income_check
                        or (
                            passes_income_check
                            and (
                                not is_income_in_range(application)
                                or not is_income_in_range_leadgen_partner(application)
                                or not is_income_in_range_agent_assisted_partner(application)
                            )
                        )
                    )
                ):
                    is_document_submission = True
                    card_property = CardProperty.PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_MEDIUM_SCORE

                info_cards = list(webview_infocards_queryset.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=card_property,
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))
    elif application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
        negative_payment_history = not is_customer_has_good_payment_histories(
            customer, is_for_julo_one=True)
        if negative_payment_history:
            extra_condition = \
                CardProperty.PARTNERSHIP_WEBVIEW_INFO_MOVE_TO_106_WITH_REASON_NEGATIVE_PAYMENT_HISTORY  # noqa
        else:
            extra_condition = \
                CardProperty.PARTNERSHIP_WEBVIEW_INFO_ALL_106_EXPECT_PREVIOUS_EXPIRY_REASON
        info_cards = list(webview_infocards_queryset.filter(
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=application.application_status_id,
            extra_conditions=extra_condition,
            is_active=True
        ).order_by('message__info_card_property__card_order_number'))

    elif application.application_status_id == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:
        info_cards = get_info_cards_privy(application.id)

    elif application.application_status_id == ApplicationStatusCodes.APPLICATION_DENIED:
        if customer.can_reapply:
            info_cards = list(webview_infocards_queryset.filter(
                communication_platform=CommunicationPlatform.INFO_CARD,
                status_code_id=application.application_status_id,
                extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_ALREADY_ELIGIBLE_TO_REAPPLY,
                is_active=True
            ).order_by('message__info_card_property__card_order_number'))
    elif application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
        if not is_already_have_transaction(customer):
            info_cards = list(webview_infocards_queryset.filter(
                communication_platform=CommunicationPlatform.INFO_CARD,
                status_code_id=application.application_status_id,
                extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_MSG_TO_STAY_UNTIL_1ST_TRANSACTION,  # noqa
                is_active=True
            ).order_by('message__info_card_property__card_order_number'))

    if len(info_cards) == 0:
        info_cards = list(webview_infocards_queryset.filter(
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=application.application_status_id,
            extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CARDS,
            is_active=True
        ).order_by('message__info_card_property__card_order_number'))
    if application.application_status_id == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:  # noqa
        is_document_submission = True

    data['is_document_submission'] = is_document_submission
    is_block_infocard = False
    account = application.account
    if account:
        account_status = account.status.status_code
        if account_status in AccountConstant.EMPTY_INFO_CARD_ACCOUNT_STATUS:
            is_block_infocard = True
            # delete existing infocard because account status is 430
            info_cards = []

    if application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
        if application.is_julo_one():

            loan = application.account.loan_set.last()
            if loan:
                if not is_block_infocard:
                    loan_cards_qs = StreamlinedCommunication.objects.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=loan.status,
                        is_active=True,
                        show_in_web=True,
                        show_in_android=False
                    )

                    account_limit = application.account.get_account_limit
                    account_property = application.account.accountproperty_set.last()
                    if account_limit and account_property.concurrency and \
                            loan.status == LoanStatusCodes.CURRENT and \
                            account_limit.available_limit >= CardProperty.EXTRA_220_LIMIT_THRESHOLD:

                        loan_cards_qs = loan_cards_qs.filter(
                            extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CHECK_LIMIT_AND_CONCURRENCY)  # noqa
                    else:
                        loan_cards_qs = loan_cards_qs.filter(
                            extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CARDS)

                    loan_cards = list(
                        loan_cards_qs.order_by('message__info_card_property__card_order_number'))
                    info_cards = loan_cards + info_cards

                oldest_payment = loan.account.accountpayment_set.not_paid_active() \
                    .order_by('due_date') \
                    .first()
                if oldest_payment:
                    dpd = oldest_payment.dpd
                    payment_cards = list(webview_infocards_queryset.filter(
                        Q(dpd=dpd)
                        | (Q(dpd_lower__lte=dpd) & Q(dpd_upper__gte=dpd))
                        | (Q(dpd_lower__lte=dpd) & Q(until_paid=True))).filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CARDS,
                        is_active=True,
                        show_in_web=True,
                        show_in_android=False
                    ).order_by('message__info_card_property__card_order_number'))
                    info_cards = payment_cards + info_cards

    processed_info_cards = []
    for info_card in info_cards:
        is_expired = False

        if info_card.expiration_option and info_card.expiration_option != "No Expiration Time":
            is_expired = is_info_card_expired(info_card, application, loan)
        if not is_expired:
            processed_info_cards.append(
                format_info_card_for_partnership_webview(info_card, available_context)
            )
    data['cards'] = processed_info_cards
    data['application_id'] = application.id
    return success_response(data)


def format_info_card_for_partnership_webview(streamlined_communication, available_context):
    streamlined_message = streamlined_communication.message
    info_card_property = streamlined_message.info_card_property
    card_type = info_card_property.card_type[0]
    button_list = info_card_property.button_list
    formated_buttons = []
    for button in button_list:
        formated_buttons.append(
            {
                "colour": '',
                "text": button.text,
                "textcolour": button.text_color,
                "action_type": button.action_type,
                "destination": button.destination,
                "border": None,
                "background_img": button.background_image_url
            }
        )

    formated_data = dict(
        type=card_type,
        title={
            "colour": info_card_property.title_color,
            "text": process_convert_params_to_data(
                info_card_property.title, available_context)
        },
        content={
            "colour": info_card_property.text_color,
            "text": process_convert_params_to_data(
                streamlined_message.message_content, available_context)
        },
        button=formated_buttons,
        border=None,
        background_img=info_card_property.card_background_image_url,
        image_icn=info_card_property.card_optional_image_url,
        card_action_type=info_card_property.card_action,
        card_action_destination=info_card_property.card_destination,
    )
    return formated_data


def get_application_status_webview(customer):
    application = customer.application_set.filter(
        workflow__name=WorkflowConst.JULO_ONE).last()
    if not application:
        return general_error_response("Aplikasi {}".format(ErrorMessageConst.NOT_FOUND))

    return_dict = {
        "application_id": application.id,
        "application_xid": application.application_xid,
        "application_status_code": application.application_status_id
    }
    return success_response(return_dict)


def get_count_request_on_redis(identifier, prefix_key=None):
    if prefix_key:
        redis_key = '%s_%s' % (prefix_key, identifier)
    else:
        redis_key = '%s_%s' % (
            PartnershipRedisPrefixKey.WEBVIEW_CREATE_LOAN, identifier)
    redis_cache = RedisCache(key=redis_key, hours=1)
    # Redis value for this key will be '{count};{date}'
    value = redis_cache.get()
    if not value:
        request_count = 0
    else:
        request_count = int(value.split(';')[0])

    return request_count, value


def create_customer_pin(customer_data, application):
    customer = application.customer
    with transaction.atomic():
        user = customer.user
        user.set_password(customer_data['pin'])
        user.save()
        try:
            customer_pin_service = CustomerPinService()
            customer_pin_service.init_customer_pin(user)

        except IntegrityError:
            return general_error_response('PIN aplikasi sudah ada')
    # link to partner attribution rules
    partner_referral = link_to_partner_if_exists(application)
    response_data = {
        "token": str(user.auth_expiry_token),
        "customer": CustomerSerializer(customer).data,
        "applications": [ApplicationSerializer(application).data],
        "partner": PartnerReferralSerializer(partner_referral).data,
        "device_id": None
    }

    return created_response(response_data)


def calculate_loan_partner_simulations(partner_config: Partner, amount: float,
                                       is_number_result: bool = False) -> Dict:
    """
        This Function get from redis data
        Formula Calculate:
        amount_calculation = [(amount+ origination rate * transaction amount)/tenor option]
        get_interest = amount * common monthly interest rate
    """

    offering_loan_result = {
        'loan_offers_in_str': [],
        'loan_offers_in_number': [],
    }

    redis_key = '%s_%s' % ("partner_simulation_key:", partner_config.id)
    redis_client = get_redis_client()
    partner_simulations = redis_client.get(redis_key)
    if not partner_simulations:
        return offering_loan_result

    is_show_interest_rate = partner_config.is_show_interest_in_loan_simulations
    partner_simulations = json.loads(partner_simulations)
    for simulation in partner_simulations:
        origination_rate = simulation['origination_rate']
        interest_rate = simulation['interest_rate']
        tenure = simulation['tenure']

        amount_calculation = (amount + (origination_rate * amount)) / tenure
        interest_rate_amount = amount * interest_rate
        monthly_installment = round(amount_calculation + interest_rate_amount)
        monthly_interest_rate = round(interest_rate * 100, 2)

        if is_number_result:
            loan_offers = {
                'monthly_installment': monthly_installment,
                'tenure': tenure,
            }

            if is_show_interest_rate:
                loan_offers['monthly_interest_rate'] = monthly_interest_rate

            offering_loan_result['loan_offers_in_number'].append(loan_offers)
        else:
            loan_offers = {
                'monthly_installment': display_rupiah(monthly_installment),
                'tenure': '{} Bulan'.format(tenure),
            }

            if is_show_interest_rate:
                loan_offers['monthly_interest_rate'] = 'Bunga {} %'.format(monthly_interest_rate)

            offering_loan_result['loan_offers_in_str'].append(loan_offers)

    return offering_loan_result


def store_partner_simulation_data_in_redis(indetifier: str, partner_simulations: List) -> List:
    """
        Store simulation data to redis
    """
    list_of_partner_simulations = []

    if not partner_simulations:
        return

    for simulation in partner_simulations:
        data = {
            "id": simulation.id,
            "origination_rate": simulation.origination_rate,
            "interest_rate": simulation.interest_rate,
            "tenure": simulation.tenure,
            "is_active": simulation.is_active
        }
        list_of_partner_simulations.append(data)

    redis_client = get_redis_client()
    redis_client.set(indetifier, json.dumps(list_of_partner_simulations), 86_400)  # expire in 1 Day

    return list_of_partner_simulations


def send_email_otp_webview(email, partner, nik, token,
                           action_type=SessionTokenAction.REGISTER):
    feature_setting = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.EMAIL_OTP)
    if not feature_setting or not feature_setting.is_active:
        return general_error_response(message="feature setting email otp tidak aktif")
    otp_wait_seconds = feature_setting.parameters['wait_time_seconds']
    otp_max_request = feature_setting.parameters['otp_max_request']
    otp_resend_time = feature_setting.parameters['otp_resend_time']
    return_data = {
        "message": None,
        "content": {
            "otp_max_request": otp_max_request,
            "otp_wait_seconds": otp_wait_seconds,
            "otp_resend_time": otp_resend_time
        }
    }

    partnership_customer_data_otp_prefetch = Prefetch(
        'partnership_customer_data_otps',
        queryset=PartnershipCustomerDataOTP.objects.filter(
            otp_type=PartnershipCustomerDataOTP.EMAIL
        ),
        to_attr='partnership_customer_data_otp'
    )
    pii_filter_dict = generate_pii_filter_query_partnership(PartnershipCustomerData, {'nik': nik})
    partnership_customer_data = (
        PartnershipCustomerData.objects.filter(
            token=token, otp_status=PartnershipCustomerData.VERIFIED, **pii_filter_dict
        )
        .prefetch_related(partnership_customer_data_otp_prefetch)
        .last()
    )
    if not partnership_customer_data:
        return general_error_response('Data tidak ditemukan')

    # will return error when:
    # request register but email in partnership_customer_data exist
    # request login but email in partnership_customer_data not exist
    # request login but with different email
    if action_type == SessionTokenAction.REGISTER:
        is_verified = partnership_customer_data.email_otp_status == PartnershipCustomerData.VERIFIED
        customer_email = partnership_customer_data.email
        if partnership_customer_data.customer:
            customer_xid = partnership_customer_data.customer.customer_xid
            detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
                PiiSource.PARTNERSHIP_APPLICATION_DATA,
                partnership_customer_data,
                customer_xid,
                ['email'],
            )
            customer_email = detokenize_partnership_customer_data.email

        if customer_email and is_verified:
            return general_error_response(
                'Akun sudah terdaftar, silahkan langsung masuk ke akun Anda')
    else:
        if not partnership_customer_data.email:
            return general_error_response('Email tidak ditemukan, silahkan daftar terlebih dahulu')
        if partnership_customer_data.email != email:
            return general_error_response(
                'Email, NIK, Nomor Telepon, PIN, atau Kata Sandi kamu salah')

    with transaction.atomic():
        partnership_customer_data.update_safely(email=email)
        pcd_otp, created = PartnershipCustomerDataOTP.objects.get_or_create(
            partnership_customer_data=partnership_customer_data,
            otp_type=PartnershipCustomerDataOTP.EMAIL,
        )

        logger.info({
            "status": "created" if created else "exists",
            "partnership_customer_data_otp": pcd_otp
        })

        existing_otp_request = OtpRequest.objects.filter(
            partnership_customer_data=partnership_customer_data,
            is_used=False,
            email=email,
            action_type=action_type
        ).order_by('id').last()

        response = trigger_email_otp_sending(
            existing_otp_request,
            partnership_customer_data,
            feature_setting, email, partner,
            action_type
        )

        otp_request, data = response
        if not data["success"]:
            return_data["message"] = data["message"]
            return_data["content"] = data["content"]
            return general_error_response(return_data)
        else:
            return_data['message'] = "Email OTP JULO sudah dikirim"
            send_email_otp_token.delay(None, otp_request.id, email)

    return success_response(return_data)


def trigger_email_otp_sending(existing_otp_request, partnership_customer_data,
                              feature_setting, email, partner, action_type):
    """
    prepare email otp before sended

    param:
        - existing_otp_request (OtpRequest obj): otp request object
        - partnership_customer_data (PartnershipCustomerData obj): partnership customer data object
        - feature_setting (FeatureSetting obj): feature setting object
        - email (str) : email
        - partner (Partner obj): partner object
        - action_type (str): type of action type

    return:
        - otp_request obj and dict of data
    """
    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = feature_setting.parameters['wait_time_seconds']
    otp_max_request = feature_setting.parameters['otp_max_request']
    otp_resend_time = feature_setting.parameters['otp_resend_time']
    data = {
        "success": True,
        "message": "email sent is rejected",
        "content": {
            "active": feature_setting.is_active,
            "expired_time": None,
            "resend_time": None,
            "otp_max_request": otp_max_request,
            "retry_count": 0,
            "current_time": curr_time
        }
    }
    if existing_otp_request and not existing_otp_request.is_expired:
        email_history = existing_otp_request.email_history
        prev_time = timezone.localtime(
            email_history.cdate) if email_history else timezone.localtime(
            existing_otp_request.cdate)
        expired_time = timezone.localtime(existing_otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        resend_time = timezone.localtime(prev_time) + timedelta(seconds=otp_resend_time)
        retry_count = 0

        if partnership_customer_data.customer:
            retry_count = EmailHistory.objects.filter(
                customer=partnership_customer_data.customer,
                cdate__gte=existing_otp_request.cdate
            ).exclude(status=PartnershipEmailHistory.PENDING).count()

        retry_count += 1

        data['content']['expired_time'] = expired_time
        data['content']['resend_time'] = resend_time
        data['content']['retry_count'] = retry_count

        if retry_count > otp_max_request:
            data["success"] = False
            data['message'] = "Permohonan otp melebihi batas maksimal,"\
                "Anda dapat mencoba beberapa saat lagi"
        if curr_time < resend_time:
            data["success"] = False
            data['message'] = "Tidak bisa mengirim ulang kode otp," \
                " belum memenuhi waktu yang ditentukan"

        if data["success"]:
            # update otp token and request id
            otp_token, postfixed_request_id = create_otp_token(partnership_customer_data)
            existing_otp_request.update_safely(otp_token=otp_token, request_id=postfixed_request_id)
        otp_request = existing_otp_request
    else:
        otp_token, postfixed_request_id = create_otp_token(partnership_customer_data)
        otp_request = OtpRequest.objects.create(
            partnership_customer_data=partnership_customer_data,
            request_id=postfixed_request_id,
            otp_token=otp_token, application=None,
            otp_service_type=OTPType.EMAIL,
            action_type=action_type, email=email)
        data['message'] = "Kode verifikasi sudah dikirim"
        data['content']['expired_time'] = timezone.localtime(otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        data['content']['retry_count'] = 1

    if partner:
        partnership_config = PartnershipConfig.objects.filter(partner=partner).last()
        if partnership_config and partnership_config.is_validation_otp_checking:
            PartnershipUserOTPAction.objects.update_or_create(
                otp_request=otp_request.id, is_used=False
            )

    return otp_request, data


def email_otp_validation_webview(otp_token: str, email: str,
                                 partnership_customer_data_token: str):
    feature_setting = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.EMAIL_OTP)
    if not feature_setting or not feature_setting.is_active:
        return success_response(
            data={
                "success": True,
                "content": {
                    "active": feature_setting.is_active,
                    "parameters": feature_setting.parameters,
                    "message": "Verifikasi kode tidak aktif"
                }
            }
        )
    with transaction.atomic():
        partnership_customer_data_otp_prefetch = Prefetch(
            'partnership_customer_data_otps',
            queryset=PartnershipCustomerDataOTP.objects.filter(
                otp_type=PartnershipCustomerDataOTP.EMAIL
            ),
            to_attr='partnership_customer_data_otp'
        )
        pii_filter_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData, {'email': email}
        )
        partnership_customer_data = (
            PartnershipCustomerData.objects.filter(
                token=partnership_customer_data_token, **pii_filter_dict
            )
            .prefetch_related(partnership_customer_data_otp_prefetch)
            .last()
        )
        if not partnership_customer_data:
            return general_error_response("Data tidak ditemukan")
        partnership_customer_data_otp =\
            partnership_customer_data.partnership_customer_data_otp[0]
        existing_otp_request = OtpRequest.objects.filter(
            otp_token=otp_token, partnership_customer_data=partnership_customer_data, is_used=False
        ).order_by('id').last()
        if not existing_otp_request:
            logger.error({
                "status": "otp_token_not_found",
                "otp_token": otp_token,
                "partnership_customer_data": partnership_customer_data.id
            })

            partnership_customer_data_otp.otp_last_failure_time = timezone.localtime(timezone.now())
            partnership_customer_data_otp.otp_latest_failure_count = \
                partnership_customer_data_otp.otp_latest_failure_count + 1
            partnership_customer_data_otp.otp_failure_count = \
                partnership_customer_data_otp.otp_failure_count + 1
            partnership_customer_data_otp.save()
            return general_error_response("Kode verifikasi belum terdaftar")

        if str(partnership_customer_data.id) not in existing_otp_request.request_id:
            logger.error("Kode verifikasi tidak valid")

        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        valid_token = hotp.verify(otp_token, int(existing_otp_request.request_id))
        if not valid_token:
            logger.error({
                "status": "invalid_token",
                "otp_token": otp_token,
                "otp_request": existing_otp_request.id,
                "partnership_customer_data": partnership_customer_data.id
            })
            partnership_customer_data_otp.otp_last_failure_time = \
                timezone.localtime(timezone.now())
            partnership_customer_data_otp.otp_latest_failure_count = \
                partnership_customer_data_otp.otp_latest_failure_count + 1
            partnership_customer_data_otp.save()
            return general_error_response("Kode verifikasi tidak valid")

        if existing_otp_request.is_expired:
            logger.error({
                "status": "otp_token_expired",
                "otp_token": otp_token,
                "otp_request": existing_otp_request.id,
                "partnership_customer_data": partnership_customer_data.id
            })
            return general_error_response("Kode verifikasi kadaluarsa")

        existing_otp_request.is_used = True
        existing_otp_request.save(update_fields=['is_used'])
        return_data = {'secret_key': partnership_customer_data.token}
        partnership_customer_data.update_safely(email_otp_status=PartnershipCustomerData.VERIFIED)
        partnership_customer_data_otp.otp_latest_failure_count = 0
        partnership_customer_data_otp.save(
            update_fields=['otp_latest_failure_count'])
    return success_response(return_data)


def create_otp_token(pcd: PartnershipCustomerData):
    hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
    postfixed_request_id = str(pcd.id) + str(int(time.time()))
    otp_token = str(hotp.at(int(postfixed_request_id)))
    return otp_token, postfixed_request_id


def leadgen_process_reset_pin_request(customer: Customer):
    email = customer.email
    password_type = 'pin'
    customer_pin_change_service = pin_services.CustomerPinChangeService()

    if customer.reset_password_exp_date is None or customer.has_resetkey_expired():
        new_key_needed = True
    else:
        new_key_needed = False

    if new_key_needed:
        reset_pin_key = generate_email_key(email)
        customer.reset_password_key = reset_pin_key
        reset_pin_exp_date = datetime.now() + timedelta(days=7)
        customer.reset_password_exp_date = reset_pin_exp_date
        customer.save()
        customer_pin = customer.user.pin
        customer_pin_change_service.init_customer_pin_change(
            email=email,
            phone_number=None,
            expired_time=reset_pin_exp_date,
            customer_pin=customer_pin,
            change_source='Forget PIN',
            reset_key=reset_pin_key
        )
        logger.info({
            'status': 'just_generated_reset_%s' % password_type,
            'email': email,
            'customer': customer,
            'reset_%s_key' % password_type: reset_pin_key,
            'reset_%s_exp_date' % password_type: reset_pin_exp_date
        })
    else:
        reset_pin_key = customer.reset_password_key
        logger.info({
            'status': 'reset_%s_key_already_generated' % password_type,
            'email': email,
            'customer': customer,
            'reset_%s_key' % password_type: reset_pin_key
        })

    send_reset_pin_email.delay(email, reset_pin_key)
    # Set redis cache to block incoming request on 30 minutes
    redis_key = '%s: %s' % (PartnershipRedisPrefixKey.LEADGEN_RESET_PIN_EMAIL, email)
    redis_cache = RedisCache(redis_key, minutes=30)
    now = timezone.localtime(timezone.now())
    now_formatted = now.strftime('%Y-%m-%d %H:%M:%S')
    redis_cache.set(now_formatted)


def check_is_valid_otp_token_and_retry_attempt(existing_otp_request, feature_setting, otp_token):
    otp_max_validate = feature_setting.parameters['otp_max_validate']

    if existing_otp_request.retry_validate_count >= otp_max_validate:
        return "Kesempatan mencoba OTP sudah habis, " \
               "coba kembali beberapa saat lagi"

    existing_otp_request.update_safely(retry_validate_count=F('retry_validate_count') + 1)
    wait_time_seconds = feature_setting.parameters['wait_time_seconds']
    if not check_otp_request_is_active(existing_otp_request, wait_time_seconds):
        return "OTP telah kadaluarsa. Silahkan kirim ulang permintaan kode OTP"

    if existing_otp_request.otp_token != str(otp_token):
        if existing_otp_request.retry_validate_count == 1:
            err_msg = 'OTP tidak sesuai, coba kembali'
        elif existing_otp_request.retry_validate_count == 2:
            err_msg = 'OTP yang kamu masukan salah'
        else:
            err_msg = 'Kesempatan mencoba OTP sudah habis, coba kembali beberapa saat lagi'

        return err_msg

    return None


def whitelabel_email_otp_request(
    email: str, action_type: str=SessionTokenAction.PAYLATER_LINKING,
    paylater_transaction_xid: str = '',
    nik: str = '',
) -> Response:
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.EMAIL_OTP
    )
    if not feature_setting or not feature_setting.is_active:
        return Response(
            data={
                "success": True,
                "content": {
                    "active": feature_setting.is_active,
                    "parameters": feature_setting.parameters,
                    "message": "Verifikasi kode tidak aktif",
                },
            }
        )
    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = feature_setting.parameters["wait_time_seconds"]
    otp_max_request = feature_setting.parameters["otp_max_request"]
    otp_resend_time = feature_setting.parameters["otp_resend_time"]
    data = {
        "success": True,
        "content": {
            "active": feature_setting.is_active,
            "expired_time": None,
            "resend_time": None,
            "otp_max_request": otp_max_request,
            "retry_count": 0,
            "current_time": curr_time,
        },
    }

    customer = Customer.objects.filter(email=email.lower()).last()
    if not customer and not paylater_transaction_xid:
        data['success'] = False
        data["content"]["message"] = ErrorMessageConst.CUSTOMER_NOT_FOUND
        return Response(data=data)

    existing_otp_request = (
        OtpRequest.objects.filter(
            customer=customer, is_used=False, email=email, action_type=action_type
        )
        .order_by("id")
        .last()
    )
    if paylater_transaction_xid:
        customer_with_nik = Customer.objects.filter(nik=nik).last()
        if customer or customer_with_nik:
            data['success'] = False
            data["content"]["message"] = (
                'NIK/Email sudah terdaftar, ' 'Silahkan langsung masuk ke akun Anda'
            )
            return Response(data=data)

        paylater_transaction = PaylaterTransaction.objects.filter(
            paylater_transaction_xid=paylater_transaction_xid
        ).last()
        if not paylater_transaction:
            data['success'] = False
            data["content"]["message"] = ErrorMessageConst.INVALID_PAYLATER_TRANSACTION_XID
            return Response(data=data)

    if existing_otp_request and not existing_otp_request.is_expired:
        email_history = existing_otp_request.email_history
        prev_time = (
            timezone.localtime(email_history.cdate)
            if email_history
            else timezone.localtime(existing_otp_request.cdate)
        )
        expired_time = timezone.localtime(existing_otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
        resend_time = timezone.localtime(prev_time) + timedelta(seconds=otp_resend_time)
        retry_count = (
            EmailHistory.objects.filter(
                customer=customer, cdate__gte=existing_otp_request.cdate
            )
            .exclude(status=PartnershipEmailHistory.PENDING)
            .count()
        )
        retry_count += 1

        data["content"]["expired_time"] = expired_time
        data["content"]["resend_time"] = resend_time
        data["content"]["retry_count"] = retry_count

        if retry_count > otp_max_request:
            data["success"] = False
            data["content"]["message"] = (
                "Permohonan otp melebihi batas maksimal,"
                "Anda dapat mencoba beberapa saat lagi"
            )
        if curr_time < resend_time:
            data["success"] = False
            data["content"]["message"] = (
                "Tidak bisa mengirim ulang kode otp,"
                " belum memenuhi waktu yang ditentukan"
            )

        if data["success"]:
            # update otp token and request id
            if paylater_transaction_xid:
                otp_token, postfixed_request_id = create_otp_token(paylater_transaction)
            else:
                otp_token, postfixed_request_id = create_otp_token(customer)
            existing_otp_request.update_safely(
                otp_token=otp_token, request_id=postfixed_request_id
            )
        otp_request = existing_otp_request
    else:
        if paylater_transaction_xid:
            otp_token, postfixed_request_id = create_otp_token(paylater_transaction)
        else:
            otp_token, postfixed_request_id = create_otp_token(customer)
        if customer:
            application = customer.application_set.filter(
                workflow__name=WorkflowConst.JULO_ONE,
                product_line__product_line_code__in=ProductLineCodes.julo_one(),
                application_status_id=ApplicationStatusCodes.LOC_APPROVED,
            ).last()
        else:
            application = None
        otp_request = OtpRequest.objects.create(
            customer=customer,
            request_id=postfixed_request_id,
            otp_token=otp_token,
            otp_service_type=OTPType.EMAIL,
            action_type=action_type,
            email=email,
            application=application
        )
        data["content"]["message"] = "Kode verifikasi sudah dikirim"
        data["content"]["expired_time"] = timezone.localtime(
            otp_request.cdate
        ) + timedelta(seconds=otp_wait_seconds)
        data["content"]["retry_count"] = 1

    if not data["success"]:
        return Response(data=data)
    else:
        data["content"]["message"] = "Email OTP JULO sudah dikirim"
        if customer:
            send_email_otp_token.delay(customer.id, otp_request.id, email)
        else:
            send_email_otp_token.delay(None, otp_request.id, email)
    return Response(data=data)


def get_webview_info_card_button_for_linkaja(customer, response):
    application = customer.application_set.regular_not_deletes().filter(
        workflow__name=WorkflowConst.JULO_ONE).last()
    application_status_code = application.application_status.status_code
    is_valid_status_codes = {
        ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.APPLICATION_RESUBMITTED,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
    }

    is_valid_cards = (response and response.data and response.data.get('data', None)
                      and response.data['data'].get('cards', None))
    if application_status_code in is_valid_status_codes and is_valid_cards:
        cards = response.data['data']['cards']
        for i in range(0, len(cards)):
            card = cards[i]
            streamlined_communication = StreamlinedCommunication.objects.filter(
                show_in_web=True,
                show_in_android=False,
                communication_platform=CommunicationPlatform.INFO_CARD,
                status_code_id=ApplicationStatusCodes.FORM_CREATED,
                extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CARD_BUTTON_FOR_LINKAJA,
                is_active=True
            ).last()
            if streamlined_communication:
                streamlined_message = streamlined_communication.message
                info_card_property = streamlined_message.info_card_property
                button_list = info_card_property.button_list
                formated_buttons = []
                for button in button_list:
                    formated_buttons.append(
                        {
                            "colour": info_card_property.text_color,
                            "text": button.text,
                            "textcolour": button.text_color,
                            "action_type": button.action_type,
                            "destination": button.destination,
                            "border": None,
                            "background_img": button.background_image_url
                        }
                    )
                    card['button'] = formated_buttons

    return response


def get_gosel_skrtp_agreement(
    loan,
    application,
    partner_loan_request,
    html_template,
):
    template = Template(html_template.sphp_template)

    payments = loan.payment_set.exclude(is_restructured=True).order_by('id')
    payment_result = []
    index = 0
    for payment in payments.iterator():
        map_payment = {}
        index += 1
        map_payment['index'] = index
        map_payment['due_date'] = format_date(payment.due_date, 'd MMMM yyyy', locale='id_ID')
        map_payment['due_amount'] = display_rupiah(payment.due_amount)
        payment_result.append(map_payment)

    if not partner_loan_request.buying_amount:
        partner_loan_request.buying_amount = 0

    today = timezone.localtime(timezone.now()).date()
    param = {
        'application_xid': application.application_xid,
        'date_today': format_datetime(today, "d MMMM yyyy", locale='id_ID'),
        'customer_name': application.fullname,
        'dob': format_datetime(application.dob, "d MMMM yyyy", locale='id_ID'),
        'customer_nik': application.ktp,
        'customer_phone': application.mobile_phone_1,
        'full_address': application.full_address,
        'installment_amount': display_rupiah(math.floor(loan.installment_amount / 20)),
        'interest_rate': round((loan.product.monthly_interest_rate * 100), 2),
        'provision_amount': display_rupiah(
            math.floor(loan.loan_amount * partner_loan_request.provision_rate)),
        'principal_loan_amount': display_rupiah(loan.loan_disbursement_amount),
    }

    lender = loan.lender
    if lender:
        param.update(
            {
                'poc_name': lender.poc_name,
                'license_number': lender.license_number,
                'lender_address': lender.lender_address,
                'lender_company_name': lender.company_name,
            }
        )

    if loan.loan_status_id >= LoanStatusCodes.LENDER_APPROVAL:
        param.update(
            {
                'customer_signature': application.fullname,
            }
        )

    if loan.loan_status_id >= LoanStatusCodes.FUND_DISBURSAL_ONGOING:
        param.update(
            {
                'lender_signature_name': lender.poc_name,
            }
        )

    context_obj = Context(param)
    content_skrtp = template.render(context_obj)

    return content_skrtp


def get_merchant_skrtp_agreement(
    loan,
    application,
    partner_loan_request,
    html_template,
    account_limit,
    partnership_application_data,
    distributor,
    payment_method,
    is_new_digisign=False,
):
    template = Template(html_template.sphp_template)

    tenure_unit = 'Hari'
    if partner_loan_request.loan_duration_type == LoanDurationType.MONTH:
        tenure_unit = 'Bulan'

    loan_duration = '{} {}'.format(
        loan.loan_duration, tenure_unit
    )
    payments = loan.payment_set.exclude(is_restructured=True).order_by('id')
    payment_result = []
    index = sum_interest_amount = 0
    for payment in payments.iterator():
        map_payment = {}
        index += 1
        map_payment['index'] = index
        map_payment['due_date'] = format_date(payment.due_date, 'd MMMM yyyy', locale='id_ID')
        map_payment['due_amount'] = display_rupiah(payment.due_amount)
        payment_result.append(map_payment)
        sum_interest_amount += payment.installment_interest

    product_lookup = ProductLookup.objects.filter(
        product_line__product_line_code=ProductLineCodes.AXIATA_WEB,
        product_code=loan.product.product_code
    ).first()

    late_fee_rate = product_lookup.late_fee_pct / 30
    payment = payments[0]
    installment_amount = payment.installment_principal + payment.installment_interest
    raw_late_fee = installment_amount * late_fee_rate * FIXED_DPD
    rounded_late_fee = int(round_half_up(raw_late_fee))
    if not partner_loan_request.buying_amount:
        partner_loan_request.buying_amount = 0

    today = timezone.localtime(timezone.now()).date()

    customer_xid = application.customer.customer_xid
    detokenize_partnership_application_data = partnership_detokenize_sync_object_model(
        PiiSource.PARTNERSHIP_APPLICATION_DATA,
        partnership_application_data,
        customer_xid,
        ['fullname', 'mobile_phone_1'],
    )

    partnership_customer_data = application.partnership_customer_data
    detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
        PiiSource.PARTNERSHIP_CUSTOMER_DATA,
        partnership_customer_data,
        customer_xid,
        ['nik'],
    )

    partner = application.partner
    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER, partner, customer_xid, ['email']
    )

    provision_amount = loan.loan_amount * partner_loan_request.provision_rate
    vat_amount = 0.11 * provision_amount
    e_sign_amount_gross_up = 0

    param = {
        'application_xid': application.application_xid,
        'date_today': format_datetime(today, "d MMMM yyyy", locale='id_ID'),
        'customer_name': detokenize_partnership_application_data.fullname,
        'dob': format_datetime(partnership_application_data.dob, "d MMMM yyyy", locale='id_ID'),
        'customer_nik': detokenize_partnership_customer_data.nik,
        'customer_phone': detokenize_partnership_application_data.mobile_phone_1,
        'full_address': application.full_address,
        'partner_email': detokenize_partner.email,
        'max_limit_amount': display_rupiah(account_limit.max_limit),
        'loan_xid': loan.loan_xid,
        'loan_purpose': loan.loan_purpose,
        'business_category': partnership_application_data.business_category,
        'merchant_name': distributor.distributor_name,
        'buyer_name': partner_loan_request.buyer_name,
        'receivable_amount': display_rupiah(partner_loan_request.buying_amount),
        'invoice_no': partner_loan_request.invoice_number,
        'loan_amount': display_rupiah(loan.loan_amount),
        'provision_amount': display_rupiah(provision_amount),
        'interest_amount': display_rupiah(sum_interest_amount),
        'available_limit': display_rupiah(account_limit.available_limit),
        'payments': payment_result,
        'loan_duration': loan_duration,
        'late_fee_amount': display_rupiah(rounded_late_fee),
        'maximum_late_fee_amount': display_rupiah(loan.loan_amount),
        'distributor_bank_account_number': distributor.distributor_bank_account_number,
        'distributor_bank_account_name': distributor.distributor_bank_account_name,
        'distributor_bank_name': distributor.bank_name,
        'va_bank_code': payment_method.bank_code,
        'va_number': payment_method.virtual_account,
        'vat_amount': display_rupiah(vat_amount),
        'e_sign_amount_gross_up': display_rupiah(e_sign_amount_gross_up),
        'payment_method_name': payment_method.payment_method_name,
    }

    lender = loan.lender
    if lender:
        param.update(
            {
                'poc_name': lender.poc_name,
                'poc_position': lender.poc_position,
                'license_number': lender.license_number,
                'lender_address': lender.lender_address,
            }
        )

    if not is_new_digisign:
        if loan.loan_status_id >= LoanStatusCodes.LENDER_APPROVAL:
            param.update(
                {
                    'customer_signature': detokenize_partnership_application_data.fullname,
                }
            )

    if loan.loan_status_id >= LoanStatusCodes.FUND_DISBURSAL_ONGOING:
        param.update(
            {
                'lender_signature_name': lender.poc_name,
            }
        )

    context_obj = Context(param)
    content_skrtp = template.render(context_obj)

    return content_skrtp


def ledgen_webapp_send_email_otp_request(email):
    action_type = SessionTokenAction.PARTNERSHIP_REGISTER_VERIFY_EMAIL
    hashing_request_id = hashlib.sha256(email.encode()).digest()
    b64_encoded_request_id = base64.urlsafe_b64encode(hashing_request_id).decode()

    redis_client = get_redis_client()
    otp_type = OTPType.EMAIL
    data = {
        "expired_time": None,
        "resend_time": None,
        "waiting_time": None,
        "retry_count": 0,
        "attempt_left": 0,
        "request_time": None,
        "otp_service_type": otp_type,
        "request_id": b64_encoded_request_id,
    }

    # Get feature setting for leadgen OTP
    all_otp_settings = PartnershipFeatureSetting.objects.filter(
        is_active=True,
        feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
    ).last()
    if not all_otp_settings:
        return OTPRequestStatus.FEATURE_NOT_ACTIVE, data

    # Get otp setting for otp type email
    otp_setting = all_otp_settings.parameters.get('email', {})
    if not otp_setting:
        return OTPRequestStatus.FEATURE_NOT_ACTIVE, data

    curr_time = timezone.localtime(timezone.now())
    otp_wait_seconds = otp_setting['wait_time_seconds']
    otp_max_request = otp_setting['otp_max_request']
    otp_expired_time = otp_setting['otp_expired_time']
    otp_resend_time = otp_setting['otp_resend_time']
    retry_count = 1

    otp_request_query = PartnershipUserOTPAction.objects.filter(
        request_id=b64_encoded_request_id, otp_service_type=otp_type
    ).order_by('id')

    # get existing otp
    existing_otp_request = otp_request_query.last()

    # get total retries
    otp_requests = otp_request_query.filter(
        cdate__gte=(curr_time - relativedelta(seconds=otp_wait_seconds))
    )
    otp_request_count = otp_requests.count()

    # Get if user is blocked because max request attempt
    redis_key = 'leadgen_webapp_otp_request_register_blocked:{}:{}'.format(email, action_type)
    is_blocked_max_attempt = redis_client.get(redis_key)

    if existing_otp_request:
        previous_time = timezone.localtime(existing_otp_request.cdate)
        exp_time = previous_time + relativedelta(seconds=otp_expired_time)
        resend_time = previous_time + relativedelta(seconds=otp_resend_time)
        # Check max attempt
        retry_count += otp_request_count

        if is_blocked_max_attempt:
            # calculate when can request otp again
            blocked_time = timezone.localtime(previous_time) + relativedelta(
                seconds=otp_wait_seconds
            )

            if curr_time < blocked_time:
                data['expired_time'] = exp_time
                data['retry_count'] = retry_count
                data['resend_time'] = blocked_time
                data['attempt_left'] = 0
                return OTPRequestStatus.LIMIT_EXCEEDED, data

        if retry_count > otp_max_request:
            last_request_timestamp = timezone.localtime(otp_requests.last().cdate)
            exp_time = last_request_timestamp + relativedelta(seconds=otp_expired_time)

            # calculate when can request otp again
            blocked_time = timezone.localtime(otp_requests.last().cdate) + relativedelta(
                seconds=otp_wait_seconds
            )

            if curr_time < blocked_time:
                data['expired_time'] = exp_time
                data['retry_count'] = retry_count
                data['resend_time'] = blocked_time
                data['attempt_left'] = 0

                # Set if user is blocked because max request attempt
                if not is_blocked_max_attempt:
                    redis_client.set(redis_key, True)
                    redis_client.expireat(redis_key, blocked_time)

                return OTPRequestStatus.LIMIT_EXCEEDED, data

        # Check resend time
        if curr_time < resend_time:
            data['request_time'] = previous_time
            data['expired_time'] = exp_time
            data['retry_count'] = retry_count - 1
            data['resend_time'] = resend_time
            data['attempt_left'] = otp_max_request - data['retry_count']
            return OTPRequestStatus.RESEND_TIME_INSUFFICIENT, data

    # send OTP
    hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
    current_timestamp = timezone.localtime(timezone.now()).timestamp()
    unique_data = "{}{}".format(email, int(current_timestamp))
    hashed_counter = int(hashlib.sha256(unique_data.encode()).hexdigest(), 16)
    otp = hotp.at(hashed_counter)
    otp_request = OtpRequest.objects.create(
        request_id=b64_encoded_request_id,
        otp_token=otp,
        email=email,
        otp_service_type=OTPType.EMAIL,
        action_type=action_type,
    )
    PartnershipUserOTPAction.objects.create(
        otp_request=otp_request.id,
        request_id=b64_encoded_request_id,
        otp_service_type=OTPType.EMAIL,
        action_type=action_type,
        is_used=False,
    )
    leadgen_send_email_otp_token_register.delay(email, otp_request.id)

    curr_time = timezone.localtime(otp_request.cdate)
    data['request_time'] = curr_time
    data['expired_time'] = curr_time + relativedelta(seconds=otp_expired_time)
    data['retry_count'] = retry_count
    data['resend_time'] = curr_time + relativedelta(seconds=otp_resend_time)
    data['attempt_left'] = otp_max_request - retry_count

    return OTPRequestStatus.SUCCESS, data


def leadgen_webapp_validate_otp(request_id: str, email: str, otp_token: str) -> Tuple[str, str]:
    action_type = SessionTokenAction.PARTNERSHIP_REGISTER_VERIFY_EMAIL
    data = {'retry_count': 0}
    # Get latest available otp request
    partnership_otp_action = PartnershipUserOTPAction.objects.filter(
        request_id=request_id, action_type=action_type, is_used=False
    ).last()
    if not partnership_otp_action:
        return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]

    # Validate OTP email
    otp_request = OtpRequest.objects.filter(id=partnership_otp_action.otp_request).last()
    if not otp_request or otp_request.email != email:
        return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]

    # Get OTP feature settings
    all_otp_settings = PartnershipFeatureSetting.objects.filter(
        is_active=True,
        feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
    ).last()
    if not all_otp_settings:
        return (
            OTPValidateStatus.FEATURE_NOT_ACTIVE,
            otp_validate_message_map[OTPValidateStatus.FEATURE_NOT_ACTIVE],
        )

    otp_setting = all_otp_settings.parameters.get('email', {})
    if not otp_setting:
        return (
            OTPValidateStatus.FEATURE_NOT_ACTIVE,
            otp_validate_message_map[OTPValidateStatus.FEATURE_NOT_ACTIVE],
        )

    # Validate max validate
    otp_max_validate = otp_setting['otp_max_validate']
    otp_request.update_safely(retry_validate_count=F('retry_validate_count') + 1)
    data['retry_count'] = otp_request.retry_validate_count
    if otp_request.retry_validate_count > otp_max_validate:
        return (
            OTPValidateStatus.LIMIT_EXCEEDED,
            otp_validate_message_map[OTPValidateStatus.LIMIT_EXCEEDED],
        )

    # Check OTP Token
    if otp_request.action_type != action_type:
        return OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED]

    if otp_request.otp_token != otp_token:
        if otp_request.retry_validate_count == 1:
            return (OTPValidateStatus.FAILED, otp_validate_message_map[OTPValidateStatus.FAILED])
        elif otp_request.retry_validate_count >= otp_max_validate:
            return (
                OTPValidateStatus.FAILED,
                otp_validate_message_map[OTPValidateStatus.LIMIT_EXCEEDED],
            )
        else:
            error_message = "Kode OTP salah. Kamu punya kesempatan coba {} kali lagi."
            attempt_left = otp_max_validate - otp_request.retry_validate_count
            return (OTPValidateStatus.FAILED, error_message.format(attempt_left))

    # Validate otp expired time
    otp_expired_time = otp_setting['otp_expired_time']
    current_time = timezone.localtime(timezone.now())
    exp_time = timezone.localtime(otp_request.cdate) + relativedelta(seconds=otp_expired_time)
    if current_time > exp_time:
        return OTPValidateStatus.EXPIRED, otp_validate_message_map[OTPValidateStatus.EXPIRED]

    otp_request.update_safely(is_used=True)
    partnership_otp_action.update_safely(is_used=True)

    return OTPValidateStatus.SUCCESS, otp_validate_message_map[OTPValidateStatus.SUCCESS]
