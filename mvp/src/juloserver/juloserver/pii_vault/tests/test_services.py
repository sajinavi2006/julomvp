import copy
import mock
from unittest.mock import ANY
from datetime import timedelta, datetime
from django.test.testcases import TestCase
from django.db import transaction
from django.utils import timezone

from juloserver.julo.models import Application
from mock import patch

from juloserver.grab.models import GrabCustomerData
from juloserver.grab.tests.factories import GrabCustomerDataFactory
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    AuthUserPiiData,
    ApplicationOriginal,
    Customer,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationJ1Factory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.pii_vault.partnership.services import (
    partnership_tokenize_pii_data_task,
    partnership_construct_pii_data,
    partnership_get_pii_schema,
    partnership_tokenize_pii_data,
    partnership_vault_xid_from_values,
    get_id_from_vault_xid,
    partnership_vault_xid_from_resource,
    partnership_pii_mapping_field,
    partnership_reverse_field_mapper,
)
from juloserver.pii_vault.services import (
    get_resource,
    get_resource_with_select_for_update,
    get_vault_xid_from_resource,
    tokenize_data_from_resource,
    update_resource,
    tokenize_pii_data,
    back_fill_pii_data,
    recover_pii_vault_event,
    map_data_for_vault_service,
    map_data_from_vault_service,
    generate_pii_vault_event_and_refine_pii_data,
    is_data_to_be_tokenization,
    get_pii_data_from_save_resource,
    prepare_pii_event,
    detokenize_pii_data,
    detokenize_pii_data_by_client,
    detokenize_for_model_object,
)
from juloserver.pii_vault.constants import PiiSource, PiiVaultEventStatus, DetokenizeResourceType
from juloserver.pii_vault.models import PiiVaultEvent
from juloserver.pii_vault.exceptions import PIIDataIsEmpty


class TestGetResource(TestCase):
    def setUp(self):
        pass

    def test_get_resource_success(self):
        customer = CustomerFactory()
        with transaction.atomic():
            resource = get_resource(PiiSource.CUSTOMER, customer.id)
        self.assertEqual(resource.id, customer.id)

        auth_user = AuthUserFactory()
        with transaction.atomic():
            resource = get_resource(PiiSource.AUTH_USER, auth_user.id)
        self.assertEqual(resource.id, auth_user.id)

        application = ApplicationFactory()
        with transaction.atomic():
            resource = get_resource(PiiSource.APPLICATION, application.id)
        self.assertEqual(resource.id, application.id)

    def test_get_resource_fail(self):
        resource = get_resource('fake_resource', 312312)
        self.assertIsNone(resource)

    def test_get_resource_with_select_for_update_success(self):
        customer = CustomerFactory()
        with transaction.atomic():
            resource = get_resource_with_select_for_update(PiiSource.CUSTOMER, customer.id)
        self.assertEqual(resource.id, customer.id)

        auth_user = AuthUserFactory()
        with transaction.atomic():
            resource = get_resource_with_select_for_update(PiiSource.AUTH_USER, auth_user.id)
        self.assertEqual(resource.id, auth_user.id)

        application = ApplicationFactory()
        with transaction.atomic():
            resource = get_resource_with_select_for_update(PiiSource.APPLICATION, application.id)
        self.assertEqual(resource.id, application.id)

    def test_get_resource_with_select_for_update_fail(self):
        resource = get_resource_with_select_for_update('fake_resource', 312312)
        self.assertIsNone(resource)


class TestGetVaultXIDFromResource(TestCase):
    def setUp(self):
        pass

    def test_get_vault_xid_from_resource_success(self):
        customer = CustomerFactory()
        result = get_vault_xid_from_resource(PiiSource.CUSTOMER, customer)
        self.assertEqual(result, str(customer.customer_xid))

        result = get_vault_xid_from_resource(PiiSource.AUTH_USER, customer.user)
        self.assertEqual(result, 'au_{}'.format(customer.user.id))

        application = ApplicationFactory(customer=customer)
        result = get_vault_xid_from_resource(PiiSource.APPLICATION, application)
        self.assertEqual(result, 'ap_{}_{}'.format(application.id, customer.customer_xid))


class TestMappingDataWithVaultService(TestCase):
    def setUp(self):
        pass

    def test_mapping_data_for_vault_service(self):
        pii_information = {
            'fullname': 'peter parker',
            'email': 'peter@marvel.com',
            'phone': '0999999999',
            'nik': '123125321312123',
        }
        result = map_data_for_vault_service(pii_information, PiiSource.CUSTOMER)
        self.assertEqual(
            result,
            {
                'name': 'peter parker',
                'email': 'peter@marvel.com',
                'mobile_number': '0999999999',
                'nik': '123125321312123',
            },
        )

        pii_information = {
            'fullname': 'peter parker',
            'email': 'peter@marvel.com',
            'mobile_phone_1': '0999999999',
            'ktp': '123125321312123',
        }
        result = map_data_for_vault_service(pii_information, PiiSource.APPLICATION)
        self.assertEqual(
            result,
            {
                'name': 'peter parker',
                'email': 'peter@marvel.com',
                'mobile_number': '0999999999',
                'nik': '123125321312123',
            },
        )

        pii_information = {
            'fullname': 'peter parker',
            'email': 'peter@marvel.com',
            'mobile_phone_1': '0999999999',
            'ktp': '123125321312123',
        }
        result = map_data_for_vault_service(pii_information, PiiSource.APPLICATION_ORIGINAL)
        self.assertEqual(
            result,
            {
                'name': 'peter parker',
                'email': 'peter@marvel.com',
                'mobile_number': '0999999999',
                'nik': '123125321312123',
            },
        )

    def test_mapping_data_from_vault_service(self):
        tokenized_data = {
            'name': '<peter parker>',
            'email': '<peter@marvel.com>',
            'mobile_number': '<0999999999>',
            'nik': '<123125321312123>',
        }
        pii_data = {'fields': ['fullname', 'email', 'phone', 'nik']}
        result = map_data_from_vault_service(tokenized_data, pii_data, PiiSource.CUSTOMER)
        self.assertEqual(
            result,
            {
                'fullname_tokenized': '<peter parker>',
                'email_tokenized': '<peter@marvel.com>',
                'phone_tokenized': '<0999999999>',
                'nik_tokenized': '<123125321312123>',
            },
        )

        pii_data = {'fields': ['fullname', 'email', 'mobile_phone_1', 'ktp']}
        result = map_data_from_vault_service(tokenized_data, pii_data, PiiSource.APPLICATION)
        self.assertEqual(
            result,
            {
                'fullname_tokenized': '<peter parker>',
                'email_tokenized': '<peter@marvel.com>',
                'mobile_phone_1_tokenized': '<0999999999>',
                'ktp_tokenized': '<123125321312123>',
            },
        )

        pii_data = {'fields': ['fullname', 'email', 'mobile_phone_1', 'ktp']}
        result = map_data_from_vault_service(
            tokenized_data, pii_data, PiiSource.APPLICATION_ORIGINAL
        )
        self.assertEqual(
            result,
            {
                'fullname_tokenized': '<peter parker>',
                'email_tokenized': '<peter@marvel.com>',
                'mobile_phone_1_tokenized': '<0999999999>',
                'ktp_tokenized': '<123125321312123>',
            },
        )

        tokenized_data = {
            'email': '<peter@marvel.com>',
            'mobile_number': '<0999999999>',
        }
        pii_data = {'fields': ['phone_number', 'email_address']}
        result = map_data_from_vault_service(
            tokenized_data, pii_data, PiiSource.MONNAI_INSIGHT_REQUEST
        )
        self.assertEqual(
            result,
            {
                'phone_number_tokenized': '<0999999999>',
                'email_address_tokenized': '<peter@marvel.com>',
            },
        )

        result = map_data_from_vault_service(tokenized_data, pii_data, PiiSource.SEON_FRAUD_REQUEST)
        self.assertEqual(
            result,
            {
                'phone_number_tokenized': '<0999999999>',
                'email_address_tokenized': '<peter@marvel.com>',
            },
        )


