import re
import logging
from collections import namedtuple
from datetime import datetime

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection, connections
from django.utils import timezone
from rest_framework import status

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountProperty, AccountLimit, AccountLimitHistory
from juloserver.account.services.credit_limit import (
    get_salaried,
    get_is_proven,
    is_inside_premium_area,
    get_proven_threshold,
    get_voice_recording,
    store_account_property_history,
)
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.dana.constants import (
    INDONESIA,
    BindingResponseCode,
    BindingRejectCode,
    DANA_PAYMENT_METHOD_CODE,
    DANA_PAYMENT_METHOD_NAME,
    OnboardingApproveReason,
    OnboardingRejectReason,
    XIDGenerationMethod,
    DANA_SUFFIX_EMAIL,
    DANA_CASH_LOAN_SUFFIX_EMAIL,
    DanaProductType,
    DanaFDCResultStatus,
    MaxCreditorStatus,
)
from juloserver.dana.models import DanaCustomerData, DanaApplicationReference, DanaFDCResult
from juloserver.dana.utils import (
    set_redis_key,
    create_dana_nik,
    create_dana_phone,
    create_dana_email,
    create_temporary_user_nik,
    cursor_dictfetchall,
)
from juloserver.julo.constants import WorkflowConst, FeatureNameConst, XidIdentifier
from juloserver.julo.models import (
    Application,
    Customer,
    PaymentMethod,
    Workflow,
    ProductLine,
    BlacklistCustomer,
    MasterAgreementTemplate,
    FeatureSetting,
    ApplicationNote,
    Loan,
    CreditScore,
    ApplicationHistory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import (
    trim_name,
    execute_after_transaction_safely,
    format_mobile_phone,
    format_nexmo_voice_phone_number,
)
from juloserver.julovers.models import Julovers
from juloserver.partnership.constants import (
    PartnershipImageProductType,
    PartnershipImageType,
    PartnershipFlag,
)
from juloserver.partnership.models import PartnershipApplicationFlag, PartnershipFlowFlag
from juloserver.dana.utils import (
    generate_xid_from_unixtime,
    generate_xid_from_datetime,
    generate_xid_from_product_line,
)
from juloserver.pusdafil.constants import (
    job__job_industries,
    gender,
)
from juloserver.loan.services.loan_related import (
    check_eligible_and_out_date_other_platforms,
    get_parameters_fs_check_other_active_platforms_using_fdc,
    is_apply_check_other_active_platforms_using_fdc,
)

from typing import Tuple, Dict, Union


logger = logging.getLogger(__name__)


def store_account_property_dana(application: Application, set_limit: int) -> None:
    is_proven = get_is_proven()

    input_params = dict(
        account=application.account,
        pgood=0.0,
        p0=0.0,
        is_salaried=get_salaried(application.job_type),
        is_proven=is_proven,
        is_premium_area=is_inside_premium_area(application),
        proven_threshold=get_proven_threshold(set_limit),
        voice_recording=get_voice_recording(is_proven),
        concurrency=True,
    )

    account_property = AccountProperty.objects.create(**input_params)

    # create history
    store_account_property_history(input_params, account_property)


def create_dana_user(dana_customer_data: DanaCustomerData, partner_reference_number: str) -> Tuple:
    """
    This function create:
    - User
    - Customer
    - Application
    - Update Dana Customer Data
    - Upload Image Data
    - Dana reference no
    """

    from juloserver.dana.tasks import upload_dana_customer_image

    # temporary nik user
    dana_mobile_number = dana_customer_data.mobile_number
    dana_full_name = dana_customer_data.full_name
    dob = dana_customer_data.dob

    if dana_customer_data.is_cash_loan:
        product_code = ProductLineCodes.DANA_CASH_LOAN
        suffix_email = DANA_CASH_LOAN_SUFFIX_EMAIL
        product_line = ProductLineCodes.DANA_CASH_LOAN
    else:
        product_code = ProductLineCodes.DANA
        suffix_email = DANA_SUFFIX_EMAIL
        product_line = ProductLineCodes.DANA

    temp_nik = create_temporary_user_nik(dana_customer_data.nik, product_code)

    user_email = create_dana_email(dana_full_name, dana_mobile_number, suffix_email)
    user_phone = create_dana_phone(dana_mobile_number, product_code)

    user = User(username=temp_nik, email=user_email)
    user.save()

    customer = Customer.objects.create(
        user=user,
        fullname=dana_full_name,
        email=user_email,
        phone=user_phone,
        appsflyer_device_id=None,
        advertising_id=None,
        mother_maiden_name=None,
        dob=dob,
    )

    workflow = Workflow.objects.get(name=WorkflowConst.DANA)

    dana_product_line = ProductLine.objects.get(pk=product_line)
    address_street_num = dana_customer_data.address
    if len(dana_customer_data.address) > 100:
        address_street_num = dana_customer_data.address[:100]

    application_xid_generated = generate_dana_application_xid()
    partner = dana_customer_data.partner
    application = Application.objects.create(
        customer=customer,
        email=user_email,
        fullname=dana_full_name,
        partner=partner,
        mobile_phone_1=user_phone,
        workflow=workflow,
        product_line=dana_product_line,
        name_bank_validation_id=settings.DANA_NAME_BANK_VALIDATION_ID,
        dob=dob,
        payday=1,  # hardcode payday
        address_street_num=address_street_num,
        application_xid=application_xid_generated,
    )

    # Update monthly income based on dana income range mapping
    monthly_income_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_MONTHLY_INCOME,
        is_active=True,
    ).last()
    dana_income_range = dana_customer_data.income
    if (
        monthly_income_feature_setting
        and monthly_income_feature_setting.parameters
        and dana_income_range
    ):
        income_range = dana_income_range.replace(" ", "").lower()
        monthly_income = monthly_income_feature_setting.parameters.get(income_range)
        if monthly_income:
            application.update_safely(monthly_income=monthly_income)
            customer.update_safely(monthly_income=monthly_income)

    # User Dana NIK
    user_nik = create_dana_nik(application.id, product_code)

    # Upload user, customer, application nik
    user.username = user_nik
    user.save(update_fields=['username'])

    customer.nik = user_nik
    customer.save(update_fields=['nik'])

    application.ktp = user_nik
    application.save(update_fields=['ktp'])

    application_id = application.id
    dana_application_reference = DanaApplicationReference.objects.create(
        application_id=application_id,
        partner_reference_no=partner_reference_number,
    )

    # Set application STATUS to 100
    application.change_status(ApplicationStatusCodes.FORM_CREATED)
    application.save(update_fields=['application_status_id'])

    # Update dana customer data
    dana_customer_data.customer = customer
    dana_customer_data.application = application
    dana_customer_data.save(update_fields=['customer', 'application'])

    # Create Payment Method
    PaymentMethod.objects.create(
        payment_method_code=DANA_PAYMENT_METHOD_CODE,
        payment_method_name=DANA_PAYMENT_METHOD_NAME,
        customer=customer,
    )

    # Upload Image KTP and Selfie
    execute_after_transaction_safely(
        lambda: upload_dana_customer_image.delay(
            image_url=dana_customer_data.selfie_image_url,
            image_type=PartnershipImageType.SELFIE,
            product_type=PartnershipImageProductType.DANA,
            application_id=application_id,
        )
    )

    execute_after_transaction_safely(
        lambda: upload_dana_customer_image.delay(
            image_url=dana_customer_data.ktp_image_url,
            image_type=PartnershipImageType.KTP_SELF,
            product_type=PartnershipImageProductType.DANA,
            application_id=application_id,
        )
    )

    dana_data = namedtuple('DanaData', ['application_id', 'dana_application_reference'])
    dana_application_data = dana_data(application_id, dana_application_reference)

    return dana_application_data


