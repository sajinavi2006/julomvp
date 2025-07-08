import json
import requests

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import base64
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.julo.utils import get_file_from_oss
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.models import (
    Application,
    FeatureSetting,
    Image,
    ExperimentSetting,
)
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.julo.constants import ExperimentConst
from juloserver.face_recognition.constants import ImageType
from juloserver.merchant_financing.web_app.constants import MFStandardImageType
from juloserver.partnership.models import PartnershipImage
from juloserver.personal_data_verification.clients import (
    get_dukcapil_client,
    get_dukcapil_direct_client,
)
from juloserver.personal_data_verification.constants import (
    DUKCAPIL_DIRECT_METHODS,
    MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS,
    DukcapilFeatureMethodConst,
    FeatureNameConst,
    DukcapilFRClient,
    DUKCAPIL_FR_TYPE,
    DUKCAPIL_FR_POSITION,
    DUKCAPIL_FR_THRESHOLD,
)
from juloserver.personal_data_verification.models import (
    DukcapilResponse,
    DukcapilFaceRecognitionCheck,
)
from juloserver.personal_data_verification.clients.dukcapil_fr_client import get_dukcapil_fr_client
from juloserver.personal_data_verification.exceptions import SelfieImageNotFound
from juloserver.personal_data_verification.tasks import notify_dukcapil_asliri_remaining_balance

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

logger = JuloLog(__name__)


def get_dukcapil_verification_setting():
    """
    Get Dukcapil Verification setting.

    Returns:
        DukcapilVerificationSetting
    """
    return DukcapilVerificationSetting()


def get_dukcapil_verification_setting_leadgen(partner_name):
    """
    Get Dukcapil Verification setting. for leadgen
    if not found will use j1 setting
    Returns:
        DukcapilVerificationSetting or DukcapilVerificationSettingLeadgen
    """
    setting = DukcapilVerificationSettingLeadgen(partner_name)
    if not setting.setting:
        return DukcapilVerificationSetting()
    return setting


def get_dukcapil_verification_feature(method=None):
    """
    Get the FeatureSetting object of dukcapil_verification.

    Args:
        method (str | None):

    Returns:
        FeatureSetting | None
    """
    setting = get_dukcapil_verification_setting()
    if not setting.is_active or (method is not None and method != setting.method):
        return None

    return setting.setting


def get_dukcapil_verification_feature_leadgen(partner_name, method=None):
    """
    Get the FeatureSetting object of dukcapil_verification.

    Args:
        partner_name (string)
        method (str | None):

    Returns:
        FeatureSetting | None
    """
    setting = get_dukcapil_verification_setting_leadgen(partner_name)
    if not setting.is_active or (method is not None and method != setting.method):
        j1_feature_setting = get_dukcapil_verification_feature(method=method)
        return j1_feature_setting

    return setting.setting


def is_pass_dukcapil_verification_at_x130(application):
    """
    Check if the application is eligible for Dukcapil Verification.
    This handle is called/used in x130 application status.
    Only Possible using method with `asliri` or `direct_v2`.

    Args:
        application (Application): Application object.
    Returns:
        boolean
    """
    if application.is_partnership_leadgen():
        setting = get_dukcapil_verification_setting_leadgen(application.partner.name)
    else:
        # Skip if the setting is not eligible at x130.
        setting = DukcapilVerificationSetting()
    if not setting.is_triggered_at_x130:
        return True

    return is_pass_dukcapil_verification(application)


def is_pass_dukcapil_verification_at_x105(application):
    """
    Check if the application is eligible using Official Dukcapil API.
    This function is called after binary check from Ana server (handle_iti_ready)
    Only Possible using method with `direct`.

    Args:
        application (Application): The Application object

    Returns:
        bool
    """
    # getting the leadgen config if not found will get j1 config
    if application.is_partnership_leadgen():
        dukcapil_bypass = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DUKCAPIL_BYPASS_TOGGLE_LEADGEN, is_active=True
        ).last()
        if dukcapil_bypass:
            """
            parameters = {
                'partner_name': false
            }
            bypass_partner = None or False or True
            """
            bypass_partner = dukcapil_bypass.parameters.get(application.partner.name)
            if bypass_partner:
                return False
        else:
            dukcapil_bypass = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.DUKCAPIL_BYPASS_TOGGLE, is_active=True
            ).last()
            if dukcapil_bypass:
                bypass_parameters = dukcapil_bypass.parameters
                if bypass_parameters['dukcapil_bypass']:
                    if not application.is_julo_starter():
                        return False
    else:
        dukcapil_bypass = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DUKCAPIL_BYPASS_TOGGLE, is_active=True
        ).last()
        if dukcapil_bypass:
            bypass_parameters = dukcapil_bypass.parameters
            if bypass_parameters['dukcapil_bypass']:
                if not application.is_julo_starter():
                    return False

    if application.is_partnership_leadgen():
        setting = get_dukcapil_verification_setting_leadgen(application.partner.name)
    else:
        # Skip if the setting is not eligible at x105 (binary check).
        # Only "direct" method can be executed.
        setting = DukcapilVerificationSetting()
    if not setting.is_triggered_after_binary_check:
        return True

    return is_pass_dukcapil_verification(application)


