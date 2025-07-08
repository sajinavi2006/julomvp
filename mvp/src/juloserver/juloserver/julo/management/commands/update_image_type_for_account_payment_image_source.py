from django.core.management.base import BaseCommand
from juloserver.portal.object.loan_app.constants import ImageUploadType

from juloserver.julo.models import Image


class Command(BaseCommand):
    help = 'Helps to update the image type for the image source which has account payment id'

    def handle(self, *args, **options):
        image_lists = Image.objects.filter(
            url__contains='account_payment',
            image_type = ImageUploadType.PAYSTUB
        )
        for image in image_lists:
            image.update_safely(image_type=ImageUploadType.LATEST_PAYMENT_PROOF)
