from __future__ import print_function

import json
import logging
import operator
import sys
from builtins import map, str
from datetime import datetime, timedelta
from functools import reduce
from itertools import chain

from app_status.functions import app_lock_list, choose_number
from app_status.services import (
    application_dashboard,
    fraudops_dashboard,
    application_priority_dashboard,
    lender_bucket,
    loan_dashboard,
    payment_dashboard,
    pv_3rd_party_dashboard,
)
from cuser.middleware import CuserMiddleware
from dashboard.models import CRMSetting
from dashboard.services import (
    generate_va_for_bank_bca,
    generate_va_for_bank_permata,
    list_payment_methods,
    load_color,
    update_primary_and_is_shown_payment_methods,
)
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core import serializers
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import EmptyPage, Paginator
from django.core.urlresolvers import reverse
from django.db import DatabaseError, transaction
from django.db.models import CharField, Max, Q, Value
from django.db.utils import IntegrityError
from django.http.response import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.generic import ListView
from object import julo_login_required
from payment_status.functions import payment_lock_list
from pyexcel_xls import get_data
from scraped_data.forms import ApplicationSearchForm

from juloserver.account.models import Account
from juloserver.collection_field_automation.views import agent_field_dashboard
from juloserver.collectionbucket.models import CollectionAgentTask
from juloserver.collectionbucket.services import get_agent_service_for_bucket
from juloserver.entry_limit.services import is_entry_level_type
from juloserver.followthemoney.models import LenderWithdrawal
from juloserver.followthemoney.services import get_reversal_trx_data
from juloserver.julo.banks import BankCodes
from juloserver.julo.clients import get_autodial_client, get_julo_sentry_client
from juloserver.julo.clients.telephony import QuirosApiError
from juloserver.julo.constants import AgentAssignmentTypeConst, FeatureNameConst
from juloserver.julo.models import (
    PTP,
    Agent,
    Application,
    ApplicationHistory,
    ApplicationNote,
    Autodialer122Queue,
    AutodialerActivityHistory,
    AutodialerCallResult,
    AutodialerSession,
    AutodialerSessionStatus,
    Customer,
    CustomerAppAction,
    Device,
    DeviceAppAction,
    FeatureSetting,
    Loan,
    OpsTeamLeadStatusChange,
    Partner,
    Payment,
    PaymentAutodialerActivity,
    PaymentAutodialerSession,
    PaymentMethod,
    PaymentNote,
    PredictiveMissedCall,
    QuirosProfile,
    Skiptrace,
    SkiptraceHistory,
    SkiptraceResultChoice,
    StatusLookup,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import (
    autodialer_next_turn,
    get_julo_pn_client,
    process_application_status_change,
    process_status_change_on_failed_call,
)
from juloserver.julo.services2 import get_agent_service, get_redis_client
from juloserver.julo.services2.activity_dialer import UploadDialerActivityForm
from juloserver.julo.services2.agent import convert_usergroup_to_agentassignment_type
from juloserver.julo.services2.experiment import check_cootek_experiment
from juloserver.julo.services2.ops_team_leader import SubmitOPSStatusForm
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
    StatusManager,
)
from juloserver.julo.tasks import send_all_notification_to_customer_notify_backup_va
from juloserver.julo.tasks import async_store_crm_navlog
from juloserver.julo.utils import (
    autodialer_note_generator,
    format_e164_indo_phone_number,
)

# LOC
from juloserver.line_of_credit.services import LocCollectionService
from juloserver.loan.services.loan_related import (
    get_credit_matrix_and_credit_matrix_product_line,
)
from juloserver.minisquad.constants import RedisKey
from juloserver.minisquad.models import CollectionHistory, CollectionSquad
from juloserver.minisquad.services import get_oldest_payment_ids_loans
from juloserver.paylater.models import DisbursementSummary, Statement
from juloserver.sales_ops.constants import SalesOpsRoles
from juloserver.sales_ops.services import (
    autodialer_services as sales_ops_autodialer_services,
)
from juloserver.sales_ops.views import crm_views as sales_ops_crm_views
from juloserver.streamlined_communication.views import streamlined_communication

from .constants import BucketType, JuloUserRoles, RepaymentChannel
from juloserver.portal.object import julo_login_required_group, julo_login_required_multigroup

from .forms import DefaultRoleForm
from .functions import create_or_update_role, get_selected_defaultrole

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))
sentry_client = get_julo_sentry_client()


PROJECT_URL = getattr(settings, 'PROJECT_URL')
DPD1_DPD29 = AgentAssignmentTypeConst.DPD1_DPD29
DPD30_DPD59 = AgentAssignmentTypeConst.DPD30_DPD59
DPD60_DPD89 = AgentAssignmentTypeConst.DPD60_DPD89
DPD90PLUS = AgentAssignmentTypeConst.DPD90PLUS


def index(request):
    user = request.user
    try:
        url_current = request.META['HTTP_REFERER']
    except KeyError:
        url_current = ''
    if user.is_authenticated():
        default_role = get_selected_defaultrole(request.user)

        if default_role and default_role != JuloUserRoles.JULO_PARTNERS:
            dashboard_view = select_active_role(request, default_role)
            if dashboard_view is not None:
                return dashboard_view
            else:
                return no_dashboard_view(request)
        else:
            partners_role = request.user.groups.filter(name=JuloUserRoles.JULO_PARTNERS)
            if partners_role and 'list' not in url_current:
                role_name = JuloUserRoles.JULO_PARTNERS
                create_or_update_role(request.user, role_name)
                url = reverse('dashboard:lender_list_page')
                return redirect(url)

            field_agent_role = user.groups.filter(name=JuloUserRoles.COLLECTION_FIELD_AGENT)
            if field_agent_role:
                return dashboard_agent_field(request)

            groups = request.user.groups.all()
            for group in groups:
                dashboard_view = select_active_role(request, group.name)
                if dashboard_view is not None:
                    return dashboard_view

        # if there is no groups/roles for this user
        return no_dashboard_view(request)

    # render to home page
    return render(request, 'main/welcome.html')


@julo_login_required
def select_active_role(request, role_selected):
    if JuloUserRoles.ADMIN_FULL in role_selected:
        return dashboard_admin_full(request)
    if JuloUserRoles.BO_DATA_VERIFIER in role_selected:
        return dashboard_bo_data_verifier(request)
    if JuloUserRoles.BO_CREDIT_ANALYST in role_selected:
        return dashboard_bo_credit_analyst(request)
    if JuloUserRoles.DOCUMENT_VERIFIER in role_selected:
        return dashboard_bo_data_verifier(request)
    if JuloUserRoles.BO_SD_VERIFIER in role_selected:
        return dashboard_bo_sd_verifier(request)

    # TODO: maintainin roles below
    if JuloUserRoles.ADMIN_READ_ONLY in role_selected:
        return dashboard_bo_data_verifier(request)
    if JuloUserRoles.BO_FULL in role_selected:
        return dashboard_bo_data_verifier(request)
    if JuloUserRoles.BO_READ_ONLY in role_selected:
        return dashboard_bo_data_verifier(request)
    if JuloUserRoles.BO_OUTBOUND_CALLER in role_selected:
        return dashboard_bo_data_verifier(request)
    if JuloUserRoles.BO_OUTBOUND_CALLER_3rd_PARTY in role_selected:
        return dashboard_bo_outbound_caller_3rd_party(request)
    if JuloUserRoles.BO_FINANCE in role_selected:
        return dashboard_finance(request)
    if JuloUserRoles.PARTNER_FULL in role_selected:
        return dashboard_bo_data_verifier(request)
    if JuloUserRoles.PARTNER_READ_ONLY in role_selected:
        return dashboard_bo_data_verifier(request)
    if JuloUserRoles.CS_TEAM_LEADER in role_selected:
        return dashboard_bo_data_verifier(request)
    if JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_2A in role_selected:
        return collection_agent_partnership_bl_2a(request)
    if JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_2B in role_selected:
        return collection_agent_partnership_bl_2b(request)
    if JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_3A in role_selected:
        return collection_agent_partnership_bl_3a(request)
    if JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_3B in role_selected:
        return collection_agent_partnership_bl_3b(request)
    if JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_4 in role_selected:
        return collection_agent_partnership_bl_4(request)
    if JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_5 in role_selected:
        return collection_agent_partnership_bl_5(request)
    if JuloUserRoles.OPS_TEAM_LEADER in role_selected:
        return dashboard_ops_team_leader(request)
    if role_selected in chain(
        JuloUserRoles.collection_roles(),
        JuloUserRoles.collection_bucket_roles(),
        [
            JuloUserRoles.COLLECTION_SUPERVISOR,
            JuloUserRoles.COLLECTION_TEAM_LEADER,
            JuloUserRoles.COLLECTION_AREA_COORDINATOR,
        ],
    ):
        return all_collection_dashboard(request, role_selected)
    if JuloUserRoles.CHANGE_OF_REPAYMENT_CHANNEL in role_selected:
        return dashboard_change_of_repayment_channel(request)
    if JuloUserRoles.CHANGE_OF_PAYMENT_VISIBILITY in role_selected:
        return dashboard_change_of_payment_visibility(request)
    if JuloUserRoles.BUSINESS_DEVELOPMENT in role_selected:
        return lender_registration(request)
    if JuloUserRoles.PRODUCT_MANAGER in role_selected:
        return dashboard_streamlined_communication(request)
    if JuloUserRoles.COLLECTION_FIELD_AGENT in role_selected:
        return dashboard_agent_field(request)
    if JuloUserRoles.BO_GENERAL_CS in role_selected:
        return dashboard_bo_general_cs(request)
    if SalesOpsRoles.SALES_OPS in role_selected:
        return redirect(reverse("sales_ops.crm:list"))
    if JuloUserRoles.FRAUD_OPS in role_selected:
        return dashboard_fraudops(request)
    if JuloUserRoles.CS_ADMIN in role_selected:
        return dashboard_cs_admin(request)
    if JuloUserRoles.J1_AGENT_ASSISTED_100 in role_selected:
        return dashboard_j1_agent_assisted_100(request)
    return None


@julo_login_required_multigroup(
    JuloUserRoles.collection_roles()
    + JuloUserRoles.collection_bucket_roles()
    + [
        JuloUserRoles.COLLECTION_SUPERVISOR,
        JuloUserRoles.COLLECTION_TEAM_LEADER,
        JuloUserRoles.COLLECTION_AREA_COORDINATOR,
    ]
)
def all_collection_dashboard(request, role_name=''):
    create_or_update_role(request.user, role_name)
    return redirect(reverse('account_payment_status:list', args=('all',)))


@julo_login_required
def no_dashboard_view(request, role=''):
    create_or_update_role(request.user, role)
    return render(request, 'error/no_dashboard.html')


@julo_login_required
@julo_login_required_group(JuloUserRoles.PRODUCT_MANAGER)
def dashboard_streamlined_communication(request):
    role_name = JuloUserRoles.PRODUCT_MANAGER
    create_or_update_role(request.user, role_name)
    return streamlined_communication(request)


@julo_login_required
@julo_login_required_group(JuloUserRoles.BUSINESS_DEVELOPMENT)
def lender_registration(request):
    role_name = JuloUserRoles.BUSINESS_DEVELOPMENT
    create_or_update_role(request.user, role_name)
    url = reverse('lender:registration')
    return redirect(url)


@julo_login_required
@julo_login_required_group(JuloUserRoles.ADMIN_FULL)
def dashboard_admin_full(request):
    role_name = JuloUserRoles.ADMIN_FULL
    create_or_update_role(request.user, role_name)
    return render(request, 'object/dashboard/admin.html', {})


@julo_login_required
@julo_login_required_multigroup(
    [
        JuloUserRoles.BO_DATA_VERIFIER,
        JuloUserRoles.DOCUMENT_VERIFIER,
        JuloUserRoles.ADMIN_READ_ONLY,
        JuloUserRoles.BO_FULL,
        JuloUserRoles.BO_READ_ONLY,
        JuloUserRoles.BO_OUTBOUND_CALLER,
        JuloUserRoles.PARTNER_FULL,
        JuloUserRoles.PARTNER_READ_ONLY,
        JuloUserRoles.CS_TEAM_LEADER,
        JuloUserRoles.SALES_OPS,
    ]
)
def dashboard_bo_data_verifier(request):
    role_name = JuloUserRoles.BO_DATA_VERIFIER
    create_or_update_role(request.user, role_name)
    disbursement_summary_count = DisbursementSummary.objects.filter(disbursement=None).count()
    _status = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
    # print 'payment_dashboard: ', payment_dashboard()
    return render(
        request,
        'object/dashboard/bo_verifier.html',
        {
            'app_dashboard': application_dashboard(),
            'app_priority_dashboard': application_priority_dashboard(),
            'status_color': load_color(),
            'loan_dashboard': loan_dashboard(),
            'payment_dashboard': payment_dashboard(),
            'PROJECT_URL': PROJECT_URL,
            'disbursement_summary_count': disbursement_summary_count,
            'activation_call_change_status': _status,
        },
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.FRAUD_OPS)
def dashboard_fraudops(request):
    role_name = JuloUserRoles.FRAUD_OPS
    create_or_update_role(request.user, role_name)

    return render(
        request,
        'object/dashboard/fraudops.html',
        {
            'app_dashboard': fraudops_dashboard(),
            'status_color': load_color(),
            'PROJECT_URL': PROJECT_URL,
        },
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.BO_CREDIT_ANALYST)
def dashboard_bo_credit_analyst(request):
    role_name = JuloUserRoles.BO_CREDIT_ANALYST
    create_or_update_role(request.user, role_name)
    return render(request, 'object/dashboard/bo_ca.html', {})


