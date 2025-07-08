from rest_framework.authentication import SessionAuthentication
from rest_framework.views import APIView

from juloserver.fraud_portal.serializers.compare_page import ApplicationScoresResponse
from juloserver.fraud_portal.services.application_info import (
    get_application_info,
    get_applications_by_device,
)
from juloserver.fraud_portal.services.application_scores import get_application_scores
from juloserver.fraud_portal.services.bpjs_dukcapil_info import (
    get_bpjs_and_ducakpil_info_of_applications,
)
from juloserver.fraud_portal.services.connection_and_device import get_connection_and_device
from juloserver.fraud_portal.services.face_matching import get_face_matching_info
from juloserver.fraud_portal.services.face_similarity import get_face_similarity_info
from juloserver.fraud_portal.services.loan_info import get_loan_info
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julolog.julolog import JuloLog
from juloserver.new_crm.utils import crm_permission
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
)

logger = JuloLog(__name__)
sentry_client = get_julo_sentry_client()


class ApplicationInfo(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]

    def get(self, request):
        try:
            application_ids = request.query_params.get('application_id', None).split(",")

            if not application_ids:
                return success_response([])

            application_info = get_application_info(application_ids)

            return success_response(application_info)

        except Exception as e:
            logger.error(e)

            return general_error_response(message=str(e))


class ApplicationScores(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]
    serializer_class = ApplicationScoresResponse

    def get(self, request):
        try:

            application_ids = request.query_params.get('application_id', None).split(",")

            if not application_ids:
                return success_response([])

            application_scores = get_application_scores(application_ids)
            serialized_data = self.serializer_class(application_scores, many=True).data

            return success_response(serialized_data)
        except Exception as e:
            logger.error(e)

            return general_error_response(message=str(e))


class FaceMatching(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]

    def get(self, request):
        try:

            application_ids = request.query_params.get('application_id', None).split(",")

            if not application_ids:
                return success_response([])

            face_matching_info = get_face_matching_info(application_ids)

            return success_response(face_matching_info)

        except Exception as e:
            logger.error(e)

            return general_error_response(message=str(e))


class FaceSimilarity(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]

    def get(self, request):
        try:
            application_ids = request.query_params.get('application_id', None).split(",")

            if not application_ids:
                return success_response([])

            face_matching_info = get_face_similarity_info(application_ids)

            return success_response(face_matching_info)

        except Exception as e:
            logger.error(e)

            return general_error_response(message=str(e))


class BPJSAndDukcapilInfo(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]

    def get(self, request):
        try:
            application_ids = request.query_params.get('application_id', None).split(",")

            if not application_ids:
                return success_response([])

            bpjs_and_ducakpil_info = get_bpjs_and_ducakpil_info_of_applications(application_ids)

            return success_response(bpjs_and_ducakpil_info)
        except Exception as e:
            logger.error(e)

            return general_error_response(message=str(e))


class LoanInfo(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]

    def get(self, request):
        try:
            application_ids = request.query_params.get('application_id', None).split(",")

            if not application_ids:
                return success_response([])

            loan_info = get_loan_info(application_ids)

            return success_response(loan_info)

        except Exception as e:
            sentry_client.captureException()
            logger.error(e)

            return general_error_response(message=str(e))


class ConnectionAndDevice(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]

    def get(self, request):
        try:
            application_ids = request.query_params.get('application_id', None).split(",")

            if not application_ids:
                return success_response([])

            connection_and_device = get_connection_and_device(application_ids)

            return success_response(connection_and_device)

        except Exception as e:
            sentry_client.captureException()
            logger.error(e)

            return general_error_response(message=str(e))


class ApplicationsByDevice(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [
        crm_permission(
            [
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.FRAUD_OPS,
                JuloUserRoles.PRODUCT_MANAGER,
            ]
        )
    ]

    def get(self, request):
        try:
            android_id = request.query_params.get('android_id', None)
            ios_id = request.query_params.get('ios_id', None)

            if not android_id and not ios_id:
                return success_response([])
            elif android_id and ios_id:
                return general_error_response(
                    message='you can only use either android_id or ios_id, but not both'
                )
            elif (android_id and ',' in android_id) or (ios_id and ',' in ios_id):
                return general_error_response(message='you can only use 1 id')

            application_ids = get_applications_by_device(android_id=android_id, ios_id=ios_id)

            return success_response(application_ids)

        except Exception as e:
            logger.error(e)

            return general_error_response(message=str(e))
