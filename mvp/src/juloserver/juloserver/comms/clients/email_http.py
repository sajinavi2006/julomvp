import base64

import requests

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException


class EmailNotSent(JuloException):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        self.response = kwargs.pop("response", None)
        if self.response is not None and not self.request and hasattr(self.response, "request"):
            self.request = self.response.request
        super().__init__(*args)


class EmailServiceHTTPClient(object):
    """
    Email service client to send email using HTTP request.
    """
    def __init__(self, url: str, api_key: str):
        self.url = url
        self.api_key = api_key

    def send_email_handler(
        self,
        recipient: dict,
        subject: str = None,
        content: str = None,
        content_type: str = None,
        from_email: str = None,
        cc_email: list = None,
        bcc_email: list = None,
        template_id: str = None,
        template_variables: dict = None,
        attachments: list = None,
    ):
        endpoint = f"{self.url}/v1/email/send"
        headers = {"Content-Type": "application/json", "X_API_KEY": self.api_key}

        if not recipient or 'email' not in recipient or 'name' not in recipient:
            raise ValueError("Recipient must be provided with 'name' and 'email' fields")
        if not template_id:
            if not subject:
                raise ValueError("Subject is required if not using template")
            if not content:
                raise ValueError("Content is required if not using template")
            if not content_type:
                raise ValueError("Content type is required if not using template")

        processed_attachments = []
        if attachments:
            for attachment in attachments:
                if (
                    'content' not in attachment
                    or 'type' not in attachment
                    or 'filename' not in attachment
                ):
                    raise ValueError(
                        "Each attachment must have 'content', 'type', and 'filename' fields"
                    )
                try:
                    base64.b64decode(attachment['content'])
                except Exception:
                    with open(attachment['content'], "rb") as file:
                        attachment['content'] = base64.b64encode(file.read()).decode('utf-8')
                processed_attachments.append(attachment)

        payload = {
            "recipients": recipient,
            "cc_email": cc_email or [],
            "bcc_email": bcc_email or [],
            "attachments": processed_attachments or [],
        }

        if from_email:
            payload['from'] = from_email
        if template_id:
            payload['template_id'] = template_id
            payload['template_variables'] = template_variables or {}
        else:
            payload.update(
                {
                    'subject': subject,
                    'content': content,
                    'content_type': content_type,
                }
            )

        response = requests.post(endpoint, headers=headers, json=payload)

        if response.status_code != 200:
            raise EmailNotSent(
                f"Failed to send email: {response.status_code}, {response.text}",
                response=response,
            )

        return response.json()

    def send_email(
        self,
        recipient: dict,
        subject: str = None,
        content: str = None,
        content_type: str = None,
        from_email: str = None,
        cc_email: list = None,
        bcc_email: list = None,
        template_id: str = None,
        template_variables: dict = None,
        attachments: list = None,
        retry: int = 0,
    ):
        try:
            if retry == 3:
                raise EmailNotSent(
                    f"Attempting to send email. Failed {retry} times. Abort sending."
                )
            self.send_email_handler(
                recipient,
                subject,
                content,
                content_type,
                from_email,
                cc_email,
                bcc_email,
                template_id,
                template_variables,
                attachments,
            )
        except EmailNotSent as error:
            get_julo_sentry_client().captureException()
            raise EmailNotSent(error)
        except Exception:
            self.send_email(
                recipient,
                subject,
                content,
                content_type,
                from_email,
                cc_email,
                bcc_email,
                template_id,
                template_variables,
                attachments,
                retry=retry + 1,
            )
