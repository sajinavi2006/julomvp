import logging
import json
import math
from datetime import timedelta, datetime
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models.signals import post_save
from django.utils import timezone
from django.db.models import (
    Q, Sum, Case, When, IntegerField, F, Count
)
from factory.django import mute_signals

from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.account.constants import AccountConstant, CreditLimitGenerationLog, \
    AccountLockReason
from juloserver.fdc.models import InitialFDCInquiryLoanData
from juloserver.julo.clients import get_julo_sentry_client
import juloserver.graduation.tasks as tasks
from juloserver.apiv2.models import PdClcsPrimeResult, PdCreditModelResult, PdWebModelResult
from juloserver.julo.exceptions import JuloException
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes, ApplicationStatusCodes
from juloserver.account.models import Account, CreditLimitGeneration, AccountLimit, \
    AccountLimitHistory, AccountPropertyHistory, AccountProperty
from juloserver.graduation.models import (
    CustomerGraduation,
    CustomerGraduationFailure,
    DowngradeCustomerHistory,
    GraduationRegularCustomerAccounts,
    GraduationCustomerHistory2,
    CustomerSuspend,
    CustomerSuspendHistory,
)
from juloserver.julo.models import FeatureSetting, Application, FDCInquiry
from juloserver.graduation.constants import (
    FeatureNameConst,
    GraduationRules,
    RiskCategory,
    GraduationAdditionalLimit,
    DefaultLimitClass,
    GraduationType,
    CustomerSuspendRedisConstant,
    GraduationFailureType,
    DowngradeInfoRedisConst,
)
from juloserver.graduation.exceptions import (
    DowngradeMaxLimitException,
    DowngradeSetLimitException,
)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_available_limit_created,
    send_user_attributes_to_moengage_after_graduation_downgrade
)
from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.julo.workflows2.tasks import appsflyer_update_status_task
from juloserver.julo.tasks import (
    send_pn_invalidate_caching_loans_android,
    send_pn_invalidate_caching_downgrade_alert,
)
from juloserver.julo.models import Customer
from juloserver.julo.utils import display_rupiah
from typing import Tuple


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()

QUERY_LIMIT = 1000
TOTAL_DAY_RUN_TASK = 10


class GraduationRegularCustomer(object):
    def __init__(self):
        self.today = timezone.localtime(timezone.now()).date()

    def generate_query(self, is_first_graduate):
        qs = GraduationRegularCustomerAccounts.objects.filter(
            last_graduation_date__isnull=is_first_graduate
        )
        total_items_per_day = math.ceil(qs.count() / TOTAL_DAY_RUN_TASK)
        from_record = self.today.day % TOTAL_DAY_RUN_TASK * total_items_per_day
        to_record = from_record + total_items_per_day
        return qs.order_by('account_id')[from_record: to_record]

    def handle(self, query_limit=QUERY_LIMIT):
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.GRADUATION_REGULAR_CUSTOMER, is_active=True
        ).last()
        if not feature_setting:
            return

        qs = self.generate_query(is_first_graduate=True).values_list('account_id', flat=True)
        graduation_rule = feature_setting.parameters['graduation_rule']

        for i in range(0, len(qs), query_limit):
            tasks.process_graduation.delay(
                qs[i:i + query_limit], self.today, graduation_rule, True
            )

        qs = self.generate_query(is_first_graduate=False).values_list('account_id', flat=True)
        for i in range(0, len(qs), query_limit):
            tasks.process_graduation.delay(
                qs[i:i + query_limit], self.today, graduation_rule, False
            )


def _filter_count_grace_payments(account_ids, to_date, max_grace_payment,
                                 is_first_graduate):
    if is_first_graduate:
        valid_account_ids = Account.objects.filter(id__in=account_ids).annotate(
            count_grace_payment=Sum(
                Case(
                    When(
                        loan__payment__payment_status_id=PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                        then=1
                    ), default=0, output_field=IntegerField()
                )
            )
        ).filter(count_grace_payment__lte=max_grace_payment).values_list('id', flat=True)
    else:
        valid_account_ids = Account.objects.filter(id__in=account_ids).annotate(
            last_graduation_date=F('accountproperty__last_graduation_date')
        ).annotate(
            count_grace_payment=Sum(
                Case(
                    When(
                        loan__payment__paid_date__gte=F('last_graduation_date'),
                        loan__payment__paid_date__lte=to_date,
                        loan__payment__payment_status_id=PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                        then=1
                    ), default=0, output_field=IntegerField()
                )
            )
        ).filter(count_grace_payment__lte=max_grace_payment).values_list('id', flat=True)

    invalid_account_ids = set(account_ids) - set(valid_account_ids)
    if invalid_account_ids:
        logger.info({
            'invalid_account_ids': list(invalid_account_ids),
            'function': '_filter_count_grace_payments',
            'max_grace_payment': max_grace_payment,
            'to_date': to_date,
            'is_first_graduate': is_first_graduate
        })
    return valid_account_ids


