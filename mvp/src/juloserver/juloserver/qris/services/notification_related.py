from typing import Dict

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.models import Partner
from juloserver.qris.constants import QrisLinkageStatus, AmarRejection
from juloserver.qris.models import QrisPartnerLinkage


def get_partner_extra_moengage_data_to_send(linkage: QrisPartnerLinkage, partner: Partner) -> Dict:
    """
    Extra Data based on qris partners
        - Amar Partner: add "reject_reasons" when status is "failed"
    """
    extra_send_data = {
        "reject_reasons": [],
    }
    if partner.name == PartnerNameConstant.AMAR:
        if linkage.status == QrisLinkageStatus.FAILED:
            # get reject reasons

            # e.g. "selfieHoldingIdCard,editedSelfie,selfieCapturedByOther,zeroLiveness"
            from_amar_reject_reason = linkage.partner_callback_payload['reject_reason']

            # use from_keys() to keep original order of reject codes
            reject_reasons = list(
                dict.fromkeys(
                    AmarRejection.get_message(reason)
                    for reason in from_amar_reject_reason.split(',')
                )
            )

            extra_send_data = {"reject_reasons": reject_reasons}

    return extra_send_data
