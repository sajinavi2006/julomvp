import csv
import os
import shutil
from bulk_update.helper import bulk_update
from collections import defaultdict
from django.utils import timezone
from juloserver.account.models import AccountLimit, AccountLimitHistory
from juloserver.fdc.files import TempDir
from typing import List


def update_dana_credit_limit(local_file_path: str) -> List:

    maping_dana_customer = defaultdict(int)
    with TempDir(dir="/media") as tempdir:
        path_and_name, extension = os.path.splitext(local_file_path)
        file_name_elements = path_and_name.split('/')
        filename = file_name_elements[-1] + extension
        dir_path = tempdir.path
        file_path = os.path.join(dir_path, filename)
        shutil.copy(local_file_path, file_path)

        with open(file_path) as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                dana_customer_id = int(row['account_id'])
                proposed_credit_limit = row['proposed_increased_limit'].replace(',', '')
                maping_dana_customer[dana_customer_id] = float(proposed_credit_limit)

    account_limits = AccountLimit.objects.filter(
        account__dana_customer_data__dana_customer_identifier__in=maping_dana_customer.keys()
    ).select_related(
        'account',
        'account__dana_customer_data',
        'account__dana_customer_data__customer__customerlimit',
    )

    updated_account_limit_history = []
    account_limit_updated_data = []
    customer_limit_update = []
    update_date = timezone.localtime(timezone.now())
    not_updated_limit = []
    for account_limit in account_limits.iterator():
        dana_customer_data = account_limit.account.dana_customer_data
        dana_customer_identifer = int(dana_customer_data.dana_customer_identifier)

        customer_limit = dana_customer_data.customer.customerlimit

        new_limit = maping_dana_customer[dana_customer_identifer]
        if account_limit.set_limit > new_limit:
            not_updated_limit.append(dana_customer_identifer)
            continue

        old_available_limit = account_limit.available_limit
        old_set_limit = account_limit.set_limit
        old_max_limit = account_limit.max_limit
        if (new_limit - account_limit.used_limit) < 0:
            account_limit.available_limit = 0
        else:
            account_limit.available_limit = new_limit - account_limit.used_limit

        available_account_limit_history = AccountLimitHistory(
            account_limit=account_limit,
            field_name='available_limit',
            value_old=str(old_available_limit),
            value_new=str(account_limit.available_limit),
        )
        updated_account_limit_history.append(available_account_limit_history)

        account_limit.set_limit = new_limit
        set_limit_account_limit_history = AccountLimitHistory(
            account_limit=account_limit,
            field_name='set_limit',
            value_old=str(old_set_limit),
            value_new=str(account_limit.set_limit),
        )
        updated_account_limit_history.append(set_limit_account_limit_history)

        account_limit.max_limit = new_limit
        max_limit_account_limit_history = AccountLimitHistory(
            account_limit=account_limit,
            field_name='max_limit',
            value_old=str(old_max_limit),
            value_new=str(account_limit.max_limit),
        )

        customer_limit.udate = update_date
        customer_limit.max_limit = new_limit
        account_limit.udate = update_date

        updated_account_limit_history.append(max_limit_account_limit_history)
        account_limit_updated_data.append(account_limit)
        customer_limit_update.append(customer_limit)
        print('Processed dana_customer_id: {}'.format(dana_customer_identifer))

    bulk_update(
        account_limit_updated_data,
        update_fields=['udate', 'available_limit', 'set_limit', 'max_limit'],
        batch_size=100,
    )

    bulk_update(
        customer_limit_update,
        update_fields=['udate', 'max_limit'],
        batch_size=100,
    )

    AccountLimitHistory.objects.bulk_create(updated_account_limit_history, batch_size=100)

    return not_updated_limit
