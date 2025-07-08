from datetime import (
    timedelta,
    datetime)
from django.utils import timezone
from django.db.models import (
    ExpressionWrapper,
    IntegerField,
    F)

from juloserver.julo.constants import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.models import Payment

from ..constants import RamadanCampaign


def get_oldest_payments():
    return Payment.objects.filter(
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME
    ).order_by('loan', 'id').distinct('loan').values_list('id', flat=True)


def get_customer_data_from_dpd(dpd, excluded_payment_ids=[]):
    today = timezone.localtime(timezone.now()).date()
    eligible_product_codes = ProductLineCodes.mtl() + \
        ProductLineCodes.laku6() + ProductLineCodes.pedemtl()

    if dpd is None:
        initiative3_start_date = (datetime.strptime(
            RamadanCampaign.EMAIL1_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        oldest_payments = get_oldest_payments()

        return Payment.objects.annotate(
            dpd=ExpressionWrapper(
                initiative3_start_date - F('due_date'),
                output_field=IntegerField()))\
            .filter(
                loan__application__product_line_id__in=eligible_product_codes,
                loan__loan_status_id__gte=LoanStatusCodes.LOAN_1DPD,
                loan__loan_status_id__lte=LoanStatusCodes.LOAN_90DPD,
                payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
                due_date__lte=initiative3_start_date,
                id__in=oldest_payments)\
            .exclude(
                loan__application__is_fdc_risky=True)\
            .exclude(id__in=excluded_payment_ids)\
            .values_list('id', flat=True)

    targeted_due_date = today + timedelta(days=dpd)

    return Payment.objects.filter(
        due_date=targeted_due_date,
        loan__application__product_line_id__in=eligible_product_codes,
        loan__loan_status_id=LoanStatusCodes.CURRENT
    ).exclude(loan__application__is_fdc_risky=True).values_list('id', flat=True)


def get_gcm_ids_from_dpd(dpd, excluded_payment_ids=[]):
    today = timezone.localtime(timezone.now()).date()
    eligible_product_codes = ProductLineCodes.mtl()

    if dpd is None:
        initiative3_start_date = (datetime.strptime(
            RamadanCampaign.EMAIL1_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        oldest_payments = get_oldest_payments()

        return Payment.objects.annotate(
            dpd=ExpressionWrapper(
                initiative3_start_date - F('due_date'),
                output_field=IntegerField()))\
            .filter(
            dpd__lte=100,
            loan__application__product_line_id__in=eligible_product_codes,
            loan__loan_status_id__gte=LoanStatusCodes.LOAN_1DPD,
            loan__loan_status_id__lte=LoanStatusCodes.LOAN_90DPD,
            due_date__lte=initiative3_start_date,
            id__in=oldest_payments)\
            .exclude(
                loan__application__is_fdc_risky=True)\
            .exclude(id__in=excluded_payment_ids)\
            .values_list('loan__application__device__gcm_reg_id', flat=True)

    t_minus = today + timedelta(days=dpd)

    return Payment.objects.filter(
        due_date=t_minus,
        loan__application__product_line_id__in=eligible_product_codes,
        loan__loan_status_id=LoanStatusCodes.CURRENT
    ).exclude(loan__application__is_fdc_risky=True).values_list(
        'loan__application__device__gcm_reg_id', flat=True)
