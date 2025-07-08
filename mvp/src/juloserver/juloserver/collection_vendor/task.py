import csv
import io
import os
from builtins import map
from builtins import range
import logging
from zipfile import ZipFile

from celery import task
import math
from dateutil.relativedelta import relativedelta
from django.contrib.auth.models import User
from django.db.models.expressions import ExpressionWrapper, F
from django.db.models.fields import IntegerField

from juloserver.account.models import Account
from juloserver.collection_vendor.celery_progress import ProgressRecorder
from juloserver.collection_vendor.constant import (
    AgentAssignmentConstant,
    CollectionVendorCodes,
    CollectionVendorAssignmentConstant, CollectionAssignmentConstant
)
from juloserver.collection_vendor.models import (
    AgentAssignment,
    CollectionVendorAssignment,
    CollectionVendorRatio,
    SubBucket,
    CollectionAssignmentHistory,
    CollectionVendor,
)
from juloserver.collection_vendor.services import (
    get_current_sub_bucket,
    drop_zeros,
    check_vendor_assignment,
    get_expired_vendor_assignment,
    allocated_oldest_payment_without_active_ptp,
    allocated_to_vendor_for_payment_less_then_fifty_thousand,
    allocated_to_vendor_for_payment_last_contacted_more_thirty_days,
    allocated_to_vendor_for_last_payment_more_then_sixty_days,
    check_active_ptp_agent_assignment,
    get_loan_ids_have_waiver_already,
    get_account_ids_have_waiver_already_will_excluded_in_b5,
    allocated_oldest_account_payment_without_active_ptp,
    allocated_to_vendor_for_account_payment_less_then_fifty_thousand,
    allocated_to_vendor_for_last_account_payment_more_then_sixty_days,
    check_vendor_assignment_for_j1,
    create_record_movement_history,
    construct_data_for_send_to_vendor,
    format_and_create_single_movement_history,
    set_expired_from_vendor_b4_account_payment_reach_b5,
    check_expiration_b4_vendor_assignment_for_j1,
    process_assign_b4_account_payments_to_vendor,
    assign_new_vendor,
)
from juloserver.fdc.files import TempDir
from juloserver.julo.constants import (
    FeatureNameConst,
)
from juloserver.julo.models import Loan, Payment, PTP, FeatureSetting
from django.utils import timezone
from django.db.models import (
    Count, Q,
)
from datetime import timedelta, datetime

from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_selloff.services import calculate_remaining_principal
from juloserver.minisquad.constants import (
    RedisKey,
    IntelixTeam,
    DialerTaskStatus,
    REPAYMENT_ASYNC_REPLICA_DB,
)
from juloserver.minisquad.models import (
    VendorRecordingDetail, DialerTask, BulkVendorRecordingFileCache)
from juloserver.minisquad.services import (
    get_oldest_payment_ids_loans,
    get_oldest_unpaid_account_payment_ids,
    get_account_payment_details_for_calling,
    serialize_data_for_sent_to_vendor,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.models import (
    Skiptrace,
    Application,
    SkiptraceHistory,
    SkiptraceResultChoice
)
import urllib
from juloserver.julo.utils import get_oss_presigned_url, delete_public_file_from_oss
from django.conf import settings
from juloserver.julo.utils import upload_file_to_oss
from juloserver.minisquad.services2.dialer_related import (
    get_eligible_account_payment_for_dialer_and_vendor_qs)
from juloserver.minisquad.services2.intelix import create_history_dialer_task_event
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.monitors.notifications import (
    slack_notify_and_send_csv_files,
    send_message_normal_format,
)

logger = logging.getLogger(__name__)


@task(queue='collection_dialer_normal')
def assign_agent_for_bucket_5(agent_user_id, loan_id):
    logger.info({
        'action': 'assign_agent_for_bucket_5',
        'loan_id': loan_id,
        'status': 'Initate',
        'agent_user_id': agent_user_id
    })
    today = timezone.localtime(timezone.now())
    agent_user = User.objects.get(pk=agent_user_id)
    loan = Loan.objects.get(pk=loan_id)
    oldest_payment = loan.get_oldest_unpaid_payment()
    if not oldest_payment:
        logger.info({
            'action': 'assign_agent_for_bucket_5',
            'loan_id': loan_id,
            'status': 'Failed',
            'agent_user_id': agent_user_id
        })
        return

    existing_agent_assignment = AgentAssignment.objects.filter(
        payment=oldest_payment, is_active_assignment=True
    )
    if existing_agent_assignment:
        logger.info({
            'action': 'assign_agent_for_bucket_5_j1',
            'payment': oldest_payment,
            'status': 'Failed',
            'agent_user_id': agent_user_id,
            'reason': 'because theres still active agent assignment'
        })
        return

    sub_bucket_current = get_current_sub_bucket(oldest_payment)
    format_and_create_single_movement_history(
        oldest_payment, agent_user,
        reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
            'RPC_ELIGIBLE_CALLING_STATUS'],
        is_julo_one=False
    )
    AgentAssignment.objects.create(
        agent=agent_user,
        payment=oldest_payment,
        sub_bucket_assign_time=sub_bucket_current,
        dpd_assign_time=oldest_payment.due_late_days,
        assign_time=today,
    )
    logger.info({
        'action': 'assign_agent_for_bucket_5',
        'status': 'Success',
        'loan_id': loan_id,
        'agent_user_id': agent_user_id,
    })


@task(queue='collection_dialer_normal')
def assign_agent_for_julo_one_bucket_5(agent_user_id, account_payment_id):
    logger.info({
        'action': 'assign_agent_for_julo_one_bucket_5',
        'account_payment_id': account_payment_id,
        'status': 'Initate',
        'agent_user_id': agent_user_id
    })
    today = timezone.localtime(timezone.now())
    agent_user = User.objects.get(pk=agent_user_id)
    account_payment = AccountPayment.objects.get_or_none(
        pk=account_payment_id)
    if not account_payment:
        logger.info({
            'action': 'assign_agent_for_julo_one_bucket_5',
            'account_payment': account_payment_id,
            'status': 'Failed',
            'agent_user_id': agent_user_id
        })
        return

    existing_agent_assignment = AgentAssignment.objects.filter(
        account_payment=account_payment, is_active_assignment=True
    )
    if existing_agent_assignment:
        logger.info({
            'action': 'assign_agent_for_julo_one_bucket_5',
            'account_payment': account_payment_id,
            'status': 'Failed',
            'agent_user_id': agent_user_id,
            'reason': 'because theres still active agent assignment'
        })
        return

    sub_bucket_current = get_current_sub_bucket(account_payment, is_julo_one=True)
    if not sub_bucket_current:
        logger.info({
            'action': 'assign_agent_for_julo_one_bucket_5',
            'account_payment': account_payment_id,
            'status': 'Failed',
            'agent_user_id': agent_user_id,
            'reason': 'because sub bucket False, that mean this Account '
                      'payment not eligible yet to B5'
        })
        return

    format_and_create_single_movement_history(
        account_payment, agent_user,
        reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
            'RPC_ELIGIBLE_CALLING_STATUS'],
        is_julo_one=True
    )
    AgentAssignment.objects.create(
        agent=agent_user,
        account_payment=account_payment,
        sub_bucket_assign_time=sub_bucket_current,
        dpd_assign_time=account_payment.dpd,
        assign_time=today,
    )

    logger.info({
        'action': 'assign_agent_for_julo_one_bucket_5',
        'status': 'Success',
        'account_payment': account_payment_id,
        'agent_user_id': agent_user_id,
    })


@task(queue='collection_dialer_normal')
def process_unassignment_when_paid(payment_id):
    payment = Payment.objects.get_or_none(id=payment_id)
    if not payment or payment.bucket_number_special_case != 5:
        return

    next_unpaid_payment = payment.get_next_unpaid_payment()
    sub_bucket_current = None
    if next_unpaid_payment:
        sub_bucket_current = get_current_sub_bucket(next_unpaid_payment)

    agent_assignments = AgentAssignment.objects.filter(
        payment=payment, is_active_assignment=True)
    vendor_assignments = CollectionVendorAssignment.objects.filter(
        payment=payment, is_active_assignment=True)
    if not agent_assignments and not vendor_assignments:
        return

    today = timezone.localtime(timezone.now())
    is_already_new_assign = False
    if agent_assignments:
        agent_assignment = agent_assignments.last()
        # unassign old active assignment
        # None means inhouse
        format_and_create_single_movement_history(
            payment, None,
            reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS['PAID'],
            is_julo_one=False
        )
        agent_assignments.update(
            is_active_assignment=False, unassign_time=today)
        # set next agent to unpaid payment if still have time
        if not next_unpaid_payment:
            return
        allocated_days = (today.date() - agent_assignment.assign_time.date()).days
        if not allocated_days < 30:
            return
        is_next_payment_already_assign = AgentAssignment.objects.filter(
            payment=next_unpaid_payment,
            is_active_assignment=True
        ).exists()
        if is_next_payment_already_assign:
            return
        format_and_create_single_movement_history(
            next_unpaid_payment, agent_assignment.agent,
            reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                'ACCOUNT_SYSTEM_TRANSFERRED_AGENT'],
            is_julo_one=False
        )
        AgentAssignment.objects.create(
            agent=agent_assignment.agent,
            payment=next_unpaid_payment,
            sub_bucket_assign_time=sub_bucket_current,
            dpd_assign_time=next_unpaid_payment.due_late_days,
            assign_time=agent_assignment.assign_time,
        )
        is_already_new_assign = True
    if vendor_assignments:
        vendor_assignment = vendor_assignments.last()
        format_and_create_single_movement_history(
            payment, None,
            reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS['PAID'],
            is_julo_one=False
        )
        vendor_assignments.update(
            is_active_assignment=False, unassign_time=today, collected_ts=today)
        # assign next payment to existing vendor
        if not next_unpaid_payment:
            return
        allocated_days = (today.date() - vendor_assignment.assign_time.date()).days
        remaining_vendor_stay_threshold = vendor_assignment.sub_bucket_assign_time.\
            vendor_type_expiration_days
        if allocated_days >= remaining_vendor_stay_threshold:
            return

        is_next_payment_already_assign = CollectionVendorAssignment.objects.filter(
            payment=next_unpaid_payment,
            is_active_assignment=True
        ).exists()
        if is_next_payment_already_assign or is_already_new_assign:
            return

        vendor = vendor_assignment.vendor
        vendor_configuration = vendor_assignment.vendor_configuration
        if not vendor_assignment.vendor.is_active:
            vendor_type = vendor_assignment.vendor_configuration.vendor_types
            collection_vendor_ratio = CollectionVendorRatio.objects.filter(
                vendor_types=vendor_type).exclude(collection_vendor__is_active=False).last()
            vendor = collection_vendor_ratio.collection_vendor
            vendor_configuration = collection_vendor_ratio

        format_and_create_single_movement_history(
            next_unpaid_payment, vendor,
            reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                'ACCOUNT_SYSTEM_TRANSFERRED_VENDOR'],
            is_julo_one=False
        )
        CollectionVendorAssignment.objects.create(
            vendor=vendor,
            vendor_configuration=vendor_configuration,
            payment=next_unpaid_payment,
            sub_bucket_assign_time=sub_bucket_current,
            dpd_assign_time=next_unpaid_payment.due_late_days,
            assign_time=vendor_assignment.assign_time
        )


