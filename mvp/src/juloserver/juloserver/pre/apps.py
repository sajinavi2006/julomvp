from django.apps import AppConfig
from django.db.models.signals import pre_save

import sys
import logging

logger = logging.getLogger(__name__)


class PreConfig(AppConfig):
    name = "juloserver.pre"
    domain = 'juloserver'

    def ready(self):
        if not any('test' in arg.lower() for arg in sys.argv):
            self.apply_signals()

    def apply_signals(self):
        from django.apps import apps
        from juloserver.julo.constants import FeatureNameConst
        from juloserver.julo.models import FeatureSetting
        from juloserver.pre.signals import my_log

        try:
            feature_setting = (
                FeatureSetting.objects.nocache()
                .filter(feature_name=FeatureNameConst.FIELD_TRACKER_LOG, is_active=True)
                .last()
            )
            if feature_setting:
                tables = feature_setting.parameters.get("tables", [])
                for model in apps.get_models():
                    if model._meta.db_table in tables:
                        pre_save.connect(my_log, sender=model)
        except Exception:
            logger.error(
                {
                    "action": "PreConfig.apply_signals",
                    "message": "failed to setup field tracker log",
                }
            )
