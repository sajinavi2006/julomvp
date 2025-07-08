from datetime import date
from django.db import transaction
from typing import List, Dict

from juloserver.julo.models import Payment


@transaction.atomic
def backfill_mismatch_loan_amount(
    dana_customer_data_ids: List,
    target_loan_end_created_date: date,
    target_loan_start_created_date: date = None,
) -> Dict:
    """
    This function will be process
    1. Fix Loan amount with adding new difference
    2. Fix disbursement with adding amount add new difference
    3. create disbursement history
    4. calculate new available balance
    """

    from collections import defaultdict
    from django_bulk_update.helper import bulk_update
    from juloserver.dana.models import DanaCustomerData, DanaPaymentBill
    from juloserver.disbursement.models import Disbursement, DisbursementHistory
    from juloserver.julo.models import Loan
    from juloserver.followthemoney.models import (
        LenderBalanceCurrent,
    )
    from juloserver.partnership.models import PartnerLoanRequest

    from juloserver.followthemoney.tasks import calculate_available_balance
    from juloserver.followthemoney.constants import SnapshotType

    dana_customer_datas = DanaCustomerData.objects.filter(
        id__in=dana_customer_data_ids
    ).values_list('account_id', flat=True)

    if target_loan_start_created_date:
        loans_ids = Loan.objects.filter(
            account_id__in=dana_customer_datas,
            cdate__date__gte=target_loan_start_created_date,
            cdate__date__lte=target_loan_end_created_date,
        ).values_list('id', flat=True)
    else:
        loans_ids = Loan.objects.filter(
            account_id__in=dana_customer_datas, cdate__date__lte=target_loan_end_created_date
        ).values_list('id', flat=True)

    payments = Payment.objects.select_related('loan', 'loan__lender').filter(loan__id__in=loans_ids)
    payment_ids = payments.values_list('id', flat=True)
    dana_payment_bills = DanaPaymentBill.objects.filter(payment_id__in=set(payment_ids)).order_by(
        'id'
    )

    mapping_dana_payment_principal = defaultdict(int)
    for dana_payment_bill in dana_payment_bills.iterator():
        loan_id = payments.get(id=dana_payment_bill.payment_id).loan_id
        mapping_dana_payment_principal[loan_id] += dana_payment_bill.principal_amount

    print('Success Mapping {} dana payment bill'.format(len(mapping_dana_payment_principal)))

    partner_loan_requests = PartnerLoanRequest.objects.filter(loan__id__in=loans_ids)
    mapping_partner_loan_request = defaultdict(int)
    for partner_loan_request in partner_loan_requests.iterator():
        mapping_partner_loan_request[partner_loan_request.loan_id] = partner_loan_request

    print('Success Mapping {} partner loan request'.format(len(mapping_partner_loan_request)))

    loans = Loan.objects.filter(id__in=loans_ids).order_by('cdate')
    disbursment_ids = loans.values_list('disbursement_id')
    disbursements = Disbursement.objects.filter(id__in=disbursment_ids).order_by('id')

    mapping_disbursements = defaultdict(int)
    for disbursement in disbursements.iterator():
        mapping_disbursements[disbursement.id] = disbursement

    print('Success Mapping {} disbursement data'.format(len(mapping_disbursements)))

    loan_update = []
    partner_loan_request_update = []
    disbursement_update = []
    loan_need_to_check = []
    for loan in loans.iterator():
        total_principal_amount = mapping_dana_payment_principal[loan.id]
        if loan.loan_amount != total_principal_amount:

            # Just in case if loan.loan_amount > total_principal_amount need to check further
            if loan.loan_amount > total_principal_amount:
                loan_need_to_check.append(loan.id)
                continue

            old_loan_amount = loan.loan_amount
            loan.loan_amount = total_principal_amount
            loan.loan_disbursement_amount = total_principal_amount
            loan_update.append(loan)

            partner_loan_request = mapping_partner_loan_request[loan.id]
            partner_loan_request.loan_disbursement_amount = total_principal_amount
            partner_loan_request_update.append(partner_loan_request)

            disbursement = mapping_disbursements[loan.disbursement_id]
            disbursement.before_update_amount = disbursement.amount
            disbursement.amount = total_principal_amount
            disbursement.original_amount = total_principal_amount
            disbursement_update.append(disbursement)

            # Update Lender Transaction Mapping
            lender = loan.lender
            current_lender_balance = (
                LenderBalanceCurrent.objects.select_for_update().filter(lender=lender).last()
            )
            difference_amount = total_principal_amount - old_loan_amount
            current_lender_committed_amount = current_lender_balance.committed_amount
            updated_committed_amount = current_lender_committed_amount + difference_amount
            updated_dict = {
                'loan_amount': difference_amount,
                'committed_amount': updated_committed_amount,
                'is_delay': False,
            }
            calculate_available_balance(
                current_lender_balance.id, SnapshotType.TRANSACTION, **updated_dict
            )
            print('Success Update loan {} '.format(loan.id))

    bulk_update(
        loan_update, update_fields=['loan_amount', 'loan_disbursement_amount'], batch_size=100
    )
    bulk_update(
        partner_loan_request_update, update_fields=['loan_disbursement_amount'], batch_size=100
    )
    bulk_update(disbursement_update, update_fields=['amount', 'original_amount'], batch_size=100)

    disbursement_history_bulk_create = []
    for disbursement in disbursement_update:
        updated_changes = {
            'new_amount': disbursement.amount,
            'new_original_amount': disbursement.original_amount,
            'old_amount': disbursement.before_update_amount,
            'difference_amount': disbursement.original_amount - disbursement.before_update_amount,
        }
        disbursement_create = DisbursementHistory(
            disbursement=disbursement, event='update_mismatch_amount', field_changes=updated_changes
        )
        disbursement_history_bulk_create.append(disbursement_create)
        print('Success Update loan {} '.format(disbursement.id))

    DisbursementHistory.objects.bulk_create(disbursement_history_bulk_create, batch_size=100)

    data = {
        'loan_update': loan_update,
        'partner_loan_request_update': partner_loan_request_update,
        'disbursement_update': disbursement_update,
        'loan_need_to_check': loan_need_to_check,
    }
    return data
