import csv
import io
import datetime
import operator
from functools import reduce
from typing import Any, Dict, List, Union

from django.conf import settings
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.db.models import CharField, Q, QuerySet, Value
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.generic import ListView
from scraped_data.forms import ApplicationSearchForm

from juloserver.julo.constants import (
    FeatureNameConst,
    UploadAsyncStateStatus,
    UploadAsyncStateType,
)
from juloserver.julo.models import Agent, Application, FeatureSetting, UploadAsyncState, Loan
from juloserver.partnership.constants import (
    AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE_HEADERS,
    AGENT_ASSISTED_UPLOAD_USER_DATA_HEADERS,
    PRODUCT_FINANCING_LOAN_CREATION_UPLOAD_HEADERS,
    PRODUCT_FINANCING_LOAN_DISBURSEMENT_UPLOAD_HEADERS,
    PRODUCT_FINANCING_LOAN_REPAYMENT_UPLOAD_HEADERS,
    PRODUCT_FINANCING_LENDER_APPROVAL_UPLOAD_HEADERS,
    PartnershipPreCheckFlag,
    ProductFinancingUploadActionType,
    AGENT_ASSISTED_PRE_CHECK_HEADERS,
    AGENT_ASSISTED_FDC_PRE_CHECK_HEADERS,
)
from juloserver.partnership.crm.forms import (
    AgentAssistedUploadForm,
    ProductFinancingUploadFileForm,
    PartnershipLoanCancelFileForm,
)
from juloserver.partnership.models import PartnershipApplicationFlag
from juloserver.partnership.tasks import (
    agent_assisted_process_complete_user_data_update_status_task,
    agent_assisted_process_pre_check_fdc_upload_user_task,
    agent_assisted_process_pre_upload_user_task,
    agent_assisted_scoring_user_data_upload_task,
    product_financing_upload_task,
)
from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_multigroup,
)
from juloserver.utilities.paginator import TimeLimitedPaginator
from juloserver.loan.services.sphp import cancel_loan
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def agent_assisted_pre_check_user_upload(
    request: HttpRequest,
) -> Union[HttpResponse, HttpResponseRedirect]:
    upload_form = AgentAssistedUploadForm(request.POST, request.FILES)
    template_name = 'object/agent_assisted/upload_pre_check_user.html'
    url = reverse('bulk_upload:agent_assisted_pre_check_user_upload')
    if request.method == 'POST':
        if not upload_form.is_valid():
            for key in upload_form.errors:
                messages.error(request, upload_form.errors[key][0] + "\n")
        else:
            agent = Agent.objects.filter(user=request.user).last()
            file_ = upload_form.cleaned_data['file_field']
            partner = upload_form.cleaned_data['partner_field']
            extension = file_.name.split('.')[-1]

            if extension != 'csv':
                msg = 'Please upload the correct file type: CSV'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            decoded_file = file_.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)
            not_exist_headers = []
            for header in AGENT_ASSISTED_PRE_CHECK_HEADERS[:-4]:
                if header not in reader.fieldnames:
                    not_exist_headers.append(header)

            if not_exist_headers:
                msg = 'Missing header: {}'.format(not_exist_headers)
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            in_processed_status = {
                UploadAsyncStateStatus.WAITING,
                UploadAsyncStateStatus.PROCESSING,
            }

            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=UploadAsyncStateType.AGENT_ASSISTED_PRE_CHECK_USER,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                msg = 'Another process in waiting or process please wait and try again later'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            upload_async_state = UploadAsyncState(
                task_type=UploadAsyncStateType.AGENT_ASSISTED_PRE_CHECK_USER,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id
            agent_assisted_process_pre_upload_user_task.delay(upload_async_state_id, partner.id)
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status',
            )

    elif request.method == 'GET':
        upload_form = AgentAssistedUploadForm()
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class AgentAssistedPreCheckUserUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/agent_assisted/upload_pre_check_user_history.html'

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self) -> List:
        return ListView.get_template_names(self)

    def get_queryset(self) -> QuerySet:
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                UploadAsyncStateType.AGENT_ASSISTED_PRE_CHECK_USER,
            ],
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list: Any) -> Any:
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs: Any) -> Dict:
        context = super().get_context_data(**kwargs)

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
def agent_assisted_scoring_user_data_upload(
    request: HttpRequest,
) -> Union[HttpResponse, HttpResponseRedirect]:
    upload_form = AgentAssistedUploadForm(request.POST, request.FILES, hide_partner=True)
    template_name = 'object/agent_assisted/upload_scoring_user_data.html'
    url = reverse('bulk_upload:agent_assisted_scoring_user_data_upload')
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

            decoded_file = file_.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)
            not_exist_headers = []
            for header in AGENT_ASSISTED_UPLOAD_USER_DATA_HEADERS[:-2]:
                if header not in reader.fieldnames:
                    not_exist_headers.append(header)

            if not_exist_headers:
                msg = 'Missing header: {}'.format(not_exist_headers)
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            in_processed_status = {
                UploadAsyncStateStatus.WAITING,
                UploadAsyncStateStatus.PROCESSING,
            }

            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=UploadAsyncStateType.AGENT_ASSISTED_SCORING_USER_DATA,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                msg = 'Another process in waiting or process please wait and try again later'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            upload_async_state = UploadAsyncState(
                task_type=UploadAsyncStateType.AGENT_ASSISTED_SCORING_USER_DATA,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id
            agent_assisted_scoring_user_data_upload_task.delay(upload_async_state_id)
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status',
            )

    elif request.method == 'GET':
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class AgentAssistedScoringUserDataUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/agent_assisted/upload_scoring_user_data_history.html'

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self) -> List:
        return ListView.get_template_names(self)

    def get_queryset(self) -> QuerySet:
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                UploadAsyncStateType.AGENT_ASSISTED_SCORING_USER_DATA,
            ],
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list: Any) -> Any:
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs: Any) -> Dict:
        context = super().get_context_data(**kwargs)

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
def agent_assisted_fdc_pre_check_user_upload(
    request: HttpRequest,
) -> Union[HttpResponse, HttpResponseRedirect]:
    upload_form = AgentAssistedUploadForm(request.POST, request.FILES)
    template_name = 'object/agent_assisted/upload_fdc_pre_check_user.html'
    url = reverse('bulk_upload:agent_assisted_fdc_pre_check_user_upload')
    if request.method == 'POST':
        if not upload_form.is_valid():
            for key in upload_form.errors:
                messages.error(request, upload_form.errors[key][0] + "\n")
        else:
            agent = Agent.objects.filter(user=request.user).last()
            file_ = upload_form.cleaned_data['file_field']
            partner = upload_form.cleaned_data['partner_field']
            extension = file_.name.split('.')[-1]

            if extension != 'csv':
                msg = 'Please upload the correct file type: CSV'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            decoded_file = file_.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)
            not_exist_headers = []
            for header in AGENT_ASSISTED_FDC_PRE_CHECK_HEADERS[:-7]:
                if header not in reader.fieldnames:
                    not_exist_headers.append(header)

            if not_exist_headers:
                msg = 'Missing header: {}'.format(not_exist_headers)
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            in_processed_status = {
                UploadAsyncStateStatus.WAITING,
                UploadAsyncStateStatus.PROCESSING,
            }

            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=UploadAsyncStateType.AGENT_ASSISTED_FDC_PRE_CHECK_USER,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                msg = 'Another process in waiting or process please wait and try again later'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            upload_async_state = UploadAsyncState(
                task_type=UploadAsyncStateType.AGENT_ASSISTED_FDC_PRE_CHECK_USER,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id
            agent_assisted_process_pre_check_fdc_upload_user_task.delay(
                upload_async_state_id, partner.id
            )
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status',
            )

    elif request.method == 'GET':
        upload_form = AgentAssistedUploadForm()
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class AgentAssistedFDCPreCheckUserUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/agent_assisted/upload_fdc_pre_check_user_history.html'

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self) -> List:
        return ListView.get_template_names(self)

    def get_queryset(self) -> QuerySet:
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                UploadAsyncStateType.AGENT_ASSISTED_FDC_PRE_CHECK_USER,
            ],
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list: Any) -> Any:
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs: Any) -> Dict:
        context = super().get_context_data(**kwargs)

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context


