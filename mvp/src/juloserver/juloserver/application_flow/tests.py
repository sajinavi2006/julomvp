import json
import os
from copy import deepcopy
from datetime import (
    datetime,
    timedelta,
    date,
)

from dateutil.relativedelta import relativedelta

import pytest
import responses
from django.contrib.auth.hashers import make_password
from django.test.testcases import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from factory import Iterator
from mock import (
    MagicMock,
    patch,
)
from mock_django.query import QuerySetMock
from requests import Response
from rest_framework.test import APIClient, APITestCase

import juloserver.julo.services
import juloserver.julo_starter.services.onboarding_check
from juloserver.account.models import (
    Account,
    AccountLimit,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountLookupFactory,
)
from juloserver.ana_api.tests.factories import (
    PdApplicationFraudModelResultFactory,
    SdBankAccountFactory,
    SdBankStatementDetailFactory,
    EligibleCheckFactory,
    PdApplicationFraudModelResult,
)
from juloserver.ana_api.models import SdDevicePhoneDetail
from juloserver.apiv2.tests.factories import (
    PdCreditModelResultFactory,
    SdDeviceAppFactory,
    AutoDataCheckFactory,
)
from juloserver.application_flow.factories import (
    ApplicationRiskyCheckFactory,
    ApplicationRiskyDecisionFactory,
    MycroftThresholdFactory,
    SuspiciousFraudAppsFactory,
    LevenshteinLogFactory,
    ApplicationTagFactory,
    ApplicationPathTagStatusFactory,
)
from juloserver.application_flow.handlers import JuloOne141Handler
from juloserver.application_flow.models import (
    EmulatorCheck,
    MycroftResult,
    ApplicationNameBankValidationChange,
    ApplicationPathTag,
    ApplicationPathTagStatus,
    TelcoScoringResult,
)
from juloserver.application_flow.models import ShopeeScoring as ScoringModel
from juloserver.application_flow.models import SuspiciousFraudApps
from juloserver.application_flow.services import (
    ApplicationTagTracking,
    JuloOneByPass,
    list_experiment_application,
    still_in_experiment,
    is_referral_blocked,
    suspicious_app_check,
)
from juloserver.application_flow.services2.telco_scoring import TelcoScore, Telkomsel, Indosat, XL
from juloserver.application_flow.tasks import (
    mycroft_check,
    revalidate_name_bank_validation,
)
from juloserver.application_flow.workflows import JuloOneWorkflowAction
from juloserver.bpjs.tests.factories import SdBpjsCompanyFactory, SdBpjsProfileFactory
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.followthemoney.factories import InventorUserFactory
from juloserver.julo.constants import (
    ApplicationStatusCodes,
    ExperimentConst,
    WorkflowConst,
    OnboardingIdConst,
    FeatureNameConst,
    ProductLineCodes,
)
from juloserver.julo.models import (
    ApplicationHistory,
    ExperimentSetting,
    WorkflowStatusNode,
    WorkflowStatusPath,
    CreditScore,
)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.tests.factories import (
    AffordabilityHistoryFactory,
    ApplicationFactory,
    ApplicationJ1Factory,
    AuthUserFactory,
    BankFactory,
    CreditMatrixFactory,
    CurrentCreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditScoreFactory,
    CustomerFactory,
    CustomerRemovalFactory,
    DeviceFactory,
    ExperimentFactory,
    ExperimentSettingFactory,
    ExperimentTestGroupFactory,
    FeatureSettingFactory,
    HighScoreFullBypassFactory,
    MobileFeatureSettingFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
    OnboardingFactory,
    ReferralSystemFactory,
    FDCInquiryFactory,
    FDCInquiryLoanFactory,
)
from juloserver.julo.workflows2.tasks import (
    do_advance_ai_id_check_task,
    update_status_apps_flyer_task,
)
from juloserver.julovers.tests.factories import (
    WorkflowStatusPathFactory,
    WorkflowStatusNodeFactory,
)

from juloserver.application_flow.services import (
    JuloOneService,
    create_or_update_application_risky_check,
    determine_by_experiment_julo_starter,
    has_application_rejection_history,
    send_application_event_by_certain_pgood,
    send_application_event_for_x100_device_info,
    send_application_event_for_x105_bank_name_info,
    send_application_event_base_on_mycroft,
)
from juloserver.application_flow.services2 import ShopeeScoring
from juloserver.application_flow.services2.bank_validation import (
    remove_prefix,
    remove_non_alphabet,
)
from juloserver.application_flow.tasks import (
    check_mycroft_holdout,
    handle_google_play_integrity_decode_request_task,
    handle_iti_ready,
    reject_application_by_google_play_integrity_task,
)
from juloserver.application_flow.exceptions import PlayIntegrityDecodeError
from juloserver.new_crm.tests.factories import ApplicationPathTagFactory
from juloserver.personal_data_verification.constants import DukcapilDirectError
from juloserver.personal_data_verification.tests.factories import DukcapilResponseFactory

from juloserver.personal_data_verification.constants import DukcapilDirectError
from juloserver.customer_module.models import BankAccountDestination
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.models import NameBankValidation
from juloserver.apiv2.services import get_credit_score3
from juloserver.disbursement.services.xfers import XfersService
from juloserver.personal_data_verification.tests.factories import (
    DukcapilResponseFactory,
    DukcapilFaceRecognitionCheckFactory,
)
from juloserver.apiv2.services import get_credit_score3
from juloserver.customer_module.models import BankAccountDestination
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.models import NameBankValidation
from juloserver.disbursement.services.xfers import XfersService
from juloserver.application_flow.services import is_suspicious_domain
from juloserver.julo.tests.factories import SuspiciousDomainFactory
from juloserver.julocore.cache_client import get_loc_mem_cache
from juloserver.application_flow.services2.shopee_scoring import ShopeeWhitelist
from juloserver.fraud_security.binary_check import BlacklistedCompanyHandler
from ..new_crm.tests.factories import ApplicationPathTagFactory
from juloserver.application_flow.services2.telco_scoring import TelcoScore
from juloserver.fraud_security.constants import FraudChangeReason
from juloserver.julocore.tests import force_run_on_commit_hook
from juloserver.fraud_security.tests.factories import FraudHighRiskAsnFactory
from juloserver.fraud_security.binary_check import BlacklistedCompanyHandler
from juloserver.application_flow.services2.bank_statement import PowerCred
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.partnership.constants import PartnershipPreCheckFlag
from juloserver.partnership.tests.factories import PartnershipApplicationFlagFactory
from juloserver.julo.services2.redis_helper import MockRedisHelper

from juloserver.fraud_security.binary_check import BlacklistedGeohash5Handler
from juloserver.application_flow.handlers import JuloOne105Handler
from juloserver.application_flow.tasks import process_clik_model
from juloserver.application_flow.constants import HSFBPIncomeConst


def update_status_apps_flyer_task_mock(app_data, *arg, **kargs):
    update_status_apps_flyer_task(*app_data)


def mock_do_advance_ai_id_check_task_mock(app_id, *arg, **kargs):
    do_advance_ai_id_check_task(app_id)


class TestJuloOneWorkflows(TestCase):
    @classmethod
    def setUp(cls):
        cls.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        cls.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        cls.user = AuthUserFactory()
        cls.customer = CustomerFactory()
        cls.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        WorkflowStatusPath.objects.create(
            status_previous=105, status_next=120, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=120, status_next=124, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=124, status_next=130, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=141, status_next=150, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=150, status_next=190, workflow=cls.julo_one_workflow
        )
        WorkflowStatusNode.objects.create(
            status_node=105, handler='JuloOne105Handler', workflow=cls.julo_one_workflow
        )
        WorkflowStatusNode.objects.create(
            status_node=122, handler='JuloOne122Handler', workflow=cls.julo_one_workflow
        )
        WorkflowStatusNode.objects.create(
            status_node=124, handler='JuloOne124Handler', workflow=cls.julo_one_workflow
        )
        WorkflowStatusNode.objects.create(
            status_node=150, handler='JuloOne150Handler', workflow=cls.julo_one_workflow
        )
        WorkflowStatusNode.objects.create(
            status_node=190, handler='JuloOne190Handler', workflow=cls.julo_one_workflow
        )
        WorkflowStatusNode.objects.create(
            status_node=130, handler='JuloOne130Handler', workflow=cls.julo_one_workflow
        )
        WorkflowStatusNode.objects.create(
            status_node=141, handler='JuloOne141Handler', workflow=cls.julo_one_workflow
        )
        WorkflowStatusNode.objects.create(
            status_node=124, handler='JuloOne124Handler', workflow=cls.julo_one_workflow
        )
        WorkflowStatusNode.objects.create(
            status_node=150, handler='JuloOne150Handler', workflow=cls.julo_one_workflow
        )
        WorkflowStatusNode.objects.create(
            status_node=190, handler='JuloOne190Handler', workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=120, status_next=121, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=121, status_next=122, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=122, status_next=124, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=130, status_next=141, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=130, status_next=142, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=134, status_next=105, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=105, status_next=135, workflow=cls.julo_one_workflow
        )
        WorkflowStatusPath.objects.create(
            status_previous=105, status_next=106, workflow=cls.julo_one_workflow
        )
        cls.julo_product = ProductLineFactory(product_line_code=1)
        cls.application = ApplicationFactory(
            customer=cls.customer, product_line=cls.julo_product, application_xid=919
        )

        cls.application.workflow = cls.julo_one_workflow
        cls.application.application_status_id = 105
        cls.application.ktp = "4420040404840004"
        cls.application.save()
        cls.affordability_history = AffordabilityHistoryFactory(application=cls.application)
        cls.credit_matrix = CreditMatrixFactory()
        cls.credit_matrix_product_line = CreditMatrixProductLineFactory()
        cls.account_lookup = AccountLookupFactory(workflow=cls.julo_one_workflow)
        cls.bank = BankFactory(
            bank_code='012',
            bank_name=cls.application.bank_name,
            xendit_bank_code='BCA',
            swift_bank_code='01',
        )
        cls.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        cls.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        cls.name_bank_validation_success = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='success',
            mobile_phone='08674734',
            attempt=0,
        )
        cls.application.name_bank_validation = cls.name_bank_validation
        cls.application.save()

        existing_fraud_app_package_names = {
            'is_sus_camera_app': [
                'com.blogspot.newapphorizons.fakecamera',
                'com.github.fkloft.gallerycam',
            ],
            'is_sus_ektp_generator_app': ['com.fujisoft.ektp_simulator'],
        }
        to_create = []
        for risky_check, package_names in existing_fraud_app_package_names.items():
            to_create.append(
                SuspiciousFraudApps(
                    transaction_risky_check=risky_check, package_names=package_names
                )
            )
        SuspiciousFraudApps.objects.bulk_create(to_create)

    # test HSFB
    @patch('juloserver.application_flow.tasks.process_anti_fraud_binary_check', return_value='do_nothing')
    @patch('juloserver.application_flow.tasks.process_bad_history_customer', return_value=False)
    @patch('juloserver.application_flow.tasks.check_high_risk_asn', return_value=None)
    @patch('juloserver.application_flow.services.send_event_to_ga_task_async')
    @patch('juloserver.application_flow.services.special_event_fraud_checking', return_value=None)
    @patch('juloserver.application_flow.services.suspicious_app_check', return_value=None)
    @patch('juloserver.julo.workflows2.handlers.check_scrapped_bank')
    @patch('juloserver.application_flow.tasks.JuloOneService')
    @patch('juloserver.julo.workflows.trigger_name_in_bank_validation')
    @patch('juloserver.julo.services2.high_score.feature_high_score_full_bypass')
    @patch('juloserver.julo.workflows2.tasks.do_advance_ai_id_check_task')
    @patch('juloserver.julo.workflows.update_status_apps_flyer_task')
    @patch('juloserver.application_flow.tasks.feature_high_score_full_bypass')
    def test_hsfb_flow(
        self,
        mock_feature_high_score_full_bypass,
        mock_update_status_apps_flyer_task,
        mock_do_advance_ai_id_check_task,
        mock_feature_high_score_full_bypass_2,
        mock_trigger_validation,
        mock_julo_one_service,
        mock_check_scrapped_bank,
        mock_suspicious_app_check,
        mock_special_event_fraud_checking,
        mock_send_event_to_ga_task_async,
        mock_check_high_risk_asn,
        mock_process_bad_history_customer,
        mock_process_anti_fraud_binary_check,
    ):
        # is high score
        mock_julo_one_service.is_c_score.return_value = False
        hsfbp = MagicMock()
        hsfbp.bypass_dv_x121.return_value = False
        mock_feature_high_score_full_bypass_2.return_value = hsfbp
        mock_feature_high_score_full_bypass.return_value = True
        mock_update_status_apps_flyer_task.apply_async.side_effect = (
            update_status_apps_flyer_task_mock
        )
        mock_do_advance_ai_id_check_task.delay.side_effect = mock_do_advance_ai_id_check_task_mock
        validation_process = MagicMock()
        validation_process.get_id.return_value = self.name_bank_validation_success.id
        validation_process.validate.return_value = True
        validation_process.get_data.return_value = {
            'account_number': '12312312',
            'validated_name': 'success',
        }
        validation_process.is_success.return_value = True
        mock_trigger_validation.return_value = validation_process
        mock_check_scrapped_bank.return_value = False
        self.credit_model = PdCreditModelResultFactory(
            application_id=self.application.id, credit_score_type='A', pgood=0.65
        )
        # not app instance id
        handle_iti_ready(self.application.id)
        self.application.refresh_from_db()
        assert self.application.application_status_id == 124
        assert mock_update_status_apps_flyer_task.apply_async.called
        assert mock_do_advance_ai_id_check_task.delay.called
        assert ApplicationHistory.objects.filter(
            application=self.application,
            status_old=105,
            status_new=120,
            change_reason='high_score_full_bypass',
        ).exists()
        assert ApplicationHistory.objects.filter(
            application=self.application,
            status_old=120,
            status_new=124,
            change_reason='high_score_full_bypass',
        ).exists()
        assert not mock_send_event_to_ga_task_async.apply_async.called

        # has app instance id
        self.customer.app_instance_id = '111111111'
        self.customer.save()
        self.application.application_status_id = 105
        self.application.save()
        handle_iti_ready(self.application.id)
        assert mock_send_event_to_ga_task_async.apply_async.called_with(
            kwargs={'customer_id': self.application.customer.id, 'event': 'application_bypass'}
        )

    @patch('juloserver.application_flow.tasks.process_anti_fraud_binary_check', return_value='do_nothing')
    @patch('juloserver.application_flow.tasks.process_bad_history_customer', return_value=False)
    @patch('juloserver.application_flow.tasks.check_high_risk_asn', return_value=None)
    @patch('juloserver.application_flow.services.suspicious_app_check', return_value=None)
    @patch('juloserver.application_flow.tasks.send_event_to_ga_task_async')
    @patch('juloserver.application_flow.services.special_event_fraud_checking', return_value=None)
    @patch('juloserver.julo.workflows2.handlers.check_scrapped_bank')
    @patch('juloserver.julo.workflows2.tasks.do_advance_ai_id_check_task')
    @patch('juloserver.application_flow.tasks.check_scrapped_bank')
    @patch('juloserver.application_flow.tasks.check_submitted_bpjs')
    @patch('juloserver.application_flow.tasks.JuloOneService')
    @patch('juloserver.julo.services2.high_score.feature_high_score_full_bypass')
    @patch('juloserver.application_flow.tasks.feature_high_score_full_bypass')
    def test_medium_score_or_high_c_flow(
        self,
        mock_feature_high_score_full_bypass,
        mock_feature_high_score_full_bypass_2,
        mock_julo_one_service,
        mock_check_submitted_bpjs,
        mock_check_scrapped_bank,
        mock_do_advance_ai_id_check_task,
        mock_check_scrapped_bank_2,
        mock_special_event_fraud_checking,
        mock_send_event_to_ga_task_async,
        mock_suspicious_app_check,
        mock_check_high_risk_asn,
        mock_process_bad_history_customer,
        mock_process_anti_fraud_binary_check,
    ):
        # not HSFB score and not C score
        self.application.application_status_id = 105
        self.application.save()
        mock_feature_high_score_full_bypass.return_value = False
        mock_feature_high_score_full_bypass_2.return_value = False
        mock_julo_one_service.is_c_score.return_value = False

        # high c score
        mock_julo_one_service.is_high_c_score.return_value = True
        mock_check_submitted_bpjs.return_value = True
        mock_check_scrapped_bank.return_value = True
        mock_check_scrapped_bank_2.return_value = False
        sd_bank_account = SdBankAccountFactory(id=1, application_id=self.application.id)
        SdBankStatementDetailFactory(id=1, sd_bank_account=sd_bank_account)
        sd_profile = SdBpjsProfileFactory(application_id=self.application.id)
        SdBpjsCompanyFactory(sd_bpjs_profile=sd_profile)
        self.customer.app_instance_id = '111111111'
        self.customer.save()
        self.credit_model = PdCreditModelResultFactory(
            application_id=self.application.id, credit_score_type='A', pgood=0.65
        )
        handle_iti_ready(self.application.id)
        self.application.refresh_from_db()
        assert self.application.application_status_id == 120
        assert ApplicationHistory.objects.filter(
            application=self.application,
            status_old=105,
            status_new=120,
            change_reason='Julo one pass high C score',
        ).exists()
        assert mock_send_event_to_ga_task_async.apply_async.called_with(
            kwargs={'customer_id': self.application.customer.id, 'event': 'application_md'}
        )

        # medium score
        self.application.application_status_id = 105
        self.application.save()
        mock_feature_high_score_full_bypass.return_value = False
        mock_feature_high_score_full_bypass_2.return_value = False
        mock_julo_one_service.is_high_c_score.return_value = False
        mock_check_submitted_bpjs.return_value = True
        mock_check_scrapped_bank.return_value = True
        mock_julo_one_service.is_c_score.return_value = False
        handle_iti_ready(self.application.id)
        self.application.refresh_from_db()
        assert self.application.application_status_id == 120
        assert ApplicationHistory.objects.filter(
            application=self.application,
            status_old=105,
            status_new=120,
            change_reason='Julo one pass medium score',
        ).exists()
        assert mock_send_event_to_ga_task_async.apply_async.called_with(
            kwargs={'customer_id': self.application.customer.id, 'event': 'application_md'}
        )

    # test ITI
    @patch('juloserver.julo.workflows.post_anaserver')
    @patch('juloserver.application_flow.workflows.check_iti_repeat')
    @patch('juloserver.julo.workflows.trigger_name_in_bank_validation')
    @patch(
        'juloserver.julo.formulas.experiment.calculation_affordability_based_on_affordability_model'
    )
    def test_iti_flow(
        self,
        mock_calculation_affordability_based_on_affordability_model,
        mock_trigger_validation,
        mock_check_iti_repeat,
        mock_post_ana,
    ):
        mock_check_iti_repeat.return_value = True
        self.application.application_status_id = 121
        self.application.save()
        mock_calculation_affordability_based_on_affordability_model.return_value = True
        validation_process = MagicMock()
        validation_process.get_id.return_value = self.name_bank_validation_success.id
        validation_process.validate.return_value = True
        validation_process.get_data.return_value = {
            'account_number': '12312312',
            'validated_name': 'success',
        }
        validation_process.is_success.return_value = True
        mock_trigger_validation.return_value = validation_process
        process_application_status_change(self.application.id, 122, 'Document verified')
        self.application.refresh_from_db()
        assert self.application.application_status_id == 122

    @patch('juloserver.application_flow.tasks.pass_binary_check_scoring', return_value=False)
    @patch('juloserver.application_flow.services.suspicious_app_check', return_value=None)
    @patch('juloserver.application_flow.services.special_event_fraud_checking', return_value=None)
    @patch('juloserver.application_flow.tasks.JuloOneService')
    def test_under_c_flow(
        self,
        mock_julo_one_service,
        mock_special_event_fraud_checking,
        mock_suspicious_app_check,
        mock_pass_binary_check_scoring,
    ):
        CreditScoreFactory(application_id=self.application.id, score='B')
        self.application.application_status_id = 105
        self.application.save()
        mock_julo_one_service.is_c_score.return_value = True
        handle_iti_ready(self.application.id)
        self.application.refresh_from_db()
        assert self.application.application_status_id == 105

    def test_process_bad_history_customer(self):
        self.customer_removal = CustomerRemovalFactory(
            customer=self.customer,
            application=self.application,
            user=self.user,
            reason="its a test",
            nik=self.application.ktp,
        )
        self.account = AccountFactory(customer=self.customer)
        self.account.status_id = 430
        self.account.save()
        handle_iti_ready(self.application.id)
        self.application.refresh_from_db()
        assert self.application.application_status_id == 135

    @patch('juloserver.julo.workflows.trigger_name_in_bank_validation')
    def test_process_validate_bank(self, mock_trigger_validation):
        self.application.application_status_id = 122
        self.application.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.application.save()
        validation_process = MagicMock()
        validation_process.get_id.return_value = self.name_bank_validation_success.id
        validation_process.validate.return_value = True
        validation_process.get_data.return_value = {
            'account_number': '12312312',
            'validated_name': 'success',
        }
        validation_process.is_success.return_value = True
        mock_trigger_validation.return_value = validation_process
        process_application_status_change(self.application.id, 124, 'SonicAffodability')
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 124)

    @patch('juloserver.julo_privyid.tasks.create_new_privy_user')
    def test_register_privy_customer(self, mock_create_new_privy_user):
        self.application.application_status_id = 141
        self.application.save()
        # not privy mode
        process_application_status_change(self.application.id, 150, '')
        mock_create_new_privy_user.delay.assert_not_called()
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 190)

        # privy mode existed
        self.application.application_status_id = 141
        self.application.save()
        MobileFeatureSettingFactory(feature_name='privy_mode')
        process_application_status_change(self.application.id, 150, '')
        mock_create_new_privy_user.delay.assert_called_once()
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 150)

    def test_process_at_190_status(self):
        ReferralSystemFactory()
        CreditScoreFactory(application_id=self.application.id, score='B+')
        account = AccountFactory(customer=self.application.customer)
        account.status_id = 410
        account.save()

        self.application.account = account
        self.application.application_status_id = 150
        self.application.save()

        account_limit = AccountLimitFactory(account=account, set_limit=200000)
        process_application_status_change(self.application.id, 190, '')
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 190)

        account.refresh_from_db()
        account_limit.refresh_from_db()
        self.assertEqual(account.status_id, 420)
        available_limit = account_limit.set_limit - account_limit.used_limit
        self.assertEqual(account_limit.available_limit, available_limit)
        self.customer.refresh_from_db()
        self.assertNotEqual(self.customer.self_referral_code, '')

    @patch('juloserver.account.services.credit_limit.get_redis_client')
    @patch('juloserver.application_flow.workflows.get_redis_client')
    @patch('juloserver.application_flow.tasks.process_bad_history_customer', return_value=False)
    @patch('juloserver.julo.workflows.send_email_status_change_task')
    @patch.object(JuloOneWorkflowAction, 'has_shopee_blacklist_executed', return_value=None)
    def test_process_at_130_status(
        self,
        scoring,
        mock_send_email_status_change_task,
        mock_process_bad_history_customer,
        mock_get_client,
        mock_redis_client,
    ):
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.lbs_bypass_es = ExperimentSettingFactory(
            is_active=True,
            code=ExperimentConst.LBS_130_BYPASS,
            criteria={
                'limit_total_of_application_min_affordability': 700,
                'limit_total_of_application_swap_out_dukcapil': 700,
            },
        )
        self.fake_redis = MockRedisHelper()
        CreditScoreFactory(application_id=self.application.id, score=u'A-')
        self.credit_matrix_product_line.credit_matrix = self.credit_matrix
        self.credit_matrix_product_line.save()
        self.credit_matrix_product_line.refresh_from_db()
        self.application.application_status_id = 124
        self.application.monthly_income = 30000000
        self.application.income_1 = 20000000
        self.application.income_2 = 5000000
        self.application.income_3 = 5000000
        self.application.workflow = self.workflow
        self.application.save()
        self.application.refresh_from_db()
        mock_get_client.return_value = self.fake_redis
        mock_redis_client.return_value = self.fake_redis
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ONBOARDING_BANK_VALIDATION_PG,
            is_active=True,
        )
        process_application_status_change(self.application.id, 130, '')
        self.application.refresh_from_db()
        # happy path or unhappy path
        self.assertIsNotNone(Account.objects.all())
        self.assertIsNotNone(AccountLimit.objects.all())

    @patch('juloserver.application_flow.handlers.JuloOneWorkflowAction')
    def test_process_at_105_status(self, mock_handler_action):
        self.application.application_status_id = 134
        self.application.save()
        process_application_status_change(self.application.id, 105, 'Success manual check liveness')
        mock_handler_action().update_status_apps_flyer.assert_not_called()

    @patch('juloserver.application_flow.handlers.JuloOneWorkflowAction')
    def test_blocked_referral_moneyduck(self, mock_julo_one_service):
        self.application.referral_code = 'mdjulo'
        self.application.save()
        self.assertTrue(is_referral_blocked(self.application))

        self.application.referral_code = 'mduckjulo'
        self.application.save()
        self.assertTrue(is_referral_blocked(self.application))

        self.application.referral_code = 'MDUCKJULO'
        self.application.save()
        self.assertTrue(is_referral_blocked(self.application))

        self.application.referral_code = None
        self.application.save()
        self.assertFalse(is_referral_blocked(self.application))

    @patch('juloserver.application_flow.services.suspicious_app_check', return_value=None)
    @patch('juloserver.application_flow.services.special_event_fraud_checking', return_value=None)
    @patch(
        'juloserver.julo.workflows.WorkflowAction.trigger_anaserver_short_form_timeout',
        return_value=True,
    )
    @patch(
        'juloserver.julo.workflows.WorkflowAction.process_application_reapply_status_action',
        return_value=True,
    )
    def test_partnership_process_pre_check_application(
        self,
        process_reapply,
        trigger_ana,
        mock_special_event_fraud_checking,
        mock_suspicious_app_check,
    ):
        from juloserver.julo.tests.factories import PartnerFactory

        partner = PartnerFactory()
        self.application.update_safely(partner=partner)
        CreditScoreFactory(application_id=self.application.id, score='C')
        self.application.application_status_id = 105
        self.application.save()
        application_flag = PartnershipApplicationFlagFactory(
            application_id=self.application.id,
            name=PartnershipPreCheckFlag.ELIGIBLE_TO_BINARY_PRE_CHECK,
        )
        handle_iti_ready(self.application.id)
        self.application.refresh_from_db()
        application_flag.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 106)
        self.assertEqual(application_flag.name, PartnershipPreCheckFlag.NOT_PASSED_BINARY_PRE_CHECK)


