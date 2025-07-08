from datetime import datetime

import nexmo
import random
import logging
import time
import copy

from celery.task import task
from django.db.models import Q
from django.utils import timezone

from .infobip import JuloInfobipVoiceClient
from .voice import VoiceApiError
from . import get_julo_sentry_client
from juloserver.julo.utils import format_nexmo_voice_phone_number
from juloserver.julo.models import (
    CommsProviderLookup,
    ExperimentSetting,
    FeatureSetting,
    VoiceCallRecord,
    Payment,
)
from juloserver.julo.constants import (
    ExperimentConst,
    FeatureNameConst,
    VoiceTypeStatus,
    WorkflowConst,
)
from juloserver.julo.services2.voice import get_voice_template
from ..exceptions import VoiceNotSent
from juloserver.loan_refinancing.clients.voice import LoanRefinancingVoiceClient
from juloserver.account_payment.models import AccountPayment
from juloserver.streamlined_communication.models import StreamlinedCommunication
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform, NexmoVoice, nexmo_voice_map, id_to_en_gender_map, NexmoVoiceAction)
from juloserver.nexmo.services import choose_phone_number
from juloserver.nexmo.constants import RANDOMIZER_PHONE_NUMBER_TEMPLATE_CODES
from juloserver.streamlined_communication.utils import (
    render_stream_lined_communication_content_for_infobip_voice,
)
from juloserver.nexmo.models import RobocallCallingNumberChanger
from juloserver.julo.product_lines import ProductLineCodes

logger = logging.getLogger(__name__)
client = get_julo_sentry_client()


