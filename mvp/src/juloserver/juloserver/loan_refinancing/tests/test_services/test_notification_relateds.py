from mock import patch, MagicMock
from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.clients.email import JuloEmailClient
from juloserver.julo.models import EmailHistory
from juloserver.julo.tests.factories import LoanFactory, CustomerFactory, ApplicationFactory, PaymentMethodFactory
from juloserver.loan_refinancing.services.notification_related import (
    CovidLoanRefinancingEmail, CovidLoanRefinancingSMS, CovidLoanRefinancingPN)
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory, LoanRefinancingRequestCampaignFactory, WaiverRequestFactory)
from juloserver.loan_refinancing.constants import Campaign, CohortCampaignEmail, CohortCampaignPN
from juloserver.julo.utils import display_rupiah
from babel.dates import format_date
from datetime import datetime, timedelta
from unittest import skip


class TestCovidLoanRefinancingEmail(TestCase):
    def setUp(self):
        self.loan_ref_req = LoanRefinancingRequestFactory(
            product_type="R4", comms_channel_1="Email",
        )
        self.covid_loan_refinancing_email = CovidLoanRefinancingEmail(self.loan_ref_req)
        self.waiver_request = WaiverRequestFactory()

    @patch('juloserver.loan_refinancing.models.WaiverRequest.objects')
    def test_waiver_send_approved_email(self, waiver_mock):
        # loan refinancing request is R4 special campaign
        self.loan_ref_req.product_type = "R4"
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at=(datetime.today() + timedelta(days=2)).date()
        )
        self.waiver_request.outstanding_amount = 9000000
        waiver_mock.filter.return_value.last.return_value = self.waiver_request
        self.loan_ref_req.prerequisite_amount = 900000
        self.loan_ref_req.save()
        self.covid_loan_refinancing_email._construct_email_params = MagicMock(
            return_value=({}, {'prerequisite_amount': 900000})
        )
        self.covid_loan_refinancing_email._generate_google_calendar_link = MagicMock(
            return_value='test'
        )
        self.covid_loan_refinancing_email._email_client = MagicMock()
        self.covid_loan_refinancing_email._create_email_history = MagicMock()
        self.covid_loan_refinancing_email.send_approved_email()
        self.covid_loan_refinancing_email._email_client.email_covid_refinancing_approved_for_r4.\
            assert_called_once_with(
            {}, {'total_payments': self.waiver_request.outstanding_amount,
                 'prerequisite_amount': 900000},
            CohortCampaignEmail.SUBJECT_R4_1,
            'covid_refinancing/covid_r4_special_cohort_approved_email.html', 'test', False)

    def test_get_reminder_template(self):
        # loan refinancing request is R4 special campaign
        self.loan_ref_req.product_type = "R4"
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at=(datetime.today() + timedelta(days=2)).date()
        )
        self.covid_loan_refinancing_email._generate_google_calendar_link = MagicMock(
            return_value='test'
        )
        # due to expried = 2
        template, template_code, calendar_link = self.covid_loan_refinancing_email.\
            _get_reminder_template(2)
        self.assertEqual(template, 'covid_refinancing/covid_r4_special_cohort_minus2_email.html')
        self.assertEqual(template_code, CohortCampaignEmail.TEMPLATE_CODE_R4_2)
        # due to expried = 1
        template, template_code, calendar_link = self.covid_loan_refinancing_email. \
            _get_reminder_template(1)
        self.assertEqual(template, 'covid_refinancing/covid_r4_special_cohort_minus1_email.html')
        self.assertEqual(template_code, CohortCampaignEmail.TEMPLATE_CODE_R4_3)


