from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
from django.utils import timezone

from juloserver.payment_point.models import TransactionMethod
from juloserver.promo.constants import PromoCodeMessage, PromoCodeTypeConst, PromoCodeCriteriaConst, \
    PromoCodeBenefitConst
from juloserver.promo.exceptions import BenefitTypeDoesNotExist
from juloserver.promo.models import PromoCode
from juloserver.promo.serializers import PromoCodeCheckSerializerV3, PromoCodeSerializerV3, \
    PromoCodeQueryParamSerializer
from juloserver.promo.services import is_valid_promo_code_whitelist, get_existing_promo_code, \
    sort_promo_code_list_highest_first
from juloserver.promo.services_v3 import (
    check_promo_code_and_get_message_v2,
    get_promo_code_super_type,
)
from juloserver.standardized_api_response.utils import not_found_response, general_error_response, \
    success_response


class LoanPromoCodeCheckV3(APIView):
    serializer_class = PromoCodeCheckSerializerV3

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.data
        transaction_method_id = data['transaction_method_id']
        transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
        if not transaction_method:
            return not_found_response(PromoCodeMessage.ERROR.INVALID_TRANSACTION_METHOD)

        promo_code = get_existing_promo_code(data['promo_code'])
        if not promo_code:
            return not_found_response(PromoCodeMessage.ERROR.WRONG)

        benefit = promo_code.promo_code_benefit
        if benefit.type not in PromoCodeBenefitConst.PROMO_CODE_BENEFIT_TYPE_V2_SUPPORT:
            return general_error_response(
                message=PromoCodeMessage.ERROR.PROMO_CODE_BENEFIT_NOT_SUPPORT
            )

        loan_amount = data['loan_amount']
        loan_duration = data['loan_duration']
        customer = request.user.customer
        application = customer.application_set.regular_not_deletes().last()

        failed_criterion, message = check_promo_code_and_get_message_v2(
            application=application,
            promo_code=promo_code,
            loan_amount=loan_amount,
            transaction_method_id=transaction_method_id,
            loan_duration=loan_duration,
        )

        if failed_criterion:
            return general_error_response(message=message)

        return success_response(data={
            'promo_code_type': get_promo_code_super_type(promo_code),
            'message': message
        })


class LoanPromoCodeListViewV3(ListAPIView):
    serializer_class = PromoCodeSerializerV3

    def get_queryset(self):
        now = timezone.localtime(timezone.now())
        return PromoCode.objects.filter(
            type=PromoCodeTypeConst.LOAN,
            start_date__lte=now,
            end_date__gte=now,
            is_active=True,
            is_public=True,
            promo_code_benefit__type__in=PromoCodeBenefitConst.PROMO_CODE_BENEFIT_TYPE_V2_SUPPORT
        )

    def filter_queryset(self, queryset):
        serializer = PromoCodeQueryParamSerializer(data=self.request.query_params)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()

        loan_amount = validated_data['loan_amount']
        transaction_method_id = validated_data['transaction_method_id']
        loan_duration = validated_data['loan_duration']

        valid_promo_codes = []

        for promo in queryset:
            if not is_valid_promo_code_whitelist(promo, customer.id):
                continue
            try:
                failed_criterion, message = check_promo_code_and_get_message_v2(
                    application, promo, loan_amount, transaction_method_id, loan_duration
                )
            except BenefitTypeDoesNotExist:
                continue

            is_valid = not failed_criterion
            promo.is_eligible = is_valid
            if is_valid:
                promo.message = message
                valid_promo_codes.append(promo)
            else:
                promo.ineligibility_reason = message
                if failed_criterion.type == PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT:
                    valid_promo_codes.append(promo)

        return sort_promo_code_list_highest_first(valid_promo_codes)

    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)
