import json
from builtins import str
from datetime import datetime

from babel.numbers import parse_number

from juloserver.followthemoney.models import LenderBucket
from juloserver.fraud_security.constants import FraudApplicationBucketType
from juloserver.fraud_security.models import (
    FraudVelocityModelGeohashBucket,
    FraudApplicationBucket
)
from juloserver.julo.models import Application
from juloserver.julo.models import ApplicationNote
from juloserver.julo.models import DashboardBuckets
from juloserver.julo.models import Payment, Document
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.portal.object.app_status.constants import JuloStarterFields
from .functions import unlocked_app
from .models import ApplicationLocked
from .models import ApplicationLockedMaster


def application_priority_dashboard():
    """
    get count data for each application status on the list
    """
    # print "application_dashboard HERE"
    status_to_do = [
        ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        ApplicationStatusCodes.PRE_REJECTION,
        ApplicationStatusCodes.CALL_ASSESSMENT,
        ApplicationStatusCodes.DOCUMENTS_VERIFIED,
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.APPLICANT_CALLS_ONGOING,
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.APPLICATION_RESUBMITTED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
        ApplicationStatusCodes.NAME_VALIDATE_ONGOING,
        ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
        ApplicationStatusCodes.NAME_VALIDATE_FAILED,
        ApplicationStatusCodes.LOC_APPROVED,
        ApplicationStatusCodes.LENDER_APPROVAL
    ]
    status_follow_up = [
        ApplicationStatusCodes.FORM_SUBMITTED,
        ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
        ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
        ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
        ApplicationStatusCodes.FORM_PARTIAL
    ]

    status_graveyard = [
        ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        ApplicationStatusCodes.APPLICATION_DENIED,
        ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
        ApplicationStatusCodes.OFFER_EXPIRED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
        ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
    ]
    status_graveyard = sorted(status_graveyard)

    status_partner = [
        ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
        ApplicationStatusCodes.PARTNER_APPROVED
    ]

    count_data = {
        'to_do': {},
        'follow_up': {},
        'graveyard': {},
        'partner_app': {}
    }

    buckets = DashboardBuckets.objects.last()
    if not buckets:
        buckets = DashboardBuckets.objects.create()

    for status in status_to_do:
        key = 'app_priority_{}'.format(status)
        count_data['to_do'][str(status)] = getattr(buckets, key)

    for status in status_follow_up:
        key = 'app_priority_{}'.format(status)
        count_data['follow_up'][str(status)] = getattr(buckets, key)

    for status in status_graveyard:
        key = 'app_priority_{}'.format(status)
        count_data['graveyard'][str(status)] = getattr(buckets, key)

    for status in status_partner:
        key = 'app_priority_{}'.format(status)
        count_data['partner_app'][str(status)] = getattr(buckets, key)

    count_data['follow_up']['courtesy_call'] = buckets.app_courtesy_call
    count_data['to_do']['cashback_request'] = buckets.app_cashback_request
    count_data['to_do']['overpaid_verification'] = buckets.app_overpaid_verification

    return count_data


