import datetime
import tempfile
import os
import logging

from django.conf import settings
from django.views.decorators.http import require_http_methods
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import ListView
from django.contrib import messages
from django.shortcuts import (
    redirect,
    render,
    get_object_or_404,
)
from django.core.urlresolvers import reverse

from juloserver.balance_consolidation.constants import HTTPMethod
from juloserver.utilities.paginator import TimeLimitedPaginator

from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_multigroup,
)
from juloserver.channeling_loan.forms import (
    ChannelingLoanForm,
    UploadFileForm,
    ARSwitcherForm,
    LenderOspTransactionForm,
    LenderOspAccountForm,
    WriteOffLoanForm,
)
from juloserver.channeling_loan.services.general_services import (
    get_channeling_loan_configuration,
    send_notification_to_slack,
)
from juloserver.channeling_loan.services.views_services import (
    construct_bjb_response,
    construct_fama_repayment_response,
    construct_fama_reconciliation_response,
    execute_withdraw_batch_service,
    execute_repayment_service,
    get_approval_response,
    process_permata_early_payoff_request,
    construct_smf_response,
)
from juloserver.channeling_loan.services.bni_services import BNIRepaymentServices
from juloserver.channeling_loan.services.dbs_services import (
    DBSRepaymentServices,
    DBSReconciliationServices,
)
from juloserver.channeling_loan.services.permata_services import (
    construct_permata_response,
)

from juloserver.channeling_loan.models import (
    ChannelingLoanStatus,
    LenderOspTransaction,
    LenderLoanLedger,
    LenderOspAccount,
    ARSwitchHistory,
)
from juloserver.channeling_loan.constants import (
    ChannelingStatusConst,
    ChannelingConst,
    ChannelingLenderLoanLedgerConst,
    ChannelingActionTypeConst,
    ARSwitchingConst,
)
from juloserver.julo.models import (
    Document,
)
from juloserver.channeling_loan.tasks import (
    process_ar_switching_task,
    process_upload_ar_switching_file,
    process_upload_loan_write_off_file,
    process_upload_lender_switch_file,
    process_loan_write_off_task,
    construct_fama_response_tasks,
    proceed_sync_channeling,
    construct_bss_response_tasks,
    process_lender_switch_task,
)
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.streamlined_communication.utils import add_thousand_separator
from juloserver.channeling_loan.crm_forms import (
    LenderOspTransactionSearchForm,
    LenderRepaymentSearchForm,
    LenderAccountSearchForm,
)

logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
class ChannelingLoanListView(ListView):
    model = ChannelingLoanStatus
    paginate_by = 50
    template_name = '../../channeling_loan/templates/list.html'

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data()
        if not get_channeling_loan_configuration(context['channeling_type']):
            return redirect(reverse('dashboard:bo_finance'))
        return self.render_to_response(context)

    def get_queryset(self):
        self.qs = super(ChannelingLoanListView, self).get_queryset()
        channeling_type = self.kwargs['channeling_type']
        self.error_message = None
        self.tgl_range = None
        self.qs = self.qs.filter(
            channeling_type=channeling_type,
            channeling_eligibility_status__channeling_type=channeling_type,
            channeling_eligibility_status__eligibility_status=ChannelingStatusConst.ELIGIBLE,
        ).order_by('-cdate')

        if self.request.method == 'GET':
            self.tgl_range = self.request.GET.get('datetime_range', None)
            self.status = self.request.GET.get('channeling_status', None)
            self.status_now = self.request.GET.get('status_now', 'True')

            if self.status and self.status != "all":
                self.qs = self.qs.filter(channeling_status=self.status)

            if self.status_now:
                if self.status_now == 'True':
                    current_ts = timezone.localtime(timezone.now())
                    startdate = current_ts.replace(hour=0, minute=0, second=0)
                    enddate = startdate + datetime.timedelta(days=1)
                    enddate -= datetime.timedelta(seconds=1)
                    self.qs = self.qs.filter(cdate__range=[startdate, enddate])
                else:
                    _date_range = self.tgl_range.split('-')
                    if _date_range[0].strip() != 'Invalid date':
                        format_date = "%d/%m/%Y %H:%M"
                        _tgl_mulai = datetime.datetime.strptime(_date_range[0].strip(), format_date)
                        _tgl_end = datetime.datetime.strptime(_date_range[1].strip(), format_date)
                        if _tgl_end > _tgl_mulai:
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.error_message = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.error_message = "Format Tanggal tidak valid"
            return self.qs

    def get_context_data(self, **kwargs):
        context = super(ChannelingLoanListView, self).get_context_data(**kwargs)
        url_params = self.request.GET.copy()
        url_params.pop('page', '')
        context['form'] = ChannelingLoanForm()
        if self.request.method == 'GET':
            context['form'] = ChannelingLoanForm(self.request.GET.copy())
        context['results_per_page'] = self.paginate_by
        context['channeling_type'] = self.kwargs['channeling_type']
        context['error_message'] = self.error_message
        context['parameters'] = url_params.urlencode()
        return context


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def download_approval_channeling_loan_data(request, channeling_type):
    file_type = request.GET.get('file_type', ChannelingActionTypeConst.DISBURSEMENT)
    if channeling_type not in ChannelingConst.LIST:
        return redirect(reverse('dashboard:bo_finance'))

    return get_approval_response(
        request=request, channeling_type=channeling_type, file_type=file_type
    )


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def download_channeling_loan_data(request, channeling_type, file_type):
    if not file_type:
        file_type = ChannelingActionTypeConst.DISBURSEMENT
    current_ts = timezone.localtime(timezone.now())
    startdate = current_ts.replace(hour=0, minute=0, second=0)
    enddate = (startdate + datetime.timedelta(days=1)) - datetime.timedelta(seconds=1)
    _filter = {
        "channeling_type": channeling_type,
        "channeling_eligibility_status__channeling_type": channeling_type,
        "channeling_eligibility_status__eligibility_status": ChannelingStatusConst.ELIGIBLE,
        "cdate__range": [startdate, enddate],
    }
    tgl_range = request.GET.get('datetime_range', None)
    status = request.GET.get('channeling_status', None)
    status_now = request.GET.get('status_now', 'True')
    if status and status != "all":
        _filter["channeling_status"] = status

    if status_now:
        if status_now == 'False':
            _date_range = tgl_range.split('-')
            if _date_range[0].strip() != 'Invalid date':
                _tgl_mulai = datetime.datetime.strptime(_date_range[0].strip(), "%d/%m/%Y %H:%M")
                _tgl_end = datetime.datetime.strptime(_date_range[1].strip(), "%d/%m/%Y %H:%M")
                if _tgl_end > _tgl_mulai:
                    _filter["cdate__range"] = [_tgl_mulai, _tgl_end]

    logger.info(
        {
            'action': 'juloserver.channeling_loan.views.crm_views.download_channeling_loan_data',
            "message": "File uploaded successfully",
            'current_ts': current_ts,
            '_filter': _filter,
        }
    )

    if channeling_type == ChannelingConst.BJB:
        return construct_bjb_response(current_ts, _filter)

    if channeling_type == ChannelingConst.FAMA:
        construct_fama_response_tasks.delay(
            current_ts, _filter, user_id=request.user.id, upload=True
        )
        base_url = "%s?%s" % (
            reverse('channeling_loan_portal:list', args=[channeling_type]),
            request.GET.copy().urlencode(),
        )
        messages.info(
            request, "File will be generated, you'll be inform over slack for download link"
        )
        return redirect(base_url)

    if channeling_type == ChannelingConst.PERMATA:
        """
        handled for repayment / reconciliation case for permata only
        becayse permata are not using metabase to upload the repayment / reconciliation file
        """
        return construct_permata_response(
            current_ts, _filter, user_id=request.user.id, file_type=file_type
        )

    if channeling_type == ChannelingConst.SMF:
        base_url = "%s?%s" % (
            reverse('channeling_loan_portal:list', args=[channeling_type]),
            request.GET.copy().urlencode(),
        )
        filename = construct_smf_response(current_ts, _filter, user_id=request.user.id)
        messages.info(
            request,
            (
                "File will be generated with name %s, "
                "you'll be inform over slack for download link" % filename
            ),
        )
        return redirect(base_url)

    if channeling_type == ChannelingConst.BSS:
        construct_bss_response_tasks.delay(current_ts, _filter, user_id=request.user.id)

        base_url = "%s?%s" % (
            reverse('channeling_loan_portal:list', args=[channeling_type]),
            request.GET.copy().urlencode(),
        )
        messages.info(
            request, ("File will be generated " "you'll be inform over slack for download link")
        )
        return redirect(base_url)

    return redirect(reverse('dashboard:bo_finance'))


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def sync_disbursement_channeling_loan_data(request, channeling_type):
    base_url = "%s?%s" % (
        reverse('channeling_loan_portal:list', args=[channeling_type]),
        request.GET.copy().urlencode(),
    )
    upload_form = UploadFileForm(request.POST, request.FILES)
    if not upload_form.is_valid():
        messages.error(request, 'Invalid form')
        return redirect(base_url)

    url_field = upload_form.cleaned_data['url_field']
    file_ = upload_form.cleaned_data['file_field']
    if file_:
        extension = file_.name.split('.')[-1]
        if extension not in ['xls', 'xlsx', 'csv']:
            messages.error(request, 'Please upload correct file excel')
            return redirect(base_url)

    if channeling_type == ChannelingConst.BSS:
        current_user = request.user
        username = current_user.username
        batch_number = timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M")
        reason = 'Lender switcher by {} batch:{}'.format(current_user.username, batch_number)
        upload_file = request.FILES.get("file_field")
        upload_form.cleaned_data.pop('file_field')
        if upload_file:
            filename = '{}_{}_{}'.format(username, batch_number, upload_file.name)
            file_path = os.path.join(tempfile.gettempdir(), filename)
            with open(file_path, 'wb') as f:
                f.write(upload_file.read())

            document = Document.objects.create(
                document_source=current_user.id,
                document_type="lender_switcher",
                filename=filename,
            )
            process_upload_lender_switch_file(
                username,
                upload_form.cleaned_data,
                reason,
                document.id,
                file_path,
                channeling_type,
            )
        else:
            process_lender_switch_task.delay(
                username,
                None,
                upload_form.cleaned_data,
                reason,
                channeling_type,
            )
    else:
        proceed_sync_channeling.delay(url_field, file_, channeling_type)

    logs = (
        "Your sync request is being processed. The result will be send in Channel:" " {}"
    ).format(settings.SYNC_COMPLETE_SLACK_NOTIFICATION_CHANNEL)
    messages.success(request, logs)
    return redirect(base_url)


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def send_permata_early_payoff_request(request):
    base_url = reverse('channeling_loan_portal:list', args=[ChannelingConst.PERMATA])

    upload_form = UploadFileForm(request.POST, request.FILES)
    if not upload_form.is_valid():
        messages.error(request, "Please check again your input")
        return redirect(base_url)

    success, response = process_permata_early_payoff_request(
        csv_file=upload_form.cleaned_data['file_field'],
        user_id=request.user.id,
    )
    if not success:
        messages.error(request, response)
        return redirect(base_url)

    return response


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def repayment_channeling_loan_data(request, channeling_type):
    current_ts = timezone.localtime(timezone.now())
    if channeling_type == ChannelingConst.BNI:
        bni_repayment_service = BNIRepaymentServices()
        success, result = bni_repayment_service.send_repayment_for_channeling_to_bni(request)
    elif channeling_type == ChannelingConst.DBS:
        success, result = DBSRepaymentServices().send_repayment_for_channeling_to_dbs(
            request, is_upload_to_oss=True
        )
    else:
        success, result = construct_fama_repayment_response(
            request, channeling_type, current_ts, user_id=request.user.id
        )

    if not success:
        messages.error(request, str(result))
        return redirect(reverse('channeling_loan_portal:list', args=[channeling_type]))

    if channeling_type == ChannelingConst.BNI:
        filename = result.get("filename", None)
        content = result.get("content", None)
        content_disposition = "attachment; filename=%s" % (filename)
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    elif channeling_type == ChannelingConst.DBS:
        base_url = "%s?%s" % (
            reverse('channeling_loan_portal:list', args=[channeling_type]),
            request.GET.copy().urlencode(),
        )
        messages.info(
            request,
            (
                "File will be generated with name %s, "
                "you'll be inform over slack for download link" % result
            ),
        )
        return redirect(base_url)
    else:
        content = result
        content_disposition = "attachment; filename=%s_Repayment_%s.txt" % (
            channeling_type,
            current_ts.strftime("%Y%m%d%H%M"),
        )
        content_type = 'text/plain'

    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = content_disposition
    return response


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def reconciliation_channeling_loan_data(request, channeling_type):
    content_type = 'text/plain'
    current_ts = timezone.localtime(timezone.now())

    if channeling_type == ChannelingConst.DBS:
        success, content = DBSReconciliationServices().send_reconciliation_for_channeling_to_dbs(
            request, is_upload_to_oss=True
        )

        filename = content
    else:
        success, content = construct_fama_reconciliation_response(
            request, channeling_type, current_ts, user_id=request.user.id
        )

        filename = "FAMA_Reconciliation_%s.txt" % (current_ts.strftime("%Y%m%d%H%M"))

    if not success:
        messages.error(request, content)
        return redirect(reverse('channeling_loan_portal:list', args=[channeling_type]))

    if channeling_type == ChannelingConst.DBS:
        base_url = "%s?%s" % (
            reverse('channeling_loan_portal:list', args=[channeling_type]),
            request.GET.copy().urlencode(),
        )
        messages.info(
            request,
            (
                "File will be generated with name %s, "
                "you'll be inform over slack for download link" % filename
            ),
        )
        return redirect(base_url)

    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = 'attachment; filename=%s' % filename
    return response


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def ar_switching_view(request):
    def _render(request, upload_form=None):
        if not upload_form:
            upload_form = ARSwitcherForm()
        return render(
            request,
            '../../channeling_loan/templates/ar_switching.html',
            {'form': upload_form}
        )

    if request.method == 'GET':
        return _render(request)

    upload_form = ARSwitcherForm(request.POST, request.FILES)
    current_user = request.user
    username = current_user.username
    if upload_form.is_valid():
        batch_number = timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M")
        reason = 'AR Switch by {} batch:{}'.format(current_user.username, batch_number)
        upload_file = request.FILES.get("file_field")
        upload_form.cleaned_data.pop('file_field')

        slack_messages = "*{} begin*".format(reason)
        send_notification_to_slack(
            slack_messages, settings.SYNC_COMPLETE_SLACK_NOTIFICATION_CHANNEL
        )
        ARSwitchHistory.objects.create(
            username=username, batch=reason, status=ARSwitchingConst.STARTED_AR_SWITCH_STATUS
        )

        if upload_file:
            filename = '{}_{}_{}'.format(username, batch_number, upload_file.name)
            file_path = os.path.join(tempfile.gettempdir(), filename)
            with open(file_path, 'wb') as f:
                f.write(upload_file.read())

            document = Document.objects.create(
                document_source=current_user.id,
                document_type="ar_switching",
                filename=filename,
            )
            process_upload_ar_switching_file(
                username, upload_form.cleaned_data, reason, document.id, file_path
            )
        else:
            execute_after_transaction_safely(
                lambda: process_ar_switching_task.delay(
                    username, None, upload_form.cleaned_data, reason
                )
            )
        upload_form = ARSwitcherForm()
        messages.success(request, 'Batch Number : {}'.format(reason))

    else:
        messages.error(request, "Failed : please check again your input")

    return _render(request, upload_form)


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def write_off_view(request):
    def _render(request, upload_form=None):
        if not upload_form:
            upload_form = WriteOffLoanForm()
        return render(
            request, '../../channeling_loan/templates/write_off_loan.html', {'form': upload_form}
        )

    if request.method == 'GET':
        return _render(request)

    upload_form = WriteOffLoanForm(request.POST, request.FILES)
    current_user = request.user
    username = current_user.username
    if upload_form.is_valid():
        batch_number = timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M")
        reason = 'Write off by {} batch:{}'.format(current_user.username, batch_number)
        upload_file = request.FILES.get("file_field")
        upload_form.cleaned_data.pop('file_field')
        channeling_type = ChannelingConst.BSS
        if upload_file:
            filename = '{}_{}_{}'.format(username, batch_number, upload_file.name)
            file_path = os.path.join(tempfile.gettempdir(), filename)
            with open(file_path, 'wb') as f:
                f.write(upload_file.read())

            document = Document.objects.create(
                document_source=current_user.id,
                document_type="write_off",
                filename=filename,
            )
            process_upload_loan_write_off_file(
                username,
                upload_form.cleaned_data,
                reason,
                document.id,
                file_path,
                channeling_type,
                current_user.id,
            )
        else:
            process_loan_write_off_task.delay(
                username,
                None,
                upload_form.cleaned_data,
                reason,
                channeling_type,
                current_user.id,
            )

        upload_form = WriteOffLoanForm()
        messages.success(request, 'Batch Number : {}'.format(reason))

    else:
        messages.error(request, "Failed : please check again your input")

    return _render(request, upload_form)


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
class LenderOspTransactionListView(ListView):
    queryset = LenderOspTransaction.objects.order_by('-id')
    paginate_by = 50
    template_name = '../../channeling_loan/templates/lender_withdraw_batch_list.html'
    paginator_class = TimeLimitedPaginator

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        self.change_currency_format(self.object_list)
        context = self.get_context_data()
        return self.render_to_response(context)

    def change_currency_format(self, objects):
        for object in objects:
            object.balance_amount = add_thousand_separator(str(object.balance_amount))

    def get_queryset(self):
        queryset = super(LenderOspTransactionListView, self).get_queryset()
        if not self.is_reset_filter():
            queryset = self.filter_queryset(queryset)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(LenderOspTransactionListView, self).get_context_data(**kwargs)
        context['results_per_page'] = self.paginate_by
        filter_form = LenderOspTransactionSearchForm(self.get_request_data())

        if self.is_reset_filter():
            filter_form.reset_filter()
        context['filter_form'] = filter_form
        return context

    def get_request_data(self):
        request_data = self.request.GET.copy()
        return request_data

    def is_reset_filter(self):
        return 'reset' in self.request.GET

    def filter_queryset(self, queryset):
        form = LenderOspTransactionSearchForm(self.get_request_data())
        if form.is_valid():
            filter_keyword = form.cleaned_data.get('filter_keyword')
            filter_condition = form.cleaned_data.get('filter_condition', 'contains')
            filter_field = form.cleaned_data.get('filter_field')
            filter_args = {}
            if filter_keyword:
                filter_args = {
                    '{}__{}'.format(filter_field, filter_condition): filter_keyword
                }

            filter_args['transaction_type'] = ChannelingLenderLoanLedgerConst.WITHDRAWAL
            queryset = queryset.filter(**filter_args)
        return queryset


