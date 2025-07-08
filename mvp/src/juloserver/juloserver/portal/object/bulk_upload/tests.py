import pytest
from mock import MagicMock, patch

from django.core.urlresolvers import reverse
from django.test.testcases import TestCase, override_settings
from django.test import mock
import time
from datetime import date, timedelta, datetime
from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountLimit
from juloserver.julo.partners import PartnerConstant
from juloserver.partnership.constants import PartnershipFlag
from juloserver.partnership.models import PartnershipFlowFlag
from juloserver.sdk.models import AxiataCustomerData
from .tasks import generate_application_axiata_async
from juloserver.julo.tests.factories import (PartnerFactory,
                                             AppVersionFactory,
                                             ProductLookupFactory,
                                             CustomerFactory,
                                             LoanFactory,
                                             StatusLookupFactory,
                                             ApplicationFactory,
                                             AuthUserFactory,
                                             GroupFactory,
                                             ProductLineFactory,
                                             WorkflowFactory,
                                             AuthUserFactory,
                                             ApplicationHistoryFactory,
                                             PaymentMethodFactory)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.grab.tests.factories import GrabLoanDataFactory, GrabCustomerDataFactory
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.sdk.tests.factories import AxiataCustomerDataFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import ProductLine, StatusLookup, EmailHistory, Application, Partner
from juloserver.account.tests.factories import AccountFactory
from juloserver.portal.object.bulk_upload.serializers import AxiataCustomerDataSerializer
from juloserver.merchant_financing.serializers import ApplicationPartnerUpdateSerializer
from juloserver.portal.object.bulk_upload.tasks import (
    grab_loan_restructure_task,
    grab_loan_restructure_revert_task,
    grab_early_write_off_task,
    grab_early_write_off_revert_task,
    grab_referral_program_task
)
from juloserver.apiv1.tests.test_views_apiv1 import JuloAPITestCase
from juloserver.portal.object.bulk_upload.constants import MerchantFinancingCSVUploadPartner
from juloserver.portal.object.bulk_upload.services import (
    register_partner_application,
    update_mf_customer_adjust_limit,
    upgrade_efishery_customers
)

from juloserver.account.tests.factories import (
    AccountFactory, AccountLookupFactory, AccountLimitFactory, CreditLimitGenerationFactory
)
from juloserver.julo.constants import WorkflowConst, ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.partnership.tasks import email_notification_for_partner_loan
from .tasks import send_email_at_190_for_pilot_product_csv_upload
from juloserver.julo.clients.email import JuloEmailClient
from juloserver.grab.services.services import grab_update_old_and_create_new_referral_whitelist
from juloserver.grab.models import (
    GrabReferralWhitelistProgram,
    GrabCustomerReferralWhitelistHistory,
    GrabRestructreHistoryLog
)
from juloserver.grab.tests.factories import GrabReferralWhitelistProgramFactory
from juloserver.julo.exceptions import JuloException
# Create your tests here.


