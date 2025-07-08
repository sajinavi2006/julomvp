import csv
import io
import json

import mock
from django.core.urlresolvers import reverse
from django.http import StreamingHttpResponse
from django.test.testcases import TestCase
from io import StringIO

from mock.mock import (
    PropertyMock,
    patch,
)

from juloserver.account.models import ExperimentGroup
from django.core.files.uploadedfile import InMemoryUploadedFile
from juloserver.customer_module.tests.factories import AccountDeletionRequestFactory
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from django.utils import timezone
from datetime import timedelta, datetime
from dateutil.relativedelta import relativedelta
from django.conf import settings

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AddressFactory,
    AccountLimitFactory,
    AccountPropertyFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.application_flow.services import JuloOneService
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.grab.clients.paths import GrabPaths
from juloserver.grab.models import GrabCustomerData
from juloserver.grab.tests.factories import GrabAPILogFactory, GrabCustomerDataFactory, GrabLoanDataFactory
from juloserver.julo.clients.infobip import JuloInfobipClient
from juloserver.julo.constants import (
    VendorConst,
    WorkflowConst,
    FeatureNameConst,
    OnboardingIdConst,
    IdentifierKeyHeaderAPI,
    ExperimentConst,
)
from juloserver.julo.models import SmsHistory, Application
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    PaymentStatusCodes,
    CreditCardCodes,
    LoanStatusCodes,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CommsProviderLookupFactory,
    CustomerFactory,
    DocumentFactory,
    ApplicationFactory,
    ImageFactory,
    CreditScoreFactory,
    PartnerFactory,
    PaymentFactory,
    SmsHistoryFactory,
    WorkflowFactory,
    ApplicationHistoryFactory,
    StatusLookupFactory,
    LoanFactory,
    CommsBlockedFactory,
    CommsBlocked,
    FeatureSettingFactory,
    ExperimentSettingFactory,
    ExperimentFactory,
    ExperimentTestGroupFactory,
    ApplicationExperimentFactory,
    JobTypeFactory,
    ApplicationJ1Factory,
    ProductLineFactory,
    ReferralSystemFactory,
    MasterAgreementTemplateFactory,
    MobileFeatureSettingFactory,
    AffordabilityHistoryFactory,
    ProductLookupFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    MobileFeatureSettingFactory,
    ApplicationUpgradeFactory,
    FDCInquiryFactory,
    FDCInquiryLoanFactory,
    ExperimentSettingFactory,
    OnboardingFactory,
    GroupFactory,
    AgentAssistedWebTokenFactory,
)
from juloserver.julo.models import Loan

from django.contrib.auth.models import Group

from juloserver.julo_financing.tests.factories import JFinancingProductFactory
from juloserver.promo.tests.factories import PromoEntryPageFeatureSetting
from juloserver.streamlined_communication.constant import (
    CardProperty,
    CommunicationPlatform,
    PageType,
    TemplateCode,
    J1_PRODUCT_DEEP_LINK_MAPPING_TRANSACTION_METHOD,
    NeoBannerConst,
    NeoBannerStatusesConst,
    CommsUserSegmentConstants,
)
from juloserver.streamlined_communication.exceptions import (
    ApplicationNotFoundException,
    MissionEnableStateInvalid,
)
from juloserver.streamlined_communication.models import (
    InfoCardButtonProperty,
    StreamlinedCommunication,
    StreamlinedCommunicationCampaign,
    CommsCampaignSmsHistory,
)
from juloserver.streamlined_communication.test.factories import (
    InfoCardPropertyFactory,
    ButtonInfoCardFactory,
    StreamlinedMessageFactory,
    StreamlinedCommunicationFactory,
    NeoBannerCardFactory,
    StreamlinedCommunicationSegmentFactory,
    StreamlinedCampaignDepartmentFactory,
    StreamlinedCommunicationCampaignFactory,
    StreamlinedCampaignSquadFactory,
    CommsCampaignSmsHistoryFactory,
    CommsUserSegmentChunkFactory,
)
from juloserver.account.constants import AccountConstant

from juloserver.credit_card.constants import FeatureNameConst as JuloCardFeatureNameConst
from juloserver.credit_card.tests.factiories import JuloCardWhitelistUserFactory
from juloserver.credit_card.tests.test_views.test_view_api_v1 import (
    create_mock_credit_card_application,
)
from juloserver.loan.tests.factories import (
    TransactionMethodFactory,
    TransactionCategoryFactory,
)
from juloserver.loan.constants import LoanJuloOneConstant, LoanFeatureNameConst

from juloserver.payment_point.constants import TransactionMethodCode
from http import HTTPStatus

from juloserver.streamlined_communication.models import InfoCardProperty
from juloserver.julo.tests.factories import IdfyVideoCallFactory
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.cfs.tests.factories import (
    CfsTierFactory,
    CfsActionFactory,
    CfsActionAssignmentFactory,
    CfsAssignmentVerificationFactory,
)
from juloserver.cfs.constants import CfsProgressStatus
from juloserver.application_form.constants import LabelFieldsIDFyConst
from juloserver.julo.constants import FeatureNameConst
from juloserver.streamlined_communication.services import determine_main_application_infocard
from juloserver.ana_api.tests.factories import EligibleCheckFactory
from juloserver.application_flow.constants import AgentAssistedSubmissionConst
from juloserver.application_form.constants import (
    AgentAssistedSubmissionConst as AgentAssistedSubmissionConstForm,
)
from juloserver.application_form.utils import generate_web_token
from juloserver.julo.utils import get_oss_public_url


from juloserver.streamlined_communication.constant import StreamlinedCommCampaignConstants
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.new_crm.services import streamlined_services
from collections import OrderedDict
from juloserver.new_crm.tests.factories import ApplicationPathTagFactory
from juloserver.application_flow.factories import ApplicationPathTagStatusFactory

PACKAGE_NAME = 'juloserver.streamlined_communication.views'


