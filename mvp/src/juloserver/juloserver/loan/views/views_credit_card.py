from __future__ import division

import logging

from django.utils import timezone

from rest_framework.views import APIView

from datetime import timedelta

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.julo.models import Loan
from juloserver.julo.statuses import LoanStatusCodes

from juloserver.account.models import AccountLimit
from juloserver.loan.serializers import (
    UpdateLoanSerializer,
    CreditCardLoanSPHPViewSerializer,
)
from juloserver.loan.services.loan_related import (
    get_credit_matrix_and_credit_matrix_product_line,
    get_loan_amount_by_transaction_type,
    get_loan_duration,
    get_first_payment_date_by_application,
    calculate_installment_amount,
    compute_first_payment_installment_julo_one,
    update_loan,
)
from juloserver.loan.constants import GoogleDemo
from juloserver.loan.services.agreement_related import get_loan_agreement_template_julo_one

from ..services.adjusted_loan_matrix import validate_max_fee_rule

from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod

from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    internal_server_error_response,
    not_found_response,
    forbidden_error_response,
    request_timeout_response,
)

from juloserver.credit_card.tasks.transaction_tasks import assign_loan_credit_card_to_lender_task


logger = logging.getLogger(__name__)


class LoanCalculation(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        transaction_method_id = TransactionMethodCode.CREDIT_CARD.code
        transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
        transaction_type = TransactionMethodCode.CREDIT_CARD.name
        is_payment_point = False
        self_bank_account = False
        loan = Loan.objects.filter(
            loan_status_id=LoanStatusCodes.INACTIVE,
            transaction_method=transaction_method,
            customer=request.user.customer
        ).last()

        if not loan:
            return general_error_response('pinjaman tidak ditemukan')

        application = loan.get_application
        account = loan.account
        credit_matrix, credit_matrix_product_line = \
            get_credit_matrix_and_credit_matrix_product_line(
                application,
                self_bank_account,
                is_payment_point,
                transaction_type
            )

        account_limit = AccountLimit.objects.filter(account=application.account).last()
        loan_amount_request = loan.loan_disbursement_amount
        available_duration = get_loan_duration(
            loan_amount_request,
            credit_matrix_product_line.max_duration,
            credit_matrix_product_line.min_duration,
            account_limit.set_limit,
            customer=account.customer,
            application=application,
        )
        available_duration = [1] if loan_amount_request <= 100000 else available_duration
        is_loan_one = available_duration[0] == 1

        if not available_duration:
            return general_error_response('Gagal mendapatkan durasi pinjaman')
        expire_ts = timezone.localtime(loan.cdate) + timedelta(minutes=5)
        loan_choice = {
            'expire_time': expire_ts,
            'transaction_ts': timezone.localtime(loan.cdate),
            'disbursement_amount': loan.loan_disbursement_amount,
            'loan_xid': loan.loan_xid,
            'durations': []
        }
        origination_fee_pct = credit_matrix.product.origination_fee_pct
        loan_amount = get_loan_amount_by_transaction_type(loan_amount_request,
                                                          origination_fee_pct,
                                                          self_bank_account)
        today_date = timezone.localtime(timezone.now()).date()

        first_payment_date = get_first_payment_date_by_application(application)

        # filter out duration less than equal 2 month for google demo account
        if account.customer.email == GoogleDemo.EMAIL_ACCOUNT:
            for i in range(1, 3):
                if i in available_duration:
                    available_duration.remove(i)
                    # if 1 and 2 is the only duration available, replace it by 3
                    if not available_duration:
                        available_duration.append(3)

        monthly_interest_rate = credit_matrix.product.monthly_interest_rate
        self_bank_account = False
        for duration in available_duration:
            (
                is_exceeded,
                _,
                max_fee_rate,
                provision_fee_rate,
                adjusted_interest_rate,
                _,
                _,
            ) = validate_max_fee_rule(
                first_payment_date, monthly_interest_rate, duration, origination_fee_pct
            )

            if is_exceeded:
                # adjust loan amount based on new provision
                if origination_fee_pct != provision_fee_rate and not self_bank_account:
                    loan_amount = get_loan_amount_by_transaction_type(
                        loan_amount_request,
                        provision_fee_rate,
                        self_bank_account)
                monthly_interest_rate = adjusted_interest_rate

            monthly_installment = calculate_installment_amount(
                loan_amount,
                duration,
                monthly_interest_rate
            )

            if is_loan_one and not is_exceeded:
                _, _, monthly_installment = compute_first_payment_installment_julo_one(
                    loan_amount, duration, monthly_interest_rate,
                    today_date, first_payment_date
                )

            loan_choice['durations'].append({
                'loan_amount': loan_amount,
                'duration': duration,
                'is_default': True if duration == loan.loan_duration else False,
                'monthly_interest': round(monthly_interest_rate * 100, 1),
                'monthly_installment': monthly_installment,
            })

        return success_response(loan_choice)


class SubmitLoan(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        try:
            loan = Loan.objects.filter(
                loan_status_id=LoanStatusCodes.INACTIVE,
                transaction_method_id=TransactionMethodCode.CREDIT_CARD.code,
                customer=request.user.customer
            ).last()

            if not loan:
                return general_error_response('tidak ditemukan')

            assign_loan_credit_card_to_lender_task.delay(loan.id)

            return success_response()
        except Exception as e:
            return internal_server_error_response(str(e))


class UpdateLoan(StandardizedExceptionHandlerMixin, APIView):
    def patch(self, request, *args, **kwargs):
        serializer = UpdateLoanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        loan = Loan.objects.filter(
            transaction_method_id=TransactionMethodCode.CREDIT_CARD.code,
            customer=request.user.customer,
            loan_xid=kwargs['loan_xid']
        ).last()

        if not loan:
            return general_error_response('Transaksi tidak ditemukan')

        today_ts = timezone.localtime(timezone.now())
        loan_amount_request = loan.loan_disbursement_amount
        response_data = {
            'transaction_ts': today_ts,
            'disbursement_amount': loan_amount_request,
            'loan_duration': data['loan_duration']
        }

        expire_ts = timezone.localtime(loan.cdate) + timedelta(minutes=5)
        if today_ts > expire_ts or loan.loan_status_id != LoanStatusCodes.INACTIVE:
            return request_timeout_response('Waktu telah habis', response_data)

        application = loan.get_application
        credit_matrix, credit_matrix_product_line = \
            get_credit_matrix_and_credit_matrix_product_line(
                application,
                False,
                False,
                TransactionMethodCode.CREDIT_CARD.name
            )
        if not credit_matrix or not credit_matrix.product:
            return general_error_response('Product tidak ditemukan', response_data)

        account_limit = application.account.accountlimit_set.last()
        available_duration = get_loan_duration(
            loan_amount_request,
            credit_matrix_product_line.max_duration,
            credit_matrix_product_line.min_duration,
            account_limit.set_limit,
            customer=application.customer,
            application=application,
        )
        if not available_duration:
            return general_error_response('tenor tidak tersedia', response_data)

        available_duration = [1] if loan_amount_request <= 100000 else available_duration

        if data['loan_duration'] not in available_duration:
            return general_error_response('tenor yang dipilih salah', response_data)

        update_loan(loan, data['loan_duration'])

        return success_response(response_data)


class CreditCardLoanSPHPView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        serializer = CreditCardLoanSPHPViewSerializer(data=request.GET.dict())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user
        loan_xid = data['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            return not_found_response("Loan XID:{} Not found".format(loan_xid))

        if user.id != loan.customer.user_id:
            return forbidden_error_response(
                data={'user_id': user.id},
                message=['User not allowed'])
        application = loan.get_application
        credit_matrix, credit_matrix_product_line = \
            get_credit_matrix_and_credit_matrix_product_line(
                application,
                False,
                False,
                TransactionMethodCode.CREDIT_CARD.name
            )

        account_limit = loan.account.accountlimit_set.last()
        loan_amount_request = loan.loan_disbursement_amount
        available_duration = get_loan_duration(
            loan_amount_request,
            credit_matrix_product_line.max_duration,
            credit_matrix_product_line.min_duration,
            account_limit.set_limit,
            customer=application.customer,
            application=application,
        )
        if not available_duration:
            return general_error_response('tenor tidak tersedia')

        available_duration = [1] if loan_amount_request <= 100000 else available_duration

        if data['loan_duration'] not in available_duration:
            return general_error_response('tenor yang dipilih salah')

        text_sphp, _ = get_loan_agreement_template_julo_one(loan.id, type="android",
                                                            is_simulation=True,
                                                            loan_duration=data['loan_duration'])
        return success_response(data=text_sphp)


class JuloCardTransactionInfoView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        loan_xid = kwargs['loan_xid']
        loan = (
            Loan.objects
            .only('id', 'loan_amount', 'loan_duration', 'sphp_accepted_ts')
            .filter(
                transaction_method_id=TransactionMethodCode.CREDIT_CARD.code,
                customer=request.user.customer,
                loan_xid=loan_xid
            ).last()
        )

        if not loan:
            return not_found_response("Loan with loan xid:{} Not found".format(loan_xid))
        sphp_accepted_ts_local = timezone.localtime(loan.sphp_accepted_ts)
        data = {
            'date': sphp_accepted_ts_local.strftime('%Y-%m-%d'),
            'time': sphp_accepted_ts_local.strftime('%H:%M:%S'),
            'nominal': loan.loan_amount,
            'tenor': loan.loan_duration,
        }
        return success_response(data)