def get_axiata_data():
    data = {
        'acceptance_date': '2020-09-10T10:42:00+07:00',
        'account_number': u'628177000000',
        # 'address_kabupaten': u'Jakarta',
        # 'address_kecamatan': u'Kebon jeruk',
        # 'address_kelurahan': u'Sukabumi Selatan',
        # 'address_kodepos': u'40526',
        # 'address_provinsi': u'DKI Jakarta',
        'address_street_num': u'Jl.gegunung Muneng  Kel. Tirtohargo  '
                                u' Kec. Kretek Bantul Daerah Istimewa Yogyakarta  55772',
        'admin_fee': 10000,
        'application': None,
        'birth_place': u'Bantul',
        'brand_name': u'Den prenjak cell',
        'business_category': u'Services',
        'disbursement_date': '2020-09-10T10:42:00+07:00',
        'disbursement_time': '10:15:47',
        'distributor': u'4011',
        'dob': '1993-03-16',
        'email': u'dwi+digiadit@julofinance.com',
        'final_monthly_installment': 6008255.2,
        'first_payment_date': '2020-09-24',
        'fullname': u'Aditya mahendre',
        'funder': u'2',
        'gender': u'Wanita',
        'insurance_fee': 0,
        'interest_rate': 0.75,
        'invoice_id': u'Test1',
        'ip_address': u'120.188.87.195',
        'ktp': u'8979090101020010',
        'loan_amount': 5965305,
        'loan_duration': 1,
        'loan_duration_unit': u'Weeks',
        'marital_status': u'Lajang',
        'monthly_installment': 6008255.2,
        'origination_fee': 0.01,
        'partner_application_date': '2020-09-10T10:42:00+07:00',
        'partner_id': u'0',
        'partner_product_line': u'ISCF V2 - Trio 2.4',
        'partner_score_grade': u'D',
        'phone_number': u'628561112355',
        'shops_number': u'1',
        # 'token': u'd0969b4c-68dc-11ea-a1ff-0694c746bcf4',
        'type_of_business': u'Perusahaan',
        'user_type': 'Perorangan',
        'income': u'5965305',
        'last_education': u'S1',
        'home_status': u'Milik sendiri, lunas',
        'certificate_number': u'132746198123',
        'certificate_date': u'05/29/2020',
        'npwp': u'8979090101020010',
        'kin_name': u'John Testing',
        'kin_mobile_phone': u'082218021552',
    }
    return data


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestAxiataBulkUpload(TestCase):
    def setUp(self):
        self.partner = PartnerFactory(name='axiata')
        self.app_version = AppVersionFactory()
        self.app_version.status = 'latest'
        self.app_version.save()
        self.product_lookup = ProductLookupFactory()
        self.product_lookup.origination_fee_pct = 0.0001
        self.product_lookup.admin_fee = 10000
        self.product_lookup.interest_rate = 0.0075

    def get_axiata_data(self):
        return get_axiata_data()

    @mock.patch('juloserver.portal.object.bulk_upload.tasks.change_due_dates')
    @mock.patch('juloserver.portal.object.bulk_upload.tasks.process_application_status_change')
    @mock.patch('juloserver.portal.object.bulk_upload.tasks.update_payment_fields')
    @mock.patch('juloserver.portal.object.bulk_upload.tasks.generate_application_async')
    @mock.patch('juloserver.portal.object.bulk_upload.tasks.AxiataCustomerData.objects.create')
    def test_generate_application_axiata_async(self, mocked_axiata_obj, mocked_generate_application,
                                               mocked_payment_update, mocked_status_change,
                                               mocked_due_date):
        axiata_data = self.get_axiata_data()
        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        loan = LoanFactory(customer=customer, application=application)
        self.axiata_customer_data = AxiataCustomerDataFactory()
        self.axiata_customer_data.application = application
        self.axiata_customer_data.acceptance_date = datetime.now()
        self.axiata_customer_data.loan_amount = 100000
        self.axiata_customer_data.interest_rate = 0.75
        self.axiata_customer_data.admin_fee = 900
        self.axiata_customer_data.origination_fee = 0.01
        self.axiata_customer_data.save()
        self.account_lookup = AccountLookupFactory(partner=self.partner)
        mocked_axiata_obj.return_value = self.axiata_customer_data
        mocked_generate_application.return_value = (True, "Application generated successfully")
        mocked_payment_update.return_value = None
        mocked_status_change.return_value = None
        mocked_due_date.return_value = None
        generate_application_axiata_async(axiata_data=axiata_data,
                                          partner_id=self.partner.id)
        # mocked_axiata_obj.assert_called_once()
        mocked_generate_application.assert_called_once()
        mocked_payment_update.assert_called_once()
        mocked_status_change.assert_called_with(application.id,
                                                ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
                                                change_reason='approval by script'
                                                )
        loan.refresh_from_db()
        assert loan.loan_amount == 100000
        assert loan.installment_amount == 100750
        assert loan.loan_disbursement_amount == 99090


