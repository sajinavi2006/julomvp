from __future__ import print_function
from future import standard_library

from juloserver.account_payment.services.account_payment_related import (
    is_crm_sms_email_locking_active
)

standard_library.install_aliases()
from builtins import zip
from builtins import str
import json
import operator
import re
import math
import csv
import io

from dateutil import tz
from dateutil.parser import parse
import logging

from datetime import date, datetime
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.conf import settings

from django.utils import timezone
from django.http import (
    HttpResponse,
    HttpResponseForbidden,
)
from django.http import HttpResponseBadRequest
from django.http import HttpResponseNotAllowed
from django.http import HttpResponseNotFound
from django.http import JsonResponse
from django.template import RequestContext
from django.shortcuts import render_to_response, render
from django.shortcuts import get_object_or_404, redirect
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User, Group
from django.http import Http404
from django.db.models import Q, F, ExpressionWrapper, IntegerField, Case, When
from django.views.generic import ListView
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core import serializers
from django.db import transaction
from wsgiref.util import FileWrapper
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned

from juloserver.collection_vendor.constant import CollectionVendorAssignmentConstant
from juloserver.collection_vendor.models import CollectionVendorAssignment, AgentAssignment
from juloserver.collection_vendor.services import display_account_movement_history, get_current_sub_bucket
from juloserver.julo.utils import check_email, format_e164_indo_phone_number, display_rupiah

# set decorator for login required
from object import julo_login_required, julo_login_required_exclude
from object import julo_login_req_group_class, julo_login_required_multigroup

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.clients import get_julo_autodialer_client
from juloserver.julo.constants import (AgentAssignmentTypeConst,
                                       FeatureNameConst,
                                       PaymentConst)
from juloserver.julo.exceptions import SmsNotSent, EmailNotSent

from juloserver.julo.partners import PartnerConstant

from juloserver.julo.banks import BankManager

from juloserver.julo.models import (Application,
                                    AutoDialerRecord,
                                    ApplicationNote,
                                    Bank,
                                    CollectionAgentAssignment,
                                    CustomerWalletHistory,
                                    CustomerWalletNote,
                                    EmailHistory,
                                    FacebookData,
                                    FeatureSetting,
                                    Image,
                                    Loan,
                                    Partner,
                                    Payment,
                                    PaymentEvent,
                                    PaymentMethod,
                                    PaymentNote,
                                    RepaymentTransaction,
                                    RobocallTemplate,
                                    Skiptrace,
                                    SkiptraceHistory,
                                    SkiptraceResultChoice,
                                    SmsHistory,
                                    StatusLookup,
                                    VoiceRecord,
                                    PTP,
                                    CootekRobocall)
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_payment_status_change
from juloserver.julo.services import process_partial_payment
from juloserver.julo.services import send_custom_sms_payment_reminder
from juloserver.julo.services import send_custom_email_payment_reminder
from juloserver.julo.services import get_data_application_checklist_collection
from juloserver.julo.services import update_skiptrace_score
from juloserver.julo.services import process_change_due_date
from juloserver.julo.services import update_payment_installment
from juloserver.julo.services import change_due_dates
from juloserver.julo.services import (ptp_create,
                                      get_wa_message_is_5_days_unreachable,
                                      get_wa_message_is_broken_ptp_plus_1)
from juloserver.julo.services2.agent import convert_usergroup_to_agentassignment_type
from juloserver.julo.services2.payment_event import PaymentEventServices
from juloserver.julo.services2.primo import delete_from_primo_payment
from juloserver.julo.services2 import get_agent_service
from juloserver.julo.statuses import (ApplicationStatusCodes, LoanStatusCodes)
from julo_status.models import ReasonStatusAppSelection
from juloserver.julo.services2.experiment import check_cootek_experiment
from juloserver.julo.tasks import send_sms_update_ptp
from loan_app.forms import ImageUploadForm, MultiImageUploadForm

from juloserver.warning_letter.services import get_current_mtl_wl_web_url
from juloserver.minisquad.tasks2 import delete_paid_payment_from_intelix_if_exists_async
from juloserver.collection_vendor.task import assign_agent_for_bucket_5
from juloserver.portal.object.loan_app.constants import ImageUploadType
from .services import check_change_due_date_active
from .services import check_first_installment_btn_active
from .utils import (get_list_history,
                    get_app_list_history,
                    get_wallet_list_note,
                    payment_parse_pass_due,
                    get_list_email_sms,
                    payment_filter_search_field,
                    account_payment_filter_search_field)
from .forms import StatusChangesForm
from .forms import PaymentSearchForm
from .forms import PaymentForm
from .forms import RobocallTemplateForm
from loan_status.forms import NewPaymentInstallmentForm
from payment_status.models import GhostPayment, CsvFileManualPaymentRecord
from .serializers import SkiptraceSerializer, SkiptraceHistorySerializer, \
    GrabSkiptraceHistorySerializer

from dashboard.functions import get_selected_role
from dashboard.constants import JuloUserRoles


from app_status.forms import ApplicationForm
from app_status.forms import ApplicationSelectFieldForm
from app_status.utils import ExtJsonSerializer
from payment_status.services import create_reversal_transaction
from .functions import payment_lock_list, MAX_COUNT_LOCK_PAYMENT, get_user_lock_count, get_payment_lock_count
from .functions import check_lock_payment, lock_by_user, unlocked_payment, role_allowed, get_lock_status
from .models import PaymentLocked, PaymentLockedMaster
from .constants import PAYMENT_EVENT_CONST

from juloserver.collectionbucket.services import get_agent_service_for_bucket
from juloserver.collectionbucket.models import CollectionAgentTask
from juloserver.julo.clients import get_julo_centerix_client
from juloserver.minisquad.models import CollectionHistory, CollectionSquad
from juloserver.minisquad.constants import SquadNames
from juloserver.minisquad.services import get_oldest_payment_ids_loans, check_customer_bucket_type
from juloserver.minisquad.tasks import trigger_insert_col_history

from .utils import get_ptp_max_due_date, get_acc_pmt_list_history
from juloserver.payback.models import WaiverTemp
from juloserver.payback.services.waiver import (get_remaining_late_fee,
                                                get_remaining_interest,
                                                get_remaining_principal)
from juloserver.loan_refinancing.models import LoanRefinancing, LoanRefinancingRequest
from juloserver.loan_refinancing.constants import LoanRefinancingStatus
from juloserver.loan_refinancing.services.customer_related import get_refinancing_status_display
from juloserver.account_payment.models import AccountPayment

from functools import reduce

from account_payment_status.constants import SearchCategory, SpecialConditions
from juloserver.apiv3.models import ProvinceLookup
from juloserver.whatsapp.services import get_mtl_whatsapp_collection_text
from juloserver.account_payment.models import AccountPaymentNote
from juloserver.customer_module.services.customer_related import update_cashback_balance_status
from juloserver.pii_vault.collection.services import mask_phone_number_sync


logger = logging.getLogger(__name__)
client = get_julo_sentry_client()

PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')
DPD1_DPD29 = AgentAssignmentTypeConst.DPD1_DPD29
DPD30_DPD59 = AgentAssignmentTypeConst.DPD30_DPD59
DPD60_DPD89 = AgentAssignmentTypeConst.DPD60_DPD89
DPD90PLUS = AgentAssignmentTypeConst.DPD90PLUS
DPD1_DPD15 = AgentAssignmentTypeConst.DPD1_DPD15
DPD16_DPD29 = AgentAssignmentTypeConst.DPD16_DPD29
DPD30_DPD44 = AgentAssignmentTypeConst.DPD30_DPD44
DPD45_DPD59 = AgentAssignmentTypeConst.DPD45_DPD59


