import logging

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from juloserver.account_payment.models import AccountPayment
from juloserver.dana.constants import DanaProductType
from juloserver.dana.models import DanaDialerTemporaryData
from juloserver.julo.models import Application
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.minisquad.constants import DialerSystemConst
from juloserver.partnership.models import PartnershipFeatureSetting
from datetime import timedelta

logger = logging.getLogger(__name__)


def get_bucket_config(feature_name):
    fs = PartnershipFeatureSetting.objects.get(feature_name=feature_name)
    parameters = fs.parameters
    if not parameters:
        logger.info(
            {
                "action": "get_bucket_config",
                "message": "parameters not found",
            }
        )
        return
    return parameters['buckets']


def get_bucket_names(feature_name):
    config = get_bucket_config(feature_name)
    if not config:
        logger.info(
            {
                "action": "get_bucket_names",
                "message": "config not set",
            }
        )
        return
    return [bucket['name'] for bucket in config]


def get_specific_bucket_config(feature_name, bucket_name):
    bucket_configs = get_bucket_config(feature_name)
    if not validate_bucket_configs(bucket_configs):
        logger.info(
            {
                "action": "validate_bucket_configs",
                "message": "bucket configuration not valid",
            }
        )
        return
    for config in bucket_configs:
        if config['name'] == bucket_name:
            return config
    return None


def validate_bucket_configs(bucket_configs):
    false_count = 0
    for config in bucket_configs:
        if config['dpd'].get('to') is None or config['dpd'].get('from') is None:
            false_count += 1

        if config['name'] == DialerSystemConst.DANA_BUCKET_CICIL:
            if not config.get('product_id'):
                false_count += 1
            elif config['product_id'] != DanaProductType.CICIL:
                false_count += 1

        if config['name'] == DialerSystemConst.DANA_BUCKET_CASHLOAN:
            if not config.get('product_id'):
                false_count += 1
            elif config['product_id'] != DanaProductType.CASH_LOAN:
                false_count += 1

    if false_count > 0:
        return False
    else:
        return True


def dana_get_account_payment_base_on_mobile_phone(mobile_phone):
    from juloserver.julo.utils import format_mobile_phone

    current_date = timezone.localtime(timezone.now()).date()

    formatted_main_phone = format_mobile_phone(mobile_phone)
    account_payment_param = None
    account_payments = []

    dana_dialer_temp_datas = DanaDialerTemporaryData.objects.select_related(
        'account_payment'
    ).filter(mobile_number=formatted_main_phone)
    if dana_dialer_temp_datas:
        for ddtd in dana_dialer_temp_datas:
            if ddtd.is_active:
                account_payment_param = ddtd.account_payment
            account_payments.append(ddtd.account_payment)
    # handle if dana_dialer_temporary_data is not found
    else:
        five_days_ago = current_date - timedelta(days=5)

        dacil_prefix = str(ProductLineCodes.DANA)
        cashloan_prefix = str(ProductLineCodes.DANA_CASH_LOAN)

        dacil_account_ids = Application.objects.filter(
            account_id__isnull=False, mobile_phone_1=dacil_prefix + formatted_main_phone
        ).values_list('account_id', flat=True)

        cashloan_account_ids = Application.objects.filter(
            account_id__isnull=False, mobile_phone_1=cashloan_prefix + formatted_main_phone
        ).values_list('account_id', flat=True)

        if not dacil_account_ids and not cashloan_account_ids:
            return None

        account_payments = AccountPayment.objects.filter(is_restructured=False)

        combined_filter = Q()

        if dacil_account_ids:
            combined_filter |= Q(account_id__in=dacil_account_ids, due_date__lt=five_days_ago)

        if cashloan_account_ids:
            combined_filter |= Q(account_id__in=cashloan_account_ids, due_date__lt=current_date)

        account_payments = (
            account_payments.filter(combined_filter)
            .order_by('account', 'due_date', 'id')
            .distinct('account')
        )

        for account_payment in account_payments:
            paid_date = account_payment.paid_date
            if (paid_date and paid_date == current_date) or not paid_date:
                account_payment_param = account_payment

    return account_payment_param, account_payments


def dana_extract_bucket_name_dialer(task_name: str):
    setting_env = settings.ENVIRONMENT.upper()
    bucket_name_extracted = task_name.split('-')
    index = 0
    if setting_env != 'PROD':
        index = 1
    bucket_name = bucket_name_extracted[index]
    if bucket_name in ['DANA_B_ALL', 'DANA_BUCKET_AIRUDDER']:
        return bucket_name
    return '{}-{}'.format(bucket_name, bucket_name_extracted[index + 1])
