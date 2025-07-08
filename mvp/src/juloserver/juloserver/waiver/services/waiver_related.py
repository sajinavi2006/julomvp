import math
from builtins import str
import logging

from argparse import Namespace
from django.db.models import Sum
from django.utils import timezone, dateparse
from django.db import transaction

from .loan_refinancing_related import loan_refinancing_request_update_for_j1_waiver
from juloserver.waiver.models import (
    WaiverAccountPaymentRequest,
    WaiverAccountPaymentApproval,
)

from juloserver.payback.models import WaiverTemp
from juloserver.payback.models import WaiverPaymentTemp
from juloserver.payback.constants import WaiverConst
from juloserver.julo.utils import display_rupiah
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Payment
from juloserver.julo.constants import PaymentEventConst
from juloserver.account.models import (
    Account,
    AccountTransaction,
)
from juloserver.account_payment.models import (
    AccountPayment,
    AccountPaymentNote,
)
from juloserver.account_payment.services.payment_flow import (
    consume_payment_for_principal,
    consume_payment_for_interest,
    consume_payment_for_late_fee,
    store_calculated_payments,
    construct_old_paid_amount_list,
    update_account_payment_paid_off_status,
    get_and_update_latest_loan_status,
)
from juloserver.account_payment.services.reversal import (
    process_account_transaction_reversal,
    transfer_payment_after_reversal,
)
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest,
    WaiverRecommendation,
    WaiverRequest,
    WaiverPaymentRequest,
    WaiverPaymentApproval,
)
from juloserver.loan_refinancing.services.loan_related import expire_loan_refinancing_request
from juloserver.waiver.serializers import WaiverAccountPaymentApprovalSerializer
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.constants import Campaign
from juloserver.loan_refinancing.utils import get_partner_product
from juloserver.julocore.python2.utils import py2round
from juloserver.minisquad.services2.dialer_related import \
    delete_temp_bucket_base_on_account_payment_ids_and_bucket

logger = logging.getLogger(__name__)


def get_j1_waiver_recommendation(
    account_id, program, is_covid_risky, bucket, account_payment_ids=[]
):
    account = Account.objects.get_or_none(pk=account_id)
    product = 'normal'
    if bucket.lower() == "current":
        bucket = "Current"
    else:
        buckets = bucket.split(' ')
        if len(buckets) == 2:
            bucket = buckets[1]
    waiver_recommendation = WaiverRecommendation.objects.filter(
        program_name=program,
        bucket_name=bucket,
        partner_product=product,
        is_covid_risky=is_covid_risky,
    )
    if program == 'R6':
        if account_payment_ids:
            late_account_payments_count = (
                AccountPayment.objects.filter(id__in=account_payment_ids).overdue().count()
            )
        else:
            late_account_payments_count = (
                AccountPayment.objects.filter(account_id=account_id).overdue().count()
            )

        if not late_account_payments_count:
            logger.info(
                {
                    'method': 'get_j1_waiver_recommendation',
                    'account_id': account.id,
                    'error': (
                        "late_account_payments_count is zero program {}"
                        "bucket {} product {} is_covid_risky {}"
                    ).format(program, bucket, product, is_covid_risky),
                }
            )
            return
        waiver_recommendation = waiver_recommendation.filter(
            total_installments__lte=late_account_payments_count
        ).order_by("total_installments")
    waiver_recommendation = waiver_recommendation.last()
    if not waiver_recommendation:
        logger.info(
            {
                'method': 'get_j1_waiver_recommendation',
                'account_id': account.id,
                'error': (
                    "waiver recommendation not found for program {}"
                    "bucket {} product {} is_covid_risky {}"
                ).format(program, bucket, product, is_covid_risky),
            }
        )
        return
    return waiver_recommendation


def get_partial_account_payments(
        account, create_date, transaction_date_start, transaction_date_end):
    return AccountTransaction.objects.filter(
        transaction_type__in=["payment", "payment_void", "customer_wallet", "customer_wallet_void"],
        cdate__gte=create_date,
        transaction_date__date__gte=transaction_date_start,
        transaction_date__date__lte=transaction_date_end,
        account=account
    ).aggregate(
        total=Sum('transaction_amount')
    ).get('total') or 0


def get_partial_account_payments_by_program(loan_refinancing):
    if isinstance(loan_refinancing, WaiverRequest):
        return get_partial_account_payments(
            loan_refinancing.account,
            loan_refinancing.cdate,
            loan_refinancing.cdate.date(),
            loan_refinancing.waiver_validity_date,
        )
    if isinstance(loan_refinancing, LoanRefinancingRequest):
        if loan_refinancing.is_reactive:
            today = timezone.localtime(timezone.now())
            date_approved = timezone.localtime(loan_refinancing.cdate)
            loan_refinancing_offer = loan_refinancing.loanrefinancingoffer_set.filter(
                is_accepted=True
            ).last()
            if loan_refinancing_offer:
                date_approved = timezone.localtime(loan_refinancing_offer.offer_accepted_ts)
            return get_partial_account_payments(
                loan_refinancing.account, date_approved, date_approved.date(), today.date()
            )
        elif loan_refinancing.is_waiver:
            waiver_request = loan_refinancing.waiverrequest_set.last()
            return get_partial_account_payments(
                waiver_request.account,
                waiver_request.cdate,
                waiver_request.cdate.date(),
                waiver_request.waiver_validity_date,
            )
    return 0


def get_existing_j1_waiver_temp(account_payment, status=WaiverConst.ACTIVE_STATUS):
    waiver_payment_temp_dict = dict(
        waiver_temp__account=account_payment.account,
        account_payment=account_payment,
    )
    if status:
        waiver_payment_temp_dict["waiver_temp__status"] = status

    waiver_payment_temp = WaiverPaymentTemp.objects.filter(**waiver_payment_temp_dict).last()

    if waiver_payment_temp:
        return waiver_payment_temp.waiver_temp

    return None


def force_expired_j1_waiver_temp(account):
    WaiverTemp.objects.filter(
        account=account, status=WaiverConst.ACTIVE_STATUS,
    ).update(status=WaiverConst.EXPIRED_STATUS)


