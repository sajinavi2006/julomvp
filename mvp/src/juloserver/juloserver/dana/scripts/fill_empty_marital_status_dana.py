from juloserver.dana.models import DanaCustomerData
from juloserver.partnership.models import PartnershipImage
from juloserver.partnership.constants import PartnershipImageType
from django_bulk_update.helper import bulk_update
from google.cloud import vision
from google.oauth2 import service_account
from google.cloud.vision_v1 import types
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def get_ocr_marital_status(uri, client) -> str:
    image = types.Image()
    image.source.image_uri = uri

    print('Scanning image... ')
    response = client.text_detection(image=image)
    texts = response.text_annotations
    marital_status = ''

    for text in texts:
        scanned_text = text.description
        scanned_text = scanned_text.lower()
        scanned_text = scanned_text.replace(" ", "")

        if "belumkawin" in scanned_text:
            marital_status = "Lajang"
        else:
            marital_status = 'Menikah'

        break

    if response.error.message:
        logger.error(
            {
                'action_view': 'get_ocr_marital_status',
                'data': {'error': str(response.error.message)},
                'message': "fail google vision text detection",
            }
        )
        marital_status = "error"

    return marital_status


def insert_marital_status_dana(batch_limit: int = 500) -> None:
    dana_customers = DanaCustomerData.objects.select_related('application').filter(
        application__marital_status__isnull=True
    )

    service_account_info = {
        "type": "service_account",
        "project_id": settings.PARTNERSHIP_GOOGLE_VISION_PROJECT_ID,
        "private_key_id": settings.PARTNERSHIP_GOOGLE_VISION_PRIVATE_KEY_ID,
        "private_key": settings.PARTNERSHIP_GOOGLE_VISION_PRIVATE_ID,
        "client_email": settings.PARTNERSHIP_GOOGLE_VISION_CLIENT_EMAIL,
        "client_id": settings.PARTNERSHIP_GOOGLE_VISION_CLIENT_ID,
        "auth_uri": settings.PARTNERSHIP_GOOGLE_VISION_AUTH_URI,
        "token_uri": settings.PARTNERSHIP_GOOGLE_VISION_TOKEN_URI,
        "auth_provider_x509_cert_url": settings.PARTNERSHIP_GOOGLE_VISION_AUTH_PROVIDER,
        "client_x509_cert_url": settings.PARTNERSHIP_GOOGLE_VISION_CLIENT_X509_CERT_URL,
        "universe_domain": settings.PARTNERSHIP_GOOGLE_VISION_UNIVERSE_DOMAIN,
    }

    vision_credentials = service_account.Credentials.from_service_account_info(service_account_info)
    client = vision.ImageAnnotatorClient(credentials=vision_credentials)
    data_list = []

    for dana_customer in dana_customers.iterator():
        application = dana_customer.application

        if (
            application.gender
            and application.address_kabupaten
            and application.address_provinsi
            and application.address_kodepos
            and application.job_type
            and application.job_industry
            and application.monthly_income
        ):
            img = PartnershipImage.objects.filter(
                application_image_source=dana_customer.application.id,
                image_type=PartnershipImageType.KTP_SELF,
            ).last()
            if not img:
                print(
                    'application_id: {} - Empty partnership_image'.format(
                        dana_customer.application.id
                    )
                )
                continue

            img_url = img.image_url_external
            print("IMAGE URL: ", img_url)
            marital_status = get_ocr_marital_status(img_url, client)
            if not marital_status:
                print('application_id: {} - NO TEXT FOUND'.format(dana_customer.application.id))
            elif marital_status != "error":
                dana_customer.application.marital_status = marital_status
                data_list.append(dana_customer.application)
                print(
                    'application_id: {} - marital_status: {}'.format(
                        dana_customer.application.id, marital_status
                    )
                )

                if len(data_list) == batch_limit:
                    bulk_update(data_list, update_fields=['marital_status'], batch_size=batch_limit)
                    print("Success update {} application.marital_status".format(len(data_list)))
                    data_list = []
            else:
                print('application_id: {} - ERROR'.format(dana_customer.application.id))
        else:
            print('application_id: {} - Data incomplete'.format(dana_customer.application.id))

    if len(data_list) > 0:
        bulk_update(data_list, update_fields=['marital_status'])
        print("Success update {} application.marital_status".format(len(data_list)))
