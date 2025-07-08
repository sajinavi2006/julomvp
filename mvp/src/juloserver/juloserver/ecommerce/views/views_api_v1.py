from rest_framework.status import HTTP_404_NOT_FOUND
from rest_framework.views import APIView
from juloserver.ecommerce.services import create_iprice_transaction, check_account_limit
from juloserver.ecommerce.juloshop_service import (
    check_juloshop_account_limit, create_juloshop_transaction, get_juloshop_transaction_details,
    is_application_eligible_for_juloshop,
)
from juloserver.partnership.security import IpriceAuthentication, JuloShopAuthentication

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (general_error_response,
                                                        success_response, response_template)
from juloserver.ecommerce.models import EcommerceConfiguration
from juloserver.ecommerce.serializers import (
    EcommerceConfigurationSerializer,
    IpriceCheckoutSerializer,
    JuloShopCheckoutSerializer,
    JuloShopTransactionDetailsSerializer,
)
from juloserver.ecommerce.constants import EcommerceConstant


class EcommerceCategoryView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        ecommerce_configuration = EcommerceConfiguration.objects.exclude(
            ecommerce_name=EcommerceConstant.JULOSHOP
        ).order_by('order_number')
        if not ecommerce_configuration:
            return general_error_response('Ecommerce tidak ditemukan')
        serializer = EcommerceConfigurationSerializer(ecommerce_configuration, many=True)
        data = dict(
            warningText=EcommerceConstant.WARNING_MESSAGE_TEXT,
            category=serializer.data
        )
        return success_response(data)


class IpriceCheckoutCallbackView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [IpriceAuthentication, ]
    serializer_class = IpriceCheckoutSerializer

    def post(self, request):
        """
        iPrice calls this when user clicks checkout on webview
        """
        serializer = IpriceCheckoutSerializer(data=request.data)
        if not serializer.is_valid():
            return general_error_response("Invalid Request Params")
        data = serializer.data

        transaction = create_iprice_transaction(data)
        check_account_limit(transaction)

        deep_link = "julo://e-commerce/checkout-redirect/iprice"
        response_data = {
            "transaction_id": transaction.iprice_transaction_xid,
            "application_id": transaction.application.application_xid,
            "redirect_url": "{}?transaction_id={}".format(
                deep_link,
                transaction.iprice_transaction_xid,
            ),
        }

        return success_response(data=response_data)


class JuloShopCheckoutCallbackView(APIView):
    permission_classes = []
    authentication_classes = (JuloShopAuthentication,)
    serializer_class = JuloShopCheckoutSerializer

    def post(self, request):
        serializer = JuloShopCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        if not is_application_eligible_for_juloshop(validated_data['application'].id):
            return general_error_response("JuloShop tidak ditemukan")

        transaction = create_juloshop_transaction(validated_data)
        is_valid = check_juloshop_account_limit(transaction)
        if not is_valid:
            return general_error_response("Account limit not sufficient")
        response_data = {
            "transaction_id": transaction.transaction_xid,
            "application_id": transaction.application.application_xid,
            "redirect_url": EcommerceConstant.JULOSHOP_REDIRECT_URL.format(
                transaction.transaction_xid,
            ),
        }

        return success_response(data=response_data)


class JuloShopTransactionDetails(APIView):
    serializer_class = JuloShopTransactionDetailsSerializer

    def get(self, request):
        data = request.query_params
        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)

        customer = request.user.customer
        application = customer.account.get_active_application()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        transaction_xid = serializer.validated_data['transaction_xid']
        transaction_details = get_juloshop_transaction_details(
            transaction_xid, customer, application
        )
        return success_response({
            "transaction_details": transaction_details
        })
