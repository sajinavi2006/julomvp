from __future__ import unicode_literals

from itertools import chain

from dashboard.models import CRMSetting
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User
from django_request_cache import cache_for_request

from juloserver.julo.models import StatusLookup
from juloserver.sales_ops.constants import SalesOpsRoles

from .constants import JuloUserRoles


def set_roles_url(role_name):
    if role_name == JuloUserRoles.ADMIN_FULL:
        ret_url = "dashboard:admin_full"
    elif role_name == JuloUserRoles.ADMIN_READ_ONLY:
        ret_url = "dashboard:bo_data_verifier"
    elif role_name == JuloUserRoles.BO_FULL:
        ret_url = "dashboard:bo_data_verifier"
    elif role_name == JuloUserRoles.BO_READ_ONLY:
        ret_url = "dashboard:bo_data_verifier"
    elif role_name == JuloUserRoles.BO_SD_VERIFIER:
        ret_url = "dashboard:bo_sd_verifier"
    elif role_name == JuloUserRoles.BO_DATA_VERIFIER:
        ret_url = "dashboard:bo_data_verifier"
    elif role_name == JuloUserRoles.BO_CREDIT_ANALYST:
        ret_url = "dashboard:bo_credit_analyst"
    elif role_name == JuloUserRoles.BO_OUTBOUND_CALLER:
        ret_url = "dashboard:bo_data_verifier"
    elif role_name == JuloUserRoles.BO_OUTBOUND_CALLER_3rd_PARTY:
        ret_url = "dashboard:bo_outbound_caller_3rd_party"
    elif role_name == JuloUserRoles.BO_FINANCE:
        ret_url = "dashboard:bo_finance"
    elif role_name == JuloUserRoles.PARTNER_FULL:
        ret_url = "dashboard:bo_data_verifier"
    elif role_name == JuloUserRoles.PARTNER_READ_ONLY:
        ret_url = "dashboard:bo_data_verifier"
    elif role_name == JuloUserRoles.JULO_PARTNERS:
        ret_url = "dashboard:lender_list_page"
    elif role_name == JuloUserRoles.ACTIVITY_DIALER:
        ret_url = "dashboard:activity_dialer_upload"
    elif role_name == JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_2A:
        ret_url = "dashboard:collection_agent_partnership_bl_2a"
    elif role_name == JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_2B:
        ret_url = "dashboard:collection_agent_partnership_bl_2b"
    elif role_name == JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_3A:
        ret_url = "dashboard:collection_agent_partnership_bl_3a"
    elif role_name == JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_3B:
        ret_url = "dashboard:collection_agent_partnership_bl_3b"
    elif role_name == JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_4:
        ret_url = "dashboard:collection_agent_partnership_bl_4"
    elif role_name == JuloUserRoles.COLLECTION_AGENT_PARTNERSHIP_BL_5:
        ret_url = "dashboard:collection_agent_partnership_bl_5"
    elif role_name == JuloUserRoles.OPS_TEAM_LEADER:
        ret_url = "dashboard:ops_team_leader"
    elif role_name == JuloUserRoles.CS_ADMIN:
        ret_url = "dashboard:cs_admin_dashboard"
    elif role_name in chain(
        JuloUserRoles.collection_roles(),
        JuloUserRoles.collection_bucket_roles(),
        [JuloUserRoles.COLLECTION_SUPERVISOR],
    ):
        return reverse('dashboard:all_collection_dashboard', args=[role_name])
    elif role_name == JuloUserRoles.CHANGE_OF_REPAYMENT_CHANNEL:
        ret_url = "dashboard:change_of_repayment_channel"
    elif role_name == JuloUserRoles.CHANGE_OF_PAYMENT_VISIBILITY:
        ret_url = "dashboard:change_of_payment_visibility"
    elif role_name == JuloUserRoles.BUSINESS_DEVELOPMENT:
        ret_url = "lender:registration"
    elif role_name == JuloUserRoles.PRODUCT_MANAGER:
        ret_url = "streamlined:list"
    elif role_name == JuloUserRoles.BO_GENERAL_CS:
        ret_url = "dashboard:bo_general_cs"
    elif role_name == SalesOpsRoles.SALES_OPS:
        ret_url = "sales_ops.crm:list"
    elif role_name == JuloUserRoles.FRAUD_OPS:
        ret_url = "dashboard:fraudops"
    elif role_name == JuloUserRoles.J1_AGENT_ASSISTED_100:
        ret_url = "dashboard:j1_agent_assisted_100"
    elif role_name == JuloUserRoles.COLLECTION_FIELD_AGENT:
        ret_url = "dashboard:collection_field_agent"
    elif role_name == JuloUserRoles.COHORT_CAMPAIGN_EDITOR:
        ret_url = "cohort_campaign_automation:cohort_campaign_automation_list"
    else:
        return None
    return reverse(ret_url)  # , kwargs={'app_label': 'auth'})


def user_roles_data(request):
    ret_group_list = []
    user = request.user
    if user.is_authenticated():
        groups = list_group_name(user)
        for role in groups:
            dashboard_url = set_roles_url(role)
            if dashboard_url:
                ret_group_list.append({'role': role, 'url': dashboard_url})
    return ret_group_list


def create_or_update_role(user_instance, role_name):
    objselect, created = CRMSetting.objects.get_or_create(user=user_instance)
    objselect.role_select = role_name
    objselect.save()


@cache_for_request
def get_selected_role(user_instance):
    try:
        objselect = CRMSetting.objects.get(user=user_instance)
        return objselect.role_select
    except CRMSetting.DoesNotExist:
        return 'no-role-selected'


def create_or_update_defaultrole(user_instance, role_name):
    objselect, created = CRMSetting.objects.get_or_create(user=user_instance)
    objselect.role_default = role_name
    objselect.save()


def get_selected_defaultrole(user_instance):
    try:
        objselect = CRMSetting.objects.get(user=user_instance)
        if User.objects.filter(pk=user_instance.id, groups__name=objselect.role_default).exists():
            return objselect.role_default
        else:
            objselect.role_default = None
            objselect.save()
            return None
    except CRMSetting.DoesNotExist:
        return None


@cache_for_request
def list_group_name(user):
    return set(user.groups.values_list('name', flat=True))


def list_status_menu(type_menu):
    if type_menu == 'application':
        return [
            item.status_code
            for item in StatusLookup.objects.filter(status_code__range=[100, 190])
            .exclude(status_code=189)
            .order_by('status_code')
        ]
    elif type_menu == 'loan':
        return [
            item.status_code
            for item in StatusLookup.objects.filter(status_code__range=[200, 250]).order_by(
                'status_code'
            )
        ]
    elif type_menu == 'payment':
        return [
            item.status_code
            for item in StatusLookup.objects.filter(status_code__gte=300).order_by('status_code')
        ]
    elif type_menu == 'account':
        return [
            item.status_code
            for item in StatusLookup.objects.filter(status_code__in=[440, 441, 442, 432]).order_by(
                'status_code'
            )
        ]
    else:
        return None
