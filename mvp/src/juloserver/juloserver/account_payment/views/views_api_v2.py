import logging
from django.db import transaction
from rest_framework.authentication import SessionAuthentication
from rest_framework.views import APIView

from juloserver.cashback.constants import OverpaidConsts
from juloserver.julo.models import (
    PaymentMethod,
    GlobalPaymentMethod,
    Image
)
from juloserver.julo.services2.payment_method import aggregate_payment_methods
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    not_found_response,
    forbidden_error_response,
    service_unavailable_error_response
)
from juloserver.account_payment.serializers import (
    CreateCheckoutRequestSerializer,
    UpdateCheckoutRequestStatusSerializer,
    UploadCheckoutRequestSerializer
)
from juloserver.account_payment.models import (
    AccountPayment,
    CheckoutRequest
)
from juloserver.account_payment.services.account_payment_related import (
    create_checkout_request,
    process_crm_customer_detail_list,
    process_crm_unpaid_loan_account_details_list
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.account_payment.constants import CheckoutRequestCons
from juloserver.portal.object.loan_app.constants import ImageUploadType
from juloserver.account_payment.tasks.scheduled_tasks import (
    process_remaining_bulk_create_receipt_image_checkout_request,
    send_checkout_experience_pn,
)
from juloserver.pin.decorators import pin_verify_required
from juloserver.cashback.services import has_ineligible_overpaid_cases
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.julo.exceptions import DuplicateCashbackTransaction
from juloserver.julo.services2.cashback import (
    ERROR_MESSAGE_TEMPLATE_4,
    ERROR_MESSAGE_TEMPLATE_1
)
from juloserver.julo.services2 import get_cashback_redemption_service
from juloserver.loan_refinancing.models import LoanRefinancingRequest

logger = logging.getLogger(__name__)


class PaymentMethodRetrieveView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, account_id):
        customer = self.request.user.customer
        if not customer:
            return general_error_response('Customer tidak ditemukan')
        account = customer.account_set.get_or_none(id=account_id)
        if not account:
            return general_error_response('Account tidak ditemukan')

        payment_methods = PaymentMethod.objects.filter(
            customer=customer, is_shown=True).order_by('sequence').exclude(
                payment_method_code=PaymentMethodCodes.OVO)
        application = account.application_set.last()
        if application.application_status_id >= ApplicationStatusCodes.LOC_APPROVED:
            global_payment_methods = GlobalPaymentMethod.objects.all()
        else:
            global_payment_methods = []

        list_method_lookups = aggregate_payment_methods(
            payment_methods, global_payment_methods, application.bank_name, slimline_dict=True)

        return success_response({"payment_methods": list_method_lookups})


class PaymentCheckout(StandardizedExceptionHandlerMixin, APIView):
    """
    end point to handle create checkout request
    """
    serializer_class = CreateCheckoutRequestSerializer

    @pin_verify_required
    def paid_checkout_with_cashback_method(self, request, checkout):
        logger.info({
            "function": "paid_checkout_with_cashback_method",
            "info": "function begin"
        })
        customer = request.user.customer
        if has_ineligible_overpaid_cases(customer):
            # old android apps
            return service_unavailable_error_response(OverpaidConsts.Message.CASHBACK_LOCKED)

        try:
            cashback_redemption_service = get_cashback_redemption_service()
            status = cashback_redemption_service.\
                pay_checkout_experience_by_selected_account_payment(
                    customer, checkout.account_payment_ids)
            if status:
                logger.info({
                    "function": "paid_checkout_with_cashback_method",
                    "info": "successfully to reedemed cashback"
                })
                return success_response({
                    'checkout_xid': checkout.checkout_request_xid
                })
            else:
                logger.warn({
                    "function": "paid_checkout_with_cashback_method",
                    "info": "there's no payment schedule yet"
                })
                return service_unavailable_error_response(ERROR_MESSAGE_TEMPLATE_4)
        except DuplicateCashbackTransaction:
            logger.error({
                "function": "paid_checkout_with_cashback_method",
                "info": "transaction already on process"
            })
            return service_unavailable_error_response(
                'Terdapat transaksi yang sedang dalam proses, '
                'Coba beberapa saat lagi.')
        except Exception as e:
            logger.error({
                "function": "paid_checkout_with_cashback_method",
                "info": e
            })
            get_julo_sentry_client().captureException()
            return service_unavailable_error_response(ERROR_MESSAGE_TEMPLATE_1)

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payment_method = None
        # customer not choose cashback method and not choose payment method
        if not data['redeem_cashback'] and not data.get('payment_method_id'):
            return general_error_response(
                'Silahkan pilih metode pembayaran'
            )
        if data.get('payment_method_id'):
            payment_method = PaymentMethod.objects.filter(
                pk=data['payment_method_id']
            ).first()
            if not payment_method:
                return not_found_response('Payment method tidak ditemukan')
            if request.user.customer != payment_method.customer:
                logger.error({
                    'action': 'Payment checkout',
                    'error': 'customer not match',
                    'payment_method_customer_id': payment_method.customer.id,
                    'requester_customer': request.user.customer.id
                })
                return general_error_response('User is not match with virtual account')
        account_payments = AccountPayment.objects.only(
            'due_amount', 'account', 'paid_amount'
        ).filter(pk__in=data['account_payment_id'], account=request.user.customer.account)
        if not data.get('refinancing_id'):
            if not account_payments:
                return not_found_response('Account payment tidak ditemukan')
            data['account_payment_id'] = [payment.pk for payment in account_payments]

        if data.get('refinancing_id'):
            loan_refinancing_request = LoanRefinancingRequest.objects.filter(
                pk=data.get('refinancing_id')
            ).last()
            data['refinancing_id'] = loan_refinancing_request

        checkout = None
        response_cashback = None
        retry = 12
        for i in range(retry):
            try:
                with transaction.atomic():
                    checkout = create_checkout_request(
                        account_payments=account_payments,
                        payment_method=payment_method, data=data)
                    if data['redeem_cashback']:
                        i = 12
                        response_cashback = \
                            self.paid_checkout_with_cashback_method(request, checkout)
                        if response_cashback.status_code != 200:
                            raise Exception("Error reedemed cashback")
                    break
            except Exception as e:
                if i < retry - 1:
                    continue
                else:
                    logger.error({
                        "action": "PaymentCheckout",
                        "info": e
                    })
                    get_julo_sentry_client().captureException()
                    break

        if data['redeem_cashback']:
            logger.info({
                "action": "PaymentCheckout",
                "request": request.data,
                "response_code": response_cashback.status_code,
                "response": response_cashback.data
            })
            return response_cashback
        if not checkout:
            response = general_error_response('Gagal membuat checkout request')
            logger.info({
                "action": "PaymentCheckout",
                "request": request.data,
                "response_code": response.status_code,
                "response": response.data
            })
            return response
        else:
            data = {
                'checkout_xid': checkout.checkout_request_xid
            }
            response = success_response(data)
            logger.info({
                "action": "PaymentCheckout",
                "request": request.data,
                "response_code": response.status_code,
                "response": response.data
            })
            return response


