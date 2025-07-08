import logging

from rest_framework.views import APIView

from juloserver.fraud_score.constants import TrustGuardConst
from juloserver.fraud_score.juicy_score_services import check_application_exist_in_result
from juloserver.fraud_score.juicy_score_tasks import execute_juicy_score_result
from juloserver.fraud_score.models import TrustGuardApiRequest
from juloserver.fraud_score.serializers import (
    JuicyScoreRequestSerializer,
    TrustGuardRequestSerializer,
    TrustGuardBlackboxRequestSerializer,
)
from juloserver.fraud_score.trust_decision_tasks import execute_trust_guard_for_loan_event
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    Application,
    FeatureSetting,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    not_found_response,
)

logger = logging.getLogger(__name__)


class TrustGuardScoreView(StandardizedExceptionHandlerMixinV2, APIView):
    """
    Trust Guard Integration.
    """
    serializer_class = TrustGuardRequestSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        application_id = data.get('application_id')
        black_box = data.get('black_box')
        event_type = data.get('event_type')
        device_type = request.META.get(
            "HTTP_X_PLATFORM", TrustGuardConst.DeviceType.ANDROID
        ).lower()

        logger.info(
            {
                'function': 'TrustGuardScoreView',
                'application_id': application_id,
                'black_box': black_box,
                'device_type': device_type,
            }
        )

        if not event_type:
            event_type = TrustGuardConst.EventType.APPLICATION[0]

        application = request.user.customer.application_set.get_or_none(id=application_id)
        if not application:
            return general_error_response('Application does not exist.')

        execute_trust_guard_for_loan_event.delay(
            application_id, black_box, event_type, device_type=device_type
        )

        return success_response({
            'message': 'Blackbox string received.',
        })


class JuicyScoreView(APIView):
    serializer_class = JuicyScoreRequestSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.JUICY_SCORE_FRAUD_SCORE,
            is_active=True,
        ).last()

        if not feature_setting:
            logger.warning({
                'action': 'juicy_score view feature setting check',
                'data': data,
                'message': 'Juicy Score feature is not found or inactive'
            })
            return general_error_response('Juicy Score feature is not found or inactive')

        application_id = data['application_id']

        customer_id = request.user.customer.id
        data.update({"customer_id": customer_id})
        if check_application_exist_in_result(application_id):
            logger.warning({
                'action': 'juicy_score view check application exist in result',
                'data': data,
                'message': 'Application id is exist in result'
            })
            return general_error_response('not valid request')

        application = Application.objects.filter(pk=application_id, customer_id=customer_id).last()
        if not application:
            logger.info({
                'action': 'juicy_score view check application and customer',
                'application_id': application_id,
                'customer_id': customer_id,
                'message': 'Application does not exist.'
            })
            return not_found_response("not valid request")
        delay_time = feature_setting.parameters["delay_time"]
        logger.info({
            'action': 'juicy_score view send data to task with delay {0}s'.format(delay_time),
            'application_id': application_id,
            'customer_id': customer_id
        })
        execute_juicy_score_result.apply_async((data, application_id, customer_id),
                                               countdown=delay_time)

        return success_response(
            {
                'message': 'Success',
            }
        )


class TrustGuardBlackBoxView(StandardizedExceptionHandlerMixinV2, APIView):
    """
    Trust Guard API to store a blackbox.
    """

    serializer_class = TrustGuardBlackboxRequestSerializer

    def post(self, request, *args, **kwargs):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            application_id = data.get('application_id')
            black_box = data.get('black_box')
            device_type = request.META.get(
                "HTTP_X_PLATFORM", TrustGuardConst.DeviceType.ANDROID
            ).lower()

            logger.info(
                {
                    'function': 'TrustGuardBlackBoxView',
                    'application_id': application_id,
                    'black_box': black_box,
                    'device_type': device_type,
                }
            )

            application = request.user.customer.application_set.get_or_none(id=application_id)

            if not application:
                return general_error_response('Application does not exist.')

            TrustGuardApiRequest.objects.create(
                application=application,
                black_box=str(black_box),
                device_type=device_type,
            )
            return success_response(
                {
                    'message': 'Blackbox string received.',
                }
            )
        except Exception as e:
            logger.error(e)

            return general_error_response(message=str(e))