def check_fullname_with_DTTOT(fullname: str) -> bool:
    stripped_name = trim_name(fullname)
    black_list_customer = BlacklistCustomer.objects.filter(
        fullname_trim__iexact=stripped_name, citizenship__icontains=INDONESIA
    ).exists()

    if black_list_customer:
        # stored in redis if name is blacklisted, and expiry in 6 hour
        blacklist_key = '%s_%s' % ("blacklist_user_key:", stripped_name)
        set_redis_key(blacklist_key, 1, 21_600)

    return black_list_customer


def check_customer_fraud(dana_customer_data: DanaCustomerData, application_id: int) -> bool:
    """
    - NIK / Phone application exists
    - Check all data if fraud status (133) in application history, not current application and
    - If account status is fraud 440,441 also rejected
    - Check if spouse_mobile_phone exists in application with dana phone and have status 133 reject
    - Check if kin_mobile_phone exists in application with dana phone and have status 133 reject
    - Check if mobile_phone_2 exists in application with dana phone and have status 133 reject
    """
    dana_phone_number = dana_customer_data.mobile_number
    nik = dana_customer_data.nik

    fraud_status = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
    fraud_account_status = {
        AccountConstant.STATUS_CODE.fraud_reported,
        AccountConstant.STATUS_CODE.application_or_friendly_fraud,
    }

    nik_applications = Application.objects.filter(ktp=nik).exclude(id=application_id)
    if nik_applications:
        """
        Application checking based nik with:
        - Application status 133 fraud
        - Account Status = 440,441
        """
        if nik_applications.filter(applicationhistory__status_new=fraud_status).exists():
            # stored in redis if nik is found as fraud, and expiry in 6 hour
            fraud_nik_key = '%s_%s' % ("fraud_nik_key:", nik)
            set_redis_key(fraud_nik_key, 1, 21_600)

            return True

        elif nik_applications.filter(account__status_id__in=fraud_account_status).exists():
            # stored in redis if nik is found as fraud, and expiry in 6 hour
            fraud_nik_key = '%s_%s' % ("fraud_nik_key:", nik)
            set_redis_key(fraud_nik_key, 1, 21_600)

            return True

    phone_applications = Application.objects.filter(mobile_phone_1=dana_phone_number).exclude(
        id=application_id
    )

    if phone_applications:
        """
        Application checking based phone with:
        - Application status 133 fraud
        - Account Status = 440,441
        """
        if phone_applications.filter(applicationhistory__status_new=fraud_status).exists():
            # stored in redis if phone number is found as fraud, and expiry in 6 hour
            fraud_phone_key = '%s_%s' % ("fraud_phone_key:", dana_phone_number)
            set_redis_key(fraud_phone_key, 1, 21_600)

            return True

        elif phone_applications.filter(account__status_id__in=fraud_account_status).exists():

            # stored in redis if phone number is found as fraud, and expiry in 6 hour
            fraud_phone_key = '%s_%s' % ("fraud_phone_key:", dana_phone_number)
            set_redis_key(fraud_phone_key, 1, 21_600)

            return True

    spouse_phone_number_application_fraud = (
        Application.objects.filter(
            spouse_mobile_phone=dana_phone_number,
            applicationhistory__status_new=fraud_status,
        )
        .exclude(id=application_id)
        .exists()
    )

    if spouse_phone_number_application_fraud:

        # stored in redis if phone number is found as fraud, and expiry in 6 hour
        fraud_phone_key = '%s_%s' % ("fraud_phone_key:", dana_phone_number)
        set_redis_key(fraud_phone_key, 1, 21_600)

        return True

    kin_phone_number_application_fraud = (
        Application.objects.filter(
            kin_mobile_phone=dana_phone_number,
            applicationhistory__status_new=fraud_status,
        )
        .exclude(id=application_id)
        .exists()
    )

    if kin_phone_number_application_fraud:

        # stored in redis if phone number is found as fraud, and expiry in 6 hour
        fraud_phone_key = '%s_%s' % ("fraud_phone_key:", dana_phone_number)
        set_redis_key(fraud_phone_key, 1, 21_600)

        return True

    mobile_phone_2_application_fraud = (
        Application.objects.filter(
            mobile_phone_2=dana_phone_number,
            applicationhistory__status_new=fraud_status,
        )
        .exclude(id=application_id)
        .exists()
    )

    if mobile_phone_2_application_fraud:

        # stored in redis if phone number is found as fraud, and expiry in 6 hour
        fraud_phone_key = '%s_%s' % ("fraud_phone_key:", dana_phone_number)
        set_redis_key(fraud_phone_key, 1, 21_600)

        return True

    return False


def check_customer_delinquent(dana_customer_data: DanaCustomerData, application_id: int) -> bool:
    dana_phone_number = dana_customer_data.mobile_number
    nik = dana_customer_data.nik

    delinquent_account_status = {
        AccountConstant.STATUS_CODE.active_in_grace,
        AccountConstant.STATUS_CODE.suspended,
    }

    if (
        Application.objects.filter(ktp=nik, account__status_id__in=delinquent_account_status)
        .exclude(id=application_id)
        .exists()
    ):
        return True
    elif (
        Application.objects.filter(
            mobile_phone_1=dana_phone_number, account__status_id__in=delinquent_account_status
        )
        .exclude(id=application_id)
        .exists()
    ):
        return True

    has_existing_user_app_delinquent = (
        DanaCustomerData.objects.filter(
            dana_customer_identifier=dana_customer_data.dana_customer_identifier,
            account__status_id__in=delinquent_account_status,
        )
        .exclude(id=dana_customer_data.id)
        .last()
    )

    # Flagged existing user delinquent on different product
    if has_existing_user_app_delinquent:
        if has_existing_user_app_delinquent.is_cash_loan:
            note = "User has delinquent account on product Dana Cash Loan, app_id={}".format(
                has_existing_user_app_delinquent.application_id
            )
        else:
            note = "User has delinquent account on product Dana Cicil, app_id={}".format(
                has_existing_user_app_delinquent.application_id
            )

        ApplicationNote.objects.create(application_id=application_id, note_text=note)

    return False


