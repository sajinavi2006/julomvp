from datetime import date

from django.core.management.base import BaseCommand

from juloserver.cashback.models import CashbackEarned


class Command(BaseCommand):
    help = """
        changed all cashback expiry date to 2022-12-31
        Shall be used after release of card CLS3-135
    """

    def handle(self, *args, **kwargs):
        self.stdout.write("Start retroloading...", ending='\n\n')
        new_expiry_date = date(year=2022, month=12, day=31)
        rows_affected = CashbackEarned.objects.update(
            expired_on_date=new_expiry_date,
        )
        self.stdout.write(
            "Done updating {x} rows of <ops.cashbackearned.expired_on_date> to '2022-12-31'".format(
                x=rows_affected), ending='\n'
        )
