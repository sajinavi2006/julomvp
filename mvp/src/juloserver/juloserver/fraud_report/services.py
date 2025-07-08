import logging
import base64

from django.http import StreamingHttpResponse
from django.conf import settings
from PIL import Image as PILImage
from io import BytesIO

from juloserver.julo.utils import (upload_file_as_bytes_to_oss, get_file_from_oss)
from juloserver.fraud_report.tasks import trigger_fraud_report_email
from juloserver.fraud_report.models import FraudReport
from juloserver.fraud_report.constants import OSS_FRAUD_REPORT_BUCKET
from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.pii_vault.constants import PiiSource

logger = logging.getLogger(__name__)


class FraudReportService(object):
    def __init__(self, application, proof_files, validated_data):
        self.application = application
        self.proof_files = proof_files
        self.data = validated_data
        self.fraud_report = None
        self.pdf_bytes = None
    
    def convert(self, img):
        if img.mode == 'RGBA':
            rgb = PILImage.new('RGB', img.size, (255,255,255)) 
            rgb.paste(img, mask=img.split()[3])
            return(rgb)
        else:
            return(img)

    def convert_proof_images_to_pdf(self):
        images = [PILImage.open(i) for i in self.proof_files]
        images = [self.convert(i) for i in images]
        bytes_io = BytesIO()
        images[0].save(
            bytes_io,
            'PDF',
            resolution=100.00,
            save_all=True,
            append_images=images[1:])
        self.pdf_bytes = bytes_io.getvalue()
    
    def upload_and_save_proof_url(self):
        remote_file_path = 'proof_files/{}.pdf'.format(str(self.application.id))
        upload_file_as_bytes_to_oss(
            OSS_FRAUD_REPORT_BUCKET, self.pdf_bytes, remote_file_path)
        self.fraud_report.proof_remote_path = remote_file_path
        image_url = settings.BASE_URL + '/api/fraud_report/download_fraud_report/' + str(self.application.id)
        self.fraud_report.image_url = image_url
        self.fraud_report.save()
        logger.info({
            'action': 'upload_and_save_proof_url',
            'application_id': self.application.id,
            'success': True
        })
    
    def trigger_email_for_fraud_report(self):
        encoded_attachment = base64.b64encode(self.pdf_bytes).decode()
        attachment_dict = {
            "content": encoded_attachment,
            "filename": '{}_{}.pdf'.format(str(self.application.id), str(self.fraud_report.id)),
            "type": "application/pdf"
        }
        trigger_fraud_report_email.apply_async(
            (self.fraud_report.id, attachment_dict), countdown=3)

    def save_proofs_and_trigger_email(self):
        self.convert_proof_images_to_pdf()
        self.upload_and_save_proof_url()
        self.trigger_email_for_fraud_report()

    def save_and_email_fraud_report(self):
        detokenized_application = detokenize_pii_antifraud_data(
            PiiSource.APPLICATION, [self.application]
        )[0]
        self.fraud_report = FraudReport.objects.create(
            application=detokenized_application,
            nik=detokenized_application.ktp,
            email=detokenized_application.email,
            phone_number=detokenized_application.mobile_phone_1,
            **self.data)
        self.save_proofs_and_trigger_email()


def get_downloadable_response(application):
    fraud_report = FraudReport.objects.filter(application=application).last()
    if fraud_report or not fraud_report.proof_remote_path:
        proof_file_stream = get_file_from_oss(
            OSS_FRAUD_REPORT_BUCKET, fraud_report.proof_remote_path)
        response = StreamingHttpResponse(
            streaming_content=proof_file_stream, content_type='application/pdf')
        downloaded_file_name = 'filename="{}"'.format(
            str(application.id)+'_fraud_report.pdf')
        response['Content-Disposition'] = downloaded_file_name
        return response
    else:
        raise Exception('Application has no fraud report proofs')
