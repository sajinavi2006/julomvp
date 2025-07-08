from juloserver.julolog.julolog import JuloLog
from builtins import str

from django.db import transaction
from rest_framework.generics import CreateAPIView, UpdateAPIView
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_400_BAD_REQUEST
from rest_framework.views import APIView

from juloserver.ana_api.constants import MINIMUM_INCOME
from juloserver.ana_api.models import PdBankScrapeModelResult
from juloserver.ana_api.services import process_dsd_completion
from juloserver.apiv2.models import PdCreditModelResult
from juloserver.apiv2.services import get_credit_score3, get_eta_time_for_c_score_delay
from juloserver.ios.services import get_credit_score_ios
from juloserver.application_flow.services import (
    bpjs_nik_mismatch_fraud_check,
    is_experiment_application,
)
from juloserver.ios.tasks import handle_iti_ready_ios
from juloserver.application_flow.tasks import (
    handle_iti_ready,
    handle_process_bypass_julo_one_at_120,
    handle_process_bypass_julo_one_at_122,
)
from juloserver.julo.exceptions import JuloInvalidStatusChange
from juloserver.julo.formulas.experiment import calculation_affordability
from juloserver.julo.models import (
    Application,
    ApplicationFieldChange,
    ApplicationNote,
    DeviceScrapedData,
)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tasks import send_pn_etl_done
from juloserver.julo.utils import post_anaserver
from juloserver.julo.workflows2.tasks import do_advance_ai_id_check_task
from juloserver.moengage.services.use_cases import (
    update_moengage_for_application_status_change_event,
)
from juloserver.partnership.tasks import trigger_partnership_callback
from juloserver.paylater.services import get_paylater_credit_score
from juloserver.portal.object.bulk_upload.services import (
    run_merchant_financing_upload_csv,
)
from juloserver.sdk.services import get_credit_score_partner
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response,
)

from .serializers import (
    DeviceScrapedDataSerializer,
    EtlPushNotificationUpdateStatusSerializer,
    PredictBankScrapCallbackSerializer,
    SkipTraceSerializer,
    StatusChangeSerializer,
    DSDCompletionSerializer,
)
from .services import process_etl_push_notification_update_status
from .utils import check_app_cs_v20b
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2

logger = JuloLog(__name__)


