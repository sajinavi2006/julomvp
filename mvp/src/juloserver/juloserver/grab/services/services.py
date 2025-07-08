from __future__ import division

from __future__ import print_function

from http import HTTPStatus
import time

import datetime
import random
import hashlib

from builtins import range
import json
import logging
import math
from typing import (
    Iterable,
    Union,
    Tuple,
    List,
    Dict
)
import uuid
import os
import binascii
import re
import hmac
from operator import itemgetter
import requests
import shortuuid

import pyotp
from hashids import Hashids
from requests.exceptions import Timeout
from rest_framework import status as https_status_codes
from django.conf import settings
from babel.dates import format_date
from juloserver.julo.utils import (add_plus_62_mobile_phone,
                                   display_rupiah,
                                   format_e164_indo_phone_number,
                                   generate_email_key)
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import QuerySet, Sum, Prefetch, Q, F
from django.shortcuts import render
from datetime import timedelta, date
from dateutil.relativedelta import relativedelta
from django.db.models import Min
from django.db import connection, utils

from django.template.loader import render_to_string

from django.utils import timezone
from past.utils import old_div
from juloserver.grab.clients.paths import GrabPaths

import juloserver.pin.services as pin_services
from juloserver.pin.constants import ReturnCode

from juloserver.account.models import Account, AccountLimit
from juloserver.account.services.credit_limit import update_available_limit
from juloserver.disbursement.models import NameBankValidation
from juloserver.grab.clients.clients import GrabClient, send_grab_api_timeout_alert_slack
from juloserver.grab.constants import (
    GRAB_ACCOUNT_LOOKUP_NAME,
    GRAB_APPLICATION_FIELDS,
    GRAB_IMAGE_TYPES,
    GRAB_CUSTOMER_NAME,
    GRAB_REFERRAL_CASHBACK,
    GRAB_ALPHABET,
    GRAB_NUMBER,
    GRAB_CUSTOMER_BASE_ID,
    GrabAuthStatus,
    GrabAuthAPIErrorCodes,
    GrabApplicationConstants,
    GRAB_FAILED_3MAX_CREDITORS_CHECK,
    PromoCodeStatus,
    GrabExperimentConst,
    GRAB_DOMAIN_NAME,
    INFO_CARD_AJUKAN_PINJAMAN_LAGI_DESC,
    grab_rejection_mapping_statuses,
    TIME_DELAY_IN_MINUTES_190,
    GrabErrorMessage,
    GrabErrorCodes,
    GrabWriteOffStatus,
    GrabApplicationPageNumberMapping,
    GrabApiLogConstants,
    GrabMasterLockReasons,
    GrabFeatureNameConst,
)
from juloserver.grab.exceptions import (
    GrabLogicException,
    GrabApiException,
    GrabHandlerException,
    GrabServiceApiException,
)
from juloserver.grab.forms import GrabApplicationForm
from juloserver.grab.models import *
from juloserver.grab.tasks import (trigger_application_creation_grab_api,
                                   trigger_auth_call_for_loan_creation,
                                   trigger_sms_to_submit_digisign,
                                   grab_send_reset_pin_sms)
from juloserver.grab.serializers import (GrabApplicationReviewSerializer, GrabAccountPageSerializer,
                                         GrabApplicationSerializer,
                                         GrabApplicationPopulateSerializer,
                                         GrabApplicationPopulateReapplySerializer,
                                         GrabLoanOfferSerializer,
                                         GrabChoosePaymentPlanSerializer,
                                         GrabLoanOfferArchivalSerializer,
                                         GrabApplicationV2Serializer)
from juloserver.grab.services.loan_related import generate_loan_payment_grab, get_loan_repayment_amount
from juloserver.julo.constants import WorkflowConst, FeatureNameConst, MobileFeatureNameConst
from juloserver.julo.formulas import round_rupiah_grab
from juloserver.julo.models import CustomerAppAction, Workflow, OtpRequest
from juloserver.julo.models import (
    Payment,
    Image,
    Partner,
    ProductLine,
    StatusLookup,
    ProductLookup,
    Bank,
    PaybackTransaction,
    FeatureSetting,
    ApplicationHistory,
    MobileFeatureSetting,
    LoanHistory,
    SmsHistory
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import (process_application_status_change, process_image_upload, update_customer_data,
                                      normal_application_status_change, experimentation)
from juloserver.julo.statuses import PaymentStatusCodes, ApplicationStatusCodes
from juloserver.julo.tasks import upload_image, send_sms_otp_token
from juloserver.julo.utils import check_email
from juloserver.grab.utils import GrabUtils
from juloserver.julo.statuses import LoanStatusCodes
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.paginator import Paginator

from juloserver.grab.services.growthbook import trigger_store_grab_customer_data_to_growthbook
from .repayment import (
    record_payback_transaction_grab,
    grab_payment_process_account
)
from juloserver.loan.services.views_related import get_sphp_template_grab
from juloserver.account_payment.models import AccountPayment
from juloserver.grab.services.loan_related import compute_payment_installment_grab

from juloserver.streamlined_communication.utils import add_thousand_separator, format_date_indo
from juloserver.streamlined_communication.models import StreamlinedCommunication
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform, CardProperty
)
from juloserver.streamlined_communication.services import (format_info_card_for_android,
                                                           format_bottom_sheet_for_grab)
from juloserver.julo_privyid.services.privy_services import get_info_cards_privy
from juloserver.pin.models import CustomerPin
from juloserver.pin.tasks import send_email_unlock_pin, send_email_lock_pin
from juloserver.julo.utils import format_nexmo_voice_phone_number, format_mobile_phone
from juloserver.api_token.authentication import make_never_expiry_token
from juloserver.apiv1.data import DropDownData
from juloserver.julo.models import Application, LoanPurpose, ApplicationFieldChange, CustomerFieldChange
from juloserver.grab.clients.request_constructors import GrabRequestDataConstructor
from juloserver.apiv2.models import AutoDataCheck
from juloserver.apiv1.dropdown import BirthplaceDropDown
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.grab.tasks import trigger_push_notification_grab
from juloserver.disbursement.constants import NameBankValidationStatus, NameBankValidationVendors
from juloserver.disbursement.services import trigger_name_in_bank_validation
from juloserver.otp.constants import (
    MisCallOTPStatus,
    CitcallRetryGatewayType,
    OTPType,
    FeatureSettingName,
    SessionTokenAction,
)
from juloserver.otp.exceptions import CitcallClientError
from juloserver.otp.models import MisCallOTP
from juloserver.otp.clients import get_citcall_client
from juloserver.account.models import AccountTransaction
from juloserver.julo.models import PaymentEvent
from juloserver.julo.services2 import get_redis_client
from juloserver.partnership.services.services import get_pin_settings
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.julo.tasks import update_payment_status_subtask
from juloserver.account_payment.tasks import update_account_payment_status_subtask
from juloserver.fdc.files import TempDir
from juloserver.julo.utils import upload_file_to_oss
from juloserver.grab.models import GrabAsyncAuditCron
from juloserver.julo.utils import get_oss_presigned_url_external
from rest_framework import serializers
from juloserver.julocore.python2.utils import py2round
from juloserver.grab.segmented_tasks.disbursement_tasks import (
    trigger_create_or_update_ayoconnect_beneficiary,
)
from juloserver.julocore.customized_psycopg2.base import IntegrityError
from juloserver.pii_vault.partnership.services import partnership_construct_pii_data
from juloserver.pii_vault.partnership.services import partnership_tokenize_pii_data
from juloserver.pii_vault.constants import PiiSource
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.pin.services import CustomerPinChangeService
from juloserver.julo.services2.sms import create_sms_history
from juloserver.otp.services import check_otp_request_is_active
from juloserver.urlshortener.services import shorten_url
from juloserver.application_form.constants import EmergencyContactConst
from juloserver.grab.services.crs_failed_validation_services import CRSFailedValidationService
from juloserver.disbursement.constants import DisbursementVendors

logger = logging.getLogger(__name__)

active_loan_status = [
    StatusLookup.CURRENT_CODE,
    StatusLookup.LOAN_1DPD_CODE,
    StatusLookup.LOAN_5DPD_CODE,
    StatusLookup.LOAN_30DPD_CODE,
    StatusLookup.LOAN_60DPD_CODE,
    StatusLookup.LOAN_90DPD_CODE,
    StatusLookup.LOAN_120DPD_CODE,
    StatusLookup.LOAN_150DPD_CODE,
    StatusLookup.LOAN_180DPD_CODE,
    StatusLookup.RENEGOTIATED_CODE,
]

inactive_loan_status = [
    StatusLookup.CANCELLED_BY_CUSTOMER,
    StatusLookup.SPHP_EXPIRED,
    StatusLookup.LENDER_REJECT,
    StatusLookup.PAID_OFF_CODE
]

graveyard_statuses = {
    ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,  # 106
    ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,  # 136
    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,  # 139
    ApplicationStatusCodes.APPLICATION_DENIED,  # 135
    ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,  # 137
    ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,  # 111
    ApplicationStatusCodes.OFFER_EXPIRED,  # 143
    ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED # 171
}

graveyard_loan_statuses = {
    LoanStatusCodes.PAID_OFF,
    LoanStatusCodes.CANCELLED_BY_CUSTOMER,
    LoanStatusCodes.SPHP_EXPIRED,
    LoanStatusCodes.LENDER_REJECT,
    LoanStatusCodes.GRAB_AUTH_FAILED,
    LoanStatusCodes.TRANSACTION_FAILED
}

rejected_statuses = {
    ApplicationStatusCodes.LOC_APPROVED,
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
    ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
}

excluded_statuses = graveyard_statuses | rejected_statuses