def validate_blacklist_check(
    dana_customer_data: DanaCustomerData,
    application_id: int,
    dana_application_reference: DanaApplicationReference,
) -> Union[Dict, None]:

    is_blacklisted = check_fullname_with_DTTOT(dana_customer_data.full_name)
    if is_blacklisted:
        process_application_status_change(
            application_id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason=OnboardingRejectReason.BLACKLISTED,
        )

        data = {
            'responseCode': BindingResponseCode.BAD_REQUEST.code,
            'responseMessage': BindingResponseCode.BAD_REQUEST.message,
            'accountId': str(dana_customer_data.customer.customer_xid),
            'partnerReferenceNo': dana_application_reference.partner_reference_no,
            'referenceNo': str(dana_application_reference.reference_no),
            'additionalInfo': {
                'rejectCode': BindingRejectCode.BLACKLISTED_CUSTOMER.code,
                'rejectReason': BindingRejectCode.BLACKLISTED_CUSTOMER.reason,
            },
        }

        return data

    return None


def validate_fraud_check(
    dana_customer_data: DanaCustomerData,
    application_id: int,
    dana_application_reference: DanaApplicationReference,
) -> Union[Dict, None]:

    is_fraud_user = check_customer_fraud(dana_customer_data, application_id)
    if is_fraud_user:
        process_application_status_change(
            application_id,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            change_reason=OnboardingRejectReason.FRAUD,
        )

        data = {
            'responseCode': BindingResponseCode.BAD_REQUEST.code,
            'responseMessage': BindingResponseCode.BAD_REQUEST.message,
            'accountId': str(dana_customer_data.customer.customer_xid),
            'partnerReferenceNo': dana_application_reference.partner_reference_no,
            'referenceNo': str(dana_application_reference.reference_no),
            'additionalInfo': {
                'rejectCode': BindingRejectCode.FRAUD_CUSTOMER.code,
                'rejectReason': BindingRejectCode.FRAUD_CUSTOMER.reason,
            },
        }

        return data

    return None


def validate_delinquent_check(
    dana_customer_data: DanaCustomerData,
    application_id: int,
    dana_application_reference: DanaApplicationReference,
) -> Union[Dict, None]:

    is_delinquent = check_customer_delinquent(dana_customer_data, application_id)
    if is_delinquent:
        process_application_status_change(
            application_id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason=OnboardingRejectReason.DELINQUENT,
        )

        data = {
            'responseCode': BindingResponseCode.BAD_REQUEST.code,
            'responseMessage': BindingResponseCode.BAD_REQUEST.message,
            'accountId': str(dana_customer_data.customer.customer_xid),
            'partnerReferenceNo': dana_application_reference.partner_reference_no,
            'referenceNo': str(dana_application_reference.reference_no),
            'additionalInfo': {
                'rejectCode': BindingRejectCode.DELINQUENT_CUSTOMER.code,
                'rejectReason': BindingRejectCode.DELINQUENT_CUSTOMER.reason,
            },
        }

        return data

    return None


def reject_customer_existing_phone_number_with_different_nik(
    application_id: int,
    dana_application_reference: DanaApplicationReference,
    dana_customer_data: DanaCustomerData,
) -> Dict:
    process_application_status_change(
        application_id,
        ApplicationStatusCodes.APPLICATION_DENIED,
        change_reason=OnboardingRejectReason.EXISTING_PHONE_DIFFERENT_NIK,
    )

    data = {
        'responseCode': BindingResponseCode.BAD_REQUEST.code,
        'responseMessage': BindingResponseCode.BAD_REQUEST.message,
        'accountId': str(dana_customer_data.customer.customer_xid),
        'partnerReferenceNo': dana_application_reference.partner_reference_no,
        'referenceNo': str(dana_application_reference.reference_no),
        'additionalInfo': {
            'rejectCode': BindingRejectCode.EXISTING_USER_INVALID_NIK.code,
            'rejectReason': BindingRejectCode.EXISTING_USER_INVALID_NIK.reason,
        },
    }

    return data


def process_valid_application(application_id: int) -> None:
    process_application_status_change(
        application_id,
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        change_reason='change status by API',
    )


def dana_master_agreement_template(application: Application) -> str:
    """
    This function will be return a template master agreement Dana
    """
    application_id = application.id
    ma_template = MasterAgreementTemplate.objects.filter(
        product_name=PartnerNameConstant.DANA, is_active=True
    ).last()

    if not ma_template:
        logger.error(
            {
                'action_view': 'Master Agreement DANA - get_master_agreement_template',
                'data': {},
                'errors': 'Master Agreement Template tidak ditemukan application_id: {}'.format(
                    application_id
                ),
            }
        )
        return False

    template = ma_template.parameters
    if len(template) == 0:
        logger.error(
            {
                'action_view': 'Master Agreement DANA - get_master_agreement_template',
                'data': {},
                'errors': 'Body content tidak ada application_id: {}'.format(application_id),
            }
        )
        return False

    customer = application.customer
    if not customer:
        logger.error(
            {
                'action_view': 'Master Agreement DANA - master_agreement_content',
                'data': {},
                'errors': 'Customer tidak ditemukan application_id: {}'.format(application_id),
            }
        )
        return False

    account = customer.account
    if not account:
        logger.error(
            {
                'action_view': 'Master Agreement DANA - master_agreement_content',
                'data': {},
                'errors': 'Customer tidak ditemukan application_id: {}'.format(application_id),
            }
        )
        return False

    first_credit_limit = account.accountlimit_set.first().set_limit
    if not first_credit_limit:
        logger.error(
            {
                'action_view': 'Master Agreement DANA - master_agreement_content',
                'data': {},
                'errors': 'First Credit Limit tidak ditemukan application_id: {}'.format(
                    application_id
                ),
            }
        )
        return False

    customer_name = customer.fullname
    today = datetime.now()
    hash_digi_sign = "PPFP-" + str(application.application_xid)
    dob = application.dob.strftime("%d %B %Y") if application.dob else "-"
    signature = (
        '<table border="0" cellpadding="1" cellspacing="1" style="border:none;">'
        '<tbody><tr><td><p><strong>PT. JULO Teknologi Finansial</strong><br>'
        '(dalam kedudukan selaku kuasa Pemberi Dana)<br>'
        '<cite><tt>Adrianus Hitijahubessy</tt></cite></span></p>'
        'Jabatan: Direktur</p></td>'
        '<td><p style="text-align:right">'
        'Jakarta, ' + today.strftime("%d %B %Y") + '</p>'
        '<p style="text-align:right">Penerima&nbsp;Dana,</p>'
        '<p style="text-align:right"><span style="font-family:Allura">'
        '<cite><tt>' + customer_name + '</tt></cite></span></p>'
        '<p style="text-align:right">' + customer_name + '</p></td>'
        '</tr></tbody></table>'
    )

    ma_content = template.format(
        hash_digi_sign=hash_digi_sign,
        date_today=today.strftime("%d %B %Y, %H:%M:%S"),
        customer_name=customer_name,
        dob=dob,
        customer_nik=application.ktp,
        customer_phone=application.mobile_phone_1,
        full_address=application.full_address if application.full_address else "-",
        first_credit_limit=first_credit_limit,
        link_history_transaction=settings.BASE_URL + "/account/v1/account/account_payment",
        tnc_link="https://www.julo.co.id/privacy-policy",
        signature=signature,
    )

    return ma_content