class TestViewsInfoCard(TestCase):
    def setUp(self):
        group = Group(name="product_manager")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.info_card = InfoCardPropertyFactory()
        self.button = ButtonInfoCardFactory(id=999, info_card_property=self.info_card)
        self.image_button = ImageFactory(
            image_source=self.button.id,
            image_type=CardProperty.IMAGE_TYPE.button_background_image)
        self.image_background = ImageFactory(
            image_source=self.info_card.id,
            image_type=CardProperty.IMAGE_TYPE.card_background_image)
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.LOC_APPROVED,
            extra_conditions=CardProperty.MSG_TO_STAY_UNTIL_1ST_TRANSACTION
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name='master_agreement_setting',
        )

    def test_access_streamlined_for_extra_condition(self):
        response = self.client.get(
            '/streamlined_communication/list/',
            {"status_ptp": -1}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(
            '/streamlined_communication/list/',
            {
                "extra_condition": CardProperty.MSG_TO_STAY_UNTIL_1ST_TRANSACTION,
                "application_status": ApplicationStatusCodes.LOC_APPROVED
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_access_get_info_card_property(self):
        response = self.client.get(
            '/streamlined_communication/get_info_card_property/',
            {"streamlined_communication_id": self.streamlined_communication.id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = response.json()['data']
        self.assertEqual(response['status'], 'Success')

    @mock.patch('juloserver.streamlined_communication.views.InfoCardSerializer.is_valid')
    @mock.patch('juloserver.streamlined_communication.views.create_and_upload_image_assets_for_streamlined')
    def test_create_new_info_card(self, mocked_ser, mocked_upload_image_assets):
        image = (io.BytesIO(b"test"), 'test.png')
        data = {
            'info_card_template_code': 'info_card_unit_test_code',
            'info_card_type': '1',
            'info_card_product' : 'J1',
            'info_card_title': 'title unit test',
            'title_text_color': '#FFFFFF',
            'info_card_content': 'unit test info card content',
            'content_parameters': 'unit_test_param_1,unit_test_param_2',
            'body_text_color': '#FFFFFF',
            'dpd': '',
            'dpd_lower': '',
            'dpd_upper': '',
            'until_paid': '',
            'ptp': '',
            'status_code': '190',
            'extra_condition': CardProperty.MSG_TO_STAY_UNTIL_1ST_TRANSACTION,
            'is_have_l_button': 'true',
            'is_have_r_button': 'true',
            'is_have_m_button': 'true',
            'clickable_card': 'true',
            'card_action': 'webpage',
            'info_card_destination_webpage': 'google.co.id',
            'l_button_text': 'L',
            'l_button_text_color': '#FFFFFF',
            'l_button_action': 'app_deeplink',
            'l_button_destination_app_deeplink': 'homepage',
            'm_button_text': 'M',
            'm_button_text_color': '#FFFFFF',
            'm_button_action': 'app_deeplink',
            'm_button_destination_app_deeplink': 'homepage',
            'r_button_text': 'R',
            'r_button_text_color': '#FFFFFF',
            'r_button_action': 'app_deeplink',
            'r_button_destination_app_deeplink': 'homepage',
            'background_card_image': image,
            'optional_image': image,
            'l_button_image': image,
            'm_button_image': image,
            'r_button_image': image,
            'is_shown_in_android': 'true',
            'is_shown_in_webview': 'true',
            'youtube_video_id': '',
        }
        mocked_upload_image_assets.return_value = True
        mocked_ser.return_value = True

        response = self.client.post('/streamlined_communication/create_new_info_card', data=data,)
        info_card_property_obj = InfoCardProperty.objects.get(title='title unit test')
        info_card_button_property = InfoCardButtonProperty.objects.get(
            info_card_property_id=info_card_property_obj.id, button_name='L.BUTTON')
        self.assertEqual(info_card_button_property.destination, 'homepage')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch('juloserver.streamlined_communication.views.InfoCardSerializer.is_valid')
    def test_create_new_info_card_for_type_9_youtube(self, mocked_ser):
        data = {
            'info_card_template_code': 'info_card_unit_test_code',
            'info_card_type': '9',
            'info_card_title': '',
            'title_text_color': '#FFFFFF',
            'info_card_content': '',
            'content_parameters': '',
            'body_text_color': '#FFFFFF',
            'dpd': '',
            'dpd_lower': '',
            'dpd_upper': '',
            'until_paid': '',
            'ptp': '',
            'extra_condition': '',
            'is_have_l_button': '',
            'is_have_r_button': '',
            'is_have_m_button': '',
            'clickable_card': '',
            'status_code': '190',
            'youtube_video_id': 'nWkUpYeRTMQ',
            'is_shown_in_android': 'true',
            'is_shown_in_webview': 'true',
            'info_card_product': '',
        }
        mocked_ser.return_value = True

        response = self.client.post('/streamlined_communication/create_new_info_card', data=data,)
        streamlined_communication = StreamlinedCommunication.objects.all().last()
        streamlined_message = streamlined_communication.message
        info_card_property = streamlined_message.info_card_property
        self.assertEqual(data['youtube_video_id'], info_card_property.youtube_video_id)
        self.assertEqual(data['info_card_type'], info_card_property.card_type)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch('juloserver.streamlined_communication.views.InfoCardSerializer.is_valid')
    @mock.patch('juloserver.streamlined_communication.views.create_and_upload_image_assets_for_streamlined')
    def test_update_info_card(self, mocked_ser, mocked_upload_image_assets):
        image = (io.BytesIO(b"test"), 'test.png')
        data = {
            'info_card_id': self.streamlined_communication.id,
            'info_card_template_code': 'info_card_unit_test_code',
            'info_card_type': '1',
            'info_card_product' : 'J1',
            'info_card_title': 'title unit test',
            'title_text_color': '#FFFFFF',
            'info_card_content': 'unit test info card content',
            'content_parameters': 'unit_test_param_1,unit_test_param_2',
            'body_text_color': '#FFFFFF',
            'dpd': '',
            'ptp': '',
            'status_code': 190,
            'extra_condition': CardProperty.MSG_TO_STAY_UNTIL_1ST_TRANSACTION,
            'is_have_l_button': 'true',
            'is_have_r_button': 'true',
            'is_have_m_button': 'true',
            'clickable_card': 'true',
            'card_action': 'webpage',
            'info_card_destination_webpage': 'google.co.id',
            'l_button_text': 'L',
            'l_button_text_color': '#FFFFFF',
            'l_button_action': 'app_deeplink',
            'l_button_destination_app_deeplink': 'homepage',
            'm_button_text': 'M',
            'm_button_text_color': '#FFFFFF',
            'm_button_action': 'app_deeplink',
            'm_button_destination_app_deeplink': 'homepage',
            'r_button_text': 'R',
            'r_button_text_color': '#FFFFFF',
            'r_button_action': 'app_deeplink',
            'r_button_destination_app_deeplink': 'homepage',
            'background_card_image': image,
            'optional_image': image,
            'l_button_image': image,
            'm_button_image': image,
            'r_button_image': image,
            'is_background_changes': 'true',
            'is_optional_image_changes': 'true',
            'is_button_l_background_changes': 'true',
            'is_button_m_background_changes': 'true',
            'is_button_r_background_changes': 'true',
            'is_shown_in_android': 'true',
            'is_shown_in_webview': 'true',
            'youtube_video_id': '',
        }
        mocked_upload_image_assets.return_value = True
        mocked_ser.return_value = True

        response = self.client.post('/streamlined_communication/update_info_card', data=data, )
        self.streamlined_communication.refresh_from_db()
        self.info_card.refresh_from_db()
        expected_l_button = InfoCardButtonProperty.objects.filter(
            info_card_property_id=self.info_card.id,
            button_name='L.BUTTON'
        ).last()
        expected_r_button = InfoCardButtonProperty.objects.filter(
            info_card_property_id=self.info_card.id,
            button_name='R.BUTTON'
        ).last()
        expected_m_button = InfoCardButtonProperty.objects.filter(
            info_card_property_id=self.info_card.id,
            button_name='M.BUTTON'
        ).last()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data['info_card_id'], self.streamlined_communication.id)
        self.assertEqual(data['info_card_template_code'],
                         self.streamlined_communication.template_code)
        self.assertEqual(data['info_card_type'], self.info_card.card_type)
        self.assertEqual(data['info_card_title'], self.info_card.title)
        self.assertEqual(data['title_text_color'], self.info_card.title_color)
        self.assertEqual(data['info_card_content'],
                         self.streamlined_communication.message.message_content)
        self.assertEqual(['unit_test_param_1', 'unit_test_param_2'],
                         self.streamlined_communication.message.parameter)
        self.assertEqual(data['body_text_color'], self.info_card.text_color)
        self.assertEqual(data['status_code'], self.streamlined_communication.status_code.status_code)
        self.assertEqual(data['extra_condition'], self.streamlined_communication.extra_conditions)
        self.assertEqual(True, self.streamlined_communication.show_in_android)
        self.assertEqual(True, self.streamlined_communication.show_in_web)
        self.assertIsNotNone(expected_l_button)
        self.assertIsNotNone(expected_r_button)
        self.assertIsNotNone(expected_m_button)
        self.assertEqual(data['card_action'], self.info_card.card_action)
        self.assertEqual(data['info_card_destination_webpage'], self.info_card.card_destination)

    @mock.patch('juloserver.streamlined_communication.views.InfoCardSerializer.is_valid')
    def test_update_info_card_for_type_9_youtube(self, mocked_ser):

        self.info_card = InfoCardPropertyFactory()
        self.info_card.youtibe_id = 'nWkUpYeRTMQ'

        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.LOC_APPROVED,
            extra_conditions=CardProperty.MSG_TO_STAY_UNTIL_1ST_TRANSACTION
        )
        data_to_update = {
            'info_card_id': self.streamlined_communication.id,
            'info_card_template_code': 'Template_code 1',
            'info_card_type': '9',
            'info_card_title': '',
            'title_text_color': '#FFFFFF',
            'info_card_content': '',
            'content_parameters': '',
            'body_text_color': '#FFFFFF',
            'dpd': '',
            'dpd_lower': '',
            'dpd_upper': '',
            'until_paid': '',
            'ptp': '',
            'extra_condition': '',
            'is_have_l_button': '',
            'is_have_r_button': '',
            'is_have_m_button': '',
            'clickable_card': '',
            'status_code': '190',
            'youtube_video_id': 'KlvPsocufig',
            'is_shown_in_android': 'true',
            'is_shown_in_webview': 'true',
            'is_background_changes': '',
            'is_optional_image_changes': '',
            'info_card_product': '',
        }

        response = self.client.post('/streamlined_communication/update_info_card', data=data_to_update, )
        mocked_ser.return_value = True
        self.streamlined_communication.refresh_from_db()
        self.info_card.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(data_to_update['youtube_video_id'], self.info_card.youtube_video_id)

    def test_info_card_update_ordering_and_activate(self):
        data = {
            'updated_info_card_ids': self.streamlined_communication.id,
            'is_active-{}'.format(self.streamlined_communication.id): 'true',
            'infoCardOrder-{}'.format(self.streamlined_communication.id): '4'
        }
        response = self.client.post('/streamlined_communication/info_card_update_ordering_and_activate', data=data, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_info_card(self):
        data = {
            'streamlined_communication_id': self.streamlined_communication.id,
        }
        response = self.client.post('/streamlined_communication/delete_info_card', data=data, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestViewsInfoCardAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account = AccountFactory(customer=self.customer)
        self.master_agreement_template = MasterAgreementTemplateFactory()
        self.application = ApplicationFactory(
            id=77777,
            customer=self.customer, workflow=self.workflow,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            application_status=StatusLookupFactory(status_code=190)
        )
        self.loan = LoanFactory(account=self.account)
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id, score='A')
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
                                HTTP_X_APP_VERSION='7.7.0')
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False
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
            created_by='Djasen Tjendry'
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id',
            value="#nth:-1:1",
            experiment_id=self.experiment.id
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name='master_agreement_setting',
        )

    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_android_info_card(
            self, mocked_is_already_have_transaction, mock_get_eta_time_for_c_score_delay, mock_checking_rating_shown):
        self.info_card = InfoCardPropertyFactory()
        self.button = ButtonInfoCardFactory(id=888, info_card_property=self.info_card)
        self.image_button = ImageFactory(
            image_source=self.button.id,
            image_type=CardProperty.IMAGE_TYPE.button_background_image)
        self.image_background = ImageFactory(
            image_source=self.info_card.id,
            image_type=CardProperty.IMAGE_TYPE.card_background_image)
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.LOC_APPROVED,
            extra_conditions=CardProperty.MSG_TO_STAY_UNTIL_1ST_TRANSACTION
        )
        mocked_is_already_have_transaction.return_value = False
        self.application.application_status_id = 190
        self.application.workflow_id = self.workflow.id
        self.application.save()
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # C score and julo one
        ## delay for C score
        credit_score = self.credit_score
        credit_score.score = 'C'
        credit_score.save()
        j1_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        mock_get_eta_time_for_c_score_delay.return_value = \
            timezone.localtime(timezone.now()) + relativedelta(days=1)
        self.application.workflow = j1_workflow
        self.application.application_status_id = 105
        self.application.save()
        app_history_105 = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105)
        StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=105,
            extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DElAY,
            is_active=True
        )
        mocked_is_already_have_transaction.return_value = False
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)
        ## not delay
        StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=105,
            extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C,
            is_active=True
        )
        mock_get_eta_time_for_c_score_delay.return_value = \
            timezone.localtime(timezone.now()) - relativedelta(days=1)
        mocked_is_already_have_transaction.return_value = False
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)

    @mock.patch('juloserver.streamlined_communication.services2.web_services.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.services2.'
                'web_services.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_web_info_card(
            self, mocked_is_already_have_transaction, mock_get_eta_time_for_c_score_delay, mock_checking_rating_shown):
        self.info_card = InfoCardPropertyFactory()
        self.button = ButtonInfoCardFactory(id=888, info_card_property=self.info_card)
        self.image_button = ImageFactory(
            image_source=self.button.id,
            image_type=CardProperty.IMAGE_TYPE.button_background_image)
        self.image_background = ImageFactory(
            image_source=self.info_card.id,
            image_type=CardProperty.IMAGE_TYPE.card_background_image)
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.LOC_APPROVED,
            extra_conditions=CardProperty.MSG_TO_STAY_UNTIL_1ST_TRANSACTION
        )
        mocked_is_already_have_transaction.return_value = False
        self.application.application_status_id = 190
        self.application.workflow_id = self.workflow.id
        self.application.save()
        response = self.client.get('/api/streamlined_communication/web/v1/info_cards')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # C score and julo one
        ## delay for C score
        credit_score = self.credit_score
        credit_score.score = 'C'
        credit_score.save()
        j1_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        mock_get_eta_time_for_c_score_delay.return_value = \
            timezone.localtime(timezone.now()) + relativedelta(days=1)
        self.application.workflow = j1_workflow
        self.application.application_status_id = 105
        self.application.save()
        app_history_105 = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105)
        StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=105,
            extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DElAY,
            is_active=True
        )
        mocked_is_already_have_transaction.return_value = False
        response = self.client.get('/api/streamlined_communication/web/v1/info_cards')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)
        ## not delay
        StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=105,
            extra_conditions=CardProperty.CUSTOMER_HAVE_LOW_SCORE_OR_C,
            is_active=True,
            show_in_web=True
        )
        mock_get_eta_time_for_c_score_delay.return_value = \
            timezone.localtime(timezone.now()) - relativedelta(days=1)
        mocked_is_already_have_transaction.return_value = False
        response = self.client.get('/api/streamlined_communication/web/v1/info_cards')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)

    @mock.patch('juloserver.streamlined_communication.views.check_scrapped_bank',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_submitted_bpjs',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.is_income_in_range', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_salary_izi_data',
                return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.check_iti_repeat', return_value=False)
    def test_popup_mandocs_should_shown_when_below_threshold__has_salary__izi_found__income_not_in_range(
            self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6
    ):
        """
        Test case #2
        based on https://docs.google.com/spreadsheets/d/1If1mT_zuCFLY5pDN9bm08yNM_gLShJr_/edit?usp=sharing&ouid=113723092991318373162&rtpof=true&sd=true
        """
        self.credit_score.score = 'B-'
        self.credit_score.save()
        self.application.application_status_id = 120
        self.application.save()

        ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment
        )
        JobTypeFactory(job_type=self.application.job_type)

        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json = response.json()
        self.assertEqual(json['data']['is_document_submission'], True)

    @mock.patch(
        'juloserver.streamlined_communication.views.is_income_in_range_agent_assisted_partner',
        return_value=True,
    )
    @mock.patch(
        'juloserver.streamlined_communication.views.is_income_in_range_leadgen_partner',
        return_value=True,
    )
    @mock.patch(
        'juloserver.streamlined_communication.views.check_scrapped_bank', return_value=False
    )
    @mock.patch(
        'juloserver.streamlined_communication.views.check_submitted_bpjs', return_value=False
    )
    @mock.patch(
        'juloserver.streamlined_communication.views.checking_rating_shown', return_value=False
    )
    @mock.patch('juloserver.streamlined_communication.views.is_income_in_range', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.check_salary_izi_data',
                return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.check_iti_repeat', return_value=False)
    def test_popup_mandocs_should_shown_when_below_threshold__passes_income_check__income_in_range(
        self,
        mock_1,
        mock_2,
        mock_3,
        mock_4,
        mock_5,
        mock_6,
        mock_7,
        mock_8,
    ):
        """
        Test case #1
        based on https://docs.google.com/spreadsheets/d/1If1mT_zuCFLY5pDN9bm08yNM_gLShJr_/edit?usp=sharing&ouid=113723092991318373162&rtpof=true&sd=true
        """
        self.credit_score.score = 'B-'
        self.credit_score.save()
        self.application.application_status_id = 120
        self.application.save()

        ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment
        )
        JobTypeFactory(job_type=self.application.job_type)

        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json = response.json()
        self.assertEqual(json['data']['is_document_submission'], False)

    @mock.patch('juloserver.streamlined_communication.views.check_scrapped_bank',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_submitted_bpjs',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.is_income_in_range', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_salary_izi_data',
                return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.check_iti_repeat', return_value=False)
    def test_popup_mandocs_should_not_shown_when_below_threshold__no_salary__izi_found__income_not_in_range(
            self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6
    ):
        self.credit_score.score = 'B-'
        self.credit_score.save()
        self.application.application_status_id = 120
        self.application.save()

        ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment
        )

        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json = response.json()
        self.assertEqual(json['data']['is_document_submission'], True)

    @mock.patch('juloserver.streamlined_communication.views.check_scrapped_bank',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_submitted_bpjs',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.is_income_in_range', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_salary_izi_data',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_iti_repeat', return_value=False)
    def test_popup_mandocs_should_not_shown_when_below_threshold__has_salary__izi_not_found__income_not_in_range(
            self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6
    ):
        """
        Test case #3
        based on https://docs.google.com/spreadsheets/d/1If1mT_zuCFLY5pDN9bm08yNM_gLShJr_/edit?usp=sharing&ouid=113723092991318373162&rtpof=true&sd=true
        """
        self.credit_score.score = 'B-'
        self.credit_score.save()
        self.application.application_status_id = 120
        self.application.save()

        ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment
        )
        JobTypeFactory(job_type=self.application.job_type)

        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json = response.json()
        self.assertEqual(json['data']['is_document_submission'], True)

    @mock.patch('juloserver.streamlined_communication.views.check_scrapped_bank',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_submitted_bpjs',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.is_income_in_range', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_salary_izi_data',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_iti_repeat', return_value=False)
    def test_popup_mandocs_should_not_shown_when_score_c_at_105(
            self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6
    ):
        """
        Test case #13
        based on https://docs.google.com/spreadsheets/d/1If1mT_zuCFLY5pDN9bm08yNM_gLShJr_/edit?usp=sharing&ouid=113723092991318373162&rtpof=true&sd=true
        """
        self.credit_score.score = 'C'
        self.credit_score.save()
        self.application.application_status_id = 105
        self.application.save()

        ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment
        )
        JobTypeFactory(job_type=self.application.job_type)

        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json = response.json()
        self.assertEqual(json['data']['is_document_submission'], False)

    @mock.patch('juloserver.streamlined_communication.views.check_scrapped_bank',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_submitted_bpjs',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_iti_repeat', return_value=False)
    @mock.patch.object(JuloOneService, 'is_high_c_score', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.do_advance_ai_id_check_task')
    def test_popup_mandocs_should_not_shown_when_high_c_score_bank_scrape_load_success(
            self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6
    ):
        """
        Test case #5
        based on https://docs.google.com/spreadsheets/d/1If1mT_zuCFLY5pDN9bm08yNM_gLShJr_/edit?usp=sharing&ouid=113723092991318373162&rtpof=true&sd=true
        """
        from juloserver.apiv2.tests.factories import EtlJobFactory
        EtlJobFactory(application_id=self.application.id, status='load_success')
        self.credit_score.score = 'B--'
        self.credit_score.save()
        self.application.application_status_id = 120
        self.application.save()
        ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment
        )
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json = response.json()
        self.assertEqual(json['data']['is_document_submission'], False)

    @mock.patch('juloserver.streamlined_communication.views.check_scrapped_bank',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_submitted_bpjs',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_iti_repeat', return_value=False)
    @mock.patch.object(JuloOneService, 'is_high_c_score', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.do_advance_ai_id_check_task')
    def test_popup_mandocs_should_not_shown_when_high_c_score_bank_scrape_not_load_success(
            self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6
    ):
        """
        Test case #4
        based on https://docs.google.com/spreadsheets/d/1If1mT_zuCFLY5pDN9bm08yNM_gLShJr_/edit?usp=sharing&ouid=113723092991318373162&rtpof=true&sd=true
        """
        from juloserver.apiv2.tests.factories import EtlJobFactory
        EtlJobFactory(application_id=self.application.id, status='initiated')
        self.credit_score.score = 'B--'
        self.credit_score.save()
        self.application.application_status_id = 120
        self.application.save()
        ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment
        )
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json = response.json()
        self.assertEqual(json['data']['is_document_submission'], False)

    @mock.patch('juloserver.streamlined_communication.views.check_scrapped_bank',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_submitted_bpjs',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_iti_repeat', return_value=False)
    @mock.patch.object(JuloOneService, 'is_high_c_score', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.do_advance_ai_id_check_task')
    def test_popup_mandocs_should_not_shown_when_high_c_inactive__Bplus_bank_scrape_load_success(
            self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6
    ):
        """
        Test case #8
        based on https://docs.google.com/spreadsheets/d/1If1mT_zuCFLY5pDN9bm08yNM_gLShJr_/edit?usp=sharing&ouid=113723092991318373162&rtpof=true&sd=true
        """
        from juloserver.apiv2.tests.factories import EtlJobFactory
        EtlJobFactory(application_id=self.application.id, status='load_success')
        self.credit_score.score = 'B+'
        self.credit_score.save()
        self.application.application_status_id = 120
        self.application.save()
        ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment
        )
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json = response.json()
        self.assertEqual(json['data']['is_document_submission'], False)

    @mock.patch('juloserver.streamlined_communication.views.check_scrapped_bank',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_submitted_bpjs',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.check_iti_repeat', return_value=False)
    @mock.patch.object(JuloOneService, 'is_high_c_score', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.do_advance_ai_id_check_task')
    def test_popup_mandocs_should_not_shown_when_high_c_inactive__Bminmin_bank_scrape_load_success(
            self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6
    ):
        """
        Test case #9
        based on https://docs.google.com/spreadsheets/d/1If1mT_zuCFLY5pDN9bm08yNM_gLShJr_/edit?usp=sharing&ouid=113723092991318373162&rtpof=true&sd=true
        """
        from juloserver.apiv2.tests.factories import EtlJobFactory
        EtlJobFactory(application_id=self.application.id, status='load_success')
        self.credit_score.score = 'B--'
        self.credit_score.save()
        self.application.application_status_id = 120
        self.application.save()
        ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment
        )
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        json = response.json()
        self.assertEqual(json['data']['is_document_submission'], False)

    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_julovers_mtl_migration(self, *mock_args):
        julover_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        self.customer.update_safely(can_reapply=False)
        self.application.update_safely(product_line=julover_product_line)

        info_card = InfoCardPropertyFactory(title='migration_title')
        streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=info_card
        )
        StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            extra_conditions=CardProperty.MTL_MIGRATION_CAN_NOT_REAPPLY,
            is_active=True,
            message=streamlined_message
        )
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.content)
        self.assertEqual(0, len(response.json()['data']['cards']), response.json()['data']['cards'])

    @mock.patch(
        'juloserver.streamlined_communication.views.checking_rating_shown', return_value=False
        )
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_julovers_loan_info_card(self, *mock_args):
        julover_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        self.customer.update_safely(can_reapply=False)
        self.application.update_safely(application_status_id=190, product_line=julover_product_line)
        self.loan.update_safely(loan_status=StatusLookupFactory(status_code=212))

        info_card = InfoCardPropertyFactory(title='julover title')
        streamlined_message = StreamlinedMessageFactory(
            message_content="julovers info card",
            info_card_property=info_card
        )
        StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            extra_conditions=None,
            status_code=StatusLookupFactory(status_code=212),
            is_active=True,
            message=streamlined_message
        )

        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(status.HTTP_200_OK, response.status_code, response.content)
        self.assertEqual(1, len(response.json()['data']['cards']), response.json()['data']['cards'])
        self.assertEqual('julover title', response.json()['data']['cards'][0]['title']['text'])

    @mock.patch(
        'juloserver.streamlined_communication.views.checking_rating_shown', return_value=False
        )
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_j1_master_agreement_info_card(self, *mock_args):
        self.application.application_status_id = 190
        self.application.save()
        info_card = InfoCardPropertyFactory(title='master agreement')
        streamlined_message = StreamlinedMessageFactory(
            message_content="master agreement",
            info_card_property=info_card
        )
        StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            extra_conditions=CardProperty.HAS_NOT_SIGN_MASTER_AGREEMENT,
            status_code=StatusLookupFactory(status_code=190),
            is_active=True,
            message=streamlined_message
        )

        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(status.HTTP_200_OK, response.status_code, response.content)
        self.assertEqual(1, len(response.json()['data']['cards']), response.json()['data']['cards'])
        self.assertEqual('master agreement', response.json()['data']['cards'][0]['title']['text'])

    @mock.patch(
        'juloserver.streamlined_communication.views.checking_rating_shown', return_value=False
    )
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    @mock.patch(
        'juloserver.streamlined_communication.views.is_product_locked', return_value=False
    )
    def test_android_info_card_api__for_serbuacuankita_campaign(self, *mock_args):
        ReferralSystemFactory()
        self.customer.update_safely(self_referral_code='TESTJULO')
        self.account.update_safely(status=StatusLookupFactory(status_code=420))
        self.application.application_status_id = 190
        self.application.save()
        PaymentFactory(loan=self.loan, payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME))
        info_card_property = InfoCardPropertyFactory(
                card_type=1,
                card_action='app_deeplink',
                card_destination='referral',
                card_order_number=1,
                title='',
                title_color='#FFFF',
                text_color='#FFFF'
            )
        ButtonInfoCardFactory(info_card_property=info_card_property)
        streamlined_message = StreamlinedMessageFactory(
            message_content='',
            info_card_property=info_card_property
        )
        streamlined_communication = StreamlinedCommunicationFactory(
            message=streamlined_message,
            template_code=TemplateCode.CARD_REFERRAL_SERBUCUANKITA,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            extra_conditions=CardProperty.J1_ACTIVE_REFERRAL_CODE_EXIST
        )

        with patch.object(
            timezone, 'now', return_value=datetime(2023, 5, 12)
        ) as mock_timezone:
            expected_response = [{
                'type': '1',
                'streamlined_communication_id': streamlined_communication.id,
                'title': {'colour': '#FFFF', 'text': ''},
                'content': {'colour': '#FFFF', 'text': ''},
                'button': [{
                    'colour': '',
                    'text': 'Button',
                    'textcolour': None,
                    'action_type': None,
                    'destination': None,
                    'border': None,
                    'background_img': None
                }],
                'border': None,
                'background_img': None,
                'image_icn': None,
                'card_action_type': 'app_deeplink',
                'card_action_destination': 'referral',
                'youtube_video_id': None,
            }]

            response = self.client.get('/api/streamlined_communication/v1/android_info_card')
            response_data_cards = response.json()['data']['cards']
            self.assertEqual(status.HTTP_200_OK, response.status_code, response.content)
            self.assertEqual(1, len(response_data_cards))
            self.assertEqual(expected_response, response_data_cards)


    @mock.patch(
        'juloserver.streamlined_communication.views.checking_rating_shown', return_value=False
    )
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    @mock.patch(
        'juloserver.streamlined_communication.views.is_product_locked', return_value=False
    )
    @mock.patch(
        'juloserver.streamlined_communication.views.'
        'create_collection_hi_season_promo_card'
    )
    @mock.patch(
        'juloserver.streamlined_communication.views.'
        'get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_android_info_card_api_for_julo_card_choose_tenor(
            self, mock_get_credit_matrix_and_credit_matrix_product_line,
            mock_create_collection_hi_season_promo_card, *mock_args
    ):
        self.application.application_status_id = 190
        self.application.save()

        info_card = InfoCardPropertyFactory(
            # id=last_info_card_id + 1,
            card_type='6',
            title='Ubah cicilan dan pilih tenor untuk kebebasan transaksi kamu',
            title_color='#00ACF0',
            text_color='#00ACF0',
            card_order_number=1
        )
        data_buttons = {
            'button': ['Lewati', 'Ubah tenor'],
            'button_name': ['L.BUTTON', 'R.BUTTON'],
            'click_to': ['skip_choose_tenor', 'julo_card_choose_tenor'],
            'button_text_color': ['#00ACF0', '#FFFFFF'],
            'button_background_type': ['L', 'R'],
            'button_url': [],
        }
        for idx, _ in enumerate(data_buttons['button']):
            ButtonInfoCardFactory(
                id=989 + idx,
                info_card_property=info_card,
                text=data_buttons['button'][idx],
                button_name=data_buttons['button_name'][idx],
                action_type=CardProperty.APP_DEEPLINK,
                destination=data_buttons['click_to'][idx],
                text_color=data_buttons['button_text_color'][idx],
            )

        message = StreamlinedMessageFactory(
            message_content='',
            info_card_property=info_card
        )
        julo_card_streamlined_communication = StreamlinedCommunicationFactory(
            status_code=None,
            status=None,
            communication_platform=CommunicationPlatform.INFO_CARD,
            message=message,
            description='',
            is_active=True,
            extra_conditions=CardProperty.CREDIT_CARD_TRANSACTION_CHOOSE_TENOR
        )

        credit_card_application = create_mock_credit_card_application(
            CreditCardCodes.CARD_ACTIVATED
        )
        credit_card_application.update_safely(account=self.account)
        transaction_method = TransactionMethodFactory(
            id=TransactionMethodCode.CREDIT_CARD.code,
            method=TransactionMethodCode.CREDIT_CARD.name,
            transaction_category=TransactionCategoryFactory(fe_display_name="Belanja"),
        )
        self.loan.update_safely(transaction_method=transaction_method,
                                cdate=timezone.localtime(timezone.now()),
                                loan_status_id=210,
                                loan_disbursement_amount=600000)
        affordability_history = AffordabilityHistoryFactory(application=self.application)
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score=u'A-',
            credit_matrix_id=credit_matrix.id
        )
        AccountLimitFactory(
            account=self.account,
            max_limit=10000000,
            set_limit=10000000,
            available_limit=10000000,
            latest_affordability_history=affordability_history,
            latest_credit_score=credit_score,
        )
        AccountPropertyFactory(
            account=credit_card_application.account,
            concurrency=True
        )
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = \
            credit_matrix, credit_matrix_product_line
        mock_create_collection_hi_season_promo_card.return_value = {
            'buttonurl': 'test_button_url',
            'topimage': 'test_top_image',
        }
        expected_response = {
            "type": "6",
            "streamlined_communication_id": julo_card_streamlined_communication.id,
            "title": {
                "colour": "#00ACF0",
                "text": "Ubah cicilan dan pilih tenor untuk kebebasan transaksi kamu"
            },
            "content": {
                "colour": "#00ACF0",
                "text": ""
            },
            "button": [
                {
                    "colour": "",
                    "text": "Lewati",
                    "textcolour": "#00ACF0",
                    "action_type": "app_deeplink",
                    "destination": "skip_choose_tenor",
                    "border": None,
                    "background_img": None
                },
                {
                    "colour": "",
                    "text": "Ubah tenor",
                    "textcolour": "#FFFFFF",
                    "action_type": "app_deeplink",
                    "destination": "julo_card_choose_tenor",
                    "border": None,
                    "background_img": None
                }
            ],
            "border": None,
            "background_img": None,
            "image_icn": None,
            "card_action_type": "app_deeplink",
            "card_action_destination": None,
            "youtube_video_id": None,
        }

        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(status.HTTP_200_OK, response.status_code, response.content)
        response_data_cards = response.json()['data']['cards']
        self.assertEqual(2, len(response_data_cards))
        self.assertEqual(julo_card_streamlined_communication.id,
                         response_data_cards[1]['streamlined_communication_id'])
        self.assertEqual(expected_response, response_data_cards[1])

    def create_infocard_data(self, data):

        for item in data:
            title_card = item['title_card']
            button_text = item['button_text']
            destination = item['destination']
            streamlined_message = item['streamlined_message']
            card_type = item['card_type']

            self.info_card = InfoCardPropertyFactory(
                card_type=card_type,
                title=title_card,
                title_color='#ffffff',
                text_color='#ffffff',
                card_order_number=1
            )
            if card_type == '1':
                self.button = ButtonInfoCardFactory(
                    info_card_property=self.info_card,
                    text=button_text,
                    button_name='R.BUTTON',
                    action_type='app_deeplink',
                    destination=destination,
                    text_color='#ffffff',
                )
            else:
                self.button = ButtonInfoCardFactory(
                    info_card_property=self.info_card,
                    text=button_text,
                    button_name='',
                    action_type='',
                    destination=destination,
                    text_color='#ffffff',
                )

            self.image_button = ImageFactory(
                image_source=self.button.id,
                image_type=CardProperty.IMAGE_TYPE.button_background_image)
            self.image_background = ImageFactory(
                image_source=self.info_card.id,
                image_type=CardProperty.IMAGE_TYPE.card_background_image)

            self.streamlined_message = StreamlinedMessageFactory(
                message_content=streamlined_message,
                info_card_property=self.info_card
            )

    @mock.patch('juloserver.streamlined_communication.views.customer_have_upgrade_case', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.is_using_turbo_limit', return_value=True)
    def test_android_card_for_success_upgrade_case(
            self,
            mock_using_turbo_limit,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_have_upgrade_case,
    ):
        """
        To test upgrade to J1 is success
        """

        title_info_card = 'Akunmu sudah Upgrade ke JULO Kredit Digital'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': 'Pinjam Tunai',
                'destination': '',
                'card_type': '1',
                'streamlined_message': 'Yuk, rutin transaksi di JULO agar limitmu dapat meningkat!'
            },
        ]

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
                                HTTP_X_APP_VERSION='7.6.0')

        # create infocard data
        self.create_infocard_data(data_infocard)

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        CreditScoreFactory(
            application_id=self.application.id,
            score='A',
            credit_matrix_id=credit_matrix.id
        )

        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.LOC_APPROVED,
            is_active=True,
            extra_conditions='J1_LIMIT_LESS_THAN_TURBO'
        )

        # J1
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        # JStarter
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )

        self.application.application_status = StatusLookupFactory(status_code=190)
        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_j1
        self.application.save()

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment,
        )

        self.application_jstarter = ApplicationFactory(
            workflow=self.workflow_jstarter,
            product_line=self.product_jstarter,
            customer=self.customer,
        )
        self.application_jstarter.update_safely(StatusLookupFactory(status_code=192))

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_android_card_for_offer_to_j1(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown
    ):
        """
        To test scenario user have status x107 (Offer to J1) from Julo Turbo aka Julo Starter
        """

        title_card = 'Pengajuan JULO Turbo Belum Berhasil'
        button_text = 'Ajukan JULO Kredit Digital'
        destination = 'to_upgrade_form'
        streamlined_message = 'Kamu masih bisa ajukan JULO Kredit Digital, kok. Ajukan sekarang!'

        self.info_card = InfoCardPropertyFactory(
            card_type='1',
            title=title_card,
            title_color='#ffffff',
            text_color='#ffffff',
            card_order_number=1
        )
        self.button = ButtonInfoCardFactory(
            info_card_property=self.info_card,
            text=button_text,
            button_name='R.BUTTON',
            action_type='app_deeplink',
            destination=destination,
            text_color='#ffffff',
        )
        self.image_button = ImageFactory(
            image_source=self.button.id,
            image_type=CardProperty.IMAGE_TYPE.button_background_image)
        self.image_background = ImageFactory(
            image_source=self.info_card.id,
            image_type=CardProperty.IMAGE_TYPE.card_background_image)

        self.streamlined_message = StreamlinedMessageFactory(
            message_content=streamlined_message,
            info_card_property=self.info_card
        )

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)

        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )
        CreditScoreFactory(
            application_id=self.application.id,
            score='A-',
            credit_matrix_id=credit_matrix.id
        )

        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.OFFER_REGULAR,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.JULO_TURBO_OFFER_TO_REGULAR
        )

        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )
        mocked_is_already_have_transaction.return_value = False

        self.application.application_status_id = ApplicationStatusCodes.OFFER_REGULAR
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_jstarter
        self.application.save()

        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]

        self.assertEqual(response_json['title']['text'], title_card)
        self.assertEqual(response_json['content']['text'], streamlined_message)
        self.assertEqual(response_json['button'][0]['text'], button_text)
        self.assertEqual(response_json['button'][0]['destination'], destination)

    def create_infocard_data(self, data):

        for item in data:
            title_card = item['title_card']
            button_text = item['button_text']
            destination = item['destination']
            streamlined_message = item['streamlined_message']
            card_type = item['card_type']

            self.info_card = InfoCardPropertyFactory(
                card_type=card_type,
                title=title_card,
                title_color='#ffffff',
                text_color='#ffffff',
                card_order_number=1
            )
            if card_type == '1':
                self.button = ButtonInfoCardFactory(
                    info_card_property=self.info_card,
                    text=button_text,
                    button_name='R.BUTTON',
                    action_type='app_deeplink',
                    destination=destination,
                    text_color='#ffffff',
                )
            else:
                self.button = ButtonInfoCardFactory(
                    info_card_property=self.info_card,
                    text=button_text,
                    button_name='',
                    action_type='',
                    destination=destination,
                    text_color='#ffffff',
                )

            self.image_button = ImageFactory(
                image_source=self.button.id,
                image_type=CardProperty.IMAGE_TYPE.button_background_image)
            self.image_background = ImageFactory(
                image_source=self.info_card.id,
                image_type=CardProperty.IMAGE_TYPE.card_background_image)

            self.streamlined_message = StreamlinedMessageFactory(
                message_content=streamlined_message,
                info_card_property=self.info_card
            )

    @mock.patch('juloserver.streamlined_communication.views.user_have_upgrade_application', return_value=({}, True))
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_for_activation_call_process(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_have_upgrade_case
    ):
        """
        To test scenario user have upgrade app from JTurbo to J1
        And for J1 still Activation Call Process
        """
        title_info_card = 'Proses Verifikasi Telepon 📞'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': 'Ajukan JULO Kredit Digital',
                'destination': '',
                'card_type': '2',
                'streamlined_message': 'Pihak JULO akan segera menghubungimu untuk proses upgrade ke JULO Kredit Digital.'
            },
        ]

        self.create_infocard_data(data_infocard)

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)

        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        CreditScoreFactory(
            application_id=self.application.id,
            score='C',
            credit_matrix_id=credit_matrix.id
        )

        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.ACTIVATION_CALL_JTURBO_UPGRADE
        )

        # J1
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        # JStarter
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )

        # J1 app in status 141
        self.application.application_status_id = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_j1
        self.application.save()

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment,
        )

        # JTurbo app in status 191
        self.application_jstarter = ApplicationFactory(
            workflow=self.workflow_jstarter,
            product_line=self.product_jstarter,
            customer=self.customer,
        )
        self.application_jstarter.update_safely(application_status=StatusLookupFactory(status_code=191))

        # create Application Upgrade
        application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application.id,
            application_id_first_approval=self.application_jstarter.id,
            is_upgrade=1,
        )

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.user_have_upgrade_application', return_value=({}, True))
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.is_using_turbo_limit', return_value=False)
    def test_android_card_for_success_upgrade_case(
            self,
            mock_using_turbo_limit,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_have_upgrade_case
    ):
        """
        To test upgrade to J1 is success
        """

        title_info_card = 'Asik, Upgrade dan Naik Limit Berhasil!'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': 'Pinjam Tunai',
                'destination': '',
                'card_type': '1',
                'streamlined_message': 'Yuk, rutin transaksi di JULO agar limitmu dapat meningkat!'
            },
        ]

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
                                HTTP_X_APP_VERSION='7.6.0')

        # create infocard data
        self.create_infocard_data(data_infocard)

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        CreditScoreFactory(
            application_id=self.application.id,
            score='A',
            credit_matrix_id=credit_matrix.id
        )

        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.LOC_APPROVED,
            is_active=True,
            product='jstarter',
            extra_conditions='J1_LIMIT_MORE_THAN_TURBO'
        )

        # J1
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        # JStarter
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )

        self.application_jstarter = ApplicationFactory(
            workflow=self.workflow_jstarter,
            product_line=self.product_jstarter,
            customer=self.customer,
        )
        self.application_jstarter.update_safely(application_status=StatusLookupFactory(status_code=192))

        self.application.application_status = StatusLookupFactory(status_code=190)
        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_j1
        self.application.save()

        # create Application Upgrade
        application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application.id,
            application_id_first_approval=self.application_jstarter.id,
            is_upgrade=1,
        )

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment,
        )

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @patch.object(Application, 'has_master_agreement', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.is_active_session_limit_infocard')
    @mock.patch('juloserver.streamlined_communication.views.user_have_upgrade_application', return_value=({}, True))
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_for_failed_upgrade_case(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_have_upgrade_case,
            mock_session_infocard,
            mock_application,
    ):
        """
        To test upgrade to J1 is failed
        """

        title_info_card = 'Permohonan Upgrade Gagal'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '2',
                'streamlined_message': 'Kamu belum memenuhi kriteria yang ada dari analisa tim JULO.'
                                       ' {{duration_message}} '
                                       'Tenang, kamu masih bisa menggunakan limit JULO Turbo'
            },
        ]

        # create infocard data
        self.create_infocard_data(data_infocard)
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.REJECTION_JTURBO_UPGRADE
        )

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
                                HTTP_X_APP_VERSION='7.6.0')

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score='A',
            credit_matrix_id=credit_matrix.id
        )

        self.master = MasterAgreementTemplateFactory(is_active=False)

        # JStarter
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )

        workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_jstarter
        self.application.save()

        self.application.update_safely(application_status=StatusLookupFactory(status_code=191))
        self.application_j1 = ApplicationFactory(
            workflow=workflow_j1,
            product_line=product_j1,
            customer=self.customer,
        )
        self.application_j1.update_safely(application_status=StatusLookupFactory(status_code=135))

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.application_j1,
            experiment=self.experiment,
        )

        # create Application Upgrade
        application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_j1.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        application_history = ApplicationHistoryFactory(
            application_id=self.application_j1.id,
            status_old=105,
            status_new=135,
            change_reason="failed dv expired ktp"
        )

        # set session is true -> can show infocard Rejected upgrade
        mock_session_infocard.return_value = True

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

        title_info_card_default = 'Infocard JStarter Default'
        self.info_card.update_safely(title=title_info_card_default)
        self.streamlined_communication_default = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.LOC_APPROVED,
            is_active=True,
            product='jstarter',
            extra_conditions=None
        )

        # to get condition default infocard
        mock_session_infocard.return_value = False
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        credit_score_j1 = CreditScoreFactory(
            application_id=self.application_j1.id,
            score='C',
            credit_matrix_id=credit_matrix.id
        )

        self.info_card.update_safely(title=title_info_card)
        self.application_j1.update_safely(application_status=StatusLookupFactory(status_code=105))
        mock_session_infocard.return_value = True
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.check_application_are_rejected_status', return_value=True)
    @patch.object(Application, 'has_master_agreement', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.is_active_session_limit_infocard', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.user_have_upgrade_application', return_value=({}, True))
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_for_failed_upgrade_case_and_can_reapply(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_have_upgrade_case,
            mock_session_infocard,
            mock_application,
            mock_have_approval,
    ):
        """
        To test upgrade to J1 is failed
        """

        title_info_card = 'Mau Limit Lebih Besar dan Tenor Panjang?'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '1',
                'streamlined_message': 'streamlined_message_testing'
            },
        ]

        # create infocard data
        self.create_infocard_data(data_infocard)
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.JULO_TURBO_OFFER_J1_CANNOT_REAPPLY
        )

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
                                HTTP_X_APP_VERSION='7.6.0')

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        CreditScoreFactory(
            application_id=self.application.id,
            score='A',
            credit_matrix_id=credit_matrix.id
        )

        self.master = MasterAgreementTemplateFactory(is_active=False)
        # JStarter
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )
        workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_jstarter
        self.application.save()

        self.application.update_safely(application_status=StatusLookupFactory(status_code=191))
        self.application_j1 = ApplicationFactory(
            workflow=workflow_j1,
            product_line=product_j1,
            customer=self.customer,
        )
        self.application_j1.update_safely(application_status=StatusLookupFactory(status_code=135))

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.application_j1,
            experiment=self.experiment,
        )

        # create Application Upgrade
        application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_j1.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        self.customer.update_safely(can_reapply=True)

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.check_application_are_rejected_status', return_value=True)
    @patch.object(Application, 'has_master_agreement', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.is_active_session_limit_infocard', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.user_have_upgrade_application', return_value=({}, True))
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_for_failed_upgrade_case_and_cannot_reapply(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_have_upgrade_case,
            mock_session_infocard,
            mock_application,
            mock_have_approval,
    ):
        """
        To test upgrade to J1 is failed
        """

        title_info_card = 'Yuk! Lakukan Transaksi!'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '1',
                'streamlined_message': 'streamlined_message_testing'
            },
        ]

        # create infocard data
        self.create_infocard_data(data_infocard)
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.JULO_TURBO_OFFER_J1_CANNOT_REAPPLY
        )

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
                                HTTP_X_APP_VERSION='7.6.0')

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        CreditScoreFactory(
            application_id=self.application.id,
            score='A',
            credit_matrix_id=credit_matrix.id
        )

        self.master = MasterAgreementTemplateFactory(is_active=False)
        # JStarter
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )
        workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_jstarter
        self.application.save()

        self.application.update_safely(application_status=StatusLookupFactory(status_code=191))
        self.application_j1 = ApplicationFactory(
            workflow=workflow_j1,
            product_line=product_j1,
            customer=self.customer,
        )
        self.application_j1.update_safely(application_status=StatusLookupFactory(status_code=135))

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.application_j1,
            experiment=self.experiment,
        )

        # create Application Upgrade
        application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_j1.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        self.customer.update_safely(
            can_reapply=False,
            disabled_reapply_date=timezone.localtime(timezone.now()).date(),
            can_reapply_date=None,
        )
        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.check_application_are_rejected_status',
                return_value=True)
    @patch.object(Application, 'has_master_agreement', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.is_active_session_limit_infocard',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.user_have_upgrade_application',
                return_value=({}, True))
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown',
                return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction',
                return_value=False)
    def test_android_card_for_137_j1(
        self,
        mocked_is_already_have_transaction,
        mock_get_eta_time_for_c_score_delay,
        mock_checking_rating_shown,
        mock_have_upgrade_case,
        mock_session_infocard,
        mock_application,
        mock_have_approval,
    ):
        self.application.application_status_id = 137
        self.application.save()
        self.info_card = InfoCardPropertyFactory()
        self.button = ButtonInfoCardFactory(id=888, info_card_property=self.info_card)
        self.image_button = ImageFactory(
            image_source=self.button.id,
            image_type=CardProperty.IMAGE_TYPE.button_background_image)
        self.image_background = ImageFactory(
            image_source=self.info_card.id,
            image_type=CardProperty.IMAGE_TYPE.card_background_image)
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )
        StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.ALREADY_ELIGIBLE_TO_REAPPLY
        )
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]

        self.assertEqual(response_json['title']['text'], self.info_card.title)

    @mock.patch('juloserver.streamlined_communication.views.user_have_upgrade_application', return_value=({}, True))
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_for_x127_in_j1(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_have_upgrade_case
    ):
        """
        To test scenario user when get x127 in J1
        """
        title_info_card = 'Angkat Telepon dari Pihak JULO, Ya 📞'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '2',
                'streamlined_message': 'Pastikan nomor HP kamu aktif untuk memastikan datamu sudah sesuai dan benar '
                                        'biar segera bisa dapat limit, oke?'
            },
        ]

        self.create_infocard_data(data_infocard)
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        CreditScoreFactory(
            application_id=self.application.id,
            score='C',
            credit_matrix_id=credit_matrix.id
        )

        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=127,
            is_active=True,
            product='j1',
            extra_conditions=CardProperty.TYPO_CALLS_UNSUCCESSFUL
        )

        # J1
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        # J1 app in status 141
        self.application.application_status_id = 127
        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_j1
        self.application.save()

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment,
        )

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.user_have_upgrade_application', return_value=({}, True))
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_for_x128_in_j1(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_have_upgrade_case
    ):
        """
        To test scenario user when get x128 in J1
        """
        title_info_card = 'Angkat Telepon dari Pihak JULO, Ya 📞'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '2',
                'streamlined_message': 'Pastikan nomor HP kamu aktif untuk memastikan datamu sudah sesuai dan benar '
                                       'biar segera bisa dapat limit, oke?'
            },
        ]

        self.create_infocard_data(data_infocard)
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        CreditScoreFactory(
            application_id=self.application.id,
            score='C',
            credit_matrix_id=credit_matrix.id
        )

        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL,
            is_active=True,
            product='j1',
            extra_conditions=CardProperty.TYPO_CALLS_UNSUCCESSFUL
        )

        # J1
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        # J1 app
        self.application.application_status_id = ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS
        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_j1
        self.application.save()

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment,
        )

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)


    @mock.patch('juloserver.streamlined_communication.views.user_have_upgrade_application', return_value=({}, True))
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_for_x133_to_x190_jstarter(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_have_upgrade_case
    ):
        """
        To test scenario user for rejected jturbo user at x190 from x133
        """
        title_info_card = 'Test Jstarter x133 to x190'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '2',
                'streamlined_message': 'Test Jstarter 133 to 190'
            },
        ]

        self.create_infocard_data(data_infocard)
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        CreditScoreFactory(
            application_id=self.application.id,
            score='C',
            credit_matrix_id=credit_matrix.id
        )

        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.LOC_APPROVED,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.JULO_STARTER_133_TO_190
        )

        # Jstarter
        self.workflow_jturbo = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jturbo = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )

        # Jstarter app
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.workflow = self.workflow_jturbo
        self.application.product_line = self.product_jturbo
        self.application.save()

        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=133,
            status_new=190)

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.user_have_upgrade_application', return_value=({}, True))
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_if_have_expired_app_and_x100(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_have_upgrade_case
    ):
        """
        To test scenario user when get x128 in J1
        """
        title_info_card = 'Yuk lanjutkan isi formulir'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '2',
                'streamlined_message': 'Test to lanjutkan isi form'
            },
        ]

        self.create_infocard_data(data_infocard)
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        # CreditScoreFactory(
        #     application_id=self.application.id,
        #     score='C',
        #     credit_matrix_id=credit_matrix.id
        # )

        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.FORM_CREATED,
            is_active=True,
            product='j1',
            extra_conditions=None
        )

        # J1
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        # J1 app
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_j1
        self.application.save()

        self.new_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_j1,
        )
        self.new_application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment,
        )

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.get_ongoing_account_deletion_request')
    def test_ongoing_account_deletion(self, mock_get_ongoing_account_deletion_request):
        mock_get_ongoing_account_deletion_request.return_value = AccountDeletionRequestFactory(
            customer=self.customer,
        )

        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data'], {'cards': []})

    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_case_191_106_100(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
    ):
        title_info_card = 'Yuk lanjutkan isi formulir'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '2',
                'streamlined_message': 'Test to lanjutkan isi form'
            },
        ]

        self.create_infocard_data(data_infocard)
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=ApplicationStatusCodes.FORM_CREATED,
            is_active=True,
            product='j1',
            extra_conditions=None
        )

        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        # Create JTurbo Application x191
        self.application.application_status_id = ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_jstarter
        self.application.save()

        # insert to application upgrade
        application_upgrade_jturbo = ApplicationUpgradeFactory(
            application_id=self.application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=0,
        )

        # Create J1 application
        self.j1_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_j1,
        )
        self.j1_application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        )
        application_upgrade_j1 = ApplicationUpgradeFactory(
            application_id=self.j1_application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.j1_application,
            experiment=self.experiment,
        )

        # create other J1
        self.j1_second_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_j1,
        )
        self.j1_second_application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )
        # store the table application experiment as UW
        ApplicationExperimentFactory(
            application=self.j1_second_application,
            experiment=self.experiment,
        )
        application_upgrade_second_j1 = ApplicationUpgradeFactory(
            application_id=self.j1_second_application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(determine_main_application_infocard(self.customer), self.j1_second_application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @patch.object(Application, 'has_master_agreement', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_case_190_106(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_master_agreement,
    ):
        title_info_card = 'Upgrade ke JULO Kredit Digital aja. Limit hingga Rp15juta'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': 'Upgrade',
                'destination': 'turbo_to_j1',
                'card_type': '2',
                'streamlined_message': 'Mau Tarik Dana dan Naikkan Limit?'
            },
        ]

        self.create_infocard_data(data_infocard)
        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        # infocard for x190
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.JULO_TURBO_OFFER_J1_CAN_REAPPLY,
        )

        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        # Create JTurbo Application x190
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_jstarter
        self.application.save()

        # insert to application upgrade
        application_upgrade_jturbo = ApplicationUpgradeFactory(
            application_id=self.application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=0,
        )

        # Create J1 application
        self.j1_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_j1,
        )
        self.j1_application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        )
        application_upgrade_j1 = ApplicationUpgradeFactory(
            application_id=self.j1_application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=106,
            status_new=190,
            change_reason='test',
        )
        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.j1_application,
            experiment=self.experiment,
        )

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(determine_main_application_infocard(self.customer), self.application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.is_active_session_limit_infocard', return_value=False)
    @patch.object(Application, 'has_master_agreement', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_case_191_106(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_master_agreement,
            mock_is_active_session_limit,
    ):
        title_info_card = 'Yuk, lakukan transaksi dengan limit besarmu!'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '2',
                'streamlined_message': ''
            },
        ]

        # set can_reapply is False
        self.customer.update_safely(can_reapply=False)
        # create infocard data
        self.create_infocard_data(data_infocard)
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.JULO_TURBO_OFFER_J1_CANNOT_REAPPLY
        )

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        # Create JTurbo Application x191
        self.application.application_status_id = ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_jstarter
        self.application.save()

        # insert to application upgrade
        application_upgrade_jturbo = ApplicationUpgradeFactory(
            application_id=self.application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=0,
        )

        # Create J1 application
        self.j1_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_j1,
        )
        self.j1_application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        )
        application_upgrade_j1 = ApplicationUpgradeFactory(
            application_id=self.j1_application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        self.app_experiment = ApplicationExperimentFactory(
            application=self.j1_application,
            experiment=self.experiment,
        )

        # create second J1 application
        self.j1_second_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_j1,
        )
        self.j1_second_application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        )
        application_upgrade_second_j1 = ApplicationUpgradeFactory(
            application_id=self.j1_second_application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        # store the table application experiment as UW
        self.app_experiment = ApplicationExperimentFactory(
            application=self.j1_second_application,
            experiment=self.experiment,
        )

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(determine_main_application_infocard(self.customer), self.application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

        # set can_reapply is True
        self.customer.update_safely(can_reapply=True)
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(determine_main_application_infocard(self.customer), self.application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.is_active_session_limit_infocard', return_value=False)
    @patch.object(Application, 'has_master_agreement', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_case_191_136_139(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_master_agreement,
            mock_is_active_session_limit,
    ):
        title_info_card = 'Yuk, lakukan transaksi dengan limit besarmu!'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '2',
                'streamlined_message': ''
            },
        ]

        # set can_reapply is False
        self.customer.update_safely(can_reapply=False)

        # create infocard data
        self.create_infocard_data(data_infocard)
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.JULO_TURBO_OFFER_J1_CANNOT_REAPPLY
        )

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        # Create JTurbo Application x191
        self.application.application_status_id = ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_jstarter
        self.application.save()

        # insert to application upgrade
        application_upgrade_jturbo = ApplicationUpgradeFactory(
            application_id=self.application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=0,
        )

        # Create J1 application
        self.j1_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_j1,
        )
        # test case for x136
        self.j1_application.update_safely(
            application_status_id=ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        )

        application_upgrade_j1 = ApplicationUpgradeFactory(
            application_id=self.j1_application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )
        self.app_experiment = ApplicationExperimentFactory(
            application=self.j1_application,
            experiment=self.experiment,
        )

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(determine_main_application_infocard(self.customer), self.application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

        #set can_reapply is True
        self.customer.update_safely(can_reapply=True)
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(determine_main_application_infocard(self.customer), self.application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

        # 139 and can_reapply is True
        self.j1_application.update_safely(
            application_status_id=ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        )
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(determine_main_application_infocard(self.customer), self.application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch('juloserver.streamlined_communication.views.is_active_session_limit_infocard', return_value=False)
    @patch.object(Application, 'has_master_agreement', return_value=True)
    @mock.patch('juloserver.streamlined_communication.views.checking_rating_shown', return_value=False)
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction', return_value=False)
    def test_android_card_case_191_137(
            self,
            mocked_is_already_have_transaction,
            mock_get_eta_time_for_c_score_delay,
            mock_checking_rating_shown,
            mock_master_agreement,
            mock_is_active_session_limit,
    ):
        title_info_card = 'Yuk, lakukan transaksi dengan limit besarmu!'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': '',
                'card_type': '2',
                'streamlined_message': ''
            },
        ]

        # set can_reapply is False
        self.customer.update_safely(can_reapply=False)
        # create infocard data
        self.create_infocard_data(data_infocard)
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            product='jstarter',
            extra_conditions=CardProperty.JULO_TURBO_OFFER_J1_CANNOT_REAPPLY
        )

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_j1 = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

        # Create JTurbo Application x191
        self.application.application_status_id = ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_jstarter
        self.application.save()

        # insert to application upgrade
        application_upgrade_jturbo = ApplicationUpgradeFactory(
            application_id=self.application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=0,
        )

        # Create J1 application
        self.j1_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_j1,
        )
        self.j1_application.update_safely(
            application_status_id=ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        )
        application_upgrade_j1 = ApplicationUpgradeFactory(
            application_id=self.j1_application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        self.app_experiment = ApplicationExperimentFactory(
            application=self.j1_application,
            experiment=self.experiment,
        )

        # try get data infocard
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(determine_main_application_infocard(self.customer), self.application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

        # set can_reapply is True
        self.customer.update_safely(can_reapply=True)
        response = self.client.get('/api/streamlined_communication/v1/android_info_card')
        self.assertEqual(determine_main_application_infocard(self.customer), self.application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

    @mock.patch(
        'juloserver.streamlined_communication.views.is_active_session_limit_infocard',
        return_value=False,
    )
    @patch.object(Application, 'has_master_agreement', return_value=False)
    @mock.patch(
        'juloserver.streamlined_communication.views.checking_rating_shown', return_value=False
    )
    @mock.patch('juloserver.streamlined_communication.views.get_eta_time_for_c_score_delay')
    @mock.patch(
        'juloserver.streamlined_communication.services.is_already_have_transaction',
        return_value=False,
    )
    def test_android_info_card_x107_reapply(
        self,
        mocked_is_already_have_transaction,
        mock_get_eta_time_for_c_score_delay,
        mock_checking_rating_shown,
        mock_master_agreement,
        mock_is_active_session_limit,
    ):
        title_info_card = 'Ayo lanjutkan isi form pengajuan'
        data_infocard = [
            {
                'title_card': title_info_card,
                'button_text': '',
                'destination': 'to_upgrade_form',
                'card_type': '2',
                'streamlined_message': '',
            },
        ]

        endpoint_target = '/api/streamlined_communication/v1/android_info_card'

        # set can_reapply is False
        self.customer.update_safely(can_reapply=False)
        # create infocard data
        self.create_infocard_data(data_infocard)
        self.streamlined_communication = StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            status_code_id=ApplicationStatusCodes.OFFER_REGULAR,
            product='jstarter',
            extra_conditions=CardProperty.JULO_TURBO_OFFER_TO_REGULAR,
        )
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=105,
            status_new=107,
        )

        product_lookup = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product_lookup)
        CreditMatrixProductLineFactory(
            credit_matrix=credit_matrix,
            product=self.application.product_line,
            max_duration=8,
            min_duration=1,
        )

        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
        )

        # Create JTurbo Application x107
        self.application.application_status_id = ApplicationStatusCodes.OFFER_REGULAR
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_jstarter
        self.application.save()

        # insert to application upgrade
        application_upgrade_jturbo = ApplicationUpgradeFactory(
            application_id=self.application.id,
            application_id_first_approval=self.application.id,
            is_upgrade=0,
        )

        # try get data infocard
        response = self.client.get(endpoint_target)
        self.assertEqual(determine_main_application_infocard(self.customer), self.application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)

        # set can_reapply is True
        self.customer.update_safely(can_reapply=True)
        response = self.client.get(endpoint_target)
        self.assertEqual(determine_main_application_infocard(self.customer), self.application)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()['data']['cards'][0]
        self.assertEqual(response_json['title']['text'], title_info_card)