class TestJuloOneService(TestCase):
    def setUp(self):
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer, application_xid=919)
        self.application.workflow = self.julo_one_workflow
        self.application.application_status_id = 105
        self.application.save()

    def test_is_high_c_score(self):
        # not credit score
        result = JuloOneService.is_high_c_score(self.application)
        self.assertEqual(result, False)

        credit_score = CreditScoreFactory(application_id=self.application.id, score='B-')
        # not high c score setting
        result = JuloOneService.is_high_c_score(self.application)
        self.assertEqual(result, False)

        CreditMatrixFactory(min_threshold=0.8, max_threshold=0.9, score='B--')
        MobileFeatureSettingFactory(
            feature_name='high_c_setting', parameters={'B--': {'is_active': True}}
        )
        result = JuloOneService.is_high_c_score(self.application)
        self.assertEqual(result, False)

        # high c score
        credit_score.score = 'B--'
        credit_score.save()
        result = JuloOneService.is_high_c_score(self.application)
        self.assertEqual(result, True)

    def test_is_c_score(self):
        application = ApplicationFactory(customer=self.customer, application_xid=919)
        # not credit score
        result = JuloOneService.is_c_score(application)
        self.assertEqual(result, False)

        # not C score
        credit_score = CreditScoreFactory(application_id=application.id, score='B')
        result = JuloOneService.is_c_score(application)
        self.assertEqual(result, False)

        # score C
        credit_score.score = 'C'
        credit_score.save()
        result = JuloOneService.is_c_score(application)
        self.assertEqual(result, True)


class TestBankAccountCorrectionView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )

    def test_resubmit_bank_info(self):
        data = {"bank_code": "BCA", "account_number": "19231231", "name_in_bank": "prod_only"}
        res = self.client.post('/api/application_flow/web/v1/resubmit_bank_account', data=data)
        assert res.status_code == 200

        res = self.client.post('/api/application_flow/web/v1/resubmit_bank_account', data={})
        assert res.status_code == 400

        res = self.client.get('/api/application_flow/web/v1/resubmit_bank_account', data={})
        assert res.status_code == 405


class TestFraudService(TestCase):
    def setUp(self):
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer, application_xid=919)
        self.application.workflow = self.julo_one_workflow
        self.application.application_status_id = 105
        self.application.save()
        self.decision_1 = ApplicationRiskyDecisionFactory(
            decision_name='NO DV BYPASS AND NO PVE BYPASS'
        )
        self.decision_2 = ApplicationRiskyDecisionFactory(decision_name='NO DV BYPASS')
        self.decision_3 = ApplicationRiskyDecisionFactory(decision_name='NO PVE BYPASS')
        self.user = AuthUserFactory()
        existing_fraud_app_package_names = {
            'is_sus_camera_app': [
                'com.blogspot.newapphorizons.fakecamera',
                'com.github.fkloft.gallerycam',
            ],
            'is_sus_ektp_generator_app': ['com.fujisoft.ektp_simulator'],
        }
        to_create = []
        for risky_check, package_names in existing_fraud_app_package_names.items():
            to_create.append(
                SuspiciousFraudApps(
                    transaction_risky_check=risky_check, package_names=package_names
                )
            )
        SuspiciousFraudApps.objects.bulk_create(to_create)

    # @patch('juloserver.application_flow.tasks.check_suspicious_ip')
    # def test_suspicious_ip_app_fraud_check(self, mock_check_suspicious_ip):
    #     # not used fake cam app
    #     mock_check_suspicious_ip.return_value = False
    #     result = suspicious_ip_app_fraud_check(self.application.id, '192.168.20.111')
    #     self.assertFalse(result.is_vpn_detected)
    #
    #     mock_check_suspicious_ip.return_value = True
    #
    #     # ApplicationRiskyCheck is not existed
    #     result = suspicious_ip_app_fraud_check(self.application.id, '192.168.20.111')
    #     self.assertIsNotNone(result)
    #     app_risk_check = ApplicationRiskyCheck.objects.filter(application=self.application).last()
    #     self.assertIsNotNone(app_risk_check)
    #
    #     # ApplicationRiskyCheck is already existed
    #     app_risk_check.decision = self.decision_3
    #     app_risk_check.save()
    #     result = suspicious_ip_app_fraud_check(self.application.id, '192.168.20.111')
    #     self.assertIsNotNone(result)
    #     app_risk_check.refresh_from_db()
    #     self.assertEqual(app_risk_check.is_vpn_detected, True)
    #     self.assertEqual(app_risk_check.decision.decision_name, 'NO DV BYPASS AND NO PVE BYPASS')
    #
    #     # ip adress not found
    #     result = suspicious_ip_app_fraud_check(self.application.id, None)
    #     self.assertIsNone(result)
    #
    #     # is_suspicious_ip param is true
    #     app_risk_check.decision = self.decision_3
    #     app_risk_check.save()
    #     result = suspicious_ip_app_fraud_check(self.application.id, '192.168.20.111', True)
    #     self.assertIsNotNone(result)
    #     app_risk_check.refresh_from_db()
    #     self.assertEqual(app_risk_check.is_vpn_detected, True)
    #     self.assertEqual(app_risk_check.decision.decision_name, 'NO DV BYPASS AND NO PVE BYPASS')

    def test_create_or_update_application_risky_check(self):
        # create successfully
        app_risky_check, created = create_or_update_application_risky_check(self.application)
        self.assertIsNotNone(app_risky_check)
        self.assertTrue(created)

        # object already existed
        app_risky_check, created = create_or_update_application_risky_check(self.application)
        self.assertIsNotNone(app_risky_check)
        self.assertFalse(created)


class TestJuloOneByPass(TestCase):
    def setUp(self):
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry',
        )
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer, application_xid=919)
        self.application.workflow = self.julo_one_workflow
        self.application.application_status_id = 120
        self.application.save()
        WorkflowStatusPath.objects.create(
            status_previous=120, status_next=124, workflow=self.julo_one_workflow
        )

    @patch('juloserver.julo.services2.high_score.feature_high_score_full_bypass')
    @patch('juloserver.application_flow.services.send_event_to_ga_task_async')
    def test_do_high_score_full_bypass_for_julo_one(
        self, mock_send_event_to_ga_task_async, mocked_feature_hsfbp
    ):
        # test ga event
        self.customer.app_instance_id = 'fake_instance_id'
        self.customer.save()
        mocked_feature_hsfbp.return_value = HighScoreFullBypassFactory(
            threshold=0.8, bypass_dv_x121=True
        )
        JuloOneByPass().do_high_score_full_bypass_for_julo_one(self.application)
        mock_send_event_to_ga_task_async.apply_async.assert_called()
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 124)


class TestStillinExperiment(TestCase):
    def setUp(self):
        self.experiment = ExperimentSettingFactory(
            code='RegistrationExperiment',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=True,
            is_permanent=True,
        )
        self.today = datetime.now()
        self.yesterday = self.today - timedelta(days=1)

    # still in experiment
    def test_case_1(self):
        self.experiment.is_active = False
        self.experiment.save()
        result = still_in_experiment('RegistrationExperiment')
        self.assertTrue(result)

    # still in experiment
    def test_case_2(self):
        self.experiment.is_permanent = False
        self.experiment.save()
        result = still_in_experiment('RegistrationExperiment')
        self.assertTrue(result)

    # not in experiment
    def test_case_3(self):
        self.experiment.is_active = False
        self.experiment.is_permanent = False
        self.experiment.save()
        result = still_in_experiment('RegistrationExperiment')
        self.assertFalse(result)

    # not in experiment because not in the schedule
    def test_case_4(self):
        self.experiment.start_date = datetime.now() + timedelta(days=10)
        self.experiment.end_date = datetime.now() + timedelta(days=50)
        self.experiment.is_permanent = False
        self.experiment.is_active = True
        self.experiment.save()
        result = still_in_experiment('RegistrationExperiment')
        self.assertFalse(result)


class TestListExperimentApplication(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = InventorUserFactory(username='test123', password=make_password('password@123'))
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='Experiment underwriting squad 1',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-144',
            status_old='0',
            status_new='0',
            date_start="2021-11-06 00:00:00+00",
            date_end="2099-02-06 00:00:00+00",
            is_active=True,
            created_by='Djasen Tjendry',
        )

        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )

    def test_happy_case_1(self):
        self.application.id = 2000506353
        self.application.save()
        self.experiment_test_group.value = '#nth:-1:1,2,3'
        self.experiment_test_group.save()
        result = list_experiment_application(self.experiment.code, self.application.id)

        tag_tracer = ApplicationTagTracking(self.application, 0, 100)
        tracking = tag_tracer.is_underwriting_overhaul()

        self.assertTrue(result)
        self.assertEqual(tracking, 1)

    def test_happy_case_2(self):
        self.application.id = 2000506355
        self.application.save()
        self.experiment_test_group.value = '#nth:-2:11,22,33,44,55,51,52'
        self.experiment_test_group.save()
        result = list_experiment_application(self.experiment.code, self.application.id)
        self.assertTrue(result)

    def test_happy_case_3(self):
        self.application.id = 2000506355
        self.application.save()
        self.experiment_test_group.value = '#nth:-1:1,2,3,4,5'
        self.experiment_test_group.save()
        result = list_experiment_application(self.experiment.code, self.application.id)
        self.assertTrue(result)

    def test_happy_case_4(self):
        self.application.id = 2000505123
        self.application.save()
        self.experiment_test_group.value = '#nth:-4:1111,1231,1234,5432,5123'
        self.experiment_test_group.save()
        result = list_experiment_application(self.experiment.code, self.application.id)
        self.assertTrue(result)

    def test_sad_case_1(self):
        self.application.id = 2000505125
        self.application.save()
        self.experiment_test_group.value = '#nth:-1:1,2,3,4'
        self.experiment_test_group.save()
        result = list_experiment_application(self.experiment.code, self.application.id)
        tag_tracer = ApplicationTagTracking(self.application, 0, 100)
        tracking = tag_tracer.is_underwriting_overhaul()

        self.assertEqual(tracking, 0)
        self.assertFalse(result)

    def test_sad_case_2(self):
        self.application.id = 2000505123
        self.application.save()
        self.experiment_test_group.value = '#nth:-2:11,22,33,12,44'
        self.experiment_test_group.save()
        result = list_experiment_application(self.experiment.code, self.application.id)
        self.assertFalse(result)

    def test_sad_case_3(self):
        self.application.id = 2000505125
        self.application.save()
        self.experiment_test_group.value = '#nth:-1:1,2,3,4,6,7'
        self.experiment_test_group.save()
        result = list_experiment_application(self.experiment.code, self.application.id)
        self.assertFalse(result)

    def test_sad_case_4(self):
        self.application.id = 2000505123
        self.application.save()
        self.experiment_test_group.value = '#nth:-4:1111,2222,3123,4213,6123,7213'
        self.experiment_test_group.save()
        result = list_experiment_application(self.experiment.code, self.application.id)
        self.assertFalse(result)

    def test_sad_case_5(self):
        self.application.id = 2000505123
        self.application.save()
        self.experiment.code = 'you cant find me'
        self.experiment.save()
        result = list_experiment_application(self.experiment.code, self.application.id)
        self.assertFalse(result)


class TestJuloOneWorkflowAction(TestCase):
    def setUp(self) -> None:
        FeatureSettingFactory(
            feature_name=FeatureNameConst.SHOPEE_SCORING,
            parameters={
                'pgood_threshold': 0.85,
                'blacklist_reason_code': [100, 101, 102, 103, 104, 105, 106],
            },
        )
        self.lbs_bypass_es = ExperimentSettingFactory(
            is_active=True,
            code=ExperimentConst.LBS_130_BYPASS,
            criteria={
                'limit_total_of_application_min_affordability': 700,
                'limit_total_of_application_swap_out_dukcapil': 700,
            },
        )
        self.fake_redis = MockRedisHelper()

    @override_settings(CELERY_ALWAYS_EAGER=True)
    @override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
    @responses.activate
    def test_personal_data_verification_190_async(self):
        """
        Detailed test case for `personal_data_verification_190_async` in
        `juloserver.personal_data_verification.tests.test_tasks.py`
        """
        application = ApplicationFactory()
        workflow_action = JuloOneWorkflowAction(
            application=application,
            new_status_code=190,
            old_status_code=130,
            change_reason='test',
            note='test',
        )

        workflow_action.personal_data_verification_190_async()
        responses.assert_call_count('http://172.16.160.31/databalikan/api/store', 0)

    @patch('juloserver.application_flow.workflows.get_redis_client')
    @patch('juloserver.application_flow.workflows.is_pass_dukcapil_verification_at_x130')
    @patch('juloserver.application_flow.workflows.process_application_status_change')
    @patch('juloserver.application_flow.workflows.generate_credit_limit')
    def test_process_credit_limit_generation_eligible_dukcapil(
        self,
        mock_generate_credit_limit,
        mock_process_application_status_change,
        mock_is_pass_dukcapil_verification_at_x130,
        mock_get_client,
    ):
        mock_get_client.return_value = self.fake_redis
        customer = CustomerFactory()
        application = ApplicationJ1Factory(application_status=StatusLookupFactory(status_code=130))
        application.customer = customer
        application.save()
        EligibleCheckFactory(
            application_id=application.id,
            check_name="eligible_limit_increase",
            parameter={"limit_gain": 5000000},
        )
        AccountLookupFactory(workflow=application.workflow)
        PdCreditModelResultFactory(application_id=application.id, credit_score_type='A', pgood=0.9)
        mock_generate_credit_limit.return_value = (1000000, 1000000)
        mock_is_pass_dukcapil_verification_at_x130.return_value = True
        workflow_action = JuloOneWorkflowAction(
            application=application,
            new_status_code=130,
            old_status_code=124,
            change_reason='test',
            note='test',
        )

        workflow_action.process_credit_limit_generation()

        mock_process_application_status_change.assert_called_once_with(
            application.id,
            141,
            change_reason='Credit limit generated',
        )

    @patch('juloserver.application_flow.workflows.get_redis_client')
    @patch('juloserver.application_flow.workflows.is_pass_dukcapil_verification_at_x130')
    @patch('juloserver.application_flow.workflows.process_application_status_change')
    @patch('juloserver.application_flow.workflows.generate_credit_limit')
    def test_process_credit_limit_generation_not_eligible_dukcapil(
        self,
        mock_generate_credit_limit,
        mock_process_application_status_change,
        mock_is_pass_dukcapil_verification_at_x130,
        mock_get_client,
    ):
        mock_get_client.return_value = self.fake_redis
        customer = CustomerFactory()
        application = ApplicationJ1Factory(application_status=StatusLookupFactory(status_code=130))
        application.customer = customer
        application.save()
        EligibleCheckFactory(
            application_id=application.id,
            check_name="eligible_limit_increase",
            parameter={"limit_gain": 5000000},
        )
        AccountLookupFactory(workflow=application.workflow)
        PdCreditModelResultFactory(application_id=application.id, credit_score_type='A', pgood=0.9)
        mock_generate_credit_limit.return_value = (1000000, 1000000)
        mock_is_pass_dukcapil_verification_at_x130.return_value = False
        DukcapilResponseFactory(
            application=application,
            status=200,
            errors=DukcapilDirectError.NOT_FOUND,
        )

        workflow_action = JuloOneWorkflowAction(
            application=application,
            new_status_code=130,
            old_status_code=124,
            change_reason='test',
            note='test',
        )
        workflow_action.process_credit_limit_generation()

        mock_process_application_status_change.assert_called_once_with(
            application.id,
            140,
            change_reason='Credit limit generated (Fail Dukcapil)',
        )

    @patch('juloserver.application_flow.workflows.get_redis_client')
    @patch('juloserver.application_flow.workflows.is_pass_dukcapil_verification_at_x130')
    @patch('juloserver.application_flow.workflows.process_application_status_change')
    @patch('juloserver.application_flow.workflows.generate_credit_limit')
    def test_process_credit_limit_generation_not_eligible_dukcapil_fraud(
        self,
        mock_generate_credit_limit,
        mock_process_application_status_change,
        mock_is_pass_dukcapil_verification_at_x130,
        mock_get_client,
    ):
        mock_get_client.return_value = self.fake_redis
        customer = CustomerFactory()
        application = ApplicationJ1Factory(application_status=StatusLookupFactory(status_code=130))
        application.customer = customer
        application.save()
        EligibleCheckFactory(
            application_id=application.id,
            check_name="eligible_limit_increase",
            parameter={"limit_gain": 5000000},
        )
        AccountLookupFactory(workflow=application.workflow)
        PdCreditModelResultFactory(application_id=application.id, credit_score_type='A', pgood=0.9)
        mock_generate_credit_limit.return_value = (1000000, 1000000)
        mock_is_pass_dukcapil_verification_at_x130.return_value = False
        DukcapilResponseFactory(
            application=application,
            status=200,
            errors=DukcapilDirectError.FOUND_DEAD,
        )

        workflow_action = JuloOneWorkflowAction(
            application=application,
            new_status_code=130,
            old_status_code=124,
            change_reason='test',
            note='test',
        )
        workflow_action.process_credit_limit_generation()

        mock_process_application_status_change.assert_called_once_with(
            application.id,
            133,
            change_reason='Credit limit generated (Fraud Dukcapil)',
        )

    @patch.object(JuloOneWorkflowAction, 'trigger_dukcapil_fr')
    def test_dukcapil_fr_j1(self, mock_trigger):
        customer = CustomerFactory()
        application = ApplicationJ1Factory(application_status=StatusLookupFactory(status_code=141))
        application.customer = customer
        application.save()

        DukcapilFaceRecognitionCheckFactory(response_score=6, application_id=application.id)
        FeatureSettingFactory(
            feature_name="dukcapil_fr_threshold",
            parameters={"j1": {"is_active": True, "very_high": 9.5, "high": 5}},
        )

        workflow_action = JuloOneWorkflowAction(
            application=application,
            new_status_code=141,
            old_status_code=140,
            change_reason='test',
            note='test',
        )
        result = workflow_action.dukcapil_fr_j1()
        self.assertTrue(result)

    @patch.object(JuloOneWorkflowAction, 'trigger_dukcapil_fr')
    def test_dukcapil_fr_partnership(self, _):

        from juloserver.julo.tests.factories import PartnerFactory
        from juloserver.partnership.leadgenb2b.constants import LeadgenFeatureSetting

        customer = CustomerFactory()
        partner = PartnerFactory(name='cermati')
        application = ApplicationJ1Factory(application_status=StatusLookupFactory(status_code=141))
        application.customer = customer
        application.partner = partner
        application.save()

        DukcapilFaceRecognitionCheckFactory(response_score=6, application_id=application.id)
        FeatureSettingFactory(
            feature_name="dukcapil_fr_threshold_partnership_leadgen",
            parameters={partner.name: {"is_active": True, "very_high": 9.5, "high": 5}},
        )

        FeatureSettingFactory(
            feature_name=LeadgenFeatureSetting.API_CONFIG,
            parameters={"allowed_partner": [partner.name]},
        )

        workflow_action = JuloOneWorkflowAction(
            application=application,
            new_status_code=141,
            old_status_code=140,
            change_reason='test',
            note='test',
        )
        result = workflow_action.dukcapil_fr_partnership_leadgen()
        self.assertTrue(result)