class TestCovidLoanRefinancingSMS(TestCase):
    def setUp(self):
        self.loan_ref_req = LoanRefinancingRequestFactory(product_type="R4")
        self.covid_loan_refinancing_sms = CovidLoanRefinancingSMS(self.loan_ref_req)

    def test_send_approved_sms_not_campaign(self):
        # loan refinancing request is R1 not special campaign
        self.loan_ref_req.product_type = "R1"
        self.loan_ref_req.save()
        self.covid_loan_refinancing_sms.sms_client = MagicMock()
        self.covid_loan_refinancing_sms._send_approved_all_product()
        self.covid_loan_refinancing_sms.sms_client.loan_refinancing_sms.assert_called_once_with(
            self.loan_ref_req,
            "{}, terima kasih utk pengajuan program keringanan JULO. " \
            "Bayar {} sebelum tgl {} utk aktivasi".format(
                self.loan_ref_req.loan.application.first_name_only,
                display_rupiah(self.loan_ref_req.last_prerequisite_amount),
                format_date(
                    self.loan_ref_req.first_due_date, 'd MMMM yyyy', locale='id_ID'
                )
            ),
            "approved_offer_first_sms"
        )

    def test_reminder_minus_2_not_campaign(self):
        # loan refinancing request is R3 not special campaign
        self.loan_ref_req.product_type = "R3"
        self.loan_ref_req.save()
        self.covid_loan_refinancing_sms._send_sms_with_validation = MagicMock()
        self.covid_loan_refinancing_sms._reminder_minus_2_all_product()
        self.covid_loan_refinancing_sms._send_sms_with_validation.assert_called_once_with(
            dict(
                robocall=("approved_first_robocall_alloffers",),
                pn=("approved_offer_first_pn",),
                email=("approved_first_email_R4", "approved_first_email_R4_b5")
            ),
            "approved_offer_second_sms",
            "{}, penawaran program keringanan JULO Anda berakhir dlm 2 hari. " \
            "Bayar {} sebelum {}" \
                .format(
                    self.loan_ref_req.loan.application.first_name_with_title,
                    display_rupiah(self.loan_ref_req.last_prerequisite_amount),
                    format_date(self.loan_ref_req.first_due_date, 
                                'd MMMM yyyy', locale='id_ID'))
        )

    def test_reminder_minus_1_not_campaign(self):
        # loan refinancing request is R4 not special campaign
        self.loan_ref_req.product_type = "R4"
        self.loan_ref_req.save()
        self.covid_loan_refinancing_sms._send_sms_with_validation = MagicMock()
        self.covid_loan_refinancing_sms._reminder_minus_1_all_product()
        self.covid_loan_refinancing_sms._send_sms_with_validation.assert_called_once_with(
            dict(
                robocall=("approved_first_robocall_alloffers",),
                pn=("offerselected_second_PN_R1R2R3R4",),
                email=("approved_second_email_R4", "approved_second_email_R4_b5")
            ),
            "approved_offer_third_sms",
            "{}, penawaran program keringanan JULO Anda berakhir BESOK. " \
            "Bayar {} sebelum {}" \
                .format(
                    self.loan_ref_req.loan.application.first_name_with_title,
                    display_rupiah(self.loan_ref_req.last_prerequisite_amount),
                    format_date(self.loan_ref_req.first_due_date, 
                                'd MMMM yyyy', locale='id_ID'))
        )

    def test_send_approved_sms_campaign(self):
        # loan refinancing request is R1 special campaign
        self.loan_ref_req.product_type = "R1"
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at=(datetime.today() + timedelta(days=2)).date()
        )
        self.covid_loan_refinancing_sms.sms_client = MagicMock()
        self.assertIsNone(self.covid_loan_refinancing_sms._send_approved_all_product())
        # self.covid_loan_refinancing_sms.sms_client.loan_refinancing_sms.assert_called_once_with(
        #     self.loan_ref_req,
        #     '{}, Ingin merdeka dr pinjaman JULO? Bayar {} sebelum tgl {}, '
        #     'hutang 100% LUNAS!'.format(
        #         self.loan_ref_req.loan.application.first_name_only,
        #         display_rupiah(self.loan_ref_req.last_prerequisite_amount),
        #         format_date(
        #             self.loan_ref_req.first_due_date, 'd MMMM yyyy', locale='id_ID'
        #         )
        #     ),
        #     "approved_offer_first_sms"
        # )

    def test_reminder_minus_2_campaign(self):
        # loan refinancing request is R3 special campaign
        self.loan_ref_req.product_type = "R3"
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at = (datetime.today() + timedelta(days=2)).date()
        )
        self.covid_loan_refinancing_sms._send_sms_with_validation = MagicMock()
        self.assertIsNone(self.covid_loan_refinancing_sms._reminder_minus_2_all_product())
        # self.covid_loan_refinancing_sms._send_sms_with_validation.assert_called_once_with(
        #     dict(
        #         robocall=("approved_first_robocall_alloffers",),
        #         pn=("approved_offer_first_pn",),
        #         email=("approved_first_email_R4", "approved_first_email_R4_b5")
        #     ),
        #     "approved_offer_second_sms",
        #     "{first_name}, Selangkah lagi utk merdeka dr hutang! Bayar " \
        #     "{prerequisite_amount} sebelum tgl {offer_expiry_date}, " \
        #     "hutang 100% LUNAS!".format(
        #         first_name=self.loan_ref_req.loan.application.first_name_only,
        #         prerequisite_amount=display_rupiah(
        #             self.loan_ref_req.last_prerequisite_amount),
        #         offer_expiry_date=format_date(
        #             self.loan_ref_req.first_due_date, 'd MMMM yyyy', locale='id_ID'))
        # )

    def test_reminder_minus_1_campaign(self):
        # loan refinancing request is R4 special campaign
        self.loan_ref_req.product_type = "R4"
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at=(datetime.today() + timedelta(days=2)).date()
        )
        self.covid_loan_refinancing_sms._send_sms_with_validation = MagicMock()
        self.assertIsNone(self.covid_loan_refinancing_sms._reminder_minus_1_all_product())
        # self.covid_loan_refinancing_sms._send_sms_with_validation.assert_called_once_with(
        #     dict(
        #         robocall=("approved_first_robocall_alloffers",),
        #         pn=("offerselected_second_PN_R1R2R3R4",),
        #         email=("approved_second_email_R4", "approved_second_email_R4_b5")
        #     ),
        #     "approved_offer_third_sms",
        #     "{first_name}, KESEMPATAN TERAKHIR! Segera bayar " \
        #                   "{prerequisite_amount} sebelum {offer_expiry_date} " \
        #                   "& siap u/ merdeka dr hutang!".format(
        #             first_name=self.loan_ref_req.loan.application.first_name_only,
        #             prerequisite_amount=display_rupiah(
        #                 self.loan_ref_req.last_prerequisite_amount),
        #             offer_expiry_date=format_date(
        #                 self.loan_ref_req.first_due_date, 'd MMMM yyyy', locale='id_ID'
        #     ))
        # )


