from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN
from rest_framework.views import APIView
from rest_framework.response import Response
from juloserver.apiv1.exceptions import ResourceNotFound
from juloserver.cashback.constants import CashbackNewSchemeConst
from juloserver.julo.models import (
    Loan,
    PaymentMethod,
    GlobalPaymentMethod,
    FeatureSetting,
    PaybackTransaction,
)
from juloserver.julo.services2.payment_method import aggregate_payment_methods
from juloserver.julo.statuses import (
    ApplicationStatusCodes
)
from juloserver.julo.constants import ExperimentConst
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response, success_response, forbidden_error_response)

from juloserver.account_payment.models import (
    PaymentMethodInstruction,
    RepaymentRecallLog,
)
from juloserver.account_payment.serializers import (
    RepaymentInstructionSerializer,
    PaymentMethodExperimentSerializer,
)
from juloserver.account_payment.constants import (
    FeatureNameConst,
    REPAYMENT_RECALL_WAIT_TIME,
)
from juloserver.account_payment.tasks.repayment_tasks import check_repayment_process
from juloserver.account_payment.services.account_payment_related import (
    store_experiment,
    store_repayment_recall_log,
    get_potential_cashback_by_account_payment,
)
from juloserver.account_payment.constants import RepaymentRecallPaymentMethod
from juloserver.account_payment.services.earning_cashback import get_paramters_cashback_new_scheme


# we can't using the new standardized API response for avoid android side have a lot effort
class PaymentMethodRetrieveView(APIView):

    def get(self, request, *args, **kwargs):
        user = self.request.user
        customer = user.customer

        # monkey patch for case J1 account get blank on tagihan result
        if customer.account:
            loan = customer.account.loan_set.last()
            if not loan:
                raise ResourceNotFound(resource_id=1234)
        else:
            loan_id = self.request.query_params.get('loan_id', None)
            if not loan_id:
                raise ResourceNotFound(resource_id=loan_id)
            loan = Loan.objects.get_or_none(id=loan_id)
            if not loan:
                raise ResourceNotFound(resource_id=loan_id)

        if user.id != loan.customer.user_id:
            return Response(status=HTTP_403_FORBIDDEN, data={
                'errors': 'User not allowed',
                'user_id': user.id})

        # quickfix for PBUG-772 (somehow android hit this j1 dedicated API with MTL loan_id)
        if not loan.account:
            return Response(status=HTTP_200_OK, data={'results': []})

        payment_methods = PaymentMethod.objects.filter(
            customer=loan.customer, is_shown=True).order_by('sequence')
        application = loan.account.application_set.last()
        if application.application_status_id >= ApplicationStatusCodes.LOC_APPROVED:
            global_payment_methods = GlobalPaymentMethod.objects.all()
        else:
            global_payment_methods = []

        list_method_lookups = aggregate_payment_methods(
            payment_methods, global_payment_methods, loan.julo_bank_name)

        return Response(status=HTTP_200_OK, data={'results': list_method_lookups})


class PaymentMethodUpdateView(StandardizedExceptionHandlerMixin, APIView):

    def put(self, request, payment_method_id):
        payment_method = PaymentMethod.objects.get_or_none(id=payment_method_id)
        if not payment_method or not payment_method.customer:
            return general_error_response('Payment method not found')
        if request.user.customer != payment_method.customer:
            return forbidden_error_response('User not allowed')

        with transaction.atomic():
            PaymentMethod.objects.filter(
                customer=payment_method.customer, is_primary=True).update(is_primary=False)
            payment_method.update_safely(is_primary=True)

        return success_response('Update payment method successfully!')


