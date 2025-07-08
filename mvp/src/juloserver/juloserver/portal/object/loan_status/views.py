from __future__ import print_function

from builtins import str
from builtins import range
import json
import csv
import datetime
import logging
import traceback

from babel.numbers import format_decimal
from dateutil.relativedelta import relativedelta
from datetime import timedelta
from dateutil.parser import parse

from django.contrib import messages
from django.db import transaction
from django.views.decorators.csrf import csrf_protect
from django.conf import settings
from django.http import JsonResponse

from django.utils import timezone
from django.http import HttpResponse
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.core.urlresolvers import reverse
from django.shortcuts import render
from django.views.generic import ListView
from django.views.decorators.http import require_http_methods

# set decorator for login required
from object import julo_login_required, julo_login_required_group, julo_login_required_multigroup

from juloserver.disbursement.services import get_disbursement

from juloserver.julo.constants import LoanVendorList

from juloserver.julo.partners import PartnerConstant

from juloserver.julo.models import PaymentNote
from juloserver.julo.models import CollectionAgentAssignment
from juloserver.julo.models import Loan, Payment
from juloserver.julo.models import ApplicationNote, FacebookData
from juloserver.julo.models import PaymentMethod
from juloserver.julo.models import CustomerWalletHistory
from juloserver.julo.services import change_cycle_day
from juloserver.julo.services import update_payment_installment
from juloserver.julo.models import RobocallTemplate
from juloserver.julo.models import Skiptrace
from juloserver.julo.models import SkiptraceHistory
from juloserver.julo.models import Agent
from juloserver.julo.models import PTP
from juloserver.julo.services import get_data_application_checklist_collection
from juloserver.julo.services import process_loan_status_change
from juloserver.julo.services import change_due_dates
from juloserver.julo.services2.agent import get_payment_type_vendor_agent
from juloserver.julo.formulas import get_available_due_dates_by_payday
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.exceptions import JuloException
from juloserver.julo.tasks import send_sms_update_ptp
from juloserver.julo.clients import get_julo_sentry_client

from .utils import (get_list_history,
                    get_wallet_list_note,
                    parse_loan_status, loan_filter_search_field)

from .forms import (LoanSearchForm,
                    NewPaymentInstallmentForm,
                    NoteForm,
                    LoanForm,
                    LoanCycleDayForm,
                    LoanReassignmentForm,
                    SquadReassignmentForm)

from app_status.forms import ApplicationForm
from app_status.forms import ApplicationSelectFieldForm
from .forms import StatusChangesForm as LoanStatusChangesForm
from django.contrib.auth.models import User
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.collectionbucket.models import CollectionAgentTask
from juloserver.collectionbucket.services.agent import AGENT_ASSIGNTMENT_DICT
from juloserver.minisquad.models import CollectionSquad, CollectionHistory
from juloserver.pii_vault.collection.services import mask_phone_number_sync
from juloserver.portal.object import user_has_collection_blacklisted_role

logger = logging.getLogger(__name__)


PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')
restricted_reassign_statuses = [LoanStatusCodes.INACTIVE,
                                LoanStatusCodes.CURRENT,
                                LoanStatusCodes.PAID_OFF,
                                str(LoanStatusCodes.INACTIVE),
                                str(LoanStatusCodes.CURRENT),
                                str(LoanStatusCodes.PAID_OFF)]
sentry_client = get_julo_sentry_client()

# ----------------------------- Loan data Start ---------------------------------------


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
                                 'document_verifier', 'bo_credit_analyst', 'cs_team_leader', 'bo_general_cs',
                                 'collection_supervisor'])