def create_reapply_data(
    dana_customer_data: DanaCustomerData, partner_reference_number: str
) -> Tuple:
    """
    This function create:
    - Update customer
    - Application
    - Update Dana Customer Data
    - Upload Image Data
    - Dana reference no
    """
    from juloserver.dana.tasks import upload_dana_customer_image

    dob = dana_customer_data.dob
    dana_mobile_number = dana_customer_data.mobile_number
    dana_full_name = dana_customer_data.full_name

    if dana_customer_data.is_cash_loan:
        product_code = ProductLineCodes.DANA_CASH_LOAN
        suffix_email = DANA_CASH_LOAN_SUFFIX_EMAIL
        product_line = ProductLineCodes.DANA_CASH_LOAN
    else:
        product_code = ProductLineCodes.DANA
        suffix_email = DANA_SUFFIX_EMAIL
        product_line = ProductLineCodes.DANA

    user_email = create_dana_email(dana_full_name, dana_mobile_number, suffix_email)
    user_phone = create_dana_phone(dana_mobile_number, product_code)

    customer = dana_customer_data.customer
    workflow = Workflow.objects.get(name=WorkflowConst.DANA)

    dana_product_line = ProductLine.objects.get(pk=product_line)

    address_street_num = dana_customer_data.address
    if len(dana_customer_data.address) > 100:
        address_street_num = dana_customer_data.address[:100]

    application_xid_generated = generate_dana_application_xid()
    partner = dana_customer_data.partner
    application = Application.objects.create(
        customer=customer,
        email=user_email,
        fullname=dana_full_name,
        partner=partner,
        mobile_phone_1=user_phone,
        workflow=workflow,
        product_line=dana_product_line,
        name_bank_validation_id=settings.DANA_NAME_BANK_VALIDATION_ID,
        dob=dob,
        payday=1,  # hardcode payday
        address_street_num=address_street_num,
        application_xid=application_xid_generated,
    )

    # User Dana NIK
    user_nik = create_dana_nik(application.id, product_code)

    customer.nik = user_nik
    customer.fullname = dana_full_name
    customer.email = user_email
    customer.phone = user_phone
    customer.save(update_fields=['nik', 'fullname', 'email', 'phone'])

    application.ktp = user_nik
    application.save(update_fields=['ktp'])

    application_id = application.id
    dana_application_reference = DanaApplicationReference.objects.create(
        application_id=application_id,
        partner_reference_no=partner_reference_number,
    )

    # Set application STATUS to 100
    application.change_status(ApplicationStatusCodes.FORM_CREATED)
    application.save(update_fields=['application_status_id'])

    # Update dana customer data
    dana_customer_data.application = application
    dana_customer_data.save(update_fields=['application'])

    # Upload Image KTP and Selfie
    execute_after_transaction_safely(
        lambda: upload_dana_customer_image.delay(
            image_url=dana_customer_data.selfie_image_url,
            image_type=PartnershipImageType.SELFIE,
            product_type=PartnershipImageProductType.DANA,
            application_id=application_id,
        )
    )

    execute_after_transaction_safely(
        lambda: upload_dana_customer_image.delay(
            image_url=dana_customer_data.ktp_image_url,
            image_type=PartnershipImageType.KTP_SELF,
            product_type=PartnershipImageProductType.DANA,
            application_id=application_id,
        )
    )

    dana_data = namedtuple('DanaData', ['application_id', 'dana_application_reference'])
    dana_application_data = dana_data(application_id, dana_application_reference)
    return dana_application_data


def process_application_to_105(application_id: int) -> None:
    process_application_status_change(
        application_id,
        ApplicationStatusCodes.FORM_PARTIAL,
        change_reason='customer_triggered',
    )


def is_whitelisted_user(dana_customer_id: str) -> bool:
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_WHITELIST_USERS,
    ).first()

    user_whitelisted = (
        feature_setting
        and feature_setting.is_active
        and str(dana_customer_id) in feature_setting.parameters['dana_customer_identifiers']
    )

    return user_whitelisted


def generate_dana_application_xid(
    retry_time: int = 0, method: int = XIDGenerationMethod.DATETIME.value
) -> Union[None, int]:
    """
    This function have retry generate as 4 times
    """

    if retry_time > 3:
        logger.info(
            {
                'action': 'dana_xid_application_generated_failed',
                'retry_time': retry_time,
                'message': 'Will returning as None value',
            }
        )
        return None

    if method == XIDGenerationMethod.UNIX_TIME.value:
        generated_application_xid = generate_xid_from_unixtime(XidIdentifier.APPLICATION.value)
    elif method == XIDGenerationMethod.DATETIME.value:
        generated_application_xid = generate_xid_from_datetime(XidIdentifier.APPLICATION.value)
    elif method == XIDGenerationMethod.PRODUCT_LINE:
        generated_application_xid = generate_xid_from_product_line()

    xid_existed = Application.objects.filter(application_xid=generated_application_xid).exists()
    if not xid_existed:
        return generated_application_xid

    logger.info(
        {
            'action': 'dana_xid_application_generated_failed',
            'xid': generated_application_xid,
            'retry_time': retry_time,
            'message': 'Will do repeat to generate xid',
        }
    )

    retry_time += 1
    return generate_dana_application_xid(retry_time, method)


def update_customer_limit(dana_customer_id: str, new_limit: float, lender_product_id: str) -> None:
    account_limit = (
        AccountLimit.objects.filter(
            account__dana_customer_data__dana_customer_identifier=dana_customer_id,
            account__dana_customer_data__lender_product_id=lender_product_id,
        )
        .select_related(
            'account',
            'account__dana_customer_data',
            'account__dana_customer_data__customer__customerlimit',
        )
        .first()
    )

    old_available_limit = account_limit.available_limit
    old_set_limit = account_limit.set_limit
    old_max_limit = account_limit.max_limit

    if (new_limit - account_limit.used_limit) < 0:
        account_limit.available_limit = 0
    else:
        account_limit.available_limit = new_limit - account_limit.used_limit

    account_limit.set_limit = new_limit
    account_limit.max_limit = new_limit
    account_limit.save()

    available_account_limit_history = AccountLimitHistory(
        account_limit=account_limit,
        field_name='available_limit',
        value_old=str(old_available_limit),
        value_new=str(account_limit.available_limit),
    )

    set_limit_account_limit_history = AccountLimitHistory(
        account_limit=account_limit,
        field_name='set_limit',
        value_old=str(old_set_limit),
        value_new=str(account_limit.set_limit),
    )

    max_limit_account_limit_history = AccountLimitHistory(
        account_limit=account_limit,
        field_name='max_limit',
        value_old=str(old_max_limit),
        value_new=str(account_limit.max_limit),
    )

    AccountLimitHistory.objects.bulk_create(
        [
            available_account_limit_history,
            set_limit_account_limit_history,
            max_limit_account_limit_history,
        ]
    )


