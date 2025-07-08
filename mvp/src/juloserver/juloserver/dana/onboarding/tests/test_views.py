import json
import random
import string
import uuid

from datetime import datetime
from django.conf import settings
from django.test import override_settings
from django.test.testcases import TestCase
from mock import MagicMock, patch

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLimit
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    StatusLookupFactory,
    AccountLookupFactory,
)
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.dana.constants import (
    BindingResponseCode,
    DANA_BANK_NAME,
    BindingRejectCode,
    DANA_ACCOUNT_LOOKUP_NAME,
    AccountUpdateResponseCode,
    DanaProductType,
)
from juloserver.dana.models import DanaCustomerData, DanaAccountInfo
from juloserver.dana.tests.factories import (
    DanaCustomerDataFactory,
    DanaApplicationReferenceFactory,
    DanaFDCResultFactory,
)
from juloserver.dana.utils import create_sha256_signature, hash_body
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.julo.models import Customer, FeatureSetting
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    PartnerFactory,
    ProductLineFactory,
    ProductProfileFactory,
    WorkflowFactory,
    BlacklistCustomerFactory,
    ApplicationHistoryFactory,
    CustomerFactory,
    ApplicationFactory,
    FeatureSettingFactory,
)
from juloserver.julovers.tests.factories import (
    WorkflowStatusNodeFactory,
    WorkflowStatusPathFactory,
)

from rest_framework import status
from rest_framework.test import APIClient


def create_random_character(max_number: int = 7):
    response = ''.join(random.choices(string.ascii_uppercase + string.digits, k=max_number))
    return response