class LoanDataListView(ListView):
    model = Loan
    paginate_by = 50  # get_conf("PAGINATION_ROW")
    template_name = 'object/loan_status/list.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self, **kwargs):
        self.qs = super(LoanDataListView, self).get_queryset().select_related('loanzerointerest')

        # define a special data for Icare client
        self.router_keyword = 'all'
        if self.status_code and self.status_code == 'partner':
            self.router_keyword = 'partner'
            self.qs = self.qs.filter(application__partner__name__in=PartnerConstant.form_partner())
        else:
            self.qs = self.qs.exclude(application__partner__name__in=PartnerConstant.form_partner())

        if self.status_code:
            _loan_status = parse_loan_status(self.status_code)
            if _loan_status:
                if 'app_status' in self.kwargs:
                    self.app_status = self.kwargs['app_status']
                    self.qs = self.qs.filter(application__application_status=self.app_status,
                                             loan_status__status_code=_loan_status)
                else:
                    self.qs = self.qs.filter(loan_status__status_code=_loan_status)
            elif self.status_code == 'cdr':
                self.qs = self.qs.filter(cycle_day_requested__gte=1)
                self.status_code = "Change Cycle-Day Requested"
            else:
                self.status_code = "all"
        else:
            self.status_code = "all"

        self.qs = self.qs.order_by('-pk')

        self.err_message_here = None
        self.tgl_range = None
        self.tgl_start = None
        self.tgl_end = None
        self.status_loan = None
        self.search_q = None
        self.sort_q = None
        self.status_now = None

        if self.request.method == 'GET':
            self.tgl_range = self.request.GET.get('datetime_range', None)
            if (self.status_code == 'all'):
                self.status_loan = self.request.GET.get('status_app', None)
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.sort_q = self.request.GET.get('sort_q', None)
            self.status_now = self.request.GET.get('status_now', None)
            sort_partner = self.request.GET.get('list_partner', None)
            self.specific_column_search = self.request.GET.get('specific_column_search', None)
            if isinstance(self.search_q, str) and self.search_q:
                if self.specific_column_search:
                    field = self.specific_column_search
                    keyword = self.search_q.strip()
                    if not keyword.isnumeric() and field =='loan_xid':
                        return self.qs.none()

                else:
                    field, keyword = loan_filter_search_field(self.search_q)
                    if not field:
                        field = 'id'

                if field == 'customer__application__fullname':
                    self.qs = self.qs.filter(**{('%s__%s' % (field, 'icontains')): keyword})
                elif field == 'application__partner':
                    if hasattr(self.qs.query.where.children[0], 'negated'):
                        """
                        removing
                        exclude(application__partner__name__in=PartnerConstant.form_partner()
                        from queryset
                        """
                        del self.qs.query.where.children[0]
                    self.qs = self.qs.filter(
                        **{
                            field: keyword,
                            'application__partner__name__isnull': False
                        }
                    )
                else:
                    if field and keyword:
                        self.qs = self.qs.filter(**{field: keyword})

            if self.status_code == 'all':
                if self.status_loan:
                    self.qs = self.qs.filter(loan_status__status_code=self.status_loan)
                elif not self.search_q:
                    self.qs = self.qs.filter(loan_status__status_code=LoanStatusCodes.DRAFT)

            if sort_partner:
                self.qs = self.qs.filter(application__partner_id=sort_partner)

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
                        _tgl_mulai = datetime.datetime.strptime(_date_range[0].strip(), "%d/%m/%Y %H:%M")
                        _tgl_end = datetime.datetime.strptime(_date_range[1].strip(), "%d/%m/%Y %H:%M")
                        if _tgl_end > _tgl_mulai:
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.err_message_here = "Format Tanggal tidak valid"

            if self.sort_q:
                if self.sort_q == 'app_and_status_asc':
                    self.qs = self.qs.order_by('application__id',
                                               'application__application_status__status_code')
                elif self.sort_q == 'app_and_status_desc':
                    self.qs = self.qs.order_by('-application__id',
                                               '-application__application_status__status_code')
                else:
                    self.qs = self.qs.order_by(self.sort_q)

        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(LoanDataListView, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = LoanSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = LoanSearchForm()
        # to check field application.product_line.product_line_code
        product_line_STL = (ProductLineCodes.STL1, ProductLineCodes.STL2)
        context['vendor_list'] = LoanVendorList.VENDOR_LIST
        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['status_code_now'] = self.status_code
        context['status_show'] = self.status_show
        context['status_loan'] = self.status_loan
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        # print "parameters: ", parameters
        context['parameters'] = parameters
        context['product_line_STL'] = product_line_STL
        context['product_line_GRAB'] = ProductLineCodes.grab()
        context['product_line_julo_one'] = ProductLineCodes.julo_one()
        context['product_line_mlt'] = ProductLineCodes.mtl()
        context['loan_count'] = len(context['object_list'])

        # way to redirect to ICare page
        context['router_keyword'] = self.router_keyword

        context['restricted_reassign_statuses'] = restricted_reassign_statuses
        context['loan_reassignment'] = LoanReassignmentForm()
        context['squad_reassignment'] = SquadReassignmentForm()

        #check if the user role is supervisor or not for loan reassignemnt
        user = self.request.user
        user_groups = user.groups.all().values_list('name', flat=True)
        is_user_supervisor = JuloUserRoles.COLLECTION_SUPERVISOR in user_groups
        context['is_supervisor'] = is_user_supervisor
        list_users = {
            'agent': {
                JuloUserRoles.COLLECTION_BUCKET_2: list(User.objects.filter(groups__name=JuloUserRoles.COLLECTION_BUCKET_2)
                                                                    .exclude(username__in=('asiacollect2',
                                                                                           'mbacollection2',
                                                                                           'telmark2',
                                                                                           'collmatra2'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_3: list(User.objects.filter(groups__name=JuloUserRoles.COLLECTION_BUCKET_3)
                                                                    .exclude(username__in=('asiacollect3',
                                                                                           'mbacollection3',
                                                                                           'telmark3',
                                                                                           'collmatra3'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_4: list(User.objects.filter(groups__name=JuloUserRoles.COLLECTION_BUCKET_4)
                                                                    .exclude(username__in=('asiacollect4',
                                                                                           'mbacollection4',
                                                                                           'telmark4',
                                                                                           'collmatra4'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_5: list(User.objects.filter(groups__name=JuloUserRoles.COLLECTION_BUCKET_5)
                                                                    .exclude(username__in=('asiacollect5',
                                                                                           'mbacollection5',
                                                                                           'telmark5',
                                                                                           'collmatra5'))
                                                                    .values_list('username', flat=True)),
            },
            'vendor': {
                JuloUserRoles.COLLECTION_BUCKET_2: list(User.objects.filter(username__in=('asiacollect2',
                                                                                          'mbacollection2',
                                                                                          'telmark2',
                                                                                          'collmatra2'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_3: list(User.objects.filter(username__in=('asiacollect3',
                                                                                          'mbacollection3',
                                                                                          'telmark3',
                                                                                          'collmatra3'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_4: list(User.objects.filter(username__in=('asiacollect4',
                                                                                          'mbacollection4',
                                                                                          'telmark4',
                                                                                          'collmatra4'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_5: list(User.objects.filter(username__in=('asiacollect5',
                                                                                          'mbacollection5',
                                                                                          'telmark5',
                                                                                          'collmatra5'))
                                                                    .values_list('username', flat=True))
            }
        }

        # Get squad names
        collection_bucket_2_squad_names = list(CollectionSquad.objects\
                .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_2)\
                .values_list('squad_name', flat=True))
        collection_bucket_3_squad_names = list(CollectionSquad.objects\
                .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_3)\
                .values_list('squad_name', flat=True))
        collection_bucket_4_squad_names = list(CollectionSquad.objects\
                .filter(group__name=JuloUserRoles.COLLECTION_BUCKET_4)\
                .values_list('squad_name', flat=True))
        squad_names = []
        squad_names.extend(collection_bucket_2_squad_names)
        squad_names.extend(collection_bucket_3_squad_names)
        squad_names.extend(collection_bucket_4_squad_names)

        # Assign list squad
        list_squads = {
            JuloUserRoles.COLLECTION_BUCKET_2: collection_bucket_2_squad_names,
            JuloUserRoles.COLLECTION_BUCKET_3: collection_bucket_3_squad_names,
            JuloUserRoles.COLLECTION_BUCKET_4: collection_bucket_4_squad_names,
        }

        # Assign list agent
        list_agents = {}
        for squad_name in squad_names:
            list_agents[squad_name] = list(Agent.objects\
                .filter(squad__squad_name=squad_name)\
                .values_list('user__username', flat=True))

        context['list_users'] = json.dumps(list_users)
        context['list_agents'] = json.dumps(list_agents)
        context['list_squads'] = json.dumps(list_squads)
        context['is_show_sphp_number'] = user.groups.filter(
            name__in=(
                JuloUserRoles.COLLECTION_SUPERVISOR, JuloUserRoles.OPS_REPAYMENT,
                JuloUserRoles.OPS_TEAM_LEADER)
        ).exists()

        return context

    def get(self, request, *args, **kwargs):
        try:
            self.status_code = self.kwargs['status_code']
            if self.status_code in ['all', 'partner']:
                self.status_show = self.status_code
            else:
                self.status_show = 'with_status'
        except:
            self.status_code = None
            self.status_show = 'with_status'

        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super(LoanDataListView, self).render_to_response(context, **response_kwargs)
        return rend_here

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or user_has_collection_blacklisted_role(request.user):
            return render(request, 'covid_refinancing/404.html')

        return super().dispatch(request, *args, **kwargs)



def re_configure_req_post(request_post):
    if 'form2-loan_amount' in request_post:
        request_post['form2-loan_amount'] = str(request_post['form2-loan_amount']).replace(".", "")
    if 'form2-installment_amount' in request_post:
        request_post['form2-installment_amount'] = str(request_post['form2-installment_amount']).replace(".", "")
    if 'form2-cashback_earned_total' in request_post:
        request_post['form2-cashback_earned_total'] = str(request_post['form2-cashback_earned_total']).replace(".", "")
    if 'id_first_payment_installment' in request_post:
        request_post['id_first_payment_installment'] = str(request_post['id_first_payment_installment']).replace(".", "")
    if 'id_cycle_date_requested' in request_post:
        request_post['id_cycle_date_requested'] = str(request_post['id_cycle_date_requested']).replace(".", "")

    return request_post


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
                                 'document_verifier', 'bo_credit_analyst', 'cs_team_leader', 'bo_general_cs',
                                 'collection_supervisor'])
def details(request, pk):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    if not request.user.is_authenticated or user_has_collection_blacklisted_role(request.user):
        return render(request, 'covid_refinancing/404.html')

    loan_obj = get_object_or_404(Loan, id=pk)
    customer = loan_obj.customer
    application = loan_obj.get_application
    status_current = loan_obj.loan_status
    cycle_day_req_current = loan_obj.cycle_day_requested
    installment_form = NewPaymentInstallmentForm(request.POST)
    disbursement = get_disbursement(loan_obj.disbursement_id)
    try:
        current_agent_assigned = CollectionAgentAssignment.objects.filter(
            loan_id=loan_obj.id).last().agent.agent.user_extension
    except AttributeError:
        customer = loan_obj.customer
        application = loan_obj.get_application
        current_agent_assigned = None

    template_name = 'object/loan_status/details.html'

    robocall_templates = RobocallTemplate.objects.filter(is_active=True)
    robo_templates_map = {}
    for robocall_template in robocall_templates:
        robo_templates_map[str(robocall_template.id)] = robocall_template.text
    skiptrace_list = Skiptrace.objects.filter(customer=customer).order_by('id')
    skiptrace_history_list = SkiptraceHistory.objects.filter(application=application).order_by('-cdate')[:100]
    status_skiptrace = True
    ptp_robocall_mobile_qs = skiptrace_list.filter(
        contact_source__in=['mobile_phone_1', 'mobile_phone_2']).values(
        'contact_source', 'phone_number')
    ptp_robocall_mobile_list = list(ptp_robocall_mobile_qs)

    if request.method == "POST":
        form = LoanStatusChangesForm(status_current, loan_obj.id, request.POST)
        if form.is_valid():

            status_to = form.cleaned_data['status_to']
            reason = form.cleaned_data['reason']
            notes = form.cleaned_data['notes']

            logger.info({
                'status_to': status_to,
                'reason': reason,
                'notes': notes
            })

            try:
                with transaction.atomic():
                    process_loan_status_change(
                        loan_obj.id, int(status_to), reason, request.user)

                url = reverse('loan_status:details', kwargs={'pk': loan_obj.id})
                return redirect(url)

            except Exception as e:
                err_msg =   """
                            Ada Kesalahan di Backend Server!!!, Harap hubungi Administrator : %s
                            """
                sentry_client.captureException()
                traceback.print_exc()
                err_msg = err_msg % (e)
                logger.info({
                    'app_id': loan_obj.id,
                    'error': "Ada Kesalahan di Backend Server with \
                    process_application_status_change !!!."
                })
                # messages.error(request, err_msg)
                message_out_ubah_status = err_msg
                ubah_status_active = 1


    if len(ptp_robocall_mobile_list) == 0:
        ptp_robocall_mobile_list.append(
            {'contact_source': 'mobile_phone_1', 'phone_number': application.mobile_phone_1})
        ptp_robocall_mobile_list.append(
            {'contact_source': 'mobile_phone_2', 'phone_number': application.mobile_phone_2})
        form = NoteForm(request.POST)
        loan_obj.refresh_from_db()
        # re-configure request.POST for loan
        request_POST = re_configure_req_post(request.POST.copy())
        # print "loan_req_post: ", request_POST
        form_loan = LoanForm(request_POST,
                             instance=loan_obj,
                             prefix='form2')
        form_loan_cdr = LoanCycleDayForm(request_POST,
                                         instance=loan_obj,
                                         prefix='form3')

        if 'simpan_note' in request.POST:
            flag_notes = True
            if form.is_valid():
                notes = form.cleaned_data['notes']
                if notes:
                    user_id = request.user.id if request.user else None
                    app_note = ApplicationNote.objects.create(
                        note_text=notes,
                        application_id=loan_obj.application.id,
                        added_by_id=user_id,
                    )
                    logger.info(
                        {
                            'loan_status:details': notes,
                            'app_note': app_note,
                        }
                    )

                    url = reverse('loan_status:details', kwargs={'pk': loan_obj.id})
                    return redirect(url)
                else:
                    flag_notes = False
            else:
                flag_notes = False

            if not flag_notes:
                # there is an error
                err_msg = """
                    Catatan Tidak Boleh dikosongkan!!!
                """
                logger.info({
                    'loan_id': loan_obj.id,
                    'error': err_msg
                })
                messages.error(request, err_msg)

        if 'ubah_loan' in request.POST:
            if form_loan.is_valid():
                print("form_loan.is_valid")
                form_loan.save()

                url = reverse('loan_status:details', kwargs={'pk': loan_obj.id})
                return redirect(url)
            else:
                # there is an error
                err_msg = """
                    Masih terdapat kesalahan input, mohon diperbaiki dahulu!!!
                """

                for field in form_loan:
                    if field.errors:
                        # print dir(form_loan.fields[field.name]), field.name
                        if form_loan.fields[field.name].error_messages['required']:
                            err_field = form_loan.fields[field.name].error_messages['required']
                        elif form_loan.fields[field.name].error_messages['invalid']:
                            err_field = form_loan.fields[field.name].error_messages['invalid']
                        else:
                            "unknown error!"
                        err_msg += ": %s - err_msg: %s" % (
                            field.name, err_field)

                logger.info({
                    'loan_id': loan_obj.id,
                    'error': err_msg
                })
                messages.error(request, err_msg)

        if 'ubah_cycle_day' in request.POST:
            if form_loan_cdr.is_valid():
                loan = form_loan_cdr.save()
                try:
                    change_cycle_day(loan)
                    url = reverse('loan_status:details', kwargs={'pk': loan_obj.id})
                    return redirect(url)

                except Exception as je:
                    err_msg = """
                        Error from Backend Process:
                    """
                    loan_obj.refresh_from_db()
                    err_msg = "%s %s" % (err_msg, str(je))
                    logger.info({
                        'ubah_cycle_day': 'ubah_cycle_day',
                        'loan_id': loan_obj.id,
                        'error': err_msg
                    })
                    messages.error(request, err_msg)
            else:
                # there is an error
                err_msg = """
                    Masih terdapat kesalahan input, cycle day tidak boleh kosong dan tidak boleh lebih dari 28!!!
                """
                logger.info({
                    'loan_id': loan_obj.id,
                    'error': err_msg
                })
                messages.error(request, err_msg)

        if 'ubah_first_installment' in request.POST:
            cycle_date_requested = request_POST['id_cycle_date_requested']
            new_first_payment_installment = request_POST['id_first_payment_installment']
            payday_requested = request_POST['id_payday_requested']
            if payday_requested:
                app = loan_obj.application
                if int(payday_requested) != app.payday:
                    app.payday = payday_requested
                    app.save()
            if new_first_payment_installment:
                print(new_first_payment_installment)
            else:
                err_msg = """
                    Masih terdapat kesalahan input, payment installment tidak boleh kosong!!!
                """
                logger.info({
                    'loan_id': loan_obj.id,
                    'error': err_msg
                })
                messages.error(request, err_msg)
            if cycle_date_requested:
                try:
                    print("cycle_date_requested: ", cycle_date_requested)
                    cycle_datetime_req_obj = datetime.datetime.strptime(
                        cycle_date_requested.strip(), "%d-%m-%Y")
                    cycle_date_req_obj = cycle_datetime_req_obj.date()
                    print("cycle_date_req_obj: ", cycle_date_req_obj)

                    # proceed cycle day change
                    change_due_dates(loan_obj, cycle_date_req_obj)
                    print('succes change cycle_dates')

                    # save first payment installment
                    print("new_first_payment_installment: ", new_first_payment_installment)
                    update_payment_installment(loan_obj, cycle_date_req_obj)

                    url = reverse('loan_status:details', kwargs={'pk': loan_obj.id})
                    return redirect(url)

                except Exception as je:
                    err_msg = """
                        Error from Backend Process:
                    """
                    loan_obj.refresh_from_db()
                    err_msg = "%s %s" % (err_msg, str(je))
                    logger.info({
                        'ubah_cycle_day': 'ubah_cycle_day',
                        'loan_id': loan_obj.id,
                        'error': err_msg
                    })
                    messages.error(request, err_msg)
            else:
                # there is an error
                err_msg = """
                    Masih terdapat kesalahan input, cycle day tidak boleh kosong dan tidak boleh lebih dari 28!!!
                """
                logger.info({
                    'loan_id': loan_obj.id,
                    'error': err_msg
                })
                messages.error(request, err_msg)

    else:
        loan_obj.refresh_from_db()
        form = NoteForm()
        form_loan = LoanForm(instance=loan_obj, prefix='form2')
        form_loan_cdr = LoanCycleDayForm(instance=loan_obj,
                                         prefix='form3')

    history_note_list = get_list_history(loan_obj.get_application, loan_obj)
    payments_after_restructured = Payment.objects.filter(loan=loan_obj).normal()

    # #get fb data
    try:
        fb_obj = loan_obj.get_application.facebook_data
    except FacebookData.DoesNotExist:
        fb_obj = None
    # get loan data and order by offer_number
    offer_set_objects = loan_obj.get_application.offer_set.all().order_by("offer_number")

    cycle_day_button_active = False
    product_lines_STL = (ProductLineCodes.STL1, ProductLineCodes.STL2)
    loan_status_code = loan_obj.loan_status.status_code
    product_line_code = loan_obj.get_application.product_line.product_line_code

    first_installment_btn_active = False
    if product_line_code in product_lines_STL:
        if loan_status_code < LoanStatusCodes.CURRENT:
            first_installment_btn_active = True
    else:
        if loan_status_code < LoanStatusCodes.PAID_OFF:
            first_installment_btn_active = True

    app_data = get_data_application_checklist_collection(loan_obj.get_application)
    deprecated_list = [
        'address_kodepos',
        'address_kecamatan',
        'address_kabupaten',
        'bank_scrape',
        'address_kelurahan',
        'address_provinsi',
        'bidang_usaha'
    ]
    form_app = ApplicationForm(
        instance=loan_obj.get_application, prefix='form2')
    form_app_select = ApplicationSelectFieldForm(loan_obj.get_application, prefix='form2')
    payment_method = PaymentMethod.objects.displayed(loan_obj)
    customer = loan_obj.customer
    wallets = CustomerWalletHistory.objects.filter(customer=customer).order_by('-id')
    wallets = wallets.exclude(change_reason__contains='_old').order_by('-id')
    wallet_notes = get_wallet_list_note(customer)
    loan_can_restructure = False
    not_restructure_statuses = [LoanStatusCodes.INACTIVE,
                                LoanStatusCodes.RENEGOTIATED]

    if status_current.status_code not in not_restructure_statuses:
        allowed_products = ProductLineCodes.mtl() + ProductLineCodes.stl()
        if (loan_obj.get_application.product_line.product_line_code in allowed_products):
            loan_can_restructure = True
    loan_form = LoanStatusChangesForm(status_current, loan_obj.id)

    education_bank_account_validated_name = None
    education_bank_account_number = None
    education_bank_name_frontend = None
    if loan_obj.is_education_product:
        education_bank_account_validated_name = (
            loan_obj.bank_account_destination.name_bank_validation.validated_name
        )
        education_bank_account_number = loan_obj.bank_account_destination.account_number
        education_bank_name_frontend = loan_obj.bank_account_destination.bank.bank_name_frontend

    return render(
        request,
        template_name,
        {
            'form': form,
            'form_loan': form_loan,
            'form_loan_cdr': form_loan_cdr,
            'installment_form': installment_form,
            'loan_obj': loan_obj,
            "disbursement_method": disbursement['method'],
            'education_bank_account_validated_name': education_bank_account_validated_name,
            'education_bank_account_number': education_bank_account_number,
            'education_bank_name_frontend': education_bank_name_frontend,
            'payments': payments_after_restructured,
            'fb_obj': fb_obj,
            'status_current': status_current,
            'history_note_list': history_note_list,
            'datetime_now': timezone.now(),
            'first_installment_btn_active': first_installment_btn_active,
            'cycle_day_button_active': cycle_day_button_active,
            'offer_set_objects': offer_set_objects,
            'app_data': app_data,
            'deprecatform_apped_list': deprecated_list,
            'form_app': form_app,
            'form_app_select': form_app_select,
            'payment_method': payment_method,
            'wallets': wallets,
            'wallet_notes': wallet_notes,
            'restricted_reassign_statuses': restricted_reassign_statuses,
            'vendor_list': LoanVendorList.VENDOR_LIST,
            'current_agent_assigned': current_agent_assigned,
            'loan_can_restructure': loan_can_restructure,
            'robocall_templates': robocall_templates,
            'robo_templates_map': json.dumps(robo_templates_map),
            'ptp_robocall_mobile_list': ptp_robocall_mobile_list,
            "loan_form": loan_form,
            "ubah_status_active": 1,
            "simpan_note_active": 1
        }
    )


# ----------------------------- Loan Status END  -------------------------------


def set_unavailable_due_dates(payday, startday, product_line_code):
    disable_days = []
    available_due_dates = get_available_due_dates_by_payday(payday, startday, product_line_code)
    unavailable_due_dates = []

    for days in range(0, 60):
        date = startday + relativedelta(days=days)
        if date not in available_due_dates:
            unavailable_due_dates.append(date)

    for due_date in unavailable_due_dates:
        day = due_date.day
        month = due_date.month
        year = due_date.year
        unavailable_date = str(day) + "-" + str(month) + "-" + str(year)
        disable_days.append(unavailable_date)
    return disable_days

# -----------------------------   AJAX   START  --------------------------------


@csrf_protect
def simulate_adjusted_installment(request):
    """
    """
    if request.method == 'GET':
        current_user = request.user
        loan_obj = Loan.objects.get_or_none(pk=int(request.GET.get('loan_id', 0)))
        response_data = {}
        loan_id = request.GET.get('loan_id')
        if loan_obj and current_user:
            # set int date object
            try:
                new_due_date = request.GET.get('new_due_date', '')
                new_due_date_obj = datetime.datetime.strptime(str(new_due_date), "%d-%m-%Y").date()
            except Exception as e:
                logger.warning({
                    'status': 'ajax - simulate_adjusted_installment',
                    'new_due_date': new_due_date,
                    'loan': loan_obj
                })
                return HttpResponse(
                    json.dumps({
                        "reason": "exception on calculate days_extra",
                        "result": "nok"
                    }),
                    content_type="application/json"
                )

            # simulate recalculation for first payment installment
            new_first_payment_installment = None
            try:
                new_first_payment_installment = update_payment_installment(loan_obj, new_due_date_obj,
                                                                           simulate=True)
            except Exception as e:
                logger.warning({
                    'status': 'ajax - simulate_adjusted_payment_installment',
                    'exception': e,
                    'loan': loan_obj
                })
                return HttpResponse(
                    json.dumps({
                        "reason": "exception on simulate_adjusted_payment_installment",
                        "result": "nok",
                        "addd": e
                    }),
                    content_type="application/json"
                )

            response_data['result'] = 'successful!'
            response_data['output'] = "%s" % (format_decimal(new_first_payment_installment, locale='id_ID')) if new_first_payment_installment else 'none'
            response_data['reason'] = "ALL OKE"

        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'Loan id does not exist or sphp date is empty'

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


def ajax_update_ptp(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()
    loan_id = data['loan_id']
    loan = Loan.objects.get_or_none(pk=loan_id)
    try:
        ptp_date = parse(data['ptp_date']).date()
    except JuloException:
        return JsonResponse({
            'status': 'failed',
            'message': 'invalid format ptp date {}'.format(data['ptp_date'])
        })
    if not loan:
        return JsonResponse({
            "status": "failed",
            "message": "loan id %s is not found" % (loan_id)
        })

    payment = loan.payment_set.normal().not_paid_active().order_by('payment_number').first()
    ptp_amount = str(data['ptp_amount'])
    ptp_robocall_mobile_phone = str(data['ptp_robo_mobile_phone'])
    robocall_template_id = data['robocall_template_id']
    is_ptp_robocall_active = data['is_ptp_robocall_active']
    if payment is None:
        return JsonResponse({
            "status": "failed",
            "message": "no unpaid payment in loan id %s" % (loan_id)
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
            payment.ptp_amount = ptp_amount
            payment.ptp_robocall_phone_number = mask_phone_number_sync(ptp_robocall_mobile_phone)
            payment.is_ptp_robocall_active = False if is_ptp_robocall_active == "false" else True
            payment.ptp_robocall_template = robocall_template
            notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
            payment.save(update_fields=['ptp_date',
                                        'ptp_amount',
                                        'is_ptp_robocall_active',
                                        'ptp_robocall_template',
                                        'ptp_robocall_phone_number',
                                        'udate'])

            PTP.objects.create(payment=payment,
                               loan=loan,
                               agent_assigned=request.user,
                               ptp_date=ptp_date,
                               ptp_amount=ptp_amount)

            payment_note = PaymentNote.objects.create(
                note_text=notes,
                payment=payment)
            logger.info({
                'ptp_date': ptp_date,
                'payment_note': payment_note,
            })

        # block sms to partner
        if payment.loan.get_application.customer.can_notify:
            send_sms_update_ptp.delay(payment.id)

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
def ajax_unavailable_due_dates(request):
    if request.method == 'GET':
        loan_obj = Loan.objects.get_or_none(pk=int(request.GET.get('loan_id', 0)))
        payday_requested = request.GET.get('payday', 0)
        payday = int(payday_requested) if payday_requested else loan_obj.get_application.payday
        product_line_code = loan_obj.get_application.product_line.product_line_code
        last_paid_payment = Payment.objects.by_loan(loan_obj).paid().order_by('payment_number').last()
        first_payment = Payment.objects.by_loan(loan_obj).not_paid().order_by('payment_number').first()
        response_data = {}
        if first_payment is None:
            start = None
        else:
            if first_payment.payment_number == 1:
                start_day = loan_obj.offer.cdate.date() if getattr(loan_obj, 'offer', None) else \
                    loan_obj.cdate.date()
            elif first_payment.payment_number > 1:
                start_day = last_paid_payment.due_date
            start = str(start_day.day) + '-' + str(start_day.month) + '-' + str(start_day.year)

        try:
            unavailable_dates = set_unavailable_due_dates(payday, start_day, product_line_code)
        except Exception as e:
            logger.warning({
                'status': 'ajax - get available due_dates',
                'exception': e,
                'loan': loan_obj
            })
            return HttpResponse(
                json.dumps({
                    "reason": "exception on get available due_dates",
                    'result': "nok"
                }),
                content_type="application/json"
            )

        response_data['result'] = 'successful!'
        response_data['output'] = unavailable_dates if unavailable_dates else 'none'
        response_data['start'] = start
        response_data['end'] = unavailable_dates[len(unavailable_dates) - 1] if unavailable_dates else 'none'
        response_data['reason'] = "ALL OKE"
        if start:
            formatted_start = datetime.datetime.strptime(start, '%d-%m-%Y')
            response_data['formatted_start'] = datetime.datetime.strftime(formatted_start,
                                                                          '%Y-%m-%d')

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({"reason": "this isn't happening",
                        "result": "nok"}),
            content_type="application/json"
        )


def reassign_vendor_agent(agent_payments, assigned_by=None):
    today = timezone.now()
    with transaction.atomic():
        for data in agent_payments:
            payment = data['payment']
            loan = payment.loan
            agent = data['agent']
            type = data['type']
            old_agent_assignments = CollectionAgentAssignment.objects.filter(
                loan=loan, unassign_time__isnull=True,
                payment=payment, type=type)

            for old_agent_assignment in old_agent_assignments:
                old_agent_assignment.unassign_time = today
                old_agent_assignment.save()

            CollectionAgentAssignment.objects.create(
                loan=loan, payment=payment, agent=agent, type=type,
                assign_time=today)


@csrf_protect
def ajax_bulk_vendor_reassign(request):
    if request.method == 'GET':
        vendor = request.GET.get('vendor')
        loan_ids = json.loads(request.GET.get('loan_list'))
        loan_status = int(request.GET.get('loan_status_code'))
        if loan_status in restricted_reassign_statuses:
            return HttpResponse(
                json.dumps({
                    "messages": "Tidak dapat melakukan reassign pada loan yg belum/tidak telat!!",
                    'status': "failed"
                }),
                content_type="application/json"
            )

        loans = Loan.objects.filter(id__in=loan_ids, loan_status_id=loan_status)
        for loan in loans:
            payments = loan.payment_set.filter(
                payment_status__status_code__range=(
                    PaymentStatusCodes.PAYMENT_DUE_TODAY, PaymentStatusCodes.PAYMENT_180DPD)
            )
            agent_payments = get_payment_type_vendor_agent(payments, vendor)
            try:
                reassign_vendor_agent(agent_payments, request.user)
            except Exception:
                return HttpResponse(
                    json.dumps({
                        "messages": "Terjadi kesalahan di backend server",
                        'status': "failed"
                    }),
                    content_type="application/json"
                )
        return HttpResponse(
            json.dumps({
                "messages": "sukses reassign all loan to vendor",
                'status': "success"
            }),
            content_type="application/json"
        )


@require_http_methods(["GET"])
@csrf_protect
def ajax_vendor_reassign(request):
    vendor = request.GET.get('vendor')
    loan_id = request.GET.get('loan_id')
    loan_status_code = int(request.GET.get('loan_status_code'))

    if not vendor:
        return HttpResponse(
            json.dumps({
                "messages": "No Vendor Selected, 'Please select vendor to reassign!!!",
                "status": "failed",
            })
        )
    if loan_status_code in restricted_reassign_statuses:
        return HttpResponse(
            json.dumps({
                "messages": "Tidak dapat melakukan reassign pada loan yg belum/tidak telat!!",
                'status': "failed"
            }),
            content_type="application/json"
        )
    try:
        loan = Loan.objects.get(id=loan_id, loan_status_id=loan_status_code)
        payments = loan.payment_set.filter(
            payment_status__status_code__range=(
                PaymentStatusCodes.PAYMENT_DUE_TODAY, PaymentStatusCodes.PAYMENT_180DPD)
        )
        agent_payments = get_payment_type_vendor_agent(payments, vendor)
        reassign_vendor_agent(agent_payments, request.user)

    except Loan.DoesNotExist:
        return HttpResponse(
            json.dumps({
                "messages": "Selected Loan Does Not Exist please recheck",
                'status': "failed"
            }),
            content_type="application/json"
        )
    except Exception as e:
        return HttpResponse(
            json.dumps({
                "messages": "Terjadi kesalahan di backend server {}".format(e),
                'status': "failed"
            }),
            content_type="application/json"
        )
    return HttpResponse(
        json.dumps({
            "messages": "sukses reassign all loan to vendor",
            'status': "success"
        }),
        content_type="application/json"
    )


@require_http_methods(["GET"])
@csrf_protect
def ajax_mark_loan_restructure(request):
    loan_id = request.GET.get('loan_id')
    loan = Loan.objects.get(id=int(loan_id))
    not_restructure_statuses = [LoanStatusCodes.INACTIVE,
                                LoanStatusCodes.RENEGOTIATED]

    if loan.status in not_restructure_statuses:
        return HttpResponse(
            json.dumps({
                "messages": "Loan is not in the right status %s" % loan.status,
                'status': "failed"
            }),
            content_type="application/json"
        )

    with transaction.atomic():
        loan.loan_status_id = LoanStatusCodes.RENEGOTIATED
        loan.save()
        # unassign all loan agent assignments
        CollectionAgentAssignment.objects.filter(
            loan=loan, unassign_time__isnull=True).update(
            unassign_time=timezone.now())

    return HttpResponse(
        json.dumps({
            "messages": "sukses mark loan restructure",
            'status': "success"
        }),
        content_type="application/json"
    )
# -----------------------------   AJAX   END  ----------------------------------

@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_SUPERVISOR)
def bulk_loan_reassignment(request):
    template = 'object/loan_status/bulk_loan_reassignment.html'

    return render(
        request,
        template
    )


@csrf_protect
def ajax_loan_reassignment(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    error_loans = []

    if request.FILES and request.FILES['file'] is not None:
        if 'csv' in request.FILES['file'].name:
            paramFile = request.FILES['file']

            csv_reader = csv.DictReader(paramFile.read().decode().splitlines())
            loans = []
            count = 0

            for count, row in enumerate(csv_reader):
                loans.append(row['loan_id'])

            if count == 0:
                return JsonResponse({
                    "status": "warning",
                    "error_loans": error_loans,
                    "error_loans_count": 0
                })

        else:
            return JsonResponse({
                "status": "error",
                "messages": "File is not in csv format"
            })
    else:
        loans = json.loads(data['loans'])

    today = timezone.localtime(timezone.now()).date()
    payment_ids = []
    t_plus_1 = today - timedelta(days=1)
    t_plus_100 = today - timedelta(days=100)

    for loan_id in loans:
        loan = Loan.objects.get_or_none(pk=loan_id)

        if loan is None:
            error_loans.append(loan_id)
            continue

        payment = loan.get_oldest_unpaid_payment()

        if payment is None:
            continue

        if t_plus_100 < payment.due_date < t_plus_1:
            payment_ids.append(payment.id)
            continue

        assignment = CollectionAgentTask.objects.filter(loan=loan,
                                                        payment=payment)
        if not assignment:
            error_loans.append(loan_id)
            continue

        CollectionAgentTask.objects.filter(loan=loan,
                                           unassign_time__isnull=True)\
                                   .update(unassign_time=today)

        collection_agent_type = AGENT_ASSIGNTMENT_DICT[data['role']]
        agent = User.objects.get(username=data['agent'])

        CollectionAgentTask.objects.create(loan=loan,
                                           payment=payment,
                                           assign_time=today,
                                           type=collection_agent_type,
                                           allocate_by=request.user,
                                           agent=agent,
                                           assign_to_vendor=True)
    if len(error_loans) > 0:
        return JsonResponse({
            "status": "warning",
            "error_loans": error_loans,
            "error_loans_count": len(error_loans)
        })

    if len(payment_ids) > 0:
        return JsonResponse({
            "status": "error",
            "messages": "Payment in loan not in T+101",
            "payment_ids": payment_ids
        })

    return JsonResponse({
        "status": "success",
        "messages": "Success loan reassignemnts"
    })


@csrf_protect
def ajax_squad_reassignment(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    loans = json.loads(data['loans'])
    error_payment_ids = []
    selected_agent = User.objects.filter(username=data['agent']).last()

    for loan in loans:
        loan = Loan.objects.get_or_none(pk=loan)

        if loan is None:
            continue

        payment = loan.get_oldest_unpaid_payment()
        collection_history_list = CollectionHistory.objects.filter(payment_id=payment.id, last_current_status=True)
        collection_history = collection_history_list.last()

        if collection_history is None:
            continue

        # Check same squad and call result ptp
        if (collection_history.squad.squad_name != data['squad'] or
            collection_history.call_result.name != 'RPC - PTP'):
            error_payment_ids.append(payment.id)
            continue

        # Set current data to false
        for history in collection_history_list:
            history.update_safely(last_current_status=False)

        # Insert new row data for reassign ptp agent
        CollectionHistory.objects.create(
            customer=collection_history.customer,
            loan=collection_history.loan,
            payment=collection_history.payment,
            squad=collection_history.squad,
            agent=selected_agent,
            call_result=collection_history.call_result,
            last_current_status=True,
            excluded_from_bucket=collection_history.excluded_from_bucket
        )

    if len(error_payment_ids) > 0:
        return JsonResponse({
            "status": "error",
            "messages": "Agent not in the same squad or payment call result not PTP",
            "payment_ids": error_payment_ids
        })

    return JsonResponse({
        "status": "success",
        "messages": "Success squad reassignment"
    })


@csrf_protect
def ajax_bulk_loan_reassignment_get_data(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    data = {}
    data['bucket_types'] = [
        {
            'value': JuloUserRoles.COLLECTION_BUCKET_2,
            'name': 'Bucket 2'
        },
        {
            'value': JuloUserRoles.COLLECTION_BUCKET_3,
            'name': 'Bucket 3'
        },
        {
            'value': JuloUserRoles.COLLECTION_BUCKET_4,
            'name': 'Bucket 4'
        },
        {
            'value': JuloUserRoles.COLLECTION_BUCKET_5,
            'name': 'Bucket 5'
        }]

    data['list_agents'] = {
            'agent': {
                JuloUserRoles.COLLECTION_BUCKET_2: list(User.objects.filter(groups__name=JuloUserRoles.COLLECTION_BUCKET_2)
                                                                    .exclude(username__in=('asiacollect2',
                                                                                           'mbacollection2',
                                                                                           'telmark2',
                                                                                           'collmatra2'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_3: list(User.objects.filter(groups__name=JuloUserRoles.COLLECTION_BUCKET_3)
                                                                    .exclude(username__in=('asiacollect3',
                                                                                           'mbacollection3',
                                                                                           'telmark3',
                                                                                           'collmatra3'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_4: list(User.objects.filter(groups__name=JuloUserRoles.COLLECTION_BUCKET_4)
                                                                    .exclude(username__in=('asiacollect4',
                                                                                           'mbacollection4',
                                                                                           'telmark4',
                                                                                           'collmatra4'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_5: list(User.objects.filter(groups__name=JuloUserRoles.COLLECTION_BUCKET_5)
                                                                    .exclude(username__in=('asiacollect5',
                                                                                           'mbacollection5',
                                                                                           'telmark5',
                                                                                           'collmatra5'))
                                                                    .values_list('username', flat=True)),
            },
            'vendor': {
                JuloUserRoles.COLLECTION_BUCKET_2: list(User.objects.filter(username__in=('asiacollect2',
                                                                                          'mbacollection2',
                                                                                          'selaras2',
                                                                                          'collmatra2'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_3: list(User.objects.filter(username__in=('asiacollect3',
                                                                                          'mbacollection3',
                                                                                          'selaras3',
                                                                                          'collmatra3'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_4: list(User.objects.filter(username__in=('asiacollect4',
                                                                                          'mbacollection4',
                                                                                          'selaras4',
                                                                                          'collmatra4'))
                                                                    .values_list('username', flat=True)),
                JuloUserRoles.COLLECTION_BUCKET_5: list(User.objects.filter(username__in=('asiacollect5',
                                                                                          'mbacollection5',
                                                                                          'selaras5',
                                                                                          'collmatra5'))
                                                                    .values_list('username', flat=True))
            }
    }

    return JsonResponse({
        'status' : 'success',
        'messages': 'Success get agent data',
        'data': data
    })