class GrabAuthService(object):
    @staticmethod
    def login(nik, pin):
        user = pin_services.get_user_from_username(nik)

        if not user or not hasattr(user, 'customer'):
            data = {
                "title": "NIK, Email, atau PIN Anda salah",
                "subtitle": ""
            }
            raise GrabLogicException(data)

        total_seconds_failed = 0
        minutes_last_failed = 0

        if user.pin.last_failure_time:
            total_seconds_failed = (timezone.localtime(timezone.now()).replace(tzinfo=None) -
                             timezone.localtime(user.pin.last_failure_time).replace(tzinfo=None)
                             ).total_seconds()
            minutes_last_failed = total_seconds_failed / 60

        pin_settings = get_pin_settings()
        max_wait_time_minutes = pin_settings.max_wait_time_mins
        max_retry_count = pin_settings.max_retry_count
        login_failure_count = pin_settings.login_failure_count  # dict in minutes
        custom_max_retry_count = 3

        email = user.email or user.customer.email

        redis_client = get_redis_client()
        blocked_key = '%s_%s' % ("blocked_account:", email)
        has_blocked_key = redis_client.get(blocked_key)

        if has_blocked_key:
            accumulate_failure_login = int(has_blocked_key)
            acc_max_wait_time_minutes = login_failure_count[str(accumulate_failure_login)]
        else:
            # initialize phase
            accumulate_failure_login = 1
            acc_max_wait_time_minutes = max_wait_time_minutes

        if user.pin.latest_failure_count >= custom_max_retry_count and minutes_last_failed < acc_max_wait_time_minutes:
            if user.pin.latest_failure_count == custom_max_retry_count:
                username = email.split("@")[0]

                # Set a redis key to check if email has available send
                redis_key = '%s_%s' % ("email_has_sended:", email)
                has_sended_email = redis_client.get(redis_key)

                # calculate minutes and seconds
                count_down = acc_max_wait_time_minutes * 60
                total_blocked_seconds = count_down - total_seconds_failed

                # early return email already sended, no need send a email again
                time_message = "{:0>8}".format(str(timedelta(seconds=round(total_blocked_seconds))))\
                    .replace('days', 'hari').replace('day', 'hari')
                already_blocked = "Mohon menunggu akun anda telah terblokir " \
                    "akun akan terbuka secara otomatis selama %s dari sekarang" % time_message

                if has_sended_email:
                    data = {
                        "title": already_blocked,
                        "subtitle": ""
                    }
                    raise GrabLogicException(data)

                unlock_time = user.pin.last_failure_time + datetime.timedelta(minutes=acc_max_wait_time_minutes)
                unlock_time_str = unlock_time.strftime("%H.%M")

                # send email locked pin
                send_email_lock_pin.delay(
                    username, acc_max_wait_time_minutes, max_retry_count, unlock_time_str, email)

                # send email unlocked pin
                send_email_unlock_pin.apply_async((username, email, ), countdown=count_down)

                # Set value if email has sended
                redis_client.set(redis_key, 1, count_down)

                # set blocked accumulative failure login increament
                if not has_blocked_key:
                    redis_client.set(blocked_key, 1, 86_400)  # Expire in 1 Day
                elif int(has_blocked_key) < 3:
                    accumulate_failure_login += 1
                    redis_client.set(blocked_key, accumulate_failure_login, 86_400)  # Expire in 1 Day

            blocked_time_seconds = login_failure_count[str(accumulate_failure_login)] * 60
            time_message = "{:0>8}".format(str(timedelta(seconds=round(blocked_time_seconds))))\
                    .replace('days', 'hari').replace('day', 'hari')
            exception_message = "Akun Anda diblokir sementara selama %s karena salah " \
                                "memasukkan kombinasi KTP / Email / PIN, silahkan coba " \
                                "kembali masuk nanti." % time_message

            data = {
                "title": exception_message,
                "subtitle": ""
            }
            raise GrabLogicException(data)

        if user.pin.latest_failure_count >= custom_max_retry_count and minutes_last_failed > acc_max_wait_time_minutes:
            GrabAuthService._reset_pin_failure(user)

        is_password_correct = user.check_password(pin)

        if not is_password_correct:
            user.pin.last_failure_time = timezone.localtime(timezone.now())
            user.pin.latest_failure_count = user.pin.latest_failure_count + 1
            user.pin.save()

            data = {
                "title": "NIK, Email, atau PIN Anda salah",
                "subtitle": ""
            }
            raise GrabLogicException(data)


        force_logout_action = CustomerAppAction.objects.get_or_none(customer=user.customer,
                                                                    action='force_logout',
                                                                    is_completed=False)
        if force_logout_action:
            force_logout_action.mark_as_completed()
            force_logout_action.save()

        GrabAuthService._reset_pin_failure(user)

        phone_number = user.customer.phone
        is_grab_user = block_users_other_than_grab(user)
        if not is_grab_user:
            data = {
                "title": GrabErrorMessage.NIK_EMAIL_INVALID,
                "subtitle": GrabErrorMessage.USE_VALID_NIK
            }
            raise GrabLogicException(data)
        if phone_number:

            grab_customer_data = GrabCustomerData.objects.get_or_none(
                phone_number=phone_number,
                grab_validation_status=True,
                otp_status=GrabCustomerData.VERIFIED,
                customer__isnull=True
            )

            if grab_customer_data:
                grab_customer_data.update_safely(customer_id=user.customer.id)

            phone_number = format_nexmo_voice_phone_number(phone_number)
        else:
            application = user.customer.application_set.filter(workflow__name=WorkflowConst.JULO_ONE).last()
            if application and application.application_status_id == ApplicationStatusCodes.FORM_CREATED:
                process_application_status_change(
                    application.id, ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                    'Customer Login to grab'
                )
        make_never_expiry_token(user)
        expire_ctl_applications(user)
        response = {
            "user_id": user.id,
            "customer_id": user.customer.id,
            "token": user.auth_expiry_token.key,
            "nik": user.customer.nik,
            "phone_number": phone_number
        }

        redis_client.delete_key(blocked_key)
        return response

    @staticmethod
    def _reset_pin_failure(user):
        user.pin.last_failure_time = timezone.localtime(timezone.now())
        user.pin.latest_failure_count = 0
        user.pin.save()

    @staticmethod
    def register(token, nik, phone_number, pin, j1_bypass=False, email=None):
        try:
            if email is not None and j1_bypass:
                validate_email_registration(email)
            else:
                validate_nik(nik)
            validate_phone_number(phone_number)

            with transaction.atomic():
                user = User(username=nik, email='')
                user.set_password(pin)
                user.save()
                make_never_expiry_token(user)

                customer = Customer.objects.create(
                    user=user,
                    nik=nik,
                    phone=format_nexmo_voice_phone_number(phone_number),
                    appsflyer_device_id=None,
                    advertising_id=None,
                    mother_maiden_name=None,
                    ever_entered_250=False
                )

                customer_pin_service = pin_services.CustomerPinService()
                customer_pin_service.init_customer_pin(user)

                grab_customer_data = GrabCustomerData.objects.get_or_none(
                    phone_number=customer.phone,
                    token=token
                )

                if grab_customer_data:
                    grab_customer_data.update_safely(customer_id=customer.id)
                else:
                    raise GrabLogicException("Token is invalid")

                workflow = Workflow.objects.get_or_none(name=WorkflowConst.GRAB)
                product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.GRAB)
                partner = Partner.objects.get(name=PartnerConstant.GRAB_PARTNER)

                app_version = "5.1.0"
                web_version = "5.1.0"
                application = Application.objects.create(
                    app_version=app_version,
                    web_version=web_version,
                    customer=customer,
                    ktp=nik,
                    workflow=workflow,
                    product_line=product_line,
                    partner=partner,
                    application_number=1,
                    mobile_phone_1=format_nexmo_voice_phone_number(phone_number),
                    company_name=GrabApplicationConstants.COMPANY_NAME_DEFAULT,
                    job_type=GrabApplicationConstants.JOB_TYPE_DEFAULT,
                    job_industry=GrabApplicationConstants.JOB_INDUSTRY_DEFAULT,
                )
                update_customer_data(application)
        except GrabLogicException as gle:
            with transaction.atomic():
                if email is not None and j1_bypass:
                    existing_customer = Customer.objects.filter(email__iexact=email).first()
                else:
                    existing_customer = Customer.objects.filter(nik=nik).first()
                if not existing_customer:
                    raise
                customer = existing_customer
                user = customer.user
                if customer.application_set.filter(workflow__name=WorkflowConst.GRAB):
                    raise GrabLogicException("Existing Grab Application. Please Login")

                if not check_existing_customer_status(customer):
                    raise GrabLogicException("Existing Loan/Application. Cannot Continue.")

                j1_application = customer.application_set.filter(
                    workflow__name=WorkflowConst.JULO_ONE
                ).exists()
                ctl_application = customer.application_set.filter(
                    product_line__product_line_code__in=ProductLineCodes.ctl()
                ).exists()

                # j1_bypass will have value True if user already login and try to reapply
                customer_have_pin = CustomerPin.objects.filter(user=user).exists()
                if (j1_application or ctl_application) and customer_have_pin and not j1_bypass:
                    raise GrabLogicException("J1/CTL Application exist. Please Login")

                if not customer_have_pin:
                    user.set_password(pin)
                    user.save()
                    customer_pin_service = pin_services.CustomerPinService()
                    customer_pin_service.init_customer_pin(user)

                grab_customer_data = GrabCustomerData.objects.get_or_none(
                    phone_number=format_nexmo_voice_phone_number(phone_number),
                    token=token,
                    grab_validation_status=True,
                    otp_status=GrabCustomerData.VERIFIED,
                )

                if grab_customer_data:
                    grab_customer_data.update_safely(customer_id=customer.id)
                else:
                    raise GrabLogicException("Token is invalid")

                make_never_expiry_token(user)

                workflow = Workflow.objects.get_or_none(name=WorkflowConst.GRAB)
                product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.GRAB)
                partner = Partner.objects.get(name=PartnerConstant.GRAB_PARTNER)
                app_version = "5.1.0"
                web_version = "5.1.0"
                application = Application.objects.create(
                    app_version=app_version,
                    web_version=web_version,
                    customer=customer,
                    ktp=customer.nik,
                    email=customer.email,
                    workflow=workflow,
                    product_line=product_line,
                    partner=partner,
                    application_number=1,
                    company_name=GrabApplicationConstants.COMPANY_NAME_DEFAULT,
                    job_type=GrabApplicationConstants.JOB_TYPE_DEFAULT,
                    job_industry=GrabApplicationConstants.JOB_INDUSTRY_DEFAULT,
                    mobile_phone_1=format_nexmo_voice_phone_number(phone_number),
                )
                application.update_safely(workflow=workflow)
                customer.update_safely(phone=phone_number)

        process_application_status_change(
            application.id, ApplicationStatusCodes.FORM_CREATED,
            change_reason='customer_triggered'
        )
        create_application_checklist_async.apply_async(
            (application.id,), queue='grab_global_queue')
        logger.info({
            "action": "register_grab_account",
            "customer_id": str(customer.id),
            "phone_number": str(phone_number),
            "application_id": str(application.id),
            "j1_bypass_flag": str(j1_bypass)
        })

        trigger_application_creation_grab_api.delay(application.id)

        response = {
            "user_id": customer.user.id,
            "customer_id": customer.id,
            "token": str(user.auth_expiry_token)
        }

        return response

    @staticmethod
    def update_customer_phone(customer, grab_customer_data):
        customer_phone = customer.phone
        if customer_phone != grab_customer_data.phone_number:
            customer.phone = format_nexmo_voice_phone_number(grab_customer_data.phone_number)
            customer.save()

    @staticmethod
    def reapply(customer):
        with transaction.atomic():
            last_application = customer.application_set.last()
            if last_application.status not in graveyard_statuses:
                raise GrabLogicException("Application id {} not in "
                                         "graveyard status".format(last_application.id))

            workflow = Workflow.objects.get_or_none(name=WorkflowConst.GRAB)
            product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.GRAB)
            partner = Partner.objects.get(name=PartnerConstant.GRAB_PARTNER)

            application_number = customer.application_set.count()

            app_version = "5.1.0"
            web_version = "5.1.0"
            application = Application.objects.create(
                app_version=app_version,
                web_version=web_version,
                customer=customer,
                ktp=customer.nik,
                email=last_application.email,
                workflow=workflow,
                product_line=product_line,
                partner=partner,
                application_number=int(application_number) + 1,
                company_name=GrabApplicationConstants.COMPANY_NAME_DEFAULT,
                job_type=GrabApplicationConstants.JOB_TYPE_DEFAULT,
                job_industry=GrabApplicationConstants.JOB_INDUSTRY_DEFAULT,
            )

            last_app_images = Image.objects.filter(
                image_type__in=('selfie', 'ktp_self', 'crop_selfie'),
                image_source=last_application.pk,
                image_status=Image.CURRENT
            )

            # copy image from last application
            for last_app_image in last_app_images:
                last_app_image.pk=None
                last_app_image.image_source=application.pk
                last_app_image.save()

            update_customer_data(application)

        grab_customer_data = GrabCustomerData.objects.filter(customer_id=customer.id).last()

        if not grab_customer_data:
            raise GrabLogicException("Grab customer Data {} is missing"
                                        "".format(customer.id))

        GrabAuthService.update_customer_phone(customer, grab_customer_data)
        if not GrabLoanInquiry.objects.filter(
                grab_customer_data_id=grab_customer_data.id,
                udate__gte=timezone.localtime(timezone.now() - timedelta(days=1))).exists():
            raise GrabLogicException("Pengajuan Kamu sudah Kadaluarsa")

        process_application_status_change(
            application.id, ApplicationStatusCodes.FORM_CREATED,
            change_reason='customer_triggered'
        )

        application.refresh_from_db()

        trigger_application_creation_grab_api.delay(application.id)

        create_application_checklist_async.apply_async(
            (application.id,), queue='grab_global_queue')

        return_response = {
            "application":
                {
                    "application_id": application.id,
                    "application_status": application.status,
                    "application_number": application.application_number,
                }
        }
        return return_response

    @staticmethod
    def link_account(phone_number, device, web_browser):

        grab_customer_data = GrabCustomerData.objects.get_or_none(phone_number=phone_number,
                                                                  grab_validation_status=True)
        token = binascii.b2a_hex(os.urandom(128)).decode('ascii')

        response = {"is_linked": False, "token": token}

        if GrabCustomerData.objects.filter(
            phone_number=phone_number,
            grab_validation_status=True,
            customer__isnull=False
        ).exists():
            data = GrabUtils.built_error_message_format(
                title=GrabErrorMessage.LINK_CUSTOMER_EXISTS_MESSAGE
            )
            raise GrabLogicException(data)
        is_valid_user = validate_customer_phone_number(phone_number)
        if not is_valid_user:
            data = GrabUtils.built_error_message_format(
                title=GrabErrorMessage.NIK_EMAIL_INVALID, subtitle=GrabErrorMessage.USE_VALID_NIK
            )
            raise GrabLogicException(data)

        grab_response = None
        if not grab_customer_data:
            try:
                grab_response = GrabClient.check_account_on_grab_side(phone_number=phone_number)
            except Timeout as e:
                default_url = GrabPaths.LINK_GRAB_ACCOUNT
                if e.response:
                    send_grab_api_timeout_alert_slack.delay(
                        response=e.response,
                        uri_path=e.request.url if e.request else default_url,
                        phone_number=phone_number
                    )
                else:
                    send_grab_api_timeout_alert_slack.delay(
                        uri_path=e.request.url if e.request else default_url,
                        phone_number=phone_number,
                        err_message=str(e) if e else None
                    )

            grab_customer_data = GrabCustomerData.objects.filter(phone_number=phone_number).last()
            if not grab_customer_data:
                grab_customer_data = GrabCustomerData()
            grab_customer_data.phone_number = phone_number
            grab_customer_data.device = device
            grab_customer_data.web_browser = web_browser
            if grab_response and grab_response["success"]:
                existing_grab_customer_data = GrabCustomerData.objects.filter(
                    phone_number=phone_number).last()

                if not existing_grab_customer_data:
                    grab_customer_data.grab_validation_status = True
                    grab_customer_data.token = token
                    hashed_phone = GrabUtils.create_user_token(phone_number)
                    grab_customer_data.hashed_phone_number = hashed_phone

                    grab_customer_data.save()
                else:
                    hashed_phone = GrabUtils.create_user_token(phone_number)
                    existing_grab_customer_data.update_safely(grab_validation_status=True,
                                                              token=token,
                                                              device=device,
                                                              web_browser=web_browser,
                                                              hashed_phone_number=hashed_phone,
                                                              otp_status=GrabCustomerData.UNVERIFIED)

                response = {"is_linked": True, "token": token}
            else:
                grab_customer_data.grab_validation_status = False
                grab_customer_data.token = None
                hashed_phone = GrabUtils.create_user_token(phone_number)
                grab_customer_data.hashed_phone_number = hashed_phone
                grab_customer_data.save()
        else:
            hashed_phone = GrabUtils.create_user_token(phone_number)
            grab_customer_data.update_safely(
                token=token,
                hashed_phone_number=hashed_phone,
                otp_status=GrabCustomerData.UNVERIFIED
            )

            response = {"is_linked": True, "token": grab_customer_data.token}

        request_id = int(timezone.localtime(timezone.now()).strftime("%s")) * 1000
        response['request_id'] = request_id

        response["grab_customer_data_id"] = None
        if grab_customer_data:
            response["grab_customer_data_id"] = grab_customer_data.id

        return response

    @staticmethod
    def forgot_password(email):

        if not check_email(email):
            logger.error({
                'status': 'email invalid',
                'email': email
            })

            return

        customer = pin_services.get_customer_by_email(email)
        if not customer:
            logger.error({
                'status': 'customer does not exist',
                'email': email
            })

            return

        if not pin_services.does_user_have_pin(customer.user):
            logger.error({
                'status': 'customer does not have pin',
                'email': email
            })

            return

        process_reset_pin_request(customer)
        return

    @staticmethod
    def confirm_otp(token, otp_token, request_id, phone_number):
        grab_customer_data = GrabCustomerData.objects.get_or_none(phone_number=phone_number,
                                                                  token=token,
                                                                  grab_validation_status=True)

        if grab_customer_data:

            try:
                minutes_last_failed = 0

                if grab_customer_data.otp_last_failure_time:
                    minutes_last_failed = (timezone.localtime(timezone.now()).replace(tzinfo=None) -
                                           timezone.localtime(grab_customer_data.otp_last_failure_time)
                                           .replace(tzinfo=None)).total_seconds() / 60

                (
                    otp_max_request,
                    otp_max_validate,
                    otp_resend_time_sms,
                    wait_time_seconds,
                ) = get_mobile_phone_otp_settings_grab()

                otp_request = get_latest_available_otp_request_grab(
                    [OTPType.SMS, OTPType.MISCALL], phone_number
                )
                if not otp_request or otp_request.is_used:
                    logger.warning(
                        'validate_otp_invalid|grab_customer_data={},otp_token={}'.format(
                            grab_customer_data.id, otp_token
                        )
                    )
                    data = GrabUtils.built_error_message_format(title=GrabErrorMessage.OTP_INACTIVE)
                    raise GrabLogicException(data)

                otp_request.update_safely(retry_validate_count=F('retry_validate_count') + 1)

                if otp_request.retry_validate_count > otp_max_validate:
                    raise GrabLogicException(
                        GrabUtils.built_error_message_format(
                            title=GrabErrorMessage.OTP_CODE_INVALID
                        )
                    )

                check_conditions = (
                    otp_request.otp_token != otp_token,
                    otp_request.request_id != request_id,
                )
                if any(check_conditions):
                    logger.info(
                        'validate_otp_failed|otp_request={}, '
                        'check_results={}, otp_token={}'.format(
                            otp_request.id, check_conditions, otp_token
                        )
                    )
                    raise GrabLogicException(
                        GrabUtils.built_error_message_format(
                            title=GrabErrorMessage.OTP_CODE_INVALID
                        )
                    )

                if not check_otp_request_is_active(otp_request, wait_time_seconds):
                    logger.info('validate_otp_otp_inactive|otp_request={}'.format(otp_request.id))
                    raise GrabLogicException(
                        GrabUtils.built_error_message_format(title=GrabErrorMessage.OTP_INACTIVE)
                    )

                h_otp = pyotp.HOTP(settings.OTP_SECRET_KEY)
                valid_token = h_otp.verify(otp_token, int(otp_request.request_id))

                if otp_request.otp_service_type == OTPType.MISCALL:
                    valid_token = True

                if otp_request.is_active and valid_token:
                    otp_request.is_used = True
                    otp_request.save()

                    grab_customer_data.update_safely(otp_status=GrabCustomerData.VERIFIED)

                    customer = Customer.objects.filter(phone=phone_number)

                    GrabAuthService._reset_otp_failure(grab_customer_data)

                    return {
                        "is_otp_success": True,
                        "is_phone_number_registered": True if customer else False
                    }
                else:
                    grab_customer_data.otp_last_failure_time = timezone.localtime(timezone.now())
                    grab_customer_data.otp_latest_failure_count = grab_customer_data.otp_latest_failure_count + 1
                    grab_customer_data.save()

                    raise GrabLogicException(
                        GrabUtils.built_error_message_format(
                            title=GrabErrorMessage.OTP_CODE_INVALID
                        )
                    )

            except ObjectDoesNotExist:
                grab_customer_data.otp_last_failure_time = timezone.localtime(timezone.now())
                grab_customer_data.otp_latest_failure_count = grab_customer_data.otp_latest_failure_count + 1
                grab_customer_data.save()
                data = GrabUtils.built_error_message_format(title=GrabErrorMessage.OTP_CODE_INVALID)
                raise GrabLogicException(data)
        else:
            data = GrabUtils.built_error_message_format(title=GrabErrorMessage.OTP_CODE_INVALID)
            raise GrabLogicException(data)

    @staticmethod
    def request_otp(phone_number, request_id, token, is_api_request=False):
        default_otp_max_wait_time = 25
        grab_customer_data = GrabCustomerData.objects.get_or_none(phone_number=phone_number,
                                                                  token=token,
                                                                  grab_validation_status=True)
        is_resent_otp = False
        is_otp_active = False

        if grab_customer_data:
            retry_count = 1

            postfix = int(time.time())
            post_fixed_request_id = str(request_id) + str(postfix)
            curr_time = timezone.localtime(timezone.now())

            (
                otp_max_request,
                otp_max_validate,
                otp_resend_time_sms,
                wait_time_seconds,
            ) = get_mobile_phone_otp_settings_grab()

            current_count, start_create_time = get_total_retries_and_start_create_time_grab_otp(
                phone_number, wait_time_seconds
            )

            retry_count += current_count
            existing_otp_request = get_latest_available_otp_request_grab(
                [OTPType.SMS], phone_number
            )
            if retry_count > otp_max_request:
                logger.warning(
                    'exceeded the max request, '
                    'otp_request_id={}, retry_count={}, '
                    'otp_max_request={}'.format(
                        existing_otp_request.id, retry_count, otp_max_request
                    )
                )
                if wait_time_seconds:
                    wait_time_in_minutes = math.ceil(int(wait_time_seconds) // 60)
                else:
                    wait_time_in_minutes = default_otp_max_wait_time
                if not is_api_request:
                    data = GrabUtils.built_error_message_format(
                        subtitle=GrabErrorMessage.OTP_LIMIT_REACHED.format(
                            max_otp_request=otp_max_request, wait_time_minutes=wait_time_in_minutes
                        )
                    )
                else:
                    data = GrabUtils.built_error_message_format(
                        title=GrabErrorMessage.OTP_LIMIT_REACHED.format(
                            max_otp_request=otp_max_request, wait_time_minutes=wait_time_in_minutes
                        )
                    )
                raise GrabLogicException(data)
            if existing_otp_request:
                previous_time = existing_otp_request.cdate
                previous_otp_resend_time = otp_resend_time_sms
                previous_resend_time = timezone.localtime(previous_time) + relativedelta(
                    seconds=previous_otp_resend_time
                )
                is_otp_active = check_otp_request_is_active(
                    existing_otp_request, wait_time_seconds, curr_time
                )
                if is_otp_active:
                    if curr_time < previous_resend_time:
                        logger.info(
                            {
                                'request_time': previous_time,
                                'expired_time': previous_time
                                + relativedelta(seconds=wait_time_seconds),
                                'retry_count': retry_count - 1,
                                'resend_time': previous_resend_time,
                            }
                        )
                        if not is_api_request:
                            data = GrabUtils.built_error_message_format(
                                subtitle=GrabErrorMessage.OTP_RESEND_TIME_INEFFICIENT
                            )
                        else:
                            data = GrabUtils.built_error_message_format(
                                title=GrabErrorMessage.OTP_RESEND_TIME_INEFFICIENT
                            )
                        raise GrabLogicException(data)
                    is_resent_otp = True

            create_new_otp = (
                False if (existing_otp_request and is_otp_active) and not is_resent_otp else True
            )
            if create_new_otp:
                h_otp = pyotp.HOTP(settings.OTP_SECRET_KEY)
                otp = str(h_otp.at(int(post_fixed_request_id)))

                otp_request = OtpRequest.objects.create(
                    request_id=post_fixed_request_id,
                    otp_token=otp,
                    phone_number=phone_number,
                    otp_service_type=OTPType.SMS,
                    action_type=SessionTokenAction.PHONE_REGISTER,
                )
                if not is_resent_otp:
                    GrabAuthService._reset_otp_failure(grab_customer_data)
            else:
                otp = existing_otp_request.otp_token
                post_fixed_request_id = existing_otp_request.request_id
                otp_request = existing_otp_request

            text_message = render_to_string('sms_otp_token.txt', context={
                'otp_token': otp
            })

            send_sms_otp_token.delay(phone_number, text_message, None, otp_request.id)

            return {
                "request_id": post_fixed_request_id
            }

        else:
            if not is_api_request:
                data = GrabUtils.built_error_message_format(
                    subtitle=GrabErrorMessage.OTP_CODE_INVALID
                )
            else:
                data = GrabUtils.built_error_message_format(title=GrabErrorMessage.OTP_CODE_INVALID)
            raise GrabLogicException(data)

    @staticmethod
    def _reset_otp_failure(grab_customer_data):
        grab_customer_data.otp_last_failure_time = timezone.localtime(timezone.now())
        grab_customer_data.otp_latest_failure_count = 0
        grab_customer_data.save()

    @staticmethod
    def change_phonenumber_request_otp(phone_number, request_id, grab_customer):
        grab_customer_data = GrabCustomerData.objects.get_or_none(
            phone_number=format_nexmo_voice_phone_number(grab_customer.phone),
            customer=grab_customer,
            grab_validation_status=True
        )
        if not grab_customer_data:
            raise GrabLogicException("Old Phone Number not registered.")

        postfix = int(time.time())
        post_fixed_request_id = str(request_id) + str(postfix)

        existing_otp = OtpRequest.objects.filter(customer=grab_customer, phone_number=phone_number,
                                                 is_used=False).order_by('id').exclude(
            otp_service_type=OTPType.MISCALL).last()

        create_new_otp = False if existing_otp and existing_otp.is_active else True

        if create_new_otp:
            h_otp = pyotp.HOTP(settings.OTP_SECRET_KEY)
            otp = str(h_otp.at(int(post_fixed_request_id)))

            otp_request = OtpRequest.objects.create(
                customer=grab_customer,
                request_id=post_fixed_request_id,
                otp_token=otp,
                phone_number=phone_number
            )
            GrabAuthService._reset_otp_failure(grab_customer_data)
        else:
            otp = existing_otp.otp_token
            post_fixed_request_id = existing_otp.request_id
            otp_request = existing_otp

        text_message = render_to_string('sms_otp_token.txt', context={
            'otp_token': otp
        })

        send_sms_otp_token.delay(phone_number, text_message, grab_customer.id, otp_request.id)

        return {
            "request_id": post_fixed_request_id
        }

    @staticmethod
    def change_phonenumber_confirm_otp(
            grab_customer, otp_token, request_id, phone_number):
        grab_customer_data = GrabCustomerData.objects.get_or_none(
            phone_number=format_nexmo_voice_phone_number(grab_customer.phone),
            customer=grab_customer,
            grab_validation_status=True
        )
        if not grab_customer_data:
            raise GrabLogicException("Old Phone Number not registered.")

        try:
            minutes_last_failed = 0

            if grab_customer_data.otp_last_failure_time:
                minutes_last_failed = (timezone.localtime(timezone.now()).replace(tzinfo=None) -
                                       timezone.localtime(grab_customer_data.otp_last_failure_time)
                                       .replace(tzinfo=None)).total_seconds() / 60

            pin_settings = get_pin_settings()

            max_wait_time_minutes = pin_settings.max_wait_time_mins
            max_retry_count = pin_settings.max_retry_count

            if grab_customer_data.otp_latest_failure_count >= max_retry_count \
                    and minutes_last_failed < max_wait_time_minutes:
                raise GrabLogicException("Kesempatan Anda telah habis, silahkan coba lagi.")

            if grab_customer_data.otp_latest_failure_count >= 3 and minutes_last_failed > max_wait_time_minutes:
                GrabAuthService._reset_otp_failure(grab_customer_data)

            otp_data = OtpRequest.objects.filter(otp_token=otp_token,
                                                 customer=grab_customer,
                                                 request_id=request_id,
                                                 is_used=False).latest('id')

            h_otp = pyotp.HOTP(settings.OTP_SECRET_KEY)
            valid_token = h_otp.verify(otp_token, int(otp_data.request_id))

            if otp_data.is_active and valid_token:
                otp_data.is_used = True
                otp_data.save()

                grab_customer_data.update_safely(otp_status=GrabCustomerData.VERIFIED)

                GrabAuthService._reset_otp_failure(grab_customer_data)

                return {
                    "is_otp_success": True
                }
            else:
                grab_customer_data.otp_last_failure_time = timezone.localtime(timezone.now())
                grab_customer_data.otp_latest_failure_count = grab_customer_data.otp_latest_failure_count + 1
                grab_customer_data.save()
                raise GrabLogicException('OTP code tidak valid')

        except ObjectDoesNotExist:
            grab_customer_data.otp_last_failure_time = timezone.localtime(timezone.now())
            grab_customer_data.otp_latest_failure_count = grab_customer_data.otp_latest_failure_count + 1
            grab_customer_data.save()
            raise GrabLogicException('OTP code tidak valid')

    @staticmethod
    def request_miscall_otp(phone_number, request_id, token):
        default_otp_max_wait_time = 25
        retry_count = 1
        postfix = int(time.time())

        grab_customer_data = GrabCustomerData.objects.get_or_none(
            phone_number=phone_number, token=token, grab_validation_status=True
        )
        logger.info(
            {
                "task": "GrabAuthServices.request_miscall_otp",
                "action": "starting",
                "phone_number": phone_number,
                "request_id": request_id,
            }
        )
        if not grab_customer_data:
            data = GrabLogicException(
                GrabUtils.built_error_message_format(title=GrabErrorMessage.OTP_INACTIVE)
            )
            raise GrabLogicException(data)

        post_fixed_request_id = str(request_id) + str(postfix)
        (
            otp_max_request,
            otp_max_validate,
            otp_resend_time_sms,
            wait_time_seconds,
        ) = get_mobile_phone_otp_settings_grab()

        current_count, start_create_time = get_total_retries_and_start_create_time_grab_otp(
            phone_number, wait_time_seconds
        )

        retry_count += current_count
        existing_otp_request = get_latest_available_otp_request_grab(
            [OTPType.MISCALL], phone_number
        )
        if existing_otp_request and (retry_count > otp_max_request):
            logger.warning(
                'exceeded the max request, '
                'otp_request_id={}, retry_count={}, '
                'otp_max_request={}'.format(existing_otp_request.id, retry_count, otp_max_request)
            )
            if wait_time_seconds:
                wait_time_in_minutes = math.ceil(int(wait_time_seconds) // 60)
            else:
                wait_time_in_minutes = default_otp_max_wait_time
            raise GrabLogicException(
                GrabUtils.built_error_message_format(
                    title=GrabErrorMessage.OTP_LIMIT_REACHED.format(
                        max_otp_request=otp_max_request, wait_time_minutes=wait_time_in_minutes
                    )
                )
            )
        create_new_otp, is_resent_otp = get_missed_called_otp_creation_active_flags(
            existing_otp_request, otp_resend_time_sms, wait_time_seconds, retry_count
        )
        if create_new_otp:
            otp_request = GrabAuthService.create_new_otp_request_missed_call(
                post_fixed_request_id, phone_number
            )
            if not is_resent_otp:
                GrabAuthService._reset_otp_failure(grab_customer_data)

            mobile_number = format_e164_indo_phone_number(phone_number)

            callback_id = str(uuid.uuid4().hex)
            miscall_otp_data = {
                'customer_id': None,
                'request_id': None,
                'otp_request_status': MisCallOTPStatus.REQUEST,
                'respond_code_vendor': None,
                'call_status_vendor': None,
                'otp_token': None,
                'miscall_number': None,
                'dial_code_telco': None,
                'dial_status_telco': None,
                'price': None,
                'callback_id': callback_id,
            }
            result = {}
            try:
                with transaction.atomic():
                    citcall_client = get_citcall_client()
                    miscall_otp = MisCallOTP.objects.create(**miscall_otp_data)
                    result = citcall_client.request_otp(
                        mobile_number, CitcallRetryGatewayType.INDO, callback_id
                    )
                    if not result:
                        raise CitcallClientError(
                            'miscall otp response error|response={}'.format(result)
                        )
                    otp_token = result.get('token')[-4::]
                    miscall_otp.update_safely(
                        request_id=result['trxid'],
                        otp_request_status=MisCallOTPStatus.PROCESSED,
                        respond_code_vendor=result['rc'],
                        otp_token=otp_token,
                        miscall_number=result.get('token'),
                    )
                    otp_request.update_safely(otp_token=otp_token, miscall_otp=miscall_otp)
                    GrabMisCallOTPTracker.objects.create(
                        otp_request=otp_request, miscall_otp=miscall_otp
                    )
            except (AttributeError, TypeError) as e:
                logger.error('miscall otp response error|response={}'.format(result))
                raise CitcallClientError(str(e))
        else:
            data = GrabUtils.built_error_message_format(
                title=GrabErrorMessage.OTP_RESEND_TIME_INEFFICIENT
            )
            raise GrabLogicException(data)

        return {"request_id": post_fixed_request_id}

    @staticmethod
    def create_new_otp_request_missed_call(post_fixed_request_id, phone_number):
        otp_request = OtpRequest.objects.create(
            request_id=post_fixed_request_id,
            phone_number=phone_number,
            otp_service_type=OTPType.MISCALL,
            action_type=SessionTokenAction.PHONE_REGISTER,
        )
        return otp_request

    @staticmethod
    def validate_email_or_nik(parameter: str):
        """
        parameter can be email or nik
        """
        try:
            if re.match(r'\d{16}', parameter):
                Customer.objects.get(nik=parameter, is_active=True)
            else:
                Customer.objects.get(email__iexact=parameter, is_active=True)
        except ObjectDoesNotExist:
            logger.info(
                {
                    'action': 'validate_email_or_nik',
                    'error': 'User not found',
                    'parameter': parameter,
                }
            )
            success = False
            data = {
                "title": "NIK / Email anda tidak terdaftar",
                "subtitle": "your NIK / Email not registered",
            }
            raise GrabLogicException(data)

        return None

    def get_grab_customer_data(self, customer_id):
        grab_customer_data = GrabCustomerData.objects.get_or_none(customer_id=customer_id)
        return grab_customer_data

    def get_application_data(self, customer_id):
        customer = Customer.objects.get_or_none(id=customer_id)
        if not customer:
            return None
        application = customer.application_set.last()
        return application


class GrabCommonService(object):
    is_crs_validation_error = False

    def is_loan_status_valid(loan: Loan) -> bool:
        loan_status_code = None
        if loan:
            loan_status_code = loan.loan_status.status_code

        if loan_status_code in {
            LoanStatusCodes.INACTIVE,
            LoanStatusCodes.LENDER_APPROVAL,
            LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
            LoanStatusCodes.FUND_DISBURSAL_FAILED
        }:
            return False

        return True

    def is_grab_customer_valid(customer_id):
        is_customer_blocked_for_loan_creation = None
        grab_customer_data = GrabCustomerData.objects.get_or_none(customer_id=customer_id)
        if grab_customer_data:
            is_customer_blocked_for_loan_creation = grab_customer_data.is_customer_blocked_for_loan_creation

        if is_customer_blocked_for_loan_creation:
            return False
        return True

    def is_application_valid(application):
        app_history_190 = application.applicationhistory_set.filter(
            status_new=ApplicationStatusCodes.LOC_APPROVED
        )
        if not app_history_190.exists():
            return False

        time_delay_in_minutes = datetime.timedelta(minutes=TIME_DELAY_IN_MINUTES_190)

        less_than_15_mins = (timezone.localtime(timezone.now()) - app_history_190.last().cdate) \
            < time_delay_in_minutes

        if app_history_190.exists() and less_than_15_mins:
            return False

        return True

    def is_loan_have_valid_log(self, loan: Loan):
        grab_api_logs = GrabAPILog.objects.filter(
            loan_id=loan.id).filter(
            Q(query_params__contains=GrabPaths.LOAN_CREATION) |
            Q(query_params__contains=GrabPaths.DISBURSAL_CREATION) |
            Q(query_params__contains=GrabPaths.CANCEL_LOAN)
        )

        auth_log = grab_api_logs.filter(query_params__contains=GrabPaths.LOAN_CREATION)
        crs_failed_validation_service = CRSFailedValidationService()
        grab_feature_setting_crs_flow_blocker = (
            crs_failed_validation_service.get_grab_feature_setting_crs_flow_blocker()
        )
        if grab_feature_setting_crs_flow_blocker:
            crs_failed_log_exists = crs_failed_validation_service.check_crs_failed_exists(
                auth_log, loan
            )
            if crs_failed_log_exists:
                self.is_crs_validation_error = True
                return False

        success_auth_log = auth_log.filter(http_status_code=https_status_codes.HTTP_200_OK).exists()

        capture_log = grab_api_logs.filter(
            Q(query_params__contains=GrabPaths.DISBURSAL_CREATION),
            http_status_code=https_status_codes.HTTP_200_OK
        ).exists()

        cancel_log = grab_api_logs.filter(
            Q(query_params__contains=GrabPaths.CANCEL_LOAN),
            http_status_code=https_status_codes.HTTP_200_OK
        ).exists()

        loan_status_code = loan.loan_status.status_code

        if loan_status_code in {
            LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            LoanStatusCodes.SPHP_EXPIRED,
            LoanStatusCodes.LENDER_REJECT
        }:
            if success_auth_log:
                if cancel_log:
                    return True
                else:
                    return False
            else:
                return True

        if loan_status_code > LoanStatusCodes.FUND_DISBURSAL_ONGOING and \
            loan_status_code < LoanStatusCodes.HALT:
            return success_auth_log and (capture_log or cancel_log)

        return True

    def should_show_ajukan_pinjaman_lagi_info_card(
        self, customer_id: int, loan: Loan, application: Application
    ) -> bool:
        if FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
            is_active=True
        ).exists():
            return False

        is_grab_cust_valid = GrabCommonService.is_grab_customer_valid(customer_id)
        is_application_valid = GrabCommonService.is_application_valid(application)

        # if application have loan before, check the loan
        is_loan_valid = True
        is_loan_have_valid_log = True
        if loan:
            is_loan_valid = GrabCommonService.is_loan_status_valid(loan)
            is_loan_have_valid_log = self.is_loan_have_valid_log(loan)

        if is_loan_valid and is_grab_cust_valid and is_application_valid and \
            is_loan_have_valid_log:
            return True

        return False

    def get_ajukan_pinjaman_lagi_info_card(self):
        return [
            StreamlinedCommunication.objects.filter(
                communication_platform=CommunicationPlatform.INFO_CARD,
                status_code_id=ApplicationStatusCodes.LOC_APPROVED,
                extra_conditions=CardProperty.GRAB_AJUKAN_PINJAMAN_LAGI,
                is_active=True,
            ).last()
        ]

    def get_belum_bisa_lanjutkan_aplikasi_info_card(self):
        return [
            StreamlinedCommunication.objects.filter(
                communication_platform=CommunicationPlatform.INFO_CARD,
                status_code_id=ApplicationStatusCodes.LOC_APPROVED,
                extra_conditions=CardProperty.GRAB_BELUM_BISA_MELANJUTKAN_APLIKASI,
                is_active=True,
            ).last()
        ]

    @staticmethod
    def get_info_card(customer):

        data = dict()
        application_set = customer.application_set.regular_not_deletes()
        if application_set.filter(workflow__name=WorkflowConst.GRAB).exists():
            application = application_set.filter(workflow__name=WorkflowConst.GRAB).last()
        else:
            application = application_set.last()
        if not application:
            raise GrabLogicException("Aplikasi tidak ditemukan")

        card_due_date = '-'
        card_due_amount = '-'
        card_cashback_amount = '-'
        card_cashback_multiplier = '-'
        card_dpd = '-'
        loan_amount = ''
        loan_tenure = ''
        loan_sphp_exp_date_day = 0
        loan = None if not hasattr(application, 'loan') else application.loan
        if application.is_grab():
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
        bottom_sheets = []
        if not application.is_grab():
            if check_existing_customer_status(customer):
                extra_condition = CardProperty.GRAB_INFO_CARD_JULO_CUSTOMER
            else:
                extra_condition = CardProperty.GRAB_INFO_CARD_JULO_CUSTOMER_FAILED
            info_cards = list(StreamlinedCommunication.objects.filter(
                communication_platform=CommunicationPlatform.INFO_CARD,
                extra_conditions=extra_condition,
                is_active=True
            ).order_by('message__info_card_property__card_order_number'))
        else:
            if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL_EXPIRED:
                if not check_grab_reapply_eligibility(application.id):
                    extra_condition = CardProperty.GRAB_INFO_CARD_BAD_HISTORY
                else:
                    extra_condition = CardProperty.GRAB_INFO_CARD
                info_cards = list(StreamlinedCommunication.objects.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=extra_condition,
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))

            elif application.application_status_id == ApplicationStatusCodes.APPLICATION_DENIED:
                if check_grab_reapply_eligibility(application.id) and \
                        can_reapply_application_grab(application.customer):
                    application_history = application.applicationhistory_set.filter(
                        status_new=ApplicationStatusCodes.APPLICATION_DENIED
                    ).last()

                    extra_condition = CardProperty.GRAB_INFO_CARD_REAPPLY

                    if application_history:
                        if 'bank account not under own name' in application_history.\
                            change_reason.strip():
                            extra_condition = CardProperty.GRAB_BANK_ACCOUNT_REJECTED
                        elif 'grab_phone_number_check' in application_history.\
                            change_reason.lower().strip():
                            extra_condition = CardProperty.GRAB_PHONE_NUMBER_CHECK_FAILED
                else:
                    extra_condition = CardProperty.GRAB_INFO_CARD

                info_cards = list(StreamlinedCommunication.objects.filter(
                    communication_platform=CommunicationPlatform.INFO_CARD,
                    status_code_id=application.application_status_id,
                    extra_conditions=extra_condition,
                    is_active=True
                ).order_by('message__info_card_property__card_order_number'))

            elif application.application_status_id == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:
                info_cards = get_info_cards_privy(application.id)

            elif application.application_status_id == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
                application_history = application.applicationhistory_set.filter(
                    status_new=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
                ).last()
                if application_history and \
                        GRAB_FAILED_3MAX_CREDITORS_CHECK in application_history. \
                        change_reason.strip():
                    if loan:
                        loan_amount = display_rupiah(loan.loan_amount)
                        loan_tenure = str(loan.loan_duration) + ' hari'
                    extra_condition = CardProperty.GRAB_FAILED_3MAX_CREDITORS_CHECK
                    info_cards = list(StreamlinedCommunication.objects.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=extra_condition,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))
                    bottom_sheets = list(StreamlinedCommunication.objects.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=application.application_status_id,
                        extra_conditions=CardProperty.GRAB_FAILED_3MAX_CREDITORS_BOTTOM_SHEET,
                        is_active=True
                    ).order_by('message__info_card_property__card_order_number'))


        if len(info_cards) == 0:
            info_cards = list(StreamlinedCommunication.objects.filter(
                communication_platform=CommunicationPlatform.INFO_CARD,
                status_code_id=application.application_status_id,
                extra_conditions=CardProperty.GRAB_INFO_CARD,
                is_active=True
            ).order_by('message__info_card_property__card_order_number'))

        if application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
            if application.is_grab():
                loan = application.account.loan_set.last()

                if loan:
                    extra_conditions = CardProperty.GRAB_INFO_CARD
                    loan_amount = display_rupiah(loan.loan_amount)
                    loan_tenure = str(loan.loan_duration) + ' hari'
                    if loan.sphp_exp_date:
                        loan_sphp_exp_date_day = (
                            loan.sphp_exp_date -  datetime.datetime.now().date()
                        ).days
                        if loan_sphp_exp_date_day < 0:
                            loan_sphp_exp_date_day = 0

                    available_context.update(
                        {"loan_sphp_exp_date_day": loan_sphp_exp_date_day}
                    )

                    if loan.status in {LoanStatusCodes.INACTIVE, LoanStatusCodes.LENDER_REJECT}:
                        auth_status_mapping = {
                            GrabAuthStatus.FAILED_4002: CardProperty.GRAB_INFO_CARD_AUTH_FAILED_4002,
                            GrabAuthStatus.FAILED: CardProperty.GRAB_INFO_CARD_AUTH_FAILED,
                            GrabAuthStatus.SUCCESS: CardProperty.GRAB_INFO_CARD_AUTH_SUCCESS
                        }
                        auth_status = check_grab_auth_status(loan.id)
                        if auth_status not in auth_status_mapping:
                            extra_conditions = CardProperty.GRAB_INFO_CARD_AUTH_PENDING
                        else:
                            extra_conditions = auth_status_mapping[auth_status]
                    loan_cards_qs = StreamlinedCommunication.objects.filter(
                        communication_platform=CommunicationPlatform.INFO_CARD,
                        status_code_id=loan.status,
                        extra_conditions=extra_conditions,
                        is_active=True)

                    loan_cards = list(
                        loan_cards_qs.order_by('message__info_card_property__card_order_number'))
                    info_cards = loan_cards + info_cards
                    loan = application.account.loan_set.last()

                common_service = GrabCommonService()
                if common_service.should_show_ajukan_pinjaman_lagi_info_card(
                    customer_id=customer.id, loan=loan, application=application
                ):
                    ajukan_pinjaman_info_card = common_service.get_ajukan_pinjaman_lagi_info_card()
                    info_cards = ajukan_pinjaman_info_card + info_cards
                elif common_service.is_crs_validation_error:
                    belum_bisa_lanjutkan_aplikasi_info_card = (
                        common_service.get_belum_bisa_lanjutkan_aplikasi_info_card()
                    )
                    info_cards = belum_bisa_lanjutkan_aplikasi_info_card + info_cards

        processed_info_cards = []
        for info_card in info_cards:
            processed_info_cards.append(
                format_info_card_for_android(info_card, available_context)
            )
        processed_bottom_sheets = []
        for bottom_sheet in bottom_sheets:
            processed_bottom_sheets.append(
                format_bottom_sheet_for_grab(bottom_sheet, available_context)
            )
        data['cards'] = processed_info_cards
        data['bottom_sheets'] = processed_bottom_sheets
        data['application_status'] = application.status
        data['application_id'] = application.id
        data['loan_amount'] = loan_amount
        data['loan_tenure'] = loan_tenure
        data['loan_sphp_exp_date_day'] = loan_sphp_exp_date_day

        return data

    @staticmethod
    def get_homepage_data(customer, user):
        accounts = Account.objects.filter(customer=customer)

        grab_response = GrabClient.get_loan_offer(phone_number=customer.phone,
                                                  customer_id=customer.id)

        account_result = []
        for account in accounts:
            account_result.append({
                "account_name": account.account_lookup.name,
                "account_set_limit": account.get_account_limit.set_limit,
                "account_card_image": account.account_lookup.image_url if hasattr(account.account_lookup, "image_url")
                else None
            })

        if len(account_result) == 0:
            account_result.append({
                "account_name": "Grab",
                "account_set_limit": 0,
                "account_card_image": ""
            })

        is_eligible_to_apply_loan_from_julo = False
        is_eligible_to_apply_loan_from_grab = True \
            if grab_response["data"] and grab_response["data"]["loan_offers"] and \
               len(grab_response["data"]["loan_offers"]) > 0 \
            else False

        response = {
            "customer_name": customer.fullname,
            "is_eligible_to_apply_loan": is_eligible_to_apply_loan_from_julo and is_eligible_to_apply_loan_from_grab,
            "info_card": GrabCommonService._get_info_card(user),
            "accounts": account_result
        }

        return response

    @staticmethod
    def get_bank_check_data(customer, bank_name, bank_account_number, application_id=None):

        grab_customer_data = GrabCustomerData.objects.get_or_none(
            customer=customer,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True
        )
        if not grab_customer_data:
            logger.info(
                {
                    "action": "get_bank_check_data",
                    "error_message": GrabUtils.create_error_message(
                        GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                        GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE,
                    ),
                }
            )
            raise GrabLogicException(GrabErrorMessage.NO_REKENING_NOT_CONFIRMED)

        phone_number = grab_customer_data.phone_number

        bank = Bank.objects.filter(
            bank_name=bank_name
        ).last()
        if not bank:
            logger.info(
                {
                    "action": "get_bank_check_data",
                    "error_message": GrabUtils.create_error_message(
                        GrabErrorCodes.GAX_ERROR_CODE.format('2'),
                        GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE,
                    ),
                }
            )
            raise GrabLogicException(GrabErrorMessage.NO_REKENING_NOT_CONFIRMED)

        swift_bank_code = bank.swift_bank_code

        response = GrabClient.get_pre_disbursal_check(
            phone_number=phone_number,
            bank_code=swift_bank_code,
            bank_account_number=bank_account_number,
            customer_id=customer.id,
            application_id=application_id
        )
        response_data = json.loads(response.content)

        if 'data' not in response_data:
            logger.info(
                {
                    "action": "get_bank_check_data",
                    "error_message": GrabUtils.create_error_message(
                        GrabErrorCodes.GAX_ERROR_CODE.format('4'),
                        GrabErrorMessage.BANK_VALIDATION_PRE_DISBURSAL_CHECK_ERROR_MESSAGE,
                    ),
                }
            )
            raise GrabLogicException(GrabErrorMessage.NO_REKENING_NOT_CONFIRMED)

        if response_data['data']['code']:
            logger.info(
                {
                    "action": "get_bank_check_data",
                    "error_message": GrabUtils.create_error_message(
                        GrabErrorCodes.GAX_ERROR_CODE.format('5'),
                        GrabErrorMessage.BANK_VALIDATION_PRE_DISBURSAL_CHECK_ERROR_MESSAGE,
                    ),
                }
            )
            raise GrabLogicException(GrabErrorMessage.NO_REKENING_NOT_CONFIRMED)

        if not application_id:
            application = customer.application_set.filter(
                workflow__name=WorkflowConst.GRAB).last()
        else:
            application = Application.objects.filter(pk=application_id).last()
        if not application:
            logger.info(
                {
                    "action": "get_bank_check_data",
                    "error_message": GrabUtils.create_error_message(
                        GrabErrorCodes.GAX_ERROR_CODE.format('3'),
                        GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE,
                    ),
                }
            )
            raise GrabLogicException(GrabErrorMessage.NO_REKENING_NOT_CONFIRMED)
        update_loan_status_for_grab_invalid_bank_account(application.id)

    @staticmethod
    def get_dropdown_data(page):
        drop_down_data = {
            "banks": DropDownData(DropDownData.BANK).select_data(),
            "loan_purposes": LoanPurpose.objects.all().values_list('purpose', flat=True),
            "kin_relationships": [x[0] for x in Application().KIN_RELATIONSHIP_CHOICES],
            "last_educations": [x[0] for x in Application().LAST_EDUCATION_CHOICES],
            "marital_statuses": [x[0] for x in Application().MARITAL_STATUS_CHOICES]
        }

        dropdown_page = {
            '1': ['marital_statuses', 'last_educations'],
            '2': ['kin_relationships'],
            '3': ['banks', 'loan_purposes']
        }

        response = {}
        if page in dropdown_page:
            for param in dropdown_page[page]:
                response[param] = drop_down_data[param]
        else:
            raise GrabLogicException("Invalid Page")

        return response

    @staticmethod
    def get_cropped_image(upload, application_id):
        crop_selfie, cropped_file = GrabUtils.generate_crop_selfie(upload)
        cropped_upload = InMemoryUploadedFile(file=cropped_file,
                                              field_name='file',
                                              name=upload.name, content_type=upload.content_type,
                                              size=crop_selfie.tell, content_type_extra=upload.content_type_extra,
                                              charset=None)
        cropped_image = Image.objects.create(image_type='crop_selfie', image_source=application_id)
        cropped_image.image.save(cropped_image.full_image_name(cropped_upload.name), cropped_upload)
        process_image_upload(cropped_image)
        cropped_image.refresh_from_db()
        return cropped_image

    @staticmethod
    def upload(image_type, upload, customer):

        if image_type in GRAB_IMAGE_TYPES:
            application = customer.application_set.last()

            if upload:
                image = Image.objects.create(image_type=image_type, image_source=application.id)
                image.image.save(image.full_image_name(upload.name), upload)
                process_image_upload(image)
                image.refresh_from_db()
                if image_type == 'selfie':
                    cropped_image = GrabCommonService.get_cropped_image(upload, application.id)
                response = {
                    "url": settings.OSS_ENDPOINT + "/" + image.url,
                    "image_id": image.id,
                    "image_url": image.image_url
                }
                return response
            else:
                raise GrabLogicException("file not defined")
        else:
            raise GrabLogicException("Not valid image type")

    @staticmethod
    def get_grab_feature_setting():
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
            is_active=True
        )
        return_dict = dict()
        return_dict['grab_customer_registeration'] = False
        if feature_setting:
            return_dict['grab_customer_registeration'] = True
        return return_dict

    @staticmethod
    def get_grab_promo_code_details(token, data):
        grab_customer_data = GrabCustomerData.objects.get_or_none(
            phone_number=data.get("phone_number"),
            grab_validation_status=True,
            token=token,
            otp_status=GrabCustomerData.VERIFIED,
        )
        if not grab_customer_data:
            raise GrabLogicException("You are not eligible for getting promo code.")

        today = timezone.localtime(timezone.now()).date()
        promo_code = GrabPromoCode.objects.filter(
            promo_code=data.get("promo_code"), active_date__lte=today, expire_date__gte=today
        ).last()
        return_dict = dict()
        return_dict['is_valid_promo_code'] = False
        return_dict['message'] = GrabErrorMessage.PROMO_CODE_INVALID
        return_dict['title'] = ''
        return_dict['description'] = ''
        if promo_code and promo_code.rule:
            customer_segment = GrabCommonService().get_customer_promo_segment(
                grab_customer_data.customer_id
            )
            if customer_segment in promo_code.rule:
                return_dict['is_valid_promo_code'] = True
                return_dict['message'] = GrabErrorMessage.PROMO_CODE_VERIFIED_SUCCESS
                return_dict['title'] = promo_code.title
                return_dict['description'] = promo_code.description
        return return_dict

    @staticmethod
    def get_customer_promo_segment(customer_id: int) -> int:
        customer_segment = GrabPromoCode.NEW_USER
        active_loans = Loan.objects.filter(
            customer_id=customer_id,
            account__account_lookup__workflow__name=WorkflowConst.GRAB,
            loan_status__gte=LoanStatusCodes.CURRENT,
            loan_status__lte=LoanStatusCodes.PAID_OFF,
        )
        if active_loans:
            customer_segment = GrabPromoCode.EXISTING_USER_WITH_OUTSTANDING
            customer_loans_with_outstanding_exist = active_loans.filter(
                loan_status__gte=LoanStatusCodes.CURRENT, loan_status__lt=LoanStatusCodes.PAID_OFF
            ).exists()
            customer_loans_without_outstanding_exist = active_loans.filter(
                loan_status=LoanStatusCodes.PAID_OFF
            ).exists()
            if (
                not customer_loans_with_outstanding_exist
                and customer_loans_without_outstanding_exist
            ):
                customer_segment = GrabPromoCode.EXISTING_USER_WITHOUT_OUTSTANDING
        return customer_segment