# ----------------------------- Payment data Start ---------------------------------------


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class PaymentDataListView(ListView):
    model = GhostPayment
    paginate_by = 50 #get_conf("PAGINATION_ROW")
    template_name = 'object/payment_status/list.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        # print "http_method_not_allowed"
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        # print "get_template_names"
        return ListView.get_template_names(self)

    def get_queryset(self):
        # print "status_code: ", self.status_code
        self.qs = super(PaymentDataListView, self).get_queryset()
        here_title_status = None
        if self.status_code:
            _title_status = payment_parse_pass_due(self.status_code)
            here_title_status = _title_status
            if _title_status:
                self.qs = self.qs.normal()
                if _title_status[0] == 6:
                    self.qs = self.qs.dpd_groups()
                elif 0 <= _title_status[0] <= 5:
                    self.qs = self.qs.dpd_to_be_called().due_soon(due_in_days=_title_status[0])
                elif _title_status[0] < 0:
                    self.qs = self.qs.overdue().filter(ptp_date__isnull=True)
                elif _title_status[0] == 15:
                    self.qs = self.qs.dpd_groups_1to5()
                elif _title_status[0] == 'PTP':
                    self.qs = self.qs.filter(ptp_date__isnull=False)
                elif _title_status[0] == 531:
                    self.qs = self.qs.dpd_groups_minus5and3and1()
                elif _title_status[0] == 14:
                    self.qs = self.qs.overdue_group_plus_with_range(1, 4)
                elif _title_status[0] == 530:
                    self.qs = self.qs.overdue_group_plus_with_range(5, 30)
                elif _title_status[0] == 30:
                    self.qs = self.qs.overdue_group_plus30()
                elif _title_status[0] == 1000:
                    self.qs = self.qs.uncalled_group()
                elif _title_status[0] == 1001:
                    self.qs = self.qs.due_group0()
                elif _title_status[0] == 1002:
                    self.qs = self.qs.grab_0plus()

                self.status_code = _title_status[1]
        else:
            self.status_code = "all"

        # self.qs = self.qs.order_by('-cdate','-udate','-payment_number','id','loan__application__fullname','loan__application__email')

        self.err_message_here = None
        self.tgl_range = None
        self.tgl_start = None
        self.tgl_end = None
        self.status_payment = None
        self.search_q = None
        self.sort_q = None
        self.sort_agent = None
        self.status_now = None

        # print "self.request.GET: ", self.request.GET
        if self.request.method == 'GET':
            self.tgl_range = self.request.GET.get('datetime_range', None)
            self.sort_q = self.request.GET.get('sort_q', None)
            self.sort_agent = self.request.GET.get('sort_agent', None)
            if (self.status_code == 'all'):
                self.status_payment = self.request.GET.get('status_app', None)
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.status_now = self.request.GET.get('status_now', None)

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_,
                    [
                        Q(**{('%s__icontains' % 'loan__application__id'): self.search_q}),
                        Q(**{('%s__icontains' % 'loan__application__fullname'): self.search_q}),
                        Q(**{('%s__icontains' % 'loan__application__ktp'): self.search_q}),
                        Q(**{('%s__icontains' % 'loan__application__mobile_phone_1'): self.search_q}),
                        Q(**{('%s__icontains' % 'id'): self.search_q}),
                        Q(**{('%s__icontains' % 'payment_status__status_code'): self.search_q}),
                        Q(**{('%s__icontains' % 'loan__id'): self.search_q}),
                        Q(**{('%s__icontains' % 'loan__application__email'): self.search_q}),
                        Q(**{('%s__icontains' % 'loan__julo_bank_account_number'): self.search_q})
                    ]))

            if(self.status_payment) and (self.status_code == 'all'):
                self.qs = self.qs.filter(payment_status__status_code=self.status_payment)

            if(self.status_now):
                # print "OKAY STATUS NOW : ", self.status_now
                if(self.status_now == 'True'):
                    # print "HARI INI"
                    startdate = datetime.today()
                    startdate = startdate.replace(hour=0, minute=0, second=0)
                    enddate = startdate + datetime.timedelta(days=1)
                    enddate = enddate - datetime.timedelta(seconds=1)
                    self.qs = self.qs.filter(cdate__range=[startdate, enddate])
                else:
                    _date_range = self.tgl_range.split('-')
                    if(_date_range[0].strip() != 'Invalid date'):
                        _tgl_mulai = datetime.strptime(_date_range[0].strip(), "%d/%m/%Y %H:%M")
                        _tgl_end = datetime.strptime(_date_range[1].strip(), "%d/%m/%Y %H:%M")
                        # print "BEBAS"
                        if(_tgl_end > _tgl_mulai):
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.err_message_here = "Format Tanggal tidak valid"

            # add dpd_sort for property sorting
            self.qs = self.qs.extra(
                select={
                    'loan_status': 'loan.loan_status_code',
                    'dpd_sort': "CASE WHEN payment.due_date is not Null THEN DATE_PART('day', CURRENT_TIMESTAMP - due_date) END",
                    'dpd_ptp_sort': "CASE WHEN payment.ptp_date is not Null THEN DATE_PART('day', ptp_date - CURRENT_TIMESTAMP) END"
                },
                tables=['loan'],
                where=['loan.loan_status_code != %s', 'loan.loan_id = payment.loan_id'],
                # order_by = ['dpd_sort', 'payment_number', '-udate'],
                params=[StatusLookup.INACTIVE_CODE],
            )
            if (self.status_code == 'all'):
                self.qs = self.qs.extra(order_by=['dpd_sort'])
                # self.qs = self.qs.order_by('-cdate','-udate','-payment_number','id','loan__application__fullname','loan__application__email')
            else:
                if here_title_status:
                    _title_status_dpd_sort_list = (6, 15, 14, 530, 30)
                    if 0 <= _title_status[0] <= 5 or _title_status[0] < 0 or _title_status[0] in _title_status_dpd_sort_list:
                        self.qs = self.qs.extra(order_by=['dpd_sort'])
                    elif _title_status[0] == 531:
                        self.qs = self.qs.extra(order_by=['-dpd_sort'])
            if(self.sort_q):
                if(self.sort_q == 'loan_and_status_asc'):
                    self.qs = self.qs.order_by('loan__id','loan__loan_status__status_code')
                elif(self.sort_q == 'loan_and_status_desc'):
                    self.qs = self.qs.order_by('-loan__id','-loan__loan_status__status_code')
                elif(self.sort_q == 'dpd'):
                    self.qs = self.qs.extra(order_by=['dpd_sort'])
                elif(self.sort_q == '-dpd'):
                    self.qs = self.qs.extra(order_by=['-dpd_sort'])
                elif(self.sort_q == 'dpd_ptp'):
                    self.qs = self.qs.extra(order_by=['dpd_ptp_sort'])
                elif(self.sort_q == '-dpd_ptp'):
                    self.qs = self.qs.extra(order_by=['-dpd_ptp_sort'])
                else:
                    self.qs = self.qs.order_by(self.sort_q)


        else:
            print("else request GET")

        len(self.qs)  # for bugfix pagination, effect have double value same id at page to another page.
        return self.qs

    def get_context_object_name(self, object_list):
        # if object_list:
        #     print "hohoho: ", dir(object_list[0])
        #     if object_list[0].dpd_sort is not None or object_list[0].dpd_sort != '':
        #         print "object_list[0].dpd_sort: ", object_list[0].dpd_sort
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(PaymentDataListView, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = PaymentSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = PaymentSearchForm()
        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['status_code_now'] = self.status_code
        context['status_show'] = self.status_show
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        users = User.objects.all().order_by('id')
        collection_agents = users.filter(groups__name__in=[
                                                            JuloUserRoles.COLLECTION_AGENT_2,
                                                            JuloUserRoles.COLLECTION_AGENT_3,
                                                            JuloUserRoles.COLLECTION_AGENT_4,
                                                            JuloUserRoles.COLLECTION_AGENT_5
                                                          ], is_active=True)
        context['collection_agents'] = collection_agents
        autodialer_result = AutoDialerRecord.objects.all().order_by('payment_id')
        context['autodialer_result'] = autodialer_result
        context['payment_id_locked'] = payment_lock_list()
        return context

    def get(self, request, *args, **kwargs):
        try:
            self.status_code = self.kwargs['status_code']
            if self.status_code == 'all':
                self.status_show = self.status_code
            else:
                self.status_show = 'with_status'
        except:
            self.status_code = None
            self.status_show = 'with_status'

        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super(PaymentDataListView, self).render_to_response(context, **response_kwargs)
        return rend_here

@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def payment_list_view_v2(request, status_code):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    template_name = 'object/payment_status/list_v2.html'
    #get parameters url
    search_q = request.GET.get('search_q', '')
    status_app = request.GET.get('status_app', '')
    filter_special_condition = request.GET.get('filter_special_condition', '')
    #init variabel
    list_show_filter_agent = ['Collection supervisor T+1, T+4', 'Collection supervisor T+5, T+15', 'Collection supervisor T+16, T+29',
                              'Collection supervisor T+30, T+44', 'Collection supervisor T+45, T+59', 'Collection supervisor T+60, T+74',
                              'Collection supervisor T+60, T+74', 'Collection supervisor T+75, T+89', 'Collection supervisor T+90, T+119',
                              'Collection supervisor T+120, T+179', 'Collection supervisor T+179++',
                              'Collection supervisor PTP', 'Collection supervisor ignore called', 'Collection supervisor whatsapp', 'all',
                              'Collection Supervisor bucket T+1, T+4', 'Collection Supervisor bucket T+5, T+10',
                              'Collection Supervisor bucket T+11, T+25', 'Collection Supervisor bucket T+26, T+40',
                              'Collection Supervisor bucket T+41, T+55', 'Collection Supervisor bucket T+56, T+70',
                              'Collection Supervisor bucket T+71, T+85', 'Collection Supervisor bucket T+86, T+100',
                              'Collection supervisor T+101 >> ++', 'Collection Supervisor bucket 1 PTP',
                              'Collection Supervisor bucket 2 PTP', 'Collection Supervisor bucket 3 PTP',
                              'Collection Supervisor bucket 4 PTP', 'Collection Supervisor bucket 5 PTP',
                              'Collection Supervisor bucket 1 WA', 'Collection Supervisor bucket 2 WA',
                              'Collection Supervisor bucket 3 WA', 'Collection Supervisor bucket 4 WA',
                              'Collection Supervisor bucket 5 WA', 'Collection Supervisor Bucket 3 Ignore Called',
                              'Collection Supervisor Bucket 4 Ignore Called', 'Collection Supervisor Bucket 5 Ignore Called']
    try:
        title_status = payment_parse_pass_due(status_code)
        if title_status:
            title_status = title_status[1]
        else:
            if status_app:
                title_status = str(status_app)
            else:
                title_status = 'all'
        if status_code == 'all':
            status_show = status_code
        else:
            status_show = 'with_status'
    except:
        status_code = 'all'
        status_show = 'with_status'

    return render(
        request,
        template_name,
        {
            'status_code': status_code,
            'status_show': status_show,
            'status_title': title_status,
            'status_app': status_app,
            'search_q': search_q,
            'list_show_filter_agent':list_show_filter_agent,
            'filter_special_condition':filter_special_condition
        }
    )


from app_status.utils import ExtJsonSerializer
from .forms import EventPaymentForm, ApplicationPhoneForm, SendEmailForm


@julo_login_required
def change_pmt_status(request, pk):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    user = request.user
    user_groups = user.groups.values_list('name', flat=True).all()
    today = timezone.localtime(timezone.now()).date()
    payment_obj = Payment.objects.select_related(
        'loan',
        'payment_status',
        'loan__application',
        'loan__customer').annotate(
            dpd=ExpressionWrapper((today - F('due_date')), output_field=IntegerField()))\
                .get(id=pk)

    status_current = payment_obj.payment_status
    loan_obj = payment_obj.loan
    payments_after_restructured = Payment.objects.filter(loan=loan_obj).normal()
    if payment_obj.is_paid:
        payment_obj.dpd = payment_obj.paid_late_days

    template_name = 'object/payment_status/change_status.html'
    message_out_ubah_status = None
    message_out_simpan_note = None
    ubah_status_active = 0
    simpan_note_active = 0
    is_julo_one = False
    if loan_obj.account:
        application = loan_obj.account.last_application
        is_julo_one = True
    else:
        application = loan_obj.application
    application_id = application.id
    application_product_line = application.product_line
    customer = loan_obj.customer
    app_list = get_app_list_history(application)
    wallet_notes = get_wallet_list_note(customer)
    app_phone = [
        (application.mobile_phone_1, 'mobile_phone_1'),
        (application.mobile_phone_2, 'mobile_phone_2'),
        (application.spouse_mobile_phone, 'spouse_mobile_phone'),
        (application.kin_mobile_phone, 'kin_mobile_phone'),
        ('0', 'custom')
    ]

    robocall_templates = RobocallTemplate.objects.filter(is_active=True)
    robo_templates_map = {}
    for robocall_template in robocall_templates:
        robo_templates_map[str(robocall_template.id)] = robocall_template.text
    app_email = application.email

    if request.method == 'POST':
        form = StatusChangesForm(status_current, request.POST)
        form_app_phone = ApplicationPhoneForm(app_phone, request.POST)
        form_email = SendEmailForm()
        if form.is_valid():
            if 'ubah_status' in request.POST:
                print("ubah_status-> valid here")

            status_to = form.cleaned_data['status_to']
            reason = form.cleaned_data['reason']
            notes = form.cleaned_data['notes']

            reason_arr = [item_reason.reason for item_reason in reason]
            reason = ", ".join(reason_arr)

            logger.info({
                'status_to': status_to,
                'reason': reason,
                'notes': notes
            })

            # TODO: call change_status_backend mapping
            ret_status = process_payment_status_change(
                payment_obj.id, status_to.status_code, reason, note=notes)
            print("ret_status: ", ret_status)
            if (ret_status):
                # form is sukses
                url = reverse('payment_status:change_status', kwargs={'pk': payment_obj.id})
                return redirect(url)
            else:
                # there is an error
                err_msg = """
                    Ada Kesalahan di Backend Server!!!, Harap hubungi Administrator
                """
                logger.info({
                    'app_id': payment_obj.id,
                    'error': "Ada Kesalahan di Backend Server with process_payment_status_change!!."
                })
                messages.error(request, err_msg)
                message_out_ubah_status = err_msg
                ubah_status_active = 1

        else:
            print("for is invalid and check notes")
            if 'simpan_note_to' in request.POST:
                try:
                    text_notes = form.cleaned_data['notes_only']
                    data = request.POST
                    user_id = request.user.id if request.user else None
                    if text_notes:
                        if data['simpan_note_to'] == 'application':
                            notes = ApplicationNote.objects.create(
                                note_text=text_notes,
                                application_id=application.id,
                                added_by_id=user_id,
                            )
                        else:
                            notes = PaymentNote.objects.create(
                                note_text=text_notes,
                                payment=payment_obj)

                        logger.info({
                            'action': 'save_note',
                            'notes': notes,
                        })

                        url = reverse(
                            'payment_status:change_status',
                            kwargs={'pk': payment_obj.id}
                        )
                        return redirect(url)
                    else:
                        err_msg = """
                            Note/Catatan Tidak Boleh Kosong !!!
                        """
                        messages.error(request, err_msg)
                        message_out_simpan_note = err_msg
                        simpan_note_active = 1

                except Exception as e:
                    err_msg = """
                        Catatan Tidak Boleh Kosong !!!
                    """
                    messages.error(request, err_msg)
                    message_out_simpan_note = err_msg
                    simpan_note_active = 1
            else:
                # form is not valid
                err_msg = """
                    Ubah Status atau Alasan harus dipilih dahulu !!!
                """
                messages.error(request, err_msg)
                message_out_ubah_status = err_msg
                ubah_status_active = 1

    else:
        form = StatusChangesForm(status_current)
        form_app_phone = ApplicationPhoneForm(app_phone)
        form_email = SendEmailForm()
        loan_obj.refresh_from_db()

    image_list = Image.objects.filter(
        image_source=application_id,
        image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
    )
    results_json = ExtJsonSerializer().serialize(
        image_list,
        props=['image_url', 'image_ext'],
        fields=('image_type',)
    )

    image_list_1 = Image.objects.filter(image_source=application_id, image_status=Image.DELETED)
    results_json_1 = ExtJsonSerializer().serialize(
        image_list_1,
        props=['image_url', 'image_ext'],
        fields=('image_type',)
    )
    voice_list = VoiceRecord.objects.filter(
        application=application_id,
        status__in=[VoiceRecord.CURRENT, VoiceRecord.RESUBMISSION_REQ]
    )
    results_json_2 = ExtJsonSerializer().serialize(
        voice_list,
        props=['presigned_url'],
        fields=('status')
    )

    voice_list_1 = VoiceRecord.objects.filter(
        application=application_id,
        status=VoiceRecord.DELETED
    )
    results_json_3 = ExtJsonSerializer().serialize(
        voice_list_1,
        props=['presigned_url'],
        fields=('status')
    )
    bucket_5_collection_assignment_movement_history = None
    if payment_obj.loan.ever_entered_B5:
        bucket_5_collection_assignment_movement_history = display_account_movement_history(
            account_payment_or_payment=payment_obj, is_julo_one=False
        )
    history_note_list = get_list_history(payment_obj, bucket_5_collection_assignment_movement_history)
    email_sms_list = get_list_email_sms(payment_obj)
    # sms_history = SmsHistory.objects.filter(payment=payment_obj)
    # email_history = EmailHistory.objects.filter(payment=payment_obj)
    skiptrace_list = (
        Skiptrace.objects.filter(customer_id=customer.id)
        .exclude(contact_source='kin_mobile_phone')
        .order_by('id')
    )
    skiptrace_history_list = SkiptraceHistory.objects.filter(application_id=application_id).order_by('-cdate')[:100]
    cootek_payment = CootekRobocall.objects.filter(payment_id=payment_obj.id).order_by('-cdate')
    status_skiptrace = True
    # call_result = SkiptraceResultChoice.objects.all()

    # get fb data
    fb_obj = getattr(application, 'facebook_data', None)
    # get loan data and order by offer_number
    offer_set_objects = application.offer_set.all().order_by("offer_number")
    app_data = get_data_application_checklist_collection(application)
    deprecated_list = ['address_kodepos','address_kecamatan','address_kabupaten','bank_scrape','address_kelurahan','address_provinsi','bidang_usaha']
    form_payment = PaymentForm(instance=payment_obj, prefix='form2')
    form_app = ApplicationForm(instance=application, prefix='form2')
    form_app_select = ApplicationSelectFieldForm( application, prefix='form2')
    payment_methods = PaymentMethod.objects.filter(loan=loan_obj, is_shown=True)
    lock_status, lock_by = 0, None
    if application.product_line_code not in ProductLineCodes.grab():
        lock_status, lock_by = get_lock_status(payment_obj, user)
    wallets = CustomerWalletHistory.objects.filter(customer=customer).order_by('-id')
    wallets = wallets.exclude(change_reason__contains='_old').order_by('-id')
    payment_event_service = PaymentEventServices()
    payment_event_detail = payment_event_service.get_detail(payment_obj, user, user_groups)
    change_due_date_active = check_change_due_date_active(payment_obj, loan_obj, status_current)
    first_installment_btn_active = check_first_installment_btn_active(payment_obj,
                                                                      application \
                                                                      if is_julo_one else None)

    list_whatsapp_phone = skiptrace_list.filter(
                            contact_source__in=['mobile phone 1','mobile_phone1','mobile_phone 1','mobile_phone_1','Mobile phone 1'
                                                'Mobile_phone_1','Mobile_Phone_1','mobile_phone1_1','mobile phone 2','mobile_phone2'
                                                'mobile_phone 2','mobile_phone_2','Mobile phone 2','Mobile_phone2','Mobile_phone_2'
                                                'MOBILE_PHONE_2']).order_by('contact_source')
    ptp_robocall_mobile_qs = skiptrace_list.filter(
        contact_source__in=['mobile_phone_1', 'mobile_phone_2']).values(
        'contact_source', 'phone_number')
    ptp_robocall_mobile_list = list(ptp_robocall_mobile_qs)
    if len(ptp_robocall_mobile_list) == 0:
        ptp_robocall_mobile_list.append(
            {'contact_source': 'mobile_phone_1', 'phone_number': application.mobile_phone_1})
        ptp_robocall_mobile_list.append(
            {'contact_source': 'mobile_phone_2', 'phone_number': application.mobile_phone_2})
    installment_form = NewPaymentInstallmentForm(request.POST)
    collection_agent_service = get_agent_service_for_bucket()
    agent_details = collection_agent_service.get_agent([{'id': payment_obj.id}])

    # iso collection setting hide tab and button
    is_iso_inactive = True
    iso_st_source = ['mobile_phone_1',
                     'mobile_phone_2',
                     'kin_mobile_phone',
                     'close_kin_mobile_phone',
                     'company_phone_number',
                     'spouse_mobile_phone']
    iso_collection_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ISO_COLLECTION,
        category='collection', is_active=True).last()
    if iso_collection_setting:
        param = iso_collection_setting.parameters
        start_date = parse(param.get('start')).date()
        end_date = parse(param.get('end')).date()
        if start_date <= today <= end_date:
            is_iso_inactive = False
        elif today > end_date:
            iso_collection_setting.is_active = False
            iso_collection_setting.save()
            is_iso_inactive = True

    if not is_iso_inactive:
        image_list = image_list.filter(image_type__icontains='RECEIPT')

    is_for_ojk = False
    if user.crmsetting.role_select in JuloUserRoles.collection_bucket_roles():
        is_for_ojk = True
        image_list = image_list.filter(image_type__in=(ImageUploadType.PAYSTUB, 'crop_selfie'))

    waiver_temps = WaiverTemp.objects.filter(loan=payment_obj.loan)
    loan_refinancing_status = None
    loan_refinancing = LoanRefinancing.objects.filter(loan=loan_obj).last()
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(loan=loan_obj).last()

    if loan_refinancing:
        if loan_refinancing.status == LoanRefinancingStatus.REQUEST:
            loan_refinancing_status = 'Restructure Pending'
        elif loan_refinancing.status == LoanRefinancingStatus.ACTIVE:
            loan_refinancing_status = 'Restructured'

    if loan_refinancing_request:
        loan_refinancing_status = get_refinancing_status_display(loan_refinancing_request)

    # only show current payment during transition to new integrated waiver
    last_payment = Payment.objects.by_loan(payment_obj.loan).not_paid_active().order_by(
        '-payment_number').last()
    last_payment_number = payment_obj.payment_number
    if last_payment:
        last_payment_number = last_payment.payment_number
    total_max_waive_interest = get_remaining_interest(
        payment_obj, is_unpaid=False, max_payment_number=last_payment_number)
    total_max_waive_late_fee = get_remaining_late_fee(
        payment_obj, is_unpaid=False, max_payment_number=last_payment_number)
    total_max_waive_principal = get_remaining_principal(
        payment_obj, is_unpaid=False, max_payment_number=last_payment_number)
    total_unpaid_due_amount = loan_obj.get_total_outstanding_due_amount()

    provinces = ProvinceLookup.objects.filter(
        is_active=True
    ).order_by('province').values_list('province', flat=True)

    whatsapp_text = get_mtl_whatsapp_collection_text(application, payment_obj, loan_obj, payment_methods)
    no_contact_whatsapp_text = get_wa_message_is_5_days_unreachable(application)

    wa_contact_mobile_data = skiptrace_list.filter(
        contact_source__in=['mobile_phone_1', 'mobile_phone_2',
                            'kin_mobile_phone', 'close_kin_mobile_phone', 'spouse_mobile_phone']). \
        values('contact_source', 'phone_number')
    wa_contact_mobile_list = list(wa_contact_mobile_data)

    # check if is_5_days_uncontacted, is_broken_ptp_plus_1
    is_5_days_unreachable = False
    is_broken_ptp_plus_1 = False
    broken_ptp_whatsapp_text = ""

    oldest_unpaid_payment = payment_obj.loan.get_oldest_unpaid_payment()
    if oldest_unpaid_payment and (oldest_unpaid_payment.id == payment_obj.id):
        is_5_days_unreachable = payment_obj.loan.is_5_days_unreachable
        is_broken_ptp_plus_1 = payment_obj.loan.is_broken_ptp_plus_1
        if is_broken_ptp_plus_1:
            broken_ptp_whatsapp_text = get_wa_message_is_broken_ptp_plus_1(oldest_unpaid_payment, application)

    is_multiple_factors = False
    if is_broken_ptp_plus_1 and is_5_days_unreachable:
        is_multiple_factors = True

    return render(
        request,
        template_name,
        {
            'form': form,
            'payment_obj': payment_obj,
            'application': application,
            'application_product_line': application_product_line,
            'fb_obj': fb_obj,
            'status_current': status_current,
            'image_list': image_list,
            'json_image_list': results_json,
            'image_list_1': image_list_1,
            'json_image_list_1': results_json_1,
            'voice_list': voice_list,
            'json_voice_list': results_json_2,
            'voice_list_1': voice_list_1,
            'json_voice_list_1': results_json_3,
            'history_note_list': history_note_list,
            'email_sms_list': email_sms_list,
            'datetime_now': timezone.now(),
            'image_per_row0': [1, 7, 13, 19, 25],
            'image_per_row': [7, 13, 19, 25],
            'message_out_simpan_note': message_out_simpan_note,
            'message_out_ubah_status': message_out_ubah_status,
            'ubah_status_active': ubah_status_active,
            'simpan_note_active': simpan_note_active,
            'form_app_phone': form_app_phone,
            'form_send_email': form_email,
            'app_email': app_email,
            'app_list': app_list,
            'offer_set_objects': offer_set_objects,
            'loan_obj': loan_obj,
            'skiptrace_list': skiptrace_list,
            'skiptrace_history_list': skiptrace_history_list,
            'cootek_payment' : cootek_payment,
            'status_skiptrace': status_skiptrace,
            'application_id': application_id,
            'app_data':app_data,
            'deprecatform_apped_list':deprecated_list,
            'deprecated_list': deprecated_list,
            'form_app':form_app,
            'form_app_select':form_app_select,
            'form_payment':form_payment,
            'payment_methods' : payment_methods,
            'button_lock' : get_payment_lock_count(payment_obj),
            'lock_status': lock_status,
            'lock_by': lock_by,
            'is_payment_called' : 1 if payment_obj.is_collection_called else 0,
            'bank_name_list':json.dumps(BankManager.get_bank_names()),
            'wallets': wallets,
            'wallet_notes': wallet_notes,
            'payment_event_detail': payment_event_detail,
            'change_due_date_active': change_due_date_active,
            'first_installment_btn_active': first_installment_btn_active,
            'list_whatsapp_phone':list_whatsapp_phone,
            'robocall_templates': robocall_templates,
            'robo_templates_map': json.dumps(robo_templates_map),
            'ptp_robocall_mobile_list': ptp_robocall_mobile_list,
            'installment_form': installment_form,
            'agent_details': agent_details[0],
            'is_iso_inactive': is_iso_inactive,
            'iso_st_source': iso_st_source,
            'is_for_ojk': is_for_ojk,
            # only show current payment during transition to new integrated waiver
            'payment_number_list': sorted((payment_obj.payment_number, ), reverse=True),
            'waiver_temps': waiver_temps,
            'total_max_waive_interest' : total_max_waive_interest,
            'total_max_waive_late_fee' : total_max_waive_late_fee,
            'total_max_waive_principal': total_max_waive_principal,
            'total_max_waive_principal_input': total_max_waive_principal - 1,
            'total_max_waive_principal_paid': payment_obj.installment_principal - payment_obj.paid_principal,
            'total_max_waive_interest_paid': payment_obj.installment_interest - payment_obj.paid_interest,
            'total_max_waive_late_fee_paid': payment_obj.late_fee_amount - payment_obj.paid_late_fee,
            'loan_refinancing_status': loan_refinancing_status,
            'payment_event_reversal_reason' : PAYMENT_EVENT_CONST.REVERSAL_REASONS,
            'reversal_reason_show_move_payment': PAYMENT_EVENT_CONST.REVERSAL_REASON_WRONG_PAYMENT,
            'payments': payments_after_restructured,
            'customer_bucket_type': check_customer_bucket_type(payment_obj),
            'provinces': provinces,
            'user': user,
            'available_parameters': get_current_mtl_wl_web_url(loan_obj),
            'whatsapp_text': whatsapp_text,
            'total_unpaid_due_amount': total_unpaid_due_amount or 0,
            'no_contact_whatsapp_text': no_contact_whatsapp_text,
            'wa_contact_mobile_list': wa_contact_mobile_list,
            'is_5_days_unreachable': is_5_days_unreachable,
            'is_broken_ptp_plus_1': is_broken_ptp_plus_1,
            'broken_ptp_whatsapp_text': broken_ptp_whatsapp_text,
            'is_multiple_factors': is_multiple_factors,
            'is_sms_email_button_unlocked': not is_crm_sms_email_locking_active(),
            'is_julo_one_or_starter': application.is_julo_one_or_starter,
        }
    )


