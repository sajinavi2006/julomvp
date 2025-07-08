import requests

from django.http import HttpResponse
from dateutil.relativedelta import relativedelta
from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.conf import settings
from django.db import transaction
from django.http import StreamingHttpResponse
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from rest_framework.views import APIView

from juloserver.api_token.authentication import (
    ExpiryTokenAuthentication,
    generate_new_token,
    get_expiry_token,
)
from juloserver.api_token.models import ExpiryToken as Token
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Customer, Loan
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.merchant_financing.web_portal.constants import (
    WebPortalErrorMessage,
)
from juloserver.merchant_financing.web_portal.services import (
    web_portal_send_sms_otp,
    web_portal_verify_sms_otp,
    process_upload_image,
    get_web_portal_agreement,
)
from juloserver.merchant_financing.web_portal.serializers import (
    WebPortalRegisterSerializer,
    ImageUploadSerializer,
    OTPRequestSerializer,
    OTPValidateSerializer,
    ChangeLoanStatusSerializer
)
from juloserver.merchant_financing.web_portal.utils import (
    error_response_web_portal,
    success_response_web_portal,
)
from juloserver.partnership.constants import(
    ErrorMessageConst,
    HTTPStatusCode,
    PartnershipImageType,
    AgreementStatus,
)
from juloserver.partnership.utils import generate_pii_filter_query_partnership
from juloserver.portal.object.bulk_upload.serializers import (
    AxiataTemporaryDataSerializer,
)
from juloserver.sdk.models import AxiataTemporaryData
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
)
from juloserver.julo.utils import get_file_from_oss

from juloserver.partnership.models import PartnershipImage
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.merchant_financing.web_portal.services import hold_loan_status_to_211
from juloserver.loan.services.sphp import cancel_loan
sentry_client = get_julo_sentry_client()


class WebPortalAPIView(StandardizedExceptionHandlerMixin, APIView):
    """ Customize APIView FOR MERCHANT FINANCING  WEB PORTAL """
    authentication_classes = [ExpiryTokenAuthentication]
    
    def handle_exception(self, exc):
        get_token = self.request.META.get('HTTP_AUTHORIZATION', b'')
        key = get_token.split()
        if len(key) != 2:
            error = { 'token' : ['Token Not Found']}
            return error_response_web_portal(
                    HTTP_400_BAD_REQUEST,
                    WebPortalErrorMessage.INVALID_AUTH,
                    error)
        try:
            token = get_expiry_token(key[1], Token)
        except Token.DoesNotExist:
            error = { 'token' : ['Invalid token']}
            return error_response_web_portal(
                    HTTP_400_BAD_REQUEST,
                    WebPortalErrorMessage.INVALID_AUTH,
                    error)
        if not token.user.is_active:
            error = { 'token' : ['User inactive or deleted']}
            return error_response_web_portal(
                    HTTP_400_BAD_REQUEST,
                    WebPortalErrorMessage.INVALID_AUTH,
                    error)
            
        return super().handle_exception(exc)


class WebPortalListAPIView(StandardizedExceptionHandlerMixin, ListAPIView):
    """ Customize ListAPIView FOR MERCHANT FINANCING WEB PORTAL """
    authentication_classes = [ExpiryTokenAuthentication]

    def handle_exception(self, exc):
        get_token = self.request.META.get('HTTP_AUTHORIZATION', b'')
        key = get_token.split()
        if len(key) != 2:
            error = { 'token' : ['Token Not Found']}
            return error_response_web_portal(
                    HTTP_400_BAD_REQUEST,
                    WebPortalErrorMessage.INVALID_AUTH,
                    error)
        try:
            token = get_expiry_token(key[1], Token)
        except Token.DoesNotExist:
            error = { 'token' : ['Invalid token']}
            return error_response_web_portal(
                    HTTP_400_BAD_REQUEST,
                    WebPortalErrorMessage.INVALID_AUTH,
                    error)
        if not token.user.is_active:
            error = { 'token' : ['User inactive or deleted']}
            return error_response_web_portal(
                    HTTP_400_BAD_REQUEST,
                    WebPortalErrorMessage.INVALID_AUTH,
                    error)
        return super().handle_exception(exc)


