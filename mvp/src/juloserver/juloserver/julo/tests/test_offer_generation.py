"""
"""
from __future__ import absolute_import

from builtins import str
import datetime
import pytest
import mock
from django.test.testcases import TestCase
from .factories import (AuthUserFactory,
                       CustomerFactory,
                       ApplicationFactory,
                       ProductLookupFactory,
                       ProductLine)
from juloserver.julo.services import get_offer_recommendations
from juloserver.julo.models import ProductLookup
from juloserver.julo.exceptions import JuloException
from juloserver.julocore.python2.utils import py2round


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
        ProductLookupFactory(interest_rate=0.36, product_line=self.prod_line)
        ProductLookupFactory(interest_rate=0.84, product_line=self.prod_line)

    @mock.patch('juloserver.julo.services.compute_adjusted_payment_installment')
    @mock.patch('juloserver.julo.services.check_eligible_for_campaign_referral')
    @mock.patch('juloserver.julo.services.false_reject_min_exp')
    @mock.patch('juloserver.julo.services.check_fraud_model_exp')
    @mock.patch('juloserver.julo.services.get_credit_score3')
    @mock.patch('juloserver.julo.services.get_score_product')
    def test_affordable_payment_true(self, mock_get_score_product,
                                     mock_get_credit_score3,
                                     mock_check_fraud_model_exp,
                                     mock_false_reject_min_exp,
                                     mock_check_eligible_for_campaign_referral,
                                     mock_compute_adjusted_payment_installment):
        """"""
        mock_check_eligible_for_campaign_referral.return_value = 1400000
        mock_compute_adjusted_payment_installment.return_value = [0, 0, 1430000]
        mock_check_fraud_model_exp.return_value = False
        mock_false_reject_min_exp.return_value = False
        mock_score_product = mock.MagicMock()
        mock_score_product.min_loan_amount = 2000000
        mock_score_product.max_loan_amount = 7000000
        mock_score_product.min_duration = 1
        mock_score_product.max_duration = 3
        mock_score_product.interest = 0.06
        mock_score_product.get_product_lookup.return_value = ProductLookup.objects.filter(
            interest_rate=py2round(mock_score_product.interest*12, 2),
            product_line=10
        ).first()

        mock_get_credit_score3.return_value = 'test'
        mock_get_score_product.return_value = mock_score_product

        product_line_code = 10
        loan_amount_requested = 2500000
        loan_duration_requested = 2
        affordable_payment = 1700000
        payday = 5
        application_nik = self.application.ktp
        application_id = self.application.id

        expected = {
            'requested_offer': {
                'installment_amount_offer': 1400000,
                'first_installment_amount': 1430000,
                'can_afford': True,
                'loan_duration_offer': 2,
                'loan_amount_offer': 2500000
            },
            'product_rate': {
                'monthly_interest_rate': 0.06,
                'origination_fee_rate': 0.05,
                'annual_interest_rate': 0.72,
                'late_fee_rate': 0.05,
                'cashback_payment_rate': 0.01,
                'cashback_initial_rate': 0.0
            },
            'offers': [
                {
                    'installment_amount_offer': 1400000,
                    'first_installment_amount': 1400000,
                    'offer_number': 1,
                    'is_accepted': False,
                    'loan_duration_offer': 2,
                    'loan_amount_offer': 2500000
                }
            ]
        }

        result = get_offer_recommendations(
            product_line_code,
            loan_amount_requested,
            loan_duration_requested,
            affordable_payment,
            payday,
            application_nik,
            application_id
        )
        result['requested_offer'].pop('product')
        result['requested_offer'].pop('first_payment_date')
        result['offers'][0].pop('product')
        result['offers'][0].pop('first_payment_date')
        assert result['requested_offer'] == expected['requested_offer']
        assert result['product_rate'] == expected['product_rate']
        assert result['offers'] == expected['offers']
        mock_get_score_product.assert_called_with('test', 'julo', 10, 'Pegawai swasta')


    @mock.patch('juloserver.julo.services.compute_adjusted_payment_installment')
    @mock.patch('juloserver.julo.services.false_reject_min_exp')
    @mock.patch('juloserver.julo.services.check_fraud_model_exp')
    @mock.patch('juloserver.julo.services.get_credit_score3')
    @mock.patch('juloserver.julo.services.get_score_product')
    def test_no_credit_score(self, mock_get_score_product,
                             mock_get_credit_score3,
                             mock_check_fraud_model_exp,
                             mock_false_reject_min_exp,
                             mock_compute_adjusted_payment_installment):
        """"""
        mock_compute_adjusted_payment_installment.return_value = [0, 0, 27000]
        mock_check_fraud_model_exp.return_value = False
        mock_false_reject_min_exp.return_value = False
        mock_score_product = mock.MagicMock()
        mock_score_product.min_loan_amount = 2000000
        mock_score_product.max_loan_amount = 3000000
        mock_score_product.min_duration = 1
        mock_score_product.max_duration = 3
        mock_score_product.interest = 0.06
        mock_score_product.get_product_lookup.return_value = ProductLookup.objects.filter(
            interest_rate=py2round(mock_score_product.interest*12, 2),
            product_line=10
        ).first()

        mock_get_credit_score3.return_value = None
        mock_get_score_product.return_value = mock_score_product

        product_line_code = 10
        loan_amount_requested = 100000
        loan_duration_requested = 5
        affordable_payment = 50000
        payday = 5
        application_nik = self.application.ktp
        application_id = self.application.id

        with self.assertRaises(JuloException) as context:
            result = get_offer_recommendations(
                product_line_code,
                loan_amount_requested,
                loan_duration_requested,
                affordable_payment,
                payday,
                application_nik,
                application_id
            )
        assert 'CreditCore is not found' == str(context.exception)

    @mock.patch('juloserver.julo.services.compute_adjusted_payment_installment')
    @mock.patch('juloserver.julo.services.false_reject_min_exp')
    @mock.patch('juloserver.julo.services.check_fraud_model_exp')
    @mock.patch('juloserver.julo.services.get_credit_score3')
    @mock.patch('juloserver.julo.services.get_score_product')
    def test_tokopedia_partner(self, mock_get_score_product,
                               mock_get_credit_score3,
                               mock_check_fraud_model_exp,
                               mock_false_reject_min_exp,
                               mock_compute_adjusted_payment_installment):
        """"""
        mock_compute_adjusted_payment_installment.return_value = [0, 0, 118000]
        mock_check_fraud_model_exp.return_value = False
        mock_false_reject_min_exp.return_value = False
        mock_score_product = mock.MagicMock()
        mock_score_product.min_loan_amount = 2000000
        mock_score_product.max_loan_amount = 7000000
        mock_score_product.min_duration = 1
        mock_score_product.max_duration = 3
        mock_score_product.interest = 0.06
        mock_score_product.get_product_lookup.return_value = ProductLookup.objects.filter(
            interest_rate=py2round(0.03*12, 2),
            product_line=10
        ).first()

        mock_get_credit_score3.return_value = 'test'
        mock_get_score_product.return_value = mock_score_product

        product_line_code = 10
        loan_amount_requested = 500000
        loan_duration_requested = 5
        affordable_payment = 500
        payday = 5
        application_nik = self.application.ktp
        application_id = self.application.id

        mock_partner = mock.MagicMock()
        mock_partner.name = 'tokopedia'

        expected = {
            'requested_offer': {
                'installment_amount_offer': 115000,
                'first_installment_amount': 118000,
                'can_afford': False,
                'loan_duration_offer': 5,
                'loan_amount_offer': 500000
            },
            'product_rate': {
                'monthly_interest_rate': 0.03,
                'origination_fee_rate': 0.05,
                'annual_interest_rate': 0.36,
                'late_fee_rate': 0.05,
                'cashback_payment_rate': 0.01,
                'cashback_initial_rate': 0.01
            },
            'offers': []
        }

        result = get_offer_recommendations(
            product_line_code,
            loan_amount_requested,
            loan_duration_requested,
            affordable_payment,
            payday,
            application_nik,
            application_id,
            mock_partner
        )
        result['requested_offer'].pop('product')
        result['requested_offer'].pop('first_payment_date')
        self.assertEqual(result['requested_offer'], expected['requested_offer'])
        self.assertEqual(result['product_rate'], expected['product_rate'])
        self.assertEqual(result['offers'], expected['offers'])
        mock_get_score_product.assert_called_with('test', 'julo', 10, 'Pegawai swasta')

    @mock.patch('juloserver.julo.services.compute_adjusted_payment_installment')
    @mock.patch('juloserver.julo.services.check_eligible_for_campaign_referral')
    @mock.patch('juloserver.julo.services.false_reject_min_exp')
    @mock.patch('juloserver.julo.services.check_fraud_model_exp')
    @mock.patch('juloserver.julo.services.get_credit_score3')
    @mock.patch('juloserver.julo.services.get_score_product')
    def test_mock_check_fraud_model_exp_true(self, mock_get_score_product,
                                             mock_get_credit_score3,
                                             mock_check_fraud_model_exp,
                                             mock_false_reject_min_exp,
                                             mock_check_eligible_for_campaign_referral,
                                             mock_compute_adjusted_payment_installment):
        """"""
        mock_compute_adjusted_payment_installment.return_value = [0, 0, 1454000]
        mock_check_eligible_for_campaign_referral.return_value = 1400000
        mock_check_fraud_model_exp.return_value = True
        mock_false_reject_min_exp.return_value = False
        mock_score_product = mock.MagicMock()
        mock_score_product.min_loan_amount = 2000000
        mock_score_product.max_loan_amount = 7000000
        mock_score_product.min_duration = 1
        mock_score_product.max_duration = 3
        mock_score_product.interest = 0.06
        mock_score_product.get_product_lookup.return_value = ProductLookup.objects.filter(
            interest_rate=py2round(0.07*12, 2),
            product_line=10
        ).first()

        mock_get_credit_score3.return_value = 'test'
        mock_get_score_product.return_value = mock_score_product

        product_line_code = 10
        loan_amount_requested = 2500000
        loan_duration_requested = 2
        affordable_payment = 1700000
        payday = 5
        application_nik = self.application.ktp
        application_id = self.application.id

        expected = {
            'requested_offer': {
                'installment_amount_offer': 1425000,
                'first_installment_amount': 1454000,
                'can_afford': True,
                'loan_duration_offer': 2,
                'loan_amount_offer': 2500000
            },
            'product_rate': {
                'monthly_interest_rate': 0.07,
                'origination_fee_rate': 0.05,
                'annual_interest_rate': 0.84,
                'late_fee_rate': 0.05,
                'cashback_payment_rate': 0.01,
                'cashback_initial_rate': 0.01
            },
            'offers': [{
                'installment_amount_offer': 570000,
                'first_installment_amount': 1400000,
                'offer_number': 1,
                'is_accepted': False,
                'loan_duration_offer': 2,
                'loan_amount_offer': 1000000
            }]
        }

        result = get_offer_recommendations(
            product_line_code,
            loan_amount_requested,
            loan_duration_requested,
            affordable_payment,
            payday,
            application_nik,
            application_id
        )
        result['requested_offer'].pop('first_payment_date')
        result['requested_offer'].pop('product')
        result['offers'][0].pop('product')
        result['offers'][0].pop('first_payment_date')
        assert result['requested_offer'] == expected['requested_offer']
        assert result['product_rate'] == expected['product_rate']
        assert result['offers'] == expected['offers']
        mock_get_score_product.assert_called_with('test', 'julo', 10, 'Pegawai swasta')
