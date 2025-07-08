import os.path
import secrets
import tempfile
from abc import ABC, abstractmethod
from base64 import b64decode, b64encode
from typing import Union

import oss2
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Hash import SHA512
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from django.conf import settings

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from django.utils import timezone
from pyhanko import stamp
from pyhanko.pdf_utils import text
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields, signers, timestamps
from pyhanko.sign.timestamps import TimestampRequestError
from pyhanko_certvalidator.registry import SimpleCertificateStore

from juloserver.customer_module.models import DocumentSignatureHistory, Key
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Document as DocumentModel
from juloserver.julo.utils import StorageType, oss_bucket
from juloserver.julolog.julolog import JuloLog

logger = JuloLog()
sentry = get_julo_sentry_client()

SIGNATURE_BUCKET = settings.DIGITAL_SIGNATURE["BUCKET"]
MEDIA_BUCKET = settings.OSS_MEDIA_BUCKET


class DigitalSignatureOSSBucket:
    def __init__(self, bucket):
        endpoint = settings.OSS_ENDPOINT
        auth = oss2.Auth(
            settings.DIGITAL_SIGNATURE["OSS_ACCESS_KEY_ID"],
            settings.DIGITAL_SIGNATURE["OSS_ACCESS_KEY_SECRET"],
        )
        self.bucket = oss2.Bucket(auth, endpoint, bucket)

    def __call__(self, *args, **kwargs):
        return self.bucket


def digital_signature_oss_bucket(bucket):
    return DigitalSignatureOSSBucket(bucket)()


class DigitalSignatureException(Exception):
    pass


class Storage:
    def __init__(self, storage: StorageType):
        if settings.ENVIRONMENT == "dev":
            # Override the unit test default storage
            self.storage = StorageType.LOCAL
        else:
            self.storage = storage

        self.media_bucket = oss_bucket(MEDIA_BUCKET) if self.is_oss else None
        self.signature_bucket = (
            digital_signature_oss_bucket(SIGNATURE_BUCKET) if self.is_oss else None
        )

    def set_storage(self, kind: StorageType):
        self.storage = kind
        return self

    @property
    def is_oss(self) -> bool:
        """Check if the storage is OSS"""
        return self.storage == StorageType.OSS

    @property
    def is_s3(self) -> bool:
        """Check if the storage is S3"""
        return self.storage == StorageType.S3

    @property
    def is_local(self) -> bool:
        """Check if the storage is local"""
        return self.storage == StorageType.LOCAL

    def file_exists(self, path: str, media: bool = False) -> bool:
        """Check existence of file

        :param path: string
        :param media: bool
        :return: boolean
        """

        if self.is_oss:
            _bucket = self.media_bucket if media else self.signature_bucket
            return _bucket.object_exists(path)

        return os.path.isfile(path)

    def file_not_exists(self, path: str, media: bool = False) -> bool:
        """Check not existence of file

        :param path: path
        :param media: bool
        :return: boolean
        """
        return not self.file_exists(path, media)

    def write(self, path, content):
        """Write content to the file.

        :param path: string
        :param content: bytes
        :return:
        """
        if self.is_oss:
            return self.write_to_oss(path, content)

        return self.write_to_local(path, content)

    def write_to_oss(self, path, content):
        """Write file to OSS

        :param path: string
        :param content: bytes
        """
        self.signature_bucket.put_object(path, content)

    def write_to_local(self, path, content):
        """Write file to local

        :param path: string
        :param content: bytes
        """
        if isinstance(content, str):
            content = bytes(content, 'utf-8')

        os.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
        if not os.path.isfile(path):
            with open(path, "xb") as file:
                file.write(content)

    def read(self, path, media: bool = False):
        """Read the file

        :param path: string
        :param media: bool
        :return: bytes
        """
        if self.is_oss:
            return self.read_from_oss(path, media)

        return self.read_from_local(path)

    @sentry.capture_exceptions
    def read_from_oss(self, path, media=False):
        """Read the file from OSS

        :param path: string
        :param media: bool
        :return: bytes
        """
        bucket = self.media_bucket if media else self.signature_bucket
        if not bucket.object_exists(path):
            raise DigitalSignatureException("File not exists.")

        return bucket.get_object(path).read()

    @staticmethod
    @sentry.capture_exceptions
    def read_from_local(path):
        """Read the file from local

        :param path: string
        :return: bytes
        """

        if not os.path.isfile(path):
            raise DigitalSignatureException("File not exists.")

        with open(path, "rb") as file:
            content = file.read()

        return content

    def remove(self, path):
        """Remove file

        :param path: string
        """
        if self.is_oss:
            return self.remove_in_oss(path)

        return self.remove_in_local(path)

    def remove_in_oss(self, path):
        """Remove file in OSS"""
        self.signature_bucket.delete_object(path)

    @staticmethod
    def remove_in_local(path):
        """Remove file in local"""
        os.remove(path)

    def temporary_path(self, path_or_content, media=False):
        """Temporary downloaded file in the server to read directly."""

        if isinstance(path_or_content, str):
            if "-----BEGIN" in path_or_content and "-----END" in path_or_content:
                # Meaning this is PEM content
                content = path_or_content
                path = tempfile.gettempdir() + "/" + secrets.token_hex(16)
            elif "/" in path_or_content:
                # Meaning this is path in cloud storage
                content = (
                    self.read_from_local(path_or_content)
                    if self.is_local
                    else self.read(path_or_content, media)
                )
                path = tempfile.gettempdir() + "/" + path_or_content
            else:
                raise DigitalSignatureException("Unknown condition")
        else:
            # Meaning this binary content
            content = path_or_content
            path = tempfile.gettempdir() + "/" + secrets.token_hex(16)

        if not os.path.isfile(path):
            self.write_to_local(path, content)

        return path


