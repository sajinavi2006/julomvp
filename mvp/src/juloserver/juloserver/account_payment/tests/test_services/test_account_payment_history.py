from django.test import TestCase
from juloserver.account_payment.services.account_payment_history import update_account_payment_status_history
from juloserver.account_payment.services.account_payment_related import get_image_by_account_payment_id
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             CustomerFactory,
                                             ImageFactory)
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.account_payment.models import AccountPaymentStatusHistory
from juloserver.portal.object.loan_app.constants import ImageUploadType


class TestAccountPaymentHistory(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.image = ImageFactory(image_type=ImageUploadType.LATEST_PAYMENT_PROOF,
                                  image_source=self.account_payment.id,
                                  image_status=0)

    def test_update_account_payment_status_history(self):
        with update_account_payment_status_history(self.account_payment, 320):
            self.account_payment.update_safely(status_id=320)
        count = AccountPaymentStatusHistory.objects.filter(
                                    account_payment=self.account_payment,
                                    status_new_id=320).count()
        assert count == 1

    def test_get_image_by_account_payment_id(self):
        result = get_image_by_account_payment_id(self.account_payment.id)
        self.image.refresh_from_db()
        assert result == self.image