@mock.patch('juloserver.streamlined_communication.services2.web_services.checking_rating_shown', return_value=False)
class TestViewsInfoCardWebApi(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            id=777788,
            customer=self.customer, workflow=self.workflow,
            account=self.account,
            application_status=StatusLookupFactory(status_code=190)
        )
        self.loan = LoanFactory(account=self.account)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.info_card = InfoCardPropertyFactory()
        self.button = ButtonInfoCardFactory(id=888, info_card_property=self.info_card)
        self.image_button = ImageFactory(
            image_source=self.button.id,
            image_type=CardProperty.IMAGE_TYPE.button_background_image)
        self.image_background = ImageFactory(
            image_source=self.info_card.id,
            image_type=CardProperty.IMAGE_TYPE.card_background_image)
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )

    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_web_info_card_waiting_score(
            self, mocked_is_already_have_transaction, mock_checking_rating_shown):

        j1_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        self.application.workflow = j1_workflow
        self.application.application_status_id = 105
        self.application.save()
        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105)
        StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=105,
            extra_conditions=CardProperty.CUSTOMER_WAITING_SCORE,
            is_active=True,
            show_in_web=True,
            partner=None
        )
        mocked_is_already_have_transaction.return_value = False
        response = self.client.get('/api/streamlined_communication/web/v1/info_cards')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)

    @mock.patch(
        'juloserver.streamlined_communication.services2.web_services.'
        'feature_high_score_full_bypass')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_web_info_card_high_score(
            self, mocked_is_already_have_transaction, mocked_service, mock_checking_rating_shown):
        mocked_service.return_value = True
        j1_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )

        CreditScoreFactory(application_id=self.application.id, score='A')
        self.application.workflow = j1_workflow
        self.application.application_status_id = 105
        self.application.save()
        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105)
        StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=105,
            extra_conditions=CardProperty.CUSTOMER_HAVE_HIGH_SCORE,
            is_active=True,
            show_in_web=True,
            partner=None
        )
        mocked_is_already_have_transaction.return_value = False
        response = self.client.get('/api/streamlined_communication/web/v1/info_cards')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)

    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_web_info_card_medium_score(
            self, mocked_is_already_have_transaction, mock_checking_rating_shown):
        j1_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )

        CreditScoreFactory(application_id=self.application.id, score='B')
        self.application.workflow = j1_workflow
        self.application.application_status_id = 105
        self.application.save()
        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105)
        StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=105,
            extra_conditions=CardProperty.CUSTOMER_HAVE_MEDIUM_SCORE,
            is_active=True,
            show_in_web=True,
            partner=None
        )
        mocked_is_already_have_transaction.return_value = False
        response = self.client.get('/api/streamlined_communication/web/v1/info_cards')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)

    @mock.patch(
        'juloserver.application_flow.services.'
        'JuloOneService.is_high_c_score')
    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_web_info_card_high_c_score(
            self, mocked_is_already_have_transaction, mocked_service, mock_checking_rating_shown):
        mocked_service.return_value = True

        j1_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )

        CreditScoreFactory(application_id=self.application.id, score='C+')
        self.application.workflow = j1_workflow
        self.application.application_status_id = 105
        self.application.save()
        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105)
        StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=105,
            extra_conditions=CardProperty.CUSTOMER_HAVE_HIGH_C_SCORE,
            is_active=True,
            show_in_web=True,
            partner=None
        )
        mocked_is_already_have_transaction.return_value = False
        response = self.client.get('/api/streamlined_communication/web/v1/info_cards')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)

    @mock.patch('juloserver.streamlined_communication.services.is_already_have_transaction')
    def test_web_info_106(
            self, mocked_is_already_have_transaction, mock_checking_rating_shown):
        j1_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )

        self.application.workflow = j1_workflow
        self.application.application_status_id = 106
        self.application.save()
        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105)
        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=105,
            status_new=106)
        StreamlinedCommunicationFactory(
            message=self.streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=106,
            extra_conditions=CardProperty.ALL_106_EXPECT_PREVIOUS_EXPIRY_REASON,
            is_active=True,
            show_in_web=True,
            partner=None
        )
        mocked_is_already_have_transaction.return_value = False
        response = self.client.get('/api/streamlined_communication/web/v1/info_cards')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)


