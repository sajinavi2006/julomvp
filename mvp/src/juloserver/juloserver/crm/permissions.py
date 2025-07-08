import logging

from django.contrib.auth.models import User
from rest_framework import permissions

from .constants import AGENT_USER_GROUP

logger = logging.getLogger(__name__)


class IsAuthenticatedAgent(permissions.IsAuthenticated):

    def has_permission(self, request, view):
        if not super(IsAuthenticatedAgent, self).has_permission(request, view):
            logger.warn({
                'status': 'not_authenticated',
                'user': request.user
            })
            return False

        user_groups = request.user.groups.values_list('name', flat=True)

        if not list(set(AGENT_USER_GROUP) & set(user_groups)):
            logger.warn({
                'status': 'not_in_correct_group',
                'user': request.user
            })
            return False

        logger.info({
            'status': 'has_permission',
            'user': request.user
        })
        return True


def has_user_groups(user: User, groups: list) -> bool:
    """
    Check if the user has the groups
    Args:
        user (User): The authenticated user object.
        groups (list): list of the group name.

    Returns:
        bool: True if the user has the groups, False otherwise.
    """
    return user.groups.filter(name__in=groups).exists()
