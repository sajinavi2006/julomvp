from typing import Union

from django.db.models import (
    Prefetch,
)

from juloserver.julo.models import Application, Customer
from juloserver.new_crm.services.application_services import (
    get_application_status_histories,
)


def get_customer(nik: str = None, email: str = None) -> Union[Customer, None]:
    """
    Get customer by nik and email with prefetched application data
    """

    customer = (
        Customer.objects.filter(email=email, nik=nik)
        .prefetch_related(
            Prefetch(
                "application_set",
                to_attr="prefetched_applications",
                queryset=Application.objects.select_related(
                    "account", "product_line", "creditscore"
                ).order_by('-id'),
            ),
        )
        .prefetch_related(
            Prefetch(
                "application_set",
                to_attr="prefetched_active_applications",
                queryset=Application.objects.select_related(
                    "account", "product_line", "creditscore"
                ).filter(application_status=190),
            ),
        )
        .first()
    )
    return customer


def get_history_list(
    customer: Customer,
) -> list:

    application = customer.get_active_or_last_application

    return get_application_status_histories(application)