class TestTokenizeDataFromResource(TestCase):
    def setUp(self):
        self.resource = CustomerFactory()
        self.source = PiiSource.CUSTOMER

    @patch('juloserver.pii_vault.services.pii_vault_client')
    def test_tokenize_data_success(self, mock_pii_vault_client):
        pii_data = {'resource_id': self.resource.id, 'fields': ['email']}
        mock_pii_vault_client.tokenize.return_value = [{'fields': {'email': '<EMAIL>'}}]
        result = tokenize_data_from_resource(PiiSource.CUSTOMER, pii_data, self.resource)
        self.assertEqual(result, {'email_tokenized': '<EMAIL>'})

    def test_tokenize_data_success_resource_emtpy(self):
        pii_data = {'resource_id': self.resource.id, 'fields': ['email']}
        self.resource.email = None
        self.resource.save()
        self.assertRaises(
            PIIDataIsEmpty, tokenize_data_from_resource, PiiSource.CUSTOMER, pii_data, self.resource
        )

    @patch('juloserver.pii_vault.services.pii_vault_client')
    def test_tokenize_data_pii_vault_client_error(self, mock_pii_vault_client):
        pii_data = {'resource_id': self.resource.id, 'fields': ['email']}
        mock_pii_vault_client.tokenize.return_value = [
            {'error': 'server busy!!!', 'fields': {'email': '<EMAIL>'}}
        ]
        self.assertRaises(
            JuloException, tokenize_data_from_resource, PiiSource.CUSTOMER, pii_data, self.resource
        )


class TestUpdateResource(TestCase):
    def setUp(self):
        self.resource = CustomerFactory(email='tonystark@marvel.universal')

    def test_update_resource_success(self):
        data = {'email_tokenized': '<TOKENIZED>'}
        pii_vault_event = PiiVaultEvent.objects.create(
            vault_xid=self.resource.customer_xid,
            payload={PiiSource.CUSTOMER: [{'resource_id': self.resource.id, 'fields': ['email']}]},
            status=PiiVaultEventStatus.INITIAL,
        )
        update_resource(
            PiiSource.CUSTOMER,
            {
                'pii_vault_event_id': pii_vault_event.id,
                'resource_id': self.resource.id,
                'fields': ['email'],
            },
            self.resource,
            data,
        )
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.email_tokenized, data['email_tokenized'])

        # test update resource for AUTH_USER
        pii_vault_event = PiiVaultEvent.objects.create(
            vault_xid='au_{}'.format(self.resource.user),
            payload={PiiSource.CUSTOMER: [{'resource_id': self.resource.id, 'fields': ['email']}]},
            status=PiiVaultEventStatus.INITIAL,
        )
        update_resource(
            PiiSource.AUTH_USER,
            {
                'pii_vault_event_id': pii_vault_event.id,
                'resource_id': self.resource.user.id,
                'fields': ['email'],
            },
            self.resource.user,
            data,
        )
        resource = AuthUserPiiData.objects.get(user=self.resource.user)
        self.assertEqual(resource.email_tokenized, data['email_tokenized'])


class TestTokenizeData(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(username='0123456789', email='tonystark@dc.com')
        self.customer = CustomerFactory(
            email='tonystark@dc.com', phone='0123456789', user=self.user
        )
        self.application = ApplicationFactory(
            customer=self.customer, email='tonystark@dc.com', mobile_phone_1='0123456789'
        )

    @patch('juloserver.pii_vault.services.pii_vault_client')
    def test_tokenize_data(self, mock_pii_vault_client):
        FeatureSettingFactory(feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_TOKENIZATION)
        pii_vault_event_1 = PiiVaultEvent.objects.create(
            vault_xid='au_{}'.format(self.customer.customer_xid),
            payload={
                PiiSource.CUSTOMER: [
                    {'resource_id': self.customer.id, 'fields': ['email', 'phone']}
                ]
            },
            status=PiiVaultEventStatus.INITIAL,
        )
        pii_vault_event_2 = PiiVaultEvent.objects.create(
            vault_xid='au_{}'.format(self.customer.user.id),
            payload={
                PiiSource.AUTH_USER: [{'resource_id': self.customer.user.id, 'fields': ['email']}]
            },
            status=PiiVaultEventStatus.INITIAL,
        )
        pii_vault_event_3 = PiiVaultEvent.objects.create(
            vault_xid='ap_{}'.format(self.application.id),
            payload={
                PiiSource.APPLICATION: [
                    {'resource_id': self.application.id, 'fields': ['email', 'mobile_phone_1']}
                ]
            },
            status=PiiVaultEventStatus.INITIAL,
        )
        data = {
            PiiSource.CUSTOMER: [
                {
                    'resource_id': self.customer.id,
                    'fields': ['email', 'phone'],
                    'pii_vault_event_id': pii_vault_event_1.id,
                }
            ],
            PiiSource.AUTH_USER: [
                {
                    'resource_id': self.customer.user.id,
                    'fields': ['email'],
                    'pii_vault_event_id': pii_vault_event_2.id,
                }
            ],
            PiiSource.APPLICATION: [
                {
                    'resource_id': self.application.id,
                    'fields': ['email', 'mobile_phone_1'],
                    'pii_vault_event_id': pii_vault_event_3.id,
                }
            ],
        }

        mock_pii_vault_client.tokenize.side_effect = [
            [{'fields': {'email': '<EMAIL>', 'mobile_number': '<PHONE>'}}],
            [{'fields': {'email': '<EMAIL>'}}],
            [{'fields': {'email': '<EMAIL>', 'mobile_number': '<MobilePhone>'}}],
        ]
        tokenize_pii_data(data, run_async=False)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email_tokenized, '<EMAIL>')
        self.assertEqual(self.customer.phone_tokenized, '<PHONE>')

        auth_user_pii_data = AuthUserPiiData.objects.get(user=self.user)
        self.assertEqual(auth_user_pii_data.email_tokenized, '<EMAIL>')

        self.application.refresh_from_db()
        self.assertEqual(self.application.email_tokenized, '<EMAIL>')
        self.assertEqual(self.application.mobile_phone_1_tokenized, '<MobilePhone>')


class TestBackFillPiiData(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(username='0123456789', email='tonystark@dc.com')
        self.customer = CustomerFactory(
            email='tonystark@dc.com', phone='0123456789', user=self.user
        )
        self.application = ApplicationJ1Factory(
            customer=self.customer, email='tonystark@dc.com', mobile_phone_1='0123456789'
        )
        self.application_original = ApplicationOriginal.objects.create(
            current_application=self.application,
            customer=self.customer,
            email=self.application.email,
            mobile_phone_1=self.application.mobile_phone_1,
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_TOKENIZATION,
            parameters={
                'backfill_pii_setting': {
                    'is_active': True,
                    'total_record': 500,
                },
            },
        )

    @patch('juloserver.pii_vault.services.pii_vault_client')
    def test_back_fill_pii_data(self, mock_pii_vault_client):
        mock_pii_vault_client.tokenize.side_effect = [
            [{'fields': {'email': '<EMAIL>', 'mobile_number': '<PHONE>'}}],
            [{'fields': {'email': '<EMAIL>'}}],
            [{'fields': {'email': '<EMAIL>', 'mobile_number': '<MobilePhone>'}}],
            [{'fields': {'email': '<EMAIL>', 'mobile_number': '<MobilePhone>'}}],
        ]
        back_fill_pii_data()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email_tokenized, '<EMAIL>')
        self.assertEqual(self.customer.phone_tokenized, '<PHONE>')

        auth_user_pii_data = AuthUserPiiData.objects.get(user=self.user)
        self.assertEqual(auth_user_pii_data.email_tokenized, '<EMAIL>')

        self.application.refresh_from_db()
        self.assertEqual(self.application.email_tokenized, '<EMAIL>')
        self.assertEqual(self.application.mobile_phone_1_tokenized, '<MobilePhone>')

        self.application_original.refresh_from_db()
        self.assertEqual(self.application_original.email_tokenized, '<EMAIL>')
        self.assertEqual(self.application_original.mobile_phone_1_tokenized, '<MobilePhone>')


