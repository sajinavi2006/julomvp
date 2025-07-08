from django.db import OperationalError
from django.forms import Select, TextInput
from django.utils import timezone
from django.http import JsonResponse

from juloserver.julo.models import SepulsaTransaction
from juloserver.julo.clients import get_julo_sentry_client
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK, HTTP_400_BAD_REQUEST,
)
from juloserver.account.models import Account
from juloserver.disbursement.services.gopay import GopayService
from juloserver.loan.services.views_related import validate_mobile_number
from juloserver.loyalty.constants import (
    DailyCheckinMessageConst,
    MissionMessageConst,
    MissionFilterCategoryConst,
    PointExpiredReminderConst,
    PointRepaymentErrorMessage,
    PointRedeemReferenceTypeConst,
    ERROR_CODE_MESSAGE_MAPPING,
    RedemptionMethodErrorCode,
    PointTransferErrorMessage,
)
from juloserver.api_token.authentication import ExpiryTokenAuthentication
from juloserver.loyalty.exceptions import (
    DailyCheckinHasBeenClaimedException,
    DailyCheckinNotFoundException,
    MissionProgressNotFoundException,
    MissionConfigNotFoundException,
    PointTransferException,
    GopayException,
    LoyaltyGopayTransferNotFoundException,
    DanaException,
)
from juloserver.loyalty.forms import MissionCriteriaForm
from juloserver.loyalty.models import PointHistory
from juloserver.loyalty.constants import (
    PointHistoryPaginationConst,
    APIVersionConst,
)
from juloserver.loyalty.services.mission_related import (
    get_customer_loyalty_mission_list,
    get_customer_loyalty_mission_detail,
    get_choice_criteria_by_category,
    get_choice_reward_by_category,
    get_choice_target_by_category,
    get_choice_sepulsa_categories_by_transaction_method,
    get_mission_filter_categories,
    claim_mission_rewards,
)
from juloserver.loyalty.services.daily_checkin_related import (
    claim_daily_checkin_point,
    get_or_create_daily_checkin_progress,
    get_loyalty_entry_point_information,
)
from juloserver.loyalty.services.point_redeem_services import (
    pay_next_loan_payment,
    get_convert_rate_info,
    check_eligible_redemption_method,
    get_point_transfer_bottom_sheet_information,
    construct_data_response_success_gopay_transfer,
    get_loyalty_gopay_transfer_transaction,
    get_point_usage_history_by_reference,
    process_transfer_loyalty_point_to_dana,
    construct_data_response_success_dana_transfer,
)
from juloserver.loyalty.services.services import (
    get_account_payments_list,
    construct_data_point_information,
    get_floating_action_button_info,
    get_non_locked_loyalty_point, is_eligible_for_loyalty_entry_point,
)
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.payment_point.models import TransactionMethod
from juloserver.pin.decorators import pin_verify_required
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response, response_template,
)
from juloserver.portal.object import julo_login_required
from juloserver.loyalty.serializers import (
    LoyaltyPointSerializer,
    MissionClaimRewardsSerializer,
    PointHistorySerializer,
    PointRePaymentSerializer,
    PointTransferBottomSheetSerializer,
    TransferToGopaySerializer,
    CheckGopayTransferTransactionSerializer,
    TransferToDanaSerializer,
    CheckDanaTransferTransactionSerializer,
)
from juloserver.julo.models import Application


sentry_client = get_julo_sentry_client()


class LoyaltyInfoAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        customer = request.user.customer
        loyalty_point = get_non_locked_loyalty_point(customer_id=customer.id)
        loyalty_point_serializer = LoyaltyPointSerializer(loyalty_point)
        convert_rate_info = get_convert_rate_info()
        data = request.query_params
        category = data.get('category', MissionFilterCategoryConst.ALL_MISSIONS)
        mission_list = get_customer_loyalty_mission_list(
            customer=customer,
            category=category,
            api_version=APIVersionConst.V1
        )

        return success_response({
            'loyalty_point': loyalty_point_serializer.data,
            'convert_rate_info': convert_rate_info,
            'missions': mission_list
        })


