from django.conf import settings
from rest_framework.permissions import BasePermission


class IsXendit(BasePermission):
    def has_permission(self, request, view):
        token = request.META.get('HTTP_X_CALLBACK_TOKEN', None)
        return token == settings.XENDIT_DISBURSEMENT_VALIDATION_TOKEN
