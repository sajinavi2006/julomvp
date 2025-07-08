from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.credgenics.models.loan import CredgenicsLoan
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CustomerFactory,
    LoanFactory,
)
from juloserver.omnichannel.services.credgenics import (
    construct_omnichannel_customer_using_credgenics_data,
)


@patch('juloserver.omnichannel.services.credgenics.get_julo_sentry_client')
@patch('juloserver.omnichannel.services.credgenics.get_credgenics_loans_by_customer_ids_v2')
class TestConstructOmnichannelCustomerUsingCredgenicsData(TestCase):
    def setUp(self):
        self.customers = CustomerFactory.create_batch(2)
        self.customer = self.customers[0]
        self.application = ApplicationJ1Factory(
            customer=self.customer,
            account=AccountFactory(customer=self.customer),
        )
        self.loan = LoanFactory(
            account=self.application.account,
        )
        self.account_payment = AccountPaymentFactory(account=self.application.account)
        self.customer_ids = [customer.id for customer in self.customers]

    def _dummy_credgenic_loan(self, account_payment):
        return CredgenicsLoan(
            transaction_id=account_payment.id,
            account_id=account_payment.account.id,
            client_customer_id=account_payment.account.customer.id,
            customer_due_date='2022-12-31',
            date_of_default='2022-12-31',
            allocation_month='2022-12',
            expected_emi_principal_amount=0,
            expected_emi_interest_amount=0,
            expected_emi=0,
            customer_dpd=0,
            late_fee=0,
            allocation_dpd_value=0,
            dpd=0,
            total_denda=0,
            potensi_cashback=0,
            total_seluruh_perolehan_cashback=0,
            total_due_amount=0,
            total_claim_amount=0,
            total_outstanding=0,
            tipe_produk='product_type',
            last_pay_amount=0,
            activation_amount=0,
            zip_code='12345',
            angsuran_per_bulan=0,
            mobile_phone_1='1234567890',
            mobile_phone_2='0987654321',
            nama_customer='customer_name',
            nama_perusahaan='company_name',
            posisi_karyawan='employee_position',
            nama_pasangan='spouse_name',
            nama_kerabat='relative_name',
            hubungan_kerabat='relative_relationship',
            alamat='address',
            kota='city',
            jenis_kelamin='gender',
            tgl_lahir='1980-01-01',
            tgl_gajian=1,
            tujuan_pinjaman='loan_purpose',
            va_bca='1234567890',
            va_permata='0987654321',
            va_maybank='1234567890',
            va_alfamart='0987654321',
            va_indomaret='1234567890',
            va_mandiri='0987654321',
            last_pay_date='2022-12-31',
            partner_name='partner_name',
            last_agent='last_agent',
            last_call_status='last_call_status',
            refinancing_status='refinancing_status',
            program_expiry_date='2022-12-31',
            customer_bucket_type='customer_bucket_type',
            telp_perusahaan='1234567890',
            no_telp_pasangan='0987654321',
            no_telp_kerabat='1234567890',
            uninstall_indicator='uninstall_indicator',
            fdc_risky=False,
            email='email@example.com',
            cashback_new_scheme_experiment_group=False,
            va_method_name='va_method_name',
            va_number='1234567890',
            short_ptp_date='2022-12-31',
            ptp_amount=0,
            is_j1_customer=False,
            first_name='first_name',
            last_name='last_name',
            month_due_date='12',
            year_due_date='2022',
            due_date_long='2022-12-31',
            age=42,
            title='title',
            sms_due_date_short='31-12',
            sms_month=12,
            sms_firstname='first_name',
            sms_primary_va_name='va_name',
            sms_primary_va_number='1234567890',
            sms_payment_details_url='http://example.com',
            collection_segment='collection_segment',
            bank_code='bank_code',
            bank_code_text='bank_code_text',
            bank_name='bank_name',
            cashback_amount=0,
            cashback_counter=0,
            cashback_due_date_slash='31/12/2022',
            title_long='title_long',
            name_with_title='name_with_title',
            formatted_due_amount='0',
            google_calendar_url='http://example.com',
            shopee_score_status='shopee_score_status',
            shopee_score_list_type='shopee_score_list_type',
            application_similarity_score=Decimal(0.0),
            mycroft_score=0.0,
            credit_score='credit_score',
            active_liveness_score=0.0,
            passive_liveness_score=0.0,
            heimdall_score=0.0,
            orion_score=0.0,
            fpgw=0.0,
            total_loan_amount=0,
            late_fee_applied=0,
            status_code=0,
            is_collection_called=False,
            is_ptp_robocall_active=False,
            is_reminder_called=False,
            is_robocall_active=False,
            is_success_robocall=False,
            ptp_date='2022-12-31',
            ptp_robocall_phone_number='1234567890',
            is_restructured=False,
            account_payment_xid=0,
            autodebet_retry_count=0,
            paid_during_refinancing=False,
            is_paid_within_dpd_1to10=False,
            is_autodebet=False,
            internal_sort_order=0.0,
            campaign_due_amount=0,
            is_risky=False,
            is_email_blocked=False,
            is_sms_blocked=False,
            is_one_way_robocall_blocked=False,
        )

    def test_no_credgenics_loan(self, mock_get_credgenics_loans_by_customer_ids_v2, *args):
        mock_get_credgenics_loans_by_customer_ids_v2.return_value = []

        # Act
        result = construct_omnichannel_customer_using_credgenics_data(self.customer_ids)

        # Assert
        self.assertEqual(2, len(result))

    def test_found_credgenic_loan(
        self, mock_get_credgenics_loans_by_customer_ids_v2, mock_sentry_client
    ):
        mock_get_credgenics_loans_by_customer_ids_v2.return_value = [
            self._dummy_credgenic_loan(self.account_payment)
        ]

        result = construct_omnichannel_customer_using_credgenics_data(self.customer_ids)

        self.assertEqual(2, len(result))
        mock_sentry_client.assert_not_called()
