from builtins import object
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import user_passes_test

from inspect import isfunction


class _cbv_decorate(object):
    def __init__(self, dec):
        self.dec = method_decorator(dec)

    def __call__(self, obj):
        obj.dispatch = self.dec(obj.dispatch)
        return obj


def patch_view_decorator(dec):
    def _conditional(view):
        if isfunction(view):
            return dec(view)

        return _cbv_decorate(dec)(view)

    return _conditional


julo_login_required = patch_view_decorator(login_required)
julo_login_required_admin = patch_view_decorator(
                          user_passes_test(lambda u: u.groups.filter(name='admin').exists()))


def julo_login_required_group(group_name):
    return patch_view_decorator(
              user_passes_test(lambda u: u.groups.filter(name=group_name).exists()))


"""
    ex: arr_group = ['group1', 'group2']
"""
def julo_login_required_multigroup(arr_group):
    return patch_view_decorator(
              user_passes_test(lambda u: u.groups.filter(name__in=arr_group).exists()))

def julo_login_req_group_class(group_name):
    return patch_view_decorator(
            user_passes_test(lambda u: u.groups.filter(name=group_name).exists()))

def julo_login_req_group(group_name):
    return user_passes_test(lambda u: u.groups.filter(name=group_name).exists())

def julo_login_req_multigroup(arr_group):
    return user_passes_test(lambda u: u.groups.filter(name__in=arr_group).exists())

def julo_login_required_exclude(arr_group):
    return patch_view_decorator(
              user_passes_test(lambda u: u.groups.exclude(name__in=arr_group).exists()))


def user_has_collection_blacklisted_role(user):
    from juloserver.portal.object.dashboard.constants import JuloUserRoles

    if not user:
        return False

    # Define blacklisted and whitelisted roles
    collection_blacklisted_roles = {
        JuloUserRoles.COLLECTION_AGENT_1,
        JuloUserRoles.COLLECTION_AGENT_2,
        JuloUserRoles.COLLECTION_AGENT_2A,
        JuloUserRoles.COLLECTION_AGENT_2B,
        JuloUserRoles.COLLECTION_AGENT_3,
        JuloUserRoles.COLLECTION_AGENT_3A,
        JuloUserRoles.COLLECTION_AGENT_3B,
        JuloUserRoles.COLLECTION_AGENT_4,
        JuloUserRoles.COLLECTION_AGENT_5,
        JuloUserRoles.COLLECTION_BUCKET_1,
        JuloUserRoles.COLLECTION_BUCKET_2,
        JuloUserRoles.COLLECTION_BUCKET_3,
        JuloUserRoles.COLLECTION_BUCKET_4,
        JuloUserRoles.COLLECTION_BUCKET_5,
        JuloUserRoles.COLLECTION_TEAM_LEADER,
        JuloUserRoles.COLLECTION_AREA_COORDINATOR,
    }
    collection_whitelisted_roles = {JuloUserRoles.BO_DATA_VERIFIER}

    # Get user's roles as a set for efficient lookups
    user_roles = set(user.groups.values_list('name', flat=True) or [])

    # Check if the user has any whitelisted roles
    if user_roles & collection_whitelisted_roles:
        return False

    # Check if the user has any blacklisted roles
    return bool(user_roles & collection_blacklisted_roles)
