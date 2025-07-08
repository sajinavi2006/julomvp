from __future__ import print_function

import csv
import datetime
import json
import logging
import operator
import re
import traceback
from builtins import map, str
from functools import reduce
from itertools import chain
from math import ceil
from babel.dates import format_datetime
from babel.numbers import parse_number
from dashboard.constants import BucketCode
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.paginator import Paginator
from django.core.urlresolvers import reverse
from django.db import transaction
from django.db.models import CharField, F, Max, Q, Value
from django.db.models.aggregates import Count
from django.db.models.expressions import Case, When
from django.db.models.sql.where import ExtraWhere
from django.forms.models import fields_for_model
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
    JsonResponse,
    QueryDict,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.generic import DetailView, ListView, View
from loan_app.forms import ValidationCheckForm
from loan_app.services import create_data_verification_checks
from loan_app.utils import (
    get_app_detail_list_history,
    get_list_history,
    get_list_history_all,
)
from juloserver.application_flow.services2.bank_statement import get_lbs_submission
from object import (
    julo_login_required,
    julo_login_required_exclude,
    julo_login_required_multigroup,
)
from offers.forms import OfferForm
from payment_status.forms import SendEmailForm
from payment_status.utils import get_wallet_list_note
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from scraped_data.forms import ApplicationSearchForm, OESearchForm

import juloserver.pin.services as pin_services
from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account, AccountStatusHistory, ExperimentGroup
from juloserver.account.services.account_related import process_change_account_status
from juloserver.account_payment.models import AccountPayment
from juloserver.ana_api.services import check_positive_processed_income
from juloserver.ana_api.models import PdApplicationFraudModelResult

# from account.models import UserActivation
from juloserver.apiv1.services import get_voice_record_script
from juloserver.apiv2.models import EtlJob
from juloserver.apiv2.services import (
    get_eta_time_for_c_score_delay,
    is_c_score_in_delay_period,
)

# import disbursement service
# import disbursement service
from juloserver.application_flow.constants import JuloOneChangeReason
from juloserver.application_flow.models import (
    ApplicationPathTag,
    ApplicationPathTagStatus,
    ApplicationRiskyCheck,
)
from juloserver.application_flow.services import (
    check_hsfbp_bypass,
    check_sonic_bypass,
    fraud_message_mismatch_scraping,
    is_experiment_application,
    list_experiment_application,
    still_in_experiment,
    eligible_to_offline_activation_flow,
)
from juloserver.autodebet.constants import AutodebetVendorConst, ExperimentConst
from juloserver.autodebet.models import AutodebetAccount
from juloserver.autodebet.services.authorization_services import (
    process_account_registration,
    process_reset_autodebet_account,
    validate_existing_autodebet_account,
)
from juloserver.autodebet.services.task_services import determine_best_deduction_day
from juloserver.bpjs.constants import TongdunCodes
from juloserver.bpjs.models import BpjsTask, SdBpjsCompany, SdBpjsProfile
from juloserver.cashback.constants import CashbackChangeReason, OverpaidConsts
from juloserver.cashback.models import CashbackOverpaidVerification
from juloserver.cashback.services import (
    get_pending_overpaid_apps,
    overpaid_status_sorting_func,
)
from juloserver.customer_module.constants import BankAccountCategoryConst, ongoing_account_deletion_request_statuses
from juloserver.customer_module.models import (
    AccountDeletionRequest,
    BankAccountCategory,
    BankAccountDestination,
)
from juloserver.customer_module.services.customer_related import (
    CustomerService,
    change_customer_primary_phone_number,
    get_ongoing_account_deletion_request,
    get_ongoing_account_deletion_requests,
)
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.exceptions import DisbursementServiceError
from juloserver.disbursement.models import BankNameValidationLog, NameBankValidation
from juloserver.disbursement.services import (
    get_disbursement,
    get_disbursement_process_by_id,
    get_julo_balance,
    get_julo_balance_from_cache,
    get_list_disbursement_method,
    get_list_validation_method,
    get_multi_step_disbursement,
    get_name_bank_validation,
    get_name_bank_validation_process_by_id,
    get_xfers_balance_from_cache,
    trigger_name_in_bank_validation,
)
from juloserver.disbursement.services.gopay import GopayConst
from juloserver.grab.segmented_tasks.disbursement_tasks import (
    trigger_create_or_update_ayoconnect_beneficiary,
)
from juloserver.entry_limit.services import is_entry_level_type
from juloserver.followthemoney.models import LenderBucket
from juloserver.fraud_score.services import process_account_reactivation
from juloserver.geohash.models import AddressGeolocationGeohash
from juloserver.grab.clients.clients import GrabClient
from juloserver.grab.exceptions import GrabApiException, GrabLogicException
from juloserver.grab.services.services import (
    GrabCommonService,
    GrabLoanService,
    update_loan_status_for_grab_invalid_bank_account,
)
from juloserver.julo.banks import BankManager
from juloserver.julo.clients import (
    get_julo_pn_client,
    get_julo_sentry_client,
    get_julo_sim_client,
    get_julo_xendit_client,
)
from juloserver.julo.constants import (
    APP_STATUS_SKIP_PRIORITY,
    CashbackTransferConst,
    FeatureNameConst,
    WorkflowConst,
    ApplicationStatusChange,
    ApplicationStatusCodes,
    OnboardingIdConst,
)
from juloserver.julo.exceptions import (
    EmailNotSent,
    InvalidBankAccount,
    JuloException,
    SimApiError,
)
from juloserver.julo.formulas.underwriting import compute_affordable_payment
from juloserver.julo.models import (
    AddressGeolocation,
    AffordabilityHistory,
    Agent,
    Application,
    ApplicationDataCheck,
    ApplicationFieldChange,
    ApplicationHistory,
    ApplicationNote,
    Bank,
    BankStatementSubmit,
    CashbackTransferTransaction,
    Customer,
    CustomerFieldChange,
    CustomerWalletHistory,
    CustomerWalletNote,
    Device,
    Disbursement,
    ExperimentSetting,
    FacebookData,
    FeatureSetting,
    FraudCrmForm,
    FraudNote,
    Image,
    Loan,
    LoanDisburseInvoices,
    MassMoveApplicationsHistory,
    Offer,
    PartnerBankAccount,
    PartnerReferral,
    SecurityNote,
    Skiptrace,
    SkiptraceHistory,
    VoiceRecord,
    OnboardingEligibilityChecking,
    Image,
    OtpRequest,
)
from juloserver.julo.partners import DokuAccountType, PartnerConstant, get_doku_client
from juloserver.julo.product_lines import ProductLineCodes, ProductLineManager
from juloserver.julo.services import (
    get_data_application_checklist_collection,
    get_monthly_income_by_experiment_group,
    get_offer_recommendations,
    is_bank_name_validated,
    process_application_status_change,
    send_email_application,
    send_email_courtesy,
    send_email_fraud_mitigation,
    send_magic_link_sms,
    suspect_account_number_is_va,
    update_application_checklist_collection,
    update_offer,
)

# julo/services2
from juloserver.julo.services2 import get_cashback_redemption_service
from juloserver.julo.services2.cashback import CashbackRedemptionService
from juloserver.julo.services2.high_score import check_high_score_full_bypass
from juloserver.julo.services2.primo import delete_from_primo_courtesy_calls
from juloserver.julo.services2.telephony import call_customer, hangup_customer_call
from juloserver.julo.services2.voice import make_nexmo_test_call
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
    LoanStatusCodes,
)
from juloserver.julo.tasks import process_applications_mass_move
from juloserver.julo.utils import (
    check_email,
    filter_search_field,
    generate_transaction_id,
)
from juloserver.julo.workflows import WorkflowAction

# set decorator for login required
# set decorator for login required
from juloserver.julovers.workflows import JuloverWorkflowAction
from juloserver.loan.services.loan_related import (
    get_credit_matrix_and_credit_matrix_product_line,
)
from juloserver.magic_link.services import (
    check_if_magic_link_verified,
    generate_magic_link,
)
from juloserver.minisquad.tasks2 import (
    delete_account_from_intelix_if_exists_async_for_j1,
)
from juloserver.otp.constants import EmailOTP
from juloserver.paylater.models import DisbursementSummary
from juloserver.paylater.services import process_bulk_disbursement
from juloserver.personal_data_verification.constants import (
    DIRECT_DUKCAPIL_TAB_CRM_STATUSES,
    DUKCAPIL_TAB_CRM_STATUSES,
)
from juloserver.personal_data_verification.models import DukcapilResponse
from juloserver.personal_data_verification.services import (
    DukcapilVerificationSetting,
    get_existing_dukcapil_response,
    get_dukcapil_verification_setting_leadgen,
)
from juloserver.pin.constants import ResetEmailStatus
from juloserver.pin.models import CustomerPinChange
from juloserver.portal.object import julo_login_required_group, user_has_collection_blacklisted_role
from juloserver.application_flow.services import registration_method_is_video_call
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.julo_starter.constants import JuloStarter190RejectReason
from juloserver.sdk.constants import LIST_PARTNER, PARTNER_LAKU6
from juloserver.utilities.paginator import TimeLimitedPaginator

from .constants import AccountStatusMove, AgentUpdateAppSettings, FraudStatusMove
from .forms import (
    ApplicationForm,
    ApplicationSelectFieldForm,
    SecurityForm,
    StatusChangesForm,
    HsfbpIncomeVerificationForm,
)
from .functions import (
    AUTODIAL_SIM_STATUSES,
    CHANGE_REASONS_FIELD,
    DISBURSEMENT_STATUSES,
    FIN_MAX_COUNT_LOCK_APP,
    LOCK_STATUS_LIST,
    MAX_COUNT_LOCK_APP,
    NAME_BANK_VALIDATION_STATUSES,
    app_lock_list,
    check_lock_app,
    decode_unquote_plus,
    get_app_lock_count,
    get_cashback_request,
    get_lock_status,
    get_user_lock_count,
    lock_by_user,
    role_allowed,
    unlocked_app,
)
from .models import ApplicationLocked, ApplicationLockedMaster, CannedResponse
from .services import (
    dump_application_values_to_excel,
    get_js_validation_fields,
    is_customer_soft_deleted,
)
from .utils import (
    ExtJsonSerializer,
    canned_filter,
    courtesy_call_range,
    get_list_email_history,
)

from juloserver.grab.services.services import update_loan_status_for_grab_invalid_bank_account
from juloserver.geohash.models import AddressGeolocationGeohash
from django.core.paginator import Paginator
from juloserver.customer_module.tasks.notification import (
    send_customer_data_change_by_agent_notification_task,
)
from juloserver.customer_module.constants import (
    AgentDataChange,
)
from juloserver.apiv1.dropdown.loan_purposes import LoanPurposeDropDown
from juloserver.apiv1.dropdown.jobs import JobDropDownV2
from juloserver.apiv1.dropdown.addresses import AddressDropDown
from juloserver.apiv1.dropdown.companies import CompanyDropDown
from juloserver.otp.constants import SessionTokenAction
from juloserver.partnership.tasks import partnership_trigger_process_validate_bank
from juloserver.partnership.models import (
    PartnershipFlowFlag,
)
from juloserver.partnership.constants import PartnershipFlag
from juloserver.julo.workflows2.tasks import process_validate_bank_task

logger = logging.getLogger('juloserver.' + __name__)

PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')


# ----------------------------- Seluruh data Start ---------------------------------------
@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class ApplicationDataListView(ListView):
    model = Application
    paginate_by = 50  # get_conf("PAGINATION_ROW")
    paginator_class = TimeLimitedPaginator
    template_name = 'object/app_status/list.html'
    blacklisted_roles = ['collection_agent_1']


    def http_method_not_allowed(self, request, *args, **kwargs):
        # print "http_method_not_allowed"
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        # print "get_template_names"
        return ListView.get_template_names(self)

    def get_base_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(
                os_name=Case(
                    When(workflow__name='JuloOneIOSWorkflow', then=Value('A_iOS')),
                    When(
                        workflow__name__in=['JuloOneWorkflow', 'JuloStarterWorkflow'],
                        then=Value('A_Android'),
                    ),
                    default=Value('Z_-'),
                    output_field=CharField(),
                )
            )
        )

    def get_queryset(self):
        # print "get_queryset"
        self.qs = self.get_base_queryset()

        self.qs = self.qs.order_by('-id')

        self.err_message_here = None
        self.tgl_range = None
        self.tgl_start = None
        self.tgl_end = None
        self.status_app = None
        self.search_q = None
        self.sort_q = None
        self.status_now = None

        # print "self.request.GET: ", self.request.GET
        if self.request.method == 'GET':
            self.tgl_range = self.request.GET.get('datetime_range', None)
            self.status_app = self.request.GET.get('status_app', None)
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.sort_q = self.request.GET.get('sort_q', None)
            self.status_now = self.request.GET.get('status_now', None)

            self.qs = self.qs.annotate(
                crm_url=Value('%s/applications/' % settings.CRM_BASE_URL,
                              output_field=CharField()))

            if isinstance(self.search_q, str) and self.search_q:
                # checking full text search or not
                is_matched = re.search("^%(.*)%$", self.search_q)
                search_type = 'iexact'
                if is_matched:
                    self.search_q = is_matched.group(1)
                    search_type = 'icontains'

                field, keyword = filter_search_field(self.search_q)
                search_type = 'in' if field in ['product_line_id', 'account_id'] else search_type

                self.qs = self.qs.filter(
                    Q(**{('%s__%s' % (field, search_type)): keyword})
                )

            if (self.status_app):
                if int(self.status_app) <= ApplicationStatusCodes.LOC_APPROVED:
                    self.qs = self.qs.filter(application_status_id=self.status_app)
                elif int(self.status_app) in JuloOneCodes.fraud_check():
                    self.qs = self.qs.filter(account__status_id=self.status_app)
                elif int(self.status_app) in (433,):
                    self.qs = self.qs.filter(account__status_id=self.status_app)

            if (self.status_now):
                # print "OKAY STATUS NOW : ", self.status_now
                if (self.status_now == 'True'):
                    # print "HARI INI"
                    startdate = datetime.datetime.today()
                    startdate = startdate.replace(hour=0, minute=0, second=0)
                    enddate = startdate + datetime.timedelta(days=1)
                    enddate = enddate - datetime.timedelta(seconds=1)
                    self.qs = self.qs.filter(cdate__range=[startdate, enddate])
                else:
                    _date_range = self.tgl_range.split('-')
                    if (_date_range[0].strip() != 'Invalid date'):
                        _tgl_mulai = datetime.datetime.strptime(
                            _date_range[0].strip(), "%d/%m/%Y %H:%M")
                        _tgl_end = datetime.datetime.strptime(
                            _date_range[1].strip(), "%d/%m/%Y %H:%M")
                        # print "BEBAS"
                        if (_tgl_end > _tgl_mulai):
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.err_message_here = "Format Tanggal tidak valid"

            if self.sort_q:
                if self.sort_q == 'os_name':
                    self.qs = self.qs.order_by('os_name', '-id')
                elif self.sort_q == '-os_name':
                    self.qs = self.qs.order_by('-os_name', '-id')
                else:
                    self.qs = self.qs.order_by(self.sort_q)

        else:
            print("else request GET")

        return self.qs.select_related('product_line', 'partner', 'account', 'customer', 'workflow')

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(ApplicationDataListView, self).get_context_data(**kwargs)

        if self.request.method == 'GET':
            context['form_search'] = ApplicationSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = ApplicationSearchForm()

        # to check field application.product_line.product_line_code
        product_line_STL = (ProductLineCodes.STL1, ProductLineCodes.STL2)

        customer_ids = list(context.get('object_list').values_list('customer_id', flat=True))
        customer_ids_on_deletion = get_ongoing_account_deletion_requests(customer_ids)
        if customer_ids_on_deletion:
            customer_ids_on_deletion = customer_ids_on_deletion.values_list('customer_id', flat=True)

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['STATUS'] = "Seluruh Data"
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        # print "parameters: ", parameters
        context['parameters'] = parameters
        context['app_lock_status'] = LOCK_STATUS_LIST
        context['app_id_locked'] = app_lock_list()
        context['product_line_STL'] = product_line_STL
        context['customer_ids_on_deletion'] = customer_ids_on_deletion

        return context

    def get(self, request, *args, **kwargs):
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super(ApplicationDataListView, self).render_to_response(
            context, **response_kwargs)
        return rend_here

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or user_has_collection_blacklisted_role(request.user):
            return render(request, 'covid_refinancing/404.html')

        return super().dispatch(request, *args, **kwargs)


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class OnboardinEligibilityDataWSCListView(ListView):
    model = OnboardingEligibilityChecking
    paginate_by = 50  # get_conf("PAGINATION_ROW")
    paginator_class = TimeLimitedPaginator
    template_name = 'object/app_status/list_0_turbo.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        # print "http_method_not_allowed"
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        # print "get_template_names"
        return ListView.get_template_names(self)

    def get_queryset(self):
        from django.db import connection
        raw_0_turbo = """
            SELECT DISTINCT ON (oe.customer_id)
                oe.onboarding_eligibility_checking_id
            FROM
                onboarding_eligibility_checking AS oe
            ORDER BY
                customer_id, udate DESC
        """
        with connection.cursor() as cursor:
            cursor.execute(raw_0_turbo)
            result_0_turbo = cursor.fetchall()

        latest_0_turbo_ids = []
        for result in result_0_turbo:
            latest_0_turbo_ids.append(result[0])

        self.qs = super(OnboardinEligibilityDataWSCListView, self).get_queryset(
        ).select_related('customer'
                         ).filter(Q(bpjs_check=2) | Q(fdc_check=2)
                                  ).filter(id__in=latest_0_turbo_ids, dukcapil_check=None, application=None)
        self.qs = self.qs.order_by('-cdate', '-udate', 'id')

        self.err_message_here = None
        self.search_q = None
        self.sort_q = None

        # print "self.request.GET: ", self.request.GET
        if self.request.method == 'GET':
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.sort_q = self.request.GET.get('sort_q', None)
            self.qs = self.qs.annotate(
                crm_url=Value('%s/applications/' % settings.CRM_BASE_URL,
                              output_field=CharField()))

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_, [
                    Q(**{('%s__icontains' % 'customer__nik'): self.search_q}),
                    Q(**{('%s__icontains' % 'customer__email'): self.search_q})
                ]))

            if (self.sort_q):
                if (self.sort_q == 'customer-id'):
                    self.qs = self.qs.annotate(Max('customer__id')).order_by(
                        'customer__id__max')
                elif (self.sort_q == '-customer-id'):
                    self.qs = self.qs.annotate(Max('customer__id')).order_by(
                        '-customer__id__max')
                elif (self.sort_q == 'email'):
                    self.qs = self.qs.annotate(Max('customer__email')).order_by(
                        'customer__email__max')
                elif (self.sort_q == '-email'):
                    self.qs = self.qs.annotate(Max('customer__email')).order_by(
                        '-customer__email__max')
                else:
                    self.qs = self.qs.order_by(self.sort_q)

        else:
            print("else request GET")

        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(OnboardinEligibilityDataWSCListView, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = OESearchForm(self.request.GET.copy())
        else:
            context['form_search'] = OESearchForm()

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        # print "parameters: ", parameters
        context['parameters'] = parameters

        return context

    def get(self, request, *args, **kwargs):
        self.courtesy_call = False
        try:
            self.status_code = self.kwargs['status_code']
        except:
            self.status_code = None
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super(OnboardinEligibilityDataWSCListView, self).render_to_response(context,
                                                                                        **response_kwargs)
        return rend_here


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class ApplicationDataWSCListView(ListView):
    model = Application
    paginate_by = 50  # get_conf("PAGINATION_ROW")
    paginator_class = TimeLimitedPaginator
    template_name = 'object/app_status/list_w_status.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        # print "http_method_not_allowed"
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        # print "get_template_names"
        return ListView.get_template_names(self)

    def get_base_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(
                os_name=Case(
                    When(workflow__name='JuloOneIOSWorkflow', then=Value('A_iOS')),
                    When(
                        workflow__name__in=['JuloOneWorkflow', 'JuloStarterWorkflow'],
                        then=Value('A_Android'),
                    ),
                    default=Value('Z_-'),
                    output_field=CharField(),
                )
            )
        )

    def get_queryset(self):
        self.is_julo_one = False
        self.is_grab = False
        self.is_jstarter = False
        self.is_revive_mtl = False
        self.is_j1_assisted_agent = False

        partner_list = LIST_PARTNER

        app_status_skip_priority = APP_STATUS_SKIP_PRIORITY
        app_status_julo_one = [
            ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
            ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
            ApplicationStatusCodes.NAME_VALIDATE_FAILED,
            ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL,
            ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS
        ]

        app_status_grab = [
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            ApplicationStatusCodes.APPLICATION_RESUBMITTED
        ]

        app_status_jstarter = [
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        ]

        # 121, 122, 124, 130, 133, 135, 137, 150, 160, 163, 165, 170, 172, 180, 181
        # need to be normal bucket - JIRA-ON-1197
        self.bucket_code = self.status_code
        if '.' in self.status_code:
            self.status_code = self.status_code.split('.')[0]
            self.is_julo_one = True

        if '_grab' in self.status_code:
            self.status_code = self.status_code.split('_')[0]
            self.is_grab = True

        if '_jstarter' in self.status_code:
            self.status_code = self.status_code.split('_')[0]
            self.is_jstarter = True

        if '_mtl' in self.status_code:
            self.status_code = self.status_code.split('_')[0]
            self.is_revive_mtl = True

        if '_j1_assisted_agent' in self.status_code:
            self.status_code = self.status_code.split('_')[0]
            self.is_j1_assisted_agent = True

            # override template to dedicated template
            self.template_name = 'object/app_status/list_w_status_agent_assisted.html'

        if int(self.status_code) in app_status_skip_priority:
            partner_list = [x for x in partner_list if x != PartnerConstant.PEDE_PARTNER]
        # print "status_code: ", self.status_code
        self.qs = self.get_base_queryset().select_related(
            'product_line', 'application_status', 'customer', 'device', 'workflow'
        )

        is_revive_mtl_tag = ApplicationPathTagStatus.objects.get(
            application_tag='is_revive_mtl',
            status=1
        )
        mtl_application_ids = ApplicationPathTag.objects.filter(
            application_path_tag_status=is_revive_mtl_tag
        ).values_list('application_id', flat=True)

        if self.status_code:
            if self.status_code in BucketCode.cashback_crm_buckets():
                cb_app_ids, status_text = get_cashback_request(self.status_code)
                self.qs = self.qs.filter(pk__in=cb_app_ids)
                self.status_code = status_text

            elif self.status_code == BucketCode.VERIFYING_OVERPAID:
                overpaid_app_ids = get_pending_overpaid_apps()
                self.status_code = "Verifying Overpaid"
                self.qs = self.qs.filter(pk__in=overpaid_app_ids)

            elif self.status_code == '199':
                self.status_code = 180
                self.courtesy_call = True
                start_date, end_date = courtesy_call_range()
                today = timezone.now().date()
                dpd_min_5 = today + relativedelta(days=5)
                self.qs = self.qs.select_related('loan__offer', 'loan__loan_status').filter(
                    application_status__status_code=self.status_code,
                    loan__loan_status__status_code__range=(
                        LoanStatusCodes.CURRENT, LoanStatusCodes.RENEGOTIATED),
                    loan__fund_transfer_ts__range=[start_date, end_date],
                    is_courtesy_call=False,
                    loan__offer__first_payment_date__gt=dpd_min_5)
            else:
                if self.is_jstarter:
                    self.qs = self.qs.filter(
                        application_status__status_code=self.status_code,
                        partner=None
                    )

                    if self.status_code == '121':
                        hide_account_440 = (
                            Account.objects.filter(
                                status=JuloOneCodes.FRAUD_REPORTED,
                                customer_id__in=list(self.qs.values_list('customer_id', flat=True)),
                            )
                            .values_list('customer_id', flat=True)
                        )

                        self.qs = self.qs.exclude(customer_id__in=list(hide_account_440))
                elif self.is_revive_mtl:
                    self.qs = self.qs.filter(
                        application_status__status_code=self.status_code,
                        id__in=list(mtl_application_ids),
                        partner=None
                    )
                elif self.is_j1_assisted_agent:
                    self.qs = self.qs.filter(
                        mobile_phone_1__isnull=False,
                        ktp__isnull=False,
                        email__isnull=False,
                        application_status_id=ApplicationStatusCodes.FORM_CREATED,
                        workflow__name=WorkflowConst.JULO_ONE,
                        onboarding_id=OnboardingIdConst.LONGFORM_SHORTENED_ID,
                    )

                    customer_ids_otp_verified = (
                        OtpRequest.objects.filter(
                            is_used=True,
                            customer_id__in=list(self.qs.values_list('customer_id', flat=True)),
                            action_type__in=(
                                SessionTokenAction.VERIFY_PHONE_NUMBER,
                                SessionTokenAction.PHONE_REGISTER,
                            ),
                        )
                        .distinct('customer_id')
                        .values_list('customer_id', flat=True)
                    )

                    self.qs = self.qs.filter(customer_id__in=list(customer_ids_otp_verified))

                    app_ids_has_image_ktp = (
                        Image.objects.filter(
                            image_source__in=list(self.qs.values_list('id', flat=True)),
                            image_type='ktp_self',
                            image_status=Image.CURRENT,
                        )
                        .distinct('image_source')
                        .values_list('image_source', flat=True)
                    )

                    app_ids_has_image = (
                        Image.objects.filter(
                            image_source__in=list(app_ids_has_image_ktp),
                            image_type='selfie',
                            image_status=Image.CURRENT,
                        )
                        .distinct('image_source')
                        .values_list('image_source', flat=True)
                    )

                    self.qs = self.qs.filter(id__in=list(app_ids_has_image))
                else:
                    self.qs = self.qs.filter(
                        application_status__status_code=self.status_code
                    ).exclude(partner__name__in=partner_list)
        else:
            self.status_code = "Seluruh Data"

        self.qs = self.qs.order_by('-cdate', '-udate', 'id', 'fullname', 'email')

        self.err_message_here = None
        self.tgl_range = None
        self.tgl_start = None
        self.tgl_end = None
        self.status_app = None
        self.search_q = None
        self.sort_q = None
        self.status_now = None

        # print "self.request.GET: ", self.request.GET
        if self.request.method == 'GET':
            self.tgl_range = self.request.GET.get('datetime_range', None)
            self.status_app = self.request.GET.get('status_app', None)
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.sort_q = self.request.GET.get('sort_q', None)
            self.status_now = self.request.GET.get('status_now', None)
            self.qs = self.qs.annotate(
                crm_url=Value('%s/applications/' % settings.CRM_BASE_URL,
                              output_field=CharField()))

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_, [
                    Q(**{('%s__icontains' % 'fullname'): self.search_q}),
                    Q(**{('bank_account_number'): self.search_q}),
                    Q(**{('%s__icontains' % 'ktp'): self.search_q}),
                    Q(**{('%s__icontains' % 'mobile_phone_1'): self.search_q}),
                    Q(**{('%s__icontains' % 'id'): self.search_q}),
                    Q(**{('%s__icontains' % 'email'): self.search_q}),
                    Q(**{('%s__icontains' % 'product_line__product_line_type'): self.search_q}),
                    Q(**{('%s__icontains' % 'product_line__product_line_code'): self.search_q})
                ]))

            if (self.status_now):
                # print "OKAY STATUS NOW : ", self.status_now
                if (self.status_now == 'True'):
                    # print "HARI INI"
                    startdate = datetime.datetime.today()
                    startdate = startdate.replace(hour=0, minute=0, second=0)
                    enddate = startdate + datetime.timedelta(days=1)
                    enddate = enddate - datetime.timedelta(seconds=1)
                    self.qs = self.qs.filter(cdate__range=[startdate, enddate])
                else:
                    _date_range = self.tgl_range.split('-')
                    if (_date_range[0].strip() != 'Invalid date'):
                        _tgl_mulai = datetime.datetime.strptime(_date_range[0].strip(),
                                                                "%d/%m/%Y %H:%M")
                        _tgl_end = datetime.datetime.strptime(_date_range[1].strip(),
                                                              "%d/%m/%Y %H:%M")
                        # print "BEBAS"
                        if (_tgl_end > _tgl_mulai):
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.err_message_here = "Format Tanggal tidak valid"

            if self.sort_q:
                if self.sort_q == 'disbursementDate':
                    self.qs = self.qs.annotate(Max('loan__disbursement__cdate')).order_by(
                        'loan__disbursement__cdate__max')
                elif (self.sort_q == '-disbursementDate'):
                    self.qs = self.qs.annotate(Max('loan__disbursement__cdate')).order_by(
                        '-loan__disbursement__cdate__max'
                    )
                elif self.sort_q == 'os_name':
                    self.qs = self.qs.order_by('os_name', '-id')
                elif self.sort_q == '-os_name':
                    self.qs = self.qs.order_by('-os_name', '-id')
                else:
                    self.qs = self.qs.order_by(self.sort_q)

        else:
            print("else request GET")

        if self.status_code in list(map(str, app_status_julo_one)):
            if self.is_julo_one or self.is_revive_mtl:
                self.qs = self.qs.filter(workflow__name__in=[
                        WorkflowConst.JULO_ONE, WorkflowConst.JULO_ONE_IOS])
            else:
                if self.status_code in list(map(str, app_status_grab)):
                    self.qs = self.qs.exclude(workflow__name__in=[
                        WorkflowConst.JULO_ONE, WorkflowConst.GRAB,
                        WorkflowConst.JULO_ONE_IOS])
                else:
                    self.qs = self.qs.exclude(workflow__name__in=[
                        WorkflowConst.JULO_ONE, WorkflowConst.JULO_ONE_IOS])

        if self.status_code in list(map(str, app_status_grab)):
            if self.is_grab:
                self.qs = self.qs.filter(product_line__product_line_code__in=ProductLineCodes.grab())
            elif self.is_jstarter:
                self.qs = self.qs.filter(product_line__product_line_code__in=ProductLineCodes.turbo())
            else:
                self.qs = self.qs.exclude(
                    product_line__product_line_code__in=(ProductLineCodes.grab() + ProductLineCodes.turbo())
                )

        if self.status_code in list(map(str, app_status_jstarter)) and self.is_jstarter:
            self.qs = self.qs.filter(workflow__name=WorkflowConst.JULO_STARTER)

        if self.status_code == str(ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL):
            application_ids = self.qs.filter(
                workflow__name=WorkflowConst.JULO_ONE).values_list('id', flat=True)
            application_ids_124_sonic_and_hsfb = ApplicationHistory.objects.filter(
                application_id__in=application_ids,
                status_new=ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
                change_reason__in=JuloOneChangeReason.NOT_REGULAR_VERIFICATION_CALLS_SUCCESSFUL_REASON
            ).values_list('application_id', flat=True)
            self.qs = self.qs.filter(workflow__name__in=[
                WorkflowConst.JULO_ONE,
                WorkflowConst.GRAB
            ])
            if not self.is_julo_one:
                self.qs = self.qs.filter(
                    Q(id__in=application_ids_124_sonic_and_hsfb) | Q(
                        workflow__name=WorkflowConst.GRAB)
                )
            else:
                self.qs = self.qs.exclude(
                    id__in=application_ids_124_sonic_and_hsfb
                ).exclude(workflow__name=WorkflowConst.GRAB)

        if self.status_code == '175' and self.is_julo_one:
            self.qs = self.qs.exclude(id__in=list(mtl_application_ids))

        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(ApplicationDataWSCListView, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = ApplicationSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = ApplicationSearchForm()

        # to check field application.product_line.product_line_code
        product_line_STL = (ProductLineCodes.STL1, ProductLineCodes.STL2)

        customer_ids = list(context.get('object_list').values_list('customer_id', flat=True))
        customer_ids_on_deletion = get_ongoing_account_deletion_requests(customer_ids)
        if customer_ids_on_deletion:
            customer_ids_on_deletion = customer_ids_on_deletion.values_list('customer_id', flat=True)

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        if (self.courtesy_call == True):
            context['status_code_now'] = "Courtesy Call - 180"
        else:
            context['status_code_now'] = self.status_code
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        # print "parameters: ", parameters
        context['parameters'] = parameters
        context['app_lock_status'] = LOCK_STATUS_LIST
        context['change_reasons_status'] = CHANGE_REASONS_FIELD
        context['app_id_locked'] = app_lock_list()
        context['product_line_STL'] = product_line_STL
        context['bucket_code'] = self.bucket_code
        if self.status_code == '165':
            context['balance_list'] = dict(
                # Xendit=get_julo_balance('Xendit'),
                Xfers=get_julo_balance('Xfers'),
                Bca=get_julo_balance('Bca'),
                Instamoney=get_julo_balance('Instamoney')
            )
        context['customer_ids_on_deletion'] = customer_ids_on_deletion

        context['query_notes'] = []
        if self.status_code in ('130', '138'):
            query_notes = (
                ApplicationNote.objects.values('application_id')
                .annotate(last_udate=Max('udate'))
                .filter(
                    application_id__in=list(context.get('object_list').values_list('id', flat=True))
                )
            )
            context['query_notes'] = query_notes

        return context

    def get(self, request, *args, **kwargs):
        self.courtesy_call = False
        try:
            self.status_code = self.kwargs['status_code']
        except:
            self.status_code = None
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super(ApplicationDataWSCListView, self).render_to_response(context,
                                                                               **response_kwargs)
        return rend_here

    def get_lender_bucket(self):
        self.model = LenderBucket

        # print "status_code: ", self.status_code
        self.qs = super(ApplicationDataWSCListView, self).get_queryset(
        ).select_related('partner').order_by('-is_active', '-is_disbursed', '-cdate')

        self.err_message_here = None
        self.tgl_range = None
        self.tgl_start = None
        self.tgl_end = None
        self.status_app = None
        self.search_q = None
        self.sort_q = None
        self.status_now = None

        # print "self.request.GET: ", self.request.GET
        if self.request.method == 'GET':
            self.tgl_range = self.request.GET.get('datetime_range', None)
            self.status_app = self.request.GET.get('status_app', None)
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.sort_q = self.request.GET.get('sort_q', None)
            self.status_now = self.request.GET.get('status_now', None)

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_, [
                    Q(**{('%s__icontains' % 'id'): self.search_q}),
                    Q(**{('%s__icontains' % 'partner__name'): self.search_q}),
                ]))

            if (self.status_now):
                # print "OKAY STATUS NOW : ", self.status_now
                if (self.status_now == 'True'):
                    # print "HARI INI"
                    startdate = datetime.datetime.today()
                    startdate = startdate.replace(hour=0, minute=0, second=0)
                    enddate = startdate + datetime.timedelta(days=1)
                    enddate = enddate - datetime.timedelta(seconds=1)
                    self.qs = self.qs.filter(cdate__range=[startdate, enddate])
                else:
                    _date_range = self.tgl_range.split('-')
                    if (_date_range[0].strip() != 'Invalid date'):
                        _tgl_mulai = datetime.datetime.strptime(_date_range[0].strip(),
                                                                "%d/%m/%Y %H:%M")
                        _tgl_end = datetime.datetime.strptime(_date_range[1].strip(),
                                                              "%d/%m/%Y %H:%M")
                        # print "BEBAS"
                        if (_tgl_end > _tgl_mulai):
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.err_message_here = "Format Tanggal tidak valid"

            if (self.sort_q):
                self.qs = self.qs.order_by(self.sort_q)

        else:
            print("else request GET")

        return self.qs


