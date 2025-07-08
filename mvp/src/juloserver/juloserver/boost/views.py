from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from juloserver.application_flow.tasks import fraud_bpjs_or_bank_scrape_checking
from juloserver.julo.exceptions import ApplicationNotFound
from juloserver.julo.models import Application
from juloserver.julolog.julolog import JuloLog
from juloserver.standardized_api_response.mixin import (
    StandardizedExceptionHandlerMixin,
    StandardizedExceptionHandlerMixinV2,
)
from juloserver.standardized_api_response.utils import (
    forbidden_error_response,
    general_error_response,
    success_response,
)

from .constants import BoostBankConst, BoostBPJSConst
from .serializers import BoostStatusViewSerializer
from .services import get_boost_status, get_boost_status_at_homepage, save_boost_forms

logger = JuloLog()


class BoostStatusView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request: Request, application_id: int) -> Response:
        workflow_name = request.GET.get('workflow_name')
        data = dict()
        user = self.request.user

        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            logger.warning(message="Application not found", request=request)
            return general_error_response("ApplicationNotFound", {'msg': "Data sending failed"})

        if user.id != application.customer.user_id:
            log_data = {"user_id": str(user.id), "message": "User not allowed"}
            logger.warning(log_data, request=request)
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        data = get_boost_status(application_id, workflow_name)
        bank_statuses = data.get('bank_status')
        boost_bank_verifed = BoostBankConst.VERIFIED

        bank_status_verified = False
        if bank_statuses:
            bank_status_verified = any(dic['status'] == boost_bank_verifed for dic in bank_statuses)

        if data.get('bpjs_status') == BoostBPJSConst.VERIFIED or bank_status_verified:

            # do checking for fraud
            fraud_bpjs_or_bank_scrape_checking.apply_async(
                kwargs={'application_id': application_id}
            )

        return success_response(data=data)


class BoostDataUpdate(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request, application_id):
        data = request.data.copy()
        serializer = BoostStatusViewSerializer(data=data)
        user = self.request.user

        if not serializer.is_valid():
            logger.warning(
                {"message": "Data sending failed", "application_id": application_id},
                request=request,
            )
            return general_error_response(serializer.errors, {'msg': "Data sending failed"})

        try:
            application = Application.objects.get_or_none(pk=application_id)

            if user.id != application.customer.user_id:
                logger.warning(
                    {
                        "message": "User not allowed",
                        "application_id": application_id,
                        "user_id": user.id,
                    },
                    request=request,
                )
                return forbidden_error_response(
                    data={'user_id': user.id}, message=['User not allowed']
                )

            update_data = save_boost_forms(application_id, serializer.data)

        except ApplicationNotFound:
            logger.error(
                {"message": "Application not Found", "application_id": application_id},
                request=request,
            )
            return general_error_response("ApplicationNotFound", {'msg': "Data sending failed"})

        update_data['msg'] = "Data successfully send"
        logger.info(
            {"message": "Data successfully send", "application_id": application_id}, request=request
        )
        return success_response(update_data)


class BoostStatusAtHomepageView(StandardizedExceptionHandlerMixinV2, APIView):

    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def get(self, request, application_id):
        workflow_name = request.GET.get('workflow_name')
        app_version_header = request.META.get('HTTP_X_APP_VERSION')
        user = self.request.user
        try:
            application = Application.objects.get_or_none(pk=application_id)

            if application:
                if user.id != application.customer.user_id:
                    logger.warning(
                        {
                            "message": "User not allowed",
                            "application_id": application_id,
                            "user_id": user.id,
                        },
                        request=request,
                    )
                    return forbidden_error_response(
                        data={'user_id': user.id}, message=['User not allowed']
                    )

            data = get_boost_status_at_homepage(application_id, workflow_name, app_version_header)
        except ApplicationNotFound:
            logger.error(
                {"message": "Application not Found", "application_id": application_id},
                request=request,
            )
            return general_error_response("ApplicationNotFound", {'msg': "Data sending failed"})

        logger.info(
            {"message": "Data successfully", "application_id": application_id, "data": data},
            request=request,
        )
        return success_response(data=data)