class TestSafetyNetViewEmulatorCheck(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = InventorUserFactory(username='test123', password=make_password('password@123'))
        self.customer = CustomerFactory(user=self.user)
        self.julo_product = ProductLineFactory(product_line_code=1)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 105
        self.application.product_line = self.julo_product
        self.application.save()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='Experiment underwriting squad 1',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-144',
            status_old='0',
            status_new='0',
            date_start="2021-11-06 00:00:00+00",
            date_end="2099-02-06 00:00:00+00",
            is_active=True,
            created_by='Djasen Tjendry',
        )

        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id', value="#nth:-1:1", experiment_id=self.experiment.id
        )
        self.js_workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)

    @patch('juloserver.julo_starter.services.submission_process.check_affordability')
    @patch('juloserver.apiv2.services.check_binary_result')
    def test_verify_emulator_check_eligibility(
        self, mock_check_binary_result, mock_check_affordability
    ):
        mock_check_binary_result.return_value = True
        data = {'application_id': self.application.id}
        CreditScoreFactory(score='A', application_id=self.application.id)
        FeatureSettingFactory(
            feature_name='emulator_detection',
            parameters={
                'active_emulator_detection': True,
                'timeout': 20,
                'reject_fail_emulator_detection': True,
            },
        )
        response = self.client.get('/api/application_flow/v1/emulator-check', data=data)
        self.assertEqual(response.json()['data']['request_timeout'], 20)

        # application is julo starter
        self.application.workflow = self.js_workflow
        self.application.application_status_id = 105
        self.application.product_line = None
        self.application.save()
        mock_check_affordability.return_value = True
        response = self.client.get('/api/application_flow/v1/emulator-check', data=data)
        self.assertEqual(response.json()['data']['eligible_for_emulator_check'], True)

        mock_check_affordability.return_value = False
        response = self.client.get('/api/application_flow/v1/emulator-check', data=data)
        self.assertEqual(response.json()['data']['eligible_for_emulator_check'], False)

    def test_create_emulator_detection_result_non_use_emulator(self):
        data = {
            'application_id': self.application.id,
            'service_provider': 'SafetyNet',
            'timestamp_ms': '1645912697',
            'is_request_timeout': False,
        }
        FeatureSettingFactory(
            feature_name='emulator_detection',
            parameters={'active_emulator_detection': True, 'timeout': 20},
        )
        response = self.client.post('/api/application_flow/v1/emulator-check', data=data)
        self.assertEqual(response.status_code, 201)
        emulator_check = EmulatorCheck.objects.filter(application=self.application).last()
        self.assertIsNotNone(emulator_check)

    def test_create_emulator_detection_result_use_emulator(self):
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.application.workflow = julo_one_workflow
        self.application.save()
        WorkflowStatusPath.objects.create(
            status_previous=105, status_next=135, workflow=julo_one_workflow
        )
        data = {
            'application_id': self.application.id,
            'service_provider': 'SafetyNet',
            'timestamp_ms': '1645912697',
            'is_request_timeout': False,
            'cts_profile_match': False,
            'basic_integrity': False,
            'error_msg': '',
        }
        FeatureSettingFactory(
            feature_name='emulator_detection',
            parameters={
                'active_emulator_detection': True,
                'timeout': 20,
                'reject_fail_emulator_detection': True,
            },
        )
        response = self.client.post('/api/application_flow/v1/emulator-check', data=data)
        self.assertEqual(response.status_code, 201)
        emulator_check = EmulatorCheck.objects.filter(application=self.application).last()
        self.assertIsNotNone(emulator_check)
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 135)

    def test_create_emulator_detection_result_use_emulator_but_timeout(self):
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.application.workflow = julo_one_workflow
        self.application.save()
        WorkflowStatusPath.objects.create(
            status_previous=105, status_next=135, workflow=julo_one_workflow
        )
        data = {
            'application_id': self.application.id,
            'service_provider': 'SafetyNet',
            'timestamp_ms': '1645912697',
            'is_request_timeout': True,
            'cts_profile_match': False,
            'basic_integrity': False,
            'error_msg': '',
        }
        FeatureSettingFactory(
            feature_name='emulator_detection',
            parameters={
                'active_emulator_detection': True,
                'timeout': 20,
                'reject_fail_emulator_detection': True,
            },
        )
        response = self.client.post('/api/application_flow/v1/emulator-check', data=data)
        self.assertEqual(response.status_code, 201)
        emulator_check = EmulatorCheck.objects.filter(application=self.application).last()
        self.assertIsNotNone(emulator_check)
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 105)

    def test_emulator_check_already_existed(self):
        data = {
            'application_id': self.application.id,
            'service_provider': 'SafetyNet',
            'timestamp_ms': '1645912697',
            'is_request_timeout': True,
            'cts_profile_match': False,
            'basic_integrity': False,
            'error_msg': '',
        }
        self.application.workflow = self.js_workflow
        self.application.application_status_id = 105
        self.application.product_line = None
        self.application.save()
        first_emulator = EmulatorCheck.objects.create(
            service_provider='test', application=self.application
        )
        response = self.client.get('/api/application_flow/v1/emulator-check', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['data']['eligible_for_emulator_check'])


class TestGooglePlayIntegrity(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = InventorUserFactory(username='test123', password=make_password('password@123'))
        self.customer = CustomerFactory(user=self.user)
        self.julo_product = ProductLineFactory(product_line_code=1)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 105
        self.application.product_line = self.julo_product
        self.application.save()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_create_emulator_detection_result_non_use_emulator(self):
        data = {
            "requestDetails": {
                "requestPackageName": "com.julofinance.juloapp",
                "timestampMillis": "1655238922431",
                "nonce": "afacf342432424242424vsvsfevsevsfvseaface",
            },
            "appIntegrity": {
                "appRecognitionVerdict": "UNRECOGNIZED_VERSION",
                "packageName": "com.julofinance.juloapp",
                "certificateSha256Digest": ["QuVoZeH4Uj_gPm8PHHODbkDoLaI9kQxH8EYTLAsywzU"],
                "versionCode": "1",
            },
            "deviceIntegrity": {"deviceRecognitionVerdict": ["MEETS_DEVICE_INTEGRITY"]},
            "accountDetails": {"appLicensingVerdict": "LICENSED"},
        }
        FeatureSettingFactory(
            feature_name='emulator_detection',
            parameters={'active_emulator_detection': True, 'timeout': 20},
        )
        response = self.client.post(
            f"/api/application_flow/v2/emulators/{self.application.id}", data=data, format="json"
        )
        self.assertEqual(response.status_code, 201)
        emulator_check = EmulatorCheck.objects.filter(application=self.application).last()
        self.assertIsNotNone(emulator_check)

    def test_create_emulator_detection_result_use_emulator(self):
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.application.workflow = julo_one_workflow
        self.application.save()
        WorkflowStatusPath.objects.create(
            status_previous=105, status_next=135, workflow=julo_one_workflow
        )
        data = {
            "requestDetails": {
                "requestPackageName": "com.julofinance.juloapp",
                "timestampMillis": "1655238922431",
                "nonce": "afacf342432424242424vsvsfevsevsfvseaface",
            },
            "appIntegrity": {"appRecognitionVerdict": "UNEVALUATED"},
            "deviceIntegrity": {},
            "accountDetails": {"appLicensingVerdict": "UNEVALUATED"},
        }
        FeatureSettingFactory(
            feature_name='emulator_detection',
            parameters={
                'active_emulator_detection': True,
                'timeout': 20,
                'reject_fail_emulator_detection': True,
            },
        )
        response = self.client.post(
            f"/api/application_flow/v2/emulators/{self.application.id}", data=data, format="json"
        )
        self.assertEqual(response.status_code, 201)
        emulator_check = EmulatorCheck.objects.filter(application=self.application).last()
        self.assertIsNotNone(emulator_check)

        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 135)

    def test_create_emulator_detection_result_has_error(self):
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.application.workflow = julo_one_workflow
        self.application.save()
        WorkflowStatusPath.objects.create(
            status_previous=105, status_next=135, workflow=julo_one_workflow
        )
        data = {'error_message': 'Something bad happened'}
        FeatureSettingFactory(
            feature_name='emulator_detection',
            parameters={
                'active_emulator_detection': True,
                'timeout': 20,
                'reject_fail_emulator_detection': True,
            },
        )
        response = self.client.post(
            f"/api/application_flow/v2/emulators/{self.application.id}", data=data, format="json"
        )
        self.assertEqual(response.status_code, 201)
        emulator_check = EmulatorCheck.objects.filter(application=self.application).last()
        self.assertIsNotNone(emulator_check)
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 105)


class TestJuloOneBypass141to144(TestCase):
    def setUp(self):
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.application = ApplicationFactory()
        self.application.application_status = StatusLookupFactory(
            status_code=140,
        )
        self.application.workflow = self.julo_one_workflow
        self.application.save()

    def test_140_to_150(self):
        WorkflowStatusPathFactory(
            status_previous=140,
            status_next=150,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )

        process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
            change_reason="Entry Level Bypass 141",
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 150)

    def test_140_to_144(self):
        StatusLookupFactory(status_code=144)
        WorkflowStatusPathFactory(
            status_previous=140,
            status_next=144,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )

        process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.NAME_BANK_VALIDATION_FAILED,
            change_reason="system_triggered",
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 144)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestShopeeScoring(TestCase):
    scoring_data = {
        "code": "2000",
        "msg": "Success",
        "sign_type": "RSA-SHA256",
        "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
        "encrypt": False,
        "encrypt_type": "",
        "flow_no": "45b0b68746d74b1ca0fd355468230753",
        "timestamp": 1664347920722,
        "biz_code": "200000",
        "biz_msg": "Success",
        "biz_data": "{\"hit_flag\":1,\"hit_reason_code\":\"200\",\"list_type\":2}",
    }

    scoring_data_2 = {
        "code": "2000",
        "msg": "Success",
        "sign_type": "RSA-SHA256",
        "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
        "encrypt": False,
        "encrypt_type": "",
        "flow_no": "45b0b68746d74b1ca0fd355468230753",
        "timestamp": 1664347920722,
        "biz_code": "200000",
        "biz_msg": "Success",
        "biz_data": "",
    }

    scoring_data_3 = {
        "code": "2000",
        "msg": "Success",
        "sign_type": "RSA-SHA256",
        "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
        "encrypt": False,
        "encrypt_type": "",
        "flow_no": "45b0b68746d74b1ca0fd355468230753",
        "timestamp": 1664347920722,
        "biz_code": "200000",
        "biz_msg": "Success",
        "biz_data": "{\"hit_flag\":1,\"hit_reason_code\":\"103\",\"list_type\":1}",
    }

    scoring_data_4 = {
        "code": "2000",
        "msg": "Success",
        "sign_type": "RSA-SHA256",
        "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
        "encrypt": False,
        "encrypt_type": "",
        "flow_no": "45b0b68746d74b1ca0fd355468230753",
        "timestamp": 1664347920722,
        "biz_code": "200000",
        "biz_msg": "Success",
        "biz_data": "{\"hit_flag\":1,\"hit_reason_code\":\"106\",\"list_type\":1}",
    }

    def setUp(self) -> None:
        self.shopee_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SHOPEE_SCORING,
            parameters={
                'pgood_threshold': 0.85,
                'blacklist_reason_code': [100, 101, 102, 103],
                'holdout': {"percentage": 10, "per_requests": 10},
            },
        )
        self.j1_workflow = WorkflowFactory(name="JuloOneWorkflow")
        WorkflowStatusPathFactory(
            status_previous=130,
            status_next=190,
            type='happy',
            is_active=True,
            workflow=self.j1_workflow,
        )
        WorkflowStatusPathFactory(
            status_previous=130,
            status_next=135,
            type='graveyard',
            is_active=True,
            workflow=self.j1_workflow,
        )
        self.customer = CustomerFactory()
        status_130 = StatusLookupFactory(status_code=130)
        self.application = ApplicationFactory(
            id=3, customer=self.customer, application_status=status_130
        )
        self.application.workflow = self.j1_workflow
        self.application.application_status = status_130
        self.application.save()

        self.credit_model = PdCreditModelResultFactory(
            application_id=self.application.id, credit_score_type='A', pgood=0.80
        )

        self.action = JuloOneWorkflowAction(
            application=self.application,
            old_status_code=124,
            new_status_code=130,
            change_reason='Testing',
            note='',
        )

        self.lbs_bypass_es = ExperimentSettingFactory(
            is_active=True,
            code=ExperimentConst.LBS_130_BYPASS,
            criteria={
                'limit_total_of_application_min_affordability': 700,
                'limit_total_of_application_swap_out_dukcapil': 700,
            },
        )
        self.fake_redis = MockRedisHelper()

    def test_should_not_hit_when_application_status_not_130(self):
        """Failed with config threshold and application id matched"""
        from juloserver.application_flow.services2.shopee_scoring import ShopeeException

        status_105 = StatusLookupFactory(status_code=105)

        self.application.application_status = status_105
        self.application.save()

        model = ScoringModel.objects.filter(application=self.application)
        self.assertFalse(model.exists())

    def test_should_not_hit_when_above_threshold(self):
        self.credit_model.pgood = 0.9
        self.credit_model.save()

        self.action.has_shopee_blacklist_executed(190, "Test to 190")

        model = ScoringModel.objects.filter(application=self.application)
        self.assertFalse(model.exists())

    def test_should_not_hit_when_not_setting_off(self):
        self.shopee_setting.update_safely(is_active=False)

        self.action.has_shopee_blacklist_executed(190, "Test to 190")

        model = ScoringModel.objects.filter(application=self.application)
        self.assertFalse(model.exists())

    @patch('juloserver.application_flow.services2.shopee_scoring.get_redis_client')
    @patch.object(ShopeeScoring, 'call', return_value=scoring_data)
    def test_should_success_when_status_threshold_and_id_matched(self, mock_data, mock_get_client):
        mock_get_client.return_value = self.fake_redis
        self.action.has_shopee_blacklist_executed(190, "Test to 190")

        model = ScoringModel.objects.filter(application=self.application)
        self.assertTrue(model.exists())
        self.assertTrue(model.last().is_passed)

    @patch('juloserver.application_flow.services2.shopee_scoring.get_redis_client')
    @patch.object(ShopeeScoring, 'call', return_value=scoring_data)
    def test_should_success_when_is_permanent(self, mock_data, mock_get_client):
        mock_get_client.return_value = self.fake_redis
        self.action.has_shopee_blacklist_executed(190, "Test to 190")

        is_exists = ScoringModel.objects.filter(application=self.application).exists()
        self.assertTrue(is_exists)

    @patch('juloserver.application_flow.services2.shopee_scoring.get_redis_client')
    @patch.object(ShopeeScoring, 'call', return_value=scoring_data_2)
    def test_should_success_when_biz_data_is_empty_string(self, mock_data, mock_get_client):
        mock_get_client.return_value = self.fake_redis
        self.action.has_shopee_blacklist_executed(190, "Test to 190")

        model = ScoringModel.objects.filter(application=self.application)
        self.assertTrue(model.exists())
        self.assertTrue(model.last().is_passed)

    @patch('juloserver.application_flow.services2.shopee_scoring.get_redis_client')
    @patch.object(ShopeeScoring, 'call', return_value=scoring_data_3)
    @patch(
        'juloserver.julocore.cache_client.get_redis_cache',
        return_value=get_loc_mem_cache(),
    )
    def test_should_success_when_biz_data_blacklist(self, mock_cache, mock_data, mock_get_client):
        mock_get_client.return_value = self.fake_redis
        self.action.has_shopee_blacklist_executed(190, "Test to 190")

        model = ScoringModel.objects.filter(application=self.application)
        self.assertTrue(model.exists())
        self.assertFalse(model.last().is_passed)

        # Check the application status
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 135)

        # Check the reapply status
        customer = self.application.customer
        customer.refresh_from_db()
        self.assertFalse(self.application.customer.can_reapply)
        self.assertIsNotNone(self.application.customer.can_reapply_date)

    @patch('juloserver.application_flow.services2.shopee_scoring.get_redis_client')
    @patch.object(ShopeeScoring, 'call', return_value=scoring_data_4)
    def test_should_success_when_biz_data_not_in_registered_fail_list_codes(
        self, mock_data, mock_get_client
    ):
        mock_get_client.return_value = self.fake_redis
        self.action.has_shopee_blacklist_executed(190, "Test to 190")

        model = ScoringModel.objects.filter(application=self.application)
        self.assertTrue(model.exists())
        self.assertTrue(model.last().is_passed)

        # Check the application status
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 190)

        # Check the reapply status
        customer = self.application.customer
        customer.refresh_from_db()
        self.assertFalse(self.application.customer.can_reapply)
        self.assertIsNone(self.application.customer.can_reapply_date)


class TestShopeeScoringService(TestCase):
    def test_encrypt_data(self):
        from django.conf import settings

        scoring = ShopeeScoring(nik='4420040404840004', phone='0852837362927')
        scoring.encrypt_data()

        self.assertEqual(scoring.data, {"ktp_no": '4420040404840004', "msisdn": "62852837362927"})
        self.assertIsNotNone(scoring._iv)
        self.assertEqual(scoring._iv, settings.SCORING_KEY[:16].encode('utf-8'))
        self.assertIsNotNone(scoring.encrypted_data)

    def test_decrypt_data(self):
        scoring = ShopeeScoring(nik='4420040404840004', phone='0852837362927')
        result = scoring.decrypt_data(scoring.encrypted_data)

        self.assertEqual(result, {"ktp_no": '4420040404840004', "msisdn": "62852837362927"})


class TestExperimentJuloStarter(TestCase):
    def setUp(self):
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.JULO_STARTER_EXPERIMENT,
            start_date=timezone.localtime(timezone.now()) - timedelta(days=1),
            end_date=timezone.localtime(timezone.now()) + timedelta(days=5),
            criteria={
                "regular_customer_id": [2, 3, 4, 5, 6, 7, 8, 9],
                "julo_starter_customer_id": [0, 1],
                "target_version": "==7.9.0",
            },
            is_active=False,
            is_permanent=False,
        )

    def test_scenario_for_julo_starter_onboarding(self):
        """
        Experiment with case JuloStarter onboarding
        """

        # enabled for experiment
        self.experiment_setting.is_active = True
        self.experiment_setting.save()

        expected_onboarding = OnboardingIdConst.JULO_STARTER_FORM_ID
        onboarding = OnboardingFactory(id=OnboardingIdConst.JULO_STARTER_FORM_ID)
        customer = CustomerFactory(id=1000016460)
        application = ApplicationFactory(id=1, customer=customer, onboarding=onboarding)

        apply_process = determine_by_experiment_julo_starter(customer, application, '7.9.0')
        self.assertEqual(apply_process.onboarding_id, expected_onboarding)

    def test_scenario_for_regular_onboarding(self):
        """
        Experiment with case regular onboarding
        """

        # enabled for experiment
        self.experiment_setting.is_active = True
        self.experiment_setting.save()

        expected_onboarding = OnboardingIdConst.LONGFORM_SHORTENED_ID
        onboarding = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        customer = CustomerFactory(id=1000016462)
        application = ApplicationFactory(id=1, customer=customer, onboarding=onboarding)

        apply_process = determine_by_experiment_julo_starter(customer, application, '7.9.0')
        self.assertEqual(apply_process.onboarding_id, expected_onboarding)

    def test_scenario_for_experiment_is_expire(self):
        """
        Experiment with case expire
        """

        # enabled for experiment
        self.experiment_setting.start_date = datetime.now() - timedelta(days=2)
        self.experiment_setting.end_date = datetime.now() - timedelta(days=1)
        self.experiment_setting.is_active = True
        self.experiment_setting.save()

        expected_onboarding = OnboardingIdConst.JULO_STARTER_FORM_ID
        onboarding = OnboardingFactory(id=OnboardingIdConst.JULO_STARTER_FORM_ID)
        customer = CustomerFactory(id=1000016462)
        application = ApplicationFactory(id=1, customer=customer, onboarding=onboarding)

        apply_process = determine_by_experiment_julo_starter(customer, application, '7.9.0')
        self.assertEqual(apply_process.onboarding_id, expected_onboarding)

    def test_scenario_for_experiment_for_condition_invalid(self):
        """
        ExperimentSetting on criteria we set invalid json
        """

        # enabled for experiment
        self.experiment_setting.criteria = "{}"
        self.experiment_setting.is_active = True
        self.experiment_setting.save()

        onboarding = OnboardingFactory(id=OnboardingIdConst.JULO_STARTER_FORM_ID)
        customer = CustomerFactory(id=1000016462)
        application = ApplicationFactory(id=1, customer=customer, onboarding=onboarding)

        with self.assertRaises(Exception) as error:
            determine_by_experiment_julo_starter(customer, application, '7.9.0')
        self.assertTrue(str(error), 'Criteria experiment is invalid')

    def test_scenario_for_app_version_is_null(self):
        """
        Condition for App Version is None
        """

        # enabled for experiment
        self.experiment_setting.is_active = True
        self.experiment_setting.save()

        onboarding = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        customer = CustomerFactory(id=1000016462)
        application = ApplicationFactory(id=1, customer=customer, onboarding=onboarding)

        apply_process = determine_by_experiment_julo_starter(customer, application)
        self.assertEqual(apply_process.onboarding_id, OnboardingIdConst.LONGFORM_SHORTENED_ID)

    def test_scenario_for_app_version_is_lower_version(self):
        """
        Condition for App Version is lower version
        Should be if not lower version onboarding_id will be updated
        to onboarding_id = 6, because last_digit customer_id is 0
        And experiment is active.
        """

        # enabled for experiment
        self.experiment_setting.is_active = True
        self.experiment_setting.save()

        onboarding = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        customer = CustomerFactory(id=1000016460)
        application = ApplicationFactory(id=1, customer=customer, onboarding=onboarding)

        apply_process = determine_by_experiment_julo_starter(customer, application, '7.8.0')
        self.assertEqual(apply_process.onboarding_id, OnboardingIdConst.LONGFORM_SHORTENED_ID)

    def test_scenario_for_start_end_experiment_is_expire(self):
        """
        Check condition for set start dan end experiment with date and time.
        Expected experiment not execute because end time experiment is expire.
        """

        # enabled for experiment
        self.experiment_setting.start_date = timezone.localtime(timezone.now()) - timedelta(hours=2)
        self.experiment_setting.end_date = timezone.localtime(timezone.now()) - timedelta(hours=1)
        self.experiment_setting.is_active = True
        self.experiment_setting.save()

        onboarding = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        customer = CustomerFactory(id=1000016460)
        application = ApplicationFactory(id=1, customer=customer, onboarding=onboarding)
        apply_process = determine_by_experiment_julo_starter(customer, application, '7.9.0')
        self.assertEqual(apply_process.onboarding_id, OnboardingIdConst.LONGFORM_SHORTENED_ID)

    def test_scenario_for_start_end_experiment_is_not_expire(self):
        """
        Check condition for set start dan end experiment with date and time.
        Expected experiment should be execute because end time experiment is not expire.
        """

        # enabled for experiment
        self.experiment_setting.start_date = timezone.localtime(timezone.now()) - timedelta(days=1)
        self.experiment_setting.end_date = timezone.localtime(timezone.now()) + timedelta(hours=3)
        self.experiment_setting.is_active = True
        self.experiment_setting.save()

        onboarding = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        customer = CustomerFactory(id=1000016460)
        application = ApplicationFactory(id=1, customer=customer, onboarding=onboarding)
        apply_process = determine_by_experiment_julo_starter(customer, application, '7.9.0')
        self.assertEqual(apply_process.onboarding_id, OnboardingIdConst.JULO_STARTER_FORM_ID)

    def test_scenario_for_is_permanent_is_checked(self):
        """
        Scenario for is_permanent is checked and experiment will running forever
        without checking start_date, end_date, and is_active
        """

        self.experiment_setting.start_date = timezone.localtime(timezone.now()) - timedelta(days=2)
        self.experiment_setting.end_date = timezone.localtime(timezone.now()) - timedelta(days=1)
        self.experiment_setting.is_active = False

        # Set True for is_permanent
        self.experiment_setting.is_permanent = True
        self.experiment_setting.save()

        onboarding = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        customer = CustomerFactory(id=1000016460)
        application = ApplicationFactory(id=1, customer=customer, onboarding=onboarding)
        apply_process = determine_by_experiment_julo_starter(customer, application, '7.9.0')
        self.assertEqual(apply_process.onboarding_id, OnboardingIdConst.JULO_STARTER_FORM_ID)


