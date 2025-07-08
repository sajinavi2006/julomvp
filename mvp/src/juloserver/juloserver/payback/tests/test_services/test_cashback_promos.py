from django.test.testcases import TestCase
from django.conf import settings

from juloserver.payback.services.cashback_promo import save_cashback_promo_file
from juloserver.payback.tests.factories import CashbackPromoFactory


class TestCashbackPromo(TestCase):
    def setUp(self):
        pass

    def test_save_cashback_promo_file(self):
        cashback_promo = CashbackPromoFactory()
        file = open(settings.BASE_DIR + '/juloserver/payback/tests/test_services/assets/test.csv', 'rb')
        number_of_customer, total_money = save_cashback_promo_file(cashback_promo, file, '')
        file.close()
        self.assertEqual(number_of_customer, 1)
        self.assertEqual(total_money, 10000)
