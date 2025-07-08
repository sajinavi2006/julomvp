from unittest import mock
from datetime import datetime, date
from django.test import TestCase

from juloserver.julo.tests.factories import (
    CustomerFactory,
    ChurnUserFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.promo.tests.factories import (
    PromoCodeCriteriaFactory,
    CriteriaControlListFactory,
)
from juloserver.promo.constants import PromoCodeCriteriaConst
from juloserver.promo.tasks import upload_whitelist_customers_data_for_raven_experiment
from juloserver.promo.models import CriteriaControlList


class TestUploadWhitelistRavenExperimentModel(TestCase):
    def setUp(self):
        self.customer_A = CustomerFactory()
        self.account_A = AccountFactory(customer=self.customer_A)
        self.customer_B = CustomerFactory()
        self.account_B = AccountFactory(customer=self.customer_B)

        # Init promo criteria raven A
        self.criterion_whitelist_A = PromoCodeCriteriaFactory(
            pk=143,
            name="raven model A",
            type=PromoCodeCriteriaConst.WHITELIST_CUSTOMERS,
            value={}
        )

        # Init promo criteria raven B
        self.criterion_whitelist_B = PromoCodeCriteriaFactory(
            pk=144,
            name="raven model B",
            type=PromoCodeCriteriaConst.WHITELIST_CUSTOMERS,
            value={}
        )

    def set_up_churn_customer(self):
        # Customer with model A
        self.churn_customer_A = ChurnUserFactory(
            customer_id=self.customer_A.id,
            experiment_group="model_A",
            predict_date=date(2024, 4, 9),
        )

        # Customer with model B
        self.churn_customer_B = ChurnUserFactory(
            customer_id=self.customer_B.id,
            experiment_group="model_B",
            predict_date=date(2024, 3, 26),
        )

    @mock.patch('django.utils.timezone.now')
    def test_create_new_whitelist_customers_raven_experiment(self, mock_now):
        mock_now.return_value = datetime(2024, 4, 9, 1, 0, 0)

        # No need to create exists customer in CriteriaControlList
        self.set_up_churn_customer()
        upload_whitelist_customers_data_for_raven_experiment()

        # Check promo_code_control_list
        whitelist_customer_model_A = CriteriaControlList.objects.get(
            customer_id=self.customer_A.id,
            promo_code_criteria_id=self.criterion_whitelist_A.id
        )
        whitelist_customer_model_B = CriteriaControlList.objects.get(
            customer_id=self.customer_B.id,
            promo_code_criteria_id=self.criterion_whitelist_B.id
        )

        self.assertIsNotNone(whitelist_customer_model_A)
        self.assertIsNotNone(whitelist_customer_model_B)
        self.assertEqual(whitelist_customer_model_A.is_deleted, False)
        self.assertEqual(whitelist_customer_model_B.is_deleted, False)

    @mock.patch('django.utils.timezone.now')
    def test_update_exists_whitelist_customers_raven_experiment(self, mock_now):
        mock_now.return_value = datetime(2024, 4, 9, 1, 0, 0)
        # Create exists customer in CriteriaControlList
        exists_whitelist_customer_A = CriteriaControlListFactory(
            customer_id=self.customer_A.id,
            promo_code_criteria=self.criterion_whitelist_A,
            is_deleted=True,
        )
        exists_whitelist_customer_B = CriteriaControlListFactory(
            customer_id=self.customer_B.id,
            promo_code_criteria=self.criterion_whitelist_B,
        )

        self.set_up_churn_customer()
        upload_whitelist_customers_data_for_raven_experiment()

        # Check promo_code_control_list
        whitelist_customer_model_A = CriteriaControlList.objects.get(
            customer_id=self.customer_A.id,
            promo_code_criteria_id=self.criterion_whitelist_A.id
        )
        whitelist_customer_model_B = CriteriaControlList.objects.get(
            customer_id=self.customer_B.id,
            promo_code_criteria_id=self.criterion_whitelist_B.id
        )

        self.assertIsNotNone(whitelist_customer_model_A)
        self.assertIsNotNone(whitelist_customer_model_B)
        self.assertEqual(whitelist_customer_model_A.is_deleted, False)
        self.assertEqual(whitelist_customer_model_B.is_deleted, False)

    @mock.patch('django.utils.timezone.now')
    def test_no_customers_from_pd_churn(self, mock_now):
        # 16 days after the last predict_date
        mock_now.return_value = datetime(2024, 4, 11, 1, 0, 0)
        # Create exists customer in CriteriaControlList
        exists_whitelist_customer_A = CriteriaControlListFactory(
            customer_id=self.customer_A.id,
            promo_code_criteria=self.criterion_whitelist_A,
        )
        exists_whitelist_customer_B = CriteriaControlListFactory(
            customer_id=self.customer_B.id,
            promo_code_criteria=self.criterion_whitelist_B,
        )

        self.set_up_churn_customer()
        upload_whitelist_customers_data_for_raven_experiment()

        # Check promo_code_control_list
        whitelist_customer_model_A = CriteriaControlList.objects.get(
            customer_id=self.customer_A.id,
            promo_code_criteria_id=self.criterion_whitelist_A.id
        )
        whitelist_customer_model_B = CriteriaControlList.objects.get(
            customer_id=self.customer_B.id,
            promo_code_criteria_id=self.criterion_whitelist_B.id
        )

        # A 2 days, B 16 days --> update A, delete B
        self.assertIsNotNone(whitelist_customer_model_A)
        self.assertIsNotNone(whitelist_customer_model_B)
        self.assertEqual(whitelist_customer_model_A.is_deleted, False)
        self.assertEqual(whitelist_customer_model_B.is_deleted, True)

    @mock.patch('django.utils.timezone.now')
    def test_delete_whitelist_customers_raven_experiment(self, mock_now):
        mock_now.return_value = datetime(2024, 4, 9, 1, 0, 0)

        # Create exists customer in CriteriaControlList
        exists_whitelist_customer_A = CriteriaControlListFactory(
            customer_id=self.customer_A.id,
            promo_code_criteria=self.criterion_whitelist_A,
        )
        exists_whitelist_customer_B = CriteriaControlListFactory(
            customer_id=self.customer_B.id,
            promo_code_criteria=self.criterion_whitelist_B,
        )
        # Create customer in CriteriaControlList, not in PdChurnModel --> delete
        self.customer_C = CustomerFactory()
        self.account_C = AccountFactory(customer=self.customer_C)
        exists_whitelist_customer_C = CriteriaControlListFactory(
            customer_id=self.customer_C.id,
            promo_code_criteria=self.criterion_whitelist_B,
        )

        self.set_up_churn_customer()
        upload_whitelist_customers_data_for_raven_experiment()

        # Check promo_code_control_list
        whitelist_customer_model_A = CriteriaControlList.objects.get(
            customer_id=self.customer_A.id,
            promo_code_criteria_id=self.criterion_whitelist_A.id
        )
        whitelist_customer_model_B = CriteriaControlList.objects.get(
            customer_id=self.customer_B.id,
            promo_code_criteria_id=self.criterion_whitelist_B.id
        )
        whitelist_customer_model_C = CriteriaControlList.objects.get(
            customer_id=self.customer_C.id,
            promo_code_criteria_id=self.criterion_whitelist_B.id
        )

        self.assertIsNotNone(whitelist_customer_model_A)
        self.assertIsNotNone(whitelist_customer_model_B)
        self.assertIsNotNone(whitelist_customer_model_C)
        self.assertEqual(whitelist_customer_model_A.is_deleted, False)
        self.assertEqual(whitelist_customer_model_B.is_deleted, False)
        self.assertEqual(whitelist_customer_model_C.is_deleted, True)