@julo_login_required
@julo_login_required_group(JuloUserRoles.BO_SD_VERIFIER)
def dashboard_bo_sd_verifier(request):
    role_name = JuloUserRoles.BO_SD_VERIFIER
    create_or_update_role(request.user, role_name)
    disbursement_summary_count = DisbursementSummary.objects.filter(disbursement=None).count()
    _status = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
    return render(
        request,
        'object/dashboard/bo_sd_verifier_new_bucket.html',
        {
            'app_dashboard': application_dashboard(),
            'app_priority_dashboard': application_priority_dashboard(),
            'loan_dashboard': loan_dashboard(),
            'status_color': load_color(),
            'payment_dashboard': payment_dashboard(),
            'PROJECT_URL': PROJECT_URL,
            'disbursement_summary_count': disbursement_summary_count,
            'role_name': role_name,
            'activation_call_change_status': _status,
        },
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_AGENT_2)
def dashboard_collection_agent_2(request):
    """
    Deprecated
    """
    role_name = JuloUserRoles.COLLECTION_AGENT_2
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_agent.html',
        {
            'app_dashboard': application_dashboard(),
            'app_priority_dashboard': application_priority_dashboard(),
            'loan_dashboard': loan_dashboard(),
            'payment_dashboard': payment_dashboard(),
            'PROJECT_URL': PROJECT_URL,
            'role_name': role_name,
        },
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_AGENT_3)
def dashboard_collection_agent_3(request):
    """
    Deprecated
    """
    role_name = JuloUserRoles.COLLECTION_AGENT_3
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_agent.html',
        {
            'app_dashboard': application_dashboard(),
            'app_priority_dashboard': application_priority_dashboard(),
            'loan_dashboard': loan_dashboard(),
            'payment_dashboard': payment_dashboard(),
            'PROJECT_URL': PROJECT_URL,
            'role_name': role_name,
        },
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_AGENT_4)
def dashboard_collection_agent_4(request):
    """
    Deprecated
    """
    role_name = JuloUserRoles.COLLECTION_AGENT_4
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_agent.html',
        {
            'app_dashboard': application_dashboard(),
            'app_priority_dashboard': application_priority_dashboard(),
            'loan_dashboard': loan_dashboard(),
            'payment_dashboard': payment_dashboard(),
            'PROJECT_URL': PROJECT_URL,
            'role_name': role_name,
        },
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_AGENT_5)
def dashboard_collection_agent_5(request):
    """
    Deprecated
    """
    role_name = JuloUserRoles.COLLECTION_AGENT_5
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_agent.html',
        {
            'app_dashboard': application_dashboard(),
            'app_priority_dashboard': application_priority_dashboard(),
            'loan_dashboard': loan_dashboard(),
            'payment_dashboard': payment_dashboard(),
            'PROJECT_URL': PROJECT_URL,
            'role_name': role_name,
        },
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.BO_FINANCE)
def dashboard_finance(request):
    role_name = JuloUserRoles.BO_FINANCE
    create_or_update_role(request.user, role_name)
    lender_withdrawal_count = LenderWithdrawal.objects.filter(status__in=['requested']).count()
    reversal_trx_count = get_reversal_trx_data(count=True)

    # print 'payment_dashboard: ', payment_dashboard()
    return render(
        request,
        'object/dashboard/bo_finance.html',
        {
            'app_dashboard': application_dashboard(),
            'app_priority_dashboard': application_priority_dashboard(),
            'status_color': load_color(),
            'PROJECT_URL': PROJECT_URL,
            'lender_bucket': lender_bucket(),
            'lender_withdrawal_count': lender_withdrawal_count,
            'reversal_trx_count': reversal_trx_count,
        },
    )


@julo_login_required
@julo_login_required_multigroup(
    [
        JuloUserRoles.COLLECTION_BUCKET_1,
        JuloUserRoles.COLLECTION_SUPERVISOR,
    ]
)
def dashboard_collection_bucket_1(request):
    """
    Deprecated
    """
    role_name = JuloUserRoles.COLLECTION_BUCKET_1
    bucket_type = BucketType.BUCKET_1
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_bucket.html',
        {'role_name': role_name, 'bucket_type': bucket_type},
    )


@julo_login_required
@julo_login_required_multigroup(
    [
        JuloUserRoles.COLLECTION_BUCKET_2,
        JuloUserRoles.COLLECTION_SUPERVISOR,
    ]
)
def dashboard_collection_bucket_2(request):
    """
    Deprecated
    """
    role_name = JuloUserRoles.COLLECTION_BUCKET_2
    bucket_type = BucketType.BUCKET_2
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_bucket.html',
        {'role_name': role_name, 'bucket_type': bucket_type},
    )


@julo_login_required
@julo_login_required_multigroup(
    [
        JuloUserRoles.COLLECTION_BUCKET_3,
        JuloUserRoles.COLLECTION_SUPERVISOR,
    ]
)
def dashboard_collection_bucket_3(request):
    """
    Deprecated
    """
    role_name = JuloUserRoles.COLLECTION_BUCKET_3
    bucket_type = BucketType.BUCKET_3
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_bucket.html',
        {'role_name': role_name, 'bucket_type': bucket_type},
    )


@julo_login_required
@julo_login_required_multigroup(
    [
        JuloUserRoles.COLLECTION_BUCKET_4,
        JuloUserRoles.COLLECTION_SUPERVISOR,
    ]
)
def dashboard_collection_bucket_4(request):
    """
    Deprecated
    """
    role_name = JuloUserRoles.COLLECTION_BUCKET_4
    bucket_type = BucketType.BUCKET_4
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_bucket.html',
        {'role_name': role_name, 'bucket_type': bucket_type},
    )


@julo_login_required
@julo_login_required_multigroup(
    [
        JuloUserRoles.COLLECTION_BUCKET_5,
        JuloUserRoles.COLLECTION_SUPERVISOR,
    ]
)
def dashboard_collection_bucket_5(request):
    """
    Deprecated
    """
    role_name = JuloUserRoles.COLLECTION_BUCKET_5
    bucket_type = BucketType.BUCKET_5
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_bucket.html',
        {'role_name': role_name, 'bucket_type': bucket_type},
    )


@julo_login_required
def dashboard_collection_bucket_1_non_agent(request, role_name):
    bucket_type = BucketType.BUCKET_1
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_bucket.html',
        {'role_name': role_name, 'bucket_type': bucket_type},
    )


@julo_login_required
def dashboard_collection_bucket_2_non_agent(request, role_name):
    bucket_type = BucketType.BUCKET_2
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_bucket.html',
        {'role_name': role_name, 'bucket_type': bucket_type},
    )


@julo_login_required
def dashboard_collection_bucket_3_non_agent(request, role_name):
    bucket_type = BucketType.BUCKET_3
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_bucket.html',
        {'role_name': role_name, 'bucket_type': bucket_type},
    )


@julo_login_required
def dashboard_collection_bucket_4_non_agent(request, role_name):
    bucket_type = BucketType.BUCKET_4
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_bucket.html',
        {'role_name': role_name, 'bucket_type': bucket_type},
    )


@julo_login_required
def dashboard_collection_supervisor_bucket_5(request):
    role_name = JuloUserRoles.COLLECTION_SUPERVISOR
    bucket_type = BucketType.BUCKET_5
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_bucket.html',
        {'role_name': role_name, 'bucket_type': bucket_type},
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_2A)
def collection_agent_partnership_bl_2a(request):
    role_name = JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_2A
    create_or_update_role(request.user, role_name)

    return render(
        request,
        'object/dashboard/collection_agent_bl.html',
        {'PROJECT_URL': PROJECT_URL, 'role_name': role_name},
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_2B)
def collection_agent_partnership_bl_2b(request):
    role_name = JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_2B
    create_or_update_role(request.user, role_name)

    return render(
        request,
        'object/dashboard/collection_agent_bl.html',
        {'PROJECT_URL': PROJECT_URL, 'role_name': role_name},
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_3A)
def collection_agent_partnership_bl_3a(request):
    role_name = JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_3A
    create_or_update_role(request.user, role_name)

    return render(
        request,
        'object/dashboard/collection_agent_bl.html',
        {'PROJECT_URL': PROJECT_URL, 'role_name': role_name},
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_3B)
def collection_agent_partnership_bl_3b(request):
    role_name = JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_3B
    create_or_update_role(request.user, role_name)

    return render(
        request,
        'object/dashboard/collection_agent_bl.html',
        {'PROJECT_URL': PROJECT_URL, 'role_name': role_name},
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_4)
def collection_agent_partnership_bl_4(request):
    role_name = JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_4
    create_or_update_role(request.user, role_name)

    return render(
        request,
        'object/dashboard/collection_agent_bl.html',
        {'PROJECT_URL': PROJECT_URL, 'role_name': role_name},
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_5)
def collection_agent_partnership_bl_5(request):
    role_name = JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_5
    create_or_update_role(request.user, role_name)

    return render(
        request,
        'object/dashboard/collection_agent_bl.html',
        {'PROJECT_URL': PROJECT_URL, 'role_name': role_name},
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_SUPERVISOR)
def dashboard_collection_supervisor(request):
    """
    Deprecated
    """
    role_name = JuloUserRoles.COLLECTION_SUPERVISOR
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/collection_supervisor_new_bucket.html',
        {
            'app_dashboard': application_dashboard(),
            'app_priority_dashboard': application_priority_dashboard(),
            'loan_dashboard': loan_dashboard(),
            'payment_dashboard': payment_dashboard(),
            'PROJECT_URL': PROJECT_URL,
            'role_name': role_name,
        },
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.BO_OUTBOUND_CALLER_3rd_PARTY)
def dashboard_bo_outbound_caller_3rd_party(request):
    role_name = JuloUserRoles.BO_OUTBOUND_CALLER_3rd_PARTY
    create_or_update_role(request.user, role_name)
    # print 'payment_dashboard: ', payment_dashboard()
    return render(
        request,
        'object/dashboard/outbond_caller_3rdparty.html',
        {
            'app_dashboard': application_dashboard(),
            'app_priority_dashboard': application_priority_dashboard(),
            'loan_dashboard': loan_dashboard(),
            'payment_dashboard': payment_dashboard(),
            'PROJECT_URL': PROJECT_URL,
        },
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.JULO_PARTNERS)
class LenderListPage(ListView):
    model = Application
    paginate_by = 50  # get_conf("PAGINATION_ROW")
    template_name = 'object/dashboard/lender_list_page.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        # print "http_method_not_allowed"
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        # print "get_template_names"
        return ListView.get_template_names(self)

    def get_queryset(self):
        # print "status_code: ", self.status_code
        self.qs = super(LenderListPage, self).get_queryset()
        self.is_partner = self.user.groups.filter(name='julo_partners')
        if self.is_partner:
            partner = self.user.username
            if partner in ['jtp', 'jtf']:
                partner = None
            self.qs = self.qs.filter(
                application_status__status_code=self.status_code, partner__name=partner
            )
        else:
            self.qs = self.qs.filter(application_status__status_code=self.status_code)

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
                crm_url=Value('%s/applications/' % settings.CRM_BASE_URL, output_field=CharField())
            )

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(
                    reduce(
                        operator.or_,
                        [
                            Q(**{('%s__icontains' % 'fullname'): self.search_q}),
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
                # print "OKAY STATUS NOW : ", self.status_now
                if self.status_now == 'True':
                    # print "HARI INI"
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
                        # print "BEBAS"
                        if _tgl_end > _tgl_mulai:
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.err_message_here = "Format Tanggal tidak valid"

            if self.sort_q:
                if self.sort_q == 'disbursementDate':
                    self.qs = self.qs.annotate(Max('loan__disbursement__cdate')).order_by(
                        'loan__disbursement__cdate__max'
                    )
                elif self.sort_q == '-disbursementDate':
                    self.qs = self.qs.annotate(Max('loan__disbursement__cdate')).order_by(
                        '-loan__disbursement__cdate__max'
                    )
                else:
                    self.qs = self.qs.order_by(self.sort_q)

        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(LenderListPage, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = ApplicationSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = ApplicationSearchForm()

        # to check field application.product_line.product_line_code
        product_line_STL = (ProductLineCodes.STL1, ProductLineCodes.STL2)

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        # print "parameters: ", parameters
        context['parameters'] = parameters
        context['product_line_STL'] = product_line_STL
        context['is_partner'] = self.is_partner
        context['login_username'] = self.user.username
        return context

    def get(self, request, *args, **kwargs):
        self.courtesy_call = False
        self.user = request.user
        self.status_code = ApplicationStatusCodes.LENDER_APPROVAL
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super(LenderListPage, self).render_to_response(context, **response_kwargs)
        return rend_here


@julo_login_required
def update_default_role(request):
    # print "update_default_role Inside"
    try:
        obj_default_role = CRMSetting.objects.get(user=request.user)
    except CRMSetting.DoesNotExists:
        obj_default_role = CRMSetting(user=request.user)

    if request.method == 'POST':
        form = DefaultRoleForm(request.user, request.POST)
        if form.is_valid():
            # print form.cleaned_data['role_default']
            current_role = form.cleaned_data['role_default']
            form.save()

            return render(
                request,
                'object/dashboard/create_defaultrole.html',
                {'form': form, 'current_role': current_role, 'msg_title': 'Sukses '},
            )
    else:
        form = DefaultRoleForm(request.user)

    return render(
        request,
        'object/dashboard/create_defaultrole.html',
        {'form': form, 'current_role': obj_default_role.role_default, 'msg_title': 'Konfirmasi '},
    )


@julo_login_required
def update_user_extension(request):

    agent = Agent.objects.get_or_none(user=request.user)
    if not agent:
        agent = Agent.objects.create(user=request.user)

    quiros_profile = QuirosProfile.objects.get_or_none(agent=agent)
    quiros_username = quiros_profile.username if quiros_profile is not None else None
    quiros_password = quiros_profile.password if quiros_profile is not None else None

    return render(
        request,
        'object/dashboard/create_userextension.html',
        {
            'current_user_extension': agent.user_extension,
            'quiros_username': quiros_username,
            'quiros_password': quiros_password,
            'msg_title': 'Agent Settings',
        },
    )


@julo_login_required
def autodialer(request):
    agent = Agent.objects.get_or_none(user=request.user)
    if not agent:
        agent = Agent.objects.create(user=request.user)

    return render(
        request,
        'object/dashboard/autodialer.html',
        {
            'current_user_extension': agent.user_extension,
            'app_dashboard': application_dashboard(),
        },
    )


def ajax_update_user_extension(request):

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    user = request.user
    agent = Agent.objects.get_or_none(user=user)

    if agent is None:
        agent = Agent.objects.create(user=user)

    if 'user_extension' in data:
        agent.user_extension = data.get('user_extension')
        agent.save()

    if 'quiros_username' in data and 'quiros_password' in data:

        # For the API username, Quiros append "@julofinance" at the end. This
        # block is added so that agent does not need to remember to add it.
        api_username_suffix = '@julofinance'
        if not data['quiros_username'].endswith(api_username_suffix):
            data['quiros_username'] += api_username_suffix

        autodial_client = get_autodial_client()
        try:
            token = autodial_client.login(data['quiros_username'], data['quiros_password'])
        except QuirosApiError as qae:
            return JsonResponse(
                {
                    "status": "failed",
                    "message": str(qae),
                }
            )
        time_now = timezone.now()

        quiros_profile = QuirosProfile.objects.get_or_none(agent=agent)
        if quiros_profile is None:
            quiros_profile = QuirosProfile.objects.create(
                agent=agent, current_token=token, last_login_time=time_now
            )
        quiros_profile.username = data['quiros_username']
        quiros_profile.password = data['quiros_password']
        quiros_profile.save()

    return JsonResponse({"status": "success", "messages": "successfully updated settings"})


@julo_login_required
def get_dashboard_bucket_count(request):

    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    return JsonResponse(
        {
            "status": "success",
            'app_priority_dashboard': application_priority_dashboard(),
            'app_dashboard': application_dashboard(),
            'loan_dashboard': loan_dashboard(),
            'payment_dashboard': {},  # This is kept for backward compatibility in FE
        }
    )


@julo_login_required
def get_fraudops_dashboard_bucket_count(request):

    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    return JsonResponse(
        {
            "status": "success",
            'app_dashboard': fraudops_dashboard(),
            'payment_dashboard': {},  # This is kept for backward compatibility in FE
        }
    )


def get_collection_agent_bucket(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])
    user = request.user
    agent_service = get_agent_service()
    qs = Payment.objects.normal()
    list_bucket = {}
    list_bucket['T1to4'] = agent_service.filter_payments_by_agent_and_type(
        qs.overdue_group_plus_with_range(1, 4), user, DPD1_DPD29
    ).count()
    list_bucket['T5to15'] = agent_service.filter_payments_by_agent_and_type(
        qs.overdue_group_plus_with_range(5, 15), user, DPD1_DPD29
    ).count()
    list_bucket['T16to29'] = agent_service.filter_payments_by_agent_and_type(
        qs.overdue_group_plus_with_range(16, 29), user, DPD1_DPD29
    ).count()
    list_bucket['T30to44'] = agent_service.filter_payments_by_agent_and_type(
        qs.overdue_group_plus_with_range(30, 44), user, DPD30_DPD59
    ).count()
    list_bucket['T45to59'] = agent_service.filter_payments_by_agent_and_type(
        qs.overdue_group_plus_with_range(45, 59), user, DPD30_DPD59
    ).count()
    list_bucket['T60to74'] = agent_service.filter_payments_by_agent_and_type(
        qs.overdue_group_plus_with_range(60, 74), user, DPD60_DPD89
    ).count()
    list_bucket['T75to89'] = agent_service.filter_payments_by_agent_and_type(
        qs.overdue_group_plus_with_range(75, 89), user, DPD60_DPD89
    ).count()
    list_bucket['T90to119'] = agent_service.filter_payments_by_agent_and_type(
        qs.overdue_group_plus_with_range(90, 119), user, DPD90PLUS
    ).count()
    list_bucket['T120to179'] = agent_service.filter_payments_by_agent_and_type(
        qs.overdue_group_plus_with_range(120, 179), user, DPD90PLUS
    ).count()
    list_bucket['Tplus180'] = agent_service.filter_payments_by_agent_and_type(
        qs.overdue_group_plus180(), user, DPD90PLUS
    ).count()
    list_bucket['PTPagent2'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=False, ptp_date__isnull=False), user, DPD1_DPD29
    ).count()
    list_bucket['PTPagent3'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=False, ptp_date__isnull=False), user, DPD30_DPD59
    ).count()
    list_bucket['PTPagent4'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=False, ptp_date__isnull=False), user, DPD60_DPD89
    ).count()
    list_bucket['PTPagent5'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=False, ptp_date__isnull=False), user, DPD90PLUS
    ).count()
    list_bucket['IgnoreCalledAgent3'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=True), user, DPD30_DPD59
    ).count()
    list_bucket['IgnoreCalledAgent4'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=True), user, DPD60_DPD89
    ).count()
    list_bucket['IgnoreCalledAgent5'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=True), user, DPD90PLUS
    ).count()
    list_bucket['WhatsappAgent2'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=False, is_whatsapp=True), user, DPD1_DPD29
    ).count()
    list_bucket['WhatsappAgent3'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=False, is_whatsapp=True), user, DPD30_DPD59
    ).count()
    list_bucket['WhatsappAgent4'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=False, is_whatsapp=True), user, DPD60_DPD89
    ).count()
    list_bucket['WhatsappAgent5'] = agent_service.filter_payments_by_agent_and_type(
        qs.filter(loan__is_ignore_calls=False, is_whatsapp=True), user, DPD90PLUS
    ).count()
    return JsonResponse(
        {
            "status": "success",
            'payment_dashboard': list_bucket,
        }
    )


