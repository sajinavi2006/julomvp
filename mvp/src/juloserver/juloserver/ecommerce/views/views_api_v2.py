from rest_framework.views import APIView

from juloserver.ecommerce.juloshop_service import check_juloshop_app_version
from juloserver.loan.constants import LoanJuloOneConstant

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response
)
from juloserver.ecommerce.serializers import EcommerceConfigurationSerializer, MarketPlaceSerializer
from juloserver.ecommerce.services import (
    get_iprice_transaction,
    prepare_ecommerce_data,
)
from juloserver.julo.utils import display_rupiah
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


class EcommerceCategoryView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        category_data, marketplace_data = prepare_ecommerce_data(customer)
        # -----Hiding Julo Shop if app version is less than 7.10.0-----
        if not request.META.get('HTTP_X_APP_VERSION'):
            return general_error_response('Missing App version')

        app_version = request.META.get('HTTP_X_APP_VERSION')
        invalid_version = check_juloshop_app_version(app_version)
        if invalid_version:
            marketplace_data = []
        # -------------------------------------------------------------

        if not category_data and not marketplace_data:
            return general_error_response('Ecommerce tidak ditemukan')

        category_serializer = EcommerceConfigurationSerializer(category_data, many=True)
        marketplace_serializer = MarketPlaceSerializer(marketplace_data, many=True)

        limit_transaction = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.MINIMUM_AMOUNT_TRANSACTION_LIMIT, is_active=True
        ).last()
        if not limit_transaction:
            warning_text = "<ul>{}{}</ul>".format(
                "<li> Transaksi E-commerce hanya bisa dilakukan dengan Nomor "
                "Virtual Account dari Bank tertentu</li>",
                "<li> Nilai transaksi pembelian minimal {}</li>".format(
                    display_rupiah(LoanJuloOneConstant.MIN_lOAN_TRANSFER_AMOUNT)
                ),
            )
        else:
            warning_text = limit_transaction.parameters['information'].replace(
                "{minimum_amount}",
                display_rupiah(limit_transaction.parameters['limit_transaction'])
            )

        data = dict(
            warningText=warning_text,
            category=category_serializer.data,
            marketPlace=marketplace_serializer.data,
        )
        return success_response(data)


class IpriceGetTransactionData(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, transaction_xid):
        customer = request.user.customer
        transaction = get_iprice_transaction(customer, transaction_xid, use_xid=True)

        if not transaction:
            return not_found_response("No requested iPrice transaction found")

        response_data = {
            "iprice_transaction_id": transaction.id,
            "iprice_total_amount": transaction.iprice_total_amount,
            "iprice_order_id": transaction.iprice_order_id,
            "current_status": transaction.current_status,
            "success_redirect_url": transaction.success_redirect_url,
            "fail_redirect_url": transaction.fail_redirect_url,
            "checkout_info": transaction.checkout_info,
        }

        return success_response(data=response_data)
