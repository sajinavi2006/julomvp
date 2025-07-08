from builtins import str
import re
import logging
from datetime import datetime
from typing import List
from rest_framework.views import APIView

from juloserver.payment_point.exceptions import NoMobileOperatorFound, NoProductForCreditMatrix
from juloserver.payment_point.services.sepulsa import (
    create_sepulsa_payment_point_inquire_tracking_id,
)
from juloserver.payment_point.services.ewallet_related import (
    get_ewallet_categories,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
)

from juloserver.payment_point.clients import get_julo_sepulsa_loan_client
from juloserver.payment_point.serializers import (
    InquiryElectricityPostpaidSerializer,
    InquireBpjsSerializer,
    InquireMobilePostpaidSerializer,
    PaymentProductSerializer
)
from juloserver.payment_point.services.views_related import (
    construct_ewallet_categories_response,
    construct_payment_product_response,
    get_ewallet_products,
    get_sepulsa_products,
    validate_data_and_get_sepulsa_product,
    get_error_message
)
from juloserver.payment_point.constants import (
    SepulsaProductType,
    SepulsaProductCategory,
    ErrorMessage,
    TransactionMethodCode,
)
from juloserver.payment_point.utils import censor_fullname

from juloserver.julo.models import (
    Customer
)
from juloserver.account.models import (
    Account
)

logger = logging.getLogger(__name__)


