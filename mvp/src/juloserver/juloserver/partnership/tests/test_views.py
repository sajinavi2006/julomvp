import hashlib
import json
import mock
import datetime
import time
import pytest
import base64
import ulid
import io

from datetime import timedelta
from mock import patch
from dateutil.relativedelta import relativedelta
from factory import LazyAttribute
from faker import Faker

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.files import File
from django.test import override_settings
from django.test.testcases import TestCase
from django.utils import timezone
from http import HTTPStatus
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import MagicMock

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory, AccountLimitFactory, AccountLookupFactory,
    AccountPropertyFactory
)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory
)
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.otp.constants import SessionTokenAction
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.bpjs.tests.factories import BpjsTaskFactory
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.julo.models import (
    Partner,
    ProductLine,
    Application,
    StatusLookup,
    FeatureSetting,
    OtpRequest,
    FDCInquiry,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.services2 import encrypt
from juloserver.julo.tests.factories import (
    PartnershipApplicationDataFactory,
    PartnershipSessionInformationFactory,
    WorkflowFactory,
    AuthUserFactory,
    ProductProfileFactory,
    ProductLineFactory,
    XidLookupFactory,
    ProvinceLookupFactory,
    CityLookupFactory,
    DistrictLookupFactory,
    SubDistrictLookupFactory,
    ImageFactory,
    ApplicationFactory,
    CustomerFactory,
    StatusLookupFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    ProductLookupFactory,
    ApplicationHistoryFactory,
    PartnerFactory,
    PartnershipCustomerDataFactory,
    XidLookupFactory,
    FeatureSettingFactory,
    LoanFactory,
    MobileFeatureSettingFactory,
    CreditScoreFactory,
    VoiceRecordFactory,
    CustomerWalletHistoryFactory,
    FaceRecognitionFactory,
    OtpRequestFactory,
    PartnershipCustomerDataOTPFactory,
    PartnerBankAccountFactory,
    BankFactory,
    PartnerPropertyFactory,
    FDCInquiryFactory,
)

from juloserver.julo_privyid.tests.factories import MockRedis
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.merchant_financing.models import Merchant, MerchantApplicationReapplyInterval
from juloserver.merchant_financing.tests.factories import MerchantFactory
from juloserver.partnership.constants import (
    PartnershipLogStatus,
    PartnershipTypeConstant,
    ErrorMessageConst,
    PaylaterTransactionStatuses,
    PartnershipFeatureNameConst,
)
from juloserver.partnership.models import (
    CustomerPinVerify,
    PartnershipCustomerData,
    PartnershipApiLog,
    PartnerOrigin,
    PaylaterTransaction,
    PartnershipFeatureSetting,
    PartnershipUserOTPAction,
    PartnershipClikModelResult,
)
from juloserver.customer_module.models import BankAccountDestination
from juloserver.partnership.tests.factories import (
    DistributorFactory,
    MerchantDistributorCategoryFactory,
    PartnershipConfigFactory,
    PartnershipLogRetryCheckTransactionStatusFactory,
    PartnershipTransactionFactory,
    PartnershipTypeFactory,
    MerchantHistoricalTransactionFactory,
    PartnershipApplicationDataFactory,
    PartnerLoanSimulationsFactory,
    CustomerPinVerifyFactory,
    PaylaterTransactionFactory,
    PaylaterTransactionDetailsFactory,
    PaylaterTransactionStatusFactory,
    PaylaterTransactionLoanFactory,
    PartnerOriginFactory,
    PartnershipApiLogFactory,
    PartnerLoanRequestFactory,
    LivenessResultsMappingFactory,
)
from juloserver.portal.object.bulk_upload.constants import MerchantFinancingCSVUploadPartner
from juloserver.streamlined_communication.test.factories import (
    InfoCardPropertyFactory,
    ButtonInfoCardFactory,
    StreamlinedMessageFactory,
    StreamlinedCommunicationFactory
)
from juloserver.streamlined_communication.constant import (
    CardProperty,
    CommunicationPlatform
)
from juloserver.payment_point.models import TransactionMethod
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.pin.constants import (
    ReturnCode,
    ResetMessage,
    VerifyPinMsg
)
from juloserver.pin.services import VerifyPinProcess

from juloserver.julo.tests.factories import PartnershipApplicationDataFactory

from juloserver.julo.product_lines import ProductLineCodes

from juloserver.pin.tests.factories import LoginAttemptFactory
from juloserver.moengage.tests.factories import MoengageUploadFactory
from juloserver.moengage.constants import MoengageEventType
from juloserver.partnership.authentication import PartnershipOnboardingInternalAuthentication
from juloserver.personal_data_verification.tests.factories import (
    DukcapilResponseFactory,
    DukcapilFaceRecognitionCheckFactory,
)
from juloserver.partnership.liveness_partnership.constants import (
    LivenessType,
)
from juloserver.partnership.liveness_partnership.tests.factories import (
    LivenessResultFactory,
)

fake = Faker()


def register_partner_merchant_financing():
    from juloserver.partnership.services.services import (
        process_register_partner_for_merchant_with_product_line_data,
    )

    product_line_type = 'MF'
    product_line_code = 300
    ProductLineFactory(
        product_line_type=product_line_type,
        product_line_code=product_line_code
    )
    ProductProfileFactory(
        name=product_line_type,
        code=product_line_code,
    )
    group = Group(name="julo_partners")
    group.save()
    partnership_type = PartnershipTypeFactory(partner_type_name='Merchant financing')

    data_partner = {
        'username': 'partner_merchant_financing',
        'email': 'partnermerchantfinancing@gmail.com',
        'partnership_type': partnership_type.id,
        'callback_url': None,
        'callback_token': None,
    }
    response = process_register_partner_for_merchant_with_product_line_data(data_partner)
    return response


def register_partner_lead_gen():
    from juloserver.partnership.services.services import process_register_partner

    group = Group(name="julo_partners")
    group.save()
    partnership_type = PartnershipTypeFactory(partner_type_name='Lead gen')

    data_partner = {
        'username': 'partner_lead_gen',
        'email': 'partnerleadgen@gmail.com',
        'partnership_type': partnership_type.id,
        'callback_url': None,
        'callback_token': None,
    }
    response = process_register_partner(data_partner)
    return response


def register_partner_linkaja(client):
    group = Group(name="julo_partners")
    group.save()
    partnership_type = PartnershipTypeFactory(
        partner_type_name=PartnerNameConstant.LINKAJA)

    data_partner = {
        'username': PartnerNameConstant.LINKAJA,
        'email': 'partnerleadgen@gmail.com',
        'partnership_type': partnership_type.id
    }
    response = client.post('/api/partnership/v1/partner',
                           data=data_partner)
    return response


def register_partner_paylater(client):
    group = Group.objects.filter(name="julo_partners").last()
    if not group:
        group = Group(name="julo_partners")
        group.save()

    partnership_type = PartnershipTypeFactory(partner_type_name='Whitelabel Paylater')

    data_partner = {
        'username': 'partner_paylater',
        'email': 'partnerpaylater@gmail.com',
        'partnership_type': partnership_type.id
    }
    response = client.post('/api/partnership/v1/partner',
                           data=data_partner)
    return response


def new_julo1_product_line():
    if not ProductLine.objects.filter(product_line_code=1).exists():
        ProductLineFactory(product_line_code=1)


class TestMerchantTransactionHistory(TestCase):
    @patch('juloserver.julo.services.process_application_status_change')
    def setUp(self, mock_process_application_status_change):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        response_register_partner_mf = register_partner_merchant_financing()
        partner = Partner.objects.first()
        self.distributor = DistributorFactory(
            partner=partner,
            user=partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor a',
            address='jakarta',
            email='testdistributora@gmail.com',
            phone_number='08123152321',
            type_of_business='warung',
            npwp='123040410292312',
            nib='223040410292312',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=123456,
        )
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner_mf['secret_key'],
            HTTP_USERNAME=response_register_partner_mf['partner_name'],
        )
        for x in range(0, 302):
            XidLookupFactory(
                is_used_application=False
            )
        data = dict(
            nik='3203020101910011',
            shop_name='merchant',
            distributor_xid=int(self.distributor.distributor_xid)
        )
        response_create_merchant = self.client.post('/api/partnership/v1/merchants',
                                                    data=data, format='json')
        merchant = Merchant.objects.get(
            merchant_xid=response_create_merchant.json()['data']['merchant_xid']
        )
        merchant.update_safely(distributor=self.distributor)
        data_application = dict(
            merchant_xid=response_create_merchant.json()['data']['merchant_xid'],
            pin=159558,
            email="merchantJulo+4@julo.co.id"
        )
        self.response_create_application = self.client.post(
            '/api/partnership/v1/merchants/initial-application',
            data=data_application, format='json'
        )
        self.application = Application.objects.filter(application_xid=
                                                      self.response_create_application.json()['data'][
                                                          'application_xid']).last()
        self.application.customer = self.customer
        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.save()
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))

    def test_store_merchant_historical_transaction(self):
        data = [
            {
                "type": "debit",
                "transaction_date": "2010-01-01",
                "booking_date": "2010-01-01",
                "payment_method": "verified",
                "amount": 100,
                "term_of_payment": 0
            },
            {
                "type": "debit",
                "transaction_date": "2010-01-01",
                "booking_date": "2010-01-01",
                "payment_method": "verified",
                "amount": 1,
                "term_of_payment": 1
            }
        ]
        response = self.client.post(
            '/api/partnership/v1/merchants/transactions/{}'.format(
                self.response_create_application.json()['data']['application_xid']
            ),
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()['data'])


class TestAddress(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        response_register_partner_mf = register_partner_merchant_financing()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner_mf['secret_key'],
            HTTP_USERNAME=response_register_partner_mf['partner_name'],
        )
        self.province_lookup = ProvinceLookupFactory(
            province='Jawa barat',
            is_active=True,
        )
        self.city_lookup = CityLookupFactory(
            province=self.province_lookup,
            city='Garut',
            is_active=True
        )
        self.district_lookup = DistrictLookupFactory(
            city=self.city_lookup,
            is_active=True,
            district='Padasuka'
        )
        self.sub_district_lookup = SubDistrictLookupFactory(
            sub_district='Cikajang',
            is_active=True,
            zipcode='43251',
            district=self.district_lookup
        )

    def test_get_address_province(self):
        response = self.client.get('/api/partnership/v1/address?address_type=province')
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.province_lookup.province, response.json()['data'])

    def test_get_address_city(self):
        response = self.client.get(
            '/api/partnership/v1/address?address_type=city&province={}'.format(
                self.province_lookup.province
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.city_lookup.city, response.json()['data'])

    def test_get_address_district(self):
        response = self.client.get(
            '/api/partnership/v1/address?address_type=district&province={}&city={}'.format(
                self.province_lookup.province, self.city_lookup.city
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.district_lookup.district, response.json()['data'])

    def test_get_address_sub_district(self):
        response = self.client.get(
            '/api/partnership/v1/address?address_type=sub_district&province={}'
            '&city={}&district={}'.format(
                self.province_lookup.province, self.city_lookup.city, self.district_lookup.district
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sub_district_lookup.sub_district,
                         response.json()['data'][0]['subDistrict'])
        self.assertEqual(self.sub_district_lookup.zipcode,
                         response.json()['data'][0]['zipcode'])


class TestDropdown(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner_mf = register_partner_merchant_financing()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner_mf['secret_key'],
            HTTP_USERNAME=response_register_partner_mf['partner_name'],
        )

    def test_success_get_marital_statuses(self):
        response = self.client.get('/api/partnership/v1/dropdowns?data_selected=marital_statuses')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()['data'])

    def test_failed_get_marital_statuses(self):
        response = self.client.get('/api/partnership/v1/dropdowns?data_selected=marital_status')
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(response.json()['data'])


class TestPartnerLeadGen(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        self.partnership_type = PartnershipTypeFactory()
        new_julo1_product_line()
        WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        group = Group(name="julo_partners")
        group.save()

    def test_success_register_partner_lead_gen(self):
        data_partner = {
            'username': 'partner_lead_gen',
            'email': 'partnerleadgen@gmail.com',
            'partnership_type': self.partnership_type.id,
        }
        response = self.client.post('/api/partnership/v1/partner',
                                    data=data_partner)
        self.assertEqual(response.status_code, 201)


class TestPartnerMerchantFinancing(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        self.partnership_type = PartnershipTypeFactory()
        WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        product_line_type = 'MF'
        product_line_code = 300
        ProductLineFactory(
            product_line_type=product_line_type,
            product_line_code=product_line_code
        )
        ProductProfileFactory(
            name=product_line_type,
            code=product_line_code,
        )
        group = Group(name="julo_partners")
        group.save()

    def test_success_register_partner_merchant_financing(self):
        partnership_type = PartnershipTypeFactory(partner_type_name='Merchant financing')
        data_partner = {
            'username': 'partner_merchant_financing',
            'email': 'partnermerchantfinancing@gmail.com',
            'partnership_type': partnership_type.id
        }
        response = self.client.post('/api/partnership/v1/merchant-partner',
                                    data=data_partner)
        self.assertEqual(response.status_code, 201)


class TestApplicationMerchantFinancing(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner_mf = register_partner_merchant_financing()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner_mf['secret_key'],
            HTTP_USERNAME=response_register_partner_mf['partner_name'],
        )
        partner = Partner.objects.first()
        self.distributor = DistributorFactory(
            partner=partner,
            user=partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor a',
            address='jakarta',
            email='testdistributora@gmail.com',
            phone_number='08123152321',
            type_of_business='warung',
            npwp='123040410292312',
            nib='223040410292312',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=123456,
        )
        XidLookupFactory(
            xid=2554367999,
            is_used_application=False
        )
        self.merchant_1 = MerchantFactory(
            nik='3203020101910011',
            shop_name='merchant 1',
            distributor=self.distributor,
            merchant_xid=2554367997
        )
        self.merchant_2 = MerchantFactory(
            nik='3203020101910012',
            shop_name='merchant 2',
            distributor=self.distributor,
            merchant_xid=2554367998
        )
        self.province_lookup = ProvinceLookupFactory(
            province='Jawa barat',
            is_active=True,
        )
        self.city_lookup = CityLookupFactory(
            province=self.province_lookup,
            city='Garut',
            is_active=True
        )
        self.district_lookup = DistrictLookupFactory(
            city=self.city_lookup,
            is_active=True,
            district='Padasuka'
        )
        self.sub_district_lookup = SubDistrictLookupFactory(
            sub_district='Cikajang',
            is_active=True,
            zipcode='43251',
            district=self.district_lookup
        )
        # Set Config for dot address
        self.province_lookup2 = ProvinceLookupFactory(
            province='Papua',
            is_active=True,
        )
        self.city_lookup2 = CityLookupFactory(
            province=self.province_lookup2,
            city='Kab. Puncak',
            is_active=True
        )
        self.district_lookup2 = DistrictLookupFactory(
            city=self.city_lookup2,
            is_active=True,
            district='Gome'
        )
        self.sub_district_lookup2 = SubDistrictLookupFactory(
            sub_district='Maki',
            is_active=True,
            zipcode='98966',
            district=self.district_lookup2
        )
        workflow = WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        customer = CustomerFactory(user=user)
        self.application = ApplicationFactory(
            customer=customer,
            workflow=workflow,
            merchant=self.merchant_1,
            partner=self.distributor.partner,
            application_xid=2554367666,
        )
        ImageFactory(
            image_type='selfie',
            image_source=self.application.id
        )
        ImageFactory(
            image_type='ktp_self',
            image_source=self.application.id
        )
        ImageFactory(
            image_type='crop_selfie',
            image_source=self.application.id
        )
        today_date = timezone.localtime(timezone.now()).date()
        MerchantHistoricalTransactionFactory(
            merchant=self.application.merchant,
            type='debit',
            transaction_date=today_date,
            booking_date=today_date,
            payment_method='verified',
            amount=10000,
            term_of_payment=1,
            is_using_lending_facilities=False,
            application=self.application
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))

        self.merchant_3 = MerchantFactory(
            nik='3203020101910013',
            shop_name='merchant 3',
            distributor=self.distributor,
            merchant_xid=2554367999
        )
        self.reject_status = StatusLookupFactory(status_code=135)
        self.rejected_application = ApplicationFactory(
            workflow=workflow,
            merchant=self.merchant_3,
            partner=self.distributor.partner,
        )

        self.rejected_application.application_status = StatusLookupFactory(
            status_code=135
        )
        self.rejected_application.save()
        self.rejected_customer = self.rejected_application.customer

        self.rejected_application_history = ApplicationHistoryFactory(
            application_id=self.rejected_application.id,
            status_old=0,
            status_new=135
        )
        ten_days_datetime = now - relativedelta(days=10)
        self.rejected_application_history.cdate = ten_days_datetime
        self.rejected_application_history.save()
        self.today = timezone.localtime(timezone.now())
        application_xid = self.application.application_xid
        self.transaction_endpoint = '/api/partnership/v1/merchants/transactions/{}'.format(
            application_xid
        )
        self.merchant_app_endpoint = '/api/partnership/v1/merchants/applications/{}'.format(
            application_xid
        )

    @patch('juloserver.julo.services.process_application_status_change')
    def test_success_application_registration(self, mock_process_application_status_change):
        initial_data_application = {
            "email": "merchantJulo@julo.co.id",
            "merchant_xid": self.merchant_2.merchant_xid
        }
        response_initial_application = self.client.post(
            '/api/partnership/v1/merchants/initial-application',
            data=initial_data_application, format='json'
        )
        self.assertEqual(response_initial_application.status_code, status.HTTP_201_CREATED)

    @patch('juloserver.partnership.services.services.process_application_status_change')
    def test_success_complete_application_registration(self,
                                                       mock_process_application_status_change):
        self.application.application_status = StatusLookupFactory(
            status_code=100
        )
        self.application.save()
        data = [
            {
                "type": "debit",
                "transaction_date": "2010-01-01",
                "booking_date": "2010-01-01",
                "payment_method": "verified",
                "amount": 100,
                "term_of_payment": 0
            },
            {
                "type": "debit",
                "transaction_date": "2010-01-01",
                "booking_date": "2010-01-01",
                "payment_method": "verified",
                "amount": 1,
                "term_of_payment": 1
            }
        ]
        response = self.client.post(
            '/api/partnership/v1/merchants/transactions/{}'.format(
                self.application.application_xid
            ),
            data=data, format='json'
        )
        longform_data_application = {
            "fullname": "prod only3,./",
            "birth_place": "Jakarta",
            "dob": "2020-01-01",
            "gender": "Pria",
            "address_street_num": "Fawn Road 2 68",
            "address_provinsi": self.province_lookup.province,
            "address_kabupaten": self.city_lookup.city,
            "address_kecamatan": self.district_lookup.district,
            "address_kelurahan": self.sub_district_lookup.sub_district,
            "address_kodepos": self.sub_district_lookup.zipcode,
            "marital_status": "Lajang",
            "mobile_phone_1": "082123466207",
            "spouse_name": "Jeane Melany",
            "spouse_mobile_phone": "085330838901",
            "close_kin_name": "ibu name",
            "close_kin_mobile_phone": "082123466197",
        }
        response_longform = self.client.post(
            '/api/partnership/v1/merchants/applications/{}'.format(
                self.application.application_xid
            ),
            data=longform_data_application, format='json'
        )
        self.assertEqual(response_longform.status_code, status.HTTP_200_OK)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_success_reapply_when_status_135(self, mock_process_application_status_change):
        self.rejected_customer.can_reapply_date = self.today + datetime.timedelta(days=-1)
        self.rejected_customer.save()

        initial_data_application = {
            "email": "merchantJulo@julo.co.id",
            "merchant_xid": self.merchant_3.merchant_xid
        }
        response_initial_application = self.client.post(
            '/api/partnership/v1/merchants/initial-application',
            data=initial_data_application, format='json'
        )
        self.assertEqual(response_initial_application.status_code, status.HTTP_201_CREATED)

    def test_fail_reapply_when_status_135(self):
        self.rejected_customer.can_reapply_date = self.today + datetime.timedelta(days=1)
        self.rejected_customer.save()

        initial_data_application = {
            "email": "merchantJulo3@julo.co.id",
            "merchant_xid": self.merchant_3.merchant_xid
        }
        response_initial_application = self.client.post(
            '/api/partnership/v1/merchants/initial-application',
            data=initial_data_application, format='json'
        )
        self.assertEqual(response_initial_application.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('juloserver.partnership.services.services.process_application_status_change')
    def test_success_complete_application_registration_with_dot_address(
        self,
        _: MagicMock
    ) -> None:
        # Created application status 100 (Form Created)
        self.application.application_status = StatusLookupFactory(
            status_code=100
        )
        self.application.save()

        data = [
            {
                "type": "debit",
                "transaction_date": "2010-01-01",
                "booking_date": "2010-01-01",
                "payment_method": "verified",
                "amount": 100,
                "term_of_payment": 0
            },
            {
                "type": "debit",
                "transaction_date": "2010-01-01",
                "booking_date": "2010-01-01",
                "payment_method": "verified",
                "amount": 1,
                "term_of_payment": 1
            }
        ]

        # Hit API Historical Transaction Endpoint to create transaction
        self.client.post(self.transaction_endpoint,data=data, format='json')

        longform_data_application = {
            "fullname": "prod only3,./",
            "birth_place": "Jakarta",
            "dob": "2020-01-01",
            "gender": "Pria",
            "address_street_num": "Fawn Road 2 68",
            "address_provinsi": self.province_lookup2.province,
            "address_kabupaten": self.city_lookup2.city,  # Kab. Puncak
            "address_kecamatan": self.district_lookup2.district,
            "address_kelurahan": self.sub_district_lookup2.sub_district,
            "address_kodepos": self.sub_district_lookup2.zipcode,
            "marital_status": "Lajang",
            "mobile_phone_1": "082123466207",
            "spouse_name": "Jeane Melany",
            "spouse_mobile_phone": "085330838901",
            "close_kin_name": "ibu name",
            "close_kin_mobile_phone": "082123466197",
        }

        # Response Success
        response = self.client.post(
            self.merchant_app_endpoint,
            data=longform_data_application,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


class TestCreatePin(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_partner_pin(self):
        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        encrypter = encrypt()
        xid = encrypter.encode_string(str(application.application_xid))
        data = dict(
            xid=xid,
            pin='159357'
        )
        response = self.client.post('/api/partnership/v1/create-pin', data=data, format='json')
        self.assertIsNotNone(response)

    def test_input_partner_pin(self):
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        application = ApplicationFactory(customer=customer)
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=user, latest_failure_count=1, last_failure_time=now - relativedelta(minutes=90))
        user.set_password('159357')
        user.save()
        encrypter = encrypt()
        xid = encrypter.encode_string(str(application.application_xid))
        data = dict(
            xid=xid,
            pin='159357'
        )
        response = self.client.post('/api/partnership/v1/input-pin', data=data, format='json')
        self.assertIsNotNone(response)


class TestPartnerLeadGenLoanOffer(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        self.response_register_partner = register_partner_lead_gen()
        self.partner = Partner.objects.filter(name='partner_lead_gen').last()
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_register_partner['secret_key'],
            HTTP_USERNAME=self.response_register_partner['partner_name'],
        )
        self.partnership_type = PartnershipTypeFactory()
        new_julo1_product_line()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.partner_user = AuthUserFactory(username='test_lead_gen_offer')
        self.customer = CustomerFactory(user=self.partner_user)
        status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=status)
        CustomerPinFactory(user=self.partner_user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999887,
            partner=self.partner
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.save()
        self.application.save()

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_offer_lead_gen(self, mocked_credit_matrix):
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        data = {
            "application_xid": self.application.application_xid
        }
        response = self.client.get(
            '/api/partnership/v1/loan-offer', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(json.loads(response.content)['data']['loan_duration']) > 0)
        self.assertEqual(json.loads(response.content)['data']['selected_amount'],
                         json.loads(response.content)['data']['max_amount'])

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_offer_lead_gen_1(self, mocked_credit_matrix):
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        data = {
            "application_xid": self.application.application_xid,
            "loan_amount_request": 1000
        }
        response = self.client.get(
            '/api/partnership/v1/loan-offer', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(json.loads(response.content)['data']['loan_duration']) == 0)

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_offer_lead_gen_2(self, mocked_credit_matrix):
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        data = {
            "application_xid": self.application.application_xid,
            "loan_amount_request": 300000
        }
        response = self.client.get(
            '/api/partnership/v1/loan-offer', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['data']['selected_amount'] == 300000)
        self.assertTrue(len(json.loads(response.content)['data']['loan_duration']) > 0)

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_offer_paylater_with_invalid_paylater_transaction_xid(self, mocked_credit_matrix):
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        data = {
            "application_xid": self.application.application_xid,
            "paylater_transaction_xid": 56756756757
        }
        partner_name = self.response_register_partner['partner_name']
        partner = Partner.objects.filter(name=partner_name).last()
        partnership_type = partner.partnership_config.partnership_type
        partnership_type.partner_type_name = PartnershipTypeConstant.WHITELABEL_PAYLATER
        partnership_type.save()
        partnership_type.refresh_from_db()
        partner.refresh_from_db()
        response = self.client.get(
            '/api/partnership/v1/loan-offer', data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['paylater_transaction_xid tidak ditemukan'])

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    @mock.patch('juloserver.partnership.views.get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_offer_lead_gen_check_active_account_limit_balance_paylater(
        self,
        mocked_views_credit_matrix: MagicMock,
        mocked_credit_matrix: MagicMock
    ) -> None:
        self.account.status = StatusLookupFactory(status_code=420)
        self.account.save()
        mocked_views_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        data = {
            "application_xid": self.application.application_xid,
            "paylater_transaction_xid": 56756756757
        }

        paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id='900878712',
            transaction_amount=10000001,
            paylater_transaction_xid=data['paylater_transaction_xid'],
            partner=self.partner
        )

        PaylaterTransactionStatusFactory(
            paylater_transaction=paylater_transaction,
            transaction_status=PaylaterTransactionStatuses.IN_PROGRESS
        )

        partner_name = self.response_register_partner['partner_name']
        partner = Partner.objects.filter(name=partner_name).last()
        partnership_type = partner.partnership_config.partnership_type
        partnership_type.partner_type_name = PartnershipTypeConstant.WHITELABEL_PAYLATER
        partnership_type.save()
        partnership_type.refresh_from_db()
        partner.refresh_from_db()

        # Failed insufficient balance
        response = self.client.get(
            '/api/partnership/v1/loan-offer', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Limit Kamu Tidak Mencukupi'])

        # Success
        paylater_transaction.transaction_amount = 500_000
        paylater_transaction.save(update_fields=['transaction_amount'])
        response = self.client.get(
            '/api/partnership/v1/loan-offer', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)

        # Should be using from paylater_transaction.transaction_amount 500_000
        self.assertTrue(json.loads(response.content)['data']['selected_amount'] == 500_000)
        self.assertTrue(len(json.loads(response.content)['data']['loan_duration']) > 0)


class TestPartnerLeadGenLoanDurationRange(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner = register_partner_lead_gen()
        self.partner = Partner.objects.filter(name='partner_lead_gen').last()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner['secret_key'],
            HTTP_USERNAME=response_register_partner['partner_name'],
        )
        self.partnership_type = PartnershipTypeFactory()
        new_julo1_product_line()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.partner_user = AuthUserFactory(username='test_lead_gen_offer')
        self.customer = CustomerFactory(user=self.partner_user)
        status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=status)
        CustomerPinFactory(user=self.partner_user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999887,
            partner=self.partner
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.save()
        self.application.save()
        self.url_range_loan_amount = '/api/partnership/v1/range-loan-amount'
        self.url_loan_duration = '/api/partnership/v1/loan-duration'

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_range_loan_amount_lead_gen(self, mocked_credit_matrix):
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        response = self.client.get(
            '/api/partnership/v1/range-loan-amount/{}'.format(
                self.application.application_xid), data=None)
        self.assertEqual(response.status_code, 200)
        print(response.content)
        self.assertTrue(json.loads(response.content)['data']['min_amount'] > 0)
        self.assertTrue(json.loads(response.content)['data']['max_amount'] > 0)

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_range_loan_amount_lead_gen_1(self, mocked_credit_matrix):
        self.account_limit.available_limit = 10000
        self.account_limit.set_limit = 10000
        self.account_limit.save()
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        response = self.client.get(
            '/api/partnership/v1/range-loan-amount/{}'.format(
                self.application.application_xid))
        self.assertEqual(response.status_code, 200)
        print(response.content)
        self.assertTrue(json.loads(response.content)['data']['min_amount'] == 0)
        self.assertTrue(json.loads(response.content)['data']['max_amount'] == 0)

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_range_loan_amount_lead_gen_2_with_invalid_account_status(self, mocked_credit_matrix):
        self.account.status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended)
        self.account.save()
        self.account_limit.available_limit = 10000
        self.account_limit.set_limit = 10000
        self.account_limit.save()
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        response = self.client.get(
            '{}/{}'.format(self.url_range_loan_amount,
                           self.application.application_xid))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['akun belum dapat mengajukan loan'])

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_duration_lead_gen(self, mocked_credit_matrix):
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        data = {
            "loan_amount_request": 300000
        }
        response = self.client.post(
            '/api/partnership/v1/loan-duration/{}'.format(
                self.application.application_xid), data=data, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(json.loads(response.content)['data']) > 0)

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_duration_lead_gen_1(self, mocked_credit_matrix):
        self.account_limit.available_limit = 10000
        self.account_limit.set_limit = 10000
        self.account_limit.save()
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        data = {
            "loan_amount_request": 300000
        }
        response = self.client.post(
            '/api/partnership/v1/loan-duration/{}'.format(
                self.application.application_xid), data=data, format='json')
        self.assertEqual(response.status_code, 400)

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_duration_lead_gen_with_invalid_account_status(self, mocked_credit_matrix):
        self.account.status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended)
        self.account.save()
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        data = {
            "loan_amount_request": 300000
        }
        response = self.client.post(
            '{}/{}'.format(self.url_loan_duration,
                           self.application.application_xid), data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['akun belum dapat mengajukan loan'])


class TestPartnershipLoanExpectation(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.endpoint = '/api/partnership/web/v1/loan-expectation'
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )
        self.client = APIClient()
        self.loan_expectation_data = dict(
            nik=self.partnership_customer_data.nik,
            loan_amount_request=19000000,
            loan_duration_request=11
        )

    def test_error_without_credentials(self):
        response = self.client.post(
            self.endpoint,
            data=self.loan_expectation_data,
            format='json'
        )
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    def test_error_required(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )

        response = self.client.post(
            self.endpoint,
            data={},
            format='json',
        )
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertIsNone(response.json()['data'])
        self.assertEqual(response.data.get("errors")[0], 'NIK harus diisi')

    def test_success_save_loan_expectation(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )

        response = self.client.post(
            self.endpoint,
            data=self.loan_expectation_data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertIsNotNone(response.json()['data'])


class TestWebviewCheckPartnerStrongPin(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.endpoint = '/api/partnership/web/v1/check-partner-strong-pin'
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner,
            nik='3173051512900241'
        )
        self.partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data
        )
        self.client = APIClient()

    def test_error_without_credentials(self):
        response = self.client.post(self.endpoint, data={})
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    def test_empty_data(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        response = self.client.post(self.endpoint, data={})
        assert response.status_code == HTTPStatus.BAD_REQUEST

        response = self.client.post(self.endpoint, data={
            'nik': 3173051512900041,
            'pin': '111111'
        })
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_pin_is_weakness(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        response = self.client.post(self.endpoint, data={
            'nik': self.partnership_customer_data.nik,
            'pin': '111111'
        })
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_pin_is_same_with_dob(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        response = self.client.post(self.endpoint, data={
            'nik': self.partnership_customer_data.nik,
            'pin': '121590'
        })
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_pin_is_strong(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        response = self.client.post(self.endpoint, data={
            'nik': self.partnership_customer_data.nik,
            'pin': '159357'
        })
        assert response.status_code == HTTPStatus.OK


class TestWebviewCreatePartnerPin(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.endpoint = '/api/partnership/web/v1/create-partner-pin'
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner,
            nik='3173051512900251'
        )
        self.partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data
        )
        self.client = APIClient()

    def test_error_without_credentials(self):
        response = self.client.post(self.endpoint, data={})
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    def test_empty_data(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        response = self.client.post(self.endpoint, data={})
        assert response.status_code == HTTPStatus.BAD_REQUEST

        response = self.client.post(self.endpoint, data={
            'nik': 3173051512900141,
            'pin': '111111'
        })
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_pin_is_weakness(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        response = self.client.post(self.endpoint, data={
            'nik': self.partnership_customer_data.nik,
            'pin': '111111'
        })
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_pin_is_same_with_dob(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        response = self.client.post(self.endpoint, data={
            'nik': self.partnership_customer_data.nik,
            'pin': '121590'
        })
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_pin_is_strong(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        response = self.client.post(self.endpoint, data={
            'nik': self.partnership_customer_data.nik,
            'pin': '159357'
        })
        assert response.status_code == 201

    def test_update_partner_pin(self):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        response = self.client.post(self.endpoint, data={
            'nik': self.partnership_customer_data.nik,
            'pin': '159357'
        })
        assert response.status_code == 201


class TestWebviewVerifyPartnerPin(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, nik=3173051512980141)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=partner
        )
        self.endpoint = '/api/partnership/web/v1/verify-partner-pin'
        workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            product_line=self.product_line,
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))
        self.client = APIClient()

    def test_error_without_credentials(self):
        response = self.client.post(self.endpoint, data={})
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    @mock.patch.object(VerifyPinProcess, 'verify_pin_process')
    def test_verify_partner_pin(self, mock_verify_pin):
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        mock_verify_pin.return_value = ReturnCode.OK, 'success', None
        response = self.client.post(self.endpoint, data={
            'pin': '159357'
        })
        assert response.status_code == HTTPStatus.OK


class TestWebviewLoanOfferView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=partner
        )
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )

        self.partnership_type = PartnershipTypeFactory()
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer,  status=active_status_code)
        now = timezone.localtime(timezone.now())
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999087,
            partner=partner,
            product_line=self.product_line
        )
        self.application.application_status = StatusLookupFactory(
                status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))

        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.save()
        self.application.save()
        self.endpoint = '/api/partnership/web/v1/loan-offer'

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_offer(self, mocked_credit_matrix):
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        response = self.client.get(
            self.endpoint)
        self.assertEqual(response.status_code, HTTPStatus.OK)

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_offer1(self, mocked_credit_matrix):
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        data = {
            "loan_amount_request": 1000
        }
        response = self.client.get(
            self.endpoint, data=data)
        self.assertEqual(response.status_code, HTTPStatus.OK)

    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_loan_offer2(self, mocked_credit_matrix):
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        data = {
            "loan_amount_request": 300000
        }
        response = self.client.get(
            self.endpoint, data=data)
        self.assertEqual(response.status_code, HTTPStatus.OK)


class TestWebviewLoanAgreementView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)

        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)

        self.loan = LoanFactory(account=self.account, customer=self.customer,
                           application=self.application,
                           loan_amount=10000000, loan_xid=1000003456)
        self.application.save()
        self.data = {"data": "NotEmpty", 'upload':
            open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb')}
        self.endpoint_agreement_content = '/api/partnership/web/v1/agreement/content/{}/'.format(
                self.loan.loan_xid)
        self.endpoint_voice_script = '/api/partnership/web/v1/agreement/voice/script/{}/'.format(
                self.loan.loan_xid)
        self.endpoint_voice_upload = '/api/partnership/web/v1/agreement/voice/upload/{}/'.format(
            self.loan.loan_xid)
        self.endpoint_sign_upload = '/api/partnership/web/v1/agreement/signature/upload/{}/'.format(
            self.loan.loan_xid)
        self.endpoint_loan_details = '/api/partnership/web/v1/agreement/loan/{}/'.format(
            self.loan.loan_xid)

    def test_loan_agreement_content_failure(self):
        res = self.client.get(self.endpoint_agreement_content)
        self.assertEqual(res.status_code, HTTPStatus.OK)

    def test_loan_agreement_content_success(self):
        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        self.loan.save()
        res = self.client.get(self.endpoint_agreement_content)
        self.assertEqual(res.status_code, HTTPStatus.OK)

    def test_loan_agreement_voice_script_failure(self):
        res = self.client.get(self.endpoint_voice_script)
        self.assertEqual(res.status_code, HTTPStatus.BAD_REQUEST)

    def test_loan_agreement_voice_script_success(self):
        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        self.loan.save()
        res = self.client.get(self.endpoint_voice_script)
        self.assertEqual(res.status_code, HTTPStatus.OK)

    def test_voice_upload_failure(self):
        res = self.client.post(self.endpoint_voice_upload, data=self.data)
        self.assertEqual(res.status_code, HTTPStatus.BAD_REQUEST)

    def test_voice_upload_success(self):
        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        self.loan.save()
        res = self.client.post(self.endpoint_voice_upload, data=self.data)
        self.assertEqual(res.status_code, HTTPStatus.OK)

    def test_signature_upload_failure(self):
        res = self.client.post(self.endpoint_sign_upload, data=self.data)
        self.assertEqual(res.status_code, HTTPStatus.BAD_REQUEST)

    def test_signature_upload_success(self):
        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        self.loan.save()
        res = self.client.post(self.endpoint_sign_upload, data=self.data)
        self.assertEqual(res.status_code, HTTPStatus.OK)

    def test_loan_agreement_details_failure(self):
        res = self.client.get(self.endpoint_loan_details)
        self.assertEqual(res.status_code, HTTPStatus.BAD_REQUEST)

    def test_loan_agreement_details_success(self):
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.status=active_status_code
        self.account.save()
        res = self.client.get(self.endpoint_loan_details)
        self.assertEqual(res.status_code, HTTPStatus.OK)


class TestWebviewDropdownDataView(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )
        self.client = APIClient()
        self.endpoint = '/api/partnership/web/v1/dropdowns'
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )

    def test_success_get_dropdown_data(self):
        # loan_purposes
        response_loan_purposes = self.client.get(
            "{}?data_selected=loan_purposes".format(self.endpoint),
        )
        self.assertEqual(response_loan_purposes.status_code, HTTPStatus.OK)
        self.assertIsNotNone(response_loan_purposes.json()['data'])
        # home_statuses
        response_home_statuses = self.client.get(
            "{}?data_selected=home_statuses".format(self.endpoint),
        )
        self.assertEqual(response_home_statuses.status_code, HTTPStatus.OK)
        self.assertIsNotNone(response_home_statuses.json()['data'])
        response_banks = self.client.get(
            "{}?data_selected=banks".format(self.endpoint),
        )
        self.assertEqual(response_banks.status_code, HTTPStatus.OK)
        self.assertIsNotNone(response_banks.json()['data'])

    def test_fail_get_jobs_without_job_industries(self):
        response_jobs = self.client.get(
            "{}?data_selected=jobs".format(self.endpoint),
        )
        self.assertEqual(response_jobs.status_code, HTTPStatus.BAD_REQUEST)

    def test_fail_get_jobs_without_job_industries(self):
        response_jobs = self.client.get(
            "{}?data_selected=jobs&job_industry=Admin / Finance / HR".format(self.endpoint),
        )
        self.assertEqual(response_jobs.status_code, HTTPStatus.OK)


