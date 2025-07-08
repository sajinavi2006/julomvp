import io
import os
import jwt
import logging
import re

from datetime import datetime
from typing import Dict, Union, Optional

from django.core.files import File
from hashids import Hashids

from django.conf import settings
from django.contrib.auth.models import User
from django_bulk_update.helper import bulk_update

from rest_framework.response import Response
from rest_framework import status

from juloserver.dana.constants import DanaHashidsConstant
from juloserver.julo.models import Partner
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.utils import upload_file_to_oss
from juloserver.merchant_financing.web_app.constants import (
    ALGORITHM_JWT_TYPE,
    ACCESS_TOKEN_LIFETIME,
    REFRESH_TOKEN_LIFETIME,
    PARTNERSHIP_PREFIX_IDENTIFIER,
    PARTNERSHIP_SUFFIX_EMAIL,
    MFStdDocumentTypes,
    MFStdImageTypes,
)
from juloserver.partnership.constants import PartnershipTokenType, PartnershipImageProductType
from juloserver.partnership.models import (
    PartnershipJSONWebToken,
    PartnershipDocument,
    PartnershipImage,
    PartnershipCustomerData,
    PartnershipImageStatus,
    PartnershipApplicationData,
)
from juloserver.partnership.utils import generate_pii_filter_query_partnership

logger = logging.getLogger(__name__)


def response_template_success(
    status=status.HTTP_200_OK, data: Optional[dict] = None, meta: Optional[dict] = None
):
    response_dict = dict()
    if data:
        response_dict['data'] = data

    if meta:
        response_dict['meta'] = meta

    return Response(status=status, data=response_dict)


def response_template_error(
    status=status.HTTP_400_BAD_REQUEST,
    message: Optional[str] = None,
    meta: Optional[dict] = None,
    errors: Optional[dict] = None,
    data: Optional[dict] = None,
):
    response_dict = dict()
    if message:
        response_dict['message'] = message

    if meta:
        response_dict['meta'] = meta

    if errors:
        response_dict['errors'] = errors

    if data:
        response_dict['data'] = data

    return Response(status=status, data=response_dict)


def success_response_web_app(data: dict = {}, meta: dict = {}):
    return response_template_success(data=data, meta=meta)


def response_template_accepted(
    status=status.HTTP_202_ACCEPTED,
    message: Optional[str] = None,
):
    response_dict = dict()
    if message:
        response_dict['message'] = message

    return Response(status=status, data=response_dict)


def accepted_response_web_app(status=status.HTTP_202_ACCEPTED, message=None):
    return response_template_accepted(status=status, message=message)


def no_content_response_web_app(status=status.HTTP_204_NO_CONTENT, data=None, meta={}):
    return Response(status=status)


def created_response_web_app(status=status.HTTP_201_CREATED, data=None, meta={}):
    response_dict = {'data': data, 'meta': meta}
    return Response(status=status, data=response_dict)


def error_response_web_app(
    status=status.HTTP_400_BAD_REQUEST, message: str = '', errors: list = [], meta: Dict = {}
):
    result = {}
    for field in errors:
        result[field] = errors[field][0]
    return response_template_error(status=status, message=message, errors=result, meta=meta)


def error_response_validation(
    status=status.HTTP_400_BAD_REQUEST, message: str = '', errors: list = [], meta: Dict = {}
):
    result = {}
    for field in errors:
        result[field] = errors[field][0]
        status = errors.as_data()[field][0].code or status

    return response_template_error(status=status, message=message, errors=result, meta=meta)


