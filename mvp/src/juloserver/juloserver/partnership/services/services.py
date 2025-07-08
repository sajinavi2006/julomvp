import logging
import os
import re
import random
import datetime
import requests
from datetime import timedelta, datetime as datetime2
import pyotp
import time
import urllib.parse

from PIL import Image as Imagealias
from collections import namedtuple
from io import BytesIO

from bulk_update.helper import bulk_update
from django.core.files import File
from django.db import transaction
from django.db.models import F, Prefetch, Func, Value, CharField
from django.db.models.functions import Lower
from django.contrib.auth.models import User, Group
from django.contrib.auth.hashers import make_password
from django.conf import settings
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.utils import IntegrityError
from django.forms.models import model_to_dict

from rest_framework.request import Request
from rest_framework.response import Response

from juloserver.customer_module.utils.utils_crm_v1 import (
    get_deletion_nik_format,
    get_deletion_email_format,
    get_deletion_phone_format,
)
from juloserver.fdc.services import get_and_save_fdc_data
from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.followthemoney.models import LenderBalanceCurrent
from juloserver.otp.constants import OTPType

from juloserver.standardized_api_response.utils import (general_error_response,
                                                        success_response,
                                                        created_response,
                                                        forbidden_error_response,
                                                        unauthorized_error_response)

from juloserver.application_flow.services import (
    assign_julo1_application,
    store_application_to_experiment_table,
)
from juloserver.pin.services import (
    CustomerPinService,
    VerifyPinProcess
)
import juloserver.julo.services as julo_services
import juloserver.apiv2.services as apiv2_services
from juloserver.julo.tasks import create_application_checklist_async
from juloserver.julo.models import (
    Application,
    Customer,
    CustomerFieldChange,
    FDCInquiry,
    FDCInquiryLoan,
    Partner,
    OtpRequest,
    AddressGeolocation,
    SmsHistory,
    Image,
    LoanPurpose,
    MobileFeatureSetting,
    ProductLine,
    ProductProfile,
    ProductLookup,
    Workflow,
    WorkflowStatusPath,
    ApplicationHistory,
    AwsFaceRecogLog,
    FaceRecognition,
    FeatureSetting,
    CreditScore,
    SepulsaProduct,
    Payment,
    Loan,
    ApplicationNote,
    ApplicationFieldChange,
    SphpTemplate,
    HighScoreFullBypass,
    ITIConfiguration,
    JobType,
)
from juloserver.julo.services import update_customer_data, process_application_status_change
from juloserver.julo.constants import (
    ApplicationStatusCodes,
    FeatureNameConst,
    VendorConst,
    WorkflowConst,
    XidIdentifier,
)
from juloserver.julo.services2 import encrypt, get_customer_service
from juloserver.apiv3.models import (ProvinceLookup,
                                     CityLookup,
                                     DistrictLookup,
                                     SubDistrictLookup)
from juloserver.julo.tasks import send_sms_otp_token
from juloserver.julo.exceptions import SmsNotSent
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.apiv1.data import DropDownData
from juloserver.apiv1.dropdown import BirthplaceDropDown
from juloserver.api_token.authentication import make_never_expiry_token
from juloserver.apiv3.serializers import SubDistrictLookupResSerializer
from juloserver.partnership.tasks import notify_user_linking_account, upload_image_partnership
from juloserver.julo.admin2.job_data_constants import JOB_INDUSTRY_LIST, JOB_MAPPING

from juloserver.julo.product_lines import ProductLineCodes
from juloserver.application_flow.tasks import fraud_bpjs_or_bank_scrape_checking
from juloserver.google_analytics.constants import GAEvent
from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.julo.services2.high_score import feature_high_score_full_bypass
from juloserver.application_flow.services import JuloOneService
from juloserver.julo_privyid.clients import get_julo_privy_client
from juloserver.julo_privyid.services.common import store_privy_api_data
from juloserver.julo_privyid.exceptions import PrivyApiResponseException
from juloserver.julo_privyid.services.privy_integrate import store_privy_customer_data, \
    get_privy_customer_data
from juloserver.julo_privyid.constants import PrivyReUploadCodes, PRIVY_IMAGE_TYPE, \
    CustomerStatusPrivy
from juloserver.partnership.constants import (
    AddressConst,
    ErrorMessageConst,
    MERCHANT_FINANCING_PREFIX,
    PartnershipFeatureNameConst,
    PartnershipTypeConstant,
    DEFAULT_PARTNER_REDIRECT_URL,
    APISourceFrom,
    PaylaterUserAction,
    WhitelabelURLPaths,
    WhitelabelErrorType,
    PaylaterURLPaths,
    PaylaterTransactionStatuses,
    LoanPartnershipConstant,
    SLACK_CHANNEL_LEADGEN_WEBVIEW_NOTIF,
    PartnershipXIDGenerationMethod,
)
from juloserver.partnership.utils import (
    check_contain_more_than_one_space,
    generate_pii_filter_query_partnership,
    generate_public_key_whitelabel,
)
from juloserver.partnership.models import (
    PartnershipConfig,
    PartnershipFeatureSetting,
    PartnershipType,
    MerchantHistoricalTransaction,
    CustomerPinVerify,
    MasterPartnerConfigProductLookup,
    HistoricalPartnerConfigProductLookup,
    PartnerLoanRequest,
    PartnershipApplicationData,
    CustomerPin,
    CustomerPinVerifyHistory,
    PartnershipCustomerCallbackToken,
    PartnershipUserOTPAction,
    PaylaterTransaction,
    PaylaterTransactionDetails,
    PaylaterTransactionStatus,
    PartnershipApiLog,
    Distributor,
    PreLoginCheckPaylater,
    PreLoginCheckPaylaterAttempt,
    PaylaterTransactionLoan,
    PartnerOrigin,
    PartnershipUserSessionHistoryDetails,
    PartnershipUserSession,
    LivenessResult,
    LivenessResultsMapping,
    LivenessImage,
)
from juloserver.boost.services import (
    get_boost_mobile_feature_settings, get_scapper_client,
    show_bpjs_status,
    show_bank_status
)
from juloserver.boost.constants import BoostBankConst, BoostBPJSConst
from juloserver.julo.exceptions import JuloException
from juloserver.account.models import AccountLimit, Account
from juloserver.julocore.python2.utils import py2round
from juloserver.loan.services.loan_related import (
    check_eligible_and_out_date_other_platforms,
    get_credit_matrix_and_credit_matrix_product_line,
    get_parameters_fs_check_other_active_platforms_using_fdc,
    is_apply_check_other_active_platforms_using_fdc,
    update_fdc_active_loan_checking,
)
from juloserver.loan.services.loan_related import (
    get_first_payment_date_by_application,
    compute_first_payment_installment_julo_one,
    calculate_installment_amount,
    refiltering_cash_loan_duration,
    get_loan_amount_by_transaction_type,
    get_loan_duration, determine_transaction_method_by_transaction_type,
    get_transaction_type,
    generate_loan_payment_julo_one,
    update_loan_status_and_loan_history
)
from juloserver.payment_point.models import TransactionMethod
from juloserver.account.constants import TransactionType
from juloserver.loan.services.loan_related import get_ecommerce_limit_transaction
from juloserver.loan.serializers import BankAccountSerializer
from juloserver.loan.serializers import ManualSignatureSerializer
from juloserver.payment_point.constants import TransactionMethodCode, SepulsaProductCategory
from juloserver.loan.exceptions import AccountLimitExceededException
from juloserver.account.services.credit_limit import update_available_limit
from juloserver.loan.services.views_related import validate_loan_concurrency
from juloserver.julo.services2.sepulsa import SepulsaService
from juloserver.qris.services.legacy_service import QrisService
from juloserver.payment_point.services.sepulsa import get_sepulsa_partner_amount
from juloserver.payment_point.services.product_related import (
    determine_transaction_method_by_sepulsa_product
)
from juloserver.customer_module.services.bank_account_related import (
    get_bank_account_destination_by_transaction_method_partner
)
from juloserver.disbursement.services.xfers import XfersService
from juloserver.julo.clients.xfers import XfersApiError
from juloserver.disbursement.models import NameBankValidation, BankNameValidationLog
from juloserver.disbursement.constants import NameBankValidationVendors, NameBankValidationStatus
from juloserver.julo.models import PartnerBankAccount, Bank
from juloserver.customer_module.models import BankAccountDestination, BankAccountCategory
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.disbursement.services import get_validation_method
from juloserver.account_payment.models import AccountPayment
from juloserver.merchant_financing.models import (
    Merchant
)
from juloserver.loan.services.adjusted_loan_matrix import validate_max_fee_rule
from juloserver.julo.models import PartnerProperty
from juloserver.account.constants import AccountConstant
from juloserver.julo.utils import (
    format_nexmo_voice_phone_number,
    format_mobile_phone,
    upload_file_as_bytes_to_oss,
)
from juloserver.pin.constants import VerifyPinMsg, ReturnCode

from juloserver.apiv2.tasks import populate_zipcode, generate_address_from_geolocation_async
from juloserver.api_token.authentication import generate_new_token
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes, JuloOneCodes
from juloserver.monitors.notifications import (
    get_slack_bot_client,
    notify_partnership_insufficient_lender_balance,
)
from juloserver.moengage.services.use_cases import update_moengage_for_user_linking_status
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.banks import BankCodes
from juloserver.julo.workflows2.tasks import signature_method_history_task_julo_one
from typing import Dict, Union, Tuple
from juloserver.fdc.services import store_initial_fdc_inquiry_loan_data
from juloserver.income_check.services import is_income_in_range
from juloserver.partnership.liveness_partnership.constants import (
    LivenessResultMappingStatus,
    LivenessType,
)

logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()
privy_client = get_julo_privy_client()


def process_register(customer_data, partner):
    from juloserver.partnership.serializers import ApplicationSerializer
    from juloserver.merchant_financing.services import generate_encrypted_application_xid

    email = customer_data['email'].strip().lower()
    nik = customer_data['username']

    with transaction.atomic():
        user = User(username=customer_data['username'], email=email)
        user.save()

        customer = Customer.objects.create(
            user=user, email=email, nik=nik,
            appsflyer_device_id=None,
            advertising_id=None,
            mother_maiden_name=None,
            phone=customer_data.get('phone_number') or None
        )

        application = Application.objects.create(
            customer=customer,
            ktp=nik,
            email=email,
            partner=partner,
            mobile_phone_1=customer_data.get('phone_number') or None
        )

        if customer_data.get('callback_token') or customer_data.get('callback_url'):
            PartnershipCustomerCallbackToken.objects.create(
                callback_token=customer_data.get('callback_token') or None,
                callback_url=customer_data.get('callback_url') or None,
                customer=customer,
                partner=partner
            )

        update_customer_data(application)

        # update workflow and product_line to julo1
        assign_julo1_application(application)

        julo_services.process_application_status_change(
            application.id, ApplicationStatusCodes.FORM_CREATED,
            change_reason='customer_triggered'
        )

        # create AddressGeolocation
        address_geolocation = AddressGeolocation.objects.create(
            application=application,
            latitude=customer_data['latitude'],
            longitude=customer_data['longitude'])

        generate_address_from_geolocation_async.delay(address_geolocation.id)

        # store location to device_geolocation table
        apiv2_services.store_device_geolocation(
            customer,
            latitude=customer_data['latitude'],
            longitude=customer_data['longitude']
        )

        response_data = ApplicationSerializer(application).data
        if application:
            response_data['xid'] = generate_encrypted_application_xid(application.application_xid)

        create_application_checklist_async.delay(application.id)

    return response_data


def process_register_partner(partner_data):
    group = Group.objects.get(name="julo_partners")
    password = make_password('partner_{}'.format(partner_data['username']))
    with transaction.atomic():
        user = User.objects.create(username=partner_data['username'],
                                   email=partner_data['email'],
                                   password=password)
        user.groups.add(group)
        make_never_expiry_token(user)
        encrypter = encrypt()
        secret_key = encrypter.encode_string(str(user.auth_expiry_token))

        partner = Partner.objects.create(
            user=user,
            name=partner_data['username'],
            email=partner_data['email'],
            token=secret_key,
            is_active=True
        )

        partnership_type = PartnershipType.objects.filter(
            id=partner_data['partnership_type']).last()
        if not partnership_type:
            raise JuloException("Invalid partnership_type")

        if partner_data['callback_url'] and 'https' not in partner_data['callback_url']:
            raise JuloException(r"callback_url harus menggunakan format 'https'")

        partner_config = PartnershipConfig.objects.create(
            partner=partner,
            partnership_type=partnership_type,
            callback_url=partner_data['callback_url'],
            callback_token=partner_data['callback_token'],
        )
    encrypter = encrypt()
    secret_key = encrypter.encode_string(str(user.auth_expiry_token))

    response_data = {
        'partner_name': partner.name,
        'partner_email': partner.email,
        'secret_key': secret_key,
        'callback_url': partner_config.callback_url,
        'callback_token': partner_config.callback_token
    }

    return response_data


def send_otp(application, phone, paylater_transaction_xid=None):
    mfs = MobileFeatureSetting.objects.get_or_none(feature_name='mobile_phone_1_otp')
    if not mfs.is_active:
        return success_response(
            data={
                "content": {
                    "message": "Verifikasi kode otp tidak aktif"
                }
            }
        )

    partner = None
    if application.partner:
        partner = application.partner

    customer = application.customer
    existing_otp_request = OtpRequest.objects.filter(
        customer=customer, is_used=False, phone_number=phone).order_by('id').last()

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

    if existing_otp_request and existing_otp_request.is_active:
        sms_history = existing_otp_request.sms_history
        prev_time = sms_history.cdate if sms_history else existing_otp_request.cdate
        expired_time = timezone.localtime(existing_otp_request.cdate) + timedelta(
            seconds=otp_wait_seconds
        )
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
            return success_response(
                data=data
            )
        if retry_count > otp_max_request:
            data['content']['message'] = "excedded the max request"
            return success_response(
                data=data
            )

        if curr_time < resend_time:
            data['content']['message'] = "requested OTP less than resend time"
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
        postfixed_request_id = str(customer.id) + str(int(time.time()))
        otp = str(hotp.at(int(postfixed_request_id)))

        current_application = Application.objects.regular_not_deletes().filter(
            customer=customer, application_status=ApplicationStatusCodes.FORM_CREATED).first()
        otp_request = OtpRequest.objects.create(
            customer=customer, request_id=postfixed_request_id,
            otp_token=otp, application=current_application, phone_number=phone)

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

    text_message = render_to_string(
        'sms_otp_token_application.txt', context={'otp_token': otp_request.otp_token})
    try:
        send_sms_otp_token.delay(phone, text_message, customer.id,
                                 otp_request.id, change_sms_provide)
        data['content']['resend_time'] = timezone.localtime(timezone.now()) + timedelta(
            seconds=otp_resend_time
        )
    except SmsNotSent:
        logger.error({
            "status": "sms_not_sent",
            "customer": customer.id,
            "phone": phone,
        })
        julo_sentry_client.captureException()
        return general_error_response("Kode verifikasi belum dapat dikirim")
    if paylater_transaction_xid:
        data['content']['message'] = "OTP JULO sudah dikirim"
        return success_response(data=data)

    return success_response("OTP JULO sudah dikirim")


def otp_validation(otp_token, application):
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

    otp_token = otp_token

    customer = application.customer
    existing_otp_request = OtpRequest.objects.filter(
        otp_token=otp_token, customer=customer, is_used=False).order_by('id').last()
    if not existing_otp_request:
        logger.error({
            "status": "otp_token_not_found",
            "otp_token": otp_token,
            "customer": customer.id
        })
        return general_error_response("Kode verifikasi belum terdaftar")

    if str(customer.id) not in existing_otp_request.request_id:
        logger.error("Kode verifikasi tidak valid")

    hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
    valid_token = hotp.verify(otp_token, int(existing_otp_request.request_id))
    if not valid_token:
        logger.error({
            "status": "invalid_token",
            "otp_token": otp_token,
            "otp_request": existing_otp_request.id,
            "customer": customer.id
        })
        return general_error_response("Kode verifikasi tidak valid")

    if not existing_otp_request.is_active:
        logger.error({
            "status": "otp_token_expired",
            "otp_token": otp_token,
            "otp_request": existing_otp_request.id,
            "customer": customer.id
        })
        return general_error_response("Kode verifikasi kadaluarsa")

    existing_otp_request.is_used = True
    existing_otp_request.save(update_fields=['is_used'])

    return success_response()


def get_drop_down_data(data, partner_name=''):
    EXCLUDE_FRAUD_DIGI_BANK_CODE = [
        BankCodes.ROYAL,
        BankCodes.YUDHA_BHAKTI,
        BankCodes.KESEJAHTERAAN_EKONOMI,
        BankCodes.ARTOS,
        BankCodes.HARDA,
        BankCodes.AGRONIAGA,
        BankCodes.ANGLOMAS,
        'gopay'
    ]
    EXCLUDED_EWALLET = [
        'ovo',
        'shopeepay',
        'dana',
        'gopay',
    ]

    bank = Bank.objects.get_bank_names_and_xfers_bank_code()
    if partner_name == PartnerNameConstant.LINKAJA:
        bank = (
            bank.annotate(
                normalize_bank_name=Func(
                    Lower(F('bank_name')),
                    Value('[^a-z0-9]'),
                    Value(''),
                    Value('gi'),
                    function='REGEXP_REPLACE',
                    output_field=CharField(),
                )
            )
            .exclude(bank_code__in=EXCLUDE_FRAUD_DIGI_BANK_CODE)
            .exclude(normalize_bank_name__in=EXCLUDED_EWALLET)
        )

    banks = bank.annotate(
        bank_code=F('xfers_bank_code')
    ).values('bank_name', 'bank_code')
    job_industry = data['job_industry'] if 'job_industry' in data else None
    all_drop_down_data = {
        "banks": banks,
        "jobs": JOB_MAPPING[job_industry] if job_industry in JOB_MAPPING else None,
        "loan_purposes": LoanPurpose.objects.all().values_list('purpose', flat=True),
        "home_statuses": [x[0] for x in AddressConst.HOME_STATUS_CHOICES],
        "job_industries": [x[0] for x in JOB_INDUSTRY_LIST],
        "job_types": list(set([x[0] for x in Application().JOB_TYPE_CHOICES]
                              ) - {'Pekerja rumah tangga', 'Lainnya'}),
        "kin_relationships": [x[0] for x in Application().KIN_RELATIONSHIP_CHOICES],
        "last_educations": [x[0] for x in Application().LAST_EDUCATION_CHOICES],
        "marital_statuses": [x[0] for x in Application().MARITAL_STATUS_CHOICES],
        "vehicle_types": list(set([x[0] for x in Application().VEHICLE_TYPE_CHOICES]
                                  ) - {'Lainnya'}),
        "vehicle_ownerships": [x[0] for x in Application().VEHICLE_OWNERSHIP_CHOICES],
        "birth_places": BirthplaceDropDown().DATA,
        "companies": DropDownData(DropDownData.COMPANY).select_data(),
    }

    drop_down_data = all_drop_down_data[data['data_selected']]

    if drop_down_data and data['data_selected'] == "jobs" and 'All' in drop_down_data:
        drop_down_data.remove('All')
    return drop_down_data