class TestWebviewAddressView(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        self.province_lookup = ProvinceLookupFactory(
            province='Jawa barat',
            is_active=True,
        )
        self.city_lookup = CityLookupFactory(
            province=self.province_lookup,
            city='Garut',
            is_active=True
        )
        self.district_lookup = DistrictLookupFactory(
            city=self.city_lookup,
            is_active=True,
            district='Padasuka'
        )
        self.sub_district_lookup = SubDistrictLookupFactory(
            sub_district='Cikajang',
            is_active=True,
            zipcode='43251',
            district=self.district_lookup
        )

    def test_get_address_province(self):
        response = self.client.get('/api/partnership/web/v1/address?address_type=province')
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.province_lookup.province, response.json()['data'])

    def test_get_address_city(self):
        response = self.client.get(
            '/api/partnership/web/v1/address?address_type=city&province={}'.format(
                self.province_lookup.province
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.city_lookup.city, response.json()['data'])

    def test_get_address_district(self):
        response = self.client.get(
            '/api/partnership/web/v1/address?address_type=district&province={}&city={}'.format(
                self.province_lookup.province, self.city_lookup.city
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.district_lookup.district, response.json()['data'])

    def test_get_address_sub_district(self):
        response = self.client.get(
            '/api/partnership/web/v1/address?address_type=sub_district&province={}'
            '&city={}&district={}'.format(
                self.province_lookup.province, self.city_lookup.city, self.district_lookup.district
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sub_district_lookup.sub_district,
                         response.json()['data'][0]['subDistrict'])
        self.assertEqual(self.sub_district_lookup.zipcode,
                         response.json()['data'][0]['zipcode'])


class TestWebviewImageView(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )
        self.partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        self.endpoint = '/api/partnership/web/v1/images'

    def test_success_get_image(self):
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)


class TestWebviewSubmitApplicationView(TestCase):
    BASE_PATH = 'juloserver.partnership.tasks.'
    BASE_NOTIFY_EMAIL_MOCK = BASE_PATH + 'notify_user_to_check_submission_status.delay'
    def create_fresh_data_until_registration_form(
        self, with_application=False, with_partnership_application=True,
        application_status=None, with_image=True, can_reapply=True
    ):
        new_user = AuthUserFactory()
        new_customer = CustomerFactory(user=new_user)
        new_partnership_customer_data = PartnershipCustomerDataFactory(
            customer=new_customer,
            partner=self.partner
        )
        if with_application:
            new_application = ApplicationFactory(
                customer=new_customer,
                workflow=self.workflow,
                partner=self.partner
            )
            new_customer.nik = new_partnership_customer_data.nik
            new_application.ktp = new_partnership_customer_data.nik
            if application_status == 100:
                new_application.application_status = StatusLookupFactory(status_code=100)
                new_customer.can_reapply = can_reapply
                CustomerPinFactory(user=new_user)
                new_user.password = 'pbkdf2_sha256$24000$f0pBJkFVkJrU$c2LUOxLcdb7qQdlqLEveyZr28no1U/S9VhJgkaS581c='
                new_user.save()

            new_customer.save()
            new_application.save()


        if with_partnership_application:
            new_partnership_application_data_fresh = PartnershipApplicationDataFactory(
                partnership_customer_data=new_partnership_customer_data,
                encoded_pin='Z0FBQUFBQmlNRTdndUltaVJfMDI3R1g5b1cxQThFcmdVT256bXdsQkVmWjczSV9XZnNDWUdjQW5vZHdCLXJuN2gzTHZ1M3EyRWctMEFWa1NpY0Z4QUdDOWt5d1RqSnBZU3c9PQ=='
            )
            if with_image:
                ImageFactory(
                    image_type='selfie_partnership',
                    image_source=-abs(new_partnership_application_data_fresh.id + 510)
                )
                ImageFactory(
                    image_type='ktp_self_partnership',
                    image_source=-abs(new_partnership_application_data_fresh.id + 510)
                )
                ImageFactory(
                    image_type='crop_selfie_partnership',
                    image_source=-abs(new_partnership_application_data_fresh.id + 510)
                )
        return new_user, new_partnership_customer_data.token

    def setUp(self):
        self.user = AuthUserFactory()
        customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(user=self.user, is_active=True)
        self.partnership_type = PartnershipTypeFactory(
            partner_type_name=PartnershipTypeConstant.LEAD_GEN
        )
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30]
        )
        self.province_lookup = ProvinceLookupFactory(
            province='Jawa barat',
            is_active=True,
        )
        self.city_lookup = CityLookupFactory(
            province=self.province_lookup,
            city='Garut',
            is_active=True
        )
        self.district_lookup = DistrictLookupFactory(
            city=self.city_lookup,
            is_active=True,
            district='Padasuka'
        )
        self.sub_district_lookup = SubDistrictLookupFactory(
            sub_district='Cikajang',
            is_active=True,
            zipcode='43251',
            district=self.district_lookup
        )
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        ProductLineFactory(product_line_code=ProductLineCodes.J1)
        WorkflowStatusPathFactory(
            status_previous=0, status_next=105, type='happy', is_active=True,
            workflow=self.workflow,
        )
        WorkflowStatusPathFactory(
            status_previous=100, status_next=105, type='happy', is_active=True,
            workflow=self.workflow,
        )

        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=self.partner
        )
        self.partnership_application_data_fresh = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data,
            encoded_pin='Z0FBQUFBQmlNRTdndUltaVJfMDI3R1g5b1cxQThFcmdVT256bXdsQkVmWjczSV9XZnNDWUdjQW5vZHdCLXJuN2gzTHZ1M3EyRWctMEFWa1NpY0Z4QUdDOWt5d1RqSnBZU3c9PQ=='
        )
        ImageFactory(
            image_type='selfie_partnership',
            image_source=-abs(self.partnership_application_data_fresh.id + 510)
        )
        ImageFactory(
            image_type='ktp_self_partnership',
            image_source=-abs(self.partnership_application_data_fresh.id + 510)
        )
        ImageFactory(
            image_type='crop_selfie_partnership',
            image_source=-abs(self.partnership_application_data_fresh.id + 510)
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        self.endpoint = '/api/partnership/web/v1/submit'
        self.request_data = {
            "fullname": "Prod Only",
            "birth_place": "Jakarta",
            "dob": "1996-11-01",
            "gender": "Pria",
            "mother_maiden_name": "nama ibu",
            "address_street_num": "JL. Pasar Minggu Raya",
            "address_provinsi": self.province_lookup.province,
            "address_kabupaten": self.city_lookup.city,
            "address_kecamatan": self.district_lookup.district,
            "address_kelurahan": self.sub_district_lookup.sub_district,
            "address_kodepos": self.sub_district_lookup.zipcode,
            "home_status": "Milik sendiri, lunas",
            "marital_status": "Lajang",
            "dependent": "0",
            "mobile_phone_1": str(self.partnership_customer_data.phone_number),
            "mobile_phone_2": "082123786543",
            "occupied_since": "1996-11-01",
            "spouse_name": "test test",
            "spouse_mobile_phone": "082123466105",
            "close_kin_name": "ibu7",
            "close_kin_mobile_phone": "082123466104",
            "kin_relationship": "Orang tua",
            "kin_mobile_phone": "087778231804",
            "kin_name": "Lawage Nugroho7",
            "job_type": "Pegawai negeri",
            "job_industry": "Admin / Finance / HR",
            "job_description": "HR",
            "company_name": "DBS Bank",
            "company_phone_number": "0253653322223",
            "job_start": "2019-07-01",
            "payday": "1",
            "last_education": "S3",
            "monthly_income": 10000000,
            "monthly_expenses": 2000000,
            "monthly_housing_cost": 0,
            "total_current_debt": 0,
            "bank_name": "BANK CENTRAL ASIA, Tbk (BCA)",
            "bank_account_number": "0672272764",
            "loan_purpose": "Membayar hutang lainnya",
            "loan_purpose_desc": "Untuk memulihkan Cash Flow saya 2 bulan. Untuk memulihkan Cash Flow saya 2 bulan",
            "is_term_accepted": True,
            "is_verification_agreed": True,
            "address_same_as_ktp": True,
        }

    @mock.patch('juloserver.julo.services.process_application_status_change')
    def test_success_submit_fresh_customer(self, mock_process_application_status_change):
        request_data = self.request_data
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)
        application = Application.objects.get(id=response.json()['data']['application_id'])

        # payday should be 4
        self.assertEqual(str(application.payday), request_data['payday'])

    @mock.patch('juloserver.julo.services.process_application_status_change')
    def test_success_submit_fresh_customer_check_payday(self,
                                                        _: MagicMock) -> None:

        # Set payday none and job type Pegawai negeri
        request_data = self.request_data
        request_data['payday'] = None
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()['errors'], ['Payday data tidak valid'])

        request_data['job_type'] = 'Ibu rumah tangga'
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        application = Application.objects.get(id=response.json()['data']['application_id'])

        # payday should be 1
        self.assertEqual(application.payday, 1)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_submit_existing_105_customer(self, mock_process_application_status_change):
        user_105 = AuthUserFactory()
        customer_105 = CustomerFactory(user=user_105)
        application_105 = ApplicationFactory(
            customer=customer_105,
            workflow=self.workflow,
            partner=self.partner
        )
        partnership_customer_data_105 = PartnershipCustomerDataFactory(
            customer=customer_105,
            partner=self.partner
        )
        customer_105.nik = partnership_customer_data_105.nik
        customer_105.save()
        application_105.ktp = partnership_customer_data_105.nik
        application_105.save()
        partnership_application_data_105 = PartnershipApplicationDataFactory(
            partnership_customer_data=partnership_customer_data_105,
            encoded_pin='Z0FBQUFBQmlNRTdndUltaVJfMDI3R1g5b1cxQThFcmdVT256bXdsQkVmWjczSV9XZnNDWUdjQW5vZHdCLXJuN2gzTHZ1M3EyRWctMEFWa1NpY0Z4QUdDOWt5d1RqSnBZU3c9PQ=='
        )
        ImageFactory(
            image_type='selfie_partnership',
            image_source=-abs(partnership_application_data_105.id + 510)
        )
        ImageFactory(
            image_type='ktp_self_partnership',
            image_source=-abs(partnership_application_data_105.id + 510)
        )
        ImageFactory(
            image_type='crop_selfie_partnership',
            image_source=-abs(partnership_application_data_105.id + 510)
        )

        self.client = APIClient()
        self.client.force_authenticate(user=user_105)
        self.client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data_105.token,
            HTTP_USERNAME="linkaja"
        )
        request_data = self.request_data
        self.request_data['pin'] = '159357'
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)
        expected_105_message = {
            'application_id': None,
            'expiry_token': None,
            'message': 'Customer dan aplikasi sudah ada dengan status aplikasi: FORM_NOT_CREATED',
            'redirect_to_page': 'j1_verification_page'
        }

        self.assertDictEqual(response.json()['data'] ,expected_105_message)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_failed_because_mobile_phone_1_is_different(self, mock_process_application_status_change):
        user, token = self.create_fresh_data_until_registration_form()
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.client.credentials(
            HTTP_SECRET_KEY=token,
            HTTP_USERNAME="linkaja"
        )

        request_data = self.request_data
        request_data['mobile_phone_1'] = '082112341234'
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_failed_because_mandatory_field_is_null(self, mock_process_application_status_change):
        user, token = self.create_fresh_data_until_registration_form()
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.client.credentials(
            HTTP_SECRET_KEY=token,
            HTTP_USERNAME="linkaja"
        )

        request_data = self.request_data
        del request_data['fullname']
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_failed_100_reapply_customer_without_pin(self, mock_process_application_status_change):
        user, token = self.create_fresh_data_until_registration_form(with_application=True, application_status=100)
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.client.credentials(
            HTTP_SECRET_KEY=token,
            HTTP_USERNAME="linkaja"
        )
        request_data = self.request_data
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        expected_response = {'success': False, 'data': None, 'errors': ['Pin Harus Diisi']}
        self.assertDictEqual(response.json(), expected_response)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_failed_100_reapply_customer_wrong_pin(self, mock_process_application_status_change):
        user, token = self.create_fresh_data_until_registration_form(with_application=True, application_status=100)
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.client.credentials(
            HTTP_SECRET_KEY=token,
            HTTP_USERNAME="linkaja"
        )
        request_data = self.request_data
        request_data['pin'] = '123456'
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        expected_response = {
            'data': None, 'errors': [
                'Email, NIK, Nomor Telepon, PIN, atau Kata Sandi kamu salah'
            ], 'success': False
        }
        self.assertDictEqual(response.json(), expected_response)
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)

    @pytest.mark.skip(reason="Flaky")
    @patch(BASE_NOTIFY_EMAIL_MOCK)
    @patch('juloserver.julo.services.process_application_status_change')
    def test_success_100_reapply_customer(self, _: MagicMock,
                                          notif_email_mock: MagicMock):
        user, token = self.create_fresh_data_until_registration_form(with_application=True, application_status=100)
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.client.credentials(
            HTTP_SECRET_KEY=token,
            HTTP_USERNAME="linkaja"
        )
        request_data = self.request_data
        request_data['pin'] = '159357'
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)

        # Email sended to user (Need upload several document)
        self.assertEqual(notif_email_mock.call_count, 1)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_failed_without_partnership_application(self, mock_process_application_status_change):
        user, token = self.create_fresh_data_until_registration_form(
            with_application=True, application_status=100, with_partnership_application=False)
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.client.credentials(
            HTTP_SECRET_KEY=token,
            HTTP_USERNAME="linkaja"
        )
        request_data = self.request_data
        request_data['pin'] = '159357'
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        expected_response = {'success': False, 'data': None, 'errors': ['Partnership Application Data tidak ditemukan']}
        self.assertDictEqual(response.json(), expected_response)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_failed_without_image(self, mock_process_application_status_change):
        user, token = self.create_fresh_data_until_registration_form(
            with_application=True, with_image=False)
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.client.credentials(
            HTTP_SECRET_KEY=token,
            HTTP_USERNAME="linkaja"
        )
        request_data = self.request_data
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        expected_response = {'success': False, 'data': None, 'errors': ['images ktp_self_partnership, crop_selfie_partnership and selfie_partnership is required']}
        self.assertDictEqual(response.json(), expected_response)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_failed_wrong_authorization(self, mock_process_application_status_change):
        user, token = self.create_fresh_data_until_registration_form()
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.client.credentials(
            HTTP_SECRET_KEY='asdasdasdasd',
            HTTP_USERNAME="linkaja"
        )
        request_data = self.request_data
        response = self.client.patch(
            self.endpoint,
            data=request_data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)