def _filter_count_late_payments(account_ids, to_date, max_late_payment,
                                is_first_graduate):
    if is_first_graduate:
        valid_account_ids = Account.objects.filter(id__in=account_ids).annotate(
            count_late_payment=Sum(
                Case(
                    When(
                        loan__payment__payment_status_id=PaymentStatusCodes.PAID_LATE,
                        then=1
                    ), default=0, output_field=IntegerField()
                )
            )
        ).filter(count_late_payment__lte=max_late_payment).values_list('id', flat=True)
    else:
        valid_account_ids = Account.objects.filter(id__in=account_ids).annotate(
            last_graduation_date=F('accountproperty__last_graduation_date')
        ).annotate(
            count_late_payment=Sum(
                Case(
                    When(
                        loan__payment__paid_date__gte=F('last_graduation_date'),
                        loan__payment__paid_date__lte=to_date,
                        loan__payment__payment_status_id=PaymentStatusCodes.PAID_LATE,
                        then=1
                    ), default=0, output_field=IntegerField()
                )
            )
        ).filter(count_late_payment__lte=max_late_payment).values_list('id', flat=True)

    invalid_account_ids = set(account_ids) - set(valid_account_ids)
    if invalid_account_ids:
        logger.info({
            'invalid_account_ids': list(invalid_account_ids),
            'function': '_filter_count_late_payments',
            'max_late_payment': max_late_payment,
            'to_date': to_date,
            'is_first_graduate': is_first_graduate
        })
    return valid_account_ids


def _filter_count_not_paid_payments(account_ids, to_date, max_not_paid_payment,
                                    is_first_graduate):
    if is_first_graduate:
        valid_account_ids = Account.objects.filter(id__in=account_ids).annotate(
            count_not_paid_payment=Sum(
                Case(
                    When(Q(
                        loan__payment__payment_status_id__gte=PaymentStatusCodes.PAYMENT_1DPD,
                        loan__payment__payment_status_id__lte=PaymentStatusCodes.PAYMENT_180DPD,
                        loan__payment__due_date__lt=to_date - timedelta(days=4)
                    ), then=1),
                    default=0, output_field=IntegerField()
                )
            )
        ).filter(count_not_paid_payment__lte=max_not_paid_payment).values_list('id', flat=True)
    else:
        valid_account_ids = Account.objects.filter(id__in=account_ids).annotate(
            last_graduation_date=F('accountproperty__last_graduation_date')
        ).annotate(
            count_not_paid_payment=Sum(
                Case(
                    When(Q(
                        loan__payment__due_date__gte=F('last_graduation_date'),
                        loan__payment__due_date__lte=to_date,
                        loan__payment__payment_status_id__gte=PaymentStatusCodes.PAYMENT_1DPD,
                        loan__payment__payment_status_id__lte=PaymentStatusCodes.PAYMENT_180DPD,
                        loan__payment__due_date__lt=to_date - timedelta(days=4)
                    ), then=1),
                    default=0, output_field=IntegerField()
                )
            )
        ).filter(count_not_paid_payment__lte=max_not_paid_payment).values_list('id', flat=True)

    invalid_account_ids = set(account_ids) - set(valid_account_ids)
    if invalid_account_ids:
        logger.info({
            'invalid_account_ids': list(invalid_account_ids),
            'function': '_filter_count_not_paid_payments',
            'max_not_paid_payment': max_not_paid_payment,
            'to_date': to_date,
            'is_first_graduate': is_first_graduate
        })
    return valid_account_ids


def _filter_min_paid_per_credit_limit(account_ids, to_date,
                                      percentage_paid_per_credit_limit, is_first_graduate):
    if is_first_graduate:
        valid_account_ids = Account.objects.filter(id__in=account_ids).annotate(
            total_paid_amount=Sum('loan__payment__paid_amount')
        ).annotate(
            current_set_limit=F('accountlimit__set_limit')
        ).filter(
            total_paid_amount__gte=F('current_set_limit') * percentage_paid_per_credit_limit
        ).values_list('id', flat=True)
    else:
        valid_account_ids = Account.objects.filter(id__in=account_ids).annotate(
            last_graduation_date=F('accountproperty__last_graduation_date')
        ).annotate(
            total_paid_amount=Sum(
                Case(
                    When(Q(
                        loan__payment__paid_date__gte=F('last_graduation_date'),
                        loan__payment__paid_date__lte=to_date,
                    ), then='loan__payment__paid_amount'),
                    default=0, output_field=IntegerField()
                )
            )
        ).annotate(
            current_set_limit=F('accountlimit__set_limit')
        ).filter(
            total_paid_amount__gte=F('current_set_limit') * percentage_paid_per_credit_limit
        ).values_list('id', flat=True)

    invalid_account_ids = set(account_ids) - set(valid_account_ids)
    if invalid_account_ids:
        logger.info({
            'invalid_account_ids': list(invalid_account_ids),
            'function': '_filter_min_paid_per_credit_limit',
            'percentage_paid_per_credit_limit': percentage_paid_per_credit_limit,
            'to_date': to_date,
            'is_first_graduate': is_first_graduate
        })
    return valid_account_ids


