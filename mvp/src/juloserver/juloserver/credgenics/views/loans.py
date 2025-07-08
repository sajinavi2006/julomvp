from rest_framework.authentication import SessionAuthentication
from rest_framework.views import APIView


from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.new_crm.utils import crm_permission
from juloserver.standardized_api_response.utils import (
    success_response,
    custom_bad_request_response,
)

from juloserver.credgenics.tasks.loans import (
    send_credgenics_csv_oss_url_to_agent,
)


class GenerateCredgenicsLoanCSV(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.PRODUCT_MANAGER,
                JuloUserRoles.OPS_REPAYMENT,
            ]
        )
    ]

    def post(self, request):

        customer_ids = request.data.get('customer_ids', [])
        if not customer_ids:
            return custom_bad_request_response('lorem ipsum')

        agent_id = request.user.id
        if not agent_id:
            return custom_bad_request_response('lorem ipsum')

        send_credgenics_csv_oss_url_to_agent.delay(
            customer_ids=customer_ids,
            requestor_agent_id=agent_id,
        )

        return success_response('success')