class TestWebviewLoanView(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer_pin = CustomerPinFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=partner
        )
        product_line = ProductLineFactory(product_line_code=1)
        self.partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data
        )
        self.account = AccountFactory(customer=self.customer)
        self.account.status = StatusLookupFactory(status_code=420)
        self.account.save()
        self.account_property = AccountPropertyFactory(account=self.account, concurrency=True, is_proven=True)
        workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            partner=partner,
            product_line=product_line,
            workflow=workflow
        )
        self.application.application_status = StatusLookupFactory(status_code=190)
        self.application.save()

        partner_id = partner.id
        self.partnership_session_information = PartnershipSessionInformationFactory(
            partner_id=partner_id
        )
        self.partnership_session_information.phone_number = self.partnership_customer_data.phone_number
        self.partnership_session_information.session_id = '01EA1PTFKAQMFJEQR999XWZHVW'
        self.partnership_session_information.customer_token = '01FY8AZE0Q2DYBX1R32TYC390Z'
        self.partnership_session_information.save()

        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.max_loan_amount = 10000000
        self.credit_matrix_product_line.save()

        self.partnership_type = PartnershipTypeFactory()
        self.partnership_config = PartnershipConfigFactory(
            partner=partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30]
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION=self.user.auth_expiry_token.key,
            HTTP_USERNAME="linkaja"
        )
        self.endpoint = '/api/partnership/web/v1/loan'

    @pytest.mark.skip(reason="Flaky")
    @patch('juloserver.partnership.views.get_count_request_on_redis')
    @patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.partnership.clients.clients.LinkAjaClient.cash_in_inquiry')
    def test_success_create_loan(
        self, mock_cashin_inquiry, mocked_credit_matrix, mock_get_count_request_on_redis
    ):
        expiry_time = timezone.now() + timedelta(days=1)
        CustomerPinVerify.objects.create(
            customer=self.application.customer,
            is_pin_used=False,
            customer_pin=self.customer_pin,
            expiry_time=expiry_time
        )
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        mock_cashin_inquiry.return_value.status_code = 200
        mock_cashin_inquiry.return_value.content = '{"responseCode": "00", "responseMessage": "Success", "custName": "RIFKY RADITYATAMA", "msisdn": "6285217296020", "amount": "300000", "cashInLimit": "8193514", "merchantTrxID": "10000724130161", "sessionID": "PD5I590f8e38e26a4ad09f89ee5557ed8f25"}'
        mock_get_count_request_on_redis.return_value = 0, ''
        request_data = {
            "application_id": self.application.id,
            "loan_amount_request": 300000,
            "loan_duration": 3,
            "loan_purpose": "Modal usaha"
        }
        response = self.client.post(self.endpoint, data=request_data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.OK)

    @patch('juloserver.partnership.views.get_count_request_on_redis')
    @patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.partnership.clients.clients.LinkAjaClient.cash_in_inquiry')
    def test_failed_create_loan_exceed_limit(
        self, mock_cashin_inquiry, mocked_credit_matrix, mock_get_count_request_on_redis
    ):
        expiry_time = timezone.now() + timedelta(days=1)
        CustomerPinVerify.objects.create(
            customer=self.application.customer,
            is_pin_used=False,
            customer_pin=self.customer_pin,
            expiry_time=expiry_time
        )
        request_data = {
            "application_id": self.application.id,
            "loan_amount_request": 3000000000,
            "loan_duration": 3,
            "loan_purpose": "Modal usaha"
        }
        mock_get_count_request_on_redis.return_value = 0, ''
        response = self.client.post(self.endpoint, data=request_data, format='json')
        expected_response = {'success': False, 'data': None, 'errors': ['Limit kamu tidak mencukupi untuk pinjaman ini']}
        self.assertDictEqual(response.json(), expected_response)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.partnership.views.get_count_request_on_redis')
    @patch('juloserver.partnership.clients.clients.LinkAjaClient.cash_in_inquiry')
    def test_failed_create_invalid_loan_duration(
        self, mock_cashin_inquiry, mock_get_count_request_on_redis, mocked_credit_matrix
    ):
        expiry_time = timezone.now() + timedelta(days=1)
        CustomerPinVerify.objects.create(
            customer=self.application.customer,
            is_pin_used=False,
            customer_pin=self.customer_pin,
            expiry_time=expiry_time
        )
        mock_get_count_request_on_redis.return_value = 0, ''
        request_data = {
            "application_id": self.application.id,
            "loan_amount_request": 300000,
            "loan_duration": 100,
            "loan_purpose": "Modal usaha"
        }
        response = self.client.post(self.endpoint, data=request_data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    @patch('juloserver.partnership.services.services.'
           'get_credit_matrix_and_credit_matrix_product_line')
    @patch('juloserver.partnership.views.get_count_request_on_redis')
    @patch('juloserver.partnership.clients.clients.LinkAjaClient.cash_in_inquiry')
    def test_failed_create_loan_for_beyond_max_threshold(
            self, mock_cashin_inquiry, mock_get_count_request_on_redis, mocked_credit_matrix
    ):
        expiry_time = timezone.now() + timedelta(days=1)
        CustomerPinVerify.objects.create(
            customer=self.application.customer,
            is_pin_used=False,
            customer_pin=self.customer_pin,
            expiry_time=expiry_time
        )
        self.account_limit.available_limit = 20000000
        self.account_limit.set_limit = 20000000
        self.account_limit.save()
        mock_get_count_request_on_redis.return_value = 0, ''
        request_data = {
            "application_id": self.application.id,
            "loan_amount_request": 10000004,
            "loan_duration": 100,
            "loan_purpose": "Modal usaha"
        }
        response = self.client.post(self.endpoint, data=request_data, format='json')
        expected_response = {'success': False, 'data': None,
                             'errors': [ErrorMessageConst.LOWER_THAN_MAX_THRESHOLD_LINKAJA]}
        self.assertDictEqual(response.json(), expected_response)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)


class TestWebviewApplicationStatus(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.endpoint = '/api/partnership/web/v1/application/status'

    def test_application_not_found(self) -> None:
        # Update none workflow on application
        self.application.workflow = None
        self.application.save(update_fields=['workflow'])
        response = self.client.get(self.endpoint)

        # return 400 bad request
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'], ['Aplikasi tidak ditemukan'])

    def test_application_status_success(self) -> None:
        response = self.client.get(self.endpoint)

        # return 200 success
        self.assertEqual(response.json()['success'], True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        json_response = response.json()['data']
        self.assertEqual(json_response['application_id'], self.application.id)
        self.assertEqual(json_response['application_xid'], self.application.application_xid)
        self.assertEqual(json_response['application_status_code'],
                         self.application.application_status_id)


class TestPartnershipCreditInfoView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user2 = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer2 = CustomerFactory(user=self.user2)
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="limit_card_call_to_action",
            is_active=True,
            parameters={
                'bottom_left': {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "product_transfer_self"
                },
                "bottom_right": {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "aktivitaspinjaman"
                }
            }
        )
        self.partner = PartnerFactory(
            user=self.user, is_active=True,
            name=PartnerNameConstant.LINKAJA
        )
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=self.partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            status=ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.credit_score = CreditScoreFactory(application_id=self.application.id,
                                               score='B-')
        self.account_property = AccountPropertyFactory(account=self.account, is_proven=True)
        self.endpoint = '/api/partnership/web/v1/credit-info'

    @mock.patch('django.utils.timezone.localtime')
    def test_get_application_not_found(self, _: MagicMock) -> None:
        self.application.customer = self.customer2
        self.application.save(update_fields=['customer'])
        self.application.refresh_from_db()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        result = response.__dict__['data']
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['Application Not Found'])

    @mock.patch('django.utils.timezone.localtime')
    def test_get_credit_info_fail_error_exception(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
        ]
        self.mobile_feature_setting.delete()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(response.json()['success'], False)

    @mock.patch('django.utils.timezone.localtime')
    def test_get_credit_info_success(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
        ]
        response = self.client.get(self.endpoint)
        result = response.__dict__['data']
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(result['success'], True)

        credit_info = result['data']['creditInfo']
        self.assertEqual(credit_info['fullname'], self.customer.fullname)
        self.assertEqual(credit_info['is_proven'], self.account_property.is_proven)

    @mock.patch('django.utils.timezone.localtime')
    def test_credit_limit_on_delay(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
            datetime_now,
            datetime_now
        ]
        now = timezone.localtime(timezone.now())
        two_hours_ago = now - timedelta(hours=2)
        minutes = two_hours_ago.strftime('%M')
        hours = two_hours_ago.strftime('%H')
        format_hours = '%s:%s' % (hours, minutes)
        self.feature_setting = FeatureSettingFactory()
        self.feature_setting.feature_name = FeatureNameConst.DELAY_C_SCORING
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {
            'hours': format_hours,
            'exact_time': True
        }
        self.feature_setting.save()

        # Denied
        self.application.application_status = StatusLookupFactory(
            status_code=135
        )
        self.application.save(update_fields=['application_status'])
        self.rejected_customer = self.application.customer
        self.rejected_application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=0,
            status_new=105
        )
        one_days = now + relativedelta(days=1)
        self.rejected_application_history.cdate = one_days
        self.rejected_application_history.save()

        # Pending
        self.application.application_status = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL)
        self.application.save(update_fields=['application_status'])

        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.__dict__['data']['data']['creditInfo']['limit_message'], 'Pengajuan kredit JULO sedang dalam proses')
        self.assertEqual(response.__dict__['data']['data']['creditInfo']['account_state'], 310)

    @mock.patch('django.utils.timezone.localtime')
    def test_credit_limit_c(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
        ]
        self.credit_score.score = 'C'
        self.credit_score.save()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.__dict__['data']['success'], True)
        self.assertEqual(response.__dict__['data']['data']['creditInfo']['credit_score'], 'C')

        product = response.__dict__['data']['data']['product']
        self.assertNotEqual(len(product), 1)

    @mock.patch('django.utils.timezone.localtime')
    def test_credit_limit_gt_c(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
        ]
        self.credit_score.score = 'B'
        self.credit_score.save()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        transaction_methods = TransactionMethod.objects.all().order_by('order_number')[:7]

        # adding 1 because in response added 1 more product hardcoded TransactionMethodCode.ALL_PRODUCT
        self.assertEqual(len(transaction_methods) + 1,
                         len(response.__dict__['data']['data']['product']))
        self.assertEqual(response.__dict__['data']['data']['product'][0]['name'],
                         transaction_methods[0].fe_display_name)
        self.assertEqual(response.__dict__['data']['data']['product'][0]['code'],
                         transaction_methods[0].id)


class TestPartnershipImageListCreateView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.credit_score = CreditScoreFactory()
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="limit_card_call_to_action"
        )
        self.partner = PartnerFactory(
            user=self.user, is_active=True,
            name=PartnerNameConstant.LINKAJA
        )
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=self.partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            status=ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.account_property = AccountPropertyFactory(account=self.account, is_proven=True)
        self.endpoint = '/api/partnership/web/v1/images/'

    def test_upload_not_in_request(self) -> None:
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_type_not_in_request(self) -> None:
        data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_type_not_in_request(self) -> None:
        data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_create_image_source(self) -> None:
        data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
            'image_source': 1111111111
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_image_existing(self) -> None:
        data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
            'image_source': 2000000001,
        }

        # Application not found
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.application2 = ApplicationFactory(
            id=2000000001,
            customer=self.customer,
            status=ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )

        # Application Found
        self.image = ImageFactory(image_source=self.application2.id,
                                  image_type='selfie')

        # Success
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class TestPartnershipCombinedHomeScreen(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.loan = LoanFactory(application=self.application)
        self.voice_record = VoiceRecordFactory()
        self.customer_wallet_history = CustomerWalletHistoryFactory()
        self.endpoint = '/api/partnership/web/v1/homescreen/combined'

    @patch('juloserver.apiv2.views.is_bank_name_validated')
    @patch('juloserver.apiv2.views.get_referral_home_content')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.ProductLineSerializer')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_customer_app_actions')
    @patch('juloserver.apiv2.views.render_loan_sell_off_card')
    @patch('juloserver.apiv2.views.render_sphp_card')
    @patch('juloserver.apiv2.views.render_season_card')
    @patch('juloserver.apiv2.views.render_campaign_card')
    @patch('juloserver.apiv2.views.render_account_summary_cards')
    def test_partnership_combined_home_screen(self, mock_render_account_summary_cards: MagicMock,
                                              mock_render_campaign_card: MagicMock,
                                              mock_render_season_card: MagicMock,
                                              mock_render_sphp_card: MagicMock,
                                              mock_render_loan_sell_off_card: MagicMock,
                                              mock_get_customer_app_actions: MagicMock,
                                              mock_get_product_lines: MagicMock,
                                              mock_update_response_false_rejection: MagicMock,
                                              mock_check_fraud_model_exp: MagicMock,
                                              mock_ProductLineSerializer: MagicMock,
                                              mock_update_response_fraud_experiment: MagicMock,
                                              mock_get_referral_home_content: MagicMock,
                                              mock_is_bank_name_validated:MagicMock) -> None:

        data = {
            'application_id': self.application.id,
            'app_version': '2.2.2',
        }
        self.loan.application = self.application
        self.loan.loan_status_id = 260
        self.loan.save()

        self.application.application_status_id = 150
        self.application.save()

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.save()

        self.voice_record.application = self.application
        self.voice_record.save()

        mock_render_account_summary_cards.return_value = ['']
        mock_is_bank_name_validated.return_value = False
        mock_get_customer_app_actions.return_value = 'mock_customer_action'
        mock_update_response_fraud_experiment.return_value = 'TestCombinedHomeScreenAPIv2'
        mock_get_referral_home_content.return_value = (True,'test_referral_content')

        response = self.client.get(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestPartnershipSubmitDocumentCompleteView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user2 = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer2 = CustomerFactory(user=self.user2)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.face_recognition = FaceRecognitionFactory()
        self.application_history = ApplicationHistoryFactory(application_id=self.application.id)
        self.application2 = ApplicationFactory(
            customer=self.customer2,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        WorkflowStatusPathFactory(
            status_previous=0, status_next=105, type='happy', is_active=True,
            workflow=self.workflow,
        )
        WorkflowStatusPathFactory(
            status_previous=100, status_next=105, type='happy', is_active=True,
            workflow=self.workflow,
        )
        WorkflowStatusPathFactory(
            status_previous=105, status_next=120, type='happy', is_active=True,
            workflow=self.workflow,
        )
        self.loan = LoanFactory(application=self.application)
        self.voice_record = VoiceRecordFactory()
        self.customer_wallet_history = CustomerWalletHistoryFactory()
        self.endpoint = '/api/partnership/web/v1/submit-document-flag/{}/'.format(self.application.id)

    def test_submit_document_application_not_found(self)-> None:
        self.endpoint = '/api/partnership/web/v1/submit-document-flag/9999999/'
        response = self.client.put(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_submit_document_forbidden(self)-> None:
        self.endpoint = '/api/partnership/web/v1/submit-document-flag/{}/'.format(self.application2.id)
        response = self.client.put(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['errors'], 'User not allowed')

    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_submit_document_success(self, _: MagicMock)-> None:
        data = {
            'is_document_submitted': True,
            'is_sphp_signed': True
        }

        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.save(update_fields=['application_status_id'])
        self.application.product_line = self.product_line
        self.application.save(update_fields=['product_line'])

        response = self.client.put(self.endpoint, data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['content']['application']['status'],
                         ApplicationStatusCodes.FORM_PARTIAL)
        self.assertEqual(response.json()['content']['application']['product_line'],
                         ProductLineCodes.J1)

    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_submit_document_on_status_face_recognition_after_resubmit(self, _: MagicMock) -> None:
        data = {
            'is_document_submitted': True,
            'is_sphp_signed': True
        }

        resubmission_status = ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
        self.application.application_status_id = resubmission_status
        self.application.save(update_fields=['application_status_id'])
        self.application.product_line = self.product_line
        self.application.save(update_fields=['product_line'])

        face_recognition_status = ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT
        self.application_history.status_old = face_recognition_status
        self.application_history.status_new = resubmission_status
        self.application_history.change_reason = 'failed upload selfie image'
        self.application_history.save(update_fields=['change_reason', 'status_old', 'status_new'])

        self.face_recognition.feature_name = 'face_recognition'
        self.face_recognition.is_active = True
        self.face_recognition.save(update_fields=['feature_name', 'is_active'])
        response = self.client.put(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['content']['application']['status'], resubmission_status)

    @patch('juloserver.apiv2.views.get_customer_service')
    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_submit_document_on_status_131_resubmission_request(
            self, mock_customer_service: MagicMock, _: MagicMock
        ) -> None:
        data = {
            'is_document_submitted': True,
            'is_sphp_signed': True
        }

        resubmission_status = ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
        self.application.application_status_id = resubmission_status
        self.application.save(update_fields=['application_status_id'])
        self.application.product_line = self.product_line
        self.application.save(update_fields=['product_line'])

        self.application_history.status_old = ApplicationStatusCodes.DOCUMENTS_SUBMITTED
        self.application_history.status_new = resubmission_status
        self.application_history.change_reason = 'failed upload selfie image'
        self.application_history.save(update_fields=['change_reason', 'status_new', 'status_old'])

        mock_res_bypass = {
            'new_status_code': 123,
            'change_reason': 'test change_reason bypass'
        }

        mock_customer_service.return_value.do_high_score_full_bypass_or_iti_bypass.return_value = mock_res_bypass
        response = self.client.put(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['content']['application']['status'], resubmission_status)

    @patch('juloserver.apiv2.views.get_customer_service')
    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_submit_document_on_status_132_resubmitted(
            self, mock_customer_service: MagicMock, _: MagicMock
        ) -> None:
        data = {
            'is_document_submitted': True,
            'is_sphp_signed': True
        }

        resubmission_status = ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
        self.application.application_status_id = resubmission_status
        self.application.save(update_fields=['application_status_id'])
        self.application.product_line = self.product_line
        self.application.save(update_fields=['product_line'])

        resubmitted = ApplicationStatusCodes.APPLICATION_RESUBMITTED
        self.application_history.status_old = resubmitted
        self.application_history.status_new = resubmission_status
        self.application_history.change_reason = 'failed upload selfie image'
        self.application_history.save(update_fields=['change_reason', 'status_old', 'status_new'])

        mock_res_bypass = {
            'new_status_code': 123,
            'change_reason': 'test change_reason bypass'
        }

        mock_customer_service.return_value.do_high_score_full_bypass_or_iti_bypass.return_value = mock_res_bypass

        response = self.client.put(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['content']['application']['status'], resubmission_status)


class TestPartnershipBoostStatusView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user2 = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer2 = CustomerFactory(user=self.user2)
        self.partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=self.partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="boost"
        )
        self.mobile_feature_setting.parameters = {
            'bank': {
                'is_active': True,
            },
            'bpjs': {
                'is_active': False
            }
        }
        self.bpjs_task = BpjsTaskFactory()
        self.mobile_feature_setting.save()
        self.forbidden_application = ApplicationFactory(
            customer=self.customer2,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.endpoint = '/api/partnership/web/v1/booster/status/{}/'.format(self.application.id)

    def test_get_partnership_boost_status_application_not_found(self) -> None:
        self.endpoint = '/api/partnership/web/v1/booster/status/9999999/'
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_get_partnership_boost_forbidden(self) -> None:
        self.endpoint = '/api/partnership/web/v1/booster/status/{}/'.format(self.forbidden_application.id)
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['success'], False)

    @patch('juloserver.boost.services.get_boost_status')
    @patch('juloserver.boost.clients.JuloScraperClient.get_bank_scraping_status')
    @patch('juloserver.application_flow.tasks.fraud_bpjs_or_bank_scrape_checking')
    def test_get_partnership_boost_success(self, _: MagicMock,
                                           bank_scraping_status: MagicMock,
                                           fraud_bpjs_mock: MagicMock) -> None:
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestPartnershipBoostStatusAtHomepageView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user2 = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer2 = CustomerFactory(user=self.user2)
        self.partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=self.partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="boost"
        )
        self.mobile_feature_setting.parameters = {
            'bank': {
                'is_active': True,
            },
            'bpjs': {
                'is_active': False
            }
        }
        self.bpjs_task = BpjsTaskFactory()
        self.mobile_feature_setting.save()
        self.forbidden_application = ApplicationFactory(
            customer=self.customer2,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.endpoint = '/api/partnership/web/v1/booster/document-status/{}/'.format(self.application.id)

    def test_document_status_partnership_boost_status_application_not_found(self) -> None:
        self.endpoint = '/api/partnership/web/v1/booster/document-status/99999999/'
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_document_status_partnership_boost_status_application_forbidden(self) -> None:
        self.endpoint = '/api/partnership/web/v1/booster/status/{}/'.format(self.forbidden_application.id)
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['success'], False)

    @patch('juloserver.boost.services.get_boost_status')
    @patch('juloserver.boost.clients.JuloScraperClient.get_bank_scraping_status')
    @patch('juloserver.application_flow.tasks.fraud_bpjs_or_bank_scrape_checking')
    def test_document_status_partnership_boost_status_application_success(self, _: MagicMock,
                                                                          bank_scraping_status: MagicMock,
                                                                          fraud_bpjs_mock: MagicMock) -> None:
        self.credit_score = CreditScoreFactory(application_id=self.application.id)
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()

        self.assertEqual(result['success'], True)
        bank_status = result['data']['bank_status']

        self.assertEqual(bank_status['enable'], True)
        bpjs_status = result['data']['bpjs_status']
        self.assertEqual(bpjs_status['enable'], False)

        credit_score = result['data']['credit_score']
        self.assertEqual(credit_score['score'], self.credit_score.score)
        self.assertEqual(credit_score['is_high_c_score'], False)


class TestMerchantRegistrationView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        response_register_partner_mf = register_partner_merchant_financing()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner_mf['secret_key'],
            HTTP_USERNAME=response_register_partner_mf['partner_name'],
        )
        self.endpoint = '/api/partnership/v1/merchants'
        partner = Partner.objects.first()
        self.distributor = DistributorFactory(
            partner=partner,
            user=partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor a',
            address='jakarta',
            email='testdistributora@gmail.com',
            phone_number='08123152321',
            type_of_business='warung',
            npwp='123040410292312',
            nib='223040410292312',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=123456,
        )

    def test_fail_get_merchants_due_to_not_found(self):
        partner = PartnerFactory(
            user=self.user,
            is_active=True
        )
        self.distributor = DistributorFactory(
            partner=partner,
            user=partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor a',
            address='jakarta',
            email='testdistributora@gmail.com',
            phone_number='08123152321',
            type_of_business='warung',
            npwp='123040410292312',
            nib='223040410292312',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=123456,
        )
        response = self.client.get(
            self.endpoint
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNotNone(response.json()['errors'])
        self.assertEqual(response.json()['errors'], ['Merchant tidak ditemukan'])

    def test_success_get_merchants(self):
        data = dict(
            nik='3203020101910011',
            shop_name='merchant',
            distributor_xid=int(self.distributor.distributor_xid)
        )
        test_create = self.client.post(
            self.endpoint,
            data=data,
            format='json'
        )

        response = self.client.get(
            self.endpoint
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()['data'])

        # Get method Log not Stored
        api_logs = PartnershipApiLog.objects.filter(partner=self.distributor.partner)
        self.assertTrue(api_logs)
        self.assertTrue(api_logs.count(), 0)

    def test_success_post_merchants(self):
        data = dict(
            nik='3203020101910012',
            shop_name='merchant',
            distributor_xid=int(self.distributor.distributor_xid)
        )

        response = self.client.post(
            self.endpoint,
            data=data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Log Stored
        api_logs = PartnershipApiLog.objects.filter(partner=self.distributor.partner)
        self.assertTrue(api_logs)
        self.assertTrue(api_logs.count(), 1)

    def test_fail_post_merchant_due_to_null_nik(self):
        data = dict(
            shop_name='merchant',
            distributor_xid=int(self.distributor.distributor_xid)
        )

        response = self.client.post(
            self.endpoint,
            data=data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNotNone(response.json()['errors'])
        self.assertEqual(response.json()['errors'], ['Nik harus diisi'])

        # Log Stored
        api_logs = PartnershipApiLog.objects.filter(partner=self.distributor.partner)
        self.assertTrue(api_logs)
        self.assertTrue(api_logs.count(), 1)

    def test_fail_post_merchant_due_to_null_shop_name(self):
        data = dict(
            nik='3203020101910012',
            distributor_xid=int(self.distributor.distributor_xid)
        )

        response = self.client.post(
            self.endpoint,
            data=data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNotNone(response.json()['errors'])
        self.assertEqual(response.json()['errors'], ['Shop_name harus diisi'])

        # Log Stored
        api_logs = PartnershipApiLog.objects.filter(partner=self.distributor.partner)
        self.assertTrue(api_logs)
        self.assertTrue(api_logs.count(), 1)


class TestWebviewApplicationOtpRequest(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner = register_partner_linkaja(self.client)
        self.partner = Partner.objects.filter(name=PartnerNameConstant.LINKAJA).last()
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            is_validation_otp_checking=False
        )
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner.json()['data']['secret_key'],
            HTTP_USERNAME=response_register_partner.json()['data']['partner_name'],
        )
        self.partnership_type = PartnershipTypeFactory()
        new_julo1_product_line()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.partner_user = AuthUserFactory(username='test_lead_gen_offer')
        self.customer = CustomerFactory(user=self.partner_user, nik=3173051512980141)
        self.account = AccountFactory(customer=self.customer)
        CustomerPinFactory(user=self.partner_user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999889,
            partner=self.partner
        )
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.save()
        self.application.save()
        self.endpoint = '/api/partnership/web/v1/request-otp'

    def test_otp_invalid_data(self) -> None:
        data = {
            'phone': None,
        }

        # Phone number not sended
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['Phone harus diisi'])

        # Invalid Phone Number
        data['phone'] = 82231456781
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['Phone format tidak sesuai'])

    @patch('juloserver.julo.tasks.send_sms_otp_partnership')
    def test_otp_success(self, _: MagicMock) -> None:
        mfs_parameters = {
            'wait_time_seconds': 1,
            'otp_max_request': 1,
            'otp_resend_time': 1
        }
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        data = {
            'phone': '082231456781',
            'nik': self.customer.nik
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['message'], 'OTP JULO sudah dikirim')

        # if partner config is_validation_otp_checking true, must be still success
        self.partnership_config.is_validation_otp_checking = True
        self.partnership_config.save(update_fields=['is_validation_otp_checking'])

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('juloserver.julo.tasks.send_sms_otp_partnership')
    def test_otp_fail_user_j1(self, _: MagicMock) -> None:
        mfs_parameters = {
            'wait_time_seconds': 1,
            'otp_max_request': 1,
            'otp_resend_time': 1
        }
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.application.partner = None
        self.application.save()
        data = {
            'phone': '082231456781',
            'nik': self.customer.nik
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_msg = (['Mohon untuk melanjutkan login pada apps JULO sesuai akun yang terdaftar.'
                      ' Mengalami kesulitan login? hubungi cs@julo.co.id'])
        self.assertEqual(response.json()['errors'], error_msg)


class TestWebviewApplicationOtpConfirmation(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner = register_partner_lead_gen()
        self.partner = Partner.objects.filter(name='partner_lead_gen').last()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner['secret_key'],
            HTTP_USERNAME=response_register_partner['partner_name'],
        )
        self.partnership_type = PartnershipTypeFactory()
        new_julo1_product_line()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.partner_user = AuthUserFactory(username='test_lead_gen_offer')
        self.customer = CustomerFactory(user=self.partner_user, nik=3173051512980141)
        self.account = AccountFactory(customer=self.customer)
        CustomerPinFactory(user=self.partner_user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999889,
            partner=self.partner
        )
        self.otp_request = OtpRequestFactory()
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=self.partner,
            nik=self.customer.nik,
            phone_number='082231456781'
        )
        self.partnership_customer_data_otp = PartnershipCustomerDataOTPFactory(
            partnership_customer_data=self.partnership_customer_data
        )
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.save()
        self.application.save()
        self.endpoint = '/api/partnership/web/v1/confirm-otp'

    def test_otp_confirmation_invalid_data(self) -> None:
        data = {
            'phone': None,
            'otp_token': '1234',
            'nik': None
        }

        # Invalid Token
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['Otp_token harus diisi'])

        # Invalid Phone Number
        data['phone'] = 82231456781
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['Phone format tidak sesuai'])

        # Invalid NIK
        data['phone'] = '082231456781'
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['NIK tidak memenuhi pattern yang dibutuhkan'])

    @patch('juloserver.partnership.services.web_services.pyotp')
    def test_otp_confirmation_not_registered(self, mock_pyotp: MagicMock) -> None:
        data = {
            'otp_token': '311232',
            'phone': self.partnership_customer_data.phone_number,
            'nik': self.customer.nik
        }

        mfs_parameters = {
            'wait_time_seconds': 1,
            'otp_max_request': 1,
            'otp_resend_time': 1
        }
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = str(self.customer.id)
        self.otp_request.cdate = timezone.now().date().replace(2099, 12, 30)
        self.otp_request.save()


        mock_pyotp.HOTP.return_value.verify.return_value = True
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'], ['Kode verifikasi belum terdaftar'])

    @patch('juloserver.partnership.services.web_services.pyotp')
    def test_otp_confirmation_not_registered(self, mock_pyotp: MagicMock) -> None:
        data = {
            'otp_token': '311232',
            'phone': self.partnership_customer_data.phone_number,
            'nik': self.customer.nik
        }

        mfs_parameters = {
            'wait_time_seconds': 1,
            'otp_max_request': 1,
            'otp_resend_time': 1
        }
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'], ['Kode verifikasi belum terdaftar'])

    @patch('juloserver.partnership.services.web_services.pyotp')
    def test_otp_confirmation_invalid(self, mock_pyotp: MagicMock) -> None:
        data = {
            'otp_token': '22222',
            'phone': self.partnership_customer_data.phone_number,
            'nik': self.customer.nik
        }

        mfs_parameters = {
            'wait_time_seconds': 1,
        }
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = str(self.customer.id)
        self.otp_request.partnership_customer_data=self.partnership_customer_data
        self.otp_request.cdate = timezone.now().date().replace(2099, 12, 30)
        self.otp_request.save()

        mock_pyotp.HOTP.return_value.verify.return_value = False
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'], ['Kode verifikasi tidak valid'])

    @patch('juloserver.partnership.services.web_services.pyotp')
    def test_otp_confirmation_expired(self, mock_pyotp: MagicMock) -> None:
        data = {
            'otp_token': '311232',
            'phone': self.partnership_customer_data.phone_number,
            'nik': self.customer.nik
        }

        mfs_parameters = {
            'wait_time_seconds': 1,
        }
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = str(self.customer.id)
        self.otp_request.partnership_customer_data=self.partnership_customer_data
        self.otp_request.cdate = timezone.now().date().replace(2000, 12, 30)
        self.otp_request.save()

        mock_pyotp.HOTP.return_value.verify.return_value = True
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'], ['Kode verifikasi kadaluarsa'])

    @patch('juloserver.partnership.services.web_services.pyotp')
    def test_otp_confirmation_success(self, mock_pyotp: MagicMock) -> None:
        data = {
            'otp_token': '311232',
            'phone': self.partnership_customer_data.phone_number,
            'nik': self.customer.nik
        }

        mfs_parameters = {
            'wait_time_seconds': 1,
        }
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = str(self.customer.id)
        self.otp_request.partnership_customer_data=self.partnership_customer_data
        self.otp_request.cdate = timezone.now().date().replace(2099, 12, 30)
        self.otp_request.save()

        mock_pyotp.HOTP.return_value.verify.return_value = True
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestWebviewRegistration(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user2 = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.partner = PartnerFactory(user=self.user)
        self.partner2 = PartnerFactory(user=self.user2)
        self.customer = CustomerFactory(user=self.user, nik=3173051512980141)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=self.partner,
            nik=self.customer.nik,
            phone_number='082231456781',
            otp_status=PartnershipCustomerData.VERIFIED,
        )
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="linkaja"
        )
        self.partnership_type = PartnershipTypeFactory()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.account = AccountFactory(customer=self.customer)
        CustomerPinFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999889,
            partner=self.partner
        )
        self.endpoint = '/api/partnership/web/v1/register'

    def test_registration_customer_data_invalid(self) -> None:
        data = {
            'nik': self.customer.nik,
            'email': None,
            'latitude': -6.9175,
            'longitude': 107.6195,
            'web_version': '1.0.0',
        }

        # Invalid Email
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Masukan alamat email yang valid'])

        # Invalid NIK
        data['email'] = self.customer.email
        data['nik'] = '123456789012345'
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Nik tidak memenuhi pattern yang dibutuhkan'])

    def test_registration_customer_data_not_found(self) -> None:
        data = {
            'nik': self.customer.nik,
            'email': self.customer.email,
            'latitude': -6.9175,
            'longitude': 107.6195,
            'web_version': '1.0.0',
        }

        self.partnership_customer_data.partner = self.partner2
        self.partnership_customer_data.save()

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Partnership Customer Data tidak ditemukan'])

    def test_registration_customer_data_success(self) -> None:
        data = {
            'nik': self.customer.nik,
            'email': self.customer.email,
            'latitude': -6.9175,
            'longitude': 107.6195,
            'web_version': '1.0.0',
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

        result = response.json()
        self.assertEqual(result['data']['email'], self.customer.email)
        self.assertEqual(result['data']['nik'], str(self.customer.nik))


class TestWebviewInfocard(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.client1 = APIClient()
        self.user1 = AuthUserFactory()
        self.customer1 = CustomerFactory(user=self.user1)
        partner1 = PartnerFactory(user=self.user1, is_active=True)
        self.token1 = self.customer1.user.auth_expiry_token.key
        self.partnership_customer_data1 = PartnershipCustomerDataFactory(
            customer=self.customer1,
            partner=partner1
        )
        self.client1.force_login(user=self.user1)
        self.client1.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data1.token,
            HTTP_AUTHORIZATION='Token ' + self.token1
        )
        self.product_line1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow1 = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.application1 = ApplicationFactory(
            customer=self.customer1,
            workflow=self.workflow1,
            application_xid=9999990347,
            partner=partner1,
            product_line=self.product_line1,
            email='testing_email1@gmail.com'
        )
        self.credit_score = CreditScoreFactory(application_id=self.application.id,
                                               score='B-')
        self.credit_score1 = CreditScoreFactory(application_id=self.application1.id,
                                                score='B-')
        self.endpoint = '/api/partnership/web/v1/info-card'

    def test_get_info_card(self) -> None:
        self.application.application_status = self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['application_id'], self.application.id)

    def test_get_info_card_for_form_partial_status(self) -> None:
        self.application1.application_status = self.application1.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL
        )
        response = self.client1.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['application_id'], self.application1.id)

    def test_get_info_card_with_button_in_121_status(self) -> None:
        self.application1.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application1.save()
        self.info_card = InfoCardPropertyFactory(card_type='2')
        self.button = ButtonInfoCardFactory(id=200, info_card_property=self.info_card)
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="content",
            info_card_property=self.info_card
        )
        self.streamlined_comms = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            message=self.streamlined_message,
            is_active=True,
            show_in_web=True,
            show_in_android=False,
            extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CARDS,
            status_code_id=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        )
        response = self.client1.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['application_id'], self.application1.id)
        cards = response.json()['data']['cards']
        if cards:
            for i in range(0, len(cards)):
                card = cards[i]
                self.assertGreater(len(card['button']), 0)


