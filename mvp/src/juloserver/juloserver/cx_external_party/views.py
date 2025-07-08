import logging

from django.utils import timezone
from rest_framework import exceptions
from rest_framework.views import APIView

from juloserver.account.models import Account
from juloserver.cx_external_party.authentication import (
    CXAPIKeyAuthentication,
    CXUserTokenAuthentication,
)
from juloserver.cx_external_party.constants import (
    ERROR_MESSAGE,
    YELLOW_API_USE_CASE,
)
from juloserver.cx_external_party.parser import APIKeyParser
from juloserver.cx_external_party.serializers import (
    AppDcoumentVerifySerializer,
    CustomerInfoSerializer,
    CustomerLoanPaymentSerializer,
    CustomerPersonalDataSerializer,
    ExternalPartySerializer,
    SecurityInfoSerializer,
    UserTokenSerializer,
)
from juloserver.cx_external_party.services import (
    get_customer,
    get_history_list,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import ApplicationNote, Image
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    internal_server_error_response,
    not_found_response,
    success_response,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class GenerateUserToken(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [CXAPIKeyAuthentication]
    permission_classes = []
    key_parser = APIKeyParser()
    serializer_class = UserTokenSerializer
    http_method_names = ['post']

    def post(self, request):
        key = self.key_parser.get(request)
        serializer = self.serializer_class(data=request.data, context={"key": key})
        if not serializer.is_valid():
            return general_error_response(serializer.errors)
        serializer.save()
        return success_response(serializer.data)


class ExternalDetailAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [CXAPIKeyAuthentication]
    serializer_class = ExternalPartySerializer
    permission_classes = []

    def get(self, request):
        if not request.external_party:
            return not_found_response(ERROR_MESSAGE.EXTERNAL_PARTY_NOT_FOUND)

        serializer = self.serializer_class(request.external_party)
        return success_response(serializer.data)


class UserExternalDetailAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [CXUserTokenAuthentication]
    permission_classes = []

    def get(self, request):
        if not request.external_party and not request.user_external_party:
            return not_found_response(ERROR_MESSAGE.USER_EXTERNAL_PARTY_NOT_FOUND)
        request.user_external_party.pop("_api_key")
        return success_response(request.user_external_party)


class CustomerView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [CXUserTokenAuthentication]
    permission_classes = []
    serializer_class = None

    def get_object(self):
        nik = self.request.query_params.get('nik', None)
        email = self.request.query_params.get('email', None)
        if not nik or not email:
            raise exceptions.APIException(ERROR_MESSAGE.MSG_NIK_EMAIL_REQUIRED)

        customer = get_customer(nik, email)
        if not customer:
            logger.info(
                {
                    'action': 'cx_external_party_get_customer_data',
                    'status_code': 404,
                    'customer_id': None,
                    'message': ERROR_MESSAGE.MSG_DATA_NOT_FOUND,
                }
            )
            raise exceptions.NotFound(ERROR_MESSAGE.MSG_DATA_NOT_FOUND)

        if not customer.prefetched_applications and not customer.prefetched_active_applications:
            logger.info(
                {
                    'action': 'cx_external_party_get_customer_data',
                    'status_code': 404,
                    'customer_id': None,
                    'message': ERROR_MESSAGE.USER_APPLICATION_NOT_FOUND,
                }
            )
            raise exceptions.NotFound(ERROR_MESSAGE.USER_APPLICATION_NOT_FOUND)

        return customer

    def get(self, request):
        try:
            object = self.get_object()
        except exceptions.NotFound as e:
            return not_found_response(str(e))
        except exceptions.APIException as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_customer_data',
                    'status_code': 400,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return general_error_response(str(e))
        except Exception as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_customer_data',
                    'status_code': 500,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return internal_server_error_response(str(e))

        serializer = self.serializer_class(object)
        return success_response(serializer.data)


class CustomerInfoView(CustomerView):
    serializer_class = CustomerInfoSerializer


class SecurityInfoView(CustomerView):
    serializer_class = SecurityInfoSerializer


class AppDocumentVerifyView(CustomerView):
    serializer_class = AppDcoumentVerifySerializer

    def get_object(self):
        customer = super().get_object()
        app_obj = customer.get_active_or_last_application
        images = Image.objects.filter(
            image_source=app_obj.id, image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
        )
        return images

    def get(self, request):
        try:
            object = self.get_object()
        except exceptions.NotFound as e:
            return not_found_response(str(e))
        except exceptions.APIException as e:
            return general_error_response(str(e))

        serializer = self.serializer_class(object, many=True)
        return success_response(serializer.data)


class UserStatusHistoryView(CustomerView):
    def get_object(self):
        customer = super().get_object()
        user_status_history = get_history_list(customer)
        if not user_status_history:
            logger.info(
                {
                    'action': 'cx_external_party_get_user_status_history',
                    'status_code': 404,
                    'customer_id': None,
                    'message': ERROR_MESSAGE.MSG_DATA_NOT_FOUND,
                }
            )
            return not_found_response(ERROR_MESSAGE.MSG_DATA_NOT_FOUND)

        return user_status_history

    def get(self, request):
        try:
            object = self.get_object()
        except exceptions.NotFound as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_user_status_history',
                    'status_code': 404,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return not_found_response(str(e))
        except exceptions.APIException as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_user_status_history',
                    'status_code': 400,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return general_error_response(str(e))
        except Exception as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_user_status_history',
                    'status_code': 500,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return internal_server_error_response(str(e))

        return success_response(object)


class CustomerPersonalDataView(CustomerView):
    serializer_class = CustomerPersonalDataSerializer


class CustomerLoanDataView(CustomerView):
    def get_object(self):
        customer = super().get_object()
        account = Account.objects.filter(customer_id=customer.id).last()
        if not account:
            raise exceptions.NotFound(ERROR_MESSAGE.ACCOUNT_NOT_FOUND)

        active_Loans = account.get_all_active_loan()
        if not active_Loans:
            return ERROR_MESSAGE.LOAN_NOT_FOUND

        remaining_loan_amount_total = 0
        for account_payment in account.accountpayment_set.all():
            remaining_loan_amount_total += account_payment.remaining_installment_amount()

        data = {
            "loan_amount": remaining_loan_amount_total,
            "loan_duration": account.sum_of_all_active_loan_duration(),
            "installment_amount": account.sum_of_all_active_installment_amount(),
            "cashback_earned_total": account.sum_of_all_active_loan_cashback_earned_total(),
            "loan_disbursement_amount": account.sum_of_all_active_loan_disbursement_amount(),
        }

        return data

    def get(self, request):
        customer = super().get_object()
        use_case = self.request.query_params.get('use_case', None)
        if use_case not in YELLOW_API_USE_CASE["loan"]:
            return general_error_response(ERROR_MESSAGE.USECASE_PARAM_INVALID)
        else:
            try:
                data = self.get_object()
            except exceptions.NotFound as e:
                logger.info(
                    {
                        'action': 'cx_external_party_get_customer_loan',
                        'status_code': 404,
                        'customer_id': None,
                        'message': str(e),
                    }
                )
                return not_found_response(str(e))
            except exceptions.APIException as e:
                logger.info(
                    {
                        'action': 'cx_external_party_get_customer_loan',
                        'status_code': 400,
                        'customer_id': None,
                        'message': str(e),
                    }
                )
                return general_error_response(str(e))
            except Exception as e:
                logger.info(
                    {
                        'action': 'cx_external_party_get_customer_loan',
                        'status_code': 500,
                        'customer_id': None,
                        'message': str(e),
                    }
                )
                return internal_server_error_response(str(e))

            if data and isinstance(data, dict) and use_case:
                message = "Loan was found"
                data = data[use_case]

            else:
                message = data
                data = []

        logger.info(
            {
                'action': 'cx_external_party_get_customer_loan',
                'status_code': 200,
                'customer_id': str(customer.id),
                'message': message,
            }
        )

        return success_response(data=data, message=message)


class AccountPaymentDataView(CustomerView):
    def get_object(self):
        use_case = self.request.query_params.get('use_case', None)
        customer = super().get_object()
        account = Account.objects.filter(customer_id=customer.id).first()
        if not account:
            raise exceptions.NotFound(ERROR_MESSAGE.ACCOUNT_NOT_FOUND)

        data = {}
        if use_case in YELLOW_API_USE_CASE["next_payment"]:
            if use_case == "late_fee_amount":
                oldest_unpaid_payment = account.get_oldest_unpaid_account_payment()
                if not oldest_unpaid_payment:
                    return ERROR_MESSAGE.LAST_PAYMENT_NOT_FOUND

                data = {**data, **{"late_fee_amount": oldest_unpaid_payment.late_fee_amount}}
            else:
                unpaid_account_payment = account.accountpayment_set.not_paid_active().first()
                if not unpaid_account_payment:
                    return ERROR_MESSAGE.NEXT_PAYMENT_NOT_FOUND

                # next_payment = unpaid_account_payment.get_next_unpaid_payment()
                next_payment_queryset = account.accountpayment_set.filter(
                    due_date__gt=timezone.localtime(timezone.now()),
                    status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
                )
                if next_payment_queryset:
                    next_payment = next_payment_queryset.order_by("due_date").first()
                else:
                    next_payment = None

                if not next_payment:
                    return ERROR_MESSAGE.NEXT_PAYMENT_NOT_FOUND

                data = {
                    **data,
                    **{
                        "due_date": next_payment.due_date,
                        "due_amount": next_payment.due_amount,
                        "principal_amount": next_payment.principal_amount,
                        "interest_amount": next_payment.interest_amount,
                    },
                }

        elif use_case in YELLOW_API_USE_CASE["last_payment"]:
            last_payment = (
                account.accountpayment_set.paid_or_partially_paid().order_by('paid_date').last()
            )
            if not last_payment:
                return ERROR_MESSAGE.LAST_PAYMENT_NOT_FOUND
            data = {
                "paid_date": last_payment.paid_date,
                "paid_amount": last_payment.paid_amount,
            }

        else:
            return ERROR_MESSAGE.USECASE_PARAM_INVALID

        return data

    def get(self, request):
        customer = super().get_object()
        use_case = self.request.query_params.get('use_case', None)
        try:
            data = self.get_object()
        except exceptions.NotFound as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_customer_account_payment',
                    'status_code': 404,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return not_found_response(str(e))
        except exceptions.APIException as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_customer_account_payment',
                    'status_code': 400,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return general_error_response(str(e))
        except Exception as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_customer_account_payment',
                    'status_code': 500,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return internal_server_error_response(str(e))

        if data and isinstance(data, dict) and use_case:
            message = "Account payment was found"
            data = data[use_case]
        else:
            message = data
            data = []

        logger.info(
            {
                'action': 'cx_external_party_get_customer_account_payment',
                'status_code': 200,
                'customer_id': str(customer.id),
                'message': message,
            }
        )

        return success_response(data=data, message=message)


class CustomerLoanPaymentView(CustomerView):
    serializer_class = CustomerLoanPaymentSerializer


class UserApplicationStatusView(CustomerView):
    def get_object(self):
        customer = super().get_object()
        application = customer.last_application
        if not application:
            logger.info(
                {
                    'action': 'cx_external_party_get_last_app_status',
                    'status_code': 404,
                    'customer_id': customer.id,
                    'message': ERROR_MESSAGE.USER_APPLICATION_NOT_FOUND,
                }
            )
            return not_found_response(ERROR_MESSAGE.USER_APPLICATION_NOT_FOUND)

        last_history = application.applicationhistory_set.last()
        application_note = ApplicationNote.objects.filter(application_id=application.pk).last()

        return {
            "application_cdate": application.cdate,
            "application_udate": application.udate,
            "application_id": application.id,
            "application_status_code": application.status,
            "application_last_history": {
                "id": last_history.pk,
                "status_old": last_history.status_old,
                "status_new": last_history.status_new,
                "change_reason": last_history.change_reason,
            }
            if last_history
            else {},
            "application_note": {
                "cdate": application_note.cdate,
                "udate": application_note.udate,
                "note_text": application_note.note_text,
            }
            if application_note
            else {},
        }

    def get(self, request):
        try:
            object = self.get_object()
        except exceptions.NotFound as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_last_app_status',
                    'status_code': 404,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return not_found_response(str(e))
        except exceptions.APIException as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_last_app_status',
                    'status_code': 400,
                    'customer_id': None,
                    'message': str(e),
                }
            )
            return general_error_response(str(e))
        except Exception as e:
            logger.info(
                {
                    'action': 'cx_external_party_get_last_app_status',
                    'status_code': 500,
                    'customer_id': None,
                    'message': str(e),
                }
            )

        logger.info(
            {
                'action': 'cx_external_party_get_last_app_status',
                'status_code': 200,
                'customer_id': None,
                'message': 'Data was found',
            }
        )
        return success_response(object)
