from django.test import TestCase, override_settings
from mock import patch

from juloserver.entry_limit.factories import EntryLevelLimitConfigurationFactory
from juloserver.entry_limit.models import EntryLevelLimitHistory
from juloserver.entry_limit.services import EntryLevelLimitProcess
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    StatusLookupFactory,
)
from juloserver.application_flow.services import JuloOneService
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory


class TestEntryLevelLimitProcess(TestCase):
    @patch.object(EntryLevelLimitProcess, "check_entry_level_limit_config")
    @patch("juloserver.entry_limit.services.process_application_status_change")
    def test_entry_level_change_status_twice(self, mock_a, mock_b):
        application = ApplicationFactory()

        application.application_status = StatusLookupFactory(status_code=106)
        application.save()
        limit_history_cnt = EntryLevelLimitHistory.objects.filter(
            application_id=application.id
        ).count()
        self.assertEqual(limit_history_cnt, 0)

        # Run for the first time entry level hit
        ellp = EntryLevelLimitProcess(application.id)
        mock_b.return_value = EntryLevelLimitConfigurationFactory(action="106->120")
        ellp.start(120)
        limit_history_cnt = EntryLevelLimitHistory.objects.filter(
            application_id=application.id
        ).count()
        self.assertEqual(limit_history_cnt, 1)

        # Run again when for second entry level hit
        application.application_status = StatusLookupFactory(status_code=120)
        application.save()
        ellp = EntryLevelLimitProcess(application.id)
        mock_b.return_value = EntryLevelLimitConfigurationFactory(action="120->136")
        ellp.start(136)

        # check that the record should one, not incrementing
        limit_history_cnt = EntryLevelLimitHistory.objects.filter(
            application_id=application.id
        ).count()
        self.assertEqual(limit_history_cnt, 1)
        limit_history = EntryLevelLimitHistory.objects.filter(application_id=application.id).last()
        self.assertEqual(limit_history.action, "106->120")

    @patch.object(EntryLevelLimitProcess, "check_entry_level_limit_config")
    @patch("juloserver.entry_limit.services.process_application_status_change")
    def test_skip_entry_limit_when_ktp_needed(self, mock_1, mock_2):
        mock_2.return_value = EntryLevelLimitConfigurationFactory(action="136->124")

        # First we create application that history 131 with reason "KTP needed"
        application = ApplicationFactory()
        ApplicationHistoryFactory(
            application_id=application.id, status_new=131, change_reason="KTP needed"
        )

        # Then move it into 136
        application.application_status = StatusLookupFactory(status_code=136)
        application.save()
        ApplicationHistoryFactory(
            application_id=application.id,
            status_new=136,
            change_reason="status_expired",
        )

        # Then move it into 124 -> it should not trigger entry limit
        ellp = EntryLevelLimitProcess(application.id)
        ellp.start(124)

        # assert the test
        limit_history_cnt = EntryLevelLimitHistory.objects.filter(
            application_id=application.id
        ).count()
        self.assertEqual(limit_history_cnt, 0)

    @patch.object(EntryLevelLimitProcess, "check_entry_level_limit_config")
    @patch("juloserver.entry_limit.services.process_application_status_change")
    def test_skip_entry_limit_when_selfie_needed(self, mock_1, mock_2):
        mock_2.return_value = EntryLevelLimitConfigurationFactory(action="136->124")

        # First we create application that history 131 with reason "KTP needed"
        application = ApplicationFactory()
        ApplicationHistoryFactory(
            application_id=application.id, status_new=131, change_reason="Selfie needed"
        )

        # Then move it into 136
        application.application_status = StatusLookupFactory(status_code=136)
        application.save()
        ApplicationHistoryFactory(
            application_id=application.id,
            status_new=136,
            change_reason="status_expired",
        )

        # Then move it into 124 -> it should not trigger entry limit
        ellp = EntryLevelLimitProcess(application.id)
        ellp.start(124)

        # assert the test
        limit_history_cnt = EntryLevelLimitHistory.objects.filter(
            application_id=application.id
        ).count()
        self.assertEqual(limit_history_cnt, 0)

    @patch.object(EntryLevelLimitProcess, "check_entry_level_limit_config")
    @patch("juloserver.entry_limit.services.process_application_status_change")
    def test_skip_entry_limit_when_offer_declined_by_customer(self, mock_1, mock_2):
        mock_2.return_value = EntryLevelLimitConfigurationFactory(action="135->124")

        # Create an application that has an offer declined by customer status
        application = ApplicationFactory()
        ApplicationHistoryFactory(
            application_id=application.id, status_new=130, change_reason="PV Employer Verified"
        )

        application.application_status = StatusLookupFactory(status_code=135)
        application.save()
        ApplicationHistoryFactory(
            application_id=application.id,
            status_new=142,
            change_reason='Affordability value lower than threshold',
        )
        ApplicationHistoryFactory(
            application_id=application.id, status_new=135, change_reason='Ops request'
        )

        # Attempt to trigger the entry level limit
        ellp = EntryLevelLimitProcess(application.id)
        ellp.start(124)

        should_cancel = ellp._should_cancel_entry_limit()
        self.assertTrue(should_cancel)

        # Assert that the limit history count is 0
        limit_history_cnt = EntryLevelLimitHistory.objects.filter(
            application_id=application.id
        ).count()
        self.assertEqual(limit_history_cnt, 0)

    @patch.object(EntryLevelLimitProcess, "check_entry_level_limit_config")
    @patch("juloserver.entry_limit.services.process_application_status_change")
    def test_entry_limit_bypass_124(self, mock_1, mock_2):
        mock_2.return_value = EntryLevelLimitConfigurationFactory(action="135->124")

        # Create an application that has an offer declined by customer status
        application = ApplicationFactory()
        ApplicationHistoryFactory(
            application_id=application.id, status_new=130, change_reason="PV Employer Verified"
        )

        application.application_status = StatusLookupFactory(status_code=135)
        application.save()

        ApplicationHistoryFactory(
            application_id=application.id, status_new=135, change_reason='Ops request'
        )

        ApplicationHistoryFactory(
            application_id=application.id,
            status_new=142,
            change_reason='Affordability value lower than threshold',
        )

        ellp = EntryLevelLimitProcess(application.id)
        self.assertEqual(ellp.can_bypass_124(), False)

    @patch.object(EntryLevelLimitProcess, "check_entry_level_limit_config")
    @patch("juloserver.entry_limit.services.process_application_status_change")
    def test_entry_limit_bypass_141(self, mock_1, mock_2):
        mock_2.return_value = EntryLevelLimitConfigurationFactory(action="130->141")

        application = ApplicationFactory()
        application.application_status = StatusLookupFactory(status_code=130)
        application.save()

        ApplicationHistoryFactory(
            application_id=application.id, status_new=130, change_reason="PV Employer Verified"
        )

        ApplicationHistoryFactory(
            application_id=application.id,
            status_new=142,
            change_reason='Affordability value lower than threshold',
        )

        ellp = EntryLevelLimitProcess(application.id)
        self.assertEqual(ellp.can_bypass_141(), False)

    @patch.object(EntryLevelLimitProcess, "check_entry_level_limit_config")
    @patch("juloserver.entry_limit.services.process_application_status_change")
    def test_skip_entry_limit_when_name_validate_failed_history_name_validate_failed(
        self, mock_1, mock_2
    ):
        mock_2.return_value = EntryLevelLimitConfigurationFactory(action="135->124")

        # Create an application that has an offer declined by customer status
        application = ApplicationFactory()
        application.application_status = StatusLookupFactory(status_code=135)
        application.save()
        ApplicationHistoryFactory(
            application_id=application.id, status_new=130, change_reason="PV Employer Verified"
        )
        ApplicationHistoryFactory(
            application_id=application.id,
            status_new=175,
            change_reason='Name validation failed',
        )
        ApplicationHistoryFactory(
            application_id=application.id, status_new=135, change_reason='Ops request'
        )

        # Attempt to trigger the entry level limit
        ellp = EntryLevelLimitProcess(application.id)
        ellp.start(124)
        should_cancel = ellp._should_cancel_entry_limit()
        self.assertTrue(should_cancel)

        # Assert that the limit history count is 0
        limit_history_cnt = EntryLevelLimitHistory.objects.filter(
            application_id=application.id
        ).count()
        self.assertEqual(limit_history_cnt, 0)

    @patch.object(EntryLevelLimitProcess, "check_entry_level_limit_config")
    @patch("juloserver.entry_limit.services.process_application_status_change")
    def test_entry_limit_bypass_124_when_name_validate_failed_history(self, mock_1, mock_2):
        mock_2.return_value = EntryLevelLimitConfigurationFactory(action="135->124")

        # Create an application that has a name validate failed history
        application = ApplicationFactory()
        application.application_status = StatusLookupFactory(status_code=135)
        application.save()

        ApplicationHistoryFactory(
            application_id=application.id, status_new=130, change_reason="PV Employer Verified"
        )
        ApplicationHistoryFactory(
            application_id=application.id, status_new=135, change_reason='Ops request'
        )
        ApplicationHistoryFactory(
            application_id=application.id,
            status_new=175,
            change_reason='Name validation failed',
        )

        ellp = EntryLevelLimitProcess(application.id)
        self.assertEqual(ellp.can_bypass_124(), False)

    @patch.object(EntryLevelLimitProcess, "check_entry_level_limit_config")
    @patch("juloserver.entry_limit.services.process_application_status_change")
    def test_entry_limit_bypass_141_name_validate_failed_history(self, mock_1, mock_2):
        mock_2.return_value = EntryLevelLimitConfigurationFactory(action="130->141")

        # Create an application that has a name validate failed history
        application = ApplicationFactory()
        application.application_status = StatusLookupFactory(status_code=130)
        application.save()

        ApplicationHistoryFactory(
            application_id=application.id, status_new=130, change_reason="PV Employer Verified"
        )
        ApplicationHistoryFactory(
            application_id=application.id,
            status_new=175,
            change_reason='Name validation failed',
        )

        ellp = EntryLevelLimitProcess(application.id)
        self.assertEqual(ellp.can_bypass_141(), False)

    @patch.object(EntryLevelLimitProcess, "has_account_deletion_request")
    @patch.object(EntryLevelLimitProcess, "_should_cancel_entry_limit")
    @patch.object(EntryLevelLimitProcess, "_check_is_spouse_registered")
    @patch.object(EntryLevelLimitProcess, "check_entry_level_limit_config")
    def test_start_custom_parameters_and_force_got_config_id(self, mock_1, mock_2, mock_3, mock_4):

        # mock
        mock_1.return_value = None
        mock_2.return_value = False
        mock_3.return_value = False
        mock_4.return_value = False

        # prepare test data
        test_data = [
            ("empty custom parameters and force_got_config_id", None, None),
            ("filled custom parameters", {"min_threshold__lte": 100}, None),
            ("filled force_got_config_id", None, 1),
            ("filled custom parameters and force_got_config_id", {"min_threshold__lte": 100}, 1),
        ]

        for (description, custom_parameters, force_got_config_id) in test_data:
            with self.subTest(description=description):
                # create application that passed validation
                application = ApplicationFactory()
                application.application_status = StatusLookupFactory(status_code=135)

                ellp = EntryLevelLimitProcess(application.id)
                ellp.start(
                    application.status,
                    custom_parameters=custom_parameters,
                    force_got_config_id=force_got_config_id,
                )

                mock_1.assert_called_with(
                    status=application.status,
                    custom_parameters=custom_parameters,
                    force_got_config_id=force_got_config_id,
                )

    @patch("juloserver.application_flow.services.has_good_score_mycroft")
    @patch.object(JuloOneService, "is_high_c_score")
    @patch.object(JuloOneService, "is_c_score")
    @patch("juloserver.account.services.credit_limit.get_credit_model_result")
    @patch("juloserver.account.services.credit_limit.get_credit_matrix_type")
    @patch("juloserver.account.services.credit_limit.get_salaried")
    @patch("juloserver.account.services.credit_limit.is_inside_premium_area")
    def test_check_entry_level_limit_config_custom_parameters_and_force_id(
        self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6, mock_7
    ):

        # mock
        mock_1.return_value = False
        mock_2.return_value = False
        mock_5.return_value = False
        mock_6.return_value = False
        mock_7.return_value = True

        # prepare factories
        ellc1 = EntryLevelLimitConfigurationFactory(
            action="135->124", min_threshold=0.75, is_premium_area=False, is_salaried=False
        )
        ellc2 = EntryLevelLimitConfigurationFactory(
            action="135->124", min_threshold=0.80, is_premium_area=False, is_salaried=False
        )

        # prepare test data
        # description, custom_parameters, force_got_config_id, pgood, credit_matrix_type, expectation (matched config)
        test_data = [
            ("not match with criteria", None, None, 0.65, "julo1", None),
            ("match with criteria", None, None, 0.75, "julo1", ellc1),
            ("invalid customer category", None, None, 0.75, "julo1123", None),
            (
                "bypass min_threshold to be 100",
                {"min_threshold__lte": 100},
                None,
                0.65,
                "julo1",
                ellc1,
            ),
            (
                "bypass min_threshold to be 80",
                {"min_threshold__lte": 80},
                None,
                0.65,
                "julo1",
                ellc1,
            ),
            (
                "bypass min_threshold but invalid customer category",
                {"min_threshold__lte": 80},
                None,
                0.65,
                "julo1123",
                None,
            ),
            (
                "bypass customer category",
                {"customer_category": "julo1"},
                None,
                0.95,
                "julo1123",
                ellc1,
            ),
            ("force got config ellc1", None, ellc1, 0.65, "julo1123", ellc1),
            ("force got config ellc2", None, ellc2, 0.65, "julo1123", ellc2),
            (
                "bypass min_threshold and force got config ellc2",
                {"min_threshold__lte": 100},
                ellc2,
                0.65,
                "julo1",
                ellc2,
            ),
        ]

        idx = 1
        for (
            description,
            custom_parameters,
            force_got_config,
            pgood,
            credit_matrix_type,
            expectation_config,
        ) in test_data:
            with self.subTest(description=description):
                application = ApplicationFactory()

                mock_3.return_value = credit_matrix_type
                mock_4.return_value = PdCreditModelResultFactory(
                    id=idx, application_id=application.id, pgood=pgood
                )

                application.application_status = StatusLookupFactory(status_code=135)

                ellp = EntryLevelLimitProcess(application.id)
                force_got_config_id = None
                if force_got_config:
                    force_got_config_id = force_got_config.id
                result = ellp.check_entry_level_limit_config(
                    status=application.status,
                    custom_parameters=custom_parameters,
                    force_got_config_id=force_got_config_id,
                )
                if result:
                    self.assertEqual(result.id, expectation_config.id, description)
                else:
                    self.assertEqual(result, None, description)
                idx += 1

    def test_modify_filter_based_on_custom_parameters(
        self,
    ):
        # prepare test data
        # test data : custom parameters
        ex_custom_parameters = {
            "customer_category": "julo1",
            "product_line": 1,
            "is_premium_area": True,
            "is_salaried": True,
            "min_threshold__lte": 0.75,
        }
        ex_custom_parameters_invalid_pgood = {
            "customer_category": "julo1",
            "product_line": 1,
            "is_premium_area": True,
            "is_salaried": True,
        }
        ex_custom_parameters_invalid_salaried = {
            "customer_category": "julo1",
            "product_line": 1,
            "is_premium_area": True,
            "min_threshold__lte": 0.75,
        }
        ex_custom_parameters_invalid_key = {
            "customer_category": "julo1",
            "product_line": 1,
            "is_premium_area": True,
            "is_salaried": True,
            "min_thresholdlte": 0.75,
        }
        ex_custom_parameters_empty = {}
        # test data : new_parameters
        ex_new_parameters_pgood = {"min_threshold__lte": 1}
        ex_new_parameters_invalid = {"min_threshold": 1}
        ex_new_parameters_salaried = {"is_salaried": False}
        ex_new_parameters_empty = {}
        ex_new_parameters_full = {
            "customer_category": "juloturbo",
            "product_line": 2,
            "is_premium_area": False,
            "is_salaried": False,
            "min_threshold__lte": 1,
        }
        # test_data : expectation (as return value)
        ex_return_value_no_changes = {
            "customer_category": "julo1",
            "product_line": 1,
            "is_premium_area": True,
            "is_salaried": True,
            "min_threshold__lte": 0.75,
        }
        ex_return_value_pgood_changes = {
            "customer_category": "julo1",
            "product_line": 1,
            "is_premium_area": True,
            "is_salaried": True,
            "min_threshold__lte": 1,
        }
        ex_return_value_salaried_changes = {
            "customer_category": "julo1",
            "product_line": 1,
            "is_premium_area": True,
            "is_salaried": False,
            "min_threshold__lte": 0.75,
        }
        ex_return_value_full_changes = {
            "customer_category": "juloturbo",
            "product_line": 2,
            "is_premium_area": False,
            "is_salaried": False,
            "min_threshold__lte": 1,
        }
        ex_return_value_invalid_pgood = {
            "customer_category": "julo1",
            "product_line": 1,
            "is_premium_area": True,
            "is_salaried": True,
        }
        ex_return_value_invalid_key = {
            "customer_category": "julo1",
            "product_line": 1,
            "is_premium_area": True,
            "is_salaried": True,
            "min_thresholdlte": 0.75,
        }

        # description, current_parameters, new_parameters, expectation
        test_data = [
            ("no changes", ex_custom_parameters, None, ex_return_value_no_changes),
            (
                "pgood changes",
                ex_custom_parameters,
                ex_new_parameters_pgood,
                ex_return_value_pgood_changes,
            ),
            (
                "invalid pgood changes",
                ex_custom_parameters,
                ex_new_parameters_invalid,
                ex_return_value_no_changes,
            ),
            (
                "salary changes",
                ex_custom_parameters,
                ex_new_parameters_salaried,
                ex_return_value_salaried_changes,
            ),
            (
                "empty changes",
                ex_custom_parameters,
                ex_new_parameters_empty,
                ex_return_value_no_changes,
            ),
            (
                "full changes",
                ex_custom_parameters,
                ex_new_parameters_full,
                ex_return_value_full_changes,
            ),
            (
                "invalid custom_parameter pgood with pgood changes",
                ex_custom_parameters_invalid_pgood,
                ex_new_parameters_pgood,
                ex_return_value_pgood_changes,
            ),
            (
                "invalid custom_parameter pgood with invalid changes",
                ex_custom_parameters_invalid_pgood,
                ex_new_parameters_invalid,
                ex_return_value_invalid_pgood,
            ),
            (
                "invalid custom_parameter pgood with full changes",
                ex_custom_parameters_invalid_pgood,
                ex_new_parameters_full,
                ex_return_value_full_changes,
            ),
            (
                "invalid custom_parameter salary with full changes",
                ex_custom_parameters_invalid_salaried,
                ex_new_parameters_full,
                ex_return_value_full_changes,
            ),
            (
                "invalid custom_parameter key with full changes",
                ex_custom_parameters_invalid_key,
                ex_new_parameters_full,
                ex_return_value_invalid_key,
            ),
            (
                "empty custom_parameter with full changes",
                ex_custom_parameters_empty,
                ex_new_parameters_full,
                ex_return_value_full_changes,
            ),
            ("null custom_parameter with full changes", None, ex_new_parameters_full, None),
        ]

        for (
            description,
            current_parameters,
            new_parameters,
            expectation,
        ) in test_data:
            with self.subTest(description=description):
                application = ApplicationFactory()
                application.application_status = StatusLookupFactory(status_code=135)

                ellp = EntryLevelLimitProcess(application.id)
                result = ellp._modify_filter_based_on_custom_parameters(
                    current_parameters, new_parameters
                )
                self.assertEqual(result, expectation, description)