class TestPauseReminder(TestCase):
    def setUp(self):
        group = Group(name="product_manager")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        self.client.force_login(self.user)

    def test_get_pause_reminder_failed(self):
        # missing params
        response = self.client.get('/streamlined_communication/get_pause_reminder')
        self.assertEqual(response.status_code, 200)

        # loan not found
        response = self.client.get(
            '/streamlined_communication/get_pause_reminder',
            data={
                'block_id': 9999999999,
                'block_type': 'mtl'
            })
        self.assertEqual(response.status_code, 200)

        # account not found
        response = self.client.get(
            '/streamlined_communication/get_pause_reminder',
            data={
                'block_id': 9999999999,
                'block_type': 'j1'
            })
        self.assertEqual(response.status_code, 200)

    def test_get_pause_reminder_success(self):
        today = timezone.localtime(timezone.now()).date()
        # with loan
        loan = LoanFactory()
        payment = loan.payment_set.order_by('payment_number').first()
        payment.due_date = today + timedelta(days=1)
        payment.save()
        comms_blocked = CommsBlockedFactory(
            loan=loan, impacted_payments=[payment.id])
        response = self.client.get(
            '/streamlined_communication/get_pause_reminder',
            data={
                'block_id': loan.id,
                'block_type': 'mtl'
            })
        self.assertEqual(response.status_code, 200)

        # account not found
        account = AccountFactory()
        account_payment = AccountPaymentFactory(account=account)
        account_payment.due_date = today + timedelta(days=1)
        account_payment.save()
        comms_blocked = CommsBlockedFactory(
            account=account, impacted_payments=[account_payment.id])
        response = self.client.get(
            '/streamlined_communication/get_pause_reminder',
            data={
                'block_id': account.id,
                'block_type': 'j1'
            })
        self.assertEqual(response.status_code, 200)

    def test_submit_pause_reminder_failed(self):
        # block_dpd not found
        response = self.client.post(
            '/streamlined_communication/submit_pause_reminder',
            data={
                'block_id': 9999999999,
                'block_type': 'mtl'
            })
        self.assertEqual(response.status_code, 400)
        # loan not found
        response = self.client.post(
            '/streamlined_communication/submit_pause_reminder',
            data={
                'block_id': 9999999999,
                'block_type': 'mtl',
                'block_dpd': -1
            })
        self.assertEqual(response.status_code, 400)

        # account not found
        response = self.client.post(
            '/streamlined_communication/submit_pause_reminder',
            data={
                'block_id': 9999999999,
                'block_type': 'j1',
                'block_dpd': -1
            })
        self.assertEqual(response.status_code, 400)

    @mock.patch('juloserver.streamlined_communication.views.send_user_attributes_to_moengage_for_block_comms')
    def test_submit_pause_reminder_success(self, mock_send_user_attributes_to_moengage_for_block_comms):
        today = timezone.localtime(timezone.now()).date()
        # loan
        ## not comms blocked
        loan = LoanFactory()
        payment = loan.payment_set.order_by('payment_number').first()
        payment.due_date = today + timedelta(days=1)
        payment.save()
        response = self.client.post(
            '/streamlined_communication/submit_pause_reminder',
            data={
                'block_id': loan.id,
                'block_type': 'mtl',
                'comms_block[]': ['email', 'pn'],
                'block_dpd': -1,
                'block_ids[]': [payment.id]
            })
        self.assertEqual(response.status_code, 200)
        comms_blocked = CommsBlocked.objects.filter(loan=loan).first()
        self.assertIsNotNone(comms_blocked)
        self.assertEqual(comms_blocked.is_email_blocked, True)
        self.assertEqual(comms_blocked.is_pn_blocked, True)

        # comms blocked is existed
        response = self.client.post(
            '/streamlined_communication/submit_pause_reminder',
            data={
                'block_id': loan.id,
                'block_type': 'mtl',
                'comms_block[]': ['cootek', 'robocall'],
                'block_dpd': -1,
                'block_ids[]': [payment.id]
            })
        self.assertEqual(response.status_code, 200)
        comms_blocked = CommsBlocked.objects.filter(loan=loan).last()
        self.assertIsNotNone(comms_blocked)
        self.assertEqual(comms_blocked.is_email_blocked, False)
        self.assertEqual(comms_blocked.is_pn_blocked, False)
        self.assertEqual(comms_blocked.is_cootek_blocked, True)
        self.assertEqual(comms_blocked.is_robocall_blocked, True)

        # account
        account = AccountFactory()
        account_payment = AccountPaymentFactory(account=account)
        account_payment.due_date = today + timedelta(days=1)
        account_payment.save()
        response = self.client.post(
            '/streamlined_communication/submit_pause_reminder',
            data={
                'block_id': account.id,
                'block_type': 'j1',
                'comms_block[]': ['email', 'pn'],
                'block_dpd': -1,
                'block_ids[]': [account_payment.id]
            })
        self.assertEqual(response.status_code, 200)
        comms_blocked = CommsBlocked.objects.filter(account=account).first()
        self.assertIsNotNone(comms_blocked)
        self.assertEqual(comms_blocked.is_email_blocked, True)
        self.assertEqual(comms_blocked.is_pn_blocked, True)
        mock_send_user_attributes_to_moengage_for_block_comms.apply_async.assert_called()


class TestViewsPNPermissionAPI(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            id=88888,
            customer=self.customer, workflow=self.workflow,
            account=self.account,
            application_status=StatusLookupFactory(status_code=190)
        )
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_hit_pn_permission_api(self):
        data = {
            "customer_id": self.customer.id,
            "is_pn_permission": True,
            "is_do_not_disturb": True
        }
        response = self.client.post(
            '/api/streamlined_communication/v1/disturb_logging_push_notification_permission',
            data=data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()['data']['message'],
            "Success Insert new row on Push Notification Logging"
        )
        response = self.client.post(
            '/api/streamlined_communication/v1/disturb_logging_push_notification_permission',
            data=data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()['data']['message'],
            "No Change Detected"
        )


