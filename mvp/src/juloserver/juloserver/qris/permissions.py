import logging
from juloserver.julo.models import Partner
from juloserver.application_flow.constants import PartnerNameConstant
from rest_framework import permissions

logger = logging.getLogger(__name__)


class QRISPartnerPermission(permissions.IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False

        return Partner.objects.filter(
            user_id=request.user.pk,
            partner_xid=request.META.get('HTTP_PARTNERXID'),
            name__in=PartnerNameConstant.qris_partners(),
        ).exists()