class TestDanaAccountBindingAPI(TestCase):
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def setUp(self) -> None:
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.partner = PartnerFactory(name=PartnerNameConstant.DANA, is_active=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA)
        self.account_lookup = AccountLookupFactory(
            partner=self.partner, workflow=self.workflow, name=DANA_ACCOUNT_LOOKUP_NAME
        )

        product_line_code = ProductLineCodes.DANA
        self.product_line = ProductLineFactory(
            product_line_type=DANA_ACCOUNT_LOOKUP_NAME, product_line_code=product_line_code
        )
        self.product_profile = ProductProfileFactory(
            name=DANA_ACCOUNT_LOOKUP_NAME,
            code=product_line_code,
        )

        self.customer = CustomerFactory()
        self.account = AccountFactory()
        self.account_factory = AccountLimitFactory(account=self.account)
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='9999999999999',
            name_in_bank=DANA_BANK_NAME,
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone='087790909090',
            method='xfers',
        )
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            name_bank_validation=self.name_bank_validation,
            partner=self.partner,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            customer=self.customer,
            partner=self.partner,
            application=self.application,
            dana_customer_identifier="12345679237",
            credit_score=750,
        )

        application_id = self.application.id
        self.dana_application_reference = DanaApplicationReferenceFactory(
            application_id=application_id,
            partner_reference_no='1234555',
            reference_no=uuid.uuid4(),
        )

        self.blacklist_name = 'Test User'
        BlacklistCustomerFactory(
            citizenship='Indonesia', fullname_trim='test-user', name=self.blacklist_name
        )

        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=135,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=133,
            type='graveyard',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=130,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=130,
            status_next=190,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusNodeFactory(status_node=100, workflow=self.workflow, handler='Dana100Handler')

        WorkflowStatusNodeFactory(status_node=105, workflow=self.workflow, handler='Dana105Handler')

        WorkflowStatusNodeFactory(status_node=133, workflow=self.workflow, handler='Dana133Handler')

        WorkflowStatusNodeFactory(status_node=135, workflow=self.workflow, handler='Dana135Handler')

        WorkflowStatusNodeFactory(status_node=130, workflow=self.workflow, handler='Dana130Handler')

        WorkflowStatusNodeFactory(status_node=190, workflow=self.workflow, handler='Dana190Handler')

        dt = datetime.now()
        self.x_timestamp = datetime.timestamp(dt)
        self.x_partner_id = 554433
        self.x_external_id = 223344
        self.x_channel_id = 12345

        self.payload = {
            "customerId": "21612837132",
            "partnerReferenceNo": "DS2uawhzh6XdohiCswMsOFhJ4MMcqfNq",
            "phoneNo": "082290768740",
            "additionalInfo": {
                "registrationTime": "2020-12-17T14:49:00+07:00",
                "identificationInfo": "xxxxxxxxxxxxxxxxxxxx",  # Encrypted data can mock later
                "proposedCreditLimit": {"value": "200000.00", "currency": "IDR"},
                "creditScore": 60,
                "lenderProductId": DanaProductType.CICIL,
                "appId": "22",
                "incomeRange": "Di bawah Rp1.000.000",
            },
        }
        self.endpoint = '/v1.0/registration-account-creation'
        self.method = "POST"
        self.hashed_body = hash_body(self.payload)

        self.string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        self.x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, self.string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

        self.whitelisted_customer_id = '999999999999991'
        self.list_bypass_dana_customer_id = [self.whitelisted_customer_id]
        self.feature_setting_whitelisted_user = FeatureSettingFactory(
            feature_name=FeatureNameConst.DANA_WHITELIST_USERS,
            parameters={'dana_customer_identifiers': self.list_bypass_dana_customer_id},
            is_active=False,
            category='dana',
            description='Dana whitelist users, if identity valid bypass dana validation checking',
        )
        self.decrypt_mock_return_value = {
            "cardId": "3106031909910021",
            "cardName": "Rudy Rudy Rudy",
            "cardType": "DRIVER_LICENSE/IDENTIFICATION_NUMBER",
            "selfieImage": "http://images.example.com/",
            "identityCardImage": "http://images.example.com/",
            "dob": "04-12-1999",
            "address": "Our Home Address",
        }

        FeatureSetting.objects.get_or_create(
            is_active=True,
            feature_name=FeatureNameConst.DANA_MONTHLY_INCOME,
            category="dana",
            parameters={
                "belowrp1.000.000": 1000000,
                "dibawahrp1.000.000": 1000000,
                "rp1.000.000–rp2.000.000": 1500000,
                "rp2.000.000–rp3.000.000": 2500000,
                "rp3.000.000–rp5.000.000": 4000000,
                "rp5.000.000–rp10.000.000": 7500000,
                "rp10.000.000–rp20.000.000": 15000000,
                "rp20.000.000andabove": 20000000,
                "rp20.000.000dankeatas": 20000000,
            },
            description="Mapping dana income range to monthly income",
        )

    @patch('juloserver.dana.onboarding.services.execute_after_transaction_safely')
    @patch('juloserver.dana.onboarding.services.execute_after_transaction_safely')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_success_account_binding(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
        upload_selfie_image_mock: MagicMock,
        upload_identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True
        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True
        upload_selfie_image_mock.return_value = True
        upload_identity_card_image_mock.return_value = True
        response = self.client.post(self.endpoint, data=self.payload, format='json')

        response_data = response.json()

        # success
        self.assertEqual(response_data['responseCode'], BindingResponseCode.SUCCESS.code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data['partnerReferenceNo'], self.payload['partnerReferenceNo'])

        # Application in 190, and account is active
        customer = Customer.objects.filter(customer_xid=response_data['accountId']).last()
        dana_customer_data = DanaCustomerData.objects.filter(customer=customer).last()

        application = dana_customer_data.application
        account = dana_customer_data.account

        # Application is 190, account is active 420
        self.assertEqual(application.status, ApplicationStatusCodes.LOC_APPROVED)
        self.assertEqual(account.status.status_code, AccountConstant.STATUS_CODE.active)
        self.assertEqual(1000000, application.monthly_income)

    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_invalid_field_additional_info(
        self, auth_mock: MagicMock, decrypt_mock: MagicMock
    ) -> None:
        auth_mock.return_value = True

        # additional info empty
        del self.payload['additionalInfo']
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_MANDATORY_FIELD.code
        )

        # Identification Info empty
        self.payload['additionalInfo'] = {
            "registrationTime": "2020-12-17T14:49:00+07:00",
            "proposedCreditLimit": {"value": "200000.00", "currency": "IDR"},
            "creditScore": 60,
            "lenderProductId": DanaProductType.CICIL,
            "appId": "22",
        }
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_MANDATORY_FIELD.code
        )

        # Failed to decrypt
        self.payload['additionalInfo']['identificationInfo'] = 'xxxxxxxxxx'
        decrypt_mock.return_value = Exception

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )

        decrypt_mock.return_value = self.decrypt_mock_return_value

        # Failed don't have proposedCreditLimit
        del self.payload['additionalInfo']['proposedCreditLimit']
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_MANDATORY_FIELD.code
        )

        # Invalid field format proposed credit limit
        self.payload['additionalInfo']['proposedCreditLimit'] = 'amount'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )

        # Invalid mandatory fields proposedCreditLimit
        self.payload['additionalInfo']['proposedCreditLimit'] = {"currency": "IDR"}
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_MANDATORY_FIELD.code
        )

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_invalid_field_serializer(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True
        old_card_id = self.decrypt_mock_return_value['cardId']

        self.decrypt_mock_return_value['cardId'] = ""
        decrypt_mock.return_value = self.decrypt_mock_return_value

        # Required mandatory field
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_MANDATORY_FIELD.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['cardId'])
        self.decrypt_mock_return_value['cardId'] = old_card_id

        decrypt_mock.return_value = self.decrypt_mock_return_value

        # Invalid customerId
        self.payload['customerId'] = 'sssaaa1121312'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['customerId'])

        # Invalid registration time format
        self.payload['customerId'] = '21612837132'
        self.payload['additionalInfo']['registrationTime'] = 'sasasas'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['registrationTime'])

        # Invalid Phone No
        self.payload['additionalInfo']['registrationTime'] = '2020-12-17T14:49:00+07:00'
        self.payload['phoneNo'] = '06120909292'

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['phoneNo'])

        self.payload['phoneNo'] = '082290768740'

        # invalid cardName
        card_name = create_random_character(101)
        old_card_name = self.decrypt_mock_return_value['cardName']
        old_card_id = self.decrypt_mock_return_value['cardId']
        old_dob = self.decrypt_mock_return_value['dob']
        self.decrypt_mock_return_value['cardName'] = card_name
        decrypt_mock.return_value = self.decrypt_mock_return_value

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['cardName'])
        self.decrypt_mock_return_value['cardName'] = old_card_name

        # Invalid Card ID
        # Card id 17 characters
        self.decrypt_mock_return_value['cardId'] = "31060319099100212"
        decrypt_mock.return_value = self.decrypt_mock_return_value

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['cardId'])
        self.decrypt_mock_return_value['cardId'] = old_card_id

        # Invalid dob
        self.decrypt_mock_return_value['dob'] = "1999-04-01"
        decrypt_mock.return_value = self.decrypt_mock_return_value

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['dob'])
        self.decrypt_mock_return_value['dob'] = old_dob

        decrypt_mock.return_value = self.decrypt_mock_return_value

        # Invalid creditScore
        self.payload['additionalInfo']['creditScore'] = 'sss'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['creditScore'])

        self.payload['additionalInfo']['creditScore'] = '60'

        # Invalid lenderProductId
        product_id = create_random_character(256)
        self.payload['additionalInfo']['lenderProductId'] = product_id
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['lenderProductId'])

        self.payload['additionalInfo']['lenderProductId'] = DanaProductType.CICIL

        # Invalid appId
        app_id = create_random_character(256)
        self.payload['additionalInfo']['appId'] = app_id
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['appId'])

        self.payload['additionalInfo']['appId'] = '123'

        # User is exists and approved return success, but different partnerReferenceNo
        self.application.change_status(ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        self.dana_customer_data.dana_customer_identifier = self.payload['customerId']
        self.dana_customer_data.lender_product_id = self.payload['additionalInfo'][
            'lenderProductId'
        ]
        self.dana_customer_data.save(
            update_fields=['dana_customer_identifier', 'lender_product_id']
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data['responseCode'], BindingResponseCode.SUCCESS.code)
        self.assertEqual(
            response_data['additionalInfo']['rejectCode'],
            BindingRejectCode.USER_HAS_REGISTERED.code,
        )

        # User is exists and fraud, but different partnerReferenceNo
        self.application.change_status(ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD)
        self.application.save()

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_data['responseCode'], BindingResponseCode.BAD_REQUEST.code)
        self.assertEqual(
            response_data['additionalInfo']['rejectCode'], BindingRejectCode.FRAUD_CUSTOMER.code
        )

        self.dana_customer_data.dana_customer_identifier = '9992929121212'
        self.dana_customer_data.save(update_fields=['dana_customer_identifier'])

        # Invalid partnerReferenceNo is exists
        self.payload['partnerReferenceNo'] = '1234555'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], BindingResponseCode.INCONSISTENT_REQUEST.code
        )

        # Existing NIK but different customerId
        self.payload['partnerReferenceNo'] = 'DS2uawhzh6XdohiCswMsOFhJ4MMcqfNq'
        self.dana_customer_data.mobile_number = self.payload['phoneNo']
        self.dana_customer_data.save(update_fields=['mobile_number'])
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_data['responseCode'], BindingResponseCode.BAD_REQUEST.code)
        self.assertEqual(
            response_data['additionalInfo']['rejectCode'],
            BindingRejectCode.EXISTING_USER_DIFFERENT_CUSTOMER_ID.code,
        )

    @patch('juloserver.dana.onboarding.services.execute_after_transaction_safely')
    @patch('juloserver.dana.onboarding.services.execute_after_transaction_safely')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_success_existing_phone_number_nik_none(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
        upload_selfie_image_mock: MagicMock,
        upload_identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True

        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True
        self.customer.phone = self.payload['phoneNo']
        self.customer.save(update_fields=['phone'])
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response_data['responseCode'], BindingResponseCode.SUCCESS.code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_data['partnerReferenceNo'], self.payload['partnerReferenceNo'])

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_reject_blacklist(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True

        self.decrypt_mock_return_value['cardName'] = self.blacklist_name
        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response_data['responseCode'], BindingResponseCode.BAD_REQUEST.code)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['additionalInfo']['rejectCode'],
            BindingRejectCode.BLACKLISTED_CUSTOMER.code,
        )

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_reject_fraud(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True

        ktp = "3106031909910021"
        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True

        self.application.ktp = ktp
        self.application.save(update_fields=['ktp'])

        ApplicationHistoryFactory(
            application_id=self.application.id, status_old=105, status_new=133
        )

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response_data['responseCode'], BindingResponseCode.BAD_REQUEST.code)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['additionalInfo']['rejectCode'], BindingRejectCode.FRAUD_CUSTOMER.code
        )

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_reject_delinquent(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True

        ktp = "3106031909910021"
        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True

        account = self.application.account
        account.status = StatusLookupFactory(status_code=421)
        account.save()

        self.application.ktp = ktp
        self.application.change_status(ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response_data['responseCode'], BindingResponseCode.BAD_REQUEST.code)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['additionalInfo']['rejectCode'],
            BindingRejectCode.DELINQUENT_CUSTOMER.code,
        )

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_success_reapply(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True

        ktp = "3106031909910021"
        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True

        self.dana_customer_data.dana_customer_identifier = self.payload['customerId']
        self.dana_customer_data.nik = self.decrypt_mock_return_value.get('cardId')
        self.dana_customer_data.lender_product_id = self.payload['additionalInfo'][
            'lenderProductId'
        ]
        self.dana_customer_data.save(
            update_fields=['dana_customer_identifier', 'nik', 'lender_product_id']
        )

        account = self.application.account
        account.status = StatusLookupFactory(status_code=420)
        account.save()

        self.application.ktp = ktp
        self.application.change_status(ApplicationStatusCodes.APPLICATION_DENIED)
        self.application.save()
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        # Success
        self.assertEqual(response_data['responseCode'], BindingResponseCode.SUCCESS.code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Have 2 applications
        self.assertEqual(self.customer.application_set.count(), 2)

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_success_reapply_old_fraud_application(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        self.feature_setting_whitelisted_user.is_active = True
        self.feature_setting_whitelisted_user.save(update_fields=['is_active'])
        auth_mock.return_value = True

        ktp = "3106031909910021"
        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True

        self.payload['customerId'] = self.whitelisted_customer_id
        self.dana_customer_data.dana_customer_identifier = self.payload['customerId']
        self.dana_customer_data.nik = self.decrypt_mock_return_value.get('cardId')
        self.dana_customer_data.lender_product_id = self.payload['additionalInfo'][
            'lenderProductId'
        ]
        self.dana_customer_data.save(
            update_fields=['dana_customer_identifier', 'nik', 'lender_product_id']
        )

        account = self.application.account
        account.status = StatusLookupFactory(status_code=420)
        account.save()

        self.application.ktp = ktp
        self.application.change_status(ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD)
        self.application.save()
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        # Success
        self.assertEqual(response_data['responseCode'], BindingResponseCode.SUCCESS.code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Have a Reject Code
        self.assertEqual(
            response_data['additionalInfo']['rejectCode'],
            BindingRejectCode.WHITELISTED_FRAUD_USER.code,
        )
        self.assertEqual(
            response_data['additionalInfo']['rejectReason'],
            BindingRejectCode.WHITELISTED_FRAUD_USER.reason,
        )

        # Have 2 applications
        self.assertEqual(self.customer.application_set.count(), 2)

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_reject_existing_phone_number_different_nik(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True

        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True
        self.customer.phone = self.payload['phoneNo']
        self.customer.nik = '4106031909910021'
        self.customer.save(update_fields=['phone', 'nik'])
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response_data['responseCode'], BindingResponseCode.BAD_REQUEST.code)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['additionalInfo']['rejectCode'],
            BindingRejectCode.EXISTING_USER_INVALID_NIK.code,
        )

    @patch('juloserver.dana.onboarding.services.execute_after_transaction_safely')
    @patch('juloserver.dana.onboarding.services.execute_after_transaction_safely')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_reject_underage(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
        upload_selfie_image_mock: MagicMock,
        upload_identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True

        today = datetime.today()
        underage_year = today.year - 18
        self.decrypt_mock_return_value['dob'] = "04-12-{}".format(underage_year)
        decrypt_mock.return_value = self.decrypt_mock_return_value

        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True
        upload_selfie_image_mock.return_value = True
        upload_identity_card_image_mock.return_value = True

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()
        self.assertEqual(response_data['responseCode'], BindingResponseCode.BAD_REQUEST.code)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            BindingRejectCode.UNDERAGED_CUSTOMER.code, response_data['additionalInfo']['rejectCode']
        )
        self.assertEqual(
            BindingRejectCode.UNDERAGED_CUSTOMER.reason,
            response_data['additionalInfo']['rejectReason'],
        )

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_existing_dana_customer_identifier_user_different_nik(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True

        ktp = "4106031909910089"
        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True

        self.dana_customer_data.dana_customer_identifier = self.payload['customerId']
        self.dana_customer_data.nik = ktp
        self.dana_customer_data.lender_product_id = DanaProductType.CASH_LOAN
        self.dana_customer_data.save(
            update_fields=['dana_customer_identifier', 'nik', 'lender_product_id']
        )

        account = self.application.account
        account.status = StatusLookupFactory(status_code=420)
        account.save()

        self.application.ktp = ktp
        self.application.change_status(ApplicationStatusCodes.APPLICATION_DENIED)
        self.application.save()
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response_data['responseCode'], BindingResponseCode.BAD_REQUEST.code)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['additionalInfo']['rejectCode'],
            BindingRejectCode.EXISTING_USER_DIFFERENT_NIK.code,
        )

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_success_register_user_different_product_id(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        auth_mock.return_value = True

        ktp = self.decrypt_mock_return_value['cardId']
        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True

        self.dana_customer_data.dana_customer_identifier = self.payload['customerId']
        self.dana_customer_data.nik = ktp
        self.dana_customer_data.lender_product_id = DanaProductType.CASH_LOAN
        self.dana_customer_data.save(
            update_fields=['dana_customer_identifier', 'nik', 'lender_product_id']
        )

        account = self.application.account
        account.status = StatusLookupFactory(status_code=420)
        account.save()

        self.application.ktp = ktp
        self.application.change_status(ApplicationStatusCodes.APPLICATION_DENIED)
        self.application.save()
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response_data['responseCode'], BindingResponseCode.SUCCESS.code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_success_register_dana_cashloan_with_product_config_true(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        """
        Test success registration DANA CASH LOAN
        with condition dana_customer_identifier have
        DANA CICIL and product config is True.
        """
        auth_mock.return_value = True
        dana_cash_loan = "DANA CASH LOAN"
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DANA_CASH_LOAN_REGISTRATION_USER_CONFIG,
            is_active=True,
            category='dana',
            description='Product Configuration For Dana Cash Loan',
        )
        ProductLineFactory(
            product_line_type=dana_cash_loan, product_line_code=ProductLineCodes.DANA_CASH_LOAN
        )
        ProductProfileFactory(
            name=dana_cash_loan,
            code=ProductLineCodes.DANA_CASH_LOAN,
        )

        ktp = self.decrypt_mock_return_value['cardId']
        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True

        self.dana_customer_data.dana_customer_identifier = self.payload['customerId']
        self.dana_customer_data.nik = ktp
        self.dana_customer_data.lender_product_id = DanaProductType.CICIL
        self.dana_customer_data.save(
            update_fields=['dana_customer_identifier', 'nik', 'lender_product_id']
        )
        self.payload['additionalInfo']['lenderProductId'] = DanaProductType.CASH_LOAN

        account = self.application.account
        account.status = StatusLookupFactory(status_code=420)
        account.save()

        self.application.ktp = ktp
        self.application.change_status(ApplicationStatusCodes.APPLICATION_DENIED)
        self.application.save()
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response_data['responseCode'], BindingResponseCode.SUCCESS.code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_reject_register_dana_cashloan_with_product_config_true(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        """
        Test reject registration DANA CASH LOAN
        with condition dana_customer_identifier not have
        DANA CICIL and product config is True.
        """
        auth_mock.return_value = True
        dana_cash_loan = "DANA CASH LOAN"
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DANA_CASH_LOAN_REGISTRATION_USER_CONFIG,
            is_active=True,
            category='dana',
            description='Product Configuration For Dana Cash Loan',
        )
        ProductLineFactory(
            product_line_type=dana_cash_loan, product_line_code=ProductLineCodes.DANA_CASH_LOAN
        )
        ProductProfileFactory(
            name=dana_cash_loan,
            code=ProductLineCodes.DANA_CASH_LOAN,
        )

        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True

        self.dana_customer_data.delete()
        self.application.delete()
        self.payload['additionalInfo']['lenderProductId'] = DanaProductType.CASH_LOAN

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_data['responseCode'], BindingResponseCode.BAD_REQUEST.code)
        self.assertEqual(
            response_data['additionalInfo']['rejectCode'],
            BindingRejectCode.NON_EXISTING_DANA_CICIL_USER.code,
        )

    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.serializers.validate_image_url')
    @patch('juloserver.dana.onboarding.views.decrypt_personal_information')
    @patch('juloserver.dana.security.is_valid_signature')
    def test_success_register_dana_cashloan_with_product_config_false(
        self,
        auth_mock: MagicMock,
        decrypt_mock: MagicMock,
        selfie_image_mock: MagicMock,
        identity_card_image_mock: MagicMock,
    ) -> None:
        """
        Test success registration DANA CASH LOAN
        with condition dana_customer_identifier not have
        DANA CICIL and product config is False.
        """
        auth_mock.return_value = True
        dana_cash_loan = "DANA CASH LOAN"
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DANA_CASH_LOAN_REGISTRATION_USER_CONFIG,
            is_active=False,
            category='dana',
            description='Product Configuration For Dana Cash Loan',
        )
        ProductLineFactory(
            product_line_type=dana_cash_loan, product_line_code=ProductLineCodes.DANA_CASH_LOAN
        )
        ProductProfileFactory(
            name=dana_cash_loan,
            code=ProductLineCodes.DANA_CASH_LOAN,
        )

        decrypt_mock.return_value = self.decrypt_mock_return_value
        selfie_image_mock.return_value = True
        identity_card_image_mock.return_value = True

        self.dana_customer_data.delete()
        self.application.delete()
        self.payload['additionalInfo']['lenderProductId'] = DanaProductType.CASH_LOAN

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        response_data = response.json()

        self.assertEqual(response_data['responseCode'], BindingResponseCode.SUCCESS.code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestDanaAccountUpdateAPI(TestCase):
    @override_settings(DANA_SIGNATURE_KEY='secret-signature')
    def setUp(self) -> None:
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.partner = PartnerFactory(name=PartnerNameConstant.DANA, is_active=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA)
        self.account_lookup = AccountLookupFactory(
            partner=self.partner, workflow=self.workflow, name=DANA_ACCOUNT_LOOKUP_NAME
        )

        product_line_code = ProductLineCodes.DANA
        self.product_line = ProductLineFactory(
            product_line_type=DANA_ACCOUNT_LOOKUP_NAME, product_line_code=product_line_code
        )
        self.product_profile = ProductProfileFactory(
            name=DANA_ACCOUNT_LOOKUP_NAME,
            code=product_line_code,
        )

        self.customer = CustomerFactory()
        self.account = AccountFactory()
        self.account_limit_factory = AccountLimitFactory(
            account=self.account,
            max_limit=500000,
            set_limit=500000,
            available_limit=200000,
            used_limit=300000,
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='9999999999999',
            name_in_bank=DANA_BANK_NAME,
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone='087790909090',
            method='xfers',
        )
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            name_bank_validation=self.name_bank_validation,
            partner=self.partner,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            customer=self.customer,
            partner=self.partner,
            application=self.application,
            dana_customer_identifier="12345679237",
            credit_score=750,
            lender_product_id='LP0001',
        )

        application_id = self.application.id
        self.dana_application_reference = DanaApplicationReferenceFactory(
            application_id=application_id,
            partner_reference_no='1234555',
            reference_no=uuid.uuid4(),
        )

        self.dana_fdc_result = DanaFDCResultFactory(
            fdc_status="Approve1",
            status="success",
            dana_customer_identifier="12345679237",
            application_id=self.application.id,
            lender_product_id="LP0001",
        )

        dt = datetime.now()
        self.x_timestamp = datetime.timestamp(dt)
        self.x_partner_id = 554433
        self.x_external_id = 223344
        self.x_channel_id = 12345

        self.endpoint = '/v1.0/user/update/account-info'
        self.method = "POST"

    def generate_signature(self, payload):
        self.hashed_body = hash_body(payload)

        string_to_sign = (
            self.method + ":" + self.endpoint + ":" + self.hashed_body + ":" + str(self.x_timestamp)
        )
        x_signature = create_sha256_signature(settings.DANA_SIGNATURE_KEY, string_to_sign)
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

    @patch('juloserver.dana.security.is_valid_signature')
    def test_success_account_update_limit_increase(self, auth_mock: MagicMock):
        auth_mock.return_value = True

        new_limit = "1000000.00"
        update_value = {"currency": "IDR", "value": "1000000.00"}
        payload = {
            "customerId": self.dana_customer_data.dana_customer_identifier,
            "lenderProductId": self.dana_customer_data.lender_product_id,
            "updateInfoList": [
                {
                    "updateKey": "limit",
                    "updateValue": json.dumps(update_value),
                    "updateAdditionalInfo": {"updatedTime": "2023-09-09 10:10:10"},
                },
            ],
            "additionalInfo": {},
        }
        self.generate_signature(payload=payload)

        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()

        # success
        self.assertEqual(response_data['responseCode'], AccountUpdateResponseCode.SUCCESS.code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # account limit is updated
        account_limit = (
            AccountLimit.objects.filter(
                account__dana_customer_data__dana_customer_identifier=payload["customerId"]
            )
            .select_related(
                'account',
                'account__dana_customer_data',
                'account__dana_customer_data__customer__customerlimit',
            )
            .first()
        )

        new_available_limit = float(new_limit) - self.account_limit_factory.used_limit
        self.assertEqual(new_available_limit, account_limit.available_limit)
        self.assertEqual(float(new_limit), account_limit.set_limit)
        self.assertEqual(float(new_limit), account_limit.max_limit)

    @patch('juloserver.dana.security.is_valid_signature')
    def test_success_account_update_limit_decrease(self, auth_mock: MagicMock):
        auth_mock.return_value = True

        self.account_limit_factory.set_limit = 200000
        self.account_limit_factory.max_limit = 200000
        self.account_limit_factory.available_limit = 0
        self.account_limit_factory.used_limit = 200000

        new_limit = "100000.00"
        update_value = {"currency": "IDR", "value": "100000.00"}
        payload = {
            "customerId": self.dana_customer_data.dana_customer_identifier,
            "lenderProductId": self.dana_customer_data.lender_product_id,
            "updateInfoList": [
                {
                    "updateKey": "limit",
                    "updateValue": json.dumps(update_value),
                    "updateAdditionalInfo": {"updatedTime": "2023-09-09 10:10:10"},
                },
            ],
            "additionalInfo": {},
        }
        self.generate_signature(payload=payload)

        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()

        # success
        self.assertEqual(response_data['responseCode'], AccountUpdateResponseCode.SUCCESS.code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # account limit is updated
        account_limit = (
            AccountLimit.objects.filter(
                account__dana_customer_data__dana_customer_identifier=payload["customerId"]
            )
            .select_related(
                'account',
                'account__dana_customer_data',
                'account__dana_customer_data__customer__customerlimit',
            )
            .first()
        )

        self.assertEqual(account_limit.available_limit, 0)
        self.assertEqual(account_limit.set_limit, float(new_limit))
        self.assertEqual(account_limit.max_limit, float(new_limit))

    @patch('juloserver.dana.security.is_valid_signature')
    def test_invalid_field_serializer(self, auth_mock: MagicMock):
        auth_mock.return_value = True
        update_value = {"currency": "IDR", "value": "100000.00"}
        payload = {
            "customerId": self.dana_customer_data.dana_customer_identifier,
            "lenderProductId": self.dana_customer_data.lender_product_id,
            "updateInfoList": [
                {
                    "updateKey": "limit",
                    "updateValue": json.dumps(update_value),
                    "updateAdditionalInfo": {"updatedTime": "2023-09-09 10:10:10"},
                },
            ],
            "additionalInfo": {"appId": "app0001"},
        }
        self.generate_signature(payload=payload)

        # Invalid customerId - Customer not found
        payload['customerId'] = 'sssaaa1121312'
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_data['responseCode'], AccountUpdateResponseCode.BAD_REQUEST.code)
        self.assertTrue(response_data['additionalInfo']['errors']['customerId'])

        # Invalid customerId - customerId length format
        payload['customerId'] = '74557571403755173808993476135722997540823030416846218791954731842'
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['customerId'])

        # Invalid lenderProductId - lenderProductId length format
        payload['customerId'] = self.dana_customer_data.dana_customer_identifier
        payload['lenderProductId'] = '130225115859365982721865029839287'
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['lenderProductId'])

        # Invalid lenderProductId - lenderProductId not found for CustomerId
        payload['lenderProductId'] = 'CASH_LOAN_JULO_01'
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_data['responseCode'], AccountUpdateResponseCode.BAD_REQUEST.code)
        self.assertTrue(response_data['additionalInfo']['errors']['lenderProductId'])

        # Invalid updateKey value
        payload['lenderProductId'] = self.dana_customer_data.lender_product_id
        payload['updateInfoList'][0]['updateKey'] = 'hello'
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_UPDATE_KEY.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['updateKey'])

        # Invalid updateValue value
        payload['updateInfoList'][0]['updateKey'] = "limit"
        payload['updateInfoList'][0]['updateValue'] = json.dumps({"currency": "IDR"})
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['updateValue'])

        # Invalid updateAdditionalInfo value - String updateAdditionalInfo
        payload['updateInfoList'][0]['updateValue'] = json.dumps(update_value)
        payload['updateInfoList'][0]['updateAdditionalInfo'] = '23445'
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(
            response_data['additionalInfo']['errors']['updateInfoList']['updateAdditionalInfo']
        )

        # Invalid updateAdditionalInfo value - Empty updateAdditionalInfo
        payload['updateInfoList'][0]['updateAdditionalInfo'] = {}
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_FIELD_FORMAT.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['updateAdditionalInfo'])

        # Invalid updateInfoList value - Duplicate key
        payload['updateInfoList'][0]['updateAdditionalInfo'] = None
        payload['updateInfoList'].append(
            {
                "updateKey": "limit",
                "updateValue": json.dumps(update_value),
                "updateAdditionalInfo": {"updatedTime": "2023-09-09 10:10:10"},
            }
        )
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['updateInfoList'])

    @patch('juloserver.dana.security.is_valid_signature')
    def test_invalid_mandatory_field_serializer(self, auth_mock: MagicMock):
        auth_mock.return_value = True
        update_value = {"currency": "IDR", "value": "100000.00"}
        payload = {
            "customerId": self.dana_customer_data.dana_customer_identifier,
            "lenderProductId": self.dana_customer_data.lender_product_id,
            "updateInfoList": [
                {
                    "updateKey": "limit",
                    "updateValue": json.dumps(update_value),
                    "updateAdditionalInfo": None,
                },
            ],
            "additionalInfo": {"appId": "app0001"},
        }
        self.generate_signature(payload=payload)

        # Invalid customerId - Empty customerId
        payload['customerId'] = ""
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['customerId'])

        # Invalid lenderProductId - Empty lenderProductId
        payload['customerId'] = self.dana_customer_data.dana_customer_identifier
        payload['lenderProductId'] = ""
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['lenderProductId'])

        # Invalid additionalInfo - Empty additionalInfo
        payload['lenderProductId'] = self.dana_customer_data.lender_product_id
        payload['additionalInfo'] = None
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['additionalInfo'])

        # Invalid updateInfoList - Empty updateKey
        payload['additionalInfo'] = {"appId": "app0001"}
        payload['updateInfoList'][0]['updateKey'] = ""
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['updateInfoList']['updateKey'])

        # Invalid updateInfoList - Empty updateValue
        payload['updateInfoList'][0]['updateKey'] = "limit"
        payload['updateInfoList'][0]['updateValue'] = ""
        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_data['responseCode'], AccountUpdateResponseCode.INVALID_MANDATORY_FIELD.code
        )
        self.assertTrue(response_data['additionalInfo']['errors']['updateInfoList']['updateValue'])

    @patch('juloserver.dana.security.is_valid_signature')
    def test_dana_account_info(self, auth_mock: MagicMock):
        auth_mock.return_value = True

        # dana customer have fdc result
        update_value = {"currency": "IDR", "value": "1000000.00"}
        payload = {
            "customerId": self.dana_customer_data.dana_customer_identifier,
            "lenderProductId": self.dana_customer_data.lender_product_id,
            "updateInfoList": [
                {
                    "updateKey": "limit",
                    "updateValue": json.dumps(update_value),
                    "updateAdditionalInfo": {"updatedTime": "2023-09-09 10:10:10"},
                },
            ],
            "additionalInfo": {},
        }
        self.generate_signature(payload=payload)
        self.client.post(self.endpoint, data=payload, format='json')

        dana_account_info = DanaAccountInfo.objects.filter(
            dana_customer_identifier=self.dana_customer_data.dana_customer_identifier,
            lender_product_id=self.dana_customer_data.lender_product_id,
        ).last()
        self.assertIsNotNone(dana_account_info)  # dana account info created

        # dana customer doesn't have fdc result
        customer2 = CustomerFactory()
        account2 = AccountFactory()
        application2 = ApplicationFactory(
            account=account2,
            customer=customer2,
            product_line=self.product_line,
            name_bank_validation=self.name_bank_validation,
            partner=self.partner,
        )
        dana_customer_without_fdc = DanaCustomerDataFactory(
            account=account2,
            customer=customer2,
            partner=self.partner,
            application=application2,
            dana_customer_identifier="12345679900",
            credit_score=750,
            lender_product_id="LP0001",
        )
        account_limit_2 = AccountLimitFactory(
            account=account2,
            max_limit=500000,
            set_limit=500000,
            available_limit=200000,
            used_limit=300000,
        )
        payload2 = {
            "customerId": dana_customer_without_fdc.dana_customer_identifier,
            "lenderProductId": self.dana_customer_data.lender_product_id,
            "updateInfoList": [
                {
                    "updateKey": "limit",
                    "updateValue": json.dumps(update_value),
                    "updateAdditionalInfo": {"updatedTime": "2023-09-09 10:10:10"},
                },
            ],
            "additionalInfo": {},
        }
        self.generate_signature(payload=payload2)
        self.client.post(self.endpoint, data=payload2, format='json')

        dana_account_info2 = DanaAccountInfo.objects.filter(
            dana_customer_identifier=dana_customer_without_fdc.dana_customer_identifier
        ).last()
        self.assertIsNone(dana_account_info2)  # dana account info is not created
        account_limit = (
            AccountLimit.objects.filter(
                account__dana_customer_data__dana_customer_identifier=payload2["customerId"],
                account__dana_customer_data__lender_product_id=payload2["lenderProductId"],
            )
            .select_related(
                'account',
                'account__dana_customer_data',
                'account__dana_customer_data__customer__customerlimit',
            )
            .first()
        )
        new_available_limit = float("1000000.00") - account_limit_2.used_limit
        self.assertEqual(new_available_limit, account_limit.available_limit)

    @patch('juloserver.dana.security.is_valid_signature')
    def test_success_dana_cash_loan_account_update_limit_increase(self, auth_mock: MagicMock):
        auth_mock.return_value = True

        # Create data
        customer = CustomerFactory()
        account = AccountFactory()
        account_limit_factory = AccountLimitFactory(
            account=account,
            max_limit=1000000,
            set_limit=1000000,
            available_limit=7000000,
            used_limit=3000000,
        )
        application = ApplicationFactory(
            account=account,
            customer=customer,
            product_line=self.product_line,
            name_bank_validation=self.name_bank_validation,
            partner=self.partner,
        )
        dana_customer_data = DanaCustomerDataFactory(
            account=account,
            customer=customer,
            partner=self.partner,
            application=application,
            dana_customer_identifier="12345673823",
            credit_score=750,
            lender_product_id="CASH_LOAN_JULO_01",
        )

        new_limit = "20000000.00"
        update_value = {"currency": "IDR", "value": new_limit}
        payload = {
            "customerId": dana_customer_data.dana_customer_identifier,
            "lenderProductId": "CASH_LOAN_JULO_01",
            "updateInfoList": [
                {
                    "updateKey": "limit",
                    "updateValue": json.dumps(update_value),
                    "updateAdditionalInfo": {"updatedTime": "2023-09-09 10:10:10"},
                },
            ],
            "additionalInfo": {},
        }
        self.generate_signature(payload=payload)

        response = self.client.post(self.endpoint, data=payload, format='json')
        response_data = response.json()

        # success
        self.assertEqual(response_data['responseCode'], AccountUpdateResponseCode.SUCCESS.code)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # account limit is updated
        account_limit = (
            AccountLimit.objects.filter(
                account__dana_customer_data__dana_customer_identifier=payload["customerId"],
                account__dana_customer_data__lender_product_id=payload["lenderProductId"],
            )
            .select_related(
                'account',
                'account__dana_customer_data',
                'account__dana_customer_data__customer__customerlimit',
            )
            .first()
        )

        new_available_limit = float(new_limit) - account_limit_factory.used_limit
        self.assertEqual(new_available_limit, account_limit.available_limit)
        self.assertEqual(float(new_limit), account_limit.set_limit)
        self.assertEqual(float(new_limit), account_limit.max_limit)
