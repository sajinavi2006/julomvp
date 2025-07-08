from __future__ import print_function
from builtins import map
import decimal

from django.contrib.auth.models import User
import datetime
from django.db import transaction
import logging
import math
import numpy
import ast

from juloserver.account_payment.models import AccountPayment
from juloserver.collection_vendor.constant import (
    CollectionVendorCodes,
    CollectionVendorAssignmentConstant, CollectionAssignmentConstant
)
from juloserver.collection_vendor.models import (
    CollectionVendor,
    CollectionVendorRatio,
    SubBucket,
    CollectionVendorAssigmentTransferType,
    CollectionVendorAssignment,
    AgentAssignment,
    CollectionVendorAssignmentTransfer, VendorReportErrorInformation,
    CollectionAssignmentHistory
)
from django.utils import timezone
from datetime import timedelta

from juloserver.collops_qa_automation.models import RecordingReport
from juloserver.julo.constants import (
    BucketConst,
    FeatureNameConst,
)
from juloserver.julo.models import (
    PTP,
    PaymentEvent,
    SkiptraceHistory,
    ApplicationNote,
    SkiptraceResultChoice,
    Application,
    Payment,
    FeatureSetting,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import WaiverRequest, LoanRefinancingRequest
from juloserver.minisquad.constants import (
    CenterixCallResult,
    IntelixTeam,
    ReasonNotSentToDialer,
    DEFAULT_DB,
)
from django.db.models import (
    Aggregate,
    CharField,
    Count,
    When,
    Case,
    IntegerField,
)
from juloserver.account.models import Account
from juloserver.minisquad.models import (
    CollectionDialerTemporaryData,
    NotSentToDialer,
    SentToDialer,
    CollectionBucketInhouseVendor
)
from juloserver.minisquad.services2.dialer_related import get_populated_data_for_calling
from juloserver.minisquad.exceptions import NullFreshAccountException

logger = logging.getLogger(__name__)


class Concat(Aggregate):
    function = 'string_agg'
    template = "%(function)s(%(distinct)s%(expressions)s::text, ',')"

    def __init__(self, expression, distinct=False, **extra):
        super(Concat, self).__init__(
            expression,
            distinct='DISTINCT ' if distinct else '',
            output_field=CharField(),
            **extra)


def validate_collection_vendor_name(new_vendor_name):
    check_existing = CollectionVendor.objects.normal().filter(
        vendor_name__iexact=new_vendor_name
    )
    if check_existing.count() > 0:
        return False
    return True


def delete_collection_vendors(collection_vendor_ids):
    CollectionVendor.objects.filter(
        id__in=collection_vendor_ids
    ).update(is_deleted=True)


def generate_collection_vendor_ratio(collection_vendor, created_by):
    selected_collection_vendor_types = []
    if collection_vendor.is_special:
        selected_collection_vendor_types.append(CollectionVendorCodes.VENDOR_TYPES.get('special'))

    if collection_vendor.is_general:
        selected_collection_vendor_types.append(CollectionVendorCodes.VENDOR_TYPES.get('general'))

    if collection_vendor.is_final:
        selected_collection_vendor_types.append(CollectionVendorCodes.VENDOR_TYPES.get('final'))

    if collection_vendor.is_b4:
        selected_collection_vendor_types.append(CollectionVendorCodes.VENDOR_TYPES.get('b4'))

    generated_collection_vendor_ratio = []
    for collection_vendor_type in selected_collection_vendor_types:
        is_exist_configuration = CollectionVendorRatio.objects.filter(
            collection_vendor=collection_vendor,
            vendor_types=collection_vendor_type
        ).count()
        if is_exist_configuration > 0:
            continue

        generated_collection_vendor_ratio.append(
            CollectionVendorRatio(
                collection_vendor=collection_vendor,
                vendor_types=collection_vendor_type,
                account_distribution_ratio=0,
                created_by=created_by,
            )
        )
    CollectionVendorRatio.objects.bulk_create(generated_collection_vendor_ratio)


def get_grouped_collection_vendor_ratio(queryset):
    return queryset.exclude(collection_vendor__is_deleted=True).values('vendor_types').annotate(
        vendor_names=Concat('collection_vendor__vendor_name', distinct=True),
        account_distribution_ratios=Concat('account_distribution_ratio', distinct=False),
        vendor_ratio_ids=Concat('id', distinct=False),
    )


def get_current_sub_bucket(oldest_payment, is_julo_one=False, is_bucket_4=False):
    if is_bucket_4:
        return SubBucket.objects.filter(bucket=4).last()

    dpd = oldest_payment.due_late_days
    if is_julo_one:
        dpd = oldest_payment.dpd

    sub_bucket_item = SubBucket.objects.filter(
        end_dpd__gte=dpd, start_dpd__lte=dpd).first()
    if sub_bucket_item:
        return sub_bucket_item
    sub_bucket_item = SubBucket.sub_bucket_six(4)
    if dpd >= sub_bucket_item.start_dpd:
        return sub_bucket_item

    if not is_julo_one:
        loan = oldest_payment.loan
        if loan.ever_entered_B5:
            return SubBucket.objects.filter(bucket=5).first()
    else:
        loan_eligible_to_b5 = Payment.objects.filter(
            account_payment=oldest_payment,
            loan__ever_entered_B5=True
        )
        if loan_eligible_to_b5:
            return SubBucket.objects.filter(bucket=5).first()

    return False


def is_payment_have_active_ptp(payment):
    today = timezone.localtime(timezone.now()).date()
    tomorrow = timezone.localtime(timezone.now() + timedelta(days=1)).date()
    ptp = PTP.objects.filter(payment=payment, ptp_amount__gt=payment.paid_amount).last()
    if ptp and ptp.ptp_date in [today, tomorrow]:
        return True

    return False


def drop_zeros(number):
    mynum = decimal.Decimal(number).normalize()
    return mynum.__trunc__() if not mynum % 1 else float(mynum)


def determine_first_vendor_should_assign(exclude_vendor_ratio, is_block_old_vendor=True):
    vendor_type = exclude_vendor_ratio.vendor_types
    exclude_vendor_ratio_dictionary = {
        'vendor__is_active': False,
        'vendor__is_{}'.format(vendor_type.lower()): False,
        'vendor_configuration__account_distribution_ratio': float(0)
    }
    filter_vendor_ratio_dictionary = {
        'vendor__is_active': True,
        'vendor__is_{}'.format(vendor_type.lower()): True,
        'vendor_configuration__account_distribution_ratio__gt': float(0),
        'vendor_configuration__vendor_types': exclude_vendor_ratio.vendor_types
    }
    filter_exlude_old_vendor = {}
    if is_block_old_vendor:
        filter_exlude_old_vendor = dict(vendor_configuration=exclude_vendor_ratio,)
    vendor_ratios = CollectionVendorAssignment.objects.filter(
        **filter_vendor_ratio_dictionary
    ).exclude(
        **filter_exlude_old_vendor
    ).exclude(
        **exclude_vendor_ratio_dictionary
    ).values('vendor_configuration').annotate(
        total=Count('vendor_configuration')
    ).order_by('total')
    collection_vendor_ratios_filter = {
        'vendor_types': exclude_vendor_ratio.vendor_types,
        'collection_vendor__is_{}'.format(vendor_type.lower()): True,
        'collection_vendor__is_active': True,
        'account_distribution_ratio__gt': float(0)
    }
    collection_vendor_ratios = CollectionVendorRatio.objects.filter(
        **collection_vendor_ratios_filter
    )
    if is_block_old_vendor:
        collection_vendor_ratios = collection_vendor_ratios.exclude(pk=exclude_vendor_ratio.id)
    if len(vendor_ratios) != len(collection_vendor_ratios):
        exclude_id = []
        if not vendor_ratios:
            vendor_ratios = []
        else:
            exclude_id = [
                vendor_ratio['vendor_configuration'] for vendor_ratio in vendor_ratios
            ]
            vendor_ratios = list(vendor_ratios)

        collection_vendor_ratio_ids = collection_vendor_ratios.exclude(
            pk__in=exclude_id
        ).exclude(collection_vendor__is_active=False).order_by(
            'account_distribution_ratio').values_list('id', flat=True)

        for collection_vendor_ratio_id in collection_vendor_ratio_ids:
            vendor_ratios.insert(0, {'vendor_configuration': collection_vendor_ratio_id})

    return vendor_ratios


def format_assigment_transfer_from(assigned_from, is_julo_one=False):
    context = {}
    if is_julo_one:
        account_payment = assigned_from.account_payment
        account = account_payment.account
        application = account.application_set.last()
        context['dpd_today'] = account_payment.dpd
        sub_bucket_today = get_current_sub_bucket(account_payment, is_julo_one)
        loan_id = '-'
        payment_id = '-'
        account_payment_id = account_payment.id
    else:
        payment = assigned_from.payment
        application = payment.loan.application
        sub_bucket_today = get_current_sub_bucket(payment)
        context['dpd_today'] = payment.due_late_days
        loan_id = payment.loan.id
        payment_id = payment.id
        account_payment_id = '-'

    customer = application.customer
    context['application_id'] = application.id
    context['assign_time'] = assigned_from.assign_time.date()
    context['dpd_assign_time'] = assigned_from.dpd_assign_time
    context['sub_bucket_assign_time'] = assigned_from.sub_bucket_assign_time.sub_bucket_label
    context['sub_bucket_today'] = '-'
    if sub_bucket_today:
        context['sub_bucket_today'] = sub_bucket_today.sub_bucket_label

    context['loan_id'] = loan_id
    context['payment_id'] = payment_id
    context['account_payment_id'] = account_payment_id
    context['customer_name'] = customer.fullname
    context['customer_email'] = customer.email
    context['transfer_from'] = assigned_from
    if type(assigned_from) is AgentAssignment:
        context['transfer_from'] = 'Agent ({})'.format(assigned_from)

    context['transfer_from_id'] = assigned_from.id
    return context


def check_vendor_assignment(vendor_ratio):
    vendor_type = vendor_ratio.vendor_types.lower()
    today = timezone.localtime(timezone.now())
    expire_assignment = today - timedelta(
        days=CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.__dict__[vendor_type]
    )
    collection_vendor_assignments = CollectionVendorAssignment.objects.filter(
        vendor_configuration=vendor_ratio,
        assign_time__lt=expire_assignment,
        is_active_assignment=True,
        payment__isnull=False,
        assign_time__isnull=False
    ).distinct('payment_id')

    if not collection_vendor_assignments:
        return

    vendor_ratios = determine_first_vendor_should_assign(vendor_ratio)
    key_vendor = 0
    reassign_payments_data = []
    max_dpd = 180 if vendor_type == 'special' else 720
    history_movement = []

    for collection_vendor_assignment in collection_vendor_assignments:
        payment = collection_vendor_assignment.payment
        active_collection_vendor_assigments = CollectionVendorAssignment.objects.filter(
            vendor_configuration=vendor_ratio,
            assign_time__lt=expire_assignment,
            is_active_assignment=True,
            payment=payment
        )

        if collection_vendor_assignment.is_extension:
            if not collection_vendor_assignment.get_expiration_assignment:
                continue

            end_period_retain = \
                collection_vendor_assignment.get_expiration_assignment + timedelta(days=30)

            if today.date() > end_period_retain.date():
                history_movement.append(
                    format_and_create_single_movement_history(
                        payment, None,
                        reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                            'ASSIGNMENT_EXPIRED_VENDOR_END'],
                        is_julo_one=False, is_only_formated=True
                    )
                )

                active_collection_vendor_assigments.update(
                    unassign_time=today,
                    is_active_assignment=False
                )

            continue

        if vendor_type == 'special' and payment.due_late_days > max_dpd:
            history_movement.append(
                format_and_create_single_movement_history(
                    payment, None,
                    reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                        'ASSIGNMENT_EXPIRED_VENDOR_END'],
                    is_julo_one=False, is_only_formated=True
                )
            )

            active_collection_vendor_assigments.update(
                unassign_time=today,
                is_active_assignment=False
            )

            continue

        if vendor_type != 'special' and payment.due_late_days < max_dpd:
            continue

        collection_vendor_ratio = CollectionVendorRatio.objects.get_or_none(
            pk=vendor_ratios[key_vendor]['vendor_configuration'])

        sub_bucket = get_current_sub_bucket(payment)

        transfer_account = CollectionVendorAssignmentTransfer.objects.create(
            payment=payment,
            transfer_from=collection_vendor_ratio.collection_vendor,
            transfer_from_id=collection_vendor_assignment.vendor.id,
            transfer_to_id=collection_vendor_ratio.collection_vendor.id,
            transfer_type=CollectionVendorAssigmentTransferType.vendor_to_vendor(),
        )

        # create history for transfer from other vendor to other vendor
        history_movement.append(
            format_and_create_single_movement_history(
                collection_vendor_assignment.payment, collection_vendor_ratio.collection_vendor,
                reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ASSIGNMENT_EXPIRED_VENDOR_END'],
                is_julo_one=False, is_only_formated=True)
        )

        active_collection_vendor_assigments.update(
            is_active_assignment=False,
            unassign_time=today,
            is_transferred_to_other=True,
            collection_vendor_assigment_transfer=transfer_account
        )

        reassign_payments_data.append(CollectionVendorAssignment(
            vendor=collection_vendor_ratio.collection_vendor,
            vendor_configuration=collection_vendor_ratio,
            payment=payment,
            sub_bucket_assign_time=sub_bucket,
            dpd_assign_time=payment.due_late_days,
            is_transferred_from_other=True)
        )

        key_vendor = key_vendor + 1 if key_vendor != (len(vendor_ratios) - 1) else 0

    create_record_movement_history(history_movement)
    CollectionVendorAssignment.objects.bulk_create(reassign_payments_data)