def process_upload_image(image_data, application, from_webview=False):
    image = Image()
    image_type = image_data['image_type']
    image_source = application.id

    if image_type is not None:
        image.image_type = image_type
    if image_source is None:
        return general_error_response(data={
            'success': False,
            'data': None,
            'error_message': ['Invalid image_source']
        })

    if from_webview:
        # For webview the process is synchronous
        # Image source id for Webview Parntership should will be a negative to distinguish it
        # since there are not application yet, It will be change into the actual application id
        # with function "update_image_source_id_partnership"
        # PARTNER-719 / PARTNER-816
        image.image_source = -abs(int(image_source) + 510)
        image.save()
        upload = image_data['upload']
        _, file_extension = os.path.splitext(upload.name)
        image_data = {
            'file_extension': '.{}'.format(file_extension),
            'image_file': upload,
        }
        process_image_upload_partnership(image, image_data)
        image.refresh_from_db()
        response = {
            "image_id": image.id,
            "image_url_api": image.image_url_api,
        }
        return success_response(response)
    else:
        image.image_source = int(image_source)
        image.save()
        upload = image_data['upload']
        _, file_extension = os.path.splitext(upload.name)
        image_data = {
            'file_extension': '.{}'.format(file_extension),
            'image_file': upload,
        }
        upload_image_partnership.delay(image, image_data)

    return success_response('success upload image')


def get_address(data):
    address_values = None
    if data['address_type'] == AddressConst.PROVINCE:
        address_values = ProvinceLookup.objects.filter(
            is_active=True
        ).order_by('province').values_list('province', flat=True)
    elif data['address_type'] == AddressConst.CITY:
        address_values = CityLookup.objects.filter(
            province__province__icontains=data['province'],
            is_active=True
        ).order_by('city').values_list('city', flat=True)
    elif data['address_type'] == AddressConst.DISTRICT:
        address_values = DistrictLookup.objects.filter(
            city__city__icontains=data['city'],
            city__province__province__icontains=data['province'],
            is_active=True
        ).order_by('district').values_list('district', flat=True)
    elif data['address_type'] == AddressConst.SUB_DISTRICT:
        sub_district = SubDistrictLookup.objects.filter(
            district__district__icontains=data['district'],
            district__city__city__icontains=data['city'],
            district__city__province__province__icontains=data['province'],
            is_active=True
        ).order_by('sub_district')
        address_values = SubDistrictLookupResSerializer(sub_district, many=True).data
    return address_values


def check_image_upload(application_id):
    images = Image.objects.filter(
        image_type__in=['selfie', 'ktp_self', 'crop_selfie'],
        image_source=application_id
    ).distinct('image_type')

    if images.count() < 3:
        return False

    return True


def is_pass_otp(customer: Customer, phone_number: str) -> bool:
    """
    MobileFeatureSetting is_active = True -> the validation is active -> check OTPRequest
    if is_active = False -> we can by pass the OTP -> True
    """
    if MobileFeatureSetting.objects.filter(
        feature_name='mobile_phone_1_otp', is_active=True
    ).exists() and \
        not OtpRequest.objects.filter(
        is_used=True, customer=customer, phone_number=phone_number
    ).exists():
        return False

    return True


def validate_mother_maiden_name(mother_maiden_name):
    if not mother_maiden_name:
        return False, 'Mother_maiden_name {}'.format(ErrorMessageConst.REQUIRED)
    elif len(mother_maiden_name) < 3:
        return False, 'Mother_maiden_name minimal 3 karakter'
    elif check_contain_more_than_one_space(mother_maiden_name):
        return False, 'Mother_maiden_name {}'.format(ErrorMessageConst.SPACE_MORE_THAN_ONE)
    elif not re.match(r'^[A-Za-z0-9 ]*$', mother_maiden_name):
        return False, 'Mother_maiden_name {}'.format(ErrorMessageConst.INVALID_DATA)

    return True, None


def process_register_partner_for_merchant_with_product_line_data(partner_data):
    with transaction.atomic():
        group = Group.objects.get(name="julo_partners")
        password = make_password('partner_{}'.format(partner_data['username']))

        user = User.objects.create(username=partner_data['username'],
                                   email=partner_data['email'],
                                   password=password)
        user.groups.add(group)
        make_never_expiry_token(user)
        encrypter = encrypt()
        secret_key = encrypter.encode_string(str(user.auth_expiry_token))

        partner = Partner.objects.create(
            user=user,
            name=partner_data['username'],
            email=partner_data['email'],
            token=secret_key,
            is_active=True
        )
        partnership_type = PartnershipType.objects.filter(
            id=partner_data['partnership_type']).last()
        if not partnership_type:
            raise JuloException("Invalid partnership_type")

        loan_duration = None
        if partnership_type.partner_type_name == PartnershipTypeConstant.MERCHANT_FINANCING:
            loan_duration = [3, 7, 14, 30]  # in days

        PartnershipConfig.objects.create(
            partner=partner,
            partnership_type=partnership_type,
            callback_url=partner_data['callback_url'],
            callback_token=partner_data['callback_token'],
            loan_duration=loan_duration
        )
        product_line_code = 300
        product_line_type = 'MF'
        product_line = ProductLine.objects.filter(product_line_type=product_line_type,
                                                  product_line_code=product_line_code).last()
        product_profile = ProductProfile.objects.filter(name=product_line_type,
                                                        code=product_line_code).last()
        if not product_line and not product_profile:

            product_line_code = product_line_code
            product_profile = ProductProfile.objects.create(
                name=product_line_type,
                min_amount=2000000,
                max_amount=40000000,
                min_duration=3,
                max_duration=60,
                min_interest_rate=0.027,
                max_interest_rate=0.04,
                interest_rate_increment=0,
                payment_frequency="Daily",
                is_active=True,
                is_product_exclusive=True,
                is_initial=True,
                min_origination_fee=0,
                max_origination_fee=0,
                code=product_line_code
            )
            ProductLine.objects.create(
                product_line_code=product_line_code,
                product_line_type=product_line_type,
                min_amount=2000000,
                max_amount=40000000,
                min_duration=3,
                max_duration=60,
                min_interest_rate=0.027,
                max_interest_rate=0.04,
                payment_frequency='Daily',
                product_profile=product_profile
            )
            raw_data = [
                ['I.000-O.020-L.050-C1.000-C2.000-M', 0.00, 0.020, 0.05, 0, 0,
                 True, product_line_code, product_profile.id],
                ['I.000-O.0225-L.050-C1.000-C2.000-M', 0.00, 0.0225, 0.05, 0, 0,
                 True, product_line_code, product_profile.id],
                ['I.000-O.025-L.050-C1.000-C2.000-M', 0.00, 0.025, 0.05, 0, 0,
                 True, product_line_code, product_profile.id],
                ['I.000-O.0275-L.050-C1.000-C2.000-M', 0.00, 0.0275, 0.05, 0, 0,
                 True, product_line_code, product_profile.id],
                ['I.000-O.030-L.050-C1.000-C2.000-M', 0.00, 0.030, 0.05, 0, 0,
                 True, product_line_code, product_profile.id],
                ['I.000-O.0325-L.050-C1.000-C2.000-M', 0.00, 0.0325, 0.05, 0, 0,
                 True, product_line_code, product_profile.id],
                ['I.000-O.035-L.050-C1.000-C2.000-M', 0.00, 0.035, 0.05, 0, 0,
                 True, product_line_code, product_profile.id],
                ['I.000-O.0375-L.050-C1.000-C2.000-M', 0.00, 0.0375, 0.05, 0, 0,
                 True, product_line_code, product_profile.id],
                ['I.000-O.040-L.050-C1.000-C2.000-M', 0.00, 0.040, 0.05, 0, 0,
                 True, product_line_code, product_profile.id]
            ]
            keys = [
                'product_name',
                'interest_rate',
                'origination_fee_pct',
                'late_fee_pct',
                'cashback_initial_pct',
                'cashback_payment_pct',
                'is_active',
                'product_line_id',
                'product_profile_id'
            ]

            for data in raw_data:
                ProductLookup.objects.create(**dict(list(zip(keys, data))))
            workflow = Workflow.objects.get_or_none(name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW)
            WorkflowStatusPath.objects.get_or_create(
                status_previous=0,
                status_next=100,
                type="happy",
                workflow=workflow
            )

        response_data = {
            'partner_name': partner.name,
            'partner_email': partner.email,
            'secret_key': secret_key
        }

    return response_data


def process_register_merchant(customer_data, partner, merchant):
    from juloserver.partnership.serializers import ApplicationSerializer
    from juloserver.merchant_financing.services import generate_encrypted_application_xid
    email = customer_data['email'].strip().lower()
    nik = merchant.nik

    with transaction.atomic():
        user, user_created = User.objects.get_or_create(username=nik, email=email)
        customer, customer_created = Customer.objects.get_or_create(
            user=user, email=email, nik=nik,
            appsflyer_device_id=None,
            advertising_id=None,
            mother_maiden_name=None)
        workflow = Workflow.objects.get_or_none(name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW)
        product_line = ProductLine.objects.get(product_line_code=ProductLineCodes.MF)
        merchant = Merchant.objects.get(merchant_xid=customer_data['merchant_xid'])
        application = Application.objects.create(
            customer=customer,
            ktp=nik,
            email=email,
            partner=partner,
            workflow=workflow,
            product_line=product_line,
            application_number=1,
            merchant=merchant,
        )
        update_customer_data(application)
        customer.can_reapply_date = None
        customer.save()

        julo_services.process_application_status_change(
            application.id, ApplicationStatusCodes.FORM_CREATED,
            change_reason='customer_triggered'
        )
        response_data = ApplicationSerializer(application).data
        if application:
            response_data['xid'] = generate_encrypted_application_xid(
                application.application_xid,
                MERCHANT_FINANCING_PREFIX)

    return response_data


def submit_document_flag(application_xid, is_document_submitted):
    application = Application.objects.get_or_none(
        application_xid=application_xid
    )

    is_document_submitted = is_document_submitted
    if is_document_submitted:
        if application.status in (ApplicationStatusCodes.FORM_PARTIAL,
                                  ApplicationStatusCodes.FORM_SUBMITTED):  # 110 or 105
            if application.product_line.product_line_code in ProductLineCodes.ctl():
                julo_services.process_application_status_change(
                    application.id, ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,  # 129
                    change_reason='customer_triggered')
            else:
                send_event_to_ga_task_async.apply_async(
                    kwargs={'customer_id': application.customer.id, 'event': GAEvent.APPLICATION_MD}
                )
                if application.status == ApplicationStatusCodes.FORM_PARTIAL:
                    # do checking for fraud
                    fraud_bpjs_or_bank_scrape_checking.apply_async(
                        kwargs={'application_id': application.id}
                    )
                julo_services.process_application_status_change(
                    application.id, ApplicationStatusCodes.DOCUMENTS_SUBMITTED,  # 120
                    change_reason='customer_triggered')

        elif application.status == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:  # 131
            application = Application.objects.get_or_none(pk=application.id)
            app_history = ApplicationHistory.objects.filter(
                application=application,
                status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED).last()
            repeat_face_recognition = [ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
                                       ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT,
                                       ApplicationStatusCodes.CALL_ASSESSMENT]
            result_face_recognition = AwsFaceRecogLog.objects.filter(application=application).last()
            face_recognition = FaceRecognition.objects.get_or_none(
                feature_name='face_recognition',
                is_active=True
            )
            failed_upload_image_reasons = [
                'failed upload selfie image',
                'Passed KTP check & failed upload selfie image'
            ]
            change_reason = 'customer_triggered'
            # check if app_history from 120 or 1311
            if app_history.status_old in repeat_face_recognition and \
                    application.product_line_code in ProductLineCodes.new_lended_by_jtp() and \
                    result_face_recognition and \
                    not result_face_recognition.is_quality_check_passed and \
                    face_recognition or \
                    (app_history.change_reason in failed_upload_image_reasons) and \
                    face_recognition:
                application_status_code = ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT
            else:
                application_status_code = ApplicationStatusCodes.APPLICATION_RESUBMITTED
                if app_history.status_old in repeat_face_recognition and \
                        application.product_line_code in \
                        ProductLineCodes.new_lended_by_jtp() and \
                        result_face_recognition and \
                        not face_recognition or \
                        (app_history.change_reason in failed_upload_image_reasons) and \
                        not face_recognition:
                    application_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                    change_reason = 'Passed KTP Check'
                    customer_service = get_customer_service()
                    result_bypass = customer_service.do_high_score_full_bypass_or_iti_bypass(
                        application.id)
                    if result_bypass:
                        application_status_code = result_bypass['new_status_code']
                        change_reason = result_bypass['change_reason']
            if application.status != ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                julo_services.process_application_status_change(
                    application.id, application_status_code,  # 132
                    change_reason=change_reason)
        elif application.status == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:  # 147
            # customer = application.customer
            # customer_data = reregister_privy_service(customer, application)
            julo_services.process_application_status_change(
                application.id,
                ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,  # 150
                change_reason='customer_triggered')
    logger.info({
        "action": "submit_document_flag_partnership",
        "application_xid": application_xid,
        "is_document_submitted": is_document_submitted,
        "application_status": application.status
    })

    application.refresh_from_db()


def get_document_submit_flag(application):
    is_document_submitted = False
    mandatory_docs_submission = False
    is_credit_score_created = False
    can_continue = True
    if application.application_status_id in [
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        ApplicationStatusCodes.APPLICATION_DENIED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER
    ]:
        can_continue = False
    if application.application_status_id not in [
        ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        ApplicationStatusCodes.FORM_PARTIAL
    ]:
        return (is_document_submitted, mandatory_docs_submission,
                is_credit_score_created, can_continue)
    if not CreditScore.objects.filter(application=application).exists():
        return (is_document_submitted, mandatory_docs_submission,
                is_credit_score_created, can_continue)
    is_credit_score_created = True
    # customer_high_score = feature_high_score_full_bypass(application)
    customer_with_high_c_score = JuloOneService.is_high_c_score(application)
    is_c_score = JuloOneService.is_c_score(application)
    if not is_c_score or customer_with_high_c_score or \
            application.application_status_id == \
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
        is_document_submitted = True
    if application.application_status_id == \
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
        mandatory_docs_submission = True
    if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL:
        if is_c_score and is_credit_score_created:
            can_continue = False

    logger.info({
        "action": "get_document_submit_flag",
        "application_xid": application.application_xid,
        "is_document_submitted": is_document_submitted,
        "application_status": application.status,
        "mandatory_docs_submission": mandatory_docs_submission
    })

    return (is_document_submitted, mandatory_docs_submission,
            is_credit_score_created, can_continue)


def get_documents_to_be_uploaded(application):
    DOCUMENT_TYPE = {
        'image': 'IMAGE',
        'bank_scrape': 'BANK_SCRAPE',
        'bpjs': 'BPJS'
    }
    return_list = []
    is_c_score = JuloOneService.is_c_score(application)
    if is_c_score:
        return return_list
    if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL:
        workflow_name = 'julo_one'
        boost_status = {
            "bank_status": {
                "enable": False,
                "status": []
            },
            "bpjs_status": {
                "enable": False,
                "status": ""
            },
            "salary_status": {
                "enable": False,
                "image": {}
            },
            "bank_statement_status": {
                "enable": False,
                "image": {}
            }
        }
        boost_settings = get_boost_mobile_feature_settings()
        if boost_settings:
            bank_settings = boost_settings.parameters['bank']
            if bank_settings['is_active']:
                boost_status['bank_status']['enable'] = True
                julo_scraper_client = get_scapper_client()
                bank_statuses = julo_scraper_client.get_bank_scraping_status(application.id)
                mapped_bank_statuses = show_bank_status(bank_statuses, workflow_name)
                boost_status['bank_status']['status'] = mapped_bank_statuses['bank_status']

        bpjs_status = show_bpjs_status(application=application, workflow_name=workflow_name)
        if bpjs_status:
            boost_status['bpjs_status']['enable'] = True
            boost_status['bpjs_status']['status'] = bpjs_status['bpjs_status']

        if not CreditScore.objects.filter(application=application).exists():
            return []

        is_image_enable = False
        medium_score_condition = not feature_high_score_full_bypass(application) and not \
            JuloOneService.is_high_c_score(application) and not \
            JuloOneService.is_c_score(application)

        if medium_score_condition:
            is_image_enable = True

        if is_image_enable:
            boost_status['salary_status']['enable'] = True
            boost_status['bank_statement_status']['enable'] = True

        bank_settings = boost_settings.parameters['bank']
        bank_flag = False
        bpjs_flag = False
        if bank_settings['is_active']:
            bank_statuses = boost_status['bank_status']['status']
            for bank_status in bank_statuses:
                if bank_status['status'] is BoostBankConst.VERIFIED:
                    bank_flag = True
                    break

        bpjs_flag = False
        bpjs_settings = boost_settings.parameters['bpjs']
        if bpjs_settings['is_active']:
            bpjs_flag = boost_status['bpjs_status']['status'] is BoostBPJSConst.VERIFIED
        for key in list(boost_status.keys()):
            return_dict = dict()
            if key == 'bank_status' and boost_status[key]['enable']:
                return_dict['DOCUMENT_TYPE'] = DOCUMENT_TYPE['bank_scrape']
                return_dict['document_type'] = DOCUMENT_TYPE['bank_scrape']
                return_dict['document_upload_status'] = bank_flag

            elif key == 'bpjs_status' and boost_status[key]['enable']:
                return_dict['DOCUMENT_TYPE'] = DOCUMENT_TYPE['bpjs']
                return_dict['document_type'] = DOCUMENT_TYPE['bpjs']
                return_dict['document_upload_status'] = bpjs_flag

            else:
                image_type = None

                if key == 'salary_status' and boost_status[key]['enable']:
                    image_type = 'paystub'
                elif key == 'bank_statement_status' and boost_status[key]['enable']:
                    image_type = 'bank_statement'
                elif not boost_status[key]['enable']:
                    continue
                else:
                    if not image_type:
                        raise JuloException('ERROR INVALID DOCUMENT TYPE')

                image_status = Image.objects.filter(
                    image_source=application.id,
                    image_type=image_type
                ).exists()
                return_dict['DOCUMENT_TYPE'] = DOCUMENT_TYPE['image']
                return_dict['document_type'] = image_type
                return_dict['document_upload_status'] = image_status

            return_list.append(return_dict)

    elif application.application_status_id == ApplicationStatusCodes.\
            APPLICATION_RESUBMISSION_REQUESTED:
        failed_images_types = Image.objects.filter(
            image_source=application.id,
            image_status__in=[Image.RESUBMISSION_REQ, Image.DELETED]
        ).values_list('image_type', flat=True)
        failed_images_types = list(set(failed_images_types))
        success_image = Image.objects.filter(
            image_source=application.id,
            image_status=Image.CURRENT,
            image_type__in=failed_images_types
        ).values_list('image_type', flat=True)
        for failed_image_type in failed_images_types:
            return_dict = dict()
            return_dict['DOCUMENT_TYPE'] = DOCUMENT_TYPE['image']
            return_dict['document_type'] = failed_image_type
            return_dict['document_upload_status'] = True if \
                failed_image_type in success_image else False
            return_list.append(return_dict)

    elif application.application_status_id == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:
        return_response = get_failed_privy_images(application)
        if return_response['failed_image_types']:
            for failed_image_type in return_response['failed_image_types']:
                return_dict = dict()
                return_dict['DOCUMENT_TYPE'] = DOCUMENT_TYPE['image']
                return_dict['document_type'] = failed_image_type
                return_dict['document_upload_status'] = True \
                    if failed_image_type in return_response['uploaded_failed_images'] else False
                return_list.append(return_dict)

    logger.info({
        "action": "get_documents_to_be_uploaded",
        "application_id": application.id,
        "return_list": return_list
    })

    return return_list