@julo_login_required
def get_collection_agent_bl_bucket(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed["GET"]

    list_bucket = {}
    bl_statement_query = Statement.objects
    list_bucket['bl_T0'] = bl_statement_query.bucket_list_t0().count()
    list_bucket['bl_T1toT5'] = bl_statement_query.bucket_list_t1_to_t5().count()
    list_bucket['bl_T6toT14'] = bl_statement_query.bucket_list_t6_to_t14().count()
    list_bucket['bl_T15toT29'] = bl_statement_query.bucket_list_t15_to_t29().count()
    list_bucket['bl_T30toT44'] = bl_statement_query.bucket_list_t30_to_t44().count()
    list_bucket['bl_T45toT59'] = bl_statement_query.bucket_list_t45_to_t59().count()
    list_bucket['bl_T60toT89'] = bl_statement_query.bucket_list_t60_to_t89().count()
    list_bucket['bl_T90plus'] = bl_statement_query.bucket_list_t90plus().count()

    return JsonResponse(
        {
            "status": "success",
            'data': list_bucket,
        }
    )


def get_collection_bucket_v2(request):
    """
    Deprecated
    """
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    role_name = request.GET.get('role_name')
    squad = request.user.agent.squad
    agent_id = request.user.id
    collection_bucket_role = [
        JuloUserRoles.COLLECTION_BUCKET_2,
        JuloUserRoles.COLLECTION_BUCKET_3,
        JuloUserRoles.COLLECTION_BUCKET_4,
    ]
    if role_name in collection_bucket_role and squad is None:
        return JsonResponse(
            {
                "status": "failed",
                "message": "squad undefined",
            }
        )

    bucket_type = request.GET.get('bucket_type')
    get_agent_service_for_bucket()
    qs = Payment.objects.normal().exclude(is_restructured=True)
    list_bucket = {}

    if role_name == JuloUserRoles.COLLECTION_BUCKET_1:
        oldest_payment_ids = get_oldest_payment_ids_loans()

        tminus5_payments = qs.bucket_1_t_minus_5([])
        tminus5_payments = tminus5_payments.filter(id__in=oldest_payment_ids)
        tminus3_payments = qs.bucket_1_t_minus_3([])
        tminus3_payments = tminus3_payments.filter(id__in=oldest_payment_ids)
        t1to4_payments = qs.bucket_1_t1_t4([])
        t1to4_payments = t1to4_payments.filter(id__in=oldest_payment_ids)
        t5to10_payments = qs.bucket_1_t5_t10([])
        t5to10_payments = t5to10_payments.filter(id__in=oldest_payment_ids)
        ptp_payments = qs.bucket_1_ptp([])
        ptp_payments = ptp_payments.filter(id__in=oldest_payment_ids)
        wa_payments = qs.bucket_1_wa([])
        wa_payments = wa_payments.filter(id__in=oldest_payment_ids)
        tminus1_payments = qs.bucket_cootek([], True, 1)
        tminus1_payments = tminus1_payments.filter(id__in=oldest_payment_ids)
        t0_payments = qs.bucket_cootek([], True, 0)
        t0_payments = t0_payments.filter(id__in=oldest_payment_ids)

        list_bucket['Tminus5'] = tminus5_payments.count()
        list_bucket['Tminus3'] = tminus3_payments.count()
        list_bucket['T1to4'] = t1to4_payments.count()
        list_bucket['T5to10'] = t5to10_payments.count()
        list_bucket['PTP'] = ptp_payments.count()
        list_bucket['WA'] = wa_payments.count()
        list_bucket['Tminus1'] = check_cootek_experiment(tminus1_payments, -1).count()
        list_bucket['T0'] = check_cootek_experiment(t0_payments, 0).count()
    elif role_name == JuloUserRoles.COLLECTION_BUCKET_2:
        list_bucket['T11to25'] = CollectionHistory.objects.get_bucket_t11_to_t25(squad.id).count()
        list_bucket['T26to40'] = CollectionHistory.objects.get_bucket_t26_to_t40(squad.id).count()
        list_bucket['PTP'] = CollectionHistory.objects.get_bucket_ptp(squad.id, agent_id).count()
        list_bucket['WA'] = CollectionHistory.objects.get_bucket_wa(squad.id).count()
    elif role_name == JuloUserRoles.COLLECTION_BUCKET_3:
        list_bucket['T41to55'] = CollectionHistory.objects.get_bucket_t41_to_t55(squad.id).count()
        list_bucket['T56to70'] = CollectionHistory.objects.get_bucket_t56_to_t70(squad.id).count()
        list_bucket['PTP'] = CollectionHistory.objects.get_bucket_ptp(squad.id, agent_id).count()
        list_bucket['WA'] = CollectionHistory.objects.get_bucket_wa(squad.id).count()
    elif role_name == JuloUserRoles.COLLECTION_BUCKET_4:
        list_bucket['T71to85'] = CollectionHistory.objects.get_bucket_t71_to_t85(
            squad.id, agent_id
        ).count()
        list_bucket['T86to100'] = CollectionHistory.objects.get_bucket_t86_to_t100(
            squad.id, agent_id
        ).count()
        list_bucket['PTP'] = CollectionHistory.objects.get_bucket_ptp(squad.id, agent_id).count()
        list_bucket['WA'] = CollectionHistory.objects.get_bucket_wa(squad.id).count()
    elif role_name == JuloUserRoles.COLLECTION_BUCKET_5:
        oldest_payment_ids = get_oldest_payment_ids_loans()

        bucket5_payments = qs.bucket_5_list()
        bucket5_payments = bucket5_payments.filter(id__in=oldest_payment_ids)
        ptp_payments = qs.list_bucket_5_group_ptp_only()
        ptp_payments = ptp_payments.filter(id__in=oldest_payment_ids)
        wa_payments = qs.list_bucket_5_group_wa_only()
        wa_payments = wa_payments.filter(id__in=oldest_payment_ids)

        list_bucket['T101plus'] = bucket5_payments.count()
        list_bucket['PTP'] = ptp_payments.count()
        list_bucket['WA'] = wa_payments.count()
    else:
        if role_name == JuloUserRoles.COLLECTION_SUPERVISOR:
            qs = Payment.objects.normal()
        else:
            # bo sd verifier
            qs = (
                Payment.objects.select_related(
                    'loan', 'loan__application', 'loan__application__partner'
                )
                .exclude(loan__application__partner__name__in=PartnerConstant.form_partner())
                .normal()
            )

        # Get non contact payment ids
        non_contact_payment_ids = CollectionHistory.objects.filter(
            excluded_from_bucket=True
        ).values_list('payment_id', flat=True)

        if bucket_type == BucketType.BUCKET_1:
            ptp_count = qs.list_bucket_1_group_ptp_only().count()
            wa_count = qs.list_bucket_1_group_wa_only().count()

            # Bucket T-5 - T+10
            list_bucket['Tminus5'] = qs.dpd_groups_minus5().count()
            list_bucket['Tminus3'] = qs.dpd_groups_minus3().count()
            list_bucket['Tminus1'] = check_cootek_experiment(
                qs.dpd_groups_minus1(exclude_stl=True), -1
            ).count()
            list_bucket['T0'] = check_cootek_experiment(qs.due_group0(), 0).count()
            list_bucket['T1to4'] = qs.bucket_list_t1_to_t4().count()
            list_bucket['T5to10'] = qs.bucket_list_t5_to_t10().count()
        elif bucket_type == BucketType.BUCKET_2:
            ptp_count = qs.list_bucket_2_group_ptp_only().count()
            wa_count = qs.list_bucket_2_group_wa_only().count()
            vendor_loan_ids = CollectionAgentTask.objects.get_bucket_2_vendor().values_list(
                'loan_id', flat=True
            )
            excluded_bucket_loan_ids = (
                SkiptraceHistory.objects.get_non_contact_bucket2().values_list('loan_id', flat=True)
            )
            # Bucket T+11 - T+40
            list_bucket['T11to25'] = (
                qs.bucket_list_t11_to_t25()
                .exclude(pk__in=non_contact_payment_ids)
                .exclude(loan_id__in=vendor_loan_ids)
                .exclude(loan_id__in=excluded_bucket_loan_ids)
                .count()
            )
            list_bucket['T26to40'] = (
                qs.bucket_list_t26_to_t40()
                .exclude(pk__in=non_contact_payment_ids)
                .exclude(loan_id__in=vendor_loan_ids)
                .exclude(loan_id__in=excluded_bucket_loan_ids)
                .count()
            )

            # Non contact bucket 2
            b2_squad_ids = CollectionSquad.objects.filter(
                group__name=JuloUserRoles.COLLECTION_BUCKET_2
            ).values_list('id', flat=True)
            list_bucket['NonContactsS2'] = CollectionHistory.objects.get_bucket_non_contact_squads(
                b2_squad_ids
            ).count()

            # Bucket 2 vendor
            list_bucket['VendorB2'] = (
                qs.bucket_list_t11_to_t40().filter(loan_id__in=vendor_loan_ids).count()
            )
            list_bucket['NonContactsB2'] = excluded_bucket_loan_ids.count()
        elif bucket_type == BucketType.BUCKET_3:
            ptp_count = qs.list_bucket_3_group_ptp_only().count()
            wa_count = qs.list_bucket_3_group_wa_only().count()
            vendor_loan_ids = CollectionAgentTask.objects.get_bucket_3_vendor().values_list(
                'loan_id', flat=True
            )
            excluded_bucket_loan_ids = (
                SkiptraceHistory.objects.get_non_contact_bucket3().values_list('loan_id', flat=True)
            )
            # Bucket T+41 - T+70
            list_bucket['T41to55'] = (
                qs.bucket_list_t41_to_t55()
                .exclude(pk__in=non_contact_payment_ids)
                .exclude(loan_id__in=vendor_loan_ids)
                .exclude(loan_id__in=excluded_bucket_loan_ids)
                .count()
            )
            list_bucket['T56to70'] = (
                qs.bucket_list_t56_to_t70()
                .exclude(pk__in=non_contact_payment_ids)
                .exclude(loan_id__in=vendor_loan_ids)
                .exclude(loan_id__in=excluded_bucket_loan_ids)
                .count()
            )

            # Non contact bucket 3
            b3_squad_ids = CollectionSquad.objects.filter(
                group__name=JuloUserRoles.COLLECTION_BUCKET_3
            ).values_list('id', flat=True)
            list_bucket['NonContactsS3'] = CollectionHistory.objects.get_bucket_non_contact_squads(
                b3_squad_ids
            ).count()

            # Bucket 3 vendor
            list_bucket['VendorB3'] = (
                qs.bucket_list_t41_to_t70().filter(loan_id__in=vendor_loan_ids).count()
            )
            list_bucket['NonContactsB3'] = excluded_bucket_loan_ids.count()
        elif bucket_type == BucketType.BUCKET_4:
            ptp_count = qs.list_bucket_4_group_ptp_only().count()
            wa_count = qs.list_bucket_4_group_wa_only().count()
            vendor_loan_ids = CollectionAgentTask.objects.get_bucket_4_vendor().values_list(
                'loan_id', flat=True
            )
            excluded_bucket_loan_ids = (
                SkiptraceHistory.objects.get_non_contact_bucket4().values_list('loan_id', flat=True)
            )
            # Bucket T+71 - T+100
            list_bucket['T71to85'] = (
                qs.bucket_list_t71_to_t85()
                .exclude(pk__in=non_contact_payment_ids)
                .exclude(loan_id__in=vendor_loan_ids)
                .exclude(loan_id__in=excluded_bucket_loan_ids)
                .count()
            )
            list_bucket['T86to100'] = (
                qs.bucket_list_t86_to_t100()
                .exclude(pk__in=non_contact_payment_ids)
                .exclude(loan_id__in=vendor_loan_ids)
                .exclude(loan_id__in=excluded_bucket_loan_ids)
                .count()
            )

            # Non contact bucket 4
            b4_squad_ids = CollectionSquad.objects.filter(
                group__name=JuloUserRoles.COLLECTION_BUCKET_4
            ).values_list('id', flat=True)
            list_bucket['NonContactsS4'] = CollectionHistory.objects.get_bucket_non_contact_squads(
                b4_squad_ids
            ).count()

            # Bucket 4 vendor
            list_bucket['VendorB4'] = (
                qs.bucket_list_t71_to_t90().filter(loan_id__in=vendor_loan_ids).count()
            )
            list_bucket['NonContactsB4'] = excluded_bucket_loan_ids.count()
        elif bucket_type == BucketType.BUCKET_5:
            ptp_count = qs.list_bucket_5_group_ptp_only().count()
            wa_count = qs.list_bucket_5_group_wa_only().count()

        list_bucket['PTP'] = ptp_count
        list_bucket['WA'] = wa_count

    return JsonResponse(
        {
            "status": "success",
            'data': list_bucket,
        }
    )


def get_collection_supervisor_bucket(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])
    payment_query = Payment.objects.normal()
    list_bucket = {}
    list_bucket['Tminus_5_3_1'] = payment_query.dpd_groups_minus5and3and1().count()
    list_bucket['T0'] = payment_query.due_group0().count()
    list_bucket['T1to4'] = payment_query.overdue_group_plus_with_range(1, 4).count()
    list_bucket['T5to15'] = payment_query.overdue_group_plus_with_range(5, 15).count()
    list_bucket['T16to29'] = payment_query.overdue_group_plus_with_range(16, 29).count()
    list_bucket['T30to44'] = payment_query.overdue_group_plus_with_range(30, 44).count()
    list_bucket['T45to59'] = payment_query.overdue_group_plus_with_range(45, 59).count()
    list_bucket['T60to74'] = payment_query.overdue_group_plus_with_range(60, 74).count()
    list_bucket['T75to89'] = payment_query.overdue_group_plus_with_range(75, 89).count()
    list_bucket['T90to119'] = payment_query.overdue_group_plus_with_range(90, 119).count()
    list_bucket['T120to179'] = payment_query.overdue_group_plus_with_range(120, 179).count()
    list_bucket['Tplus180'] = payment_query.overdue_group_plus180().count()
    list_bucket['PTP'] = payment_query.filter(ptp_date__isnull=False).count()
    list_bucket['IgnoreCalled'] = payment_query.filter(loan__is_ignore_calls=True).count()
    list_bucket['whatsapp_supervisor'] = payment_query.filter(is_whatsapp=True).count()

    # BukaLapak partner buckets
    bl_statement_query = Statement.objects
    list_bucket['bl_T0'] = bl_statement_query.bucket_list_t0().count()
    list_bucket['bl_T1toT5'] = bl_statement_query.bucket_list_t1_to_t5().count()
    list_bucket['bl_T6toT14'] = bl_statement_query.bucket_list_t6_to_t14().count()
    list_bucket['bl_T15toDpd29'] = bl_statement_query.bucket_list_t15_to_t29().count()
    list_bucket['bl_T30toT44'] = bl_statement_query.bucket_list_t30_to_t44().count()
    list_bucket['bl_T45toT59'] = bl_statement_query.bucket_list_t45_to_t59().count()
    list_bucket['bl_T60toT89'] = bl_statement_query.bucket_list_t60_to_t89().count()
    list_bucket['bl_T90plus'] = bl_statement_query.bucket_list_t90plus().count()

    return JsonResponse(
        {
            "status": "success",
            'payment_dashboard': list_bucket,
        }
    )