from .services import validate_cashback_earned, save_payment_event_from_csv


@csrf_protect
def add_payment_event(request):

    if request.method == 'POST':
        user = request.user
        user_groups = user.groups.values_list('name', flat=True).all()
        data = request.POST.dict()
        payment_obj = Payment.objects.get(pk=data['payment_id'])
        if not payment_obj:
            return HttpResponse(
                json.dumps({
                    "messages": "payment id not found : %s " % (data['payment_id']),
                    "result": "failed"}),
                content_type="application/json")
        payment_event_service = PaymentEventServices()
        messages = "payment event not success"
        result = 'failed'

        if data['event_type'] == 'payment':
            status = payment_event_service.process_event_type_payment(payment_obj, data)
        elif data['event_type'] == 'late_fee':
            status = payment_event_service.process_event_type_late_fee(payment_obj, data)
        elif data['event_type'] == 'customer_wallet':
            status = payment_event_service.process_event_type_customer_wallet(payment_obj, data)
        elif 'waive_late_fee' in data['event_type']:
            status, messages = payment_event_service.process_event_type_waive_late_fee(payment_obj, data, user_groups)
        elif 'waive_interest' in data['event_type']:
            status, messages = payment_event_service.process_event_type_waive_interest(payment_obj, data, user_groups)
        elif 'waive_principal' in data['event_type']:
            status, messages = payment_event_service.process_event_type_waive_principal(payment_obj, data, user_groups)
        if status:
            messages = "payment event success"
            result = 'success'
        return HttpResponse(
            json.dumps({
                "messages": messages,
                "result": result}),
            content_type="application/json")


@csrf_protect
def get_remaining_late_fee_amount(request):
    if request.method == 'GET':
        payment_id = request.GET.get('payment_id')
        payment_obj = Payment.objects.get(pk=payment_id)
        payment_event_service = PaymentEventServices()
        remaining_late_fee_amount = payment_event_service.get_remaining_late_fee(payment_obj)
        return HttpResponse(
            json.dumps({
                "success": True,
                "remaining_late_fee_amount": remaining_late_fee_amount}),
            content_type="application/json")


@csrf_protect
def populate_reason(request):
    # print "f(x) populate_reason INSIDE"
    if request.method == 'GET':
        status_to = request.GET.get('status_code')
        response_data = {}
        # print "status_to : %s" % (status_to)

        # check if there is StatusLookup which matches the status_code (if not then display 404)
        status_obj = get_object_or_404(StatusLookup, pk=status_to)
        # print 'status_obj: ', status_obj

    if status_obj:
        reason_query = ReasonStatusAppSelection.objects.filter(status_to=status_obj)
        reason_list = [[item.id, item.reason] for item in reason_query]
        # print "reason_list: ", reason_list
        response_data['result'] = 'successful!'
        response_data['reason_list'] = reason_list

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "nothing to see": "this isn't happening",
                'result': "nok"}),
            content_type="application/json")


@csrf_protect
def send_sms(request):

    if request.method == 'GET':

        payment_id = request.GET.get('payment_id')
        payment = Payment.objects.get_or_none(id=payment_id)
        if payment is None:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Payment=%s not found" % payment_id
                }),
                content_type="application/json")

        if not payment.loan.application.customer.can_notify:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Can not notify to this customer"
                }),
                content_type="application/json")

        sms_message = request.GET.get('sms_message').strip()

        if "{nonj1_wl_url}" in sms_message:
            short_wl_url = get_current_mtl_wl_web_url(payment.loan)
            if short_wl_url:
                short_wl_url = short_wl_url.replace("https://", "")
                short_wl_url = ' %s ' % short_wl_url
                sms_message = sms_message.format(nonj1_wl_url=short_wl_url)

        to_number = request.GET.get('to_number')
        phone_type = request.GET.get('phone_type')
        category = request.GET.get('category')
        template_code = request.GET.get('template_code')
        if sms_message == '':
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Message is empty"
                }),
                content_type="application/json")

        try:
            send_custom_sms_payment_reminder(
                payment, to_number,
                phone_type, category, sms_message, template_code)

        except SmsNotSent as sns:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': str(sns)
                }),
                content_type="application/json")

        return HttpResponse(
            json.dumps({
                'result': 'successful!',
            }),
            content_type="application/json")


@csrf_protect
def send_email(request):
    if request.method == 'GET':
        payment_id = request.GET.get('payment_id')
        payment = Payment.objects.get_or_none(id=payment_id)
        if payment is None:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Payment=%s not found" % payment_id
                }),
                content_type="application/json")

        if not payment.loan.application.customer.can_notify:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Can not notify to this customer"
                }),
                content_type="application/json")

        email_content = request.GET.get('content')
        if "{nonj1_wl_url}" in email_content:
            short_wl_url = get_current_mtl_wl_web_url(payment.loan)
            if short_wl_url:
                short_wl_url = short_wl_url.replace("https://", "")
                short_wl_url = ' %s ' % short_wl_url
                email_content = email_content.format(nonj1_wl_url=short_wl_url)

        to_email = request.GET.get('to_email')
        subject = request.GET.get('subject')
        category = request.GET.get('category')
        template_code = request.GET.get('template_code')
        pre_header = request.GET.get('pre_header')
        valid_email = check_email(to_email)

        if not valid_email:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Invalid Email Address"
                }),
                content_type="application/json")

        if email_content == '':
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Message is empty"
                }),
                content_type="application/json")

        try:
            send_custom_email_payment_reminder(
                payment, to_email, subject, email_content, category, pre_header, template_code)

        except EmailNotSent as ens:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': str(ens)
                }),
                content_type="application/json")

        return HttpResponse(
            json.dumps({
                'result': 'successful!',
            }),
            content_type="application/json")


