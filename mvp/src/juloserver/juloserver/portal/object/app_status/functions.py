from __future__ import print_function
from future import standard_library

standard_library.install_aliases()
from builtins import str
import urllib.request, urllib.parse, urllib.error
from django.db.models import Count, Q
from django.contrib.auth.decorators import user_passes_test

from .models import ApplicationLocked, ApplicationLockedMaster
from juloserver.julo.constants import CashbackTransferConst
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import CashbackTransferTransaction
from juloserver.julo.models import Skiptrace
from dashboard.constants import BucketCode


LOCK_STATUS_LIST =  [
    ApplicationStatusCodes.FORM_SUBMITTED, # 110
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS, # 115
    ApplicationStatusCodes.DOCUMENTS_SUBMITTED, # 120
    ApplicationStatusCodes.SCRAPED_DATA_VERIFIED, # 121
    ApplicationStatusCodes.DOCUMENTS_VERIFIED, # 122,
    ApplicationStatusCodes.DOCUMENTS_VERIFIED_BY_THIRD_PARTY, #1220
    ApplicationStatusCodes.PRE_REJECTION, # 123,
    ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL, # 124,
    ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL_BY_THIRD_PARTY, # 1240,
    ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL,  # 127
    ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS, #128
    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL, # 130,
    ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED, # 131
    ApplicationStatusCodes.APPLICATION_RESUBMITTED, # 132
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR, # 134
    ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING, # 138
    ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING_BY_THIRD_PARTY, # 1380
    ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,  # 140
    ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,  # 141
    ApplicationStatusCodes.WAITING_LIST,  # 155
    ApplicationStatusCodes.NAME_BANK_VALIDATION_FAILED,  # 144
    ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,  # 162
    ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,  # 163
    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,  # 170
    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,  # 172
    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,  # 180
    ApplicationStatusCodes.LOC_APPROVED,  # 190
]

CHANGE_REASONS_FIELD = ['131','138']
MAX_COUNT_LOCK_APP = 3
FIN_MAX_COUNT_LOCK_APP = 6
AUTODIAL_SIM_STATUSES = [
    ApplicationStatusCodes.DOCUMENTS_VERIFIED_BY_THIRD_PARTY, # 1220
    ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL_BY_THIRD_PARTY, # 1240
    ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING_BY_THIRD_PARTY, # 1380
]
NAME_BANK_VALIDATION_STATUSES = [
    ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED, #163
    ApplicationStatusCodes.NAME_VALIDATE_ONGOING, #164
    ApplicationStatusCodes.LENDER_APPROVAL, #165
    ApplicationStatusCodes.NAME_VALIDATE_FAILED, #175
    ApplicationStatusCodes.BANK_NAME_CORRECTED, #179
]
DISBURSEMENT_STATUSES = [
    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
    ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
]


def role_allowed(user_obj, arr_group):
    return user_obj.groups.filter(name__in=arr_group).exists()


def check_lock_app(app_obj, user_obj):
    app_locked_master = ApplicationLockedMaster.objects.get_or_none(application=app_obj)

    if (app_locked_master == None):
        return 3, None

    if app_obj:
        app_locked_obj = ApplicationLocked.objects.filter(
            application=app_obj,
            status_obsolete=False,
            locked=True,
            user_lock = user_obj)

        if app_locked_obj:
            return 1, app_locked_obj

        else:
            app_locked_obj_in = ApplicationLocked.objects.filter(
                application=app_obj,
                status_obsolete=False,
                locked=True)
            if app_locked_obj_in:
                return 2, app_locked_obj_in
            else:
                return 3, None


def get_user_lock_count(current_user):
    return ApplicationLocked.objects.filter(user_lock=current_user,
                locked=True).count()


def get_app_lock_count(app_obj):
    return ApplicationLocked.objects.filter(application=app_obj,
                locked=True).count()


def app_lock_list():
    app_lock_queryset = ApplicationLocked.objects.filter(
        locked=True).order_by('application_id').values_list('application_id', flat=True)
    app_id_locked = list(app_lock_queryset)
    return app_id_locked

def lock_by_user(queryset):
    lock_by = ''
    index = 0
    for item in queryset:
        if index==0:
            lock_by += "%s" % item.user_lock
        else:
            lock_by += ", %s" % item.user_lock
        index+=1
    return lock_by

