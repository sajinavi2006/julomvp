from juloserver.julo.models import ProductLine
from juloserver.julocore.data.models import CustomQuerySet


def get_product_lines_qs() -> CustomQuerySet:
    return ProductLine.objects.all().order_by('product_line_code')
