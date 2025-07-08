import logging

from juloserver.account.constants import AccountConstant
from juloserver.customer_module.constants import active_loan_status
from juloserver.customer_module.services.crm_v1 import (
    deactivate_user,
    update_customer_table_as_inactive,
)
from juloserver.customer_module.utils.utils_crm_v1 import (
    get_deletion_nik_format,
    get_deletion_phone_format,
)
from juloserver.dana.models import DanaCustomerData
from juloserver.julo.models import CustomerFieldChange
from juloserver.partnership.services.services import (
    update_application_table_as_inactive_for_partnership,
)

logger = logging.getLogger(__name__)


def soft_delete_dana_customer_multiple_lender_product_id(
    dana_customer_identifier, lender_product_ids
):
    dana_customers = DanaCustomerData.objects.filter(
        dana_customer_identifier=dana_customer_identifier, lender_product_id__in=lender_product_ids
    )
    if not dana_customers:
        logger.info(
            {
                "action": "soft_delete_dana_customer",
                "dana_customer_identifier": dana_customer_identifier,
                "lender_product_id": lender_product_ids,
                "message": "Failed to delete customer {}, because customer not found".format(
                    dana_customer_identifier
                ),
            }
        )
        print(
            "Failed to delete customer {}, because customer not found".format(
                dana_customer_identifier
            )
        )
        return
    for dana_customer in dana_customers.iterator():
        message = soft_delete_dana_customer(
            dana_customer.dana_customer_identifier, dana_customer.lender_product_id
        )
        if message != "Successfully soft deleted":
            logger.info(message)
            print(message)
            continue
        logger.info(
            {
                "action": "soft_delete_dana_customer",
                "dana_customer_identifier": dana_customer.dana_customer_identifier,
                "lender_product_id": dana_customer.lender_product_id,
                "account_id": dana_customer.account.id,
                "message": "Successfully Soft Deleted",
            }
        )
        print(message)


def soft_delete_dana_customer(dana_customer_identifier, lender_product_id):
    dana_customer = DanaCustomerData.objects.filter(
        dana_customer_identifier=dana_customer_identifier, lender_product_id=lender_product_id
    ).last()
    if not dana_customer:
        info = {
            "action": "soft_delete_dana_customer",
            "dana_customer_identifier": dana_customer_identifier,
            "lender_product_id": lender_product_id,
            "message": "Dana customer data not found, customer cannot be deleted",
        }
        return info

    customer = dana_customer.customer
    if not customer:
        info = {
            "action": "soft_delete_dana_customer",
            "dana_customer_identifier": dana_customer_identifier,
            "lender_product_id": lender_product_id,
            "message": "Customer data not found, customer cannot be deleted",
        }
        return info
    user = customer.user
    if not user:
        info = {
            "action": "soft_delete_dana_customer",
            "dana_customer_identifier": dana_customer_identifier,
            "lender_product_id": lender_product_id,
            "message": "Customer data not found, customer cannot be deleted",
        }
        return info
    applications = customer.application_set.all()
    if not applications:
        info = {
            "action": "soft_delete_dana_customer",
            "dana_customer_identifier": dana_customer_identifier,
            "lender_product_id": lender_product_id,
            "message": "Application data not found, customer cannot be deleted",
        }
        return info
    application = dana_customer.application
    nik = customer.nik

    account = application.account
    if account and account.status_id in {
        AccountConstant.STATUS_CODE.active_in_grace,
        AccountConstant.STATUS_CODE.suspended,
        AccountConstant.STATUS_CODE.fraud_reported,
        AccountConstant.STATUS_CODE.application_or_friendly_fraud,
    }:
        info = {
            "action": "soft_delete_dana_customer",
            "dana_customer_identifier": dana_customer_identifier,
            "lender_product_id": lender_product_id,
            "account_id": account.id,
            "message": "Account status in {}, customer cannot be deleted".format(account.status_id),
        }
        return info

    loans = dana_customer.customer.loan_set.filter(loan_status__in=active_loan_status).exists()
    if loans:
        info = {
            "action": "soft_delete_dana_customer",
            "dana_customer_identifier": dana_customer_identifier,
            "lender_product_id": lender_product_id,
            "account_id": account.id,
            "message": "User still have ongoing loans, customer status cannot be deleted",
        }
        return info

    deactivate_user(user, customer, nik)
    update_customer_table_as_inactive(user, customer, application)
    update_application_table_as_inactive_for_partnership(user, applications)
    update_data_dana_customer_table_as_inactive(dana_customer)
    return "Successfully soft deleted"


def update_data_dana_customer_table_as_inactive(dana_customer):
    field_changes = []
    edited_nik = get_deletion_nik_format(dana_customer.customer.id)
    field_changes.append(
        CustomerFieldChange(
            customer=dana_customer.customer,
            application=dana_customer.application,
            field_name='dana_customer_data_nik',
            old_value=dana_customer.nik,
            new_value=edited_nik,
        )
    )
    edited_phone = get_deletion_phone_format(dana_customer.customer.id)
    field_changes.append(
        CustomerFieldChange(
            customer=dana_customer.customer,
            application=dana_customer.application,
            field_name='dana_customer_data_mobile_number',
            old_value=dana_customer.mobile_number,
            new_value=edited_phone,
        )
    )

    CustomerFieldChange.objects.bulk_create(field_changes)
    dana_customer.update_safely(
        nik=edited_nik,
        mobile_number=edited_phone,
    )
