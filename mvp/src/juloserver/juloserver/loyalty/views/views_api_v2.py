from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
)
from juloserver.loyalty.services.point_redeem_services import (
    get_data_point_information,
    get_convert_rate_info,
)
from juloserver.loyalty.services.services import (
    get_non_locked_loyalty_point
)
from juloserver.loyalty.services.mission_related import (
    get_customer_loyalty_mission_list,
    get_customer_loyalty_mission_detail,
)
from juloserver.loyalty.serializers import (
    LoyaltyPointSerializer,
)
from juloserver.loyalty.constants import (
    MissionFilterCategoryConst,
    MissionMessageConst,
    APIVersionConst,
)
from juloserver.loyalty.exceptions import (
    MissionConfigNotFoundException,
)


class PointInformationAPIViewV2(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        customer = request.user.customer
        response = get_data_point_information(customer)
        return success_response(response)


class LoyaltyInfoAPIViewV2(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        customer = request.user.customer
        loyalty_point = get_non_locked_loyalty_point(customer_id=customer.id)
        loyalty_point_serializer = LoyaltyPointSerializer(loyalty_point)
        convert_rate_info = get_convert_rate_info()
        data = request.query_params
        category = data.get('category', MissionFilterCategoryConst.ALL_MISSIONS)
        mission_list = get_customer_loyalty_mission_list(
            customer=customer,
            category=category,
            api_version=APIVersionConst.V2
        )

        return success_response({
            'loyalty_point': loyalty_point_serializer.data,
            'convert_rate_info': convert_rate_info,
            'missions': mission_list
        })


class LoyaltyMissionDetailAPIViewV2(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, mission_config_id):
        customer = request.user.customer
        try:
            mission_detail = get_customer_loyalty_mission_detail(
                customer=customer,
                mission_config_id=mission_config_id,
                api_version=APIVersionConst.V2
            )
        except MissionConfigNotFoundException:
            return general_error_response(MissionMessageConst.ERROR_MISSION_CONFIG_NOT_FOUND)
        return success_response(mission_detail)
