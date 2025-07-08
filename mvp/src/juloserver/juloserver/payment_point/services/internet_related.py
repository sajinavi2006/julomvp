from datetime import datetime
from typing import Tuple, List, Optional

from juloserver.julo.clients.sepulsa import SepulsaResponseCodes, SepulsaHTTPCodes
from juloserver.payment_point.constants import SepulsaMessage, InternetBillCategory
from juloserver.julo.models import SepulsaProduct
from juloserver.payment_point.clients import get_julo_sepulsa_loan_client


def get_or_none_sepulsa_product(product_id: str, product_type: str) -> SepulsaProduct:
    query_filter = {
        'product_id': product_id,
        'type': product_type,
        'is_active': True,
        'is_not_blocked': True,
    }
    return SepulsaProduct.objects.filter(**query_filter).last()


def get_error_message_for_internet_bill(response: dict) -> str:
    response_code = response['response_code']
    if response_code in SepulsaResponseCodes.INTERNET_ERROR_RESPONSE:
        return response['message']
    elif response_code == SepulsaHTTPCodes.PRODUCT_CLOSED_TEMPORARILY:
        return SepulsaMessage.PRODUCT_CLOSED_TEMPORARILY
    elif response_code == SepulsaResponseCodes.GENERAL_ERROR:
        return SepulsaMessage.INVALID
    else:
        return None


def get_internet_bill_info(customer_number: str, internet_product: SepulsaProduct) -> Tuple:
    internet_service = InternetBillService(customer_number, internet_product)
    response, error = internet_service.inquiry_internet_bill()
    if error:
        return None, error

    internet_bill = internet_service.construct_internet_bill_data(response)
    return internet_bill, None


def format_bill_periods(bill_period) -> List[str]:
    # a customer can have > 1 month bill
    # bill_periods: "201611,201611"
    list_periods = bill_period.split(',')
    return [
        datetime.strptime(bill_period, '%Y%m').strftime('%m-%Y') for bill_period in list_periods
    ]


class InternetBillService:
    inquiry_endpoints = {
        InternetBillCategory.TELKOM: 'inquire/telkom_postpaid.json',
        InternetBillCategory.POSTPAID_INTERNET: 'inquire/tv_cable.json',
    }

    def __init__(self, customer_number: str, internet_product: SepulsaProduct) -> None:
        self.customer_number = customer_number
        self.internet_product = internet_product

        # every API has different response
        self.construct_functions = {
            InternetBillCategory.TELKOM: self._construct_telkom_internet_bill_data,
            InternetBillCategory.POSTPAID_INTERNET: self._construct_postpaid_internet_bill_data,
        }

    def _construct_telkom_internet_bill_data(self, internet_data: dict) -> dict:
        return dict(
            subscriber_id=internet_data['id_pelanggan'],
            customer_name=internet_data['nama_pelanggan'],
            price=internet_data['jumlah_bayar'],  # bill_amount + admin fee
            bill_period=format_bill_periods(internet_data['bulan_thn']),
        )

    def _construct_postpaid_internet_bill_data(self, internet_data: dict) -> dict:
        return dict(
            subscriber_id=internet_data['customer_id'],
            customer_name=internet_data['customer_name'],
            price=internet_data['total_amount'],
            bill_period=format_bill_periods(internet_data['bill_period']),
        )

    def construct_internet_bill_data(self, response: dict) -> dict:
        return self.construct_functions[self.internet_product.category](response)

    def inquiry_internet_bill(self) -> Tuple[Optional[dict], Optional[str]]:
        sepulsa_client = get_julo_sepulsa_loan_client()
        endpoint = InternetBillService.inquiry_endpoints[self.internet_product.category]
        return sepulsa_client.inquiry_internet_bill_info(
            customer_number=self.customer_number,
            product_id=self.internet_product.product_id,
            endpoint=endpoint,
        )
