import logging
import json
import re
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.views import APIView
from rest_framework import serializers
from rest_framework.serializers import ValidationError

from juloserver.julo_financing.constants import JFinancingErrorMessage
from juloserver.julo_financing.exceptions import (
    CheckoutNotFound,
    InvalidVerificationStatus,
    ProductOutOfStock,
    UserNotAllowed,
    ProductNotFound,
    JFinancingProductLocked,
)
from juloserver.julo_financing.serializers import (
    CategoryIdSerializer,
    ProductListSerializer,
    ProductDetailSerializer,
    JFinancingLoanCalculationSerializer,
)
from juloserver.julo_financing.services.view_related import (
    JFinancingTransactionDetailViewService,
    JFinancingUploadSignatureService,
    get_list_j_financing_product,
    get_j_financing_user_info,
    get_j_financing_product_detail,
    populate_request_data_loan_calculation,
    get_available_durations,
    get_j_financing_loan_agreement_template,
)
from juloserver.loan.exceptions import (
    AccountLimitExceededException,
    LoanTransactionLimitExceeded,
)
from juloserver.loan.services.views_related import validate_mobile_number
from juloserver.pin.decorators import pin_verify_required
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.julo_financing.services.core_services import (
    is_product_available,
    is_province_supported,
    get_shipping_fee_from_province,
)
from juloserver.julo_financing.authentication import FinancingTokenAuthentication
from juloserver.standardized_api_response.utils import (
    created_response,
    forbidden_error_response,
    success_response,
    general_error_response,
)
from juloserver.julo_financing.services.token_related import (
    get_entry_point,
    validate_entry_point_type,
)
from juloserver.julo_financing.services.view_related import (
    JFinancingSubmitViewService,
    get_customer_jfinancing_transaction_history,
)
from juloserver.loan.views.views_api_v3 import LoanCalculation
from juloserver.partnership.constants import ErrorMessageConst

logger = logging.getLogger(__name__)


class EntryPointWebView(APIView):
    def get(self, request):
        query_params = request.query_params
        type = query_params.get('type', None)

        is_valid, message = validate_entry_point_type(type, query_params)
        if not is_valid:
            return general_error_response(message)

        customer_id = request.user.customer.pk
        entry_point = get_entry_point(customer_id, type, query_params)

        return success_response({"link": entry_point})


class JFinancingAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (FinancingTokenAuthentication,)


class JFinancingProductListView(JFinancingAPIView):
    def get(self, request, *args, **kwargs):
        query_serializer = CategoryIdSerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        response_serializer = ProductListSerializer(
            {
                'user_info': get_j_financing_user_info(customer=request.user.customer),
                'products': get_list_j_financing_product(
                    category_id=query_serializer.validated_data.get('category_id')
                ),
            }
        )
        return success_response(data=response_serializer.data)


class JFinancingProductDetailView(JFinancingAPIView):
    def get(self, request, *args, **kwargs):
        product_id = int(kwargs['product_id'])  # path pattern is [0-9]+ -> safe to cast to int
        try:
            product_detail = get_j_financing_product_detail(product_id=product_id)
            return success_response(data=ProductDetailSerializer(product_detail).data)
        except ProductOutOfStock:
            return general_error_response(JFinancingErrorMessage.STOCK_NOT_AVAILABLE)
        except ProductNotFound:
            return general_error_response(JFinancingErrorMessage.PRODUCT_NOT_AVAILABLE)


class JFinancingLoanCalculationView(JFinancingAPIView, LoanCalculation):
    def post(self, request, *args, **kwargs):
        serializer = JFinancingLoanCalculationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        account_id = request.user.customer.account.pk
        request.data['account_id'] = account_id

        province_shipping_fee = get_shipping_fee_from_province(request.data['province_name'])
        populate_request_data_loan_calculation(request.data)
        request.data['loan_amount_request'] = str(
            int(request.data['loan_amount_request']) + province_shipping_fee
        )

        response_data = super(JFinancingLoanCalculationView, self).post(request)
        if response_data.status_code == HTTP_200_OK:
            json_data = json.loads(response_data.content)
            json_data['data']['shipping_fee'] = province_shipping_fee
            loan_choice = json_data['data']['loan_choice']
            if loan_choice:
                json_data['data']['loan_choice'] = get_available_durations(loan_choice)
        else:
            json_data = response_data.data

        return Response(status=response_data.status_code, data=json_data)


class TransactionHistoryListView(JFinancingAPIView):
    def get(self, request, *args, **kwargs):
        """
        Get customer's J Financing transaction/verification history
        """

        customer = request.user.customer

        response_data = get_customer_jfinancing_transaction_history(
            customer_id=customer.id,
        )

        return success_response(data=response_data)


