from functools import wraps
from cryptography.fernet import InvalidToken
from juloserver.julo.models import Customer
from juloserver.balance_consolidation.services import BalanceConsolidationToken
from juloserver.standardized_api_response.utils import not_found_response


def handle_token_decryption(view_func):
    @wraps(view_func)
    def wrapper(view, request, *args, **kwargs):
        try:
            token_obj = BalanceConsolidationToken()
            customer_id, _ = token_obj.decrypt_token_balance_cons_submit(kwargs['token'])
        except InvalidToken:
            return not_found_response(
                'Link formulir sudah kedaluwarsa. Silakan hubungi CS kami '
                'untuk dapatkan link formulir perpindahan dana lagi, ya!'
            )
        except ValueError:
            return not_found_response('Failed to decrypt Token')

        customer = Customer.objects.get_or_none(pk=customer_id)
        if not customer:
            return not_found_response('Customer not found')
        kwargs['customer'] = customer
        if request.method == 'POST':
            request.data['username'] = customer.email
            request.data['latitude'] = 0.0
            request.data['longitude'] = 0.0
        return view_func(view, request, *args, **kwargs)

    return wrapper
