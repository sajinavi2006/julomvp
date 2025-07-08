from rest_framework.views import APIView

from juloserver.healthcare.constants import SuccessMessage
from juloserver.healthcare.permissions import HealthCarePermission
from juloserver.healthcare.services.views_related import (
    delete_healthcare_user,
    get_healthcare_faq,
    get_healthcare_platform_list_and_allow_adding_feature,
    get_list_active_healthcare_user_by_account,
    process_healthcare_user,
    process_healthcare_user_update,
)
from juloserver.healthcare.serializers import (
    HealthcareUserSerializer,
    HealthcareFaqOutputSerializer,
    HealthcarePlatformReponseSerializer,
    CreateHealthcareUserSerializer,
    HealthcareUserUpdateSerializer,
    UpdateHealthcarePlatformRegisterPathParamSerializer,
    CreateHealthcareUpdateReponseSerializer,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
)


class HealthcareAPIView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (HealthCarePermission,)

    def validate_data(self, serializer_class, data, is_multiple=False, context=None):
        serializer = serializer_class(data=data, many=is_multiple, context=context)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class HeathCareUserAPIListCreateView(HealthcareAPIView):
    def get(self, request):
        customer = request.user.customer
        account = customer.account

        queryset = get_list_active_healthcare_user_by_account(account.pk)
        serializer = HealthcareUserSerializer(queryset, many=True)
        response_data = {'healthcare_users': serializer.data}

        return success_response(response_data)


class HealthcareFAQView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (HealthCarePermission,)

    def get(self, request):
        serializer = HealthcareFaqOutputSerializer(get_healthcare_faq(), many=True)
        return success_response(data={"faq": serializer.data})


class HelathcarePlatformAPIListView(HealthcareAPIView):
    def get(self, request):
        limit = int(request.GET.get('limit', 500))
        keyword = request.GET.get('query', '')

        return success_response(
            self.validate_data(
                serializer_class=HealthcarePlatformReponseSerializer,
                data=get_healthcare_platform_list_and_allow_adding_feature(limit, keyword),
            ),
        )


class HealthcareUserAPICreatePutDeleteView(HealthcareAPIView):
    def post(self, request):
        customer = request.user.customer
        account = customer.account
        application = account.get_active_application()

        data = self.validate_data(
            serializer_class=CreateHealthcareUserSerializer,
            data=request.data,
            context={'application': application},
        )
        healthcare_user = process_healthcare_user(
            application=application,
            customer=customer,
            account=account,
            bank=data['bank_obj'],
            bank_name_validation_log=data['bank_name_validation_log_obj'],
            healthcare_platform_id=data['healthcare_platform']['id'],
            healthcare_platform_name=data['healthcare_platform']['name'],
            healthcare_user_fullname=data.get('name', '') or '',
        )

        return success_response(HealthcareUserSerializer(healthcare_user).data)

    def delete(self, request, pk):
        delete_healthcare_user(user_id=pk, request_user=request.user)

        return success_response(
            data={
                "message": SuccessMessage.DELETE_SUCCESS,
            },
        )

    def put(self, request, pk):
        customer = request.user.customer
        account = customer.account
        application = account.get_active_application()

        healthcare_user = self.validate_data(
            serializer_class=UpdateHealthcarePlatformRegisterPathParamSerializer,
            data={'healthcare_user_id': pk},
            context={'account': account},
        )

        data = self.validate_data(
            serializer_class=HealthcareUserUpdateSerializer,
            data=request.data,
            context={
                'application': application,
                'current_healthcare_platform_id': healthcare_user.healthcare_platform_id
            },
        )
        healthcare_user_id, bank_account_destination_id = process_healthcare_user_update(
            healthcare_user=healthcare_user,
            application=application,
            customer=customer,
            account=account,
            bank=data['bank_obj'] if data['bank'] else None,
            bank_name_validation_log=data['bank_name_validation_log_obj'] if data['bank'] else None,
            healthcare_platform_id=data['healthcare_platform']['id'],
            healthcare_platform_name=data['healthcare_platform']['name'],
            healthcare_user_fullname=data.get('name', ''),
        )

        return success_response(
            self.validate_data(
                serializer_class=CreateHealthcareUpdateReponseSerializer,
                data={
                    'healthcare_user_id': healthcare_user_id,
                    'bank_account_destination_id': bank_account_destination_id,
                },
            )
        )