def redirect_application(request, pk):
    app_obj = get_object_or_404(Application, id=pk)

    template_name = 'object/app_status/redirect.html'

    return render(
        request,
        template_name,
        {
            'application_id': app_obj.id

        }
    )


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class ApplicationDataWSCPriorityListView(ListView):
    model = Application
    paginate_by = 50  # get_conf("PAGINATION_ROW")
    template_name = 'object/app_status/list_w_status.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        # print "http_method_not_allowed"
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        # print "get_template_names"
        return ListView.get_template_names(self)

    def get_base_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(
                os_name=Case(
                    When(workflow__name='JuloOneIOSWorkflow', then=Value('A_iOS')),
                    When(
                        workflow__name__in=['JuloOneWorkflow', 'JuloStarterWorkflow'],
                        then=Value('A_Android'),
                    ),
                    default=Value('Z_-'),
                    output_field=CharField(),
                )
            )
        )

    def get_queryset(self):
        # print "status_code: ", self.status_code
        partner_list = LIST_PARTNER

        self.qs = self.get_base_queryset().select_related(
            'product_line', 'application_status', 'customer', 'device', 'account'
        )

        if self.status_code:
            if self.status_code == '999':
                self.status_code = 'Cashback Request'
                cb_app_ids = get_cashback_request()
                self.qs = self.qs.filter(pk__in=cb_app_ids)

            elif self.status_code == '199':
                self.status_code = 180
                self.courtesy_call = True
                start_date, end_date = courtesy_call_range()
                today = timezone.now().date()
                dpd_min_5 = today + relativedelta(days=5)
                self.qs = self.qs.select_related('loan__offer', 'loan__loan_status').filter(
                    application_status__status_code=self.status_code,
                    loan__loan_status__status_code__range=(
                        LoanStatusCodes.CURRENT, LoanStatusCodes.RENEGOTIATED),
                    loan__fund_transfer_ts__range=[start_date, end_date],
                    is_courtesy_call=False,
                    loan__offer__first_payment_date__gt=dpd_min_5)
            else:
                self.qs = self.qs.filter(application_status__status_code=self.status_code,
                                         partner__name__in=partner_list)
        else:
            self.status_code = "Seluruh Data"

        self.qs = self.qs.order_by('-cdate', '-udate', 'id', 'fullname', 'email')

        self.err_message_here = None
        self.tgl_range = None
        self.tgl_start = None
        self.tgl_end = None
        self.status_app = None
        self.search_q = None
        self.sort_q = None
        self.status_now = None

        # print "self.request.GET: ", self.request.GET
        if self.request.method == 'GET':
            self.tgl_range = self.request.GET.get('datetime_range', None)
            self.status_app = self.request.GET.get('status_app', None)
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.sort_q = self.request.GET.get('sort_q', None)
            self.status_now = self.request.GET.get('status_now', None)
            self.qs = self.qs.annotate(
                crm_url=Value('%s/applications/' % settings.CRM_BASE_URL,
                              output_field=CharField()))

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_, [
                    Q(**{('bank_account_number'): self.search_q}),
                    Q(**{('%s__icontains' % 'fullname'): self.search_q}),
                    Q(**{('%s__icontains' % 'ktp'): self.search_q}),
                    Q(**{('%s__icontains' % 'mobile_phone_1'): self.search_q}),
                    Q(**{('%s__icontains' % 'id'): self.search_q}),
                    Q(**{('%s__icontains' % 'email'): self.search_q}),
                    Q(**{('%s__icontains' % 'product_line__product_line_type'): self.search_q}),
                    Q(**{('%s__icontains' % 'product_line__product_line_code'): self.search_q})
                ]))

            if (self.status_now):
                # print "OKAY STATUS NOW : ", self.status_now
                if (self.status_now == 'True'):
                    # print "HARI INI"
                    startdate = datetime.datetime.today()
                    startdate = startdate.replace(hour=0, minute=0, second=0)
                    enddate = startdate + datetime.timedelta(days=1)
                    enddate = enddate - datetime.timedelta(seconds=1)
                    self.qs = self.qs.filter(cdate__range=[startdate, enddate])
                else:
                    _date_range = self.tgl_range.split('-')
                    if (_date_range[0].strip() != 'Invalid date'):
                        _tgl_mulai = datetime.datetime.strptime(_date_range[0].strip(),
                                                                "%d/%m/%Y %H:%M")
                        _tgl_end = datetime.datetime.strptime(_date_range[1].strip(),
                                                              "%d/%m/%Y %H:%M")
                        # print "BEBAS"
                        if (_tgl_end > _tgl_mulai):
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.err_message_here = "Format Tanggal tidak valid"

            if self.sort_q:
                if self.sort_q == 'disbursementDate':
                    self.qs = self.qs.annotate(Max('loan__disbursement__cdate')).order_by(
                        'loan__disbursement__cdate__max')
                elif (self.sort_q == '-disbursementDate'):
                    self.qs = self.qs.annotate(Max('loan__disbursement__cdate')).order_by(
                        '-loan__disbursement__cdate__max'
                    )
                elif self.sort_q == 'os_name':
                    self.qs = self.qs.order_by('os_name', '-id')
                elif self.sort_q == '-os_name':
                    self.qs = self.qs.order_by('-os_name', '-id')
                else:
                    self.qs = self.qs.order_by(self.sort_q)

        else:
            print("else request GET")

        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(ApplicationDataWSCPriorityListView, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = ApplicationSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = ApplicationSearchForm()

        # to check field application.product_line.product_line_code
        product_line_STL = (ProductLineCodes.STL1, ProductLineCodes.STL2)

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        if (self.courtesy_call == True):
            context['status_code_now'] = "Courtesy Call - 180"
        else:
            context['status_code_now'] = self.status_code
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        # print "parameters: ", parameters
        context['parameters'] = parameters
        context['app_lock_status'] = LOCK_STATUS_LIST
        context['change_reasons_status'] = CHANGE_REASONS_FIELD
        context['app_id_locked'] = app_lock_list()
        context['product_line_STL'] = product_line_STL
        return context

    def get(self, request, *args, **kwargs):
        self.courtesy_call = False
        try:
            self.status_code = self.kwargs['status_code']
        except:
            self.status_code = None
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super(ApplicationDataWSCPriorityListView, self).render_to_response(context,
                                                                                       **response_kwargs)
        return rend_here


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class ApplicationDetailView(DetailView):
    model = Application
    template_name = 'object/app_status/details.html'

    def get_context_data(self, **kwargs):
        history_note_list = get_list_history(self.get_object())

        context = super(ApplicationDetailView, self).get_context_data(**kwargs)
        context['now'] = timezone.now()
        context['history_note_list'] = history_note_list
        context['rupiah_sequence'] = (59, 61, 62, 63, 64,)
        context['option_list'] = ValidationCheckForm.GPS_RANGE

        return context


# ----------------------------- Seluruh data END ---------------------------------------


# ----------------------------- VCHECK Start  ---------------------------------------


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def verification_check(request, pk):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    app_obj = get_object_or_404(Application, id=pk)

    template_name = 'object/app_status/cr_up_vcheck.html',

    # check the status list is exists on application_data_check
    app_check_cnt = ApplicationDataCheck.objects.filter(application_id=app_obj.id).count()
    if (app_check_cnt == 0):
        # create if doesnot exists
        create_data_verification_checks(app_obj)
    elif (app_check_cnt == 68):
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
                        if check_obj.number_value != _clean_data and _clean_data and _clean_data != '':
                            check_obj.number_value = _clean_data
                    else:
                        if check_obj.text_value != _clean_data:
                            check_obj.text_value = _clean_data
                        if _clean_data and _clean_data != '':
                            check_obj.number_value = int(
                                str(_clean_data).replace(' ', '').replace('.', '').replace(',', ''))
                    check_obj.save()

            url = reverse('loan_app:detail_verification_check', kwargs={'pk': app_obj.id})
            return redirect(url)
        else:
            print("Form is not valid")

    else:
        print("::GET::")
        form = ValidationCheckForm(app_check_queryset)

    return render(
        request,
        template_name,
        {
            'form': form,
            'app_obj': app_obj,
            'app_check_queryset': app_check_queryset,
            'datetime_now': timezone.now(),
            'number_seq_list': (18, 19, 20, 21, 22, 23, 24, 25, 53,),
        }
    )


# ----------------------------- VCHECK END  ------------------------------------------------

# ----------------------------- Change Status START  ---------------------------------------


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def change_app_status(request, pk):
    if not request.user.is_authenticated or user_has_collection_blacklisted_role(request.user):
        return render(request, 'covid_refinancing/404.html')

    # check if there is application found (if not then display 404)
    try:
        app_obj = (
            Application.objects
            .select_related('account')
            .select_related('application_status')
            .select_related('customer')
            .select_related('customer__user')
            .select_related('name_bank_validation')
            .select_related('partner')
            .select_related('loan')
            .select_related('workflow')
            .select_related('product_line')
            .prefetch_related('account__accountlimit_set')
            .prefetch_related('account__accountproperty_set')
            .prefetch_related('devicescrapeddata_set')
            .prefetch_related('offer_set')
            .get(id=pk)
        )
    except Application.objects.model.DoesNotExist:
        raise Http404('No %s matches the given query.' % Application.objects.model._meta.object_name)

    status_current = app_obj.application_status
    current_user = request.user

    # Fraud tab data
    account_status_current = 0
    account_set_limit = 0
    enable_fraud_mitigation = "no"
    # Email templates
    fraud_email_template_code = {
        '440-420': "crm_fraud_account_reset_success",
        '440-432': "crm_fraud_account_closed",
        '442-420-waived': "crm_fraud_already_waived",
        '442-420-not-waived': "crm_fraud_not_yet_waived"
    }
    fruad_templates_folder = 'fraud/'
    available_context = {
        'fullname': app_obj.full_name_only,
        'banner_url': EmailOTP.BANNER_URL,
        'footer_url': EmailOTP.FOOTER_URL,
    }
    fraud_email_template_dict = {
        '440-420': render_to_string(
            fruad_templates_folder + fraud_email_template_code['440-420'] + '.html',
            available_context),
        '440-432': render_to_string(
            fruad_templates_folder + fraud_email_template_code['440-432'] + '.html',
            available_context),
        '442-420-waived': render_to_string(fruad_templates_folder + \
                                           fraud_email_template_code['442-420-waived'] + '.html',
                                           available_context),
        '442-420-not-waived': render_to_string(fruad_templates_folder + \
                                               fraud_email_template_code[
                                                   '442-420-not-waived'] + '.html',
                                               available_context)
    }
    if app_obj.account and \
            status_current.status_code == ApplicationStatusCodes.LOC_APPROVED:
        account = app_obj.account
        account_status_current = account.status_id
        if account_status_current in [
            JuloOneCodes.FRAUD_REPORTED,
            JuloOneCodes.SCAM_VICTIM,
            JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
            JuloOneCodes.ACTIVE,
            JuloOneCodes.SUSPENDED,
            JuloOneCodes.ACTIVE_IN_GRACE, ]:
            enable_fraud_mitigation = "yes"
            total_outstanding_due_amount = account.get_total_outstanding_amount()
            account_limit = account.accountlimit_set.last()
            if account_limit:
                account_set_limit = account_limit.set_limit

            fraud_status_type = 'STATUS_' + str(account_status_current)
            fraud_status_move_list = getattr(FraudStatusMove, fraud_status_type)

            app_changes_mobile = ApplicationFieldChange.objects.filter(
                application=app_obj, field_name='mobile_phone_1').first()
            registered_phone_number = app_obj.mobile_phone_1
            if app_changes_mobile:
                registered_phone_number = app_changes_mobile.old_value \
                    if app_changes_mobile.old_value else app_changes_mobile.new_value

            registered_email = app_obj.email
            app_changes_email = ApplicationFieldChange.objects.filter(
                application=app_obj, field_name='email').first()
            if app_changes_email:
                registered_email = app_changes_email.old_value

            device_list = Device.objects.filter(customer_id=account.customer_id)

            # Check for FraudCrmForm data in process for account take over
            account_take_over_data = FraudCrmForm.objects.filter(account=account).last()
            saved_fraud_form_data = {}
            if account_take_over_data and account_status_current == JuloOneCodes.FRAUD_REPORTED:
                saved_fraud_form_data = account_take_over_data.saved_value

            last_fraud_note = FraudNote.objects.filter(customer=app_obj.customer).last()
            fraud_note_text = last_fraud_note.note_text if last_fraud_note else ""

    max_set_limit_fraud = AccountStatusMove.MAX_SET_LIMIT

    template_name = 'object/app_status/change_status.html'
    message_out_ubah_status = None
    message_out_simpan_note = None
    message_out_security_note = None
    ubah_status_active = 0
    simpan_note_active = 0
    security_note_active = 0
    julo_product_line_code = (ProductLineCodes.STL1, ProductLineCodes.STL2,
                              ProductLineCodes.MTL1, ProductLineCodes.MTL2, ProductLineCodes.BRI1,
                              ProductLineCodes.BRI2,
                              ProductLineCodes.GRAB1, ProductLineCodes.GRAB2,
                              ProductLineCodes.GRABF1, ProductLineCodes.GRABF2,
                              ProductLineCodes.PEDEMTL1, ProductLineCodes.PEDEMTL2,
                              ProductLineCodes.PEDESTL1, ProductLineCodes.PEDESTL2,
                              ProductLineCodes.GRAB)
    # message_out_update_app = None
    # update_app_active = 0
    autodebet_obj = AutodebetAccount.objects.filter(
        account=app_obj.account, vendor=AutodebetVendorConst.BCA)

    # For the new additional fields on Crm-ADBCA agent menu
    autodebet_account_last = autodebet_obj.filter(
        is_use_autodebet=True,
        deduction_cycle_day__isnull=False).last()
    is_group_experiment = 'Tidak'
    deduction_cycle_day = None
    if autodebet_account_last:
        deduction_cycle_day = autodebet_account_last.deduction_cycle_day
    elif app_obj.account:
        deduction_cycle_day = determine_best_deduction_day(app_obj.account)

    if deduction_cycle_day:
        experiment_setting = ExperimentSetting.objects.filter(
            code=ExperimentConst.BEST_DEDUCTION_TIME_ADBCA_EXPERIMENT_CODE).last()
        experiment_group = ExperimentGroup.objects.filter(
            experiment_setting=experiment_setting,
            account_id=app_obj.account.id).last()
        if experiment_group and experiment_group.group == 'experiment':
            is_group_experiment = 'Ya'

    status_reasons = {
        str(JuloOneCodes.FRAUD_REPORTED): ['Reported fraud', 'Confirmed fraud'],
        str(JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD): [
            'Application/friendly fraud',
            'Confirmed fraud',
        ],
    }

    if request.method == 'POST':
        request.session['security_note_active'] = ''
        form = StatusChangesForm(status_current, app_obj, request.POST)
        # re-configure request.POST for loan
        form_app = ApplicationForm(
            request.POST, instance=app_obj, prefix='form2')
        form_app_select = ApplicationSelectFieldForm(
            app_obj, request.POST, prefix='form2')
        form_hsfbp = HsfbpIncomeVerificationForm(request.POST)
        form_security = SecurityForm(request.POST)
        if form.is_valid():
            if 'ubah_status' in request.POST:
                print("ubah_status-> valid here")

            status_to = form.cleaned_data['status_to']
            reason = form.cleaned_data['reason_str']
            notes = form.cleaned_data['notes']

            logger.info({
                'status_to': status_to,
                'reason': reason,
                'notes': notes
            })

            try:
                with transaction.atomic():
                    if (
                        app_obj.application_status.status_code
                        == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                        and (app_obj.is_julo_one() or app_obj.is_julo_one_ios())
                    ):
                        list_of_tags = ['is_sonic', 'is_hsfbp']
                        application_tag_status = ApplicationPathTagStatus.objects.filter(
                            application_tag__in=list_of_tags, definition='success')
                        application_tag = ApplicationPathTag.objects.filter(
                            application_id=app_obj.id,
                            application_path_tag_status__in=application_tag_status).last()
                        if application_tag:
                            tag_result = application_tag.application_path_tag_status.application_tag
                        else:
                            tag_result = None

                        if tag_result in list_of_tags and int(status_to) == 124:
                            logger.info({
                                "message": "change_app_status move to x124",
                                "application": app_obj.id,
                                "tag_result": tag_result
                            })
                            process_application_status_change(
                                app_obj,
                                int(status_to),
                                reason
                            )

                            if tag_result == 'is_sonic':
                                change_reason = FeatureNameConst.SONIC_BYPASS
                            else:
                                change_reason = FeatureNameConst.HIGH_SCORE_FULL_BYPASS

                            app = Application.objects.get_or_none(pk=app_obj.id)

                            if app.is_assisted_selfie is None:
                                app.update_safely(is_assisted_selfie=False)

                            if is_experiment_application(app_obj.id, 'ExperimentUwOverhaul') and \
                                    app.status == ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL:
                                logger.info({
                                    "message": "change_app_status move to x124 have experiment uw",
                                    "application": app_obj.id,
                                })
                                process_application_status_change(
                                    app_obj,
                                    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                                    change_reason
                                )

                        elif int(status_to) == 124:
                            from juloserver.application_flow.services import (
                                check_bpjs_entrylevel,
                            )
                            logger.info({
                                "message": "change_app_status move to x124 outside list of tags",
                                "application": app_obj.id,
                            })
                            process_application_status_change(
                                app_obj, int(status_to), reason, note=notes)

                            app = Application.objects.get_or_none(pk=app_obj.id)

                            if app.is_assisted_selfie is None:
                                app.update_safely(is_assisted_selfie=False)

                            if app.status == ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL:
                                is_bpjs_el = check_bpjs_entrylevel(app_obj)
                                if is_bpjs_el:
                                    logger.info({
                                        "message": "change_app_status() is_bpjs_el",
                                        "app.id": app.id,
                                        "app_obj.id": app_obj.id,
                                        "app.status": app.status,
                                        "app_obj.status": app_obj.status
                                    })
                                    process_application_status_change(
                                        app_obj.id, ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                                        'bpjs_entrylevel')
                                elif is_experiment_application(app_obj.id, 'ExperimentUwOverhaul') and \
                                        not list_experiment_application('ExperimentOverhaulApplicationStuck124',
                                                                        app_obj.id):
                                    logger.info({
                                        "message": "change_app_status() good payslip bypass",
                                        "app.id": app.id,
                                        "app_obj.id": app_obj.id,
                                        "app.status": app.status,
                                        "app_obj.status": app_obj.status
                                    })
                                    process_application_status_change(
                                        app_obj, ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                                        'good_payslip_bypass')
                        else:
                            logger.info({
                                "message": "change_app_status move to target status",
                                "status_to": int(status_to),
                                "application": app_obj.id,
                            })
                            process_application_status_change(
                                app_obj, int(status_to), reason, note=notes)
                    elif app_obj.application_status.status_code == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED \
                            or app_obj.application_status.status_code == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS \
                            and app_obj.is_julo_starter:
                        logger.info({
                            "message": "change_app_status move to target 121",
                            "status_to": int(status_to),
                            "application": app_obj.id,
                        })
                        process_application_status_change(
                            app_obj, int(status_to), reason, note=notes)

                        exist = ApplicationHistory.objects.filter(
                            application_id=app_obj.id,
                            status_new=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
                        ).exists()

                        if exist:
                            app = Application.objects.get_or_none(pk=app_obj.id)
                            if app.status == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD or \
                                    app.status == ApplicationStatusCodes.APPLICATION_DENIED:
                                reason = JuloStarter190RejectReason.REJECT

                                status_to = ApplicationStatusCodes.LOC_APPROVED
                                process_application_status_change(
                                    app_obj, int(status_to), reason, note=notes)

                                if app.status == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD:
                                    account = app_obj.account
                                    account_status_new = int(JuloOneCodes.DEACTIVATED)
                                    process_change_account_status(
                                        account,
                                        account_status_new,
                                        reason,
                                        manual_change=True
                                    )

                    elif app_obj.application_status.status_code == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER \
                            and app_obj.is_julover():
                        app_obj.refresh_from_db()
                        if app_obj.name_bank_validation.is_success:
                            logger.info({
                                "message": "change_app_status move to target 141",
                                "status_to": int(status_to),
                                "application": app_obj.id,
                            })
                            process_application_status_change(
                                app_obj, int(status_to), reason, note=notes)
                    else:
                        logger.info({
                            "message": "change_app_status move to target status else condition",
                            "status_to": int(status_to),
                            "application": app_obj.id,
                        })
                        process_application_status_change(
                            app_obj, int(status_to), reason, note=notes)

                # remarked , there is no unlock after change status
                # if status_current.status_code in LOCK_STATUS_LIST:
                #     ret_unlocked = unlocked_app_from_user(app_obj, request.user, status_to)
                #     print "ret_unlocked: ", ret_unlocked
                # else:
                #     print "status code %s not in LOCK_STATUS_LIST" % (status_current)

                # check if status moved to x127
                if int(status_to) == ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL and (
                    app_obj.is_julo_one() or app_obj.is_julo_one_ios()
                ):
                    from juloserver.moengage.services.use_cases import (
                        send_user_attributes_to_moengage_for_typo_calls_unsuccessful,
                    )
                    # prepare notification to user
                    logger.info({
                        'application': app_obj.id,
                        'process': 'CRM-moengage_for_typo_calls_unsuccessful'
                    })
                    send_user_attributes_to_moengage_for_typo_calls_unsuccessful.delay(
                        app_obj.id,
                        WorkflowConst.JULO_ONE
                    )

                url = reverse('app_status:change_status', kwargs={'pk': app_obj.id})
                # return render(request, 'object/app_status/blank.html')
                return redirect(url)

            except Exception as e:
                err_msg = """
                            Ada Kesalahan di Backend Server!!!, Harap hubungi Administrator : %s
                            """
                sentry_client.captureException()
                traceback.print_exc()
                # there is an error
                err_msg = err_msg % (e)
                logger.info({
                    'app_id': app_obj.id,
                    'error': "Ada Kesalahan di Backend Server with \
                    process_application_status_change !!!."
                })
                # messages.error(request, err_msg)
                message_out_ubah_status = err_msg
                ubah_status_active = 1

        else:
            if 'notes_only' in request.POST:
                try:
                    notes = form.cleaned_data['notes_only']
                    print("simpan_note-> notes: ", notes)

                    if notes:
                        application_note = ApplicationNote.objects.create(
                            note_text=notes,
                            application_id=app_obj.id,
                            added_by_id=current_user.id,
                        )
                        logger.info(
                            {
                                'application_note': application_note,
                            }
                        )

                        url = reverse('app_status:change_status', kwargs={'pk': app_obj.id})
                        return redirect(url)
                    else:
                        err_msg = """
                            Note/Catatan Tidak Boleh Kosong !!!
                        """
                        # messages.error(request, err_msg)
                        message_out_simpan_note = err_msg
                        simpan_note_active = 1

                except Exception as e:
                    err_msg = """
                        Catatan Tidak Boleh Kosong !!!
                    """
                    # messages.error(request, err_msg)
                    message_out_simpan_note = err_msg
                    simpan_note_active = 1
            elif 'security_note' in request.POST:
                try:
                    security_note = request.POST['security_note']

                    if security_note:
                        SecurityNote.objects.create(
                            note_text=security_note,
                            customer=app_obj.customer,
                            added_by=request.user)
                        logger.info({
                            'security_note': security_note,
                        })

                        request.session['security_note_active'] = 1
                        url = reverse('app_status:change_status',
                                      kwargs={'pk': app_obj.id})
                        return redirect(url)
                    else:
                        err_msg = """
                            Note/Catatan Tidak Boleh Kosong !!!
                        """
                        message_out_security_note = err_msg

                except Exception as e:
                    err_msg = """
                        Catatan Tidak Boleh Kosong !!!
                    """
                    message_out_security_note = err_msg
            elif 'fraud_note' in request.POST:
                try:
                    fraud_note = request.POST['fraud_note']
                    account_status_new = request.POST['account_status_new']
                    account = app_obj.account
                    old_status_id = account.status_id
                    if account_status_new == "":
                        account_take_over = request.POST['account_take_over']
                        if account_take_over == 'yes':
                            account_status_new = JuloOneCodes.ACTIVE
                        else:
                            account_status_new = JuloOneCodes.TERMINATED

                    account_status_new = int(account_status_new)
                    if fraud_note and account_status_new and old_status_id != account_status_new:
                        with transaction.atomic():
                            email_to = app_obj.email
                            if account_status_new == JuloOneCodes.ACTIVE and \
                                    old_status_id == JuloOneCodes.FRAUD_REPORTED:

                                from juloserver.antifraud.tasks.fraud_block import (
                                    deactivate_fraud_block,
                                )

                                deactivate_fraud_block.delay(app_obj.customer_id)

                                # update email/phone
                                if 'magic_link_email' in saved_fraud_form_data:
                                    email_to = saved_fraud_form_data['magic_link_email']
                                    if saved_fraud_form_data['magic_link_email'] != app_obj.email:
                                        customer_service = CustomerService()
                                        customer_service.change_email(
                                            app_obj.customer.user,
                                            saved_fraud_form_data['magic_link_email'])
                                        app_obj.refresh_from_db()
                                if 'magic_link_phone' in saved_fraud_form_data:
                                    if app_obj.mobile_phone_1 != saved_fraud_form_data[
                                        'magic_link_phone']:
                                        change_success, _, _ = change_customer_primary_phone_number(
                                            app_obj, saved_fraud_form_data['magic_link_phone'])
                                        app_obj.refresh_from_db()

                                # Delete FraudCrmForm data
                                if account_take_over_data:
                                    account_take_over_data.delete()

                            account_change_reason = request.POST.get(
                                'account_status_new_reason',
                                AccountStatusMove.REASONS[account_status_new],
                            )

                            process_change_account_status(
                                account,
                                account_status_new,
                                str(account_change_reason),
                                manual_change=True
                            )

                            # send email to customer
                            fraud_email_content = request.POST['fraud_email_content']
                            fraud_email_template_key = request.POST['fraud_email_template_key']
                            if account_status_new in [JuloOneCodes.ACTIVE, JuloOneCodes.TERMINATED]:
                                if not fraud_email_template_key:
                                    fraud_email_template_key = str(old_status_id) + "-" + str(
                                        account_status_new)
                                    if account_status_new == JuloOneCodes.ACTIVE and old_status_id == JuloOneCodes.SCAM_VICTIM:
                                        is_already_waived = request.POST['is_already_waived']
                                        if is_already_waived:
                                            is_waved_template_key = "-waved" if is_already_waived == "yes" else "-not-waived"
                                            fraud_email_template_key += is_waved_template_key
                                if fraud_email_template_key in fraud_email_template_dict:
                                    if not fraud_email_content:
                                        fraud_email_content = fraud_email_template_dict[
                                            fraud_email_template_key]
                                    template_code = fraud_email_template_code[
                                        fraud_email_template_key]
                                    # send account related email
                                    email_history = send_email_fraud_mitigation(app_obj,
                                                                                fraud_email_content,
                                                                                template_code,
                                                                                email_to=email_to)

                            # Delete from intellix
                            if account_status_new in [
                                JuloOneCodes.FRAUD_REPORTED,
                                JuloOneCodes.SCAM_VICTIM,
                                JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD]:
                                delete_account_from_intelix_if_exists_async_for_j1.delay(account.id)

                            account_limit = account.accountlimit_set.last()
                            if account_status_new == JuloOneCodes.SCAM_VICTIM and account_limit.set_limit > max_set_limit_fraud:
                                account_limit.update_safely(set_limit=max_set_limit_fraud)
                            # save to fraud note
                            FraudNote.objects.create(
                                note_text=fraud_note,
                                customer=app_obj.customer,
                                added_by=current_user,
                                status_change=account.accountstatushistory_set.last())

                            url = reverse('app_status:change_status',
                                          kwargs={'pk': app_obj.id})
                            return redirect(url)
                    else:
                        err_msg = """
                            Note/Catatan Tidak Boleh Kosong !!!
                        """
                        message_out_fraud_changes = err_msg

                except Exception as e:
                    err_msg = """
                        Catatan Tidak Boleh Kosong !!!
                    """
                    message_out_fraud_changes = err_msg
                    sentry_client.captureException()
                    logger.info({
                        'action': "fraud_mitigation",
                        'application_id': app_obj.id,
                        'exception': e
                    })
            elif 'autodebit_notes' in request.POST:
                try:
                    notes = form.cleaned_data['autodebit_notes']
                    print("simpan_note-> notes: ", notes)

                    if notes:
                        current_autodebet_obj = autodebet_obj.last()
                        current_autodebet_obj.notes = notes
                        current_autodebet_obj.save()

                        url = reverse('app_status:change_status', kwargs={'pk': app_obj.id})
                        return redirect(url)

                except Exception as e:
                    err_msg = """
                        Catatan Tidak Boleh Kosong !!!
                    """
                    # messages.error(request, err_msg)
                    message_out_simpan_note = err_msg
                    simpan_note_active = 1
            else:
                # form is not valid
                err_msg = """
                    Ubah Status atau Alasan harus dipilih dahulu !!!
                """
                # messages.error(request, err_msg)
                message_out_ubah_status = err_msg
                ubah_status_active = 1

    else:
        form = StatusChangesForm(status_current, app_obj)
        form_app = ApplicationForm(
            instance=app_obj, prefix='form2')
        form_app_select = ApplicationSelectFieldForm(app_obj, prefix='form2')
        form_security = SecurityForm()
        form_hsfbp = HsfbpIncomeVerificationForm(request.POST)
        if request.session.get('security_note_active'):
            security_note_active = request.session.get('security_note_active')
            request.session['security_note_active'] = ''
        else:
            security_note_active = 0
            request.session['security_note_active'] = ''

    image_list = Image.objects.filter(
        image_source=app_obj.id,
        image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
    )
    ktp_self_image = image_list.filter(image_type='ktp_self').last()
    results_json = ExtJsonSerializer().serialize(
        image_list,
        props=['image_url', 'image_ext'],
        fields=('image_type',)
    )

    image_list_1 = Image.objects.filter(image_source=app_obj.id, image_status=Image.DELETED)
    results_json_1 = ExtJsonSerializer().serialize(
        image_list_1,
        props=['image_url', 'image_ext'],
        fields=('image_type',)
    )
    voice_list = VoiceRecord.objects.filter(
        application=app_obj.id,
        status__in=[VoiceRecord.CURRENT, VoiceRecord.RESUBMISSION_REQ]
    )
    results_json_2 = ExtJsonSerializer().serialize(
        voice_list,
        props=['presigned_url'],
        fields=('status')
    )

    voice_list_1 = VoiceRecord.objects.filter(
        application=app_obj.id,
        status=VoiceRecord.DELETED
    )
    results_json_3 = ExtJsonSerializer().serialize(
        voice_list_1,
        props=['presigned_url'],
        fields=('status')
    )

    history_note_list = get_list_history_all(app_obj)

    bank_statement = get_lbs_submission(app_obj)
    is_soft_deleted = is_customer_soft_deleted(history_note_list)
    email_sms_list = get_list_email_history(app_obj)
    app_detail_history_list = get_app_detail_list_history(app_obj)
    customer = app_obj.customer
    security_note_list = SecurityNote.objects.filter(customer=customer).order_by('-cdate')
    skiptrace_list = Skiptrace.objects.filter(customer=customer).order_by('id')
    skiptrace_history_list = SkiptraceHistory.objects.filter(application=app_obj).order_by(
        '-cdate')[:100]

    from juloserver.bpjs.services import Bpjs
    bpjs = Bpjs(application=app_obj)
    bpjs_details = bpjs.detail()
    if not bpjs.is_scraped:
        bpjs_details = None

    sd_data = app_obj.device_scraped_data.last()
    if sd_data and not sd_data.reports_xls_s3_url:
        sd_data = None

    etl_job = EtlJob.objects.filter(
        application_id=pk, status='load_success',
        data_type__in=['bca', 'mandiri', 'bni', 'bri']).order_by('-cdate').first()

    if etl_job:
        bank_report_url = etl_job.get_bank_report_url()
        bank_report_name = bank_report_url.split('.xlsx')[0] if \
            bank_report_url else ''
    else:
        bank_report_url = ''
        bank_report_name = ''

    list_skiptrace_status = (121, 122, 1220, 123, 124, 1240,
                             125, 127, 130, 131, 132, 138,
                             1380, 141, 144, 172, 180)

    status_skiptrace = True if app_obj.status in list_skiptrace_status else False

    partner_referral = None
    partner_account_id = None
    account_doku_julo = None
    # doku is deprecated code removed

    # get fb data
    fb_obj = app_obj.facebook_data if hasattr(app_obj, 'facebook_data') else None

    # get loan data and order by offer_number
    offer_set_objects = app_obj.offer_set.all().order_by("offer_number")
    button_lock = get_app_lock_count(app_obj)
    lock_status, lock_by = get_lock_status(app_obj, request.user)
    # print "lock_status, lock_by: ", lock_status, lock_by
    min_income_due = 413000
    app_data_fields, app_data_values = dump_application_values_to_excel(app_obj)

    app_data = get_data_application_checklist_collection(app_obj, for_app_only=True)
    deprecated_list = (
        'address_kodepos', 'address_kecamatan', 'address_kabupaten',
        'bank_scrape', 'address_kelurahan', 'address_provinsi', 'bidang_usaha'
    )
    calculation_view_statuses = (130, 134, 140, 141, 142, 143, 144, 160, 161)

    # For CA combo calculation
    product_rate = None
    calculation_results = None
    sum_undisclosed_expense = 0
    if 'total_current_debt' in app_data:
        for expense in app_data['total_current_debt']['undisclosed_expenses']:
            sum_undisclosed_expense += expense['amount']
    if app_obj.partner and app_obj.partner.name in LIST_PARTNER:
        pass
    elif app_obj.status in calculation_view_statuses:
        # logic ITIFTC to use perdicted income here
        monthly_income = get_monthly_income_by_experiment_group(app_obj)
        input_params = {
            'product_line_code': app_obj.product_line_id,
            'job_start_date': app_obj.job_start,
            'job_end_date': timezone.localtime(app_obj.cdate).date(),
            'job_type': app_obj.job_type,
            'monthly_income': monthly_income,
            'monthly_expense': app_obj.monthly_expenses,
            'dependent_count': app_obj.dependent,
            'undisclosed_expense': sum_undisclosed_expense,
            'monthly_housing_cost': app_obj.monthly_housing_cost,
            'application': app_obj,
            'application_id': app_obj.id,
            'application_xid': app_obj.application_xid,
        }

        if not app_obj.is_merchant_flow() and not app_obj.is_julover() and not app_obj.is_grab():
            calculation_results = compute_affordable_payment(**input_params)

            calculation_results['undisclosed_expense'] = sum_undisclosed_expense
            if app_obj.product_line_id not in chain(ProductLineCodes.loc(),
                                                    ProductLineCodes.grabfood(),
                                                    ProductLineCodes.laku6(),
                                                    ProductLineCodes.julo_one(),
                                                    ProductLineCodes.grab()):
                offer_recommendations_output = get_offer_recommendations(
                    app_obj.product_line_id,
                    app_obj.loan_amount_request,
                    app_obj.loan_duration_request,
                    calculation_results['affordable_payment'],
                    app_obj.payday,
                    app_obj.ktp,
                    app_obj.id,
                    app_obj.partner
                )
                product_rate = offer_recommendations_output['product_rate']

    offers = None
    offer_form = None
    product_line = None
    email = None
    if app_obj.product_line_id:
        if app_obj.product_line_id in julo_product_line_code:
            offers = app_obj.offer_set.all().order_by('offer_number')
            offer = Offer(application=app_obj,
                          product=app_obj.product_line.productlookup_set.all().first())
            offer_form = OfferForm(instance=offer, prefix='form2')
            product_line = app_obj.product_line.productlookup_set.all()

    if app_obj.email:
        email = app_obj.email.lower()

    form_email = SendEmailForm()
    email_statuses = (121, 132, 138, 122, 130, 131, 135)
    disbursement_statuses = (ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                             ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                             ApplicationStatusCodes.NAME_VALIDATE_FAILED)

    if app_obj.status < ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        disbursement = None
        bank_number_validate = None
        name_validate = None
    else:
        if hasattr(app_obj, 'loan'):
            loan = app_obj.loan
            disbursement = Disbursement.objects.get_or_none(loan=loan)
            if disbursement is not None:
                if disbursement.bank_number is None:
                    bank_number_validate = 'PENDING'
                else:
                    bank_number_validate = 'VALID'

                if disbursement.validated_name is None:
                    name_validate = 'PENDING'
                elif str(disbursement.validated_name).lower() != str(app_obj.name_in_bank).lower():
                    name_validate = 'INVALID'
                else:
                    name_validate = 'VALID'
            else:
                bank_number_validate = 'NOT INITIATED'
                name_validate = 'NOT INITIATED'
        else:
            disbursement = None
            bank_number_validate = None
            name_validate = None

    xfers_balance = None
    bca_balance = None
    if app_obj.status in disbursement_statuses:
        xfers_balance = get_julo_balance_from_cache('Xfers')
        bca_balance = get_julo_balance_from_cache('Bca')

    canned_responses = CannedResponse.objects.all()
    email_app_params = {
        'FULL_NAME': app_obj.fullname_with_title,
        'LOAN_AMOUNT': app_obj.loan_amount_request,
        'LOAN_DURATION': app_obj.loan_duration_request,
        'LOAN_PURPOSE': app_obj.loan_purpose,
        'AGENT_NAME': request.user.username,
    }

    # cashback redeem detail
    wallet_notes = get_wallet_list_note(customer)
    bucket_code = request.GET.get('bucket_code')
    cashback_transfers = CashbackTransferTransaction.objects.filter(
        application=app_obj
    ).exclude(bank_code=GopayConst.BANK_CODE)
    if bucket_code == BucketCode.CASHBACK_REQUEST:
        cashback_transfer = cashback_transfers.filter(
            transfer_status=CashbackTransferConst.STATUS_REQUESTED
        ).last()
    elif bucket_code == BucketCode.CASHBACK_PENDING:
        cashback_transfer = cashback_transfers.filter(
            transfer_status=CashbackTransferConst.STATUS_PENDING
        ).last()
    elif bucket_code == BucketCode.CASHBACK_FAILED:
        cashback_transfer = cashback_transfers.filter(
            transfer_status=CashbackTransferConst.STATUS_FAILED
        ).last()
    else:
        cashback_transfer = cashback_transfers.last()
    cashback_external_id = None
    cashback_retry_times = None
    if cashback_transfer:
        if cashback_transfer.transfer_id:
            try:
                cashback_disbursement = get_disbursement(cashback_transfer.transfer_id)
                cashback_external_id = cashback_disbursement['external_id']
                cashback_retry_times = cashback_disbursement['retry_times']
            except Exception as e:
                logger.info({
                    'application_id': app_obj.id,
                    'cashback_transfer_transfer_id': cashback_transfer.transfer_id,
                    'exception': e
                })

    skip_pv_dv = False
    if customer.potential_skip_pv_dv:
        applications = customer.application_set.filter(
            application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        ).order_by('id')
        application_before = applications.exclude(id__gte=app_obj.id).last()
        if application_before:
            paid_off_date = application_before.loan.payment_set.last().paid_date
            if paid_off_date:
                apply_date = app_obj.cdate
                range_day = (apply_date.date() - paid_off_date).days
                if range_day <= 90:
                    skip_pv_dv = True

    agent_update_app_status = 1
    hsfbp_verified_income = app_obj.hsfbp_verified_income()
    high_score_full_bypass_status = check_high_score_full_bypass(app_obj)
    if is_experiment_application(app_obj.id, 'ExperimentUwOverhaul') and (
        app_obj.is_julo_one() or app_obj.is_julo_one_ios()
    ):
        high_score_full_bypass_status = app_obj.has_pass_hsfbp()

    sonic_bypass_status = app_obj.has_pass_sonic()
    offline_activation_flow_status = eligible_to_offline_activation_flow(app_obj)
    if app_obj.status in AgentUpdateAppSettings.RESTRICTED_STATUSES:
        agent_update_app_status = 0

    # disbursement detail
    new_xfers = False
    name_bank_validation = None
    disbursement2 = None
    julo_balance = None
    disburse_process_statuses = NAME_BANK_VALIDATION_STATUSES + DISBURSEMENT_STATUSES
    disbursement_method_list = []
    validation_method_list = []

    # for multi disbursement partner
    partner_banks = None
    partner_disbursement = list()
    if app_obj.partner and app_obj.partner.name == PARTNER_LAKU6:
        partner_banks = PartnerBankAccount.objects.filter(partner=app_obj.partner).all()

        # partner name validation
        for p_banks in partner_banks:
            p_banks.name_bank_validation = get_name_bank_validation(p_banks.name_bank_validation_id)
        if app_obj.partner and app_obj.partner.name == PARTNER_LAKU6:
            name_bank_validation = NameBankValidation.objects.filter(
                account_number=app_obj.bank_account_number,
                name_in_bank=app_obj.name_in_bank,
                mobile_phone=app_obj.mobile_phone_1,
            ).last()
            if name_bank_validation:
                name_bank_validation_id = name_bank_validation.id
                validation_method_list = get_list_validation_method()
                name_bank_validation = get_name_bank_validation(name_bank_validation_id)
            else:
                name_bank_validation_id = None
                validation_method_list = None
                name_bank_validation = None

    if app_obj.status in disburse_process_statuses:
        if hasattr(app_obj, 'loan'):
            loan = app_obj.loan
            if app_obj.partner and app_obj.partner.name == PARTNER_LAKU6:
                invoices = LoanDisburseInvoices.objects.filter(loan=loan).all()
                # partner disbursement
                for invoice in invoices:
                    p_disbursement = get_disbursement(invoice.disbursement_id)
                    partner_disbursement.append(p_disbursement)
            else:
                validation_method_list = get_list_validation_method()
                name_bank_validation = get_name_bank_validation(loan.name_bank_validation_id)
                disbursement_method_list = get_list_disbursement_method(bank_name=app_obj.bank_name)
                if name_bank_validation is not None:
                    disbursement_method_list = get_list_disbursement_method(
                        app_obj.bank_name, name_bank_validation['method'])
                new_xfers, disbursement2 = get_multi_step_disbursement(loan.disbursement_id,
                                                                       loan.lender_id)
                julo_balance = None

    limit_info = None

    if (
        app_obj.is_julo_one() or app_obj.is_julo_one_ios() or app_obj.is_grab()
    ) and app_obj.status in (
        ApplicationStatusCodes.NAME_VALIDATE_FAILED,
        ApplicationStatusCodes.LOC_APPROVED,
        ApplicationStatusCodes.NAME_BANK_VALIDATION_FAILED,
        ApplicationStatusCodes.BANK_NAME_CORRECTED,
    ):
        name_bank_validation = app_obj.name_bank_validation
        if name_bank_validation:
            name_bank_validation_id = name_bank_validation.id
            validation_method_list = get_list_validation_method()
            name_bank_validation = get_name_bank_validation(name_bank_validation_id)

    if is_experiment_application(app_obj.id, 'ExperimentUwOverhaul') and (
        app_obj.is_julo_one() or app_obj.is_julo_one_ios()
    ):
        is_experiment = True
        target_status = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        experiment = {
            'is_experiment': is_experiment,
            'target_status': target_status
        }
    else:
        is_experiment = False
        if app_obj.is_julover():
            target_status = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        else:
            target_status = ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL
        experiment = {'is_experiment': is_experiment, 'target_status': target_status}
    if (
        app_obj.is_julo_one() or app_obj.is_julo_one_ios() or app_obj.is_julover()
    ) and app_obj.status == target_status:
        validation_method_list = get_list_validation_method()
        name_bank_validation = get_name_bank_validation(app_obj.name_bank_validation_id)

    if (app_obj.is_julo_one() or app_obj.is_julo_one_ios()) and app_obj.status in [
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        ApplicationStatusCodes.LOC_APPROVED,
        ApplicationStatusCodes.NAME_BANK_VALIDATION_FAILED,
    ]:
        account = app_obj.account
        account_limit = account.accountlimit_set.last()
        account_property = account.accountproperty_set.last()
        _matrix, self_interest = get_credit_matrix_and_credit_matrix_product_line(
            app_obj,
            is_self_bank_account=True
        )
        _matrix, other_interest = get_credit_matrix_and_credit_matrix_product_line(
            app_obj,
            is_self_bank_account=False
        )
        limit_info = {
            'account_limit': account_limit.set_limit,
            'self_interest': '{}%'.format(self_interest.interest * 100),
            'other_interest': '{}%'.format(other_interest.interest * 100),
            'cycle_day': account.cycle_day,
            'concurrency': account_property.concurrency,
            'is_entry_level': is_entry_level_type(app_obj)
        }

    risky_checklist = app_obj.get_last_risky_check()

    risky_fraud_list = None
    if risky_checklist:
        risky_fraud_list = risky_checklist.get_fraud_list()

    # Start of Dukcapil Logic
    dukcapil_response = get_existing_dukcapil_response(app_obj)
    if app_obj.is_partnership_leadgen():
        dukcapil_verification_setting = get_dukcapil_verification_setting_leadgen(
            app_obj.partner.name
        )
    else:
        dukcapil_verification_setting = DukcapilVerificationSetting()
    if dukcapil_response and dukcapil_verification_setting.is_triggered_after_binary_check:
        dukcapil_tab_statuses = DIRECT_DUKCAPIL_TAB_CRM_STATUSES
    else:
        dukcapil_tab_statuses = DUKCAPIL_TAB_CRM_STATUSES

    highlight_dukcapil_tab = True
    if dukcapil_response:
        highlight_dukcapil_tab = dukcapil_response.highlight_dukcapil_tab()
    # End of Dukcapil Logic

    # overpaid + count number of rejected times for each case
    overpaid_cases = CashbackOverpaidVerification.objects.filter(
        application=app_obj,
    ).annotate(
        rejected_times=Count(
            Case(When(Q(overpaid_history__decision=OverpaidConsts.Statuses.REJECTED), then=1)),
        )
    ).order_by('-cdate')
    # sort to put pending to top
    overpaid_cases = sorted(overpaid_cases, key=overpaid_status_sorting_func)

    is_hidden_menu = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CRM_HIDE_MENU,
        is_active=True).last()

    hide_tabs = []
    if is_hidden_menu and current_user.crmsetting.role_select in is_hidden_menu.parameters['roles']:
        hide_tabs = is_hidden_menu.parameters['menu']
    mycroft_score_ana = PdApplicationFraudModelResult.objects.filter(application_id=app_obj.id).last()
    mycroft_score = None
    if mycroft_score_ana:
        mycroft_score = ceil(mycroft_score_ana.pgood * 100) / 100

    is_vcdv = registration_method_is_video_call(app_obj)

    from juloserver.application_form.services.idfy_service import (
        compare_application_data_idfy,
        edited_data_comparison,
        transform_data_from_video_call,
    )
    is_edited_application, different_data = compare_application_data_idfy(app_obj)
    edited_data = edited_data_comparison(app_obj, different_data)
    data_video_call, is_match_for_job = transform_data_from_video_call(app_obj)

    is_superuser = request.user.is_superuser
    if is_superuser:
        restrict_data_for_sales_ops_role = False
    else:
        restrict_data_for_sales_ops_role = request.user.groups.filter(name=JuloUserRoles.SALES_OPS).exists()

    is_can_assisted_agent_j1 = False
    if (
        (app_obj.is_julo_one() or app_obj.is_julo_one_ios())
        and app_obj.mobile_phone_1
        and app_obj.ktp
        and app_obj.email
        and app_obj.application_status_id == ApplicationStatusCodes.FORM_CREATED
        and app_obj.onboarding_id == OnboardingIdConst.LONGFORM_SHORTENED_ID
    ):
        # check ktp image
        current_image_ktp = Image.objects.filter(
            image_source=app_obj.id,
            image_type='ktp_self',
            image_status=Image.CURRENT,
        ).exists()

        # check image selfie
        current_image_selfie = Image.objects.filter(
            image_source=app_obj.id,
            image_type='selfie',
            image_status=Image.CURRENT,
        ).exists()

        if current_image_ktp and current_image_selfie:
            is_can_assisted_agent_j1 = True

    context = {
        'form': form,
        'uw_tag': app_obj.is_uw_overhaul,
        'form_app': form_app,
        'form_hsfbp': form_hsfbp,
        'restrict_data_for_sales_ops_role': restrict_data_for_sales_ops_role,
        'form_app_select': form_app_select,
        'form_security': form_security,
        'app_obj': app_obj,
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
        'bank_statement': bank_statement,
        'datetime_now': timezone.now(),
        'image_per_row0': (1, 7, 13, 19, 25),
        'image_per_row': (7, 13, 19, 25),
        'lock_status': lock_status,
        'lock_by': lock_by,
        'button_lock': button_lock,
        'message_out_simpan_note': message_out_simpan_note,
        'message_out_ubah_status': message_out_ubah_status,
        'message_out_security_note': message_out_security_note,
        'security_note_active': security_note_active,
        'ubah_status_active': ubah_status_active,
        'simpan_note_active': simpan_note_active,
        'min_income_due': min_income_due,
        'offer_set_objects': offer_set_objects,
        'app_data_values': None,
        'app_data_fields': app_data_fields,
        'skiptrace_list': skiptrace_list,
        'skiptrace_history_list': skiptrace_history_list,
        'status_skiptrace': status_skiptrace,
        'partner_referral': partner_referral,
        'partner_account_id': partner_account_id,
        'account_doku_julo': account_doku_julo,
        'app_data': app_data,
        'deprecated_list': deprecated_list,
        'offers': offers,
        'offer_form': offer_form,
        'calculation_view_statuses': calculation_view_statuses,
        'product_line': product_line,
        'calculation_results': calculation_results,
        'product_rate': product_rate,
        'product_line_STL': ProductLineCodes.stl(),
        'product_line_BRI': ProductLineCodes.bri(),
        'product_line_GRAB': ProductLineCodes.grab(),
        'product_line_LOC': ProductLineCodes.loc(),
        'product_line_GRABFOOD': ProductLineCodes.grabfood(),
        'form_send_email': form_email,
        'app_email': email,
        'email_statuses': email_statuses,
        'email_sms_list': email_sms_list,
        'disbursement': disbursement,
        'bank_number_validate': bank_number_validate,
        'name_validate': name_validate,
        'bank_list': BankManager.get_bank_names(),
        'bank_name_list': json.dumps(BankManager.get_bank_names()),
        'app_detail_history_list': app_detail_history_list,
        'xfers_balance': xfers_balance,
        'bca_balance': bca_balance,
        'canned_responses': canned_filter(canned_responses),
        'email_app_params': json.dumps(email_app_params),
        'cashback_transfer': cashback_transfer,
        'cashback_external_id': cashback_external_id,
        'cashback_retry_times': cashback_retry_times,
        'wallet_notes': wallet_notes,
        'skip_pv_dv': skip_pv_dv,
        'agent_update_app_status': agent_update_app_status,
        'disburse_process_statuses': disburse_process_statuses,
        'disbursement_statuses': DISBURSEMENT_STATUSES,
        'name_bank_validation': name_bank_validation,
        'digisign_failed': ApplicationStatusCodes.DIGISIGN_FAILED,
        'disbursement2': disbursement2,
        'julo_balance': julo_balance,
        'disbursement_method_list': disbursement_method_list,
        'validation_method_list': validation_method_list,
        'partner_transfers': CashbackTransferConst.partner_transfers,
        'partner_banks': partner_banks,
        'partner_disbursement': partner_disbursement,
        'product_line_PEDESTL': ProductLineCodes.pedestl(),
        'product_line_PEDEMTL': ProductLineCodes.pedemtl(),
        'partner_laku6': PARTNER_LAKU6,
        'new_xfers': new_xfers,
        'is_suspect_va': suspect_account_number_is_va(app_obj.bank_account_number,
                                                      app_obj.bank_name),
        'bpjs_details': bpjs_details,
        'sd_data': sd_data,
        'bank_report_url': bank_report_url,
        'bank_report_name': bank_report_name,
        'is_c_score_in_delay_period': is_c_score_in_delay_period(app_obj),
        'eta_time_for_c_score_delay': format_datetime(
            timezone.localtime(get_eta_time_for_c_score_delay(app_obj)),
            'd MMMM yyyy HH:mm', locale='id_ID'
        ),
        'julo_one_limit_info_status': [ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                                       ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
                                       ApplicationStatusCodes.LOC_APPROVED],
        'julo_one_bank_name_status': [ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                                       ApplicationStatusCodes.BANK_NAME_CORRECTED],
        'limit_info': limit_info,
        'julo_one_product_code': ProductLineCodes.J1,
        'pd_bank_scrape_model_result': check_positive_processed_income(app_obj.id),
        'security_note_list': security_note_list,
        'is_grab': app_obj.is_grab(),
        'risky_fraud_list': risky_fraud_list,
        'hsfbp_verified_income': hsfbp_verified_income,
        'check_high_score_full_bypass': high_score_full_bypass_status,
        'dukcapil_response': dukcapil_response,
        'dukcapil_tab_statuses': dukcapil_tab_statuses,
        'highlight_dukcapil_tab': highlight_dukcapil_tab,
        'ktp_self_image_url': ktp_self_image.image_url if ktp_self_image else None,
        'fraud_check_status_list': JuloOneCodes.fraud_check(),
        'max_set_limit_fraud': max_set_limit_fraud,
        'saved_fraud_form_data': {},
        'account_status_current': account_status_current,
        'account_set_limit': account_set_limit,
        'enable_fraud_mitigation': enable_fraud_mitigation,
        'fraud_email_template_dict': json.dumps(fraud_email_template_dict),
        'experiment': experiment,
        'check_sonic_bypass': sonic_bypass_status,
        'check_offline_activation_flow': offline_activation_flow_status,
        'overpaid_cases': overpaid_cases,
        'autodebet_obj': autodebet_obj.order_by('-registration_ts'),
        'agent_id': current_user.id,
        'deduction_cycle_day': deduction_cycle_day,
        'is_group_experiment': is_group_experiment,
        'jstarter_fields': get_js_validation_fields(app_obj),
        'hide_tabs': hide_tabs,
        'mycroft_score': mycroft_score,
        'is_vcdv': is_vcdv,
        'is_edited_application': is_edited_application,
        'edited_data': edited_data,
        'is_request_deletion': get_ongoing_account_deletion_request(customer) is not None,
        'data_video_call': data_video_call,
        'is_match_for_job': is_match_for_job,
        'is_soft_deleted': is_soft_deleted,
        'is_can_assisted_agent_j1': is_can_assisted_agent_j1,
        'is_julo_one_ios': app_obj.is_julo_one_ios(),
    }

    if hasattr(app_obj, 'product_line'):
        product_line = app_obj.product_line_id
        bank_name_validated = is_bank_name_validated(app_obj)
        if product_line in ProductLineCodes.mtl():
            check_point_lists = [
                'menandatangani SPHP secara elektronik di dalam aplikasi.',
                'merekam pernyataan dengan lengkap (kalau tidak lengkap, pencairan akan terhambat)'
            ]
            if not bank_name_validated:
                check_point_lists.insert(0,
                                         "melakukan validasi akun rekening bank Anda di Aplikasi JULO")
            context['check_point_lists'] = check_point_lists
        elif product_line in ProductLineCodes.stl():
            context['validate_bank_account'] = bank_name_validated

    # Fraud tab data
    if enable_fraud_mitigation == "yes":
        context['fraud_note_text'] = fraud_note_text
        context['total_outstanding_due_amount'] = total_outstanding_due_amount
        context['registered_phone_number'] = registered_phone_number
        context['registered_email'] = registered_email
        context['device_list'] = device_list
        context['saved_fraud_form_data'] = json.dumps(saved_fraud_form_data)
        context['fraud_status_move_list'] = fraud_status_move_list
        context['status_reasons'] = status_reasons

    # is_partnership_leadgen
    is_partnership_leadgen = False
    list_image_partnership_liveness = []
    json_list_image_partnership_liveness = None
    if app_obj.is_partnership_leadgen():
        from juloserver.partnership.services.services import partnership_get_image_liveness_result

        is_partnership_leadgen = True
        list_image_partnership_liveness = partnership_get_image_liveness_result(pk)
        if list_image_partnership_liveness:
            json_list_image_partnership_liveness = ExtJsonSerializer().serialize(
                list_image_partnership_liveness,
                props=['image_url', 'image_ext'],
                fields=('image_type',),
            )
    context['is_partnership_leadgen'] = is_partnership_leadgen
    context['list_image_partnership_liveness'] = list_image_partnership_liveness
    context['json_list_image_partnership_liveness'] = json_list_image_partnership_liveness

    return render(
        request,
        template_name,
        context
    )


