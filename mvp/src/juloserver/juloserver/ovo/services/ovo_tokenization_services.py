from datetime import datetime
from typing import Optional, Union

from django.db import transaction
from django.utils import timezone

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.autodebet.models import AutodebetOvoTransaction
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.services import get_oldest_payment_due
from juloserver.julo.services2.payment_method import get_active_loan
from juloserver.ovo.models import (
    OvoWalletAccount,
    OvoWalletBalanceHistory,
    OvoWalletTransaction,
)
from juloserver.account.models import Account, AccountTransaction
from juloserver.julo.clients import get_doku_snap_ovo_client
from juloserver.julo.models import (
    PaymentMethod,
    PaybackTransaction,
)
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.ovo.constants import (
    OvoWalletAccountStatusConst,
    OvoWalletRequestBindingResponseCodeAndMessage,
    OvoWalletTransactionStatusConst,
    OvoPaymentResponseMessage,
    OvoPaymentErrorResponseCodeAndMessage,
    OvoPaymentResponse,
    OvoPaymentType,
)
import logging
from juloserver.julo.payment_methods import OVOTokenizationPaymentMethod
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.autodebet.services.account_services import get_existing_autodebet_account
from juloserver.autodebet.services.autodebet_services import suspend_autodebet_insufficient_balance
from juloserver.autodebet.constants import (
    VendorConst as AutodebetVendorConst,
    OVOErrorCode,
)
from juloserver.autodebet.services.benefit_services import is_eligible_to_get_benefit, give_benefit
from juloserver.autodebet.models import AutodebetBenefit


logger = logging.getLogger(__name__)


def get_ovo_tokenization_onboarding_data():
    feature_settings = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.OVO_TOKENIZATION_ONBOARDING, is_active=True
    )

    if not feature_settings:
        return {}, 'Feature setting not found/not active.'

    return feature_settings.parameters, ''


def get_ovo_wallet_account(auth_code, customer_xid):
    ovo_wallets = OvoWalletAccount.objects.filter(
        auth_code=auth_code,
    ).order_by('-cdate')

    for ovo_wallet in ovo_wallets.iterator():
        account = Account.objects.filter(id=ovo_wallet.account_id).last()
        if account and account.customer.customer_xid == int(customer_xid):
            return ovo_wallet

    return None


def get_ovo_wallet_balance(ovo_wallet_account, is_autodebet=False):
    doku_client = get_doku_snap_ovo_client(
        ovo_wallet_account=ovo_wallet_account,
        account=Account.objects.get_or_none(id=ovo_wallet_account.account_id),
        is_autodebet=is_autodebet,
    )
    response, error_message = doku_client.balance_inquiry()

    if error_message:
        return None, error_message

    balance = ovo_wallet_account.balance or 0
    for account_info in response.get("accountInfos", []):
        if account_info.get("balanceType") == "CASH":
            response_balance = account_info.get("availableBalance", {}).get("value", None)
            if response_balance:
                balance = int(float(response_balance))
                ovo_wallet_account.balance = balance
                ovo_wallet_account.save()
                OvoWalletBalanceHistory.objects.create(
                    ovo_wallet_account=ovo_wallet_account,
                    balance=balance,
                )
            break

    return balance, None


def update_ovo_tokenization_latest_payment_method(account_id):
    account = (
        Account.objects.filter(id=account_id).select_related("customer").only("customer__id").last()
    )
    customer_id = account.customer.id

    ovo_pm = PaymentMethod.objects.filter(
        customer_id=customer_id,
        payment_method_name='OVO',
    ).last()
    if ovo_pm and ovo_pm.is_latest_payment_method:
        ovo_tokenization_pm = PaymentMethod.objects.filter(
            customer_id=customer_id,
            payment_method_name=OVOTokenizationPaymentMethod.name,
        )

        if not ovo_tokenization_pm.exists():
            logger.warning(
                {
                    "action": "juloserver.ovo.services."
                    "ovo_tokenization_services.update_ovo_tokenization_latest_payment_method",
                    "message": "ovo tokenization payment method not found",
                    "account_id": account_id,
                }
            )
            return
        ovo_tokenization_pm.update(is_latest_payment_method=True)
        ovo_pm.is_latest_payment_method = False
        ovo_pm.save()

    return