class TestViewsNotificationValidity(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code,
            app_version='7.7.0'
        )
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
            parameters={
                'faqs': {
                    'header': 'header',
                    'topics': [{
                        'question': 'question test 1',
                        'answer': 'answer test 1'
                    }]
                }
            }
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name=JuloCardFeatureNameConst.JULO_CARD_WHITELIST,
        )
        PromoEntryPageFeatureSetting()
        JuloCardWhitelistUserFactory(
            application=self.application
        )
        self.cfs_tier = CfsTierFactory(id=1, name='Advanced', point=300, julo_card=True)
        self.mbs = MobileFeatureSettingFactory(
            feature_name=LoanJuloOneConstant.PRODUCT_LOCK_FEATURE_SETTING,
            is_active=True,
            parameters={"credit_card": {"locked": True, "app_version": "6.5.0"}}
        )
        credit_card_application = create_mock_credit_card_application(
            CreditCardCodes.CARD_ACTIVATED
        )
        credit_card_application.update_safely(account=self.account)
        self.loan = LoanFactory(
            loan_xid=123456,
            transaction_method_id=TransactionMethodCode.CREDIT_CARD.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
            cdate=timezone.localtime(timezone.now()),
            customer=self.customer
        )
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.8)
        self.account_property = AccountPropertyFactory(account=self.account, is_entry_level=True)
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
            parameters={
                'faqs': {
                    'header': 'header',
                    'topics': [{
                        'question': 'question test 1',
                        'answer': 'answer test 1'
                    }]
                },
                "graduation_rules": [
                    {
                        "max_late_payment": 0,
                        "max_account_limit": 300000,
                        "max_grace_payment": 1,
                        "min_account_limit": 100000,
                        "new_account_limit": 500000,
                        "min_percentage_limit_usage": 300,
                        "min_percentage_paid_amount": 100
                    },
                    {
                        "max_late_payment": 0,
                        "max_account_limit": 500000,
                        "max_grace_payment": 1,
                        "min_account_limit": 500000,
                        "new_account_limit": 1000000,
                        "min_percentage_limit_usage": 200,
                        "min_percentage_paid_amount": 100
                    }
                ],
                "is_active_graduation": True,
            }
        )
        self.action_payslip = CfsActionFactory(
            is_active=True,
            action_code='upload_salary_slip',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000,
            app_version='6.0.0',
        )
        self.action_bank_statement = CfsActionFactory(
            is_active=True,
            action_code='upload_bank_statement',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000,
            app_version='6.0.0',
        )
        CfsTierFactory(id=2, name='Starter', point=100, icon='123.pnj', cashback_multiplier=0.5)
        CfsTierFactory(id=3, name='Pro', point=600, icon='123.pnj', cashback_multiplier=0.5)
        CfsTierFactory(id=4, name='Champion', point=1000, icon='123.pnj', cashback_multiplier=0.5)


    @mock.patch('juloserver.julo.models.Application.eligible_for_cfs', new_callable=PropertyMock)
    def test_notification_action(self, mock_cfs_app_eligible):
        mock_cfs_app_eligible.return_value = True
        data = {}
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        assert response.status_code == 400

        data['action'] = "asdf"
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        assert response.status_code == 400

        data['action'] = "cfs"
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        assert response.status_code == 200

        data['action'] = "healthcare_main_page"
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        assert response.status_code == 200

        data['action'] = "loyalty_homepage"
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification', data=data, format='json'
        )
        assert response.status_code == 200

        data['action'] = "qris_main_page"
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        assert response.status_code == 200

    @mock.patch('juloserver.streamlined_communication.services.is_eligible_for_deep_link')
    def test_notification_action_j1_product_deep_link(self, mock_is_eligible_for_deep_link):
        for page_type in J1_PRODUCT_DEEP_LINK_MAPPING_TRANSACTION_METHOD:
            data = {
                'action': page_type
            }

            mock_is_eligible_for_deep_link.return_value = False
            response = self.client.post(
                '/api/streamlined_communication/v1/validate/notification',
                data=data,
                format='json'
            )
            self.assertEqual(200, response.status_code)
            self.assertEqual({'isValid': False}, response.json().get('data'))

            mock_is_eligible_for_deep_link.return_value = True
            response = self.client.post(
                '/api/streamlined_communication/v1/validate/notification',
                data=data,
                format='json'
            )
            self.assertEqual(200, response.status_code)
            self.assertEqual({'isValid': True}, response.json().get('data'))

    @mock.patch(f'{PACKAGE_NAME}.validate_action')
    def test_validate_action_success_julo_shop(self, mock_validate_action):
        mock_validate_action.return_value = True, {'isValid': True}
        url = reverse('streamlined-api:android_check_notification')
        post_data = {
            'action': PageType.JULO_SHOP,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({'isValid': True}, response.data['data'])

    @mock.patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_validate_julo_card_home_page_should_success(self, mock_get_customer_tier_info):
        mock_get_customer_tier_info.return_value = None, self.cfs_tier
        post_data = {
            'action': PageType.JULO_CARD_HOME_PAGE,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': True}, response.data['data'])

    @mock.patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_validate_julo_card_home_page_should_failed_when_tier_is_not_eligible(
            self, mock_get_customer_tier_info
    ):
        self.cfs_tier.update_safely(julo_card=False)
        mock_get_customer_tier_info.return_value = None, self.cfs_tier
        post_data = {
            'action': PageType.JULO_CARD_HOME_PAGE,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    @mock.patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_validate_julo_card_home_page_should_failed_when_user_is_not_whitelisted(
            self, mock_get_customer_tier_info
    ):
        mock_get_customer_tier_info.return_value = None, self.cfs_tier
        self.application.julocardwhitelistuser_set.all().delete()
        post_data = {
            'action': PageType.JULO_CARD_HOME_PAGE,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    @mock.patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_validate_julo_card_home_page_should_failed_when_app_version_is_not_eligible(
            self, mock_get_customer_tier_info
    ):
        self.account.update_safely(app_version='6.4.0')
        mock_get_customer_tier_info.return_value = None, self.cfs_tier
        post_data = {
            'action': PageType.JULO_CARD_HOME_PAGE,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    @mock.patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_validate_julo_card_home_page_should_failed_when_account_status_is_not_420(
            self, mock_get_customer_tier_info
    ):
        mock_get_customer_tier_info.return_value = None, self.cfs_tier
        self.account.update_safely(
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active_in_grace)
        )
        post_data = {
            'action': PageType.JULO_CARD_HOME_PAGE,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    @mock.patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_validate_julo_card_home_page_should_failed_when_application_status_is_not_eligible(
            self, mock_get_customer_tier_info
    ):
        mock_get_customer_tier_info.return_value = None, self.cfs_tier
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.APPLICATION_RESUBMITTED
            )
        )
        post_data = {
            'action': PageType.JULO_CARD_HOME_PAGE,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    @mock.patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_validate_julo_card_home_page_should_failed_when_application_is_not_j1(
            self, mock_get_customer_tier_info
    ):
        mock_get_customer_tier_info.return_value = None, self.cfs_tier
        self.application.update_safely(workflow=WorkflowFactory(name=WorkflowConst.JULOVER))
        post_data = {
            'action': PageType.JULO_CARD_HOME_PAGE,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    def test_validate_julo_card_transaction_completed_success(self):
        action = '{}/{}'.format(PageType.JULO_CARD_TRANSACTION_COMPLETED, self.loan.loan_xid)
        post_data = {
            'action': action,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': True}, response.data['data'])

    def test_validate_julo_card_transaction_completed_should_failed_when_loan_not_found(self):
        Loan.objects.all().delete()
        action = '{}/{}'.format(PageType.JULO_CARD_TRANSACTION_COMPLETED, 123456)
        post_data = {
            'action': action,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    def test_validate_julo_card_choose_tenor_success(self):
        post_data = {
            'action': PageType.JULO_CARD_CHOOSE_TENOR,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': True}, response.data['data'])

    def test_validate_julo_card_choose_tenor_fail_when_loan_status_not_210(self):
        self.loan.update_safely(loan_status_id=LoanStatusCodes.LENDER_APPROVAL)
        self.loan.refresh_from_db()
        post_data = {
            'action': PageType.JULO_CARD_CHOOSE_TENOR,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    def test_validate_julo_card_choose_tenor_fail_when_expire_to_choose_tenor(self):
        datetime_6_minutes_ago = timezone.localtime(timezone.now()) - timedelta(minutes=6)
        self.loan.update_safely(cdate=datetime_6_minutes_ago)
        self.loan.refresh_from_db()
        post_data = {
            'action': PageType.JULO_CARD_CHOOSE_TENOR,
        }
        response = self.client.post(reverse('streamlined-api:android_check_notification'),
                                    data=post_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    def test_validate_valid_action_but_no_condition_logic(self):
        post_data = {
            'action': PageType.LOAN,
        }
        response = self.client.post(
            reverse('streamlined-api:android_check_notification'),
            data=post_data,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': True}, response.data['data'])

    @mock.patch('juloserver.streamlined_communication.views.validate_action')
    def test_invalid_validate_action(self, mock_validate_action):
        post_data = {
            'action': PageType.LOAN,
        }
        mock_validate_action.return_value = False, None
        response = self.client.post(
            reverse('streamlined-api:android_check_notification'),
            data=post_data,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    @mock.patch('juloserver.streamlined_communication.views.validate_action')
    def test_cfs_mission_failed(self, mock_validate_action):
        post_data = {
            'action': PageType.LOAN,
        }
        mock_validate_action.side_effect = MissionEnableStateInvalid()
        response = self.client.post(
            reverse('streamlined-api:android_check_notification'),
            data=post_data,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    @mock.patch('juloserver.streamlined_communication.views.validate_action')
    def test_application_not_found(self, mock_validate_action):
        post_data = {
            'action': PageType.LOAN,
        }
        mock_validate_action.side_effect = ApplicationNotFoundException()
        response = self.client.post(
            reverse('streamlined-api:android_check_notification'),
            data=post_data,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    def test_validate_action_ewallet_success(self):
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_WHITELIST_ELIGIBLE_USER,
            is_active=False,
            parameters={'customer_ids': [self.customer.id]},
        )
        self.fs.is_active = True
        self.fs.save()
        post_data = {'action': PageType.E_WALLET}
        response = self.client.post(
            reverse('streamlined-api:android_check_notification'), data=post_data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': True}, response.data['data'])

    def test_validate_action_ewallet_application_failed(self):
        self.application.update_safely(application_status=StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        ))

        post_data = {'action': PageType.E_WALLET}
        response = self.client.post(
            reverse('streamlined-api:android_check_notification'), data=post_data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    def test_validate_action_ewallet_account_failed(self):
        self.account.update_safely(status=StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.inactive)
        )

        post_data = {'action': PageType.E_WALLET}
        response = self.client.post(
            reverse('streamlined-api:android_check_notification'), data=post_data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    def test_validate_action_ewallet_product_locked_failed(self):
        self.mbs.parameters['dompet_digital'] = {
            'app_version': '7.9.0',
            'locked': True
        }
        self.mbs.save()

        post_data = {'action': PageType.E_WALLET}
        response = self.client.post(
            reverse('streamlined-api:android_check_notification'), data=post_data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    def test_validate_action_promo_entry_page(self):
        data = {'action': PageType.PROMO_ENTRY_PAGE}
        self.application.update_safely(product_line_id=ProductLineCodes.J1)
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': True}, response.json().get('data'))

    @patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    def test_validate_action_mission_payslip(self, mock_boost_mobile_setting):
        mock_boost_mobile_setting.return_value.parameters = {
            "bank": {
                'is_active': True,
            },
            "bpjs": {
                'is_active': True,
            },
        }
        data = {'action': PageType.UPLOAD_SALARY_SLIP}
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': False}, response.json().get('data'))

        self.application.update_safely(product_line_id=ProductLineCodes.J1)
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': True}, response.json().get('data'))

        action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.action_payslip, extra_data={},
            progress_status=CfsProgressStatus.PENDING)
        CfsAssignmentVerificationFactory(cfs_action_assignment=action_assignment)

        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': False}, response.json().get('data'))

    @patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    def test_validate_action_bank_statement(self, mock_boost_mobile_setting):
        mock_boost_mobile_setting.return_value.parameters = {
            "bank": {
                'is_active': True,
            },
            "bpjs": {
                'is_active': True,
            },
        }
        data = {'action': PageType.UPLOAD_BANK_STATEMENT}
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': False}, response.json().get('data'))

        self.application.update_safely(product_line_id=ProductLineCodes.J1)
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': True}, response.json().get('data'))

        action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.action_bank_statement, extra_data={},
            progress_status=CfsProgressStatus.PENDING)
        CfsAssignmentVerificationFactory(cfs_action_assignment=action_assignment)

        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification',
            data=data,
            format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': False}, response.json().get('data'))

    def test_validate_action_transaction_status(self):
        loan_xid = self.loan.loan_xid
        data = {"action": "transaction_status/{}".format(loan_xid)}
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification', data=data, format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': True}, response.json().get('data'))

    def test_validate_checkout_has_active_loan(self):
        self.loan.update_safely(loan_status_id=LoanStatusCodes.LOAN_1DPD)
        post_data = {
            'action': PageType.CHECKOUT,
        }
        response = self.client.post(
            reverse('streamlined-api:android_check_notification'), data=post_data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': True}, response.data['data'])

    def test_validate_checkout_has_no_active_loan(self):
        self.user.customer.loan_set.all().update(loan_status_id=LoanStatusCodes.PAID_OFF)
        post_data = {
            'action': PageType.CHECKOUT,
        }
        response = self.client.post(
            reverse('streamlined-api:android_check_notification'), data=post_data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual({'isValid': False}, response.data['data'])

    def test_validate_action_julo_financing_success(self):
        data = {"action": PageType.JULO_FINANCING}
        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification', data=data, format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': True}, response.json().get('data'))

    def test_validate_action_julo_financing_product(self):
        # set up
        product = JFinancingProductFactory(is_active=True)

        # case failed, doesn't match pattern (due to negative number)
        fake_product_id = -1
        data = {"action": "{}/{}".format(PageType.JULO_FINANCING, fake_product_id)}

        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification', data=data, format='json'
        )
        self.assertEqual(400, response.status_code)

        # case not found product id
        fake_product_id = 9999
        data = {"action": "{}/{}".format(PageType.JULO_FINANCING, fake_product_id)}

        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification', data=data, format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': False}, response.json().get('data'))

        # case successful
        data = {"action": "{}/{}".format(PageType.JULO_FINANCING, product.id)}

        response = self.client.post(
            '/api/streamlined_communication/v1/validate/notification', data=data, format='json'
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({'isValid': True}, response.json().get('data'))


class TestUpdateEmailDetails(TestCase):
    def setUp(self):
        group = Group(name="product_manager")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.data = dict(
            email_category='normal',
            email_type='Payment Reminder',
            email_product='J1',
            email_hour=18,
            email_minute=0,
            email_subject='Payment Reminder A',
            email_template_code='some_template_code_a',
            email_moengage_template_code='',
            email_content='This is email content',
            email_description='This is a payment reminder comm.',
            email_msg_id='',
            email_parameters='',
            communication_platform='EMAIL',
            dpd=-2,
            ptp='',
            application_status='',
            pre_header='This is pre header',
            partners_selection='',
            partners_selection_action=''
        )
        self.streamlined_comm = StreamlinedCommunicationFactory(
            template_code='some_template_code_0',
            moengage_template_code='some_template_code_moe_0',
            dpd=-2,
            ptp=None,
            communication_platform=CommunicationPlatform.EMAIL
        )

    def test_update_email_details_create_normal(self):
        response = self.client.post(
            '/streamlined_communication/update_email_details',
            data=self.data
        )
        response_json = response.json()['data']

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual('Email details added successfully', response_json['msg'])
        self.assertTrue('Success', response_json['status'])

    def test_update_email_details_create_backup(self):
        self.data['email_category'] = 'backup'
        self.data['email_moengage_template_code'] = 'some_template_code_moe_a'
        response = self.client.post(
            '/streamlined_communication/update_email_details',
            data=self.data
        )
        response_json = response.json()['data']

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual('Email details added successfully', response_json['msg'])
        self.assertTrue('Success', response_json['status'])

    def test_update_email_details_update_existing(self):
        self.data['email_msg_id'] = self.streamlined_comm.pk
        response = self.client.post(
            '/streamlined_communication/update_email_details',
            data=self.data
        )
        response_json = response.json()['data']

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual('Email details updated successfully', response_json['msg'])
        self.assertTrue('Success', response_json['status'])

    def test_update_email_details_update_non_existing(self):
        self.data['email_msg_id'] = '99999'
        response = self.client.post(
            '/streamlined_communication/update_email_details',
            data=self.data
        )
        response_json = response.json()['data']

        self.assertEqual('Template not exists', response_json['msg'])
        self.assertTrue('Failure', response_json['status'])

    def test_update_email_details_create_duplicate_template_code_fail(self):
        self.data['email_template_code'] = 'some_template_code_0'
        response = self.client.post(
            '/streamlined_communication/update_email_details',
            data=self.data
        )
        response_json = response.json()['data']

        self.assertEqual('Template Code already exists', response_json['msg'])
        self.assertTrue('Failure', response_json['status'])

    def test_update_email_details_create_backup_no_moengage_template_code(self):
        self.data['email_category'] = 'backup'
        self.data.pop('email_moengage_template_code')
        response = self.client.post(
            '/streamlined_communication/update_email_details',
            data=self.data
        )
        response_json = response.json()['data']

        self.assertEqual('Backup email must have moengage template code', response_json['msg'])
        self.assertTrue('Failure', response_json['status'])

class TestUpdatePnDetails(TestCase):
    def setUp(self):
        group = Group(name="product_manager")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        self.client.force_login(self.user)


    @mock.patch('juloserver.streamlined_communication.views.upload_image_assets_for_streamlined_pn')
    def test_update_pn_details_with_image(self, mock_upload_image_assets):
        image = (io.BytesIO(b"test"), 'test.png')

        data = {
            'pn_category': 'normal',
            'pn_type': 'Payment Reminder',
            'pn_product': 'stl',
            'pn_hour': '16',
            'pn_minute': '30',
            'pn_template_code': 'test_pn',
            'pn_moengage_template_code': '',
            'pn_subject': 'test pn_title',
            'pn_content': 'test content',
            'pn_heading': 'test pn',
            'pn_description': 'test description',
            'pn_parameters': '',
            'dpd': '-10',
            'dpd_upper': '',
            'dpd_lower': '',
            'until_paid': 'on',
            'ptp': '',
            'application_status': '',
            'pn_msg_id': '',
            'pn_image': image,
        }
        mock_upload_image_assets.return_value = True

        response = self.client.post('/streamlined_communication/update_pn_details', data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestViewsNeoBannerCard(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.info_card = NeoBannerCardFactory()
        self.application = ApplicationFactory(
            customer=self.customer, workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.IDFY_VIDEO_CALL_HOURS,
            is_active=True,
            parameters={
                'weekdays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 0,
                    }
                },
                'holidays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 30,
                    }
                }
            }
        )
        self.ios_id = 'E78E234E-4981-4BB7-833B-2B6CEC2F56DF'
        self.new_device_header = {
            IdentifierKeyHeaderAPI.X_DEVICE_ID: self.ios_id,
            IdentifierKeyHeaderAPI.X_PLATFORM: 'iOS',
            IdentifierKeyHeaderAPI.X_PLATFORM_VERSION: '18.0.1',
        }

    @patch('django.utils.timezone.now')
    def test_view_neo_banner_card(self, mock_timezone):

        # override today time zone
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)

        NeoBannerCardFactory(
            product='J1',
            statuses='[100_VIDEO_CALL]',
            template_card='B_BUTTON',
            top_info_message='Top info message',
            top_info_title='Top info title',
            is_active=True,
        )

        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.save()

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'

        response = self.client.get(neo_banner_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)

        self.application.application_status = StatusLookupFactory(status_code=109)
        self.application.save()

        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['cards'], None)

        self.application.delete()

        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['cards'], None)

    @patch('django.utils.timezone.now')
    def test_view_video_call_neo_banner(self, mock_timezone):

        # override today time zone
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        NeoBannerCardFactory(
            product='J1',
            statuses='[100_FORM]',
            template_card='B_BUTTON',
            is_active=True,
        )

        NeoBannerCardFactory(
            product='J1',
            statuses='[100_VIDEO_CALL]',
            template_card='B_BUTTON',
            top_info_message='Top info message',
            top_info_title='Top info title',
            is_active=True,
        )

        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.save()

        top_info_message = 'Senin-Jumat: 08:00-20:00 <br>Sabtu-Minggu/Libur Nasional: 08:00-20:30'

        # no IDFY record case
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertEqual(response.json()['data']['cards']['template_card'],'B_BUTTON')
        self.assertEqual(response.json()['data']['cards']['top_info_icon'], None)
        self.assertEqual(response.json()['data']['cards']['top_info_message'], top_info_message)
        self.assertEqual(response.json()['data']['cards']['top_info_title'], 'Top info title')
        self.assertIn('100_VIDEO_CALL', response.json()['data']['cards']['statuses'])

        # IDFY record status = in_progress case
        self.video_call_record = IdfyVideoCallFactory(
            application_id=self.application.id,
            status='in_progress',
        )

        response = self.client.get(neo_banner_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertEqual(response.json()['data']['cards']['template_card'],'B_BUTTON')
        self.assertEqual(response.json()['data']['cards']['top_info_icon'], None)
        self.assertEqual(response.json()['data']['cards']['top_info_message'], top_info_message)
        self.assertEqual(response.json()['data']['cards']['top_info_title'], 'Top info title')
        self.assertIn('100_VIDEO_CALL', response.json()['data']['cards']['statuses'])

        # IDFY record status = completed case
        self.video_call_record.status = 'completed'
        self.video_call_record.save()
        self.video_call_record.refresh_from_db()

        response = self.client.get(neo_banner_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertEqual(response.json()['data']['cards']['template_card'],'B_BUTTON')
        self.assertEqual(response.json()['data']['cards']['top_info_icon'], None)
        self.assertEqual(response.json()['data']['cards']['top_info_message'], None)
        self.assertEqual(response.json()['data']['cards']['top_info_title'], None)
        self.assertNotIn('100_VIDEO_CALL', response.json()['data']['cards']['statuses'])
        self.assertIn('100_FORM', response.json()['data']['cards']['statuses'])

    @patch('django.utils.timezone.now')
    def test_view_video_call_neo_banner_no_get_idfy(self, mock_timezone):

        # override today time zone
        # 7am and no have record IDFy should be no get IDFy Banner
        mock_timezone.return_value = datetime(2023, 10, 10, 7, 0, 0)

        NeoBannerCardFactory(
            product='J1',
            statuses='[100_FORM]',
            template_card='B_BUTTON',
            is_active=True,
        )

        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.save()

        # no IDFY record case
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertNotIn('100_FORM', response.json()['data']['cards']['statuses'])

    @patch('django.utils.timezone.now')
    def test_view_video_call_neo_banner_get_idfy(self, mock_timezone):

        # override today time zone
        # 8am and no have record IDFy should be get IDFy Banner
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)

        NeoBannerCardFactory(
            product='J1',
            statuses='[100_VIDEO_CALL]',
            template_card='B_BUTTON',
            top_info_message='Top info message',
            top_info_title='Top info title',
            is_active=True,
        )

        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.save()

        # no IDFY record case
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_VIDEO_CALL', response.json()['data']['cards']['statuses'])

    @patch('django.utils.timezone.now')
    def test_view_video_call_neo_banner_no_get_idfy(self, mock_timezone):

        # override today time zone
        # 9pm and no have record IDFy should be get IDFy Banner
        mock_timezone.return_value = datetime(2023, 10, 10, 21, 0, 0)

        NeoBannerCardFactory(
            product='J1',
            statuses='[100_VIDEO_CALL]',
            template_card='B_BUTTON',
            top_info_message='Top info message',
            top_info_title='Top info title',
            is_active=True,
        )

        NeoBannerCardFactory(
            product='J1',
            statuses='[100_FORM]',
            template_card='B_BUTTON',
            is_active=True,
        )

        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.save()

        # IDFY record status = in_progress case
        self.video_call_record = IdfyVideoCallFactory(
            application_id=self.application.id,
            status='in_progress',
        )

        # no IDFY record case
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_FORM', response.json()['data']['cards']['statuses'])

        # 18am and no have record IDFy should be get IDFy Banner
        mock_timezone.return_value = datetime(2023, 10, 10, 15, 0, 0)

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_VIDEO_CALL', response.json()['data']['cards']['statuses'])

        # update the idfy case if already completed video call should be cannot get banner idfy
        self.video_call_record.update_safely(status='completed')
        self.video_call_record.refresh_from_db()

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertNotIn('100_VIDEO_CALL', response.json()['data']['cards']['statuses'])

    @patch('django.utils.timezone.now')
    def test_view_video_call_neo_banner_rule_time(self, mock_timezone):

        # override today time zone
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        NeoBannerCardFactory(
            product='J1',
            statuses='[100_VIDEO_CALL]',
            template_card='B_BUTTON',
            top_info_message='Top info message',
            top_info_title='Top info title',
            is_active=True,
        )

        NeoBannerCardFactory(
            product='J1',
            statuses='[100_FORM]',
            template_card='B_BUTTON',
            is_active=True,
        )

        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.save()

        # IDFY record status = in_progress case
        self.video_call_record = IdfyVideoCallFactory(
            application_id=self.application.id,
            status='in_progress',
        )

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_VIDEO_CALL', response.json()['data']['cards']['statuses'])

        # 20.01  and no have record IDFy should be get IDFy Banner
        mock_timezone.return_value = datetime(2023, 10, 10, 20, 1, 0)
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_FORM', response.json()['data']['cards']['statuses'])

        mock_timezone.return_value = datetime(2023, 10, 10, 7, 59, 0)
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_FORM', response.json()['data']['cards']['statuses'])

        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_VIDEO_CALL', response.json()['data']['cards']['statuses'])

        # if feature setting active
        self.fs.parameters={
                'weekdays': {
                    'open': {
                        'hour': 5,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 17,
                        'minute': 0,
                    }
                },
                'holidays': {
                    'open': {
                        'hour': 12,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 15,
                        'minute': 30,
                    }
                }
            }
        self.fs.save()

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_VIDEO_CALL', response.json()['data']['cards']['statuses'])
        self.assertEqual(f'Senin-Jumat: 05:00-17:00 <br>Sabtu-Minggu/Libur Nasional: 12:00-15:30', response.json()['data']['cards']['top_info_message'])

        # weekend hours = weekdays hours
        self.fs.parameters = {
                'weekdays': {
                    'open': {
                        'hour': 5,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 17,
                        'minute': 0,
                    }
                },
                'holidays': {
                    'open': {
                        'hour': 5,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 17,
                        'minute': 0,
                    }
                }
            }
        self.fs.save()

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(f'Senin-Minggu/Libur Nasional: 05:00-17:00', response.json()['data']['cards']['top_info_message'])

        # update the idfy case if already completed video call should be cannot get banner idfy
        self.video_call_record.update_safely(status='completed')
        self.video_call_record.refresh_from_db()
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_FORM', response.json()['data']['cards']['statuses'])

    @patch('django.utils.timezone.now')
    def test_view_neo_banner_for_x100(self, mock_timezone):

        # 21am and no have record IDFy should be get IDFy Banner
        mock_timezone.return_value = datetime(2023, 10, 10, 21, 0, 0)

        NeoBannerCardFactory(
            product='J1',
            statuses='[100_FORM]',
            template_card='B_BUTTON',
            is_active=True,
        )

        NeoBannerCardFactory(
            product='J1',
            statuses='[106_CANNOT_REAPPLY]',
            template_card='B_BUTTON',
            is_active=True,
        )

        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=106)
        )

        # create new application
        self.new_application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
        )
        self.new_application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED
        )

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_FORM', response.json()['data']['cards']['statuses'])

    @patch('django.utils.timezone.now')
    def test_view_neo_banner_for_continue_form_or_video(self, mock_timezone):

        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        NeoBannerCardFactory(
            product='J1',
            statuses='[100_VIDEO_CALL]',
            template_card='B_BUTTON',
            is_active=True,
        )
        NeoBannerCardFactory(
            product='J1',
            statuses='[100_FORM]',
            template_card='B_BUTTON',
            is_active=True,
        )
        NeoBannerCardFactory(
            product='J1',
            statuses=NeoBannerStatusesConst.FORM_OR_VIDEO_CALL_STATUSES,
            template_card='B_BUTTON',
            is_active=True,
        )

        app_version = '8.15.0'
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'

        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=100)
        )
        self.video_call_record = IdfyVideoCallFactory(
            application_id=self.application.id,
            status=LabelFieldsIDFyConst.KEY_IN_PROGRESS,
        )

        response = self.client.get(neo_banner_url, HTTP_X_APP_VERSION=app_version)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertEqual(
            response.json()['data']['cards']['statuses'],
            NeoBannerStatusesConst.FORM_OR_VIDEO_CALL_STATUSES,
        )

        # lower version should be get 100_FORM
        app_version = '8.13.1'
        response = self.client.get(neo_banner_url, HTTP_X_APP_VERSION=app_version)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertEqual(response.json()['data']['cards']['statuses'], '[100_VIDEO_CALL]')

        # set IDFy Video Call is complete
        app_version = '8.12.1'
        self.video_call_record.update_safely(status=LabelFieldsIDFyConst.KEY_COMPLETED)
        response = self.client.get(neo_banner_url, HTTP_X_APP_VERSION=app_version)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['cards']['statuses'], '[100_FORM]')

        app_version = '8.15.2'
        response = self.client.get(neo_banner_url, HTTP_X_APP_VERSION=app_version)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()['data']['cards']['statuses'], '[100_FORM]',
        )

    @patch('django.utils.timezone.now')
    @patch(
        'juloserver.streamlined_communication.services.is_agent_assisted_submission_flow',
        return_value=True,
    )
    def test_neo_banner_for_assisted_agent_submission(self, mocking_path_tag, mock_date_time):

        time_now = datetime(2023, 10, 10, 8, 0, 0)
        mock_date_time.return_value = time_now
        get_today = timezone.localtime(timezone.now())

        NeoBannerCardFactory(
            product='J1',
            statuses=[AgentAssistedSubmissionConst.STATUS_IN_NEO_BANNER],
            template_card='B_BUTTON',
            button_text='Lihat Kebijakan Privasi',
            button_action='{{link}}',
            is_active=True,
        )

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL
        )
        self.application.is_term_accepted = False
        self.application.is_verification_agreed = False
        self.application.application_xid = 123131321
        self.application.save()

        expire_time = get_today + timedelta(
            hours=AgentAssistedSubmissionConstForm.TOKEN_EXPIRE_HOURS
        )
        web_token = generate_web_token(expire_time, self.application.application_xid)

        self.web_token = AgentAssistedWebTokenFactory(
            application_id=self.application.id,
            session_token=web_token,
            expire_time=expire_time,
            is_active=True,
        )

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['cards']['button_text'], 'Lihat Kebijakan Privasi')
        self.assertIn(
            AgentAssistedSubmissionConst.STATUS_IN_NEO_BANNER,
            response.json()['data']['cards']['statuses'],
        )

    @patch('django.utils.timezone.now')
    @patch(
        'juloserver.streamlined_communication.services.is_agent_assisted_submission_flow',
        return_value=False,
    )
    def test_neo_banner_for_assisted_agent_submission_already_approve_tnc(
        self, mocking_path_tag, mock_date_time
    ):

        time_now = datetime(2023, 10, 10, 8, 0, 0)
        mock_date_time.return_value = time_now
        get_today = timezone.localtime(timezone.now())

        NeoBannerCardFactory(
            product='J1',
            statuses=[AgentAssistedSubmissionConst.STATUS_IN_NEO_BANNER],
            template_card='B_BUTTON',
            button_text='Lihat Kebijakan Privasi',
            button_action='{{link}}',
            is_active=True,
        )

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL
        )
        self.application.application_xid = 123131321
        self.application.save()

        expire_time = get_today + timedelta(
            hours=AgentAssistedSubmissionConstForm.TOKEN_EXPIRE_HOURS
        )
        web_token = generate_web_token(expire_time, self.application.application_xid)

        self.web_token = AgentAssistedWebTokenFactory(
            application_id=self.application.id,
            session_token=web_token,
            expire_time=expire_time,
            is_active=True,
        )

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['cards'], None)

    def test_view_video_call_neo_banner_get_x100_for_ios(self):

        NeoBannerCardFactory(
            product='J1',
            statuses='[100_FORM]',
            template_card='B_BUTTON',
            top_info_message='Top info message',
            top_info_title='Top info title',
            is_active=True,
        )

        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE_IOS)
        self.application.save()

        # no IDFY record case
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.json()['data']['cards']), 1)
        self.assertIn('100_FORM', response.json()['data']['cards']['statuses'])

    def test_view_neo_banner_reapply_for_ios_device(self):

        default_btn_action = 'reapply_for_j1'
        expected_btn_action = 'reapply_form'

        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=106,
        )
        NeoBannerCardFactory(
            product='J1',
            statuses='[106_REAPPLY, 136_REAPPLY]',
            template_card='B_BUTTON',
            is_active=True,
            button_action=default_btn_action,
        )

        self.application.application_status = StatusLookupFactory(status_code=106)
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE_IOS)
        self.application.save()
        self.customer.update_safely(can_reapply=True)

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url, **self.new_device_header)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['cards']['button_action'], expected_btn_action)

    @patch(
        'juloserver.application_flow.services.is_available_session_check_hsfbp', return_value=False
    )
    @patch(
        'juloserver.streamlined_communication.services.is_hsfbp_hold_with_status', return_value=True
    )
    def test_view_neo_banner_for_120_hsfbp_for_android_or_ios(
        self, mock_is_hsfbp_hold, mock_is_available_session_check
    ):

        default_btn_action = 'x120_HSFBP'
        NeoBannerCardFactory(
            product='J1',
            statuses='[120_HSFBP]',
            template_card='B_BUTTON',
            is_active=True,
            button_action=default_btn_action,
        )
        tag = 'is_hsfbp'
        app_version_header = {
            'HTTP_X_APP_VERSION': '8.49.0',
        }
        ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=ApplicationPathTagStatusFactory(
                application_tag=tag, status=1, definition="success"
            ),
        )

        ExperimentSettingFactory(
            code=ExperimentConst.HSFBP_INCOME_VERIFICATION,
            criteria={"app_id": [0, 1], "x120_hsfbp_expiry": 1, "android_app_version": ">=8.49.0"},
            is_active=True,
            is_permanent=False,
        )

        self.application.application_status = StatusLookupFactory(status_code=120)
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application.save()

        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url, **app_version_header)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['cards']['button_action'], default_btn_action)

        # check hit by iOS App
        self.new_device_header.update(app_version_header)
        neo_banner_url = '/api/streamlined_communication/v1/android_neo_banner_card'
        response = self.client.get(neo_banner_url, **self.new_device_header)
        self.assertIsNone(response.json()['data']['cards'])


