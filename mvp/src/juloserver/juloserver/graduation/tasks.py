import logging
from datetime import date, timedelta, datetime

from django.conf import settings
from django.db.models import F
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from celery.task import task
from django.db import connection, transaction

from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.account.constants import AccountConstant
from juloserver.account.models import (
    AccountLimit,
    AccountProperty, Account,
)
import juloserver.graduation.services as services
from juloserver.graduation.constants import (
    FeatureNameConst,
    GraduationType,
    GraduationFailureConst,
    GraduationFailureType,
    GraduationRedisConstant,
)
from juloserver.graduation.exceptions import (
    DowngradeMaxLimitException,
    DowngradeSetLimitException,
)
from juloserver.graduation.models import (
    CustomerGraduation,
    CustomerGraduationFailure,
    CustomerSuspendHistory,
    GraduationCustomerHistory2,
)
from juloserver.graduation.serializers import CustomerGraduationSerializer
from juloserver.graduation.utils import calculate_countdown
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.graduation.constants import RiskCategory
from juloserver.julo.models import FeatureSetting, Application
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_customer_suspended_unsuspended
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()
APPLICATION_APPROVED_DAT_LEAST_DAY = 30


@task(queue='loan_low')
def upgrade_entry_level_for_regular_customer():
    services.GraduationRegularCustomer().handle()


@task(queue='loan_normal')
def refresh_materialized_view_graduation_regular_customer_accounts():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GRADUATION_REGULAR_CUSTOMER, is_active=True
    ).last()
    if not feature_setting:
        return

    with connection.cursor() as cursor:
        cursor.execute('REFRESH MATERIALIZED VIEW ops.graduation_regular_customer_accounts')


def get_valid_approval_account_ids(account_ids, is_first_graduate):
    valid_account_ids = list(Application.objects.filter(
        account_id__in=account_ids,
        account__status_id=AccountConstant.STATUS_CODE.active,
        applicationhistory__status_new=ApplicationStatusCodes.LOC_APPROVED,
        applicationhistory__cdate__lte=date.today() - timedelta(
            days=APPLICATION_APPROVED_DAT_LEAST_DAY
        )
    ).values_list('account_id', flat=True))

    invalid_account_ids = set(account_ids) - set(valid_account_ids)
    if invalid_account_ids:
        logger.info({
            'invalid_account_ids': list(invalid_account_ids),
            'function': 'get_valid_approval_account_ids',
            'is_first_graduate': is_first_graduate
        })
    return valid_account_ids


def get_valid_graduation_date_account_ids(account_ids, checking_date, is_first_graduate):
    if not is_first_graduate:
        account_ids = AccountProperty.objects.filter(
            last_graduation_date__lte=checking_date - relativedelta(months=2)
        ).values_list('account_id', flat=True)
    return account_ids


@task(queue='loan_low')
def process_graduation(account_ids, checking_date, graduation_rule, is_first_graduate):
    try:
        account_ids = get_valid_approval_account_ids(account_ids, is_first_graduate)
        account_ids = get_valid_graduation_date_account_ids(
            account_ids, checking_date, is_first_graduate
        )
        passed_clcs_rules_account_ids = services.get_passed_clcs_rules_account_ids(
            account_ids, checking_date
        )
        if passed_clcs_rules_account_ids:
            evaluate_less_risky_customers_graduation.delay(passed_clcs_rules_account_ids)

        #Payment rules
        passed_manual_rules_account_ids = services.get_passed_manual_rules_account_ids(
            set(account_ids) - set(passed_clcs_rules_account_ids), checking_date, graduation_rule, is_first_graduate
        )
        if passed_manual_rules_account_ids:
            evaluate_less_risky_customers_graduation.delay(passed_manual_rules_account_ids)

    except Exception:
        sentry_client.captureException()

    logger.info({
        'action': 'juloserver.graduation.tasks.process_graduation',
        'account_ids': account_ids,
        'checking_date': checking_date,
        'graduation_rule': graduation_rule,
        'is_first_graduate': is_first_graduate,
        'message': 'success',
    })


@task(queue='loan_low')
def evaluate_less_risky_customers_graduation(account_ids):
    """
        - if customer is less risky, can graduate
        - if customer is not less risky, can be evaluated again with risky validation
    """
    valid_account_ids = services.evaluate_account_limit_utilization(account_ids)

    if valid_account_ids:
        logger.info({
            'field': 'valid_account_ids',
            'action': 'evaluate_less_risky_customers_graduation',
            'data': valid_account_ids
        })
        regular_customer_graduation.delay(valid_account_ids, RiskCategory.LESS_RISKY)

    invalid_account_ids = set(account_ids) - set(valid_account_ids)
    if invalid_account_ids:
        logger.info({
            'field': 'invalid_account_ids',
            'action': 'evaluate_less_risky_customers_graduation',
            'data': invalid_account_ids
        })
        evaluate_risky_customers_graduation(invalid_account_ids)


