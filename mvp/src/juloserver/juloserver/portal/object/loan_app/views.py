from __future__ import print_function
from builtins import zip
from builtins import str
from builtins import range
import json
import operator

import datetime
import logging

from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.conf import settings

from django.utils import timezone
from django.http import HttpResponse
from django.shortcuts import render
from django.shortcuts import get_object_or_404, redirect
from django.core.urlresolvers import reverse
from django.http import Http404
from django.db.models import Q
from django.views.generic import ListView, DetailView

from juloserver.julo.utils import construct_remote_filepath, upload_file_to_oss

# set decorator for login required
from object import julo_login_required, julo_login_required_exclude
from object import julo_login_req_group_class, julo_login_required_multigroup

# from account.models import UserActivation
from juloserver.julo.models import (
    Application,
    StatusLookup,
    Image,
    FaceRecognition,
    AwsFaceRecogLog,
    Loan,
    SepulsaTransaction,
    Document,
    PaymentMethod,
)
from juloserver.julo.services import process_application_status_change, is_bank_name_validated
from juloserver.julo.statuses import StatusManager
from juloserver.julo.tasks import upload_image
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes

from .forms import ImageUploadForm, StatusChangesForm, MultiImageUploadForm
from .forms import NoteForm
from .tasks import drop_after_successful_upload

from dashboard.functions import get_selected_role
from scraped_data.forms import ApplicationSearchForm
from functools import reduce
from babel.dates import format_date
from juloserver.julo.utils import display_rupiah
from juloserver.loan.services.sphp import get_loan_type_sphp_content
from juloserver.grab.services.services import get_sphp_context_grab
from django.shortcuts import redirect
from juloserver.followthemoney.constants import DocumentTypes
from juloserver.partnership.models import LivenessImage

logger = logging.getLogger(__name__)


PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class ApplicationDataListView(ListView):
    model = Application
    paginate_by = 50  # get_conf("PAGINATION_ROW")
    template_name = 'object/loan_app/list.html'


    def http_method_not_allowed(self, request, *args, **kwargs):
        # print "http_method_not_allowed"
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        # print "get_template_names"
        return ListView.get_template_names(self)

    def get_queryset(self):
        # print "get_queryset"
        self.qs = super(ApplicationDataListView, self).get_queryset()

        # exclude ICare client
        self.qs = self.qs.exclude(partner__name='icare')

        self.qs = self.qs.order_by('-cdate')

        self.err_message_here = None
        self.tgl_range = None
        self.tgl_start = None
        self.tgl_end = None
        self.status_app = None
        self.search_q = None
        self.status_now = None

        # print "self.request.GET: ", self.request.GET
        if self.request.method == 'GET':
            self.tgl_range = self.request.GET.get('datetime_range', None)
            self.status_app = self.request.GET.get('status_app', None)
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.status_now = self.request.GET.get('status_now', None)

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_,
                    [
                        Q(**{('%s__icontains' % 'fullname'): self.search_q}),
                        Q(**{('%s__icontains' % 'ktp'): self.search_q}),
                        Q(**{('%s__icontains' % 'mobile_phone_1'): self.search_q}),
                        Q(**{('%s__icontains' % 'id'): self.search_q}),
                        Q(**{('%s__icontains' % 'email'): self.search_q})
                    ]))

            if(self.status_app):
                self.qs = self.qs.filter(application_status__status_code=self.status_app)

            if(self.status_now):
                # print "OKAY STATUS NOW : ", self.status_now
                if(self.status_now=='True'):
                    # print "HARI INI"
                    startdate = datetime.datetime.today()
                    startdate = startdate.replace(hour=0, minute=0, second=0)
                    enddate = startdate + datetime.timedelta(days=1)
                    enddate = enddate - datetime.timedelta(seconds=1)
                    self.qs = self.qs.filter(cdate__range=[startdate, enddate])
                else:
                    _date_range = self.tgl_range.split('-')
                    if(_date_range[0].strip()!= 'Invalid date'):
                        _tgl_mulai = datetime.datetime.strptime(_date_range[0].strip(),"%d/%m/%Y %H:%M")
                        _tgl_end = datetime.datetime.strptime(_date_range[1].strip(), "%d/%m/%Y %H:%M")
                        # print "BEBAS"
                        if(_tgl_end > _tgl_mulai):
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.err_message_here = "Format Tanggal tidak valid"
        else:
            print("else request GET")

        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(ApplicationDataListView, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = ApplicationSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = ApplicationSearchForm()
        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        try:
            context['STATUS_ORDER'] = showStatusOrder(self.kwargs['status_order'])
        except:
            context['STATUS_ORDER'] = "Seluruh Data"
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        # print "parameters: ", parameters
        context['parameters'] = parameters
        return context

    def get(self, request, *args, **kwargs):
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super(ApplicationDataListView, self).render_to_response(context, **response_kwargs)
        return rend_here

from .utils import get_list_history

@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class ApplicationDetailView(DetailView):
    model = Application
    template_name='object/loan_app/details.html'

    def get_context_data(self, **kwargs):
        history_note_list = get_list_history(self.get_object())

        context = super(ApplicationDetailView, self).get_context_data(**kwargs)
        context['now'] = timezone.now()
        context['history_note_list'] = history_note_list
        return context

# ----------------------------- Seluruh data END ---------------------------------------


# ----------------------------- SPHP START ------------------------------------
@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
    'document_verifier', 'bo_credit_analyst'])
