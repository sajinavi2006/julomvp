import urllib.request
import csv

from django.core.management.base import BaseCommand
from juloserver.graduation.services import retroload_graduation_customer_history
from juloserver.sales_ops.utils import chunker



class Command(BaseCommand):
    help = """
        Populate data from CSV to new table GraduationCustomerHistory2
    """

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to CSV file")

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(
            'Starting populate data from CSV to new table GraduationCustomerHistory2 --BEGIN--'))
        csv_path = options['csv_path']
        with urllib.request.urlopen(csv_path) as response:
            data = response.read().decode('utf-8')

        reader = csv.DictReader(data.splitlines())
        for graduation_batch in chunker(reader):
            retroload_graduation_customer_history(graduation_batch)
        self.stdout.write(self.style.SUCCESS(
            'Successfully populate data in CSV to new table --END--'))
