import logging
import time
import urllib.parse

import django_filters
from django.conf import settings
from django.core.exceptions import ValidationError
from rest_framework import viewsets
from rest_framework.filters import DjangoFilterBackend, SearchFilter
from rest_framework.pagination import PageNumberPagination

from juloserver.core.renderers import JuloJSONRenderer
from juloserver.customer_module.tasks.account_deletion_tasks import (
    handle_web_account_deletion_request,
)
from juloserver.customer_module.tasks.customer_related_tasks import (
    handle_web_consent_withdrawal_request,
)
from juloserver.cx_complaint_form.helpers import get_ip
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.utils import upload_file_as_bytes_to_oss
from juloserver.landing_page_api.constants import ConsentWithdrawalConst
from juloserver.landing_page_api.filters import InFilterBackend
from juloserver.landing_page_api.models import (
    FAQItem,
    LandingPageCareer,
    LandingPageSection,
)
from juloserver.landing_page_api.serializers import (
    DeleteAccountRequestSerializer,
    FAQItemSerializer,
    LandingPageCareerListSerializer,
    LandingPageCareerSerializer,
    LandingPageSectionSerializer,
)
from juloserver.standardized_api_response.utils import (
    custom_bad_request_response,
    general_error_response,
    internal_server_error_response,
    success_response,
)

logger = logging.getLogger(__name__)


class FAQItemFilter(django_filters.FilterSet):
    class Meta:
        model = FAQItem
        fields = ['type', 'parent']


class LandingPagePagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 10000


class FAQItemViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = []
    authentication_classes = ()

    renderer_classes = [JuloJSONRenderer]
    queryset = FAQItem.objects.find_visible().all()
    serializer_class = FAQItemSerializer
    pagination_class = LandingPagePagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filter_fields = ['type', 'parent']
    search_fields = ['title', 'rich_text', 'parent__title']


class LandingPageCareerViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = []
    authentication_classes = ()
    renderer_classes = [JuloJSONRenderer]
    queryset = LandingPageCareer.objects.active().all()
    serializer_class = LandingPageCareerSerializer
    serializer_classes = {'list': LandingPageCareerListSerializer}
    pagination_class = LandingPagePagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filter_fields = ['category']
    search_fields = ['title', 'category']

    def get_serializer_class(self, *args, **kwargs):
        try:
            return self.serializer_classes[self.action]
        except (KeyError, AttributeError):
            return super(LandingPageCareerViewSet, self).get_serializer_class()


class LandingPageSectionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = []
    authentication_classes = ()
    renderer_classes = [JuloJSONRenderer]
    queryset = LandingPageSection.objects.all()
    serializer_class = LandingPageSectionSerializer
    pagination_class = LandingPagePagination
    filter_backends = [DjangoFilterBackend, InFilterBackend, SearchFilter]
    filter_fields = ['name']


class DeleteAccountRequestViewSet(viewsets.ViewSet):
    permission_classes = []
    authentication_classes = ()

    def create(self, request, *args, **kwargs):
        try:
            data = self.validate_and_prepare_request_data(request.POST)
            handle_web_account_deletion_request.apply_async(args=[data])
        except (Exception, ValidationError) as e:
            if isinstance(e, ValidationError):
                return custom_bad_request_response(str(e))
            return internal_server_error_response(str(e))

        return success_response()

    def validate_and_prepare_request_data(self, request_dict):
        validation = DeleteAccountRequestSerializer(data=request_dict)
        if not validation.is_valid():
            raise ValidationError(validation.errors)

        timestamp = time.time()

        selfie_file_ext = request_dict.get("image_selfie").name.split('.')[-1]
        selfie_bytes = request_dict.get("image_selfie").file.read()
        selfie_remote_filepath = 'selfie-{}-{}-{}-{}.{}'.format(
            request_dict.get("nik"),
            request_dict.get("phone_number"),
            request_dict.get("email_address"),
            str(timestamp),
            selfie_file_ext,
        )
        encoded_selfie_remote_filepath = urllib.parse.quote(selfie_remote_filepath)
        upload_file_as_bytes_to_oss(
            settings.OSS_PUBLIC_BUCKET,
            selfie_bytes,
            encoded_selfie_remote_filepath,
        )

        ktp_file_ext = request_dict.get("image_ktp").name.split('.')[-1]
        ktp_bytes = request_dict.get("image_ktp").file.read()
        ktp_remote_filepath = 'ktp-{}-{}-{}-{}.{}'.format(
            request_dict.get("nik"),
            request_dict.get("phone_number"),
            request_dict.get("email_address"),
            str(timestamp),
            ktp_file_ext,
        )
        encoded_ktp_remote_filepath = urllib.parse.quote(ktp_remote_filepath)
        upload_file_as_bytes_to_oss(
            settings.OSS_PUBLIC_BUCKET,
            ktp_bytes,
            encoded_ktp_remote_filepath,
        )

        data = {
            "fullname": request_dict.get("full_name"),
            "nik": request_dict.get("nik"),
            "phone": request_dict.get("phone_number"),
            "email": request_dict.get("email_address"),
            "reason": request_dict.get("reason"),
            "details": request_dict.get("details"),
            "image_ktp_filepath": encoded_ktp_remote_filepath,
            "image_selfie_filepath": encoded_selfie_remote_filepath,
        }

        return data