@julo_login_required
def get_collection_supervisor_new_bucket(request):
    """
    Deprecated
    """
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])
    payment_query = Payment.objects.normal()
    list_bucket = {}

    list_bucket['bucket_1'] = payment_query.bucket_1_list().count()
    list_bucket['bucket_2'] = payment_query.bucket_2_list().count()
    list_bucket['bucket_3'] = payment_query.bucket_3_list().count()
    list_bucket['bucket_4'] = payment_query.bucket_4_list().count()
    redisClient = get_redis_client()
    cached_oldest_payment_ids = redisClient.get_list(RedisKey.OLDEST_PAYMENT_IDS)
    if not cached_oldest_payment_ids:
        oldest_payment_ids = get_oldest_payment_ids_loans()
    else:
        oldest_payment_ids = list(map(int, cached_oldest_payment_ids))

    list_bucket['bucket_5'] = (
        payment_query.bucket_5_list().filter(id__in=oldest_payment_ids).count()
    )
    list_bucket['PTP'] = payment_query.bucket_ptp().count()
    list_bucket['whatsapp_supervisor'] = payment_query.bucket_whatsapp().count()

    # BukaLapak partner buckets
    bl_statement_query = Statement.objects
    list_bucket['bl_T0'] = bl_statement_query.bucket_list_t0().count()
    list_bucket['bl_T1toT5'] = bl_statement_query.bucket_list_t1_to_t5().count()
    list_bucket['bl_T6toT14'] = bl_statement_query.bucket_list_t6_to_t14().count()
    list_bucket['bl_T15toDpd29'] = bl_statement_query.bucket_list_t15_to_t29().count()
    list_bucket['bl_T30toT44'] = bl_statement_query.bucket_list_t30_to_t44().count()
    list_bucket['bl_T45toT59'] = bl_statement_query.bucket_list_t45_to_t59().count()
    list_bucket['bl_T60toT89'] = bl_statement_query.bucket_list_t60_to_t89().count()
    list_bucket['bl_T90plus'] = bl_statement_query.bucket_list_t90plus().count()

    return JsonResponse(
        {
            "status": "success",
            'payment_dashboard': list_bucket,
        }
    )


@julo_login_required
def get_loc_collection_agent_bucket(request):
    """
    Deprecated
    """
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])
    # user = request.user
    loc_col_service = LocCollectionService()
    keys = ['Tmin1', 'T0', 'T1to30', 'Tplus30']
    list_bucket = {}
    for key in keys:
        list_bucket[key] = loc_col_service.get_bucket_count(key)

    return JsonResponse(
        {
            "status": "success",
            'loc_payment_dashboard': list_bucket,
        }
    )


# AJAX AUTODIALER #
def ajax_unlock_autodialer_agent(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    agent = Agent.objects.get_or_none(user=request.user)
    if not agent:
        agent = Agent.objects.create(user=request.user)

    if agent.is_autodialer_online:
        agent.is_autodialer_online = False
        agent.save()
        return JsonResponse({"status": "success", "messages": "successfully unlock autodialer"})

    return JsonResponse({"status": "failed", "messages": "autodialer already unlocked"})


# this is old ajax to get application before move to autofialer_session attach to application
def ajax_get_application_autodialer_old(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    data = request.GET.get('options')
    # condition prefix 1000 for collection
    if not str(data)[:4] == "1000":
        status = int(data)
        recalled_status = (122, 124, 138, 140, 141, 160, 172)
        subjects = {
            122: "PV EMPLOYER",
            124: "PV APPLICANT",
            138: "PV EMPLOYER",
            140: "FOLLOW UP",
            141: "ACTIVATION CALL",
            160: "FOLLOW UP",
            180: "COURTESY CALL",
            172: "ACTIVATION CALL",
        }

        session_delay = {122: 0, 124: 0, 138: 0, 140: 0, 141: 0, 160: 0, 180: 0, 172: 0}

        locked_list = app_lock_list()
        # if status = 122 get autodialer for nexmo filter
        app122queue = None
        feature = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.AUTO_CALL_PING_122
        )
        if feature:
            if feature.is_active:
                if status == 122:
                    app122queue = Autodialer122Queue.objects.get_uncalled_app().values_list(
                        'application_id', flat=True
                    )

        # get uncalled application first
        application = ApplicationHistory.objects.autodialer_uncalled_app(
            status, locked_list, app122queue
        )

        # this application has been called but has no hashtag
        if not application and (status in recalled_status):
            application = Application.objects.autodialer_priority_recalled(
                status, locked_list, app122queue
            )

        # this application has been called an has a hashtag
        if not application and (status in recalled_status):
            application = Application.objects.autodialer_recalled(status, locked_list, app122queue)

        if application:
            phone = choose_number(app_obj=application)
            return JsonResponse(
                {
                    "status": "success",
                    "message": "success get applicant",
                    "object_id": application.id,
                    "object_name": application.first_name_with_title,
                    "object_type": "application",
                    "email": application.email,
                    "subject": subjects[status],
                    "telphone": phone,
                    "session_delay": session_delay[status],
                }
            )

        return JsonResponse(
            {
                "status": "failed",
                "message": "tidak ada aplikasi yang tersedia",
            }
        )
    # section for collections
    else:
        status = int(str(data).replace(str(data)[:4], ""))
        subject = "COLLECTION CALL"

        session_delay = {0: 0, 531: 0}

        locked_list = payment_lock_list()

        # get uncalled application first
        payment = Payment.objects.autodialer_uncalled_payment(status, locked_list)

        # this application has been called but has no hashtag
        if not payment and status == 0:
            payment = Payment.objects.autodialer_recalled_payment(status, locked_list)

        if payment:
            collections_t0 = True if status == 0 else False
            application = payment.loan.application
            phone = choose_number(app_obj=application, collections_t0=collections_t0)
            return JsonResponse(
                {
                    "status": "success",
                    "message": "success get applicant",
                    "object_id": payment.id,
                    "object_name": application.first_name_with_title,
                    "object_type": "payment",
                    "email": application.email,
                    "subject": subject,
                    "telphone": phone,
                    "session_delay": session_delay[status],
                }
            )

        return JsonResponse(
            {
                "status": "failed",
                "message": "tidak ada payment yang tersedia",
            }
        )


# currently using this method to get application autodialer
def ajax_get_application_autodialer(request):

    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    data = request.GET.get('options')

    is_julo_one = None
    app_status_julo_one = (124, 141)
    if '.' in data:
        data = data.split('.')[0]
        is_julo_one = True

    if not is_julo_one and data.isdigit() and int(data) in app_status_julo_one:
        is_julo_one = False

    if sales_ops_autodialer_services.is_sales_ops_autodialer_option(data):
        return sales_ops_crm_views.ajax_get_application_autodialer(request)
    # Normal PV call x100-x190 queue
    elif str(data)[:4] != "1000":
        status = int(data)
        subjects = {
            122: "PV EMPLOYER",
            124: "PV APPLICANT",
            138: "PV EMPLOYER",
            140: "FOLLOW UP",
            141: "ACTIVATION CALL",
            160: "FOLLOW UP",
            180: "COURTESY CALL",
            172: "ACTIVATION CALL",
        }
        session_delay = {122: 0, 124: 0, 138: 0, 140: 0, 141: 0, 160: 0, 180: 0, 172: 0}

        locked_list = app_lock_list()

        # Predictive missed call flag
        is_pmc = False
        feature122_qs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AUTO_CALL_PING_122, is_active=True
        )
        feature_pred_missed_call_qs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.PREDICTIVE_MISSED_CALL, is_active=True
        )
        if status == 122 and feature122_qs.exists():
            is_pmc = True
        elif (
            status
            in chain(PredictiveMissedCall().moved_statuses, PredictiveMissedCall().unmoved_statuses)
            and feature_pred_missed_call_qs.exists()
        ):
            is_pmc = True

        # Get recalled application
        application = Application.objects.autodialer_recalled(
            status, locked_list=locked_list, is_julo_one=is_julo_one, is_pmc=is_pmc
        )

        # Get uncalled application
        if not application:
            application = Application.objects.autodialer_uncalled_app(
                status, locked_list=locked_list, is_julo_one=is_julo_one, is_pmc=is_pmc
            )

        # Get next recalled application
        autodialer_logic_qs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AUTODIALER_LOGIC, is_active=True
        )
        if not application and autodialer_logic_qs.exists():
            application = Application.objects.autodialer_recalled(
                status,
                locked_list=locked_list,
                is_julo_one=is_julo_one,
                is_pmc=is_pmc,
                is_fast_forward=True,
            )

        # Set logic flag for UI
        logic_flag = 'blue'
        if autodialer_logic_qs.exists():
            logic_flag = 'green'

        if application:
            bank_name_validation_status = 'Belum Tersedia'
            if application.name_bank_validation:
                bank_name_validation_status = application.name_bank_validation.validation_status

            phone = choose_number(app_obj=application)
            return JsonResponse(
                {
                    "status": "success",
                    "message": "success get applicant",
                    "object_id": application.id,
                    "object_name": application.first_name_with_title,
                    "object_type": "application",
                    "email": application.email,
                    "subject": subjects[status],
                    "telphone": phone,
                    "session_delay": session_delay[status],
                    "logic_flag": logic_flag,
                    "bank_name_status": bank_name_validation_status,
                }
            )

        return JsonResponse(
            {
                "status": "failed",
                "message": "tidak ada aplikasi yang tersedia",
            }
        )
    # section for collections
    else:
        status = int(str(data).replace(str(data)[:4], ""))
        subject = "COLLECTION CALL"

        session_delay = {0: 0, 531: 0}

        locked_list = payment_lock_list()

        # get uncalled application first
        payment = Payment.objects.autodialer_uncalled_payment(status, locked_list)

        # this application has been called but has no hashtag
        if not payment and status == 0:
            payment = Payment.objects.autodialer_recalled_payment(status, locked_list)

        if payment:
            collections_t0 = True if status == 0 else False
            application = payment.loan.application
            phone = choose_number(app_obj=application, collections_t0=collections_t0)
            return JsonResponse(
                {
                    "status": "success",
                    "message": "success get applicant",
                    "object_id": payment.id,
                    "object_name": application.first_name_with_title,
                    "object_type": "payment",
                    "email": application.email,
                    "subject": subject,
                    "telphone": phone,
                    "session_delay": session_delay[status],
                }
            )

        return JsonResponse(
            {
                "status": "failed",
                "message": "tidak ada payment yang tersedia",
            }
        )


def ajax_autodialer_agent_status(request):
    """
    @param request: agent_status ---> set to "start" when agent start autodialer,
    and set "stop" for stoping
    """

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    data = request.POST.dict()
    user = request.user
    status = data['agent_status']
    agent = Agent.objects.get_or_none(user=user)

    agent_online = agent.is_autodialer_online
    if agent_online:
        if status == "stop":
            agent.is_autodialer_online = False
            agent.save()
            return JsonResponse(
                {"status": "success", "messages": "successfully updated agent status"}
            )

        if status == "start":
            return JsonResponse({"status": "failed", "message": "agent already started autodialer"})
    else:
        if status == "start":
            agent.is_autodialer_online = True
            agent.save()
            return JsonResponse(
                {"status": "success", "messages": "successfully updated agent status"}
            )

        if status == "stop":
            return JsonResponse({"status": "failed", "message": "agent already stoped autodialer"})