def j1_paid_waiver(
    waiver_type,
    account_payment,
    waiver_amount,
    note,
    loan_statuses_list: list,
    from_unpaid=False,
    waiver_request=None,
    is_autodebet_waive=False,
):
    """
    this function for create payment event for waive_late_fee and implemented waiver
    :param account_payment:
    :param waiver_amount:
    :param note:
    :return status an message:
    """

    title = " ".join(waiver_type.split('_')).title()
    waiver_dict = {
        'late_fee': Namespace(**{
            'towards': 0,
            'remaining': account_payment.remaining_late_fee,
            'action': consume_payment_for_late_fee,
        }),
        'interest': Namespace(**{
            'towards': 0,
            'remaining': account_payment.remaining_interest,
            'action': consume_payment_for_interest,
        }),
        'principal': Namespace(**{
            'towards': 0,
            'remaining': account_payment.remaining_principal,
            'action': consume_payment_for_principal,
        }),
    }

    if waiver_dict[waiver_type].remaining == 0:
        message = "Waive %s Failed, due to 0 value" % title
        return False, message

    transaction_datetime = timezone.localtime(timezone.now())
    transaction_date = transaction_datetime.date()

    payment_note = '[Add Event Waive %s]\n\
                    amount: %s,\n\
                    date: %s,\n\
                    note: %s.' % (title, display_rupiah(waiver_amount),
                                  transaction_date.strftime('%d-%m-%Y'),
                                  note)
    logger.info({
        'action': 'j1_waive_paid',
        'account_payment_id': account_payment.id,
        'waiver_amount': waiver_amount,
        'transaction_date': transaction_date,
        'waiver_type': waiver_type,
    })

    try:
        with transaction.atomic():
            account_payment = AccountPayment.objects.select_for_update().get(pk=account_payment.id)
            if from_unpaid:
                waiver_temp = get_existing_j1_waiver_temp(account_payment)
                waiver_payment_temp = waiver_temp.waiver_payment_temp_by_account_payment(
                    account_payment)
                amount_for_consume = getattr(waiver_payment_temp, "%s_waiver_amount" % waiver_type)
                waiver_request = waiver_temp.waiver_request
            else:
                amount_for_consume = waiver_amount
            payments = list(
                Payment.objects.not_paid_active_julo_one().filter(
                    account_payment=account_payment).order_by('loan_id')
            )
            old_paid_amount_list = construct_old_paid_amount_list(payments)

            if is_autodebet_waive:
                remaining_amount, total_paid_amount = process_autodebet_benefit_waiver(
                    account_payment, waiver_amount, payments
                )
            else:
                remaining_amount, total_paid_amount = waiver_dict[waiver_type].action(
                    payments,
                    account_payment.due_amount,
                    account_payment,
                    waiver_request,
                    amount_for_consume,
                )

            payment_events = store_calculated_payments(
                payments,
                transaction_date,
                None,
                None,
                old_paid_amount_list,
                False,
                loan_statuses_list,
                event_type="waive_%s" % waiver_type,
            )

            if account_payment.due_amount == 0:
                history_data = {
                    'status_old': account_payment.status,
                    'change_reason': 'paid_off %s' % note
                }
                update_account_payment_paid_off_status(account_payment)
                # delete account_payment bucket 3 data on collection table
                # logic paid off
                delete_temp_bucket_base_on_account_payment_ids_and_bucket(
                    [account_payment.id])
                account_payment.create_account_payment_status_history(history_data)
            account_payment.paid_date = transaction_date
            account_payment.save(update_fields=[
                'due_amount',
                'paid_amount',
                'paid_principal',
                'paid_interest',
                'paid_late_fee',
                'paid_date',
                'status',
                'udate'
            ])

            waiver_dict[waiver_type].towards += total_paid_amount

            account_trx = AccountTransaction.objects.create(
                account=account_payment.account,
                payback_transaction=None,
                transaction_date=transaction_datetime,
                transaction_amount=waiver_amount,
                transaction_type='waive_%s' % waiver_type,
                towards_principal=waiver_dict['principal'].towards,
                towards_interest=waiver_dict['interest'].towards,
                towards_latefee=waiver_dict['late_fee'].towards,
            )

            for payment_event in payment_events:
                payment_event.update_safely(account_transaction=account_trx)

            AccountPaymentNote.objects.create(
                note_text=payment_note,
                account_payment=account_payment)

    except JuloException as e:
        logger.info({
            'action': 'j1_waive_paid',
            'account_payment_id': account_payment.id,
            'message': str(e)
        })
    else:
        message = "Account Transaction waive_%s success" % waiver_type
        return True, message


def process_autodebet_benefit_waiver(account_payment, waiver_amount, payments):
    total_paid_interest = 0
    remaining_amount = account_payment.due_amount

    for payment in payments:
        remaining_interest = payment.installment_interest - payment.paid_interest
        if remaining_interest == 0:
            continue

        if total_paid_interest == waiver_amount:
            break

        payment.paid_amount += waiver_amount
        payment.due_amount -= waiver_amount
        payment.paid_interest += waiver_amount

        account_payment.paid_amount += waiver_amount
        account_payment.due_amount -= waiver_amount
        account_payment.paid_interest += waiver_amount

        remaining_amount -= waiver_amount
        total_paid_interest += waiver_amount

    return remaining_amount, total_paid_interest


def j1_unpaid_waiver(
        waiver_type, account_payment, waiver_amount, note, waive_validity_date, payment):
    """
    this function for create waiver temporary record which will executed by function
    j1_paid_waiver when customer do payment
    :param account_payment:
    :param waiver_amount:
    :param note:
    :param waive_validity_date:
    :return status and message:
    """

    existing_waiver_temp = get_existing_j1_waiver_temp(account_payment)
    transaction_date = timezone.localtime(timezone.now()).date()
    total_due_amount = account_payment.due_amount
    if existing_waiver_temp:
        total_due_amount = existing_waiver_temp.waiver_payment_temp.aggregate(
            total=Sum('account_payment__due_amount'))['total'] or 0

    data_to_save = dict()
    account_payment_to_save = dict(account_payment=account_payment)
    waiver_types = ("late_fee", "interest", "principal")
    total_waiver_amount = 0
    for new_waiver_type in waiver_types:
        field = '%s_waiver_amt' % new_waiver_type
        if new_waiver_type == waiver_type:
            if existing_waiver_temp:
                new_amount = existing_waiver_temp.get_waiver_amount(
                    "%s_waiver_amount" % new_waiver_type,
                    dict(account_payment=account_payment)
                ) + waiver_amount
            else:
                new_amount = waiver_amount
            total_waiver_amount += new_amount

            data_to_save[field] = new_amount
            data_to_save['%s_waiver_note' % new_waiver_type] = note
            account_payment_to_save['%s_waiver_amount' % new_waiver_type] = waiver_amount
        elif existing_waiver_temp and hasattr(existing_waiver_temp, field):
            total_waiver_amount += getattr(existing_waiver_temp, field)

    data_to_save.update(
        dict(
            need_to_pay=total_due_amount - total_waiver_amount,
            waiver_date=transaction_date,
            valid_until=waive_validity_date
        )
    )

    if existing_waiver_temp:
        existing_waiver_temp.update_safely(**data_to_save)
        existing_waiver_temp.waiver_payment_temp_by_account_payment(account_payment).update_safely(
            **account_payment_to_save)
        message = "Payment event waive_%s berhasil diubah" % waiver_type
        waiver_request = existing_waiver_temp.waiver_request
        if waiver_request:
            waiver_approval = waiver_request.waiverapproval_set.last()
            if waiver_approval:
                waiver_payment = waiver_approval.waiverpaymentapproval_set.get(payment=payment)
                if waiver_payment:
                    waiver_payment.approved_late_fee_waiver_amount += waiver_amount
                    waiver_payment.outstanding_late_fee_amount += waiver_amount
                    waiver_payment.total_outstanding_amount += waiver_amount
                    waiver_payment.total_approved_waiver_amount += waiver_amount
                    waiver_payment.save()
            else:
                waiver_payment = waiver_request.waiverpaymentrequest_set.get(payment=payment)
                if waiver_payment:
                    waiver_payment.requested_late_fee_waiver_amount += waiver_amount
                    waiver_payment.outstanding_late_fee_amount += waiver_amount
                    waiver_payment.total_outstanding_amount += waiver_amount
                    waiver_payment.total_requested_waiver_amount += waiver_amount
                    waiver_payment.save()
    else:
        waiver_temp = WaiverTemp.objects.create(account=account_payment.account, **data_to_save)
        WaiverPaymentTemp.objects.create(waiver_temp=waiver_temp, **account_payment_to_save)
        message = "Payment event waive_%s berhasil dibuat" % waiver_type
    loan_refinancing_request_update_for_j1_waiver(account_payment)
    return True, message