def application_dashboard():
    """
    get count data for each application status on the list
    """
    # print "application_dashboard HERE"
    status_to_do = [
        ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        ApplicationStatusCodes.PRE_REJECTION,
        ApplicationStatusCodes.CALL_ASSESSMENT,
        ApplicationStatusCodes.DOCUMENTS_VERIFIED,
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.APPLICANT_CALLS_ONGOING,
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.APPLICATION_RESUBMITTED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        ApplicationStatusCodes.LENDER_APPROVAL,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
        ApplicationStatusCodes.NAME_VALIDATE_ONGOING,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
        ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
        ApplicationStatusCodes.NAME_VALIDATE_FAILED,
        ApplicationStatusCodes.LOC_APPROVED,
        ApplicationStatusCodes.NAME_BANK_VALIDATION_FAILED,
        ApplicationStatusCodes.ACTIVATION_AUTODEBET,
        ApplicationStatusCodes.DIGISIGN_FAILED,
        ApplicationStatusCodes.WAITING_LIST,
        ApplicationStatusCodes.BANK_NAME_CORRECTED,
    ]
    status_follow_up = [
        ApplicationStatusCodes.FORM_SUBMITTED,
        ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
        ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
        ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
        ApplicationStatusCodes.FORM_PARTIAL
    ]

    status_graveyard = [
        ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        ApplicationStatusCodes.APPLICATION_DENIED,
        ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
        ApplicationStatusCodes.OFFER_EXPIRED,
        ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
        ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
    ]
    status_graveyard = sorted(status_graveyard)

    status_partner = [
        ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
        ApplicationStatusCodes.PARTNER_APPROVED
    ]

    status_julo_one = [
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
        ApplicationStatusCodes.NAME_VALIDATE_FAILED,
        ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL,
        ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS,
    ]

    status_grab = [
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        ApplicationStatusCodes.APPLICATION_RESUBMITTED
    ]

    status_jstarter = [
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,  # 121
        ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
    ]

    status_partnership_agent_assisted_flow = [
        ApplicationStatusCodes.FORM_CREATED,  # 100
    ]

    status_deletion = [
        ApplicationStatusCodes.CUSTOMER_ON_DELETION,
        ApplicationStatusCodes.CUSTOMER_DELETED,
    ]

    count_data = {
        'to_do': {},
        'follow_up': {},
        'graveyard': {},
        'partner_app': {},
        'deletion': {},
    }

    buckets = DashboardBuckets.objects.last()
    if not buckets:
        buckets = DashboardBuckets.objects.create()

    for status in status_to_do:
        key = 'app_{}'.format(status)
        count_data['to_do'][str(status)] = getattr(buckets, key)

    for status in status_follow_up:
        key = 'app_{}'.format(status)
        count_data['follow_up'][str(status)] = getattr(buckets, key)

    for status in status_graveyard:
        key = 'app_{}'.format(status)
        count_data['graveyard'][str(status)] = getattr(buckets, key)

    for status in status_partner:
        key = 'app_{}'.format(status)
        count_data['partner_app'][str(status)] = getattr(buckets, key)

    for status in status_julo_one:
        key = 'app_{}_j1'.format(status)
        count_data['to_do'][str(status) + '_j1'] = getattr(buckets, key)

    for status in status_grab:
        key = 'app_{}_grab'.format(status)
        count_data['to_do'][str(status) + '_grab'] = getattr(buckets, key)

    for status in status_jstarter:
        key = 'app_{}_jstarter'.format(status)
        count_data['to_do'][str(status) + '_jstarter'] = getattr(buckets, key)

    for status in status_partnership_agent_assisted_flow:
        key = 'app_partnership_agent_assisted_{}'.format(status)
        count_data['to_do'][str(status) + '_agent_assisted'] = getattr(buckets, key)

    for status in status_deletion:
        key = 'app_{}'.format(status)
        count_data['deletion'][str(status)] = getattr(buckets, key)

    count_data['follow_up']['courtesy_call'] = buckets.app_courtesy_call
    count_data['to_do']['cashback_request'] = buckets.app_cashback_request
    count_data['to_do']['cashback_pending'] = buckets.app_cashback_pending
    count_data['to_do']['cashback_failed'] = buckets.app_cashback_failed
    count_data['to_do']['overpaid_verification'] = buckets.app_overpaid_verification
    count_data['to_do']['0_turbo'] = buckets.app_0_turbo
    count_data['to_do']['175_mtl'] = buckets.app_175_mtl
    count_data['to_do']['agent_assisted_100'] = buckets.app_agent_assisted_100

    return count_data

def lender_bucket():
    return dict(
        count=LenderBucket.objects.filter(is_active=True).count()
    )

def loan_dashboard():
    """
    get count data for each application status on the list
    [210, 211, 212, 213, 215, 216, 218, 220, 240, 250]
    """

    status_arr = [
        LoanStatusCodes.INACTIVE,
        LoanStatusCodes.LENDER_APPROVAL,
        LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.TRANSACTION_FAILED,
        LoanStatusCodes.CANCELLED_BY_CUSTOMER,
        LoanStatusCodes.FUND_DISBURSAL_FAILED,
        LoanStatusCodes.CURRENT,
        LoanStatusCodes.RENEGOTIATED,
        LoanStatusCodes.PAID_OFF
    ]

    status_julo_one = [
        LoanStatusCodes.INACTIVE,
        LoanStatusCodes.CURRENT
    ]

    buckets = DashboardBuckets.objects.last()
    if not buckets:
        buckets = DashboardBuckets.objects.create()

    count_data = {}
    for status in status_arr:
        key = 'loan_{}'.format(status)
        count_data[str(status)] = getattr(buckets, key)

    for status in status_julo_one:
        key = 'loan_{}_j1'.format(status)
        count_data[str(status) + '_j1'] = getattr(buckets, key)

    count_data['cycle_day_requested'] = buckets.loan_cycle_day_requested

    return count_data