def ajax_autodialer_history_record_old(request):
    """

    @param request: object_id ---> application_id or payment_id
                    action ---> string of agent activity
                    object_type  --> 'application' or 'payment'

    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    user = request.user

    data = request.POST.dict()
    if data.get('object_type') == 'application':
        application = Application.objects.get_or_none(pk=int(data['object_id']))
        if application:
            app_history = ApplicationHistory.objects.filter(
                application=application, status_new=application.application_status_id
            ).last()
            if not hasattr(app_history, 'autodialersessionstatus'):
                app_history = ApplicationHistory.objects.filter(application=application).order_by(
                    '-id'
                )[1]

            autodialer_status = app_history.autodialersessionstatus

            AutodialerActivityHistory.objects.create(
                autodialer_session_status=autodialer_status, action=data.get('action'), agent=user
            )
            return JsonResponse(
                {"status": "success", "message": "berhasil rekam autodialer activity history"}
            )
        else:
            return JsonResponse({"status": "failed", "message": "application not found"})
    else:
        payment = Payment.objects.get_or_none(pk=int(data['object_id']))
        if payment:
            payment_autodialer_session = PaymentAutodialerSession.objects.filter(
                payment=payment
            ).last()

            PaymentAutodialerActivity.objects.create(
                payment_autodialer_session=payment_autodialer_session,
                action=data.get('action'),
                agent=user,
            )
            return JsonResponse(
                {"status": "success", "message": "berhasil rekam autodialer activity history"}
            )
        else:
            return JsonResponse({"status": "failed", "message": "payment not found"})


def ajax_autodialer_history_record(request):
    """

    @param request: object_id ---> application_id or payment_id
                    action ---> string of agent activity
                    object_type  --> 'application' or 'payment' or 'sales_ops'

    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    user = request.user

    data = request.POST.dict()
    if not data['object_id']:
        return JsonResponse({"status": "failed", "message": "application_id is None"})

    object_type = data.get('object_type')
    if object_type == 'application':
        application = Application.objects.get_or_none(pk=int(data['object_id']))
        if application:
            autodialer_session = AutodialerSession.objects.filter(
                application_id=application.id, status=application.status
            ).last()

            if not autodialer_session:
                return JsonResponse(
                    {
                        "status": "failed",
                        "message": "session not found, application status %s"
                        % (application.status),
                    }
                )

            AutodialerActivityHistory.objects.create(
                autodialer_session=autodialer_session, action=data.get('action'), agent=user
            )
            return JsonResponse(
                {"status": "success", "message": "berhasil rekam autodialer activity history"}
            )
        else:
            return JsonResponse({"status": "failed", "message": "application not found"})
    elif object_type == 'sales_ops':
        return sales_ops_crm_views.ajax_autodialer_history_record(request)
    else:
        payment = Payment.objects.get_or_none(pk=int(data['object_id']))
        if payment:
            payment_autodialer_session = PaymentAutodialerSession.objects.filter(
                payment=payment
            ).last()

            PaymentAutodialerActivity.objects.create(
                payment_autodialer_session=payment_autodialer_session,
                action=data.get('action'),
                agent=user,
            )
            return JsonResponse(
                {"status": "success", "message": "berhasil rekam autodialer activity history"}
            )
        else:
            return JsonResponse({"status": "failed", "message": "payment not found"})


def ajax_autodialer_session_status_old(request):
    """

    @param request: object_id ---> application_id or payment_id
                    session_start ---> 1 for true, and don't sent parameter for False
                    session_stop ---> 1 for true, and don't sent parameter for False
                    is_failed   ---> 1 for True, and don't sent parameter for False
                    hashtag     ---> 1 for True, and don't sent parameter for False
                    courtesy_result --> for 180 status ("CC Call" or "CC Email")
                    call_result ---> SkiptraceResultChoice id
                    is_fu --> 1 for True, and don't sent parameter for False
                    object_type  --> 'application' or 'payment'
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    user = request.user
    data = request.POST.dict()
    if data.get('object_type') == 'application':
        application = Application.objects.get_or_none(pk=int(data['object_id']))
        app_status = int(application.application_status.status_code)
        if application:

            app_history = ApplicationHistory.objects.filter(
                application=application, status_new=application.application_status_id
            ).last()
            autodialer_status = AutodialerSessionStatus.objects.get_or_none(
                application_history=app_history
            )

            if data.get('session_start'):
                if not autodialer_status:
                    autodialer_status = AutodialerSessionStatus.objects.create(
                        application_history=app_history
                    )
                action = "session_started"
            else:
                if not autodialer_status:
                    app_history = ApplicationHistory.objects.filter(
                        application=application
                    ).order_by('-id')[1]
                    app_status = int(app_history.status_new)
                    autodialer_status = app_history.autodialersessionstatus

            if data.get('session_stop'):
                action = "session_stoped"

            if data.get('session_start') or data.get('session_stop'):
                AutodialerActivityHistory.objects.create(
                    autodialer_session_status=autodialer_status, action=action, agent=user
                )

            next_turn = autodialer_next_turn(app_status)

            condition_failed = (
                data.get('is_failed') == '1' and app_status != 180 and data.get('hashtag') == '1'
            )

            condition_180 = app_status == 180 and data.get('courtesy_result')

            fu_success = data.get('is_fu')
            if data.get('call_result'):
                call_result = SkiptraceResultChoice.objects.get(pk=data['call_result'])
                AutodialerActivityHistory.objects.create(
                    autodialer_session_status=autodialer_status,
                    action="session_status_called_with_call_result %s " % call_result.name,
                    agent=user,
                )
            if data.get('call_result') in ['2', '3', '4']:
                # for call result Not connected, Rejected/Busy, Not Answer
                autodialer_status.next_session_ts = next_turn
                autodialer_status.save()
                AutodialerActivityHistory.objects.create(
                    autodialer_session_status=autodialer_status,
                    action="next_session_ts_set",
                    agent=user,
                )

            if condition_failed or condition_180 or fu_success:
                if condition_failed:
                    autodialer_status.failed_count += 1
                    autodialer_status.next_session_ts = next_turn
                    autodialer_status.save()
                    call_result = SkiptraceResultChoice.objects.get(pk=data['call_result'])
                    note = autodialer_note_generator(
                        app_status, autodialer_status.failed_count, call_result.name
                    )
                    AutodialerActivityHistory.objects.create(
                        autodialer_session_status=autodialer_status,
                        action="failed_call",
                        agent=user,
                    )
                if condition_180:
                    note = data.get('courtesy_result')
                    AutodialerActivityHistory.objects.create(
                        autodialer_session_status=autodialer_status,
                        action=("courtesy call (%s)" % note),
                        agent=user,
                    )
                if fu_success:
                    autodialer_status.next_session_ts = autodialer_next_turn('fu')
                    autodialer_status.save()
                    note = 'Follow up success'

                ApplicationNote.objects.create(
                    note_text=note,
                    application_id=application.id,
                    added_by_id=user.id,
                )

            return JsonResponse(
                {"status": "success", "message": "berhasil rekam autodialer session"}
            )
        else:
            return JsonResponse({"status": "failed", "message": "application not found"})
    else:
        payment = Payment.objects.get_or_none(pk=int(data['object_id']))
        if payment:
            payment_autodialer_session = PaymentAutodialerSession.objects.filter(
                payment=payment
            ).last()
            today = timezone.localtime(timezone.now()).date()
            if data.get('session_start'):
                dpd_changed = False
                if payment_autodialer_session:
                    dpd_changed = (
                        payment_autodialer_session.dpd_code < 0
                        and payment_autodialer_session.dpd_code != (today - payment.due_date).days
                    )

                if not payment_autodialer_session or dpd_changed:
                    dpd_code = (today - payment.due_date).days
                    payment_autodialer_session = PaymentAutodialerSession.objects.create(
                        payment=payment, dpd_code=dpd_code
                    )

                    PaymentAutodialerActivity.objects.create(
                        payment_autodialer_session=payment_autodialer_session,
                        action="session_started",
                        agent=user,
                    )
            if data.get('session_stop'):
                PaymentAutodialerActivity.objects.create(
                    payment_autodialer_session=payment_autodialer_session,
                    action="session_stoped",
                    agent=user,
                )
            next_turn = autodialer_next_turn('colT0')

            condition_failed = (
                data.get('is_failed') == '1'
                and data.get('hashtag') == '1'
                and payment.due_date == today
            )
            if condition_failed:
                payment_autodialer_session.failed_count += 1
                payment_autodialer_session.next_session_ts = next_turn
                payment_autodialer_session.save()
                call_result = SkiptraceResultChoice.objects.get(pk=data['call_result'])
                note = "Collection #%s : %s " % (
                    str(payment_autodialer_session.failed_count),
                    call_result.name,
                )
                PaymentAutodialerActivity.objects.create(
                    payment_autodialer_session=payment_autodialer_session,
                    action="failed_call",
                    agent=user,
                )

                PaymentNote.objects.create(note_text=note, payment=payment)
            return JsonResponse(
                {"status": "success", "message": "berhasil rekam autodialer session"}
            )
        else:
            return JsonResponse({"status": "failed", "message": "payment not found"})


def ajax_autodialer_session_status(request):
    """

    @param request: object_id ---> application_id or payment_id
                    session_start ---> 1 for true, and don't sent parameter for False
                    session_stop ---> 1 for true, and don't sent parameter for False
                    is_failed   ---> 1 for True, and don't sent parameter for False
                    hashtag     ---> 1 for True, and don't sent parameter for False
                    courtesy_result --> for 180 status ("CC Call" or "CC Email")
                    call_result ---> SkiptraceResultChoice id
                    is_fu --> 1 for True, and don't sent parameter for False
                    object_type  --> 'application' or 'payment' or 'sales_ops'
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    user = request.user
    data = request.POST.dict()

    object_type = data.get('object_type')
    if object_type == 'application':
        application = Application.objects.get_or_none(pk=int(data['object_id']))
        app_status = application.application_status.status_code
        if data.get('app_status'):
            # is_julo_one = False
            if '.' in data.get('app_status'):
                data['app_status'] = data.get('app_status').split('.')[0]
                # is_julo_one = True
            app_status = int(data['app_status'])

        if application:
            autodialer_session = AutodialerSession.objects.filter(
                application_id=application.id, status=app_status
            ).last()

            if not autodialer_session:
                autodialer_session = AutodialerSession.objects.create(
                    application=application, status=app_status
                )
            if data.get('session_start'):
                action = "session_started"

            if data.get('session_stop'):
                action = "session_stoped"

            if data.get('session_start') or data.get('session_stop'):
                AutodialerActivityHistory.objects.create(
                    autodialer_session=autodialer_session, action=action, agent=user
                )

            # get next session call ts
            next_turn = autodialer_next_turn(app_status)

            condition_failed = (
                data.get('is_failed') == '1' and app_status != 180 and data.get('hashtag') == '1'
            )

            condition_180 = app_status == 180 and data.get('courtesy_result')

            fu_success = data.get('is_fu')

            # get called phone_number
            phone_number = None
            if data.get('phone_number'):
                phone_number = data['phone_number']

            if data.get('call_result'):
                call_result = SkiptraceResultChoice.objects.get(pk=data['call_result'])
                AutodialerCallResult.objects.create(
                    autodialer_session=autodialer_session,
                    action=call_result.name,
                    phone_number=phone_number,
                    agent=user,
                )

            if condition_failed or condition_180 or fu_success:
                if condition_failed:
                    autodialer_session.failed_count += 1
                    autodialer_session.next_session_ts = next_turn
                    autodialer_session.save()
                    call_result = SkiptraceResultChoice.objects.get(pk=data['call_result'])
                    note = autodialer_note_generator(
                        app_status, autodialer_session.failed_count, call_result.name
                    )
                    AutodialerCallResult.objects.create(
                        autodialer_session=autodialer_session,
                        action="failed_call and hashtag %s" % call_result.name,
                        agent=user,
                    )
                    today = timezone.localtime(timezone.now())
                    if (today - autodialer_session.cdate).days > 1:
                        process_status_change_on_failed_call(autodialer_session)
                if condition_180:
                    note = data.get('courtesy_result')
                    AutodialerCallResult.objects.create(
                        autodialer_session=autodialer_session,
                        action=("courtesy call (%s)" % note),
                        agent=user,
                    )
                if fu_success:
                    autodialer_session.next_session_ts = autodialer_next_turn('fu')
                    autodialer_session.save()
                    note = 'Follow up success'

                custom_note = data.get('note')
                if custom_note:
                    note_text = '%s \n %s' % (note, data['note'])
                else:
                    note_text = note
                ApplicationNote.objects.create(
                    note_text=note_text,
                    application_id=application.id,
                    added_by_id=user.id,
                )

            return JsonResponse(
                {"status": "success", "message": "berhasil rekam autodialer session"}
            )
        else:
            return JsonResponse({"status": "failed", "message": "application not found"})
    elif object_type == 'sales_ops':
        return sales_ops_crm_views.ajax_autodialer_session_status(request)
    else:
        payment = Payment.objects.get_or_none(pk=int(data['object_id']))
        if payment:
            payment_autodialer_session = PaymentAutodialerSession.objects.filter(
                payment=payment
            ).last()
            today = timezone.localtime(timezone.now()).date()
            if data.get('session_start'):
                dpd_changed = False
                if payment_autodialer_session:
                    dpd_changed = (
                        payment_autodialer_session.dpd_code < 0
                        and payment_autodialer_session.dpd_code != (today - payment.due_date).days
                    )

                if not payment_autodialer_session or dpd_changed:
                    dpd_code = (today - payment.due_date).days
                    payment_autodialer_session = PaymentAutodialerSession.objects.create(
                        payment=payment, dpd_code=dpd_code
                    )

                    PaymentAutodialerActivity.objects.create(
                        payment_autodialer_session=payment_autodialer_session,
                        action="session_started",
                        agent=user,
                    )
            if data.get('session_stop'):
                PaymentAutodialerActivity.objects.create(
                    payment_autodialer_session=payment_autodialer_session,
                    action="session_stoped",
                    agent=user,
                )
            next_turn = autodialer_next_turn('colT0')

            condition_failed = (
                data.get('is_failed') == '1'
                and data.get('hashtag') == '1'
                and payment.due_date == today
            )
            if condition_failed:
                payment_autodialer_session.failed_count += 1
                payment_autodialer_session.next_session_ts = next_turn
                payment_autodialer_session.save()
                call_result = SkiptraceResultChoice.objects.get(pk=data['call_result'])
                note = "Collection #%s : %s " % (
                    str(payment_autodialer_session.failed_count),
                    call_result.name,
                )
                PaymentAutodialerActivity.objects.create(
                    payment_autodialer_session=payment_autodialer_session,
                    action="failed_call",
                    agent=user,
                )

                PaymentNote.objects.create(note_text=note, payment=payment)
            return JsonResponse(
                {"status": "success", "message": "berhasil rekam autodialer session"}
            )
        else:
            return JsonResponse({"status": "failed", "message": "payment not found"})


