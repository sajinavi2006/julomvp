from builtins import str
import logging

from rest_framework.views import APIView

from .serializers import ConfirmOtpSerializer, ReuploadPrivyImageSerializer
from .services import (get_privy_customer_data,
                       check_status_privy_user,
                       get_privy_document_data,
                       check_privy_document_status,
                       get_otp_token,
                       request_otp_to_privy,
                       confirm_otp_to_privy,
                       proccess_signing_document,
                       get_privy_feature,
                       get_failover_feature,
                       update_digital_signature_face_recognition)
from .tasks import upload_document_privy, create_new_privy_user
from .constants import CustomerStatusPrivy

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (general_error_response,
                                                        not_found_response,
                                                        success_response,
                                                        created_response)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo_privyid.exceptions import JuloPrivyLogicException
from juloserver.julo_privyid.services.usecases import check_document_status_for_upload
from juloserver.julo_privyid.services.usecases import upload_document_privy_service
from juloserver.julo_privyid.services.usecases import request_otp_privy_service
from juloserver.julo_privyid.services.usecases import confirm_otp_privy_service
from juloserver.julo_privyid.services.usecases import sign_document_privy_service
from juloserver.julo_privyid.services.usecases import reregister_privy_service
from .exceptions import PrivyNotFailoverException, PrivyApiResponseException, \
    PrivyDocumentExistException, JuloPrivyException
from juloserver.julo_privyid.services.privy_services import check_customer_status
from rest_framework.generics import CreateAPIView
from ..julo.tasks import upload_image
import rest_framework.status as status
from rest_framework.response import Response
from .constants import PRIVY_IMAGE_TYPE

logger = logging.getLogger(__name__)


class PrivyAPIView(StandardizedExceptionHandlerMixin, APIView):

    def validate_data(self, serializer_class, data):
        serializer = serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class PrivyFeatureStatus(PrivyAPIView):

    def get(self, request):
        failover = get_failover_feature()
        privy = get_privy_feature()

        return_response = {
            'is_privy_mode': privy,
            'is_failover_active': failover
        }

        return success_response(return_response)


class PrivyCustomerStatus(PrivyAPIView):

    def get(self, request):
        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()

        failover = get_failover_feature()
        privy = get_privy_feature()
        return_response = {
            'privy_status': 'unregistered',
            'is_privy_mode': privy,
            'is_failover_active': failover,
            'failed': False
        }

        privy_customer = get_privy_customer_data(customer)

        if not privy_customer:
            if privy:
                if (application.status ==
                        ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING):
                    create_new_privy_user.delay(application.id)
            return success_response(return_response)

        user_token = privy_customer.privy_customer_token
        user_data, response = check_status_privy_user(user_token, application)

        if not user_data:
            return_response['privy_status'] = privy_customer.privy_customer_status
            return success_response(return_response)

        if user_data.reject_reason is not None:
            if not failover:
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.DIGISIGN_FAILED,
                    user_data.reject_reason
                )
        update_digital_signature_face_recognition(application, user_data)

        return_response['privy_status'] = user_data.privy_customer_status

        return success_response(return_response)


class PrivyDocumentUpload(PrivyAPIView):

    def post(self, request):
        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()

        document_max_retry = int(request.data['max_count'])
        upload_retry_count = int(request.data['retry_count'])
        if not document_max_retry or (not upload_retry_count and upload_retry_count != 0):
            return general_error_response('Something wrong!! parameters incomplete for upload')
        privy_customer = get_privy_customer_data(customer)
        if not privy_customer:
            return not_found_response('Customer did not registered to privy yet')

        if privy_customer.privy_customer_status not in CustomerStatusPrivy.ALLOW_UPLOAD:
            return general_error_response('Customer not verifed yet')

        privy_document = get_privy_document_data(application)
        if privy_document:
            return success_response(None)

        upload_document_privy.delay(application.id)

        if document_max_retry == upload_retry_count + 1:
            privy_document = get_privy_document_data(application)
            if privy_document:
                return success_response(None)
            else:
                if not get_failover_feature():
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.DIGISIGN_FAILED,
                        'privy_document_upload_failed'
                    )
                    return success_response(None)
        return created_response(None)


class PrivyDocumentStatus(PrivyAPIView):

    def get(self, request):
        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()

        failover = get_failover_feature()
        privy = get_privy_feature()
        return_response = {
            'document_status': 'not_exist',
            'is_privy_mode': privy,
            'is_failover_active': failover
        }

        privy_document = get_privy_document_data(application)
        if not privy_document:
            return success_response(return_response)

        document_data = check_privy_document_status(privy_document, application)

        if not document_data:
            return_response['document_status'] = privy_document.privy_document_status

        return_response['document_status'] = document_data.privy_document_status

        return success_response(return_response)


class PrivyRequestOtp(PrivyAPIView):

    def post(self, request):
        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()

        privy_customer = get_privy_customer_data(customer)
        if not privy_customer:
            return not_found_response('Customer did not registered to privy yet')

        otp_token = get_otp_token(privy_customer.privy_id, application.id)
        if not otp_token:
            return general_error_response('Something wrong!! failed generate otp token')

        request_otp = request_otp_to_privy(otp_token, application.id)

        if not request_otp:
            return general_error_response('Something wrong!! failed request OTP')

        return success_response({
            'sent_to': application.mobile_phone_1
        })


