from rest_framework.permissions import BasePermission

from juloserver.integapiv1.authentication import AnySourceAuthentication


class ApplicationPermission(BasePermission):

    message = "You are not permitted to access this application."

    def has_object_permission(self, request, view, application):
        return request.user == application.customer.user


class OnboardingInternalAuthentication(AnySourceAuthentication):
    DIGITAL_SIGNATURE = "digital-signature"

    def whitelisted_sources(self):
        return [
            self.DIGITAL_SIGNATURE,
        ]

    def authenticate_header(self, request):
        return "Bearer"