def create_or_update_token(
    user: User,
    partner_name: str, token_type: str,
    token: str = None
) -> PartnershipJSONWebToken:

    hashids = Hashids(min_length=DanaHashidsConstant.MIN_LENGTH, salt=settings.DANA_SALT)
    expired_token_time = None
    if token_type == PartnershipTokenType.ACCESS_TOKEN:
        expired_token_time = ACCESS_TOKEN_LIFETIME
    else:
        expired_token_time = REFRESH_TOKEN_LIFETIME

    payload = {
        'user_id': hashids.encode(user.id),
        'partner': partner_name,
        'exp': datetime.utcnow() + expired_token_time,
        'iat': datetime.utcnow()
    }

    user_token = PartnershipJSONWebToken.objects.filter(
        user=user,
        partner_name=partner_name,
        token_type=token_type
    )

    if token:
        user_token = user_token.filter(token=token).last()
    else:
        user_token = user_token.last()

    new_token = encode_jwt_token(payload)

    if not user_token:
        user_token = PartnershipJSONWebToken.objects.create(
            user=user,
            expired_at=datetime.fromtimestamp(payload['exp']),
            name=user.first_name,
            partner_name=partner_name,
            token_type=token_type,
            token=new_token,
            is_active=True,
        )
    else:
        # if key is not expired still using same token
        is_token_expired = decode_jwt_token(user_token.token)
        is_token_active = verify_token_is_active(user_token.token, token_type)
        if is_token_expired and is_token_active:
            return user_token

        user_token.token = new_token
        user_token.is_active = True
        user_token.expired_at = datetime.fromtimestamp(payload['exp'])
        user_token.save(update_fields=['token', 'expired_at', 'is_active'])
        user_token.refresh_from_db()

    return user_token


def generate_access_token(refresh_token: str, partner_name: str) -> Union[bool, str]:

    hashids = Hashids(min_length=DanaHashidsConstant.MIN_LENGTH, salt=settings.DANA_SALT)
    is_token_expired = decode_jwt_token(refresh_token)

    if not is_token_expired:
        return False

    is_token_active = verify_token_is_active(refresh_token, PartnershipTokenType.REFRESH_TOKEN)

    if not is_token_active:
        return False

    user_tokens = PartnershipJSONWebToken.objects.filter(
        user=hashids.decode(is_token_expired['user_id']),
        partner_name=partner_name,
        token_type=PartnershipTokenType.ACCESS_TOKEN,
    ).last()

    payload = {
        'user_id': hashids.encode(user_tokens.user.id),
        'partner': partner_name,
        'exp': datetime.utcnow() + ACCESS_TOKEN_LIFETIME,
        'iat': datetime.utcnow()
    }

    new_token = encode_jwt_token(payload)

    # if access token is not expired still using same token
    is_access_token_expired = decode_jwt_token(user_tokens.token)
    is_access_token_active = verify_token_is_active(
        user_tokens.token,
        PartnershipTokenType.ACCESS_TOKEN
    )
    if is_access_token_expired and is_access_token_active:
        return user_tokens.token

    user_tokens.token = new_token
    user_tokens.is_active = True
    user_tokens.expired_at = datetime.fromtimestamp(payload['exp'])
    user_tokens.save(update_fields=['token', 'expired_at', 'is_active'])
    user_tokens.refresh_from_db()
    return new_token


def encode_jwt_token(payload: Dict) -> str:
    encode_jwt = jwt.encode(
        payload, settings.WEB_FORM_JWT_SECRET_KEY,
        ALGORITHM_JWT_TYPE
    ).decode('utf-8')

    return encode_jwt


def decode_jwt_token(token: str) -> Union[bool, Dict]:
    try:
        decode_jwt = jwt.decode(token, settings.WEB_FORM_JWT_SECRET_KEY, ALGORITHM_JWT_TYPE)
    except Exception:
        logger.info({
            'token_title': 'partnership_token_expired_invalid',
            'token': token
        })
        return False

    return decode_jwt


def verify_token_is_active(token: str, token_type: str) -> bool:

    is_active = PartnershipJSONWebToken.objects.filter(
        token=token, is_active=True, token_type=token_type
    ).exists()
    return is_active


def inactivate_token(token: str, partner_name: str) -> bool:

    is_expired_token = decode_jwt_token(token)
    hashids = Hashids(min_length=DanaHashidsConstant.MIN_LENGTH, salt=settings.DANA_SALT)

    if not is_expired_token:
        return False
    user_tokens = PartnershipJSONWebToken.objects.filter(
        user=hashids.decode(is_expired_token['user_id']),
        partner_name=partner_name,
        is_active=True
    )

    if not user_tokens:
        return False

    list_token_list = []

    for user_token in user_tokens.iterator():

        user_token.is_active = False
        list_token_list.append(user_token)

    bulk_update(list_token_list, update_fields=['is_active'])

    return True


