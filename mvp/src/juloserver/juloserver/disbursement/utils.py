import re

from fuzzywuzzy import fuzz

from django.conf import settings

from juloserver.julo.services2.encryption import AESCipher
from juloserver.disbursement.constants import (NameBankValidationConst, DisbursementVendors,
                                               DisbursementStatus)
from juloserver.julo.models import FeatureSetting, Loan
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.disbursement.models import Disbursement
from juloserver.julo.statuses import LoanStatusCodes
from django.utils import timezone

import requests
import uuid

XFERS_TIMEOUT = 40


def bank_name_similarity_check(fullname, validated_name):
    distance = fuzz.ratio(fullname, validated_name)
    if distance >= NameBankValidationConst.NAME_SIMILARITY_THRESHOLD:
        return True
    else:
        return False


def get_session_request_xfers():
    return requests.sessions.Session(timeout=XFERS_TIMEOUT)


def generate_unique_id():
    """
    Convert a UUID to a 32-character hexadecimal string
    e.g; "1d80cbafed3444dfad400241d23902ae"
    """
    return uuid.uuid4().hex


def encrypt_request_payload(payload: str):
    """
    encrypt the request payload using AESCipher
    :param payload: payload string, must be converted to a plain text.
    :returns: the result of the encrypted text.
    """
    aes = AESCipher(settings.PAYMENT_GATEWAY_VENDOR_SALT)
    encrypted_payload = aes.encrypt(payload)
    return encrypted_payload


def decrypt_request_payload(encrypted_payload: str):
    """
    encrypt the request payload using AESCipher
    :param encrypted_payload: encrypted payload.
    :returns: the result of the decrypted payload.
    """
    aes = AESCipher(settings.PAYMENT_GATEWAY_VENDOR_SALT)
    decrypted_payload = aes.decrypt(encrypted_payload)
    return decrypted_payload


def payment_gateway_matchmaking():
    """
    to determine which payment gateway method will be used
    it will calculate all total loan that has been disbursed for each payment gateway method
    and read from payment gateway ratio feature setting
    Whichever payment gateway disbursed has lower ratio than the ideal ratio,
    disbursement method will be assigned to that payment gateway
    """
    default_payment_gateway = DisbursementVendors.AYOCONNECT
    pg_ratio_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GRAB_PAYMENT_GATEWAY_RATIO,
        is_active=True
    ).first()

    if not pg_ratio_feature_setting:
        return default_payment_gateway

    if not pg_ratio_feature_setting.parameters:
        return default_payment_gateway

    # convert the str to a float
    doku_ratio_str = pg_ratio_feature_setting.parameters.get("doku_ratio", '0%')
    ayoconnect_ratio_str = pg_ratio_feature_setting.parameters.get("ac_ratio", '0%')
    doku_ratio_float = float(doku_ratio_str.strip('%')) / 100
    ayoconnect_ratio_float = float(ayoconnect_ratio_str.strip('%')) / 100

    # if ratio is 100% for pg service
    if doku_ratio_float == 1:
        return DisbursementVendors.PG

    # if ratio is 100% for ayoconnect
    if ayoconnect_ratio_float == 1:
        return default_payment_gateway

    # get disbursed grab loans ids
    disbursed_grab_loan_ids = Loan.objects.filter(
        account__account_lookup__workflow__name=WorkflowConst.GRAB,
        loan_status=LoanStatusCodes.CURRENT
    ).values_list('disbursement_id', flat=True)

    # get total today loan amount disbursed
    today = timezone.localtime(timezone.now())
    today_pg_and_ayoconnect_disbursments_qs = Disbursement.objects.filter(
        id__in=disbursed_grab_loan_ids,
        method__in=[DisbursementVendors.AYOCONNECT, DisbursementVendors.PG],
        cdate__date=today,
        disburse_status=DisbursementStatus.COMPLETED
    )
    today_disbursed_loan_count = today_pg_and_ayoconnect_disbursments_qs.count()
    if today_disbursed_loan_count is None:
        today_disbursed_loan_count = 0

    if today_disbursed_loan_count == 0:
        return default_payment_gateway

    # get pg service and ayoconnect total loan disbursed
    pg_disbursed_loan_count = today_pg_and_ayoconnect_disbursments_qs.filter(
        method=DisbursementVendors.PG
    ).count()
    ayoconnect_disbursed_loan_count = today_pg_and_ayoconnect_disbursments_qs.filter(
        method=DisbursementVendors.AYOCONNECT).count()

    if ayoconnect_disbursed_loan_count is None:
        ayoconnect_disbursed_loan_count = 0

    if pg_disbursed_loan_count is None:
        pg_disbursed_loan_count = 0

    # calculate with float ratio and get the payment gateway vendor result
    if ayoconnect_disbursed_loan_count < (today_disbursed_loan_count * ayoconnect_ratio_float):
        return DisbursementVendors.AYOCONNECT
    elif pg_disbursed_loan_count < (today_disbursed_loan_count * doku_ratio_float):
        return DisbursementVendors.PG

    return default_payment_gateway


def replace_ayoconnect_transaction_id_in_url(url, unique_id):
    transaction_id = unique_id
    old_transaction_id = re.search(r'transactionId=(\w+)\&', url).group(1)
    url = url.replace(old_transaction_id, transaction_id)
    return url