@task(queue='collection_dialer_high')
def allocate_payments_to_collection_vendor_for_bucket_5_less_then_91(excluded_payment_ids):
    redisClient = get_redis_client()
    cached_oldest_payment_ids = redisClient.get_list(RedisKey.OLDEST_PAYMENT_IDS)
    if not cached_oldest_payment_ids:
        oldest_payment_ids = get_oldest_payment_ids_loans()
        if oldest_payment_ids:
            redisClient.set_list(
                RedisKey.OLDEST_PAYMENT_IDS, oldest_payment_ids, timedelta(hours=4))
    else:
        oldest_payment_ids = list(map(int, cached_oldest_payment_ids))

    sub_bucket = SubBucket.sub_bucket_five(1)
    excluded_timestamp = datetime(2020, 11, 30, 11, 30, 20)
    excluded_b6 = CollectionVendorAssignment.objects.filter(
        unassign_time=excluded_timestamp, payment__isnull=False).values_list(
        "payment_id", flat=True)
    assigned_collection_vendor_loan_ids = CollectionVendorAssignment.objects.filter(
        is_active_assignment=True,
        payment__isnull=False
    ).distinct("payment__loan_id").values_list("payment__loan_id", flat=True)
    loan_ids_have_waiver_request = get_loan_ids_have_waiver_already()
    # assign to vendor if payment <= 50000
    qs = Payment.objects.not_paid_active().filter(account_payment_id__isnull=True)
    payments_b5_1_less_then_91 = qs.get_sub_bucket_5_1_special_case(
        sub_bucket.start_dpd - 1).filter(id__in=oldest_payment_ids).exclude(
        id__in=(excluded_payment_ids + list(excluded_b6)))\
        .exclude(loan_id__in=list(loan_ids_have_waiver_request) + list(
            assigned_collection_vendor_loan_ids))
    allocated_to_vendor_for_payment_less_then_50000 = \
        allocated_to_vendor_for_payment_less_then_fifty_thousand(
            payments_b5_1_less_then_91)

    today = timezone.localtime(timezone.now()).date()
    payments_b5_1_ever_enter = payments_b5_1_less_then_91.exclude(
        id__in=allocated_to_vendor_for_payment_less_then_50000)
    check_for_last_contacted_payment = []
    check_for_last_payment_payment = []
    for payment in payments_b5_1_ever_enter:
        previous_payment = payment.get_previous_payment()
        if not hasattr(previous_payment, 'is_paid') or not previous_payment.is_paid:
            continue

        paid_at_dpd = (previous_payment.paid_date - payment.due_date).days
        current_payment_entered_b5_date = payment.due_date + relativedelta(
            days=paid_at_dpd + 1)
        last_contacted_date_should_be_check_on = current_payment_entered_b5_date + relativedelta(
            days=30)
        if last_contacted_date_should_be_check_on == today:
            check_for_last_contacted_payment.append(payment)
            continue

        last_payment_should_be_check_on = current_payment_entered_b5_date + relativedelta(
            days=60)
        if last_payment_should_be_check_on == today:
            check_for_last_payment_payment.append(payment)

    allocated_payment_to_vendor_last_contacted_ids = \
        allocated_to_vendor_for_payment_last_contacted_more_thirty_days(
            check_for_last_contacted_payment)

    allocated_payment_with_last_payment_gte_60_ids =\
        allocated_to_vendor_for_last_payment_more_then_sixty_days(
            check_for_last_payment_payment)

    all_allocated_vendor = []

    for payment_id in allocated_to_vendor_for_payment_less_then_50000 + \
            allocated_payment_to_vendor_last_contacted_ids + \
            allocated_payment_with_last_payment_gte_60_ids:
        all_allocated_vendor.append(dict(payment_id=payment_id, type='inhouse_to_vendor'))

    return construct_data_for_send_to_vendor(
        allocated_to_vendor_for_payment_less_then_50000,
        allocated_payment_to_vendor_last_contacted_ids,
        allocated_payment_with_last_payment_gte_60_ids,
        is_for_julo_one=False
    )


@task(queue="collection_dialer_high")
def allocate_payments_to_collection_vendor_for_bucket_5():
    redisClient = get_redis_client()
    cached_oldest_payment_ids = redisClient.get_list(
        RedisKey.OLDEST_PAYMENT_IDS)
    if not cached_oldest_payment_ids:
        oldest_payment_ids = get_oldest_payment_ids_loans()
        if oldest_payment_ids:
            redisClient.set_list(
                RedisKey.OLDEST_PAYMENT_IDS, oldest_payment_ids, timedelta(hours=4))
    else:
        oldest_payment_ids = list(map(int, cached_oldest_payment_ids))

    allocated_from_agent_to_vendor_assignment_payment_ids = []
    sub_bucket = SubBucket.sub_bucket_five(1)
    # select assigned payment on vendor
    excluded_timestamp = datetime(2020, 11, 30, 11, 30, 20)
    excluded_b6 = CollectionVendorAssignment.objects.filter(
        unassign_time=excluded_timestamp,
        payment__isnull=False
    ).values_list("payment_id", flat=True)
    assigned_collection_vendor_loan_ids = CollectionVendorAssignment.objects.filter(
        is_active_assignment=True, payment__isnull=False
    ).distinct("payment__loan_id").values_list("payment__loan_id", flat=True)
    excluded_payment_ids = list(excluded_b6)
    loan_ids_have_waiver_request = get_loan_ids_have_waiver_already()
    excluded_loan_ids = list(loan_ids_have_waiver_request) +\
        list(assigned_collection_vendor_loan_ids)
    qs = Payment.objects.not_paid_active().filter(account_payment_id__isnull=True)
    payments_b5_1 = qs.get_sub_bucket_5_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd)\
        .exclude(id__in=excluded_payment_ids)\
        .exclude(loan_id__in=excluded_loan_ids)
    # why -1 because dpd 91 its already handled
    payments_b5_1_dpd_less_then_91 = qs.get_sub_bucket_5_1_special_case(
        sub_bucket.start_dpd - 1).filter(id__in=oldest_payment_ids)\
        .exclude(loan_id__in=excluded_loan_ids).values_list("id", flat=True)

    passed_threshold_agent = AgentAssignment.objects.filter(
        is_active_assignment=True,
        payment_id__in=list(payments_b5_1.values_list("id", flat=True)) +
        list(payments_b5_1_dpd_less_then_91),
        sub_bucket_assign_time=sub_bucket
    ).values('agent').annotate(
        total=Count('payment')).filter(
        total__gt=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_1)

    for agent in passed_threshold_agent:
        assigned_payments = AgentAssignment.objects.filter(
            agent_id=agent['agent'], is_active_assignment=True,
            payment_id__in=(list(payments_b5_1.values_list("id", flat=True)) +
                            list(payments_b5_1_dpd_less_then_91)),
        ).order_by('assign_time')
        # check oldest payment have active PTP
        should_allocated_count = agent['total'] - AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_1
        allocated_from_agent_to_vendor_assignment_payment_ids += \
            allocated_oldest_payment_without_active_ptp(assigned_payments, should_allocated_count)

    assigned_payment_to_agent = AgentAssignment.objects.filter(
        is_active_assignment=True, payment__isnull=False
    ).values_list("payment_id", flat=True)
    excluded_payment_list = list(assigned_payment_to_agent) + \
        allocated_from_agent_to_vendor_assignment_payment_ids

    # run checking for dpd < 91
    allocated_payment_less_than_91 = \
        allocate_payments_to_collection_vendor_for_bucket_5_less_then_91(
            excluded_payment_list)

    payments_b5_1_excluded_assigned = payments_b5_1.filter(id__in=oldest_payment_ids).exclude(
        id__in=excluded_payment_list)
    # assign to vendor if payment <= 50000
    allocated_to_vendor_for_payment_less_then_50000 = \
        allocated_to_vendor_for_payment_less_then_fifty_thousand(
            payments_b5_1_excluded_assigned)
    # Last contacted  date >= 30 days
    due_date_plus_120 = timezone.localtime(timezone.now() - timedelta(days=120)).date()
    payments_b5_1_excluded_assigned = payments_b5_1_excluded_assigned.exclude(
        id__in=allocated_to_vendor_for_payment_less_then_50000
    )
    payments_with_dpd_120 = payments_b5_1_excluded_assigned.filter(due_date__lte=due_date_plus_120)
    assigned_payment_to_vendor_last_contacted = \
        allocated_to_vendor_for_payment_last_contacted_more_thirty_days(payments_with_dpd_120)

    # last payment >= 60 checking for dpd 150
    due_date_plus_150 = timezone.localtime(timezone.now() - timedelta(days=150)).date()
    payments_b5_1_assigned_excluded = payments_b5_1_excluded_assigned.exclude(
        id__in=assigned_payment_to_vendor_last_contacted
    )
    payments_with_dpd_150 = payments_b5_1_assigned_excluded.filter(due_date__lte=due_date_plus_150)
    allocated_payment_with_last_payment_gte_60 = \
        allocated_to_vendor_for_last_payment_more_then_sixty_days(payments_with_dpd_150)

    # combine all allocated payments
    all_allocated_vendor = construct_data_for_send_to_vendor(
        allocated_to_vendor_for_payment_less_then_50000,
        assigned_payment_to_vendor_last_contacted,
        allocated_payment_with_last_payment_gte_60,
        allocated_from_agent_to_vendor_assignment_payment_ids,
        agent_threshold=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_1,
        is_for_julo_one=False
    )
    all_allocated_vendor = all_allocated_vendor + allocated_payment_less_than_91
    assign_payments_to_vendor.delay(
        all_allocated_vendor, CollectionVendorCodes.VENDOR_TYPES.get('special'),
        IntelixTeam.JULO_B5
    )


@task(queue='collection_dialer_high')
def allocate_payments_to_collection_vendor_for_bucket_6_1():
    """
    this early return because already have sorting system fot this bucket
    """
    return True
    redisClient = get_redis_client()
    cached_oldest_payment_ids = redisClient.get_list(RedisKey.OLDEST_PAYMENT_IDS)
    if not cached_oldest_payment_ids:
        oldest_payment_ids = get_oldest_payment_ids_loans()
        if oldest_payment_ids:
            redisClient.set_list(
                RedisKey.OLDEST_PAYMENT_IDS,
                oldest_payment_ids, timedelta(hours=4))
    else:
        oldest_payment_ids = list(map(int, cached_oldest_payment_ids))

    allocated_from_agent_to_vendor_assignment_payment_ids = []
    sub_bucket = SubBucket.sub_bucket_six(1)
    # select assigned payment on vendor
    excluded_timestamp = datetime(2020, 11, 30, 11, 30, 20)
    excluded_b6 = CollectionVendorAssignment.objects.filter(
        unassign_time=excluded_timestamp).values_list("payment_id", flat=True)
    assigned_collection_vendor_loan_ids = CollectionVendorAssignment.objects.filter(
        is_active_assignment=True, payment__isnull=False
    ).distinct("payment__loan_id").values_list("payment__loan_id", flat=True)
    excluded_payment_ids = list(excluded_b6)
    loan_ids_have_waiver_request = get_loan_ids_have_waiver_already()
    qs = Payment.objects.not_paid_active().filter(account_payment_id__isnull=True)
    payments_b5_2 = qs.get_sub_bucket_5_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd)\
        .exclude(id__in=excluded_payment_ids)\
        .exclude(loan_id__in=list(loan_ids_have_waiver_request) + list(
            assigned_collection_vendor_loan_ids))
    passed_threshold_agent = AgentAssignment.objects.filter(
        is_active_assignment=True,
        payment_id__in=list(payments_b5_2.values_list("id", flat=True)),
        sub_bucket_assign_time=sub_bucket
    ).values('agent').annotate(
        total=Count('payment')).filter(
        total__gt=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_2)
    for agent in passed_threshold_agent:
        assigned_payments = AgentAssignment.objects.filter(
            agent_id=agent['agent'], is_active_assignment=True,
            payment_id__in=list(payments_b5_2.values_list("id", flat=True)),
        ).order_by('assign_time')
        should_allocated_count = agent['total'] - AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_2
        allocated_from_agent_to_vendor_assignment_payment_ids += \
            allocated_oldest_payment_without_active_ptp(assigned_payments, should_allocated_count)

    assigned_payment_to_agent = AgentAssignment.objects.filter(
        is_active_assignment=True, payment__isnull=False
    ).values_list("payment_id", flat=True)
    payments_b5_2_excluded_assigned = payments_b5_2.filter(
        id__in=oldest_payment_ids).exclude(
        id__in=list(assigned_payment_to_agent) +
            allocated_from_agent_to_vendor_assignment_payment_ids)
    # assign to vendor if payment <= 50000
    allocated_to_vendor_for_payment_less_then_50000 = \
        allocated_to_vendor_for_payment_less_then_fifty_thousand(
            payments_b5_2_excluded_assigned)

    # Last contacted  date >= 30 days
    due_date_plus_210 = timezone.localtime(timezone.now() - timedelta(days=210)).date()
    payments_b5_2_excluded_assigned = payments_b5_2_excluded_assigned.exclude(
        id__in=allocated_to_vendor_for_payment_less_then_50000
    )
    payments_with_dpd_210 = payments_b5_2_excluded_assigned.filter(due_date__lte=due_date_plus_210)
    assigned_payment_to_vendor_last_contacted = \
        allocated_to_vendor_for_payment_last_contacted_more_thirty_days(payments_with_dpd_210)
    # last payment >= 60 checking for dpd 150
    due_date_plus_240 = timezone.localtime(timezone.now() - timedelta(days=240)).date()
    payments_b5_2_assigned_excluded = payments_b5_2_excluded_assigned.exclude(
        id__in=assigned_payment_to_vendor_last_contacted
    )
    payments_with_dpd_240 = payments_b5_2_assigned_excluded.filter(due_date__lte=due_date_plus_240)
    allocated_payment_with_last_payment_gte_60 = \
        allocated_to_vendor_for_last_payment_more_then_sixty_days(payments_with_dpd_240)
    # combine all allocated payments
    all_allocated_vendor = construct_data_for_send_to_vendor(
        allocated_to_vendor_for_payment_less_then_50000,
        assigned_payment_to_vendor_last_contacted,
        allocated_payment_with_last_payment_gte_60,
        allocated_from_agent_to_vendor_assignment_payment_ids,
        agent_threshold=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_2,
        is_for_julo_one=False
    )
    assign_payments_to_vendor.delay(
        all_allocated_vendor,
        CollectionVendorCodes.VENDOR_TYPES.get('general'), IntelixTeam.JULO_B6_1
    )