def process_j1_waiver_before_payment(account_payment, paid_amount, paid_date):
    # This function need to be called inside transaction atomic, since it using select_for_update
    # and will be called when customer do payment
    if not account_payment:
        return

    do_reversal = False
    waiver_temp = WaiverTemp.objects.select_for_update().filter(
        account=account_payment.account,
        status=WaiverConst.ACTIVE_STATUS
    ).last()
    if not waiver_temp:
        return

    # date validity
    if paid_date.date() > waiver_temp.valid_until:
        return

    # process multiple payment ptp
    process_j1_multiple_payment_ptp(waiver_temp.waiver_request, paid_amount, paid_date)

    # get partial payments
    payments_in_waive_period = get_partial_account_payments_by_program(waiver_temp.waiver_request)

    total_paid_amount = paid_amount
    if payments_in_waive_period > 0:
        total_paid_amount = payments_in_waive_period + paid_amount

    if total_paid_amount < waiver_temp.need_to_pay:
        return

    # handle for need_to_pay amount from partial payments
    if total_paid_amount != paid_amount:
        do_reversal = True
        account_transactions = AccountTransaction.objects.filter(
            transaction_type__in=[PaymentEventConst.PAYMENT, PaymentEventConst.CUSTOMER_WALLET],
            cdate__gte=waiver_temp.cdate,
            transaction_date__date__gte=waiver_temp.waiver_request.cdate.date(),
            transaction_date__date__lte=waiver_temp.waiver_request.waiver_validity_date,
            account=account_payment.account,
            can_reverse=True,
        ).order_by('-id')

        note = "partial payment waiver"
        account_transaction_voids = dict()
        for account_transaction in account_transactions:
            account_transaction_voids[
                account_transaction.id
            ] = process_account_transaction_reversal(
                account_transaction, note=note, refinancing_reversal=True
            )

    # allocate waiver amount
    waiver_account_payments = waiver_temp.waiverpaymenttemp_set.order_by(
        "account_payment__due_date")
    loan_statuses_list = []
    for waiver_account_payment in waiver_account_payments:
        waiver_types = ("late_fee", "interest", "principal")
        waiver_dict = {
            'late_fee': Namespace(**{
                'amount': waiver_account_payment.late_fee_waiver_amount,
                'note': waiver_temp.late_fee_waiver_note,
            }),
            'interest': Namespace(**{
                'amount': waiver_account_payment.interest_waiver_amount,
                'note': waiver_temp.interest_waiver_note,
            }),
            'principal': Namespace(**{
                'amount': waiver_account_payment.principal_waiver_amount,
                'note': waiver_temp.principal_waiver_note,
            }),
        }
        for waiver_type in waiver_types:
            with transaction.atomic():
                waiver_amount = waiver_dict[waiver_type].amount
                if waiver_amount and waiver_amount > 0:
                    j1_paid_waiver(
                        waiver_type,
                        waiver_account_payment.account_payment,
                        waiver_amount,
                        waiver_dict[waiver_type].note,
                        loan_statuses_list,
                        from_unpaid=True,
                    )
    get_and_update_latest_loan_status(loan_statuses_list)
    # bring back account_transaction that reversed
    if do_reversal:
        with transaction.atomic():
            account_transaction_void_objs = AccountTransaction.objects.filter(
                id__in=account_transaction_voids.keys()
            ).order_by('id')

            for account_transaction in account_transaction_void_objs:
                account_transaction_void = account_transaction_voids[account_transaction.id]
                if account_transaction_void:
                    transfer_payment_after_reversal(
                        account_transaction_void.original_transaction,
                        account_transaction_void.account,
                        account_transaction_void,
                        from_refinancing=True,
                    )

    waiver_temp.update_safely(status=WaiverConst.IMPLEMENTED_STATUS)


def get_existing_j1_waiver_request(account_payment):
    waiver_account_payment_request = WaiverAccountPaymentRequest.objects.filter(
        waiver_request__account=account_payment.account,
        account_payment=account_payment,
    ).last()

    if waiver_account_payment_request and \
            waiver_account_payment_request.waiver_request.waiver_validity_date >= \
            timezone.localtime(timezone.now()).date():
        return waiver_account_payment_request.waiver_request

    return None


def automate_late_fee_waiver_for_j1(account_payment, late_fee_amount, payment, event_date):
    waiver_temp = get_existing_j1_waiver_temp(account_payment)
    if waiver_temp:
        waiver_request = waiver_temp.waiver_request
        if not waiver_request:
            return

    else:
        waiver_request = get_existing_j1_waiver_request(account_payment)
        if not waiver_request:
            return

    waiver_payment_request = waiver_request.waiverpaymentrequest_set.get(payment=payment)
    waiver_approval = waiver_request.waiverapproval_set.last()
    if waiver_approval:
        waiver_payment_approval = waiver_approval.waiverpaymentapproval_set.get(payment=payment)

    # this mean waiver is not active yet
    if not waiver_temp:
        # updating waiver_request only if the waiver is not yet active
        # waiver_request need updated no mather if waiver_approval is created or not
        waiver_request.outstanding_amount += late_fee_amount
        waiver_request.unpaid_late_fee += late_fee_amount
        waiver_request.requested_late_fee_waiver_amount += late_fee_amount
        waiver_request.requested_waiver_amount += late_fee_amount
        if waiver_request.final_approved_waiver_amount:
            waiver_request.final_approved_waiver_amount += late_fee_amount
        waiver_request.save()

        # if waiver_approval exist this mean waiver program is not auto approved
        # in this case we only mantain waiver_payment_approval and
        # waiver_account_payment_approval table
        # and leave waiver_payment_request and waiver_account_payment_request untouched
        if waiver_approval:
            waiver_approval.approved_waiver_amount += late_fee_amount
            waiver_approval.save()

            waiver_account_payment_approval = (
                waiver_approval.waiver_account_payment_approval.filter(
                    account_payment=account_payment).last()
            )
            waiver_account_payment_approval.approved_late_fee_waiver_amount += late_fee_amount
            waiver_account_payment_approval.total_approved_waiver_amount += late_fee_amount
            waiver_account_payment_approval.save()

            waiver_payment_approval.approved_late_fee_waiver_amount += late_fee_amount
            waiver_payment_approval.total_approved_waiver_amount += late_fee_amount
            waiver_payment_approval.save()
            return

        waiver_account_payment_request = waiver_request.waiver_account_payment_request.filter(
            account_payment=account_payment).last()
        waiver_account_payment_request.requested_late_fee_waiver_amount += late_fee_amount
        waiver_account_payment_request.total_requested_waiver_amount += late_fee_amount
        waiver_account_payment_request.save()

        waiver_payment_request.requested_late_fee_waiver_amount += late_fee_amount
        waiver_payment_request.total_requested_waiver_amount += late_fee_amount
        waiver_payment_request.save()
        return

    if waiver_temp.status == WaiverConst.ACTIVE_STATUS:
        approved_obj = waiver_approval if waiver_approval else waiver_request

        note = ("Original Late Fee Waiver Amount: {}; "
                "New Accrued Late Fee Waiver Amount After Request: {}").format(
            approved_obj.total_account_payment_approved_late_fee_waiver,
            waiver_temp.late_fee_waiver_amt + late_fee_amount, )
        transaction_date = timezone.localtime(timezone.now()).date()

        # Prevent racing condition
        waiver_temp = WaiverTemp.objects.select_for_update().get(pk=waiver_temp.id)

        # for active waiver program we need to update waiver_temp table instead of waiver_request
        waiver_temp.late_fee_waiver_amt += late_fee_amount
        waiver_temp.late_fee_waiver_note = note
        waiver_temp.waiver_date = transaction_date
        waiver_temp.save()

        # on J1 waiver program the data stored on waiver_payment_temp
        # table actually in account_payment level data
        waiver_account_payment_temp = waiver_temp.waiver_payment_temp.select_for_update().filter(
            account_payment=account_payment).last()
        waiver_account_payment_temp.late_fee_waiver_amount += late_fee_amount
        waiver_account_payment_temp.save()

        if waiver_approval:
            waiver_payment_approval.approved_late_fee_waiver_amount += late_fee_amount
            waiver_payment_approval.outstanding_late_fee_amount += late_fee_amount
            waiver_payment_approval.total_outstanding_amount += late_fee_amount
            waiver_payment_approval.total_approved_waiver_amount += late_fee_amount
            waiver_payment_approval.save()
        else:
            waiver_payment_request.requested_late_fee_waiver_amount += late_fee_amount
            waiver_payment_request.outstanding_late_fee_amount += late_fee_amount
            waiver_payment_request.total_outstanding_amount += late_fee_amount
            waiver_payment_request.total_requested_waiver_amount += late_fee_amount
            waiver_payment_request.save()

        loan_refinancing_request_update_for_j1_waiver(account_payment)
        return

    if waiver_temp.status == WaiverConst.IMPLEMENTED_STATUS and \
            event_date <= waiver_temp.valid_until:
        j1_paid_waiver(
            "late_fee", account_payment, late_fee_amount,
            "Automated waive_late_fee due to implemented waiver",
            from_unpaid=False, waiver_request=None
        )
        return


