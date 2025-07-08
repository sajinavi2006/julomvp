import mock
from django.test import TestCase
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             CustomerFactory,
                                             ApplicationFactory)
from juloserver.account_payment.models import *
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory

class TestAccountPaymentModels(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.save()

    @mock.patch('juloserver.julo.services2.get_redis_client')
    def test_account_payment_queryset(self, mock_redis_client):
        mock_redis_client.return_value.get_list.return_value = []
        qs = AccountPayment.objects.not_paid_active()
        qs.bucket_1_t0([1,2,3])
        qs.bucket_1_minus(5, [1,2,3])
        qs.bucket_1_t_minus_1([1,2,3])
        qs.bucket_1_plus(1, 5, [1,2,3])
        qs.bucket_1_t1_t4([1,2,3])
        qs.bucket_1_t5_t10([1,2,3])
        qs.bucket_1_t1_t10([1,2,3])
        qs.dpd_to_be_called()
        qs.get_bucket_1()
        qs.get_bucket_2()
        qs.get_bucket_3()
        qs.get_bucket_4()
        qs.determine_bucket_by_range([5,2,3])
        qs.list_bucket_group_with_range(1,5)
        qs.bucket_list_t11_to_t40()
        qs.bucket_list_t41_to_t70()
        qs.bucket_list_t71_to_t90()
        qs.paid_or_partially_paid()
        qs.by_product_line_codes([10,1])
    
    def test_account_payment_manager(self):
        AccountPayment.objects.not_paid_active()
        AccountPayment.objects.paid_or_partially_paid()
        AccountPayment.objects.failed_automated_robocall_account_payments([1,10],5)
        AccountPayment.objects.tobe_robocall_account_payments([1,10],[5])
        AccountPayment.objects.status_tobe_update()
    
    def test_account_payment_properties(self):
        self.account_payment.cashback_multiplier
        self.account_payment.dpd
        self.account_payment.payment_number
        self.account_payment.due_late_days
        self.account_payment.due_status()
        self.account_payment.update_paid_date_based_on_payment()
        self.account_payment.paid_late_days
        self.account_payment.update_late_fee_amount(12000)
        self.account_payment.change_status(321)
        self.account_payment.paid_status_str
        self.account_payment.due_status_str
        self.account_payment.paid_off_status_str
        self.account_payment.bucket_number
        self.account_payment.max_cashback_earned
        self.account_payment.total_redeemed_cashback
        self.account_payment.total_cashback_earned
