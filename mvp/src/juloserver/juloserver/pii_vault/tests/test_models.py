import copy
from datetime import datetime
from django.test.testcases import TestCase

from mock import patch
from juloserver.julo.models import (
    Customer,
    Application,
    ApplicationOriginal,
    AuthUser,
    AuthUserPiiData,
    FDCInquiry,
)

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    FeatureSettingFactory,
    FDCInquiryFactory,
)
from juloserver.pii_vault.models import PiiVaultEvent


class TestCustomerPiiVaultModels(TestCase):
    def setUp(self):
        self.customer_data = dict(
            user=AuthUserFactory(),
            fullname='tester',
            email='tester@testspeed.com',
            is_email_verified=False,
            phone='08888888888',
            is_phone_verified=False,
            country='',
            self_referral_code='',
            email_verification_key='email_verification_key',
            email_key_exp_date=datetime.today(),
            reset_password_key='',
            reset_password_exp_date=None,
            nik=None,
        )
        self.application_data = dict(
            loan_amount_request=2000000,
            loan_duration_request=4,
            loan_purpose='PENDIDIKAN',
            loan_purpose_desc='Biaya pendidikan',
            marketing_source='Facebook',
            referral_code='',
            is_own_phone=True,
            fullname='test',
            gender='Wanita',
            ktp='3271065902890002',
            address_provinsi='Gorontalo',
            address_kabupaten='Bogor',
            address_kecamatan='Tanah Sareal',
            address_kelurahan='Kedung Badak',
            address_kodepos='16164',
            occupied_since='2014-02-01',
            home_status='',
            landlord_mobile_phone='',
            mobile_phone_1='081218926858',
            has_whatsapp_1=True,
            mobile_phone_2='',
            has_whatsapp_2='',
            email='test@gmail.com',
            bbm_pin='',
            twitter_username='',
            instagram_username='',
            marital_status='',
            dependent=3,
            spouse_dob='1990-02-02',
            spouse_mobile_phone='0811144247',
            spouse_has_whatsapp=True,
            kin_dob='1990-02-02',
            kin_gender='Pria',
            kin_mobile_phone='08777788929',
            kin_relationship='',
            job_type='Pegawai swasta',
            job_industry='Admin / Finance / HR',
            job_function='',
            job_description='Admin / Finance / HR',
            company_name='',
            company_phone_number='',
            work_kodepos='',
            job_start='2015-11-02',
            monthly_income=4000000,
            income_1=3500000,
            income_2=500000,
            income_3=200000,
            last_education='SMA',
            college='',
            major='',
            graduation_year='2007',
            gpa='2.84',
            has_other_income=True,
            other_income_amount=200000,
            other_income_source='',
            monthly_housing_cost=1000000,
            monthly_expenses=2000000,
            total_current_debt=230000,
            vehicle_type_1='Sepeda Motor',
            vehicle_ownership_1='Mencicil',
            bank_name='BCA',
            bank_branch='sudirman',
            bank_account_number='1234567890',
            is_term_accepted=True,
            is_verification_agreed=True,
            is_document_submitted=None,
            is_sphp_signed=None,
            sphp_exp_date='2017-09-08',
            app_version='',
            is_fdc_risky=False,
            payday=7,
        )
        FeatureSettingFactory(feature_name='onboarding_pii_vault_tokenization')

    @patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_save(self, mock_send_pii_vault_events):
        # create
        ## Customer
        customer = Customer(**self.customer_data)
        customer.save()
        mock_send_pii_vault_events.assert_called_once_with(
            {
                'customer': [
                    {
                        'resource': customer,
                        'resource_id': customer.id,
                        'fields': ['fullname', 'phone', 'email'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )
        ## Application
        application = Application(**self.application_data, customer_id=customer.id)
        application.save()
        mock_send_pii_vault_events.assert_called_with(
            {
                'application': [
                    {
                        'resource': application,
                        'resource_id': application.id,
                        'fields': ['fullname', 'ktp', 'email', 'mobile_phone_1'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )

        ## Application original
        application_original = ApplicationOriginal(
            **self.application_data, customer_id=customer.id, current_application=application
        )
        application_original.save()
        mock_send_pii_vault_events.assert_called_with(
            {
                'application_original': [
                    {
                        'resource': application_original,
                        'resource_id': application_original.id,
                        'fields': ['fullname', 'ktp', 'email', 'mobile_phone_1'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )

    @patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_create(self, mock_send_pii_vault_events):
        # Customer
        customer = Customer.objects.create(**self.customer_data)
        mock_send_pii_vault_events.assert_called_once_with(
            {
                'customer': [
                    {
                        'resource': customer,
                        'resource_id': customer.id,
                        'fields': ['fullname', 'phone', 'email'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )
        self.assertIsNotNone(customer.customer_xid)

        # Application
        application = Application.objects.create(**self.application_data, customer=customer)
        mock_send_pii_vault_events.assert_called_with(
            {
                'application': [
                    {
                        'resource': application,
                        'resource_id': application.id,
                        'fields': ['fullname', 'ktp', 'email', 'mobile_phone_1'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )
        self.assertIsNotNone(application.application_xid)

        # Application original
        application_original = ApplicationOriginal.objects.create(
            **self.application_data,
            current_application=application,
            customer=customer,
        )
        mock_send_pii_vault_events.assert_called_with(
            {
                'application_original': [
                    {
                        'resource': application_original,
                        'resource_id': application_original.id,
                        'fields': ['fullname', 'ktp', 'email', 'mobile_phone_1'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )

    @patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_update(self, mock_send_pii_vault_events):
        # Customer
        customer = Customer.objects.create(**self.customer_data)
        mock_send_pii_vault_events.assert_called_once_with(
            {
                'customer': [
                    {
                        'resource': customer,
                        'resource_id': customer.id,
                        'fields': ['fullname', 'phone', 'email'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )
        Customer.objects.filter(id=customer.id).update(phone='0999999999999')
        mock_send_pii_vault_events.assert_called_with(
            {
                'customer': [
                    {
                        'resource': customer,
                        'resource_id': customer.id,
                        'fields': ['phone'],
                        'pii_type': 'cust',
                    }
                ]
            },
            bulk_create=True,
        )

        # Application
        application = Application.objects.create(**self.application_data, customer=customer)
        mock_send_pii_vault_events.assert_called_with(
            {
                'application': [
                    {
                        'resource': application,
                        'resource_id': application.id,
                        'fields': ['fullname', 'ktp', 'email', 'mobile_phone_1'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )
        Application.objects.filter(id=application.id).update(mobile_phone_1='0999999999999')
        mock_send_pii_vault_events.assert_called_with(
            {
                'application': [
                    {
                        'resource': application,
                        'resource_id': application.id,
                        'fields': ['mobile_phone_1'],
                        'pii_type': 'cust',
                    }
                ]
            },
            bulk_create=True,
        )

        # Application original
        application_original = ApplicationOriginal.objects.create(
            **self.application_data,
            current_application=application,
            customer=customer,
        )
        mock_send_pii_vault_events.assert_called_with(
            {
                'application_original': [
                    {
                        'resource': application_original,
                        'resource_id': application_original.id,
                        'fields': ['fullname', 'ktp', 'email', 'mobile_phone_1'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )
        (
            ApplicationOriginal.objects.filter(id=application_original.id).update(
                mobile_phone_1='0999999999999'
            )
        )
        mock_send_pii_vault_events.assert_called_with(
            {
                'application_original': [
                    {
                        'resource': application_original,
                        'resource_id': application_original.id,
                        'fields': ['mobile_phone_1'],
                        'pii_type': 'cust',
                    }
                ]
            },
            bulk_create=True,
        )

    @patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_bulk_create(self, mock_send_pii_vault_events):
        FeatureSettingFactory(feature_name='onboarding_pii_vault_tokenization')
        # Customer
        customer = Customer(**self.customer_data)
        Customer.objects.bulk_create([customer])
        mock_send_pii_vault_events.assert_called_once_with(
            {
                'customer': [
                    {
                        'resource': customer,
                        'resource_id': customer.id,
                        'fields': ['fullname', 'phone', 'email'],
                        'pii_type': 'cust',
                    }
                ]
            },
            bulk_create=True,
        )

        # Application
        application = Application(**self.application_data, customer=customer)
        Application.objects.bulk_create([application])
        mock_send_pii_vault_events.assert_called_with(
            {
                'application': [
                    {
                        'resource': application,
                        'resource_id': application.id,
                        'fields': ['fullname', 'ktp', 'email', 'mobile_phone_1'],
                        'pii_type': 'cust',
                    }
                ]
            },
            bulk_create=True,
        )

        # Application original
        application_original = ApplicationOriginal(
            **self.application_data,
            current_application=application,
            customer=customer,
        )
        ApplicationOriginal.objects.bulk_create([application_original])
        mock_send_pii_vault_events.assert_called_with(
            {
                'application_original': [
                    {
                        'resource': application_original,
                        'resource_id': application_original.id,
                        'fields': ['fullname', 'ktp', 'email', 'mobile_phone_1'],
                        'pii_type': 'cust',
                    }
                ]
            },
            bulk_create=True,
        )

    @patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_create_update_with_emtpy_pii_data(self, mock_send_pii_vault_events):
        self.customer_data.update(fullname=None, email=None, phone=None)
        customer_1 = Customer(**self.customer_data)
        customer_1.save()
        mock_send_pii_vault_events.assert_not_called()

        user_2 = AuthUserFactory()
        self.customer_data['user'] = user_2
        customer_2 = Customer.objects.create(**self.customer_data)
        mock_send_pii_vault_events.assert_not_called()

        Customer.objects.filter(id=customer_2.id).update(country='Indo')
        mock_send_pii_vault_events.assert_not_called()

        user_3 = AuthUserFactory()
        self.customer_data['user'] = user_3
        customer_3 = Customer.objects.bulk_create([Customer(**self.customer_data)])
        mock_send_pii_vault_events.assert_not_called()

        Customer.objects.filter(id=customer_3[0].id).update(email='vvvv@gmail.com')
        mock_send_pii_vault_events.assert_called_once()

    @patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_send_to_custom_queue(self, mock_send_pii_vault_events):
        # test save
        fdc_inquiry = FDCInquiry(nik='1231112011969098')
        fdc_inquiry.save()
        mock_send_pii_vault_events.assert_called_once_with(
            {
                'fdc_inquiry': [
                    {
                        'resource': fdc_inquiry,
                        'resource_id': fdc_inquiry.id,
                        'fields': ['nik'],
                        'pii_type': 'kv',
                    }
                ]
            },
            async_queue='onboarding_pii_vault',
        )

        # test update
        FDCInquiry.objects.filter(id=fdc_inquiry.id).update(
            nik='1231112011969099',
            email='vvvv@gmail.com',
        )
        mock_send_pii_vault_events.assert_called_with(
            {
                'fdc_inquiry': [
                    {
                        'resource': fdc_inquiry,
                        'resource_id': fdc_inquiry.id,
                        'fields': ['nik', 'email'],
                        'pii_type': 'kv',
                    }
                ]
            },
            bulk_create=True,
            async_queue='onboarding_pii_vault',
        )

        # test with custom queue
        fdc_inquiry_2 = FDCInquiry(nik='1231112011969999')
        FDCInquiry.objects.bulk_create([fdc_inquiry_2])
        mock_send_pii_vault_events.assert_called_with(
            {
                'fdc_inquiry': [
                    {
                        'resource': fdc_inquiry_2,
                        'resource_id': fdc_inquiry_2.id,
                        'fields': ['nik'],
                        'pii_type': 'kv',
                    }
                ]
            },
            bulk_create=True,
            async_queue='onboarding_pii_vault',
        )


class TestPiiVaultEventModelReturnIDQueryset(TestCase):
    def setUp(self):
        pass

    def test_bulk_create_return_id(self):
        pii_vault_event = PiiVaultEvent(vault_xid='test_vault_xid', payload={}, status='intial')
        pii_vault_events = PiiVaultEvent.objects.bulk_create([pii_vault_event])
        self.assertIsNotNone(pii_vault_events[0].id)


class TestAuthUserProxyPiiVaultModels(TestCase):
    def setUp(self):
        self.user_data = {'username': 'superuser', 'email': 'homelander@marvel.com'}
        FeatureSettingFactory(feature_name='onboarding_pii_vault_tokenization', parameters={})

    @patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_save(self, mock_send_pii_vault_events):
        # create
        auth_user = AuthUser(**self.user_data)
        auth_user.save()
        mock_send_pii_vault_events.assert_called_once_with(
            {
                'auth_user': [
                    {
                        'resource': auth_user,
                        'resource_id': auth_user.id,
                        'fields': ['email'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )
        # update
        auth_user_pii_data = AuthUserPiiData.objects.create(
            user=auth_user, email_tokenized='12312312312'
        )
        auth_user.email = 'superman@dc.com'
        auth_user.save()
        mock_send_pii_vault_events.assert_called_with(
            {
                'auth_user': [
                    {
                        'resource': auth_user,
                        'resource_id': auth_user.id,
                        'fields': ['email'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )
        auth_user_pii_data.refresh_from_db()
        self.assertIsNone(auth_user_pii_data.email_tokenized)

    @patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_create(self, mock_send_pii_vault_events):
        auth_user = AuthUser.objects.create(**self.user_data)
        mock_send_pii_vault_events.assert_called_once_with(
            {
                'auth_user': [
                    {
                        'resource': auth_user,
                        'resource_id': auth_user.id,
                        'fields': ['email'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )

    @patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_update(self, mock_send_pii_vault_events):
        auth_user = AuthUser.objects.create(**self.user_data)
        auth_user_pii_data = AuthUserPiiData.objects.create(
            user=auth_user, email_tokenized='12312312312'
        )
        mock_send_pii_vault_events.assert_called_once_with(
            {
                'auth_user': [
                    {
                        'resource': auth_user,
                        'resource_id': auth_user.id,
                        'fields': ['email'],
                        'pii_type': 'cust',
                    }
                ]
            }
        )
        AuthUser.objects.filter(id=auth_user.id).update(email='thor-rabbit@marvel.com')
        mock_send_pii_vault_events.assert_called_with(
            {
                'auth_user': [
                    {
                        'resource': auth_user,
                        'resource_id': auth_user.id,
                        'fields': ['email'],
                        'pii_type': 'cust',
                    }
                ]
            },
            bulk_create=True,
        )
        auth_user_pii_data.refresh_from_db()
        self.assertIsNone(auth_user_pii_data.email_tokenized)

    @patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_bulk_create(self, mock_send_pii_vault_events):
        FeatureSettingFactory(feature_name='onboarding_pii_vault_tokenization', parameters={})
        # Customer
        auth_user = AuthUser(**self.user_data)
        AuthUser.objects.bulk_create([auth_user])
        mock_send_pii_vault_events.assert_called_once_with(
            {
                'auth_user': [
                    {
                        'resource': auth_user,
                        'resource_id': auth_user.id,
                        'fields': ['email'],
                        'pii_type': 'cust',
                    }
                ]
            },
            bulk_create=True,
        )