class TestGetMerchantView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        self.response_register_partner_mf = register_partner_merchant_financing()
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_register_partner_mf['secret_key'],
            HTTP_USERNAME=self.response_register_partner_mf['partner_name'],
        )
        self.partner = PartnerFactory(user=user, is_active=True)
        self.user_partner = Partner.objects.filter(
            email=self.response_register_partner_mf['partner_email']
        ).last()
        self.distributor = DistributorFactory(
            partner=self.user_partner ,
            user=self.user_partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor a',
            address='jakarta',
            email='testdistributora@gmail.com',
            phone_number='08123152321',
            type_of_business='warung',
            npwp='123040410292312',
            nib='223040410292312',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=123456,
        )
        XidLookupFactory(
            xid=2554367999,
            is_used_application=False
        )
        self.merchant_1 = MerchantFactory(
            nik='3203020101910011',
            shop_name='merchant 1',
            distributor=self.distributor,
            merchant_xid=2554367997
        )
        self.province_lookup = ProvinceLookupFactory(
            province='Jawa barat',
            is_active=True,
        )
        self.city_lookup = CityLookupFactory(
            province=self.province_lookup,
            city='Garut',
            is_active=True
        )
        self.district_lookup = DistrictLookupFactory(
            city=self.city_lookup,
            is_active=True,
            district='Padasuka'
        )
        self.sub_district_lookup = SubDistrictLookupFactory(
            sub_district='Cikajang',
            is_active=True,
            zipcode='43251',
            district=self.district_lookup
        )
        workflow = WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        customer = CustomerFactory(user=user)
        self.application = ApplicationFactory(
            customer=customer,
            workflow=workflow,
            merchant=self.merchant_1,
            partner=self.distributor.partner,
            application_xid=123321
        )
        ImageFactory(
            image_type='selfie',
            image_source=self.application.id
        )
        ImageFactory(
            image_type='ktp_self',
            image_source=self.application.id
        )
        ImageFactory(
            image_type='crop_selfie',
            image_source=self.application.id
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))
        self.endpoint = '/api/partnership/v1/merchants'

    def test_get_merchant_not_found(self) -> None:
        self.distributor.partner = self.partner
        self.distributor.save(update_fields=['partner'])

        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_get_merchant_success(self) -> None:
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestImageListCreateView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.response_register_partner_mf = register_partner_merchant_financing()
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_register_partner_mf['secret_key'],
            HTTP_USERNAME=self.response_register_partner_mf['partner_name'],
        )
        self.user_partner = Partner.objects.filter(
            email=self.response_register_partner_mf['partner_email']
        ).last()
        self.user = self.user_partner.user
        self.partner = self.user_partner
        self.distributor = DistributorFactory(
            partner=self.user_partner ,
            user=self.user_partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor a',
            address='jakarta',
            email='testdistributora@gmail.com',
            phone_number='08123152321',
            type_of_business='warung',
            npwp='123040410292312',
            nib='223040410292312',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=123456,
        )
        XidLookupFactory(
            xid=2554367999,
            is_used_application=False
        )
        self.merchant_1 = MerchantFactory(
            nik='3203020101910011',
            shop_name='merchant 1',
            distributor=self.distributor,
            merchant_xid=2554367997
        )
        self.province_lookup = ProvinceLookupFactory(
            province='Jawa barat',
            is_active=True,
        )
        self.city_lookup = CityLookupFactory(
            province=self.province_lookup,
            city='Garut',
            is_active=True
        )
        self.district_lookup = DistrictLookupFactory(
            city=self.city_lookup,
            is_active=True,
            district='Padasuka'
        )
        self.sub_district_lookup = SubDistrictLookupFactory(
            sub_district='Cikajang',
            is_active=True,
            zipcode='43251',
            district=self.district_lookup
        )
        workflow = WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=customer,
            workflow=workflow,
            merchant=self.merchant_1,
            partner=self.distributor.partner,
            application_xid=123321,
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.FORM_CREATED
            )
        )
        ImageFactory(
            image_type='selfie',
            image_source=self.application.id
        )
        ImageFactory(
            image_type='ktp_self',
            image_source=self.application.id
        )
        ImageFactory(
            image_type='crop_selfie',
            image_source=self.application.id
        )
        self.customer_pin = CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1
        )
        application_xid = self.application.application_xid
        self.endpoint = '/api/partnership/v1/applications/{}/images'.format(application_xid)

    def test_upload_image_application_not_found(self) -> None:
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        self.application.save()

        self.endpoint = '/api/partnership/v1/applications/999999999/images'
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_upload_image_application_error(self) -> None:
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        self.application.save()

        response = self.client.post(self.endpoint)
        # Not found upload data
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

        data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
        }

        response = self.client.post(self.endpoint, data=data)
        # Not found image_type data
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_upload_image_application_invalid_status(self) -> None:
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_RESUBMITTED
        )
        self.application.save()
        data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_upload_image_application_invalid_success(self) -> None:
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        self.application.save()

        data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
        }

        response = self.client.post(self.endpoint, data=data)
        # Not found upload data
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

    def test_upload_image_application_invalid_paylater_transaction_xid(self) -> None:
        self.endpoint = self.endpoint + '?paylater_transaction_xid=3423423423'
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        self.application.save()
        data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'],
                         [ErrorMessageConst.PAYLATER_TRANSACTION_XID_NOT_FOUND])

    def test_upload_image_application_with_paylater_transaction_xid_success(self) -> None:
        paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id='9008787121',
            transaction_amount=10000001,
            paylater_transaction_xid=5233634749,
            partner=self.partner,
        )

        PaylaterTransactionStatusFactory(
            paylater_transaction=paylater_transaction,
            transaction_status=PaylaterTransactionStatuses.IN_PROGRESS,
        )
        self.endpoint = self.endpoint + '?paylater_transaction_xid=' \
            .format(paylater_transaction.paylater_transaction_xid)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        self.application.save()
        data = {
            'upload': open(settings.BASE_DIR + '/juloserver/apiv1/tests/asset_test/ww.jpg', 'rb'),
            'image_type': 'selfie',
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestPartnershipApplicationOtpRequest(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.response_register_partner_mf = register_partner_merchant_financing()
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_register_partner_mf['secret_key'],
            HTTP_USERNAME=self.response_register_partner_mf['partner_name'],
        )
        self.user_partner = Partner.objects.filter(
            email=self.response_register_partner_mf['partner_email']
        ).last()
        self.partnership_config = PartnershipConfigFactory(
            partner=self.user_partner,
            is_validation_otp_checking=False
        )
        self.user = self.user_partner.user
        self.customer = CustomerFactory(user=self.user, nik=3173051512980141)
        workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            product_line=self.product_line,
            application_xid='1987131908',
            partner=self.user_partner
        )
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        application_xid = self.application.application_xid
        self.customer_pin = CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1
        )
        self.endpoint = '/api/partnership/v1/application/otp/{}'.format(application_xid)

    def test_send_otp_request_not_found_customer_pin(self) -> None:
        self.customer_pin.delete()
        data ={
            "phone": 812345601
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Aplikasi belum memiliki PIN'])

    @patch('juloserver.partnership.services.services.send_sms_otp_token')
    def test_send_otp_request_customer(self, _: MagicMock) -> None:
        mfs_parameters = {
            'wait_time_seconds': 1,
            'otp_max_request': 1,
            'otp_resend_time': 1
        }
        self.mobile_feature_setting.feature_name = 'mobile_phone_1_otp'
        self.mobile_feature_setting.is_active = True
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        data ={
            'phone': 812345601
        }
        response = self.client.post(self.endpoint, data=data)

        # Error Invalid phone number
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

        # Success
        data['phone'] = '082212347890'
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

        # if partner config is_validation_otp_checking true, must be still success
        self.partnership_config.is_validation_otp_checking = True
        self.partnership_config.save(update_fields=['is_validation_otp_checking'])

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestPartnershipApplicationOtpValidation(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.response_register_partner_mf = register_partner_merchant_financing()
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_register_partner_mf['secret_key'],
            HTTP_USERNAME=self.response_register_partner_mf['partner_name'],
        )
        self.user_partner = Partner.objects.filter(
            email=self.response_register_partner_mf['partner_email']
        ).last()
        self.user = self.user_partner.user
        self.customer = CustomerFactory(user=self.user, nik=3173051512980141)
        self.otp_request = OtpRequestFactory()
        workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            product_line=self.product_line,
            application_xid='1987131908',
            partner=self.user_partner
        )
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name='mobile_phone_1_otp',
            is_active=True
        )
        application_xid = self.application.application_xid
        self.customer_pin = CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1
        )
        self.endpoint = '/api/partnership/v1/application/otp/validate/{}'.format(application_xid)

    def test_otp_validation_not_found_customer_pin(self) -> None:
        self.customer_pin.delete()
        data ={
            'otp_token': '311232'
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Aplikasi belum memiliki PIN'])

    def test_validation_otp_customer_request_not_exist(self) -> None:
        data = {
            'otp_token': '311232'
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Kode verifikasi belum terdaftar'])

    @patch('juloserver.partnership.services.services.pyotp')
    def test_validation_otp_customer_request_token_invalid(self, mock_pyotp: MagicMock) -> None:
        data = {
            'otp_token': '311232'
        }

        self.otp_request.customer = self.customer
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = str(self.customer.id)
        self.otp_request.save()

        mock_pyotp.HOTP.return_value.verify.return_value = False
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Kode verifikasi tidak valid'])

    @patch('juloserver.partnership.services.services.pyotp')
    def test_validation_otp_customer_request_token_success(self, mock_pyotp: MagicMock) -> None:
        data = {
            'otp_token': '311232'
        }

        mfs_parameters = {
            'wait_time_seconds': 1
        }
        self.mobile_feature_setting.parameters = mfs_parameters
        self.mobile_feature_setting.save()

        self.otp_request.customer = self.customer
        self.otp_request.otp_token = data['otp_token']
        self.otp_request.is_used = False
        self.otp_request.request_id = str(self.customer.id)
        self.otp_request.cdate = timezone.now().date().replace(2099, 12, 30)
        self.otp_request.save()

        mock_pyotp.HOTP.return_value.verify.return_value = True
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestPartnershipRetryCheckTransactionView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(
            user=self.user, is_active=True,
            name=PartnerNameConstant.LINKAJA
        )
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=self.partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.application2 = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990085,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email2@gmail.com',
            account=self.account
        )
        self.loan1 = LoanFactory(
            partner=self.partner,
            account=self.account, customer=self.customer,
            application=self.application,
            loan_amount=10000000, loan_xid=1000003456
        )
        self.loan2 = LoanFactory(
            partner=self.partner,
            account=self.account, customer=self.customer,
            application=self.application2,
            loan_amount=10000000, loan_xid=1000003457
        )
        self.partnership_transaction = PartnershipTransactionFactory(
            transaction_id='1109876543', partner_transaction_id='09809765',
            customer=self.customer, partner=self.partner, loan=self.loan1
        )
        self.partnership_transaction2 = PartnershipTransactionFactory(
            transaction_id='1109876542', partner_transaction_id='09809767',
            customer=self.customer, partner=self.partner, loan=self.loan2
        )
        PartnershipLogRetryCheckTransactionStatusFactory(
            status=PartnershipLogStatus.FAILED,
            loan=self.loan1
        )
        self.task_checking2 = PartnershipLogRetryCheckTransactionStatusFactory(
            status=PartnershipLogStatus.IN_PROGRESS,
            loan=self.loan2
        )

    def test_partnership_retry_check_invalid_partner(self) -> None:
        self.partner.delete()
        response = self.client.post('/api/partnership/v1/retry-check-transaction-status')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_partnership_retry_check_no_loan(self) -> None:
        response = self.client.post('/api/partnership/v1/retry-check-transaction-status')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    @patch('juloserver.partnership.clients.tasks.bulk_task_check_transaction_linkaja.delay')
    def test_partnership_retry_check_success(self, task_retry: MagicMock) -> None:
        self.loan1.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.DISBURSEMENT_FAILED_ON_PARTNER_SIDE
        )
        self.loan1.save()
        self.loan1.refresh_from_db()
        self.loan2.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.DISBURSEMENT_FAILED_ON_PARTNER_SIDE
        )
        self.loan2.save()
        self.loan2.refresh_from_db()
        self.task_checking2.status = PartnershipLogStatus.FAILED
        self.task_checking2.save()
        self.task_checking2.refresh_from_db()

        response = self.client.post('/api/partnership/v1/retry-check-transaction-status')
        result = response.json()
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(result['success'], True)
        self.assertEqual(result['data']['total_loan_status'], 2)
        loan_ids_result = result['data']['loan_ids']
        loans_expected_result = [self.loan1.id, self.loan2.id]
        self.assertEqual(loan_ids_result.sort(), loans_expected_result.sort())

        # Task Executed
        self.assertEqual(task_retry._mock_call_count, 1)


class TestPartnershipLogTransactionView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(
            user=self.user, is_active=True,
            name=PartnerNameConstant.LINKAJA
        )
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.application2 = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990085,
            partner=partner,
            product_line=self.product_line,
            email='testing_email2@gmail.com',
            account=self.account
        )
        self.loan1 = LoanFactory(
            account=self.account, customer=self.customer,
            application=self.application,
            loan_amount=10000000, loan_xid=1000003456
        )
        self.loan2 = LoanFactory(
            account=self.account, customer=self.customer,
            application=self.application2,
            loan_amount=10000000, loan_xid=1000003457
        )
        self.partnership_transaction = PartnershipTransactionFactory(
            transaction_id='1109876543', partner_transaction_id='09809765',
            customer=self.customer, partner=partner, loan=self.loan1
        )
        self.partnership_transaction2 = PartnershipTransactionFactory(
            transaction_id='1109876542', partner_transaction_id='09809767',
            customer=self.customer, partner=partner, loan=self.loan2
        )
        PartnershipLogRetryCheckTransactionStatusFactory(
            status=PartnershipLogStatus.FAILED,
            loan=self.loan1
        )
        PartnershipLogRetryCheckTransactionStatusFactory(
            status=PartnershipLogStatus.IN_PROGRESS,
            loan=self.loan2
        )

    def test_get_log_partnership_transaction_invalid_ids(self) -> None:
        # Invalid no IDs send
        response = self.client.post('/api/partnership/v1/transaction-status-logs')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)

    def test_get_log_partnership_transaction_not_found(self) -> None:
        # None data set as 0
        data = {
            'loan_ids': [199998, 199992]
        }
        response = self.client.post('/api/partnership/v1/transaction-status-logs', data=data)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        result = response.json()
        self.assertEqual(result['success'], True)
        self.assertEqual(result['data']['loans_failed']['loan_ids'], [])
        self.assertEqual(result['data']['loans_failed']['total'], 0)
        self.assertEqual(result['data']['loans_success']['loan_ids'], [])
        self.assertEqual(result['data']['loans_success']['total'], 0)
        self.assertEqual(result['data']['loans_in_progress']['loan_ids'], [])
        self.assertEqual(result['data']['loans_in_progress']['total'], 0)

    def test_get_log_partnership_transaction_found(self) -> None:
        # Loan Logs Not found send return default 0
        loans = {
            'loan_ids': [self.loan1.id, self.loan2.id]
        }
        response = self.client.post('/api/partnership/v1/transaction-status-logs', data=loans)
        result = response.json()
        self.assertEqual(result['success'], True)
        self.assertEqual(result['data']['loans_failed']['loan_ids'], [self.loan1.id])
        self.assertEqual(result['data']['loans_failed']['total'], 1)
        self.assertEqual(result['data']['loans_success']['loan_ids'], [])
        self.assertEqual(result['data']['loans_success']['total'], 0)
        self.assertEqual(result['data']['loans_in_progress']['loan_ids'], [self.loan2.id])
        self.assertEqual(result['data']['loans_in_progress']['total'], 1)