class LoanAppSPHPListView(ListView):
    model = Application
    paginate_by = 10 #get_conf("PAGINATION_ROW") #= 20
    # template_name = 'object/loan_app/list.html'

    def get_queryset(self):
        qs = super(LoanAppSPHPListView, self).get_queryset().with_sphp_info()
        qs = qs.order_by('-cdate')

        # qs = qs.filter(application_status__status_code__gte = StatusLookup.VERIFICATION_CALLS_SUCCESSFUL_CODE)

        self.q = self.request.GET.get('q', '').strip()
        # Fetching information for display
        if isinstance(self.q, str) and self.q:
            qs = qs.filter(reduce(operator.or_,
                [
                    Q(**{('%s__icontains' % 'fullname'): self.q}),
                    Q(**{('%s__icontains' % 'ktp'): self.q}),
                    Q(**{('%s__icontains' % 'mobile_phone_1'): self.q}),
                    Q(**{('%s__icontains' % 'id'): self.q}),
                    Q(**{('%s__icontains' % 'email'): self.q}),
                    Q(**{('%s__icontains' % 'application_status__status_code'): self.q})
                ]))

        return qs

    def get_context_data(self, **kwargs):
        context = super(LoanAppSPHPListView, self).get_context_data(**kwargs)
        self.q = self.request.GET.get('q', '').strip()
        context['extra_context'] = {'q': self.q},
        context['results_per_page'] = self.paginate_by
        return context


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
    'document_verifier', 'bo_credit_analyst'])
class LoanApplicationSPHPView(DetailView):
    model = Application
    # template_name='object/loan_app/detail_sphp.html'

    def get_context_data(self, **kwargs):
        context = super(LoanApplicationSPHPView, self).get_context_data(**kwargs)
        context['product_line_BRI'] = ProductLineCodes.bri()
        context['product_line_GRAB'] = ProductLineCodes.grab()
        context['now'] = timezone.now()
        context['bank_niaga'] = ['BANK CIMB NIAGA', 'BANK NIAGA', 'CIMB NIAGA', 'BANK CIMB NIAGA, Tbk',
                            'Bank CIMB Niaga', 'Bank Niaga', 'CIMB Niaga', 'Bank CIMB Niaga, Tbk']
        self.object = self.get_object()
        if self.object.partner:
            partnerreferral = self.object.customer.partnerreferral_set.filter(pre_exist=False).last()
            context['partner_account_id'] = partnerreferral.partner_account_id
            context['account_doku_julo'] = settings.DOKU_ACCOUNT_ID
        product_line = self.object.product_line.product_line_code
        bank_name_validated = is_bank_name_validated(self.object)
        if product_line in ProductLineCodes.mtl():
            check_point_lists = [
                'menandatangani SPHP secara elektronik di dalam aplikasi.',
                'merekam pernyataan dengan lengkap (kalau tidak lengkap, pencairan akan terhambat)'
            ]
            if not bank_name_validated:
                check_point_lists.insert(0, "melakukan validasi akun rekening bank Anda di Aplikasi JULO")
            context['check_point_lists'] = check_point_lists
        elif product_line in ProductLineCodes.stl():
            context['validate_bank_account'] = bank_name_validated
        return context


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
                                 'document_verifier', 'bo_credit_analyst'])
