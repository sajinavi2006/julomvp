import logging
from builtins import str
from datetime import datetime, timedelta

from django.db.models import signals
from django.dispatch import receiver
from django.utils import timezone

from juloserver.account.constants import AccountLimitSignal
from juloserver.account.models import (
    Account,
    AccountLimit,
    AccountLimitHistory,
    AccountStatusHistory,
    AccountTransaction,
)
from juloserver.cfs.constants import CfsActionPointsActivity
from juloserver.cfs.services.core_services import tracking_fraud_case_for_action_points
from juloserver.julo.models import AccountingCutOffDate, Device
from juloserver.julo.statuses import JuloOneCodes
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_available_limit_created,
)
from juloserver.julo.tasks import send_pn_invalidate_caching_loans_android

logger = logging.getLogger(__name__)


@receiver(signals.post_init, sender=AccountTransaction)
def include_stored_accounting_date(sender, instance=None, **kwargs):
    instance.__stored_accounting_date = instance.accounting_date


@receiver(signals.pre_save, sender=AccountTransaction)
def add_accounting_date_on_creation(sender, instance=None, **kwargs):
    account_trx = instance

    # This check indicates whether the object is being created for the
    # first time or already exists and being updated. True means created.
    if not account_trx._state.adding:

        # Forbidding accounting date from being updated without update_fields
        if account_trx.__stored_accounting_date != account_trx.accounting_date:
            account_trx.accounting_date = account_trx.__stored_accounting_date
        return
    accounting_cutoff_date = AccountingCutOffDate.objects.all().last()
    if not accounting_cutoff_date:
        return
    cutoff_date = accounting_cutoff_date.cut_off_date.day
    today = timezone.localtime(timezone.now()).date()

    if isinstance(account_trx.transaction_date, str):
        transaction_date = datetime.strptime(account_trx.transaction_date, "%Y-%m-%d").date()
    elif isinstance(account_trx.transaction_date, datetime):
        transaction_date = account_trx.transaction_date.date()
    else:
        transaction_date = account_trx.transaction_date

    first_day_of_this_month = today.replace(day=1)
    if first_day_of_this_month > transaction_date:
        if today.day > cutoff_date:
            account_trx.accounting_date = today
        else:
            last_day_of_previous_month = first_day_of_this_month - timedelta(days=1)
            account_trx.accounting_date = last_day_of_previous_month
    else:
        account_trx.accounting_date = today
    account_trx.__stored_accounting_date = account_trx.accounting_date


@receiver(signals.post_save, sender=AccountLimit)
def record_account_limit_history(sender, instance=None, **kwargs):
    all_fields_dict = dict((f.name, f.attname) for f in AccountLimit._meta.fields)
    updated_account_limit = instance
    histories_to_create = []

    if not kwargs.get('created'):
        update_fields = []
        raw_update_fields = kwargs.get('update_fields') or []
        for field in raw_update_fields:
            if all_fields_dict.get(field):
                update_fields.append(all_fields_dict.get(field))
            else:
                update_fields.append(field)

        fields_change_to_check = update_fields or list(all_fields_dict.values())
        fields_change_to_check = set(fields_change_to_check) - set(
            AccountLimitSignal.NOT_ALLOW_UPDATE_FIELDS
        )
        for field in fields_change_to_check:
            value_old = updated_account_limit.tracker.previous(field)
            value_new = getattr(updated_account_limit, field)
            if field in AccountLimitSignal.FOREIGN_KEY_FIELDS:
                instance.tracker.saved_data[field] = value_new

            if value_old != value_new:
                if field == 'available_limit':
                    execute_after_transaction_safely(
                        lambda: send_user_attributes_to_moengage_for_available_limit_created.delay(
                            updated_account_limit.account.customer,
                            updated_account_limit.account,
                            updated_account_limit.available_limit,
                        )
                    )
                last_history_id = updated_account_limit.latest_affordability_history_id
                histories_to_create.append(
                    AccountLimitHistory(
                        account_limit=updated_account_limit,
                        field_name=field,
                        value_old=str(value_old),
                        value_new=str(value_new),
                        affordability_history_id=last_history_id,
                        credit_score_id=updated_account_limit.latest_credit_score_id,
                    )
                )
    else:
        execute_after_transaction_safely(
            lambda: send_user_attributes_to_moengage_for_available_limit_created.delay(
                updated_account_limit.account.customer,
                updated_account_limit.account,
                updated_account_limit.available_limit,
            )
        )

    if histories_to_create:
        AccountLimitHistory.objects.bulk_create(histories_to_create)


@receiver(signals.pre_save, sender=AccountTransaction)
def update_device_id_on_disbursement(sender, instance=None, **kwargs):
    account_trx = instance
    if account_trx.transaction_type != 'disbursement':
        return
    device = Device.objects.filter(customer=account_trx.account.customer).last()
    if device:
        account_trx.device = device


@receiver(signals.post_init, sender=Account)
def get_data_before_account_updation(sender, instance=None, **kwargs):
    instance.__stored_status_id = instance.status_id


@receiver(signals.post_save, sender=AccountStatusHistory)
def track_frausdster_for_action_points(sender, instance, created, **kwargs):
    if created:
        account_status_history = instance
        status_code = account_status_history.status_new_id
        if status_code == JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD:  # 441
            account = account_status_history.account
            application = account.application_set.last()
            if application.eligible_for_cfs:
                tracking_fraud_case_for_action_points(
                    account=account_status_history.account,
                    activity_id=CfsActionPointsActivity.FRAUDSTER,
                )


@receiver(signals.post_save, sender=Account)
def update_on_account_status_change(sender, instance, created, **kwargs):
    account = instance
    if not created:
        is_trigger_invalidate_caching = account.__stored_status_id != account.status_id and (
            account.__stored_status_id == JuloOneCodes.ACTIVE
            or account.status_id == JuloOneCodes.ACTIVE
        )
        if is_trigger_invalidate_caching:
            execute_after_transaction_safely(
                lambda: send_pn_invalidate_caching_loans_android.delay(
                    account.customer_id, None, None
                )
            )


@receiver(signals.post_save, sender=Account)
def update_user_timezone_account_level(sender, instance, created, **kwargs):
    """
    Signal receiver that updates the user_timezone field of the Account model
    after an instance is saved. why we fill this after data creation is because
    we dont want to impact existing account creation
    """
    if created and not instance.user_timezone:
        from juloserver.account.tasks.account_task import update_user_timezone_async

        update_user_timezone_async.delay(instance.id)
