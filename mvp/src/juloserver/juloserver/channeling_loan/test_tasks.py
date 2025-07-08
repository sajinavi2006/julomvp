from unittest.mock import call
import mock

from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.channeling_loan.factories import ChannelingLoanHistoryFactory
from juloserver.julo.models import StatusLookup
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    LoanFactory,
    ApplicationFactory,
    CustomerFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
)
from juloserver.moengage.constants import (
    MoengageLoanStatusEventType,
    MoengageEventType,
)
from juloserver.moengage.models import MoengageUpload
from juloserver.moengage.services.data_constructors import construct_data_for_change_lender
from juloserver.moengage.services.use_cases import \
    send_user_attributes_to_moengage_for_change_lender


class TestTaskSendToMoEngageForChangeLender(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.old_lender = LenderCurrentFactory()
        self.lender = LenderCurrentFactory()
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            application=self.application,
            lender=self.lender,
        )
        self.channeling_loan_history = ChannelingLoanHistoryFactory(
            loan=self.loan,
            old_lender=self.old_lender,
            new_lender=self.lender,
        )

    def test_construct_data_for_change_lender(self):
        user_attributes, event_data = construct_data_for_change_lender(
            event_type=MoengageLoanStatusEventType.STATUS_220,
            loan=self.loan,
            customer_id=self.customer.id,
        )

        self.assertEqual(
            user_attributes['attributes']['fullname_with_title'],
            self.application.fullname_with_title
        )

        event_attributes = event_data['actions'][0]['attributes']
        self.assertEqual(event_attributes['current_lender_id'], self.old_lender.id)
        self.assertEqual(
            event_attributes['current_lender_display_name'],
            self.old_lender.lender_display_name
        )
        self.assertEqual(event_attributes['new_lender_id'], self.lender.id)
        self.assertEqual(
            event_attributes['new_lender_display_name'],
            self.lender.lender_display_name
        )
        self.assertEqual(
            event_attributes['transfer_date'],
            timezone.localtime(self.channeling_loan_history.cdate).strftime(
                "%b %d, %Y, %I:%M %p"
            )
        )

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage')
    @mock.patch('juloserver.moengage.services.use_cases.construct_data_for_change_lender')
    def test_send_user_attributes_to_moengage_for_change_lender_success(
            self, mock_construct_event_data, mock_send_to_moengage
    ):
        self.loan.loan_status = StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        self.loan.save()
        user_attributes = {'123': 123}
        event_data = {'456': 456}
        mock_construct_event_data.return_value = user_attributes, event_data

        send_user_attributes_to_moengage_for_change_lender(loan_id=self.loan.id)

        mock_construct_event_data.assert_called_once_with(
            event_type='BEx220_channeling_loan',
            loan=self.loan,
            customer_id=self.customer.id,
        )

        moengage_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.BEx220_CHANNELING_LOAN,
            loan_id=self.loan.id,
        ).last()
        mock_send_to_moengage.delay.assert_has_calls([
            call([moengage_upload.id], [user_attributes, event_data]),
        ])

    @mock.patch('juloserver.moengage.services.use_cases.construct_data_for_change_lender')
    def test_send_user_attributes_to_moengage_for_change_lender_fail_due_wrong_loan_status(
            self, mock_construct_event_data
    ):
        self.loan.loan_status = StatusLookup.objects.get(pk=LoanStatusCodes.INACTIVE)
        self.loan.save()

        send_user_attributes_to_moengage_for_change_lender(loan_id=self.loan.id)

        mock_construct_event_data.assert_not_called()
