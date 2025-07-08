from functools import wraps

from juloserver.standardized_api_response.utils import (
    unauthorized_error_response,
    force_logout_response,
)
from juloserver.application_form.services.application_service import has_partner_not_allowed_reapply
from juloserver.julolog.julolog import JuloLog


logger = JuloLog(__name__)


def verify_is_allowed_user(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('User not found')

        customer = user.customer
        is_block = has_partner_not_allowed_reapply(user.customer)
        if is_block:
            logger.info(
                {
                    'message': '[Force Logout]: Set force logout by token expired for partner user',
                    'user': user.id,
                    'is_block': is_block,
                    'customer': customer.id if customer else None,
                }
            )

            # this return will be trigger force logout for customer
            return force_logout_response('Already have other product')

        return function(view, request, *args, **kwargs)

    return wrapper
