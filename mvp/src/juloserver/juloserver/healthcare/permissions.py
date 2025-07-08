from rest_framework.permissions import IsAuthenticated

from juloserver.julo.statuses import ApplicationStatusCodes, JuloOneCodes


class HealthCarePermission(IsAuthenticated):
    def has_permission(self, request, view):
        if not super(HealthCarePermission, self).has_permission(request, view):
            return False

        account = request.user.customer.account
        if not account:
            return False

        application = account.get_active_application()
        if application.is_jstarter:
            if application.status < ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED:
                return False
        else:
            # Application status must be x190
            if application.status != ApplicationStatusCodes.LOC_APPROVED:
                return False

            # Account status must be x420
            if account.status.status_code != JuloOneCodes.ACTIVE:
                return False

        return True