class WebPortalRegister(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = WebPortalRegisterSerializer

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)

        data = {}
        msg = {}

        if not serializer.is_valid():
            return error_response_web_portal(message=WebPortalErrorMessage.INVALID_REGISTER, errors=serializer.errors)
        
        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        pii_nik_filter_dict = generate_pii_filter_query_partnership(Customer, {'nik': username})
        check_customer = Customer.objects.filter(**pii_nik_filter_dict).first()

        if check_customer:
            # LOGIN
            user = check_customer.user
            is_password_correct = user.check_password(password)
            if not is_password_correct:
                errors = {
                    "username": ['NIK atau password Tidak Valid'],
                    "password": ['NIK atau password Tidak Valid']
                }
                return error_response_web_portal(message=WebPortalErrorMessage.INVALID_LOGIN, errors=errors)
            generate_new_token(user)
            token = user.auth_expiry_token.key
            data = {
                'token': token
            }
            msg = {
                'status' : WebPortalErrorMessage.SUCCESSFUL_LOGIN
            }
        
        elif not check_customer:
            # REGISTER
            if len(password) < 6:
                errors = {"password": ['Password Kurang Dari 6 Karakter']}
                return error_response_web_portal(message=WebPortalErrorMessage.INVALID_LOGIN, errors=errors)

            with transaction.atomic(): 
                try:
                    user = User(username=username)
                    user.set_password(password)
                    user.save()
                    expiry_token = user.auth_expiry_token
                    expiry_token.update_safely(is_active=True)
                    customer, customer_created = Customer.objects.get_or_create(
                        user=user,
                        nik=username,
                    )
                except Exception:
                    sentry_client.captureException()
                    return error_response_web_portal(
                        status=HTTP_500_INTERNAL_SERVER_ERROR, 
                        message=WebPortalErrorMessage.INVALID_REGISTER
                    )

                token = user.auth_expiry_token.key
            
                data = {
                    'token': token
                }
                msg = {
                    'status' : WebPortalErrorMessage.SUCCESSFUL_REGISTER
                }
        return success_response_web_portal(data=data, meta=msg)


class WebPortalLogout(WebPortalAPIView):

    def post(self, request: Request) -> Response:
        generate_new_token(request.user.id)
        logout(request)
        return Response(status=HTTP_204_NO_CONTENT)


class ListApplications(StandardizedExceptionHandlerMixin, APIView):

    def get(self, request: Request) -> Response:
        return success_response("Hello World")


class AxiataTemporaryDataSubmitView(WebPortalAPIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY
    serializer_class = AxiataTemporaryDataSerializer

    def patch(self, request, axiata_temporary_data_id):
        axiata_temporary_data = AxiataTemporaryData.objects.filter(
            id=axiata_temporary_data_id
        ).last()
        if not axiata_temporary_data:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': "Axiata Temporary Data not found", 'meta': {}, 'errors': {}}
            )

        serializer = self.serializer_class(axiata_temporary_data, data=self.request.data)
        if serializer.is_valid():
            if self.request.data.get("loan_duration"):
                duration = self.request.data.get("loan_duration")
            else:
                duration = axiata_temporary_data.loan_duration

            if self.request.data.get("loan_duration_unit"):
                duration_unit = self.request.data.get("loan_duration_unit")
            else:
                duration_unit = axiata_temporary_data.loan_duration_unit

            if duration_unit.lower() in {"week", "weeks", "minggu"}:
                first_payment_date = axiata_temporary_data.cdate + relativedelta(weeks=duration)
            elif duration_unit.lower() in {"month", "months", "bulan"}:
                first_payment_date = axiata_temporary_data.cdate + relativedelta(months=duration)
            else:
                first_payment_date = axiata_temporary_data.cdate + relativedelta(days=duration)

            serializer.validated_data["first_payment_date"] = first_payment_date.date()
            serializer.validated_data["is_submitted"] = True
            serializer.save()
            return Response(
                status=HTTP_200_OK,
                data={
                    'data': serializer.data,
                    'meta': {},
                    'errors': {}
                }
            )

        else:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': str(serializer.errors), 'meta': {}, 'errors': {}}
            )


class UploadDocumentData(WebPortalAPIView):
    serializer_class = ImageUploadSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request: Request, axiata_temporary_data_id) -> Response:
        
        axiata_temporary_data = AxiataTemporaryData.objects.filter(
            id=axiata_temporary_data_id
        ).last()
        if not axiata_temporary_data:
            return error_response_web_portal(message='Axiata Temporary Data not found')

        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    'message': "",
                    'meta': {},
                    'errors': serializer.errors
                }
            )

        image_file = serializer.validated_data['image_file']
        image_type = serializer.validated_data['image_type']

        if image_type not in [PartnershipImageType.KTP_SELF, PartnershipImageType.SELFIE]:
            return error_response_web_portal(message='Document Type does not match')

        partnership_image = process_upload_image(request.data, axiata_temporary_data)

        data = {
            'axiata_temporary_data_id' : axiata_temporary_data.id,
            'partnership_image_id' : partnership_image.id,
        }
        return success_response_web_portal(data=data, meta='Success Upload dokumen')