@julo_login_required
@require_http_methods([HTTPMethod.GET, HTTPMethod.POST])
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def lender_osp_transaction_create_view(request):
    template_name = '../../channeling_loan/templates/lender_withdraw_batch_form.html'

    form = LenderOspTransactionForm()
    if request.method == 'POST':
        form = LenderOspTransactionForm(request.POST)
        if form.is_valid():
            execute_withdraw_batch_service(form.cleaned_data)
            url = reverse('channeling_loan_portal:lender_osp_transaction_list')
            return redirect(url)
        else:
            messages.error(request, 'Input must not be null')

    return render(request, template_name, {'form': form})


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
class LenderOspTransactionDetailView(ListView):
    paginate_by = 50
    template_name = '../../channeling_loan/templates/lender_withdraw_batch_form.html'
    paginator_class = TimeLimitedPaginator
    lender_osp_transaction = None
    lender_loan_ledgers = []

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data()
        return self.render_to_response(context)

    def get_queryset(self):
        lender_osp_transaction_id = self.kwargs['lender_osp_transaction_id']
        self.lender_osp_transaction = get_object_or_404(
            LenderOspTransaction,
            pk=lender_osp_transaction_id
        )
        self.lender_osp_transaction.balance_amount = add_thousand_separator(
            str(self.lender_osp_transaction.balance_amount)
        )
        self.lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account_id=self.lender_osp_transaction.lender_osp_account_id
        )
        for lender_loan_ledger in self.lender_loan_ledgers:
            lender_loan_ledger.osp_amount = add_thousand_separator(
                str(lender_loan_ledger.osp_amount)
            )

        return self.lender_loan_ledgers

    def get_context_data(self, **kwargs):
        context = super(LenderOspTransactionDetailView, self).get_context_data(**kwargs)
        context['form'] = LenderOspTransactionForm(instance=self.lender_osp_transaction)
        context['results_per_page'] = self.paginate_by
        context['disabled'] = True
        return context


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
class LenderRepaymentListView(ListView):
    queryset = LenderOspTransaction.objects.order_by('-id')
    paginate_by = 50
    template_name = '../../channeling_loan/templates/lender_repayment_list.html'
    paginator_class = TimeLimitedPaginator

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        self.change_currency_format(self.object_list)
        context = self.get_context_data()
        return self.render_to_response(context)

    def change_currency_format(self, objects):
        for object in objects:
            object.balance_amount = add_thousand_separator(str(object.balance_amount))

    def get_queryset(self):
        queryset = super(LenderRepaymentListView, self).get_queryset()
        if not self.is_reset_filter():
            queryset = self.filter_queryset(queryset)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(LenderRepaymentListView, self).get_context_data(**kwargs)
        context['results_per_page'] = self.paginate_by
        filter_form = LenderRepaymentSearchForm(self.get_request_data())

        if self.is_reset_filter():
            filter_form.reset_filter()
        context['filter_form'] = filter_form
        return context

    def get_request_data(self):
        request_data = self.request.GET.copy()
        return request_data

    def is_reset_filter(self):
        return 'reset' in self.request.GET

    def filter_queryset(self, queryset):
        form = LenderRepaymentSearchForm(self.get_request_data())
        if form.is_valid():
            filter_keyword = form.cleaned_data.get('filter_keyword')
            filter_condition = form.cleaned_data.get('filter_condition', 'contains')
            filter_field = form.cleaned_data.get('filter_field')
            filter_args = {}
            if filter_keyword:
                filter_args = {
                    '{}__{}'.format(filter_field, filter_condition): filter_keyword
                }

            filter_args['transaction_type'] = ChannelingLenderLoanLedgerConst.REPAYMENT
            queryset = queryset.filter(**filter_args)
        return queryset


