import json
from typing import (
    Dict,
    Optional,
)
import logging
from datetime import datetime
from django.db import transaction
import time

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    FeatureSetting,
    PaymentMethod,
    Customer,
    Device,
    PaybackTransaction,
)
from juloserver.julo.utils import (
    generate_hex_sha256,
)
from juloserver.julo.payment_methods import PaymentMethodCodes

from juloserver.dana_linking import get_dana_linking_client
from juloserver.dana_linking.constants import (
    DanaWalletAccountStatusConst,
    ErrorMessage,
    ResponseMessage,
)
from juloserver.dana_linking.models import (
    DanaWalletAccount,
    DanaWalletTransaction,
)
from django.utils import timezone

from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.account_payment.models import (
    AccountPayment,
)
from juloserver.account.models import AccountTransaction, Account
from juloserver.dana_linking.utils import add_params_to_url
from juloserver.autodebet.services.dana_services import dana_autodebet_deactivation


logger = logging.getLogger(__name__)


def is_account_whitelisted_for_dana(account):
    whitelist_dana_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_LINKING_WHITELIST, is_active=True
    ).last()

    if not whitelist_dana_feature_setting:
        return True

    application = account.last_application
    if application.id in whitelist_dana_feature_setting.parameters["application_id"]:
        return True

    return False


def is_show_dana_linking(application_id):
    dana_linking_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.DANA_LINKING, is_active=True
    )

    dana_whitelist_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.DANA_LINKING_WHITELIST, is_active=True
    )

    if dana_linking_feature_setting:
        if dana_whitelist_setting:
            if application_id in dana_whitelist_setting.parameters['application_id']:
                return True
            return False
        return True
    return False


def get_dana_onboarding_data():
    feature_settings = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.DANA_LINKING_ONBOARDING, is_active=True
    )

    if not feature_settings:
        return {}, 'Feature setting not found/not active.'

    return feature_settings.parameters, ''


def generate_string_to_sign(headers: Dict, data: Dict, method: str, relative_url: str) -> str:
    body = json.dumps(data, separators=(',', ':'))
    encrypted_data = generate_hex_sha256(body)
    access_token = headers.get('access_token').split(' ')[-1]
    string_to_sign = '%s:%s:%s:%s:%s' % (
        method.upper(),
        relative_url,
        access_token,
        encrypted_data,
        headers.get('x_timestamp'),
    )

    return string_to_sign


def get_dana_balance_amount(
    dana_wallet_account: DanaWalletAccount,
    android_id: str,
    customer_xid: int,
    is_autodebet: bool = False,
    account: Account = None,
    account_payment: AccountPayment = None,
) -> Optional[int]:
    logger.info(
        {
            'action': 'juloserver.dana_linking.services.get_dana_balance_amount',
            'dana_wallet_account_id': dana_wallet_account.id,
        }
    )
    access_token = get_access_token(dana_wallet_account)
    if not access_token:
        logger.warning(
            {
                'action': 'juloserver.dana_linking.services.get_dana_balance_amount',
                'dana_wallet_account_id': dana_wallet_account.id,
                'error': 'invalid access token',
            }
        )
        return
    dana_linking_client = get_dana_linking_client(account, account_payment)
    response_data, error_message = dana_linking_client.check_balance(
        access_token, android_id, customer_xid, is_autodebet
    )
    balance_amount = None
    if not error_message and response_data and "accountInfos" in response_data:
        balance = next(
            (item for item in response_data['accountInfos'] if item['balanceType'] == 'BALANCE'),
            None,
        )
        if not balance:
            logger.warning(
                {
                    'action': 'juloserver.dana_linking.services.get_dana_balance_amount',
                    'dana_wallet_account_id': dana_wallet_account.id,
                    'error': 'no balance found',
                    'response_data': response_data,
                    'error_message': error_message,
                }
            )
        else:
            balance_amount = int(float(balance["availableBalance"]["value"]))

    return balance_amount


def get_access_token(dana_wallet_account: DanaWalletAccount) -> Optional[str]:
    today = timezone.localtime(timezone.now())
    access_token_expiry_time = dana_wallet_account.access_token_expiry_time
    if access_token_expiry_time > today:
        return dana_wallet_account.access_token
    elif dana_wallet_account.refresh_token_expiry_time > access_token_expiry_time:
        access_token = get_new_access_token(dana_wallet_account)
        return access_token
    return


