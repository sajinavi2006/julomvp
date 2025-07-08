from rest_framework.views import APIView

from juloserver.education.constants import SuccessMessage
from juloserver.education.exceptions import EducationException
from juloserver.education.serializers import (
    CreateStudentRegisterSerializer,
    CreateStudentRegisterReponseSerializer,
    DeleteStudentRegisterSerializer,
    DeleteStudentRegisterReponseSerializer,
    StudentRegisterListReponseSerializer,
    UpdateStudentRegisterPathParamSerializer,
    UpdateStudentRegisterSerializer,
)
from juloserver.education.services.views_related import (
    is_eligible_for_education,
    get_list_student_register,
    process_student_register,
    delete_student_register,
    process_student_register_update,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import success_response

from juloserver.education.serializers import (
    SchoolListReponseSerializer,
    EducationFAQSerializer,
)
from juloserver.education.services.views_related import (
    get_school_list_and_allow_adding_feature,
    get_education_faq,
)


class EducationAPIView(StandardizedExceptionHandlerMixin, APIView):
    def validate_data(self, serializer_class, data, is_multiple=False, context=None):
        serializer = serializer_class(data=data, many=is_multiple, context=context)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def check_eligible_for_education(self, customer, account):
        is_eligible, error_message = is_eligible_for_education(
            application=account.get_active_application(), account=account
        )
        if not is_eligible:
            raise EducationException(error_message)


class StudentRegisterListAndCreateView(EducationAPIView):
    def get(self, request):
        customer = request.user.customer
        account = customer.account

        self.check_eligible_for_education(customer=customer, account=account)

        return success_response(
            self.validate_data(
                serializer_class=StudentRegisterListReponseSerializer,
                data=get_list_student_register(account=account),
            )
        )

    def post(self, request):
        customer = request.user.customer
        account = customer.account
        application = account.get_active_application()

        data = self.validate_data(
            serializer_class=CreateStudentRegisterSerializer,
            data=request.data,
            context={'application': application},
        )

        self.check_eligible_for_education(customer=customer, account=account)

        student_register_id, bank_account_destination_id = process_student_register(
            application=application,
            customer=customer,
            account=account,
            bank=data['bank_obj'],
            bank_name_validation_log=data['bank_name_validation_log_obj'],
            school_id=data['school']['id'],
            school_name=data['school']['name'],
            student_fullname=data['name'],
            note=data['note'],
        )

        return success_response(
            self.validate_data(
                serializer_class=CreateStudentRegisterReponseSerializer,
                data={
                    'student_register_id': student_register_id,
                    'bank_account_destination_id': bank_account_destination_id,
                },
            )
        )

    def delete(self, request):
        customer = request.user.customer
        account = customer.account

        data = self.validate_data(
            serializer_class=DeleteStudentRegisterSerializer,
            data=request.data,
            context={'account': account},
        )

        self.check_eligible_for_education(customer=customer, account=account)

        delete_student_register(student_register=data['student_register_obj'])

        return success_response(
            self.validate_data(
                serializer_class=DeleteStudentRegisterReponseSerializer,
                data={
                    'message': SuccessMessage.DELETE_SUCCESS,
                },
            )
        )

    def put(self, request, student_register_id):
        customer = request.user.customer
        application = customer.application_set.last()
        account = request.user.customer.account

        student_register = self.validate_data(
            serializer_class=UpdateStudentRegisterPathParamSerializer,
            data={'student_register_id': student_register_id},
            context={'account': account},
        )

        data = self.validate_data(
            serializer_class=UpdateStudentRegisterSerializer,
            data=request.data,
            context={'application': application, 'current_school_id': student_register.school_id},
        )

        self.check_eligible_for_education(customer=customer, account=account)

        student_register_id, bank_account_destination_id = process_student_register_update(
            student_register=student_register,
            application=application,
            customer=customer,
            account=account,
            bank=data['bank_obj'] if data['bank'] else None,
            bank_name_validation_log=data['bank_name_validation_log_obj'] if data['bank'] else None,
            school_id=data['school']['id'],
            school_name=data['school']['name'],
            student_fullname=data['name'],
            note=data['note'],
        )

        return success_response(
            self.validate_data(
                serializer_class=CreateStudentRegisterReponseSerializer,
                data={
                    'student_register_id': student_register_id,
                    'bank_account_destination_id': bank_account_destination_id,
                },
            )
        )


class SchoolListView(EducationAPIView):
    serializer_class = None

    def get(self, request):
        limit = int(request.GET.get('limit', 500))
        keyword = request.GET.get('query', '')

        return success_response(
            self.validate_data(
                serializer_class=SchoolListReponseSerializer,
                data=get_school_list_and_allow_adding_feature(limit, keyword),
            ),
        )


class EducationFAQView(EducationAPIView):
    serializer_class = None

    def get(self, request):
        return success_response(
            data={"faq": self.validate_data(EducationFAQSerializer, get_education_faq(), True)}
        )
