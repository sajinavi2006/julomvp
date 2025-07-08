import csv
import io
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

from django.conf import settings
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.db import transaction
from django.db.models import CharField, Q, Value, Sum
from django.forms import formset_factory
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import CreateView, ListView
from scraped_data.forms import ApplicationSearchForm

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLimit
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.constants import UploadAsyncStateStatus
from juloserver.julo.models import (
    Agent,
    Application,
    Document,
    Image,
    Loan,
    Partner,
    Payment,
    ProductLookup,
    UploadAsyncState,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.merchant_financing.web_app.constants import (
    MF_WEB_APP_DISBURSEMENT_UPLOAD_HEADER,
    MF_WEB_APP_LOAN_UPLOAD_HEADER,
    MF_WEB_APP_REPAYMENT_UPLOAD_HEADER,
    MFWebAppUploadAsyncStateType,
    MF_WEB_APP_REGISTER_UPLOAD_HEADER,
    MF_WEB_APP_REPAYMENT_PER_LOAN_UPLOAD_HEADER,
)
from juloserver.merchant_financing.web_app.crm.forms import (
    MFWebAppCSVLoanUploadForm,
    MFWebappLoanListForm,
    MFWebAppMultiImageUploadForm,
    MFWebAppUploadFileForm,
    MFWebDisbursementUploadFileForm,
    MFWebLoanUploadFileForm,
    MFWebRepaymentUploadFileForm,
)
from juloserver.merchant_financing.web_app.crm.serializers import (
    MFWebAppRepaymentUploadSerializer,
    MFWebAppRepaymentUploadPerLoanSerializer,
)
from juloserver.merchant_financing.web_app.crm.services import (
    create_loan_mf_bau,
    create_or_update_account_payments,
    merchant_financing_repayment,
    merchant_financing_repayment_per_loan,
)
from juloserver.merchant_financing.web_app.crm.tasks import (
    process_mf_web_app_register_file_task,
    send_email_skrtp,
)
from juloserver.merchant_financing.web_app.crm.utils import (
    mf_web_app_filter_search_field,
    mf_web_app_loan_filter_search_field,
)
from juloserver.merchant_financing.web_app.services import (
    process_upload_document,
    process_image_upload,
)
from juloserver.merchant_financing.web_app.tasks import (
    send_success_email_after_loan_220,
)
from juloserver.partnership.constants import CSV_DELIMITER_SIZE, DOCUMENT_TYPE, IMAGE_TYPE
from juloserver.partnership.models import (
    PartnershipCustomerData,
    PartnershipDistributor,
    PartnerLoanRequest,
    PartnershipApplicationData,
)
from juloserver.partnership.utils import (
    generate_pii_filter_query_partnership,
    partnership_detokenize_sync_kv_in_bulk,
    partnership_detokenize_sync_primary_object_model_in_bulk,
)
from juloserver.pii_vault.constants import PiiSource
from juloserver.portal.object import julo_login_required, julo_login_required_multigroup
from juloserver.utilities.paginator import TimeLimitedPaginator
from juloserver.merchant_financing.web_app.utils import mf_standard_verify_nik
from juloserver.sdk.models import AxiataCustomerData
from juloserver.partnership.tasks import (
    partnership_mfsp_send_email_disbursement_notification_task,
)

logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class ApplicationMFWebAppListApplicationStatusView(ListView):
    model = Application
    paginate_by = 50
    paginator_class = TimeLimitedPaginator
    template_name = 'object/merchant_financing_web_app/mf_web_app_list_application.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()

        self.qs = self.qs.filter(product_line_id=ProductLineCodes.AXIATA_WEB).order_by('-id')
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

                field, keyword = mf_web_app_filter_search_field(self.search_q)
                search_type = (
                    'in'
                    if field
                    in {'partnership_customer_data__application__product_line_id', 'account_id'}
                    else search_type
                )
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
        context = super(
            ApplicationMFWebAppListApplicationStatusView, self
        ).get_context_data(**kwargs)

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
        rend_here = super(ApplicationMFWebAppListApplicationStatusView, self).render_to_response(
            context, **response_kwargs
        )
        return rend_here


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def mf_web_app_upload_documents(request, pk):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    app_obj = get_object_or_404(Application, id=pk)
    if not hasattr(app_obj, 'partnership_customer_data'):
        return render(request, 'covid_refinancing/404.html')
    list_document = list()
    template_name = ('object/merchant_financing_web_app/mf_web_app_upload_document.html',)

    if request.method == 'POST':
        form = MFWebAppMultiImageUploadForm(request.POST, request.FILES)

        if form.is_valid():
            image_source = form.cleaned_data['attachment']
            document_type = form.cleaned_data['document_type']
            extension = form.cleaned_data['extension']
            file_name = form.cleaned_data['file_name']

            obj_image = Image()
            obj_image.image_source = app_obj.id
            obj_image.image_type = document_type
            obj_image.save()

            if extension in {'.jpeg', '.png', '.jpg'}:
                process_image_upload(
                    image=obj_image,
                    image_file=image_source,
                    thumbnail=True,
                    delete_if_last_image=False,
                    suffix=file_name
                )
                obj_image.refresh_from_db()
            else:
                document = Document.objects.create(
                    document_source=app_obj.id,
                    document_type=document_type,
                    filename=image_source.name,
                    application_xid=app_obj.application_xid
                )
                data = dict()
                data['customer_id'] = app_obj.customer_id
                data['type'] = document_type
                data['extension'] = extension
                process_upload_document(image_source, document, data)

            url = reverse('bulk_upload:mf_web_app_documents_upload', kwargs={'pk': app_obj.id})
            return redirect(url)
        else:
            err_msg = form.errors
            logger.info({
                'app_id': app_obj.id,
                'error': form.errors
            })
            messages.error(request, err_msg)
            url = reverse('bulk_upload:mf_web_app_documents_upload', kwargs={'pk': app_obj.id})
            return redirect(url)
    else:
        form = MFWebAppMultiImageUploadForm()
        list_document_type = DOCUMENT_TYPE.copy()
        list_document_type.update(IMAGE_TYPE)
        images = Image.objects.filter(
            image_source=app_obj.id,
            image_type__in=list_document_type
        )
        for image in images:
            split_str = image.url.split('_')[::-1]
            file_name = ''
            if len(split_str) > 0:
                file_name = split_str[0]

            list_document.append({
                "url": image.image_url_api,
                "id": str(image.id) + '_img',
                "file_name": file_name,
                "document_type": image.image_type
            })
        documents = Document.objects.filter(
            document_source=app_obj.id,
            document_type__in=list_document_type
        ).order_by('id')
        for document in documents:
            list_document.append({
                "url": document.document_url,
                "id": document.id,
                "file_name": document.filename,
                "document_type": document.document_type
            })

    context = {
        'form': form,
        'app_obj': app_obj,
        'datetime_now': timezone.now(),
        'list_document': list_document,
    }
    return render(request, template_name, context)


def mf_web_app_csv_upload_view(request):
    upload_form = MFWebAppUploadFileForm(request.POST, request.FILES)
    template_name = 'object/merchant_financing_web_app/mf_web_app_upload.html'
    url = reverse('bulk_upload:mf_web_app_csv_upload')
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

            decoded_file = file_.read().decode('utf-8')
            # Detect the delimiter using csv.Sniffer
            try:
                # using replace just to read the actual delimiter
                dialect = csv.Sniffer().sniff(decoded_file.replace(" ", ""))
            except csv.Error:
                dialect = csv.excel  # default to excel dialect

            reader = csv.DictReader(io.StringIO(decoded_file), dialect=dialect)
            fieldnames_set = set(reader.fieldnames)
            missing_columns = [
                column
                for column in MF_WEB_APP_REGISTER_UPLOAD_HEADER
                if column not in fieldnames_set and column != 'result'
            ]

            if len(missing_columns) > 0:
                msg = 'invalid csv header, missing column {}'.format(', '.join(missing_columns))
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            in_processed_status = {
                UploadAsyncStateStatus.WAITING,
                UploadAsyncStateStatus.PROCESSING,
            }

            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=MFWebAppUploadAsyncStateType.MERCHANT_FINANCING_WEB_APP_REGISTER,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                msg = 'Another process in waiting or process please wait and try again later'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            upload_async_state = UploadAsyncState(
                task_type=MFWebAppUploadAsyncStateType.MERCHANT_FINANCING_WEB_APP_REGISTER,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id
            process_mf_web_app_register_file_task.delay(upload_async_state_id, partner)
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status',
            )
    elif request.method == 'GET':
        upload_form = MFWebAppUploadFileForm()
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class MFWebAppRegiserUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/merchant_financing_web_app/mf_web_app_upload_history.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type=MFWebAppUploadAsyncStateType.MERCHANT_FINANCING_WEB_APP_REGISTER,
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
def mf_webapp_csv_loan_upload(request):
    form = MFWebLoanUploadFileForm(request.POST, request.FILES)
    url = reverse('bulk_upload:mf_webapp_csv_loan_upload')

    if request.method == 'POST':
        template_name = 'object/merchant_financing_web_app/mf_web_app_loan_validation.html'
        if not form.is_valid():
            for key in form.errors:
                messages.error(request, form.errors[key][0] + "\n")
            return HttpResponseRedirect(url)

        file_csv = form.cleaned_data['file_field']
        partner = form.cleaned_data['partner_field']

        if not file_csv.name.endswith('.csv'):
            messages.error(request, 'File is not CSV type')
            return HttpResponseRedirect(url)

        file_content = file_csv.read().decode('utf-8')
        sniffer = csv.Sniffer()
        delimiter = str(sniffer.sniff(file_content[:CSV_DELIMITER_SIZE]).delimiter)
        freader = io.StringIO(file_content)
        reader = csv.DictReader(freader, delimiter=delimiter)

        csv_header = set(reader.fieldnames)
        missing_columns = []
        error_message = ''
        valid_rows = []
        invalid_rows = []

        for column in MF_WEB_APP_LOAN_UPLOAD_HEADER:
            if column not in csv_header:
                missing_columns.append(column)

        if len(missing_columns) > 0:
            error_message = 'invalid csv header, missing column {}'.format(
                ', '.join(missing_columns)
            )
        else:
            distributor_ids = []
            niks = []
            total_loan_amount = dict()
            total_due_amount = dict()
            row_number = 0
            for row in reader:
                if row['distributor'] and row['distributor'].isnumeric():
                    distributor_ids.append(row['distributor'])
                if row['nik'] and row['nik'].isnumeric():
                    niks.append(row['nik'])

            distributors = PartnershipDistributor.objects.filter(
                distributor_id__in=distributor_ids
            )
            distributors_dict = dict()
            for distributor in distributors:
                distributors_dict[str(distributor.distributor_id)] = distributor

            pii_filter_dict = generate_pii_filter_query_partnership(
                PartnershipCustomerData, {'nik__in': niks}
            )
            partnership_customer_list = PartnershipCustomerData.objects.filter(**pii_filter_dict)
            account_ids = []
            for pcd in partnership_customer_list:
                account_ids.append(pcd.account)
            detokenize_partnership_customer_data_list = (
                partnership_detokenize_sync_primary_object_model_in_bulk(
                    PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                    partnership_customer_list,
                    ['nik'],
                )
            )
            account_limits = AccountLimit.objects.filter(account__in=account_ids).select_related(
                'account', 'account__partnership_customer_data'
            )
            account_limits_dict = dict()
            account_status_dict = dict()
            for account_limit in account_limits:
                partnership_customer_data = account_limit.account.partnership_customer_data
                nik = getattr(
                    detokenize_partnership_customer_data_list.get(
                        partnership_customer_data.customer.customer_xid
                    ),
                    'nik',
                    '',
                )
                account_limits_dict[nik] = account_limit
                account_status_dict[nik] = account_limit.account.status_id

                account_payments = AccountPayment.objects.filter(account_id=account_limit.account)

                sum_due_amount = 0
                for account_payment in account_payments:
                    sum_due_amount += (
                        account_payment.principal_amount - account_payment.paid_principal
                    )
                total_due_amount[nik] = sum_due_amount

            product_lookups = ProductLookup.objects.filter(
                product_line=ProductLineCodes.AXIATA_WEB
            ).values('interest_rate', 'origination_fee_pct')

            decimal_precision = 5
            set_interest_and_provision = set()
            for product_lookup in product_lookups:
                interest_fixed_dec = "{0:.5f}".format(
                    round((product_lookup.get('interest_rate') * 100 / 12), decimal_precision)
                )
                provision_fixed_dec = "{0:.5f}".format(
                    round(
                        (product_lookup.get('origination_fee_pct') * 100), decimal_precision
                    )
                )
                set_interest_and_provision.add(
                    "{}_{}".format(interest_fixed_dec, provision_fixed_dec)
                )

            freader.seek(0)
            reader.__init__(freader, delimiter=delimiter)
            for row in reader:
                validation_result = row
                validation_result['note'] = "valid"
                row_number += 1
                validation_result['row_number'] = row_number
                valid_nik = True
                err_fields = []
                account_limit = account_limits_dict.get(row['nik'])

                if not row['nik']:
                    err_fields.append("[nik] can't be empty")
                    valid_nik = False
                else:
                    if not re.match(r'^\d{16}$', row['nik']):
                        err_fields.append("[nik] must be a number and 16 digit")
                        valid_nik = False

                if not account_limit:
                    err_fields.append("[nik] NIK not found")
                    valid_nik = False

                account_status = account_status_dict.get(row['nik'])
                if valid_nik and account_status != AccountConstant.STATUS_CODE.active:
                    err_fields.append("[nik] account_status is not 420")

                if not row['distributor']:
                    err_fields.append("[distributor] can't be empty")
                else:
                    distributor = distributors_dict.get(row['distributor'])
                    if not distributor:
                        err_fields.append("[distributor] not found")

                if not row['funder']:
                    err_fields.append("[funder] can't be empty")

                if not row['invoice_number']:
                    err_fields.append("[invoice_number] can't be empty")

                if not row['type']:
                    err_fields.append("[type] can't be empty")
                else:
                    if row['type'].upper() not in {'SCF', 'IF'}:
                        err_fields.append("[type] must be SCF or IF")
                    else:
                        if row['type'].upper() == 'IF':
                            if not row.get('buyer_name'):
                                err_fields.append("[buyer_name] can't be empty")
                            if not row.get('buying_amount'):
                                err_fields.append("[buying_amount] can't be empty")
                            else:
                                try:
                                    buying_amount = float(row['buying_amount'])
                                    if buying_amount < 0:
                                        err_fields.append("[buying_amount] must be positive value")
                                except ValueError:
                                    err_fields.append("[buying_amount] must be a number")

                if not row['loan_request_date']:
                    err_fields.append("[loan_request_date] can't be empty")
                else:
                    try:
                        datetime.strptime(row['loan_request_date'], '%d/%m/%Y')
                    except ValueError:
                        err_fields.append("[loan_request_date] invalid format, eg. 31/12/2023")

                interest_rate = 0.0
                provision_fee = 0.0
                if not row['interest_rate']:
                    err_fields.append("[interest_rate] can't be empty")
                else:
                    try:
                        interest_rate = float(row['interest_rate'])
                        if interest_rate < 0:
                            err_fields.append("[interest_rate] must be positive value")
                    except ValueError:
                        err_fields.append("[interest_rate] must be a number")

                if not row['provision_fee']:
                    err_fields.append("[provision_fee] can't be empty")
                else:
                    try:
                        provision_fee = float(row['provision_fee'])
                        if provision_fee < 0:
                            err_fields.append("[provision_fee] must be positive value")
                    except ValueError:
                        err_fields.append("[provision_fee] must be a number")

                csv_interest_rate = "{0:.5f}".format(round(interest_rate, decimal_precision))
                csv_provision_fee = "{0:.5f}".format(round(provision_fee, decimal_precision))
                csv_interest_and_provision = "{}_{}".format(csv_interest_rate, csv_provision_fee)
                if csv_interest_and_provision not in set_interest_and_provision:
                    err_fields.append(
                        "[interest_rate] or [provision_fee] not matches with product lookup"
                    )

                if not row['financing_tenure']:
                    err_fields.append("[financing_tenure] can't be empty")
                else:
                    try:
                        financing_tenure = float(row['financing_tenure'])
                        if financing_tenure < 0:
                            err_fields.append("[financing_tenure] must be positive value")
                    except ValueError:
                        err_fields.append("[financing_tenure] must be a number")

                if not row['financing_amount']:
                    err_fields.append("[financing_amount] can't be empty")
                else:
                    try:
                        financing_amount = float(row['financing_amount'])
                        if financing_amount < 0:
                            err_fields.append("[financing_amount] must be positive value")
                        else:
                            total_loan = total_loan_amount.get(row['nik'], 0) + financing_amount
                            if valid_nik:
                                if total_loan > account_limit.available_limit:
                                    err_fields.append(
                                        "[financing_amount] exceed the available limit"
                                    )
                                else:
                                    account_payment_due = total_due_amount.get(row['nik']) or 0
                                    total_due = account_payment_due + financing_amount
                                    if total_due > account_limit.max_limit:
                                        err_fields.append(
                                            "[nik] total due_amount is more than available limit"
                                        )
                                    else:
                                        total_loan_amount[row['nik']] = total_loan
                                        total_due_amount[row['nik']] = total_due
                    except ValueError:
                        err_fields.append("[financing_amount] must be a number")

                if not row['instalment_number']:
                    err_fields.append("[instalment_number] can't be empty")
                else:
                    try:
                        instalment_number = float(row['instalment_number'])
                        if instalment_number < 0:
                            err_fields.append("[instalment_number] must be positive value")
                    except ValueError:
                        err_fields.append("[instalment_number] must be a number")

                if len(err_fields) > 0:
                    validation_result['note'] = ', '.join(err_fields)

                if validation_result['note'] == 'valid':
                    valid_rows.append(validation_result)
                else:
                    invalid_rows.append(validation_result)

        context = {
            'partner': partner,
            'invalid_rows': invalid_rows,
            'valid_rows': valid_rows,
            'error_message': error_message,
            'count_invalid_rows': len(invalid_rows),
            'count_valid_rows': len(valid_rows),
        }

        return render(request, template_name, context)

    elif request.method == 'GET':
        template_name = 'object/merchant_financing_web_app/mf_web_app_loan_upload.html'
        form = MFWebLoanUploadFileForm()
        return render(request, template_name, {'form': form})

    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def mf_webapp_csv_loan_upload_docs(request):
    template_name = 'object/merchant_financing_web_app/mf_web_app_loan_upload_docs.html'

    if request.method == 'POST':
        form = dict(request.POST)

        datas = []
        for row_number in form.get('list_row_number'):
            data = form[row_number]
            datas.append(
                {
                    'row_number': data[0],
                    'nik': data[1],
                    'distributor': data[2],
                    'funder': data[3],
                    'type': data[4],
                    'loan_request_date': data[5],
                    'interest_rate': data[6],
                    'provision_fee': data[7],
                    'provision_rate': data[7],
                    'financing_amount': data[8],
                    'financing_tenure': data[9],
                    'installment_number': data[10],
                    'instalment_number': data[10],
                    'invoice_number': data[11],
                    'buyer_name': data[12],
                    'buying_amount': data[13],
                    'partner': form.get('partner')[0],
                }
            )

        MFWebAppCSVLoanUploadFormset = formset_factory(MFWebAppCSVLoanUploadForm)
        formset = MFWebAppCSVLoanUploadFormset(initial=datas)
        context = {
            'partner': form.get('partner'),
            'datas': datas,
            'formset': formset
        }

        return render(request, template_name, context)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class MFWebAppCSVLoanUploadSubmitView(CreateView):
    def post(self, request, *args, **kwargs):
        MFWebAppCSVLoanUploadFormset = formset_factory(MFWebAppCSVLoanUploadForm)
        formset = MFWebAppCSVLoanUploadFormset(request.POST, request.FILES)
        if formset.is_valid():
            partner = Partner.objects.filter(name=formset.cleaned_data[0]['partner']).last()
            is_success, error_message = create_loan_mf_bau(formset.cleaned_data, partner)
            if is_success:
                messages.success(
                    request,
                    "Loan request has been submitted. \
                    You can check the submission results on the Loan List page"
                )
            else:
                messages.error(request, error_message)

            return HttpResponseRedirect(reverse('bulk_upload:mf_webapp_csv_loan_upload'))
        else:
            context = {
                'formset': formset
            }
            template = 'object/merchant_financing_web_app/mf_web_app_loan_upload_docs.html'
            return render(request, template, context)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class MFWebAppLoanListView(ListView):
    model = Loan
    paginator_class = TimeLimitedPaginator
    paginate_by = 50
    template_name = 'object/merchant_financing_web_app/mf_web_app_loan_list.html'

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self) -> List[str]:
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()
        # use new variable to reduce character
        axiata_web_pl = ProductLineCodes.AXIATA_WEB
        self.qs = self.qs.filter(
            account__partnership_customer_data__application__product_line_id=axiata_web_pl
        )

        self.err_message_here = None
        self.tgl_start = None
        self.tgl_end = None
        self.tgl_range = self.request.GET.get('datetime_range', None)
        self.search_q = self.request.GET.get('search_q', '').strip()
        self.sort_q = self.request.GET.get('sort_q', None)
        self.status_now = self.request.GET.get('status_now', None)

        if isinstance(self.search_q, str) and self.search_q:
            is_matched = re.search("^%(.*)%$", self.search_q)
            search_type = 'iexact'
            if is_matched:
                self.search_q = is_matched.group(1)
                search_type = 'icontains'

            field, keyword = mf_web_app_loan_filter_search_field(self.search_q)
            search_type = 'in' if field in {'product_line_id', 'account_id'} else search_type
            self.qs = self.qs.filter(Q(**{('%s__%s' % (field, search_type)): keyword}))

        self.status_app = self.request.GET.get('status_app', None)
        sort_product_line = self.request.GET.get('list_product_line', None)

        if sort_product_line:
            self.qs = self.qs.filter(
                account__partnership_customer_data__application__product_line_id=sort_product_line
            )

        if self.status_app:
            self.qs = self.qs.filter(loan_status=self.status_app)

        if self.status_now:
            if self.status_now == 'True':
                startdate = datetime.today()
                startdate = startdate.replace(hour=0, minute=0, second=0)
                enddate = startdate + timedelta(days=1)
                enddate = enddate - timedelta(seconds=1)
                self.qs = self.qs.filter(cdate__range=[startdate, enddate])
            else:
                _date_range = self.tgl_range.split('-')
                if _date_range[0].strip() != 'Invalid date':
                    _tgl_mulai = datetime.strptime(
                        _date_range[0].strip(), "%d/%m/%Y %H:%M"
                    )
                    _tgl_end = datetime.strptime(_date_range[1].strip(), "%d/%m/%Y %H:%M")
                    if _tgl_end > _tgl_mulai:
                        self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                    else:
                        self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                else:
                    self.err_message_here = "Format Tanggal tidak valid"

        if self.status_now:
            if self.status_now == 'True':
                start_date = datetime.today()
                start_date = start_date.replace(hour=0, minute=0, second=0)
                end_date = start_date + timedelta(days=1)
                end_date = end_date - timedelta(seconds=1)
                self.qs = self.qs.filter(cdate__range=[start_date, end_date])
            else:
                _date_range = self.tgl_range.split('-')
                if _date_range[0].strip() != 'Invalid date':
                    _tgl_mulai = datetime.strptime(_date_range[0].strip(), "%d/%m/%Y %H:%M")
                    _tgl_end = datetime.strptime(_date_range[1].strip(), "%d/%m/%Y %H:%M")
                    if _tgl_end > _tgl_mulai:
                        self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                    else:
                        self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                else:
                    self.err_message_here = "Format Tanggal tidak valid"

        if self.sort_q:
            self.qs = self.qs.order_by(self.sort_q)

        return self.qs.select_related(
            'loan_status',
            'account',
            'account__partnership_customer_data',
            'account__partnership_customer_data__application__product_line',
        )

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = MFWebappLoanListForm(self.request.GET.copy())
        else:
            context['form_search'] = MFWebappLoanListForm()

        context['results_per_page'] = self.paginate_by
        return context

    def get(self, request, *args, **kwargs):
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super().render_to_response(context, **response_kwargs)
        return rend_here


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def mf_webapp_csv_disbursement_upload(request):
    template_name = 'object/merchant_financing_web_app/mf_web_app_disbursement_upload.html'
    logs = ""
    upload_form = MFWebDisbursementUploadFileForm
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

        if extension != 'csv':
            logs = 'Please upload the correct file type: CSV'
            messages.error(request, logs)
            return _render()

        freader = io.StringIO(file_.read().decode('utf-8'))
        reader = csv.DictReader(freader, delimiter=',')

        not_exist_headers = []
        for header in MF_WEB_APP_DISBURSEMENT_UPLOAD_HEADER:
            if header not in reader.fieldnames:
                not_exist_headers.append(header)

        if len(not_exist_headers) == len(MF_WEB_APP_DISBURSEMENT_UPLOAD_HEADER):
            logs = 'CSV format is not correct'
            messages.error(request, logs)
            return _render()

        if not_exist_headers:
            logs = 'CSV format is not correct. Headers not exists: %s' % not_exist_headers
            messages.error(request, logs)
            return _render()

        loan_xids = []
        for row in reader:
            if row['loan_xid'].isnumeric():
                loan_xids.append(int(row['loan_xid']))

        loans = (
            Loan.objects.prefetch_related("payment_set")
            .select_related("customer", "account")
            .filter(loan_xid__in=loan_xids)
        )

        loan_dicts = {}
        application_ids = set()

        for loan in loans:
            loan_dicts[loan.loan_xid] = loan
            application_ids.add(loan.application_id2)

        applications = Application.objects.select_related("partner", "product_line").filter(
            id__in=application_ids
        )
        partner_loan_requests = PartnerLoanRequest.objects.select_related("partner", "loan").filter(
            loan__application_id2__in=application_ids
        )

        app_dicts = {}
        partner_dicts = {}

        for app in applications:
            app_dicts[app.id] = {"product_line": app.product_line.product_line_code}

        partner_ids = set()
        for plr in partner_loan_requests:
            partner_ids.add(plr.partner.id)

        partner_query = Partner.objects.filter(id__in=partner_ids).all()
        detokenize_partner_list = partnership_detokenize_sync_kv_in_bulk(
            PiiSource.PARTNER,
            partner_query,
            ['name'],
        )

        for plr in partner_loan_requests:
            partner_name = getattr(detokenize_partner_list.get(plr.partner.id), 'name', '')
            partner_dicts[plr.loan.application_id2] = {"partner": partner_name}

        freader.seek(0)
        reader.__init__(freader, delimiter=',')
        for idx, row in enumerate(reader, start=2):
            idx -= 1
            if not row['loan_xid'].isnumeric():
                logs += "loan_xid baris ke-%s - loan tidak numerik\n" % idx
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            loan = loan_dicts.get(int(row['loan_xid']))
            if not loan:
                logs += "loan_xid baris ke-%s - loan tidak ditemukan\n" % idx
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            if (
                partner != PartnerNameConstant.AXIATA_WEB
                and partner_dicts[loan.application_id2]["partner"] != partner
            ):
                logs += "partner tidak sesuai\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            if (
                partner == PartnerNameConstant.AXIATA_WEB
                and app_dicts[loan.application_id2]["product_line"] != ProductLineCodes.AXIATA_WEB
            ):
                logs += "product_line tidak sesuai\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            if (
                loan.loan_status_id != LoanStatusCodes.FUND_DISBURSAL_ONGOING
                and partner == PartnerNameConstant.AXIATA_WEB
            ):
                logs += (
                    "loan_xid baris ke-%s -"
                    "disbursement tidak bisa dilakukan untuk loan ini\n" % idx
                )
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            elif (
                loan.loan_status_id != LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING
                and partner != PartnerNameConstant.AXIATA_WEB
            ):
                logs += (
                    "loan_xid baris ke-%s -"
                    "disbursement tidak bisa dilakukan untuk loan ini\n" % idx
                )
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            try:
                with transaction.atomic():
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=LoanStatusCodes.CURRENT,
                        change_by_id=loan.customer.id,
                        change_reason="MF upload disbursement",
                    )

                    fund_transfer_ts = timezone.localtime(timezone.now())
                    loan.fund_transfer_ts = fund_transfer_ts
                    loan.save(update_fields=['fund_transfer_ts'])
                    axiata_customer_data = AxiataCustomerData.objects.filter(
                        loan_xid=loan.loan_xid
                    ).last()
                    if axiata_customer_data:
                        axiata_customer_data.disbursement_date = fund_transfer_ts.date()
                        axiata_customer_data.disbursement_time = fund_transfer_ts.time()
                        axiata_customer_data.save()

                    payment = loan.payment_set.all()
                    create_or_update_account_payments(payment, loan.account)
                    if loan.is_mf_std_loan():
                        partnership_mfsp_send_email_disbursement_notification_task.delay(loan.id)
                    else:
                        send_success_email_after_loan_220.delay(loan.id)

            except Exception as e:
                logs += "baris ke-%s terdapat kesalahan-%s\n" % (idx, e)
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            logs += "loan_xid baris ke-%s - berhasil diinput\n" % idx
            logs += "---" * 20 + "\n"
            ok_couter += 1

    return _render()


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def mf_webapp_csv_repayment_upload(request):
    template_name = 'object/merchant_financing_web_app/mf_web_app_repayment_upload.html'
    logs = ""
    upload_form = MFWebRepaymentUploadFileForm
    ok_couter = 0
    nok_couter = 0

    def _render():
        """lamda func to reduce code"""
        return render(
            request,
            template_name,
            {
                "title": "MF Webapp Repayment Upload",
                "form": upload_form,
                "logs": logs,
                "ok": ok_couter,
                "nok": nok_couter,
            },
        )

    if request.method == "POST":
        upload_form = upload_form(request.POST, request.FILES)
        if not upload_form.is_valid():
            for key in upload_form.errors:
                logs += upload_form.errors[key][0] + "\n"
                logs += "---" * 20 + "\n"
            return _render()

        file_ = upload_form.cleaned_data["file_field"]
        partner = str(upload_form.cleaned_data["partner_field"]).lower()
        extension = file_.name.split(".")[-1]

        if extension != "csv":
            logs = "Please upload the correct file type: CSV"
            messages.error(request, logs)
            return _render()

        freader = io.StringIO(file_.read().decode("utf-8"))
        reader = csv.DictReader(freader, delimiter=",")

        not_exist_headers = []
        for header in MF_WEB_APP_REPAYMENT_UPLOAD_HEADER:
            if header not in reader.fieldnames:
                not_exist_headers.append(header)

        if len(not_exist_headers) == len(MF_WEB_APP_REPAYMENT_UPLOAD_HEADER):
            logs = "CSV format is not correct"
            messages.error(request, logs)
            return _render()

        if not_exist_headers:
            logs = "CSV format is not correct. Headers not exists: %s" % not_exist_headers
            messages.error(request, logs)
            return _render()

        niks = set()
        loan_ids = set()
        application_ids = set()
        nik_dictionaries = {}

        for row in reader:
            invalid_nik_error_msg = mf_standard_verify_nik(row["nik"])

            if not invalid_nik_error_msg:
                niks.add(row["nik"])

                nik_dictionaries[row["nik"]] = {}

        partnership_customer_data_filter_dict = {'nik__in': niks}
        pii_partnership_customer_data_filter_dict = generate_pii_filter_query_partnership(
            PartnershipCustomerData, partnership_customer_data_filter_dict
        )
        pcd_ids = PartnershipCustomerData.objects.filter(
            **pii_partnership_customer_data_filter_dict
        ).values_list('id', flat=True)
        partnership_application_data = PartnershipApplicationData.objects.select_related(
            "application",
        ).filter(partnership_customer_data__id__in=pcd_ids)

        for pad in partnership_application_data:
            application_ids.add(pad.application.id)

        partner_loan_requests = PartnerLoanRequest.objects.select_related("loan",).filter(
            loan__application_id2__in=application_ids,
            loan__loan_status_id__gte=LoanStatusCodes.CURRENT,
        )

        for plr in partner_loan_requests:
            loan_ids.add(plr.loan.id)

        payments = (
            Payment.objects.select_related(
                "loan",
                "loan__product__product_line",
                "loan__account__partnership_customer_data",
                "loan__account__partnership_customer_data__partner",
                "loan__account__partnership_customer_data__customer",
            )
            .filter(
                loan__in=loan_ids,
                payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                loan__account__partnership_customer_data__id__in=pcd_ids,
            )
            .order_by("due_date", "payment_number", "cdate")
        )

        partnership_customer_data_ids = set()
        partner_ids = set()
        for payment in payments:
            partnership_customer_data_ids.add(payment.loan.account.partnership_customer_data.id)
            partner_ids.add(payment.loan.account.partnership_customer_data.partner.id)

        partnership_customer_data_list = PartnershipCustomerData.objects.filter(
            id__in=partnership_customer_data_ids
        )

        detokenize_partnership_customer_data_list = (
            partnership_detokenize_sync_primary_object_model_in_bulk(
                PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                partnership_customer_data_list,
                ['nik'],
            )
        )

        partner_query = Partner.objects.filter(id__in=partner_ids).all()
        detokenize_partner_list = partnership_detokenize_sync_kv_in_bulk(
            PiiSource.PARTNER,
            partner_query,
            ['name'],
        )

        for payment in payments:
            customer_xid = payment.loan.account.partnership_customer_data.customer.customer_xid
            partner_id = payment.loan.account.partnership_customer_data.partner.id
            pcd_nik = getattr(
                detokenize_partnership_customer_data_list.get(customer_xid), 'nik', ''
            )
            nik_dictionaries[pcd_nik].update(
                {
                    payment.id: {
                        "loan": payment.loan,
                        "partner": getattr(detokenize_partner_list.get(partner_id), 'name', ''),
                        "product_line": payment.loan.product.product_line.product_line_code,
                        "payment": payment,
                    }
                }
            )

        processed_nik = []

        freader.seek(0)
        reader.__init__(freader, delimiter=",")
        for idx, row in enumerate(reader, start=2):
            nik = row["nik"]

            invalid_nik_error_msg = mf_standard_verify_nik(nik)
            serializer = MFWebAppRepaymentUploadSerializer(data=row)

            if not serializer.is_valid():
                logs += "Baris ke-%s - %s\n" % (idx, serializer.errors)
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            if invalid_nik_error_msg:
                logs += "NIK %s baris ke-%s - %s\n" % (nik, idx, invalid_nik_error_msg)
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            if nik in processed_nik:
                logs += "NIK %s duplikat pada baris ke-%s\n" % (nik, idx)
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            if nik not in nik_dictionaries:
                logs += "NIK %s baris ke-%s tidak terdaftar\n" % (nik, idx)
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            payment_dicts = nik_dictionaries.get(nik)
            if not payment_dicts:
                logs += "NIK %s baris ke-%s tidak memiliki payment\n" % (nik, idx)
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            remainder_paid_amount = int(row["paid_amount"])
            if remainder_paid_amount <= 0:
                logs += "NIK %s baris ke-%s paid_amount harus lebih dari 0 (nol)\n" % (nik, idx)
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            processed_nik.append(nik)

            for payment_count, payment_id in enumerate(payment_dicts, start=1):
                if remainder_paid_amount <= 0:
                    break

                payment = payment_dicts[payment_id].get("payment")

                if (
                    partner != PartnerNameConstant.AXIATA_WEB
                    and payment_dicts[payment_id].get("partner") != partner
                ):
                    logs += "NIK %s - baris ke-%s partner tidak sesuai\n" % (nik, idx)
                    logs += "---" * 20 + "\n"
                    nok_couter += 1
                    break

                if (
                    partner == PartnerNameConstant.AXIATA_WEB
                    and payment_dicts[payment_id].get("product_line") != ProductLineCodes.AXIATA_WEB
                ):
                    logs += "NIK %s - baris ke-%s product_line tidak sesuai\n" % (nik, idx)
                    logs += "---" * 20 + "\n"
                    nok_couter += 1
                    break
                elif (
                    partner != PartnerNameConstant.AXIATA_WEB
                    and payment_dicts[payment_id].get("product_line")
                    != ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
                ):
                    logs += "NIK %s - baris ke-%s product_line tidak sesuai\n" % (nik, idx)
                    logs += "---" * 20 + "\n"
                    nok_couter += 1
                    break

                if remainder_paid_amount >= payment.due_amount and payment_count < len(
                    payment_dicts
                ):
                    paid_amount = payment.due_amount
                else:
                    paid_amount = remainder_paid_amount

                paid_date = serializer.validated_data["paid_date"]
                is_success, message = merchant_financing_repayment(
                    payment, paid_amount, paid_date, partner
                )

                if is_success:
                    logs += "NIK %s - payment_id %s baris ke-%s - berhasil diinput\n" % (
                        nik,
                        payment.id,
                        idx,
                    )
                    logs += "---" * 20 + "\n"
                    ok_couter += 1
                    remainder_paid_amount -= paid_amount
                else:
                    logs += "NIK %s - payment_id %s baris ke-%s terdapat kesalahan-%s\n" % (
                        nik,
                        payment.id,
                        idx,
                        message,
                    )
                    logs += "---" * 20 + "\n"
                    nok_couter += 1
                    continue

    return _render()


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def mf_webapp_csv_repayment_upload_per_loan(request):
    template_name = 'object/merchant_financing_web_app/mf_web_app_repayment_upload.html'
    logs = ""
    upload_form = MFWebRepaymentUploadFileForm
    ok_couter = 0
    nok_couter = 0

    def _render():
        return render(
            request,
            template_name,
            {
                "title": "MF Webapp Repayment Per Loan Upload",
                "form": upload_form,
                "logs": logs,
                "ok": ok_couter,
                "nok": nok_couter,
            },
        )

    if request.method == "POST":
        upload_form = upload_form(request.POST, request.FILES)
        if not upload_form.is_valid():
            for key in upload_form.errors:
                logs += upload_form.errors[key][0] + "\n"
                logs += "---" * 20 + "\n"
            return _render()

        file_ = upload_form.cleaned_data["file_field"]
        partner_field = str(upload_form.cleaned_data["partner_field"]).lower()
        extension = file_.name.split(".")[-1]

        if extension != "csv":
            logs = "Please upload the correct file type: CSV"
            messages.error(request, logs)
            return _render()

        freader = io.StringIO(file_.read().decode("utf-8"))
        reader = csv.DictReader(freader, delimiter=",")

        csv_header = MF_WEB_APP_REPAYMENT_PER_LOAN_UPLOAD_HEADER
        not_exist_headers = []
        for header in csv_header:
            if header not in reader.fieldnames:
                not_exist_headers.append(header)

        if len(not_exist_headers) == len(csv_header):
            logs = "CSV format is not correct"
            messages.error(request, logs)
            return _render()

        if not_exist_headers:
            logs = "CSV format is not correct. Headers not exists: %s" % not_exist_headers
            messages.error(request, logs)
            return _render()

        if partner_field != PartnerNameConstant.AXIATA_WEB:
            logs = "Currently only available for partner %s" % PartnerNameConstant.AXIATA_WEB
            messages.error(request, logs)
            return _render()

        loan_xids = []
        for row in reader:
            if row['loan_xid'].isnumeric():
                loan_xids.append(int(row['loan_xid']))

        loans = (
            Loan.objects.prefetch_related("payment_set", "partnerloanrequest_set")
            .select_related("customer", "account")
            .filter(loan_xid__in=loan_xids)
        )

        current_date = timezone.localtime(timezone.now()).date()

        partner_ids = set()
        data_dict = {}
        for loan in loans:
            payments = loan.payment_set.all()
            partner_loan_request = loan.partnerloanrequest_set.first()
            partner_ids.add(partner_loan_request.partner.id)
            data_dict[loan.loan_xid] = {
                "loan": loan,
                "payment": {
                    "total_due_amount": payments.aggregate(total=Sum('due_amount')).get('total'),
                    "total_principal": payments.aggregate(total=Sum('installment_principal')).get(
                        'total'
                    ),
                    "total_interest": payments.aggregate(total=Sum('installment_interest')).get(
                        'total'
                    ),
                    "total_late_fee": payments.aggregate(total=Sum('late_fee_amount')).get('total'),
                    "total_paid_principal": payments.aggregate(total=Sum('paid_principal')).get(
                        'total'
                    ),
                    "total_paid_interest": payments.aggregate(total=Sum('paid_interest')).get(
                        'total'
                    ),
                    "total_paid_late_fee": payments.aggregate(total=Sum('paid_late_fee')).get(
                        'total'
                    ),
                },
                "product_line_code": loan.get_application.product_line.product_line_code,
                "partner_loan_request": partner_loan_request,
            }

        partner_name_dict = {}
        partner_query = Partner.objects.filter(id__in=partner_ids).all()
        detokenize_partner_list = partnership_detokenize_sync_kv_in_bulk(
            PiiSource.PARTNER,
            partner_query,
            ['name'],
        )
        for loan in loans:
            partner_loan_request = loan.partnerloanrequest_set.first()
            partner_name = getattr(
                detokenize_partner_list.get(partner_loan_request.partner.id), 'name', ''
            )
            partner_name_dict[loan.loan_xid] = partner_name

        freader.seek(0)
        reader.__init__(freader, delimiter=",")
        processed_loan_xid = set()
        for idx, row in enumerate(reader, start=2):
            serializer = MFWebAppRepaymentUploadPerLoanSerializer(data=row)
            if not serializer.is_valid():
                logs += "Baris ke-%s - %s\n" % (idx, serializer.errors)
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            loan_xid = int(row["loan_xid"])
            log_msg = "[loan_xid: %s] [baris ke-%s] - " % (row["loan_xid"], idx)
            if not data_dict:
                logs += log_msg + "data loan tidak ditemukan\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if not partner_name_dict:
                logs += log_msg + "data partner tidak ditemukan\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            csv_paid_amount = int(row["paid_amount"])
            csv_paid_principal = int(row["paid_principal"])
            csv_paid_interest = int(row["paid_interest"])
            csv_paid_latefee = int(row["paid_latefee"])
            csv_paid_provision = int(row["paid_provision"])
            csv_paid_date_str = row["paid_date"]
            total_paid_amount_csv = (
                csv_paid_principal + csv_paid_provision + csv_paid_interest + csv_paid_latefee
            )

            loan = data_dict.get(loan_xid).get("loan")
            if not loan:
                logs += log_msg + "loan tidak ditemukan\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if loan_xid in processed_loan_xid:
                logs += log_msg + "tidak bisa memproses loan_xid yang sama dalam sekali upload\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if (
                loan.loan_status_id < LoanStatusCodes.CURRENT
                or loan.loan_status_id >= LoanStatusCodes.PAID_OFF
            ):
                logs += log_msg + "loan status tidak sesuai\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            partner_name = partner_name_dict.get(loan_xid)
            if not partner_name:
                logs += log_msg + "partner tidak ditemukan\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if partner_name != PartnerNameConstant.AXIATA_WEB:
                logs += log_msg + "partner tidak sesuai\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            product_line_code = data_dict.get(loan_xid).get("product_line_code")
            if not product_line_code:
                logs += log_msg + "product_line_code tidak ditemukan\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if product_line_code != ProductLineCodes.AXIATA_WEB:
                logs += log_msg + "product line tidak sesuai\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            try:
                csv_paid_date = datetime.strptime(csv_paid_date_str, "%Y-%m-%d").date()
                if csv_paid_date > current_date:
                    logs += log_msg + "paid_date tidak boleh melebihi tanggal sekarang \n"
                    logs += "---" * 20 + "\n"
                    nok_couter += 1
                    continue
            except Exception:
                logs += log_msg + "paid_date format tidak sesuai, e.g: 2024-12-31 \n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            payment = data_dict.get(loan_xid).get("payment")
            if not payment:
                logs += log_msg + "payment tidak ditemukan\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            total_due_amount = payment["total_due_amount"]
            total_due_principal = payment["total_principal"] - payment["total_paid_principal"]
            total_due_interest = payment["total_interest"] - payment["total_paid_interest"]
            total_due_late_fee = payment["total_late_fee"] - payment["total_paid_late_fee"]
            if total_due_amount == 0:
                logs += log_msg + "tidak mempunyai due_amount\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if (csv_paid_amount - total_paid_amount_csv) != 0:
                total_paid_amount_log = "(paid_principal+paid_provision+paid_interest+paid_latefee)"
                logs += log_msg + "paid_amount tidak sama dengan %s \n" % total_paid_amount_log
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if not csv_paid_amount > 0:
                logs += log_msg + "paid_amount tidak boleh kosong\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
            if csv_paid_principal > 0 and csv_paid_principal > total_due_principal:
                logs += (
                    log_msg
                    + "paid_principal lebih besar daripada yang harus dibayarkan (%s) \n"
                    % format(total_due_principal, ',d')
                )
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if csv_paid_interest > 0 and csv_paid_interest > total_due_interest:
                logs += (
                    log_msg
                    + "paid_interest lebih besar daripada yang harus dibayarkan (%s) \n"
                    % format(total_due_interest, ',d')
                )
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            if csv_paid_latefee > 0 and csv_paid_latefee > total_due_late_fee:
                logs += (
                    log_msg
                    + "paid_latefee lebih besar daripada yang harus dibayarkan (%s) \n"
                    % format(total_due_late_fee, ',d')
                )
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            partner_loan_request = data_dict.get(loan_xid).get("partner_loan_request")
            if not partner_loan_request:
                logs += log_msg + "partner_loan_request tidak ditemukan\n"
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue
            provision_amount = partner_loan_request.provision_amount
            paid_provision_amount = partner_loan_request.paid_provision_amount
            due_provision_amount = provision_amount - paid_provision_amount
            if csv_paid_provision > 0 and csv_paid_provision > due_provision_amount:
                logs += (
                    log_msg
                    + "paid_provision lebih besar daripada yang harus dibayarkan (%s) \n"
                    % format(int(due_provision_amount), ',d')
                )
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

            req_data = {
                "partner_name": partner_name,
                "paid_amount": csv_paid_amount,
                "paid_principal": csv_paid_principal,
                "paid_interest": csv_paid_interest,
                "paid_latefee": csv_paid_latefee,
                "paid_provision": csv_paid_provision,
                "due_provision_amount": due_provision_amount,
                "paid_date": csv_paid_date,
            }
            is_success, message = merchant_financing_repayment_per_loan(
                loan, partner_loan_request, req_data
            )
            if is_success:
                processed_loan_xid.add(loan_xid)
                logs += log_msg + "repayment berhasil diinput\n"
                logs += "---" * 20 + "\n"
                ok_couter += 1
            else:
                logs += log_msg + "terdapat kesalahan - %s\n" % (message)
                logs += "---" * 20 + "\n"
                nok_couter += 1
                continue

    return _render()


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def mf_webapp_resend_skrtp(request):
    url = reverse('bulk_upload:mf_webapp_resend_skrtp')

    if request.method == 'POST':
        form = request.POST
        loan_id = form.get('loan_id')
        loan = Loan.objects.get_or_none(id=loan_id)
        if not loan:
            messages.error(request, "Loan not found")
            return HttpResponseRedirect(url)
        if loan.loan_status_id != LoanStatusCodes.INACTIVE:
            messages.error(request, "Loan status not 210")
            return HttpResponseRedirect(url)

        partner_loan_request = loan.partnerloanrequest_set.last()
        if not partner_loan_request:
            messages.error(request, "PartnerLoanRequest not found")
            return HttpResponseRedirect(url)

        interest_rate = partner_loan_request.interest_rate * 100
        loan_request_date = partner_loan_request.loan_request_date.strftime('%d/%m/%Y')
        err_msg = send_email_skrtp(
            loan_id=loan.id,
            interest_rate=interest_rate,
            loan_request_date=loan_request_date,
            timestamp=datetime.now(),
        )
        if err_msg:
            messages.error(request, err_msg)
            return HttpResponseRedirect(url)

        messages.success(request, "SKRTP has been sent!")

    elif request.method == 'GET':
        template_name = 'object/merchant_financing_web_app/mf_web_resend_skrtp.html'
        return render(request, template_name)

    return HttpResponseRedirect(url)
