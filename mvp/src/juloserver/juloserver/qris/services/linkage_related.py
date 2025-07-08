import logging
from typing import Tuple

from juloserver.qris.constants import QrisLinkageStatus
from juloserver.qris.models import QrisPartnerLinkage, QrisPartnerLinkageHistory, QrisUserState


logger = logging.getLogger(__name__)


def get_linkage(customer_id: int, partner_id: int) -> QrisPartnerLinkage:
    """
    Get User QRIS Linkage data
    """
    linkage = (
        QrisPartnerLinkage.objects.filter(
            customer_id=customer_id,
            partner_id=partner_id,
        )
        .select_related('qris_user_state')
        .last()
    )
    return linkage


def get_user_state(linkage_id: int) -> QrisUserState:
    """
    Get User QRIS linkage state data
    """
    state = QrisUserState.objects.filter(
        qris_partner_linkage_id=linkage_id,
    ).last()

    return state


def get_or_create_linkage(customer_id: int, partner_id: int) -> Tuple[QrisPartnerLinkage, bool]:
    """
    Use this function when need to get or create linkage
    """

    linkage, is_created = QrisPartnerLinkage.objects.get_or_create(
        customer_id=customer_id,
        partner_id=partner_id,
    )

    # if create, create history
    if is_created:
        default_status = QrisLinkageStatus.REQUESTED
        QrisPartnerLinkageHistory.objects.create(
            qris_partner_linkage_id=linkage.id,
            field='status',
            value_old='',
            value_new=default_status,
        )

    return linkage, is_created
