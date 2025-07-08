import logging
from datetime import time, timedelta
from celery import task
from django.db import transaction
from django.utils import timezone

from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.account.models import AccountLimit, Account
from juloserver.cfs.constants import ActionPointsReason, CfsProgressStatus, CfsActionId, \
    MAP_AUTODEBET_STATUS_WITH_CFS_STATUS
from juloserver.cfs.services.core_services import (
    create_or_update_cfs_action_assignment
)
from juloserver.graduation.constants import GraduationType
from juloserver.graduation.services import check_entry_customer_affordability, \
    update_post_graduation, check_fdc_graduation
from juloserver.graduation.tasks import get_valid_approval_account_ids

from juloserver.julo.clients import (
    get_julo_pn_client,
    get_julo_sentry_client
)
from juloserver.cfs.models import (
    CfsActionAssignment, CfsActionPointsAssignment, TotalActionPoints, TotalActionPointsHistory
)
from juloserver.julo.models import Payment, Loan, Customer
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.utils import execute_after_transaction_safely

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='loan_normal')
def claim_cfs_action_assignment():
    from juloserver.cfs.services.core_services import claim_cfs_rewards
    today = timezone.localtime(timezone.now())
    to_time = today.combine(today, time.max)
    julo_pn_client = get_julo_pn_client()

    unclaimed_action_assignments = CfsActionAssignment.objects.filter(
        expiry_date__lte=to_time,
        progress_status=CfsProgressStatus.UNCLAIMED
    ).all()
    for action_assignment in unclaimed_action_assignments.iterator():
        try:
            is_success, cashback_earned = claim_cfs_rewards(
                action_assignment.id, action_assignment.customer
            )
            julo_pn_client.alert_claim_cfs_action_assignment(
                action_assignment.customer, cashback_earned
            )
        except Exception as e:
            logger.error({
                'message': "Log task claim cfs action assignment failed",
                'action_assignment_id': action_assignment.id,
                'error': e,
            })
            pass


@task(queue='loan_normal')
def check_cfs_action_expired():
    # Find all expired action-point-assignments
    # Updating the total action points of those customers
    # Bulk insert these into 'total_action_points_history'
    # Update is_expired=True to all those assigments

    today = timezone.localtime(timezone.now()).date()
    expired_assignments = CfsActionPointsAssignment.objects.all()\
        .filter(expiry_date__lt=today, is_processed=False)\
        .order_by('cdate')

    # make a dict of with key == customer_id; example:
    # {
    #   customer_id1 : [{'points_changed': 10, 'assignment: assignment}, {'points_changed': ...}]
    #   customer_id2 : [{'points_changed': 50, 'assignment: assignment}, {}]
    # }
    customer_expired_assignments = {}
    for expired in expired_assignments:
        d = {
            'points_changed': expired.points_changed,
            'assignment': expired
        }
        if expired.customer_id in customer_expired_assignments:
            customer_expired_assignments[expired.customer_id].append(d)
        else:
            customer_expired_assignments[expired.customer_id] = [d]

    # Now we start updating the actual total action points
    bulk_points_history_load = []
    change_reason = ActionPointsReason.ACTION_EXPIRED

    with transaction.atomic(), transaction.atomic(using='utilization_db'):
        action_points = TotalActionPoints.objects.select_for_update()\
            .filter(customer__id__in=customer_expired_assignments.keys())

        for action_point in action_points:
            old_point = action_point.point

            # process all expired assignment of a customer
            while customer_expired_assignments[action_point.customer.id]:
                expired_assignment = customer_expired_assignments[action_point.customer.id].pop(0)
                new_point = old_point - expired_assignment['points_changed']

                new_history = TotalActionPointsHistory(
                    customer_id=action_point.customer_id,
                    cfs_action_point_assignment_id=expired_assignment['assignment'].id,
                    partition_date=today,
                    old_point=old_point,
                    new_point=new_point,
                    change_reason=change_reason
                )
                bulk_points_history_load.append(new_history)
                old_point = new_point

            action_point.point = new_point
            action_point.save()

        TotalActionPointsHistory.objects.bulk_create(bulk_points_history_load)

        expired_assignments.update(is_processed=True)


