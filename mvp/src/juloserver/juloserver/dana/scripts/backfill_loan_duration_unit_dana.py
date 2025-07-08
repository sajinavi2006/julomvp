from bulk_update.helper import bulk_update
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.models import (
    Loan,
    LoanDurationUnit,
)
from juloserver.dana.constants import MAP_PAYMENT_FREQUENCY_TO_UNIT


def retroload_loan_duration_unit_dana(start_date, end_date, batch_size: int = 100):
    loans_to_update = []
    total_success = 0
    total_skipped = 0
    total_failed = 0
    empty_plr = []
    total_failed = 0
    print("Fetching data..")
    print("-" * 20)
    loans = (
        Loan.objects.select_related('product')
        .filter(
            cdate__range=(start_date, end_date),
            product__product_line__in=(
                ProductLineCodes.DANA,
                ProductLineCodes.DANA_CASH_LOAN,
            ),
        )
        .exclude(
            loan_status_id__in=(
                LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                LoanStatusCodes.LENDER_REJECT,
            )
        )
    )
    print("Fetched {} data.".format(len(loans)))
    if not loans:
        print("NO DATA TO UPDATE")

    for loan in loans.iterator():
        plr = loan.partnerloanrequest_set.last()
        if not plr:
            total_skipped += 1
            empty_plr.append(loan.id)
            continue

        if not plr.loan_duration_type:
            payment_frequency = 'monthly'
            duration_unit = 'month'
            if loan.product.product_line_id == ProductLineCodes.DANA:
                payment_frequency = 'biweekly'
                duration_unit = 'biweek'
        else:
            payment_frequency = plr.loan_duration_type.lower()
            if payment_frequency == 'month':
                payment_frequency = 'monthly'
            duration_unit = MAP_PAYMENT_FREQUENCY_TO_UNIT.get(payment_frequency)

        loan_duration_unit_id = None
        if duration_unit and payment_frequency:
            loan_duration_unit_id = (
                LoanDurationUnit.objects.filter(
                    duration_unit=duration_unit, payment_frequency=payment_frequency
                )
                .values_list('id', flat=True)
                .first()
            )
            if not loan_duration_unit_id:
                loan_duration_unit = LoanDurationUnit.objects.create(
                    duration_unit=duration_unit,
                    payment_frequency=payment_frequency,
                    description="duration is in {} and paid {}".format(
                        duration_unit, payment_frequency
                    ),
                )
                loan_duration_unit_id = loan_duration_unit.id

        if not loan_duration_unit_id:
            total_skipped += 1
            print(
                "SKIPPED loan_id[{}] - loan_duration_unit_id not found\
                (duration_unit:{}, payment_frequency:{})".format(
                    loan.id, duration_unit, payment_frequency
                )
            )
            continue

        loan.loan_duration_unit_id = loan_duration_unit_id
        loans_to_update.append(loan)

        if len(loans_to_update) == batch_size:
            try:
                bulk_update(
                    loans_to_update,
                    update_fields=['loan_duration_unit'],
                )
                loans_to_update = []
                total_success += batch_size
            except Exception as e:
                total_failed += batch_size
                print("ERR Exception bulk_update per batch - {}".format(e))

    try:
        if len(loans_to_update) > 0:
            bulk_update(
                loans_to_update,
                update_fields=['loan_duration_unit'],
            )
            total_success += len(loans_to_update)

    except Exception as e:
        total_skipped += len(loans_to_update)
        print("ERR Exception bulk_update - {}".format(e))

    print("-" * 20)
    print("SUCCESS: {}".format(total_success))
    print("SKIPPED: {}".format(total_skipped))
    print("FAILED: {}".format(total_failed))
    print("Empty partner_loan_request - loan_ids: {}".format(empty_plr))

    return
