from __future__ import division, unicode_literals

import calendar
from typing import List
from bulk_update.helper import bulk_update
from cacheops.invalidation import invalidate_obj

from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5
from difflib import SequenceMatcher

from .formulas import filter_due_dates_by_pub_holiday, filter_due_dates_by_weekend
from .constants import FeatureNameConst
from .clients import get_object_storage_client
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.exceptions import (
    BadStatuses,
    InvalidPhoneNumberError,
    JuloException,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.fdc.constants import FDCConstant
from juloserver.account.constants import ImageSource
from rest_framework.response import Response
from requests.exceptions import ReadTimeout
from geopy.geocoders import Nominatim
from email_validator import EmailNotValidError, validate_email
from django.utils import timezone
from django.db import transaction
from django.core.files.base import File
from django.conf import settings
from dateutil.relativedelta import relativedelta
from cryptography.fernet import Fernet
from babel.numbers import format_number
import requests
import phonenumbers
import oss2
from hashlib import sha1
from datetime import date, datetime, time, timedelta
from builtins import map, range, str
import zipfile
import uuid
import urllib.request
import urllib.parse
import urllib.error
import unicodedata
import time as time1
import string
import shutil
import re
import random
import os
import mimetypes
import logging
import json
import io
import hmac
import hashlib
import copy
import base64
import phonenumbers

import mock
from future import standard_library
from past.utils import old_div

standard_library.install_aliases()
from PIL import Image
import base64
import copy
import hashlib
import hmac
import io
import json
import logging
import mimetypes
import os
import random
import re
import shutil
import string
import time as time1
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from builtins import map, range, str
from datetime import date, datetime, time, timedelta
from hashlib import sha1

import oss2
import phonenumbers
import requests
from babel.numbers import format_number
from cryptography.fernet import Fernet
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.files.base import File
from django.db import transaction
from django.utils import timezone
from email_validator import EmailNotValidError, validate_email
from geopy.geocoders import Nominatim
from requests.exceptions import ReadTimeout
from rest_framework.response import Response

from juloserver.account.constants import ImageSource
from juloserver.fdc.constants import FDCConstant
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import (
    BadStatuses,
    InvalidPhoneNumberError,
    JuloException,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client

from .clients import get_object_storage_client
from .constants import FeatureNameConst
from .formulas import filter_due_dates_by_pub_holiday, filter_due_dates_by_weekend
from juloserver.julocore.python2.utils import py2round

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()
ANA_MAX_RETRY = 5


def email_blacklisted(email):
    """
    These cannot be used for registration as we cannot get their email messages
    with the gmail API.
    """
    black_list = ['@yahoo.', '@rocketmail.', '@ymail.', '@hotmail.']
    return any(word in email for word in black_list)


def verify_nik(nik):
    """
    Check or Validate NIK:
    - make sure NIK have 16 digit not more or less
    - have a standard indonesian format

    Param:
        - nik (str): nik

    Returns:
        - true for valid nik
    """
    birth_day = int(nik[6:8])
    if len(nik) != 16 or not nik.isdigit():
        return False
    initial_digit = nik[0]
    if int(initial_digit) == 0:
        return False
    if not (1 <= int(nik[0:2])) or not (1 <= int(nik[2:4])) or not (1 <= int(nik[4:6])):
        return False
    if not (1 <= birth_day <= 31 or 41 <= birth_day <= 71):
        return False
    if not (1 <= int(nik[8:10]) <= 12):
        return False
    if not (1 <= int(nik[12:])):
        return False
    return True


def display_rupiah(number):
    return "Rp " + format_number(number, locale='id_ID')


def display_rupiah_no_space(number) -> str:
    return "Rp" + format_number(number, locale='id_ID')


def display_rupiah_skrtp(number):
    return "Rp" + format_number(number, locale='id_ID')


def display_IDR(number):
    return "IDR " + format_number(number, locale='id_ID')


def convert_to_me_value(number):
    returned_val = number
    if int(number) >= 1000000:
        returned_val = int(number / 100000) / 10

        # example 5.0 => 5
        if returned_val % int(returned_val) == 0:
            returned_val = int(returned_val)
        returned_val = f'{returned_val} Juta'
    else:
        returned_val = int(round(number / 1000, 0))
        returned_val = f'{returned_val} Ribu'
    return returned_val


def display_bank_account_number(number):
    display = ''
    number_length = len(number)
    i = 0

    while i < number_length:
        display += number[i]
        if (i + 1) % 4 == 0:
            display += ' '
        i += 1
    return display


def construct_remote_filepath_base(
    customer_id, image, suffix=None, source_image_id=None, image_file_name=None
):
    """Using some input constructing folder structure in cloud storage"""

    # construct destination name
    if 2000000000 < int(image.image_source) < 2999999999:
        folder_type = 'application_'
    elif 3000000000 < int(image.image_source) < 3999999999:
        folder_type = 'loan_'
    elif 1000000000 < int(image.image_source) < 1999999999:
        folder_type = 'customer_'
    elif source_image_id == ImageSource.ACCOUNT_PAYMENT:
        folder_type = 'account_payment_'

    subfolder = folder_type + str(image.image_source)
    _, file_extension = os.path.splitext(image_file_name)
    if suffix:
        filename = "%s_%s_%s%s" % (
            image.image_type, str(image.id), suffix, file_extension)
    else:
        filename = "%s_%s%s" % (
            image.image_type, str(image.id), file_extension)

    dest_name = '/'.join(['cust_' + str(customer_id), subfolder, filename])
    logger.info({'remote_filepath': dest_name})
    return dest_name


def construct_remote_filepath(customer_id, image, suffix=None, source_image_id=None):
    """Using some input constructing folder structure in cloud storage"""
    return construct_remote_filepath_base(
        customer_id, image, suffix, source_image_id, image.image.name
    )


def construct_customize_remote_filepath(customer_id, image, folder_type, suffix=None):
    subfolder = folder_type + str(image.image_source)
    _, file_extension = os.path.splitext(image.image.name)
    if suffix:
        filename = "%s_%s_%s%s" % (
            image.image_type, str(image.id), suffix, file_extension)
    else:
        filename = "%s_%s%s" % (
            image.image_type, str(image.id), file_extension)

    dest_name = '/'.join(['cust_' + str(customer_id), subfolder, filename])
    logger.info({'remote_filepath': dest_name})
    return dest_name


def construct_public_remote_filepath(image, subfolder="public", suffix=None):
    """Construct public image url for cloud storage"""
    file_name = datetime.now().strftime('%Y%m%d%H%M%S%f')
    _, file_extension = os.path.splitext(image.name)
    if suffix:
        filename = "%s_%s%s" % (file_name, suffix, file_extension)
    else:
        filename = "%s%s" % (file_name, file_extension)
    dest_name = '/'.join([subfolder, filename])
    logger.info({'remote_filepath': dest_name})
    return dest_name


def redirect_post_to_anaserver(url, data, files=None):
    headers = {'Authorization': 'Token %s' % settings.ANASERVER_TOKEN}
    result = requests.post(
        settings.ANASERVER_BASE_URL + url,
        data=data, files=files, headers=headers)
    try:
        return Response(status=result.status_code, data=result.json())
    except ValueError:
        return Response(status=result.status_code, data=result.content)


def post_anaserver(url, data=None, json=None):
    from juloserver.monitors.notifications import notify_failed_post_anaserver

    headers = {'Authorization': 'Token %s' % settings.ANASERVER_TOKEN}
    url = settings.ANASERVER_BASE_URL + url
    log_data = {
        'action': "post call to anaserver",
        'url': url,
        'data': data,
        'json': json}
    logger.info(log_data)

    # 408 (Request Timeout)
    # 502 (Bad Gateway)
    # 503 (Service Unavailable)
    # 504 (Gateway Timeout)
    retry_statuses = [408, 502, 503, 504]
    good_statuses = [200, 201]

    retry_count = 0
    while retry_count <= ANA_MAX_RETRY:
        time1.sleep(2 ** retry_count)
        try:
            response = requests.post(url, data=data, json=json, headers=headers)
            if response.status_code in good_statuses:
                return response
            elif response.status_code in retry_statuses:
                raise BadStatuses
            else:
                break  # out of loop
        except (ReadTimeout, BadStatuses):
            retry_count += 1

    # notify slack for failed ana request
    notify_failed_post_anaserver(log_data)

    err_msg = "POST to anaserver url {} fails: {}, {}".format(
        url, response.status_code, response.text)
    raise JuloException(err_msg)


class StorageType:
    LOCAL = 'local'
    S3 = 's3'
    OSS = 'oss'


def push_file_to_s3(bucket_name, file_path, s3_key_path):
    """ public method to upload image to s3 instance
    parameter file_path: absolute path to local file
    parameter dest_name: destination name of the file in s3 without extension (e.g. "1_KTP")
    return: the relative URL on s3 instance
    """

    # Get the mime type since boto3 needs ContentType otherwise
    # it will upload as binary/octet-stream
    mime_type = mimetypes.guess_type(file_path)
    s3 = get_object_storage_client()
    logger.info({
        'action': 'uploading file to s3',
        'bucket_name': bucket_name,
        'filepath': file_path,
        's3_key_path': s3_key_path,
        'mime_type': mime_type
    })

    s3.Bucket(bucket_name).upload_file(file_path,
                                       s3_key_path,
                                       ExtraArgs={'ContentType': mime_type[0]})

    bucket_key_name = bucket_name + '/' + s3_key_path
    logger.info({
        'action': 'uploaded',
        'bucket_key_name': bucket_key_name,
        'filepath': file_path,
    })
    return bucket_key_name


def push_in_mem_file_to_s3(buf, s3_key_path, bucket_name=settings.S3_DATA_BUCKET):
    s3 = get_object_storage_client()
    logger.info({
        'action': 'uploading memory buffer to s3',
        'bucket_name': bucket_name,
        's3_key_path': s3_key_path,
    })
    bucket = s3.Bucket(bucket_name)
    bucket.put_object(Body=buf, Key=s3_key_path)
    return bucket_name + '/' + s3_key_path


def upload_file_to_s3(file_path, bucket_name, dest_name):
    """
    Function to push file into S3 bucket. Deletes file from local filesystem.
    """

    # get the mime type since boto3 needs ContentType otherwise it will uploaded
    # as binary/octet-stream
    mime_type = mimetypes.guess_type(file_path)
    s3 = get_object_storage_client()
    s3.Bucket(bucket_name).upload_file(file_path,
                                       dest_name,
                                       ExtraArgs={'ContentType': mime_type[0]})

    s3_url = os.path.join(bucket_name, dest_name)
    logger.info({
        'status': 'file_uploaded_to_s3',
        'file': file_path,
        's3_url': s3_url
    })

    if os.path.exists(file_path):
        logger.info({
            'action': 'deleting',
            'file': file_path,
        })
        os.remove(file_path)

    return s3_url


class OSSBucket:
    def __init__(self, bucket):
        endpoint = settings.OSS_ENDPOINT
        auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
        self.bucket = oss2.Bucket(auth, endpoint, bucket)

    def __call__(self, *args, **kwargs):
        return self.bucket


def oss_bucket(bucket):
    return OSSBucket(bucket)()


def check_file_is_exist(file_path):
    fib1, fib2 = 1, 1  # Start with the first two Fibonacci numbers
    total_delay = 0
    max_total_delay = 30

    while not os.path.exists(file_path):
        delay = min(fib2, max_total_delay - total_delay)
        if delay <= 0:
            break

        logger.info("check_file_is_exist_file_not_found|path={}, delay={}".format(file_path, delay))
        time1.sleep(delay)
        total_delay += delay

        # Update Fibonacci values for the next delay
        fib1, fib2 = fib2, fib1 + fib2

    return os.path.exists(file_path)


def upload_file_to_oss(bucket_name, local_filepath, remote_filepath):
    if not check_file_is_exist(local_filepath):
        raise JuloException(
            'process_image_upload_local_file_path_not_found|local_file_path={}'.format(
                local_filepath
            )
        )

    endpoint = settings.OSS_ENDPOINT
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    logger.info({
        'action': 'uploading_file',
        'bucket_name': bucket_name,
        'local_filepath': local_filepath,
        'remote_filepath': remote_filepath,
    })
    bucket.put_object_from_file(remote_filepath, local_filepath)
    logger.info({
        'status': 'uploaded',
        'bucket_name': bucket_name,
        'remote_filepath': remote_filepath,
    })


def upload_file_as_bytes_to_oss(
    bucket_name: str,
    file_bytes: bytes,
    remote_filepath: str,
):
    if settings.ENVIRONMENT == "dev":
        return
    endpoint = settings.OSS_ENDPOINT
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    logger.info({
        'action': 'uploading_file',
        'bucket_name': bucket_name,
        'remote_filepath': remote_filepath})
    bucket.put_object(remote_filepath, file_bytes)

    logger.info({
        'status': 'uploaded',
        'bucket_name': bucket_name,
        'remote_filepath': remote_filepath})


def get_file_from_oss(bucket_name, remote_filepath):
    endpoint = settings.OSS_ENDPOINT
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    logger.info({
        'action': 'get_file_from_oss',
        'bucket_name': bucket_name,
        'remote_filepath': remote_filepath,
    })

    return bucket.get_object(remote_filepath)


def put_public_file_to_oss(bucket_name, file, remote_filepath):
    endpoint = settings.OSS_ENDPOINT
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    logger.info({
        'action': 'uploading_file',
        'bucket_name': bucket_name,
        'remote_filepath': remote_filepath,
    })
    update_obj = bucket.put_object(remote_filepath, file)
    logger.info({
        'status': 'uploaded',
        'bucket_name': bucket_name,
        'remote_filepath': remote_filepath,
    })
    return update_obj


def delete_public_file_from_oss(bucket_name, remote_filepath):
    endpoint = settings.OSS_ENDPOINT
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    logger.info({
        'action': 'delete_file',
        'bucket_name': bucket_name,
        'remote_filepath': remote_filepath,
    })
    delete_obj = bucket.delete_object(remote_filepath)
    logger.info({
        'status': 'deleted',
        'bucket_name': bucket_name,
        'remote_filepath': remote_filepath,
    })
    return delete_obj


def get_oss_public_url(bucket_name, remote_path):
    domain_name = settings.OSS_PUBLIC_DOMAIN_NAME
    return "https://%s.%s/%s" % (bucket_name, domain_name, remote_path)


def get_oss_presigned_url(bucket_name, remote_filepath, expires_in_seconds=120):
    endpoint = settings.OSS_ENDPOINT
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    url = bucket.sign_url('GET', remote_filepath, expires_in_seconds)
    logger.info({
        'bucket_name': bucket_name,
        'remote_filepath': remote_filepath,
        'url': url
    })
    return url


def get_oss_presigned_url_external(bucket_name, remote_filepath, expires_in_seconds=120):
    endpoint = settings.JULOFILES_BUCKET_URL
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    url = bucket.sign_url('GET', remote_filepath, expires_in_seconds)
    logger.info({
        'bucket_name': bucket_name,
        'remote_filepath': remote_filepath,
        'url': url
    })
    key = url.split('/')
    final_url = settings.JULOFILES_BUCKET_URL + key[-1]

    return final_url

def create_zip_folder(folder_path):
    """
    Function to zip folders contens and delete folder from local filesystem.
    """
    parent_dir, dir_name = os.path.split(os.path.dirname(folder_path))
    zip_file_root = os.path.join(parent_dir, dir_name)

    zip_file_path = shutil.make_archive(zip_file_root, 'zip', folder_path)
    shutil.rmtree(folder_path)

    return zip_file_path


def create_zip_file(file_path):
    zip_file_path = os.path.splitext(file_path)[0] + '.zip'
    with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(file_path, os.path.basename(file_path))
    os.remove(file_path)
    return zip_file_path


def check_email(email):
    if email.endswith("julofinance.com") or email.endswith("julo.co.id"):
        return True
    # verify the email format
    match = re.match('^[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,4})$', email)
    if match is None:
        return False
    # validate the domain using email_validator
    try:
        v = validate_email(email)

    except EmailNotValidError:
        return False

    if 'mx-fallback' in v:
        if v['mx-fallback'] != False:
            return False
    if 'unknown-deliverability' in v:
        if v['unknown-deliverability'] == 'timeout':
            return False

    return True


def generate_email_key(email):
    """
    Create a hash that will be concatinated in
    verification url to confirm email addrees.
    """
    salt = hashlib.sha1(str(random.random()).encode()).hexdigest()
    value = (salt + email).encode()
    activation_key = hashlib.sha1(value).hexdigest()
    logger.debug({
        'activation_key': activation_key,
        'email': email
    })
    return activation_key


def generate_phone_number_key(phone_number):
    """
    Create a hash that will be concatinated in
    verification url to confirm email addrees.
    """
    salt = hashlib.sha1(str(random.random()).encode()).hexdigest()
    value = (salt + phone_number).encode()
    activation_key = hashlib.sha1(value).hexdigest()
    logger.debug({
        'activation_key': activation_key,
        'phone_number': phone_number
    })
    return activation_key


def format_e164_indo_phone_number(phone_number):
    try:
        if not phone_number:
            #raise JuloException('invalid_phone_number|phone_number={}'.format(phone_number))
            logger.debug({
                'phone_number': phone_number,
                'error': 'invalid_phone_number'
            })
            return phone_number
        phone_length = len(phone_number)

        if isinstance(phone_number, str) and phone_length <= 11\
                and phone_number.startswith('62'):
            return format_e164_indo_old_phone_number(phone_number)
    except JuloException as err:
        sentry_client.captureException()
        return phone_number

    try:
        parsed_phone_number = phone_number
        if isinstance(phone_number, str):
            parsed_phone_number = phonenumbers.parse(phone_number, "ID")
        e164_indo_phone_number = phonenumbers.format_number(
            parsed_phone_number, phonenumbers.PhoneNumberFormat.E164)
    except Exception as err:
        logger.exception('format_e164_indo_phone_number_raise_exception|error={}'.format(err))
        return phone_number
    logger.debug({
        'phone_number': phone_number,
        'formatted_phone_number': e164_indo_phone_number
    })
    return e164_indo_phone_number


def format_e164_indo_old_phone_number(phone_number: str):
    logger.info('format_e164_indo_old_phone_number|phone_number={}'.format(phone_number))
    is_start_with_area_code = True if phone_number.startswith('62') else False
    if not is_start_with_area_code:
        logger.warning('format_e164_indo_old_phone_number_not_start_with_area_code|'
                       'phone_number={}'.format(phone_number))
        return phone_number
    return '+{}'.format(phone_number)


def format_valid_e164_indo_phone_number(phone_number: str):
    """
    Format the string to a valid e164 Indonesia phone number format.

    :param phone_number: String | phonenumbers.PhoneNumber
    :return: string, A valid e164 Indonesia Phone Number
    :raise: InvalidPhoneNumberError, if the phone number is invalid format or invalid number.
    """
    try:
        if isinstance(phone_number, phonenumbers.PhoneNumber):
            parsed_phone_number = phone_number
        else:
            if not isinstance(phone_number, str):
                raise InvalidPhoneNumberError(
                    "Invalid phone number [{}] [type={}]".format(phone_number, type(phone_number))
                )

            if phone_number.startswith('62'):
                phone_number = '+{}'.format(phone_number)

            parsed_phone_number = phonenumbers.parse(phone_number, "ID")

        if not phonenumbers.is_valid_number(parsed_phone_number):
            raise InvalidPhoneNumberError(
                "Invalid phone number [{}]".format(phone_number)
            )

        e164_indo_phone_number = phonenumbers.format_number(
            parsed_phone_number, phonenumbers.PhoneNumberFormat.E164
        )
        return e164_indo_phone_number
    except phonenumbers.NumberParseException:
        raise InvalidPhoneNumberError("Invalid format phone number [{}]".format(phone_number))


def format_nexmo_voice_phone_number(phone_number):
    formatted_number = format_e164_indo_phone_number(phone_number)
    if '+' in formatted_number:
        return formatted_number.replace('+', '')
    return formatted_number


def format_national_phone_number(phone_number):
    try:
        parsed_phone_number = phonenumbers.parse(phone_number, "ID")
        national_number = parsed_phone_number.national_number
    except:
        return phone_number
    logger.debug({
        'phone_number': phone_number,
        'formatted_phone_number': national_number
    })
    return national_number


def format_mobile_phone(phone_number) -> str:
    """
    Simple formatting to transform e164 format number to Indonesia's landline format.

    Args:
        phone_number (str): Phone number to be checked and transformed.

    Returns:
        str: Returns the transformed phone_number.
    """
    if '+' in phone_number:
        return phone_number.replace('+62', '0')
    elif phone_number.startswith('62'):
        return phone_number.replace('62', '0', 1)
    else:
        return phone_number


def is_indonesia_landline_mobile_phone_number(phone_number: str) -> bool:
    """
    Check whether a given phone_number is considered Indonesia's landline mobile phone number.
    Not to be confused with e164 format that uses country code 62.

    Args:
        phone_number (str): Phone number to be checked.

    Returns:
        bool: Returns True if it passes criteria for Indonesia's landline phone number.
    """
    pattern = r'^0[1-9][0-9]{8,11}$'
    return True if re.match(pattern, phone_number) else False


def generate_guid():
    guid = str(uuid.uuid4())
    return guid


def generate_hmac(secret_key, string):
    string_to_sign = string.encode()
    hashed = hmac.new(string_to_sign, secret_key.encode(), sha1)
    hmac_hex = hashed.hexdigest()
    logger.debug({
        'string': string,
        'secret_key': secret_key,
        'hmac_sha1': hmac_hex
    })
    return hmac_hex


def generate_transaction_id(application_xid):
    ts = timezone.now()
    str_ts = ts.strftime('%Y%m%d%H%M%S')
    transaction_id = 'julo_' + str(application_xid) + '_' + str_ts
    logger.debug({
        'application_xid': application_xid,
        'time_stamp': ts,
        'transaction_id': transaction_id
    })
    return transaction_id


def get_delayed_rejection_time(
        rejection_time, delay_hours=8, latest_hour=22, earliest_hour=10):

    delay = relativedelta(hours=delay_hours)
    delayed_rejection_time = rejection_time + delay

    next_day_morning = relativedelta(
        days=1, hour=earliest_hour, minute=0, second=0, microsecond=0)
    this_morning = relativedelta(
        hour=earliest_hour, minute=0, second=0, microsecond=0)

    if delayed_rejection_time.hour >= latest_hour or delayed_rejection_time.hour < earliest_hour:

        if delayed_rejection_time.hour >= latest_hour:
            delayed_rejection_time = delayed_rejection_time + next_day_morning
        elif delayed_rejection_time.hour < earliest_hour:
            delayed_rejection_time = delayed_rejection_time + this_morning

    logger.debug({
        'rejection_time': str(rejection_time),
        'delayed_rejection_time': str(delayed_rejection_time)
    })
    return delayed_rejection_time


def generate_temporary_password():
    str_char = 'abcdefghijklmnopqrstuvwxyz0123456789'
    max_char = 8
    temporary_password = ''
    for i in range(max_char):
        temporary_password += random.choice(str_char)
    return temporary_password


def generate_sha1_base64(keystring, salt):
    hashed = hmac.new(salt.encode('utf-8'), keystring.encode('utf-8'), digestmod=sha1)
    return base64.b64encode(hashed.digest()).decode().rstrip('\n')


def generate_sha1_md5(keystring):
    key_sha1_md5 = hashlib.sha1(
        hashlib.md5(keystring.encode()).hexdigest().encode()
    ).hexdigest()
    return key_sha1_md5


def generate_sha512(keystring):
    return hashlib.sha512(keystring.encode()).hexdigest()


def scrub(x):
    ret = copy.deepcopy(x)
    # Handle dictionaries. Scrub all values
    if isinstance(x, dict):
        for k, v in list(ret.items()):
            ret[k] = scrub(v)
    # Handle None
    if x == None:
        ret = ''
    # Handle None
    if x == "None":
        ret = ''
    # Handle datetime
    if isinstance(x, (datetime, date)):
        ret = x.isoformat()
    # Finished scrubbing
    return ret


def get_penghasilan_perbulan(amount):
    if amount <= 5000000:
        return 'G1'
    elif amount >= 5000000 and amount <= 10000000:
        return 'G2'
    elif amount >= 10000000 and amount <= 50000000:
        return 'G3'
    elif amount >= 50000000 and amount <= 100000000:
        return 'G4'
    elif amount > 100000000:
        return 'G5'
    else:
        return ''


def get_jenis_pekerjaan(application):
    if application.job_type == 'Pegawai swasta':
        return 'SWAS'
    elif application.job_type == 'Pegawai negeri':
        return 'PNSI'
    elif application.job_type == 'Pengusaha':
        return 'WIRA'
    elif application.job_type == 'Mahasiswa':
        return 'MAHA'
    elif application.job_industry == 'Admin / Finance / HR' and application.job_description == 'Admin':
        return 'SERV'
    elif application.job_industry == 'Admin / Finance / HR' and application.job_description == 'Akuntan / Finance':
        return 'PROF'
    elif application.job_industry == 'Admin / Finance / HR' and application.job_description == 'HR':
        return 'SERV'
    elif application.job_industry == 'Admin / Finance / HR' and application.job_description == 'Office Boy':
        return 'SERV'
    elif application.job_industry == 'Admin / Finance / HR' and application.job_description == 'Sekretaris':
        return 'SERV'
    elif application.job_industry == 'Design / Seni' and application.job_description == 'Design Grafis':
        return 'SENI'
    elif application.job_industry == 'Design / Seni' and application.job_description == 'Pelukis':
        return 'SENI'
    elif application.job_industry == 'Design / Seni' and application.job_description == 'Photographer':
        return 'SENI'
    elif application.job_industry == 'Design / Seni' and application.job_description == 'Lainnya':
        return 'SENI'
    elif application.job_industry == 'Entertainment / Event' and application.job_description == 'DJ / Musisi':
        return 'SENI'
    elif application.job_industry == 'Entertainment / Event' and application.job_description == 'Event Organizer':
        return 'SERV'
    elif application.job_industry == 'Entertainment / Event' and application.job_description == 'Kameraman':
        return 'SENI'
    elif application.job_industry == 'Entertainment / Event' and application.job_description == 'Penyanyi / Penari / Model':
        return 'SENI'
    elif application.job_industry == 'Entertainment / Event' and application.job_description == 'Produser / Sutradara':
        return 'SENI'
    elif application.job_industry == 'Hukum / Security / Politik' and application.job_description == 'Anggota Pemerintahan':
        return 'PNSI'
    elif application.job_industry == 'Hukum / Security / Politik' and application.job_description == 'Hakim / Jaksa / Pengacara':
        return 'PGCR'
    elif application.job_industry == 'Hukum / Security / Politik' and application.job_description == 'Notaris':
        return 'NOTA'
    elif application.job_industry == 'Hukum / Security / Politik' and application.job_description == 'Satpam':
        return 'SERV'
    elif application.job_industry == 'Hukum / Security / Politik' and application.job_description == 'TNI / Polisi':
        return 'MILP'
    elif application.job_industry == 'Kesehatan' and application.job_description == 'Apoteker':
        return 'PROF'
    elif application.job_industry == 'Kesehatan' and application.job_description == 'Dokter':
        return 'PROF'
    elif application.job_industry == 'Kesehatan' and application.job_description == 'Perawat':
        return 'PROF'
    elif application.job_industry == 'Kesehatan' and application.job_description == 'Teknisi Laboratorium':
        return 'TECH'
    elif application.job_industry == 'Konstruksi / Real Estate' and application.job_description == 'Arsitek / Tehnik Sipil':
        return 'TECH'
    elif application.job_industry == 'Konstruksi / Real Estate' and application.job_description == 'Interior Designer':
        return 'SENI'
    elif application.job_industry == 'Konstruksi / Real Estate' and application.job_description == 'Mandor':
        return 'PROD'
    elif application.job_industry == 'Konstruksi / Real Estate' and application.job_description == 'Pemborong':
        return 'PROD'
    elif application.job_industry == 'Konstruksi / Real Estate' and application.job_description == 'Proyek Manager / Surveyor':
        return 'PROD'
    elif application.job_industry == 'Konstruksi / Real Estate' and application.job_description == 'Real Estate Broker':
        return 'PROD'
    elif application.job_industry == 'Konstruksi / Real Estate' and application.job_description == 'Tukang Bangunan':
        return 'SERV'
    elif application.job_industry == 'Media' and application.job_description == 'Kameraman':
        return 'SENI'
    elif application.job_industry == 'Media' and application.job_description == 'Penulis / Editor':
        return 'SENI'
    elif application.job_industry == 'Media' and application.job_description == 'Wartawan':
        return 'PROF'
    elif application.job_industry == 'Pabrik / Gudang' and application.job_description == 'Buruh Pabrik / Gudang':
        return 'SWAS'
    elif application.job_industry == 'Pabrik / Gudang' and application.job_description == 'Kepala Pabrik / Gudang':
        return 'SWAS'
    elif application.job_industry == 'Pabrik / Gudang' and application.job_description == 'Teknisi Mesin':
        return 'TECH'
    elif application.job_industry == 'Pendidikan' and application.job_description == 'Dosen':
        return 'GUST'
    elif application.job_industry == 'Pendidikan' and application.job_description == 'Guru':
        return 'GUST'
    elif application.job_industry == 'Pendidikan' and application.job_description == 'Instruktur / Pembimbing Kursus':
        return 'GUST'
    elif application.job_industry == 'Pendidikan' and application.job_description == 'Kepala Sekolah':
        return 'GUST'
    elif application.job_industry == 'Pendidikan' and application.job_description == 'Tata Usaha':
        return 'SERV'
    elif application.job_industry == 'Perawatan Tubuh' and application.job_description == 'Fashion Designer':
        return 'SENI'
    elif application.job_industry == 'Perawatan Tubuh' and application.job_description == 'Gym / Fitness':
        return 'GUST'
    elif application.job_industry == 'Perawatan Tubuh' and application.job_description == 'Pelatih / Trainer':
        return 'GUST'
    elif application.job_industry == 'Perawatan Tubuh' and application.job_description == 'Salon / Spa / Panti Pijat':
        return 'SERV'
    elif application.job_industry == 'Perbankan' and application.job_description == 'Back-office':
        return 'SERV'
    elif application.job_industry == 'Perbankan' and application.job_description == 'Bank Teller':
        return 'SERV'
    elif application.job_industry == 'Perbankan' and application.job_description == 'CS Bank':
        return 'SERV'
    elif application.job_industry == 'Perbankan' and application.job_description == 'Credit Analyst':
        return 'PROF'
    elif application.job_industry == 'Perbankan' and application.job_description == 'Resepsionis':
        return 'SERV'
    elif application.job_industry == 'Sales / Marketing' and application.job_description == 'Account Executive / Manager':
        return 'SALE'
    elif application.job_industry == 'Sales / Marketing' and application.job_description == 'Salesman':
        return 'SALE'
    elif application.job_industry == 'Sales / Marketing' and application.job_description == 'SPG':
        return 'SALE'
    elif application.job_industry == 'Sales / Marketing' and application.job_description == 'Telemarketing':
        return 'SALE'
    elif application.job_industry == 'Sales / Marketing' and application.job_description == 'Lainnya':
        return 'SALE'
    elif application.job_industry == 'Service' and application.job_description == 'Customer Service':
        return 'SERV'
    elif application.job_industry == 'Service' and application.job_description == 'Kasir':
        return 'SERV'
    elif application.job_industry == 'Service' and application.job_description == 'Kebersihan':
        return 'SERV'
    elif application.job_industry == 'Service' and application.job_description == 'Koki':
        return 'SERV'
    elif application.job_industry == 'Service' and application.job_description == 'Pelayan / Pramuniaga':
        return 'SERV'
    elif application.job_industry == 'Service' and application.job_description == 'Lainnya':
        return 'SERV'
    elif application.job_industry == 'Tehnik / Computer' and application.job_description == 'Engineer / Ahli Tehnik':
        return 'TECH'
    elif application.job_industry == 'Tehnik / Computer' and application.job_description == 'Penulis Teknikal':
        return 'SENI'
    elif application.job_industry == 'Tehnik / Computer' and application.job_description == 'Programmer / Developer':
        return 'TECH'
    elif application.job_industry == 'Tehnik / Computer' and application.job_description == 'R&D / Ilmuwan / Peneliti':
        return 'RISE'
    elif application.job_industry == 'Tehnik / Computer' and application.job_description == 'Warnet':
        return 'WIRA'
    elif application.job_industry == 'Tehnik / Computer' and application.job_description == 'Otomotif':
        return 'TECH'
    elif application.job_industry == 'Transportasi' and application.job_description == 'Supir / Ojek':
        return 'SERV'
    elif application.job_industry == 'Transportasi' and application.job_description == 'Agen Perjalanan':
        return 'SERV'
    elif application.job_industry == 'Transportasi' and application.job_description == 'Kurir / Ekspedisi':
        return 'SERV'
    elif application.job_industry == 'Transportasi' and application.job_description == 'Pelaut / Staff Kapal / Nahkoda Kapal':
        return 'PROF'
    elif application.job_industry == 'Transportasi' and application.job_description == 'Pilot / Staff Penerbangan':
        return 'PROF'
    elif application.job_industry == 'Transportasi' and application.job_description == 'Sewa Kendaraan':
        return 'SERV'
    elif application.job_industry == 'Transportasi' and application.job_description == 'Masinis / Kereta Api':
        return 'PROF'
    elif application.job_industry == 'Staf Rumah Tangga' and application.job_description == 'Babysitter / Perawat':
        return 'SERV'
    elif application.job_industry == 'Staf Rumah Tangga' and application.job_description == 'Pembantu Rumah Tangga':
        return 'SERV'
    elif application.job_industry == 'Staf Rumah Tangga' and application.job_description == 'Supir':
        return 'SERV'
    elif application.job_industry == 'Staf Rumah Tangga' and application.job_description == 'Tukang Kebun':
        return 'SERV'
    else:
        return 'ZZZZZ'


def get_expired_time(app_histrory):
    expired_time = None
    today = timezone.localtime(timezone.now()).date()
    try:
        filter_due_dates_by_weekend((today,))
        filter_due_dates_by_pub_holiday((today,))
        delta = today - timezone.localtime(app_histrory.cdate).date()
        if delta.days == 2:
            expired_time = datetime.combine(today, time(22, 0)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        expired_time = None
    return expired_time


def password_validation_error_messages_translate(message_list):
    error_messages = {
        "This password is too short. It must contain at least 8 characters.":
            "Password terlalu pendek. minimal harus 8 karakter.",
        "This password is too common.": "Password terlalu mudah.",
        "This password is entirely numeric.": "Password tidak boleh semua angka"
    }

    returned_list = [item for item in list([error_messages.get(x) for x in message_list]) if item]
    if "The password is too similar" in message_list:
        returned_list.append("Password dan Username terlalu mirip")
    return returned_list


def autodialer_note_generator(app_status, failed_count, sk_result):
    notes = {
        122: 'PV Employer #%s : %s',
        124: 'PV Applicant #%s : %s',
        138: 'PV Employer #%s : %s',
        140: 'Follow up 140 #%s : %s',
        141: 'Act call #%s : %s',
        160: 'Follow up 160 #%s : %s',
        172: 'Act call #%s : %s'
    }
    return notes[app_status] % (failed_count, sk_result)


def autodialer_next_turn(application_status):
    # delay in hour
    delay = {
        '122': 3,
        '124': 1,
        '138': 3,
        '140': 1,
        '141': 1,
        '160': 1,
        '180': None,
        'fu': 12,
        'colT0': 5,
        '172': 1
    }
    today = timezone.localtime(timezone.now())
    next_turn = None
    if delay[str(application_status)]:
        next_turn = today + timedelta(hours=delay[application_status])
    return next_turn


def convert_to_base64_csv(colnames, query_result):

    # Creating the csv formatted string
    csv_string = io.StringIO()
    csv_string.write(','.join(colnames) + '\n')
    for row in query_result:
        csv_string.write(','.join(map(str, row)) + '\n')
    # Encoding the string to base64
    encoded = base64.b64encode(csv_string.getvalue().encode('utf-8'))
    csv_string.close()
    return encoded.decode()


def get_geolocator():
    geolocator = Nominatim()

    requester = geolocator.urlopen

    def requester_hack(req, **kwargs):
        req = urllib.request.Request(url=req, headers=geolocator.headers)
        return requester(req, **kwargs)

    geolocator.urlopen = requester_hack

    return geolocator


def encrypt_order_id_sepulsa(key_str):
    fernet = Fernet(settings.SEPULSA_FERNET_KEY)
    return fernet.encrypt(key_str.encode()).decode()


def decrypt_order_id_sepulsa(key_str):
    fernet = Fernet(settings.SEPULSA_FERNET_KEY)
    return fernet.decrypt(key_str.encode()).decode()


def fulfil_optional_response_sepulsa(payload):
    optional_fields = [
        'serial_number',
        'token',
        'status',
        'transaction_id',
        'response_code'
    ]
    for field in optional_fields:
        if field not in payload:
            payload[field] = ''

    return payload


def generate_hmac_sha256(secret_key, string):
    signature_hmac_sha256 = hmac.new(
        secret_key.encode(), string.encode(), hashlib.sha256).hexdigest()
    return signature_hmac_sha256


def generate_base64(key_string):
    return base64.b64encode(key_string.encode()).decode()


def generate_hex_sha256(string):
    str_sha256 = str(hashlib.sha256(string.encode()).hexdigest())
    return str_sha256.lower()


def generate_sha1_hex(string):
    return hashlib.sha1(string.encode()).hexdigest()


def clean_special_character(string):
    return ''.join(c for c in string if c.isalnum() or c.isspace())


def splitAt(w, n):
    for i in range(0, len(w), n):
        yield w[i:i + n]


def have_pn_device(device):
    if device and device.gcm_reg_id:
        return True
    return False


def filter_search_field(keyword):
    from django.core.validators import ValidationError, validate_email
    from django.db.models import Max

    from juloserver.account.models import Account
    from juloserver.julo.models import ProductLine

    keyword = keyword.strip()
    if keyword[:1] == '+':
        keyword = keyword[1:]
    if keyword.isdigit():
        account_id_max = Account.objects.aggregate(Max('id'))['id__max']

        if len(keyword) == 2 and int(keyword) in ProductLineCodes.all():
            return 'product_line_id', [int(keyword)]
        elif len(keyword) == 10 and keyword[:1] == '2':
            return 'id', keyword
        elif int(keyword) in range(1, account_id_max + 1):
            return 'account_id', [int(keyword)]
        else:
            mobile_phone_regex = re.compile(r'^(^\+62\s?|^62\s?|^0)(\d{3,4}-?){2}\d{3,4}$')
            if mobile_phone_regex.match(keyword):
                return 'mobile_phone_1', keyword
            else:
                return 'ktp', keyword
    else:
        try:
            validate_email(keyword)
            is_email_valid = True
        except ValidationError:
            is_email_valid = False
        if is_email_valid:
            return 'email', keyword
        else:
            product_line_code_list = ProductLine.objects.filter(
                product_line_type__icontains=keyword
            ).values_list('product_line_code', flat=True)
            if product_line_code_list:
                return 'product_line_id', list(product_line_code_list)
            else:
                return 'fullname', keyword


def remove_current_user():
    """
    this util for remove agent_id from (current_user),
    so bypass and any other experiment status change will not recorded as agent triggered
    """
    from cuser.middleware import CuserMiddleware
    CuserMiddleware.del_user()


def get_float_or_none(number):
    try:
        return float(number)
    except:
        return None


def eval_or_none(eval_str):
    try:
        return eval(eval_str)
    except Exception:
        return None


def generate_agent_password(length=20):
    return ''.join(
        random.choice(
            string.ascii_uppercase + string.ascii_lowercase + string.digits
        ) for _ in range(length))


def parse_reminder_template(reminder_type):
    pass


def experiment_check_criteria(field, criteria, data):
    result = False
    if field in criteria:
        group_test = criteria[field].split(":")
        if group_test[0] == "#nth":
            digit_index = int(group_test[1])
            digit_criteria = group_test[2].split(",")
            digit = str(data)[digit_index] if digit_index < 0 else str(data)[digit_index - 1]
            if digit in digit_criteria:
                result = True
    return result


def generate_product_name(data):
    keys = ['interest_value', 'origination_value', 'late_fee_value',
            'cashback_initial_value', 'cashback_payment_value']

    for key in keys:
        data[key] = ('000' + str(int(data[key] * 100)))[-3:]

    return "I.{}-O.{}-L.{}-C1.{}-C2.{}-M".format(
        data['interest_value'],
        data['origination_value'],
        data['late_fee_value'],
        data['cashback_initial_value'],
        data['cashback_payment_value']
    )


def chunk_array(array, size):
    from itertools import islice
    it = iter(array)
    return list(iter(lambda: list(islice(it, size)), []))


def combine_array_with_ratio(array1, array2, ratio_1, ratio_2):
    """
        this function is for combine 2 array become 1 with ratio ratio_1:ratio_2
        the array can be object or just int or string return 1 array
    """
    array1_with_ratio = chunk_array(array1, ratio_1)
    array2_with_ratio = chunk_array(array2, ratio_2)
    result = []
    while len(array1_with_ratio) > 0 and len(array2_with_ratio) > 0:
        result.append(array1_with_ratio.pop(0))
        result.append(array2_with_ratio.pop(0))
    result = result + array1_with_ratio + array2_with_ratio
    return sum(result, [])


def trim_name(name):
    name = re.sub("[-, ,    ,',`,/,\,*]", '', name)
    name = re.sub('["]', '', name)
    normalized = unicodedata.normalize("NFKD", name)
    name = normalized.encode('ASCII', 'ignore').decode()
    return str(name).lower()


def generate_ics_link(calendar):
    calendar_description = urllib.parse.quote_plus(
        calendar.contents['vevent'][0].contents['description'][0].value)
    summary = urllib.parse.quote_plus(calendar.contents['vevent'][0].contents['summary'][0].value)
    rrule = calendar.contents['vevent'][0].contents['rrule'][0].value
    start_date = str(calendar.contents['vevent'][0].contents['dtstart'][0].value).replace(
        "-", "").replace(":", "").replace(" ", "T")
    end_date = str(calendar.contents['vevent'][0].contents['dtend'][0].value).replace(
        "-", "").replace(":", "").replace(" ", "T")
    date_formated = start_date + "/" + end_date
    link_url = "https://calendar.google.com/calendar/r/eventedit?dates={}&recur=RRULE:{}&text={}&location=&details={}".format(
        date_formated, rrule, summary, calendar_description)
    return link_url


def get_data_from_ana_server(url):
    headers = {'Authorization': 'Token %s' % settings.ANASERVER_TOKEN}
    url = settings.ANASERVER_BASE_URL + url
    log_data = {
        'action': "get data from anaserver",
        'url': url,
    }
    logger.info(log_data)

    response = requests.get(url, headers=headers)
    return response


def execute_after_transaction_safely(func):
    if not callable(func):
        raise Exception('Param must be callable!')

    in_atomic_block = transaction.get_connection().in_atomic_block
    if in_atomic_block:
        transaction.on_commit(func)
    else:
        func()


def get_customer_age(customer_dob):
    today = timezone.localtime(timezone.now())
    customer_age = 0
    if customer_dob:
        customer_age = today.year - customer_dob.year
        if today.month == customer_dob.month:
            if today.day < customer_dob.day:
                customer_age -= 1
        elif today.month < customer_dob.month:
            customer_age -= 1
    return customer_age


def get_work_duration_in_month(job_start):
    today = timezone.localtime(timezone.now())
    if not job_start:
        return 0
    return (today.year - job_start.year) * 12 + today.month - job_start.month


def generate_zip_on_memory(files):
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(f[0], f[1])

    return mem_zip.getvalue()


def get_marital_status_in_english(marital_status):
    if marital_status == "Menikah":
        return "Married"
    if marital_status == "Cerai":
        return "Divorced"
    if marital_status == "Janda / duda":
        return "Widow"
    return "Single"


def get_gender_in_english(gender):
    if gender == 'Pria':
        return "Male"
    return "Female"


def get_last_education_in_english(last_education):
    if last_education == 'SLTP':
        return "Middle School"
    if last_education == 'SLTA':
        return "High School"
    if last_education == 'Diploma':
        return "Associate Degree"
    if last_education == 'S1':
        return "Bachelor Degree"
    if last_education == 'S2':
        return "Master Degree"
    if last_education == 'S3':
        return "Doctor"
    return "Elementary School"


def get_monthly_income_band(income):
    if income >= 10000000:
        return '>10M'
    number, rest = divmod(income, 1000000)
    if rest > 500000:
        return "%s.5-%sM" % (number, float(number + 1))
    return "%s.0-%s.5M" % (number, number)


#### Template Dictionary for reminders ####
template_reminders = {
    'MTL': 'voice_reminder_{}_MTL',
    'STL': 'voice_reminder_{}_STL',
    'J1': 'voice_reminder_{}_J1',
    'GRAB': 'voice_reminder_{}_GRAB',
    'T-5_STL': 'voice_reminder_T-5_STL',
    'T-5_MTL': 'voice_reminder_T-5_MTL',
    'T-3_STL': 'voice_reminder_T-3_STL',
    'T-3_MTL': 'voice_reminder_T-3_MTL',
    'SMS-OTP': 'sms_otp_token.txt'
}
#### End Template reminders Dictionary ####

def run_commit_hooks(self):
    """
        Used for unit testing commit hooks
        Fake transaction commit to run delayed on_commit functions
        :return:
    """
    for db_name in reversed(self._databases_names()):
        with mock.patch('django.db.backends.base.base.BaseDatabaseWrapper.validate_no_atomic_block', lambda a: False):
            transaction.get_connection(using=db_name).run_and_clear_commit_hooks()


class DictItemsEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, File):
            return str(obj)
        return json.JSONEncoder.default(self, obj)


def add_plus_62_mobile_phone(phone_number):
    if phone_number and phone_number.startswith('08'):
        return phone_number.replace('08', '628', 1)
    elif phone_number and phone_number.startswith('+628'):
        return phone_number.replace('+628', '628', 1)
    else:
        return phone_number


def is_forbidden_symbol(data, quote=False, additional_symbol=False):
    """
    If quote is True to include ' or " to convert.
    Default is False
    this function specific created for prevent XSS Payload
    """

    symbols = (
        '<',
        '>',
        '=',
        ';',
        ':',
        '{',
        '}',
        '%',
    )

    if not data:
        return True

    if isinstance(data, str):
        if quote:
            symbols = symbols + ('"', '\'')

        if additional_symbol:
            symbols = symbols + ('(', ')', '&')

        if not re.fullmatch('^[ -~]+$', data):
            return False

        for symbol in symbols:
            if symbol in data:
                return False

    return True


class RedisCacheValue:
    def __init__(self, cache_key, feature_setting_name=None):
        self.redis_client = get_redis_client()
        self.feature_setting_name = feature_setting_name
        self.feature_setting = None
        self.cache_key = cache_key

    def get_if_exists(self):
        from juloserver.julo.models import FeatureSetting
        """
        Get cache value from Redis
        (have support for checking feature setting is active when have feature_setting_name)
        :return: None if not exists, otherwise return cache value
        """
        if self.feature_setting_name:
            self.feature_setting = FeatureSetting.objects.filter(
                feature_name=self.feature_setting_name,
                is_active=True,
            ).last()
            if not self.feature_setting:
                return None

        return self.redis_client.get(self.cache_key)

    def cache(
        self, value, expire_time=None,
        is_expire_time_get_from_fs=False, parameter_key_to_get_days=None
    ):
        """
        Cache value to Redis
        (have support for checking feature setting is active when have feature_setting_name)
        :param value: value need to cache
        :param expire_time: self config expire time
        :param is_expire_time_get_from_fs: get expire time from parameters of feature setting
        :param parameter_key_to_get_days: days=feature_setting.parameters[parameter_key_to_get_days]
        We can add more parameter here to get seconds or weeks or .... if needed
        :return:
        """
        if expire_time and is_expire_time_get_from_fs:
            raise Exception('Cannot set expire_time if is_expire_time_get_from_fs is True')

        if not self.feature_setting_name or self.feature_setting:
            if not expire_time:
                parameters = self.feature_setting.parameters
                expire_time = timedelta(
                    days=parameters[parameter_key_to_get_days] if parameter_key_to_get_days else 0
                )

            self.redis_client.set(
                key=self.cache_key,
                value=value,
                expire_time=expire_time,
            )


class ImageUtil:

    class ImageType:
        PNG = 'PNG'
        JPEG = 'JPEG'

    class ResizeResponseType:
        PIL_IMAGE = 'pil_image'
        BYTES = 'bytes'

    def __init__(self, image_file):
        self.image_file = image_file

    def resize_image(
            self, target_filesize, tolerance=0, file_type_response=ResizeResponseType.PIL_IMAGE,
            max_exec_time=5, image_format=ImageType.PNG
    ):
        """
            Resize the uploaded file to expect filesize in byte
            @param target_filesize: the number of bytes for the new target filesize
            @type target_filesize: integer
            @param tolerance: the percent of what the file may be bigger than target_filesize
            @type tolerance: integer
            @param file_type_response: the data format of result
            @type file_type_response: An :py:class:`~PIL.Image.Image` object or bytes
            @param max_exec_time: the maximum execution time to resize the image in second
            @type max_exec_time: integer
            @param image_format: image format type
            @type image_format: An :py:class:`~ImageUtil.ImageType`
            @return: file in bytes or :py:class:`~PIL.Image.Image`
            @rtype:

        """
        start_time = time1.time()
        elapsed = 0
        img = original_img = Image.open(self.image_file).convert('RGB')
        aspect = img.size[0] / img.size[1]
        filesize = 0

        while True:
            if elapsed > max_exec_time:
                error_msg = (
                    'resize_image_reached_limit_of_execution_time|elapsed={}, max_exec_time={}, '
                    'filesize={}, tolerance={}, target_filesize{}'
                ).format(elapsed, max_exec_time, filesize, tolerance, target_filesize)
                logger.error(error_msg)
                raise JuloException(error_msg)

            with io.BytesIO() as buffer:
                img.save(buffer, format=image_format)
                data = buffer.getvalue()
            filesize = len(data)
            if not filesize:
                error_msg = (
                    'resize_image_filesize_error|elapsed={}, max_exec_time={}, tolerance={}, '
                    'target_filesize{}'
                ).format(elapsed, max_exec_time, filesize, tolerance, target_filesize)
                logger.error(error_msg)
                raise JuloException(error_msg)
            size_deviation = filesize / target_filesize

            if size_deviation <= (100 + tolerance) / 100:
                msg = (
                    'debug_resize_image|elapsed={}|file_size={}'
                ).format(time1.time()-start_time, filesize)
                logger.info(msg)
                return img if file_type_response == self.ResizeResponseType.PIL_IMAGE else data
            else:
                # filesize isn't fit, adjust size(width, height)
                # use sqrt of deviation since applied both in width and height
                new_width = img.size[0] / size_deviation**0.5
                new_height = new_width / aspect
                # resize with the original image to keep the high quality
                img = original_img.resize((int(new_width), int(new_height)))
            elapsed = time1.time() - start_time


def convert_number_to_rupiah_terbilang(number):
    thousands = ["", "Ribu", "Juta", "Miliar", "Triliun"]

    if number == 0:
        return "Nol"

    is_negative = number < 0
    number = abs(number)

    word_representation = ""
    index = 0

    while number > 0:
        three_digit_number = number % 1000

        if three_digit_number != 0:
            number_word = convert_three_digit_number_to_word(three_digit_number)
            word_representation = number_word + " " + thousands[index] + " " + word_representation

        number //= 1000
        index += 1

    if is_negative:
        word_representation = "Minus " + word_representation

    return word_representation.strip()


def convert_three_digit_number_to_word(number):
    ones = ["", "Satu", "Dua", "Tiga", "Empat", "Lima", "Enam", "Tujuh", "Delapan", "Sembilan"]
    teens = ["Sepuluh", "Sebelas", "Dua Belas", "Tiga Belas", "Empat Belas",
             "Lima Belas", "Enam Belas", "Tujuh Belas", "Delapan Belas", "Sembilan Belas"]
    tens = ["", "", "Dua Puluh", "Tiga Puluh", "Empat Puluh", "Lima Puluh",
            "Enam Puluh", "Tujuh Puluh", "Delapan Puluh", "Sembilan Puluh"]
    word = ""
    hundred_digit = number // 100
    remainder = number % 100

    if hundred_digit != 0:
        if hundred_digit == 1:
            word += "Seratus "
        else:
            word += ones[hundred_digit] + " Ratus "

    if remainder < 10:
        word += ones[remainder]
    elif remainder >= 10 and remainder < 20:
        word += teens[remainder % 10]
    else:
        ten_digit = remainder // 10
        one_digit = remainder % 10
        word += tens[ten_digit] + " " + ones[one_digit]

    return word.strip()


def generate_sha256_rsa(private_key, string_to_sign):
    digest = SHA256.new(bytes(string_to_sign, 'utf-8'))
    private_key = RSA.importKey(private_key)
    signature = PKCS1_v1_5.new(private_key).sign(digest)
    signature = base64.b64encode(signature).decode()
    return signature


def wrap_sha512_with_base64(secret_key, message):
    hmac_hash = hmac.new(
        secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha512).digest()
    return base64.b64encode(hmac_hash).decode('utf-8')


def generate_sha512_data(secret_key, data):
    hmac_sha512 = hmac.new(bytes(secret_key, 'utf-8'), bytes(data, 'utf-8'), hashlib.sha512)
    return hmac_sha512.hexdigest()


def seconds_until_end_of_day() -> int:
    now = datetime.now()
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)

    time_difference = end_of_day - now
    seconds_left = time_difference.total_seconds()

    return int(seconds_left)


def generate_sha512_data(secret_key, data):
    hmac_sha512 = hmac.new(bytes(secret_key, 'utf-8'), bytes(data, 'utf-8'), hashlib.sha512)
    return hmac_sha512.hexdigest()


def replace_day(original_date: date, new_day: int) -> date:
    """
    # if the new day is greater than the last day in the new month, adjust it to avoid overflow
    # e.g. original_date=15th of Feb & new_day=31 -> 31st of February -> incorrect
    # because Feb only has 28 days or 29 days during leap years => 28th of February -> correct
    """
    _, last_day_in_month = calendar.monthrange(original_date.year, original_date.month)
    return original_date.replace(day=min(new_day, last_day_in_month))


def is_phone_number_valid(phone_number):
    try:
        # Check if the phone number contains only digits and symbols '+'
        if not all(char.isdigit() or char == '+' for char in phone_number):
            return False
        if len(phone_number) < 10:
            return False

        # Prefixes included in the card https://juloprojects.atlassian.net/browse/PLAT-2173
        valid_prefixes = [
            "852",
            "853",
            "811",
            "812",
            "813",
            "821",
            "822",
            "823",
            "851",
            "855",
            "856",
            "857",
            "858",
            "814",
            "815",
            "816",
            "817",
            "818",
            "819",
            "859",
            "877",
            "878",
            "832",
            "833",
            "838",
            "895",
            "896",
            "897",
            "898",
            "899",
            "881",
            "882",
            "883",
            "884",
            "885",
            "886",
            "887",
            "888",
            "889",
            "828",
            "831",
        ]

        # Parse the phone number
        parsed_number = phonenumbers.parse(phone_number, "ID")
        national_number_str = str(parsed_number.national_number)
        if national_number_str[:3] not in valid_prefixes:
            return False

        if phonenumbers.is_valid_number(parsed_number):
            return True
        else:
            return False
    except phonenumbers.phonenumberutil.NumberParseException:
        return False


def convert_size_unit(bytes: int, to_unit: str, b_size=1024) -> str:
    """
    Convert B to KB, MB, GB, TB
    """
    exponential = {"KB": 1, "MB": 2, "GB": 3, "TB": 4}
    if to_unit not in exponential:
        raise ValueError("Invalid converted unit")
    return f"{round(bytes / (b_size ** exponential[to_unit]), 1)} {to_unit}"


def display_percent_from_float_type(number: float):
    return "{}%".format(py2round(number * 100, 3))


def convert_payment_number_to_word(payment_number: int):
    if payment_number == 1:
        return "Cicilan Pertama"
    return "Cicilan Ke" + convert_three_digit_number_to_word(payment_number).lower()


def masking_phone_number_value(phone_number: str) -> str:
    '''
    sample of expected result '+62*******1234'
    '''
    if not phone_number or (isinstance(phone_number, str) and len(phone_number) < 10):
        return None
    length_value = len(phone_number)
    length_value_masking = length_value - 7
    value_masked = '*' * length_value_masking
    return phone_number[:4] + value_masked + phone_number[-4:]


def cacheops_bulk_update(objs: List, *args, **kwargs):
    """
    Bulk update list of objects & invalidate their cacheops
    """

    bulk_update(objs, *args, **kwargs)
    for obj in objs:
        invalidate_obj(obj)


def ratio_of_similarity(value_target, value_check):

    if not value_target or not value_check:
        return 0

    return SequenceMatcher(None, value_target, value_check).ratio()


def get_age_from_timestamp(timestamp):
    current_date = datetime.now()

    delta_years = current_date.year - timestamp.year
    delta_months = current_date.month - timestamp.month
    delta_days = current_date.day - timestamp.day

    # Adjust for negative month/day differences
    if delta_days < 0:
        delta_months -= 1
        previous_month = current_date.replace(day=1) - timedelta(days=1)
        delta_days += previous_month.day

    if delta_months < 0:
        delta_years -= 1
        delta_months += 12

    return delta_years, delta_months, delta_days


def validation_of_roman_numerals(str):
    word = str.split()
    import re
    # Importing regular expression
    concat_str = ''
    for words in word:
        word_upper = words.upper()
        if bool(re.search(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$",
                          word_upper)):
            concat_str = concat_str + " " + word_upper
        else:
            concat_str = concat_str + " " + words

    return concat_str.strip()


def remove_double_space(value):
    return re.sub(' +', ' ', value)


def clean_string_from_special_chars(text, is_remove_unicode=True, is_specific_symbols=True):

    if not text:
        return text

    original_text = text
    try:
        if is_remove_unicode:
            text = re.sub(r'[\u0370-\u03FF]', '', text)

        if is_specific_symbols:
            text = re.sub(r"[!@#$%^&'’`~?{};*]", "", text)

        clean_text = re.sub(r"\n", " ", text)
        if '\\n' in clean_text:
            clean_text = re.sub(r"\\n", " ", clean_text)

        return clean_text
    except Exception as error:
        logger.error(
            {
                'message': 'Error: {}'.format(str(error)),
                'original_text': original_text,
                'function_name': 'clean_string_from_special_chars',
            }
        )
        return original_text
