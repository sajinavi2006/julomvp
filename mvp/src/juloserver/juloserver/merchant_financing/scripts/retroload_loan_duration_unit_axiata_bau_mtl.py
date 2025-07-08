import math
from bulk_update.helper import bulk_update
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.models import Loan
from juloserver.sdk.models import AxiataCustomerData
from juloserver.partnership.utils import get_loan_duration_unit_id
from juloserver.partnership.constants import LOAN_DURATION_UNIT_DAY


def retroload_loan_duration_unit_axiata_bau_mtl(start_date, end_date, batch_size: int = 100):
    mapping_acd_loan_duration_unit = {
        "daily": "day",
        "days": "day",
        "weeks": "week",
        "week": "week",
        "minggu": "week",
        "month": "month",
        "months": "month",
        "monthly": "month",
    }
    loans_to_update = []
    print("Fetching data..")
    loans = (
        Loan.objects.select_related('product')
        .filter(
            cdate__range=(start_date, end_date),
            product__product_line__in=(
                ProductLineCodes.AXIATA_WEB,
                ProductLineCodes.AXIATA1,
                ProductLineCodes.AXIATA2,
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
        print("END")

    for loan in loans.iterator():
        duration_unit = LOAN_DURATION_UNIT_DAY
        if loan.product.product_line_id != ProductLineCodes.AXIATA_WEB:
            acd = AxiataCustomerData.objects.filter(application=loan.get_application).first()
            if not acd:
                print("SKIPPED loan_id[{}] - axiata_customer_data not found".format(loan.id))
                continue

            financing_tenure = acd.loan_duration
            if acd.monthly_installment > 0:
                installment_number = math.ceil(acd.loan_amount / acd.monthly_installment)
            else:
                print("SKIPPED loan_id[{}] - zero monthly_installment".format(loan.id))
                continue

            duration_unit = mapping_acd_loan_duration_unit.get(acd.loan_duration_unit.lower())
            if not duration_unit:
                print(
                    "SKIPPED loan_id[{}] - invalid acd_loan_duration_unit {}".format(loan.id, acd)
                )
                continue
        else:
            plr = loan.partnerloanrequest_set.last()
            financing_tenure = plr.financing_tenure
            installment_number = plr.installment_number

        loan_duration_unit_id, err = get_loan_duration_unit_id(
            duration_unit, financing_tenure, installment_number
        )
        if err:
            print(
                "SKIPPED loan_id[{}] - get_loan_duration_unit_id - {} (duration_unit:{}, financing_tenure:{}, installment_number:{})".format(
                    loan.id, err, duration_unit, financing_tenure, installment_number
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
                print("UPDATED {} Loans".format(batch_size))
            except Exception as e:
                print("ERR Exception bulk_update per batch - {}".format(e))

    try:
        if len(loans_to_update) > 0:
            bulk_update(
                loans_to_update,
                update_fields=['loan_duration_unit'],
            )
            print("UPDATED {} Loans".format(len(loans_to_update)))

    except Exception as e:
        print("ERR Exception bulk_update - {}".format(e))

    print("END")
    return
