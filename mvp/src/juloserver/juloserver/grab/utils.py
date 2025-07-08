from __future__ import division
from builtins import bytes
from builtins import str
from builtins import object
from past.utils import old_div
from rest_framework import status
from rest_framework.response import Response
import hmac
import hashlib
import base64
import array
import re
from django.conf import settings
from PIL import Image
from io import BytesIO
from django.db import connection
from django.db.models import Prefetch
from juloserver.julo.models import ApplicationHistory
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.clients import get_julo_sms_client
from django.template.loader import render_to_string
from juloserver.julo.utils import format_e164_indo_phone_number, trim_name
from juloserver.julo.models import ApplicationHistory, BlacklistCustomer, Payment
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.services2 import get_redis_client
from juloserver.grab.models import GrabLoanData


class GrabUtils(object):
    redis_client = None

    def set_redis_client(self):
        self.redis_client = get_redis_client()

    def set_redis_key(self, key, value, exp=60 * 60):
        # expire in 6 hours
        self.redis_client.set(key, value, exp)

    @staticmethod
    def create_signature(message, method, uri_path, date_header):
        digest = hashlib.sha256(GrabUtils.text_to_bytes(message)).digest()
        e_digest = base64.b64encode(digest).decode('utf-8')

        encoded_text = "{}\n{}\n{}\n{}\n{}\n".format(method,
                                                     "application/json" if method in ["POST", "PUT"] else "",
                                                     date_header,
                                                     uri_path,
                                                     e_digest)

        encoded_text_bytes = GrabUtils.text_to_array_bytes(encoded_text)
        secret_key_bytes = GrabUtils.text_to_bytes(settings.GRAB_HMAC_SECRET)

        signature = hmac.new(secret_key_bytes, encoded_text_bytes, hashlib.sha256).digest()

        return base64.b64encode(signature).decode('utf-8')

    @staticmethod
    def create_user_token(phone_number):
        encoded_text_bytes = phone_number.encode()
        secret_key_bytes = GrabUtils.text_to_bytes(settings.GRAB_HMAC_SECRET_PHONE_NUMBER)

        signature = hmac.new(secret_key_bytes, encoded_text_bytes, hashlib.sha256).hexdigest()

        return signature

    @staticmethod
    def text_to_array_bytes(text):
        return array.array('B', text.encode("utf8"))

    @staticmethod
    def text_to_bytes(text):
        return bytes(str(text).encode("utf-8"))

    @staticmethod
    def generate_crop_selfie(upload):
        selfie_image = Image.open(upload)
        width, height = selfie_image.size
        cropped_height = (old_div(height, 3)) * 2
        crop_selfie = selfie_image.crop([0, 0, width, cropped_height])
        output = BytesIO()
        crop_selfie.save(output, format='JPEG')
        return crop_selfie, output

    @staticmethod
    def custom_grab_error_messages_for_required(message):
        messages = {
            "blank": str(message + " harus diisi"),
            "null": str(message + " harus diisi"),
            "required": str(message + " harus diisi"),
            "invalid": str(message + " tidak valid"),
        }

        return messages

    @staticmethod
    def create_error_message(error_code, error_message):
        final_error_message = error_code + ": " + error_message
        return final_error_message

    @staticmethod
    def format_grab_mobile_phone(phone_number: str):
        if phone_number.startswith('+62'):
            return phone_number.replace('+62', '62')
        elif phone_number.startswith('0'):
            return phone_number.replace('0', '62', 1)
        elif phone_number.startswith('62'):
            return phone_number

    @staticmethod
    def validate_phone_number(phone_number: str, field_name: str):
        """
        validate grab phone number

        param:
            - phone_number (str): phone number need to be validated,
            - field_name (Str): field name for returning error message

        return:
            - formatted_phone_number (str/None), error_message (str/None)
        """
        prefixes = ['+62', '62', '0']
        formatted_phone_number = None
        error_message = None
        valid_format = phone_number.startswith(tuple(prefixes))
        if not valid_format:
            return formatted_phone_number, "Mohon isi {} dengan format 628xxxxxxxx".format(field_name)

        formatted_phone_number = GrabUtils.format_grab_mobile_phone(phone_number)
        if not re.match(r"^(62)\d{8,12}$", formatted_phone_number):
            return formatted_phone_number, "Mohon isi {} dengan format 8 sampai 12 digit setelah kode negara".format(
                field_name)
        return formatted_phone_number, error_message

    @staticmethod
    def create_digital_signature(user, file_path):
        """
        create a document's digital signature for OJK needs

        return:
            - hash_digi_sign (str): encrypted signature
        """
        # digital signature
        from juloserver.customer_module.services.digital_signature import DigitalSignature
        user = user
        digital_signature = DigitalSignature(
            user=user, key_name="key-{}-1".format(user.id)
        )

        signature = digital_signature.sign(document=file_path)
        hash_digi_sign = signature.get("signature")
        key_id = signature.get('key_id')
        accepted_ts = signature.get('created_at')
        return hash_digi_sign, key_id, accepted_ts

    @staticmethod
    def built_error_message_format(title="", subtitle=""):
        data = {"title": title, "subtitle": subtitle}
        return data

    def check_fullname_with_DTTOT(self, fullname: str) -> bool:
        stripped_name = trim_name(fullname)
        blacklist_key = '%s_%s' % ("blacklist_user_key:", stripped_name)

        if self.redis_client:
            if self.redis_client.exists(blacklist_key):
                return True

        black_list_customer = BlacklistCustomer.objects.filter(
            fullname_trim__iexact=stripped_name
        ).exists()

        if black_list_customer and self.redis_client:
            # stored in redis if name is blacklisted, and expiry in 1 hour
            self.set_redis_key(blacklist_key, 1)

        return black_list_customer

    @staticmethod
    def roundup_loan_amount_to_by_multiplication(loan_amount, multiplier=50000):
        """default multiplier is 50000"""
        from math import ceil

        return ceil(loan_amount / multiplier) * multiplier