def is_pass_dukcapil_verification(application):
    """
    Check if pass dukcapil verification based on the feature setting criteria.
    This function will not trigger any API hit if the there is a record in `ops.dukcapil_response`.

    Args:
        application (Application): Application

    Returns:
        bool: Will return True if the `dukcapil_verification` setting is not active.
    """
    from juloserver.julo.constants import FeatureNameConst as JuloConst
    from juloserver.julo.product_lines import ProductLineCodes

    existing_dukcapil_response = get_existing_dukcapil_response(application)
    if existing_dukcapil_response:
        return existing_dukcapil_response.is_eligible()

    if application.is_partnership_leadgen():
        setting = get_dukcapil_verification_setting_leadgen(application.partner.name)
    else:
        setting = get_dukcapil_verification_setting()

    dukcapil_mock_feature = FeatureSetting.objects.get_or_none(
        feature_name=JuloConst.DUKCAPIL_MOCK_RESPONSE_SET,
        is_active=True,
    )

    if (
        settings.ENVIRONMENT != 'prod'
        and dukcapil_mock_feature
        and (
            (
                'j-starter' in dukcapil_mock_feature.parameters['product']
                and application.is_julo_starter()
            )
            or (
                'j1' in dukcapil_mock_feature.parameters['product']
                and application.is_julo_one_product()
            )
            or (
                'partnership_merchant_financing' in dukcapil_mock_feature.parameters['product']
                and application.product_line.product_line_code == ProductLineCodes.AXIATA_WEB
            )
        )
    ):
        dukcapil_direct_client = get_dukcapil_direct_client(
            application=application,
            pass_criteria=setting.minimum_checks_to_pass,
        )
        return dukcapil_direct_client.mock_hit_dukcapil_official_api()

    if not setting.is_active:
        return True

    if setting.is_bypass_by_product_line(application.product_line_code):
        return True

    notify_dukcapil_asliri_remaining_balance()

    if setting.is_direct:
        dukcapil_direct_client = get_dukcapil_direct_client(
            application=application,
            pass_criteria=setting.minimum_checks_to_pass,
        )
        return dukcapil_direct_client.hit_dukcapil_official_api()

    if setting.is_asliri:
        dukcapil_client = get_dukcapil_client(
            application=application,
            pass_criteria=setting.minimum_checks_to_pass,
        )
        return dukcapil_client.hit_dukcapil_api()

    raise Exception('Undefined dukcapil verification method.')


def get_existing_dukcapil_response(application):
    existing_dukcapil_response = application.dukcapilresponse_set.last()

    detokenized_application = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'customer_xid': application.customer.customer_xid, 'object': application}],
        force_get_local_data=True,
    )
    application = detokenized_application[0]
    if not existing_dukcapil_response and application.ktp:
        duplicate_reapply_application_ids = (
            application.customer.application_set.exclude(id=application.id)
            .filter(ktp=application.ktp)
            .values_list('id', flat=True)
        )
        if duplicate_reapply_application_ids:
            existing_dukcapil_response = DukcapilResponse.objects.filter(
                application__in=list(duplicate_reapply_application_ids)
            ).last()

    if application.is_julo_starter() and existing_dukcapil_response:
        now = timezone.localtime(timezone.now())
        if existing_dukcapil_response.cdate <= now - relativedelta(days=1):
            return None

    return existing_dukcapil_response


def get_latest_dukcapil_response(application, source=None):
    queryset = application.dukcapilresponse_set
    if source:
        queryset = queryset.filter(source=source)

    return queryset.last()