class LoanJuloOneSphpDetailView(DetailView):
    model = Loan

    def get_context_data(self, **kwargs):
        loan = self.object
        lender = loan.lender
        pks_number = '1.JTF.201707'
        if lender and lender.pks_number:
            pks_number = lender.pks_number
        sphp_date = loan.sphp_sent_ts
        application = loan.account.application_set.last()
        loan_type = get_loan_type_sphp_content(loan)
        context = {
            'loan': loan,
            'application': application,
            'dob': format_date(application.dob, 'dd-MM-yyyy', locale='id_ID'),
            'full_address': application.full_address,
            'loan_amount': display_rupiah(loan.loan_amount),
            'late_fee_amount': display_rupiah(loan.late_fee_amount),
            'julo_bank_name': loan.julo_bank_name,
            'julo_bank_code': '-',
            'julo_bank_account_number': loan.julo_bank_account_number,
            'date_today': format_date(sphp_date, 'd MMMM yyyy', locale='id_ID'),
            'background_image': settings.SPHP_STATIC_FILE_PATH + 'julo-a-4@3x.png',
            'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
            'agreement_letter_number': pks_number,
            'loan_type': loan_type
        }

        if 'bca' not in loan.julo_bank_name.lower():
            payment_method = PaymentMethod.objects.filter(
                virtual_account=loan.julo_bank_account_number).first()
            if payment_method:
                context['julo_bank_code'] = payment_method.bank_code
        payments = loan.payment_set.all().order_by('id')
        for payment in payments:
            payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
            payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)
        context['payments'] = payments
        context['max_total_late_fee_amount'] = display_rupiah(loan.max_total_late_fee_amount)
        context['provision_fee_amount'] = display_rupiah(loan.provision_fee())
        context['interest_rate'] = '{}%'.format(loan.interest_percent_monthly())
        return context


@julo_login_required
@julo_login_required_multigroup(
    ['admin_full', 'bo_data_verifier', 'bo_sd_verifier', 'document_verifier', 'bo_credit_analyst']
)
class LoanJuloOneSKRTPDetailView(DetailView):
    model = Loan

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        doc = Document.objects.filter(
            document_source=self.object.pk, document_type=DocumentTypes.SKRTP_JULO
        ).last()
        if doc and doc.document_url:
            return redirect(doc.document_url)

        raise Http404("SKRTP document not found")


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
                                 'document_verifier', 'bo_credit_analyst'])
class LoanGrabSphpDetailView(DetailView):
    model = Loan

    def get_context_data(self, **kwargs):
        loan = self.object
        application = loan.account.application_set.last()
        context = get_sphp_context_grab(loan.id)
        context['application'] = application
        context['loan'] = loan
        return context

# ----------------------------- SPHP END ------------------------------------

# ----------------------------- Image Verification START ------------------------------------
@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
    'document_verifier', 'bo_credit_analyst'])
class LoanApplicationView(ListView):
    model = Application
    paginate_by = 10 #get_conf("PAGINATION_ROW") #= 20

    def get_queryset(self):
        qs = super(LoanApplicationView, self).get_queryset()
