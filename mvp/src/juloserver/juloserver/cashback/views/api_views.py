from django.forms.models import model_to_dict
from builtins import str
from django.db import transaction
from django.db import DatabaseError
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.status import (
    HTTP_404_NOT_FOUND,
)
from django.utils import timezone

from juloserver.cashback.constants import CASHBACK_FROZEN_MESSAGE, OverpaidConsts, \
    CashbackMethodName
from juloserver.cashback.models import CashbackOverpaidVerification
from juloserver.cashback.serializers import (
    CashBackToGopaySerializerV2,
    CashBackToPaymentSerializer,
    CashbackTransferSerializerV2,
    CashbackSepulsaSerializerV2,
    SubmitOverpaidSerializer,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    not_found_response,
    response_template
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.services2 import get_cashback_redemption_service
from juloserver.julo.services2.cashback import (
    ERROR_MESSAGE_TEMPLATE_4,
    ERROR_MESSAGE_TEMPLATE_1,
    ERROR_MESSAGE_TEMPLATE_2,
    ERROR_MESSAGE_TEMPLATE_3,
    CashbackRedemptionService,
)
from juloserver.julo.constants import CashbackTransferConst
from juloserver.julo.models import (
    CashbackTransferTransaction,
    Customer,
)
from juloserver.disbursement.services.gopay import GopayService, GopayConst
from juloserver.disbursement.exceptions import GopayServiceError, GopayInsufficientError
from juloserver.pin.decorators import pin_verify_required
from juloserver.julo.exceptions import JuloException, DuplicateCashbackTransaction, \
    BlockedDeductionCashback
from juloserver.cashback.services import (
    create_cashback_transfer_transaction,
    get_cashback_options_info_v1,
    has_ineligible_overpaid_cases,
    map_cases_to_images,
    get_expired_date_and_cashback,
    CashbackExpiredSetting,
    get_cashback_options_response,
    is_cashback_method_active,
    is_valid_overpaid_cases_images,
)
from juloserver.julo_starter.services.services import determine_application_for_credit_info

julo_sentry_client = get_julo_sentry_client()
cashback_redemption_service = get_cashback_redemption_service()


class CashBackToGopay(StandardizedExceptionHandlerMixin, APIView):
    """
        Endpoint transfer cashback to gopay
    """
    serializer_class = CashBackToGopaySerializerV2

    @pin_verify_required
    def post(self, request):
        gopay_enable = is_cashback_method_active(CashbackMethodName.GOPAY)
        if not gopay_enable:
            return general_error_response(
                'Pencairan cashback melalui metode ini untuk sementara tidak dapat dilakukan'
            )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_data = serializer.validated_data
        customer = request.user.customer
        if customer.is_cashback_freeze:
            return general_error_response(CASHBACK_FROZEN_MESSAGE)

        if has_ineligible_overpaid_cases(customer):
            # old android apps
            return general_error_response(OverpaidConsts.Message.CASHBACK_LOCKED)

        cashback_nominal = request_data['cashback_nominal']
        mobile_phone_number = request_data['mobile_phone_number']
        sentry_client = get_julo_sentry_client()
        try:
            gopay = GopayService()
            gopay.process_cashback_to_gopay(
                customer,
                cashback_nominal,
                mobile_phone_number)

            return success_response({'message': 'The Gopay cashback already sent'})
        except (GopayServiceError, DuplicateCashbackTransaction) as error:
            sentry_client.captureException()
            return general_error_response(str(error))
        except GopayInsufficientError as error:
            return general_error_response(str(error))


class CashbackPayment(APIView):
    """
        Endpoint Cashback to payment
    """
    serializer_class = CashBackToPaymentSerializer

    @pin_verify_required
    def post(self, request):
        cashback_payment_enable = is_cashback_method_active(CashbackMethodName.PAYMENT)
        if not cashback_payment_enable:
            return general_error_response(
                'Pencairan cashback melalui metode ini untuk sementara tidak dapat dilakukan'
            )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        if has_ineligible_overpaid_cases(customer):
            # old android apps
            return general_error_response(OverpaidConsts.Message.CASHBACK_LOCKED)

        try:
            status = cashback_redemption_service.pay_next_loan_payment(customer)
            if status:
                return success_response({
                    'balance': customer.wallet_balance_available,
                    'message': None
                })
            else:
                return general_error_response(ERROR_MESSAGE_TEMPLATE_4)
        except DuplicateCashbackTransaction:
            return general_error_response('Terdapat transaksi yang sedang dalam proses, '
                                          'Coba beberapa saat lagi.')
        except BlockedDeductionCashback:
            return general_error_response('Mohon maaf, saat ini cashback tidak bisa digunakan '
                                          'karena program keringanan')
        except Exception:
            julo_sentry_client.captureException()
            return general_error_response(ERROR_MESSAGE_TEMPLATE_1)


class CashbackSepulsa(APIView):
    """
        Endpoint Cashback to sepulsa
    """
    serializer_class = CashbackSepulsaSerializerV2

    @pin_verify_required
    def post(self, request):
        sepulsa_enable = is_cashback_method_active(CashbackMethodName.SEPULSA)
        if not sepulsa_enable:
            return general_error_response(
                'Pencairan cashback melalui metode ini untuk sementara tidak dapat dilakukan'
            )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        customer = request.user.customer
        if customer.is_cashback_freeze:
            return general_error_response(CASHBACK_FROZEN_MESSAGE)

        if has_ineligible_overpaid_cases(customer):
            # old android apps
            return general_error_response(OverpaidConsts.Message.CASHBACK_LOCKED)

        try:
            product, sepulsa_transaction, balance = cashback_redemption_service.\
                trigger_partner_purchase(data, customer)
        except JuloException as e:
            return general_error_response(str(e))
        return success_response({
            'product': model_to_dict(product),
            'transaction': model_to_dict(sepulsa_transaction),
            'balance': balance,
            'message': None
        })


class CashbackTransfer(generics.ListCreateAPIView):
    """
        Endpoint Redeem Cashback
    """
    serializer_class = CashbackTransferSerializerV2
    model_class = CashbackTransferTransaction

    @pin_verify_required
    def post(self, request, *args, **kwargs):
        xendit_enable = is_cashback_method_active(CashbackMethodName.XENDIT)
        if not xendit_enable:
            return general_error_response(
                'Pencairan cashback melalui metode ini untuk sementara tidak dapat dilakukan'
            )

        customer = request.user.customer
        if customer.is_cashback_freeze:
            return general_error_response(CASHBACK_FROZEN_MESSAGE)

        # check overpaid
        if has_ineligible_overpaid_cases(customer):
            return general_error_response(OverpaidConsts.Message.CASHBACK_LOCKED)

        # last_application
        application = determine_application_for_credit_info(customer)
        if not application:
            return not_found_response('application not found')

        try:
            with transaction.atomic():
                try:
                    customer = Customer.objects.select_for_update(
                        nowait=True).filter(id=customer.id).first()
                except DatabaseError:
                    return general_error_response(ERROR_MESSAGE_TEMPLATE_3)

                cashback_available = customer.wallet_balance_available
                # check cashback amount
                if cashback_available < CashbackTransferConst.MIN_TRANSFER:
                    return general_error_response(ERROR_MESSAGE_TEMPLATE_2)

                current_cashback_transfer = customer.cashbacktransfertransaction_set.exclude(
                    transfer_status__in=CashbackTransferConst.FINAL_STATUSES).exclude(
                    bank_code=GopayConst.BANK_CODE).last()
                if current_cashback_transfer:
                    return general_error_response(ERROR_MESSAGE_TEMPLATE_3)

                cashback_transfer = create_cashback_transfer_transaction(
                    application=application,
                    redeem_amount=cashback_available,
                )
                cashback_service = CashbackRedemptionService()
                cashback_service.process_transfer_reduction_wallet_customer(
                    customer, cashback_transfer)
                balance = customer.wallet_balance_available

            try:
                if cashback_transfer:
                    cashback_transfer_transaction_id = cashback_transfer.id
                    cashback_transfer = CashbackTransferTransaction.objects.get_or_none(
                        id=cashback_transfer_transaction_id)
                    status = cashback_transfer.transfer_status
                    if status == CashbackTransferConst.STATUS_REQUESTED:
                        with transaction.atomic():
                            # choose transfer method
                            if 'bca' in cashback_transfer.bank_name.lower():
                                cashback_transfer.partner_transfer = \
                                    CashbackTransferConst.METHOD_BCA
                            else:
                                cashback_transfer.partner_transfer = \
                                    CashbackTransferConst.METHOD_XFERS

                            cashback_transfer.transfer_status = \
                                CashbackTransferConst.STATUS_APPROVED
                            cashback_transfer.save()
                            cashback_redemption_service.transfer_cashback(cashback_transfer)

            except Exception:
                julo_sentry_client.captureException()
                return success_response({
                    'transaction': model_to_dict(cashback_transfer),
                    'balance': balance,
                    'message': None
                })
        except Exception:
            julo_sentry_client.captureException()
            return general_error_response(ERROR_MESSAGE_TEMPLATE_1)

        return success_response({
            'transaction': model_to_dict(cashback_transfer),
            'balance': balance,
            'message': None
        })


class CashbackInformation(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        today = timezone.localtime(timezone.now()).date()
        expired_date, expired_cashback = get_expired_date_and_cashback(customer.id)
        reminder_days = CashbackExpiredSetting.get_reminder_days()
        data = None
        if expired_cashback > 0 and (expired_date - today).days <= reminder_days:
            data = {
                'cashback_amount': expired_cashback,
                'cashback_expiry_date': expired_date
            }
        return success_response(data)


class CashbackOptionsInfoV1(APIView):
    def get(self, request):
        customer = request.user.customer
        application = customer.application_set.regular_not_deletes().last()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        cashback_options_info = get_cashback_options_info_v1(application)
        return success_response(cashback_options_info)


class CashbackOptionsInfoV2(APIView):
    def get(self, request):
        customer = request.user.customer
        application = customer.application_set.regular_not_deletes().last()
        if not application:
            return response_template(
                status=HTTP_404_NOT_FOUND,
                success=False,
                message=['Application not found']
            )

        cashback_options_info = get_cashback_options_response(application)
        return success_response(cashback_options_info)


class SubmitOverpaid(APIView):
    serializer_class = SubmitOverpaidSerializer

    def post(self, request):
        """
        Request data example:
        "overpaid_cases" : [
                {
                    "case_id" : 32,
                    "image_id": 101
                },
                {
                    "case_id" : 33,
                    "image_id": 103
                }
            ]
        """
        customer = request.user.customer
        serializer = self.serializer_class(data=request.data['overpaid_cases'], many=True)
        serializer.is_valid(raise_exception=True)
        cases_images_map = serializer.validated_data

        if not is_valid_overpaid_cases_images(cases_images_map, customer):
            return general_error_response("Cases or images do not belong to customer")

        map_cases_to_images(cases_images_map, customer)
        return success_response(
            data={"message": "The request has been successfully saved"}
        )


class OverpaidVerification(APIView):
    def get(self, request):
        """
        Find all cashback overpaid cases that are unprocessed or rejected
        Response:
            {
                "success": true,
                "data": {
                    "overpaid_cases": [
                        {
                            "case_id": 31,
                            "date" : "2020-12-24",
                            "amount" : 10000
                        },
                        {
                            "case_id": 32,
                            "date" : "2020-12-24",
                            "amount" : 1000000
                        },
                    ]
                },
                "errors":[]
            }
        """
        customer = request.user.customer
        # find and return overpaid cases:
        cases = CashbackOverpaidVerification.objects.filter(
            status__in=[OverpaidConsts.Statuses.REJECTED, OverpaidConsts.Statuses.UNPROCESSED],
            customer=customer, overpaid_amount__gt=0,
        ).order_by('cdate')
        overpaid_cases = []
        for case in cases:
            case_info = {
                'case_id': case.id,
                'time': timezone.localtime(case.cdate).isoformat(),
                'amount': case.overpaid_amount,
            }
            overpaid_cases.append(case_info)

        data = {
            "overpaid_cases": overpaid_cases,
        }
        return success_response(data=data)
