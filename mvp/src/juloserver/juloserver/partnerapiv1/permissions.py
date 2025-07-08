import logging

from rest_framework import permissions

from .constants import PARTNER_GROUP_NAME

logger = logging.getLogger(__name__)


class IsAuthenticatedPartner(permissions.IsAuthenticated):
    def has_permission(self, request, view):

        if not super(IsAuthenticatedPartner, self).has_permission(request, view):
            logger.warn({'status': 'not_authenticated', 'user': request.user})
            return False

        user_groups = request.user.groups.values_list('name', flat=True)
        if PARTNER_GROUP_NAME not in user_groups:
            logger.warn({'status': 'not_in_correct_group', 'user': request.user})
            return False

        logger.info({'status': 'has_permission', 'user': request.user})
        return True


class MerchantPartnerSellerAppPermission(permissions.BasePermission):
    """
    Object-level permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        return obj.partner and obj.partner.name == "laku6" and obj.status == 130

    def has_permission(self, request, view):
        return hasattr(request.user, 'partner') and request.user.partner.name == "laku6"