class Signer:
    KEY_LOCATION = "keys"

    def __init__(
        self, user, signature, key_name: str = None, storage=StorageType.OSS, for_organization=False
    ):
        logger.info({"msg": "Initialize digital signature instance", "user_or_customer": user.id})

        self.should_encrypt_private_key = False

        self.storage = Storage(storage)

        # Mark that this signer intended for organization
        self._organization = for_organization

        self.user = user
        self.key_name = key_name
        self.full_name = None
        self.email = None
        self.country_code = 'ID'

        # Set the organization name
        self.organization = None

        self.province = None
        self.city = None
        self.address = None
        self.postal_code = None
        self.location = ""

        if signature is not None:
            self.signature = signature(self)

    @property
    def id(self):
        return self.user.id

    def _global_path(self, extension):
        name = (
            "user.{}".format(extension)
            if self.key_name is None
            else "{}.{}".format(self.key_name, extension)
        )

        path = "{}/{}/{}".format(self.KEY_LOCATION, self.id, name)
        if self.storage.is_local:
            return "{}/{}".format(SIGNATURE_BUCKET, path)

        return path

    @property
    def private_key_path(self) -> str:
        """The private key path for the user"""
        return self._global_path('pem')

    @property
    def public_key_path(self) -> str:
        """The public key path for the user"""
        return self._global_path('pub')

    @property
    def csr_path(self) -> str:
        return self._global_path('csr')

    @property
    def certificate_path(self) -> str:
        return self._global_path('crt')

    def has_certificate(self):
        return self.storage.file_exists(self.certificate_path)

    def has_private_key(self):
        return self.storage.file_exists(self.private_key_path)

    def has_public_key(self):
        return self.storage.file_exists(self.public_key_path)

    def has_key_pairs(self):
        return self.has_private_key() and self.has_public_key()

    def has_csr(self):
        return self.storage.file_exists(self.csr_path)

    @staticmethod
    def _decrypt_private_key(enc_private_key, password):
        return RSA.importKey(enc_private_key, passphrase=password)

    def private_key(self, password=None):
        """Read the real private key with the password

        :param password: string
        :return: bytes
        """
        if self.should_encrypt_private_key is False:
            return self.storage.read(self.private_key_path)

        enc_private_key = self.storage.read(self.private_key_path)
        return self._decrypt_private_key(enc_private_key, password)

    def public_key(self):
        return self.storage.read(self.public_key_path)

    def set_key_name(self, name: str):
        """Set the key pairs name to override the existing name.

        :param name: string
            The new name that will be used.
        :return: DigitalSignature
        """

        self.key_name = name
        return self

    @sentry.capture_exceptions
    def generate_key_pairs(self, password: str = None, raise_exception: bool = False):
        """Generate key pairs using default name or based on name provided. This function only
        store the result in the storage, to interact with database you must do it yourself.

        :param password: string
            Password that used to encrypt the private key.
        :param raise_exception: boolean
            Choose to raise exception or not when key exists.
        :return: dict
            We are not return the private key data to the response because of the private key
            is encrypted in binary format, hard to digest.
            :return private_key_encrypted_path: string
                Path of the private key
            :return public_key: string
                The string representation of public key
            :return public_key_path: string
                Path of the public key
        """
        logger.info({"msg": "generating key pairs", "user": self.user.id})

        if self.storage.file_exists(self.private_key_path) and self.storage.file_exists(
            self.public_key_path
        ):
            if raise_exception:
                raise DigitalSignatureException("Key pair exists.")

            logger.info({"msg": "Key pair exists, using existing one.", "user": self.user.id})

            return {
                "public_key": self.storage.read(self.public_key_path),
                "private_key_path": self.private_key_path,
                "public_key_path": self.public_key_path,
            }

        if (
            self.storage.file_exists(self.private_key_path)
            and self.storage.file_not_exists(self.public_key_path)
        ) or (
            self.storage.file_not_exists(self.private_key_path)
            and self.storage.file_exists(self.public_key_path)
        ):
            logger.info({"msg": "Found invalid key pairs.", "user": self.user.id})
            raise DigitalSignatureException("Found invalid invalid key pairs.")

        if self.should_encrypt_private_key and password is None:
            raise DigitalSignatureException("Password is required to encrypt private key.")
        if self.should_encrypt_private_key is False:
            password = None

        # Generate the keys
        rsa = RSA.generate(2048)
        private_key = rsa.export_key(passphrase=password)
        public_key = rsa.public_key().export_key()

        # Store the keys
        self.storage.write(self.private_key_path, private_key)
        self.storage.write(self.public_key_path, public_key)

        logger.info({"msg": "Key pairs generated and encrypted.", "user": self.user.id})
        return {
            "public_key": self.storage.read(self.public_key_path),
            "private_key_path": self.private_key_path,
            "public_key_path": self.public_key_path,
        }

    def generate_csr(self, password: str = None, overwrite=False):
        from juloserver.julo.services2.encryption import AESCipher

        if self.storage.file_exists(self.csr_path) and not overwrite:
            return self

        private_key = load_pem_private_key(self.private_key(), password=password)
        builder = x509.CertificateSigningRequestBuilder()
        email = ''
        if self.user.email is None or self.user.email == "":
            if self.email is not None and self.email != "":
                email = self.email
        else:
            email = self.user.email

        cipher = AESCipher(settings.CRYPTOGRAPHY_KEY)

        certificate_attributes = [
            x509.NameAttribute(x509.NameOID.COMMON_NAME, self.full_name),
            x509.NameAttribute(
                x509.NameOID.ORGANIZATION_NAME,
                self.organization if self._organization else "Individual",
            ),
            x509.NameAttribute(x509.NameOID.COUNTRY_NAME, self.country_code),
            x509.NameAttribute(x509.NameOID.EMAIL_ADDRESS, email),
            x509.NameAttribute(x509.NameOID.USER_ID, cipher.encrypt(str(self.user.id))),
        ]

        if self.province is not None:
            certificate_attributes.append(
                x509.NameAttribute(x509.NameOID.STATE_OR_PROVINCE_NAME, self.province)
            )

        if self.city is not None:
            certificate_attributes.append(x509.NameAttribute(x509.NameOID.LOCALITY_NAME, self.city))

        if self.address is not None:
            certificate_attributes.append(
                x509.NameAttribute(x509.NameOID.STREET_ADDRESS, self.address)
            )

        if self.postal_code is not None:
            certificate_attributes.append(
                x509.NameAttribute(x509.NameOID.POSTAL_CODE, self.postal_code)
            )

        builder = builder.subject_name(x509.Name(certificate_attributes))

        csr = builder.sign(private_key, algorithm=hashes.SHA512(), backend=default_backend())
        self.storage.write(self.csr_path, csr.public_bytes(serialization.Encoding.PEM))
        return self

    def csr(self):
        return self.storage.read(self.csr_path)

    def certificate(self):
        return self.storage.read(self.certificate_path)


