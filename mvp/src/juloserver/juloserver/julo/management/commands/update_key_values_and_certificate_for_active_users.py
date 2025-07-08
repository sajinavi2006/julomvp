import logging
import sys
import os
import time
import pdfkit
import tempfile
from django.db import transaction
from django.core.management.base import BaseCommand
from django.utils import timezone
from juloserver.customer_module.services.digital_signature import (
    DigitalSignature
)
from juloserver.customer_module.models import Key
from juloserver.julo.models import Loan
from juloserver.loan.services.agreement_related import get_julo_loan_agreement_template
from juloserver.followthemoney.services import get_signature_key_config


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


def update_key_for_user(loan_id, updated_key='1', old_key='1'):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return loan_id, "FAILED"
    now = timezone.localtime(timezone.now())
    application = loan.account.last_application
    filename = '{}_{}_{}_{}.pdf'.format(
        application.fullname,
        loan.loan_xid,
        now.strftime("%Y%m%d"),
        now.strftime("%H%M%S"),
    )
    file_path = os.path.join(tempfile.gettempdir(), filename)
    user = application.customer.user
    body, agreement_type, lender_signature, borrower_signature = \
        get_julo_loan_agreement_template(loan_id)
    if not body:
        return loan_id, "FAILED"
    try:
        now = time.time()
        pdfkit.from_string(body, file_path)
        time_limit = 2
        elapsed = time.time() - now
    except Exception as e:
        return loan_id, "FAILED: error {}".format(str(e))

    with transaction.atomic():
        # RENAME DEFAULT VALUE
        key_to_be_reset = Key.objects.filter(user_id=user.id, name='key-{}-{}'.format(user.id, old_key)).last()
        if not key_to_be_reset:
            raise Exception('INVALID OLD KEY NOT FOUND')
        name_to_be_reset = str(key_to_be_reset.name) + '-failure'
        public_key_path = key_to_be_reset.public_key_path
        private_key_path = key_to_be_reset.private_key_path
        pub_key_updated_link = str(key_to_be_reset.public_key_path).split('.pub')[0] + '-failure' + '.pub'
        pvt_key_updated_link = str(key_to_be_reset.private_key_path).split('.pem')[0] + '-failure' + '.pem'
        borrower_sign_old = DigitalSignature.Signer(
            user,
            signature=borrower_signature,
            key_name="key-{}-{}".format(
                user.id, old_key,
            ),
            full_name=application.fullname,
            province=application.address_provinsi or '',
            city=application.address_kabupaten or '',
            address=application.address_street_num or '',
            postal_code=application.address_kodepos or '',
            location='',
        )
        storage = borrower_sign_old.signer.storage
        certificate_path = borrower_sign_old.signer.certificate_path
        csr_path = borrower_sign_old.signer.csr_path
        renamed_certificate_path = certificate_path.split('.crt')[0] + '-failure' + '.crt'
        renamed_csr_path = certificate_path.split('.csr')[0] + '-failure' + '.csr'
        result = storage.signature_bucket.copy_object(storage.signature_bucket.bucket_name, certificate_path,
                                                      renamed_certificate_path)
        if result.status == 200:
            result_del = storage.signature_bucket.delete_object(certificate_path)
            if storage.signature_bucket.object_exists(certificate_path):
                return loan_id, "FAILED OSS DELETION CRT"
        else:
            return loan_id, "FAILED OSS COPY CRT"

        result = storage.signature_bucket.copy_object(storage.signature_bucket.bucket_name, public_key_path,
                                                      pub_key_updated_link)
        if result.status == 200:
            result_del = storage.signature_bucket.delete_object(public_key_path)
            if storage.signature_bucket.object_exists(public_key_path):
                return loan_id, "FAILED OSS DELETION PUB"
        else:
            return loan_id, "FAILED OSS COPY PUB"

        result = storage.signature_bucket.copy_object(storage.signature_bucket.bucket_name, private_key_path,
                                                      pvt_key_updated_link)
        if result.status == 200:
            result_del = storage.signature_bucket.delete_object(private_key_path)
            if storage.signature_bucket.object_exists(private_key_path):
                return loan_id, "FAILED OSS DELETION PUB"
        else:
            return loan_id, "FAILED OSS COPY PUB"

        result = storage.signature_bucket.copy_object(storage.signature_bucket.bucket_name, csr_path,
                                                      renamed_csr_path)
        if result.status == 200:
            result_del = storage.signature_bucket.delete_object(csr_path)
            if storage.signature_bucket.object_exists(csr_path):
                return loan_id, "FAILED OSS DELETION PUB"
        else:
            return loan_id, "FAILED OSS COPY PUB"

        key_to_be_reset.private_key_path = pvt_key_updated_link
        key_to_be_reset.public_key_path = pub_key_updated_link
        key_to_be_reset.name = key_to_be_reset.name + '-failure'
        key_to_be_reset.save()

    # create new key
    borrower_sign = DigitalSignature.Signer(
        user,
        signature=borrower_signature,
        key_name="key-{}-{}".format(
            user.id, updated_key,
        ),
        full_name=application.fullname,
        province=application.address_provinsi or '',
        city=application.address_kabupaten or '',
        address=application.address_street_num or '',
        postal_code=application.address_kodepos or '',
        location='',
    )
    user_keys, default_key = get_signature_key_config()
    lender = loan.lender
    user_lender = lender.user
    lender_sign = DigitalSignature.Signer(
        user_lender,
        signature=lender_signature,
        key_name="key-{}-{}".format(
            lender.user_id,
            user_keys[str(lender.user_id)] if str(lender.user_id) in user_keys else default_key,
        ),
        for_organization=True,
    )
    tempfile_path = file_path
    file_path = DigitalSignature.Document(file_path) \
        .add_signer(borrower_sign) \
        .add_signer(lender_sign) \
        .sign()

    if os.path.isfile(tempfile_path):
        os.remove(tempfile_path)

    if os.path.isfile(file_path):
        os.remove(file_path)

    return loan_id, "SUCCESS"


class Command(BaseCommand):
    help = \
        """
            Update Key for issue related to card 
            link: https://juloprojects.atlassian.net/browse/GRABSUB-40
            Usage instruction:
                1. Will work for only one Loan at a time.
                2. Sample usage:             
        """

    def add_arguments(self, parser):
        parser.add_argument('--loan_id', nargs=1, type=int, help='LoanID which failed '
                                                           'SPHP creation due to key issue')
        parser.add_argument('--new-key-identifier', nargs='?', type=str,
                            help='Identifier for new key(the one to be created). eg. --new-key-identifier \'1\'')
        parser.add_argument('--old-key-identifier', nargs='?', type=str,
                            help='Identifier for existing key(Existing in db). eg. --old-key-identifier \'1\'')

    def handle(self, *args, **options):
        for key, value in options.items():
            if key == 'new_key_identifier':
                new_key_identifier = str(value) if value else '1'
            if key == 'old_key_identifier':
                old_key_identifier = str(value) if value else '1'
            if key == 'loan_id':
                loan_id = value[0]
        if not new_key_identifier or not old_key_identifier or not loan_id:
            self.stdout.write("INVALID INPUT. SOmething went wrong: {}".format(loan_id))
            return
        self.stdout.write("STARTING COMMAND FOR LOAN_ID: {}".format(loan_id))
        loan_id, status = update_key_for_user(
            loan_id, updated_key=new_key_identifier, old_key=old_key_identifier)
        self.stdout.write(status)