def check_partner_name(partner: str) -> bool:
    pii_partner_filter_dict = generate_pii_filter_query_partnership(Partner, {'name': partner})

    is_partner = Partner.objects.filter(is_active=True, **pii_partner_filter_dict).exists()

    return is_partner


def verify_access_token(authorization: str) -> Union[bool, str]:

    if not authorization:
        return False

    bearer_token = authorization.split(' ')
    if len(bearer_token) == 2 and bearer_token[0].lower() == 'bearer':
        return bearer_token[1]

    return False


def is_valid_password(password: str) -> bool:
    """Define password policy criteria"""
    required_length = 6

    # Check password length
    if len(password) < required_length:
        return False

    # Check character alphabet
    alpha_count = sum(1 for char in password if char.isalpha())

    if alpha_count <= 0:
        return False

    # Check if the password contains a number and special character
    return re.search(r'\d|[!@#$%^&*(),.?":{}|<>]', password)


def create_partnership_nik(application_id: int) -> str:
    """
    eg: 8889002000016081
    """
    prefix = PARTNERSHIP_PREFIX_IDENTIFIER
    product_code = ProductLineCodes.AXIATA_WEB

    return '{}{}{}'.format(prefix, product_code, application_id)


def create_partnership_email(username: str, partner_name: str) -> str:
    """
    eg: 1050241708900097_partner@julopartner.com
    """
    return '{}_{}{}'.format(username, partner_name, PARTNERSHIP_SUFFIX_EMAIL)


def create_temporary_partnership_user_nik(nik: str) -> str:
    """
    eg: 8889003106026502202123
    """
    prefix = PARTNERSHIP_PREFIX_IDENTIFIER
    product_code = ProductLineCodes.AXIATA_WEB

    return '{}{}{}'.format(prefix, product_code, nik)


def check_partner_from_token(token: str) -> Union[bool, str]:
    is_valid_token = decode_jwt_token(token)

    if not is_valid_token:
        return False

    partner = check_partner_name(is_valid_token['partner'])

    if not partner:
        return False

    return is_valid_token['partner']


def get_user_from_token(token: str) -> Union[bool, User]:
    hashids = Hashids(min_length=DanaHashidsConstant.MIN_LENGTH, salt=settings.DANA_SALT)
    is_valid_token = decode_jwt_token(token)

    if not is_valid_token:
        return False

    user_id = hashids.decode(is_valid_token['user_id'])
    user = User.objects.filter(
        pk=user_id[0],
    ).last()

    if not user:
        return False

    return user


def masking_axiata_web_app_phone_number(origin_phone_number: str) -> str:
    """
    Formula for masking -> product_line + origin_phone_number
    eg:
    305082289129312
    """
    product_code = ProductLineCodes.AXIATA_WEB
    return '{}{}'.format(product_code, origin_phone_number)


def get_partnership_imgs_and_docs(partner_loan_requests: list) -> dict:
    imgs_docs_dict = {}
    loan_ids = set()

    for plr in partner_loan_requests:
        loan_ids.add(plr.loan.id)

    partnership_documents = PartnershipDocument.objects.filter(
        document_source__in=loan_ids, document_status=PartnershipDocument.CURRENT
    )

    partnership_images = PartnershipImage.objects.filter(
        loan_image_source__in=loan_ids, image_status=PartnershipImageStatus.ACTIVE
    )

    for plr in partner_loan_requests:
        imgs_docs_dict[plr.loan.id] = {
            MFStdDocumentTypes.INVOICE: {
                "file_id": "",
                "file_name": "",
                "file_type": "",
                "file_url": "",
            },
            MFStdDocumentTypes.BILYET: {
                "file_id": "",
                "file_name": "",
                "file_type": "",
                "file_url": "",
            },
            MFStdDocumentTypes.SKRTP: {
                "file_id": "",
                "file_name": "",
                "file_type": "",
                "file_url": "",
            },
            MFStdImageTypes.MERCHANT_PHOTO: {
                "file_id": "",
                "file_name": "",
                "file_type": "",
                "file_url": "",
            },
        }

    for pd in partnership_documents:
        imgs_docs_dict[pd.document_source][pd.document_type] = {
            "file_id": pd.id or "",
            "file_name": pd.filename or "",
            "file_type": pd.document_type or "",
            "file_url": pd.document_url_api or "",
        }

    for pi in partnership_images:
        imgs_docs_dict[pi.loan_image_source][pi.image_type] = {
            "file_id": pi.id or "",
            "file_name": pi.thumbnail_url or "",
            "file_type": pi.image_type or "",
            "file_url": pi.image_url or "",
        }

    return imgs_docs_dict