def get_credit_limit_info(application):
    account = application.account
    account_limit = account.accountlimit_set.last()
    account_details = dict()
    account_details['available_limit'] = account_limit.available_limit
    account_details['max_limit'] = account_limit.max_limit
    account_details['set_limit'] = account_limit.set_limit
    account_details['used_limit'] = account_limit.used_limit

    return account_details


def get_failed_privy_images(application):
    customer = application.customer
    privy_settings = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PRIVY_REUPLOAD_SETTINGS,
        is_active=True
    )
    return_response = {
        'failed': False,
        'failed_image_types': [],
        'uploaded_failed_images': []
    }
    privy_customer = get_privy_customer_data(customer)
    user_token = privy_customer.privy_customer_token
    data, api_data = privy_client.register_status(user_token)
    store_privy_api_data(None, api_data, application)
    if not api_data or api_data['response_status_code'] not in (200, 201):
        raise PrivyApiResponseException('Customer Status API failed')
    privy_user_data = store_privy_customer_data(customer, data)
    if privy_user_data.reject_reason is not None:
        if data['reject']:
            if data['reject']['code']:
                list_image_types = list()
                list_uploaded_images = list()
                for category in PrivyReUploadCodes.LIST_CODES:
                    for codes in privy_settings.parameters[category]:
                        if data['reject']['code'] in codes:
                            image_type = PrivyReUploadCodes.IMAGE_MAPPING[category]
                            if image_type not in list_image_types:
                                reuploaded_image = Image.objects.filter(
                                    image_source=application.id,
                                    image_type=PRIVY_IMAGE_TYPE[image_type],
                                    image_status__in=[Image.CURRENT,
                                                      Image.RESUBMISSION_REQ]
                                ).order_by('-udate').first()
                                if reuploaded_image:
                                    image_type = reuploaded_image.image_type \
                                        if reuploaded_image.image_type else None
                                    list_uploaded_images.append({
                                        "image_url": reuploaded_image.image_url if
                                        reuploaded_image.image_url else None,
                                        "image_type": image_type
                                    })
                                list_image_types.append(PRIVY_IMAGE_TYPE[image_type])
                    return_response['failed_image_types'] = list_image_types
                    return_response['uploaded_failed_images'] = list_uploaded_images

    return_response['privy_status'] = privy_user_data.privy_customer_status

    if return_response['privy_status'] == CustomerStatusPrivy.WAITING and application.status \
            == ApplicationStatusCodes.DIGISIGN_FACE_FAILED:
        julo_services.process_application_status_change(
            application.id,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
            'Privy Reupload Successful'
        )


def get_application_status_flag_status(return_application_status, application):
    return_application_status['is_any_document_upload'] = None
    return_application_status['is_submit_document_flag_ready'] = None

    if return_application_status['documents_to_be_uploaded']:
        if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL:
            return_application_status['is_any_document_upload'] = True
            return_application_status['is_submit_document_flag_ready'] = False
        else:
            return_application_status['is_any_document_upload'] = False
            return_application_status['is_submit_document_flag_ready'] = True

        for document in return_application_status['documents_to_be_uploaded']:
            if return_application_status['is_any_document_upload']:
                if document['document_upload_status']:
                    return_application_status['is_submit_document_flag_ready'] = True
                    break
            else:
                if not document['document_upload_status']:
                    return_application_status['is_submit_document_flag_ready'] = False
                    break

    return return_application_status


def get_range_loan_amount(application, self_bank_account, transaction_method_id):
    account = application.account
    application = account.application_set.last()
    account_limit = AccountLimit.objects.filter(account=account).last()
    available_limit = account_limit.available_limit
    # TODO check if this need to send in input param
    transaction_type = None
    if transaction_method_id:
        transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
        if transaction_method:
            transaction_type = transaction_method.method
    credit_matrix, credit_matrix_product_line = \
        get_credit_matrix_and_credit_matrix_product_line(
            application,
            self_bank_account, None,
            transaction_type)
    if not credit_matrix.product:
        raise JuloException("Gagal mendapatkan minimal dan maksimal nilai pinjaman")
    origination_fee = credit_matrix.product.origination_fee_pct
    max_amount = available_limit
    if not self_bank_account:
        max_amount -= int(py2round(max_amount * origination_fee))
    min_amount_threshold = LoanPartnershipConstant.MIN_LOAN_AMOUNT_THRESHOLD
    if transaction_type == TransactionType.ECOMMERCE:
        min_amount_threshold = get_ecommerce_limit_transaction()
    min_amount = min_amount_threshold if min_amount_threshold < available_limit \
        else available_limit
    response_data = dict(
        min_amount_threshold=min_amount_threshold,
        min_amount=min_amount,
        max_amount=max_amount
    )
    return response_data


def get_loan_duration_partnership(
        application, self_bank_account, is_payment_point, loan_amount_request,
        transaction_method_id):

    transaction_type = None
    if transaction_method_id:
        transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
        if transaction_method:
            transaction_type = transaction_method.method

    credit_matrix, credit_matrix_product_line = \
        get_credit_matrix_and_credit_matrix_product_line(
            application, self_bank_account, is_payment_point, transaction_type
        )

    account_limit = AccountLimit.objects.filter(account=application.account).last()
    available_duration = get_loan_duration(
        loan_amount_request,
        credit_matrix_product_line.max_duration,
        credit_matrix_product_line.min_duration,
        account_limit.set_limit
    )

    available_duration = [1] if loan_amount_request <= 100000 else available_duration

    if not available_duration or (len(available_duration) == 1 and available_duration[0] == 0):
        raise JuloException('Gagal mendapatkan durasi pinjaman')

    is_loan_one = available_duration[0] == 1
    loan_choice = []
    origination_fee_pct = credit_matrix.product.origination_fee_pct
    available_limit = account_limit.available_limit
    loan_amount = get_loan_amount_by_transaction_type(loan_amount_request,
                                                      origination_fee_pct,
                                                      self_bank_account)

    if loan_amount > account_limit.available_limit:
        raise JuloException(
            "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
        )
    provision_fee = int(py2round(loan_amount * origination_fee_pct))
    available_limit_after_transaction = available_limit - loan_amount
    disbursement_amount = py2round(loan_amount - provision_fee)
    today_date = timezone.localtime(timezone.now()).date()

    is_qris_transaction = transaction_type == TransactionMethodCode.QRIS.name
    is_ecommerce = transaction_type == TransactionType.ECOMMERCE

    first_payment_date = get_first_payment_date_by_application(application)
    # if is_loan_one and (is_payment_point or is_qris_transaction or is_ecommerce):
    #     first_payment_date = get_first_payment_date_by_application(application)

    # filter out duration less than 60 days due to google restriction for cash loan
    if not is_payment_point:
        available_duration = refiltering_cash_loan_duration(available_duration, application)

    for duration in available_duration:
        monthly_interest_rate = credit_matrix.product.monthly_interest_rate
        (
            is_exceeded,
            _,
            max_fee_rate,
            provision_fee_rate,
            adjusted_interest_rate,
            _,
            _,
        ) = validate_max_fee_rule(
            first_payment_date, monthly_interest_rate, duration, origination_fee_pct
        )

        if is_exceeded:
            # adjust loan amount based on new provision
            if origination_fee_pct != provision_fee_rate and not self_bank_account:
                loan_amount = get_loan_amount_by_transaction_type(
                    loan_amount_request,
                    provision_fee_rate,
                    self_bank_account)
            provision_fee = int(py2round(loan_amount * provision_fee_rate))
            disbursement_amount = py2round(loan_amount - provision_fee)
            monthly_interest_rate = adjusted_interest_rate

        monthly_installment = calculate_installment_amount(
            loan_amount,
            duration,
            monthly_interest_rate
        )

        if is_loan_one and (is_payment_point or is_qris_transaction or is_ecommerce) and \
                not is_exceeded:
            _, _, monthly_installment = compute_first_payment_installment_julo_one(
                loan_amount, duration, monthly_interest_rate,
                today_date, first_payment_date
            )

        loan_choice.append({
            'loan_amount': loan_amount,
            'duration': duration,
            'monthly_installment': monthly_installment,
            'provision_amount': provision_fee,
            'disbursement_amount': int(disbursement_amount),
            'cashback': int(py2round(
                loan_amount * credit_matrix.product.cashback_payment_pct
            )),
            'available_limit': available_limit,
            'available_limit_after_transaction': available_limit_after_transaction,
        })

    return loan_choice


def get_payments_partnership(loan):
    payment_list = []
    payments = Payment.objects.by_loan(loan=loan).order_by('payment_number')
    date_today = timezone.localtime(timezone.now()).date()
    for payment in payments.iterator():
        installment_amount = payment.installment_principal + payment.installment_interest
        installment_paid = payment.paid_principal + payment.paid_interest
        installment_overdue = installment_amount - installment_paid if\
            payment.due_date < date_today else 0
        payment_details = {
            "installment_number": payment.payment_number,
            "installment_dpd": payment.get_dpd,
            "installment_due_date": payment.due_date.strftime("%Y-%m-%d"),
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
            "late_fee_amount": payment.late_fee_amount,
            "late_fee_paid": payment.paid_late_fee,
            "late_fee_overdue": payment.late_fee_amount - payment.paid_late_fee if
            payment.due_date < date_today else 0
        }
        payment_list.append(payment_details)
    return payment_list


def get_loan_details_partnership(loan):
    from juloserver.partnership.serializers import LoanDetailsPartnershipSerializer
    serializer = LoanDetailsPartnershipSerializer(loan)
    data = serializer.data
    serializer_bank = BankAccountSerializer(loan.bank_account_destination)
    data['bank'] = serializer_bank.data if loan.bank_account_destination else None
    return data


def get_manual_signature_partnership(loan):
    manual_signature = Image.objects.filter(
        image_source=loan.id,
        image_type='signature').last()
    serializer = ManualSignatureSerializer(manual_signature)
    return_data = serializer.data
    if return_data and 'id' in return_data:
        return_data.pop('id')
        return_data.pop('thumbnail_url_api')
    return return_data


def process_create_loan(
    data, application, partner, skip_bank_account=False, paylater_transaction=None
):
    account = application.account
    if not account:
        return general_error_response('Account tidak ditemukan')
    customer = application.customer
    if not customer:
        return general_error_response('Customer {}'.format(ErrorMessageConst.NOT_FOUND))
    account_limit = AccountLimit.objects.filter(
        account=account
    ).last()
    if data['loan_amount_request'] <= 0:
        return general_error_response(ErrorMessageConst.INVALID_LOAN_REQUEST_AMOUNT)

    if data['loan_amount_request'] > account_limit.available_limit:
        return general_error_response(
            ErrorMessageConst.OVER_LIMIT
        )

    _, concurrency_messages = validate_loan_concurrency(account)
    if concurrency_messages:
        return general_error_response(concurrency_messages['content'])

    mobile_number = data['mobile_number']
    if mobile_number:
        feature_setting = FeatureSetting.objects.filter(
            feature_name=LoanPartnershipConstant.PHONE_NUMBER_BLACKLIST,
            is_active=True).last()
        if feature_setting:
            params = feature_setting.parameters
            blacklist_phone_number = params['blacklist_phone_numnber']
            if mobile_number in blacklist_phone_number:
                return general_error_response(
                    "Invalid phone number"
                )

    is_payment_point = data['is_payment_point'] if 'is_payment_point' in data else False
    data['self_bank_account'] = data['transaction_type_code'] == TransactionMethodCode.SELF.code
    transaction_method_id = data.get('transaction_type_code', None)
    transaction_type = None
    if paylater_transaction:
        data['transaction_type_code'] = transaction_method_id = TransactionMethodCode. \
            E_COMMERCE.code

    if transaction_method_id:
        transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
        if transaction_method:
            transaction_type = transaction_method.method
    credit_matrix, credit_matrix_product_line = \
        get_credit_matrix_and_credit_matrix_product_line(
            application,
            data['self_bank_account'],
            is_payment_point,
            transaction_type
        )
    if not credit_matrix.product:
        return general_error_response('application belum bisa mengajukan pinjaman')
    range_loan_amount = get_range_loan_amount(
        application, data['self_bank_account'], data['transaction_type_code']
    )
    min_amount_threshold = range_loan_amount['min_amount_threshold']
    min_loan_amount = range_loan_amount['min_amount']
    max_loan_amount = range_loan_amount['max_amount']
    if transaction_type == TransactionType.ECOMMERCE:
        min_amount_threshold = get_ecommerce_limit_transaction()

    if data['loan_amount_request'] < min_amount_threshold:
        return general_error_response(ErrorMessageConst.INVALID_LOAN_REQUEST_AMOUNT)

    if data['loan_amount_request'] < min_loan_amount or \
            data['loan_amount_request'] > max_loan_amount:
        return general_error_response(
            'Loan_amount_request harus tidak boleh kurang dari {} dan lebih dari {}'.format(
                min_loan_amount, max_loan_amount
            )
        )
    available_duration = get_loan_duration(
        data['loan_amount_request'],
        credit_matrix_product_line.max_duration,
        credit_matrix_product_line.min_duration,
        account_limit.set_limit
    )
    available_duration = [1] if data['loan_amount_request'] <= 100000 else available_duration
    if data['loan_duration'] not in available_duration:
        return general_error_response('loan_duration yang dipilih tidak sesuai')
    origination_fee_pct = credit_matrix.product.origination_fee_pct
    if is_payment_point:
        product = SepulsaProduct.objects.filter(
            pk=data['payment_point_product_id'],
        ).last()
        if not product:
            return general_error_response('Produk tidak ditemukan')
    loan_amount = data['loan_amount_request']
    is_loan_amount_adjusted = False
    if not is_payment_point or product.category not in (
            SepulsaProductCategory.PRE_PAID_AND_DATA +
            (SepulsaProductCategory.ELECTRICITY_PREPAID,)
    ):
        loan_amount = get_loan_amount_by_transaction_type(data['loan_amount_request'],
                                                          origination_fee_pct,
                                                          data['self_bank_account'])
        is_loan_amount_adjusted = True
    loan_requested = dict(
        is_loan_amount_adjusted=is_loan_amount_adjusted,
        original_loan_amount_requested=data['loan_amount_request'],
        loan_amount=loan_amount,
        loan_duration_request=data['loan_duration'],
        interest_rate_monthly=credit_matrix.product.monthly_interest_rate,
        product=credit_matrix.product,
        provision_fee=origination_fee_pct,
        is_withdraw_funds=data['self_bank_account']
    )
    bank_account_destination = None
    loan_purpose = None
    is_qris_transaction = transaction_type == TransactionMethodCode.QRIS.name
    if not skip_bank_account:
        if not is_payment_point and not is_qris_transaction:
            loan_purpose = data.get('loan_purpose', False)

            bank_account_destination = get_bank_account_destination_by_transaction_method_partner(
                application.customer, transaction_method_id, partner
            )
            if not bank_account_destination:
                return general_error_response('Bank_account_id tidak ditemukan')
    else:
        loan_purpose = data.get('loan_purpose', None)

    # Create QRIS Loan at 209 for beginning
    draft_loan = False
    if is_qris_transaction:
        draft_loan = True

    try:
        with transaction.atomic():
            account_limit = AccountLimit.objects.select_for_update().filter(
                account=application.account
            ).last()
            if data['loan_amount_request'] > account_limit.available_limit:
                raise AccountLimitExceededException(
                    "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
                )
            loan = generate_loan_payment_julo_one(application,
                                                  loan_requested,
                                                  loan_purpose,
                                                  credit_matrix,
                                                  bank_account_destination,
                                                  draft_loan=draft_loan)
            if not transaction_method:
                transaction_type = get_transaction_type(
                    data['self_bank_account'], is_payment_point, bank_account_destination)
                transaction_method = determine_transaction_method_by_transaction_type(
                    transaction_type)

            # qris transaction
            if is_qris_transaction:
                qr_id = data['qr_id']
                qirs_service = QrisService(account)
                qirs_service.init_doku_qris_transaction_payment(
                    qr_id, data['loan_amount_request'], loan)

            elif is_payment_point:
                sepulsa_service = SepulsaService()
                paid_period = None
                customer_amount = None
                partner_amount = get_sepulsa_partner_amount(data['loan_amount_request'],
                                                            product)
                customer_number = None
                if partner_amount:
                    customer_amount = data['loan_amount_request']
                if 'customer_number' in data and data['customer_number']:
                    customer_number = data['customer_number']
                elif 'bpjs_number' in data and data['bpjs_number']:
                    customer_number = data['bpjs_number']
                    paid_period = data['bpjs_times']

                sepulsa_service.create_transaction_sepulsa(
                    customer=loan.customer,
                    product=product,
                    account_name=data['customer_name'],
                    phone_number=data['mobile_number'],
                    customer_number=customer_number,
                    loan=loan,
                    retry_times=0,
                    partner_price=product.partner_price,
                    customer_price=product.customer_price,
                    customer_price_regular=product.customer_price_regular,
                    category=product.category,
                    customer_amount=customer_amount,
                    partner_amount=partner_amount,
                    admin_fee=product.admin_fee,
                    service_fee=product.service_fee,
                    paid_period=paid_period,
                    collection_fee=product.collection_fee
                )
                if not transaction_method:
                    transaction_method = determine_transaction_method_by_sepulsa_product(
                        product)

            loan.update_safely(transaction_method=transaction_method)
            update_available_limit(loan)
    except AccountLimitExceededException as e:
        return general_error_response(str(e))

    monthly_interest_rate = loan.interest_rate_monthly
    if hasattr(loan, 'loanadjustedrate'):
        origination_fee_pct = loan.loanadjustedrate.adjusted_provision_rate
        monthly_interest_rate = loan.loanadjustedrate.adjusted_monthly_interest_rate

    disbursement_amount = py2round(loan.loan_amount - (loan.loan_amount * origination_fee_pct))
    installment_amount = loan.installment_amount
    if is_payment_point and loan.loan_duration == 1:
        installment_amount = loan.first_installment_amount

    partner_origin_name = data.get('partner_origin_name', None)
    process_add_partner_loan_request(loan, partner, None, 0, partner_origin_name)

    response_data = {
        'loan_status': loan.partnership_status,
        'loan_amount': loan.loan_amount,
        'disbursement_amount': int(disbursement_amount),
        'loan_duration': loan.loan_duration,
        'installment_amount': installment_amount,
        'monthly_interest': monthly_interest_rate,
        'loan_xid': loan.loan_xid,
    }
    # Should be update if the flow is paylater
    if paylater_transaction:
        update_paylater_transaction_status(paylater_transaction=paylater_transaction, loan=loan)

    update_customer_pin_used_status(application)

    return success_response(response_data)