class GetLastAccountPaymentDetail(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        account = customer.account

        if not account:
            return general_error_response("Customer tidak memiliki Account")

        oldest_account_payment = account.get_last_unpaid_account_payment()
        if not oldest_account_payment:
            return general_error_response("Customer tidak memiliki account payment")

        app_version = int(request.META.get('HTTP_X_VERSION_CODE', 0))
        eligible_new_cashback_scheme = \
            (app_version > CashbackNewSchemeConst.ELIGIBLE_MINIMUM_ANDROID_VERSION)
        due_date, percentage_mapping = get_paramters_cashback_new_scheme()
        cashback_parameters = dict(
            is_eligible_new_cashback=account.is_cashback_new_scheme,
            due_date=due_date,
            percentage_mapping=percentage_mapping,
            account_status=account.status_id,
        )
        (
            potential_cashback_amount,
            is_eligible_new_cashback,
        ) = get_potential_cashback_by_account_payment(
            oldest_account_payment,
            account.cashback_counter,
            is_eligible_android_version=eligible_new_cashback_scheme,
            is_return_with_experiment_status=True,
            cashback_parameters=cashback_parameters,
        )

        response_data = {
            'due_date': oldest_account_payment.due_date,
            'due_amount': oldest_account_payment.due_amount,
            'cashback_amount': potential_cashback_amount,
        }
        if eligible_new_cashback_scheme:
            response_data['cashback_counter'] = account.cashback_counter_for_customer
            response_data['dpd'] = oldest_account_payment.dpd
            response_data['is_new_cashback_active'] = is_eligible_new_cashback

        return success_response(response_data)


class PaymentMethodInstructionView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        serializer = RepaymentInstructionSerializer(data=request.GET.dict())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        response_data = [
            {
                'payment_method': data['global_payment_method'].payment_method_name,
                'payment_instructions': (
                    PaymentMethodInstruction.objects.
                    filter(
                        global_payment_method__payment_method_name=data[
                            'global_payment_method'
                        ].payment_method_name,
                        is_active=True
                    ).
                    values('title', 'content')
                )
            }
        ]

        return success_response(response_data)


class RepaymentCheckView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        repayment_recall_log = RepaymentRecallLog.objects.filter(customer_id=customer.id).last()
        today = timezone.localtime(timezone.now())
        time_delta = timedelta(hours=REPAYMENT_RECALL_WAIT_TIME)
        reinquiry_payment_status = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.REINQUIRY_PAYMENT_STATUS, is_active=True
        ).last()
        if reinquiry_payment_status:
            time_delta = timedelta(minutes=reinquiry_payment_status.parameters["interval_minute"])
        if (
            repayment_recall_log
            and today < timezone.localtime(repayment_recall_log.cdate) + time_delta
        ):
            return general_error_response("Harap tunggu beberapa saat untuk cek ulang")
        payback_transactions = PaybackTransaction.objects.only('id', 'payback_service').filter(
            customer_id=customer.id,
            is_processed=False,
            payback_service__in=RepaymentRecallPaymentMethod.all()
        )
        store_repayment_recall_log(customer.id, payback_transactions)
        if payback_transactions:
            check_repayment_process.delay(customer.id, payback_transactions)

        return success_response({"message": "Checking in progress"})


class RepaymentFAQView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.REPAYMENT_FAQ_SETTING
        ).last()
        if not feature_setting or not feature_setting.parameters:
            return general_error_response("contents not found")
        contents = feature_setting.parameters
        return success_response(contents)


class RepaymentSettingView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        repayment_recall_log = RepaymentRecallLog.objects.filter(customer_id=customer.id).last()
        duration = 0
        loan_state = 'empty'
        time_delta = timedelta(hours=REPAYMENT_RECALL_WAIT_TIME)
        today = timezone.localtime(timezone.now())
        latest_payback_success = None
        reinquiry_payment_status = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.REINQUIRY_PAYMENT_STATUS, is_active=True
        ).last()
        if reinquiry_payment_status:
            time_delta = timedelta(minutes=reinquiry_payment_status.parameters["interval_minute"])
        if (
            not repayment_recall_log
            or today >= timezone.localtime(repayment_recall_log.cdate) + time_delta
        ):
            payback_transactions = PaybackTransaction.objects.only('id', 'payback_service').filter(
                customer_id=customer.id,
                is_processed=False,
                payback_service__in=RepaymentRecallPaymentMethod.all(),
            )
            repayment_recall_log = store_repayment_recall_log(customer.id, payback_transactions)
            if payback_transactions:
                check_repayment_process.delay(customer.id, payback_transactions)
        if repayment_recall_log:
            next_recall_datetime = timezone.localtime(repayment_recall_log.cdate) + time_delta
            interval_datetime = next_recall_datetime - timezone.localtime(timezone.now())
            if interval_datetime.total_seconds() > 0:
                duration = int(interval_datetime.total_seconds())
        unpaid_account_payments = customer.account.accountpayment_set.not_paid_active()
        if unpaid_account_payments:
            loan_state = 'unpaid'

        payback = (
            PaybackTransaction.objects.filter(cdate__gte=today - timedelta(days=2))
            .order_by("cdate")
            .last()
        )
        if payback.is_processed:
            latest_payback_success = payback.id

        response_data = {
            "duration": duration,
            "loan_state": loan_state,
            "latest_payback_success": latest_payback_success,
        }
        return success_response(response_data)


class PaymentMethodExperimentView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = PaymentMethodExperimentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        customer = request.user.customer
        store_experiment(
            ExperimentConst.PAYMENT_METHOD_EXPERIMENT, customer.id, data['group']
        )

        return success_response({"message": "Data has been processed"})