#         qs = qs.filter(application_status__status_code__lte = StatusLookup.APPLICATION_RESUBMISSION_REQUESTED_CODE)
        qs = qs.order_by('-cdate')

        self.q = self.request.GET.get('q', '').strip()
        # Fetching information for display
        if isinstance(self.q, str) and self.q:
            qs = qs.filter(reduce(operator.or_,
                [
                    Q(**{('%s__icontains' % 'fullname'): self.q}),
                    Q(**{('%s__icontains' % 'ktp'): self.q}),
                    Q(**{('%s__icontains' % 'mobile_phone_1'): self.q}),
                    Q(**{('%s__icontains' % 'id'): self.q}),
                    Q(**{('%s__icontains' % 'email'): self.q}),
                    Q(**{('%s__icontains' % 'application_status__status_code'): self.q})
                ]))

        return qs

    def get_context_data(self, **kwargs):
        context = super(LoanApplicationView, self).get_context_data(**kwargs)
        self.q = self.request.GET.get('q', '').strip()
        context['extra_context'] = {'q': self.q},
        context['q_value'] = self.q
        context['results_per_page'] = self.paginate_by
        return context

@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
    'document_verifier', 'bo_credit_analyst'])
class LoanApplicationDetailView(DetailView):
    model = Application

    def get_context_data(self, **kwargs):
        self.object = self.get_object()
        context = super(LoanApplicationDetailView, self).get_context_data(**kwargs)
        context['now'] = timezone.now()
        context['image_list'] = Image.objects.filter(image_source = self.object.id)
        # context['application_id'] = self.object.id
        # is_partnership_leadgen
        is_partnership_leadgen = False
        list_image_partnership_liveness = []
        if self.object.is_partnership_leadgen():
            from juloserver.partnership.services.services import (
                partnership_get_image_liveness_result,
            )

            application_id = self.object.id
            is_partnership_leadgen = True
            list_image_partnership_liveness = partnership_get_image_liveness_result(application_id)
        context['is_partnership_leadgen'] = is_partnership_leadgen
        context['list_image_partnership_liveness'] = list_image_partnership_liveness
        return context


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
    'document_verifier', 'bo_credit_analyst'])
class ImageDetailView(DetailView):
    model = Image
    template_name='object/loan_app/roles/detail_image_edit.html'

    def get_context_data(self, **kwargs):
        if get_selected_role(self.request.user) == 'admin_full':
            template_name='object/loan_app/admin_full/detail_image_edit.html'

        self.object = self.get_object()
        context = super(ImageDetailView, self).get_context_data(**kwargs)
        context['now'] = timezone.now()
        return context


@julo_login_required
@julo_login_required_multigroup(
    ['admin_full', 'bo_data_verifier', 'bo_sd_verifier', 'document_verifier', 'bo_credit_analyst']
)
class PartnershipLivenessImageDetailView(DetailView):
    model = LivenessImage
    template_name = 'object/loan_app/roles/detail_image_partnership_liveness_edit.html'

    def get_context_data(self, **kwargs):
        if get_selected_role(self.request.user) == 'admin_full':
            template_name = 'object/loan_app/admin_full/detail_image_edit.html'
        context = super(PartnershipLivenessImageDetailView, self).get_context_data(**kwargs)
        application_id = self.kwargs.get('application_id')
        context['application'] = Application.objects.filter(pk=application_id).last()
        context['now'] = timezone.now()
        return context


@julo_login_required
@julo_login_required_multigroup([
    'admin_full', 'bo_data_verifier', 'bo_sd_verifier', 'document_verifier'
])
def app_image_upload(request, application_id):
    # check if there is Application which matches the application_id (if not then display 404)
    app_object = get_object_or_404(Application, id=application_id)

    template_name ='object/loan_app/roles/image_upload.html'
    if get_selected_role(request.user) == 'admin_full':
        template_name = 'object/loan_app/admin_full/image_upload.html'

    SUFFIX_OPS = 'ops'

    obj_image = Image()
    obj_image.image_source = app_object.id
    if request.method == 'POST':
        form = ImageUploadForm(request.POST, request.FILES, instance=obj_image)
        if form.is_valid():
            # image_source = form.cleaned_data['image_source']
            # 'cdate', 'udate', 'application', 'is_readable', 'image_type', 'url'
            image_save = form.save()

            try:
                dest_name = construct_remote_filepath(app_object.customer.id, image_save, SUFFIX_OPS)
                upload_file_to_oss(
                    settings.OSS_MEDIA_BUCKET,
                    settings.MEDIA_ROOT + '/' + image_save.image.name,
                    dest_name)
                image_save.url = dest_name
                image_save.image_type = '%s_%s' % (image_save.image_type, SUFFIX_OPS)
                image_save.save(update_fields=["url", "image_type"])

                # drop file from current server
                drop_after_successful_upload.delay(image_save)

                url = reverse('loan_app:detail_img_verification', kwargs={'pk': app_object.id })
                return redirect(url)
            except Exception as e:
                logger.debug("Uploading to s3 with folder structure = %s" % e)
                redirect(Http404)
    else:
        form = ImageUploadForm(instance=obj_image)

    return render(
        request,
        template_name,
        {
            'form': form,
            'app_object': app_object
        }
    )


