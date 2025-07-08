import logging

from juloserver.julo.models import Application
from juloserver.digisign.constants import RegistrationStatus
from juloserver.digisign.exceptions import (
    DigitallySignedRegistrationException,
)
from juloserver.digisign.models import DigisignRegistration
from juloserver.digisign.services.digisign_client import get_digisign_client


logger = logging.getLogger(__name__)


def get_registration_status(application: Application) -> str:
    registration = DigisignRegistration.objects.filter(
        customer_id=application.customer_id
    ).last()

    if registration and registration.registration_status in RegistrationStatus.DONE_STATUS:
        return registration.registration_status

    status_str = None
    client = get_digisign_client()
    resp_status = client.get_registration_status_code(application.id)
    if resp_status.get('success'):
        data = resp_status.get('data', {})
        status_code = data['registration_status']
        status_str = RegistrationStatus.get_status(status_code)

        if status_str:
            DigisignRegistration.objects.update_or_create(
                customer_id=application.customer_id,
                defaults={
                    'reference_number': data['reference_number'],
                    'verification_results': data.get('verification_results', {}),
                    'registration_status': status_str,
                    'error_code': data['error_code'],
                }
            )
    else:
        logger.error({
            'action': 'get_registration_status',
            'message': 'Request is failed',
            'response': resp_status,
            'application_id': application.id,
        })

    return status_str


def register_digisign(application: Application) -> DigisignRegistration:
    registration = DigisignRegistration.objects.filter(
        customer_id=application.customer_id
    ).last()

    if registration:
        raise DigitallySignedRegistrationException()


    client = get_digisign_client()
    resp_registration = client.register(application.id)
    if resp_registration.get('success'):
        data = resp_registration['data']
        status_str = RegistrationStatus.get_status(data['registration_status'])
        registration, created = DigisignRegistration.objects.update_or_create(
            customer_id=application.customer_id,
            defaults={
                'reference_number': data['reference_number'],
                'verification_results': data.get('verification_results', {}),
                'registration_status': status_str,
                'error_code': data['error_code'],
            }
        )
    else:
        logger.error({
            'action': 'register_digisign',
            'message': 'Request is failed',
            'response': resp_registration,
            'application_id': application.id,
        })

    return registration


def can_make_digisign(application: Application, force: bool = False) -> bool:
    status = get_registration_status(application)
    if force and status is None:
        try:
            registration = register_digisign(application)
        except DigitallySignedRegistrationException:
            logger.error({
                'action': 'can_make_digisign',
                'message': 'Application already registered: {}'.format(application.id),
            })
            return False
        except Exception as e:
            logger.error({
                'action': 'can_make_digisign',
                'message': 'Failed to register application: {}'.format(application.id),
                'error': str(e),
            })
            return False

        if registration:
            status = registration.registration_status

    return status in RegistrationStatus.DONE_STATUS
