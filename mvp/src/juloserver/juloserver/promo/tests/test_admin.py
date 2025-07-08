from django.core.urlresolvers import reverse
from django.test import TestCase
from django.utils import timezone
from factory import Iterator

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ProductLineFactory,
    PartnerFactory,
    CreditMatrixFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.promo.constants import (
    PromoCodeBenefitConst,
    PromoCodeCriteriaConst,
    PromoCodeTypeConst,
)
from juloserver.promo.models import (
    PromoCodeBenefit,
    PromoCodeCriteria,
    PromoCode,
)
from juloserver.promo.tests.factories import (
    PromoCodeBenefitFactory,
    PromoCodeCriteriaFactory,
    PromoCodeFactory,
    PromoCodeLoanFactory,
)
from juloserver.sales_ops.tests.factories import SalesOpsRMScoringFactory


class TestPromoCodeBenefitAdmin(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)

    def test_get_list(self):
        PromoCodeBenefitFactory.create_batch(10)
        url = reverse('admin:promo_promocodebenefit_changelist')
        res = self.client.get(url)

        self.assertContains(res, '10 promo code benefit')

    def test_get_add(self):
        url = reverse('admin:promo_promocodebenefit_add')
        res = self.client.get(url)

        self.assertContains(res, 'Save')

    def test_post_add_fixed_cashback(self):
        url = reverse('admin:promo_promocodebenefit_add')
        post_data = {
            'name': 'benefit name',
            'type': PromoCodeBenefitConst.FIXED_CASHBACK,
            'value_amount': '10',
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeBenefit.objects.get(name='benefit name')
        expected_value = {
            'amount': 10,
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeBenefitConst.FIXED_CASHBACK, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_cashback_from_loan_amount(self):
        url = reverse('admin:promo_promocodebenefit_add')
        post_data = {
            'name': 'benefit name',
            'type': PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            'value_max_cashback': '10000',
            'value_percent': '10',
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeBenefit.objects.get(name='benefit name')
        expected_value = {
            'percent': 10,
            'max_cashback': 10000,
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_installment_discount(self):
        url = reverse('admin:promo_promocodebenefit_add')
        post_data = {
            'name': 'benefit name',
            'type': PromoCodeBenefitConst.INSTALLMENT_DISCOUNT,
            'value_duration': '9',
            'value_percent': '10',
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeBenefit.objects.get(name='benefit name')
        expected_value = {
            'duration': 9,
            'percent': 10,
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeBenefitConst.INSTALLMENT_DISCOUNT, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_get_change(self):
        obj = PromoCodeBenefitFactory(
            name='benefit name',
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value={'amount': 1000}
        )
        url = reverse('admin:promo_promocodebenefit_change', args=[obj.id])
        res = self.client.get(url)

        self.assertContains(res, 'benefit name')
        self.assertContains(res, PromoCodeBenefitConst.FIXED_CASHBACK)
        self.assertContains(res, '1000')
        self.assertContains(res, 'Save')

    def test_post_change(self):
        obj = PromoCodeBenefitFactory(
            name='benefit name',
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value={'amount': 1000}
        )
        url = reverse('admin:promo_promocodebenefit_change', args=[obj.id])

        post_data = {
            'name': 'new benefit name',
            'type': PromoCodeBenefitConst.INSTALLMENT_DISCOUNT,
            'value_duration': '9',
            'value_percent': '10',
        }
        res = self.client.post(url, post_data)

        obj.refresh_from_db()
        self.assertEqual('new benefit name', obj.name)
        self.assertEqual(PromoCodeBenefitConst.INSTALLMENT_DISCOUNT, obj.type)
        self.assertEqual({'duration': 9, 'percent': 10}, obj.value)

    def test_get_delete(self):
        obj = PromoCodeBenefitFactory()
        url = reverse('admin:promo_promocodebenefit_delete', args=[obj.id])
        res = self.client.get(url)

        self.assertContains(res, f'promo code benefit "{obj}"')
        self.assertContains(res, 'Yes')

    def test_post_delete(self):
        obj = PromoCodeBenefitFactory()
        url = reverse('admin:promo_promocodebenefit_delete', args=[obj.id])
        res = self.client.post(url, {'post': 'yes'})

        with self.assertRaises(PromoCodeBenefit.DoesNotExist):
            PromoCodeBenefit.objects.get(id=obj.id)

    def test_post_add_voucher(self):
        url = reverse('admin:promo_promocodebenefit_add')
        post_data = {
            'name': 'benefit voucher',
            'type': PromoCodeBenefitConst.VOUCHER,
        }
        self.client.post(url, post_data)

        expected_obj = PromoCodeBenefit.objects.get(name='benefit voucher')
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeBenefitConst.VOUCHER, expected_obj.type)
        self.assertEqual(expected_obj.value, {})


class TestPromoCodeCriteriaAdmin(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)

    def test_get_list(self):
        PromoCodeCriteriaFactory.create_batch(10)
        url = reverse('admin:promo_promocodecriteria_changelist')
        res = self.client.get(url)

        self.assertContains(res, '10 promo code criteria')

    def test_get_add(self):
        url = reverse('admin:promo_promocodecriteria_add')
        res = self.client.get(url)

        self.assertContains(res, 'Save')

    def test_post_add_limit_per_customer_daily(self):
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER,
            'value_limit': '10',
            'value_times': 'daily',
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'limit': 10,
            'times': 'daily',
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_limit_per_customer_all_time(self):
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER,
            'value_limit': '10',
            'value_times': 'all_time',
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'limit': 10,
            'times': 'all_time',
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_limit_per_promo_code_daily_tc1(self):
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            'value_limit_per_promo_code': '10',
            'value_times': 'daily',
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'limit_per_promo_code': 10,
            'times': 'daily',
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_limit_per_promo_code_daily_tc2(self):
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            'value_limit_per_promo_code': '0',
            'value_times': 'daily',
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'limit_per_promo_code': 0,
            'times': 'daily',
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_limit_per_promo_code_all_time_tc1(self):
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            'value_limit_per_promo_code': '10',
            'value_times': 'all_time',
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'limit_per_promo_code': 10,
            'times': 'all_time',
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_limit_per_promo_code_all_time_tc2(self):
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            'value_limit_per_promo_code': '0',
            'value_times': 'all_time',
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'limit_per_promo_code': 0,
            'times': 'all_time',
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_application_partner(self):
        partners = PartnerFactory.create_batch(2, name=Iterator(['A', 'B']))
        partner_ids = [partner.id for partner in partners]
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.APPLICATION_PARTNER,
            'value_partners': [str(partner_id) for partner_id in partner_ids],
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'partners': partner_ids,
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.APPLICATION_PARTNER, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_product_line_codes(self):
        ProductLineFactory.create_batch(2, product_line_code=Iterator([1, 2]))
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.PRODUCT_LINE,
            'value_product_line_codes': ['1', '2'],
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'product_line_codes': [1, 2]
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.PRODUCT_LINE, expected_obj.type)
        self.assertIn('product_line_codes', expected_obj.value)

        expected_obj.value['product_line_codes'].sort()
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_transaction_methods(self):
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.TRANSACTION_METHOD,
            'value_transaction_method_ids': ['1', '2'],
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'transaction_method_ids': [1, 2]
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.TRANSACTION_METHOD, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

        # update transaction history
        url = reverse('admin:promo_promocodecriteria_change', args=[expected_obj.id])
        update_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.TRANSACTION_METHOD,
            'value_transaction_method_ids': ['1', '2'],
            'value_transaction_history': ['never'],
        }
        res = self.client.post(url, update_data)
        expected_obj = PromoCodeCriteria.objects.get(pk=expected_obj.id)
        expected_value = {
            'transaction_method_ids': [1, 2],
            'transaction_history': 'never',
        }
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_credit_scores(self):
        CreditMatrixFactory.create_batch(3, score=Iterator(['A', 'B', 'C']))
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.CREDIT_SCORE,
            'value_credit_scores': ['A', 'B'],
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'credit_scores': ['A', 'B'],
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.CREDIT_SCORE, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_minimum_loan_amount(self):
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT,
            'value_minimum_loan_amount': 10000,
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get(name='criteria name')
        expected_value = {
            'minimum_loan_amount': 10000,
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

    def test_post_add_r_score(self):
        SalesOpsRMScoringFactory.create_batch(
            3, is_active=True, criteria='recency', score=Iterator([1, 2, 3])
        )
        url = reverse('admin:promo_promocodecriteria_add')
        post_data = {
            'name': 'criteria name',
            'type': PromoCodeCriteriaConst.R_SCORE,
            'value_r_scores': [1, 2, 3],
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get_or_none(name='criteria name')
        expected_value = {
            'r_scores': [1, 2, 3],
        }
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeCriteriaConst.R_SCORE, expected_obj.type)
        self.assertEqual(expected_value, expected_obj.value)

        post_data.update({
            'name': 'criteria name 2',
            'value_r_scores': [1, 2, 3, 4, 5, 6]
        })
        res = self.client.post(url, post_data)

        expected_obj = PromoCodeCriteria.objects.get_or_none(name='criteria name 2')
        self.assertIsNone(expected_obj)

        post_data['value_r_scores'] = 'shibainu'
        res = self.client.post(url, post_data)
        expected_obj = PromoCodeCriteria.objects.get_or_none(name='criteria name 2')
        self.assertIsNone(expected_obj)

        post_data['value_r_scores'] = []
        res = self.client.post(url, post_data)
        expected_obj = PromoCodeCriteria.objects.get_or_none(name='criteria name 2')
        self.assertIsNone(expected_obj)

    def test_get_change(self):
        obj = PromoCodeCriteriaFactory(
            name='criteria name',
            type=PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER,
            value={'limit': 10}
        )
        url = reverse('admin:promo_promocodecriteria_change', args=[obj.id])
        res = self.client.get(url)

        self.assertContains(res, 'criteria name')
        self.assertContains(res, PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER)
        self.assertContains(res, '10')
        self.assertContains(res, 'Save')

    def test_post_change(self):
        ProductLineFactory.create_batch(5, product_line_code=Iterator([1, 2, 3, 4, 5]))
        obj = PromoCodeCriteriaFactory(
            name='criteria name',
            type=PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER,
            value={'limit': 10}
        )
        url = reverse('admin:promo_promocodecriteria_change', args=[obj.id])

        post_data = {
            'name': 'new criteria name',
            'type': PromoCodeCriteriaConst.PRODUCT_LINE,
            'value_product_line_codes': ['1', '2', '3'],
        }
        res = self.client.post(url, post_data)

        obj.refresh_from_db()
        self.assertEqual('new criteria name', obj.name)
        self.assertEqual(PromoCodeCriteriaConst.PRODUCT_LINE, obj.type)

        obj.value['product_line_codes'].sort()
        self.assertListEqual([1, 2, 3], obj.value['product_line_codes'])

    def test_get_delete(self):
        obj = PromoCodeCriteriaFactory()
        url = reverse('admin:promo_promocodecriteria_delete', args=[obj.id])
        res = self.client.get(url)

        self.assertContains(res, f'promo code criteria "{obj}"')
        self.assertContains(res, 'Yes')

    def test_post_delete(self):
        obj = PromoCodeCriteriaFactory()
        url = reverse('admin:promo_promocodecriteria_delete', args=[obj.id])
        res = self.client.post(url, {'post': 'yes'})

        with self.assertRaises(PromoCodeCriteria.DoesNotExist):
            PromoCodeCriteria.objects.get(id=obj.id)


class TestPromoCodeAdmin(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)

    def test_get_list(self):
        PromoCodeFactory.create_batch(7)
        PromoCodeLoanFactory.create_batch(3)
        url = reverse('admin:promo_promocode_changelist')
        res = self.client.get(url)

        self.assertContains(res, '10 promo code')

    def test_get_add(self):
        url = reverse('admin:promo_promocode_add')
        res = self.client.get(url)

        self.assertContains(res, 'Save')

    def test_post_add_application(self):
        url = reverse('admin:promo_promocode_add')
        post_data = {
            'promo_name': 'name',
            'promo_code': 'code',
            'description': 'long description',
            'type': PromoCodeTypeConst.APPLICATION,
            'start_date_0': '2020-01-01',
            'start_date_1': '11:12:13',
            'end_date_0': '2021-01-01',
            'end_date_1': '11:12:13',
            'is_active': 'on',
            'promo_benefit': 'cashback',
            'cashback_amount': 10000,
            'partner': ['All'],
            'product_line': ['All'],
            'credit_score': ['All'],
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCode.objects.get(promo_name='name')
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeTypeConst.APPLICATION, expected_obj.type)
        self.assertEqual('code', expected_obj.promo_code)
        self.assertEqual('long description', expected_obj.description)
        self.assertEqual('2020-01-01 11:12:13', timezone.localtime(expected_obj.start_date).strftime('%Y-%m-%d %H:%M:%S'))
        self.assertEqual('2021-01-01 11:12:13', timezone.localtime(expected_obj.end_date).strftime('%Y-%m-%d %H:%M:%S'))
        self.assertTrue(expected_obj.is_active)
        self.assertEqual(10000, expected_obj.cashback_amount)
        self.assertEqual(['All'], expected_obj.partner)
        self.assertEqual(['All'], expected_obj.product_line)
        self.assertEqual(['All'], expected_obj.credit_score)

    def test_post_add_non_application(self):
        criteria = PromoCodeCriteriaFactory()
        benefit = PromoCodeBenefitFactory()
        url = reverse('admin:promo_promocode_add')
        post_data = {
            'promo_name': 'name',
            'promo_code': 'code',
            'description': 'long description',
            'type': PromoCodeTypeConst.LOAN,
            'start_date_0': '2020-01-01',
            'start_date_1': '11:12:13',
            'end_date_0': '2021-01-01',
            'end_date_1': '11:12:13',
            'is_active': True,
            'criteria': [str(criteria.id)],
            'promo_code_benefit': str(benefit.id),
        }
        res = self.client.post(url, post_data)

        expected_obj = PromoCode.objects.get(promo_name='name')
        self.assertIsNotNone(expected_obj)
        self.assertEqual(PromoCodeTypeConst.LOAN, expected_obj.type)
        self.assertEqual('CODE', expected_obj.promo_code)
        self.assertEqual('long description', expected_obj.description)
        self.assertEqual('2020-01-01 11:12:13', timezone.localtime(expected_obj.start_date).strftime('%Y-%m-%d %H:%M:%S'))
        self.assertEqual('2021-01-01 11:12:13', timezone.localtime(expected_obj.end_date).strftime('%Y-%m-%d %H:%M:%S'))
        self.assertTrue(expected_obj.is_active)
        self.assertEqual(benefit, expected_obj.promo_code_benefit)

    def test_get_change(self):
        obj = PromoCodeLoanFactory(
            promo_name='custom promo name',
        )
        url = reverse('admin:promo_promocode_change', args=[obj.id])
        res = self.client.get(url)

        self.assertContains(res, 'custom promo name')

    def test_post_change(self):
        criteria = PromoCodeCriteriaFactory()
        benefit = PromoCodeBenefitFactory()
        obj = PromoCodeFactory(
            promo_name='custom promo name',
        )
        url = reverse('admin:promo_promocode_change', args=[obj.id])

        post_data = {
            'promo_name': 'new name',
            'promo_code': 'newcode',
            'description': 'new long description',
            'type': PromoCodeTypeConst.LOAN,
            'start_date_0': '2020-01-01',
            'start_date_1': '11:12:13',
            'end_date_0': '2021-01-01',
            'end_date_1': '11:12:13',
            'is_active': True,
            'is_public': True,
            'criteria': [str(criteria.id)],
            'promo_code_benefit': str(benefit.id),
        }
        res = self.client.post(url, post_data)

        obj.refresh_from_db()
        self.assertEqual(PromoCodeTypeConst.LOAN, obj.type)
        self.assertEqual('new name', obj.promo_name)
        self.assertEqual('NEWCODE', obj.promo_code)
        self.assertEqual('new long description', obj.description)
        self.assertEqual('2020-01-01 11:12:13', timezone.localtime(obj.start_date).strftime('%Y-%m-%d %H:%M:%S'))
        self.assertEqual('2021-01-01 11:12:13', timezone.localtime(obj.end_date).strftime('%Y-%m-%d %H:%M:%S'))
        self.assertTrue(obj.is_active)
        self.assertEqual([criteria.id], obj.criteria)
        self.assertEqual(benefit, obj.promo_code_benefit)

    def test_get_delete(self):
        obj = PromoCodeLoanFactory()
        url = reverse('admin:promo_promocode_delete', args=[obj.id])
        res = self.client.get(url)

        self.assertContains(res, f'promo code "{obj}"')
        self.assertContains(res, 'Yes')

    def test_post_delete(self):
        obj = PromoCodeLoanFactory()
        url = reverse('admin:promo_promocode_delete', args=[obj.id])
        res = self.client.post(url, {'post': 'yes'})

        with self.assertRaises(PromoCode.DoesNotExist):
            PromoCode.objects.get(id=obj.id)
