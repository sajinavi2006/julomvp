import operator
from django.utils import timezone
from juloserver.julo.services2.sepulsa import SepulsaService

from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.loan_refinancing.services.loan_related import \
    is_point_blocked_by_collection_repayment_reason
from juloserver.loyalty.constants import (
    FeatureNameConst,
    PointHistoryChangeReasonConst,
    PointRedeemReferenceTypeConst,
    PointExchangeUnitConst,
    PointExpiredReminderConst,
    RedemptionMethodErrorCode
)
from juloserver.julo.models import FeatureSetting, SepulsaProduct
from juloserver.loyalty.models import LoyaltyPoint, PointUsageHistory, \
    LoyaltyGopayTransferTransaction
from juloserver.julo.utils import display_rupiah
from juloserver.loyalty.services.services import (
    update_customer_total_points,
    get_point_history_change_reason,
    get_point_reminder_config,
    get_amount_deduct,
    get_point_expiry_info,
    get_non_locked_loyalty_point,
)
from juloserver.julo.point_repayment_services import point_payment_process_account
from juloserver.loyalty.utils import convert_point_to_rupiah, convert_rupiah_to_point, \
    get_convert_rate_from_point_to_rupiah
from juloserver.loyalty.exceptions import (
    PointTransferException,
    LoyaltyGopayTransferNotFoundException,
    DanaException,
    SepulsaInsufficientError,
)
from juloserver.payment_point.constants import SepulsaProductType, SepulsaProductCategory


def pay_next_loan_payment(customer):
    with db_transactions_atomic({
        *DbConnectionAlias.transaction(),
        DbConnectionAlias.REPAYMENT,
        DbConnectionAlias.COLLECTION}
    ):
        loyalty_point = LoyaltyPoint.objects.select_for_update().get(customer_id=customer.id)

        notes = ('-- Customer Trigger by App -- \n' +
                 'Amount Redeemed Rupiah : %s, \n') % (
            display_rupiah(loyalty_point.total_point))

        exchange_amount = convert_point_to_rupiah(loyalty_point.total_point)
        status, payback_transaction, used_wallet_amount = point_payment_process_account(
            customer.account, notes, exchange_amount
        )
        point_amount = 0
        if status:
            point_amount = convert_rupiah_to_point(used_wallet_amount)
            reason = get_point_history_change_reason(
                PointHistoryChangeReasonConst.POINT_REPAYMENT, point_deduct=used_wallet_amount
            )
            process_deduct_point(
                loyalty_point=loyalty_point,
                exchange_amount=used_wallet_amount,
                point_amount=point_amount,
                reference_id=payback_transaction.id,
                reason=reason,
                reference_type=PointRedeemReferenceTypeConst.REPAYMENT,
                exchange_amount_unit=PointExchangeUnitConst.RUPIAH,
            )
        loyalty_point.refresh_from_db()
        return status, loyalty_point.total_point, used_wallet_amount, point_amount


def process_deduct_point(loyalty_point, exchange_amount, point_amount, reference_id,
                         reason, reference_type, exchange_amount_unit, extra_data=None):
    customer_id = loyalty_point.customer_id
    _, point_history = update_customer_total_points(
        customer_id=customer_id,
        customer_point=loyalty_point,
        point_amount=point_amount,
        reason=reason,
        adding=False
    )
    # exchange_amount round down in case odd number
    puh_dict = {
        "reference_type": reference_type,
        "reference_id": reference_id,
        "point_amount": point_amount,
        "exchange_amount": exchange_amount,
        "exchange_amount_unit": exchange_amount_unit,
        "point_history_id": point_history.id
    }
    if extra_data:
        puh_dict["extra_data"] = extra_data
    return PointUsageHistory.objects.create(**puh_dict)


def get_convert_rate_info():
    from_point_to_rupiah = get_convert_rate_from_point_to_rupiah()
    return PointExchangeUnitConst.Message.CONVERT_RATE_INFO.format(
        convert_rate=from_point_to_rupiah
    )