def check_vendor_assignment_for_j1(vendor_ratio):
    vendor_type = vendor_ratio.vendor_types.lower()
    today = timezone.localtime(timezone.now())
    expire_assignment = today - timedelta(
        days=CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.__dict__[vendor_type]
    )
    collection_vendor_assignments = CollectionVendorAssignment.objects.filter(
        vendor_configuration=vendor_ratio,
        assign_time__lt=expire_assignment,
        is_active_assignment=True,
        account_payment__isnull=False,
        assign_time__isnull=False
    ).distinct('account_payment_id')

    if not collection_vendor_assignments:
        return

    vendor_ratios = determine_first_vendor_should_assign(vendor_ratio)
    today = timezone.localtime(timezone.now())
    key_vendor = 0
    reassign_payments_data = []
    history_movement = []
    max_dpd = 180 if vendor_type == 'special' else 720

    for collection_vendor_assignment in collection_vendor_assignments:

        account_payment = collection_vendor_assignment.account_payment
        active_collection_vendor_assigments = CollectionVendorAssignment.objects.filter(
            vendor_configuration=vendor_ratio,
            assign_time__lt=expire_assignment,
            is_active_assignment=True,
            account_payment=account_payment
        )

        if collection_vendor_assignment.is_extension:
            if not collection_vendor_assignment.get_expiration_assignment:
                continue

            end_period_retain = \
                collection_vendor_assignment.get_expiration_assignment + timedelta(days=30)

            if today.date() > end_period_retain.date():
                history_movement.append(
                    format_and_create_single_movement_history(
                        account_payment, None,
                        reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                            'ASSIGNMENT_EXPIRED_VENDOR_END'],
                        is_julo_one=True, is_only_formated=True
                    )
                )
                active_collection_vendor_assigments.update(
                    unassign_time=today,
                    is_active_assignment=False
                )

            continue

        account_payment = collection_vendor_assignment.account_payment

        if vendor_type == 'special' and account_payment.dpd > max_dpd:
            history_movement.append(
                format_and_create_single_movement_history(
                    collection_vendor_assignment.account_payment, None,
                    reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                        'ASSIGNMENT_EXPIRED_VENDOR_END'],
                    is_julo_one=True, is_only_formated=True
                )
            )

            active_collection_vendor_assigments.update(
                is_active_assignment=False,
                unassign_time=today,
            )
            continue

        if vendor_type != 'special' and account_payment.dpd < max_dpd:
            continue

        collection_vendor_ratio = CollectionVendorRatio.objects.get_or_none(
            pk=vendor_ratios[key_vendor]['vendor_configuration'])
        sub_bucket = get_current_sub_bucket(account_payment, is_julo_one=True)

        transfer_account = CollectionVendorAssignmentTransfer.objects.create(
            account_payment=account_payment,
            transfer_from=collection_vendor_ratio.collection_vendor,
            transfer_from_id=collection_vendor_assignment.vendor.id,
            transfer_to_id=collection_vendor_ratio.collection_vendor.id,
            transfer_type=CollectionVendorAssigmentTransferType.vendor_to_vendor(),
        )

        # create history for transfer from other vendor to other vendor
        history_movement.append(
            format_and_create_single_movement_history(
                collection_vendor_assignment.account_payment,
                collection_vendor_ratio.collection_vendor,
                reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ASSIGNMENT_EXPIRED_VENDOR_END'],
                is_julo_one=True, is_only_formated=True)
        )
        active_collection_vendor_assigments.update(
            is_active_assignment=False,
            unassign_time=today,
            is_transferred_to_other=True,
            collection_vendor_assigment_transfer=transfer_account
        )

        reassign_payments_data.append(CollectionVendorAssignment(
            vendor=collection_vendor_ratio.collection_vendor,
            vendor_configuration=collection_vendor_ratio,
            account_payment=account_payment,
            sub_bucket_assign_time=sub_bucket,
            dpd_assign_time=account_payment.dpd,
            is_transferred_from_other=True)
        )

        key_vendor = key_vendor + 1 if key_vendor != (len(vendor_ratios) - 1) else 0

    create_record_movement_history(history_movement)
    CollectionVendorAssignment.objects.bulk_create(reassign_payments_data)


def get_expired_vendor_assignment(expire_time, sub_bucket):
    collection_vendor_assignments = CollectionVendorAssignment.objects.filter(
        assign_time__date__lt=expire_time.date(),
        sub_bucket_assign_time=sub_bucket,
        is_active_assignment=True
    )
    return collection_vendor_assignments


def allocated_oldest_payment_without_active_ptp(assigned_payments, should_allocated_count):
    allocated_from_agent_to_vendor_assignment_payment_ids = []
    allocated_not_active_ptp = 0
    index = 0
    while allocated_not_active_ptp != should_allocated_count:
        oldest_assigned = assigned_payments[index]
        if not is_payment_have_active_ptp(oldest_assigned.payment):
            # send to collection vendor get oldest assignment
            allocated_from_agent_to_vendor_assignment_payment_ids.append(
                oldest_assigned.payment.id
            )
            allocated_not_active_ptp = allocated_not_active_ptp + 1

        index = index + 1

    return allocated_from_agent_to_vendor_assignment_payment_ids


def allocated_to_vendor_for_payment_less_then_fifty_thousand(payments):
    allocated_to_vendor_for_payment_less_then_50000_payment_ids = []
    for payment in payments:
        loan = payment.loan
        payment_ids = loan.payment_set.all().values_list('id', flat=True)
        payment_event = PaymentEvent.objects.filter(
            event_type='payment',
            payment__id__in=payment_ids).order_by('-cdate').first()
        if payment_event:
            if payment_event.event_payment <= 50000:
                allocated_to_vendor_for_payment_less_then_50000_payment_ids.append(
                    payment.id)
        else:
            allocated_to_vendor_for_payment_less_then_50000_payment_ids.append(payment.id)

    return allocated_to_vendor_for_payment_less_then_50000_payment_ids


def is_send_to_vendor_for_last_contacted(payment_or_account_payment, is_julo_one=False):
    filter_dict = dict()
    if is_julo_one:
        account = payment_or_account_payment.account
        filter_dict['account'] = account
    else:
        loan = payment_or_account_payment.loan
        filter_dict['loan'] = loan

    select_dict = {
        'date': "(skiptrace_history.cdate AT TIME ZONE 'Asia/Jakarta')::date"
    }
    skiptrace_history = SkiptraceHistory.objects.filter(**filter_dict).order_by('cdate')

    if not skiptrace_history:
        return False

    latest_history = skiptrace_history.last()
    first_history = skiptrace_history.first()
    first_called_date = timezone.localtime(first_history.cdate).date()
    last_called_date = timezone.localtime(latest_history.cdate).date()
    call_result_names = CenterixCallResult.RPC + CenterixCallResult.WPC
    filter_dict['cdate__date__range'] = (first_called_date, last_called_date)
    # todo need confirm with debora
    call_histories = SkiptraceHistory.objects.extra(
        select=select_dict).values('date') \
        .filter(**filter_dict) \
        .annotate(rpc_calls=Count(Case(When(
            call_result__name__in=call_result_names, then=1), output_field=IntegerField())))
    threshold_count = 0
    for call_history in call_histories:
        if call_history['rpc_calls'] == 0:
            threshold_count += 1

    return threshold_count >= 30


def allocated_to_vendor_for_payment_last_contacted_more_thirty_days(payments, is_julo_one=False):
    assigned_payment_to_vendor_last_contacted_payment_ids = []
    for payment in payments:
        if is_send_to_vendor_for_last_contacted(payment, is_julo_one):
            assigned_payment_to_vendor_last_contacted_payment_ids.append(payment.id)

    return assigned_payment_to_vendor_last_contacted_payment_ids


def allocated_to_vendor_for_last_payment_more_then_sixty_days(payments):
    allocated_payment_with_last_payment_gte_60_payment_ids = []
    due_date_plus_60 = timezone.localtime(timezone.now() - timedelta(days=60)).date()
    for payment in payments:
        loan = payment.loan
        payment_ids = loan.payment_set.all().values_list('id', flat=True)
        payment_events = PaymentEvent.objects.filter(
            event_type='payment',
            payment__id__in=payment_ids)
        if not payment_events:
            allocated_payment_with_last_payment_gte_60_payment_ids.append(payment.id)
        else:
            last_60_days_payment = payment_events.order_by('-cdate').first()
            if last_60_days_payment.event_date <= due_date_plus_60:
                allocated_payment_with_last_payment_gte_60_payment_ids.append(payment.id)

    return allocated_payment_with_last_payment_gte_60_payment_ids


def check_active_ptp_agent_assignment(payment_or_account_payment, is_julo_one=False):
    if is_julo_one:
        ptp_filter = dict(
            account_payment=payment_or_account_payment,
        )
        application = payment_or_account_payment.account.application_set.last()
    else:
        ptp_filter = dict(
            payment=payment_or_account_payment,
        )
        application = payment_or_account_payment.loan.application

    ptp = PTP.objects.filter(**ptp_filter).last()
    today = timezone.localtime(timezone.now()).date()
    yesterday = timezone.localtime(timezone.now() - timedelta(days=1)).date()
    tomorrow = timezone.localtime(timezone.now() + timedelta(days=1)).date()
    last_agent_check = ''
    if ptp and ptp.ptp_date in [today, tomorrow]:
        last_agent_check = ptp.agent_assigned.username

    if ptp and ptp.ptp_date == yesterday:
        ApplicationNote.objects.create(
            note_text="Broken PTP", application_id=application.id, application_history_id=None
        )

    return last_agent_check


