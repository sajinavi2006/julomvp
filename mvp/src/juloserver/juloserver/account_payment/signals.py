import logging
import functools
from django.db.models import signals
from django.db import transaction
from django.dispatch import receiver

from juloserver.account_payment.constants import CheckoutRequestCons
from juloserver.account_payment.models import (
    AccountPayment,
    AccountPaymentStatusHistory,
    CheckoutRequest,
    AccountPaymentNote,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.moengage.constants import ACCOUNT_PAYMENT_STATUS_CHANGE_EVENTS
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_realtime_basis,
    update_moengage_for_account_payment_status_change,
)
from django.conf import settings

from juloserver.waiver.services.loan_refinancing_related import get_j1_loan_refinancing_request
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.autodebet.tasks import update_gopay_autodebet_account_subscription
from juloserver.credgenics.tasks.loans import real_time_credgenics_repayment_task
from juloserver.minisquad.tasks import sent_webhook_to_field_collection_service_by_category
from juloserver.pii_vault.collection.tasks import mask_phone_numbers
from juloserver.payback.models import GopayAutodebetTransaction
from juloserver.integapiv1.services import get_bni_payment_method
from juloserver.autodebet.services.task_services import get_due_amount_for_gopay_autodebet_deduction

logger = logging.getLogger(__name__)


def suspendingreceiver(signal, **decorator_kwargs):
    def our_wrapper(func):
        @receiver(signal, **decorator_kwargs)
        @functools.wraps(func)
        def fake_receiver(sender, **kwargs):
            if getattr(settings, 'SUSPEND_SIGNALS', False):
                return
            return func(sender, **kwargs)

        return fake_receiver

    return our_wrapper


@receiver(signals.post_init, sender=AccountPayment)
def get_data_before_account_payment_updation(sender, instance=None, **kwargs):
    instance.__stored_due_amount = instance.due_amount
    instance.__stored_status_id = instance.status_id


@suspendingreceiver(signals.post_save, sender=AccountPayment)
def get_data_after_account_payment_updation(sender, instance=None, created=False, **kwargs):
    account_payment = instance
    try:
        with transaction.atomic():
            if not account_payment._state.adding:
                customer = account_payment.account.customer
                if account_payment.__stored_due_amount != account_payment.due_amount:
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async(
                            (
                                customer.id,
                                'due_amount',
                            ),
                            countdown=settings.DELAY_FOR_REALTIME_EVENTS,
                        )
                    )
                    logger.info(
                        {
                            'action': 'get_data_after_account_payment_updation',
                            'account_payment_id': account_payment.id,
                            'old_due_amount': account_payment.__stored_due_amount,
                            'new_due_amount': account_payment.due_amount,
                        }
                    )

                if account_payment.__stored_status_id != account_payment.status_id:
                    if account_payment.status_id >= PaymentStatusCodes.PAID_ON_TIME:
                        execute_after_transaction_safely(
                            lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async(
                                (
                                    customer.id,
                                    'account_payment_status',
                                ),
                                countdown=settings.DELAY_FOR_REALTIME_EVENTS,
                            )
                        )
                        logger.info(
                            {
                                'action': 'get_data_after_account_payment_updation',
                                'account_payment_id': account_payment.id,
                                'old_status_code': account_payment.__stored_status_id,
                                'new_status_code': account_payment.status_id,
                            }
                        )
    except Exception as e:
        logger.info(
            {
                'action': 'get_data_after_account_payment_updation',
                'account_payment_id': account_payment.id,
                'error_message': e,
            }
        )


@receiver(signals.post_save, sender=AccountPaymentStatusHistory)
def update_moengage_for_status_change(sender, created, instance=None, **kwargs):
    if created and (
        instance.status_new_id in ACCOUNT_PAYMENT_STATUS_CHANGE_EVENTS[0]
        or instance.status_new_id in ACCOUNT_PAYMENT_STATUS_CHANGE_EVENTS[1]
    ):
        if (
            instance.account_payment
            == instance.account_payment.account.get_oldest_unpaid_account_payment()
        ):
            execute_after_transaction_safely(
                lambda: update_moengage_for_account_payment_status_change.apply_async(
                    (instance, instance.status_new_id), countdown=settings.DELAY_FOR_REALTIME_EVENTS
                )
            )
            logger.info(
                {
                    'action': 'get_data_after_account_payment_updation',
                    'account_payment_status_history_id': instance.id,
                }
            )


