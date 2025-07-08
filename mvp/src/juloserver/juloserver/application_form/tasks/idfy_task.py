import requests
import os

from celery import task

from juloserver.fdc.files import (
    TempDir,
)
from juloserver.julo.models import Application, ApplicationStatusCodes
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.models import Image
from juloserver.julo.tasks import upload_image
from juloserver.face_recognition.constants import ImageType
from juloserver.julo.services import process_image_upload_direct
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting

logger = JuloLog(__name__)


@task(queue="application_high")
def copy_resource_selfie_to_application(url_selfie, application_id):
    from juloserver.application_form.services.idfy_service import upload_file_image_with_filename
    from juloserver.partnership.services.services import download_image_from_url

    if not url_selfie:
        logger.error(
            {
                'message': 'skip process get image selfie',
                'source_url': url_selfie,
                'application': application_id,
            }
        )
        return

    # get the file
    application = Application.objects.filter(pk=application_id).last()
    if not application:
        return

    if application.application_status_id != ApplicationStatusCodes.FORM_CREATED:
        logger.error(
            {
                'message': 'application not allowed',
                'process': 'copying image from IDFy',
                'application': application.id,
                'application_status_code': application.application_status_id,
            }
        )
        return

    with TempDir() as tempdir:

        # selfie
        selfie_photo = requests.get(url_selfie).content
        full_filename = 'selfie.png'
        selfie_filepath = os.path.join(tempdir.path, full_filename)

        file_selfie = open(selfie_filepath, 'wb')
        file_selfie.write(selfie_photo)
        file_selfie.close()

        logger.info(
            {
                'message': 'try to upload file selfie',
                'filename': full_filename,
                'application': application.id,
            }
        )

        with open(selfie_filepath, 'rb') as file:
            image_selfie = download_image_from_url(url_selfie)
            upload_file_image_with_filename(
                image_selfie,
                file.name,
                application.id,
                ImageType.SELFIE,
            )
            upload_file_image_with_filename(
                image_selfie,
                file.name,
                application.id,
                ImageType.CROP_SELFIE,
            )

    return True


@task(queue="application_high")
def copy_resource_ktp_to_application(url_ktp, application_id):
    from juloserver.partnership.services.services import download_image_from_url

    if not url_ktp:
        logger.error(
            {
                'message': 'skip process get image ktp',
                'source_url': url_ktp,
                'application': application_id,
            }
        )
        return

    # get the file
    application = Application.objects.filter(pk=application_id).last()
    if not application:
        return

    if application.application_status_id != ApplicationStatusCodes.FORM_CREATED:
        logger.error(
            {
                'message': 'application not allowed',
                'process': 'copying image from IDFy',
                'application': application.id,
                'application_status_code': application.application_status_id,
            }
        )
        return

    with TempDir() as tempdir:

        ktp_photo = requests.get(url_ktp).content
        full_filename = 'ktp_selfie.png'
        ktp_filepath = os.path.join(tempdir.path, full_filename)
        file_ktp = open(ktp_filepath, 'wb')
        file_ktp.write(ktp_photo)

        logger.info(
            {
                'message': 'try to upload file KTP',
                'filename': full_filename,
                'application': application.id,
            }
        )

        use_oss = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.IDFY_NFS_DEPENDENCY, is_active=True
        ).exists()
        with open(ktp_filepath, 'rb') as file:

            # create the image
            image = Image()
            image.image_type = 'ktp_self'
            image.image_source = application_id
            image.save()

            image_ktp = download_image_from_url(url_ktp)
            if use_oss:
                process_image_upload_direct(
                    image,
                    image_ktp,
                    thumbnail=True,
                    delete_if_last_image=False,
                    image_file_name=full_filename,
                )
            else:
                image.image.save(file.name, image_ktp)
                upload_image(image.id, True)

    return True


@task(queue="application_high")
def copy_resource_additional_document_to_application(url_docs, application_id):
    from juloserver.partnership.services.services import download_image_from_url

    if not url_docs:
        logger.error(
            {
                'message': 'skip process get image document',
                'source_url': url_docs,
                'application': application_id,
            }
        )
        return

    # get the file
    application = Application.objects.filter(pk=application_id).last()
    if not application:
        return

    if application.application_status_id != ApplicationStatusCodes.FORM_CREATED:
        logger.error(
            {
                'message': 'application not allowed',
                'process': 'copying document from IDFy',
                'application': application.id,
                'application_status_code': application.application_status_id,
            }
        )
        return

    with TempDir() as tempdir:

        docs_files_request = requests.get(url_docs).content
        full_filename = 'additional_document.png'
        docs_filepath = os.path.join(tempdir.path, full_filename)
        file_docs = open(docs_filepath, 'wb')
        file_docs.write(docs_files_request)

        logger.info(
            {
                'message': 'try to upload file Additional Document',
                'filename': full_filename,
                'application': application.id,
            }
        )

        use_oss = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.IDFY_NFS_DEPENDENCY, is_active=True
        ).exists()
        with open(docs_filepath, 'rb') as file:

            # create the image
            image = Image()
            image.image_type = 'additional_document'
            image.image_source = application_id
            image.save()

            docs_file = download_image_from_url(url_docs)
            if use_oss:
                process_image_upload_direct(
                    image,
                    docs_file,
                    thumbnail=True,
                    delete_if_last_image=False,
                    image_file_name=full_filename,
                )
            else:
                image.image.save(file.name, docs_file)
                upload_image(image.id, True)

    return True