class ConsentWithdrawalRequestView(DeleteAccountRequestViewSet):
    """
    Handle the creation of a consent withdrawal request through landing page web.

    Args:
        request (HttpRequest): The HTTP request object containing the POST data.
            The POST data should include the following fields:
            - full_name (str): The full name of the user.
            - nik (str): The national identification number of the user.
            - phone_number (str): The phone number of the user.
            - email_address (str): The email address of the user.
            - reason (str): The reason for the consent withdrawal.
            - details (str): Additional details provided by the user.
            - image_selfie (UploadedFile): The selfie image file uploaded by the user.
            - image_ktp (UploadedFile): The KTP image file uploaded by the user.
        *args: Additional positional arguments.
        **kwargs: Additional keyword arguments.

    Returns:
        Response: A success response if the request is processed successfully,
                    otherwise an internal server error response.
    """

    MAX_ATTEMPTS = 10
    CACHE_TTL = 3600  # 1 hour

    def _get_cache_key(
        self, identifier: str, email: str = "", phone: str = "", nik: str = ""
    ) -> str:
        return (
            "consent_withdrawal_request_web:" + identifier + "_" + email + "_" + phone + "_" + nik
        )

    def check_submission_eligibility(self, ip_address, email, phone, nik):
        """
        Check if submission is eligible based on IP address and identifiers.
        (max 5 attempts per hour).
        Returns (is_eligible, reason) tuple.
        """
        redis_client = get_redis_client()

        # Check 1: IP address rate limiting with the same field values
        cache_key = self._get_cache_key(ip_address, email, phone, nik)
        attempts = redis_client.get(cache_key)
        if attempts and int(attempts) >= self.MAX_ATTEMPTS:
            return False, ConsentWithdrawalConst.MSG_MAX_ATTEMPT_SUBMISSION

        # Check 2: IP address rate limiting with different field values
        ip_pattern = "consent_withdrawal_request_web:" + ip_address + "_*"
        ip_keys = redis_client.get_keys(ip_pattern)
        ip_count = 0

        for key in ip_keys:
            ttl = redis_client.get_ttl(key)
            if 0 < ttl <= self.CACHE_TTL:
                ip_count += 1

        if ip_count >= self.MAX_ATTEMPTS:
            return False, ConsentWithdrawalConst.MSG_MAX_ATTEMPT_SUBMISSION

        # Check 3: if any identifier (email, phone, nik) has reached max attempts
        identifiers = [(email, "email"), (phone, "phone"), (nik, "nik")]
        for identifier, field_name in identifiers:
            if not identifier:
                continue

            pattern = "consent_withdrawal_request_web:*" + identifier + "*"
            keys = redis_client.get_keys(pattern)
            identifier_count = 0

            for key in keys:
                ttl = redis_client.get_ttl(key)
                if 0 < ttl <= self.CACHE_TTL:
                    identifier_count += 1

            if identifier_count >= self.MAX_ATTEMPTS:
                return False, ConsentWithdrawalConst.MSG_FIELD_MAX_ATTEMPT_SUBMISSION % (field_name)

        cache_key = self._get_cache_key(ip_address, email, phone, nik)
        attempts = redis_client.get(cache_key)
        if not attempts:
            redis_client.set(cache_key, 1, self.CACHE_TTL)
        else:
            redis_client.increment(cache_key)

        return True, ""

    def create(self, request, *args, **kwargs):
        ip_address, _ = get_ip(request)
        if not ip_address:
            logger.info(
                {'action': 'consent_withdrawal_request_web', 'message': "IP address not found"}
            )
            return internal_server_error_response("IP address not found in request")

        post_data = request.POST
        email = post_data.get('email_address', '')
        phone = post_data.get('phone_number', '')
        nik = post_data.get('nik', '')

        # Check eligibility
        # is_eligible, reason = self.check_submission_eligibility(ip_address, email, phone, nik)
        # if not is_eligible:
        #     return general_error_response(reason)

        try:
            data = self.validate_and_prepare_request_data(post_data)
            handle_web_consent_withdrawal_request(data, ip_address)
            return success_response()
        except (Exception, ValidationError) as e:
            redis_client = get_redis_client()
            cache_key = self._get_cache_key(ip_address, email, phone, nik)
            attempts = redis_client.get(cache_key)
            if not attempts:
                redis_client.delete_key(cache_key)
            else:
                redis_client.decrement(cache_key)
            logger.error(
                {
                    'action': 'request_consent_withdrawal_web',
                    'request_data': {'email': email, 'nik': nik, 'phone': phone},
                    'ip_address': ip_address,
                    'message': str(e),
                }
            )

            if isinstance(e, ValidationError):
                return general_error_response(ConsentWithdrawalConst.MSG_DATA_INVALID)
            return internal_server_error_response("Terjadi kesalahan pada server")
