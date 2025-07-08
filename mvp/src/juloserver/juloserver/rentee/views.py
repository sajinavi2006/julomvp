from rest_framework.views import APIView

from rest_framework import status as HTTPStatus
from django.http.response import JsonResponse

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import general_error_response

from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.models import Loan

from .services import check_verification_code, update_verified_code, get_active_loan_by_customer


class CheckVerificationCodeView(StandardizedExceptionHandlerMixin, APIView):

    def post(self, request, loan_xid):
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return general_error_response('Loan tidak ditemukan')

        user = request.user
        if loan.customer.user != user:
            return general_error_response('User tidak sesuai dengan account')

        if loan.status != LoanStatusCodes.INACTIVE:
            return general_error_response('Invalid Loan')

        result = check_verification_code(str(request.data['code']), loan)
        if result:
            update_verified_code(loan)

        return JsonResponse({
            'success': True,
            'data': {'result': result},
            'errors': []
        })


class RenteeLoanView(StandardizedExceptionHandlerMixin, APIView):
    exclude_raise_error_sentry_in_status_code = {
        HTTPStatus.HTTP_400_BAD_REQUEST,
        HTTPStatus.HTTP_401_UNAUTHORIZED,
        HTTPStatus.HTTP_403_FORBIDDEN,
        HTTPStatus.HTTP_404_NOT_FOUND,
        HTTPStatus.HTTP_405_METHOD_NOT_ALLOWED,
    }

    def get(self, request):
        customer = request.user.customer
        loan_data = get_active_loan_by_customer(customer)

        return JsonResponse({
            'success': True,
            'data': loan_data,
            'errors': []
        })
