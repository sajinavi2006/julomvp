from datetime import timedelta
from itertools import chain

from django.db.models import Max
from django.utils import timezone
from juloserver.account.models import (
    AccountLimit, AccountProperty, Account, AccountStatusHistory
)
from juloserver.account_payment.models import AccountPayment
from juloserver.cfs.services.core_services import get_customer_tier_info
from juloserver.graduation.models import CustomerSuspend
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.models import (
    FeatureSetting,
    Application,
    Loan,
    SkiptraceHistory,
    Agent,
    SkiptraceResultChoice,
    Skiptrace,
    VoiceCallRecord,
    CootekRobocall,
    ApplicationHistory,
    Payment,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes, PaymentStatusCodes
from juloserver.loan.services.loan_related import is_product_locked
from juloserver.payment_point.models import TransactionMethod
from juloserver.sales_ops.models import SalesOpsAccountSegmentHistory, SalesOpsRMScoring
from juloserver.sales_ops.services import sales_ops_services


def get_sales_ops_setting(name=None, default=None):
    setting = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.SALES_OPS)

    if setting is None:
        return default
    if name is None:
        return setting.parameters

    return setting.parameters.get(name, default)


def _latest_account_mapping_dict(qs):
    qs = qs.distinct('account_id').order_by('account_id', '-cdate')
    model_list = qs.values_list('account_id', 'id')
    return {account_id: model_id for account_id, model_id in model_list}


def get_latest_account_limit(account_id):
    return AccountLimit.objects.filter(account_id=account_id).last()


def get_bulk_latest_account_limit_id_dict(account_ids):
    qs = AccountLimit.objects.filter(account_id__in=account_ids)
    return _latest_account_mapping_dict(qs)


def get_latest_account_property(account_id):
    return AccountProperty.objects.filter(account_id=account_id).last()


def get_bulk_latest_account_property_id_dict(account_ids):
    qs = AccountProperty.objects.filter(account_id__in=account_ids)
    return _latest_account_mapping_dict(qs)


def get_latest_disbursed_loan(account_id):
    return Loan.objects.get_queryset().disbursed().filter(account_id=account_id).last()


def get_bulk_latest_disbursed_loan_id_dict(account_ids):
    qs = Loan.objects.get_queryset().disbursed().filter(account_id__in=account_ids)
    return _latest_account_mapping_dict(qs)


def get_latest_application(account_id):
    return Application.objects.filter(
        account_id=account_id, application_status_id=ApplicationStatusCodes.LOC_APPROVED
    ).last()


def get_bulk_latest_application_id_dict(account_ids):
    qs = Application.objects.filter(
        account_id__in=account_ids,
        application_status_id=ApplicationStatusCodes.LOC_APPROVED
    )
    return _latest_account_mapping_dict(qs)


def get_account_status_code_history_list(account_id):
    statuses_list = AccountStatusHistory.objects.filter(account_id=account_id)\
        .values_list('status_new_id', 'status_old_id')

    all_status_set = set()
    for status_list in statuses_list:
        all_status_set.update(status_list)

    return list(all_status_set)


def get_product_locked_info_dict(account_id):
    all_transaction_codes = get_transaction_method_choices()
    account = Account.objects.get_or_none(id=account_id)
    if account is None:
        return {}
    return {
        transaction_code: is_product_locked(account, transaction_code)
        for transaction_code, _ in all_transaction_codes
    }


def get_transaction_method_choices():
    transaction_methods = TransactionMethod.objects.order_by('order_number')
    return (
        (transaction_method.id, transaction_method.fe_display_name)
        for transaction_method in transaction_methods
    )


def get_cfs_tier_info(account_id):
    application = get_latest_application(account_id)
    if application is None:
        return None, None

    j_score, cfs_tier = get_customer_tier_info(application)
    return j_score, cfs_tier


def get_loan_history(account_id):
    return Loan.objects.get_queryset().all_active_julo_one().filter(account_id=account_id)\
        .order_by('-fund_transfer_ts').select_related('transaction_method').all()