@task(queue='collection_dialer_high')
def allocate_payments_to_collection_vendor_for_bucket_6_2():
    redisClient = get_redis_client()
    cached_oldest_payment_ids = redisClient.get_list(RedisKey.OLDEST_PAYMENT_IDS)
    if not cached_oldest_payment_ids:
        oldest_payment_ids = get_oldest_payment_ids_loans()
        if oldest_payment_ids:
            redisClient.set_list(
                RedisKey.OLDEST_PAYMENT_IDS, oldest_payment_ids,
                timedelta(hours=4))
    else:
        oldest_payment_ids = list(map(int, cached_oldest_payment_ids))

    allocated_from_agent_to_vendor_assignment_payment_ids = []
    sub_bucket = SubBucket.sub_bucket_six(2)
    # select assigned payment on vendor
    excluded_timestamp = datetime(2020, 11, 30, 11, 30, 20)
    excluded_b6 = CollectionVendorAssignment.objects.filter(
        unassign_time=excluded_timestamp).values_list("payment_id", flat=True)
    assigned_collection_vendor_loan_ids = CollectionVendorAssignment.objects.filter(
        is_active_assignment=True, payment__isnull=False
    ).distinct("payment__loan_id").values_list("payment__loan_id", flat=True)
    excluded_payment_ids = list(excluded_b6)
    loan_ids_have_waiver_request = get_loan_ids_have_waiver_already()
    qs = Payment.objects.not_paid_active().filter(account_payment_id__isnull=True)
    payments_b5_3 = qs.get_sub_bucket_5_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd)\
        .exclude(id__in=excluded_payment_ids)\
        .exclude(loan_id__in=list(loan_ids_have_waiver_request) + list(
            assigned_collection_vendor_loan_ids))
    passed_threshold_agent = AgentAssignment.objects.filter(
        is_active_assignment=True,
        payment_id__in=list(payments_b5_3.values_list("id", flat=True)),
        sub_bucket_assign_time=sub_bucket
    ).values('agent').annotate(
        total=Count('payment')).filter(
        total__gt=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_3)
    for agent in passed_threshold_agent:
        assigned_payments = AgentAssignment.objects.filter(
            agent_id=agent['agent'], is_active_assignment=True,
            payment_id__in=list(payments_b5_3.values_list("id", flat=True)),
        ).order_by('assign_time')
        # check oldest payment have active PTP
        should_allocated_count = agent['total'] - AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_3
        allocated_from_agent_to_vendor_assignment_payment_ids += \
            allocated_oldest_payment_without_active_ptp(assigned_payments, should_allocated_count)

    assigned_payment_to_agent = AgentAssignment.objects.filter(
        is_active_assignment=True
    ).values_list("payment_id", flat=True)
    payments_b5_3_excluded_assigned = payments_b5_3.filter(
        id__in=oldest_payment_ids).exclude(
        id__in=list(assigned_payment_to_agent) +
            allocated_from_agent_to_vendor_assignment_payment_ids)
    # assign to vendor if payment <= 50000
    allocated_to_vendor_for_payment_less_then_50000 = \
        allocated_to_vendor_for_payment_less_then_fifty_thousand(
            payments_b5_3_excluded_assigned)

    # Last contacted  date >= 30 days
    due_date_plus_300 = timezone.localtime(timezone.now() - timedelta(days=300)).date()
    payments_b5_3_excluded_assigned = payments_b5_3_excluded_assigned.exclude(
        id__in=allocated_to_vendor_for_payment_less_then_50000
    )
    payments_with_dpd_300 = payments_b5_3_excluded_assigned.filter(due_date__lte=due_date_plus_300)
    assigned_payment_to_vendor_last_contacted = \
        allocated_to_vendor_for_payment_last_contacted_more_thirty_days(payments_with_dpd_300)

    # last payment >= 60 checking for dpd 150
    due_date_plus_330 = timezone.localtime(timezone.now() - timedelta(days=330)).date()
    payments_b5_3_assigned_excluded = payments_b5_3_excluded_assigned.exclude(
        id__in=assigned_payment_to_vendor_last_contacted
    )
    payments_with_dpd_330 = payments_b5_3_assigned_excluded.filter(due_date__lte=due_date_plus_330)
    allocated_payment_with_last_payment_gte_60 = \
        allocated_to_vendor_for_last_payment_more_then_sixty_days(payments_with_dpd_330)
    # combine all allocated payments
    all_allocated_vendor = construct_data_for_send_to_vendor(
        allocated_to_vendor_for_payment_less_then_50000,
        assigned_payment_to_vendor_last_contacted,
        allocated_payment_with_last_payment_gte_60,
        allocated_from_agent_to_vendor_assignment_payment_ids,
        agent_threshold=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_3,
        is_for_julo_one=False
    )
    assign_payments_to_vendor.delay(
        all_allocated_vendor, CollectionVendorCodes.VENDOR_TYPES.get('general'),
        IntelixTeam.JULO_B6_2
    )


@task(queue='collection_dialer_high')
def allocate_payments_to_collection_vendor_for_bucket_6_3():
    redisClient = get_redis_client()
    cached_oldest_payment_ids = redisClient.get_list(RedisKey.OLDEST_PAYMENT_IDS)
    if not cached_oldest_payment_ids:
        oldest_payment_ids = get_oldest_payment_ids_loans()
        if oldest_payment_ids:
            redisClient.set_list(RedisKey.OLDEST_PAYMENT_IDS,
                                 oldest_payment_ids, timedelta(hours=4))
    else:
        oldest_payment_ids = list(map(int, cached_oldest_payment_ids))

    sub_bucket = SubBucket.sub_bucket_six(3)
    excluded_timestamp = datetime(2020, 11, 30, 11, 30, 20)
    excluded_b6 = CollectionVendorAssignment.objects.filter(
        unassign_time=excluded_timestamp).values_list("payment_id", flat=True)
    assigned_collection_vendor_loan_ids = CollectionVendorAssignment.objects.filter(
        is_active_assignment=True, payment__isnull=False
    ).distinct("payment__loan_id").values_list("payment__loan_id", flat=True)
    excluded_payment_ids = list(excluded_b6)
    loan_ids_have_waiver_request = get_loan_ids_have_waiver_already()
    qs = Payment.objects.not_paid_active().filter(account_payment_id__isnull=True)
    payments_ids_b5_4 = qs.get_sub_bucket_5_by_range(
        sub_bucket.start_dpd, sub_bucket.end_dpd).filter(
        id__in=oldest_payment_ids
    ).exclude(id__in=excluded_payment_ids)\
        .exclude(loan_id__in=list(loan_ids_have_waiver_request) + list(
            assigned_collection_vendor_loan_ids))\
        .extra(
        select={'type': "'inhouse_to_vendor'", 'payment_id': 'payment_id', 'reason': '%s'},
        select_params=(CollectionAssignmentConstant.ASSIGNMENT_REASONS[
            'ACCOUNT_SYSTEM_TRANSFERRED_VENDOR'],))\
        .values("payment_id", "type", "reason")
    assign_payments_to_vendor.delay(
        list(payments_ids_b5_4), CollectionVendorCodes.VENDOR_TYPES.get('final'),
        IntelixTeam.JULO_B6_3
    )


@task(queue='collection_dialer_normal')
def set_settled_status_for_bucket_6_sub_3_and_4():
    sub_bucket_3 = SubBucket.sub_bucket_six(3)
    sub_bucket_4 = SubBucket.sub_bucket_six(4)
    qs = Payment.objects.normal().filter(account_payment_id__isnull=True)
    payment_dpd_320_until_dpd_721 = qs.get_sub_bucket_5_by_range(
        sub_bucket_3.start_dpd, sub_bucket_4.start_dpd)
    paid_off_loan_ids = payment_dpd_320_until_dpd_721.paid().order_by(
        'loan', '-id').distinct('loan').values_list('loan_id', flat=True)
    loan_ids_have_refinancing_request = LoanRefinancingRequest.objects.filter(
        loan_id__in=paid_off_loan_ids,
        status=CovidRefinancingConst.STATUSES.activated,
        product_type=CovidRefinancingConst.PRODUCTS.r4
    ).values_list('loan_id', flat=True)
    loan_ids_dont_have_refinancing_request = list(
        set(list(paid_off_loan_ids)) - set(list(loan_ids_have_refinancing_request)))
    # update is_settled_1 = True
    Loan.objects.filter(id__in=loan_ids_have_refinancing_request).update(
        is_settled_1=True, is_settled_2=False)
    # update is_settled_2 = True
    Loan.objects.filter(id__in=loan_ids_dont_have_refinancing_request).update(
        is_settled_2=True, is_settled_1=False)
    # unpaid loan
    unpaid_loan_ids = payment_dpd_320_until_dpd_721.filter(loan__is_settled_1__isnull=True)\
        .order_by('loan', '-id').distinct('loan').exclude(
        id__in=list(loan_ids_have_refinancing_request) +
            list(loan_ids_dont_have_refinancing_request))\
        .values_list('loan_id', flat=True)
    Loan.objects.filter(id__in=unpaid_loan_ids).update(is_settled_2=False, is_settled_1=False)
    # j1
    j1_qs = AccountPayment.objects.normal()
    account_ids_dpd_320_until_dpd_721 = j1_qs.paid().annotate(
        paid_at_dpd=ExpressionWrapper(
            F('paid_date') - F('due_date'),
            output_field=IntegerField())
    ).filter(
        paid_at_dpd__gte=sub_bucket_3.start_dpd,
        paid_at_dpd__lte=sub_bucket_4.start_dpd
    ).distinct('account').values_list('account_id', flat=True)
    account_id_is_settled = []
    account_id_not_settled = []
    for account_id in account_ids_dpd_320_until_dpd_721:
        loan_with_status_not_paid_off = Loan.objects.filter(
            ~Q(loan_status_id=LoanStatusCodes.PAID_OFF), account_id=account_id).count()
        if loan_with_status_not_paid_off > 0:
            continue

        # set is_settled_1
        loan_ids_have_refinancing_request = LoanRefinancingRequest.objects.filter(
            account_id=account_id,
            status=CovidRefinancingConst.STATUSES.activated,
            product_type=CovidRefinancingConst.PRODUCTS.r4
        ).count()
        if loan_ids_have_refinancing_request > 0:
            account_id_is_settled.append(account_id)
        else:
            account_id_not_settled.append(account_id)

    Account.objects.filter(id__in=account_id_is_settled).update(
        is_settled_1=True, is_settled_2=False
    )
    Account.objects.filter(id__in=account_id_not_settled).update(
        is_settled_1=False, is_settled_2=True
    )


@task(queue='collection_dialer_normal')
def set_is_warehouse_status_for_bucket_6_sub_4():
    redisClient = get_redis_client()
    cached_oldest_payment_ids = redisClient.get_list(RedisKey.OLDEST_PAYMENT_IDS)
    if not cached_oldest_payment_ids:
        oldest_payment_ids = get_oldest_payment_ids_loans()
        if oldest_payment_ids:
            redisClient.set_list(RedisKey.OLDEST_PAYMENT_IDS, oldest_payment_ids,
                                 timedelta(hours=4))
    else:
        oldest_payment_ids = list(map(int, cached_oldest_payment_ids))

    sub_bucket = SubBucket.sub_bucket_six(4)
    qs = Payment.objects.not_paid_active().filter(
        account_payment_id__isnull=True)
    payments_b5_5 = qs.get_sub_bucket_5_by_range(sub_bucket.start_dpd).filter(
        id__in=oldest_payment_ids).exclude(
        loan__loan_status_id__in=(
            LoanStatusCodes.PAID_OFF, LoanStatusCodes.SELL_OFF,
            LoanStatusCodes.RENEGOTIATED))
    loan_ids_is_warehouse_1 = []
    loan_ids_is_warehouse_2 = []
    for payment in payments_b5_5:
        loan = payment.loan
        total_remaining_principal = calculate_remaining_principal(loan)
        if total_remaining_principal > 0:
            loan_ids_is_warehouse_1.append(loan.id)
        else:
            loan_ids_is_warehouse_2.append(loan.id)

    # update is_warehouse_1 = True
    Loan.objects.filter(id__in=loan_ids_is_warehouse_1).update(
        is_warehouse_1=True, is_warehouse_2=False)
    # update is_warehouse_2 = True
    Loan.objects.filter(id__in=loan_ids_is_warehouse_2).update(
        is_warehouse_2=True, is_warehouse_1=False)

    # j1 product
    cached_oldest_account_payment_ids = redisClient.get_list(
        RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS)
    if not cached_oldest_account_payment_ids:
        oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
        if oldest_account_payment_ids:
            redisClient.set_list(
                RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS, oldest_account_payment_ids, timedelta(hours=4))
    else:
        oldest_account_payment_ids = list(map(int, cached_oldest_account_payment_ids))

    j1_qs = AccountPayment.objects.not_paid_active()
    account_ids_b6_4 = j1_qs.get_bucket_6_by_range(
        sub_bucket.start_dpd).filter(
        id__in=oldest_account_payment_ids).distinct('account').values_list('account_id', flat=True)
    account_is_warehouse_1 = []
    account_not_is_warehouse_1 = []
    for account_id in account_ids_b6_4:
        loans = Loan.objects.filter(
            account_id=account_id).exclude(
            loan_status_id__in=(
                LoanStatusCodes.PAID_OFF, LoanStatusCodes.SELL_OFF,
                LoanStatusCodes.RENEGOTIATED))
        if not loans:
            continue
        total_remaining_principal_account = 0
        for loan in loans:
            total_remaining_principal_account = calculate_remaining_principal(loan)
            if total_remaining_principal_account > 0:
                account_is_warehouse_1.append(account_id)
                break
        if total_remaining_principal_account == 0:
            account_not_is_warehouse_1.append(account_id)

    Account.objects.filter(id__in=account_is_warehouse_1).update(
        is_warehouse_1=True, is_warehouse_2=False)
    Account.objects.filter(id__in=account_not_is_warehouse_1).update(
        is_warehouse_1=False, is_warehouse_2=True)