def get_application_dictionaries(partner_loan_requests: list) -> dict:
    application_ids = set()
    application_dicts = {}

    for plr in partner_loan_requests:
        application_ids.add(plr.loan.application_id2)

    partnership_customer_data = PartnershipCustomerData.objects.select_related("customer").filter(
        application_id__in=application_ids
    )

    partnership_application_data = PartnershipApplicationData.objects.select_related(
        "partnership_customer_data"
    ).filter(application_id__in=application_ids)

    for plr in partner_loan_requests:
        application_dicts[plr.loan.application_id2] = {
            "partnership_customer_data": {"borrower_name": "", "nik": "", "phone_number": ""},
            "partnership_application_data": {"business_type": ""},
        }

    for pcd in partnership_customer_data:
        application_dicts[pcd.application_id]["partnership_customer_data"] = {
            "borrower_name": pcd.customer.fullname,
            "nik": pcd.nik,
            "phone_number": pcd.phone_number,
        }

    for pad in partnership_application_data:
        application_dicts[pad.application_id]["partnership_application_data"] = {
            "business_type": pad.business_type
        }

    return application_dicts


def mf_standard_verify_nik(nik: str) -> Union[str, None]:
    err_invalid_format = 'NIK format is incorrect or invalid'
    if len(nik) != 16:
        return 'NIK must be 16 digits'
    if not nik.isdigit():
        return 'NIK must use numbers'
    birth_day = int(nik[6:8])
    if not (1 <= int(nik[0:2])) or not (1 <= int(nik[2:4])) or not (1 <= int(nik[4:6])):
        return err_invalid_format
    if not (1 <= birth_day <= 31 or 41 <= birth_day <= 71):
        return err_invalid_format
    if not (1 <= int(nik[8:10]) <= 12):
        return err_invalid_format
    if not (1 <= int(nik[12:])):
        return err_invalid_format
    return None


def mf_standard_generate_onboarding_document(
    file_path,
    file_type: str,
    application_id: int,
    customer_id: int,
    created_by_user_id: int,
    is_image=True,
):
    filename = os.path.basename(file_path)
    file_object = io.FileIO(file_path, 'rb')
    filename = "mf-std-{}-{}{}".format(file_type, application_id, os.path.splitext(filename)[1])
    url = "mf_cust_{}/application_{}/{}".format(customer_id, application_id, filename)
    if is_image:
        document = PartnershipImage(
            application_image_source=application_id,
            image_type=file_type,
            thumbnail_url=filename,
            image_status=PartnershipImageStatus.ACTIVE,
            product_type=PartnershipImageProductType.MF_API,
            image=File(file_object),
            url=url,
            user_id=created_by_user_id,
        )
        document.save()
        upload_file_to_oss(
            settings.OSS_MEDIA_BUCKET,
            document.image.path,
            document.url,
        )
        # Check if file opened
        if not document.image.closed:
            document.image.close()
        # Delete local file
        if os.path.isfile(document.image.path):
            document.image.delete()
    else:
        document = PartnershipDocument(
            file=File(file_object),
            document_source=application_id,
            document_type=file_type,
            filename=filename,
            document_status=PartnershipDocument.CURRENT,
            url=url,
            user_id=created_by_user_id,
        )
        document.save()
        upload_file_to_oss(settings.OSS_MEDIA_BUCKET, document.file.path, document.url)
        # Check if file opened
        if not document.file.closed:
            document.file.close()
        # Delete local file
        if os.path.isfile(document.file.path):
            document.file.delete()

    return document