def process_create_bank_account_destination(data, application):
    customer = application.customer
    bank_account_category = BankAccountCategory.objects.filter(
        category=data['category']
    ).last()

    if not bank_account_category:
        return general_error_response('kategori akun bank tidak ditemukan')
    bank = Bank.objects.filter(xfers_bank_code=data['bank_code']).last()
    method = get_validation_method(application)
    if bank_account_category.category != BankAccountCategoryConst.PARTNER:
        name_bank_validation_log = BankNameValidationLog.objects.filter(
            validation_status=NameBankValidationStatus.SUCCESS,
            account_number=data['account_number'],
            validation_id=data['validated_id'],
        ).last()

        if not name_bank_validation_log:
            return general_error_response('Bank account harus divalidasi terlebih dahulu')
        name_bank_validation = NameBankValidation.objects.create(
            bank_code=bank.xfers_bank_code,
            account_number=data['account_number'],
            name_in_bank=name_bank_validation_log.validated_name,
            mobile_phone=application.mobile_phone_1,
            method=method,
            validation_id=data['validated_id'],
            validated_name=name_bank_validation_log.validated_name,
            reason=NameBankValidationStatus.SUCCESS.lower(),
            validation_status=NameBankValidationStatus.SUCCESS)
    else:
        partnership_bank_account = PartnerBankAccount.objects.filter(
            partner=application.partner
        ).last()
        name_bank_validation = NameBankValidation.objects.get_or_none(
            pk=partnership_bank_account.name_bank_validation_id
        )
        data['account_number'] = partnership_bank_account.bank_account_number

    BankAccountDestination.objects.create(
        bank_account_category=bank_account_category,
        customer=customer,
        bank=bank,
        account_number=data['account_number'],
        name_bank_validation=name_bank_validation,
    )

    response_data = dict(
        category=bank_account_category.display_label,
        account_number=data['account_number'],
        name_in_bank=data['name_in_bank'],
        bank_name=bank.bank_name_frontend,
    )

    return success_response(response_data)


def validate_partner_bank_account(data):
    bank = Bank.objects.filter(xfers_bank_code=data['bank_code']).last()
    name_bank_validation = NameBankValidation(
        bank_code=bank.xfers_bank_code,
        account_number=data['account_number'],
        mobile_phone=data['mobile_phone'],
        method=NameBankValidationVendors.DEFAULT)
    xfers_service = XfersService()
    try:
        name_bank_validation_log = BankNameValidationLog()
        name_bank_validation_log.account_number = data['account_number']
        name_bank_validation_log.method = NameBankValidationVendors.DEFAULT
        response_validate = xfers_service.validate(name_bank_validation)
        name_bank_validation_log.validation_id = response_validate['id']
        name_bank_validation_log.validation_status = response_validate['status']
        name_bank_validation_log.validated_name = response_validate['validated_name']
        reason = response_validate['reason']
        response_message = response_validate['reason']
        if response_validate['status'] != NameBankValidationStatus.SUCCESS:
            reason = 'Gagal menambahkan rekening bank. Coba kembali beberapa saat.'
            response_message = 'Akun Bank Tidak Sesuai'
        name_bank_validation_log.reason = reason
        name_bank_validation_log.save()
    except XfersApiError:
        return general_error_response('Verifikasi akun bank gagal')

    response_data = dict(
        name_in_bank=response_validate['validated_name'],
        account_number=response_validate['account_no'],
        bank=response_validate['bank_abbrev'],
        validation_status=response_validate['status'],
        reason=response_message,
        validation_id=response_validate['id'],
    )

    return success_response(response_data)


def store_partner_bank_account(data):
    with transaction.atomic():
        partner = Partner.objects.get_or_none(pk=data['partner_id'])

        if not partner:
            return general_error_response('partner tidak ditemukan')
        name_bank_validation_log = BankNameValidationLog.objects.filter(
            validation_status=NameBankValidationStatus.SUCCESS,
            account_number=data['account_number'],
            validation_id=data['validated_id'],
        ).last()

        if not name_bank_validation_log:
            return general_error_response('Bank account harus divalidasi terlebih dahulu')

        bank = Bank.objects.filter(
            xfers_bank_code=data['bank_code']
        ).last()
        if not bank:
            return general_error_response('bank code tidak ditemukan')

        name_bank_validation = NameBankValidation.objects.create(
            bank_code=bank.xfers_bank_code,
            account_number=data['account_number'],
            name_in_bank=name_bank_validation_log.validated_name,
            mobile_phone=data['mobile_phone'],
            method=NameBankValidationVendors.DEFAULT,
            validation_id=name_bank_validation_log.validation_id,
            validated_name=name_bank_validation_log.validated_name,
            reason=NameBankValidationStatus.SUCCESS.lower(),
            validation_status=NameBankValidationStatus.SUCCESS)

        PartnerBankAccount.objects.create(
            partner=partner,
            name_in_bank=name_bank_validation.validated_name,
            bank_name=bank.bank_name,
            name_bank_validation_id=name_bank_validation.id,
            bank_account_number=name_bank_validation.account_number
        )

    return created_response(
        dict(
            account_number=data['account_number'],
            name_in_bank=name_bank_validation_log.validated_name,
            mobile_phone=data['mobile_phone'],
            bank_code=bank.xfers_bank_code,
        )
    )


def get_account_payments_and_virtual_accounts(application_xid, data):
    from juloserver.merchant_financing.services import get_payment_methods
    is_paid_off = data.get('is_paid_off', None)
    is_paid_off = is_paid_off == 'true'
    virtual_accounts = None
    only_fields = [
        'id',
        'account_id',
        'customer_id',
        'application_status_id'
    ]
    join_tables = [
        'account',
        'customer'
    ]

    application = Application.objects.select_related(*join_tables) \
        .only(*only_fields).filter(application_xid=application_xid).first()
    account_payment_query_set = AccountPayment.objects.filter(
        account=application.account
    ).exclude(due_amount=0, paid_amount=0).order_by('due_date')

    if is_paid_off:
        account_payments = account_payment_query_set.paid()
    else:
        account_payments = account_payment_query_set.not_paid_active()
        if not account_payments:
            loan = []
        else:
            loan = account_payment_query_set.first().payment_set.order_by('due_date').first().loan

        julo_bank_name = ''
        if account_payments.first():
            loan = account_payments.first().payment_set.order_by('due_date').first().loan
            julo_bank_name = loan.julo_bank_name

        virtual_accounts = get_payment_methods(application, julo_bank_name)

    return account_payments, virtual_accounts


def get_existing_partnership_loans(application):
    if application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
        return []
    loan_list = []
    account = application.account
    loans = Loan.objects.filter(account=account).order_by(
        '-cdate')
    for loan in loans.iterator():
        loan_dict = dict()
        loan_dict['loan_xid'] = loan.loan_xid
        loan_dict['loan_status'] = loan.partnership_status
        loan_list.append(loan_dict)
    return loan_list


def store_merchant_application_data(application, application_data):
    with transaction.atomic():
        application.update_safely(**application_data)

    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_PARTIAL,
        change_reason='customer_triggered')
    return application


def store_merchant_historical_transaction(
        application, merchant_transaction_histories, merchant_historical_transaction_task_id):
    MerchantHistoricalTransaction.objects.filter(
        application_id=application.id) \
        .update(is_deleted=True)
    merchant_transaction_histories_data = []
    for idx, merchant_transaction_history in enumerate(merchant_transaction_histories, start=1):
        is_using_lending_facilities = False
        if merchant_transaction_history['term_of_payment'] > 0:
            is_using_lending_facilities = True
        merchant_transaction_histories_data.append(MerchantHistoricalTransaction(
            merchant=application.merchant,
            type=merchant_transaction_history['type'],
            transaction_date=merchant_transaction_history['transaction_date'],
            booking_date=merchant_transaction_history['booking_date'],
            payment_method=merchant_transaction_history['payment_method'],
            amount=merchant_transaction_history['amount'],
            term_of_payment=merchant_transaction_history['term_of_payment'],
            is_using_lending_facilities=is_using_lending_facilities,
            application=application,
            merchant_historical_transaction_task_id=merchant_historical_transaction_task_id,
            reference_id='%s-%s' % (str(merchant_historical_transaction_task_id), str(idx))
        ))
    MerchantHistoricalTransaction.objects.bulk_create(
        merchant_transaction_histories_data
    )


def process_customer_pin(customer_data, application):
    customer = application.customer
    redirect_url = DEFAULT_PARTNER_REDIRECT_URL

    with transaction.atomic():
        user = customer.user
        user.set_password(customer_data['pin'])
        user.save()
        try:
            customer_pin_service = CustomerPinService()
            customer_pin_service.init_customer_pin(user)
            redirect_url = get_partner_redirect_url(application)

        except IntegrityError:
            return general_error_response('PIN aplikasi sudah ada')

    return created_response(
        dict(
            message='PIN berhasil dibuat',
            redirect_url=redirect_url
        )
    )


def update_customer_pin_used_status(application):
    CustomerPinVerify.objects.filter(customer=application.customer)\
        .update(is_pin_used=True)


def get_product_lookup_by_merchant(merchant, application_id=None, is_work_flow_check=False):
    distributor = merchant.distributor
    if not distributor:
        raise JuloException("Merchant id: {} doesn't have distributor".format(merchant.id))

    partner = distributor.partner
    if not partner:
        raise JuloException(
            "Distributor id: {} from merchant id: {} doesn't have partner".format(
                distributor.id, merchant.id
            )
        )

    merchant_score = merchant.business_rules_score

    if not merchant_score:
        raise JuloException(
            "Merchant id: {} doesn't have business_rules_score".format(merchant.id)
        )

    master_partner_config_product_lookup = MasterPartnerConfigProductLookup.objects.filter(
        partner=partner, minimum_score__lte=merchant_score, maximum_score__gte=merchant_score
    ).first()
    if not master_partner_config_product_lookup:
        if is_work_flow_check:
            process_application_status_change(
                application_id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                "Product lookup doesn't exist")
        else:
            raise JuloException(
                "Product lookup for merchant id: {} doesn't exists".format(merchant.id)
            )

    maximum_score = master_partner_config_product_lookup.maximum_score
    minimum_score = master_partner_config_product_lookup.minimum_score
    historical_partner_config_product_lookup = HistoricalPartnerConfigProductLookup.objects.filter(
        master_partner_config_product_lookup=master_partner_config_product_lookup,
        maximum_score=maximum_score, minimum_score=minimum_score
    ).select_related('product_lookup').last()

    if not historical_partner_config_product_lookup:
        if is_work_flow_check:
            process_application_status_change(
                application_id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                "Product lookup doesn't exist")
        else:
            raise JuloException(
                "Product lookup for merchant id: {} doesn't exists".format(merchant.id)
            )

    # historical_partner_config_product_lookup have relation to product lookup
    return historical_partner_config_product_lookup


def is_able_to_reapply(application):
    # Will return 2 data: boolean and not able reason (if False)
    customer = application.customer
    if customer.can_reapply:
        return (True, '')
    else:
        today_date = timezone.localtime(timezone.now())

        if customer.can_reapply_date <= today_date:
            return (True, '')
        else:
            delta_datetime = customer.can_reapply_date - today_date
            reapply_duration = delta_datetime.days + 1
            return (False,
                    'Silakan tunggu selama {} hari untuk dapat melanjutkan proses ini'.format(
                        reapply_duration
                    ),
                    reapply_duration
                    )


def get_initialized_data_whitelabel(
    email: str,
    phone: str,
    partner_name: str,
    partner_reference_id: str,
    partner_customer_id: str = "",
    partner_origin_name: str = "",
    is_web: bool = False
):
    """
        based on PARTNER-1865, init_redirect_url just dead base url
        So in the FE side can mapping the error with uri path
        eg: http://close-webview.julo.co.id/unregistered,
        then partner apps can detect the webview error based on the path
    """
    partnership_config = PartnershipConfig.objects.get_or_none(
        partner__name=partner_name
    )
    init_redirect_url = "julo://close-webview.julo.co.id"
    redirect_url = (
        partnership_config.redirect_url if partnership_config.redirect_url else init_redirect_url
    )
    encoded_redirect_url = urllib.parse.quote(redirect_url, safe="")
    encrypted_string = None
    possible_phone_numbers = {
        format_mobile_phone(phone),
        format_nexmo_voice_phone_number(phone),
    }
    application_xid = ""
    account_active = False
    is_linked = False
    otp_type = OTPType.SMS
    error_msg = ""
    customer_by_email_and_phone = Customer.objects.filter(email=email.lower(),
                                                          phone__in=possible_phone_numbers).last()
    if customer_by_email_and_phone:
        encrypted_string = generate_public_key_whitelabel(
            email.lower(),
            phone,
            partner_name,
            partner_reference_id,
            partner_customer_id=partner_customer_id,
            partner_origin_name=partner_origin_name
        )
        # Customer by email and phone both found
        (
            application,
            account_active,
            is_linked,
            relative_path,
            error_type,
        ) = _get_whitelabel_paylater_data_by_customer_and_partner(customer_by_email_and_phone,
                                                                  partner_name)
        if application and account_active:
            application_xid = application.application_xid
        else:
            error_msg = ErrorMessageConst.INVALID_LOGIN
    else:
        customer_by_email = Customer.objects.filter(email=email.lower()).last()
        if customer_by_email:
            # Customer by email found
            encrypted_string = generate_public_key_whitelabel(
                email.lower(),
                phone,
                partner_name,
                partner_reference_id,
                partner_customer_id=partner_customer_id,
                email_phone_diff='email',
                partner_origin_name=partner_origin_name
            )
            # Customer by email and phone both found
            (
                application,
                account_active,
                is_linked,
                relative_path,
                error_type,
            ) = _get_whitelabel_paylater_data_by_customer_and_partner(customer_by_email,
                                                                      partner_name)
            if application and account_active:
                application_xid = application.application_xid
                if customer_by_email.phone not in possible_phone_numbers:
                    # Phone number is not same with customer_by_email
                    otp_type = OTPType.EMAIL
        else:
            # Customer by Email not found
            customer_by_phone = Customer.objects.filter(
                phone__in=possible_phone_numbers
            ).last()

            if customer_by_phone:
                # Customer by phone is found
                encrypted_string = generate_public_key_whitelabel(
                    email.lower(),
                    phone,
                    partner_name,
                    partner_reference_id,
                    partner_customer_id=partner_customer_id,
                    email_phone_diff='phone',
                    partner_origin_name=partner_origin_name
                )
                (
                    application,
                    account_active,
                    is_linked,
                    relative_path,
                    error_type,
                ) = _get_whitelabel_paylater_data_by_customer_and_partner(
                    customer_by_phone, partner_name
                )
                if application and account_active:
                    application_xid = application.application_xid

            else:
                # Customer by Phone Number and Email Not Found
                relative_path = WhitelabelURLPaths.VERIFY_PAGE
                encrypted_string = generate_public_key_whitelabel(
                    email.lower(),
                    phone,
                    partner_name,
                    partner_reference_id,
                    partner_customer_id=partner_customer_id,
                    partner_origin_name=partner_origin_name
                )
                error_type = WhitelabelErrorType.VERIFY
                error_msg = ErrorMessageConst.EMAIL_OR_PHONE_NOT_FOUND

    webview_url = get_webview_url_whitelabel(
        relative_path, encrypted_string, error_type, redirect_url=encoded_redirect_url
    )

    webview_url = "{}&otp_type={}".format(webview_url, otp_type)
    if redirect_url and is_linked:
        if not account_active:
            application_xid = ""
        redirect_url = add_url_query_param(
            redirect_url, application_xid, partner_reference_id
        )

    return_data = {
        "user_token": encrypted_string if account_active else None,
        "account_active": account_active,
        "is_linked": is_linked,
        "webview_url": webview_url,
        "application_xid": application_xid if account_active else None,
        "redirect_url": redirect_url,
    }
    if is_web:
        return_data['error_msg'] = error_msg

    return return_data


def _get_whitelabel_paylater_data_by_customer_and_partner(
    customer: Customer, partner_name: str
) -> Tuple[Application, bool, bool, str, str]:
    """
    This function will return Application, account_active, is_linked, relative_path, error_type
    """
    UNLOCK_STATUS = {
        AccountConstant.STATUS_CODE.active,
        AccountConstant.STATUS_CODE.active_in_grace,
    }
    relative_path = WhitelabelURLPaths.ERROR_PAGE
    account_active = False
    is_linked = False
    application = customer.application_set.filter(
        product_line__product_line_code__in=ProductLineCodes.julo_one(),
        application_status_id=ApplicationStatusCodes.LOC_APPROVED,
    ).select_related('account').last()

    if application:
        if application.account:
            if application.account.status_id in UNLOCK_STATUS:
                # Account already active
                account_active = True
                is_linked = application.account.partnerproperty_set.filter(
                    partner__name=partner_name, is_active=True
                ).exists()
                relative_path = WhitelabelURLPaths.TNC_PAGE
                error_type = ""
            else:
                # Account inactive
                error_type = WhitelabelErrorType.VERIFICATION_IN_PROGRESS
        else:
            # Application without Account means system error
            error_type = WhitelabelErrorType.SYSTEM_ERROR
    else:
        # Application Not Found But Customer Exits
        error_type = WhitelabelErrorType.VERIFICATION_IN_PROGRESS

    return (application, account_active, is_linked, relative_path, error_type)


def get_webview_url_whitelabel(
        relative_path, encrypted_string, error_type=None, redirect_url=None):
    base_url = settings.WHITELABEL_FRONTEND_BASE_URL
    url = base_url + relative_path

    final_url = url.format(
        secret_key=encrypted_string,
        error_type=error_type,
        redirect_url=redirect_url
    )
    return final_url


def process_register_partner_whitelabel_paylater(partner_data):
    group = Group.objects.get(name="julo_partners")
    password = make_password('partner_{}'.format(partner_data['username']))
    with transaction.atomic():
        user = User.objects.create(username=partner_data['username'],
                                   email=partner_data['email'],
                                   password=password)
        user.groups.add(group)
        make_never_expiry_token(user)
        encrypter = encrypt()
        secret_key = encrypter.encode_string(str(user.auth_expiry_token))

        partner = Partner.objects.create(
            user=user,
            name=partner_data['username'],
            email=partner_data['email'],
            token=secret_key
        )

        partnership_type = PartnershipType.objects.get_or_none(
            partner_type_name=PartnershipTypeConstant.WHITELABEL_PAYLATER)
        if not partnership_type:
            raise JuloException("Partnership Type Error")

        if partner_data['callback_url'] and 'https' not in partner_data['callback_url']:
            raise JuloException(r"callback_url harus menggunakan format 'https'")

        partner_config = PartnershipConfig.objects.create(
            partner=partner,
            partnership_type=partnership_type,
            callback_url=partner_data['callback_url'],
            callback_token=partner_data['callback_token'],
            redirect_url=partner_data['redirect_url']
        )
    encrypter = encrypt()
    secret_key = encrypter.encode_string(str(user.auth_expiry_token))

    response_data = {
        'partner_name': partner.name,
        'partner_email': partner.email,
        'secret_key': secret_key,
        'callback_url': partner_config.callback_url,
        'callback_token': partner_config.callback_token,
        'redirect_url': partner_config.redirect_url
    }

    return response_data