def trigger_chain_b5_assignment(intelix_team):
    if intelix_team == IntelixTeam.JULO_B5:
        allocate_payments_to_collection_vendor_for_bucket_6_1.delay()
    elif intelix_team == IntelixTeam.JULO_B6_1:
        allocate_payments_to_collection_vendor_for_bucket_6_2.delay()
    elif intelix_team == IntelixTeam.JULO_B6_2:
        allocate_bucket_5_account_payments_to_collection_vendor.delay()


@task(queue='collection_dialer_high')
def assign_payments_to_vendor(data_payments, vendor_type, intelix_team=None, is_trigger_chain=True):
    data_payments = serialize_data_for_sent_to_vendor(data_payments, is_mtl=True)
    if not data_payments:
        if is_trigger_chain:
            trigger_chain_b5_assignment(intelix_team)
        return

    collection_vendor_ratios = CollectionVendorRatio.objects.filter(
        **{'vendor_types': vendor_type, 'collection_vendor__is_active': True,
           'collection_vendor__is_{}'.format(vendor_type.lower()): True
           }
    )
    total_data = len(data_payments)
    today = timezone.localtime(timezone.now()).date()
    history_movement_record_data = []
    for collection_vendor_ratio in collection_vendor_ratios:

        if not collection_vendor_ratio.collection_vendor.is_active:
            continue

        assigned_payments_count = collection_vendor_ratio.account_distribution_ratio * total_data

        if isinstance(assigned_payments_count, float):
            ratios = collection_vendor_ratios.exclude(
                pk=collection_vendor_ratio.id
            ).values_list('account_distribution_ratio', flat=True)

            total_payments = []

            for ratio in ratios:
                tmp_total_payment = drop_zeros(ratio * total_data)
                if isinstance(tmp_total_payment, float):
                    total_payments.append(tmp_total_payment)

            if any(assigned_payments_count > total_payment for total_payment in total_payments):
                assigned_payments_count = int(math.ceil(assigned_payments_count))
            else:
                assigned_payments_count = int(math.floor(assigned_payments_count))

        if assigned_payments_count < 1:
            recount_assigned_payment_count = int(math.ceil(
                collection_vendor_ratio.account_distribution_ratio * total_data))
            if recount_assigned_payment_count >= 1:
                assigned_payments_count = recount_assigned_payment_count

        for i in range(assigned_payments_count):
            if not data_payments:
                break
            data_payment = data_payments.pop()
            payment = Payment.objects.get_or_none(pk=data_payment['payment_id'])

            if payment:
                sub_bucket = get_current_sub_bucket(payment)
                is_transferred_from_other = \
                    True if 'inhouse_to_vendor' != data_payment['type'] else False
                # None means inhouse
                old_assignment = None

                if data_payment['type'] == 'agent_to_vendor':
                    agent_assignment = AgentAssignment.objects.filter(
                        payment=payment,
                        is_active_assignment=True
                    ).last()
                    if agent_assignment:
                        agent_assignment.update_safely(is_active_assignment=False)
                        old_assignment = agent_assignment.agent

                elif data_payment['type'] == 'vendor_to_vendor':
                    old_vendor_assignment = CollectionVendorAssignment.objects.filter(
                        payment=payment,
                        unassign_time__date=today
                    ).last()
                    if old_vendor_assignment:
                        old_assignment = old_vendor_assignment.vendor
                # prevent double assignment
                if CollectionVendorAssignment.objects.filter(
                        payment__loan=payment.loan, is_active_assignment=True).exists():
                    continue
                CollectionVendorAssignment.objects.create(
                    vendor=collection_vendor_ratio.collection_vendor,
                    vendor_configuration=collection_vendor_ratio,
                    payment=payment,
                    sub_bucket_assign_time=sub_bucket,
                    dpd_assign_time=payment.due_late_days,
                    is_transferred_from_other=is_transferred_from_other,
                )

                history_movement_record_data.append(
                    CollectionAssignmentHistory(
                        payment=payment,
                        old_assignment=old_assignment,
                        new_assignment=collection_vendor_ratio.collection_vendor,
                        assignment_reason=data_payment['reason'],
                    )
                )
    create_record_movement_history(
        history_movement_record_data
    )
    if is_trigger_chain:
        trigger_chain_b5_assignment(intelix_team)


@task(queue="collection_dialer_high")
def check_assignment_bucket_5():
    special_vendors_ratios = CollectionVendorRatio.objects.filter(
        vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('special')
    )
    for special_vendor_ratio in special_vendors_ratios:
        check_vendor_assignment(special_vendor_ratio)
        check_vendor_assignment_for_j1(special_vendor_ratio)

    check_assignment_bucket_6_1.delay()


@task(queue="collection_dialer_high")
def check_assignment_bucket_6_1():
    today = timezone.localtime(timezone.now())
    expire_time = today - timedelta(
        days=CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.__dict__[
            CollectionVendorCodes.VENDOR_TYPES.get('general').lower()
        ]
    )

    sub_bucket = SubBucket.sub_bucket_five(2)
    expired_vendor_assignments = get_expired_vendor_assignment(expire_time, sub_bucket)
    if not expired_vendor_assignments:
        check_assignment_bucket_6_2.delay()
        return

    today = timezone.localtime(timezone.now())
    history_movement = []

    # MTL
    collection_vendor_assignments = expired_vendor_assignments.filter(
        payment__isnull=False
    ).distinct('payment_id')

    for collection_vendor_assignment in collection_vendor_assignments:
        payment = collection_vendor_assignment.payment

        if collection_vendor_assignment.is_extension:
            end_period_retain = \
                collection_vendor_assignment.get_expiration_assignment + timedelta(days=30)
            if today.date() < end_period_retain.date():
                continue

        # create history
        history_movement.append(
            format_and_create_single_movement_history(
                payment, None,
                reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ASSIGNMENT_EXPIRED_VENDOR_END'],
                is_julo_one=False, is_only_formated=True)
        )

        active_collection_vendor_assigments = CollectionVendorAssignment.objects.filter(
            assign_time__date__lt=expire_time.date(),
            sub_bucket_assign_time=sub_bucket,
            is_active_assignment=True,
            payment=payment
        )
        active_collection_vendor_assigments.update(
            unassign_time=today,
            is_active_assignment=False
        )

    # J1
    collection_vendor_assignments = expired_vendor_assignments.filter(
        payment__isnull=True
    ).distinct('account_payment_id')

    for collection_vendor_assignment in collection_vendor_assignments:
        account_payment = collection_vendor_assignment.account_payment

        if collection_vendor_assignment.is_extension:
            end_period_retain = \
                collection_vendor_assignment.get_expiration_assignment + timedelta(days=30)
            if today.date() < end_period_retain.date():
                continue

        # create history
        history_movement.append(
            format_and_create_single_movement_history(
                account_payment, None,
                reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ASSIGNMENT_EXPIRED_VENDOR_END'],
                is_julo_one=True, is_only_formated=True)
        )

        active_collection_vendor_assigments = CollectionVendorAssignment.objects.filter(
            assign_time__date__lt=expire_time.date(),
            sub_bucket_assign_time=sub_bucket,
            is_active_assignment=True,
            account_payment=account_payment
        )
        active_collection_vendor_assigments.update(
            unassign_time=today,
            is_active_assignment=False
        )

    create_record_movement_history(history_movement)
    check_assignment_bucket_6_2.delay()


@task(queue="collection_dialer_high")
def check_assignment_bucket_6_2():
    today = timezone.localtime(timezone.now())
    expire_time = today - timedelta(
        days=CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.__dict__[
            CollectionVendorCodes.VENDOR_TYPES.get('general').lower()
        ]
    )
    sub_bucket = SubBucket.sub_bucket_five(3)
    expired_vendor_assignments = get_expired_vendor_assignment(expire_time, sub_bucket)

    if not expired_vendor_assignments:
        check_assignment_bucket_6_3.delay()
        return

    payments_ids_b6_2 = []

    # MTL
    collection_vendor_assignments = expired_vendor_assignments.filter(
        payment__isnull=False
    ).distinct('payment_id')

    for collection_vendor_assignment in collection_vendor_assignments:
        payment = collection_vendor_assignment.payment

        if collection_vendor_assignment.is_extension:
            end_period_retain = \
                collection_vendor_assignment.get_expiration_assignment + timedelta(days=30)
            if today.date() < end_period_retain.date():
                continue

        payments_ids_b6_2.append({
            'payment_id': payment.id,
            'type': 'vendor_to_vendor',
            'reason': CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                'ASSIGNMENT_EXPIRED_VENDOR_END']
        })

        active_collection_vendor_assignments = CollectionVendorAssignment.objects.filter(
            assign_time__date__lt=expire_time.date(),
            sub_bucket_assign_time=sub_bucket,
            is_active_assignment=True,
            payment=payment
        )

        active_collection_vendor_assignments.update(
            unassign_time=today,
            is_active_assignment=False
        )

    # J1
    account_payments_ids_b6_2 = []
    collection_vendor_assignments = expired_vendor_assignments.filter(
        payment__isnull=True
    ).distinct('account_payment_id')

    for collection_vendor_assignment in collection_vendor_assignments:
        account_payment = collection_vendor_assignment.account_payment

        if collection_vendor_assignment.is_extension:
            end_period_retain = \
                collection_vendor_assignment.get_expiration_assignment + timedelta(days=30)
            if today.date() < end_period_retain.date():
                continue

        account_payments_ids_b6_2.append({
            'account_payment_id': account_payment.id,
            'type': 'vendor_to_vendor',
            'reason': CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                'ASSIGNMENT_EXPIRED_VENDOR_END']
        })

        active_collection_vendor_assignments = CollectionVendorAssignment.objects.filter(
            assign_time__date__lt=expire_time.date(),
            sub_bucket_assign_time=sub_bucket,
            is_active_assignment=True,
            account_payment=account_payment
        )

        active_collection_vendor_assignments.update(
            unassign_time=today,
            is_active_assignment=False
        )

    assign_payments_to_vendor.delay(
        list(payments_ids_b6_2), CollectionVendorCodes.VENDOR_TYPES.get('final'),
        IntelixTeam.JULO_B6_3, False
    )
    assign_account_payments_to_vendor.delay(
        list(account_payments_ids_b6_2), CollectionVendorCodes.VENDOR_TYPES.get('final'),
        IntelixTeam.JULO_B6_3, False
    )
    check_assignment_bucket_6_3.delay()


@task(queue="collection_dialer_high")
def check_assignment_bucket_6_3():
    special_vendors_ratios = CollectionVendorRatio.objects.filter(
        vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('final')
    )
    for special_vendor_ratio in special_vendors_ratios:
        check_vendor_assignment(special_vendor_ratio)
        check_vendor_assignment_for_j1(special_vendor_ratio)

    allocate_payments_to_collection_vendor_for_bucket_5.delay()