class PrivyConfirmOtp(PrivyAPIView):
    serializer_class = ConfirmOtpSerializer

    def post(self, request):
        data = request.data
        # validate request data
        otp_data = self.validate_data(self.serializer_class, data)
        otp_code = otp_data['otp_code']

        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()

        privy_customer = get_privy_customer_data(customer)
        if not privy_customer:
            return not_found_response('Customer did not registered to privy yet')

        otp_token = get_otp_token(privy_customer.privy_id, application.id)
        if not otp_token:
            return general_error_response('Something wrong!! failed generate otp token')

        confirm_otp = confirm_otp_to_privy(otp_code, otp_token, application.id)

        if not confirm_otp:
            return general_error_response('Something wrong!! failed request OTP')

        return success_response(None)


class PrivySignDocument(PrivyAPIView):

    def post(self, request):
        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()

        privy_document = get_privy_document_data(application)
        if not privy_document:
            return not_found_response('privy document Not Found')

        privy_customer = privy_document.privy_customer
        otp_token = get_otp_token(privy_customer.privy_id, application.id)
        if not otp_token:
            return general_error_response('Something wrong!! failed generate otp token')

        signing_document = proccess_signing_document(
            privy_document.privy_document_token, otp_token, application.id)

        if not signing_document:
            return general_error_response('Something wrong!! cant signing document privy')

        check_privy_document_status(privy_document, application)

        return success_response(None)


"""
Refactored Code
"""


class PrivyCustomerStatusView(PrivyAPIView):
    def get(self, request):
        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()
        if not application:
            raise JuloPrivyException(
                "Application Not found for customer {}".format(customer.id)
            )

        try:
            return_response = check_customer_status(customer, application)
        except PrivyApiResponseException as e:
            return general_error_response(str(e))
        except JuloPrivyLogicException as e:
            return general_error_response(str(e))
        return success_response(return_response)


class PrivyDocumentStatusView(PrivyAPIView):

    def get(self, request, loan_xid):
        try:
            document_status, is_privy_mode, is_failover_active = check_document_status_for_upload(
                request.user, loan_xid)
        except JuloPrivyLogicException as e:
            return general_error_response(str(e))

        response_data = {
            'document_status': document_status,
            'is_privy_mode': is_privy_mode,
            'is_failover_active': is_failover_active
        }
        return success_response(data=response_data)


class PrivyDocumentUploadView(PrivyAPIView):

    def post(self, request):
        loan_xid = request.data.get('loan_xid')
        try:
            upload_document_privy_service(request.user, loan_xid, request.data)
        except (JuloPrivyLogicException, PrivyNotFailoverException,
                PrivyDocumentExistException) as e:
            return general_error_response(str(e))
        return created_response(None)


class PrivyRequestOtpView(PrivyAPIView):

    def post(self, request):
        loan_xid = request.data.get('loan_xid')
        try:
            mobile_phone_no = request_otp_privy_service(request.user, loan_xid)
        except JuloPrivyLogicException as e:
            return general_error_response(str(e))
        except PrivyApiResponseException as e:
            return general_error_response(str(e))

        return success_response({
            'sent_to': mobile_phone_no
        })


class PrivyConfirmOtpView(PrivyAPIView):
    serializer_class = ConfirmOtpSerializer

    def post(self, request):
        data = request.data
        # validate request data
        otp_data = self.validate_data(self.serializer_class, data)
        otp_code = otp_data['otp_code']
        loan_xid = data['loan_xid']

        try:
            confirm_otp_privy_service(request.user, loan_xid, otp_code)
        except JuloPrivyLogicException as e:
            return general_error_response(str(e))
        except PrivyApiResponseException as e:
            return general_error_response(str(e))

        return success_response(None)


class PrivySignDocumentView(PrivyAPIView):
    def post(self, request):
        data = request.data
        loan_xid = data['loan_xid']
        try:
            sign_document_privy_service(request.user, loan_xid)
        except JuloPrivyLogicException as e:
            return general_error_response(str(e))
        except PrivyApiResponseException as e:
            return general_error_response(str(e))

        return success_response(None)


class PrivyReRegisterView(PrivyAPIView):
    def post(self, request):
        customer = self.request.user.customer
        application = customer.application_set.regular_not_deletes().last()
        if not application:
            raise JuloPrivyException("Application Not found for customer {}".format(customer.id))

        try:
            customer_data = reregister_privy_service(customer, application)
        except JuloPrivyLogicException as e:
            return general_error_response(str(e))
        except PrivyApiResponseException as e:
            return general_error_response(str(e))

        return success_response(customer_data)


class ReuploadPrivyImage(StandardizedExceptionHandlerMixin, CreateAPIView):
    serializer_class = ReuploadPrivyImageSerializer

    def create(self, request, *args, **kwargs):
        image_type = kwargs['image_type']
        if not image_type:
            return general_error_response('Image Type missing')
        data = request.POST.copy()
        application = self.request.user.customer.application_set.last()
        if not application:
            return general_error_response('Application Not Found')
        data['image_source'] = application.id
        image_type = PRIVY_IMAGE_TYPE[image_type]
        data['image_type'] = image_type
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except JuloPrivyLogicException as je:
            return general_error_response(message=str(je))
        headers = self.get_success_headers(serializer.data)
        return created_response(data=serializer.data)

    def perform_create(self, serializer):
        if 'upload' not in self.request.POST or 'data' not in self.request.POST\
                or not self.request.POST['upload'] or not self.request.POST['data']:
            raise JuloPrivyLogicException("No Upload Data")
        reupload_image = serializer.save()
        image_file = self.request.data['upload']
        reupload_image.image.save(self.request.data['data'], image_file)
        upload_image.delay(reupload_image.id)