class TestGooglePlayIntegrityDecode(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = InventorUserFactory(username='test123', password=make_password('password@123'))
        self.customer = CustomerFactory(user=self.user)
        self.julo_product = ProductLineFactory(product_line_code=1)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 105
        self.application.product_line = self.julo_product
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.application.workflow = self.julo_one_workflow
        self.application.save()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.dummy_json = {
            'tokenPayloadExternal': {
                'requestDetails': {
                    'requestPackageName': 'com.julofinance.juloapp',
                    'timestampMillis': '1676628975308',
                    'nonce': 'hMgfs01w7truj4PLkW9vkMMxNxNiTGVF',
                },
                'appIntegrity': {
                    'appRecognitionVerdict': 'UNRECOGNIZED_VERSION',
                    'packageName': 'com.julofinance.juloapp',
                    'certificateSha256Digest': ['gTqndE03AQBWHs3ltg64VaulxC4AsaIgSzL1YyZ9Qto'],
                    'versionCode': '2331',
                },
                'deviceIntegrity': {
                    'deviceRecognitionVerdict': [
                        'MEETS_BASIC_INTEGRITY',
                        'MEETS_DEVICE_INTEGRITY',
                        'MEETS_STRONG_INTEGRITY',
                    ]
                },
                'accountDetails': {'appLicensingVerdict': 'LICENSED'},
            }
        }
        self.js_workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)

    @patch('juloserver.julo_starter.services.submission_process.check_affordability')
    @patch('juloserver.application_flow.clients.get_google_play_integrity_token_file_path')
    @patch(
        "juloserver.application_flow.clients.google_play_integrity.GooglePlayIntegrityClient.decode_integrity_token"
    )
    @patch('juloserver.julo_starter.services.onboarding_check.check_dukcapil_for_turbo')
    @patch('juloserver.julo_starter.services.onboarding_check.check_bpjs_for_turbo')
    def test_handle_google_play_integrity_decode_request_with_token(
        self,
        mock_bpjs_check,
        mock_dukcapil_check,
        mock_decode_integrity_token,
        mock_file_path,
        mock_check_affordability,
    ):
        # Test to decode and store json from integrity token

        data = {"integrity_token": "XXXYYYZZZ", "error_message": None}
        mock_json_data_dict = deepcopy(self.dummy_json)
        mock_file_path.return_value = 'dummypath'
        mock_decode_integrity_token.return_value = mock_json_data_dict, None
        mock_dukcapil_check.return_value = True
        mock_dukcapil_check.return_value = 1
        emulator_check = handle_google_play_integrity_decode_request_task(self.application.id, data)
        self.assertNotEqual(emulator_check, None)
        self.assertEqual(emulator_check.application_id, self.application.id)
        self.assertEqual(
            emulator_check.device_recognition_verdict,
            mock_json_data_dict["tokenPayloadExternal"]["deviceIntegrity"][
                "deviceRecognitionVerdict"
            ],
        )
        self.assertEqual(emulator_check.error_msg, None)

        # application is julo_starter
        js_application = ApplicationFactory(workflow=self.js_workflow)
        js_application.application_status_id = 105
        js_application.save()
        WorkflowStatusPathFactory(workflow=self.js_workflow, status_previous=105, status_next=108)
        data = {"integrity_token": "XXXYYYZZZ", "error_message": None}
        mock_json_data_dict = self.dummy_json
        mock_decode_integrity_token.return_value = mock_json_data_dict, None
        mock_check_affordability.return_value = True
        emulator_check = handle_google_play_integrity_decode_request_task(js_application.id, data)
        self.assertNotEqual(emulator_check, None)
        self.assertEqual(emulator_check.application_id, js_application.id)
        self.assertEqual(
            emulator_check.device_recognition_verdict,
            mock_json_data_dict["tokenPayloadExternal"]["deviceIntegrity"][
                "deviceRecognitionVerdict"
            ],
        )
        self.assertEqual(emulator_check.error_msg, None)
        js_application.refresh_from_db()
        # self.assertEqual(js_application.status, 108)

    @patch('juloserver.julo_starter.services.submission_process.check_affordability')
    def test_handle_google_play_integrity_decode_request_with_error(self, mock_check_affordability):
        # Test to test and store when error message is sent from FE

        data = {"integrity_token": None, "error_message": "Error Occured"}
        emulator_check = handle_google_play_integrity_decode_request_task(self.application.id, data)
        self.assertNotEqual(emulator_check, None)
        self.assertEqual(emulator_check.application_id, self.application.id)
        self.assertEqual(emulator_check.error_msg, "Error Occured")

        # application is julo_starter
        js_application = ApplicationFactory(workflow=self.js_workflow)
        js_application.application_status_id = 105
        js_application.save()
        WorkflowStatusPathFactory(workflow=self.js_workflow, status_previous=105, status_next=107)
        data = {"integrity_token": None, "error_message": "Error Occured"}
        mock_check_affordability.return_value = True
        emulator_check = handle_google_play_integrity_decode_request_task(js_application.id, data)
        self.assertNotEqual(emulator_check, None)
        self.assertEqual(emulator_check.application_id, js_application.id)
        self.assertEqual(emulator_check.error_msg, "Error Occured")
        js_application.refresh_from_db()
        self.assertEqual(js_application.application_status_id, 107)
        last_app_history = ApplicationHistory.objects.filter(application=js_application).last()
        self.assertEqual(last_app_history.change_reason, 'emulator_detection_client_detect_error')

    @patch('juloserver.julo_starter.services.submission_process.check_affordability')
    @patch('juloserver.application_flow.clients.get_google_play_integrity_token_file_path')
    @patch(
        "juloserver.application_flow.clients.google_play_integrity.GooglePlayIntegrityClient.decode_integrity_token"
    )
    def test_handle_google_play_integrity_decode_request_retry_log(
        self, mock_decode_integrity_token, mock_file_path, mock_check_affordability
    ):
        # Test to check if the retry are recoded in the table

        data = {"integrity_token": "XXXYYYZZZ", "error_message": None}
        mock_file_path.return_value = 'dummypath'
        mock_decode_integrity_token.return_value = None, 'Failed Decoding'
        handle_google_play_integrity_decode_request_task.delay(self.application.id, data)
        emulator_check = EmulatorCheck.objects.last()
        self.assertNotEqual(emulator_check, None)
        self.assertNotEqual(emulator_check.error_msg, None)
        self.assertEqual(len(emulator_check.error_occurrences), 6)
        self.assertEqual('Failed Decoding' in emulator_check.error_msg, True)

        # application is julo_starter
        js_application = ApplicationFactory(workflow=self.js_workflow)
        js_application.application_status_id = 105
        js_application.save()
        WorkflowStatusPathFactory(workflow=self.js_workflow, status_previous=105, status_next=108)
        data = {"integrity_token": "XXXYYYZZZ", "error_message": None}
        mock_check_affordability.return_value = True
        with patch('juloserver.application_flow.tasks.GooglePlayIntegrityConstants') as mock_cs:
            with self.assertRaises(PlayIntegrityDecodeError):
                mock_cs.JS_MAX_NO_OF_RETRIES = 3
                mock_cs.JS_RETRY_BACKOFF = 0
                handle_google_play_integrity_decode_request_task(js_application.id, data)

        emulator_check = EmulatorCheck.objects.filter(application=js_application).last()
        self.assertNotEqual(emulator_check, None)
        self.assertNotEqual(emulator_check.error_msg, None)
        self.assertEqual(len(emulator_check.error_occurrences), 3)
        self.assertEqual('Failed Decoding' in emulator_check.error_msg, True)
        js_application.refresh_from_db()
        self.assertEqual(js_application.status, 108)

    def test_emulator_check_already_exist(self):
        data = {"integrity_token": "XXXYYYZZZ", "error_message": None}
        js_application = ApplicationFactory(workflow=self.js_workflow)
        js_application.application_status_id = 105
        js_application.save()
        first_emulator = EmulatorCheck.objects.create(
            service_provider='test', application=js_application
        )
        emulator_check = handle_google_play_integrity_decode_request_task(js_application.id, data)
        self.assertEqual(emulator_check.id, first_emulator.id)

    @patch('juloserver.application_flow.clients.get_google_play_integrity_token_file_path')
    @patch(
        "juloserver.application_flow.clients.google_play_integrity.GooglePlayIntegrityClient.decode_integrity_token"
    )
    def test_handle_google_play_integrity_decode_request_existing_entry_return(
        self, mock_decode_integrity_token, mock_file_path
    ):
        # Test to check if the retry are recoded in the table
        existing_emulator_check = EmulatorCheck.objects.create(
            application=self.application, service_provider='google'
        )
        data = {"integrity_token": "XXXYYYZZZ", "error_message": None}
        mock_file_path.return_value = 'dummypath'
        emulator_check = handle_google_play_integrity_decode_request_task(self.application.id, data)
        self.assertEqual(emulator_check.id, existing_emulator_check.id)
        self.assertNotEqual(emulator_check, None)

    def test_reject_application_by_google_play_integrity_task(self):
        emulator_check = EmulatorCheck.objects.create(
            application=self.application, service_provider='google', device_recognition_verdict=None
        )
        FeatureSettingFactory(
            feature_name='emulator_detection',
            is_active=True,
            parameters={'reject_fail_emulator_detection': True},
        )
        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=135,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )
        reject_application_by_google_play_integrity_task(emulator_check.id)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 135)

        # application is julo_starter
        js_application = ApplicationFactory(workflow=self.js_workflow)
        js_application.application_status_id = 105
        js_application.save()
        emulator_check = EmulatorCheck.objects.create(
            application=js_application, service_provider='google', device_recognition_verdict=None
        )
        WorkflowStatusPathFactory(workflow=self.js_workflow, status_previous=105, status_next=133)
        WorkflowStatusNodeFactory(
            status_node=133, workflow=self.js_workflow, handler='JuloStarter133Handler'
        )
        reject_application_by_google_play_integrity_task(emulator_check.id)
        js_application.refresh_from_db()
        self.assertEqual(js_application.status, 133)

    @patch('juloserver.julo_starter.services.submission_process.check_affordability')
    @patch('juloserver.application_flow.clients.get_google_play_integrity_token_file_path')
    @patch('juloserver.julo_starter.services.onboarding_check.check_bpjs_for_turbo', return_value=1)
    @patch(
        'juloserver.julo_starter.services.onboarding_check.check_dukcapil_for_turbo',
        return_value=True,
    )
    def test_mock_response(
        self, mock_dukcapil, mock_bpjs, mock_file_path, mock_check_affordability
    ):
        setting = FeatureSettingFactory(
            feature_name='emulator_detection_mock',
            is_active=True,
            parameters={
                "product": ["j-starter"],
                "latency": 10,
                "response_value": {
                    "decoded_response": {
                        'tokenPayloadExternal': {
                            'requestDetails': {
                                'requestPackageName': 'com.julofinance.juloapp',
                                'timestampMillis': 1682588242,
                                'nonce': 'UNyBufVRiN9gticiU38WccEQRiIIxSes',
                            },
                            'appIntegrity': {
                                'appRecognitionVerdict': 'PLAY_RECOGNIZED',
                                'packageName': 'com.julofinance.juloapp',
                                'certificateSha256Digest': [
                                    'YlOH2m2ELWDim2gi6y_BaFkhX0YI1vtQdfNDgK5uABE'
                                ],
                                'versionCode': '2342',
                            },
                            'deviceIntegrity': {
                                'deviceRecognitionVerdict': [
                                    'MEETS_BASIC_INTEGRITY',
                                    'MEETS_DEVICE_INTEGRITY',
                                    'MEETS_STRONG_INTEGRITY',
                                ]
                            },
                            'accountDetails': {'appLicensingVerdict': 'LICENSED'},
                        }
                    },
                    "decode_error": "",
                },
            },
        )

        js_application = ApplicationFactory(workflow=self.js_workflow)
        js_application.application_status_id = 105
        js_application.save()
        WorkflowStatusPathFactory(workflow=self.js_workflow, status_previous=105, status_next=108)
        data = {"integrity_token": "XXXYYYZZZ", "error_message": None}
        mock_file_path.return_value = 'dummypath'
        mock_check_affordability.return_value = True
        emulator_check = handle_google_play_integrity_decode_request_task(js_application.id, data)
        self.assertNotEqual(emulator_check, None)
        self.assertEqual(emulator_check.application_id, js_application.id)
        self.assertEqual(
            emulator_check.device_recognition_verdict,
            setting.parameters["response_value"]["decoded_response"]["tokenPayloadExternal"][
                "deviceIntegrity"
            ]["deviceRecognitionVerdict"],
        )
        self.assertEqual(emulator_check.error_msg, None)
        js_application.refresh_from_db()
        self.assertEqual(js_application.status, 108)


class TestSuspiciousFraudAppCheck(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.application_risky_check = ApplicationRiskyCheckFactory(application=self.application)
        self.suspicious_fraud_app = SuspiciousFraudAppsFactory.create_batch(
            2,
            package_names=Iterator(['{com.random.p2p, comm.random.p3p}', '{com.factory.package}']),
            transaction_risky_check=Iterator(['random_p2p', 'factory_package']),
        )
        self.application_risky_decisions = ApplicationRiskyDecisionFactory.create_batch(
            3,
            decision_name=Iterator(
                ['NO DV BYPASS AND NO PVE BYPASS', 'NO DV BYPASS', 'NO PVE BYPASS']
            ),
        )

    def test_suspicious_app_detected(self):
        SdDeviceAppFactory(
            application_id=self.application.id,
            app_package_name='com.random.p2p',
        )
        suspicious_app_check(self.application)

        self.application_risky_check.refresh_from_db()
        self.assertEqual(self.application_risky_check.is_sus_app_detected, True)
        self.assertEqual(self.application_risky_check.sus_app_detected_list, ['com.random.p2p'])
        self.assertEqual(self.application_risky_check.decision.decision_name, 'NO DV BYPASS')

    def test_no_suspicious_app_detected_with_no_sd_device_app_record(self):
        suspicious_app_check(self.application)

        self.application_risky_check.refresh_from_db()
        self.assertEqual(self.application_risky_check.is_sus_app_detected, False)
        self.assertEqual(self.application_risky_check.decision, None)

    def test_no_suspicious_app_detected_in_sd_device_app_record(self):
        SdDeviceAppFactory(application_id=self.application.id, app_package_name='com.game.fgo')
        suspicious_app_check(self.application)

        self.application_risky_check.refresh_from_db()
        self.assertEqual(self.application_risky_check.is_sus_app_detected, False)
        self.assertEqual(self.application_risky_check.decision, None)


class TestPreprocessBankName(TestCase):
    def test_remove_prefix_Mr(self):
        name = remove_prefix('Mr. Albert Einstein')
        self.assertEqual(name, 'Albert Einstein')

    def test_remove_prefix_Dr(self):
        name = remove_prefix('Dr. Albert Einstein')
        self.assertEqual(name, 'Albert Einstein')

    def test_remove_prefix_Prof(self):
        name = remove_prefix('Prof. Albert Einstein')
        self.assertEqual(name, 'Albert Einstein')

    def test_remove_prefix_Mrs(self):
        name = remove_prefix('Mrs. Diana')
        self.assertEqual(name, 'Diana')

    def test_remove_prefix_Ms(self):
        name = remove_prefix('Ms. Diana')
        self.assertEqual(name, 'Diana')

    def test_remove_prefix_Sdri(self):
        name = remove_prefix('Sdri. Diana')
        self.assertEqual(name, 'Diana')

    def test_remove_prefix_Ibu(self):
        name = remove_prefix('Ibu Diana')
        self.assertEqual(name, 'Diana')

    def test_remove_prefix_Sdra(self):
        name = remove_prefix('Sdra. Akung')
        self.assertEqual(name, 'Akung')

    def test_remove_prefix_Bapak(self):
        name = remove_prefix('Bapak Akung')
        self.assertEqual(name, 'Akung')

    def test_remove_prefix_with_double_spaces(self):
        name = remove_prefix('Sdra  Akung')
        self.assertEqual(name, 'Akung')

    def test_remove_prefix_with_dash(self):
        name = remove_prefix('Sdra-Akung')
        self.assertEqual(name, 'Akung')

    def test_remove_prefix_with_dash_dot(self):
        name = remove_prefix('Sdra-.Akung')
        self.assertEqual(name, 'Akung')

    def test_remove_prefix_with_number(self):
        name = remove_prefix('Sdra983Akung')
        self.assertEqual(name, 'Akung')

    def test_not_remove_prefix_direct(self):
        name = remove_prefix('SdrAkung')
        self.assertEqual(name, 'SdrAkung')

    def test_remove_double_spaces_in_the_middle_of_name(self):
        name = remove_non_alphabet('Albert  Einstein')
        self.assertEqual(name, 'AlbertEinstein')

    def test_remove_punctuation_in_the_beginning(self):
        name = remove_non_alphabet('!Albert')
        self.assertEqual(name, 'Albert')

    def test_remove_punctuation_in_the_middle(self):
        name = remove_non_alphabet('Alb!ert')
        self.assertEqual(name, 'Albert')

    def test_remove_punctuation_in_the_end(self):
        name = remove_non_alphabet('Albert!')
        self.assertEqual(name, 'Albert')

    def test_remove_punctuation_multiple(self):
        name = remove_non_alphabet('!!Alb!e!!!rt!')
        self.assertEqual(name, 'Albert')


class TestMycroftCheck(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.pd_application_fraud_model_result = PdApplicationFraudModelResultFactory.create(
            application_id=self.application.id, pgood=0.7
        )
        self.mycroft_threshold = MycroftThresholdFactory(score=0.6, logical_operator='>=')
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.MYCROFT_SCORE_CHECK, is_active=True
        )

        self.app_risky_check = ApplicationRiskyCheckFactory(application=self.application)
        current_date = timezone.localtime(timezone.now())
        self.mycroft_holdout = ExperimentSetting.objects.create(
            is_active=True,
            code=ExperimentConst.MYCROFT_HOLDOUT_EXPERIMENT,
            name="MYCROFT HOLDOUT EXPERIMENT",
            start_date=current_date,
            end_date=current_date + relativedelta(years=2),
            schedule="",
            action="",
            type="fraud",
            criteria={},
        )

    def test_mycroft_check_with_valid_application_data(self):
        mycroft_check_result = mycroft_check(self.application)
        mycroft_result = MycroftResult.objects.get(application=self.application)

        self.assertTrue(mycroft_check_result)
        self.assertEqual(0.7, mycroft_result.score)
        self.assertEqual(self.mycroft_threshold.id, mycroft_result.mycroft_threshold.id)
        self.assertEqual(True, mycroft_result.result)

    def test_mycroft_check_no_ana_result(self):
        self.pd_application_fraud_model_result.delete()
        mycroft_check_result = mycroft_check(self.application)
        mycroft_result = MycroftResult.objects.filter(application=self.application)

        self.assertTrue(mycroft_check_result)
        self.assertQuerysetEqual([], mycroft_result)

    def test_check_mycroft_holdout(self):
        is_holdout = check_mycroft_holdout(self.application.id)
        self.assertFalse(is_holdout)
        self.mycroft_holdout.criteria = {"last_digit_app_ids": [int(str(self.application.id)[-1:])]}
        self.mycroft_holdout.save()
        is_holdout = check_mycroft_holdout(self.application.id)
        self.assertTrue(is_holdout)
        self.app_risky_check.refresh_from_db()
        self.assertTrue(self.app_risky_check.is_mycroft_holdout)


@patch('juloserver.application_flow.tasks.check_high_risk_asn', return_value=None)
@patch('juloserver.application_flow.tasks.run_bypass_eligibility_checks')
@patch('juloserver.application_flow.tasks.is_pass_dukcapil_verification_at_x105')
@patch('juloserver.application_flow.tasks.check_scrapped_bank')
@patch('juloserver.application_flow.tasks.check_application_liveness_detection_result')
@patch('juloserver.application_flow.tasks.process_application_status_change')
class TestHandleItiReadyMycroftCheck(TestCase):
    def setUp(self):
        self.now = timezone.localtime(timezone.now())
        self.application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=105),
        )
        self.mycroft_threshold = MycroftThresholdFactory(score=0.6, logical_operator='>=')
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.MYCROFT_SCORE_CHECK, is_active=True
        )

        WorkflowStatusPathFactory(
            workflow=self.application.workflow, status_previous=105, status_next=120
        )
        self.credit_score = CreditScoreFactory(score='B+', application_id=self.application.id)
        SdBankStatementDetailFactory(
            id=1,
            sd_bank_account=SdBankAccountFactory(id=1, application_id=self.application.id),
        )

    @patch('juloserver.application_flow.tasks.process_anti_fraud_binary_check', return_value='do_nothing')
    @patch('juloserver.application_flow.tasks.mycroft_check')
    def test_mycroft_feature_not_active(
        self,
        mock_mycroft_check,
        mock_process_anti_fraud_binary_check,
        mock_process_application_status_change,
        mock_check_liveness_result,
        mock_check_scrapped_bank,
        *args,
    ):
        mock_check_scrapped_bank.return_value = True
        mock_check_liveness_result.return_value = True, ''
        mock_mycroft_check.return_value = True
        self.feature_setting.update_safely(is_active=False)

        handle_iti_ready(self.application.id)

        self.application.refresh_from_db()
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            120,
            'Julo one pass medium score',
        )
        mock_mycroft_check.assert_not_called()

    @patch('juloserver.application_flow.tasks.process_anti_fraud_binary_check', return_value='do_nothing')
    @patch('juloserver.application_flow.tasks.mycroft_check')
    def test_mycroft_feature_active_and_check_true(
        self,
        mock_mycroft_check,
        mock_process_anti_fraud_binary_check,
        mock_process_application_status_change,
        mock_check_liveness_result,
        mock_check_scrapped_bank,
        *args,
    ):
        mock_check_scrapped_bank.return_value = True
        mock_check_liveness_result.return_value = True, ''
        mock_mycroft_check.return_value = True

        handle_iti_ready(self.application.id)

        self.application.refresh_from_db()
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            120,
            'Julo one pass medium score',
        )
        mock_mycroft_check.assert_called_once_with(self.application)

    @patch('juloserver.application_flow.tasks.bypass_bpjs_scoring')
    @patch('juloserver.application_flow.tasks.mycroft_check')
    def test_mycroft_feature_active_and_check_false_bypass_bpjs(
        self,
        mock_mycroft_check,
        mock_bypass_bpjs_scoring,
        mock_process_application_status_change,
        mock_check_liveness_result,
        mock_check_scrapped_bank,
        *args,
    ):
        MobileFeatureSettingFactory(feature_name='bpjs_direct', is_active=True)
        mock_check_scrapped_bank.return_value = True
        mock_check_liveness_result.return_value = True, ''
        mock_mycroft_check.return_value = False
        mock_bypass_bpjs_scoring.return_value = True

        handle_iti_ready(self.application.id)

        self.application.refresh_from_db()
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            135,
            'fail to pass Mycroft check',
        )
        mock_mycroft_check.assert_called_once_with(self.application)
        mock_bypass_bpjs_scoring.assert_not_called()

    @patch('juloserver.application_flow.tasks.process_anti_fraud_binary_check', return_value='do_nothing')
    @patch('juloserver.application_flow.tasks.check_mycroft_holdout')
    @patch('juloserver.application_flow.tasks.mycroft_check')
    def test_mycroft_feature_active_and_check_false_and_holdout(
        self,
        mock_mycroft_check,
        mock_check_mycroft_holdout,
        mock_process_anti_fraud_binary_check,
        mock_process_application_status_change,
        mock_check_liveness_result,
        mock_check_scrapped_bank,
        *args,
    ):
        mock_check_scrapped_bank.return_value = True
        mock_check_liveness_result.return_value = True, ''
        mock_mycroft_check.return_value = False
        mock_check_mycroft_holdout.return_value = True

        handle_iti_ready(self.application.id)

        self.application.refresh_from_db()
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            120,
            'Julo one pass medium score',
        )
        mock_mycroft_check.assert_called_once_with(self.application)

    @patch('juloserver.application_flow.tasks.check_mycroft_holdout')
    @patch('juloserver.application_flow.tasks.mycroft_check')
    def test_mycroft_feature_active_and_check_false_and_holdout_false(
        self,
        mock_mycroft_check,
        mock_check_mycroft_holdout,
        mock_process_application_status_change,
        mock_check_liveness_result,
        mock_check_scrapped_bank,
        *args,
    ):
        mock_check_scrapped_bank.return_value = True
        mock_check_liveness_result.return_value = True, ''
        mock_mycroft_check.return_value = False
        mock_check_mycroft_holdout.return_value = False

        handle_iti_ready(self.application.id)

        self.application.refresh_from_db()
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            135,
            'fail to pass Mycroft check',
        )
        mock_mycroft_check.assert_called_once_with(self.application)


