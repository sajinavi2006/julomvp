from builtins import str
import logging
import sys
from django.db import connection
from django.core.management.base import BaseCommand
from juloserver.julo.models import Loan

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'retro is ever entered Bucket 5 that have active loan'

    def handle(self, *args, **options):
        loan_data_ids = []
        query = """select loan_id from (
                  SELECT DISTINCT ON ("payment"."loan_id") "payment"."cdate",
                    "payment"."payment_id",
                    "payment"."loan_id",
                    "payment"."payment_status_code",
                    "payment"."due_date",
                    "payment"."payment_number" as oldest_payment_number,
                    current_date - "payment"."due_date" as current_dpd,
                    case
                       when current_date - "payment"."due_date" between 1 and 10
                           then 'Bucket 1'
                       when current_date - "payment"."due_date" between 11
                       and 40
                           then 'Bucket 2'
                       when current_date - "payment"."due_date" between 41
                        and 70
                           then 'Bucket 3'
                       when current_date - "payment"."due_date" between 71
                        and 90
                           then 'Bucket 4'
                       when current_date - "payment"."due_date" > 90
                           then 'Bucket 5'
                       end as current_bucket,
                       case
                           when (
                                    select count(1)
                                    from ops.payment as payment2
                                    where payment2.loan_id = payment.loan_id
                                      and payment2.payment_number <
                                       payment.payment_number
                                      and (payment2.paid_date -
                                       payment2.due_date) >= 91
                                ) > 0 then True
                           else False
                        end as ever_entered_b5
                  FROM ops."payment"
                   INNER JOIN ops."loan" ON ("payment"."loan_id" = "loan"."loan_id")
                   INNER JOIN ops."application"
                    ON ("loan"."application_id" = "application"."application_id")
                  WHERE (NOT ("loan"."loan_status_code" = 240)
                   AND NOT ("payment"."is_restructured" = True) AND
                         "payment"."payment_status_code" < 330)
                  ORDER BY "payment"."loan_id" ASC, "payment"."payment_id" ASC
            ) as foo where foo.ever_entered_b5 = True and foo.current_bucket in
             ('Bucket 1','Bucket 2', 'Bucket 3', 'Bucket 4')
              and foo.payment_id not in (4001563019, 4001565060, 4001540573)
        """
        self.stdout.write(self.style.WARNING(
            'Start query data for ever_enter B5')
        )
        with connection.cursor() as cursor:
            try:
                self.stdout.write(self.style.WARNING(
                    'Queried ....')
                )
                cursor.execute(query)
                loan_data_ids = cursor.fetchall()
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    'No Data For retroload ever_enter B5 {}'.format(str(e)))
                )

        loan_data_ids = [i[0] for i in loan_data_ids]
        self.stdout.write(self.style.WARNING(
            'List Loan ID :')
        )
        self.stdout.write(self.style.WARNING(
            str(loan_data_ids))
        )
        self.stdout.write(self.style.WARNING(
            'Start Update Loan ever_entered_B5')
        )
        Loan.objects.filter(id__in=loan_data_ids).update(ever_entered_B5=True)
        self.stdout.write(self.style.SUCCESS(
            'Successfully retro load data for ever_enter B5')
        )
