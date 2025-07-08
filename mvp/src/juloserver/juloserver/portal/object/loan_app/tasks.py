from __future__ import absolute_import

import logging
# from django.conf import settings

from celery import task

from .utils import remove_file


logger = logging.getLogger(__name__)

# MEDIA_ROOT = getattr(settings, 'MEDIA_ROOT', '../../media')


@task(name='drop_after_successful_upload')
def drop_after_successful_upload(image_object, thumbnail_url):

    result = remove_file(image_object.image.path)

    logger.info({
        'result': result,
        'image_object': image_object.image.path,
    })
