import hashlib
import logging
import requests
from datetime import timedelta

from django.conf import settings

from juloserver.julo.services2 import get_redis_client

from juloserver.credit_card.utils import AESCipher

logger = logging.getLogger(__name__)


class BSSCreditCardClient(object):
    def __init__(self, base_url):
        self.base_url = base_url

    def __construct_hash_code(self, payloads: dict) -> str:
        combined_payloads = ''.join(
            str(payload) for payload in list(payloads.values()) +
            [settings.BSS_CREDIT_CARD_HASHCODE]
        )
        combined_payloads = combined_payloads.encode('utf-8')
        hash_result = hashlib.md5(combined_payloads).hexdigest()

        return hash_result

    def __construct_reference_number(self, application_xid: int) -> str:
        redis_client = get_redis_client()
        key = 'credit_card:counter_reference_number:{}'.format(application_xid)
        counter = redis_client.get(key)
        if counter:
            counter = str(redis_client.increment(key))
        else:
            redis_client.set(key, 0, timedelta(days=1))
            counter = '0'
        reference_number_max_length = 12
        application_xid = str(application_xid)
        counter_formatted = counter.zfill(reference_number_max_length - len(application_xid))
        reference_number = application_xid + counter_formatted
        return reference_number

    def __send_request(self, url: str, data: dict, timeout: int = 60) -> dict:
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        logger_data = {
            'action': "juloserver.credit_card.clients.bss.BSSCreditCardClient.__send_request",
            'url': url,
            'data': data
        }
        try:
            response = requests.post(url, headers=headers, data=data, timeout=timeout)
            response.raise_for_status()
            return_response = response.json()
            logger_data['response'] = response.__dict__
            logger_data['error_message'] = None
            logger.info(logger_data)
        except Exception as error:
            error_message = str(error)
            return_response = {"error": error}
            response = error
            logger_data['response'] = response.__dict__
            logger_data['error_message'] = error_message
            logger.error(logger_data)

        return return_response

    def inquiry_card_status(
            self, card_number: str, virtual_account_number: str,
            virtual_account_name: str, application_xid: int
    ) -> dict:
        url = self.base_url + '/inquiryCardStatus'
        reference_number = self.__construct_reference_number(application_xid)
        data = dict(
            cardNumber=card_number,
            virtualAccountNumber=virtual_account_number,
            virtualAccountName=virtual_account_name,
            referenceNumber=reference_number,
        )
        hash_code = self.__construct_hash_code(data)
        data['hashCode'] = hash_code
        response = self.__send_request(url, data, timeout=10)
        return response

    def request_otp_value(
            self, card_number: str, virtual_account_number: str,
            virtual_account_name: str, transaction_type: str, application_xid: int
    ) -> dict:
        url = self.base_url + '/requestOTPValue'
        reference_number = self.__construct_reference_number(application_xid)
        data = dict(
            cardNumber=card_number,
            virtualAccountNumber=virtual_account_number,
            virtualAccountName=virtual_account_name,
            transactionType=transaction_type,
            referenceNumber=reference_number,
        )
        hash_code = self.__construct_hash_code(data)
        data['hashCode'] = hash_code
        response = self.__send_request(url, data)
        return response

    def set_new_pin(
            self, card_number: str, virtual_account_number: str,
            virtual_account_name: str, otp: str, pin: str, application_xid: int
    ):
        url = self.base_url + '/newPIN'
        reference_number = self.__construct_reference_number(application_xid)
        aes_cipher = AESCipher(card_number)
        encrypted_pin = aes_cipher.encrypt(pin)
        data = dict(
            cardNumber=card_number,
            virtualAccountNumber=virtual_account_number,
            virtualAccountName=virtual_account_name,
            otp=otp,
            encryptedPIN=encrypted_pin,
            referenceNumber=reference_number,
        )
        hash_code = self.__construct_hash_code(data)
        data['hashCode'] = hash_code
        response = self.__send_request(url, data)
        return response

    def change_pin(
            self, card_number: str, virtual_account_number: str,
            virtual_account_name: str, old_pin: str, new_pin: str, application_xid: int
    ) -> dict:
        url = self.base_url + '/changePIN'
        reference_number = self.__construct_reference_number(application_xid)
        aes_cipher = AESCipher(card_number)
        encrypted_old_pin = aes_cipher.encrypt(old_pin)
        encrypted_new_pin = aes_cipher.encrypt(new_pin)
        data = dict(
            cardNumber=card_number,
            virtualAccountNumber=virtual_account_number,
            virtualAccountName=virtual_account_name,
            encryptedOldPIN=encrypted_old_pin,
            encryptedNewPIN=encrypted_new_pin,
            referenceNumber=reference_number,
        )
        hash_code = self.__construct_hash_code(data)
        data['hashCode'] = hash_code
        response = self.__send_request(url, data)
        return response

    def block_card(
            self, card_number: str, virtual_account_number: str,
            virtual_account_name: str, application_xid: int
    ):
        url = self.base_url + '/blockCard'
        reference_number = self.__construct_reference_number(application_xid)
        data = dict(
            cardNumber=card_number,
            virtualAccountNumber=virtual_account_number,
            virtualAccountName=virtual_account_name,
            referenceNumber=reference_number,
        )
        hash_code = self.__construct_hash_code(data)
        data['hashCode'] = hash_code
        response = self.__send_request(url, data)
        return response

    def unblock_card(
            self, card_number: str, virtual_account_number: str,
            virtual_account_name: str, pin: str, application_xid: int
    ) -> dict:
        url = self.base_url + '/unblockCard'
        reference_number = self.__construct_reference_number(application_xid)
        aes_cipher = AESCipher(card_number)
        encrypted_pin = aes_cipher.encrypt(pin)
        data = dict(
            cardNumber=card_number,
            virtualAccountNumber=virtual_account_number,
            virtualAccountName=virtual_account_name,
            encryptedPIN=encrypted_pin,
            referenceNumber=reference_number,
        )
        hash_code = self.__construct_hash_code(data)
        data['hashCode'] = hash_code
        response = self.__send_request(url, data)
        return response

    def reset_pin(
            self, card_number: str, virtual_account_number: str,
            virtual_account_name: str, otp: str, pin: str, application_xid: int
    ) -> dict:
        url = self.base_url + '/resetPIN'
        reference_number = self.__construct_reference_number(application_xid)
        aes_cipher = AESCipher(card_number)
        encrypted_pin = aes_cipher.encrypt(pin)
        data = dict(
            cardNumber=card_number,
            virtualAccountNumber=virtual_account_number,
            virtualAccountName=virtual_account_name,
            otp=otp,
            encryptedPIN=encrypted_pin,
            referenceNumber=reference_number,
        )
        hash_code = self.__construct_hash_code(data)
        data['hashCode'] = hash_code
        response = self.__send_request(url, data)
        return response

    def close_card(
            self, card_number: str, virtual_account_number: str,
            virtual_account_name: str, application_xid: int
    ):
        url = self.base_url + '/closeCard'
        reference_number = self.__construct_reference_number(application_xid)
        data = {
            'cardNumber': card_number,
            'virtualAccountNumber': virtual_account_number,
            'virtualAccountName': virtual_account_name,
            'referenceNumber': reference_number,
        }
        hash_code = self.__construct_hash_code(data)
        data['hashCode'] = hash_code
        response = self.__send_request(url, data)
        return response