@patch('juloserver.application_flow.tasks.check_high_risk_asn', return_value=None)
@patch('juloserver.application_flow.tasks.run_bypass_eligibility_checks')
@patch('juloserver.application_flow.tasks.is_pass_dukcapil_verification_at_x105')
@patch('juloserver.application_flow.tasks.check_scrapped_bank')
@patch('juloserver.application_flow.tasks.check_application_liveness_detection_result')
@patch('juloserver.application_flow.tasks.process_application_status_change')
class TestHandleItiReadyFraudBinaryCheck(TestCase):
    def setUp(self):
        self.now = timezone.localtime(timezone.now())
        self.application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=105),
        )
        WorkflowStatusPathFactory(
            workflow=self.application.workflow, status_previous=105, status_next=120
        )
        WorkflowStatusPathFactory(
            workflow=self.application.workflow, status_previous=105, status_next=133
        )
        self.credit_score = CreditScoreFactory(score='B+', application_id=self.application.id)
        SdBankStatementDetailFactory(
            id=1,
            sd_bank_account=SdBankAccountFactory(id=1, application_id=self.application.id),
        )

    @patch('juloserver.application_flow.tasks.process_anti_fraud_binary_check')
    def test_success_fraud_check(
        self,
        mock_process_fraud_binary_check,
        mock_process_application_status_change,
        mock_check_liveness_result,
        mock_check_scrapped_bank,
        *args,
    ):
        mock_check_scrapped_bank.return_value = True
        mock_check_liveness_result.return_value = True, ''
        mock_process_fraud_binary_check.return_value = 'do_nothing'

        handle_iti_ready(self.application.id)

        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            120,
            'Julo one pass medium score',
        )

    @patch('juloserver.application_flow.tasks.process_anti_fraud_binary_check')
    def test_fail_fraud_check(
        self,
        mock_process_fraud_binary_check,
        mock_process_application_status_change,
        mock_check_liveness_result,
        mock_check_scrapped_bank,
        *args,
    ):
        from juloserver.antifraud.constant.binary_checks import StatusEnum
        mock_check_scrapped_bank.return_value = True
        mock_check_liveness_result.return_value = True, ''
        mock_process_fraud_binary_check.return_value = StatusEnum.MOVE_APPLICATION_TO133

        FeatureSettingFactory(
            feature_name="antifraud_api_onboarding",
            is_active=True,
            parameters={
                'turbo_109': False,
                'j1_x105': True,
                'j1_x120': True,
            },
        )

        handle_iti_ready(self.application.id)
        mock_process_application_status_change.assert_called_once_with(
            application_id=self.application.id,
            new_status_code=133,
            change_reason='Prompted by the Anti Fraud API',
        )

        mock_process_fraud_binary_check.return_value = StatusEnum.MOVE_APPLICATION_TO133
        handle_iti_ready(self.application.id)
        mock_process_application_status_change.assert_called_with(
            application_id=self.application.id,
            new_status_code=133,
            change_reason='Prompted by the Anti Fraud API',
        )


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestNameBankRevalidate(TestCase):
    def setUp(self) -> None:

        turbo_workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)

        self.application = ApplicationFactory(
            workflow=turbo_workflow,
            name_in_bank="Radeon Graphics",
            bank_name='BANK CENTRAL ASIA, Tbk (BCA)',
        )
        self.name_bank_validation = NameBankValidationFactory(
            name_in_bank="Radeon Graphics",
            validated_name="Radeon Graphics",
            account_number=self.application.bank_account_number,
        )
        self.application.name_bank_validation = self.name_bank_validation
        self.application.save()

        BankAccountDestinationFactory(
            customer=self.application.customer,
            name_bank_validation=self.name_bank_validation,
        )

    @patch.object(XfersService, 'validate')
    def test_should_update_application_name_bank(self, mock_xfers):

        mock_xfers.return_value = {
            'id': 2,
            'status': 'SUCCESS',
            'validated_name': 'Radeon Graphics',
            'reason': 'success',
            'error_message': None,
            'account_no': self.name_bank_validation.account_number,
            'bank_abbrev': "BCA",
        }

        self.name_bank_validation.validation_status = NameBankValidationStatus.NAME_INVALID
        self.name_bank_validation.save()

        log = LevenshteinLogFactory(application=self.application)

        revalidate_name_bank_validation(self.application.id, log.id)

        validation = NameBankValidation.objects.filter(
            account_number=self.name_bank_validation.account_number,
            validation_status=NameBankValidationStatus.SUCCESS,
        ).last()

        self.application.refresh_from_db()
        self.assertNotEqual(self.application.name_bank_validation, self.name_bank_validation)
        self.assertEqual(self.application.name_bank_validation, validation)
        changes = ApplicationNameBankValidationChange.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual(changes.old_name_bank_validation_id, self.name_bank_validation.id)
        self.assertEqual(changes.new_name_bank_validation_id, validation.id)

        # Should have bank account destination
        bank_exists = BankAccountDestination.objects.filter(
            name_bank_validation=validation
        ).exists()
        self.assertTrue(bank_exists)

        log.refresh_from_db()
        self.assertIsNotNone(log.start_async_at)
        self.assertIsNotNone(log.end_async_at)

    def test_should_not_update_application_name_bank(self):
        self.name_bank_validation.validation_status = NameBankValidationStatus.SUCCESS
        self.name_bank_validation.save()
        log = LevenshteinLogFactory(application=self.application)

        revalidate_name_bank_validation(self.application.id, log.id)

        self.application.refresh_from_db()
        validation = NameBankValidation.objects.filter(
            account_number=self.name_bank_validation.account_number,
            validation_status=NameBankValidationStatus.SUCCESS,
        ).last()

        self.assertEqual(self.application.name_bank_validation, self.name_bank_validation)
        self.assertEqual(self.application.name_bank_validation, validation)
        changes = ApplicationNameBankValidationChange.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertIsNone(changes)

        bank_exists = BankAccountDestination.objects.filter(
            name_bank_validation=self.name_bank_validation
        ).exists()
        self.assertTrue(bank_exists)

        log.refresh_from_db()
        self.assertIsNotNone(log.start_async_at)
        self.assertIsNotNone(log.end_async_at)


class TestIsSuspiciousDomain(TestCase):
    def setUp(self):
        SuspiciousDomainFactory(email_domain="@test.com")

    def test_suspicious_domain_valid(self):
        suspicious_domain = is_suspicious_domain('test@test.com')
        self.assertTrue(suspicious_domain)

    def test_suspicious_domain_invalid(self):
        suspicious_domain = is_suspicious_domain('test@gmail.com')
        self.assertFalse(suspicious_domain)

    def test_suspicious_domain_blankspace(self):
        suspicious_domain = is_suspicious_domain(' ')
        self.assertFalse(suspicious_domain)

    def test_suspicious_domain_None(self):
        suspicious_domain = is_suspicious_domain(None)
        self.assertFalse(suspicious_domain)


class TestApplicationUpdate(TestCase):
    url = '/api/application_flow/v1/bottom-sheet-tutorial'

    def setUp(self) -> None:
        self.client = APIClient()

    def test_feature_setting_not_found(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 404)

    def test_success(self):
        FeatureSettingFactory(
            feature_name="tutorial_bottom_sheet",
            is_active=True,
            parameters={
                'title': 'Aktifkan Lokasi di Google Chrome, Ya!',
                'image_url': 'info-card/TUTORIAL_BOTTOM_SHEET.png',
                'subtitle': 'Biar bisa lanjut proses registrasinya, aktifkan lokasimu dulu, '
                'yuk!!!! Gini caranya:',
                'step': (
                    '<ul>'
                    '<li>Buka “Setting” di Google Chrome</li>'
                    '<li>Klik “Site settings” lalu klik “Location”</li>'
                    '<li>Lihat bagian “Blocked” lalu klik “julo.co.id”</li>'
                    '<li>Ubah dari “Block” ke “Allow”</li>'
                    '<li>Asik, aktivasi lokasimu di Google Chrome berhasil!</li>'
                    '</ul>'
                ),
                'button_text': 'Mengerti',
            },
        )
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)