class DukcapilVerificationSetting:
    def __init__(self):
        self.setting_helper = FeatureSettingHelper(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION,
        )

    @property
    def setting(self):
        """
        Return the Feature Setting object

        Returns:
            FeatureSetting
        """
        return self.setting_helper.setting

    @property
    def is_active(self):
        """
        Check if the feature setting is enabled.

        Returns:
            bool
        """
        return self.setting_helper.is_active

    @property
    def method(self):
        """
        Get the dukcapil method value.

        Returns:
            string | None
        """
        return self.setting_helper.get('method')

    @property
    def is_direct(self):
        """
        Check if integrated with the Official/Direct Dukcapil API

        Returns:
            bool
        """
        return self.method in DUKCAPIL_DIRECT_METHODS if self.method is not None else False

    @property
    def is_asliri(self):
        """
        Check if integrated with the Asliri API

        Returns:
            bool
        """
        return (
            self.method == DukcapilFeatureMethodConst.ASLIRI if self.method is not None else False
        )

    @property
    def minimum_checks_to_pass(self):
        """
        Get minimum criteria to pass.

        Returns:
            integer
        """
        return self.setting_helper.get(
            'minimum_checks_to_pass',
            MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS,
        )

    @property
    def is_triggered_after_binary_check(self):
        """
        Check if the Dukcapil logic is triggered after binary check (x105)

        Returns:
            bool
        """
        return self.method in {
            DukcapilFeatureMethodConst.DIRECT,
        }

    @property
    def is_triggered_at_x130(self):
        """
        Check if the Dukcapil logic is triggered at x130 (Account Limit Generation)

        Returns:
            bool
        """
        return self.method in {
            DukcapilFeatureMethodConst.ASLIRI,
            DukcapilFeatureMethodConst.DIRECT_V2,
        }

    def is_bypass_by_product_line(self, product_line_code):
        """
        Check if bypass the logic by product line

        Returns:
            bool
        """
        return product_line_code in self.setting_helper.get('bypass_by_product_line', [])


def is_dukcapil_fraud(application_id: int) -> bool:
    """
    Check if the application_id is dukcapil fraud or not.
    Args:
        application_id (int): Application ID
    Returns:
        bool
    """
    dukcapil_response = DukcapilResponse.objects.filter(application_id=application_id).last()
    if not dukcapil_response:
        return False

    return dukcapil_response.is_fraud()


def get_dukcapil_fr_setting():
    return FeatureSetting.objects.filter(
        feature_name='dukcapil_fr_threshold',
    ).last()


def dukcapil_fr_turbo_threshold(application_id: int):
    data = DukcapilFaceRecognitionCheck.objects.filter(
        application_id=application_id,
        response_code__isnull=False,
    ).last()

    if not data:
        return False

    result = ''
    setting = get_dukcapil_fr_setting()
    turbo_setting = setting.parameters.get('turbo')

    very_high_threshold = turbo_setting.get('very_high', 0)
    high_threshold = turbo_setting.get('high', 0)
    medium_threshold = turbo_setting.get('medium', 0)
    low_threshold = turbo_setting.get('low', 0)

    score = float(data.response_score)

    if score >= very_high_threshold:
        result = 'very_high'
    elif very_high_threshold > score >= high_threshold:
        result = 'high'
    elif high_threshold > score >= medium_threshold:
        result = 'medium'
    elif medium_threshold > score > low_threshold:
        result = 'low'
    elif score == 0:
        result = 'zero'

    return result