def payment_dashboard():
    """
    get count data for each application status on the list
    [0 > T >= -5, T0, T > 0 ]
    """

    buckets = DashboardBuckets.objects.last()
    if not buckets:
        buckets = DashboardBuckets.objects.create()

    keys = ['T531', 'Tminus5', 'Tminus3', 'Tminus1', 'T0', 'T1to4',
            'T5to30', 'Tplus30', 'TnotCalled', 'PTP', 'T5', 'T1',
            'grab', 'whatsapp', 'whatsapp_blasted', 'Tminus5Robo', 'Tminus3Robo']

    count_data = {key: getattr(buckets, 'payment_{}'.format(key)) for key in keys}

    for status in PaymentStatusCodes.paid_status_codes():
        key = 'payment_{}'.format(status)
        data_count = getattr(buckets, key, None)
        if data_count is not None:
            count_data[str(status)] = data_count

    return count_data


def payment_dashboard_new_bucket():
    """
    get count data for each application status on the list
    [TnotCalled, PTP, grab, whatsapp, whatsapp_blasted, Tminus5Robo,
    Tminus3Robo, 330, 331, 332]
    """

    buckets = DashboardBuckets.objects.last()
    if not buckets:
        buckets = DashboardBuckets.objects.create()

    keys = ['TnotCalled', 'PTP', 'grab', 'whatsapp',
            'whatsapp_blasted', 'Tminus5Robo', 'Tminus3Robo']

    count_data = {key: getattr(buckets, 'payment_{}'.format(key)) for key in keys}

    bucket_1to5 = get_payment_bucket_1to5_from_cache()

    if bucket_1to5:
        count_data.update(bucket_1to5)

    for status in PaymentStatusCodes.paid_status_codes():
        key = 'payment_{}'.format(status)
        data_count = getattr(buckets, key, None)
        if data_count is not None:
            count_data[str(status)] = data_count

    return count_data


def get_payment_bucket_1to5_from_cache():
    """
    Depreceted
    """
    key = 'payment_bucket_1to5'
    redis_client = get_redis_client()
    result = redis_client.get(key)
    if not result:
        return result
    return json.loads(result)


def update_payment_bucket_1to5_in_cache():
    """
    Depreceted
    """
    key = 'payment_bucket_1to5'
    bucket_1to5 = payment_bucket_1to5()
    redis_client = get_redis_client()
    redis_client.set(key, json.dumps(bucket_1to5))


def payment_bucket_1to5():
    """
    Depreceted
    """
    payment_query = Payment.objects.exclude(
        loan__application__partner__name__in=PartnerConstant.form_partner()
    ).normal()

    buckets_dict = {}
    buckets_dict['bucket_1'] = payment_query.bucket_1_list().count()
    buckets_dict['bucket_2'] = payment_query.bucket_2_list().count()
    buckets_dict['bucket_3'] = payment_query.bucket_3_list().count()
    buckets_dict['bucket_4'] = payment_query.bucket_4_list().count()
    buckets_dict['bucket_5'] = payment_query.bucket_5_list().count()
    return buckets_dict


def app_locked_data_all(request):
    if request.user.is_authenticated():
        result = ApplicationLocked.objects.filter(
            locked=True, status_obsolete=False
        ).order_by("user_lock", "ts_locked")
        return result.exclude(user_lock=request.user)
    else:
        return None


def app_locked_data_user(request):
    if request.user.is_authenticated():
        result = ApplicationLocked.objects.select_related('application').filter(
            locked=True, status_obsolete=False, user_lock=request.user
        ).order_by("status_code_locked", "ts_locked")
        return result
    else:
        return None


