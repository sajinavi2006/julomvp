from juloserver.account.constants import AccountConstant
from juloserver.autodebet.utils import detokenize_sync_primary_object_model
from juloserver.pii_vault.constants import PiiSource
from juloserver.julo.services2.payment_method import get_payment_method_type
from juloserver.julo.models import (
    FeatureSetting,
    PaymentEvent,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.account_payment.models import CheckoutRequest
from juloserver.account_payment.constants import CheckoutRequestCons
from juloserver.account.models import AccountTransaction, PaymentMethodMapping


def get_account_from_payment_method(payment_method):
    customer = payment_method.customer
    if customer is None:
        return None

    account = customer.account
    if account and account.status_id >= AccountConstant.STATUS_CODE.active:
        return account
    return None


def get_payback_services_for_listing():
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.REPAYMENT_PAYBACK_SERVICE_LIST,
    ).last()

    if fs and fs.parameters and fs.parameters.get("include_list"):
        return fs.parameters.get("include_list")

    return None


def get_payment_data_payment_method(payback_transaction):
    payment_event = None
    payment_method = payback_transaction.payment_method

    # Default Return Data
    payment_method_data = {
        "payment_method": {
            "type": "Others",
            "bank_name": None,
            "virtual_account": None,
        },
        "checkout_xid": None,
        "paid_late_fee": None,
    }

    # Cashback Handling
    if payback_transaction.payback_service == "cashback":
        payment_method_data["payment_method"]["type"] = "Cashback"

    account_trx = AccountTransaction.objects.filter(payback_transaction=payback_transaction).last()
    if account_trx:
        payment_method_data["paid_late_fee"] = account_trx.towards_latefee
        payment_event = account_trx.paymentevent_set.last()

    if not payment_event and payback_transaction.transaction_id:
        payment_event = PaymentEvent.objects.filter(
            payment_receipt=payback_transaction.transaction_id,
        ).last()

    if not payment_method and payment_event:
        payment_method = payment_event.payment_method

    if not payment_method:
        return payment_method_data

    if payment_method:
        payment_method_mapping = PaymentMethodMapping.objects.filter(
            payment_method_name=payment_method.payment_method_name
        ).last()
        payment_method_name = payment_method.payment_method_name.replace(' Biller', '').replace(
            ' Tokenization', ''
        )
        payment_method_data["payment_method"]["bank_name"] = (
            payment_method_mapping.visible_payment_method_name
            if payment_method_mapping
            else payment_method_name
        )

    order_payment_methods_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ORDER_PAYMENT_METHODS_BY_GROUPS,
    ).last()
    payment_method_type = get_payment_method_type(payment_method, order_payment_methods_feature)

    if payment_method_type:
        payment_method_data["payment_method"]["type"] = payment_method_type

    if "autodebet" in payback_transaction.payback_service.lower():
        payment_method_data["payment_method"]["type"] = "Autodebet"

    detokenized_payment_method = detokenize_sync_primary_object_model(
        PiiSource.PAYMENT_METHOD,
        payment_method,
        required_fields=['virtual_account'],
    )
    if detokenized_payment_method.virtual_account:
        payment_method_data["payment_method"][
            "virtual_account"
        ] = detokenized_payment_method.virtual_account

    if payment_event:
        checkout = CheckoutRequest.objects.filter(
            payment_event_ids__contains=[payment_event.id]
        ).last()
        if checkout and checkout.status not in [
            CheckoutRequestCons.EXPIRED,
            CheckoutRequestCons.CANCELED,
        ]:
            payment_method_data["checkout_xid"] = checkout.checkout_request_xid

    return payment_method_data