class LoyaltyMissionGetSearchCategories(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        data_res = get_mission_filter_categories()
        return success_response(data=data_res)


class LoyaltyMissionDetailAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, mission_config_id):
        customer = request.user.customer
        try:
            mission_detail = get_customer_loyalty_mission_detail(
                customer=customer,
                mission_config_id=mission_config_id,
                api_version=APIVersionConst.V1
            )
        except MissionConfigNotFoundException:
            return general_error_response(MissionMessageConst.ERROR_MISSION_CONFIG_NOT_FOUND)
        return success_response(mission_detail)


class DailyCheckinAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        customer = request.user.customer
        try:
            data = get_or_create_daily_checkin_progress(customer)
        except DailyCheckinNotFoundException:
            return not_found_response(DailyCheckinMessageConst.ERROR_DAILY_CHECK_IN_NOT_FOUND)
        return success_response(data)


class DailyCheckinAPIClaimView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        customer = request.user.customer
        try:
            today_reward = claim_daily_checkin_point(customer)
            data = {
                "today_reward": today_reward
            }
        except DailyCheckinHasBeenClaimedException:
            return general_error_response(DailyCheckinMessageConst.ERROR_HAS_BEEN_CLAIMED)

        return success_response(data)


class PointHistoryPagination(PageNumberPagination):
    page_size_query_param = PointHistoryPaginationConst.PAGE_SIZE_QUERY_PARAM
    page_size = PointHistoryPaginationConst.DEFAULT_PAGE_SIZE
    max_page_size = PointHistoryPaginationConst.MAX_PAGE_SIZE

    def get_paginated_response(self, data):
        if self.page.has_next():
            next_page = self.page.next_page_number()
        else:
            next_page = None

        return Response({
            'success': True,
            'page_size': len(data),
            'next_page': next_page,
            'data': data,
            'errors': []
        }, status=HTTP_200_OK)


