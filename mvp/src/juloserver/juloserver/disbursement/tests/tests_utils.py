import json

from django.test.testcases import TestCase

from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.disbursement.utils import (bank_name_similarity_check, encrypt_request_payload,
                                           decrypt_request_payload, payment_gateway_matchmaking,
                                           replace_ayoconnect_transaction_id_in_url)
from juloserver.julo.constants import FeatureNameConst
from juloserver.disbursement.constants import DisbursementVendors, DisbursementStatus
from mock import patch


class TestUtils(TestCase):
    def setUp(self):
        self.identical_name_data = ('Mohammad rachmat ramadhan', 'Mohammad rachmat ramadhan')
        self.typo_name_data_1 = ('Mohammad rachmat ramadhan', 'Mochammad rachmat ramadhan')
        self.typo_name_data_2 = ('Mohammad rachmat ramadhan', 'Muhammad rachmat ramadhan')
        self.typo_name_data_3 = ('Mohammad rachmat ramadhan', 'Muhamad rachmat ramadhan')
        self.typo_name_data_4 = ('Mohammad rachmat ramadhan', 'Mohammad rahmat ramadhan')
        self.abbreviated_name_data_1 = ('Mohammad rachmat ramadhan', 'M rachmat ramadhan')
        self.abbreviated_name_data_2 = ('Mohammad rachmat ramadhan', 'Mohammad rachmat r')
        self.trimed_name_data_1 = ('Mohammad rachmat ramadhan', 'Mohammad rachmat ramadha')
        self.trimed_name_data_2 = ('Mohammad rachmat ramadhan', 'Mohammad rachmat rama')
        self.titled_name_data_1 = ('Mohammad rachmat ramadhan', 'Bpk Mohammad rachmat ramadhan')
        self.titled_name_data_2 = ('Mohammad rachmat ramadhan', 'Sdr Mohammad rachmat ramadhan')
        self.titled_name_data_3 = ('Mohammad rachmat ramadhan', 'Mohammad rachmat ramadhan, S.Kom.')
        self.different_name_data_1 = ('Mohammad rachmat ramadhan', 'Muhamad ramdan')
        self.different_name_data_2 = ('Adit wiryawan', 'Dita wiryawan')

    def test_identical_name(self):
        self.assertTrue(bank_name_similarity_check(*self.identical_name_data))

    def test_typo_name(self):
        self.assertTrue(bank_name_similarity_check(*self.typo_name_data_1))
        self.assertTrue(bank_name_similarity_check(*self.typo_name_data_2))
        self.assertTrue(bank_name_similarity_check(*self.typo_name_data_3))
        self.assertTrue(bank_name_similarity_check(*self.typo_name_data_4))

    def test_abbreviated_name(self):
        self.assertFalse(bank_name_similarity_check(*self.abbreviated_name_data_1))
        self.assertFalse(bank_name_similarity_check(*self.abbreviated_name_data_2))

    def test_trimed_name(self):
        self.assertTrue(bank_name_similarity_check(*self.trimed_name_data_1))
        self.assertTrue(bank_name_similarity_check(*self.trimed_name_data_2))

    def test_titled_name(self):
        self.assertTrue(bank_name_similarity_check(*self.titled_name_data_1))
        self.assertTrue(bank_name_similarity_check(*self.titled_name_data_2))
        self.assertFalse(bank_name_similarity_check(*self.titled_name_data_3))

    def test_different_name(self):
        self.assertFalse(bank_name_similarity_check(*self.different_name_data_1))
        self.assertFalse(bank_name_similarity_check(*self.different_name_data_2))


class TestAyoconnectUtils(TestCase):
    def setUp(self) -> None:
        self.headers = {'Authorization': 'Bearer yefaNvMy4ncATB5ZF0bwLtL9GS42',
                        'Content-Type': 'application/json', 'Accept': 'application/json',
                        'A-Correlation-ID': '6376a9f3d80a4e31b8da74aaad16d23d',
                        'A-Merchant-Code': 'JULOTF', 'A-Latitude': '-6.2146',
                        'A-Longitude': '106.845'}
        self.payload = {'transactionId': 'e61e9074ab3d4b45bcb97cc7cbd4dba4',
                        'phoneNumber': '6281260036277',
                        'customerDetails': {'ipAddress': '192.168.100.12'},
                        'beneficiaryAccountDetails': {'accountNumber': '121212121212',
                                                      'bankCode': 'CENAIDJA'}}
        self.pg_ratio_feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_PAYMENT_GATEWAY_RATIO,
            parameters={"doku_ratio": "30%", "ac_ratio": "70%"},
        )

    def test_encrypt_and_decrypt_header_and_payload(self):
        header_and_payload = {
            "header": self.headers,
            "payload": self.payload
        }
        header_and_payload_str = json.dumps(header_and_payload)
        encrypted_header_and_payload = encrypt_request_payload(header_and_payload_str)

        self.assertTrue(isinstance(encrypted_header_and_payload, str))
        self.assertNotEqual(encrypted_header_and_payload, header_and_payload_str)

        decrypted_header_and_payload = decrypt_request_payload(encrypted_header_and_payload)
        self.assertEqual(decrypted_header_and_payload, header_and_payload_str)

    def test_payment_gateway_matchmaking(self):
        for i in range(3):
            DisbursementFactory(
                method=DisbursementVendors.PG, disburse_status=DisbursementStatus.COMPLETED
            )

        method = payment_gateway_matchmaking()
        self.assertEqual(method, DisbursementVendors.AYOCONNECT)

    @patch('juloserver.disbursement.utils.generate_unique_id')
    def test_replace_transaction_id(self, mock_generate_unique_id):
        unique_id = '666'
        mock_generate_unique_id.return_value = unique_id
        url = "https://sandbox.api.of.ayoconnect.id/api/v1/bank-disbursements/status/1212asdfdasf?transactionId=1234&transactionReferenceNumber=None&beneficiaryId=123&customerId=None"
        new_url = replace_ayoconnect_transaction_id_in_url(url, unique_id)
        self.assertEqual(
            new_url,
            "https://sandbox.api.of.ayoconnect.id/api/v1/bank-disbursements/status/1212asdfdasf?transactionId=666&transactionReferenceNumber=None&beneficiaryId=123&customerId=None"
        )


class DummyAyoconnectClient(object):
    is_error = False
    error = None

    def create_disbursement(
        self, user_token: str, ayoconnect_customer_id: str, beneficiary_id: str, amount: str,
        remark: str = None, counter: int = 0, log_data=None) -> dict:
        if not self.is_error:
            return {'transaction':{"status": 1}}
        raise self.error


class DummySentryClient(object):
    capture_exception_called = False

    def capture_exceptions(self):
        self.capture_exception_called = True
