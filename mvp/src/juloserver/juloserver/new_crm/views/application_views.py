import logging

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from juloserver.julo.banks import BankManager
from juloserver.julo.exceptions import JuloInvalidStatusChange
from juloserver.julo.models import (
    Application,
    ApplicationNote,
    Image,
    SecurityNote,
    SkiptraceHistory,
)
from juloserver.julo.services import process_application_status_change
from juloserver.new_crm.exceptions import NewCrmException
from juloserver.new_crm.serializers import (
    AppAppSecurityTabFetchSerializer,
    AppDetailSerializer,
    AppDetailUpdateHistorySerializer,
    AppFinanceSerializer,
    AppNoteSerializer,
    AppSecurityTabSerializer,
    AppStatusChangeReadSerializer,
    AppStatusChangeWriteSerializer,
    AppStatusCheckListCommentsSerializer,
    AppStatusCheckListSerializer,
    BasicAppDetailSerializer,
    EmailAndSmsHistorySerializer,
    SkiptraceHistorySerializer,
    SkiptraceResultChoiceSerializer,
    SkiptraceSerializer,
)
from juloserver.new_crm.services.application_services import (
    create_application_checklist_comment_data,
    filter_app_statuses_crm,
    get_application_scrape_data,
    get_application_skiptrace_list,
    get_application_skiptrace_result_list,
    get_application_status_histories,
    get_image_list,
)
from juloserver.new_crm.tasks import upload_image
from juloserver.new_crm.utils import crm_permission, crm_permission_exclude
from juloserver.portal.object.app_status.utils import get_list_email_history
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.portal.object.loan_app.forms import MultiImageUploadForm
from juloserver.portal.object.loan_app.services import ImageListIndex
from juloserver.portal.object.loan_app.utils import get_app_detail_list_history
from juloserver.standardized_api_response.mixin import (
    StrictStandardizedExceptionHandlerMixin,
)
from juloserver.standardized_api_response.utils import (
    created_response,
    general_error_response,
    not_found_response,
    success_response,
)

logger = logging.getLogger(__name__)


class BasicAppDetail(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]
    http_method_names = ['get']

    def get_object(self, pk):
        return Application.objects.filter(pk=pk).last()

    def get(self, request, application_id):
        try:
            app = get_object_or_404(Application, pk=application_id)
            serializer = BasicAppDetailSerializer(instance=app, context={'user': request.user})
            return success_response(data=serializer.data)
        except Http404:
            return not_found_response("Application not found")


class AppDetail(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]
    http_method_names = ['get', 'post']

    def get(self, request, application_id: int):
        try:
            application = get_object_or_404(Application, pk=application_id)
            serializer = AppDetailSerializer(instance=application, context=self.request)
            return success_response(data=serializer.data)
        except Http404:
            return not_found_response("Application not found")

    def post(self, request, application_id: int):
        try:
            app = get_object_or_404(Application, pk=application_id)
            serializer = AppDetailSerializer(instance=app, data=request.data, partial=True,
                                             context=self.request)

            if serializer.is_valid(raise_exception=True):
                serializer.save()

            return success_response({
                'status': 'success',
                'message': 'successfully update application detail'
            })
        except Http404:
            return not_found_response('Application not found')
        except ValidationError as e:
            if not serializer.errors:
                return general_error_response('Bad Parameter(s)', data=e.detail)
            else:
                return general_error_response('Bad Parameter(s)', data=serializer.errors)


class AppStatusChange(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]
    http_method_names = ['get', 'post']

    def get(self, request, application_id):
        try:
            app = get_object_or_404(Application, pk=application_id)
        except Http404:
            return not_found_response("Application not found")
        statuses, _ = filter_app_statuses_crm(
            status_code=app.application_status,
            application=app,
        )
        serializer = AppStatusChangeReadSerializer(instance=statuses, many=True)
        return success_response(data=serializer.data)

    def post(self, request, application_id):
        serializer = AppStatusChangeWriteSerializer(data=request.data)
        try:
            if serializer.is_valid():
                result = process_application_status_change(
                    application_id,
                    new_status_code=serializer.validated_data['status'],
                    change_reason=serializer.validated_data['change_reason'],
                )
                if not result:
                    raise NewCrmException("Failed to change app status")

            else:
                return general_error_response("Bad params", data=serializer.errors)

        except (JuloInvalidStatusChange, NewCrmException) as e :
            return general_error_response(f"{str(e)}")

        return success_response()


class AppMultiImageUpload(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]
    http_method_names = ['post']

    def post(self, request, application_id):
        try:
            app_object = get_object_or_404(Application, pk=application_id)
        except Http404:
            return not_found_response("Application not found")
        form = MultiImageUploadForm(request.POST, request.FILES)
        if form.is_valid():
            attachments = form.cleaned_data['attachments']

            arr_image_type = []
            for index_key in range(10):
                key_image = "image_type_%d" % (index_key+1)
                arr_image_type.append(form.cleaned_data[key_image])
            arr_image_type = ImageListIndex(arr_image_type).output()

            index = 0
            for attachment in attachments:
                image_type_selected = arr_image_type[index]

                obj_image = Image()
                obj_image.image_source = app_object.id
                obj_image.image_type = '%s_%s' % (image_type_selected, 'ops')
                obj_image.save()
                obj_image.image.save(obj_image.full_image_name(attachment.name), attachment)

                upload_image.apply_async((obj_image.id,), countdown=3)
                index += 1

            return success_response({
                'status': 'success',
                'message': 'successfully upload images'
            })

        else:
            return general_error_response(
                'Upload File tidak boleh kosong, '
                ' Upload dokumen/gambar hanya 10 File dan maxSize 10MB per-file!!!'
            )


