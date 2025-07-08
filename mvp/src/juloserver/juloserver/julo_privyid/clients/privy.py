from future import standard_library
standard_library.install_aliases()
from builtins import str
import os
import requests
import json
import pdfkit
import urllib.request, urllib.parse, urllib.error
from requests.auth import HTTPBasicAuth
from io import BytesIO
from PIL import Image as ImageReader

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo_privyid.clients.privyid import JuloPrivyIDClient
from juloserver.julo_privyid.exceptions import PrivyApiResponseException
from juloserver.julo_privyid.constants import DocumentStatusPrivy
from juloserver.julo.models import Image
from juloserver.loan.services.views_related import get_sphp_template_privy
import logging
from ..constants import PrivyReUploadCodes
logger = logging.getLogger(__name__)


class JuloPrivyClient(JuloPrivyIDClient):

    def make_request(
            self, request_path, request_type, data=None, params=None,
            files=None, extra_headers=None, is_reregistered=False, is_v3=False):

        # basically same logic as self.send_request but:
        # 1. edited the way the make API
        # 2. removed store_privy_response_log from this context

        headers = {'Merchant-Key': self.merchant_key}
        if extra_headers:
            headers.update(extra_headers)

        if not is_reregistered:
            if is_v3:
                url = self.base_url.replace("v1", "v3") + request_path
            else:
                url = self.base_url + request_path
        else:
            if self.base_url.find('/v1/merchant') == -1:
                url = self.base_url.replace('/merchant', '') + request_path
            else:
                url = self.base_url.replace('/v1/merchant', '/v3') + request_path

        try:
            request_method = getattr(requests, request_type)
            response = request_method(
                url=url,
                auth=HTTPBasicAuth(self.username, self.secret_key),
                headers=headers,
                data=data,
                params=params,
                files=files)
            response.raise_for_status()
            response_json = response.json()
        except requests.exceptions.HTTPError as e:
            response = e.response
            if response.status_code >= requests.codes.internal_server_error:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                response_json = None
            else:
                response_json = response.json()

        request_params = dict(
            url=url,
            headers=headers,
            data=data,
            params=params,
            files=files
        )
        api_data = dict(
            response_json=response_json,
            response_status_code=response.status_code,
            request_path=request_path,
            request_params=request_params
        )
        return api_data

    def register(self, application):
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

    def reregister_photos(self, category, user_token, application_id, image_obj, code=None,
                          file_support=None):
        """
                Process registration privy_id
                :param category: photos category example: 'ktp' or 'selfie'
                :param user_token: registration token that got from privyid registration proccess
                :param application_id: unique application id
                :param image_obj: image object to be uploaded
                :param code: type of type
                :param file_support: False if only one image
                :return: object response.json
                """
        request_path = '/user/merchant/reregister/' + category
        request_type = 'post'

        request_files = {}
        request_data = {}
        if category == 'file-support':
            request_files = []
            filename = '{}-{}.jpg'.format(category, application_id)
            if image_obj:
                file = BytesIO(urllib.request.urlopen(image_obj.image_url).read())
                image = ImageReader.open(file)
                image = image.convert('RGB')
                image.save(filename)
                if code == PrivyReUploadCodes.KK and 'KK' in file_support:
                    category_request = 'KK'
                elif code == PrivyReUploadCodes.DRIVING_LICENSE and 'SIM' in file_support:
                    category_request = 'SIM'
                elif code == PrivyReUploadCodes.PASSPORT and 'PASSPORT' in file_support:
                    category_request = 'PASSPORT'
                else:
                    category_request = 'FILE-SUPPORT'
                request_files.append(
                    ('fileSupport[][attachment]', (filename, open(filename, 'rb'), 'image/jpg')),
                )
                request_data = {"fileSupport[][category]": category_request}

            additional_headers = {
                'Token': user_token,
                'Content - Type': 'multipart/form-data'
            }
        # get image from db and temporary store at server
        else:
            filename = '{}-{}.jpg'.format(category, application_id)
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

        api_data = self.make_request(
            request_path,
            request_type,
            data=request_data,
            files=request_files,
            extra_headers=additional_headers,
            is_reregistered=True)
        if 'data' in api_data['response_json']:
            data = api_data['response_json']['data']
        else:
            data = None
        api_data['request_params']['files'] = str(api_data['request_params']['files'])

        # delete temporary image from server
        if os.path.exists(filename):
            logger.info({
                'action': 'delete_image_registration_privyid',
                'filename': filename,
                'application_id': application_id
            })
            os.remove(filename)

        if api_data['response_status_code'] in (200, 201):
            if image_obj:
                image_obj.update_safely(image_status=Image.DELETED)

        return data, api_data

    def register_status(self, user_token):
        """
        Check registration status to privy_id
        :param user_token: registration token that got from privyid registration proccess
        :param loan_id: unique loan id
        :return: object response.json
        """
        request_path = '/registration/status'
        request_type = 'post'

        request_data = {
            'token': user_token
        }

        api_data = self.make_request(
            request_path,
            request_type,
            data=request_data)
        data = api_data['response_json']["data"]
        return data, api_data

    def upload_document(self, customer_privy_id, loan_id):
        """
        Process upload document privy_id
        :param customer_privy_id: registration id that got from privyid registration proccess
        :param loan_id: unique loan id
        :return: object response.json
        """
        request_path = '/document/upload'
        request_type = 'post'

        # Build sphp pdf
        filename = '{}_{}.pdf'.format(customer_privy_id, loan_id)
        request_files = {}
        html = get_sphp_template_privy(loan_id)

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

        api_data = self.make_request(
            request_path,
            request_type,
            data=request_data,
            files=request_files,
            is_v3=True)

        data = api_data['response_json']["data"]

        # delete temporary image from server
        if os.path.exists(filename):
            logger.info({
                'action': 'delete_document_upload_privyid',
                'filename': filename,
                'loan_id': loan_id
            })
            os.remove(filename)

        return data, api_data

    def get_document_status(self, document_token):

        request_path = '/document/status/' + document_token
        request_type = 'get'
        api_data = self.make_request(request_path, request_type)

        if "data" not in api_data['response_json']:
            raise PrivyApiResponseException(
                "No response data for document_token: %s" % document_token)
        data = api_data['response_json']["data"]

        if data.get('documentStatus') == DocumentStatusPrivy.COMPLETED:
            download_url = data['download']['url']
            if not download_url:
                raise PrivyApiResponseException(
                    "No download URL for document_token: %s" % document_token)

        return data, api_data

    def create_token(self, customer_privy_id):
        """
                Create otp token for get access to signing API
                :param customer_privy_id: registration id that got
                 from privyid registration proccess
                :param source_id: unique application/loan id
                :param is_julo_one: is julo one flag
                :return: object response.json
                """
        request_path = '/user-token/token'
        request_type = 'post'

        request_data = {
            'privyId': customer_privy_id
        }

        api_data = self.make_request(
            request_path,
            request_type,
            data=request_data)

        data = api_data['response_json']["data"]

        return data, api_data

    def request_otp_token(self, otp_token):
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

        api_data = self.make_request(
            request_path,
            request_type,
            extra_headers=additional_headers)
        # data = api_data['response_json']["data"]
        return {}, api_data

    def confirm_otp_token(self, otp_code, otp_token):
        """
        request privy to send to our customer
        :param otp_code: otp for privy
        :param otp_token: token got from create_otp_token
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

        api_data = self.make_request(
            request_path,
            request_type,
            data=request_data,
            extra_headers=additional_headers)

        # data = api_data['response_json']["data"]
        return {}, api_data

    def sign_document(self, document_tokens, otp_token):
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
                'visibility': False
            }
        })

        additional_header = {
            'Token': otp_token,
            'Content-Type': 'application/json'
        }

        api_data = self.make_request(
            request_path,
            request_type,
            data=request_data,
            extra_headers=additional_header)
        # data = api_data['response_json']["data"]
        return None, api_data