class UpdateCheckoutRequestStatus(StandardizedExceptionHandlerMixin, APIView):
    """
    end point to handle update checkout request status
    from "active" to "canceled"
    from "redeemed" to "finished"
    """
    serializer_class = UpdateCheckoutRequestStatusSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        checkout_request = CheckoutRequest.objects.get_or_none(
            pk=data['checkout_id']
        )
        if not checkout_request:
            return not_found_response('Data checkout tidak ditemukan')
        if checkout_request.account_id.id != request.user.customer.account.id:
            return forbidden_error_response('User not allowed')
        # show response payment in process
        if checkout_request.status == CheckoutRequestCons.FINISH \
            or checkout_request.status == CheckoutRequestCons.REDEEMED \
                and data['status'] != 'finish':
            return general_error_response('Pembayaran sedang diproses')

        if checkout_request.status == CheckoutRequestCons.ACTIVE and data['status'] == 'cancel' \
                or checkout_request.status == CheckoutRequestCons.REDEEMED \
                and data['status'] == 'finish':
            status = data['status'] + 'ed'
            CheckoutRequest.objects.filter(
                pk=data['checkout_id']
            ).update(status=status)
            if status == CheckoutRequestCons.CANCELED:
                send_checkout_experience_pn.delay(
                    [checkout_request.account_id.customer_id], CheckoutRequestCons.CANCELED
                )
                update_va_bni_transaction.delay(
                    checkout_request.account_id.id,
                    'account_payment.views.views_api_v2.UpdateCheckoutRequestStatus',
                )

            message = {
                'message': 'Data berhasil diupdate'
            }
            return success_response(message)
        else:
            return general_error_response('Perubahan status tidak sesuai')


class UploadCheckoutReceipt(StandardizedExceptionHandlerMixin, APIView):
    """
    end point to handle upload checkout receipt
    """
    serializer_class = UploadCheckoutRequestSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user

        image = Image(image_type=ImageUploadType.LATEST_PAYMENT_PROOF)
        checkout_id = data['checkout_id']
        upload = data['upload']

        checkout_request = CheckoutRequest.objects.get_or_none(pk=checkout_id)
        if not checkout_request:
            return not_found_response("Checkout request dengan id={} tidak ditemukan".format(
                checkout_id
            ))
        if checkout_request.status != CheckoutRequestCons.ACTIVE:
            return general_error_response(
                "Checkout request dengan id={} statusnya tidak aktif".format(
                    checkout_id))

        if user.id != checkout_request.account_id.customer.user_id:
            return forbidden_error_response(data={'user_id': user.id}, message=['User not allowed'])

        account_payment_ids = list(checkout_request.account_payment_ids)
        image.image_source = int(account_payment_ids[0])
        image.save()
        image.image.save(image.full_image_name(upload.name), upload)

        # update checkout request receipt
        receipt = [image.id]
        checkout_request.receipt_ids = receipt
        checkout_request.save()

        # update remaining account_payment
        account_payment_ids.remove(account_payment_ids[0])

        process_remaining_bulk_create_receipt_image_checkout_request.\
            delay(image.id, account_payment_ids, checkout_request.id)

        return success_response({'id': str(image.id)})


class CRMCustomerDetailList(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]

    def get(self, request, account_payment_id: int):
        account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
        if not account_payment:
            return not_found_response("AccountPayment request dengan id={} tidak ditemukan".format(
                account_payment_id
            ))

        response_data = process_crm_customer_detail_list(account_payment, request.user)
        return success_response(data=response_data)


class CRMUnpaidLoanAccountDetailsList(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]

    def get(self, request, account_payment_id: int):
        account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
        if not account_payment:
            return not_found_response(
                "AccountPayment request dengan id={} tidak ditemukan".format(account_payment_id)
            )
        response_data = process_crm_unpaid_loan_account_details_list(account_payment)
        return success_response(data=response_data)