def whitelabel_paylater_link_account(
    customer: Customer,
    partner: Partner,
    unique_customer_identifier: str,
    julo_application: Application,
    partner_customer_id: str = None,
    partner_origin_name: str = None,
) -> Dict:
    if not julo_application:
        raise JuloException("Julo Application is not available for this customer")

    customer_verify_pin = CustomerPinVerify.objects.filter(
        customer=customer,
        is_pin_used=False,
        expiry_time__gt=timezone.localtime(timezone.now())
    ).last()

    time_10_min_before = timezone.localtime(timezone.now()) - timedelta(minutes=10)
    otp_request = OtpRequest.objects.filter(
        customer=customer,
        is_used=True,
        cdate__gt=time_10_min_before,
        application=julo_application
    ).last()

    if not customer_verify_pin and not otp_request:
        raise JuloException("Need to verify PIN and OTP before linking")

    if not customer_verify_pin:
        raise JuloException("Pin Needs to be verified before Linking")

    if not otp_request:
        raise JuloException("OTP verification needed before Linking")

    if PartnerProperty.objects.filter(
        partner=partner,
        account=julo_application.account
    ).exclude(partner_reference_id=unique_customer_identifier).exists():
        raise JuloException("Account already linked for partner with different partner"
                            " reference id")

    if PartnerProperty.objects.filter(
        partner_reference_id=unique_customer_identifier
    ).exclude(account=julo_application.account).exists():
        raise JuloException("Partner Reference ID already registered on "
                            "different application")

    if PartnerProperty.objects.filter(
        partner=partner,
        account=julo_application.account,
        partner_reference_id=unique_customer_identifier,
        is_active=True
    ).exists():
        raise JuloException("Account is already linked")

    with transaction.atomic():
        return_data = {
            "is_linked": True,
            "partner_reference": unique_customer_identifier
        }

        account = julo_application.account
        UNLOCK_STATUS = {AccountConstant.STATUS_CODE.active,
                         AccountConstant.STATUS_CODE.active_in_grace}
        if account.status_id not in UNLOCK_STATUS:
            raise JuloException("Account Not in active status. Please activate before continuing")

        partner_property = PartnerProperty.objects.filter(
            partner=partner,
            partner_reference_id=unique_customer_identifier,
            account=account
        ).last()

        if not partner_property:
            partner_property = PartnerProperty.objects.create(
                partner=partner,
                partner_reference_id=unique_customer_identifier,
                account=account,
                partner_customer_id=partner_customer_id
            )
        partner_property.is_active = True
        partner_property.save(update_fields=['is_active'])

        # send email linking
        notify_user_linking_account.delay(customer_id=customer.id,
                                          partner_id=partner.id)

        ApplicationNote.objects.create(
            note_text="Application linked with partner: {}".format(partner.name),
            application_id=julo_application.id,
        )
        customer_verify_pin.update_safely(is_pin_used=True)
        partner_origin = PartnerOrigin.objects.filter(
            partner_origin_name=partner_origin_name, partner=partner).last()
        active_account = AccountConstant.STATUS_CODE.active
        is_valid_application = (julo_application and julo_application.account
                                and julo_application.account.status_id == active_account)
        is_valid_partner_origin = partner_origin and partner_origin_name
        if is_valid_application and is_valid_partner_origin:
            partner_origin.update_safely(is_linked=partner_property.is_active)
            update_moengage_for_user_linking_status.delay(julo_application.account.id,
                                                          partner_origin.id)

    return return_data


def unlink_account_whitelabel(partner, application, data):
    with transaction.atomic():
        unique_reference_id = data['partner_reference_id']
        partner_origin_name = data.get('partner_origin_name', '')
        partner_property = PartnerProperty.objects.filter(
            partner=partner,
            account=application.account
        )
        if not partner_property.exists():
            raise JuloException(ErrorMessageConst.ACCOUNT_NOT_LINKED)
        partner_property = partner_property.filter(
            partner_reference_id=unique_reference_id
        ).last()
        if not partner_property:
            raise JuloException(ErrorMessageConst.PARTNER_REFERENCE_NOT_MATCHED)
        if not partner_property.is_active:
            raise JuloException(ErrorMessageConst.ACCOUNT_NOT_LINKED)
        else:
            partner_property.update_safely(is_active=False)
            partner_origin = PartnerOrigin.objects.filter(
                partner_origin_name=partner_origin_name, partner=partner).last()
            is_valid_application = application and application.account
            is_valid_partner_origin = partner_origin and partner_origin_name
            if is_valid_application and is_valid_partner_origin:
                partner_origin.update_safely(is_linked=partner_property.is_active)
                update_moengage_for_user_linking_status.delay(application.account.id,
                                                              partner_origin.id)
    return {"is_linked": partner_property.is_active}


def get_status_summary_whitelabel(application, partner):
    application_data = {
        "application_xid": application.application_xid,
        "email": application.customer.email,
        "ktp": application.ktp,
        "application_status": application.partnership_status,
        "fullname": application.fullname,
        "mobile_phone_1": application.mobile_phone_1
    }
    account = application.account
    if account:
        account_limit = account.accountlimit_set.last()
        loans = account.loan_set.select_related('loan_status').all().order_by('id')
    else:
        account_limit = None
        loans = []
    account_data = {
        "account_status": account.status.status if account else None,
        "available_limit": account_limit.available_limit if account_limit else None,
        "max_limit": account_limit.max_limit if account_limit else None,
        "set_limit": account_limit.set_limit if account_limit else None,
        "used_limit": account_limit.used_limit if account_limit else None,
        "is_linked": account.partnerproperty_set.filter(
            partner=partner, is_active=True).exists() if account else None
    }
    loans_data = []
    for loan in loans:
        loan_data = {
            "loan_xid": loan.loan_xid,
            "loan_status": loan.partnership_status
        }
        loans_data.append(loan_data)
    return_data = {
        "application": application_data,
        "account": account_data,
        "loans": loans_data
    }
    return return_data


def process_add_partner_loan_request(loan: Loan,
                                     partner: Partner,
                                     distributor: Distributor = None,
                                     loan_original_amount: float = 0,
                                     partner_origin_name: str = None) -> None:
    with transaction.atomic():
        loan_amount = loan.loan_amount
        loan_disbursement_amount = loan.loan_disbursement_amount
        partner_loan_request, _ = PartnerLoanRequest.objects.get_or_create(
            loan=loan,
            partner=partner,
            distributor=distributor,
            loan_amount=loan_amount,
            loan_disbursement_amount=loan_disbursement_amount,
            loan_original_amount=loan_original_amount,
            partner_origin_name=partner_origin_name
        )
        partner_origin = PartnerOrigin.objects.filter(
            partner_origin_name=partner_origin_name, partner=partner).last()
        if partner_origin and partner_origin_name and loan.account and \
                loan.account.status_id == AccountConstant.STATUS_CODE.active:
            update_moengage_for_user_linking_status.delay(loan.account.id, partner_origin.id,
                                                          partner_loan_request.id)


def get_confirm_pin_url(application):
    confirm_pin_dict = dict()
    encrypter = encrypt()
    xid = \
        encrypter.encode_string(str(application.application_xid))
    pin_url = settings.WHITELABEL_FRONTEND_BASE_URL + WhitelabelURLPaths.INPUT_PIN.format(
        xid=xid)
    confirm_pin_dict['pin_webview_url'] = pin_url
    return confirm_pin_dict


def partnership_check_image_upload(application_id):
    # Get the image by using negative partnership_application_id
    # Because we convert image_source to use negative to distinguish it with application id
    images = Image.objects.filter(
        image_type__in=['selfie_partnership', 'ktp_self_partnership', 'crop_selfie_partnership'],
        image_source=-abs(application_id + 510)
    ).distinct('image_type')

    if images.count() < 3:
        return False

    return True


def check_existing_customer_and_application(partnership_customer):
    customer = Customer.objects.filter(
        nik=partnership_customer.nik
    ).first()
    if customer:
        application = customer.application_set.order_by('id').last()
        return (customer, application)
    else:
        return (None, None)


def create_customer_and_application(nik, email, partner, latitude=None, longitude=None):
    with transaction.atomic():
        user = User(username=nik, email=email)
        user.save()

        customer = Customer.objects.create(
            user=user, email=email, nik=nik,
            appsflyer_device_id=None,
            advertising_id=None,
            mother_maiden_name=None)

        application = Application.objects.create(
            customer=customer,
            ktp=nik,
            email=email,
            partner=partner,
        )
        update_customer_data(application)

        # update workflow and product_line to julo1
        assign_julo1_application(application)

        julo_services.process_application_status_change(
            application.id, ApplicationStatusCodes.FORM_CREATED,
            change_reason='customer_triggered'
        )

        if latitude and longitude:
            # create AddressGeolocation
            address_geolocation = AddressGeolocation.objects.create(
                application=application,
                latitude=latitude,
                longitude=longitude)

            generate_address_from_geolocation_async.delay(address_geolocation.id)

            # store location to device_geolocation table
            apiv2_services.store_device_geolocation(
                customer,
                latitude=latitude,
                longitude=longitude
            )
        create_application_checklist_async.delay(application.id)
    application.refresh_from_db()
    return (customer, application)


def create_or_update_application(customer, partner, partnership_application, application=None):
    from juloserver.partnership.serializers import WebviewApplicationSerializer

    if not application:
        application = Application.objects.create(
            customer=customer,
            ktp=customer.nik,
            email=customer.email,
            partner=partner,
        )
        update_customer_data(application)
        assign_julo1_application(application)
        julo_services.process_application_status_change(
            application.id, ApplicationStatusCodes.FORM_CREATED,
            change_reason='customer_triggered'
        )

        if partnership_application.latitude and partnership_application.longitude:
            address_geolocation = AddressGeolocation.objects.create(
                application=application,
                latitude=partnership_application.latitude,
                longitude=partnership_application.longitude
            )
            generate_address_from_geolocation_async.delay(address_geolocation.id)
            apiv2_services.store_device_geolocation(
                customer,
                latitude=partnership_application.latitude,
                longitude=partnership_application.longitude
            )
        create_application_checklist_async.delay(application.id)
        application.refresh_from_db()

    with transaction.atomic():
        serializer = WebviewApplicationSerializer(
            application,
            model_to_dict(partnership_application)
        )
        serializer.is_valid(raise_exception=True)
        create_application_field_change(application, serializer.validated_data)
        application = serializer.save()

        if not CustomerPin.objects.filter(user=customer.user).exists():
            decoded_pin = get_decoded_pin(partnership_application.encoded_pin)
            user = customer.user
            user.set_password(decoded_pin)
            user.save()
            current_time = timezone.localtime(timezone.now())
            customer_pin = CustomerPin.objects.create(
                last_failure_time=current_time,
                latest_failure_count=0,
                user=user,
            )

            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.PARTNER_PIN_EXPIRY_TIME,
                is_active=True
            ).last()
            if feature_setting:
                partner_pin_expiry_time = feature_setting.parameters['partner_pin_expiry_time']
                expiry_time = current_time + timedelta(seconds=partner_pin_expiry_time)
            else:
                expiry_time = current_time + timedelta(seconds=300)

            CustomerPinVerify.objects.create(
                customer=application.customer,
                is_pin_used=False,
                customer_pin=customer_pin,
                expiry_time=expiry_time
            )

        if application.customer.mother_maiden_name !=\
                partnership_application.mother_maiden_name:
            CustomerFieldChange.objects.create(
                customer=application.customer,
                field_name='mother_maiden_name',
                old_value=application.customer.mother_maiden_name,
                new_value=partnership_application.mother_maiden_name,
                application=application
            )

        application.customer.update_safely(
            mother_maiden_name=partnership_application.mother_maiden_name
        )
        application.web_version = partnership_application.web_version\
            if partnership_application else application.web_version
        application.save()
        application.refresh_from_db()
    # store the application to application experiment
    store_application_to_experiment_table(application, 'ExperimentUwOverhaul')
    process_application_status_change(
        application.id, ApplicationStatusCodes.FORM_PARTIAL,
        change_reason='customer_triggered')
    application.refresh_from_db()
    populate_zipcode.delay(application.id)
    partnership_application.application = application
    partnership_application.save()

    return application


def process_partnership_longform(partnership_customer, partnership_application,
                                 customer=None, application=None, pin=None):
    if not application and not customer:
            if Customer.objects.filter(email__iexact=partnership_application.email).exists():
                response = {
                    'application_id': None,
                    'expiry_token': None,
                    'message': 'Customer dengan email sudah ada',
                    'redirect_to_page': 'registration_page'
                }
                return success_response(response)
            customer, application = create_customer_and_application(
                partnership_customer.nik,
                partnership_application.email,
                partnership_customer.partner,
                partnership_application.latitude,
                partnership_application.longitude
            )
            application = create_or_update_application(
                customer, partnership_customer.partner,
                partnership_application, application=application
            )
    # Existing Customer without Application
    elif not application and customer:
        application = create_or_update_application(customer, partnership_customer.partner,
                                                   partnership_application)
    # Reapply Customer
    elif customer.can_reapply and application.application_status.status_code in {
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
            ApplicationStatusCodes.APPLICATION_DENIED,
            ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
            ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
            ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
    }:
        if not pin:
            return general_error_response('Pin %s' % ErrorMessageConst.SHOULD_BE_FILLED)
        verify_pin = verify_pin_webview_longform('process_partnership_longform', customer, pin)
        if type(verify_pin) == bool and verify_pin:
            application = create_or_update_application(customer, partnership_customer.partner,
                                                       partnership_application)
        else:
            return verify_pin

    # 100 Application
    elif application.application_status.status_code == ApplicationStatusCodes.FORM_CREATED:
        if not pin:
            return general_error_response('Pin %s' % ErrorMessageConst.SHOULD_BE_FILLED)
        verify_pin = verify_pin_webview_longform('process_partnership_longform', customer, pin)
        if type(verify_pin) == bool and verify_pin:
            application = create_or_update_application(
                customer, partnership_customer.partner,
                partnership_application, application=application)
        else:
            return verify_pin
    else:
        response = {
            'application_id': None,
            'expiry_token': None,
            'message': 'Customer dan aplikasi sudah ada dengan status aplikasi: %s'
            % application.partnership_status,
            'redirect_to_page': 'j1_verification_page'
        }
        return success_response(response)

    partnership_customer.customer = customer
    partnership_customer.save()
    partnership_application.is_used_for_registration = True
    partnership_application.save()
    update_image_source_id_partnership(-abs(partnership_application.id + 510), application.id)
    expiry_token = generate_new_token(customer.user)

    response = {
        'application_id': application.id,
        'expiry_token': expiry_token,
        'message': '',
        'redirect_to_page': ''
    }
    return success_response(response)


def update_image_source_id_partnership(previous_id, new_id):
    all_images = Image.objects.filter(image_source=previous_id)
    all_images.filter(image_type='selfie_partnership').update(image_type='selfie')
    all_images.filter(image_type='crop_selfie_partnership').update(image_type='crop_selfie')
    all_images.filter(image_type='ktp_self_partnership').update(image_type='ktp_self')
    all_images = Image.objects.filter(image_source=previous_id) \
        .update(image_source=new_id)


def get_decoded_pin(encrypted_pin):
    encrypter = encrypt()
    decoded_pin = encrypter.decode_string(str(encrypted_pin))
    return decoded_pin


def process_image_upload_partnership(
    image, image_data=None, thumbnail=True, delete_if_last_image=False
):
    """
    image -> Image Object
    image_data = {
        'file_extension':'.jpeg',
        'image_file': file,
        'image_byte_file': bytes,
    }
    """
    if image_data is None:
        image_data = {}
    try:
        application = Application.objects.filter(id=image.image_source).first()
        partnership_application = None
        if not application:
            partnership_application = (
                PartnershipApplicationData.objects.select_related('partnership_customer_data')
                .filter(id=abs(image.image_source) - 510)
                .first()
            )
            if not partnership_application:
                raise JuloException('Unrecognized image_source=%s' % image.image_source)

        # upload image to s3 and save s3url to field
        string_file = "application"
        if partnership_application:
            string_file = "partnership_application"
            cust_id = str(partnership_application.partnership_customer_data.id)
        else:
            cust_id = str(application.customer_id)
        file_extension = image_data.get('file_extension', '.jpeg')
        image_byte = image_data.get('image_byte_file', None)
        image_file = image_data.get('image_file')
        if not image_file and not image_byte:
            logger.info(
                {
                    'action': 'process_image_upload_partnership',
                    'image_source_id': image.id,
                    'application_id': image.image_source,
                    'message': 'wrong image data please input it correctly',
                }
            )
            return
        if not image_byte:
            image_byte = image_file.file.read()

        filename = "%s_%s%s" % (image.image_type, str(image.id), file_extension)
        image_remote_filepath = '/'.join(['cust_' + cust_id, string_file, filename])

        upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, image_byte, image_remote_filepath)
        image.update_safely(url=image_remote_filepath)

        logger.info(
            {
                'status': 'successfull upload image to s3',
                'image_remote_filepath': image_remote_filepath,
                'application_id': image.image_source,
                'image_type': image.image_type,
            }
        )

        # mark all other images with same type as 'deleted'
        image_query = (
            Image.objects.exclude(id=image.id)
            .exclude(image_status=Image.DELETED)
            .filter(image_source=image.image_source, image_type=image.image_type)
        )

        # handle race condition if image type is ktp_self
        if image.image_type == 'ktp_self':

            # getting application data
            application = Application.objects.filter(pk=image.image_source).last()
            if application and application.is_julo_one_or_starter():

                # get other images to delete with id <= current_image.id
                image_query = image_query.filter(id__lte=image.id)
                logger.info(
                    {
                        'status': 'delete selected image',
                        'image_remote_filepath': image_remote_filepath,
                        'application_id': image.image_source,
                        'image_id': image.id,
                        'image_list': list(image_query),
                    }
                )

        images = list(image_query)
        mark_delete_images = True
        if delete_if_last_image:
            last_image = Image.objects.filter(
                image_source=image.image_source, image_type=image.image_type
            ).last()
            mark_delete_images = True if last_image.id == image.id else False

        if mark_delete_images:
            for img in images:
                logger.info({'action': 'marking_deleted', 'image': img.id})
                img.update_safely(image_status=Image.DELETED)

        if image.image_ext != '.pdf' and thumbnail:
            img_buffer = BytesIO(image_byte)
            with Imagealias.open(img_buffer) as im:
                # Create thumbnail
                im = im.convert('RGB')
                size = (150, 150)
                im.thumbnail(size, Imagealias.ANTIALIAS)

                # Save thumbnail to bytes
                thumbnail_buffer = BytesIO()
                im.save(thumbnail_buffer, format='JPEG', quality=85)
                thumbnail_bytes = thumbnail_buffer.getvalue()

            # Generate thumbnail filename and path
            thumbnail_filename = "%s_%s_%s%s" % (
                image.image_type,
                str(image.id),
                'thumbnail',
                file_extension,
            )
            thumbnail_dest_name = '/'.join(
                ['cust_' + cust_id, 'partnership_application', thumbnail_filename]
            )

            # Upload thumbnail to OSS
            upload_file_as_bytes_to_oss(
                settings.OSS_MEDIA_BUCKET, thumbnail_bytes, thumbnail_dest_name
            )
            image.update_safely(thumbnail_url=thumbnail_dest_name)

            logger.info(
                {
                    'status': 'successfull upload thumbnail to s3',
                    'thumbnail_dest_name': thumbnail_dest_name,
                    'application_id': image.image_source,
                    'image_type': image.image_type,
                }
            )
    except Exception:
        get_julo_sentry_client().captureException()


