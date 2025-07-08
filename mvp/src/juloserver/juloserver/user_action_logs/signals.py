import logging

from django.db.models import signals
from django.dispatch import receiver

from juloserver.autodebet.tasks import reactivate_autodebet_validation
from juloserver.user_action_logs.models import MobileUserActionLog
from juloserver.user_action_logs.constants import (
    MobileUserActionLogActivity,
    MobileUserActionLogFragment,
    MobileUserActionLogView,
    MobileUserActionLogEvent,
)


@receiver(signals.post_save, sender=MobileUserActionLog)
def validate_autodebet_reactivation(sender, instance, created, **kwargs):
    if not created:
        return
    
    action_log = instance

    if (action_log.activity == MobileUserActionLogActivity.PAYMENT_METHOD_REVAMP \
        or (action_log.activity == MobileUserActionLogActivity.JULO_ONE_HOME \
        and action_log.fragment == MobileUserActionLogFragment.TRANSACTION_JULO)) \
        and action_log.view == MobileUserActionLogView.AUTODEBET_DEBIT_ACTIVATE \
        and action_log.event == MobileUserActionLogEvent.ONCLICK:
        
        reactivate_autodebet_validation.delay(action_log.app_version, \
            action_log.customer_id)

    return