def get_script_for_agent(request):

    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    application_id = request.GET.get('application_id')
    user = request.user

    application = Application.objects.get_or_none(pk=application_id)
    limit_info = None
    if application.is_julo_one():
        if application.status == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
            account = application.account
            account_limit = account.accountlimit_set.last()
            account_property = account.accountproperty_set.last()
            _matrix, self_interest = get_credit_matrix_and_credit_matrix_product_line(
                application, is_self_bank_account=True
            )
            _matrix, other_interest = get_credit_matrix_and_credit_matrix_product_line(
                application, is_self_bank_account=False
            )
            limit_info = {
                'account_limit': account_limit.set_limit,
                'self_interest': '{}%'.format(self_interest.interest * 100),
                'other_interest': '{}%'.format(other_interest.interest * 100),
                'cycle_day': account.cycle_day,
                'concurrency': account_property.concurrency,
                'is_entry_level': is_entry_level_type(application),
            }

    if application:
        activation_call_statuses = [
            ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
        ]
        if application.application_status_id in activation_call_statuses:
            if application.product_line_code in ProductLineCodes.stl():
                html = render_to_string(
                    'object/loan_app/include/sphp_stl.html', {'object': application}
                )
            elif application.product_line_code in ProductLineCodes.grabfood():
                html = render_to_string(
                    'object/loan_app/include/sphp_grabfood.html', {'object': application}
                )
            elif application.product_line_code in ProductLineCodes.loc():
                html = render_to_string(
                    'object/loan_app/include/sphp_loc.html', {'object': application}
                )
            elif (
                application.application_status_id
                == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
                and application.is_julo_one()
            ):
                html = render_to_string(
                    'object/loan_app/include/limit_generated.html',
                    {'object': application, 'limit_info': limit_info},
                )
            else:
                html = render_to_string(
                    'object/loan_app/include/sphp.html',
                    {
                        'object': application,
                        'product_line_BRI': ProductLineCodes.bri(),
                        'product_line_GRAB': ProductLineCodes.grab(),
                    },
                )
            return HttpResponse(html)
        if application.application_status_id == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
            html = render_to_string(
                'object/app_status/include/courtesy_call.html',
                {'object': application, 'user': user},
            )
            return HttpResponse(html)

        return JsonResponse(
            {
                "status": "failed",
                "message": "not specified request",
            }
        )

    return JsonResponse(
        {
            "status": "failed",
            "message": "application not found",
        }
    )


def ajax_change_status(request):

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    data = request.POST.dict()
    application_id = int(data['application_id'])
    status_to = int(data['status_to'])
    reason = data['reason']
    notes = data['notes']

    try:
        application = Application.objects.get(pk=application_id)
        process_application_status_change(application.id, status_to, reason, note=notes)

    except Exception as e:
        sentry_client.captureException()
        return JsonResponse({"status": "failed", "message": e})

    return JsonResponse(
        {"status": "success", "message": "berhasil pindah status ke %s" % status_to}
    )


# END OF AJAX AUTODIALER #


@julo_login_required
def customer_app_action(request):
    return render(request, 'object/dashboard/customer_app_action.html')


