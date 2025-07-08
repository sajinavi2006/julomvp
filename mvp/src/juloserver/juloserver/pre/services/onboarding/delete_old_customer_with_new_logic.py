from juloserver.julo.models import (
    Customer,
    ApplicationFieldChange,
)
from django.db.models import Q
from bulk_update.helper import bulk_update
from django.db import transaction

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from juloserver.customer_module.services.crm_v1 import (
    deactivate_user,
    update_customer_table_as_inactive,
)
from juloserver.customer_module.utils.utils_crm_v1 import (
    get_deletion_email_format,
    get_deletion_nik_format,
    get_deletion_phone_format,
    get_email_from_applications,
    get_phone_from_applications,
)
from juloserver.julo.models import ApplicationHistory, CustomerRemoval
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.pre.services.common import track_agent_retrofix
from juloserver.julo.models import (
    Application,
)


# IF YOU RUN THIS, PLEASE CHANGE EXECUTOR !!!
# from juloserver.julo.clients import get_julo_sentry_client
import logging

logger = logging.getLogger(__name__)


def deactivate_applications(agent, applications):
    field_changes = []
    history_changes = []
    for application in applications:
        field_changes.append(
            ApplicationFieldChange(
                application=application,
                field_name='is_deleted',
                old_value=application.is_deleted,
                new_value=True,
                agent=agent,
            )
        )
        application.is_deleted = True

        if application.ktp:
            edited_ktp = get_deletion_nik_format(application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='ktp',
                    old_value=application.ktp,
                    new_value=edited_ktp,
                    agent=agent,
                )
            )
            application.ktp = edited_ktp

        if application.email:
            edited_email = get_deletion_email_format(application.email, application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='email',
                    old_value=application.email,
                    new_value=edited_email,
                    agent=agent,
                )
            )
            application.email = edited_email

        if application.mobile_phone_1:
            edited_phone = get_deletion_phone_format(application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='mobile_phone_1',
                    old_value=application.mobile_phone_1,
                    new_value=edited_phone,
                    agent=agent,
                )
            )
            application.mobile_phone_1 = edited_phone

        history_changes.append(
            ApplicationHistory(
                application=application,
                status_old=application.application_status_id,
                status_new=ApplicationStatusCodes.CUSTOMER_DELETED,
                changed_by=agent,
                change_reason='manual delete by script',
            )
        )
        application.application_status_id = ApplicationStatusCodes.CUSTOMER_DELETED

    ApplicationFieldChange.objects.bulk_create(field_changes)
    ApplicationHistory.objects.bulk_create(history_changes)
    bulk_update(
        applications,
        update_fields=['ktp', 'is_deleted', 'email', 'mobile_phone_1', 'application_status_id'],
    )


def _latest_app_is_old_product(last_application):
    if not (
        last_application.product_line_id in (10, 11, 20, 21, 30, 31)
        or last_application.product_line_id is None
    ):
        return False
    return True


def _last_app_j1_or_jturbo_but_have_old_product(customer):
    last_app = Application.objects.filter(customer_id=customer.id).last()
    if last_app.product_line_id not in (1, 2):
        return False
    have_old_product = Application.objects.filter(
        Q(customer_id=customer.id)
        & (Q(product_line_id__in=[10, 11, 20, 21, 30, 31]) | Q(product_line_id__isnull=True))
    )
    if not have_old_product:
        return False
    return True


def do_new_delete_customer_based_on_api_logic(
    customer_id, reason, executor_user, only_old_customer=False
):
    from juloserver.customer_module.utils.utils_crm_v1 import (
        get_nik_from_applications,
        get_active_loan_ids,
    )

    from juloserver.moengage.services.use_cases import (
        send_user_attributes_to_moengage_for_realtime_basis,
    )

    customer = Customer.objects.filter(pk=customer_id).exclude(is_active=False, can_reapply=False)
    if not customer.exists():
        raise Exception("akun tidak ditemukan")

    customer = customer.last()

    if customer.is_active is False and customer.can_reapply is False:
        raise Exception("customer id tidak ditemukan")

    applications = customer.application_set.all()
    application = applications.last()

    if only_old_customer:
        if not (
            _latest_app_is_old_product(application)
            or _last_app_j1_or_jturbo_but_have_old_product(customer)
        ):
            raise Exception(
                "last app is not old product OR last app is j1/jturbo but dont have old product"
            )

    logger.info(
        {
            'method': 'do_new_delete_customer_based_on_api_logic',
            "status": "start",
            'data': {
                'is_deleted': True,
                'customer_id': customer.pk,
                'application_id': application.pk,
            },
        }
    )

    loan_ids = get_active_loan_ids(customer)
    nik = customer.nik or get_nik_from_applications(applications)
    phone = customer.phone or get_phone_from_applications(applications)
    email = customer.email or get_email_from_applications(applications)
    if loan_ids:
        raise Exception("masih punya loan berjalan")

    logger.info(
        {
            'method': 'do_new_delete_customer_based_on_api_logic',
            "status": "ready to delete",
            'data': {
                'is_deleted': True,
                'customer_id': customer.pk,
                'application_id': application.pk,
            },
        }
    )
    current_cr = CustomerRemoval.objects.filter(user_id=customer.user_id).last()
    with transaction.atomic():
        if current_cr:
            current_cr.delete()
        update_customer_table_as_inactive(
            executor_user,
            customer,
            application,
        )
        deactivate_applications(
            executor_user,
            applications,
        )
        CustomerRemoval.objects.create(
            customer=customer,
            application=application,
            user=customer.user,
            reason=reason,
            added_by=executor_user,
            nik=nik,
            email=email,
            phone=phone,
        )
        deactivate_user(executor_user, customer, nik, phone)
    send_user_attributes_to_moengage_for_realtime_basis.delay(customer.id, 'is_deleted')
    logger.info(
        {
            'method': 'do_new_delete_customer_based_on_api_logic',
            "status": "done",
            'data': {
                'is_deleted': True,
                'customer_id': customer.pk,
                'application_id': application.pk,
            },
        }
    )


def new_delete_customer_based_on_api_logic(data, only_old_customer=True, actor_id=None):

    executor_user = User.objects.get(pk=actor_id)

    for customer_data in data:
        cust_id = customer_data["cust_id"]
        reason = 'user requested delete'
        # -- fix --
        last_app = Application.objects.filter(customer_id=cust_id).last()
        track_agent_retrofix('new_delete_customer_based_on_api_logic', last_app.id, data, actor_id)
        do_new_delete_customer_based_on_api_logic(cust_id, reason, executor_user, only_old_customer)
        # ---------
    return "Success"