def request_webview_url(account: Account, phone_number: str):
    ovo_wallet_account = OvoWalletAccount.objects.filter(
        account_id=account.id,
        status=OvoWalletAccountStatusConst.ENABLED,
    )
    ovo_wallet_payment_method = PaymentMethod.objects.filter(
        customer=account.customer,
        payment_method_code=PaymentMethodCodes.OVO_TOKENIZATION,
    )

    if not ovo_wallet_payment_method.exists():
        return None, OvoWalletRequestBindingResponseCodeAndMessage.UNAUTHORIZED

    if ovo_wallet_account.exists():
        return None, OvoWalletRequestBindingResponseCodeAndMessage.ALREADY_REGISTERED

    application = account.last_application
    customer = application.customer
    customer_xid = customer.customer_xid
    if not customer_xid:
        customer_xid = customer.generated_customer_xid

    doku_snap_client = get_doku_snap_ovo_client(ovo_wallet_account, account)
    body = {
        'phone_number': phone_number,
        'customer_xid': customer_xid,
        'success_url': 'https://www.julo.com/ovo-tokenization/success',
        'failed_url': 'https://www.julo.com/ovo-tokenization/failed',
    }
    response_data, error_message = doku_snap_client.ovo_registration_binding(body)
    if error_message:
        doku_response = OvoWalletRequestBindingResponseCodeAndMessage()
        for doku_error_response in doku_response.get_doku_error_responses():
            if error_message == doku_error_response.message:
                return None, doku_error_response

        return None, OvoWalletRequestBindingResponseCodeAndMessage.OvoWalletBindingResponse(
            400, error_message
        )

    auth_code = response_data['additionalInfo']['authCode']
    OvoWalletAccount.objects.create(
        account_id=account.id,
        status=OvoWalletAccountStatusConst.PENDING,
        phone_number=phone_number,
        auth_code=auth_code,
    )

    return {
        'doku_url': response_data['redirectUrl'],
        'success_url': body['success_url'],
        'failed_url': body['failed_url'],
    }, None


def activate_ovo_wallet_account(ovo_wallet):
    doku_snap_client = get_doku_snap_ovo_client(
        ovo_wallet,
        Account.objects.get_or_none(id=ovo_wallet.account_id),
    )
    b2b2c_success = doku_snap_client._get_b2b2c_access_token()

    if not b2b2c_success:
        return None, "Failed to get b2b2c access token"

    # update latest payment method
    update_ovo_tokenization_latest_payment_method(ovo_wallet.account_id)
    ovo_wallet.status = OvoWalletAccountStatusConst.ENABLED
    ovo_wallet.save()

    return ovo_wallet, None


def payment_request(account: Account, ovo_wallet: OvoWalletAccount, amount: int):
    account_payment = account.get_oldest_unpaid_account_payment()
    if not account_payment:
        return None, OvoPaymentErrorResponseCodeAndMessage.BILL_NOT_FOUND

    doku_client = get_doku_snap_ovo_client(ovo_wallet, account, account_payment)
    body = {
        "payment_type": "SALE",
        "partner_reference_number": doku_client.generate_reference_no(),
        "amount": amount,
        "success_url": "https://www.julo.com/ovo-tokenization/payment/success",
        "failed_url": "https://www.julo.com/ovo-tokenization/payment/failed",
    }
    response_data, error_message = doku_client.payment(body)

    if error_message:
        error_response = OvoPaymentResponse(code=400, message=error_message)
        if error_message == OvoPaymentResponseMessage.INSUFFICIENT_BALANCE:
            error_response = OvoPaymentErrorResponseCodeAndMessage.INSUFFICIENT_BALANCE
        elif error_message == OvoPaymentResponseMessage.INVALID_CUSTOMER_TOKEN:
            error_response = OvoPaymentErrorResponseCodeAndMessage.ALREADY_UNLINKED_FROM_APP
        elif error_message == OvoPaymentResponseMessage.MAXIMUM_DEDUCTION_AMOUNT:
            error_response = OvoPaymentErrorResponseCodeAndMessage.MAXIMUM_DEDUCTION_AMOUNT

        return None, error_response

    with transaction.atomic(), transaction.atomic(using="repayment_db"):
        ovo_wallet_payment_method = PaymentMethod.objects.filter(
            customer=account.customer,
            payment_method_code=PaymentMethodCodes.OVO_TOKENIZATION,
        ).last()
        PaybackTransaction.objects.create(
            transaction_id=body["partner_reference_number"],
            payback_service="OVO_Tokenization",
            amount=amount,
            is_processed=False,
            payment_method=ovo_wallet_payment_method,
            account=account,
            customer=account.customer,
            transaction_date=timezone.localtime(timezone.now()),
        )
        OvoWalletTransaction.objects.create(
            ovo_wallet_account=ovo_wallet,
            account_payment_id=account_payment.id,
            partner_reference_no=body["partner_reference_number"],
            reference_no=response_data.get("referenceNo"),
            amount=amount,
            status=OvoWalletTransactionStatusConst.PENDING,
            vendor="doku",
        )

        return_response = {
            "doku_url": response_data["webRedirectUrl"],
            "success_url": body["success_url"],
            "failed_url": body["failed_url"],
        }

        return return_response, None


