import logging
import sys

from django.core.management.base import BaseCommand

from juloserver.entry_limit.models import EntryLevelLimitConfiguration
from juloserver.payment_point.constants import TransactionMethodCode

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = "update tarik dana for all user"

    def handle(self, *args, **options):
        entry_level_limit_configs = EntryLevelLimitConfiguration.objects.all()
        for entry_level_limit_config in entry_level_limit_configs:
            enabled_trx_method = entry_level_limit_config.enabled_trx_method
            if TransactionMethodCode.SELF.code in enabled_trx_method:
                continue
            enabled_trx_method.append(TransactionMethodCode.SELF.code)
            entry_level_limit_config.update_safely(enabled_trx_method=enabled_trx_method)
        print("process finished!!!!")
