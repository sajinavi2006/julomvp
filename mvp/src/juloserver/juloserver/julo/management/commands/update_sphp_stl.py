import logging
import sys

from django.core.management.base import BaseCommand

from ...models import SphpTemplate
from ...statuses import Statuses
from ...workflows2.schemas.default_status_handler import *
from . import update_status_label


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Update stl sphp'

    def handle(self, *args, **options):
        with open('juloserver/julo/templates/stl_sphp.html', "r") as file:
            sphp_stl = file.read()
            file.close()

        SphpTemplate.objects.filter(
            product_name__in=('STL1', 'STL2')
        ).update(
            sphp_template=sphp_stl)
