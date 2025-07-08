from datetime import timedelta

from django.db.models import (
    ExpressionWrapper,
    F,
    IntegerField,
)
from django.utils import timezone

from juloserver.account_payment.models import AccountPayment
from juloserver.apiv2.models import (
    PdCollectionModelResultExclude,
    PdCollectionModelResult,
)
from juloserver.julo.statuses import PaymentStatusCodes


def determine_segment_for_collection_tailor(
        dpd: int, range_from_due_filter: int, oldest_account_payment_ids: list,
        filter_sort_method_objects):
    data_for_send_pn = []
    today_date = timezone.localtime(timezone.now()).date()
    due_date_filter = today_date - timedelta(days=dpd)
    account_payment_base_on_dpd = AccountPayment.objects.filter(
        id__in=oldest_account_payment_ids, due_date=due_date_filter
    ).exclude(status__in=PaymentStatusCodes.paid_status_codes())
    account_payment_ids_base_on_dpd = list(account_payment_base_on_dpd.values_list('pk', flat=True))
    # this feature use model version Now Or Never and is risky customer
    collection_model_payment_and_account_payments = PdCollectionModelResult.objects.filter(
        filter_sort_method_objects
    ).filter(
        range_from_due_date=range_from_due_filter,
        account_payment__isnull=False,
        account_payment_id__in=account_payment_ids_base_on_dpd,
        account_payment__account__application__partner__isnull=True,
        sort_method__isnull=False
    ).annotate(
        dpd=ExpressionWrapper(
            today_date - F('account_payment__due_date'),
            output_field=IntegerField())
    ).filter(dpd=dpd).extra(
        select={'segment': "SUBSTRING(sort_method, 9)", 'send_as_dpd': dpd}
    ).values('account_payment', 'segment', 'send_as_dpd').order_by('sort_rank')
    experiment_data = collection_model_payment_and_account_payments.extra(
        where=["SUBSTRING(sort_method, 9) != ''"]
    ).values(
        'account_payment', 'segment', 'send_as_dpd').order_by('sort_rank')
    experiment_data_account_payment_ids = list(
        experiment_data.values_list('account_payment_id', flat=True))
    data_for_send_pn.extend(list(experiment_data))
    # not risky customer
    high_risk_collection_model_data = PdCollectionModelResultExclude.objects.filter(
        filter_sort_method_objects
    ).filter(
        range_from_due_date=range_from_due_filter,
        account_payment__isnull=False,
        account_payment_id__in=account_payment_ids_base_on_dpd,
        account_payment__account__application__partner__isnull=True,
        sort_method__isnull=False
    ).exclude(account_payment_id__in=experiment_data_account_payment_ids).annotate(
        dpd=ExpressionWrapper(
            today_date - F('account_payment__due_date'),
            output_field=IntegerField())
    ).filter(dpd=dpd).extra(
        select={'segment': "SUBSTRING(sort_method, 9)", 'send_as_dpd': dpd}
    ).values('account_payment', 'segment', 'send_as_dpd').order_by('sort_rank')
    high_risk_collection_model_experiment_data = high_risk_collection_model_data.extra(
        where=["SUBSTRING(sort_method, 9) != ''"]
    ).values(
        'account_payment', 'segment', 'send_as_dpd').order_by('sort_rank')

    high_risk_collection_model_account_payment_ids = \
        list(high_risk_collection_model_experiment_data.values_list(
            'account_payment', flat=True))
    data_for_send_pn.extend(list(high_risk_collection_model_experiment_data))

    account_payments_ids_exists_in_ana = experiment_data_account_payment_ids + \
        high_risk_collection_model_account_payment_ids
    account_payment_base_on_dpd = account_payment_base_on_dpd.exclude(
        id__in=account_payments_ids_exists_in_ana)
    # prevent using when on query because there's posibility stuck if data is big
    for account_payment in account_payment_base_on_dpd.iterator():

        if account_payment.due_amount >= 500000:
            collection_segment = 'bull'
        else:
            collection_segment = 'scorpio'
        data_for_send_pn.append(
            dict(account_payment=account_payment.id, send_as_dpd=dpd, segment=collection_segment)
        )

    return data_for_send_pn


def construct_experiment_data_for_email_and_robocall_collection_tailor_experiment(
    account_payment_ids, filter_account_id_objects, filter_sort_method_objects,
    range_from_due_filter, dpd, exclude=True):
    table = PdCollectionModelResultExclude
    if not exclude:
        table = PdCollectionModelResult

    today_date = timezone.localtime(timezone.now()).date()
    # experiment group data from ana table
    experiment_from_ana_schema = table.objects.filter(
        range_from_due_date=range_from_due_filter,
        account_payment__isnull=False,
        account__isnull=False,
        account_payment_id__in=account_payment_ids,
        sort_method__isnull=False,
    ).filter(
        filter_account_id_objects
    ).filter(
        filter_sort_method_objects
    ).annotate(
        dpd=ExpressionWrapper(
            today_date - F('account_payment__due_date'),
            output_field=IntegerField())
    ).filter(dpd=dpd).extra(
        select={'segment': "SUBSTRING(sort_method, 9)", 'send_as_dpd': dpd}
    ).values('account_payment', 'segment', 'send_as_dpd').order_by('sort_rank')
    # filter if data have NULL segment
    experiment_from_ana_schema_data = experiment_from_ana_schema.extra(
        where=["SUBSTRING(sort_method, 9) != ''"]
    ).values(
        'account_payment', 'segment', 'send_as_dpd').order_by('sort_rank')

    return experiment_from_ana_schema_data