class TestGrabInfoCardAPI(APITestCase):
    def setUp(self):
        self.info_card_url = '/api/partner/grab/common/info_cards'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True
        )
        self.application = ApplicationFactory(
            id=77777,
            customer=self.customer, workflow=self.workflow,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.loan = LoanFactory(account=self.account)
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id, score='A')
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
                                HTTP_X_APP_VERSION='7.7.0')
        self.name_bank_validation = NameBankValidationFactory(bank_code='HELLOQWE')
        self.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup,
            loan_status=self.loan_status,
            sphp_accepted_ts=timezone.localtime(timezone.now() - timedelta(days=6))
        )
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan,
        )


    def test_success_grab_info_card_210_auth_pending(self):
        auth_pending_title = 'Dalam proses verifikasi ⏳'
        auth_pending_content = 'Data pengajuan Anda telah diterima dan sedang diverifikasi. Silahkan kembali dalam satu hari kerja untuk memeriksa status pengajuan Anda.'
        info_card_pending = InfoCardPropertyFactory(title=auth_pending_title)
        streamlined_message_pending = StreamlinedMessageFactory(
            message_content=auth_pending_content,
            info_card_property=info_card_pending
        )
        StreamlinedCommunicationFactory(
            message=streamlined_message_pending,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=LoanStatusCodes.INACTIVE,
            extra_conditions=CardProperty.GRAB_INFO_CARD_AUTH_PENDING,
            is_active=True
        )
        self.application.update_safely(application_status_id=ApplicationStatusCodes.LOC_APPROVED)
        response = self.client.get(self.info_card_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)
        self.assertEqual(response.json()['data']['cards'][0]['title']['text'],auth_pending_title)


    def test_success_grab_info_card_219_auth_failed(self):
        auth_failed_client = APIClient()
        auth_failed_user = AuthUserFactory()
        auth_failed_customer = CustomerFactory(user=auth_failed_user)
        auth_failed_account_lookup = AccountLookupFactory(workflow=self.workflow)
        auth_failed_account = AccountFactory(
            customer=auth_failed_customer,
            account_lookup=auth_failed_account_lookup
        )
        auth_failed_application = ApplicationFactory(
            customer=auth_failed_customer, workflow=self.workflow,
            account=auth_failed_account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        auth_failed_client.credentials(HTTP_AUTHORIZATION='Token ' + auth_failed_user.auth_expiry_token.key,
                                HTTP_X_APP_VERSION='7.7.0')
        auth_failed_name_bank_validation = NameBankValidationFactory(bank_code='FAILED_HELLOQWE')
        auth_failed_loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LENDER_REJECT)
        auth_failed_loan = LoanFactory(
            account=auth_failed_account,
            customer=auth_failed_customer,
            name_bank_validation_id=auth_failed_name_bank_validation.id,
            product=self.product_lookup,
            loan_status=auth_failed_loan_status,
            sphp_accepted_ts=timezone.localtime(timezone.now() - timedelta(days=6))
        )
        auth_failed_title = 'Mohon maaf 🙏'
        auth_failed_content = 'Permohonan Anda belum dapat disetujui untuk saat ini karena belum memenuhi kriteria yang ada.'
        auth_failed_info_card_property = InfoCardPropertyFactory(title=auth_failed_title)
        auth_failed_streamlined_message = StreamlinedMessageFactory(
            message_content=auth_failed_content,
            info_card_property=auth_failed_info_card_property
        )
        StreamlinedCommunicationFactory(
            message=auth_failed_streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=LoanStatusCodes.LENDER_REJECT,
            extra_conditions=CardProperty.GRAB_INFO_CARD_AUTH_FAILED,
            is_active=True
        )

        GrabAPILogFactory(
            customer_id=auth_failed_customer.id,
            loan_id=auth_failed_loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=HTTPStatus.BAD_GATEWAY
        )

        auth_failed_application.update_safely(application_status_id=ApplicationStatusCodes.LOC_APPROVED)
        response = auth_failed_client.get(self.info_card_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)
        self.assertEqual(response.json()['data']['cards'][0]['title']['text'], auth_failed_title)


    def test_success_grab_info_card_219_auth_failed_with_4002_error(self):
        auth_failed_4002_client = APIClient()
        auth_failed_4002_user = AuthUserFactory()
        auth_failed_4002_customer = CustomerFactory(user=auth_failed_4002_user)
        auth_failed_4002_account_lookup = AccountLookupFactory(workflow=self.workflow)
        auth_failed_4002_account = AccountFactory(
            customer=auth_failed_4002_customer,
            account_lookup=auth_failed_4002_account_lookup
        )
        auth_failed_4002_application = ApplicationFactory(
            customer=auth_failed_4002_customer, workflow=self.workflow,
            account=auth_failed_4002_account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        auth_failed_4002_client.credentials(HTTP_AUTHORIZATION='Token ' + auth_failed_4002_user.auth_expiry_token.key,
                                HTTP_X_APP_VERSION='7.7.0')
        auth_failed_4002_name_bank_validation = NameBankValidationFactory(bank_code='FAILED_4002_HELLOQWE')
        auth_failed_4002_loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LENDER_REJECT)
        auth_failed_4002_loan = LoanFactory(
            account=auth_failed_4002_account,
            customer=auth_failed_4002_customer,
            name_bank_validation_id=auth_failed_4002_name_bank_validation.id,
            product=self.product_lookup,
            loan_status=auth_failed_4002_loan_status,
            sphp_accepted_ts=timezone.localtime(timezone.now() - timedelta(days=6))
        )
        auth_failed_4002_title = 'Pengajuan Kamu Gagal'
        auth_failed_4002_content = 'Pastikan nomor HP yang kamu gunakan di GrabModal dan aplikasi driver sama. Kamu bisa ubah nomor HP GrabModal kamu lewat halaman Profil, ya.'
        auth_failed_4002_info_card_property = InfoCardPropertyFactory(title=auth_failed_4002_title)
        auth_failed_4002_streamlined_message = StreamlinedMessageFactory(
            message_content=auth_failed_4002_content,
            info_card_property=auth_failed_4002_info_card_property
        )
        StreamlinedCommunicationFactory(
            message=auth_failed_4002_streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD,
            status_code_id=LoanStatusCodes.LENDER_REJECT,
            extra_conditions=CardProperty.GRAB_INFO_CARD_AUTH_FAILED_4002,
            is_active=True
        )

        GrabAPILogFactory(
            customer_id=auth_failed_4002_customer.id,
            loan_id=auth_failed_4002_loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=HTTPStatus.BAD_GATEWAY,
            external_error_code=4002
        )

        auth_failed_4002_application.update_safely(application_status_id=ApplicationStatusCodes.LOC_APPROVED)
        response = auth_failed_4002_client.get(self.info_card_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['cards']), 1)
        self.assertEqual(response.json()['data']['cards'][0]['title']['text'], auth_failed_4002_title)



class TestIpaBannerAPI(APITestCase):
    def setUp(self):
        self.url = '/api/streamlined_communication/v1/android_ipa_banner'
        self.url_v2 = '/api/streamlined_communication/v2/android_ipa_banner'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)

        self.fdc_inquiry = FDCInquiryFactory(
            customer_id=self.customer.id,
            inquiry_status='success',
            inquiry_date=self.customer.cdate,
        )

        self.fdc_inquiry_loan = FDCInquiryLoanFactory(
            fdc_inquiry_id=self.fdc_inquiry.id,
            no_identitas=self.customer.nik,
            tgl_pelaporan_data = self.customer.cdate,
            tgl_jatuh_tempo_pinjaman=self.customer.cdate - relativedelta(days=2),
        )

        self.app_version = '8.9.0'

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE,)
        self.onboarding = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        self.application = ApplicationFactory(
            customer=self.customer,
            onboarding=self.onboarding,
            workflow=self.workflow,
        )

        self.application.application_status_id=ApplicationStatusCodes.FORM_CREATED
        self.application.save()

        self.fs = FeatureSettingFactory(
            feature_name= 'ipa_banner_v2',
            is_active= True,
            parameters= {
                "experiment": {
                    "high_fdc": {
                        "title": "This is title for EXPERIMENT HIGH",
                        "message": "Kamu bisa banget dapat limit lebih besar, lho. Yuk, lengkapi data diri kamu sekarang!",
                        "link_image": "/info-card/IPA_BANNER_V2_GOOD_FDC.png",
                        "link_sticky_bar": "info-card/STICKY_BANNER_GOOD_FDC_EXP.png",
                    },
                    "medium_fdc": {
                        "title": "This is title for EXPERIMENT MEDIUM",
                        "message": "Raih kesempatanmu untuk dapat limit! Lengkapi dulu data diri kamu di bawah ini, ya.",
                        "link_image": "/info-card/IPA_BANNER_V2_MEDIUM_FDC.png",
                        "link_sticky_bar": "info-card/STICKY_BANNER_MEDIUM_FDC_EXP.png",
                    }
                },
                "control": {
                    "high_fdc": {
                        "title": "This is title for CONTROL HIGH",
                        "message": "Kamu bisa banget dapat limit lebih besar, lho. Yuk, lengkapi data diri kamu sekarang!",
                        "link_image": "/info-card/IPA_BANNER_V2_GOOD_FDC.png",
                        "link_sticky_bar": "info-card/STICKY_BANNER_GOOD_FDC_CTRL.png",
                    },
                    "medium_fdc": {
                        "title": "This is title for CONTROL MEDIUM",
                        "message": "Raih kesempatanmu untuk dapat limit! Lengkapi dulu data diri kamu di bawah ini, ya.",
                        "link_image": "/info-card/IPA_BANNER_V2_MEDIUM_FDC.png",
                        "link_sticky_bar": "info-card/STICKY_BANNER_MEDIUM_FDC_CTRL.png",
                    },
                },
            },
        )

        self.eligible_data = EligibleCheckFactory(
            application_id=self.application.id,
            check_name='eligible_good_fdc_x100',
            is_okay=True,
        )

        self.ExperimentSetting = ExperimentSettingFactory(
            code="FDCIPABannerExperimentV2",
            name='IPA Banner Experiment V2',
            type='IPA Banner',
            criteria={"customer_id": [0, 2, 4, 6, 8], "target_version": ">=8.9.0"},
            is_active=True,
            is_permanent=True,
            start_date=timezone.now(),
            end_date=timezone.now() + relativedelta(year=1),
        )

        criteria_v3 = {
            "customer_id": {
                'no_stickybar': [1, 2],
                'all_component': [4, 5, 6],
                'no_banner': [7, 8, 9],
            },
            "target_version": ">=8.34.0",
        }

        self.ExperimentSettingV3 = ExperimentSettingFactory(
            code="FDCIPABannerExperimentV3",
            name='IPA Banner Experiment V3',
            type='IPA Banner',
            criteria=criteria_v3,
            is_active=True,
            is_permanent=True,
            start_date=timezone.now(),
            end_date=timezone.now() + relativedelta(year=1),
        )

    @patch('juloserver.streamlined_communication.services.determine_ipa_banner_experiment', return_value=True)
    def test_show_ipa_banner(self, mock_determine_experiment):
        # case pass check
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Lancar (<30 hari)'
        self.fdc_inquiry_loan.save()

        response = self.client.get(self.url, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        self.assertTrue(data['show_ipa_banner'])

        # case max dpd < 90
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Tidak Lancar (30 sd 90 hari)'
        self.fdc_inquiry_loan.save()

        response = self.client.get(self.url, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        self.assertTrue(data['show_ipa_banner'])

        # case sisa pinjaman = 0 and dpd > 90
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Macet (>90)'
        self.fdc_inquiry_loan.nilai_pendanaan = 10000
        self.fdc_inquiry_loan.sisa_pinjaman_berjalan = 0
        self.fdc_inquiry_loan.save()

        response = self.client.get(self.url, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        self.assertTrue(data['show_ipa_banner'])

        # case sisa pinjaman > 0 and dpd > 90
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Macet (>90)'
        self.fdc_inquiry_loan.nilai_pendanaan = 10000
        self.fdc_inquiry_loan.sisa_pinjaman_berjalan = 10000
        self.fdc_inquiry_loan.save()

        response = self.client.get(self.url, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        self.assertFalse(data['show_ipa_banner'])

        # case fdc no fdc data
        self.fdc_inquiry_loan.delete()
        response = self.client.get(self.url, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        self.assertFalse(data['show_ipa_banner'])

    def test_show_ipa_banner_v2_high_banner(self):

        # case control
        self.user_control = AuthUserFactory()
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user_control.auth_expiry_token.key
        )
        self.customer_control = CustomerFactory(id=1, user=self.user_control)
        expected_sticky_url = get_oss_public_url(
            settings.OSS_PUBLIC_ASSETS_BUCKET, 'info-card/STICKY_BANNER_GOOD_FDC_CTRL.png'
        )

        self.application.customer = self.customer_control
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(
            response.json()['data']['message']['title'], 'This is title for CONTROL HIGH'
        )
        self.assertEqual(response.status_code, 200)

        # case experiment
        self.user_experiment = AuthUserFactory()
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user_experiment.auth_expiry_token.key
        )
        self.customer_experiment = CustomerFactory(id=2, user=self.user_experiment)
        self.application.customer = self.customer_experiment
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(
            response.json()['data']['message']['title'], 'This is title for EXPERIMENT HIGH'
        )
        self.assertEqual(response.status_code, 200)

    def test_show_ipa_banner_v2_medium_banner(self):
        self.eligible_data.is_okay = False
        self.eligible_data.save()

        # case control
        self.user_control = AuthUserFactory()
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user_control.auth_expiry_token.key
        )
        self.customer_control = CustomerFactory(id=1, user=self.user_control)
        expected_sticky_url = get_oss_public_url(
            settings.OSS_PUBLIC_ASSETS_BUCKET, 'info-card/STICKY_BANNER_MEDIUM_FDC_CTRL.png'
        )

        self.application.customer = self.customer_control
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(
            response.json()['data']['message']['title'], 'This is title for CONTROL MEDIUM'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['message']['link_sticky_bar'], expected_sticky_url)

        # case experiment
        self.user_experiment = AuthUserFactory()
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user_experiment.auth_expiry_token.key
        )
        self.customer_experiment = CustomerFactory(id=2, user=self.user_experiment)
        self.application.customer = self.customer_experiment
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(
            response.json()['data']['message']['title'], 'This is title for EXPERIMENT MEDIUM'
        )
        self.assertEqual(response.status_code, 200)

    def test_experiment_ipa_v3_high_fdc(self):
        self.app_version = '8.34.0'
        self.eligible_data.is_okay = True
        self.eligible_data.save()
        expected_sticky_url = get_oss_public_url(
            settings.OSS_PUBLIC_ASSETS_BUCKET, 'info-card/STICKY_BANNER_GOOD_FDC_EXP.png'
        )

        # case flow 1 (no sticky bar) high_fdc
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(id=11, user=self.user)
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['data']['show_sticky_banner'])
        self.assertTrue((response.json()['data']['show_ipa_banner']))

        experiment_group = ExperimentGroup.objects.filter(application_id=self.application.id).last()
        self.assertEqual(experiment_group.group, 'experiment')
        self.assertEqual(experiment_group.segment, 'high_fdc_no_stickybar')

        # case flow 2 (all_component) high_fdc
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(id=14, user=self.user)
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['show_sticky_banner'])
        self.assertTrue((response.json()['data']['show_ipa_banner']))
        self.assertEqual(response.json()['data']['message']['link_sticky_bar'], expected_sticky_url)

        experiment_group = ExperimentGroup.objects.filter(application_id=self.application.id).last()
        self.assertEqual(experiment_group.group, 'experiment')
        self.assertEqual(experiment_group.segment, 'high_fdc_all_component')

        # case flow 3 (no banner) high_fdc
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(id=19, user=self.user)
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['show_sticky_banner'])
        self.assertFalse((response.json()['data']['show_ipa_banner']))

        experiment_group = ExperimentGroup.objects.filter(application_id=self.application.id).last()
        self.assertEqual(experiment_group.group, 'experiment')
        self.assertEqual(experiment_group.segment, 'high_fdc_no_banner')
        self.assertEqual(response.json()['data']['message']['link_sticky_bar'], expected_sticky_url)

        # case flow control high_fdc
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(id=10, user=self.user)
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['show_ipa_banner'])
        self.assertFalse((response.json()['data']['show_sticky_banner']))

        experiment_group = ExperimentGroup.objects.filter(application_id=self.application.id).last()
        self.assertEqual(experiment_group.group, 'control')
        self.assertEqual(experiment_group.segment, 'high_fdc')

    def test_experiment_ipa_v3_medium_fdc(self):
        self.app_version = '8.34.0'
        self.eligible_data.is_okay = False
        self.eligible_data.save()
        expected_sticky_url = get_oss_public_url(
            settings.OSS_PUBLIC_ASSETS_BUCKET, 'info-card/STICKY_BANNER_MEDIUM_FDC_EXP.png'
        )

        # case flow 1 (no sticky bar) high_fdc
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(id=11, user=self.user)
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['data']['show_sticky_banner'])
        self.assertTrue((response.json()['data']['show_ipa_banner']))

        experiment_group = ExperimentGroup.objects.filter(application_id=self.application.id).last()
        self.assertEqual(experiment_group.group, 'experiment')
        self.assertEqual(experiment_group.segment, 'medium_fdc_no_stickybar')

        # case flow 2 (all_component) high_fdc
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(id=14, user=self.user)
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['show_sticky_banner'])
        self.assertTrue((response.json()['data']['show_ipa_banner']))
        self.assertEqual(response.json()['data']['message']['link_sticky_bar'], expected_sticky_url)

        experiment_group = ExperimentGroup.objects.filter(application_id=self.application.id).last()
        self.assertEqual(experiment_group.group, 'experiment')
        self.assertEqual(experiment_group.segment, 'medium_fdc_all_component')

        # case flow 3 (no banner) high_fdc
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(id=19, user=self.user)
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['show_sticky_banner'])
        self.assertFalse((response.json()['data']['show_ipa_banner']))
        self.assertEqual(response.json()['data']['message']['link_sticky_bar'], expected_sticky_url)

        experiment_group = ExperimentGroup.objects.filter(application_id=self.application.id).last()
        self.assertEqual(experiment_group.group, 'experiment')
        self.assertEqual(experiment_group.segment, 'medium_fdc_no_banner')

        # case flow control high_fdc
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(id=10, user=self.user)
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['show_ipa_banner'])
        self.assertFalse((response.json()['data']['show_sticky_banner']))

        experiment_group = ExperimentGroup.objects.filter(application_id=self.application.id).last()
        self.assertEqual(experiment_group.group, 'control')
        self.assertEqual(experiment_group.segment, 'medium_fdc')

    def test_experiment_setting_inactive(self):
        # v2 experiment
        self.ExperimentSetting.update_safely(is_active=False)
        self.user = AuthUserFactory()
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
        )
        self.customer = CustomerFactory(user=self.user)
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['data']['message']['title'], 'This is title for CONTROL HIGH'
        )

        experiment_group = ExperimentGroup.objects.filter(application_id=self.application.id).last()
        self.assertIsNone(experiment_group.group)
        self.assertEqual(experiment_group.segment, 'high_fdc')

        # v3 experiment
        self.ExperimentSettingV3.update_safely(is_active=False)
        self.user = AuthUserFactory()
        self.app_version = '8.34.0'

        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
        )
        self.customer = CustomerFactory(user=self.user)
        self.application.customer = self.customer
        self.application.save()

        response = self.client.get(self.url_v2, HTTP_X_APP_VERSION=self.app_version)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['data']['message']['title'], 'This is title for CONTROL HIGH'
        )

        experiment_group = ExperimentGroup.objects.filter(application_id=self.application.id).last()
        self.assertIsNone(experiment_group.group)
        self.assertEqual(experiment_group.segment, 'high_fdc')