@task(queue="collection_dialer_high")
def update_agent_assigment_for_expired_account():
    today = timezone.localtime(timezone.now())
    sub_bucket = SubBucket.sub_bucket_five(1)
    bulk_data_history_movement = []

    # mtl
    loan_ids_have_waiver_request = get_loan_ids_have_waiver_already()
    agent_assignments = AgentAssignment.objects.filter(
        is_active_assignment=True, is_transferred_to_other=False,
        payment__isnull=False
    ).extra(where=[
        "(now() AT TIME ZONE 'Asia/Jakarta')::date - "
        "(agent_assignment.assign_time AT TIME ZONE 'Asia/Jakarta')::date "
        ">= 30"
    ]).exclude(
        payment__loan_id__in=loan_ids_have_waiver_request).distinct(
            'payment_id')

    unassign_payment_ids = []

    for agent_assignment in agent_assignments:
        payment = agent_assignment.payment
        last_agent =\
            check_active_ptp_agent_assignment(payment)

        if last_agent:
            continue

        unassign_payment_ids.append(payment.id)
        bulk_data_history_movement.append(
            CollectionAssignmentHistory(
                payment=payment,
                old_assignment=agent_assignment.agent,
                new_assignment=None,
                assignment_reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ASSIGNMENT_EXPIRED_GTE_30_DAYS'],
            )
        )

    # j1
    account_ids_have_waiver_request = get_account_ids_have_waiver_already_will_excluded_in_b5()
    agent_assignments = AgentAssignment.objects.filter(
        is_active_assignment=True, is_transferred_to_other=False,
        account_payment__isnull=False
    ).extra(where=[
        "(now() AT TIME ZONE 'Asia/Jakarta')::date - "
        "(agent_assignment.assign_time AT TIME ZONE 'Asia/Jakarta')::date "
        ">= 30"
    ]).exclude(
        account_payment__account_id__in=account_ids_have_waiver_request).distinct(
            'account_payment_id')

    unassign_account_payment_ids = []

    for agent_assignment in agent_assignments:
        account_payment = agent_assignment.account_payment
        last_agent =\
            check_active_ptp_agent_assignment(account_payment, is_julo_one=True)

        if last_agent:
            continue

        unassign_account_payment_ids.append(account_payment.id)
        bulk_data_history_movement.append(
            CollectionAssignmentHistory(
                account_payment=account_payment,
                old_assignment=agent_assignment.agent,
                new_assignment=None,
                assignment_reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ASSIGNMENT_EXPIRED_GTE_30_DAYS'],
            )
        )

    # unassign agent assignment update
    AgentAssignment.objects.filter(
        payment_id__in=unassign_payment_ids).update(
        is_active_assignment=False, unassign_time=today)

    AgentAssignment.objects.filter(
        account_payment_id__in=unassign_account_payment_ids).update(
        is_active_assignment=False, unassign_time=today)

    # expired agent assigment that current bucket is gte then active assignment mtl or
    # reach end of the bucket
    unassign_payment_ids = []
    agent_assignments = AgentAssignment.objects.raw(
        "select distinct payment_id, * from agent_assignment as aa"
        " where aa.payment_id is not null and aa.is_active_assignment = true"
        " and sub_bucket_assign_time_id < ("
        " select sub_bucket.sub_bucket_id from sub_bucket where ("
        " select (now() AT TIME ZONE 'Asia/Jakarta')::date -"
        " (py.due_date AT TIME ZONE 'Asia/Jakarta')::date"
        " from payment as py where py.payment_id = aa.payment_id"
        " and (now() AT TIME ZONE 'Asia/Jakarta')::date -"
        " (py.due_date AT TIME ZONE 'Asia/Jakarta')::date > %s)"
        " between start_dpd and end_dpd)", [sub_bucket.end_dpd, ]
    )

    for agent_assignment in agent_assignments:
        payment = agent_assignment.payment

        if payment.loan_id in loan_ids_have_waiver_request:
            continue

        unassign_payment_ids.append(payment.id)
        bulk_data_history_movement.append(
            CollectionAssignmentHistory(
                payment=payment,
                old_assignment=agent_assignment.agent,
                new_assignment=None,
                assignment_reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ASSIGNMENT_EXPIRED_END_OF_BUCKET'],
            )
        )

    # expired agent assigment that current bucket is gte then active assignment j1 or
    # reach end of the bucket
    agent_assignments = AgentAssignment.objects.raw(
        "select distinct account_payment_id, * from agent_assignment as aa"
        " where aa.account_payment_id is not null and aa.is_active_assignment = true"
        " and sub_bucket_assign_time_id < ("
        " select sub_bucket.sub_bucket_id from sub_bucket where ("
        " select (now() AT TIME ZONE 'Asia/Jakarta')::date - ("
        "apy.due_date AT TIME ZONE 'Asia/Jakarta')::date"
        " from account_payment as apy where apy.account_payment_id = aa.account_payment_id"
        " and (now() AT TIME ZONE 'Asia/Jakarta')::date - ("
        "apy.due_date AT TIME ZONE 'Asia/Jakarta')::date > %s)"
        " between start_dpd and end_dpd)", [sub_bucket.end_dpd, ]
    )

    unassign_account_payment_ids = []
    for agent_assignment in agent_assignments:
        account_payment = agent_assignment.account_payment

        if account_payment.account_id in account_ids_have_waiver_request:
            continue

        unassign_account_payment_ids.append(account_payment.id)
        bulk_data_history_movement.append(
            CollectionAssignmentHistory(
                account_payment=account_payment,
                old_assignment=agent_assignment.agent,
                new_assignment=None,
                assignment_reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ASSIGNMENT_EXPIRED_END_OF_BUCKET'],
            )
        )
    # unassign agent assignment update
    AgentAssignment.objects.filter(
        payment_id__in=unassign_payment_ids).update(
        is_active_assignment=False, unassign_time=today)

    AgentAssignment.objects.filter(
        account_payment_id__in=unassign_account_payment_ids).update(
        is_active_assignment=False, unassign_time=today)

    # record history
    create_record_movement_history(bulk_data_history_movement)
    check_assignment_bucket_5.delay()


@task(queue="collection_normal")
def store_related_data_calling_vendor_result_task(data_xls):
    for row_data in data_xls:
        user = User.objects.filter(pk=int(row_data['collector id'])).last()
        customer = None
        application = None
        oldest_unpaid_payment = None
        application_status = None
        start_ts = datetime.strptime(row_data['waktu visit/penelponan'],
                                     '%d-%m-%Y, %H.%M')
        loan = None
        loan_status = None
        payment_status = None
        oldest_account_payment = None
        account_payment_status = None
        account = None
        notes = row_data['notes'] if 'notes' in row_data else ''
        ptp_amount = 0
        ptp_date = None
        ptp_status = None
        all_type_payment = None
        if 'ptp date' in row_data:
            notes = notes + '; ' if len(notes) > 0 else notes
            notes = notes + row_data['ptp date']
            ptp_date = datetime.strptime(row_data['ptp date'], '%d-%m-%Y')
        if 'ptp amount' in row_data:
            notes = notes + '; ' if len(notes) > 0 else notes
            notes = notes + row_data['ptp amount']
            ptp_amount = row_data['ptp amount']
        if 'application xid' in row_data:
            application = Application.objects.filter(
                application_xid=int(row_data['application xid'])
            ).last()
            customer = application.customer
            loan = Loan.objects.filter(
                application=application
            ).last()
            loan_status = loan.loan_status.status_code
            oldest_unpaid_payment = loan.get_oldest_unpaid_payment()
            application_status = application.application_status.status_code
            payment_status = oldest_unpaid_payment.payment_status.status_code
            all_type_payment = oldest_unpaid_payment
        elif 'account id' in row_data:
            account = Account.objects.get(
                pk=int(row_data['account id'])
            )
            customer = account.customer
            oldest_account_payment = AccountPayment.objects.filter(
                account=account
            ).not_paid_active().order_by('due_date').first()
            account_payment_status = oldest_account_payment.status
            payment_status = oldest_account_payment.status.status_code
            all_type_payment = oldest_account_payment
        skiptrace = Skiptrace.objects.filter(
            customer=customer,
            phone_number='+' + row_data['phone number']
        ).last()
        if not skiptrace:
            skiptrace = Skiptrace.objects.create(
                customer=customer,
                application=application,
                effectiveness=0,
                phone_number='+' + row_data['phone number']
            )
        skiptrace_result_choice = SkiptraceResultChoice.objects.filter(
            pk=int(row_data['action code'])
        ).last()
        SkiptraceHistory.objects.create(
            skiptrace=skiptrace,
            payment=oldest_unpaid_payment,
            payment_status=payment_status,
            agent=user,
            agent_name=user.username,
            application=application,
            application_status=application_status,
            start_ts=start_ts,
            end_ts=start_ts + timedelta(minutes=5),
            loan=loan,
            loan_status=loan_status,
            call_result=skiptrace_result_choice,
            notes=notes,
            account=account,
            account_payment=oldest_account_payment,
            account_payment_status=account_payment_status,
            source='CRM'
        )
        if ptp_amount and ptp_date:
            paid_status_codes = [PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                                 PaymentStatusCodes.PAID_LATE,
                                 PaymentStatusCodes.PAID_ON_TIME]
            if all_type_payment and \
                    all_type_payment.paid_date is not None and \
                    all_type_payment.paid_amount != 0:
                if payment_status in paid_status_codes:
                    if all_type_payment.paid_date > ptp_date:
                        ptp_status = "Paid after ptp date"
                    elif all_type_payment.paid_date <= ptp_date and \
                            all_type_payment.due_amount != 0:
                        ptp_status = "Partial"
                    else:
                        ptp_status = "Paid"
                elif all_type_payment.due_amount != 0:
                    ptp_status = "Partial"
            else:
                ptp_status = "Not Paid"
            PTP.objects.create(
                account_payment=oldest_account_payment,
                account=account,
                agent_assigned=user,
                ptp_date=ptp_date,
                ptp_status=ptp_status,
                ptp_amount=ptp_amount,
                loan=loan,
                payment=oldest_unpaid_payment
            )


@task(queue='collection_dialer_high')
def allocate_bucket_5_less_then_91_account_payments_to_collection_vendor(
        excluded_account_payment_ids):
    sub_bucket = SubBucket.sub_bucket_five(1)
    assigned_collection_vendor_account_ids = CollectionVendorAssignment.objects.filter(
        is_active_assignment=True, account_payment__isnull=False
    ).distinct("account_payment__account_id").values_list("account_payment__account_id", flat=True)
    account_ids_have_waiver_request = get_account_ids_have_waiver_already_will_excluded_in_b5()
    # assign to vendor if payment <= 50000
    qs = get_eligible_account_payment_for_dialer_and_vendor_qs()
    account_payments_b5_1_less_then_91 = qs.get_bucket_5_by_range(
        sub_bucket.start_dpd - 1).exclude(id__in=excluded_account_payment_ids).exclude(
        account_id__in=list(account_ids_have_waiver_request) + list(
            assigned_collection_vendor_account_ids)
    )
    allocated_to_vendor_for_account_payment_less_then_50000 = \
        allocated_to_vendor_for_account_payment_less_then_fifty_thousand(
            account_payments_b5_1_less_then_91)

    today = timezone.localtime(timezone.now()).date()
    account_payments_b5_1_ever_enter = account_payments_b5_1_less_then_91.exclude(
        id__in=allocated_to_vendor_for_account_payment_less_then_50000)
    check_for_last_contacted_account_payment = []
    check_for_last_payment_account_payment = []
    for account_payment in account_payments_b5_1_ever_enter:
        previous_account_payment = account_payment.get_previous_account_payment()
        if not hasattr(previous_account_payment, 'is_paid') or not previous_account_payment.is_paid:
            continue

        paid_at_dpd = (previous_account_payment.paid_date - account_payment.due_date).days
        current_account_payment_entered_b5_date = account_payment.due_date + relativedelta(
            days=paid_at_dpd + 1)
        last_contacted_date_should_be_check_on = \
            current_account_payment_entered_b5_date + relativedelta(days=30)
        if last_contacted_date_should_be_check_on == today:
            check_for_last_contacted_account_payment.append(account_payment)
            continue

        last_payment_should_be_check_on = current_account_payment_entered_b5_date + relativedelta(
            days=60)
        if last_payment_should_be_check_on == today:
            check_for_last_payment_account_payment.append(account_payment)

    allocated_account_payment_to_vendor_last_contacted_ids = \
        allocated_to_vendor_for_payment_last_contacted_more_thirty_days(
            check_for_last_contacted_account_payment, is_julo_one=True)

    allocated_account_payment_with_last_payment_gte_60_ids =\
        allocated_to_vendor_for_last_account_payment_more_then_sixty_days(
            check_for_last_payment_account_payment)

    return construct_data_for_send_to_vendor(
        allocated_to_vendor_for_account_payment_less_then_50000,
        allocated_account_payment_to_vendor_last_contacted_ids,
        allocated_account_payment_with_last_payment_gte_60_ids
    )


