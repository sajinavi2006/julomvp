import logging

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.fraud_security.services import check_login_for_ato_device_change
from juloserver.pii_vault.constants import PiiSource
from juloserver.pin.models import LoginAttempt

logger = logging.getLogger(__name__)


def ato_change_device_on_login_success_handler(sender, **kwargs) -> None:
    """
    The signals handler is attached in juloserver.pin.signals for login_success signal.

    Args:
        sender (str): the sender string name.
        **kwargs (): See event_login_data in "juloserver.pin.services.process_login()"
    Returns:
        None
    """
    login_data = kwargs['login_data']
    customer = kwargs['customer']
    android_id = login_data.get('android_id')
    login_attempt_id = login_data.get('login_attempt_id')
    logger.info(
        {
            'message': 'Run ato_change_device_on_login_success_handler',
            'action': 'ato_change_device_on_login_success_handler',
            'customer_id': customer.id,
            'android_id': android_id,
            'login_attempt_id': login_attempt_id
        }
    )

    # Skip the checking if the required data is not enough.
    if not login_attempt_id or not android_id:
        return

    # Early return and skip ato check if the email is from a julovers account.
    if customer:
        detokenized_customer = detokenize_pii_antifraud_data(
            PiiSource.CUSTOMER, [customer], ['email']
        )[0]
        if detokenized_customer.email:
            is_julo_email = any(
                substring in detokenized_customer.email
                for substring in ['julofinance.com', 'julo.co.id']
            )
            if is_julo_email:
                return

    login_attempt = LoginAttempt.objects.filter(
        is_success=True,
        android_id=android_id,
        customer_id=customer.id,
    ).get(id=login_attempt_id)

    check_login_for_ato_device_change(login_attempt)