def _filter_count_paid_off_loan(account_ids, to_date, min_paid_off_loan,
                                is_first_graduate):
    if is_first_graduate:
        valid_account_ids = Account.objects.filter(id__in=account_ids).annotate(
            count_paid_off_loan=Sum(
                Case(
                    When(Q(
                        loan__loan_status_id=LoanStatusCodes.PAID_OFF,
                    ), then=1), default=0, output_field=IntegerField()
                )
            )
        ).filter(count_paid_off_loan__gte=min_paid_off_loan).values_list('id', flat=True)
    else:
        valid_account_ids = Account.objects.filter(id__in=account_ids).annotate(
            last_graduation_date=F('accountproperty__last_graduation_date')
        ).annotate(
            count_paid_off_loan=Sum(
                Case(
                    When(Q(
                        loan__loanhistory__cdate__date__gte=F('last_graduation_date'),
                        loan__loanhistory__cdate__date__lte=to_date,
                        loan__loanhistory__status_new=LoanStatusCodes.PAID_OFF,
                    ), then=1), default=0, output_field=IntegerField()
                )
            )
        ).filter(
            count_paid_off_loan__gte=min_paid_off_loan
        ).values_list('id', flat=True)

    invalid_account_ids = set(account_ids) - set(valid_account_ids)
    if invalid_account_ids:
        logger.info({
            'invalid_account_ids': list(invalid_account_ids),
            'function': '_filter_count_late_payments',
            'min_paid_off_loan': min_paid_off_loan,
            'to_date': to_date,
            'is_first_graduate': is_first_graduate
        })
    return valid_account_ids


def get_passed_manual_rules_account_ids(account_ids, checking_date, graduation_rule,
                                        is_first_graduate):
    percentage_paid_per_credit_limit = graduation_rule["min_percentage_paid_per_credit_limit"] / 100

    account_ids = _filter_count_grace_payments(
        account_ids, checking_date, graduation_rule["max_grace_payment"],
        is_first_graduate
    )
    account_ids = _filter_count_late_payments(
        account_ids, checking_date, graduation_rule["max_late_payment"],
        is_first_graduate
    )
    account_ids = _filter_count_not_paid_payments(
        account_ids, checking_date, graduation_rule["max_not_paid_payment"],
        is_first_graduate
    )
    account_ids = _filter_min_paid_per_credit_limit(
        account_ids, checking_date, percentage_paid_per_credit_limit, is_first_graduate
    )

    account_ids = _filter_count_paid_off_loan(
        account_ids, checking_date, graduation_rule["min_paid_off_loan"],
        is_first_graduate
    )

    return account_ids


def get_pd_clcs_prime_result_months_mappings(customer_ids, from_date, to_date):
    pd_clcs_prime_results = PdClcsPrimeResult.objects.filter(
        customer_id__in=customer_ids,
        partition_date__range=[from_date, to_date]
    ).order_by('partition_date').values('customer_id', 'clcs_prime_score', 'partition_date')
    pd_clcs_prime_result_months_mappings = {}
    for item in pd_clcs_prime_results:
        value = item['clcs_prime_score']
        if value is None:
            continue
        pd_clcs_prime_result_months_mappings.setdefault(item['customer_id'], {}).update({
            item['partition_date'].strftime('%Y-%m'): math.floor(value * 20) / 20
        })
    return pd_clcs_prime_result_months_mappings


def get_pgood_by_customers_mappings(customer_ids):
    pd_credit_model_results = PdCreditModelResult.objects.filter(
        customer_id__in=customer_ids
    ).order_by('id').values('customer_id', 'pgood')
    result = {
        item['customer_id']: math.floor(item['pgood'] * 20) / 20
        for item in pd_credit_model_results if item['pgood']
    }
    remaining_customer_ids = set(customer_ids) - set(result.keys())
    pd_web_model_results = PdWebModelResult.objects.filter(
        customer_id__in=remaining_customer_ids
    ).order_by('id').values('customer_id', 'pgood')
    result.update({
        item['customer_id']:
            math.floor(item['pgood'] * 20) / 20 for item in pd_web_model_results if item['pgood']
    })
    return result