def get_lock_status(app_obj, user_obj):
    lock_status = 1
    lock_by = None
    ret_cek_app = check_lock_app(app_obj, user_obj)

    if ret_cek_app[0]==1:
        lock_status = 0
        lock_by = lock_by_user(ret_cek_app[1])
    elif ret_cek_app[0]==2:
        lock_status = 1
        lock_by = lock_by_user(ret_cek_app[1])
    else:
        lock_status = 1

    if app_obj.status not in LOCK_STATUS_LIST:
        lock_status = 0

    #Force if admin full locked status is False
    if role_allowed(user_obj, ['admin_unlocker']):
        lock_status = 0

    # print "lock_status, lock_by: ", lock_status, lock_by
    return lock_status, lock_by


def unlocked_app(app_locked_obj, user_unlock_obj, status_to=None):
    app_locked = app_locked_obj
    if app_locked:
        app_locked.locked = False
        app_locked.user_unlock = user_unlock_obj
        if status_to:
            app_locked.status_code_unlocked = status_to

        app_locked.save()
        return app_locked


def unlocked_app_from_user(app_obj, user_obj, status_to=None):
    app_locked = ApplicationLocked.objects.get_or_none(application=app_obj,
                            user_lock=user_obj,
                            locked=True)
    print("app_locked: ", app_locked)
    if app_locked:
        if status_to:
            return unlocked_app(app_locked, user_obj, status_to)
        else:
            return unlocked_app(app_locked, user_obj)

    return None


def decode_unquote_plus(str_in):
    if str_in:
        return urllib.parse.unquote_plus(str_in).strip()
    else:
        return None


def choose_number(app_obj, collections_t0=False):
    customer_phone = Skiptrace.objects.filter(customer_id=app_obj.customer_id)\
        .order_by('id','-effectiveness')\
        .exclude(effectiveness__lt=-15)
    if app_obj.status in [ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING]:
        phones = customer_phone.filter(
            contact_source__in=['mobile_phone_number_1',
                                'mobile_phone',
                                'mobile_phone_1',
                                'mobile_phone_2',
                                'mobile_phone_3',
                                'mobile phone',
                                'mobile phone 1',
                                'mobile phone 2',
                                'mobile_phone_lain',
                                'mobile_phone1',
                                'mobile_phone2',
                                'mobile',
                                'mobile 1',
                                'mobile 2',
                                'mobile2',
                                'mobile 3',
                                'mobile aktif',
                                'App mobile phone',
                                'App_mobile_phone'])

    if app_obj.status in [ApplicationStatusCodes.DOCUMENTS_VERIFIED,
        ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING]:
        phones = customer_phone.filter(
            contact_source__contains='company')

    if app_obj.status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL and collections_t0:
        phones = customer_phone.filter(Q(
            contact_source__in=['mobile_phone_number_1',
                                'mobile_phone',
                                'mobile_phone_1',
                                'mobile_phone_2',
                                'mobile_phone_3',
                                'mobile phone',
                                'mobile phone 1',
                                'mobile phone 2',
                                'mobile_phone_lain',
                                'mobile_phone1',
                                'mobile_phone2',
                                'mobile',
                                'mobile 1',
                                'mobile 2',
                                'mobile2',
                                'mobile 3',
                                'mobile aktif',
                                'App mobile phone',
                                'App_mobile_phone']) | Q(contact_source__contains='company'))

    result = []
    if phones:
        for p in phones:
            phone_obj = {
                'skiptrace_id': p.pk,
                'contact_name': p.contact_name,
                'contact_source': p.contact_source,
                'phone_number': str(p.phone_number)
            }
            result.append(phone_obj)

    return result


def get_cashback_request(status_code):
    status_text = None
    cb_app_ids = []
    if status_code == BucketCode.CASHBACK_REQUEST:
        cb_requests = CashbackTransferTransaction.objects.filter(
            transfer_status=CashbackTransferConst.STATUS_REQUESTED).values(
            'application').annotate(Count('application'))
        cb_app_ids = [app['application'] for app in cb_requests]
        status_text = 'Cashback Request'
    elif status_code == BucketCode.CASHBACK_PENDING:
        cb_requests = CashbackTransferTransaction.objects.filter(
            transfer_status=CashbackTransferConst.STATUS_PENDING).values(
            'application').annotate(Count('application'))
        cb_app_ids = [app['application'] for app in cb_requests]
        status_text = 'Pending Cashback'
    elif status_code == BucketCode.CASHBACK_FAILED:
        cb_requests = CashbackTransferTransaction.objects.filter(
            transfer_status=CashbackTransferConst.STATUS_FAILED).values(
            'application').annotate(Count('application'))
        cb_app_ids = [app['application'] for app in cb_requests]
        status_text = 'Failed Cashback'

    return cb_app_ids, status_text