class TestAxiataCustomerDataSerializer(TestCase):
    def setUp(self):
        super().setUp()
        self.product_lookup = ProductLookupFactory(
            origination_fee_pct=0.0001,
            admin_fee=10000,
            interest_rate=0.0075,
            product_line=ProductLine.objects.get_or_none(product_line_code=ProductLineCodes.AXIATA1)
        )

        self.partner = PartnerFactory(name=PartnerConstant.AXIATA_PARTNER)
        self.partnership_flow_flag = PartnershipFlowFlag.objects.create(
            partner=self.partner,
            name=PartnershipFlag.FIELD_CONFIGURATION,
            configs={
                'fields': {
                    'user_type': True,
                    'income': True,
                    'last_education': True,
                    'home_status': True,
                    'certificate_number': True,
                    'certificate_date': True,
                    'npwp': True,
                    'kin_name': True,
                    'kin_mobile_phone': True,
                },
                'perorangan': [
                    'income',
                    'last_education',
                    'home_status',
                    'kin_name',
                    'kin_mobile_phone',
                ],
                'lembaga': [
                    'income',
                    'certificate_number',
                    'certificate_date',
                    'npwp',
                    'kin_name',
                    'kin_mobile_phone',
                ],
            },
        )

    def test_invalid_data(self):
        axiata_data = get_axiata_data()
        axiata_data.pop('email')
        serializer = AxiataCustomerDataSerializer(data=axiata_data)

        self.assertFalse(serializer.is_valid())

    def test_product_line_axiata1(self):
        axiata_data = get_axiata_data()
        self.product_lookup.product_line = ProductLine.objects.get_or_none(
            product_line_code=ProductLineCodes.AXIATA1)
        self.product_lookup.save()
        serializer = AxiataCustomerDataSerializer(data=axiata_data)

        self.assertTrue(serializer.is_valid())

    def test_product_line_axiata2(self):
        axiata_data = get_axiata_data()
        self.product_lookup.product_line = ProductLine.objects.get_or_none(
            product_line_code=ProductLineCodes.AXIATA2)
        self.product_lookup.save()
        serializer = AxiataCustomerDataSerializer(data=axiata_data)

        self.assertFalse(serializer.is_valid())

    def test_customer_exists(self):
        axiata_data = get_axiata_data()
        self.customer = CustomerFactory(nik=axiata_data['ktp'])
        serializer = AxiataCustomerDataSerializer(data=axiata_data)

        self.assertTrue(serializer.is_valid())

    def test_email_uppercase(self):
        axiata_data = get_axiata_data()
        axiata_data['email'] = 'EmAil@Testing.Com'
        serializer = AxiataCustomerDataSerializer(data=axiata_data)

        expected_email = 'email@testing.com'
        self.assertTrue(serializer.is_valid())
        self.assertEqual(expected_email, serializer.data['email'])

    def test_user_type(self):
        axiata_data = get_axiata_data()

        serializer = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertTrue(serializer.is_valid())

        axiata_data['user_type'] = 'koperasi'
        serializer_2 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer_2.is_valid())

    def test_last_education(self):
        axiata_data = get_axiata_data()

        axiata_data['last_education'] = 'sS'
        serializer = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer.is_valid())

        axiata_data['last_education'] = 's3'
        serializer_2 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertTrue(serializer_2.is_valid())

    def test_certificate_date(self):
        axiata_data = get_axiata_data()
        axiata_data['user_type'] = 'Lembaga'

        serializer = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertTrue(serializer.is_valid())

        axiata_data['certificate_date'] = '05-29-2020'
        serializer_2 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer_2.is_valid())

    def test_kin_name(self):
        axiata_data = get_axiata_data()

        axiata_data['kin_name'] = ''
        serializer = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer.is_valid())

        axiata_data['kin_name'] = 'John testing1212'
        serializer_2 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer_2.is_valid())

        axiata_data['kin_name'] = 'Bpk testing1212$$'
        serializer_3 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer_3.is_valid())

        axiata_data['kin_name'] = 'John testing'
        serializer_4 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertTrue(serializer_4.is_valid())

        # test required kin_name as lembaga
        axiata_data['user_type'] = 'Lembaga'
        axiata_data['kin_name'] = ''
        serializer_5 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer_5.is_valid())

        axiata_data['kin_name'] = 'John testing1212'
        serializer_6 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer_6.is_valid())

        axiata_data['kin_name'] = 'Bpk testing1212$$'
        serializer_7 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer_7.is_valid())

        axiata_data['kin_name'] = 'John testing'
        serializer_8 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertTrue(serializer_8.is_valid())

    def test_kin_mobile_phone(self):
        axiata_data = get_axiata_data()

        axiata_data['kin_mobile_phone'] = '082118101131as'
        serializer = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer.is_valid())

        axiata_data['kin_mobile_phone'] = '082118101131'
        serializer_2 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertTrue(serializer_2.is_valid())

        # test required kin_mobile_phone as lembaga
        axiata_data['user_type'] = 'Lembaga'
        axiata_data['kin_mobile_phone'] = '082118101131as'
        serializer_3 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer_3.is_valid())

        axiata_data['kin_mobile_phone'] = '082118101131'
        serializer_4 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertTrue(serializer_4.is_valid())

    def test_config(self):
        axiata_data = get_axiata_data()

        self.partnership_flow_flag.configs.update(
            {
                'fields': {
                    'user_type': False,
                    'income': False,
                    'last_education': False,
                    'home_status': False,
                    'certificate_number': False,
                    'certificate_date': True,
                    'npwp': False,
                    'kin_name': False,
                    'kin_mobile_phone': False,
                },
                'perorangan': [
                    'income',
                    'last_education',
                    'home_status',
                    'kin_name',
                    'kin_mobile_phone',
                ],
                'lembaga': ['income', 'certificate_number', 'certificate_date', 'npwp'],
            }
        )
        self.partnership_flow_flag.save()

        # Should return False because certificate_number is not required for 'Perorangan'
        # but certificate_date config is mandatory
        axiata_data['user_type'] = 'Perorangan'
        axiata_data['income'] = ''
        axiata_data['certificate_date'] = u'05-29-2020'
        serializer = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertFalse(serializer.is_valid())

        # Should return True because certificate_number is not required for 'Perorangan'
        # and certificate_number config is optional
        axiata_data['certificate_date'] = u'05/29/2020'
        axiata_data['certificate_number'] = u'1327dsfsd  46198123'
        serializer_2 = AxiataCustomerDataSerializer(data=axiata_data)
        self.assertTrue(serializer_2.is_valid())


class TestGrabRestructured(TestCase):
    def setUp(self) -> None:
        from juloserver.grab.tests.utils import ensure_grab_restructure_history_log_table_exists
        ensure_grab_restructure_history_log_table_exists()

        self.product_lookup = ProductLookupFactory(
            origination_fee_pct=0.0001,
            admin_fee=10000,
            interest_rate=0.0075,
            product_line=ProductLineFactory()
        )
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, partner=self.partner, account=self.account)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() + timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account
        )

        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)

    @mock.patch('juloserver.portal.object.bulk_upload.tasks.'
                'trigger_grab_loan_sync_api_async_task.apply_async')
    @mock.patch('juloserver.portal.object.bulk_upload.tasks.trigger_grab_refinance_email.apply_async')
    def test_restructure_task(self, mocked_email, mocked_loan_sync) -> None:
        self.grab_loan_data.is_repayment_capped = None
        self.grab_loan_data.save()
        mocked_loan_sync.return_value = None
        mocked_email.return_value = None
        test_data = {
            'loan_xid': self.loan.loan_xid,
            'action': 'restructure',
            'action_key': 'Restructure',
            'partner': 'grab',
            'agent_user_id': None
        }
        grab_loan_restructure_task(test_data, self.partner.id)
        self.grab_loan_data.refresh_from_db()
        self.assertTrue(self.grab_loan_data.is_repayment_capped)
        self.assertIsNotNone(self.grab_loan_data.restructured_date)
        mocked_email.assert_called()
        mocked_loan_sync.assert_called()
        self.assertTrue(
            GrabRestructreHistoryLog.objects.filter(
                loan_id=self.loan.id, is_restructured=True).exists()
        )

    def test_restructure_revert_task(self) -> None:
        self.grab_loan_data.is_repayment_capped = True
        self.grab_loan_data.save()
        test_data = {
            'loan_xid': self.loan.loan_xid,
            'action': 'revert',
            'action_key': 'Revert',
            'partner': 'grab',
            'agent_user_id': None
        }
        grab_loan_restructure_revert_task(test_data, self.partner.id)
        self.grab_loan_data.refresh_from_db()
        self.assertFalse(self.grab_loan_data.is_repayment_capped)

        self.assertTrue(
            GrabRestructreHistoryLog.objects.filter(
                loan_id=self.loan.id,
                is_restructured=False,
                restructure_date__isnull=True).exists()
        )


