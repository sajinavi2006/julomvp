# coding=utf-8


from app_status.services import app_locked_data_user
from dashboard.functions import get_selected_role, list_status_menu, user_roles_data
from juloserver.balance_consolidation.services import get_locked_consolidation_verifications
from juloserver.channeling_loan.services.general_services import get_crm_channeling_loan_list
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from django.conf import settings
from payment_status.services import payment_locked_data_user

from juloserver.cfs.services.core_services import get_locked_assignment_verifications
from juloserver.julo_financing.services.verification_related import (
    get_locked_j_financing_verifications,
)

DATABASE_DEFAULT = getattr(settings, 'DATABASE_DEFAULT', 'default')
PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://localhost:8000')
DATABASES = getattr(settings, 'DATABASES', {})
INSTALLED_APPS = getattr(settings, 'INSTALLED_APPS', tuple())


def julo(request):
    if request.user.is_authenticated():
        julo_current_role = get_selected_role(request.user)
    else:
        julo_current_role = request.user

    no_logo = (
        u'<img src="/static/images/profile/no-logo-1.png" '
        u'alt="company-logo" '
        u'width="36" '
        u'class="img-circle"/>'
    )
    ret_dict_out = {
        'PROJECT_URL': PROJECT_URL,
        'julo_roles': user_roles_data(request),
        'julo_current_role': julo_current_role,
        'nav_profile_logo': no_logo,
        'app_menu': list_status_menu('application'),
        'loan_menu': list_status_menu('loan'),
        'payment_menu': list_status_menu('payment'),
        'account_menu': list_status_menu('account'),
        # 'payment_and_app_locked_data_all': payment_and_app_locked_data_all(request)
    }
    if julo_current_role == JuloUserRoles.BO_FINANCE:
        ret_dict_out['channeling_menu_list'] = get_crm_channeling_loan_list()

    if not request.path.startswith('/account_payment_status/'):
        ret_dict_out['app_locked_data_user'] = app_locked_data_user(request)
        ret_dict_out['payment_locked_data_user'] = payment_locked_data_user(request)

    if request.path.startswith('/cfs/') and request.user:
        agent = request.user.agent
        ret_dict_out[
            'cfs_assignment_verification_locked_data_user'
        ] = get_locked_assignment_verifications(agent.id)

    if request.path.startswith('/balance-consolidation/') and request.user:
        agent = request.user.agent
        ret_dict_out[
            'balance_consolidation_verification_locked_data_user'
        ] = get_locked_consolidation_verifications(agent.id)

    if request.path.startswith('/julo-financing/') and request.user:
        agent = request.user.agent
        ret_dict_out[
            'j_financing_verification_locked_data_user'
        ] = get_locked_j_financing_verifications(agent.id)

    return ret_dict_out


def app(request):
    return {'INSTALLED_APPS': INSTALLED_APPS}


def saledashboard(request):
    return {'HELLO': 'Hello World'}