@receiver(signals.post_save, sender=AccountPayment)
def update_bni_transaction_data(sender, instance, **kwargs):
    if not kwargs.get('update_fields'):
        return

    loan_refinancing_request = get_j1_loan_refinancing_request(instance.account)

    if loan_refinancing_request:
        if loan_refinancing_request.status != CovidRefinancingConst.STATUSES.activated:
            return

    checkout_request = CheckoutRequest.objects.filter(
        account_id=instance.account, status=CheckoutRequestCons.ACTIVE
    ).exists()

    if checkout_request:
        return

    if 'due_amount' in kwargs.get('update_fields'):
        if not instance.account:
            return
        _, is_bni_payment_method_exist = get_bni_payment_method(instance.account)
        if is_bni_payment_method_exist:
            oldest_account_payment = (
                instance.account.accountpayment_set.not_paid_active()
                .order_by('due_date')
                .only('id')
                .first()
            )
            if (
                oldest_account_payment
                and oldest_account_payment.id != instance.id
                and instance.due_amount > 0
            ):
                return
            execute_after_transaction_safely(
                lambda: update_va_bni_transaction.delay(
                    instance.account.id,
                    'account_payment.signals.update_bni_transaction_data',
                )
            )

    logger.info(
        {
            'action': 'account_payment.signals.update_bni_transaction_data',
            'account_payment_id': instance.id,
        }
    )


@receiver(signals.post_save, sender=AccountPayment)
def update_gopay_autodebet_subscription(sender, instance, **kwargs):
    if not kwargs.get('update_fields'):
        return

    if 'due_amount' in kwargs.get('update_fields'):
        if not instance.account:
            return
        gopay_autodebet_transaction = (
            GopayAutodebetTransaction.objects.filter(
                customer=instance.account.customer,
                is_active=True,
            )
            .only('id', 'amount')
            .last()
        )
        if not gopay_autodebet_transaction:
            return
        due_amount = get_due_amount_for_gopay_autodebet_deduction(instance.account)
        if due_amount == gopay_autodebet_transaction.amount:
            return

        execute_after_transaction_safely(
            lambda: update_gopay_autodebet_account_subscription.delay(
                instance.account.id,
            )
        )

    logger.info(
        {
            'action': 'account_payment.signals.update_gopay_autodebet_subscription',
            'account_payment_id': instance.id,
        }
    )


# @receiver(signals.pre_save, sender=AccountPayment)
def update_credgenics_repayment(sender, instance, **kwargs):
    if not kwargs.get('update_fields'):
        return

    if 'paid_amount' not in kwargs.get('update_fields'):
        return

    credgenics_amount = 0
    if not instance.pk:
        credgenics_amount = instance.paid_amount
    else:
        old_paid_amount = (
            AccountPayment.objects.filter(id=instance.id)
            .values_list('paid_amount', flat=True)
            .last()
        )
        new_paid_amount = instance.paid_amount
        credgenics_amount = new_paid_amount - old_paid_amount

    if credgenics_amount == 0:
        return

    execute_after_transaction_safely(
        lambda: real_time_credgenics_repayment_task.delay(
            instance.account.id, instance.id, instance.due_date, credgenics_amount
        )
    )

    logger.info(
        {
            'action': 'account_payment.signals.update_credgenics_repayment',
            'account_payment_id': instance.id,
            'amount': credgenics_amount,
        }
    )


@receiver(signals.post_save, sender=AccountPayment)
def update_field_collection_debtor(sender, instance, **kwargs):
    if not kwargs.get('update_fields'):
        return

    if 'due_amount' in kwargs.get('update_fields'):
        execute_after_transaction_safely(
            lambda: sent_webhook_to_field_collection_service_by_category.delay(
                category='transaction',
                account_xid=instance.account.id,
            )
        )

    logger.info(
        {
            'action': 'account_payment.signals.update_field_collection_debtor',
            'account_payment_id': instance.id,
        }
    )


@receiver(signals.post_save, sender=AccountPaymentNote)
def mask_phone_number_post_save(sender, instance=None, created=False, **kwargs):
    signals.post_save.disconnect(mask_phone_number_post_save, sender=AccountPaymentNote)
    if instance.note_text:
        mask_phone_numbers.delay(
            instance.note_text, 'note_text', AccountPaymentNote, instance.id, False
        )

    if instance.extra_data:
        mask_phone_numbers.delay(
            instance.extra_data, 'extra_data', AccountPaymentNote, instance.id, True
        )

    signals.post_save.connect(mask_phone_number_post_save, sender=AccountPaymentNote)