class TestSmsCampaignListView(APITestCase):
    def setUp(self):
        self.url = '/streamlined_communication/campaign/'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = GroupFactory(name="comms_campaign_manager")
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.user_segment = StreamlinedCommunicationSegmentFactory()
        self.campaign_department = StreamlinedCampaignDepartmentFactory()
        self.sms_campaign_1 = StreamlinedCommunicationCampaignFactory(
            department=self.campaign_department
        )
        self.sms_campaign_2 = StreamlinedCommunicationCampaignFactory(
            department=self.campaign_department,
            status=StreamlinedCommCampaignConstants.CampaignStatus.ON_GOING,
        )
        self.sms_campaign_3 = StreamlinedCommunicationCampaignFactory(
            department=self.campaign_department,
            status=StreamlinedCommCampaignConstants.CampaignStatus.SENT,
        )
        self.sms_campaign_4 = StreamlinedCommunicationCampaignFactory(
            department=self.campaign_department, name='Dummy campaign'
        )
        self.sms_campaign_5 = StreamlinedCommunicationCampaignFactory(
            department=self.campaign_department,
            name='Dummy campaign',
            status=StreamlinedCommCampaignConstants.CampaignStatus.FAILED,
        )
        self.sms_campaign_6 = StreamlinedCommunicationCampaignFactory(
            department=self.campaign_department,
            name='Dummy campaign',
            status=StreamlinedCommCampaignConstants.CampaignStatus.CANCELLED,
        )

    def test_sms_campaign_list_all(self):
        response = self.client.get(self.url)

        # Check if the response status code is 200 OK
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check if the response content is a JSON response
        self.assertEqual(len(response.json()['results']['data']), 6)
        self.assertEqual(
            response.json()['results']['data'][0]['department'], self.campaign_department.name
        )
        self.assertEqual(response.json()['results']['data'][0]['name'], self.sms_campaign_1.name)

    def test_sms_campaign_list_menunggu_konfirmasi_status(self):
        url = '/streamlined_communication/campaign/?campaign_status=Menunggu Konfirmasi'
        response = self.client.get(url)

        # Check if the response status code is 200 OK
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check if the response content is a JSON response
        self.assertEqual(len(response.json()['results']['data']), 2)
        self.assertEqual(
            response.json()['results']['data'][0]['department'], self.campaign_department.name
        )
        self.assertEqual(response.json()['results']['data'][0]['name'], self.sms_campaign_1.name)

    def test_sms_campaign_list_sedang_berjalan_status(self):
        url = '/streamlined_communication/campaign/?campaign_status=Sedang Berjalan'
        response = self.client.get(url)

        # Check if the response status code is 200 OK
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check if the response content is a JSON response
        self.assertEqual(len(response.json()['results']['data']), 1)
        self.assertEqual(
            response.json()['results']['data'][0]['department'], self.campaign_department.name
        )
        self.assertEqual(response.json()['results']['data'][0]['name'], self.sms_campaign_1.name)

    def test_sms_campaign_list_selesai_status(self):
        url = '/streamlined_communication/campaign/?campaign_status=Selesai'
        response = self.client.get(url)

        # Check if the response status code is 200 OK
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check if the response content is a JSON response
        self.assertEqual(len(response.json()['results']['data']), 3)
        self.assertEqual(
            response.json()['results']['data'][0]['department'], self.campaign_department.name
        )
        self.assertEqual(response.json()['results']['data'][0]['name'], self.sms_campaign_1.name)

    def test_sms_campaign_list_with_sort(self):
        # test sort by ascending order
        url = '/streamlined_communication/campaign/?sort_by=-cdate'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['results']['data']), 6)
        self.assertEqual(response.json()['results']['data'][0]['name'], self.sms_campaign_6.name)

        # test sort by descending order
        url = '/streamlined_communication/campaign/?sort_by=cdate'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['results']['data']), 6)
        self.assertEqual(response.json()['results']['data'][0]['name'], self.sms_campaign_1.name)


