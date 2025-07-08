from celery import task
from datetime import datetime
from juloserver.julo.models import (
    Customer,
    FeatureSetting,
)
from juloserver.customer_module.constants import (
    AgentDataChange,
)
from juloserver.customer_module.services.email import (
    send_email_with_html,
    send_reset_phone_number_email,
    send_customer_field_change_bank_account_number_notification,
    send_customer_field_change_email_notification,
    send_customer_field_change_phone_number_notification,
)


@task(queue='high')
def send_email_with_html_task(
    subject: str,
    html_content: str,
    recipient_email: str,
    sender_email: str,
    template_code: str,
    attachments: list = None,
    fullname: str = None,
) -> None:
    """
    Queue task to send email asyncly
    Args:
        subject: email subject
        html_content: email content
        recipient_email: email recipient
        sender_email: email sender
        template_code: email template code
        attachments: list of attachment
        fullname: fullname of recipient
    Returns:
        None
    """

    return send_email_with_html(
        subject=subject,
        html_content=html_content,
        recipient_email=recipient_email,
        sender_email=sender_email,
        template_code=template_code,
        attachments=attachments,
        fullname=fullname,
    )


@task(queue='high')
def send_reset_phone_number_email_task(
    customer: Customer,
    reset_key: str,
) -> None:
    send_reset_phone_number_email(
        customer=customer,
        reset_key=reset_key,
    )

    return


@task(queue='high')
def send_customer_data_change_by_agent_notification_task(
    customer_id: int,
    field_changed: AgentDataChange.Field = None,
    previous_value=None,
    new_value=None,
    recipient_email: str = None,
    timestamp: datetime = None,
) -> None:

    if previous_value == new_value:
        return

    feature_setting = FeatureSetting.objects.filter(
        feature_name=AgentDataChange.feature_name,
        is_active=True,
    ).last()
    if not feature_setting:
        return

    customer = Customer.objects.get(pk=customer_id)

    if not recipient_email and not customer.email:
        return

    if not recipient_email:
        recipient_email = customer.email

    if field_changed == AgentDataChange.Field.Phone:
        send_customer_field_change_phone_number_notification(
            customer=customer,
            previous_value=previous_value,
            new_value=new_value,
            recipient_email=recipient_email,
            timestamp=timestamp,
        )
    elif field_changed == AgentDataChange.Field.Email:
        send_customer_field_change_email_notification(
            customer=customer,
            previous_value=previous_value,
            new_value=new_value,
            recipient_email=recipient_email,
            timestamp=timestamp,
        )
    elif field_changed == AgentDataChange.Field.BankAccountNumber:
        send_customer_field_change_bank_account_number_notification(
            customer=customer,
            previous_value=previous_value,
            new_value=new_value,
            recipient_email=recipient_email,
            timestamp=timestamp,
        )

    return