def grab_custom_error_messages_for_required():
    messages = {
        "blank": "Harus Diisi",
        "null": "Harus Diisi",
        "required": "Harus Diisi",
        "invalid": "Tidak Valid",
    }
    return messages


class ImageNames(object):
    DESIGNS_REAL = 'info-card/data_bg.png'
    GROUP_3500 = 'info-card/group_3500.png'
    LAYER_3 = 'info-card/layer_3.png'
    LAYER_4 = 'info-card/layer_4.png'
    LAYER_5 = 'info-card/layer_5.png'
    LAYER_6 = 'info-card/layer_6.png'
    RECTANGLE_1489 = 'info-card/rectangle_1489.png'
    RECTANGLE_1489_2 = 'info-card/rectangle_1489_2.png'


def create_image(image_source_id, image_type, image_url):
    from juloserver.julo.models import Image
    image = Image()
    image.image_source = image_source_id
    image.image_type = image_type
    image.url = image_url
    image.save()


class MockValidationProcessService(object):
    data_to_return = {}

    def __init__(self, data_to_return):
        self.data_to_return = data_to_return

    def validate(self, _):
        return self.data_to_return


class GrabSqlUtility(object):
    @staticmethod
    def run_sql_query_for_paid_off_payment_invalid_status(account_lookup_name):
        payment_status_code = PaymentStatusCodes.PAID_ON_TIME
        unformatted_sql_query = """
            select distinct p.loan_id from payment p join loan l on l.loan_id = p.loan_id join
            account a on a.account_id = l.account_id join account_lookup al
            on al.account_lookup_id = a.account_lookup_id
            where al."name" = '{account_lookup_name}' and
            p.due_amount = 0 and p.payment_status_code < {payment_status_code};
        """
        raw_sql_query = unformatted_sql_query.format(
            account_lookup_name=account_lookup_name,
            payment_status_code=payment_status_code
        )
        with connection.cursor() as cursor:
            cursor.execute(raw_sql_query)
            data = cursor.fetchall()
        return data