class TestGrabRestructureView(JuloAPITestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.group_factory = GroupFactory(name=JuloUserRoles.BO_DATA_VERIFIER)
        self.user.groups.add(self.group_factory)
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, partner=self.partner, account=self.account)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() + timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account,
            loan_xid=1000003236
        )

        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)

    @mock.patch('juloserver.portal.object.bulk_upload.views.grab_loan_restructure_revert_task.apply_async')
    @mock.patch('juloserver.portal.object.bulk_upload.views.grab_loan_restructure_task.apply_async')
    def test_grab_api_view(
            self, mocked_restructure_task, mocked_revert_task):
        self.client.force_login(self.user)
        url = reverse('bulk_upload:grab_loan_restructuring')

        mocked_restructure_task.return_value = None
        mocked_revert_task.return_value = None
        data = {
            'partner_field': [str(self.partner.id)],
            'action_field': ['Restructure']
        }
        files = {'file_field': b'random_garbage_value'}
        response = self.client.post(url, data, files=files, format='json')
        self.assertEqual(response.status_code, 200)


class TestRegisterPartnerApplication(TestCase):

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(user=self.user,
                                      name=MerchantFinancingCSVUploadPartner.EFISHERY,
                                      is_disbursement_to_partner_bank_account=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.EFISHERY,
                                               product_line_type='EF')
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )
        self.user1 = AuthUserFactory()
        self.customer1 = CustomerFactory(user=self.user1)
        self.partner1 = PartnerFactory(user=self.user1,
                                       name=MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE,
                                       is_disbursement_to_partner_bank_account=True)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE,
            handler='JuloOneWorkflowHandler'
        )

    @patch('juloserver.portal.object.bulk_upload.services.download_image_from_url_and_upload_to_oss')
    def test_register_partner_application(self, mock_download_image_from_url):
        customer_data = {}
        customer_data['ktp'] = 3271065902890002
        customer_data['email'] = "testing@gmail.com"
        customer_data['approved_limit'] = 1000000
        customer_data['selfie_photo'] = ''
        customer_data['ktp_photo'] = ''
        customer_data['last_education'] = ''
        customer_data['home_status'] = ''
        customer_data['kin_name'] = ''
        customer_data['kin_mobile_phone'] = ''

        with self.assertRaises(Exception):
            with self.assertRaises(Exception):
                register_partner_application(customer_data, self.partner)

        with self.assertRaises(Exception):
            with self.assertRaises(Exception):
                register_partner_application(customer_data, self.partner1)


class TestGrabEarlyWriteOffServices(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, partner=self.partner, account=self.account)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() + timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account
        )

        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)

    @mock.patch('juloserver.portal.object.bulk_upload.tasks.'
                'trigger_grab_loan_sync_api_async_task.apply_async')
    def test_early_write_off_task(self, mocked_loan_sync) -> None:
        self.grab_loan_data.is_early_write_off = None
        self.grab_loan_data.save()
        test_data = {
            'loan_xid': self.loan.loan_xid,
            'action': 'early_write_off',
            'action_key': 'Early Write Off',
            'partner': 'grab',
            'agent_user_id': None
        }
        mocked_loan_sync.return_value = None
        grab_early_write_off_task(test_data, self.partner.id)
        self.grab_loan_data.refresh_from_db()
        self.assertTrue(self.grab_loan_data.is_early_write_off)
        self.assertIsNotNone(self.grab_loan_data.early_write_off_date)
        mocked_loan_sync.assert_called()

    def test_early_write_off_revert_task(self) -> None:
        self.grab_loan_data.is_early_write_off = True
        self.grab_loan_data.save()
        test_data = {
            'loan_xid': self.loan.loan_xid,
            'action': 'revert',
            'action_key': 'Revert',
            'partner': 'grab',
            'agent_user_id': None
        }
        grab_early_write_off_revert_task(test_data, self.partner.id)
        self.grab_loan_data.refresh_from_db()
        self.assertFalse(self.grab_loan_data.is_early_write_off)


