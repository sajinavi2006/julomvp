"""
"""

import datetime

import mock
import pytest
from django.test.testcases import TestCase

from juloserver.apiv2.services import get_product_lines
from juloserver.julo.exceptions import JuloException
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    ProductLine,
    ProductLookupFactory,
)


@pytest.mark.django_db
class TestOfferGeneration(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.user = AuthUserFactory()
        self.paid_date_str = datetime.datetime.today().strftime('%d-%m-%Y')
        self.prod_line = ProductLine.objects.get(pk=10)
        self.prod_line.amount_increment = 500000
        self.prod_line.save()

    @mock.patch('juloserver.apiv2.services.get_credit_score3')
    @mock.patch('juloserver.apiv2.services.get_credit_matrix')
    @mock.patch('juloserver.apiv2.services.get_score_product')
    @mock.patch('juloserver.apiv2.services.check_eligible_mtl_extenstion')
    def test_get_prod_line(
        self,
        mock_check_eligible_mtl_extenstion,
        mock_get_score_product,
        mock_get_credit_matrix,
        mock_get_credit_score3,
    ):
        """"""
        mock_credit_score3 = mock.MagicMock()
        mock_credit_score3.score = 'A-'
        mock_credit_score3.score_tag = ''

        credit_matrix_database = mock.MagicMock()
        credit_matrix_database.list_product_lines = [10]

        score_product = mock.MagicMock()
        score_product.min_loan_amount = 500000
        score_product.max_loan_amount = 500000
        score_product.min_duration = 1
        score_product.max_duration = 5
        score_product.interest = 0.03

        mock_get_credit_score3.return_value = mock_credit_score3
        mock_get_credit_matrix.return_value = credit_matrix_database
        mock_get_score_product.return_value = score_product
        mock_check_eligible_mtl_extenstion.return_value = False

        self.application.app_version = '3.19.1'
        self.application.save()
        result = get_product_lines(self.customer, self.application, False)
        mtl1 = None

        for prod_line in result:
            if prod_line.product_line_type == 'MTL1':
                mtl1 = prod_line
                break

        assert mtl1 is not None
        assert mtl1.min_amount == 500000
        assert mtl1.max_amount == 1000000
