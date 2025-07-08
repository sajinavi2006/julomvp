import logging

from django.http.response import JsonResponse

from juloserver.account.services.credit_limit import update_available_limit
from rest_framework.views import APIView
from django.db import transaction
from juloserver.loan.exceptions import AccountLimitExceededException

from juloserver.customer_module.models import BankAccountDestination

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin

from juloserver.julo.models import (
    Loan,
    Partner
)
from juloserver.account.models import (
    AccountLimit,
    Account
)

from juloserver.payment_point.models import TransactionMethod

from juloserver.loan.services.views_related import get_rentee_sphp_template

from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.partners import PartnerConstant
from juloserver.loan.services.loan_related import (
    calculate_installment_amount,
    generate_rentee_loan_payment_julo_one,
    refiltering_cash_loan_duration,
    update_loan_status_and_loan_history
)
from juloserver.pin.decorators import pin_verify_required

from juloserver.account.constants import TransactionType

from juloserver.loan.serializers import RenteeLoanRequestSerializer
from juloserver.loan.services.views_related import validate_loan_concurrency


from juloserver.rentee import services as rentee_service

from juloserver.standardized_api_response.utils import (
    general_error_response,
    forbidden_error_response,
    not_found_response,
    success_response)
from juloserver.julo.services import prevent_web_login_cases_check

logger = logging.getLogger(__name__)


