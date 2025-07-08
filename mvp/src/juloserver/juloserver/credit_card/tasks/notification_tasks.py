from celery import task

from juloserver.julo.clients import get_julo_pn_client
from juloserver.julo.models import Customer
from juloserver.julo.statuses import CreditCardCodes

from juloserver.credit_card.constants import PushNotificationContentsConst
from juloserver.credit_card.models import CreditCardApplication


@task(queue='loan_normal')
def send_pn_status_changed(customer_id: int, new_status: int) -> None:
    customer = Customer.objects.get(pk=customer_id)
    pn_content = PushNotificationContentsConst.STATUSES.get(new_status)
    if not pn_content:
        return

    if new_status == CreditCardCodes.RESUBMIT_SELFIE:
        account = customer.account_set.last()
        credit_card_application = account.creditcardapplication_set.last()
        card_resubmit_selfie_history = credit_card_application.creditcardapplicationhistory_set. \
            filter(
                status_new=CreditCardCodes.RESUBMIT_SELFIE
            ).count()
        if card_resubmit_selfie_history > 3:
            return

    julo_pn_client = get_julo_pn_client()
    julo_pn_client.credit_card_notification(
        customer,
        pn_content['title'],
        pn_content['body'],
        pn_content['template_code'],
    )


@task(queue='loan_high')
def send_pn_change_tenor(customer_id: int) -> None:
    customer = Customer.objects.get(pk=customer_id)
    pn_content = PushNotificationContentsConst.CHANGE_TENOR
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.credit_card_notification(
        customer,
        pn_content['title'],
        pn_content['body'],
        pn_content['template_code'],
        pn_content['destination'],
    )


@task(queue='loan_normal')
def send_pn_transaction_completed(customer_id: int, loan_duration: int, loan_xid: int) -> None:
    customer = Customer.objects.get(pk=customer_id)
    pn_content = PushNotificationContentsConst.TRANSACTION_COMPLETED
    julo_pn_client = get_julo_pn_client()
    destination = "{}/{}".format(pn_content['destination'], loan_xid)
    julo_pn_client.credit_card_notification(
        customer,
        pn_content['title'],
        pn_content['body'].format(loan_duration),
        pn_content['template_code'],
        destination,
    )


@task(queue='loan_high')
def send_pn_incorrect_pin_warning(customer_id: int) -> None:
    customer = Customer.objects.get(pk=customer_id)
    pn_content = PushNotificationContentsConst.INCORRECT_PIN_WARNING
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.credit_card_notification(
        customer,
        pn_content['title'],
        pn_content['body'],
        pn_content['template_code'],
    )


@task(queue='loan_normal')
def send_pn_inform_first_transaction_cashback(
    credit_card_application_id: int, cashback_percentage: int, cashback_max_amount: int
) -> None:
    credit_card_application = CreditCardApplication.objects.get(pk=credit_card_application_id)
    credit_card_transaction = credit_card_application.creditcardtransaction_set.filter(
        loan__isnull=False,
        transaction_status="success"
    ).exists()
    if credit_card_transaction:
        return
    pn_content = PushNotificationContentsConst.INFORM_FIRST_TRANSACTION_CASHBACK
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.credit_card_notification(
        credit_card_application.account.customer,
        pn_content['title'].format(cashback_percentage,
                                   PushNotificationContentsConst.Emoticons.MONEY_MOUTH_FACE),
        pn_content['body'].format(cashback_max_amount),
        pn_content['template_code'],
    )


@task(queue='loan_normal')
def send_pn_obtained_first_transaction_cashback(customer_id: int) -> None:
    customer = Customer.objects.get(pk=customer_id)
    pn_content = PushNotificationContentsConst.OBTAINED_FIRST_TRANSACTION_CASHBACK
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.credit_card_notification(
        customer,
        pn_content['title'],
        pn_content['body'],
        pn_content['template_code'],
        pn_content['destination'],
    )