def get_new_access_token(dana_wallet_account: DanaWalletAccount) -> Optional[str]:
    dana_linking_client = get_dana_linking_client(account=dana_wallet_account.account)
    response_data, error_message = dana_linking_client.apply_token(
        "REFRESH_TOKEN", dana_wallet_account.refresh_token
    )
    if error_message:
        logger.warning(
            {
                'action': 'juloserver.dana_linking.services.request_new_access_token',
                'dana_wallet_account_id': dana_wallet_account.id,
                'response_data': response_data,
                'error_message': error_message,
            }
        )
        return
    try:
        access_token_expiry_time = datetime.strptime(
            response_data.get("accessTokenExpiryTime"), "%Y-%m-%dT%H:%M:%S%z"
        )
        refresh_token_expiry_time = datetime.strptime(
            response_data.get("refreshTokenExpiryTime"), "%Y-%m-%dT%H:%M:%S%z"
        )
    except (TypeError, ValueError) as e:
        logger.warning(
            {
                'action': 'juloserver.dana_linking.services.request_new_access_token',
                'dana_wallet_account_id': dana_wallet_account.id,
                'error': 'invalid expiry time',
                'response_data': response_data,
                'error_message': str(e),
            }
        )
        return
    dana_wallet_account.update_safely(
        access_token=response_data.get("accessToken"),
        access_token_expiry_time=access_token_expiry_time,
        refresh_token=response_data.get("refreshToken"),
        refresh_token_expiry_time=refresh_token_expiry_time,
    )
    return response_data.get("accessToken")


def create_dana_payment_method(customer: Customer) -> PaymentMethod:
    last_method = (
        PaymentMethod.objects.only('id', 'sequence')
        .filter(customer=customer, sequence__isnull=False)
        .order_by('-sequence')
        .first()
    )
    sequence = last_method.sequence + 1 if last_method else 1
    payment_method = PaymentMethod.objects.filter(
        payment_method_code=PaymentMethodCodes.DANA,
        payment_method_name="DANA",
        customer=customer,
    ).last()
    if payment_method:
        return payment_method
    payment_method = PaymentMethod.objects.create(
        payment_method_code=PaymentMethodCodes.DANA,
        payment_method_name="DANA",
        customer=customer,
        sequence=sequence,
        is_shown=True,
        is_primary=False,
    )

    return payment_method


def process_dana_repayment(payback_transaction_id: int, data) -> Optional[AccountTransaction]:
    note = 'payment with dana'
    paid_date = datetime.strptime(data['transaction_time'], "%Y-%m-%dT%H:%M:%S%z")

    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.select_for_update().get(
            pk=payback_transaction_id
        )
        if payback_transaction.is_processed:
            return False
        account_payment = payback_transaction.account.get_oldest_unpaid_account_payment()
        j1_refinancing_activation(
            payback_transaction, account_payment, payback_transaction.transaction_date
        )
        process_j1_waiver_before_payment(account_payment, payback_transaction.amount, paid_date)
        payment_processed = process_repayment_trx(payback_transaction, note=note)

    if payment_processed:
        update_moengage_for_payment_received_task.delay(payment_processed.id)

    return payment_processed


def create_debit_payment(
    customer_xid: int,
    amount: int,
    account_payment: AccountPayment,
    dana_wallet_account: DanaWalletAccount,
    android_id: str,
    customer: Customer,
) -> Optional[str]:
    dana_linking_client = get_dana_linking_client()
    account_payment_xid = account_payment.account_payment_xid
    if not account_payment_xid:
        account_payment.update_safely(account_payment_xid=str(time.time()).replace('.', '')[:14])
        account_payment_xid = account_payment.account_payment_xid
    response_data, error_message = dana_linking_client.direct_debit_payment(
        customer_xid, amount, account_payment_xid, account_payment.due_date
    )
    if error_message:
        logger.warning(
            {
                'action': 'juloserver.dana_linking.views.DanaPaymentView',
                'error': error_message,
                'response_data': response_data,
            }
        )
        return
    response_data_ott, error_message_ott = dana_linking_client.apply_ott(
        dana_wallet_account.access_token,
        android_id,
        customer_xid,
    )
    ott = None
    if not error_message_ott and response_data_ott:
        ott = response_data_ott.get('value')
    web_redirect_url = response_data["webRedirectUrl"]
    if ott:
        web_redirect_url = add_params_to_url(web_redirect_url, {'ott': ott}) or web_redirect_url
    with transaction.atomic():
        payment_method = PaymentMethod.objects.filter(
            customer=customer,
            payment_method_code=PaymentMethodCodes.DANA,
        ).last()
        payback_transaction = PaybackTransaction.objects.create(
            transaction_id=response_data["partnerReferenceNo"],
            payback_service="DANA_wallet",
            amount=amount,
            is_processed=False,
            payment_method=payment_method,
            account=account_payment.account,
            customer=account_payment.account.customer,
            transaction_date=timezone.localtime(timezone.now()),
        )
        DanaWalletTransaction.objects.create(
            dana_wallet_account=dana_wallet_account,
            partner_reference_no=response_data["partnerReferenceNo"],
            reference_no=response_data["referenceNo"],
            amount=amount,
            transaction_type="repayment",
            payback_transaction=payback_transaction,
            redirect_url=web_redirect_url,
        )
    return web_redirect_url