def get_skiptrace_list(customer_id):
    return Skiptrace.objects.filter(customer_id=customer_id).order_by('-id')[:10]


def get_skiptrace_histories(account_id):
    return SkiptraceHistory.objects.select_related('skiptrace', 'call_result').filter(
        account_id=account_id
    ).extra(
        select={'cdate_timestamp': "CAST(skiptrace_history.cdate AS TIMESTAMP)"}
    ).order_by('-cdate_timestamp').all()


def is_julo1_account(account):
    return Application.objects.filter(
            account_id=account.id,
            product_line_id__in=ProductLineCodes.julo_one(),
            workflow__name=WorkflowConst.JULO_ONE,
            partner__isnull=True,
    ).exists()


def filter_suspended_users(account_ids):
    account_customer_queryset = Account.objects.filter(id__in=account_ids).values('id', 'customer_id')
    account_customer_mappings = {account['customer_id']: account['id'] for account in account_customer_queryset}

    customer_suspend_ids =  set(
        CustomerSuspend.objects.filter(
            customer_id__in=account_customer_mappings.keys(),
            is_suspend=True,
        ).values_list('customer_id', flat=True)
    )
    invalid_account_ids = {
        account_customer_mappings[customer_id] for customer_id in account_customer_mappings
        if customer_id in customer_suspend_ids
    }
    return invalid_account_ids


def filter_invalid_account_ids_application_restriction(account_ids, lineup_min_available_days):
    today = timezone.localtime(timezone.now())
    application_histories = ApplicationHistory.objects.filter(
        application__account_id__in=account_ids, status_new=ApplicationStatusCodes.LOC_APPROVED
    ).values('application__account_id', 'cdate')
    invalid_account_ids = {
        application_history['application__account_id']
        for application_history in application_histories
        if (today - timezone.localtime(application_history['cdate'])).days < lineup_min_available_days
    }
    return invalid_account_ids


def filter_invalid_account_limit_restriction(account_ids, lineup_max_used_limit_percentage):
    account_limits = AccountLimit.objects.filter(
        account_id__in=account_ids,
    ).values('used_limit', 'set_limit', 'account_id')

    invalid_account_ids = set()
    for account_limit in account_limits:
        if account_limit['used_limit'] > \
                (account_limit['set_limit'] * lineup_max_used_limit_percentage):
            invalid_account_ids.add(account_limit['account_id'])
    return invalid_account_ids


def filter_invalid_account_ids_collection_restriction(account_ids, due_date_delta_days):
    """
    Card: https://juloprojects.atlassian.net/browse/CLS3-299
    - Exclude user from sales ops lineup start from dpd-5.
    """
    today = timezone.localtime(timezone.now()).date()

    # check if there is installment based on due_date_delta_days
    filter_dpd_date = today + due_date_delta_days
    invalid_account_ids = AccountPayment.objects.not_paid_active()\
        .filter(account_id__in=account_ids, due_date__lte=filter_dpd_date)\
        .values_list('account_id', flat=True)

    return set(invalid_account_ids)


def filter_invalid_account_ids_paid_collection_restriction(account_ids, expired_delta_time):
    """
    Card: https://juloprojects.atlassian.net/browse/CLS3-299
    - Those customers (collection call) will be back to the lineup the day
    after they repaid the installment
    """
    today = timezone.localtime(timezone.now()).date()
    paid_account_payments = AccountPayment.objects.get_last_paid_by_account(account_ids)
    account_id_map = {ap.id: ap.account_id for ap in paid_account_payments}

    valid_account_payment_ids = {
        paid_account_payment.pk
        for paid_account_payment in paid_account_payments
        if (
            not paid_account_payment.paid_date
            or paid_account_payment.paid_date + expired_delta_time <= today
        )
    }

    paid_account_payment_ids = list(account_id_map.keys() - valid_account_payment_ids)
    nexmo_calls = VoiceCallRecord.objects.get_last_account_payment_calls(paid_account_payment_ids)
    cootek_calls = CootekRobocall.objects.get_last_account_payment_calls(paid_account_payment_ids)
    skiptrace_calls = SkiptraceHistory.objects.get_last_collection_account_payment_calls(
        paid_account_payment_ids
    )

    return {
        account_id_map[collection_call.account_payment_id]
        for collection_call in chain(nexmo_calls, cootek_calls, skiptrace_calls)
    }