@csrf_protect
def add_skiptrace(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    user = request.user
    data = request.POST.dict()
    application = Application.objects.get_or_none(pk=data['application'])
    if not application:
        return HttpResponseNotFound("application id %s not found" %data['application'])

    data['customer'] = application.customer.id
    data['phone_number'] = format_e164_indo_phone_number(data['phone_number'])
    new_phone_number = data['phone_number']
    change_reason = data.get('change_reason', '')

    skiptrace_serializer = SkiptraceSerializer(data=data)
    if not skiptrace_serializer.is_valid():
        return HttpResponseBadRequest("invalid data!! or phone number already exist!!")

    skiptrace = skiptrace_serializer.save()
    skiptrace_obj = skiptrace_serializer.data

    old_contact_source = skiptrace.contact_source
    old_contact_name = skiptrace.contact_name

    if 'account_payment_id' in data:
        account_payment_id = data['account_payment_id']
        if account_payment_id:
            account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
            AccountPaymentNote.objects.create(
                account_payment=account_payment,
                added_by=user,
                note_text='Menambahkan Nomer telepon {} - {} {} dengan alasan {}'.format(
                    old_contact_source,
                    old_contact_name,
                    new_phone_number,
                    change_reason,
                ),
            )

    return JsonResponse({
        "messages": "save success",
        "data": skiptrace_obj
    })


@csrf_protect
def update_skiptrace(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    user = request.user
    data = request.POST.dict()
    application = Application.objects.get_or_none(pk=int(data['application']))
    if not application:
        return HttpResponseNotFound("application id %s not found" % data['application'])

    new_phone_number = format_e164_indo_phone_number(
        data['phone_number']) if data['phone_number'] else ''
    data['customer'] = application.customer.id
    data['phone_number'] = new_phone_number
    change_reason = data.get('change_reason', '')

    skiptrace = Skiptrace.objects.get_or_none(pk=data['skiptrace_id'])
    if not skiptrace:
        return HttpResponseNotFound("skiptrace id %s not found" % data['skiptrace_id'])
    old_phone_number = skiptrace.phone_number
    old_contact_source = skiptrace.contact_source
    old_contact_name = skiptrace.contact_name
    if new_phone_number == '0':
        skiptrace.update_safely(
            phone_number='',
            contact_source=data['contact_source'],
            contact_name=data['contact_name'],
        )
        skiptrace_serializer = SkiptraceSerializer(skiptrace, data=data, partial=True)
        skiptrace_serializer.is_valid()
        skiptrace_obj = skiptrace_serializer.data
    else:
        skiptrace_serializer = SkiptraceSerializer(skiptrace, data=data, partial=True)
        if not skiptrace_serializer.is_valid():
            return HttpResponseBadRequest("invalid data!! or phone number already exist!!")

        skiptrace_obj = skiptrace_serializer.save()
        skiptrace_obj = skiptrace_serializer.data

    if 'account_payment_id' in data:
        account_payment_id = data['account_payment_id']
        if account_payment_id:
            account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
            AccountPaymentNote.objects.create(
                account_payment=account_payment,
                added_by=user,
                note_text='Mengganti Nomer telepon {} - {} dari {} ke {} dengan alasan {}'.format(
                    old_contact_source,
                    old_contact_name,
                    old_phone_number,
                    new_phone_number,
                    change_reason,
                ),
            )

    return JsonResponse({
        "messages": "save success",
        "data": skiptrace_obj
    })


@csrf_protect
@julo_login_required
def skiptrace_history(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application = Application.objects.get_or_none(pk=int(data['application']))
    if not application:
        return HttpResponseNotFound("application id %s not found" % data['application'])

    ptp_date_str = data['skip_ptp_date'] if 'skip_ptp_date' in data else None
    ptp_date = None

    if ptp_date_str:
        ptp_date = datetime.strptime(ptp_date_str, '%d-%m-%Y').date()

    today = timezone.localtime(timezone.now()).date()

    if ptp_date is not None and ptp_date < today:
        return JsonResponse(status=400, data={
            "status": "failed",
            "message": "ptp_date is less than today!"
        })

    loan_id = data['loan_id'] if 'loan_id' in data else None
    ptp_due_date = None

    if loan_id is not None:
        loan = Loan.objects.get_or_none(pk=int(data['loan_id']))
        ptp_due_date = get_ptp_max_due_date(loan)

    if ptp_date is not None and ptp_due_date != date(2017, 1, 1) and \
        ptp_due_date is not None and \
        (ptp_due_date is None or ptp_date > ptp_due_date):
        return JsonResponse(status=400, data={
            "status": "failed",
            "message": "ptp_date is greater than max ptp bucket date"
        })

    data['application_status'] = application.status
    data['old_application_status'] = None

    status_new = application.application_status.status_code
    app_history = application.applicationhistory_set.filter(status_new=status_new).order_by('cdate').last()
    is_payment = 0
    if app_history:
        data['application_status'] =app_history.status_new
        data['old_application_status'] = app_history.status_old

    if 'payment' in data:
        payment = Payment.objects.get_or_none(pk=int(data['payment']))
        if not payment:
            return HttpResponseNotFound("payment id %s not found" % data['payment'])
        if application.account:
            return JsonResponse(status=400, data={
                "status": "failed",
                "message": "can not do manual call for J1 from ALL 300"
            })
        data['payment_status'] = payment.status
        data['loan'] = payment.loan.id
        data['loan_status'] = payment.loan.status
        is_payment = 1

    data['end_ts'] = parse(str(data['end_ts']))
    data['start_ts'] = parse(str(data['start_ts'])) if data['start_ts'] else data['end_ts']

    data['agent'] = request.user.id
    data['agent_name'] = request.user.username
    if 'level1' in data:
        data['notes'] = data['skip_note']
        if 'skip_time' in data:
            data['callback_time'] = data['skip_time']
    if application.is_grab():
        skiptrace_history_serializer = GrabSkiptraceHistorySerializer(data=data)
    else:
        skiptrace_history_serializer = SkiptraceHistorySerializer(data=data)
    if not skiptrace_history_serializer.is_valid():
        logger.warn({
            'skiptrace_id': data['skiptrace'],
            'agent_name': data['agent_name'],
            'error_msg': skiptrace_history_serializer.errors
        })
        return HttpResponseBadRequest("data invalid")

    skiptrace_history_obj = skiptrace_history_serializer.save()
    skiptrace_history_obj = skiptrace_history_serializer.data

    call_result = SkiptraceResultChoice.objects.get(pk=data['call_result'])
    if call_result.name == 'Cancel':
        return JsonResponse({
            "messages": "save success",
            "data": ""
        })

    skiptrace = Skiptrace.objects.get_or_none(pk=data['skiptrace'])

    if not skiptrace:
        return HttpResponseNotFound("skiptrace id %s not found" % data['skiptrace'])
    skiptrace = update_skiptrace_score(skiptrace, data['start_ts'])
    agent_assignment_message = ''

    call_note = {
        "contact_source": skiptrace.contact_source,
        "phone_number": str(skiptrace.phone_number),
        "call_result": call_result.name or '',
        "spoke_with": skiptrace_history_obj['spoke_with'],
        "non_payment_reason": skiptrace_history_obj.get('non_payment_reason') or ''
    }
    skip_note = data.get('skip_note')

    if 'level1' in data:
        # wa_client = get_julo_centerix_client()
        customer_id = application.customer.id
        if payment and request.user and call_result:
            trigger_insert_col_history(payment.id, request.user.id, call_result.id)
        # response = wa_client.upload_skiptrace_data(data, call_result, customer_id, is_payment)

        # if response:
        if ptp_date:

            with transaction.atomic():
                # Create PTP Entry
                ptp_amount = data['skip_ptp_amount']
                ptp = PTP.objects.filter(payment=payment).last()
                paid_ptp_status = ['Paid', 'Paid after ptp date']

                if payment.payment_status_id in PaymentStatusCodes.paid_status_codes():
                    return JsonResponse(status=400, data={
                            "status": "failed",
                            "message": "Tidak dapat tambah PTP, payment ini sudah lunas"
                    })

                if ptp:
                    if ptp.ptp_status and ptp.ptp_status in paid_ptp_status:
                        return JsonResponse(status=400, data={
                                "status": "failed",
                                "message": "Tidak dapat tambah PTP, payment ini sudah lunas"
                        })

                ptp_create(payment, ptp_date, ptp_amount, request.user)

                notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
                if skip_note:
                    notes = ", ".join([notes, skip_note])

                payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)

                PaymentNote.objects.create(
                    note_text=notes,
                    payment=payment,
                    extra_data={
                        'call_note': call_note
                    }
                )
        else:
            if skip_note:
                payment_note = {
                    'payment': payment,
                    'extra_data': {
                        'call_note': call_note
                    },
                    'note_text': skip_note
                }
                PaymentNote.objects.create(**payment_note)

        # delete intelix queue
        if call_result.name in ('RPC - Regular', 'RPC - PTP'):
            delete_paid_payment_from_intelix_if_exists_async.delay(payment.id)
        if call_result.name in \
                CollectionVendorAssignmentConstant.SKIPTRACE_CALL_STATUS_ASSIGNED_CRITERIA \
                and payment.bucket_number_special_case == 5:
            # check collection vendor assignment
            subbucket = get_current_sub_bucket(payment)
            assigned_payment_to_vendor = CollectionVendorAssignment.objects.filter(
                is_active_assignment=True, is_transferred_to_other__isnull=True,
                payment=payment
            )
            assigned_payment_to_agent = AgentAssignment.objects.filter(
                is_active_assignment=True, payment=payment,
                sub_bucket_assign_time=subbucket
            )
            if assigned_payment_to_vendor:
                assigned_vendor = assigned_payment_to_vendor.last()
                agent_assignment_message += 'failed add agent assignment because payment ' \
                                            'assigned to vendor {}'.format(
                                                assigned_vendor.vendor.vendor_name)
            if assigned_payment_to_agent:
                agent_assignment_data = assigned_payment_to_agent.last()
                agent_assignment_message += 'failed add agent assignment because payment ' \
                                            'assigned to agent {}'.format(
                                                agent_assignment_data.agent.username)

            if not assigned_payment_to_vendor and not assigned_payment_to_agent:
                assign_agent_for_bucket_5.delay(agent_user_id=request.user.id, loan_id=loan_id)
        #     logger.info({
        #         'response': response
        #     })
        # else:
        #     logger.error({
        #         'status': "centerix skiptrace details upload failed for " + str(data['skiptrace'])
        #     })
    return JsonResponse({
        "messages": "save success skiptrace history {}".format(agent_assignment_message),
        "data": SkiptraceSerializer(skiptrace).data
    })


@csrf_protect
def load_call_result(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])
    call_result = SkiptraceResultChoice.objects.all().order_by("id")

    if not call_result:
        return HttpResponseNotFound("no call result choices found")

    call_result_list = [[item.id, item.name] for item in call_result]
    return JsonResponse({
        "messages": "load success",
        "data": call_result_list
    })

from juloserver.julo.utils import generate_transaction_id
from juloserver.julo.partners import get_doku_client
from juloserver.julo.partners import DokuAccountType
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.statuses import PaymentStatusCodes,\
     JuloOneCodes
sentry_client = get_julo_sentry_client()

@csrf_protect
def get_doku_customer_balance(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])
    payment_id = request.GET.get('payment_id')
    payment = Payment.objects.get(pk=payment_id)
    customer = payment.loan.application.customer
    partner_referral = customer.partnerreferral_set.filter(pre_exist=False).first()
    account_id = partner_referral.partner_account_id

    doku_client = get_doku_client()

    try:
        customer_info = doku_client.check_balance(account_id)
    except JuloException as e:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "message": "failed get doku customer info"
        })
    data ={
        "doku_id" : customer_info["dokuId"],
        "doku_balance": customer_info["lastBalance"]
    }
    return JsonResponse({
        "status": "success",
        "data": data
    })

@csrf_protect
def autodebit_payment_from_doku(request):

    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    payment_id = request.GET.get('payment_id')
    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment is None:
        return JsonResponse({
            "status": "failed",
            "message": "payment id %s is not found" % (payment_id)
        })

    if payment.status in PaymentStatusCodes.paid_status_codes():
        return JsonResponse({
            "status": "failed",
            "message": "autodebet is not allowed!!"
        })

    application = payment.loan.application
    customer = application.customer
    partner_referral = customer.partnerreferral_set.filter(pre_exist=False).first()
    account_id = partner_referral.partner_account_id
    doku_client = get_doku_client()
    try:
        customer_info = doku_client.check_balance(account_id)
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "message": "failed get customer info"
        })

    customer_balance = customer_info['lastBalance']
    minimum_balance = 100000
    due_amount = payment.due_amount

    if customer_balance >= due_amount:
        transfer_amount = due_amount
    elif minimum_balance <= customer_balance < due_amount:
        transfer_amount = customer_balance
    else:
        return JsonResponse({
            "status": "failed",
            "message": "customer doesn't have enough balance"
        })

    transaction_id = generate_transaction_id(application.application_xid)
    try:
        init_transfer = doku_client.transfer(account_id, transaction_id, transfer_amount)
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "message": "connection failed to doku, transfer failed"
        })

    tracking_id = init_transfer["trackingId"]
    try:
        confirmed_transfer = doku_client.confirm_transfer(tracking_id)
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "message": "connection failed to doku, confirm transfer failed"
        })
    payment_receipt = confirmed_transfer['transactionId']
    notes = "doku payment success with paid amount: %s, transaction id: %s, tracking_id: %s" % (
        transfer_amount, payment_receipt, tracking_id)
    payment_method = PaymentMethod.objects.filter(
        loan=payment.loan, payment_method_code=PaymentMethodCodes.DOKU).first()

    ret_status = process_partial_payment(payment,
                                         transfer_amount,
                                         notes,
                                         payment_receipt=payment_receipt,
                                         payment_method=payment_method)
    if not ret_status:
        return JsonResponse({
            "status": "failed",
            "message": "success autodebit doku gagal save payment_event"
        })
    return JsonResponse({
        "status": "success",
        "message": "success autodebit doku"
    })

@csrf_protect
def ajax_update_agent(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    # get params
    data = request.POST.dict()
    payment_id = int(data['payment_id'])
    new_agent_id = int(data['new_agent_id'])
    current_agent_id = int(data['current_agent_id'])
    usergroup = data['usergroup']
    # check agent same
    if new_agent_id == current_agent_id:
        return JsonResponse({
            "status": "failed",
            "message": "Agent same."
        })
    # check payment
    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment is None:
        return JsonResponse({
            "status": "failed",
            "message": "payment id %s is not found" % (payment_id)
        })
    # check agent
    new_agent = User.objects.get(pk=new_agent_id)
    current_agent = User.objects.get(pk=current_agent_id)
    if new_agent is None or current_agent is None:
        return JsonResponse({
            "status": "failed",
            "message": "agent id (%s,%s) is not found" % (new_agent_id,current_agent_id)
        })
    # check loan agent
    loan = payment.loan
    application = loan.application
    agent_assignment_type = convert_usergroup_to_agentassignment_type(usergroup)
    current_agent_assignments = CollectionAgentAssignment.objects.filter(
                            agent=current_agent,
                            loan=loan,
                            type=agent_assignment_type,
                            unassign_time__isnull=True
                         )
    if current_agent_assignments is None:
        return JsonResponse({
            "status": "failed",
            "message": "current loan agent notfound"
        })
    try:
        with transaction.atomic():
            today = timezone.localtime(timezone.now())
            for current_agent_assignment in current_agent_assignments:
                current_agent_assignment.unassign_time = today
                current_agent_assignment.save()
                new_agent_assignment= CollectionAgentAssignment.objects.create(
                        loan= loan,
                        payment= current_agent_assignment.payment,
                        agent= new_agent,
                        type= agent_assignment_type,
                        assign_time= today)
        logger.info({
            'action': 'change_loan_agent_via_crm',
            'current_agent_id': current_agent_id,
            'new_agent_id': new_agent_id,
            'current_agent_assignment_id': current_agent_assignment.id,
            'new_agent_assignment_id': new_agent_assignment.id,
        })
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "message": "Failed change agent"
        })
    return JsonResponse({
        "status": "success",
        "message": "Success update agent"
    })