class Signature(ABC):

    height = 130
    width = 170

    def __init__(self, signer: Signer):
        self.signer = signer

    @property
    def field_name(self):
        return "Signer{}Signature".format(self.signer.id)

    @property
    def style(self):
        return stamp.TextStampStyle(
            stamp_text="",
            border_width=0,
            text_box_style=text.TextBoxStyle(
                border_width=0,
            ),
        )

    @property
    @abstractmethod
    def reason(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def box(self) -> tuple:
        raise NotImplementedError

    @property
    @abstractmethod
    def page(self) -> int:
        raise NotImplementedError


class CertificateAuthority:

    LOCAL_CERTIFICATE_PATH = '.crt/julo-ca.crt'

    def __init__(self, private_key, passphrase, certificate, storage=StorageType.OSS):
        self.storage = Storage(storage)

        self.private_key = private_key
        if isinstance(self.private_key, str):
            self.private_key = bytes(self.private_key, 'utf-8')

        self.passphrase = passphrase
        if isinstance(self.passphrase, str):
            self.passphrase = bytes(self.passphrase, 'utf-8')

        self.certificate = certificate
        if isinstance(self.certificate, str):
            self.certificate = bytes(self.certificate, 'utf-8')

    @classmethod
    def guarantee_local_certificate(cls):
        if not os.path.isfile(cls.LOCAL_CERTIFICATE_PATH):
            storage = Storage(StorageType.LOCAL)
            storage.write_to_local(
                cls.LOCAL_CERTIFICATE_PATH, settings.JULO_CERTIFICATE_AUTHORITY['CERTIFICATE']
            )

    def make_certificate(self, signer: Signer, chain: bool = False):

        serial_number = x509.random_serial_number()
        csr = x509.load_pem_x509_csr(signer.csr())
        ca_cert = x509.load_pem_x509_certificate(self.certificate)
        ca_key = load_pem_private_key(self.private_key, password=self.passphrase)

        cert_builder = (
            x509.CertificateBuilder()
            .issuer_name(ca_cert.subject)
            .subject_name(csr.subject)
            .public_key(csr.public_key())
            .serial_number(serial_number)
            .not_valid_before(ca_cert.not_valid_before)
            .not_valid_after(ca_cert.not_valid_after)
        )

        for extension in csr.extensions:
            cert_builder.add_extension(extension.value, extension.critical)

        cert_builder = (
            cert_builder.add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(csr.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
        )

        cert = cert_builder.sign(ca_key, hashes.SHA512())
        if chain:
            user_cert = cert.public_bytes(encoding=serialization.Encoding.PEM).decode('utf-8')
            parent_cert = self.certificate.decode('utf-8')
            cert = bytes("{}{}".format(user_cert, parent_cert), 'utf-8')
        else:
            cert = cert.public_bytes(encoding=serialization.Encoding.PEM)

        self.storage.write(signer.certificate_path, cert)
        return cert


class Document:
    def __init__(self, document, storage=StorageType.OSS):
        self.document = document
        self.storage = Storage(storage)
        self.signers = []

    def add_signer(self, signer: Signer):
        self.signers.append(signer)
        return self

    def sign_with_hash(self, password=None, hash_function="sha-512", cipher="pkcs1-v15"):
        """Sign the document with the private key.

        :param password: string
            Password that used to read the private key to sign the document.
        :param hash_function: string
        :param cipher: string
        :return: dict
            :return hexdigest: string
            :return signature: string
            :return signature_path: string
            :return is_exists: boolean
        """

        if isinstance(self.document, str):
            doc = self.storage.read_from_local(self.document)
        else:
            document_path = self.document.path
            doc = self.storage.read(document_path, media=True)

        # Match the hash function
        if hash_function == "sha-512":
            hash_sha_512 = SHA512.new(doc)
            hashed = hash_sha_512
        else:
            raise DigitalSignatureException("Unknown hash function.")

        result = {"hash": {"sha512": hash_sha_512.hexdigest()}, "signatures": []}

        for signer in self.signers:

            logger.info({"msg": "Signing the document.", "user": signer.id})

            if (
                self.storage.file_exists(signer.private_key_path)
                and self.storage.file_not_exists(signer.public_key_path)
            ) or (
                self.storage.file_not_exists(signer.private_key_path)
                and self.storage.file_exists(signer.public_key_path)
            ):
                logger.info({"msg": "Invalid key pairs.", "user": signer.id})
                raise DigitalSignatureException("Invalid key pairs.")

            if signer.should_encrypt_private_key is False:
                password = None
            private_key = signer.private_key(password)

            #  Match the cipher
            if cipher == "pkcs1-oaep":
                cipher = PKCS1_OAEP.new(RSA.importKey(private_key))
                signature = b64encode(cipher.encrypt(hashed.digest()))
            elif cipher == "pkcs1-v15":
                cipher = PKCS1_v1_5.new(RSA.importKey(private_key, passphrase=password))
                signature = b64encode(cipher.sign(hashed))
            else:
                raise DigitalSignatureException("Unknown cipher.")

            logger.info({"msg": "Document signature created.", "user": signer.id})
            result["signatures"].append(
                {
                    "user": signer.id,
                    "signature": signature,
                    "created_at": timezone.localtime(timezone.now()),
                }
            )

        return result

    def _get_signing_cert_content(self, path):
        from pyhanko.sign.general import load_certs_from_pemder_data

        content = self.storage.read(path)
        result = list(load_certs_from_pemder_data(content))
        return result[0]

    def _get_signing_key_content(self, path, passphrase):
        from pyhanko.sign.general import load_private_key_from_pemder_data

        content = self.storage.read(path)
        return load_private_key_from_pemder_data(content, passphrase=passphrase)

    def _load_ca_chain(self, ca_chain_files):
        from pyhanko.sign import load_certs_from_pemder

        try:
            return set(load_certs_from_pemder(ca_chain_files))
        except (IOError, ValueError) as e:  # pragma: nocover
            logger.error('Could not load CA chain', exc_info=e)
            return None

    def _get_cert_registry_content(self):
        ca_chain_files = (CertificateAuthority.LOCAL_CERTIFICATE_PATH,)
        ca_chain = self._load_ca_chain(ca_chain_files) if ca_chain_files else []
        if ca_chain is None:  # pragma: nocover
            return None

        cert_reg = SimpleCertificateStore()
        cert_reg.register_multiple(ca_chain)
        return cert_reg

    def _signer_being_signing(
        self,
        signer: Signer,
        path: str,
        timestamper,
        file_token: str,
        increment: int,
        password: str = None,
    ):
        cms_signer = signers.SimpleSigner(
            signing_cert=self._get_signing_cert_content(signer.certificate_path),
            signing_key=self._get_signing_key_content(signer.private_key_path, passphrase=password),
            cert_registry=self._get_cert_registry_content(),
        )

        with open(path, "rb") as doc:
            logger.info({"action": "_signer_being_signing_open_file", "path": path})
            w = IncrementalPdfFileWriter(doc)
            fields.append_signature_field(
                w,
                sig_field_spec=fields.SigFieldSpec(
                    signer.signature.field_name,
                    box=signer.signature.box,
                    on_page=signer.signature.page,
                ),
            )

            pdf_signer = signers.PdfSigner(
                signers.PdfSignatureMetadata(
                    field_name=signer.signature.field_name,
                    location=signer.location,
                    reason=signer.signature.reason,
                ),
                signer=cms_signer,
                timestamper=timestamper,
                stamp_style=signer.signature.style,
            )
            new_path = tempfile.gettempdir() + "/pdf/{}-{}.pdf".format(file_token, increment)
            os.makedirs("/".join(new_path.split("/")[:-1]), exist_ok=True)

            with open(new_path, 'wb') as f:
                pdf_signer.sign_pdf(w, output=f)

        if os.path.isfile(path) and increment > 1:
            os.remove(path)
            logger.info({"action": "_signer_being_signing", "path": path})

        return new_path

    def _get_timestamp_server(self):
        # timestamper=timestamps.HTTPTimeStamper("https://freetsa.org/tsr"),
        return timestamps.HTTPTimeStamper("https://tsa.swisssign.net")

    def sign_with_certificate(self, password: str = None, with_tsa=True):

        logger.info(
            {
                "msg": "Sign document with certificate",
                "document": self.document.id if hasattr(self.document, 'id') else self.document,
                "tsa": with_tsa,
            }
        )

        if isinstance(self.document, str):
            doc_path = self.document
        else:
            doc = self.storage.read(self.document.path, media=True)
            doc_path = self.storage.temporary_path(doc)

        if with_tsa:
            timestamper = self._get_timestamp_server()
        else:
            timestamper = None

        try:
            CertificateAuthority.guarantee_local_certificate()

            file_token = secrets.token_hex(16)
            path = doc_path
            i = 1
            for signer in self.signers:
                path = self._signer_being_signing(
                    signer=signer,
                    timestamper=timestamper,
                    path=path,
                    increment=i,
                    file_token=file_token,
                    password=password,
                )
                i += 1

        except TimestampRequestError as e:
            logger.info(
                {
                    "action": "sign_with_certificate_error",
                    "msg": str(e),
                    "document": self.document.id if hasattr(self.document, 'id') else self.document,
                }
            )
            return self.sign_with_certificate(password=password, with_tsa=False)

        if os.path.isfile(doc_path):
            os.remove(doc_path)
            logger.info({"action": "sign_with_certificate_delete_file", "path": doc_path})

        return path

    def sign(self, password=None, with_certificate=False, with_tsa=True):
        if with_certificate:
            return self.sign_with_certificate(password, with_tsa=with_tsa)

        return self.sign_with_hash(password)

    def verify_with_certificate(self):
        pass

    def verify_with_hash(self, signature, *, hash_function="sha-512", cipher="pkcs1-v15"):
        """Verify the document with given signature

        :param document: DocumentModel|string
        :param signature: string
        :param hash_function: string
        :param cipher: string
        :return: boolean
        """

        if len(self.signers) == 0:
            raise DigitalSignatureException("Please provide one signer to verify.")

        if len(self.signers) > 1:
            raise DigitalSignatureException("Currently, only accepting one signer to verify.")

        signer = self.signers[0]
        logger.info({"msg": "Verifying document signature.", "user": signer.id})
        if not isinstance(signature, str):
            raise DigitalSignatureException('Signature must be a string or path')

        if isinstance(self.document, str):
            doc = self.storage.read_from_local(self.document)
        else:
            doc = self.storage.read(self.document.path, media=True)

        if "/" in signature and ".sig" in signature:
            sig = self.storage.read(signature)
        else:
            sig = signature

        public_key = self.storage.read(signer.public_key_path)

        if hash_function == "sha-512":
            hashed = SHA512.new(doc)
        else:
            raise DigitalSignatureException("Unknown hash function.")

        try:

            if cipher == "pkcs1-v15":
                cipher = PKCS1_v1_5.new(RSA.importKey(public_key))
                # The problem here we cannot get the signature hash!
                is_verified = cipher.verify(hashed, b64decode(sig))
            elif cipher == "pkcs1-oeap":
                cipher = PKCS1_OAEP.new(RSA.importKey(public_key))
                decrypted_hash = cipher.decrypt(b64decode(sig))
                is_verified = decrypted_hash == hashed
            else:
                raise DigitalSignatureException("Unknown cipher.")

        except (ValueError, TypeError, DigitalSignatureException) as e:
            logger.info(
                {
                    "msg": "Document is not verified with exception.",
                    "exception": str(e),
                    "user": signer.id,
                }
            )
            is_verified = False

        return is_verified

    def verify(self, signature: str = None, with_certificate=False):
        if with_certificate:
            return self.verify_with_certificate()
        return self.verify_with_hash(signature)


class DigitalSignature:

    VERSION = "v2.1"

    def __init__(self, user, key_name):
        self.user = user
        self.key_name = key_name

    def sign(self, document):
        legacy_signer = self.Signer(user=self.user, key_name=self.key_name, signature=None)
        return legacy_signer.sign(document)

    class Signer:
        def __init__(
            self, user: User, signature=None, key_name: str = None, for_organization=False, **kwargs
        ):
            self.user = user
            self.signature = signature
            self.key_name = key_name
            self._key = None
            self.should_encrypt_private_key = False

            self.signer = Signer(user, signature, key_name, for_organization=for_organization)
            _available_signer_attributes = [
                'full_name',
                'organization',
                'email',
                'province',
                'city',
                'address',
                'postal_code',
                'location',
            ]
            for attr in _available_signer_attributes:
                if attr in kwargs:
                    setattr(self.signer, attr, kwargs[attr])

        @property
        def key(self) -> Key:
            if self._key is None:
                self._key = Key.objects.filter(name=self.key_name, user=self.user).last()
            return self._key

        def key_exists(self) -> bool:
            return Key.objects.filter(user=self.user, name=self.key_name).exists()

        @sentry.capture_exceptions
        def generate_key_pairs(self, password=None):
            if self.should_encrypt_private_key and not self.user.check_password(password):
                msg = "User password is wrong!"
                logger.warning(
                    {
                        "msg": msg,
                        "user_id": self.user.id,
                    }
                )
                raise DigitalSignatureException(msg)

            if self.signer.has_key_pairs():

                msg = "Key name with this user already exists."
                logger.warning(
                    {
                        "msg": msg,
                        "user_id": self.user.id,
                    }
                )

                # Here we can check that key is exists in database or not, sometimes is not
                # synchronized.
                if not self.key_exists():
                    Key.objects.create(
                        user=self.user,
                        name=self.key_name,
                        public_key_path=self.signer.public_key_path,
                        private_key_path=self.signer.private_key_path,
                    )
                    return self

                raise DigitalSignatureException(msg)

            keys = self.signer.generate_key_pairs(password, raise_exception=True)
            data = {
                "user": self.user,
                "name": self.key_name,
                "public_key_path": keys['public_key_path'],
            }

            if self.should_encrypt_private_key:
                data['encrypted_private_key_path'] = keys['private_key_path']
            else:
                data['private_key_path'] = keys['private_key_path']

            key = Key.objects.create(**data)
            logger.info(
                {
                    "msg": "Successfully create new key with id {}".format(key.id),
                    "user_id": self.user.id,
                }
            )
            return self

        @sentry.capture_exceptions
        def sign(self, path: str, password=None):
            """Sign the file to create digital signature based on encrypted hash."""
            if self.should_encrypt_private_key and password is None:
                raise DigitalSignatureException("Password must be provided!")

            if self.should_encrypt_private_key and not self.user.check_password(password):
                msg = "User password is wrong!"
                logger.warning(
                    {
                        "msg": msg,
                        "user_id": self.user.id,
                    }
                )
                raise DigitalSignatureException(msg)

            try:
                if not self.signer.has_key_pairs():
                    self.generate_key_pairs(password)

                doc = Document(path)
                doc.add_signer(self.signer)
                signature = doc.sign(password)['signatures'][0]

                note = "Successfully generate digital signature."

                logger.info(
                    {
                        "msg": note,
                        "user_id": self.user.id,
                    }
                )

                signature['key_id'] = self.key.id
                signature['version'] = DigitalSignature.VERSION

                return signature
            except DigitalSignatureException as e:
                note = e.message if hasattr(e, 'message') else e
                logger.warning(
                    {
                        "msg": "Failed to create document signature",
                        "error": note,
                        "user_id": self.user.id,
                    }
                )
                raise DigitalSignatureException(note)

        @sentry.capture_exceptions
        def verify(self, document: Union[DocumentModel, str], signature):
            doc = Document(document)
            doc.add_signer(self.signer)
            is_verified = doc.verify(signature)
            status = 'VERIFIED' if is_verified else 'NOT VERIFIED'
            self.record_history(document, action="verify", note=status)
            return is_verified

        @sentry.capture_exceptions
        def record_history(self, document: DocumentModel, action: str, note: str):
            if not isinstance(document, DocumentModel):
                return

            DocumentSignatureHistory.objects.create(
                document=document, key=self.key, action=action, note=note
            )

    class Document:
        def __init__(self, path: str):
            self.doc = Document(path)
            self.signers = []

        @sentry.capture_exceptions
        def add_signer(self, signer):
            self.signers.append(signer)
            self.doc.add_signer(signer.signer)
            return self

        @sentry.capture_exceptions
        def sign(self):
            for signer in self.signers:
                self.guarantee_certificate(signer)

            return self.doc.sign(with_certificate=True)

        @sentry.capture_exceptions
        def record_history(self, document: DocumentModel, action: str, note: str):
            if not isinstance(document, DocumentModel):
                return

            for signer in self.signers:
                DocumentSignatureHistory.objects.create(
                    document=document, key=signer.key, action=action, note=note
                )

        @staticmethod
        @sentry.capture_exceptions
        def guarantee_certificate(signer):
            if not signer.key_exists():
                # DigitalSignature.Signer.generate_key_pairs() not Signer.generate_key_pairs()
                signer.generate_key_pairs()

            if signer.signer.has_certificate():
                return

            signer.signer.generate_csr()
            CertificateAuthority(
                private_key=settings.JULO_CERTIFICATE_AUTHORITY["PRIVATE_KEY"],
                passphrase=settings.JULO_CERTIFICATE_AUTHORITY["PASSPHRASE"],
                certificate=settings.JULO_CERTIFICATE_AUTHORITY["CERTIFICATE"],
            ).make_certificate(signer.signer)
