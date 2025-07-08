from datetime import timedelta
from django.utils import timezone
from factory.django import DjangoModelFactory
from juloserver.limit_validity_timer.models import LimitValidityTimer


class LimitValidityTimerCampaignFactory(DjangoModelFactory):
    class Meta(object):
        model = LimitValidityTimer

    end_date = timezone.now() + timedelta(days=10)