def ovo_unbinding(account: Account):
    from juloserver.autodebet.constants import AutodebetVendorConst
    from juloserver.autodebet.models import AutodebetAccount
    from juloserver.autodebet.constants import AutodebetStatuses
    ovo_wallet_account = OvoWalletAccount.objects.filter(
        account_id=account.id,
        status=OvoWalletAccountStatusConst.ENABLED,
    ).last()
    if not ovo_wallet_account:
        return None, "Akun OVO Tidak Ditemukan"

    doku_client = get_doku_snap_ovo_client(
        ovo_wallet_account=ovo_wallet_account,
        account=account,
    )
    response, error = doku_client.ovo_unbinding()

    if error:
        # CHECK STATUS ALREADY DISABLED FROM OVO UNLINKED APP
        ovo_wallet_account.refresh_from_db()
        if ovo_wallet_account.status == OvoWalletAccountStatusConst.DISABLED:
            return "Akun OVO Kamu Berhasil Diputuskan", None
        return None, error

    ovo_wallet_account.update_safely(status=OvoWalletAccountStatusConst.DISABLED)
    _filter = {
        "account": account,
        "is_deleted_autodebet": False,
        "vendor": AutodebetVendorConst.OVO,
        "activation_ts__isnull": False,
        "is_use_autodebet": True,
    }
    existing_autodebet_account = AutodebetAccount.objects.filter(**_filter)
    if existing_autodebet_account:
        existing_autodebet_account.update(
            deleted_request_ts=timezone.localtime(timezone.now()),
            deleted_success_ts=timezone.localtime(timezone.now()),
            is_deleted_autodebet=True,
            is_use_autodebet=False,
            status=AutodebetStatuses.REVOKED,
        )
    return "Akun OVO Kamu Berhasil Diputuskan", None


def process_ovo_repayment(
    payback_transaction_id: int,
    paid_datetime: datetime,
    paid_amount: int,
    reference_no: Optional[str],
    latest_transaction_status: str,
    transaction_status_desc: str,
    ovo_transaction: Union[OvoWalletTransaction, AutodebetOvoTransaction],
    payment_type: str,
    account: Optional[Account] = None,
) -> Optional[AccountTransaction]:
    note = 'payment with ovo'

    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.select_for_update().get(
            pk=payback_transaction_id
        )

        if payback_transaction.is_processed:
            return

        if latest_transaction_status != '00':
            # OVO TOKENIZATION
            if payment_type == OvoPaymentType.SALE:
                ovo_transaction.update_safely(
                    reference_no=reference_no, status=transaction_status_desc
                )
            # OVO AUTODEBET
            else:
                ovo_transaction.update_safely(
                    original_reference_no=reference_no,
                    status=transaction_status_desc.upper(),
                )
                # INSUFFICIENT BALANCE
                if (
                    latest_transaction_status == '06'
                    and ovo_transaction.status_desc == OVOErrorCode.INSUFFICIENT_FUND
                    and account
                ):
                    autodebet_account = get_existing_autodebet_account(
                        account, AutodebetVendorConst.OVO
                    )
                    suspend_autodebet_insufficient_balance(
                        autodebet_account, AutodebetVendorConst.OVO
                    )
            return

        loan = get_active_loan(payback_transaction.payment_method)
        payment = get_oldest_payment_due(loan)
        payback_transaction.update_safely(
            amount=paid_amount,
            transaction_date=paid_datetime,
            payment=payment,
            loan=loan,
        )
        account_payment = payback_transaction.account.get_oldest_unpaid_account_payment()
        j1_refinancing_activation(
            payback_transaction, account_payment, payback_transaction.transaction_date
        )
        process_j1_waiver_before_payment(account_payment, payback_transaction.amount, paid_datetime)
        payment_processed = process_repayment_trx(payback_transaction, note=note)

    if payment_processed:
        if payment_type == OvoPaymentType.SALE:
            ovo_transaction.update_safely(
                reference_no=reference_no, status=OvoWalletTransactionStatusConst.SUCCESS
            )
        else:
            ovo_transaction.update_safely(
                original_reference_no=reference_no,
                status=OvoWalletTransactionStatusConst.SUCCESS,
                paid_amount=paid_amount,
                status_desc=transaction_status_desc,
            )

            # GIVE BENEFIT
            benefit = AutodebetBenefit.objects.get_or_none(account_id=account.id)
            if benefit and not ovo_transaction.is_partial and ovo_transaction.is_eligible_benefit:
                if is_eligible_to_get_benefit(account):
                    give_benefit(benefit, account, account_payment)

        update_moengage_for_payment_received_task.delay(payment_processed.id)

    return payment_processed