class GrabApplicationService(object):
    latest_application_data = None
    last_failed_application = None
    current_step = 0

    @staticmethod
    def _validate_fields(application):
        form = GrabApplicationForm(instance=application)

        missing_fields = set(GRAB_APPLICATION_FIELDS).difference(tuple(form.changed_data))

        for image_type in GRAB_IMAGE_TYPES:
            image = Image.objects.filter(image_source=application.id, image_type=image_type)

            if not image:
                missing_fields.add(image_type)

        return False if missing_fields else True, missing_fields if missing_fields else None

    @staticmethod
    def get_pre_loan_response(customer, application=None):
        grab_loan_data = GrabLoanData.objects.filter(
            grab_loan_inquiry__grab_customer_data__customer=customer
        ).order_by('-cdate').first()

        if grab_loan_data:
            loan_amount = grab_loan_data.selected_amount
            interest_rate = grab_loan_data.selected_interest
            admin_fee = grab_loan_data.selected_fee
            loan_duration = grab_loan_data.selected_tenure

            disbursed_amount = loan_amount - admin_fee
            daily_repayment_amount = get_daily_repayment_amount(
                loan_amount, loan_duration, interest_rate)
            pre_loan_response = {
                "loan": {
                    "amount": loan_amount,
                    "fee": admin_fee,
                    "disbursed": disbursed_amount,
                },
                "repayment": {
                    "amount": daily_repayment_amount,
                    "tenure": loan_duration,
                    "interest_rate": interest_rate
                }
            }

            if application:
                pre_loan_response.get("loan")[
                    "disbursed_to"] = application.bank_name + " a.n. " + application.name_in_bank
            return pre_loan_response
        else:
            raise GrabLogicException('Grab loan data does not exist')

    @staticmethod
    def submit_grab_application(customer, validated_data, data, version=1):
        with transaction.atomic():
            application = customer.application_set.last()
            if application.application_status_id >= ApplicationStatusCodes.FORM_PARTIAL:
                if version == 1:
                    pre_loan = GrabApplicationService.get_pre_loan_response(customer, application)
                    response = {
                        "is_grab_application_saved": False,
                        "application_id": application.id,
                        "is_submitted": False,
                        "missing_fields": [],
                        "pre_loan_data": pre_loan
                    }
                    return response
                elif version == 2:
                    raise GrabApiException("Invalid application state")

            validate_email(validated_data["email"], customer)
            validate_email_application(validated_data["email"], customer)
            customer.update_safely(email=validated_data["email"])
            user = customer.user
            user.email = validated_data["email"]
            user.save(update_fields=["email"])

            workflow = Workflow.objects.get_or_none(name=WorkflowConst.GRAB)
            product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.GRAB)
            partner = Partner.objects.get(name=PartnerConstant.GRAB_PARTNER)

            validated_data["name_in_bank"] = validated_data["fullname"]
            if validated_data.get("mobile_phone_1"):
                validated_data["mobile_phone_1"] = format_nexmo_voice_phone_number(
                    validated_data["mobile_phone_1"])
            application.update_safely(
                workflow=workflow,
                product_line=product_line,
                partner=partner,
                **validated_data)

            for image_type in GRAB_IMAGE_TYPES:
                upload = data.get(image_type)

                if upload:
                    image = Image.objects.create(image_type=image_type, image_source=application.id)
                    image.image.save(image.full_image_name(upload.name), upload)
                    upload_image(image.id)

        if application.application_status.status_code < ApplicationStatusCodes.FORM_PARTIAL:
            process_application_status_change(
                application.id, ApplicationStatusCodes.FORM_PARTIAL,  # 105
                change_reason='customer_triggered')
        if validated_data.get('referral_code') and validated_data.get('referral_code') != '':
            update_grab_referral_code(application, validated_data['referral_code'])

        is_submitted, missing_fields = GrabApplicationService._validate_fields(application)
        pre_loan = GrabApplicationService.get_pre_loan_response(customer, application)

        response = {
            "is_grab_application_saved": True,
            "application_id": application.id,
            "is_submitted": is_submitted,
            "missing_fields": missing_fields,
            "pre_loan_data": pre_loan
        }

        return response

    @staticmethod
    def update_grab_application(customer, validated_data, data, step):
        with transaction.atomic():
            application = customer.application_set.last()
            step = int(step)
            if application.application_status_id >= ApplicationStatusCodes.FORM_PARTIAL:
                raise GrabApiException("Invalid application state")

            if step not in list(range(1, 4)):
                raise GrabLogicException('Invalid Page Number')

            if "email" in validated_data:
                validate_email(
                    validated_data["email"], customer, raise_validation_error=True)
                validate_email_application(
                    validated_data["email"], customer, raise_validation_error=True)
                customer.update_safely(email=validated_data["email"])
                user = customer.user
                user.email = validated_data["email"]
                user.save(update_fields=["email"])

            workflow = Workflow.objects.get_or_none(name=WorkflowConst.GRAB)
            product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.GRAB)
            partner = Partner.objects.get(name=PartnerConstant.GRAB_PARTNER)
            if "fullname" in validated_data:
                validated_data["name_in_bank"] = validated_data["fullname"]
            if "secondary_phone_number" in data and data.get("secondary_phone_number") == "":
                validated_data["mobile_phone_2"] = data.get("secondary_phone_number")
            if "referral_code" in data and data.get("referral_code") == "":
                validated_data["referral_code"] = data.get("referral_code")
            if validated_data.get("mobile_phone_1"):
                validated_data["mobile_phone_1"] = format_nexmo_voice_phone_number(
                    validated_data["mobile_phone_1"])
            application.update_safely(
                workflow=workflow,
                product_line=product_line,
                partner=partner,
                **validated_data)

        if validated_data.get('referral_code') and validated_data.get('referral_code') != '':
            update_grab_referral_code(application, validated_data['referral_code'])

        is_submitted, missing_fields = GrabApplicationService._validate_fields(application)
        response = {
            "is_allowed_application": True,
            "application_id": application.id
        }

        return response

    @staticmethod
    def update_application_information(request, application):
        with transaction.atomic():
            for image_type in GRAB_IMAGE_TYPES:
                upload = request.data.get(image_type)
                if upload:
                    image, created = Image.objects.get_or_create(image_type=image_type, image_source=application.id)
                    image.image.save(image.full_image_name(upload.name), upload)
                    upload_image.apply_async((image.id,), countdown=3)

        is_submitted, missing_fields = GrabApplicationService.validate_fields(application)

        response = {
            "is_application_updated": True,
            "application_id": application.id,
            "is_submitted": is_submitted,
            "missing_fields": missing_fields
        }

        return response

    @staticmethod
    def get_application_review(customer):
        application = customer.application_set.last()

        if application:
            application_serializer = GrabApplicationReviewSerializer(application)

            return application_serializer.data
        else:
            raise GrabApiException("Application for the customer is not found")

    @staticmethod
    def get_grab_registeration_reapply_status(customer):
        return_dict = {
            "j1_loan_selected": False,
            "grab_customer_exist": False,
            "grab_customer_token": None
        }
        if not customer.phone:
            return return_dict
        grab_customer_data = GrabCustomerData.objects.filter(
            phone_number=format_nexmo_voice_phone_number(customer.phone),
            grab_validation_status=True,
            otp_status=GrabCustomerData.VERIFIED
        ).filter(Q(customer__isnull=True) | Q(customer=customer)).last()
        if grab_customer_data:
            return_dict['grab_customer_exist'] = True
            return_dict['grab_customer_token'] = grab_customer_data.token
            grab_loan_inquiry = grab_customer_data.grabloaninquiry_set.last()
            if grab_loan_inquiry:
                grab_loan_data = grab_loan_inquiry.grabloandata_set.last()
                if grab_loan_data:
                    return_dict["j1_loan_selected"] = True
        return return_dict

    @staticmethod
    def get_grab_loan_transaction_detail(customer):
        transaction_detail_data = GrabApplicationService.get_pre_loan_response(customer)

        response = {
            "data": transaction_detail_data
        }

        return response

    def get_latest_application(self, customer):
        is_reapply_application = False

        latest_application = customer.application_set.filter(
            product_line__product_line_code__in=ProductLineCodes.grab()).last()
        if not latest_application:
            raise GrabLogicException('No Valid Grab application')

        logger.info({
            "view": "get_application_details_long_form",
            "application_id": latest_application.id,
            "status": "beginning request"
        })

        last_failed_application_serializer = None
        application_count = customer.application_set.count()
        if application_count > 1 and latest_application.status == ApplicationStatusCodes.FORM_CREATED:
            last_failed_application = customer.application_set.filter(
                application_status_id__in=list(graveyard_statuses)).order_by('cdate').last()
            self.last_failed_application = last_failed_application

            if last_failed_application.status in graveyard_statuses and \
                    latest_application.status == ApplicationStatusCodes.FORM_CREATED:
                last_failed_application_serializer = GrabApplicationPopulateReapplySerializer(
                    last_failed_application, context={"latest_app_id": latest_application.id})
                is_reapply_application = True

        self.latest_application_data = {
            'last_failed_application_serializer': last_failed_application_serializer,
            'is_reapply_application': is_reapply_application,
            'latest_application': latest_application
        }
        return self.latest_application_data

    def get_application_details_long_form(self, customer, step: int):
        step = int(step)

        if not self.latest_application_data:
            raise GrabLogicException('No Valid Grab application')

        latest_application = self.latest_application_data.get('latest_application')
        last_failed_application_serializer = self.latest_application_data.get(
            'last_failed_application_serializer'
        )
        is_reapply_application = self.latest_application_data.get('is_reapply_application')

        serializer = GrabApplicationPopulateSerializer(latest_application)
        validated_application = dict(serializer.data)

        if is_reapply_application:
            validated_failed_application = dict(last_failed_application_serializer.data)

        final_application_data = validated_application.copy()
        for item, value in validated_application.items():
            if value:
                continue
            if value is None or value == '':
                del final_application_data[item]
                if last_failed_application_serializer and validated_failed_application[item]:
                    final_application_data[item] = validated_failed_application[item]

        # Find the last Page Number Which are Valid
        final_updated_page_number = 1
        if self.current_step > 1:
            final_updated_page_number = self.current_step

        if not is_reapply_application:
            for page_number in list(range(1, 5)):
                final_updated_page_number = page_number
                is_last_updated_page_found = False
                fields_per_page = GrabApplicationService.get_all_fields_wrt_page_num(
                    page_number)
                for field in fields_per_page:
                    if field in {GrabApplicationPageNumberMapping.SELFIE_IMAGE,
                                 GrabApplicationPageNumberMapping.KTP_IMAGE,
                                 GrabApplicationPageNumberMapping.MOBILE_PHONE2,
                                 GrabApplicationPageNumberMapping.REFERRAL_CODE}:
                        continue
                    if field not in list(map(
                            GrabApplicationPageNumberMapping.mapping_application_to_fe_variable_name,
                            final_application_data.keys())):
                        is_last_updated_page_found = True
                        break
                if is_last_updated_page_found:
                    break
        # Check if page number is valid
        if step not in list(range(1, 5)):
            raise GrabLogicException('Invalid Page Number Entered')

        # Share the relevant Page Details(Fields) with FE
        fields_per_page = GrabApplicationService.get_all_fields_wrt_page_num(
            step)
        items_to_be_deleted = []

        for item in final_application_data.keys():
            updated_field = item
            if updated_field not in list(
                    map(GrabApplicationPageNumberMapping.mapping_fe_variable_name_to_application,
                        fields_per_page)):
                items_to_be_deleted.append(item)
        for item_to_be_deleted in items_to_be_deleted:
            del final_application_data[item_to_be_deleted]

        # Update ITEMS from Application table to FE Requested format
        for item, value in final_application_data.copy().items():
            updated_item = GrabApplicationPageNumberMapping.mapping_application_to_fe_variable_name(item)
            if updated_item not in final_application_data:
                final_application_data[updated_item] = final_application_data[item]
                del final_application_data[item]

        logger.info({
            "view": "get_application_details_long_form",
            "application_id": latest_application.id,
            "status": "ending request",
            "last_updated_page": final_updated_page_number
        })
        if final_application_data.get(GrabApplicationPageNumberMapping.MOBILE_PHONE1):
            final_application_data[
                GrabApplicationPageNumberMapping.MOBILE_PHONE1] = format_mobile_phone(customer.phone)
        final_application_data['current_step'] = final_updated_page_number

        return final_application_data

    @staticmethod
    def get_all_fields_wrt_page_num(page_number: int):
        page_fields = {}
        if page_number == 1:
            page_fields = GrabApplicationPageNumberMapping.PAGE_1
        elif page_number == 2:
            page_fields = GrabApplicationPageNumberMapping.PAGE_2
        elif page_number == 3:
            page_fields = GrabApplicationPageNumberMapping.PAGE_3
        elif page_number == 4:
            page_fields = GrabApplicationPageNumberMapping.PAGE_1 | GrabApplicationPageNumberMapping.PAGE_2 | \
                          GrabApplicationPageNumberMapping.PAGE_3
        return page_fields

    @staticmethod
    def get_bank_rejection_reason():
        for mapping_status in grab_rejection_mapping_statuses:
            if 'bank account not under own name' in mapping_status.additional_check:
                return mapping_status
        return None

    def is_last_failed_application_valid(self):
        if not self.last_failed_application:
            return False

        is_status_135 = self.last_failed_application.application_status.status_code == \
            ApplicationStatusCodes.APPLICATION_DENIED

        app_histroy = ApplicationHistory.objects.filter(
            application=self.last_failed_application).last()

        is_reason_because_of_bank = self.get_bank_rejection_reason().mapping_status.lower() in \
            app_histroy.change_reason.lower()

        if False in {is_status_135, is_reason_because_of_bank}:
            return False

        return True

    def get_missing_data(self, step):
        if step == 1:
            return {
                'ktp': self.last_failed_application.ktp,
                'marital_status': self.last_failed_application.marital_status
            }

        if step == 2:
            return {
                'close_kin_mobile_phone' :self.last_failed_application.close_kin_mobile_phone,
                'close_kin_name': self.last_failed_application.close_kin_name,
                'kin_relationship': self.last_failed_application.kin_relationship
            }

        if step == 3:
            return {
                'bank_account_number_verified': True,
                'fullname': self.last_failed_application.fullname,
                'referral_code': self.last_failed_application.referral_code
            }

        return None

    def save_failed_latest_app_to_new_app(self, customer):
        is_failed_app_valid = self.is_last_failed_application_valid()
        if not is_failed_app_valid:
            return

        self.current_step = 1
        for step in range(1, 4):
            data = self.get_application_details_long_form(customer, step)

            data.update({'step': step})
            missing_data = self.get_missing_data(step=step)
            data.update(**missing_data)

            serializer = GrabApplicationV2Serializer(
                data=data,
                src_customer_id=customer.id,
                is_update=True
            )
            serializer.is_valid(raise_exception=True)
            result = self.update_grab_application(
                customer=customer,
                validated_data=serializer.validated_data,
                data=data,
                step=step
            )
            if result.get('is_allowed_application'):
                self.current_step += 1
            else:
                GrabApiException("failed to load data from previous app at step: {}".format(step))


