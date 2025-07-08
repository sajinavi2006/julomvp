import logging

from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

# from juloserver.channeling_loan.authentication import DBSAPIKeyAuthentication
from juloserver.channeling_loan.services.dbs_services import DBSUpdateLoanStatusService

logger = logging.getLogger(__name__)


class DBSUpdateLoanStatusView(APIView):
    # skip authentication for testing purpose
    # authentication_classes = (DBSAPIKeyAuthentication,)
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def post(self, request):
        return DBSUpdateLoanStatusService().process_request(request=request)