def get_data_point_information(customer):
    # Get customer point
    loyalty_point = get_non_locked_loyalty_point(customer_id=customer.id)
    total_point = loyalty_point.total_point

    # Get point expiry reminder
    expiry_info = get_point_expiry_info(customer, loyalty_point)

    # Get available redemption methods
    redemption_methods = get_available_redemption_methods(customer, total_point)
    data = dict(
        total_point=total_point,
        redemption_methods=redemption_methods
    )
    if expiry_info:
        data['point_expiry_info'] = expiry_info
    return data


def get_available_redemption_methods(customer, total_point):
    """
        Retrieve available redemption methods from feature settings
    """
    point_redeem_fs = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.POINT_REDEEM
    )
    fs_parameters = getattr(point_redeem_fs, "parameters", {})

    redemption_methods = []
    for method, params in fs_parameters.items():
        is_valid, _ = is_eligible_redemption_method(
            method=method, params=params, customer=customer
        )
        if not is_valid:
            continue
        redemption_methods.append(
            construct_redemption_method_data_response(
                method=method,
                params=params,
                customer=customer,
                total_point=total_point
            )
        )

    return sorted(
        redemption_methods,
        key=operator.itemgetter("is_default"),
        reverse=True
    )


def construct_redemption_method_data_response(method, params, customer, total_point):
    general_info = get_redemption_method_general_info(method=method, params=params)

    if method == PointRedeemReferenceTypeConst.REPAYMENT:
        return {
            **general_info,
            **get_repayment_method_point_info(
                params=params, customer=customer, total_point=total_point
            )
        }
    else:
        return {
            **general_info,
            **get_transfer_method_pricing_info(
                method=method, params=params, total_point=total_point
            )
        }


def get_redemption_method_general_info(method, params):
    return dict(
        redemption_method=method,
        name=params['name'],
        tag_info=params['tag_info'],
        icon=params['icon'],
        is_default=params['is_default'],
        is_valid=True
    )


def get_repayment_method_point_info(params, customer, total_point):
    """
        Return specific info for repayment method
    """
    account = customer.account
    minimum_withdrawal = params['minimum_withdrawal']
    point_reminder_config = get_point_reminder_config()
    point_amount_deduction = get_amount_deduct(account, total_point)
    point_usage_info = point_reminder_config.get(
        'point_usage_info', PointExpiredReminderConst.Message.POINT_USAGE_INFO
    )

    return dict(
        point_usage_info=point_usage_info,
        total_point_deduction=point_amount_deduction,
        minimum_withdrawal=minimum_withdrawal,
    )


def get_transfer_method_pricing_info(method, params, total_point):
    """
        Return specific info for GoPay/DANA transfer method
    """
    if method == PointRedeemReferenceTypeConst.DANA_TRANSFER:
        product = get_sepulsa_instant_transfer_to_dana_product()
        partner_fee = product.partner_price
    elif method == PointRedeemReferenceTypeConst.GOPAY_TRANSFER:
        partner_fee = params['partner_fee']
    else:
        raise RedemptionMethodErrorCode.UNAVAILABLE_METHOD

    admin_fee = params['julo_fee'] + partner_fee
    minimum_withdrawal = params['minimum_withdrawal']
    minimum_nominal_amount = max(admin_fee, minimum_withdrawal)
    maximum_nominal_amount = convert_point_to_rupiah(total_point)

    return dict(
        admin_fee=admin_fee,
        minimum_nominal_amount=minimum_nominal_amount,
        maximum_nominal_amount=maximum_nominal_amount,
        detail_fees=dict(
            julo_fee=params['julo_fee'],
            partner_fee=partner_fee
        )
    )


def check_eligible_redemption_method(method, customer):
    point_redeem_fs = FeatureSetting.objects.get(feature_name=FeatureNameConst.POINT_REDEEM)
    params = point_redeem_fs.parameters.get(method, {})

    return is_eligible_redemption_method(
        method=method, params=params, customer=customer
    )