class LoyaltyPointHistoryAPIView(StandardizedExceptionHandlerMixin, ListAPIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = PointHistoryPagination
    serializer_class = PointHistorySerializer

    def get_queryset(self):
        customer = self.request.user.customer
        return PointHistory.objects.filter(customer_id=customer.id).order_by('-id')


@julo_login_required
def load_criteria_by_category(request, category):
    result = get_choice_criteria_by_category(category)
    return JsonResponse(result, safe=False)


@julo_login_required
def load_reward_by_category(request, category):
    result = get_choice_reward_by_category(category)
    return JsonResponse(result, safe=False)


@julo_login_required
def load_target_by_category(request, category):
    result = get_choice_target_by_category(category)
    return JsonResponse(result, safe=False)


@julo_login_required
def load_sepulsa_categories_by_transaction_method(request, transaction_method):
    result = get_choice_sepulsa_categories_by_transaction_method(int(transaction_method))
    return JsonResponse(result, safe=False)


class LoyaltyMissionClaimRewardsAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [ExpiryTokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = MissionClaimRewardsSerializer

    def post(self, request):
        customer = request.user.customer
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            mission_progress_id = serializer.validated_data['mission_progress_id']
            point_amount = claim_mission_rewards(mission_progress_id, customer)
        except MissionProgressNotFoundException:
            return general_error_response(
                MissionMessageConst.ERROR_MISSION_PROGRESS_NOT_FOUND
            )

        return success_response({
            'point_amount': point_amount
        })


@julo_login_required
def generate_field_transaction_method(request, target_trx):
    if request.is_ajax() and request.method == 'GET':
        from django import forms
        form = MissionCriteriaForm()
        form.fields['value_transaction_method_id_{}'.format(target_trx)] = forms.ModelChoiceField(
            label='Transaction Method',
            required=False,
            queryset=TransactionMethod.objects.order_by('id').all(),
            widget=Select(attrs={
                'data-id': target_trx,
            }),
            empty_label=None
        )
        form.fields['value_categories_{}'.format(target_trx)] = forms.CharField(
            label='Categories',
            required=False,
            widget=TextInput(attrs={
                'data-id': target_trx,
            }),
        )
        return JsonResponse({
            'extra_transaction_method': {
                'field': str(form['value_transaction_method_id_{}'.format(target_trx)]),
                'field_name': 'value_transaction_method_id_{}'.format(target_trx)
            },
            'extra_categories': {
                'field': str(form['value_categories_{}'.format(target_trx)]),
                'field_name': 'value_categories_{}'.format(target_trx)
            },
        })
    else:
        JsonResponse({'error': 'Invalid request'})


class AccountPaymentListAPIView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        user = self.request.user
        customer = user.customer
        account = Account.objects.filter(customer=customer).last()
        if not account:
            return success_response()

        account_payments_list = get_account_payments_list(account)
        return success_response({"account_payments_list": account_payments_list})


class PointInformation(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        data = construct_data_point_information(customer)

        is_valid, error_code = check_eligible_redemption_method(
            method=PointRedeemReferenceTypeConst.REPAYMENT, customer=customer
        )

        # construct response
        response = {
            'point_amount': data['point_amount'],
            'point_usage_info': data['point_reminder_config'].get(
                'point_usage_info', PointExpiredReminderConst.Message.POINT_USAGE_INFO
            ),
            'amount_deduct': data["amount_deduct"],
            'eligible_for_point_repayment': {
                "is_valid": is_valid,
                "error_msg": ERROR_CODE_MESSAGE_MAPPING.get(error_code),
            }
        }
        if data.get('next_expiry_date') and data.get('next_expiry_point'):
            response['point_expiry_info'] = data['point_reminder_config'].get(
                'point_expiry_info', PointExpiredReminderConst.Message.EXPIRY_INFO
            ).format(
                f"{data['next_expiry_point']:,}".replace(',', '.'),
                data['next_expiry_date'].strftime('%d %b %Y')
            )

        return success_response(response)


class PointRepayment(StandardizedExceptionHandlerMixin, APIView):
    """
        Endpoint using point to payment
    """
    serializer_class = PointRePaymentSerializer

    @pin_verify_required
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer

        is_valid, error_code = check_eligible_redemption_method(
            method=PointRedeemReferenceTypeConst.REPAYMENT, customer=customer
        )

        if not is_valid:
            return general_error_response(ERROR_CODE_MESSAGE_MAPPING[error_code])

        status, total_point, amount_deduct, point_deduct = pay_next_loan_payment(customer)
        if status:
            return success_response({
                'total_point': total_point,
                'amount_deduct': amount_deduct,
                'point_deduct': point_deduct,
                'request_time': timezone.now()
            })

        if total_point == 0:
            return general_error_response(PointRepaymentErrorMessage.NOT_ENOUGH_POINT)
        return general_error_response(PointRepaymentErrorMessage.NO_ACCOUNT_PAYMENT)


class PointTransferBottomSheet(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = PointTransferBottomSheetSerializer

    def get(self, request):
        serializer = self.serializer_class(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        customer = request.user.customer
        method = serializer.validated_data['redemption_method']
        nominal_amount = serializer.validated_data['nominal_amount']

        try:
            data = get_point_transfer_bottom_sheet_information(
                method, nominal_amount, customer
            )
        except PointTransferException as error:
            return general_error_response(ERROR_CODE_MESSAGE_MAPPING[str(error)])
        return success_response(data)


class GopayTransfer(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = TransferToGopaySerializer

    @pin_verify_required
    def post(self, request):
        customer = request.user.customer
        is_valid, error_code = check_eligible_redemption_method(
            PointRedeemReferenceTypeConst.GOPAY_TRANSFER, customer
        )
        if not is_valid:
            return general_error_response(ERROR_CODE_MESSAGE_MAPPING[error_code])

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_data = serializer.validated_data

        nominal = request_data['nominal']
        mobile_phone_number = request_data['mobile_phone_number']
        if not validate_mobile_number(mobile_phone_number):
            return general_error_response(ErrorMessageConst.PHONE_INVALID)
        try:
            gopay = GopayService()
            _, gopay_transfer, point_usage_history = gopay.process_transfer_loyalty_point_to_gopay(
                customer,
                nominal,
                mobile_phone_number
            )
            return success_response(
                construct_data_response_success_gopay_transfer(gopay_transfer, point_usage_history)
            )
        except OperationalError:
            sentry_client.captureException()
            return general_error_response(
                ERROR_CODE_MESSAGE_MAPPING[RedemptionMethodErrorCode.OPERATIONAL_ERROR]
            )
        except GopayException as error_code:
            return general_error_response(ERROR_CODE_MESSAGE_MAPPING[str(error_code)])


class CheckGopayTransfer(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CheckGopayTransferTransactionSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = request.user.customer
        try:
            gopay_transfer_id = serializer.validated_data['gopay_transfer_id']
            gopay_transfer = get_loyalty_gopay_transfer_transaction(gopay_transfer_id,customer.id)
            point_usage_his = get_point_usage_history_by_reference(
                PointRedeemReferenceTypeConst.GOPAY_TRANSFER, gopay_transfer.id
            )
            return success_response(
                construct_data_response_success_gopay_transfer(gopay_transfer, point_usage_his)
            )
        except LoyaltyGopayTransferNotFoundException:
            return general_error_response(
                PointTransferErrorMessage.GOPAY_TRANSFER_NOT_FOUND
            )


class DanaTransfer(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = TransferToDanaSerializer

    @pin_verify_required
    def post(self, request):
        customer = request.user.customer
        is_valid, error_code = check_eligible_redemption_method(
            PointRedeemReferenceTypeConst.DANA_TRANSFER, customer
        )
        if not is_valid:
            return general_error_response(ERROR_CODE_MESSAGE_MAPPING[error_code])

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_data = serializer.validated_data

        nominal = request_data['nominal']
        mobile_phone_number = request_data['mobile_phone_number']
        if not validate_mobile_number(mobile_phone_number):
            return general_error_response(ErrorMessageConst.PHONE_INVALID)

        try:
            sepulsa_transaction, point_usage_history = process_transfer_loyalty_point_to_dana(
                customer,
                nominal,
                mobile_phone_number
            )
            return success_response(
                construct_data_response_success_dana_transfer(
                    sepulsa_transaction, point_usage_history
                )
            )
        except OperationalError:
            sentry_client.captureException()
            return general_error_response(
                ERROR_CODE_MESSAGE_MAPPING[RedemptionMethodErrorCode.OPERATIONAL_ERROR]
            )
        except DanaException as error_code:
            return general_error_response(ERROR_CODE_MESSAGE_MAPPING[str(error_code)])


class CheckDanaTransfer(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = CheckDanaTransferTransactionSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        transaction_id = serializer.validated_data['transaction_id']
        point_usage_his = get_point_usage_history_by_reference(
            PointRedeemReferenceTypeConst.DANA_TRANSFER,
            transaction_id,
        )
        sepulsa_transaction = SepulsaTransaction.objects.get(id=transaction_id)
        return success_response(
            construct_data_response_success_dana_transfer(
                sepulsa_transaction, point_usage_his
            )
        )


class FloatingActionButtonAPI(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        application = Application.objects.get_active_julo_product_applications().filter(
            customer_id=customer.pk,
        ).last()
        if not application:
            return not_found_response(message='Application not found')

        data_response = get_floating_action_button_info()
        return success_response(data_response)


class LoyaltyEntryPointAPIView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        customer = request.user.customer
        application = Application.objects.get_active_julo_product_applications().filter(
            customer_id=customer.pk,
        ).last()
        if not application:
            return not_found_response(message='Application not found')

        if not is_eligible_for_loyalty_entry_point(customer.id):
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=['Feature setting not found']
            )

        loyalty_point = get_non_locked_loyalty_point(customer_id=customer.id)
        has_new_reward, label = get_loyalty_entry_point_information(customer.id)
        return success_response({
            'loyalty_point': loyalty_point.total_point,
            'has_new_reward': has_new_reward,
            'label': label,
        })
