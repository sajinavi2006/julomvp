from bulk_update.helper import bulk_update
from juloserver.julo.models import Loan
from juloserver.followthemoney.models import LenderCurrent
from juloserver.partnership.constants import PartnershipLender


def update_dana_lender_jtp_to_jtp_iaf(start_date, end_date, batch_size: int = 100):
    loans_to_update = []
    total_success = 0
    total_skipped = 0
    total_failed = 0
    print("Fetching data..")
    print("-" * 20)
    lender_jtp = LenderCurrent.objects.filter(lender_name=PartnershipLender.JTP).first()
    loans = Loan.objects.select_related('danaloanreference').filter(
        danaloanreference__trans_time__range=(start_date, end_date),
        lender=lender_jtp,
    )
    print("Fetched {} data.".format(len(loans)))
    if not loans:
        print("NO DATA TO UPDATE")

    lender_iaf_jtp = LenderCurrent.objects.filter(lender_name=PartnershipLender.IAF_JTP).first()
    for loan in loans.iterator():
        loan.lender = lender_iaf_jtp
        loans_to_update.append(loan)

        if len(loans_to_update) == batch_size:
            try:
                bulk_update(
                    loans_to_update,
                    update_fields=['lender'],
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
                update_fields=['lender'],
            )
            total_success += len(loans_to_update)

    except Exception as e:
        total_failed += len(loans_to_update)
        print("ERR Exception bulk_update - {}".format(e))

    print("-" * 20)
    print("SUCCESS: {}".format(total_success))
    print("SKIPPED: {}".format(total_skipped))
    print("FAILED: {}".format(total_failed))

    return