@julo_login_required
@require_http_methods([HTTPMethod.GET, HTTPMethod.POST])
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def lender_repayment_create_view(request):
    template_name = '../../channeling_loan/templates/lender_repayment_form.html'

    form = LenderOspTransactionForm()
    if request.method == 'POST':
        form = LenderOspTransactionForm(request.POST)
        if form.is_valid():
            execute_repayment_service(form.cleaned_data)
            url = reverse('channeling_loan_portal:lender_repayment_list')
            return redirect(url)
        else:
            messages.error(request, 'Input must not be null')

    return render(request, template_name, {'form': form})


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
class LenderRepaymentDetailView(ListView):
    paginate_by = 50
    template_name = '../../channeling_loan/templates/lender_repayment_form.html'
    paginator_class = TimeLimitedPaginator
    lender_osp_transaction = None
    lender_loan_ledgers = []

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data()
        return self.render_to_response(context)

    def get_queryset(self):
        lender_osp_transaction_id = self.kwargs['lender_osp_transaction_id']
        self.lender_osp_transaction = get_object_or_404(
            LenderOspTransaction,
            pk=lender_osp_transaction_id
        )
        self.lender_osp_transaction.balance_amount = add_thousand_separator(
            str(self.lender_osp_transaction.balance_amount)
        )
        self.lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account_id=self.lender_osp_transaction.lender_osp_account_id
        )
        return self.lender_loan_ledgers

    def get_context_data(self, **kwargs):
        context = super(LenderRepaymentDetailView, self).get_context_data(**kwargs)
        context['form'] = LenderOspTransactionForm(instance=self.lender_osp_transaction)
        context['results_per_page'] = self.paginate_by
        context['disabled'] = True
        return context


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
class LenderOpsAccountListView(ListView):
    queryset = LenderOspAccount.objects.order_by('priority')
    paginate_by = 10
    template_name = '../../channeling_loan/templates/balance_lender_list.html'
    paginator_class = TimeLimitedPaginator

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        self.change_currency_format(self.object_list)
        context = self.get_context_data()
        return self.render_to_response(context)

    def change_currency_format(self, objects):
        for object in objects:
            object.balance_amount = add_thousand_separator(str(object.balance_amount))
            object.fund_by_lender = add_thousand_separator(str(object.fund_by_lender))
            object.fund_by_julo = add_thousand_separator(str(object.fund_by_julo))
            object.total_outstanding_principal = add_thousand_separator(
                str(object.total_outstanding_principal)
            )

    def get_queryset(self):
        queryset = super(LenderOpsAccountListView, self).get_queryset()
        if not self.is_reset_filter():
            queryset = self.filter_queryset(queryset)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(LenderOpsAccountListView, self).get_context_data(**kwargs)
        context['results_per_page'] = self.paginate_by
        filter_form = LenderAccountSearchForm(self.get_request_data())

        if self.is_reset_filter():
            filter_form.reset_filter()
        context['filter_form'] = filter_form
        return context

    def get_request_data(self):
        request_data = self.request.GET.copy()
        return request_data

    def is_reset_filter(self):
        return 'reset' in self.request.GET

    def filter_queryset(self, queryset):
        form = LenderAccountSearchForm(self.get_request_data())
        if form.is_valid():
            filter_keyword = form.cleaned_data.get('filter_keyword')
            filter_condition = form.cleaned_data.get('filter_condition', 'contains')
            filter_field = form.cleaned_data.get('filter_field')
            filter_args = {}
            if filter_keyword:
                filter_args = {
                    '{}__{}'.format(filter_field, filter_condition): filter_keyword
                }

            queryset = queryset.filter(**filter_args)
        return queryset


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
class LenderOpsAccountDetailView(ListView):
    paginate_by = 50
    template_name = '../../channeling_loan/templates/balance_lender_form.html'
    paginator_class = TimeLimitedPaginator
    lender_loan_ledgers = []

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data()
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        lender_osp_account_id = self.kwargs['lender_osp_account_id']
        lender_osp_account = LenderOspAccount.objects.get_or_none(
            pk=lender_osp_account_id
        )
        if lender_osp_account:
            priority = request.POST.get('priority')
            lender_osp_account.update_safely(
                priority=priority
            )
            url = reverse('channeling_loan_portal:lender_osp_account_list')
            return redirect(url)
        else:
            messages.error(request, 'Error')

    def get_queryset(self):
        lender_osp_account_id = self.kwargs['lender_osp_account_id']
        self.lender_osp_account = get_object_or_404(
            LenderOspAccount,
            pk=lender_osp_account_id
        )
        self.lender_osp_account.balance_amount = add_thousand_separator(
            str(self.lender_osp_account.balance_amount)
        )
        self.lender_osp_account.fund_by_lender = add_thousand_separator(
            str(self.lender_osp_account.fund_by_lender)
        )
        self.lender_osp_account.fund_by_julo = add_thousand_separator(
            str(self.lender_osp_account.fund_by_julo)
        )
        self.lender_osp_account.total_outstanding_principal = add_thousand_separator(
            str(self.lender_osp_account.total_outstanding_principal)
        )
        self.lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account_id=lender_osp_account_id
        )
        for lender_loan_ledger in self.lender_loan_ledgers:
            lender_loan_ledger.osp_amount = add_thousand_separator(
                str(lender_loan_ledger.osp_amount)
            )
        return self.lender_loan_ledgers

    def get_context_data(self, **kwargs):
        context = super(LenderOpsAccountDetailView, self).get_context_data(**kwargs)
        context['form'] = LenderOspAccountForm(instance=self.lender_osp_account)
        context['results_per_page'] = self.paginate_by
        context['disabled'] = True
        return context
