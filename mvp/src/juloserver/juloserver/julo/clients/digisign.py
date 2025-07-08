from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import object
import json
import logging
import requests
import urllib.request, urllib.parse, urllib.error
import io
import os
import pdfkit
import datetime

from xhtml2pdf import pisa
from io import StringIO
from datetime import datetime
from io import BytesIO
from PIL import Image as ImageAlias

from django.template.loader import render_to_string

from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (Application,
                                    Image,
                                    Document,
                                    Customer)
from juloserver.followthemoney.models import LenderBucket, LenderCurrent
from juloserver.followthemoney.services import get_summary_loan_agreement_template
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import get_sphp_template
from juloserver.julo.workflows2.tasks import record_digital_signature
from juloserver.julo.services import get_application_sphp

logger = logging.getLogger(__name__)


class JuloDigisignClient(object):
    """Digisign Client"""

    def __init__(self, base_url, token, user_id, pwd,
        platform_email, platform_name, platform_key):
        self.base_url = base_url
        self.token = token
        self.user_id = user_id
        self.pwd = pwd
        self.platform_email = platform_email
        self.platform_name = platform_name
        self.platform_key = platform_key
        self.MAPPING_GENDER = {
            'Pria': "laki-laki",
            'Wanita': "perempuan"
        }


    def register(self, application_id):
        api_url = self.base_url + '/REG-MITRA.html'
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            raise JuloException('Application not exist')

        jsonData = {
            'JSONFile': {
                'userid': self.user_id,
                'alamat': application.address_street_num,
                'jenis_kelamin': self.MAPPING_GENDER[application.gender],
                'kecamatan': application.address_kecamatan,
                'kelurahan': application.address_kelurahan,
                'kode-pos': application.address_kodepos,
                'kota': application.address_kabupaten,
                'nama': application.fullname,
                'tlp': application.mobile_phone_1,
                'tgl_lahir': application.dob.strftime('%d-%m-%Y') if application.dob else None,
                'provinci': application.address_provinsi,
                'idktp': application.ktp,
                'tmp_lahir': application.birth_place,
                'email': application.email,
                'npwp': None,
                'reg_number': None
            }
        }

        # Build ktp and selfie image
        ktp_self_obj = Image.objects.filter(image_source=application.id, image_type='ktp_self',
            image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]).order_by('-udate').first()
        selfie_obj = Image.objects.filter(image_source=application.id, image_type='crop_selfie',
            image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]).order_by('-udate').first()
        ktp_filename = 'ktp_self_{}.jpg'.format(application_id)
        selfie_filename = 'selfie_{}.jpg'.format(application_id)
        image_list = [
            {'filename': ktp_filename, 'url': ktp_self_obj.image_url},
            {'filename': selfie_filename, 'url': selfie_obj.image_url}
        ]

        for img_data in image_list:
            url = img_data.get('url')
            file = io.StringIO(urllib.request.urlopen(url).read())
            image = ImageAlias.open(file)
            image = image.convert('RGB')
            image.save(img_data.get('filename'))

        # Build param data
        files = {
            'jsonfield': (None, json.dumps(jsonData), 'application/json'),
            'fotoktp': open(ktp_filename, 'rb'),
            'fotodiri': open(selfie_filename, 'rb'),
            'ttd': None,
            'fotonpwp': None,
        }
        headers = self.get_headers()

        # Request registration to digisign
        response = requests.post(api_url, headers=headers, files=files)
        status_code = response.status_code
        jsonReponse = response.json() if status_code == 200 else None
        # reassign value to filename for record value to table signature vendor log
        files['fotoktp'] = ktp_filename
        files['fotodiri'] = selfie_filename
        params_digital_signature = {'event': 'digisign_register',
                                       'response_code': status_code,
                                       'response_string': jsonReponse,
                                       'request_string': files,
                                       'vendor': 'Digisign',
                                       'document': None}
        record_digital_signature.delay(application_id, params_digital_signature)
        logger.info({
            'action': 'digisign_register',
            'request': files,
            'response': jsonReponse,
            'ktp_image_id': ktp_self_obj.id,
            'selfie_image_id': selfie_obj.id
        })

        # Delete unused image file
        if os.path.exists(ktp_filename):
            logger.info({
                'action': 'deleting_local_ktp_digisign',
                'filename': ktp_filename,
                'application_id': application_id
            })
            os.remove(ktp_filename)
        if os.path.exists(selfie_filename):
            logger.info({
                'action': 'deleting_local_selfie_digisign',
                'filename': selfie_filename,
                'application_id': application_id
            })
            os.remove(selfie_filename)

        if response.status_code != 200:
            raise JuloException('Failed register customer to digisign ApplicationID: {}, Response Code: {}'
                .format(application_id, status_code))
        return jsonReponse

    def send_document(self, document_id, application_id, filename):
        api_url = self.base_url + '/SendDocMitraAT.html'
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            raise JuloException('Application not exist')

        page = '1'
        llx_user = '473'
        lly_user = '109.7'
        urx_user = '557'
        ury_user = '165.7'
        llx_julo = '30'
        lly_julo = '109.7'
        urx_julo = '120'
        ury_julo = '165.7'
        if application.product_line.product_line_code in ProductLineCodes.pede():
            page = '2'
            llx_user = '473'
            lly_user = '750'
            urx_user = '557'
            ury_user = '800'
            llx_julo = '30'
            lly_julo = '745'
            urx_julo = '120'
            ury_julo = '795'

        elif application.product_line.product_line_code in ProductLineCodes.mtl():
            page = '2'
            llx_user = '473'
            lly_user = '395'
            urx_user = '557'
            ury_user = '445'
            llx_julo = '30'
            lly_julo = '390'
            urx_julo = '120'
            ury_julo = '440'

        send_to = [{'name': self.platform_name, 'email': self.platform_email},
            {'name': application.fullname, 'email': application.email}]
        req_sign = [{'name': self.platform_name, 'email': self.platform_email, 'aksi_ttd': 'at', 'kuser': self.platform_key,
            'user': 'ttd1', 'page': page, 'llx': llx_julo, 'lly': lly_julo, 'urx': urx_julo, 'ury': ury_julo},
            {'name': application.fullname, 'email': application.email, 'aksi_ttd': 'mt',
            'user': 'ttd2', 'page': page, 'llx': llx_user, 'lly': lly_user, 'urx': urx_user, 'ury': ury_user}]
        jsonData = {
            'JSONFile': {
                'userid': self.user_id,
                'document_id': document_id,
                'payment': '3',
                'send-to': send_to,
                'req-sign': req_sign
            }
        }

        # Build sphp pdf
        html = get_application_sphp(application)
        pdfkit.from_string(html, filename)

        # Build param data
        files = {
            'jsonfield': (None, json.dumps(jsonData), 'application/json'),
            'file': open(filename, 'rb')
        }
        headers = self.get_headers()

        # Request send document to digisign
        response = requests.post(api_url, headers=headers, files=files)
        status_code = response.status_code
        jsonReponse = response.json() if status_code == 200 else None
        # reassign value to filename for record value to table signature vendor log
        files['file'] = filename
        params_digital_signature = {'event': 'digisign_send_document',
                                        'response_code': status_code,
                                        'response_string': jsonReponse,
                                        'request_string': files,
                                        'vendor': 'Digisign',
                                        'document': None}
        record_digital_signature.delay(application_id, params_digital_signature)
        logger.info({
            'action': 'digisign_send_document',
            'document_id': document_id,
            'application_id': application,
            'request': files,
            'response': jsonReponse
        })

        # Delete unused pdf file
        if os.path.exists(filename):
            logger.info({
                'action': 'deleting_local_sphp_digisign',
                'filename': filename,
                'application_id': application_id
            })
            os.remove(filename)

        if response.status_code != 200:
            raise JuloException('Failed send document to Digisign. DocumentID: {}, ApplicationID: {}, Reponse Code: {}'
                .format(document_id, application_id, status_code))
        return jsonReponse

    def user_status(self, email):
        api_url = self.base_url + '/CheckUserMitra.html'
        jsonData = {
            'JSONFile': {
                'userid': self.user_id,
                'email': email
            }
        }
        files = {'jsonfield': (None, json.dumps(jsonData), 'application/json')}
        headers = self.get_headers()
        response = requests.post(api_url, headers=headers, files=files)
        status_code = response.status_code

        jsonReponse = response.json() if status_code == 200 else None
        customer = Customer.objects.get_or_none(email=email)
        application = customer.application_set.last()
        params_digital_signature = {'event': 'digisign_user_status',
                                        'response_code': status_code,
                                        'response_string': jsonReponse,
                                        'request_string': files,
                                        'vendor': 'Digisign',
                                        'document': None}
        record_digital_signature.delay(application.id, params_digital_signature)
        logger.info({
            'action': 'digisign_user_status',
            'request': files,
            'response': jsonReponse
        })

        if status_code != 200:
            raise JuloException('Failed get user status from Digisign. Email: {}, Reponse Code: {}'
                .format(email, status_code))
        return jsonReponse

    def document_status(self, document_id):
        api_url = self.base_url + '/STATUSDOC.html'
        jsonData = {
            'JSONFile': {
                'userid': self.user_id,
                'document_id': document_id
            }
        }
        files = {'jsonfield': (None, json.dumps(jsonData), 'application/json')}
        headers = self.get_headers()
        response = requests.post(api_url, headers=headers, files=files)
        status_code = response.status_code

        jsonReponse = response.json() if status_code == 200 else None
        document = Document.objects.get_or_none(id=document_id)
        params_digital_signature = {'event': 'digisign_document_status',
                                        'response_code': status_code,
                                        'response_string': jsonReponse,
                                        'request_string': files,
                                        'vendor': 'Digisign',
                                        'document': document}
        record_digital_signature.delay(document.document_source, params_digital_signature)
        logger.info({
            'action': 'digisign_document_status',
            'request': files,
            'response': jsonReponse
        })

        if response.status_code != 200:
            raise JuloException('Failed get document status from Digisign. DocumentID: {}, Response Code: {}'
                .format(document_id, status_code))
        return jsonReponse

    def get_download_file(self, document_id):
        api_url = self.base_url + '/DWMITRA.html'
        jsonData = {
            'JSONFile': {
                'userid': self.user_id,
                'document_id': document_id
            }
        }
        files = {'jsonfield': (None, json.dumps(jsonData), 'application/json')}
        headers = self.get_headers()

        response = requests.post(api_url, headers=headers, files=files)
        document = Document.objects.get_or_none(id=document_id)
        params_digital_signature = {'event': 'get_download_file',
                                        'response_code': response.status_code,
                                        'response_string': str(response.content),
                                        'request_string': files,
                                        'vendor': 'Digisign',
                                        'document': document}
        record_digital_signature.delay(document.document_source, params_digital_signature)
        if response.status_code != 200:
            raise JuloException('Failed get download file from Digisign')

        return response.content

    def get_download_file_base64(self, document_id):
        api_url = self.base_url + '/DWMITRA64.html'
        jsonData = {
            'JSONFile': {
                'userid': self.user_id,
                'document_id': document_id
            }
        }
        files = {'jsonfield': (None, json.dumps(jsonData), 'application/json')}
        headers = self.get_headers()

        response = requests.post(api_url, headers=headers, files=files)
        status_code = response.status_code
        document = Document.objects.get_or_none(id=document_id)
        params_digital_signature = {'event': 'digisign_download_file_base64',
                                        'response_code': status_code,
                                        'response_string': str(response.content),
                                        'request_string': files,
                                        'vendor': 'Digisign',
                                        'document': document}
        record_digital_signature.delay(document.document_source, params_digital_signature)
        logger.info({
            'action': 'digisign_download_file_base64',
            'request': files,
            'status_code': status_code
        })

        if status_code != 200:
            raise JuloException('Failed get download file base64 from Digisign')

        return response.json()

    def sign_document(self, document_id, email_user, is_web_browser=False):
        api_url = self.base_url + ('/SignWebView.html' if not is_web_browser else '/SignWebViewBased.html')
        jsonData = {
            'JSONFile': {
                'userid': self.user_id,
                'document_id': document_id,
                'email_user': email_user
            }
        }
        files = {'jsonfield': (None, json.dumps(jsonData), 'application/json')}
        headers = self.get_headers()

        response = requests.post(api_url, headers=headers, files=files)
        status_code = response.status_code
        document = Document.objects.get_or_none(id=document_id)
        params_digital_signature = {'event': 'digisign_sign_document',
                                        'response_code': status_code,
                                        'response_string': str(response.content),
                                        'request_string': files,
                                        'vendor': 'Digisign',
                                        'document': document}
        record_digital_signature.delay(document.document_source, params_digital_signature)
        logger.info({
            'action': 'digisign_sign_document',
            'request': files,
            'status_code': status_code
        })

        if status_code != 200:
            error_message = 'Failed get sign document webview from Digisign. '
            if status_code == 401:
                error_message += 'User not active/register. '
            if status_code == 404:
                error_message += 'SPHP Document not uploaded. '

            raise JuloException(error_message + 'Response Code: {}'.format(status_code))

        return response.content

    def activation(self, email_user, is_web_browser):
        api_url = self.base_url + ('/ACTMitra-M.html' if not is_web_browser else '/ACTMitra.html')
        jsonData = {
            'JSONFile': {
                'userid': self.user_id,
                'pwd': self.pwd,
                'email_user': email_user
            }
        }
        files = {'jsonfield': (None, json.dumps(jsonData), 'application/json')}
        headers = self.get_headers()

        response = requests.post(api_url, headers=headers, files=files)
        status_code = response.status_code
        customer = Customer.objects.get_or_none(email=email_user)
        application = customer.application_set.last()
        params_digital_signature = {'event': 'digisign_activation',
                                        'response_code': status_code,
                                        'response_string': str(response.content),
                                        'request_string': files,
                                        'vendor': 'Digisign',
                                        'document': None}
        record_digital_signature.delay(application.id, params_digital_signature)
        logger.info({
            'action': 'digisign_activation',
            'request': files,
            'status_code': status_code
        })

        if status_code != 200:
            raise JuloException('Failed get activation webview from Digisign')

        return response.content

    def get_headers(self):
        headers = {'Authorization': 'Bearer ' + self.token}
        return headers

    def send_lla_document(self, document_id, lender_id, bucket_id, filename):
        api_url = self.base_url + '/SendDocMitraAT.html'
        lender = LenderCurrent.objects.get_or_none(pk=lender_id)
        if not lender:
            raise JuloException('Lender not exist')

        lender_bucket = LenderBucket.objects.get_or_none(pk=bucket_id)
        if not lender_bucket:
            raise JuloException('LenderBucket not exist')

        page = '2'
        llx_julo = '380'
        lly_julo = '700'
        urx_julo = '460'
        ury_julo = '750'

        llx_user = '120'
        lly_user = '700'
        urx_user = '210'
        ury_user = '750'

        send_to = [{'name': self.platform_name, 'email': self.platform_email},
            {'name': lender.lender_name, 'email': lender.poc_email}]
        req_sign = [{'name': self.platform_name, 'email': self.platform_email, 'aksi_ttd': 'at', 'kuser': self.platform_key,
            'user': 'ttd1', 'page': page, 'llx': llx_julo, 'lly': lly_julo, 'urx': urx_julo, 'ury': ury_julo},
            {'name': lender.lender_name, 'email': lender.poc_email, 'aksi_ttd': 'mt',
            'user': 'ttd2', 'page': page, 'llx': llx_user, 'lly': lly_user, 'urx': urx_user, 'ury': ury_user}]
        jsonData = {
            'JSONFile': {
                'userid': self.user_id,
                'document_id': document_id,
                'payment': '3',
                'send-to': send_to,
                'req-sign': req_sign
            }
        }

        # Build sphp pdf
        html = get_summary_loan_agreement_template(lender_bucket, lender)
        pdfkit.from_string(html, filename)

        # Build param data
        files = {
            'jsonfield': (None, json.dumps(jsonData), 'application/json'),
            'file': open(filename, 'rb')
        }
        headers = self.get_headers()

        # Request send document to digisign
        response = requests.post(api_url, headers=headers, files=files)
        status_code = response.status_code
        jsonReponse = response.json() if status_code == 200 else None
        # reassign value to filename for record value to table signature vendor log
        files['file'] = filename
        document = Document.objects.get_or_none(id=document_id)
        params_digital_signature = {'event': 'digisign_send_document',
                                        'response_code': status_code,
                                        'response_string': jsonReponse,
                                        'request_string': files,
                                        'vendor': 'Digisign',
                                        'document': document}
        record_digital_signature.delay(document.document_source, params_digital_signature)
        logger.info({
            'action': 'digisign_send_document',
            'document_id': document_id,
            'lender_id': lender_id,
            'bucket_id': bucket_id,
            'request': files,
            'response': jsonReponse
        })

        # Delete unused pdf file
        if os.path.exists(filename):
            logger.info({
                'action': 'deleting_local_sphp_digisign',
                'filename': filename,
                'lender_id': lender_id,
                'bucket_id': bucket_id,
            })
            os.remove(filename)

        if response.status_code != 200:
            raise JuloException('Failed send document to Digisign. DocumentID: {}, LenderId: {}, BucketId: {}, Reponse Code: {}'
                .format(document_id, lender_id, bucket_id, status_code))
        return jsonReponse