def update_dana_fdc_result(
    dana_customer_identifier: str,
    customer_id: int,
    dana_fdc_result: DanaFDCResult,
    partner_id: int,
) -> bool:
    """
    After Hit FDC at 105, we Analyze FDC status
    of customers and update the result
    on table ops.dana_fdc_result.
    The Query Create By Data Analys
    """
    results = None
    base_query = []
    try:
        config_data = (
            PartnershipFlowFlag.objects.filter(
                partner_id=partner_id, name=PartnershipFlag.DANA_FDC_LIMIT_APPLICATION_HANDLER
            )
            .values_list('configs', flat=True)
            .last()
        )
        application_datas = []
        if config_data and config_data.get('limit_application'):
            limit_application = config_data.get('limit_application')
            application_raw_query = """
            select application_id, cdate, product_line_code from application where customer_id = %s
            order by cdate desc limit %s
            """
            with connection.cursor() as cursor:
                cursor.execute(application_raw_query, [customer_id, limit_application])
                application_datas = cursor.fetchall()
        else:
            application_raw_query = """
            select application_id, cdate, product_line_code from application where customer_id = %s
            """
            with connection.cursor() as cursor:
                cursor.execute(application_raw_query, [customer_id])
                application_datas = cursor.fetchall()

        application_id_list = []
        application_cdate_list = []
        product_line_code_list = []
        for app_data in application_datas:
            application_id_list.append(app_data[0])
            application_cdate_list.append(app_data[1])
            product_line_code_list.append(app_data[2])

        base_raw_query = """
        select
            fi.customer_id,
            fi.application_id ,
            fil.fdc_inquiry_id,
            fil.cdate,
            date(a.cdate) application_date,
            fil.status_pinjaman,
            date(inquiry_date) inquiry_date,
            fil.tgl_penyaluran_dana,
            fil.tgl_jatuh_tempo_pinjaman,
            fil.dpd_terakhir,
            fil.dpd_max,
            dense_rank() over(partition by fi.customer_id order by inquiry_date desc) rn
        from
            ops.fdc_inquiry fi
        join
            ops.fdc_inquiry_loan fil on fil.fdc_inquiry_id = fi.fdc_inquiry_id
        left join LATERAL (
            SELECT * FROM UNNEST(%s) as t(application_id), UNNEST(%s) as f(cdate),
            UNNEST(%s) as g(product_line_code)
        ) as a
        ON fi.application_id = a.application_id

        where
            fi.customer_id = %s
            and
            date(fil.cdate)>= '2021-09-01'
            and
            date(a.cdate) - date(inquiry_date) between 0 and 730
            and
            date(a.cdate) - tgl_penyaluran_dana between 0 and 730
            and
            lower(fi.status) = 'found'
            and
            fi.inquiry_status in ('success','pending')
            and
            product_line_code in (700,701)
        """

        with connections['bureau_db'].cursor() as cursor:
            cursor.execute(
                base_raw_query,
                [application_id_list, application_cdate_list, product_line_code_list, customer_id],
            )
            base_query = cursor_dictfetchall(cursor)

        # Check if the fdc_inquiry not found: Approve6
        if not base_query:
            dana_fdc_result.update_safely(fdc_status='Approve6')
            return True

        base_values = ", ".join(
            ["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(base_query)
        )
        formatted_base_data = []
        for data in base_query:
            formatted_data = (
                data['customer_id'],
                data['application_id'],
                data['fdc_inquiry_id'],
                data['cdate'].strftime('%Y-%m-%d %H:%M:%S.%f'),
                data['application_date'],
                data['status_pinjaman'],
                data['inquiry_date'],
                data['tgl_penyaluran_dana'],
                data['tgl_jatuh_tempo_pinjaman'],
                data['dpd_terakhir'],
                data['dpd_max'],
                data['rn'],
            )
            formatted_base_data.extend(formatted_data)

        result_raw_query = (
            """
        WITH base AS (
            SELECT * FROM (VALUES """
            + base_values
            + """) AS
            t(
                customer_id, application_id, fdc_inquiry_id, cdate,
                application_date, status_pinjaman, inquiry_date,
                tgl_penyaluran_dana, tgl_jatuh_tempo_pinjaman, dpd_terakhir, dpd_max, rn
            )
        )

        , wo as (
            select
                customer_id
            from
                base
            where
                status_pinjaman = 'Write-Off'
        )

        , bad as ( -- approve 2 l90d have delinquency --
            select
                customer_id
            from
                base
            where
                application_date - tgl_penyaluran_dana between 0 and 90 --- change date---
                and
                dpd_max > 0
                and
                rn = 1
        )

        , bad2 as ( --- ever had delinquency record ---
            select
                customer_id
            from
                base
            where
                dpd_max > 0
                and
                rn = 1
        )

        , d1 as (
        select
            b.customer_id
        from
            base b
        left join
            bad bd on b.customer_id = bd.customer_id
        where
            dpd_max > 0
            and
            bd.customer_id is null
            and
            application_date - tgl_penyaluran_dana between 91 and 365
            and
            rn = 1
        )

        , d2 as(
        select
            b.customer_id
        from
            base b
        left join
            bad bd on b.customer_id = bd.customer_id
        where
            dpd_max > 0
            and
            bd.customer_id is null
            and
            application_date - tgl_penyaluran_dana between 366 and 730
            and
            rn = 1
        )

        , nd as (
        select
            b.customer_id
        from
            base b
        left join
            bad2 bd2 on b.customer_id = bd2.customer_id
        where
            dpd_max < 1
            and
            bd2.customer_id is null
            and
            status_pinjaman not in ('Write-Off')
            and
            rn = 1
        )

        , app as (
        select
            customer_id,
            case
                when customer_id in (select customer_id from wo) then 'Approve1' --- Write Off --
            when customer_id in (select customer_id from bad) then 'Approve2' --Current Delinquent--
                when customer_id in (select customer_id from d1) then 'Approve3' ---Delinquent 1y---
                when customer_id in (select customer_id from d2) then 'Approve4' ---Delinquent 2y---
                when customer_id in (select customer_id from nd) then 'Approve5' ---NonDelinquent---
            end cust_group,
            dpd_terakhir,
            dpd_max,
            inquiry_date,
            tgl_penyaluran_dana,
            tgl_jatuh_tempo_pinjaman
        from
            base
        where
            rn = 1
        )

        select distinct
            dcd.dana_customer_identifier,
            date(a.cdate) application_date,
            dcd.customer_id,
            case when
                cust_group is not null then cust_group
                else 'Approve6'
            end status,
            dpd_terakhir,
            dpd_max,
            inquiry_date,
            tgl_penyaluran_dana,
            tgl_jatuh_tempo_pinjaman
        from
            ops.dana_customer_data dcd
        left join
            ops.application a on dcd.customer_id = a.customer_id
        left join
            app  on dcd.customer_id = app.customer_id
        where
            dana_customer_identifier = %s
        """
        )

        with connection.cursor() as cursor:
            cursor.execute(
                result_raw_query, tuple(formatted_base_data) + (dana_customer_identifier,)
            )
            results = cursor.fetchone()

        if not results:
            logger.error(
                {
                    "action": "failed_dana_send_fdc_status",
                    "message": "FDC Results Not Found",
                    "customer_id": dana_customer_identifier,
                }
            )
            return False

        # Update FDC Status
        fdc_status = results[3]
        dana_fdc_result.update_safely(fdc_status=fdc_status)
        return True
    except Exception as err:
        logger.error(
            {
                "action": "failed_dana_send_fdc_status",
                "error": str(err),
                "message": "Failed Update Fdc status",
                "customer_id": dana_customer_identifier,
                "results": results,
            }
        )
        return False


def validate_underage_check(
    dana_customer_data: DanaCustomerData,
    application_id: int,
    dana_application_reference: DanaApplicationReference,
) -> Union[Dict, None]:
    """Validate dana customer age, reject application if below 21 years old"""
    from dateutil.relativedelta import relativedelta

    today = datetime.today()
    dob = dana_customer_data.dob
    age = relativedelta(today, dob)
    if age.years < 21:
        process_application_status_change(
            application_id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason=OnboardingRejectReason.UNDERAGE,
        )

        data = {
            'responseCode': BindingResponseCode.BAD_REQUEST.code,
            'responseMessage': BindingResponseCode.BAD_REQUEST.message,
            'accountId': str(dana_customer_data.customer.customer_xid),
            'partnerReferenceNo': dana_application_reference.partner_reference_no,
            'referenceNo': str(dana_application_reference.reference_no),
            'additionalInfo': {
                'rejectCode': BindingRejectCode.UNDERAGED_CUSTOMER.code,
                'rejectReason': BindingRejectCode.UNDERAGED_CUSTOMER.reason,
            },
        }

        return data

    return None


def process_completed_application_data(application_id: int) -> None:
    """
    this function for migration last data application DANA
    to new application with different lender_product_id
    """
    dana_customer_data = (
        DanaCustomerData.objects.select_related('application')
        .filter(application_id=application_id)
        .last()
    )

    if not dana_customer_data:
        logger.error(
            {
                "action": "failed_process_completed_application_data",
                "message": "Dana customer data not found",
                "application_id": application_id,
            }
        )
        return None

    last_dana_customer_data = (
        DanaCustomerData.objects.select_related('application')
        .filter(dana_customer_identifier=dana_customer_data.dana_customer_identifier)
        .exclude(lender_product_id=dana_customer_data.lender_product_id)
        .last()
    )

    if not last_dana_customer_data:
        logger.info(
            {
                "action": "skip_process_completed_application_data",
                "message": "Dana customer doesn't have any other product",
                "customer_id": dana_customer_data.dana_customer_identifier,
            }
        )
        return None

    new_application = dana_customer_data.application
    last_application = last_dana_customer_data.application

    if last_application:
        """
        Make sure one of the fields exists on the last application.
        here is the list of fields:
            1. application.gender
            2. application.address_kabupaten
            3. application.address_provinsi
            4. application.address_kodepos
            5. application.marital_status
            6. application.job_type
            7. application.job_industry
            8. application.monthly_income
        if one of the fields in the last application exists we will do the process
        update data to new application
        """
        if (
            last_application.address_provinsi
            or last_application.address_kabupaten
            or last_application.address_kodepos
            or last_application.gender
            or last_application.job_type
            or last_application.job_industry
            or last_application.monthly_income
            or last_application.marital_status
        ):
            application_update_fields = []
            if last_application.address_provinsi:
                new_application.address_provinsi = last_application.address_provinsi
                application_update_fields.append('address_provinsi')

            if last_application.address_kabupaten:
                new_application.address_kabupaten = last_application.address_kabupaten
                application_update_fields.append('address_kabupaten')

            if last_application.address_kodepos:
                new_application.address_kodepos = last_application.address_kodepos
                application_update_fields.append('address_kodepos')

            if last_application.gender:
                new_application.gender = last_application.gender
                application_update_fields.append('gender')

            if last_application.job_type:
                new_application.job_type = last_application.job_type
                application_update_fields.append('job_type')

            if last_application.job_industry:
                new_application.job_industry = last_application.job_industry
                application_update_fields.append('job_industry')

            if last_application.monthly_income:
                new_application.monthly_income = last_application.monthly_income
                application_update_fields.append('monthly_income')

            if last_application.marital_status:
                new_application.marital_status = last_application.marital_status
                application_update_fields.append('marital_status')

            new_application.save(update_fields=application_update_fields)
            logger.info(
                {
                    "action": "success_process_completed_application_data",
                    "message": "Success migrate data to new application ",
                    "customer_id": dana_customer_data.dana_customer_identifier,
                    "new_application": "new_application_id {}, with lender_product_id {}".format(
                        new_application.id, dana_customer_data.lender_product_id
                    ),
                    "last_application": "last_application_id {}, with lender_product_id {}".format(
                        last_application.id, last_dana_customer_data.lender_product_id
                    ),
                }
            )
            return None

    logger.info(
        {
            "action": "skip_process_completed_application_data",
            "message": "Other dana_customer_data product user found, but doesn't have application",
            "customer_id": dana_customer_data.dana_customer_identifier,
        }
    )
    return None


def validate_customer_for_dana_cash_loan(
    dana_customer_identifier: str,
    partner_reference_no: str,
) -> Union[Dict, None]:
    """
    Customer checking based on dana_customer_identifier with:
    - feature setting dana_cash_loan_registration_user_config is True(if False we skip validate)
    - dana_customer_identifier have DANA CICIL
    """
    allowed_dana_cash_loan_user_config = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_CASH_LOAN_REGISTRATION_USER_CONFIG,
        is_active=True,
    ).exists()

    if not allowed_dana_cash_loan_user_config:
        logger.info(
            {
                'action_view': 'validate_customer_for_dana_cash_loan',
                'message': 'feature setting {} is off, we skip checking existing data'.format(
                    FeatureNameConst.DANA_CASH_LOAN_REGISTRATION_USER_CONFIG
                ),
            }
        )
        return None

    is_have_dana_cicil_account = DanaCustomerData.objects.filter(
        dana_customer_identifier=dana_customer_identifier,
        lender_product_id=DanaProductType.CICIL,
    ).exists()

    if not is_have_dana_cicil_account:
        """
        If a dana_customer_identifier does not have a DANA CICIL,
        their registration will be rejected
        """
        data = {
            'responseCode': BindingResponseCode.BAD_REQUEST.code,
            'responseMessage': BindingResponseCode.BAD_REQUEST.message,
            'partnerReferenceNo': partner_reference_no,
            'additionalInfo': {
                'rejectCode': BindingRejectCode.NON_EXISTING_DANA_CICIL_USER.code,
                'rejectReason': BindingRejectCode.NON_EXISTING_DANA_CICIL_USER.reason,
            },
        }

        return data

    return None


