import logging

from celery import task

from juloserver.account.models import Account
from juloserver.julo.clients import get_julo_pn_client, get_julo_sms_client
from juloserver.julo.models import Application
from juloserver.integapiv1.constants import MAX_TASK_RETRY
from juloserver.julo.models import PaymentMethod


LOGGER = logging.getLogger(__name__)

@task(queue='collection_low')
def send_sms_async(application_id, context, template_code):
    application = Application.objects.get(pk=application_id)
    sms_client = get_julo_sms_client()
    sms_client.send_sms_streamline(template_code=template_code,
                                   context=context,
                                   application=application)


@task(queue='collection_high')
def send_push_notif_async(func_name, args):
    """
    func_name: string corrensponding to instance method name in JuloPNClient
    args: list of arguments, will be passed to the function
    """
    julo_pn_client = get_julo_pn_client()
    getattr(julo_pn_client, func_name)(*args)


@task(queue='repayment_high')
def update_va_bni_transaction(account_id, source, due_amount=0, retry_count=0):
    from juloserver.integapiv1.services import create_or_update_transaction_data_bni
    max_retry = MAX_TASK_RETRY
    account = Account.objects.get_or_none(pk=account_id)

    if retry_count >= max_retry:
        return

    if not account:
        return

    response, error = create_or_update_transaction_data_bni(
        account, source, due_amount, retry_count=retry_count)
    
    error_list = ['Transaction not found', 'payment method not found']
    if error and error not in error_list:
        retry_count += 1
        update_va_bni_transaction.apply_async(
            (account_id, source, due_amount, retry_count), countdown=30*retry_count)


@task(queue='repayment_high')
def create_va_snap_bni_transaction(account_id, source, due_amount=0, retry_count=0):
    from juloserver.integapiv1.services import create_transaction_data_bni

    max_retry = MAX_TASK_RETRY
    account = Account.objects.get_or_none(pk=account_id)

    if retry_count > max_retry:
        return

    if not account:
        return
    
    response, error = create_transaction_data_bni(
        account, source, due_amount, retry_count=retry_count)
    
    error_list = ['Transaction not found', 'payment method not found']
    if error and error not in error_list:
        retry_count += 1
        create_va_snap_bni_transaction.apply_async(
            (account_id, source, due_amount, retry_count), countdown=30 * retry_count
        )


@task(queue='repayment_low', rate_limit='4/s')
def create_va_snap_bni_transaction_retroload(
    account_id, payment_method_id, due_amount=0, retry_count=0
):
    from juloserver.integapiv1.services import create_transaction_data_bni

    max_retry = MAX_TASK_RETRY
    account = Account.objects.get_or_none(pk=account_id)
    source = "bni_va_retroload"

    if retry_count > max_retry:
        return

    if not account:
        return

    response, error = create_transaction_data_bni(
        account, source, due_amount, retry_count, payment_method_id
    )

    if error:
        retry_count += 1
        create_va_snap_bni_transaction_retroload.apply_async(
            (account_id, payment_method_id, due_amount, retry_count), countdown=30 * retry_count
        )
    else:
        # update to is shown true
        payment_method = PaymentMethod.objects.filter(id=payment_method_id).first()
        payment_method.is_shown = True
        payment_method.save()