class TestGrabWriteOffView(JuloAPITestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.group_factory = GroupFactory(name=JuloUserRoles.PRODUCT_MANAGER)
        self.user.groups.add(self.group_factory)
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, partner=self.partner, account=self.account)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() + timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account,
            loan_xid=1000003236
        )

        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)

    @mock.patch('juloserver.portal.object.bulk_upload.views.grab_early_write_off_revert_task.apply_async')
    @mock.patch('juloserver.portal.object.bulk_upload.views.grab_early_write_off_task.apply_async')
    def test_grab_api_view(
            self, mocked_early_write_off_task, mocked_revert_task):
        self.client.force_login(self.user)
        url = reverse('bulk_upload:early_write_off')

        mocked_early_write_off_task.return_value = None
        mocked_revert_task.return_value = None
        data = {
            'partner_field': [str(self.partner.id)],
            'action_field': ['Early Write Off']
        }
        files = {'file_field': b'random_garbage_value'}
        response = self.client.post(url, data, files=files, format='json')
        self.assertEqual(response.status_code, 200)


class TestSendEmailAt190ForPilotCsvUploadTask(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user,
                                      name=MerchantFinancingCSVUploadPartner.KOPERASI_TUNAS)
        self.customer = CustomerFactory(
            email='koperasi_tunas+4011112001700001__-__300000__-__@julofinance.com')
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationFactory(
            customer=self.customer, partner=self.partner, account=self.account)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id, status_new=ApplicationStatusCodes.LOC_APPROVED)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() + timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=10000000,
            used_limit=100000
        )
        self.credit_limit_generation = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            max_limit=10000000,
            set_limit=self.account_limit.set_limit
        )
        self.payment_method = PaymentMethodFactory(
            is_primary=True,
            customer=self.customer,
            payment_method_name='test'
        )

    @patch('juloserver.portal.object.bulk_upload.tasks.get_pdf_content_from_html')
    @patch.object(JuloEmailClient, 'send_email')
    def test_send_email_at_190_for_pilot_product_csv_upload(self, mock_email_client: MagicMock,
                                                            mock_pdf_content: MagicMock) -> None:
        provision = None
        customer = self.application.customer
        email_split = customer.email.split('__-__')
        limit = email_split[1]

        with self.assertRaises(Exception) as context:
            send_email_at_190_for_pilot_product_csv_upload(self.application.id,
                                                           limit, provision)
        self.assertEqual(str(context.exception),
                         "{} sender_email_address_for_190_application not found".
                         format(self.partner.name))
        self.partner.sender_email_address_for_190_application = 'sender@est.com'
        self.partner.save()

        with self.assertRaises(Exception) as context:
            send_email_at_190_for_pilot_product_csv_upload(self.application.id,
                                                           limit, provision)
        self.assertEqual(str(context.exception),
                         "{} recipients_email_address_for_190_application not found".
                         format(self.partner.name))
        self.partner.recipients_email_address_for_190_application = 'receiver@test.com'
        self.partner.save()
        mock_email_client.return_value = \
            (202, {'X-Message-Id': 'mf_190_email'},
             'dummy_subject', 'dummy_message', 'mf_190_email')

        send_email_at_190_for_pilot_product_csv_upload(self.application.id,
                                                       limit, provision)

        email_history = EmailHistory.objects.filter(
            customer=self.account.customer,
            template_code='{}_190_email'.format(self.partner.name)).count()
        assert email_history > 0


class TestGrabReferralView(JuloAPITestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.group_factory = GroupFactory(name=JuloUserRoles.PRODUCT_MANAGER)
        self.user.groups.add(self.group_factory)
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, partner=self.partner, account=self.account)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() + timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account,
            loan_xid=1000003236
        )

        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)

    @mock.patch('juloserver.portal.object.bulk_upload.views.'
                'grab_update_old_and_create_new_referral_whitelist')
    @mock.patch('juloserver.portal.object.bulk_upload.views.grab_referral_program_task.apply_async')
    def test_grab_api_view(
            self, mocked_referral_task, mocked_sync_task):
        self.client.force_login(self.user)
        url = reverse('bulk_upload:referral_program')

        mocked_referral_task.return_value = None
        mocked_sync_task.return_value = None
        data = {
            'partner_field': [str(self.partner.id)],
            'action_field': ['Referral']
        }
        files = {'file_field': b'random_garbage_value'}
        response = self.client.post(url, data, files=files, format='json')
        self.assertEqual(response.status_code, 200)