class DukcapilFRService:
    def __init__(self, application_id, nik: str):
        self.application_id = application_id
        self.nik = nik
        self.public_key = settings.DUKCAPIL_FR_PUBLIC_KEY
        self.request_data = {}
        self.dukcapil_fr_check = None
        self._experiment_setting = self._get_feature_setting()

    def face_recognition(self):
        if not self._experiment_setting:
            logger.info(
                'dukcapil_feature_setting_is_off|application_id={}'.format(self.application_id)
            )
            return

        image = Image.objects.filter(
            image_source=self.application_id, image_type=ImageType.SELFIE
        ).last()
        if not image:
            raise SelfieImageNotFound(
                'not found any selfie image with application_id {}'.format(self.application_id)
            )
        dukcapil_fr_client = get_dukcapil_fr_client()
        self._format_request_data(image, self.nik)
        self.dukcapil_fr_check = DukcapilFaceRecognitionCheck.objects.create(
            application_id=self.application_id,
            transaction_source=self.request_data['transactionSource'],
            client_customer_id=self.request_data['customer_id'],
            nik=self.nik,
            threshold=self.request_data['threshold'],
            image_id=image.id,
            template=self.request_data['template'],
            type=self.request_data['type'],
            position=self.request_data['position'],
        )
        self.request_data['transactionId'] = '{}-{}'.format(
            settings.ENVIRONMENT, self.dukcapil_fr_check.id
        )
        logger.info(
            'start_dukcapil_face_recognition|image_id={}, application_id={}, '
            'transactionId={}, ip={}'.format(
                image.id,
                self.application_id,
                self.request_data['transactionId'],
                self.request_data['ip'],
            )
        )
        get_direct_data = True
        result = {}
        if settings.ENVIRONMENT != 'prod':
            mock_feature = FeatureSetting.objects.filter(
                feature_name='mock_dukcapil_fr', is_active=True
            ).last()
            if mock_feature:
                get_direct_data = False
                result = mock_feature.parameters.get('mock_result', {})
            logger.info(
                'get_dukcapil_face_recognition_result_from_mock|'
                'image_id={}, application_id={}, result = {}, get_direct_data={}'.format(
                    image.id, self.application_id, result, get_direct_data
                )
            )

        if get_direct_data:
            result = dukcapil_fr_client.face_recognition(self.request_data)

        self.dukcapil_fr_check.update_safely(
            transaction_id=self.request_data['transactionId'],
            response_code=str(result.get('error', {}).get('errorCode')),
            response_score=str(result.get('matchScore', '')),
            quota_limiter=str(result.get('quotaLimiter', '')),
            raw_response=json.dumps(result),
        )

    def face_recognition_partnership(self):
        if not self._experiment_setting:
            logger.info(
                'dukcapil_feature_setting_is_off|application_id={}'.format(self.application_id)
            )
            return

        image = PartnershipImage.objects.filter(
            application_image_source=self.application_id, image_type=MFStandardImageType.KTP_SELFIE
        ).last()
        if not image:
            raise SelfieImageNotFound(
                'not found any selfie image with application_id {}'.format(self.application_id)
            )
        dukcapil_fr_client = get_dukcapil_fr_client()
        self._format_request_data_partnership(image, self.nik)
        self.dukcapil_fr_check = DukcapilFaceRecognitionCheck.objects.create(
            application_id=self.application_id,
            transaction_source=self.request_data['transactionSource'],
            client_customer_id=self.request_data['customer_id'],
            nik=self.nik,
            threshold=self.request_data['threshold'],
            image_id=image.id,
            template=self.request_data['template'],
            type=self.request_data['type'],
            position=self.request_data['position'],
        )
        self.request_data['transactionId'] = '{}-{}'.format(
            settings.ENVIRONMENT, self.dukcapil_fr_check.id
        )
        logger.info(
            'start_dukcapil_face_recognition|image_id={}, application_id={}, '
            'transactionId={}, ip={}'.format(
                image.id,
                self.application_id,
                self.request_data['transactionId'],
                self.request_data['ip'],
            )
        )
        get_direct_data = True
        result = {}
        if settings.ENVIRONMENT != 'prod':
            mock_feature = FeatureSetting.objects.filter(
                feature_name='mock_dukcapil_fr', is_active=True
            ).last()
            if mock_feature:
                get_direct_data = False
                result = mock_feature.parameters.get('mock_result', {})
            logger.info(
                'get_dukcapil_face_recognition_result_from_mock|'
                'image_id={}, application_id={}, result = {}, get_direct_data={}'.format(
                    image.id, self.application_id, result, get_direct_data
                )
            )

        if get_direct_data:
            result = dukcapil_fr_client.face_recognition(self.request_data)

        self.dukcapil_fr_check.update_safely(
            transaction_id=self.request_data['transactionId'],
            response_code=str(result.get('error', {}).get('errorCode')),
            response_score=str(result.get('matchScore', '')),
            quota_limiter=str(result.get('quotaLimiter', '')),
            raw_response=json.dumps(result),
        )

    @staticmethod
    def _get_feature_setting():
        today_date = timezone.localtime(timezone.now()).date()

        return (
            ExperimentSetting.objects.filter(code=ExperimentConst.DUKCAPIL_FR, is_active=True)
            .filter(
                (Q(start_date__date__lte=today_date) & Q(end_date__date__gte=today_date))
                | Q(is_permanent=True)
            )
            .last()
        )

    def _encrypt_data(self, data, encoding='utf-8'):
        key = RSA.import_key(self.public_key)
        cipher = PKCS1_v1_5.new(key)

        # encode to base64
        encoded_text = cipher.encrypt(bytes(data, encoding))
        cipher_text = base64.b64encode(encoded_text).decode(encoding)

        return cipher_text

    def _format_request_data(self, image: Image, nik):
        from juloserver.julo.utils import ImageUtil

        try:
            response = requests.get(image.image_url, stream=True)

            image_resize_handler = ImageUtil(response.raw)
            image_bytes = image_resize_handler.resize_image(
                195000, 0, ImageUtil.ResizeResponseType.BYTES, 10
            )
            logger.info(
                'get_dukcapil_face_recognition_request_data|'
                'image_id={}, application_id={}, size={}'.format(
                    image.id, self.application_id, len(image_bytes)
                )
            )

            base64_image = base64.b64encode(image_bytes).decode('utf-8')
        except Exception:
            raise

        threshold = (
            self._experiment_setting.criteria.get('score_threshold')
            if self._experiment_setting.criteria
            else DUKCAPIL_FR_THRESHOLD
        )

        application = Application.objects.filter(id=self.application_id).last()
        app_type = DukcapilFRClient.ANDROID
        if application and application.is_julo_one_ios():
            app_type = DukcapilFRClient.IOS

        self.request_data = dict(
            transactionId='',
            transactionSource=app_type,
            customer_id=settings.DUKCAPIL_FR_CUSTOMER_ID,
            nik=self._encrypt_data(nik),
            threshold=threshold,
            image=base64_image,
            template='',
            type=DUKCAPIL_FR_TYPE,
            position=DUKCAPIL_FR_POSITION,
            user_id=self._encrypt_data(settings.DUKCAPIL_FR_CLIENT_USER),
            password=self._encrypt_data(settings.DUKCAPIL_FR_CLIENT_PASSWORD),
            ip=settings.DUKCAPIL_FR_CLIENT_IP,
        )

    def _format_request_data_partnership(self, image: PartnershipImage, nik):
        try:
            image_file = get_file_from_oss(settings.OSS_MEDIA_BUCKET, image.url)
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        except Exception:
            raise

        threshold = (
            self._experiment_setting.criteria.get('score_threshold')
            if self._experiment_setting.criteria
            else DUKCAPIL_FR_THRESHOLD
        )

        self.request_data = dict(
            transactionId='',
            transactionSource=DukcapilFRClient.ANDROID,
            customer_id=settings.DUKCAPIL_FR_CUSTOMER_ID,
            nik=self._encrypt_data(nik),
            threshold=threshold,
            image=base64_image,
            template='',
            type=DUKCAPIL_FR_TYPE,
            position=DUKCAPIL_FR_POSITION,
            user_id=self._encrypt_data(settings.DUKCAPIL_FR_CLIENT_USER),
            password=self._encrypt_data(settings.DUKCAPIL_FR_CLIENT_PASSWORD),
            ip=settings.DUKCAPIL_FR_CLIENT_IP,
        )


