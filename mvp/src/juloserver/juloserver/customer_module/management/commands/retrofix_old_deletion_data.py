import logging
from django.core.management.base import BaseCommand
from django.db.models import F
from django.contrib.auth.models import User
from bulk_update.helper import bulk_update
from juloserver.customer_module.constants import (
    soft_delete_account_status_account_deletion,
    soft_delete_application_status_account_deletion,
)
from juloserver.julo.models import (
    ApplicationFieldChange,
    ApplicationHistory,
    AuthUserFieldChange,
    CustomerFieldChange,
    CustomerRemoval,
)
from juloserver.customer_module.utils.utils_crm_v1 import (
    get_deletion_email_format,
    get_deletion_nik_format,
    get_deletion_phone_format,
)
from juloserver.customer_module.services.account_deletion import (
    get_allowed_product_line_for_deletion,
    is_complete_deletion,
)
from juloserver.julo.statuses import ApplicationStatusCodes

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Correcting customer data that are deleted using the old mechanism '
    '(old mechanism not updating their NIK, email, and phone data).'
    'To run via shell, use this command'
    'from juloserver.customer_module.management.commands.retrofix_old_deletion_data import Command'
    'cmd = Command()'
    'cmd.execute("your_email@julofinance.com")'

    def handle(self, *args, **options):
        return

    def execute(self, agent_email):
        agent = User.objects.filter(email=agent_email).last()
        if not agent:
            print('agent empty, canceling process..')
            return

        deleted_old_customer = CustomerRemoval.objects.filter(
            nik=F('customer__nik'),
            email=F('customer__email'),
            phone=F('customer__phone'),
        ).exclude(
            application__application_status_id__in=soft_delete_application_status_account_deletion,
            customer__account__status__in=soft_delete_account_status_account_deletion,
        )

        allowed_product_line_deletion = get_allowed_product_line_for_deletion()
        for customer_removal in deleted_old_customer.iterator():
            customer = customer_removal.customer
            applications = customer.application_set.all()
            application = applications.last()
            if application.product_line_id not in allowed_product_line_deletion:
                continue

            nik = customer.get_nik
            phone = customer.get_phone

            try:
                is_full_deletion = is_complete_deletion(customer)
                if is_full_deletion:
                    self.update_user(agent, customer, nik, phone)
                    self.update_customer(agent, customer, application)
                else:
                    print('ignore updating user & customer for customer id {}'.format(customer.id))
                self.update_application(agent, applications)
            except Exception as e:
                err_msg = {
                    'action': 'retrofix_old_deletion_data',
                    'message': 'failed retrofix',
                    'customer_id': customer.id,
                    'error': str(e),
                }

                print(str(err_msg))
                logger.error(err_msg)

        print('=========Finish=========')

    def update_user(self, agent, customer, nik, phone):
        field_changes = []
        user = customer.user

        if nik and user.username == nik:
            edited_username = get_deletion_nik_format(customer.id)
            field_changes.append(
                AuthUserFieldChange(
                    user=user,
                    customer=customer,
                    field_name='username',
                    old_value=user.username,
                    new_value=edited_username,
                    changed_by=agent,
                )
            )
            user.username = edited_username

        if phone and user.username == phone:
            edited_username = get_deletion_phone_format(customer.id)
            field_changes.append(
                AuthUserFieldChange(
                    user=user,
                    customer=customer,
                    field_name='username',
                    old_value=user.username,
                    new_value=edited_username,
                    changed_by=agent,
                )
            )
            user.username = edited_username

        if user.email:
            edited_email = get_deletion_email_format(user.email, customer.id)
            field_changes.append(
                AuthUserFieldChange(
                    user=user,
                    customer=customer,
                    field_name='email',
                    old_value=user.email,
                    new_value=edited_email,
                    changed_by=agent,
                )
            )
            user.email = edited_email

        if user.is_active:
            field_changes.append(
                AuthUserFieldChange(
                    user=user,
                    customer=customer,
                    field_name='is_active',
                    old_value=user.is_active,
                    new_value=False,
                    changed_by=agent,
                )
            )
            user.is_active = False
        AuthUserFieldChange.objects.bulk_create(field_changes)
        user.save()

    def update_customer(self, agent, customer, application):
        field_changes = []
        field_changes.append(
            CustomerFieldChange(
                customer=customer,
                application=application,
                field_name='can_reapply',
                old_value=customer.can_reapply,
                new_value=False,
                changed_by=agent,
            )
        )
        field_changes.append(
            CustomerFieldChange(
                customer=customer,
                application=application,
                field_name='is_active',
                old_value=customer.is_active,
                new_value=False,
                changed_by=agent,
            )
        )
        customer.can_reapply = False
        customer.is_active = False

        if customer.nik:
            edited_nik = get_deletion_nik_format(customer.id)
            field_changes.append(
                CustomerFieldChange(
                    customer=customer,
                    application=application,
                    field_name='nik',
                    old_value=customer.nik,
                    new_value=edited_nik,
                    changed_by=agent,
                )
            )
            customer.nik = edited_nik

        if customer.email:
            edited_email = get_deletion_email_format(customer.email, customer.id)
            field_changes.append(
                CustomerFieldChange(
                    customer=customer,
                    application=application,
                    field_name='email',
                    old_value=customer.email,
                    new_value=edited_email,
                    changed_by=agent,
                )
            )
            customer.email = edited_email

        if customer.phone:
            edited_phone = get_deletion_phone_format(customer.id)
            field_changes.append(
                CustomerFieldChange(
                    customer=customer,
                    application=application,
                    field_name='phone',
                    old_value=customer.phone,
                    new_value=edited_phone,
                    changed_by=agent,
                )
            )
            customer.phone = edited_phone
        CustomerFieldChange.objects.bulk_create(field_changes)
        customer.save()

    def update_application(self, agent, applications):
        deleted_application_id = []
        field_changes = []
        history_changes = []

        allowed_product_line_deletion = get_allowed_product_line_for_deletion()
        for application in applications:
            if application.product_line_id not in allowed_product_line_deletion:
                continue

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

            if application.application_status_id != ApplicationStatusCodes.CUSTOMER_DELETED:
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

            deleted_application_id.append(application.id)

        if len(history_changes) > 0:
            ApplicationHistory.objects.bulk_create(history_changes)
        ApplicationFieldChange.objects.bulk_create(field_changes)
        bulk_update(
            applications,
            update_fields=['ktp', 'is_deleted', 'email', 'mobile_phone_1', 'application_status_id'],
        )

        return deleted_application_id