def last_agent_active_waiver_request(payment_or_account_payment, is_julo_one=False):
    today = timezone.localtime(timezone.now()).date()
    filter_expired_waiver_request = dict(
        waiver_validity_date__gte=today,
        program_name__in=list(map(str.lower, CovidRefinancingConst.waiver_products()))
    )
    filter_loan_refinancing_request = dict(
        status__in=(
            CovidRefinancingConst.STATUSES.offer_selected,
            CovidRefinancingConst.STATUSES.approved,
        )
    )

    if is_julo_one:
        account = payment_or_account_payment.account
        filter_expired_waiver_request['account'] = account
        filter_loan_refinancing_request['account'] = account
    else:
        loan = payment_or_account_payment.loan
        filter_expired_waiver_request['loan'] = loan
        filter_loan_refinancing_request['loan'] = loan

    expired_waiver_request = WaiverRequest.objects.filter(
        **filter_expired_waiver_request
    ).last()
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        **filter_loan_refinancing_request
    ).last()
    if expired_waiver_request and loan_refinancing_request:
        return expired_waiver_request.agent_name

    return None


def get_loan_ids_have_waiver_already():
    today = timezone.localtime(timezone.now()).date()
    waiver_loan_ids = WaiverRequest.objects.filter(
        waiver_validity_date__gte=today,
        program_name__in=list(map(str.lower, CovidRefinancingConst.waiver_products()))
    ).values_list('loan_id', flat=True)
    loan_refinancing_loan_ids = LoanRefinancingRequest.objects.filter(
        loan_id__in=waiver_loan_ids, status__in=(
            CovidRefinancingConst.STATUSES.offer_selected,
            CovidRefinancingConst.STATUSES.approved,
        )
    ).values_list('loan_id', flat=True)
    return loan_refinancing_loan_ids


def validate_data_calling_result(data_xls):
    errors = []
    for row_data in data_xls:
        identifier = {'key': None, 'value': None}

        if 'application xid' in row_data:
            identifier = {
                'value': row_data['application xid'],
                'key': 'application xid'
            }
        elif 'account id' in row_data:
            identifier = {
                'value': row_data['account id'],
                'key': 'account id'
            }

        if 'application xid' in row_data and 'account id' in row_data:
            errors.append({
                'identifier': identifier['key'],
                'identifier_id': identifier['value'],
                'error_detail': {
                    'fields': identifier['key'],
                    'error_reason': 'application xid dan account id tidak boleh diisi bersamaan, '
                                    'mohon isi salah satu',
                    'value': identifier['value'],
                }
            })
        elif 'application xid' not in row_data and 'account id' not in row_data:
            errors.append({
                'identifier': None,
                'identifier_id': None,
                'error_detail': {
                    'fields': 'Application xid / Account Id',
                    'error_reason': 'Data tidak terisi. Mohon isi dengan data yang sesuai',
                    'value': None,
                }
            })

        if identifier['value']:
            if identifier['value'].isdigit():
                application = None
                account = None
                if 'application xid' in row_data:
                    application = Application.objects.filter(
                        application_xid=int(identifier['value'])
                    ).last()
                elif 'account id' in row_data:
                    account = Account.objects.get_or_none(pk=int(identifier['value']))

                if not application and not account:
                    errors.append({
                        'identifier': identifier['key'],
                        'identifier_id': identifier['value'],
                        'error_detail': {
                            'fields': identifier['key'],
                            'error_reason': 'ID tidak terdaftar di database JULO. Mohon periksa '
                                            'kembali ID yang di-input.',
                            'value': identifier['value'],
                        }
                    })
            else:
                errors.append({
                    'identifier': identifier['key'],
                    'identifier_id': identifier['value'],
                    'error_detail': {
                        'fields': identifier['key'],
                        'error_reason': 'Harus angka. Mohon perbaiki data.',
                        'value': identifier['value'],
                    }
                })

        if 'collector id' in row_data:
            if row_data['collector id'].isdigit():
                collector = User.objects.filter(pk=int(row_data['collector id'])).last()
                if not collector:
                    errors.append({
                        'identifier': identifier['key'],
                        'identifier_id': identifier['value'],
                        'error_detail': {
                            'fields': 'Collector ID',
                            'error_reason': 'ID tidak terdaftar di database JULO. Mohon periksa '
                                            'kembali ID yang di-input ATAU request untuk '
                                            'buat ID baru jika Agent belum terdaftar',
                            'value': row_data['collector id'],
                        }
                    })
            else:
                errors.append(
                    {
                        'identifier': identifier['key'],
                        'identifier_id': identifier['value'],
                        'error_detail': {
                            'fields': 'Collector ID',
                            'error_reason': 'Harus angka. Mohon perbaiki data.',
                            'value': row_data['collector id'],
                        }
                    }
                )
        else:
            errors.append({
                'identifier': identifier['key'],
                'identifier_id': identifier['value'],
                'error_detail': {
                    'fields': 'Collector ID',
                    'error_reason': 'Data tidak terisi. Mohon isi dengan data yang sesuai',
                    'value': None,
                }
            })

        if 'waktu visit/penelponan' in row_data:
            try:
                datetime.datetime.strptime(row_data['waktu visit/penelponan'], '%d-%m-%Y, %H.%M')
            except Exception:
                errors.append({
                    'identifier': identifier['key'],
                    'identifier_id': identifier['value'],
                    'error_detail': {
                        'fields': 'Waktu Visit/Penelponan',
                        'error_reason': 'Tanggal/Jam tidak valid. Mohon perbaiki data',
                        'value': row_data['waktu visit/penelponan'],
                    }
                })

        else:
            errors.append({
                'identifier': identifier['key'],
                'identifier_id': identifier['value'],
                'error_detail': {
                    'fields': 'Waktu Visit/Penelponan',
                    'error_reason': 'Data tidak terisi. Mohon isi dengan data yang sesuai',
                    'value': None,
                }
            })

        if 'phone number' in row_data:
            if not row_data['phone number'].isdigit():
                errors.append({
                    'identifier': identifier['key'],
                    'identifier_id': identifier['value'],
                    'error_detail': {
                        'fields': 'Phone Number',
                        'error_reason': 'Harus angka. Mohon perbaiki data.',
                        'value': row_data['phone number'],
                    }
                })
            elif row_data['phone number'][:2] != '62':
                errors.append({
                    'identifier': identifier['key'],
                    'identifier_id': identifier['value'],
                    'error_detail': {
                        'fields': 'Phone Number',
                        'error_reason': 'Phone Number harus diawali dengan 62',
                        'value': row_data['phone number'],
                    }
                })
        else:
            errors.append({
                'identifier': identifier['key'],
                'identifier_id': identifier['value'],
                'error_detail': {
                    'fields': 'Phone Number',
                    'error_reason': 'Data tidak terisi. Mohon isi dengan data yang sesuai',
                    'value': None,
                }
            })

        if 'action code' in row_data:
            if row_data['action code'].isdigit():
                skiptrace_result_choice = SkiptraceResultChoice.objects.filter(
                    pk=int(row_data['action code'])
                ).last()
                if not skiptrace_result_choice:
                    errors.append({
                        'identifier': identifier['key'],
                        'identifier_id': identifier['value'],
                        'error_detail': {
                            'fields': 'Action Code',
                            'error_reason': 'Action Code tidak terdaftar di database JULO. '
                                            'Mohon periksa kembali Action Code yang di-input',
                            'value': row_data['action code'],
                        }
                    })
            else:
                errors.append({
                    'identifier': identifier['key'],
                    'identifier_id': identifier['value'],
                    'error_detail': {
                        'fields': 'Action Code',
                        'error_reason': 'Harus angka. Mohon perbaiki data.',
                        'value': row_data['action code'],
                    }
                })
        else:
            errors.append({
                'identifier': identifier['key'],
                'identifier_id': identifier['value'],
                'error_detail': {
                    'fields': 'Action Code',
                    'error_reason': 'Data tidak terisi. Mohon isi dengan data yang sesuai',
                    'value': None,
                }
            })

        if 'ptp date' in row_data:
            try:
                datetime.datetime.strptime(row_data['ptp date'],
                                           '%d-%m-%Y')
            except Exception:
                errors.append({
                    'identifier': identifier['key'],
                    'identifier_id': identifier['value'],
                    'error_detail': {
                        'fields': 'ptp date',
                        'error_reason': 'Tanggal tidak valid. Mohon perbaiki data',
                        'value': row_data['ptp date'],
                    }
                })
        elif 'ptp date' not in row_data and 'action code' in row_data \
                and row_data['action code'] == '17':
            errors.append({
                'identifier': identifier['key'],
                'identifier_id': identifier['value'],
                'error_detail': {
                    'fields': 'PTP Date',
                    'error_reason': 'Action Code adalah 17 (PTP) dan data tidak terisi. '
                                    'Mohon isi dengan data yang sesuai',
                    'value': None,
                }
            })

        if 'ptp amount' in row_data:
            if not row_data['ptp amount'].isdigit():
                errors.append({
                    'identifier': identifier['key'],
                    'identifier_id': identifier['value'],
                    'error_detail': {
                        'fields': 'PTP Amount',
                        'error_reason': 'Harus angka. Mohon perbaiki data.',
                        'value': row_data['ptp amount'],
                    }
                })
        elif 'ptp amount' not in row_data and 'action code' in row_data \
             and row_data['action code'] == '17':
            errors.append({
                'identifier': identifier['key'],
                'identifier_id': identifier['value'],
                'error_detail': {
                    'fields': 'PTP Amount',
                    'error_reason': 'Action Code adalah 17 (PTP) dan data tidak terisi. '
                                    'Mohon isi dengan data yang sesuai',
                    'value': None,
                }
            })

    return True if not errors else False, errors


def store_error_information_calling_vendor_result(errors, upload_vendor_report):
    for error in errors:
        account = None
        application_xid = None
        if error['identifier_id'] and error['identifier_id'].isdigit():
            if error['identifier'] == 'application xid':
                application = Application.objects.filter(
                    application_xid=int(error['identifier_id'])
                ).last()
                application_xid = application.application_xid if application else None
            else:
                account = Account.objects.get_or_none(pk=int(error['identifier_id']))
        VendorReportErrorInformation.objects.create(
            upload_vendor_report=upload_vendor_report,
            account=account,
            application_xid=application_xid,
            field=error['error_detail']['fields'],
            error_reason=error['error_detail']['error_reason'],
            value=error['error_detail']['value']
        )


def get_account_ids_have_waiver_already_will_excluded_in_b5():
    today = timezone.localtime(timezone.now()).date()
    waiver_account_ids = WaiverRequest.objects.filter(
        waiver_validity_date__gte=today,
        program_name__in=list(map(str.lower, CovidRefinancingConst.waiver_products())),
        is_j1=True
    ).values_list('account_id', flat=True)
    loan_refinancing_account_ids = LoanRefinancingRequest.objects.filter(
        account_id__in=waiver_account_ids, status__in=(
            CovidRefinancingConst.STATUSES.offer_selected,
            CovidRefinancingConst.STATUSES.approved,
        )
    ).values_list('account_id', flat=True)
    return loan_refinancing_account_ids


def is_account_payment_have_active_ptp(account_payment):
    today = timezone.localtime(timezone.now()).date()
    ptp = PTP.objects.filter(account_payment=account_payment, ptp_date__gte=today).last()
    if ptp:
        return True

    return False


