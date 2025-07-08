from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from mock import patch

from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import ProductLine
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import ApplicationFactory, LoanFactory, PaymentMethodFactory
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingMainReason, LoanRefinancingSubReason
from juloserver.loan_refinancing.tasks.notification_tasks import (
    notify_eligible_customers_for_loan_refinancing,
    send_loan_refinancing_email, send_loan_refinancing_request_email,
    send_loan_refinancing_success_email, send_sms_covid_refinancing_offer_selected,
    send_sms_covid_refinancing_approved, send_sms_covid_refinancing_activated,
    send_sms_covid_refinancing_reminder_offer_selected_2,
    send_sms_covid_refinancing_reminder_offer_selected_1,
    send_sms_covid_refinancing_reminder_to_pay_minus_2,
    send_sms_covid_refinancing_reminder_to_pay_minus_1, send_proactive_sms_reminder,
    send_pn_covid_refinancing_offer_selected, send_pn_covid_refinancing_approved,
    send_pn_covid_refinancing_activated, send_pn_covid_refinancing_reminder_offer_selected_2,
    send_email_covid_refinancing_reminder, send_pn_covid_refinancing_reminder_offer_selected_1,
    send_pn_covid_refinancing_reminder_to_pay_minus_2,
    send_pn_covid_refinancing_reminder_to_pay_minus_1, send_proactive_pn_reminder,
    send_email_refinancing_offer_selected_minus_2,
    send_all_refinancing_request_reminder_offer_selected_2,
    send_all_proactive_refinancing_pn_reminder_8am,
    send_all_refinancing_request_reminder_offer_selected_1,
    send_robocall_refinancing_request_reminder_offer_selected_3,
    send_robocall_refinancing_request_approved_selected_3)
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory, \
    CollectionOfferExtensionConfigurationFactory, LoanRefinancingFactory