class TestCheckRegisteredUser(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer
        )
        self.partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=self.partnership_customer_data
        )
        self.application = ApplicationFactory(customer=self.customer)
        self.application.save()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            product_line=self.product_line,
            workflow=self.workflow
        )
        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.save()

        self.client = APIClient()
        self.client.force_authenticate(user=self.partnership_customer_data.customer.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME=self.partnership_customer_data.partner.name
        )
        self.endpoint = '/api/partnership/web/v1/check_registered_user'

    def test_success_check_registered_user(self):
        response = self.client.post(
            self.endpoint
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_fail_without_token(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.partnership_customer_data.customer.user)
        self.client.credentials(
            HTTP_USERNAME=self.partnership_customer_data.partner.name
        )
        response = self.client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(response.data.get("errors")[0], 'Token Cannot be empty')
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_check_reject_non_j1_customer(self):
        self.partnership_customer_data.nik = '1598930506022616'
        self.partnership_customer_data.save()
        self.customer.nik = '1598930506022616'
        self.customer.save()
        self.data = {
            "show_pin_creation_page": False,
            "redirect_to_page": 'non_j1_customer_page',
            "verify_pin_j1": False,
            'partnership_customer': self.partnership_customer_data.id
        }
        response = self.client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_customer_data_customer_not_none_and_is_submitted_true(self):
        self.partnership_application_data.is_submitted = True
        self.partnership_application_data.save()
        self.data = {
            "show_pin_creation_page": False,
            "redirect_to_page": 'j1_verification_page',
            "verify_pin_j1": False,
            'partnership_customer': self.partnership_customer_data.id
        }
        response = self.client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_none_has_j1_can_reapply(self):
        customer = CustomerFactory(
            can_reapply=True
        )
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow
        )
        application.application_status = StatusLookupFactory(status_code=100)
        application.save()

        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()
        partnership_customer_data.customer.nik = '1598930506022617'
        customer.save()

        self.data = {
            "show_pin_creation_page": False,
            "redirect_to_page": 'loan_expectation_page',
            "verify_pin_j1": True,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_none_has_j1_cant_reapply(self):
        customer = CustomerFactory()
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow,
        )
        application.save()
        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()
        partnership_customer_data.customer.nik = '1598930506022617'
        partnership_customer_data.customer.save()

        self.data = {
            "show_pin_creation_page": False,
            "redirect_to_page": 'loan_expectation_page',
            "verify_pin_j1": False,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_none_has_not_j1(self):
        customer = CustomerFactory()
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow,
        )
        application.save()
        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()
        partnership_customer_data.customer.nik = '1598930506022616'
        partnership_customer_data.customer.save()

        self.data = {
            "show_pin_creation_page": True,
            "redirect_to_page": 'loan_expectation_page',
            "verify_pin_j1": False,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_has_j1_not_submitted_can_reapply(self):
        customer = CustomerFactory(
            can_reapply=True
        )
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow
        )
        application.application_status = StatusLookupFactory(status_code=100)
        application.save()

        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )

        partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=partnership_customer_data
        )
        partnership_application_data.is_submitted = False
        partnership_application_data.save()

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()
        partnership_customer_data.customer.nik = '1598930506022617'
        customer.save()

        self.data = {
            "show_pin_creation_page": False,
            "redirect_to_page": 'long_form_page',
            "verify_pin_j1": True,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_has_j1_not_submitted_cant_reapply(self):
        customer = CustomerFactory()
        customer.can_reapply = False
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow
        )
        application.application_status = StatusLookupFactory(status_code=200)
        application.save()

        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )

        partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=partnership_customer_data
        )
        partnership_application_data.is_submitted = False
        partnership_application_data.save()

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()
        partnership_customer_data.customer.nik = '1598930506022617'
        customer.save()

        self.data = {
            "show_pin_creation_page": False,
            "redirect_to_page": 'long_form_page',
            "verify_pin_j1": False,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_submitted_has_j1_can_reapply_cust_data_not_none(self):
        customer = CustomerFactory()
        customer.can_reapply = True
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow
        )
        application.application_status = StatusLookupFactory(status_code=100)
        application.save()

        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=None,
            partner=partner
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()

        partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=partnership_customer_data
        )
        partnership_application_data.is_submitted = True
        partnership_application_data.save()

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        customer.nik = '1598930506022617'
        customer.save()

        self.data = {
            "show_pin_creation_page": False,
            "redirect_to_page": 'registration_page',
            "verify_pin_j1": True,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_submitted_has_j1_cust_data_not_none(self):
        customer = CustomerFactory()
        customer.can_reapply = True
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow
        )
        application.application_status = StatusLookupFactory(status_code=100)
        application.save()

        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            partner=partner
        )

        partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=partnership_customer_data
        )
        partnership_application_data.is_submitted = True
        partnership_application_data.save()

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()
        customer.nik = '1598930506022617'
        customer.save()

        self.data = {
            "show_pin_creation_page": False,
            "redirect_to_page": 'j1_verification_page',
            "verify_pin_j1": False,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_j1_flag_none_application_data_submitted_pin_none(self):
        customer = CustomerFactory()
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow
        )
        application.save()

        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )

        partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=partnership_customer_data
        )
        partnership_application_data.is_submitted = False
        partnership_application_data.save()

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()
        partnership_customer_data.customer.nik = '1598930506022618'
        customer.save()

        self.data = {
            "show_pin_creation_page": True,
            "redirect_to_page": 'pin_creation_page',
            "verify_pin_j1": False,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_none_j1_flag_none_application_data_submitted_pin_(self):
        customer = CustomerFactory()
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow
        )
        application.save()

        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )

        partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=partnership_customer_data
        )
        partnership_application_data.is_submitted = False
        partnership_application_data.encoded_pin = "Z0FBQUFBQmlGMW9aQzVqUTgzZE5RT2FhbTkzLW" \
        "xzN1JZZVhyeXlzeDFwTHF2djh6bDhPaXVzMnN5TVE1ZWI5OUxBWnFvN1JNa1BUMkEwakdmTFRNYW9kTlRvL" \
        "XI4WmRwTHc9PQ=="
        partnership_application_data.save()

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()
        partnership_customer_data.customer.nik = '1598930506022618'
        customer.save()

        self.data = {
            "show_pin_creation_page": False,
            "redirect_to_page": 'long_form_page',
            "verify_pin_j1": False,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_j1_flag_none_customer_data_none(self):
        customer = CustomerFactory()
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow
        )
        application.save()

        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=None,
            partner=partner
        )

        partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=partnership_customer_data
        )
        partnership_application_data.is_submitted = True
        partnership_application_data.save()

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()
        customer.save()

        self.data = {
            "show_pin_creation_page": True,
            "redirect_to_page": 'registration_page',
            "verify_pin_j1": False,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])

    def test_partnership_application_data_j1_flag_none_customer_data_not_none(self):
        customer = CustomerFactory()
        application = ApplicationFactory(
            customer=customer,
            product_line=self.product_line,
            workflow=self.workflow
        )
        application.save()

        user = AuthUserFactory()
        partner = PartnerFactory(user=user, is_active=True)
        partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=partner
        )

        partnership_application_data = PartnershipApplicationDataFactory(
            partnership_customer_data=partnership_customer_data
        )
        partnership_application_data.is_submitted = True
        partnership_application_data.save()

        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(
            HTTP_SECRET_KEY=partnership_customer_data.token,
            HTTP_USERNAME=partnership_customer_data.partner.name
        )
        partnership_customer_data.nik = '1598930506022617'
        partnership_customer_data.save()
        partnership_customer_data.customer.nik = '1598930506022618'
        customer.save()

        self.data = {
            "show_pin_creation_page": False,
            "redirect_to_page": 'j1_verification_page',
            "verify_pin_j1": False,
            'partnership_customer': partnership_customer_data.id
        }
        response = client.post(
            self.endpoint,
            format='json'
        )

        self.assertEqual(self.data, response.json()['data'])


class TestGetPhoneNumber(TestCase):
    def setUp(self) -> None:
        partner = PartnerFactory()
        partner.name = 'linkaja'
        partner.is_active = True
        partner.save()
        self.client = APIClient()
        self.client.credentials(
            HTTP_USERNAME=partner.name
        )
        self.endpoint = '/api/partnership/web/v1/get-phone-number' \
                        '?sessionID=01EA1PTFKAQMFJEQR999XWZHVW'
        self.serializer_data = {
            "max_length": 500,
            "error_messages": "Error"
        }
        self.data = {
            "max_length": 500,
            "error_messages": "Error"
        }

    @patch('juloserver.partnership.views.get_count_request_on_redis')
    @patch('juloserver.partnership.clients.clients.LinkAjaClient.verify_session_id')
    def test_success_get_phone_number(self, mock_verify_sessionID, mock_get_count_request_on_redis):
        mock_get_count_request_on_redis.return_value = 0, ""
        mock_verify_sessionID.return_value.status_code = 200
        mock_verify_sessionID.return_value.content = '{"data": ' \
        '{"customerAccessToken": "01FY8AZE0Q2DYBX1R32TYC390Z", "customerNumber": "6285217296020",' \
        ' "customerID": "202000000040457062"}, "status": "00", "message": "Success"}'
        response = self.client.get(
            self.endpoint
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)

    @patch('juloserver.partnership.views.get_count_request_on_redis')
    def test_fail_get_phone_number(self, mock_get_count_request_on_redis):
        mock_get_count_request_on_redis.return_value = 0, ""
        endpoint = '/api/partnership/web/v1/get-phone-number' \
                        '?sessionID=32234234'
        self.client = APIClient()
        response = self.client.get(
            endpoint,
            data={},
        )

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertIsNone(response.json()['data'])


class TestWebviewLogin(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.user.password = 'pbkdf2_sha256$24000$mnhfL9EfGWHQ$tsBPrpT0HoIO8az7eo2FxRvNYq9E98n' \
                             'msuBwSiNAtQ0='
        self.partner = PartnerFactory(user=self.user, is_active=True,
                                      name=PartnerNameConstant.LINKAJA)
        self.customer_pin = CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=self.partner
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            partner=self.partner,
            web_version="1.0.0"
        )
        self.partnership_customer_data.nik = '1598930506022617'
        self.user.username = self.partnership_customer_data.nik
        self.customer.nik = self.partnership_customer_data.nik
        self.partnership_customer_data.otp_status = 'VERIFIED'
        self.partnership_customer_data.save()
        self.customer.save()
        self.user.save()

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME=self.partnership_customer_data.partner.name
        )
        self.endpoint = '/api/partnership/web/v1/login'

    def test_success_login(self):
        login_attempt = LoginAttemptFactory(
            customer=self.customer,
        )

        response = self.client.post(
            self.endpoint,
            data={
                'nik': self.user.username,
                'pin': "159357",
                "latitude": 0.0,
                "longitude": 0.0,
                'web_version': "1.0.0",
                "partner_name": "tester"
            },
            format='json'
        )
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_fail_login(self):
        login_attempt = LoginAttemptFactory(
            customer=self.customer,
        )

        response = self.client.post(
            self.endpoint,
            data={
                'nik': self.user.username,
                'pin': "111111",
                "latitude": 133.2,
                "longitude": 230.2,
                'web_version': "1.0.0",
                "partner_name": "tester"
            },
            format='json'
        )

        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)

    def test_success_fail_user_j1(self):
        self.application.partner = None
        self.application.save()
        login_attempt = LoginAttemptFactory(
            customer=self.customer,
        )

        response = self.client.post(
            self.endpoint,
            data={
                'nik': self.user.username,
                'pin': "159357",
                "latitude": 133.2,
                "longitude": 230.2,
                'web_version': "1.0.0",
                "partner_name": "tester"
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        error_msg = (['Mohon untuk melanjutkan login pada apps JULO sesuai akun yang terdaftar.'
                      ' Mengalami kesulitan login? hubungi cs@julo.co.id'])
        self.assertEqual(response.json()['errors'], error_msg)


class TestPartnershipLoanStatus(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner = register_partner_paylater(self.client)
        self.partner = Partner.objects.filter(name='partner_paylater').last()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner.json()['data']['secret_key'],
            HTTP_USERNAME=response_register_partner.json()['data']['partner_name'],
        )
        self.partnership_type = PartnershipTypeFactory(
            partner_type_name='Whitelabel Paylater')
        new_julo1_product_line()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.partner_user = AuthUserFactory(username='test_paylater1')
        self.customer = CustomerFactory(user=self.partner_user)
        self.account = AccountFactory(customer=self.customer)
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30],
            loan_cancel_duration = 7
        )
        CustomerPinFactory(user=self.partner_user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999867,
            partner=self.partner
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.application.save()
        self.status = StatusLookupFactory()
        self.status.status_code = 220
        self.status.save()
        self.loan = LoanFactory(
            partner=self.partner,
            account=self.account, customer=self.customer,
            application=self.application,
            loan_amount=10000000, loan_xid=1000003056,
            loan_status=self.status,
            sphp_accepted_ts=timezone.localtime(
                timezone.now()).date() - timedelta(days=5)
        )
        self.endpoint = '/api/partnership/v1/agreement/loan/status/{}/'.format(self.loan.loan_xid)
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=220, status_next=216, workflow=self.workflow)

    def test_change_partnership_loan_status_success(self):
        data = {
            "status": 'cancel'
        }
        response = self.client.post(self.endpoint, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_change_partnership_loan_status_failure(self):
        data = {
            "status": 'cancel'
        }
        self.status = StatusLookupFactory()
        self.status.status_code = 216
        self.status.save()
        self.loan.loan_status = self.status
        self.loan.sphp_accepted_ts = None
        self.loan.save()

        response = self.client.post(self.endpoint, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('juloserver.partnership.views.accept_julo_sphp')
    def test_change_partnership_loan_status_success_paylater(self,
                                                             _: MagicMock) -> None:
        data = {
            "status": 'sign'
        }
        self.status = StatusLookupFactory()
        self.status.status_code = LoanStatusCodes.INACTIVE
        self.status.save()
        self.loan.loan_status = self.status
        self.loan.save()
        self.paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id='900878712',
            transaction_amount=10000001,
            paylater_transaction_xid=9991111111,
            partner=self.partner
        )

        ImageFactory(
            image_type='signature',
            image_source=self.loan.id,
            image_status=0
        )

        self.paylater_transaction_status = PaylaterTransactionStatusFactory(
            paylater_transaction=self.paylater_transaction,
            transaction_status=PaylaterTransactionStatuses.IN_PROGRESS
        )

        self.paylater_transaction_loan = PaylaterTransactionLoanFactory(
            paylater_transaction=self.paylater_transaction,
            loan=self.loan
        )
        response = self.client.post(self.endpoint, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.paylater_transaction_status.refresh_from_db()
        self.assertEqual(self.paylater_transaction_status.transaction_status,
                         PaylaterTransactionStatuses.SUCCESS)

    @patch('juloserver.partnership.views.cancel_loan')
    def test_change_partnership_loan_status_cancel_paylater(self,
                                                            _: MagicMock) -> None:
        data = {
            "status": 'cancel'
        }
        self.status = StatusLookupFactory()
        self.status.status_code = LoanStatusCodes.INACTIVE
        self.status.save()
        self.loan.loan_status = self.status
        self.loan.save()
        self.paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id='900878712',
            transaction_amount=10000001,
            paylater_transaction_xid=9991111111,
            partner=self.partner
        )

        ImageFactory(
            image_type='signature',
            image_source=self.loan.id,
            image_status=0
        )

        self.paylater_transaction_status = PaylaterTransactionStatusFactory(
            paylater_transaction=self.paylater_transaction,
            transaction_status=PaylaterTransactionStatuses.IN_PROGRESS
        )

        self.paylater_transaction_loan = PaylaterTransactionLoanFactory(
            paylater_transaction=self.paylater_transaction,
            loan=self.loan
        )
        response = self.client.post(self.endpoint, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.paylater_transaction_status.refresh_from_db()
        self.assertEqual(self.paylater_transaction_status.transaction_status,
                         PaylaterTransactionStatuses.CANCEL)


class TestCustomerRegistrationView(TestCase):
    def setUp(self):
        from juloserver.julo.services2.encryption import Encryption

        self.endpoint = '/api/partnership/v1/customer/'
        self.client = APIClient()
        self.user = AuthUserFactory()
        encrypt = Encryption()
        partner_token = encrypt.encode_string(self.user.auth_expiry_token.key)
        self.partner = PartnerFactory(user=self.user, is_active=True, token=partner_token)
        self.partner.name = self.user.username
        self.partner.save()
        new_julo1_product_line()
        WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.client.credentials(
            HTTP_USERNAME=self.partner.name,
            HTTP_SECRET_KEY=self.partner.token,
        )

    def test_invalid_nik(self):
        request_data = {
            "username": "11111111111111111111111",
            "email": "test@gmail.com",
            "latitude": -6.215124,
            "longitude": 107.0185668
        }
        response = self.client.post(self.endpoint, data=request_data, format='json')
        response_data = response.json()
        self.assertEqual('Username data tidak valid', response_data['errors'][0])
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code)

    def test_invalid_email(self):
        request_data = {
            "username": "1203022001999877",
            "email": "test????????@gmail.com",
            "latitude": -6.215124,
            "longitude": 107.0185668
        }
        response = self.client.post(self.endpoint, data=request_data, format='json')
        response_data = response.json()
        self.assertEqual('Email data tidak valid', response_data['errors'][0])
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code)

    @patch('juloserver.julo.services.process_application_status_change')
    def test_success_registration(self, mock_process_application_status_change):
        request_data = {
            "username": "1203022001999877",
            "email": "test@gmail.com",
            "latitude": -6.215124,
            "longitude": 107.0185668
        }
        response = self.client.post(self.endpoint, data=request_data, format='json')
        self.assertEqual(HTTPStatus.CREATED, response.status_code)


class TestWebviewCreatePin(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, nik=3170051512980141)
        self.partner = PartnerFactory(user=self.user, is_active=True)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=self.partner
        )
        self.endpoint = '/api/partnership/web/v1/create-pin'
        workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            product_line=self.product_line,
            application_xid=1000677706,
            partner=self.partner
        )
        encrypter = encrypt()
        self.xid = encrypter.encode_string(str(self.application.application_xid))
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)


    def test_create_pin_for_no_data(self):
        response = self.client.post(self.endpoint, data={}, format='json')
        assert response.status_code == HTTPStatus.BAD_REQUEST
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["Pin harus diisi",
                                                     "Xid harus diisi"])

    def test_create_pin_for_invalid_pin_format(self):
        response = self.client.post(self.endpoint, data={
            'xid': self.xid,
            'pin': '4333'
        }, format='json')
        assert response.status_code == HTTPStatus.BAD_REQUEST
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["Pin tidak memenuhi pattern yang dibutuhkan"])


    def test_create_pin_for_no_application(self):
        response = self.client.post(self.endpoint, data={
            'xid': '77',
            'pin': '111111'
        }, format='json')
        assert response.status_code == HTTPStatus.BAD_REQUEST
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Aplikasi tidak ditemukan'])


    def test_create_pin_for_no_partnership_config(self):
        response = self.client.post(self.endpoint, data={
            'xid': self.xid,
            'pin': '159357'
        }, format='json')
        assert response.status_code == HTTPStatus.BAD_REQUEST
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'],
                         [ErrorMessageConst.INVALID_DATA_CHECK])


    def test_create_pin_for_no_partnership_type(self):
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            loan_duration=[3, 7, 14, 30]
        )
        response = self.client.post(self.endpoint, data={
            'xid': self.xid,
            'pin': '159357'
        }, format='json')
        assert response.status_code == HTTPStatus.BAD_REQUEST
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], [ErrorMessageConst.INVALID_DATA_CHECK])


    def test_create_pin_for_invalid_application_status(self):
        self.partnership_type = PartnershipTypeFactory(partner_type_name=
                                                       PartnershipTypeConstant.LEAD_GEN)
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30]
        )
        response = self.client.post(self.endpoint, data={
            'xid': self.xid,
            'pin': '159357'
        }, format='json')
        assert response.status_code == HTTPStatus.BAD_REQUEST
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Aplikasi status tidak valid'])


    def test_create_pin_success(self):
        self.partnership_type = PartnershipTypeFactory(partner_type_name=
                                                       PartnershipTypeConstant.LEAD_GEN)
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30]
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.application.save()
        response = self.client.post(self.endpoint, data={
            'xid': self.xid,
            'pin': 159357
        }, format='json')
        self.assertIsNotNone(response)


class TestValidateApplicationView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, nik='1111222233334444')
        partner = PartnerFactory(user=self.user, is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            ktp='1111222233334444',
            customer=self.customer,
            workflow=self.workflow,
            application_xid=999991111,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.endpoint = '/api/partnership/web/v1/validate-application'
        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.save()

    @override_settings(CRYPTOGRAPHY_KEY='QWvxJtgPh36mHJ9R8hn_5uFuaMCxQ5Yj6St2kQ4Mgkb=')
    def test_application_validation_failed(self) -> None:
        invalid_xid = 8888881111
        self.assertNotEqual(self.application.application_xid, invalid_xid)

        encrypter = encrypt()
        xid = encrypter.encode_string(str(invalid_xid))
        data = {
            'application_xid': self.application.application_xid,
            'xid': xid
        }
        response = self.client.post(self.endpoint, data=data, format='json')

        # return error xid is invalid not match with application xid
        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'],
                         [ErrorMessageConst.INVALID_DATA_CHECK])

        # invalid xid data
        data['xid'] = 12121212
        response = self.client.post(self.endpoint, data=data, format='json')
        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'],
                         [ErrorMessageConst.INVALID_DATA_CHECK])

        # match xid and application xid, error application not found
        encrypter = encrypt()
        xid = encrypter.encode_string(str(12121212))
        data['xid'] = xid
        data['application_xid'] = 12121212
        response = self.client.post(self.endpoint, data=data, format='json')
        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'],
                         [ErrorMessageConst.INVALID_DATA_CHECK])

        # application status not 100
        self.application.application_status = StatusLookupFactory(status_code=105)
        self.application.save()

        encrypter = encrypt()
        xid = encrypter.encode_string(str(self.application.application_xid))
        data = {
            'application_xid': self.application.application_xid,
            'xid': xid
        }
        response = self.client.post(self.endpoint, data=data, format='json')
        result = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], [ErrorMessageConst.CUSTOMER_HAS_REGISTERED])

    @override_settings(CRYPTOGRAPHY_KEY='QWvxJtgPh36mHJ9R8hn_5uFuaMCxQ5Yj6St2kQ4Mgkb=')
    def test_application_validation_success(self) -> None:
        encrypter = encrypt()
        xid = encrypter.encode_string(str(self.application.application_xid))
        data = {
            'application_xid': self.application.application_xid,
            'xid': xid
        }
        response = self.client.post(self.endpoint, data=data, format='json')
        result = response.json()
        self.assertEqual(result['success'], True)
        self.assertEqual(result['data']['nik'], self.application.ktp)
        self.assertEqual(result['data']['is_pin_created'], False)

        # Test for validate merchant financing
        CustomerPinFactory(user=self.application.customer.user)
        mf_application_xid = 'MF_{}'.format(self.application.application_xid)
        xid = encrypter.encode_string(mf_application_xid)
        response = self.client.post(self.endpoint, data=data, format='json')
        result = response.json()
        self.assertEqual(result['success'], True)
        self.assertEqual(result['data']['nik'], self.application.ktp)
        self.assertIsNotNone(result['data']['token'])
        self.assertEqual(result['data']['is_pin_created'], True)


class TestPartnershipLoanSimulation(TestCase):

    @patch('juloserver.partnership.models.get_redis_client')
    def setUp(self, _: MagicMock) -> None:
        self.user = AuthUserFactory()
        customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(user=self.user, is_active=True)
        self.partnership_type = PartnershipTypeFactory(
            partner_type_name='Whitelabel Paylater'
        )
        self.partnership_type2 = PartnershipTypeFactory(
            partner_type_name='Leadgen'
        )
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30]
        )
        PartnerLoanSimulationsFactory(partnership_config=self.partnership_config,
                                      interest_rate=0.03, tenure=1,
                                      is_active=True,
                                      origination_rate=0.05)
        PartnerLoanSimulationsFactory(partnership_config=self.partnership_config,
                                      interest_rate=0.06, tenure=2,
                                      is_active=True,
                                      origination_rate=0.05)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=self.partner
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="tokopedia"
        )
        self.endpoint = '/api/partnership/web/v1/calculate-loan?transaction_amount=100000'

    @patch('juloserver.partnership.views.get_redis_client')
    @patch('juloserver.partnership.views.store_partner_simulation_data_in_redis')
    @patch('juloserver.partnership.services.web_services.get_redis_client')
    def test_partner_loan_simulation_failed(self, calculate_mock: MagicMock,
                                             services_mock: MagicMock,
                                             _: MagicMock) -> None:

        mocked_redis_mock = MagicMock()
        stored_data = '[{"id": 2, "origination_rate": 0.06, "interest_rate": 0.03, "tenure": 1}]'
        mocked_redis_mock.get.return_value = stored_data
        calculate_mock.return_value = mocked_redis_mock

        # error not active loan simulation
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 400)
        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['Simulasi pinjaman tidak aktif, mohon hubungi JULO untuk mengaktifkan'])

        self.partnership_config.is_show_loan_simulations = True
        self.partnership_config.save(update_fields=['is_show_loan_simulations'])

        # error transaction amount not filled
        self.endpoint = '/api/partnership/web/v1/calculate-loan'
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 400)
        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['transaction_amount harus diisi'])

        # error transaction amount not valid
        self.endpoint = '/api/partnership/web/v1/calculate-loan?transaction_amount=dsadsad'
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 400)
        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['transaction_amount data tidak valid'])

        # Error partnership type not paylater
        self.partnership_config.partnership_type = self.partnership_type2
        self.partnership_config.save()
        self.endpoint = '/api/partnership/web/v1/calculate-loan?transaction_amount=100000'
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 400)
        result = response.json()
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['Partner tidak valid'])

    @patch('juloserver.partnership.views.get_redis_client')
    @patch('juloserver.partnership.views.store_partner_simulation_data_in_redis')
    @patch('juloserver.partnership.services.web_services.get_redis_client')
    def test_partner_loan_simulation_success(self, calculate_mock: MagicMock,
                                             services_mock: MagicMock,
                                             _: MagicMock) -> None:

        self.partnership_config.is_show_loan_simulations = True
        self.partnership_config.save(update_fields=['is_show_loan_simulations'])

        mocked_redis_mock = MagicMock()
        stored_data = '[{"id": 2, "origination_rate": 0.06, "interest_rate": 0.03, "tenure": 1}]'
        mocked_redis_mock.get.return_value = stored_data
        calculate_mock.return_value = mocked_redis_mock

        response = self.client.get(self.endpoint)
        result = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result['success'], True)
        self.assertEqual(result['data']['loan_offers_in_number'], [])
        self.assertEqual(result['data']['loan_offers_in_str'][0]['tenure'],
                         '1 Bulan')
        self.assertEqual(result['data']['loan_offers_in_str'][0]['monthly_installment'],
                         'Rp 109.000')

        amount = 'transaction_amount=100000'
        response_type = 'response_type=number'
        self.endpoint = (
            '/api/partnership/web/v1/calculate-loan?{}&{}'.format(amount, response_type)
        )
        response = self.client.get(self.endpoint)
        result = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result['success'], True)
        self.assertEqual(result['data']['loan_offers_in_str'], [])
        self.assertEqual(result['data']['loan_offers_in_number'][0]['tenure'],
                         1)
        self.assertEqual(result['data']['loan_offers_in_number'][0]['monthly_installment'],
                         109000)

        # Show interest
        self.partnership_config.is_show_interest_in_loan_simulations = True
        self.partnership_config.save(update_fields=['is_show_interest_in_loan_simulations'])

        amount = 'transaction_amount=100000'
        response_type = 'response_type=string'
        self.endpoint = (
            '/api/partnership/web/v1/calculate-loan?{}&{}'.format(amount, response_type)
        )
        response = self.client.get(self.endpoint)
        result = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result['success'], True)
        self.assertEqual(result['data']['loan_offers_in_number'], [])
        self.assertEqual(result['data']['loan_offers_in_str'][0]['monthly_interest_rate'],
                         'Bunga 3.0 %')

        amount = 'transaction_amount=100000'
        response_type = 'response_type=number'
        self.endpoint = (
            '/api/partnership/web/v1/calculate-loan?{}&{}'.format(amount, response_type)
        )
        response = self.client.get(self.endpoint)
        result = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result['success'], True)
        self.assertEqual(result['data']['loan_offers_in_str'], [])
        self.assertEqual(result['data']['loan_offers_in_number'][0]['monthly_interest_rate'],
                         3.0)


