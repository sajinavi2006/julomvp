from django.template import (
    Context,
    Template,
)
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.exceptions import EmailNotSent
from juloserver.julo.models import (
    Customer,
    EmailHistory,
)
from juloserver.moengage.constants import INHOUSE
from juloserver.streamlined_communication.models import StreamlinedCommunication


def get_email_service():
    client = get_julo_email_client()
    return EmailService(client)


class EmailService:
    def __init__(self, client):
        """
        Create EmailService object.
        Args:
            client (JuloEmailClient): The JuloEmailClient Objects.
        """
        self.client = client

    @staticmethod
    def prepare_email_context(customer: Customer, **kwargs) -> dict:
        """
        Prepare the email context for sending email. Mostly used for template rendering.
        Args:
            customer (Customer): Customer object.
        Returns:
            dict: Email's context.
        """
        from juloserver.moengage.services.data_constructors import (
            construct_user_attributes_for_realtime_basis,
        )
        context = construct_user_attributes_for_realtime_basis(customer)
        context['full_name'] = customer.fullname
        if not context['full_name']:
            context['full_name'] = "Yang Terhormat"

        context.update(**kwargs)
        context.update(customer_id=customer.id)
        return context

    def send_email_streamlined(
        self,
        streamlined: StreamlinedCommunication,
        context: dict,
        **kwargs,
    ):
        """
        Send email using streamlined communication as a content.
        Args:
            streamlined (StreamlinedCommunication): Streamlined communication object.
            context (dict): Please refer to send_email context.

        Returns:
            EmailHistory: Failed or success send will return EmailHistory object.
        """
        email_params = kwargs.copy()
        template_code = streamlined.template_code
        email_params.update(
            pre_header=streamlined.pre_header,
            subject=streamlined.subject,
            content=streamlined.message.message_content,
        )
        return self.send_email(template_code, context, **email_params)

    def send_email(self, template_code: str, context: dict, **kwargs):
        """
        Send email to sendgrid and save the email history.
        Args:
            template_code (str): The template code of the email
            context (dict): The context of the email.
                It used for the template rendering and sms history.
                For SMSHistory the available context are
                    - customer_id
                    - application_id
                    - account_payment_id
                    - payment_id
                    - lender_id
                    - partner_id

        Returns:
            EmailHistory: Failed or success send will return EmailHistory object.

        """
        email_params = kwargs.copy()
        self._validate_context(context)
        self._validate_email_params(email_params)

        email_params.update(
            subject=self._format_message(email_params['subject'], context),
            content=self._format_message(email_params['content'], context),
        )

        email_history = self._prepare_email_history(template_code, context, **email_params)
        email_history.save()

        try:
            response_status, body, headers = self.client.send_email(**email_params)
            sg_message_id = headers.get('X-Message-Id')
            error_message = None
            if response_status == 202:
                status = 'sent_to_sendgrid'
            else:
                status = 'error'
                error_message = body
        except EmailNotSent as e:
            status = 'error'
            error_message = str(e)
            sg_message_id = None

        email_history.update_safely(
            status=status,
            sg_message_id=sg_message_id,
            error_message=error_message
        )
        return email_history

    @staticmethod
    def _prepare_email_history(template_code, context: dict, **email_params):
        return EmailHistory(
            template_code=template_code,
            application_id=context.get("application_id"),
            payment_id=context.get("payment_id"),
            account_payment_id=context.get("account_payment_id"),
            customer_id=context.get("customer_id"),
            lender_id=context.get("lender_id"),
            partner_id=context.get("partner_id"),
            category=context.get("category"),
            campaign_id=context.get("campaign_id"),
            collection_hi_season_campaign_comms_setting_id=context.get(
                'collection_hi_season_campaign_comms_setting_id',
            ),
            source=INHOUSE,
            to_email=email_params['email_to'],
            cc_email=email_params.get('cc_email'),
            subject=email_params['subject'],
            pre_header=email_params.get('pre_header'),
            message_content=email_params['content'],
            status='pending',
        )

    @staticmethod
    def _validate_context(context: dict):
        """
        Simple validation for email context.

        Raises:
            ValueError: if context is invalid
        """
        if not context.get('customer_id'):
            raise ValueError('customer_id is required')

    @staticmethod
    def _validate_email_params(email_params: dict):
        """
        Simple validation for email context.

        Raises:
            ValueError: if email_params is invalid
            """
        required_fields = ['email_to', 'subject', 'content']
        for field in required_fields:
            if not email_params.get(field):
                raise ValueError(f'{field} is required')

    @staticmethod
    def _format_message(message, available_context):
        template = Template(message)
        return template.render(Context(available_context))
