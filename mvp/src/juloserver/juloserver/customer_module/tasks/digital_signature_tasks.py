from celery import task
from django.conf import settings

# from django.contrib.auth.models import User

from juloserver.customer_module.services.digital_signature import (
    DigitalSignature,
    DigitalSignatureException,
)
from juloserver.julo.models import Document, AuthUser as User
from juloserver.julo.services2.encryption import AESCipher


@task(queue='application_low')
def generate_user_key_pairs(user_id, encrypted_password):
    """Queue task to generate user key pairs

    Before you call this task, you must encrypt the password with
    AESCipher(settings.DIGITAL_SIGNATURE_BASE_KEY).encrypt()

    :param user_id: int
    :param encrypted_password: string User password
    """

    password = AESCipher(settings.DIGITAL_SIGNATURE_BASE_KEY).decrypt(encrypted_password)

    user = User.objects.get(pk=user_id)
    if not user.check_password(password):
        raise DigitalSignatureException("User password is wrong!")

    DigitalSignature(user).generate_key_pairs(password)


@task(queue='application_low')
def generate_document_signature(user_id, document_id, encrypted_password):
    """Queue task to generate document

    Before you call this task, you must encrypt the password with
    AESCipher(settings.DIGITAL_SIGNATURE_BASE_KEY).encrypt()

    :param user_id: int
    :param document_id: int
    :param encrypted_password: string User password
    """
    password = AESCipher(settings.DIGITAL_SIGNATURE_BASE_KEY).decrypt(encrypted_password)

    user = User.objects.get(pk=user_id)
    if not user.check_password(password):
        raise DigitalSignatureException("User password is wrong!")

    document = Document.objects.get(pk=document_id)
    DigitalSignature(user).sign(document, password)