@julo_login_required
def change_app_status_by_customer(request, customer_id):
    customer = Customer.objects.get(id=customer_id)
    application = customer.application_set.regular_not_deletes().last()
    redirect_url = reverse('app_status:change_status', args=[application.id])
    redirect_url = '{}?{}'.format(redirect_url, request.GET.urlencode())
    return HttpResponseRedirect(redirect_url)


# ----------------------------- Change Status END  ---------------------------------------


# -----------------------------   AJAX   START  ---------------------------------------

@csrf_protect
def check_app_priority(request):
    current_user = request.user

    response_data = {}
    # set max count lock app
    is_finance_agent = current_user.groups.filter(name='bo_finance').last()
    if is_finance_agent:
        max_agents_lock_app = FIN_MAX_COUNT_LOCK_APP

    if request.method == 'GET':
        application_id = request.GET.get('application_id')

        if application_id == '' or application_id is None:
            return HttpResponse(
                json.dumps({
                    "reason": "the application id not allowed to be empty",
                    'result': "failed!"
                }),
                content_type="application/json"
            )

        application_id = int(application_id)
        app_obj = Application.objects.get_or_none(pk=application_id)

        if app_obj:
            app_priority = ApplicationHistory.objects.filter(
                Q(application_id=app_obj.id) &
                (Q(change_reason__icontains=JuloOneChangeReason.REVIVE) |
                 Q(change_reason__icontains=JuloOneChangeReason.RESCORE))
            ).exists()

            app_note_priority = ApplicationNote.objects.filter(
                Q(application_id=app_obj.id) &
                (Q(note_text__icontains=JuloOneChangeReason.REVIVE) |
                 Q(note_text__icontains=JuloOneChangeReason.RESCORE))
            )

            if app_priority or app_note_priority:
                response_data['code'] = '02'
                response_data['reason'] = 'RESCORE/REVIVE'
                response_data['result'] = 'PRIORITY_02'
                return HttpResponse(
                    json.dumps(response_data),
                    content_type="application/json"
                )
            else:
                response_data['code'] = '01'
                response_data['reason'] = 'ORGANIC'
                response_data['result'] = 'PRIORITY_01'

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
def check_app_locked(request):
    # print "f(x) populate_reason INSIDE"
    # TODO: check only bo_data_verifier or document verifier role can access
    current_user = request.user
    max_agents_lock_app = MAX_COUNT_LOCK_APP

    response_data = {}
    # set max count lock app
    is_finance_agent = current_user.groups.filter(name='bo_finance').last()
    if is_finance_agent:
        max_agents_lock_app = FIN_MAX_COUNT_LOCK_APP

    # check max agents locking app
    agent_locked_count = get_user_lock_count(current_user)
    # print "agent_locked_count: ", agent_locked_count

    if request.method == 'GET':
        application_id = request.GET.get('application_id')

        if application_id == '' or application_id is None:
            return HttpResponse(
                json.dumps({
                    "reason": "the application id should not empty",
                    'result': "failed!"
                }),
                content_type="application/json"
            )

        application_id = int(application_id)
        app_obj = Application.objects.get_or_none(pk=application_id)

        if app_obj:
            ret_cek_app = check_lock_app(app_obj, current_user)
            if ret_cek_app[0] == 1:
                response_data['code'] = '01'
                response_data['result'] = 'successful!'
                response_data['reason'] = 'application is allowed for this %s' % (current_user)
                return HttpResponse(
                    json.dumps(response_data),
                    content_type="application/json"
                )
            elif (agent_locked_count >= max_agents_lock_app):
                response_data['code'] = '09'
                response_data['result'] = 'failed!'
                response_data['reason'] = 'aplikasi lock oleh agent <code>%s</code> \
                telah lebih dari %d!' % (request.user, max_agents_lock_app)
                return HttpResponse(
                    json.dumps(response_data),
                    content_type="application/json"
                )
            elif ret_cek_app[0] == 2:
                app_locked_obj = ret_cek_app[1]
                response_data['code'] = '02'
                response_data['result'] = 'failed!'
                response_data['reason'] = (
                    'application is locked for this',
                    lock_by_user(app_locked_obj),
                    app_locked_obj.first().status_code_locked,
                    datetime.datetime.strftime(
                        app_locked_obj.first().ts_locked,
                        "%d %b %Y %H:%M:%S"
                    ),
                )
            else:
                response_data['code'] = '03'
                response_data['result'] = 'successful!'
                response_data['reason'] = 'application is free and still not locked'

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
def set_app_locked(request):
    """
    """
    max_agents_lock_app = MAX_COUNT_LOCK_APP
    current_user = request.user
    response_data = {}

    # set max count lock app
    is_finance_agent = current_user.groups.filter(name='bo_finance').last()
    if is_finance_agent:
        max_agents_lock_app = FIN_MAX_COUNT_LOCK_APP

    # check max agents locking app
    agent_locked_count = get_user_lock_count(current_user)
    # print "agent_locked_count: ", agent_locked_count

    if (agent_locked_count >= max_agents_lock_app):
        response_data['result'] = 'failed!'
        response_data['reason'] = 'aplikasi lock by agent <code>%s</code> \
        telah lebih dari %d!' % (request.user, max_agents_lock_app)
        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )

    if request.method == 'GET':
        application_id = request.GET.get('application_id')

        if application_id == '' or application_id is None:
            return HttpResponse(
                json.dumps({
                    "reason": "the application id should not empty",
                    'result': "failed!"
                }),
                content_type="application/json"
            )

        application_id = int(application_id)
        app_obj = Application.objects.get_or_none(pk=application_id)

        if app_obj and request.user:
            ret_master = ApplicationLockedMaster.create(
                user=request.user, application=app_obj, locked=True)
            if ret_master:
                ApplicationLocked.create(
                    application=app_obj, user=request.user,
                    status_code_locked=app_obj.application_status.status_code)
                response_data['result'] = 'successful!'
                response_data['reason'] = 'application is locked'
            else:
                ret_master_obj = ApplicationLockedMaster.objects.get_or_none(
                    application=app_obj)
                response_data['result'] = 'failed!'
                if ret_master_obj:
                    response_data['reason'] = 'Aplikasi telah di lock oleh %s dengan TS: \
                    %s' % (ret_master_obj.user_lock, ret_master_obj.ts_locked)
                else:
                    response_data['reason'] = 'Aplikasi telah di lock'
        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'user not login or application not exist'

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
def set_app_unlocked(request):
    """
    """
    current_user = request.user
    # print "current_user: ", current_user

    if request.method == 'GET':
        application_id = request.GET.get('application_id')

        if application_id == '' or application_id is None:
            return HttpResponse(
                json.dumps({
                    "reason": "the application id should not empty",
                    'result': "failed!"
                }),
                content_type="application/json"
            )

        application_id = int(application_id)
        app_obj = Application.objects.get_or_none(pk=application_id)

        response_data = {}
        if app_obj and current_user:
            app_locked_master = ApplicationLockedMaster.objects.get_or_none(application=app_obj)

            if app_locked_master:
                app_locked = ApplicationLocked.objects.filter(
                    application=app_obj, user_lock=current_user, locked=True)

                if app_locked.count() > 0:
                    print("app_locked: ", app_locked[0].user_lock)
                    unlocked_app(app_locked[0], current_user)

                    response_data['result'] = 'successful!'
                    response_data['reason'] = 'Application <code>%s</code> \
                    Succesfully Un-Locked' % app_obj.id

                    # delete master locked
                    app_locked_master.delete()

                else:
                    flag_admin = True
                    # check if admin, so it can be unlocked
                    if role_allowed(current_user,
                                    ['admin_unlocker', 'collection_supervisor',
                                     'ops_supervisor', 'ops_team_leader']):
                        app_locked_here = ApplicationLocked.objects.filter(
                            application=app_obj, locked=True).first()
                        if app_locked_here:
                            unlocked_app(
                                app_locked_here, current_user,
                                app_obj.application_status.status_code
                            )
                            response_data['result'] = 'successful!'
                            response_data['reason'] = 'Application <code>%s</code> \
                            Succesfully Un-Locked by Admin' % app_obj.id

                            # delete master locked
                            app_locked_master.delete()

                        else:
                            flag_admin = False
                    else:
                        flag_admin = False

                    if (not flag_admin):
                        response_data['result'] = 'failed!'
                        response_data['reason'] = 'application is lock by %s, \
                        you are not allowed to unlock!' % (app_locked_master.user_lock)
            else:
                response_data['result'] = 'failed!'
                response_data['reason'] = 'application locked master not exists, \
                application still not un-locked, please refresh your browser!'
        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'user not login or application not exist'

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
def image_resubmission(request):
    """
    """
    current_user = request.user
    print("current_user: ", current_user)

    if request.method == 'GET':

        image_id = int(request.GET.get('image_id'))
        image_req = request.GET.get('image_action')
        image_obj = Image.objects.get_or_none(pk=image_id)

        response_data = {}
        if image_obj and current_user:
            # save image resubmission request
            if image_req == 'KirimUlang':
                image_obj.image_status = Image.RESUBMISSION_REQ
            else:
                image_obj.image_status = Image.CURRENT
            image_obj.save()

            response_data['result'] = 'successful!'
            response_data['reason'] = 'Image <code>%s</code> , action: %s sukses' % (
                image_obj.id, image_req)

        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'Image id does not exist'

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
def voice_resubmission(request):
    """
    """
    current_user = request.user
    logger.info({
        'current_user': current_user
    })

    if request.method == 'GET':

        voice_id = int(request.GET.get('voice_id'))
        voice_req = request.GET.get('voice_action')
        voice_obj = VoiceRecord.objects.get_or_none(pk=voice_id)

        response_data = {}
        if voice_obj and current_user:
            # save image resubmission request
            if voice_req == 'KirimUlang':
                voice_obj.status = VoiceRecord.RESUBMISSION_REQ
            else:
                voice_obj.status = VoiceRecord.CURRENT
            voice_obj.save()

            response_data['result'] = 'successful!'
            response_data['reason'] = 'Voice <code>%s</code> , action: %s sukses' % (
                voice_obj.id, voice_req)

        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'Voice id does not exist'

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
def voice_records_script(request):
    """
    """
    current_user = request.user
    logger.info({
        'current_user': current_user
    })

    if request.method == 'GET':
        application_id = request.GET.get('application_id')

        if application_id == '' or application_id is None:
            return HttpResponse(
                json.dumps({
                    "reason": "the application id should not empty",
                    'result': "failed!"
                }),
                content_type="application/json"
            )

        application_id = int(application_id)

        response_data = {}
        if current_user:
            application = get_object_or_404(Application, id=application_id)

            response_data['result'] = 'successful!'
            response_data['reason'] = get_voice_record_script(application)

        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'Voice id does not exist'

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "reason": "Method Request not supported.",
                'result': "Error Request."
            }),
            content_type="application/json"
        )


