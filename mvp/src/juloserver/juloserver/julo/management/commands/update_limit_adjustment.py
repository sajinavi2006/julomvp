import logging
from django.core.management.base import BaseCommand

from juloserver.apiv2.models import PdCreditModelResult
from juloserver.julo.models import AffordabilityHistory, Application
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.statuses import PaymentStatusCodes, ApplicationStatusCodes
from juloserver.julo.tasks2.application_tasks import update_limit_for_good_customers

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update limit adjustment factor to 100% for Pgood >= 0.93'

    def add_arguments(self, parser):
        parser.add_argument('--pgood_upper', nargs='?', type=float,
                            help="upper PGOOD value to cutoff. Default Value is 1")
        parser.add_argument('--pgood_lower', nargs='?', type=float,
                            help="lower PGOOD value to cutoff. Default Value is 0")
        parser.add_argument('--old_limit_adjustment_factor', nargs='?', type=float,
                            help="limit_adjustment_factor with the current implementation."
                                 "Default Value is None(will work on updating all pgood in that range.)")
        parser.add_argument('--new_limit_adjustment_factor', nargs='?', type=float,
                            help="limit_adjustment_factor with the new implementation. "
                                 "Necessary argument.")
        parser.add_argument('--usage_limit', nargs='?', type=str,
                            help="Usage Limit. Default will run for all cases")

    def handle(self, *args, **options):
        for key, value in options.items():
            if key == 'pgood_upper':
                pgood_upper = value if value else 1
            elif key == 'pgood_lower':
                pgood_lower = value if value else 0
            elif key == 'old_limit_adjustment_factor':
                old_limit_adjustment_factor = value
            elif key == 'new_limit_adjustment_factor':
                new_limit_adjustment_factor = value
            elif key == 'usage_limit':
                usage_limit = True if value else False
                if usage_limit:
                    try:
                        lower_usage_limit, higher_usage_limit = map(int, value.split(':'))
                    except ValueError:
                        self.stdout.write(self.style.ERROR(
                            'Please provide usage_limit in the format "lowerlimit":"upperlimit"')
                        )
                        return

        if not new_limit_adjustment_factor:
            self.stdout.write(self.style.SUCCESS(
                'Please provide new limit Adjustment Factor. Use '
                '"python manage.py update_limit_adjustment -h" '
                'for help')
            )
            return
        if usage_limit:
            if higher_usage_limit < lower_usage_limit:
                self.stdout.write(self.style.ERROR(
                    'Please provide usage_limit in the format "lowerlimit":"upperlimit" '
                    'and lowerlimit < upperlimit')
                )
                return

        if pgood_upper == 1:
            application_list = PdCreditModelResult.objects.filter(
                pgood__gte=pgood_lower, pgood__lte=pgood_upper).values_list(
                'application_id', flat=True)
        else:
            application_list = PdCreditModelResult.objects.filter(
                pgood__gte=pgood_lower, pgood__lt=pgood_upper).values_list(
                'application_id', flat=True)
        graduated_applications = AffordabilityHistory.objects.filter(
            application_id__in=application_list, reason='manual graduation'
        ).values_list('application_id', flat=True)

        not_graduated_applications = list(set(application_list) - set(graduated_applications))

        final_application_list = []

        for application_id in not_graduated_applications:
            application = Application.objects.filter(
                id=application_id,
                workflow__name=WorkflowConst.JULO_ONE,
                application_status_id=ApplicationStatusCodes.LOC_APPROVED
            ).last()

            if not application or not application.account:
                continue
            account_payment_set = application.account.accountpayment_set.all()
            count_paid_off_late = account_payment_set.filter(
                status__gte=PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
            ).count()
            count_current_late = account_payment_set.filter(
                status__gte=PaymentStatusCodes.PAYMENT_1DPD,
                status__lt=PaymentStatusCodes.PAID_ON_TIME
            ).count()

            if count_current_late or count_paid_off_late:
                continue

            final_application_list.append(application_id)
        if usage_limit:
            limited_application_list = final_application_list[lower_usage_limit:higher_usage_limit]
        else:
            limited_application_list = final_application_list

        for application_id in limited_application_list:
            update_limit_for_good_customers.delay(
                application_id,
                old_limit_adjustment_factor,
                new_limit_adjustment_factor
            )
            logger.info({
                "action": "update_limit_adjustment_triggered",
                "application": application_id
            })
        self.stdout.write(self.style.SUCCESS(
            'Successfully Triggered Update in Limit adjustment')
        )