class GrabLoanService(object):
    from juloserver.julo.services2 import get_redis_client
    redis_client = None

    def set_redis_client(self):
        self.redis_client = get_redis_client()

    def get_grab_loan_offer_data(self,  grab_customer_data_id, program_id, force_from_db=True):
        grab_loan_offer_obj = None

        if not force_from_db and self.redis_client:
            grab_loan_offer_obj = self.get_grab_loan_offer_from_redis(
                grab_customer_data_id, program_id)

        if not grab_loan_offer_obj:
            grab_loan_offer_obj = GrabLoanOffer.objects.filter(
                grab_customer_data=grab_customer_data_id,
                program_id=program_id
            ).last()

        return grab_loan_offer_obj

    def get_grab_loan_offer_from_redis(self, grab_customer_data_id, program_id):
        if self.redis_client:
            try:
                key = "grab_loan_offer_{}_{}".format(grab_customer_data_id, program_id)
                result = self.redis_client.get(key)
                result = result.replace("\'", "\"")
                result = result.replace('None', "null")
                return GrabLoanOffer(**json.loads(result))
            except json.JSONDecodeError:
                return None
        return None

    def save_grab_loan_offer_to_redis(self, grab_loan_offer_data):
        redis_key = "grab_loan_offer_{}_{}".format(
            grab_loan_offer_data.get("grab_customer_data_id"),
            grab_loan_offer_data.get("program_id"))

        saved_data_to_redis = {}
        for key, value in grab_loan_offer_data.items():
            if key.startswith("_") or key in ['cdate', 'udate']:
                continue
            saved_data_to_redis[key] = value

        self.redis_client.set(redis_key, saved_data_to_redis, expire_time=timedelta(minutes=5))

    def save_grab_loan_offer_archival(self, grab_loan_offer_data):
        grab_loan_offer_archival_serializer = GrabLoanOfferArchivalSerializer(
            data=grab_loan_offer_data
        )
        grab_loan_offer_archival_serializer.is_valid(raise_exception=True)
        grab_loan_offer_archival_serializer.create(
            grab_loan_offer_archival_serializer.validated_data
        )

    def save_grab_loan_offer(self, offer, grab_customer_data):
        grab_loan_offer_data = offer
        grab_loan_offer_data.update({
            "grab_customer_data": grab_customer_data.id,
            "tenure": offer.get("loan_duration")
        })
        del offer["loan_duration"]

        # just allow 1 data in this grab loan offer
        grab_loan_offer_obj = GrabLoanOffer.objects.filter(
                grab_customer_data=grab_customer_data.id
        ).last()

        grab_loan_offer_obj_data = None

        if grab_loan_offer_obj:
            grab_loan_offer_serializer = GrabLoanOfferSerializer(
                data=grab_loan_offer_data,
                context={"exclude_fields": ["grab_customer_data"]}
            )

            grab_loan_offer_serializer.is_valid(raise_exception=True)

            grab_loan_offer_obj_data = grab_loan_offer_serializer.update(
                grab_loan_offer_obj, grab_loan_offer_serializer.validated_data
            )
        else:
            grab_loan_offer_serializer = GrabLoanOfferSerializer(data=grab_loan_offer_data)
            grab_loan_offer_serializer.is_valid(raise_exception=True)

            grab_loan_offer_obj_data = grab_loan_offer_serializer.create(
                grab_loan_offer_serializer.validated_data)

        if self.redis_client and grab_loan_offer_obj_data:
            self.save_grab_loan_offer_to_redis(grab_loan_offer_obj_data.__dict__)

        # for archival
        self.save_grab_loan_offer_archival(grab_loan_offer_data=grab_loan_offer_data)

    def parse_loan_offer(self, grab_response, grab_customer_data):
        response = []
        if "data" in grab_response and grab_response["data"]:
            for offer in grab_response["data"]:
                offer["tenure_interval"] = 30
                if int(float(offer["min_loan_amount"])) > int(float(offer["max_loan_amount"])) \
                    or int(offer["loan_duration"]) < 1:
                    continue
                calculated_max_loan = int(math.floor(
                    int(round(float(offer['weekly_installment_amount']))) * (
                                int(offer["loan_duration"]) / 7) / 50000.0) * 50000)
                max_loan_amount = min(int(float(offer["max_loan_amount"])), calculated_max_loan)
                offer['max_loan_amount'] = str(max_loan_amount)
                if int(float(offer["min_loan_amount"])) > int(float(offer["max_loan_amount"])):
                    continue

                response.append({
                    "program_id": offer["program_id"],
                    "max_loan_amount": offer["max_loan_amount"],
                    "min_loan_amount": offer["min_loan_amount"],
                    "weekly_installment_amount": offer['weekly_installment_amount'],
                    "tenure": offer["loan_duration"],
                    "min_tenure": offer["min_tenure"],
                    "tenure_interval": offer["tenure_interval"],
                    "daily_repayment": get_daily_repayment_amount(
                        offer["max_loan_amount"], offer["loan_duration"], offer["interest_value"]),
                    "upfront_fee_type": offer["fee_type"],
                    "upfront_fee": offer["fee_value"],
                    "interest_rate_type": offer["interest_type"],
                    "interest_rate": offer["interest_value"],
                    "penalty_type": offer["penalty_type"],
                    "penalty_value": offer["penalty_value"],
                    "loan_disbursement_amount": int(float(offer["max_loan_amount"])) - int(offer["fee_value"]),
                    "frequency_type": offer["frequency_type"]
                })
                self.save_grab_loan_offer(offer, grab_customer_data)
        elif "error" in grab_response and 'message' in grab_response['error']:
            if "UserProfileNotFound" in grab_response["error"]["message"]:
                if grab_customer_data.customer_id:
                    logger.warning(
                        {
                            "action": "get_loan_offer",
                            "grab_response": grab_response,
                            "raises": "UserProfileNotFound",
                            "error": GrabErrorCodes.GE_1
                        }
                    )
                    raise GrabLogicException(
                        GrabUtils.create_error_message(
                            GrabErrorCodes.GE_1,
                            GrabErrorMessage.CHANGE_PHONE_REQUEST
                        )
                    )
        return response

    def get_loan_offer(self, token, phone_number):
        if FeatureSetting.objects.filter(feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
                                         is_active=True).exists():
            raise GrabLogicException("Can't getting offer at the moment")

        grab_customer_data = GrabCustomerData.objects.\
            get_or_none(phone_number=phone_number,
                        grab_validation_status=True,
                        token=token,
                        otp_status=GrabCustomerData.VERIFIED
            )

        if grab_customer_data:
            grab_response = GrabClient.get_loan_offer(phone_number=phone_number,
                                                      customer_id=grab_customer_data.customer_id)

            response = self.parse_loan_offer(grab_response, grab_customer_data)
            return response
        else:
            raise GrabLogicException("You are not eligible for getting offer.")

    @staticmethod
    def calculate_payment_plans(offer_threshold, loan_duration, max_loan_amount,
                                min_loan_amount, interest_rate):
        calculated_max_loan_disbursement = (offer_threshold * loan_duration) / 7
        loan_amount = round_rupiah_grab(py2round(
            calculated_max_loan_disbursement / (1 + ((interest_rate / 100) * loan_duration / 30))
        ))
        loan_amount = (math.floor(loan_amount / 50000.0) * 50000.0)
        loan_amount = min(int(max_loan_amount), loan_amount)
        if int(min_loan_amount) > int(loan_amount):
            return None
        daily_intalment_amount = get_daily_repayment_amount(
            loan_amount, loan_duration, interest_rate)
        weekly_instalment_amount = get_weekly_instalment_amount(
            loan_amount, loan_duration)

        calculated_max_loan_disbursement_for_slo = int(math.floor(int(round(float(
            offer_threshold))) * (int(loan_duration) / 7) / 50000.0) * 50000)
        slo_max_loan_amount = min(int(max_loan_amount), calculated_max_loan_disbursement_for_slo)
        slo_loan_amount = str(slo_max_loan_amount)
        repayment_amount = get_loan_repayment_amount(loan_amount, loan_duration, interest_rate)
        return {
            "loan_amount": int(loan_amount),
            "daily_intalment_amount": daily_intalment_amount,
            "weekly_instalment_amount": weekly_instalment_amount,
            "slo_loan_amount": slo_loan_amount,
            "repayment_amount": repayment_amount
        }

    def get_payment_plans(self, token, phone_number, program_id, loan_amount, interest_rate,
                          upfront_fee, min_tenure, tenure, tenure_interval, offer_threshold,
                          min_loan_amount, max_loan_amount):

        grab_customer_data = GrabCustomerData.objects.get_or_none(phone_number=phone_number,
                                                                  grab_validation_status=True,
                                                                  token=token,
                                                                  otp_status=GrabCustomerData.VERIFIED)

        if grab_customer_data:
            grab_loan_offer = self.get_grab_loan_offer_data(
                grab_customer_data_id=grab_customer_data.id,
                program_id=program_id
            )

            if not grab_loan_offer:
                raise GrabLogicException("You are not eligible for getting payment plans.")

            response = []
            response_slo = []

            list_of_tenure_duration = list(range(
                grab_loan_offer.min_tenure,
                grab_loan_offer.tenure + 1,
                grab_loan_offer.tenure_interval)
            )

            interest_rate = grab_loan_offer.interest_value
            upfront_fee = grab_loan_offer.fee_value
            offer_threshold = grab_loan_offer.weekly_installment_amount
            min_loan_amount = grab_loan_offer.min_loan_amount
            max_loan_amount = grab_loan_offer.max_loan_amount
            min_tenure = grab_loan_offer.min_tenure

            if tenure not in list_of_tenure_duration:
                raise GrabLogicException("Invalid tenure")

            additional_options = []
            additional_loan_options_count = 0
            max_tenure = list_of_tenure_duration[-1] if list_of_tenure_duration else 0
            min_loan_result = 0
            max_loan_result = 0

            for loan_duration in list_of_tenure_duration:
                daily_repayment_data = self.calculate_payment_plans(
                    offer_threshold=offer_threshold,
                    loan_duration=loan_duration,
                    max_loan_amount=max_loan_amount,
                    min_loan_amount=min_loan_amount,
                    interest_rate=interest_rate
                )

                if not daily_repayment_data:
                    continue

                if int(min_loan_amount) > int(loan_amount):
                    continue

                loan_amount = daily_repayment_data["loan_amount"]
                daily_intalment_amount = daily_repayment_data["daily_intalment_amount"]
                weekly_instalment_amount = daily_repayment_data["weekly_instalment_amount"]
                slo_loan_amount = daily_repayment_data["slo_loan_amount"]
                repayment_amount = daily_repayment_data["repayment_amount"]

                if loan_duration == max_tenure:
                    max_loan_result = int(slo_loan_amount)

                response.append({
                    "tenure": loan_duration,
                    "daily_repayment": daily_intalment_amount,
                    "repayment_amount": repayment_amount,
                    "loan_disbursement_amount": int(loan_amount) - int(upfront_fee),
                    "weekly_instalment_amount": weekly_instalment_amount,
                    "loan_amount": int(loan_amount),
                    "smaller_loan_option_flag": False
                })
                response_slo.append(
                    {
                        "slo_loan_amount": slo_loan_amount
                    }
                )

            min_tenure = grab_loan_offer.min_tenure
            max_tenure = grab_loan_offer.tenure
            interest_rate = grab_loan_offer.interest_value
            upfront_fee = grab_loan_offer.fee_value

            # set the first index of response into a min loan and tenure result
            if response:
                min_loan_result = int(response_slo[0].get('slo_loan_amount'))

            """ experiment smaller loan offer """
            additional_options, additional_loan_options_count, additional_response = \
                process_additional_smaller_loan_offer_option(min_loan_result, max_loan_result,
                                                             min_tenure, max_tenure, interest_rate,
                                                             upfront_fee, offer_threshold)
            response.extend(additional_response)
            """ end of experiment smaller loan offer """
            # Sort generated loan and merge with additional loans
            # Sorting logic:
            # Order 1: Max tenure, max loan amount
            # Order 2: Additional option 2 (Can be empty)
            # Order 3: Additional option 1
            # Order 4: Rest of the loan options, sort by loan amount and loan tenure (max to min)
            response = sorted(response, key=itemgetter('loan_amount', 'tenure'), reverse=True)
            response = response[:1] + additional_options + response[1:]

            # record to GrabExperiment table
            if additional_loan_options_count:
                create_grab_experiment(
                    experiment_name="smaller_loan_option",
                    grab_customer_data_id=grab_customer_data.id,
                    parameters={
                        "additional_loan_options_count": additional_loan_options_count
                    }
                )
            return response
        else:
            raise GrabLogicException("You are not eligible for getting payment plans.")

    @staticmethod
    def get_timedelta_in_days_for_new_loans():
        default_timedelta = 4
        first_due_date = (
            timezone.localtime(timezone.now()) + timedelta(days=default_timedelta)
        ).date()
        current_date = timezone.localtime(timezone.now()).date()
        is_active, loan_halt_date, loan_resume_date = GrabLoanService.get_fs_for_loan_timedelta()
        if is_active and loan_halt_date <= first_due_date <= loan_resume_date:
            calculated_timedelta = (loan_resume_date - current_date).days
        else:
            calculated_timedelta = default_timedelta
        return calculated_timedelta

    @staticmethod
    def get_fs_for_loan_timedelta():
        """
        Return value:
            is_active: whether FS is active or not
            loan halt date: Loan Halt date
            loan Resume date: loan resume date
        """
        grab_fs = GrabFeatureSetting.objects.filter(
            feature_name=GrabFeatureNameConst.GRAB_HALT_RESUME_DISBURSAL_PERIOD, is_active=True
        ).last()
        if not grab_fs:
            return False, None, None
        loan_resume_date = grab_fs.parameters.get('loan_resume_date')
        loan_halt_date = grab_fs.parameters.get('loan_halt_date')
        loan_resume_date = datetime.datetime.strptime(loan_resume_date, '%Y-%m-%d').date()
        loan_halt_date = datetime.datetime.strptime(loan_halt_date, '%Y-%m-%d').date()
        return grab_fs.is_active, loan_halt_date, loan_resume_date


    @staticmethod
    def get_payment_plans_from_additional_option(payment_plan, grab_loan_offer, validated_data):
        min_loan_result = GrabLoanService().calculate_payment_plans(
            offer_threshold=grab_loan_offer.weekly_installment_amount,
            loan_duration=grab_loan_offer.min_tenure,
            max_loan_amount=grab_loan_offer.max_loan_amount,
            min_loan_amount=grab_loan_offer.min_loan_amount,
            interest_rate=grab_loan_offer.interest_value
        )

        additional_options, _, additional_response = \
            process_additional_smaller_loan_offer_option(
            min_loan_result=min_loan_result.get("loan_amount"),
            max_loan_result=payment_plan.get("loan_amount"),
            min_tenure=grab_loan_offer.min_tenure,
            max_tenure=grab_loan_offer.tenure,
            interest_rate=grab_loan_offer.interest_value,
            upfront_fee=grab_loan_offer.fee_value,
            offer_threshold=grab_loan_offer.weekly_installment_amount
        )
        result = {}
        for plan in additional_options + additional_response:
            result["{}_{}".format(int(plan["loan_amount"]), int(plan["tenure"]))] = plan
        return result

    @staticmethod
    def is_valid_tenure(grab_loan_offer, tenure):
        list_of_tenure_duration = list(range(
            grab_loan_offer.min_tenure,
            grab_loan_offer.tenure + 1,
            grab_loan_offer.tenure_interval)
        )
        return int(tenure) in list_of_tenure_duration

    def choose_payment_plan(self, token, validated_data):
        grab_customer_data = GrabCustomerData.objects.get_or_none(phone_number=validated_data["phone_number"],
                                                                  otp_status=GrabCustomerData.VERIFIED,
                                                                  token=token,
                                                                  grab_validation_status=True)

        if grab_customer_data:
            with transaction.atomic():
                not_eligible_str = "You are not eligible for getting payment plans."
                grab_loan_offer = self.get_grab_loan_offer_data(
                    grab_customer_data_id=grab_customer_data.id,
                    program_id=validated_data["program_id"]
                )

                if not grab_loan_offer:
                    raise GrabLogicException(not_eligible_str)

                if not GrabLoanService().is_valid_tenure(grab_loan_offer,
                                                         validated_data.get("tenure_plan")):
                    raise GrabLogicException(not_eligible_str)

                # check payment plan from request
                is_exist, payment_plan = self.is_payment_plan_exist(
                    grab_customer_data.id, validated_data
                )
                if not is_exist:
                    raise GrabLogicException(not_eligible_str)

                validated_data['instalment_amount_plan'] = payment_plan.get('daily_repayment')
                validated_data['tenure_plan'] = payment_plan.get('tenure')
                validated_data['total_repayment_amount_plan'] = payment_plan.get('repayment_amount')
                validated_data['loan_disbursement_amount'] = payment_plan.get(
                    'loan_disbursement_amount'
                )
                validated_data['weekly_installment_amount'] = payment_plan.get(
                    'weekly_instalment_amount'
                )
                validated_data["fee_value_plan"] = payment_plan.get('upfront_fee')
                validated_data["interest_value_plan"] = grab_loan_offer.interest_value
                validated_data["amount_plan"] = payment_plan.get('loan_amount')

                # get the last grab_loan_data that not assigned by loan
                # if exists and update it
                grab_loan_data = GrabLoanData.objects.filter(
                    loan_id__isnull=True,
                    grab_loan_inquiry__program_id=validated_data["program_id"],
                    grab_loan_inquiry__grab_customer_data=grab_customer_data,
                ).last()
                grab_loan_inquiry = (
                    grab_loan_data.grab_loan_inquiry if grab_loan_data else GrabLoanInquiry()
                )
                grab_loan_inquiry.grab_customer_data_id = grab_customer_data.id

                # loan offer data
                grab_loan_inquiry.program_id = validated_data["program_id"]
                grab_loan_inquiry.max_loan_amount = validated_data["max_loan_amount"]
                grab_loan_inquiry.min_loan_amount = validated_data["min_loan_amount"]
                grab_loan_inquiry.instalment_amount = validated_data["instalment_amount_plan"]
                grab_loan_inquiry.loan_duration = validated_data["tenure_plan"]
                grab_loan_inquiry.frequency_type = validated_data["frequency_type"]
                grab_loan_inquiry.fee_value = validated_data["fee_value_plan"]
                grab_loan_inquiry.loan_disbursement_amount = validated_data["loan_disbursement_amount"]
                grab_loan_inquiry.interest_type = validated_data["interest_type_plan"]
                grab_loan_inquiry.interest_value = validated_data["interest_value_plan"]
                grab_loan_inquiry.penalty_type = validated_data["penalty_type"]
                grab_loan_inquiry.penalty_value = validated_data["penalty_value"]

                # repayment data
                grab_loan_inquiry.amount_plan = validated_data["amount_plan"]
                grab_loan_inquiry.tenure_plan = validated_data["tenure_plan"]
                grab_loan_inquiry.interest_type_plan = validated_data["interest_type_plan"]
                grab_loan_inquiry.interest_value_plan = validated_data["interest_value_plan"]
                grab_loan_inquiry.instalment_amount_plan = validated_data["instalment_amount_plan"]
                grab_loan_inquiry.fee_type_plan = validated_data["fee_type_plan"]
                grab_loan_inquiry.fee_value_plan = validated_data["fee_value_plan"]
                grab_loan_inquiry.total_repayment_amount_plan = validated_data["total_repayment_amount_plan"]
                grab_loan_inquiry.weekly_instalment_amount = validated_data['weekly_installment_amount']

                grab_loan_inquiry.save()

                grab_loan_inquiry.refresh_from_db()

                grab_loan_data = grab_loan_data if grab_loan_data else GrabLoanData()
                grab_loan_data.grab_loan_inquiry_id = grab_loan_inquiry.id
                grab_loan_data.program_id = grab_loan_inquiry.program_id
                grab_loan_data.selected_amount = grab_loan_inquiry.amount_plan
                grab_loan_data.selected_tenure = grab_loan_inquiry.tenure_plan
                grab_loan_data.selected_fee = grab_loan_inquiry.fee_value_plan
                grab_loan_data.selected_interest = grab_loan_inquiry.interest_value_plan
                grab_loan_data.selected_instalment_amount = grab_loan_inquiry.instalment_amount_plan

                grab_loan_data.save()
                grab_loan_data.refresh_from_db()
                promo_code = validated_data.get('promo_code', None)
                if promo_code:
                    add_grab_loan_promo_code(promo_code, grab_loan_data.id)

                process_update_grab_experiment_by_grab_customer_data(validated_data,
                                                                     grab_customer_data,
                                                                     grab_loan_data)

                response = {"is_payment_plan_set": True}

                return response
        else:
            raise GrabLogicException("You are not eligible for getting payment plans.")

    @staticmethod
    def get_pre_loan_detail(customer):
        grab_loan_data = GrabLoanData.objects.filter(
            grab_loan_inquiry__grab_customer_data__customer=customer
        ).order_by('-cdate')[0:1]

        if grab_loan_data:
            program_id = grab_loan_data[0].program_id
            application = Application.objects.filter(customer=customer).order_by("-cdate")[0:1]
            grab_customer_data_obj = GrabCustomerData.objects.filter(customer=customer).last()
            grab_loan_offer_obj = GrabLoanOffer.objects.filter(
                grab_customer_data=grab_customer_data_obj, program_id=program_id
            ).last()

            if application:
                provision = 7.0
                loan_offer = {}
                disbursed_to = None
                if application[0].bank_name and application[0].name_in_bank:
                    disbursed_to = "{} a.n. {}".format(
                        application[0].bank_name, application[0].name_in_bank
                    )
                if grab_loan_offer_obj:
                    loan_offer = {
                        "tenure": grab_loan_offer_obj.tenure,
                        "program_id": grab_loan_offer_obj.program_id,
                        "max_loan_amount": grab_loan_offer_obj.max_loan_amount,
                        "min_loan_amount": grab_loan_offer_obj.min_loan_amount,
                        "phone_number": grab_customer_data_obj.phone_number,
                        "interest_value": grab_loan_offer_obj.interest_value,
                        "weekly_installment_amount": grab_loan_offer_obj.weekly_installment_amount,
                        "min_tenure": grab_loan_offer_obj.min_tenure,
                        "tenure_interval": grab_loan_offer_obj.tenure_interval,
                        "loan_disbursement_amount": grab_loan_offer_obj.max_loan_amount
                        - grab_loan_offer_obj.fee_value,
                    }

                response = {
                    "loan": {
                        "amount": grab_loan_data[0].selected_amount,
                        "fee": grab_loan_data[0].selected_fee,
                        "disbursed": grab_loan_data[0].grab_loan_inquiry.loan_disbursement_amount,
                        "disbursed_to": disbursed_to,
                    },
                    "repayment": {
                        "amount": grab_loan_data[0].selected_instalment_amount,
                        "tenure": grab_loan_data[0].selected_tenure,
                        "interest_rate": grab_loan_data[0].selected_interest,
                    },
                    "loan_offer": loan_offer,
                }

                return response
            else:
                raise GrabLogicException("The latest application form is not found for this customer.")
        else:
            raise GrabLogicException("The latest loan offer is not found for this customer.")

    def get_valid_grab_customer_data(self, customer):
        grab_customer_data = GrabCustomerData.objects.filter(
            customer=customer).exclude(
            is_customer_blocked_for_loan_creation=True).last()

        if not grab_customer_data:
            raise GrabLogicException("Grab customer Not Found")

        return grab_customer_data

    def apply(self, customer, user, program_id, loan_amount, tenure, bypass=False):
        if FeatureSetting.objects.filter(feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
                                         is_active=True).exists():
            raise GrabLogicException("grab modal registration not active")

        if not customer:
            raise GrabLogicException("Customer id {} not found".format(customer.id))

        grab_customer_data = self.get_valid_grab_customer_data(customer)

        # validate the program id
        grab_loan_offer = self.get_grab_loan_offer_data(
            grab_customer_data_id=grab_customer_data.id,
            program_id=program_id)
        if not grab_loan_offer:
            raise GrabLogicException("Grab Loan offer not found")

        # validate tenure
        list_of_tenure_duration = set(range(
            grab_loan_offer.min_tenure,
            grab_loan_offer.tenure + 1,
            grab_loan_offer.tenure_interval)
        )
        if tenure not in list_of_tenure_duration:
            raise GrabLogicException("Tenure not valid")

        account = Account.objects.filter(
            customer=customer,
            account_lookup__workflow__name=WorkflowConst.GRAB).last()
        if not account:
            raise GrabLogicException('Account tidak ditemukan')

        graveyard_loan_statuses.update({
            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.HALT
        })
        existing_loans = Loan.objects.filter(account=account).exclude(
            loan_status__in=graveyard_loan_statuses
        ).exists()
        if existing_loans:
            raise GrabLogicException('Active Loan Exists. Please Refresh screen.')

        application = account.last_application
        if not application:
            raise GrabLogicException('Application tidak ditemukan')
        if not bypass:
            update_grab_limit(account, program_id)
            if application.customer.user != user:
                raise GrabLogicException('User tidak sesuai dengan account')

        if not GrabAPILog.objects.filter(
            query_params=GrabPaths.APPLICATION_CREATION,
            application_id=application.id,
            http_status_code=https_status_codes.HTTP_200_OK
        ).exists():
            if not GrabAPILog.objects.filter(
                query_params=GrabPaths.LEGACY_APPLICATION_CREATION,
                application_id=application.id,
                http_status_code=https_status_codes.HTTP_200_OK
            ).exists():
                raise GrabLogicException('ApplicationLog tidak ditemukan')

        if program_id:
            grab_loan_data = GrabLoanData.objects.filter(
                loan_id__isnull=True,
                grab_loan_inquiry__program_id=program_id,
                grab_loan_inquiry__grab_customer_data=grab_customer_data,
            ).last()
            if not grab_loan_data:
                raise GrabLogicException("Grab Loan Data Not Found")

            grab_loan_inquiry = grab_loan_data.grab_loan_inquiry
            if not grab_loan_inquiry:
                raise GrabLogicException("Grab Loan Inquiry Not Found")

            loan_amount = grab_loan_data.selected_amount
        else:
            raise GrabLogicException("No Program Data")

        account_limit = AccountLimit.objects.filter(
            account=account
        ).last()

        if account_limit:
            if loan_amount > account_limit.available_limit:
                raise GrabLogicException(
                    "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
                )

        product = ProductLookup.objects.filter(
            product_line_id=ProductLineCodes.GRAB,
            admin_fee=grab_loan_inquiry.fee_value,
            interest_rate=float(old_div(grab_loan_inquiry.interest_value, 100))
        ).last()

        if not product:
            raise GrabLogicException(
                "ProductLookup missing with fee {} and interest {}".format(
                    grab_loan_inquiry.fee_value, float(old_div(grab_loan_inquiry.interest_value, 100))))

        if not loan_amount:
            raise GrabLogicException('Loan amount not specified')

        loan_requested = dict(
            loan_amount=loan_amount,
            loan_duration_request=tenure,
            interest_rate_monthly=grab_loan_inquiry.interest_value,
            product=product,
            provision_fee=0,
            grab_loan_inquiry=grab_loan_inquiry,
            admin_fee=grab_loan_inquiry.fee_value
        )
        try:
            trigger_application_creation_grab_api.delay(application.id)
            with transaction.atomic():
                loan = generate_loan_payment_grab(
                    application,
                    account,
                    loan_requested,
                    'Grab_loan_creation',
                    None)
                name_bank_validation = NameBankValidation.objects.get_or_none(
                    pk=loan.name_bank_validation_id)
                if not name_bank_validation:
                    raise GrabLogicException({
                        'action': 'loan_lender_approval_process',
                        'message': 'Name Bank Validation Not Found!!',
                        'loan_id': loan.id
                    })
                bank_code = name_bank_validation.bank_code
                swift_bank_code = ''
                if bank_code:
                    filter_param = {}
                    if name_bank_validation.method == DisbursementVendors.PG:
                        filter_param['id'] = name_bank_validation.bank_id
                    else:
                        filter_param["xfers_bank_code"] = bank_code

                    swift_bank_code = Bank.objects.filter(**filter_param).last()

                    if swift_bank_code:
                        swift_bank_code = swift_bank_code.swift_bank_code
                    else:
                        swift_bank_code = ''
                pre_disbursal_check_data = {
                    "phone_number": grab_customer_data.phone_number,
                    "bank_code": swift_bank_code,
                    "bank_account_number": name_bank_validation.account_number,
                    "application_id": application.id,
                    "customer_id": customer.id,
                    "loan_id": loan.id
                }
                try:
                    response = GrabClient().get_pre_disbursal_check(**pre_disbursal_check_data)
                    response_data = json.loads(response.content)
                    if 'data' not in response_data:
                        exception_message = 'Mohon maaf, akun / nama bank Anda tidak sesuai , ' \
                                            'mohon contact cs@julo.co.id dengan melampirkan ' \
                                            'info permasalahan ini'
                        raise GrabLogicException(exception_message)
                    if response_data['data']['code']:
                        exception_message = 'Mohon maaf, akun / nama bank Anda tidak sesuai , ' \
                                            'mohon contact cs@julo.co.id dengan melampirkan ' \
                                            'info permasalahan ini'
                        raise GrabLogicException(exception_message)
                    update_available_limit(loan)
                except Timeout as e:
                    default_url = GrabPaths.PRE_DISBURSAL_CHECK
                    if e.response:
                        send_grab_api_timeout_alert_slack.delay(
                            response=e.response,
                            uri_path=e.request.url if e.request else default_url,
                            application_id=application.id,
                            customer_id=application.customer.id,
                            loan_id=loan.id
                        )
                    else:
                        send_grab_api_timeout_alert_slack.delay(
                            uri_path=e.request.url if e.request else default_url,
                            application_id=application.id,
                            customer_id=application.customer.id,
                            loan_id=loan.id,
                            err_message=str(e) if e else None
                        )
                update_grab_loan_promo_code_with_loan_id(grab_loan_data.id, loan.id)
        except GrabLogicException as e:
            GrabClient.log_grab_api_call(response.request.headers, response,
                                         response.request.method, response.request.url,
                                         application_id=application.id, customer_id=customer.id,
                                         grab_customer_data=grab_customer_data)
            logger.exception(str(e))
            raise
        disbursement_amount = grab_loan_inquiry.loan_disbursement_amount
        installment_amount = round_rupiah_grab(
            math.floor(
                (old_div(loan.loan_amount, loan.loan_duration)) +
                old_div((grab_loan_inquiry.interest_value * loan.loan_amount), 30)
            )
        )
        trigger_auth_call_for_loan_creation.delay(loan.id)
        return_data = {
            "loan": loan,
            "disbursement_amount": disbursement_amount,
            "installment_amount": installment_amount,
            "monthly_interest": grab_loan_inquiry.interest_value
        }
        trigger_push_notification_grab.apply_async(
            kwargs={'loan_id': loan.id})
        trigger_sms_to_submit_digisign.delay(loan.id)
        return return_data

    @staticmethod
    def get_agreement_summary(loan_xid):
        if not loan_xid:
            raise GrabLogicException("Loan_xid Harus Diisi")
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        grab_loan_data = GrabLoanData.objects.get_or_none(loan=loan)

        response = {
            "loan": {
                "amount": loan.loan_amount,
                "upfront_fee": grab_loan_data.selected_fee,
                "disbursal_amount": loan.loan_disbursement_amount,
                "daily_repayment": grab_loan_data.selected_instalment_amount,
                "tenure": grab_loan_data.selected_tenure,
                "interest_rate": grab_loan_data.selected_interest
            },
            "bank": {
                "account_number": loan.bank_account_destination.account_number,
                "account_name": loan.bank_account_destination.name_bank_validation.validated_name,
                "bank_name": loan.bank_account_destination.bank.bank_name
            }
        }

        return response

    @staticmethod
    def get_agreement_letter(loan_xid):

        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            raise GrabLogicException('loan does not exist with loan_xid {}'.format(loan_xid))
        template = get_sphp_template_grab(loan.id, "android")

        response = {
            "agreement_letter": template,
            'context': get_sphp_context_grab(loan.id)
        }
        return response

    @staticmethod
    def get_loans_account_payment(customer, account_id, data_type):

        loans = None
        if data_type and data_type == "ACTIVE":
            loans = Loan.objects.filter(
                customer=customer,
                account__account_lookup__name=GRAB_ACCOUNT_LOOKUP_NAME,
                loan_status__in=active_loan_status)
        elif data_type and data_type == "IN_ACTIVE":
            loans = Loan.objects.filter(
                customer=customer,
                account__account_lookup__name=GRAB_ACCOUNT_LOOKUP_NAME,
                loan_status__in=inactive_loan_status)
        elif data_type and data_type == "ALL":
            loans = Loan.objects.filter(
                customer=customer,
                account__account_lookup__name=GRAB_ACCOUNT_LOOKUP_NAME)

        if account_id:
            account = Account.objects.get_or_none(id=account_id)
            if not account:
                raise GrabLogicException("Account not found for ID {}".format(account_id))

            loans = loans.filter(account=account)

        loan_results = []
        dpd_list = []
        status_loan = None
        oldest_unpaid_account_payment = None

        if loans:
            status_loan = loans.filter(loan_status__lt=LoanStatusCodes.PAID_OFF).order_by('-loan_status').first()
            oldest_unpaid_account_payment = AccountPayment.objects.filter(
                account__loan__in=loans,
                status__lt=PaymentStatusCodes.PAID_ON_TIME
            ).order_by('due_date').first()
            for loan in loans.iterator():
                first_payment = Payment.objects.filter(loan=loan).order_by('due_date').first()

                total_due_amount = Payment.objects.filter(
                    loan=loan,
                    payment_status__status_code__lt=PaymentStatusCodes.PAID_ON_TIME) \
                    .aggregate(Sum('due_amount'))

                total_payment_count = Payment.objects.filter(
                    loan=loan).count()

                paid_payment_count = Payment.objects.filter(
                    loan=loan,
                    payment_status__status_code__gte=PaymentStatusCodes.PAID_ON_TIME).count()

                # dpd_list.append(loan.dpd)

                grab_loan_data = GrabLoanData.objects.get_or_none(loan=loan)
                if loan.status == LoanStatusCodes.PAID_OFF:
                    last_payment = Payment.objects.filter(loan=loan).order_by('due_date').last()
                    paid_off_date = last_payment.paid_date
                else:
                    paid_off_date = '-'

                loan_results.append({
                    "loan_xid": loan.loan_xid,
                    "start_pay": first_payment.due_date.strftime("%d %b %Y") if first_payment else '-',
                    "remaining_payment": total_due_amount["due_amount__sum"],
                    "daily_payment": loan.installment_amount,
                    "status": loan.loan_status_label if loan.loan_status_label else "Sedang diproses",
                    "successful_payment": str(paid_payment_count) + " dari " + str(
                        total_payment_count),
                    "application_date": loan.cdate.strftime("%d %b %Y"),
                    "loan_amount": loan.loan_amount,
                    "loan_duration": loan.loan_duration,
                    "paid_off_date": paid_off_date.strftime(
                        "%d %b %Y") if paid_off_date != '-' else paid_off_date,
                    "interest_rate": (loan.product.interest_rate * 100),
                    "loan_status_code": loan.status
                })
        # if dpd_list:
        #     due_date_in = "{} Day{}".format(max(dpd_list), '' if max(
        #         dpd_list) == 1 else 's')
        #
        # else:
        #     due_date_in = '-'

        if status_loan:
            status_loan_label = status_loan.loan_status_label if \
                status_loan.loan_status_label else "Sedang diproses"
        else:
            status_loan_label = '-'

        if oldest_unpaid_account_payment:
            due_amount = oldest_unpaid_account_payment.due_amount
            due_date_in = '{} hari'.format(oldest_unpaid_account_payment.dpd)
        else:
            due_amount = '-'
            due_date_in = '-'

        response = {
            "status": status_loan_label,
            "amount": due_amount,
            "due_date_in": due_date_in,
            "loans": loan_results
        }

        return response

    @staticmethod
    def get_loans_payment(customer, account_id, data_type):
        prefetch_payment_qs = Payment.objects.all().order_by('due_date')
        prefetch_payment_set = Prefetch(
            'payment_set', prefetch_payment_qs, to_attr="prefetch_payment_set")

        total_due_amount_qs = Payment.objects.select_related('payment_status').filter(
            payment_status__status_code__lt=PaymentStatusCodes.PAID_ON_TIME
        )
        prefetch_total_due_amount = Prefetch(
            'payment_set', total_due_amount_qs,
            to_attr="prefetch_total_due_amount")

        total_payment_count_qs = Payment.objects.all()
        prefetch_total_payment_count = Prefetch('payment_set', total_payment_count_qs,
                                                to_attr="prefetch_total_payment_count")
        total_paid_payment_count_qs = Payment.objects.select_related('payment_status').filter(
                    payment_status__status_code__gte=PaymentStatusCodes.PAID_ON_TIME)
        prefetch_total_paid_payment_count = Prefetch('payment_set', total_paid_payment_count_qs,
                                                     to_attr="prefetch_total_paid_payment_count")

        join_tables = [
            prefetch_payment_set,
            prefetch_total_due_amount,
            prefetch_total_payment_count,
            prefetch_total_paid_payment_count
        ]
        loans = Loan.objects.select_related('account', 'account__account_lookup'
                                            ).prefetch_related(*join_tables).filter(
            customer=customer,
            account__account_lookup__name=GRAB_ACCOUNT_LOOKUP_NAME)
        if data_type and data_type == "ACTIVE":
            loans = loans.filter(loan_status__in=active_loan_status)
        elif data_type and data_type == "IN_ACTIVE":
            loans = loans.filter(loan_status__in=inactive_loan_status)
        elif data_type and data_type == "ALL":
            pass
        if account_id:
            account = Account.objects.get_or_none(id=account_id)
            if not account:
                raise GrabLogicException("Account not found for ID {}".format(account_id))

            loans = loans.filter(account=account)

        loan_results = []
        status_loan = None
        oldest_payments_due_amount = None
        days_in_dpd = None
        if loans:
            status_loan = loans.filter(loan_status__lt=LoanStatusCodes.PAID_OFF).order_by('-loan_status').first()
            loan_ids = loans.values_list('id', flat=True)
            oldest_due_date = Payment.objects.filter(
                loan_id__in=loan_ids).not_paid_active().order_by(
                'due_date').annotate(min_due_date=Min('due_date'))
            oldest_unpaid_payment = Payment.objects.filter(
                loan_id__in=loan_ids).not_paid_active().order_by(
                'due_date').first()
            if oldest_due_date.exists():
                oldest_due_date = oldest_due_date[0].due_date
                oldest_due_date_payments = Payment.objects.filter(
                    loan_id__in=loan_ids, due_date=oldest_due_date).not_paid_active().aggregate(Sum('due_amount'))
                oldest_payments_due_amount = oldest_due_date_payments['due_amount__sum']
                days_in_dpd = oldest_unpaid_payment.due_late_days_grab

            for loan in loans:
                first_payment = loan.prefetch_payment_set[0]
                total_due_amount = 0
                for due_amount_payment in loan.prefetch_total_due_amount:
                    total_due_amount += due_amount_payment.due_amount

                total_payment_count = len(loan.prefetch_total_payment_count)

                paid_payment_count = len(loan.prefetch_total_paid_payment_count)

                if loan.status == LoanStatusCodes.PAID_OFF:
                    last_payment = loan.prefetch_payment_set[-1]
                    paid_off_date = last_payment.paid_date
                else:
                    paid_off_date = '-'

                loan_results.append({
                    "loan_xid": loan.loan_xid,
                    "start_pay": first_payment.due_date.strftime("%d %b %Y") if first_payment else '-',
                    "remaining_payment": total_due_amount,
                    "daily_payment": loan.installment_amount,
                    "status": loan.loan_status_label if loan.loan_status_label else "Sedang diproses",
                    "successful_payment": str(paid_payment_count) + " dari " + str(
                        total_payment_count),
                    "application_date": loan.cdate.strftime("%d %b %Y"),
                    "loan_amount": loan.loan_amount,
                    "loan_duration": loan.loan_duration,
                    "paid_off_date": paid_off_date.strftime(
                        "%d %b %Y") if paid_off_date != '-' else paid_off_date,
                    "interest_rate": (loan.product.interest_rate * 100),
                    "loan_status_code": loan.status
                })

        if status_loan:
            status_loan_label = status_loan.loan_status_label if \
                status_loan.loan_status_label else "Sedang diproses"
        else:
            status_loan_label = '-'

        if oldest_payments_due_amount:
            due_amount = oldest_payments_due_amount
            due_date_in = '{} hari'.format(days_in_dpd)
        else:
            due_amount = '-'
            due_date_in = '-'

        response = {
            "status": status_loan_label,
            "amount": due_amount,
            "due_date_in": due_date_in,
            "loans": loan_results
        }

        return response

    @staticmethod
    def get_loan_payments(loan_xid):

        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            raise GrabLogicException("Loan not found for loan xid {}".format(loan_xid))

        total_due_amount = Payment.objects.filter(
            loan=loan,
            payment_status__status_code__lt=PaymentStatusCodes.PAID_ON_TIME) \
            .aggregate(Sum('due_amount'))

        total_payment_count = Payment.objects.filter(
            loan=loan).count()

        paid_payment = Payment.objects.filter(
            loan=loan,
            payment_status__status_code__gte=PaymentStatusCodes.PAID_ON_TIME
        ).order_by('id')

        payments = []

        for payment in paid_payment:
            payments.append({
                "paid_date": payment.paid_date.strftime("%d %b %Y"),
                "paid_amount": payment.paid_amount,
                "due_date": payment.due_date.strftime("%d %b %Y")
            })

        response = {
            "loan_xid": loan.loan_xid,
            "remaining_payment": total_due_amount["due_amount__sum"],
            "successful_payment": str(paid_payment.count()) + " dari " + str(total_payment_count),
            "payments": payments,
            "total_payments_paid": paid_payment.aggregate(Sum('paid_amount'))['paid_amount__sum']
        }

        return response

    @staticmethod
    def get_loan_payment_detail(request, payment_id):

        payment = Payment.objects.get_or_none(id=payment_id)

        params = {
            "payment": payment
        }

        template = render(request, "loan_payment_detail.html", params)

        response = {"payment_detail_content": template.content}

        return response

    @staticmethod
    def get_loan_detail(loan_xid):

        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            raise GrabLogicException("Loan not found with loan_xid {}".format(loan_xid))

        first_payment = Payment.objects.filter(loan=loan).order_by('due_date').first()

        total_due_amount = Payment.objects.filter(
            loan=loan,
            payment_status__status_code__lt=PaymentStatusCodes.PAID_ON_TIME) \
            .aggregate(Sum('due_amount'))

        total_payment_count = Payment.objects.filter(
            loan=loan).count()

        paid_payment_count = Payment.objects.filter(
            loan=loan,
            payment_status__status_code__gte=PaymentStatusCodes.PAID_ON_TIME).count()

        grab_loan_data = GrabLoanData.objects.get_or_none(loan=loan)

        response = {
            "loan_xid": loan.loan_xid,
            "status": loan.loan_status_label if loan.loan_status_label else "Sedang diproses",
            "start_pay": first_payment.due_date.strftime("%d %b %Y") if first_payment else '-',
            "disbursed": loan.loan_disbursement_amount,
            "remaining_payment": total_due_amount["due_amount__sum"],
            "daily_repayment": loan.installment_amount,
            "successful_payment": str(paid_payment_count) + " dari " + str(total_payment_count)
        }

        return response

    @staticmethod
    def check_phone_number_change(customer, phone_number):
        grab_customer_data = GrabCustomerData.objects.get_or_none(
            grab_validation_status=True,
            otp_status=GrabCustomerData.VERIFIED,
            customer=customer
        )
        return_dict = {
            "already_registered_number": False,
            "valid_phone": False,
            "error_message": None
        }
        error_message_grab = "Nomor HP kamu tidak terdaftar di sistem Grab. Kamu " \
                             "bisa konfirmasi pergantian nomor HP ke Customer Service Julo"
        if Customer.objects.filter(
            phone__in=[format_nexmo_voice_phone_number(phone_number),
                       format_mobile_phone(phone_number)]
        ).exists() or Application.objects.filter(
            mobile_phone_1__in=[
                format_nexmo_voice_phone_number(phone_number),
                format_mobile_phone(phone_number)]
        ).exclude(customer=customer).exists() or GrabCustomerData.objects.filter(
            phone_number__in=[
                format_nexmo_voice_phone_number(phone_number),
                format_mobile_phone(phone_number)],
            grab_validation_status=True,
            customer__isnull=False
        ).exists() or Loan.objects.filter(
            account__account_lookup__workflow__name=WorkflowConst.GRAB,
            customer=customer,
            loan_status_id__in={
                LoanStatusCodes.LENDER_APPROVAL,
                LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
                LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                LoanStatusCodes.FUND_DISBURSAL_FAILED,
            }
        ).exists():
            return_dict["already_registered_number"] = True
            return_dict["valid_phone"] = False
            return_dict["error_message"] = error_message_grab
            return return_dict

        if grab_customer_data:
            grab_response = GrabClient.get_loan_offer(phone_number=phone_number,
                                                          customer_id=grab_customer_data.customer_id)
            if "error" in grab_response and 'message' in grab_response['error']:
                if "UserProfileNotFound" in grab_response["error"]["message"]:
                    return_dict['valid_phone'] = False
                    return_dict["error_message"] = "Nomor HP kamu tidak terdaftar di sistem Grab. " \
                                                   "Kamu bisa konfirmasi pergantian nomor HP ke " \
                                                   "Customer Service Grab."
                elif 'No loan offers found' in grab_response["error"]["message"]:
                    return_dict['valid_phone'] = True
            elif "data" in grab_response:
                return_dict['valid_phone'] = True
            return return_dict
        else:

            return_dict["error_message"] = error_message_grab
            return return_dict

    def get_payment_plans_v2(self, token, phone_number, program_id, tenure):

        grab_customer_data = GrabCustomerData.objects.get_or_none(phone_number=phone_number,
                                                                  grab_validation_status=True,
                                                                  token=token,
                                                                  otp_status=GrabCustomerData.VERIFIED)

        if grab_customer_data:
            grab_loan_offer = self.get_grab_loan_offer_data(
                grab_customer_data_id=grab_customer_data.id,
                program_id=program_id
            )

            if not grab_loan_offer:
                raise GrabLogicException("You are not eligible for getting payment plans.")

            response = []

            list_of_tenure_duration = list(range(
                grab_loan_offer.min_tenure,
                grab_loan_offer.tenure + 1,
                grab_loan_offer.tenure_interval)
            )

            interest_rate = grab_loan_offer.interest_value
            upfront_fee = grab_loan_offer.fee_value
            offer_threshold = grab_loan_offer.weekly_installment_amount
            min_loan_amount = grab_loan_offer.min_loan_amount
            max_loan_amount = grab_loan_offer.max_loan_amount

            if tenure not in list_of_tenure_duration:
                raise GrabLogicException("Invalid tenure")

            # generate 6 loan amounts based from max and min loan amount
            # round the amounts to nearest 50k
            # calculate daily installment for each loan amount, and tenure
            # validates by daily offer threshold
            daily_offer_threshold = int(offer_threshold / 7)
            loan_multiplications = [0, 0.2, 0.4, 0.6, 0.8, 1]
            for multiplication in loan_multiplications:
                loan_amount = (max_loan_amount - min_loan_amount) * multiplication + min_loan_amount
                loan_amount = GrabUtils.roundup_loan_amount_to_by_multiplication(loan_amount)

                if min_loan_amount > loan_amount:
                    continue

                for tenure_duration in list_of_tenure_duration:
                    interest_value = interest_rate / 100  # to apply percentage real value
                    total_installment_with_interest = loan_amount + (
                        loan_amount
                        * interest_value
                        * tenure_duration
                        / GrabExperimentConst.DAYS_OF_MONTH
                    )
                    daily_installment = float(math.ceil(total_installment_with_interest / tenure_duration))
                    if daily_installment > daily_offer_threshold:
                        continue
                    response.append(
                        {
                            "tenure": tenure_duration,
                            "daily_repayment": daily_installment,
                            "repayment_amount": math.ceil(total_installment_with_interest),
                            "loan_disbursement_amount": loan_amount - upfront_fee,
                            "weekly_instalment_amount": daily_installment * 7,
                            "loan_amount": loan_amount,
                        }
                    )

            # Sorting logic:
            # 1. Max tenure, max loan amount
            # 2. The Rest of the loan options sorted by loan amount and loan tenure decremental
            response = sorted(response, key=itemgetter('loan_amount', 'tenure'))
            response = response[:1] + response[1:]
            return response
        else:
            raise GrabLogicException("You are not eligible for getting payment plans.")

    @staticmethod
    def record_payment_plans(grab_customer_data_id, program_id, payment_plans):
        try:
            grab_payment_plan_obj = GrabPaymentPlans.objects.filter(
                grab_customer_data_id=grab_customer_data_id
            ).last()
            if grab_payment_plan_obj:
                grab_payment_plan_obj.update_safely(
                    program_id=program_id, payment_plans=json.dumps(payment_plans)
                )
            else:
                GrabPaymentPlans.objects.create(
                    grab_customer_data_id=grab_customer_data_id,
                    program_id=program_id,
                    payment_plans=json.dumps(payment_plans),
                )
        except IntegrityError as err:
            logger.exception({"action": "record_payment_plans", "error_message": err})

    @staticmethod
    def is_payment_plan_exist(grab_customer_data_id: int, request_data: dict):
        """
        Get payment plan list from db and compare from request data
        """
        default_payment_plan = {}
        grab_payment_plans_obj = GrabPaymentPlans.objects.filter(
            grab_customer_data_id=grab_customer_data_id, program_id=request_data.get('program_id')
        ).last()
        if not grab_payment_plans_obj or not grab_payment_plans_obj.payment_plans:
            return False, default_payment_plan

        list_of_payment_plan = json.loads(grab_payment_plans_obj.payment_plans)
        for payment_plan in list_of_payment_plan:
            if request_data.get('total_repayment_amount_plan') == payment_plan.get(
                'repayment_amount'
            ) and request_data.get('tenure_plan') == payment_plan.get('tenure'):
                return True, payment_plan
        return False, default_payment_plan


