from juloserver.integapiv1.authentication import AnySourceAuthentication


class PartnershipOnboardingInternalAuthentication(AnySourceAuthentication):
    PARTNERSHIP_DIGITAL_SIGNATURE = "partnership-digital-signature"

    def whitelisted_sources(self):
        return [
            self.PARTNERSHIP_DIGITAL_SIGNATURE,
        ]

    def authenticate_header(self, request):
        return "Bearer"