@task(queue='loan_low')
def update_graduate_entry_level(account_id, graduation_rules):
    is_first_graduate = True
    account_ids = get_valid_approval_account_ids([account_id], is_first_graduate)
    if not account_ids:
        return False
    account_id = account_ids[0]

    is_valid = check_fdc_graduation(account_id)
    if not is_valid:
        logger.info({
            'action': 'juloserver.cfs.update_graduate_entry_level',
            'graduation_type': GraduationType.ENTRY_LEVEL,
            'account_id': account_id,
            'passed_fdc_check': is_valid,
        })
        return False

    account = Account.objects.filter(id=account_id).last()

    account_limit = account.accountlimit_set.last()
    count_loan_250 = 0
    sum_loan_amount = 0
    count_late_payment = 0
    count_grace_payment = 0
    sum_paid_amount = 0

    loans = Loan.objects.filter(
        account=account, loan_status__gte=LoanStatusCodes.CURRENT
    ).values_list('id', 'loan_status_id', 'loan_amount')
    loan_id_set = set()
    for loan_id, loan_status, loan_amount in loans:
        loan_id_set.add(loan_id)
        sum_loan_amount += loan_amount
        if loan_status == LoanStatusCodes.PAID_OFF:
            count_loan_250 += 1

    payments = Payment.objects.filter(loan_id__in=loan_id_set).values_list(
        'payment_status_id', 'paid_amount'
    )
    for payment_status, paid_amount in payments:
        if payment_status == PaymentStatusCodes.PAID_LATE:
            count_late_payment += 1
        if payment_status == PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD:
            count_grace_payment += 1
        sum_paid_amount += paid_amount

    with db_transactions_atomic(DbConnectionAlias.utilization()):
        account_limit = AccountLimit.objects.select_for_update().get(id=account_limit.id)
        account_property = account.accountproperty_set.last()
        if not account_property.is_entry_level:
            return False
        set_limit = account_limit.set_limit
        valid_rule = None
        for rule in graduation_rules:
            if rule['min_account_limit'] <= set_limit <= rule['max_account_limit']:
                valid_rule = rule
                break

        if not valid_rule:
            return False

        check_conditions = (
            count_grace_payment <= valid_rule['max_grace_payment'],
            count_late_payment <= valid_rule['max_late_payment'],
            sum_paid_amount >= set_limit * (valid_rule['min_percentage_paid_amount'] / 100),
            sum_loan_amount >= set_limit * (valid_rule['min_percentage_limit_usage'] / 100),
            count_loan_250 > 0,
        )
        if all(check_conditions):
            new_account_limit = valid_rule['new_account_limit']
            new_account_limit = check_entry_customer_affordability(new_account_limit, account_id)
            if account_limit.set_limit == new_account_limit:
                logger.info({
                    'action': 'juloserver.cfs.update_graduate_entry_level',
                    'graduation_type': GraduationType.ENTRY_LEVEL,
                    'account_id': account_id,
                    'same_limit_generated': account_limit.set_limit == new_account_limit
                })
                return False
            new_available_limit = new_account_limit - account_limit.used_limit

            update_post_graduation(
                GraduationType.ENTRY_LEVEL,
                account_property,
                account_limit,
                new_available_limit,
                new_account_limit
            )
            return True
        return False


def handle_cfs_mission(customer_id, new_bca_status):
    #  handle cfs mission
    valid_cfs_progress_status = MAP_AUTODEBET_STATUS_WITH_CFS_STATUS.get(new_bca_status)
    if not valid_cfs_progress_status:
        return

    execute_after_transaction_safely(
        lambda: create_or_update_cfs_action_assignment_bca_autodebet.apply_async(
            (customer_id, valid_cfs_progress_status)
        )
    )


@task(queue='loan_normal')
def create_or_update_cfs_action_assignment_bca_autodebet(customer_id, progress_status):
    customer = Customer.objects.get(pk=customer_id)
    completed_mission = CfsActionAssignment.objects.filter(
        customer=customer, action_id=CfsActionId.BCA_AUTODEBET,
        progress_status=CfsProgressStatus.CLAIMED
    ).last()
    if completed_mission:
        return

    application = customer.application_set.last()
    if not application or not application.eligible_for_cfs:
        return
    return create_or_update_cfs_action_assignment(
        application, CfsActionId.BCA_AUTODEBET, progress_status
    )


@task(queue='loan_normal')
def tracking_transaction_case_for_action_points(loan_id, activity_id):
    from juloserver.cfs.services.core_services import update_total_points_and_create_history
    loan = Loan.objects.get(pk=loan_id)
    data = {
        'customer': loan.customer,
        'assignment_info': {
            'loan_id': loan.id
        },
        'amount': loan.loan_amount
    }
    update_total_points_and_create_history(data, activity_id=activity_id)


@task(queue='loan_normal')
def tracking_repayment_case_for_action_points(payment_id, activity_id):
    from juloserver.cfs.services.core_services import update_total_points_and_create_history
    payment = Payment.objects.get(pk=payment_id)
    data = {
        'customer': payment.loan.customer,
        'assignment_info': {
            'payment_id': payment.id
        },
        'amount': payment.installment_principal
    }
    update_total_points_and_create_history(data, activity_id=activity_id)