def update_partner_application_pin(validated_data, partnership_customer_data):
    encoded_pin = get_encoded_pin(validated_data['pin'])
    partnership_application_data = PartnershipApplicationData.objects.filter(
        partnership_customer_data=partnership_customer_data).last()
    partnership_application_data.encoded_pin = encoded_pin
    partnership_application_data.save()

    return created_response(
        dict(
            message='PIN berhasil dibuat'
        )
    )


def is_valid_data(nik, pin):
    error_msg = customer_pin = customer = None
    if not nik or nik is None:
        return customer, customer_pin, VerifyPinMsg.USER_NOT_FOUND

    pii_nik_filter_dict = generate_pii_filter_query_partnership(Customer, {'nik': nik})
    customer = Customer.objects.filter(**pii_nik_filter_dict).last()
    if not customer:
        return customer, customer_pin, VerifyPinMsg.USER_NOT_FOUND

    user = customer.user
    if not user:
        return customer, customer_pin, VerifyPinMsg.USER_NOT_FOUND

    if not pin:
        return customer, customer_pin, VerifyPinMsg.REQUIRED_PIN

    customer_pin = CustomerPin.objects.filter(user=user).last()
    if not customer_pin:
        return customer, customer_pin, 'pin tidak dibuat'

    return customer, customer_pin, error_msg


def get_encoded_pin(pin):
    encrypter = encrypt()
    encoded_pin = encrypter.encode_string(str(pin))

    return encoded_pin


def verify_pin_webview_longform(reason, customer, pin):
    android_id = None
    user = customer.user
    if not user:
        return general_error_response(VerifyPinMsg.USER_NOT_FOUND)

    customer_pin = CustomerPin.objects.filter(user=user).last()
    if not customer_pin:
        return general_error_response('pin not created')
    customer_pin_verify_data = CustomerPinVerify.objects.get_or_none(customer_pin=customer_pin)
    if customer_pin_verify_data:
        customer_pin_verify_data.update_safely(is_pin_used=True)

    pin_process = VerifyPinProcess()
    code, msg, _ = pin_process.verify_pin_process(
        view_name=reason, user=user, pin_code=pin, android_id=android_id
    )
    if code != ReturnCode.OK:
        if code == ReturnCode.LOCKED:
            return forbidden_error_response(msg)
        elif code == ReturnCode.FAILED:
            return unauthorized_error_response(msg)
        return general_error_response(msg)
    with transaction.atomic():
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.PARTNER_PIN_EXPIRY_TIME,
            is_active=True
        ).last()
        current_time = timezone.localtime(timezone.now())
        if feature_setting:
            partner_pin_expiry_time = feature_setting.parameters['partner_pin_expiry_time']
            expiry_time = current_time + timedelta(seconds=partner_pin_expiry_time)
        else:
            expiry_time = current_time + timedelta(seconds=300)
        if not customer_pin_verify_data:
            customer_pin_verify_data = CustomerPinVerify.objects.create(
                customer=customer,
                is_pin_used=False,
                customer_pin=customer_pin,
                expiry_time=expiry_time
            )
        else:
            customer_pin_verify_data.update_safely(is_pin_used=False, expiry_time=expiry_time)

        customer_pin_verify_history_data = dict(customer_pin_verify=customer_pin_verify_data,
                                                is_pin_used=False,
                                                expiry_time=expiry_time)

        CustomerPinVerifyHistory.objects.create(**customer_pin_verify_history_data)
    return True


def create_application_field_change(application, updated_data):
    if not type(application) is dict:
        dict_application = model_to_dict(application)
    else:
        dict_application = application

    app_field_change_list = []
    for key in updated_data:
        if isinstance(dict_application.get(key), datetime.date) or\
                isinstance(dict_application.get(key), datetime.datetime):
            dict_application[key] = dict_application[key].strftime('%Y-%m-%d')

        if (dict_application.get(key) != updated_data[key]) and\
                dict_application.get(key):
            app_field_change_list.append(ApplicationFieldChange(
                application=application,
                field_name=key,
                old_value=dict_application.get(key),
                new_value=updated_data[key]
            ))
    ApplicationFieldChange.objects.bulk_create(app_field_change_list)


def check_application_loan_status(loan):
    if loan.status != LoanStatusCodes.INACTIVE:
        return False

    application = loan.customer.application_set.last()
    if not application:
        return False

    if application.status != ApplicationStatusCodes.LOC_APPROVED:
        return False

    return True


def check_application_account_status(loan):
    application = loan.customer.application_set.last()
    if not application:
        return False

    if application.status != ApplicationStatusCodes.LOC_APPROVED:
        return False

    account = application.account
    UNLOCK_STATUS = {AccountConstant.STATUS_CODE.active,
                     AccountConstant.STATUS_CODE.active_in_grace}
    if account.status_id not in UNLOCK_STATUS:
        return False

    return True


def add_url_query_param(redirect_url, application_xid, partner_reference_id):
    redirect_url = "{}?application_xid={}&partner_reference_id={}".format(
        redirect_url, application_xid, partner_reference_id)

    return redirect_url


def get_partner_redirect_url(application):
    redirect_url = DEFAULT_PARTNER_REDIRECT_URL
    partner = application.partner
    account = application.account
    if not partner and account:
        partner_property = PartnerProperty.objects.filter(account=account, is_active=True).last()
        if partner_property:
            partner = partner_property.partner

    if partner:
        partnership_config = PartnershipConfig.objects.filter(
            partner=partner
        ).last()
        if partnership_config and partnership_config.redirect_url:
            redirect_url = partnership_config.redirect_url

    return redirect_url


def call_slack_bot(partner_name='', url='', method='', headers='', body='', case='',
                   response_status='', response_data=''):
    slack_bot_client = get_slack_bot_client()
    message = ("<!here> %s API Call Failed\n```URL: %s\nMETHOD: %s" "\nHEADERS: %s\nBODY: %s\nCASE:"
               " %s\nRESPONSE STATUS: %s\n" "RESPONSE DATA: %s```" %
               (partner_name, url, method, headers, body, case, response_status, response_data))
    slack_bot_client.api_call(
        "chat.postMessage",
        channel=SLACK_CHANNEL_LEADGEN_WEBVIEW_NOTIF,
        text=message,
    )


def void_payment_status_on_loan_cancel(loan):
    payments = loan.payment_set.normal().filter(
        payment_status__in=[PaymentStatusCodes.PAYMENT_NOT_DUE,
                            PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                            PaymentStatusCodes.PAYMENT_DUE_TODAY,
                            PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                            PaymentStatusCodes.PAYMENT_1DPD,
                            PaymentStatusCodes.PAYMENT_5DPD,
                            PaymentStatusCodes.PAYMENT_30DPD,
                            PaymentStatusCodes.PAYMENT_60DPD,
                            PaymentStatusCodes.PAYMENT_90DPD,
                            PaymentStatusCodes.PAYMENT_120DPD,
                            PaymentStatusCodes.PAYMENT_150DPD,
                            PaymentStatusCodes.PAYMENT_180DPD],
        is_restructured=False).exclude(
        loan__application__product_line__product_line_code__in=ProductLineCodes.grab()
    ).order_by('payment_number')
    with transaction.atomic():
        for payment in payments:
            account_payment = AccountPayment.objects.filter(
                account=loan.account, id=payment.account_payment_id
            )
            account_payment.update(due_amount=F('due_amount') - payment.due_amount,
                                   principal_amount=F('principal_amount') - payment.
                                   installment_principal,
                                   interest_amount=F('interest_amount') - payment.
                                   installment_interest)
            account_payment.filter(due_amount=0).update(status_id=PaymentStatusCodes.PAID_ON_TIME)
            payment.update_safely(account_payment=None,
                                  payment_status_id=PaymentStatusCodes.PAID_ON_TIME)


def get_pin_settings() -> Tuple:
    """
        Improvement and copied from src.juloserver.juloserver.pin.services.get_global_pin_setting
    """
    tuple_of_settings = namedtuple(
        'PinSettings',
        ['max_block_number', 'max_retry_count', 'max_wait_time_mins', 'login_failure_count']
    )

    pin_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PIN_SETTING, is_active=True)

    # set as default not found pin settings
    max_wait_time_mins = 60  # default value
    max_retry_count = 3  # default value
    max_block_number = 3  # default value
    login_failure_count = {
        '1': max_wait_time_mins,
        '2': max_wait_time_mins,
        '3': max_wait_time_mins,
    }

    # Handle if pin setting is found
    if pin_setting:
        param = pin_setting.parameters
        max_wait_time_mins = param.get('max_wait_time_mins') or max_wait_time_mins
        max_retry_count = param.get('max_retry_count') or max_retry_count
        max_block_number = param.get('max_block_number') or max_block_number
        if "login_failure_count" in param:
            login_failure_count = param['login_failure_count']
        else:
            login_failure_count['1'] = max_wait_time_mins
            login_failure_count['2'] = max_wait_time_mins
            login_failure_count['3'] = max_wait_time_mins

    pin_configuration_settings = tuple_of_settings(max_block_number, max_retry_count,
                                                   max_wait_time_mins, login_failure_count)
    return pin_configuration_settings


def get_webview_url_paylater(
        relative_path, encrypted_string):
    base_url = settings.WHITELABEL_FRONTEND_BASE_URL
    url = base_url + relative_path
    final_url = url.format(
        secret_key=encrypted_string
    )
    return final_url


def check_paylater_customer_exists(
        email, phone, partner, partner_reference_id, paylater_transaction_xid, is_web=False
):
    phone_number = format_nexmo_voice_phone_number(phone)
    encrypted_string = generate_public_key_whitelabel(
        email.lower(), phone_number, partner.name, partner_reference_id, paylater_transaction_xid
    )
    possible_phone_numbers = [phone_number, format_mobile_phone(phone)]
    ALLOWED_ACCOUNT_STATUS = {
        AccountConstant.STATUS_CODE.active,
        AccountConstant.STATUS_CODE.active_in_grace,
        AccountConstant.STATUS_CODE.overlimit,
    }
    application_prefetch = Prefetch(
        'application_set',
        queryset=Application.objects.select_related('product_line').filter(
            product_line__product_line_code__in=ProductLineCodes.julo_one(),
            mobile_phone_1__in=possible_phone_numbers,
        ),
        to_attr='applications',
    )
    customer = (
        Customer.objects.filter(email=email.lower(), phone__in=possible_phone_numbers)
        .prefetch_related(application_prefetch)
        .last()
    )
    error_msg = None
    is_linked = False
    application_xid = None
    if customer:
        if not customer.applications:
            relative_path = PaylaterURLPaths.ACTIVATION_PAGE
            error_msg = "Julo Application is not available for this customer"
        elif customer.applications[0].status != ApplicationStatusCodes.LOC_APPROVED or (
                customer.applications[0].status == ApplicationStatusCodes.LOC_APPROVED
                and customer.applications[0].account and customer.applications[0].account.status_id
                not in ALLOWED_ACCOUNT_STATUS
        ):
            relative_path = PaylaterURLPaths.LOGIN_PAGE
            is_linked = True
            track_partner_session_status(partner, PaylaterUserAction.LOGIN_SCREEN,
                                         partner_reference_id, application_xid,
                                         paylater_transaction_xid,)
            if customer.applications:
                application_xid = customer.applications[0].application_xid
        elif customer.applications[0].status == ApplicationStatusCodes.LOC_APPROVED \
                and customer.applications[0].account and \
                customer.applications[0].account.status_id in ALLOWED_ACCOUNT_STATUS:
            partner_property = PartnerProperty.objects.filter(
                partner=partner,
                account=customer.applications[0].account,
                partner_reference_id=partner_reference_id,
                is_active=True,
            ).exists()
            if partner_property:
                is_linked = True
                relative_path = PaylaterURLPaths.PAYMENT_PAGE
            else:
                relative_path = PaylaterURLPaths.VERIFY_OTP
        else:
            relative_path = PaylaterURLPaths.ACTIVATION_PAGE
    else:
        relative_path = PaylaterURLPaths.ACTIVATION_PAGE
        if is_web:
            error_msg = pre_login_attempt_check(phone_number, paylater_transaction_xid)

    webview_url = get_webview_url_paylater(relative_path, encrypted_string)

    return_data = {"webview_url": webview_url, "paylater_transaction_xid": paylater_transaction_xid}
    if is_web:
        return_data['error_msg'] = error_msg
        return_data['is_linked'] = is_linked
        track_partner_session_status(partner, PaylaterUserAction.ONLY_EMAIL_AND_PHONE_MATCH,
                                     partner_reference_id, application_xid,
                                     paylater_transaction_xid,)
    else:
        if relative_path != PaylaterURLPaths.LOGIN_PAGE:
            track_partner_session_status(partner, PaylaterUserAction.CHECKOUT_INITIATED,
                                         partner_reference_id, application_xid,
                                         paylater_transaction_xid,)

    return return_data


def create_paylater_transaction_details(request):
    data = request.data
    kodepos = data.get('kodepos', None)
    kabupaten = data.get('kabupaten', None)
    provinsi = data.get('provinsi', None)
    partner_reference_id = data.get('partner_reference_id')
    bulk_create_data = []
    with transaction.atomic():
        transaction_status = {
            PaylaterTransactionStatuses.INITIATE,
            PaylaterTransactionStatuses.IN_PROGRESS,
        }
        paylater_transaction = PaylaterTransaction.objects.filter(
            paylater_transaction_status__transaction_status__in=transaction_status,
            partner_reference_id=partner_reference_id,
        ).last()
        partner = request.user.partner
        if paylater_transaction is None:
            paylater_transaction_xid = random.randint(1000000000, 9999999999)
            paylater_transaction = PaylaterTransaction.objects.create(
                partner_reference_id=partner_reference_id,
                paylater_transaction_xid=paylater_transaction_xid,
                partner=partner,
                cart_amount=0,
                transaction_amount=data['transaction_amount'],
            )
            PaylaterTransactionStatus.objects.create(
                transaction_status=PaylaterTransactionStatuses.INITIATE,
                paylater_transaction=paylater_transaction,
            )
        else:
            paylater_transaction_xid = paylater_transaction.paylater_transaction_xid
            PaylaterTransactionDetails.objects.filter(
                paylater_transaction=paylater_transaction
            ).delete()

        cart_amount = 0
        if len(data['order_details']) == 0:
            return general_error_response('order_details wajib diisi')

        for order_detail in data['order_details']:
            order_detail_keys = order_detail.keys()
            if 'products' not in order_detail_keys:
                return general_error_response(ErrorMessageConst.PRODUCT_NOT_FOUND)

            if len(order_detail['products']) == 0:
                return general_error_response(ErrorMessageConst.PRODUCT_NOT_FOUND)

            if 'merchant_name' not in order_detail_keys or not order_detail['merchant_name']:
                return general_error_response('merchant_name wajib diisi')

            for products in order_detail['products']:
                products_keys = products.keys()
                if 'product_name' not in products_keys or not products['product_name']:
                    return general_error_response('nama produk wajib diisi')

                if 'product_qty' not in products_keys or not products['product_qty']:
                    return general_error_response('qty wajib diisi')

                if not (isinstance(products['product_qty'], int)):
                    return general_error_response('qty harus nomor')

                product_qty = products['product_qty']
                if 'product_price' not in products_keys or not products['product_price']:
                    return general_error_response('price wajib diisi')

                product_price = products['product_price']
                if not (isinstance(product_price, int) or isinstance(product_price, float)):
                    return general_error_response('price harus nomor')

                cart_amount += product_price * product_qty
                bulk_create_data.append(
                    PaylaterTransactionDetails(
                        merchant_name=order_detail['merchant_name'],
                        product_name=products['product_name'],
                        product_qty=product_qty,
                        product_price=product_price,
                        paylater_transaction=paylater_transaction,
                    )
                )
        PaylaterTransactionDetails.objects.bulk_create(bulk_create_data, batch_size=20)
        paylater_transaction.cart_amount = cart_amount
        paylater_transaction.transaction_amount = data['transaction_amount']
        paylater_transaction.kodepos = kodepos
        paylater_transaction.kabupaten = kabupaten
        paylater_transaction.provinsi = provinsi
        paylater_transaction.save()
        phone_number = data.get('mobile_phone')
        email = data.get('email')

        return success_response(
            check_paylater_customer_exists(
                email, phone_number, partner, partner_reference_id, paylater_transaction_xid
            )
        )


def check_partnership_type_is_paylater(partner):
    partnership_config = PartnershipConfig.objects.filter(
        partner=partner
    ).select_related('partnership_type').last()

    if partnership_config and partnership_config.partnership_type:
        partnership_type = partnership_config.partnership_type
        if partnership_type and \
                partnership_type.partner_type_name == \
                PartnershipTypeConstant.WHITELABEL_PAYLATER:
            return True

    return False


def store_partnership_initialize_api_log(request: Request, response: Response,
                                         request_body: Dict) -> None:
    partner = request.user.partner
    customer = None
    application = None

    response_data = response.data.get('data')
    if response_data and response_data.get('application_xid'):
        application_xid = response_data.get('application_xid')
        application = Application.objects.filter(application_xid=application_xid).last()
        customer = application.customer if application else None
    elif hasattr(request.user, 'customer'):
        customer = request.user.customer
        application = Application.objects.filter(customer=customer).last()

    distributor = None
    merchant = Merchant.objects.filter(distributor__partner=partner)\
        .select_related('distributor').last()

    if merchant:
        distributor = merchant.distributor

    error_message = None
    if response.data and 'errors' in response.data:
        error_message = response.data['errors']

    partnership_api_log = PartnershipApiLog.objects.create(
        partner=partner,
        application=application,
        customer=customer,
        api_url=request.build_absolute_uri(),
        query_params=request.get_full_path(),
        api_type=request.method,
        response_json=response.data,
        http_status_code=response.status_code,
        request_body_json=request_body,
        error_message=error_message,
        distributor=distributor,
        api_from=APISourceFrom.INTERNAL
    )

    has_partner_origin_name = ('partner_origin_name' in request_body
                               and request_body.get('partner_origin_name'))
    if application or has_partner_origin_name:
        partner_origin_name = None
        if has_partner_origin_name:
            partner_origin_name = str(request_body.get('partner_origin_name'))

        email = request_body.get('email')
        phone_number = request_body.get('phone_number')

        application_xid = None
        if application:
            application_xid = application.application_xid

        is_linked = None
        if response_data:
            is_linked = response_data.get('is_linked')

        partner_origin = PartnerOrigin.objects.create(
            partnership_api_log=partnership_api_log,
            partner=partner,
            partner_origin_name=partner_origin_name,
            phone_number=phone_number,
            email=email,
            application_xid=application_xid,
            is_linked=is_linked
        )
        if application and partner_origin and partner_origin_name:
            if application.account and \
                    application.account.status_id == AccountConstant.STATUS_CODE.active:
                update_moengage_for_user_linking_status.delay(application.account.id,
                                                              partner_origin.id)


