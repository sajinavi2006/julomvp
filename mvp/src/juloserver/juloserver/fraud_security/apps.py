from django.apps import AppConfig


class FraudSecurityConfig(AppConfig):
    name = 'juloserver.fraud_security'
    domain = 'juloserver'

    def ready(self):
        self._init_admin()

    def _init_admin(self):
        from juloserver.fraud_security.admins.swift_limit_drainer_admin import (
            SwiftLimitDrainerFeatureSettingAdminForm,
        )
        from juloserver.julo.constants import FeatureNameConst
        from juloserver.julo.admin import FeatureSettingAdmin

        FeatureSettingAdmin.register_form(
            FeatureNameConst.SWIFT_LIMIT_DRAINER,
            SwiftLimitDrainerFeatureSettingAdminForm,
        )