def allocated_oldest_account_payment_without_active_ptp(
        assigned_account_payments, should_allocated_count):
    allocated_from_agent_to_vendor_assignment_account_payment_ids = []
    allocated_not_active_ptp = 0
    index = 0
    while allocated_not_active_ptp != should_allocated_count:
        if index + 1 > len(assigned_account_payments):
            break

        oldest_assigned = assigned_account_payments[index]
        if not is_account_payment_have_active_ptp(oldest_assigned.account_payment):
            # send to collection vendor get oldest assignment
            allocated_from_agent_to_vendor_assignment_account_payment_ids.append(
                oldest_assigned.account_payment.id
            )
            allocated_not_active_ptp += 1

        index = index + 1

    return allocated_from_agent_to_vendor_assignment_account_payment_ids


def allocated_to_vendor_for_account_payment_less_then_fifty_thousand(account_payments):
    allocated_to_vendor_for_account_payment_less_then_50000_payment_ids = []
    for account_payment in account_payments:
        account = account_payment.account
        all_active_Loan_ids = account.get_all_active_loan().values_list(
            'id', flat=True)
        payment_ids = Payment.objects.filter(
            loan_id__in=all_active_Loan_ids
        ).values_list('id', flat=True)
        payment_event = PaymentEvent.objects.filter(
            event_type='payment',
            payment__id__in=payment_ids).order_by('-cdate').first()
        if payment_event:
            if payment_event.event_payment <= 50000:
                allocated_to_vendor_for_account_payment_less_then_50000_payment_ids.append(
                    account_payment.id)
        else:
            allocated_to_vendor_for_account_payment_less_then_50000_payment_ids.append(
                account_payment.id)

    return allocated_to_vendor_for_account_payment_less_then_50000_payment_ids


def allocated_to_vendor_for_last_account_payment_more_then_sixty_days(account_payments):
    allocated_payment_with_last_payment_gte_60_account_payment_ids = []
    due_date_plus_60 = timezone.localtime(timezone.now() - timedelta(days=60)).date()
    for account_payment in account_payments:
        account = account_payment.account
        all_active_Loan_ids = account.get_all_active_loan().values_list(
            'id', flat=True)
        payment_ids = Payment.objects.filter(
            loan_id__in=all_active_Loan_ids
        ).values_list('id', flat=True)
        payment_events = PaymentEvent.objects.filter(
            event_type='payment',
            payment__id__in=payment_ids)
        if not payment_events:
            allocated_payment_with_last_payment_gte_60_account_payment_ids.append(
                account_payment.id)
        else:
            last_60_days_payment = payment_events.order_by('-cdate').first()
            if last_60_days_payment.event_date <= due_date_plus_60:
                allocated_payment_with_last_payment_gte_60_account_payment_ids.append(
                    account_payment.id)

    return allocated_payment_with_last_payment_gte_60_account_payment_ids


def record_assignment_movement_history(
        payment_or_account_payment, new_assignment, reason,
        old_assignment=None, is_julo_one=True):

    if is_julo_one:
        record_assignment_movement_history_data = dict(
            account_payment=payment_or_account_payment
        )
    else:
        record_assignment_movement_history_data = dict(
            payment=payment_or_account_payment
        )

    record_assignment_movement_history_data.update(
        assignment_reason=reason,
        old_assignment=old_assignment,
        new_assignment=new_assignment
    )
    CollectionAssignmentHistory.objects.create(**record_assignment_movement_history_data)


def bulk_create_assignment_movement_history_base_on_agent_assignment(
        agent_assignments, reason, new_assignment=None):
    movement_history_data = []
    for agent_assignment in agent_assignments:
        data_param = dict(
            assignment_reason=reason,
            old_assignment=agent_assignment.agent,
            new_assignment=new_assignment,
        )
        if agent_assignment.account_payment:
            data_param.update(
                account_payment=agent_assignment.account_payment,
            )
        else:
            data_param.update(
                payment=agent_assignment.payment,
            )
        movement_history_data.append(
            CollectionAssignmentHistory(**data_param)
        )
    CollectionAssignmentHistory.objects.bulk_create(
        movement_history_data
    )


def format_and_create_single_movement_history(
        payment_or_account_payment, new_assignment, reason, is_julo_one=True,
        is_only_formated=False, old_assignment=None
):
    data_param = dict(
        account_payment=payment_or_account_payment,
        assignment_reason=reason,
        new_assignment=new_assignment
    )
    old_assignment_params = dict(
        is_active_assignment=True,
        account_payment=payment_or_account_payment,
    )
    if not is_julo_one:
        data_param = dict(
            payment=payment_or_account_payment,
            assignment_reason=reason,
            new_assignment=new_assignment
        )
        old_assignment_params = dict(
            is_active_assignment=True,
            payment=payment_or_account_payment
        )
    # set None meaning the data is from inhouse
    if not old_assignment:
        agent_assignment = AgentAssignment.objects.filter(**old_assignment_params).last()
        if agent_assignment:
            old_assignment = agent_assignment.agent
        if not old_assignment:
            collection_vendor_assignment = CollectionVendorAssignment.objects.filter(
                **old_assignment_params
            ).last()
            if collection_vendor_assignment:
                old_assignment = collection_vendor_assignment.vendor

    data_param.update(
        old_assignment=old_assignment
    )
    if is_only_formated:
        return CollectionAssignmentHistory(**data_param)

    create_record_movement_history(data_param)


def construct_data_for_send_to_vendor(
    account_payment_or_payment_ids_less_then_50000,
    account_payment_or_payment_last_contacted_ids,
    account_payment_or_payment_last_payment_gte_60_ids,
    account_payment_or_payment_passing_threshold_ids=None,
    agent_threshold=None,
    is_for_julo_one=True,
):
    all_allocated_vendor = []
    if not is_for_julo_one:
        for payment_id in account_payment_or_payment_ids_less_then_50000:
            all_allocated_vendor.append(
                dict(
                    payment_id=payment_id, type='inhouse_to_vendor',
                    reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                        'ACCOUNT_MOVED_VENDOR_PAYMENT_LTE_50K']
                )
            )
        for payment_id in account_payment_or_payment_last_contacted_ids:
            all_allocated_vendor.append(
                dict(
                    payment_id=payment_id, type='inhouse_to_vendor',
                    reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                        'ACCOUNT_MOVED_VENDOR_LAST_CONTACTED_GTE_30_DAYS']
                )
            )
        for payment_id in account_payment_or_payment_last_payment_gte_60_ids:
            all_allocated_vendor.append(
                dict(
                    payment_id=payment_id, type='inhouse_to_vendor',
                    reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                        'ACCOUNT_MOVED_VENDOR_LAST_PAYMENT_GTE_60_DAYS']
                )
            )

        if not account_payment_or_payment_passing_threshold_ids:
            return all_allocated_vendor

        for payment_id in account_payment_or_payment_passing_threshold_ids:
            all_allocated_vendor.append(
                dict(
                    payment_id=payment_id,
                    type='agent_to_vendor',
                    reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                        'ACCOUNT_MOVED_VENDOR_EXCEEDS_THRESHOLD'].format(agent_threshold)
                )
            )

        return all_allocated_vendor

    for account_payment_id in account_payment_or_payment_ids_less_then_50000:
        all_allocated_vendor.append(
            dict(
                account_payment_id=account_payment_id, type='inhouse_to_vendor',
                reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ACCOUNT_MOVED_VENDOR_PAYMENT_LTE_50K']
            )
        )
    for account_payment_id in account_payment_or_payment_last_contacted_ids:
        all_allocated_vendor.append(
            dict(
                account_payment_id=account_payment_id, type='inhouse_to_vendor',
                reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ACCOUNT_MOVED_VENDOR_LAST_CONTACTED_GTE_30_DAYS']
            )
        )
    for account_payment_id in account_payment_or_payment_last_payment_gte_60_ids:
        all_allocated_vendor.append(
            dict(
                account_payment_id=account_payment_id, type='inhouse_to_vendor',
                reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ACCOUNT_MOVED_VENDOR_LAST_PAYMENT_GTE_60_DAYS']
            )
        )

    if not account_payment_or_payment_passing_threshold_ids:
        return all_allocated_vendor

    for account_payment_id in account_payment_or_payment_passing_threshold_ids:
        all_allocated_vendor.append(
            dict(
                account_payment_id=account_payment_id,
                type='agent_to_vendor',
                reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ACCOUNT_MOVED_VENDOR_EXCEEDS_THRESHOLD'].format(agent_threshold)
            )
        )

    return all_allocated_vendor


def create_record_movement_history(data):
    if type(data) is list:
        CollectionAssignmentHistory.objects.bulk_create(
            data
        )
        return

    CollectionAssignmentHistory.objects.create(
        **data
    )


def display_account_movement_history(account_payment_or_payment, is_julo_one=False):
    if is_julo_one:
        account = account_payment_or_payment.account
        to_display_account_payments_ids = account.accountpayment_set.filter(
            due_date__lte=account_payment_or_payment.due_date
        ).order_by('due_date').values_list('id', flat=True)
        filter_collection_assignment_history = dict(
            account_payment_id__in=to_display_account_payments_ids
        )
    else:
        filter_collection_assignment_history = dict(
            payment=account_payment_or_payment
        )

    collection_assignment_history = CollectionAssignmentHistory.objects.filter(
        **filter_collection_assignment_history
    ).extra(select={'type_data': "'Account Assignment Change'"}).order_by('-cdate')
    return collection_assignment_history


def determine_input_is_account_id_or_loan_id(str_id):
    if len(str_id) == 10 and str_id[:4] == '3000':
        return "payment__loan_id"
    return "account_payment__account_id"


def format_agent_assignment_list_for_removal_agent_menu(agent_assignment_list):
    formated_data = []
    for agent_assignment in agent_assignment_list:
        agent = agent_assignment.agent
        agent_fullname = agent.first_name + " " + agent.last_name
        if not agent_fullname.strip():
            agent_fullname = agent.username

        data = dict(
            id=agent_assignment.id,
            agent_name=agent_fullname
        )
        if agent_assignment.payment:
            loan = agent_assignment.payment.loan
            application = loan.application
            status = loan.status
            loan_or_account_id = loan.id
            dpd = agent_assignment.payment.due_late_days
        else:
            account = agent_assignment.account_payment.account
            application = account.last_application
            status = agent_assignment.account_payment.status_id
            loan_or_account_id = account.id
            dpd = agent_assignment.account_payment.dpd

        customer = application.customer
        product_line = application.product_line.product_line_type
        data.update(
            loan_or_account_id=loan_or_account_id,
            status=status,
            product_line=product_line,
            full_name=customer.fullname,
            dpd=dpd
        )
        formated_data.append(data)
    return formated_data


def move_agent_assignment_to_new_agent(old_agent_assignments, new_agent_user_obj, assign_time):
    new_agent_assignments = []
    for old_agent_assignment in old_agent_assignments:
        data = dict(
            assign_time=assign_time,
            agent=new_agent_user_obj,
            sub_bucket_assign_time=old_agent_assignment.sub_bucket_assign_time,
        )
        ptp_filter = dict(
            agent_assigned=old_agent_assignment.agent
        )
        if old_agent_assignment.account_payment:
            data.update(
                dpd_assign_time=old_agent_assignment.account_payment.dpd,
                account_payment=old_agent_assignment.account_payment
            )
            ptp_filter.update(
                account_payment=old_agent_assignment.account_payment
            )
        else:
            data.update(
                dpd_assign_time=old_agent_assignment.payment.due_late_days,
                payment=old_agent_assignment.payment
            )
            ptp_filter.update(
                payment=old_agent_assignment.payment
            )
        PTP.objects.filter(**ptp_filter).update(
            agent_assigned=new_agent_user_obj
        )

        new_agent_assignments.append(
            AgentAssignment(**data)
        )
    created_new_agent_assignment = AgentAssignment.objects.bulk_create(
        new_agent_assignments
    )
    if created_new_agent_assignment:
        return True
    return False