class TestCovidLoanRefinancingPN(TestCase):
    def setUp(self):
        self.loan_ref_req = LoanRefinancingRequestFactory(product_type="R4")
        self.covid_loan_refinancing_pn = CovidLoanRefinancingPN(self.loan_ref_req)

    def test_send_approved_pn(self):
        # loan refinancing request is R4 special campaign
        self.loan_ref_req.product_type = "R4"
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at=(datetime.today() + timedelta(days=2)).date()
        )
        self.covid_loan_refinancing_pn.pn_client = MagicMock()
        self.covid_loan_refinancing_pn._send_approved_all_product()
        self.covid_loan_refinancing_pn.pn_client.loan_refinancing_notification.\
            assert_called_once_with(
            self.loan_ref_req,
            {
                "title": CohortCampaignPN.SUBJECT_R4_1,
                "image_url": "{}{}".\
                    format(self.covid_loan_refinancing_pn.base_image_url_campaign,
                           CohortCampaignPN.IMAGE_URL_R4_1),
                "body": CohortCampaignPN.MESSAGE_R4_1,
            },
            CohortCampaignPN.TEMPLATE_CODE_R4_1
        )

    def test_reminder_minus_2(self):
        # loan refinancing request is R4 special campaign
        self.loan_ref_req.product_type = "R4"
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at=(datetime.today() + timedelta(days=2)).date()
        )
        self.covid_loan_refinancing_pn.pn_client = MagicMock()
        self.covid_loan_refinancing_pn._reminder_minus_2_all_product()
        self.covid_loan_refinancing_pn.pn_client.loan_refinancing_notification.\
            assert_called_once_with(
            self.loan_ref_req,
            {
                "title": CohortCampaignPN.SUBJECT_R4_2,
                "image_url": "{}{}".\
                    format(self.covid_loan_refinancing_pn.base_image_url_campaign,
                           CohortCampaignPN.IMAGE_URL_R4_2),
                "body": CohortCampaignPN.MESSAGE_R4_2,
            },
            CohortCampaignPN.TEMPLATE_CODE_R4_2
        )

    def test_reminder_minus_1(self):
        # loan refinancing request is R4 special campaign
        self.loan_ref_req.product_type = "R4"
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at=(datetime.today() + timedelta(days=2)).date()
        )
        self.covid_loan_refinancing_pn.pn_client = MagicMock()
        self.covid_loan_refinancing_pn._reminder_minus_1_all_product()
        self.covid_loan_refinancing_pn.pn_client.loan_refinancing_notification.\
            assert_called_once_with(
            self.loan_ref_req,
            {
                "title": CohortCampaignPN.SUBJECT_R4_3,
                "image_url": "{}{}".\
                    format(self.covid_loan_refinancing_pn.base_image_url_campaign,
                           CohortCampaignPN.IMAGE_URL_R4_3),
                "body": CohortCampaignPN.MESSAGE_R4_3,
            },
            CohortCampaignPN.TEMPLATE_CODE_R4_3
        )

    def test_send_requested_status_campaign_pn(self):
        # loan refinancing request except R4 offer special campaign
        self.loan_ref_req.status = 'Requested'
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at=(datetime.today() + timedelta(days=2)).date()
        )
        self.covid_loan_refinancing_pn.pn_client = MagicMock()
        self.covid_loan_refinancing_pn._send_requested_status_campaign_pn()
        self.covid_loan_refinancing_pn.pn_client.loan_refinancing_notification.\
            assert_called_once_with(
            self.loan_ref_req,
            {
                "title": CohortCampaignPN.SUBJECT_OTHER_REFINANCING_1,
                "body": CohortCampaignPN.MESSAGE_OTHER_REFINANCING_1,
                "image_url": "{}pn_program_berkah_r6_1.png".\
                    format(self.covid_loan_refinancing_pn.base_image_url_campaign)
            },
            CohortCampaignPN.TEMPLATE_CODE_OTHER_REFINANCING_1
        )

    def test_send_requested_status_campaign_reminder_minus_2(self):
        # loan refinancing request except R4 offer special campaign
        self.loan_ref_req.status = 'Requested'
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at=(datetime.today() + timedelta(days=2)).date()
        )
        self.covid_loan_refinancing_pn.pn_client = MagicMock()
        self.covid_loan_refinancing_pn._send_requested_status_campaign_reminder_minus_2()
        self.covid_loan_refinancing_pn.pn_client.loan_refinancing_notification.\
            assert_called_once_with(
            self.loan_ref_req,
            {
                "title": CohortCampaignPN.SUBJECT_OTHER_REFINANCING_2,
                "body": CohortCampaignPN.MESSAGE_OTHER_REFINANCING_2,
                "image_url": "{}pn_program_berkah_r6_2.png".\
                    format(self.covid_loan_refinancing_pn.base_image_url_campaign)
            },
            CohortCampaignPN.TEMPLATE_CODE_OTHER_REFINANCING_2
        )

    def test_send_requested_status_campaign_reminder_minus_1(self):
        # loan refinancing request except R4 offer special campaign
        self.loan_ref_req.status = 'Requested'
        self.loan_ref_req.save()
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at=(datetime.today() + timedelta(days=2)).date()
        )
        self.covid_loan_refinancing_pn.pn_client = MagicMock()
        self.covid_loan_refinancing_pn._send_requested_status_campaign_reminder_minus_1()
        self.covid_loan_refinancing_pn.pn_client.loan_refinancing_notification.\
            assert_called_once_with(
            self.loan_ref_req,
            {
                "title": CohortCampaignPN.SUBJECT_OTHER_REFINANCING_3,
                "body": CohortCampaignPN.MESSAGE_OTHER_REFINANCING_3,
                "image_url": "{}pn_program_berkah_r6_3.png".\
                    format(self.covid_loan_refinancing_pn.base_image_url_campaign)
            },
            CohortCampaignPN.TEMPLATE_CODE_OTHER_REFINANCING_3
        )


