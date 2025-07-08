import datetime
import time
from unittest.mock import patch, ANY

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from mock import MagicMock

from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.graduation.constants import CustomerSuspendType
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CustomerFactory,
    DeviceFactory,
    LoanFactory,
    PartnerFactory,
    StatusLookupFactory,
)
from juloserver.julo_financing.services.token_related import (
    JFinancingToken,
    get_or_create_customer_token,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.moengage.constants import MoengageEventType
from juloserver.moengage.services.data_constructors import (
    construct_application_status_change_event_data_for_j1_customer,
    construct_base_data_for_application_status_change,
    construct_data_for_loan_status_change_j1_event,
    construct_data_for_referral_event,
    construct_julo_financing_event_data,
    construct_moengage_event_data,
    construct_qris_linkage_status_change_event_data,
    construct_user_attributes_application_level,
    construct_data_for_cashback_freeze_unfreeze,
    construct_user_attributes_for_graduation_downgrade,
    construct_user_attributes_for_customer_suspended_unsuspended,
)
from juloserver.payment_point.models import TransactionMethod
from juloserver.qris.constants import AmarRejection, QrisLinkageStatus
from juloserver.qris.tests.factories import (
    QrisPartnerLinkageFactory,
)


class TestConstructUserAttributesApplicationLevel(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.device = DeviceFactory()
        self.application = ApplicationJ1Factory(
            customer=self.customer,
            device=self.device,
            app_version='8.0.0',
        )

    def test_construct_user_attributes_application_level_j1_x190(self):
        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 1, 12, 0, 0)
        ):
            result = construct_user_attributes_application_level(self.customer)
            expected_result = {'application_id': self.application.id,
                               'application_status_code': 190,
                               'product_type': 'J1',
                               'is_fdc_risky': False,
                               'monthly_income': 4000000,
                               'loan_purpose': 'PENDIDIKAN',
                               'application_count': 1,
                               'job_type': 'Pegawai swasta',
                               'job_industry': 'Admin / Finance / HR',
                               'score': '',
                               'is_j1_customer': True,
                               'mobile_phone_1': '6281218926858',
                               'mobile': '6281218926858',
                               'age': 25,
                               'date_of_birth': '1996-10-03T00:00:00.000000Z',
                               'city': 'Bogor',
                               'address_provinsi': 'Gorontalo',
                               'partner_name': '',
                               'is_entry_level': False,
                               'is_deleted': False,
                               'app_version': '8.0.0'}

        self.assertDictEqual(result, expected_result)

    def test_construct_user_attributes_application_level_has_no_application(self):
        self.application.delete()

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 1, 12, 0, 0)
        ):
            result = construct_user_attributes_application_level(self.customer)

        self.assertEqual(result, {})

    def test_construct_user_attributes_application_level_has_app_version(self):
        expected_result = {
            'application_id': self.application.id,
            'application_count': 1,
            'score': '',
            'is_j1_customer': True,
            'app_version': '8.0.0',
            'is_entry_level': False
        }

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 1, 12, 0, 0)
        ):
            result = construct_user_attributes_application_level(self.customer, 'app_version')

        self.assertEqual(expected_result, result)