def is_eligible_redemption_method(method, params, customer):
    account =  customer.account
    if not (params and params.get('is_active')):
        return False, RedemptionMethodErrorCode.UNAVAILABLE_METHOD

    if method == PointRedeemReferenceTypeConst.REPAYMENT:
        is_point_blocked = is_point_blocked_by_collection_repayment_reason(account.id)
        if is_point_blocked:
            return False, RedemptionMethodErrorCode.BLOCK_DEDUCTION_POINT

    elif method == PointRedeemReferenceTypeConst.DANA_TRANSFER:
        is_valid_whitelist = check_loyalty_transfer_dana_whitelist(customer.id)
        if not is_valid_whitelist:
            return False, RedemptionMethodErrorCode.UNAVAILABLE_METHOD

        product = get_sepulsa_instant_transfer_to_dana_product()
        if not product:
            return False, RedemptionMethodErrorCode.UNAVAILABLE_METHOD

    return True, None


def get_point_transfer_bottom_sheet_information(method, gross_nominal_amount, customer):
    """
        Validate transfer method availability and inputted nominal amount.
        Return bottom sheet information:
            - gross_nominal_amount
            - point_amount
            - admin_fee
            - net_nominal_amount
    """
    _, error_code = check_eligible_redemption_method(
        method=method, customer=customer
    )
    if error_code:
        raise PointTransferException(error_code)

    loyalty_point = LoyaltyPoint.objects.get(customer_id=customer.id)
    total_point = loyalty_point.total_point
    data, error_code = validate_transfer_method_nominal_amount(
        method=method, gross_nominal_amount=gross_nominal_amount, total_point=total_point
    )
    if error_code:
        raise PointTransferException(error_code)

    point_amount = convert_rupiah_to_point(gross_nominal_amount)
    return {
        'gross_nominal_amount': gross_nominal_amount,
        'point_amount': point_amount,
        **data,
    }


def validate_transfer_method_nominal_amount(method, gross_nominal_amount, total_point):
    """
        Validate transfer method availability and inputted nominal amount
        Return:
            - data: dict(admin_fee, net_nominal_amount)
            - error_code: str
    """
    point_redeem_fs = FeatureSetting.objects.get(feature_name=FeatureNameConst.POINT_REDEEM)
    params = point_redeem_fs.parameters.get(method, {})
    pricing_info = get_transfer_method_pricing_info(method, params, total_point)
    min_nominal = pricing_info['minimum_nominal_amount']
    max_nominal = pricing_info['maximum_nominal_amount']
    if not min_nominal <= gross_nominal_amount <= max_nominal:
        return None, RedemptionMethodErrorCode.INVALID_NOMINAL_AMOUNT

    admin_fee = pricing_info['admin_fee']
    net_nominal_amount = gross_nominal_amount - admin_fee

    if net_nominal_amount <= 0:
        return None, RedemptionMethodErrorCode.INSUFFICIENT_AMOUNT

    data = dict(
        admin_fee=admin_fee,
        net_nominal_amount=net_nominal_amount,
        detail_fees=pricing_info['detail_fees']
    )
    return data, None


def create_loyalty_gopay_transfer_transaction(customer, net_amount, bank, nominal,
                                              mobile_phone_number):
    from juloserver.disbursement.services.gopay import GopayConst
    return LoyaltyGopayTransferTransaction.objects.create(
        customer_id=customer.id,
        transfer_amount=net_amount,
        redeem_amount=nominal,
        bank_name=bank.bank_name,
        bank_code=bank.bank_code,
        bank_number=mobile_phone_number,
        name_in_bank=customer.fullname,
        partner_transfer=GopayConst.BANK_CODE,
    )


def deduct_point_before_transfer_to_gopay(loyalty_point, transfer, nominal, extra_data):
    return process_deduct_point(
        loyalty_point=loyalty_point,
        exchange_amount=nominal,
        point_amount=convert_rupiah_to_point(nominal),
        reference_id=transfer.id,
        reason=get_point_history_change_reason(
            reason=PointHistoryChangeReasonConst.GOPAY_TRANSFER
        ),
        reference_type=PointRedeemReferenceTypeConst.GOPAY_TRANSFER,
        exchange_amount_unit=PointExchangeUnitConst.RUPIAH,
        extra_data=extra_data
    )


def get_loyalty_gopay_transfer_trx(transfer_id):
    from juloserver.disbursement.services.gopay import GopayConst
    return LoyaltyGopayTransferTransaction.objects.filter(
        transfer_id=transfer_id).exclude(
        transfer_status__in=GopayConst.PAYOUT_END_STATUS
    ).last()