class GrabAPIService(object):

    @staticmethod
    def get_account_summary(loan_xid, application_xid, offset, limit):
        response = []
        if loan_xid:
            loans = get_loans(loan_xid=loan_xid)
            if not loans:
                raise GrabLogicException(
                    "Grab Application not found for loan xid {}".format(loan_xid)
                )
            response = generate_response_account_summary(loans)
        elif application_xid:
            loans = get_loans(application_xid)
            if not loans:
                raise GrabLogicException(
                    "Grab Application not found for application_xid {}".format(application_xid)
                )
            response = generate_response_account_summary(loans)
        else:
            response = generate_response_account_summary_by_offset_limit(
                int(offset), int(limit)
            )

        return {
            "count": len(response),
            "currency": "IDR",
            "rows": response
        }

    @staticmethod
    def add_repayment(
            application_xid, loan_xid, deduction_reference_id, event_date,
            deduction_amount, txn_id=None):

        loan = Loan.objects.filter(
            loan_xid=loan_xid,
            loan_status__lt=LoanStatusCodes.PAID_OFF
        ).exclude(loan_status=LoanStatusCodes.HALT).last()
        if not loan:
            raise GrabLogicException("No Active Loan found for xid {}".format(loan_xid))

        account = loan.account

        payback_transaction = PaybackTransaction.objects.get_or_none(
            transaction_id=deduction_reference_id)
        if payback_transaction:
            outstanding_principal, outstanding_interest, outstanding_late_fee = \
                track_payment_details_based_on_txn_id(loan, deduction_reference_id)
            weekly_instalment_amount = get_weekly_installment_amount_txn_simple(
                loan)
            principal_settled = get_principal_settled_grab(loan, txn_id=deduction_reference_id)
            response = {
                "principal_outstanding": int(outstanding_principal),
                "interest_outstanding": int(outstanding_interest),
                "fee_outstanding": int(outstanding_late_fee),
                "penalty_outstanding": 0.00,
                "weekly_instalment_amount": weekly_instalment_amount,
                "principal_settled": int(principal_settled)
            }
            return response

        application = Application.objects.get_or_none(application_xid=application_xid)
        if not application:
            raise GrabLogicException("Application not found for xid {}".format(application_xid))

        with transaction.atomic():
            payment_transaction, data, note = record_payback_transaction_grab(
                event_date, deduction_amount, application_xid,
                loan_xid, deduction_reference_id, txn_id)
            _, principal_settled = grab_payment_process_account(
                payment_transaction, data, note, grab_txn_id=deduction_reference_id)
            weekly_instalment_amount = get_weekly_installment_amount_txn_simple(
                loan)

        response = {
            "principal_outstanding": loan.get_outstanding_principal(),
            "interest_outstanding": loan.get_outstanding_interest(),
            "fee_outstanding": loan.get_outstanding_late_fee(),
            "penalty_outstanding": 0.00,
            "weekly_instalment_amount": weekly_instalment_amount,
            "principal_settled": principal_settled
        }
        add_account_in_temp_table(loan)
        return response

    @staticmethod
    def application_validate_referral_code(customer, referral_code):
        validation_status = grab_check_valid_referal_code(referral_code)
        error_message = ''
        if not validation_status:
            error_message = 'Kode referral tidak terdaftar. Silakan ' \
                            'masukkan kode referral lainnya.'
        return {
            "referral_code": referral_code.upper(),
            "validation_status": validation_status,
            "error_message": error_message
        }

    @staticmethod
    def application_status_check(customer):

        if not customer:
            raise GrabLogicException("ID grab Anda aktif")
        grab_customer = GrabCustomerData.objects.filter(customer=customer).last()
        account_data = None
        loan_data = None

        if not grab_customer:
            raise GrabLogicException("ID grab Anda aktif")

        application_set = customer.application_set.all()
        if application_set.filter(workflow__name=WorkflowConst.GRAB).exists():
            application = application_set.filter(workflow__name=WorkflowConst.GRAB).last()
        else:
            application = application_set.last()
        if not application and application.customer != customer:
            raise GrabLogicException("Grab Application not Found for customer id {}".format(customer.id))

        account = application.account
        if account:
            account_data = {'account_id': account.id}

        return_dict = {
            "application": {
                "application_id": application.id,
                "application_status": application.status
            },
            "account": account_data,
            "loan": loan_data,
            "customer_name": application.fullname,
            "grab_token": grab_customer.token,
            "phone_number": grab_customer.phone_number,
            "reapply_application": None,
            "activate_190_loan": True,
            "activate_loan_button": False,
            "ecc_reject": False,
        }
        activate_button = False
        if application.is_kin_approved == EmergencyContactConst.CONSENT_REJECTED:
            return_dict['ecc_reject'] = True

        if application.status == ApplicationStatusCodes.LOC_APPROVED and application.account:
            loan = Loan.objects.filter(
                account=application.account
            ).last()
            app_history_190 = application.applicationhistory_set.filter(
                status_new=ApplicationStatusCodes.LOC_APPROVED)
            time_delay_in_minutes = datetime.timedelta(minutes=TIME_DELAY_IN_MINUTES_190)
            if app_history_190.exists() and (
                    timezone.localtime(timezone.now()) - app_history_190.last().cdate
            ) < time_delay_in_minutes:
                return_dict['activate_190_loan'] = False
            else:
                return_dict['activate_190_loan'] = True
            if loan:
                if loan.status in {
                    LoanStatusCodes.GRAB_AUTH_FAILED, LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                    LoanStatusCodes.SPHP_EXPIRED, LoanStatusCodes.LENDER_REJECT,
                    LoanStatusCodes.PAID_OFF, LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
                    LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.TRANSACTION_FAILED, LoanStatusCodes.HALT
                }:
                    if loan.status not in {
                        LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
                        LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.HALT
                    }:
                        activate_button = True and return_dict['activate_190_loan']
                    else:
                        grab_api_logs = GrabAPILog.objects.filter(
                            loan_id=loan.id).filter(
                            Q(query_params__contains=GrabPaths.LOAN_CREATION) |
                            Q(query_params__contains=GrabPaths.DISBURSAL_CREATION)
                        )

                        # Auth Check
                        auth_log = grab_api_logs.filter(
                            query_params__contains=GrabPaths.LOAN_CREATION,
                            http_status_code=https_status_codes.HTTP_200_OK
                        ).exists()
                        capture_log = grab_api_logs.filter(
                            Q(query_params__contains=GrabPaths.DISBURSAL_CREATION),
                            http_status_code=https_status_codes.HTTP_200_OK
                        ).exists()
                        if auth_log and capture_log:
                            activate_button = True and return_dict['activate_190_loan']

                return_dict['loan'] = {"loan_xid": loan.loan_xid,
                                       "status": loan.status,
                                       "loan_id": loan.id}
            else:
                activate_button = True and return_dict['activate_190_loan']

        # disable "ajukan pinjaman" button
        if FeatureSetting.objects.filter(feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
                                         is_active=True).exists():
            activate_button = False

        if grab_customer.is_customer_blocked_for_loan_creation:
            activate_button = False

        return_dict['activate_loan_button'] = activate_button
        reapply_flag = True
        application_100_reapply_flag = False
        last_application = None
        if application.status in graveyard_statuses or \
                application.status == ApplicationStatusCodes.FORM_CREATED:
            application_count = customer.application_set.count()
            if application_count > 1 and application.status == ApplicationStatusCodes.FORM_CREATED:
                last_application = customer.application_set.order_by('-cdate')[1]
                if last_application.status in graveyard_statuses and \
                        application.status == ApplicationStatusCodes.FORM_CREATED:
                    application_100_reapply_flag = True
            if can_reapply_application_grab(application.customer) \
                    or application_100_reapply_flag:
                if application_100_reapply_flag:
                    application = last_application
                serializer = GrabApplicationSerializer(application)
                data = serializer.data
                data['ktp'] = customer.nik
                for i in GRAB_IMAGE_TYPES:
                    data[i] = None
                images = Image.objects.filter(image_type__in=GRAB_IMAGE_TYPES, image_source=application.id)
                for image in images:
                    data[image.image_type] = image.image_url_api
                return_dict['reapply_application'] = data
        if application.status == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
            """
                For application 131, get the required image type and text and passing to front end
            """
            app_history = ApplicationHistory.objects.filter(
                application_id=application.id,
                status_new=application.application_status_id
            ).last()
            return_dict["document_resubmission_image_list"] = []
            return_dict["document_resubmission_message"] = []
            if not app_history:
                logger.warning('grab_application_status_error|err=missing_application_'
                               'history_for_application_{}'.format(application.id))
                return return_dict
            image_types = list()
            change_reason = app_history.change_reason
            change_reason_split = change_reason.split(',')
            IMAGE_MAPPING = {
                'ktp_self': 'ktp',
                'drivers_license_ops': 'sim',
                'Foto NPWP': 'npwp'
            }
            image_flag = dict()
            image_flag['ktp'] = False
            image_flag['sim'] = False
            image_flag['npwp'] = False
            image_rank_list = []
            base_message = 'Upload ulang {filler}. Pastikan foto Dokumen ' \
                           'dan Selfie terlihat jelas.'
            general_error_message = "Mohon cek email Anda untuk mengirim dokumen yang diperlukan."
            # Iterate through the change reasons split using , and remove empty values
            change_reason_split = [value for value in change_reason_split if value.strip()]

            # If selfie exist with other change reasons, the behaviour is to use the other change reason as primary
            if ('Selfie needed' in change_reason_split or 'Selfie blurry' in change_reason_split) and \
                    len(change_reason_split) > 1:
                change_reason_split = [value for value in change_reason_split
                                       if value.strip() not in ("Selfie blurry", "Selfie needed")]

            # To improve time complexity
            image_types_set = set()
            # Iterate through the change reasons split using ,
            for change_reason_iter in change_reason_split:
                change_reason_split = change_reason_iter.strip()
                if change_reason_split in {'KTP blurry', 'KTP needed',
                                           'Selfie needed', 'Selfie blurry'}:

                    if 'ktp_self' not in image_types_set:
                        image_types.append('ktp_self')
                        image_types_set.add('ktp_self')
                    image_rank_list.append(0)  # Set Rank 0
                    image_flag['ktp'] = True
                elif change_reason_split == 'SIM needed':
                    if 'drivers_license_ops' not in image_types_set:
                        image_types.append('drivers_license_ops')
                        image_types_set.add('drivers_license_ops')
                    image_rank_list.append(1)  # Set Rank 1
                    image_flag['sim'] = True
                elif change_reason_split == 'NPWP needed':
                    if 'Foto NPWP' not in image_types_set:
                        image_types.append('Foto NPWP')
                        image_types_set.add('Foto NPWP')
                    image_rank_list.append(1)  # Set Rank 1
                    image_flag['npwp'] = True

            # Sort based on image_rank priority(Descending order)
            image_sort = sorted(zip(image_rank_list, image_types), reverse=True)
            image_types = [image_type for _, image_type in image_sort]

            filler_message = []
            # Filler message order set here
            for image_type in image_types:
                if image_flag[IMAGE_MAPPING[image_type]]:
                    filler_message.append(IMAGE_MAPPING[image_type].upper())

            final_image_list = []
            for image_type in image_types:
                data = dict()
                data['image_type'] = image_type
                data['text'] = IMAGE_MAPPING[image_type].upper()
                final_image_list.append(data)
            if filler_message:
                filler_message = r" / ".join(filler_message)
                message = base_message.format(filler=filler_message)
            else:
                message = general_error_message
            return_dict["document_resubmission_image_list"] = final_image_list
            return_dict["document_resubmission_message"] = message

        return return_dict

    @staticmethod
    def get_grab_home_page_data(hashed_phone_number, offset, limit):
        applied_amount = 0
        grab_customer_data = GrabCustomerData.objects.filter(
            customer__isnull=False,
            hashed_phone_number=hashed_phone_number
        ).last()
        if not grab_customer_data:
            raise GrabLogicException('No grab customers Found with this phone number')

        customer = grab_customer_data.customer
        applications = customer.application_set.select_related('application_status').filter(
            workflow__name=WorkflowConst.GRAB)
        if not applications.exists():
            raise GrabLogicException('No grab Application Found with this phone number')
        grab_loan_inquiry = grab_customer_data.grabloaninquiry_set.last()
        if grab_loan_inquiry:
            grab_loan_data = grab_loan_inquiry.grabloandata_set.last()
            if grab_loan_data:
                applied_amount = grab_loan_data.selected_amount

        last_application = applications.last()
        application_data = dict()
        application_data['application_id'] = last_application.application_xid
        application_data['applied_amount'] = applied_amount
        application_data['status'] = GrabRequestDataConstructor.\
            get_application_status_grab(last_application)
        application_data['metadata'] = {
            'rejected_reason': get_reject_reason_for_application(last_application),
            'expiry_date': get_expiry_date_grab(last_application),
            'application_start_date': last_application.cdate.strftime("%Y-%m-%d")
        }

        loan_entities = []
        account = last_application.account
        loan_entity_count = 0
        if account:
            loans, loan_entity_count = get_loan_details_grab_offset(account.id, offset, limit)
            for loan in loans:
                total_due_amount = 0
                if len(loan.total_outstanding_due_amounts) > 0:
                    total_due_amount = sum(
                        [payment.due_amount for payment in loan.total_outstanding_due_amounts]
                    )
                total_paid_amount = 0
                if len(loan.total_paid_amount) > 0:
                    total_paid_amount = sum(
                        [payment.paid_amount for payment in loan.total_paid_amount]
                    )
                total_outstanding_amount = 0
                if len(loan.total_outstanding_amounts) > 0:
                    total_outstanding_amount = sum(
                        [payment.due_amount for payment in loan.total_outstanding_amounts]
                    )
                individual_loan = dict()
                individual_loan['application_id'] = last_application.application_xid
                individual_loan['loan_id'] = loan.loan_xid
                individual_loan['dpd'] = loan.dpd
                individual_loan['total_outstanding_amount'] = total_outstanding_amount
                individual_loan['total_due_amount'] = total_due_amount
                individual_loan['loan_amount'] = loan.loan_amount
                individual_loan['amount_paid'] = total_paid_amount
                individual_loan['loan_duration'] = loan.loan_duration
                individual_loan['loan_status_id'] = loan.loan_status.status
                individual_loan['description'] = loan.grab_loan_description
                individual_loan['disbursement_date'] = loan.disbursement_date.strftime("%Y-%m-%d") if \
                    loan.disbursement_date else None
                loan_entities.append(individual_loan)

        return_data = dict()
        return_data['LoanApplication'] = [application_data]
        return_data['loan_entities'] = list(loan_entities)
        return_data['loan_entity_count'] = loan_entity_count
        return return_data


def generate_response_account_summary(loans):
    response = []
    is_early_write_off, is_180_dpd_write_off, is_manual_write_off = \
        get_grab_write_off_feature_setting()
    for loan in loans:
        application = loan.account.applications[0]
        dpd = 0
        if len(loan.grab_oldest_unpaid_payments) > 0:
            dpd = loan.grab_oldest_unpaid_payments[0].get_grab_dpd

        last_unpaid_payment_due_date = None
        if len(loan.grab_last_unpaid_payments) > 0:
            last_unpaid_payment_due_date = loan.grab_last_unpaid_payments[0].due_date

        total_due_amount = 0
        if len(loan.total_outstanding_due_amounts) > 0:
            total_due_amount = sum(
                [payment.due_amount for payment in loan.total_outstanding_due_amounts]
            )
            if loan.grab_loan_data_set[0].is_repayment_capped:
                installment_amount = loan.installment_amount
                current_date_transactions = loan.current_date_transactions
                total_paid_today = 0
                for current_date_transaction in current_date_transactions:
                    total_paid_today += current_date_transaction.amount
                if total_due_amount >= installment_amount:
                    total_due_amount = installment_amount - total_paid_today
                    if total_due_amount < 0:
                        total_due_amount = 0

        total_outstanding_amount = 0
        if len(loan.total_outstanding_amounts) > 0:
            total_outstanding_amount = sum(
                [payment.due_amount for payment in loan.total_outstanding_amounts]
            )

        admin_fee = 0
        if loan.product.admin_fee:
            admin_fee = loan.product.admin_fee
        loan_status = get_account_summary_loan_status(
            loan, is_early_write_off, is_180_dpd_write_off, is_manual_write_off, dpd)

        response.append(
            {
                "application_xid": int(application.application_xid),
                "loan_xid": loan.loan_xid,
                "dpd": dpd,
                "total_due_amount": total_due_amount,
                "total_outstanding_amount": total_outstanding_amount,
                "loan_amount": loan.loan_amount,
                "loan_duration": loan.loan_duration,
                "payment_details": format_payment_account_summary(loan),
                "loan_status_id": loan_status,
                "loan_origination": format_get_loan_origination(loan),
                "total_interest_waived": 0,
                "total_penalty_waived": 0,
                "next_due_date": last_unpaid_payment_due_date,
                "next_due_date_timezone": "IDN",
                "admin_fee": admin_fee,
                "disbursement_date": loan.fund_transfer_ts if loan.fund_transfer_ts else None
            }
        )

    return response


def generate_response_account_summary_by_offset_limit(offset, limit):
    response = []
    is_early_write_off, is_180_dpd_write_off, is_manual_write_off = \
        get_grab_write_off_feature_setting()
    for loan in get_loans_based_on_grab_offset_v2(offset, limit):
        if len(loan.account.applications) < 1:
            raise GrabLogicException("Grab Account doesn't have application")
        application = loan.account.applications[0]
        dpd = 0
        if len(loan.grab_oldest_unpaid_payments) > 0:
            dpd = loan.grab_oldest_unpaid_payments[0].get_grab_dpd

        last_unpaid_payment_due_date = None
        if len(loan.grab_last_unpaid_payments) > 0:
            last_unpaid_payment_due_date = loan.grab_last_unpaid_payments[0].due_date

        total_due_amount = 0
        if len(loan.total_outstanding_due_amounts) > 0:
            total_due_amount = sum(
                [payment.due_amount for payment in loan.total_outstanding_due_amounts]
            )
            if loan.grab_loan_data_set[0].is_repayment_capped:
                installment_amount = loan.installment_amount
                current_date_transactions = loan.current_date_transactions
                total_paid_today = 0
                for current_date_transaction in current_date_transactions:
                    total_paid_today += current_date_transaction.amount
                if total_due_amount >= installment_amount:
                    total_due_amount = installment_amount - total_paid_today
                    if total_due_amount < 0:
                        total_due_amount = 0

        total_outstanding_amount = 0
        if len(loan.total_outstanding_amounts) > 0:
            total_outstanding_amount = sum(
                [payment.due_amount for payment in loan.total_outstanding_amounts]
            )

        admin_fee = 0
        if loan.product.admin_fee:
            admin_fee = loan.product.admin_fee
        loan_status = get_account_summary_loan_status(
            loan, is_early_write_off, is_180_dpd_write_off, is_manual_write_off, dpd)
        response.append(
            {
                "application_xid": int(application.application_xid),
                "loan_xid": loan.loan_xid,
                "dpd": dpd,
                "total_due_amount": total_due_amount,
                "total_outstanding_amount": total_outstanding_amount,
                "loan_amount": loan.loan_amount,
                "loan_duration": loan.loan_duration,
                "payment_details": format_payment_account_summary(loan),
                "loan_status_id": loan_status,
                "loan_origination": format_get_loan_origination(loan),
                "total_interest_waived": 0,
                "total_penalty_waived": 0,
                "next_due_date": last_unpaid_payment_due_date,
                "next_due_date_timezone": "IDN",
                "admin_fee": admin_fee,
            }
        )

    return response


class GrabAccountPageService(object):
    @staticmethod
    def get_account_page_response(customer):
        grab_customer = GrabCustomerData.objects.filter(customer=customer).last()
        if not grab_customer:
            raise GrabLogicException(GrabUtils.create_error_message(
                GrabErrorCodes.GAP_ERROR_CODE.format('1'),
                GrabErrorMessage.PROFILE_PAGE_GENERAL_ERROR_MESSAGE
            ))

        application = customer.application_set.last()
        if not application:
            raise GrabLogicException(GrabUtils.create_error_message(
                GrabErrorCodes.GAP_ERROR_CODE.format('2'),
                GrabErrorMessage.PROFILE_PAGE_GENERAL_ERROR_MESSAGE
            ))

        serializer = GrabAccountPageSerializer(customer, many=False)
        data = serializer.data
        bank = Bank.objects.filter(
            bank_name=application.bank_name
        ).last()
        if bank:
            data['bank_logo'] = bank.bank_logo

        data['bank_account_number'] = application.bank_account_number
        return data

    @staticmethod
    def process_verify_pin_response(customer, pin):
        response = {
            'verified_status': False,
            'locked': False,
            'message': ''
        }
        if not pin_services.does_user_have_pin(customer.user):
            response['message'] = 'User ini tidak mempunyai PIN'
            return response

        verify_pin_service = pin_services.VerifyPinProcess()
        status_code, message, _ = verify_pin_service.verify_pin_process(
            view_name='CheckCurrentPin', user=customer.user, pin_code=pin, android_id=None
        )
        if status_code != ReturnCode.OK:
            if status_code == ReturnCode.LOCKED:
                response['message'] = message
                response['locked'] = True
                return response
            elif status_code == ReturnCode.FAILED:
                response['message'] = message
                return response

        response['verified_status'] = True
        response['message'] = message
        return response

    @staticmethod
    def process_update_pin_response(customer, current_pin, new_pin):
        response = {
            'updated_status': False,
            'message': ''
        }
        if not pin_services.does_user_have_pin(customer.user):
            response['message'] = 'User ini tidak mempunyai PIN'
            return response

        # check if new pin is same as current pin
        if GrabAccountPageService.validate_pin(customer, new_pin):
            response['message'] = 'Pastikan PIN Baru Kamu tidak sama dengan PIN lama'
            return response

        # check if current pin is correct
        if not GrabAccountPageService.validate_pin(customer, current_pin):
            response['message'] = 'PIN tidak sesuai silahkan coba lagi'
            return response

        status, message = pin_services.process_change_pin(customer.user, new_pin)
        response['updated_status'] = status
        response['message'] = message
        return response

    @staticmethod
    def validate_pin(customer, current_pin) -> bool:
        valid = customer.user.check_password(current_pin)
        return valid

    @staticmethod
    def check_and_generate_referral_code(customer, is_creation_flag=False):
        """
            Is_creation_flag -- if active will generate the referrel code if not present
        """
        referral_code = None
        start_time = None
        total_cashback = 0
        max_whitelist = 0
        referrer_incentive = 0
        referred_incentive = 0
        logger.info({
            "service": "check_and_generate_referral_code",
            "action": "validating_referal_code_started"
        })
        valid = GrabAccountPageService.validate_generate_referral(customer)
        if valid:
            current_active_whitelist_program = \
                GrabReferralWhitelistProgram.objects.filter(is_active=True).last()
            if customer.self_referral_code:
                referral_code = customer.self_referral_code
                if is_creation_flag:
                    return valid, referral_code, total_cashback
                start_time = timezone.localtime(
                    current_active_whitelist_program.start_time)

                referred_account_list = GrabReferralCode.objects.filter(
                    referred_customer=customer,
                    application__application_status_id=ApplicationStatusCodes.LOC_APPROVED,
                    cdate__gte=start_time
                ).values_list('application__account_id', flat=True)

                if len(referred_account_list) > 0:
                    active_loans_account_ids = Loan.objects.filter(
                        account_id__in=referred_account_list,
                        loan_status_id__in=set(LoanStatusCodes.grab_current_until_180_dpd() +
                                               (LoanStatusCodes.PAID_OFF,))
                    ).values_list('account_id', flat=True)
                else:
                    active_loans_account_ids = []

                num_app_referred = len(set(active_loans_account_ids))
                actual_referral_app_count = num_app_referred
                feature_setting = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.GRAB_REFERRAL_PROGRAM, is_active=True).last()
                if feature_setting:
                    # Feature setting to limit max per whitelist
                    max_whitelist = feature_setting.parameters['max incentivised referral/whitelist']
                    referrer_incentive = feature_setting.parameters['referrer_incentive']
                    referred_incentive = feature_setting.parameters['referred_incentive']
                    if int(num_app_referred) > int(max_whitelist):
                        actual_referral_app_count = int(max_whitelist)
                total_cashback = actual_referral_app_count * referrer_incentive
            else:
                if is_creation_flag:
                    referral_code = generate_grab_referral_code(customer)
                    customer.update_safely(self_referral_code=referral_code)
        logger.info({
            "service": "check_and_generate_referral_code",
            "action": "validating_referal_code_started"
        })
        return valid, referral_code, total_cashback, start_time.strftime("%m-%d-%Y, %H:%M:%S") if \
            start_time else None, int(max_whitelist), referrer_incentive, referred_incentive

    @staticmethod
    def validate_generate_referral(customer) -> bool:
        logger.info({
            "service": "validate_generate_referral",
            "action": "validating_referal_code_started"
        })
        is_have_active_loan = customer.loan_set.filter(
            loan_status_id__in=set(LoanStatusCodes.grab_current_until_180_dpd() +
                                   (LoanStatusCodes.PAID_OFF,))).exists()
        current_active_whitelist_program = GrabReferralWhitelistProgram.objects.filter(
            is_active=True).last()
        if not current_active_whitelist_program:
            is_whitelisted = False
        else:
            is_whitelisted = GrabCustomerReferralWhitelistHistory.objects.filter(
                customer=customer,
                grab_referral_whitelist_program=current_active_whitelist_program
            ).exists()
        logger.info({
            "service": "validate_generate_referral",
            "action": "validating_referal_code_ended",
            "customer": customer,
            "is_have_active_loan": is_have_active_loan,
            "is_whitelisted": is_whitelisted
        })
        return is_have_active_loan and is_whitelisted

    @staticmethod
    def get_user_application_details(customer):
        grab_customer_data = GrabCustomerData.objects.get_or_none(
            customer=customer,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True
        )
        if not grab_customer_data:
            raise GrabLogicException(GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('1'),
                GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE
            ))

        application = customer.application_set.last()
        if not application:
            raise GrabLogicException(GrabUtils.create_error_message(
                GrabErrorCodes.GAX_ERROR_CODE.format('3'),
                GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE
            ))
        if application.application_status_id == ApplicationStatusCodes.APPLICATION_DENIED:
            application_history = application.applicationhistory_set.filter(
                status_new=ApplicationStatusCodes.APPLICATION_DENIED
            ).last()
            if not (application_history and
                    'bank account not under own name' in application_history.change_reason.strip()):
                raise GrabLogicException(GrabUtils.create_error_message(
                    GrabErrorCodes.GAX_ERROR_CODE.format('10'),
                    GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE
                ))
        else:
            if application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
                raise GrabLogicException(GrabUtils.create_error_message(
                    GrabErrorCodes.GAX_ERROR_CODE.format('10'),
                    GrabErrorMessage.BANK_VALIDATION_GENERAL_ERROR_MESSAGE
                ))

        return application

    @staticmethod
    def get_user_bank_account_details(customer):
        application = GrabAccountPageService().get_user_application_details(customer)
        fullname = application.name_in_bank
        if not fullname:
            fullname = application.fullname

        data = {
            'banks': DropDownData(DropDownData.BANK).select_data(),
            'bank_name': application.bank_name,
            'bank_account_number': application.bank_account_number,
            'fullname': fullname
        }
        return data


def format_payment_account_summary(loan):
    return_list = []
    total_principal_amount = 0
    total_interest_amount = 0
    total_late_fees = 0
    for payment in loan.prefetch_payments:
        total_interest_amount += payment.installment_interest
        total_late_fees += payment.late_fee_amount
        total_principal_amount += payment.installment_principal

        date_today = timezone.localtime(timezone.now()).date()
        installment_amount = payment.installment_principal + payment.installment_interest
        installment_paid = payment.paid_principal + payment.paid_interest
        installment_overdue = installment_amount - installment_paid if \
            payment.due_date < date_today else 0

        payment_details = {
            "installment_number": payment.payment_number,
            "installment_dpd": payment.get_grab_dpd if payment.due_amount else 0,
            "installment_due_date": payment.due_date.strftime("%Y-%m-%d"),
            "installment_due_date_timezone": "IDN",
            "installment_amount": installment_amount,
            "installment_paid": installment_paid,
            "installment_overdue": installment_overdue,
            "installment_status": payment.payment_status.status,
            "principal_amount": payment.installment_principal,
            "principal_paid": payment.paid_principal,
            "principal_overdue": payment.installment_principal - payment.paid_principal if
            payment.due_date < date_today else 0,
            "interest_amount": payment.installment_interest,
            "interest_paid": payment.paid_interest,
            "interest_overdue": payment.installment_interest - payment.paid_interest if
            payment.due_date < date_today else 0,
            "interest_waived": 0,
            "fee_amount": 0,
            "fee_paid": 0,
            "fee_overdue": 0,
            "penalty_amount": payment.late_fee_amount,
            "penalty_paid": payment.paid_late_fee,
            "penalty_overdue": payment.late_fee_amount - payment.paid_late_fee if
            payment.due_date < date_today else 0,
            "penalty_waived": 0,
            "txns": [transaction.transaction_id for transaction in payment.transaction_ids],
        }
        return_list.append(payment_details)

    """
        set the sum of values for each loan object
        and the temporary attributes will be called in function format_get_loan_origination
    """
    setattr(loan, 'total_principal_amount', total_principal_amount)
    setattr(loan, 'total_interest_amount', total_interest_amount)
    setattr(loan, 'total_late_fees', total_late_fees)

    return return_list


def calculate_payment_dpd(payment, loan):
    if not payment.due_date:
        return None
    if loan.status == LoanStatusCodes.HALT:
        grab_loan_data = loan.grab_loan_data_set[0]
        base_date = grab_loan_data.loan_halt_date
    else:
        base_date = timezone.localtime(timezone.now()).date()
    return (base_date - payment.due_date).days if payment.due_amount else 0


def format_get_loan_origination(loan):
    return loan.total_principal_amount + loan.total_interest_amount + loan.total_late_fees


def get_loans_based_on_grab_offset(offset, limit):
    account_ids = Account.objects.filter(account_lookup__workflow__name=WorkflowConst.GRAB) \
        .values_list('id', flat=True)
    loan_ids = Loan.objects.filter(account__id__in=account_ids).order_by('-cdate') \
        .values_list('id', flat=True)
    if not loan_ids:
        return []
    if offset + limit >= len(loan_ids):
        end_limit = len(loan_ids)
    else:
        end_limit = limit + offset
    if offset >= len(loan_ids):
        raise GrabLogicException("Offset Out of range")

    grab_payment_queryset = GrabPaymentTransaction.objects.only('id', 'transaction_id', 'payment_id').all()
    prefetch_grab_payments = Prefetch(
        'grabpaymenttransaction_set', queryset=grab_payment_queryset, to_attr='transaction_ids'
    )

    payment_queryset_fields = [
        'id', 'due_date', 'payment_status_id', 'late_fee_amount', 'paid_principal', 'paid_interest', 'payment_number',
        'due_amount', 'paid_late_fee', 'installment_principal', 'installment_interest', 'paid_principal',
        'paid_interest', 'loan_id'
    ]
    payment_queryset = Payment.objects.select_related('payment_status') \
        .prefetch_related(prefetch_grab_payments).only(*payment_queryset_fields).all().order_by('due_date')
    prefetch_payments = Prefetch('payment_set', to_attr="prefetch_payments", queryset=payment_queryset)

    last_unpaid_payment_queryset = Payment.objects.only('id', 'loan_id', 'due_date') \
        .not_paid_active().order_by('payment_number')
    prefetch_last_unpaid_payments = Prefetch('payment_set', to_attr="grab_last_unpaid_payments",
                                             queryset=last_unpaid_payment_queryset)

    oldest_unpaid_payments_queryset = Payment.objects.only('id', 'loan_id', 'due_date', 'payment_status_id') \
        .not_paid_active().order_by('due_date')
    prefetch_oldest_unpaid_payments = Prefetch('payment_set', to_attr="grab_oldest_unpaid_payments",
                                               queryset=oldest_unpaid_payments_queryset)

    total_outstanding_amount_queryset = Payment.objects.only('id', 'loan_id', 'due_amount').not_paid_active()
    prefetch_total_outstanding_amount = Prefetch('payment_set', to_attr="total_outstanding_amounts",
                                                 queryset=total_outstanding_amount_queryset)

    today = timezone.localtime(timezone.now()).date()
    total_outstanding_due_amount_queryset = Payment.objects.only('id', 'loan_id', 'due_amount', 'payment_status_id') \
        .not_paid_active().filter(due_date__lte=today)
    prefetch_total_outstanding_due_amount = Prefetch('payment_set', to_attr="total_outstanding_due_amounts",
                                                     queryset=total_outstanding_due_amount_queryset)
    loan_history_180_dpd_query_set = LoanHistory.objects.filter(status_new=LoanStatusCodes.LOAN_180DPD).order_by('pk')
    prefetch_loan_history_180_dpd = Prefetch('loanhistory_set', to_attr='loan_histories_180_dpd',
                                             queryset=loan_history_180_dpd_query_set)

    loan_history_from_180_dpd_query_set = LoanHistory.objects.only('cdate').filter(
        status_old=LoanStatusCodes.LOAN_180DPD).order_by('pk')
    prefetch_loan_history_from_180_dpd = Prefetch(
        'loanhistory_set', to_attr='loan_histories_from_180dpd', queryset=loan_history_from_180_dpd_query_set)

    prefetch_applications = Prefetch(
        'account__application_set', to_attr="applications",
        queryset=Application.objects.only('application_xid', 'id', 'account_id').all().order_by('-id')
    )
    prefetch_join_tables = [
        prefetch_applications,
        prefetch_payments,
        prefetch_last_unpaid_payments,
        prefetch_oldest_unpaid_payments,
        prefetch_total_outstanding_due_amount,
        prefetch_total_outstanding_amount,
        prefetch_loan_history_180_dpd,
        prefetch_loan_history_from_180_dpd
    ]

    only_fields = ['id', 'loan_status', 'loan_xid', 'loan_amount', 'loan_duration', 'account__status']
    return Loan.objects.select_related('account').prefetch_related(*prefetch_join_tables) \
               .only(*only_fields).filter(account__id__in=account_ids).order_by('-id')[offset: end_limit]


def get_loans_based_on_grab_offset_v2(offset, limit):
    grab_payment_queryset = GrabPaymentTransaction.objects.only('id', 'transaction_id', 'payment_id').all()
    prefetch_grab_payments = Prefetch(
        'grabpaymenttransaction_set', queryset=grab_payment_queryset, to_attr='transaction_ids'
    )

    payback_transaction_current_date_queryset = PaybackTransaction.objects.only(
        'id', 'loan_id', 'payback_service', 'amount',
        'is_processed', 'transaction_date').filter(
        transaction_date__date=timezone.localtime(timezone.now()).date(),
        is_processed=True,
        payback_service='grab'
    )
    prefetch_payback_transactions_current_date = Prefetch(
        'paybacktransaction_set', queryset=payback_transaction_current_date_queryset,
        to_attr='current_date_transactions'
    )

    payment_queryset_fields = [
        'id', 'due_date', 'payment_status_id', 'late_fee_amount', 'paid_principal', 'paid_interest', 'payment_number',
        'due_amount', 'paid_late_fee', 'installment_principal', 'installment_interest', 'paid_principal',
        'paid_interest', 'loan_id'
    ]
    payment_queryset = Payment.objects.select_related('payment_status') \
        .prefetch_related(prefetch_grab_payments).only(*payment_queryset_fields).all().order_by('due_date')
    prefetch_payments = Prefetch('payment_set', to_attr="prefetch_payments", queryset=payment_queryset)

    last_unpaid_payment_queryset = Payment.objects.only('id', 'loan_id', 'due_date') \
        .not_paid_active().order_by('payment_number')
    prefetch_last_unpaid_payments = Prefetch('payment_set', to_attr="grab_last_unpaid_payments",
                                             queryset=last_unpaid_payment_queryset)

    oldest_unpaid_payments_queryset = Payment.objects.only('id', 'loan_id', 'due_date', 'payment_status_id') \
        .not_paid_active().order_by('due_date')
    prefetch_oldest_unpaid_payments = Prefetch('payment_set', to_attr="grab_oldest_unpaid_payments",
                                               queryset=oldest_unpaid_payments_queryset)

    total_outstanding_amount_queryset = Payment.objects.only('id', 'loan_id', 'due_amount').not_paid_active()
    prefetch_total_outstanding_amount = Prefetch('payment_set', to_attr="total_outstanding_amounts",
                                                 queryset=total_outstanding_amount_queryset)

    today = timezone.localtime(timezone.now()).date()
    total_outstanding_due_amount_queryset = Payment.objects.only('id', 'loan_id', 'due_amount', 'payment_status_id') \
        .not_paid_active().filter(due_date__lte=today)
    prefetch_total_outstanding_due_amount = Prefetch('payment_set', to_attr="total_outstanding_due_amounts",
                                                     queryset=total_outstanding_due_amount_queryset)
    grab_loan_data_set = GrabLoanData.objects.only(
        'loan_halt_date', 'loan_resume_date', 'id', 'loan_id', 'is_repayment_capped')
    prefetch_grab_loan_data = Prefetch('grabloandata_set', to_attr='grab_loan_data_set',
                                       queryset=grab_loan_data_set)

    prefetch_applications = Prefetch(
        'account__application_set', to_attr="applications",
        queryset=Application.objects.only('application_xid', 'id', 'account_id').all().order_by('-id')
    )
    loan_history_180_dpd_query_set = LoanHistory.objects.filter(status_new=LoanStatusCodes.LOAN_180DPD
                                                                ).order_by('pk')
    prefetch_loan_history_180_dpd = Prefetch('loanhistory_set', to_attr='loan_histories_180_dpd',
                                             queryset=loan_history_180_dpd_query_set)

    loan_history_from_180_dpd_query_set = LoanHistory.objects.only('cdate').filter(
        status_old=LoanStatusCodes.LOAN_180DPD).order_by('pk')
    prefetch_loan_history_from_180_dpd = Prefetch(
        'loanhistory_set', to_attr='loan_histories_from_180dpd', queryset=loan_history_from_180_dpd_query_set)

    prefetch_join_tables = [
        prefetch_applications,
        prefetch_payments,
        prefetch_last_unpaid_payments,
        prefetch_oldest_unpaid_payments,
        prefetch_total_outstanding_due_amount,
        prefetch_total_outstanding_amount,
        prefetch_grab_loan_data,
        prefetch_payback_transactions_current_date,
        prefetch_loan_history_180_dpd,
        prefetch_loan_history_from_180_dpd
    ]
    only_fields = ['id', 'loan_status__status', 'loan_xid', 'loan_amount',
                   'loan_duration', 'account__status',
                   'product_id', 'product__admin_fee', 'account__account_lookup']

    deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE, is_active=True)

    loan_qs = Loan.objects.select_related(
        'account', 'loan_status', 'product', 'account__account_lookup',
        'account__account_lookup__workflow').prefetch_related(*prefetch_join_tables) \
        .only(*only_fields) \
        .filter(account__account_lookup__workflow__name=WorkflowConst.GRAB) \
        .exclude(loan_status_id=LoanStatusCodes.PAID_OFF) \
        .order_by('-id')
    if deduction_feature_setting and deduction_feature_setting.parameters:
        complete_rollover_flag = deduction_feature_setting.parameters.get("complete_rollover", False)
        if not complete_rollover_flag:
            loan_qs = loan_qs.filter(grabexcludedoldrepaymentloan__isnull=True)
    return loan_qs[offset: offset+limit]