def dump_application_values_to_excel(app_obj):
    field_ordering = [
        'cdate', 'udate', 'id', 'loan_amount_request', 'loan_duration_request',
        'loan_purpose', 'marketing_source', 'referral_code', 'is_own_phone',
        'fullname', 'dob', 'gender', 'ktp', 'address_street_num',
        'address_provinsi', 'address_kabupaten', 'address_kecamatan',
        'address_kelurahan', 'address_kodepos', 'occupied_since', 'home_status',
        'landlord_mobile_phone', 'mobile_phone_1', 'has_whatsapp_1', 'mobile_phone_2',
        'has_whatsapp_2', 'email', 'bbm_pin', 'marital_status', 'dependent',
        'spouse_name', 'spouse_dob', 'spouse_mobile_phone', 'spouse_has_whatsapp',
        'kin_name', 'kin_dob', 'kin_gender', 'kin_mobile_phone',
        'kin_relationship', 'job_type', 'job_description', 'company_name',
        'company_phone_number', 'job_start', 'monthly_income',
        'income_1', 'income_2', 'income_3', 'last_education', 'graduation_year',
        'gpa', 'has_other_income', 'other_income_amount',
        'other_income_source', 'monthly_housing_cost', 'monthly_expenses',
        'total_current_debt', 'vehicle_type_1', 'vehicle_ownership_1',
        'bank_name', 'bank_branch', 'bank_account_number',
        'is_term_accepted', 'is_verification_agreed', 'is_document_submitted',
        'is_sphp_signed', 'sphp_exp_date',
        'twitter_username', 'instagram_username',
        'loan_purpose_desc', 'work_kodepos', 'job_function',
        'job_industry', 'college', 'major',
        'application_xid', 'app_version', 'application_number',
        'gmail_scraped_status', 'payday'
    ]
    fields = []
    values = []
    for field in field_ordering:
        fields.append(str(field))
        values.append(str(eval('app_obj.%s' % field)))
    ret_values = '\t'.join(values)
    ret_fields = '\t'.join(fields)
    return ret_fields, ret_values


def re_configure_req_post(request_post):

    if 'form2-payday' in request_post:
        if request_post['form2-payday'] != '':
            request_post['form2-payday'] = datetime.strptime(
                str(request_post['form2-payday']).strip(), "%d-%m-%Y")

    if 'form2-kin_dob' in request_post:
        if request_post['form2-kin_dob'] != '':
            request_post['form2-kin_dob'] = datetime.strptime(
                str(request_post['form2-kin_dob']).strip(), "%d-%m-%Y")

    if 'form2-monthly_income' in request_post:
        request_post['form2-monthly_income'] = parse_number(
            request_post['form2-monthly_income'], locale='id_ID')

    if 'form2-other_income_amount' in request_post:
        request_post['form2-other_income_amount'] = parse_number(
            request_post['form2-other_income_amount'], locale='id_ID')

    if 'form2-monthly_housing_cost'in request_post:
        request_post['form2-monthly_housing_cost'] = parse_number(
            request_post['form2-monthly_housing_cost'], locale='id_ID')

    if 'form2-monthly_expenses' in request_post:
        request_post['form2-monthly_expenses'] = parse_number(
            request_post['form2-monthly_expenses'], locale='id_ID')

    if 'form2-total_current_debt' in request_post:
        request_post['form2-total_current_debt'] = parse_number(
            request_post['form2-total_current_debt'], locale='id_ID')


def pv_3rd_party_dashboard():
    """
    get count data for each sim application status
    """
    # print "application_dashboard HERE"
    status_to_do = [
        ApplicationStatusCodes.DOCUMENTS_VERIFIED_BY_THIRD_PARTY,
        ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL_BY_THIRD_PARTY,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING_BY_THIRD_PARTY,
    ]

    count_data = {
        'to_do': {},
    }

    buckets = DashboardBuckets.objects.last()
    if not buckets:
        buckets = DashboardBuckets.objects.create()

    for status in status_to_do:
        key = 'app_{}'.format(status)
        count_data['to_do'][str(status)] = getattr(buckets, key)

    return count_data