def get_passed_clcs_rules_account_ids(account_ids, checking_date):
    from_date = (checking_date - relativedelta(months=1)).replace(day=1)

    accounts = Account.objects.filter(id__in=account_ids).values('id', 'customer_id')
    account_customer_mappings = {account['customer_id']: account['id'] for account in accounts}

    customer_ids = account_customer_mappings.keys()
    pgood_by_customers_mappings = get_pgood_by_customers_mappings(customer_ids)
    pgood_customer_ids = pgood_by_customers_mappings.keys()

    pd_clcs_prime_result_months_mappings = get_pd_clcs_prime_result_months_mappings(
        pgood_customer_ids, from_date, checking_date
    )
    result = set()
    current_month_str = checking_date.strftime('%Y-%m')
    prev_month_str = from_date.strftime('%Y-%m')
    for customer_id, customer_score in pd_clcs_prime_result_months_mappings.items():
        if current_month_str not in customer_score or prev_month_str not in customer_score:
            continue
        if customer_score[current_month_str] <= customer_score[prev_month_str]:
            continue
        if customer_score[current_month_str] <= pgood_by_customers_mappings[customer_id]:
            continue
        result.add(account_customer_mappings[customer_id])

    invalid_account_ids = set(account_ids) - result
    if invalid_account_ids:
        logger.info({
            'invalid_account_ids': list(invalid_account_ids),
            'function': 'get_passed_clcs_rules_account_ids',
            'to_date': checking_date,
        })
    return result


def evaluate_account_limit_utilization(account_ids):
    max_limit_utilization = GraduationRules.LIMIT_UTILIZATION
    valid_account_ids = Account.objects.filter(
        id__in=account_ids,
        accountlimit__used_limit__lt=F('accountlimit__set_limit') * max_limit_utilization
    ).values_list('id', flat=True)

    return valid_account_ids


def evaluate_account_clcs_prime_score(account_ids):
    min_clcs_prime_score = GraduationRules.CLCS_PRIME_SCORE
    accounts = Account.objects.filter(
        id__in=account_ids
    ).values('id', 'customer_id')
    account_customer_mappings = {account['customer_id']: account['id'] for account in accounts}
    pdclcs_prime_scores = PdClcsPrimeResult.objects. \
        filter(customer_id__in=account_customer_mappings.keys(),
               clcs_prime_score__gte=min_clcs_prime_score). \
        order_by('customer_id', '-partition_date').distinct('customer_id')
    valid_account_ids = []
    for item in pdclcs_prime_scores:
        account_id = account_customer_mappings.get(item.customer_id)
        if account_id:
            valid_account_ids.append(account_id)

    return valid_account_ids


def regular_customer_graduation_new_limit_generator(account_id, risk_category, account_limit):
    current_limit = account_limit.set_limit

    new_limit = current_limit
    if risk_category == RiskCategory.LESS_RISKY:
        if current_limit < DefaultLimitClass.ONE_MILLION:
            new_limit = GraduationAdditionalLimit.ONE_MILLION
        elif DefaultLimitClass.ONE_MILLION <= current_limit < DefaultLimitClass.FIVE_MILLION:
            new_limit = current_limit + GraduationAdditionalLimit.ONE_MILLION
        elif DefaultLimitClass.FIVE_MILLION <= current_limit < DefaultLimitClass.TEN_MILLION:
            new_limit = current_limit + GraduationAdditionalLimit.TWO_MILLION
        elif DefaultLimitClass.TEN_MILLION <= current_limit:
            new_limit = current_limit + GraduationAdditionalLimit.FOUR_MILLION
    elif risk_category == RiskCategory.RISKY:
        if 0 <= current_limit < DefaultLimitClass.ONE_MILLION:
            new_limit = GraduationAdditionalLimit.ONE_MILLION
        elif DefaultLimitClass.ONE_MILLION <= current_limit:
            new_limit = current_limit + GraduationAdditionalLimit.ONE_MILLION

    account = Account.objects.get(id=account_id)
    application = account.last_application
    credit_limit = CreditLimitGeneration.objects.filter(
        application=application,
    ).last()
    credit_limit_log_json = json.loads(credit_limit.log)
    max_limit_pre_matrix = int(credit_limit_log_json["max_limit (pre-matrix)"])

    logger.info({
        'action': 'regular_customer_graduation_new_limit_generator',
        'account_id': account_id,
        'new_account_limit': new_limit,
        'max_limit_pre_matrix': max_limit_pre_matrix
    })

    if max_limit_pre_matrix < new_limit:
        return max_limit_pre_matrix
    else:
        return new_limit


