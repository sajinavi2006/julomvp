from mock import patch

from django.test import TestCase

from juloserver.julo.tests.factories import CustomerFactory, PartnerFactory
from juloserver.qris.constants import QrisLinkageStatus
from juloserver.qris.tests.factories import (
    QrisPartnerLinkageFactory,
    QrisPartnerLinkageHistoryFactory,
)


class TestQrisLinkagePostSave(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.partner = PartnerFactory(name='amar')
        self.linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            status=QrisLinkageStatus.REQUESTED,
        )

    @patch('juloserver.qris.signals.send_qris_linkage_status_change_to_moengage')
    @patch('juloserver.qris.signals.execute_after_transaction_safely')
    def test_sending_moengage_linkage_status_event(
        self, mock_execuate_after_transaction, mock_send
    ):
        # saving object but not history => not called
        self.linkage.status = "hello"
        self.linkage.save()

        mock_execuate_after_transaction.assert_not_called()

        # history but for different field => not called
        QrisPartnerLinkageHistoryFactory(
            qris_partner_linkage=self.linkage,
            field='not_status',
            value_old=QrisLinkageStatus.REQUESTED,
            value_new=QrisLinkageStatus.FAILED,
        )
        mock_execuate_after_transaction.assert_not_called()

        # changing `status` field => called
        QrisPartnerLinkageHistoryFactory(
            qris_partner_linkage=self.linkage,
            field='status',
            value_old=QrisLinkageStatus.REQUESTED,
            value_new=QrisLinkageStatus.FAILED,
        )
        mock_execuate_after_transaction.assert_called_once()

        # get lambda func from mock, first argument
        lambda_func = mock_execuate_after_transaction.call_args[0][0]
        lambda_func()

        # make sure it is called
        mock_send.delay.assert_called_once_with(
            linkage_id=self.linkage.id,
        )
