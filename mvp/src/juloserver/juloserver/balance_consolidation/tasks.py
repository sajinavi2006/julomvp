import logging
import pytz
from celery import task
from datetime import datetime
from django.utils import timezone

from juloserver.julo.clients import get_julo_pn_client
from juloserver.account.models import Account
from juloserver.julo.models import Image, FeatureSetting
from juloserver.julo.exceptions import JuloException
from juloserver.balance_consolidation.models import BalanceConsolidationVerification
from juloserver.balance_consolidation.constants import (
    BalanceConsolidationStatus,
    FeatureNameConst,
)
from juloserver.julo.statuses import LoanStatusCodes


logger = logging.getLogger(__name__)


@task(queue='loan_normal')
def send_pn_balance_consolidation_verification_status_approved(customer_id):
    action_name = 'balance_consolidation.tasks.send_pn_balance_consolidation_verification_status_approved'
    logger.info({
        'action': action_name,
        'data': {'customer_id': customer_id}
    })
    pn = get_julo_pn_client()
    account = Account.objects.filter(customer_id=customer_id).last()
    application = account.get_active_application()
    gcm_reg_id = application.device.gcm_reg_id
    pn.pn_balance_consolidation_verification_approve(gcm_reg_id)


@task(queue='loan_normal')
def balance_consolidation_upload_signature_image(image_id, customer_id):
    from juloserver.balance_consolidation.services import (
        process_balance_consolidation_upload_signature_image,
    )
    image = Image.objects.get_or_none(pk=image_id)
    if not image:
        raise JuloException("Failed to upload balance consolidation signature. Image ID = %s not found" % image_id)
    process_balance_consolidation_upload_signature_image(image, customer_id)


@task(queue='loan_normal')
def fetch_balance_consolidation_fdc_data():
    balcon_fdc_checking_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BALANCE_CONSOLIDATION_FDC_CHECKING,
        is_active=True
    ).last()
    if not balcon_fdc_checking_fs:
        return

    start_date = balcon_fdc_checking_fs.parameters.get('start_date')
    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()

    today = timezone.localtime(timezone.now()).date()
    candidates_data = (
        BalanceConsolidationVerification.objects
        .filter(
            cdate__date__gte=start_date,
            validation_status=BalanceConsolidationStatus.DISBURSED,
            loan__loan_status__gte=LoanStatusCodes.CURRENT,
            loan__loan_status__lt=LoanStatusCodes.PAID_OFF,
            loan__payment__due_date=today
        )
        .order_by(
            "id", "loan__customer_id",
            "-balanceconsolidationdelinquentfdcchecking__pk"
        )
        .distinct(
            "id", "loan__customer_id"
        )
        .values(
            "id", "loan__customer_id",
            'balanceconsolidationdelinquentfdcchecking__is_punishment_triggered'
        )
    )

    for candidate_data in candidates_data:
        verificiation_id = candidate_data['id']
        customer_id = candidate_data['loan__customer_id']
        is_triggered_punishment = candidate_data[
            'balanceconsolidationdelinquentfdcchecking__is_punishment_triggered'
        ]

        if is_triggered_punishment:
            continue

        fetch_balance_consolidation_fdc_data_for_customer.delay(
            verification_id=verificiation_id,
            customer_id=customer_id
        )


@task(queue='loan_normal')
def fetch_balance_consolidation_fdc_data_for_customer(verification_id, customer_id):
    from juloserver.balance_consolidation.services import (
        get_and_validate_fdc_data_for_balcon_punishments,
    )

    logger.info({
        'action': 'fetch_balance_consolidation_fdc_data_for_customer',
        'message': 'Triggered task to fetch latest FDC data of customer',
        'data': {
            'verification_id': verification_id,
            'customer_id': customer_id
        }
    })

    get_and_validate_fdc_data_for_balcon_punishments(
        verification_id=verification_id,
        customer_id=customer_id
    )