class AppStatusAppHistory(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]

    def get(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
        except Http404:
            return not_found_response("Application not found")
        data = get_application_status_histories(application)

        return success_response(data=data)


class AppNote(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]
    serializer_class = AppNoteSerializer

    def post(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
        except Http404:
            return not_found_response("Application not found")
        note_text = request.data.get('note_text')
        if not note_text:
            return general_error_response('Bad params', "field 'note_text' is required")
        user_id = request.user.id
        app_note = ApplicationNote.objects.create(
            application_id=application.id,
            note_text=note_text,
            added_by_id=user_id,
        )
        serializer = self.serializer_class(app_note)
        return success_response(data=serializer.data)


class AppStatusImageList(APIView):
    """View to list the documents based on application."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]

    def get(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
            image_list = get_image_list(application)
            return success_response(data=image_list)
        except Http404:
            return not_found_response("Application not found")


class AppSecurityTab(APIView):
    """View to fetch the details for application security tab."""

    authentication_classes = [SessionAuthentication]
    permission_list = [
        JuloUserRoles.BO_FULL,
        JuloUserRoles.ADMIN_FULL,
        JuloUserRoles.CS_TEAM_LEADER,
        JuloUserRoles.BO_SD_VERIFIER]
    permission_classes = [crm_permission(permission_list)]
    serializer_class = AppSecurityTabSerializer

    def get(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
            serializer = AppSecurityTabSerializer(application, context={'user':request.user})
            return success_response(data=serializer.data)
        except Http404:
            return not_found_response("Application not found")

    def post(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
            serializer = AppAppSecurityTabFetchSerializer(data=request.data)
            if serializer.is_valid(raise_exception=True):
                security_note = serializer.validated_data.get('security_note')
                SecurityNote.objects.create(
                    customer=application.customer,
                    note_text=security_note,
                    added_by=request.user)
            return created_response("Security Note has been created")
        except Http404:
            return not_found_response("Application not found")


class AppDetailUpdateHistory(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]
    serializer_class = AppDetailUpdateHistorySerializer

    def get(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
            data = get_app_detail_list_history(application)
            serializer = self.serializer_class(data, many=True)
            return success_response(data=serializer.data)
        except Http404:
            return not_found_response("Application not found")


class AppScrapeDataView(StrictStandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]

    def get(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
            sd_data = get_application_scrape_data(application)
            return success_response(data=sd_data)
        except Http404:
            return not_found_response("Application not found")


class AppStatusSkiptraceHistory(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]
    serializer_class = SkiptraceHistorySerializer

    def get(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
            skiptrace_history_queryset = SkiptraceHistory.objects.filter(
                application=application).order_by('-cdate')[:100]
            skiptrace_history_serializer = SkiptraceHistorySerializer(
                skiptrace_history_queryset, many=True)
            return success_response(data=skiptrace_history_serializer.data)
        except Http404:
            return not_found_response('Application not found')


class EmailAndSmsHistory(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]
    serializer_class = EmailAndSmsHistorySerializer

    def get(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
            email_and_sms_list = get_list_email_history(application)
            serializer = self.serializer_class(email_and_sms_list, many=True)
            return success_response(data=serializer.data)
        except Http404:
            return not_found_response('Application not found')


class AppFinanceView(StrictStandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission([JuloUserRoles.BO_SD_VERIFIER])]
    serializer_class = AppFinanceSerializer

    def get(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
            serializer = self.serializer_class(application)
            return success_response(data=serializer.data)
        except Http404:
            return not_found_response("Application not found")


class AppSkiptrace(StrictStandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [crm_permission_exclude([JuloUserRoles.BO_CREDIT_ANALYST])]
    serializer_class = SkiptraceSerializer

    def get(self, request, application_id):
        try:
            application = get_object_or_404(Application, pk=application_id)
            skiptrace_list = get_application_skiptrace_list(application)
            skiptrace_serializer = self.serializer_class(skiptrace_list, many=True)

            skiptrace_result_list = get_application_skiptrace_result_list()
            skiptrace_result_serializer = SkiptraceResultChoiceSerializer(
                skiptrace_result_list, many=True
            )
            resp_data = {
                "skiptrace": skiptrace_serializer.data,
                "wa_template": "",
                "skiptrace_result_option": skiptrace_result_serializer.data

            }
            return success_response(data=resp_data)
        except Http404:
            return not_found_response('Application is not found.')


class BankListView(APIView):
    """
    API for returning valid bank list in value,text pairs on request. Meant for FE dropdown.
    """
    authentication_classes = [SessionAuthentication]
    permission_classes = []
    serializer_class = SkiptraceSerializer

    def get(self, request):
        try:
            bank_name_options = []
            bank_list = BankManager.get_bank_names()
            for bank_name_choice in bank_list:
                bank_name_options.append({
                    'value': bank_name_choice,
                    'text': bank_name_choice
                })

            return success_response(data=bank_name_options)
        except Http404:
            return not_found_response('Bank list not found.')
