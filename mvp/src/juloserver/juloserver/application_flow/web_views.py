import logging

from rest_framework.views import APIView

from juloserver.apiv1.data import DropDownData
from juloserver.apiv1.dropdown import BirthplaceDropDown
from juloserver.application_flow.serializers import ResubmitBankAccountSerializer
from juloserver.julo.models import Application, Bank, LoanPurpose
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response,
)

from ..standardized_api_response.mixin import StandardizedExceptionHandlerMixin

logger = logging.getLogger(__name__)


class DropDownApi(APIView, StandardizedExceptionHandlerMixin):
    def get(self, request):
        data = {
            "companies": DropDownData(DropDownData.COMPANY)._select_data(),
            "job": DropDownData(DropDownData.JOB)._select_data(),
            "loan_purposes": LoanPurpose.objects.all().values_list('purpose', flat=True),
            "home_statuses": [x[0] for x in Application().HOME_STATUS_CHOICES],
            "job_types": list(
                set([x[0] for x in Application().JOB_TYPE_CHOICES])
                - set(['Pekerja rumah tangga', 'Lainnya'])
            ),
            "kin_relationships": [x[0] for x in Application().KIN_RELATIONSHIP_CHOICES],
            "last_educations": [x[0] for x in Application().LAST_EDUCATION_CHOICES],
            "marital_statuses": [x[0] for x in Application().MARITAL_STATUS_CHOICES],
            "vehicle_types": list(
                set([x[0] for x in Application().VEHICLE_TYPE_CHOICES]) - set(['Lainnya'])
            ),
            "vehicle_ownerships": [x[0] for x in Application().VEHICLE_OWNERSHIP_CHOICES],
            "birth_places": BirthplaceDropDown().DATA,
        }
        return success_response(data)


class ResubmitBankAccount(APIView, StandardizedExceptionHandlerMixin):
    def post(self, request):
        serializer = ResubmitBankAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_data = serializer.validated_data

        customer = request.user.customer

        # get last application
        last_application = customer.application_set.regular_not_deletes().last()
        if not last_application:
            return not_found_response('customer belum mempunyai application')

        bank = Bank.objects.filter(xfers_bank_code=request_data['bank_code']).last()
        if not bank:
            return general_error_response('Bank code tidak dikenal')
        last_application.update_safely(
            bank_name=bank.bank_name,
            bank_account_number=request_data['account_number'],
            name_in_bank=request_data['name_in_bank'],
        )
        last_application.refresh_from_db()
        return success_response(
            {
                'application_id': last_application.id,
                'bank_name': last_application.bank_name,
                'bank_account_number': last_application.bank_account_number,
                'name_in_bank': last_application.name_in_bank,
            }
        )
