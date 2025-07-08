import csv
import io
import logging
import requests
from rest_framework.request import Request
from rest_framework.response import Response

from rest_framework import status
from rest_framework.serializers import ValidationError
from rest_framework.views import APIView

from django.conf import settings
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.db import transaction
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.generic import ListView
from juloserver.ana_api.views import IsAdminUser
from juloserver.employee_financing.decorators import check_is_form_submitted
from juloserver.employee_financing.forms.application_upload import PilotApplicationUploadFileForm
from juloserver.employee_financing.forms.pre_approval_form import PreApprovalUploadFileForm
from juloserver.employee_financing.forms.export_web_form import ExportResponseWebForm
from juloserver.employee_financing.models import (Company,
                                                  EmFinancingWFApplication,
                                                  EmFinancingWFDisbursement)
from juloserver.employee_financing.forms.send_form_url_to_email import SendFormURLToEmailForm
from juloserver.employee_financing.services import (
    run_employee_financing_upload_csv, process_upload_image,
    ef_master_agreement_template
)
from juloserver.employee_financing.serializers import (
    SubmitWFEmployeeFinancingSerializer,
    SubmitWFDisbursementEmployeeFinancingSerializer
)
from juloserver.employee_financing.tasks.application_upload_task import process_ef_upload_task, \
    process_ef_pre_approval_upload_task, send_form_url_to_email_task
from juloserver.julo.constants import (UploadAsyncStateStatus, UploadAsyncStateType)
from juloserver.julo.models import (
    Agent,
    Application,
    UploadAsyncState,
)
from juloserver.partnership.constants import (
    PartnershipImageType,
    HTTPStatusCode,
    EFWebFormType
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.utilities.paginator import TimeLimitedPaginator
from juloserver.portal.object import (julo_login_required, julo_login_required_multigroup, julo_login_required_group)
from juloserver.standardized_api_response.utils import (general_error_response, success_response)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.employee_financing.constants import (
    EMPLOYEE_FINANCING_DISBURSEMENT,
    EMPLOYEE_FINANCING_REPAYMENT,
    IMAGE_EXTENSION_FORMAT,
    ErrorMessageConstEF
)
from juloserver.employee_financing.security import EmployeeFinancingAuthentication
from juloserver.employee_financing.utils import response_template, encode_jwt_token
from juloserver.employee_financing.exceptions import (
    APIError, 
    LockAquisitionError,
    FailedUploadImageException
)
from juloserver.employee_financing.context_managers import lock
from juloserver.partnership.models import PartnershipImage
from juloserver.julo.services2 import encrypt

logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def pilot_application_csv_upload_view(request):
    upload_form = PilotApplicationUploadFileForm(request.POST, request.FILES)
    template_name = 'object/employee_financing/partner_pilot_upload.html'
    url = reverse('employee_financing:pilot_application_csv_upload')
    if request.method == 'POST':
        if not upload_form.is_valid():
            for key in upload_form.errors:
                messages.error(request, upload_form.errors[key][0] + "\n")
        else:
            agent = Agent.objects.filter(user=request.user).last()
            file_ = upload_form.cleaned_data['file_field']
            action_key = upload_form.cleaned_data['action_field']
            extension = file_.name.split('.')[-1]

            if extension != 'csv':
                msg = 'Please upload the correct file type: CSV'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            # default task_type is employee financing register
            task_type = UploadAsyncStateType.EMPLOYEE_FINANCING
            if action_key == EMPLOYEE_FINANCING_DISBURSEMENT:
                task_type = UploadAsyncStateType.EMPLOYEE_FINANCING_DISBURSEMENT
            elif action_key == EMPLOYEE_FINANCING_REPAYMENT:
                task_type = UploadAsyncStateType.EMPLOYEE_FINANCING_REPAYMENT

            upload_async_state = UploadAsyncState(
                task_type=task_type,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(
                upload_async_state.full_upload_name(upload.name), upload
            )
            upload_async_state_id = upload_async_state.id
            process_ef_upload_task.delay(upload_async_state_id, task_type)
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status'
            )

    elif request.method == 'GET':
        upload_form = PilotApplicationUploadFileForm()
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


class UpdateEmployeeFinancingApplicationStatus(APIView):
    permission_classes = [IsAdminUser, ]

    def post(self, request):
        try:
            application_id = request.data['application_id']
            application = Application.objects.get_or_none(pk=application_id)
            if not application:
                return general_error_response(f'application id({application_id}) not found.')

            run_employee_financing_upload_csv(application)
            return success_response()
        except Exception as e:
            return general_error_response(str(e))


@julo_login_required
@julo_login_required_group(JuloUserRoles.PRODUCT_MANAGER)
class EFUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/employee_financing/ef_upload_history.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super(EFUploadHistory, self).get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                UploadAsyncStateType.EMPLOYEE_FINANCING,
                UploadAsyncStateType.EMPLOYEE_FINANCING_DISBURSEMENT,
                UploadAsyncStateType.EMPLOYEE_FINANCING_REPAYMENT,
                UploadAsyncStateType.EMPLOYEE_FINANCING_PRE_APPROVAL
            ]
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(EFUploadHistory, self).get_context_data(**kwargs)

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def pre_approval_view(request):
    upload_form = PreApprovalUploadFileForm(request.POST, request.FILES)
    template_name = 'object/employee_financing/pre_approval_upload.html'
    url = reverse('employee_financing:pre_approval_csv_upload')
    if request.method == 'POST':
        if not upload_form.is_valid():
            for key in upload_form.errors:
                messages.error(request, upload_form.errors[key][0] + "\n")
        else:
            agent = Agent.objects.filter(user=request.user).last()
            file_ = upload_form.cleaned_data['file_field']
            extension = file_.name.split('.')[-1]

            if extension != 'csv':
                msg = 'Please upload the correct file type: CSV'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            upload_async_state = UploadAsyncState(
                task_type=UploadAsyncStateType.EMPLOYEE_FINANCING_PRE_APPROVAL,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(
                upload_async_state.full_upload_name(upload.name), upload
            )
            upload_async_state_id = upload_async_state.id
            process_ef_pre_approval_upload_task.delay(upload_async_state_id)
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status'
            )

    elif request.method == 'GET':
        upload_form = PreApprovalUploadFileForm()
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


