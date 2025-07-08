import re

from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView

from juloserver.julo.models import Loan
from juloserver.promo.constants import (
    PromoCodeMessage,
    PromoCodeTypeConst,
    PromoCMSCategory,
)
from juloserver.promo.models import PromoCode
from juloserver.promo.constants import PromoCodeBenefitConst

from juloserver.promo.serializers import (
    PromoCodeCheckSerializer,
    PromoCMSDetailSerializer,
    PromoCodeTnCSerializer,
    PromoCodeSerializer,
)
from juloserver.promo.services import (
    check_promo_code_and_get_message,
    get_existing_promo_code,
    get_promo_code_benefit_tnc,
    get_promo_cms_info,
    get_promo_cms_detail,
    sort_promo_code_list_highest_first,
    get_promo_code_super_type,
    get_search_categories,
    is_valid_promo_code_whitelist,
)

from juloserver.standardized_api_response.utils import (
    forbidden_error_response,
    general_error_response,
    success_response,
    response_template,
    not_found_response,
)


class LoanPromoCodeCheckV1(APIView):
    serializer_class = PromoCodeCheckSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        data = serializer.data

        loan = Loan.objects.get_or_none(loan_xid=data['loan_xid'])

        if not loan:
            return general_error_response("Invalid Loan")

        if user.id != loan.customer.user_id:
            return forbidden_error_response(
                message=['User not allowed'],
            )

        promo_code = get_existing_promo_code(data['promo_code'])
        if not promo_code:
            return general_error_response(PromoCodeMessage.ERROR.WRONG)

        is_valid, message = check_promo_code_and_get_message(
            promo_code=promo_code,
            loan=loan,
        )
        if not is_valid:
            return general_error_response(message=message)

        data = {
            'message': message,
            'terms': get_promo_code_benefit_tnc(promo_code),
        }
        return success_response(data=data)


class PromoCodeTnCRetrieveView(APIView):
    serializer_class = PromoCodeTnCSerializer

    def get(self, request, promo_code):
        promo = PromoCode.objects.filter(promo_code__iexact=promo_code).last()
        if not promo:
            return general_error_response(PromoCodeMessage.ERROR.WRONG)
        serializer = self.serializer_class(instance=promo)
        return success_response(data=serializer.data)


class PromoCMSList(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, *args, **kwargs):
        data = request.query_params
        category = data.get('category', PromoCMSCategory.ALL)
        data_res = get_promo_cms_info(category)
        return success_response(data=data_res)


class PromoCMSDetail(APIView):
    permission_classes = (AllowAny,)
    serializer_class = PromoCMSDetailSerializer

    def get(self, request, *args, **kwargs):
        data = request.query_params
        serializer = self.serializer_class(data=data)
        serializer.is_valid()
        if serializer.errors:
            return response_template(
                status=HTTP_400_BAD_REQUEST,
                success=False,
                message=['Incorrect request data']
            )
        data_detail = get_promo_cms_detail(data['nid'])
        return success_response(data=data_detail)


class LoanPromoCodeCheckV2(APIView):
    serializer_class = PromoCodeCheckSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        data = serializer.data

        loan = Loan.objects.get_or_none(loan_xid=data['loan_xid'])

        if not loan:
            return not_found_response('Not found')

        if user.id != loan.customer.user_id:
            return not_found_response('Not found')

        promo_code = get_existing_promo_code(data['promo_code'])
        if not promo_code:
            return not_found_response(PromoCodeMessage.ERROR.WRONG)

        is_valid, message = check_promo_code_and_get_message(
            promo_code=promo_code,
            loan=loan,
        )

        if not is_valid:
            return general_error_response(message=message)

        return success_response(data={
            'promo_code_type': get_promo_code_super_type(promo_code),
            'message': message
        })


class LoanPromoCodeListViewV2(ListAPIView):
    serializer_class = PromoCodeSerializer

    def get_queryset(self):
        now = timezone.localtime(timezone.now())
        # Restrict promo code v2
        return PromoCode.objects.filter(
            type=PromoCodeTypeConst.LOAN,
            start_date__lte=now, end_date__gte=now,
            is_active=True, is_public=True
        ).exclude(
            promo_code_benefit__type__in=PromoCodeBenefitConst.PROMO_CODE_BENEFIT_V2_APPLIED_DURING_LOAN_CREATION
        )

    def filter_queryset(self, queryset):
        loan_xid = self.kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        return_qs = []

        for promo_code in queryset:
            if not is_valid_promo_code_whitelist(promo_code, loan.customer_id):
                continue

            is_valid, message = check_promo_code_and_get_message(promo_code, loan)
            promo_code.is_eligible = is_valid
            if is_valid:
                promo_code.message = message
            else:
                promo_code.ineligibility_reason = message

            pattern = PromoCodeMessage.ERROR.MINIMUM_LOAN_AMOUNT
            pattern = pattern.replace('{minimum_amount}', 'Rp \d[\d.,]*\d')
            if is_valid or re.fullmatch(pattern, message):
                return_qs.append(promo_code)

        # sorting
        return_qs = sort_promo_code_list_highest_first(promo_codes=return_qs)

        return return_qs

    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data)


class PromoCMSGetSearchCategories(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, *args, **kwargs):
        data_res = get_search_categories()
        return success_response(data=data_res)
