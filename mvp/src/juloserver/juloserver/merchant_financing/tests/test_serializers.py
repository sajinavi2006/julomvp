from django.test.testcases import TestCase
from faker import Faker

from juloserver.core.utils import JuloFakerProvider
from juloserver.julo.tests.factories import AppVersionFactory, PartnerFactory
from juloserver.merchant_financing.serializers import MerchantFinancingUploadRegisterSerializer
from juloserver.partnership.constants import PartnershipFlag
from juloserver.partnership.models import PartnershipFlowFlag
from juloserver.portal.object.bulk_upload.constants import MerchantFinancingCSVUploadPartner
from juloserver.portal.object.bulk_upload.tests import get_axiata_data
from juloserver.portal.object.bulk_upload.serializers import ApplicationPartnerUpdateSerializer
from juloserver.portal.object.bulk_upload.tests import get_axiata_data

fake = Faker()
fake.add_provider(JuloFakerProvider)


class TestApplicationPartnerUpdateSerializer(TestCase):
    def setUp(self):
        super().setUp()
        self.app_version = AppVersionFactory(status='latest')

    def test_email_uppercase(self):
        # Borrowed from juloserver.portal.object.bulk_upload.tests
        # because it used on that subapp too.
        data = get_axiata_data()

        data['email'] = 'EmAIL@TesTing.com'
        serializer = ApplicationPartnerUpdateSerializer(data=data)

        expected_email = 'email@testing.com'
        self.assertTrue(serializer.is_valid())
        self.assertEqual(expected_email, serializer.data['email'])


