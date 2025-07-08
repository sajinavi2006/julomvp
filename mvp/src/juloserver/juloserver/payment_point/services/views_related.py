from builtins import str
from datetime import datetime
from typing import Dict, List, Union

from juloserver.julo.constants import MobileFeatureNameConst
from juloserver.julo.models import Customer, MobileFeatureSetting, MobileOperator, SepulsaProduct
from juloserver.loan.services.loan_related import (
    is_customer_can_do_zero_interest,
    is_product_locked_and_reason,
    get_lock_info_in_app_bottom_sheet,
)
from juloserver.loan.constants import DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST
from juloserver.payment_point.constants import (
    FeatureNameConst,
    SepulsaProductType,
    SepulsaProductCategory,
    TransactionMethodCode,
    SepulsaMessage,
)
from juloserver.payment_point.exceptions import NoMobileOperatorFound, NoProductForCreditMatrix
from juloserver.payment_point.models import AYCProduct, TransactionMethod, XfersProduct
from juloserver.payment_point.services.ewallet_related import (
    is_applied_ayc_switching_flow,
    is_applied_xfers_switching_flow,
)
import juloserver.payment_point.utils as payment_point_utils
from juloserver.julo.clients.sepulsa import SepulsaResponseCodes, SepulsaHTTPCodes
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
)
from juloserver.loan.services.loan_related import get_credit_matrix_and_credit_matrix_product_line
from juloserver.account.models import (
    Account,
    AccountLimit,
)


def construct_data_inquiry_electricity(raw_data, category):
    if 'subscriber_id' in raw_data:
        subscriber_id = raw_data['subscriber_id']
    else:
        subscriber_id = raw_data['material_number']
    data = dict(
        subscriber_id=subscriber_id,
        subscriber_name=raw_data['subscriber_name'],
        subscriber_segmentation=raw_data['subscriber_segmentation'],
        admin_charge=raw_data['admin_charge'],
        amount=None,
        bills=None
    )

    if category == 'postpaid':
        data['amount'] = raw_data['amount']
        bills = []
        for bill in raw_data['bills']:
            bills.append(dict(
                bill_period=datetime.strptime(
                    bill['bill_period'] + '01', '%Y%m%d'
                ).strftime('%Y-%m-%d'),
                produk=bill['produk'],
                due_date=datetime.strptime(
                    bill['due_date'], '%Y%m%d'
                ).strftime('%Y-%m-%d'),
                total_electricity_bill=bill['total_electricity_bill'],
                penalty_fee=int(bill['penalty_fee']),
            ))
        data['bills'] = bills

    return data


def construct_transaction_method_for_android(account,
                                             transaction_method,
                                             is_proven,
                                             lock_colour,
                                             application_direct=None,
                                             account_limit_direct=None,
                                             highlight_setting_direct=None,
                                             product_lock_in_app_bottom_sheet=None,
                                             device_ios_user=None):
    # this function update support lock for android & iOS
    def check_is_transaction_method_highlighted():

        # check highlight_setting from CreditInfo
        highlight_setting = highlight_setting_direct or MobileFeatureSetting.objects.get_or_none(
            is_active=True, feature_name=FeatureNameConst.TRANSACTION_METHOD_HIGHLIGHT)

        if not highlight_setting:
            return False
        highlight = False
        if highlight_setting:
            parameters = highlight_setting.parameters
            method_setting = parameters.get(str(transaction_method.id))
            if not method_setting:
                return False
            if method_setting.get('is_active'):
                # For optimize CreditInfo V2 need bypass account limit for root class
                account_limit = account_limit_direct or account.accountlimit_set.last()

                available_limit = account_limit.available_limit
                if method_setting.get('limit_threshold') is not None:
                    if available_limit >= method_setting['limit_threshold']:
                        highlight = True
        return highlight

    is_locked, reason_locked = is_product_locked_and_reason(
        account, transaction_method.id, application_direct, device_ios_user
    )
    if (
        application_direct
        and application_direct.status == ApplicationStatusCodes.ACTIVATION_AUTODEBET
    ):
        is_locked = False

    foreground_icon = transaction_method.foreground_locked_icon_url
    background_icon = None

    is_new = False
    if not is_locked:
        foreground_icon = transaction_method.foreground_icon_url
        if transaction_method.id in TransactionMethodCode.new_products():
            is_new = True
        if check_is_transaction_method_highlighted():
            background_icon = transaction_method.background_icon_url

    campaign_name = get_campaign_name(
        is_locked=is_locked,
        account=account,
        transaction_method=transaction_method,
    )

    response = {
        "is_locked": is_locked,
        "reason_locked": reason_locked,
        "is_partner": False,
        "code": transaction_method.id,
        "name": transaction_method.fe_display_name,
        "foreground_icon": foreground_icon,
        "background_icon": background_icon,
        "lock_colour": lock_colour,
        "is_new": is_new,
        "campaign": campaign_name,
    }
    if is_locked:
        response['lock_in_app_bottom_sheet'] = get_lock_info_in_app_bottom_sheet(
            reason_locked, product_lock_in_app_bottom_sheet
        )
    return response


