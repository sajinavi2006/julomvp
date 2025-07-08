from typing import Union
from django.conf import settings
from django.db.models import Max

from juloserver.payment_point.constants import (
    SepulsaProductCategory,
    SepulsaProductType,
    MAXIMUM_PULSA_TRANSACTION_HISTORIES,
    SepulsaTransactionStatus,
    PREFIX_MOBILE_OPERATOR_LENGTH,
)
from juloserver.julo.services2.sepulsa import SepulsaService
from juloserver.payment_point.clients import get_julo_sepulsa_loan_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting, SepulsaTransaction, MobileOperator, Loan
from juloserver.payment_point.models import (
    SepulsaPaymentPointInquireTracking,
    AYCEWalletTransaction,
    XfersEWalletTransaction,
)


def get_sepulsa_partner_amount(customer_amount, sepulsa_product, pdam_service_fee=0):
    partner_amount = None
    if (
        sepulsa_product.type == SepulsaProductType.BPJS
        or sepulsa_product.type == SepulsaProductType.ELECTRICITY
        and sepulsa_product.category == SepulsaProductCategory.ELECTRICITY_POSTPAID
    ):
        bill_amount = customer_amount - sepulsa_product.admin_fee
        partner_amount = bill_amount + sepulsa_product.service_fee
    elif sepulsa_product.category == SepulsaProductCategory.POSTPAID[0]:
        partner_amount = customer_amount - sepulsa_product.collection_fee
    elif sepulsa_product.type == SepulsaProductType.PDAM:
        partner_amount = customer_amount + pdam_service_fee

    return partner_amount


class SepulsaLoanService(SepulsaService):
    def __init__(self):
        self.julo_sepulsa_client = get_julo_sepulsa_loan_client()

    def inquire_train_station(self):
        return self.julo_sepulsa_client.send_request("get", "v3/train/station")

    def inquire_booking_train_ticket(self, data):
        return self.julo_sepulsa_client.send_request(
            "post", "v3/booking/train", data=data
        )

    def inquire_train_ticket(self, data):
        return self.julo_sepulsa_client.send_request('post', 'v3/train/ticket', data=data)

    def inquire_pdam_operator(self, data):
        return self.julo_sepulsa_client.send_request('post', 'operator/pdam.json', data=data)

    def inquire_pdam(self, data):
        return self.julo_sepulsa_client.send_request('post', 'inquire/pdam.json', data=data)

    def inquire_train_ticket_seat(self, data):
        return self.julo_sepulsa_client.send_request("post", "v3/train/seat", data=data)

    def inquire_train_change_seats(self, data):
        return self.julo_sepulsa_client.send_request("post", "v3/train/change_seat", data=data)

    def get_train_transaction_detail(self, transaction_id):
        return self.julo_sepulsa_client.send_request(
            "get", "v3/transaction/train/%s" % (transaction_id)
        )


def get_sepulsa_base_url():
    using_new_url = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.USE_NEW_SEPULSA_BASE_URL,
        is_active=True,
    ).exists()
    if using_new_url:
        return settings.NEW_SEPULSA_BASE_URL

    return settings.SEPULSA_BASE_URL


def get_mobile_operator_dict():
    mobile_operators = MobileOperator.objects.filter(is_active=True).all()
    result = {}
    for mobile_operator in mobile_operators:
        initial_numbers = mobile_operator.initial_numbers
        for initial_number in initial_numbers:
            result[initial_number] = {
                "id": mobile_operator.id,
                "name": mobile_operator.name,
            }
    return result


def get_recent_sepulsa_transaction_histories(customer, category):
    mobile_operator_dict = get_mobile_operator_dict()
    transaction_histories = (
        SepulsaTransaction.objects.filter(
            customer=customer,
            product__category=category,
            transaction_status=SepulsaTransactionStatus.SUCCESS,
        )
        .values('phone_number', 'product__id', 'product__product_name', 'product__product_nominal')
        .annotate(max_pk=Max('pk'))
        .order_by('-max_pk')[:MAXIMUM_PULSA_TRANSACTION_HISTORIES]
    )
    return [
        {
            "phone_number": transaction_history["phone_number"],
            "product_id": transaction_history["product__id"],
            "product_name": transaction_history["product__product_name"],
            "mobile_operator_name": mobile_operator_dict.get(
                transaction_history["phone_number"][:PREFIX_MOBILE_OPERATOR_LENGTH], {}
            ).get("name"),
            "nominal_amount": transaction_history["product__product_nominal"],
        }
        for transaction_history in transaction_histories
    ]


def get_sepulsa_recent_phones(customer_id):
    phone_numbers = SepulsaTransaction.objects.filter(
        transaction_status=SepulsaTransactionStatus.SUCCESS,
        phone_number__isnull=False,
        customer_id=customer_id
    ).values('phone_number').annotate(max_id=Max('id')).order_by(
        '-max_id'
    )[:MAXIMUM_PULSA_TRANSACTION_HISTORIES]

    if not phone_numbers:
        return []

    mobile_operator_dict = get_mobile_operator_dict()
    distinct_pns = [num['phone_number'] for num in phone_numbers]
    data = []

    for num in distinct_pns:
        mobile_operator = mobile_operator_dict.get(num[:PREFIX_MOBILE_OPERATOR_LENGTH])
        if mobile_operator:
            data.append({
                'phone_number': num,
                'mobile_operator_id': mobile_operator['id'],
                'mobile_operator_name': mobile_operator['name']
            })

    return data


def create_sepulsa_payment_point_inquire_tracking_id(
    account, transaction_method_id, price, sepulsa_product_id, identity_number, other_data
):
    if not FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT,
        is_active=True,
    ).exists():
        return None

    sepulsa_payment_point_inquire_tracking = SepulsaPaymentPointInquireTracking.objects.create(
        account=account,
        transaction_method_id=transaction_method_id,
        price=price,
        sepulsa_product_id=sepulsa_product_id,
        identity_number=identity_number,
        other_data=other_data,
    )

    return sepulsa_payment_point_inquire_tracking.id


def get_payment_point_transaction_from_loan(
    loan: Loan,
) -> Union[SepulsaTransaction, AYCEWalletTransaction, XfersEWalletTransaction]:
    """
    Find transaction for payment point from Loan
    """
    sepulsa_transaction = loan.sepulsatransaction_set.last()
    if sepulsa_transaction:
        return sepulsa_transaction

    ayc_ewallet_transaction = loan.aycewallettransaction_set.last()
    if ayc_ewallet_transaction:
        return ayc_ewallet_transaction

    if loan.is_xfers_ewallet_transaction:
        return loan.xfers_ewallet_transaction

    return None