def check_entry_customer_affordability(new_limit, account_id):
    max_credit_limit_gen = CreditLimitGeneration.objects.filter(account_id=account_id).last()
    credit_limit_log = max_credit_limit_gen.log

    credit_limit_log_json = json.loads(credit_limit_log)
    max_limit_pre_matrix = int(credit_limit_log_json[CreditLimitGenerationLog.MAX_LIMIT_PRE_MATRIX])

    return min(new_limit, max_limit_pre_matrix)


def update_post_graduation(graduation_type, account_property, account_limit, new_available_limit,
                           new_account_limit, new_max_limit=None, graduation_id=None,
                           graduation_flow=None):
    today = timezone.localtime(timezone.now()).date()
    last_graduation_date = account_property.last_graduation_date

    available_limit_history, max_limit_history, set_limit_history = \
        update_account_limit_graduation(
            account_limit, new_available_limit, new_account_limit, new_max_limit,
            graduation_flow=graduation_flow
        )

    account_property.update_safely(last_graduation_date=today)
    AccountPropertyHistory.objects.create(
        account_property=account_property,
        field_name='last_graduation_date',
        value_new=today,
        value_old=last_graduation_date
    )
    if graduation_type == GraduationType.ENTRY_LEVEL:
        account_property.update_safely(is_entry_level=False)
        AccountPropertyHistory.objects.create(
            account_property=account_property,
            field_name='is_entry_level',
            value_old=True,
            value_new=False
        )
    GraduationCustomerHistory2.objects.filter(
        account_id=account_property.account_id,
        latest_flag=True
    ).update(latest_flag=False)
    gdh = {
        "account_id": account_property.account_id,
        "graduation_type": graduation_type,
        "available_limit_history_id": getattr(available_limit_history, 'id', None),
        "max_limit_history_id": getattr(max_limit_history, 'id', None),
        "set_limit_history_id": getattr(set_limit_history, 'id', None),
        "latest_flag": True
    }
    if graduation_id is not None:
        gdh["customer_graduation_id"] = graduation_id
    GraduationCustomerHistory2.objects.create(**gdh)


def update_post_graduation_for_balance_consolidation(graduation_type, account_property,
                                                     account_property_history_dict):
    today = timezone.localtime(timezone.now()).date()
    last_graduation_date = account_property.last_graduation_date
    account_property.update_safely(last_graduation_date=today)

    AccountPropertyHistory.objects.create(
        account_property=account_property,
        field_name='last_graduation_date',
        value_new=today,
        value_old=last_graduation_date
    )
    GraduationCustomerHistory2.objects.filter(
        account_id=account_property.account_id,
        latest_flag=True
    ).update(latest_flag=False)
    GraduationCustomerHistory2.objects.create(
        account_id=account_property.account_id,
        graduation_type=graduation_type,
        available_limit_history_id=account_property_history_dict['available_limit'],
        max_limit_history_id=account_property_history_dict['max_limit'],
        set_limit_history_id=account_property_history_dict['set_limit'],
        latest_flag=True,
    )


def update_account_limit_graduation(account_limit, new_available_limit, new_account_limit,
                                    new_max_limit=None, is_graduated=True, graduation_flow=None):
    available_limit_history = None
    max_limit_history = None
    set_limit_history = None
    old_set_limit = account_limit.set_limit
    last_history_id = account_limit.latest_affordability_history_id
    account = account_limit.account
    customer = account.customer

    if account_limit.available_limit != new_available_limit:
        execute_after_transaction_safely(
            lambda: send_user_attributes_to_moengage_for_available_limit_created.delay(
                customer,
                account,
                account_limit.available_limit,
            )
        )

        if is_graduated:
            graduated_event = 'is_graduated'
            graduated_params = {'new_set_limit': new_account_limit}
            application = account.get_active_application()
            execute_after_transaction_safely(
                lambda: send_event_to_ga_task_async.apply_async(
                    kwargs={
                        'customer_id': account.customer_id,
                        'event': graduated_event,
                        'extra_params': graduated_params
                    }
                )
            )

            execute_after_transaction_safely(
                lambda: appsflyer_update_status_task.delay(
                    application.id, graduated_event, extra_params=graduated_params)
            )

        available_limit_history = AccountLimitHistory.objects.create(
            account_limit=account_limit,
            field_name='available_limit',
            value_old=str(account_limit.available_limit),
            value_new=str(new_available_limit),
            affordability_history_id=last_history_id,
            credit_score_id=account_limit.latest_credit_score_id,
        )
    # Assign new_max_limit equal new_set_limit if it is not provided
    if new_max_limit is None:
        new_max_limit = new_account_limit
    if account_limit.max_limit != new_max_limit:
        max_limit_history = AccountLimitHistory.objects.create(
            account_limit=account_limit,
            field_name='max_limit',
            value_old=str(account_limit.max_limit),
            value_new=str(new_max_limit),
            affordability_history_id=last_history_id,
            credit_score_id=account_limit.latest_credit_score_id,
        )
    if account_limit.set_limit != new_account_limit:
        set_limit_history = AccountLimitHistory.objects.create(
            account_limit=account_limit,
            field_name='set_limit',
            value_old=str(account_limit.set_limit),
            value_new=str(new_account_limit),
            affordability_history_id=last_history_id,
            credit_score_id=account_limit.latest_credit_score_id,
        )
        execute_after_transaction_safely(
            lambda: send_user_attributes_to_moengage_after_graduation_downgrade.delay(
                account_limit.id, new_account_limit, old_set_limit, is_graduated,
                graduation_flow=graduation_flow,
                graduation_date=timezone.localtime(timezone.now())
            )
        )

    with mute_signals(post_save):
        account_limit.update_safely(
            set_limit=new_account_limit,
            max_limit=new_max_limit,
            available_limit=new_available_limit
        )
    return available_limit_history, max_limit_history, set_limit_history