def remove_active_ptp_after_agent_removal(old_agent_assignments):
    will_deleted_ptp_ids = []
    for old_assignment in old_agent_assignments:
        ptp_filter = dict(
            agent_assigned=old_assignment.agent
        )
        if old_assignment.account_payment:
            ptp_filter.update(
                account_payment=old_assignment.account_payment
            )
        else:
            ptp_filter.update(
                account_payment=old_assignment.account_payment,
                payment=old_assignment.payment
            )
        will_deleted_ptp_ids += PTP.objects.filter(**ptp_filter).values_list(
            'id', flat=True)
    # delete PTP data
    PTP.objects.filter(id__in=will_deleted_ptp_ids).delete()


def generate_filter_for_recording_detail(request_data):
    from datetime import datetime as filter_datetime
    filter_data = dict()
    search_call_date_mode = request_data.get('search_call_date_mode')
    search_duration_mode = request_data.get('search_duration_mode')
    search_negative_score_mode = request_data.get('search_negative_score_mode')
    search_sop_score_mode = request_data.get('search_sop_score_mode')
    search_value_call_start = request_data.get('global_search_value_call_start')
    search_value_call_end = request_data.get('global_search_value_call_end')
    search_value_duration = request_data.get('global_search_value_duration')
    search_value_account_id = request_data.get('global_search_value_account_id')
    search_value_account_payment_id = request_data.get(
        'global_search_value_account_payment_id')
    search_value_call_to = request_data.get('global_search_value_call_to')
    search_value_negative_score = request_data.get('global_search_value_negative_score')
    search_value_sop_score = request_data.get('global_search_value_sop_score')
    search_value_id = request_data.get('global_search_value_id')
    search_value_agent = request_data.get('global_search_value_agent')
    search_value_bucket = request_data.get('global_search_value_bucket')
    search_value_source = request_data.get('global_search_value_source')
    search_exact_ids = []
    if search_value_id:
        search_exact_ids = search_value_id.split(',')
        filter_data['id__in'] = search_exact_ids

    if search_call_date_mode:
        if search_call_date_mode == 'today':
            today = timezone.localtime(timezone.now())
            filter_data.update(
                call_start__date=today.date()
            )
        else:
            search_call_date_start = filter_datetime.strptime(
                request_data.get('search_call_date_1'), '%Y-%m-%d %H:%M:%S')
            if search_call_date_mode == 'between':
                search_call_date_end = filter_datetime.strptime(
                    request_data.get('search_call_date_2'), '%Y-%m-%d %H:%M:%S')
                filter_data.update(
                    call_start__range=(
                        search_call_date_start,
                        search_call_date_end
                    )
                )
            elif search_call_date_mode == 'after':
                filter_data.update(
                    call_start__gte=search_call_date_start
                )
            elif search_call_date_mode == 'before':
                filter_data.update(
                    call_start__lte=search_call_date_start
                )

    if search_duration_mode:
        search_duration_start = int(request_data.get('search_duration_filter_1'))
        if search_duration_mode == 'between':
            search_duration_end = int(request_data.get('search_duration_filter_2'))
            filter_data.update(
                duration__range=(search_duration_start, search_duration_end)
            )
        elif search_duration_mode == 'greater':
            filter_data.update(
                duration__gte=search_duration_start
            )
        elif search_duration_mode == 'less':
            filter_data.update(
                duration__lte=search_duration_start
            )

    airudder_filter = dict()

    if search_negative_score_mode:
        search_negative_score_start = int(request_data.get('search_negative_score_filter_1'))
        if search_negative_score_mode == 'between':
            search_negative_score_end = int(request_data.get('search_negative_score_filter_2'))
            airudder_filter.update(
                r_channel_negative_score_amount__range=(
                    search_negative_score_start, search_negative_score_end)
            )
        elif search_negative_score_mode == 'greater':
            airudder_filter.update(
                r_channel_negative_score_amount__gte=search_negative_score_start
            )
        elif search_negative_score_mode == 'less':
            airudder_filter.update(
                r_channel_negative_score_amount__lte=search_negative_score_start
            )

    if search_sop_score_mode:
        search_sop_score_start = int(request_data.get('search_sop_score_filter_1'))
        if search_sop_score_mode == 'between':
            search_sop_score_end = int(request_data.get('search_sop_score_filter_2'))
            airudder_filter.update(
                r_channel_sop_score_amount__range=(
                    search_sop_score_start, search_sop_score_end)
            )
        elif search_sop_score_mode == 'greater':
            airudder_filter.update(
                r_channel_sop_score_amount__gte=search_sop_score_start
            )
        elif search_sop_score_mode == 'less':
            airudder_filter.update(
                r_channel_sop_score_amount__lte=search_sop_score_start
            )

    if airudder_filter:
        if search_exact_ids:
            airudder_filter.update(
                airudder_recording_upload__vendor_recording_detail_id__in=search_exact_ids
            )
        vendor_recording_detail_ids = (
            RecordingReport.objects.filter(**airudder_filter)
            .values_list('airudder_recording_upload__vendor_recording_detail_id', flat=True)
        )
        if not vendor_recording_detail_ids:
            # for make data is null if not found
            filter_data.update(id=0)
        else:
            filter_data.update(
                id__in=list(vendor_recording_detail_ids)
            )

    if search_value_call_start:
        search_value_call_start_lists = []
        for item in search_value_call_start.split(','):
            search_value_call_start_lists.append(
                filter_datetime.strptime(item, '%Y-%m-%d %H:%M:%S')
            )
        filter_data['call_start__in'] = search_value_call_start_lists

    if search_value_call_end:
        search_value_call_end_lists = []
        for item in search_value_call_end.split(','):
            search_value_call_end_lists.append(
                filter_datetime.strptime(item, '%Y-%m-%d %H:%M:%S')
            )
        filter_data['call_end__in'] = search_value_call_end_lists

    if search_value_duration:
        filter_data['duration__in'] = search_value_duration.split(',')

    if search_value_account_id:
        filter_data['account_payment__account_id__in'] = search_value_account_id.split(',')

    if search_value_account_payment_id:
        filter_data['account_payment_id__in'] = search_value_account_payment_id.split(',')

    if search_value_source:
        filter_data['skiptrace__contact_source'] = search_value_source

    if search_value_agent:
        filter_data['agent__username'] = search_value_agent

    if search_value_bucket:
        filter_data['bucket'] = search_value_bucket

    if search_value_call_to:
        filter_data['call_to__in'] = search_value_call_to.split(',')

    airudder_specific_filter = dict()
    if search_value_negative_score:
        airudder_specific_filter = dict(
            r_channel_negative_score_amount__in=search_value_negative_score.split(',')
        )

    if search_value_sop_score:
        airudder_specific_filter = dict(
            r_channel_sop_score_amount__in=search_value_sop_score.split(',')
        )

    if airudder_specific_filter:
        if search_exact_ids:
            airudder_specific_filter.update(
                airudder_recording_upload__vendor_recording_detail_id__in=search_exact_ids
            )

        vendor_recording_detail_ids = RecordingReport.objects.filter(
            **airudder_specific_filter).values_list(
                'airudder_recording_upload__vendor_recording_detail_id', flat=True)
        if not vendor_recording_detail_ids:
            # for make data is null if not found
            filter_data.update(id=0)
        else:
            filter_data.update(
                id__in=list(vendor_recording_detail_ids)
            )

    return filter_data


def assign_new_vendor(
    payment_or_account_payment,
    new_vendor, is_julo_one,
    reason
):
    today = timezone.localtime(timezone.now())
    if is_julo_one:
        collection_vendor_assignment_data = dict(
            account_payment=payment_or_account_payment,
            dpd_assign_time=payment_or_account_payment.due_late_days,
        )
        old_assignment = CollectionVendorAssignment.objects.filter(
            is_active_assignment=False, account_payment=payment_or_account_payment
        ).last()
        old_assignment_history = CollectionAssignmentHistory.objects.filter(
            account_payment=payment_or_account_payment
        ).last()
        collection_vendor_transfer_data = dict(
            account_payment=payment_or_account_payment
        )
    else:
        collection_vendor_assignment_data = dict(
            payment=payment_or_account_payment,
            dpd_assign_time=payment_or_account_payment.due_late_days,
        )
        old_assignment = CollectionVendorAssignment.objects.filter(
            is_active_assignment=False, payment=payment_or_account_payment
        ).last()
        old_assignment_history = CollectionAssignmentHistory.objects.filter(
            payment=payment_or_account_payment
        ).last()
        collection_vendor_transfer_data = dict(
            payment=payment_or_account_payment
        )
    # assign new vendor
    sub_bucket_today = get_current_sub_bucket(
        payment_or_account_payment, is_julo_one=is_julo_one)
    if not sub_bucket_today:
        message = "failed because dont have sub bucket {}".format(payment_or_account_payment.id)
        return False, message
    vendor_types = None
    if sub_bucket_today.id == 1:
        vendor_types = CollectionVendorCodes.VENDOR_TYPES.get('special')
    elif sub_bucket_today.id in (2, 3):
        vendor_types = CollectionVendorCodes.VENDOR_TYPES.get('general')
    elif sub_bucket_today.id == 4:
        vendor_types = CollectionVendorCodes.VENDOR_TYPES.get('final')
    vendor_configuration = CollectionVendorRatio.objects.filter(
        vendor_types=vendor_types,
        collection_vendor=new_vendor
    ).last()
    if not vendor_configuration:
        message = "Failed assignment because dont have vendor \
        configuration payment {} vendor_types : {}".format(
            payment_or_account_payment.id, vendor_types
        )
        return False, message
    collection_vendor_assignment_data.update(
        vendor=new_vendor,
        vendor_configuration=vendor_configuration,
        sub_bucket_assign_time=sub_bucket_today,
        assign_time=today,
        is_transferred_from_other=True
    )
    format_and_create_single_movement_history(
        payment_or_account_payment, new_vendor,
        reason=reason,
        is_julo_one=is_julo_one,
        is_only_formated=False,
        old_assignment=old_assignment_history
    )
    transfer_from_id = None
    transfer_from = None
    transfer_type = CollectionVendorAssigmentTransferType.inhouse_to_vendor()
    if old_assignment:
        if old_assignment.vendor:
            transfer_from = old_assignment.vendor
            transfer_from_id = old_assignment.vendor.id
            transfer_type = CollectionVendorAssigmentTransferType.vendor_to_vendor()

    collection_vendor_transfer_data.update(
        transfer_from=transfer_from,
        transfer_from_id=transfer_from_id,
        transfer_to_id=new_vendor.id,
        transfer_reason=reason,
        transfer_type=transfer_type,
    )
    CollectionVendorAssignmentTransfer.objects.create(**collection_vendor_transfer_data)
    # assign
    new_assignment = CollectionVendorAssignment.objects.create(**collection_vendor_assignment_data)
    if new_assignment:
        message = "Success new assignment payment {}".format(payment_or_account_payment.id)
        return True, message
    else:
        message = "Error assignment payment {}".format(payment_or_account_payment.id)
        return False, message