@patch('juloserver.application_flow.tasks.check_high_risk_asn', return_value=None)
@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestShopeeWhitelist(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=105),
        )
        self.application.mobile_phone_1 = "628179186373"
        self.application.save()
        self.mycroft_threshold = MycroftThresholdFactory(score=0.6, logical_operator='>=')
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.MYCROFT_SCORE_CHECK, is_active=True
        )

        EligibleCheckFactory(
            application_id=self.application.id,
            check_name="eligible_vendor_check",
        )

        WorkflowStatusPathFactory(
            workflow=self.application.workflow, status_previous=105, status_next=120
        )
        WorkflowStatusPathFactory(
            workflow=self.application.workflow, status_previous=105, status_next=135
        )
        SdBankStatementDetailFactory(
            id=1,
            sd_bank_account=SdBankAccountFactory(id=1, application_id=self.application.id),
        )
        _criteria = {
            "criteria_1": {
                "heimdall": {"bottom_threshold": 0.45, "upper_threshold": 0.5},
                "mycroft": {"bottom_threshold": 0.8},
                "fdc": "pass",
                "limit": 3000,
                "tag": "is_fail_heimdall_whitelisted",
            },
            "criteria_2": {
                "heimdall": {"bottom_threshold": 0.75, "upper_threshold": 0.85},
                "mycroft": {"bottom_threshold": 0.8},
                "fdc": "not_found",
                "limit": 3000,
                "tag": "is_no_fdc_whitelisted",
            },
            "criteria_3": {
                "heimdall": {"bottom_threshold": 0.51, "upper_threshold": 1},
                "mycroft": {"bottom_threshold": 0.75, "upper_threshold": 0.8},
                "fdc": "pass",
                "limit": 3000,
                "tag": "is_fail_mycroft_whitelisted",
            },
        }
        self.whitelist_setting = ExperimentSettingFactory(
            code=ExperimentConst.SHOPEE_WHITELIST_EXPERIMENT,
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=True,
            is_permanent=False,
            action='{"criteria_1": 10, "criteria_2": 15, "criteria_3": 20}',
            criteria=_criteria,
        )

        for criterion in _criteria:
            tag = _criteria[criterion]["tag"]
            ApplicationTagFactory(application_tag=tag)
            ApplicationPathTagStatusFactory(application_tag=tag, status=1, definition="success")

            _min = _criteria[criterion]["heimdall"]["bottom_threshold"]
            _max = _criteria[criterion]["heimdall"]["upper_threshold"]
            cm = CreditMatrixFactory(
                credit_matrix_type="julo1",
                min_threshold=_min,
                max_threshold=_max,
                score_tag=f"B--: {_min} - {_max}",
                score="B--",
                transaction_type="self",
                parameter="feature:shopee_whitelist",
            )
            CurrentCreditMatrixFactory(credit_matrix=cm)

    @patch('juloserver.application_flow.tasks.run_bypass_eligibility_checks')
    @patch('juloserver.application_flow.tasks.is_pass_dukcapil_verification_at_x105')
    @patch('juloserver.application_flow.tasks.check_scrapped_bank')
    @patch('juloserver.application_flow.tasks.check_application_liveness_detection_result')
    @patch('juloserver.application_flow.tasks.process_application_status_change')
    @patch('juloserver.application_flow.tasks.check_mycroft_holdout')
    @patch('juloserver.application_flow.tasks.mycroft_check')
    def test_experiment_is_turned_off_when_mycroft_feature_active_and_check_false_and_holdout_false(
        self,
        mock_mycroft_check,
        mock_check_mycroft_holdout,
        mock_process_application_status_change,
        mock_check_liveness_result,
        mock_check_scrapped_bank,
        *args,
    ):
        """Expecting to go to x135"""
        self.whitelist_setting.is_active = False
        self.whitelist_setting.save()

        mock_check_scrapped_bank.return_value = True
        mock_check_liveness_result.return_value = True, ''
        mock_mycroft_check.return_value = False
        mock_check_mycroft_holdout.return_value = False

        handle_iti_ready(self.application.id)

        self.application.refresh_from_db()
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            135,
            'fail to pass Mycroft check',
        )
        mock_mycroft_check.assert_called_once_with(self.application)

    @patch('juloserver.application_flow.tasks.run_bypass_eligibility_checks')
    @patch('juloserver.application_flow.tasks.is_pass_dukcapil_verification_at_x105')
    @patch('juloserver.application_flow.tasks.check_scrapped_bank')
    @patch('juloserver.application_flow.tasks.check_application_liveness_detection_result')
    @patch('juloserver.application_flow.tasks.process_application_status_change')
    @patch('juloserver.application_flow.tasks.bypass_bpjs_scoring')
    @patch('juloserver.application_flow.tasks.mycroft_check')
    def test_experiment_is_turned_off_when_mycroft_feature_active_check_false_and_bypass_bpjs(
        self,
        mock_mycroft_check,
        mock_bypass_bpjs_scoring,
        mock_process_application_status_change,
        mock_check_liveness_result,
        mock_check_scrapped_bank,
        *args,
    ):
        """Expecting to go to x135"""

        self.whitelist_setting.is_active = False
        self.whitelist_setting.save()

        MobileFeatureSettingFactory(feature_name='bpjs_direct', is_active=True)
        mock_check_scrapped_bank.return_value = True
        mock_check_liveness_result.return_value = True, ''
        mock_mycroft_check.return_value = False
        mock_bypass_bpjs_scoring.return_value = True

        handle_iti_ready(self.application.id)

        self.application.refresh_from_db()
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            135,
            'fail to pass Mycroft check',
        )
        mock_mycroft_check.assert_called_once_with(self.application)
        mock_bypass_bpjs_scoring.assert_not_called()

    ### ---------  SCENARIO 1 --------- ###

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.apiv2.services.is_inside_premium_area', return_value=True)
    @patch.object(ShopeeWhitelist, '_pass_shopee_whitelist_dynamic_check', return_value=True)
    @patch.object(TelcoScore, 'run_in_105', return_value=False)
    @patch.object(XL, "call_score_endpoint")
    @patch('juloserver.account.services.credit_matrix.get_good_score_j1')
    @patch.object(ShopeeScoring, 'call')
    def test_good_fdc_fail_heimdall_good_mycroft_whitelist(
        self, mock_shopee, mock_good_score_j1, *args
    ):
        """Scenario 1:
        Make heimdall: 0.5, mycroft 0.9, has fdc with fdc inquiry loan.
        Shopee whitelist.
        """
        mock_shopee.return_value = {
            "code": "2000",
            "msg": "Success",
            "sign_type": "RSA-SHA256",
            "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
            "encrypt": False,
            "encrypt_type": "",
            "flow_no": "45b0b68746d74b1ca0fd355468230753",
            "timestamp": 1664347920722,
            "biz_code": "200000",
            "biz_msg": "Success",
            "biz_data": "{\"hit_flag\":0}",
        }
        mock_good_score_j1.return_value = (
            'C',
            'credit_matrix_low_score.list_product_lines',
            'pesan',
            'c_low_credit_score',
            1,
            1,
        )

        PdCreditModelResultFactory(
            application_id=self.application.id,
            probability_fpd=0.5,
            pgood=0.5,
            credit_score_type='A',
            has_fdc=True,
        )
        PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.9,
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check="fdc_inquiry_check"
        )

        get_credit_score3(self.application.id)

        apts = ApplicationPathTagStatus.objects.filter(
            application_tag="is_fail_heimdall_whitelisted", status=1
        ).last()
        exists = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=apts
        ).exists()
        self.assertTrue(exists)
        self.assertEqual(self.application.creditscore.score, 'B--')

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.apiv2.services.is_inside_premium_area', return_value=True)
    @patch.object(ShopeeWhitelist, '_pass_shopee_whitelist_dynamic_check', return_value=True)
    @patch.object(TelcoScore, 'run_in_105', return_value=False)
    @patch.object(XL, "call_score_endpoint")
    @patch('juloserver.account.services.credit_matrix.get_good_score_j1')
    @patch.object(ShopeeScoring, 'call')
    def test_good_fdc_fail_heimdall_good_mycroft_blacklist(
        self, mock_shopee, mock_good_score_j1, *args
    ):
        """Scenario 1: expected to C
        Make heimdall: 0.5, mycroft 0.9, has fdc with fdc inquiry loan.
        Shopee blacklist.
        """
        mock_shopee.return_value = {
            "code": "2000",
            "msg": "Success",
            "sign_type": "RSA-SHA256",
            "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
            "encrypt": False,
            "encrypt_type": "",
            "flow_no": "45b0b68746d74b1ca0fd355468230753",
            "timestamp": 1664347920722,
            "biz_code": "200000",
            "biz_msg": "Success",
            "biz_data": "{\"hit_flag\":1,\"hit_reason_code\":\"100\",\"list_type\":1}",
        }
        mock_good_score_j1.return_value = (
            'C',
            'credit_matrix_low_score.list_product_lines',
            'pesan',
            'c_low_credit_score',
            1,
            1,
        )

        PdCreditModelResultFactory(
            application_id=self.application.id,
            probability_fpd=0.5,
            pgood=0.5,
            credit_score_type='A',
            has_fdc=True,
        )
        PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.9,
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check="fdc_inquiry_check"
        )

        get_credit_score3(self.application.id)

        apts = ApplicationPathTagStatus.objects.filter(
            application_tag="is_fail_heimdall_whitelisted", status=1
        ).last()
        exists = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=apts
        ).exists()
        self.assertFalse(exists)
        self.assertEqual(self.application.creditscore.score, "C")

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.apiv2.services.is_inside_premium_area', return_value=True)
    @patch.object(ShopeeWhitelist, '_pass_shopee_whitelist_dynamic_check', return_value=True)
    @patch.object(TelcoScore, 'run_in_105', return_value=False)
    @patch.object(XL, "call_score_endpoint")
    @patch('juloserver.account.services.credit_matrix.get_good_score_j1')
    @patch.object(ShopeeScoring, 'call')
    def test_good_fdc_fail_heimdall_good_mycroft_whitelist_quota_exhausted(
        self, mock_shopee, mock_good_score_j1, *args
    ):
        """Scenario 1: Expecting C,
        Make heimdall: 0.5, mycroft 0.9, has fdc with fdc inquiry loan.
        Shopee whitelist, quota: 0.
        """
        import json

        action = self.whitelist_setting.action
        cache = json.loads(action)
        cache['criteria_1'] = 3000
        self.whitelist_setting.action = json.dumps(cache)
        self.whitelist_setting.save()

        mock_shopee.return_value = {
            "code": "2000",
            "msg": "Success",
            "sign_type": "RSA-SHA256",
            "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
            "encrypt": False,
            "encrypt_type": "",
            "flow_no": "45b0b68746d74b1ca0fd355468230753",
            "timestamp": 1664347920722,
            "biz_code": "200000",
            "biz_msg": "Success",
            "biz_data": "{\"hit_flag\":0}",
        }
        mock_good_score_j1.return_value = (
            'C',
            'credit_matrix_low_score.list_product_lines',
            'pesan',
            'c_low_credit_score',
            1,
            1,
        )

        PdCreditModelResultFactory(
            application_id=self.application.id,
            probability_fpd=0.5,
            pgood=0.5,
            credit_score_type='A',
            has_fdc=True,
        )
        PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.9,
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check="fdc_inquiry_check"
        )

        get_credit_score3(self.application.id)

        apts = ApplicationPathTagStatus.objects.filter(
            application_tag="is_fail_heimdall_whitelisted", status=1
        ).last()
        exists = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=apts
        ).exists()
        self.assertFalse(exists)
        self.assertEqual(self.application.creditscore.score, "C")

    #### ----- SCENARIO 2 ----- ####

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.apiv2.services.is_inside_premium_area', return_value=True)
    @patch.object(ShopeeWhitelist, '_pass_shopee_whitelist_dynamic_check', return_value=True)
    @patch.object(TelcoScore, 'run_in_105', return_value=False)
    @patch.object(XL, "call_score_endpoint")
    @patch('juloserver.account.services.credit_matrix.get_good_score_j1')
    @patch.object(ShopeeScoring, 'call')
    def test_no_fdc_fail_heimdall_good_mycroft(self, mock_shopee, mock_good_score_j1, *args):
        """Scenario 2: Expecting get B--, has tag
        No FDC, Heimdall: 0.76, Mycroft: 0.9
        Whitelist.
        """
        mock_shopee.return_value = {
            "code": "2000",
            "msg": "Success",
            "sign_type": "RSA-SHA256",
            "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
            "encrypt": False,
            "encrypt_type": "",
            "flow_no": "45b0b68746d74b1ca0fd355468230753",
            "timestamp": 1664347920722,
            "biz_code": "200000",
            "biz_msg": "Success",
            "biz_data": "{\"hit_flag\":0}",
        }
        mock_good_score_j1.return_value = (
            'C',
            'credit_matrix_low_score.list_product_lines',
            'pesan',
            'c_low_credit_score',
            1,
            1,
        )

        PdCreditModelResultFactory(
            application_id=self.application.id,
            probability_fpd=0.76,
            pgood=0.76,
            credit_score_type='A',
            has_fdc=False,
        )
        PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.9,
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check="fdc_inquiry_check"
        )

        get_credit_score3(self.application.id)

        apts = ApplicationPathTagStatus.objects.filter(
            application_tag="is_no_fdc_whitelisted", status=1
        ).last()
        exists = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=apts
        ).exists()
        self.assertTrue(exists)
        self.assertEqual(self.application.creditscore.score, 'B--')

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.apiv2.services.is_inside_premium_area', return_value=True)
    @patch.object(ShopeeWhitelist, '_pass_shopee_whitelist_dynamic_check', return_value=True)
    @patch.object(TelcoScore, 'run_in_105', return_value=False)
    @patch.object(XL, "call_score_endpoint")
    @patch('juloserver.account.services.credit_matrix.get_good_score_j1')
    @patch.object(ShopeeScoring, 'call')
    def test_no_fdc_fail_heimdall_good_mycroft_blacklisted(
        self, mock_shopee, mock_good_score_j1, *args
    ):
        """Scenario 2: Expecting get B--, has tag
        No FDC, Heimdall: 0.76, Mycroft: 0.9
        Blacklist.
        """
        mock_shopee.return_value = {
            "code": "2000",
            "msg": "Success",
            "sign_type": "RSA-SHA256",
            "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
            "encrypt": False,
            "encrypt_type": "",
            "flow_no": "45b0b68746d74b1ca0fd355468230753",
            "timestamp": 1664347920722,
            "biz_code": "200000",
            "biz_msg": "Success",
            "biz_data": "{\"hit_flag\":1,\"hit_reason_code\":\"100\",\"list_type\":1}",
        }
        mock_good_score_j1.return_value = (
            'C',
            'credit_matrix_low_score.list_product_lines',
            'pesan',
            'c_low_credit_score',
            1,
            1,
        )

        PdCreditModelResultFactory(
            application_id=self.application.id,
            probability_fpd=0.76,
            pgood=0.76,
            credit_score_type='A',
            has_fdc=False,
        )
        PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.9,
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check="fdc_inquiry_check"
        )

        get_credit_score3(self.application.id)

        apts = ApplicationPathTagStatus.objects.filter(
            application_tag="is_no_fdc_whitelisted", status=1
        ).last()
        exists = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=apts
        ).exists()
        self.assertFalse(exists)
        self.assertEqual(self.application.creditscore.score, "C")

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.apiv2.services.is_inside_premium_area', return_value=True)
    @patch.object(ShopeeWhitelist, '_pass_shopee_whitelist_dynamic_check', return_value=True)
    @patch.object(TelcoScore, 'run_in_105', return_value=False)
    @patch.object(XL, "call_score_endpoint")
    @patch('juloserver.account.services.credit_matrix.get_good_score_j1')
    @patch.object(ShopeeScoring, 'call')
    def test_no_fdc_fail_heimdall_good_mycroft_quota_exhausted(
        self, mock_shopee, mock_good_score_j1, *args
    ):
        """Scenario 2: Expecting get B--, has tag
        No FDC, Heimdall: 0.76, Mycroft: 0.9
        Whitelist.
        """
        import json

        action = self.whitelist_setting.action
        cache = json.loads(action)
        cache['criteria_2'] = 3000
        self.whitelist_setting.action = json.dumps(cache)
        self.whitelist_setting.save()

        mock_shopee.return_value = {
            "code": "2000",
            "msg": "Success",
            "sign_type": "RSA-SHA256",
            "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
            "encrypt": False,
            "encrypt_type": "",
            "flow_no": "45b0b68746d74b1ca0fd355468230753",
            "timestamp": 1664347920722,
            "biz_code": "200000",
            "biz_msg": "Success",
            "biz_data": "{\"hit_flag\":0}",
        }
        mock_good_score_j1.return_value = (
            'C',
            'credit_matrix_low_score.list_product_lines',
            'pesan',
            'c_low_credit_score',
            1,
            1,
        )

        PdCreditModelResultFactory(
            application_id=self.application.id,
            probability_fpd=0.76,
            pgood=0.76,
            credit_score_type='A',
            has_fdc=False,
        )
        PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.9,
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check="fdc_inquiry_check"
        )

        get_credit_score3(self.application.id)

        apts = ApplicationPathTagStatus.objects.filter(
            application_tag="is_no_fdc_whitelisted", status=1
        ).last()
        exists = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=apts
        ).exists()
        self.assertFalse(exists)
        self.assertEqual(self.application.creditscore.score, "C")

    ### ------ SCENARIO 3 ----- ###

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.apiv2.services.is_inside_premium_area', return_value=True)
    @patch.object(ShopeeWhitelist, '_pass_shopee_whitelist_dynamic_check', return_value=True)
    @patch.object(TelcoScore, 'run_in_105', return_value=False)
    @patch.object(XL, "call_score_endpoint")
    @patch('juloserver.account.services.credit_matrix.get_good_score_j1')
    @patch.object(ShopeeScoring, 'call')
    def test_good_fdc_good_heimdall_fail_mycroft(self, mock_shopee, mock_good_score_j1, *args):
        """Scenario 3: Expecting get B--, has tag
        Pass FDC, Heimdall: 0.8, Mycroft: 0.8
        Whitelist"""

        mock_shopee.return_value = {
            "code": "2000",
            "msg": "Success",
            "sign_type": "RSA-SHA256",
            "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
            "encrypt": False,
            "encrypt_type": "",
            "flow_no": "45b0b68746d74b1ca0fd355468230753",
            "timestamp": 1664347920722,
            "biz_code": "200000",
            "biz_msg": "Success",
            "biz_data": "{\"hit_flag\":0}",
        }
        mock_good_score_j1.return_value = (
            'C',
            'credit_matrix_low_score.list_product_lines',
            'pesan',
            'c_low_credit_score',
            1,
            1,
        )

        PdCreditModelResultFactory(
            application_id=self.application.id,
            probability_fpd=0.8,
            pgood=0.8,
            credit_score_type='A',
            has_fdc=True,
        )
        PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.8,
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check="fdc_inquiry_check"
        )

        get_credit_score3(self.application.id)

        apts = ApplicationPathTagStatus.objects.filter(
            application_tag="is_fail_mycroft_whitelisted", status=1
        ).last()
        exists = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=apts
        ).exists()
        self.assertTrue(exists)
        self.assertEqual(self.application.creditscore.score, 'B--')

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.apiv2.services.is_inside_premium_area', return_value=True)
    @patch.object(ShopeeWhitelist, '_pass_shopee_whitelist_dynamic_check', return_value=True)
    @patch.object(TelcoScore, 'run_in_105', return_value=False)
    @patch.object(XL, "call_score_endpoint")
    @patch('juloserver.account.services.credit_matrix.get_good_score_j1')
    @patch.object(ShopeeScoring, 'call')
    def test_good_fdc_good_heimdall_fail_mycroft_blacklisted(
        self, mock_shopee, mock_good_score_j1, *args
    ):
        """Scenario 3: Expecting get B--, has tag
        Pass FDC, Heimdall: 0.8, Mycroft: 0.8
        Blacklisted"""

        mock_shopee.return_value = {
            "code": "2000",
            "msg": "Success",
            "sign_type": "RSA-SHA256",
            "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
            "encrypt": False,
            "encrypt_type": "",
            "flow_no": "45b0b68746d74b1ca0fd355468230753",
            "timestamp": 1664347920722,
            "biz_code": "200000",
            "biz_msg": "Success",
            "biz_data": "{\"hit_flag\":1,\"hit_reason_code\":\"100\",\"list_type\":1}",
        }
        mock_good_score_j1.return_value = (
            'C',
            'credit_matrix_low_score.list_product_lines',
            'pesan',
            'c_low_credit_score',
            1,
            1,
        )

        PdCreditModelResultFactory(
            application_id=self.application.id,
            probability_fpd=0.8,
            pgood=0.8,
            credit_score_type='A',
            has_fdc=True,
        )
        PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.8,
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check="fdc_inquiry_check"
        )

        get_credit_score3(self.application.id)

        apts = ApplicationPathTagStatus.objects.filter(
            application_tag="is_fail_mycroft_whitelisted", status=1
        ).last()
        exists = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=apts
        ).exists()
        self.assertFalse(exists)
        self.assertEqual(self.application.creditscore.score, 'C')

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.apiv2.services.is_inside_premium_area', return_value=True)
    @patch.object(ShopeeWhitelist, '_pass_shopee_whitelist_dynamic_check', return_value=True)
    @patch.object(TelcoScore, 'run_in_105', return_value=False)
    @patch.object(XL, "call_score_endpoint")
    @patch('juloserver.account.services.credit_matrix.get_good_score_j1')
    @patch.object(ShopeeScoring, 'call')
    def test_good_fdc_good_heimdall_fail_mycroft_quota_exhausted(
        self, mock_shopee, mock_good_score_j1, *args
    ):
        """Scenario 3: Expecting get B--, has tag
        Pass FDC, Heimdall: 0.8, Mycroft: 0.8
        Whitelisted"""

        import json

        action = self.whitelist_setting.action
        cache = json.loads(action)
        cache['criteria_3'] = 3000
        self.whitelist_setting.action = json.dumps(cache)
        self.whitelist_setting.save()

        mock_shopee.return_value = {
            "code": "2000",
            "msg": "Success",
            "sign_type": "RSA-SHA256",
            "sign": "hSg3DFcBOko45un8xWJ7tiFpMubY3h12SdSjgMi4FTa+uzIPSLrvE0f8Z2KK+ygfCzMuBGhiqm+TsH4Ozo81UwvmvmOMSdcuHTptpAu1SQn4SljG7wgwvyhQoLGKQPKpzYu9iaOpqvPi10BcuDgQaSMyfzwU02w1VyYul4Q7K4g/pE5HZTWhd4BVBl3ZOW1z3IbVGMifN6VxPKL4rsaORKaADfCwibcJ3ytlKENzNxZVLZ2Sk0jS/xHrvh+BVjmTyRg278s7YTnMuxO4VCLzxZIwyo/3tfjXtc+W20yoxBRGk2k9x6EGIlk8J/aQ4D5tmd1cNQRi6LGuBvIAXtq/0g==",
            "encrypt": False,
            "encrypt_type": "",
            "flow_no": "45b0b68746d74b1ca0fd355468230753",
            "timestamp": 1664347920722,
            "biz_code": "200000",
            "biz_msg": "Success",
            "biz_data": "{\"hit_flag\":0}",
        }
        mock_good_score_j1.return_value = (
            'C',
            'credit_matrix_low_score.list_product_lines',
            'pesan',
            'c_low_credit_score',
            1,
            1,
        )

        PdCreditModelResultFactory(
            application_id=self.application.id,
            probability_fpd=0.8,
            pgood=0.8,
            credit_score_type='A',
            has_fdc=True,
        )
        PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.8,
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check="fdc_inquiry_check"
        )

        get_credit_score3(self.application.id)

        apts = ApplicationPathTagStatus.objects.filter(
            application_tag="is_fail_mycroft_whitelisted", status=1
        ).last()
        exists = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=apts
        ).exists()
        self.assertFalse(exists)
        self.assertEqual(self.application.creditscore.score, 'C')

    ### NORMAL ###

    @patch('juloserver.account.services.credit_limit.get_salaried', return_value=True)
    @patch('juloserver.apiv2.services.is_inside_premium_area', return_value=True)
    @patch.object(ShopeeWhitelist, '_pass_shopee_whitelist_dynamic_check', return_value=True)
    @patch.object(TelcoScore, 'run_in_105', return_value=False)
    @patch.object(XL, "call_score_endpoint")
    @patch('juloserver.account.services.credit_matrix.get_good_score_j1')
    def test_no_fdc_good_heimdall_good_mycroft(self, mock_good_score_j1, *args):
        """Normal: Expecting to x120, without tag
        No FDC, Heimdall: 0.86, mycroft: 0.9
        Whitelist
        """

        mock_good_score_j1.return_value = (
            'A',
            'credit_matrix_low_score.list_product_lines',
            'pesan',
            'A+++',
            1,
            1,
        )
        PdCreditModelResultFactory(
            application_id=self.application.id,
            probability_fpd=0.86,
            pgood=0.86,
            credit_score_type='A',
            has_fdc=False,
        )
        PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.9,
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check="fdc_inquiry_check"
        )

        get_credit_score3(self.application.id)

        apts = ApplicationPathTagStatus.objects.filter(
            application_tag__in=(
                "is_fail_heimdall_whitelisted" "is_fail_mycroft_whitelisted",
                "is_fail_mycroft_whitelisted",
            ),
            status=1,
        )
        exists = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status__in=apts
        ).exists()
        self.assertFalse(exists)
        self.assertEqual(self.application.creditscore.score, 'A')


@patch('juloserver.fraud_security.tasks.remove_application_from_fraud_application_bucket.delay')
@patch('juloserver.application_flow.handlers.insert_fraud_application_bucket.delay')
class TestJuloOne115Handler(TestCase):
    def setUp(self):
        self.j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=121),
        )

        WorkflowStatusNodeFactory(
            workflow=self.j1_workflow,
            status_node=115,
            handler='JuloOne115Handler',
        )
        WorkflowStatusNodeFactory(
            workflow=self.j1_workflow,
            status_node=120,
            handler='JuloOne120Handler',
        )
        WorkflowStatusNodeFactory(
            workflow=self.j1_workflow,
            status_node=121,
            handler='JuloOne121Handler',
        )
        WorkflowStatusNodeFactory(
            workflow=self.j1_workflow,
            status_node=132,
            handler='JuloOne132Handler',
        )
        WorkflowStatusPathFactory(
            status_previous=121,
            status_next=115,
            workflow=self.j1_workflow,
            is_active=True,
        )
        WorkflowStatusPathFactory(
            status_previous=115,
            status_next=121,
            workflow=self.j1_workflow,
            is_active=True,
        )
        WorkflowStatusPathFactory(
            status_previous=115,
            status_next=132,
            workflow=self.j1_workflow,
            is_active=True,
        )
        WorkflowStatusPathFactory(
            status_previous=115,
            status_next=120,
            workflow=self.j1_workflow,
            is_active=True,
        )

    def test_move_x121_to_x115(self, mock_insert_function, mock_remove_function):
        ret_val = process_application_status_change(
            self.application,
            115,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )

        self.assertTrue(ret_val)

        force_run_on_commit_hook()
        mock_insert_function.assert_called_once_with(
            self.application.id,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )
        mock_remove_function.assert_not_called()

    def test_move_x115_to_x121(self, mock_insert_function, mock_remove_function):
        self.application.update_safely(application_status_id=115)
        ret_val = process_application_status_change(
            self.application,
            121,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )

        self.assertTrue(ret_val)

        force_run_on_commit_hook()
        mock_insert_function.assert_not_called()
        mock_remove_function.assert_called_once_with(self.application.id)

    def test_move_x115_to_x132(self, mock_insert_function, mock_remove_function):
        self.application.update_safely(application_status_id=115)
        ret_val = process_application_status_change(
            self.application,
            132,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )

        self.assertTrue(ret_val)

        force_run_on_commit_hook()
        mock_insert_function.assert_not_called()
        mock_remove_function.assert_called_once_with(self.application.id)

    def test_move_x115_to_x120(self, mock_insert_function, mock_remove_function):
        self.application.update_safely(application_status_id=115)
        ret_val = process_application_status_change(
            self.application,
            120,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )

        self.assertTrue(ret_val)

        force_run_on_commit_hook()
        mock_insert_function.assert_not_called()
        mock_remove_function.assert_called_once_with(self.application.id)