def generate_dana_credit_score_based_fdc_result(application: Application, fdc_result: str) -> str:
    """
    Application_id: application_id Object
    fdc_result: dana_fdc_result.fdc_status string
    """
    customer_id = application.customer_id
    application_id = application.id
    has_loans = Loan.objects.filter(customer_id=customer_id).exists()

    if fdc_result == DanaFDCResultStatus.APPROVE1:
        if has_loans:
            new_credit_score = 'C+'
        else:
            new_credit_score = 'C'
    elif fdc_result == DanaFDCResultStatus.APPROVE2:
        new_credit_score = 'B--'
    elif fdc_result == DanaFDCResultStatus.APPROVE3:
        new_credit_score = 'B-'
    elif fdc_result == DanaFDCResultStatus.APPROVE4:
        new_credit_score = 'B'
    elif fdc_result == DanaFDCResultStatus.APPROVE5:
        new_credit_score = 'B+'
    elif fdc_result == DanaFDCResultStatus.APPROVE6:
        new_credit_score = 'A-'
    else:
        raise Exception(
            'Mapping application_id={} Failed fdc_result={} not found'.format(
                application_id, fdc_result
            )
        )

    if hasattr(application, 'creditscore'):
        credit_score = application.creditscore
        credit_score.update_safely(score=new_credit_score)
    else:
        CreditScore.objects.create(application_id=application_id, score=new_credit_score)