class TestGrabReferralServices(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer,
            phone_number="6284962122335"
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.application = ApplicationFactory(
            customer=self.customer,
            partner=self.partner,
            account=self.account,
            product_line=self.product_line
        )
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.PAID_OFF_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            fund_transfer_ts=date.today() + timedelta(days=3),
            loan_status=self.loan_status,
            account=self.account
        )

        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)

    def test_grab_create_new_whitelist_success_1(self):
        grab_update_old_and_create_new_referral_whitelist()
        self.assertTrue(GrabReferralWhitelistProgram.objects.filter(
            is_active=True).exists())

    def test_grab_create_new_whitelist_success_2(self):
        grwp = GrabReferralWhitelistProgramFactory()
        grab_update_old_and_create_new_referral_whitelist()
        self.assertEqual(GrabReferralWhitelistProgram.objects.filter(
            is_active=True).count(), 1)
        grwp.refresh_from_db()
        self.assertIsNotNone(grwp.end_time)
        self.assertFalse(grwp.is_active)

    def test_grab_referral_program_task_success_1(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        grwp = GrabReferralWhitelistProgramFactory()
        data = {
            'phone_number': '6284962122335',
            'action': 'referral',
            'partner_id': self.partner.id,
            'action_key': 'Referral w/o updating whitelist',
            'partner': 'grab'
        }
        grab_referral_program_task(data)
        self.assertTrue(GrabCustomerReferralWhitelistHistory.objects.filter(
            grab_referral_whitelist_program=grwp, customer=self.customer).exists())

    def test_grab_referral_program_task_failure_1(self):
        # For no active number
        grwp = GrabReferralWhitelistProgramFactory()
        data = {
            'phone_number': '6284962122337',
            'action': 'referral',
            'partner_id': self.partner.id,
            'action_key': 'Referral w/o updating whitelist',
            'partner': 'grab'
        }
        return_value = grab_referral_program_task(data)
        self.assertEqual(return_value, None)
        self.assertFalse(GrabCustomerReferralWhitelistHistory.objects.filter(
            grab_referral_whitelist_program=grwp, customer=self.customer).exists())

    def test_grab_referral_program_task_failure_2(self):
        GrabReferralWhitelistProgram.objects.all().delete()
        GrabCustomerReferralWhitelistHistory.objects.filter(
            customer=self.customer).delete()
        customer = CustomerFactory()
        grab_customer_data = GrabCustomerDataFactory(
            phone_number='6284962122337', customer=customer)
        data = {
            'phone_number': '6284962122337',
            'action': 'referral',
            'partner_id': self.partner.id,
            'action_key': 'Referral w/o updating whitelist',
            'partner': 'grab'
        }
        return_value = grab_referral_program_task(data)
        self.assertIsNone(return_value)
        self.assertFalse(GrabCustomerReferralWhitelistHistory.objects.filter(
            customer=self.customer).exists())

    def test_grab_referral_program_task_failure_3(self):
        GrabReferralWhitelistProgram.objects.all().delete()
        GrabCustomerReferralWhitelistHistory.objects.filter(
            customer=self.customer).delete()
        customer = CustomerFactory()
        GrabCustomerDataFactory(
            phone_number='6284962122337', customer=customer)
        ApplicationFactory(
            customer=customer,
            partner=self.partner
        )
        data = {
            'phone_number': '6284962122337',
            'action': 'referral',
            'partner_id': self.partner.id,
            'action_key': 'Referral w/o updating whitelist',
            'partner': 'grab'
        }
        return_value = grab_referral_program_task(data)
        self.assertIsNone(return_value)
        self.assertFalse(GrabCustomerReferralWhitelistHistory.objects.filter(
            customer=self.customer).exists())

    def test_grab_referral_program_task_failure_4(self):
        GrabReferralWhitelistProgram.objects.all().delete()
        GrabCustomerReferralWhitelistHistory.objects.filter(
            customer=self.customer).delete()
        customer = CustomerFactory()
        GrabCustomerDataFactory(
            phone_number='6284962122337', customer=customer)
        application = ApplicationFactory(
            customer=customer,
            partner=self.partner,
            product_line=self.product_line
        )
        partner = PartnerFactory()
        data = {
            'phone_number': '6284962122337',
            'action': 'referral',
            'partner_id': self.partner.id,
            'action_key': 'Referral w/o updating whitelist',
            'partner': 'grab'
        }
        return_value = grab_referral_program_task(data)
        self.assertIsNone(return_value)
        self.assertFalse(GrabCustomerReferralWhitelistHistory.objects.filter(
            customer=self.customer).exists())


class TestUpdateMfCustomerAdjustLimit(TestCase):
    def setUp(self):
        self.valid_customer = CustomerFactory()
        self.invalid_customer = CustomerFactory()

        # Partner
        self.valid_partner = PartnerFactory(name=MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE,
                                            is_active=True)
        self.invalid_partner = PartnerFactory(name=MerchantFinancingCSVUploadPartner.KARGO, is_active=True)

        # StatusLookup
        self.status_active = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.status_inactive = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.inactive)
        self.status_loc_approved = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.status_application_denied = StatusLookupFactory(status_code=ApplicationStatusCodes.APPLICATION_DENIED)

        # Account
        self.customer = CustomerFactory()
        self.account = AccountFactory(status=self.status_active)
        self.account_limit_factory = AccountLimitFactory(
            account=self.account,
            max_limit=500000,
            set_limit=500000,
            available_limit=200000,
            used_limit=300000,
        )

        # Application
        self.application = ApplicationFactory(account=self.account, partner=self.valid_partner)
        self.application.application_status = self.status_loc_approved
        self.application.save()

    @mock.patch('juloserver.portal.object.bulk_upload.services.'
                'fdc_binary_check_merchant_financing_csv_upload')
    def test_success_adjust_limit_increase(self, mock_fdc_binary_check):
        new_limit = '1000000'
        mock_fdc_binary_check.return_value = True
        is_success, message = update_mf_customer_adjust_limit(application_xid=self.application.application_xid,
                                                              new_limit=new_limit, partner=self.valid_partner)
        print(is_success, message)
        self.assertEqual(True, is_success)
        self.assertEqual("Success update limit and product line", message)

        # account limit is updated
        account_limit = (
            AccountLimit.objects.filter(account=self.account)
            .select_related(
                'account',
                'account__dana_customer_data',
                'account__dana_customer_data__customer__customerlimit',
            )
            .first()
        )

        new_available_limit = int(new_limit) - self.account_limit_factory.used_limit
        self.assertEqual(account_limit.available_limit, new_available_limit)
        self.assertEqual(account_limit.set_limit, int(new_limit))
        self.assertEqual(account_limit.max_limit, int(new_limit))

    @mock.patch('juloserver.portal.object.bulk_upload.services.'
                'fdc_binary_check_merchant_financing_csv_upload')
    def test_success_adjust_limit_decrease(self, mock_fdc_binary_check):
        new_limit = '10000'
        mock_fdc_binary_check.return_value = True
        is_success, message = update_mf_customer_adjust_limit(application_xid=self.application.application_xid,
                                                              new_limit=new_limit, partner=self.valid_partner)
        print(is_success, message)
        self.assertEqual(True, is_success)
        self.assertEqual("Success update limit and product line", message)

        # account limit is updated
        account_limit = (
            AccountLimit.objects.filter(account=self.account)
            .select_related(
                'account',
                'account__dana_customer_data',
                'account__dana_customer_data__customer__customerlimit',
            )
            .first()
        )

        new_available_limit = int(new_limit) - self.account_limit_factory.used_limit
        self.assertEqual(account_limit.available_limit, new_available_limit)
        self.assertEqual(account_limit.set_limit, int(new_limit))
        self.assertEqual(account_limit.max_limit, int(new_limit))

    @mock.patch('juloserver.portal.object.bulk_upload.services.'
                'fdc_binary_check_merchant_financing_csv_upload')
    def test_invalid_adjust_limit(self, mock_fdc_binary_check):
        # invalid application_xid - Application xid not found
        is_success, message = update_mf_customer_adjust_limit(application_xid='1324768124', new_limit='300000',
                                                              partner=self.invalid_partner)
        self.assertEqual(False, is_success)
        self.assertEqual("Application not found with application_xid: 1324768124", message)

        # invalid application status
        self.application.application_status = self.status_application_denied
        self.application.save()
        is_success, message = update_mf_customer_adjust_limit(application_xid=self.application.application_xid,
                                                              new_limit='300000', partner=self.invalid_partner)
        self.assertEqual(False, is_success)
        self.assertEqual("Application status is not 190: {}".format(self.application.application_xid), message)

        # invalid fdc binary check
        self.application.application_status = self.status_loc_approved
        self.application.save()
        mock_fdc_binary_check.return_value = False
        is_success, message = update_mf_customer_adjust_limit(application_xid=self.application.application_xid,
                                                              new_limit='300000', partner=self.valid_partner)
        print(is_success, message)
        self.assertEqual(False, is_success)
        self.assertEqual("Fail FDC Check: {}".format(self.application.application_xid), message)


