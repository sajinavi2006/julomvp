import logging
import random

from django.conf import settings
from django.utils import timezone

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Customer,
    ExperimentSetting,
    VoiceCallRecord,
)
from juloserver.julo.constants import ExperimentConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import (
    NexmoVoice,
    NexmoVoiceAction,
)


logger = logging.getLogger(__name__)


def choose_phone_number(account):
    feature_setting = ExperimentSetting.objects.filter(
        code=ExperimentConst.NEXMO_NUMBER_RANDOMIZER,
        is_active=True
    ).last()
    if not feature_setting or not feature_setting.start_date or not feature_setting.end_date:
        return None

    now = timezone.localtime(timezone.now())
    if now < feature_setting.start_date or now > feature_setting.end_date:
        return None

    setting_criteria = feature_setting.criteria
    phone_numbers = setting_criteria['phone_numbers']
    if phone_numbers:
        recent_number_used = get_most_recent_phone_numbers(
            len(phone_numbers)-1, account.customer.id)
        last_account_id_number = int(str(account.id)[-1])
        test_numbers = setting_criteria['test_numbers']
        if last_account_id_number in test_numbers:
            remain_numbers = list(set(phone_numbers).difference(set(recent_number_used)))
            if remain_numbers:
                return remain_numbers[-1]

    return None


def get_most_recent_phone_numbers(total_records, customer_id):
    return VoiceCallRecord.objects.filter(
        account_payment__account__customer=customer_id).exclude(call_from__isnull=True).values_list(
        'call_from', flat=True).order_by('-id')[:total_records]


def nexmo_product_type(product_line_code: int):
    """
    Get the product type for Nexmo based on product_line_code
    Args:
        product_line_code (int): Product line code
    Returns:
        str: Product type
    """
    product_map = {
        ProductLineCodes.J1: "J1",
        ProductLineCodes.JTURBO: "JTurbo",
        ProductLineCodes.GRAB: "GRAB",
    }
    product_type = product_map.get(product_line_code)
    if not product_type:
        raise ValueError(f"Invalid product line code: {product_line_code}")
    return product_type


class NexmoVoiceContentSanitizer:
    """
    This class responsible for validating and sanitizing content (ncco_data) supported by Nexmo.
    """

    def __init__(self, content: list, customer: Customer = None, input_webhook_url: str = None):
        self._content = content
        self._customer = customer
        self._input_webhook_url = input_webhook_url
        self.record_callback_url = (
            settings.BASE_URL + '/api/integration/v1/callbacks/voice-call-recording-callback'
        )
        self._success_validate = None
        self._is_sanitized = False
        self._voice_style_id = None

    @property
    def content(self):
        if not self._is_sanitized:
            raise JuloException("Content is not sanitized. Please call sanitize() method first")
        return self._content

    def validate(self):
        """
        Validate content (ncco_data) supported by Nexmo.
        Sample of valid content is
        [
            {
              "action": "talk",
              "voiceName": "Damayanti",
              "text": "Bayar sekarang dan dapatkan kesbek sebesar 3 persen."
            },
            {
              "action": "talk",
              "voiceName": "Damayanti",
              "text": "Tekan 1 untuk konfirmasi. Terima kasih"
            },
            {
              "action": "input",
              "maxDigits": 1
            }
        ]
        Returns:
            None
        """
        if self._success_validate:
            return

        content = self._content
        if not isinstance(content, list):
            raise ValueError("content is not a list")

        for idx, contentItem in enumerate(content):
            if not isinstance(contentItem, dict):
                raise ValueError("content item is not a dict")

            action = contentItem.get('action')
            if not action:
                raise ValueError("action is not valid")

            if action == NexmoVoiceAction.TALK:
                if 'text' not in contentItem:
                    raise ValueError("text is required for 'talk' action at index {}".format(idx))
            elif action == NexmoVoiceAction.INPUT:
                if not self._input_webhook_url:
                    raise ValueError(
                        "input_webhook arg is required for input action at index {}".format(idx)
                    )

        self._success_validate = True

    def sanitize(self):
        """
        Sanitize content (ncco_data) supported by Nexmo.
        Returns:
            dict: Sanitized content
        """
        self.validate()

        voice_style_id = self.voice_style_id()
        for contentItem in self._content:
            if contentItem['action'] == NexmoVoiceAction.INPUT:
                contentItem['eventUrl'] = [self._input_webhook_url]
            elif contentItem['action'] == NexmoVoiceAction.TALK:
                contentItem.update(
                    language=NexmoVoice.INDO,
                    style=voice_style_id,
                )
                contentItem["text"] = self._clean_text(contentItem["text"])

        self._is_sanitized = True

    def voice_style_id(self) -> int:
        """
        Get voice style id for the customer. If no customer data random value will be returned
        Returns:
            int: Voice style id. The possible value is
                from juloserver.streamlined_communication.constant.NexmoVoice
        """
        from juloserver.julo.clients.voice_v2 import JuloVoiceClientV2

        if self._voice_style_id is not None:
            return self._voice_style_id

        if self._customer:
            try:
                self._voice_style_id = JuloVoiceClientV2.rotate_voice_for_account_payment_reminder(
                    self._customer
                )
                return self._voice_style_id
            except Exception as exc:
                logger.exception(
                    {
                        "action": "NexmoVoiceContentSanitizer.get_voice_style_id",
                        "message": "failed to get voice style id for customer",
                        "customer_id": self._customer.id,
                        "exc": str(exc),
                    }
                )
                get_julo_sentry_client().captureException()

        self._voice_style_id = random.choice(NexmoVoice.all_voice_styles())
        return self._voice_style_id

    def add_record_action(self):
        """
        Add recording event to the content (ncco_data) supported by Nexmo.
        Args:
            content (list): content (ncco_data) supported by Nexmo.
            webhook_url (str): Webhook URL
        Returns:
            None
        """
        record_json_params = {"action": "record", "eventUrl": [self.record_callback_url]}
        self._content.insert(0, record_json_params)

        return self

    @staticmethod
    def _clean_text(text):
        return text.replace('JULO', 'Julo')
