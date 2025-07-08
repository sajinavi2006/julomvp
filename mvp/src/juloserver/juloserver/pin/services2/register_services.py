import logging
from datetime import timedelta
from rest_framework.status import HTTP_200_OK, HTTP_401_UNAUTHORIZED, HTTP_400_BAD_REQUEST

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from django.utils import timezone

from juloserver.standardized_api_response.utils import unauthorized_error_response
from juloserver.julo.models import (
    Customer,
)
from juloserver.pin.models import RegisterAttemptLog
from juloserver.standardized_api_response.utils import (
    general_error_response,
    locked_response,
    success_response,
)
from django.db.models import Q
from juloserver.registration_flow.services.google_auth_services import (
    verify_google_access_token,
    generate_email_verify_token,
)

logger = logging.getLogger(__name__)


def check_email_and_record_register_attempt_log(data, verify_email=False):
    def create_log_and_return(status=HTTP_400_BAD_REQUEST, valid_email=None):
        blocked_until = None
        if current_attempt >= max_attempt:
            blocked_until = tree_hour_later

        android_id = None
        valid_email = data['email'] if not valid_email else valid_email
        if 'android_id' in data:
            android_id = data['android_id']

        device_ios_user = data.get('device_ios_user', {})
        ios_id = device_ios_user['ios_id'] if device_ios_user else None

        register_attempt_data = dict(
            email=valid_email.lower(),
            nik=data['nik'],
            attempt=current_attempt,
            blocked_until=blocked_until,
            android_id=android_id,
            ios_id=ios_id,
        )
        email_token = None
        if verify_email:
            if is_email_verify:
                register_attempt_data.update(is_email_validated=is_email_verify)
                if status == HTTP_200_OK:
                    email_validation_code, email_token = generate_email_verify_token(valid_email)
                    register_attempt_data.update(
                        blocked_until=current_time, email_validation_code=email_validation_code
                    )
            else:
                register_attempt_data.update(is_email_validated=is_email_verify)

        RegisterAttemptLog.objects.create(**register_attempt_data)

        if verify_email and status == HTTP_200_OK:
            return success_response(data={'email_token': email_token})

        if blocked_until:
            return locked_response(
                message=locked_response_msg.get("message"), data=locked_response_msg
            )

        if verify_email and status == HTTP_401_UNAUTHORIZED:
            return unauthorized_error_response("Email atau NIK tidak ditemukan")

        error_response = {
            "title": "NIK / Email Tidak Valid atau Sudah Terdaftar",
            "message": (
                "Silakan masuk atau gunakan NIK / "
                "email yang valid dan belum didaftarkan di JULO, ya."
            ),
        }
        return general_error_response(message=error_response.get("message"), data=error_response)

    locked_response_msg = {
        "title": "NIK / Email Diblokir",
        "message": (
            "Kamu sudah 3 kali memasukkan NIK / "
            "email yang tidak valid atau sudah terdaftar. "
            "Silakan coba lagi dengan NIK / email berbeda dalam 3 jam ke depan."
        ),
    }
    max_attempt = 3
    current_attempt = 1
    current_time = timezone.localtime(timezone.now())
    tree_hour_later = current_time + timedelta(hours=3)

    preregister_log = RegisterAttemptLog.objects.filter(email=data['email'].lower()).last()
    if preregister_log:
        if preregister_log.blocked_until:
            if preregister_log.blocked_until >= current_time:
                return locked_response(
                    message=locked_response_msg.get("message"), data=locked_response_msg
                )
        else:
            current_attempt = preregister_log.attempt + 1

    is_email_verify = None
    valid_email = data['email']
    if verify_email:
        is_email_verify = True

        device_ios_user = data.get('device_ios_user', {})
        ios_id = device_ios_user['ios_id'] if device_ios_user else None
        is_ios_device = True if ios_id else False

        is_verify, valid_email = verify_google_access_token(
            access_token=data.get('google_auth_access_token'),
            email=data['email'],
            is_ios_device=is_ios_device,
        )
        if not is_verify:
            is_email_verify = False
            return create_log_and_return(status=HTTP_401_UNAUTHORIZED, valid_email=valid_email)

    user_queryset = User.objects.filter(username=data['nik'])
    customer_queryset = Customer.objects.filter(Q(nik=data['nik']) | Q(email=valid_email))

    if user_queryset.exists() or customer_queryset.exists():
        return create_log_and_return(valid_email=valid_email)
    if verify_email:
        return create_log_and_return(status=HTTP_200_OK, valid_email=valid_email)

    return success_response()
