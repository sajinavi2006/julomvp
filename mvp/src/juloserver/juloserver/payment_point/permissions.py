from rest_framework.permissions import IsAuthenticated

from juloserver.account.constants import AccountConstant


class TrainTicketPermission(IsAuthenticated):
    def has_permission(self, request, view):
        if not super(TrainTicketPermission, self).has_permission(request, view):
            return False

        account = request.user.customer.account
        if not account:
            return False

        application = account.get_active_application()
        if not (
            application.is_julover()
            or application.is_julo_one_product()
            or application.is_julo_starter()
        ):
            return False

        if application.account.status_id != AccountConstant.STATUS_CODE.active:
            return False

        return True
