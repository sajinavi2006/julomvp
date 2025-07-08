import pickle

from django.db import connection
from django.db.models import Prefetch, Q, Sum
from juloserver.grab.models import GrabLoanData
from django.utils import timezone
from juloserver.julo.constants import AddressPostalCodeConst, FeatureNameConst
from juloserver.julo.models import Payment, FeatureSetting
from juloserver.streamlined_communication.constant import CardProperty
from juloserver.grab.constants import GrabRobocallConstant
from juloserver.grab.models import GrabIntelixCScore
from juloserver.streamlined_communication.models import StreamlinedCommunication
from juloserver.julo.services2 import get_redis_client



def get_payments_from_grab_robocall(
        streamlined_dpd, attempt_hour, attempt, product_lines, is_retry=False):
    """
        This function gets all the relevant payment_ids based on DPD,
        Then it returns the AccountPayments for those Payments which are selected.
        We use a raw query since using prefetch related and select related can
        be very expensive
    """
    redis_client = get_redis_client()
    raw_undecoded_data = redis_client.get(GrabRobocallConstant.REDIS_KEY_FOR_ROBOCALL, decode=False)
    rows = None
    if raw_undecoded_data:
        rows = pickle.loads(raw_undecoded_data)
    else:
        custom_sql_query = """
            WITH cte AS
                (
                    SELECT p.loan_id, p.payment_id, ROW_NUMBER() OVER (PARTITION BY p.loan_id ORDER BY 
                    p.due_date asc) AS rn from ops.loan l join ops.payment p on p.loan_id = l.loan_id 
                    join ops.account a on a.account_id = l.account_id
                    join ops.account_lookup al  on al.account_lookup_id = a.account_lookup_id 
                    join ops.workflow w on w.workflow_id = al.workflow_id
                    where l.loan_purpose = 'Grab_loan_creation' and l.loan_status_code >= 220 
                    and l.loan_status_code < 250 and p.payment_status_code < 330 
                    and p.is_restructured = false and w.name = 'GrabWorkflow'
                    group by p.loan_id, p.payment_id order by p.due_date asc
                )
            SELECT *
            FROM cte
            WHERE rn = 1
        """
        # SQL to get the oldest unpaid payment and loan ID for all grab loans(active)
        with connection.cursor() as cursor:
            cursor.execute(custom_sql_query)
            rows = cursor.fetchall()
    total_number_of_loans = len(rows) if rows else 0
    robocall_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_ROBOCALL_SETTING,
        is_active=True
    )
    if robocall_feature_setting:
        default_batch_values = int(robocall_feature_setting.parameters.get('robocall_batch_size',
                                                                           GrabRobocallConstant.ROBOCALL_BATCH_SIZE))
    else:
        robocall_active = Payment.objects.none()
        return robocall_active

    all_postal_code = AddressPostalCodeConst.WIB_POSTALCODE \
        + AddressPostalCodeConst.WITA_POSTALCODE + AddressPostalCodeConst.WIT_POSTALCODE
    set_of_payments_at_dpd = set()
    for iterator in list(range(0, total_number_of_loans, default_batch_values)):
        batch_payments = set()
        for loan_id, payment_id, _ in rows[
            iterator: iterator + default_batch_values
        ]:
            batch_payments.add(payment_id)
        grab_loan_data_set = GrabLoanData.objects.only(
            'id', 'loan_id', 'account_halt_status', 'account_halt_info'
        )
        prefetch_grab_loan_data = Prefetch('loan__grabloandata_set', to_attr='grab_loan_data_set',
                                           queryset=grab_loan_data_set)
        prefetch_join_tables = [
            prefetch_grab_loan_data
        ]
        payments = Payment.objects.select_related('loan').prefetch_related(
            *prefetch_join_tables).filter(id__in=batch_payments)
        for payment in payments:
            if payment.get_grab_dpd == int(streamlined_dpd):
                set_of_payments_at_dpd.add(payment.id)

    dpd_filtered_payments = Payment.objects.normal().filter(id__in=set_of_payments_at_dpd)

    hour = timezone.localtime(timezone.now()).hour
    if hour == attempt_hour and attempt == 0:
        robocall_active = dpd_filtered_payments.filter(
            account_payment__is_robocall_active=True,
            account_payment__account__application__address_kodepos__in=AddressPostalCodeConst.WIT_POSTALCODE,
            account_payment__account__application__product_line__product_line_code__in=product_lines
        )
    elif hour == attempt_hour and attempt == 1:
        robocall_active = dpd_filtered_payments.filter(
            account_payment__is_robocall_active=True,
            account_payment__account__application__address_kodepos__in=AddressPostalCodeConst.WITA_POSTALCODE,
            account_payment__account__application__product_line__product_line_code__in=product_lines
        )
    elif hour == attempt_hour and attempt == 2:
        robocall_active = dpd_filtered_payments.filter(
            Q(account_payment__is_robocall_active=True) & (
                Q(account_payment__account__application__address_kodepos__in=AddressPostalCodeConst.WIB_POSTALCODE) |
                Q(account_payment__account__application__address_kodepos=None) | ~Q(
                    account_payment__account__application__address_kodepos__in=all_postal_code)),
            account_payment__account__application__product_line__product_line_code__in=product_lines)
    else:
        robocall_active = dpd_filtered_payments.none()

    if is_retry:
        robocall_active = robocall_active.exclude(
            Q(account_payment__is_success_robocall=True) | Q(
                account_payment__is_collection_called=True)
        )
    return robocall_active


