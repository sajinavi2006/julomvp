from rest_framework.views import APIView

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account
from juloserver.autodebet.services.account_services import construct_autodebet_feature_status
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import general_error_response, success_response


class AccountStatusView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        from juloserver.application_flow.services2 import AutoDebit

        user = self.request.user

        if not hasattr(user, 'customer'):
            return general_error_response('Invalid user')

        application = user.customer.application_set.last()
        if application.product_line_code == 2 and \
                application.application_status_id >= ApplicationStatusCodes.SCRAPED_DATA_VERIFIED:
            account = Account.objects.filter(
                customer=user.customer,
                account_lookup__workflow__name=WorkflowConst.JULO_STARTER
            ).last()
        elif AutoDebit(application).has_pending_tag:
            account = Account.objects.filter(
                customer=user.customer,
                account_lookup__workflow__name__in=[
                    WorkflowConst.JULO_ONE_IOS,
                    WorkflowConst.JULO_ONE
                ]
            ).last()
        else:
            account = Account.objects.filter(
                customer=user.customer,
                status_id__gte=AccountConstant.STATUS_CODE.active,
                account_lookup__workflow__name__in=[
                    WorkflowConst.JULO_ONE,
                    WorkflowConst.JULO_STARTER,
                    WorkflowConst.JULO_ONE_IOS,
                ],
            ).last()

        if not account:
            return general_error_response("Customer tidak memiliki account")

        return success_response(
            construct_autodebet_feature_status(
                account,
                version='v3',
                app_version=request.META.get('HTTP_X_APP_VERSION'),
                platform=request.META.get('HTTP_X_PLATFORM'),
            )
        )