class TestJ1RefinancingComms(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(id=222344)
        self.account = AccountFactory(
            customer=self.customer
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account
        )
        self.loan = LoanFactory(
            account=self.account, is_restructured=True)
        self.account_payment = AccountPaymentFactory(
            account=self.account, is_restructured=False)
        self.loan_refinancing_request_j1 = LoanRefinancingRequestFactory(
            account=self.account, loan=None, request_date=datetime.today()
        )
        self.payment_method = PaymentMethodFactory(
            customer=self.customer, is_primary=True,
        )
        self.covid_loan_email_refinancing = CovidLoanRefinancingEmail(
            self.loan_refinancing_request_j1
        )

    @patch.object(JuloEmailClient, 'email_covid_refinancing_activated_for_all_product')
    def test_send_email_send_activated_email_r1_r2_r3_j1(self, mock_email_client):
        mock_email_client.return_value = \
            (202, {'X-Message-Id': 'activated_offer_refinancing_email'},
             'dummy_subject', 'dummy_message', 'activated_offer_refinancing_email')
        self.covid_loan_email_refinancing._send_activated_email_r1()
        self.covid_loan_email_refinancing._send_activated_email_r2()
        self.covid_loan_email_refinancing._send_activated_email_r3()
        email_history = EmailHistory.objects.filter(
            customer=self.account.customer,
            template_code='activated_offer_refinancing_email').count()
        assert email_history == 3

    @patch.object(JuloEmailClient, 'email_refinancing_offer_selected')
    def test_send_email_send_offer_selected_refinancing_j1_r1(self, mock_email_client):
        mock_email_client.return_value = (
            202,
            {'X-Message-Id': 'offerselected_first_email_R1'},
            'dummy_subject',
            'dummy_message',
            'offerselected_first_email_R1',
        )
        self.covid_loan_email_refinancing._send_offer_selected_refinancing()
        email_history = EmailHistory.objects.filter(
            customer=self.account.customer, template_code='offerselected_first_email_R1'
        ).count()
        assert email_history > 0

    @patch.object(JuloEmailClient, 'email_refinancing_offer_selected')
    def test_send_email_send_offer_selected_refinancing_j1_r2_r3(self, mock_email_client):
        mock_email_client.return_value = (
            202,
            {'X-Message-Id': 'offerselected_first_email_R2R3'},
            'dummy_subject',
            'dummy_message',
            'offerselected_first_email_R2R3',
        )
        self.covid_loan_email_refinancing._send_offer_selected_refinancing()
        email_history = EmailHistory.objects.filter(
            customer=self.account.customer, template_code='offerselected_first_email_R2R3'
        ).count()
        assert email_history > 0

    @skip('obsolete, since the template is now changed')
    @patch.object(JuloEmailClient, 'email_refinancing_offer_selected')
    def test_send_email_send_offer_selected_refinancing_j1(self, mock_email_client):
        mock_email_client.return_value = \
            (202, {'X-Message-Id': 'offerselected_first_email_R1R2R3'},
             'dummy_subject', 'dummy_message', 'offerselected_first_email_R1R2R3')
        self.covid_loan_email_refinancing._send_offer_selected_refinancing()
        email_history = EmailHistory.objects.filter(
            customer=self.account.customer,
            template_code='offerselected_first_email_R1R2R3').count()
        assert email_history > 0

    @patch.object(JuloEmailClient, 'email_refinancing_offer_selected')
    def test_send_email_send_offer_selected_refinancing_j1(self, mock_email_client):
        mock_email_client.return_value = \
            (202, {'X-Message-Id': 'offerselected_third_email'},
             'dummy_subject', 'dummy_message', 'offerselected_third_email')
        self.covid_loan_email_refinancing.send_offer_selected_minus_1_email_reminder()
        email_history = EmailHistory.objects.filter(
            customer=self.account.customer,
            template_code='offerselected_third_email').count()
        assert email_history > 0

    @patch("juloserver.loan_refinancing.services.refinancing_product_related.get_max_tenure_extension_r1")
    @patch.object(JuloEmailClient, 'email_covid_refinancing_approved_for_all_product')
    def test_send_email_send_offer_selected_refinancing_j1(self, mock_email_client, mock_r1_max_tenore):
        mock_email_client.return_value = \
            (202, {'X-Message-Id': 'approved_first_email_R1R2R3'},
             'dummy_subject', 'dummy_message', 'approved_first_email_R1R2R3')
        mock_r1_max_tenore.return_value = self.loan.loan_duration
        self.covid_loan_email_refinancing._send_approved_email_r1()
        self.covid_loan_email_refinancing._send_approved_email_r2()
        self.covid_loan_email_refinancing._send_approved_email_r3()
        email_history = EmailHistory.objects.filter(
            customer=self.account.customer,
            template_code='approved_first_email_R1R2R3').count()
        assert email_history == 3
        # send_offer_selected_minus_1_email_reminder
        # _send_approved_email_r1
        # _send_approved_email_r2
        # _send_approved_email_r3
