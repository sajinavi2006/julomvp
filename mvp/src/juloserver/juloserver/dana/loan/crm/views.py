import csv
import io
import datetime
import re
import logging

from django.conf import settings
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpRequest
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.views.generic import ListView
from django.db.models import CharField, Value, Q

from juloserver.dana.constants import (
    DanaUploadAsyncStateType,
    DanaProductType,
)
from juloserver.dana.loan.crm.forms import (
    DanaSettlementFileUpload,
    DanaUpdateLoanTransferFundForm,
    DanaDepositDeductionUpload,
    DanaUpdateMaritalStatus,
)
from juloserver.dana.loan.crm.tasks import (
    process_dana_loan_settlement_file_task,
    process_dana_update_pusdafil_data_task,
    process_dana_update_loan_fund_transfer_ts_task,
)
from juloserver.julo.constants import UploadAsyncStateStatus, UploadAsyncStateType
from juloserver.julo.models import Agent, Payment, UploadAsyncState, Application
from juloserver.portal.object import julo_login_required, julo_login_required_multigroup
from juloserver.utilities.paginator import TimeLimitedPaginator
from juloserver.dana.models import DanaPaymentBill
from juloserver.dana.loan.utils import dana_filter_search_field
from juloserver.julo.statuses import (
    PaymentStatusCodes,
    ApplicationStatusCodes,
    JuloOneCodes,
)
from juloserver.julo.product_lines import ProductLineCodes
from scraped_data.forms import ApplicationSearchForm

logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def dana_bulk_update_loan_fund_transfer_ts_view(request: HttpRequest):
    upload_form = DanaUpdateLoanTransferFundForm(request.POST, request.FILES)
    template_name = 'object/dana/dana_bulk_update_loan_fund_transfer_ts.html'
    url = reverse('bulk_upload:dana_bulk_update_transfer_fund_ts')
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

            freader = io.StringIO(file_.read().decode('utf-8'))
            reader = csv.DictReader(freader, delimiter=',')
            header_fieldnames = set(reader.fieldnames)
            product_type = upload_form.cleaned_data['product_type']
            task_type = DanaUploadAsyncStateType.DANA_UPDATE_FUND_TRANSFER_TS

            if product_type == DanaProductType.CASH_LOAN:
                required_field = ["REQUEST_ID", "TRANSACTION_DATE"]
                not_exist_headers = [
                    field for field in required_field if field not in header_fieldnames
                ]
                if not_exist_headers:
                    msg = 'CSV format is not correct. Headers not exists: %s' % not_exist_headers
                    messages.error(request, msg)
                    return HttpResponseRedirect(url)
            elif product_type == DanaProductType.CICIL:
                if "loan_id" not in header_fieldnames:
                    msg = 'CSV format is not correct. Headers not exists: loan_id not_exist_headers'
                    messages.error(request, msg)
                    return HttpResponseRedirect(url)

            in_processed_status = {
                UploadAsyncStateStatus.WAITING,
                UploadAsyncStateStatus.PROCESSING,
            }
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

            product_type = upload_form.cleaned_data['product_type']
            process_dana_update_loan_fund_transfer_ts_task.delay(
                upload_async_state_id, task_type, product_type
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
class dana_bulk_update_loan_fund_transfer_ts_history(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/dana/dana_upload_payment_settlement_file_history.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                DanaUploadAsyncStateType.DANA_UPDATE_FUND_TRANSFER_TS,
            ],
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
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
def dana_upload_payment_settlement_file(request: HttpRequest):
    upload_form = DanaSettlementFileUpload(request.POST, request.FILES, show_product=True)
    template_name = 'object/dana/dana_upload_payment_settlement_file.html'
    url = reverse('bulk_upload:dana_upload_payment_settlement_file')
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

            in_processed_status = {
                UploadAsyncStateStatus.WAITING,
                UploadAsyncStateStatus.PROCESSING,
            }
            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=DanaUploadAsyncStateType.DANA_PAYMENT_SETTTLEMENT,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                msg = 'Another process in waiting or process please wait and try again later'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            upload_async_state = UploadAsyncState(
                task_type=UploadAsyncStateType.DANA_LOAN_SETTLEMENT,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id

            product_type = upload_form.cleaned_data['product_type']
            process_dana_loan_settlement_file_task.delay(
                upload_async_state_id, UploadAsyncStateType.DANA_LOAN_SETTLEMENT, product_type
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
class DanaPaymentSettlementUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/dana/dana_upload_payment_settlement_file_history.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                UploadAsyncStateType.DANA_LOAN_SETTLEMENT,
            ],
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
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
def dana_upload_pusdafil_data(request):
    upload_form = DanaSettlementFileUpload(request.POST, request.FILES)
    template_name = 'object/dana/dana_upload_pusdafil_data.html'
    url = reverse('bulk_upload:dana_upload_pusdafil_data')
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
                task_type=UploadAsyncStateType.DANA_UPDATE_PUSDAFIL_DATA,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id
            process_dana_update_pusdafil_data_task.delay(
                upload_async_state_id, UploadAsyncStateType.DANA_UPDATE_PUSDAFIL_DATA
            )
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status',
            )

    elif request.method == 'GET':
        upload_form = DanaSettlementFileUpload()
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class DanaUploadPusdafilDataHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/dana/dana_upload_pusdafil_data_history.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                UploadAsyncStateType.DANA_UPDATE_PUSDAFIL_DATA,
            ],
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
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
def dana_deposit_deduction_upload(request):
    """
    Uploading CSV to update fund_transfer_ts for Dana PaymentBill
    """
    template_name = 'object/dana/dana_deposit_deduction_upload_file.html'
    logs = ""
    upload_form = DanaDepositDeductionUpload
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
        extension = file_.name.split('.')[-1]

        if extension != 'csv':
            logs = 'Please upload the correct file type: CSV'
            return _render()

        freader = io.StringIO(file_.read().decode('utf-8'))
        reader = csv.DictReader(freader, delimiter=',')
        if "payment_id" not in reader.fieldnames:
            logs = "'CSV format is not correct. payment_id not exists in header"
            return _render()
        if "deduction_date" not in reader.fieldnames:
            logs = "'CSV format is not correct. deduction_date not exists in header"
            return _render()

        payment_ids = set()
        for row in reader:
            if row['payment_id'] and row['payment_id'].isnumeric():
                payment_ids.add(row["payment_id"])

        payments = Payment.objects.filter(
            id__in=payment_ids, payment_status__gte=PaymentStatusCodes.PAYMENT_30DPD
        )
        payment_ids = payments.values_list('id', flat=True)
        dana_bill_payments = DanaPaymentBill.objects.filter(
            payment_id__in=set(payment_ids),
        ).only("id", "payment_id", "deposit_deducted", "deducted_date")
        dana_bill_payment_dicts = dict()
        for dana_bill_payment in dana_bill_payments.iterator():
            dana_bill_payment_dicts[dana_bill_payment.payment.id] = dana_bill_payment

        freader.seek(0)
        reader.__init__(freader, delimiter=',')
        for idx, row in enumerate(reader, start=2):
            if not row['payment_id'] and not row['deduction_date']:
                logs += "Row num-%s - payment_id & deduction_date should not be empty\n" % idx
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if not row['payment_id'].isnumeric():
                logs += "Row num-%s - payment_id is not a valid integer\n" % idx
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            date_string = row['deduction_date']
            date_format = '%d/%m/%Y'
            try:
                deduction_date = datetime.datetime.strptime(date_string, date_format).strftime(
                    "%Y-%m-%d"
                )
            except ValueError:
                logs += "Row num-%s - Incorrect data format, should be DD/MM/YYYY\n" % idx
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            dana_bill_payment = dana_bill_payment_dicts.get(int(row["payment_id"]))
            if not dana_bill_payment:
                logs += "PAYMENT ID %s - not found \n" % row["payment_id"]
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if not dana_bill_payment.deducted_date:
                dana_bill_payment.deposit_deducted = True
                dana_bill_payment.deducted_date = deduction_date
                dana_bill_payment.save(update_fields=['deposit_deducted', 'deducted_date'])

            logs += (
                "PAYMENT ID %s - successfully updated deposit_deducted  & deducted_date\n"
                % row["payment_id"]
            )
            logs += "---" * 20 + "\n"
            ok_couter += 1

        freader.close()
        return _render()
    else:
        return _render()


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class ApplicationDanaListMaritalStatusView(ListView):
    model = Application
    paginate_by = 50
    paginator_class = TimeLimitedPaginator
    template_name = 'object/dana/dana_list_marital_status.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()

        self.qs = self.qs.filter(product_line_id=ProductLineCodes.DANA).order_by('-id')
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
                # checking full text search or not
                is_matched = re.search("^%(.*)%$", self.search_q)
                search_type = 'iexact'
                if is_matched:
                    self.search_q = is_matched.group(1)
                    search_type = 'icontains'

                field, keyword = dana_filter_search_field(self.search_q)
                search_type = 'in' if field in {'product_line_id', 'account_id'} else search_type
                self.qs = self.qs.filter(Q(**{('%s__%s' % (field, search_type)): keyword}))

            if self.status_app:
                if int(self.status_app) <= ApplicationStatusCodes.LOC_APPROVED:
                    self.qs = self.qs.filter(application_status_id=self.status_app)
                elif int(self.status_app) in JuloOneCodes.fraud_check():
                    self.qs = self.qs.filter(account__status_id=self.status_app)

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

        return self.qs.select_related('product_line', 'partner', 'account')

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(ApplicationDanaListMaritalStatusView, self).get_context_data(**kwargs)

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
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context

    def get(self, request, *args, **kwargs):
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super(ApplicationDanaListMaritalStatusView, self).render_to_response(
            context, **response_kwargs
        )
        return rend_here


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def dana_update_marital_status(request, pk):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    app_obj = get_object_or_404(Application, id=pk)
    if not hasattr(app_obj, 'dana_customer_data'):
        return render(request, 'covid_refinancing/404.html')

    template_name = ('object/dana/dana_update_marital_status_detail.html',)

    if request.method == 'POST':
        form = DanaUpdateMaritalStatus(request.POST)
        if form.is_valid():
            logger.info(
                {
                    'form': form,
                }
            )
            marital_status = form.cleaned_data['marital_status']
            app_obj.update_safely(marital_status=marital_status)
            url = reverse('app_status:dana_list_marital_status')
            return redirect(url)
    else:
        form = DanaUpdateMaritalStatus(initial={'marital_status': app_obj.marital_status})

    context = {
        'form': form,
        'app_obj': app_obj,
        'datetime_now': timezone.now(),
        'number_seq_list': (
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            53,
        ),
    }
    return render(request, template_name, context)