class InquireElectricityPostpaid(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = InquiryElectricityPostpaidSerializer

    def get(self, request):
        data, sepulsa_product = validate_data_and_get_sepulsa_product(
            request.query_params,
            self.serializer_class,
            SepulsaProductType.ELECTRICITY,
            SepulsaProductCategory.ELECTRICITY_POSTPAID
        )
        if not sepulsa_product:
            return general_error_response('Produk tidak ditemukan')

        sepulsa_client = get_julo_sepulsa_loan_client()
        result = sepulsa_client.inquire_electricity_postpaid_information(
            data['customer_number'], sepulsa_product.product_id
        )
        is_request_success, status_code, response = result
        if not is_request_success:
            return general_error_response(ErrorMessage.GENERAL_FOR_REQUEST_EXCEPTION)

        if 'response_code' not in response or response['response_code'] != '00':
            response_code = response['response_code'] if 'response_code' in response else None
            error_message = get_error_message(response_code, sepulsa_product.type, status_code)
            return general_error_response(error_message)

        actual_bill_amount = int(response['amount']) - int(response['admin_charge'])
        total_bill_amount = actual_bill_amount + sepulsa_product.admin_fee
        total_electricity_time = len(response["blth_summary"].split(','))
        last_bill = response["bills"][-1]
        due_date_last_bill = date_validation(last_bill['due_date'])
        price = str(total_bill_amount)

        inquire_tracking_id = create_sepulsa_payment_point_inquire_tracking_id(
            account=request.user.customer.account,
            transaction_method_id=TransactionMethodCode.LISTRIK_PLN.code,
            price=price,
            sepulsa_product_id=sepulsa_product.id,
            identity_number=data['customer_number'],
            other_data={
                "customer_name": response["subscriber_name"],
            },
        )

        response_data = {
            "subscriber_id": response['subscriber_id'],
            "subscriber_name": response['subscriber_name'],
            "power": response['power'],
            "price": price,
            "admin_charge": str(sepulsa_product.admin_fee),
            "bill_summary": {
                "total_electricity_bill": str(actual_bill_amount),
                "due_date": datetime.strftime(due_date_last_bill, "%Y-%m-%d"),
                "total_electricity_time": total_electricity_time,
                "admin_charge": str(sepulsa_product.admin_fee),
                "total_price": str(total_bill_amount),
            },
            "sepulsa_payment_point_inquire_tracking_id": inquire_tracking_id,
        }

        logger.info({
            'action': 'inquire_electricity_validate_data_and_get_sepulsa_product',
            'response_data': response_data,
            'customer_number': data['customer_number']
        })

        return success_response(response_data)


class InquireBpjs(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = InquireBpjsSerializer

    def get(self, request):
        data, sepulsa_product = validate_data_and_get_sepulsa_product(
            request.query_params,
            self.serializer_class,
            SepulsaProductType.BPJS,
            SepulsaProductCategory.BPJS_KESEHATAN[0]
        )
        if not sepulsa_product:
            return general_error_response('Produk tidak ditemukan')
        sepulsa_client = get_julo_sepulsa_loan_client()
        response = sepulsa_client.inquire_bpjs(sepulsa_product.product_id,
                                               data['bpjs_times'],
                                               data['bpjs_number'])
        if 'response_code' not in response or response['response_code'] != '00':
            response_code = response['response_code'] if 'response_code' in response else None
            error_message = get_error_message(response_code, sepulsa_product.type)
            return general_error_response(error_message)

        customer_amount = int(response['premi']) + sepulsa_product.admin_fee
        name = re.sub(r"\([^()]*\)", "", response['name'])
        censored_name = censor_fullname(name)

        inquire_tracking_id = create_sepulsa_payment_point_inquire_tracking_id(
            account=request.user.customer.account,
            transaction_method_id=TransactionMethodCode.BPJS_KESEHATAN.code,
            price=customer_amount,
            sepulsa_product_id=sepulsa_product.id,
            identity_number=data['bpjs_number'],
            other_data={
                "bpjs_times": data['bpjs_times'],
                "customer_name": censored_name,
            },
        )

        response_data = dict(
            price=customer_amount,
            name=censored_name,
            bpjs_number=data['bpjs_number'],
            bill_summary=dict(
                total_electricity_bill=str(int(response['premi'])),
                admin_charge=str(sepulsa_product.admin_fee),
                total_price=str(customer_amount),
            ),
            sepulsa_payment_point_inquire_tracking_id=inquire_tracking_id,
        )

        logger.info({
            'action': 'inquire_bpjs_validate_data_and_get_sepulsa_product',
            'response_data': response_data,
            'bpjs_number': data['bpjs_number']
        })

        return success_response(response_data)


class EwalletCategory(StandardizedExceptionHandlerMixin, APIView):

    def get(self, request):
        customer_id = request.user.customer.id
        categories = get_ewallet_categories(customer_id=customer_id)

        if not categories:
            return general_error_response(ErrorMessage.EWALLET_NOT_AVAILABLE_OR_HAS_ISSUES)

        data = construct_ewallet_categories_response(categories=categories)

        return success_response(data)


class InquireMobilePostpaid(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = InquireMobilePostpaidSerializer

    def get(self, request):
        data, sepulsa_product = validate_data_and_get_sepulsa_product(
            request.query_params,
            self.serializer_class,
            SepulsaProductType.MOBILE,
            SepulsaProductCategory.POSTPAID[0]
        )
        if not sepulsa_product:
            return general_error_response('Produk tidak ditemukan')

        sepulsa_client = get_julo_sepulsa_loan_client()
        response = sepulsa_client.inquire_mobile_postpaid(sepulsa_product.product_id,
                                                          data['mobile_number'])

        if 'response_code' not in response or response['response_code'] != '00':
            response_code = response['response_code'] if 'response_code' in response else None
            error_message = get_error_message(response_code, sepulsa_product.type)
            return general_error_response(error_message)

        admin_free = sepulsa_product.admin_fee if sepulsa_product.admin_fee else 0
        customer_amount = int(response['bill_amount'])
        due_date = '{}-{}'.format(response['bill_periode'][:4], response['bill_periode'][-2:])
        censored_name = censor_fullname(response['customer_name'])
        price = customer_amount + admin_free

        inquire_tracking_id = create_sepulsa_payment_point_inquire_tracking_id(
            account=request.user.customer.account,
            transaction_method_id=TransactionMethodCode.PASCA_BAYAR.code,
            price=price,
            sepulsa_product_id=sepulsa_product.id,
            identity_number=data['mobile_number'],
            other_data={
                "customer_name": censored_name,
            },
        )

        response_data = {
            "phone_number": data['mobile_number'],
            "operator_name": sepulsa_product.operator.name,
            "subscriber_name": censored_name,
            "price": price,
            "bill_amount": customer_amount,
            "admin_charge": admin_free,
            "due_date": due_date,
            "sepulsa_payment_point_inquire_tracking_id": inquire_tracking_id,
        }

        logger.info({
            'action': 'inquire_mobile_validate_data_and_get_sepulsa_product',
            'response_data': response_data,
            'mobile_number': data['mobile_number']
        })

        return success_response(response_data)


def date_validation(raw_date):
    try:
        due_date = datetime.strptime(raw_date, "%Y%m%d")
        return due_date
    except ValueError:
        date = raw_date[0:2]
        month = raw_date[2:4]
        year = raw_date[4:8]
        due_date = str(year + month + date)
        due_date = datetime.strptime(due_date, "%Y%m%d")

        return due_date


class PaymentProduct(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = PaymentProductSerializer

    def get(self, request):
        try:
            serializer = self.serializer_class(data=request.query_params)
            serializer.is_valid(raise_exception=True)

            data = serializer.data
            products = self._get_products(data=data)

            # construct reponse
            data_response = construct_payment_product_response(products=products)

            logger.info(
                {
                    'action': 'PaymentProductV2',
                    'user_id': self.request.user.id,
                    'request_data': data,
                    'products': data_response,
                }
            )

            return success_response(data_response)

        except NoMobileOperatorFound:
            return general_error_response('Data operator seluler tidak ditemukan')

        except NoProductForCreditMatrix:
            return general_error_response(ErrorMessage.NOT_ELIGIBLE_FOR_THE_TRANSACTION)

    def _get_products(self, data) -> List:
        # get customer & account
        user = self.request.user
        customer = Customer.objects.filter(user=user).last()
        account = Account.objects.filter(customer=customer).last()

        # seperate case of EWALLET to handle non-sepulsa products
        if data['type'] == SepulsaProductType.EWALLET:
            return get_ewallet_products(
                data=data,
                account=account,
                customer=customer,
            )

        sepulsa_products = get_sepulsa_products(
            data=data,
            account=account,
        )

        return sepulsa_products