def get_loan_details_grab_offset(account_id, offset, limit):
    loan_ids = Loan.objects.filter(
        account__id=account_id,
        loan_status__status_code__in={
            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
            LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
            LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
            LoanStatusCodes.LOAN_180DPD, LoanStatusCodes.RENEGOTIATED,
            241
        }
    ).order_by('id') \
        .values_list('id', flat=True)
    if not loan_ids:
        return [], 0
    if offset + limit >= len(loan_ids):
        end_limit = len(loan_ids)
    else:
        end_limit = limit + offset
    if offset >= len(loan_ids):
        raise GrabLogicException("Offset Out of range")

    payment_queryset_fields = [
        'id', 'due_date', 'payment_status_id', 'late_fee_amount', 'paid_principal', 'paid_interest', 'payment_number',
        'due_amount', 'paid_late_fee', 'installment_principal', 'installment_interest', 'paid_principal',
        'paid_interest', 'loan_id'
    ]
    payment_queryset = Payment.objects.select_related('payment_status').only(
        *payment_queryset_fields).all().order_by('due_date')
    prefetch_payments = Prefetch('payment_set', to_attr="prefetch_payments", queryset=payment_queryset)

    last_unpaid_payment_queryset = Payment.objects.only('id', 'loan_id', 'due_date') \
        .not_paid_active().order_by('payment_number')
    prefetch_last_unpaid_payments = Prefetch('payment_set', to_attr="grab_last_unpaid_payments",
                                             queryset=last_unpaid_payment_queryset)

    oldest_unpaid_payments_queryset = Payment.objects.only('id', 'loan_id', 'due_date', 'payment_status_id') \
        .not_paid_active().order_by('due_date')
    prefetch_oldest_unpaid_payments = Prefetch('payment_set', to_attr="grab_oldest_unpaid_payments",
                                               queryset=oldest_unpaid_payments_queryset)

    total_outstanding_amount_queryset = Payment.objects.only('id', 'loan_id', 'due_amount').not_paid_active()
    prefetch_total_outstanding_amount = Prefetch('payment_set', to_attr="total_outstanding_amounts",
                                                 queryset=total_outstanding_amount_queryset)

    total_paid_amount_queryset = Payment.objects.only('id', 'loan_id', 'paid_amount')
    prefetch_total_paid_amount = Prefetch('payment_set', to_attr="total_paid_amount",
                                          queryset=total_paid_amount_queryset)

    today = timezone.localtime(timezone.now()).date()
    total_outstanding_due_amount_queryset = Payment.objects.only('id', 'loan_id', 'due_amount', 'payment_status_id') \
        .not_paid_active().filter(due_date__lte=today)
    prefetch_total_outstanding_due_amount = Prefetch('payment_set', to_attr="total_outstanding_due_amounts",
                                                     queryset=total_outstanding_due_amount_queryset)

    prefetch_applications = Prefetch(
        'account__application_set', to_attr="applications",
        queryset=Application.objects.only('application_xid', 'id', 'account_id').all().order_by('-id')
    )
    loan_history_180_dpd_query_set = LoanHistory.objects.filter(status_new=LoanStatusCodes.LOAN_180DPD
                                                                ).order_by('pk')
    prefetch_loan_history_180_dpd = Prefetch('loanhistory_set', to_attr='loan_histories_180_dpd',
                                             queryset=loan_history_180_dpd_query_set)

    loan_history_from_180_dpd_query_set = LoanHistory.objects.only('cdate').filter(
        status_old=LoanStatusCodes.LOAN_180DPD).order_by('pk')
    prefetch_loan_history_from_180_dpd = Prefetch(
        'loanhistory_set', to_attr='loan_histories_from_180dpd', queryset=loan_history_from_180_dpd_query_set)


    prefetch_join_tables = [
        prefetch_applications,
        prefetch_payments,
        prefetch_last_unpaid_payments,
        prefetch_oldest_unpaid_payments,
        prefetch_total_outstanding_due_amount,
        prefetch_total_outstanding_amount,
        prefetch_total_paid_amount,
        prefetch_loan_history_180_dpd,
        prefetch_loan_history_from_180_dpd
    ]

    only_fields = ['id', 'loan_status', 'loan_xid', 'loan_amount', 'loan_duration', 'account__status']
    return Loan.objects.select_related('account').prefetch_related(*prefetch_join_tables) \
               .only(*only_fields).filter(
        account__id=account_id,
        loan_status__status_code__in={
            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
            LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
            LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
            LoanStatusCodes.LOAN_180DPD, LoanStatusCodes.RENEGOTIATED,
            241
        }
    ).order_by('-id')[offset: end_limit], \
           len(loan_ids)


def get_loans(application_xid="", loan_xid=""):
    loan_filters = dict()
    if application_xid:
        application = Application.objects.only('application_xid', 'id', 'account_id') \
            .filter(application_xid=application_xid).first()
        if not application:
            raise GrabLogicException(
                f"Grab Application not found for application xid {application_xid}"
            )
        loan_filters['account__application__application_xid'] = application_xid
    elif loan_xid:
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            raise GrabLogicException(f"Grab Application not found for loan xid {loan_xid}")
        loan_filters['loan_xid'] = loan_xid

    grab_payment_queryset = GrabPaymentTransaction.objects.only('id', 'transaction_id', 'payment_id').all()
    prefetch_grab_payments = Prefetch(
        'grabpaymenttransaction_set', queryset=grab_payment_queryset, to_attr='transaction_ids'
    )

    payback_transaction_current_date_queryset = PaybackTransaction.objects.only(
        'id', 'loan_id', 'payback_service', 'amount',
        'is_processed', 'transaction_date').filter(
        transaction_date__date=timezone.localtime(timezone.now()).date(),
        is_processed=True
    )
    prefetch_payback_transactions_current_date = Prefetch(
        'paybacktransaction_set', queryset=payback_transaction_current_date_queryset,
        to_attr='current_date_transactions'
    )

    payment_queryset_fields = [
        'id', 'due_date', 'payment_status_id', 'late_fee_amount', 'paid_principal', 'paid_interest', 'payment_number',
        'due_amount', 'paid_late_fee', 'installment_principal', 'installment_interest', 'paid_principal',
        'paid_interest', 'loan_id'
    ]
    payment_queryset = Payment.objects.select_related('payment_status')\
        .prefetch_related(prefetch_grab_payments) \
        .only(*payment_queryset_fields).all().order_by('due_date')
    prefetch_payments = Prefetch('payment_set', to_attr="prefetch_payments", queryset=payment_queryset)

    last_unpaid_payment_queryset = Payment.objects.only('id', 'loan_id', 'due_date') \
        .not_paid_active().order_by('payment_number')
    prefetch_last_unpaid_payments = Prefetch('payment_set', to_attr="grab_last_unpaid_payments",
                                             queryset=last_unpaid_payment_queryset)

    oldest_unpaid_payments_queryset = Payment.objects.only('id', 'loan_id', 'due_date', 'payment_status_id') \
        .not_paid_active().order_by('due_date')
    prefetch_oldest_unpaid_payments = Prefetch('payment_set', to_attr="grab_oldest_unpaid_payments",
                                               queryset=oldest_unpaid_payments_queryset)

    total_outstanding_amount_queryset = Payment.objects.only('id', 'loan_id', 'due_amount').not_paid_active()
    prefetch_total_outstanding_amount = Prefetch('payment_set', to_attr="total_outstanding_amounts",
                                                 queryset=total_outstanding_amount_queryset)

    today = timezone.localtime(timezone.now()).date()
    total_outstanding_due_amount_queryset = Payment.objects.only(
        'id', 'loan_id', 'due_amount', 'payment_status_id', 'payment_status__cdate'
    ).not_paid_active().filter(due_date__lte=today)
    prefetch_total_outstanding_due_amount = Prefetch('payment_set', to_attr="total_outstanding_due_amounts",
                                                     queryset=total_outstanding_due_amount_queryset)

    grab_loan_data_set = GrabLoanData.objects.only(
        'loan_halt_date', 'loan_resume_date', 'id', 'loan_id', 'is_repayment_capped')
    prefetch_grab_loan_data = Prefetch('grabloandata_set', to_attr='grab_loan_data_set',
                                       queryset=grab_loan_data_set)

    prefetch_applications = Prefetch(
        'account__application_set', to_attr="applications",
        queryset=Application.objects.only('application_xid', 'id', 'account_id').all().order_by('-id')
    )
    loan_history_180_dpd_query_set = LoanHistory.objects.filter(status_new=LoanStatusCodes.LOAN_180DPD
                                                                ).order_by('pk')
    prefetch_loan_history_180_dpd = Prefetch('loanhistory_set', to_attr='loan_histories_180_dpd',
                                             queryset=loan_history_180_dpd_query_set)

    loan_history_from_180_dpd_query_set = LoanHistory.objects.only('cdate').filter(
        status_old=LoanStatusCodes.LOAN_180DPD).order_by('pk')
    prefetch_loan_history_from_180_dpd = Prefetch(
        'loanhistory_set', to_attr='loan_histories_from_180dpd', queryset=loan_history_from_180_dpd_query_set)

    prefetch_join_tables = [
        prefetch_applications,
        prefetch_payments,
        prefetch_last_unpaid_payments,
        prefetch_oldest_unpaid_payments,
        prefetch_total_outstanding_due_amount,
        prefetch_total_outstanding_amount,
        prefetch_grab_loan_data,
        prefetch_payback_transactions_current_date,
        prefetch_loan_history_180_dpd,
        prefetch_loan_history_from_180_dpd
    ]

    only_fields = ['id', 'loan_status__status', 'loan_xid', 'loan_amount', 'loan_duration', 'account__status',
                   'product_id', 'product__admin_fee', 'fund_transfer_ts']
    return Loan.objects.select_related('account', 'loan_status', 'product').prefetch_related(*prefetch_join_tables) \
               .only(*only_fields).filter(**loan_filters).order_by('-id')


def update_grab_limit(account, program_id):
    if account:
        grab_customer = GrabCustomerData.objects.filter(customer=account.customer).last()
        if grab_customer:
            grab_loan_data = GrabLoanData.objects.filter(
                loan_id__isnull=True,
                grab_loan_inquiry__program_id=program_id,
                grab_loan_inquiry__grab_customer_data=grab_customer,
            ).last()
            if not grab_loan_data:
                raise GrabLogicException("Grab Loan Data Not Found")
            grab_loan_inquiry = grab_loan_data.grab_loan_inquiry
            if not grab_loan_inquiry:
                raise GrabLogicException("Grab Loan Inquiry Not Found")
            account_limit = AccountLimit.objects.filter(account=account).last()
            account_limit.max_limit = grab_loan_inquiry.max_loan_amount
            account_limit.available_limit = grab_loan_inquiry.max_loan_amount
            account_limit.save()


def get_daily_repayment_amount(loan_amount, loan_duration, interest):
    _, _, instalment_amount = compute_payment_installment_grab(
        int(loan_amount), int(loan_duration), interest)
    return instalment_amount


def format_grab_transaction_id(payment):
    return GrabPaymentTransaction.objects.filter(
        payment=payment
    ).values_list('transaction_id', flat=True)


def track_payment_details_based_on_txn_id(loan, txn_id):
    loan_payment_set = loan.payment_set.all()
    if not loan_payment_set:
        return
    paid_principal = 0
    paid_late_fee = 0
    paid_interest = 0
    total_loan_principal = loan_payment_set.aggregate(
        Sum('installment_principal'))['installment_principal__sum']
    total_loan_interest = loan_payment_set.aggregate(
        Sum('installment_interest'))['installment_interest__sum']
    total_loan_late_fee = loan_payment_set.aggregate(
        Sum('late_fee_amount'))['late_fee_amount__sum']
    payment_ids = loan_payment_set.values_list('id', flat=True)
    grab_payment_txn = GrabPaymentTransaction.objects.filter(
        transaction_id=txn_id
    ).last()
    relevant_grab_txns = GrabPaymentTransaction.objects.filter(
        payment__in=payment_ids).exclude(cdate__gt=grab_payment_txn.cdate)
    total_paid_amount = relevant_grab_txns.aggregate(
        Sum('payment_amount'))['payment_amount__sum']
    installment_principal = loan_payment_set[1].installment_principal
    installment_interest = loan_payment_set[1].installment_interest
    late_fee_amount = loan_payment_set[1].late_fee_amount
    total_paid_amount = total_paid_amount or 0

    while total_paid_amount > 0:
        if total_paid_amount - installment_principal >= 0:
            paid_principal += installment_principal
            total_paid_amount -= installment_principal
        else:
            paid_principal += total_paid_amount
            break
        if total_paid_amount - installment_interest >= 0:
            paid_interest += installment_interest
            total_paid_amount -= installment_interest
        else:
            paid_interest += total_paid_amount
            break
        if total_paid_amount - late_fee_amount >= 0:
            paid_late_fee += late_fee_amount
            total_paid_amount -= late_fee_amount
        else:
            paid_late_fee += total_paid_amount
            break

    outstanding_principle = total_loan_principal - paid_principal
    outstanding_interest = total_loan_interest - paid_interest
    outstanding_late_fee_amount = total_loan_late_fee - paid_late_fee
    return outstanding_principle, outstanding_interest, outstanding_late_fee_amount


def get_weekly_instalment_amount(loan_amount,
                                 installment_count,
                                 frequency="daily"):
    weekly_installment_amount = 0
    if frequency == 'daily':
        installment_amount = float(loan_amount) / installment_count
        weekly_installment_amount = min(installment_count, 7) * installment_amount
    elif frequency == 'weekly':
        installment_amount = loan_amount
        weekly_installment_amount = installment_amount
    elif frequency == 'monthly':
        installment_amount = loan_amount
        weekly_installment_amount = float(installment_amount) / 4
    return weekly_installment_amount


def get_weekly_installment_amount_txn(loan, txn_id):
    loan_payment_set = loan.payment_set.all()
    payment_ids = loan_payment_set.values_list('id', flat=True)
    grab_payment_txn = GrabPaymentTransaction.objects.filter(
        transaction_id=txn_id
    ).last()
    relevant_grab_txns = GrabPaymentTransaction.objects.filter(
        payment__in=payment_ids).order_by('-cdate').exclude(cdate__gt=grab_payment_txn.cdate)
    last_txn = None
    for txns in relevant_grab_txns:
        if txns.transaction_id != txn_id:
            last_txn = txns
            break
    if last_txn:
        current_outstanding_principal, _, _ = track_payment_details_based_on_txn_id(
            loan, txn_id)
        last_outstanding_principal, _, _ = track_payment_details_based_on_txn_id(
            loan, last_txn.transaction_id)
        principal_paid = last_outstanding_principal - current_outstanding_principal
    else:
        relevant_grab_payment_id = relevant_grab_txns.values_list(
            'payment__id', flat=True)
        principal_paid = loan.payment_set.filter(
            id__in=relevant_grab_payment_id).aggregate(
            Sum('paid_principal'))['paid_principal__sum']
    weekly_instalment_amount = get_weekly_instalment_amount(
        principal_paid, loan.loan_duration)
    return weekly_instalment_amount


def get_weekly_installment_amount_txn_simple(loan):
    grab_loan = GrabLoanData.objects.filter(loan=loan).last()
    if not grab_loan:
        raise GrabLogicException("Grab Loan Data not found for "
                                 "loan id {}".format(loan.id))
    return grab_loan.grab_loan_inquiry.weekly_instalment_amount


def check_grab_reapply_eligibility(application_id):
    application = Application.objects.get(id=application_id)
    if not application:
        raise GrabLogicException("Application Not found for Application id {}".format(
            application_id))
    response = []
    phone = application.customer.phone
    if application.mobile_phone_1:
        phone = application.mobile_phone_1
    phone = format_nexmo_voice_phone_number(phone)
    try:
        grab_response = GrabClient.get_loan_offer(
            phone_number=phone, customer_id=application.customer.id)
        if "data" in grab_response and grab_response["data"]:
            for offer in grab_response["data"]:
                if int(float(offer["min_loan_amount"])) > int(float(offer["max_loan_amount"])) \
                        or int(offer["loan_duration"]) < 1:
                    continue
                response.append({
                    "program_id": offer["program_id"],
                    "max_loan_amount": offer["max_loan_amount"],
                    "min_loan_amount": offer["min_loan_amount"],
                    "weekly_installment_amount": offer['weekly_installment_amount'],
                    "tenure": offer["loan_duration"],
                    "min_tenure": offer["min_tenure"],
                    "tenure_interval": offer["tenure_interval"],
                    "daily_repayment": get_daily_repayment_amount(
                        offer["min_loan_amount"], offer["loan_duration"], offer["interest_value"]),
                    "upfront_fee_type": offer["fee_type"],
                    "upfront_fee": offer["fee_value"],
                    "interest_rate_type": offer["interest_type"],
                    "interest_rate": offer["interest_value"],
                    "penalty_type": offer["penalty_type"],
                    "penalty_value": offer["penalty_value"],
                    "loan_disbursement_amount": int(float(offer["max_loan_amount"])) - int(offer["fee_value"]),
                    "frequency_type": offer["frequency_type"]
                })
    except GrabApiException as gae:
        logger.warning({
            "task": "check_grab_reapply_eligibility",
            "application_id": application_id,
            "error": str(gae),
            "note": "Could be blocking potential dax"
        })
    return len(response) >= 1


def get_principal_settled_grab(loan, txn_id):
    loan_payment_set = loan.payment_set.all()
    payment_ids = loan_payment_set.values_list('id', flat=True)
    grab_payment_txn = GrabPaymentTransaction.objects.filter(
        transaction_id=txn_id
    ).last()
    relevant_grab_txns = GrabPaymentTransaction.objects.filter(
        payment__in=payment_ids).order_by('-cdate').exclude(cdate__gt=grab_payment_txn.cdate)
    last_txn = None
    total_loan_principal = loan_payment_set.aggregate(
        Sum('installment_principal'))['installment_principal__sum']
    for txns in relevant_grab_txns:
        if txns.transaction_id != txn_id:
            last_txn = txns
            break
    current_outstanding_principal, _, _ = track_payment_details_based_on_txn_id(
        loan, txn_id)
    if last_txn:
        last_outstanding_principal, _, _ = track_payment_details_based_on_txn_id(
            loan, last_txn.transaction_id)
        principal_paid = last_outstanding_principal - current_outstanding_principal
        return principal_paid
    return total_loan_principal - current_outstanding_principal


def validate_nik(value):
    existing = Customer.objects.filter(nik=value).first()

    if existing:
        raise GrabLogicException("NIK anda sudah terdaftar")

    return value


def validate_phone_number(value):
    existing = Customer.objects.filter(phone=value).first()

    if existing:
        raise GrabLogicException("Nomor HP anda sudah terdaftar")

    return value


def validate_email(value, customer, raise_validation_error=False):
    existing = Customer.objects.filter(email__iexact=value).exclude(id=customer.id).first()
    if existing:
        if not raise_validation_error:
            raise GrabLogicException("Alamat email sudah terpakai")
        else:
            raise serializers.ValidationError("Alamat email sudah terpakai")

    return value


def validate_email_registration(value):
    existing = Customer.objects.filter(email__iexact=value).first()
    if existing:
        raise GrabLogicException("Alamat email sudah terpakai")

    return value


def validate_email_application(value, customer, raise_validation_error=False):
    existing = Application.objects.filter(email__iexact=value).exclude(customer=customer).exists()
    if existing:
        if not raise_validation_error:
            raise GrabLogicException("Alamat email sudah terpakai")
        else:
            raise serializers.ValidationError("Alamat email sudah terpakai")

    return value


def get_sphp_context_grab(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)

    if not loan:
        return None
    sphp_date = loan.sphp_sent_ts
    payments = loan.payment_set.order_by('due_date')
    if not payments:
        return None
    start_date = payments.first().due_date
    end_date = payments.last().due_date
    today_date = timezone.localtime(timezone.now()).date()
    application = loan.account.application_set.last()
    context = {
        'application_xid': application.application_xid,
        'fullname': application.fullname,
        'ktp': application.ktp,
        'mobile_phone': application.mobile_phone_1,
        'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
        'full_address': application.full_address,
        'loan_amount': display_rupiah(loan.loan_amount),
        'late_fee_amount': display_rupiah(loan.late_fee_amount),
        'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
        'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'start_date': format_date(start_date, 'dd-MM-yyyy', locale='id_ID'),
        'end_date': format_date(end_date, 'dd-MM-yyyy', locale='id_ID'),
        'total_number_of_payments': payments.count(),
        'max_total_late_fee_amount': display_rupiah(loan.max_total_late_fee_amount),
        'provision_fee_amount': display_rupiah(loan.provision_fee() + loan.product.admin_fee),
        'interest_rate': '{}%'.format(loan.product.interest_rate * 100),
        'instalment_amount': display_rupiah(loan.installment_amount),
        'maximum_late_fee_amount': display_rupiah(loan.loan_amount if loan.late_fee_amount else 0),
        'signature_date': format_date(today_date, 'dd-MM-yyyy', locale='id_ID'),
    }
    return context


def check_existing_customer_status(customer):
    applicationset = customer.application_set.all()
    for application in applicationset.iterator():
        if application.application_status_id not in graveyard_statuses:
            return False
        if application.product_line_code in ProductLineCodes.mtl() + ProductLineCodes.ctl():
            if application.application_status_id == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
                last_loan = Loan.objects.filter(
                    application=application,
                    loan_status__gte=LoanStatusCodes.CURRENT,
                    loan_status__lt=LoanStatusCodes.PAID_OFF,
                    application__product_line__product_line_code__in=
                    ProductLineCodes.mtl() + ProductLineCodes.ctl()).last()
                if last_loan:
                    return False
    return True


def verify_grab_loan_offer(application):
    verify_loan_flag = False
    try:
        grab_response = GrabClient.get_loan_offer(
            application.customer.phone,
            application.id,
            application.customer.id
        )
        if "data" in grab_response and grab_response["data"]:
            for offer in grab_response["data"]:
                if int(float(offer["min_loan_amount"])) > int(float(offer["max_loan_amount"])) \
                        or int(offer["loan_duration"]) < 1:
                    continue
                verify_loan_flag = True
    except GrabApiException as e:
        logger.exception({
            "task_name": "verify_grab_loan_offer",
            "application": application.id,
            "error": str(e)
        })
    return verify_loan_flag


def validate_loan_request(customer):
    grab_customer_data = GrabCustomerData.objects.filter(customer=customer).last()
    if not grab_customer_data:
        raise GrabLogicException("grab_customer_data cannot be blank")
    existing_grab_loans = GrabLoanData.objects.filter(
        grab_loan_inquiry__grab_customer_data=grab_customer_data,
        loan_id__isnull=False
    ).exclude(loan__loan_status_id=LoanStatusCodes.PAID_OFF).values_list(
        'loan_id', flat=True)
    for grab_loan_id in existing_grab_loans:
        loan = Loan.objects.get_or_none(id=grab_loan_id)
        graveyard_loan_statuses.update({
            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.HALT
        })
        if loan.loan_status_id not in graveyard_loan_statuses:
            raise GrabLogicException("Existing Loan Ongoing")
        grab_api_logs = GrabAPILog.objects.filter(
            loan_id=grab_loan_id).filter(
            Q(query_params__contains=GrabPaths.LOAN_CREATION) |
            Q(query_params__contains=GrabPaths.DISBURSAL_CREATION) |
            Q(query_params__contains=GrabPaths.CANCEL_LOAN)
        )

        # Auth Check
        auth_log = grab_api_logs.filter(
            query_params__contains=GrabPaths.LOAN_CREATION,
        )
        success_auth_log = auth_log.filter(http_status_code=https_status_codes.HTTP_200_OK).exists()

        capture_cancel_log = grab_api_logs.filter(
            (
                Q(query_params__contains=GrabPaths.DISBURSAL_CREATION)
                | Q(query_params__contains=GrabPaths.CANCEL_LOAN)
            ),
            http_status_code=https_status_codes.HTTP_200_OK,
        ).exists()

        if not success_auth_log:
            continue

        if success_auth_log and not capture_cancel_log:
            raise GrabLogicException("Hanging AUTH call")


def change_phone_number_grab(customer, old_phone_number, new_phone_number):
    response_data = {
        "update_customer": False
    }
    with transaction.atomic():
        existing_grab_customer = GrabCustomerData.objects.filter(
            grab_validation_status=True,
            phone_number=format_nexmo_voice_phone_number(new_phone_number)
        )
        if existing_grab_customer.filter(customer__isnull=False).exists():
            raise GrabLogicException("Customer Already registered "
                                     "with new_phone_number")
        else:
            existing_grab_customer.update(grab_validation_status=False)
        cutoff_time = timezone.localtime(timezone.now()) - timedelta(minutes=5)
        grab_customer_data = GrabCustomerData.objects.filter(
            customer=customer,
            phone_number=format_nexmo_voice_phone_number(old_phone_number)
        ).last()

        if customer.user.pin.latest_failure_count != 0 or \
                customer.user.pin.last_failure_time < timezone.\
                localtime(timezone.now()) - timedelta(minutes=10):
            raise GrabLogicException('Please Verify Pin before changing Phone')
        if not grab_customer_data:
            raise GrabLogicException('Old Phone Number not found')

        otp_requests = OtpRequest.objects.filter(
            customer=customer,
            is_used=True,
            cdate__gt=cutoff_time
        )
        mfs = MobileFeatureSetting.objects.get_or_none(
            feature_name='mobile_phone_1_otp', is_active=True)
        if mfs:
            old_phone_count = otp_requests.filter(
                phone_number=format_nexmo_voice_phone_number(old_phone_number)).count()
            new_phone_count = otp_requests.filter(
                phone_number=format_nexmo_voice_phone_number(new_phone_number)).count()
            if not (new_phone_count > 0 and old_phone_count > 0):
                raise GrabLogicException("Please redo OTP Verification")
        application = customer.application_set.filter(
            workflow__name=WorkflowConst.GRAB).last()
        if not application:
            application = customer.application_set.last()
        ApplicationFieldChange.objects.create(
            application=application,
            field_name='mobile_phone_1',
            old_value=application.mobile_phone_1,
            new_value=format_nexmo_voice_phone_number(new_phone_number),
            agent=None
        )

        application.update_safely(
            mobile_phone_1=format_nexmo_voice_phone_number(new_phone_number))
        CustomerFieldChange.objects.create(
            customer=customer,
            field_name='phone',
            old_value=customer.phone,
            new_value=format_nexmo_voice_phone_number(new_phone_number),
            application_id=application.id,
            changed_by=None
        )
        customer.phone = format_nexmo_voice_phone_number(new_phone_number)
        customer.save(update_fields=['phone'])
        loans = Loan.objects.filter(
            customer=customer,
            account__account_lookup__workflow__name=WorkflowConst.GRAB,
            loan_status_id=LoanStatusCodes.INACTIVE
        )
        for loan in loans:
            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                change_by_id=customer.user.id,
                change_reason="Customer phone number changed"
            )
        hashed_phone = GrabUtils.create_user_token(new_phone_number)
        grab_customer_data.phone_number = format_nexmo_voice_phone_number(new_phone_number)
        grab_customer_data.hashed_phone_number = hashed_phone
        grab_customer_data.save(update_fields=['phone_number', 'hashed_phone_number'])
        response_data = {
            "update_customer": True
        }

        trigger_create_or_update_ayoconnect_beneficiary.delay(customer.id, update_phone=True)

    return response_data


def get_reject_reason_for_application(application):
    if not application or type(application) != Application:
        return
    if application.application_status_id not in excluded_statuses:
        return

    if application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
        last_loan = application.account.loan_set.select_related('loan_status').last()
        if not last_loan:
            return

        if last_loan.loan_status.status_code != LoanStatusCodes.SPHP_EXPIRED:
            return
        else:
            grab_rejection_reason = None
            for rejection_mapping in grab_rejection_mapping_statuses:
                if last_loan.loan_status.status_code == \
                        rejection_mapping.application_loan_status:
                    grab_rejection_reason = rejection_mapping.mapping_status
            return grab_rejection_reason
    else:
        additional_check_grab = get_additional_check_for_rejection_grab(application)
        grab_rejection_reason = application.grab_rejection_reason(additional_check_grab)
    return grab_rejection_reason


def get_expiry_date_grab(application):
    if application.application_status_id not in [
        ApplicationStatusCodes.LOC_APPROVED,
        ApplicationStatusCodes.FORM_CREATED,
        ApplicationStatusCodes.FORM_PARTIAL,
        ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
    ]:
        return
    if application.application_status_id in [
        ApplicationStatusCodes.FORM_CREATED,
        ApplicationStatusCodes.FORM_PARTIAL
    ]:
        app_history = ApplicationHistory.objects.filter(
            application_id=application.id,
            status_new=application.application_status_id,
        ).last()
        expiry_date = (app_history.cdate + relativedelta(days=14)).strftime("%Y-%m-%d")
    elif application.application_status_id == \
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
        application_history = ApplicationHistory.objects.filter(
            application=application, status_new=application.application_status_id
        ).order_by("cdate").last()
        if not application_history:
            return
        delta = timezone.localtime(application_history.cdate + timedelta(days=2)).date()
        expiry_date = delta.strftime("%Y-%m-%d")
    else:
        account = application.account
        if not account:
            raise GrabLogicException("Account Dont exist for application {}".format(
                application.id))
        loan = account.loan_set.filter(
            loan_status__status_code=LoanStatusCodes.INACTIVE).last()
        if not loan:
            return
        expiry_date = loan.sphp_exp_date.strftime("%Y-%m-%d")
    return expiry_date


def get_additional_check_for_rejection_grab(application):
    from juloserver.grab.constants import OTHER_DOCUMENTS_RESUBMISSION
    additional_check = None
    if application.application_status_id == ApplicationStatusCodes.APPLICATION_DENIED:
        failed_checks = AutoDataCheck.objects.filter(
            application_id=application.id, is_okay=False).values_list(
            'data_to_check', flat=True
        )
        if not failed_checks:
            app_history = ApplicationHistory.objects.filter(
                status_new=application.application_status_id,
                application=application).last()
            if not app_history:
                return
            additional_check = []
            for reject_message in grab_rejection_mapping_statuses:
                if reject_message.application_loan_status == \
                        ApplicationStatusCodes.APPLICATION_DENIED:
                    if reject_message.additional_check in app_history.change_reason:
                        additional_check.append(reject_message.additional_check)
            return additional_check[0] if additional_check else additional_check
        return failed_checks[0]
    elif application.application_status_id == \
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
        app_history = ApplicationHistory.objects.filter(
            status_new=application.application_status_id,
            application=application).last()
        if not app_history:
            return
        additional_check = []
        for reject_message in grab_rejection_mapping_statuses:
            if reject_message.application_loan_status == \
                    ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
                if reject_message.additional_check in app_history.change_reason:
                    additional_check.append(reject_message.additional_check)
        for reject_reason in OTHER_DOCUMENTS_RESUBMISSION:
            if reject_reason in app_history.change_reason:
                additional_check.append("Other")
    return additional_check[0] if additional_check else additional_check


def can_reapply_application_grab(customer):
    """
    Checking if grab customer can reapply or not.
    """
    last_application = customer.application_set.filter(workflow__name=WorkflowConst.GRAB).last()
    if not last_application:
        return False
    application_status = last_application.application_status_id
    if application_status in {
        ApplicationStatusCodes.FORM_CREATED, ApplicationStatusCodes.FORM_PARTIAL
    }:
        return False
    if application_status not in graveyard_statuses:
        return False

    if application_status in {
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER
    }:
        return True
    elif application_status == ApplicationStatusCodes.APPLICATION_DENIED:
        failed_checks = AutoDataCheck.objects.filter(
            application_id=last_application.id, is_okay=False).values_list(
            'data_to_check', flat=True
        )
        if failed_checks:
            for failed_check in failed_checks:
                if failed_check in {'blacklist_customer_check', 'grab_application_check'}:
                    return False
    if not check_active_loans_pending_j1_mtl(customer):
        return False
    return True