from .services import ImageListIndex


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
    'document_verifier'])
def app_multi_image_upload(request, application_id):
    # check if there is Application which matches the application_id (if not then display 404)
    app_object = get_object_or_404(Application, id=application_id)

    template_name ='object/loan_app/roles/multi_image_upload.html'
    SUFFIX_OPS = 'ops'

    if request.method == 'POST':
        form = MultiImageUploadForm(request.POST, request.FILES)
        # print " VALID: ", form.is_valid()
        if form.is_valid():
            image_source = form.cleaned_data['attachments']

            arr_image_type = []
            for index_key in range(10):
                key_image = "image_type_%d" % (index_key+1)
                arr_image_type.append(form.cleaned_data[key_image])
            arr_image_type = ImageListIndex(arr_image_type).output()

            index = 0
            for each in image_source:
                image_type_selected = arr_image_type[index]

                obj_image = Image()
                obj_image.image_source = app_object.id
                obj_image.image_type = '%s_%s' % (image_type_selected, SUFFIX_OPS)
                obj_image.save()
                obj_image.image.save(obj_image.full_image_name(each.name), each)

                upload_image.apply_async((obj_image.id,), countdown=3)

                index += 1

            url = reverse('loan_app:detail_img_verification', kwargs={'pk': app_object.id })
            return redirect(url)

        else:
            err_msg = """
                Upload File tidak boleh kosong, Maximum Upload dokumen/gambar hanya 10 File dan maxSize 10MB per-file!!!
            """
            logger.info({
                'app_id': app_object.id,
                'error': err_msg
            })
            messages.error(request, err_msg)

    else:
        form = MultiImageUploadForm()
        image_hide_list = {

        }

    return render(request,
        template_name,
        {
            'form':form ,
            'app_object': app_object,
            }
        )
# ----------------------------- Image Verification END ------------------------------------

# ----------------------------- Change Status START ---------------------------------------
@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
    'document_verifier'])
class StatusChangesView(ApplicationDataListView):
    template_name ='object/loan_app/roles/list_status_changes.html'


from itertools import chain
from operator import attrgetter
from juloserver.julo.models import ApplicationHistory, ApplicationNote
from django.db.models import F, Value, CharField

