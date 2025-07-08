from django.core.urlresolvers import reverse
from unittest.mock import patch

from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.constants import WorkflowConst
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, \
    HTTP_404_NOT_FOUND
from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory, ApplicationJ1Factory, ApplicationFactory,
    PdBscoreModelResultFactory,
    ProductLookupFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.promo.constants import (
    PromoCodeBenefitConst,
    PromoCodeCriteriaConst,
    PromoCodeMessage,
    PromoCodeTypeConst,
    PromoCodeTimeConst,
)
from juloserver.promo.tests.factories import (
    PromoCodeBenefitFactory,
    PromoCodeCriteriaFactory,
    PromoCodeFactory,
    CriteriaControlListFactory,
)


class TestLoanPromoCodeCheckV3(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.fixed_cash_benefit = PromoCodeBenefitFactory(
            name="You bring me more meth, that's brilliant!",
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value = {
                'amount': 20000,
            },
        )
        self.promo_code = PromoCodeFactory(
            promo_code_benefit=self.fixed_cash_benefit,
            promo_code="You've got one part of that wrong...",
            is_active=True,
            type=PromoCodeTypeConst.LOAN,
            promo_code_daily_usage_count=5,
            promo_code_usage_count=5,
        )
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=AccountLookupFactory(
                workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            ),
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_case_not_exist_promo_code(self):
        self.promo_code.is_active = False
        self.promo_code.save()
        data = {
            'loan_amount': 100000,
            'transaction_method_id': 1,
            'loan_duration': 3,
            'promo_code': self.promo_code.promo_code,
        }
        response = self.client.post(
            path='/api/promo/v3/promo-code/check/',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['errors'][0], PromoCodeMessage.ERROR.WRONG)

    @patch('juloserver.promo.views_v3.check_promo_code_and_get_message_v2')
    def test_case_good(self, mock_check_promo_code):
        message = "This, is not meth."
        mock_check_promo_code.return_value = None, message

        data = {
            'loan_amount': 100000,
            'transaction_method_id': 1,
            'loan_duration': 3,
            'promo_code': self.promo_code.promo_code,
        }

        response = self.client.post(
            path='/api/promo/v3/promo-code/check/',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, HTTP_200_OK)

    def test_promo_code_criteria_limit_per_promo_code_success_case(self):
        criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={
                 'limit_per_promo_code': 6,
                 'times': PromoCodeTimeConst.ALL_TIME,
            }
        )
        self.promo_code.criteria = [
            criteria.id,
        ]
        self.promo_code.save()

        data = {
            'loan_amount': 100000,
            'transaction_method_id': 1,
            'loan_duration': 3,
            'promo_code': self.promo_code.promo_code,
        }
        resp = self.client.post(
            path='/api/promo/v3/promo-code/check/',
            data=data, format='json',
        )
        self.assertEqual(HTTP_200_OK, resp.status_code)

    def test_promo_code_criteria_limit_per_promo_code_fail_tc1(self):
        criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={
                 'limit_per_promo_code': 5,
                 'times': PromoCodeTimeConst.ALL_TIME,
            }
        )
        self.promo_code.criteria = [
            criteria.id,
        ]
        self.promo_code.save()

        data = {
            'loan_amount': 100000,
            'transaction_method_id': 1,
            'loan_duration': 3,
            'promo_code': self.promo_code.promo_code,
        }
        resp = self.client.post(
            path='/api/promo/v3/promo-code/check/',
            data=data, format='json',
        )
        self.assertEqual(HTTP_400_BAD_REQUEST, resp.status_code)
        self.assertEqual(resp.data['errors'][0], PromoCodeMessage.ERROR.LIMIT_PER_PROMO_CODE)

    def test_promo_code_criteria_limit_per_promo_code_fail_tc2(self):
        criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={
                 'limit_per_promo_code': 4,
                 'times': PromoCodeTimeConst.ALL_TIME,
            }
        )
        self.promo_code.criteria = [
            criteria.id,
        ]
        self.promo_code.save()

        data = {
            'loan_amount': 100000,
            'transaction_method_id': 1,
            'loan_duration': 3,
            'promo_code': self.promo_code.promo_code,
        }
        resp = self.client.post(
            path='/api/promo/v3/promo-code/check/',
            data=data, format='json',
        )
        self.assertEqual(HTTP_400_BAD_REQUEST, resp.status_code)
        self.assertEqual(resp.data['errors'][0], PromoCodeMessage.ERROR.LIMIT_PER_PROMO_CODE)

    def test_promo_code_criteria_b_score_less_than_threshold(self):
        criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.B_SCORE,
            value={
                 'b_score': 0.3,
            }
        )
        self.promo_code.criteria = [
            criteria.id,
        ]
        self.promo_code.save()

        data = {
            'loan_amount': 100000,
            'transaction_method_id': 1,
            'loan_duration': 3,
            'promo_code': self.promo_code.promo_code,
        }
        resp = self.client.post(
            path='/api/promo/v3/promo-code/check/',
            data=data, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['errors'], ['kamu belum memenuhi kriteria'])

        PdBscoreModelResultFactory(customer_id=self.customer.id, pgood=0.2)

        criteria.update_safely(value={'b_score': 0.1})
        resp = self.client.post(
            path='/api/promo/v3/promo-code/check/',
            data=data, format='json',
        )
        self.assertEqual(resp.status_code, 200)