@csrf_protect
def update_app_selected_field(request):
    """
    """
    current_user = request.user
    print("current_user: ", current_user)

    if request.method == 'GET':

        app_id = int(request.GET.get('app_id'))
        # PIN TAB
        loan_purpose = decode_unquote_plus(request.GET.get('loan_purpose'))
        loan_purpose_desc = decode_unquote_plus(request.GET.get('loan_purpose_desc'))
        loan_purpose_description_expanded = decode_unquote_plus(request.GET.get(
            'loan_purpose_description_expanded'))

        # BIO TAB
        ktp = decode_unquote_plus(request.GET.get('ktp'))
        address_street_num = decode_unquote_plus(request.GET.get('address_street_num'))
        address_kecamatan = decode_unquote_plus(request.GET.get('address_kecamatan'))
        address_kelurahan = decode_unquote_plus(request.GET.get('address_kelurahan'))
        address_kabupaten = decode_unquote_plus(request.GET.get('address_kabupaten'))
        address_provinsi = decode_unquote_plus(request.GET.get('address_provinsi'))
        address_kodepos = decode_unquote_plus(request.GET.get('address_kodepos'))

        mobile_phone_1 = decode_unquote_plus(request.GET.get('mobile_phone_1'))
        has_whatsapp_1 = True if decode_unquote_plus(
            request.GET.get('has_whatsapp_1')) == "True" else False
        mobile_phone_2 = decode_unquote_plus(request.GET.get('mobile_phone_2'))
        has_whatsapp_2 = True if decode_unquote_plus(
            request.GET.get('has_whatsapp_2')) == "True" else False
        dialect = decode_unquote_plus(request.GET.get('dialect'))

        # KEL TAB
        spouse_name = decode_unquote_plus(request.GET.get('spouse_name'))
        spouse_dob = decode_unquote_plus(request.GET.get('spouse_dob'))
        marital_status = decode_unquote_plus(request.GET.get('marital_status'))
        dependent = decode_unquote_plus(request.GET.get('dependent'))

        spouse_mobile_phone = decode_unquote_plus(request.GET.get('spouse_mobile_phone'))
        spouse_has_whatsapp = True if decode_unquote_plus(
            request.GET.get('spouse_has_whatsapp')) == "True" else False
        kin_name = decode_unquote_plus(request.GET.get('kin_name'))
        kin_dob = decode_unquote_plus(request.GET.get('kin_dob'))
        kin_gender = decode_unquote_plus(request.GET.get('kin_gender'))
        kin_mobile_phone = decode_unquote_plus(request.GET.get('kin_mobile_phone'))
        kin_relationship = decode_unquote_plus(request.GET.get('kin_relationship'))
        close_kin_name = decode_unquote_plus(request.GET.get('close_kin_name'))
        close_kin_mobile_phone = decode_unquote_plus(request.GET.get('close_kin_mobile_phone'))
        close_kin_relationship = decode_unquote_plus(request.GET.get('close_kin_relationship'))

        # PEK TAB
        company_phone_number = decode_unquote_plus(request.GET.get('company_phone_number'))
        monthly_income = decode_unquote_plus(request.GET.get('monthly_income'))
        payday = decode_unquote_plus(request.GET.get('payday'))

        # KEU TAB
        other_income_amount = decode_unquote_plus(request.GET.get('other_income_amount'))
        monthly_housing_cost = decode_unquote_plus(request.GET.get('monthly_housing_cost'))
        monthly_expenses = decode_unquote_plus(request.GET.get('monthly_expenses'))
        total_current_debt = decode_unquote_plus(request.GET.get('total_current_debt'))
        vehicle_ownership_1 = decode_unquote_plus(request.GET.get('vehicle_ownership_1'))

        # notes
        notes = decode_unquote_plus(request.GET.get('notes'))

        app_obj = Application.objects.get_or_none(pk=app_id)
        user_id = request.user.id if request.user else None
        response_data = {}
        if app_obj and current_user:
            # set int date object
            try:
                print("kin_dob: %s" % kin_dob)
                if kin_dob:
                    kin_dob = datetime.datetime.strptime(
                        str(kin_dob), "%d-%m-%Y")
                else:
                    kin_dob = None

                print("spouse_dob: %s" % kin_dob)
                if spouse_dob:
                    spouse_dob = datetime.datetime.strptime(
                        str(spouse_dob), "%d-%m-%Y")
                else:
                    spouse_dob = None

                print("monthly_income:%s" % monthly_income)
                monthly_income = parse_number(monthly_income, locale='id_ID')

                print("other_income_amount: %s" % other_income_amount)
                other_income_amount = parse_number(other_income_amount, locale='id_ID')

                print("monthly_housing_cost: %s" % monthly_housing_cost)
                monthly_housing_cost = parse_number(monthly_housing_cost, locale='id_ID')

                print("monthly_expenses: %s" % monthly_expenses)
                monthly_expenses = parse_number(monthly_expenses, locale='id_ID')

                print("total_current_debt: %s" % total_current_debt)
                total_current_debt = parse_number(total_current_debt, locale='id_ID')

            except Exception as e:
                logger.info({
                    'status': 'ajax 1 - update_app_selected_field',
                    'exception': e,
                    'app.id': app_obj.id
                })
                print("error: ", e)
                response_data['result'] = 'failed!'
                response_data['reason'] = 'data not valid'
                return HttpResponse(
                    json.dumps(response_data),
                    content_type="application/json"
                )

            # update application
            try:
                print('loan_purpose : %s ' % loan_purpose)
                print('loan_purpose_desc : %s ' % loan_purpose_desc)
                print('loan_purpose_description_expanded : %s ' % loan_purpose_description_expanded)
                print('ktp : %s ' % ktp)
                print('address_street_num : %s ' % address_street_num)
                print('address_kecamatan : %s ' % address_kecamatan)
                print('address_kelurahan : %s ' % address_kelurahan)
                print('address_kabupaten : %s ' % address_kabupaten)
                print('address_provinsi : %s ' % address_provinsi)
                print('address_kodepos : %s ' % address_kodepos)
                print('mobile_phone_1 : %s ' % mobile_phone_1)
                print('has_whatsapp_1 : %s ' % has_whatsapp_1)
                print('mobile_phone_2 : %s ' % mobile_phone_2)
                print('has_whatsapp_2 : %s ' % has_whatsapp_2)
                print('dialect : %s ' % dialect)
                print('spouse_name : %s ' % spouse_name)
                print('spouse_dob : %s ' % spouse_dob)
                print('marital_status : %s ' % marital_status)
                print('dependent : %s ' % dependent)
                print('spouse_mobile_phone : %s ' % spouse_mobile_phone)
                print('spouse_has_whatsapp : %s ' % spouse_has_whatsapp)
                print('kin_name : %s ' % kin_name)
                print('kin_dob : %s ' % kin_dob)
                print('kin_gender : %s ' % kin_gender)
                print('kin_mobile_phone : %s ' % kin_mobile_phone)
                print('kin_relationship : %s ' % kin_relationship)
                print('close_kin_name : %s ' % close_kin_name)
                print('close_kin_mobile_phone : %s ' % close_kin_mobile_phone)
                print('close_kin_relationship : %s ' % close_kin_relationship)
                print('company_phone_number : %s ' % company_phone_number)
                print('monthly_income : %s ' % monthly_income)
                print('payday : %s ' % payday)
                print('other_income_amount : %s ' % other_income_amount)
                print('monthly_housing_cost : %s ' % monthly_housing_cost)
                print('monthly_expenses : %s ' % monthly_expenses)
                print('total_current_debt : %s ' % total_current_debt)
                print('vehicle_ownership_1 : %s ' % vehicle_ownership_1)

                Application.objects.filter(pk=app_id).update(
                    loan_purpose=loan_purpose,
                    loan_purpose_desc=loan_purpose_desc,
                    loan_purpose_description_expanded=loan_purpose_description_expanded,
                    ktp=ktp,
                    address_street_num=address_street_num,
                    address_kecamatan=address_kecamatan,
                    address_kelurahan=address_kelurahan,
                    address_kabupaten=address_kabupaten,
                    address_provinsi=address_provinsi,
                    address_kodepos=address_kodepos,
                    mobile_phone_1=mobile_phone_1,
                    has_whatsapp_1=has_whatsapp_1,
                    mobile_phone_2=mobile_phone_2,
                    has_whatsapp_2=has_whatsapp_2,
                    dialect=dialect,
                    spouse_name=spouse_name,
                    spouse_dob=spouse_dob,
                    marital_status=marital_status,
                    dependent=dependent,
                    spouse_mobile_phone=spouse_mobile_phone,
                    spouse_has_whatsapp=spouse_has_whatsapp,
                    kin_name=kin_name,
                    kin_dob=kin_dob,
                    kin_gender=kin_gender,
                    kin_mobile_phone=kin_mobile_phone,
                    kin_relationship=kin_relationship,
                    close_kin_name=close_kin_name,
                    close_kin_mobile_phone=close_kin_mobile_phone,
                    close_kin_relationship=close_kin_relationship,
                    company_phone_number=company_phone_number,
                    monthly_income=monthly_income,
                    payday=payday,
                    other_income_amount=other_income_amount,
                    monthly_housing_cost=monthly_housing_cost,
                    monthly_expenses=monthly_expenses,
                    total_current_debt=total_current_debt,
                    vehicle_ownership_1=vehicle_ownership_1)

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

            except Exception as e:
                msg_err = "error while updating application:", e
                print(msg_err)
                logger.info({
                    'status': 'ajax 2 - update_app_selected_field',
                    'exception': msg_err,
                    'app.id': app_obj.id
                })

                response_data['result'] = 'failed!'
                response_data['reason'] = 'updating process failed: ' + str(msg_err)
                return HttpResponse(
                    json.dumps(response_data),
                    content_type="application/json"
                )

            # simulate recalculation for first payment installment
            response_data['result'] = 'successful!'
            response_data['reason'] = "ALL Data Succesfully save"

        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'Application id does not exist'

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