def get_campaign_name(
    is_locked: bool, account: Account, transaction_method: TransactionMethod
) -> str:
    """
    Logic for getting campaign name for constructing transaction method data for android
    """

    campaign = DEFAULT_CAMPAIGN_NAME = ""

    if is_locked:
        return DEFAULT_CAMPAIGN_NAME

    if account:
        customer = account.customer
        is_zero_interest_eligible, _ = is_customer_can_do_zero_interest(
            customer, transaction_method.id
        )
        if is_zero_interest_eligible:
            campaign = DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST

        campaign = get_campaign_from_transaction_method(
            method_id=transaction_method.id,
            campaign=campaign,
        )

    return campaign


def get_campaign_from_transaction_method(method_id: int, campaign: str = "") -> str:
    """
    Get campaign name based on transaction method code
    """

    fs = (
        MobileFeatureSetting.objects.filter(
            feature_name=MobileFeatureNameConst.TRANSACTION_METHOD_CAMPAIGN,
            is_active=True,
        )
        .exclude(parameters__isnull=True)
        .last()
    )

    if fs:
        campaign = fs.parameters.get(str(method_id), campaign)

    return campaign


def validate_data_and_get_sepulsa_product(data, serializer, product_type, category):
    serializer = serializer(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.data
    query_filter = {'type': product_type,
                    'is_active': True,
                    'is_not_blocked': True,
                    'category': category,
                    }
    if 'product_id' in data:
        query_filter['id'] = data['product_id']

    sepulsa_product = SepulsaProduct.objects.filter(**query_filter).last()

    return data, sepulsa_product


def get_pdam_sepulsa_product(product_code, product_name):
    sepulsa_product = SepulsaProduct.objects.filter(
        product_name__icontains=product_name,
        product_desc=product_code,
        type=SepulsaProductType.PDAM,
        category=SepulsaProductCategory.WATER_BILL,
        is_active=True,
    ).last()
    return sepulsa_product


def get_error_message(response_code, product_type, status_code=None):

    # An error occurred, data is invalid
    response_code = str(response_code)

    error_message = SepulsaMessage.INVALID
    if status_code in [SepulsaHTTPCodes.FORBIDDEN,
                       SepulsaHTTPCodes.DUPLICATE_ORDER_ID,
                       SepulsaHTTPCodes.MISSING_OR_UNACCEPTABLE_DATA]:
        return error_message
    elif status_code == SepulsaHTTPCodes.PRODUCT_CLOSED_TEMPORARILY \
            or response_code == str(SepulsaHTTPCodes.PRODUCT_CLOSED_TEMPORARILY):
        # The product is being updated, please try again later
        return SepulsaMessage.PRODUCT_CLOSED_TEMPORARILY

    if product_type == SepulsaProductType.TRAIN_TICKET:
        error_message = None
        if response_code == SepulsaResponseCodes.TRAIN_ROUTE_NOT_FOUND:
            error_message = SepulsaMessage.TRAIN_ROUTE_NOT_FOUND
        if response_code in SepulsaResponseCodes.TRAIN_TICKET_ERROR_RESPONSE:
            error_message = SepulsaMessage.GENERAL_ERROR_TRAIN_TICKET
    elif SepulsaResponseCodes.WRONG_NUMBER == response_code:
        if product_type in (SepulsaProductType.MOBILE, SepulsaProductType.EWALLET):
            identifier = SepulsaMessage.WRONG_NUMBER_MOBILE_EWALLET
        elif product_type == SepulsaProductType.BPJS:
            identifier = SepulsaMessage.WRONG_NUMBER_BPJS
        elif product_type == SepulsaProductType.ELECTRICITY:
            identifier = SepulsaMessage.WRONG_NUMBER_ELECTRICITY
        error_message = '{} tidak terdaftar'.format(identifier)
    elif SepulsaResponseCodes.BILL_ALREADY_PAID == response_code:
        error_message = SepulsaMessage.BILL_ALREADY_PAID
    elif SepulsaResponseCodes.PRODUCT_ISSUE == response_code:
        error_message = SepulsaMessage.PRODUCT_ISSUE
    elif response_code == SepulsaResponseCodes.GENERAL_ERROR \
            and product_type == SepulsaProductType.MOBILE:
        error_message = SepulsaMessage.GENERAL_ERROR_MOBILE

    if response_code == SepulsaResponseCodes.READ_TIMEOUT:
        error_message = SepulsaMessage.READ_TIMEOUT_ERROR
    return error_message


def construct_ewallet_categories_response(categories: List[str]) -> List[Dict]:
    """
    construct reponse data for ewallet categories API
    """
    data = []
    for cat in categories:
        data.append(
            {
                "category_name": cat.capitalize(),
                "category_logo": payment_point_utils.get_ewallet_logo(cat),
                "category_code": cat,
            }
        )

    return data


def calculate_available_limit(data, account: Account) -> int:
    """
    For PaymentProduct API View
    """
    account_limit = AccountLimit.objects.filter(account=account).last()
    application = account.get_active_application()
    transaction_method_id = data.get('transaction_type_code', None)
    transaction_type = None
    if transaction_method_id:
        transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
        if transaction_method:
            transaction_type = transaction_method.method
    credit_matrix, _ = get_credit_matrix_and_credit_matrix_product_line(
        application, True, None, transaction_type
    )

    if not credit_matrix.product:
        raise NoProductForCreditMatrix

    provision_fee = account_limit.available_limit * credit_matrix.product.origination_fee_pct
    available_limit = account_limit.available_limit - provision_fee

    return available_limit


def get_sepulsa_products(data: Dict, account: Account) -> List[SepulsaProduct]:
    """
    Get sepulsa products for PaymentProduct API View
    """
    query_filter = dict(
        type=data['type'], category=data['category'], is_active=True, is_not_blocked=True
    )
    if account and data['category'] not in SepulsaProductCategory.POSTPAID:
        available_limit = calculate_available_limit(data=data, account=account)
        query_filter['customer_price_regular__lte'] = available_limit

    if data['mobile_operator_id']:
        mobile_operator = MobileOperator.objects.get_or_none(pk=data['mobile_operator_id'])
        if not mobile_operator:
            raise NoMobileOperatorFound

        query_filter['operator'] = mobile_operator

    products = SepulsaProduct.objects.filter(**query_filter).order_by('customer_price_regular')

    return list(products)


def get_ayc_products(data: Dict, account: Account) -> List[AYCProduct]:
    """
    Get ayoconnect products for PaymentProduct API View
    """
    query_filter = dict(
        type=data['type'],
        category=data['category'],
        is_active=True,
    )

    if account:
        available_limit = calculate_available_limit(data=data, account=account)
        query_filter['customer_price_regular__lte'] = available_limit

    products = AYCProduct.objects.filter(**query_filter).order_by('customer_price_regular')

    return list(products)


def get_xfers_products(data: Dict, account: Account) -> List[XfersProduct]:
    """
    Get xfers products for PaymentProduct API View
    """
    query_filter = dict(
        type=data['type'],
        category=data['category'],
        is_active=True,
    )

    if account:
        available_limit = calculate_available_limit(data=data, account=account)
        query_filter['customer_price_regular__lte'] = available_limit

    products = XfersProduct.objects.filter(**query_filter).order_by('customer_price_regular')

    return list(products)


def construct_payment_product_response(
    products: Union[List[SepulsaProduct], List[AYCProduct], List[XfersProduct]]
) -> List[Dict]:
    data = []
    for product in products:
        label = None
        if isinstance(product, SepulsaProduct):
            label = product.product_label

        data.append(
            dict(
                id=product.sepulsa_id,
                product_id=product.product_id,
                product_name=product.product_name,
                product_label=label,
                customer_price_regular=product.customer_price_regular,
                type=product.type,
                category=product.category.replace('_', ' ').capitalize(),
            )
        )

    return data


def get_ewallet_products(
    data: Dict, account: Account, customer: Customer
) -> List[Union[SepulsaProduct, AYCProduct, XfersProduct]]:
    """
    PaymentProduct view
    Get available products from Ewallet Vendors
    """
    is_applied_ayc_flow = is_applied_ayc_switching_flow(
        customer_id=customer.id,
        transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
    )
    is_applied_xfers_flow = is_applied_xfers_switching_flow(
        customer_id=customer.id,
        transaction_method=TransactionMethodCode.DOMPET_DIGITAL.code,
    )

    # hierachy: ayoconnect => xfers => sepulsa
    ewallet_products = get_sepulsa_products(data=data, account=account)

    xfers_products = get_xfers_products(data, account)
    if is_applied_xfers_flow and xfers_products:
        ewallet_products = xfers_products

    ayo_products = get_ayc_products(data=data, account=account)
    if is_applied_ayc_flow and ayo_products:
        ewallet_products = ayo_products

    return sorted(ewallet_products, key=lambda x: x.customer_price_regular)