class DukcapilVerificationSettingLeadgen(DukcapilVerificationSetting):
    """
    feature setting parameters contains
    parameters = {
        'bypass_by_product_line': [] # if have bypassed product line
        'partner_name_a': {
            'low_balance_quota_alert': 42000,
            'method': 'direct_v2',
            'minimum_checks_to_pass': 2,
        },
        'partner_name_b': {
            'low_balance_quota_alert': 42000,
            'method': 'direct_v2',
            'minimum_checks_to_pass': 2,
        }
    }

    """

    def __init__(self, partner_name):
        self.feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DUKCAPIL_VERIFICATION_LEADGEN,
            is_active=True,
        ).last()
        self.partner_name = partner_name

    @property
    def setting(self):
        """
        Return the Feature Setting object

        Returns:
            FeatureSetting
        """
        return self.feature_setting

    @property
    def is_active(self):
        """
        Check if the feature setting is enabled.

        Returns:
            bool
        """
        return True if self.feature_setting else False

    @property
    def method(self):
        """
        Get the dukcapil method value.

        Returns:
            string | None
        """
        partner_config = self.feature_setting.parameters.get(self.partner_name, None)
        if not partner_config:
            return None
        return partner_config.get('method', None)

    @property
    def minimum_checks_to_pass(self):
        """
        Get minimum criteria to pass.

        Returns:
            integer
        """
        partner_config = self.feature_setting.parameters.get(self.partner_name, None)
        if not partner_config:
            return MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS
        return partner_config.get(
            'minimum_checks_to_pass',
            MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS,
        )

    def is_bypass_by_product_line(self, product_line_code):
        """
        Check if bypass the logic by product line

        Returns:
            bool
        """
        if not self.feature_setting:
            return False
        return product_line_code in self.feature_setting.parameters.get(
            'bypass_by_product_line', []
        )
