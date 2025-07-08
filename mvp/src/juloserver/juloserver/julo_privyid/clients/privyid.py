from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import object
import json
import logging
import requests
import urllib.request, urllib.parse, urllib.error
import os
import pdfkit

from io import BytesIO
from PIL import Image as ImageReader
from requests.auth import HTTPBasicAuth

from ..constants import PRIVY_IMAGE_TYPE
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (Image)
from juloserver.loan.services.views_related import get_sphp_template_privy
import warnings

from juloserver.julo.workflows2.tasks import record_digital_signature, record_digital_signature_julo_one

logger = logging.getLogger(__name__)


class JuloPrivyIDClient(object):
    TIMEOUT_DURATION = 1800
    API_CALL_TIME_GAP = 30
    TIMEOUT_ATTEMPTS = 11

    def __init__(self, base_url, merchant_key, username, secret_key, enterprise_token, enterprise_id):
        self.base_url = base_url
        self.merchant_key = merchant_key
        self.username = username
        self.secret_key = secret_key

        self.enterprise_token = enterprise_token
        self.enterprise_id = enterprise_id

        self.images_type = PRIVY_IMAGE_TYPE

    @staticmethod
    def store_privy_response_log(application_id, event, status_code, request_params, response_json,
                                 loan_id, is_julo_one):
        # pop auth data
        request_params.pop('auth')

        # change files data to filename
        if 'files' in request_params:
            for key, file in list(request_params['files'].items()):
                request_params['files'][key] = file.name

        signature_data = {
            'event': event,
            'response_code': status_code,
            'response_string': response_json,
            'request_string': request_params,
            'vendor': 'PrivyID',
            'document': None
        }
        warnings.warn("", PendingDeprecationWarning)
        if not is_julo_one:
            record_digital_signature.delay(application_id, signature_data)
        else:
            record_digital_signature_julo_one.delay(loan_id, signature_data)

    def send_request(self, request_path, request_type, data=None, params=None, files=None, add_headers=None,
                     application_id=None, is_reregistered=False, loan_id=None, is_julo_one=False):
        """
        Send API request to Privy ID Client
        :param request_path: mintos's route url
        :param  request_type: request type [get, post]
        :param data: Dictionary contains data using for requests body usually using by [POST]
        :param params: Dictionary contains data using for requests query params usually using by [GET]
        :param files: Dictionary contains data files usually using for send photos
        :param add_headers: Dictionary contains additional headers data
        :param loan_id: unique loan id
        :param application_id: unique application id
        :param is_julo_one: flag for julo one
        :return: object response.json
        """
        warnings.warn("", PendingDeprecationWarning)

        request_params = dict(
            headers={'Merchant-Key': self.merchant_key},
            auth=HTTPBasicAuth(self.username, self.secret_key),
        )
        if not is_reregistered:
            request_params['url'] = self.base_url + request_path
        else:
            if self.base_url.find('/v1/merchant') == -1:
                request_params['url'] = self.base_url.replace('/merchant', '') + request_path
            else:
                request_params['url'] = self.base_url.replace('/v1/merchant', '/v3') + request_path

        if add_headers:
            request_params['headers'].update(add_headers)

        for key in ('data', 'params', 'files',):
            if eval(key):
                request_params[key] = eval(key)

        try:
            requests_ = eval('requests.%s' % request_type)
            response = requests_(**request_params)

            response.raise_for_status()
            return_response = response.json()
            error = None
        except Exception as error:
            sentry_client = get_julo_sentry_client()
            response = error.response
            is_error_500 = str(response.status_code)[:1] == '5'
            if is_error_500:
                sentry_client.captureException()
                return_response = None
            else:
                return_response = response.json()

        # record resquest and response logs to db
        self.store_privy_response_log(
            application_id, request_path, response.status_code, request_params,
            return_response, loan_id, is_julo_one)

        return return_response

    def registration_proccess(self, application):
        """
        Process registration privy_id
        :param application: application object
        :return: object response.json
        """
        request_path = '/registration'
        request_type = 'post'
        images_type = ['ktp', 'selfie']

        # get image from db and temporary store at server
        request_files = {}
        for img_type in images_type:
            image_obj = Image.objects.filter(
                image_source=application.id, image_type=self.images_type[img_type],
                image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
            ).order_by('-udate').first()

            if image_obj:
                filename = '{}-{}.jpg'.format(img_type, application.id)

                file = BytesIO(urllib.request.urlopen(image_obj.image_url).read())
                image = ImageReader.open(file)
                image = image.convert('RGB')
                image.save(filename)

                request_files.update({
                    img_type: open(filename, 'rb')
                })

        # proccess send request registration
        request_data = {
            'email': application.email,
            'phone': application.mobile_phone_1,
            'identity': json.dumps({
                'nik': application.ktp,
                'nama': application.fullname,
                'tanggalLahir': application.dob.strftime('%Y-%m-%d')
            })
        }

        response = self.send_request(
            request_path,
            request_type,
            data=request_data,
            files=request_files,
            application_id=application.id)

        # delete temporary image from server
        for img_type in images_type:
            filename_ = '{}-{}.jpg'.format(img_type, application.id)
            if os.path.exists(filename_):
                logger.info({
                    'action': 'delete_image_registration_privyid',
                    'filename': img_type,
                    'application_id': application.id
                })
                os.remove(filename_)

        return response

    def reregistration_photos(self, category, user_token, application_id):
        """
        Process registration privy_id
        :param category: photos category example: 'ktp' or 'selfie'
        :param user_token: registration token that got from privyid registration proccess
        :param application_id: unique application id
        :return: object response.json
        """
        category = category.replace('_reupload', '')
        request_path = '/user/merchant/reregister/' + category
        request_type = 'post'

        # get image from db and temporary store at server
        request_files = {}
        filename = '{}-{}.jpg'.format(category, application_id)
        image_obj = Image.objects.filter(
            image_source=application_id, image_type=self.images_type[category + '_reupload'],
            image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
        ).order_by('-udate').first()
        if image_obj:
            file = BytesIO(urllib.request.urlopen(image_obj.image_url).read())
            image = ImageReader.open(file)
            image = image.convert('RGB')
            image.save(filename)
            request_files.update({
                category: open(filename, 'rb')
            })

        additional_headers = {
            'Token': user_token,
        }

        response = self.send_request(
            request_path,
            request_type,
            files=request_files,
            add_headers=additional_headers,
            application_id=application_id,
            is_reregistered=True)

        # delete temporary image from server
        if os.path.exists(filename):
            logger.info({
                'action': 'delete_image_registration_privyid',
                'filename': filename,
                'application_id': application_id
            })
            os.remove(filename)

        return response

    def registration_status(self, user_token, source_id, is_julo_one=False):
        """
        Check registration status to privy_id
        :param user_token: registration token that got from privyid registration proccess
        :param application_id: unique application id
        :return: object response.json
        """
        request_path = '/registration/status'
        request_type = 'post'

        request_data = {
            'token': user_token
        }

        if is_julo_one:
            loan_id = source_id
            application_id = None
        else:
            loan_id = None
            application_id = source_id

        response = self.send_request(
            request_path,
            request_type,
            data=request_data,
            application_id=application_id,
            loan_id=loan_id,
            is_julo_one=is_julo_one)

        return response

    def document_upload(self, customer_privy_id, source_id, is_julo_one=False):
        """
        Process upload document privy_id
        :param customer_privy_id: registration id that got from privyid registration proccess
        :param application_id: unique application id
        :param is_julo_one: flag is set to true is Julo One
        :return: object response.json
        """
        self.base_url = self.base_url.replace("v1", "v3")
        request_path = '/document/upload'
        request_type = 'post'

        # Build sphp pdf
        filename = '{}_{}.pdf'.format(customer_privy_id, source_id)
        request_files = {}
        html = get_sphp_template_privy(source_id)

        if html != '':
            pdfkit.from_string(html, filename)
            request_files['document'] = open(filename, 'rb')

        # proccess upload document
        request_data = {
            "documentTitle": filename,
            "docType": "Serial",
            "templateId": "juloPOA001",
            "owner": json.dumps(
                {
                    "privyId": self.enterprise_id,
                    "enterpriseToken": self.enterprise_token,
                }
            ),
            "recipients": json.dumps(
                [
                    {
                        "privyId": self.enterprise_id,
                        "type": "Signer",
                        "enterpriseToken": self.enterprise_token,
                    },
                    {
                        "privyId": customer_privy_id,
                        "type": "Signer",
                        "enterpriseToken": "",
                    },
                ]
            ),
        }
        if is_julo_one:
            application_id = None
            loan_id = source_id
        else:
            application_id = source_id
            loan_id = None

        response = self.send_request(
            request_path,
            request_type,
            data=request_data,
            files=request_files,
            application_id=application_id,
            loan_id=loan_id,
            is_julo_one=is_julo_one)

        # delete temporary image from server
        if os.path.exists(filename):
            logger.info({
                'action': 'delete_document_upload_privyid',
                'filename': filename,
                'application_id': application_id
            })
            os.remove(filename)

        return response

    def document_status(self, document_token, source_id, is_julo_one=False):
        """
        Check document status to privy_id
        :param document_token: document token that got from privyid document upload proccess
        :param source_id: unique application/loan id
        :param is_julo_one: flag for julo one api calls
        :return: object response.json
        """
        request_path = '/document/status/' + document_token
        request_type = 'get'

        if is_julo_one:
            loan_id = source_id
            application_id = None
        else:
            application_id = source_id
            loan_id = None

        response = self.send_request(request_path, request_type, application_id=application_id,
                                     loan_id=loan_id, is_julo_one=is_julo_one)

        return response

    def create_otp_token(self, customer_privy_id, source_id, is_julo_one=True):
        """
        Create otp token for get access to signing API
        :param customer_privy_id: registration id that got from privyid registration proccess
        :param source_id: unique application/loan id
        :param is_julo_one: is julo one flag
        :return: object response.json
        """
        request_path = '/user-token/token'
        request_type = 'post'

        request_data = {
            'privyId': customer_privy_id
        }
        if is_julo_one:
            loan_id = source_id
            application_id = None
        else:
            application_id = source_id
            loan_id = None

        response = self.send_request(
            request_path,
            request_type,
            data=request_data,
            application_id=application_id,
            loan_id=loan_id,
            is_julo_one=is_julo_one)

        return response

    def request_user_otp(self, otp_token, source_id, is_julo_one=False):
        """
        request privy to send to our customer
        :param otp_token: token got from create_otp_token
        :param source_id: unique application/loan id
        :param is_julo_one: is_julo_one flag for julo one
        :return: object response.json
        """
        request_path = '/user-token/otp-request'
        request_type = 'post'

        additional_headers = {
            'Token': otp_token,
        }

        if is_julo_one:
            loan_id = source_id
            application_id = None
        else:
            application_id = source_id
            loan_id = None

        response = self.send_request(
            request_path,
            request_type,
            add_headers=additional_headers,
            application_id=application_id,
            loan_id=loan_id,
            is_julo_one=is_julo_one)

        return response

    def confirm_user_otp(self, otp_code, otp_token, source_id, is_julo_one=False):
        """
        request privy to send to our customer
        :param otp_code: otp for privy
        :param otp_token: token got from create_otp_token
        :param source_id: unique application/loan id
        :param is_julo_one: flag for julo one
        :return: object response.json
        """
        request_path = '/user-token/otp-confirm'
        request_type = 'post'

        request_data = {
            'code': otp_code
        }

        additional_headers = {
            'Token': otp_token,
        }

        if is_julo_one:
            loan_id = source_id
            application_id = None
        else:
            application_id = source_id
            loan_id = None

        response = self.send_request(
            request_path,
            request_type,
            data=request_data,
            add_headers=additional_headers,
            application_id=application_id,
            loan_id=loan_id,
            is_julo_one=is_julo_one)

        return response

    def document_multiple_sign(self, document_tokens, otp_token, source_id, is_julo_one=False):
        """
        proccess multiple sign
        :param document_tokens: list of string document_token, example ['token', 'token']
        :param otp_token: token got from create_otp_token
        :param source_id: unique application/loan id
        :return: object response.json
        """
        request_path = '/document/multiple-signing'
        request_type = 'post'

        request_data = json.dumps({
            'documents': list([{'docToken': x} for x in document_tokens]),
            'signature': {
                'visibility': True
            }
        })

        additional_header = {
            'Token': otp_token,
            'Content-Type': 'application/json'
        }

        if is_julo_one:
            loan_id = source_id
            application_id = None
        else:
            application_id = source_id
            loan_id = None

        response = self.send_request(
            request_path,
            request_type,
            data=request_data,
            add_headers=additional_header,
            application_id=application_id,
            loan_id=loan_id,
            is_julo_one=is_julo_one)

        return response