class TestConstructDataApplicationChange(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()

    def test_construct_application_status_change_event_data_for_j1_customer(self):
        with patch.object(time, 'time') as mock_time:
            mock_time.return_value = 1622745600.0
            event_data = construct_application_status_change_event_data_for_j1_customer(
                'custom-event',
                self.application.id,
                {'event': 'attributes'},
            )

        expected_event_data = {
            "type": "event",
            "customer_id": self.application.customer_id,
            "device_id": self.application.device.gcm_reg_id,
            "actions": [{
                "action": 'custom-event',
                "attributes": {'event': 'attributes'},
                "platform": "ANDROID",
                "current_time": 1622745600.0,
                "user_timezone_offset": 25200,
            }]
        }
        self.assertEqual(expected_event_data, event_data)

    @patch('juloserver.moengage.services.data_constructors.construct_user_attributes_for_j1_customer')
    def test_construct_base_data_for_application_status_change(
        self,
        mock_construct_user_attributes,
    ):
        mock_construct_user_attributes.return_value = {'user': 'attributes'}
        with patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime.datetime(2021, 6, 4, 12, 0, 0)
            user_data, event_data = construct_base_data_for_application_status_change(
                self.application.id,
            )

        expected_event_data = {
            "customer_id": self.application.customer.id,
            "partner_name": '',
            "application_id": self.application.id,
            "cdate": None,
            "event_triggered_date": '2021-06-04 12:00:00',
            "product_type": 'J1',
        }
        self.assertEqual(expected_event_data, event_data)
        self.assertEqual({'user': 'attributes'}, user_data)


class TestConstructDataLoanStatusChange(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
        self.transaction_method = TransactionMethod.objects.last()
        self.loan = LoanFactory(
            account=self.application.account,
            customer=self.application.customer,
            loan_status=StatusLookupFactory(status_code=220),
            loan_amount=1234567,
            transaction_method=self.transaction_method
        )

    @patch('juloserver.moengage.services.data_constructors.construct_user_attributes_for_j1_customer')
    def test_construct_data_for_loan_status_change_j1_event(
        self,
        mock_construct_user_attributes,
    ):
        mock_construct_user_attributes.return_value = {'user': 'attributes'}

        with patch.object(timezone, 'now') as mock_now:
            with patch.object(time, 'time') as mock_time:
                mock_now.return_value = datetime.datetime(2021, 6, 4, 12, 0, 0)
                mock_time.return_value = 1622745600.0
                user_data, event_data = construct_data_for_loan_status_change_j1_event(
                    self.loan,
                    'custom-event',
                )

        expected_event_data = {
            "type": "event",
            "customer_id": self.application.customer_id,
            "device_id": self.application.device.gcm_reg_id,
            "actions": [{
                "action": 'custom-event',
                "attributes": {
                    "customer_id": self.application.customer_id,
                    "event_triggered_date": "2021-06-04 12:00:00",
                    "transaction_method": self.transaction_method.fe_display_name,
                    "loan_amount": 1234567,
                    "account_id": self.application.account_id,
                    "loan_id": self.loan.id,
                    "cdate": datetime.datetime.strftime(self.loan.udate, "%Y-%m-%dT%H:%M:%S.%fZ"),
                    'application_product_type': 'J1',
                },
                "platform": "ANDROID",
                "current_time": 1622745600.0,
                "user_timezone_offset": 25200,
            }]
        }
        self.assertEqual(expected_event_data, event_data)
        self.assertEqual({'user': 'attributes'}, user_data)


class TestConstructDataForReferralEvent(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(self_referral_code='ABCD1234')
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(
            customer=self.customer,
            account=self.account,
            device=None,
        )

    def test_construct_referral_event(self):
        with patch.object(time, 'time') as mock_time:
            mock_time.return_value = 1622745600.0
            event_data = construct_data_for_referral_event(
                self.customer, MoengageEventType.BEx190_NOT_YET_REFER, 10000,
            )

        expected_event_data = {
            "type": "event",
            "customer_id": self.application.customer_id,
            "device_id": '',
            "actions": [{
                "action": MoengageEventType.BEx190_NOT_YET_REFER,
                "attributes": {
                    "loan_id": '',
                    "account_id": self.application.account_id,
                    "self_referral_code": self.customer.self_referral_code,
                    "cdate_at_130": None,
                    "customer_referred_id": self.customer.id,
                    "referred_cashback_earned": 10000,
                    "product_type": "J1"
                },
                "platform": "ANDROID",
                "current_time": 1622745600.0,
                "user_timezone_offset": 25200,
            }]
        }
        self.assertEqual(expected_event_data, event_data)


class TestConstructUserAttributesForGraduation(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(
            customer=self.customer, account=self.account
        )
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=2000000)

    @patch('juloserver.moengage.services.data_constructors.timezone')
    def test_construct_user_attributes_for_graduation(self, mock_timezone):
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2022, month=10, day=20, hour=15, minute=0, second=0, microsecond=0
        )
        mock_timezone.localtime.return_value = mock_now
        user_attributes, event_data = construct_user_attributes_for_graduation_downgrade(
            self.customer, self.account, 2370000, self.account_limit.set_limit,
            MoengageEventType.GRADUATION, graduation_date=mock_now
        )

        self.assertIsNotNone(user_attributes)
        self.assertIsNotNone(event_data)
        self.assertEqual(user_attributes['customer_id'], self.customer.id)
        self.assertEqual(event_data['customer_id'], self.customer.id)
        self.assertEqual(
            event_data['actions'][0]['attributes']['old_set_limit'], "2 Juta"
        )
        self.assertEqual(
            event_data['actions'][0]['attributes']['new_set_limit'], "2.3 Juta"
        )
        self.assertEqual(
            event_data['actions'][0]['attributes']['additional_limit'], "370 Ribu"
        )
        self.assertEqual(
            event_data['actions'][0]['attributes']['graduated_date'],
            "2022-10-20T08:00:00+00:00"
        )

        self.assertEqual(
            user_attributes['attributes']['old_set_limit'], "2 Juta"
        )
        self.assertEqual(
            user_attributes['attributes']['new_set_limit'], "2.3 Juta"
        )
        self.assertEqual(
            user_attributes['attributes']['additional_limit'], "370 Ribu"
        )
        self.assertEqual(
            user_attributes['attributes']['graduated_date'],
            "2022-10-20T08:00:00+00:00"
        )

    def test_construct_user_attributes_for_downgrade(self):
        user_attributes, event_data = construct_user_attributes_for_graduation_downgrade(
            self.customer, self.account, 1630000, self.account_limit.set_limit,
            MoengageEventType.DOWNGRADE, 'FTC Repeat'
        )

        self.assertIsNotNone(user_attributes)
        self.assertIsNotNone(event_data)
        self.assertEqual(user_attributes['customer_id'], self.customer.id)
        self.assertEqual(event_data['customer_id'], self.customer.id)
        self.assertEqual(
            event_data['actions'][0]['attributes']['new_set_limit'], "1.6 Juta"
        )
        self.assertEqual(
            event_data['actions'][0]['attributes']['downgrade_limit'], "370 Ribu"
        )
        self.assertEqual(
            event_data['actions'][0]['attributes']['graduation_flow'], "FTC Repeat"
        )

        self.assertEqual(
            user_attributes['attributes']['new_set_limit'], "1.6 Juta"
        )
        self.assertEqual(
            user_attributes['attributes']['downgrade_limit'], "370 Ribu"
        )
        self.assertEqual(
            user_attributes['attributes']['graduation_flow'], "FTC Repeat"
        )


class TestConstructDataForCashbackFreezeUnfreeze(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)

    def test_construct_data(self):
        user_attributes, event_data = construct_data_for_cashback_freeze_unfreeze(
            self.customer, self.account, 'referrer', 'freeze', 150000
        )

        self.assertIsNotNone(user_attributes)
        self.assertIsNotNone(event_data)
        self.assertEqual(user_attributes['customer_id'], self.customer.id)
        self.assertEqual(event_data['customer_id'], self.customer.id)
        self.assertEqual(
            event_data['actions'][0]['attributes']['status'], 'freeze'
        )
        self.assertEqual(
            event_data['actions'][0]['attributes']['referral_type'], 'referrer'
        )
        self.assertEqual(
            event_data['actions'][0]['attributes']['cashback_earned'], '150 Ribu'
        )


class TestConstructUserAttributesForCustomerSuspendUnsuspend(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    def test_construct_user_attributes_for_customer_suspended(self):
        self.account = AccountFactory(customer=self.customer)

        reason = 'bad_clcs_delinquent_fdc'
        user_attributes, event_data = construct_user_attributes_for_customer_suspended_unsuspended(
            self.customer,
            self.account,
            MoengageEventType.CUSTOMER_SUSPENDED,
            True,
            reason
        )

        self.assertIsNotNone(user_attributes)
        self.assertIsNotNone(event_data)
        self.assertEqual(user_attributes['customer_id'], self.customer.id)
        self.assertEqual(user_attributes['attributes']['is_suspended'], True)
        self.assertEqual(event_data['customer_id'], self.customer.id)
        self.assertIsNotNone(event_data['actions'])

        actions = event_data['actions']
        self.assertEqual(actions[0]['action'], MoengageEventType.CUSTOMER_SUSPENDED)
        self.assertEqual(actions[0]['action'], MoengageEventType.CUSTOMER_SUSPENDED)
        self.assertEqual(actions[0]['attributes']['type'], CustomerSuspendType.SUSPENDED)
        self.assertEqual(actions[0]['attributes']['reason'], reason)

    def test_construct_user_attributes_for_customer_suspended_without_account(self):
        self.application = ApplicationJ1Factory(customer=self.customer, account=None)

        reason = 'bad_clcs_delinquent_fdc'
        user_attributes, event_data = construct_user_attributes_for_customer_suspended_unsuspended(
            self.customer,
            None,
            MoengageEventType.CUSTOMER_SUSPENDED,
            True,
            reason
        )

        self.assertIsNotNone(user_attributes)
        self.assertIsNotNone(event_data)
        self.assertEqual(user_attributes['customer_id'], self.customer.id)
        self.assertEqual(user_attributes['attributes']['is_suspended'], True)
        self.assertEqual(event_data['customer_id'], self.customer.id)
        self.assertIsNotNone(event_data['actions'])

        actions = event_data['actions']
        self.assertEqual(actions[0]['action'], MoengageEventType.CUSTOMER_SUSPENDED)
        self.assertEqual(actions[0]['action'], MoengageEventType.CUSTOMER_SUSPENDED)
        self.assertEqual(actions[0]['attributes']['type'], CustomerSuspendType.SUSPENDED)
        self.assertEqual(actions[0]['attributes']['reason'], reason)


class TestConstructMoengageEventData(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)
        self.device = DeviceFactory(customer=self.customer)

    @patch('juloserver.moengage.services.data_constructors.construct_data_moengage_event_data')
    def test_construct_moengage_event_data(self, mock_construct_data):
        gcm_req_id = "Eren Jaeger"
        self.device.gcm_reg_id = gcm_req_id
        self.device.save()

        self.application.device = self.device
        self.application.save()

        event_attributes = {'acttack': 'on titan'}
        event_type = "ill kill them all!"
        construct_moengage_event_data(
            event_type=event_type,
            event_attributes=event_attributes,
            customer_id=self.customer.id,
        )
        mock_construct_data.assert_called_once_with(
            device_id=gcm_req_id,
            customer_id=self.customer.id,
            event_type=event_type,
            event_attributes=event_attributes,
            event_time=ANY,
        )


class TestDataConstructorJuloFinancing(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)
        self.device = DeviceFactory(customer=self.customer)

        settings.J_FINANCING_SECRET_KEY_TOKEN = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        self.jfinancing_token = JFinancingToken().generate_token(self.customer.id)

    @patch("juloserver.julo_financing.services.token_related.get_redis_client")
    def test_construct_julo_financing_event_data(self, mock_get_redis_client):
        my_token = self.jfinancing_token
        mock_redis_client = MagicMock()

        mock_get_redis_client.return_value = mock_redis_client
        mock_redis_client.get.return_value = my_token

        # create j financing token
        token, token_data = get_or_create_customer_token(self.customer.id)

        self.assertEqual(token, my_token)

        user_attrs, event_data = construct_julo_financing_event_data(
            customer_id=self.customer.id,
            event_type=MoengageEventType.JULO_FINANCING,
        )

        self.assertIsNotNone(user_attrs)
        self.assertEqual(user_attrs['customer_id'], self.customer.id)
        self.assertEqual(user_attrs['attributes']['jfinancing_encrypted_key'], token)

        self.assertIsNotNone(event_data)
        self.assertEqual(event_data['customer_id'], self.customer.id)

        self.assertIsNotNone(event_data['actions'])
        actions = event_data['actions']
        self.assertEqual(actions[0]['action'], MoengageEventType.JULO_FINANCING)

        self.assertEqual(
            actions[0]['attributes']['key_event_time'],
            token_data.event_time_datetime.strftime('%Y-%m-%d, %H:%M:%S %z'),
        )
        self.assertEqual(
            actions[0]['attributes']['key_expiry_time'],
            token_data.expiry_time_datetime.strftime('%Y-%m-%d, %H:%M:%S %z'),
        )
        self.assertEqual(actions[0]['attributes']['jfinancing_encrypted_key'], token)


class TestConstructQrisLinkageStatusChange(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)
        self.partner = PartnerFactory(name='amar')
        self.linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            status=QrisLinkageStatus.REQUESTED,
        )

    def test_construct_qris_linkage_status_change_event_data_case_sucess(self):

        self.linkage.status = QrisLinkageStatus.SUCCESS
        self.linkage.save()

        result_attributes, event_data = construct_qris_linkage_status_change_event_data(
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            event_type=MoengageEventType.QRIS_LINKAGE_STATUS,
        )

        assert result_attributes['attributes']['customer_id'] == self.customer.id

        self.assertIsNotNone(event_data)
        self.assertEqual(event_data['customer_id'], self.customer.id)

        self.assertIsNotNone(event_data['actions'])
        actions = event_data['actions']
        self.assertEqual(actions[0]['action'], MoengageEventType.QRIS_LINKAGE_STATUS)

        self.assertEqual(
            actions[0]['attributes']['status'],
            QrisLinkageStatus.SUCCESS,
        )
        self.assertEqual(
            actions[0]['attributes']['linkage_partner'],
            self.partner.name,
        )
        self.assertEqual(actions[0]['attributes']['reject_reasons'], [])

    def test_construct_qris_linkage_status_change_event_data_case_amar_failed(self):

        reject_code_1 = AmarRejection.Code.ZERO_LIVENESS
        reject_code_2 = AmarRejection.Code.NAME_SCORE_LOW
        reject_code_3 = AmarRejection.Code.BIRTHDAY_SCORE_LOW
        reject_code_4 = "unexpected_code"
        reject_code_5 = "unexpected_code_2"

        self.linkage.partner_callback_payload = {
            "type": "new",
            "status": "rejected",
            "client_id": "ebf-julo-android",
            "source_type": "partner_apps",
            "accountNumber": "",
            "reject_reason": "{},{},{},{}".format(
                reject_code_1, reject_code_2, reject_code_3, reject_code_4, reject_code_5
            ),
            "additional_info": None,
            "partnerCustomerId": self.linkage.to_partner_user_xid.hex,
        }
        self.linkage.status = QrisLinkageStatus.FAILED
        self.linkage.save()

        result_attributes, event_data = construct_qris_linkage_status_change_event_data(
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            event_type=MoengageEventType.QRIS_LINKAGE_STATUS,
        )

        assert result_attributes['attributes']['customer_id'] == self.customer.id

        self.assertIsNotNone(event_data)
        self.assertEqual(event_data['customer_id'], self.customer.id)

        self.assertIsNotNone(event_data['actions'])
        actions = event_data['actions']
        self.assertEqual(actions[0]['action'], MoengageEventType.QRIS_LINKAGE_STATUS)

        self.assertEqual(
            actions[0]['attributes']['status'],
            QrisLinkageStatus.FAILED,
        )
        self.assertEqual(
            actions[0]['attributes']['linkage_partner'],
            self.partner.name,
        )
        self.assertEqual(
            actions[0]['attributes']['reject_reasons'],
            [
                AmarRejection.get_message(reject_code_1),
                AmarRejection.get_message(reject_code_2),
                AmarRejection.get_message(reject_code_3),
                AmarRejection.get_message(reject_code_4),
            ],
        )