class TestRecoverPIIVaultEvent(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(username='0123456789', email='tonystark@dc.com')
        self.customer = CustomerFactory(
            email='tonystark@dc.com', phone='0123456789', user=self.user
        )
        self.application = ApplicationJ1Factory(
            customer=self.customer, email='tonystark@dc.com', mobile_phone_1='0123456789'
        )
        self.application_original = ApplicationOriginal.objects.create(
            current_application=self.application,
            customer=self.customer,
            email=self.application.email,
            mobile_phone_1=self.application.mobile_phone_1,
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_TOKENIZATION,
            parameters={
                'recover_pii_setting': {
                    'is_active': True,
                    'total_record': 500,
                },
            },
        )
        self.pii_event_1 = PiiVaultEvent.objects.create(
            vault_xid='123456789',
            payload={PiiSource.AUTH_USER: [{'resource_id': self.user.id, 'fields': ['email']}]},
            status='failed',
        )
        self.pii_event_2 = PiiVaultEvent.objects.create(
            vault_xid='123456788',
            payload={
                PiiSource.CUSTOMER: [
                    {'resource_id': self.customer.id, 'fields': ['email', 'phone']}
                ]
            },
            status='failed',
        )
        self.pii_event_3 = PiiVaultEvent.objects.create(
            vault_xid='123456787',
            payload={
                PiiSource.APPLICATION: [
                    {'resource_id': self.application.id, 'fields': ['email', 'mobile_phone_1']}
                ]
            },
            status='initial',
        )
        self.pii_event_3.cdate = timezone.localtime(timezone.now() - timedelta(hours=2))
        self.pii_event_3.save()
        self.pii_event_4 = PiiVaultEvent.objects.create(
            vault_xid='123456788',
            payload={
                PiiSource.APPLICATION_ORIGINAL: [
                    {
                        'resource_id': self.application_original.id,
                        'fields': ['email', 'mobile_phone_1'],
                    }
                ]
            },
            status='failed',
        )

    @patch('juloserver.pii_vault.services.pii_vault_client')
    def test_recover_pii_vault_event(self, mock_pii_vault_client):
        mock_pii_vault_client.tokenize.side_effect = [
            [{'fields': {'email': '<EMAIL>'}}],
            [{'fields': {'email': '<EMAIL>', 'mobile_number': '<PHONE>'}}],
            [{'fields': {'email': '<EMAIL>', 'mobile_number': '<MobilePhone>'}}],
            [{'fields': {'email': '<EMAIL>', 'mobile_number': '<MobilePhone>'}}],
        ]
        recover_pii_vault_event()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email_tokenized, '<EMAIL>')
        self.assertEqual(self.customer.phone_tokenized, '<PHONE>')

        auth_user_pii_data = AuthUserPiiData.objects.get(user=self.user)
        self.assertEqual(auth_user_pii_data.email_tokenized, '<EMAIL>')

        self.application.refresh_from_db()
        self.assertEqual(self.application.email_tokenized, '<EMAIL>')
        self.assertEqual(self.application.mobile_phone_1_tokenized, '<MobilePhone>')

        self.application_original.refresh_from_db()
        self.assertEqual(self.application_original.email_tokenized, '<EMAIL>')
        self.assertEqual(self.application_original.mobile_phone_1_tokenized, '<MobilePhone>')

        self.assertIsNone(PiiVaultEvent.objects.filter(pk=self.pii_event_1.id).first())
        self.assertIsNone(PiiVaultEvent.objects.filter(pk=self.pii_event_2.id).first())
        self.assertIsNone(PiiVaultEvent.objects.filter(pk=self.pii_event_3.id).first())
        self.assertIsNone(PiiVaultEvent.objects.filter(pk=self.pii_event_4.id).first())