class TestPowerCredBankStatement(TestCase):
    def setUp(self) -> None:
        self.name_bank_validation = NameBankValidationFactory(account_number="4760157576")
        customer = CustomerFactory()
        self.application = ApplicationFactory(
            name_bank_validation=self.name_bank_validation, customer=customer
        )
        device = DeviceFactory(customer=customer)

        self.request = {
            "data": {
                "Account": [
                    {
                        "Account Holder name": "ANGIN LALU",
                        "Account Number": "4760157576",
                        "Address": "",
                        "Bank Name": "BNI",
                        "Period": "February 2023, March 2023, April 2023",
                        "Type": "",
                    }
                ],
                "Analysis": {
                    "4760157576": [
                        {
                            "Ending balances": 12639.15,
                            "Starting balances": 10578.15,
                            "average_EOD_balance": 776968.08,
                            "index": "Feb-2023",
                            "max_EOD_balance": 4372578.15,
                            "min_EOD_balance": 10139.15,
                            "month": "Feb-2023",
                            "total_amount_of_cash_deposits": 0,
                            "total_amount_of_cash_withdrawals": 0,
                            "total_amount_of_credit_transactions": 21665910,
                            "total_amount_of_debit_transactions": 21663849,
                            "total_credit_transactions": 9,
                            "total_debit_transactions": 23,
                            "total_number_of_cash_deposits": 0,
                            "total_number_of_cash_withdrawals": 0,
                        },
                        {
                            "Ending balances": 18190.15,
                            "Starting balances": 12639.15,
                            "average_EOD_balance": 44609.18,
                            "index": "Mar-2023",
                            "max_EOD_balance": 620171.15,
                            "min_EOD_balance": 2553.15,
                            "month": "Mar-2023",
                            "total_amount_of_cash_deposits": 0,
                            "total_amount_of_cash_withdrawals": 0,
                            "total_amount_of_credit_transactions": 18198120,
                            "total_amount_of_debit_transactions": 18192569,
                            "total_credit_transactions": 13,
                            "total_debit_transactions": 23,
                            "total_number_of_cash_deposits": 0,
                            "total_number_of_cash_withdrawals": 0,
                        },
                        {
                            "Ending balances": 10530.15,
                            "Starting balances": 18190.15,
                            "average_EOD_balance": 422715.68,
                            "index": "Apr-2023",
                            "max_EOD_balance": 2368530.15,
                            "min_EOD_balance": 10007.15,
                            "month": "Apr-2023",
                            "total_amount_of_cash_deposits": 6341971,
                            "total_amount_of_cash_withdrawals": 0,
                            "total_amount_of_credit_transactions": 35664772,
                            "total_amount_of_debit_transactions": 35672432,
                            "total_credit_transactions": 14,
                            "total_debit_transactions": 32,
                            "total_number_of_cash_deposits": 1,
                            "total_number_of_cash_withdrawals": 0,
                        },
                    ]
                },
                "fraud_indicators": [],
                "credentials": {
                    "user_id": str(customer.user_id),
                    "client": self.application.email,
                    "application_xid": str(self.application.application_xid),
                    "device_id": str(device.id),
                },
            }
        }

    @patch.object(PowerCred, 'process_callback')
    def test_process_callback_called_from_class_method(self, mock_process_callback):
        PowerCred.callback(self.request)

        mock_process_callback.assert_called()

    def test_get_analyzed_account(self):
        power_cred = PowerCred(self.application)
        power_cred.get_analyzed_account(self.request["data"]["Analysis"])

        self.assertEqual(
            power_cred.analyzed_account, self.request["data"]["Analysis"]["4760157576"]
        )

    def test_consecutive_month_sorted(self):
        power_cred = PowerCred(self.application)
        months = [
            power_cred.cast_to_date("Feb-2023"),
            power_cred.cast_to_date("Mar-2023"),
            power_cred.cast_to_date("Apr-2023"),
        ]

        result = power_cred._is_month_consecutive(months)
        self.assertTrue(result)

    def test_consecutive_month_unsorted(self):
        power_cred = PowerCred(self.application)
        months = [
            power_cred.cast_to_date("Mar-2023"),
            power_cred.cast_to_date("Feb-2023"),
            power_cred.cast_to_date("Apr-2023"),
        ]

        result = power_cred._is_month_consecutive(months)
        self.assertTrue(result)

    def test_consecutive_month_year_changed(self):
        power_cred = PowerCred(self.application)
        months = [
            power_cred.cast_to_date("Dec-2023"),
            power_cred.cast_to_date("Jan-2024"),
            power_cred.cast_to_date("Feb-2024"),
        ]

        result = power_cred._is_month_consecutive(months)
        self.assertTrue(result)

    def test_unconsecutive_month_sorted(self):
        power_cred = PowerCred(self.application)
        months = [
            power_cred.cast_to_date("Feb-2023"),
            power_cred.cast_to_date("Apr-2023"),
            power_cred.cast_to_date("Sep-2023"),
        ]

        result = power_cred._is_month_consecutive(months)
        self.assertFalse(result)

    def test_unconsecutive_month_unsorted(self):
        power_cred = PowerCred(self.application)
        months = [
            power_cred.cast_to_date("Apr-2023"),
            power_cred.cast_to_date("Sep-2023"),
            power_cred.cast_to_date("Feb-2023"),
        ]

        result = power_cred._is_month_consecutive(months)
        self.assertFalse(result)

    @patch.object(PowerCred, '_current_time')
    def test_without_gap(self, mock_current_time):
        mock_current_time.return_value = datetime.strptime("2023-10-1", "%Y-%m-%d")

        power_cred = PowerCred(self.application)

        months = [
            power_cred.cast_to_date("Jul-2023"),
            power_cred.cast_to_date("Aug-2023"),
            power_cred.cast_to_date("Sep-2023"),
        ]
        self.assertTrue(power_cred._in_accepted_gap(months))

    @patch.object(PowerCred, '_current_time')
    def test_gap_a_month(self, mock_current_time):
        mock_current_time.return_value = datetime.strptime("2023-10-1", "%Y-%m-%d")

        power_cred = PowerCred(self.application)

        months = [
            power_cred.cast_to_date("Jun-2023"),
            power_cred.cast_to_date("Jul-2023"),
            power_cred.cast_to_date("Aug-2023"),
        ]
        self.assertTrue(power_cred._in_accepted_gap(months))

    @patch.object(PowerCred, '_current_time')
    def test_gap_two_month(self, mock_current_time):
        mock_current_time.return_value = datetime.strptime("2023-10-1", "%Y-%m-%d")

        power_cred = PowerCred(self.application)

        months = [
            power_cred.cast_to_date("May-2023"),
            power_cred.cast_to_date("Jun-2023"),
            power_cred.cast_to_date("Jul-2023"),
        ]
        self.assertFalse(power_cred._in_accepted_gap(months))

    @patch.object(PowerCred, '_current_time')
    def test_gap_three_month(self, mock_current_time):
        mock_current_time.return_value = datetime.strptime("2023-10-1", "%Y-%m-%d")
        power_cred = PowerCred(self.application)

        months = [
            power_cred.cast_to_date("Apr-2023"),
            power_cred.cast_to_date("May-2023"),
            power_cred.cast_to_date("Jun-2023"),
        ]
        self.assertFalse(power_cred._in_accepted_gap(months))

    def test_store_response_to_db(self):
        from juloserver.julo.models import BankStatementSubmit, BankStatementSubmitBalance

        power_cred = PowerCred(self.application)
        power_cred.request = self.request
        power_cred.get_analyzed_account(self.request["data"]["Analysis"])
        power_cred.store_request()

        statement = BankStatementSubmit.objects.filter(application_id=self.application.id).last()
        self.assertEqual(statement.vendor, "powercred")
        self.assertEqual(statement.status, "success")
        self.assertEqual(statement.name_in_bank, "ANGIN LALU")

        balances = BankStatementSubmitBalance.objects.filter(bank_statement_submit=statement)
        self.assertEqual(balances.count(), 3)


class TestNonFDCAutoDebit(TestCase):
    def setUp(self) -> None:
        credit_matrix = CreditMatrixFactory(
            credit_matrix_type='julo1_entry_level',
            is_salaried=False,
            is_premium_area=False,
            min_threshold=0.75,
            max_threshold=0.85,
            transaction_type='self',
            parameter=None,
        )
        CurrentCreditMatrixFactory(credit_matrix=credit_matrix)

        self.setting = ExperimentSettingFactory(
            code=ExperimentConst.AUTODEBET_ACTIVATION_EXPERIMENT,
            criteria={"limit": 2500, "upper_threshold": 0.85, "bottom_threshold": 0.75},
            action={"count": 100},
        )
        self.x105_status = StatusLookupFactory(status_code=105)
        self.j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.bpjs_mfs = MobileFeatureSettingFactory(feature_name='bpjs_direct', is_active=False)
        self.application = ApplicationFactory(id=2, workflow=self.j1_workflow)
        self.application.update_safely(application_status=self.x105_status)
        self.credit_model = PdCreditModelResultFactory(
            application_id=self.application.id, has_fdc=False, pgood=0.8, probability_fpd=0.8
        )

    def test_should_not_continue_if_turbo(self):
        from juloserver.application_flow.services2 import AutoDebit

        turbo_workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.update_safely(workflow=turbo_workflow)
        auto_debit = AutoDebit(self.application)
        self.assertFalse(auto_debit.should_continue_in_x105())

    def test_should_not_continue_if_j1_has_partner(self):
        from juloserver.application_flow.services2 import AutoDebit
        from juloserver.julo.tests.factories import PartnerFactory

        partner = PartnerFactory()
        self.application.update_safely(partner=partner)

        auto_debit = AutoDebit(self.application)
        self.assertFalse(auto_debit.should_continue_in_x105())

    def test_should_not_continue_if_not_105(self):
        from juloserver.application_flow.services2 import AutoDebit

        x120 = StatusLookupFactory(status_code=120)
        self.application.update_safely(application_status=x120)
        auto_debit = AutoDebit(self.application)
        self.assertFalse(auto_debit.should_continue_in_x105())

    def test_should_not_continue_if_configuration_disabled(self):
        from juloserver.application_flow.services2 import AutoDebit

        self.setting.update_safely(is_active=False)

        auto_debit = AutoDebit(self.application)
        self.assertFalse(auto_debit.should_continue_in_x105())

    def test_should_not_continue_if_fdc_found(self):
        from juloserver.application_flow.services2 import AutoDebit

        self.credit_model.has_fdc = True
        self.credit_model.save()

        auto_debit = AutoDebit(self.application)
        self.assertFalse(auto_debit.should_continue_in_x105())

    def test_should_not_continue_if_app_odd(self):
        ...

    def test_should_not_continue_if_heimdall_below_threshold(self):
        from juloserver.application_flow.services2 import AutoDebit

        self.credit_model.pgood = 0.74
        self.credit_model.probability_fpd = 0.74
        self.credit_model.save()

        auto_debit = AutoDebit(self.application)
        self.assertFalse(auto_debit.should_continue_in_x105())

    def test_should_not_continue_if_heimdall_above_threshold(self):
        from juloserver.application_flow.services2 import AutoDebit

        self.credit_model.pgood = 0.86
        self.credit_model.probability_fpd = 0.86
        self.credit_model.save()

        auto_debit = AutoDebit(self.application)
        self.assertFalse(auto_debit.should_continue_in_x105())

    def test_should_continue_if_heimdall_in_threshold(self):
        from juloserver.application_flow.services2 import AutoDebit

        auto_debit = AutoDebit(self.application)
        self.assertTrue(auto_debit.should_continue_in_x105())

    def test_should_assign_tag_if_condition_matched(self):
        from juloserver.application_flow.services2 import AutoDebit

        auto_debit = AutoDebit(self.application)
        tagged = auto_debit.decide_to_assign_tag()
        self.assertTrue(tagged)

        # do check to application path tag table

    def test_should_get_proper_credit_matrix(self):
        from juloserver.application_flow.services2 import AutoDebit

        auto_debit = AutoDebit(self.application)
        auto_debit.is_premium_area = False
        auto_debit.decide_to_assign_tag()

        credit_matrix = auto_debit.credit_matrix
        self.assertEqual(credit_matrix.credit_matrix_type, 'julo1_entry_level')


class TestHasApplicationRejectionHistory(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application_denied_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED,
        )
        self.application_approved_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        self.application_expired = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        )
        self.product_line = ProductLineFactory()
        self.product_line2 = ProductLineFactory()

    def test_customer_none(self):
        rejected = has_application_rejection_history(None)
        self.assertFalse(rejected)

    def test_no_application(self):
        rejected = has_application_rejection_history(self.customer)
        self.assertFalse(rejected)

    def test_has_application_rejected(self):
        ApplicationFactory(
            customer=self.customer,
            product_line=self.product_line,
        ).update_safely(application_status=self.application_denied_status)
        ApplicationFactory(
            customer=self.customer,
            product_line=self.product_line2,
        ).update_safely(application_status=self.application_approved_status)

        rejected = has_application_rejection_history(self.customer)
        self.assertTrue(rejected)

    @patch('juloserver.application_flow.services.JuloOneService')
    def test_has_106_c_score_application(self, mock_julo_one_service):
        mock_julo_one_service.return_value.is_c_score.return_value = True
        ApplicationFactory(
            customer=self.customer,
        ).update_safely(application_status=self.application_expired)

        rejected = has_application_rejection_history(self.customer)
        self.assertTrue(rejected)

    @patch('juloserver.application_flow.services.JuloOneService')
    def test_expired_application_not_c_score(self, mock_julo_one_service):
        mock_julo_one_service.return_value.is_c_score.return_value = False
        ApplicationFactory(
            customer=self.customer,
        ).update_safely(application_status=self.application_expired)

        rejected = has_application_rejection_history(self.customer)
        self.assertFalse(rejected)


