from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from juloserver.integapiv1.views import LoggedResponse
from juloserver.email_delivery.services import parse_callback_from_sendgrid
from juloserver.email_delivery.tasks import update_email_history_status


class EmailEventCallbackView(APIView):
    """
    API for SendGrid callback.
    """
    permission_classes = (AllowAny,)

    def post(self, request):
        data = request.data
        grouped_data = parse_callback_from_sendgrid(data)
        for item in grouped_data:
            update_email_history_status.delay(item)
        return LoggedResponse(data={'success': True})