class DownloadDocumentData(WebPortalAPIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get(self, request: Request, *args, **kwargs) -> Response:
        if not self.kwargs['axiata_temporary_data_id']:
            return error_response_web_portal(message='axiata_temporary_data_id not found')

        if not self.kwargs['partnership_image_id']:
            return error_response_web_portal(message='partnership_image_id not found')
        
        axiata_temporary_data_id = self.kwargs['axiata_temporary_data_id']
        partnership_image_id = self.kwargs['partnership_image_id']

        axiata_temporary_data = AxiataTemporaryData.objects.filter(
            id=axiata_temporary_data_id
        ).last()

        if not axiata_temporary_data:
            return error_response_web_portal(message='Axiata Temporary Data not found')
        
        partnership_image = PartnershipImage.objects.filter(pk=partnership_image_id, application_image_source=axiata_temporary_data_id).last()

        proof_file_stream = get_file_from_oss(settings.OSS_MEDIA_BUCKET, partnership_image.url)
        content_type = 'image/jpeg'
        file_name = partnership_image.url.split('/')[2]

        response = StreamingHttpResponse(
            streaming_content=proof_file_stream, content_type=content_type)
        response['Content-Disposition'] = 'attachment; filename="{0}"'.format(file_name)

        return response
class AxiataCreateTemporaryDataView(WebPortalAPIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request):
        axiata_temporary_data = AxiataTemporaryData.objects.create()
        data = {'axiata_temporary_data_id': axiata_temporary_data.id}
        return success_response_web_portal(data=data)


class WebPortalOTPRequest(WebPortalAPIView):
    serializer_class = OTPRequestSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response_web_portal(message='Failed to request OTP', errors=serializer.errors)

        try:
            success_send_otp = web_portal_send_sms_otp(serializer.data.get('phone_number'))
            return success_response_web_portal(data=success_send_otp, meta='Success to request OTP')
        except Exception:
            sentry_client.captureException()

            error = {'error': ['Failed to request OTP']}
            return error_response_web_portal(
                HTTP_500_INTERNAL_SERVER_ERROR,
                'Failed to request OTP need please try again',
                error
            )


class ShowImage(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, *args, **kwargs):
        try:
            image_url = request.GET.get('image', None)
            image = PartnershipImage.objects.filter(url=image_url).last()
            if not image:
                error = {'error': ['image not exists']}
                return error_response_web_portal(
                    HTTP_400_BAD_REQUEST,
                    'Sorry! image not found.',
                    error
                )
            with requests.get(image.image_url, stream=True) as response_stream:
                return HttpResponse(
                    response_stream.raw.read(),
                    content_type="image/png"
                )
        except Exception:
            sentry_client.captureException()

            error = {'error': ['Failed to request URL']}
            return error_response_web_portal(
                HTTP_500_INTERNAL_SERVER_ERROR,
                'Sorry! some errors occurred',
                error
            )


class WebPortalVerifyOtp(WebPortalAPIView):
    serializer_class = OTPValidateSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response_web_portal(message='Failed to validate OTP',
                                             errors=serializer.errors)
        data = serializer.data
        try:
            success_send_otp = web_portal_verify_sms_otp(data)
            if not success_send_otp['success']:
                msg = success_send_otp['content']['message']
                error = {'error': [msg]}
                return error_response_web_portal(
                    HTTP_400_BAD_REQUEST,
                    "Failed to validate OTP",
                    error
                )
            return success_response_web_portal(data=success_send_otp, meta='Success to validate OTP')
        except Exception:
            sentry_client.captureException()
            msg = 'Sorry! some errors occurred'
            error = {'error': [msg]}
            return error_response_web_portal(
                HTTP_500_INTERNAL_SERVER_ERROR,
                msg,
                error
            )


class WebPortalAgreement(WebPortalAPIView):

    def get(self, request, *args, **kwargs):
        loan_xid = self.kwargs['loan_xid']
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)

        if not loan:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        application = loan.application
        if not application:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        if application.status != ApplicationStatusCodes.FUND_DISBURSAL_ONGOING:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        text_agreement = get_web_portal_agreement(loan, show_provider_signature=False)
        html_start = """
        <html><head><title></title>
        <link href="https://fonts.googleapis.com/css?family=Pinyon Script" rel="stylesheet">
        </head><body>
        """
        html_end = '</body></html>'

        text_response = html_start + text_agreement + html_end
        return success_response(data=text_response)


class WebPortalLoanStatusView(WebPortalAPIView):
    serializer_class = ChangeLoanStatusSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return error_response_web_portal(message='Failed to change status', errors=serializer.errors)

        loan_xid = self.kwargs['loan_xid']
        data = request.data
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        valid_loan_statuses = {LoanStatusCodes.DRAFT,
                               LoanStatusCodes.INACTIVE}
        if not loan or loan.status not in valid_loan_statuses:
            msg = ErrorMessageConst.LOAN_NOT_FOUND
            error = {'error': [msg]}
            return error_response_web_portal(
                HTTP_400_BAD_REQUEST,
                msg,
                error
            )

        if data['status'] == AgreementStatus.SIGN and loan.status == LoanStatusCodes.INACTIVE:
            status_code = hold_loan_status_to_211(loan, "JULO")
        elif data['status'] == AgreementStatus.CANCEL and \
                loan.status < LoanStatusCodes.FUND_DISBURSAL_ONGOING:
            status_code = cancel_loan(loan)
        else:
            msg = "Invalid Status Request or invalid Status change"
            error = {'error': [msg]}
            return error_response_web_portal(
                HTTP_400_BAD_REQUEST,
                msg,
                error
            )

        msg = 'Status changed successfully'
        data = {
            "success": True,
            "content": {
                "status": status_code,
                "loan_xid": loan_xid,
                "message": msg,
            },
        }
        return success_response_web_portal(data=data, meta='Status changed successfully')
