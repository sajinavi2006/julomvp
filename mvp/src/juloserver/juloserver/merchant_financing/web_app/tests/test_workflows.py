from django.test import TestCase

from juloserver.account.tests.factories import AccountLookupFactory
from juloserver.face_recognition.constants import ImageType
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import Application
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    StatusLookupFactory,
    PartnerFactory,
    WorkflowFactory,
    PartnershipCustomerDataFactory,
    CustomerFactory,
    PartnershipApplicationDataFactory,
    ImageFactory,
    PartnershipFeatureSettingFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory, WorkflowStatusNodeFactory
from juloserver.merchant_financing.web_app.workflows import PartnershipMfWebAppWorkflowAction
from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.personal_data_verification.tests.factories import (
    DukcapilFaceRecognitionCheckFactory,
)


class TestPartnershipMfWebAppWorkflowAction(TestCase):
    def setUp(self):
        self.partner = PartnerFactory(name='agrari')
        StatusLookupFactory(status_code=135)
        StatusLookupFactory(status_code=133)
        self.status_130_lookup = StatusLookupFactory(status_code=130)
        self.status_141_lookup = StatusLookupFactory(status_code=141)
        self.status_190_lookup = StatusLookupFactory(status_code=190)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW,
            is_active=True,
            handler="PartnershipMfWebAppWorkflowHandler",
        )

        WorkflowStatusNodeFactory(
            workflow=self.workflow, status_node=141, handler='PartnershipMF141Handler'
        )
        WorkflowStatusNodeFactory(
            workflow=self.workflow, status_node=190, handler='PartnershipMF190Handler'
        )
        WorkflowStatusNodeFactory(
            workflow=self.workflow, status_node=135, handler='PartnershipMF135Handler'
        )
        WorkflowStatusNodeFactory(
            workflow=self.workflow, status_node=133, handler='PartnershipMF133Handler'
        )

        WorkflowStatusPathFactory(
            workflow=self.workflow,
            status_previous=130,
            status_next=141,
        )
        WorkflowStatusPathFactory(
            workflow=self.workflow,
            status_previous=141,
            status_next=190,
        )
        WorkflowStatusPathFactory(
            workflow=self.workflow,
            status_previous=141,
            status_next=133,
        )
        AccountLookupFactory(
            workflow=self.workflow,
            partner=self.partner,
        )

    def test_generate_mf_partnership_credit_limit(self):
        customer = CustomerFactory()
        application = ApplicationFactory(
            application_status=self.status_130_lookup,
            customer=customer,
            partner=self.partner,
            workflow=self.workflow,
        )
        application.application_status_id = 130
        application.save()
        partnership_customer_data = PartnershipCustomerDataFactory(
            application=application,
            customer=customer,
            partner=self.partner,
        )
        PartnershipApplicationDataFactory(
            application=application,
            partnership_customer_data=partnership_customer_data,
            proposed_limit=100000,
        )
        workflow_action = PartnershipMfWebAppWorkflowAction(
            application=application,
            new_status_code=130,
            old_status_code=121,
            change_reason='test',
            note='test',
        )
        workflow_action.generate_mf_partnership_credit_limit()
        application.refresh_from_db()
        self.assertEqual(application.application_status_id, 141)

    def test_success_dukcapil_fr_mf(self):
        application = ApplicationFactory(
            ktp='1231232103901000',
            application_status=self.status_141_lookup,
            partner=self.partner,
            workflow=self.workflow,
        )
        application.application_status_id = 141
        application.save()
        DukcapilFaceRecognitionCheckFactory(
            response_score=6, application_id=application.id, response_code='6018'
        )
        PartnershipFeatureSettingFactory(
            feature_name=PartnershipFeatureNameConst.DUKCAPIL_FR_THRESHOLD_MFSP,
            parameters={self.partner.name: {"is_active": True, "very_high": 9.5, "high": 5}},
        )
        ImageFactory(
            image_source=application.id,
            image_type=ImageType.SELFIE,
        )

        workflow_action = PartnershipMfWebAppWorkflowAction(
            application=application,
            new_status_code=141,
            old_status_code=130,
            change_reason='test',
            note='test',
        )
        workflow_action.dukcapil_fr_mf()
        application.refresh_from_db()
        self.assertEqual(application.application_status_id, 190)

    def test_success_dukcapil_fr_mf_with_no_feature_setting(self):
        customer = CustomerFactory()
        application = ApplicationFactory(
            ktp='1231232103901000',
            application_status=self.status_141_lookup,
            partner=self.partner,
            workflow=self.workflow,
        )
        application.application_status_id = 141
        application.save()
        partnership_customer_data = PartnershipCustomerDataFactory(
            application=application,
            customer=customer,
            partner=self.partner,
        )
        PartnershipApplicationDataFactory(
            application=application,
            partnership_customer_data=partnership_customer_data,
            proposed_limit=100000,
        )

        workflow_action = PartnershipMfWebAppWorkflowAction(
            application=application,
            new_status_code=141,
            old_status_code=130,
            change_reason='test',
            note='test',
        )
        workflow_action.dukcapil_fr_mf()
        application.refresh_from_db()
        self.assertEqual(application.application_status_id, 190)

    def test_success_dukcapil_fr_mf_with_no_dukcapil_fr_data(self):
        application = ApplicationFactory(
            ktp='1231232103901000',
            application_status=self.status_141_lookup,
            partner=self.partner,
            workflow=self.workflow,
        )
        application.application_status_id = 141
        application.save()
        PartnershipFeatureSettingFactory(
            feature_name=PartnershipFeatureNameConst.DUKCAPIL_FR_THRESHOLD_MFSP,
            parameters={self.partner.name: {"is_active": True, "very_high": 9.5, "high": 5}},
        )

        workflow_action = PartnershipMfWebAppWorkflowAction(
            application=application,
            new_status_code=141,
            old_status_code=130,
            change_reason='test',
            note='test',
        )
        workflow_action.dukcapil_fr_mf()
        application.refresh_from_db()
        self.assertEqual(application.application_status_id, 190)

    def test_success_dukcapil_fr_mf_0_score(self):
        application = ApplicationFactory(
            ktp='1231232103901000',
            application_status=self.status_141_lookup,
            partner=self.partner,
            workflow=self.workflow,
        )
        application.application_status_id = 141
        application.save()
        DukcapilFaceRecognitionCheckFactory(
            response_score=0, application_id=application.id, response_code='6018'
        )
        PartnershipFeatureSettingFactory(
            feature_name=PartnershipFeatureNameConst.DUKCAPIL_FR_THRESHOLD_MFSP,
            parameters={self.partner.name: {"is_active": True, "very_high": 9.5, "high": 5}},
        )
        ImageFactory(
            image_source=application.id,
            image_type=ImageType.SELFIE,
        )

        workflow_action = PartnershipMfWebAppWorkflowAction(
            application=application,
            new_status_code=141,
            old_status_code=130,
            change_reason='test',
            note='test',
        )
        workflow_action.dukcapil_fr_mf()
        application.refresh_from_db()
        self.assertEqual(application.application_status_id, 190)

    def test_failed_dukcapil_fr_mf_low_score(self):
        application = ApplicationFactory(
            ktp='1231232103901000',
            application_status=self.status_141_lookup,
            partner=self.partner,
            workflow=self.workflow,
        )
        application.application_status_id = 141
        application.save()
        DukcapilFaceRecognitionCheckFactory(
            response_score=4, application_id=application.id, response_code='6018'
        )
        PartnershipFeatureSettingFactory(
            feature_name=PartnershipFeatureNameConst.DUKCAPIL_FR_THRESHOLD_MFSP,
            parameters={self.partner.name: {"is_active": True, "very_high": 9.5, "high": 5}},
        )
        ImageFactory(
            image_source=application.id,
            image_type=ImageType.SELFIE,
        )

        workflow_action = PartnershipMfWebAppWorkflowAction(
            application=application,
            new_status_code=141,
            old_status_code=130,
            change_reason='test',
            note='test',
        )
        workflow_action.dukcapil_fr_mf()
        application.refresh_from_db()
        self.assertEqual(application.application_status_id, 133)

    def test_failed_dukcapil_fr_mf_high_score(self):
        application = ApplicationFactory(
            ktp='1231232103901000',
            application_status=self.status_141_lookup,
            partner=self.partner,
            workflow=self.workflow,
        )
        application.application_status_id = 141
        application.save()
        DukcapilFaceRecognitionCheckFactory(
            response_score=10, application_id=application.id, response_code='6018'
        )
        PartnershipFeatureSettingFactory(
            feature_name=PartnershipFeatureNameConst.DUKCAPIL_FR_THRESHOLD_MFSP,
            parameters={self.partner.name: {"is_active": True, "very_high": 9.5, "high": 5}},
        )
        ImageFactory(
            image_source=application.id,
            image_type=ImageType.SELFIE,
        )

        workflow_action = PartnershipMfWebAppWorkflowAction(
            application=application,
            new_status_code=141,
            old_status_code=130,
            change_reason='test',
            note='test',
        )
        workflow_action.dukcapil_fr_mf()
        application.refresh_from_db()
        self.assertEqual(application.application_status_id, 133)

    def test_failed_nik_not_found(self):
        application = ApplicationFactory(
            ktp='1231232103901000',
            application_status=self.status_141_lookup,
            partner=self.partner,
            workflow=self.workflow,
        )
        application.application_status_id = 141
        application.save()
        DukcapilFaceRecognitionCheckFactory(
            response_score=10, application_id=application.id, response_code='6020'
        )
        PartnershipFeatureSettingFactory(
            feature_name=PartnershipFeatureNameConst.DUKCAPIL_FR_THRESHOLD_MFSP,
            parameters={self.partner.name: {"is_active": True, "very_high": 9.5, "high": 5}},
        )
        ImageFactory(
            image_source=application.id,
            image_type=ImageType.SELFIE,
        )

        workflow_action = PartnershipMfWebAppWorkflowAction(
            application=application,
            new_status_code=141,
            old_status_code=130,
            change_reason='test',
            note='test',
        )
        workflow_action.dukcapil_fr_mf()
        application.refresh_from_db()
        self.assertEqual(application.application_status_id, 133)