def get_assigned_b4_account_payment_ids_to_vendors():
    assigned_to_vendor_account_payment_ids = list(CollectionVendorAssignment.objects.filter(
        is_active_assignment=True, account_payment__isnull=False,
        sub_bucket_assign_time=SubBucket.sub_bucket_four()
    ).values_list('account_payment', flat=True))
    return assigned_to_vendor_account_payment_ids


def set_expired_from_vendor_b4_account_payment_reach_b5():
    logger.info({
        "action": "set_expired_from_vendor_b4_account_payment_reach_b5",
    })

    today = timezone.localtime(timezone.now())
    b5_reach_date = today - timedelta(days=BucketConst.BUCKET_5_DPD)
    vendor_assignment_reach_b5 = CollectionVendorAssignment.objects.select_related(
        'account_payment').filter(
        account_payment__isnull=False,
        is_active_assignment=True,
        sub_bucket_assign_time=SubBucket.sub_bucket_four(),
        account_payment__due_date__lte=b5_reach_date
    )
    if not vendor_assignment_reach_b5:
        logger.warn({
            "action": "set_expired_from_vendor_b4_account_payment_reach_b5",
            "info": "no data to expired"
        })

    history_movement = []
    account_payment_ids = []
    for collection_vendor in vendor_assignment_reach_b5:
        history_movement.append(
            format_and_create_single_movement_history(
                collection_vendor.account_payment, None,
                reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ASSIGNMENT_EXPIRED_VENDOR_END'],
                is_julo_one=True, is_only_formated=True
            )
        )
        account_payment_ids.append(collection_vendor.account_payment.id)
        collection_vendor.update_safely(
            unassign_time=today, is_active_assignment=False
        )
    logger.info({
        "action": "set_expired_from_vendor_b4_account_payment_reach_b5",
        "account_payment_ids": account_payment_ids
    })
    create_record_movement_history(history_movement)


def check_expiration_b4_vendor_assignment_for_j1(vendor_ratio):
    logger.info({
        "action": "check_expiration_b4_vendor_assignment_for_j1",
        "info": "function begin"
    })
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.B4_EXPIRED_THRESHOLD,
        is_active=True
    ).last()
    # default value for expiration days
    expiration_day = 19
    if feature_setting:
        expiration_day = int(feature_setting.parameters['expired_in_days'])

    today = timezone.localtime(timezone.now())
    expire_assignment = (today - timedelta(days=expiration_day)).date()
    sub_bucket = SubBucket.sub_bucket_four()
    collection_vendor_assignments = CollectionVendorAssignment.objects.select_related(
        'account_payment').filter(
        vendor_configuration=vendor_ratio,
        assign_time__lt=expire_assignment,
        is_active_assignment=True,
        account_payment__isnull=False,
        assign_time__isnull=False,
        sub_bucket_assign_time=sub_bucket
    ).distinct('account_payment_id')

    if not collection_vendor_assignments:
        logger.warn({
            "action": "check_expiration_b4_vendor_assignment_for_j1",
            "info": "no data to expired"
        })
        return

    vendor_ratios = determine_first_vendor_should_assign(vendor_ratio, is_block_old_vendor=False)
    vendor_ratios = [sub['vendor_configuration'] for sub in vendor_ratios] or []
    key_vendor = 0
    reassign_payments_data = []
    history_movement = []
    account_payment_ids = []
    for collection_vendor_assignment in collection_vendor_assignments:
        account_payment = collection_vendor_assignment.account_payment
        active_collection_vendor_assigments = CollectionVendorAssignment.objects.filter(
            vendor_configuration=vendor_ratio,
            assign_time__lt=expire_assignment,
            is_active_assignment=True,
            account_payment=account_payment
        )
        account_payment = collection_vendor_assignment.account_payment
        collection_vendor_ratio = vendor_ratio
        # assign to old vendor again if theres no other active vendor
        if vendor_ratios:
            ever_enter_vendor_configuration_ids = list(CollectionVendorAssignment.objects.filter(
                account_payment=account_payment,
                vendor_configuration__vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('b4'),
                vendor__is_b4=True
            ).values_list('vendor_configuration', flat=True))
            next_vendor_config = vendor_ratios
            if ever_enter_vendor_configuration_ids:
                ever_enter_vendor_configuration_ids = set(ever_enter_vendor_configuration_ids)
                determined_next_vendor_ratio = set(vendor_ratios)
                never_enter_vendor_ratios = list(
                    sorted(determined_next_vendor_ratio - ever_enter_vendor_configuration_ids))
                if never_enter_vendor_ratios:
                    next_vendor_config = never_enter_vendor_ratios
            index = key_vendor if key_vendor != (len(vendor_ratios) - 1) else 0
            if index > (len(next_vendor_config) - 1):
                index = len(next_vendor_config) - 1

            collection_vendor_ratio = CollectionVendorRatio.objects.get_or_none(
                pk=next_vendor_config[index])

        transfer_account = CollectionVendorAssignmentTransfer.objects.create(
            account_payment=account_payment,
            transfer_from=collection_vendor_assignment.vendor,
            transfer_from_id=collection_vendor_assignment.vendor.id,
            transfer_to_id=collection_vendor_ratio.collection_vendor.id,
            transfer_type=CollectionVendorAssigmentTransferType.vendor_to_vendor(),
        )

        # create history for transfer from other vendor to other vendor
        history_movement.append(
            format_and_create_single_movement_history(
                collection_vendor_assignment.account_payment,
                collection_vendor_ratio.collection_vendor,
                reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ASSIGNMENT_EXPIRED_VENDOR_END'],
                is_julo_one=True, is_only_formated=True)
        )
        active_collection_vendor_assigments.update(
            is_active_assignment=False,
            unassign_time=timezone.localtime(timezone.now()),
            is_transferred_to_other=True,
            collection_vendor_assigment_transfer=transfer_account
        )

        reassign_payments_data.append(CollectionVendorAssignment(
            vendor=collection_vendor_ratio.collection_vendor,
            vendor_configuration=collection_vendor_ratio,
            account_payment=account_payment,
            sub_bucket_assign_time=sub_bucket,
            dpd_assign_time=account_payment.dpd,
            is_transferred_from_other=True)
        )

        key_vendor = key_vendor + 1 if key_vendor != (len(vendor_ratios) - 1) else 0
        account_payment_ids.append(account_payment)

    logger.info({
        "action": "check_expiration_b4_vendor_assignment_for_j1",
        "account_payment_ids": account_payment_ids
    })
    create_record_movement_history(history_movement)
    CollectionVendorAssignment.objects.bulk_create(reassign_payments_data)


def manual_transfer_assignment(data, user, context):
    transfer_from_id = data['transfer_from_id']
    transfer_to_id = data['vendor_name']
    transfer_reason = data['transfer_reason']
    save_type = data['save_type']
    is_julo_one = data['is_julo_one']
    payment_id = data['payment_id']
    account_payment_id = data['account_payment_id']
    collection_vendor_transfer_data = dict()
    if is_julo_one:
        payment_or_account_payment = AccountPayment.objects.get_or_none(
            pk=account_payment_id)
        collection_vendor_transfer_data.update(
            account_payment=payment_or_account_payment
        )
    else:
        payment_or_account_payment = Payment.objects.get_or_none(pk=payment_id)
        collection_vendor_transfer_data.update(
            payment=payment_or_account_payment
        )

    transfer_from_label = data['transfer_from_labels']
    transfer_to_label = 'vendor'
    unassign_from = None
    transfer_from = None
    if transfer_from_label == 'agent':
        unassign_from = AgentAssignment.objects.filter(pk=transfer_from_id).last()
        if unassign_from:
            transfer_from = unassign_from.agent
    elif transfer_from_label == 'vendor':
        unassign_from = CollectionVendorAssignment.objects.filter(
            pk=transfer_from_id).last()
        if unassign_from:
            transfer_from = unassign_from.vendor
    today_time = timezone.localtime(timezone.now())
    try:
        with transaction.atomic():
            transfer_to = None
            if transfer_to_id != 'inhouse':
                transfer_to = CollectionVendor.objects.normal().filter(
                    id=transfer_to_id).last()
            else:
                transfer_to_label = 'inhouse'

            collection_vendor_transfer_data.update(
                transfer_from=transfer_from, transfer_to=transfer_to,
                transfer_reason=transfer_reason,
                transfer_type=eval(
                    'CollectionVendorAssigmentTransferType.{}_to_{}'.format(
                        transfer_from_label, transfer_to_label))(),
                transfer_inputted_by=user
            )
            collection_vendor_transfer = CollectionVendorAssignmentTransfer.objects.create(
                **collection_vendor_transfer_data
            )
            reason = CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                'ACCOUNT_MANUALLY_TRANSFERRED_VENDOR']
            if transfer_to_label == 'inhouse':
                reason = CollectionAssignmentConstant.ASSIGNMENT_REASONS[
                    'ACCOUNT_MANUALLY_TRANSFERRED_INHOUSE']

            format_and_create_single_movement_history(
                payment_or_account_payment, transfer_to,
                reason=reason,
                is_julo_one=is_julo_one, old_assignment=transfer_from
            )
            if transfer_to:
                sub_bucket_today = get_current_sub_bucket(
                    payment_or_account_payment, is_julo_one=is_julo_one)
                vendor_types = None
                if sub_bucket_today.id == 1:
                    vendor_types = CollectionVendorCodes.VENDOR_TYPES.get('special')
                elif sub_bucket_today.id in (2, 3):
                    vendor_types = CollectionVendorCodes.VENDOR_TYPES.get('general')
                elif sub_bucket_today.id == 4:
                    vendor_types = CollectionVendorCodes.VENDOR_TYPES.get('final')

                vendor_configuration = None
                if vendor_types:
                    vendor_configuration = CollectionVendorRatio.objects.filter(
                        vendor_types=vendor_types,
                        collection_vendor=transfer_to
                    ).last()

                # create transfer to
                collection_vendor_assignment_data = dict(
                    vendor=transfer_to,
                    sub_bucket_assign_time=sub_bucket_today,
                    is_transferred_from_other=True, assign_time=today_time,
                    vendor_configuration=vendor_configuration
                )
                if is_julo_one:
                    collection_vendor_assignment_data.update(
                        account_payment=payment_or_account_payment,
                        dpd_assign_time=payment_or_account_payment.dpd
                    )
                else:
                    collection_vendor_assignment_data.update(
                        payment=payment_or_account_payment,
                        dpd_assign_time=payment_or_account_payment.due_late_days
                    )
                CollectionVendorAssignment.objects.create(
                    **collection_vendor_assignment_data
                )
            # update transfer from
            if unassign_from:
                unassign_from.update_safely(
                    collection_vendor_assigment_transfer=collection_vendor_transfer,
                    unassign_time=today_time,
                    is_active_assignment=False, is_transferred_to_other=True
                )
            context['success'] = True
            context['save_type'] = save_type
    except Exception as e:
        context['success'] = False
        context['error_message'] = str(e)
    return context


def b3_vendor_distribution(account_payments, block_intelix_params, bucket_name):
    if not account_payments:
        return []

    today = timezone.localtime(timezone.now()).date()
    ever_in_rpc_account_payment_ids = account_payments.exclude(
        skiptracehistory__call_result__name__startswith='RPC'
    ).exclude(
        ptp__ptp_date__gte=today
    ).values_list('pk', flat=True)
    negative_pgood_account_payment_ids = account_payments.filter(
        account__accountproperty__pgood__lt=block_intelix_params.get('pgood')
    ).exclude(
        ptp__ptp_date__gte=today
    ).values_list('pk', flat=True)

    unsent_b3_reason = 'sending b3 to vendor'
    unsent_b3_vendor_account_payment_ids = account_payments.filter(
        notsenttodialer__bucket=bucket_name,
        notsenttodialer__unsent_reason=unsent_b3_reason
    ).distinct().values_list('pk', flat=True)

    sending_b3_to_vendor = set(
        list(ever_in_rpc_account_payment_ids) + list(negative_pgood_account_payment_ids) +
        list(unsent_b3_vendor_account_payment_ids))
    return sending_b3_to_vendor