def evaluate_risky_customers_graduation(account_ids):
    """
        - if customer's clcs_prime_score is bigger or equal than 0.95, can graduate
        - if customer's clcs_prime_score is smaller than 0.95, can not graduate
    """
    valid_account_ids = services.evaluate_account_clcs_prime_score(account_ids)

    if valid_account_ids:
        logger.info({
            'field': 'valid_account_ids',
            'action': 'evaluate_risky_customers_graduation',
            'data': valid_account_ids
        })
        regular_customer_graduation.delay(valid_account_ids, RiskCategory.RISKY)


@task(queue='loan_low')
def regular_customer_graduation(account_ids, risk_category):
    logger.info({
        'action': 'regular_customer_graduation',
        'account_ids': account_ids,
        'risk_category': risk_category
    })
    for account_id in account_ids:
        is_valid = services.check_fdc_graduation(account_id)
        if not is_valid:
            logger.info({
                'action': 'juloserver.graduation.regular_customer_graduation',
                'graduation_type': GraduationType.REGULAR_CUSTOMER,
                'account_id': account_id,
                'passed_fdc_check': is_valid,
            })
            continue
        automatic_customer_graduation.delay(account_id, risk_category)


@task(queue='loan_low')
def automatic_customer_graduation(account_id, risk_category):
    with db_transactions_atomic(DbConnectionAlias.utilization()):
        account_limit = AccountLimit.objects.select_for_update().get(account_id=account_id)
        new_account_limit = services.regular_customer_graduation_new_limit_generator(
            account_id,
            risk_category,
            account_limit
        )
        if account_limit.set_limit == new_account_limit:
            logger.info({
                'action': 'juloserver.graduation.automatic_customer_graduation',
                'graduation_type': GraduationType.REGULAR_CUSTOMER,
                'account_id': account_id,
                'same_limit_generated': account_limit.set_limit == new_account_limit
            })
            return
        account_property = AccountProperty.objects.select_for_update().get(account_id=account_id)
        new_available_limit = new_account_limit - account_limit.used_limit
        services.update_post_graduation(
            GraduationType.REGULAR_CUSTOMER,
            account_property,
            account_limit,
            new_available_limit,
            new_account_limit
        )


# graduation new flow
def manual_graduation_customer(date_run_str=None):
    # call manual_graduation_customer('2023-06-12')
    if date_run_str:
        date_run = datetime.strptime(date_run_str, "%Y-%m-%d").date()
    else:
        date_run = timezone.localtime(timezone.now()).date()

    qs = CustomerGraduation.objects.filter(
        cdate__date=date_run,
        is_graduate=True
    ).values('account_id', 'new_set_limit', 'new_max_limit', 'graduation_flow')
    for customer_graduation in qs.iterator():
        automatic_customer_graduation_new_flow.delay(
            customer_graduation['account_id'], customer_graduation['new_set_limit'],
            customer_graduation['new_max_limit'], customer_graduation['graduation_flow']
        )


@task(queue='loan_normal')
def graduation_customer():
    # request ana team change script insert partition date = today
    active_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GRADUATION_NEW_FLOW, is_active=True
    ).exists()
    if not active_feature_setting:
        return

    #  redis support stored max graduation id for process new data  if graduation in the day > 2nd
    redis_client = get_redis_client()
    max_graduation_id = redis_client.get(GraduationRedisConstant.MAX_CUSTOMER_GRADUATION_ID)
    today = timezone.localtime(timezone.now()).date()
    qs = CustomerGraduation.objects.filter(
        partition_date=today,
        is_graduate=True
    ).values('id', 'account_id', 'new_set_limit', 'new_max_limit', 'graduation_flow')
    if max_graduation_id:
        qs = qs.filter(id__gt=int(max_graduation_id))

    total = 0
    max_graduation_id = 0
    for customer_graduation in qs:
        automatic_customer_graduation_new_flow.delay(
            customer_graduation['id'], customer_graduation['account_id'],
            customer_graduation['new_set_limit'], customer_graduation['new_max_limit'],
            customer_graduation['graduation_flow']
        )
        max_graduation_id = max(customer_graduation['id'], max_graduation_id)
        total += 1

    if max_graduation_id:
        redis_client.set(GraduationRedisConstant.MAX_CUSTOMER_GRADUATION_ID, max_graduation_id)

    if total:
        notify_slack_graduation_customer.apply_async(
            (qs.first()['id'], max_graduation_id, total), countdown=calculate_countdown(total)
        )