def update_gopay_transfer_data(gopay_transfer, update_data: dict):
    gopay_transfer.update_safely(**update_data)


def process_refunded_transfer_loyalty_point_to_gopay(gopay_transfer):
    loyalty_point = LoyaltyPoint.objects.get(customer_id=gopay_transfer.customer_id)
    update_customer_total_points(
        customer_id=loyalty_point.customer_id,
        customer_point=loyalty_point,
        point_amount=convert_rupiah_to_point(gopay_transfer.redeem_amount),
        reason=get_point_history_change_reason(
            reason=PointHistoryChangeReasonConst.REFUNDED_GOPAY_TRANSFER
        ),
        adding=True
    )


def process_callback_gopay_transfer(gopay_transfer, callback_data):
    from juloserver.disbursement.services.gopay import GopayConst

    transfer_status = callback_data['status']
    update_data = {
        'transfer_status': transfer_status
    }
    if transfer_status == GopayConst.PAYOUT_STATUS_COMPLETED:
        update_data['fund_transfer_ts'] = timezone.now()
        update_gopay_transfer_data(gopay_transfer, update_data)

    elif transfer_status == GopayConst.PAYOUT_STATUS_FAILED:
        update_data['failure_code'] = callback_data['error_code']
        update_data['failure_message'] = callback_data['error_message']
        update_gopay_transfer_data(gopay_transfer, update_data)
        process_refunded_transfer_loyalty_point_to_gopay(gopay_transfer)


def construct_data_response_success_gopay_transfer(gopay_transfer, point_usage_history):
    from juloserver.disbursement.services.gopay import GopayConst
    response = {
        "id": gopay_transfer.id,
        "transfer_status": gopay_transfer.transfer_status,
        "nominal_amount": gopay_transfer.redeem_amount,
        "transfer_amount": gopay_transfer.transfer_amount,
        "admin_fee": gopay_transfer.redeem_amount - gopay_transfer.transfer_amount,
        "point_amount": point_usage_history.point_amount,
        "mobile_phone_number": gopay_transfer.bank_number,
    }
    if gopay_transfer.transfer_status == GopayConst.PAYOUT_STATUS_COMPLETED:
        response['fund_transfer_ts'] = gopay_transfer.fund_transfer_ts
    return response


def get_loyalty_gopay_transfer_transaction(gopay_transfer_id, customer_id):
    obj = LoyaltyGopayTransferTransaction.objects.get_or_none(
        id=gopay_transfer_id, customer_id=customer_id
    )
    if not obj:
        raise LoyaltyGopayTransferNotFoundException
    return obj


def get_point_usage_history_by_reference(reference_type, reference_id):
    return PointUsageHistory.objects.filter(
        reference_type=reference_type,
        reference_id=reference_id
    ).last()


def get_sepulsa_instant_transfer_to_dana_product():
    return SepulsaProduct.objects.filter(
        type=SepulsaProductType.E_WALLET_OPEN_PAYMENT, category=SepulsaProductCategory.DANA,
        is_active=True
    ).last()