@task(queue='collection_dialer_high')
def allocate_bucket_5_account_payments_to_collection_vendor():
    allocated_from_agent_to_vendor_assignment_account_payment_ids = []
    sub_bucket = SubBucket.sub_bucket_five(1)
    assigned_collection_vendor_account_ids = CollectionVendorAssignment.objects.filter(
        is_active_assignment=True,
        account_payment__isnull=False
    ).distinct("account_payment__account_id").values_list("account_payment__account_id", flat=True)
    account_ids_have_waiver_request = get_account_ids_have_waiver_already_will_excluded_in_b5()
    excluded_account_ids = list(assigned_collection_vendor_account_ids) + list(
        account_ids_have_waiver_request)
    qs = get_eligible_account_payment_for_dialer_and_vendor_qs()
    account_payments_b5_1 = qs.get_bucket_5_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd)\
        .exclude(account_id__in=excluded_account_ids)
    # why -1 because dpd 91 its already handled
    account_payments_b5_1_dpd_less_then_91 = qs.get_bucket_5_by_range(
        sub_bucket.start_dpd - 1).exclude(
        account_id__in=excluded_account_ids).values_list("id", flat=True)
    account_payments_ids_for_passed_threshold_agent = list(account_payments_b5_1.values_list(
        "id", flat=True)) + list(account_payments_b5_1_dpd_less_then_91)
    passed_threshold_agent = AgentAssignment.objects.filter(
        is_active_assignment=True,
        account_payment_id__in=account_payments_ids_for_passed_threshold_agent,
        sub_bucket_assign_time=sub_bucket
    ).values('agent').annotate(
        total=Count('account_payment')).filter(
        total__gt=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_1)

    for agent in passed_threshold_agent:
        assigned_account_payments = AgentAssignment.objects.filter(
            agent_id=agent['agent'], is_active_assignment=True, is_transferred_to_other=False,
            account_payment_id__in=account_payments_ids_for_passed_threshold_agent,
        ).order_by('assign_time')
        # check oldest payment have active PTP
        should_allocated_count = agent['total'] - AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_1
        allocated_from_agent_to_vendor_assignment_account_payment_ids += \
            allocated_oldest_account_payment_without_active_ptp(
                assigned_account_payments, should_allocated_count)

    assigned_account_payment_to_agent = AgentAssignment.objects.filter(
        is_active_assignment=True, account_payment__isnull=False
    ).values_list("account_payment_id", flat=True)
    excluded_account_payment_list = list(assigned_account_payment_to_agent) + \
        allocated_from_agent_to_vendor_assignment_account_payment_ids

    allocated_account_payment_less_than_91 = \
        allocate_bucket_5_less_then_91_account_payments_to_collection_vendor(
            excluded_account_payment_list)

    account_payments_b5_1_excluded_assigned = account_payments_b5_1.exclude(
        id__in=excluded_account_payment_list)
    # assign to vendor if payment <= 50000
    allocated_to_vendor_for_account_payment_less_then_50000 = \
        allocated_to_vendor_for_account_payment_less_then_fifty_thousand(
            account_payments_b5_1_excluded_assigned)
    # Last contacted  date >= 30 days
    due_date_plus_120 = timezone.localtime(timezone.now() - timedelta(days=120)).date()
    account_payments_b5_1_excluded_assigned = account_payments_b5_1_excluded_assigned.exclude(
        id__in=allocated_to_vendor_for_account_payment_less_then_50000
    )
    account_payments_with_dpd_120 = account_payments_b5_1_excluded_assigned.filter(
        due_date__lte=due_date_plus_120)
    assigned_account_payment_to_vendor_last_contacted = \
        allocated_to_vendor_for_payment_last_contacted_more_thirty_days(
            account_payments_with_dpd_120, is_julo_one=True)

    # last payment >= 60 checking for dpd 150
    due_date_plus_150 = timezone.localtime(timezone.now() - timedelta(days=150)).date()
    account_payments_b5_1_excluded_assigned = account_payments_b5_1_excluded_assigned.exclude(
        id__in=assigned_account_payment_to_vendor_last_contacted
    )
    account_payments_with_dpd_150 = account_payments_b5_1_excluded_assigned.filter(
        due_date__lte=due_date_plus_150)
    allocated_account_payment_with_last_payment_gte_60 = \
        allocated_to_vendor_for_last_account_payment_more_then_sixty_days(
            account_payments_with_dpd_150)

    # combine all allocated payments
    all_allocated_vendor = construct_data_for_send_to_vendor(
        allocated_to_vendor_for_account_payment_less_then_50000,
        assigned_account_payment_to_vendor_last_contacted,
        allocated_account_payment_with_last_payment_gte_60,
        allocated_from_agent_to_vendor_assignment_account_payment_ids,
        agent_threshold=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_1
    )

    all_allocated_vendor = all_allocated_vendor + allocated_account_payment_less_than_91
    assign_account_payments_to_vendor.delay(
        all_allocated_vendor, CollectionVendorCodes.VENDOR_TYPES.get('special'),
        IntelixTeam.JULO_B5
    )


@task(queue='collection_dialer_high')
def allocate_bucket_6_1_account_payments_to_collection_vendor():
    allocated_from_agent_to_vendor_assignment_account_payment_ids = []
    sub_bucket = SubBucket.sub_bucket_six(1)
    assigned_collection_vendor_account_ids = CollectionVendorAssignment.objects.filter(
        is_active_assignment=True, account_payment__isnull=False
    ).distinct("account_payment__account_id").values_list("account_payment__account_id", flat=True)
    account_ids_have_waiver_request = get_account_ids_have_waiver_already_will_excluded_in_b5()
    qs = get_eligible_account_payment_for_dialer_and_vendor_qs()
    account_payments_b6_1 = qs.get_bucket_6_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd)\
        .exclude(
        account_id__in=list(
            account_ids_have_waiver_request) + list(
            assigned_collection_vendor_account_ids))

    passed_threshold_agent = AgentAssignment.objects.filter(
        is_active_assignment=True,
        account_payment_id__in=list(account_payments_b6_1.values_list("id", flat=True)),
        sub_bucket_assign_time=sub_bucket
    ).values('agent').annotate(
        total=Count('account_payment')).filter(
        total__gt=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_2)
    for agent in passed_threshold_agent:
        assigned_account_payments = AgentAssignment.objects.filter(
            agent_id=agent['agent'], is_active_assignment=True,
            account_payment_id__in=list(account_payments_b6_1.values_list("id", flat=True)),
        ).order_by('assign_time')
        should_allocated_count = agent['total'] - AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_2
        allocated_from_agent_to_vendor_assignment_account_payment_ids += \
            allocated_oldest_account_payment_without_active_ptp(
                assigned_account_payments, should_allocated_count)

    assigned_account_payment_to_agent = AgentAssignment.objects.filter(
        is_active_assignment=True, account_payment__isnull=False
    ).values_list("account_payment_id", flat=True)

    account_payments_b6_1_excluded_assigned = account_payments_b6_1.exclude(
        id__in=list(assigned_account_payment_to_agent) +
        allocated_from_agent_to_vendor_assignment_account_payment_ids)

    # assign to vendor if payment <= 50000
    allocated_to_vendor_for_payment_less_then_50000 = \
        allocated_to_vendor_for_account_payment_less_then_fifty_thousand(
            account_payments_b6_1_excluded_assigned)

    # Last contacted date >= 30 days
    due_date_plus_210 = timezone.localtime(timezone.now() - timedelta(days=210)).date()
    account_payments_b6_1_excluded_assigned = account_payments_b6_1.exclude(
        id__in=allocated_to_vendor_for_payment_less_then_50000
    )
    account_payments_with_dpd_210 = account_payments_b6_1_excluded_assigned.filter(
        due_date__lte=due_date_plus_210)
    assigned_payment_to_vendor_last_contacted = \
        allocated_to_vendor_for_payment_last_contacted_more_thirty_days(
            account_payments_with_dpd_210, is_julo_one=True)
    # last payment >= 60 checking for dpd 240
    due_date_plus_240 = timezone.localtime(timezone.now() - timedelta(days=240)).date()
    account_payments_b6_1_excluded_assigned = account_payments_b6_1_excluded_assigned.exclude(
        id__in=assigned_payment_to_vendor_last_contacted
    )
    account_payments_with_dpd_240 = account_payments_b6_1_excluded_assigned.filter(
        due_date__lte=due_date_plus_240)
    allocated_payment_with_last_payment_gte_60 = \
        allocated_to_vendor_for_last_account_payment_more_then_sixty_days(
            account_payments_with_dpd_240)
    # combine all allocated payments
    all_allocated_vendor = construct_data_for_send_to_vendor(
        allocated_to_vendor_for_payment_less_then_50000,
        assigned_payment_to_vendor_last_contacted,
        allocated_payment_with_last_payment_gte_60,
        allocated_from_agent_to_vendor_assignment_account_payment_ids,
        agent_threshold=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_2
    )

    assign_account_payments_to_vendor.delay(
        all_allocated_vendor,
        CollectionVendorCodes.VENDOR_TYPES.get('general'), IntelixTeam.JULO_B6_1
    )


@task(queue='collection_dialer_high')
def allocate_bucket_6_2_account_payments_to_collection_vendor():
    allocated_from_agent_to_vendor_assignment_account_payment_ids = []
    sub_bucket = SubBucket.sub_bucket_six(2)
    assigned_collection_vendor_account_ids = CollectionVendorAssignment.objects.filter(
        is_active_assignment=True,
        account_payment__isnull=False
    ).distinct("account_payment__account_id").values_list("account_payment__account_id", flat=True)
    account_ids_have_waiver_request = get_account_ids_have_waiver_already_will_excluded_in_b5()
    qs = get_eligible_account_payment_for_dialer_and_vendor_qs()
    account_payments_b6_2 = qs.get_bucket_6_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd) \
        .exclude(
        account_id__in=list(
            account_ids_have_waiver_request) + list(
            assigned_collection_vendor_account_ids))

    passed_threshold_agent = AgentAssignment.objects.filter(
        is_active_assignment=True,
        account_payment_id__in=list(account_payments_b6_2.values_list("id", flat=True)),
        sub_bucket_assign_time=sub_bucket
    ).values('agent').annotate(
        total=Count('account_payment')).filter(
        total__gt=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_3)
    for agent in passed_threshold_agent:
        account_assigned_payments = AgentAssignment.objects.filter(
            agent_id=agent['agent'], is_active_assignment=True,
            account_payment_id__in=list(account_payments_b6_2.values_list("id", flat=True)),
        ).order_by('assign_time')
        # check oldest payment have active PTP
        should_allocated_count = agent['total'] - AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_3
        allocated_from_agent_to_vendor_assignment_account_payment_ids += \
            allocated_oldest_account_payment_without_active_ptp(
                account_assigned_payments, should_allocated_count)

    assigned_account_payment_to_agent = AgentAssignment.objects.filter(
        is_active_assignment=True, account_payment__isnull=False
    ).values_list("account_payment_id", flat=True)
    account_payments_b6_2_excluded_assigned = account_payments_b6_2.exclude(
        id__in=list(assigned_account_payment_to_agent) +
        allocated_from_agent_to_vendor_assignment_account_payment_ids)
    # assign to vendor if payment <= 50000
    allocated_to_vendor_for_account_payment_less_then_50000 = \
        allocated_to_vendor_for_account_payment_less_then_fifty_thousand(
            account_payments_b6_2_excluded_assigned)

    # Last contacted  date >= 30 days
    due_date_plus_300 = timezone.localtime(timezone.now() - timedelta(days=300)).date()
    account_payments_b6_2_excluded_assigned = account_payments_b6_2_excluded_assigned.exclude(
        id__in=allocated_to_vendor_for_account_payment_less_then_50000
    )
    account_payments_with_dpd_300 = account_payments_b6_2_excluded_assigned.filter(
        due_date__lte=due_date_plus_300)
    assigned_account_payment_to_vendor_last_contacted = \
        allocated_to_vendor_for_payment_last_contacted_more_thirty_days(
            account_payments_with_dpd_300, is_julo_one=True)

    # last payment >= 60 checking for dpd 330
    due_date_plus_330 = timezone.localtime(timezone.now() - timedelta(days=330)).date()
    account_payments_b6_2_excluded_assigned = account_payments_b6_2_excluded_assigned.exclude(
        id__in=assigned_account_payment_to_vendor_last_contacted
    )
    payments_with_dpd_330 = account_payments_b6_2_excluded_assigned.filter(
        due_date__lte=due_date_plus_330)
    allocated_account_payment_with_last_payment_gte_60 = \
        allocated_to_vendor_for_last_account_payment_more_then_sixty_days(
            payments_with_dpd_330)
    # combine all allocated payments
    all_allocated_vendor = construct_data_for_send_to_vendor(
        allocated_to_vendor_for_account_payment_less_then_50000,
        assigned_account_payment_to_vendor_last_contacted,
        allocated_account_payment_with_last_payment_gte_60,
        allocated_from_agent_to_vendor_assignment_account_payment_ids,
        agent_threshold=AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_3
    )
    assign_account_payments_to_vendor.delay(
        all_allocated_vendor, CollectionVendorCodes.VENDOR_TYPES.get('general'),
        IntelixTeam.JULO_B6_2
    )


@task(queue='collection_dialer_high')
def allocate_bucket_6_3_account_payments_to_collection_vendor():
    sub_bucket = SubBucket.sub_bucket_six(3)
    assigned_collection_vendor_account_ids = CollectionVendorAssignment.objects.filter(
        is_active_assignment=True,
        account_payment__isnull=False
    ).distinct("account_payment__account_id").values_list("account_payment__account_id", flat=True)
    account_ids_have_waiver_request = get_account_ids_have_waiver_already_will_excluded_in_b5()
    qs = get_eligible_account_payment_for_dialer_and_vendor_qs()
    account_payments_b6_3 = qs.get_bucket_6_by_range(sub_bucket.start_dpd, sub_bucket.end_dpd)\
        .exclude(
        account_id__in=list(
            account_ids_have_waiver_request) + list(assigned_collection_vendor_account_ids)
    ).extra(select={
        'type': "'inhouse_to_vendor'",
        'account_payment_id': 'account_payment_id', 'reason': '%s'},
        select_params=(
            CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                'ACCOUNT_SYSTEM_TRANSFERRED_VENDOR'], ))\
        .values("account_payment_id", "type", "reason")
    assign_account_payments_to_vendor.delay(
        list(account_payments_b6_3), CollectionVendorCodes.VENDOR_TYPES.get('final'),
        IntelixTeam.JULO_B6_3
    )