class JuloVoiceClientV2(LoanRefinancingVoiceClient, object):
    def __init__(
        self,
        voice_key,
        voice_secret,
        voice_application_id,
        private_key,
        julo_phone_number,
        base_url,
        test_number,
    ):

        self.client = nexmo.Client(
            application_id=voice_application_id,
            private_key=private_key,
            key=voice_key,
            secret=voice_secret,
        )

        self.client.api_host = 'api-ap-3.vonage.com'
        self.julo_phone_numbers = julo_phone_number.split(",")
        self.base_url = base_url
        self.test_number = test_number

    def rotate_nexmo_caller(self, application_id: int) -> str:
        """
        Used to ratate nexmo number so that customer will receive call from a random pool of number.
        This is to avoid customer receiving call from the same number multiple times while skipping
            other numbers.

        Args:
            application_id (int): Application id that will be used to filter VoiceCallRecord.

        Returns:
            str: A random number choosen from rotation.

        TODO:
            This function will break if RobocallCallingNumberChanger has no record that fit.
        """
        now = datetime.now()
        active_numbers = RobocallCallingNumberChanger.objects.filter(
            Q(start_date__lte=now, end_date__gte=now) |
            Q(start_date__lte=now, end_date__isnull=True) |
            Q(start_date__isnull=True, end_date__gte=now) |
            Q(start_date__isnull=True, end_date__isnull=True)
        ).values_list('new_calling_number', flat=True)
        active_number_count = active_numbers.count()

        if active_number_count < 1:
            return RobocallCallingNumberChanger.objects.first().new_calling_number

        voice_call_record_phone_numbers = VoiceCallRecord.objects.filter(
            application_id=application_id
        ).order_by('-cdate').values_list('call_from', flat=True
        )[:active_number_count - 1]

        unused_numbers = [valid_number for valid_number in active_numbers
                          if valid_number not in voice_call_record_phone_numbers]

        return random.choice(unused_numbers)

    def create_call(self, phone_number: str, application_id: int, ncco_dict: dict, retry: int = 0,
                    call_from: str = None, capture_sentry: bool=True):
        """
        Initiate call with nexmo api v2 sdk.

        Args:
            phone_number (str): Target for robocall.
            application_id (int): Application id of the customer used to rotate nexmo number.
            ncco_dict (dict): Contain data required for nexmo to process. Typically provided by
                            juloserver.julo.services2.get_voice_template
            retry (int): Number of retries. Reserved for retry mechanism.
            call_from (str): Number that Nexmo will use to call the target. @deprecated
        """
        call_from = self.randomize_call_number(application_id, call_from)

        data = {
            'to': [{'type': 'phone', 'number': phone_number}],
            'from': {'type': 'phone', 'number': call_from},
            'ncco': ncco_dict
        }

        try:
            response = self.client.create_call(data)
        except Exception as e:
            if capture_sentry:
                client.captureException()
            raise Exception(e)

        # This is so that our API credentials are not entirely logged,
        # only the last 2 chars for debugging
        safe_params = data.copy()
        logger.info({
            'action': 'initiate call with nexmo api v2 sdk',
            'params': safe_params,
        })

        return response

    def payment_reminder(self, phone_number, payment_id, streamlined_id, template_code=None,
                         test_robocall_content=None):
        """
        send voice for payment reminder
        """
        ncco_dict = get_voice_template(
            VoiceTypeStatus.PAYMENT_REMINDER, payment_id, streamlined_id, test_robocall_content)
        payment = Payment.objects.get_or_none(id=payment_id)
        voice_style = None
        application_id = None
        if payment:
            voice_style = self.update_ncco_voice_style(ncco_dict, payment.loan.customer)
            application_id = payment.loan.application.id

        voice_call_record = VoiceCallRecord.objects.create(
                template_code=template_code,
                event_type=VoiceTypeStatus.PAYMENT_REMINDER,
                voice_identifier=payment_id,
                voice_style_id=voice_style)

        response = self.create_call(format_nexmo_voice_phone_number(phone_number), application_id,
            ncco_dict)

        logger.info({
            'action': 'sending_voice_call_for_payment_reminder',
            'payment_id': payment_id,
            'response': response
        })

        if response.get('conversation_uuid'):
            voice_call_record.update_safely(
                status=response['status'],
                direction=response['direction'],
                uuid=response['uuid'],
                conversation_uuid=response['conversation_uuid'],
                )
        else:
            voice_call_record.update_safely(status=response.get('status'))

        return response

    def account_payment_reminder(
            self, phone_number: str, account_payment_id: int, streamlined_id: int,
            template_code: str = None, test_robocall_content: str = None, is_j1: bool = True,
            is_grab: bool = False
    ):
        """
        Call customer for payment reminder.

        Args:
            phone_number (str): Target phone number to call.
            account_payment_id (int): AccountPayment id of call target.
            streamlined_id (int): StreamlinedCommunication id.
            template_code (str): Template code based on StreamlinedCommunication.
            test_robocall_content (str): Any string as message from the robocall during test call.
            is_j1 (bool): Whether the call is for J1.
            is_grab (bool): Whether the call is for Grab.
        """
        if is_grab:
            return

        is_jturbo = False

        streamline = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
        if streamline.product == 'nexmo_turbo':
            is_j1, is_grab, is_jturbo = False, False, True

        application = None
        application_id = None
        account_payment = AccountPayment.objects.get(pk=account_payment_id)
        if account_payment:
            if is_jturbo:
                application = account_payment.account.application_set.filter(workflow__name=WorkflowConst.JULO_STARTER).last()
            else:
                application = account_payment.account.last_application
            application_id = application.id

        voice_call_data = dict(
            template_code=template_code,
            event_type=VoiceTypeStatus.PAYMENT_REMINDER,
            application=application,
            voice_identifier=account_payment_id,
            account_payment_id=account_payment_id,
        )

        ncco_dict = get_voice_template(
            VoiceTypeStatus.PAYMENT_REMINDER, account_payment_id,
            streamlined_id, test_robocall_content, is_j1=is_j1,
            is_grab=is_grab, is_jturbo=is_jturbo,
        )

        account_id_last_digit = int(str(account_payment.account_id)[-1])
        ab_experiment_setting = ExperimentSetting.objects.get(
            code=ExperimentConst.ROBOCALL_1WAY_VENDORS_EXPERIMENT
        )
        experiment_template_code = ['nexmo_robocall_j1_-5', 'nexmo_robocall_j1_-3']
        today = timezone.localtime(timezone.now())
        criteria = ab_experiment_setting.criteria
        if (
            ab_experiment_setting.is_active
            and ab_experiment_setting.start_date <= today <= ab_experiment_setting.end_date
            and account_id_last_digit in criteria['infobip']['account_id_tail']
            and streamline.template_code in experiment_template_code
        ):
            comms_provider_lookup = CommsProviderLookup.objects.get(provider_name='Infobip')
            voice_call_data.update(comms_provider=comms_provider_lookup)
            voice_call_record = VoiceCallRecord.objects.create(**voice_call_data)

            message = render_stream_lined_communication_content_for_infobip_voice(ncco_dict)

            infobip_client = JuloInfobipVoiceClient(criteria['infobip']['calling_number'])
            response, voice_id = infobip_client.send_robocall(
                phone_number, message, True, **{'customer': application.customer}
            )
            voice_call_record.update_safely(voice_style_id=voice_id)

            if 'requestError' in response:
                voice_call_record.update_safely(
                    status='errors',
                    uuid=response['requestError']['serviceException']['messageId'],
                )
            else:
                voice_call_record.update_safely(
                    status=response['messages'][0]['status']['groupName'],
                    uuid=response['messages'][0]['messageId'],
                )
        else:
            voice_style = None
            if (account_payment and streamline
                and streamline.communication_platform == CommunicationPlatform.ROBOCALL):
                voice_style = self.update_ncco_voice_style(ncco_dict, application.customer)
            voice_call_data.update(voice_style_id=voice_style)

            comms_provider_lookup = CommsProviderLookup.objects.get(provider_name='Nexmo')
            voice_call_data.update(comms_provider=comms_provider_lookup)

            nexmo_phone_number = None
            if streamline.template_code in RANDOMIZER_PHONE_NUMBER_TEMPLATE_CODES:
                nexmo_phone_number = choose_phone_number(account_payment.account)
            if nexmo_phone_number:
                voice_call_data.update(is_experiment=True)

            if application.product_line_code in ProductLineCodes.DANA_PRODUCT:
                voice_call_data.update(event_type=VoiceTypeStatus.PAYMENT_REMINDER_DANA)

            voice_call_record = VoiceCallRecord.objects.create(**voice_call_data)

            if application.product_line_code in ProductLineCodes.DANA_PRODUCT:
                from juloserver.julo.tasks2.outbound_call_tasks import vonage_rate_limit_call_dana

                vonage_rate_limit_call_dana.apply_async(
                    args=(
                        voice_call_record.id,
                        format_nexmo_voice_phone_number(phone_number),
                        application_id,
                        ncco_dict,
                    ),
                    kwargs={'call_from': nexmo_phone_number},
                )
            else:
                from juloserver.julo.tasks2.outbound_call_tasks import vonage_rate_limit_call

                vonage_rate_limit_call.apply_async(
                    args=(
                        voice_call_record.id,
                        format_nexmo_voice_phone_number(phone_number),
                        application_id,
                        ncco_dict,
                    ),
                    kwargs={'call_from': nexmo_phone_number},
                )

        logger.info({
            'action': 'sending_voice_call_for_payment_reminder',
            'vendor': comms_provider_lookup.provider_name,
            'account_payment_id': account_payment_id,
        })

    def account_payment_reminder_grab(
            self, phone_number: str, payment_id: int, streamlined_id: int,
            template_code: str = None, test_robocall_content: str = None, is_j1: bool = True,
            is_grab: bool = False
    ):
        """
        Call customer for payment reminder.

        Args:
            phone_number (str): Target phone number to call.
            streamlined_id (int): StreamlinedCommunication id.
            template_code (str): Template code based on StreamlinedCommunication.
            test_robocall_content (str): Any string as message from the robocall during test call.
            is_j1 (bool): Whether the call is for J1.
            is_grab (bool): Whether the call is for Grab.
            payment_id (int): The payment ID is passed through for Grab Payments
        """
        if is_grab:
            is_j1 = False
        else:
            return False
        streamline = StreamlinedCommunication.objects.get_or_none(pk=streamlined_id)
        if not streamline:
            logger.exception({
                'action': 'send_voice_payment_reminder_grab',
                'message': "Streamlined Communication not found for id {}".format(streamlined_id)
            })
            return
        application = None
        application_id = None

        payment = Payment.objects.get_or_none(pk=payment_id)
        account_payment = payment.account_payment
        account_payment_id = account_payment.id
        if account_payment:
            application = account_payment.account.last_application
            application_id = application.id
        voice_call_data = dict(
            template_code=template_code,
            event_type=VoiceTypeStatus.PAYMENT_REMINDER,
            application=application,
            voice_identifier=payment_id,
            account_payment_id=account_payment.id,
        )

        ncco_dict = get_voice_template(
            VoiceTypeStatus.PAYMENT_REMINDER, payment_id, streamlined_id,
            test_robocall_content, is_j1=is_j1, is_grab=is_grab)

        account_id_last_digit = int(str(account_payment.account_id)[-1])
        ab_experiment_setting = ExperimentSetting.objects.get(
            code=ExperimentConst.ROBOCALL_1WAY_VENDORS_EXPERIMENT
        )
        experiment_template_code = ['nexmo_robocall_j1_-5', 'nexmo_robocall_j1_-3']
        today = timezone.localtime(timezone.now())
        criteria = ab_experiment_setting.criteria
        if (
            ab_experiment_setting.is_active
            and ab_experiment_setting.start_date <= today <= ab_experiment_setting.end_date
            and account_id_last_digit in criteria['infobip']
            and streamline.template_code in experiment_template_code
        ):
            comms_provider_lookup = CommsProviderLookup.objects.get(provider_name='Infobip')
            voice_call_data.update(comms_provider=comms_provider_lookup)
            voice_call_record = VoiceCallRecord.objects.create(**voice_call_data)

            message = render_stream_lined_communication_content_for_infobip_voice(ncco_dict)

            infobip_client = JuloInfobipVoiceClient()
            response, voice_id = infobip_client.send_robocall(
                phone_number, message, True, **{'customer': application.customer}
            )
            voice_call_record.update_safely(voice_style_id=voice_id)

            if 'requestError' in response:
                voice_call_record.update_safely(
                    status='errors',
                    uuid=response['requestError']['serviceException']['messageId'],
                )
            else:
                voice_call_record.update_safely(
                    status=response['messages'][0]['status']['groupName'],
                    uuid=response['messages'][0]['messageId'],
                )
        else:
            voice_style = None
            if (account_payment and streamline
                and streamline.communication_platform == CommunicationPlatform.ROBOCALL):
                voice_style = self.update_ncco_voice_style(ncco_dict, application.customer)
            voice_call_data.update(voice_style_id=voice_style)

            comms_provider_lookup = CommsProviderLookup.objects.get(provider_name='Nexmo')
            voice_call_data.update(comms_provider=comms_provider_lookup)

            nexmo_phone_number = None
            if streamline.template_code in RANDOMIZER_PHONE_NUMBER_TEMPLATE_CODES:
                nexmo_phone_number = choose_phone_number(account_payment.account)
            if nexmo_phone_number:
                voice_call_data.update(is_experiment=True)
            voice_call_record = VoiceCallRecord.objects.create(**voice_call_data)

            from juloserver.julo.tasks2.outbound_call_tasks import vonage_rate_limit_call

            vonage_rate_limit_call.apply_async(
                args=(
                    voice_call_record.id,
                    format_nexmo_voice_phone_number(phone_number),
                    application_id,
                    ncco_dict,
                ),
                kwargs={'call_from': nexmo_phone_number, 'is_grab': True},
            )

        logger.info({
            'action': 'sending_voice_call_for_payment_reminder',
            'vendor': comms_provider_lookup.provider_name,
            'account_payment_id': account_payment_id,
        })


    def ptp_payment_reminder(self, phone_number, payment_id, template_code=None):
        """
        send voice for payment reminder
        """
        ncco_dict = get_voice_template(VoiceTypeStatus.PTP_PAYMENT_REMINDER, payment_id)
        payment = Payment.objects.get_or_none(id=payment_id)
        voice_style = None
        application_id = None
        if payment:
            voice_style = self.update_ncco_voice_style(ncco_dict, payment.loan.customer)
            application_id = payment.loan.application.id

        response = self.create_call(format_nexmo_voice_phone_number(phone_number), application_id,
            ncco_dict)

        logger.info({
            'action': 'sending_voice_call_for_ptp_payment_reminder',
            'payment_id': payment_id,
            'response': response
        })

        if not response.get('conversation_uuid'):
            raise VoiceApiError('Error {}'.format(response))
        else:
            VoiceCallRecord.objects.create(
                event_type=VoiceTypeStatus.PTP_PAYMENT_REMINDER,
                voice_identifier=payment_id, status=response['status'],
                direction=response['direction'], uuid=response['uuid'],
                conversation_uuid=response['conversation_uuid'],
                template_code=template_code,
                voice_style_id=voice_style)

        return response

    def test_nexmo_call(self):
        ncco = [
            {
                "action": "talk",
                "text": "You are listening to a test text-to-speech call made with Nexmo Voice API",
                "language": NexmoVoice.INDO,
                "style": 0
            }
        ]

        response = self.create_call(format_nexmo_voice_phone_number(self.test_number), ncco)

        logger.info({
            'action': 'test_nexmo_call',
            'response': response
        })

        if not response.get('conversation_uuid'):
            raise VoiceApiError('Error {}'.format(response))

        return response

    @staticmethod
    def rotate_voice_for_account_payment_reminder(customer):
        infobip_comms_provider = CommsProviderLookup.objects.get(provider_name='Nexmo')
        last_voice_call_record = VoiceCallRecord.objects.filter(
            application__customer=customer, comms_provider=infobip_comms_provider
        ).values('voice_style_id').last()

        all_voices = nexmo_voice_map[NexmoVoice.INDO].get(
                id_to_en_gender_map.get(customer.gender, 'male'))
        if last_voice_call_record:
            previous_voice = last_voice_call_record['voice_style_id']
            if previous_voice is not None:
                next_voices = copy.copy(all_voices)
                try:
                    next_voices.remove(previous_voice)
                except ValueError:
                    client.captureException()
                return random.choice(next_voices)

        return random.choice(all_voices)

    def update_ncco_voice_style(self, ncco_dict, customer):
        style = self.rotate_voice_for_account_payment_reminder(customer)
        for ncco_action in ncco_dict:
            if isinstance(ncco_action, dict) and \
                    ncco_action.get('action') == NexmoVoiceAction.TALK:
                ncco_action.update(language=NexmoVoice.INDO,
                                   style=style)
                current_text = ncco_action.get('text', '')
                if 'JULO Anda' in current_text:
                    new_context = current_text.replace('JULO Anda', 'Julo Anda')
                    ncco_action['text'] = new_context

        return style

    def randomize_call_number(self, application_id: int, manual_call_from: str) -> str:
        """
        Evaluates if call number should be randomized and returns expected number.

        Args:
            application_id (int): Application model primary key for checking rotation.
            manual_call_from (str): Manually selected call number.

        Returns:
            (str): The number that will be used to call.
        """
        number_randomizer_feature_status = FeatureSetting.objects.get(
            feature_name=FeatureNameConst.NEXMO_NUMBER_RANDOMIZER
        ).is_active
        if number_randomizer_feature_status:
            call_from = manual_call_from or self.rotate_nexmo_caller(application_id)
        else:
            call_from = (
                manual_call_from or RobocallCallingNumberChanger.objects.first().new_calling_number
            )

        return call_from
