import mock
from factory import Iterator
from django.test import TestCase
from django.utils import timezone
from django.test.utils import override_settings
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ExperimentSettingFactory,
    FeatureSettingFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.minisquad.tests.factories import AIRudderPayloadTempFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.ana_api.tests.factories import B2AdditionalAgentExperimentFactory
from juloserver.minisquad.constants import (
    ExperimentConst,
    DialerSystemConst,
    NewPDSExperiment,
    FeatureNameConst,
    ReasonNotSentToDialer,
)
from juloserver.minisquad.tasks2.dialer_system_task import new_pds_procces
from juloserver.minisquad.models import (
    AIRudderPayloadTemp,
    NotSentToDialer,
)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestPOCCIcare(TestCase):
    def setUp(self):
        self.today = timezone.localtime(timezone.now()).date()
        self.customers = CustomerFactory.create_batch(5)
        self.accounts = AccountFactory.create_batch(5, customer=Iterator(self.customers))
        self.account_payments = AccountPaymentFactory.create_batch(
            5,
            account=Iterator(self.accounts),
        )
        self.airudder_payload_temps = AIRudderPayloadTempFactory.create_batch(
            5,
            account_payment=Iterator(self.account_payments),
            account=Iterator(self.accounts),
            customer=Iterator(self.customers),
            bucket_name=DialerSystemConst.DIALER_BUCKET_2,
        )
        self.poc_exp = ExperimentSettingFactory(
            is_active=True,
            code=ExperimentConst.NEW_PDS,
            criteria={},
        )
        # set team A 2 account id, and team B 1 account id
        self.poc_data = B2AdditionalAgentExperimentFactory.create_batch(
            3,
            account_id=Iterator([account.id for account in self.accounts[:3]]),
            experiment_group=Iterator([2, 3, 2]),
            date_key=self.today,
        )
        self.feature = FeatureSettingFactory(
            feature_name=FeatureNameConst.AI_RUDDER_FULL_ROLLOUT, is_active=True
        )
        self.redis_data = {'NEW_PDS_EXPERIMENT_TEAM_B': [3]}

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task.send_data_to_dialer')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task.get_redis_client')
    def test_poc_c_icare_process(self, mock_redis_client, mock_send_data):
        mock_redis_client.return_value.delete_key.return_value = True
        mock_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_redis_client.return_value.get_list.side_effect = self.get_redis
        new_pds_procces.delay(
            bucket_name=DialerSystemConst.DIALER_BUCKET_2,
            is_mandatory_to_alert=True,
        )
        # POC C Icare team A
        poc_c_icare_team_a = AIRudderPayloadTemp.objects.filter(
            bucket_name=NewPDSExperiment.B2_EXPERIMENT
        ).count()
        self.assertEquals(2, poc_c_icare_team_a)
        # POC C Icare team B
        nstd_team_b = NotSentToDialer.objects.filter(
            unsent_reason=ReasonNotSentToDialer.UNSENT_REASON['NEW_PDS_EXPERIMENT'].strip("'")
        ).count()
        self.assertEquals(1, nstd_team_b)
        # B2 as is
        original_payload_b2 = AIRudderPayloadTemp.objects.filter(
            bucket_name=DialerSystemConst.DIALER_BUCKET_2
        ).count()
        self.assertEquals(2, original_payload_b2)
        mock_send_data.si.assert_called()