class TestMerchantFinancingUploadRegisterSerializer(TestCase):
    def setUp(self):
        self.partner = PartnerFactory(is_active=True, name=MerchantFinancingCSVUploadPartner.EFISHERY)

        self.partnership_flow_flag = PartnershipFlowFlag.objects.create(
            partner=self.partner,
            name=PartnershipFlag.FIELD_CONFIGURATION,
            configs={}
        )
        self.field_configs = self.partnership_flow_flag.configs

        self.data = {
            "ktp_photo": 'https://test.com',
            "selfie_photo": 'https://test.com',
            "fullname": fake.name(),
            "mobile_phone_1": '08464688001',
            "ktp": '1616161806940001',
            "email": fake.random_email(),
            "gender": 'Pria',
            "birth_place": 'Kendal',
            "dob": '1981-03-12',
            "marital_status": 'Menikah',
            "close_kin_name": fake.name(),
            "close_kin_mobile_phone": '084533341001',
            "address_provinsi": 'Jawa Tengah',
            "address_kabupaten": 'Kabupaten Kendal',
            "address_kecamatan": 'Truko',
            "address_kodepos": '51353',
            "address_street_num": fake.address(),
            "bank_name": '',
            "bank_account_number": '',
            "loan_purpose": 'Modal Usaha',
            "monthly_income": '85000000',
            "monthly_expenses": '60000000',
            "pegawai": '10',
            "usaha": 'Budidaya Ikan',
            "selfie_n_ktp": 'https://test.com',
            "approved_limit": '20000000',
            "application_xid": '',
            "last_education": '',
            "home_status": '',
            "kin_name": '',
            "kin_mobile_phone": '',
        }

    def test_validate_close_kin_name(self):

        # Without field config with data
        serializer = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Without field config without data
        self.data['close_kin_name'] = ''
        serializer = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer.is_valid())

        # Set config to False
        self.data['close_kin_name'] = fake.name()
        self.partnership_flow_flag.configs = {
            'close_kin_name': False,
            'close_kin_mobile_phone': False,
        }
        self.partnership_flow_flag.save()
        self.field_configs = self.partnership_flow_flag.configs

        # With field config False and exist data
        serializer_2 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_2.is_valid())

        # With field config False and empty data
        self.data['close_kin_name'] = ''
        serializer_3 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_3.is_valid())

        # Set config to True
        self.partnership_flow_flag.configs.update(
            {'close_kin_name': True}
        )
        self.partnership_flow_flag.save()
        self.field_configs = self.partnership_flow_flag.configs

        # With field config True and exist data
        self.data['close_kin_name'] = fake.name()
        serializer_4 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_4.is_valid())

        # With field config True and empty data
        self.data['close_kin_name'] = ''
        serializer_5 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_5.is_valid())
        self.assertIsNotNone(serializer_5.errors.get('close_kin_name'))

    def test_validate_close_kin_mobile_phone(self):
        # Without field config with data
        serializer = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Without field config without data
        self.data['close_kin_mobile_phone'] = ''
        serializer = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Set config to False
        self.data['close_kin_mobile_phone'] = '084533341001'
        self.partnership_flow_flag.configs = {
            'close_kin_name': False,
            'close_kin_mobile_phone': False,
        }
        self.partnership_flow_flag.save()
        self.field_configs = self.partnership_flow_flag.configs

        # With field config False and exist data
        serializer_2 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_2.is_valid())

        # With field config False and empty data
        self.data['close_kin_mobile_phone'] = ''
        serializer_3 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_3.is_valid())

        # Set config to True
        self.partnership_flow_flag.configs.update(
            {'close_kin_mobile_phone': True}
        )
        self.partnership_flow_flag.save()
        self.field_configs = self.partnership_flow_flag.configs

        # With field config True and exist data
        self.data['close_kin_mobile_phone'] = '084533341001'
        serializer_4 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_4.is_valid())

        # With field config True and empty data
        self.data['close_kin_mobile_phone'] = ''
        serializer_5 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_5.is_valid())
        self.assertIsNotNone(serializer_5.errors.get('close_kin_mobile_phone'))

    def test_validate_last_education(self):
        # Without field config with data
        serializer = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Without field config without data
        self.data['last_education'] = ''
        serializer = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Set config to False
        self.field_configs['last_education'] = False
        self.partnership_flow_flag.configs.update(self.field_configs)
        self.partnership_flow_flag.save()

        # With field config False and empty data
        self.data['last_education'] = ''
        serializer_2 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_2.is_valid())

        # With field config False and exist data
        self.data['last_education'] = 'S1'
        serializer_3 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_3.is_valid())

        # Set config to True
        self.field_configs['last_education'] = True
        self.partnership_flow_flag.configs.update(self.field_configs)
        self.partnership_flow_flag.save()

        # With field config True and exist data
        self.data['last_education'] = 's1'
        serializer_4 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_4.is_valid())

        # With field config True and empty data
        self.data['last_education'] = ''
        serializer_5 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_5.is_valid())
        self.assertIsNotNone(serializer_5.errors.get('last_education'))

        # With field config True and data not according to master value
        self.data['last_education'] = 's14'
        serializer_6 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_6.is_valid()
        self.assertIsNotNone(serializer_6.errors.get('last_education'))

    def test_validate_home_status(self):
        # Without field config with data
        serializer = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Without field config without data
        self.data['home_status'] = ''
        serializer = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Set config to False
        self.field_configs['home_status'] = False
        self.partnership_flow_flag.configs.update(self.field_configs)
        self.partnership_flow_flag.save()

        # With field config False and empty data
        self.data['home_status'] = ''
        serializer_2 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_2.is_valid())

        # With field config False and exist data
        self.data['home_status'] = 'milik sendiri, Lunas'
        serializer_3 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_3.is_valid())

        # Set config to True
        self.field_configs['home_status'] = True
        self.partnership_flow_flag.configs.update(self.field_configs)
        self.partnership_flow_flag.save()

        # With field config True and exist data
        self.data['home_status'] = 'Kontrak'
        serializer_4 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_4.is_valid())

        # With field config True and empty data
        self.data['home_status'] = ''
        serializer_5 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_5.is_valid())
        self.assertIsNotNone(serializer_5.errors.get('home_status'))

        # With field config True and data not according to master value
        self.data['home_status'] = 'milik teman'
        serializer_6 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_6.is_valid()
        self.assertIsNotNone(serializer_6.errors.get('home_status'))

    def test_validate_kin_name(self):
        # Without config and data
        serializer = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Without config and with data
        self.data['kin_name'] = 'Deni'
        serializer_2 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_2.is_valid())

        # Set config to False
        self.field_configs['kin_name'] = False
        self.partnership_flow_flag.configs.update(self.field_configs)
        self.partnership_flow_flag.save()

        # With config False and empty data
        self.data['kin_name'] = ''
        serializer_3 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_3.is_valid())

        # With config False and data
        self.data['kin_name'] = fake.name()
        serializer_4 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_4.is_valid())

        # Set config to True
        self.field_configs['kin_name'] = True
        self.partnership_flow_flag.configs.update(self.field_configs)
        self.partnership_flow_flag.save()

        # With field config True and empty data
        self.data['kin_name'] = ''
        serializer_5 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_5.is_valid()
        self.assertIsNotNone(serializer_5.errors.get('kin_name'))

        # With field config True and valid data
        self.data['kin_name'] = ' dEni kurniawan'
        serializer_6 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_6.is_valid()
        self.assertEqual(True, serializer_6.is_valid())

        # With field config True and less than 3 char
        self.data['kin_name'] = 'De'
        serializer_7 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_7.is_valid()
        self.assertIsNotNone(serializer_7.errors.get('kin_name'))

        # With field config True and contain digit
        self.data['kin_name'] = 'Deni1'
        serializer_8 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_8.is_valid()
        self.assertIsNotNone(serializer_8.errors.get('kin_name'))

        # With field config True and allowed symbol (. , ' -)
        self.data['kin_name'] = "Deni.,'-"
        serializer_9 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_9.is_valid()
        self.assertIsNotNone(serializer_9.errors.get('kin_name'))

        # With field config True and double space
        self.data['kin_name'] = "Deni  kurniawan"
        serializer_10 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_10.is_valid()
        self.assertIsNotNone(serializer_10.errors.get('kin_name'))

    def test_validate_kin_mobile_phone(self):
        # Without config and data
        serializer = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Without config and with valid data
        self.data['kin_mobile_phone'] = '0816123444'
        serializer_2 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_2.is_valid())

        # Set config to False
        self.field_configs['kin_mobile_phone'] = False
        self.partnership_flow_flag.configs.update(self.field_configs)
        self.partnership_flow_flag.save()

        # With config False and empty data
        self.data['kin_mobile_phone'] = ''
        serializer_3 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_3.is_valid())

        # With config False and valid data
        self.data['kin_mobile_phone'] = '081612344444'
        serializer_4 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_4.is_valid())

        # Set config to True
        self.field_configs['kin_mobile_phone'] = True
        self.partnership_flow_flag.configs.update(self.field_configs)
        self.partnership_flow_flag.save()

        # With field config True and empty data
        self.data['kin_mobile_phone'] = ''
        serializer_5 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_5.is_valid()
        self.assertIsNotNone(serializer_5.errors.get('kin_mobile_phone'))

        # With field config True and valid data
        self.data['kin_mobile_phone'] = '081612344444'
        serializer_6 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_6.is_valid()
        self.assertEqual(True, serializer_6.is_valid())

        # With field config True and less than 10 char
        self.data['kin_mobile_phone'] = '08161234'
        serializer_7 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_7.is_valid()
        self.assertIsNotNone(serializer_7.errors.get('kin_mobile_phone'))

        # With field config True and more than 14 char
        self.data['kin_mobile_phone'] = '0816123444441234'
        serializer_8 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_8.is_valid()
        self.assertIsNotNone(serializer_8.errors.get('kin_mobile_phone'))

        # With field config True and allowed symbol (. , ' -)
        self.data['kin_mobile_phone'] = "0816.12344444"
        serializer_9 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_9.is_valid()
        self.assertIsNotNone(serializer_9.errors.get('kin_mobile_phone'))

        # With field config True and double space
        self.data['kin_mobile_phone'] = "0816  12344444"
        serializer_10 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_10.is_valid()
        self.assertIsNotNone(serializer_10.errors.get('kin_mobile_phone'))

        # With field config True and repeat number until 7 times
        self.data['kin_mobile_phone'] = "081111111234"
        serializer_11 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_11.is_valid()
        self.assertIsNotNone(serializer_11.errors.get('kin_mobile_phone'))

        # With field config True and same number with close kin
        self.data['kin_mobile_phone'] = '081612344444'
        self.data['close_kin_mobile_phone'] = '081612344444'
        serializer_12 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_12.is_valid())

        # With field config True and invalid format
        self.data['kin_mobile_phone'] = '02412344444'
        serializer_13 = MerchantFinancingUploadRegisterSerializer(
            data=self.data,
            context={'partner_id': self.partner.id, 'field_config': self.field_configs}
        )
        serializer_13.is_valid()
        self.assertIsNotNone(serializer_13.errors.get('kin_mobile_phone'))