class TestLoanPromoCodeListViewV3(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def set_up_promo_code_list(self):
        criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={
                 'limit_per_promo_code': 6,
                 'times': PromoCodeTimeConst.ALL_TIME,
            }
        )
        criteria.save()

        criteria_failed = PromoCodeCriteriaFactory(
            type=PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT,
            value={
                 'minimum_loan_amount': 6*(10**7),
            }
        )
        criteria_failed.save()

        # promo code cashback loan amount
        self.cashback_loan_amount_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value = {
                'percent': 20, 'max_cashback': 900
            },
        )
        self.promo_code_1 = PromoCodeFactory(
            promo_code='promo_code_1',
            promo_code_benefit=self.cashback_loan_amount_benefit,
            criteria=[criteria.id],
            is_active=True,
            is_public=True,
            type=PromoCodeTypeConst.LOAN,
        )
        # promo code fixed cashback
        self.fixed_cashback_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value = {
                'amount': 20000,
            },
        )
        self.promo_code_0 = PromoCodeFactory(
            promo_code='promo_code_0',
            promo_code_benefit=self.fixed_cashback_benefit,
            criteria=[criteria.id],
            is_active=True,
            is_public=True,
            type=PromoCodeTypeConst.LOAN,
        )

        # INELIGIBLE promo code cashback loan amount
        self.cashback_loan_amount_benefit_false = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value = {
                'percent': 15, 'max_cashback': 1700
            },
        )
        self.promo_code_3 = PromoCodeFactory(
            promo_code='promo_code_3',
            promo_code_benefit=self.cashback_loan_amount_benefit_false,
            criteria=[criteria_failed.id],
            is_active=True,
            is_public=True,
            type=PromoCodeTypeConst.LOAN,
        )

        # INELIGIBLE promo code fixed cashback
        self.fixed_cashback_benefit_false = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value = {
                'amount': 33000,
            },
        )
        self.promo_code_2 = PromoCodeFactory(
            promo_code='promo_code_2',
            promo_code_benefit=self.fixed_cashback_benefit_false,
            criteria=[criteria_failed.id],
            is_active=True,
            is_public=True,
            type=PromoCodeTypeConst.LOAN,
        )

    def set_up_promo_code_with_whitelist(self, customer=None):
        # init whitelist criteria
        criterion_whitelist = PromoCodeCriteriaFactory(
            name="whitelist for premium customer",
            type=PromoCodeCriteriaConst.WHITELIST_CUSTOMERS,
            value={}
        )
        criterion_whitelist.save()

        control_list = CriteriaControlListFactory(
            promo_code_criteria=criterion_whitelist
        )
        if customer:
            control_list.update_safely(customer_id=customer.id)

        # init min amount criteria
        criterion_min_amount = PromoCodeCriteriaFactory(
            type=PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT,
            value={
                 'minimum_loan_amount': 5_000_000,
            }
        )
        criterion_min_amount.save()

        cashback_loan_amount_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value={
                'percent': 20, 'max_cashback': 900
            },
        )
        self.promo_code_1 = PromoCodeFactory(
            promo_code='promo_code_1',
            promo_code_benefit=cashback_loan_amount_benefit,
            criteria=[criterion_min_amount.id, criterion_whitelist.id],
            is_active=True,
            is_public=True,
            type=PromoCodeTypeConst.LOAN,
        )


    def test_get_promo_code_list(self):
        self.set_up_promo_code_list()

        url = reverse('promo_v3:promo_code_list_v3') + '?loan_amount=120000&transaction_method_id=1&loan_duration=3'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        promo_codes_res = data['data']

        self.assertEquals(len(promo_codes_res), 4)
        self.assertEquals(promo_codes_res[0]['promo_code'], self.promo_code_0.promo_code)
        self.assertEquals(promo_codes_res[1]['promo_code'], self.promo_code_1.promo_code)
        self.assertEquals(promo_codes_res[2]['promo_code'], self.promo_code_2.promo_code)
        self.assertEquals(promo_codes_res[3]['promo_code'], self.promo_code_3.promo_code)

    def test_get_promo_code_list_pass_whitelist_criteria(self):
        self.set_up_promo_code_with_whitelist(self.customer)

        url = reverse('promo_v3:promo_code_list_v3') + '?loan_amount=3000000&transaction_method_id=1&loan_duration=6'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        promo_codes_res = data['data']

        self.assertEquals(len(promo_codes_res), 1)

    def test_get_promo_code_list_fail_whitelist_criteria(self):
        self.set_up_promo_code_with_whitelist()

        url = reverse('promo_v3:promo_code_list_v3') + '?loan_amount=3000000&transaction_method_id=1&loan_duration=6'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        promo_codes_res = data['data']

        self.assertEquals(len(promo_codes_res), 0)