def filter_invalid_account_ids_loan_restriction(account_ids, min_available_days):
    """
        - Those customers will be back to the lineup the day after they have at least
        7 days paid date https://juloprojects.atlassian.net/browse/UTIL-1247
        params: min_available_days that mean x days account id can back to sales ops list
    """

    today = timezone.localtime(timezone.now())
    invalid_account_ids = Account.objects.filter(
        id__in=account_ids,
    )\
        .annotate(max_paid_date=Max('loan__payment__paid_date'))\
        .filter(
            max_paid_date__gt=(today - timedelta(days=min_available_days)).date()
        ).values_list('id', flat=True)

    return set(invalid_account_ids)


def filter_invalid_account_ids_disbursement_date_restriction(account_ids, min_available_days):
    """
        - Those customers will be back to the lineup the day after they have at least
        14 days after doing disbursement
        params: min_available_days that mean x days account id can back to sales ops list
    """

    today = timezone.localtime(timezone.now())
    invalid_account_ids = Account.objects.filter(
        id__in=account_ids,
        loan__fund_transfer_ts__gt=(today - timedelta(days=min_available_days)).date()
    ).values_list('id', flat=True)

    return set(invalid_account_ids)


def get_agent(user_id):
    return Agent.objects.get_or_none(user_id=user_id)


def sorting_application_skiptrace_phone(x):
    return (
        not x.contact_source.startswith('sales_ops'),
        x.contact_source != 'mobile_phone_1',
        -(x.effectiveness or 0),
    )


def get_application_skiptrace_phone(application):
    phones = Skiptrace.objects.filter(
        customer_id=application.customer_id, contact_source__isnull=False
    )
    valid_phones = []
    for phone in phones:
        contact_source = phone.contact_source
        if contact_source.startswith('sales_ops') or \
                contact_source in ('mobile_phone_1', 'mobile_phone_2'):
            valid_phones.append(phone)

    result = []
    if phones:
        for skiptrace in sorted(valid_phones, key=lambda x: sorting_application_skiptrace_phone(x)):
            phone_obj = {
                'skiptrace_id': skiptrace.pk,
                'contact_name': skiptrace.contact_name,
                'contact_source': skiptrace.contact_source,
                'phone_number': str(skiptrace.phone_number),
                'effectiveness': skiptrace.effectiveness,
            }
            result.append(phone_obj)

    return result


def get_skiptrace_result_choice(call_result):
    return SkiptraceResultChoice.objects.get_or_none(id=call_result)


def get_last_collection_nexmo_calls(account_id):
    return VoiceCallRecord.objects.get_last_account_calls_with_event_type(account_id)


def get_last_collection_cootek_calls(account_id):
    return [CootekRobocall.objects.get_last_account_call(account_id)]


def get_last_collection_skiptrace_calls(account_id, is_intelix=False):
    if is_intelix:
        return SkiptraceHistory.objects.get_last_collection_account_calls(account_id, is_crm=False)

    return SkiptraceHistory.objects.get_last_collection_account_calls(account_id, is_crm=True)


def get_promo_code_agent_offer(agent_assignment):
    lineup = agent_assignment.lineup
    application = lineup.latest_application
    account_segment_history = SalesOpsAccountSegmentHistory.objects.filter(
        account_id=application.account_id
    ).last()
    r_score = SalesOpsRMScoring.objects.get(id=account_segment_history.r_score_id).score
    promotion = sales_ops_services.get_promotion_mapping_by_agent(agent_assignment.agent_id)
    if not promotion:
        return None

    is_valid = sales_ops_services.validate_promo_code_by_r_score(promotion, r_score)
    if not is_valid:
        return None
    return promotion