def filter_payments_based_on_c_score(payments_qs, streamlined_communication):
    """
        This is a Grab only function.
        This function is for filtering out the payment_qs based on the
        intelix_c_score which we receive from grab side.
    """
    extra_condition = streamlined_communication.extra_conditions
    if extra_condition == CardProperty.GRAB_ROBOCALL_HIGH_C_SCORE:
        payments_qs = payments_qs.filter(loan__loan_xid__in=(
            GrabIntelixCScore.objects.filter(
                cscore__range=GrabRobocallConstant.HIGH_C_SCORE_RANGE
            ).values_list('loan_xid', flat=True)))
    elif extra_condition == CardProperty.GRAB_ROBOCALL_MEDIUM_C_SCORE:
        payments_qs = payments_qs.filter(loan__loan_xid__in=(
            GrabIntelixCScore.objects.filter(
                cscore__range=GrabRobocallConstant.MEDIUM_C_SCORE_RANGE
            ).values_list('loan_xid', flat=True)))
    elif extra_condition == CardProperty.GRAB_ROBOCALL_LOW_C_SCORE:
        payments_qs = payments_qs.filter(loan__loan_xid__in=(
            GrabIntelixCScore.objects.filter(
                cscore__range=GrabRobocallConstant.LOW_C_SCORE_RANGE
            ).values_list('loan_xid', flat=True)))
    else:
        payments_qs = payments_qs.exclude(loan__loan_xid__in=(
            GrabIntelixCScore.objects.filter(
                cscore__isnull=False
            ).values_list('loan_xid', flat=True)))

    return payments_qs


def filter_based_on_feature_setting_robocall(payments_qs, streamlined_communication):
    robocall_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GRAB_ROBOCALL_SETTING,
        is_active=True
    ).last()
    """    
    This Feature setting is for getting the outstanding amount value
    Sample Parameter value:
    parameter = {
        'default': {'outstanding_amount': 5000000},
        'template_1': {'outstanding_amount': 10000},
        'template_2': {'outstanding_amount': 30000},
        'robocall_batch_size': 1000
    }
    """
    fs_outstanding_amount = 0
    if robocall_feature_setting:
        if isinstance(streamlined_communication, StreamlinedCommunication):
            template_code = streamlined_communication.template_code
            default_values = robocall_feature_setting.parameters.get(
                template_code, {'outstanding_amount': 0}
            )
            fs_outstanding_amount = int(default_values.get('outstanding_amount'))
        else:
            default_values = robocall_feature_setting.parameter.get(
                'default', {'outstanding_amount': 0}
            )
            fs_outstanding_amount = int(default_values.get('outstanding_amount'))

    if fs_outstanding_amount > 0:
        # Only need to check if the feature setting outstanding amount is greater than 0
        loan_ids = set(payments_qs.values_list('loan_id', flat=True))
        filtered_loan_ids = Payment.objects.filter(
            loan_id__in=loan_ids).not_paid_active().annotate(
            sum_unpaid_due_amount=Sum('due_amount')).filter(
            sum_unpaid_due_amount__gt=fs_outstanding_amount
        ).values_list('loan_id', flat=True)
        payments_qs = payments_qs.filter(loan_id__in=filtered_loan_ids)
    return payments_qs