# -----------------------------   AJAX   UPDATE APPLICATION  END  ------------
# ---------------------------------------Doku Disbursement ------------------
sentry_client = get_julo_sentry_client()


def ajax_check_doku_available(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application_id = int(data['application_id'])
    application = Application.objects.get(pk=application_id)
    customer = application.customer
    partner_referral = PartnerReferral.objects.filter(customer=customer, pre_exist=False).first()
    account_id = partner_referral.partner_account_id
    amount = application.loan.loan_disbursement_amount
    doku_client = get_doku_client()
    try:
        customer_partner = doku_client.get_customer_info(account_id)
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "failed get customer info",
        })

    if customer_partner['customer']['type'] == 'N':
        doku_limit = DokuAccountType.NORMAL
    elif customer_partner['customer']['type'] == 'P':
        doku_limit = DokuAccountType.PREMIUM

    try:
        response = doku_client.check_balance(account_id)
    except Exception:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "failed check doku customer balance",
        })
    current_balance = response['lastBalance']
    remaining_limit = doku_limit - current_balance

    if amount > remaining_limit:
        logger.info({
            'status': 'disbursement_failed_customer_limit',
            'customer_balance': response['lastBalance'],
            'account_type': response['type'],
            'account_id': account_id
        })
        return JsonResponse({
            "status": "failed",
            "messages": "customer limit is not enough",
        })

    try:
        julo_balance = doku_client.check_julo_balance()
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "failed check doku julo balance",
        })

    if julo_balance['lastBalance'] <= amount:
        logger.info({
            'status': 'disbursement_failed',
            'julo_balance': response['lastBalance'],
        })
        return JsonResponse({
            "status": "failed",
            "messages": "julo balance is not enough",
        })

    return JsonResponse({
        "status": "success",
        "messages": "balance and limit ok",
    })


def ajax_disbursement(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application_id = int(data['application_id'])
    application = Application.objects.get(pk=application_id)
    customer = application.customer
    partner_referral = PartnerReferral.objects.filter(customer=customer, pre_exist=False).first()
    account_id = partner_referral.partner_account_id
    amount = application.loan.loan_disbursement_amount
    transaction_id = generate_transaction_id(application.application_xid)
    cust_account_id = account_id
    str_amount = str(amount)
    doku_client = get_doku_client()
    # checking customer limit and julo balance
    try:
        customer_partner = doku_client.get_customer_info(account_id)
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "failed get customer info",
        })

    if customer_partner['customer']['type'] == 'N':
        doku_limit = DokuAccountType.NORMAL
    elif customer_partner['customer']['type'] == 'P':
        doku_limit = DokuAccountType.PREMIUM

    try:
        response = doku_client.check_balance(account_id)
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "failed check doku customer balance",
        })

    current_balance = response['lastBalance']
    remaining_limit = doku_limit - current_balance
    if amount > remaining_limit:
        return JsonResponse({
            "status": "failed",
            "messages": "customer limit is not enough",
        })

    try:
        julo_balance = doku_client.check_julo_balance()
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "failed check doku julo balance",
        })

    if julo_balance['lastBalance'] <= amount:
        return JsonResponse({
            "status": "failed",
            "messages": "julo balance is not enough",
        })
    # disbursement to doku
    user_id = request.user.id if request.user else None
    try:
        disburse = doku_client.disbursement(cust_account_id, transaction_id, str(amount))
        note = 'tracking_id : %s, transaction_id : %s, amount : %s' % (
            disburse['trackingId'], disburse['transactionId'], disburse['amount'])
        application_note = ApplicationNote.objects.create(
            note_text=note,
            application_id=application.id,
            added_by_id=user_id,
        )
        logger.info(
            {
                'status': 'save application note',
                'application_note': application_note,
                'application': application,
            }
        )

        loan = application.loan
        loan.loan_disbursement_method = 'doku disbursement'
        logger.info({
            'action': 'update_loan_disbursed_method',
            'loan_id': loan.id,
            'amount': amount
        })
        loan.save()
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "disbursement failed",
        })

    return JsonResponse({
        "status": "success",
        "messages": "disbursement success with transaction_id\
        %s amount %s" % (disburse['transactionId'], disburse['amount']),
    })


def ajax_check_ktp(request):
    # validate Ktp
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    customer_id = int(data['customer_id'])
    application_id = int(data['application_id'])
    ktp = str(data['ktp'])

    customer_app_count = (
        Application.objects.exclude(
            application_status_id__in=[
                ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
                ApplicationStatusCodes.OFFER_REGULAR,
                ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
                ApplicationStatusCodes.APPLICATION_DENIED,
                ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
                ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
                ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
            ]
        )
        .exclude(id=application_id)
        .filter(customer_id=customer_id)
        .count()
    )
    if customer_app_count > 0:
        return JsonResponse({
            "status": "failed",
            "messages": "Tidak bisa update NIK karena customer memiliki aplikasi yang sedang berjalan",
        })
    else:
        ktp_applications = Application.objects.exclude(customer_id=customer_id).filter(ktp=ktp)
        duplicate_data_info = "Duplikat KTP "
        if ktp_applications.count() > 0:
            duplicate_data_info += " in Application (AppId) : "
            for app in ktp_applications:
                duplicate_data_info += str(app.id) + ", "
            return JsonResponse({
                "status": "failed",
                "messages": duplicate_data_info,
            })
        else:
            # If applications don't have a duplicate ktp, double check in customers also
            ktp_customers = Customer.objects.exclude(id=customer_id).filter(nik=ktp)
            if ktp_customers.count() > 0:
                duplicate_data_info = " in Customers (CustomerId) : "
                for customer in ktp_customers:
                    duplicate_data_info += str(customer.id) + ", "
                return JsonResponse({
                    "status": "failed",
                    "messages": duplicate_data_info,
                })

    return JsonResponse({
        "status": "success",
        "messages": "no duplicate KTP"
    })


def ajax_update_application_checklist_collection(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application_id = int(data['application_id'])
    json_data = json.loads(data['data'])
    application = Application.objects.get(pk=application_id)

    try:
        update_application_checklist_collection(
            application, json_data)

    except GrabLogicException as e:
        return JsonResponse({
            "status": "failed",
            "messages": str(e),
        })

    except JuloException as exception_message:
        sentry_client.captureException()
        response_data = {
            "status": "failed",
            "messages": "failed update data application checklist",
        }
        if str(exception_message) == ApplicationStatusChange.DUPLICATE_PHONE:
            response_data.update({
                "status": "Update Aplikasi Gagal !",
                "messages": str(exception_message)})
        return JsonResponse(response_data)

    return JsonResponse({
        "status": "success",
        "messages": "success update data checklist collection"
    })


def ajax_calculate_suggested_offer(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    inputs = request.POST.dict()

    outputs = dict()
    outputs['calculation_inputs'] = inputs

    parsed_inputs = dict()
    number_fields = [
        'application_id',
        'monthly_housing_cost',
        'monthly_income',
        'monthly_expense',
        'undisclosed_expense',
        'product_line_code',
        'loan_amount_request',
        'loan_duration_request',
        'dependent_count',
        'payday'
    ]
    for field in number_fields:
        parsed_inputs[field] = 0 if inputs[field] == '' else int(inputs[field].replace('.', ''))

    application_id = parsed_inputs['application_id']
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        return JsonResponse({
            "status": "failed",
            "messages": "application_id=%s cannot be found" % application_id,
        })
    parsed_inputs['job_start_date'] = parse(inputs['job_start_date']).date()
    parsed_inputs['job_end_date'] = timezone.localtime(application.cdate).date()
    parsed_inputs['job_type'] = inputs['job_type']
    parsed_inputs['application_xid'] = application.application_xid

    data_consistent = ProductLineManager.is_data_consistent(
        parsed_inputs['product_line_code'],
        parsed_inputs['loan_amount_request'],
        parsed_inputs['loan_duration_request'])
    if not data_consistent:
        return JsonResponse({
            "status": "failed",
            "messages": "product line, amount, and duration are inconsistent",
        })

    try:
        parsed_inputs['monthly_income'] = get_monthly_income_by_experiment_group(
            application, parsed_inputs['monthly_income'])
        calculation_results = compute_affordable_payment(**parsed_inputs)
        outputs['calculation_results'] = calculation_results

        offer_recommendations_output = get_offer_recommendations(
            parsed_inputs['product_line_code'],
            parsed_inputs['loan_amount_request'],
            parsed_inputs['loan_duration_request'],
            calculation_results['affordable_payment'],
            parsed_inputs['payday'],
            application.ktp,
            application.id,
            application.partner
        )
        outputs.update(offer_recommendations_output)
        outputs.update({'kind_of_installment': application.determine_kind_of_installment})

        # from juloserver.julo.formulas.offers import get_offer_options
        # affordable_payment = calculation_results['affordable_payment']
        # offer_options = get_offer_options(
        #     product_line,
        #     data['loan_amount_request'],
        #     data['loan_duration_request'],
        #     product_lookup.monthly_interest_rate,
        #     affordable_payment)
        # data['requested_offer'] = {}
        # data['offer_options'] = offer_options
        #
        # # ca_calculation_data = get_ca_finance_calculation(application, data)
        # # affordable_payment = ca_calculation_data['affordable_payment']
        # data = get_suggested_offer(application, affordable_payment, data)
        # data['calculation_data'] = ca_calculation_data

    except Exception as e:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "failed calculate suggested offer",
            "error": str(e)
        })

    return JsonResponse({
        "status": "success",
        "data": outputs,
        "messages": "success calculate_suggested_offer"
    })


# -----------------------------  AJAX UPDATE COURTESY   ------------------------


def ajax_update_courtesy(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application_id = int(data['application_id'])
    application = Application.objects.get_or_none(id=application_id)

    if not application:
        return JsonResponse({
            "status": "failed",
            "messages": "application_id=%s cannot be found" % application_id,
        })

    try:

        application.is_courtesy_call = True
        logger.info({
            'application_id': application_id,
            'is_courtesy_call': application.is_courtesy_call,
        })
        application.save()
        delete_from_primo_courtesy_calls(application)
    except Exception as e:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "failed update courtesy",
            "error": str(e)
        })

    return JsonResponse({
        "status": "success",
        "messages": "success update courtesy"
    })


# -----------------------------  AJAX COURTESY EMAIL  --------------------------


def ajax_courtesy_email(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application_id = int(data['application_id'])
    application = Application.objects.get_or_none(id=application_id)

    if not application:
        return JsonResponse({
            "status": "failed",
            "messages": "application_id=%s cannot be found" % application_id,
        })

    # block notify to ICare
    if not application.customer.can_notify:
        return JsonResponse({
            "status": "failed",
            "messages": "Can not notify to this customer",
        })

    try:
        logger.info({
            'application': application,
            'event': 'send_email_courtesy'
        })
        send_email_courtesy(application)
    except EmailNotSent as ens:
        return JsonResponse({
            "status": "failed",
            "messages": str(ens)
        })
    try:
        application.is_courtesy_call = True
        logger.info({
            'application_id': application_id,
            'is_courtesy_call': application.is_courtesy_call,
        })
        application.save()
    except Exception as e:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "failed update courtesy",
            "error": str(e)
        })
    return JsonResponse({
        "status": "success",
        "messages": "send email courtesy"
    })


