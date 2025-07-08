import mock
from datetime import (
    timedelta,
)
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.apiv2.tests.factories import PdCollectionModelResultFactory
from juloserver.julo.tests.factories import (
    StatusLookupFactory,
    ExperimentSettingFactory,
)
from juloserver.minisquad.constants import (
    ExperimentConst,
)

from juloserver.minisquad.tasks2.notifications import send_pn_for_collection_tailor_experiment
from juloserver.moengage.models import MoengageUpload


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCollectionTailor(APITestCase):
    def setUp(self):
        self.current_date = timezone.localtime(timezone.now()).date()
        self.status = StatusLookupFactory(status_code=420)
        self.redis_data = {}
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.COLLECTION_TAILOR_EXPERIMENT,
            name=ExperimentConst.COLLECTION_TAILOR_EXPERIMENT,
            criteria={
                    "eligible_dpd": [
                        {"dpd": -4, "checking_dpd_at": -5}, {"dpd": -2, "checking_dpd_at": -3},
                        {"dpd": -1, "checking_dpd_at": -1}, {"dpd": 0, "checking_dpd_at": -1}
                    ],
                    "is_full_rollout": True,
                    "sort_method_list": ["elephant", "bull", "scorpion", "hamster"]},
            is_active=True,
        )

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data.get(key)

    def delete_redis(self, key):
        if key in self.redis_data:
            del self.redis_data[key]

    def get_redis_str(self, key):
        return str(self.redis_data.get(key))

    @mock.patch('juloserver.moengage.services.use_cases.get_redis_client')
    @mock.patch('juloserver.moengage.tasks.get_redis_client')
    @mock.patch('juloserver.moengage.services.use_cases.SendToMoengageManager')
    @mock.patch('juloserver.minisquad.tasks2.notifications.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.notifications.get_oldest_unpaid_account_payment_ids')
    def test_send_collection_tailor_attribute_to_moen(
            self, mock_get_oldest_unpaid_account_payment_ids, mock_redis_client,
            mock_moen_manager, mock_redis_on_moen_task, mock_redis_on_use_cases_task
    ):
        account = AccountFactory(ever_entered_B5=False, status=self.status)
        account.accountpayment_set.all().delete()
        account_payment = AccountPaymentFactory(
            account=account,
            due_date=self.current_date + timedelta(days=4),
            is_collection_called=False
        )
        PdCollectionModelResultFactory(
            account_payment=account_payment, sort_method='sort_03_elephant',
            range_from_due_date='-5'
        )
        mock_get_oldest_unpaid_account_payment_ids.return_value = [
            account_payment.id]
        mock_moen_manager.return_value.__enter__.return_value.add = None
        mock_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_redis_client.return_value.set.side_effect = self.set_redis
        mock_redis_client.return_value.get_list.side_effect = self.get_redis
        mock_redis_client.return_value.delete_key.side_effect = self.delete_redis

        mock_redis_on_moen_task.return_value.set_list.side_effect = self.set_redis
        mock_redis_on_moen_task.return_value.set.side_effect = self.set_redis
        mock_redis_on_moen_task.return_value.get_list.side_effect = self.get_redis
        mock_redis_on_moen_task.return_value.get.side_effect = self.get_redis_str
        mock_redis_on_moen_task.return_value.delete_key.side_effect = self.delete_redis

        mock_redis_on_use_cases_task.return_value.set_list.side_effect = self.set_redis
        mock_redis_on_use_cases_task.return_value.set.side_effect = self.set_redis
        mock_redis_on_use_cases_task.return_value.get_list.side_effect = self.get_redis
        mock_redis_on_use_cases_task.return_value.get.side_effect = self.get_redis_str
        mock_redis_on_use_cases_task.return_value.delete_key.side_effect = self.delete_redis

        send_pn_for_collection_tailor_experiment.delay()
        self.assertTrue(MoengageUpload.objects.filter(customer=account.customer).exists())