class JFinancingSubmitView(JFinancingAPIView):
    class InputPostSerializer(serializers.Serializer):
        class CheckoutInfoSerializer(serializers.Serializer):
            full_name = serializers.CharField(max_length=255, min_length=3)
            phone_number = serializers.CharField()
            address = serializers.CharField()
            address_detail = serializers.CharField()

            def validate_phone_number(self, phone_number):
                if not validate_mobile_number(phone_number):
                    raise serializers.ValidationError(ErrorMessageConst.PHONE_INVALID)
                return phone_number

        checkout_info = CheckoutInfoSerializer()
        loan_duration = serializers.IntegerField()
        province_name = serializers.CharField()
        j_financing_product_id = serializers.IntegerField()

        def validate_j_financing_product_id(self, j_financing_product_id):
            if not is_product_available(j_financing_product_id):
                raise serializers.ValidationError(JFinancingErrorMessage.PRODUCT_NOT_AVAILABLE)

            return j_financing_product_id

        def validate_loan_duration(self, loan_duration):
            # same validation as LoanJuloOne View
            if not 24 >= loan_duration > 0:
                raise serializers.ValidationError('Pilihan tenor tidak ditemukan')

            return loan_duration

        def validate_province_name(self, province_name):
            if not is_province_supported(province_name):
                raise serializers.ValidationError("Province not supported")

            return province_name

        def validate(self, attrs):
            # validate province match with address
            province_name = attrs.get('province_name')
            address = attrs.get('checkout_info').get('address')
            if province_name.upper() not in address.upper():
                raise serializers.ValidationError("Province not match with address")

            return attrs

    @pin_verify_required
    def post(self, request, *args, **kwargs):
        serializer = self.InputPostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # submit checkout
        customer = request.user.customer
        try:
            service = JFinancingSubmitViewService(
                customer=customer,
                submit_data=serializer.validated_data,
            )
            response_data = service.submit()
        except JFinancingProductLocked:
            return general_error_response(message=JFinancingErrorMessage.JFINANCING_NOT_AVAILABLE)
        except AccountLimitExceededException:
            return general_error_response(
                message=JFinancingErrorMessage.LIMIT_NOT_ENOUGH,
            )
        except LoanTransactionLimitExceeded as e:
            return general_error_response(message=str(e))

        return success_response(data=response_data)


class JFinancingUploadSignatureView(JFinancingAPIView):
    class InputPostSerializer(serializers.Serializer):
        upload = serializers.ImageField(required=True)
        data = serializers.CharField(required=True)  # name of file with extension

        def _check_extension(self, file_name: str) -> None:
            extensions = ['.jpg', '.png', '.jpeg']
            if not any(file_name.endswith(ext) for ext in extensions):
                # invalid file extensions
                raise ValidationError(JFinancingErrorMessage.SIGNATURE_ISSUE)

        def validate_upload(self, value):
            self._check_extension(value.name)
            return value

        def validate_data(self, value: str):
            """
            validate name
            """
            if not re.match(r"^[a-zA-Z0-9-_.]+$", value):
                # invalid file name
                raise ValidationError(JFinancingErrorMessage.SIGNATURE_ISSUE)

            if value.startswith('--') or value.endswith('--'):
                # invalid file name
                raise ValidationError(JFinancingErrorMessage.SIGNATURE_ISSUE)

            self._check_extension(value)

            return value

    def post(self, request, *args, **kwargs):

        data = request.POST
        serializer = self.InputPostSerializer(
            data=data,
        )
        serializer.is_valid(raise_exception=True)

        # service
        checkout_id = int(kwargs['checkout_id'])
        try:
            service = JFinancingUploadSignatureService(
                checkout_id=checkout_id,
                input_data=serializer.validated_data,
                user=self.request.user,
            )
            service.upload_signature()
        except (CheckoutNotFound, InvalidVerificationStatus):
            return general_error_response(JFinancingErrorMessage.SYSTEM_ISSUE)
        except ProductOutOfStock:
            return general_error_response(JFinancingErrorMessage.STOCK_NOT_AVAILABLE)
        except UserNotAllowed:
            return forbidden_error_response(
                message=JFinancingErrorMessage.JFINANCING_NOT_AVAILABLE,
            )

        return created_response()


class JFinancingTransactionDetailView(JFinancingAPIView):
    def get(self, request, *args, **kwargs):

        checkout_id = int(kwargs['checkout_id'])  # path pattern is [0-9]+ -> safe to cast to int
        try:
            service = JFinancingTransactionDetailViewService(
                checkout_id=checkout_id,
                user=self.request.user,
            )
            response_data = service.get_transaction_detail()
        except CheckoutNotFound:
            return general_error_response(JFinancingErrorMessage.SYSTEM_ISSUE)
        except UserNotAllowed:
            return forbidden_error_response(
                message=JFinancingErrorMessage.JFINANCING_NOT_AVAILABLE,
            )

        return success_response(data=response_data)


class JFinancingLoanAgreementContentView(JFinancingAPIView):
    def get(self, request, *args, **kwargs):
        checkout_id = int(kwargs['checkout_id'])
        success, content = get_j_financing_loan_agreement_template(
            checkout_id, request.user.id, "skrtp"
        )
        if not success:
            return general_error_response(content)

        return success_response(data=content)