@task(queue='loan_low')
def notify_slack_graduation_customer(first_graduation_id, last_graduation_id, total):
    succeed_count = GraduationCustomerHistory2.objects.filter(
        customer_graduation_id__gte=first_graduation_id,
        customer_graduation_id__lte=last_graduation_id,
        graduation_type__in=(GraduationType.ENTRY_LEVEL, GraduationType.REGULAR_CUSTOMER)
    ).count()

    message = 'Hi <!here> - Graduation run done:'
    sub_message = '\nTotal: {}\n'.format(total)
    sub_message += 'Succeed count: {}\n'.format(succeed_count)
    graduation_failures = CustomerGraduationFailure.objects.filter(
        customer_graduation_id__gte=first_graduation_id,
        customer_graduation_id__lte=last_graduation_id,
        type=GraduationFailureType.GRADUATION
    ).all()
    failed_result = {}
    for failure in graduation_failures:
        failure_reason = failure.failure_reason
        failed_result[failure.failure_reason] = failed_result.setdefault(failure_reason, 0) + 1

    if failed_result:
        sub_message += 'Failed count:\n'
    for failed_reason, count in failed_result.items():
        sub_message += '\t{}: {}\n'.format(failed_reason, count)

    message += '```{}```'.format(sub_message)
    slack_bot_client = get_slack_bot_client()
    slack_bot_client.api_call(
        "chat.postMessage",
        channel=settings.SLACK_GRADUATION_ALERTS,
        text=message
    )


@task(queue='loan_low')
def automatic_customer_graduation_new_flow(graduation_id, account_id, new_set_limit, new_max_limit,
                                           graduation_flow):
    failure_type = GraduationFailureType.GRADUATION
    account = Account.objects.get_or_none(
        id=account_id, status_id=AccountConstant.STATUS_CODE.active
    )
    if not account:
        reason = 'invalid account status'
        services.store_failure_record(
            graduation_id, failure_reason=reason, type=failure_type
        )
        return

    application = account.get_active_application()
    if not application:
        reason = 'application is deleted'
        services.store_failure_record(
            graduation_id, failure_reason=reason, type=failure_type
        )
        return

    with db_transactions_atomic(DbConnectionAlias.utilization()):
        account_limit = AccountLimit.objects.select_for_update().get(account_id=account_id)
        if account_limit.set_limit >= new_set_limit:
            reason = 'set limit >= new set_limit'
            services.store_failure_record(
                graduation_id, failure_reason=reason, type=failure_type
            )
            return
        if account_limit.max_limit > new_max_limit:
            reason = 'max limit > new max_limit'
            services.store_failure_record(
                graduation_id, failure_reason=reason, type=failure_type
            )
            return
        account_property = AccountProperty.objects.get(account_id=account_id)
        if account_property.is_entry_level:
            graduation_type = GraduationType.ENTRY_LEVEL
        else:
            graduation_type = GraduationType.REGULAR_CUSTOMER
        new_available_limit = account_limit.available_limit + \
                              (new_set_limit - account_limit.set_limit)
        services.update_post_graduation(
            graduation_type,
            account_property,
            account_limit,
            new_available_limit,
            new_set_limit,
            new_max_limit=new_max_limit,
            graduation_id=graduation_id,
            graduation_flow=graduation_flow,
        )


@task(queue='loan_normal')
def run_downgrade_customers():
    now = timezone.localtime(timezone.now())
    today = now.date()
    qs = CustomerGraduation.objects.filter(
        partition_date=today,
        is_graduate=False
    )

    total_downgrades = 0
    for customer_graduation in qs:
        serializer_data = CustomerGraduationSerializer(customer_graduation).data
        run_downgrade_account.delay(serializer_data)
        total_downgrades += 1

    notify_slack_downgrade_customer.apply_async(
        (total_downgrades, False, now.strftime('%d-%m-%Y %H:%M')),
        countdown=calculate_countdown(total_downgrades)
    )