def ajax_update_ptp(request):

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    payment_id = int(data['payment_id'])
    ptp_date_str = data['ptp_date']
    ptp_date = datetime.strptime(ptp_date_str, "%d-%m-%Y")
    ptp_robocall_mobile_phone = str(data['ptp_robo_mobile_phone'])
    robocall_template_id = data['robocall_template_id']
    is_ptp_robocall_active = data['is_ptp_robocall_active']
    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment is None:
        return JsonResponse({
            "status": "failed",
            "message": "payment id %s is not found" % (payment_id)
        })
    try:
        robocall_template = RobocallTemplate.objects.get_or_none(pk=int(robocall_template_id))
        if not robocall_template:
            return JsonResponse({
                "status": "failed",
                "message": "template not found"
            })
        with transaction.atomic():
            payment.ptp_date = ptp_date
            payment.ptp_robocall_phone_number = mask_phone_number_sync(ptp_robocall_mobile_phone)
            payment.is_ptp_robocall_active = False if is_ptp_robocall_active == "false" else True
            payment.ptp_robocall_template = robocall_template
            notes = "Promise to Pay : %s " % (ptp_date)
            payment.save(update_fields=['ptp_date',
                                        'is_ptp_robocall_active',
                                        'ptp_robocall_template',
                                        'ptp_robocall_phone_number',
                                        'udate'])
            payment_note = PaymentNote.objects.create(
                note_text=notes,
                payment=payment)
            logger.info({
                'payment_id': payment_id,
                'ptp_date': ptp_date,
                'payment_note': payment_note,
            })

        # block sms to partner
        if payment.loan.application.customer.can_notify:
            send_sms_update_ptp.delay(payment_id)

    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "message": "Failed update ptp"
        })
    return JsonResponse({
        "status": "success",
        "message": "Success update ptp"
    })


@csrf_protect
def update_robocall(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    payment_id = int(request.GET.get('payment_id'))
    payment = Payment.objects.get_or_none(id=payment_id)
    if payment is None:
        return JsonResponse({
            "status": "failed",
            "message": "payment id %s is not found" % (payment_id)
        })

    if payment.is_robocall_active is True:
        payment.is_robocall_active = False
        payment.save(update_fields=['is_robocall_active',
                                    'udate'])
    else:
        payment.is_robocall_active = True
        payment.save(update_fields=['is_robocall_active',
                                    'udate'])
    return JsonResponse({
        "status": "success",
        "message": "successfully updated"
    })


@csrf_protect
def julo_one_update_robocall(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    account_payment_id = int(request.GET.get('account_payment_id'))
    account_payment = AccountPayment.objects.get_or_none(id=account_payment_id)
    if account_payment is None:
        return JsonResponse({
            "status": "failed",
            "message": "Account payment id %s is not found" % account_payment_id
        })

    if account_payment.is_robocall_active is True:
        account_payment.update_safely(is_robocall_active=False)
    else:
        account_payment.update_safely(is_robocall_active=True)
    return JsonResponse({
        "status": "success",
        "message": "successfully updated"
    })


# -----------------------------   AJAX   START  ---------------------------------------

@csrf_protect
@julo_login_required
def check_payment_locked(request):
    # print "f(x) populate_reason INSIDE"
    # TODO: check only bo_data_verifier or document verifier role can access
    current_user = request.user
    max_agents_lock_payment = MAX_COUNT_LOCK_PAYMENT
    response_data = {}

    # check max agents locking app
    agent_locked_count = get_user_lock_count(current_user)
    # print "agent_locked_count: ", agent_locked_count

    if request.method == 'GET':
        payment_id = int(request.GET.get('payment_id'))
        payment_obj = Payment.objects.get_or_none(pk=payment_id)

        if payment_obj:
            ret_cek_payment = check_lock_payment(payment_obj, current_user)
            if ret_cek_payment[0] == 1:
                response_data['code'] = '01'
                response_data['result'] = 'successful!'
                response_data['reason'] = 'payment is allowed for this %s' % (current_user)
                return HttpResponse(
                    json.dumps(response_data),
                    content_type="application/json"
                )
            elif(agent_locked_count >= max_agents_lock_payment):
                response_data['code'] = '09'
                response_data['result'] = 'failed!'
                response_data['reason'] = 'payment lock oleh agent <code>%s</code> \
                telah lebih dari %d!' % (request.user, max_agents_lock_payment)
                return HttpResponse(
                    json.dumps(response_data),
                    content_type="application/json"
                )
            elif ret_cek_payment[0] == 2:
                payment_locked_obj = ret_cek_payment[1]
                response_data['code'] = '02'
                response_data['result'] = 'failed!'
                response_data['reason'] = (
                    'payment is locked for this',
                    lock_by_user(payment_locked_obj),
                    payment_locked_obj.first().status_code_locked,
                    datetime.strftime(
                        payment_locked_obj.first().ts_locked,
                        "%d %b %Y %H:%M:%S"
                    ),
                )
            else:
                response_data['code'] = '03'
                response_data['result'] = 'successful!'
                response_data['reason'] = 'payment is free and still not locked'

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                'code': '99',
                "reason": "this isn't happening",
                'result': "nok"
            }),
            content_type="application/json"
        )


@csrf_protect
@julo_login_required
def set_payment_locked(request):
    """
    """
    max_agents_lock_payment = MAX_COUNT_LOCK_PAYMENT
    current_user = request.user
    response_data = {}

    # check max agents locking app
    agent_locked_count = get_user_lock_count(current_user)
    # print "agent_locked_count: ", agent_locked_count

    if(agent_locked_count >= max_agents_lock_payment):
        response_data['result'] = 'failed!'
        response_data['reason'] = 'payment lock by agent <code>%s</code> \
        telah lebih dari %d!' % (request.user, max_agents_lock_payment)
        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )

    if request.method == 'GET':

        payment_id = int(request.GET.get('payment_id'))
        payment_obj = Payment.objects.get_or_none(pk=payment_id)

        if payment_obj and request.user:
            ret_master = PaymentLockedMaster.create(
                user=request.user, payment=payment_obj, locked=True)
            if ret_master:
                PaymentLocked.create(
                    payment=payment_obj, user=request.user,
                    status_code_locked=payment_obj.payment_status.status_code)
                response_data['result'] = 'successful!'
                response_data['reason'] = 'payment is locked'
            else:
                ret_master_obj = PaymentLockedMaster.objects.get_or_none(
                    payment=payment_obj)
                response_data['result'] = 'failed!'
                if ret_master_obj:
                    response_data['reason'] = 'Payment telah di lock oleh %s dengan TS: \
                    %s' % (ret_master_obj.user_lock, ret_master_obj.ts_locked)
                else:
                    response_data['reason'] = 'Payment telah di lock'
        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'user not login or payment not exist'

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "reason": "this isn't happening",
                'result': "nok"
            }),
            content_type="application/json"
        )


@csrf_protect
def set_payment_unlocked(request):
    """
    """
    current_user = request.user
    # print "current_user: ", current_user

    if request.method == 'GET':

        payment_id = int(request.GET.get('payment_id'))
        payment_obj = Payment.objects.get_or_none(pk=payment_id)

        response_data = {}
        if payment_obj and current_user:
            payment_locked_master = PaymentLockedMaster.objects.get_or_none(payment=payment_obj)

            if payment_locked_master:
                payment_locked = PaymentLocked.objects.filter(
                    payment=payment_obj, user_lock=current_user, locked=True)

                if payment_locked.count() > 0:
                    print("app_locked: ", payment_locked[0].user_lock)
                    unlocked_payment(payment_locked[0], current_user)

                    response_data['result'] = 'successful!'
                    response_data['reason'] = 'Payment <code>%s</code> \
                    Succesfully Un-Locked' % payment_obj.id

                    # delete master locked
                    payment_locked_master.delete()

                else:
                    flag_admin = True
                    # check if admin, so it can be unlocked
                    if role_allowed(current_user,
                                    ['admin_unlocker', 'collection_supervisor',
                                     'ops_supervisor', 'ops_team_leader']):
                        payment_locked_here = PaymentLocked.objects.filter(
                            payment=payment_obj, locked=True).first()
                        if payment_locked_here:
                            unlocked_payment(
                                payment_locked_here, current_user,
                                payment_obj.payment_status.status_code
                            )
                            response_data['result'] = 'successful!'
                            response_data['reason'] = 'Payment <code>%s</code> \
                            Succesfully Un-Locked by Admin' % payment_obj.id

                            # delete master locked
                            payment_locked_master.delete()

                        else:
                            flag_admin = False
                    else:
                        flag_admin = False

                    if (not flag_admin):
                        response_data['result'] = 'failed!'
                        response_data['reason'] = 'payment is lock by %s, \
                        you are not allowed to unlock!' % (payment_locked_master.user_lock)
            else:
                response_data['result'] = 'failed!'
                response_data['reason'] = 'payment locked master not exists, \
                payment still not un-locked, please refresh your browser!'
        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'user not login or payment not exist'

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "reason": "this isn't happening",
                'result': "nok"
            }),
            content_type="application/json"
        )


@csrf_protect
def set_payment_called(request):
    """
    """
    current_user = request.user
    response_data = {}

    if request.method == 'GET':
        payment_id = int(request.GET.get('payment_id'))
        note_text = request.GET.get('note_text')
        payment_obj = GhostPayment.objects.get_or_none(pk=payment_id)

        if payment_obj and request.user:
            dpd_note = "+"+payment_obj.dpd if "-" not in payment_obj.dpd else payment_obj.dpd
            payment_note = PaymentNote.objects.create(
                            note_text="contacted T%s by Agent %s \n %s" % (dpd_note, current_user, note_text),
                            payment=payment_obj)
            logger.info({
                'payment_note': payment_note,
            })
            payment_obj.is_collection_called = True
            payment_obj.save()
            # delete data from primo
            delete_from_primo_payment(payment_obj, PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS)

            # unlock payment
            payment_locked_master = PaymentLockedMaster.objects.get_or_none(payment=payment_obj)
            if payment_locked_master:
                payment_locked = PaymentLocked.objects.filter(
                    payment=payment_obj, user_lock=current_user, locked=True)
                if payment_locked.count() > 0:
                    logger.info({
                        "app_locked": payment_locked[0].user_lock,
                    })
                    unlocked_payment(payment_locked[0], current_user)
                    # delete master locked
                    payment_locked_master.delete()

            response_data['result'] = 'success'
            response_data['reason'] = 'Payment <code>%s</code> \
                            Succesfully set called by %s' % (payment_obj.id, current_user)

        else:
            response_data['result'] = 'failed'
            response_data['reason'] = 'user not login or payment not exist'

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "reason": "this isn't happening",
                'result': "nok"
            }),
            content_type="application/json"
        )


