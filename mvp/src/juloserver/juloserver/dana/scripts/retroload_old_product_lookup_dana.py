from datetime import timedelta

from bulk_update.helper import bulk_update
from django.db import connection
from django.utils import timezone

from juloserver.dana.constants import DanaProductType
from juloserver.dana.loan.services import (
    calculate_dana_yearly_interest_rate,
    create_product_lookup_for_dana,
)
from juloserver.dana.models import DanaLoanReference
from juloserver.julo.models import Application, ProductLookup
from juloserver.julo.product_lines import ProductLineCodes


def get_or_create_product_lookup(new_interest, product_line, late_fee_rate):
    """
    Fungsi ini akan mencari ProductLookup yang cocok, atau membuat yang baru jika tidak ditemukan.
    """
    product_lookup_map = {
        (pl.interest_rate, pl.product_line): pl for pl in ProductLookup.objects.all()
    }

    product_lookup = product_lookup_map.get((new_interest, product_line))

    if not product_lookup:
        # Jika tidak ditemukan, buat yang baru
        product_lookup = create_product_lookup_for_dana(
            float(new_interest),
            float(late_fee_rate),
            product_line,
        )
        print("New product_lookup has been created")

    print("product_lookup exists: ", product_lookup)
    return product_lookup


"""
from datetime import date, timedelta
start_date=date(2025,5,1)
max_end_date = date(2025,5,2)
bulk_update_dana_product_lookup(start_date, max_end_date)
"""


def bulk_update_dana_product_lookup(start_date, max_end_date, is_dana_cicil=True):
    end_date = start_date + timedelta(days=1)
    while end_date <= max_end_date:
        update_dana_product_lookup_with_new_interest_counting_formula_v2(
            start_date, end_date, is_dana_cicil
        )
        start_date += timedelta(days=1)
        end_date = start_date + timedelta(days=1)


def update_dana_product_lookup_with_new_interest_counting_formula_v2(
    start_date, end_date, is_dana_cicil, batch_size=1000
):
    if is_dana_cicil:
        product_line_code = ProductLineCodes.DANA
        monthly_interest_rate = 0.04
        lender_product_id = DanaProductType.CICIL
    else:
        product_line_code = ProductLineCodes.DANA_CASH_LOAN
        monthly_interest_rate = 0.0489
        lender_product_id = DanaProductType.CASH_LOAN

    loan_ids = list(get_loan_ids(product_line_code, monthly_interest_rate, start_date, end_date))
    if not loan_ids:
        print("No anomaly loans found anymore")
        return

    for i in range(0, len(loan_ids), batch_size):
        start = i
        end = i + batch_size
        loan_ids_batch = loan_ids[start:end]

        dana_loan_references = DanaLoanReference.objects.filter(
            loan__in=loan_ids_batch,
            trans_time__gte=start_date,
            trans_time__lt=end_date,
            lender_product_id=lender_product_id,
        ).select_related('loan__product')

        if not dana_loan_references.exists():
            print(
                "dana_loan_references not found in this time_range {} and {}".format(
                    start_date, end_date
                )
            )
            continue

        application_ids = set(dana_loan_references.values_list('application_id', flat=True))

        # Mapping application_id ke Application object
        application_map = {
            app.id: app for app in Application.objects.filter(pk__in=application_ids)
        }
        update_loans = []
        new_interest_map = {}
        new_interest_list = []

        for dlr in dana_loan_references.iterator():
            new_interest = calculate_dana_yearly_interest_rate(dlr)
            new_interest_map[dlr.id] = new_interest
            new_interest_list.append(new_interest)

        product_lookups = ProductLookup.objects.filter(
            interest_rate__in=new_interest_list, product_line_id=product_line_code
        )
        product_lookup_map = {}
        for product_lookup in product_lookups.iterator():
            product_lookup_map[product_lookup.interest_rate] = product_lookup

        for dlr in dana_loan_references.iterator():
            new_interest = new_interest_map.get(dlr.id)
            if not new_interest:
                continue

            old_interest = dlr.loan.product.interest_rate
            if old_interest != new_interest:
                application = application_map.get(dlr.application_id)
                if not application:
                    continue
                product_line = application.product_line

                product_lookup = product_lookup_map.get(new_interest)
                loan = dlr.loan
                if product_lookup:
                    # Update loan.product dengan product_lookup yang dipilih
                    loan.product = product_lookup
                    loan.udate = timezone.localtime(timezone.now())
                    update_loans.append(loan)
                else:
                    product_lookup = get_or_create_product_lookup(
                        new_interest, product_line, dlr.late_fee_rate
                    )
                    loan.product = product_lookup
                    loan.udate = timezone.localtime(timezone.now())
                    update_loans.append(loan)

        bulk_update(update_loans, update_fields=['udate', 'product_id'], batch_size=batch_size)

        print("Success update loan product")


def get_loan_ids(product_line_code, monthly_interest_rate, start_date, end_date):
    with connection.cursor() as cursor:
        cursor.execute(
            """
                select
                    dlr.loan_id
                from ops.dana_loan_reference dlr
                    join ops.loan l on l.loan_id = dlr.loan_id
                    join ops.product_lookup pl on pl.product_code = l.product_code
                    where
                        dlr.trans_time >=  %s
                        and dlr.trans_time < %s
                        AND pl.interest_rate / 12 <> %s
                        and pl.product_line_code = %s
            """,
            [start_date, end_date, monthly_interest_rate, product_line_code],
        )

        rows = cursor.fetchall()

    loan_ids = [row[0] for row in rows]
    return loan_ids