def ajax_customer_app_action(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    try:
        data = request.POST.dict()
        customer_list = data['customer_list'].replace(', ', ',').split(",")
        action = data['action']
        customer_query = Customer.objects.filter(id__in=(customer_list))

        customer_id_found = []
        for customer in customer_query:
            customer_id_found.append(str(customer.id))

        missing_id = list(set(customer_list).difference(set(customer_id_found)))

        existing_customer_app_action = CustomerAppAction.objects.filter(
            customer_id__in=customer_id_found, action=action, is_completed=False
        )
        customer_app_action_found = []
        for customer in existing_customer_app_action:
            customer_app_action_found.append(str(customer.customer_id))

        customer_app_action_found = list(dict.fromkeys(customer_app_action_found))
        customer_need_app_action = list(
            set(customer_id_found).difference(set(customer_app_action_found))
        )
        customer_need_app_action = Customer.objects.filter(id__in=(customer_need_app_action))

        existing_id = customer_app_action_found
        if customer_query:
            customer_app_action_arr = []
            for customer in customer_need_app_action.iterator():
                if action == 'rescrape':
                    pn_client = get_julo_pn_client()
                    pn_client.alert_rescrape(
                        customer.device_set.last().gcm_reg_id,
                        customer.application_set.regular_not_deletes().last().id,
                    )
                    data = CustomerAppAction(
                        customer_id=customer.id, action=action, is_completed=False
                    )
                    customer_app_action_arr.append(data)
                else:
                    data = CustomerAppAction(
                        customer_id=customer.id, action=action, is_completed=False
                    )
                    customer_app_action_arr.append(data)
            CustomerAppAction.objects.bulk_create(customer_app_action_arr)
            if missing_id or existing_id:
                json = {
                    "status": "success",
                    "messages": "Successfully created CustomerAppAction entry for some id.",
                }
                if missing_id:
                    json['messages'] = json['messages'] + ' Missing id: ' + str(missing_id)
                if existing_id:
                    json['messages'] = (
                        json['messages'] + ' Entry already exist: ' + str(existing_id)
                    )

                return JsonResponse(json)
            else:
                return JsonResponse(
                    {
                        "status": "success",
                        "messages": "Successfully created CustomerAppAction entry for all id",
                    }
                )
        else:
            return JsonResponse(
                {
                    "status": "failed",
                    "messages": "Failed to submit Customer App Action. Customer ID not found.",
                }
            )
    except Exception:
        return JsonResponse(
            {
                "status": "failed",
                "messages": "Invalid Input. Must be numeric, "
                "and must not end with nonnumerical character.",
            }
        )


def ajax_device_app_action(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    try:
        data = request.POST.dict()
        device_list = data['device_list'].replace(', ', ',').split(",")
        device_list = [int(device_id) for device_id in device_list]
        action = data['action']
        device_query = Device.objects.filter(id__in=device_list)
        if not device_query.exists():
            return JsonResponse(
                {
                    "status": "failed",
                    "messages": "Failed to submit Device App Action. Device ID not found.",
                }
            )

        found_device_ids = device_query.values_list('id', flat=True)
        missing_device_ids = list(set(device_list).difference(set(found_device_ids)))

        existing_device_app_action = DeviceAppAction.objects.filter(
            device_id__in=found_device_ids, action=action, is_completed=False
        )
        existing_action_device_ids = existing_device_app_action.values_list('device_id', flat=True)
        device_ids_to_create = list(
            set(found_device_ids).difference(set(existing_action_device_ids))
        )
        devices_in_need = Device.objects.filter(id__in=device_ids_to_create)

        device_app_actions_to_create = []
        for device in devices_in_need.iterator():
            data = DeviceAppAction(device_id=device.id, action=action, is_completed=False)
            device_app_actions_to_create.append(data)
        DeviceAppAction.objects.bulk_create(device_app_actions_to_create)
        if missing_device_ids or existing_action_device_ids:
            response = {
                "status": "success",
                "messages": "Successfully created CustomerAppAction entry for some id.",
            }
            if missing_device_ids:
                response['messages'] = (
                    response['messages'] + ' Missing id: ' + str(missing_device_ids)
                )
            if existing_action_device_ids:
                response['messages'] = (
                    response['messages']
                    + ' Entry already exist: '
                    + str(existing_action_device_ids)
                )
            return JsonResponse(response)
        else:
            return JsonResponse(
                {
                    "status": "success",
                    "messages": "Successfully created CustomerAppAction entry for all id",
                }
            )
    except Exception:
        return JsonResponse(
            {
                "status": "failed",
                "messages": "Invalid Input. Must be numeric, "
                "and must not end with nonnumerical character.",
            }
        )


def ajax_payment_list_collection_agent_view(request):

    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    qs = Payment.objects.normal()
    max_per_page = int(request.GET.get('max_per_page'))

    try:
        page = int(request.GET.get('page'))
    except Exception:
        page = 1

    # query payment by user
    user = request.user

    # query for PTP and Reminder Call Date
    role_name = request.GET.get('role_name', None)
    agent_assignment_type = convert_usergroup_to_agentassignment_type(role_name)
    today = datetime.today()
    today = today.replace(hour=0, minute=0, second=0)
    tomorow = today + timedelta(days=1)
    qs = qs.not_paid()
    agent_service = get_agent_service()
    # get all payment with status callback time
    call_result = SkiptraceResultChoice.objects.get(name='RPC - Call Back')
    payment_ids = SkiptraceHistory.objects.values_list('payment_id', flat=True).filter(
        udate__date=today.date(), call_result_id=call_result
    )

    qs = agent_service.filter_payments_by_agent_and_type(qs, user, agent_assignment_type)
    qs = qs.filter(
        Q(ptp_date__lte=tomorow) & Q(is_collection_called=False) & Q(ptp_date__isnull=False)
        | Q(reminder_call_date__lte=tomorow)
        & Q(is_collection_called=False)
        & Q(reminder_call_date__isnull=False)
        & Q(is_reminder_called=False)
        | Q(id__in=payment_ids)
    ).order_by('reminder_call_date', '-ptp_date')

    result = qs.values(
        'id',
        'loan__application__product_line_id',
        'loan__application__email',
        'loan__application__fullname',
        'is_robocall_active',
        'payment_status_id',
        'due_date',
        'payment_number',
        'loan_id',
        'loan__loan_status_id',
        'udate',
        'cdate',
        'loan__application__partner__name',
        'loan__application_id',
        'loan__application__customer_id',
        'due_amount',
        'late_fee_amount',
        'cashback_earned',
        'loan__application__mobile_phone_1',
        'loan__application__ktp',
        'loan__application__dob',
        'loan__loan_amount',
        'loan__loan_duration',
        'loan__application__id',
        'payment_status__status_code',
        'loan__id',
        'loan__application__email',
        'loan__julo_bank_account_number',
        'ptp_date',
        'reminder_call_date',
    )

    # add dpd_sort for property sorting
    result = result.extra(
        select={
            'loan_status': 'loan.loan_status_code',
            'dpd_sort': (
                "CASE WHEN payment.due_date is not Null "
                "THEN DATE_PART('day', CURRENT_TIMESTAMP - due_date) END"
            ),
            'dpd_ptp_sort': (
                "CASE WHEN payment.ptp_date is not Null "
                "THEN DATE_PART('day', ptp_date - CURRENT_TIMESTAMP) END"
            ),
        },
        tables=['loan'],
        where=['loan.loan_status_code != %s', 'loan.loan_id = payment.loan_id'],
        params=[StatusLookup.INACTIVE_CODE],
    )
    sort_q = request.GET.get('sort_q', None)
    if sort_q:
        if sort_q == 'loan_and_status_asc':
            result = result.order_by('loan__id', 'loan__loan_status__status_code')
        elif sort_q == 'loan_and_status_desc':
            result = result.order_by('-loan__id', '-loan__loan_status__status_code')
        elif sort_q == 'dpd':
            result = result.extra(order_by=['dpd_sort'])
        elif sort_q == '-dpd':
            result = result.extra(order_by=['-dpd_sort'])
        elif sort_q == 'dpd_ptp':
            result = result.extra(order_by=['dpd_ptp_sort'])
        elif sort_q == '-dpd_ptp':
            result = result.extra(order_by=['-dpd_ptp_sort'])
        else:
            result = result.order_by(sort_q)

    paginator = Paginator(result, max_per_page)

    try:
        payments = paginator.page(page)
    except (EmptyPage):
        return HttpResponse(
            json.dumps({"status": "failed", "message": "invalid page"}),
            content_type="application/json",
        )

    return JsonResponse(
        {
            'status': 'success',
            'data': list(payments),
            'count_page': paginator.num_pages,
            'current_page': page,
            'payment_lock_list': payment_lock_list(),
        },
        safe=False,
    )


@csrf_exempt
def ajax_store_crm_navlog(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    data = request.POST.dict()
    navlog_obj = json.loads(data['navlog'])
    navlog_obj = navlog_obj if isinstance(navlog_obj, list) else []
    async_store_crm_navlog.delay(navlog_obj)

    return HttpResponse({'message': 'success'}, content_type='application/json')


@julo_login_required
def ajax_payment_list_collection_supervisor_view(request):
    """
    Deprecated
    """
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    qs = Payment.objects.normal()
    max_per_page = int(request.GET.get('max_per_page'))

    try:
        page = int(request.GET.get('page'))
    except Exception:
        page = 1

    # query for PTP and Reminder Call Date
    today = datetime.today()
    today = today.replace(hour=0, minute=0, second=0)
    tomorow = today + timedelta(days=1)
    # get all payment with status callback time
    call_result = SkiptraceResultChoice.objects.get(name='RPC - Call Back')
    payment_ids = SkiptraceHistory.objects.values_list('payment_id', flat=True).filter(
        udate__date=today.date(), call_result_id=call_result
    )
    qs = (
        qs.not_paid()
        .filter(
            Q(ptp_date__lte=tomorow) & Q(is_collection_called=False) & Q(ptp_date__isnull=False)
            | Q(reminder_call_date__lte=tomorow)
            & Q(is_collection_called=False)
            & Q(reminder_call_date__isnull=False)
            & Q(is_reminder_called=False)
            | Q(id__in=payment_ids)
        )
        .order_by('reminder_call_date', '-ptp_date')
    )

    result = qs.values(
        'id',
        'loan__application__product_line_id',
        'loan__application__email',
        'loan__application__fullname',
        'is_robocall_active',
        'payment_status_id',
        'due_date',
        'payment_number',
        'loan_id',
        'loan__loan_status_id',
        'udate',
        'cdate',
        'loan__application__partner__name',
        'loan__application_id',
        'loan__application__customer_id',
        'due_amount',
        'late_fee_amount',
        'cashback_earned',
        'loan__application__mobile_phone_1',
        'loan__application__ktp',
        'loan__application__dob',
        'loan__loan_amount',
        'loan__loan_duration',
        'loan__application__id',
        'payment_status__status_code',
        'loan__id',
        'loan__application__email',
        'loan__julo_bank_account_number',
        'ptp_date',
        'reminder_call_date',
    )

    # add dpd_sort for property sorting
    result = result.extra(
        select={
            'loan_status': 'loan.loan_status_code',
            'dpd_sort': (
                "CASE WHEN payment.due_date is not Null "
                "THEN DATE_PART('day', CURRENT_TIMESTAMP - due_date) END"
            ),
            'dpd_ptp_sort': (
                "CASE WHEN payment.ptp_date is not Null "
                "THEN DATE_PART('day', ptp_date - CURRENT_TIMESTAMP) END"
            ),
        },
        tables=['loan'],
        where=['loan.loan_status_code != %s', 'loan.loan_id = payment.loan_id'],
        params=[StatusLookup.INACTIVE_CODE],
    )
    sort_q = request.GET.get('sort_q', None)
    if sort_q:
        if sort_q == 'loan_and_status_asc':
            result = result.order_by('loan__id', 'loan__loan_status__status_code')
        elif sort_q == 'loan_and_status_desc':
            result = result.order_by('-loan__id', '-loan__loan_status__status_code')
        elif sort_q == 'dpd':
            result = result.extra(order_by=['dpd_sort'])
        elif sort_q == '-dpd':
            result = result.extra(order_by=['-dpd_sort'])
        elif sort_q == 'dpd_ptp':
            result = result.extra(order_by=['dpd_ptp_sort'])
        elif sort_q == '-dpd_ptp':
            result = result.extra(order_by=['-dpd_ptp_sort'])
        else:
            result = result.order_by(sort_q)

    paginator = Paginator(result, max_per_page)

    try:
        payments = paginator.page(page)
    except (EmptyPage):
        return HttpResponse(
            json.dumps({"status": "failed", "message": "invalid page"}),
            content_type="application/json",
        )

    return JsonResponse(
        {
            'status': 'success',
            'data': list(payments),
            'count_page': paginator.num_pages,
            'current_page': page,
            'payment_lock_list': payment_lock_list(),
        },
        safe=False,
    )


def get_pv_3rd_party_bucket_count(request):

    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    return JsonResponse(
        {
            "status": "success",
            'app_dashboard': pv_3rd_party_dashboard(),
        }
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_SUPERVISOR)
def dashboard_activity_dialer_upload(request):
    """handle get request"""
    template_name = 'object/dashboard/activity_dialer_upload.html'
    logs = ""
    upload_form = None
    ok_couter = 0
    nok_couter = 0
    error_row = []
    path = "../../static/excel/Report Collection 9 mei prediktif -1.xls"

    def _render():
        return render(
            request,
            template_name,
            {
                'form': upload_form,
                'logs': logs,
                'ok': ok_couter,
                'nok': nok_couter,
                'path': path,
                'error_row': error_row,
            },
        )

    if request.method == 'POST':
        upload_form = UploadDialerActivityForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            nok_couter = 1
            logs = 'Invalid form'
            return _render()

        file_ = upload_form.cleaned_data['file_field']
        extension = file_.name.split('.')[-1]

        if extension not in ['xls', 'xlsx']:
            nok_couter = 1
            logs = 'Please upload correct file excel'
            return _render()

        try:
            excel_datas = get_data(file_)
        except Exception as error:
            nok_couter = 1
            logs = str(error)
            return _render()
        succes_count = 0
        skip_result_choice_mappings = {
            'Cust Busy': 'Rejected/Busy',
            'Drop Call By Customer': 'Rejected/Busy',
            'PTP': 'RPC',
            'NO_PTP': 'RPC',
            'Answering Machine': 'No Answer',
            'Left Message': 'WPC',
        }

        for idx_sheet, sheet in enumerate(excel_datas):
            for idx_rpw, row in enumerate(excel_datas[sheet]):
                try:
                    if row:
                        if row[0] == 'No. Account':
                            continue
                        else:
                            agent = row[12].strip()
                            source = row[4].strip()
                            phone = format_e164_indo_phone_number(row[3])
                            _date = row[1].strip()
                            time = row[2].strip()
                            _date = datetime.strptime(_date, "%d/%m/%Y").date()
                            time = datetime.strptime(time, "%H.%M.%S").time()
                            date_time = str(_date) + " " + str(time)
                            payment_id = row[0]
                            ptp_date = row[6].strip()
                            ptp_amount = row[7]
                            note = row[11].strip()
                            result = row[5].strip()
                            skip_result_choice = skip_result_choice_mappings.get(result)
                            if not skip_result_choice:
                                skip_result_choice = result
                            user_obj = User.objects.filter(username=agent.lower()).last()
                            payment = Payment.objects.get_or_none(id=payment_id)
                            if not user_obj:
                                logger.error(
                                    {
                                        'action': 'activity_dialer_upload',
                                        'errors': 'Agent not Found {}'.format(agent),
                                    }
                                )
                                error_row.append(row)
                                error_row.append('Reason --> Agent not Found {}'.format(agent))
                                continue
                            if not payment:
                                logger.error(
                                    {
                                        'action': 'activity_dialer_upload',
                                        'errors': 'Payment not Found {}'.format(payment_id),
                                    }
                                )
                                error_row.append(row)
                                error_row.append(
                                    'Reason -->  Payment not Found {}'.format(payment_id)
                                )
                                continue
                            CuserMiddleware.set_user(user_obj)
                            customer = payment.loan.customer.id
                            now = datetime.now()
                            skiptrace = Skiptrace.objects.create(
                                contact_source=source, phone_number=phone, customer_id=customer
                            )
                            if skiptrace.id:
                                if ptp_amount and ptp_date:
                                    ptp_amount = [x for x in ptp_amount if x.isdigit()]
                                    ptp_date = datetime.strptime(ptp_date, "%d/%m/%Y").date()
                                    PTP.objects.create(
                                        payment=payment,
                                        loan=payment.loan,
                                        agent_assigned=user_obj,
                                        ptp_date=ptp_date,
                                        ptp_amount=ptp_amount,
                                    )
                                skip_result_choice = SkiptraceResultChoice.objects.filter(
                                    name=skip_result_choice
                                ).last()
                                if not skip_result_choice:
                                    skiptrace_result_choice = SkiptraceResultChoice.objects.create(
                                        name=result, weight=-1
                                    )
                                    skiptrace_result_id = skiptrace_result_choice.id
                                else:
                                    skiptrace_result_id = skip_result_choice.id
                                if note:
                                    PaymentNote.objects.create(note_text=note, payment=payment)
                                SkiptraceHistory.objects.create(
                                    start_ts=date_time,
                                    end_ts=now,
                                    application_id=payment.loan.application.id,
                                    loan_id=payment.loan.id,
                                    agent_name=user_obj.username,
                                    call_result_id=skiptrace_result_id,
                                    agent_id=user_obj,
                                    skiptrace_id=skiptrace.id,
                                    payment_id=payment_id,
                                    notes=result,
                                    source='CRM',
                                )
                            else:
                                logger.error(
                                    {
                                        'errors': 'Data already added to skiptrace table {}'.format(
                                            payment_id
                                        ),
                                        'action': 'activity_dialer_upload',
                                    }
                                )
                                error_row.append(row)
                                error_row.append(
                                    "Reason --> Data already added to skiptrace table - phone no. "
                                    "or Type of column in excel can't be the same "
                                )
                                continue
                except Exception as error:
                    logger.error(
                        {
                            'action': 'activity_dialer_upload',
                            'errors': 'failed read row {} '.format(error),
                        }
                    )
        succes_count = 1
        if error_row:
            error_row = json.dumps(error_row)
        if succes_count == 1:
            ok_couter = 1
            logs = "Data uploaded successfully"
    else:
        upload_form = UploadDialerActivityForm()
    return _render()


@julo_login_required
@julo_login_required_group(JuloUserRoles.OPS_TEAM_LEADER)
def dashboard_ops_team_leader(request):
    """handle get request"""
    template_name = 'object/dashboard/ops_team_leader.html'

    def _render():
        return render(request, template_name, {'form': upload_form})

    if request.method == 'POST':
        try:
            upload_form = SubmitOPSStatusForm(request.POST)

            application_id = request.POST.get('application_field')
            requesting_agent = request.POST.get('agent_field')
            change_status = int(request.POST.get('status_field'))
            change_reason = request.POST.get('reason_field')
            change_reason_detail = request.POST.get('reason_detail_field')

            user = User.objects.get(id=requesting_agent)

            application = Application.objects.get_or_none(pk=application_id)
            valid_status = StatusManager.get_or_none(change_status)

            forbidden_status = (
                ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
                ApplicationStatusCodes.BULK_DISBURSAL_ONGOING,
                ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
            )

            if user is None:
                messages.error(request, 'User Tidak Ada!')

            if application is None:
                messages.error(request, 'Application Tidak Ada!')

            elif valid_status is None:
                messages.error(request, 'Status Tidak Ada! \\n Masukkan Status yang Valid!')

            elif valid_status.code == application.application_status_id:
                messages.error(request, 'Status Lama dan Baru \\n Tidak Boleh Sama!')

            elif application.customer.application_set.filter(
                application_number__gt=application.application_number
            ).exists():
                messages.error(request, 'Terdapat application baru yang berjalan')

            elif (
                change_status in ApplicationStatusCodes.can_reapply()
                or change_status in forbidden_status
            ):
                messages.error(
                    request,
                    'Tidak bisa memindahkan Application ke status {} '
                    'menggunakan halaman ini'.format(change_status),
                )

            else:
                current_status = application.application_status_id

                target_status = (
                    ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                    ApplicationStatusCodes.DOCUMENTS_VERIFIED,
                    ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
                    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                )

                if change_status in target_status:
                    if current_status >= ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL:
                        if hasattr(application, 'loan'):
                            loan = application.loan
                            offer = loan.offer
                            va_banks = loan.bankvirtualaccount_set.all()
                            payment_method = loan.paymentmethod_set.all()
                            payment_method.update(loan=None)
                            loan.payment_set.all().delete()
                            loan.virtualaccountsuffix_set.all().delete()
                            for va_bank in va_banks:
                                va_bank.update_safely(loan=None)
                            loan.signaturevendorlog_set.all().delete()
                            loan.delete()
                            if change_status == ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL:
                                offer.is_accepted = False
                                offer.save()
                            else:
                                offer.delete()
                            application.update_safely(is_sphp_signed=False)

                application.update_safely(application_status_id=change_status)

                if change_status not in ApplicationStatusCodes.can_reapply():
                    application.customer.update_safely(can_reapply=False)

                ApplicationHistory.objects.create(
                    application=application,
                    status_old=current_status,
                    status_new=change_status,
                    change_reason="{} - {}".format(change_reason, change_reason_detail),
                    changed_by=user,
                )

                OpsTeamLeadStatusChange.objects.create(
                    application=application,
                    user=user,
                    change_reason=change_reason,
                    change_reason_detail=change_reason_detail,
                )

                messages.success(
                    request,
                    'Sukses Mengubah status \\n Application ID {}\\n menjadi {}'.format(
                        application_id, change_status
                    ),
                )

                upload_form = SubmitOPSStatusForm()

        except Exception as e:
            sentry_client.captureException()
            logger.error({'action': 'dashboard_ops_team_leader', 'errors': str(e)})
            messages.error(request, "Terjadi kesalahan di server silahkan hubungi administrator.")

    else:
        upload_form = SubmitOPSStatusForm()

    return _render()


@julo_login_required
def ajax_ops_team_leader_get_agent(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    try:
        query = request.POST.get('q')
        users = tuple(
            Agent.objects.filter(
                Q(user__username__icontains=query)
                | Q(user__first_name=query)
                | Q(user__last_name=query)
            ).values('user__id', 'user__username', 'user__first_name', 'user__last_name')[:10]
        )

        return JsonResponse({"success": True, "message": "success", "agents": users})

    except Exception as e:
        return JsonResponse({"success": False, "messages": str(e), "agents": []})


@julo_login_required
@julo_login_required_multigroup(
    [
        JuloUserRoles.CHANGE_OF_REPAYMENT_CHANNEL,
        JuloUserRoles.COLLECTION_SUPERVISOR,
        JuloUserRoles.COLLECTION_TEAM_LEADER,
        JuloUserRoles.COLLECTION_AREA_COORDINATOR,
    ]
)
def dashboard_change_of_repayment_channel(request):
    role_name = JuloUserRoles.CHANGE_OF_REPAYMENT_CHANNEL
    is_collection = request.user.groups.filter(
        name__in=(
            JuloUserRoles.COLLECTION_SUPERVISOR,
            JuloUserRoles.COLLECTION_TEAM_LEADER,
            JuloUserRoles.COLLECTION_AREA_COORDINATOR,
        )
    ).exists()

    if not is_collection:
        create_or_update_role(request.user, role_name)

    return render(
        request,
        'object/dashboard/change_of_repayment_channel.html',
        {
            'PROJECT_URL': PROJECT_URL,
            'role_name': role_name,
            'bank_bca_code': BankCodes.BCA,
            'bank_permata_code': BankCodes.PERMATA,
        },
    )


def get_repaymet_channel_details(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    application_id = data['appln_id'].strip()
    submit_type = data['submit_type']
    response_data = {}
    response_data['application_det'] = {}
    response_data['payment_methods'] = {}
    response_data['msg'] = ''
    response_data['status'] = ''

    if not application_id or application_id.isnumeric() is False:
        response_data['msg'] = 'Plese enter a valid application no.'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})
    application = Application.objects.get_or_none(pk=application_id)
    if application is None:
        response_data['msg'] = 'No application found'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})
    if not hasattr(application, 'loan') or application.loan is None:
        response_data['msg'] = 'No loan found for this application'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})
    payment_methods = PaymentMethod.objects.filter(loan=application.loan)
    if not payment_methods:
        response_data['msg'] = 'No prefered channel found for application {}'.format(application_id)
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})
    if submit_type == 'update':
        payment_method_id = data['paymethod_id'].strip()
        PaymentMethod.objects.filter(loan=application.loan, is_primary=True).update(
            is_primary=False, is_shown=True, udate=datetime.now(), is_affected=True
        )
        PaymentMethod.objects.filter(id=payment_method_id).update(
            is_primary=True, is_shown=True, udate=datetime.now(), is_affected=True
        )
        payment_details = PaymentMethod.objects.get_or_none(id=payment_method_id)
        if payment_details is None:
            response_data['msg'] = 'No prefered channel found for application {}'.format(
                application_id
            )
            response_data['status'] = 'failure'
            return JsonResponse({'data': response_data})
        payment_method_name = payment_details.payment_method_name
        virtual_account = payment_details.virtual_account
        Loan.objects.filter(id=application.loan.id).update(
            julo_bank_name=payment_method_name, julo_bank_account_number=virtual_account
        )
        payment_methods = PaymentMethod.objects.filter(loan=application.loan)
    response_data['application_det'] = json.loads(serializers.serialize('json', [application]))[0]
    response_data['payment_methods'] = json.loads(serializers.serialize('json', payment_methods))
    response_data['loan'] = application.loan.id
    response_data['status'] = 'success'
    return JsonResponse({'data': response_data})


