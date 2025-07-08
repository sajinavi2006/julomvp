import string
import random
import hashlib
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from juloserver.julo.models import Application
from juloserver.application_form.constants import EmergencyContactConst
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.application_form.models import AgentAssistedWebToken
from juloserver.application_form.constants import AgentAssistedSubmissionConst
from juloserver.application_form.exceptions import WebTokenGenerationError

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


def generate_consent_form_code(length=5):
    characters = string.ascii_letters + string.digits
    while True:
        code = ''.join(random.choices(characters, k=length))
        if not Application.objects.filter(kin_consent_code=code).exists():
            return code


def generate_consent_form_url(application):
    if not application:
        return None
    if application.onboarding_id != 9:
        return None

    code = generate_consent_form_code()
    application.update_safely(kin_consent_code=code)

    if settings.ENVIRONMENT == 'prod':
        base_url = EmergencyContactConst.WEBFORM_URL_PROD
    elif settings.ENVIRONMENT == 'uat':
        base_url = EmergencyContactConst.WEBFORM_URL_UAT
    else:
        base_url = EmergencyContactConst.WEBFORM_URL_STAGING
    return "{base_url}/emergency-contact?data={code}".format(base_url=base_url, code=code)


def generate_sms_message(application):
    form_link = generate_consent_form_url(application)
    return (
        "Halo, {} memilihmu sbg kontak darurat di JULO. " "Lihat detail dan konfirmasi di sini: {}"
    ).format(application.fullname, form_link)


def get_application_for_consent_form(consent_code=None, application_xid=None):
    if consent_code:
        return Application.objects.filter(kin_consent_code=consent_code).last()
    elif application_xid:
        return Application.objects.filter(application_xid=application_xid).last()
    else:
        return None


def update_emergency_contact_consent(application, consent_response):
    application.update_safely(is_kin_approved=consent_response, refresh=True)

    if application.is_kin_approved in EmergencyContactConst.CAPPED_LIMIT_VALUES:
        return

    customer = application.customer
    customer.update_safely(customer_capped_limit=None)


def generate_web_token(expire_time, application_xid, random_length=3):
    try:
        random_variable = ''.join([str(random.randint(0, 9)) for _ in range(random_length)])
        plain_text = ''.join(
            [expire_time.strftime('%Y%m%d%H%M%S'), str(application_xid), random_variable]
        )
        return hashlib.sha256(plain_text.encode('utf-8')).hexdigest()
    except Exception as e:
        logger.warn(
            {
                'message': 'error in generate_web_token()',
                'application_xid': application_xid,
                'errors': str(e),
            }
        )
        raise WebTokenGenerationError('Failed to generate form')


def regenerate_web_token_data(web_token: AgentAssistedWebToken, application_xid):
    new_expire_time = get_expire_time_token()
    new_session_token = generate_web_token(new_expire_time, application_xid)

    web_token.session_token = new_session_token
    web_token.expire_time = new_expire_time
    web_token.is_active = True
    web_token.save()

    return new_session_token


def get_expire_time_token():
    return timezone.now() + timedelta(hours=AgentAssistedSubmissionConst.TOKEN_EXPIRE_HOURS)


@sentry.capture_exceptions
def get_url_form_for_tnc(application_id, application_xid=None, is_need_protocol_prefix=False):

    tnc_page_url = (
        settings.SALES_OPS_TNC_BASE_URL + '/sales-ops-assistance/tnc?application_xid={0}&token={1}'
    )

    if is_need_protocol_prefix:
        tnc_page_url = 'https://' + tnc_page_url

    session_form = AgentAssistedWebToken.objects.filter(application_id=application_id).last()
    if not session_form:
        logger.error(
            {
                'message': 'Invalid case session form is empty',
                'application_id': application_id,
            }
        )
        raise WebTokenGenerationError('Invalid case session data is empty!')

    if not session_form.session_token:
        logger.error(
            {
                'message': 'Invalid case session token is empty',
                'application_id': application_id,
            }
        )
        raise WebTokenGenerationError('Invalid case session token is empty!')

    logger.info(
        {
            'message': 'Success get url form for TNC',
            'application_id': application_id,
        }
    )

    if not application_xid:
        application = Application.objects.filter(pk=application_id).last()
        application_xid = application.application_xid

    return tnc_page_url.format(
        application_xid,
        session_form.session_token,
    )
