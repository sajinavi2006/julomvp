from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy
from rest_framework import exceptions


class ResourceNotFound(exceptions.NotFound):
    default_detail = ugettext_lazy('Resource with id={resource_id} not found.')

    def __init__(self, resource_id=None):
        if resource_id is None:
            return super(ResourceNotFound, self).__init__()
        self.detail = force_text(self.default_detail).format(resource_id=resource_id)


class EmailNotVerified(exceptions.ValidationError):
    default_detail = ugettext_lazy('Email {email} is not verified')

    def __init__(self, email=None):
        if email is None:
            return super(EmailNotVerified, self).__init__()
        self.detail = force_text(self.default_detail).format(email=email)


class ResourceWithDetailNotFound(exceptions.NotFound):
    default_detail = ugettext_lazy('Resource not found.')

    def __init__(self, message=None):
        if message is None:
            return super(ResourceWithDetailNotFound, self).__init__()
        self.detail = force_text(message)
