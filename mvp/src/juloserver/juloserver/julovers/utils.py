import logging

from django.conf import settings
from random import randint
from juloserver.pii_vault.clients import PIIVaultClient
from juloserver.julovers.exceptions import JuloverException

logger = logging.getLogger(__name__)

def random_number(length):
    range_start = 10 ** (length - 1)
    range_end = (10**length) - 1
    return randint(range_start, range_end)


def generate_nik():
    return str(random_number(8)) + str(randint(13, 99)) + str(random_number(6))


def tokenize_julover_pii(julover_dict, customer_xid):
    if customer_xid is None:
        raise  JuloverException()
    mobile_phone_number = julover_dict.get("mobile_phone_number")
    if mobile_phone_number:
        mobile_phone_number=str(mobile_phone_number)
    pii_information = {
        "name": julover_dict.get("fullname"),
        "email": julover_dict.get("email"),
        "mobile_number": mobile_phone_number,
        "nik": julover_dict.get("real_nik"),
        "vault_xid": customer_xid,
    }
    pii_vault_client = PIIVaultClient(authentication=settings.PII_VAULT_JULOVER_TOKEN)
    result = pii_vault_client.tokenize([pii_information])
    if result[0].get("error"):
        logger.error(result[0].get("error"))
        raise JuloverException()
    result = result[0]["fields"]
    mapped_data = {
        "fullname_tokenized": result.get("name"),
        "email_tokenized": result.get("email"),
        "mobile_phone_number_tokenized": result.get("mobile_number"),
        "real_nik_tokenized": result.get("nik"),
    }

    return mapped_data


def detokenize_julover_pii(julover_dict, customer_xid):
    if customer_xid is None:
        logger.error("customer_xid is not present to detokenize")
        raise JuloverException()
    payload = []
    back_map = {}
    for variable in julover_dict:
        if variable.endswith("_tokenized") and julover_dict[variable]:
            payload.append({"vault_xid": customer_xid, "token": julover_dict[variable]})
            back_map[julover_dict[variable]] = variable[:-10]
    if len(payload) == 0:
        return julover_dict
    pii_vault_client = PIIVaultClient(authentication=settings.PII_VAULT_JULOVER_TOKEN)
    result = pii_vault_client.detokenize(payload)
    for row in result:
        julover_dict[back_map[row["token"]]] = row.get("value")
    return julover_dict