def check_fdc_graduation(account_id):
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRADUATION_FDC_CHECK, is_active=True)
    if not fs:
        return True

    application = Application.objects.get_or_none(
        account_id=account_id,
        application_status=ApplicationStatusCodes.LOC_APPROVED
    )
    if not application:
        return False

    try:
        is_valid = check_fdc_graduation_conditions(application)
    except JuloException:
        sentry_client.captureException()
        return False

    return is_valid


def check_fdc_graduation_conditions(application):
    latest_fdc_inquiry = FDCInquiry.objects.filter(application_id=application.id).last()
    if not latest_fdc_inquiry:
        return False
    latest_fdc_inquiry_loans = latest_fdc_inquiry.fdcinquiryloan_set.exclude(is_julo_loan=True)
    check_loan = latest_fdc_inquiry_loans.aggregate(
        count_delinquent=Count(Case(When(dpd_terakhir__gt=5, then=1),
                                    output_field=IntegerField())),
        count_outstanding=Count(Case(When(status_pinjaman='Outstanding', then=1),
                                     output_field=IntegerField()))
    )
    if check_loan['count_delinquent'] > 0:
        return False

    init_fdc_inquiry = FDCInquiry.objects.filter(application_id=application.id).first()
    init_fdc_loan_data = InitialFDCInquiryLoanData.objects.filter(
        fdc_inquiry=init_fdc_inquiry
    ).last()
    if not init_fdc_loan_data:
        raise JuloException("Missing data from FDC Initial Loan Data")
    outstanding_loan_count = init_fdc_loan_data.initial_outstanding_loan_count_x100
    if check_loan['count_outstanding'] > outstanding_loan_count:
        return False

    return True


def retroload_graduation_customer_history(record_list):
    account_ids = {int(record['account_id']) for record in record_list}
    retroload_graduation_customer_list = []
    for record in record_list:
        retroload_graduation_customer_list.append(
            GraduationCustomerHistory2(
                cdate=timezone.localtime(datetime.strptime(record['graduation_date'], "%Y-%m-%d")),
                account_id=int(record['account_id']),
                graduation_type=GraduationType.ENTRY_LEVEL,
                available_limit_history_id=int(record['available_limit_history_id']) if record['available_limit_history_id'] else None,
                max_limit_history_id=int(record['max_limit_history_id']) if record['max_limit_history_id'] else None,
                set_limit_history_id=int(record['set_limit_history_id']) if record['set_limit_history_id'] else None,
                latest_flag=(record['latest_flag'] == 'true'),
            )
        )

    account_property_ids = AccountProperty.objects.filter(
        account_id__in=account_ids,
    ).values_list('id', flat=True)
    account_property_history_list = []
    for account_property_id in account_property_ids:
        account_property_history_list.append(
            AccountPropertyHistory(
                account_property_id=account_property_id,
                field_name='is_entry_level',
                value_old=True,
                value_new=False
            )
        )

    with transaction.atomic():
        GraduationCustomerHistory2.objects.bulk_create(retroload_graduation_customer_list)
        # Update entry_level of account_property
        AccountProperty.objects.filter(
            account_id__in=account_ids,
            is_entry_level=True
        ).update(is_entry_level=False)
        AccountPropertyHistory.objects.bulk_create(account_property_history_list)