def process_j1_multiple_payment_ptp(waiver_request, paid_amount, paid_date):
    if not waiver_request.multiple_payment_ptp:
        return

    for payment_ptp in waiver_request.unpaid_multiple_payment_ptp():
        if paid_amount <= 0:
            break

        if paid_amount >= payment_ptp.remaining_amount:
            payment_ptp.paid_amount = payment_ptp.promised_payment_amount
            payment_ptp.is_fully_paid = True
            paid_amount -= payment_ptp.remaining_amount

        else:
            payment_ptp.paid_amount += paid_amount
            paid_amount = 0

        payment_ptp.remaining_amount = payment_ptp.promised_payment_amount - payment_ptp.paid_amount
        payment_ptp.paid_date = paid_date.date()
        payment_ptp.save()


def manual_expire_refinancing_program(loan_refinancing_request):
    expire_loan_refinancing = expire_loan_refinancing_request(
        loan_refinancing_request
    )
    if loan_refinancing_request.product_type in CovidRefinancingConst.reactive_products():
        return expire_loan_refinancing

    WaiverTemp.objects.filter(
        account=loan_refinancing_request.account,
        loan=loan_refinancing_request.loan
    ).exclude(
        status__in=(WaiverConst.EXPIRED_STATUS, WaiverConst.IMPLEMENTED_STATUS)
    ).update(status=WaiverConst.EXPIRED_STATUS)
    return expire_loan_refinancing