def get_assigned_b4_account_payment_ids_to_vendors_improved(
        list_grouped_by_bucket_account_payment_ids):
    if len(list_grouped_by_bucket_account_payment_ids) == 0:
        return AccountPayment.objects.none()

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.B4_EXPIRED_THRESHOLD,
        is_active=True
    ).last()
    # default value for expiration days
    expiration_day = 19
    if feature_setting:
        expiration_day = int(feature_setting.parameters['expired_in_days'])
    today = timezone.localtime(timezone.now()).date()
    expire_assignment = today - timedelta(days=expiration_day)
    assigned_to_vendor_account_payment_ids = list(CollectionVendorAssignment.objects.filter(
        assign_time__date__gte=expire_assignment,
        is_active_assignment=True,
        account_payment__isnull=False,
        sub_bucket_assign_time=SubBucket.sub_bucket_four(),
        account_payment_id__in=list_grouped_by_bucket_account_payment_ids
    ).values_list('account_payment', flat=True))

    return assigned_to_vendor_account_payment_ids


def process_assign_b4_account_payments_to_vendor(data_account_payments, collection_vendor_ratios):
    today_date = timezone.localtime(timezone.now()).date()
    history_movement_record_data = []
    total_data = len(data_account_payments)
    should_assign_vendor_attributes = []
    account_payment_ids = []
    with transaction.atomic():
        for collection_vendor_ratio in collection_vendor_ratios:
            if not collection_vendor_ratio.collection_vendor.is_active:
                continue
            vendor_distribution_count = \
                collection_vendor_ratio.account_distribution_ratio * total_data
            if isinstance(vendor_distribution_count, float):
                vendor_distribution_count = int(math.ceil(vendor_distribution_count))
            should_assign_vendor_attributes.append(
                dict(
                    vendor=collection_vendor_ratio.collection_vendor,
                    should_assign_count=vendor_distribution_count,
                    collection_vendor_ratio=collection_vendor_ratio, assigned_count=0
                ))

        assigned_account_payment_to_vendor = []
        need_process_vendor = list(range(0, len(collection_vendor_ratios)))
        processed_vendor = []
        finished_assign_vendor_status = []
        for i in range(0, len(data_account_payments)):
            # prevent process existing data when should_assign_count == assigned_count each vendor
            if any(finished_assign_vendor_status) \
                    and len(finished_assign_vendor_status) == len(should_assign_vendor_attributes):
                break
            assignment_vendor_index = 0
            # determine next vendor eligible
            if processed_vendor:
                diff_list = list(set(need_process_vendor) - set(processed_vendor))
                if diff_list:
                    assignment_vendor_index = diff_list.pop(0)

            selected_vendor_attribute = should_assign_vendor_attributes[assignment_vendor_index]
            vendor = selected_vendor_attribute.get('vendor')
            collection_vendor_ratio = selected_vendor_attribute.get('collection_vendor_ratio')
            data_account_payment = data_account_payments.pop(0)
            account_payment_id = data_account_payment['account_payment_id']
            account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)

            if not account_payment:
                continue
            sub_bucket = get_current_sub_bucket(
                account_payment, is_julo_one=True, is_bucket_4=True)
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
                    unassign_time__date=today_date
                ).last()
                if old_vendor_assignment:
                    old_assignment = old_vendor_assignment.vendor
            # prevent double assignment
            if CollectionVendorAssignment.objects.filter(
                    account_payment__account=account_payment.account,
                    is_active_assignment=True).exists():
                continue

            assigned_account_payment_to_vendor.append(
                CollectionVendorAssignment(
                    vendor=vendor,
                    vendor_configuration=collection_vendor_ratio,
                    account_payment=account_payment,
                    sub_bucket_assign_time=sub_bucket,
                    dpd_assign_time=account_payment.dpd,
                    is_transferred_from_other=is_transferred_from_other,
                )
            )
            history_movement_record_data.append(
                CollectionAssignmentHistory(
                    account_payment=account_payment,
                    old_assignment=old_assignment,
                    new_assignment=collection_vendor_ratio.collection_vendor,
                    assignment_reason=data_account_payment['reason'],
                )
            )
            account_payment_ids.append(account_payment)
            # update assigned count on should_assign_vendor_attributes
            new_assigned_count = selected_vendor_attribute['assigned_count'] + 1
            selected_vendor_attribute['assigned_count'] = new_assigned_count
            processed_vendor.append(assignment_vendor_index)
            if selected_vendor_attribute['should_assign_count'] == new_assigned_count:
                finished_assign_vendor_status.append(True)

            if len(processed_vendor) == len(need_process_vendor):
                processed_vendor = []

            if new_assigned_count >= selected_vendor_attribute['should_assign_count']:
                if 0 <= assignment_vendor_index < len(need_process_vendor):
                    need_process_vendor.remove(assignment_vendor_index)

        logger.info({
            "action": "process_assign_b4_account_payments_to_vendor",
            "account_payment_ids": account_payment_ids
        })
        CollectionVendorAssignment.objects.bulk_create(assigned_account_payment_to_vendor)


def process_distribution_b3_to_vendor(
        max_ratio_threshold_for_due_amount_differences: float,
        split_threshold: int, db_name: str = DEFAULT_DB) -> tuple:
    b3_populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
        IntelixTeam.JULO_B3, is_only_account_payment_id=True, db_name=db_name)
    nc_populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
        IntelixTeam.JULO_B3_NC, is_only_account_payment_id=True, db_name=db_name)

    populated_dialer_call_account_payment_ids = b3_populated_dialer_call_account_payment_ids + \
        nc_populated_dialer_call_account_payment_ids

    # all populated data will handle by new logic
    account_payment_ids_goes_to_inhouse, account_payment_ids_goes_to_vendor, \
        total_over_due_amount = split_b3_distribution(
            populated_dialer_call_account_payment_ids,
            split_threshold,
            max_ratio_threshold_for_due_amount_differences,
            db_name=db_name,
        )
    # why this only check vendor only
    # because send data to our new table will be store on upload_julo_xxx_to_inteoix
    if account_payment_ids_goes_to_vendor:
        record_collection_inhouse_vendor(
            account_payment_ids_goes_to_vendor,
            is_vendor=True,
            db_name=db_name,
        )

    data_for_log = dict(
        total_over_due_amount=total_over_due_amount,
        distribution_count=dict(
            inhouse=len(account_payment_ids_goes_to_inhouse),
            vendor=len(account_payment_ids_goes_to_vendor)
        )
    )

    return account_payment_ids_goes_to_vendor, data_for_log