@csrf_protect
def trigger_autodial(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    agent = Agent.objects.get_or_none(user=request.user)
    if not agent:
        agent = Agent.objects.create(user=request.user)

    direct_number = request.GET.get('number_phone')
    skiptrace_id = request.GET.get('skiptrace_id')
    call_type = request.GET.get('call_type')
    name = request.GET.get('name', None)
    application_id = request.GET.get('application_id', None)
    direct_number = str(direct_number)
    if call_type == 'call':
        # call_customer(agent, direct_number, skiptrace_id)
        if application_id:
            application = Application.objects.get_or_none(pk=int(application_id))
            if application:
                if application.status in AUTODIAL_SIM_STATUSES:
                    # send to sim API
                    agent_username = agent.user.username
                    sim_client = get_julo_sim_client()
                    try:
                        call_response = sim_client.send_click2call_data(direct_number,
                                                                        name,
                                                                        agent_username,
                                                                        application.id)
                    except SimApiError as e:
                        return JsonResponse({
                            "status": "failed",
                            "message": str(e)
                        })

                    if call_response['response'] != 'Success':
                        return JsonResponse({
                            "status": "failed",
                            "message": "Failed to call %s , reason %s" % (
                                direct_number, call_response['reason'])
                        })
                    else:
                        return JsonResponse({
                            "status": "success",
                            "message": "Agent called at %s" % direct_number
                        })

                # for application not in sim statuses
                return JsonResponse({
                    "status": "success",
                    "message": "Agent called at %s" % direct_number
                })

            return JsonResponse({
                "status": "failed",
                "message": "Application %s not found" % application_id
            })

        else:
            return JsonResponse({
                "status": "success",
                "message": "Agent called at %s" % direct_number
            })

    else:
        # hangup_customer_call(agent, direct_number, skiptrace_id)
        return JsonResponse({
            "status": "success",
            "message": "Agent hangup at %s" % direct_number
        })


# -----------------------------  AJAX CUSTOM EMAIL  --------------------------


def ajax_custom_email(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application_id = int(data['application_id'])
    application = Application.objects.get_or_none(id=application_id)

    if not application:
        return JsonResponse({
            "status": "failed",
            "messages": "application_id=%s cannot be found" % application_id,
        })

    if not application.customer.can_notify:
        return JsonResponse({
            "status": "failed",
            "messages": "Can not notify to this customer"
        })

    email_content = data['content']
    email_sender = data['email_sender']
    email_receiver = data['email_receiver'].replace(" ", "")
    email_cc = data['email_cc'].replace(" ", "")
    subject = data['subject'] + ' - ' + application.email \
        if not data.get('exclude_app_email') else data['subject']

    if "," in email_receiver:
        list_email_receiver = email_receiver.split(",")
        for email in list_email_receiver:
            valid_email = check_email(email)
            if not valid_email:
                return JsonResponse({
                    "status": "failed",
                    "messages": "Invalid To Email Address = %s cannot be found" % email,
                })
    else:
        valid_email = check_email(email_receiver)
        if not valid_email:
            return JsonResponse({
                "status": "failed",
                "messages": "Invalid To Email Address = %s cannot be found" % email_receiver,
            })

    if email_cc:
        if "," in email_cc:
            list_email_cc = email_cc.split(",")
            for email in list_email_cc:
                valid_email = check_email(email)
                if not valid_email:
                    return JsonResponse({
                        "status": "failed",
                        "messages": "Invalid To Email Address = %s cannot be found" % email,
                    })
        else:
            valid_email = check_email(email_cc)
            if not valid_email:
                return JsonResponse({
                    "status": "failed",
                    "messages": "Invalid To Email Address = %s cannot be found" % email_cc,
                })

    try:
        logger.info({
            'application': application,
            'email_sender': email_sender,
            'email_receiver': email_receiver,
            'email_cc': email_cc,
            'subject': subject,
            'email_content': email_content,
        })
        send_email_application(
            application, email_sender, email_receiver, subject, email_content, email_cc)
    except EmailNotSent as ens:
        return JsonResponse({
            "status": "failed",
            "messages": str(ens)
        })

    return JsonResponse({
        "status": "success",
        "messages": "send custom email"
    })


# ----------------------------- SD SHEET  --------------------------------------


@julo_login_required
def sd_sheet(request):
    template_name = 'object/app_status/include/sheet.html'
    if request.method == 'POST':
        return HttpResponseNotAllowed(["POST"])
    else:
        return render(
            request,
            template_name,
        )


# -----------------------------AJAX for canned mail -----------------------------

@method_decorator(csrf_protect, name='dispatch')
class CannedResponseView(View):

    def post(self, request):
        data = request.POST.dict()
        try:
            CannedResponse.objects.create(
                name=data['name'],
                subject=data['subject'],
                content=data['content'])
        except Exception as e:
            return JsonResponse({
                "result": "failed",
                "message": "failed save response",
                "reason": str(e)
            })
        canned_responses = CannedResponse.objects.all()
        return JsonResponse({
            "result": "successful!",
            "message": "Template disimpan",
            "canned_responses": canned_filter(canned_responses, jsonify=False),
        })

    def put(self, request):
        data = QueryDict(request.body)
        try:
            CannedResponse.objects.filter(pk=data.get('pk')). \
                update(subject=data.get('subject'),
                       content=data.get('content'))
        except Exception as e:
            return JsonResponse({
                "result": "failed",
                "message": "failed update response",
                "reason": str(e)
            })
        canned_responses = CannedResponse.objects.all()
        return JsonResponse({
            "result": "successful!",
            "message": "Template diupdate",
            "canned_responses": canned_filter(canned_responses, jsonify=False),
        })

    def delete(self, request):
        data = QueryDict(request.body)
        try:
            CannedResponse.objects.get(pk=data.get('pk')).delete()
        except Exception as e:
            return JsonResponse({
                "result": "failed",
                "message": "failed delete response",
                "reason": str(e)
            })
        canned_responses = CannedResponse.objects.all()
        return JsonResponse({
            "result": "successful!",
            "message": "Template dihapus",
            "canned_responses": canned_filter(canned_responses, jsonify=False),
        })


# --------------------- AJAX for Redeem Cashback ----------------------------


@csrf_protect
def process_cashback_transfer_request(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    cashback_transfer_transaction_id = request.GET.get('cashback_transfer_transaction_id')
    status = request.GET.get('status')
    note_text_custom = request.GET.get('note_text')
    valid_status = [CashbackTransferConst.STATUS_APPROVED,
                    CashbackTransferConst.STATUS_REJECTED]

    if status not in valid_status:
        return JsonResponse({
            "result": "failed",
            "message": "invalid status",
            "reason": "invalid status"
        })
    cb_redemption_service = get_cashback_redemption_service()
    with transaction.atomic():
        cashback_transfer = \
            CashbackTransferTransaction.objects.select_for_update(nowait=True).filter(
                id=cashback_transfer_transaction_id
            ).exclude(transfer_status__in=valid_status).last()

        if not cashback_transfer:
            return JsonResponse({
                "result": "failed",
                "message": "not found cashback transfer request",
                "reason": "invalid cashback transfer transaction Id"
            })
        if status == CashbackTransferConst.STATUS_APPROVED:
            try:
                if 'bca' in cashback_transfer.bank_name.lower():
                    cashback_transfer.partner_transfer = CashbackTransferConst.METHOD_BCA
                else:
                    cashback_transfer.partner_transfer = CashbackTransferConst.METHOD_XFERS
                cashback_transfer.transfer_status = status
                cashback_transfer.save()
                cb_redemption_service.transfer_cashback(cashback_transfer)

            except Exception as e:
                return JsonResponse({
                    "result": "failed",
                    "message": "failed transfer cashback",
                    "reason": str(e)
                })
        if status == CashbackTransferConst.STATUS_REJECTED:
            try:
                cb_redemption_service.action_cashback_transfer_finish(cashback_transfer, False)

            except Exception as e:
                return JsonResponse({
                    "result": "failed",
                    "message": "failed reject cashback request",
                    "reason": str(e)
                })
        last_wallet = cashback_transfer.customerwallethistory_set.order_by('-cdate').first()
        if note_text_custom:
            CustomerWalletNote.objects.create(customer=cashback_transfer.customer,
                                              customer_wallet_history=last_wallet,
                                              note_text=note_text_custom)

        return JsonResponse({
            "result": "successful!",
            "message": "Process %s Transfer Cashback" % (status.lower()),
        })


@csrf_exempt
def ajax_update_offer(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()
    application_id = int(data['application_id'])
    application = Application.objects.get(pk=application_id)
    try:
        update_offer(application, data['offers'])
    except JuloException:
        sentry_client.captureException()
        return JsonResponse({
            "status": "failed",
            "messages": "failed save offer",
        })
    return JsonResponse({
        "status": "success",
        "messages": "success save offer"
    })


def ajax_update_application_bank(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()
    if not data['application_id']:
        return JsonResponse({
            "status": "failed",
            "messages": "application_id could not be empty!!"
        })

    application_id = int(data['application_id'])
    application_field = data['application_field']
    new_value = data['value']
    user_id = request.user.id if request.user else None
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        old_value = getattr(application, application_field)
        if old_value == new_value:
            return JsonResponse({
                "status": "failed",
                "messages": "no data changes"
            })

        setattr(application, application_field, new_value)
        application.save()
        note = 'change %s from %s to %s' % (application_field, old_value, new_value)
        ApplicationNote.objects.create(
            application_id=application.id,
            note_text=note,
            added_by_id=user_id,
        )
        ApplicationFieldChange.objects.create(
            application=application,
            field_name=application_field,
            old_value=old_value,
            new_value=new_value,
        )

    return JsonResponse({
        "status": "success",
        "messages": "success update %s" % application_field
    })


def ajax_update_name_bank_validation(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()
    name_bank_validation_id = int(data['name_bank_validation_id'])
    field = data['field']
    application_field = data['application_field']
    value = data['value']
    new_value = value
    application_id = int(data['application_id'])
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        return JsonResponse({
            "status": "failed",
            "messages": "application not found"
        })

    is_julo_one_or_is_julo_one_ios = application.is_julo_one() or application.is_julo_one_ios()
    if not is_julo_one_or_is_julo_one_ios:
        loan = Loan.objects.filter(name_bank_validation_id=name_bank_validation_id).last()
        if not loan:
            return JsonResponse({
                "status": "failed",
                "messages": "loan not found"
            })

    validation = get_name_bank_validation_process_by_id(name_bank_validation_id)
    user_id = request.user.id if request.user else None
    if field == 'method':
        old_value = validation.get_method()
        if old_value == new_value:
            return JsonResponse({
                "status": "failed",
                "messages": "no data changes"
            })

        validation.change_method(new_value)
        note = 'change name bank validation method from %s to %s' % (old_value, new_value)
        ApplicationNote.objects.create(
            application_id=application.id, note_text=note, added_by_id=user_id
        )

    else:
        with transaction.atomic():
            application = Application.objects.select_for_update().get(pk=application_id)
            if field == 'bank_code':
                bank_entry = BankManager.get_by_name_or_none(value)
                if not bank_entry:
                    return JsonResponse({
                        "status": "failed",
                        "messages": "bank %s not in the bank list" % value
                    })

                method = validation.get_method()
                bank_code = getattr(bank_entry, '{}_bank_code'.format(method.lower()))
                value = bank_code

            old_value = getattr(application, application_field)
            if old_value == new_value:
                return JsonResponse({
                    "status": "failed",
                    "messages": "no data changes"
                })

            setattr(application, application_field, new_value)
            application.save()
            note = 'change %s from %s to %s' % (application_field, old_value, new_value)
            ApplicationNote.objects.create(
                application_id=application.id, note_text=note, added_by_id=user_id
            )
            ApplicationFieldChange.objects.create(
                application=application,
                field_name=application_field,
                old_value=old_value,
                new_value=new_value,
            )
            validation.update_fields([field], [value])

    return JsonResponse({
        "status": "success",
        "messages": "success update %s" % field
    })


def ajax_bank_validation(request):
    data = None
    if request.method == 'GET':
        app_id = int(request.GET.get('app_id'))
    elif request.method == 'POST':
        data = request.POST.dict()
        app_id = data['app_id']
    else:
        return HttpResponseNotAllowed(["POST", "GET"])
    app = Application.objects.get_or_none(id=app_id)

    if not app:
        return JsonResponse({
            "status": "failed",
            "messages": "application not found"
        })
    workflow_action = WorkflowAction(
        app, app.application_status, '', '', app.application_status
    )
    validate_status = 'success'
    if not data:
        message = "get name bank validation success"
    else:
        account_number = data['bank_account_number']
        if not account_number.isnumeric():
            return JsonResponse({
                'status': 'failed',
                'messages': "Bank account number should contain only numbers"})
        message = "submit validation success"
        if not data['name_bank_validation_id'] and not app.is_jstarter:
            return JsonResponse({
                "status": "failed",
                "messages": "name_bank_validation_id is None"
            })

        try:
            name_bank_validation_id = int(data['name_bank_validation_id'])
        except (TypeError, ValueError) as e:
            if app.is_jstarter:
                name_bank_validation = workflow_action.process_validate_bank(force_validate=True)
                name_bank_validation_id = name_bank_validation.id
            else:
                raise e

        validation = get_name_bank_validation_process_by_id(name_bank_validation_id)
        if data['bank_name']:
            bank_entry = BankManager.get_by_name_or_none(data['bank_name'])
            if not bank_entry:
                return JsonResponse({
                    "status": "failed",
                    "messages": "bank %s not in the bank list" % data['bank_name']
                })
        user_id = request.user.id if request.user else None
        with transaction.atomic():
            if data['validation_method']:
                new_method = data['validation_method']
                old_method = validation.get_method()
                if new_method != old_method:
                    validation.change_method(new_method)
                    note = 'change name bank validation method from %s to %s' % (
                        old_method,
                        new_method,
                    )
                    ApplicationNote.objects.create(
                        application_id=app.id, note_text=note, added_by_id=user_id
                    )

            for field in ['bank_name', 'bank_account_number', 'name_in_bank']:
                new_value = data[field]
                old_value = getattr(app, field)
                if new_value != old_value:
                    app.update_safely(**{field: new_value})
                    note = 'change %s from %s to %s' % (field, old_value, new_value)
                    ApplicationNote.objects.create(
                        application_id=app.id, note_text=note, added_by_id=user_id
                    )
                    ApplicationFieldChange.objects.create(
                        application=app,
                        field_name=field,
                        old_value=old_value,
                        new_value=new_value,
                    )

                    if field == 'bank_account_number':
                        send_customer_data_change_by_agent_notification_task.delay(
                            customer_id=app.customer.id,
                            field_changed=AgentDataChange.Field.BankAccountNumber,
                            previous_value=old_value,
                            new_value=new_value,
                        )

        try:
            if (
                app.is_julo_one() or app.is_julo_one_ios() or app.is_grab()
            ) and app.status == ApplicationStatusCodes.LOC_APPROVED:
                from juloserver.grab.services.services import (
                    process_grab_bank_validation_v2,
                )
                if not app.is_grab():
                    workflow_action.process_validate_bank(force_validate=True, new_data=data)
                else:
                    process_grab_bank_validation_v2(
                        workflow_action.application.id, force_validate=True, new_data=data)
                app.refresh_from_db()
                if app.name_bank_validation.validation_status == NameBankValidationStatus.SUCCESS:
                    app.update_safely(
                        bank_name=data['bank_name'],
                        bank_account_number=data['bank_account_number'],
                        name_in_bank=data['name_in_bank'],
                    )
                    category = BankAccountCategory.objects.get(
                        category=BankAccountCategoryConst.SELF)
                    bank = Bank.objects.get(bank_name__iexact=data["bank_name"])
                    bank_account_destination = BankAccountDestination.objects.create(
                        bank_account_category=category,
                        customer=app.customer,
                        bank=bank,
                        account_number=data["bank_account_number"],
                        name_bank_validation=app.name_bank_validation
                    )
                    if app.is_grab():
                        trigger_create_or_update_ayoconnect_beneficiary.delay(app.customer.id)
                        inactive_loans = app.account.loan_set.filter(loan_status_id__in={
                            LoanStatusCodes.INACTIVE})
                        if inactive_loans.exists():
                            for inactive_loan in inactive_loans:
                                inactive_loan.update_safely(
                                    bank_account_destination=bank_account_destination
                                )
            elif app.is_julover() and \
                    app.status == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                julover_workflow_action = JuloverWorkflowAction(
                    app, app.application_status, '', '', app.application_status
                )
                julover_workflow_action.process_bank_validation()
            else:
                # For Partnership Product
                if app.is_partnership_app() or app.is_partnership_leadgen():
                    partnership_flow_flag = (
                        PartnershipFlowFlag.objects.filter(
                            partner_id=app.partner.id,
                            name=PartnershipFlag.PAYMENT_GATEWAY_SERVICE,
                        )
                        .values_list('configs', flat=True)
                        .last()
                    )
                    if partnership_flow_flag and partnership_flow_flag.get(
                        'payment_gateway_service', True
                    ):
                        partnership_trigger_process_validate_bank(app.id)
                    else:
                        process_validate_bank_task(app.id)
                else:
                    if not app.is_grab():
                        # J1
                        workflow_action.trigger_pg_validate_bank()
                    else:
                        # Grab
                        workflow_action.process_validate_bank(force_validate=True)
        except (InvalidBankAccount, DisbursementServiceError) as e:
            if type(e) == DisbursementServiceError:
                validate_status = 'failed'
                message = 'There are some steps are failed before go to the bank name ' \
                          'validation progress, reason: %s' % str(e)
            logger.exception('validate bank failed, data=%s | err=%s' % (data, e))

    app.refresh_from_db()
    if (
        app.is_julo_one()
        or app.is_julo_one_ios()
        or app.is_grab()
        or app.is_julover()
        or app.is_julo_starter()
    ):
        name_bank_validation_id = app.name_bank_validation_id
    else:
        name_bank_validation_id = app.loan.name_bank_validation_id
    bank_validation_info = get_name_bank_validation(name_bank_validation_id)
    partner_name = app.partner.name if app.partner else None

    response_data = {
        'bank_name': app.bank_name,
        'bank_account_number': app.bank_account_number,
        'name_in_bank': app.name_in_bank,
        'method': bank_validation_info['method'],
        'list_method': get_list_validation_method(),
        'validated_name': bank_validation_info['validated_name'],
        'validation_id': bank_validation_info['validation_id'],
        'validation_status': bank_validation_info['validation_status'],
        'reason': bank_validation_info['reason'],
        'partner': partner_name
    }

    return JsonResponse({
        "status": validate_status,
        "messages": message,
        "data": response_data
    })


def ajax_bank_validation_grab(request):
    if request.method == 'POST':
        data = request.POST.dict()
        bank_name = data['bank_name']
        account_number = data['bank_account_number']
        application_id = data['app_id']
    else:
        return HttpResponseNotAllowed(["POST"])
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        return JsonResponse({
            "status": "failed",
            "messages": "application not found"
        })
    if not account_number:
        return JsonResponse({
            "status": "failed",
            "messages": "account number cannot be empty"
        })
    try:
        return_value = {'bank_name_validation': True}
        GrabCommonService().get_bank_check_data(
            application.customer, bank_name, account_number.strip(), application_id)
    except GrabLogicException as e:
        return_value = {'bank_name_validation': False,
                        'errors': str(e)}
    except GrabApiException as e:
        return_value = {'bank_name_validation': False,
                        'errors': str(e)}
    update_loan_status_for_grab_invalid_bank_account(application.id)
    return JsonResponse({
        "status": "success",
        "data": return_value
    })


def ajax_change_disbursement_method(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()
    disbursement_id = int(data['disbursement_id'])
    new_value = data['method']
    user_id = request.user.id if request.user else None
    loan = Loan.objects.filter(disbursement_id=disbursement_id).last()
    if not loan:
        return JsonResponse({
            "status": "failed",
            "messages": "loan not found"
        })

    disbursement = get_disbursement_process_by_id(disbursement_id)
    old_value = disbursement.get_method()
    if old_value == new_value:
        return JsonResponse({
            "status": "failed",
            "messages": "no data changes"
        })

    with transaction.atomic():
        disbursement.change_method(new_value)
        application = loan.application
        note = 'change disbursement method from %s to %s' % (old_value, new_value)
        ApplicationNote.objects.create(
            application_id=application.id,
            note_text=note,
            added_by_id=user_id,
        )

    return JsonResponse({
        "status": "success",
        "messages": "success change disbursement method to %s" % new_value
    })


@julo_login_required
@julo_login_required_group('product_manager')
def mass_move_apps(request):
    template_name = 'object/app_status/mass_move_apps.html'
    error_message = ""
    data = MassMoveApplicationsHistory.objects.all().order_by('-id')

    if request.method == 'POST':
        if not request.FILES.get('csv_file'):
            error_message = "Error!!!, file belum dipilih"
        else:
            file = request.FILES['csv_file']
            file_exist = MassMoveApplicationsHistory.objects.get_or_none(filename=file.name)

            if file_exist:
                error_message = "Error!!!, file pernah diupload sebelumnya"
            elif file.content_type not in ("application/csv", "application/x-csv", "text/csv",
                                           "text/comma-separated-values",
                                           "text/x-comma-separated-values",
                                           "text/tab-separated-values", "application/vnd.ms-excel"):
                error_message = "Error!!!, file type harus CSV"
            else:
                column = ["application_id", "current_status", "new_status", "notes"]

                # determine delimiter
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

                if headers == column:
                    mass_move_task = MassMoveApplicationsHistory.objects.create(filename=file.name)
                    mass_move_task.status = "started"
                    mass_move_task.save()
                    process_applications_mass_move.delay(list(rows), file.name)
                    return render(request, template_name, {
                        "data": data,
                        "message": "mass move in progress, harap tunggu beberapa saat dan refresh untuk melihat hasil"
                    })
                else:
                    error_message = "Error!!!, format CSV tidak sesuai dengan template"
    elif request.method == 'GET':
        pass
    return render(request, template_name, {"data": data, "message": error_message})


def ajax_update_cashback(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()

    cashback_transfer_id = int(data['cashback_transfer_id'])
    redeem_amount = int(data['redeem_amount'])
    # transfer_amount = int(data['transfer_amount'])
    partner_transfer = data['partner_transfer']
    bank_name = data['bank_name']
    name_in_bank = data['name_in_bank']
    bank_number = data['bank_number']

    cashback_transfer = CashbackTransferTransaction.objects.get(id=cashback_transfer_id)

    if cashback_transfer.transfer_status in CashbackTransferConst.FINAL_STATUSES:
        return JsonResponse({
            "status": "failed",
            "messages": "could not updated if cashback is completed/rejected"
        })
    cashback_service = CashbackRedemptionService()
    forbidden_statuses = CashbackTransferConst.FORBIDDEN_STATUSES

    with transaction.atomic():
        updated_fields = []
        updated_values = []
        if redeem_amount != cashback_transfer.redeem_amount:
            customer = cashback_transfer.customer
            if cashback_transfer.transfer_status in forbidden_statuses:
                return JsonResponse({
                    "status": "failed",
                    "messages": "could not change amount if cashback is already processed"
                })
            # process fix customer wallet
            reducing_adjustment = cashback_transfer.redeem_amount - redeem_amount
            cashback_service.process_transfer_addition_wallet_customer(cashback_transfer.customer,
                                                                       cashback_transfer)
            # adjust cashback
            customer.change_wallet_balance(
                change_accruing=-reducing_adjustment,
                change_available=-reducing_adjustment,
                reason=CashbackChangeReason.AGENT_FINANCE_ADJUSTMENT,
                cashback_transfer_transaction=cashback_transfer)

            # reduce cashback to transfer
            customer.change_wallet_balance(
                change_accruing=-redeem_amount,
                change_available=-redeem_amount,
                reason=CashbackChangeReason.USED_TRANSFER,
                cashback_transfer_transaction=cashback_transfer)

            if redeem_amount < CashbackTransferConst.ADMIN_FEE:
                transfer_amount = 0
            else:
                transfer_amount = redeem_amount - CashbackTransferConst.ADMIN_FEE

            cashback_transfer.redeem_amount = redeem_amount
            cashback_transfer.transfer_amount = transfer_amount
            cashback_transfer.save()

            if cashback_transfer.transfer_id:
                disbursement = get_disbursement_process_by_id(cashback_transfer.transfer_id)
                disbursement.update_fields(['amount'], [transfer_amount])

        if bank_name != cashback_transfer.bank_name:
            bank = BankManager.get_by_name_or_none(bank_name)
            if not bank:
                return JsonResponse({
                    "status": "failed",
                    "messages": "bank %s not in the bank list" % bank_name
                })
            cashback_transfer.bank_name = bank_name
            cashback_transfer.bank_code = bank.bank_code
            updated_fields.append('bank_code')
            updated_values.append(bank.xfers_bank_code)

        if name_in_bank != cashback_transfer.name_in_bank:
            cashback_transfer.name_in_bank = name_in_bank
            updated_fields.append('name_in_bank')
            updated_values.append(name_in_bank)

        if bank_number != cashback_transfer.bank_number:
            cashback_transfer.bank_number = bank_number
            updated_fields.append('account_number')
            updated_values.append(bank_number)

        if partner_transfer != cashback_transfer.partner_transfer:
            if cashback_transfer.transfer_status in forbidden_statuses:
                return JsonResponse({
                    "status": "failed",
                    "messages": "could not change partner transfer if cashback is already processed"
                })
            cashback_transfer.partner_transfer = partner_transfer
            if cashback_transfer.transfer_id:
                disbursement = get_disbursement_process_by_id(cashback_transfer.transfer_id)
                disbursement.change_method(partner_transfer)

        cashback_transfer.save()
        # porcess update name_bank_validation
        if cashback_transfer.validation_id:
            validation = get_name_bank_validation_process_by_id(cashback_transfer.validation_id)
            validation_updated = 'name_in_bank' in updated_fields or 'bank_code' in updated_fields \
                                 or 'account_number' in updated_fields
            if validation_updated and validation.is_success():
                cashback_transfer.validation_id = None
                cashback_transfer.validation_status = None
                cashback_transfer.save()
            else:
                validation.update_fields(updated_fields, updated_values)

    cashback_transfer.refresh_from_db()
    # auto reject if adjusted redeem amount less than min transfer amount
    if cashback_transfer.redeem_amount < CashbackTransferConst.MIN_TRANSFER:
        cashback_service.action_cashback_transfer_finish(cashback_transfer, False)

    return JsonResponse({
        "status": "success",
        "messages": "success update data cashback"
    })


def ajax_retry_cashback_transfer(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()
    cashback_transfer_id = int(data['cashback_transfer_id'])
    cashback_transfer = CashbackTransferTransaction.objects.get_or_none(id=cashback_transfer_id)
    if not cashback_transfer:
        return JsonResponse({
            "status": "failed",
            "messages": "cashback ransfer not found!!"
        })
    try:
        cb_redemption_service = CashbackRedemptionService()
        cb_redemption_service.retry_cashback_transfer(cashback_transfer)
    except Exception as e:
        return JsonResponse({
            "result": "failed",
            "message": "failed transfer cashback",
            "reason": str(e)
        })

    return JsonResponse({
        "result": "success",
        "message": "success retry transfer cashback",
        "reason": "success"
    })


@julo_login_required
@julo_login_required_multigroup(['bo_finance'])
class DisbursementSummaryView(ListView):
    model = DisbursementSummary
    paginate_by = 50  # get_conf("PAGINATION_ROW")
    template_name = 'object/app_status/list_disbursement.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super(DisbursementSummaryView, self).get_queryset(
        ).select_related('disbursement', 'partner', 'product_line')

        self.qs = self.qs.order_by('-transaction_date', 'id')
        self.err_message_here = None

        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(DisbursementSummaryView, self).get_context_data(**kwargs)
        context['balance_list'] = dict(
            # Xendit=get_julo_balance('Xendit'),
            Xfers=get_julo_balance('Xfers'),
            Bca=get_julo_balance('Bca'),
            # Instamoney=get_julo_balance('Instamoney')
        )

        context['results_per_page'] = self.paginate_by
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters

        return context

    def get(self, request, *args, **kwargs):
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        render_ = super(DisbursementSummaryView, self).render_to_response(context,
                                                                          **response_kwargs)
        return render_


def ajax_disburse_summary(request):
    current_user = request.user
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    summary_id = data.get('summary_id')
    method = data.get('method')
    user = current_user
    bulk_disbursement = process_bulk_disbursement(summary_id, method, user)

    if bulk_disbursement:
        return JsonResponse(bulk_disbursement)

    return JsonResponse({
        "status": "failed",
        "message": "failed disbursement",
        "reason": "error server"
    })


class NexmoCallTesting(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        make_nexmo_test_call.apply_async()
        return Response(status=status.HTTP_200_OK, data={'success': 'call started'})


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_full', 'cs_team_leader'])
@csrf_protect
def ajax_change_email(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application_id = int(data['application_id'])
    new_email = data['new_email'].strip().lower()
    app = Application.objects.get_or_none(id=application_id)
    if not app:
        return JsonResponse({
            "status": "failed",
            "message": "Application not exists"
        })
    previous_email = app.email
    customer = Customer.objects.get_or_none(email=new_email)
    if customer:
        return JsonResponse({
            "status": "failed",
            "message": "Customer with email already exists."
        })
    try:
        with transaction.atomic():
            CustomerFieldChange.objects.create(customer=app.customer,
                                               field_name='email',
                                               old_value=app.email,
                                               new_value=new_email,
                                               changed_by=request.user,
                                               application=app)
            ApplicationFieldChange.objects.create(field_name='email',
                                                  old_value=app.email,
                                                  new_value=new_email,
                                                  agent=request.user,
                                                  application=app)
            Application.objects.filter(pk=application_id).update(email=new_email)
            Customer.objects.get(pk=app.customer.id).update_safely(email=new_email)
    except Exception as e:
        return JsonResponse({
            "status": "failed",
            "message": "Failed email update",
            "reason": str(e)
        })

    send_customer_data_change_by_agent_notification_task.delay(
        customer_id=app.customer.id,
        field_changed=AgentDataChange.Field.Email,
        previous_value=previous_email,
        new_value=new_email,
        recipient_email=previous_email,
    )

    return JsonResponse({
        "status": "success",
        "message": "Email updated successfully"
    })


@julo_login_required
@julo_login_required_multigroup(
    ['admin_full', 'bo_full', 'bo_data_verifier', 'cs_team_leader', 'ops_supervisor',
     'ops_team_leader', 'bo_general_cs', 'fraudcolls', 'fraudops'])
@csrf_protect
def ajax_send_reset_pin_email(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application_id = int(data['application_id'])
    app = Application.objects.get_or_none(id=application_id)

    if not app:
        return JsonResponse({
            "status": "failed",
            "message": "Application not exists"
        })

    to_email = data['to_email'] if 'to_email' in data else app.email
    customer = pin_services.get_customer_by_email(app.email)
    if not customer or not pin_services.does_user_have_pin(customer.user):
        if not customer:
            msg = 'Email not exists'
        else:
            msg = 'Customer has not set pin earlier'
        return JsonResponse({
            "status": "failed",
            "message": msg
        })

    pin_services.process_reset_pin_request(customer, to_email)
    return JsonResponse({
        "status": "success",
        "message": "success update email"
    })


# ----------------------------- Customer Service Detail START  ---------------------------------------


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def customer_service_detail(request, pk):
    # check if there is application found (if not then display 404)
    app_obj = get_object_or_404(Application, id=pk)
    status_current = app_obj.application_status

    template_name = 'object/app_status/customer_service_detail.html'
    message_out_ubah_status = None
    message_out_simpan_note = None
    message_out_security_note = None
    ubah_status_active = 0
    simpan_note_active = 0
    security_note_active = 0
    julo_product_line_code = (ProductLineCodes.STL1, ProductLineCodes.STL2,
                              ProductLineCodes.MTL1, ProductLineCodes.MTL2, ProductLineCodes.BRI1,
                              ProductLineCodes.BRI2,
                              ProductLineCodes.GRAB1, ProductLineCodes.GRAB2,
                              ProductLineCodes.GRABF1, ProductLineCodes.GRABF2,
                              ProductLineCodes.PEDEMTL1, ProductLineCodes.PEDEMTL2,
                              ProductLineCodes.PEDESTL1, ProductLineCodes.PEDESTL2,
                              ProductLineCodes.GRAB)
    # message_out_update_app = None
    # update_app_active = 0

    if request.method == 'POST':
        request.session['security_note_active'] = ''
        form = StatusChangesForm(status_current, app_obj.id, request.POST)
        # re-configure request.POST for loan
        form_app = ApplicationForm(
            request.POST, instance=app_obj, prefix='form2')
        form_app_select = ApplicationSelectFieldForm(
            app_obj, request.POST, prefix='form2')
        form_security = SecurityForm(request.POST)
        if form.is_valid():
            if 'ubah_status' in request.POST:
                print("ubah_status-> valid here")

            status_to = form.cleaned_data['status_to']
            reason = form.cleaned_data['reason_str']
            notes = form.cleaned_data['notes']

            logger.info({
                'status_to': status_to,
                'reason': reason,
                'notes': notes
            })

            try:
                with transaction.atomic():
                    process_application_status_change(
                        app_obj.id, int(status_to), reason, note=notes)

                # remarked , there is no unlock after change status
                # if status_current.status_code in LOCK_STATUS_LIST:
                #     ret_unlocked = unlocked_app_from_user(app_obj, request.user, status_to)
                #     print "ret_unlocked: ", ret_unlocked
                # else:
                #     print "status code %s not in LOCK_STATUS_LIST" % (status_current)

                url = reverse('app_status:change_status', kwargs={'pk': app_obj.id})
                return redirect(url)

            except Exception as e:
                err_msg = """
                            Ada Kesalahan di Backend Server!!!, Harap hubungi Administrator : %s
                            """
                sentry_client.captureException()
                traceback.print_exc()
                # there is an error
                err_msg = err_msg % (e)
                logger.info({
                    'app_id': app_obj.id,
                    'error': "Ada Kesalahan di Backend Server with \
                    process_application_status_change !!!."
                })
                # messages.error(request, err_msg)
                message_out_ubah_status = err_msg
                ubah_status_active = 1

        else:
            if 'notes_only' in request.POST:
                try:
                    notes = form.cleaned_data['notes_only']
                    print("simpan_note-> notes: ", notes)

                    if notes:
                        user_id = request.user.id if request.user else None
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

                        url = reverse('app_status:change_status', kwargs={'pk': app_obj.id})
                        return redirect(url)
                    else:
                        err_msg = """
                            Note/Catatan Tidak Boleh Kosong !!!
                        """
                        # messages.error(request, err_msg)
                        message_out_simpan_note = err_msg
                        simpan_note_active = 1

                except Exception as e:
                    err_msg = """
                        Catatan Tidak Boleh Kosong !!!
                    """
                    # messages.error(request, err_msg)
                    message_out_simpan_note = err_msg
                    simpan_note_active = 1
            elif 'security_note' in request.POST:
                try:
                    security_note = request.POST['security_note']

                    if security_note:
                        SecurityNote.objects.create(
                            note_text=security_note,
                            customer=app_obj.customer,
                            added_by=request.user)
                        logger.info({
                            'security_note': security_note,
                        })

                        request.session['security_note_active'] = 1
                        url = reverse('app_status:change_status',
                                      kwargs={'pk': app_obj.id})
                        return redirect(url)
                    else:
                        err_msg = """
                            Note/Catatan Tidak Boleh Kosong !!!
                        """
                        message_out_security_note = err_msg

                except Exception as e:
                    err_msg = """
                        Catatan Tidak Boleh Kosong !!!
                    """
                    message_out_security_note = err_msg
            else:
                # form is not valid
                err_msg = """
                    Ubah Status atau Alasan harus dipilih dahulu !!!
                """
                # messages.error(request, err_msg)
                message_out_ubah_status = err_msg
                ubah_status_active = 1

    else:
        form = StatusChangesForm(status_current, app_obj.id)
        form_app = ApplicationForm(
            instance=app_obj, prefix='form2')
        form_app_select = ApplicationSelectFieldForm(app_obj, prefix='form2')
        form_security = SecurityForm()
        if request.session.get('security_note_active'):
            security_note_active = request.session.get('security_note_active')
            request.session['security_note_active'] = ''
        else:
            security_note_active = 0
            request.session['security_note_active'] = ''

    image_list = Image.objects.filter(
        image_source=app_obj.id,
        image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
    )
    results_json = ExtJsonSerializer().serialize(
        image_list,
        props=['image_url', 'image_ext'],
        fields=('image_type',)
    )

    image_list_1 = Image.objects.filter(image_source=app_obj.id, image_status=Image.DELETED)
    results_json_1 = ExtJsonSerializer().serialize(
        image_list_1,
        props=['image_url', 'image_ext'],
        fields=('image_type',)
    )
    voice_list = VoiceRecord.objects.filter(
        application=app_obj.id,
        status__in=[VoiceRecord.CURRENT, VoiceRecord.RESUBMISSION_REQ]
    )
    results_json_2 = ExtJsonSerializer().serialize(
        voice_list,
        props=['presigned_url'],
        fields=('status')
    )

    voice_list_1 = VoiceRecord.objects.filter(
        application=app_obj.id,
        status=VoiceRecord.DELETED
    )
    results_json_3 = ExtJsonSerializer().serialize(
        voice_list_1,
        props=['presigned_url'],
        fields=('status')
    )

    history_note_list = get_list_history(app_obj)
    email_sms_list = get_list_email_history(app_obj)
    app_detail_history_list = get_app_detail_list_history(app_obj)
    customer = app_obj.customer
    security_note_list = SecurityNote.objects.filter(customer=customer).order_by('-cdate')
    skiptrace_list = Skiptrace.objects.filter(customer=customer).order_by('id')
    app_list = Application.objects.filter(customer_id=customer).order_by('-cdate')
    note_app = []

    for obj in app_list:
        note_app.append(ApplicationNote.objects.filter(application_id=obj.id).last())
        account_payment_objects = AccountPayment.objects.filter(account_id=obj.account_id).order_by(
            'due_date')

    if app_list:
        if app_list[0].account_id:
            account_id = app_list[0].account_id
            account_objects = Account.objects.get(id=account_id)
        else:
            account_objects = None

    history_note_app = zip(app_list, note_app)
    skiptrace_history_list = SkiptraceHistory.objects.filter(application=app_obj).order_by('-cdate')

    from juloserver.bpjs.services import Bpjs
    bpjs = Bpjs(application=app_obj)
    bpjs_details = bpjs.detail()
    if not bpjs.is_scraped:
        bpjs_details = None

    sd_data = app_obj.device_scraped_data.last()
    if sd_data and not sd_data.reports_xls_s3_url:
        sd_data = None

    etl_job = EtlJob.objects.filter(
        application_id=pk, status='load_success',
        data_type__in=['bca', 'mandiri', 'bni', 'bri']).order_by('-cdate').first()

    if etl_job:
        bank_report_url = etl_job.get_bank_report_url()
        bank_report_name = bank_report_url.split('.xlsx')[0] if \
            bank_report_url else ''
    else:
        bank_report_url = ''
        bank_report_name = ''

    list_skiptrace_status = (121, 122, 1220, 123, 124, 1240,
                             125, 127, 130, 131, 132, 138,
                             1380, 141, 144, 172, 180)

    status_skiptrace = True if app_obj.status in list_skiptrace_status else False

    partner_referral = None
    partner_account_id = None
    account_doku_julo = None
    # doku is deprecated code removed

    # get fb data
    fb_obj = app_obj.facebook_data if hasattr(app_obj, 'facebook_data') else None

    # get loan data and order by offer_number
    offer_set_objects = app_obj.offer_set.all().order_by("offer_number")
    button_lock = get_app_lock_count(app_obj)
    lock_status, lock_by = get_lock_status(app_obj, request.user)
    # print "lock_status, lock_by: ", lock_status, lock_by
    min_income_due = 413000
    app_data_fields, app_data_values = dump_application_values_to_excel(app_obj)

    app_data = get_data_application_checklist_collection(app_obj, for_app_only=True)
    deprecated_list = (
        'address_kodepos', 'address_kecamatan', 'address_kabupaten',
        'bank_scrape', 'address_kelurahan', 'address_provinsi', 'bidang_usaha'
    )
    calculation_view_statuses = (130, 134, 140, 141, 142, 143, 144, 160, 161)

    # For CA combo calculation
    product_rate = None
    calculation_results = None
    sum_undisclosed_expense = 0
    if 'total_current_debt' in app_data:
        for expense in app_data['total_current_debt']['undisclosed_expenses']:
            sum_undisclosed_expense += expense['amount']
    if app_obj.partner and app_obj.partner.name in LIST_PARTNER:
        pass
    elif app_obj.status in calculation_view_statuses:
        # logic ITIFTC to use perdicted income here
        monthly_income = get_monthly_income_by_experiment_group(app_obj)
        input_params = {
            'product_line_code': app_obj.product_line_id,
            'job_start_date': app_obj.job_start,
            'job_end_date': timezone.localtime(app_obj.cdate).date(),
            'job_type': app_obj.job_type,
            'monthly_income': monthly_income,
            'monthly_expense': app_obj.monthly_expenses,
            'dependent_count': app_obj.dependent,
            'undisclosed_expense': sum_undisclosed_expense,
            'monthly_housing_cost': app_obj.monthly_housing_cost,
            'application_id': app_obj.id,
            'application_xid': app_obj.application_xid,
        }

        calculation_results = compute_affordable_payment(**input_params)

        calculation_results['undisclosed_expense'] = sum_undisclosed_expense
        if app_obj.product_line_id not in chain(ProductLineCodes.loc(),
                                                ProductLineCodes.grabfood(),
                                                ProductLineCodes.laku6(),
                                                ProductLineCodes.julo_one(),
                                                ProductLineCodes.grab()):
            offer_recommendations_output = get_offer_recommendations(
                app_obj.product_line_id,
                app_obj.loan_amount_request,
                app_obj.loan_duration_request,
                calculation_results['affordable_payment'],
                app_obj.payday,
                app_obj.ktp,
                app_obj.id,
                app_obj.partner
            )
            product_rate = offer_recommendations_output['product_rate']

    offers = None
    offer_form = None
    product_line = None
    email = None
    if app_obj.product_line_id:
        if app_obj.product_line_id in julo_product_line_code:
            offers = app_obj.offer_set.all().order_by('offer_number')
            offer = Offer(application=app_obj,
                          product=app_obj.product_line.productlookup_set.all().first())
            offer_form = OfferForm(instance=offer, prefix='form2')
            product_line = app_obj.product_line.productlookup_set.all()

    if app_obj.email:
        email = app_obj.email.lower()

    form_email = SendEmailForm()
    email_statuses = (121, 132, 138, 122, 130, 131, 135)
    disbursement_statuses = (ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                             ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                             ApplicationStatusCodes.NAME_VALIDATE_FAILED)

    if app_obj.status < ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
        disbursement = None
        bank_number_validate = None
        name_validate = None
    else:
        if hasattr(app_obj, 'loan'):
            loan = app_obj.loan
            disbursement = Disbursement.objects.get_or_none(loan=loan)
            if disbursement is not None:
                if disbursement.bank_number is None:
                    bank_number_validate = 'PENDING'
                else:
                    bank_number_validate = 'VALID'

                if disbursement.validated_name is None:
                    name_validate = 'PENDING'
                elif str(disbursement.validated_name).lower() != str(app_obj.name_in_bank).lower():
                    name_validate = 'INVALID'
                else:
                    name_validate = 'VALID'
            else:
                bank_number_validate = 'NOT INITIATED'
                name_validate = 'NOT INITIATED'
        else:
            disbursement = None
            bank_number_validate = None
            name_validate = None

    xfers_balance = None
    bca_balance = None
    if app_obj.status in disbursement_statuses:
        xfers_balance = get_julo_balance('Xfers')
        bca_balance = get_julo_balance('Bca')

    canned_responses = CannedResponse.objects.all()
    email_app_params = {
        'FULL_NAME': app_obj.fullname_with_title,
        'LOAN_AMOUNT': app_obj.loan_amount_request,
        'LOAN_DURATION': app_obj.loan_duration_request,
        'LOAN_PURPOSE': app_obj.loan_purpose,
        'AGENT_NAME': request.user.username,
    }

    # cashback redeem detail
    wallet_notes = get_wallet_list_note(customer)
    cashback_transfer = CashbackTransferTransaction.objects.filter(
        application=app_obj).exclude(bank_code=GopayConst.BANK_CODE).last()
    cashback_external_id = None
    cashback_retry_times = None
    if cashback_transfer:
        if cashback_transfer.transfer_id:
            try:
                cashback_disbursement = get_disbursement(cashback_transfer.transfer_id)
                cashback_external_id = cashback_disbursement['external_id']
                cashback_retry_times = cashback_disbursement['retry_times']
            except Exception as e:
                logger.info({
                    'application_id': app_obj.id,
                    'cashback_transfer_transfer_id': cashback_transfer.transfer_id,
                    'exception': e
                })

    skip_pv_dv = False
    if customer.potential_skip_pv_dv:
        applications = customer.application_set.filter(
            application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        ).order_by('id')
        application_before = applications.exclude(id__gte=app_obj.id).last()
        if application_before:
            paid_off_date = application_before.loan.payment_set.last().paid_date
            if paid_off_date:
                apply_date = app_obj.cdate
                range_day = (apply_date.date() - paid_off_date).days
                if range_day <= 90:
                    skip_pv_dv = True

    agent_update_app_status = 1
    high_score_full_bypass_status = check_high_score_full_bypass(app_obj)
    if is_experiment_application(app_obj.id, 'ExperimentUwOverhaul') and (
        app_obj.is_julo_one() or app_obj.is_julo_one_ios()
    ):
        high_score_full_bypass_status = app_obj.has_pass_hsfbp()

    sonic_bypass_status = app_obj.has_pass_sonic()
    offline_activation_flow_status = eligible_to_offline_activation_flow(app_obj)

    if app_obj.status in AgentUpdateAppSettings.RESTRICTED_STATUSES:
        agent_update_app_status = 0

    # disbursement detail
    new_xfers = False
    name_bank_validation = None
    disbursement2 = None
    julo_balance = None
    disburse_process_statuses = NAME_BANK_VALIDATION_STATUSES + DISBURSEMENT_STATUSES
    disbursement_method_list = []
    validation_method_list = []

    # for multi disbursement partner
    partner_banks = None
    partner_disbursement = list()
    if app_obj.partner and app_obj.partner.name == PARTNER_LAKU6:
        partner_banks = PartnerBankAccount.objects.filter(partner=app_obj.partner).all()

        # partner name validation
        for p_banks in partner_banks:
            p_banks.name_bank_validation = get_name_bank_validation(p_banks.name_bank_validation_id)
        if app_obj.partner and app_obj.partner.name == PARTNER_LAKU6:
            name_bank_validation = NameBankValidation.objects.filter(
                account_number=app_obj.bank_account_number,
                name_in_bank=app_obj.name_in_bank,
                mobile_phone=app_obj.mobile_phone_1,
            ).last()
            if name_bank_validation:
                name_bank_validation_id = name_bank_validation.id
                validation_method_list = get_list_validation_method()
                name_bank_validation = get_name_bank_validation(name_bank_validation_id)
            else:
                name_bank_validation_id = None
                validation_method_list = None
                name_bank_validation = None

    if app_obj.status in disburse_process_statuses:
        if hasattr(app_obj, 'loan'):
            loan = app_obj.loan
            if app_obj.partner and app_obj.partner.name == PARTNER_LAKU6:
                invoices = LoanDisburseInvoices.objects.filter(loan=loan).all()
                # partner disbursement
                for invoice in invoices:
                    p_disbursement = get_disbursement(invoice.disbursement_id)
                    partner_disbursement.append(p_disbursement)
            else:
                validation_method_list = get_list_validation_method()
                name_bank_validation = get_name_bank_validation(loan.name_bank_validation_id)
                disbursement_method_list = get_list_disbursement_method(bank_name=app_obj.bank_name)
                if name_bank_validation is not None:
                    disbursement_method_list = get_list_disbursement_method(
                        app_obj.bank_name, name_bank_validation['method'])
                new_xfers, disbursement2 = get_multi_step_disbursement(loan.disbursement_id,
                                                                       loan.lender_id)
                julo_balance = None

    limit_info = None

    if (
        app_obj.is_julo_one() or app_obj.is_julo_one_ios() or app_obj.is_grab()
    ) and app_obj.status in (
        ApplicationStatusCodes.NAME_VALIDATE_FAILED,
        ApplicationStatusCodes.LOC_APPROVED,
        ApplicationStatusCodes.BANK_NAME_CORRECTED,
    ):
        name_bank_validation = app_obj.name_bank_validation
        if name_bank_validation:
            name_bank_validation_id = name_bank_validation.id
            validation_method_list = get_list_validation_method()
            name_bank_validation = get_name_bank_validation(name_bank_validation_id)

    if is_experiment_application(app_obj.id, 'ExperimentUwOverhaul') and (
        app_obj.is_julo_one() or app_obj.is_julo_one_ios()
    ):
        is_experiment = True
        target_status = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        experiment = {
            'is_experiment': is_experiment,
            'target_status': target_status
        }
    else:
        is_experiment = False
        target_status = ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL
        experiment = {
            'is_experiment': is_experiment,
            'target_status': target_status
        }

    if (app_obj.is_julo_one() or app_obj.is_julo_one_ios()) and app_obj.status == target_status:
        validation_method_list = get_list_validation_method()
        name_bank_validation = get_name_bank_validation(app_obj.name_bank_validation_id)

    if (app_obj.is_julo_one() or app_obj.is_julo_one_ios()) and app_obj.status in [
        ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        ApplicationStatusCodes.LOC_APPROVED,
    ]:
        account = app_obj.account
        account_limit = account.accountlimit_set.last()
        account_property = account.accountproperty_set.last()
        _matrix, self_interest = get_credit_matrix_and_credit_matrix_product_line(
            app_obj,
            is_self_bank_account=True
        )
        _matrix, other_interest = get_credit_matrix_and_credit_matrix_product_line(
            app_obj,
            is_self_bank_account=False
        )
        limit_info = {
            'account_limit': account_limit.set_limit,
            'self_interest': '{}%'.format(self_interest.interest * 100),
            'other_interest': '{}%'.format(other_interest.interest * 100),
            'cycle_day': account.cycle_day,
            'concurrency': account_property.concurrency,
            'is_entry_level': is_entry_level_type(app_obj)
        }

    risky_checklist = ApplicationRiskyCheck.objects.filter(
        application=app_obj).last()
    risky_fraud_list = None
    if risky_checklist:
        risky_fraud_list = risky_checklist.get_fraud_list()

    loan_objects = Loan.objects.filter(customer=customer).order_by('-cdate').all()

    # overpaid + count number of rejected times for each case
    overpaid_cases = CashbackOverpaidVerification.objects.filter(
        application=app_obj,
    ).annotate(
        rejected_times=Count(
            Case(When(Q(overpaid_history__decision=OverpaidConsts.Statuses.REJECTED), then=1)),
        )
    ).order_by('-cdate')
    # sort to put pending to top
    overpaid_cases = sorted(overpaid_cases, key=overpaid_status_sorting_func)
    mycroft_score_ana = PdApplicationFraudModelResult.objects.filter(application_id=app_obj.id).last()
    mycroft_score = None
    if mycroft_score_ana:
        mycroft_score = ceil(mycroft_score_ana.pgood * 100) / 100

    context = {
        'form': form,
        'form_app': form_app,
        'form_app_select': form_app_select,
        'form_security': form_security,
        'app_obj': app_obj,
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
        'datetime_now': timezone.now(),
        'image_per_row0': (1, 7, 13, 19, 25),
        'image_per_row': (7, 13, 19, 25),
        'lock_status': lock_status,
        'lock_by': lock_by,
        'button_lock': button_lock,
        'message_out_simpan_note': message_out_simpan_note,
        'message_out_ubah_status': message_out_ubah_status,
        'message_out_security_note': message_out_security_note,
        'security_note_active': security_note_active,
        'ubah_status_active': ubah_status_active,
        'simpan_note_active': simpan_note_active,
        'min_income_due': min_income_due,
        'offer_set_objects': offer_set_objects,
        'app_data_values': app_data_values,
        'app_data_fields': app_data_fields,
        'skiptrace_list': skiptrace_list,
        'skiptrace_history_list': skiptrace_history_list,
        'status_skiptrace': status_skiptrace,
        'partner_referral': partner_referral,
        'partner_account_id': partner_account_id,
        'account_doku_julo': account_doku_julo,
        'app_data': app_data,
        'deprecated_list': deprecated_list,
        'offers': offers,
        'offer_form': offer_form,
        'calculation_view_statuses': calculation_view_statuses,
        'product_line': product_line,
        'calculation_results': calculation_results,
        'product_rate': product_rate,
        'product_line_STL': ProductLineCodes.stl(),
        'product_line_BRI': ProductLineCodes.bri(),
        'product_line_GRAB': ProductLineCodes.grab(),
        'product_line_LOC': ProductLineCodes.loc(),
        'product_line_GRABFOOD': ProductLineCodes.grabfood(),
        'form_send_email': form_email,
        'app_email': email,
        'email_statuses': email_statuses,
        'email_sms_list': email_sms_list,
        'disbursement': disbursement,
        'bank_number_validate': bank_number_validate,
        'name_validate': name_validate,
        'bank_list': BankManager.get_bank_names(),
        'bank_name_list': json.dumps(BankManager.get_bank_names()),
        'app_detail_history_list': app_detail_history_list,
        'xfers_balance': xfers_balance,
        'bca_balance': bca_balance,
        'canned_responses': canned_filter(canned_responses),
        'email_app_params': json.dumps(email_app_params),
        'cashback_transfer': cashback_transfer,
        'cashback_external_id': cashback_external_id,
        'cashback_retry_times': cashback_retry_times,
        'wallet_notes': wallet_notes,
        'skip_pv_dv': skip_pv_dv,
        'agent_update_app_status': agent_update_app_status,
        'disburse_process_statuses': disburse_process_statuses,
        'disbursement_statuses': DISBURSEMENT_STATUSES,
        'name_bank_validation': name_bank_validation,
        'digisign_failed': ApplicationStatusCodes.DIGISIGN_FAILED,
        'disbursement2': disbursement2,
        'julo_balance': julo_balance,
        'disbursement_method_list': disbursement_method_list,
        'validation_method_list': validation_method_list,
        'partner_transfers': CashbackTransferConst.partner_transfers,
        'partner_banks': partner_banks,
        'partner_disbursement': partner_disbursement,
        'product_line_PEDESTL': ProductLineCodes.pedestl(),
        'product_line_PEDEMTL': ProductLineCodes.pedemtl(),
        'partner_laku6': PARTNER_LAKU6,
        'new_xfers': new_xfers,
        'is_suspect_va': suspect_account_number_is_va(app_obj.bank_account_number,
                                                      app_obj.bank_name),
        'bpjs_details': bpjs_details,
        'sd_data': sd_data,
        'bank_report_url': bank_report_url,
        'bank_report_name': bank_report_name,
        'is_c_score_in_delay_period': is_c_score_in_delay_period(app_obj),
        'eta_time_for_c_score_delay': format_datetime(
            timezone.localtime(get_eta_time_for_c_score_delay(app_obj)),
            'd MMMM yyyy HH:mm', locale='id_ID'
        ),
        'julo_one_limit_info_status': [ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                                       ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
                                       ApplicationStatusCodes.LOC_APPROVED],
        'julo_one_bank_name_status': [ApplicationStatusCodes.NAME_VALIDATE_FAILED,
                                       ApplicationStatusCodes.BANK_NAME_CORRECTED],
        'limit_info': limit_info,
        'julo_one_product_code': ProductLineCodes.J1,
        'pd_bank_scrape_model_result': check_positive_processed_income(app_obj.id),
        'security_note_list': security_note_list,
        'is_grab': app_obj.is_grab(),
        'risky_fraud_list': risky_fraud_list,
        'check_high_score_full_bypass': high_score_full_bypass_status,
        'loan_objects': loan_objects,
        'history_note_app': history_note_app,
        'account_payment_objects': account_payment_objects,
        'account_objects': account_objects,
        'experiment': experiment,
        'check_sonic_bypass': sonic_bypass_status,
        'check_offline_activation_flow': offline_activation_flow_status,
        'overpaid_cases': overpaid_cases,
        'mycroft_score': mycroft_score,
    }

    if hasattr(app_obj, 'product_line'):
        product_line = app_obj.product_line_id
        bank_name_validated = is_bank_name_validated(app_obj)
        if product_line in ProductLineCodes.mtl():
            check_point_lists = [
                'menandatangani SPHP secara elektronik di dalam aplikasi.',
                'merekam pernyataan dengan lengkap (kalau tidak lengkap, pencairan akan terhambat)'
            ]
            if not bank_name_validated:
                check_point_lists.insert(0,
                                         "melakukan validasi akun rekening bank Anda di Aplikasi JULO")
            context['check_point_lists'] = check_point_lists
        elif product_line in ProductLineCodes.stl():
            context['validate_bank_account'] = bank_name_validated

    return render(
        request,
        template_name,
        context
    )


# ----------------------------- Customer Service Detail END  ---------------------------------------

# ----------------------------- Application Form  Assist START  ---------------------------------------


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.J1_AGENT_ASSISTED_100])
def application_form_assist(request, pk):

    template_name = 'object/app_status/application_form_assist.html'

    app_obj = get_object_or_404(Application, id=pk)
    if app_obj and (
        app_obj.application_status_id != ApplicationStatusCodes.FORM_CREATED
        or (not app_obj.is_julo_one() and not app_obj.is_julo_one_ios())
        or app_obj.onboarding_id != OnboardingIdConst.LONGFORM_SHORTENED_ID
    ):
        url = reverse('app_status:change_status', kwargs={'pk': app_obj.id})
        return redirect(url)

    # loan purpose data
    list_loan_purpose = LoanPurposeDropDown(product_line_code=ProductLineCodes.J1)
    loan_purpose = json.loads(list_loan_purpose._get_data(ProductLineCodes.J1))

    # count application number
    customer_id = app_obj.customer.id
    last_application = (
        Application.objects.filter(customer_id=customer_id).exclude(pk=app_obj.id).last()
    )

    application_number = 1
    if last_application and last_application.application_number:
        application_number = last_application.application_number + 1

    context = {
        'app_obj': app_obj,
        'loan_purpose': loan_purpose.get('data', []),
        'token': request.user.auth_expiry_token.key,
        'application_number': application_number,
    }

    return render(request, template_name, context)


# ----------------------------- Application Form Assist END  ---------------------------------------

# ----------------------------- Fraud ajax calls START  ---------------------------------------
@julo_login_required
@julo_login_required_multigroup(
    ['admin_full', 'ops_supervisor', 'ops_team_leader', 'bo_general_cs', 'fraudcolls', 'fraudops'])
@csrf_protect
def ajax_save_fraud_crm_form(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()

    if "save_data" in data:
        fraud_form_data = json.loads(data['save_data'])

    if not data['application_id']:
        return JsonResponse({
            "status": "failed",
            "messages": "application_id could not be empty!!"
        })
    # save account take over selections

    application_id = int(data['application_id'])

    application = Application.objects.get_or_none(id=application_id)
    if not application:
        return JsonResponse({
            "status": "failed",
            "messages": "application not found!!"
        })

    if not application.account:
        return JsonResponse({
            "status": "failed",
            "messages": "account not found!!"
        })

    account = application.account
    with transaction.atomic():
        if account.status_id == JuloOneCodes.FRAUD_REPORTED:
            fraud_crm_form = FraudCrmForm.objects.filter(account=account).last()
            if fraud_crm_form:
                save_data = fraud_crm_form.saved_value
            else:
                save_data = {'account_take_over': True}

            if 'send_to' in fraud_form_data:
                if fraud_form_data['magic_link_type'] == "email":
                    save_data['use_registered_email'] = fraud_form_data['is_using_registerd_email']
                    save_data['magic_link_email'] = fraud_form_data['send_to']
                elif fraud_form_data['magic_link_type'] == "phone":
                    save_data['use_registered_phone'] = fraud_form_data['is_using_registerd_phone']
                    save_data['magic_link_phone'] = fraud_form_data['send_to']

            if 'force_logout' in fraud_form_data:
                save_data['force_logout'] = 'yes'

            if 'reset_pin' in fraud_form_data:
                save_data['reset_pin_status'] = 'email-sent'
                customer = application.customer
                if customer.reset_password_key:
                    save_data['reset_pin_key'] = customer.reset_password_key

            if fraud_crm_form:
                fraud_crm_form.update_safely(saved_value=save_data)
            else:
                fraud_crm_form = FraudCrmForm.objects. \
                    create(account=account, saved_value=save_data, customer=account.customer)

        return JsonResponse({
            "status": "success",
            "fraud_crm_data": save_data
        })


@julo_login_required
@julo_login_required_multigroup(
    ['admin_full', 'ops_supervisor', 'ops_team_leader', 'bo_general_cs', 'fraudcolls', 'fraudops'])
@csrf_protect
def ajax_send_magic_link(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()
    if not data['application_id']:
        return JsonResponse({
            "status": "failed",
            "messages": "application_id could not be empty!!"
        })

    application_id = int(data['application_id'])
    magic_link_type = data['magic_link_type']
    send_to = data['send_to']

    application = Application.objects.get_or_none(id=application_id)
    if not application:
        return JsonResponse({
            "status": "failed",
            "messages": "application not found!!"
        })

    if not application.account:
        return JsonResponse({
            "status": "failed",
            "messages": "account not found!!"
        })

    account = application.account
    # generate magic link
    generated_magic_link, magic_link_history = generate_magic_link()

    sms_history = None
    email_history = None
    if magic_link_type == "email":
        template_code = "cs_change_email_verification"
        email_subject = "Verifikasi email akun JULO Anda"
        available_context = {
            'first_name': application.first_name_only,
            'generated_magic_link': generated_magic_link,
            'banner_url': EmailOTP.BANNER_URL,
            'footer_url': EmailOTP.FOOTER_URL,
        }
        magic_link_content = render_to_string("fraud/" + template_code + ".html", available_context)
        email_history = send_email_fraud_mitigation(
            application, magic_link_content, template_code, email_subject, send_to)
        if email_history:
            magic_link_history.update_safely(email_history=email_history)
    else:
        sms_history = send_magic_link_sms(application, send_to, generated_magic_link)
        if sms_history:
            magic_link_history.update_safely(sms_history=sms_history)

    if sms_history or email_history:
        return JsonResponse({
            "status": "success",
            "messages": "success update %s" % send_to
        })

    return JsonResponse({
        "status": "failed",
        "messages": "Failed to send magic link to  %s" % send_to
    })


@julo_login_required
@julo_login_required_multigroup(
    ['admin_full', 'ops_supervisor', 'ops_team_leader', 'bo_general_cs', 'fraudcolls', 'fraudops'])
@csrf_protect
def ajax_check_if_magic_links_verified(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()
    if not data['application_id']:
        return JsonResponse({
            "status": "failed",
            "messages": "application_id could not be empty!!"
        })

    application_id = int(data['application_id'])
    magic_link_type = data['magic_link_type']

    # check verified or not in fraud crm form
    application = Application.objects.get_or_none(id=application_id)
    magic_link_status = check_if_magic_link_verified(application, magic_link_type)
    account = application.account

    if not magic_link_status:
        return JsonResponse({"status": "failed", "messages": "magic links data not found"})

    fraud_crm_form = FraudCrmForm.objects.filter(account=account).last()
    saved_value = fraud_crm_form.saved_value
    if saved_value:
        is_verified = "yes" if magic_link_status == "verified" else "no"
        if magic_link_type == "phone":
            saved_value['magic_link_phone_verified'] = magic_link_status
        elif magic_link_type == "email":
            saved_value['magic_link_email_verified'] = magic_link_status

        fraud_crm_form.update_safely(saved_value=saved_value)
        data_check = {'type': magic_link_type, "verified": is_verified,
                      "magic_link_status": magic_link_status}

        return JsonResponse({
            "status": "success",
            "messages": "magic link " + magic_link_status,
            "data": data_check
        })

    return JsonResponse({"status": "failed", "messages": "magic link verification failed "})


@julo_login_required
@julo_login_required_multigroup(
    ['admin_full', 'ops_supervisor', 'ops_team_leader', 'bo_general_cs', 'fraudcolls', 'fraudops'])
@csrf_protect
def ajax_check_reset_pin_status(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()
    if not data['application_id']:
        return JsonResponse({
            "status": "failed",
            "messages": "application_id could not be empty!!"
        })

    customer_pin_change_service = pin_services.CustomerPinChangeService()
    application_id = int(data['application_id'])

    # check verified or not in fraud crm form
    application = Application.objects.get_or_none(id=application_id)
    account = application.account
    fraud_crm_form = FraudCrmForm.objects.filter(account=account).last()
    if not fraud_crm_form:
        return JsonResponse({
            "status": "failed",
            "messages": "reset pin request not found"
        })

    saved_value = fraud_crm_form.saved_value

    pin_status = ""
    reset_pin_key = ""
    if 'reset_pin_status' in saved_value and \
            saved_value['reset_pin_status'] != "email-sent":
        pin_status = saved_value['reset_pin_status']
    else:
        customer = application.customer
        if not customer.reset_password_key:
            reset_pin_key = saved_value['reset_pin_key']
            if 'reset_pin_key' not in saved_value:
                pin_status = "expired"
        else:
            reset_pin_key = customer.reset_password_key
            if customer.has_resetkey_expired():
                pin_status = "expired"

    if reset_pin_key:
        if customer_pin_change_service.check_key(reset_pin_key):
            customer_pin_change = CustomerPinChange.objects.filter(
                reset_key=reset_pin_key,
                status=ResetEmailStatus.CHANGED,
                change_source="Forget PIN").last()
            if customer_pin_change:
                pin_status = "changed" \
                    if customer_pin_change.status == ResetEmailStatus.CHANGED else "email-sent"
        else:
            pin_status = "expired"

    if pin_status:
        saved_value['reset_pin_status'] = pin_status
        if pin_status == "changed":
            fraud_crm_form.update_safely(saved_value=saved_value)
        data_check = {'type': "reset_pin", "reset_pin_status": pin_status}

        return JsonResponse({
            "status": "success",
            "messages": "Reset PIN status: " + pin_status,
            "data": data_check
        })

    return JsonResponse({"status": "failed", "messages": "PIN reset verification failed"})


@julo_login_required
@julo_login_required_multigroup(
    ['admin_full', 'ops_supervisor', 'ops_team_leader', 'bo_general_cs', 'fraudcolls', 'fraudops'])
@csrf_protect
def ajax_check_email(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application_id = int(data['application_id'])
    customer_id = int(data['customer_id'])
    new_email = data['new_email'].strip().lower()
    app = Application.objects.get_or_none(id=application_id)
    if not app:
        return JsonResponse({
            "status": "failed",
            "message": "Application not exists"
        })
    customer = Customer.objects.exclude(id=customer_id).filter(email=new_email).last()
    if customer:
        return JsonResponse({
            "status": "failed",
            "message": "Alamat email sudah digunakan pengguna lain."
        })

    return JsonResponse({
        "status": "success"
    })


# ----------------------------- Fraud ajax call END  ---------------------------------------

# ----------------------------- ajax Grab START  -------------------------------------------


@julo_login_required
@julo_login_required_multigroup(
    ['admin_full', 'ops_supervisor', 'ops_team_leader', 'bo_general_cs', 'fraudcolls',
     'fraudops', 'bo_data_verifier'])
@csrf_protect
def ajax_grab_verify_phone_number(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()

    phone_number = data['phone_number']
    customer_id = int(data['customer_id'])
    customer = Customer.objects.get(id=customer_id)

    status_grab = 'failed'
    message_grab = None
    try:
        result = GrabLoanService().check_phone_number_change(
            customer, phone_number)

        if result['already_registered_number']:
            message_grab = "Nomor HP sudah digunakan pengguna lain."
        elif not result['valid_phone']:
            message_grab = result['error_message']
        else:
            status_grab = 'success'

    except GrabLogicException as e:
        logger.info({
            "action": "ajax_grab_verify_phone_number",
            "customer_id": customer.id,
            "error": str(e)
        })

        return JsonResponse({
            "status": status_grab,
            "message": str(e)
        })

    return JsonResponse({
        "status": status_grab,
        "message": message_grab
    })


# ----------------------------- ajax Grab END  -------------------------------------------

# ----------------------------- ajax Fraud START  -------------------------------------------


@julo_login_required
@julo_login_required_multigroup(
    ['admin_full', 'bo_full', 'bo_data_verifier', 'cs_team_leader', 'ops_supervisor',
     'ops_team_leader', 'bo_general_cs', 'fraudcolls', 'fraudops'])
@csrf_protect
def ajax_fraud_reverify_account(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    account_id = int(data['account_id'])
    account = Account.objects.filter(id=account_id).last()

    if not account:
        return JsonResponse({
            "status": "failed",
            "message": "Application or Account not exists"
        })

    success = process_account_reactivation(account)

    if success:
        return JsonResponse({
            "status": "success",
            "message": "Reverfication Success"
        })
    else:
        return JsonResponse({
            "status": 'failed',
            "message": "Exception occured check logs"
        })


# ----------------------------- ajax Fraud END  -------------------------------------------

# ----------------------------- ajax Autodebit BCA START  -------------------------------------------

@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
@csrf_protect
def ajax_get_autodebit_bca_webview(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    current_user = request.user
    data = request.POST.dict()

    if not data['account_id'] or not data['customer_id']:
        return JsonResponse({
            "status": "failed",
            "message": 'Customer/Account ID kosong'
        })

    account = Account.objects.get_or_none(pk=data['account_id'], customer=data['customer_id'])

    if not account:
        return JsonResponse({
            "status": "failed",
            "message": 'Account/Application/Customer tidak valid'
        })

    application = Application.objects.get_or_none(
        application_xid=data['application_xid'], customer=data['customer_id'])

    if not account:
        return JsonResponse({
            "status": "failed",
            "message": 'Account/Application/Customer tidak valid'
        })

    if application != account.last_application:
        return JsonResponse({
            "status": "failed",
            "message": 'Account/Application/Customer tidak valid'
        })

    existing_autodebet = AutodebetAccount.objects.filter(account=account).last()

    if existing_autodebet:
        if existing_autodebet.is_use_autodebet:
            return JsonResponse({
                'status': 'failed',
                'message': "Account autodebet sedang aktif"
            })

        if not existing_autodebet.failed_ts:
            process_reset_autodebet_account(account, is_agent=True)

    try:
        with transaction.atomic():
            data, error_message, is_forbidden = process_account_registration(
                account, True, current_user)
    except JuloException as e:
        return JsonResponse({'status': 'failed', 'message': str(e)})

    if error_message:
        return JsonResponse({'status': 'failed', 'message': error_message})

    return JsonResponse({
        'status': 'success',
        'webview_url': data['webview_url']
    })


def ajax_reset_autodebit_account(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    account = Account.objects.get_or_none(pk=data['account_id'], customer=data['customer_id'])

    if not account:
        return JsonResponse({
            "status": "failed",
            "message": 'Account/Application/Customer tidak valid'
        })

    application = Application.objects.filter(
        application_xid=data['application_xid'], customer=data['customer_id']).last()

    if not account:
        return JsonResponse({
            "status": "failed",
            "message": 'Account/Application/Customer tidak valid'
        })

    if application != account.last_application:
        return JsonResponse({
            "status": "failed",
            "message": 'Account/Application/Customer tidak valid'
        })

    existing_autodebet = AutodebetAccount.objects.filter(account=account).last()

    if existing_autodebet:
        if existing_autodebet.is_use_autodebet:
            return JsonResponse({
                'status': 'failed',
                'message': "Account autodebet sedang aktif"
            })
        elif existing_autodebet.status == 'pending_revocation':
            return JsonResponse({
                'status': 'failed',
                'message': 'Account tidak dapat direset karena status pending_revocation '
                           '- customer request deaktivasi'
            })

        if not existing_autodebet.failed_ts:
            with transaction.atomic():
                process_reset_autodebet_account(account, is_agent=True)

    return JsonResponse({
        'status': 'success'
    })


def ajax_change_autodebit_deduction_day(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    account = Account.objects.get_or_none(pk=data['account_id'], customer=data['customer_id'])

    if not account:
        return JsonResponse({
            "status": "failed",
            "message": 'Account/Application/Customer tidak valid'
        })

    existing_autodebet = AutodebetAccount.objects.filter(account=account).last()

    if not existing_autodebet:
        return JsonResponse({
            "status": "failed",
            "message": 'Autodebit account tidak ditemukan'
        })

    experiment_setting = ExperimentSetting.objects.filter(
        code=ExperimentConst.BEST_DEDUCTION_TIME_ADBCA_EXPERIMENT_CODE).last()
    experiment_group = ExperimentGroup.objects.filter(
        experiment_setting=experiment_setting,
        account_id=existing_autodebet.account.id).last()
    if experiment_group and experiment_group.group == 'experiment':
        existing_autodebet.update_safely(
            deduction_source=AutodebetDeductionSourceConst.ORIGINAL_CYCLE_DAY,
            deduction_cycle_day=account.cycle_day,
            is_experiment_complaint=True,
        )

    return JsonResponse({
        'status': 'success'
    })


# ----------------------------- ajax Autodebit BCA END  -------------------------------------------


# ------------------------------ ajax Fraud show similar faces -------------------------------------
@julo_login_required
def ajax_fraud_show_similar_faces(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    application_id = request.GET.get('application_id')
    geohash_type = request.GET.get('type')

    if not (application_id and geohash_type):
        return JsonResponse(
            {'message': 'Please enter a valid Params'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if geohash_type not in ('geohash6', 'geohash8', 'geohash9'):
        return JsonResponse(
            {'message': 'Please use a valid type'},
            status=status.HTTP_400_BAD_REQUEST
        )
    try:
        application_id = int(application_id)
        geohash_type = str(geohash_type)
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return JsonResponse(
                {'message': 'Application not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        curr_add_geohash = AddressGeolocationGeohash.objects.filter(
            address_geolocation__application=application
        ).last()
        if not curr_add_geohash:
            return JsonResponse(data={'message': 'address geolocation geohash not found'},
                                status=status.HTTP_404_NOT_FOUND)

        if geohash_type == 'geohash6':
            geohash = curr_add_geohash.geohash6
        elif geohash_type == 'geohash8':
            geohash = curr_add_geohash.geohash8
        else:
            geohash = curr_add_geohash.geohash9

        product_line_filter = (
            ProductLineCodes.TURBO,
            ProductLineCodes.J1,
            application.product_line_id,
        )

        selfie_geohash_image_feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.SELFIE_GEOHASH_CRM_IMAGE_LIMIT,
            is_active=True
        )
        if selfie_geohash_image_feature_setting:
            current_date = timezone.localtime(timezone.now()).date()
            similar_applications = (
                AddressGeolocation.objects.filter(
                    Q(addressgeolocationgeohash__geohash6=geohash) |
                    Q(addressgeolocationgeohash__geohash8=geohash) |
                    Q(addressgeolocationgeohash__geohash9=geohash)
                ).filter(
                    application__cdate__gt=current_date - datetime.timedelta(
                        days=selfie_geohash_image_feature_setting.parameters['days']),
                    application__applicationhistory__status_new=ApplicationStatusCodes.FORM_PARTIAL,
                    application__product_line_id__in=product_line_filter,
                ).exclude(
                    application_id=application_id,
                )
                .distinct().values_list('application_id', flat=True).order_by('-application_id')
            )
        else:
            similar_applications = (
                AddressGeolocation.objects.filter(
                    Q(addressgeolocationgeohash__geohash6=geohash) |
                    Q(addressgeolocationgeohash__geohash8=geohash) |
                    Q(addressgeolocationgeohash__geohash9=geohash)
                ).filter(
                    application__applicationhistory__status_new=ApplicationStatusCodes.FORM_PARTIAL,
                    application__product_line_id__in=product_line_filter,
                ).exclude(
                    application_id=application_id,
                )
                .distinct().values_list('application_id', flat=True).order_by('-application_id')
            )

        # Get similar application_ids
        default_page_size = 23
        page_size = int(request.GET.get('limit', default_page_size))
        if page_size > 100:
            page_size = default_page_size
        page_number = request.GET.get('page', 1)
        paginator = Paginator(similar_applications, page_size)
        application_ids = list(paginator.page(page_number))

        current_selfie_image = Image.objects.filter(
            image_source=application_id,
            image_type='selfie',
        ).last()
        current_selfie_data = {
            'application_id': application_id,
            'url': current_selfie_image.image_url,
        }

        selfie_images = Image.objects.filter(
            image_source__in=application_ids,
            image_type='selfie',
            image_status=Image.CURRENT,
        ).order_by('-image_source')

        data = []
        for selfie_image in selfie_images:
            geohash_data = {
                'application_id': selfie_image.image_source,
                'url': selfie_image.image_url,
            }
            data.append(geohash_data)
            application_ids.remove(int(selfie_image.image_source))

        # Handle incase there are application that doesn't have selfie image
        for application_id in application_ids:
            data.append({
                'application_id': application_id,
                'url': static('/images/icons/ic-placeholder.png'),
            })

        json_data = {
            'count': paginator.count,
            'data': data,
            'current_selfie_data': current_selfie_data,
            'geohash6': curr_add_geohash.geohash6,
            'geohash8': curr_add_geohash.geohash8,
            'geohash9': curr_add_geohash.geohash9,
        }
        return JsonResponse(data=json_data, status=status.HTTP_200_OK)
    except ValueError:
        return JsonResponse(
            {'message': 'please enter a valid params'},
            status=status.HTTP_400_BAD_REQUEST)


@julo_login_required
def ajax_check_credit_score_status(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    from juloserver.application_flow.services2.credit_score_dsd import general_check_for_scoring

    data = request.POST.dict()
    application_id = data.get('application_id', None)
    application = Application.objects.filter(pk=application_id).last()

    if not application:
        return JsonResponse(
            {
                'status': 'failed',
                'message': 'Application {0} tidak ditemukan'.format(application_id),
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    result, flag, message = general_check_for_scoring(application, is_need_to_moved=False)

    return JsonResponse(
        {
            'status': 'success',
            'message': message,
        },
        status=status.HTTP_200_OK,
    )


@julo_login_required
def ajax_get_dropdown_data_form(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    # source dropdown job
    source_job = json.loads(JobDropDownV2()._get_data(ProductLineCodes.J1))
    job_type_arr_data = []
    for item in source_job['data']:
        job_type_arr = item.split(',')[0]
        job_type_arr_data.append(job_type_arr)

    unique_job_type = list(set(job_type_arr_data)) if job_type_arr_data else []

    # source dropdown address
    source_province = AddressDropDown().DATA
    province_arr = []

    # kota kabupaten
    kota_kabupaten_arr = []
    for item in source_province:
        province_data = item.split(',')[4]
        province_arr.append(province_data)

        kota_kabupaten = item.split(',')[3]
        kota_kabupaten_arr.append(kota_kabupaten)

    unique_province = list(set(province_arr)) if province_arr else []
    unique_kota_kabupaten = list(set(kota_kabupaten_arr)) if kota_kabupaten_arr else []

    data = {
        'list_job': source_job,
        'list_job_type': unique_job_type,
        'list_province': unique_province,
        'list_kota_kabupaten': unique_kota_kabupaten,
    }

    return JsonResponse(
        {
            'status': 'success',
            'data': data,
        },
        status=status.HTTP_200_OK,
    )


@julo_login_required
def ajax_get_dropdown_data_form_job(request, job_industry, job_description):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    source_job = json.loads(JobDropDownV2()._get_data(ProductLineCodes.J1))

    job_description_arr_data, job_industry_arr_data = [], []

    for item in source_job['data']:
        job_type_arr = item.split(',')

        # search job description based on type data
        if job_type_arr[0].lower() == job_industry.lower():
            job_industry_arr_data.append(job_type_arr[1])

        # search job position based on description data
        search_key_job_position = job_type_arr[1].lower().replace('/', '').replace('/', '')
        if str(job_description) != '0' and search_key_job_position == job_description.lower():
            try:
                job_description_arr_data.append(job_type_arr[2])
            except IndexError:
                continue

    unique_job_industry = list(set(job_industry_arr_data)) if job_industry_arr_data else []
    unique_job_description = list(set(job_description_arr_data)) if job_description_arr_data else []

    data = {
        'list_job_industry': unique_job_industry,
        'list_job_description': unique_job_description,
    }

    return JsonResponse(
        {
            'status': 'success',
            'data': data,
        },
        status=status.HTTP_200_OK,
    )


@julo_login_required
def ajax_get_dropdown_data_company(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    term = request.GET.get('term')
    source_company_arr = CompanyDropDown().DATA

    unique_company = list(set(source_company_arr)) if source_company_arr else []
    result = []
    counter, limit = 0, 100

    if term:
        for item in unique_company:
            if term in item:
                counter += 1
                result.append(item)
                if counter >= limit:
                    break

    return JsonResponse(
        {
            'status': 'success',
            'data': result,
        },
        status=status.HTTP_200_OK,
    )
