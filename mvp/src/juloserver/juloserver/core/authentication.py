import jwt
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import ugettext as _
from jwt import DecodeError
from rest_framework.authentication import TokenAuthentication
from rest_framework_jwt.authentication import JSONWebTokenAuthentication
from rest_framework import exceptions
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.grab.models import GrabCustomerData
from django.conf import settings
from typing import Union, Tuple
from juloserver.core.constants import JWTErrorConstant

class JuloJSONWebTokenAuthentication(JSONWebTokenAuthentication):

    def authenticate_credentials(self, payload):
        User = get_user_model()
        user_key = "mvp_user_id"
        if user_key not in payload:
            msg = _('Invalid payload.')
            raise exceptions.AuthenticationFailed(msg)
        try:
            user = User.objects.get(pk=payload[user_key])
        except User.DoesNotExist:
            msg = _('Invalid signature.')
            raise exceptions.AuthenticationFailed(msg)

        return user


class JWTAuthentication(TokenAuthentication):
    SECRET_KEYS = {
        0: "jwt-kid",
        ProductLineCodes.GRAB: settings.GRAB_JWT_SECRET_KEY
    }

    def __init__(self, kid="jwt-kid", algorithm="HS256", secret_key="jwt-kid"):
        self.kid = kid
        self.algorithm = algorithm
        self._request = None
        self.secret_key = secret_key

    def authenticate(self, request):
        self._request = request
        return super().authenticate(request)

    def decode_token(self, token, verify_signature=True):
        """Decode the JWT token and handle any errors."""
        try:
            if not verify_signature:
                payload = jwt.decode(token, options={"verify_signature": False})
            else:
                payload = jwt.decode(token, self.secret_key, algorithms=self.algorithm)
        except DecodeError:
            raise exceptions.AuthenticationFailed(JWTErrorConstant.INVALID_TOKEN)
        return payload

    def _get_product_id(self, payload):
        product = payload.get("product", "")
        if product.isnumeric():
            return int(product)
        return 0

    def authenticate_credentials(self, token) -> Tuple[Union[User, GrabCustomerData], None]:
        payload = self.decode_token(token, verify_signature=False)

        if not "expired_at" in payload:
            raise exceptions.AuthenticationFailed(JWTErrorConstant.EXPIRED_TOKEN)

        expired_at = parse_datetime(payload.get("expired_at"))
        now = timezone.localtime(timezone.now())
        if not expired_at or now > expired_at:
            raise exceptions.AuthenticationFailed(JWTErrorConstant.EXPIRED_TOKEN)

        product = self._get_product_id(payload)
        if product == ProductLineCodes.GRAB:
            self.secret_key = self.SECRET_KEYS[product]
            payload = self.decode_token(token)
            return self._get_grab_customer_data(payload), None
        else:
            # we need to decode again with verify signature
            payload = self.decode_token(token)

        application_id = payload["application_id"]
        user = self._get_user_from_application(application_id)

        return user, None

    @staticmethod
    def _get_user_from_application(application_id):
        from juloserver.julo.models import Application

        try:
            application = Application.objects.select_related("customer__user").get(pk=application_id)
            user = application.customer.user
            return user
        except Application.DoesNotExist as err:
            raise exceptions.AuthenticationFailed(str(err))

    def _get_grab_customer_data(self, payload):
        user_identifier_id = payload.get("user_identifier_id", None)
        if not user_identifier_id:
            raise exceptions.AuthenticationFailed(JWTErrorConstant.MISSING_USER_IDENTIFIER)

        try:
            return GrabCustomerData.objects.get(id=user_identifier_id)
        except GrabCustomerData.DoesNotExist as err:
            raise exceptions.AuthenticationFailed(str(err))

    def generate_token(self, payload, key):
        token = jwt.encode(
            payload=payload,
            key=key,
            headers={
                "alg": self.algorithm,
                "typ": "JWT",
                "kid": self.kid
            }
        )
        return token.decode('utf-8')

