import logging

from juloserver.julo.models import Loan

from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.loan.services.agreement_related import get_text_agreement_by_document_type
from juloserver.loan.services.views_v4_related import LoanAgreementDetailsV4Service
from juloserver.loan.views.views_api_v3 import LoanCalculation
from rest_framework.views import APIView
from juloserver.loan.exceptions import (
    LoanNotBelongToUser,
    LoanNotFound,
)
from juloserver.pin.decorators import parse_device_ios_user
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    forbidden_error_response,
    general_error_response,
    success_response, not_found_response,
)


logger = logging.getLogger(__name__)


class LoanCalculationView(LoanCalculation):

    @parse_device_ios_user
    def post(self, request, *args, **kwargs):

        # moved insurance logic back to v3 for correct calculation
        # this v4 api might be made deprecated
        response = super(LoanCalculationView, self).post(request)

        return response


class LoanAgreementDetailsView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, loan_xid):
        try:
            service = LoanAgreementDetailsV4Service(
                query_params=request.query_params,
                user=request.user,
                loan_xid=loan_xid,
            )
            service.verify_loan_access()
            response_data = service.get_response_data()

        except LoanNotFound:
            return general_error_response(
                message="Loan XID:{} Not Found or Expired".format(loan_xid)
            )
        except LoanNotBelongToUser:
            return forbidden_error_response(
                data={'user_id': request.user.id}, message=['User not allowed']
            )

        return success_response(data=response_data)


class LoanAgreementContentView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        user = request.user
        document_type = request.query_params.get('document_type', None)
        if document_type not in LoanAgreementType.LIST_SHOWING_ON_UI:
            return general_error_response("Document type not found")

        loan_xid = kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return not_found_response("Loan XID:{} Not found".format(loan_xid))
        if user.id != loan.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        text_agreement, data_extension = get_text_agreement_by_document_type(loan, document_type)

        return success_response({
            'data': text_agreement,
            'data_extension': data_extension,
        })
