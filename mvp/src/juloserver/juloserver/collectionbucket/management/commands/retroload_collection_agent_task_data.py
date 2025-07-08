from builtins import str
import logging
import sys

from django.core.management.base import BaseCommand

from juloserver.collectionbucket.models import CollectionAgentTask
from juloserver.julo.constants import AgentAssignmentTypeConst

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'retroload collection agent task value on field type'

    def handle(self, *args, **options):
        try:
            updated_to_dpd71_dpd90 = CollectionAgentTask.objects.filter(
                type='dpd71_dpd100',
                agent__isnull=False,
            ).update(
                type=AgentAssignmentTypeConst.DPD71_DPD90
            )
            self.stdout.write(self.style.SUCCESS(
                'Success change {} data type dpd71_dpd100 to dpd71_dpd90'.format(
                    updated_to_dpd71_dpd90
                )
            ))
            updated_to_dpd91plus = CollectionAgentTask.objects.filter(
                type='dpd101plus',
                agent__isnull=False,
            ).update(
                type=AgentAssignmentTypeConst.DPD91PLUS
            )
            self.stdout.write(self.style.SUCCESS(
                'Success change {} data type dpd101plus to dpd91plus'.format(updated_to_dpd91plus)
            ))
        except Exception as e:
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error(error_msg)
            self.stdout.write(self.style.ERROR(error_msg))