@csrf_protect
def ajax_payment_list_view(request):

    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    if not getattr(request.user, 'agent', None):
        return HttpResponse(
            json.dumps({
                "status": "failed",
                "message": "Session Login Expired, Silahkan Login Kembali"
            }),
            content_type="application/json"
        )

    qs = Payment.objects.select_related('loan', 'loan__application', 'loan__application__partner')\
        .exclude(is_restructured=True)
    status_code = request.GET.get('status_code')
    max_per_page = int(request.GET.get('max_per_page'))
    here_title_status = None
    user = request.user
    agent_service = get_agent_service()
    squad = getattr(request.user.agent, 'squad', None)

    # searching
    special_condition = request.GET.get('filter_special_condition')
    if special_condition:
        spacial_condition_filter_ = {}
        spacial_condition_filter_['loan__' + special_condition] = True

        oldest_payment_ids = Payment.objects.filter(
            payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME).\
            order_by('loan', 'id').distinct('loan').values_list('id', flat=True)
        spacial_condition_filter_['id__in'] = oldest_payment_ids

        if spacial_condition_filter_:
            qs = qs.filter(**spacial_condition_filter_)


    #experimental for new group of buckets
    collection_agent_service = get_agent_service_for_bucket()

    sort_partner = request.GET.get('sort_partner')

    try:
        page = int(request.GET.get('page'))
    except:
        page = 1

    # new flow for ICare client
    if status_code and status_code == 'partner':
        qs = qs.filter(loan__application__partner__name__in=PartnerConstant.form_partner())\
               .normal()
    elif squad is None or status_code == 'all':
        exclude_partner_ids = Partner.objects.filter(name__in=PartnerConstant.form_partner())\
                                                .values_list('id', flat=True)
        qs = qs.exclude(loan__application__partner__id__in=exclude_partner_ids)

    if status_code != 'None':
        _title_status = payment_parse_pass_due(status_code)
        here_title_status = _title_status
        if _title_status:
            if _title_status[0] == 6:
                qs = qs.dpd_groups()
            elif _title_status[0] < 0:
                qs = qs.dpd_to_be_called().overdue()
            elif _title_status[0] == 1:
                qs = check_cootek_experiment(qs.dpd_groups_minus1(exclude_stl=True), -1)
            elif _title_status[0] == 3:
                qs = qs.dpd_groups_minus3()
            elif _title_status[0] == 5:
                qs = qs.dpd_groups_minus5()
            elif _title_status[0] == 15:
                qs = qs.dpd_groups_1to5()
            elif _title_status[0] == 'PTP':
                qs = qs.filter(ptp_date__isnull=False)
            elif _title_status[0] == 531:
                qs = qs.dpd_groups_minus5and3and1()
            elif _title_status[0] == 14:
                qs = qs.overdue_group_plus_with_range(1, 4)
            elif _title_status[0] == 530:
                qs = qs.overdue_group_plus_with_range(5, 30)
            elif _title_status[0] == 30:
                qs = qs.overdue_group_plus30()
            elif _title_status[0] == 1000:
                qs = qs.uncalled_group()
            elif _title_status[0] == 1001:
                qs = check_cootek_experiment(qs.due_group0().filter(is_whatsapp=False), 0)
            elif _title_status[0] == 1002:
                qs = qs.grab_0plus()
            elif _title_status[0] == 1003:
                qs = qs.filter(is_whatsapp=True, payment_status__lte=PaymentStatusCodes.PAYMENT_DUE_TODAY)
            elif _title_status[0] == 10014:
                # collection bucket 2a dpd 1 to 4
                qs = agent_service.filter_payments_by_agent_and_type(qs.overdue_group_plus_with_range(1, 4), user, DPD1_DPD15)
            elif _title_status[0] == 100515:
                # collection bucket 2a dpd 5 to 15
                qs = agent_service.filter_payments_by_agent_and_type(qs.overdue_group_plus_with_range(5, 15), user, DPD1_DPD15)
            elif _title_status[0] == 1001629:
                # collection agent bucket2b dpd16 to 29
                qs = agent_service.filter_payments_by_agent_and_type(qs.overdue_group_plus_with_range(16, 29), user, DPD16_DPD29)
            elif _title_status[0] == 1003044:
                # collection agent bucket3a dpd30 - 44
                qs = agent_service.filter_payments_by_agent_and_type(qs.overdue_group_plus_with_range(30, 44), user, DPD30_DPD44)
            elif _title_status[0] == 1004559:
                # collection agent bucket 3b dpd45 to 59
                qs = agent_service.filter_payments_by_agent_and_type(qs.overdue_group_plus_with_range(45, 59), user, DPD45_DPD59)
            elif _title_status[0] == 1006074:
                qs = agent_service.filter_payments_by_agent_and_type(qs.overdue_group_plus_with_range(60, 74), user, DPD60_DPD89)
            elif _title_status[0] == 1007589:
                qs = agent_service.filter_payments_by_agent_and_type(qs.overdue_group_plus_with_range(75, 89), user, DPD60_DPD89)
            elif _title_status[0] == 10090119:
                qs = agent_service.filter_payments_by_agent_and_type(qs.overdue_group_plus_with_range(90, 119), user, DPD90PLUS)
            elif _title_status[0] == 100120179:
                qs = agent_service.filter_payments_by_agent_and_type(qs.overdue_group_plus_with_range(120, 179), user, DPD90PLUS)
            elif _title_status[0] == 111180:
                qs = agent_service.filter_payments_by_agent_and_type(qs.overdue_group_plus180(), user, DPD90PLUS)
            elif _title_status[0] == 1000001:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(ptp_date__isnull=False, loan__is_ignore_calls=False), user, DPD1_DPD29)
            elif _title_status[0] == 1000002:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(ptp_date__isnull=False, loan__is_ignore_calls=False), user, DPD30_DPD59)
            elif _title_status[0] == 1000003:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(loan__is_ignore_calls=True), user, DPD30_DPD59)
            elif _title_status[0] == 1000004:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(loan__is_ignore_calls=False, is_whatsapp=True), user, DPD1_DPD29)
            elif _title_status[0] == 1000005:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(loan__is_ignore_calls=False, is_whatsapp=True), user, DPD30_DPD59)
            elif _title_status[0] == 1000006:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(ptp_date__isnull=False, loan__is_ignore_calls=False), user, DPD60_DPD89)
            elif _title_status[0] == 1000007:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(ptp_date__isnull=False, loan__is_ignore_calls=False), user, DPD90PLUS)
            elif _title_status[0] == 1000008:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(loan__is_ignore_calls=False, is_whatsapp=True), user, DPD60_DPD89)
            elif _title_status[0] == 1000009:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(loan__is_ignore_calls=False, is_whatsapp=True), user, DPD90PLUS)
            elif _title_status[0] == 1000010:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(loan__is_ignore_calls=True), user, DPD60_DPD89)
            elif _title_status[0] == 1000011:
                qs = agent_service.filter_payments_by_agent_and_type(qs.filter(loan__is_ignore_calls=True), user, DPD90PLUS)
            elif _title_status[0] == 10214:
                qs = qs.overdue_group_plus_with_range(1, 4)
            elif _title_status[0] == 102515:
                qs = qs.overdue_group_plus_with_range(5, 15)
            elif _title_status[0] == 1021629:
                qs = qs.overdue_group_plus_with_range(16, 29)
            elif _title_status[0] == 1023044:
                qs = qs.overdue_group_plus_with_range(30, 44)
            elif _title_status[0] == 1024559:
                qs = qs.overdue_group_plus_with_range(45, 59)
            elif _title_status[0] == 1026074:
                qs = qs.overdue_group_plus_with_range(60, 74)
            elif _title_status[0] == 1027589:
                qs = qs.overdue_group_plus_with_range(75, 89)
            elif _title_status[0] == 10290119:
                qs = qs.overdue_group_plus_with_range(90, 119)
            elif _title_status[0] == 102120179:
                qs = qs.overdue_group_plus_with_range(120, 179)
            elif _title_status[0] == 112180:
                qs = qs.overdue_group_plus180()
            elif _title_status[0] == 112101:
                qs = qs.bucket_5_list()
            elif _title_status[0] == 1030014:
                oldest_payment_ids = get_oldest_payment_ids_loans()
                qs = qs.bucket_1_t1_t4([]).filter(id__in=oldest_payment_ids)
            elif _title_status[0] == 1030510:
                oldest_payment_ids = get_oldest_payment_ids_loans()
                qs = qs.bucket_1_t5_t10([]).filter(id__in=oldest_payment_ids)
            elif _title_status[0] == 1050110:
                oldest_payment_ids = get_oldest_payment_ids_loans()
                qs = qs.bucket_1_ptp([]).filter(id__in=oldest_payment_ids)
            elif _title_status[0] == 1060110:
                oldest_payment_ids = get_oldest_payment_ids_loans()
                qs = qs.bucket_1_wa([]).filter(id__in=oldest_payment_ids)
            elif _title_status[0] in (11510102, 11510101):
                oldest_payment_ids = get_oldest_payment_ids_loans()

                if _title_status[0] == 11510102:
                    qs = qs.bucket_1_t_minus_3([]).filter(id__in=oldest_payment_ids)
                else:
                    qs = qs.bucket_1_t_minus_5([]).filter(id__in=oldest_payment_ids)
            elif _title_status[0] == 11510103:
                oldest_payment_ids = get_oldest_payment_ids_loans()
                qs = check_cootek_experiment(qs.bucket_cootek([], True, 1).filter(id__in=oldest_payment_ids), -1)
            elif _title_status[0] == 11510104:
                oldest_payment_ids = get_oldest_payment_ids_loans()
                qs = check_cootek_experiment(qs.bucket_cootek([], True, 0).filter(id__in=oldest_payment_ids), 0)
            elif _title_status[0] == 1031125:
                qs = CollectionHistory.objects.get_bucket_t11_to_t25(squad.id)
            elif _title_status[0] == 1032640:
                qs = CollectionHistory.objects.get_bucket_t26_to_t40(squad.id)
            elif _title_status[0] == 1034155:
                qs = CollectionHistory.objects.get_bucket_t41_to_t55(squad.id)
            elif _title_status[0] == 1035670:
                qs = CollectionHistory.objects.get_bucket_t56_to_t70(squad.id)
            elif _title_status[0] == 1037185:
                qs = CollectionHistory.objects.get_bucket_t71_to_t85(squad.id, user.id)
            elif _title_status[0] == 10386100:
                qs = CollectionHistory.objects.get_bucket_t86_to_t100(squad.id, user.id)
            elif _title_status[0] == 1040014 or _title_status[0] == 1070014:
                qs = qs.bucket_list_t1_to_t4()
            elif _title_status[0] == 1040510 or _title_status[0] == 1070510:
                qs = qs.bucket_list_t5_to_t10()
            elif _title_status[0] == 1041125 or _title_status[0] == 1071125:
                non_contact_payment_ids = CollectionHistory.objects.filter(excluded_from_bucket=True)\
                    .values_list('payment_id', flat=True)
                vendor_loan_ids = CollectionAgentTask.objects.get_bucket_2_vendor()\
                    .values_list('loan_id', flat=True)
                excluded_bucket_loan_ids = SkiptraceHistory.objects.get_non_contact_bucket2()\
                    .values_list('loan_id', flat=True)

                qs = qs.bucket_list_t11_to_t25()\
                    .exclude(pk__in=non_contact_payment_ids)\
                    .exclude(loan_id__in=vendor_loan_ids)\
                    .exclude(loan_id__in=excluded_bucket_loan_ids)
            elif _title_status[0] == 1042640 or _title_status[0] == 1072640:
                non_contact_payment_ids = CollectionHistory.objects.filter(excluded_from_bucket=True)\
                    .values_list('payment_id', flat=True)
                vendor_loan_ids = CollectionAgentTask.objects.get_bucket_2_vendor()\
                    .values_list('loan_id', flat=True)
                excluded_bucket_loan_ids = SkiptraceHistory.objects.get_non_contact_bucket2()\
                    .values_list('loan_id', flat=True)

                qs = qs.bucket_list_t26_to_t40()\
                    .exclude(pk__in=non_contact_payment_ids)\
                    .exclude(loan_id__in=vendor_loan_ids)\
                    .exclude(loan_id__in=excluded_bucket_loan_ids)
            elif _title_status[0] == 1044155 or _title_status[0] == 1074155:
                non_contact_payment_ids = CollectionHistory.objects.filter(excluded_from_bucket=True)\
                    .values_list('payment_id', flat=True)
                vendor_loan_ids = CollectionAgentTask.objects.get_bucket_3_vendor()\
                    .values_list('loan_id', flat=True)
                excluded_bucket_loan_ids = SkiptraceHistory.objects.get_non_contact_bucket3()\
                    .values_list('loan_id', flat=True)

                qs = qs.bucket_list_t41_to_t55()\
                    .exclude(pk__in=non_contact_payment_ids)\
                    .exclude(loan_id__in=vendor_loan_ids)\
                    .exclude(loan_id__in=excluded_bucket_loan_ids)
            elif _title_status[0] == 1045670 or _title_status[0] == 1075670:
                non_contact_payment_ids = CollectionHistory.objects.filter(excluded_from_bucket=True)\
                    .values_list('payment_id', flat=True)
                vendor_loan_ids = CollectionAgentTask.objects.get_bucket_3_vendor()\
                    .values_list('loan_id', flat=True)
                excluded_bucket_loan_ids = SkiptraceHistory.objects.get_non_contact_bucket3()\
                    .values_list('loan_id', flat=True)

                qs = qs.bucket_list_t56_to_t70()\
                    .exclude(pk__in=non_contact_payment_ids)\
                    .exclude(loan_id__in=vendor_loan_ids)\
                    .exclude(loan_id__in=excluded_bucket_loan_ids)
            elif _title_status[0] == 1047185 or _title_status[0] == 1077185:
                non_contact_payment_ids = CollectionHistory.objects.filter(excluded_from_bucket=True)\
                    .values_list('payment_id', flat=True)
                vendor_loan_ids = CollectionAgentTask.objects.get_bucket_4_vendor()\
                    .values_list('loan_id', flat=True)
                excluded_bucket_loan_ids = SkiptraceHistory.objects.get_non_contact_bucket4()\
                    .values_list('loan_id', flat=True)

                qs = qs.bucket_list_t71_to_t85()\
                    .exclude(pk__in=non_contact_payment_ids)\
                    .exclude(loan_id__in=vendor_loan_ids)\
                    .exclude(loan_id__in=excluded_bucket_loan_ids)
            elif _title_status[0] == 10486100 or _title_status[0] == 10786100:
                non_contact_payment_ids = CollectionHistory.objects.filter(excluded_from_bucket=True)\
                    .values_list('payment_id', flat=True)
                vendor_loan_ids = CollectionAgentTask.objects.get_bucket_4_vendor()\
                    .values_list('loan_id', flat=True)
                excluded_bucket_loan_ids = SkiptraceHistory.objects.get_non_contact_bucket4()\
                    .values_list('loan_id', flat=True)

                qs = qs.bucket_list_t86_to_t100()\
                    .exclude(pk__in=non_contact_payment_ids)\
                    .exclude(loan_id__in=vendor_loan_ids)\
                    .exclude(loan_id__in=excluded_bucket_loan_ids)
            elif _title_status[0] == 10310100:
                oldest_payment_ids = get_oldest_payment_ids_loans()
                qs = qs.bucket_5_list().filter(id__in=oldest_payment_ids)
            elif _title_status[0] == 10410100 or _title_status[0] == 10710100:
                qs = qs.bucket_5_list()
            elif _title_status[0] in (1051140, 1054170, 10571100, 10510100):
                qs = CollectionHistory.objects.get_bucket_ptp(squad.id, request.user.id)
            elif _title_status[0] in (1061140, 1064170, 10671100, 10610100):
                qs = CollectionHistory.objects.get_bucket_wa(squad.id)
            elif _title_status[0] == 1080110 or _title_status[0] == 1090110:
                qs = qs.list_bucket_1_group_ptp_only()
            elif _title_status[0] == 1081140 or _title_status[0] == 1091140:
                qs = qs.list_bucket_2_group_ptp_only()
            elif _title_status[0] == 1084170 or _title_status[0] == 1094170:
                qs = qs.list_bucket_3_group_ptp_only()
            elif _title_status[0] == 10871100 or _title_status[0] == 10971100:
                qs = qs.list_bucket_4_group_ptp_only()
            elif _title_status[0] == 10810100 or _title_status[0] == 10910100:
                qs = qs.list_bucket_5_group_ptp_only()
            elif _title_status[0] == 1100110 or _title_status[0] == 1110110:
                qs = qs.list_bucket_1_group_wa_only()
            elif _title_status[0] == 1101140 or _title_status[0] == 1111140:
                qs = qs.list_bucket_2_group_wa_only()
            elif _title_status[0] == 1104170 or _title_status[0] == 1114170:
                qs = qs.list_bucket_3_group_wa_only()
            elif _title_status[0] == 11071100 or _title_status[0] == 11171100:
                qs = qs.list_bucket_4_group_wa_only()
            elif _title_status[0] == 11010100 or _title_status[0] == 11110100:
                qs = qs.list_bucket_5_group_wa_only()
            elif _title_status[0] in (1124170, 11271100, 11210100):
                qs = CollectionHistory.objects.get_bucket_ignore_called(squad.id)
            elif _title_status[0] == 1134170 or _title_status[0] == 1144170:
                qs = qs.list_bucket_3_group_ignore_called_only()
            elif _title_status[0] == 11371100 or _title_status[0] == 11471100:
                qs = qs.list_bucket_4_group_ignore_called_only()
            elif _title_status[0] == 11310100 or _title_status[0] == 11410100:
                qs = qs.list_bucket_5_group_ignore_called_only()
            elif _title_status[0] == 1020001:
                qs = qs.filter(ptp_date__isnull=False)
            elif _title_status[0] == 1020002:
                qs = qs.filter(loan__is_ignore_calls=True)
            elif _title_status[0] == 1020003:
                qs = qs.filter(is_whatsapp=True)
            elif _title_status[0] in (11600000, 11700000, 11800000):
                qs = CollectionHistory.objects.get_bucket_non_contact(squad.id)
            elif _title_status[0] == 11900000:
                b2_squad_ids = CollectionSquad.objects\
                    .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_2)\
                    .values_list('id', flat=True)
                qs = CollectionHistory.objects.get_bucket_non_contact_squads(b2_squad_ids)
            elif _title_status[0] == 12000000:
                b3_squad_ids = CollectionSquad.objects\
                    .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_3)\
                    .values_list('id', flat=True)
                qs = CollectionHistory.objects.get_bucket_non_contact_squads(b3_squad_ids)
            elif _title_status[0] == 12100000:
                b4_squad_ids = CollectionSquad.objects\
                    .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_4)\
                    .values_list('id', flat=True)
                qs = CollectionHistory.objects.get_bucket_non_contact_squads(b4_squad_ids)
            elif _title_status[0] == 12200000:
                vendor_loan_ids = CollectionAgentTask.objects.get_bucket_2_vendor()\
                                                   .values_list('loan_id', flat=True)
                qs = qs.bucket_list_t11_to_t40().filter(loan_id__in=vendor_loan_ids)
            elif _title_status[0] == 12300000:
                vendor_loan_ids = CollectionAgentTask.objects.get_bucket_3_vendor()\
                                                   .values_list('loan_id', flat=True)
                qs = qs.bucket_list_t41_to_t70().filter(loan_id__in=vendor_loan_ids)
            elif _title_status[0] == 12400000:
                vendor_loan_ids = CollectionAgentTask.objects.get_bucket_4_vendor()\
                                                   .values_list('loan_id', flat=True)
                qs = qs.bucket_list_t71_to_t90().filter(loan_id__in=vendor_loan_ids)
            elif _title_status[0] == 12500000 or _title_status[0] == 12800000:
                qs = SkiptraceHistory.objects.get_non_contact_bucket2()
            elif _title_status[0] == 12600000 or _title_status[0] == 12900000:
                qs = SkiptraceHistory.objects.get_non_contact_bucket3()
            elif _title_status[0] == 12700000 or _title_status[0] == 13000000:
                qs = SkiptraceHistory.objects.get_non_contact_bucket4()
            elif 'Robo' in _title_status[0]:
                qs = qs.select_related('loan')\
                       .dpd_to_be_called()\
                       .due_soon(due_in_days=int(_title_status[0][0]))\
                       .filter(is_robocall_active=True,
                               loan__loan_status=LoanStatusCodes.CURRENT)\
                       .exclude(is_success_robocall=True)
            elif 'whatsapp_blasted' in _title_status[0]:
                qs = qs.filter(is_whatsapp_blasted=True)
            status_code = _title_status[1]
    else:
        status_code = "all"

    if sort_partner:
        qs = qs.filter(loan__application__partner_id=sort_partner)

    status_payment = None
    list_status = StatusLookup.objects.filter(status_code__gte=300).values('status_code', 'status')
    # list_agent_type = [{
    #                 'value': JuloUserRoles.COLLECTION_AGENT_2,
    #                 'label': '%s - %s' % (JuloUserRoles.COLLECTION_AGENT_2, DPD1_DPD29)
    #             },{
    #                 'value': JuloUserRoles.COLLECTION_AGENT_3,
    #                 'label': '%s - %s' % (JuloUserRoles.COLLECTION_AGENT_3, DPD30_DPD59)
    #             },{
    #                 'value': JuloUserRoles.COLLECTION_AGENT_4,
    #                 'label': '%s - %s' % (JuloUserRoles.COLLECTION_AGENT_4, DPD60_DPD89)
    #             },{
    #                 'value': JuloUserRoles.COLLECTION_AGENT_5,
    #                 'label': '%s - %s' % (JuloUserRoles.COLLECTION_AGENT_5, DPD90PLUS)
    #             },{
    #                 'value': JuloUserRoles.COLLECTION_AGENT_2A,
    #                 'label': '%s - %s' % (JuloUserRoles.COLLECTION_AGENT_2A, DPD1_DPD15)
    #             },{
    #                 'value': JuloUserRoles.COLLECTION_AGENT_2B,
    #                 'label': '%s - %s' % (JuloUserRoles.COLLECTION_AGENT_2B, DPD16_DPD29)
    #             },{
    #                 'value': JuloUserRoles.COLLECTION_AGENT_3A,
    #                 'label': '%s - %s' % (JuloUserRoles.COLLECTION_AGENT_3A, DPD1_DPD29)
    #             }]
    list_agent_type = []
    agent_roles = JuloUserRoles.collection_bucket_roles()
    for role in agent_roles:
        list_agent_type.append(
            dict(value=role,
                 label='{} - {}'.format(
                     role, convert_usergroup_to_agentassignment_type(role))
                 )
        )

    list_agent = User.objects.filter(groups__name__in=agent_roles,
                                      is_active=True)\
                              .order_by('id')\
                              .values('id', 'username', 'groups__name')
    sort_q = request.GET.get('sort_q', None)
    sort_agent = request.GET.get('sort_agent', None)
    status_payment = request.GET.get('status_app', None)

    if status_payment and status_code in ['all', 'partner']:
        qs = qs.filter(payment_status__status_code=status_payment)

    search_q = request.GET.get('search_q', None).strip()
    today_checked = request.GET.get('today_checked', None)
    freeday_checked = request.GET.get('freeday_checked', None)
    range_date = request.GET.get('range_date', None)
    autodialer_result = AutoDialerRecord.objects.all()\
                                                .order_by('payment_id')\
                                                .values('payment_id','call_status')

    if isinstance(search_q, str) and search_q:
        field, keyword = payment_filter_search_field(search_q)

        if field:
            if field == 'loan__customer_id':
                qs = qs.filter(**{('%s__in' % field): keyword})
            elif field == 'loan__application__fullname':
                qs = qs.filter(**{('%s__icontains' % field): keyword})
            else:
                qs = qs.filter(**{field: keyword})
        else:
            qs = qs.filter(**{('%s__contains' % 'loan__julo_bank_account_number'): keyword})

    if today_checked != 'false' or freeday_checked != 'false' and range_date != '':
        # print "OKAY STATUS NOW : ", self.status_now
        if today_checked == 'true':
            # print "HARI INI"
            startdate = datetime.today()
            startdate = startdate.replace(hour=0, minute=0, second=0)
            enddate = startdate + timedelta(days=1)
            enddate = enddate - timedelta(seconds=1)
            qs = qs.filter(cdate__range=[startdate, enddate])

        elif freeday_checked == 'true':
            _date_range = range_date.split('-')
            if(_date_range[0].strip() != 'Invalid date'):
                _tgl_mulai = datetime.strptime(_date_range[0].strip(), "%d/%m/%Y %H:%M")
                _tgl_end = datetime.strptime(_date_range[1].strip(), "%d/%m/%Y %H:%M")
                # print "BEBAS"
                if(_tgl_end > _tgl_mulai):
                    qs = qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                else:
                    return HttpResponse(
                        json.dumps({
                            "status": "failed",
                            "message": "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                        }),
                        content_type="application/json"
                    )
            else:
                return HttpResponse(
                    json.dumps({
                        "status": "failed",
                        "message": "Format Tanggal tidak valid"
                    }),
                    content_type="application/json"
                )

    # add dpd_sort for property sorting
    qs = qs.extra(
        select={
            'loan_status': 'loan.loan_status_code',
            'dpd_sort': "payment.due_date",
            'dpd_ptp_sort': "CASE WHEN payment.ptp_date is not Null THEN DATE_PART('day', ptp_date - CURRENT_TIMESTAMP) END"
        },
        tables=['loan'],
        where=['loan.loan_status_code != %s', 'loan.loan_id = payment.loan_id'],
        params=[StatusLookup.INACTIVE_CODE],
    )


    if status_code == 'all':
        qs = qs.extra(order_by=['-dpd_sort'])
    else:
        if here_title_status:
            _title_status_dpd_sort_list = (6, 15, 14, 530, 30)
            if 0 <= _title_status[0] <= 5 or _title_status[0] < 0 or _title_status[0] in _title_status_dpd_sort_list:
                qs = qs.extra(order_by=['-dpd_sort'])
            elif _title_status[0] == 531:
                qs = qs.extra(order_by=['dpd_sort'])

    if sort_q:
        if sort_q == 'loan_and_status_asc':
            qs = qs.order_by('loan__id', 'loan__loan_status__status_code')
        elif sort_q == 'loan_and_status_desc':
            qs = qs.order_by('-loan__id', '-loan__loan_status__status_code')
        elif sort_q == 'dpd':
            qs = qs.extra(order_by=['-dpd_sort'])
        elif sort_q == '-dpd':
            qs = qs.extra(order_by=['dpd_sort'])
        elif sort_q == 'dpd_ptp':
            qs = qs.extra(order_by=['dpd_ptp_sort'])
        elif(sort_q == '-dpd_ptp'):
            qs = qs.extra(order_by=['-dpd_ptp_sort'])
        else:
            qs = qs.order_by(sort_q)

    if sort_agent:
        if (sort_agent != ''):
            qs = agent_service.filter_payments_by_agent_id(qs, sort_agent)

    # for pagination

    if qs.model is Payment:
        collection_values = ['id', 'loan__application__product_line_id',\
            'loan__application__email','loan__application__fullname',\
            'is_robocall_active','payment_status_id','due_date','payment_number',\
            'loan_id','loan__loan_status_id', 'udate', 'cdate', 'loan__application__partner__name',\
            'loan__application_id', 'loan__application__customer_id',\
            'due_amount','late_fee_amount','cashback_earned','loan__application__mobile_phone_1',\
            'loan__application__ktp','loan__application__dob','loan__loan_amount',\
            'loan__loan_duration','loan__application__id','payment_status__status_code',\
            'loan__id','loan__application__email','loan__julo_bank_account_number',\
            'ptp_date', 'reminder_call_date', 'paid_date']
    elif qs.model is CollectionHistory:
        collection_values = ['payment__id', 'loan__application__product_line_id',\
            'loan__application__email','loan__application__fullname',\
            'payment__is_robocall_active','payment__payment_status_id','payment__due_date','payment__payment_number',\
            'loan_id','loan__loan_status_id', 'payment__udate', 'payment__cdate', 'loan__application__partner__name',\
            'loan__application_id', 'loan__application__customer_id',\
            'payment__due_amount','payment__late_fee_amount','payment__cashback_earned','loan__application__mobile_phone_1',\
            'loan__application__ktp','loan__application__dob','loan__loan_amount',\
            'loan__loan_duration','loan__application__id','payment__payment_status__status_code',\
            'loan__id','loan__application__email','loan__julo_bank_account_number',\
            'payment__ptp_date', 'payment__reminder_call_date', 'squad__squad_name', 'payment__paid_date']
    elif qs.model is SkiptraceHistory:
        collection_values = ['payment__id', 'loan__application__product_line_id',
            'loan__application__email','loan__application__fullname',
            'payment__is_robocall_active','payment__payment_status_id',
            'payment__due_date','payment__payment_number',
            'loan_id','loan__loan_status_id', 'payment__udate', 'payment__cdate',
            'loan__application__partner__name','loan__application__customer_id', 'payment__due_amount',
            'payment__late_fee_amount','payment__cashback_earned',
            'loan__application__mobile_phone_1','loan__application__ktp','loan__application__dob',
            'loan__loan_amount', 'loan__loan_duration',
            'loan__application_id','payment__payment_status__status_code',
            'loan__julo_bank_account_number', 'payment__ptp_date',
            'payment__reminder_call_date', 'payment__paid_date']

    processed_model = qs.model
    primary_key = 'id'

    three_next_pages = max_per_page * (page+2) + 1
    limit = max_per_page * page
    offset = limit - max_per_page
    result = qs.values_list(primary_key, flat=True)
    result = result[offset:three_next_pages]
    payment_ids = list(result)
    payment_ids_1page = payment_ids[:max_per_page]
    count_payment = len(payment_ids)
    count_page = page + (count_payment // max_per_page) + (count_payment % max_per_page > 0) - 1
    if count_payment == 0:
        count_page = page

    # this preserved is needed because random order by postgresql/django
    preserved = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(result)])
    payments = processed_model.objects.filter(**{primary_key+'__in':payment_ids_1page})\
                                      .order_by(preserved)\
                                      .values(*collection_values)

    # get agent
    payments = list(payments)

    if qs.model is Payment:
        payments = collection_agent_service.get_agent(payments)


    list_partner = Partner.objects.all().values('id', 'name')

    return JsonResponse({
        'status': 'success',
        'data': payments,
        'count_page': count_page,
        'current_page': page,
        'payment_lock_list': payment_lock_list(),
        'list_status': list(list_status),
        'list_agent': list(list_agent),
        'autodialer_result': list(autodialer_result),
        'list_agent_type':list_agent_type,
        'list_partner': list(list_partner),
        'payment_paid_status': PaymentStatusCodes.PAID_ON_TIME,
        'special_conditions': SpecialConditions.ALL,
    }, safe=False)


def ajax_cashback_event(request):

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    payment_id = int(data['payment_id'])
    cashback_amount = int(data['cashback_amount'])
    bank_name = data['bank_name']
    name_in_bank = data['name_in_bank']
    bank_account_number = data['bank_account_number']
    cashback_event_date = data['cashback_event_date']
    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment is None:
        return JsonResponse({
            "status": "failed",
            "message": "payment id %s is not found" % (payment_id)
        })
    try:
        notes = ('Redeemed Cashback : %s, \n'+
                  '-- Transfer to -- \n' +
                  'Bank name : %s, \n' +
                  'Name in bank : %s, \n' +
                  'Bank account no : %s, \n'+
                  'Transfer date : %s.') % (display_rupiah(cashback_amount), bank_name, name_in_bank, bank_account_number, cashback_event_date)
        with transaction.atomic():
            logger.info({
                'payment_id': payment_id,
                'cashback_amount': cashback_amount,
                'bank_name': bank_name,
                'name_in_bank': name_in_bank,
                'bank_account_number': bank_account_number,
                'event_date': cashback_event_date
            })
            event_datetime = datetime.strptime(cashback_event_date, "%d-%m-%Y")
            event_date = event_datetime.date()
            customer = payment.loan.customer
            customer.change_wallet_balance(change_accruing=-cashback_amount,
                                           change_available=-cashback_amount,
                                           reason='paid_back_to_customer',
                                           payment=payment,
                                           event_date=event_date)
            wallet_history_note = CustomerWalletNote.objects.create(
                note_text=notes,
                customer=customer,
                customer_wallet_history=customer.wallet_history.last())
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "message": "Failed action cashback event"
        })
    return JsonResponse({
        "status": "success",
        "message": "Success cashback event"
    })