class TestJuloOne141Handler(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
        self.new_status_code = MagicMock()
        self.change_reason = MagicMock()
        self.note = MagicMock()
        self.old_status_code = MagicMock()
        self.workflow_action = MagicMock()

    @patch('juloserver.application_flow.handlers.fetch_monnai_application_submit_result')
    def test_async_task_successful_execution(
        self,
        mock_fetch_monnai,
    ):
        handler = JuloOne141Handler(
            application=self.application,
            new_status_code=self.new_status_code,
            change_reason=self.change_reason,
            note=self.note,
            old_status_code=self.old_status_code,
        )
        handler.async_task()
        mock_fetch_monnai.delay.assert_called_once_with(application_id=self.application.id)

    @patch('juloserver.application_flow.handlers.JuloOneWorkflowAction')
    @patch('juloserver.application_flow.services.check_revive_mtl', return_value=True)
    def test_post_function_successful_execution(self, mock_revive_mtl, mock_workflow_action):
        handler = JuloOne141Handler(
            application=self.application,
            new_status_code=self.new_status_code,
            change_reason=self.change_reason,
            note=self.note,
            old_status_code=self.old_status_code,
        )
        handler.post()

        mock_workflow_action.return_value.generate_payment_method.assert_called_once()
        mock_workflow_action.return_value.bypass_activation_call.assert_called_once()
        mock_workflow_action.return_value.bypass_entry_level_141.assert_called_once()
        mock_workflow_action.return_value.assign_autodebet_benefit.assert_called_once()

        mock_revive_mtl.assert_called_once_with(self.application)
        mock_workflow_action.return_value.process_validate_bank.assert_called_once()

    @patch('juloserver.application_flow.handlers.JuloOneWorkflowAction')
    @patch('juloserver.application_flow.services.check_revive_mtl', return_value=False)
    def test_post_function_application_not_mtl_skip_validate_bank(
        self, mock_revive_mtl, mock_workflow_action
    ):
        handler = JuloOne141Handler(
            application=self.application,
            new_status_code=self.new_status_code,
            change_reason=self.change_reason,
            note=self.note,
            old_status_code=self.old_status_code,
        )
        handler.post()

        mock_workflow_action.return_value.generate_payment_method.assert_called_once()
        mock_workflow_action.return_value.bypass_activation_call.assert_called_once()
        mock_workflow_action.return_value.bypass_entry_level_141.assert_called_once()
        mock_workflow_action.return_value.assign_autodebet_benefit.assert_called_once()

        mock_revive_mtl.assert_called_once_with(self.application)
        mock_workflow_action.return_value.process_validate_bank.assert_not_called()


class TestSendEventByCertainPgood(TestCase):
    def setUp(self):
        self.j1_application = ApplicationJ1Factory()
        self.j1_application.customer.appsflyer_device_id = 'dasbdj123jksad'
        self.j1_application.customer.save()
        self.j1_pd_model = PdCreditModelResultFactory(
            id=9876544322, application_id=self.j1_application.id, pgood=0.7
        )

    @patch('juloserver.julo.workflows2.tasks.appsflyer_update_status_task')
    @patch('juloserver.application_flow.services.send_event_to_ga_task_async')
    def test_send_ga_event_at_105(
        self,
        mock_send_event_to_ga_task_async,
        mock_appsflyer_update_status_task,
    ):
        self.j1_application.application_status_id = 105
        self.j1_application.save()
        send_application_event_by_certain_pgood(self.j1_application, 105, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': 'x_105_pct70'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='x_105_pct70'
        )

        self.j1_pd_model.pgood = 0.8
        self.j1_pd_model.save()
        send_application_event_by_certain_pgood(self.j1_application, 105, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': 'x_105_pct80'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='x_105_pct80'
        )

        self.j1_pd_model.pgood = 0.9
        self.j1_pd_model.save()
        send_application_event_by_certain_pgood(self.j1_application, 105, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': 'x_105_pct90'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='x_105_pct90'
        )

    @patch('juloserver.julo.workflows2.tasks.appsflyer_update_status_task')
    @patch('juloserver.application_flow.services.send_event_to_ga_task_async')
    def test_send_ga_event_at_190(
        self,
        mock_send_event_to_ga_task_async,
        mock_appsflyer_update_status_task,
    ):
        self.j1_application.application_status_id = 190
        self.j1_application.save()
        send_application_event_by_certain_pgood(self.j1_application, 190, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': 'x_190_pct70'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='x_190_pct70'
        )

        self.j1_pd_model.pgood = 0.8
        self.j1_pd_model.save()
        send_application_event_by_certain_pgood(self.j1_application, 190, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': 'x_190_pct80'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='x_190_pct80'
        )

        self.j1_pd_model.pgood = 0.9
        self.j1_pd_model.save()
        send_application_event_by_certain_pgood(self.j1_application, 190, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': 'x_190_pct90'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='x_190_pct90'
        )


class TestSendEventByCertainMyCroftPgood(TestCase):
    def setUp(self):
        self.j1_application = ApplicationJ1Factory()
        self.j1_application.customer.appsflyer_device_id = 'dasbdj123jksad'
        self.j1_application.customer.save()
        self.j1_pd_model = PdCreditModelResultFactory(
            application_id=self.j1_application.id, pgood=0.8
        )
        self.j1_pd_app_fraud_model = PdApplicationFraudModelResultFactory(
            application_id=self.j1_application.id, pgood=0.9
        )

    @patch('juloserver.julo.workflows2.tasks.appsflyer_update_status_task')
    @patch('juloserver.application_flow.services.send_event_to_ga_task_async')
    def test_send_event_at_105(
        self,
        mock_send_event_to_ga_task_async,
        mock_appsflyer_update_status_task,
    ):
        self.j1_application.application_status_id = 105
        self.j1_application.save()
        send_application_event_base_on_mycroft(self.j1_application, 105, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': '105_p80_mycroft90'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='105_p80_mycroft90'
        )

        self.j1_pd_model.pgood = 0.9
        self.j1_pd_model.save()
        send_application_event_base_on_mycroft(self.j1_application, 105, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': '105_p90_mycroft90'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='105_p90_mycroft90'
        )

    @patch('juloserver.julo.workflows2.tasks.appsflyer_update_status_task')
    @patch('juloserver.application_flow.services.send_event_to_ga_task_async')
    def test_send_event_at_190(
        self,
        mock_send_event_to_ga_task_async,
        mock_appsflyer_update_status_task,
    ):
        self.j1_application.application_status_id = 190
        self.j1_application.save()
        send_application_event_base_on_mycroft(self.j1_application, 190, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': '190_p80_mycroft90'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='190_p80_mycroft90'
        )

        self.j1_pd_model.pgood = 0.9
        self.j1_pd_model.save()
        send_application_event_base_on_mycroft(self.j1_application, 190, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': '190_p90_mycroft90'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='190_p90_mycroft90'
        )


class TelcoScoreTest(TestCase):
    def setUp(self) -> None:
        from django.conf import settings
        from juloserver.julo.product_lines import ProductLineCodes

        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        j1_product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(workflow=j1_workflow, product_line=j1_product_line)
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.TELCO_SCORE,
            parameters={
                "provider": {
                    "telkomsel": {
                        "is_active": True,
                        "prefixes": [
                            '0811',
                            '0812',
                            '0813',
                            '0821',
                            '0822',
                            '0823',
                            '0851',
                            '0852',
                            '0853',
                        ],
                        "swap_in_threshold": 750,
                    },
                    "indosat": {
                        "is_active": True,
                        "prefixes": [
                            '0814',
                            '0815',
                            '0816',
                            '0855',
                            '0856',
                            '0857',
                            '0858',
                        ],
                        "swap_in_threshold": 750,
                    },
                    "xl": {
                        "is_active": True,
                        "prefixes": [
                            '0877',
                            '0878',
                            '0817',
                            '0818',
                            '0819',
                        ],
                        "swap_in_threshold": 750,
                    },
                }
            },
        )
        self.private_key = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA2aKNdqA54p3HsAirZawfxnJ7JgWrnhxrinX6iSHXbPoxDc/J\n"
            "7fNy2+Sww6TKvjw4/nRBFFEALSQ6uqN/FDcQPjOjsLKybaBXcsbN7v9aK6EB9Dmo\n"
            "5vwKj4EFLhGAjEQ//MTjonFCoOz4WCDTM8n1EOLYk7b+b8CbfLPjSZ/cucAnOCcd\n"
            "AjBSurXPlwBn2qV7GII10on5P5VGY5QoFQc3ALbi+Rx0Nfa1k9uAmTuDxFgj6JOy\n"
            "f6M8/DKGA/EBOGbFBGTd2U6fTPQlz4o1BXtRr8v/ln97vvaqo5pP/kA9FY/UOBuI\n"
            "2f9HTX4qfTNK7mI/aFWrY7vS0S/yLDTeQvq0wwIDAQABAoIBAQCPuVnSzV1s2uXU\n"
            "yuTl8BXL6C6LnZMIh5w9hEw/46lwvolGpcKk8fEYZp6VlW6O0xaQdBXGZPfI1/Qw\n"
            "7Wgu4W5IpbGkL17GJu2ZTtEQ1HGn/lxb/PgeErSmsH3LPqO1/hyDwULTNBjcTaJ0\n"
            "ELlpqiW9URHV+zNsebY1VFb1eC08PQF/kfgXsYCKQShs3QrwEmGJ0lf3D8wzSEMg\n"
            "fv9+vCsxgkU9oHNCGuizKJoEIYbBCNvhIr0KlxiRA9rnhAC43xqmK6oMBtvNVkO6\n"
            "3ORvJY6HXVwrfFv8YQfsKOk/KvfbAaYA5xtTxw7neRwu3mz6duS9z/3ZMvA+XWcq\n"
            "ctzZfbcBAoGBAPhZY/be+KrxR+4LTi1ms879CHy+Np8UHKZMd5Pv4jawcJT1405W\n"
            "YUcaT6Iyl6tNoxzFf36L/FHOvHkbnnUdXuLvyqg//Tpga+Yv21R9IruB1VwlXgNe\n"
            "EPlnDsuREL/vdYIKmH+XHoUWFS4vVV3SlDaAghVOaaYVXgCH2/Iy6ly7AoGBAOBW\n"
            "7xxtW6oVUfJO//nUxrJIBxqY3qRxkp0Cj/HBzHRa++DMlSHiJlr9j5OPdL7NHYc4\n"
            "SU53deBvcjG/6vZ/unJ4IDe66N2owhEmKYi7A4T5LcrasrKf8eAZhf8IFeUHGXaZ\n"
            "UsrUUyl6FWWveOAvX0+rCjgNRaBgINcw7CNak8uZAoGATF1wV6EIZcf7jj77swo5\n"
            "kBROX809jnzoslohCuRgcuCePa++TYBSOULl6cIU0R/2YAp6wbbZx24CllrfxrNZ\n"
            "Uf7aGhJTE3hCtW1RzBEOdQnfSY5T8kUigw4lhoL824gOYgZQDiuxvsqjiKgVX9w4\n"
            "pumtFlAePGullBQyla8CUbECgYEAt113PZYJKWEZxONbiJmo+smyvMOcn26RNrKE\n"
            "c0dDVQuU+u5dKv/M9+xusV69PsMq0n5oNLGh8JtHDHDgnTBTdgLH2qV0dtDcJuY5\n"
            "Zp/tRX/iNP9CtovTSKe0BXtXYgbGglDaAh1ACBPYb2/Ybe1qixSzWpNGiMpprVo4\n"
            "eMEtMmkCgYAsmt4lK6FmZV8imlkXvgZz03I11Y7cVQ+tmjPNP6b/zRPnnZf6vpAw\n"
            "p2Zgici9ikQ8x+HB3S9b6YxnhULZAPpZJb1bfXgH1SDmEXsZ92+50zJrksXJwgCM\n"
            "k9NHMJHh6e2slIKbDMexCyYz0NYjusRWztYC7Tn7Ec82WKrDeviw6g==\n"
            "-----END RSA PRIVATE KEY-----\n"
        )

        settings.TS_TELCO_SCORING["TELKOMSEL"]["PRIVATE_KEY"] = self.private_key
        settings.TS_TELCO_SCORING["INDOSAT"]["PRIVATE_KEY"] = self.private_key
        settings.TS_TELCO_SCORING["XL"]["PRIVATE_KEY"] = self.private_key

        self.score_success_content = json.dumps(
            {
                "verdict": "success",
                "message": "credit insight is available",
                "2017-09-06T04:24:32Z": "",
                "data": {
                    "score": "JWxN2bDgqcN4Vw4OoSJJfz4kiPkOn2tOJkAb79fX9Y2wRAQ_NSw0FhPDJJcigDXn1wc22sIXD6fMTBrQ2z0soyhpI0vhsgDJo98juRWluaV4c2btmzjgtI7zewlXmURZMKw0ngAqktnLnX_nteIEfX_O8D61oMxYr5n5WHkCpN_AI5aPmmtr2xvzEz00XvgFB8rvQ23MlEt82dBh9cOqkTpIAoOYfZx2F0guQ6-2CypI9liNLQrnk7lYZ8owDnA4NenIsXpZ-mJmzUogVDNqpolsha1H-FpQacW3XRYRr-s5-sCyN___jXr9uUa6ZNI3tQ86KtxIXHM2bgrX5UZing==",
                    "request_id": 12,
                    "verify": "new",
                },
            }
        ).encode("utf-8")

        ApplicationTagFactory(application_tag=TelcoScore.TAG)
        self.tag_pass = ApplicationPathTagStatusFactory(
            application_tag=TelcoScore.TAG, status=TelcoScore.TAG_STATUS_PASS_SWAP_IN
        )
        self.tag_bad = ApplicationPathTagStatusFactory(
            application_tag=TelcoScore.TAG, status=TelcoScore.TAG_STATUS_BAD_SWAP_OUT
        )

    def test_run_when_application_null(self):
        telco = TelcoScore(application=None)
        self.assertIsNone(telco.run())

    def test_run_when_setting_inactive(self):
        self.setting.is_active = False
        self.setting.save()

        telco = TelcoScore(application=self.application)
        self.assertIsNone(telco.run())

    def test_run_when_setting_null(self):
        self.setting.feature_name = "just-random-name"
        self.setting.save()

        telco = TelcoScore(application=self.application)
        self.assertIsNone(telco.run())

    @patch.object(Telkomsel, "call_score_endpoint")
    def test_run_for_telkomsel_628(self, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "6281100123456"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        self.assertIsNotNone(telco.run())

    @patch.object(Telkomsel, "call_score_endpoint")
    def test_run_for_telkomsel_08(self, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "081100123456"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        self.assertIsNotNone(telco.run())

    @patch.object(Telkomsel, "call_score_endpoint")
    def test_run_for_telkomsel_plus628(self, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "+6281100123456"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        self.assertIsNotNone(telco.run())

    @patch.object(Indosat, "call_score_endpoint")
    def test_run_for_indosat_628(self, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "6285500123456"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        self.assertIsNotNone(telco.run())

    @patch.object(Indosat, "call_score_endpoint")
    def test_run_for_indosat_08(self, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "085500123456"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        self.assertIsNotNone(telco.run())

    @patch.object(Indosat, "call_score_endpoint")
    def test_run_for_indosat_plus628(self, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "+6285500123456"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        self.assertIsNotNone(telco.run())

    @patch.object(XL, "call_score_endpoint")
    def test_run_for_xl_628(self, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "628179186373"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        self.assertIsNotNone(telco.run())

    @patch.object(XL, "call_score_endpoint")
    def test_run_for_xl_08(self, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "08179186373"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        self.assertIsNotNone(telco.run())

    @patch.object(XL, "call_score_endpoint")
    def test_run_for_xl_plus628(self, mock_call_score_endpoint):
        self.application.mobile_phone_1 = "+628179186373"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        self.assertIsNotNone(telco.run())

    @patch.object(XL, "call_score_endpoint")
    def test_operator_setting_disabled(self, mock_call_score_endpoint):
        parameters = self.setting.parameters
        parameters["provider"]["xl"]["is_active"] = False

        self.setting.parameters = parameters
        self.setting.save()

        self.application.mobile_phone_1 = "+628179186373"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        self.assertIsNone(telco.run())

    @patch.object(XL, "call_score_endpoint")
    @patch.object(TelcoScore, "_is_bad_in_130", return_value=True)
    @patch.object(TelcoScore, "skip_execution_in_130", return_value=False)
    def test_run_swap_out_xl(
        self, mock_skip_execution_in_130, mock_is_bad_in_130, mock_call_score_endpoint
    ):
        status_130 = StatusLookupFactory(status_code=130)
        self.application.application_status = status_130
        self.application.mobile_phone_1 = "+628179186373"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        telco.run_in_130_swapout()

        # telco scoring result
        # result = TelcoScoringResult.objects.filter(application_id=self.application.id).last()
        # self.assertIsNotNone(result)
        # self.assertEqual(result.type, "swap_out")

        tag = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=self.tag_bad
        ).last()
        self.assertIsNotNone(tag)

    @patch.object(XL, "call_score_endpoint")
    def test_run_swap_out_xl_skip_for_setting_disabled(self, mock_call_score_endpoint):
        self.setting.is_active = False
        self.setting.save()

        status_130 = StatusLookupFactory(status_code=130)
        self.application.application_status = status_130
        self.application.mobile_phone_1 = "+628179186373"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        telco.run_in_130_swapout()

        # telco scoring result
        result = TelcoScoringResult.objects.filter(application_id=self.application.id).last()
        self.assertIsNone(result)

        tag = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=self.tag_bad
        ).last()
        self.assertIsNone(tag)

    @patch.object(XL, "call_score_endpoint")
    def test_run_swap_out_xl_skip_for_pass_swap_in(self, mock_call_score_endpoint):
        ApplicationPathTagFactory(
            application_id=self.application.id, application_path_tag_status=self.tag_pass
        )

        status_130 = StatusLookupFactory(status_code=130)
        self.application.application_status = status_130
        self.application.mobile_phone_1 = "+628179186373"
        self.application.save()

        response = Response()
        response.status_code = 200
        response._content = self.score_success_content
        mock_call_score_endpoint.return_value = response

        telco = TelcoScore(application=self.application)
        telco.run_in_130_swapout()

        # telco scoring result
        result = TelcoScoringResult.objects.filter(application_id=self.application.id).last()
        self.assertIsNone(result)

        tag = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=self.tag_bad
        ).last()
        self.assertIsNone(tag)


class TestSendEventForX100DeviceInfo(TestCase):
    def setUp(self):
        self.j1_application = ApplicationJ1Factory()
        self.j1_application.customer.appsflyer_device_id = 'dasbdj123jksad'
        self.j1_application.customer.save()

    @patch('juloserver.julo.workflows2.tasks.appsflyer_update_status_task')
    @patch('juloserver.application_flow.services.send_event_to_ga_task_async')
    def test_send_event(
        self,
        mock_send_event_to_ga_task_async,
        mock_appsflyer_update_status_task,
    ):
        SdDevicePhoneDetail.objects.create(
            customer_id=self.j1_application.customer_id,
            application_id=self.j1_application.id,
            product='123',
            user='123',
            device='123',
            osapilevel='123',
            version='123',
            manufacturer='samsung',
            serial='123',
            device_type='123',
            model='123',
            phone_device_id='123',
            sdk='123',
            brand='123',
            display='123',
            device_id=123,
            repeat_number='123',
        )
        send_application_event_for_x100_device_info(self.j1_application, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': 'x_100_device'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='x_100_device'
        )


class TestSendEventForX105Bankname(TestCase):
    def setUp(self):
        self.j1_application = ApplicationJ1Factory()
        self.j1_application.customer.appsflyer_device_id = 'dasbdj123jksad'
        self.j1_application.customer.save()

    @patch('juloserver.julo.workflows2.tasks.appsflyer_update_status_task')
    @patch('juloserver.application_flow.services.send_event_to_ga_task_async')
    def test_send_event_success(
        self,
        mock_send_event_to_ga_task_async,
        mock_appsflyer_update_status_task,
    ):
        self.j1_application.bank_name = 'BANK MANDIRI (PERSERO), Tbk'
        self.j1_application.save()
        send_application_event_for_x105_bank_name_info(self.j1_application, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_called_with(
            kwargs={'customer_id': self.j1_application.customer.id, 'event': 'x_105_bank'}
        )
        mock_appsflyer_update_status_task.delay.assert_called_with(
            self.j1_application.id, event_name='x_105_bank'
        )

    @patch('juloserver.julo.workflows2.tasks.appsflyer_update_status_task')
    @patch('juloserver.application_flow.services.send_event_to_ga_task_async')
    def test_send_event_failed(
        self,
        mock_send_event_to_ga_task_async,
        mock_appsflyer_update_status_task,
    ):
        self.j1_application.bank_name = None
        self.j1_application.save()
        send_application_event_for_x105_bank_name_info(self.j1_application, 'appsflyer_and_ga')
        mock_send_event_to_ga_task_async.apply_async.assert_not_called()
        mock_appsflyer_update_status_task.delay.assert_not_called()


class TestBlockedBankAccountNumberX105(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.bank_name = 'BANK RAKYAT INDONESIA (PERSERO), Tbk (BRI)'
        self.application.save()

        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=133,
            workflow=self.julo_one_workflow,
            is_active=True,
        )
        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            workflow=self.julo_one_workflow,
            is_active=True,
        )
        self.julo_turbo_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )
        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=133,
            workflow=self.julo_turbo_workflow,
            is_active=True,
        )
        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            workflow=self.julo_turbo_workflow,
            is_active=True,
        )

        BankFactory(
            bank_code='002', is_active=True, bank_name='BANK RAKYAT INDONESIA (PERSERO), Tbk (BRI)'
        )

    @patch('juloserver.julo.services.process_application_status_change')
    def test_blocked_bank_account_number_j1(self, mock_process_application_status_change):
        self.application.workflow = self.julo_one_workflow
        self.application.bank_account_number = (
            '1004510821918171'  # Example number that should trigger the block
        )
        self.application.bank_name = 'BANK RAKYAT INDONESIA (PERSERO), Tbk (BRI)'
        self.application.save()

        handler = JuloOne105Handler(
            application=self.application,
            new_status_code=ApplicationStatusCodes.FORM_PARTIAL,
            change_reason='move',
            note='',
            old_status_code=100,
        )

        handler.post()

        # Check if check_fraud_bank_account_number returned True
        self.assertTrue(handler.action.check_fraud_bank_account_number())
        mock_process_application_status_change.assert_called_with(
            self.application.id,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            'fraud attempt: BRI digital bank',
        )

    @patch('juloserver.julo.services.process_application_status_change')
    def test_blocked_bank_account_number_turbo(self, mock_process_application_status_change):
        self.application.workflow = self.julo_turbo_workflow
        self.application.bank_account_number = (
            '1004510821918171'  # Example number that should trigger the block
        )
        self.application.save()

        handler = JuloOne105Handler(
            application=self.application,
            new_status_code=ApplicationStatusCodes.FORM_PARTIAL,
            change_reason='move',
            note='',
            old_status_code=100,
        )

        handler.post()

        # Check if check_fraud_bank_account_number returned True
        self.assertTrue(handler.action.check_fraud_bank_account_number())
        mock_process_application_status_change.assert_called_with(
            self.application.id,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            'fraud attempt: BRI digital bank',
        )

    @patch('juloserver.julo.services.process_application_status_change')
    def test_blocked_bank_account_number_different_bank(
        self, mock_process_application_status_change
    ):
        BankFactory(bank_code='003', is_active=True, bank_name='BANK APAJADEH')

        self.application.workflow = self.julo_turbo_workflow
        self.application.bank_account_number = (
            '1004510821918171'  # Example number that should trigger the block
        )
        self.application.bank_name = 'BANK APAJADEH'
        self.application.save()

        handler = JuloOne105Handler(
            application=self.application,
            new_status_code=ApplicationStatusCodes.FORM_PARTIAL,
            change_reason='move',
            note='',
            old_status_code=100,
        )

        handler.post()

        # Check if check_fraud_bank_account_number returned False
        self.assertFalse(handler.action.check_fraud_bank_account_number())


class TestSelfCorrectionTypo(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.token = self.user.auth_expiry_token.key
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer, dob=date(1996, 10, 3))

    @pytest.mark.skip(reason="Working on local but not in jenkins")
    def test_get_application_information(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token}')
        response = self.client.get(
            f'/api/application_flow/v1/applications/{self.application.id}/self-correction'
        )
        self.assertEqual(response.status_code, 200)
        json_response = response.json()
        self.assertTrue(json_response["success"])
        self.assertEqual(json_response["data"]["fullname"], self.application.fullname)
        self.assertEqual(json_response["data"]["ktp"], self.application.ktp)
        self.assertEqual(json_response["data"]["dob"], '03 Oktober 1996')
        print(json_response["data"]["dob"])
        self.assertEqual(json_response["data"]["birth_place"], self.application.birth_place)

    def test_get_application_not_exist(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token}')
        response = self.client.get(
            '/api/application_flow/v1/applications/12344431212/self-correction'
        )
        self.assertEqual(response.status_code, 404)
        json_response = response.json()
        self.assertFalse(json_response["success"])
        self.assertEqual(json_response["errors"][0], "Not found.")

    def test_get_application_without_auth(self):

        response = self.client.get(
            f'/api/application_flow/v1/applications/{self.application.id}/self-correction'
        )
        self.assertEqual(response.status_code, 401)
        json_response = response.json()
        self.assertFalse(json_response["success"])
        self.assertEqual(
            json_response["errors"][0], "Authentication credentials were not provided."
        )

    def test_get_application_with_other_user(self):
        user = AuthUserFactory()
        token = user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
        response = self.client.get(
            f'/api/application_flow/v1/applications/{self.application.id}/self-correction'
        )
        self.assertEqual(response.status_code, 403)
        json_response = response.json()
        self.assertFalse(json_response["success"])
        self.assertEqual(
            json_response["errors"][0], "You are not permitted to access this application."
        )

    @pytest.mark.skip(reason="Working on local but not in jenkins")
    @patch('juloserver.application_flow.views.process_application_status_change')
    def test_send_acknowledgement(self, mock_status_change):
        self.application.application_status = StatusLookupFactory(status_code=127)
        self.application.save()

        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token}')
        response = self.client.patch(
            f'/api/application_flow/v1/applications/{self.application.id}/self-correction'
        )
        self.assertEqual(response.status_code, 200)
        json_response = response.json()
        self.assertTrue(json_response["success"])
        self.assertEqual(json_response["data"]["fullname"], self.application.fullname)
        self.assertEqual(json_response["data"]["ktp"], self.application.ktp)
        self.assertEqual(json_response["data"]["dob"], '03 Oktober 1996')
        print(json_response["data"]["dob"])
        self.assertEqual(json_response["data"]["birth_place"], self.application.birth_place)

    def test_send_acknowledgement_from_non_127(self):
        self.application.application_status = StatusLookupFactory(status_code=105)
        self.application.save()

        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token}')
        response = self.client.patch(
            f'/api/application_flow/v1/applications/{self.application.id}/self-correction'
        )
        self.assertEqual(response.status_code, 400)
        json_response = response.json()
        self.assertFalse(json_response["success"])
        self.assertEqual(json_response["errors"][0], "Application status not permitted.")

    def test_send_acknowledgement_application_not_exists(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token}')
        response = self.client.patch(
            f'/api/application_flow/v1/applications/9428158934843/self-correction'
        )
        self.assertEqual(response.status_code, 404)
        json_response = response.json()
        self.assertFalse(json_response["success"])
        self.assertEqual(json_response["errors"][0], "Not found.")

    def test_send_acknowledgement_without_auth(self):
        response = self.client.patch(
            f'/api/application_flow/v1/applications/{self.application.id}/self-correction'
        )
        self.assertEqual(response.status_code, 401)
        json_response = response.json()
        self.assertFalse(json_response["success"])
        self.assertEqual(
            json_response["errors"][0], "Authentication credentials were not provided."
        )


class TestClikModelTask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer, dob=date(1996, 10, 3))
        self.tag_name = 'is_clik_model'
        self.path_tag_status = ApplicationPathTagStatusFactory(
            application_tag=self.tag_name, status=1, definition="success"
        )
        self.mock_clik_response = {
            "data": {
                "enquiry_type": 'nae',
                "json_data": {
                    "Body": {
                        "MGResult": {
                            "ProductResponse": {
                                "CB_ME_ProductOutput": {
                                    'CB_NAE_ProductOutput'
                                    "CBScore": {
                                        "CBSGlocal": {
                                            "ScoreData": {
                                                "ScoreRaw": 700,
                                                "ScoreRange": "600-800",
                                                "ScoreMessage": {"Description": "Good score"},
                                            }
                                        }
                                    },
                                    "CreditReport": {
                                        "ContractsHistory": {
                                            "AggregatedData": {
                                                "TotalOverdue": 500,
                                                "ReportingProvidersNumber": 3,
                                            }
                                        }
                                    },
                                },
                                "CB_NAE_ProductOutput": {
                                    "CBScore": {
                                        "CBSGlocal": {
                                            "ScoreData": {
                                                "ScoreRaw": 650,
                                                "ScoreRange": "600-800",
                                                "ScoreMessage": {"Description": "Fair score"},
                                            }
                                        }
                                    },
                                    "CreditReport": {
                                        "ContractsHistory": {
                                            "AggregatedData": {
                                                "TotalOverdue": 200,
                                                "ReportingProvidersNumber": 2,
                                            }
                                        }
                                    },
                                },
                            }
                        }
                    }
                },
            },
            "error": None,
        }

    @patch('juloserver.application_flow.services2.clik.CLIKClient.post')
    @patch('juloserver.julo.utils.post_anaserver')
    def test_process_clik_model_task(self, mock_clik_post, mock_post_anaserver):
        mock_response = MagicMock()
        mock_response.json.return_value = self.mock_clik_response
        mock_response.status_code = 200
        mock_clik_post.return_value = mock_response

        process_clik_model(self.application.id)
        self.assertIsNotNone(
            ApplicationPathTag.objects.filter(
                application_id=self.application.id,
                application_path_tag_status=self.path_tag_status.id,
            )
        )

        mock_post_anaserver.assert_called_once()


class TestEmulatorCheckIOSView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory()
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.application.customer = CustomerFactory(user=self.user)
        self.application.save()
        self.maxDiff = None

    @patch('juloserver.application_flow.views.EmulatorCheckIOS.objects.create')
    def test_success(self, mock_create):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        request_body = {
            "is_emulator": True,
            "brand": "iPhone",
            "os_name": "iOS",
            "os_version": "18.4.1",
            "cpu_arch": "iPhone11,6",
            "model": "iPhone XS Max"
        }

        expected_response = {
            "success": True,
            "data": "data stored successfully",
            "errors": []
        }
        response = self.client.post('/api/application_flow/v2/emulator-check-ios/'+str(self.application.id), request_body)
        mock_create.return_value = MagicMock()
        mock_create.assert_called_once_with(
            application_id=str(self.application.id), is_emulator=True, brand='iPhone', os_name='iOS', os_version='18.4.1', cpu_arch='iPhone11,6', model='iPhone XS Max'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_response)

    @patch('juloserver.application_flow.views.EmulatorCheckIOS.objects.create')
    def test_failed_invalid_request(self, mock_create):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        request_body = {
            "is_emulator": "trues"
        }

        expected_response = {
            "success": False,
            "data": None,
            "errors": [
                {
                    "is_emulator": [
                        "\"trues\" is not a valid boolean."
                    ]
                }
            ]
        }
        response = self.client.post('/api/application_flow/v2/emulator-check-ios/'+str(self.application.id), request_body)
        mock_create.assert_not_called()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), expected_response)

    @patch('juloserver.application_flow.views.EmulatorCheckIOS.objects.create')
    def test_failed_invalid_application(self, mock_create):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        request_body = {
            "is_emulator": True
        }

        expected_response = {
            "success": False,
            "data": None,
            "errors": ["Invalid Application ID"]
        }
        response = self.client.post('/api/application_flow/v2/emulator-check-ios/'+'123', request_body)
        mock_create.assert_not_called()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), expected_response)


class TestHSFBPIncomeVerification(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            id=1,
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application_other = ApplicationFactory(
            id=9,
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.experiment = ExperimentSettingFactory(
            code=ExperimentConst.HSFBP_INCOME_VERIFICATION,
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
            criteria={
                HSFBPIncomeConst.KEY_LAST_DIGIT_APP_ID: [0, 1],
                HSFBPIncomeConst.KEY_EXPIRATION_DAY: 2,
                HSFBPIncomeConst.KEY_ANDROID_APP_VERSION: '>=8.49.0',
            },
        )

    def test_application_get_eligible_hsfbp(self):

        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            app_version='8.49.0',
        )

        is_eligble = JuloOneByPass().is_hsfbp_income_verification(
            self.application,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        )
        # result will False experimenet is not active
        self.assertFalse(is_eligble)

        self.experiment.update_safely(is_active=True)

        is_eligble = JuloOneByPass().is_hsfbp_income_verification(
            self.application,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        )
        self.assertTrue(is_eligble)

    def test_application_is_not_eligible_hsfbp(self):
        self.application_other.update_safely(
            application_status_id=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            app_version='8.49.0',
        )
        self.experiment.update_safely(is_active=True)

        is_eligble = JuloOneByPass().is_hsfbp_income_verification(
            self.application_other,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        )
        # result will False, application last digit is 9
        self.assertFalse(is_eligble)
