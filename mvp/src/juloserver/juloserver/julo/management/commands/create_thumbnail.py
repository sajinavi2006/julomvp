import logging
import sys

from django.core.management.base import BaseCommand

from ...models import Image
from ...tasks import create_thumbnail_and_upload


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


def process_thumbnails():
    images = Image.objects.filter(thumbnail_url='').order_by('-cdate')
    for image in images:
        create_thumbnail_and_upload.delay(image)


class Command(BaseCommand):
    help = 'cretae_thumbnail_image'

    def handle(self, *args, **options):
        process_thumbnails()
        self.stdout.write(self.style.SUCCESS(
            "Successfully created thumbnails and uploaded to cloud storage."))