def process_transfer_loyalty_point_to_dana(customer, nominal, mobile_phone_number):
    product = get_sepulsa_instant_transfer_to_dana_product()
    if not product:
        raise DanaException(RedemptionMethodErrorCode.UNAVAILABLE_METHOD)

    sepulsa_service = SepulsaService()
    is_enough = sepulsa_service.is_balance_enough_for_transaction(nominal)
    if not is_enough:
        raise DanaException(RedemptionMethodErrorCode.UNAVAILABLE_METHOD)

    with db_transactions_atomic(DbConnectionAlias.utilization()):
        loyalty_point = LoyaltyPoint.objects.select_for_update(
            nowait=True
        ).get(customer_id=customer.id)

        total_point = loyalty_point.total_point
        data_pricing, error_code = validate_transfer_method_nominal_amount(
            PointRedeemReferenceTypeConst.DANA_TRANSFER, nominal, total_point
        )
        if error_code:
            raise SepulsaInsufficientError(error_code)

        customer_price_regular = data_pricing['net_nominal_amount']
        is_success = sepulsa_service.julo_sepulsa_client.inquiry_ewallet_open_payment_transaction(
            mobile_phone_number=mobile_phone_number, product_code=product.product_id,
            amount=customer_price_regular
        )
        if not is_success:
            raise DanaException(RedemptionMethodErrorCode.UNAVAILABLE_METHOD)

        sepulsa_transaction = sepulsa_service.create_transaction_sepulsa(
            customer, product,
            phone_number=mobile_phone_number,
            customer_price_regular=customer_price_regular,
            partner_price=product.partner_price,
        )
        point_usage_history = deduct_point_before_transfer_to_dana(
            loyalty_point, sepulsa_transaction, nominal, extra_data=data_pricing['detail_fees']
        )
    response = sepulsa_service.julo_sepulsa_client.create_transaction(sepulsa_transaction)

    sepulsa_transaction = sepulsa_service.update_sepulsa_transaction_with_history_accordingly(
        sepulsa_transaction, 'create_transaction', response)
    if sepulsa_transaction.transaction_status == 'failed':
        process_refunded_transfer_loyalty_point_to_dana(
            sepulsa_transaction, point_usage_history
        )
        raise DanaException(RedemptionMethodErrorCode.UNAVAILABLE_METHOD)

    return sepulsa_transaction, point_usage_history



def process_refunded_transfer_loyalty_point_to_dana(sepulsa_transaction, point_usage_history):
    loyalty_point = LoyaltyPoint.objects.get(customer_id=sepulsa_transaction.customer_id)
    update_customer_total_points(
        customer_id=loyalty_point.customer_id,
        customer_point=loyalty_point,
        point_amount=convert_rupiah_to_point(point_usage_history.exchange_amount),
        reason=get_point_history_change_reason(
            reason=PointHistoryChangeReasonConst.REFUNDED_DANA_TRANSFER
        ),
        adding=True
    )


def deduct_point_before_transfer_to_dana(loyalty_point, sepulsa_transaction, nominal, extra_data):
    return process_deduct_point(
        loyalty_point=loyalty_point,
        exchange_amount=nominal,
        point_amount=convert_rupiah_to_point(nominal),
        reference_id=sepulsa_transaction.id,
        reason=get_point_history_change_reason(
            reason=PointHistoryChangeReasonConst.DANA_TRANSFER
        ),
        reference_type=PointRedeemReferenceTypeConst.DANA_TRANSFER,
        exchange_amount_unit=PointExchangeUnitConst.RUPIAH,
        extra_data=extra_data
    )


def construct_data_response_success_dana_transfer(sepulsa_transaction, point_usage_history):
    transfer_status = sepulsa_transaction.transaction_status
    extra_data = point_usage_history.extra_data
    partner_price = extra_data.get("julo_fee", 0) + extra_data.get("partner_fee", 0)
    transfer_amount = sepulsa_transaction.customer_price_regular
    response = {
        "id": sepulsa_transaction.id,
        "transfer_status": transfer_status,
        "nominal_amount": transfer_amount + partner_price,
        "transfer_amount": transfer_amount,
        "admin_fee": partner_price,
        "point_amount": point_usage_history.point_amount,
        "mobile_phone_number": sepulsa_transaction.phone_number,
    }
    if transfer_status == 'success':
        response['fund_transfer_ts'] = sepulsa_transaction.transaction_success_date
    return response


def check_and_refunded_transfer_dana(sepulsa_transaction):
    if sepulsa_transaction.transaction_status == 'failed':
        dana_transfer_point_usage = get_point_usage_history_by_reference(
            PointRedeemReferenceTypeConst.DANA_TRANSFER,
            sepulsa_transaction.id,
        )
        if dana_transfer_point_usage:
            process_refunded_transfer_loyalty_point_to_dana(
                sepulsa_transaction, dana_transfer_point_usage
            )


def check_loyalty_transfer_dana_whitelist(customer_id):
    whitelist_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_TRANSFER_WHITELIST_CUST, is_active=True
    ).last()
    if whitelist_fs:
        whitelist_customer_ids = whitelist_fs.parameters.get('customer_ids', [])
        return customer_id in whitelist_customer_ids
    return True
