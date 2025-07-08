import logging

from django.conf import settings
from celery import task

from juloserver.julo.clients import get_julo_sepulsa_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    FeatureSetting,
    Loan,
)
from juloserver.monitors.notifications import (
    send_message_normal_format,
    send_message_normal_format_to_users,
)
from juloserver.payment_point.constants import SepulsaProductCategory
from juloserver.payment_point.clients import get_julo_sepulsa_loan_client
from juloserver.portal.core.templatetags.unit import format_rupiahs
from juloserver.payment_point.services.train_tasks_related import (
    generate_eticket,
    send_eticket_email,
)

logger = logging.getLogger(__name__)


@task(queue='loan_high')
def send_slack_notification_sepulsa_remaining_balance():
    sepulsa_loan_client = get_julo_sepulsa_loan_client()
    sepulsa_cashback_client = get_julo_sepulsa_client()
    header = "<!here>\n"
    message = "sepulsa_balance_loan : {} \n".format(
        format_rupiahs(sepulsa_loan_client.get_balance(), 'no')
    )
    message += "sepulsa_balance_cashback : {} ".format(
        format_rupiahs(sepulsa_cashback_client.get_balance(), 'no')
    )
    if settings.ENVIRONMENT != 'prod':
        header += "Testing Purpose from {} \n".format(settings.ENVIRONMENT)

    formated_message = "{} ```{}```".format(header, message)
    send_message_normal_format(formated_message, channel='#partner_balance')


@task(queue='loan_high')
def send_slack_notification_sepulsa_balance_reach_minimum_threshold():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.NOTIFICATION_MINIMUM_PARTNER_DEPOSIT_BALANCE,
        is_active=True).first()
    if not feature_setting:
        return

    balance_threshold = feature_setting.parameters['balance_threshold']
    sepulsa_loan_client = get_julo_sepulsa_loan_client()
    sepulsa_cashback_client = get_julo_sepulsa_client()
    sepulsa_loan_balance = sepulsa_loan_client.get_balance()
    sepulsa_cashback_balance = sepulsa_cashback_client.get_balance()
    if sepulsa_loan_balance <= balance_threshold or \
            sepulsa_cashback_balance <= balance_threshold:
        header = "<!here> :fire:\n"
        personal_header = ":fire:\n"
        message = "sepulsa_balance_loan : {} \n".format(
            format_rupiahs(sepulsa_loan_balance, 'no')
        )
        message += "sepulsa_balance_cashback : {} ".format(
            format_rupiahs(sepulsa_cashback_balance, 'no')
        )
        if settings.ENVIRONMENT != 'prod':
            header += "Testing Purpose from {}".format(
                settings.ENVIRONMENT)
            personal_header += "Testing Purpose from {}".format(
                settings.ENVIRONMENT)
        formated_message_for_channel = "{} ```{}```".format(header, message)
        formated_message_for_personal = "{} ```{}```".format(header, message)
        send_message_normal_format(
            formated_message_for_channel, channel='#partner_balance')
        send_message_normal_format_to_users(
            formated_message_for_personal, feature_setting.parameters['users']
        )


@task(queue="loan_normal")
def send_train_ticket_email_task(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.info(
            {
                "task": "send_train_ticket_email_task",
                "path": "juloserver/payment_point/tasks/notificatin_related",
                "respon_data": "Loan not found",
            }
        )
        return

    sepulsa_transaction = loan.sepulsatransaction_set.last()
    if not sepulsa_transaction:
        logger.info(
            {
                "task": "send_train_ticket_email_task",
                "path": "juloserver/payment_point/tasks/notificatin_related",
                "respon_data": "Sepulsa transaction not found",
            }
        )
        return

    if sepulsa_transaction.category != SepulsaProductCategory.TRAIN_TICKET:
        logger.info(
            {
                "task": "send_train_ticket_email_task",
                "path": "juloserver/payment_point/tasks/notificatin_related",
                "respon_data": "Not ticket transaction",
            }
        )
        return
    train_transaction = sepulsa_transaction.traintransaction_set.last()
    generate_eticket(train_transaction)
    send_eticket_email(train_transaction)