def trigger_chain_b5_j1(intelix_team):
    from juloserver.minisquad.tasks2.intelix_task import (
        upload_julo_b4_data_to_intelix,
    )

    if intelix_team == IntelixTeam.JULO_B5:
        allocate_bucket_6_1_account_payments_to_collection_vendor.delay()
    elif intelix_team == IntelixTeam.JULO_B6_1:
        allocate_bucket_6_2_account_payments_to_collection_vendor.delay()
    elif intelix_team == IntelixTeam.JULO_B4_NC:
        upload_julo_b4_data_to_intelix.delay()


@task(queue='collection_dialer_high')
def assign_account_payments_to_vendor(
        data_account_payments, vendor_type, intelix_team=None, is_trigger_chain=True):
    data_account_payments = serialize_data_for_sent_to_vendor(data_account_payments)
    if not data_account_payments:
        if is_trigger_chain:
            trigger_chain_b5_j1(intelix_team)
        return

    collection_vendor_ratios = CollectionVendorRatio.objects.filter(
        **{'vendor_types': vendor_type, 'collection_vendor__is_active': True,
           'collection_vendor__is_{}'.format(vendor_type.lower()): True
           }
    )
    today = timezone.localtime(timezone.now()).date()
    history_movement_record_data = []
    total_data = len(data_account_payments)
    for collection_vendor_ratio in collection_vendor_ratios:

        if not collection_vendor_ratio.collection_vendor.is_active:
            continue

        assigned_account_payments_count = \
            collection_vendor_ratio.account_distribution_ratio * total_data

        if isinstance(assigned_account_payments_count, float):
            ratios = collection_vendor_ratios.exclude(
                pk=collection_vendor_ratio.id
            ).values_list('account_distribution_ratio', flat=True)
            total_account_payments = []

            for ratio in ratios:
                tmp_total_payment = drop_zeros(ratio * total_data)
                if isinstance(tmp_total_payment, float):
                    total_account_payments.append(tmp_total_payment)

            if any(assigned_account_payments_count > total_account_payment
                   for total_account_payment in total_account_payments):
                assigned_account_payments_count = int(math.ceil(assigned_account_payments_count))
            else:
                assigned_account_payments_count = int(math.floor(assigned_account_payments_count))

        if assigned_account_payments_count < 1:
            recount_assigned_account_payment_count = int(math.ceil(
                collection_vendor_ratio.account_distribution_ratio * total_data))
            if recount_assigned_account_payment_count >= 1:
                assigned_account_payments_count = recount_assigned_account_payment_count
        for i in range(assigned_account_payments_count):
            if not data_account_payments:
                break
            data_account_payment = data_account_payments.pop()
            account_payment_id = data_account_payment['account_payment_id']
            account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)

            if not account_payment:
                continue

            sub_bucket = get_current_sub_bucket(account_payment, is_julo_one=True)
            is_transferred_from_other = \
                True if 'inhouse_to_vendor' != data_account_payment['type'] else False
            # None means the data is on inhouse
            old_assignment = None

            if data_account_payment['type'] == 'agent_to_vendor':
                agent_assignment = AgentAssignment.objects.filter(
                    account_payment=account_payment,
                    is_active_assignment=True
                ).last()
                agent_assignment.update_safely(is_active_assignment=False)
                old_assignment = agent_assignment.agent
            elif data_account_payment['type'] == 'vendor_to_vendor':
                old_vendor_assignment = CollectionVendorAssignment.objects.filter(
                    account_payment=account_payment,
                    unassign_time__date=today
                ).last()
                if old_vendor_assignment:
                    old_assignment = old_vendor_assignment.vendor
            # prevent double assignment
            if CollectionVendorAssignment.objects.filter(
                    account_payment__account=account_payment.account,
                    is_active_assignment=True).exists():
                continue
            CollectionVendorAssignment.objects.create(
                vendor=collection_vendor_ratio.collection_vendor,
                vendor_configuration=collection_vendor_ratio,
                account_payment=account_payment,
                sub_bucket_assign_time=sub_bucket,
                dpd_assign_time=account_payment.dpd,
                is_transferred_from_other=is_transferred_from_other,
            )
            history_movement_record_data.append(
                CollectionAssignmentHistory(
                    account_payment=account_payment,
                    old_assignment=old_assignment,
                    new_assignment=collection_vendor_ratio.collection_vendor,
                    assignment_reason=data_account_payment['reason'],
                )
            )
    create_record_movement_history(
        history_movement_record_data
    )
    if is_trigger_chain:
        trigger_chain_b5_j1(intelix_team)


@task(queue='collection_dialer_high')
def process_unassignment_when_paid_for_j1(account_payment_id):
    account_payment = AccountPayment.objects.get_or_none(id=account_payment_id)
    if not account_payment or \
            account_payment.bucket_number_when_paid not in (4, 5):
        return

    next_unpaid_account_payment = account_payment.get_next_unpaid_payment()
    sub_bucket_current = None
    is_bucket_4 = True if account_payment.bucket_number_when_paid == 4 else False
    if next_unpaid_account_payment:
        sub_bucket_current = get_current_sub_bucket(
            next_unpaid_account_payment, is_julo_one=True,
            is_bucket_4=is_bucket_4
        )

    agent_assignments = AgentAssignment.objects.filter(
        account_payment=account_payment, is_active_assignment=True,
    )
    vendor_assignments = CollectionVendorAssignment.objects.filter(
        account_payment=account_payment, is_active_assignment=True,
    )
    if not agent_assignments and not vendor_assignments:
        return

    today = timezone.localtime(timezone.now())
    is_already_new_assign = False
    if agent_assignments:
        agent_assignment = agent_assignments.last()
        # allocated_days = (today - agent_assignment.assign_time.date()).days
        # unassign old active assignment
        # None means inhouse
        format_and_create_single_movement_history(
            account_payment, None,
            reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS['PAID'],
            is_julo_one=True
        )
        agent_assignments.update(
            is_active_assignment=False, unassign_time=today)
        # set next agent to unpaid payment if still have time
        if not next_unpaid_account_payment or not sub_bucket_current:
            return
        allocated_days = (today.date() - agent_assignment.assign_time.date()).days
        if allocated_days >= 30:
            return

        is_next_payment_already_assign = AgentAssignment.objects.filter(
            account_payment=next_unpaid_account_payment,
            is_active_assignment=True
        ).exists()
        if is_next_payment_already_assign:
            return

        format_and_create_single_movement_history(
            next_unpaid_account_payment, agent_assignment.agent,
            reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                'ACCOUNT_SYSTEM_TRANSFERRED_AGENT'],
            is_julo_one=True
        )
        AgentAssignment.objects.create(
            agent=agent_assignment.agent,
            account_payment=next_unpaid_account_payment,
            sub_bucket_assign_time=sub_bucket_current,
            dpd_assign_time=next_unpaid_account_payment.dpd,
            assign_time=agent_assignment.assign_time,
        )
        is_already_new_assign = True
    if vendor_assignments:
        vendor_assignment = vendor_assignments.last()
        format_and_create_single_movement_history(
            account_payment, None,
            reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS['PAID'],
            is_julo_one=True
        )
        vendor_assignments.update(
            is_active_assignment=False, unassign_time=today, collected_ts=today)
        if not next_unpaid_account_payment or is_bucket_4:
            return
        allocated_days = (today.date() - vendor_assignment.assign_time.date()).days
        remaining_vendor_stay_threshold = vendor_assignment.sub_bucket_assign_time.\
            vendor_type_expiration_days
        if allocated_days >= remaining_vendor_stay_threshold:
            return
        # assign next payment to existing vendor
        is_next_payment_already_assign = CollectionVendorAssignment.objects.filter(
            account_payment=next_unpaid_account_payment,
            is_active_assignment=True
        ).exists()
        if is_next_payment_already_assign or is_already_new_assign:
            return

        vendor = vendor_assignment.vendor
        vendor_configuration = vendor_assignment.vendor_configuration
        if not vendor_assignment.vendor.is_active:
            vendor_type = vendor_assignment.vendor_configuration.vendor_types
            collection_vendor_ratio = CollectionVendorRatio.objects.filter(
                vendor_types=vendor_type).exclude(collection_vendor__is_active=False).last()
            vendor = collection_vendor_ratio.collection_vendor
            vendor_configuration = collection_vendor_ratio

        format_and_create_single_movement_history(
            next_unpaid_account_payment, vendor_assignment.vendor,
            reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                'ACCOUNT_SYSTEM_TRANSFERRED_VENDOR'],
            is_julo_one=True
        )
        CollectionVendorAssignment.objects.create(
            vendor=vendor,
            vendor_configuration=vendor_configuration,
            account_payment=next_unpaid_account_payment,
            sub_bucket_assign_time=sub_bucket_current,
            dpd_assign_time=next_unpaid_account_payment.dpd,
            assign_time=vendor_assignment.assign_time
        )


@task(queue='collection_dialer_normal')
def process_bulk_download_recording_files(vendor_recording_detail_ids, dialer_task_id):
    dialer_task = DialerTask.objects.get(pk=dialer_task_id)
    dialer_task.update_safely(
        status=DialerTaskStatus.PROCESSED,
    )
    progress_recorder = ProgressRecorder(
        task_id=process_bulk_download_recording_files.request.id
    )
    vendor_recording_details = VendorRecordingDetail.objects.using(
        REPAYMENT_ASYNC_REPLICA_DB).filter(id__in=vendor_recording_detail_ids)
    total_process = vendor_recording_details.count() + 5  # add 5% for upload
    today = timezone.localtime(timezone.now())
    zip_file_name = "{}.zip".format(today.strftime("%d-%m-%Y"))
    with TempDir(dir="/media") as tempdir:
        processed_count = 0
        dirpath = tempdir.path
        zip_filepath = os.path.join(dirpath, zip_file_name)
        zip_file = ZipFile(zip_filepath, 'w')
        for vendor_recording_detail in vendor_recording_details:
            filename_dir = os.path.join(
                dirpath, vendor_recording_detail.oss_recording_file_name)
            # download file
            urllib.request.urlretrieve(
                get_oss_presigned_url(
                    settings.OSS_JULO_COLLECTION_BUCKET, vendor_recording_detail.oss_recording_path
                ), filename_dir)
            # Writes the downloaded file archive
            zip_file.write(filename_dir, vendor_recording_detail.downloaded_file_name)
            # update progress percentage
            processed_count += 1
            progress_recorder.set_progress(processed_count, total_process)
        # Close the file
        zip_file.close()
        # upload to OSS
        dest_name = "{}/{}.{}".format(
            settings.ENVIRONMENT, today.strftime("%d-%m-%Y_%H%M%S"), 'zip'
        )
        dialer_task.update_safely(
            status=DialerTaskStatus.UPLOADING,
        )
        upload_file_to_oss(
            settings.OSS_JULO_COLLECTION_BUCKET,
            zip_filepath, dest_name
        )
        expire_in_minutes = 180
        bulk_download_feature_setting = FeatureSetting.objects.using(
            REPAYMENT_ASYNC_REPLICA_DB).filter(
            feature_name=FeatureNameConst.CACHE_BULK_DOWNLOAD_EXPIRED_SETTING,
            is_active=True
        ).last()
        if bulk_download_feature_setting:
            expire_in_minutes = bulk_download_feature_setting.parameters['expire_in']

        expire_date = timezone.localtime(timezone.now()) + relativedelta(
            minutes=expire_in_minutes)
        vendor_recording_list_ids_sorted = list(vendor_recording_detail_ids)
        vendor_recording_list_ids_sorted = [
            str(vendor_recording_id) for vendor_recording_id in vendor_recording_list_ids_sorted
        ]
        recording_file_cache = BulkVendorRecordingFileCache.objects.create(
            cache_vendor_recording_detail_ids=','.join(vendor_recording_list_ids_sorted),
            zip_recording_file_url=dest_name,
            total_data=processed_count,
            expire_date=expire_date,
            task_id=process_bulk_download_recording_files.request.id
        )
        progress_recorder.set_progress(
            processed_count + 5, total_process, description=recording_file_cache.id
        )
        dialer_task.update_safely(
            status=DialerTaskStatus.SUCCESS,
        )
        # delete cache after threshold from feature settings
        process_expire_bulk_download_cache.apply_async(
            (recording_file_cache.id, ),
            eta=expire_date
        )