class TestMfUpgradeEfisheryApplication(TestCase):

    def setUp(self) -> None:
        self.valid_customer = CustomerFactory()
        self.invalid_customer = CustomerFactory()

        # Product line
        self.product_efishery = ProductLineFactory(product_line_code=ProductLineCodes.EFISHERY,
                                                   max_amount=20000000)
        self.product_efishery_lite = ProductLineFactory(product_line_code=ProductLineCodes.EFISHERY_KABAYAN_LITE,
                                                        max_amount=50000000)
        self.product_efishery_reguler = ProductLineFactory(product_line_code=ProductLineCodes.EFISHERY_KABAYAN_REGULER,
                                                           max_amount=200000000)
        self.product_efishery_jawara = ProductLineFactory(product_line_code=ProductLineCodes.EFISHERY_JAWARA,
                                                           max_amount=1000000000)
        self.product_kargo = ProductLineFactory(product_line_code=ProductLineCodes.KARGO,
                                                max_amount=50000000)

        # Partner
        self.partner_efishery = PartnerFactory(name=MerchantFinancingCSVUploadPartner.EFISHERY,
                                               product_line=self.product_efishery,
                                               is_active=True)

        self.partner_efishery_lite = PartnerFactory(name=MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE,
                                                    product_line=self.product_efishery_lite,
                                                    is_active=True)
        self.partner_efishery_reguler = PartnerFactory(name=MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_REGULER,
                                                       product_line=self.product_efishery_reguler,
                                                       is_active=True)
        self.partner_efishery_jawara = PartnerFactory(name=MerchantFinancingCSVUploadPartner.EFISHERY_JAWARA,
                                                       product_line=self.product_efishery_jawara,
                                                       is_active=True)
        self.partner_kargo = PartnerFactory(name=MerchantFinancingCSVUploadPartner.KARGO,
                                            product_line=self.product_kargo,
                                            is_active=True)

        # StatusLookup
        self.status_active = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.status_inactive = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.inactive)
        self.status_loc_approved = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.status_data_verified = StatusLookupFactory(status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED)

        # Account
        self.customer = CustomerFactory()
        self.account = AccountFactory(status=self.status_active)

    def _build_application(self, partner, product_line):
        AccountLimitFactory(
            account=self.account,
            max_limit=500000,
            set_limit=500000,
            available_limit=200000,
            used_limit=300000,
        )

        # Application
        application = ApplicationFactory(account=self.account, partner=partner, product_line=product_line)
        application.application_status = self.status_loc_approved
        application.save()

        return application

    @mock.patch('juloserver.portal.object.bulk_upload.services.fdc_binary_check_merchant_financing_csv_upload')
    def test_upgrade_efishery(self, mock_fdc_binary_check):
        mock_fdc_binary_check.return_value = True
        # Success upgrade
        application = self._build_application(partner=self.partner_efishery, product_line=self.product_efishery)
        is_success, message = upgrade_efishery_customers(application_xid=application.application_xid,
                                                         partner=self.partner_efishery_lite,
                                                         new_limit=30000000)
        self.assertEqual(True, is_success)

        # Failed upgrade - application not found
        is_success, message = upgrade_efishery_customers(application_xid='17123813',
                                                         partner=self.partner_efishery_lite,
                                                         new_limit=30000000)
        self.assertEqual(False, is_success)
        self.assertEqual("Application not found with application_xid: 17123813", message)

        # Failed upgrade - application status not 190
        failed_application = self._build_application(partner=self.partner_efishery, product_line=self.product_efishery)
        failed_application.application_status = self.status_data_verified
        failed_application.save()
        is_success, message = upgrade_efishery_customers(application_xid=failed_application.application_xid,
                                                         partner=self.partner_efishery_lite,
                                                         new_limit=30000000)
        self.assertEqual(False, is_success)
        self.assertEqual("Application status is not 190: {}".format(failed_application.application_xid), message)

        # Failed upgrade - account status not 420
        self.account.status = self.status_inactive
        self.account.save()
        application = self._build_application(partner=self.partner_efishery, product_line=self.product_efishery)
        is_success, message = upgrade_efishery_customers(application_xid=application.application_xid,
                                                         partner=self.partner_efishery_lite,
                                                         new_limit=30000000)
        self.assertEqual(False, is_success)
        self.assertEqual("Account status is not 420: {}".format(application.application_xid), message)

        # Failed upgrade - application partner not efishery express
        self.account.status = self.status_active
        self.account.save()
        application = self._build_application(partner=self.partner_efishery, product_line=self.product_efishery)
        invalid_application = self._build_application(partner=self.partner_efishery_reguler,
                                                      product_line=self.product_efishery_reguler)
        is_success, message = upgrade_efishery_customers(application_xid=invalid_application.application_xid,
                                                         partner=self.partner_efishery_lite,
                                                         new_limit=30000000)
        self.assertEqual(False, is_success)
        self.assertEqual("Application partner is not efishery", message)

        # Failed upgrade - new limit more than product line max amount
        application = self._build_application(partner=self.partner_efishery, product_line=self.product_efishery)
        is_success, message = upgrade_efishery_customers(application_xid=application.application_xid,
                                                         partner=self.partner_efishery_lite,
                                                         new_limit=70000000)
        self.assertEqual(False, is_success)
        self.assertEqual("New limit: 70000000; is greater than max product line amount: 50000000", message)

        # Failed upgrade - new limit less than current limit
        application = self._build_application(partner=self.partner_efishery, product_line=self.product_efishery)
        is_success, message = upgrade_efishery_customers(application_xid=application.application_xid,
                                                         partner=self.partner_efishery_lite,
                                                         new_limit=200000)
        self.assertEqual(False, is_success)
        self.assertEqual("New limit: 200000; is smaller than current limit: 500000", message)

        # Failed upgrade - failed FDC check
        mock_fdc_binary_check.return_value = False
        application = self._build_application(partner=self.partner_efishery, product_line=self.product_efishery)
        is_success, message = upgrade_efishery_customers(application_xid=application.application_xid,
                                                         partner=self.partner_efishery_lite,
                                                         new_limit=30000000)
        self.assertEqual(False, is_success)
        self.assertEqual("Fail FDC Check: {}".format(application.application_xid), message)

    @mock.patch('juloserver.portal.object.bulk_upload.services.fdc_binary_check_merchant_financing_csv_upload')
    def test_upgrade_efishery_lite(self, mock_fdc_binary_check):
        mock_fdc_binary_check.return_value = True

        # Success upgrade
        application = self._build_application(partner=self.partner_efishery_lite,
                                              product_line=self.product_efishery_lite)
        is_success, message = upgrade_efishery_customers(application_xid=application.application_xid,
                                                         partner=self.partner_efishery_reguler,
                                                         new_limit=70000000)
        self.assertEqual(True, is_success)

        upgraded_application = (
            Application.objects.filter(application_xid=application.application_xid).last()
        )
        self.assertEqual(self.product_efishery_reguler, upgraded_application.product_line)

    @mock.patch('juloserver.portal.object.bulk_upload.services.fdc_binary_check_merchant_financing_csv_upload')
    def test_upgrade_efishery_reguler(self, mock_fdc_binary_check):
        mock_fdc_binary_check.return_value = True

        # Success upgrade
        application = self._build_application(partner=self.partner_efishery_reguler,
                                              product_line=self.product_efishery_reguler)
        is_success, message = upgrade_efishery_customers(application_xid=application.application_xid,
                                                         partner=self.partner_efishery_jawara,
                                                         new_limit=900000000)
        self.assertEqual(True, is_success)

        upgraded_application = (
            Application.objects.filter(application_xid=application.application_xid).last()
        )
        self.assertEqual(self.product_efishery_jawara, upgraded_application.product_line)
