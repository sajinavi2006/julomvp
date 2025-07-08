from builtins import str
import logging
import sys

from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from ...models import Customer
from ...statuses import ApplicationStatusCodes

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


def get_reapply_date(reason, dob, app_cdate):
    asap = ['failed dv other',
            'failed pv employer',
            'partner_triggered',
            'unprospect',
            ]

    month_half = ['new phone']

    month_3 = ['basic_savings',
               'monthly_income_gt_3_million',
               'monthly_income',
               'job_not_black_listed',
               'cannot afford loan',
               'debt_to_income_40_percent',
               'failed DV min income not met',
               'job_term_gt_3_month',
               'job type blacklisted',
               'sms_rejection_30_days',
               'sms_grace_period_3_months',
               'sms_grace_period_24_months',
               ]

    month_12 = ['sms_delinquency_24_months',
                'email_delinquency_24_months',
                'negative data in sd',
                'negative payment history with julo',
                ]

    after_21 = ['age not met',
                'application_date_of_birth',
                ]
    reapply_date = None
    if any(word in reason for word in asap):
        reapply_date = app_cdate
    if any(word in reason for word in month_half):
        reapply_date = app_cdate + relativedelta(days=+15)
    if any(word in reason for word in month_3):
        reapply_date = app_cdate + relativedelta(months=+3)
    if any(word in reason for word in month_12):
        reapply_date = app_cdate + relativedelta(years=+1)
    if any(word in reason for word in after_21):
        age = app_cdate.year - dob.year - ((app_cdate.month, app_cdate.day) < (dob.month, dob.day))
        if age < 21:
            reapply_date = datetime.combine(dob + relativedelta(years=+21), datetime.min.time()).replace(
                tzinfo=timezone.localtime(timezone.now()).tzinfo)
    return reapply_date


class Command(BaseCommand):
    help = 'Bulk Update all 135 application customer to can_reapply application'

    def handle(self, *args, **options):

        prior_date_str = '2017-03-01'
        last_year = datetime.strptime(prior_date_str, "%Y-%m-%d").date()

        self.stdout.write(self.style.SUCCESS("======================================"))
        self.stdout.write(self.style.SUCCESS("bulk update begin"))
        self.stdout.write(self.style.SUCCESS("======================================"))
        with transaction.atomic():
            customers = Customer.objects.filter(
                can_reapply=False,
                can_reapply_date__isnull=True,
                application__application_status=ApplicationStatusCodes.APPLICATION_DENIED,
                application__applicationhistory__status_new=ApplicationStatusCodes.APPLICATION_DENIED, )
            # application__applicationhistory__cdate__date__lte=last_year)

            for customer in customers:
                last_app = customer.application_set.last()
                if last_app.application_status.status_code == ApplicationStatusCodes.APPLICATION_DENIED:
                    last_app_history = last_app.applicationhistory_set.last()
                    if last_app_history.status_new == ApplicationStatusCodes.APPLICATION_DENIED:
                        reason = last_app_history.change_reason
                        dob = last_app.dob
                        last_app_history_cdate = timezone.localtime(last_app_history.cdate)
                        reapply_date = get_reapply_date(reason.lower(), dob, last_app_history_cdate)
                        if reapply_date:
                            # customer.can_reapply_date = reapply_date
                            # customer.save()
                            self.stdout.write(self.style.SUCCESS(
                                "customer = '%s' reason = '%s' cdate = '%s', dob = '%s',  reapply set on '%s'" % (
                                    str(customer), reason, str(last_app_history_cdate), str(dob), str(reapply_date))))
                            self.stdout.write(self.style.SUCCESS("======================================"))
        self.stdout.write(self.style.SUCCESS("all Process done"))
