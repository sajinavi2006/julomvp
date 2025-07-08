import re
import logging
from rest_framework.views import APIView

from juloserver.payment_point.clients import get_julo_sepulsa_loan_client
from juloserver.payment_point.services.sepulsa import get_recent_sepulsa_transaction_histories, \
    get_sepulsa_recent_phones
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    custom_bad_request_response,
)
from juloserver.julo.models import (
    SepulsaProduct,
    MobileOperator,
    Customer
)
from juloserver.payment_point.serializers import (
    InquiryElectricitySerializer,
    PaymentProductSerializer,
    MobileOperatorSerializer,
    MobilePhoneSerializer,
    InquiryInternetBillSerializer,
)
from juloserver.account.models import (
    AccountLimit,
    Account
)
from juloserver.loan.services.loan_related import (
    get_credit_matrix_and_credit_matrix_product_line
)
from juloserver.payment_point.services.views_related import (
    construct_data_inquiry_electricity,
)
from juloserver.payment_point.services.internet_related import (
    get_internet_bill_info,
    get_or_none_sepulsa_product,
)
from juloserver.payment_point.constants import (
    SepulsaProductCategory,
    SepulsaProductType,
    ErrorMessage,
    SepulsaMessage,
)

logger = logging.getLogger(__name__)


class PaymentProduct(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = PaymentProductSerializer

    def get(self, request):
        user = self.request.user
        customer = Customer.objects.filter(user=user).last()
        account = Account.objects.filter(customer=customer).last()
        serializer = self.serializer_class(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        query_filter = dict(
            type=data['type'],
            category=data['category'],
            is_active=True,
            is_not_blocked=True
        )
        if account and data['category'] not in SepulsaProductCategory.POSTPAID:
            account_limit = AccountLimit.objects.filter(account=account).last()
            application = account.get_active_application()
            credit_matrix, credit_matrix_product_line = \
                get_credit_matrix_and_credit_matrix_product_line(application, True)
            if not credit_matrix.product:
                return general_error_response(ErrorMessage.NOT_ELIGIBLE_FOR_THE_TRANSACTION)
            provision_fee = \
                account_limit.available_limit * credit_matrix.product.origination_fee_pct
            available_limit = account_limit.available_limit - provision_fee
            query_filter['customer_price_regular__lte'] = available_limit
        if data['mobile_operator_id']:
            mobile_operator = MobileOperator.objects.get_or_none(pk=data['mobile_operator_id'])
            if not mobile_operator:
                return general_error_response('Data operator seluler tidak ditemukan')
            query_filter['operator'] = mobile_operator
        sepulsa_products = SepulsaProduct.objects.filter(
            **query_filter
        ).order_by('customer_price_regular')
        data_response = []
        for sepulsa_product in sepulsa_products:
            data_response.append(dict(
                id=sepulsa_product.id,
                product_id=sepulsa_product.product_id,
                product_name=sepulsa_product.product_name,
                product_label=sepulsa_product.product_label,
                customer_price_regular=sepulsa_product.customer_price_regular,
                type=sepulsa_product.type,
                category=sepulsa_product.category.replace('_', ' ').capitalize()
            ))

        logger.info(
            {
                'action': 'PaymentProductV1',
                'user_id': user.id,
                'request_data': data,
                'products': data_response,
            }
        )

        return success_response(list(data_response))


class MobileOperatorView(StandardizedExceptionHandlerMixin, APIView):

    def get(self, request):
        serializer = MobileOperatorSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        mobile_phone = re.sub(r'^(0|\+62|)', r'0', data['mobile_phone'])
        mobile_operator = MobileOperator.objects.filter(
            is_active=True,
            initial_numbers__contains=[mobile_phone[:4]]
        ).last()
        if not mobile_operator:
            return general_error_response('Data operator seluler tidak ditemukan')
        data = {
            "id": mobile_operator.id,
            "name": mobile_operator.name,
        }
        return success_response(data)


class MobilePhoneValidateView(StandardizedExceptionHandlerMixin, APIView):

    def get(self, request):
        logger.info({
            'action': 'MobilePhoneValidateView',
            'mobile_phone': request.query_params,
            'customer_id': self.request.user.customer.id
        })
        serializer = MobilePhoneSerializer(data=request.query_params)
        if not serializer.is_valid():
            return general_error_response('Phone tidak valid')

        return success_response(serializer.data)


class InquiryElectricityInformation(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = InquiryElectricitySerializer

    def get(self, request):
        serializer = self.serializer_class(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        sepulsa_product = SepulsaProduct.objects.filter(
            product_id=data['product_id'],
            type=SepulsaProductType.ELECTRICITY
        ).last()
        if not sepulsa_product:
            return general_error_response('Produk tidak ditemukan')
        sepulsa_client = get_julo_sepulsa_loan_client()
        if sepulsa_product.category == SepulsaProductCategory.ELECTRICITY_PREPAID:
            response = sepulsa_client.get_account_electricity(
                data['customer_number'], sepulsa_product.product_id, True
            )
        if sepulsa_product.category == SepulsaProductCategory.ELECTRICITY_POSTPAID:
            result = sepulsa_client.inquire_electricity_postpaid_information(
                data['customer_number'], sepulsa_product.product_id
            )
            is_request_success, status_code, response = result
            if not is_request_success:
                return general_error_response(ErrorMessage.GENERAL_FOR_REQUEST_EXCEPTION)

        if 'response_code' not in response or response['response_code'] != '00':
            return general_error_response('Nomor meter / ID pelanggan tidak terdaftar. Silakan '
                                          'coba kembali dengan memasukkan Nomor meter / '
                                          'ID pelanggan yang terdaftar.')

        data = construct_data_inquiry_electricity(response, sepulsa_product.category)

        return success_response(data)


class PulsaTransactionHistory(APIView):
    def get(self, request):
        customer = request.user.customer
        transaction_histories = get_recent_sepulsa_transaction_histories(
            customer, SepulsaProductCategory.PULSA
        )

        return success_response(transaction_histories)


class PaketDataTransactionHistory(APIView):
    def get(self, request):
        customer = request.user.customer
        transaction_histories = get_recent_sepulsa_transaction_histories(
            customer, SepulsaProductCategory.PAKET_DATA
        )
        return success_response(transaction_histories)


class PhoneRecommendationView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer_id = request.user.customer.id
        phone_numbers = get_sepulsa_recent_phones(customer_id)

        return success_response({
            'phone_numbers': phone_numbers
        })


class InquiryInternetBillInfoView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = InquiryInternetBillSerializer

    def get(self, request):
        serializer = self.serializer_class(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.data

        product_id = data['product_id']
        sepulsa_product = get_or_none_sepulsa_product(
            str(product_id), SepulsaProductType.INTERNET_BILL
        )
        if not sepulsa_product:
            return general_error_response(SepulsaMessage.PRODUCT_NOT_FOUND)

        internet_bill, error = get_internet_bill_info(data['customer_number'], sepulsa_product)
        if error:
            if isinstance(error, list):
                return custom_bad_request_response(error)
            return general_error_response(error)

        return success_response(internet_bill)
