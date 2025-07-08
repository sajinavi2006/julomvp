from juloserver.customer_module.models import (
    BankAccountCategory,
    BankAccountDestination,
)


def grab_get_self_bank_account_destination(customer):
    bank_account_category = BankAccountCategory.objects.filter(category='self').last()
    bank_account_destination = BankAccountDestination.objects.filter(
        bank_account_category=bank_account_category, customer=customer
    ).exclude(bank__is_active=False)
    return bank_account_destination
