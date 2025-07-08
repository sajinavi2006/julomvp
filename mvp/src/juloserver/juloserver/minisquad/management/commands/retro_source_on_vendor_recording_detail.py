import sys
import logging
from datetime import date
from django.db import transaction
from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from juloserver.minisquad.models import VendorRecordingDetail
from juloserver.julo.models import SkiptraceHistory

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    def handle(self, **options):
        try:
            with transaction.atomic():
                ten_days_before = date.today() - relativedelta(days=10)
                intelix_recording_data = VendorRecordingDetail.objects.filter(
                    skiptrace__isnull=True,
                    cdate__date__gte=ten_days_before,
                    source='Intelix',
                )
                if intelix_recording_data:
                    for record_data in intelix_recording_data.iterator():
                        skiptrace_history = SkiptraceHistory.objects.filter(
                            unique_call_id=record_data.unique_call_id
                        ).last()
                        record_data.update_safely(
                            skiptrace=skiptrace_history.skiptrace if skiptrace_history else None)

                airudder_intelix_data = VendorRecordingDetail.objects.filter(
                    skiptrace__isnull=True,
                    cdate__date__gte=ten_days_before,
                    source='AiRudder',
                )
                if airudder_intelix_data:
                    for record_data in airudder_intelix_data.iterator():
                        skiptrace_history = SkiptraceHistory.objects.filter(
                            external_unique_identifier=record_data.unique_call_id
                        ).last()
                        record_data.update_safely(
                            skiptrace=skiptrace_history.skiptrace if skiptrace_history else None)

            logger.error({
                'action': 'retro_source_on_vendor_recording_detail',
                'message': 'all data already update',
            })
        except Exception as err:
            error_msg = 'Something went wrong -{}'.format(str(err))
            logger.error({
                'action': 'retro_source_on_vendor_recording_detail',
                'reason': error_msg
            })
            raise err
