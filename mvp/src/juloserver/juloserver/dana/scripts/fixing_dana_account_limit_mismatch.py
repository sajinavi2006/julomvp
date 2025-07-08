from bulk_update.helper import bulk_update
from collections import defaultdict

from juloserver.account.models import AccountLimit, AccountLimitHistory
from juloserver.account_payment.models import AccountPayment

from typing import List


def re_calculate_account_limit(account_ids: List) -> None:
    dana_users_account_limit = AccountLimit.objects.filter(account_id__in=account_ids)
    dana_account_payments = AccountPayment.objects.filter(account_id__in=account_ids)

    mapping_account_limit_dict = defaultdict(int)

    for account_payment in dana_account_payments.iterator():
        account_id = account_payment.account_id
        principal_amount = account_payment.principal_amount
        interest_amount = account_payment.interest_amount
        paid_principal = account_payment.paid_principal
        paid_interest = account_payment.paid_interest

        total_used_limit = (principal_amount - paid_principal) + (interest_amount - paid_interest)
        mapping_account_limit_dict[account_id] += total_used_limit
        print('Successfully mapping limit account_id: {}'.format(account_id))

    account_limit_updated_data = []
    updated_account_limit_history = []
    for dana_account_limit in dana_users_account_limit.iterator():
        used_limit = mapping_account_limit_dict.get(dana_account_limit.account_id, 0)
        available_limit = dana_account_limit.max_limit - used_limit

        current_available_limit = dana_account_limit.available_limit
        current_used_limit = dana_account_limit.used_limit
        if current_available_limit != available_limit or current_used_limit != used_limit:

            account_limit_history = AccountLimitHistory(
                account_limit=dana_account_limit,
                field_name='available_limit',
                value_old=str(current_available_limit),
                value_new=str(available_limit),
            )
            updated_account_limit_history.append(account_limit_history)
            dana_account_limit.available_limit = available_limit

            account_limit_history = AccountLimitHistory(
                account_limit=dana_account_limit,
                field_name='used_limit',
                value_old=str(current_used_limit),
                value_new=str(used_limit),
            )
            updated_account_limit_history.append(account_limit_history)
            dana_account_limit.used_limit = used_limit

        account_limit_updated_data.append(dana_account_limit)

        print('Succes to update limit on account_id: {}'.format(dana_account_limit.account_id))

    bulk_update(
        account_limit_updated_data, update_fields=['available_limit', 'used_limit'], batch_size=100
    )
    AccountLimitHistory.objects.bulk_create(updated_account_limit_history, batch_size=100)

    return account_limit_updated_data
