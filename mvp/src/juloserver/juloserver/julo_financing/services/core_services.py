import logging
import os
from PIL import Image as Imagealias

from django.conf import settings
from juloserver.julo.models import Image
from juloserver.julo.utils import construct_customize_remote_filepath, upload_file_to_oss
from juloserver.julo_financing.models import JFinancingProduct, JFinancingCategory
from juloserver.julo_financing.constants import JFinancingFeatureNameConst
from juloserver.julo.models import FeatureSetting


logger = logging.getLogger(__name__)


def is_julo_financing_product_id_valid(product_id: int) -> bool:
    """
    check if Jproduct id is valid
    """
    return JFinancingProduct.objects.filter(
        id=int(product_id),
        is_active=True,
    ).exists()


def is_julo_financing_category_id_valid(category_id: int) -> bool:
    """
    check if Jcategory id is valid
    """
    return JFinancingCategory.objects.filter(pk=category_id).exists()


def is_product_available(product_id: int) -> bool:
    """
    Check if julo financing product is available & in stock
    """
    return JFinancingProduct.objects.filter(
        id=int(product_id),
        is_active=True,
        quantity__gte=1,
    ).exists()


class JFinancingSignatureService:
    def __init__(
        self,
        signature_image: Image,
        customer_id: int,
        thumbnail: bool = True,
        folder_prefix: str = 'loan_',
    ) -> None:
        self.thumbnail = thumbnail
        self.image = signature_image
        self.customer_id = customer_id
        self.folder_prefix = folder_prefix

    def upload_jfinancing_signature_image(self) -> None:
        # Upload file to oss
        self._upload_signature_image()
        self._upload_signature_thumbnail()
        self._delete_local_images()

    def _upload_signature_image(self) -> None:
        # Create remote filepath
        image_remote_filepath = construct_customize_remote_filepath(
            self.customer_id, self.image, self.folder_prefix
        )

        upload_file_to_oss(settings.OSS_MEDIA_BUCKET, self.image.image.path, image_remote_filepath)
        self.image.update_safely(url=image_remote_filepath)
        logger.info(
            {
                'action': 'JFinancingSignatureService._upload_signature_image',
                'image_remote_filepath': image_remote_filepath,
                'julo_financing_loan_id': self.image.image_source,
                'image_type': self.image.image_type,
            }
        )

    def _upload_signature_thumbnail(self) -> None:
        if self.image.image_ext != '.pdf' and self.thumbnail:

            # create thumbnail
            im = Imagealias.open(self.image.image.path)
            im = im.convert('RGB')
            size = (150, 150)
            im.thumbnail(size, Imagealias.ANTIALIAS)
            image_thumbnail_path = self.image.thumbnail_path
            im.save(image_thumbnail_path)

            # upload thumbnail to oss
            thumbnail_dest_name = construct_customize_remote_filepath(
                self.customer_id, self.image, self.folder_prefix, suffix='thumbnail'
            )
            upload_file_to_oss(settings.OSS_MEDIA_BUCKET, image_thumbnail_path, thumbnail_dest_name)
            self.image.update_safely(thumbnail_url=thumbnail_dest_name)

            logger.info(
                {
                    'action': 'JFinancingSignatureService._upload_signature_thumbnail',
                    'thumbnail_dest_name': thumbnail_dest_name,
                    'application_id': self.image.image_source,
                    'image_type': self.image.image_type,
                }
            )

    def _delete_local_images(self) -> None:
        """
        Delete local images if any
        """
        # thumbnail
        image_thumbnail_path = self.image.thumbnail_path
        # delete thumbnail from local disk
        if os.path.isfile(image_thumbnail_path):
            logger.info(
                {
                    'action': 'deleting_thumbnail_local_file',
                    'image_thumbnail_path': image_thumbnail_path,
                    'application_id': self.image.image_source,
                    'image_type': self.image.image_type,
                }
            )
            os.remove(image_thumbnail_path)

        # main
        image_path = self.image.image.path
        if os.path.isfile(self.image.image.path):
            logger.info(
                {
                    'action': 'deleting_local_file',
                    'image_path': image_path,
                    'loan_id': self.image.image_source,
                    'image_type': self.image.image_type,
                }
            )
            self.image.image.delete()

        if self.image.image_status != Image.CURRENT:
            return

        # mark all other images with same type as 'deleted'
        images = list(
            Image.objects.exclude(id=self.image.id)
            .exclude(image_status=Image.DELETED)
            .filter(image_source=self.image.image_source, image_type=self.image.image_type)
        )
        for img in images:
            logger.info({'action': 'marking_deleted', 'image': img.id})
            img.update_safely(image_status=Image.DELETED)


def get_provinces_for_shipping_fee() -> dict:
    """
    Get all provinces from feature setting
    Example:
        {
            "DKI JAKARTA": 10000,
            "JAWA BARAT": 20000,
            "JAWA TENGAH": 30000,
            "JAWA TIMUR": 40000,
        }
    """
    fs = FeatureSetting.objects.filter(
        feature_name=JFinancingFeatureNameConst.JULO_FINANCING_PROVINCE_SHIPPING_FEE
    ).first()
    if not fs.is_active or not fs.parameters:
        return dict()

    return fs.parameters.get('province_shipping_fee', {})


def is_province_supported(province: str) -> bool:
    provinces = get_provinces_for_shipping_fee()
    return province.upper() in provinces.keys()


def get_shipping_fee_from_province(province: str) -> int:
    return get_provinces_for_shipping_fee().get(province.upper(), 0)