def ajax_change_due_date_init(request):
    if request.method == 'GET':
        payment_id = int(request.GET.get('payment_id',0))
        payment = Payment.objects.get_or_none(pk=payment_id)
        start = (date.today() + relativedelta(days=1)).strftime('%d-%m-%Y')
        end = (date.today() + relativedelta(months=2)).strftime('%d-%m-%Y')
        change_due_date_interest = 55000

        if payment.change_due_date_interest > 0:
            change_due_date_interest = payment.change_due_date_interest

        response_data = {}

        response_data['result'] = 'successful!'
        response_data['start'] = start
        response_data['end'] = end
        response_data['change_due_date_interest'] = change_due_date_interest
        response_data['reason'] = "ALL OKE"
        response_data['set'] = (date.today() + relativedelta(months=1)).strftime('%d-%m-%Y')

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "reason": "this isn't happening",
                'result': "nok"
            }),
            content_type="application/json"
        )


def ajax_change_due_dates(request):

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    payment_id = int(data['payment_id'])
    new_date_str = data['new_date']
    new_change_due_date_interest = int(data['new_change_due_date_interest'])
    note = data['note']
    max_change_due_date_interest = PaymentConst.MAX_CHANGE_DUE_DATE_INTEREST
    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment is None:
        return JsonResponse({
            "status": "failed",
            "message": "payment id %s is not found" % (payment_id)
        })
    if new_change_due_date_interest > max_change_due_date_interest:
        return JsonResponse({
            "status": "failed",
            "message": "fee change due date can not be greater than %s" % (
                max_change_due_date_interest)
        })
    loan = payment.loan
    new_change_due_date_interest, is_max = loan.get_status_max_late_fee(
        new_change_due_date_interest)
    if is_max:
        return JsonResponse({
            "status": "failed",
            "message": "total late_fee and interest already reach max amount"
        })

    try:
        with transaction.atomic():
            process_change_due_date(payment, new_date_str, note, new_change_due_date_interest)
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "message": "Failed action change due date"
        })
    return JsonResponse({
        "status": "success",
        "message": "Success change due date"
    })