class RenteeLoanCalculation(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = RenteeLoanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user

        account = Account.objects.get_or_none(pk=data['account_id'])
        if not account:
            return general_error_response('Account tidak ditemukan')

        if user.id != account.customer.user_id:
            return forbidden_error_response(
                data={'user_id': user.id},
                message=['User not allowed'])

        try:
            loan_detail = rentee_service.get_rentee_loan_detail(data['device_id'])
        except Exception as error:
            return general_error_response(str(error))

        provision_fee = loan_detail["provision_fee"]
        available_duration = loan_detail["available_duration"]
        loan_amount = loan_detail["loan_amount"]
        disbursement_amount = loan_detail["disbursement_amount"]
        product = loan_detail["product"]
        total_deposit_amount = loan_detail["total_deposit_amount"]
        installed_loan_amount = loan_detail["installed_loan_amount"]
        deposit_amount = loan_detail["deposit_amount"]

        application = account.application_set.last()
        account_limit = AccountLimit.objects.filter(account=application.account).last()
        loan_choice = []
        available_limit = account_limit.available_limit

        if loan_detail['installed_loan_amount'] > account_limit.available_limit:
            return general_error_response(
                "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
            )
        available_limit_after_transaction = available_limit - loan_detail['installed_loan_amount']

        available_duration = refiltering_cash_loan_duration(available_duration, application)
        for duration in available_duration:
            monthly_installment = calculate_installment_amount(
                installed_loan_amount,
                duration,
                product.monthly_interest_rate
            )
            loan_choice.append({
                'total_deposit_amount': total_deposit_amount,
                'loan_amount': loan_amount,
                'duration': duration,
                'monthly_installment': monthly_installment,
                'provision_amount': provision_fee,
                'disbursement_amount': int(disbursement_amount),
                'available_limit': available_limit,
                'available_limit_after_transaction': available_limit_after_transaction,
                'deposit_amount': deposit_amount
            })

        return JsonResponse({
            'success': True,
            'data': loan_choice,
            'errors': []
        })


def get_rentee_loan_purpose(_request):
    data = rentee_service.get_loan_purpose()
    return JsonResponse({
        'success': True,
        'data': list(data),
        'errors': []
    })


class RenteeLoanJuloOne(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = RenteeLoanRequestSerializer

    @pin_verify_required
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        account = Account.objects.get_or_none(pk=data['account_id'])
        if not account:
            return general_error_response('Account tidak ditemukan')
        application = account.application_set.last()
        user = self.request.user
        if application.customer.user != user:
            return general_error_response('User tidak sesuai dengan account')

        login_check, error_message = prevent_web_login_cases_check(user, PartnerConstant.RENTEE)
        if not login_check:
            return general_error_response(error_message)
        _, concurrency_messages = validate_loan_concurrency(application.account)
        if concurrency_messages:
            return JsonResponse({
                'success': False,
                'data': {},
                'errors': [concurrency_messages['content']]
            })

        try:
            loan_detail = rentee_service.get_rentee_loan_detail(data['device_id'])
        except Exception as error:
            return general_error_response(str(error))

        provision_fee = loan_detail["provision_fee"]
        available_duration = loan_detail["available_duration"]
        loan_amount = loan_detail["loan_amount"]
        disbursement_amount = loan_detail["disbursement_amount"]
        product = loan_detail["product"]
        loan_purpose = loan_detail["device_name"]
        installed_loan_amount = loan_detail["installed_loan_amount"]
        residual_loan_amount = loan_detail["residual_loan_amount"]

        loan_requested = dict(
            loan_amount=loan_amount,
            loan_duration_request=available_duration[0],
            interest_rate_monthly=product.monthly_interest_rate,
            product=product,
            provision_fee=provision_fee,
            installed_loan_amount=installed_loan_amount,
            residual_loan_amount=residual_loan_amount
        )

        rentee_partner = Partner.objects.get(name=PartnerConstant.RENTEE)
        bank_account_destination = BankAccountDestination.objects.get(
            customer__user_id=rentee_partner.user_id)
        credit_matrix = None

        try:
            with transaction.atomic():
                account_limit = AccountLimit.objects.select_for_update().filter(
                    account=application.account
                ).last()
                if installed_loan_amount > account_limit.available_limit:
                    raise AccountLimitExceededException(
                        "Jumlah pinjaman tidak boleh lebih besar dari limit tersedia"
                    )
                loan = generate_rentee_loan_payment_julo_one(application,
                                                             loan_requested,
                                                             loan_purpose,
                                                             credit_matrix,
                                                             bank_account_destination)

                transaction_method = TransactionMethod.objects.get(method=TransactionType.OTHER)

                loan.update_safely(
                    transaction_method=transaction_method,
                    loan_disbursement_amount=disbursement_amount
                )
                rentee_service.generate_payment_deposit(loan, data['device_id'])
                update_available_limit(loan)

        except AccountLimitExceededException as error:
            return general_error_response(str(error))

        return JsonResponse({
            'success': True,
            'data': {
                'loan_id': loan.id,
                'loan_status': loan.status,
                'loan_amount': loan.loan_amount,
                'disbursement_amount': loan.loan_disbursement_amount,
                'loan_duration': loan.loan_duration,
                'installment_amount': loan.installment_amount,
                'monthly_interest': product.monthly_interest_rate,
                'loan_xid': loan.loan_xid
            },
            'errors': []
        })


class DepositStatusView(StandardizedExceptionHandlerMixin, APIView):

    def get(self, request, loan_xid):

        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return general_error_response('Loan tidak ditemukan')

        user = request.user
        if loan.customer.user != user:
            return general_error_response('User tidak sesuai dengan account')

        result = rentee_service.get_deposit_status_by_loan(loan)
        return JsonResponse({
            'success': True,
            'data': result,
            'errors': []
        })


class RevertLoanView(StandardizedExceptionHandlerMixin, APIView):

    def post(self, request, loan_xid):
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return general_error_response('Loan tidak ditemukan')

        user = request.user
        if loan.customer.user != user:
            return general_error_response('User tidak sesuai dengan account')

        with transaction.atomic():
            is_revertable = rentee_service.update_deposit_before_reverting(loan)
            if not is_revertable:
                return general_error_response('Invalid Loan')

            update_loan_status_and_loan_history(loan_id=loan.id,
                                                new_status_code=LoanStatusCodes.INACTIVE,
                                                change_reason="Revert Rentee Loan")

        return JsonResponse({
            'success': True,
            'data': {'status': 'Done'},
            'errors': []
        })


class RenteeLoanSPHPView(StandardizedExceptionHandlerMixin, APIView):

    def get(self, request, *args, **kwargs):
        user = self.request.user
        loan_xid = kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return not_found_response("Loan XID:{} Not found".format(loan_xid))

        if user.id != loan.customer.user_id:
            return forbidden_error_response(
                data={'user_id': user.id},
                message=['User not allowed'])

        text_sphp = get_rentee_sphp_template(loan.id, type="android")
        return success_response(data=text_sphp)