@task(queue='loan_low')
def run_downgrade_account(customer_graduation):
    account_id = customer_graduation['account_id']
    new_set_limit = customer_graduation['new_set_limit']
    new_max_limit = customer_graduation['new_max_limit']
    graduation_flow = customer_graduation['graduation_flow']
    passed_criteria, reason = services.check_criteria_downgrade(account_id)
    passed_downgrade = passed_criteria
    failure_data = {
        'customer_graduation_id': customer_graduation['id'],
        'type': GraduationFailureType.DOWNGRADE,
        'failure_reason': reason
    }

    if passed_criteria:
        try:
            services.run_downgrade_limit(
                account_id,
                new_set_limit,
                new_max_limit,
                graduation_flow,
                customer_graduation['id']
            )
        except DowngradeMaxLimitException:
            passed_downgrade = False
            failure_data['failure_reason'] = GraduationFailureConst.FAILED_BY_MAX_LIMIT
            failure_data['skipped'] = True
        except DowngradeSetLimitException:
            passed_downgrade = False
            failure_data['failure_reason'] = GraduationFailureConst.FAILED_BY_SET_LIMIT
            failure_data['skipped'] = True

    if not passed_downgrade:
        services.store_failure_record(**failure_data)


@task(queue='loan_normal')
def retry_downgrade_customers():
    qs = CustomerGraduationFailure.objects.filter(
        type=GraduationFailureType.DOWNGRADE,
        is_resolved=False,
        skipped=False
    ).order_by('id')

    total_downgrades = 0
    for customer_graduation in qs:
        retry_downgrade_account.delay(
            customer_graduation.id,
            customer_graduation.customer_graduation_id
        )
        total_downgrades += 1

    notify_slack_downgrade_customer.apply_async(
        (total_downgrades, True, ''),
        countdown=calculate_countdown(total_downgrades)
    )


@task(queue='loan_low')
def retry_downgrade_account(failure_id, customer_graduation_id):
    failure = CustomerGraduationFailure.objects.get(id=failure_id)

    customer_graduation = CustomerGraduation.objects.filter(id=customer_graduation_id).last()
    if not customer_graduation:
        failure.skipped = True
        failure.save()
        return

    account_id = customer_graduation.account_id
    new_set_limit = customer_graduation.new_set_limit
    new_max_limit = customer_graduation.new_max_limit
    graduation_flow = customer_graduation.graduation_flow

    with transaction.atomic():
        passed_criteria, reason = services.check_criteria_downgrade(account_id)
        if passed_criteria:
            try:
                services.run_downgrade_limit(
                    account_id,
                    new_set_limit,
                    new_max_limit,
                    graduation_flow,
                    customer_graduation_id
                )
                failure.is_resolved = True
            except (DowngradeMaxLimitException, DowngradeSetLimitException):
                failure.skipped = True
        else:
            failure.retries += 1
            failure.failure_reason = reason
            if failure.retries >= GraduationFailureConst.MAX_RETRIES:
                failure.skipped = True

        failure.save()


@task(queue='loan_normal')
def scan_customer_suspend_unsuspend_for_sending_to_me():
    yesterday = timezone.localtime(timezone.now()) - timedelta(days=1)

    customer_suspend_histories = CustomerSuspendHistory.objects.filter(cdate__gte=yesterday)
    for suspend_history in customer_suspend_histories.iterator():
        send_user_attributes_to_moengage_customer_suspended_unsuspended.delay(
            suspend_history.customer_id,
            suspend_history.is_suspend_new,
            suspend_history.change_reason,
        )

    logger.info({
        'action': 'juloserver.graduation.task.scan_customer_suspend_unsuspend_for_sending_to_me',
        'msg': 'Dispatched all customer suspends'
    })


@task(queue='loan_low')
def notify_slack_downgrade_customer(total, is_retry=False, today_str=''):
    total_success = 0
    total_failed = 0
    message = ''
    if is_retry:
        message = 'Retry downgrade customer report\n'
        total_success, total_failed = services.calc_summary_retry_downgrade_customer(total)
    else:
        message = f'Downgrade customer report at {today_str}\n'
        total_success, total_failed = services.calc_summary_downgrade_customer(total, today_str)

    message += (
        f'  - Total: {total}\n' +\
        f'  - Successed: {total_success}\n' +\
        f'  - Failed: {total_failed}\n'
    )

    slack_bot_client = get_slack_bot_client()
    slack_bot_client.api_call(
        "chat.postMessage",
        channel=settings.SLACK_GRADUATION_ALERTS,
        text=message
    )


@task(queue='loan_normal')
def process_after_downgrade_limit(account_id):
    # Invalidate cache for downgrade alert API
    services.invalidate_downgrade_info_alert_cache(account_id)
