import json

from mock import patch, ANY

from dateutil.relativedelta import relativedelta

from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from juloserver.account.tests.factories import (
    PartnerFactory,
)

from juloserver.lendeast.constants import LendEastConst

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    FeatureSettingFactory,
    LoanFactory,
    ApplicationFactory,
    CreditScoreFactory,
    LenderFactory,
    CreditMatrixFactory,
    ProductLookupFactory,
)

from juloserver.julo.utils import generate_base64

from juloserver.account.tests.factories import (
    AccountFactory,
)

from .exceptions import LendEastException
from .tasks import (
    collect_loans_for_lendeast,
    construct_loans_information_data
)
from .utils import get_first_day_in_month
from .factories import LendeastDataMonthlyFactory
from .models import LendeastDataMonthly
import pytest


def mock_construct_loans_information_data_func(*arg, **karg):
    construct_loans_information_data(*arg, **karg)


@pytest.mark.skip(reason="Flaky and obsolete")
class TestLendeastAPI(APITestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(feature_name='lendeast_config')
        self.setting.parameters = {'minimum_osp': 18000000, 'page_size': 100}
        self.setting.save()
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(name='lendeast')
        self.token = 'Basic ' + generate_base64(
            "{}, {}".format(LendEastConst.PARTNER_NAME, self.partner.token)
        )
        self.url = "/api/lendeast/v1/loaninformation"

    def test_invalid_credential(self):
        res = self.client.get(self.url)
        assert res.status_code == 401

    def test_empty_data(self,):
        month = timezone.localtime(timezone.now()).date().month
        res = self.client.get(self.url, HTTP_AUTHORIZATION=self.token)
        assert res.status_code == 200


class TestLendeastTask(APITestCase):
    def setUp(self):
        self.partner = PartnerFactory(name='lendeast')
        self.setting = FeatureSettingFactory(feature_name='lendeast_config')
        self.setting.parameters = {'minimum_osp': 30600000, 'page_size': 100}
        self.setting.save()

        self.account = AccountFactory()
        self.app = ApplicationFactory(account=self.account)
        self.app.application_status_id=190
        self.app.save()

        self.product = ProductLookupFactory()
        self.product_axiata = ProductLookupFactory(
        )
        self.product_axiata.product_line_id=195
        self.product_axiata.save()

        self.matrix = CreditMatrixFactory(product=self.product)
        self.credit = CreditScoreFactory(credit_matrix_id=self.matrix.pk)
        self.credit.application_id = self.app.pk
        self.credit.save()
        self.lender = LenderFactory(lender_name='jtp')
        self.token = 'Basic ' + generate_base64(
            "{}, {}".format(LendEastConst.PARTNER_NAME, self.partner.token)
        )
        self.url = "/api/lendeast/v1/loaninformation"

    def test_cron_job_not_enough(self):
        with self.assertRaises(LendEastException) as context:
            collect_loans_for_lendeast()

        assert 'Not enough loan OSP' in str(context.exception)

    @pytest.mark.skip(reason="Flaky and obsolete")
    @patch('juloserver.lendeast.tasks.construct_loans_information_data')
    def test_cron_job(
            self, mock_construct_loans_information_data):

        current_month_year = get_first_day_in_month()
        last_month_year = current_month_year - relativedelta(months=+1)
        data_a = LendeastDataMonthlyFactory(data_date=last_month_year)
        data_a.loan.loan_status_id = 220
        data_a.loan.lender = self.lender
        data_a.loan.account = self.account
        data_a.loan.save()

        data_b = LendeastDataMonthlyFactory(data_date=last_month_year)
        data_b.loan.loan_status_id = 233
        data_b.loan.lender = self.lender
        data_b.loan.account = self.account
        data_b.loan.save()

        data_c = LendeastDataMonthlyFactory(data_date=last_month_year)
        data_c.loan.loan_status_id = 234
        data_c.loan.lender = self.lender
        data_c.loan.account = self.account
        data_c.loan.save()

        mock_construct_loans_information_data.delay.side_effect = \
                mock_construct_loans_information_data_func

        for _x in range(7):
            loan = LoanFactory(loan_amount=2080000)
            loan.lender = self.lender
            loan.account = self.account
            loan.loan_status_id = 220
            loan.product.product_line_id = 1
            loan.product.save()
            loan.save()

        # Axiata loan
        axiata_loan = LoanFactory(loan_amount=2080000)
        axiata_loan.lender = self.lender
        axiata_loan.loan_status_id = 220
        axiata_loan.product.product_line_id = 95
        axiata_loan.product.save()
        axiata_loan.application = self.app
        axiata_loan.save()

        partial_paid_payment = loan.payment_set.first()
        partial_paid_payment.paid_amount = 100000
        partial_paid_payment.paid_principal = 80000
        partial_paid_payment.paid_interest = 20000
        partial_paid_payment.save()

        retrucuted_payment = loan.payment_set.last()
        retrucuted_payment.is_restructured = True
        retrucuted_payment.save()

        collect_loans_for_lendeast()
        assert LendeastDataMonthly.objects.filter(
            data_date=current_month_year,
            loan_id__in=[data_a.loan_id, data_b.loan_id]
        ).count() == 2

        assert LendeastDataMonthly.objects.filter(
            data_date=current_month_year,
            loan_id=data_c.loan_id
        ).count() == 1

        assert LendeastDataMonthly.objects.filter(
            data_date=current_month_year,
            loan_id=axiata_loan.id
        ).exists()

        assert mock_construct_loans_information_data.delay.call_count == 1

        res = self.client.get(self.url, HTTP_AUTHORIZATION=self.token)
        assert res.status_code == 200
        assert len(res.json()['data']) == 11

        # last_loan_data = res.json()['data'][-1]

        # assert len(last_loan_data['loanIncrInterestReceived']) == 3
        # assert len(last_loan_data['loanIncrPrincipalReceived']) == 3

        # assert last_loan_data['loanIncrInterestReceived'][0] == 20000
        # assert last_loan_data['loanIncrPrincipalReceived'][0] == 80000
