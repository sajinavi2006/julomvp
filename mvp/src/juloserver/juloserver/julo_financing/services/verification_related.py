import logging
from juloserver.julo_financing.models import JFinancingVerification
from django.db import transaction, DatabaseError
from typing import List

logger = logging.getLogger(__name__)


def lock_j_financing_verification(verification_id: int, agent_id: int) -> bool:
    logger_data = {
        'action': 'lock_j_financing_verification',
        'verification_id': verification_id,
        'agent_id': agent_id,
    }
    try:
        with transaction.atomic():
            verification = JFinancingVerification.objects.select_for_update(nowait=True).get(
                id=verification_id
            )
            if verification.locked_by_id:
                logger.info(
                    {
                        'message': 'The assignment is locked by another agent',
                        'locked_by_id': verification.locked_by_id,
                        **logger_data,
                    }
                )
                return False

            verification.locked_by_id = agent_id
            verification.save(update_fields=['locked_by_id', 'udate'])
            return True

    except DatabaseError:
        logger.warning(
            {
                'message': 'The smartphone financing verification is locked from DB',
                **logger_data,
            },
            exc_info=True,
        )
        return False


def unlock_j_financing_verification(verification_id: int, agent_id: int):
    logger.info(
        {
            'action': 'unlock_j_financing_verification',
            'verification_id': verification_id,
            'agent_id': agent_id,
        }
    )
    JFinancingVerification.objects.filter(pk=verification_id).update(locked_by_id=None)


def get_locked_j_financing_verifications(agent_id: int) -> List[JFinancingVerification]:
    return list(JFinancingVerification.objects.filter(locked_by_id=agent_id).order_by('id').all())
