from juloserver.julo.models import (
    StatusLookup,
)
from juloserver.julocore.data.models import CustomQuerySet


def get_status_codes_qs() -> CustomQuerySet:
    return StatusLookup.objects.all().order_by('status_code')