def create_log_and_return_error(
    current_attempt, pre_login_check_log, phone, paylater_transaction_xid
):
    (
        max_attempt,
        blocking_hour,
        pre_login_phone_locked_msg,
    ) = check_paylater_temporary_block_period_feature()
    blocked_until = None
    current_time = timezone.localtime(timezone.now())
    max_blocking_hour = current_time + timedelta(hours=blocking_hour)
    if current_attempt >= max_attempt:
        blocked_until = max_blocking_hour

    paylater_transaction = PaylaterTransaction.objects.filter(
        paylater_transaction_xid=paylater_transaction_xid
    ).last()
    if not pre_login_check_log:
        pre_login_check_log = PreLoginCheckPaylater.objects.create(
            phone_number=phone, paylater_transaction=paylater_transaction
        )
        PreLoginCheckPaylaterAttempt.objects.create(
            pre_login_check_paylater=pre_login_check_log,
            attempt=current_attempt,
            blocked_until=blocked_until,
        )
    else:
        pre_login_check_log.attempt = current_attempt
        pre_login_check_log.blocked_until = blocked_until
        pre_login_check_log.save()

    if blocked_until:
        return pre_login_phone_locked_msg

    if current_attempt > 1:

        return ErrorMessageConst.LOGIN_ATTEMP_FAILED_PARTNERSHIP.format(
            attempt_count=current_attempt, max_attempt=max_attempt
        )

    return ErrorMessageConst.EMAIL_OR_PHONE_NOT_FOUND


def pre_login_attempt_check(phone, paylater_transaction_xid):
    current_attempt = 1
    current_time = timezone.localtime(timezone.now())
    pre_login_check_log = (
        PreLoginCheckPaylaterAttempt.objects.filter(pre_login_check_paylater__phone_number=phone)
        .select_related('pre_login_check_paylater')
        .last()
    )
    if pre_login_check_log:
        if pre_login_check_log.blocked_until:
            if pre_login_check_log.blocked_until >= current_time:
                paylater_temporary_period = check_paylater_temporary_block_period_feature()
                return paylater_temporary_period.pre_login_phone_locked_msg
        else:
            current_attempt = pre_login_check_log.attempt + 1

    return create_log_and_return_error(
        current_attempt, pre_login_check_log, phone, paylater_transaction_xid
    )


def check_paylater_temporary_block_period_feature():
    temporary_block_period_feature_setting = FeatureSetting.objects.get_or_none(
        is_active=True,
        feature_name=FeatureNameConst.PAYLATER_PARTNER_TEMPORARY_BLOCK_PERIOD,
    )
    tuple_of_settings = namedtuple(
        'TempBlockPeriodSettings', ['max_attempt', 'blocking_hour', 'pre_login_phone_locked_msg']
    )
    max_attempt = 3
    '''blocking_hour is blocking period in hour and blocking_time is blocking period in minutes'''
    blocking_hour = 1
    blocking_time = 60
    min_or_hour_txt = 'jam'
    if temporary_block_period_feature_setting:
        max_attempt = temporary_block_period_feature_setting.parameters[
            'temporary_blocking_attempt'
        ]
        blocking_hour = temporary_block_period_feature_setting.parameters['temporary_blocking_hour']
        if blocking_hour < 1:
            blocking_time = int(blocking_time * blocking_hour)
            min_or_hour_txt = 'menit'
        else:
            blocking_time = blocking_hour

    pre_login_phone_locked_msg = (
        'Akun Kamu diblokir sementara selama {} {} '
        'karena salah memasukkan informasi. '
        'Silahkan coba masuk kembali nanti.'.format(blocking_time, min_or_hour_txt)
    )

    temp_block_period_settings = tuple_of_settings(
        max_attempt, blocking_hour, pre_login_phone_locked_msg
    )
    return temp_block_period_settings


def check_active_account_limit_balance(account: Account, amount: int) -> bool:
    """
        Check account limit when user is active account
    """
    account_limit = account.accountlimit_set.last()
    available_limit = account_limit.available_limit

    active_status = {JuloOneCodes.ACTIVE, JuloOneCodes.ACTIVE_IN_GRACE,
                     JuloOneCodes.OVERLIMIT}

    active_account = account.status.status_code in active_status

    if active_account and amount > available_limit:
        return True

    return False


def update_paylater_transaction_status(
    paylater_transaction: PaylaterTransaction, loan: Loan
) -> PaylaterTransaction:
    """
    Update paylater transaction status, and create paylater transaction loan object
    currently only used in process_create_loan()
    """
    in_progress = PaylaterTransactionStatuses.IN_PROGRESS
    initiate = PaylaterTransactionStatuses.INITIATE
    paylater_status = paylater_transaction.paylater_transaction_status

    if paylater_status.transaction_status == initiate:
        paylater_transaction.update_transaction_status(status=in_progress)

    paylater_transaction_loan = PaylaterTransactionLoan.objects.filter(
        paylater_transaction=paylater_transaction).last()
    if paylater_transaction_loan:
        paylater_transaction_loan.loan = loan
        paylater_transaction_loan.save(update_fields=['loan'])
    else:
        PaylaterTransactionLoan.objects.create(paylater_transaction=paylater_transaction, loan=loan)

    return paylater_transaction


def download_image_from_url(url: str) -> File:
    """
    For Google Drive URL, only works for sharable file
    """
    if "drive.google" in url:
        regex = "https://drive.google.com/file/d/(.*?)/(.*?)"
        file_id = re.search(regex, url)
        if not file_id:
            raise Exception("Google Drive URL is not valid: {}".format(url))
        file_id = file_id[1]
        google_base_url = "https://docs.google.com/uc?export=download"
        session = requests.Session()
        response = session.get(google_base_url, params={"id": file_id}, stream=True)
    else:
        response = requests.get(url, stream=True)

    content_type = response.headers.get("Content-Type")

    # Adding exclude application/octet-stream because
    # sometimes image generate from 3rd party like AWS use that type PARTNER-1860
    if content_type == "application/octet-stream":
        try:
            image_data = BytesIO(response.content)
            Imagealias.open(image_data)
        except OSError:
            julo_sentry_client.captureException()
            raise Exception("File is not an image: {}".format(url))

    elif "image" not in content_type:
        raise Exception("File is not an image: {}".format(url))

    fp = BytesIO()
    fp.write(response.content)
    return File(fp)


def download_image_byte_from_url(url: str) -> bytes:
    """
    For Google Drive URL, only works for sharable file
    """
    if "drive.google" in url:
        regex = "https://drive.google.com/file/d/(.*?)/(.*?)"
        file_id = re.search(regex, url)
        if not file_id:
            raise Exception("Google Drive URL is not valid: {}".format(url))
        file_id = file_id[1]
        google_base_url = "https://docs.google.com/uc?export=download"
        session = requests.Session()
        response = session.get(google_base_url, params={"id": file_id}, stream=True)
    else:
        response = requests.get(url, stream=True)

    content_type = response.headers.get("Content-Type")

    # Adding exclude application/octet-stream because
    # sometimes image generate from 3rd party like AWS use that type PARTNER-1860
    if content_type == "application/octet-stream":
        try:
            Imagealias.open(BytesIO(response.content))
        except OSError:
            julo_sentry_client.captureException()
            raise Exception("File is not an image: {}".format(url))

    elif "image" not in content_type:
        raise Exception("File is not an image: {}".format(url))

    return response.content


def get_application_details_of_paylater_customer(data):
    email = data['validated_email']
    phone = data['validated_phone']

    partnership_config = PartnershipConfig.objects.filter(
        partner__name=data['validated_partner_name'],
        partner__is_active=True
    ).select_related('partner').last()
    if not partnership_config:
        raise JuloException(ErrorMessageConst.INVALID_PARTNER)

    application_data = {
        'application_xid': None,
        'application_status': None,
        'email': email,
        'phone': phone,
    }
    is_active = partnership_config.is_active
    token = ''
    if partnership_config.partner:
        token = partnership_config.partner.token

    application_status_data = {
        'is_registered': False,
        'redirect_url': '',
        'application': application_data,
        'paylater_transaction_xid': data['validated_paylater_transaction_xid'],
        'partner_name': data['validated_partner_name'],
        'is_active': is_active,
        'token': token,
        'is_use_signature': partnership_config.is_use_signature,
        'loan_xid': ''
    }
    phone = format_mobile_phone(phone)
    application_prefetch = Prefetch(
        'application_set',
        queryset=Application.objects.
        select_related('product_line').
        filter(
            product_line__product_line_code__in=ProductLineCodes.
            julo_one(),
            mobile_phone_1=phone),
        to_attr='applications')
    customer = Customer.objects.filter(email=email.lower(),
                                       phone=phone). \
        prefetch_related(application_prefetch).last()
    application_status_data['is_registered'] = True if customer else False
    if not customer:
        raise JuloException("Email and phone number is not registered, please register first")

    if customer.applications:
        application_data['application_xid'] = customer.applications[0].application_xid
        application_data['application_status'] = customer.applications[0]. \
            application_status_id
        application_data['application_fullname'] = customer.applications[0].fullname
        loan = Loan.objects.filter(application_id2=customer.applications[0].id).last()
        if loan:
            application_status_data['loan_xid'] = loan.loan_xid
        if customer.applications[0].account:
            application_status_data['account_state'] = customer.applications[0].account.status_id

    if is_active:
        track_partner_session_status(
            partnership_config.partner,
            PaylaterUserAction.TOGGLE_SWITCHED_ON,
            data.get('validated_partner_reference_id'),
            application_data['application_xid'],
            data.get('validated_paylater_transaction_xid'),
        )
    else:
        track_partner_session_status(
            partnership_config.partner,
            PaylaterUserAction.TOGGLE_SWITCHED_OFF,
            data.get('validated_partner_reference_id'),
            application_data['application_xid'],
            data.get('validated_paylater_transaction_xid'),
        )

    return application_status_data


def get_application_details_of_vospay_customer(data):
    partner_name = data['validated_partner_name']
    partner = Partner.objects.filter(name=partner_name).last()
    if not partner:
        raise JuloException(ErrorMessageConst.INVALID_PARTNER)

    partnership_config = partner.partnership_config
    email = data['validated_email']
    phone = data['validated_phone']
    email_phone_diff = data['validated_email_phone_diff']
    possible_phone_numbers = [
        format_nexmo_voice_phone_number(phone),
        format_mobile_phone(phone)
    ]
    application_data = {
        'application_xid': None,
        'application_status': None,
        'email': None,
    }

    redirect_url = ''
    is_use_signature = False
    if partnership_config:
        is_use_signature = partnership_config.is_use_signature
        if partnership_config.redirect_url:
            redirect_url = partnership_config.redirect_url

    partner_origin_name = data.get('validated_partner_origin_name', '')
    formatted_redirect_url = urllib.parse.quote(redirect_url, safe="")
    application_status_data = {
        'is_registered': False,
        'application': application_data,
        'redirect_url': formatted_redirect_url,
        'partner_name': partner_name,
        'is_use_signature': is_use_signature,
        'partner_origin_name': partner_origin_name
    }

    customer = None
    if not email_phone_diff:
        customer = Customer.objects.filter(
            email=email.lower(), phone__in=possible_phone_numbers
        ).last()
    else:
        if email_phone_diff == "email":
            customer = Customer.objects.filter(email=email.lower()).last()
        elif email_phone_diff == "phone":
            customer = Customer.objects.filter(
                phone__in=possible_phone_numbers
            ).last()

    application_status_data['is_registered'] = True if customer else False
    if not customer:
        return application_status_data
    application = customer.application_set.filter(
        product_line__product_line_code__in=ProductLineCodes.j1(),
    ).last()
    if not application or not application.account:
        return application_status_data

    if not data['validated_email_phone_diff']:
        if phone != format_nexmo_voice_phone_number(application.mobile_phone_1):
            raise JuloException("Phone Number doesn't match the email")

    application_data['application_xid'] = application.application_xid
    application_data['application_status'] = application.application_status_id
    application_data['application_fullname'] = application.fullname
    application_data['email'] = email
    application_data['phone'] = format_mobile_phone(application.mobile_phone_1)
    application_status_data['application'] = application_data
    is_linked = application.account.partnerproperty_set.filter(
        partner__name=partner_name, is_active=True).exists()
    if formatted_redirect_url and is_linked:
        application_status_data['redirect_url'] = add_url_query_param(
            formatted_redirect_url,
            application_data['application_xid'],
            data['validated_partner_reference_id'])

    return application_status_data


def hold_loan_status_to_211(loan, signature_method):
    from juloserver.loan.tasks.sphp import upload_sphp_to_oss
    new_loan_status = LoanStatusCodes.LENDER_APPROVAL
    user = loan.customer.user
    signature_method_history_task_julo_one(loan.id, signature_method)
    loan.refresh_from_db()
    if loan.status == LoanStatusCodes.LENDER_APPROVAL:
        return new_loan_status
    update_loan_status_and_loan_history(loan.id,
                                        new_status_code=new_loan_status,
                                        change_by_id=user.id,
                                        change_reason="Digital signature succeed"
                                        )
    loan.update_safely(sphp_accepted_ts=timezone.now())
    upload_sphp_to_oss.apply_async((loan.id,), countdown=30)
    return new_loan_status


def track_partner_session_status(
        partner, status_new, partner_reference_id=None, application_xid=None,
        paylater_transaction_xid=None,
):
    if not application_xid and (not partner_reference_id and not paylater_transaction_xid):
        return False

    partnership_user_session_history_details = PartnershipUserSessionHistoryDetails.objects.filter(
        status_new=status_new,
        session__partner=partner,
        session__paylater_transaction_xid=paylater_transaction_xid,
        session__partner_reference_id=partner_reference_id
    ).select_related('session', 'session__partner').last()
    with transaction.atomic():
        if not partnership_user_session_history_details:
            partnership_user_session = PartnershipUserSession.objects.filter(
                partner=partner,
                paylater_transaction_xid=paylater_transaction_xid,
                partner_reference_id=partner_reference_id
            ).last()
            if partnership_user_session:
                old_status = partnership_user_session.status
                partnership_user_session.status = status_new
                partnership_user_session.save(update_fields=['status'])
            else:
                partnership_user_session = PartnershipUserSession.objects.create(
                    application_xid=application_xid,
                    paylater_transaction_xid=paylater_transaction_xid,
                    status=status_new,
                    partner=partner,
                    partner_reference_id=partner_reference_id
                )
                old_status = status_new
            partnership_user_session.partnership_user_session_history_details. \
                create(status_new=status_new, status_old=old_status)

    return True


def partnership_mock_get_and_save_fdc_data(fdc_inquiry_data: dict) -> bool:
    """
    this function for custom result fdc. just use in staging/UAT for testing
    this function will take out when release
    """
    fdc_inquiry = FDCInquiry.objects.filter(id=fdc_inquiry_data['id']).last()
    if not fdc_inquiry:
        logger.info(
            {
                "action": "partnership_mock_get_and_save_fdc_data",
                "message": "fdc_inquiry not found",
                "fdc_inquiry_id": fdc_inquiry_data['id'],
            }
        )
        return False

    fdc_inquiry.retry_count = 0
    fdc_inquiry.save()

    fdc_mock_feature = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.PARTNERSHIP_FDC_MOCK_RESPONSE_SET
    )
    time.sleep(fdc_mock_feature.parameters['latency'] / 1000)
    data = fdc_mock_feature.parameters['response_value']

    # This field was documented to be in the response but later on removed
    # add logic if it's passed
    reference_id = data['refferenceId'] if 'refferenceId' in data else None

    with transaction.atomic():
        fdc_inquiry = FDCInquiry.objects.select_for_update().get(id=fdc_inquiry_data['id'])
        fdc_inquiry.inquiry_reason = data['inquiryReason']
        fdc_inquiry.reference_id = reference_id
        fdc_inquiry.status = data['status']
        fdc_inquiry.inquiry_date = data['inquiryDate']
        if "Found" == data['status']:
            fdc_inquiry.inquiry_status = 'success'
        elif "Inquiry Function is Disabled" == data['status']:
            fdc_inquiry.inquiry_status = 'inquiry_disabled'
        elif "Not Found" == data['status']:
            fdc_inquiry.inquiry_status = 'success'
        fdc_inquiry.save()

        if data['pinjaman'] is None:
            return

        fdc_time_format = "%Y-%m-%d"
        for loan_data in data['pinjaman']:
            inquiry_loan_record = {
                'fdc_inquiry': fdc_inquiry,
                'dpd_max': loan_data['dpd_max'],
                'dpd_terakhir': loan_data['dpd_terakhir'],
                'id_penyelenggara': loan_data['id_penyelenggara'],
                'jenis_pengguna': loan_data['jenis_pengguna_ket'],
                'kualitas_pinjaman': loan_data['kualitas_pinjaman_ket'],
                'nama_borrower': loan_data['nama_borrower'].strip('\x00')[:100],
                'nilai_pendanaan': loan_data['nilai_pendanaan'],
                'no_identitas': loan_data['no_identitas'],
                'no_npwp': loan_data['no_npwp'],
                'sisa_pinjaman_berjalan': loan_data['sisa_pinjaman_berjalan'],
                'status_pinjaman': loan_data['status_pinjaman_ket'],
                'penyelesaian_w_oleh': loan_data['penyelesaian_w_oleh'],
                'pendanaan_syariah': loan_data['pendanaan_syariah'],
                'tipe_pinjaman': loan_data['tipe_pinjaman'],
                'sub_tipe_pinjaman': loan_data['sub_tipe_pinjaman'],
                'fdc_id': loan_data['id'],
                'reference': loan_data['reference'],
                'tgl_jatuh_tempo_pinjaman': datetime2.strptime(
                    loan_data['tgl_jatuh_tempo_pinjaman'], fdc_time_format
                ),
                'tgl_pelaporan_data': datetime2.strptime(
                    loan_data['tgl_pelaporan_data'], fdc_time_format
                ),
                'tgl_penyaluran_dana': datetime2.strptime(
                    loan_data['tgl_penyaluran_dana'], fdc_time_format
                ),
                'tgl_perjanjian_borrower': datetime2.strptime(
                    loan_data['tgl_perjanjian_borrower'], fdc_time_format
                ),
            }
            fdc_inquiry_loan = FDCInquiryLoan(**inquiry_loan_record)

            if loan_data['id_penyelenggara'] == str(1):
                fdc_inquiry_loan.is_julo_loan = True

            fdc_inquiry_loan.save()
    fdc_inquiry.refresh_from_db()
    store_initial_fdc_inquiry_loan_data(fdc_inquiry)
    return True


def get_gosel_loan_agreement_template(loan, application) -> bool:
    from juloserver.partnership.services.web_services import get_gosel_skrtp_agreement

    partner_loan_request = PartnerLoanRequest.objects.filter(loan=loan).last()
    if not partner_loan_request:
        raise JuloException('PartnerLoanRequest not found')

    product_name = partner_loan_request.partner.name
    html_template = SphpTemplate.objects.filter(product_name=product_name).last()

    if not html_template:
        raise JuloException('SphpTemplate not found')

    content_skrtp = get_gosel_skrtp_agreement(
        loan,
        application,
        partner_loan_request,
        html_template,
    )

    return content_skrtp


def get_mf_std_loan_agreement_template(loan, application) -> bool:
    from juloserver.portal.object.bulk_upload.skrtp_service.service import get_mf_std_skrtp_content
    from juloserver.merchant_financing.web_app.utils import get_application_dictionaries

    loan = Loan.objects.select_related("lender").filter(id=loan.id).last()
    partner_loan_request = loan.partnerloanrequest_set.last()
    product_lookup = loan.product
    account_limit = loan.account.accountlimit_set.last()
    application_dicts = get_application_dictionaries([partner_loan_request])

    content_skrtp = get_mf_std_skrtp_content(
        loan,
        application,
        partner_loan_request,
        product_lookup,
        application_dicts,
        account_limit,
    )

    return content_skrtp


