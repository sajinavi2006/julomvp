from celery import task

from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Image
from juloserver.julo_financing.services.core_services import JFinancingSignatureService


@task(queue='loan_normal')
def upload_jfinancing_signature_image_task(image_id, customer_id):
    image = Image.objects.get_or_none(pk=image_id)
    if not image:
        raise JuloException(
            "Failed uploading jfinancing signature. Image ID = %s not found" % image_id
        )

    service = JFinancingSignatureService(signature_image=image, customer_id=customer_id)
    service.upload_jfinancing_signature_image()
