import logging
from juloserver.julo.models import CommsBlocked
from juloserver.julo.services import check_comm_type
from juloserver.account_payment.models import AccountPayment

logger = logging.getLogger(__name__)


def check_account_payment_is_blocked_comms(account_payment, comm_type=None):
    comms_block = CommsBlocked.objects.filter(account=account_payment.account).last()
    if not comms_block:
        return False
    impacted_account_payments = comms_block.impacted_payments if comms_block else None
    payment_blocked_dpd_condition = -7 <= account_payment.dpd <= 0 and \
        account_payment.dpd <= comms_block.block_until
    delinquent_condition = True
    for account_payment_id in comms_block.impacted_payments:
        _account_payment = AccountPayment.objects.get(id=account_payment_id)
        if _account_payment.dpd > 0:
            delinquent_condition = False
    comm_type_blocked_condition = check_comm_type(comm_type, comms_block) if comm_type else True
    if comms_block and impacted_account_payments \
            and account_payment.id in impacted_account_payments and payment_blocked_dpd_condition\
            and comm_type_blocked_condition and delinquent_condition:
        logger.info('account_payment_id %s comms is blocked by comms_block_id %s' % (
            account_payment.id, comms_block.id))
        return True

    return False
