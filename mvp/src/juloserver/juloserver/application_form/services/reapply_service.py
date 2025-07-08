from juloserver.julo.models import MobileFeatureSetting


def get_application_reapply_setting():
    return MobileFeatureSetting.objects.get_or_none(
        feature_name='application_reapply_setting', is_active=True
    )