def get_available_repaymet_channel_for_account(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    account_id = data['account_id'].strip()
    submit_type = data['submit_type']
    response_data = {}
    response_data['msg'] = ''
    response_data['status'] = ''

    if not account_id or account_id.isnumeric() is False:
        response_data['msg'] = 'Please enter a valid Account no.'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})

    account = Account.objects.get_or_none(pk=account_id)
    if account is None:
        response_data['msg'] = 'No account found'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})

    application = account.customer.application_set.last()
    if application is None:
        response_data['msg'] = 'No application found for account {}'.format(account_id)
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})

    payment_methods = account.customer.paymentmethod_set.all()
    if not payment_methods:
        response_data['msg'] = 'No prefered channel found for account {}'.format(account_id)
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})

    if submit_type == 'update':
        payment_methods = update_primary_and_is_shown_payment_methods(
            data, account, payment_methods
        )

    if submit_type == 'generate_va':
        bank_code = data['bank_code']
        max_sequence = payment_methods.aggregate(Max('sequence')).get('sequence__max') or 0
        sequence = max_sequence + 1
        if bank_code == BankCodes.BCA:
            mobile_phone_1 = application.mobile_phone_1
            if not mobile_phone_1:
                response_data[
                    'msg'
                ] = 'Account- {} does not have phone number for application {}'.format(
                    account_id, application.id
                )
                response_data['status'] = 'failure'
                return JsonResponse({'data': response_data})

            payment_methods = generate_va_for_bank_bca(mobile_phone_1, account, sequence)
        elif bank_code == BankCodes.PERMATA:
            payment_methods = generate_va_for_bank_permata(account, sequence)
            if not payment_methods:
                response_data['msg'] = 'No va suffix available'
                response_data['status'] = 'failure'
                return JsonResponse({'data': response_data})

        else:
            response_data['msg'] = 'No bank selected to create va for account: {}'.format(
                account_id
            )
            response_data['status'] = 'failure'
            return JsonResponse({'data': response_data})

    payment_methods = payment_methods.order_by('sequence')
    payment_methods_shown = payment_methods.filter(is_shown=True)
    payment_method_primary = payment_methods.filter(is_primary=True)
    payment_method_customer_bank = payment_methods.filter(
        bank_code__in=[BankCodes.BCA, BankCodes.PERMATA]
    )
    if payment_method_customer_bank:
        response_data['payment_method_customer_bank'] = list_payment_methods(
            payment_method_customer_bank
        )
    else:
        response_data['payment_method_customer_bank'] = []

    response_data['application_det'] = json.loads(serializers.serialize('json', [application]))[0]
    response_data['payment_methods'] = list_payment_methods(payment_methods)
    if payment_methods_shown:
        response_data['payment_methods_shown'] = list_payment_methods(payment_methods_shown)
    else:
        response_data['payment_methods_shown'] = []

    if payment_method_primary:
        response_data['payment_method_primary'] = list_payment_methods(payment_method_primary)
    else:
        response_data['payment_method_primary'] = []

    response_data['status'] = 'success'
    return JsonResponse({'data': response_data})


@julo_login_required
@julo_login_required_group(JuloUserRoles.PRODUCT_MANAGER)
def dashboard_va_modifier(request):
    role_name = JuloUserRoles.PRODUCT_MANAGER
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/va_modifier.html',
        {
            'PROJECT_URL': PROJECT_URL,
            'role_name': role_name,
        },
    )


@csrf_protect
def ajax_get_repayment_channels(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed["GET"]

    list_repayment_channels = [
        {'name': RepaymentChannel.BCA, 'value': BankCodes.BCA},
        {'name': RepaymentChannel.PERMATA, 'value': BankCodes.PERMATA},
        {'name': RepaymentChannel.BRI, 'value': BankCodes.BRI},
    ]
    backup_repayment_channels_dict = {
        BankCodes.BCA: [{'name': 'Permata', 'value': BankCodes.PERMATA}],
        BankCodes.PERMATA: [{'name': 'Maybank', 'value': BankCodes.MAYBANK}],
        BankCodes.BRI: [{'name': 'Permata', 'value': BankCodes.PERMATA}],
    }

    return JsonResponse(
        {
            'status': 'success',
            'list_repayment_channels': list_repayment_channels,
            'backup_repayment_channels_dict': backup_repayment_channels_dict,
        }
    )


@csrf_protect
def ajax_activate_backup_repayment_channel(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    primary_repayment_channel = data['primary_repayment_channel']
    selected_date = datetime.strptime(data['selected_date'], '%Y-%m-%d').date()
    chosen_backup_va = data['chosen_backup_va']
    exclude_partner_ids = Partner.objects.filter(
        name__in=PartnerConstant.excluded_for_crm()
    ).values_list('id', flat=True)

    # get active loans that are ranging from selected_date -7 to selected_date + 2
    loans = (
        Loan.objects.filter(
            loan_status_id__gte=LoanStatusCodes.CURRENT,
            loan_status_id__lt=LoanStatusCodes.RENEGOTIATED,
        )
        .exclude(application__partner__id__in=exclude_partner_ids)
        .values_list('id', flat=True)
    )

    start_date = selected_date - timedelta(days=7)
    end_date = selected_date + timedelta(days=2)

    active_loans = (
        Payment.objects.filter(
            loan_id__in=loans,
            payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            due_date__range=(start_date, end_date),
        )
        .order_by('loan', 'id')
        .distinct('loan')
        .values_list('loan', flat=True)
    )

    if active_loans is None:
        return JsonResponse(
            {'status': 'failed', 'msg': 'no active payments between d + 2 and d - 7'}
        )

    try:
        with transaction.atomic():
            primary_loans = PaymentMethod.objects.filter(
                loan__in=active_loans, bank_code=primary_repayment_channel, is_primary=True
            ).values_list('loan', flat=True)

            # make sure that the loan has both primary and backup va
            affected_loans = PaymentMethod.objects.filter(
                loan__in=primary_loans, bank_code=chosen_backup_va, is_primary=False
            ).values_list('loan', flat=True)

            PaymentMethod.objects.filter(
                loan__in=affected_loans,
                bank_code=primary_repayment_channel,
                is_primary=True,
            ).update(udate=datetime.now(), is_primary=False, is_affected=True)

            PaymentMethod.objects.filter(
                loan__in=affected_loans, is_primary=False, bank_code=chosen_backup_va
            ).update(udate=datetime.now(), is_primary=True, is_shown=True, is_affected=True)
    except DatabaseError:
        return JsonResponse({'status': 'failed', 'msg': 'database error'})

    send_all_notification_to_customer_notify_backup_va.delay(active_loans)

    return JsonResponse({'status': 'success', 'msg': 'backup va successfully activated'})


@julo_login_required
@julo_login_required_group(JuloUserRoles.CHANGE_OF_PAYMENT_VISIBILITY)
def dashboard_change_of_payment_visibility(request):
    role_name = JuloUserRoles.CHANGE_OF_PAYMENT_VISIBILITY
    create_or_update_role(request.user, role_name)
    return render(
        request,
        'object/dashboard/change_of_payment_visibility.html',
        {
            'PROJECT_URL': PROJECT_URL,
            'role_name': role_name,
        },
    )


def get_payment_visibility_details(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed("GET")

    data = request.GET.dict()
    application_id = data['appln_id'].strip()
    response_data = {'application_det': {}, 'payment_methods': [], 'msg': '', 'status': ''}

    if not application_id or not application_id.isnumeric():
        response_data['msg'] = 'Please enter a valid application no.'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})
    application = Application.objects.get_or_none(pk=application_id)
    if application is None:
        response_data['msg'] = 'No application found'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})
    if not hasattr(application, 'loan') or application.loan is None:
        response_data['msg'] = 'No loan found for this application'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})
    payment_methods = PaymentMethod.objects.filter(loan=application.loan)
    if not payment_methods:
        response_data['msg'] = 'No channel found for application {}'.format(application_id)
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})
    response_data['application_det'] = json.loads(serializers.serialize('json', [application]))[0]
    response_data['payment_methods'] = [
        {
            'id': payment_method.id,
            'name': payment_method.payment_method_name,
            'channel_type': 'Primary' if payment_method.is_primary else 'Back-up',
            'is_shown': payment_method.is_shown,
        }
        for payment_method in payment_methods
    ]
    response_data['loan'] = application.loan.id
    response_data['status'] = 'success'
    return JsonResponse({'data': response_data})


def update_payments_visibility(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed("POST")
    data = request.POST
    response_data = {'application_det': {}, 'payment_methods': [], 'msg': '', 'status': 'success'}
    payment_methods = json.loads(data.get('payment_methods'))
    try:
        with transaction.atomic():
            for update_data in payment_methods:
                payment_method_id = update_data['id']
                payment_method = PaymentMethod.objects.get(id=payment_method_id)
                payment_method.update_safely(
                    is_shown=update_data['is_shown'], edited_by=request.user
                )

                response_data['payment_methods'].append(
                    {
                        'id': payment_method.id,
                        'name': payment_method.payment_method_name,
                        'channel_type': 'Primary' if payment_method.is_primary else 'Back-up',
                        'is_shown': payment_method.is_shown,
                    }
                )
    except (IntegrityError, ObjectDoesNotExist) as e:
        sentry_client.captureException()
        logger.error({'action': 'dashboard_ops_payment_method', 'errors': str(e)})
        response_data['status'] = 'failure'
        response_data['msg'] = 'Wrong payment methods data'

    return JsonResponse({'data': response_data})


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_FIELD_AGENT)
def dashboard_agent_field(request):
    role_name = JuloUserRoles.COLLECTION_FIELD_AGENT
    create_or_update_role(request.user, role_name)
    return agent_field_dashboard(request)


@julo_login_required
@julo_login_required_group(JuloUserRoles.BO_GENERAL_CS)
def dashboard_bo_general_cs(request):
    role_name = JuloUserRoles.BO_GENERAL_CS
    create_or_update_role(request.user, role_name)
    url = reverse('app_status:list')
    return redirect(url)


def get_repayment_channel_details_axiata(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed["POST"]

    data = request.POST.dict()
    application_id = data['application_id'].strip()
    submit_type = data['submit_type']
    response_data = {'application_det': {}, 'payment_methods': {}, 'msg': '', 'status': ''}

    if not application_id:
        response_data['msg'] = 'Plese enter a valid application no.'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})

    if not application_id.isnumeric():
        response_data['msg'] = 'Plese enter a valid application no.'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})

    application = Application.objects.get_or_none(pk=application_id)
    if application is None:
        response_data['msg'] = 'No application found'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})

    if application.product_line.product_line_code not in ProductLineCodes.axiata():
        response_data['msg'] = 'No axiata application found'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})

    if not hasattr(application, 'loan') or application.loan is None:
        response_data['msg'] = 'No loan found for this application'
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})

    payment_methods = (
        PaymentMethod.objects.filter(customer=application.customer)
        .select_related('customer')
        .order_by('id')
    )
    if not payment_methods:
        response_data['msg'] = 'No prefered channel found for application {}'.format(application_id)
        response_data['status'] = 'failure'
        return JsonResponse({'data': response_data})

    if submit_type == 'update':
        payments_channel = json.loads(data['selected_channel_axiata'])
        is_primary_payment_channel = json.loads(data['select_payment_channel_primary'])
        is_shown_payments_channel = json.loads(data['payment_channel_is_shown'])
        if not payments_channel:
            msg = 'No repayment channel selected for application {}'.format(application_id)
            response_data['msg'] = msg
            response_data['status'] = 'failure'
            return JsonResponse({'data': response_data})

        payment_ids = []
        for payment in payments_channel:
            payment_ids.append(payment['id'])

        # Validate is Primary channel selected in payments_channel
        if is_primary_payment_channel:
            payment_primary_id = is_primary_payment_channel['id']
            if payment_primary_id not in payment_ids:
                msg = 'Invalid update, please ceklist primary with activate channel {}'.format(
                    application_id
                )
                response_data['msg'] = msg
                response_data['status'] = 'failure'
                return JsonResponse({'data': response_data})

        # Validate is show payment channel, should be in
        shown_payments_channel_ids = []
        if is_shown_payments_channel:
            for payment in is_shown_payments_channel:
                shown_payments_channel_ids.append(payment['id'])

            is_invalid_selected_payment = []
            for shown_payments_channel_id in shown_payments_channel_ids:
                if shown_payments_channel_id not in payment_ids:
                    is_invalid_selected_payment.append(shown_payments_channel_id)

            if is_invalid_selected_payment:
                msg = 'Invalid update, please ceklist shown with activate channel {}'.format(
                    application_id
                )
                response_data['msg'] = msg
                response_data['status'] = 'failure'
                return JsonResponse({'data': response_data})

        PaymentMethod.objects.filter(customer=application.customer).select_related(
            'customer'
        ).update(loan=None)
        PaymentMethod.objects.filter(id__in=payment_ids).order_by('id').update(
            loan=application.loan
        )

        if is_primary_payment_channel:
            PaymentMethod.objects.filter(customer=application.customer, is_primary=True).order_by(
                'id'
            ).update(is_primary=False, is_affected=True)

            payment_primary_id = is_primary_payment_channel['id']
            PaymentMethod.objects.filter(id=payment_primary_id).order_by('id').update(
                is_primary=True, is_shown=True, is_affected=True
            )

        if shown_payments_channel_ids:
            PaymentMethod.objects.filter(customer=application.customer, is_shown=True).order_by(
                'id'
            ).exclude(is_primary=True).update(is_shown=False, is_affected=True)

            PaymentMethod.objects.filter(id__in=shown_payments_channel_ids).order_by('id').update(
                is_shown=True, is_affected=True
            )

        payment_methods = (
            PaymentMethod.objects.filter(customer=application.customer)
            .select_related('customer')
            .order_by('id')
        )

    response_data['application_det'] = json.loads(serializers.serialize('json', [application]))[0]
    response_data['payment_methods'] = json.loads(serializers.serialize('json', payment_methods))
    response_data['loan'] = application.loan.id
    response_data['status'] = 'success'
    return JsonResponse({'data': response_data})


@julo_login_required
@julo_login_required_multigroup(["cs_admin"])
def dashboard_cs_admin(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(("GET"))

    role_name = JuloUserRoles.CS_ADMIN
    create_or_update_role(request.user, role_name)

    url = settings.CRM_BASE_URL
    return redirect(url)


@julo_login_required
@julo_login_required_multigroup(["fraudops"])
def dashboard_fraudops_geohash_list(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(("GET"))

    role_name = JuloUserRoles.FRAUD_OPS
    create_or_update_role(request.user, role_name)

    csrftoken = request.COOKIES.get('csrftoken', '')
    url = settings.CRM_REVAMP_BASE_URL + 'dashboard/fraudops/geohash/list/?csrftoken=' + csrftoken
    return redirect(url)


@julo_login_required
@julo_login_required_group(JuloUserRoles.J1_AGENT_ASSISTED_100)
def dashboard_j1_agent_assisted_100(request):
    role_name = JuloUserRoles.J1_AGENT_ASSISTED_100
    create_or_update_role(request.user, role_name)

    return render(
        request,
        'object/dashboard/j1_agent_assisted_100.html',
        {
            'app_dashboard': application_dashboard(),
            'app_priority_dashboard': application_priority_dashboard(),
            'status_color': load_color(),
            'PROJECT_URL': PROJECT_URL,
            'role_name': role_name,
        },
    )