class TestTransactionDetails(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        response_register_partner_mf = register_partner_merchant_financing()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner_mf['secret_key'],
            HTTP_USERNAME=response_register_partner_mf['partner_name'],
        )
        self.customer = CustomerFactory(user=self.user,
                                   email="test4444@gmail.com",
                                   phone="084564654645")
        partner = Partner.objects.first()
        workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(customer=self.customer,
                                              workflow=workflow,
                                              mobile_phone_1="084564654645",
                                              partner=partner)
        self.account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='JULO1',
            payment_frequency='monthly'
        )

        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application.product_line = self.product_line
        self.application.save(update_fields=['product_line'])
        self.application.account = self.account
        self.application.save(update_fields=['account'])
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save(update_fields=['application_status_id'])
        self.feature_setting = FeatureSettingFactory()
        self.feature_setting.feature_name = FeatureNameConst.PARTNER_ELIGIBLE_USE_J1
        self.feature_setting.is_active = True
        self.feature_setting.parameters['partners'] = {
            "partners": {
                'name': partner.name,
                'is_active': True
            }
        }
        self.feature_setting.save()
        self.partnership_type = PartnershipTypeFactory(
            partner_type_name=PartnershipTypeConstant.WHITELABEL_PAYLATER)
        self.partnership_config = PartnershipConfigFactory(
            partner=partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30]
        )
        self.url = '/api/partnership/v1/transaction-details'
        self.data = {
            "email": self.customer.email,
            "mobile_phone": self.customer.phone,
            "partner_reference_id": "test3333",
            "transaction_amount": "100000",
            "kodepos": "11111",
            "kabupaten": "Test kabupaten",
            "provinsi": "Test Provinsi",
            "order_details": [
                {
                    "merchant_name": "test",
                    "products": [
                        {
                            "product_name": "testproduct1",
                            "product_qty": 1,
                            "product_price": 5.50
                        },
                        {
                            "product_name": "testproduct2",
                            "product_qty": 2,
                            "product_price": 10
                        }
                    ]
                }
            ]
        }
        self.partner = partner

    def test_get_transaction_details_required_partner_reference_id(self):
        del self.data['partner_reference_id']
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['partner_reference_id harus diisi'])

    def test_get_transaction_details_order_details_not_found(self):
        del self.data['order_details']
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['order details tidak ada'])

    def test_get_transaction_details_required_products(self):
        del self.data['order_details'][0]['products']
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['products wajib diisi'])

    def test_get_transaction_details_required_product_name(self):
        self.data['order_details'][0]['products'][0]['product_name'] = ''
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['nama produk wajib diisi'])

    def test_get_transaction_details_required_product_qty(self):
        self.data['order_details'][0]['products'][0]['product_qty'] = ''
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['qty wajib diisi'])

    def test_get_transaction_details_qty_must_be_number(self):
        self.data['order_details'][0]['products'][0]['product_qty'] = 'dfdsfdsf'
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['qty harus nomor'])

    def test_get_transaction_details_required_product_price(self):
        self.data['order_details'][0]['products'][0]['product_price'] = ""
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['price wajib diisi'])

    def test_get_transaction_details_price_must_be_number(self):
        self.data['order_details'][0]['products'][0]['product_price'] = "dgfdfg"
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['price harus nomor'])

    def test_get_transaction_details_invalid_email(self):
        self.data['email'] = "ddfgdfgdf"
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Email tidak valid'])

    def test_get_transaction_details_invalid_format_mobile_phone(self):
        self.data['mobile_phone'] = "435345"
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Mobile_phone format tidak sesuai'])

    def test_get_transaction_details_required_mobile_phone(self):
        self.data['mobile_phone'] = ""
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Mobile_phone tidak boleh kosong'])

    def test_get_transaction_details_without_transaction_amount(self):
        del self.data['transaction_amount']
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Transaction_amount harus diisi'])

    def test_get_transaction_details_with_invalid_transaction_amount(self):
        self.data['transaction_amount'] = "ddddd"
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Transaction_amount tidak valid'])

    def test_get_transaction_details_with_zero_transaction_amount(self):
        self.data['transaction_amount'] = "0"
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'],
                         ['Transaction_amount tidak dapat kurang dari sama dengan 0'])

    def test_get_transaction_details_success_case1(self):
        self.data['email'] = "test54@julo.co.id"
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

    def test_get_transaction_details_success_case2(self):
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

    def test_get_transaction_details_success_with_otp_page_in_webview_url(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save(update_fields=['application_status'])
        self.account.status_id = AccountConstant.STATUS_CODE.active
        self.account.save()
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)
        self.assertIn("paylater/otp", response.json()['data']['webview_url'])

    def test_get_transaction_details_success_with_payment_page_in_webview_url(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save(update_fields=['application_status'])
        self.account.status_id = AccountConstant.STATUS_CODE.active
        self.account.save()
        PartnerPropertyFactory(
            partner=self.partner,
            account=self.account,
            partner_reference_id="test3333",
            is_active=True,
        )
        response = self.client.post(self.url, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)
        self.assertIn("paylater/transactions", response.json()['data']['webview_url'])


class TestWebviewApplicationEmailOtpRequest(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner = register_partner_lead_gen()
        self.partner = Partner.objects.filter(name='partner_lead_gen').last()
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            is_validation_otp_checking=False
        )
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner['secret_key'],
            HTTP_USERNAME=response_register_partner['partner_name'],
        )
        self.partnership_type = PartnershipTypeFactory()
        new_julo1_product_line()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.partner_user = AuthUserFactory(username='test_email_otp')
        self.customer = CustomerFactory(user=self.partner_user, nik=3216070308950009)
        self.account = AccountFactory(customer=self.customer)
        CustomerPinFactory(user=self.partner_user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999889,
            partner=self.partner
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name = FeatureNameConst.EMAIL_OTP,
            parameters = {
                "otp_max_request": 3,
                "otp_resend_time": 60,
                "wait_time_seconds": 200,
            }
        )
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            email=self.customer.email,
            partner=self.partner,
            nik=self.customer.nik
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.save()
        self.application.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.partnership_customer_data.customer.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME=self.partnership_customer_data.partner.name
        )
        self.endpoint = '/api/partnership/web/v1/request-email-otp'

    def test_not_valid_nik(self) -> None:
        data = {
            "nik":"000000000001",
            "email": self.customer.email,
            "action_type": SessionTokenAction.LOGIN
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['NIK tidak memenuhi format yang dibutuhkan'])

    def test_not_valid_email(self) -> None:
        data = {
            "nik":self.partnership_customer_data.nik,
            "email": "bambang.com",
            "action_type": SessionTokenAction.LOGIN
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Email tidak valid'])

    def test_wrong_action_type(self) -> None:
        data = {
            "nik":self.customer.nik,
            "email": self.customer.email,
            "action_type": "hacking"
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["action_type only can be 'login' or 'register'"])

    def test_error_email_otp_not_activated(self) -> None:
        self.feature_setting.is_active = False
        self.feature_setting.save()
        self.feature_setting.refresh_from_db()

        data = {
            "nik":self.customer.nik,
            "email": self.customer.email,
            "action_type": SessionTokenAction.LOGIN
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['feature setting email otp tidak aktif'])

    def test_customer_data_not_found(self) -> None:
        data = {
            "nik": '3172012211941677',
            "email": "bambang@julofinance.com",
            "action_type": SessionTokenAction.LOGIN
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["Data tidak ditemukan"])

    @patch('juloserver.otp.tasks.send_email_otp_token')
    def test_success_send_email_otp_login(self, mock_process_send_email_otp_token) -> None:
        data = {
            "nik":self.customer.nik,
            "email": self.customer.email,
            "action_type": SessionTokenAction.LOGIN
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)
        self.assertEqual(response.json()['errors'], [])
        mock_process_send_email_otp_token.called_once()


    @patch('juloserver.otp.tasks.send_email_otp_token')
    def test_error_account_already_registered(self, mock_process_send_email_otp_token) -> None:
        self.partnership_customer_data.email_otp_status = PartnershipCustomerData.VERIFIED
        self.partnership_customer_data.save()
        self.partnership_customer_data.refresh_from_db()

        data = {
            "nik":self.customer.nik,
            "email": "bambang.new@julofinance.com",
            "action_type": SessionTokenAction.REGISTER
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'][0], 'Akun sudah terdaftar, silahkan langsung masuk ke akun Anda')
        self.assertFalse(mock_process_send_email_otp_token.called)

    @patch('juloserver.otp.tasks.send_email_otp_token')
    def test_success_send_email_otp_register(self, mock_process_send_email_otp_token) -> None:
        data = {
            "nik":self.customer.nik,
            "email": "bambang@gmail.com",
            "action_type": SessionTokenAction.REGISTER
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)
        self.assertEqual(response.json()['errors'], [])
        mock_process_send_email_otp_token.called_once()


class TestWebviewEmailOtpConfirmation(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner = register_partner_lead_gen()
        self.partner = Partner.objects.filter(name='partner_lead_gen').last()
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            is_validation_otp_checking=False
        )
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner['secret_key'],
            HTTP_USERNAME=response_register_partner['partner_name'],
        )
        self.partnership_type = PartnershipTypeFactory()
        new_julo1_product_line()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.partner_user = AuthUserFactory(username='test_email_otp')
        self.customer = CustomerFactory(user=self.partner_user, nik=3216070308950009)
        self.account = AccountFactory(customer=self.customer)
        CustomerPinFactory(user=self.partner_user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999889,
            partner=self.partner
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name = FeatureNameConst.EMAIL_OTP,
            parameters = {
                "otp_max_request": 3,
                "otp_resend_time": 60,
                "wait_time_seconds": 200,
            }
        )
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            email=self.customer.email,
            partner=self.partner,
            nik=self.customer.nik
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.save()
        self.application.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.partnership_customer_data.customer.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME=self.partnership_customer_data.partner.name
        )
        self.endpoint = '/api/partnership/web/v1/confirm-email-otp'


    def test_not_valid_email(self) -> None:
        data = {
            "otp_token": '123213',
            "email": "bambang.com",
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Email tidak valid'])

    def test_wrong_otp_format(self) -> None:
        data = {
            "otp_token": 'a12345',
            "email": self.partnership_customer_data.email,
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Otp token harus angka'])

    def test_error_email_otp_not_activated(self) -> None:
        self.feature_setting.is_active = False
        self.feature_setting.save()
        self.feature_setting.refresh_from_db()
        data = {
            "otp_token": '123213',
            "email": self.partnership_customer_data.email,
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

    def test_customer_data_not_found(self) -> None:
        data = {
            "otp_token": '123213',
            "email": 'test@test.com',
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'][0], "Data tidak ditemukan")

    @patch('juloserver.otp.tasks.send_email_otp_token')
    def test_success_send_email_otp_register(self, mock_process_send_email_otp_token) -> None:
        otp_request = OtpRequestFactory()
        otp_request.action_type = 'register'
        otp_request.partnership_customer_data = self.partnership_customer_data
        otp_request.cdate = timezone.now().date().replace(2099, 12, 30)
        otp_request.request_id = 311656490469
        otp_request.otp_token = 458185
        otp_request.save()
        partnership_customer_data_otp = PartnershipCustomerDataOTPFactory(
            partnership_customer_data=self.partnership_customer_data
        )
        partnership_customer_data_otp.otp_type = 'email'
        partnership_customer_data_otp.save()
        data = {
            "otp_token": '458185',
            "email": self.partnership_customer_data.email,
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)
        self.assertEqual(response.json()['errors'], [])
        mock_process_send_email_otp_token.called_once()


class TestLeadgenResetPinView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.data = {
            'email': 'dummy'
        }
        self.endpoint = '/api/partnership/web/v1/reset-pin'

    def test_failed_email_not_valid(self):
        self.data = {
            'email': 'dummy'
        }
        response = self.client.post(
            self.endpoint,
            data=self.data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual('Email tidak valid', response.json()['errors'][0])

    @patch('juloserver.partnership.views.RedisCache')
    def test_failed_email_not_found(self, mock_redis_cache):
        self.data = {
            'email': 'test_test@julofinance.com'
        }
        mock_redis_cache().get.return_value = None
        response = self.client.post(
            self.endpoint,
            data=self.data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual('Email tidak terdaftar', response.json()['errors'][0])

    @patch('juloserver.partnership.views.RedisCache')
    def test_failed_user_pin_not_exist(self, mock_redis_cache):
        self.data = {
            'email': self.customer.email
        }
        mock_redis_cache().get.return_value = None
        response = self.client.post(
            self.endpoint,
            data=self.data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual('User belum memiliki pin', response.json()['errors'][0])

    @patch('juloserver.partnership.views.RedisCache')
    def test_failed_email_already_sent(self, mock_redis_cache):
        self.data = {
            'email': self.customer.email
        }
        mock_redis_cache().get.return_value = True
        response = self.client.post(
            self.endpoint,
            data=self.data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            'Email sudah dikirim, mohon tunggu selama 30 menit '
            'sebelum melakukan request untuk reset pin',
            response.json()['errors'][0]
        )

    @patch('juloserver.partnership.services.web_services.RedisCache')
    @patch('juloserver.partnership.views.RedisCache')
    def test_success_email_sent(self, mock_redis_cache_view, mock_redis_cache_services):
        self.customer_pin = CustomerPinFactory(user=self.user)
        self.data = {
            'email': self.customer.email
        }
        mock_redis_cache_view().get.return_value = None
        response = self.client.post(
            self.endpoint,
            data=self.data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ResetMessage.PIN_RESPONSE, response.json()['data'])


class TestLeadgenApplicationUpdateView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id='123123123', customer=self.customer)
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="mobile_phone_1_otp"
        )
        self.product_line = ProductLineFactory()
        self.product_line2 = ProductLineFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.path = '/api/partnership/web/v1/application/123123123/'
        self.data = {
            "web_version": "0.0.1",
            "product_line_code": None,
            "mantri_id": None,
            "can_show_status": True,
            "loc_id": None,
            "have_facebook_data": False,
            "validated_qr_code": False,
            "marketing_source": None,
            "loan_amount_request": None,
            "loan_duration_request": None,
            "is_own_phone": "",
            "new_mobile_phone": None,
            "has_whatsapp_1": "",
            "has_whatsapp_2": "",
            "bbm_pin": "",
            "twitter_username": None,
            "instagram_username": None,
            "spouse_dob": None,
            "spouse_has_whatsapp": None,
            "job_function": None,
            "income_1": None,
            "income_2": None,
            "income_3": None,
            "college": None,
            "major": None,
            "graduation_year": None,
            "gpa": None,
            "has_other_income": False,
            "other_income_amount": None,
            "other_income_source": None,
            "kin_dob": None,
            "kin_gender": "",
            "work_kodepos": None,
            "vehicle_type_1": None,
            "vehicle_ownership_1": None,
            "bank_branch": None,
            "name_in_bank": None,
            "is_document_submitted": None,
            "is_sphp_signed": None,
            "sphp_exp_date": None,
            "application_number": 1,
            "gmail_scraped_status": "Not scraped",
            "is_courtesy_call": False,
            "hrd_name": None,
            "company_address": None,
            "number_of_employees": None,
            "position_employees": None,
            "employment_status": None,
            "billing_office": None,
            "mutation": None,
            "dialect": None,
            "teaser_loan_amount": None,
            "is_deleted": None,
            "status_path_locked": None,
            "additional_contact_1_name": None,
            "additional_contact_1_number": None,
            "additional_contact_2_name": None,
            "additional_contact_2_number": None,
            "loan_purpose_description_expanded": None,
            "is_fdc_risky": None,
            "address_same_as_ktp": None,
            "is_address_suspicious": None,
            "landlord_mobile_phone": None,
            "customer": self.customer.id,
            "partner_name": "cermati",
            "email": self.customer.email,
            "ktp": self.customer.nik,
            "fullname": "PROD ONLY",
            "birth_place": "Jakarta",
            "dob": "1990-01-01",
            "gender": "Pria",
            "address_street_num": "Jalan Testing 12312312312",
            "address_provinsi": "DKI Jakarta",
            "address_kabupaten": "Kota Jakarta Barat",
            "address_kecamatan": "Taman Sari",
            "address_kelurahan": "Glodok",
            "occupied_since": "1990-01-01",
            "home_status": "Milik keluarga",
            "mobile_phone_1": "0813123123123",
            "marital_status": "Lajang",
            "dependent": "0",
            "close_kin_name": "ORANG TUA",
            "close_kin_mobile_phone": "0812313123",
            "close_kin_relationship": None,
            "kin_relationship": "Orang tua",
            "kin_name": "Orang tauaaa",
            "kin_mobile_phone": "08213123123",
            "spouse_name": "",
            "spouse_mobile_phone": "",
            "job_type": "Pegawai swasta",
            "job_industry": "Admin / Finance / HR",
            "job_description": "Admin",
            "company_name": "PT. 180 Kreatif Indonesia",
            "company_phone_number": "0213213213213",
            "job_start": "1990-01-01",
            "payday": "4",
            "last_education": "S1",
            "loan_purpose": "Modal usaha",
            "loan_purpose_desc": "Idsouahdiuasgh diasgiydgasidasod asoidasoida",
            "monthly_income": "10000000",
            "monthly_housing_cost": "0",
            "monthly_expenses": "500000",
            "total_current_debt": "0",
            "bank_name": "BANK CENTRAL ASIA, Tbk (BCA)",
            "bank_account_number": "213123123",
            "is_term_accepted": True,
            "is_verification_agreed": True,
            "customer_mother_maiden_name": "Ibu Kanduang",
            "longitude": 106.8532497,
            "latitude": -6.2473653
        }

    @patch('juloserver.partnership.views.populate_zipcode')
    @patch('juloserver.partnership.views.process_application_status_change')
    def test_success_update(self, mock_process_application_status_change,
                            mock_populate_zipcode):
        self.application.application_status_id = 100
        self.application.save()
        self.mobile_feature_setting.is_active = False
        self.mobile_feature_setting.save()
        response = self.client.patch(
            self.path,
            data=self.data,
            format='json')
        self.application.refresh_from_db()
        self.assertEqual(str(self.application.payday), self.data['payday'])
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('juloserver.partnership.views.populate_zipcode')
    @patch('juloserver.partnership.views.process_application_status_change')
    def test_success_update_jobless(self, mock_process_application_status_change: MagicMock,
                                    _: MagicMock) -> None:
        self.application.application_status_id = 100
        self.application.save()
        self.mobile_feature_setting.is_active = False
        self.mobile_feature_setting.save()
        self.data['payday'] = None
        self.data['job_type'] = 'Ibu rumah tangga'
        response = self.client.patch(
            self.path,
            data=self.data,
            format='json')
        self.application.refresh_from_db()
        self.assertEqual(self.application.payday, 1)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch('juloserver.partnership.views.populate_zipcode')
    @patch('juloserver.partnership.views.process_application_status_change')
    def test_fail_incorrect_nik(self, mock_process_application_status_change,
                            mock_populate_zipcode):
        self.application.application_status_id = 100
        self.application.save()
        self.mobile_feature_setting.is_active = False
        self.mobile_feature_setting.save()
        self.data['ktp'] = '3525013006580042'
        response = self.client.patch(
            self.path,
            data=self.data,
            format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('juloserver.partnership.views.populate_zipcode')
    @patch('juloserver.partnership.views.process_application_status_change')
    def test_fail_incorrect_email(self, mock_process_application_status_change,
                            mock_populate_zipcode):
        self.application.application_status_id = 100
        self.application.save()
        self.mobile_feature_setting.is_active = False
        self.mobile_feature_setting.save()
        self.data['email'] = 'test@test.com'
        response = self.client.patch(
            self.path,
            data=self.data,
            format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('juloserver.partnership.views.populate_zipcode')
    @patch('juloserver.partnership.views.process_application_status_change')
    def test_fail_invalidated_otp(self, mock_process_application_status_change,
                            mock_populate_zipcode):
        self.application.application_status_id = 100
        self.application.save()
        response = self.client.patch(
            self.path,
            data=self.data,
            format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fail_application_status_invalid(self):
        self.application.application_status_id = 105
        self.application.save()
        response = self.client.patch(self.path, data=self.data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


def get_paylater_initialization_credentials(client):
    user = AuthUserFactory()
    client.force_login(user)
    client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
    response_register_partner_mf = register_partner_merchant_financing()
    client.credentials(
        HTTP_SECRET_KEY=response_register_partner_mf['secret_key'],
        HTTP_USERNAME=response_register_partner_mf['partner_name'],
    )
    customer = CustomerFactory(user=user,
                                    email="test44445@gmail.com",
                                    phone="084564654647")
    partner = Partner.objects.first()
    workflow = WorkflowFactory(
        name=WorkflowConst.JULO_ONE,
        handler='JuloOneWorkflowHandler'
    )
    product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
    application = ApplicationFactory(customer=customer,
                                          workflow=workflow,
                                          mobile_phone_1="084564654647",
                                          partner=partner)
    account_lookup = AccountLookupFactory(
        workflow=workflow,
        name='JULO1',
        payment_frequency='monthly'
    )

    account = AccountFactory(
        customer=customer,
        account_lookup=account_lookup,
        cycle_day=1
    )
    application.product_line = product_line
    application.save(update_fields=['product_line'])
    application.account = account
    application.save(update_fields=['account'])
    application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
    application.save(update_fields=['application_status_id'])
    feature_setting = FeatureSettingFactory()
    feature_setting.feature_name = FeatureNameConst.PARTNER_ELIGIBLE_USE_J1
    feature_setting.is_active = True
    feature_setting.parameters['partners'] = {
        "partners": {
            'name': partner.name,
            'is_active': True
        }
    }
    feature_setting.save()
    partnership_type = PartnershipTypeFactory(
        partner_type_name=PartnershipTypeConstant.WHITELABEL_PAYLATER)
    PartnershipConfigFactory(
        partner=partner,
        partnership_type=partnership_type,
        loan_duration=[3, 7, 14, 30]
    )
    data = {
        "email": customer.email,
        "mobile_phone": customer.phone,
        "partner_reference_id": "test33334",
        "transaction_amount": "100000",
        "kodepos": "11111",
        "kabupaten": "Test kabupaten",
        "provinsi": "Test Provinsi",
        "order_details": [
            {
                "merchant_name": "test",
                "products": [
                    {
                        "product_name": "testproduct1",
                        "product_qty": 1,
                        "product_price": 5.50
                    }
                ]
            }
        ]
    }
    response = client.post(
        '/api/partnership/v1/transaction-details', data=data, format='json')
    return response, customer


class TestPaylaterApplicationDetails(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.response_credential, self.customer = get_paylater_initialization_credentials(self.client)
        self.endpoint = '/api/partnership/web/v1/whitelabel-paylater-application/details/'

    def test_get_paylater_application_details_incorrect_secret_key(self):
        self.client.credentials(
            HTTP_SECRET_KEY='XOgR4GrCMFuhWSdsqd__'
        )
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Invalid Key Error'])

    def test_get_paylater_application_details_no_secret_key(self):
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Invalid Key Error'])

    def test_get_paylater_application_details_success(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

    def test_get_vospay_application_details_success(self):
        self.response_credential, self.customer = get_initialized_data_whitelabel_credentials(self.client)
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestPaylaterCheckUserView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.response_credential, self.customer = get_paylater_initialization_credentials(self.client)
        self.data = {
            "email": self.customer.email,
            "phone": self.customer.phone
        }


    def test_paylater_check_user_with_incorrect_secret_key(self):
        self.client.credentials(
            HTTP_SECRET_KEY='XOgR4GrCMFuhWSdsqd__'
        )
        response = self.client.post(
             '/api/partnership/web/v1/check-user/', data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Invalid Key Error'])

    def test_paylater_check_user_with_no_secret_key(self):
        response = self.client.post(
            '/api/partnership/web/v1/check-user/', data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Invalid Key Error'])

    def test_paylater_check_user_with_no_data(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )
        response = self.client.post(
            '/api/partnership/web/v1/check-user/', data={}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Phone harus diisi'])

    def test_paylater_check_user_with_no_email(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )
        self.data1 = {
            "email": "",
            "phone": self.customer.phone
        }
        response = self.client.post(
            '/api/partnership/web/v1/check-user/', data=self.data1, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Email tidak boleh kosong'])


    def test_paylater_check_user_with_no_phone(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )
        self.data1 = {
            "email": self.customer.email,
            "phone": ""
        }
        response = self.client.post(
            '/api/partnership/web/v1/check-user/', data=self.data1, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Phone tidak boleh kosong'])


    def test_paylater_check_user_success(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )
        response = self.client.post(
            '/api/partnership/web/v1/check-user/', data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestPartnerDetailsView(TestCase):

    def setUp(self) -> None:
        self.user = AuthUserFactory()
        customer = CustomerFactory(user=self.user,
                                   fullname="tokopedia")
        self.partner = PartnerFactory(user=self.user,
                                      name="tokopedia",
                                      is_active=True)
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=customer,
            partner=self.partner
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="tokopedia"
        )
        self.endpoint = '/api/partnership/web/v1/details'

    def test_get_partner_details(self) -> None:
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)
        data = response.json()['data']
        self.assertEqual(data['name'], self.partner.name)
        self.assertEqual(data['email'], self.partner.email)
        self.assertEqual(data['company_name'], self.partner.company_name)
        self.assertEqual(data['company_address'], self.partner.company_address)


def update_paylater_transaction_status(paylater_transaction_xid):
    paylater_transaction = PaylaterTransaction.objects.filter(
        paylater_transaction_xid=paylater_transaction_xid
    ).select_related('paylater_transaction_status').last()
    if paylater_transaction:
        if hasattr(paylater_transaction, "paylater_transaction_status"):
            in_progess_status = PaylaterTransactionStatuses.IN_PROGRESS
            paylater_transaction.update_transaction_status(in_progess_status)
        else:
            PaylaterTransactionStatusFactory(
                paylater_transaction=paylater_transaction,
                transaction_status=PaylaterTransactionStatuses.IN_PROGRESS
            )


class TestWhitelabelApplicationOtpValidation(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.response_credential, self.customer = get_paylater_initialization_credentials(self.client)
        MobileFeatureSettingFactory(
            feature_name='mobile_phone_1_otp',
            parameters={
                "otp_max_request": 3,
                "otp_resend_time": 60,
                "wait_time_seconds": 300,
                "otp_max_validate": 3
            },
            is_active=True
        )
        postfixed_request_id = str(self.customer.id) + str(int(time.time()))
        self.otp = OtpRequestFactory(
            is_used=False,
            customer=self.customer,
            request_id=postfixed_request_id,
            action_type=SessionTokenAction.PAYLATER_LINKING
        )

    def test_validate_otp_for_invalid_otp_token_attempt1(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )
        self.data = {
            "otp_token": 377506,
            "phone": self.customer.phone
        }
        response = self.client.post(
             '/api/partnership/web/v1/whitelabel-paylater-application/validate-otp/', data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['error_message'],
                         "OTP tidak sesuai, coba kembali")

    def test_validate_otp_for_invalid_otp_token_attempt2(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )
        self.data = {
            "otp_token": 377506,
            "phone": self.customer.phone
        }
        self.otp.retry_validate_count = 2
        self.otp.save(update_fields=['retry_validate_count'])
        response = self.client.post(
             '/api/partnership/web/v1/whitelabel-paylater-application/validate-otp/', data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['error_message'],
                         "Kesempatan mencoba OTP sudah habis, coba kembali beberapa saat lagi")

    def test_validate_otp_for_max_validate_count_exceed(self):
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )
        self.data = {
            "otp_token": 377506,
            "phone": self.customer.phone
        }
        self.otp.retry_validate_count = 3
        self.otp.save(update_fields=['retry_validate_count'])
        response = self.client.post(
             '/api/partnership/web/v1/whitelabel-paylater-application/validate-otp/', data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['error_message'],
                         "Kesempatan mencoba OTP sudah habis, coba kembali beberapa saat lagi")


class TestPaylaterProductDetails(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        self.response_register_partner_mf = register_partner_merchant_financing()
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_register_partner_mf['secret_key'],
            HTTP_USERNAME=self.response_register_partner_mf['partner_name'],
        )
        customer = CustomerFactory(user=user)
        partner = Partner.objects.first()
        workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(customer=customer,
                                              workflow=workflow,
                                              mobile_phone_1=customer.phone,
                                              partner=partner)
        account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='JULO1',
            payment_frequency='monthly'
        )

        account = AccountFactory(
            customer=customer,
            account_lookup=account_lookup,
            cycle_day=1
        )
        self.application.product_line = product_line
        self.application.save(update_fields=['product_line'])
        self.application.account = account
        self.application.save(update_fields=['account'])
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save(update_fields=['application_status_id'])
        feature_setting = FeatureSettingFactory()
        feature_setting.feature_name = FeatureNameConst.PARTNER_ELIGIBLE_USE_J1
        feature_setting.is_active = True
        feature_setting.parameters['partners'] = {
            "partners": {
                'name': partner.name,
                'is_active': True
            }
        }
        feature_setting.save()
        self.partnership_type = PartnershipTypeFactory(
            partner_type_name=PartnershipTypeConstant.WHITELABEL_PAYLATER)
        self.partnership_config = PartnershipConfigFactory(
            partner=partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30]
        )
        self.paylater_transaction = PaylaterTransactionFactory(
                                         partner_reference_id=67567567567,
                                         transaction_amount=50000,
                                         paylater_transaction_xid="1234567890",
                                         partner=partner)
        PaylaterTransactionDetailsFactory(
            paylater_transaction=self.paylater_transaction,
            merchant_name="merchant test",
            product_name="test product1",
            product_qty=1,
            product_price=50000)
        self.url = '/api/partnership/web/v1/paylater-product-details'

    def test_paylater_product_details_with_incorrect_secret_key(self):
        self.client.credentials(
            HTTP_SECRET_KEY='XOgR4GrCMFuhWSdsqd__'
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['detail'], 'kredensial tidak valid')

    def test_paylater_product_details_without_username_credential(self):
        self.client.credentials(HTTP_SECRET_KEY=self.response_register_partner_mf['secret_key'])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['detail'], 'partner tidak valid')

    def test_paylater_product_details_without_paylater_transaction_xid(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Invalid paylater_transaction_xid'])

    def test_paylater_product_details_with_incorrect_paylater_transaction_xid(self):
        response = self.client.get(self.url +
                                   '?paylater_transaction_xid=435345&application_xid={}'.
                                   format(self.application.application_xid))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['paylater_transaction_xid tidak ditemukan'])

    def test_paylater_product_details_with_incorrect_application_xid(self):
        response = self.client.get(self.url +
                                   '?paylater_transaction_xid=' +
                                   self.paylater_transaction.paylater_transaction_xid +
                                   '&application_xid=345435')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Aplikasi tidak ditemukan'])

    def test_paylater_product_details_success(self):
        response = self.client.get(self.url +
                                   '?paylater_transaction_xid={}&application_xid={}'.
                                   format(self.paylater_transaction.paylater_transaction_xid,
                                           self.application.application_xid))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestPaylaterTransactionStatusView(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.user2 = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer2 = CustomerFactory(user=self.user2)
        self.partner = PartnerFactory(user=self.user, is_active=True)
        self.partner2 = PartnerFactory(user=self.user2, is_active=True)
        self.partnership_type = PartnershipTypeFactory(
            partner_type_name='Whitelabel Paylater'
        )
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30]
        )
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            ktp='1111222233334444',
            customer=self.customer,
            workflow=self.workflow,
            application_xid=999991111,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                application=self.application,
                                loan_amount=500_000, loan_xid=1000003456)
        self.paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id='900878712',
            transaction_amount=500_000,
            paylater_transaction_xid=9000988821,
            partner=self.partner
        )
        self.paylater_transaction_details = PaylaterTransactionDetailsFactory(
            merchant_name='Toko 1',
            product_name='Nvidia GTX 1660',
            product_qty=1,
            product_price=250_000,
            paylater_transaction=self.paylater_transaction
        )
        self.paylater_transaction_details2 = PaylaterTransactionDetailsFactory(
            merchant_name='Toko 1',
            product_name='Nvidia GTX 1550',
            product_qty=1,
            product_price=250_000,
            paylater_transaction=self.paylater_transaction
        )
        self.paylater_transaction_status = PaylaterTransactionStatusFactory(
            paylater_transaction=self.paylater_transaction,
            transaction_status=PaylaterTransactionStatuses.IN_PROGRESS
        )
        self.paylater_transaction_loan = PaylaterTransactionLoanFactory(
            paylater_transaction=self.paylater_transaction,
            loan=self.loan
        )
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer,
            partner=self.partner
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_USERNAME="tokopedia"
        )
        self.endpoint = '/api/partnership/v1/paylater-transaction-status'

    def test_paylater_transaction_status_error(self) -> None:
        data = {
            "paylater_transaction_xid": self.paylater_transaction.paylater_transaction_xid
        }

        # error paylater transaction status not found
        self.paylater_transaction_status.delete()
        response = self.client.get(self.endpoint, data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'], ['Invalid data, paylater transaction status not found'])

        # error Unauthorized access
        self.paylater_transaction.partner = self.partner2
        self.paylater_transaction.save(update_fields=['partner'])
        response = self.client.get(self.endpoint, data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'], ['Unauthorized access'])

        # error paylater transaction not found
        self.paylater_transaction.partner = self.partner
        self.paylater_transaction.save(update_fields=['partner'])
        data['paylater_transaction_xid'] = 11111111
        response = self.client.get(self.endpoint, data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'], ['Paylater Transaction not found'])

    def test_paylater_transaction_status_success(self) -> None:
        data = {
            "paylater_transaction_xid": self.paylater_transaction.paylater_transaction_xid
        }
        response = self.client.get(self.endpoint, data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)

        response_data = response.json()['data']
        self.assertEqual(response_data['amount'], round(self.paylater_transaction.transaction_amount))
        self.assertEqual(response_data['loan_xid'], self.loan.loan_xid)
        self.assertEqual(response_data['account_id'], self.account.id)
        self.assertEqual(response_data['status'],
                         self.paylater_transaction_status.transaction_status)

        paylater_product_details_format = [
            {
                'merchant_name': self.paylater_transaction_details.merchant_name,
                'products': [
                    {
                        'product_name': self.paylater_transaction_details.product_name,
                        'qty': self.paylater_transaction_details.product_qty,
                        'price': round(self.paylater_transaction_details.product_price)
                    },
                    {
                        'product_name': self.paylater_transaction_details2.product_name,
                        'qty': self.paylater_transaction_details2.product_qty,
                        'price': round(self.paylater_transaction_details2.product_price)
                    },
                ]
            }
        ]

        self.assertEqual(response_data['paylater_details'], paylater_product_details_format)


class TestLoanPartnerView(TestCase):
    BASE_PATH = 'juloserver.partnership.services.services.'
    BANK_DESTINATION_MOCK = BASE_PATH + 'get_bank_account_destination_by_transaction_method_partner'
    MATRIX_PRODUCT_LINE = BASE_PATH + 'get_credit_matrix_and_credit_matrix_product_line'

    def setUp(self) -> None:
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner = register_partner_lead_gen()
        self.partner = Partner.objects.filter(name='partner_lead_gen').last()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner['secret_key'],
            HTTP_USERNAME=response_register_partner['partner_name'],
        )
        self.partnership_type = PartnershipTypeFactory()
        new_julo1_product_line()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.partner_user = AuthUserFactory(username='test_lead_gen_offer')
        self.customer = CustomerFactory(user=self.partner_user)
        # Should be set a account status, because there is rule for check account status
        status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=status)
        expiry_time = timezone.now() + timedelta(days=1)
        customer_pin = CustomerPinFactory(user=self.partner_user)
        CustomerPinVerifyFactory(
            customer=self.customer,
            is_pin_used=False,
            expiry_time=expiry_time,
            customer_pin=customer_pin)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999889,
            partner=self.partner
        )
        self.paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id='900878712',
            transaction_amount=500_000,
            paylater_transaction_xid=9000988821,
            partner=self.partner
        )
        self.paylater_transaction_details = PaylaterTransactionDetailsFactory(
            merchant_name='Toko 1',
            product_name='Nvidia GTX 1660',
            product_qty=1,
            product_price=250_000,
            paylater_transaction=self.paylater_transaction
        )
        self.paylater_transaction_details2 = PaylaterTransactionDetailsFactory(
            merchant_name='Toko 1',
            product_name='Nvidia GTX 1550',
            product_qty=1,
            product_price=250_000,
            paylater_transaction=self.paylater_transaction
        )
        self.paylater_transaction_status = PaylaterTransactionStatusFactory(
            paylater_transaction=self.paylater_transaction,
            transaction_status=PaylaterTransactionStatuses.IN_PROGRESS
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.save()
        self.application.save()
        self.bank = BankFactory(xfers_bank_code='HELLOQWE')
        bank_account_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(bank_code='HELLOQWE')
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False
        )
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                application=self.application,
                                loan_amount=10000000, loan_xid=1000003456)
        self.endpoint = '/api/partnership/v1/loan/{}'.format(
            self.application.application_xid
        )

    def test_paylater_loan_partner_status_changed_with_invalid_transaction_type(self) -> None:
        data = {
            'self_bank_account': False,
            'transaction_type_code': 8,
            'loan_duration': 3,
            'loan_amount_request': self.paylater_transaction.transaction_amount,
        }
        response = self.client.post(
            self.endpoint, data=data, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Transaction_type_code data tidak valid'])

    @mock.patch('juloserver.partnership.services.services.generate_loan_payment_julo_one')
    @mock.patch(BANK_DESTINATION_MOCK)
    @mock.patch(MATRIX_PRODUCT_LINE)
    def test_paylater_loan_partner_status_changed(self, credit_matrix_mock: MagicMock,
                                                  bank_account_destination_mock: MagicMock,
                                                  loan_mock: MagicMock) -> None:
        credit_matrix_mock.return_value = self.credit_matrix, self.credit_matrix_product_line
        bank_account_destination_mock.return_value = self.bank_account_destination
        loan_mock.return_value = self.loan

        data = {
            'account_id': self.account.id,
            'self_bank_account': False,
            'transaction_type_code': 2,
            'paylater_transaction_xid': self.paylater_transaction.paylater_transaction_xid,
            'loan_duration': 3,
            'loan_amount_request': self.paylater_transaction.transaction_amount,
        }

        response = self.client.post(
            self.endpoint, data=data, format='json'
        )

        # status is still in progress
        self.paylater_transaction_status.refresh_from_db()
        self.assertEqual(self.paylater_transaction_status.transaction_status,
                         PaylaterTransactionStatuses.IN_PROGRESS)
        if hasattr(self.paylater_transaction, "transaction_loan"):
            paylater_has_loan = True
        else:
            paylater_has_loan = False
        self.assertEqual(paylater_has_loan, True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

        # Will be return 400, because need to verify again the request
        response = self.client.post(
            self.endpoint, data=data, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)


class WhitelabelInputPinView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.response_credential, self.customer = get_paylater_initialization_credentials(self.client)
        self.data = {
            "email": self.customer.email,
            "phone": self.customer.phone
        }
        self.user = self.customer.user
        self.user.set_password('123123')
        self.user.save()
        CustomerPinFactory(user=self.user)
        BankAccountCategoryFactory(
            category=BankAccountCategoryConst.PARTNER,
            parent_category_id=1,
        )
        self.endpoint = '/api/partnership/web/v1/whitelabel-paylater-input-pin/'

    def test_fail_input_pin_view(self) -> None:
        data = {
            'pin': '123123'
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_success_input_pin_view(self) -> None:
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )
        paylater_transaction_xid = self.response_credential.json()['data']['paylater_transaction_xid']
        data = {
            'pin': '123123'
        }
        paylater_transaction = PaylaterTransaction.objects.filter(
            paylater_transaction_xid=paylater_transaction_xid
        ).last()
        paylater_status = paylater_transaction.paylater_transaction_status

        self.assertEqual(paylater_status.transaction_status, PaylaterTransactionStatuses.INITIATE)
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.json()['success'], True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        paylater_transaction.refresh_from_db()
        paylater_status.refresh_from_db()
        self.assertEqual(paylater_status.transaction_status, PaylaterTransactionStatuses.IN_PROGRESS)


class TestPartnerVospayLoanCreation(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner = register_partner_lead_gen()
        self.partner = Partner.objects.filter(name='partner_lead_gen').last()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner['secret_key'],
            HTTP_USERNAME=response_register_partner['partner_name'],
        )
        self.partnership_type = PartnershipTypeFactory()
        new_julo1_product_line()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.partner_user = AuthUserFactory(username='test_lead_gen')
        self.customer = CustomerFactory(user=self.partner_user)
        status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=status)
        self.customer_pin = CustomerPinFactory(user=self.partner_user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999997887,
            partner=self.partner
        )
        expiry_time = timezone.now() + timedelta(days=1)
        CustomerPinVerify.objects.create(
            customer=self.application.customer,
            is_pin_used=False,
            customer_pin=self.customer_pin,
            expiry_time=expiry_time
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.save()
        self.application.save()
        name_bank_validation = NameBankValidationFactory(
            bank_code='TEST-BANK',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_category = BankAccountCategoryFactory(
            category='partner',
            display_label='Pribadi',
            parent_category_id=1
        )
        PartnerBankAccountFactory(
            partner=self.application.partner,
            name_bank_validation_id=name_bank_validation.id,
            bank_account_number=9999991
        )
        bank = BankFactory(xfers_bank_code=name_bank_validation.bank_code)
        BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=bank,
            name_bank_validation=name_bank_validation,
            account_number='12345',
            is_deleted=False
        )
        self.url = '/api/partnership/v1/loan/'

    @patch('juloserver.moengage.services.use_cases.update_moengage_for_user_linking_status.delay')
    @mock.patch('juloserver.partnership.services.services.'
                'get_credit_matrix_and_credit_matrix_product_line')
    def test_success_create_loan_vospay(self, mocked_credit_matrix,
                                        mock_update_moengage_for_user_linking_status):
        self.data = {
            "loan_amount_request": 300000,
            "loan_duration": 4,
            "partner_origin_name": "Blibli"
        }
        mocked_credit_matrix.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        partnership_api_log = PartnershipApiLogFactory(
            partner=self.partner
        )
        PartnerOriginFactory(
            partner=self.partner,
            partner_origin_name='Blibli',
            partnership_api_log=partnership_api_log
        )
        response = self.client.post(
            '{}{}'.format(self.url, self.application.application_xid), data=self.data)
        self.assertEqual(response.status_code, HTTPStatus.OK)


def get_initialized_data_whitelabel_credentials(client):
    user = AuthUserFactory()
    customer = CustomerFactory(user=user, phone='084564654647')
    client.force_login(user)
    client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
    response_register_partner_paylater = register_partner_paylater(client)
    client.credentials(
        HTTP_SECRET_KEY=response_register_partner_paylater.json()['data']['secret_key'],
        HTTP_USERNAME=response_register_partner_paylater.json()['data']['partner_name'],
    )
    endpoint = '/api/partnership/v1/whitelabel-handshake'
    partner = Partner.objects.first()
    payload = {
        "email": customer.email,
        "phone_number": "084564654647",
        "partner_reference_id": "usertoko1099",
        "partner_origin_name": "marketplace999"
    }
    payload['partner_origin_name'] = None
    workflow = WorkflowFactory(
        name=WorkflowConst.JULO_ONE,
        handler='JuloOneWorkflowHandler'
    )
    product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
    application = ApplicationFactory(customer=customer,
                                     workflow=workflow,
                                     mobile_phone_1="084564654647",
                                     partner=partner)
    account_lookup = AccountLookupFactory(
        workflow=workflow,
        name='JULO1',
        payment_frequency='monthly'
    )

    account = AccountFactory(
        customer=customer,
        account_lookup=account_lookup,
        cycle_day=1
    )
    application.product_line = product_line
    application.save(update_fields=['product_line'])
    application.account = account
    application.save(update_fields=['account'])
    application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
    application.save(update_fields=['application_status_id'])
    account.status = StatusLookupFactory(status_code=420)
    account.save()
    response = client.post(
        endpoint,
        data=payload,
        format='json'
    )
    return response, customer


class TestWhiteLabelPaylaterCheckUserView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.response_credential, self.customer = get_initialized_data_whitelabel_credentials(self.client)
        self.endpoint = '/api/partnership/web/v1/check-user/'

    def test_check_white_label_paylater_user(self) -> None:
        self.data = {
            "email": self.customer.email,
            "phone": self.customer.phone
        }
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )

        response = self.client.post(self.endpoint, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestWhiteLabelPaylaterEmailOtp(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.response_credential, self.customer = get_initialized_data_whitelabel_credentials(self.client)
        self.feature_setting = FeatureSettingFactory(
            feature_name = FeatureNameConst.EMAIL_OTP,
            parameters = {
                "otp_max_request": 3,
                "otp_resend_time": 60,
                "wait_time_seconds": 200,
            }
        )
        postfixed_request_id = str(self.customer.id) + str(int(time.time()))
        self.otp = OtpRequestFactory(
            is_used=False,
            customer=self.customer,
            request_id=postfixed_request_id,
            action_type=SessionTokenAction.PAYLATER_LINKING
        )
        self.endpoint = '/api/partnership/web/v1/whitelabel-paylater-application/email-otp'
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()
            ['data']['webview_url'].split('auth=')[1]
        )

    @patch('juloserver.partnership.services.web_services.send_email_otp_token.delay')
    def test_success_send_email_otp(self, mock_process_send_email_otp_token: MagicMock) -> None:
        data = {
            "email": self.customer.email,
        }
        response = self.client.post(self.endpoint, data=data)
        mock_process_send_email_otp_token.called_once()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

    def test_not_valid_email(self) -> None:
        data = {
            "email": "tessnana.com",
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["Email Doesn't Match User"])

    def test_error_email_otp_not_activated(self) -> None:
        self.feature_setting.is_active = False
        self.feature_setting.save()
        data = {
            "email": self.customer.email,
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['content']['message'], 'Verifikasi kode tidak aktif')

    def test_error_email_otp_unauthorized(self) -> None:
        self.client.credentials(
            HTTP_SECRET_KEY="wrong-secret-key"
        )
        data = {
            "email": self.customer.email,
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Invalid Key Error'])


class TestGetPartnerLoanReceiptView(TestCase):
    def setUp(self):
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
        response_register_partner = register_partner_paylater(self.client)
        self.partner = Partner.objects.filter(name='partner_paylater').last()
        self.client.credentials(
            HTTP_SECRET_KEY=response_register_partner.json()['data']['secret_key'],
            HTTP_USERNAME=response_register_partner.json()['data']['partner_name'],
        )
        self.partnership_type = PartnershipTypeFactory(
            partner_type_name='Whitelabel Paylater')
        new_julo1_product_line()
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.partner_user = AuthUserFactory(username='vospay')
        self.customer = CustomerFactory(user=self.partner_user)
        self.account = AccountFactory(customer=self.customer)
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30],
            loan_cancel_duration=7
        )
        CustomerPinFactory(user=self.partner_user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
            application_xid=9999999867,
            partner=self.partner
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.application.save()
        self.status = StatusLookupFactory()
        self.status.status_code = 210
        self.status.save()
        self.loan = LoanFactory(
            partner=self.partner,
            account=self.account, customer=self.customer,
            application=self.application,
            loan_amount=10000000, loan_xid=1000003056,
            loan_status=self.status,
            sphp_accepted_ts=timezone.localtime(
                timezone.now()).date() - timedelta(days=5)
        )
        self.endpoint = '/api/partnership/v1/loan/receipt/{}/'.format(self.loan.loan_xid)
        self.data = {
            "receipt_no": '123456'
        }

    def test_get_partner_loan_receipt_with_no_receipt_num(self):
        data = {
            "xxx": 'fghfg'
        }
        response = self.client.post(self.endpoint, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Receipt_no harus diisi'])

    def test_get_partner_loan_receipt_with_invalid_loan_status(self):
        response = self.client.post(self.endpoint, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], [ErrorMessageConst.LOAN_NOT_FOUND])

    def test_get_partner_loan_receipt_with_no_partner_loan_request(self):
        response = self.client.post(self.endpoint, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], [ErrorMessageConst.LOAN_NOT_FOUND])

    @patch('juloserver.partnership.views.update_loan_status_and_loan_history')
    def test_get_partner_loan_receipt_with_valid_receipt_num(
        self, mock_update_loan_status_and_loan_history
    ):
        self.loan.loan_status_id = 211
        self.loan.save()
        PartnerLoanRequestFactory(
            loan=self.loan,
            partner=self.partner,
            distributor=None,
            loan_amount=self.loan.loan_amount,
            loan_disbursement_amount=self.loan.loan_disbursement_amount,
            loan_original_amount=self.loan.loan_amount,
            partner_origin_name=None,
        )
        response = self.client.post(self.endpoint, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestWebviewChangeLoanStatusView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.partnership_customer_data = PartnershipCustomerDataFactory(
            customer=self.customer, partner=partner
        )
        self.client.force_login(user=self.user)
        self.client.credentials(
            HTTP_SECRET_KEY=self.partnership_customer_data.token,
            HTTP_AUTHORIZATION='Token ' + self.token,
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name='julo1', payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.account.status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.save()

        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account,
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user,
            latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90),
        )

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )

        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)

        loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application=self.application,
            loan_amount=10000000,
            loan_xid=1000003456,
            loan_status=loan_status,
            transaction_method=TransactionMethod.objects.get(id=1),
        )
        self.application.save()
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_limit.available_limit = 10000000
        self.account_limit.set_limit = 10000000
        self.account_limit.save()
        self.product = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory()
        self.credit_matrix_product_line.max_duration = 10
        self.credit_matrix_product_line.min_duration = 2
        self.credit_matrix_product_line.min_loan_amount = 100000
        self.credit_matrix_product_line.max_loan_amount = 10000000
        self.credit_matrix_product_line.save()

        self.partnership_type = PartnershipTypeFactory()
        self.partnership_config = PartnershipConfigFactory(
            partner=partner, partnership_type=self.partnership_type, loan_duration=[3, 7, 14, 30]
        )

        self.partnership_transaction = PartnershipTransactionFactory(
            transaction_id='1109876543',
            partner_transaction_id='09809765',
            customer=self.customer,
            partner=partner,
            loan=self.loan,
        )
        PartnershipLogRetryCheckTransactionStatusFactory(
            status=PartnershipLogStatus.IN_PROGRESS, loan=self.loan
        )
        partner_id = partner.id
        self.partnership_session_information = PartnershipSessionInformationFactory(
            partner_id=partner_id
        )
        self.partnership_session_information.phone_number = (
            self.partnership_customer_data.phone_number
        )
        self.partnership_session_information.session_id = '01EA1PTFKAQMFJEQR999XWZHVW'
        self.partnership_session_information.customer_token = '01FY8AZE0Q2DYBX1R32TYC390Z'
        self.partnership_session_information.save()
        ImageFactory(image_type='signature', image_source=self.loan.id, image_status=0)
        self.endpoint = '/api/partnership/web/v1/agreement/loan/status/{}/'.format(
            self.loan.loan_xid
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=210, status_next=211, workflow=self.workflow)
        self.feature_setting = FeatureSettingFactory(
            feature_name='swift_limit_drainer',
            parameters={'jail_days': 0},
            is_active=False,
        )

    @patch('juloserver.partnership.views.get_count_request_on_redis')
    @patch(
        'juloserver.partnership.services.services.'
        'get_credit_matrix_and_credit_matrix_product_line'
    )
    @patch('juloserver.partnership.clients.clients.LinkAjaClient.cash_in_confirmation')
    def test_change_loan_status_success(
        self, mock_cashin_confirmation, mocked_credit_matrix, mock_get_count_request_on_redis
    ) -> None:
        mocked_credit_matrix.return_value = self.credit_matrix, self.credit_matrix_product_line
        mock_cashin_confirmation.return_value.status_code = 200
        mock_cashin_confirmation.return_value.content = '{"responseCode": "00", "responseMessage": "Success","msisdn": "6283899270008", "amount": "300000","merchantTrxID": "10000724130161", "linkRefNum": "6LK209HEKM"}'
        mock_get_count_request_on_redis.return_value = 0, ''
        request_data = {"loan_xid": self.loan.loan_xid, "status": "sign"}
        response = self.client.post(self.endpoint, data=request_data, format='json')
        self.assertEqual(response.status_code, HTTPStatus.OK)


def register_partner_vospay(client):
    partnership_type = PartnershipTypeFactory(partner_type_name='Whitelabel Paylater')
    data_partner = {
        'username': 'vospay',
        'email': 'vospay@gmail.com',
        'partnership_type': partnership_type.id,
    }
    response = client.post('/api/partnership/v1/partner', data=data_partner)
    return response


def get_paylater_initialization_credentials_for_non_customer(client):
    user = AuthUserFactory()
    client.force_login(user)
    client.credentials(HTTP_AUTHORIZATION='Token ' + user.auth_expiry_token.key)
    response_register_partner = register_partner_vospay(client)
    client.credentials(
        HTTP_SECRET_KEY=response_register_partner.json()['data']['secret_key'],
        HTTP_USERNAME=response_register_partner.json()['data']['partner_name'],
    )
    partner = Partner.objects.first()
    partnership_type = PartnershipTypeFactory(
        partner_type_name=PartnershipTypeConstant.WHITELABEL_PAYLATER
    )
    PartnershipConfigFactory(
        partner=partner, partnership_type=partnership_type, loan_duration=[3, 7, 14, 30]
    )
    data = {
        "email": 'test@testme.com',
        "mobile_phone": '086678905555',
        "partner_reference_id": "tesst33334",
        "transaction_amount": "100000",
        "kodepos": "11111",
        "kabupaten": "Test kabupaten",
        "provinsi": "Test Provinsi",
        "order_details": [
            {
                "merchant_name": "test",
                "products": [
                    {"product_name": "testproduct1", "product_qty": 1, "product_price": 5.50}
                ],
            }
        ],
    }
    response = client.post('/api/partnership/v1/transaction-details', data=data, format='json')
    return response


class TestWhitelabelRegisterEmailOtpRequest(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.response_credential, self.customer = get_initialized_data_whitelabel_credentials(
            self.client
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.EMAIL_OTP,
            parameters={
                "otp_max_request": 3,
                "otp_resend_time": 60,
                "wait_time_seconds": 200,
            },
        )
        self.customer.nik = 3174011604951543
        self.customer.save(update_fields=['nik'])
        postfixed_request_id = str(self.customer.id) + str(int(time.time()))
        self.otp = OtpRequestFactory(
            is_used=False,
            customer=self.customer,
            request_id=postfixed_request_id,
            action_type=SessionTokenAction.PAYLATER_REGISTER,
        )
        self.endpoint = '/api/partnership/web/v1/whitelabel-paylater-request-email-otp'
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()['data']['webview_url'].split('auth=')[1]
        )

    @patch('juloserver.partnership.services.web_services.send_email_otp_token.delay')
    def test_success_send_email_otp(self, mock_process_send_email_otp_token: MagicMock) -> None:
        data = {"email": self.customer.email, "nik": self.customer.nik}
        response = self.client.post(self.endpoint, data=data)
        mock_process_send_email_otp_token.called_once()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)

    def test_not_valid_email(self) -> None:
        data = {"email": "test.com", "nik": self.customer.nik}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["Email tidak valid"])

    def test_not_valid_nik(self) -> None:
        data = {"email": self.customer.email, "nik": 567657567}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["NIK tidak memenuhi pattern yang dibutuhkan"])

        data = {"email": self.customer.email, "nik": "dfsdfdsf"}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["NIK tidak memenuhi pattern yang dibutuhkan"])

    def test_error_email_otp_not_activated(self) -> None:
        self.feature_setting.is_active = False
        self.feature_setting.save()
        data = {"email": self.customer.email, "nik": self.customer.nik}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['content']['message'], 'Verifikasi kode tidak aktif')

    def test_error_email_otp_unauthorized(self) -> None:
        self.client.credentials(HTTP_SECRET_KEY="wrong-secret-key")
        data = {"email": self.customer.email, "nik": self.customer.nik}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Invalid Key Error'])

    @patch('juloserver.partnership.services.web_services.send_email_otp_token.delay')
    def test_success_send_email_otp_for_non_customer(
        self, mock_process_send_email_otp_token: MagicMock
    ) -> None:
        self.client1 = APIClient()
        self.response_credential1 = get_paylater_initialization_credentials_for_non_customer(
            self.client1
        )
        self.client1.credentials(
            HTTP_SECRET_KEY=self.response_credential1.json()['data']['webview_url'].split('auth=')[
                1
            ]
        )
        data = {"email": "test@testme.com", "nik": 3174711604951543}
        response = self.client1.post(self.endpoint, data=data)
        mock_process_send_email_otp_token.called_once()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)


