from juloserver.partnership.miniform.serializers import MiniFormPhoneOfferSerializer
from juloserver.partnership.miniform.services import save_pii_and_phone_offer
from juloserver.partnership.security import PartnershipMiniformJWTAuthentication
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from rest_framework.views import APIView
from juloserver.standardized_api_response.utils import general_error_response
from juloserver.pin.utils import transform_error_msg
from rest_framework import status as http_status_codes
from rest_framework.request import Request
from rest_framework.response import Response
from juloserver.julo.utils import format_mobile_phone


class MiniFormPhoneOfferView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [PartnershipMiniformJWTAuthentication]
    serializer_class = MiniFormPhoneOfferSerializer

    def post(self, request: Request) -> Response:
        try:
            partner_name = request.partner_name
            data = request.data
            serializer = self.serializer_class(data=data)
            if not serializer.is_valid():
                return general_error_response(
                    transform_error_msg(serializer.errors, exclude_key=True)[0])

            request_payload = {
                "phone": format_mobile_phone(serializer.data["phone_number"]),
                "email": serializer.data['email'],
                "nik": serializer.data['nik'],
                "name": serializer.data['name'],
                "partner_name": partner_name,
            }

            other_phone_num = serializer.data.get('other_phone_number')
            if other_phone_num:
                other_phone = format_mobile_phone(other_phone_num)
                request_payload.update({"other_phone": other_phone})

            response = save_pii_and_phone_offer(request_payload)

            if response.get('error'):
                return general_error_response(message=response['error'])

            return Response(status=http_status_codes.HTTP_204_NO_CONTENT)

        except Exception as e:
            return general_error_response(str(e))