def dana_populate_pusdafil_data(dana_customer_data: DanaCustomerData) -> None:
    dana_province_city_feature = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.DANA_PROVINCE_AND_CITY
    )

    dana_occupation_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.DANA_JOB
    )

    uppercase_province = None
    uppercase_city = None
    occupation_value = None
    occupation_industry_value = None
    updated_fields = []

    application = dana_customer_data.application
    if dana_province_city_feature:

        if dana_customer_data.province_home_address:
            uppercase_province = dana_customer_data.province_home_address.upper()

        if dana_customer_data.city_home_address:
            uppercase_city = dana_customer_data.city_home_address.upper()

        dana_province_mapping = dana_province_city_feature.parameters['province']
        province_value = (
            dana_province_mapping.get(uppercase_province, '') if uppercase_province else ''
        )

        dana_city_mapping = dana_province_city_feature.parameters['city']
        city_value = dana_city_mapping.get(uppercase_city, '') if uppercase_city else ''

        # set updated data
        application.address_provinsi = province_value
        application.address_kabupaten = city_value
        updated_fields.append('address_provinsi')
        updated_fields.append('address_kabupaten')

    if dana_occupation_feature_setting and dana_customer_data.occupation:
        dana_occupation_mapping = dana_occupation_feature_setting.parameters['job']

        occupation_value = dana_occupation_mapping.get(dana_customer_data.occupation.upper(), '')

        if occupation_value:
            occupation_industry_value = job__job_industries.get(occupation_value.upper(), '')
            application.job_industry = occupation_industry_value
            updated_fields.append('job_industry')

        # set updated data
        application.job_type = occupation_value
        updated_fields.append('job_type')

    if dana_customer_data.gender:
        application.gender = gender.get(dana_customer_data.gender.upper())
        updated_fields.append('gender')

    if dana_customer_data.postal_code_home_address:
        pattern = r'^\d{5}$'
        if re.match(pattern, dana_customer_data.postal_code_home_address):
            application.address_kodepos = dana_customer_data.postal_code_home_address
            updated_fields.append('address_kodepos')

    if updated_fields:
        application.save(update_fields=updated_fields)
    else:
        logger.info(
            {
                'action_view': 'fail_dana_populate_pusdafil_data',
                'application_id': application.id,
                'message': 'skip populate pusdafil data from other application',
            }
        )


def proces_max_creditor_check(application: Application, fdc_result: str) -> None:
    application_id = application.id
    dana_application_reference = DanaApplicationReference.objects.filter(
        application_id=application_id
    ).last()

    if fdc_result == DanaFDCResultStatus.INIT:
        logger.error(
            {
                'action_view': 'proces_max_creditor_check',
                'application_id': application_id,
                'message': 'invalid fdc_result, fdc_result should be init',
            }
        )
        dana_application_reference.update_safely(creditor_check_status=MaxCreditorStatus.PENDING)
        return

    config_data = (
        PartnershipFlowFlag.objects.filter(
            partner_id=application.partner_id, name=PartnershipFlag.MAX_CREDITOR_CHECK
        )
        .values_list('configs', flat=True)
        .last()
    )

    if not config_data:
        logger.info(
            {
                'action_view': 'proces_max_creditor_check',
                'application_id': application_id,
                'message': 'flag {} not found, we skip checking set as True'.format(
                    PartnershipFlag.MAX_CREDITOR_CHECK
                ),
            }
        )
        dana_application_reference.update_safely(creditor_check_status=MaxCreditorStatus.PASS)
        return

    if not config_data.get('is_active'):
        logger.info(
            {
                'action_view': 'proces_max_creditor_check',
                'application_id': application_id,
                'message': 'feature is off, we skip checking set as True',
            }
        )
        dana_application_reference.update_safely(creditor_check_status=MaxCreditorStatus.PASS)
        return

    if not config_data.get('statuses'):
        logger.info(
            {
                'action_view': 'proces_max_creditor_check',
                'application_id': application_id,
                'message': 'flag status {} not found, we skip checking set as True'.format(
                    PartnershipFlag.MAX_CREDITOR_CHECK
                ),
            }
        )
        dana_application_reference.update_safely(creditor_check_status=MaxCreditorStatus.PASS)
        return

    status_need_to_check = config_data.get('statuses')
    if fdc_result not in status_need_to_check:
        dana_application_reference.update_safely(creditor_check_status=MaxCreditorStatus.PASS)
        return

    parameters = get_parameters_fs_check_other_active_platforms_using_fdc()
    if not is_apply_check_other_active_platforms_using_fdc(application_id, parameters):
        dana_application_reference.update_safely(creditor_check_status=MaxCreditorStatus.PASS)
        return

    outdated_threshold_days = parameters["fdc_data_outdated_threshold_days"]
    number_allowed_platforms = parameters["number_of_allowed_platforms"]
    customer = application.customer

    is_eligible, _ = check_eligible_and_out_date_other_platforms(
        customer.id,
        application_id,
        outdated_threshold_days,
        number_allowed_platforms,
    )
    if is_eligible:
        dana_application_reference.update_safely(creditor_check_status=MaxCreditorStatus.PASS)
    else:
        dana_application_reference.update_safely(creditor_check_status=MaxCreditorStatus.NOT_PASS)

    return


