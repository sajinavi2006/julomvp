from django.core.management import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Refresh the sales_ops_r_score and sales_ops_m_score materialized view table."

    def handle(self, *args, **options):

        with connection.cursor() as cursor:
            self.stdout.write('Executing "REFRESH MATERIALIZED VIEW sales_ops_r_score"...')
            cursor.execute('REFRESH MATERIALIZED VIEW sales_ops_r_score')

            self.stdout.write('Executing "REFRESH MATERIALIZED VIEW sales_ops_m_score"...')
            cursor.execute('REFRESH MATERIALIZED VIEW sales_ops_m_score')

            self.stdout.write('Executing "REFRESH MATERIALIZED VIEW sales_ops_graduation"...')
            cursor.execute('REFRESH MATERIALIZED VIEW sales_ops_graduation')

        self.stdout.write(self.style.SUCCESS('Refresh ranking is success.'))