def is_customer_suspend(customer_id):
    redis_client = get_redis_client()
    customer_suspend_redis_key = CustomerSuspendRedisConstant.CUSTOMER_SUSPEND.format(customer_id)
    lock_reason = redis_client.get(customer_suspend_redis_key)
    if lock_reason is not None:
        return True, lock_reason

    customer_suspend = CustomerSuspend.objects.filter(
        customer_id=customer_id, is_suspend=True
    ).last()
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CUSTOMER_SUSPEND, is_active=True
    ).last()
    ttl = CustomerSuspendRedisConstant.REDIS_CACHE_TTL_DEFAULT_HOUR
    if fs:
        parameters = fs.parameters or {}
        ttl = parameters.get('redis_cache_ttl_hour', ttl)

    if customer_suspend:
        last_suspend_history = CustomerSuspendHistory.objects.filter(customer_id=customer_id).last()
        execute_after_transaction_safely(
            lambda: send_pn_invalidate_caching_loans_android.delay(customer_id, None, None)
        )
        lock_reason = AccountLockReason.CUSTOMER_SUSPENDED
        if last_suspend_history:
            lock_reason = get_lock_reason_code_by_suspend_change_reason(
                last_suspend_history.change_reason
            )
        redis_client.set(customer_suspend_redis_key, lock_reason, timedelta(hours=ttl))

        return True, lock_reason

    return False, None


def get_lock_reason_code_by_suspend_change_reason(change_reason):
    from juloserver.julo.constants import FeatureNameConst
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.SUSPEND_CHANGE_REASON_MAP_PRODUCT_LOCK_CODE
    )
    if not fs:
        return AccountLockReason.CUSTOMER_SUSPENDED

    parameters = fs.parameters or {}
    return parameters.get(change_reason, AccountLockReason.CUSTOMER_SUSPENDED)


def get_customer_suspend_codes():
    from juloserver.julo.constants import FeatureNameConst
    from juloserver.julo.models import FeatureSetting

    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SUSPEND_CHANGE_REASON_MAP_PRODUCT_LOCK_CODE
    ).first()

    if fs and fs.parameters:
        return list(fs.parameters.values())

    return []


def check_criteria_downgrade(account_id):
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.DOWNGRADE_CRITERIA_CONFIG_FS,
        is_active=True
    )

    if not fs:
        return True, ''

    configs = fs.parameters
    is_passed = True
    reason = ''

    if configs.get('check_account_criteria', False):
        is_passed, reason = check_account_criteria(account_id)

    if is_passed and configs.get('next_period_days'):
        period_days = configs['next_period_days']
        is_passed, reason = check_action_period_time_downgrade(account_id, period_days)

    return is_passed, reason


def check_account_criteria(account_id):
    account = Account.objects.get_or_none(id=account_id)
    if not account:
        reason = 'Account does not exist'
        logger.error({
            'invalid_account_id': account_id,
            'action': 'check_criteria_downgrade',
            'msg': reason
        })
        return False, reason

    return True, ''


def check_action_period_time_downgrade(account_id, period_days):
    today = timezone.localtime(timezone.now()).date()
    n_date_before = today - timedelta(days=period_days - 1)
    model_pairs = [
        ('graduation', GraduationCustomerHistory2),
        ('downgrade', DowngradeCustomerHistory)
    ]
    for action_name, HistModel in model_pairs:
        exists_hist = HistModel.objects.filter(
            account_id=account_id,
            latest_flag=True,
            cdate__gt=n_date_before
        ).exists()
        if exists_hist:
            reason = f'account had {action_name} action in the last {period_days} days'
            logger.error({
                'reason': reason,
                'action': 'check_criteria_downgrade',
            })
            return False, reason

    return True, ''


def store_failure_record(customer_graduation_id, **kwargs):
    return CustomerGraduationFailure.objects.create(
        customer_graduation_id=customer_graduation_id,
        retries=0,
        is_resolved=False,
        **kwargs
    )


def run_downgrade_limit(account_id, new_set_limit, new_max_limit,
                        graduation_flow, customer_graduation_id=None):
    with db_transactions_atomic(DbConnectionAlias.utilization()):
        account_limit = AccountLimit.objects.select_for_update().get(account_id=account_id)
        if account_limit.set_limit <= new_set_limit:
            raise DowngradeSetLimitException()
        if account_limit.max_limit < new_max_limit:
            raise DowngradeMaxLimitException()
        new_available_limit = account_limit.available_limit - \
                                (account_limit.set_limit - new_set_limit)

        available_limit_history, max_limit_history, set_limit_history = \
            update_account_limit_graduation(
                account_limit, new_available_limit, new_set_limit, new_max_limit,
                is_graduated=False, graduation_flow=graduation_flow
            )

        DowngradeCustomerHistory.objects.filter(
            account_id=account_limit.account_id,
            latest_flag=True
        ).update(latest_flag=False)
        DowngradeCustomerHistory.objects.create(
            account_id=account_limit.account_id,
            downgrade_type=GraduationType.REGULAR_CUSTOMER,
            customer_graduation_id=customer_graduation_id,
            available_limit_history_id=getattr(available_limit_history, 'id', None),
            max_limit_history_id=getattr(max_limit_history, 'id', None),
            set_limit_history_id=getattr(set_limit_history, 'id', None),
            latest_flag=True,
        )
    execute_after_transaction_safely(
        lambda: tasks.process_after_downgrade_limit(account_id)
    )


