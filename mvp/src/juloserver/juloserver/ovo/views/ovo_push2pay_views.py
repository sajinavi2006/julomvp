from django.forms import model_to_dict
from rest_framework.views import APIView

from juloserver.ovo.models import OvoRepaymentTransaction
from juloserver.ovo.serializers import PushToPaySerializer
from juloserver.ovo.constants import (
    OvoPaymentStatus,
    OvoMobileFeatureName,
    OvoTransactionStatus,
)
from juloserver.ovo.services.ovo_push2pay_services import (
    create_transaction_data,
    push_to_pay,
    notification_callback,
    store_transaction_data_history,
)
from juloserver.ovo.tasks import send_payment_success_event_to_firebase

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    not_found_response,
)

from juloserver.julo.models import (
    MobileFeatureSetting,
)


class TransactionDataView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        account = request.user.customer.account
        checkout_id = request.GET.get('checkout_id', None)
        response, error = create_transaction_data(account, checkout_id)

        if error:
            return general_error_response(error)

        return success_response(response)


class PushToPayView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = PushToPaySerializer(data=request.data)

        if not serializer.is_valid():
            return general_error_response(serializer.errors)

        transaction_id = request.data['transaction_id']
        phone_number = request.data['phone_number']
        flow_id = serializer.validated_data.get('flow_id')
        status, error = push_to_pay(transaction_id, phone_number, flow_id)

        if error:
            return general_error_response(error)

        return success_response(
            'Pastikan cicilan kamu berhasil terbayar lewat aplikasi'
            ' JULO setelah melakukan pembayaran lewat aplikasi OVO'
        )


class NotificationCallbackView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        status = request.GET.get('status', None)
        signature = request.GET.get('signature', None)
        transaction_id = request.GET.get('trx_id', None)
        bill_no = request.GET.get('bill_no', None)
        bill_total = request.GET.get('bill_total', None)

        if not status or status not in [
            OvoPaymentStatus.UNPROCESSED,
            OvoPaymentStatus.IN_PROCESS,
            OvoPaymentStatus.PAYMENT_SUCCESS,
        ]:
            ovo_repayment_transaction = OvoRepaymentTransaction.objects.get_or_none(
                transaction_id=transaction_id
            )
            current_repayment_transaction = model_to_dict(ovo_repayment_transaction)
            input_params = dict(status=OvoPaymentStatus.RESPONSE[status])
            ovo_repayment_transaction.update_safely(**input_params)
            store_transaction_data_history(
                input_params, ovo_repayment_transaction, current_repayment_transaction
            )
            return success_response('Status is empty/payment failed.')

        if not signature:
            return general_error_response('Signature is empty.')

        if not transaction_id:
            return general_error_response('Transaction ID is empty.')

        if not bill_no:
            return general_error_response('Bill number is empty.')

        if not bill_total:
            return general_error_response('Bill total is empty.')

        status, message = notification_callback(
            status, signature, transaction_id, bill_no, bill_total
        )

        if not status:
            return general_error_response(message)

        send_payment_success_event_to_firebase.delay(transaction_id)

        return success_response(message)


class PaymentStatusView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        ovo_repayment_transaction = OvoRepaymentTransaction.objects.get_or_none(
            transaction_id=kwargs['transaction_id']
        )

        customer = request.user.customer
        if (
            not ovo_repayment_transaction
            or ovo_repayment_transaction.account_payment_xid.account.customer != customer
        ):
            return general_error_response('Transaction not found.')

        status = ""
        if ovo_repayment_transaction.status in {
            OvoTransactionStatus.POST_DATA_SUCCESS,
            OvoTransactionStatus.PUSH_TO_PAY_SUCCESS,
        }:
            status = "PENDING"
        elif ovo_repayment_transaction.status == OvoTransactionStatus.SUCCESS:
            status = "SUCCESS"
        mobile_feature_setting = MobileFeatureSetting.objects.filter(
            feature_name=OvoMobileFeatureName.OVO_REPAYMENT_COUNTDOWN
        ).last()

        if not mobile_feature_setting:
            return not_found_response("Countdown not found")

        return success_response(
            {
                "status": status,
                "duration": mobile_feature_setting.parameters.get("countdown"),
                "total_payment": ovo_repayment_transaction.amount,
            }
        )
