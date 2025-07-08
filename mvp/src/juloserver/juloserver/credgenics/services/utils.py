from django.conf import settings
from django.utils import timezone
from typing import (
    Tuple,
    Union,
    List,
)
import pytz
from datetime import datetime
from juloserver.ana_api.models import CredgenicsPoC
from juloserver.account_payment.models import AccountPayment
from juloserver.account.models import Account
from juloserver.julo.models import Application
from juloserver.credgenics.constants.feature_setting import (
    Parameter,
    CommsType,
)
from juloserver.waiver.models import (
    WaiverRequest,
    WaiverAccountPaymentRequest,
)
from juloserver.apiv2.models import (
    PdCollectionModelResult,
)
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest,
)
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Customer
from juloserver.credgenics.constants.csv import CSVFile
import logging

logger = logging.getLogger(__name__)


def get_localtime_now(only_date=False):
    local_tz = pytz.timezone('Asia/Jakarta')
    utc_now = datetime.utcnow()
    local_now = utc_now.replace(tzinfo=pytz.utc).astimezone(local_tz)
    if only_date:
        return local_now.date()

    return local_now


def get_dpd(
    account_payment: AccountPayment,
) -> Union[int, None]:
    """
    Get the DPD of the customer.

    Args:
        customer (Customer): The customer object.
        account_payment (AccountPayment): The account payment object.

    Returns:
        int: The DPD.
    """
    if not account_payment:
        return None

    is_paid = account_payment.is_paid
    if is_paid:
        return 0

    dpd_date = get_localtime_now(only_date=True) - account_payment.due_date

    return dpd_date.days


def get_first_last_name(
    fullname: str,
) -> Tuple[str, str]:
    """ """
    if not fullname:
        return '', ''

    names = list(filter(None, fullname.split(' ')))

    if len(names) == 0:
        return '', ''
    elif len(names) == 1:
        return names[0], ''

    return names[0], names[-1]


def get_title_long(
    title: str,
) -> str:
    """ """
    if not title:
        return ''

    if title.lower() == 'bpk ':
        return 'Bapak '
    elif title.lower() == 'ibu ':
        return 'Ibu '
    else:
        return title


def get_credgenics_customer_ids() -> List[int]:
    """"""
    # TODO: cache for how long?
    return list(CredgenicsPoC.objects.filter().values_list('customer_id', flat=True))


def get_credgenics_account_ids() -> List[int]:
    return list(CredgenicsPoC.objects.filter().values_list('account_id', flat=True))


def get_credgenics_account_payment_ids() -> List[int]:
    """
    TODO: enhance this post-poc, IN query is not efficient
    """

    account_ids = get_credgenics_account_ids()
    if not account_ids:
        return []

    return list(
        AccountPayment.objects.filter(account_id__in=account_ids).values_list('id', flat=True)
    )


def is_credgenics_customer(
    customer_id: int = None,
    customer: Customer = None,
) -> bool:
    if not customer_id and not customer:
        return False

    if customer:
        customer_id = customer.id

    return CredgenicsPoC.objects.filter(customer_id=customer_id).exists()


def is_credgenics_account(
    account: Account = None,
    account_id: int = None,
) -> bool:
    if not account_id and not account:
        return False

    if account:
        account_id = account.id

    return CredgenicsPoC.objects.filter(account_id=account_id).exists()


def is_application_owned_by_credgenics_customer(
    application: Application = None,
    application_id: int = None,
) -> bool:
    if not application_id and not application:
        return False

    if not application:
        customer_id = (
            Application.objects.filter(id=application_id)
            .values_list('customer_id', flat=True)
            .last()
        )
    else:
        customer_id = application.customer_id

    if not customer_id:
        return False

    return is_credgenics_customer(customer_id=customer_id)


def is_account_payment_owned_by_credgenics_customer(
    account_payment: AccountPayment = None,
    account_payment_id: int = None,
) -> bool:
    if not account_payment_id and not account_payment:
        return False

    if not account_payment:
        account_id = (
            AccountPayment.objects.filter(id=account_payment_id)
            .values_list('account_id', flat=True)
            .last()
        )
    else:
        account_id = account_payment.account_id

    return is_credgenics_account(account_id=account_id)