def ajax_update_reminder_call_date(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    payment_id = int(data['payment_id'])
    reminder_call_date = data['reminder_call_date']
    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment is None:
        return JsonResponse({
            "status": "failed",
            "message": "payment id %s is not found" % (payment_id)
        })
    try:
        logger.info({
            'payment_id': payment_id,
            'cashback_amount': reminder_call_date,
        })
        payment.reminder_call_date = datetime.strptime(reminder_call_date, "%d-%m-%Y %H:%M")
        payment.is_reminder_called = False
        payment.save(update_fields=['reminder_call_date',
                                    'is_reminder_called',
                                    'udate'])
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "message": "Failed update reminder date"
        })
    return JsonResponse({
        "status": "success",
        "message": "Success update reminder date"
    })


@csrf_protect
def set_payment_reminder(request):
    """
    """
    current_user = request.user
    response_data = {}

    if request.method == 'GET':

        payment_id = int(request.GET.get('payment_id'))
        payment_obj = GhostPayment.objects.get_or_none(pk=payment_id)

        if payment_obj and request.user:
            payment_obj.is_collection_called = True
            payment_obj.is_reminder_called = True
            payment_obj.save()
            response_data['result'] = 'successful!'
            response_data['reason'] = 'Succesfully set Reminder'

        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'user not login or payment not exist'

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "reason": "this isn't happening",
                'result': "nok"
            }),
            content_type="application/json"
        )


@julo_login_required
@julo_login_required_exclude(['bo_finance'])
def manual_payment_bulk_update(request):
    template_name = 'object/payment_status/manual_payment_csv_upload.html'
    error_message = ""
    user = request.user
    if request.method == 'POST':
        if not request.FILES.get('csv_file'):
            error_message = "Error!!!, file belum dipilih"
        else:
            file = request.FILES['csv_file']
            file_exist = CsvFileManualPaymentRecord.objects.get_or_none(filename=file.name)
            if file_exist:
                error_message = "Error!!!, file pernah diupload sebelumnya"
            elif file.content_type != "text/csv":
                error_message= "Error!!!, file type harus CSV"
            else:
                column = ["VA", "Amount", "Payment Date", "Payment Note / Bank Name"]
                report_column = ["Payment_Id", "Updated", "Message", "Email", "Name"]

                #determine delimiter
                coma = ','
                semicolon = ';'
                csv_file = file.read()
                count_coma = csv_file.find(coma)
                count_semicolon = csv_file.find(semicolon)
                delimiter = coma
                if count_semicolon > count_coma:
                    delimiter = semicolon

                rows = csv.DictReader(csv_file.splitlines(), delimiter=delimiter)
                headers = rows.fieldnames
                CsvFileManualPaymentRecord.objects.create(filename=file.name)

                if headers == column:
                    csv_report = io.StringIO()
                    report_writer = csv.writer(csv_report)
                    report_writer.writerow(column + report_column)
                    for row in rows:
                        row['Agent'] = user
                        result_data = save_payment_event_from_csv(row)
                        report_writer.writerow([
                            result_data["VA"],
                            result_data["Amount"],
                            result_data["Payment Date"],
                            result_data["Payment Note / Bank Name"],
                            result_data["Payment_Id"],
                            result_data["Updated"],
                            result_data["Message"],
                            result_data["Email"],
                            result_data["Name"],
                            ])
                    csv_report.flush()
                    csv_report.seek(0)  # move the pointer to the beginning of the buffer
                    response = HttpResponse(FileWrapper(csv_report), content_type='text/csv')
                    response['Content-Disposition'] = 'attachment; filename=report_' + file.name
                    return response
                else:
                    error_message = "Error!!!, format CSV tidak sesuai dengan template"
    elif request.method == 'GET':
        pass
    return render(request, template_name, {"error_message": error_message})

@csrf_protect
def reversal_payment_event_check_destination(request):
    current_user = request.user
    response_data = {}

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    payment_id = int(request.POST.get('payment_id'))
    payment_obj = Payment.objects.get_or_none(pk=payment_id)
    if payment_obj:
        if payment_obj.status in PaymentStatusCodes.paid_status_codes():
            response_data['result'] = 'failed'
            response_data['message'] = 'Payment id %s sudah lunas silahkan cek kembali' % payment_id
        else:
            application = payment_obj.loan.application
            response_data['result'] = 'success'
            response_data['message'] = '%s (%s)' % (application.fullname, application.id)
    else:
        response_data['result'] = 'failed'
        response_data['message'] = 'Payment id %s tidak ditemukan silahkan cek kembali' % payment_id

    return HttpResponse(
        json.dumps(response_data),
        content_type="application/json"
    )

@csrf_protect
def ajax_reversal_payment_event(request):
    """
    """
    current_user = request.user
    response_data = {}

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    event_object = PaymentEvent.objects.get(pk=data['event_id'])

    if not event_object:
        return HttpResponse(json.dumps({
            "result": "failed",
            "message": "payment event not found"
        }), content_type="application/json")

    if event_object.event_type not in ['payment', 'late_fee', 'customer_wallet']:
        return HttpResponse(json.dumps({
            "result": "failed",
            "message": "payment event not initiate process"
        }), content_type="application/json")

    payment_event_service = PaymentEventServices()
    if event_object.event_type == "payment":
        with transaction.atomic():
            status, event_void_obj = payment_event_service.process_reversal_event_type_payment(
                event_object, data['note'])

            if status and data['reason'] == PAYMENT_EVENT_CONST.REVERSAL_REASON_WRONG_PAYMENT:
                payment_event_service.process_transfer_payment_after_reversal(
                    event_object, data['payment_dest_id'], event_void_obj.id)

            create_reversal_transaction(event_void_obj, data['payment_dest_id'])
            update_cashback_balance_status(event_void_obj.payment.loan.customer)

    elif event_object.event_type == "late_fee":
        status = payment_event_service.process_reversal_event_type_late_fee(event_object, data['note'])
    elif event_object.event_type == "customer_wallet":
        status = payment_event_service.process_reversal_event_type_customer_wallet(event_object, data['note'])
    messages = "reverse payment event not success"
    result = 'failed'
    if status:
        messages = "reverse payment event success"
        result = 'success'
    return HttpResponse(
        json.dumps({
            "messages": messages,
            "result": result}),
        content_type="application/json")


@csrf_protect
def ajax_set_ignore_calls(request):
    """
    """
    current_user = request.user
    response_data = {}

    if request.method == 'GET':

        payment_id = int(request.GET.get('payment_id'))
        action_str = request.GET.get('action')
        action = True if action_str == 'true' else False
        payment_obj = GhostPayment.objects.get_or_none(pk=payment_id)
        message = 'Failed set ignore calls, payment not found'
        result = 'failed'
        if payment_obj and request.user:
            loan = payment_obj.loan
            if loan.is_ignore_calls == action:
                result = 'warning'
                message = 'Already set ignore calls'
            else:
                with transaction.atomic():
                    PaymentNote.objects.create(
                        note_text='Set %s Ignore Calls.' % (action_str),
                        payment=payment_obj)
                    loan.is_ignore_calls = action
                    loan.save()
                result = 'success'
                message = 'Succesfully set ignore calls'
        response_data['result'] = result
        response_data['reason'] = message

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "reason": "method not GET",
                'result': "failed"
            }),
            content_type="application/json"
        )


@csrf_protect
def ajax_set_payment_whatsapp(request):
    """
    """
    current_user = request.user
    response_data = {}

    if request.method == 'GET':

        payment_id = int(request.GET.get('payment_id'))
        payment_obj = GhostPayment.objects.get_or_none(pk=payment_id)

        if payment_obj and request.user:
            payment_obj.is_whatsapp = True
            payment_obj.save()
            response_data['result'] = 'successful!'
            response_data['reason'] = 'Succesfully set Whatsapp'

        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'user not login or payment not exist'

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "reason": "this isn't happening",
                'result': "nok"
            }),
            content_type="application/json"
        )


@csrf_protect
def ajax_save_whatsapp(request):
    """
    """
    current_user = request.user
    response_data = {}

    if request.method == 'GET':

        payment_id = int(request.GET.get('payment_id'))
        note = request.GET.get('note')
        payment_obj = GhostPayment.objects.get_or_none(pk=payment_id)

        if payment_obj and request.user:
            payment_obj.is_whatsapp = False
            payment_obj.save()
            text_notes = 'send to whatsapp %s.' % (note)
            PaymentNote.objects.create(
                note_text=text_notes,
                payment=payment_obj)
            response_data['result'] = 'successful!'
            response_data['reason'] = 'Succesfully set Whatsapp'

        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'user not login or payment not exist'

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "reason": "this isn't happening",
                'result': "nok"
            }),
            content_type="application/json"
        )


@csrf_protect
def ajax_change_first_settlement(request):
    if request.method == 'POST':
        message = ""
        cycle_date_requested = request.POST.get('new_date')
        payday_requested = request.POST.get('payday')
        payment_id = request.POST.get('payment_id')
        payment = Payment.objects.get_or_none(pk=payment_id)
        if not payment:
            return JsonResponse({
                "status": "failed",
                'message': "Payment tidak ditemukan"
            })
        if not payday_requested or not cycle_date_requested:
            return JsonResponse({
                "status": "failed",
                'message': "field wajib diisi"
            })
        loan = payment.loan
        try:
            with transaction.atomic():
                if payday_requested:
                    app = loan.application
                    if int(payday_requested) != app.payday:
                        app.payday = payday_requested
                        app.save()
                        message += "new payday, "
                if cycle_date_requested:
                    cycle_date_req_obj = datetime.strptime(cycle_date_requested.strip(), "%d-%m-%Y").date()

                    # proceed cycle day change
                    change_due_dates(loan, cycle_date_req_obj)

                    # save first payment installment
                    update_payment_installment(loan, cycle_date_req_obj)
                    message += "new installment date "
        except Exception as je:
            err_msg = "Error from Backend Process:"
            loan.refresh_from_db()
            err_msg = "%s %s" % (err_msg, str(je))
            logger.info({
                'ubah_cycle_day': 'ubah_cycle_day_installment_date',
                'loan_id': loan.id,
                'error': err_msg
            })
            return JsonResponse({
                "status": "failed",
                'message': err_msg
            })
        return JsonResponse({
            "status": "success",
            'message': message + "berhasil diupdate"
        })


@csrf_protect
def ajax_get_remaining_amount(request):
    if request.method == 'POST':
        payment_id = int(request.POST.get('payment_id'))
        event_type = request.POST.get('event_type')
        max_payment_number = int(request.POST.get('max_payment_number'))

        payment_obj = Payment.objects.get(pk=payment_id)
        if payment_obj:
            remaining_amount = eval("get_remaining_{}".format(event_type))(
                payment_obj, is_unpaid=True, max_payment_number=max_payment_number
            )
            if remaining_amount:
                return HttpResponse(
                    json.dumps({
                        "result": "success",
                        "remaining_amount": remaining_amount}),
                    content_type="application/json")

    return HttpResponse(
            json.dumps({
                "result": "failed",
                "remaining_amount": 0}),
            content_type="application/json")


@csrf_protect
def update_payment_note_for_collection(request):
    if request.method == "POST":
        payment_id = int(request.POST.get('payment_id')) if \
            request.POST.get('payment_id') else None
        account_payment_id = int(request.POST.get('account_payment_id')) if \
            request.POST.get('account_payment_id') else None
        account_payment = None
        payment = None
        dpd_note = '-'
        if payment_id:
            payment = Payment.objects.get_or_none(id=payment_id)
            account_payment = None
            dpd_note = "+" + str(payment.get_dpd) if "-" not in str(payment.get_dpd) else str(payment.get_dpd)
        elif account_payment_id:
            account_payment = AccountPayment.objects.get_or_none(id=account_payment_id)
            payment = None
            dpd_note = "+" + str(account_payment.dpd) if "-" not in str(account_payment.dpd) \
                else str(account_payment.dpd)
        note_text = "Agent {} (coll) telah melakukan revalidasi alamat".format(request.user)
        note = "contacted T%s by Agent %s \n %s" % (dpd_note, request.user, note_text)
        if payment_id:
            PaymentNote.objects.create(
                payment=payment,
                status_change=None,
                account_payment=account_payment,
                note_text=note
            )
        elif account_payment_id:
            AccountPaymentNote.objects.create(
                account_payment=account_payment,
                note_text=note,
                added_by=request.user
            )
        return HttpResponse(
            json.dumps({
                "result": "success"}),
            content_type="application/json")
    return HttpResponse(
        json.dumps({
            "result": "failed"}),
        content_type="application/json")