def generate_and_calculate_waiver_request_reactive(
    data,
    waiver_request,
    selected_waived_account_payments,
    is_from_agent=True,
    is_from_campaign=False,
):
    waiver_request.waiver_account_payment_request.all().delete()
    waiver_account_payment_data = []
    waiver_payment_data = []
    account_payments_dict = dict()
    if is_from_agent:
        requested_late_fee_waiver_percentage = float(
            data['unrounded_requested_late_fee_waiver_percentage'])
        requested_interest_waiver_percentage = float(
            data['unrounded_requested_interest_waiver_percentage'])
        requested_principal_waiver_percentage = float(
            data['unrounded_requested_principal_waiver_percentage'])
        selected_waived_principal_key = 'principal'
        selected_waived_interest_key = 'interest'
        selected_waived_late_fee_key = 'late_fee'
    elif is_from_campaign:
        if data["program_name"].lower() == 'r4':
            requested_late_fee_waiver_percentage = (
                getattr(waiver_request, "unrounded_requested_late_fee_waiver_percentage") or 1
            )
            requested_interest_waiver_percentage = (
                getattr(waiver_request, "unrounded_requested_interest_waiver_percentage") or 1
            )
            requested_principal_waiver_percentage = (
                getattr(waiver_request, "unrounded_requested_principal_waiver_percentage") or 1
            )
        else:
            requested_late_fee_waiver_percentage = (
                getattr(waiver_request, "unrounded_requested_late_fee_waiver_percentage")
            )
            requested_interest_waiver_percentage = (
                getattr(waiver_request, "unrounded_requested_interest_waiver_percentage")
            )
            requested_principal_waiver_percentage = (
                getattr(waiver_request, "unrounded_requested_principal_waiver_percentage")
            )
        selected_waived_principal_key = 'requested_principal_waiver_amount'
        selected_waived_interest_key = 'requested_interest_waiver_amount'
        selected_waived_late_fee_key = 'requested_late_fee_waiver_amount'
    else:
        requested_late_fee_waiver_percentage = (
            getattr(waiver_request, "unrounded_requested_late_fee_waiver_percentage") or 1
        )
        requested_interest_waiver_percentage = (
            getattr(waiver_request, "unrounded_requested_interest_waiver_percentage") or 1
        )
        requested_principal_waiver_percentage = (
            getattr(waiver_request, "unrounded_requested_principal_waiver_percentage") or 1
        )
        selected_waived_principal_key = 'requested_principal_waiver_amount'
        selected_waived_interest_key = 'requested_interest_waiver_amount'
        selected_waived_late_fee_key = 'requested_late_fee_waiver_amount'

    ptp_amount = data['ptp_amount']
    count_selected_waived_account_payments = len(selected_waived_account_payments)
    # only use this if we dont have any reference for the calculation
    remaining_requested_diff_calculation = dict(
        principal=0, interest=0, late_fee=0
    )
    account_payment_ids = [x['account_payment_id'] for x in selected_waived_account_payments]
    WaiverPaymentRequest.objects.filter(account_payment_id__in=account_payment_ids).delete()
    for idx in range(count_selected_waived_account_payments):
        selected_waived_account_payment = selected_waived_account_payments[idx]
        account_payment_id = selected_waived_account_payment['account_payment_id']
        payments = Payment.objects.filter(
            account_payment_id=account_payment_id).not_paid_active().order_by('id', 'due_date')
        is_last_account_payment = idx + 1 == count_selected_waived_account_payments
        agent_waived_principal = int(selected_waived_account_payment.get(
            selected_waived_principal_key) or 0)
        agent_waived_interest = int(selected_waived_account_payment.get(
            selected_waived_interest_key) or 0)
        agent_waived_late_fee = int(selected_waived_account_payment.get(
            selected_waived_late_fee_key) or 0)
        is_calculation_have_reference = True
        if not agent_waived_principal and not agent_waived_interest and not agent_waived_late_fee:
            is_calculation_have_reference = False

        waived_payment_level_per_account_payment = []
        for i, payment in enumerate(payments):
            late_fee = payment.remaining_late_fee
            interest = payment.remaining_interest
            principal = payment.remaining_principal
            account_payment_id = payment.account_payment_id
            calculated_requested_waiver = dict(
                late_fee=math.ceil(requested_late_fee_waiver_percentage * float(late_fee)),
                interest=math.ceil(requested_interest_waiver_percentage * float(interest)),
                principal=math.ceil(requested_principal_waiver_percentage * float(principal))
            )
            # because we refer the principal value from agent input / Front End
            # so waiver temp and request will arrange
            if is_calculation_have_reference:
                if agent_waived_principal >= calculated_requested_waiver['principal']:
                    agent_waived_principal -= calculated_requested_waiver['principal']
                else:
                    calculated_requested_waiver['principal'] = agent_waived_principal
                    agent_waived_principal = 0
                # because we refer the interest value from agent input / Front End
                if agent_waived_interest >= calculated_requested_waiver['interest']:
                    agent_waived_interest -= calculated_requested_waiver['interest']
                else:
                    calculated_requested_waiver['interest'] = agent_waived_interest
                    agent_waived_interest = 0

                # because we refer the interest value from agent input / Front End
                if agent_waived_late_fee >= calculated_requested_waiver['late_fee']:
                    agent_waived_late_fee -= calculated_requested_waiver['late_fee']
                else:
                    calculated_requested_waiver['late_fee'] = agent_waived_late_fee
                    agent_waived_late_fee = 0
            # but if we dont have any reference from FE then
            # final checking for recalculate if requested payment level not arrange with
            # account payment only recalculate if we dont have reference from FE
            # this code is for distribute diff between account payment and payment level
            else:
                if i + 1 == len(payments) and account_payment_id in account_payments_dict.keys():
                    account_payment_dict_calculation = account_payments_dict[account_payment_id]
                    for recalculate_type in ['principal', 'interest', 'late_fee']:
                        total_requested_account_payment = py2round(
                            eval('requested_{}_waiver_percentage'.format(recalculate_type)) *
                            float(
                                account_payment_dict_calculation[
                                    'total_{}_for_account_payment'.format(recalculate_type)
                                ] + eval(recalculate_type))
                        )
                        total_calculated_payment_level = account_payment_dict_calculation[
                            'requested_{}_waiver_amount'.format(recalculate_type)] + \
                            eval("calculated_requested_waiver['{}']".format(recalculate_type))
                        if total_requested_account_payment != total_calculated_payment_level:
                            diff = total_requested_account_payment - \
                                total_calculated_payment_level
                            remaining_requested_diff_calculation[recalculate_type] += diff
                        # distribute remaining calculation diff to last account payment
                        if is_last_account_payment:
                            calculated_requested_waiver[recalculate_type] += \
                                remaining_requested_diff_calculation[recalculate_type]

            total_requested_waiver_amount = calculated_requested_waiver['principal'] + \
                calculated_requested_waiver['interest'] + calculated_requested_waiver['late_fee']
            outstanding_late_fee = payment.remaining_late_fee - \
                calculated_requested_waiver['late_fee']
            outstanding_interest = payment.remaining_interest - \
                calculated_requested_waiver['interest']
            outstanding_principal = payment.remaining_principal - \
                calculated_requested_waiver['principal']
            total_outstanding_amount = outstanding_late_fee + outstanding_interest + \
                outstanding_principal
            remaining_dict = dict(
                remaining_interest=0,
                remaining_late_fee=0,
                remaining_principal=0,
            )
            for remaining_type in ['principal', 'interest', 'late_fee']:
                outstanding_amount = eval(
                    'outstanding_{}'.format(remaining_type))
                remaining_amount = outstanding_amount - ptp_amount
                if remaining_amount > 0:
                    remaining_dict['remaining_{}'.format(remaining_type)] = remaining_amount
                ptp_amount -= outstanding_amount
                if ptp_amount <= 0:
                    break

            remaining_amount_total = remaining_dict['remaining_late_fee'] + \
                remaining_dict['remaining_interest'] + remaining_dict['remaining_principal']
            waived_payment_level_per_account_payment.append(
                WaiverPaymentRequest(
                    waiver_request=waiver_request,
                    account_payment_id=account_payment_id,
                    payment=payment,
                    outstanding_late_fee_amount=outstanding_late_fee,
                    outstanding_interest_amount=outstanding_interest,
                    outstanding_principal_amount=outstanding_principal,
                    total_outstanding_amount=total_outstanding_amount,
                    requested_late_fee_waiver_amount=calculated_requested_waiver['late_fee'],
                    requested_interest_waiver_amount=calculated_requested_waiver['interest'],
                    requested_principal_waiver_amount=calculated_requested_waiver['principal'],
                    total_requested_waiver_amount=total_requested_waiver_amount,
                    remaining_late_fee_amount=remaining_dict['remaining_late_fee'],
                    remaining_interest_amount=remaining_dict['remaining_interest'],
                    remaining_principal_amount=remaining_dict['remaining_principal'],
                    total_remaining_amount=remaining_amount_total,
                )
            )
            if account_payment_id in account_payments_dict.keys():
                account_payment_dict = account_payments_dict[account_payment_id]
                account_payments_dict[account_payment_id] = {
                    'outstanding_late_fee_amount':
                        account_payment_dict['outstanding_late_fee_amount'] + outstanding_late_fee,
                    'outstanding_interest_amount':
                        account_payment_dict['outstanding_interest_amount'] + outstanding_interest,
                    'outstanding_principal_amount':
                        account_payment_dict[
                            'outstanding_principal_amount'] + outstanding_principal,
                    'total_outstanding_amount':
                        account_payment_dict[
                            'total_outstanding_amount'] + total_outstanding_amount,
                    'requested_late_fee_waiver_amount':
                        account_payment_dict['requested_late_fee_waiver_amount'] +
                        calculated_requested_waiver['late_fee'],
                    'requested_interest_waiver_amount':
                        account_payment_dict['requested_interest_waiver_amount'] +
                        calculated_requested_waiver['interest'],
                    'requested_principal_waiver_amount':
                        account_payment_dict['requested_principal_waiver_amount'] +
                        calculated_requested_waiver['principal'],
                    'total_requested_waiver_amount':
                        account_payment_dict['total_requested_waiver_amount'] +
                        total_requested_waiver_amount,
                    'remaining_late_fee_amount':
                        account_payment_dict['remaining_late_fee_amount'] +
                        remaining_dict['remaining_late_fee'],
                    'remaining_interest_amount':
                        account_payment_dict['remaining_interest_amount'] +
                        remaining_dict['remaining_interest'],
                    'remaining_principal_amount':
                        account_payment_dict['remaining_principal_amount'] +
                        remaining_dict['remaining_principal'],
                    'total_remaining_amount':
                        account_payment_dict['total_remaining_amount'] +
                        remaining_amount_total,
                    'total_principal_for_account_payment':
                        account_payment_dict['total_principal_for_account_payment'] + principal,
                    'total_interest_for_account_payment':
                        account_payment_dict['total_interest_for_account_payment'] + interest,
                    'total_late_fee_for_account_payment':
                        account_payment_dict['total_late_fee_for_account_payment'] + late_fee,
                }
            else:
                account_payments_dict[account_payment_id] = {
                    'outstanding_late_fee_amount': outstanding_late_fee,
                    'outstanding_interest_amount': outstanding_interest,
                    'outstanding_principal_amount': outstanding_principal,
                    'total_outstanding_amount': total_outstanding_amount,
                    'requested_late_fee_waiver_amount': calculated_requested_waiver['late_fee'],
                    'requested_interest_waiver_amount': calculated_requested_waiver['interest'],
                    'requested_principal_waiver_amount': calculated_requested_waiver['principal'],
                    'total_requested_waiver_amount': total_requested_waiver_amount,
                    'remaining_late_fee_amount': remaining_dict['remaining_late_fee'],
                    'remaining_interest_amount': remaining_dict['remaining_interest'],
                    'remaining_principal_amount': remaining_dict['remaining_principal'],
                    'total_remaining_amount': remaining_amount_total,
                    'total_principal_for_account_payment': principal,
                    'total_interest_for_account_payment': interest,
                    'total_late_fee_for_account_payment': late_fee,
                }
        # final checking if input from agent have diff with calculation from BE
        account_payment_dict = account_payments_dict[account_payment_id]
        if agent_waived_principal > 0 or agent_waived_interest > 0 \
                or agent_waived_late_fee > 0:
            for waiver_payment_level in waived_payment_level_per_account_payment:
                outstanding_principal = waiver_payment_level.outstanding_principal_amount
                outstanding_interest = waiver_payment_level.outstanding_interest_amount
                outstanding_late_fee = waiver_payment_level.outstanding_late_fee_amount
                is_remaining_outstanding_principal = outstanding_principal > 0
                is_remaining_outstanding_interest = outstanding_interest > 0
                is_remaining_outstanding_late_fee = outstanding_late_fee > 0
                is_have_remaining_outstanding = (
                    is_remaining_outstanding_principal,
                    is_remaining_outstanding_interest,
                    is_remaining_outstanding_late_fee)
                # check is payment still have remaining outstanding for substract
                # if not then change to other payment
                if not any(is_have_remaining_outstanding):
                    continue
                # recalculate outstanding, total, account payments, requested for arrange
                # with reference if exists
                remaining_principal = 0
                remaining_interest = 0
                remaining_late_fee = 0
                if agent_waived_principal > 0 and is_remaining_outstanding_principal:
                    remaining_principal = agent_waived_principal
                    if outstanding_principal - agent_waived_principal < 0:
                        remaining_principal = outstanding_principal
                    waiver_payment_level.requested_principal_waiver_amount += remaining_principal
                    waiver_payment_level.outstanding_principal_amount -= remaining_principal
                    account_payment_dict['outstanding_principal_amount'] -= remaining_principal
                    account_payment_dict['requested_principal_waiver_amount'] += remaining_principal
                    agent_waived_principal -= remaining_principal
                    if waiver_payment_level.remaining_principal_amount > 0:
                        waiver_payment_level.remaining_principal_amount -= remaining_principal
                    if account_payment_dict['remaining_principal_amount'] > 0:
                        account_payment_dict['remaining_principal_amount'] -= remaining_principal

                if agent_waived_interest > 0 and is_remaining_outstanding_interest:
                    remaining_interest = agent_waived_interest
                    if outstanding_interest - agent_waived_interest < 0:
                        remaining_interest = outstanding_interest
                    waiver_payment_level.requested_interest_waiver_amount += remaining_interest
                    waiver_payment_level.outstanding_interest_amount -= remaining_interest
                    account_payment_dict['outstanding_interest_amount'] -= remaining_interest
                    account_payment_dict['requested_interest_waiver_amount'] += remaining_interest
                    agent_waived_interest -= remaining_interest
                    if waiver_payment_level.remaining_interest_amount > 0:
                        waiver_payment_level.remaining_interest_amount -= remaining_interest
                    if account_payment_dict['remaining_interest_amount'] > 0:
                        account_payment_dict['remaining_interest_amount'] -= remaining_interest

                if agent_waived_late_fee > 0 and is_remaining_outstanding_late_fee:
                    remaining_late_fee = agent_waived_late_fee
                    if outstanding_late_fee - agent_waived_late_fee < 0:
                        remaining_late_fee = outstanding_late_fee
                    waiver_payment_level.requested_late_fee_waiver_amount += remaining_late_fee
                    waiver_payment_level.outstanding_late_fee_amount -= remaining_late_fee
                    account_payment_dict['outstanding_late_fee_amount'] -= remaining_late_fee
                    account_payment_dict['requested_late_fee_waiver_amount'] += remaining_late_fee
                    agent_waived_late_fee -= remaining_late_fee
                    if waiver_payment_level.remaining_late_fee_amount > 0:
                        waiver_payment_level.remaining_late_fee_amount -= remaining_late_fee
                    if account_payment_dict['remaining_late_fee_amount'] > 0:
                        account_payment_dict['remaining_late_fee_amount'] -= remaining_late_fee
                # recalculate total_outstanding_amount, total_requested_waiver_amount,
                # total_remaining_amount because we calculate the remaining diff
                total_remaining_from_agent = remaining_principal + \
                    remaining_interest + remaining_late_fee
                waiver_payment_level.total_outstanding_amount -= total_remaining_from_agent
                waiver_payment_level.total_requested_waiver_amount += total_remaining_from_agent
                waiver_payment_level.total_remaining_amount -= total_remaining_from_agent
                account_payment_dict['total_outstanding_amount'] -= total_remaining_from_agent
                account_payment_dict['total_requested_waiver_amount'] += total_remaining_from_agent
                account_payment_dict['total_remaining_amount'] -= total_remaining_from_agent

        waiver_payment_data.extend(waived_payment_level_per_account_payment)

    for account_payment_id in account_payments_dict:
        account_payment_dict = account_payments_dict[account_payment_id]
        waiver_account_payment_data.append(
            WaiverAccountPaymentRequest(
                waiver_request=waiver_request,
                account_payment_id=account_payment_id,
                outstanding_late_fee_amount=account_payment_dict['outstanding_late_fee_amount'],
                outstanding_interest_amount=account_payment_dict['outstanding_interest_amount'],
                outstanding_principal_amount=account_payment_dict['outstanding_principal_amount'],
                total_outstanding_amount=account_payment_dict['total_outstanding_amount'],
                requested_late_fee_waiver_amount=account_payment_dict[
                    'requested_late_fee_waiver_amount'],
                requested_interest_waiver_amount=account_payment_dict[
                    'requested_interest_waiver_amount'],
                requested_principal_waiver_amount=account_payment_dict[
                    'requested_principal_waiver_amount'],
                total_requested_waiver_amount=account_payment_dict[
                    'total_requested_waiver_amount'],
                remaining_late_fee_amount=account_payment_dict['remaining_late_fee_amount'],
                remaining_interest_amount=account_payment_dict['remaining_interest_amount'],
                remaining_principal_amount=account_payment_dict['remaining_principal_amount'],
                total_remaining_amount=account_payment_dict['total_remaining_amount'],
            )
        )
    return waiver_payment_data, waiver_account_payment_data


