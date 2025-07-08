from builtins import str
import logging
import sys
from django.utils import timezone
from django.core.management.base import BaseCommand
from ...models import Application, Skiptrace
from ...utils import format_e164_indo_phone_number


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


mobile_phone = [
    ('phone_1', '6281211998029','simpati'),
    ('spouse', '6287712890989', 'xl'),
    ('kin', '6281822828282', 'xl'),
    ('office', '6285234567891', 'as'),
]



def load_dummy_data():

    applications = Application.objects.all()

    for application in applications:
        x = 1
        for src, number, operator in mobile_phone:
            Skiptrace.objects.create(
                customer=application.customer,
                application=application,
                contact_name='Test'+ str(x),
                contact_source=src,
                phone_number=format_e164_indo_phone_number(number),
                phone_operator=operator,
                recency=timezone.localtime(timezone.now())
            )
            x+=1


class Command(BaseCommand):
    help = 'load dummy data for skiptrace'

    def handle(self, *args, **options):
        load_dummy_data()
        self.stdout.write(self.style.SUCCESS('Successfully load dummy data for skiptrace'))