def validate_dana_binary_check(
    dana_customer_data,
    user_whitelisted,
    dana_application_reference,
    application_id,
    dana_phone,
    dana_nik,
):
    from juloserver.dana.tasks import populate_dana_pusdafil_data_task

    possible_phone_numbers = {
        format_mobile_phone(dana_phone),
        format_nexmo_voice_phone_number(dana_phone),
    }

    is_customer_phone_exists = (
        Customer.objects.filter(
            phone__in=possible_phone_numbers,
            is_active=True,
        )
        .last()
    )

    # Populate Pusdafil Data
    dana_customer_id = int(dana_customer_data.id)
    populate_dana_pusdafil_data_task.delay(dana_customer_id)

    if not user_whitelisted:

        # Reject Only if existing phone number in J1 and JULOVERS but different NIK
        if is_customer_phone_exists:
            """
            Handle Julovers data, If nik None or filled
            Continue checking to JULOVERS table, because the format itself
            Some nik data is filled and some data not
            """

            # Load Config Approval
            partner_id = int(dana_customer_data.partner_id)
            dana_approval_config = (
                PartnershipFlowFlag.objects.filter(
                    partner_id=partner_id, name=PartnershipFlag.APPROVAL_CONFIG
                )
                .values_list('configs', flat=True)
                .last()
            )

            days_threshold = None
            x190_check = False
            is_validation_config_active = False
            if dana_approval_config:
                config = dana_approval_config.get('verify_same_phone_number_with_existing_nik')
                if config and config.get('is_active'):
                    is_validation_config_active = True
                    days_threshold = config.get('days_threshold')
                    x190_check = config.get('x190_check')

            julovers_data = (
                Julovers.objects.filter(mobile_phone_number__in=possible_phone_numbers)
                .values('cdate', 'real_nik', 'application_id')
                .last()
            )
            if julovers_data:
                julovers_nik = julovers_data['real_nik']
                if julovers_nik != dana_nik:

                    validate_phone_number = True
                    has_application_x190 = False
                    if is_validation_config_active:
                        created_datetime = timezone.localtime(julovers_data['cdate'])
                        current_datetime = timezone.localtime(timezone.now())
                        date_diff = current_datetime - created_datetime

                        if days_threshold and date_diff.days > days_threshold:
                            validate_phone_number = False

                        if x190_check:
                            if julovers_data.get('application_id'):
                                application = Application.objects.filter(
                                    id=julovers_data['application_id']
                                ).last()
                                if application and application.application_status_id == 190:
                                    has_application_x190 = True

                    if validate_phone_number or has_application_x190:
                        data = reject_customer_existing_phone_number_with_different_nik(
                            application_id, dana_application_reference, dana_customer_data
                        )

                        message = (
                            "reject customer existing phone number with different nik julovers"
                        )

                        logger.info(
                            {
                                'action_view': 'validate_dana_binary_check',
                                'application_id': application_id,
                                'message': message,
                            }
                        )

                        return status.HTTP_400_BAD_REQUEST, data
                    else:
                        # Tracked if skip this check
                        logger.info(
                            {
                                'action_view': 'validate_dana_binary_check',
                                'application_id': application_id,
                                'message': 'skip checking EXISTING_PHONE_DIFFERENT_NIK',
                            }
                        )

                        PartnershipApplicationFlag.objects.create(
                            application_id=application_id,
                            name=OnboardingApproveReason.BYPASS_PHONE_SAME_NIK_NEW_RULES,
                        )
            else:
                registered_nik = is_customer_phone_exists.nik
                if registered_nik and registered_nik != dana_nik:

                    validate_phone_number = True
                    has_application_x190 = False

                    if is_validation_config_active:
                        created_datetime = timezone.localtime(is_customer_phone_exists.cdate)
                        current_datetime = timezone.localtime(timezone.now())
                        date_diff = current_datetime - created_datetime

                        if days_threshold and date_diff.days > days_threshold:
                            validate_phone_number = False

                        if x190_check:
                            application_x190_exists = Application.objects.filter(
                                customer_id=is_customer_phone_exists.id,
                                application_status=ApplicationStatusCodes.LOC_APPROVED,
                            ).exists()
                            if application_x190_exists:
                                has_application_x190 = True

                    if validate_phone_number or has_application_x190:
                        data = reject_customer_existing_phone_number_with_different_nik(
                            application_id, dana_application_reference, dana_customer_data
                        )

                        message = (
                            "reject customer existing phone number with different nik customer"
                        )

                        logger.info(
                            {
                                'action_view': 'validate_dana_binary_check',
                                'application_id': application_id,
                                'message': message,
                            }
                        )

                        return status.HTTP_400_BAD_REQUEST, data
                    else:
                        # Tracked if skip this check
                        logger.info(
                            {
                                'action_view': 'validate_dana_binary_check',
                                'application_id': application_id,
                                'message': 'skip checking EXISTING_PHONE_DIFFERENT_NIK',
                            }
                        )

                        PartnershipApplicationFlag.objects.create(
                            application_id=application_id,
                            name=OnboardingApproveReason.BYPASS_PHONE_SAME_NIK_NEW_RULES,
                        )

        # Blacklist Check
        blacklisted_response = validate_blacklist_check(
            dana_customer_data, application_id, dana_application_reference
        )
        if blacklisted_response:
            return status.HTTP_400_BAD_REQUEST, blacklisted_response

        # Underage Check
        underage_response = validate_underage_check(
            dana_customer_data, application_id, dana_application_reference
        )
        if underage_response:
            return status.HTTP_400_BAD_REQUEST, underage_response

        # Fraud Check
        fraud_response = validate_fraud_check(
            dana_customer_data, application_id, dana_application_reference
        )
        if fraud_response:
            return status.HTTP_400_BAD_REQUEST, fraud_response

        # Delinquent Check
        delinquent_response = validate_delinquent_check(
            dana_customer_data, application_id, dana_application_reference
        )
        if delinquent_response:
            return status.HTTP_400_BAD_REQUEST, delinquent_response

    return None, None


def dana_reject_manual_stuck(application):
    if application.status not in {
        ApplicationStatusCodes.FORM_CREATED,
        ApplicationStatusCodes.FORM_PARTIAL,
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
    }:
        logger.info(
            {
                'action': 'dana_reject_manual_stuck',
                'application_id': application.id,
                'status': application.application_status_id,
                'message': 'application not in 100, 105, 130',
            }
        )
        return True

    latest_application = Application.objects.filter(customer=application.customer).last()
    reason = "Update Manual by Scheduler"
    if latest_application != application:
        if application.status in {
            ApplicationStatusCodes.FORM_CREATED,
            ApplicationStatusCodes.FORM_PARTIAL,
        }:
            force_update_status(application, ApplicationStatusCodes.FORM_PARTIAL_EXPIRED, reason)
        else:
            force_update_status(application, ApplicationStatusCodes.APPLICATION_DENIED, reason)
        return True
    if not hasattr(application, 'dana_customer_data'):
        force_update_status(application, ApplicationStatusCodes.APPLICATION_DENIED, reason)
        return True

    return False


def force_update_status(application, new_status, change_reason):
    old_status_code = application.application_status_id
    application.update_safely(application_status_id=new_status)

    application_history_data = {
        'application': application,
        'status_old': old_status_code,
        'status_new': application.application_status_id,
        'change_reason': change_reason,
    }

    ApplicationHistory.objects.create(**application_history_data)