def check_active_loans_pending_j1_mtl(customer):
    """
    Checking for existing MTL pending loans and checking if
    active J1 applications exists.
    """
    applications = customer.application_set.all()
    for application in applications:
        if application.workflow and \
                application.workflow.name == 'JuloOneWorkflow':
            if application.application_status_id not in graveyard_statuses:
                return False

        elif application.product_line and application.product_line.\
                product_line_code in ProductLineCodes.mtl() + ProductLineCodes.ctl():
            if application.application_status_id == \
                    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
                last_loan = Loan.objects.filter(
                    application=application,
                    loan_status__gte=220,
                    loan_status__lt=250,
                    application__product_line__product_line_code__in=
                    ProductLineCodes.mtl() + ProductLineCodes.ctl()).last()
                if last_loan:
                    return False
            elif application.application_status_id not in graveyard_statuses:
                return False
    return True


def expire_ctl_applications(user):
    customer = user.customer
    application_set = customer.application_set.filter(
        product_line__product_line_code__in=ProductLineCodes.ctl(),
        application_status_id=ApplicationStatusCodes.PENDING_PARTNER_APPROVAL
    )
    if not application_set.exists():
        return

    new_status_code = ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED
    for app in application_set:
        experiment = experimentation(app, new_status_code)
        normal_application_status_change(app, new_status_code, "system_triggered", experiment['is_experiment'])


def process_grab_bank_validation_v2(application_id, force_validate=False, new_data=None):
    application = Application.objects.get_or_none(pk=application_id)
    is_grab = application.is_grab()
    if not is_grab:
        raise GrabHandlerException("INVALID GRAB APPLICATION - FAILED BANK VALIDATION")

    name_bank_validation_id = application.name_bank_validation_id

    data_to_validate = {'name_bank_validation_id': name_bank_validation_id,
                        'bank_name': application.bank_name,
                        'account_number': application.bank_account_number,
                        'name_in_bank': application.name_in_bank,
                        'mobile_phone': application.mobile_phone_1,
                        'application': application
                        }
    if new_data:
        data_to_validate['name_in_bank'] = new_data['name_in_bank']
        data_to_validate['bank_name'] = new_data['bank_name']
        data_to_validate['account_number'] = new_data['bank_account_number']
        data_to_validate['name_bank_validation_id'] = None
        if is_grab:
            data_to_validate['mobile_phone'] = format_mobile_phone(application.mobile_phone_1)
    validation = NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)

    # checking is validation is not success already
    if validation is None or validation.validation_status != NameBankValidationStatus.SUCCESS \
            or force_validate:
        validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
        validation_id = validation.get_id()
        application.update_safely(name_bank_validation_id=validation_id)
        if (
            is_grab
            and validation.name_bank_validation.method == NameBankValidationVendors.PAYMENT_GATEWAY
        ):
            validation.validate_grab()
        else:
            validation.validate()
        validation_data = validation.get_data()
        if not validation.is_success():
            if validation_data['attempt'] >= 3:
                validation_data['go_to_175'] = True
            if application.status == ApplicationStatusCodes.LOC_APPROVED:
                logger.warning('Grab name bank validation error | application_id=%s, '
                               'validation_data=%s' % (application.id, validation_data))
                return

            process_application_status_change(
                application.id,
                ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                'name_bank_validation_failed'
            )
            return
        else:
            # update application with new verified BA
            application.update_safely(
                bank_account_number=validation_data['account_number'],
                name_in_bank=validation_data['validated_name'],
            )
            if application.status != ApplicationStatusCodes.LOC_APPROVED:
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                    "system_triggered"
                )
            else:
                update_loan_status_for_grab_invalid_bank_account(application.id)
    else:
        # update table with new verified BA
        application.update_safely(
            bank_account_number=validation.account_number,
            name_in_bank=validation.validated_name,
        )
        if application.status != ApplicationStatusCodes.LOC_APPROVED:
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                "system_triggered"
            )


def update_loan_status_for_halted_or_resumed_loan(loan):
    unpaid_payments = list(Payment.objects.select_related(
        'payment_status').by_loan(loan).not_paid())
    if len(unpaid_payments) == 0:
        if loan.status == LoanStatusCodes.RENEGOTIATED:
            loan.process_paid_off()
            return True

        else:
            # When all payments have been paid
            if loan.product.has_cashback:
                cashback_payments = loan.payment_set.aggregate(total=Sum('cashback_earned'))['total']
                cashback_earned = cashback_payments + loan.initial_cashback
                customer = loan.customer
                customer.change_wallet_balance(change_accruing=0,
                                               change_available=cashback_earned,
                                               reason='loan_paid_off')
            loan.process_paid_off()

            return True

    overdue_payments = []
    for unpaid_payment in unpaid_payments:
        if unpaid_payment.is_overdue:
            overdue_payments.append(unpaid_payment)
    if len(overdue_payments) == 0:
        # When some payments are unpaid but none is overdue
        update_loan_status_and_loan_history(loan_id=loan.id,
                                            new_status_code=StatusLookup.CURRENT_CODE,
                                            change_reason="Loan Resumed")
        return True

    # When any of the unpaid payments is overdue
    most_overdue_payment = overdue_payments[0]
    for overdue_payment in overdue_payments:
        status_code = overdue_payment.payment_status.status_code
        if status_code > most_overdue_payment.payment_status.status_code:
            most_overdue_payment = overdue_payment
    # check if loan.status is active
    if loan.status != StatusLookup.INACTIVE_CODE:
        status_code = most_overdue_payment.payment_status.status_code
        if StatusLookup.PAYMENT_1DPD_CODE <= status_code <= StatusLookup.PAYMENT_180DPD_CODE:
            if status_code == StatusLookup.PAYMENT_1DPD_CODE:
                change_status = StatusLookup.LOAN_1DPD_CODE
            elif status_code == StatusLookup.PAYMENT_5DPD_CODE:
                change_status = StatusLookup.LOAN_5DPD_CODE
            elif status_code == StatusLookup.PAYMENT_30DPD_CODE:
                change_status = StatusLookup.LOAN_30DPD_CODE
            elif status_code == StatusLookup.PAYMENT_60DPD_CODE:
                change_status = StatusLookup.LOAN_60DPD_CODE
            elif status_code == StatusLookup.PAYMENT_90DPD_CODE:
                change_status = StatusLookup.LOAN_90DPD_CODE
            elif status_code == StatusLookup.PAYMENT_120DPD_CODE:
                change_status = StatusLookup.LOAN_120DPD_CODE
            elif status_code == StatusLookup.PAYMENT_150DPD_CODE:
                change_status = StatusLookup.LOAN_150DPD_CODE
            elif status_code == StatusLookup.PAYMENT_180DPD_CODE:
                change_status = StatusLookup.LOAN_180DPD_CODE
            else:
                change_status = None
            if change_status:
                update_loan_status_and_loan_history(loan_id=loan.id,
                                                    new_status_code=change_status,
                                                    change_reason="Loan Resumed")
        else:
            logger.warn({
                'payment': most_overdue_payment,
                'payment_status': most_overdue_payment.payment_status,
                'action': 'not_updating_status'
            })
            return False
        return True
    else:
        logger.warn({
            'payment': most_overdue_payment,
            'payment_status': most_overdue_payment.payment_status,
            'loan_status': loan.status,
            'action': 'not_updating_status'
        })
        return False


def update_loan_status_for_grab_invalid_bank_account(application_id):
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        raise GrabLogicException("Application not Found for updation")
    if application.account:
        loans = application.account.loan_set.filter(loan_status_id=LoanStatusCodes.INACTIVE)
        for loan in loans.iterator():
            update_loan_status_and_loan_history(
                loan.id, LoanStatusCodes.CANCELLED_BY_CUSTOMER, application.customer.user.id,
                change_reason="Cancelled Due to Bank Updation"
            )


def get_account_summary_loan_status(
        loan, is_early_write_off_feature=False,
        is_180_dpd_write_off_feature=False, is_manual_write_off_feature=False, dpd=0):
    GRAB_180_DPD_CUT_OFF = 180
    loan_status = loan.loan_status.status

    if loan.loan_status_id == LoanStatusCodes.LOAN_INVALIDATED:
        return "Invalid"

    if loan.loan_status_id == LoanStatusCodes.SPHP_EXPIRED:
        return loan_status

    if loan.loan_status_id == LoanStatusCodes.PAID_OFF:
        if len(loan.prefetch_payments) > 0:
            last_payment = loan.prefetch_payments[-1]
            if last_payment:
                payment_event = PaymentEvent.objects.select_related('account_transaction').filter(
                    payment=last_payment
                ).last()
                if payment_event:
                    account_transaction = payment_event.account_transaction
                    if account_transaction.transaction_type in {
                        'waive_late_fee', 'waive_principal', 'waive_interest'
                    }:
                        if is_manual_write_off_feature:
                            loan_status = GrabWriteOffStatus.MANUAL_WRITE_OFF
                        else:
                            loan_status = GrabWriteOffStatus.LEGACY_WRITE_OFF
    else:
        grab_loan_data = loan.grab_loan_data_set[0]
        if grab_loan_data:
            if is_early_write_off_feature and grab_loan_data.is_early_write_off:
                loan_status = GrabWriteOffStatus.EARLY_WRITE_OFF
            elif is_180_dpd_write_off_feature and (
                    loan.loan_status_id == LoanStatusCodes.LOAN_180DPD or len(
                    loan.loan_histories_180_dpd) > 0):
                if dpd > GRAB_180_DPD_CUT_OFF:
                    loan_status = GrabWriteOffStatus.WRITE_OFF_180_DPD
                elif len(loan.loan_histories_180_dpd) > 0:
                    loan_history_cdate_to_180_list = list()
                    loan_history_cdate_to_180_list_date = list()
                    loan_history_cdate_from_180_list = list()
                    loan_history_cdate_from_180_list_date = list()
                    for loan_history_to_180 in loan.loan_histories_180_dpd:
                        if timezone.localtime(
                                loan_history_to_180.cdate).date() in loan_history_cdate_to_180_list_date:
                            continue
                        loan_history_cdate_to_180_list.append(timezone.localtime(
                                loan_history_to_180.cdate))
                        loan_history_cdate_to_180_list_date.append(timezone.localtime(
                            loan_history_to_180.cdate).date())
                    for loan_history_from_180 in loan.loan_histories_from_180dpd:
                        if timezone.localtime(
                                loan_history_from_180.cdate).date() in loan_history_cdate_from_180_list_date:
                            continue
                        loan_history_cdate_from_180_list.append(timezone.localtime(
                                loan_history_from_180.cdate))
                        loan_history_cdate_from_180_list_date.append(timezone.localtime(
                                loan_history_from_180.cdate).date())

                    count_of_history_to_180 = len(loan_history_cdate_to_180_list)
                    count_of_history_from_180 = len(loan_history_cdate_from_180_list)
                    for to_idx in list(range(count_of_history_to_180)):
                        cdate_to = loan_history_cdate_to_180_list[to_idx]
                        if count_of_history_from_180 >= 1:
                            for from_idx in list(range(count_of_history_from_180)):
                                cdate_from = loan_history_cdate_from_180_list[
                                    from_idx]
                                if cdate_to <= cdate_from:
                                    break
                                if from_idx + 1 == count_of_history_from_180:
                                    cdate_from = timezone.localtime(timezone.now())
                        else:
                            cdate_from = timezone.localtime(timezone.now())
                        if (cdate_from - cdate_to).days >= 1:
                            loan_status = GrabWriteOffStatus.WRITE_OFF_180_DPD
                            break
                    if loan.loan_status_id == LoanStatusCodes.LOAN_180DPD:
                        if ((timezone.localtime(timezone.now()) - (timezone.localtime(
                                loan.loan_histories_180_dpd[-1].cdate))).days >= 1):
                            loan_status = GrabWriteOffStatus.WRITE_OFF_180_DPD

    return loan_status


def get_account_summary_loan_status_file_transfer(
        loan, last_payment, is_early_write_off_feature=False,
        is_180_dpd_write_off_feature=False, is_manual_write_off_feature=False, dpd=0):
    GRAB_180_DPD_CUT_OFF = 180
    loan_status = loan.loan_status.status
    if loan.loan_status_id == LoanStatusCodes.PAID_OFF:
        if len(loan.prefetch_payments) > 0:
            if last_payment:
                last_payment_event = last_payment.paymentevent_set.last()
                if last_payment_event:
                    account_transaction = last_payment_event.account_transaction
                    if account_transaction.transaction_type in {
                        'waive_late_fee', 'waive_principal', 'waive_interest'
                    }:
                        if is_manual_write_off_feature:
                            loan_status = GrabWriteOffStatus.MANUAL_WRITE_OFF
                        else:
                            loan_status = GrabWriteOffStatus.LEGACY_WRITE_OFF
    else:
        grab_loan_data = loan.grab_loan_data_set
        if grab_loan_data:
            if is_early_write_off_feature and grab_loan_data[0].is_early_write_off:
                loan_status = GrabWriteOffStatus.EARLY_WRITE_OFF
            elif is_180_dpd_write_off_feature and (
                    loan.loan_status_id == LoanStatusCodes.LOAN_180DPD
                    or len(loan.loan_histories_180_dpd) > 0
            ):
                if dpd > GRAB_180_DPD_CUT_OFF:
                    loan_status = GrabWriteOffStatus.WRITE_OFF_180_DPD
                elif len(loan.loan_histories_180_dpd) > 0:
                    count_of_history_to_180 = len(loan.loan_histories_180_dpd)
                    count_of_history_from_180 = len(loan.loan_histories_from_180dpd)
                    for to_idx in list(range(count_of_history_to_180)):
                        cdate_to = loan.loan_histories_180_dpd[to_idx].cdate.date()
                        if count_of_history_from_180 >= 1:
                            for from_idx in list(range(count_of_history_from_180)):
                                cdate_from = loan.loan_histories_from_180dpd[
                                    from_idx].cdate.date()
                                if cdate_to <= cdate_from:
                                    break
                                if from_idx + 1 == count_of_history_from_180:
                                    cdate_from = timezone.localtime(timezone.now()).date()
                        else:
                            cdate_from = timezone.localtime(timezone.now()).date()
                        if (cdate_from - cdate_to).days >= 1:
                            loan_status = GrabWriteOffStatus.WRITE_OFF_180_DPD
                            break

    return loan_status


def get_grab_write_off_feature_setting():
    """
    This Feature will return the feature setting for grab write off
    Return value:
    is_early_write_off bool, is_180_dpd_write_off bool, is_manual_write_off bool
    """
    is_early_write_off = False
    is_180_dpd_write_off = False
    is_manual_write_off = False

    grab_write_off_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GRAB_WRITE_OFF,
        is_active=True
    ).last()
    if grab_write_off_feature_setting and grab_write_off_feature_setting.parameters:

        is_early_write_off = grab_write_off_feature_setting.parameters.get(
            "early_write_off", False)
        is_manual_write_off = grab_write_off_feature_setting.parameters.get(
            "manual_write_off", False)
        is_180_dpd_write_off = grab_write_off_feature_setting.parameters.get(
            "180_dpd_write_off", False)

    return is_early_write_off, is_180_dpd_write_off, is_manual_write_off


def generate_grab_referral_code(customer):
    hashids = Hashids(salt=settings.GRAB_REFERRAL_CODE_SALT, alphabet=(GRAB_ALPHABET + GRAB_NUMBER),
                      min_length=4)
    unique_id = customer.id - GRAB_CUSTOMER_BASE_ID
    postfix = hashids.encode(unique_id)
    customer_name = '' if customer.fullname is None else customer.fullname.replace(" ", "")
    customer_name = ''.join(e for e in customer_name if e.isalnum())
    if len(customer_name) < 4:
        customer_name += ''.join(
            (random.choice(GRAB_ALPHABET)) for x in range(4 - len(customer_name)))
    elif len(customer_name) > 4:
        customer_name = customer_name[:4]
    referral_code = (customer_name + postfix).upper()
    return referral_code


def grab_update_old_and_create_new_referral_whitelist():
    logger.info({
        "task": "grab_update_old_and_create_new_referral_whitelist",
        "message": "starting_updation_of_new_referral"
    })
    current_whitelists = GrabReferralWhitelistProgram.objects.filter(is_active=True)
    for current_whitelist in current_whitelists:
        logger.info({
            "task": "grab_update_old_and_create_new_referral_whitelist",
            "message": "updation_of_existing_referral",
            "current_whitelist": current_whitelist
        })
        current_whitelist.update_safely(
            is_active=False,
            end_time=timezone.localtime(timezone.now())
        )
    GrabReferralWhitelistProgram.objects.create(
        is_active=True, start_time=timezone.localtime(timezone.now()))
    logger.info({
        "task": "grab_update_old_and_create_new_referral_whitelist",
        "message": "created_new_referral_whitelist"
    })


def grab_check_valid_referal_code(referral_code):
    customer = Customer.objects.filter(
        self_referral_code=referral_code.upper()).last()
    if not customer:
        logger.info({
            "task": "grab_check_valid_referal_code",
            "action": "No Customer with Referral_code",
            "referral_code": referral_code
        })
        return False
    active_whitelist_referral_program = GrabReferralWhitelistProgram.objects.filter(is_active=True).last()
    if not active_whitelist_referral_program:
        logger.info({
            "task": "grab_check_valid_referal_code",
            "message": "whitelist referral program not found or not activated",
            "referral_code": referral_code
        })
        return False
    return GrabCustomerReferralWhitelistHistory.objects.filter(
        customer=customer,
        grab_referral_whitelist_program=active_whitelist_referral_program
    ).exists()


def get_grab_active_loan_by_index(start_index, end_index):
    """
    get grab active loan by start and end index
    used by file transfer purpose
    """

    payment_queryset = Payment.objects.select_related(
        'payment_status').all().order_by('due_date')
    prefetch_payments = Prefetch('payment_set', to_attr="prefetch_payments",
                                 queryset=payment_queryset)
    oldest_unpaid_payments_queryset = Payment.objects.only(
        'id', 'loan_id', 'due_date', 'payment_status_id', 'payment_number'
    ).filter(
        payment_status__in=PaymentStatusCodes.not_paid_status_codes()
    ).order_by('due_date')
    prefetch_oldest_unpaid_payments = Prefetch('payment_set', to_attr="grab_oldest_unpaid_payments",
                                               queryset=oldest_unpaid_payments_queryset)
    total_outstanding_amount_queryset = Payment.objects.only('id', 'loan_id',
                                                             'due_amount').not_paid_active()
    prefetch_total_outstanding_amount = Prefetch('payment_set', to_attr="total_outstanding_amounts",
                                                 queryset=total_outstanding_amount_queryset)
    today = timezone.localtime(timezone.now()).date()
    payback_transaction_current_date_queryset = PaybackTransaction.objects.only(
        'id', 'loan_id', 'payback_service', 'amount',
        'is_processed', 'transaction_date').filter(
        transaction_date__date=today - timedelta(days=1),
        is_processed=True,
        payback_service='grab'
    )
    prefetch_payback_transactions_current_date = Prefetch(
        'paybacktransaction_set', queryset=payback_transaction_current_date_queryset,
        to_attr='current_date_transactions'
    )
    total_outstanding_due_amount_queryset = Payment.objects.only(
        'id', 'loan_id', 'due_amount', 'payment_status_id'
    ).filter(
        payment_status__in=PaymentStatusCodes.not_paid_status_codes(),
        due_date__lte=today - timedelta(days=1)
    )
    prefetch_total_outstanding_due_amount = Prefetch('payment_set',
                                                     to_attr="total_outstanding_due_amounts",
                                                     queryset=total_outstanding_due_amount_queryset)
    grab_loan_data_set = GrabLoanData.objects.only('loan_halt_date', 'loan_resume_date', 'id',
                                                   'loan_id', 'early_write_off_date',
                                                   'restructured_date', 'is_early_write_off',
                                                   'is_repayment_capped')
    prefetch_grab_loan_data = Prefetch('grabloandata_set', to_attr='grab_loan_data_set',
                                       queryset=grab_loan_data_set)

    prefetch_applications = Prefetch(
        'account__application_set', to_attr="applications",
        queryset=Application.objects.only('application_xid', 'id', 'account_id').all().order_by(
            '-id')
    )
    loan_history_180_dpd_query_set = LoanHistory.objects.filter(status_new=LoanStatusCodes.LOAN_180DPD
                                                                ).order_by('pk')
    prefetch_loan_history_180_dpd = Prefetch('loanhistory_set', to_attr='loan_histories_180_dpd',
                                             queryset=loan_history_180_dpd_query_set)

    loan_history_from_180_dpd_query_set = LoanHistory.objects.filter(
        status_old=LoanStatusCodes.LOAN_180DPD).order_by('pk')
    prefetch_loan_history_from_180_dpd = Prefetch(
        'loanhistory_set', to_attr='loan_histories_from_180dpd', queryset=loan_history_from_180_dpd_query_set)

    prefetch_join_tables = [
        prefetch_applications,
        prefetch_payments,
        prefetch_oldest_unpaid_payments,
        prefetch_total_outstanding_due_amount,
        prefetch_total_outstanding_amount,
        prefetch_grab_loan_data,
        prefetch_loan_history_180_dpd,
        prefetch_payback_transactions_current_date,
        prefetch_loan_history_from_180_dpd
    ]
    only_fields = ['id', 'loan_status__status', 'loan_xid', 'loan_amount', 'loan_duration',
                   'account__status',
                   'product_id', 'product__admin_fee']

    included_loan_statuses = LoanStatusCodes.grab_current_until_180_dpd() + (
        LoanStatusCodes.FUND_DISBURSAL_ONGOING, LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.HALT)

    # today at 20:00 PM
    today_8_pm = timezone.localtime(
        timezone.now().replace(hour=20, minute=0, second=0, tzinfo=None))
    one_days_ago = today_8_pm - timedelta(days=1)

    paid_off_today_loan_ids = LoanHistory.objects.filter(
        status_new=LoanStatusCodes.PAID_OFF,
        cdate__gte=one_days_ago,
        cdate__lte=today_8_pm
    ).values_list('loan__id', flat=True)

    loan_datas = Loan.objects.select_related(
        'account', 'loan_status', 'product'
    ).prefetch_related(*prefetch_join_tables).only(*only_fields).filter(
        Q(loan_status__in=included_loan_statuses) | (Q(loan_status=LoanStatusCodes.PAID_OFF) & Q(
            id__in=paid_off_today_loan_ids)),
        product__product_line__product_line_code__in=ProductLineCodes.grab()
    ).order_by('-id')[start_index:end_index]

    return loan_datas


def get_grab_previous_day_transaction_by_index(start_index, end_index):
    # today at 20:00 PM
    today_8_pm = timezone.localtime(
        timezone.now().replace(hour=20, minute=0, second=0, tzinfo=None))
    one_days_ago = today_8_pm - timedelta(days=1)

    daily_transaction_datas = AccountTransaction.objects.values(
        'payback_transaction__transaction_id',
        'payback_transaction__transaction_date',
        'payback_transaction__loan__loan_xid'
    ).annotate(
        total_amount=Sum('payback_transaction__amount'),
        total_late_fee=Sum('towards_latefee'),
        total_interest=Sum('towards_interest'),
        total_principal=Sum('towards_principal')
    ).filter(
        payback_transaction__payback_service='grab',
        transaction_type='payment',
        payback_transaction__cdate__gte=one_days_ago,
        payback_transaction__cdate__lte=today_8_pm,
    ).exclude(
        payback_transaction__transaction_date=None
    ).order_by('payback_transaction__transaction_date')[start_index:end_index]

    return daily_transaction_datas


def populate_loans_to_upload_to_oss(start_index, end_index, file_name):
    logger.info({
        "action": "populate_loans_to_upload_to_oss",
        "message": "starting populate grab loans to upload to oss",
        "file_name": file_name
    })
    content = []
    today_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
    is_early_write_off, is_180_dpd_write_off, is_manual_write_off = get_grab_write_off_feature_setting()
    loans = get_grab_active_loan_by_index(start_index, end_index)
    for loan in loans:
        last_payment = Payment.objects.filter(pk=loan.prefetch_payments[-1].id).first()
        logger.info({
            "action": "populate_loans_to_upload_to_oss",
            "message": "processing each loan",
            "loan_id": loan.id
        })
        dpd = 0
        installment_number = 0
        total_installment_principal = 0
        total_installment_interest = 0
        total_interest_paid = 0
        total_principal_paid = 0
        total_late_fee_paid = 0
        total_paid = 0

        admin_fee = 0
        if loan.product and loan.product.admin_fee:
            admin_fee = loan.product.admin_fee

        fee_due = admin_fee if loan.loan_status_id < 220 else 0
        fee_paid = admin_fee if loan.loan_status_id > 220 else 0

        if loan.prefetch_payments:
            for payment in loan.prefetch_payments:
                total_installment_principal += payment.installment_principal
                total_installment_interest += payment.installment_interest
                total_interest_paid += payment.paid_interest
                total_principal_paid += payment.paid_principal

            total_installment_principal = total_installment_principal - total_principal_paid
            total_installment_interest = total_installment_interest - total_interest_paid
            total_paid = total_principal_paid + total_interest_paid + total_late_fee_paid

        halt_date = None
        restructure_date = None
        if loan.grab_loan_data_set:
            halt_date = loan.grab_loan_data_set[0].loan_halt_date
            restructure_date = loan.grab_loan_data_set[0].restructured_date
            if len(loan.grab_oldest_unpaid_payments) > 0:
                dpd = loan.grab_oldest_unpaid_payments[0].get_grab_dpd
                installment_number = loan.grab_oldest_unpaid_payments[0].payment_number

        total_due_amount = 0
        if len(loan.total_outstanding_due_amounts) > 0:
            total_due_amount = sum(
                [payment.due_amount for payment in loan.total_outstanding_due_amounts]
            )

            if loan.grab_loan_data_set and loan.grab_loan_data_set[0].is_repayment_capped:
                installment_amount = loan.installment_amount
                current_date_transactions = loan.current_date_transactions
                total_paid_today = 0
                for current_date_transaction in current_date_transactions:
                    total_paid_today += current_date_transaction.amount
                if total_due_amount >= installment_amount:
                    total_due_amount = installment_amount - total_paid_today
                    if total_due_amount < 0:
                        total_due_amount = 0

        total_outstanding_amount = 0
        if len(loan.total_outstanding_amounts) > 0:
            total_outstanding_amount = sum(
                [payment.due_amount for payment in loan.total_outstanding_amounts]
            )

        loan_status = get_account_summary_loan_status_file_transfer(
            loan, last_payment, is_early_write_off, is_180_dpd_write_off, is_manual_write_off, dpd)
        loan_status_change_date = get_loan_status_change_date(loan, loan_status, last_payment)

        content.append({
            "snapshot_date": today_date,
            "loan_id": loan.loan_xid,
            "max_installment_number": loan.loan_duration,
            "due": loan.installment_amount,
            "paid": total_paid,
            "overdue": total_due_amount,
            "outstanding": total_outstanding_amount,
            "principal_due": total_installment_principal,
            "principal_paid": total_principal_paid,
            "interest_due": total_installment_interest,
            "interest_paid": total_interest_paid,
            "fee_due": fee_due,
            "fee_paid": fee_paid,
            "penalty_due": 0,
            "penalty_paid": 0,
            "dpd": dpd,
            "status_id": loan_status,
            "instalment_number": installment_number,
            "halt_date": halt_date.strftime("%Y-%m-%d") if halt_date else halt_date,
            "restructure_date": restructure_date.strftime(
                "%Y-%m-%d") if restructure_date else restructure_date,
            "loan_status_change_date": loan_status_change_date.strftime(
                "%Y-%m-%d") if loan_status_change_date else loan_status_change_date
        })

    return content


def populate_previous_day_transactions_to_upload_to_oss(start_index, end_index, file_name):
    logger.info({
        "action": "populate_previous_day_transactions_to_upload_to_oss",
        "message": "starting populate grab previous day transactions to upload to oss",
        "file_name": file_name
    })
    content = []
    previous_day_transactions = get_grab_previous_day_transaction_by_index(start_index, end_index)
    for daily_trans in previous_day_transactions:
        txn_date = timezone.localtime(
            daily_trans.get('payback_transaction__transaction_date')
        ).strftime("%Y-%m-%d")
        txn_id = daily_trans.get('payback_transaction__transaction_id')
        loan_xid = daily_trans.get('payback_transaction__loan__loan_xid')
        logger.info({
            "action": "populate_previous_day_transactions_to_upload_to_oss",
            "message": "processing each previous day transactions",
            "txn_id": txn_id
        })

        content.append({
            "txn_date": txn_date,
            "txn_id": txn_id,
            "fee_amount": daily_trans.get("total_late_fee", 0),
            "funding_source": 'grab',
            "interest_amount": daily_trans.get("total_interest", 0),
            "loan_id": loan_xid,
            "penalty_amount": 0.0,
            "principal_amount": daily_trans.get("total_principal", 0),
            "total_txn_amount": daily_trans.get("total_amount", 0)
        })

    return content


def upload_grab_files_to_oss(start_index, end_index, file_name, file_type=GrabAsyncAuditCron.LOANS):
    content = []
    remote_file_path = ""
    today_date = timezone.localtime(timezone.now()).strftime('%Y-%m-%d')
    if file_type == GrabAsyncAuditCron.LOANS:
        content = populate_loans_to_upload_to_oss(start_index, end_index, file_name)
        remote_file_path = 'grab_loans/{}/{}'.format(today_date, file_name)
    elif file_type == GrabAsyncAuditCron.DAILY_TRANSACTIONS:
        content = populate_previous_day_transactions_to_upload_to_oss(start_index, end_index, file_name)
        remote_file_path = 'grab_daily_transactions/{}/{}'.format(today_date, file_name)
    with TempDir() as tempdir:
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, file_name)
        try:
            with open(file_path, "w") as json_file:
                json.dump(content, json_file)

        finally:
            json_file.close()

        upload_file_to_oss(
            settings.OSS_MEDIA_BUCKET,
            file_path,
            remote_file_path
        )
        logger.info({
            "action": "upload_grab_files_to_oss",
            "message": "done uploading files to oss",
            "file_type": file_type,
            "file_name": file_name
        })
        grab_async_audit_cron = GrabAsyncAuditCron.objects.filter(
            cron_file_type=file_type,
            cron_file_name=file_name,
            cron_status=GrabAsyncAuditCron.IN_PROGRESS
        ).last()
        grab_async_audit_cron.cron_status = GrabAsyncAuditCron.COMPLETED
        grab_async_audit_cron.oss_remote_path = remote_file_path
        grab_async_audit_cron.file_uploaded_to_oss = True
        grab_async_audit_cron.cron_end_time = timezone.localtime(timezone.now())
        grab_async_audit_cron.save(update_fields=[
            'cron_status', 'oss_remote_path', 'file_uploaded_to_oss', 'cron_end_time'])


def get_loans_based_on_grab_offset_v3(start_index, end_index):
    grab_payment_queryset = GrabPaymentTransaction.objects.only('id', 'transaction_id',
                                                                'payment_id').all()
    prefetch_grab_payments = Prefetch(
        'grabpaymenttransaction_set', queryset=grab_payment_queryset, to_attr='transaction_ids'
    )
    payment_queryset_fields = [
        'id', 'due_date', 'payment_status_id', 'late_fee_amount', 'paid_principal', 'paid_interest', 'payment_number',
        'due_amount', 'paid_late_fee', 'installment_principal', 'installment_interest', 'paid_principal',
        'paid_interest', 'loan_id'
    ]
    payment_queryset = Payment.objects.select_related('payment_status') \
        .prefetch_related(prefetch_grab_payments).only(*payment_queryset_fields).all().order_by('due_date')
    prefetch_payments = Prefetch('payment_set', to_attr="prefetch_payments", queryset=payment_queryset)
    last_unpaid_payment_queryset = Payment.objects.only('id', 'loan_id', 'due_date') \
        .not_paid_active().order_by('payment_number')
    prefetch_last_unpaid_payments = Prefetch('payment_set', to_attr="grab_last_unpaid_payments",
                                             queryset=last_unpaid_payment_queryset)
    oldest_unpaid_payments_queryset = Payment.objects.only('id', 'loan_id', 'due_date', 'payment_status_id') \
        .not_paid_active().order_by('due_date')
    prefetch_oldest_unpaid_payments = Prefetch('payment_set', to_attr="grab_oldest_unpaid_payments",
                                               queryset=oldest_unpaid_payments_queryset)
    total_outstanding_amount_queryset = Payment.objects.only('id', 'loan_id', 'due_amount').not_paid_active()
    prefetch_total_outstanding_amount = Prefetch('payment_set', to_attr="total_outstanding_amounts",
                                                 queryset=total_outstanding_amount_queryset)
    today = timezone.localtime(timezone.now()).date()
    total_outstanding_due_amount_queryset = Payment.objects.only('id', 'loan_id', 'due_amount', 'payment_status_id') \
        .not_paid_active().filter(due_date__lte=today)
    prefetch_total_outstanding_due_amount = Prefetch('payment_set', to_attr="total_outstanding_due_amounts",
                                                     queryset=total_outstanding_due_amount_queryset)
    grab_loan_data_set = GrabLoanData.objects.only('loan_halt_date', 'loan_resume_date', 'id', 'loan_id')
    prefetch_grab_loan_data = Prefetch('grabloandata_set', to_attr='grab_loan_data_set',
                                       queryset=grab_loan_data_set)

    prefetch_applications = Prefetch(
        'account__application_set', to_attr="applications",
        queryset=Application.objects.only('application_xid', 'id', 'account_id').all().order_by('-id')
    )
    prefetch_join_tables = [
        prefetch_applications,
        prefetch_payments,
        prefetch_last_unpaid_payments,
        prefetch_oldest_unpaid_payments,
        prefetch_total_outstanding_due_amount,
        prefetch_total_outstanding_amount,
        prefetch_grab_loan_data
    ]
    only_fields = ['id', 'loan_status__status', 'loan_xid', 'loan_amount', 'loan_duration', 'account__status',
                   'product_id', 'product__admin_fee']
    return Loan.objects.select_related('account', 'loan_status', 'product').prefetch_related(*prefetch_join_tables) \
               .only(*only_fields)\
               .filter(account__account_lookup__workflow__name=WorkflowConst.GRAB)\
               .order_by('-id')[start_index:end_index]


