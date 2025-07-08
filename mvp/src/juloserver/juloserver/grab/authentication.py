from rest_framework import exceptions
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.partnership.security import PartnershipAuthentication, get_token_and_username


class GrabPartnerAuthentication(PartnershipAuthentication):

    def authenticate(self, request):
        token, username = get_token_and_username(request)
        user, token = super().authenticate_credentials(token)
        self.check_partner(user, username)

        return user, token

    def check_partner(self, user, partner_username):
        if not hasattr(user, 'partner'):
            raise exceptions.AuthenticationFailed(ErrorMessageConst.NOT_PARTNER)
        elif not user.partner.is_active:
            raise exceptions.AuthenticationFailed(ErrorMessageConst.NOT_PARTNER)
        elif not user.partner.is_grab:
            raise exceptions.AuthenticationFailed(ErrorMessageConst.INVALID_PARTNER)
