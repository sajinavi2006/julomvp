import logging
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from juloserver.followthemoney.constants import LenderStatus
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.followthemoney.models import LenderCurrent
from juloserver.qris.constants import QrisLinkageStatus
from juloserver.qris.exceptions import NoQrisLenderAvailable
from juloserver.qris.models import (
    QrisLinkageLenderAgreement,
    QrisPartnerLinkage,
    QrisPartnerLinkageHistory,
    QrisPartnerTransactionHistory,
    QrisUserState,
)
from juloserver.qris.services.feature_settings import QrisMultipleLenderSetting
from juloserver.qris.services.linkage_related import get_linkage


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def create_linkage_history(
    linkage_id: int, field: str, old_value: str, new_value: str, reason: str = 'system_triggered'
):
    QrisPartnerLinkageHistory.objects.create(
        qris_partner_linkage_id=linkage_id,
        field=field,
        value_old=old_value,
        value_new=new_value,
        change_reason=reason,
    )


def create_transaction_history(
    transaction_id: int,
    field: str,
    old_value: str,
    new_value: str,
    reason: str = 'system_triggered',
):

    QrisPartnerTransactionHistory.objects.create(
        qris_partner_transaction_id=transaction_id,
        field=field,
        value_old=old_value,
        value_new=new_value,
        change_reason=reason,
    )


def retroload_blue_finc_lender_qris_lender_agreement(batch_size=400):
    """
    ONE TIME retroload existing qris user with blue finc lender
    when first add multiple lender feature
    https://juloprojects.atlassian.net/browse/LOL-3140

    DO THIS BEFORE releasing multiple lender feature to prod users

    Consider running manually to avoid slowing down deployment
    """

    logger.info(
        {
            "action": "retroload_blue_finc_lender_qris_lender_agreement",
            "message": "starting to retroload old qris blue-finc-lender agreement",
        }
    )

    blue_finc_lender = LenderCurrent.objects.get(lender_name='blue_finc_lender')

    # in case run again if error
    already_retroloaded_linkages = QrisLinkageLenderAgreement.objects.filter(
        lender_id=blue_finc_lender.id,
    ).values_list('qris_partner_linkage_id', flat=True)

    # find already signed state
    already_signed_user_states = QrisUserState.objects.filter(
        signature_image__isnull=False,
        master_agreement_id__isnull=False,
    ).exclude(
        qris_partner_linkage_id__in=already_retroloaded_linkages,
    )

    blue_finc_agreements = []
    for state in already_signed_user_states:
        agreement = QrisLinkageLenderAgreement(
            qris_partner_linkage_id=state.qris_partner_linkage_id,
            lender_id=blue_finc_lender.id,
            signature_image_id=state.signature_image_id,
            master_agreement_id=state.master_agreement_id,
        )

        blue_finc_agreements.append(agreement)

    QrisLinkageLenderAgreement.objects.bulk_create(objs=blue_finc_agreements, batch_size=batch_size)

    logger.info(
        {
            "action": "retroload_blue_finc_lender_qris_lender_agreement",
            "message": "finished retroloading old blue finc lender agreement",
        }
    )


def get_current_available_qris_lender(linkage: QrisPartnerLinkage = None) -> LenderCurrent:
    """
    Get available lender for QRIS
    Criteria:
    - Must have sufficient balance
    - Active lender is prioritized
    - If all lenders unactive, get first lender with money
    Special case: linkage not active yet, return first lender when no available lender

    """
    is_linkage_active = False
    if linkage and linkage.status == QrisLinkageStatus.SUCCESS:
        is_linkage_active = True

    fs = QrisMultipleLenderSetting()

    lender_names_by_prioprity = fs.lender_names_ordered_by_priority
    out_of_balance_threshold = fs.out_of_balance_threshold

    # get lenders & their balances
    lenders = LenderCurrent.objects.filter(
        lender_name__in=lender_names_by_prioprity,
    ).select_related('lenderbalancecurrent')

    # sorted based on prioprity set-up in FS
    sorted_lenders_by_priority = sorted(
        lenders,
        key=lambda x: lender_names_by_prioprity.index(x.lender_name),
    )

    # get default as first configured lender
    default_lender = sorted_lenders_by_priority[0]

    for lender in sorted_lenders_by_priority:
        is_lender_active = lender.lender_status == LenderStatus.ACTIVE
        is_lender_balance_enough = (
            lender.lenderbalancecurrent.available_balance >= out_of_balance_threshold
        )

        if is_lender_active and is_lender_balance_enough:
            return lender

    # no good lender found, lets look at default lender
    if is_linkage_active:
        # after user has signed and started making transactions
        # as long as default lender has money, we accept
        if default_lender.lenderbalancecurrent.available_balance >= out_of_balance_threshold:
            return default_lender
    else:
        # before user has signed and started making transactions
        # always return default
        return default_lender

    sentry_client.captureMessage(
        {
            "message": "Qris Lender out of money or not active, please configure/top-up",
            "action": "juloserver.qris.services.core_services.get_current_available_qris_lender",
            "current_config_lenders": lender_names_by_prioprity,
            "out_of_money_threshold": out_of_balance_threshold,
            "default lender": default_lender,
            "default lender balance": default_lender.lenderbalancecurrent.available_balance,
        }
    )
    raise NoQrisLenderAvailable