def bypass_name_bank_validation(application: Application) -> None:
    from juloserver.disbursement.models import NameBankValidation
    from juloserver.disbursement.constants import (
        NameBankValidationVendors,
        NameBankValidationStatus,
    )

    prefix = '999'
    nik = application.customer.nik
    application_xid = application.application_xid
    name_in_bank = application.customer.fullname
    mobile_phone = application.mobile_phone_1
    bank_account_number = '{}{}{}'.format(prefix, nik, application_xid)
    with transaction.atomic():
        logger.info(
            {
                "action": "partnership_bypass_name_bank_validation",
                "application_id": application.id,
            }
        )
        name_bank_validation = NameBankValidation.objects.create(
            bank_code='BCA',
            account_number=bank_account_number,
            name_in_bank=name_in_bank,
            mobile_phone=mobile_phone,
            method=NameBankValidationVendors.DEFAULT,
            reason=NameBankValidationStatus.SUCCESS.lower(),
            validation_status=NameBankValidationStatus.SUCCESS,
        )
        application.update_safely(
            bank_name='BANK CENTRAL ASIA, Tbk (BCA)',
            bank_account_number=bank_account_number,
            name_in_bank=name_in_bank,
            name_bank_validation_id=name_bank_validation.id,
        )


def update_application_table_as_inactive_for_partnership(agent, applications):
    field_changes = []
    for application in applications:
        field_changes.append(
            ApplicationFieldChange(
                application=application,
                field_name='is_deleted',
                old_value=application.is_deleted,
                new_value=True,
                agent=agent,
            )
        )
        application.is_deleted = True

        if application.ktp:
            edited_ktp = get_deletion_nik_format(application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='ktp',
                    old_value=application.ktp,
                    new_value=edited_ktp,
                    agent=agent,
                )
            )
            application.ktp = edited_ktp

        if application.email:
            edited_email = get_deletion_email_format(application.email, application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='email',
                    old_value=application.email,
                    new_value=edited_email,
                    agent=agent,
                )
            )
            application.email = edited_email

        if application.mobile_phone_1:
            edited_phone = get_deletion_phone_format(application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='mobile_phone_1',
                    old_value=application.mobile_phone_1,
                    new_value=edited_phone,
                    agent=agent,
                )
            )
            application.mobile_phone_1 = edited_phone

        try:
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.CUSTOMER_DELETED,
                change_reason='Customer Deleted',
            )
        except Exception as e:
            logger.error(
                {
                    'action': 'update_application_table_as_inactive',
                    'message': 'cannot update application status to deleted',
                    'customer_id': application.customer.id,
                    'application_id': application.id,
                    'current_app_status': application.application_status_id,
                    'target_app_status': ApplicationStatusCodes.CUSTOMER_DELETED,
                    'error': str(e),
                },
            )

    ApplicationFieldChange.objects.bulk_create(field_changes, batch_size=30)
    bulk_update(
        applications,
        update_fields=['ktp', 'is_deleted', 'email', 'mobile_phone_1'],
        batch_size=30
    )


def update_application_reject_reason(application_id: int, reason_detail: Dict) -> None:
    partnership_application_data = PartnershipApplicationData.objects.filter(
        application_id=application_id
    ).last()
    if partnership_application_data:
        application = partnership_application_data.application
        if application.product_line_code == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT:
            if partnership_application_data.reject_reason:
                if partnership_application_data.reject_reason.get('rejected_notes', None):
                    partnership_application_data.reject_reason['rejected_notes'].append(
                        reason_detail
                    )
                else:
                    partnership_application_data.reject_reason.update(
                        {'rejected_notes': [reason_detail]}
                    )

                partnership_application_data.save(update_fields=['reject_reason'])
            else:
                partnership_application_data.update_safely(
                    reject_reason={'rejected_notes': [reason_detail]}
                )
        else:
            partnership_application_data.update_safely(reject_reason=[reason_detail])


def partnership_max_creditor_check(application: Application) -> bool:
    fdc_inquiry_data = None
    parameters = get_parameters_fs_check_other_active_platforms_using_fdc()
    if is_apply_check_other_active_platforms_using_fdc(application.id, parameters, application):
        outdated_threshold_days = parameters["fdc_data_outdated_threshold_days"]
        number_allowed_platforms = parameters["number_of_allowed_platforms"]

        partnership_customer_data = application.partnership_customer_data
        is_eligible, is_outdated = check_eligible_and_out_date_other_platforms(
            partnership_customer_data.customer_id,
            application.id,
            outdated_threshold_days,
            number_allowed_platforms,
        )
        if is_outdated:
            fdc_inquiry = FDCInquiry.objects.create(
                nik=partnership_customer_data.nik,
                customer_id=partnership_customer_data.customer_id,
                application_id=application.id,
            )
            try:
                fdc_inquiry_data = {
                    "id": fdc_inquiry.id,
                    "nik": partnership_customer_data.nik,
                    "fdc_inquiry_id": fdc_inquiry.id,
                }

                partner_fdc_mock_feature = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.PARTNERSHIP_FDC_MOCK_RESPONSE_SET,
                    is_active=True,
                ).exists()
                if partner_fdc_mock_feature:
                    partnership_mock_get_and_save_fdc_data(fdc_inquiry_data)
                else:
                    get_and_save_fdc_data(fdc_inquiry_data, 1, False)

                update_fdc_active_loan_checking(
                    partnership_customer_data.customer_id, fdc_inquiry_data
                )
                is_eligible, _ = check_eligible_and_out_date_other_platforms(
                    partnership_customer_data.customer_id,
                    application.id,
                    outdated_threshold_days,
                    number_allowed_platforms,
                )
                return is_eligible
            except FDCServerUnavailableException:
                logger.error(
                    {
                        "action": "partnership_max_creditor_check",
                        "error": "FDC server can not reach",
                        "data": fdc_inquiry_data,
                    }
                )
            except Exception as e:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()

                logger.info(
                    {
                        "action": "partnership_max_creditor_check",
                        "error": str(e),
                        "data": fdc_inquiry_data,
                    }
                )
            return False
        else:
            return is_eligible
    else:
        return True


def partnership_generate_xid(
    retry_time: int = 0,
    table_source: int = XidIdentifier.APPLICATION.value,
    method: int = PartnershipXIDGenerationMethod.DATETIME.value,
) -> Union[None, int]:
    """
    This function have retry generate as 4 times
    """
    from juloserver.partnership.utils import (
        generate_xid_from_unixtime,
        generate_xid_from_datetime,
        generate_xid_from_product_line,
    )

    if retry_time > 3:
        logger.info(
            {
                'action': 'partnership_xid_application_generated_failed',
                'retry_time': retry_time,
                'message': 'Will returning as None value',
            }
        )
        return None

    if method == PartnershipXIDGenerationMethod.UNIX_TIME.value:
        generated_xid = generate_xid_from_unixtime(table_source)
    elif method == PartnershipXIDGenerationMethod.DATETIME.value:
        generated_xid = generate_xid_from_datetime(table_source)
    elif method == PartnershipXIDGenerationMethod.PRODUCT_LINE:
        generated_xid = generate_xid_from_product_line()

    is_application_check = False
    is_loan_check = False

    if table_source == XidIdentifier.APPLICATION.value:
        is_application_check = True

        xid_existed = Application.objects.filter(application_xid=generated_xid).exists()
        if not xid_existed:
            return generated_xid

    elif table_source == XidIdentifier.LOAN.value:
        is_loan_check = True

        xid_existed = Loan.objects.filter(loan_xid=generated_xid).exists()
        if not xid_existed:
            return generated_xid

    else:
        raise ValueError("Could not find a table source currently only application / loan")

    message = 'partnership_xid_generated_failed'
    if is_application_check:
        message = 'partnership_xid_application_generated_failed'
    elif is_loan_check:
        message = 'partnership_xid_loan_generated_failed'

    logger.info(
        {
            'action': message,
            'xid': generated_xid,
            'retry_time': retry_time,
            'message': 'Will do repeat to generate xid',
        }
    )

    retry_time += 1
    return partnership_generate_xid(retry_time, method)


def get_parameters_fs_partner_other_active_platform():
    feature_setting = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.PARTNERSHIP_MAX_PLATFORM_CHECK_USING_FDC,
        is_active=True,
    ).last()
    return feature_setting.parameters if feature_setting else None


# QOALA PARTNERSHIP - Leadgen Agent Assisted 22-11-2024
def get_latest_iti_configuration_agent_assisted_partner(customer_category, partner_id):
    return (
        ITIConfiguration.objects.filter(
            is_active=True,
            customer_category=customer_category,
            parameters__agent_assisted_partner_ids__contains=[str(partner_id)],
        )
        .order_by('-iti_version')
        .values('iti_version')
        .first()
    )


# QOALA PARTNERSHIP - Leadgen Agent Assisted 22-11-2024
def get_high_score_iti_bypass_agent_assisted_partner(
    application, iti_version, inside_premium_area, customer_category, is_salaried, checking_score
):
    return ITIConfiguration.objects.filter(
        is_active=True,
        is_premium_area=inside_premium_area,
        is_salaried=is_salaried,
        customer_category=customer_category,
        iti_version=iti_version,
        min_threshold__lte=checking_score,
        max_threshold__gt=checking_score,
        min_income__lte=application.monthly_income,
        max_income__gt=application.monthly_income,
        parameters__agent_assisted_partner_ids__contains=[str(application.partner_id)],
    ).last()


# QOALA PARTNERSHIP - Leadgen Agent Assisted 22-11-2024
def is_income_in_range_agent_assisted_partner(application):
    from juloserver.apiv2.services import get_customer_category

    if not application.partner:
        return is_income_in_range(application)

    if application.partner.name != PartnerNameConstant.QOALA:
        return is_income_in_range(application)

    is_salaried = JobType.objects.get_or_none(job_type=application.job_type).is_salaried
    customer_category = get_customer_category(application)
    latest_iti_config = get_latest_iti_configuration_agent_assisted_partner(
        customer_category, application.partner_id
    )
    credit_score = CreditScore.objects.filter(application=application).last()
    return ITIConfiguration.objects.filter(
        is_active=True,
        is_salaried=is_salaried,
        is_premium_area=credit_score.inside_premium_area,
        customer_category=customer_category,
        iti_version=latest_iti_config['iti_version'],
        min_income__lte=application.monthly_income,
        max_income__gt=application.monthly_income,
        parameters__agent_assisted_partner_ids__contains=[str(application.partner_id)],
    ).exists()


def get_high_score_full_bypass_agent_assisted_partner(
    application, cm_version, inside_premium_area, customer_category, checking_score
):
    """
    QOALA PARTNERSHIP - Leadgen Agent Assisted 20-11-2024
    """
    from juloserver.apiv2.credit_matrix2 import get_salaried

    partner_id = str(application.partner_id)
    highscores = (
        HighScoreFullBypass.objects.filter(
            cm_version=cm_version,
            is_premium_area=inside_premium_area,
            is_salaried=get_salaried(application.job_type),
            customer_category=customer_category,
            threshold__lte=checking_score,
            parameters__agent_assisted_partner_ids__contains=[partner_id],
        )
        .order_by('-threshold')
        .last()
    )

    return highscores


def update_application_partner_id_by_referral_code(application: Application) -> None:
    """
    checking application.referral_code
    checking based on feature_setting and application.referral_code
    if found Update the application to relate to the partner field as the application
    is part of the leadgen partnership application.
    """
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PARTNERSHIP_LEADGEN_CONFIG_CREDIT_MATRIX,
        is_active=True,
    ).last()
    if not feature_setting:
        logger.info(
            {
                "action": "update_application_partner_id_by_referral_code",
                "application": application.id,
                "application_status": application.status,
                "message": "partnership_leadgen_config_credit_matrix is off",
            }
        )
        return

    data_config = feature_setting.parameters
    if application.referral_code:
        referral_code = str(application.referral_code).lower()
        # get config based on referral_code
        partner_name = data_config.get('referral_map', {}).get(referral_code)
        credit_matrix_config = data_config.get('partners', {}).get(partner_name)
        if credit_matrix_config and credit_matrix_config.get('is_active'):
            partner = Partner.objects.filter(name=partner_name).last()
            if not partner:
                logger.info(
                    {
                        "action": "update_application_partner_id_by_referral_code",
                        "application": application.id,
                        "application_status": application.status,
                        "message": "partner not found",
                    }
                )
                return
            logger.info(
                {
                    "action": "update_application_partner_id_by_referral_code",
                    "application": application.id,
                    "application_status": application.status,
                    "message": "Update application.partner",
                }
            )
            application.update_safely(partner=partner)
        else:
            logger.info(
                {
                    "action": "update_application_partner_id_by_referral_code",
                    "application": application.id,
                    "application_status": application.status,
                    "message": "credit_matrix_config off",
                }
            )
    return


def partnership_leadgen_check_liveness_result(
    application_id: int,
    old_status_code: str,
    change_reason: str,
):
    from juloserver.application_flow.services import check_liveness_detour_workflow_status_path

    is_pass_passive_liveness = True
    is_pass_smile_liveness = True
    passive_score_threshold = 0
    smile_score_threshold = 0
    application = Application.objects.filter(pk=application_id).last()
    if not application:
        logger.info(
            {
                'action': 'failed_partnership_check_liveness_result',
                'message': 'applicaiton not found',
                'application_id': application_id,
            }
        )
        return
    # to check liveness already manual checking from ops or not
    if check_liveness_detour_workflow_status_path(
        application,
        ApplicationStatusCodes.FORM_PARTIAL,
        status_old=old_status_code,
        change_reason=change_reason,
    ):
        logger.info(
            {
                'action': 'failed_partnership_check_liveness_result',
                'message': 'manual check liveness from ops',
                'application_id': application_id,
            }
        )
        return

    liveness_feature_settings = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.LEADGEN_LIVENESS_SETTINGS, is_active=True
    ).last()
    config_passive = None
    config_smile = None
    if liveness_feature_settings:
        config_passive = liveness_feature_settings.parameters.get(LivenessType.PASSIVE, {})
        config_smile = liveness_feature_settings.parameters.get(LivenessType.SMILE, {})
        if config_passive:
            passive_score_threshold = config_passive.get('score_threshold', 0)
        if config_smile:
            smile_score_threshold = config_smile.get('score_threshold', 0)
    else:
        process_application_status_change(
            application_id,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            change_reason='Manual image verification by ops',
        )
        logger.info(
            {
                'action': 'failed_partnership_check_liveness_result',
                'message': 'feature settings is off, move to 134',
                'application_id': application_id,
            }
        )
        return

    """ checking passive liveness """
    passive_liveness_result_data = LivenessResultsMapping.objects.filter(
        application_id=application_id,
        detection_type=LivenessType.PASSIVE,
        status=LivenessResultMappingStatus.ACTIVE,
    ).last()

    if passive_liveness_result_data:
        str_passsive_reference_id = str(passive_liveness_result_data.liveness_reference_id)
        passsive_liveness_reference_id = passive_liveness_result_data.liveness_reference_id

        passive_liveness_result = LivenessResult.objects.filter(
            reference_id=passsive_liveness_reference_id
        ).last()

        if passive_liveness_result and (passive_liveness_result.score >= passive_score_threshold):
            is_pass_passive_liveness = True
        else:
            is_pass_passive_liveness = False
            logger.info(
                {
                    'action': 'failed_partnership_check_liveness_result',
                    'message': 'LivenessResult for smile not found or below threshold',
                    'application_id': application_id,
                    'reference_id': str_passsive_reference_id,
                    'score': passive_liveness_result.score,
                }
            )
    else:
        logger.info(
            {
                'action': 'failed_partnership_check_liveness_result',
                'message': 'LivenessResultsMapping for passive not found',
                'application_id': application_id,
            }
        )
        is_pass_passive_liveness = False

    """ checking smile liveness """
    smile_liveness_result_data = LivenessResultsMapping.objects.filter(
        application_id=application_id,
        detection_type=LivenessType.SMILE,
        status=LivenessResultMappingStatus.ACTIVE,
    ).last()

    if smile_liveness_result_data:
        str_smile_reference_id = str(smile_liveness_result_data.liveness_reference_id)
        smile_liveness_reference_id = smile_liveness_result_data.liveness_reference_id

        smile_liveness_result = LivenessResult.objects.filter(
            reference_id=smile_liveness_reference_id
        ).last()
        if smile_liveness_result and (smile_liveness_result.score == smile_score_threshold):
            is_pass_smile_liveness = True
        else:
            logger.info(
                {
                    'action': 'failed_partnership_check_liveness_result',
                    'message': 'LivenessResult for smile not found or below threshold',
                    'application_id': application_id,
                    'reference_id': str_smile_reference_id,
                    'score': passive_liveness_result.score,
                }
            )
            is_pass_smile_liveness = False
    else:
        is_pass_smile_liveness = False

    """
        if have is_pass_passive_liveness or is_pass_smile_liveness not pass
        we will move 134 will manual verification by ops
    """
    if not is_pass_passive_liveness or not is_pass_smile_liveness:
        logger.info(
            {
                'action': 'failed_partnership_check_liveness_result',
                'message': 'manual check liveness from ops, move to 134',
                'application_id': application_id,
                'is_pass_passive_liveness': is_pass_passive_liveness,
                'is_pass_smile_liveness': is_pass_smile_liveness,
            }
        )
        process_application_status_change(
            application_id,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            change_reason='Manual image verification by ops',
        )
        return
    else:
        logger.info(
            {
                'action': 'partnership_check_liveness_result',
                'message': 'pass liveness check',
                'application_id': application_id,
            }
        )
        return


def partnership_get_image_liveness_result(application_id: int):
    """checking passive liveness"""
    list_image = []
    passive_liveness_result_mapping = LivenessResultsMapping.objects.filter(
        application_id=application_id,
        detection_type=LivenessType.PASSIVE,
        status=LivenessResultMappingStatus.ACTIVE,
    ).last()
    if passive_liveness_result_mapping:
        passive_liveness_result = LivenessResult.objects.filter(
            reference_id=passive_liveness_result_mapping.liveness_reference_id
        ).last()
        image_id = passive_liveness_result.image_ids.get('neutral')
        get_image = LivenessImage.objects.filter(id=image_id).last()
        list_image.append(get_image)

    """ checking smile liveness """
    smile_liveness_result_mapping = LivenessResultsMapping.objects.filter(
        application_id=application_id,
        detection_type=LivenessType.SMILE,
        status=LivenessResultMappingStatus.ACTIVE,
    ).last()
    if smile_liveness_result_mapping:
        smile_liveness_result = LivenessResult.objects.filter(
            reference_id=smile_liveness_result_mapping.liveness_reference_id
        ).last()
        image_ids = {
            smile_liveness_result.image_ids.get('neutral'),
            smile_liveness_result.image_ids.get('smile'),
        }
        liveness_images = LivenessImage.objects.filter(id__in=image_ids)
        for image in liveness_images:
            list_image.append(image)
    return list_image


def is_partnership_lender_balance_sufficient(loan: Loan, notify_to_slack: bool = False):
    lender_balance = LenderBalanceCurrent.objects.get_or_none(lender_id=loan.lender_id)
    if lender_balance and lender_balance.available_balance < loan.loan_amount:
        if notify_to_slack:
            notify_partnership_insufficient_lender_balance(loan.id, loan.lender_id)
        return False

    return True
