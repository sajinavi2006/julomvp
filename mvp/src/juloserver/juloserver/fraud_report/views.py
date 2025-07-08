from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication
from django.http import Http404
from django.shortcuts import get_object_or_404

from juloserver.portal.object import julo_login_required_multigroup, julo_login_required
from juloserver.fraud_report.serializers import FraudReportSubmitSerializer
from juloserver.standardized_api_response.utils import (
    success_response, general_error_response, not_found_response)
from juloserver.julo.models import Application
from juloserver.fraud_report.services import FraudReportService, get_downloadable_response
from juloserver.standardized_api_response.mixin import StrictStandardizedExceptionHandlerMixin


class FraudReportSubmitView(StrictStandardizedExceptionHandlerMixin, APIView):
    serializer_class = FraudReportSubmitSerializer

    def post(self, request):
        customer = request.user.customer
        application = customer.application_set.regular_not_deletes().last()
        if not application:
            return not_found_response('Application not found')
        proof_files = request.FILES.getlist('proof')
        if not proof_files:
            return general_error_response('Atleast one proof file is required')
        if len(proof_files) > 10:
            return general_error_response('Only up to 10 proof files are allowed')
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            fraud_report_service = FraudReportService(application=application,
                proof_files=proof_files, validated_data=serializer.validated_data)
            fraud_report_service.save_and_email_fraud_report()
            return success_response('Fraud has been reported')
        else:
            return general_error_response('Bad Params', serializer.errors)


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'cs_team_leader'])
class DownloadFraudReport(StrictStandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    def get(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
            response = get_downloadable_response(application)
            return response
        except Http404:
            return general_error_response('Application not found')
