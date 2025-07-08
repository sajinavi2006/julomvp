from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.faq.services.services import get_faqs
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import success_response


class FaqAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, feature_name):
        faq_data = get_faqs(feature_name)
        data = {"faq": faq_data}

        return success_response(data)
