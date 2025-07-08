from __future__ import division
import logging

from django.http.response import JsonResponse
from rest_framework.views import APIView
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.loan.serializers import (
    LoanDbrCheckSerializer,
    LoanDbrMonthlySalarySerializer,
)
from juloserver.loan.services.loan_related import (
    get_first_payment_date_by_application,
)
from juloserver.julo.clients import get_julo_sentry_client
from rest_framework.response import Response
from rest_framework import status

from juloserver.loan.services.dbr_ratio import (
    LoanDbrSetting,
    calculate_new_monthly_income,
    create_new_monthly_income,
)
from juloserver.loan.constants import DBRConst
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.standardized_api_response.utils import (
    success_response,
    not_found_response,
)
from juloserver.cfs.authentication import EasyIncomeTokenAuth


logger = logging.getLogger(__name__)


class LoanDbrCalculation(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = LoanDbrCheckSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        customer = request.user.customer
        account = customer.account
        application = account.get_active_application() if account else None

        if not application:
            # ignore flow if application is not exist
            data = {"popup_banner": {"is_active": False}}
            return JsonResponse({"success": True, "data": data, "errors": []})

        duration = data.get('duration')
        monthly_installment = data.get('monthly_installment')
        first_monthly_installment = data.get('first_monthly_installment')
        transaction_method_id = data.get('transaction_type_code')
        if not first_monthly_installment:
            first_monthly_installment = monthly_installment

        if not transaction_method_id:
            # default tarik dana to prevent errors
            transaction_method_id = TransactionMethodCode.SELF.code

        if not duration or not monthly_installment:
            # these data cannot be empty and cannot be 0
            # except first monthly installment because old version not using it
            get_julo_sentry_client().captureMessage(
                {
                    'error': 'LoanDbrCalculation value cannot be 0',
                    'duration': duration,
                    'monthly_installment': monthly_installment,
                    'first_monthly_installment': first_monthly_installment,
                }
            )
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    'success': False,
                    'data': {
                        'duration': duration,
                        'monthly_installment': monthly_installment,
                        'first_monthly_installment': first_monthly_installment,
                    },
                    'error': 'LoanDbrCalculation value cannot be 0',
                },
            )

        first_payment_date = get_first_payment_date_by_application(application)
        loan_dbr = LoanDbrSetting(application, True)
        loan_dbr.update_popup_banner(False, transaction_method_id)
        popup_banner = loan_dbr.popup_banner
        is_dbr_exceeded = loan_dbr.is_dbr_exceeded(
            duration=duration,
            payment_amount=monthly_installment,
            first_payment_date=first_payment_date,
            first_payment_amount=first_monthly_installment,
        )

        loan_amount = first_monthly_installment + (monthly_installment * (duration - 1))
        if not is_dbr_exceeded:
            # DBR is inactive
            popup_banner["is_active"] = False
        else:
            loan_dbr.log_dbr(
                loan_amount,
                duration,
                transaction_method_id,
                DBRConst.LOAN_CREATION,
            )

        data = {"popup_banner": popup_banner}
        return JsonResponse({"success": True, "data": data, "errors": []})


class LoanDbrNewSalary(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = LoanDbrMonthlySalarySerializer
    permission_classes = []
    authentication_classes = (EasyIncomeTokenAuth,)

    def get(self, request):
        serializer = self.serializer_class(data=request.GET)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user
        result = calculate_new_monthly_income(
            data,
            user,
        )

        if result['error']:
            return not_found_response(result['error'])

        response_data = {
            'monthly_salary': result['monthly_salary'],
            'new_monthly_salary': result['new_monthly_salary'],
        }
        return success_response(response_data)

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user
        result = calculate_new_monthly_income(
            data,
            user,
        )

        if result['error']:
            return not_found_response(result['error'])

        # insert to customer request data change
        create_new_monthly_income(
            user.customer,
            result['new_monthly_salary'],
        )
        response_data = {
            'monthly_salary': result['monthly_salary'],
            'new_monthly_salary': result['new_monthly_salary'],
        }
        return success_response(response_data)
