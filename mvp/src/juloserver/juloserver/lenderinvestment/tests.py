from django.test import TestCase
from django.utils import timezone
import pytz
import mock
from juloserver.julo.tests.factories import LoanFactory
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from .models import (
    MintosLoanListStatus,
    SbMintosBuybackSendin,
    MintosReport,
    MintosQueueStatus,
    SbMintosPaymentSendin,
    ExchangeRate,
)
from .tasks import (
    rebuy_loan_tasks,
    update_mintos_loan_from_report,
    send_all_data_loan_to_mintos,
    payment_sendin_tasks,
    get_loans_tasks,
    loan_sendin_tasks,
    get_forex_rate_idr_to_eur,
)
from .services import (
    round_down,
    idr_to_eur,
    convert_all_to_uer,
    recalculate_rounding,
    insert_mintos_loan_list_status,
    update_mintos_loan_list_status,
    get_mintos_queue_data,
    upsert_mintos_report,
)
from datetime import datetime
from requests.models import Response


class TestLenderInvestmentTask(TestCase):

    def setUp(self):
        self.loan = LoanFactory()
        self.mintos_loan_list_status = MintosLoanListStatus.objects.create(
            application_xid=self.loan.application.application_xid, mintos_loan_id=12345,
            mintos_send_in_ts=datetime.now(), status='finished'
        )
        self.sb_mintos_buy_back_send_in = SbMintosBuybackSendin.objects.create(
            buyback_date=datetime.now(),
            application_xid=self.loan.application.application_xid
        )
        self.mintos_report = MintosReport.objects.create(
            filename='test', email_date=datetime.now())
        self.mintos_queue_status = MintosQueueStatus.objects.create(
            queue_status=False, queue_type='loan_sendin'
        )
        today = timezone.localtime(timezone.now()).replace(
            hour=0, minute=0, second=0, microsecond=0)
        self.sb_mintos_payment_send_in = SbMintosPaymentSendin.objects.create(
            loan_id=self.loan.id, cdate=today.replace(tzinfo=pytz.UTC), payment_date=datetime.now()
        )
        ExchangeRate.objects.create(currency="EUR", sell=1, buy=1, rate=1, source="bca")

    @mock.patch('juloserver.lenderinvestment.tasks.mintos_client.rebuy_loan')
    @mock.patch('juloserver.lenderinvestment.tasks.mintos_client.get_loans')
    def test_rebuy_loan_tasks(self, mock_get_loans, mock_rebuy_loan):
        mock_rebuy_loan.return_value = {}
        data = {'data': {'loan': {'id': self.mintos_loan_list_status.mintos_loan_id, 'status': 'active'}}}
        mock_get_loans.return_value = data
        response = rebuy_loan_tasks(self.loan.id)
        self.assertIsNone(response)

    def test_update_mintos_loan_from_report(self):
        data = dict(mintos_id=self.mintos_loan_list_status.mintos_loan_id, loan_status='active')
        response = update_mintos_loan_from_report(data, self.mintos_report.id)
        self.assertIsNone(response)

    @mock.patch('juloserver.lenderinvestment.tasks.loan_sendin_tasks')
    def test_send_all_data_loan_to_mintos(self, mock_loan_sendin_tasks):
        response = send_all_data_loan_to_mintos()
        self.assertIsNone(response)

    @mock.patch('juloserver.lenderinvestment.tasks.mintos_client.payment_sendin')
    def test_payment_sendin_tasks(self, mock_payment_sendin):
        response = payment_sendin_tasks(self.loan.id, 1)
        self.assertIsNone(response)
        self.sb_mintos_payment_send_in.payment_schedule_number = 1
        self.sb_mintos_payment_send_in.save()
        mock_payment_sendin.return_value = {'success': True}, {'payment_date': datetime.now(), 'loan_id': self.loan.id}
        response = payment_sendin_tasks(self.loan.id, 1)
        self.assertIsNone(response)
        self.assertIsNone(payment_sendin_tasks(-1, 0))

    @mock.patch('juloserver.lenderinvestment.tasks.mintos_client.get_loans')
    def test_get_loans_tasks(self, mock_get_loans):
        mock_get_loans.return_value = {}
        response = get_loans_tasks(self.loan.id)
        self.assertIsNone(response)

    @mock.patch('juloserver.lenderinvestment.tasks.mintos_client.loan_sendin')
    def test_loan_sendin_tasks(self, mock_loan_sendin):
        mock_loan_sendin.return_value = {}
        response = loan_sendin_tasks(self.loan.id)
        self.assertIsNone(response)
        self.assertIsNone(loan_sendin_tasks(-1))

    @mock.patch('requests.get')
    def test_get_forex_rate_idr_to_eur(self, mock_get):
        the_response = Response()
        html = """<table id="ctl00_PlaceHolderMain_biWebKursTransaksiBI_GridView2">
            <tr><td>EUR</td><td>10</td><td>10</td><td>10</td></tr>
            <tr><td>EUR</td><td>10</td><td>10</td><td>10</td></tr>
            <tr><td>EUR</td><td>20</td><td>10</td><td>10</td></tr>
            <tr><td>EUR</td><td>30</td><td>10</td><td>10</td></tr>
            </table>"""
        the_response._content = html
        mock_get.return_value = the_response
        response = get_forex_rate_idr_to_eur()
        self.assertIsNone(response)

    def test_round_down(self):
        assert round_down(2) == 2.0

    def test_idr_to_eur(self):
        assert idr_to_eur(1000) == 1000

    def test_convert_all_to_uer(self):
        items = [{"amount": 1000}, {"amount": 2000}, {"amount": 3000}]
        new_items = convert_all_to_uer(items, ['amount'], None)
        assert items == new_items

    def test_recalculate_rounding(self):
        items = [{"principal_amount":1000}, {"principal_amount":2000}, {"principal_amount":3000}]
        new_items = [
            {"principal_amount": 1000.34},
            {"principal_amount": 2000.33},
            {"principal_amount": 3000.33}
        ]
        new_recalculate_rounding = recalculate_rounding(
            idr_to_eur(6001),
            convert_all_to_uer(items, ['principal_amount'], None)
        )
        assert new_recalculate_rounding == new_items

    def test_insert_mintos_loan_list_status(self):
        FeatureSetting.objects.create(
            is_active=True,
            feature_name=FeatureNameConst.MINTOS_INTEREST_RATE,
            parameters={"interest_rate_percent": 1},
        )

        response = dict(
            data=dict(
                loan=dict(mintos_id="23729383772",status="Decision"),
                client=dict(id="10029383772"),
            )
        )
        insert_mintos_loan_list_status(response)
        assert MintosLoanListStatus.objects.filter(
            mintos_loan_id=23729383772).exists() == True

    def test_update_mintos_loan_list_status(self):
        loan_list_status = MintosLoanListStatus.objects.create(
            mintos_loan_id=23729383771,
            status="Decision",
            mintos_send_in_ts=timezone.localtime(timezone.now()),
        )
        response = dict(
            data=dict(
                loan=dict(
                    id=23729383771,
                    status="Active",
                )
            )
        )
        update_mintos_loan_list_status(response)
        loan_list_status.refresh_from_db()
        assert loan_list_status.status == "Active"

    def test_get_mintos_queue_data(self):
        self.mintos_queue_status.queue_status = True
        self.mintos_queue_status.save()
        assert len(get_mintos_queue_data()) == 1

    def test_upsert_mintos_report(self):
        response = upsert_mintos_report("newfile.xls", timezone.localtime(timezone.now()), None)
        assert response["exists"] == False

        response = upsert_mintos_report("newfile.xls", timezone.localtime(timezone.now()), None)
        assert response["exists"] == True