class ApplicationData100AgentAssistedListView(ListView):
    model = Application
    paginate_by = 50
    paginator_class = TimeLimitedPaginator
    template_name = 'object/agent_assisted/app_status/list_app_status_100_agent_assisted.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = (
            super(ApplicationData100AgentAssistedListView, self)
            .get_queryset()
            .select_related('product_line', 'application_status', 'customer', 'partner', 'account')
        )
        list_application_flag = list(
            PartnershipApplicationFlag.objects.filter(
                name=PartnershipPreCheckFlag.APPROVED
            ).values_list('application_id', flat=True)
        )
        self.qs = self.qs.filter(
            application_status_id=self.status_code,
            pk__in=list_application_flag,
        ).order_by('-id')
        self.full_data = self.qs
        self.err_message_here = None
        self.tgl_range = None
        self.tgl_start = None
        self.tgl_end = None
        self.status_app = None
        self.search_q = None
        self.sort_q = None
        self.status_now = None

        if self.request.method == 'GET':
            self.tgl_range = self.request.GET.get('datetime_range', None)
            self.status_app = self.request.GET.get('status_app', None)
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.sort_q = self.request.GET.get('sort_q', None)
            self.status_now = self.request.GET.get('status_now', None)

            if self.search_q:
                self.qs = self.full_data

            self.qs = self.qs.annotate(
                crm_url=Value('%s/applications/' % settings.CRM_BASE_URL, output_field=CharField())
            )

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(
                    reduce(
                        operator.or_,
                        [
                            Q(**{('%s__icontains' % 'fullname'): self.search_q}),
                            Q(**{('bank_account_number'): self.search_q}),
                            Q(**{('%s__icontains' % 'ktp'): self.search_q}),
                            Q(**{('%s__icontains' % 'mobile_phone_1'): self.search_q}),
                            Q(**{('%s__icontains' % 'id'): self.search_q}),
                            Q(**{('%s__icontains' % 'email'): self.search_q}),
                            Q(
                                **{
                                    (
                                        '%s__icontains' % 'product_line__product_line_type'
                                    ): self.search_q
                                }
                            ),
                            Q(
                                **{
                                    (
                                        '%s__icontains' % 'product_line__product_line_code'
                                    ): self.search_q
                                }
                            ),
                        ],
                    )
                )

            if self.status_now:
                if self.status_now == 'True':
                    startdate = datetime.datetime.today()
                    startdate = startdate.replace(hour=0, minute=0, second=0)
                    enddate = startdate + datetime.timedelta(days=1)
                    enddate = enddate - datetime.timedelta(seconds=1)
                    self.qs = self.qs.filter(cdate__range=[startdate, enddate])
                else:
                    _date_range = self.tgl_range.split('-')
                    if _date_range[0].strip() != 'Invalid date':
                        _tgl_mulai = datetime.datetime.strptime(
                            _date_range[0].strip(), "%d/%m/%Y %H:%M"
                        )
                        _tgl_end = datetime.datetime.strptime(
                            _date_range[1].strip(), "%d/%m/%Y %H:%M"
                        )
                        if _tgl_end > _tgl_mulai:
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.err_message_here = "Format Tanggal tidak valid"

            if self.sort_q:
                self.qs = self.qs.order_by(self.sort_q)

        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.method == 'GET':
            context['form_search'] = ApplicationSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = ApplicationSearchForm()

        # to check field application.product_line.product_line_code
        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['STATUS'] = "Seluruh Data"
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        context['status_code_now'] = self.status_code
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context

    def get(self, request, *args, **kwargs):
        if self.kwargs['status_code']:
            self.status_code = self.kwargs['status_code']
        else:
            self.status_code = None
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super().render_to_response(context, **response_kwargs)
        return rend_here


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def agent_assisted_complete_data_status_update(
    request: HttpRequest,
) -> Union[HttpResponse, HttpResponseRedirect]:
    upload_form = AgentAssistedUploadForm(request.POST, request.FILES, hide_partner=True)
    template_name = 'object/agent_assisted/upload_complete_data_status_update.html'
    url = reverse('bulk_upload:agent_assisted_upload_complete_user_data_status_update')
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

            decoded_file = file_.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)
            not_exist_headers = []
            for header in AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE_HEADERS[:-2]:
                if header not in reader.fieldnames:
                    not_exist_headers.append(header)

            if not_exist_headers:
                msg = 'Missing header: {}'.format(not_exist_headers)
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            total_rows = len(list(reader))

            is_limit_upload = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.AGENT_ASSISTED_LIMIT_UPLOADER, is_active=True
            ).last()
            if (
                is_limit_upload
                and is_limit_upload.parameters
                and is_limit_upload.parameters.get('max_row')
            ):
                max_rows = is_limit_upload.parameters.get('max_row')
                if total_rows > max_rows:
                    msg = 'Total rows exceeded, cannot more than {} rows'.format(max_rows)
                    messages.error(request, msg)
                    return HttpResponseRedirect(url)

            reader.__init__(decoded_file, delimiter=',')
            in_processed_status = {
                UploadAsyncStateStatus.WAITING,
                UploadAsyncStateStatus.PROCESSING,
            }

            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=UploadAsyncStateType.AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                msg = 'Another process in waiting or process please wait and try again later'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            upload_async_state = UploadAsyncState(
                task_type=UploadAsyncStateType.AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id
            agent_assisted_process_complete_user_data_update_status_task.delay(
                upload_async_state_id
            )
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status',
            )

    elif request.method == 'GET':
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class AgentAssistedCompleteDataStatusUpdateUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/agent_assisted/upload_complete_data_status_update_history.html'

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self) -> List:
        return ListView.get_template_names(self)

    def get_queryset(self) -> QuerySet:
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                UploadAsyncStateType.AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE,
            ],
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list: Any) -> Any:
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs: Any) -> Dict:
        context = super().get_context_data(**kwargs)

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
def product_financing_csv_upload_view(
    request: HttpRequest,
) -> Union[HttpResponse, HttpResponseRedirect]:
    upload_form = ProductFinancingUploadFileForm(request.POST, request.FILES)
    template_name = 'object/product_financing/loan_creation_upload.html'
    url = reverse('bulk_upload:product_financing_csv_upload')
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

            decoded_file = file_.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)

            in_processed_status = {
                UploadAsyncStateStatus.WAITING,
                UploadAsyncStateStatus.PROCESSING,
            }

            if action_key == ProductFinancingUploadActionType.LOAN_CREATION:
                not_exist_headers = []
                for header in PRODUCT_FINANCING_LOAN_CREATION_UPLOAD_HEADERS[:-2]:
                    if header not in reader.fieldnames:
                        not_exist_headers.append(header)

                if not_exist_headers:
                    msg = 'Missing header: {}'.format(not_exist_headers)
                    messages.error(request, msg)
                    return HttpResponseRedirect(url)

                task_type = UploadAsyncStateType.PRODUCT_FINANCING_LOAN_CREATION

            elif action_key == ProductFinancingUploadActionType.LOAN_DISBURSEMENT:
                not_exist_headers = []
                for header in PRODUCT_FINANCING_LOAN_DISBURSEMENT_UPLOAD_HEADERS[:-2]:
                    if header not in reader.fieldnames:
                        not_exist_headers.append(header)

                if not_exist_headers:
                    msg = 'Missing header: {}'.format(not_exist_headers)
                    messages.error(request, msg)
                    return HttpResponseRedirect(url)

                task_type = UploadAsyncStateType.PRODUCT_FINANCING_LOAN_DISBURSEMENT

            elif action_key == ProductFinancingUploadActionType.LOAN_REPAYMENT:
                not_exist_headers = []
                for header in PRODUCT_FINANCING_LOAN_REPAYMENT_UPLOAD_HEADERS[:-2]:
                    if header not in reader.fieldnames:
                        not_exist_headers.append(header)

                if not_exist_headers:
                    msg = 'Missing header: {}'.format(not_exist_headers)
                    messages.error(request, msg)
                    return HttpResponseRedirect(url)

                task_type = UploadAsyncStateType.PRODUCT_FINANCING_LOAN_REPAYMENT
            elif action_key == ProductFinancingUploadActionType.LENDER_APPROVAL:
                not_exist_headers = []
                for header in PRODUCT_FINANCING_LENDER_APPROVAL_UPLOAD_HEADERS[:-1]:
                    if header not in reader.fieldnames:
                        not_exist_headers.append(header)

                if not_exist_headers:
                    msg = 'Missing header: {}'.format(not_exist_headers)
                    messages.error(request, msg)
                    return HttpResponseRedirect(url)

                task_type = UploadAsyncStateType.PRODUCT_FINANCING_LENDER_APPROVAL

            else:
                messages.error(request, 'Action type is not valid')
                return HttpResponseRedirect(url)

            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=task_type,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                msg = 'Another process in waiting or process please wait and try again later'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            upload_async_state = UploadAsyncState(
                task_type=task_type,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id
            product_financing_upload_task.delay(upload_async_state_id, action_key)
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status',
            )

    elif request.method == 'GET':
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class ProductFinancingUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/product_financing/loan_creation_upload_history.html'

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self) -> List:
        return ListView.get_template_names(self)

    def get_queryset(self) -> QuerySet:
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type=UploadAsyncStateType.PRODUCT_FINANCING_LOAN_CREATION,
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list: Any) -> Any:
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs: Any) -> Dict:
        context = super().get_context_data(**kwargs)

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
class ProductFinancingUploadDisbursementHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/product_financing/loan_creation_upload_history.html'

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self) -> List:
        return ListView.get_template_names(self)

    def get_queryset(self) -> QuerySet:
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type=UploadAsyncStateType.PRODUCT_FINANCING_LOAN_DISBURSEMENT,
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list: Any) -> Any:
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs: Any) -> Dict:
        context = super().get_context_data(**kwargs)

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
class ProductFinancingUploadRepaymentHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/product_financing/loan_creation_upload_history.html'

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self) -> List:
        return ListView.get_template_names(self)

    def get_queryset(self) -> QuerySet:
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type=UploadAsyncStateType.PRODUCT_FINANCING_LOAN_REPAYMENT,
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list: Any) -> Any:
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs: Any) -> Dict:
        context = super().get_context_data(**kwargs)

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
class ProductFinancingUploadLenderApprovalHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/product_financing/loan_creation_upload_history.html'

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self) -> List:
        return ListView.get_template_names(self)

    def get_queryset(self) -> QuerySet:
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type=UploadAsyncStateType.PRODUCT_FINANCING_LENDER_APPROVAL,
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list: Any) -> Any:
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs: Any) -> Dict:
        context = super().get_context_data(**kwargs)
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
def partnership_bulk_cancel_loan_view(request):
    template_name = 'object/partnership/loan_cancel_upload.html'
    logs = ""
    upload_form = PartnershipLoanCancelFileForm
    ok_couter = 0
    nok_couter = 0

    def _render():
        """lamda func to reduce code"""
        return render(
            request,
            template_name,
            {
                'form': upload_form,
                'logs': logs,
                'ok': ok_couter,
                'nok': nok_couter,
            },
        )

    if request.method == 'POST':
        upload_form = upload_form(request.POST, request.FILES)
        if not upload_form.is_valid():
            for key in upload_form.errors:
                logs += upload_form.errors[key][0] + "\n"
                logs += "---" * 20 + "\n"
            return _render()

        file_ = upload_form.cleaned_data['file_field']
        partner = str(upload_form.cleaned_data["partner_field"]).lower()
        extension = file_.name.split('.')[-1]

        if partner != PartnerNameConstant.AXIATA_WEB:
            logs = 'Partner tidak sesuai'
            messages.error(request, logs)
            return _render()

        if extension != 'csv':
            logs = 'Ekstensi file tidak sesuai - Mohon upload upload file CSV'
            messages.error(request, logs)
            return _render()

        freader = io.StringIO(file_.read().decode('utf-8'))
        reader = csv.DictReader(freader, delimiter=',')

        if 'loan_xid' not in reader.fieldnames:
            logs = 'Format CSV tidak sesuai - Header yang tidak ada: loan_xid'
            messages.error(request, logs)
            return _render()

        loan_xids = []
        for row in reader:
            if row['loan_xid'].isnumeric():
                loan_xids.append(int(row['loan_xid']))

        loans = Loan.objects.filter(loan_xid__in=loan_xids)

        loan_dicts = {}
        for loan in loans:
            loan_dicts[loan.loan_xid] = loan

        freader.seek(0)
        reader.__init__(freader, delimiter=',')
        for idx, row in enumerate(reader, start=2):
            idx -= 1
            if not row['loan_xid'].isnumeric():
                logs += "loan_xid baris ke-%s - loan_xid tidak numerik\n" % idx
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            loan = loan_dicts.get(int(row['loan_xid']))
            if not loan:
                logs += "loan_xid baris ke-%s - loan tidak ditemukan\n" % idx
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            if loan.product.product_line.product_line_code != ProductLineCodes.AXIATA_WEB:
                logs += "loan_xid baris ke-%s - product_line tidak sesuai\n" % idx
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            if loan.loan_status_id >= LoanStatusCodes.CURRENT:
                logs += "loan_xid baris ke-%s - loan status tidak sesuai\n" % idx
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            try:
                cancel_loan(loan)

            except Exception as e:
                logs += "baris ke-%s terdapat kesalahan - %s\n" % (idx, e)
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            logs += "loan_xid baris ke-%s - berhasil diproses\n" % idx
            logs += "---" * 20 + "\n"
            ok_couter += 1

    return _render()
