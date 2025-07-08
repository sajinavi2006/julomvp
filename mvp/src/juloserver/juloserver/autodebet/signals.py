import logging
from django.db import transaction
from juloserver.autodebet.constants import AutodebetVendorConst
from juloserver.autodebet.models import (
    AutodebetAccount,
    AutodebetBRITransaction,
    AutodebetBRITransactionHistory,
    AutodebetPaymentOffer,
)

from django.dispatch import receiver
from django.db.models import signals
from django.conf import settings
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_realtime_basis,
)
from juloserver.cfs.tasks import handle_cfs_mission
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.autodebet.services.mandiri_services import (
    get_channel_name_slack_autodebet_mandiri_deduction,
)

logger = logging.getLogger(__name__)


@receiver(signals.pre_save, sender=AutodebetAccount)
def alert_on_slack_for_turning_off_autodebet(sender, instance, **kwargs):
    old_instance = AutodebetAccount.objects.filter(account=instance.account).last()
    application_id = instance.account.last_application.id
    if old_instance and old_instance.is_use_autodebet and not instance.is_use_autodebet:
        slack_data_info = str(application_id) + " turned off the autodebit"
        streamer = ''

        if settings.ENVIRONMENT != 'prod':
            streamer = "Testing Purpose from {} \n".format(settings.ENVIRONMENT.upper())

        slack_messages = streamer + slack_data_info

        if old_instance.vendor == AutodebetVendorConst.BCA:
            get_slack_bot_client().api_call(
                "chat.postMessage", channel="#bca-autodebit-alert", text=slack_messages
            )
        elif old_instance.vendor == AutodebetVendorConst.BRI:
            get_slack_bot_client().api_call(
                "chat.postMessage", channel="#bri-autodebit-alert", text=slack_messages
            )
        elif old_instance.vendor == AutodebetVendorConst.GOPAY:
            get_slack_bot_client().api_call(
                "chat.postMessage", channel="#gopay-autodebit-alert", text=slack_messages
            )
        elif old_instance.vendor == AutodebetVendorConst.MANDIRI:
            channel_name = get_channel_name_slack_autodebet_mandiri_deduction()
            get_slack_bot_client().api_call(
                "chat.postMessage", channel=channel_name, text=slack_messages
            )
        elif old_instance.vendor == AutodebetVendorConst.OVO:
            get_slack_bot_client().api_call(
                "chat.postMessage", channel="#ovo-autodebit-alert", text=slack_messages
            )


@receiver(signals.post_save, sender=AutodebetAccount)
def update_moengage_for_is_use_autodebet_change(sender, created, instance=None, **kwargs):
    if created or instance.is_use_autodebet != instance.is_use_autodebet:
        execute_after_transaction_safely(
            lambda: send_user_attributes_to_moengage_for_realtime_basis.apply_async((
                instance.account.customer.id, 'is_use_autodebet'),)
        )
        logger.info('update_moengage_for_is_use_autodebet_change|autodebet_id={}'.format(
            instance.id))


@receiver(signals.post_save, sender=AutodebetBRITransaction)
def tracking_autodebet_bri_transaction_status(sender, instance, created, **_kwargs):
    if not created:
        value_old = instance.tracker.previous("status")
        value_new = instance.status
        if value_old != value_new:
            AutodebetBRITransactionHistory.objects.create(
                old_status=value_old,
                new_status=value_new,
                autodebet_bri_transaction=instance
            )


@receiver(signals.post_save, sender=AutodebetAccount)
def update_status_autodebet_change(sender, created, instance=None, **kwargs):
    status_old = instance.tracker.previous('status')
    status_new = getattr(instance, 'status')
    if status_old == status_new:
        return

    if instance.vendor == AutodebetVendorConst.BCA:
        handle_cfs_mission(instance.account.customer_id, status_new)

    """
    Activate the autodebit.
    Move Application x153 to x190.
    """
    from juloserver.autodebet.constants import AutodebetStatuses
    if status_new == AutodebetStatuses.REGISTERED:
        from juloserver.julo.statuses import ApplicationStatusCodes
        application = instance.account.get_active_application()
        if application.application_status_id == ApplicationStatusCodes.ACTIVATION_AUTODEBET:
            from juloserver.application_flow.services2 import autodebit
            autodebit.activate(application)


@receiver(signals.post_save, sender=AutodebetAccount)
def reset_autodebet_payment_offer(sender, instance, created, **kwargs):
    if created or (
        kwargs.get('update_fields') and 'is_use_autodebet' in kwargs.get('update_fields')
    ):
        if instance.is_use_autodebet is True:
            with transaction.atomic(using="repayment_db"):
                payment_offer = (
                    AutodebetPaymentOffer.objects.select_for_update()
                    .filter(account_id=instance.account_id)
                    .first()
                )

                if payment_offer:
                    payment_offer.counter = -1
                    payment_offer.is_should_show = False
                    payment_offer.save()