@task(queue='collection_dialer_low')
def process_expire_bulk_download_cache(recording_file_cache_id):
    recording_file_cache = BulkVendorRecordingFileCache.objects.using(
        REPAYMENT_ASYNC_REPLICA_DB).get(pk=recording_file_cache_id)
    if not recording_file_cache:
        return

    # delete file from oss
    delete_public_file_from_oss(
        settings.OSS_JULO_COLLECTION_BUCKET, recording_file_cache.zip_recording_file_url)
    recording_file_cache.delete()
    redisClient = get_redis_client()
    redisClient.delete_key(recording_file_cache.task_id)


@task(queue='collection_dialer_normal')
def schedule_unassign_payment_and_account_payment_already_paid():
    filter_mtl = dict(
        is_active_assignment=True, payment__isnull=False,
        payment__payment_status__in=PaymentStatusCodes.paid_status_codes()
    )
    filter_j1 = dict(
        is_active_assignment=True, account_payment__isnull=False,
        account_payment__status__in=PaymentStatusCodes.paid_status_codes()
    )
    mtl_agent_assignments = list(AgentAssignment.objects.filter(
        **filter_mtl).values_list('payment_id', flat=True))
    mtl_vendor_assignments = list(CollectionVendorAssignment.objects.filter(
        **filter_mtl).values_list('payment_id', flat=True))
    mtl_payment_ids = mtl_agent_assignments + mtl_vendor_assignments
    j1_agent_assignments = list(AgentAssignment.objects.filter(
        **filter_j1).values_list('account_payment_id', flat=True))
    j1_vendor_assignments = list(CollectionVendorAssignment.objects.filter(
        **filter_j1).values_list('account_payment_id', flat=True))
    j1_account_payment_ids = j1_agent_assignments + j1_vendor_assignments
    for payment_id in mtl_payment_ids:
        process_unassignment_when_paid(payment_id)
    for account_payment_id in j1_account_payment_ids:
        process_unassignment_when_paid_for_j1(account_payment_id)

    update_agent_assigment_for_expired_account.delay()


@task(queue='collection_dialer_high')
def b4_vendor_distribution(intelix_team):
    logger.info({
        "action": "b4_vendor_distribution",
        "bucket": intelix_team,
        "info": "function begin"
    })
    current_date = str(timezone.localtime(timezone.now()).date())
    if intelix_team == IntelixTeam.JULO_B4_NC:
        _, account_payments, not_sent_account_payments = get_account_payment_details_for_calling(
            intelix_team)
    else:
        account_payments, not_sent_account_payments = get_account_payment_details_for_calling(
            intelix_team)
    logger.info({
        "action": "get_account_payment_details_for_calling",
        "bucket": intelix_team,
        "info": "function finish"
    })
    # order by principal amount base on card COLL-472
    account_payments_sent_to_vendor = account_payments.extra(select={
        'type': "'inhouse_to_vendor'",
        'account_payment_id': 'account_payment_id', 'reason': '%s'},
        select_params=(
            CollectionAssignmentConstant.ASSIGNMENT_REASONS['ACCOUNT_SYSTEM_TRANSFERRED_VENDOR'],)
    ).values(
        "account_payment_id", "type", "reason").order_by('-principal_amount')
    logger.info({
        "action": "b4_vendor_distribution",
        "bucket": intelix_team,
        "info": "set redis begin"
    })
    redisClient = get_redis_client()
    # not sent account payment
    redis_key = '{}_not_sent_account_payments_{}'.format(
        intelix_team, current_date
    )
    redisClient.set(redis_key, not_sent_account_payments)
    # query for send to dialer
    redis_key_query_for_dialer = '{}_account_payment_ids_for_dialer_{}'.format(
        intelix_team, current_date
    )
    account_payment_for_dialer_ids = list(account_payments.values_list('id', flat=True))
    if account_payment_for_dialer_ids:
        redisClient.set_list(
            redis_key_query_for_dialer, list(account_payments.values_list('id', flat=True))
        )
    logger.info({
        "action": "b4_vendor_distribution",
        "bucket": intelix_team,
        "info": "set redis finish"
    })
    process_assign_account_payments_to_vendor_round_robin_method.delay(
        list(account_payments_sent_to_vendor),
        CollectionVendorCodes.VENDOR_TYPES.get('b4'),
        intelix_team=intelix_team
    )


@task(queue="collection_dialer_high")
def trigger_expiry_vendor_b4_j1():
    logger.info({
        "action": "trigger_expiry_vendor_b4_j1",
        "info": "B4 flow begin"
    })
    # make account payment that already reach b5 expired
    set_expired_from_vendor_b4_account_payment_reach_b5()
    b4_vendors_ratios = CollectionVendorRatio.objects.filter(
        vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('b4'),
    )
    for b4_vendors_ratio in b4_vendors_ratios:
        check_expiration_b4_vendor_assignment_for_j1(b4_vendors_ratio)

    # upload to intelix first for cohort
    # remaining will assign to vendor
    # will trigger to upload_julo_b4_data_to_intelix.delay()
    trigger_chain_b5_j1(IntelixTeam.JULO_B4_NC)


def trigger_chain_b4_process(intelix_team, is_trigger_chain):
    if intelix_team == IntelixTeam.JULO_B4:
        b4_vendor_distribution.delay(IntelixTeam.JULO_B4_NC)
    else:
        if is_trigger_chain:
            trigger_chain_b5_j1(intelix_team)


@task(queue='collection_dialer_high')
def process_assign_account_payments_to_vendor_round_robin_method(
        data_account_payments, vendor_type, intelix_team=None, is_trigger_chain=True):
    logger.info({
        "action": "process_assign_account_payments_to_vendor_round_robin_method",
        "bucket": intelix_team,
        "info": "function begin"
    })
    data_account_payments = serialize_data_for_sent_to_vendor(data_account_payments)
    if not data_account_payments:
        logger.warn({
            "action": "process_assign_account_payments_to_vendor_round_robin_method",
            "bucket": intelix_team,
            "info": "no data account payment"
        })
        trigger_chain_b4_process(intelix_team, is_trigger_chain)
        return

    collection_vendor_ratios = CollectionVendorRatio.objects.filter(
        **{'vendor_types': vendor_type, 'collection_vendor__is_active': True,
           'collection_vendor__is_{}'.format(vendor_type.lower()): True,
           'account_distribution_ratio__gt': 0
           }
    ).order_by('-account_distribution_ratio', 'collection_vendor_id')
    if not collection_vendor_ratios:
        trigger_chain_b4_process(intelix_team, is_trigger_chain)
        return

    process_assign_b4_account_payments_to_vendor(data_account_payments, collection_vendor_ratios)
    trigger_chain_b4_process(intelix_team, is_trigger_chain)


@task(queue='collection_dialer_high')
def process_assign_account_payments_to_vendor_round_robin_method_improved(
        bucket_name, vendor_type, dialer_task_id):
    dialer_task = DialerTask.objects.filter(pk=dialer_task_id).last()
    if not dialer_task:
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.FAILURE_ASSIGN.format(bucket_name)),
            error_message='dialer task is null')
        return
    redis_client = get_redis_client()
    redis_key = RedisKey.DATA_FOR_STORE_TO_COLLECTION_VENDOR_ASSIGNMENT.\
        format(bucket_name)

    try:
        cache_grouped_account_payment_ids = redis_client.get_list(redis_key)
        cache_data_account_payment_ids = list(map(int, cache_grouped_account_payment_ids))
        account_payments = AccountPayment.objects.filter(
            id__in=cache_data_account_payment_ids)
        data_account_payments = list(account_payments.extra(select={
            'type': "'inhouse_to_vendor'",
            'account_payment_id': 'account_payment_id', 'reason': '%s'},
            select_params=(
                CollectionAssignmentConstant.
                ASSIGNMENT_REASONS['ACCOUNT_SYSTEM_TRANSFERRED_VENDOR'],)
        ).values(
            "account_payment_id", "type", "reason").order_by('-principal_amount'))
        data_account_payments = serialize_data_for_sent_to_vendor(data_account_payments)
        if not data_account_payments:
            create_history_dialer_task_event(dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.FAILURE_ASSIGN.format(bucket_name)),
                error_message='data account payment is null')
            return
        collection_vendor_ratios = CollectionVendorRatio.objects.filter(
            **{
                'vendor_types': vendor_type,
                'collection_vendor__is_active': True,
                'collection_vendor__is_{}'.format(vendor_type.lower()): True,
                'account_distribution_ratio__gt': 0
            }
        ).order_by('-account_distribution_ratio', 'collection_vendor_id')
        if not collection_vendor_ratios:
            create_history_dialer_task_event(dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.FAILURE_ASSIGN.format(bucket_name)),
                error_message='collection vendor is null')
            return
        create_history_dialer_task_event(dict(
            dialer_task=dialer_task, status=DialerTaskStatus.STORE_PROCESS))
        process_assign_b4_account_payments_to_vendor(
            data_account_payments, collection_vendor_ratios)
        create_history_dialer_task_event(
            dict(dialer_task=dialer_task, status=DialerTaskStatus.SUCCESS))
    except Exception as error:
        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.FAILURE_ASSIGN.format(bucket_name)
            ), error_message=str(error)
        )
        get_julo_sentry_client().captureException()
        return


@task(queue="collection_dialer_normal")
def bulk_transfer_vendor_async(csv_data, csv_file_name, transfer_reason=''):
    logger.info({
        'action': 'bulk_transfer_vendor_async',
        'status': 'start',
        'identifier': csv_file_name
    })

    title = "Success Process bulk transfer vendor"
    csvfile = io.StringIO(csv_data)
    reader = csv.DictReader(csvfile)
    current_time = timezone.localtime(timezone.now())

    with TempDir() as tempdir:
        file_name = 'failed_processed_{}.csv'.format(str(current_time.strftime("%Y-%m-%d-%H:%M")))
        failed_processed_csv_file = os.path.join(tempdir.path, file_name)
        failed_processed = []
        for row in reader:
            if not row.get('application_xid') or not row.get('vendor_id'):
                continue

            application_xid = row['application_xid']
            vendor_id = row['vendor_id']
            try:
                if not application_xid or not vendor_id:
                    continue

                application = Application.objects.filter(
                    application_xid=application_xid).last()
                if not application:
                    raise Exception(
                        'Application xid tidak ditemukan/ tidak terhubung dengan account')

                new_vendor = CollectionVendor.objects.filter(pk=vendor_id).last()
                if not new_vendor:
                    raise Exception('Vendor ID tidak tersedia')

                if not new_vendor.is_active:
                    raise Exception('Vendor tujuan tidak aktif')

                account = application.account
                is_julo_one = False
                if account:
                    is_julo_one = True
                    account_payment = account.get_last_unpaid_account_payment()
                    if not account_payment:
                        raise Exception('Account tidak memiliki due')

                    CollectionVendorAssignment.objects.filter(
                        is_active_assignment=True, account_payment=account_payment.id
                    ).update(is_active_assignment=False, unassign_time=current_time)
                    AgentAssignment.objects.filter(
                        is_active_assignment=True, account_payment=account_payment.id
                    ).update(is_active_assignment=False)
                    is_processed, message = assign_new_vendor(
                        account_payment, new_vendor, is_julo_one, transfer_reason
                    )
                    if not is_processed:
                        raise Exception('DPD Account tidak sesuai dengan vendor ID')
                else:
                    loan = Loan.objects.get_or_none(application=application)
                    if not loan:
                        raise Exception('loan is not found')

                    payment = loan.get_oldest_unpaid_payment()
                    if not payment:
                        raise Exception('payment is not found')

                    AgentAssignment.objects.filter(
                        is_active_assignment=True, payment__loan_id=loan.id
                    ).update(is_active_assignment=False)
                    CollectionVendorAssignment.objects.filter(
                        is_active_assignment=True, payment=payment.id
                    ).update(is_active_assignment=False, unassign_time=current_time)
                    is_processed, message = assign_new_vendor(
                        payment, new_vendor, is_julo_one, transfer_reason)
                    if not is_processed:
                        raise Exception('DPD Account tidak sesuai dengan vendor ID')
            except Exception as e:
                failed_processed.append([application_xid, vendor_id, str(e)])
                continue

        notification_message = "{} for {}".format(title, csv_file_name)

        if settings.ENVIRONMENT != 'prod':
            header = "Testing Purpose from {} \n".format(settings.ENVIRONMENT)
            notification_message = header + notification_message

        if not failed_processed:
            notification_message = "{} dont have failed process".format(notification_message)
            send_message_normal_format(
                message=notification_message, channel='#b5-vendor-assignment-alert')
        else:
            with open(failed_processed_csv_file, 'w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(['application_xid', 'vendor_id', 'message'])  # Write the header row
                writer.writerows(failed_processed)  # Write the data rows

            slack_notify_and_send_csv_files(
                message=notification_message,
                csv_path=failed_processed_csv_file, channel='#b5-vendor-assignment-alert',
                file_name=file_name)

    logger.info({
        'action': 'bulk_transfer_vendor_async',
        'status': 'finish',
        'identifier': csv_file_name
    })