def calc_summary_downgrade_customer(total, today_str):
    today = datetime.strptime(today_str, '%d-%m-%Y %H:%M').date()
    qs = CustomerGraduation.objects.filter(
        partition_date=today,
        is_graduate=False
    ).values_list('id', flat=True).order_by('id')

    CHUNK_SIZE = 2000
    chunks = []
    batch = []
    for customer_graduation_id in qs:
        batch.append(customer_graduation_id)
        if len(batch) >= CHUNK_SIZE:
            chunks.append(batch[:])
            batch = []

    if len(batch):
        chunks.append(batch[:])

    total_success = 0
    for chunk in chunks:
        success_count = DowngradeCustomerHistory.objects.filter(customer_graduation_id__in=chunk).count()
        total_success += success_count

    return (total_success, total - total_success)


def calc_summary_retry_downgrade_customer(total):
    total_failed = CustomerGraduationFailure.objects.filter(
        type=GraduationFailureType.DOWNGRADE,
        is_resolved=False,
        skipped=False
    ).count()

    return (total - total_failed, total_failed)


def check_condition_to_show_downgrade_info_alert(customer: Customer, downgrade_period: int) -> Tuple[bool, dict]:
    # Check if the customer has a downgrade history in last 2 months
    today = timezone.localtime(timezone.now()).date()
    n_date_before = today - timedelta(days=downgrade_period)

    last_downgrade_history = DowngradeCustomerHistory.objects.filter(
        account_id=customer.account.pk,
        latest_flag=True,
        cdate__gt=n_date_before,
    ).last()

    if last_downgrade_history:
        return True, last_downgrade_history.cdate.strftime('%d/%m/%Y %H:%M:%S %Z')

    return False, None


def get_customer_downgrade_info_alert(customer: Customer) -> dict:
    # Check FS
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DOWNGRADE_INFO_ALERT,
        is_active=True,
    ).last()
    if not fs:
        return {'is_showed_downgrade_alert': False}

    # Check data in redis first
    redis_client = get_redis_client()
    downgrade_info_redis_key = DowngradeInfoRedisConst.DOWNGRADE_INFO_ALERT.format(customer.pk)
    cached_data = redis_client.get(downgrade_info_redis_key)
    if cached_data:
        return json.loads(cached_data)

    parameters = fs.parameters
    period = parameters.get('downgrade_date_period', FeatureNameConst.DOWNGRADE_DATE_PERIOD)
    is_show, last_downgrade_date = check_condition_to_show_downgrade_info_alert(customer, period)

    data_response = construct_data_response_downgrade_info_alert(
        customer,
        is_show,
        last_downgrade_date,
        parameters
    )

    # Set data to redis
    redis_client.set(
        key=downgrade_info_redis_key,
        value=json.dumps(data_response),
        expire_time=DowngradeInfoRedisConst.REDIS_CACHE_TTL_DEFAULT_HOUR,
    )
    return data_response


def construct_data_response_downgrade_info_alert(
    customer: Customer,
    is_show: bool,
    last_downgrade_date: str,
    parameters: dict
) -> dict:
    if not is_show:
        return {'is_showed_downgrade_alert': False}

    account_limit = AccountLimit.objects.get(account_id=customer.account.pk)
    # Format bottom sheet content with current set limit
    bottom_sheet_content = parameters.get('bottom_sheet_content', '').format(
        set_limit=display_rupiah(account_limit.set_limit)
    )

    return {
        'is_showed_downgrade_alert': True,
        'last_downgrade_history_date': last_downgrade_date,
        'info_alert_title': parameters.get('info_alert_title', ''),
        'bottom_sheet_title': parameters.get('bottom_sheet_title', ''),
        'bottom_sheet_image_url': parameters.get('bottom_sheet_image_url'),
        'bottom_sheet_content': bottom_sheet_content,
        'how_to_revert_limit_content': parameters.get('how_to_revert_limit_content'),
        'additional_tip': parameters.get('additional_tip'),
    }


def invalidate_downgrade_info_alert_cache(account_id):
    account = Account.objects.get(pk=account_id)
    customer_id = account.customer.pk
    redis_client = get_redis_client()
    key = DowngradeInfoRedisConst.DOWNGRADE_INFO_ALERT.format(customer_id)
    redis_client.delete_key(key)
    execute_after_transaction_safely(
        lambda: send_pn_invalidate_caching_downgrade_alert.delay(customer_id)
    )