class TestNotificationTask2(TestCase):
    def setUp(self):
        mtl_product = ProductLine.objects.get(pk=ProductLineCodes.MTL1)
        application = ApplicationFactory(product_line=mtl_product)
        self.customer = application.customer
        loan = LoanFactory(application=application, customer=self.customer)
        PaymentMethodFactory(customer=application.customer, is_primary=True, loan=loan)

        self.loan_ref_req = LoanRefinancingRequestFactory(
            product_type="R4",
            loan=loan,
            expire_in_days=5
        )

        self.procative_loan_ref_req = LoanRefinancingRequestFactory(
            product_type="R1",
            loan=loan,
            expire_in_days=5
        )

        self.loan_ref = LoanRefinancingFactory(
            loan=self.loan_ref_req.loan,
            refinancing_request_date=timezone.now().date(),
            refinancing_active_date=timezone.now().date(),
            loan_refinancing_main_reason=LoanRefinancingMainReason.objects.last(),
            loan_refinancing_sub_reason=LoanRefinancingSubReason.objects.last(),
            tenure_extension=9
        )

        self.coll_ext_conf = CollectionOfferExtensionConfigurationFactory(
            product_type='R4',
            remaining_payment=2,
            max_extension=3,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )

    @patch('juloserver.loan_refinancing.tasks.notification_tasks.get_eligible_customers')
    @patch('juloserver.loan_refinancing.tasks.notification_tasks.send_loan_refinancing_email')
    @patch('juloserver.loan_refinancing.tasks.notification_tasks.FeatureSetting.objects')
    def test_notify_eligible_customers_for_loan_refinancing(self, mocked_feature_setting,
                                                            mocked_task,
                                                            mocked_customer):
        mocked_feature_setting.filter.return_value.exists.return_value = False
        notify_eligible_customers_for_loan_refinancing()

        mocked_feature_setting.filter.return_value.exists.return_value = True
        mocked_customer.return_value = [self.customer]
        notify_eligible_customers_for_loan_refinancing()
        assert mocked_task.delay.called

    @patch('juloserver.loan_refinancing.tasks.notification_tasks.get_julo_email_client')
    def test_send_loan_refinancing_email(self, mocked_email_cl):
        # customer not found
        with self.assertRaises(JuloException):
            send_loan_refinancing_email(666666666666)

        mocked_email_cl.return_value.email_loan_refinancing_eligibility.return_value = \
            (202, {'X-Message-Id': 'covid_refinancing_activated123'},
            'dummy_subject', 'dummy_message')
        send_loan_refinancing_email(self.customer.id)

    @patch('juloserver.loan_refinancing.tasks.notification_tasks.get_julo_email_client')
    @patch('juloserver.loan_refinancing.services.loan_related.get_unpaid_payments')
    @patch('juloserver.loan_refinancing.services.loan_related.get_loan_refinancing_request_info')
    @patch('juloserver.loan_refinancing.services.refinancing_product_related.'
           'get_covid_loan_refinancing_request')
    def test_send_loan_refinancing_request_email(self,
                                                 mocked_covid_loan_ref_info,
                                                 mocked_loan_ref_info,
                                                 mocked_get_payments,
                                                 mocked_email_cl
                                                 ):
        mocked_covid_loan_ref_info.return_value = self.loan_ref_req
        mocked_loan_ref_info.return_value = self.loan_ref
        mocked_get_payments.return_value = self.loan_ref_req.loan.payment_set.all()
        mocked_email_cl.return_value.email_loan_refinancing_request.return_value = \
            (202, {'X-Message-Id': 'covid_refinancing_activated123'},
             'dummy_subject', 'dummy_message')

        send_loan_refinancing_request_email(self.loan_ref_req.loan.id)

        mocked_email_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.tasks.notification_tasks.get_julo_email_client')
    @patch('juloserver.loan_refinancing.services.loan_related.get_loan_refinancing_request_info')
    def test_send_loan_refinancing_success_email(self,
                                                 mocked_covid_loan_ref_info,
                                                 mocked_email_cl
                                                 ):
        mocked_covid_loan_ref_info.return_value = self.loan_ref_req
        mocked_email_cl.return_value.email_loan_refinancing_success.return_value = \
            (202, {'X-Message-Id': 'covid_refinancing_activated123'},
             'dummy_subject', 'dummy_message')

        send_loan_refinancing_success_email(self.loan_ref_req.loan.id)

        mocked_email_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_refinancing_offer_selected_minus_2(self, mocked_email_cl):
        mocked_email_cl.return_value.email_refinancing_offer_selected.return_value = \
            (202, {'X-Message-Id': 'covid_refinancing_activated123'},
             'dummy_subject', 'dummy_message', 'dummy_template')

        send_email_refinancing_offer_selected_minus_2(self.loan_ref_req.id)
        mocked_email_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_reminder(self, mocked_email_cl):
        mocked_email_cl.return_value.email_reminder_refinancing.return_value = \
            (202, {'X-Message-Id': 'covid_refinancing_activated123'},
             'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_covid_refinancing_reminder(self.procative_loan_ref_req.id)
        mocked_email_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_sms_client')
    @patch('juloserver.loan_refinancing.services.notification_related.check_template_bucket_5')
    def test_send_sms_covid_refinancing_offer_selected(self, mocked_check_b5, mocked_sms_cl):
        mocked_check_b5.return_value = False, "offerselected_first_sms_R1R2R3R4"
        mocked_sms_cl.return_value.loan_refinancing_sms.return_value = True
        send_sms_covid_refinancing_offer_selected(self.loan_ref_req.id)
        mocked_sms_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_sms_client')
    @patch('juloserver.loan_refinancing.services.notification_related.check_template_bucket_5')
    def test_send_sms_covid_refinancing_approved(self, mocked_check_b5, mocked_sms_cl):
        mocked_sms_cl.return_value.loan_refinancing_sms.return_value = True
        mocked_check_b5.return_value = False, "approved_offer_first_sms"
        send_sms_covid_refinancing_approved(self.loan_ref_req.id)
        mocked_sms_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_sms_client')
    def test_send_sms_covid_refinancing_activated(self, mocked_sms_cl):
        mocked_sms_cl.return_value.loan_refinancing_sms.return_value = True
        send_sms_covid_refinancing_activated(self.loan_ref_req.id)
        mocked_sms_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_sms_client')
    @patch('juloserver.loan_refinancing.services.notification_related.check_template_bucket_5')
    def test_send_sms_covid_refinancing_reminder_offer_selected_2(self, mocked_check_b5, mocked_sms_cl):
        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_ref_req.save()
        mocked_sms_cl.return_value.loan_refinancing_sms.return_value = True
        mocked_check_b5.return_value = False, "offerselected_second_sms_R1R2R3R4"
        send_sms_covid_refinancing_reminder_offer_selected_2(self.loan_ref_req.id)
        mocked_sms_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_sms_client')
    @patch('juloserver.loan_refinancing.services.notification_related.check_template_bucket_5')
    def test_send_sms_covid_refinancing_reminder_offer_selected_1(self, mocked_check_b5, mocked_sms_cl):
        mocked_sms_cl.return_value.loan_refinancing_sms.return_value = True
        mocked_check_b5.return_value = False, "offerselected_second_sms_R1R2R3R4"
        send_sms_covid_refinancing_reminder_offer_selected_1(self.loan_ref_req.id)
        mocked_sms_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_sms_client')
    @patch('juloserver.loan_refinancing.services.notification_related.check_template_bucket_5')
    def test_send_sms_covid_refinancing_reminder_to_pay_minus_2(self, mocked_check_b5, mocked_sms_cl):
        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.approved
        self.loan_ref_req.save()
        mocked_sms_cl.return_value.loan_refinancing_sms.return_value = True
        mocked_check_b5.return_value = False, "offerselected_second_sms_R1R2R3R4"
        send_sms_covid_refinancing_reminder_to_pay_minus_2(self.loan_ref_req.id)
        mocked_sms_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_sms_client')
    @patch('juloserver.loan_refinancing.services.notification_related.check_template_bucket_5')
    def test_send_sms_covid_refinancing_reminder_to_pay_minus_1(self, mocked_check_b5, mocked_sms_cl):
        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.approved
        self.loan_ref_req.save()
        mocked_sms_cl.return_value.loan_refinancing_sms.return_value = True
        mocked_check_b5.return_value = False, "offerselected_second_sms_R1R2R3R4"
        send_sms_covid_refinancing_reminder_to_pay_minus_1(self.loan_ref_req.id)
        mocked_sms_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_sms_client')
    def test_send_proactive_sms_reminder(self, mocked_sms_cl):
        mocked_sms_cl.return_value.loan_refinancing_sms.return_value = True
        self.procative_loan_ref_req.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
        self.procative_loan_ref_req.save()
        send_proactive_sms_reminder(self.procative_loan_ref_req.id, 'status test')
        mocked_sms_cl.assert_called_once()

        self.procative_loan_ref_req.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit
        self.procative_loan_ref_req.save()
        send_proactive_sms_reminder(self.procative_loan_ref_req.id, 'status test')
        self.assertEqual(mocked_sms_cl.call_count, 2)

        self.procative_loan_ref_req.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer
        self.procative_loan_ref_req.save()
        send_proactive_sms_reminder(self.procative_loan_ref_req.id, 'status test')
        self.assertEqual(mocked_sms_cl.call_count, 3)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_pn_client')
    def test_send_pn_covid_refinancing_offer_selected(self, mocked_pn_cl):
        mocked_pn_cl.return_value.loan_refinancing_notification.return_value = True
        send_pn_covid_refinancing_offer_selected(self.procative_loan_ref_req.id)
        mocked_pn_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_pn_client')
    def test_send_pn_covid_refinancing_approved(self, mocked_pn_cl):
        mocked_pn_cl.return_value.loan_refinancing_notification.return_value = True
        send_pn_covid_refinancing_approved(self.procative_loan_ref_req.id)
        mocked_pn_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_pn_client')
    def test_send_pn_covid_refinancing_activated(self, mocked_pn_cl):
        mocked_pn_cl.return_value.loan_refinancing_notification.return_value = True
        send_pn_covid_refinancing_activated(self.procative_loan_ref_req.id)
        mocked_pn_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_pn_client')
    def test_send_pn_covid_refinancing_reminder_offer_selected_2(self, mocked_pn_cl):
        mocked_pn_cl.return_value.loan_refinancing_notification.return_value = True
        send_pn_covid_refinancing_reminder_offer_selected_2(self.procative_loan_ref_req.id)
        mocked_pn_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_pn_client')
    def test_send_pn_covid_refinancing_reminder_offer_selected_1(self, mocked_pn_cl):
        mocked_pn_cl.return_value.loan_refinancing_notification.return_value = True
        send_pn_covid_refinancing_reminder_offer_selected_1(self.procative_loan_ref_req.id)
        mocked_pn_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_pn_client')
    def test_send_pn_covid_refinancing_reminder_to_pay_minus_2(self, mocked_pn_cl):
        self.procative_loan_ref_req.status = CovidRefinancingConst.STATUSES.approved
        self.procative_loan_ref_req.save()
        mocked_pn_cl.return_value.loan_refinancing_notification.return_value = True
        send_pn_covid_refinancing_reminder_to_pay_minus_2(self.procative_loan_ref_req.id)
        mocked_pn_cl.assert_called_once()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_pn_client')
    def test_send_pn_covid_refinancing_reminder_to_pay_minus_1(self, mocked_pn_cl):
        self.procative_loan_ref_req.status = CovidRefinancingConst.STATUSES.approved
        self.procative_loan_ref_req.save()
        mocked_pn_cl.return_value.loan_refinancing_notification.return_value = True
        send_pn_covid_refinancing_reminder_to_pay_minus_1(self.procative_loan_ref_req.id)
        mocked_pn_cl.assert_called_once()

    @override_settings(CELERY_ALWAYS_EAGER=True)
    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_pn_client')
    def test_send_all_proactive_refinancing_pn_reminder_8am(self, mocked_pn_cl):
        mocked_pn_cl.return_value.loan_refinancing_notification.return_value = True
        send_all_proactive_refinancing_pn_reminder_8am()

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_pn_client')
    def test_send_proactive_pn_reminder(self, mocked_pn_cl):
        mocked_pn_cl.return_value.loan_refinancing_notification.return_value = True

        self.procative_loan_ref_req.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
        self.procative_loan_ref_req.save()
        send_proactive_pn_reminder(self.procative_loan_ref_req.id, 'test_status', 3)
        mocked_pn_cl.assert_called_once()

        self.procative_loan_ref_req.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit
        self.procative_loan_ref_req.save()
        send_proactive_pn_reminder(self.procative_loan_ref_req.id, 'test_status', 3)
        self.assertEqual(mocked_pn_cl.call_count, 2)

        self.procative_loan_ref_req.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer
        self.procative_loan_ref_req.save()
        send_proactive_pn_reminder(self.procative_loan_ref_req.id, 'test_status', 3)
        self.assertEqual(mocked_pn_cl.call_count, 3)

    @patch('juloserver.loan_refinancing.services.comms_channels.'
           'send_loan_refinancing_request_reminder_offer_selected_2')
    def test_send_all_refinancing_request_reminder_offer_selected_2(self, mocked_func):
        mocked_func.return_value = True
        send_all_refinancing_request_reminder_offer_selected_2()

    @patch('juloserver.loan_refinancing.services.comms_channels.'
           'send_loan_refinancing_request_reminder_offer_selected_1')
    def test_send_all_refinancing_request_reminder_offer_selected_1(self, mocked_func):
        mocked_func.return_value = True
        send_all_refinancing_request_reminder_offer_selected_1()

    @patch('juloserver.loan_refinancing.services.comms_channels.'
           'send_loan_refinancing_robocall_reminder_minus_3')
    def test_send_robocall_refinancing_request_reminder_offer_selected_3(self, mocked_func):
        mocked_func.return_value = True
        send_robocall_refinancing_request_reminder_offer_selected_3()

    @patch('juloserver.loan_refinancing.services.comms_channels.'
           'send_loan_refinancing_robocall_reminder_minus_3')
    def test_send_robocall_refinancing_request_approved_selected_3(self, mocked_func):
        mocked_func.return_value = True
        send_robocall_refinancing_request_approved_selected_3()
