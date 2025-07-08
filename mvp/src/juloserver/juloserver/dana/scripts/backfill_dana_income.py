from juloserver.dana.models import DanaCustomerData
from django.utils import timezone
from bulk_update.helper import bulk_update

from juloserver.julo.models import Application, CustomerFieldChange, ApplicationFieldChange


def backfill_dana_income(customer_ids, mapping_income):
    updated_dana_customers = []
    updated_applications = []
    updated_customers = []

    create_customer_field_changes = []
    create_application_field_changes = []

    errors = {}

    dana_customers = DanaCustomerData.objects.select_related("customer").filter(
        customer_id__in=customer_ids
    )
    for dana_customer in dana_customers.iterator():
        udate = timezone.localtime(timezone.now())
        income = mapping_income.get(dana_customer.customer_id)

        if not income:
            errors[dana_customer.customer_id] = "income doesnt found"
            continue

        dana_customer.income = income
        dana_customer.udate = udate

        customer = dana_customer.customer
        old_income = customer.monthly_income
        customer.monthly_income = income
        customer.udate = udate

        updated_dana_customers.append(dana_customer)
        updated_customers.append(customer)
        create_customer_field_changes.append(
            CustomerFieldChange(
                application_id=dana_customer.application_id,
                customer=customer,
                field_name="monthly_income",
                old_value=old_income,
                new_value=customer.monthly_income,
            )
        )

    applications = Application.objects.filter(customer_id__in=customer_ids)
    for application in applications.iterator():
        udate = timezone.localtime(timezone.now())
        income = mapping_income.get(application.customer_id)

        if not income:
            errors[application.customer_id] = "income doesnt found"
            continue

        old_income = application.monthly_income
        application.monthly_income = income
        application.udate = udate

        updated_applications.append(application)
        create_application_field_changes.append(
            ApplicationFieldChange(
                application=application,
                field_name="monthly_income",
                old_value=old_income,
                new_value=application.monthly_income,
            )
        )

    bulk_update(
        updated_dana_customers,
        update_fields=['udate', 'income'],
        batch_size=100,
    )
    bulk_update(
        updated_customers,
        update_fields=['udate', 'monthly_income'],
        batch_size=100,
    )
    bulk_update(
        updated_applications,
        update_fields=['udate', 'monthly_income'],
        batch_size=100,
    )

    CustomerFieldChange.objects.bulk_create(create_customer_field_changes, batch_size=100)
    ApplicationFieldChange.objects.bulk_create(create_application_field_changes, batch_size=100)

    return errors


"""
expectation
how to call batching_backfill_dana_income(data)
data = [
    {'customer_id':customer1, 'income':income_customer1},
    {'customer_id':customer2, 'income':income_customer2},
    etc...
]
"""


def batching_backfill_dana_income(data):
    mapping_income = {}

    for item in data:
        mapping_income[item["customer_id"]] = item["income"]

    limiter = 1000

    list_customer_ids = []
    errors = []
    for key in mapping_income:
        if len(list_customer_ids) >= limiter:
            err = backfill_dana_income(list_customer_ids, mapping_income)
            errors.append(err)
            list_customer_ids = []

        list_customer_ids.append(key)

    if list_customer_ids:
        err = backfill_dana_income(list_customer_ids, mapping_income)
        errors.append(err)

    print(errors)