def is_comms_block_active(
    comms_type: CommsType,
) -> bool:
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CREDGENICS_INTEGRATION,
        is_active=True,
    ).last()
    if not fs:
        return False

    comms_params = fs.parameters.get(Parameter.EXCLUDE_COMMS, None)
    if not comms_params:
        return False

    return comms_params.get(comms_type, False)


def is_customer_include_credgenics_repyament(
    customer_id: int,
    account_payment_ids: List[int],
    last_pay_amount: int = None,
    payback_transaction_id: int = None,
) -> bool:
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CREDGENICS_REPAYMENT,
        is_active=True,
    ).last()

    if not fs or not fs.parameters.get(Parameter.INCLUDE_BATCH):
        return False

    credgenics_poc = CredgenicsPoC.objects.filter(
        customer_id=customer_id,
    ).last()

    if credgenics_poc:
        logger.info(
            {
                'action': 'credgenics_repayment_exclude',
                'account_payment_ids': account_payment_ids,
                'customer_id': customer_id,
                'last_pay_amount': last_pay_amount,
                'payback_transaction_id': payback_transaction_id,
                'batch': credgenics_poc.cycle_batch,
                'fs_active': fs.is_active,
                'fs_batch': fs.parameters.get(Parameter.INCLUDE_BATCH),
            }
        )

    if not credgenics_poc or credgenics_poc.cycle_batch not in fs.parameters.get(
        Parameter.INCLUDE_BATCH
    ):
        return False

    return True


def get_csv_name_prefix() -> str:
    if settings.ENVIRONMENT == 'prod':
        return CSVFile.Prefix.PRODUCTION
    elif settings.ENVIRONMENT == 'staging':
        return CSVFile.Prefix.STAGING

    return CSVFile.Prefix.NA


def get_is_risky(account_id: int) -> bool:
    today = timezone.localtime(timezone.now()).date()
    return PdCollectionModelResult.objects.filter(
        account=account_id,
        prediction_date=today,
        model_version__contains='Now or Never',
    ).exists()


def get_all_credgenics_poc_account_id(cycle_batch: List[int]):
    return CredgenicsPoC.objects.filter(cycle_batch__in=cycle_batch).values_list(
        'account_id', flat=True
    )


def get_activated_loan_refinancing_request(start_time, end_time, cycle_batch: List[int]):
    credgenics_poc_account_ids = list(get_all_credgenics_poc_account_id(cycle_batch=cycle_batch))

    return LoanRefinancingRequest.objects.filter(
        account__in=credgenics_poc_account_ids,
        status=CovidRefinancingConst.STATUSES.activated,
        offer_activated_ts__range=[start_time, end_time],
    )


def is_waiver(loan_refinancing_status: str) -> bool:
    waive_principle = [
        CovidRefinancingConst.PRODUCTS.r4,
        CovidRefinancingConst.PRODUCTS.r5,
        CovidRefinancingConst.PRODUCTS.r6,
    ]
    if loan_refinancing_status in waive_principle:
        return True

    return False


def is_refinancing(loan_refinancing_status: str) -> bool:
    refinancing = [
        CovidRefinancingConst.PRODUCTS.r1,
        CovidRefinancingConst.PRODUCTS.r2,
        CovidRefinancingConst.PRODUCTS.r3,
    ]
    if loan_refinancing_status in refinancing:
        return True

    return False


def get_restructure_account_payment_ids(account_id: int, time):
    return AccountPayment.objects.filter(account=account_id, cdate__gte=time)


def get_customer_id_from_account(account_id: int):
    return Account.objects.filter(id=account_id).values_list('customer', flat=True).last()


def get_waiver_account_payment_ids(account_id: int):
    waiver_request_id = (
        WaiverRequest.objects.filter(account=account_id).values_list('id', flat=True).last()
    )

    return WaiverAccountPaymentRequest.objects.filter(waiver_request=waiver_request_id).values_list(
        'account_payment', flat=True
    )