def generate_and_calculate_waiver_approval_reactive(
        waiver_approval_obj, waiver_account_payment_approvals_data, ptp_amount_param,
        is_ptp_paid=False
):
    account_payments_dict = dict()
    waiver_payment_approval_data = []
    waiver_account_payment_approval_data = []
    unrounded_approved_principal_waiver_percentage = \
        waiver_approval_obj.unrounded_approved_principal_waiver_percentage
    unrounded_approved_interest_waiver_percentage = \
        waiver_approval_obj.unrounded_approved_interest_waiver_percentage
    unrounded_approved_late_fee_waiver_percentage = \
        waiver_approval_obj.unrounded_approved_late_fee_waiver_percentage
    ptp_amount = ptp_amount_param
    count_waiver_account_payment_approval = len(waiver_account_payment_approvals_data)
    remaining_diff_approved_calculation = dict(
        principal=0, interest=0, late_fee=0
    )
    for idx in range(count_waiver_account_payment_approval):
        waiver_account_payment_approval = waiver_account_payment_approvals_data[idx]
        waiver_account_payment_approval_serializer = \
            WaiverAccountPaymentApprovalSerializer(data=waiver_account_payment_approval)
        waiver_account_payment_approval_serializer. \
            is_valid(raise_exception=True)
        waiver_account_payment_approval_valid = \
            waiver_account_payment_approval_serializer.validated_data
        account_payment_id = \
            waiver_account_payment_approval_valid['account_payment_id']
        WaiverPaymentApproval.objects.filter(
            account_payment_id=account_payment_id).delete()
        payments = Payment.objects.filter(
            account_payment_id=account_payment_id).not_paid_active().order_by('due_date')
        tl_approved_waived_principal = waiver_account_payment_approval_valid[
            'approved_principal_waiver_amount']
        tl_approved_waived_interest = waiver_account_payment_approval_valid[
            'approved_interest_waiver_amount']
        tl_approved_waived_late_fee = waiver_account_payment_approval_valid[
            'approved_late_fee_waiver_amount']
        approved_waived_payment_level_per_account_payment = []
        is_last_account_payment = idx + 1 == count_waiver_account_payment_approval
        for i, payment in enumerate(payments):
            late_fee = payment.remaining_late_fee
            interest = payment.remaining_interest
            principal = payment.remaining_principal
            account_payment_id = payment.account_payment_id
            calculated_approved_waiver = dict(
                late_fee=math.ceil(unrounded_approved_late_fee_waiver_percentage * float(late_fee)),
                interest=math.ceil(unrounded_approved_interest_waiver_percentage * float(interest)),
                principal=math.ceil(
                    unrounded_approved_principal_waiver_percentage * float(principal))
            )
            # because we refer the principal value from agent input / Front End
            # so waiver temp and request will arrange
            if not is_ptp_paid:
                if tl_approved_waived_principal >= calculated_approved_waiver['principal']:
                    tl_approved_waived_principal -= calculated_approved_waiver['principal']
                else:
                    calculated_approved_waiver['principal'] = tl_approved_waived_principal
                    tl_approved_waived_principal = 0
                # because we refer the interest value from agent input / Front End
                if tl_approved_waived_interest >= calculated_approved_waiver['interest']:
                    tl_approved_waived_interest -= calculated_approved_waiver['interest']
                else:
                    calculated_approved_waiver['interest'] = tl_approved_waived_interest
                    tl_approved_waived_interest = 0

                # because we refer the interest value from agent input / Front End
                if tl_approved_waived_late_fee >= calculated_approved_waiver['late_fee']:
                    tl_approved_waived_late_fee -= calculated_approved_waiver['late_fee']
                else:
                    calculated_approved_waiver['late_fee'] = tl_approved_waived_late_fee
                    tl_approved_waived_late_fee = 0
            # not used for now because we already refer the amount from input FE
            # final checking for recalculate if approved payment level not arrange with
            # account payment
            else:
                if i + 1 == len(payments) and account_payment_id in account_payments_dict.keys():
                    account_payment_dict_calculation = account_payments_dict[account_payment_id]
                    for recalculate_type in ['principal', 'interest', 'late_fee']:
                        total_approved_account_payment = py2round(
                            eval(
                                'unrounded_approved_{}_waiver_percentage'.format(recalculate_type)
                            ) *
                            float(
                                account_payment_dict_calculation[
                                    'total_{}_for_account_payment'.format(recalculate_type)
                                ] + eval(recalculate_type))
                        )
                        total_calculated_payment_level = account_payment_dict_calculation[
                            'approved_{}_waiver_amount'.format(recalculate_type)] + \
                            eval("calculated_approved_waiver['{}']".format(recalculate_type))
                        # distribute remaining calculation diff to last account payment
                        if total_approved_account_payment != total_calculated_payment_level:
                            diff = total_approved_account_payment - \
                                total_calculated_payment_level
                            remaining_diff_approved_calculation[recalculate_type] += diff
                        if is_last_account_payment:
                            calculated_approved_waiver[recalculate_type] += \
                                remaining_diff_approved_calculation[recalculate_type]

            total_approved_waiver_amount = calculated_approved_waiver['principal'] + \
                calculated_approved_waiver['interest'] + calculated_approved_waiver['late_fee']
            outstanding_late_fee = payment.remaining_late_fee - \
                calculated_approved_waiver['late_fee']
            outstanding_interest = payment.remaining_interest - \
                calculated_approved_waiver['interest']
            outstanding_principal = payment.remaining_principal - \
                calculated_approved_waiver['principal']
            total_outstanding_amount = outstanding_late_fee + outstanding_interest + \
                outstanding_principal
            remaining_dict = dict(
                remaining_interest=0,
                remaining_late_fee=0,
                remaining_principal=0,
            )
            for remaining_type in ['principal', 'interest', 'late_fee']:
                outstanding_amount = eval(
                    'outstanding_{}'.format(remaining_type))
                remaining_amount = outstanding_amount - ptp_amount
                if remaining_amount > 0:
                    remaining_dict['remaining_{}'.format(remaining_type)] = remaining_amount
                ptp_amount -= outstanding_amount
                if ptp_amount <= 0:
                    break

            remaining_amount_total = remaining_dict['remaining_late_fee'] + \
                remaining_dict['remaining_interest'] + remaining_dict['remaining_principal']
            approved_waived_payment_level_per_account_payment.append(
                WaiverPaymentApproval(
                    waiver_approval=waiver_approval_obj,
                    account_payment_id=account_payment_id,
                    payment=payment,
                    outstanding_late_fee_amount=outstanding_late_fee,
                    outstanding_interest_amount=outstanding_interest,
                    outstanding_principal_amount=outstanding_principal,
                    total_outstanding_amount=total_outstanding_amount,
                    approved_late_fee_waiver_amount=calculated_approved_waiver['late_fee'],
                    approved_interest_waiver_amount=calculated_approved_waiver['interest'],
                    approved_principal_waiver_amount=calculated_approved_waiver['principal'],
                    total_approved_waiver_amount=total_approved_waiver_amount,
                    remaining_late_fee_amount=remaining_dict['remaining_late_fee'],
                    remaining_interest_amount=remaining_dict['remaining_interest'],
                    remaining_principal_amount=remaining_dict['remaining_principal'],
                    total_remaining_amount=remaining_amount_total,
                )
            )
            if account_payment_id in account_payments_dict.keys():
                account_payment_dict = account_payments_dict[account_payment_id]
                account_payments_dict[account_payment_id] = {
                    'outstanding_late_fee_amount':
                        account_payment_dict['outstanding_late_fee_amount'] + outstanding_late_fee,
                    'outstanding_interest_amount':
                        account_payment_dict['outstanding_interest_amount'] + outstanding_interest,
                    'outstanding_principal_amount':
                        account_payment_dict[
                            'outstanding_principal_amount'] + outstanding_principal,
                    'total_outstanding_amount':
                        account_payment_dict['total_outstanding_amount'] + total_outstanding_amount,
                    'approved_late_fee_waiver_amount':
                        account_payment_dict['approved_late_fee_waiver_amount'] +
                        calculated_approved_waiver['late_fee'],
                    'approved_interest_waiver_amount':
                        account_payment_dict['approved_interest_waiver_amount'] +
                        calculated_approved_waiver['interest'],
                    'approved_principal_waiver_amount':
                        account_payment_dict['approved_principal_waiver_amount'] +
                        calculated_approved_waiver['principal'],
                    'total_approved_waiver_amount':
                        account_payment_dict['total_approved_waiver_amount'] +
                        total_approved_waiver_amount,
                    'remaining_late_fee_amount':
                        account_payment_dict['remaining_late_fee_amount'] +
                        remaining_dict['remaining_late_fee'],
                    'remaining_interest_amount':
                        account_payment_dict['remaining_interest_amount'] +
                        remaining_dict['remaining_interest'],
                    'remaining_principal_amount':
                        account_payment_dict['remaining_principal_amount'] +
                        remaining_dict['remaining_principal'],
                    'total_remaining_amount':
                        account_payment_dict['total_remaining_amount'] +
                        remaining_amount_total,
                    'total_principal_for_account_payment':
                        account_payment_dict['total_principal_for_account_payment'] + principal,
                    'total_interest_for_account_payment':
                        account_payment_dict['total_interest_for_account_payment'] + interest,
                    'total_late_fee_for_account_payment':
                        account_payment_dict['total_late_fee_for_account_payment'] + late_fee,
                }
            else:
                account_payments_dict[account_payment_id] = {
                    'outstanding_late_fee_amount': outstanding_late_fee,
                    'outstanding_interest_amount': outstanding_interest,
                    'outstanding_principal_amount': outstanding_principal,
                    'total_outstanding_amount': total_outstanding_amount,
                    'approved_late_fee_waiver_amount': calculated_approved_waiver['late_fee'],
                    'approved_interest_waiver_amount': calculated_approved_waiver['interest'],
                    'approved_principal_waiver_amount': calculated_approved_waiver['principal'],
                    'total_approved_waiver_amount': total_approved_waiver_amount,
                    'remaining_late_fee_amount': remaining_dict['remaining_late_fee'],
                    'remaining_interest_amount': remaining_dict['remaining_interest'],
                    'remaining_principal_amount': remaining_dict['remaining_principal'],
                    'total_remaining_amount': remaining_amount_total,
                    'total_principal_for_account_payment': principal,
                    'total_interest_for_account_payment': interest,
                    'total_late_fee_for_account_payment': late_fee,
                }
        account_payment_dict = account_payments_dict[account_payment_id]
        if tl_approved_waived_principal > 0 or tl_approved_waived_interest > 0 \
                or tl_approved_waived_late_fee > 0:
            for waiver_payment_level in approved_waived_payment_level_per_account_payment:
                outstanding_principal = waiver_payment_level.outstanding_principal_amount
                outstanding_interest = waiver_payment_level.outstanding_interest_amount
                outstanding_late_fee = waiver_payment_level.outstanding_late_fee_amount
                is_remaining_outstanding_principal = outstanding_principal > 0
                is_remaining_outstanding_interest = outstanding_interest > 0
                is_remaining_outstanding_late_fee = outstanding_late_fee > 0
                is_have_remaining_outstanding = (
                    is_remaining_outstanding_principal,
                    is_remaining_outstanding_interest,
                    is_remaining_outstanding_late_fee)
                # check is payment still have remaining outstanding for substract
                # if not then change to other payment
                if not any(is_have_remaining_outstanding):
                    continue
                # recalculate outstanding, total, account payments, requested
                # because we need arrange the remaining amount to requested waiver
                remaining_principal = 0
                remaining_interest = 0
                remaining_late_fee = 0
                if tl_approved_waived_principal > 0 and is_remaining_outstanding_principal:
                    remaining_principal = tl_approved_waived_principal
                    if outstanding_principal - tl_approved_waived_principal < 0:
                        remaining_principal = outstanding_principal
                    waiver_payment_level.approved_principal_waiver_amount += remaining_principal
                    waiver_payment_level.outstanding_principal_amount -= remaining_principal
                    account_payment_dict['outstanding_principal_amount'] -= remaining_principal
                    account_payment_dict['approved_principal_waiver_amount'] += remaining_principal
                    tl_approved_waived_principal -= remaining_principal
                    if waiver_payment_level.remaining_principal_amount > 0:
                        waiver_payment_level.remaining_principal_amount -= remaining_principal
                    if account_payment_dict['remaining_principal_amount'] > 0:
                        account_payment_dict['remaining_principal_amount'] -= remaining_principal

                if tl_approved_waived_interest > 0 and is_remaining_outstanding_interest:
                    remaining_interest = tl_approved_waived_interest
                    if outstanding_interest - tl_approved_waived_interest < 0:
                        remaining_interest = outstanding_interest
                    waiver_payment_level.approved_interest_waiver_amount += remaining_interest
                    waiver_payment_level.outstanding_interest_amount -= remaining_interest
                    account_payment_dict['outstanding_interest_amount'] -= remaining_interest
                    account_payment_dict['approved_interest_waiver_amount'] += remaining_interest
                    tl_approved_waived_interest -= remaining_interest
                    if waiver_payment_level.remaining_interest_amount > 0:
                        waiver_payment_level.remaining_interest_amount -= remaining_interest
                    if account_payment_dict['remaining_interest_amount'] > 0:
                        account_payment_dict['remaining_interest_amount'] -= remaining_interest

                if tl_approved_waived_late_fee > 0 and is_remaining_outstanding_late_fee:
                    remaining_late_fee = tl_approved_waived_late_fee
                    if outstanding_late_fee - tl_approved_waived_late_fee < 0:
                        remaining_late_fee = outstanding_late_fee
                    waiver_payment_level.approved_late_fee_waiver_amount += remaining_late_fee
                    waiver_payment_level.outstanding_late_fee_amount -= remaining_late_fee
                    account_payment_dict['outstanding_late_fee_amount'] -= remaining_late_fee
                    account_payment_dict['approved_late_fee_waiver_amount'] += remaining_late_fee
                    tl_approved_waived_late_fee -= remaining_late_fee
                    if waiver_payment_level.remaining_late_fee_amount > 0:
                        waiver_payment_level.remaining_late_fee_amount -= remaining_late_fee
                    if account_payment_dict['remaining_late_fee_amount'] > 0:
                        account_payment_dict['remaining_late_fee_amount'] -= remaining_late_fee
                # recalculate total_outstanding_amount, total_requested_waiver_amount,
                # total_remaining_amount because we calculate the remaining diff
                total_remaining_from_agent = remaining_principal + \
                    remaining_interest + remaining_late_fee
                waiver_payment_level.total_outstanding_amount -= total_remaining_from_agent
                waiver_payment_level.total_approved_waiver_amount += total_remaining_from_agent
                waiver_payment_level.total_remaining_amount -= total_remaining_from_agent
                account_payment_dict['total_outstanding_amount'] -= total_remaining_from_agent
                account_payment_dict['total_approved_waiver_amount'] += total_remaining_from_agent
                account_payment_dict['total_remaining_amount'] -= total_remaining_from_agent

        waiver_payment_approval_data.extend(approved_waived_payment_level_per_account_payment)

    for account_payment_id in account_payments_dict:
        account_payment_dict = account_payments_dict[account_payment_id]
        waiver_account_payment_approval_data.append(
            WaiverAccountPaymentApproval(
                waiver_approval=waiver_approval_obj,
                account_payment_id=account_payment_id,
                outstanding_late_fee_amount=account_payment_dict['outstanding_late_fee_amount'],
                outstanding_interest_amount=account_payment_dict['outstanding_interest_amount'],
                outstanding_principal_amount=account_payment_dict['outstanding_principal_amount'],
                total_outstanding_amount=account_payment_dict['total_outstanding_amount'],
                approved_late_fee_waiver_amount=account_payment_dict[
                    'approved_late_fee_waiver_amount'],
                approved_interest_waiver_amount=account_payment_dict[
                    'approved_interest_waiver_amount'],
                approved_principal_waiver_amount=account_payment_dict[
                    'approved_principal_waiver_amount'],
                total_approved_waiver_amount=account_payment_dict['total_approved_waiver_amount'],
                remaining_late_fee_amount=account_payment_dict['remaining_late_fee_amount'],
                remaining_interest_amount=account_payment_dict['remaining_interest_amount'],
                remaining_principal_amount=account_payment_dict['remaining_principal_amount'],
                total_remaining_amount=account_payment_dict['total_remaining_amount'],
            )
        )
    return waiver_payment_approval_data, waiver_account_payment_approval_data