class TestSmsCampaignCreateView(APITestCase):
    def setUp(self):
        self.url = '/streamlined_communication/campaign/'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = GroupFactory(name="comms_campaign_manager")
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.user_segment = StreamlinedCommunicationSegmentFactory()
        self.campaign_department = StreamlinedCampaignDepartmentFactory()
        self.squad = StreamlinedCampaignSquadFactory()

    def test_sms_campaign_create(self):
        request_data = {
            "name": "test_campaign",
            "user_segment": self.user_segment.id,
            "squad": self.squad.id,
            "department": self.campaign_department.id,
            "schedule_mode": "Sekarang",
            "content": "dummy content",
        }
        response = self.client.post(self.url, data=request_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        streamlined_communication_campaign_qs = StreamlinedCommunicationCampaign.objects.all()

        self.assertEqual(
            streamlined_communication_campaign_qs[0].name,
            "{0}_{1}".format(self.campaign_department.department_code, request_data.get('name')),
        )
        self.assertEqual(
            streamlined_communication_campaign_qs[0].user_segment.id,
            request_data.get('user_segment'),
        )

    def test_sms_campaign_create_for_campaign_name_with_space(self):
        request_data = {
            "name": "test campaign",
            "user_segment": self.user_segment.id,
            "squad": self.squad.id,
            "department": self.campaign_department.id,
            "schedule_mode": "Sekarang",
            "content": "dummy content",
        }
        response = self.client.post(self.url, data=request_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        streamlined_communication_campaign_qs = StreamlinedCommunicationCampaign.objects.all()
        name = request_data.get('name').replace(' ', '_')
        self.assertEqual(
            streamlined_communication_campaign_qs[0].name,
            "{0}_{1}".format(self.campaign_department.department_code, name),
        )
        self.assertEqual(
            streamlined_communication_campaign_qs[0].user_segment.id,
            request_data.get('user_segment'),
        )


class TestSmsCampaignDropdownListView(APITestCase):
    def setUp(self):
        self.maxDiff = None
        self.url = '/streamlined_communication/campaign/get_dropdown_list'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group1 = GroupFactory(name="comms_campaign_manager")
        self.user.groups.add(self.group1)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.user_segment = StreamlinedCommunicationSegmentFactory()
        self.user_segment1 = StreamlinedCommunicationSegmentFactory(segment_name='test1')
        self.campaign_department = StreamlinedCampaignDepartmentFactory()
        self.campaign_department1 = StreamlinedCampaignDepartmentFactory(
            name='Collection', department_code='COL'
        )
        self.squad = StreamlinedCampaignSquadFactory()
        self.squad1 = StreamlinedCampaignSquadFactory(name='Grab')

    def test_sms_campaign_dropdown_list_with_no_segemnt_status(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        expected_result = {
            "department": [
                {"id": self.campaign_department.id, "name": self.campaign_department.name},
                {"id": self.campaign_department1.id, "name": self.campaign_department1.name},
            ],
            "squad": [
                {"id": self.squad.id, "name": self.squad.name},
                {"id": self.squad1.id, "name": self.squad1.name},
            ],
            "user_segment": [],
        }
        self.assertEqual(response.json(), expected_result)

    def test_sms_campaign_dropdown_list_with_failed_segment_status(self):
        self.user_segment.status = CommsUserSegmentConstants.SegmentStatus.FAILED
        self.user_segment1.status = CommsUserSegmentConstants.SegmentStatus.FAILED
        self.user_segment.save()
        self.user_segment1.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        expected_result = {
            "department": [
                {"id": self.campaign_department.id, "name": self.campaign_department.name},
                {"id": self.campaign_department1.id, "name": self.campaign_department1.name},
            ],
            "squad": [
                {"id": self.squad.id, "name": self.squad.name},
                {"id": self.squad1.id, "name": self.squad1.name},
            ],
            "user_segment": [],
        }
        self.assertEqual(response.json(), expected_result)

    def test_sms_campaign_dropdown_list_with_processing_success_segment_status(self):
        self.user_segment.status = CommsUserSegmentConstants.SegmentStatus.PROCESSING
        self.user_segment1.status = CommsUserSegmentConstants.SegmentStatus.SUCCESS
        self.user_segment.save()
        self.user_segment1.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        expected_result = {
            "department": [
                {"id": self.campaign_department.id, "name": self.campaign_department.name},
                {"id": self.campaign_department1.id, "name": self.campaign_department1.name},
            ],
            "squad": [
                {"id": self.squad.id, "name": self.squad.name},
                {"id": self.squad1.id, "name": self.squad1.name},
            ],
            "user_segment": [
                {
                    "id": self.user_segment.id,
                    "segment_name": self.user_segment.segment_name,
                    "total_sms_price": 0.0,
                    "segment_users_count": 0,
                    "status": CommsUserSegmentConstants.SegmentStatus.PROCESSING,
                    "cdate": self.user_segment.cdate.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                },
                {
                    "id": self.user_segment1.id,
                    "segment_name": self.user_segment1.segment_name,
                    "total_sms_price": 0.0,
                    "segment_users_count": 0,
                    "status": CommsUserSegmentConstants.SegmentStatus.SUCCESS,
                    "cdate": self.user_segment1.cdate.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                },
            ],
        }
        self.assertEqual(response.json(), expected_result)


class TestCampaignTestSmsView(APITestCase):
    def setUp(self):
        self.url = '/streamlined_communication/campaign/test_sms'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group1 = GroupFactory(name="comms_campaign_manager")
        self.user.groups.add(self.group1)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    @mock.patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms')
    def test_campaign_test_sms_view_success(self, mock_send_sms):
        request_data = {"phone_number": "086615812289", "content": "dummy data"}
        txt_msg = "fake sms"
        sms_response = {
            "messages": [
                {
                    'status': '0',
                    'message-id': '1234',
                    'to': '0857222333',
                    'julo_sms_vendor': 'nexmo',
                    'is_comms_campaign_sms': True,
                }
            ]
        }
        mock_send_sms.return_value = txt_msg, sms_response
        response = self.client.post(self.url, data=request_data)
        comms_campaign_sms_history = CommsCampaignSmsHistory.objects.get(
            template_code='test_sms',
            to_mobile_phone=format_e164_indo_phone_number(request_data.get('phone_number')),
        )
        self.assertEqual(comms_campaign_sms_history.id, response.data['data']['sms_history_id'])

    @mock.patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms')
    def test_campaign_test_sms_view_fail_to_send_sms(self, mock_send_sms):
        request_data = {"phone_number": "086615812289", "content": "dummy data"}
        txt_msg = "fake sms"
        sms_response = {
            "messages": [
                {
                    'status': '1',
                    'message-id': '1234',
                    'to': '0857222333',
                    'julo_sms_vendor': 'nexmo',
                    'is_comms_campaign_sms': True,
                }
            ]
        }
        mock_send_sms.return_value = txt_msg, sms_response
        response = self.client.post(self.url, data=request_data)
        self.assertTrue(response.data.get('message', "Failed to send SMS"))

class TestApproveSmsCampaign(APITestCase):
    def setUp(self):
        self.url = '/streamlined_communication/campaign/approve_reject'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group1 = GroupFactory(name="comms_campaign_manager")
        self.user.groups.add(self.group1)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.campaign_department = StreamlinedCampaignDepartmentFactory()
        self.user_segment_obj = StreamlinedCommunicationSegmentFactory(segment_count=2)
        self.comms_segment_chunk1 = CommsUserSegmentChunkFactory(
            streamlined_communication_segment=self.user_segment_obj
        )
        self.comms_segment_chunk2 = CommsUserSegmentChunkFactory(
            streamlined_communication_segment=self.user_segment_obj
        )
        self.sms_campaign = StreamlinedCommunicationCampaignFactory(
            department=self.campaign_department, user_segment=self.user_segment_obj
        )
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
        )
        self.sms_campaign.content = self.streamlined_message
        self.sms_campaign.save()
        self.customer = CustomerFactory()
        self.customer_2 = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_2 = AccountFactory(customer=self.customer_2)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)
        self.application_2 = ApplicationJ1Factory(customer=self.customer_2, account=self.account_2)
        self.application.mobile_phone_1 = '088321312312312'
        self.application_2.mobile_phone_1 = '12345'
        self.application_2.save()
        self.application.save()
        self.feature_setting_integrity_ttl = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.SMS_CAMPAIGN_FAILED_PROCESS_CHECK_TTL,
            parameters={"TTL": "1800"},
        )

    @mock.patch('juloserver.streamlined_communication.tasks.send_sms_campaign_async.delay')
    @mock.patch(
        'juloserver.new_crm.services.streamlined_services.StreamlinedImportUserClient.get_downloadable_response'
    )
    @patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_sms_campaign_approve_success_for_approve_action_type(
        self,
        mock_upload_import_user_file_data_to_oss,
        mock_get_downloadable_response,
        mock_send_sms_campaign_async,
    ):
        CommsCampaignSmsHistoryFactory(campaign=self.sms_campaign)
        self.application.mobile_phone_1 = '0866340695459'
        self.application_2.mobile_phone_1 = '0866340695459'
        self.application_2.save()
        self.application.save()
        chunk_csv_data1 = f"""account_id
                            {self.application.account_id}
                            """
        chunk_csv_data2 = f"""account_id
                            {self.application_2.account_id}
                            """
        data1 = bytes(chunk_csv_data1, 'utf-8')
        data2 = bytes(chunk_csv_data2, 'utf-8')

        chunk_csv_file1 = io.BytesIO(data1)
        chunk_csv_file2 = io.BytesIO(data2)

        self.chunk_file1 = InMemoryUploadedFile(
            file=chunk_csv_file1,
            field_name='',
            name=self.comms_segment_chunk1.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        self.chunk_file2 = InMemoryUploadedFile(
            file=chunk_csv_file2,
            field_name='',
            name=self.comms_segment_chunk2.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )

        response1 = StreamingHttpResponse(
            streaming_content=chunk_csv_file1, content_type='text/csv'
        )
        response1['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk1.chunk_csv_file_name + '"'
        )
        response2 = StreamingHttpResponse(
            streaming_content=chunk_csv_file2, content_type='text/csv'
        )
        response2['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk2.chunk_csv_file_name + '"'
        )

        mock_upload_import_user_file_data_to_oss.return_value = None
        mock_get_downloadable_response.return_value = [response1, response2]
        request_data = {"campaign_id": self.sms_campaign.id, "action_type": "approve"}
        response = self.client.post(self.url, data=request_data)
        mock_send_sms_campaign_async.assert_called()
        self.assertEqual(mock_send_sms_campaign_async.call_count, 2)
        self.sms_campaign.refresh_from_db()
        self.assertEqual(self.sms_campaign.confirmed_by, self.user)
        self.assertNotEquals(self.sms_campaign.created_by, self.sms_campaign.confirmed_by)

        self.assertEqual(
            self.sms_campaign.status, StreamlinedCommCampaignConstants.CampaignStatus.PARTIAL_SENT
        )
        self.assertEqual(
            response.json()['data']['data']['message'], "SMS campaign tasks enqueued for processing"
        )

    @mock.patch(
        'juloserver.new_crm.services.streamlined_services.StreamlinedImportUserClient.get_downloadable_response'
    )
    @patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_sms_campaign_approve_with_invalid_csv_file_type(
        self, mock_upload_import_user_file_data_to_oss, mock_get_downloadable_response
    ):
        chunk_csv_data1 = """dummy_id
                        8
                       """
        chunk_csv_data2 = """dummy_id
                        9
                       """

        data1 = bytes(chunk_csv_data1, 'utf-8')
        data2 = bytes(chunk_csv_data2, 'utf-8')

        chunk_csv_file1 = io.BytesIO(data1)
        chunk_csv_file2 = io.BytesIO(data2)

        self.chunk_file1 = InMemoryUploadedFile(
            file=chunk_csv_file1,
            field_name='',
            name=self.comms_segment_chunk1.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        self.chunk_file2 = InMemoryUploadedFile(
            file=chunk_csv_file2,
            field_name='',
            name=self.comms_segment_chunk2.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )

        response1 = StreamingHttpResponse(
            streaming_content=chunk_csv_file1, content_type='text/csv'
        )
        response1['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk1.chunk_csv_file_name + '"'
        )
        response2 = StreamingHttpResponse(
            streaming_content=chunk_csv_file2, content_type='text/csv'
        )
        response2['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk2.chunk_csv_file_name + '"'
        )

        mock_upload_import_user_file_data_to_oss.return_value = None
        mock_get_downloadable_response.return_value = [response1, response2]

        request_data = {"campaign_id": self.sms_campaign.id, "action_type": "approve"}
        response = self.client.post(self.url, data=request_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.sms_campaign.refresh_from_db()
        self.assertNotEqual(
            self.sms_campaign.status, StreamlinedCommCampaignConstants.CampaignStatus.SENT
        )
        self.assertEqual(
            response.json()['data']['errors'][0]['message'], "Failed to process CSV data"
        )

    @mock.patch(
        'juloserver.new_crm.services.streamlined_services.StreamlinedImportUserClient.get_downloadable_response'
    )
    @patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_sms_campaign_approve_with_invalid_mobile_numbers(
        self, mock_upload_import_user_file_data_to_oss, mock_get_downloadable_response
    ):
        chunk_csv_data1 = f"""account_id
                                    {self.application.account_id}
                                    """
        chunk_csv_data2 = f"""account_id
                                    {self.application_2.account_id}
                                    """
        data1 = bytes(chunk_csv_data1, 'utf-8')
        data2 = bytes(chunk_csv_data2, 'utf-8')
        chunk_csv_file1 = io.BytesIO(data1)
        chunk_csv_file2 = io.BytesIO(data2)

        self.chunk_file1 = InMemoryUploadedFile(
            file=chunk_csv_file1,
            field_name='',
            name=self.comms_segment_chunk1.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        self.chunk_file2 = InMemoryUploadedFile(
            file=chunk_csv_file2,
            field_name='',
            name=self.comms_segment_chunk2.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )

        response1 = StreamingHttpResponse(
            streaming_content=chunk_csv_file1, content_type='text/csv'
        )
        response1['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk1.chunk_csv_file_name + '"'
        )
        response2 = StreamingHttpResponse(
            streaming_content=chunk_csv_file2, content_type='text/csv'
        )
        response2['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk2.chunk_csv_file_name + '"'
        )

        mock_upload_import_user_file_data_to_oss.return_value = None
        mock_get_downloadable_response.return_value = [response1, response2]
        request_data = {"campaign_id": self.sms_campaign.id, "action_type": "approve"}
        response = self.client.post(self.url, data=request_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.sms_campaign.refresh_from_db()
        self.assertNotEqual(
            self.sms_campaign.status, StreamlinedCommCampaignConstants.CampaignStatus.SENT
        )
        self.assertEqual(response.json()['data']['errors'][0]['message'], "No mobile numbers found")

    @mock.patch('juloserver.streamlined_communication.tasks.send_sms_campaign_async.delay')
    @mock.patch(
        'juloserver.new_crm.services.streamlined_services.StreamlinedImportUserClient.get_downloadable_response'
    )
    @patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_sms_campaign_approve_for_reject_action_type(
        self,
        mock_upload_import_user_file_data_to_oss,
        mock_get_downloadable_response,
        mock_send_sms_campaign_async,
    ):
        self.application.mobile_phone_1 = '0866340695459'
        self.application_2.mobile_phone_1 = '0866340695459'
        self.application_2.save()
        self.application.save()
        chunk_csv_data1 = f"""account_id
                                    {self.application.account_id}
                                    """
        chunk_csv_data2 = f"""account_id
                                    {self.application_2.account_id}
                                    """
        data1 = bytes(chunk_csv_data1, 'utf-8')
        data2 = bytes(chunk_csv_data2, 'utf-8')

        chunk_csv_file1 = io.BytesIO(data1)
        chunk_csv_file2 = io.BytesIO(data2)

        self.chunk_file1 = InMemoryUploadedFile(
            file=chunk_csv_file1,
            field_name='',
            name=self.comms_segment_chunk1.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        self.chunk_file2 = InMemoryUploadedFile(
            file=chunk_csv_file2,
            field_name='',
            name=self.comms_segment_chunk2.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )

        response1 = StreamingHttpResponse(
            streaming_content=chunk_csv_file1, content_type='text/csv'
        )
        response1['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk1.chunk_csv_file_name + '"'
        )
        response2 = StreamingHttpResponse(
            streaming_content=chunk_csv_file2, content_type='text/csv'
        )
        response2['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk2.chunk_csv_file_name + '"'
        )

        mock_upload_import_user_file_data_to_oss.return_value = None
        mock_get_downloadable_response.return_value = [response1, response2]
        request_data = {"campaign_id": self.sms_campaign.id, "action_type": "reject"}
        response = self.client.post(self.url, data=request_data)
        mock_send_sms_campaign_async.assert_not_called()
        self.sms_campaign.refresh_from_db()
        self.assertEqual(self.sms_campaign.confirmed_by, self.user)
        self.assertNotEquals(self.sms_campaign.created_by, self.sms_campaign.confirmed_by)
        self.assertEqual(
            self.sms_campaign.status, StreamlinedCommCampaignConstants.CampaignStatus.REJECTED
        )

        self.assertEqual(response.json()['data']['message'], "SMS campaign Rejected")

    @mock.patch('juloserver.streamlined_communication.tasks.send_sms_campaign_async.delay')
    @mock.patch(
        'juloserver.new_crm.services.streamlined_services.StreamlinedImportUserClient.get_downloadable_response'
    )
    @patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_sms_campaign_approve_for_invalid_action_type(
        self,
        mock_upload_import_user_file_data_to_oss,
        mock_get_downloadable_response,
        mock_send_sms_campaign_async,
    ):
        self.application.mobile_phone_1 = '0866340695459'
        self.application_2.mobile_phone_1 = '0866340695459'
        self.application_2.save()
        self.application.save()
        chunk_csv_data1 = f"""account_id
                                            {self.application.account_id}
                                            """
        chunk_csv_data2 = f"""account_id
                                            {self.application_2.account_id}
                                            """
        data1 = bytes(chunk_csv_data1, 'utf-8')
        data2 = bytes(chunk_csv_data2, 'utf-8')

        chunk_csv_file1 = io.BytesIO(data1)
        chunk_csv_file2 = io.BytesIO(data2)

        self.chunk_file1 = InMemoryUploadedFile(
            file=chunk_csv_file1,
            field_name='',
            name=self.comms_segment_chunk1.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        self.chunk_file2 = InMemoryUploadedFile(
            file=chunk_csv_file2,
            field_name='',
            name=self.comms_segment_chunk2.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )

        response1 = StreamingHttpResponse(
            streaming_content=chunk_csv_file1, content_type='text/csv'
        )
        response1['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk1.chunk_csv_file_name + '"'
        )
        response2 = StreamingHttpResponse(
            streaming_content=chunk_csv_file2, content_type='text/csv'
        )
        response2['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk2.chunk_csv_file_name + '"'
        )

        mock_upload_import_user_file_data_to_oss.return_value = None
        mock_get_downloadable_response.return_value = [response1, response2]
        request_data = {"campaign_id": self.sms_campaign.id, "action_type": "invalid"}
        response = self.client.post(self.url, data=request_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_send_sms_campaign_async.assert_not_called()
        self.sms_campaign.refresh_from_db()
        self.assertNotEqual(
            self.sms_campaign.status, StreamlinedCommCampaignConstants.CampaignStatus.ON_GOING
        )
        self.assertEqual(response.json()['errors'][0]['message'], "Invalid action_type")

    @mock.patch('juloserver.streamlined_communication.tasks.send_sms_campaign_async.delay')
    @mock.patch(
        'juloserver.new_crm.services.streamlined_services.StreamlinedImportUserClient.get_downloadable_response'
    )
    @patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_sms_campaign_for_partial_sent_status(
        self,
        mock_upload_import_user_file_data_to_oss,
        mock_get_downloadable_response,
        mock_send_sms_campaign_async,
    ):
        CommsCampaignSmsHistoryFactory(campaign=self.sms_campaign)
        self.application.mobile_phone_1 = '0866340695459'
        self.application_2.mobile_phone_1 = '0866340695459'
        self.application_2.save()
        self.application.save()
        chunk_csv_data1 = f"""account_id
                            {self.application.account_id}
                            """
        chunk_csv_data2 = f"""account_id
                            {self.application_2.account_id}
                            """
        data1 = bytes(chunk_csv_data1, 'utf-8')
        data2 = bytes(chunk_csv_data2, 'utf-8')

        chunk_csv_file1 = io.BytesIO(data1)
        chunk_csv_file2 = io.BytesIO(data2)

        self.chunk_file1 = InMemoryUploadedFile(
            file=chunk_csv_file1,
            field_name='',
            name=self.comms_segment_chunk1.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        self.chunk_file2 = InMemoryUploadedFile(
            file=chunk_csv_file2,
            field_name='',
            name=self.comms_segment_chunk2.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )

        response1 = StreamingHttpResponse(
            streaming_content=chunk_csv_file1, content_type='text/csv'
        )
        response1['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk1.chunk_csv_file_name + '"'
        )
        response2 = StreamingHttpResponse(
            streaming_content=chunk_csv_file2, content_type='text/csv'
        )
        response2['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk2.chunk_csv_file_name + '"'
        )

        mock_upload_import_user_file_data_to_oss.return_value = None
        mock_get_downloadable_response.return_value = [response1, response2]

        request_data = {"campaign_id": self.sms_campaign.id, "action_type": "approve"}
        response = self.client.post(self.url, data=request_data)
        mock_send_sms_campaign_async.assert_called()
        self.assertEqual(mock_send_sms_campaign_async.call_count, 2)
        self.sms_campaign.refresh_from_db()
        self.assertEqual(self.sms_campaign.confirmed_by, self.user)
        self.assertNotEquals(self.sms_campaign.created_by, self.sms_campaign.confirmed_by)
        self.assertEqual(
            self.sms_campaign.status, StreamlinedCommCampaignConstants.CampaignStatus.PARTIAL_SENT
        )
        self.assertEqual(
            response.json()['data']['data']['message'], "SMS campaign tasks enqueued for processing"
        )

    @mock.patch('juloserver.streamlined_communication.tasks.send_sms_campaign_async.delay')
    @mock.patch(
        'juloserver.new_crm.services.streamlined_services.StreamlinedImportUserClient.get_downloadable_response'
    )
    @patch('juloserver.new_crm.services.streamlined_services.upload_file_as_bytes_to_oss')
    def test_sms_campaign_for_done_status(
        self,
        mock_upload_import_user_file_data_to_oss,
        mock_get_downloadable_response,
        mock_send_sms_campaign_async,
    ):
        CommsCampaignSmsHistoryFactory(campaign=self.sms_campaign)
        CommsCampaignSmsHistoryFactory(campaign=self.sms_campaign)

        self.application.mobile_phone_1 = '0866340695459'
        self.application_2.mobile_phone_1 = '0866340695459'
        self.application_2.save()
        self.application.save()
        chunk_csv_data1 = f"""account_id
                            {self.application.account_id}
                            """
        chunk_csv_data2 = f"""account_id
                            {self.application_2.account_id}
                            """
        data1 = bytes(chunk_csv_data1, 'utf-8')
        data2 = bytes(chunk_csv_data2, 'utf-8')

        chunk_csv_file1 = io.BytesIO(data1)
        chunk_csv_file2 = io.BytesIO(data2)

        self.chunk_file1 = InMemoryUploadedFile(
            file=chunk_csv_file1,
            field_name='',
            name=self.comms_segment_chunk1.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )
        self.chunk_file2 = InMemoryUploadedFile(
            file=chunk_csv_file2,
            field_name='',
            name=self.comms_segment_chunk2.chunk_csv_file_name,
            content_type='text/csv',
            size='',
            content_type_extra=None,
            charset=None,
        )

        response1 = StreamingHttpResponse(
            streaming_content=chunk_csv_file1, content_type='text/csv'
        )
        response1['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk1.chunk_csv_file_name + '"'
        )
        response2 = StreamingHttpResponse(
            streaming_content=chunk_csv_file2, content_type='text/csv'
        )
        response2['Content-Disposition'] = (
            'filename="' + self.comms_segment_chunk2.chunk_csv_file_name + '"'
        )

        mock_upload_import_user_file_data_to_oss.return_value = None
        mock_get_downloadable_response.return_value = [response1, response2]

        request_data = {"campaign_id": self.sms_campaign.id, "action_type": "approve"}
        response = self.client.post(self.url, data=request_data)
        mock_send_sms_campaign_async.assert_called()
        self.assertEqual(mock_send_sms_campaign_async.call_count, 2)
        self.sms_campaign.refresh_from_db()
        self.assertEqual(self.sms_campaign.confirmed_by, self.user)
        self.assertNotEquals(self.sms_campaign.created_by, self.sms_campaign.confirmed_by)
        self.assertEqual(
            self.sms_campaign.status, StreamlinedCommCampaignConstants.CampaignStatus.SENT
        )
        self.assertEqual(
            response.json()['data']['data']['message'], "SMS campaign tasks enqueued for processing"
        )


class DownloadReportCampaignTestCase(TestCase):
    def setUp(self):
        self.url = '/streamlined_communication/campaign/download-report'
        self.client = APIClient()
        self.user_1 = AuthUserFactory()
        self.user_2 = AuthUserFactory()
        self.client.force_login(self.user_1)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_1.auth_expiry_token.key)
        self.customer_1 = CustomerFactory(user=self.user_1)
        self.customer_2 = CustomerFactory(user=self.user_2)

        self.campaign_department = StreamlinedCampaignDepartmentFactory()
        self.sms_campaign = StreamlinedCommunicationCampaignFactory(
            created_by=self.user_1, department=self.campaign_department
        )

        self.sms_history1 = CommsCampaignSmsHistoryFactory(
            customer=self.customer_1, template_code='J1_sms_{}'.format(self.sms_campaign.name)
        )
        self.sms_history2 = CommsCampaignSmsHistoryFactory(
            customer=self.customer_2, template_code='J1_sms_{}'.format(self.sms_campaign.name)
        )

    def test_download_report_campaign_success(self):
        self.sms_campaign.status = StreamlinedCommCampaignConstants.CampaignStatus.SENT
        self.sms_campaign.save()
        request_data = {
            "campaign_id": self.sms_campaign.id,
        }
        response = self.client.post(self.url, data=request_data)

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response['Content-Type'], 'text/csv')

        csv_content = response.content.decode('utf-8')
        csv_reader = csv.reader(StringIO(csv_content))

        headers = next(csv_reader)
        expected_headers = [
            'WAKTU DIBUAT',
            'DIBUAT OLEH',
            'DEPARTEMEN',
            'TIPE CAMPAIGN',
            'NAMA CAMPAIGN',
            'USER SEGMENT',
            'ACCOUNT ID',
            'CUSTOMER ID',
            'APPLICATION ID',
            'PHONE NUMBER',
            'DELIVERY STATUS',
            'TIPE DATA SEGMENT',
        ]
        self.assertEqual(headers, expected_headers)

        campaign_report_row_1 = next(csv_reader)
        expected_row_1 = [
            self.sms_campaign.cdate.strftime('%Y-%m-%d %H:%M:%S.%f+00:00'),
            self.sms_campaign.created_by.username,
            self.sms_campaign.department.name,
            self.sms_campaign.campaign_type,
            self.sms_campaign.name,
            str(self.sms_campaign.user_segment.segment_name),
            str(self.sms_history1.account_id),
            str(self.sms_history1.customer_id),
            str(self.sms_history1.application_id),
            self.sms_history1.to_mobile_phone.raw_input,
            self.sms_history1.status,
            str(self.sms_campaign.user_segment.csv_file_type),
        ]
        self.assertEqual(campaign_report_row_1, expected_row_1)
        campaign_report_row_2 = next(csv_reader)
        expected_row_2 = [
            self.sms_campaign.cdate.strftime('%Y-%m-%d %H:%M:%S.%f+00:00'),
            self.sms_campaign.created_by.username,
            self.sms_campaign.department.name,
            self.sms_campaign.campaign_type,
            self.sms_campaign.name,
            str(self.sms_campaign.user_segment.segment_name),
            str(self.sms_history2.account_id),
            str(self.sms_history2.customer_id),
            str(self.sms_history2.application_id),
            self.sms_history2.to_mobile_phone.raw_input,
            self.sms_history2.status,
            str(self.sms_campaign.user_segment.csv_file_type),
        ]
        self.assertEqual(campaign_report_row_2, expected_row_2)

    def test_download_report_campaign_fail(self):
        # for 'menunggu konfirmasi' status
        request_data = {
            "campaign_id": self.sms_campaign.id,
        }
        response = self.client.post(self.url, data=request_data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['errors'][0]['message'],
            "Campaign is still pending approval or ongoing. Cannot proceed.",
        )

        # for 'sedang berjalan' status

        self.sms_campaign.status = StreamlinedCommCampaignConstants.CampaignStatus.ON_GOING
        self.sms_campaign.save()
        request_data = {
            "campaign_id": self.sms_campaign.id,
        }
        response = self.client.post(self.url, data=request_data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['errors'][0]['message'],
            "Campaign is still pending approval or ongoing. Cannot proceed.",
        )

class TestCampaignDetailView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group1 = GroupFactory(name="comms_campaign_manager")
        self.user.groups.add(self.group1)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.campaign_department = StreamlinedCampaignDepartmentFactory()
        self.sms_campaign = StreamlinedCommunicationCampaignFactory(
            department=self.campaign_department
        )
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
        )
        self.sms_campaign.content = self.streamlined_message
        self.sms_campaign.save()
        self.customer = CustomerFactory()
        self.customer_2 = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_2 = AccountFactory(customer=self.customer_2)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)
        self.application_2 = ApplicationJ1Factory(customer=self.customer_2, account=self.account_2)
        self.application.mobile_phone_1 = '088321312312312'
        self.application_2.mobile_phone_1 = '12345'
        self.application_2.save()
        self.application.save()

    def test_campaign_detail_found_success(self):
        url = f'/streamlined_communication/campaign/{self.sms_campaign.id}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['name'], self.sms_campaign.name)
        self.assertEqual(response.json()['data']['department'], self.sms_campaign.department.name)

    def test_campaign_detail_not_found(self):
        invalid_campaign_id = 21
        url = f'/streamlined_communication/campaign/{invalid_campaign_id}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['errors'][0]['message'], 'Campaign not found')

    def test_campaign_detail_for_invalid_roles(self):
        self.user.groups.remove(self.group1)
        self.group2 = GroupFactory(name="product_manager")
        self.user.groups.add(self.group2)
        url = f'/streamlined_communication/campaign/{self.sms_campaign.id}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()['errors'][0]['message'],
            'You do not have permission to perform this action.',
        )


class TestUserDetailsView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group1 = GroupFactory(name="comms_campaign_manager")
        self.group2 = GroupFactory(name="product_manager")
        self.user.groups.add(self.group1)
        self.user.groups.add(self.group2)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_user_details_view(self):
        url = f'/streamlined_communication/get_user_details/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()['data']['roles_list'], [self.group1.name, self.group2.name]
        )


class TestAndroidPTPCard(APITestCase):
    def setUp(self):
        self.url = '/api/streamlined_communication/v1/android_ptp_card'
        self.client = APIClient()
        self.user = AuthUserFactory()

        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.force_login(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
            HTTP_X_APP_VERSION='8.49.0',
        )

        self.card_property = InfoCardPropertyFactory(
            title_color='#00ACF0',
            text_color='#00ACF0',
            title='Tentukan tanggal pembayaranmu',
        )

        self.message = StreamlinedMessageFactory(
            message_content='Kalau pilih tanggal lebih awal, bisa dapet cashback hingga 4%, lho!',
            info_card_property=self.card_property,
        )

        self.card = StreamlinedCommunicationFactory(
            message=self.message,
            extra_conditions=CardProperty.INAPP_PTP_BEFORE_SET_V2,
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
        )

        self.icon = ImageFactory(
            image_source=self.card_property.id,
            url='android_ptp_icon.png',
        )

        self.setting = FeatureSettingFactory(
            feature_name='in_app_ptp_setting',
            is_active=True,
            parameters={
                "dpd_start_appear": -10,
                "dpd_stop_appear": -1,
                "order_config": "force_top_order",
                "new_card_minimum_version": ">=8.48.0",
            },
        )

    @patch('juloserver.streamlined_communication.views.is_eligible_for_in_app_ptp')
    @patch('juloserver.streamlined_communication.views.get_ongoing_account_deletion_request')
    def test_ptp_showing(
        self,
        mock_account_deletion,
        mock_eligible_app_ptp,
    ):
        mock_eligible_app_ptp.return_value = True, False, None, None
        mock_account_deletion.return_value = False

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        self.assertTrue(data['is_showing'])

        self.assertEqual(data['title']['colour'], '#00ACF0')
        self.assertEqual(
            data['content']['text'],
            'Kalau pilih tanggal lebih awal, bisa dapet cashback hingga 4%, lho!',
        )
        self.assertIn('android_ptp_icon.png', data['image_icn'])

    @patch('juloserver.streamlined_communication.views.is_eligible_for_in_app_ptp')
    @patch('juloserver.streamlined_communication.views.get_ongoing_account_deletion_request')
    def test_ptp_not_showing(
        self,
        mock_account_deletion,
        mock_eligible_app_ptp,
    ):
        # already have ptp
        mock_eligible_app_ptp.return_value = True, True, None, None
        mock_account_deletion.return_value = False

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        self.assertFalse(data['is_showing'])

        # not eligible for ptp
        mock_eligible_app_ptp.return_value = False, True, None, None
        mock_account_deletion.return_value = False

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        self.assertFalse(data['is_showing'])

        # account deletion
        mock_eligible_app_ptp.return_value = True, False, None, None
        mock_account_deletion.return_value = True

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        self.assertFalse(data['is_showing'])

        # version doesn't match
        response = self.client.get(self.url, HTTP_X_APP_VERSION="8.47.0")
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']
        self.assertFalse(data['is_showing'])