@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class StatusChangesDetailView(DetailView):
    model = Application
    template_name='object/loan_app/roles/detail_status_changes.html'

    def get_context_data(self, **kwargs):
        self.object = self.get_object()
        app_histories = self.object.applicationhistory_set.all().annotate(
            type_data=Value('Status Change', output_field=CharField()))
        app_notes = ApplicationNote.objects.filter(application_id=self.object.id).annotate(
            type_data=Value('Notes', output_field=CharField()))

        # result_list = list(chain(app_histories, app_notes))
        history_note_list = sorted(
            chain(app_histories, app_notes),
            key=lambda instance: instance.cdate, reverse=True)

        context = super(StatusChangesDetailView, self).get_context_data(**kwargs)
        context['now'] = timezone.now()
        context['history_note_list'] = history_note_list
        return context


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def update_app_status(request, pk):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    app_obj = get_object_or_404(Application, id=pk)
    status_current = app_obj.application_status

    template_name ='object/loan_app/roles/update_status_changes.html'

    if request.method == 'POST':
        form = StatusChangesForm(status_current, app_obj.id, request.POST)
        print(form.is_valid())
        if form.is_valid():
            status_to = form.cleaned_data['status_to']
            reason = form.cleaned_data['reason']
            notes = form.cleaned_data['notes']

            reason_arr = [item_reason.reason for item_reason in reason ]
            reason = ", ".join(reason_arr)

            logger.info({
                'status_to': status_to,
                'reason': reason,
                'notes': notes
            })

            # TODO: call change_status_backend mapping
            ret_status = process_application_status_change(
                app_obj.id, status_to.status_code, reason, note=notes)
            print("ret_status: ", ret_status)
            if (ret_status):
                #form is sukses
                url = reverse('loan_app:detail_status_changes', kwargs={'pk': app_obj.id })
                return redirect(url)
            else:
                #there is an error
                err_msg = """
                    Ada Kesalahan di Backend Server!!!, Harap hubungi Administrator
                """
                logger.info({
                    'app_id': app_obj.id,
                    'error': "Ada Kesalahan di Backend Server with change_application_state !!!."
                })
                messages.error(request, err_msg)

    else:
        form = StatusChangesForm(status_current, app_obj.id)

    return render(request,
        template_name,
            {
            'form':form ,
            'app_obj': app_obj,
            'status_current': status_current,
            'datetime_now': timezone.now(),
            }
        )

@csrf_protect
def populate_reason(request):
    # print "f(x) populate_reason INSIDE"

    if request.method == 'GET':

        application = None
        status_to = int(request.GET.get('status_code'))
        application_id = request.GET.get('application_id')
        # status = StatusManager.get_or_none(status_to)
        dashed_change_reason = StatusManager.dashed_change_reason_statuses()
        status = StatusLookup.objects.get_or_none(status_code=status_to)
        face_recognition = FaceRecognition.objects.get_or_none(
            feature_name='face_recognition',
            is_active=True
        )
        response_data = {}
        if status:
            order_by_field = 'id'
            success_message = 'successful!'
            if status.status_code == ApplicationStatusCodes.APPLICATION_DENIED:
                order_by_field = 'reason'
            change_reasons_from_db = status.changereason_set.all().order_by(order_by_field)

            if application_id:
                application = Application.objects.get_or_none(pk=int(application_id))

            if status_to in dashed_change_reason:
                reason_list = list([x.reason.split("-")[0] for x in change_reasons_from_db])
            else:
                reason_list = list([x.reason for x in change_reasons_from_db])
                # reason_list= status.change_reasons
            if application:
                if application.is_merchant_flow() and \
                        status.status_code == ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL:
                    mf_reason = 'Merchant Financing Application'
                    return HttpResponse(
                        json.dumps({
                            'result': success_message,
                            'reason_list': [(mf_reason, mf_reason)]
                        }),
                        content_type="application/json"
                    )
                indexed_face = AwsFaceRecogLog.objects.filter(application=application).last()
                if face_recognition and \
                        indexed_face and \
                        not indexed_face.is_quality_check_passed and \
                        application.status == ApplicationStatusCodes.CALL_ASSESSMENT and\
                        status.status_code == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED:
                    reason_list = [value for value in reason_list if "Selfie needed" in value]

            response_data['result'] = success_message
            response_data['reason_list'] = list(zip(reason_list, reason_list ))
        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({"nothing to see": "this isn't happening",
                'result': "not ok"}),
            content_type="application/json"
        )
# ----------------------------- Change Status END ---------------------------------------


# ----------------------------- Verification Check list START  ------------------------------------
@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
    'document_verifier'])
class VerificationCheckListView(ApplicationDataListView):
    template_name ='object/loan_app/roles/list_verification_check.html'