class TestWhitelabelApplicationOtpValidation(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.response_credential, self.customer = get_paylater_initialization_credentials(
            self.client
        )
        paylater_transaction_xid = self.response_credential.json()['data'][
            'paylater_transaction_xid'
        ]
        paylater_transaction = PaylaterTransaction.objects.filter(
            paylater_transaction_xid=paylater_transaction_xid
        ).last()

        postfixed_request_id = str(paylater_transaction.id) + str(int(time.time()))
        self.otp = OtpRequestFactory(
            is_used=False,
            request_id=postfixed_request_id,
            action_type=SessionTokenAction.PAYLATER_REGISTER,
            customer=None,
        )

        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.EMAIL_OTP,
            parameters={
                "otp_max_request": 3,
                "otp_resend_time": 60,
                "wait_time_seconds": 200,
                "otp_max_validate": 3,
            },
        )
        self.endpoint = '/api/partnership/web/v1/whitelabel-paylater-validate-email-otp'
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()['data']['webview_url'].split('auth=')[1]
        )

    def test_validate_email_otp_with_no_otp_token(self) -> None:
        self.feature_setting.is_active = False
        self.feature_setting.save()
        data = {}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Otp_token tidak boleh kosong'])

    def test_validate_email_otp_not_activated(self) -> None:
        self.feature_setting.is_active = False
        self.feature_setting.save()
        data = {"otp_token": 377506}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['content']['message'], 'Verifikasi kode tidak aktif')

    def test_validate_email_otp_with_no_existing_otp_request(self) -> None:
        self.otp.is_used = True
        self.otp.save(update_fields=['is_used'])
        data = {"otp_token": 377506}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['error_message'], "Kode verifikasi belum terdaftar")

    def test_validate_otp_for_invalid_otp_token_attempt1(self):
        self.data = {"otp_token": 377506}
        response = self.client.post(self.endpoint, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['error_message'], "OTP tidak sesuai, coba kembali")

    def test_validate_otp_for_invalid_otp_token_attempt2(self):
        self.data = {"otp_token": 377506}
        self.otp.retry_validate_count = 2
        self.otp.save(update_fields=['retry_validate_count'])
        response = self.client.post(self.endpoint, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(
            response.json()['error_message'],
            "Kesempatan mencoba OTP sudah habis, coba kembali beberapa saat lagi",
        )

    def test_validate_otp_for_max_validate_count_exceed(self):
        self.data = {"otp_token": 377506}
        self.otp.retry_validate_count = 3
        self.otp.save(update_fields=['retry_validate_count'])
        response = self.client.post(self.endpoint, data=self.data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(
            response.json()['error_message'],
            "Kesempatan mencoba OTP sudah habis, coba kembali beberapa saat lagi",
        )

    @patch('juloserver.partnership.services.web_services.pyotp')
    def test_validate_email_otp_success(self, mock_pyotp: MagicMock) -> None:
        self.otp.otp_token = 159357
        self.otp.save(update_fields=['otp_token'])
        data = {"otp_token": self.otp.otp_token}
        mock_pyotp.HOTP.return_value.verify.return_value = True
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()['content']['message'], 'Kode verifikasi berhasil diverifikasi'
        )

    @patch('juloserver.partnership.services.web_services.pyotp')
    def test_validate_email_otp_success_for_non_customer(self, mock_pyotp: MagicMock) -> None:
        self.client1 = APIClient()
        self.response_credential1 = get_paylater_initialization_credentials_for_non_customer(
            self.client1
        )
        self.client1.credentials(
            HTTP_SECRET_KEY=self.response_credential1.json()['data']['webview_url'].split('auth=')[
                1
            ]
        )
        paylater_transaction_xid = self.response_credential1.json()['data'][
            'paylater_transaction_xid'
        ]
        paylater_transaction = PaylaterTransaction.objects.filter(
            paylater_transaction_xid=paylater_transaction_xid
        ).last()

        postfixed_request_id = str(paylater_transaction.id) + str(int(time.time()))
        self.otp = OtpRequestFactory(
            is_used=False,
            customer=None,
            request_id=postfixed_request_id,
            action_type=SessionTokenAction.PAYLATER_REGISTER,
        )
        self.otp.otp_token = 159357
        self.otp.save(update_fields=['otp_token'])
        data = {"otp_token": self.otp.otp_token}
        mock_pyotp.HOTP.return_value.verify.return_value = True
        response = self.client1.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()['content']['message'], 'Kode verifikasi berhasil diverifikasi'
        )


