from abc import (
    ABC,
    abstractmethod,
)

import phonenumbers

from juloserver.julo.exceptions import (
    SmsClientValidationFailure,
    VoiceClientValidationFailure,
)


class CommunicationClientAbstract(ABC):
    def validate_recipient(self, phone_number: str) -> str:
        if not phone_number:
            raise SmsClientValidationFailure('Recipient argument not provided.')
        try:
            if isinstance(phone_number, phonenumbers.PhoneNumber):
                parsed_phone_number = phone_number
            else:
                if not isinstance(phone_number, str):
                    raise SmsClientValidationFailure(
                        "Invalid phone number [{}] [type={}]".format(phone_number,
                            type(phone_number))
                    )

                if phone_number.startswith('62'):
                    phone_number = '+{}'.format(phone_number)

                parsed_phone_number = phonenumbers.parse(phone_number, "ID")

            if not phonenumbers.is_valid_number(parsed_phone_number):
                raise SmsClientValidationFailure(
                    'Invalid recipient phone number format: {}'.format(parsed_phone_number))

            e164_indo_phone_number = phonenumbers.format_number(
                parsed_phone_number, phonenumbers.PhoneNumberFormat.E164
            )
            return e164_indo_phone_number
        except phonenumbers.NumberParseException:
            raise SmsClientValidationFailure(
                "Invalid format phone number [{}]".format(phone_number))


class SmsVendorClientAbstract(CommunicationClientAbstract, ABC):
    def validate_message(self, message: str) -> str:
        if not message:
            raise SmsClientValidationFailure('Message argument not provided.')

        return message

    def send_sms(self, recipient: str, message: str):
        """
        Core function that should be executed for sending the sms.

        Args:
            recipient (str): Phone number to send sms.
            message (str): Message to send.
        Raises:
            SmsClientValidationFailure: If either arguments fail to pass validation.
        """
        recipient = self.validate_recipient(recipient)
        message = self.validate_message(message)

        return self.send_sms_handler(recipient, message)

    @abstractmethod
    def send_sms_handler(self, recipient: str, message: str):
        """
        Sending SMS handler. Logic should be implemented on inherited class.

        Args:
            recipient (str): Phone number to send sms.
            message (str): Message to send.
        """
        pass


class RobocallVendorClientAbstract(CommunicationClientAbstract, ABC):
    def validate_robocall(self, message: str) -> str:
        if not message:
            raise VoiceClientValidationFailure('Message argument not provided.')

        return message

    def send_robocall(self, recipient: str, message: str, randomize_voice: bool, **kwargs):
        """
        Core function that should be executed for sending the robocall.

        Args:
            recipient (str): Phone number to send sms.
            message (str): Message to send.
            randomize_voice (bool): False or True randomize robo voices.
        Raises:
            VoiceClientValidationFailure: If either arguments fail to pass validation.
        """
        recipient = self.validate_recipient(recipient)
        message = self.validate_robocall(message)

        return self.send_robocall_handler(recipient, message, randomize_voice, **kwargs)

    @abstractmethod
    def send_robocall_handler(self, recipient: str, message: str, randomize_voice: bool, **kwargs):
        """
        Sending Robocall handler. Logic should be implemented on inherited class.

        Args:
            recipient (str): Phone number to send sms.
            message (str): Message to send.
            randomize_voice (bool): False or True randomize robo voices.
        """
        pass