def split_b3_distribution(
        populated_dialer_call_account_payment_ids,
        split_threshold, max_ratio_threshold_for_due_amount_differences, db_name=DEFAULT_DB):
    check_exist_tmp_data = CollectionBucketInhouseVendor.objects.using(db_name).all().exists()
    if not check_exist_tmp_data:
        all_b3_assigned_to_inhouse_ids = list(
            SentToDialer.objects.using(db_name).filter(
                cdate__date=(timezone.localtime(timezone.now()).date() - timedelta(days=1)),
                account_payment_id__in=populated_dialer_call_account_payment_ids,
                bucket__in=IntelixTeam.ALL_B3_BUCKET_LIST,
            ).distinct('account_payment_id').values_list('account_payment_id', flat=True)
        )
        all_b3_assigned_to_vendor_ids = list(NotSentToDialer.objects.using(db_name).filter(
            cdate__date=timezone.localtime(
                timezone.now()).date() - timedelta(days=1),
            account_payment_id__in=populated_dialer_call_account_payment_ids,
            unsent_reason=ast.literal_eval(
                ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR']),
            account_payment_id__isnull=False
        ).distinct(
            'account_payment_id').values_list('account_payment_id', flat=True))
    else:
        all_b3_assigned_to_inhouse_ids = list(
            CollectionBucketInhouseVendor.objects.using(db_name)
            .filter(bucket__in=IntelixTeam.ALL_B3_BUCKET_LIST, vendor=False)
            .values_list('account_payment', flat=True)
        )
        all_b3_assigned_to_vendor_ids = list(
            CollectionBucketInhouseVendor.objects.using(db_name)
            .filter(bucket__in=IntelixTeam.ALL_B3_BUCKET_LIST, vendor=True)
            .values_list('account_payment', flat=True)
        )
    # will filter fresh account payment only,
    # since on populated_dialer_call_account_payment_ids,
    # still have data already on sent_to_dialer table on yesterday
    all_existing_data = all_b3_assigned_to_inhouse_ids + all_b3_assigned_to_vendor_ids
    fresh_account_payment_b3_ids = list(AccountPayment.objects.using(db_name).filter(
        pk__in=populated_dialer_call_account_payment_ids
    ).exclude(pk__in=all_existing_data).values_list('id', flat=True))
    logger.info({
        "action": "split_b3_distribution",
        "inhouse_data": len(all_b3_assigned_to_inhouse_ids),
        "vendor_data": len(all_b3_assigned_to_vendor_ids),
        "fresh_data": len(fresh_account_payment_b3_ids),
        "time": str(timezone.localtime(timezone.now()))
    })
    if len(fresh_account_payment_b3_ids) == 0:
        raise NullFreshAccountException(
            "Data B3 still not available for distribution or dont have fresh account")

    # first check our data is very unbalanced
    if len(all_b3_assigned_to_vendor_ids) > len(all_b3_assigned_to_inhouse_ids) + \
            len(fresh_account_payment_b3_ids):
        # all data sent directly to inhouse
        logger.info({
            "action": "split_b3_distribution",
            "message": "all data sent to inhouse",
            "time": str(timezone.localtime(timezone.now()))
        })
        return fresh_account_payment_b3_ids, [], 0
    elif len(all_b3_assigned_to_inhouse_ids) > len(all_b3_assigned_to_vendor_ids) + \
            len(fresh_account_payment_b3_ids):
        # all data sent directly to vendor
        logger.info({
            "action": "split_b3_distribution",
            "message": "all data sent to vendor",
            "time": str(timezone.localtime(timezone.now()))
        })
        return [], fresh_account_payment_b3_ids, 0

    ordered_pgood_account_payment_ids = AccountPayment.objects.using(db_name).filter(
        pk__in=fresh_account_payment_b3_ids
    ).values_list('id', flat=True).order_by('-account__accountproperty__pgood')

    total_all_b3_data = len(all_b3_assigned_to_inhouse_ids) + len(all_b3_assigned_to_vendor_ids) \
        + len(fresh_account_payment_b3_ids)
    distribution_count = math.floor(total_all_b3_data * 0.5)
    total_fresh_data = len(fresh_account_payment_b3_ids)
    split_into = math.ceil(total_fresh_data / split_threshold)
    divided_account_payment_ids_per_batch = numpy.array_split(
        list(ordered_pgood_account_payment_ids), split_into)

    account_payment_ids_goes_to_inhouse = []
    account_payment_ids_goes_to_vendor = []
    never_goes_to_rpc_account_payment_ids = []
    # this looping is for prevent big data query to skiptrace history
    for account_payment_ids in divided_account_payment_ids_per_batch:
        account_payments = AccountPayment.objects.using(db_name).filter(pk__in=account_payment_ids)
        ever_in_rpc_account_payment_ids = list(account_payments.filter(
            skiptracehistory__call_result__name__in=(
                'RPC', 'RPC - Regular', 'RPC - PTP', 'RPC - HTP',
                'RPC - Broken Promise', 'RPC - Call Back',
            )
        ).distinct('pk').values_list('pk', flat=True))
        ever_in_rpc_account_payment_ids = list(account_payments.filter(
            pk__in=ever_in_rpc_account_payment_ids).order_by(
            '-account__accountproperty__pgood').values_list('pk', flat=True))
        never_in_rpc_account_payment_ids = account_payments.exclude(
            id__in=ever_in_rpc_account_payment_ids
        ).values_list('pk', flat=True).order_by('-account__accountproperty__pgood')
        # never goes to rpc will goes to vendor actually but we will separate this first
        # because theres posibility its goes to inhouse
        never_goes_to_rpc_account_payment_ids += list(never_in_rpc_account_payment_ids)
        # inhouse distribution
        current_inhouse_count = len(account_payment_ids_goes_to_inhouse)
        distribute_to_inhouse_count = 0
        if current_inhouse_count < abs(distribution_count - len(all_b3_assigned_to_inhouse_ids)):
            distribute_to_inhouse_count = \
                abs(current_inhouse_count - abs(
                    distribution_count - len(all_b3_assigned_to_inhouse_ids)))
            will_goes_to_inhouse = account_payments.filter(
                id__in=ever_in_rpc_account_payment_ids[:distribute_to_inhouse_count])
            account_payment_ids_goes_to_inhouse += list(
                will_goes_to_inhouse.order_by(
                    '-account__accountproperty__pgood').values_list('id', flat=True)
            )
        # vendor distribution
        # if we still have remains data on ever_in_rpc from inhouse distribution then we should
        # process the rest to vendor
        will_goes_to_vendor = account_payments.filter(
            id__in=ever_in_rpc_account_payment_ids[distribute_to_inhouse_count:]
        ).order_by('-account__accountproperty__pgood')
        if will_goes_to_vendor.exists():
            account_payment_ids_goes_to_vendor += list(
                will_goes_to_vendor.values_list('id', flat=True))

    # check if numbers goes to inhouse still not meet the threshold
    valid_to_inhouse_count = abs(distribution_count - len(all_b3_assigned_to_inhouse_ids))
    if len(account_payment_ids_goes_to_inhouse) < valid_to_inhouse_count:
        distribute_to_inhouse_count = abs(
            len(account_payment_ids_goes_to_inhouse) - valid_to_inhouse_count)
        if len(account_payment_ids_goes_to_vendor) >= distribute_to_inhouse_count:
            account_payment_ids_goes_to_inhouse += \
                account_payment_ids_goes_to_vendor[:distribute_to_inhouse_count]
            del account_payment_ids_goes_to_vendor[:distribute_to_inhouse_count]
        else:
            account_payment_ids_goes_to_inhouse += \
                never_goes_to_rpc_account_payment_ids[:distribute_to_inhouse_count]
            del never_goes_to_rpc_account_payment_ids[:distribute_to_inhouse_count]

    # assign rest of never goes to rpc into vendor
    account_payment_ids_goes_to_vendor += never_goes_to_rpc_account_payment_ids

    # for balancing B3 the due_amount will working on later
    # total_over_due_amount = dict(
    #     inhouse=AccountPayment.objects.filter(
    #         id__in=account_payment_ids_goes_to_inhouse + all_b3_assigned_to_inhouse_ids
    #         ).aggregate(total_due_amount=Sum('due_amount'))['total_due_amount'] or 0,
    #     vendor=AccountPayment.objects.filter(
    #         id__in=account_payment_ids_goes_to_vendor + all_b3_assigned_to_vendor_ids).aggregate(
    #         total_due_amount=Sum('due_amount'))['total_due_amount'] or 0
    # )
    # # balancing due_amount between inhouse and vendor and the max threshold 5%
    # balanced_distribution_count = math.floor(
    #     total_all_b3_data * max_ratio_threshold_for_due_amount_differences)
    # # check the data that need balanced and the way we get the data will different between inhouse
    # # and vendor because if need add the balanced data on vendor we need add at the
    # # beginning of list, but if the target is inhouse we need add the new one to the last index
    # if total_over_due_amount['inhouse'] > total_over_due_amount['vendor']:
    #     will_distributed_from = 'inhouse'
    #     will_distributed_to = 'vendor'
    #     # this code will order the list from back example data = [1, 2] it will change into [2, 1]
    #     will_distributed_account_payments_ids = \
    #         account_payment_ids_goes_to_inhouse[::-1][:balanced_distribution_count]
    # elif total_over_due_amount['inhouse'] < total_over_due_amount['vendor']:
    #     will_distributed_from = 'vendor'
    #     will_distributed_to = 'inhouse'
    #     will_distributed_account_payments_ids = \
    #         account_payment_ids_goes_to_vendor[:balanced_distribution_count]
    # else:
    #     return account_payment_ids_goes_to_inhouse, account_payment_ids_goes_to_vendor, \
    #         total_over_due_amount

    # will_distributed_account_payments = AccountPayment.objects.filter(
    #     id__in=will_distributed_account_payments_ids
    # ).order_by('-account__accountproperty__pgood').values('id', 'due_amount')
    # for account_payment in will_distributed_account_payments:
    #     account_payment_id = account_payment.get('id')
    #     due_amount = account_payment.get('due_amount')
    #     if (total_over_due_amount[will_distributed_from] - due_amount) \
    #             < (total_over_due_amount[will_distributed_to] + due_amount):
    #         break
    #     total_over_due_amount[will_distributed_from] -= due_amount
    #     total_over_due_amount[will_distributed_to] += due_amount
    #     eval('account_payment_ids_goes_to_{}'.format(will_distributed_from)).remove(
    #         account_payment_id)
    #     if will_distributed_to == 'vendor':
    #         account_payment_ids_goes_to_vendor.insert(0, account_payment_id)
    #     else:
    #         account_payment_ids_goes_to_inhouse.append(account_payment_id)

    return account_payment_ids_goes_to_inhouse, account_payment_ids_goes_to_vendor, 0


def record_collection_inhouse_vendor(account_payment_ids, is_vendor=True, db_name=DEFAULT_DB):
    bucket_to_inhouse_vendor_data = []
    # just to make sure not insert duplicate account payment
    all_data_already_on_inhouse_vendor = list(
        CollectionBucketInhouseVendor.objects.using(db_name)
        .all().values_list('account_payment', flat=True)
    )
    split_into = math.ceil(len(account_payment_ids) * 0.25)
    account_payments = CollectionDialerTemporaryData.objects.using(db_name).filter(
        account_payment__in=account_payment_ids
    ).exclude(
        account_payment__in=all_data_already_on_inhouse_vendor
    ).only('account_payment', 'team')
    account_payment_ids_per_batch = numpy.array_split(
        list(account_payments), split_into)

    for account_payments in account_payment_ids_per_batch:
        for account_payment in account_payments:
            bucket_to_inhouse_vendor_data.append(CollectionBucketInhouseVendor(
                account_payment=account_payment.account_payment,
                bucket=account_payment.team,
                vendor=is_vendor
            ))

    CollectionBucketInhouseVendor.objects.bulk_create(
        bucket_to_inhouse_vendor_data, batch_size=split_into)


@transaction.atomic()
def record_not_sent_to_intelix_with_reason(
    account_payment_ids: list, reason: str,
    dialer_task_id: int, db_name: str = DEFAULT_DB,
) -> bool:
    temp_account_payments = CollectionDialerTemporaryData.objects.using(db_name).filter(
        account_payment_id__in=account_payment_ids
    )
    not_sent_bulk_data = []
    for temp_account_payment in temp_account_payments.iterator():
        account_payment = temp_account_payment.account_payment
        is_paid_off = PaymentStatusCodes.PAID_ON_TIME <= account_payment.status_id <= \
            PaymentStatusCodes.PAID_LATE
        paid_off_timestamp = None
        if is_paid_off:
            account_payment_history = account_payment.accountpaymentstatushistory_set.filter(
                status_new__in=PaymentStatusCodes.paid_status_codes_without_sell_off()
            )
            paid_off_timestamp = account_payment_history.last().cdate
        not_sent_bulk_data.append(NotSentToDialer(
            account_payment=account_payment,
            account_id=account_payment.account_id,
            bucket=temp_account_payment.team,
            dpd=temp_account_payment.dpd,
            is_excluded_from_bucket=True if 'NON_CONTACTED' in temp_account_payment.team else False,
            is_paid_off=is_paid_off,
            paid_off_timestamp=paid_off_timestamp,
            unsent_reason=reason,
            is_j1=True,
            dialer_task_id=dialer_task_id
        ))
    return NotSentToDialer.objects.bulk_create(not_sent_bulk_data)


def process_distribution_b3_to_vendor_by_experiment1_method(
    account_id_tail_to_inhouse: list,
    split_threshold: int,
    db_name: str = DEFAULT_DB,
) -> tuple:
    b3_populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
        IntelixTeam.JULO_B3, is_only_account_payment_id=True, db_name=db_name)
    nc_populated_dialer_call_account_payment_ids = get_populated_data_for_calling(
        IntelixTeam.JULO_B3_NC, is_only_account_payment_id=True, db_name=db_name)

    populated_dialer_call_account_payment_ids = b3_populated_dialer_call_account_payment_ids + \
        nc_populated_dialer_call_account_payment_ids
    # check yesterday sent to inhouse as B3
    account_payment_ids_ever_in_inhouse = list(SentToDialer.objects.using(db_name).filter(
        cdate__date=(timezone.localtime(timezone.now()).date() - timedelta(days=1)),
        account_payment_id__in=populated_dialer_call_account_payment_ids,
        bucket__in=IntelixTeam.ALL_B3_BUCKET_LIST).values_list('account_payment_id', flat=True))
    populated_dialer_call_account_payment_ids = list(
        set(populated_dialer_call_account_payment_ids) - set(account_payment_ids_ever_in_inhouse))

    if len(populated_dialer_call_account_payment_ids) == 0:
        raise Exception("Data B3 still not available for distribution or dont have fresh account")
    base_account_payments = AccountPayment.objects.using(db_name).filter(
        pk__in=populated_dialer_call_account_payment_ids
    ).values_list('id', flat=True)

    total_data = len(base_account_payments)
    split_into = math.ceil(total_data / split_threshold)
    divided_account_payment_ids_per_batch = numpy.array_split(
        list(base_account_payments), split_into)

    account_payment_ids_goes_to_inhouse = []
    account_payment_ids_goes_to_vendor = []
    account_id_tail_for_inhouse = tuple(
        list(map(str, account_id_tail_to_inhouse)))

    for account_payment_ids in divided_account_payment_ids_per_batch:
        account_payments = AccountPayment.objects.using(db_name).filter(
            pk__in=account_payment_ids
        )
        # account_payment for inhouse
        account_payment_inhouse = account_payments.extra(
            where=["right(account_id::text, 1) in %s"],
            params=[account_id_tail_for_inhouse]
        ).values_list('pk', flat=True)
        account_payment_ids_goes_to_inhouse += list(account_payment_inhouse)
        # account_payment for vendor, getting from the rest of account_payment inhouse
        account_payment_vendor = account_payments.exclude(
            pk__in=account_payment_inhouse
        ).values_list('pk', flat=True)
        account_payment_ids_goes_to_vendor += list(account_payment_vendor)

    return account_payment_ids_goes_to_inhouse, account_payment_ids_goes_to_vendor