class EmployeeFinancingAPIView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = [EmployeeFinancingAuthentication]

    def handle_exception(self, exc: Exception) -> Response:
        """ Override the exception handler to handle APIError first
        """
        if isinstance(exc, APIError):
            response = response_template(success=False, errors=exc.detail,
                                         status=exc.status_code, is_exception=True)
            return response

        if isinstance(exc, ValidationError):
            response_error_details = {}
            for error in exc.detail.items():
                key_error = error[0]
                messages = error[1][0]
                response_error_details[key_error] = messages

            response = response_template(success=False, errors=response_error_details,
                                         status=exc.status_code, is_exception=True)
            return response
        return super().handle_exception(exc)


class EmployeeFinancingAuth(EmployeeFinancingAPIView):

    def get(self, request: Request) -> Response:
        return response_template(data={})


class SubmitWFApplicationEmployeeFinancing(EmployeeFinancingAPIView):
    serializer_class = SubmitWFEmployeeFinancingSerializer
    model_class = EmFinancingWFApplication

    @check_is_form_submitted
    @transaction.atomic
    def post(self, request: Request) -> Response:
        if request.token_data['form_type'] != 'application':
            return response_template(
                errors={'form': 'Token tidak valid'},
                status=status.HTTP_400_BAD_REQUEST,
                success=False
            )

        company = Company.objects.filter(id=request.token_data['company_id']).last()

        is_empty = {None, ''}
        if 'ktp_image' not in request.data or (
                'ktp_image' in request.data and request.data['ktp_image'] in is_empty):
                return response_template(errors={
                    'ktp_image': 'Mohon upload foto ktp terlebih dahulu'
                }, status=status.HTTP_400_BAD_REQUEST, success=False)

        if 'selfie' not in request.data or (
                'selfie' in request.data and request.data['selfie'] in is_empty):
                return response_template(errors={
                    'selfie': 'Mohon upload foto selfie terlebih dahulu'
                }, status=status.HTTP_400_BAD_REQUEST, success=False)

        serializer = self.serializer_class(data=request.data, company=company,
                                           valid_email=request.token_data['email'],
                                           name=request.token_data['name'])

        if serializer.is_valid(raise_exception=True):
            key = 'submit-web-form:{}:{}'.format(request.token_data['email'],
                                                 request.token_data['company_id'])
            try:
                # lock in 10 seconds to prevent multiple spam api hit
                # until process image and store data finish
                with lock(key, ttl=10):

                    # Validate image first, to prevent inconsistent stored data
                    ktp_image = request.data['ktp_image']
                    ktp_image_extension = ktp_image.name.split('.')[-1]
                    if not ktp_image_extension or not ktp_image_extension in IMAGE_EXTENSION_FORMAT:
                        return response_template(errors={
                            'ktp_image': 'KTP file tidak valid'
                        }, status=status.HTTP_400_BAD_REQUEST)

                    selfie_image = request.data['selfie']                  
                    selfie_image_extension = selfie_image.name.split('.')[-1]
                    if not selfie_image_extension or not selfie_image_extension in IMAGE_EXTENSION_FORMAT:
                        return response_template(errors={
                            'selfie': 'Selfie file tidak valid'
                        }, status=status.HTTP_400_BAD_REQUEST)

                    # Save application
                    em_financing_wf_application = serializer.save()

                    # Upload Image KTP
                    process_upload_image(request.data['ktp_image'], PartnershipImageType.KTP_SELF,
                                        em_financing_wf_application.id)

                    # Upload Image Selfie
                    process_upload_image(request.data['selfie'], PartnershipImageType.SELFIE,
                                        em_financing_wf_application.id)

                    # update user access token
                    access_token = request.user_access_token
                    access_token.is_used = True
                    access_token.save(update_fields=['is_used'])

                    return response_template(data={
                        'message': 'Success submit form'
                    })
            except FailedUploadImageException:
                return response_template(errors={
                    'web_form': 'Gagal mengupload file, file tidak valid'
                }, status=status.HTTP_400_BAD_REQUEST, success=False)
            except LockAquisitionError:
                error_message = 'Request berlebih mohon menunggu sebentar, ' \
                    'dan mohon untuk submit dengan data yang benar'
                return response_template(errors={
                    'web_form': error_message
                }, status=status.HTTP_400_BAD_REQUEST, success=False)
            except Exception as e:
                """
                    Using try catch, because this form one way submit
                    So if in the middle of process like submit photo goes wrong
                    We need user to trigger again. Because we dont want to do async task
                    When uploading photo to prevent if photo not submitted properly
                """
                logger.info({
                    'action': "em_financing_web_form_submit",
                    'error': str(e),
                    'email': request.token_data['email'],
                    'company': request.token_data['company_id']
                })
                return response_template(errors={
                    'web_form': 'Terjadi kesalahan, mohon untuk submit kembali application anda'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR, success=False)

        return response_template(errors=serializer.errors)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def send_form_url_to_email(request):
    action_type = {
        'Application': {
            'task_type': UploadAsyncStateType.EMPLOYEE_FINANCING_SEND_APPLICATION_FORM_URL,
        },
        'Disbursement': {
            'task_type': UploadAsyncStateType.EMPLOYEE_FINANCING_SEND_DISBURSEMENT_FORM_URL,
        }
    }
    template_name = 'object/employee_financing/send_form_url_to_email.html'
    url = reverse('employee_financing:send_form_url_to_email')

    upload_form = SendFormURLToEmailForm(request.POST, request.FILES)
    if request.method == 'POST':
        if not upload_form.is_valid():
            for key in upload_form.errors:
                messages.error(request, upload_form.errors[key][0] + "\n")
        else:
            agent = Agent.objects.filter(user=request.user).last()
            file_ = upload_form.cleaned_data['file_field']
            extension = file_.name.split('.')[-1]

            if extension != 'csv':
                msg = 'Please upload the correct file type: CSV'
                messages.error(request, msg)
                return HttpResponseRedirect(url)
            
            action_key = upload_form.cleaned_data['action_field']
            action_object = action_type[action_key]
            upload_async_state = UploadAsyncState(
                task_type=action_object['task_type'],
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(
                upload_async_state.full_upload_name(upload.name), upload
            )
            upload_async_state_id = upload_async_state.id
            send_form_url_to_email_task.delay(
                upload_async_state_id, action_object['task_type'], upload_form.cleaned_data['company']
            )

            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status'
            )

    elif request.method == 'GET':
        upload_form = SendFormURLToEmailForm()
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


class SubmitWFDisbursementEmployeeFinancingView(EmployeeFinancingAPIView):
    serializer_class = SubmitWFDisbursementEmployeeFinancingSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_is_form_submitted
    def post(self, request: Request) -> Response:
        if request.token_data['form_type'] != 'disbursement':
            return response_template(
                errors={'form': 'Token tidak valid'},
                status=status.HTTP_400_BAD_REQUEST,
                success=False
            )

        company = Company.objects.filter(id=request.token_data['company_id']).last()
        serializer = self.serializer_class(data=request.data, company=company)

        if serializer.is_valid(raise_exception=True):
            serializer.save()

            # update user access token
            access_token = request.user_access_token
            access_token.is_used = True
            access_token.save(update_fields=['is_used'])

            return response_template(data={
                'message': 'Success submit form'
            }) 


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def export_response_web_form_view(request):
    template_name = 'object/employee_financing/export_response_web_form.html'
    url = reverse('employee_financing:export_web_form')
    if request.method == 'POST':
        download_form = ExportResponseWebForm(request.POST)
        if not download_form.is_valid():
            for key in download_form.errors:
                messages.error(request, download_form.errors[key][0] + "\n")
        else:
            if download_form.cleaned_data['start_date'] > download_form.cleaned_data['end_date']:
                messages.error(
                    request,
                    'Start date should be less than end date'
                )
            else:
                company = download_form.cleaned_data['company_field']
                web_form_type = download_form.cleaned_data['action_field']
                start_date = download_form.cleaned_data['start_date']
                end_date = download_form.cleaned_data['end_date']
                filter_dict = dict()
                filter_dict['company'] = company
                filter_dict['cdate__date__gte'] = start_date
                filter_dict['cdate__date__lte'] = end_date
                today = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
                if web_form_type == EFWebFormType.APPLICATION:
                    qs = EmFinancingWFApplication.objects.filter(**filter_dict)
                    field_names = [
                        'cdate',
                        'udate',
                        'email',
                        'nik',
                        'phone_number',
                        'place_of_birth',
                        'gender',
                        'marriage_status',
                        'mother_name',
                        'mother_phone_number',
                        'couple_name',
                        'couple_phone_number',
                        'expense_per_month',
                        'expenses_monthly_house_rent',
                        'debt_installments_per_month',
                        'request_loan_amount',
                        'tenor',
                        'KTP',
                        'Selfie'
                    ]
                    csv_filename = f'{company}_application_{today}.csv'
                    if qs:
                        csv_report = io.StringIO()
                        writer = csv.DictWriter(csv_report, fieldnames=field_names)
                        writer.writeheader()
                        field_names = {}
                        for data in qs.iterator():
                            rows = []
                            field_names['cdate'] = timezone.localtime(data.cdate)
                            field_names['udate'] = timezone.localtime(data.udate)
                            field_names['email'] = data.email
                            field_names['nik'] = data.nik
                            field_names['phone_number'] = data.phone_number
                            field_names['place_of_birth'] = data.place_of_birth
                            field_names['gender'] = data.gender
                            field_names['marriage_status'] = data.marriage_status
                            field_names['mother_name'] = data.mother_name
                            field_names['mother_phone_number'] = data.mother_phone_number
                            field_names['couple_name'] = data.couple_name
                            field_names['couple_phone_number'] = data.couple_phone_number
                            field_names['expense_per_month'] = data.expense_per_month
                            field_names['expenses_monthly_house_rent'] = data.expenses_monthly_house_rent
                            field_names['debt_installments_per_month'] = data.debt_installments_per_month
                            field_names['request_loan_amount'] = data.request_loan_amount
                            field_names['tenor'] = data.tenor
                            images = PartnershipImage.objects.filter(ef_image_source=data.id)
                            image_ktp = images.filter(image_type=PartnershipImageType.KTP_SELF).last()
                            image_selfie = images.filter(image_type=PartnershipImageType.SELFIE).last()
                            encrypter = encrypt()
                            if image_ktp:
                                field_names['KTP'] = '{}/api/employee-financing/' \
                                                     'pilot/view-image?image={}'.\
                                    format(settings.BASE_URL,
                                           encrypter.encode_string(image_ktp.url))
                            else:
                                field_names['KTP'] = ''
                            if image_selfie:
                                field_names['Selfie'] = '{}/api/employee-financing/' \
                                                        'pilot/view-image?image={}'. \
                                    format(settings.BASE_URL,
                                           encrypter.encode_string(image_selfie.url))
                            else:
                                field_names['Selfie'] = ''
                            rows.append(field_names)
                            writer.writerows(rows)

                elif web_form_type == EFWebFormType.DISBURSEMENT:
                    qs = EmFinancingWFDisbursement.objects.filter(**filter_dict)
                    field_names = [
                        'cdate',
                        'udate',
                        'nik',
                        'request_loan_amount',
                        'tenor'
                    ]
                    csv_filename = f'{company}_disbursement_{today}.csv'
                    if qs:
                        csv_report = io.StringIO()
                        writer = csv.DictWriter(csv_report, fieldnames=field_names)
                        writer.writeheader()
                        field_names = {}
                        for data in qs.iterator():
                            rows = []
                            field_names['cdate'] = timezone.localtime(data.cdate)
                            field_names['udate'] = timezone.localtime(data.udate)
                            field_names['nik'] = data.nik
                            field_names['request_loan_amount'] = data.request_loan_amount
                            field_names['tenor'] = data.tenor
                            rows.append(field_names)
                            writer.writerows(rows)

                if qs:
                    csv_report.flush()
                    csv_report.seek(0)  # move the pointer to the beginning of the buffer
                    response = HttpResponse(csv_report, content_type='text/csv')
                    response['Content-Disposition'] = 'attachment; filename={}'.format(csv_filename)
                    return response
                else:
                    messages.error(
                        request,
                        'Sorry!! No data exists during this period for {}'.format(web_form_type)
                    )

        return render(request, template_name, {'form': download_form})

    elif request.method == 'GET':
        download_form = ExportResponseWebForm()
        return render(request, template_name, {'form': download_form})

    return HttpResponseRedirect(url)


class ShowImage(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, *args, **kwargs):

        try:
            encrypter = encrypt()
            image_decode_url = encrypter.decode_string(request.GET.get('image', None))
            image = PartnershipImage.objects.filter(url=image_decode_url).last()
            if not image:
                return general_error_response("Sorry! image not found.")
            with requests.get(image.image_url, stream=True) as response_stream:
                return HttpResponse(
                    response_stream.raw.read(),
                    content_type="image/png"
                )
        except Exception as e:
            logger.error({
                "action": "ef_show_image",
                "error": str(e),
                "image": request.GET.get('image')
            })
            return general_error_response(str(e))


class ValidateDOBEmployeeFinancingView(EmployeeFinancingAPIView):
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request: Request) -> Response:
        decode_data = request.token_data
        form_type = decode_data.get('form_type')
        token_dob = decode_data.get('dob')
        application_xid = decode_data.get('application_xid')

        user_dob_request = request.data.get('dob')
        if not user_dob_request:
            return response_template(
                errors={'dob': 'Mohon masukan tanggal lahir anda'},
                status=status.HTTP_400_BAD_REQUEST,
                success=False
            )

        if form_type != 'master_agreement':
            return response_template(
                errors={'form': ErrorMessageConstEF.INVALID_TOKEN},
                status=status.HTTP_400_BAD_REQUEST,
                success=False
            )

        application = Application.objects.filter(application_xid=application_xid).last()
        if not application:
            return response_template(errors={'form': ErrorMessageConstEF.INVALID_TOKEN},
                                     success=False, status=status.HTTP_400_BAD_REQUEST)

        if str(user_dob_request) != token_dob:
            return response_template(
                errors={'dob': 'Tanggal lahir yang anda masukan tidak valid / sesuai'},
                status=status.HTTP_400_BAD_REQUEST,
                success=False
            )

        master_agreement_template = ef_master_agreement_template(application)
        if not master_agreement_template:
            err_msg = "Mohon maaf anda belum bisa melakukan tanda tangan perjanjian, " \
                "mohon untuk menghubungi JULO untuk info lebih lanjut"
            return response_template(errors={'form': err_msg},
                                     success=False, status=status.HTTP_400_BAD_REQUEST)

        data = {
            'username': encode_jwt_token({'dob': token_dob}),
            'master_agreement_template': master_agreement_template
        }

        return response_template(data=data)
