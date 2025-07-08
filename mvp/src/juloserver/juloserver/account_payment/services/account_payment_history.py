from contextlib import contextmanager

import logging

from ..models import AccountPaymentStatusHistory

logger = logging.getLogger(__name__)


@contextmanager
def update_account_payment_status_history(account_payment, new_status_code, reason=None):
    old_status_code = account_payment.status_id
    yield
    if old_status_code != new_status_code:
        AccountPaymentStatusHistory.objects.create(
            account_payment=account_payment,
            status_old_id=old_status_code,
            status_new_id=new_status_code,
            change_reason=reason
        )
    else:
        logger.info('update account_payment status history called but seem status not changed')