class TestWhitelabelRegisteration(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.response_credential, self.customer = get_paylater_initialization_credentials(
            self.client
        )
        self.endpoint = '/api/partnership/web/v1/whitelabel-paylater-register'
        self.client.credentials(
            HTTP_SECRET_KEY=self.response_credential.json()['data']['webview_url'].split('auth=')[1]
        )

    @patch('juloserver.julo.services.process_application_status_change')
    def test_not_valid_datas(self, mock_process_application_status_change) -> None:
        data = {
            "email": "hjhg",
            "nik": 3174011604771583,
            "web_version": "0.0.1",
            "latitude": "-7.7778282",
            "longitude": "110.3795011"
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["Email tidak valid"])

        data = {
            "email": "aaa@aa.com",
            "nik": 567657567,
            "web_version": "0.0.1",
            "latitude": "-7.7778282",
            "longitude": "110.3795011"
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["NIK tidak memenuhi pattern yang dibutuhkan"])

        data = {
            "email": "aaa@aaq.com",
            "nik": "dfsdfdsf",
            "web_version": "0.0.1",
            "latitude": "-7.7778282",
            "longitude": "110.3795011"
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["NIK tidak memenuhi pattern yang dibutuhkan"])

        data = {
            "email": "aaa@aa4.com",
            "nik": 3174011604771545,
            "web_version": "0.0.1",
            "latitude": "fdg",
            "longitude": "110.3795011"
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["latitude tidak valid"])

        data = {
            "email": "aaa@aa224.com",
            "nik": 3174011604771565,
            "web_version": "0.0.1",
            "latitude": "-7.7778282",
            "longitude": "ghghgh"
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["longitude tidak valid"])

        data = {
            "email": "aaa@aa2ff24.com",
            "nik": 3174011604771505,
            "web_version": "0.0.1",
            "latitude": "fghfghfg",
            "longitude": "110.3795011"
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["latitude tidak valid"])

        data = {
            "email": "aaa@a524.com",
            "nik": 3174011604771665,
            "web_version": "0.0.1",
            "latitude": "",
            "longitude": ""
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["Latitude tidak boleh kosong"])

        data = {
            "email": "rrraaa@a524.com",
            "nik": 3174011604771665,
            "web_version": "0.0.1",
            "latitude": "-7.7778282",
            "longitude": "110.3795011"
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = {
            "email": "rrraavca@a524.com",
            "nik": 3174011604771665,
            "web_version": "0.0.1",
            "latitude": "-7.7778282",
            "longitude": "110.3795011"
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["NIK Anda sudah terdaftar"])

        data = {
            "email": "rrraaa@a524.com",
            "nik": 3174011604771905,
            "web_version": "0.0.1",
            "latitude": "-7.7778282",
            "longitude": "110.3795011"
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ["Email Anda sudah terdaftar"])

    @patch('juloserver.julo.services.process_application_status_change')
    def test_success_register(self, mock_process_application_status_change) -> None:
        data = {
            "email": "rrraaa@teste.com",
            "nik": 3174011604773365,
            "web_version": "0.0.1",
            "latitude": "-7.7778282",
            "longitude": "110.3795011"
        }
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['success'], True)
        self.assertIsNotNone(response.json()['data']['paylater_transaction_xid'])


class TestPaylaterWebviewInfocard(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.client.force_login(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name='julo1', payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990088,
            partner=partner,
            product_line=self.product_line,
            email='testing_email1@gmail.com',
            account=self.account,
        )
        self.client1 = APIClient()
        self.user1 = AuthUserFactory()
        self.customer1 = CustomerFactory(user=self.user1)
        partner1 = PartnerFactory(user=self.user1, is_active=True)
        self.token1 = self.customer1.user.auth_expiry_token.key
        self.client1.force_login(user=self.user1)
        self.client1.credentials(HTTP_AUTHORIZATION='Token ' + self.token1)
        self.product_line1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow1 = WorkflowFactory(
            name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler'
        )
        self.application1 = ApplicationFactory(
            customer=self.customer1,
            workflow=self.workflow1,
            application_xid=9999990356,
            partner=partner1,
            product_line=self.product_line1,
            email='testing_email11@gmail.com',
        )
        self.credit_score = CreditScoreFactory(application_id=self.application.id, score='B-')
        self.credit_score1 = CreditScoreFactory(application_id=self.application1.id, score='B-')
        self.paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id='900878712',
            transaction_amount=500_000,
            paylater_transaction_xid=90009888290,
            partner=partner,
        )
        self.url = '/api/partnership/web/v1/paylater-info-card?paylater_transaction_xid='
        self.endpoint = self.url + '{}'.format(self.paylater_transaction.paylater_transaction_xid)
        self.endpoint1 = self.url + '334243'

    def test_get_info_card_with_incorrect_paylater_transaction(self) -> None:
        response = self.client.get(self.endpoint1)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Paylater Transaction not found'])

    def test_get_info_card(self) -> None:
        self.application.application_status = (
            self.application.application_status
        ) = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['application_id'], self.application.id)

    def test_get_info_card_for_form_partial_status(self) -> None:
        self.application1.application_status = (
            self.application1.application_status
        ) = StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL)
        response = self.client1.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['application_id'], self.application1.id)

    def test_get_info_card_with_button_in_121_status(self) -> None:
        self.application1.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application1.save()
        self.info_card = InfoCardPropertyFactory(card_type='2')
        self.button = ButtonInfoCardFactory(id=200, info_card_property=self.info_card)
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="content", info_card_property=self.info_card
        )
        self.streamlined_comms = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            message=self.streamlined_message,
            is_active=True,
            show_in_web=True,
            show_in_android=False,
            extra_conditions=CardProperty.PARTNERSHIP_WEBVIEW_INFO_CARDS,
            status_code_id=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        )
        response = self.client1.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['application_id'], self.application1.id)
        cards = response.json()['data']['cards']
        if cards:
            for i in range(0, len(cards)):
                card = cards[i]
                self.assertGreater(len(card['button']), 0)


class TestPaylaterCreditInfoView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user2 = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.customer2 = CustomerFactory(user=self.user2)
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="limit_card_call_to_action",
            is_active=True,
            parameters={
                'bottom_left': {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "product_transfer_self",
                },
                "bottom_right": {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "aktivitaspinjaman",
                },
            },
        )
        self.partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.client.force_login(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name='julo1', payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            status=ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=self.partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account,
        )
        self.credit_score = CreditScoreFactory(application_id=self.application.id, score='B-')
        self.account_property = AccountPropertyFactory(account=self.account, is_proven=True)
        self.paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id='9008787124',
            transaction_amount=500_000,
            paylater_transaction_xid=90009888290,
            partner=self.partner,
        )
        self.url = '/api/partnership/web/v1/paylater-credit-info?paylater_transaction_xid='
        self.endpoint = self.url + '{}'.format(self.paylater_transaction.paylater_transaction_xid)
        self.endpoint1 = self.url + '334243'

    def test_get_credit_info_with_incorrect_paylater_transaction(self) -> None:
        response = self.client.get(self.endpoint1)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Paylater Transaction not found'])

    @mock.patch('django.utils.timezone.localtime')
    def test_get_application_not_found(self, _: MagicMock) -> None:
        self.application.customer = self.customer2
        self.application.save(update_fields=['customer'])
        self.application.refresh_from_db()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        result = response.__dict__['data']
        self.assertEqual(result['success'], False)
        self.assertEqual(result['errors'], ['Application Not Found'])

    @mock.patch('django.utils.timezone.localtime')
    def test_get_credit_info_fail_error_exception(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
        ]
        self.mobile_feature_setting.delete()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(response.json()['success'], False)

    @mock.patch('django.utils.timezone.localtime')
    def test_get_credit_info_success(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
        ]
        response = self.client.get(self.endpoint)
        result = response.__dict__['data']
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(result['success'], True)

        credit_info = result['data']['creditInfo']
        self.assertEqual(credit_info['fullname'], self.customer.fullname)
        self.assertEqual(credit_info['is_proven'], self.account_property.is_proven)

    @mock.patch('django.utils.timezone.localtime')
    def test_credit_limit_on_delay(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [datetime_now, datetime_now, datetime_now]
        now = timezone.localtime(timezone.now())
        two_hours_ago = now - timedelta(hours=2)
        minutes = two_hours_ago.strftime('%M')
        hours = two_hours_ago.strftime('%H')
        format_hours = '%s:%s' % (hours, minutes)
        self.feature_setting = FeatureSettingFactory()
        self.feature_setting.feature_name = FeatureNameConst.DELAY_C_SCORING
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'hours': format_hours, 'exact_time': True}
        self.feature_setting.save()

        # Denied
        self.application.application_status = StatusLookupFactory(status_code=135)
        self.application.save(update_fields=['application_status'])
        self.rejected_customer = self.application.customer
        self.rejected_application_history = ApplicationHistoryFactory(
            application_id=self.application.id, status_old=0, status_new=105
        )
        one_days = now + relativedelta(days=1)
        self.rejected_application_history.cdate = one_days
        self.rejected_application_history.save()

        # Pending
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL
        )
        self.application.save(update_fields=['application_status'])

        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.__dict__['data']['data']['creditInfo']['limit_message'],
            'Pengajuan kredit JULO sedang dalam proses',
        )
        self.assertEqual(response.__dict__['data']['data']['creditInfo']['account_state'], 310)

    @mock.patch('django.utils.timezone.localtime')
    def test_credit_limit_c(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
        ]
        self.credit_score.score = 'C'
        self.credit_score.save()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.__dict__['data']['success'], True)
        self.assertEqual(response.__dict__['data']['data']['creditInfo']['credit_score'], 'C')

        product = response.__dict__['data']['data']['product']
        self.assertNotEqual(len(product), 1)

    @mock.patch('django.utils.timezone.localtime')
    def test_credit_limit_gt_c(self, mocked_time: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
        ]
        self.credit_score.score = 'B'
        self.credit_score.save()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        transaction_methods = TransactionMethod.objects.all().order_by('order_number')[:7]

        # adding 1 because in response added 1 more product hardcoded TransactionMethodCode.ALL_PRODUCT
        self.assertEqual(
            len(transaction_methods) + 1, len(response.__dict__['data']['data']['product'])
        )
        self.assertEqual(
            response.__dict__['data']['data']['product'][0]['name'],
            transaction_methods[0].fe_display_name,
        )
        self.assertEqual(
            response.__dict__['data']['data']['product'][0]['code'], transaction_methods[0].id
        )


class TestPaylaterCombinedHomeScreen(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.token = self.customer.user.auth_expiry_token.key
        self.client.force_login(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE, handler='JuloOneWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name='julo1', payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account,
        )
        self.loan = LoanFactory(application=self.application)
        self.voice_record = VoiceRecordFactory()
        self.customer_wallet_history = CustomerWalletHistoryFactory()
        self.paylater_transaction = PaylaterTransactionFactory(
            partner_reference_id='9008787124',
            transaction_amount=500_000,
            paylater_transaction_xid=90009888290,
            partner=partner,
        )
        self.endpoint = '/api/partnership/web/v1/paylater-homescreen/combined'

    def test_get_combined_home_screen_with_incorrect_paylater_transaction(self) -> None:
        data = {
            'application_id': self.application.id,
            'app_version': '2.2.2',
            'paylater_transaction_xid': 777,
        }
        response = self.client.get(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['success'], False)
        self.assertEqual(response.json()['errors'], ['Paylater Transaction not found'])

    @patch('juloserver.apiv2.views.is_bank_name_validated')
    @patch('juloserver.apiv2.views.get_referral_home_content')
    @patch('juloserver.apiv2.views.update_response_fraud_experiment')
    @patch('juloserver.apiv2.views.ProductLineSerializer')
    @patch('juloserver.apiv2.views.check_fraud_model_exp')
    @patch('juloserver.apiv2.views.update_response_false_rejection')
    @patch('juloserver.apiv2.views.get_product_lines')
    @patch('juloserver.apiv2.views.get_customer_app_actions')
    @patch('juloserver.apiv2.views.render_loan_sell_off_card')
    @patch('juloserver.apiv2.views.render_sphp_card')
    @patch('juloserver.apiv2.views.render_season_card')
    @patch('juloserver.apiv2.views.render_campaign_card')
    @patch('juloserver.apiv2.views.render_account_summary_cards')
    def test_partnership_combined_home_screen(
        self,
        mock_render_account_summary_cards: MagicMock,
        mock_render_campaign_card: MagicMock,
        mock_render_season_card: MagicMock,
        mock_render_sphp_card: MagicMock,
        mock_render_loan_sell_off_card: MagicMock,
        mock_get_customer_app_actions: MagicMock,
        mock_get_product_lines: MagicMock,
        mock_update_response_false_rejection: MagicMock,
        mock_check_fraud_model_exp: MagicMock,
        mock_ProductLineSerializer: MagicMock,
        mock_update_response_fraud_experiment: MagicMock,
        mock_get_referral_home_content: MagicMock,
        mock_is_bank_name_validated: MagicMock,
    ) -> None:
        data = {
            'application_id': self.application.id,
            'app_version': '2.2.2',
            'paylater_transaction_xid': self.paylater_transaction.paylater_transaction_xid,
        }
        self.loan.application = self.application
        self.loan.loan_status_id = 260
        self.loan.save()

        self.application.application_status_id = 150
        self.application.save()

        self.customer_wallet_history.customer = self.customer
        self.customer_wallet_history.save()

        self.voice_record.application = self.application
        self.voice_record.save()

        mock_render_account_summary_cards.return_value = ['']
        mock_is_bank_name_validated.return_value = False
        mock_get_customer_app_actions.return_value = 'mock_customer_action'
        mock_update_response_fraud_experiment.return_value = 'TestCombinedHomeScreenAPIv2'
        mock_get_referral_home_content.return_value = (True, 'test_referral_content')

        response = self.client.get(self.endpoint, data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestLeadgenWebAppOtpValidateView(TestCase):
    def setUp(self):
        self.endpoint = "/api/partnership/v1/register/email/otp/validate"
        self.otp_setting = PartnershipFeatureSetting.objects.create(
            is_active=True,
            feature_name=PartnershipFeatureNameConst.LEADGEN_OTP_SETTINGS,
            category="leadgen_standard",
            parameters={
                "email": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 120,
                    "otp_expired_time": 1440,
                },
                "mobile_phone_1": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time": 60,
                    "wait_time_seconds": 120,
                    "otp_expired_time": 1440,
                },
            },
            description="FeatureSettings to determine standard leadgen otp settings",
        )

        self.email = "prod_only+leadgen_webapp@julofinance.com"
        self.timestamp = datetime.datetime.now()
        string_to_hash = self.email
        hash_request_id = hashlib.sha256(string_to_hash.encode()).digest()
        b64_encoded_request_id = base64.urlsafe_b64encode(hash_request_id).decode()
        self.request_id = b64_encoded_request_id

        self.otp_request = OtpRequest.objects.create(
            request_id=self.request_id,
            otp_token="123456",
            email=self.email,
            action_type=SessionTokenAction.PARTNERSHIP_REGISTER_VERIFY_EMAIL,
            is_active=True,
            otp_service_type="email",
            is_used=False,
        )

        self.partnership_otp = PartnershipUserOTPAction.objects.create(
            otp_request=self.otp_request.id,
            request_id=self.request_id,
            otp_service_type='email',
            action_type=SessionTokenAction.PARTNERSHIP_REGISTER_VERIFY_EMAIL,
            is_used=False,
        )

        self.payload = {
            "otp": "123456",
            "email": self.email,
            "request_id": self.request_id,
            "x_timestamp": self.timestamp,
        }

    def test_success_otp_validation(self):
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    def test_invalid_request_id(self):
        self.payload['request_id'] = 'asdfhj12343'
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_otp_setting_not_active(self):
        self.otp_setting.update_safely(is_active=False)
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_otp_is_used(self):
        self.partnership_otp.update_safely(is_used=True)
        self.otp_request.update_safely(is_used=True)
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_otp_max_validate(self):
        self.otp_request.update_safely(retry_validate_count=3)
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)

    def test_otp_expired(self):
        new_cdate = self.otp_request.cdate - relativedelta(seconds=1440)
        self.otp_request.update_safely(cdate=new_cdate)
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)


class TestPartnershipClikModelNotificationView(TestCase):
    def setUp(self):
        self.endpoint = "/api/partnership/v1/clik-model-notification/"
        self.user = AuthUserFactory(is_staff=True)
        self.partner = PartnerFactory(name="qoala", user=self.user, is_active=True)
        self.application = ApplicationFactory(partner=self.partner)

        self.payload = {
            'application_id': self.application.id,
            'pgood': 0.97,
            'clik_flag_matched': True,
            'model_version': "Clik v1.0.0",
        }
        PartnershipClikModelResult.objects.create(
            application_id=self.application.id, status='in_progress', pgood=float(0)
        )

        self.client = APIClient()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    def test_success(self):
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)

        clik_model_result = PartnershipClikModelResult.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual("success", clik_model_result.status)
        self.assertEqual(self.payload['pgood'], clik_model_result.pgood)

    def test_application_not_found(self):
        self.payload['application_id'] = 1234612534
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_click_model_result_not_found(self):
        new_application = ApplicationFactory(partner=self.partner)
        self.payload['application_id'] = new_application.id
        response = self.client.post(self.endpoint, data=self.payload)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_error_serializer(self):
        payload = {
            'application_id': "aaa",
            'pgood': True,
            'clik_flag_matched': "True",
        }
        response = self.client.post(self.endpoint, data=payload)
        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)


class TestPartnershipDigitalSignatureGetApplicationView(TestCase):
    def setUp(self):
        self.client_id = ulid.new().uuid
        self.phone_number = '081912344444'
        self.user_auth = AuthUserFactory()
        self.partner_name = PartnerNameConstant.IOH_BIMA_PLUS
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.client = APIClient()

        product_line_code = ProductLineCodes.J1
        self.product_line = ProductLineFactory(product_line_code=product_line_code)

        self.customer = CustomerFactory(
            user=self.user_auth,
            email='prod.only@julofinance.com',
            nik='3271065902890002',
        )
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            partner=self.partner,
            email='prod.only@julofinance.com',
            ktp='3271065902890002',
        )
        DukcapilResponseFactory(application=self.application, status='200', source='Dukcapil')
        DukcapilFaceRecognitionCheckFactory(response_score=6, application_id=self.application.id)
        self.passive_liveness_result = LivenessResultFactory(
            liveness_configuration_id=1,
            client_id=self.client_id,
            image_ids={'neutral': 3},
            platform='web',
            detection_types=LivenessType.PASSIVE,
            score=0.9,
            status='success',
            reference_id=ulid.new().uuid,
        )
        LivenessResultsMappingFactory(
            liveness_reference_id=self.passive_liveness_result.reference_id,
            application_id=self.application.id,
            status='active',
            detection_type=LivenessType.PASSIVE,
        )
        self.smile_liveness_result = LivenessResultFactory(
            liveness_configuration_id=1,
            client_id=self.client_id,
            image_ids={'smile': 1, 'neutral': 2},
            platform='web',
            detection_types=LivenessType.SMILE,
            score=1.0,
            status='success',
            reference_id=ulid.new().uuid,
        )
        LivenessResultsMappingFactory(
            liveness_reference_id=self.smile_liveness_result.reference_id,
            application_id=self.application.id,
            status='active',
        )
        ImageFactory(
            image_type='selfie',
            image_source=self.application.id,
            url='selfie.jpg',
        )
        ImageFactory(
            image_type='ktp_self',
            image_source=self.application.id,
            url='ktp_self.jpg',
        )
        self.image = File(
            file=io.BytesIO(b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01"), name='test'
        )

    @override_settings(JWT_SECRET_KEY="secret-jwt")
    @patch('juloserver.partnership.views.get_oss_presigned_url_external')
    def test_valid_partnership_digital_signature_get_application(self, mock_get_file_from_oss):
        mock_get_file_from_oss.return_value = self.image
        generate_token = PartnershipOnboardingInternalAuthentication.generate_token(
            'partnership-digital-signature'
        )
        token = 'Bearer {}'.format(generate_token)
        self.client.credentials(HTTP_AUTHORIZATION=token)
        endpoint = "/api/partnership/digital-signature/v1/applications/{}".format(
            self.application.id
        )
        response = self.client.get(endpoint)
        self.assertEqual(status.HTTP_200_OK, response.status_code)

    @override_settings(JWT_SECRET_KEY="secret-jwt")
    def test_invalid_application_id_partnership_digital_signature_get_application(self):
        generate_token = PartnershipOnboardingInternalAuthentication.generate_token(
            'partnership-digital-signature'
        )
        token = 'Bearer {}'.format(generate_token)
        self.client.credentials(HTTP_AUTHORIZATION=token)
        endpoint = "/api/partnership/digital-signature/v1/applications/{}".format(111)
        response = self.client.get(endpoint)
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)


class TestAegisFDCInquiry(TestCase):
    def setUp(self):
        self.endpoint = "/api/partnership/v1/aegis-fdc-inquiry"
        self.user = AuthUserFactory(is_staff=True)
        self.partner = PartnerFactory(
            name=MerchantFinancingCSVUploadPartner.GAJIGESA, user=self.user, is_active=True
        )
        self.application = ApplicationFactory(partner=self.partner)

        self.payload = {"application_ids": [self.application.id]}
        self.aegis_service_token = "4d9d0431-86ad-4c09-ab9a-d9971870665b"
        self.fdc_feature = FeatureSetting.objects.create(
            feature_name="fdc_configuration", is_active=True
        )

    @override_settings(AEGIS_SERVICE_TOKEN='4d9d0431-86ad-4c09-ab9a-d9971870665b')
    def test_success(self):
        response = self.client.post(
            self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.aegis_service_token
        )
        self.assertEqual(status.HTTP_201_CREATED, response.status_code)

        exist_fdc_inquiry = FDCInquiry.objects.filter(application_id=self.application.id).exists()
        self.assertTrue(exist_fdc_inquiry)

    @override_settings(AEGIS_SERVICE_TOKEN='4d9d0431-86ad-4c09-ab9a-d9971870665b')
    def test_application_have_fdc(self):
        FDCInquiryFactory(
            application_id=self.application.id,
            inquiry_date=timezone.localtime(timezone.now()).date(),
        )
        response = self.client.post(
            self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.aegis_service_token
        )
        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)

    @override_settings(AEGIS_SERVICE_TOKEN='4d9d0431-86ad-4c09-ab9a-d9971870665b')
    def test_feature_setting_off(self):
        self.fdc_feature.update_safely(is_active=False)
        response = self.client.post(
            self.endpoint, data=self.payload, HTTP_AUTHORIZATION=self.aegis_service_token
        )
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

        self.assertEqual(response.data['message'], 'fdc configuration is inactive')
