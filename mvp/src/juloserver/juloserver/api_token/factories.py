from django.utils import timezone
from factory import LazyAttribute
from factory.django import DjangoModelFactory
from juloserver.api_token.models import ProductPickerLoggedOutNeverResolved
from juloserver.julo.tests.factories import CustomerFactory
from juloserver.user_action_logs.models import MobileUserActionLog


class ProductPickerLoggedOutNeverResolvedFactory(DjangoModelFactory):
    class Meta(object):
        model = ProductPickerLoggedOutNeverResolved

    cdate = timezone.localtime(timezone.now())
    udate = timezone.localtime(timezone.now())
    android_id = 'AbcdEFajhdka'
    device_brand = 'Test Brand'
    device_model = 'Test Model'
    original_customer_id = LazyAttribute(lambda o: CustomerFactory().id)
    last_mobile_user_action_log_id = LazyAttribute(lambda o: MobileUserActionLog().id)
    last_app_version = '8.26.0'
    last_customer_id = None
    last_application_id = None