def is_qris_linkage_signed_with_lender(linkage_id: int, lender_id: int) -> bool:
    return QrisLinkageLenderAgreement.objects.filter(
        qris_partner_linkage_id=linkage_id,
        lender_id=lender_id,
    ).exists()


def is_qris_customer_signed_with_lender(customer_id: int, partner_id: int, lender_id: int) -> bool:
    linkage = get_linkage(
        customer_id=customer_id,
        partner_id=partner_id,
    )

    if not linkage:
        return False

    return is_qris_linkage_signed_with_lender(linkage_id=linkage.id, lender_id=lender_id)


def has_linkage_signed_with_current_lender(
    linkage: Optional[QrisPartnerLinkage],
) -> Tuple[bool, LenderCurrent]:
    """
    Params:
    - linkage: can also pass None

    Return current available qris lender & whether linkage has signed agreement with it
    """
    current_lender = get_current_available_qris_lender(linkage=linkage)

    if not linkage:
        return False, current_lender

    is_already_signed = is_qris_linkage_signed_with_lender(
        linkage_id=linkage.id,
        lender_id=current_lender.id,
    )
    return is_already_signed, current_lender


def get_qris_lender_from_lender_name(lender_name) -> LenderCurrent:
    """
    Get lender object from lender name for QRIS
    """

    fs = QrisMultipleLenderSetting()

    is_lender_set_up = fs.is_lender_name_set_up(lender_name)

    if not is_lender_set_up:
        return None

    lender = LenderCurrent.objects.get_or_none(lender_name=lender_name)
    return lender


def is_success_linkage_older_than(seconds_since_success: int, linkage_id: int) -> bool:
    """
    Check if linkage has been success more than X amount of seconds
    That means it will be expired for the qris progress bar
    """
    now = timezone.localtime(timezone.now())
    cutoff_datetime = now - timezone.timedelta(seconds=seconds_since_success)

    # check if older than input SECONDs
    exists = QrisPartnerLinkageHistory.objects.filter(
        qris_partner_linkage_id=linkage_id,
        field='status',
        value_new=QrisLinkageStatus.SUCCESS,
        cdate__lt=cutoff_datetime,
    ).exists()

    return exists


def update_linkage_status(linkage: QrisPartnerLinkage, to_status: str) -> bool:
    """
    Only update field 'status'
    """

    current_status = linkage.status
    # check if status path is valid
    is_valid = QrisLinkageStatus.amar_status_path_check(
        from_status=current_status,
        to_status=to_status,
    )

    is_success = False

    if is_valid:
        with transaction.atomic():
            # update status & create history
            linkage = QrisPartnerLinkage.objects.select_for_update().get(
                id=linkage.id,
            )

            current_status = linkage.status
            # check is_valid again case concurrent callback
            is_valid = QrisLinkageStatus.amar_status_path_check(
                from_status=current_status,
                to_status=to_status,
            )
            if not is_valid:
                return False

            linkage.status = to_status
            linkage.save(update_fields=['status'])

            create_linkage_history(
                linkage_id=linkage.id,
                field='status',
                old_value=current_status,
                new_value=to_status,
            )

            is_success = True

    logger.info(
        {
            "action": "juloserver.qris.services.linkage_related.update_linkage_status",
            "message": "update qris linkage status",
            "customer_id": linkage.customer_id,
            "linkage_id": linkage.id,
            "old status": current_status,
            "new status": to_status,
            "is_success": is_success,
            "is_valid": is_valid,
        }
    )

    return is_success