def construct_waiver_request_data_for_cohort_campaign(
    unpaid_account_payments, account, waivers, expired_at, product_line_code, program_name="R4"
):
    first_account_payment = unpaid_account_payments.first()
    last_account_payment = unpaid_account_payments.last()
    bucket_name = 'Bucket {}'.format(first_account_payment.bucket_number)
    total_remaining_late_fee = 0
    total_remaining_interest = 0
    total_remaining_principal = 0
    total_latefee_discount = 0
    total_interest_discount = 0
    total_principal_discount = 0
    unrounded_late_fee_percentage, unrounded_interest_percentage,\
        unrounded_principal_percentage = unrounded_requested_waiver_percentage(waivers)
    for account_payment in unpaid_account_payments:
        payments = Payment.objects.filter(
            account_payment_id=account_payment.id).not_paid_active().order_by('due_date')
        for payment in payments:
            total_remaining_late_fee += payment.remaining_late_fee
            total_remaining_interest += payment.remaining_interest
            total_remaining_principal += payment.remaining_principal
            total_latefee_discount += \
                math.ceil(unrounded_late_fee_percentage * float(payment.remaining_late_fee))
            total_interest_discount += \
                math.ceil(unrounded_interest_percentage * float(payment.remaining_interest))
            total_principal_discount += \
                math.ceil(unrounded_principal_percentage * float(payment.remaining_principal))
    outstanding_amount = total_remaining_late_fee + \
        total_remaining_interest + total_remaining_principal
    total_discount = total_latefee_discount + total_interest_discount + total_principal_discount
    prerequisite_amount = outstanding_amount - total_discount
    return dict(
        account=account,
        is_j1=True,
        first_waived_account_payment=first_account_payment,
        last_waived_account_payment=last_account_payment,
        bucket_name=bucket_name,
        program_name=program_name.lower(),
        is_covid_risky=True,
        outstanding_amount=outstanding_amount,
        unpaid_principal=total_remaining_principal,
        unpaid_interest=total_remaining_interest,
        unpaid_late_fee=total_remaining_late_fee,
        requested_late_fee_waiver_percentage=str(waivers['late_fee_waiver']) + '%',
        requested_late_fee_waiver_amount=total_latefee_discount,
        requested_interest_waiver_percentage=str(waivers['interest_waiver']) + '%',
        requested_interest_waiver_amount=total_interest_discount,
        requested_principal_waiver_percentage=str(waivers['principal_waiver']) + '%',
        requested_principal_waiver_amount=total_principal_discount,
        waiver_validity_date=dateparse.parse_date(expired_at),
        reason=Campaign.COHORT_CAMPAIGN_NAME,
        ptp_amount=prerequisite_amount,
        is_automated=True,
        remaining_amount_for_waived_payment=0,
        partner_product=get_partner_product(product_line_code),
        unrounded_requested_late_fee_waiver_percentage=unrounded_late_fee_percentage,
        unrounded_requested_interest_waiver_percentage=unrounded_interest_percentage,
        unrounded_requested_principal_waiver_percentage=unrounded_principal_percentage
    )


def unrounded_requested_waiver_percentage(waivers):
    unrounded_late_fee_percentage = \
        float("{0:.4f}".format(float(waivers['late_fee_waiver']) / 100))
    unrounded_interest_percentage = \
        float("{0:.4f}".format(float(waivers['interest_waiver']) / 100))
    unrounded_principal_percentage = \
        float("{0:.4f}".format(float(waivers['principal_waiver']) / 100))

    return unrounded_late_fee_percentage, \
        unrounded_interest_percentage, unrounded_principal_percentage