def update_grab_referral_code(application, referral_code):
    if referral_code and referral_code != '':
        customer = Customer.objects.filter(
            self_referral_code=referral_code.upper()).last()
        if not customer:
            return
        grab_referral_code = GrabReferralCode.objects.filter(
            application=application
        ).last()
        if not grab_referral_code:
            GrabReferralCode.objects.get_or_create(
                application=application,
                referred_customer=customer,
                referral_code=referral_code
            )
        else:
            grab_referral_code.update_safely(
                referred_customer=customer,
                referral_code=referral_code
            )


def get_audit_oss_links(event_date, file_number, file_type: GrabAsyncAuditCron.LOANS):
    regex_raw_string = r'loans_{event_date_format}_{regex_file_number}.json'
    if file_type == GrabAsyncAuditCron.DAILY_TRANSACTIONS:
        regex_raw_string = r'daily_transactions_{event_date_format}_{regex_file_number}.json'
    regex_string = regex_raw_string.format(
        event_date_format=event_date.strftime("%Y-%m-%d"), regex_file_number=r'\d{1,}')
    grab_async_audit_cron = GrabAsyncAuditCron.objects.filter(
        cron_file_name__regex=regex_string,
        event_date=event_date.strftime('%Y-%m-%d')
    )
    total_completed_crons = grab_async_audit_cron.filter(
        cron_status=GrabAsyncAuditCron.COMPLETED).count()
    total_inprogess_crons = grab_async_audit_cron.filter(
        cron_status=GrabAsyncAuditCron.IN_PROGRESS).count()
    total_initiated_crons = grab_async_audit_cron.filter(
        cron_status=GrabAsyncAuditCron.INITIATED).count()
    total_failed_crons = grab_async_audit_cron.filter(
        cron_status=GrabAsyncAuditCron.FAILED).count()
    return_data = {
        "file_type": file_type,
        "completed_files": total_completed_crons,
        "inprogress_files": total_inprogess_crons,
        "initiated_files": total_initiated_crons,
        "failed_files": total_failed_crons,
        "files": list()
    }
    files_list = list()
    if not file_number:
        for grab_cron in grab_async_audit_cron.iterator():
            file_number = re.findall(
                r"\d{1,}", grab_cron.cron_file_name)
            if len(file_number) > 1:
                file_number = int(file_number[-1])
            else:
                continue
            if grab_cron.cron_status == GrabAsyncAuditCron.COMPLETED:
                files_list.append(file_number)
            else:
                file_dict = {
                    "file_number": file_number,
                    "url": None
                }
                return_data['files'].append(file_dict)
        file_numbers = list(set(files_list))

        for file_number in file_numbers:
            file_dict = get_details_file_link(file_number, event_date, file_type)
            return_data['files'].append(file_dict)
        return return_data
    file_dict = get_details_file_link(file_number, event_date, file_type)
    files_list.append(file_dict)
    return_data['files'] = files_list
    return return_data


def get_details_file_link(file_number, event_date, file_type: GrabAsyncAuditCron.LOANS):
    regex_raw_string = r'loans_{event_date_format}_{regex_file_number}.json'
    if file_type == GrabAsyncAuditCron.DAILY_TRANSACTIONS:
        regex_raw_string = r'daily_transactions_{event_date_format}_{regex_file_number}.json'
    file_name = regex_raw_string.format(
        event_date_format=event_date.strftime("%Y-%m-%d"), regex_file_number=str(file_number))
    grab_async_audit_cron = GrabAsyncAuditCron.objects.filter(
        cron_file_name=file_name
    ).last()
    if not grab_async_audit_cron:
        raise GrabLogicException("INVALID FILE NAME")
    if grab_async_audit_cron.cron_status in {
        GrabAsyncAuditCron.IN_PROGRESS, GrabAsyncAuditCron.INITIATED}:
        raise GrabLogicException("Still in Progress")
    if grab_async_audit_cron.cron_status == GrabAsyncAuditCron.FAILED:
        raise GrabLogicException("File Creation Failed")
    remote_path = grab_async_audit_cron.oss_remote_path
    url = get_oss_presigned_url_external(
        settings.OSS_MEDIA_BUCKET,
        remote_path,
        expires_in_seconds=300
    )
    files_dict = {
        "file_number": file_number,
        "url": url
    }
    return files_dict


def get_loan_status_change_date(loan, loan_status, last_payment=None):
    loan_status_change_date = None
    if loan_status == GrabWriteOffStatus.EARLY_WRITE_OFF:
        loan_status_change_date = loan.grab_loan_data_set[0].early_write_off_date
    elif loan_status == GrabWriteOffStatus.WRITE_OFF_180_DPD:
        if loan.loan_histories_180_dpd:
            loan_history = loan.loan_histories_180_dpd[-1]
            loan_status_change_date = loan_history.cdate
    elif loan_status == GrabWriteOffStatus.MANUAL_WRITE_OFF and last_payment:
        last_payment_event = last_payment.paymentevent_set.last()
        if last_payment_event:
            account_transaction = last_payment_event.account_transaction
            loan_status_change_date = account_transaction.cdate
    else:
        loan_history = loan.loanhistory_set.last()
        loan_status_change_date = loan_history.cdate if loan_history else None
    return loan_status_change_date


def get_manual_write_off_payment_details(last_payment_id):
    payment_event_qs = PaymentEvent.objects.select_related('account_transaction').all().order_by(
        'cdate')
    prefetched_payment_events = Prefetch('paymentevent_set', payment_event_qs,
                                         to_attr='prefetch_payment_event')
    payment_qs = Payment.objects.prefetch_related(*[prefetched_payment_events]).filter(
        id=last_payment_id)
    return payment_qs


def mapping_grab_file_transfer_file_type(file_type: str) -> str:
    mapped_file_type = GrabAsyncAuditCron.LOANS
    if file_type == 'transaction':
        mapped_file_type = GrabAsyncAuditCron.DAILY_TRANSACTIONS
    return mapped_file_type


def check_grab_auth_status(loan_id):
    status = GrabAuthStatus.PENDING
    last_auth_grab_api_log = GrabAPILog.objects.filter(
        loan_id=loan_id, query_params=GrabPaths.LOAN_CREATION).last()
    loan = Loan.objects.filter(pk=loan_id).last()
    if last_auth_grab_api_log:
        if last_auth_grab_api_log.http_status_code == https_status_codes.HTTP_200_OK:
            status = GrabAuthStatus.SUCCESS
        elif last_auth_grab_api_log.external_error_code == str(GrabAuthAPIErrorCodes.ERROR_CODE_4002):
            status = GrabAuthStatus.FAILED_4002
        else:
            is_pending_status = ((last_auth_grab_api_log.external_error_code in list(map(
                str, [
                    GrabAuthAPIErrorCodes.ERROR_CODE_5001,
                    GrabAuthAPIErrorCodes.ERROR_CODE_5002,
                    GrabAuthAPIErrorCodes.ERROR_CODE_8002
                ])) or last_auth_grab_api_log.http_status_code >=
                                  https_status_codes.HTTP_500_INTERNAL_SERVER_ERROR
                                  ) and loan.loan_status_id == LoanStatusCodes.INACTIVE)
            if is_pending_status:
                status = GrabAuthStatus.PENDING
            else:
                status = GrabAuthStatus.FAILED
    return status


def validate_grab_application_auth(application_190, loan, retry_attempt):
    is_grab_application_creation_called = GrabAPILog.objects.filter(
        customer_id=loan.customer.id,
        application_id=application_190.id,
        query_params__contains=GrabPaths.APPLICATION_CREATION,
        http_status_code=https_status_codes.HTTP_200_OK
    ).exists()
    logger.info({
        "task": "trigger_auth_call_for_loan_creation",
        "status": "Checking Application_creation_called",
        "loan_id": loan.id,
        "is_grab_application_called": is_grab_application_creation_called,
        "retry_attempt": retry_attempt
    })
    if not is_grab_application_creation_called:
        trigger_application_creation_grab_api.apply_async((application_190.id,))
        update_loan_status_and_loan_history(
            loan_id=loan.id,
            new_status_code=LoanStatusCodes.LENDER_REJECT,
            change_reason="Grab API Error - Application Data missing",
        )
        raise GrabLogicException("No successful grab application creation - {}".format(application_190.id))


def create_grab_experiment(experiment_name: str = "grab experiment",
                           grab_customer_data_id: int = None,
                           grab_loan_data_id: int = None,
                           parameters=None) -> GrabExperiment:
    """
    record grab experiment table
    """
    if parameters is None:
        parameters = {}

    grab_customer_data = GrabCustomerData.objects.get_or_none(id=grab_customer_data_id)
    grab_loan_data = GrabLoanData.objects.get_or_none(id=grab_loan_data_id)

    if not GrabExperiment.objects.filter(grab_customer_data=grab_customer_data,
                                         parameters=parameters).exists():
        try:
            grab_experiment = GrabExperiment.objects.create(
                experiment_name=experiment_name,
                grab_customer_data=grab_customer_data,
                grab_loan_data=grab_loan_data,
                parameters=parameters
            )
            return grab_experiment
        except IntegrityError as err:
            error_string = str(err)
            logger.info({
                "action": "create_grab_experiment",
                "error_message": error_string
            })
            raise GrabLogicException(error_string)


def update_grab_experiment_by_grab_customer_data_id(experiment_name: str = "grab experiment",
                                                    grab_customer_data_id: int = None,
                                                    grab_loan_data_id: int = None,
                                                    parameters=None) -> GrabExperiment:
    """
    update grab experiment table by grab customer data
    """
    if parameters is None:
        parameters = {}

    try:
        grab_customer_data = GrabCustomerData.objects.get_or_none(id=grab_customer_data_id)
        grab_loan_data = GrabLoanData.objects.get_or_none(id=grab_loan_data_id)
        grab_experiment = GrabExperiment.objects.select_for_update().filter(
            grab_customer_data=grab_customer_data).last()
        grab_experiment.update_safely(experiment_name=experiment_name,
                                      grab_loan_data=grab_loan_data,
                                      parameters=parameters)
        return grab_experiment
    except (GrabExperiment.DoesNotExist, IntegrityError) as err:
        error_string = str(err)
        logger.info({
            "action": "update_grab_experiment_by_grab_customer_data_id",
            "error_message": error_string
        })
        raise GrabLogicException(error_string)


def process_additional_smaller_loan_offer_option(
        min_loan_result,
        max_loan_result,
        min_tenure,
        max_tenure,
        interest_rate,
        upfront_fee,
        offer_threshold
):
    # PRD link : https://juloprojects.atlassian.net/wiki/spaces/PD/pages/3149627408/Showing+Smaller+Loan+Offer+Options
    additional_options = []
    additional_loan_options_count = 0
    response = []
    slo_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GRAB_SMALLER_LOAN_OPTION,
        is_active=True
    ).last()
    if slo_feature_setting and slo_feature_setting.parameters:
        slo_parameters = slo_feature_setting.parameters
        loan_amount_eligible = slo_parameters.get('min_loan_amount', 3500000)
        loan_tenure_eligible = slo_parameters.get('loan_tenure', 180)
        range_to_max_gen_loan_amount = slo_parameters.get('range_to_max_gen_loan_amount',
                                                          2000000)

        # criteria checking
        eligible_criteria = set()
        if min_loan_result <= loan_amount_eligible <= max_loan_result:
            eligible_criteria.add(1)
        if max_loan_result - loan_amount_eligible >= range_to_max_gen_loan_amount:
            eligible_criteria.add(2)
        if min_tenure <= loan_tenure_eligible <= max_tenure:
            eligible_criteria.add(3)

        if eligible_criteria == {1, 2, 3}:
            for index, loan_option_percentage in enumerate(
                    slo_parameters.get('loan_option_range')):
                loan_option_range_digit = re.match(r'(\d+)%', loan_option_percentage).group(
                    1)
                calculated_eligible_amount = max_loan_result - loan_amount_eligible
                calculated_with_percentage = (calculated_eligible_amount * int(
                    loan_option_range_digit)) / 100
                calculate_loan_amount = int(loan_amount_eligible + calculated_with_percentage)
                daily_installment_amount = get_daily_repayment_amount(
                    calculate_loan_amount, loan_tenure_eligible,
                    interest_rate)
                weekly_instalment_amount = get_weekly_instalment_amount(
                    calculate_loan_amount, loan_tenure_eligible)
                if (daily_installment_amount * 7) > int(offer_threshold):
                    continue
                temp_option = {
                    "tenure": loan_tenure_eligible,
                    "daily_repayment": daily_installment_amount,
                    "repayment_amount": int(daily_installment_amount) * int(
                        loan_tenure_eligible),
                    "loan_disbursement_amount": int(calculate_loan_amount) - int(
                        upfront_fee),
                    "weekly_instalment_amount": weekly_instalment_amount,
                    "loan_amount": int(calculate_loan_amount),
                    "smaller_loan_option_flag": True
                }
                if index == 0:
                    additional_options.append(temp_option)
                else:
                    response.append(temp_option)
                additional_loan_options_count += 1

        if 1 in eligible_criteria and 3 in eligible_criteria:
            daily_installment_amount = get_daily_repayment_amount(
                loan_amount_eligible, loan_tenure_eligible,
                interest_rate)
            weekly_instalment_amount = get_weekly_instalment_amount(
                loan_amount_eligible, loan_tenure_eligible)
            if not (daily_installment_amount * 7) > int(offer_threshold):
                additional_options.append({
                    "tenure": loan_tenure_eligible,
                    "daily_repayment": daily_installment_amount,
                    "repayment_amount": int(daily_installment_amount) * int(
                        loan_tenure_eligible),
                    "loan_disbursement_amount": int(loan_amount_eligible) - int(
                        upfront_fee),
                    "weekly_instalment_amount": weekly_instalment_amount,
                    "loan_amount": int(loan_amount_eligible),
                    "smaller_loan_option_flag": True
                })
                additional_loan_options_count += 1

    return additional_options, additional_loan_options_count, response


def process_update_grab_experiment_by_grab_customer_data(validated_data, grab_customer_data,
                                                         grab_loan_data):
    # update grab experiment by grab customer data
    if validated_data.get("smaller_loan_option_flag"):
        grab_experiment = GrabExperiment.objects.select_for_update().filter(
            grab_customer_data=grab_customer_data).last()
        params = grab_experiment.parameters
        params["loan_offer"] = {
            "program_id": validated_data["program_id"],
            "max_loan_amount": validated_data["max_loan_amount"],
            "min_loan_amount": validated_data["min_loan_amount"],
            "instalment_amount": validated_data["instalment_amount_plan"],
            "loan_duration": validated_data["tenure_plan"],
            "frequency_type": validated_data["frequency_type"],
            "fee_value": validated_data["fee_value_plan"],
            "loan_disbursement_amount": validated_data["loan_disbursement_amount"],
            "interest_type": validated_data["interest_type_plan"],
            "interest_value": validated_data["interest_value_plan"],
            "penalty_type": validated_data["penalty_type"],
            "penalty_value": validated_data["penalty_value"]
        }
        update_grab_experiment_by_grab_customer_data_id(
            experiment_name="smaller_loan_option",
            grab_customer_data_id=grab_customer_data.id,
            grab_loan_data_id=grab_loan_data.id,
            parameters=params
        )


def add_account_in_temp_table(loan):
    grab_ai_rudder_delete_phone_number = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_AI_RUDDER_DELETE_PHONE_NUMBER, is_active=True)
    if not grab_ai_rudder_delete_phone_number:
        return False

    if loan.account and loan.account.id:
        account_id = loan.account.id
        today = timezone.localtime(timezone.now()).date()
        if GrabTempAccountData.objects.filter(account_id=account_id,
                                              cdate__date=today).exists():
            return False
        GrabTempAccountData.objects.create(account_id=account_id)

    return True


def block_users_other_than_grab(user):
    application = user.customer.application_set.exclude(
        product_line_id=ProductLineCodes.GRAB
    ).last()
    if application and (
        application.application_status_id <= ApplicationStatusCodes.FORM_PARTIAL
        or application.application_status_id >= ApplicationStatusCodes.LOC_APPROVED
        or application.application_status_id
        in (
            ApplicationStatusCodes.OFFER_REGULAR,
            ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK,
            ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED,
        )
    ):
        return False

    return True


def validate_customer_phone_number(phone):
    customer = Customer.objects.filter(phone=phone).first()
    application_statuses = {
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED, ApplicationStatusCodes.APPLICATION_DENIED
    }
    if customer:
        application = customer.application_set.filter(mobile_phone_1=phone).last()
        if application and (application.application_status_id not in application_statuses):
            return False
    else:
        application = Application.objects.filter(mobile_phone_1=phone).exclude(
            product_line_id=ProductLineCodes.GRAB).last()
        if application and (application.application_status_id not in application_statuses):
            return False

    return True


def get_mobile_phone_otp_settings_grab():
    mobile_feature_setting = MobileFeatureSetting.objects.filter(
        feature_name=FeatureSettingName.COMPULSORY, is_active=True
    ).last()

    if not mobile_feature_setting:
        raise GrabLogicException("MobileFeature Not available/supported")

    phone_settings = mobile_feature_setting.parameters.get('mobile_phone_1')
    if not phone_settings:
        raise GrabLogicException("MobileFeature Not available/supported")
    otp_max_request = phone_settings.get('otp_max_request')
    otp_max_validate = phone_settings.get('otp_max_validate')
    otp_resend_time_sms = phone_settings.get('otp_resend_time_sms')
    wait_time_seconds = mobile_feature_setting.parameters.get('wait_time_seconds')

    return otp_max_request, otp_max_validate, otp_resend_time_sms, wait_time_seconds


def get_total_retries_and_start_create_time_grab_otp(phone_number: str, otp_wait_time: int):
    now = timezone.localtime(timezone.now())
    filter_params = {'phone_number': phone_number, 'customer__isnull': True}
    otp_requests = OtpRequest.objects.filter(
        **filter_params, cdate__gte=now - relativedelta(seconds=otp_wait_time)
    )
    otp_requests = otp_requests.order_by('-id')

    otp_request_count = otp_requests.count()
    last_request_timestamp = None if not otp_request_count else otp_requests.last().cdate

    return otp_request_count, last_request_timestamp


def get_latest_available_otp_request_grab(service_types, phone_number):
    otp_request = (
        OtpRequest.objects.filter(
            phone_number=phone_number,
            otp_service_type__in=service_types,
            action_type=SessionTokenAction.PHONE_REGISTER,
        )
        .order_by('id')
        .last()
    )
    return otp_request


def get_missed_called_otp_creation_active_flags(
    existing_otp_request, otp_resend_time_sms, wait_time_seconds, retry_count
):
    """
    This function is to check if the OTP is still active or not.
    This will check if a new OTP is to created or not.
    """
    is_resent_otp = False
    is_otp_active = False

    curr_time = timezone.localtime(timezone.now())
    if existing_otp_request:
        previous_time = existing_otp_request.cdate
        previous_otp_resend_time = otp_resend_time_sms
        previous_resend_time = timezone.localtime(previous_time) + relativedelta(
            seconds=previous_otp_resend_time
        )
        is_otp_active = check_otp_request_is_active(
            existing_otp_request, wait_time_seconds, curr_time
        )
        if is_otp_active:
            if curr_time < previous_resend_time:
                logger.info(
                    {
                        'request_time': previous_time,
                        'expired_time': previous_time + relativedelta(seconds=wait_time_seconds),
                        'retry_count': retry_count - 1,
                        'resend_time': previous_resend_time,
                    }
                )
            else:
                is_resent_otp = True
    create_new_otp = (
        False if (existing_otp_request and is_otp_active) and not is_resent_otp else True
    )
    return create_new_otp, is_resent_otp


def reset_pin_ext_date():
    mobile_feature_setting = MobileFeatureSetting.objects.get_or_none(
        feature_name=MobileFeatureNameConst.LUPA_PIN, is_active=True
    )
    request_time = {'days': 0, 'hours': 24, 'minutes': 0}
    if mobile_feature_setting and 'pin_users_link_exp_time' in mobile_feature_setting.parameters:
        request_time = mobile_feature_setting.parameters['pin_users_link_exp_time']

    reset_pin_exp_date = timezone.localtime(timezone.now()) + timedelta(
        days=request_time.get('days'),
        hours=request_time.get('hours'),
        minutes=request_time.get('minutes'),
    )
    return reset_pin_exp_date


def process_reset_pin_request(customer):
    password_type = 'pin'
    email = customer.email
    phone_number = customer.phone
    new_key_needed = False
    customer_pin_change_service = CustomerPinChangeService()
    if customer.reset_password_exp_date is None:
        new_key_needed = True
    elif customer.has_resetkey_expired() or not customer_pin_change_service.check_key(customer.reset_password_key):
        new_key_needed = True

    if new_key_needed:
        reset_pin_key = generate_email_key(email)
        customer.reset_password_key = reset_pin_key
        reset_pin_exp_date = reset_pin_ext_date()
        customer.reset_password_exp_date = reset_pin_exp_date
        customer.save()
        customer_pin = customer.user.pin
        customer_pin_change_service.init_customer_pin_change(
            email=email,
            phone_number=phone_number,
            expired_time=reset_pin_exp_date,
            customer_pin=customer_pin,
            change_source='Forget PIN',
            reset_key=reset_pin_key,
        )
        logger.info(
            {
                'status': 'grab_just_generated_reset_%s' % password_type,
                'phone_number': phone_number,
                'customer': customer,
                'reset_%s_key' % password_type: reset_pin_key,
                'reset_%s_exp_date' % password_type: reset_pin_exp_date,
            }
        )
    else:
        reset_pin_key = customer.reset_password_key
        logger.info(
            {
                'status': 'grab_reset_%s_key_already_generated' % password_type,
                'phone_number': phone_number,
                'customer': customer,
                'reset_%s_key' % password_type: reset_pin_key,
            }
        )
    grab_send_reset_pin_sms.delay(customer, phone_number, reset_pin_key)


def add_grab_loan_promo_code(promo_code, grab_loan_data_id):
    promo_code_obj = validate_grab_promo_code(promo_code)
    if promo_code_obj and not GrabLoanPromoCode.objects.filter(promo_code=promo_code_obj,
                                                               grab_loan_data_id=grab_loan_data_id).exists():
            GrabLoanPromoCode.objects.get_or_create(
                promo_code=promo_code_obj,
                grab_loan_data_id=grab_loan_data_id
            )


def validate_grab_promo_code(promo_code):
    today = timezone.localtime(timezone.now()).date()
    promo_code_obj = GrabPromoCode.objects.filter(
        promo_code=promo_code,
        active_date__lte=today,
        expire_date__gte=today
    ).last()
    return promo_code_obj


def update_grab_loan_promo_code_with_loan_id(grab_loan_data_id, loan_id):
    grab_loan_promo_code = GrabLoanPromoCode.objects.filter(grab_loan_data_id=grab_loan_data_id).last()
    if grab_loan_promo_code:
        promo_code_obj = validate_grab_promo_code(grab_loan_promo_code.promo_code)
        if promo_code_obj:
            grab_loan_promo_code.update_safely(loan_id=loan_id, status=PromoCodeStatus.APPLIED)


class GrabUserExperimentService(object):
    @staticmethod
    def get_user_experiment_group(grab_customer_data_id: int) -> dict:
        experiment_group, _ = trigger_store_grab_customer_data_to_growthbook(grab_customer_data_id)

        data = {
            'experiment_group': experiment_group
        }
        return data


class EmergencyContactService(object):
    def __init__(self, redis_client=None, sms_client=None):
        self.base_url = 'emergency-contact-{}'
        self.redis_client = redis_client
        self.redis_key = "grab_emergency_contact_app_ids"
        self.reapply_redis_key = "grab_emergency_contact_reapply_app_ids"
        self.sms_client = sms_client
        self.template_code = "grab_emergency_contact"

    def get_feature_settings_parameters(self):
        feature_settings = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.GRAB_EMERGENCY_CONTACT,
            is_active=True
        ).last()
        if not feature_settings:
            return None

        return feature_settings.parameters

    def hashing_unique_link(self, unique_link):
        key = settings.GRAB_HMAC_SECRET
        return hmac.new(key.encode(), unique_link.encode(), hashlib.sha256).hexdigest()

    def validate_hashing(self, unique_link, hashed_unique_link) -> bool:
        result = self.hashing_unique_link(unique_link)
        return result == hashed_unique_link

    def generate_unique_link(self, application_id, application_kin_name):
        now = datetime.datetime.now().strftime("%s")
        concated_string = "{}_{}_{}".format(
            now,
            application_id,
            application_kin_name
        ).replace(' ', '')
        unique_id = shortuuid.ShortUUID(concated_string).random(length=8)
        return self.base_url.format(unique_id)

    def save_application_id_to_redis(self, application_id, key=None):
        if not key:
            key = self.redis_key
        self.redis_client.sadd(key, [application_id])

    def pop_application_ids_from_redis(self, key=None):
        if not key:
            key = self.redis_key

        n_chunk = 50
        temp_app_ids = []
        for application_id in self.redis_client.smembers(key):
            application_id = application_id.decode()

            temp_app_ids.append(application_id)
            yield application_id

            if len(temp_app_ids) > n_chunk:
                self.redis_client.srem(key, *temp_app_ids)

        if len(temp_app_ids) > 0:
            self.redis_client.srem(key, *temp_app_ids)

    def set_expired_time(self, opt_out_in_hour):
        return timezone.localtime(timezone.now()) + timedelta(hours=opt_out_in_hour)

    def create_emergency_contact_approval_link(self, application_id, unique_link, expiration_date):
        EmergencyContactApprovalLink.objects.create(
            application_id=application_id,
            unique_link=unique_link,
            expiration_date=expiration_date,
            is_used=False
        )

    def is_ec_received_sms_before(self, application_id, hours=0):
        application = Application.objects.filter(
            id=application_id).values('customer_id', 'kin_mobile_phone').first()
        kin_mobile_phone = format_e164_indo_phone_number(application.get('kin_mobile_phone'))

        sms_history_qs = SmsHistory.objects.filter(
            template_code=self.template_code,
            customer_id=application.get('customer_id'),
            to_mobile_phone=kin_mobile_phone
        )

        if hours > 0:
            sms_history_qs = sms_history_qs.filter(
                cdate__gte=timezone.localtime(timezone.now()) - timedelta(hours=hours)
            )

        return sms_history_qs.exists()

    def send_sms_to_ec(self, application_id, unique_link, hashed_unique_link) -> bool:
        application = Application.objects.get_or_none(id=application_id)

        if not application:
            return False

        host_name = GRAB_DOMAIN_NAME[settings.ENVIRONMENT]
        link = "https://{}/{}?unique_code={}".format(host_name, unique_link, hashed_unique_link)
        link = shorten_url(link)
        message = "Halo, {} memilihmu sbg kontak darurat di GrabModal. Lihat detail dan konfirmasi" \
            " dengan klik di sini: {}".format(application.customer.fullname, link)

        phone = format_e164_indo_phone_number(application.kin_mobile_phone)
        msg, responses = self.sms_client.send_sms(phone, message)
        for response in responses.get("messages", []):
            create_sms_history(
                response=response,
                customer=application.customer,
                application=application,
                to_mobile_phone=format_e164_indo_phone_number(response['to']),
                phone_number_type='kin_mobile_phone',
                template_code=self.template_code,
                message_content=msg
            )
        return True

    def is_ec_approval_link_valid(self, unique_link) -> Iterable[Union[int, bool]]:
        ec_approval_link = EmergencyContactApprovalLink.objects.filter(
            unique_link=unique_link).values('application_id', 'expiration_date', 'is_used').first()

        if not ec_approval_link:
            return 0, False

        if not ec_approval_link.get('expiration_date'):
            return 0, False

        if ec_approval_link.get('expiration_date') < timezone.localtime(timezone.now()) or \
            ec_approval_link.get('is_used'):
            return 0, False

        return ec_approval_link.get('application_id'), True

    def proccess_ec_response(self, application_id, ec_response):
        application = Application.objects.get(id=application_id)
        if not application:
            return False

        application.is_kin_approved = ec_response.get('response')
        application.save()
        return True

    def get_expired_emergency_approval_link_queryset(self):
        now = timezone.localtime(timezone.now())
        expired_ec_approval_link_qs = EmergencyContactApprovalLink.objects.filter(
            expiration_date__lte=now).exclude(is_used=True)

        return expired_ec_approval_link_qs

    def auto_reject_ec_consent(self, expired_ec_approval_link_qs):
        batch_size = 50
        application_ids = []
        approval_link_ids = []
        for ec_approval_link in expired_ec_approval_link_qs.\
            values("id", "application_id").iterator():
            application_ids.append(ec_approval_link.get("application_id"))
            approval_link_ids.append(ec_approval_link.get('id'))

            if len(application_ids) == batch_size:
                Application.objects.filter(id__in=application_ids).update(is_kin_approved=2)
                EmergencyContactApprovalLink.objects.filter(id__in=approval_link_ids).update(
                    is_used=True
                )
                application_ids = []
                approval_link_ids = []

        if application_ids:
            Application.objects.filter(id__in=application_ids).update(is_kin_approved=2)
            EmergencyContactApprovalLink.objects.filter(id__in=approval_link_ids).update(
                is_used=True
            )

    def fetch_records(self, limit, offset):
        query = """
        select
            distinct on
            (a.customer_id,
            a.kin_mobile_phone) ecal.emergency_contact_approval_link_id,
            ecal.application_id,
            ecal.unique_link
        from
            emergency_contact_approval_link ecal
        join application a on
            a.application_id = ecal.application_id
        where
            ecal.expiration_date >= (TIMESTAMP '{}' AT TIME ZONE 'Asia/Jakarta' AT TIME ZONE 'UTC')
            and
            (ecal.is_used is null or ecal.is_used = 'false')
        order by
            a.customer_id,
            a.kin_mobile_phone,
            ecal.emergency_contact_approval_link_id desc
        limit {} offset {};
        """.format(timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S'), limit, offset)

        result = []
        for i in EmergencyContactApprovalLink.objects.raw(query):
            result.append({
                'id': i.id,
                'application_id': i.application_id,
                'unique_link': i.unique_link
            })
        return result

    def get_paginated_record(self, page_number=1):
        page_size = 50
        offset = (page_number - 1) * page_size
        records = self.fetch_records(page_size, offset)
        return records

    def get_ec_that_need_to_resend_sms(self):
        page_number = 1
        while True:
            ec_approval_link_data = self.get_paginated_record(page_number=page_number)
            page_number += 1
            if not ec_approval_link_data:
                break

            ec_that_received_sms_in_last_24_hours = SmsHistory.objects.filter(
                template_code='grab_emergency_contact',
                cdate__gte=timezone.localtime(timezone.now()) - timedelta(hours=24),
                application_id__in=[i.get('application_id') for i in ec_approval_link_data]
            ).values('application_id')

            exclude_query = ""
            if len(ec_that_received_sms_in_last_24_hours) > 0:
                excluded_application_ids = ', '.join(
                    [str(i.get('application_id')) for i in ec_that_received_sms_in_last_24_hours])
                exclude_query = "and ecal.application_id not in ({})".format(
                    excluded_application_ids
                )

            raw_query = """
                select
                    ecal.emergency_contact_approval_link_id,
                    ecal.application_id,
                    ecal.unique_link
                from
                    emergency_contact_approval_link ecal
                where
                    ecal.emergency_contact_approval_link_id in ({})
                    {}
                order by
                    ecal.emergency_contact_approval_link_id desc;
            """.format(
                ', '.join([str(i.get('id')) for i in ec_approval_link_data]),
                exclude_query
            )
            filtered_ec = EmergencyContactApprovalLink.objects.raw(raw_query)
            result = []
            for i in filtered_ec:
                result.append({
                    'id': i.id,
                    'application_id': i.application_id,
                    'unique_link': i.unique_link
                })

            yield result

    def delete_old_emergency_contact_approval_link(self):
        old_ec_approval_link = EmergencyContactApprovalLink.objects.filter(
            cdate__lt=timezone.localtime(timezone.now()) - timedelta(days=14),
            is_used=True
        )

        old_ec_approval_link.delete()


class GrabRestructureHistoryLogService(object):
    def create_restructure_history_entry_bulk(
        self,
        datas: List[Dict],
        is_restructured: bool
    ) -> Tuple[int, int]:
        """
        function to create entry in GrabRestructreHistoryLog table

        is_restructured = False means revert/unrestructure
        """

        list_of_restructure_history_log_data = []
        for data in datas:
            have_loan_id = 'loan_id' in data
            have_restructure_date = 'restructure_date' in data

            if False in [have_loan_id, have_restructure_date]:
                continue

            list_of_restructure_history_log_data.append(
                GrabRestructreHistoryLog(
                    loan_id=data.get("loan_id"),
                    restructure_date=data.get("restructure_date"),
                    is_restructured=is_restructured
                )
            )

        n_inserted = GrabRestructreHistoryLog.objects.bulk_create(
            list_of_restructure_history_log_data,
        )

        return len(datas), len(n_inserted)

    def fetch_loan_id_by_xid(self, datas: Dict) -> Dict:
        loans_xid = datas.keys()
        for loan_data in Loan.objects.filter(
            loan_xid__in=loans_xid).values('id', 'loan_xid').iterator():
            datas[loan_data["loan_xid"]].update({"loan_id": loan_data["id"]})
        return datas