def lock_app_by_system(application_id):
    """
    to lock app by system for experiment application with further porcess that has interval time
    to prevent application lock and processed by agent
    """
    application = Application.objects.get(pk=application_id)
    # currently set None need to create user sysadmin to used here
    user = None
    app_locked_master = ApplicationLockedMaster.get_or_none(
        user=user, application=application, locked=True)
    if app_locked_master:
        unlocked_app(application, user)
        app_locked_master.delete()
        return

    app_lock_master = ApplicationLockedMaster.create(
        user=user, application=application, locked=True)
    if app_lock_master:
        ApplicationLocked.create(
            application=application, user=user,
            status_code_locked=application.application_status.status_code)


def unlock_app_by_system(application_id):
    """
    to unlock locked app
    can be use for:
    - application that locked by agent and the agent forget to unlock
    - application that locked by system (ex: experiment application)
    """
    application = Application.objects.get(pk=application_id)
    # currently set None need to create user sysadmin to used here
    user = None
    app_locked_master = ApplicationLockedMaster.get_or_none(
        user=user, application=application, locked=True)
    if app_locked_master:
        unlocked_app(application, user)
        app_locked_master.delete()


def get_js_validation_fields(application):
    if not application.is_julo_starter():
        return []

    if application.application_status_id < ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED:
        return JuloStarterFields.REQUIRE_FIELDS

    # check if customer had been sign master agreement
    is_ma_signed = Document.objects.filter(
        document_source=application.id, document_type='master_agreement'
    ).exists()

    return JuloStarterFields.ALL_FIELDS if is_ma_signed else JuloStarterFields.REQUIRE_FIELDS


def fraudops_dashboard():
    """
    get count data for geohash bucket entries not checked by agents
    """
    count_data = {
        'to_do': {},
        'label': []
    }

    geohashes_tocheck = FraudVelocityModelGeohashBucket.objects.filter(
        fraud_velocity_model_results_check__isnull=True).count()

    fraudApplicationBucket = FraudApplicationBucket.objects.filter(
        is_active=True,
        application__application_status=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
    )
    selfie_geohash_tocheck = (
        fraudApplicationBucket.filter(
            type=FraudApplicationBucketType.SELFIE_IN_GEOHASH,
        )
        .distinct()
        .count()
    )
    bank_name_velocity_tocheck = (
        fraudApplicationBucket.filter(
            type=FraudApplicationBucketType.BANK_NAME_VELOCITY,
        )
        .distinct()
        .count()
    )
    risky_phone_and_email_tocheck = (
        fraudApplicationBucket.filter(
            type=FraudApplicationBucketType.RISKY_PHONE_AND_EMAIL,
        )
        .distinct()
        .count()
    )
    risky_location_tocheck = (
        fraudApplicationBucket.filter(
            type=FraudApplicationBucketType.RISKY_LOCATION,
        )
        .distinct()
        .count()
    )

    count_data['to_do'].update(
        {
            FraudApplicationBucketType.VELOCITY_MODEL_GEOHASH: geohashes_tocheck,
            FraudApplicationBucketType.SELFIE_IN_GEOHASH: selfie_geohash_tocheck,
            FraudApplicationBucketType.BANK_NAME_VELOCITY: bank_name_velocity_tocheck,
            FraudApplicationBucketType.RISKY_PHONE_AND_EMAIL: risky_phone_and_email_tocheck,
            FraudApplicationBucketType.RISKY_LOCATION: risky_location_tocheck,
        }
    )

    count_data['label'] = [
        FraudApplicationBucketType.label(FraudApplicationBucketType.VELOCITY_MODEL_GEOHASH),
        FraudApplicationBucketType.label(FraudApplicationBucketType.SELFIE_IN_GEOHASH),
        FraudApplicationBucketType.label(FraudApplicationBucketType.BANK_NAME_VELOCITY),
        FraudApplicationBucketType.label(FraudApplicationBucketType.RISKY_PHONE_AND_EMAIL),
        FraudApplicationBucketType.label(FraudApplicationBucketType.RISKY_LOCATION),
    ]
    return count_data

def is_customer_soft_deleted(
    history_notes: list,
) -> bool:
    for note in history_notes:
        if is_soft_deleted(note):
            return True

    return False


def is_soft_deleted(
    note,
) -> bool:
    
    if type(note) != ApplicationNote:
        return False

    return 'soft deletion' in note.note_text.lower() or 'soft delete' in note.note_text.lower()
