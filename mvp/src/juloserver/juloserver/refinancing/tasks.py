import logging
from celery import task

from juloserver.account.models import Account
from juloserver.account.constants import AccountConstant
from juloserver.account.services.account_related import process_change_account_status
from juloserver.refinancing.services import update_account_property_for_refinancing

logger = logging.getLogger(__name__)


@task(queue='collection_normal')
def update_account_for_paid_off_after_refinanced(account_id):
    logger.info(
        {
            'action': 'update_account_for_paid_off_after_refinanced',
            'account_id': account_id,
        }
    )
    account = Account.objects.get(id=account_id)
    process_change_account_status(
        account, AccountConstant.STATUS_CODE.suspended, 'refinancing cool off period'
    )
    update_account_property_for_refinancing(
        account, dict(refinancing_ongoing=False, is_proven=False)
    )
