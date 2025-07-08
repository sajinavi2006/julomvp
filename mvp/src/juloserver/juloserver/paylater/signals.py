import logging

from django.db.models import signals
from django.dispatch import receiver
from django.utils import timezone
from django.db import transaction
from dateutil.relativedelta import relativedelta

from juloserver.julo.statuses import (LoanStatusCodes,
                                      PaymentStatusCodes)
# from juloserver.julo.clients import get_julo_centerix_client

from .models import (TransactionOne,
                     Statement,
                     LoanOne,
                     PaymentSchedule,
                     )
from .services import (generate_loan_one_and_payment,
                       update_loan_one_and_payment,
                       generate_new_statement,
                       generate_statement_history,
                       generate_refund_detail,
                       process_suspend_account
                       )
from .constants import LineTransactionType
from juloserver.julo.models import CootekRobocall
from juloserver.cootek.tasks import cancel_phone_call_for_payment_paid_off

logger = logging.getLogger(__name__)


@receiver(signals.post_save, sender=TransactionOne)
def transaction_postsave_handler(sender, instance, created=False, **kwargs):
    if created is True:
        with transaction.atomic():
            # update limit account_credit_limit
            account_credit_limit = instance.account_credit_limit
            account_credit_limit.update_available_credit_limit(instance)
            account_credit_limit.save(update_fields=['available_credit_limit'])

            statement = instance.statement
            statement.update_statement_amount(instance)

            # invoice
            refund_detail = None
            if instance.transaction_description == LineTransactionType.TYPE_INVOICE.get('name'):
                generate_loan_one_and_payment(instance.id)

            # refund
            elif instance.transaction_description == LineTransactionType.TYPE_REFUND.get('name'):
                refund_detail = generate_refund_detail(instance)

            # refund after paid off
            elif instance.transaction_description == LineTransactionType.TYPE_REFUND_PAID.get('name'):
                refund_detail = generate_refund_detail(instance)
                instance.disbursement_amount += instance.transaction_amount
                instance.save()

            # repayment
            elif instance.transaction_description == LineTransactionType.TYPE_PAYMENT.get('name'):
                # update statement
                late_days = statement.paid_late_days
                grace_period = statement.statement_due_date + relativedelta(day=6, months=1)
                grace_period_timedelta = grace_period - statement.statement_due_date
                grace_period_days = grace_period_timedelta.days

                if late_days <= 0:
                    statement_status = PaymentStatusCodes.PAID_ON_TIME
                elif late_days < grace_period_days:
                    statement_status = PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
                else:
                    statement_status = PaymentStatusCodes.PAID_LATE

                    process_suspend_account(instance.account_credit_limit, late_days, grace_period_days)

                # generate statement history
                generate_statement_history(statement, statement_status, "updated_by_API")
                statement.change_status(statement_status)

            statement.save()
            # cancel phone call
            payment_form_cootek = CootekRobocall.objects.filter(
                statement=statement).last()

            if payment_form_cootek and statement.statement_status_id in \
                    PaymentStatusCodes.paylater_paid_status_codes():
                cancel_phone_call_for_payment_paid_off.delay(payment_form_cootek.id)

            # adjument when do refund for all transaction
            statement.refresh_from_db()
            # refund after paid add disbursement amount with interest fee and late fee
            if instance.transaction_description == LineTransactionType.TYPE_REFUND_PAID.get('name'):
                last_refund_amount = statement.total_refund_by_invoces(invoice=None)
                if last_refund_amount >= statement.statement_principal_amount:
                    # update disbursement amount
                    add_on_disbursement = statement.statement_interest_amount + statement.statement_late_fee_amount
                    instance.disbursement_amount += add_on_disbursement
                    instance.save()
                    # update refund detail
                    refund_detail.refund_amount = instance.disbursement_amount
                    refund_detail.save()

                    # update statement status to paid refund
                    generate_statement_history(statement, PaymentStatusCodes.PAID_REFUND, "updated_by_API")
                    statement.change_status(PaymentStatusCodes.PAID_REFUND)

                    statement_transaction = TransactionOne.objects.filter(
                        statement=statement).exclude(transaction_description='payment')
                    # update date loanone and paymentschedule
                    for transaction_obj in statement_transaction:
                        update_loan_one_and_payment(transaction_obj, instance.transaction_date)

            if instance.transaction_description == LineTransactionType.TYPE_REFUND.get('name'):
                # if principal has to be 0 delete interest fee and late fee
                if statement.statement_principal_amount <= 0:
                    # update statement status to paid refund
                    generate_statement_history(statement, PaymentStatusCodes.PAID_REFUND, "updated_by_API")
                    statement.change_status(PaymentStatusCodes.PAID_REFUND)
                    statement.statement_paid_date = instance.transaction_date

                    statement_transaction = TransactionOne.objects.filter(
                        statement=statement).exclude(transaction_description='payment')
                    # update date loanone and paymentschedule
                    for transaction_obj in statement_transaction:
                        update_loan_one_and_payment(transaction_obj, instance.transaction_date)

            statement.save()

    logger.info({
        'action': 'PaylaterSignal',
        'sender': sender,
        'created': created,
        'instance': instance,
        'data': kwargs
    })