from juloserver.julo.models import ApplicationDataCheck
from .services import create_data_verification_checks
from .forms import ValidationCheckForm
from django.db import transaction


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def update_verification_check(request, pk):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    app_obj = get_object_or_404(Application, id=pk)

    template_name ='object/loan_app/roles/cr_up_verification_check.html'

    # check the status list is exists on application_data_check
    app_check_cnt = ApplicationDataCheck.objects.filter(application_id=app_obj.id).count()
    if(app_check_cnt==0):
        # create if doesnot exists
        create_data_verification_checks(app_obj)
    elif(app_check_cnt==68):
        # there is an update from 68 list become 71, this is only insert new updates
        create_data_verification_checks(app_obj, 68)

    # get verification check list
    app_check_queryset = ApplicationDataCheck.objects.filter(application_id=app_obj.id)

    if request.method == 'POST':
        print("::POST::")
        form = ValidationCheckForm(app_check_queryset, request.POST)
        print(form.is_valid())
        if form.is_valid():
            print("Form is valid")
            logger.info({
                'form': form,
            })

            with transaction.atomic():
                for check_obj in app_check_queryset:
                    _clean_data = form.cleaned_data['check_%d' % check_obj.sequence]
                    # print "%d : %s" % (check_obj.sequence, _clean_data)
                    if check_obj.check_type == 1:
                        if check_obj.is_okay != _clean_data:
                            check_obj.is_okay = _clean_data
                    elif check_obj.check_type == 2:
                        if check_obj.text_value != _clean_data:
                            check_obj.text_value = _clean_data
                    elif check_obj.check_type == 3:
                        if check_obj.number_value != _clean_data and _clean_data and _clean_data!='':
                            check_obj.number_value = _clean_data
                    else:
                        if check_obj.text_value != _clean_data:
                            check_obj.text_value = _clean_data
                        if _clean_data and _clean_data!='':
                            check_obj.number_value = int(str(_clean_data).replace(' ','').replace('.','').replace(',',''))
                    check_obj.save()

            url = reverse('loan_app:detail_verification_check', kwargs={'pk': app_obj.id })
            return redirect(url)
        else:
            print("Form is not valid")

    else:
        print("::GET::")
        form = ValidationCheckForm(app_check_queryset)

    return render(request,
        template_name,
            {
            'form':form ,
            'app_obj': app_obj,
            'app_check_queryset': app_check_queryset,
            'datetime_now': timezone.now(),
            'number_seq_list': (18, 19, 20, 21, 22, 23, 24, 25, 53, ),
            }
        )


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class VerificationCheckDetailView(DetailView):
    model = Application
    template_name='object/loan_app/roles/detail_verification_check.html'

    def get_context_data(self, **kwargs):
        self.object = self.get_object()
        print("self.object : ", self.object)
        context = super(VerificationCheckDetailView, self).get_context_data(**kwargs)
        context['now'] = timezone.now()
        context['rupiah_sequence'] = (59, 61, 62, 63, 64,)
        context['option_list'] = ValidationCheckForm.GPS_RANGE
        return context


# ----------------------------- Verification Check list END ---------------------------------------


# ----------------------------- Add Notes START ---------------------------------------

from juloserver.julo.models import ApplicationNote

@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def create_app_note(request, pk):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    app_obj = get_object_or_404(Application, id=pk)
    status_current = app_obj.application_status
    template_name ='object/loan_app/roles/create_note.html'

    if request.method == 'POST':
        form = NoteForm(request.POST)
        user_id = request.user.id if request.user else None
        print(form.is_valid())
        if form.is_valid():
            notes = form.cleaned_data['notes']

            logger.info({
                'notes': notes
            })

            if notes:
                application_note = ApplicationNote.objects.create(
                    note_text=notes,
                    application_id=app_obj.id,
                    added_by_id=user_id,
                )
                logger.info(
                    {
                        'application_note': application_note,
                    }
                )

                url = reverse('loan_app:detail_app', kwargs={'pk': app_obj.id })
                return redirect(url)

    else:
        form = NoteForm()

    return render(request,
        template_name,
            {
            'form':form ,
            'app_obj': app_obj,
            'status_current': status_current,
            'datetime_now': timezone.now(),
            }
        )
# ----------------------------- Change Status END ---------------------------------------