def unbind_dana_account_linking(account):
    dana_wallet_account = DanaWalletAccount.objects.filter(
        account=account, status=DanaWalletAccountStatusConst.ENABLED
    ).last()

    if not dana_wallet_account:
        logger.error(
            {
                'action': 'juloserver.dana_linking.services.unbind_dana_account_linking',
                'error': ErrorMessage.DANA_NOT_FOUND,
                'data': {'account_id': account.id},
            }
        )
        return None, ErrorMessage.DANA_NOT_FOUND

    customer = account.customer
    customer_xid = customer.customer_xid
    if not customer_xid:
        customer_xid = customer.generated_customer_xid

    device = Device.objects.filter(customer_id=customer.id).last()
    dana_client = get_dana_linking_client(account=account)

    response, error_message = dana_client.unbind_dana_account(
        dana_wallet_account.access_token, device.android_id, customer_xid
    )

    if response:
        if response['responseCode'] in ['2000900', '4010902', '4010904']:
            logger.info(
                {
                    'action': 'juloserver.dana_linking.services.unbind_dana_account_linking',
                    'message': response['responseMessage'],
                    'data': {'account_id': account.id},
                }
            )
            with transaction.atomic():
                dana_wallet_account.update_safely(status=DanaWalletAccountStatusConst.DISABLED)
                dana_autodebet_deactivation(account)

            return ResponseMessage.DEACTIVATED, None

    logger.error(
        {
            'action': 'juloserver.dana_linking.services.unbind_dana_account_linking',
            'message': error_message if error_message else response['responseMessage'],
            'data': {'account_id': account.id},
        }
    )
    return None, ErrorMessage.GENERAL_ERROR


def fetch_dana_other_page_details(account):
    dana_wallet_account = DanaWalletAccount.objects.filter(
        account=account, status=DanaWalletAccountStatusConst.ENABLED
    ).last()

    if not dana_wallet_account:
        logger.error(
            {
                'action': 'juloserver.dana_linking.services.fetch_other_page_details',
                'error': ErrorMessage.DANA_NOT_FOUND,
                'data': {'account_id': account.id},
            }
        )
        return None, ErrorMessage.DANA_NOT_FOUND

    access_token = get_access_token(dana_wallet_account)
    if not access_token:
        logger.error(
            {
                'action': 'juloserver.dana_linking.services.fetch_other_page_details',
                'error': 'invalid access token',
                'data': {'account_id': account.id},
            }
        )
        return None, 'invalid access token'

    dana_other_url_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_OTHER_PAGE_URL
    ).last()

    if not dana_other_url_feature or not dana_other_url_feature.parameters:
        return None, 'Feature setting not found'

    customer = account.customer
    customer_xid = customer.customer_xid
    if not customer_xid:
        customer_xid = customer.generated_customer_xid

    device = Device.objects.filter(customer_id=customer.id).last()
    dana_client = get_dana_linking_client(account)

    response, error_message = dana_client.apply_ott(access_token, device.android_id, customer_xid)

    if response and response['responseCode'] == '2004900':
        logger.info(
            {
                'action': 'juloserver.dana_linking.services.fetch_other_page_details',
                'message': response['responseMessage'],
                'data': {'account_id': account.id},
            }
        )
        apply_ott_value = response['value']
        response_data = dana_other_url_feature.parameters
        for item in response_data:
            if item['type'] == "link" and item['web_link'] and 'ott=' in item['web_link']:
                item['web_link'] = item['web_link'] + apply_ott_value

        return response_data, None

    logger.error(
        {
            'action': 'juloserver.dana_linking.services.fetch_other_page_details',
            'message': error_message if error_message else response['responseMessage'],
            'data': {'account_id': account.id},
        }
    )
    return None, ErrorMessage.GENERAL_ERROR