class IsAdminUser(BasePermission):
    """
    Allows access only to admin users.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_staff


class ChangeApplicationStatus(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        ser = StatusChangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ret_data = {'status': 'ok'}
        try:
            process_application_status_change(**dict(ser.data))
        except JuloInvalidStatusChange as e:
            ret_data = {'status': 'error', 'errors': str(e)}
        return Response(status=HTTP_200_OK, data=ret_data)


class UpdateDeviceScrapeData(UpdateAPIView):
    permission_classes = [
        IsAdminUser,
    ]
    serializer_class = DeviceScrapedDataSerializer
    queryset = DeviceScrapedData.objects.all()


class CreateDeviceScrapeData(CreateAPIView):
    permission_classes = [
        IsAdminUser,
    ]
    serializer_class = DeviceScrapedDataSerializer


class PredictBankScrapeCallback(APIView):
    serializer_class = PredictBankScrapCallbackSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response('invalid params')

        app = Application.objects.get_or_none(id=serializer.data['application_id'])
        if not app:
            return not_found_response('application not found')

        logger.info(
            message='predict bank scrape data callback response, data=%s' % serializer.data,
            request=request,
        )
        if serializer.data['status'] == 'success':
            bank_scrape_result = PdBankScrapeModelResult.objects.filter(
                application_id=app.id
            ).last()
            if bank_scrape_result and bank_scrape_result.processed_income > MINIMUM_INCOME:
                old_monthly_income_value = app.monthly_income
                with transaction.atomic():
                    app.update_safely(monthly_income=bank_scrape_result.processed_income)
                    ApplicationFieldChange.objects.create(
                        application=app,
                        field_name='monthly_income',
                        old_value=old_monthly_income_value,
                        new_value=app.monthly_income,
                    )
                    ApplicationNote.objects.create(
                        note_text='change monthly income by bank scrape model',
                        application_id=app.id,
                    )

        return success_response('Updated monthly income successful!')


class CreateSkipTrace(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        many = isinstance(request.data, list)
        ser = SkipTraceSerializer(data=request.data, many=many)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(status=HTTP_201_CREATED, data=ser.data)


class EtlPushNotification(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        if 'application' not in request.data:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'application': "This field is required"}
            )
        application = Application.objects.get_or_none(pk=request.data['application'])
        if application:
            logger.info(
                {'message': 'call EtlPushNotification.post()', 'application_id': application.id}
            )
            is_app_cs_v20b = check_app_cs_v20b(application)
            b_credit_model_result = PdCreditModelResult.objects.filter(
                application_id=application.id, credit_score_type='B'
            ).last()
            if is_app_cs_v20b and (not b_credit_model_result):
                ana_data = {'application_id': application.id}
                url = '/api/amp/v1/credit-score-advance/'
                post_anaserver(url, json=ana_data)
                update_moengage_for_application_status_change_event.delay(
                    status=ApplicationStatusCodes.FORM_PARTIAL, application_id=application.id
                )
                return Response(status=HTTP_201_CREATED)
            if application.is_julo_one_ios():
                get_score = get_credit_score_ios(application, skip_delay_checking=True)
            else:
                get_score = get_credit_score3(application, skip_delay_checking=True)

            if not application.is_julo_one() and not application.is_julo_one_ios():
                if get_score.score.upper() == 'C':
                    eta_time = get_eta_time_for_c_score_delay(application)
                    send_pn_etl_done.apply_async(
                        (
                            request.data['application'],
                            request.data['success'],
                            get_score.score.upper(),
                        ),
                        eta=eta_time,
                    )
                else:
                    send_pn_etl_done.delay(
                        request.data['application'],
                        request.data['success'],
                        get_score.score.upper(),
                    )
            update_moengage_for_application_status_change_event.delay(
                status=ApplicationStatusCodes.FORM_PARTIAL, application_id=application.id
            )
            return Response(status=HTTP_201_CREATED)
        else:
            return Response(status=HTTP_400_BAD_REQUEST)


class ObpNotification(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        # since itiv5 this fasttrack experiment is disabled

        # application_id = int(request.data['application'])
        # application = Application.objects.get_or_none(pk=application_id)
        # experiment_service = get_bypass_iti_experiment_service()
        # experiment_service.bypass_fasttrack_122(application)
        return Response(status=HTTP_200_OK)


class EtlPushNotificationPartner(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        credit_score = get_credit_score_partner(request.data['application'])
        application = Application.objects.get_or_none(pk=request.data['application'])

        # run advance AI
        if credit_score:
            if credit_score.score == "C":
                if application.status >= ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
                    process_application_status_change(
                        request.data['application'],
                        ApplicationStatusCodes.APPLICATION_DENIED,
                        "auto_failed_in_credit_score",
                    )
            else:
                do_advance_ai_id_check_task.delay(request.data['application'])

        return Response(status=HTTP_201_CREATED)


class PaylaterScoreCallback(APIView):
    permission_classes = [
        IsAdminUser,
    ]
    http_method_names = ['post']

    def post(self, request):
        if 'application' not in request.data:
            return Response(
                status=HTTP_400_BAD_REQUEST, data={'application': "This field is required"}
            )
        if request.data['success']:
            get_paylater_credit_score(request.data['application'])
        return Response(status=HTTP_200_OK)


class EtlPushNotificationWeb(APIView):
    """Get feedback from ana server when credit score is ready"""

    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        application = Application.objects.get_or_none(pk=request.data['application'])
        if not application:
            return Response(status=HTTP_400_BAD_REQUEST)
        get_credit_score3(application)
        if application.is_partnership_app() or application.is_partnership_webapp():
            trigger_partnership_callback.delay(application.id, application.application_status_id)

        return Response(status=HTTP_201_CREATED)


class ItiPushNotification(APIView):
    """
    POST API provided for ANA so it can notify when the Income Trust Index is ready.
    """

    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        application = Application.objects.get_or_none(pk=request.data['application'])
        if not application:
            return Response(status=HTTP_400_BAD_REQUEST)

        logger.info(
            {
                "message": "Function call -> ItiPushNotification.post",
                "application_id": application.id,
            },
            request=request,
        )

        calculation_affordability(
            application.id,
            application.monthly_income,
            application.monthly_housing_cost,
            application.monthly_expenses,
            application.total_current_debt,
        )
        if is_experiment_application(application.id, 'ExperimentUwOverhaul'):
            if application.status == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
                handle_process_bypass_julo_one_at_120.delay(application.id)
            else:
                if application.is_julo_one_ios():
                    handle_iti_ready_ios.delay(application.id)
                else:
                    handle_iti_ready.delay(application.id)
        elif application.is_julo_one() or application.is_julo_starter():
            if application.status == ApplicationStatusCodes.DOCUMENTS_VERIFIED:
                handle_process_bypass_julo_one_at_122.delay(application.id)
            else:
                if application.is_julo_one_ios():
                    handle_iti_ready_ios.delay(application.id)
                else:
                    handle_iti_ready.delay(application.id)
        return Response(status=HTTP_201_CREATED)


class UpdateApplicationRiskyCheck(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        try:
            application = Application.objects.get_or_none(pk=request.data['application_id'])
            if not application:
                return Response(status=HTTP_400_BAD_REQUEST)
            bpjs_nik_mismatch_fraud_check(application)
            return Response(status=HTTP_200_OK)
        except Exception:
            return Response(status=HTTP_400_BAD_REQUEST)


class UpdateMerchantBinaryCheckScore(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        try:
            application = Application.objects.get_or_none(pk=request.data['application_id'])
            if not application:
                return general_error_response(
                    'application id({}) not found.'.format(request.data['application_id'])
                )
            merchant = application.merchant
            if not merchant:
                return general_error_response(
                    'merchant not found for application id {}'.format(application.id)
                )
            merchant_score = request.data['merchant_score']
            if not merchant_score and merchant_score != 0:
                return general_error_response('merchant_score not found')

            merchant.business_rules_score = float(merchant_score)
            merchant.save(update_fields=['business_rules_score'])
            return success_response()
        except Exception as e:
            return general_error_response(str(e))


class EtlPushNotificationUpdateStatus(APIView):
    serializer_class = EtlPushNotificationUpdateStatusSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response('invalid params')
        etl_job_id = serializer.data['etl_job_id']
        process_etl_push_notification_update_status(etl_job_id)
        return success_response()


class UpdateCSVPartnerApplicationStatus(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        try:
            application = Application.objects.get_or_none(pk=request.data['application_id'])
            if not application:
                return general_error_response(
                    'application id({}) not found.'.format(request.data['application_id'])
                )

            _, msg = run_merchant_financing_upload_csv(application=application)
            return success_response(msg)
        except Exception as e:
            return general_error_response(str(e))


class JuloStarterNotification(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        from juloserver.julo_starter.tasks import (
            handle_julo_starter_generated_credit_model,
        )

        application = Application.objects.get_or_none(pk=request.data['application'])
        if not application:
            return Response(status=HTTP_400_BAD_REQUEST)

        if application.is_julo_starter():
            handle_julo_starter_generated_credit_model.delay(application.id)

        return Response(status=HTTP_201_CREATED)


class JuloStarterBinary(APIView):
    permission_classes = [
        IsAdminUser,
    ]

    def post(self, request):
        from juloserver.julo_starter.tasks import handle_julo_starter_binary_check_result

        if not request.data['success']:
            logger.error(
                {
                    'message': 'Response callback not success JuloStarterBinary',
                    'application': request.data.get('application', None),
                }
            )
            return Response(status=HTTP_400_BAD_REQUEST)

        application = Application.objects.get_or_none(pk=request.data['application'])
        if not application:
            logger.error(
                {
                    'message': 'Invalid case not found application',
                    'application': request.data.get('application', None),
                }
            )
            return Response(status=HTTP_400_BAD_REQUEST)

        if application.is_julo_starter():
            handle_julo_starter_binary_check_result.delay(application.id)
            logger.info(
                {
                    'message': 'Execute function handle_julo_starter_binary_check_result',
                    'application': application.id,
                }
            )

        return Response(status=HTTP_201_CREATED)


class FDCCalculationReady(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = [
        IsAdminUser,
    ]
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def post(self, request):

        application_id = request.data['application']
        application = Application.objects.filter(pk=application_id).last()
        if not application:
            logger.error(
                {
                    'message': 'Application not found',
                    'application_id': application_id,
                }
            )
            return not_found_response('Application not found')

        # can as trigger to run other process if calculation is done.
        return Response(status=HTTP_200_OK)


class DSDCallbackReady(StandardizedExceptionHandlerMixinV2, APIView):
    permission_classes = [
        IsAdminUser,
    ]
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }
    serializer_class = DSDCompletionSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response('invalid params')

        application_id = serializer.data['application']
        application = Application.objects.filter(pk=application_id).last()
        if not application:
            logger.error(
                {
                    'message': 'Application not found',
                    'application_id': application_id,
                }
            )
            return not_found_response('Application not found')

        process_dsd_completion(application, serializer.data['success'])

        # can as trigger to run other process if calculation is done.
        return Response(status=HTTP_200_OK)
