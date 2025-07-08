from django.core.urlresolvers import reverse
from rest_framework.status import HTTP_200_OK, HTTP_404_NOT_FOUND
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
)
from juloserver.promo.constants import (
    PromoCodeBenefitConst,
    PromoCodeCriteriaConst,
    PromoCodeTypeConst,
    PromoCodeTimeConst,
)
from juloserver.promo.tests.factories import (
    CriteriaControlListFactory,
    PromoCodeBenefitFactory,
    PromoCodeCriteriaFactory,
    PromoCodeFactory,
)


class TestLoanPromoCodeListViewV2(APITestCase):
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

        # INELIGIBLE promo code cashback installment
        self.cashback_installment_benefit_false = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_INSTALLMENT,
            value = {
                'percent': 40, 'max_cashback': 5000
            },
        )
        self.promo_code_7 = PromoCodeFactory(
            promo_code='promo_code_7',
            promo_code_benefit=self.cashback_installment_benefit_false,
            criteria=[criteria_failed.id],
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

        # promo code installment discount
        self.installment_discount_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INSTALLMENT_DISCOUNT,
            value = {
                'percent': 10, 'max_amount': 1000
            },
        )
        self.promo_code_3 = PromoCodeFactory(
            promo_code='promo_code_3',
            promo_code_benefit=self.installment_discount_benefit,
            criteria=[criteria.id],
            is_active=True,
            is_public=True,
            type=PromoCodeTypeConst.LOAN,
        )

        # INELIGIBLE promo code installment discount
        self.installment_discount_benefit_false = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INSTALLMENT_DISCOUNT,
            value = {
                'percent': 80, 'max_amount': 60000
            },
        )
        self.promo_code_8 = PromoCodeFactory(
            promo_code='promo_code_8',
            promo_code_benefit=self.installment_discount_benefit_false,
            criteria=[criteria_failed.id],
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
        self.promo_code_6 = PromoCodeFactory(
            promo_code='promo_code_6',
            promo_code_benefit=self.cashback_loan_amount_benefit_false,
            criteria=[criteria_failed.id],
            is_active=True,
            is_public=True,
            type=PromoCodeTypeConst.LOAN,
        )

        # promo code cashback installment
        self.cashback_installment_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_INSTALLMENT,
            value = {
                'percent': 7, 'max_cashback': 20000
            },
        )
        self.promo_code_2 = PromoCodeFactory(
            promo_code='promo_code_2',
            promo_code_benefit=self.cashback_installment_benefit,
            criteria=[criteria.id],
            is_active=True,
            is_public=True,
            type=PromoCodeTypeConst.LOAN,
        )

        # promo code installment discount
        self.interest_discount_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value = {
                'percent': 5, 'duration': 5, 'max_amount': 13000
            },
        )
        self.promo_code_4 = PromoCodeFactory(
            promo_code='promo_code_4',
            promo_code_benefit=self.interest_discount_benefit,
            criteria=[criteria.id],
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
        self.promo_code_5 = PromoCodeFactory(
            promo_code='promo_code_5',
            promo_code_benefit=self.fixed_cashback_benefit_false,
            criteria=[criteria_failed.id],
            is_active=True,
            is_public=True,
            type=PromoCodeTypeConst.LOAN,
        )

        # INELIGIBLE promo code installment discount
        self.interest_discount_benefit_false = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value = {
                'percent': 1, 'duration': 1, 'max_amount': 12000
            },
        )
        self.promo_code_9 = PromoCodeFactory(
            promo_code='promo_code_9',
            promo_code_benefit=self.interest_discount_benefit_false,
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

        # promo code benefit
        interest_discount_benefit_false = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value = {
                'percent': 1, 'duration': 1, 'max_amount': 12000
            },
        )

        promo_code = PromoCodeFactory(
            promo_code='promo_code_whitelist',
            promo_code_benefit=interest_discount_benefit_false,
            criteria=[criterion_min_amount.id, criterion_whitelist.id],
            is_active=True,
            is_public=True,
            type=PromoCodeTypeConst.LOAN,
        )

    def test_get_promo_code_list(self):
        self.set_up_promo_code_list()

        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_amount=120000,
            loan_duration=6
        )
        loan.save()
        for payment in loan.payment_set.all():
            payment.update_safely(installment_principal=20000, installment_interest=2000)

        url = reverse('promo_v2:promo_code_list_v2', kwargs={'loan_xid': loan.loan_xid})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        promo_codes_res = data['data']

        self.assertEquals(len(promo_codes_res), 8)
        self.assertEquals(promo_codes_res[0]['promo_code'], self.promo_code_0.promo_code)
        self.assertEquals(promo_codes_res[1]['promo_code'], self.promo_code_1.promo_code)
        self.assertEquals(promo_codes_res[2]['promo_code'], self.promo_code_2.promo_code)
        self.assertEquals(promo_codes_res[3]['promo_code'], self.promo_code_3.promo_code)
        self.assertEquals(promo_codes_res[4]['promo_code'], self.promo_code_5.promo_code)
        self.assertEquals(promo_codes_res[5]['promo_code'], self.promo_code_6.promo_code)
        self.assertEquals(promo_codes_res[6]['promo_code'], self.promo_code_7.promo_code)
        self.assertEquals(promo_codes_res[7]['promo_code'], self.promo_code_8.promo_code)

    def test_get_promo_code_list_pass_whitelist_criteria(self):
        self.set_up_promo_code_with_whitelist(self.customer)

        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_amount=3_000_000,
            loan_duration=6
        )
        loan.save()

        url = reverse('promo_v2:promo_code_list_v2', kwargs={'loan_xid': loan.loan_xid})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        promo_codes_res = data['data']

        self.assertEquals(len(promo_codes_res), 0)

    def test_get_promo_code_list_fail_whitelist_criteria(self):
        self.set_up_promo_code_with_whitelist()

        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_amount=3_000_000,
            loan_duration=6
        )
        loan.save()

        url = reverse('promo_v2:promo_code_list_v2', kwargs={'loan_xid': loan.loan_xid})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        promo_codes_res = data['data']

        self.assertEquals(len(promo_codes_res), 0)


class TestLoanPromoCodeCheckV2(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

        criteria = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={
                 'limit_per_promo_code': 6,
                 'times': PromoCodeTimeConst.ALL_TIME,
            }
        )
        criteria.save()
        self.fixed_cash_benefit = PromoCodeBenefitFactory(
            name="You bring me more meth, that's brilliant!",
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value = {
                'amount': 20000,
            },
        )
        self.promo_code = PromoCodeFactory(
            promo_code_benefit=self.fixed_cash_benefit,
            criteria=[criteria.id],
            promo_code="You've got one part of that wrong...",
            is_active=True,
            type=PromoCodeTypeConst.LOAN,
            promo_code_usage_count=5,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=1000000,
        )

        self.url = reverse('promo_v2:promo_code_check_v2')

    def test_valid_promo_code(self):
        data = {
            'loan_xid': self.loan.loan_xid,
            'promo_code': self.promo_code.promo_code,
        }

        resp = self.client.post(path=self.url, data=data, format='json')
        self.assertEquals(resp.status_code, HTTP_200_OK)
        resp_data = resp.data['data']
        self.assertEquals(resp_data['promo_code_type'], 'cashback')

    def test_invalid_promo_code(self):
        data = {
            'loan_xid': self.loan.loan_xid,
            'promo_code': 'NOT_FOUND',
        }

        resp = self.client.post(path=self.url, data=data, format='json')
        self.assertEquals(resp.status_code, HTTP_404_NOT_FOUND)