class TestPartnershipTokenize(TestCase):
    def setUp(self):
        self.auth_user_1 = AuthUserFactory()
        self.customer_1 = CustomerFactory(user=self.auth_user_1)
        self.customer_1.customer_xid = '1321412312'
        self.customer_1.save()
        self.customer_2 = CustomerFactory()
        self.customer_2.customer_xid = '1321412132'
        self.customer_2.save()
        self.application_1 = ApplicationFactory(customer=self.customer_1)
        self.grab_customer_data_1 = GrabCustomerDataFactory(customer=self.customer_1)
        self.grab_customer_data = GrabCustomerDataFactory()
        self.grab_customer_data.phone_number = '6281324123123'
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.PARTNERSHIP_CONFIG_PII_VAULT_TOKENIZATION,
            is_active=True,
            parameters={'grab': {'bulk_process': True, 'async': True, 'singular_process': True}},
        )

    @patch('juloserver.pii_vault.partnership.tasks.pii_vault_client')
    def test_tokenize_data(self, mock_pii_vault_client):
        mock_pii_vault_client.tokenize.return_value = [
            {
                'fields': {
                    'email': '<EMAIL1>',
                    'nik': '<NIK1>',
                    'mobile_number': '<MOBILE_PHONE1>',
                    'name': '<FULLNAME1>',
                    'vault_xid': str(self.customer_1.customer_xid),
                }
            },
            {
                'fields': {
                    'email': '<EMAIL2>',
                    'nik': '<NIK2>',
                    'mobile_number': '<MOBILE_PHONE2>',
                    'name': '<FULLNAME2>',
                    'vault_xid': str(self.customer_2.customer_xid),
                }
            },
        ]
        data = partnership_construct_pii_data(
            PiiSource.CUSTOMER, self.customer_1, fields=['email', 'nik', 'phone', 'fullname']
        )
        data = partnership_construct_pii_data(
            PiiSource.CUSTOMER,
            self.customer_2,
            fields=['email', 'nik', 'phone', 'fullname'],
            constructed_data=data,
        )
        partnership_tokenize_pii_data_task(data)
        self.customer_1.refresh_from_db()
        self.assertEqual(self.customer_1.email_tokenized, '<EMAIL1>')
        self.assertEqual(self.customer_1.nik_tokenized, '<NIK1>')
        self.assertEqual(self.customer_1.phone_tokenized, '<MOBILE_PHONE1>')
        self.assertEqual(self.customer_1.fullname_tokenized, '<FULLNAME1>')

        self.customer_2.refresh_from_db()
        self.assertEqual(self.customer_2.email_tokenized, '<EMAIL2>')
        self.assertEqual(self.customer_2.nik_tokenized, '<NIK2>')
        self.assertEqual(self.customer_2.phone_tokenized, '<MOBILE_PHONE2>')
        self.assertEqual(self.customer_2.fullname_tokenized, '<FULLNAME2>')

    def test_get_pii_schema(self):
        # Please update when adding more schemas
        schema = partnership_get_pii_schema(PiiSource.CUSTOMER)
        self.assertEqual(schema, "customer")

        schema = partnership_get_pii_schema(PiiSource.APPLICATION)
        self.assertEqual(schema, "customer")

    def test_partnership_construct_pii_data_case_1(self):
        constructed_data = partnership_construct_pii_data(
            PiiSource.CUSTOMER, self.customer_1, fields=['email', 'nik']
        )
        constructed_data_expectation = {
            PiiSource.CUSTOMER: [
                {
                    "data": {"email": None, "nik": None},
                    "vault_xid": str(self.customer_1.customer_xid),
                }
            ]
        }
        self.assertDictEqual(constructed_data, constructed_data_expectation)

    @mock.patch(
        'juloserver.pii_vault.partnership.services.partnership_tokenize_pii_data_task.apply_async'
    )
    @mock.patch(
        'juloserver.pii_vault.partnership.services.partnership_sync_process_tokenize_pii_data'
    )
    def test_feature_setting_pii_partnership_case_1(self, mocked_func1, mocked_func2):
        self.feature_setting.is_active = False
        self.feature_setting.save()
        mocked_func1.return_value = None
        mocked_func2.return_value = None
        constructed_data = partnership_construct_pii_data(
            PiiSource.CUSTOMER, self.customer_1, fields=['email', 'nik']
        )
        partnership_tokenize_pii_data(constructed_data, partner_name='grab')
        mocked_func1.assert_not_called()
        mocked_func2.assert_not_called()

    @mock.patch(
        'juloserver.pii_vault.partnership.services.partnership_tokenize_pii_data_task.apply_async'
    )
    @mock.patch(
        'juloserver.pii_vault.partnership.services.partnership_sync_process_tokenize_pii_data'
    )
    def test_feature_setting_pii_partnership_case_2(self, mocked_func1, mocked_func2):
        self.feature_setting.is_active = True
        self.feature_setting.parameters['grab'] = {
            'bulk_process': False,
            'async': True,
            'singular_process': True,
        }
        self.feature_setting.save()
        mocked_func1.return_value = None
        mocked_func2.return_value = None
        constructed_data = partnership_construct_pii_data(
            PiiSource.CUSTOMER, self.customer_1, fields=['email', 'nik']
        )
        partnership_tokenize_pii_data(constructed_data, partner_name='grab')
        mocked_func1.assert_not_called()
        mocked_func2.assert_called()

    @mock.patch(
        'juloserver.pii_vault.partnership.services.partnership_tokenize_pii_data_task.apply_async'
    )
    @mock.patch(
        'juloserver.pii_vault.partnership.services.partnership_sync_process_tokenize_pii_data'
    )
    def test_feature_setting_pii_partnership_case_3(self, mocked_func1, mocked_func2):
        self.feature_setting.is_active = True
        self.feature_setting.parameters['grab'] = {
            'bulk_process': False,
            'async': False,
            'singular_process': True,
        }
        self.feature_setting.save()
        mocked_func1.return_value = None
        mocked_func2.return_value = None
        constructed_data = partnership_construct_pii_data(
            PiiSource.CUSTOMER, self.customer_1, fields=['email', 'nik']
        )
        partnership_tokenize_pii_data(constructed_data, partner_name='grab')
        mocked_func1.assert_called()
        mocked_func2.assert_not_called()

    @mock.patch(
        'juloserver.pii_vault.partnership.services.partnership_tokenize_pii_data_task.apply_async'
    )
    @mock.patch('juloserver.pii_vault.partnership.services.partnership_tokenize_pii_data_task')
    def test_feature_setting_pii_partnership_case_4(self, mocked_func1, mocked_func2):
        self.feature_setting.is_active = True
        self.feature_setting.parameters['grab'] = {
            'bulk_process': False,
            'async': False,
            'singular_process': False,
        }
        self.feature_setting.save()
        mocked_func1.return_value = None
        mocked_func2.return_value = None
        constructed_data = partnership_construct_pii_data(
            PiiSource.CUSTOMER, self.customer_1, fields=['email', 'nik']
        )
        partnership_tokenize_pii_data(constructed_data, partner_name='grab')
        mocked_func1.assert_not_called()
        mocked_func2.assert_not_called()

    @mock.patch(
        'juloserver.pii_vault.partnership.services.partnership_tokenize_pii_data_task.apply_async'
    )
    @mock.patch('juloserver.pii_vault.partnership.services.partnership_tokenize_pii_data_task')
    def test_feature_setting_pii_partnership_case_5(self, mocked_func1, mocked_func2):
        self.feature_setting.is_active = True
        self.feature_setting.parameters['grab'] = {
            'bulk_process': False,
            'async': True,
            'singular_process': False,
        }
        self.feature_setting.save()
        mocked_func1.return_value = None
        mocked_func2.return_value = None
        constructed_data = partnership_construct_pii_data(
            PiiSource.CUSTOMER, self.customer_1, fields=['email', 'nik']
        )
        partnership_tokenize_pii_data(constructed_data, partner_name='grab')
        mocked_func1.assert_not_called()
        mocked_func2.assert_not_called()

    def test_partnership_vault_xid_from_values(self):
        customer_xid = '123123432'
        resource_id = '13232'
        vault_xid = partnership_vault_xid_from_values(PiiSource.CUSTOMER, resource_id, customer_xid)
        self.assertEqual(vault_xid, customer_xid)

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.APPLICATION, resource_id, customer_xid
        )
        self.assertEqual(vault_xid, 'ap_{}_{}'.format(resource_id, customer_xid))

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.GRAB_CUSTOMER_DATA, resource_id, customer_xid
        )
        self.assertEqual(vault_xid, 'gcd_{}_{}'.format(resource_id, customer_xid))

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.AUTH_USER, resource_id, customer_xid
        )
        self.assertEqual(vault_xid, 'au_{}_{}'.format(resource_id, customer_xid))

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.APPLICATION_ORIGINAL, resource_id, customer_xid
        )
        self.assertEqual(vault_xid, 'apo_{}_{}'.format(resource_id, customer_xid))

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.CUSTOMER_FIELD_CHANGE, resource_id, customer_xid
        )
        self.assertEqual(vault_xid, 'cfc_{}_{}'.format(resource_id, customer_xid))

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.AUTH_USER_FIELD_CHANGE, resource_id, customer_xid
        )
        self.assertEqual(vault_xid, 'aufc_{}_{}'.format(resource_id, customer_xid))

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.APPLICATION_FIELD_CHANGE, resource_id, customer_xid
        )
        self.assertEqual(vault_xid, 'apfc_{}_{}'.format(resource_id, customer_xid))

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.DANA_CUSTOMER_DATA, resource_id, customer_xid
        )
        self.assertEqual(vault_xid, 'dcd_{}_{}'.format(resource_id, customer_xid))

    def test_partnership_vault_xid_from_resource(self):
        vault_xid = partnership_vault_xid_from_resource(PiiSource.CUSTOMER, self.customer_1)
        self.assertEqual(vault_xid, str(self.customer_1.customer_xid))

        vault_xid = partnership_vault_xid_from_resource(PiiSource.APPLICATION, self.application_1)
        self.assertEqual(
            vault_xid, 'ap_{}_{}'.format(self.application_1.id, self.customer_1.customer_xid)
        )

        vault_xid = partnership_vault_xid_from_resource(
            PiiSource.GRAB_CUSTOMER_DATA, self.grab_customer_data_1
        )
        self.assertEqual(
            vault_xid,
            'gcd_{}_{}'.format(self.grab_customer_data_1.id, self.customer_1.customer_xid),
        )

        vault_xid = partnership_vault_xid_from_resource(PiiSource.AUTH_USER, self.auth_user_1)
        self.assertEqual(
            vault_xid, 'au_{}_{}'.format(self.auth_user_1.id, self.customer_1.customer_xid)
        )

    def test_get_id_from_vault_xid(self):
        customer_xid = "123123432"
        resource_id = "13232"
        vault_xid = partnership_vault_xid_from_values(PiiSource.CUSTOMER, resource_id, customer_xid)
        customer_xid_return, resource_id_return = get_id_from_vault_xid(
            vault_xid, PiiSource.CUSTOMER
        )
        self.assertEqual(customer_xid_return, customer_xid)
        self.assertEqual(resource_id_return, None)

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.APPLICATION, resource_id, customer_xid
        )
        customer_xid_return, resource_id_return = get_id_from_vault_xid(
            vault_xid, PiiSource.APPLICATION
        )
        self.assertEqual(customer_xid_return, customer_xid)
        self.assertEqual(resource_id_return, resource_id)

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.GRAB_CUSTOMER_DATA, resource_id, customer_xid
        )
        customer_xid_return, resource_id_return = get_id_from_vault_xid(
            vault_xid, PiiSource.GRAB_CUSTOMER_DATA
        )
        self.assertEqual(customer_xid_return, customer_xid)
        self.assertEqual(resource_id_return, resource_id)

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.AUTH_USER, resource_id, customer_xid
        )
        customer_xid_return, resource_id_return = get_id_from_vault_xid(
            vault_xid, PiiSource.AUTH_USER
        )
        self.assertEqual(customer_xid_return, customer_xid)
        self.assertEqual(resource_id_return, resource_id)

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.APPLICATION_ORIGINAL, resource_id, customer_xid
        )
        customer_xid_return, resource_id_return = get_id_from_vault_xid(
            vault_xid, PiiSource.APPLICATION_ORIGINAL
        )
        self.assertEqual(customer_xid_return, customer_xid)
        self.assertEqual(resource_id_return, resource_id)

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.CUSTOMER_FIELD_CHANGE, resource_id, customer_xid
        )
        customer_xid_return, resource_id_return = get_id_from_vault_xid(
            vault_xid, PiiSource.CUSTOMER_FIELD_CHANGE
        )
        self.assertEqual(customer_xid_return, customer_xid)
        self.assertEqual(resource_id_return, resource_id)

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.AUTH_USER_FIELD_CHANGE, resource_id, customer_xid
        )
        customer_xid_return, resource_id_return = get_id_from_vault_xid(
            vault_xid, PiiSource.AUTH_USER_FIELD_CHANGE
        )
        self.assertEqual(customer_xid_return, customer_xid)
        self.assertEqual(resource_id_return, resource_id)

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.APPLICATION_FIELD_CHANGE, resource_id, customer_xid
        )
        customer_xid_return, resource_id_return = get_id_from_vault_xid(
            vault_xid, PiiSource.APPLICATION_FIELD_CHANGE
        )
        self.assertEqual(customer_xid_return, customer_xid)
        self.assertEqual(resource_id_return, resource_id)

        vault_xid = partnership_vault_xid_from_values(
            PiiSource.DANA_CUSTOMER_DATA, resource_id, customer_xid
        )
        customer_xid_return, resource_id_return = get_id_from_vault_xid(
            vault_xid, PiiSource.DANA_CUSTOMER_DATA
        )
        self.assertEqual(customer_xid_return, customer_xid)
        self.assertEqual(resource_id_return, resource_id)

    def test_partnership_pii_mapping_field(self):
        self.assertEqual('name', partnership_pii_mapping_field('fullname', PiiSource.CUSTOMER))
        self.assertEqual(
            'mobile_number', partnership_pii_mapping_field('phone', PiiSource.CUSTOMER)
        )
        self.assertEqual(
            'mobile_number',
            partnership_pii_mapping_field('phone_number', PiiSource.GRAB_CUSTOMER_DATA),
        )
        self.assertEqual('nik', partnership_pii_mapping_field('ktp', PiiSource.APPLICATION))
        self.assertEqual(
            'mobile_number', partnership_pii_mapping_field('mobile_phone_1', PiiSource.APPLICATION)
        )
        self.assertEqual('name', partnership_pii_mapping_field('fullname', PiiSource.APPLICATION))
        self.assertEqual(
            'name', partnership_pii_mapping_field('full_name', PiiSource.DANA_CUSTOMER_DATA)
        )

    def test_partnership_reverse_field_mapper(self):
        customer_data = {
            'name_tokenized': "some_name",
            'mobile_number_tokenized': '954542',
            'email_tokenized': "some_random_email",
            'nik_tokenized': "some_random_nik",
        }
        expected_customer_data = {
            'fullname_tokenized': "some_name",
            'phone_tokenized': '954542',
            'email_tokenized': "some_random_email",
            'nik_tokenized': "some_random_nik",
        }
        self.assertDictEqual(
            partnership_reverse_field_mapper(customer_data, PiiSource.CUSTOMER),
            expected_customer_data,
        )

        application_data = {
            'name_tokenized': "some_name",
            'mobile_number_tokenized': '954542',
            'email_tokenized': "some_random_email",
            'nik_tokenized': "some_random_nik",
        }
        expected_application_data = {
            'fullname_tokenized': "some_name",
            'mobile_phone_1_tokenized': '954542',
            'email_tokenized': "some_random_email",
            'ktp_tokenized': "some_random_nik",
        }
        self.assertDictEqual(
            partnership_reverse_field_mapper(application_data, PiiSource.APPLICATION),
            expected_application_data,
        )

        gcd_data = {'mobile_number_tokenized': "some_random_phone"}
        expected_gcd_data = {'phone_number_tokenized': "some_random_phone"}
        self.assertDictEqual(
            partnership_reverse_field_mapper(gcd_data, PiiSource.GRAB_CUSTOMER_DATA),
            expected_gcd_data,
        )

        gcd_data = {'name_tokenized': "some_random_name"}
        expected_gcd_data = {'full_name_tokenized': "some_random_name"}
        self.assertDictEqual(
            partnership_reverse_field_mapper(gcd_data, PiiSource.DANA_CUSTOMER_DATA),
            expected_gcd_data,
        )

    @patch('juloserver.pii_vault.partnership.tasks.pii_vault_client')
    def test_partnership_tokenize_pii_data_task_case_1(self, mocked_client):
        customer = CustomerFactory()
        customer.email = "something@gmail.com"
        customer.phone = "081321231231"
        customer.customer_xid = "1413121212"
        customer.email_tokenized = None
        customer.phone_tokenized = None
        customer.save()
        mocked_client.tokenize.return_value = [
            {
                'fields': {
                    'email': 'JULO:49e01463-dd7d-4333-aed9-2b1fc8c16813',
                    'mobile_number': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f93',
                    'vault_xid': str(customer.customer_xid),
                }
            }
        ]

        constructed_data = partnership_construct_pii_data(
            PiiSource.CUSTOMER, customer, fields=['email', 'phone']
        )
        partnership_tokenize_pii_data_task(constructed_data)
        customer.refresh_from_db()
        self.assertIsNotNone(customer.phone_tokenized)
        self.assertIsNotNone(customer.email_tokenized)
        self.assertIsNone(customer.fullname_tokenized)
        self.assertIsNone(customer.nik_tokenized)
        self.assertEqual(customer.phone_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f93')
        self.assertEqual(customer.email_tokenized, 'JULO:49e01463-dd7d-4333-aed9-2b1fc8c16813')

    @patch('juloserver.pii_vault.partnership.tasks.pii_vault_client')
    def test_partnership_tokenize_pii_data_task_case_2(self, mocked_client):
        customer = CustomerFactory()
        customer.email = "something@gmail.com"
        customer.phone = "081321231231"
        customer.fullname = "something"
        customer.nik = "343565632345643"
        customer.customer_xid = "1413121212"
        customer.email_tokenized = None
        customer.phone_tokenized = None
        customer.nik_tokenized = None
        customer.full_tokenized = None
        customer.save()
        mocked_client.tokenize.return_value = [
            {
                'fields': {
                    'email': 'JULO:49e01463-dd7d-4333-aed9-2b1fc8c16813',
                    'mobile_number': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f93',
                    'nik': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f95',
                    'name': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f94',
                    'vault_xid': str(customer.customer_xid),
                }
            }
        ]

        constructed_data = partnership_construct_pii_data(
            PiiSource.CUSTOMER, customer, fields=['email', 'phone', 'fullname', 'nik']
        )
        partnership_tokenize_pii_data_task(constructed_data)
        customer.refresh_from_db()
        self.assertIsNotNone(customer.phone_tokenized)
        self.assertIsNotNone(customer.email_tokenized)
        self.assertIsNotNone(customer.fullname_tokenized)
        self.assertIsNotNone(customer.nik_tokenized)
        self.assertEqual(customer.phone_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f93')
        self.assertEqual(customer.email_tokenized, 'JULO:49e01463-dd7d-4333-aed9-2b1fc8c16813')
        self.assertEqual(customer.fullname_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f94')
        self.assertEqual(customer.nik_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f95')

    @patch('juloserver.pii_vault.partnership.tasks.pii_vault_client')
    def test_partnership_tokenize_pii_data_task_case_2(self, mocked_client):
        customer = CustomerFactory()
        customer.customer_xid = "2543234564"
        customer.save()
        application = ApplicationFactory()
        application.email = "something@gmail.com"
        application.mobile_phone_1 = "081321231231"
        application.fullname = "something"
        application.ktp = "343565632345643"
        application.email_tokenized = None
        application.mobile_phone_1_tokenized = None
        application.ktp_tokenized = None
        application.fullname_tokenized = None
        customer.save()
        mocked_client.tokenize.return_value = [
            {
                'fields': {
                    'email': 'JULO:49e01463-dd7d-4333-aed9-2b1fc8c16813',
                    'mobile_number': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f93',
                    'nik': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f95',
                    'name': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f94',
                    'vault_xid': get_vault_xid_from_resource(PiiSource.APPLICATION, application),
                }
            }
        ]

        constructed_data = partnership_construct_pii_data(
            PiiSource.APPLICATION,
            application,
            fields=['email', 'mobile_phone_1', 'fullname', 'ktp'],
        )
        partnership_tokenize_pii_data_task(constructed_data)
        application.refresh_from_db()
        self.assertIsNotNone(application.mobile_phone_1_tokenized)
        self.assertIsNotNone(application.email_tokenized)
        self.assertIsNotNone(application.fullname_tokenized)
        self.assertIsNotNone(application.ktp_tokenized)
        self.assertEqual(
            application.mobile_phone_1_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f93'
        )
        self.assertEqual(application.email_tokenized, 'JULO:49e01463-dd7d-4333-aed9-2b1fc8c16813')
        self.assertEqual(
            application.fullname_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f94'
        )
        self.assertEqual(application.ktp_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f95')

    @patch('juloserver.pii_vault.partnership.tasks.pii_vault_client')
    def test_partnership_tokenize_pii_data_task_case_3(self, mocked_client):
        customer = CustomerFactory()
        customer.customer_xid = "2543234564"
        customer.save()
        application = ApplicationFactory()
        application.email = "something@gmail.com"
        application.mobile_phone_1 = "081321231231"
        application.fullname = "something"
        application.ktp = "343565632345643"
        application.email_tokenized = None
        application.mobile_phone_1_tokenized = None
        application.ktp_tokenized = None
        application.fullname_tokenized = None
        customer.save()
        mocked_client.tokenize.return_value = [
            {
                'fields': {
                    'email': 'JULO:49e01463-dd7d-4333-aed9-2b1fc8c16813',
                    'mobile_number': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f93',
                    'nik': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f95',
                    'name': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f94',
                    'vault_xid': get_vault_xid_from_resource(PiiSource.APPLICATION, application),
                }
            },
            {
                'fields': {
                    'email': 'JULO:49e01463-dd7d-4333-aed9-2b1fc8c16818',
                    'mobile_number': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f90',
                    'nik': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f98',
                    'name': 'JULO:646448d0-dbca-43db-abe1-bcec558e9f97',
                    'vault_xid': get_vault_xid_from_resource(PiiSource.CUSTOMER, customer),
                }
            },
        ]
        constructed_data = partnership_construct_pii_data(
            PiiSource.CUSTOMER, customer, fields=['email', 'phone', 'fullname', 'nik']
        )
        constructed_data = partnership_construct_pii_data(
            PiiSource.APPLICATION,
            application,
            fields=['email', 'mobile_phone_1', 'fullname', 'ktp'],
            constructed_data=constructed_data,
        )
        partnership_tokenize_pii_data_task(constructed_data)
        application.refresh_from_db()
        self.assertIsNotNone(application.mobile_phone_1_tokenized)
        self.assertIsNotNone(application.email_tokenized)
        self.assertIsNotNone(application.fullname_tokenized)
        self.assertIsNotNone(application.ktp_tokenized)
        self.assertEqual(
            application.mobile_phone_1_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f93'
        )
        self.assertEqual(application.email_tokenized, 'JULO:49e01463-dd7d-4333-aed9-2b1fc8c16813')
        self.assertEqual(
            application.fullname_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f94'
        )
        self.assertEqual(application.ktp_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f95')

        customer.refresh_from_db()
        self.assertIsNotNone(customer.phone_tokenized)
        self.assertIsNotNone(customer.email_tokenized)
        self.assertIsNotNone(customer.fullname_tokenized)
        self.assertIsNotNone(customer.nik_tokenized)
        self.assertEqual(customer.phone_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f90')
        self.assertEqual(customer.email_tokenized, 'JULO:49e01463-dd7d-4333-aed9-2b1fc8c16818')
        self.assertEqual(customer.fullname_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f97')
        self.assertEqual(customer.nik_tokenized, 'JULO:646448d0-dbca-43db-abe1-bcec558e9f98')


class TestGeneratePIIVaultEvent(TestCase):
    def setUp(self):
        pass

    def test_generate_pii_vault_event_and_refine_pii_data(self):
        customer_1 = CustomerFactory()
        customer_2 = CustomerFactory()
        result = generate_pii_vault_event_and_refine_pii_data(
            {
                'customer': [
                    {
                        'resource': customer_1,
                        'resource_id': customer_1.id,
                        'fields': ['fullname', 'phone', 'email'],
                    },
                    {
                        'resource': customer_2,
                        'resource_id': customer_2.id,
                        'fields': ['fullname', 'phone', 'email'],
                    }
                ]
            },
            bulk_create=True,
        )
        self.assertEqual(
            result,
            {
                'customer': [
                    {
                        'resource_id': customer_1.id,
                        'fields': ['fullname', 'phone', 'email'],
                        'pii_vault_event_id': ANY,
                    },
                    {
                        'resource_id': customer_2.id,
                        'fields': ['fullname', 'phone', 'email'],
                        'pii_vault_event_id': ANY,
                    }
                ]
            },
        )
        self.assertNotEqual(
            result['customer'][0]['pii_vault_event_id'], result['customer'][1]['pii_vault_event_id']
        )


class TestPartnershipPiiEncryption(TestCase):
    def setUp(self):
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number='62823525113532', customer=None
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_TOKENIZATION, is_active=True
        )
        self.customer = CustomerFactory(customer_xid="1213214232")

    @patch('juloserver.pii_vault.services.execute_after_transaction_safely')
    def test_save_method_grab_customer_data(self, mocked_tokenize):
        mocked_tokenize.return_value = None
        self.grab_customer_data.save()
        mocked_tokenize.assert_not_called()

    @patch('juloserver.pii_vault.services.execute_after_transaction_safely')
    def test_tokenize_pii_data_grab_customer_data_no_customer_feature_off(
        self, mocked_pii_tokenize
    ):
        mocked_pii_tokenize.return_value = None
        self.grab_customer_data.customer = None
        self.feature_setting.is_active = False
        self.feature_setting.save()
        self.grab_customer_data.save()
        self.assertIsNone(self.grab_customer_data.phone_number_tokenized)
        mocked_pii_tokenize.assert_not_called()

    @patch('juloserver.pii_vault.services.execute_after_transaction_safely')
    def test_tokenize_pii_data_grab_customer_data_customer_feature_off(self, mocked_pii_tokenize):
        mocked_pii_tokenize.return_value = None
        self.grab_customer_data.customer = self.customer
        self.feature_setting.is_active = False
        self.feature_setting.save()
        self.grab_customer_data.save()
        self.assertIsNone(self.grab_customer_data.phone_number_tokenized)
        mocked_pii_tokenize.assert_not_called()

    @patch('juloserver.pii_vault.services.execute_after_transaction_safely')
    def test_tokenize_pii_data_grab_customer_data_no_customer_feature_on(self, mocked_pii_tokenize):
        mocked_pii_tokenize.return_value = None
        self.grab_customer_data.customer = None
        self.feature_setting.is_active = True
        self.feature_setting.save()
        self.grab_customer_data.save()
        self.assertIsNone(self.grab_customer_data.phone_number_tokenized)
        mocked_pii_tokenize.assert_not_called()

    @patch('juloserver.pii_vault.services.execute_after_transaction_safely')
    def test_tokenize_pii_data_grab_customer_data_customer_feature_on(self, mocked_pii_tokenize):
        mocked_pii_tokenize.return_value = None
        self.grab_customer_data.customer = self.customer
        self.feature_setting.is_active = True
        self.feature_setting.save()
        self.grab_customer_data.save()
        mocked_pii_tokenize.assert_called()

    def test_is_data_to_be_tokenization_grab_customer_data_no_customer(self):
        self.grab_customer_data.customer = None
        self.grab_customer_data.save()
        flag = is_data_to_be_tokenization(
            self.grab_customer_data.__class__, self.grab_customer_data
        )
        self.assertFalse(flag)

    def test_is_data_to_be_tokenization_grab_customer_data_customer(self):
        self.grab_customer_data.customer = self.customer
        self.grab_customer_data.save()
        flag = is_data_to_be_tokenization(
            self.grab_customer_data.__class__, self.grab_customer_data
        )
        self.assertTrue(flag)

    def test_is_data_to_be_tokenization_customer(self):
        flag = is_data_to_be_tokenization(self.customer.__class__, self.customer)
        self.assertTrue(flag)

    def test_get_pii_data_from_save_grab_customer_data_update_fields(self):
        self.grab_customer_data.customer = self.customer
        self.grab_customer_data.save()
        pii_data = get_pii_data_from_save_resource(
            self.grab_customer_data.__class__,
            self.grab_customer_data,
            is_created=False,
            update_fields=['phone_number'],
        )
        self.assertDictEqual(
            {
                self.grab_customer_data.__class__.__name__.lower(): [
                    {
                        'fields': ['phone_number'],
                        'pii_type': 'cust',
                        'resource': self.grab_customer_data,
                        'resource_id': self.grab_customer_data.id,
                    }
                ]
            },
            pii_data,
        )

    def test_get_pii_data_from_save_grab_customer_data_no_update_fields(self):
        self.grab_customer_data.customer = self.customer
        self.grab_customer_data.save()
        pii_data = get_pii_data_from_save_resource(
            self.grab_customer_data.__class__,
            self.grab_customer_data,
            is_created=False,
            update_fields=None,
        )
        self.assertDictEqual(
            {
                self.grab_customer_data.__class__.__name__.lower(): [
                    {
                        'fields': ['phone_number'],
                        'pii_type': 'cust',
                        'resource': self.grab_customer_data,
                        'resource_id': self.grab_customer_data.id,
                    }
                ]
            },
            pii_data,
        )

    def test_get_pii_data_from_save_grab_customer_data_creation(self):
        self.grab_customer_data.customer = self.customer
        self.grab_customer_data.save()
        pii_data = get_pii_data_from_save_resource(
            self.grab_customer_data.__class__,
            self.grab_customer_data,
            is_created=True,
            update_fields=None,
        )
        self.assertDictEqual(
            {
                self.grab_customer_data.__class__.__name__.lower(): [
                    {
                        'fields': ['phone_number'],
                        'pii_type': 'cust',
                        'resource': self.grab_customer_data,
                        'resource_id': self.grab_customer_data.id,
                    }
                ]
            },
            pii_data,
        )

    def test_get_pii_data_from_save_grab_customer_data_other_update_fields(self):
        self.grab_customer_data.customer = self.customer
        self.grab_customer_data.save()
        pii_data = get_pii_data_from_save_resource(
            self.grab_customer_data.__class__,
            self.grab_customer_data,
            is_created=False,
            update_fields=['otp_status'],
        )
        self.assertIsNone(pii_data)

    @patch('juloserver.pii_vault.services.pii_vault_client')
    def test_tokenize_data_grab_customer_data_success_creation(self, mocked_pii_client):
        self.grab_customer_data.customer = self.customer
        self.grab_customer_data.save()
        self.grab_customer_data.phone_number_tokenized = None
        self.grab_customer_data.save(update_fields=['phone_number_tokenized'])
        self.assertIsNone(self.grab_customer_data.phone_number_tokenized)
        pii_data = get_pii_data_from_save_resource(
            self.grab_customer_data.__class__,
            self.grab_customer_data,
            is_created=True,
            update_fields=None,
        )
        pii_data = prepare_pii_event(pii_data, False)
        mocked_pii_client.tokenize.return_value = [{'fields': {'mobile_number': '<PHONE>'}}]
        tokenize_pii_data(pii_data, run_async=False)
        self.grab_customer_data.refresh_from_db()
        self.assertEqual(self.grab_customer_data.phone_number_tokenized, '<PHONE>')

    @patch('juloserver.pii_vault.services.tokenize_data_task.delay')
    def test_trigger_tokenize_data_grab_customer_data_success_save(self, mocked_tokenize):
        self.grab_customer_data.customer = self.customer
        self.grab_customer_data.save()
        self.grab_customer_data.phone_number_tokenized = None
        self.grab_customer_data.save(update_fields=['phone_number_tokenized'])
        self.assertIsNone(self.grab_customer_data.phone_number_tokenized)
        mocked_tokenize.return_value = None
        self.grab_customer_data.save()
        mocked_tokenize.assert_called()

    @patch('juloserver.pii_vault.services.execute_after_transaction_safely')
    def test_trigger_tokenize_data_grab_customer_data_success_save(self, mocked_tokenize):
        self.grab_customer_data.customer = self.customer
        self.grab_customer_data.save()
        self.grab_customer_data.phone_number_tokenized = None
        self.grab_customer_data.save(update_fields=['phone_number_tokenized'])
        self.assertIsNone(self.grab_customer_data.phone_number_tokenized)
        mocked_tokenize.return_value = None
        self.grab_customer_data.save()
        mocked_tokenize.assert_called()

    def test_clear_fields_vault_model_grab_customer_data_update_fields(self):
        obj = GrabCustomerData()
        setattr(obj, 'phone_number_tokenized', 'tokenized_data')
        self.assertEqual(obj.phone_number_tokenized, 'tokenized_data')
        obj.clear_tokenized_pii_field(obj.__class__, ['phone_number'])
        self.assertIsNone(obj.phone_number_tokenized)

    def test_clear_fields_vault_model_grab_customer_data_non_update_fields(self):
        obj = GrabCustomerData()
        setattr(obj, 'phone_number_tokenized', 'tokenized_data')
        obj.clear_tokenized_pii_field(obj.__class__, ['phone_number'])
        self.assertIsNone(obj.phone_number_tokenized)

    def test_clear_fields_vault_model_customer_update_fields(self):
        obj = Customer()
        setattr(obj, 'phone_tokenized', 'token_phone')
        setattr(obj, 'nik_tokenized', 'token_nik')
        setattr(obj, 'email_tokenized', 'token_email')
        setattr(obj, 'fullname_tokenized', 'token_name')
        self.assertEqual(obj.phone_tokenized, 'token_phone')
        self.assertEqual(obj.nik_tokenized, 'token_nik')
        self.assertEqual(obj.email_tokenized, 'token_email')
        self.assertEqual(obj.fullname_tokenized, 'token_name')
        obj.clear_tokenized_pii_field(obj.__class__, ['nik'])
        self.assertEqual(obj.phone_tokenized, 'token_phone')
        self.assertEqual(obj.nik_tokenized, None)
        self.assertEqual(obj.email_tokenized, 'token_email')
        self.assertEqual(obj.fullname_tokenized, 'token_name')

    def test_clear_fields_vault_model_customer_non_update_fields(self):
        obj = Customer()
        setattr(obj, 'phone_tokenized', 'token_phone')
        setattr(obj, 'nik_tokenized', 'token_nik')
        setattr(obj, 'email_tokenized', 'token_email')
        setattr(obj, 'fullname_tokenized', 'token_name')
        self.assertEqual(obj.phone_tokenized, 'token_phone')
        self.assertEqual(obj.nik_tokenized, 'token_nik')
        self.assertEqual(obj.email_tokenized, 'token_email')
        self.assertEqual(obj.fullname_tokenized, 'token_name')
        obj.clear_tokenized_pii_field(obj.__class__, None)
        self.assertEqual(obj.phone_tokenized, None)
        self.assertEqual(obj.nik_tokenized, None)
        self.assertEqual(obj.email_tokenized, None)
        self.assertEqual(obj.fullname_tokenized, None)

    @mock.patch('juloserver.pii_vault.services.get_pii_data_from_update_resources')
    def test_clear_fields_vault_model_queryset_update(self, mocked_get_resource):
        customer_ids = []
        for i in list(range(10)):
            customer = CustomerFactory()
            customer.phone_tokenized = "SomeRandomToken"
            customer.save(update_fields=['phone_tokenized'])
            customer_ids.append(customer.id)
        mocked_get_resource.return_value = None
        customer_set = Customer.objects.filter(id__in=customer_ids)
        for customer in customer_set.iterator():
            self.assertEqual(customer.phone_tokenized, "SomeRandomToken")
        customer_set.update(phone="628123124343")
        customer_set = Customer.objects.filter(id__in=customer_ids)
        for customer in customer_set.iterator():
            self.assertEqual(customer.phone_tokenized, None)

    @mock.patch('juloserver.pii_vault.services.get_pii_data_from_update_resources')
    def test_clear_fields_vault_model_queryset_update_one_field(self, mocked_get_resource):
        customer_ids = []
        for i in list(range(10)):
            customer = CustomerFactory()
            customer.phone_tokenized = "SomeRandomTokenPhone"
            customer.email_tokenized = "SomeRandomTokenEmail"
            customer.nik_tokenized = "SomeRandomTokenNik"
            customer.save(update_fields=['phone_tokenized', 'email_tokenized', 'nik_tokenized'])
            customer_ids.append(customer.id)
        mocked_get_resource.return_value = None
        customer_set = Customer.objects.filter(id__in=customer_ids)
        for customer in customer_set.iterator():
            self.assertEqual(customer.phone_tokenized, "SomeRandomTokenPhone")
            self.assertEqual(customer.email_tokenized, "SomeRandomTokenEmail")
            self.assertEqual(customer.nik_tokenized, "SomeRandomTokenNik")
        customer_set.update(phone="628123124343")
        customer_set = Customer.objects.filter(id__in=customer_ids)
        for customer in customer_set.iterator():
            self.assertEqual(customer.phone_tokenized, None)
            self.assertEqual(customer.email_tokenized, "SomeRandomTokenEmail")
            self.assertEqual(customer.nik_tokenized, "SomeRandomTokenNik")

    @mock.patch('juloserver.pii_vault.services.send_pii_vault_events')
    def test_update_for_empty_grab_customer_data(self, mocked_pii_send):
        gcd_ids = []
        for i in list(range(10)):
            gcd = GrabCustomerDataFactory(customer=None)
            gcd_ids.append(gcd.id)
        mocked_pii_send.return_value = None
        gcd_set = GrabCustomerData.objects.filter(id__in=gcd_ids)
        gcd_set.update(phone_number='628423423433')
        gcd_set = GrabCustomerData.objects.filter(id__in=gcd_ids)
        mocked_pii_send.assert_not_called()

    # @mock.patch('juloserver.pii_vault.services.send_pii_vault_events')
    # def test_update_for_not_empty_grab_customer_data(self, mocked_pii_send):
    #     gcd_ids = []
    #     for i in list(range(10)):
    #         customer = CustomerFactory()
    #         gcd = GrabCustomerDataFactory(customer=customer)
    #         gcd_ids.append(gcd.id)
    #     mocked_pii_send.return_value = None
    #     gcd_set = GrabCustomerData.objects.filter(id__in=gcd_ids)
    #     gcd_set.update(phone_number='628423423433')
    #     gcd_set = GrabCustomerData.objects.filter(id__in=gcd_ids)
    #     mock_dict = {'resource': mock.ANY, 'resource_id': mock.ANY, 'fields': ['phone_number']}
    #     mocked_data = [mock_dict.copy() for i in list(range(10))]
    #     mocked_pii_send.assert_called_with({'grabcustomerdata': mocked_data}, bulk_create=True)


class TestDetokenize(TestCase):
    def setUp(self):
        self.customer_data = dict(
            user=AuthUserFactory(),
            fullname='testerdetoknized',
            email='tester_detokenzied@testspeed.com',
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
            gender='Pria',
        )
        self.customer = Customer.objects.create(**self.customer_data)
        self.customer.update_safely(
            fullname_tokenized='3e366f17-ab3e-48bc-9e46-d9ac51cb75da',
            email_tokenized='3e366f17-ab3e-48bc-9e46-d9ac51cb75da',
            phone_tokenized='3e366f17-ab3e-48bc-9e46-d9ac51cb75da',
        )
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.ONBOARDING_PII_VAULT_DETOKENIZATION,
            is_active=True,
            parameters={'cache_data': False, 'validate_data': True},
        )
        self.application = ApplicationFactory(customer=self.customer)
        self.application.update_safely(
            fullname_tokenized='3e366f17-ab3e-48bc-9e46-d9ac51cb75da',
            email_tokenized='3e366f17-ab3e-48bc-9e46-d9ac51cb75db',
            mobile_phone_1_tokenized='3e366f17-ab3e-48bc-9e46-d9ac51cb75dc',
        )

    @patch('juloserver.pii_vault.services.sentry_client')
    @patch('juloserver.pii_vault.services.detokenize_pii_data_by_client')
    def test_get_with_object_resource_type(
        self, mock_detokenize_pii_data_by_client, mock_sentry_client
    ):

        mock_detokenize_pii_data_by_client.return_value = {
            'fullname': self.application.fullname,
            'email': self.application.email,
            'mobile_phone_1': self.application.mobile_phone_1,
        }
        # resource is an object
        result = detokenize_pii_data(
            PiiSource.APPLICATION,
            DetokenizeResourceType.OBJECT,
            [
                {
                    'customer_xid': self.application.customer.customer_xid,
                    'object': self.application,
                }
            ],
            fields=None,
            get_all=True,
            run_async=False,
        )
        mock_sentry_client.captureException.assert_not_called()

        # resource is id
        result = detokenize_pii_data(
            PiiSource.APPLICATION,
            DetokenizeResourceType.OBJECT,
            [
                {
                    'customer_xid': self.application.customer.customer_xid,
                    'id': self.application.id,
                }
            ],
            fields=None,
            get_all=True,
            run_async=False,
        )
        mock_sentry_client.captureException.assert_not_called()

        # validate data failed
        mock_detokenize_pii_data_by_client.return_value = {
            'fullname': self.application.fullname,
            'email': self.application.email,
            'mobile_phone_1': 'fakenumber',
        }
        result = detokenize_pii_data(
            PiiSource.APPLICATION,
            DetokenizeResourceType.OBJECT,
            [
                {
                    'customer_xid': self.application.customer.customer_xid,
                    'object': self.application,
                }
            ],
            fields=None,
            get_all=True,
            run_async=False,
        )
        mock_sentry_client.captureException.assert_called()

    @patch('juloserver.pii_vault.services.sentry_client')
    @patch('juloserver.pii_vault.services.detokenize_pii_data_by_client')
    def test_get_with_dict_resource_type(
        self, mock_detokenize_pii_data_by_client, mock_sentry_client
    ):

        mock_detokenize_pii_data_by_client.return_value = {
            'fullname': self.application.fullname,
            'email': self.application.email,
            'mobile_phone_1': self.application.mobile_phone_1,
        }
        tokenized_data = {
            'fullname_tokenized': self.application.fullname_tokenized,
            'email_tokenized': self.application.email_tokenized,
            'mobile_phone_1_tokenized': self.application.mobile_phone_1_tokenized,
            'customer_xid': self.application.customer.customer_xid,
            'id': self.application.id,
        }

        # resource is an object
        result = detokenize_pii_data(
            PiiSource.APPLICATION,
            DetokenizeResourceType.DICT,
            [tokenized_data],
            fields=None,
            get_all=True,
            run_async=False,
        )
        mock_sentry_client.captureException.assert_not_called()

        # validate data failed
        mock_detokenize_pii_data_by_client.return_value = {
            'fullname': self.application.fullname,
            'email': self.application.email,
            'mobile_phone_1': 'fakenumber',
        }
        result = detokenize_pii_data(
            PiiSource.APPLICATION,
            DetokenizeResourceType.DICT,
            [tokenized_data],
            fields=None,
            get_all=True,
            run_async=False,
        )
        mock_sentry_client.captureException.assert_called()

    @patch('juloserver.pii_vault.services.pii_vault_client')
    def test_detokenize_pii_data_by_client(self, mock_pii_vault_client):
        payload = [
            {
                'token': self.application.fullname_tokenized,
                'vault_xid': self.application.customer.customer_xid,
            }
        ]
        back_map_keys = {
            self.application.fullname_tokenized: 'fullname',
            self.application.email_tokenized: 'email',
            self.application.mobile_phone_1_tokenized: 'mobile_phone_1',
        }
        feature_setting_params = {'request_timeout': 1, 'retry': 3}
        mock_pii_vault_client.detokenize.side_effect = (
            Exception('timeout'),
            [
                {
                    'token': self.application.fullname_tokenized,
                    'value': self.application.fullname,
                },
                {
                    'token': self.application.email_tokenized,
                    'value': self.application.email,
                },
                {
                    'token': self.application.mobile_phone_1_tokenized,
                    'value': 'fakenumber',
                },
            ],
        )
        rs = detokenize_pii_data_by_client(
            payload, back_map_keys, feature_setting_params, Application
        )
        self.assertEqual(len(rs), 3)

        mock_pii_vault_client.detokenize.side_effect = Exception()
        feature_setting_params['retry'] = 2
        rs = detokenize_pii_data_by_client(
            payload, back_map_keys, feature_setting_params, Application
        )
        self.assertEqual(len(rs), 0)

    @patch('juloserver.pii_vault.services.sentry_client')
    @patch('juloserver.pii_vault.services.detokenize_pii_data_by_client')
    def test_detokenize_for_model_object(
        self, mock_detokenize_pii_data_by_client, mock_sentry_client
    ):
        mock_detokenize_data = {
            'fullname': self.application.fullname,
            'email': self.application.email,
            'mobile_phone_1': 'fakenumber1',
        }
        mock_detokenize_pii_data_by_client.return_value = mock_detokenize_data
        tokenized_data = {
            'customer_xid': self.application.customer.customer_xid,
            'object': self.application,
        }
        original_application = copy.deepcopy(self.application)

        # force get local data
        result = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [tokenized_data],
            force_get_local_data=True,
        )
        mock_sentry_client.captureException.assert_not_called()
        self.assertEqual(self.application.fullname, mock_detokenize_data['fullname'])
        self.assertEqual(self.application.email, mock_detokenize_data['email'])
        self.assertEqual(self.application.mobile_phone_1, original_application.mobile_phone_1)

        # get data from pii vault client
        result = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [tokenized_data],
            force_get_local_data=False,
        )
        mock_sentry_client.captureException.assert_called()
        self.assertEqual(self.application.fullname, mock_detokenize_data['fullname'])
        self.assertEqual(self.application.email, mock_detokenize_data['email'])
        self.assertEqual(self.application.mobile_phone_1, mock_detokenize_data['mobile_phone_1'])
