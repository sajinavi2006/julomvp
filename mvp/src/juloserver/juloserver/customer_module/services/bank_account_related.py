from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import (
    BankAccountCategory,
    BankAccountDestination,
)
from juloserver.ecommerce.models import EcommerceConfiguration
from juloserver.julo.models import PartnerBankAccount
from juloserver.payment_point.constants import TransactionMethodCode


def get_self_bank_account_destination(customer):
    bank_account_category = BankAccountCategory.objects.filter(category='self').last()
    bank_account_destination = BankAccountDestination.objects.filter(
        bank_account_category=bank_account_category, customer=customer
    ).exclude(bank__is_active=False).order_by('-cdate')
    return bank_account_destination


def get_other_bank_account_destination(customer, exclude_partner=True):
    bank_account_destination = (
        BankAccountDestination.objects.filter(customer=customer).exclude(
            bank_account_category__category__in=[
                BankAccountCategoryConst.SELF,
                BankAccountCategoryConst.ECOMMERCE,
                BankAccountCategoryConst.EDUCATION,
                BankAccountCategoryConst.HEALTHCARE,
                BankAccountCategoryConst.EWALLET,
                BankAccountCategoryConst.BALANCE_CONSOLIDATION,
            ]
        ).exclude(bank__is_active=False).order_by('-name_bank_validation__name_in_bank')
    )
    if exclude_partner:
        bank_account_destination = bank_account_destination.exclude(
            bank_account_category__category=BankAccountCategoryConst.PARTNER
        )
    return bank_account_destination


def is_ecommerce_bank_account(bank_account_destination):
    if (
        bank_account_destination
        and bank_account_destination.bank_account_category.category
        == BankAccountCategoryConst.ECOMMERCE
        and EcommerceConfiguration.objects.filter(
            ecommerce_name__iexact=bank_account_destination.description
        ).exists()
    ):
        return True

    return False


def get_bank_account_destination_by_transaction_method(
    bank_account_destination_id, customer, transaction_method_id
):
    query_filter = dict(
        pk=bank_account_destination_id,
        customer=customer,
        bank_account_category__category=BankAccountCategoryConst.SELF,
    )

    if transaction_method_id == TransactionMethodCode.E_COMMERCE.code:
        query_filter['bank_account_category__category'] = BankAccountCategoryConst.ECOMMERCE
    elif transaction_method_id == TransactionMethodCode.OTHER.code:
        del query_filter['bank_account_category__category']
        query_filter[
            'bank_account_category__category__in'
        ] = BankAccountCategoryConst.transfer_dana_categories()

    bank_account_destination = BankAccountDestination.objects.filter(**query_filter).last()

    return bank_account_destination


def get_bank_account_destination_by_transaction_method_partner(
    customer, transaction_method_id, partner
):
    partner_name_bank_validation_ids = PartnerBankAccount.objects.filter(
        partner=partner
    ).values_list('name_bank_validation_id', flat=True)
    query_filter = dict(
        customer=customer,
        bank_account_category__category=BankAccountCategoryConst.SELF,
        name_bank_validation__in=partner_name_bank_validation_ids,
    )

    if transaction_method_id == TransactionMethodCode.E_COMMERCE.code:
        query_filter['bank_account_category__category'] = BankAccountCategoryConst.ECOMMERCE
    elif transaction_method_id == TransactionMethodCode.OTHER.code:
        del query_filter['bank_account_category__category']
        query_filter[
            'bank_account_category__category__in'
        ] = BankAccountCategoryConst.transfer_dana_categories()

    bank_account_destination = BankAccountDestination.objects.filter(**query_filter).last()
    return bank_account_destination