def response_template(data=None, status=status.HTTP_200_OK, success=True, message=[]):
    response_dict = {
        'success': success,
        'data': data,
        'errors': message
    }
    return Response(status=status, data=response_dict)


def error_response_web_app(message=None, data=None, errors=None):
    """Indicating that request parameters or payload failed valication"""
    if errors is None:
        errors = {}
    if message is None:
        message = {}
    title = ''
    if message:
        message = eval(message)
    if errors:
        for value in errors.values():
            title = title + value[0]+', '
        if title:
            title = title[:-2]
            message = {
                "title": str(title),
                "subtitle": ""
            }

    return response_template(
        data, status.HTTP_400_BAD_REQUEST, False, [message])


def get_customer_name_with_title(gender, fullname):
    if not fullname:
        return ''

    if gender == 'Wanita':
        return 'Ibu ' + fullname.title()
    if gender == 'Pria':
        return 'Bpk ' + fullname.title()
    if not gender:
        return '' + fullname.title()


def send_sms_to_dax_pass_3_max_creditors(phone_number, application):
    template_code = "grab_3_max_creditors_sms"
    sms_client = get_julo_sms_client()
    context = {'url': 'grab.julo.co.id'}
    message = render_to_string("{}.txt".format(template_code), context)
    phone = format_e164_indo_phone_number(phone_number)
    msg, responses = sms_client.send_sms(phone, message)
    for response in responses.get("messages", []):
        create_sms_history(
            response=response,
            customer=application.customer,
            application=application,
            to_mobile_phone=format_e164_indo_phone_number(response['to']),
            phone_number_type='mobile_phone_1',
            template_code=template_code,
            message_content=msg
        )


def is_application_reached_180_before(application):
    # means the app is not passed 3 max creditors before
    return ApplicationHistory.objects.filter(
        application_id=application.id,
        status_old=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
    ).exists()


def get_grab_dpd(account_payment_id):
    oldest_unpaid_payment = Payment.objects.only('id', 'loan_id') \
        .not_paid_active().filter(account_payment_id=account_payment_id).order_by('due_date').last()

    days = 0
    if oldest_unpaid_payment:
        grab_loan_data_set = GrabLoanData.objects.only(
            'id', 'loan_id'
        ).filter(loan_id=oldest_unpaid_payment.loan_id)

        oldest_unpaid_payments_queryset = (
            Payment.objects.only('id', 'loan_id', 'due_date', 'payment_status_id')
            .not_paid_active()
            .order_by('due_date')
        )
        prefetch_oldest_unpaid_payments = Prefetch(
            'loan__payment_set',
            to_attr="grab_oldest_unpaid_payments",
            queryset=oldest_unpaid_payments_queryset,
        )

        prefetch_grab_loan_data = Prefetch(
            'loan__grabloandata_set', to_attr='grab_loan_data_set', queryset=grab_loan_data_set
        )
        # removing the prefetch join tables to solve CRM performance issue
        prefetch_join_tables = [prefetch_grab_loan_data]

        grouped_payments = Payment.objects.select_related('loan').prefetch_related(
            *prefetch_join_tables).filter(
            id=oldest_unpaid_payment.id).last()
        if grouped_payments:
            return grouped_payments.get_grab_dpd

    return days

def get_grab_customer_data_anonymous_user():
    from django.contrib.auth.models import User
    from juloserver.julo.models import Customer
    from juloserver.grab.models import GrabCustomerData

    anonymous_user, _ = User.objects.get_or_create(username='anonymous_user')
    customer, _ = Customer.objects.get_or_create(user=anonymous_user)
    grab_customer_data, _ = GrabCustomerData.objects.get_or_create(customer=customer)
    return grab_customer_data
