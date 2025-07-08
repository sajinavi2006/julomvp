import datetime
import os
import shutil
from mock import patch

import pytest
from django.conf import settings
from django.test import TestCase
from oss2 import Bucket

from juloserver.customer_module.models import DocumentSignatureHistory, Key
from juloserver.customer_module.services.digital_signature import (
    DigitalSignature,
    DigitalSignatureException,
    Signer,
    Document,
    Signature,
    CertificateAuthority,
    DigitalSignatureOSSBucket,
    digital_signature_oss_bucket,
    Storage,
)
from juloserver.julo.models import Document as DocumentModel
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    DocumentFactory,
)
from juloserver.julo.utils import StorageType

test_file = "static/pdf/sample_pdf.pdf"

ca_key = (
    "-----BEGIN ENCRYPTED PRIVATE KEY-----\n"
    "MIIFHDBOBgkqhkiG9w0BBQ0wQTApBgkqhkiG9w0BBQwwHAQIA1wbxFZZrGYCAggA\n"
    "MAwGCCqGSIb3DQIJBQAwFAYIKoZIhvcNAwcECF7T/P3MlJUNBIIEyFoJmvFrSp0N\n"
    "YPAnmV91HWIT0wYjYTp8L+lvo9LmXKbzdMDjzFtqX028oFzL8IAbrfyOy13qlzzu\n"
    "EQU+abGy3jjpuY6q3w3cr/xp0grU0ofiJEuS7TX9tDhXdJZX4Uqkt1rgABNFfWy+\n"
    "OOjIsPaj1VYlOuScgDvuHfZdOEBsslO9yWdslHV0DI8A2pfkvx96H6ELJrBIdMyt\n"
    "vyvgKwiSR1ipNy89YpBsJF3bAaUMyhXtqBKV16GlNu4FmSQDDnEFp5/nCTqVwbRm\n"
    "zB/OWF0IRDe1DdOXtdWy/wUrxDWujuU19SEqiyxae3F0ylsuI0Lk/7l/3okGAhA3\n"
    "QIL8SwwpRQ08yANYIl4kvPVyvZTs0J6fBzoiLacvn3Ze4yPfrnJgoKEl8oTyaEGX\n"
    "s/G4PG2ZBLalNdzey/ugHXIzFZkGzC/LP1rccx0VNulcKHhFVTbMFz5Pm1JhHFKz\n"
    "AqPxKz1WmyJw576AbmDyp2vrcPzICvebc1ZxRTzMFfjTUxmA/9bOdcSI+k0BPcIG\n"
    "fKbelzBfA103wE1mnLh257Lc82Jek1tZ949+5a5lAmpnUUIn57q4LKrLOb1cogkr\n"
    "gPO5WQkMhrcyaVIXal/1sHg4o05DVrgesvN9JcIKT5tF/G+is2S/bKZwY33xotaD\n"
    "HZh9gBQGc+xXS92BizrE/hafBTA6Zq9Q0Ppl6ewWJ75OHgjInmofk8Fx7okiKBS5\n"
    "AoQyDUmBgqKMj38DmdQlOdlXgK1AqfVp6tglkqQn0hyrEa0YPv5uUZxPZ2pmlRSL\n"
    "RVD73e06A4W4INNKv3Q2fU/Tr3O/tMu3ffLqVONOWbWJ5vOQ/F5y62uwmjJ9a9sw\n"
    "xy5pMc9vvTHhV+F0il/qjLSSJpkMKEtMWuU9V3O8r4yO4+1RBCE846kD2I8t1FvB\n"
    "iyxEb8ctNCEaoUOcvODxgE9Q2LYOxRkIgTyL3errNkUwc0uLxTYEn64SRtcodrJM\n"
    "WK5TrL7pxeZDXdSEyMGdgw4wkLGc91VOvFppxJAtd56UIjrt76imz3FBx0D2Uw6T\n"
    "sKE8hLf7KMNjDYp0Cu/uqK6YHpnqnNnICaZTLrTHAXorqPje0RPQaNZCss/RDQd3\n"
    "YYVVBC8YawEeMYJUC7vj8xQLDXcWoPO8amo94p9pcz9oshthip/UsWyBjOsZq67c\n"
    "Dlkv3MNoPdiOgAnYPckyxvQ0V/Kki9B0p95uvbi4IEDJJ6TrjPXp8KufN8cHf7C3\n"
    "H86CL8s3qVTwcdTQZgMU+T0SPvEVNY+qc0MTnRyTLz658WhHAgXURjCZBldZDn/B\n"
    "CtVl3OQG/MeMO0qNPZjgohNEdhx0B0thnw+/6tncxDJ0KZX8UYnzzhEce2qKc7Hp\n"
    "TtXSlMGf8jS1TeFUjA4rglMgmRpQPPoRS7kbB3jUqTQ8BGqIKXpG/LTvnIsmeIDK\n"
    "1UO76Bm31kPqlmNShek89/dUDhXm+zEjtOfnYMCu7YxAjfDUW62fkuU6kDf8iUk2\n"
    "la/KRPKtqa2MTWLjVQyPe7ZhmfW6mNQjpynw+1KlsijqTbTwVZ66dcquJopvPt48\n"
    "OjyxD1BwXYvfxww3njHFQZPI6kwPUzXx6USKY0cTp1TsNXhyaoNFiC8NCi1atl8l\n"
    "yASYE8LtQq+GDCjp1VA/uw==\n"
    "-----END ENCRYPTED PRIVATE KEY-----"
)
ca_passphrase = "FpPmLYBSklfEnioz50Ar"
ca_cert = (
    "-----BEGIN CERTIFICATE-----\n"
    "MIID+TCCAuGgAwIBAgIUTuwFxv0SVMlSmFqGm4rHsYnnEQwwDQYJKoZIhvcNAQEL\n"
    "BQAwgYsxCzAJBgNVBAYTAklEMRQwEgYDVQQIDAtES0kgSmFrYXJ0YTEWMBQGA1UE\n"
    "BwwNU291dGggSmFrYXJ0YTElMCMGA1UECgwcUFQuIEp1bG8gVGVrbm9sb2dpIEZp\n"
    "bmFuc2lhbDEQMA4GA1UECwwHRmluYW5jZTEVMBMGA1UEAwwMSnVsbyBSb290IENB\n"
    "MB4XDTIzMDMyMDA5MTA0OVoXDTI4MDMxODA5MTA0OVowgYsxCzAJBgNVBAYTAklE\n"
    "MRQwEgYDVQQIDAtES0kgSmFrYXJ0YTEWMBQGA1UEBwwNU291dGggSmFrYXJ0YTEl\n"
    "MCMGA1UECgwcUFQuIEp1bG8gVGVrbm9sb2dpIEZpbmFuc2lhbDEQMA4GA1UECwwH\n"
    "RmluYW5jZTEVMBMGA1UEAwwMSnVsbyBSb290IENBMIIBIjANBgkqhkiG9w0BAQEF\n"
    "AAOCAQ8AMIIBCgKCAQEAyLVgtdtGcg48S6PgqNJFRvfLkz/UmsGI1ZsOmBofgFPU\n"
    "8CznDQMm92AZYyt+3QVOt2uE9YUMEAyV3shJGQELtPRWh/eQV0LdSsdYMWjRNZfj\n"
    "q4ay7BttGm+hxciFS8PEbMNMJSnenwBoA7Ve5lX1QBtg3JttYA/ku9+pglF0z1DQ\n"
    "4ikVPY1NI3x8ET9jQ+WtqlUeAk6tW4FkCV5i/ZebxhiTU8dihzQBK4sVwuvSYIqe\n"
    "cao3KM0TE5+uFYd+WHX3SXG9qJ9IJ1TQOLHZcq8mo70lnyzireZKreEZXcYEeetp\n"
    "dV6cPxqquLqUptE6/MIhh8Tc9lbq0phNC7tnwr0b7QIDAQABo1MwUTAdBgNVHQ4E\n"
    "FgQUCeKyJAdMBzn3rMS8kTmpOIMivzIwHwYDVR0jBBgwFoAUCeKyJAdMBzn3rMS8\n"
    "kTmpOIMivzIwDwYDVR0TAQH/BAUwAwEB/zANBgkqhkiG9w0BAQsFAAOCAQEAbscO\n"
    "k+zp2K/uq1drGjinWH1hpQpBUYHYtLnvVvrYhje50Bxq1RordcP7UpgjJPce+uNS\n"
    "/LZVz8hTKm4TmUpEeQ4zMqfpRIZkJyVy4pHxApLjxyx+7icyVn5U0dcCqJiLOyDP\n"
    "BYjBeh/PnB9XudS74lqDp4EOT6ZyAR5mR1rdCprFCrN8qm8i/DDh8M+lF3kq3KMG\n"
    "a2mPwnGFhhvLUd2f3WcBZf4cSYh5aHtL9Eaju5MclPmPYYw8uq4i/3oEl+JCjSae\n"
    "QJz9MS0ZwrW8BuWQG1Veoa+ly6wTsUB/O1gSw1u0bVu44xS4QFC8NGTdlcMrbzrZ\n"
    "w0j/pAkglzS9RBd0yQ==\n"
    "-----END CERTIFICATE-----"
)


class DummySignature(Signature):
    role = "dummy_role"

    @property
    def reason(self) -> str:
        return "ada"

    @property
    def box(self) -> tuple:
        return 1, 2, 3, 4

    @property
    def page(self) -> int:
        return 0


class TestDigitalSignatureBucket(TestCase):
    def test_initialization(self):
        bucket = DigitalSignatureOSSBucket('ember')
        self.assertIsInstance(bucket.bucket, Bucket)

    def test_call(self):
        bucket = DigitalSignatureOSSBucket('ember')
        self.assertIsInstance(bucket(), Bucket)

    def test_function_helper(self):
        bucket = digital_signature_oss_bucket('ember')
        self.assertIsInstance(bucket, Bucket)


class TestDigitalSignature(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.user.set_password('123123')
        self.user.save()

        if os.path.exists(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/"):
            shutil.rmtree(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/")

        if os.path.exists(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/signatures/"):
            shutil.rmtree(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/signatures/")

    def test_generate_key_pairs_with_correct_password(self):
        signer = DigitalSignature.Signer(self.user, key_name='test_1', signature=DummySignature)
        signer.generate_key_pairs('123123')

        key = Key.objects.filter(user=self.user, name='test_1').last()
        self.assertIsNotNone(key)

    @pytest.mark.skip(reason="no need for encrypt")
    def test_digital_signature_with_wrong_password(self):
        signer = DigitalSignature.Signer(self.user, key_name='test_2', signature=DummySignature)
        with pytest.raises(DigitalSignatureException):
            signer.generate_key_pairs('874849')

        key = Key.objects.filter(user=self.user, name='test_2').last()
        self.assertIsNone(key)

    @pytest.mark.skip(reason="cannot update the document table")
    def test_success_signing_document(self):
        document = DocumentFactory(url=test_file, service='local')
        signer = DigitalSignature.Signer(self.user, key_name='test_3', signature=DummySignature)
        signer.should_encrypt_private_key = True

        signature = signer.generate_key_pairs('123123').sign(document, '123123')

        history = DocumentSignatureHistory.objects.filter(document=document).last()
        self.assertIsNotNone(history)
        self.assertTrue(history.note.startswith("Successfully generate"))

    def test_fail_signing_document(self):
        document = DocumentFactory(url=test_file, service='local')
        with pytest.raises(DigitalSignatureException) as e:
            signer = DigitalSignature.Signer(self.user, key_name='test_4', signature=DummySignature)
            signer.should_encrypt_private_key = True
            signer.generate_key_pairs('123123')
            signature = signer.sign(document, '987484')

        self.assertEqual(str(e.value), "User password is wrong!")
        # history = DocumentSignatureHistory.objects.filter(document=document).last()
        # self.assertIsNotNone(history)
        # self.assertEqual(history.note, "User password is wrong!")

    @pytest.mark.skip(reason='Skip verify for now')
    def test_success_verifying_document(self):
        document = DocumentFactory(url=test_file, service='local')

        signer = DigitalSignature.Signer(self.user, key_name='test_5', signature=DummySignature)
        signer.should_encrypt_private_key = True

        signature = signer.generate_key_pairs('123123').sign(document, '123123')

        updated_doc = DocumentModel.objects.get(pk=document.id)

        signer = DigitalSignature.Signer(self.user, key_name='test_5', signature=DummySignature)
        signer.should_encrypt_private_key = True
        result = signer.verify(test_file, signature['signature'])

        self.assertTrue(result)

        history = DocumentSignatureHistory.objects.filter(document=updated_doc).last()
        self.assertEqual(history.action, 'verify')
        self.assertEqual(history.note, 'VERIFIED')

    def test_fail_verifying_document(self):
        document = DocumentFactory(url=test_file, service='local')
        signer = DigitalSignature.Signer(
            self.user, key_name='test_6', signature=DummySignature
        ).generate_key_pairs('123123')

        signer.sign(document, '123123')

        updated_doc = DocumentModel.objects.get(pk=document.id)

        signer = DigitalSignature.Signer(self.user, key_name='test_6', signature=DummySignature)
        result = signer.verify(updated_doc, '8ufdghjcbvnartdyc3245678fghj')

        self.assertFalse(result)

        history = DocumentSignatureHistory.objects.filter(document=updated_doc).last()
        self.assertEqual(history.action, 'verify')
        self.assertEqual(history.note, 'NOT VERIFIED')


class TestStorage(TestCase):
    def test_set_storage(self):
        storage = Storage(StorageType.LOCAL)
        storage.set_storage(StorageType.S3)
        self.assertEqual(storage.storage, StorageType.S3)

    def test_is_local(self):
        storage = Storage(StorageType.LOCAL)
        self.assertFalse(storage.is_oss)
        self.assertTrue(storage.is_local)
        self.assertFalse(storage.is_s3)

    def test_file_exists_in_local(self):
        storage = Storage(StorageType.LOCAL)
        storage.write_to_local('/tmp/yuhuu.txt', 'yahii')
        self.assertTrue(storage.file_exists('/tmp/yuhuu.txt'))

    def test_file_not_exists_in_local(self):
        storage = Storage(StorageType.LOCAL)
        exists = storage.file_not_exists('/hallo/how/are/you.txt')
        self.assertTrue(exists)

    def test_read_from_local_if_file_not_exists(self):
        storage = Storage(StorageType.LOCAL)
        with pytest.raises(DigitalSignatureException) as e:
            storage.read_from_local('/tmp/sungai.txt')

    def test_remove_file_from_local(self):
        storage = Storage(StorageType.LOCAL)
        storage.write_to_local('/tmp/remove.txt', 'remove me')
        self.assertTrue(storage.file_exists('/tmp/remove.txt'))
        storage.remove('/tmp/remove.txt')
        self.assertTrue(storage.file_not_exists('/tmp/remove.txt'))

    def test_remove_file_from_local2(self):
        storage = Storage(StorageType.LOCAL)
        storage.write_to_local('/tmp/remove.txt', 'remove me')
        self.assertTrue(storage.file_exists('/tmp/remove.txt'))
        storage.remove_in_local('/tmp/remove.txt')
        self.assertTrue(storage.file_not_exists('/tmp/remove.txt'))

    def test_temporary_path_for_key_content(self):
        storage = Storage(StorageType.LOCAL)
        path = storage.temporary_path('-----BEGIN-----rwoiybuoif-----END-----')
        self.assertGreaterEqual(len(path), 2)
        self.assertTrue(storage.file_exists(path))

    def test_temporary_path_for_path_not_exists(self):

        storage = Storage(StorageType.LOCAL)
        with pytest.raises(DigitalSignatureException) as e:
            path = storage.temporary_path('/sebuah/file/adakah.txt')

        self.assertEqual(str(e.value), "File not exists.")

    def test_temporary_path_random_string(self):
        storage = Storage(StorageType.LOCAL)
        with pytest.raises(DigitalSignatureException) as e:
            storage.temporary_path('yuhuuuu')

        self.assertEqual(str(e.value), "Unknown condition")

    def test_temporary_path_binary_content(self):
        storage = Storage(StorageType.LOCAL)
        path = storage.temporary_path(b"some binary string")
        self.assertTrue(storage.file_exists(path))


class TestSigner(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()

        if os.path.exists(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/"):
            shutil.rmtree(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/")

    def test_signer_id_should_return_user_id(self):
        signer = Signer(user=self.user, signature=DummySignature)
        self.assertEqual(signer.id, self.user.id)

    def test_location_is_set(self):
        signer = Signer(self.user, signature=DummySignature)
        signer.location = "Jakarta, Indonesia"
        self.assertEqual(signer.location, "Jakarta, Indonesia")

    def test_location_not_set(self):
        pass

    def test_return_private_key_path(self):
        pass

    def test_return_public_key_path(self):
        pass

    def test_return_csr_path(self):
        pass

    def test_return_certificate_path(self):
        pass

    def test_plain_private_key_content(self):
        pass

    def test_encrypted_private_key_content(self):
        pass

    def test_public_key_content(self):
        pass

    def test_csr_content(self):
        pass

    def test_certificate_content(self):
        pass

    def test_generate_key_pairs(self):
        signer = Signer(self.user, signature=DummySignature)
        signer.country_code = 'ID'
        signer.full_name = "Adri"
        signer.province = "DKI Jakarta"
        signer.city = "Jakarta Selatan"
        signer.address = "Jl. Raya Indah, No. 13"
        signer.postal_code = "123456"
        signer.location = 'Jakarta, Indonesia'
        signer.email = 'adri@julo.co.id'

        keys = signer.generate_key_pairs()
        self.assertTrue(signer.storage.file_exists(keys['private_key_path']))
        self.assertTrue(signer.storage.file_exists(keys['public_key_path']))
        self.assertTrue(signer.has_public_key())
        self.assertTrue(signer.has_private_key())

    def test_generate_key_pairs_exist_no_exception(self):
        signer = Signer(self.user, signature=DummySignature)
        signer.country_code = 'ID'
        signer.full_name = "Adri"
        signer.province = "DKI Jakarta"
        signer.city = "Jakarta Selatan"
        signer.address = "Jl. Raya Indah, No. 13"
        signer.postal_code = "123456"
        signer.location = 'Jakarta, Indonesia'
        signer.email = 'adri@julo.co.id'
        signer.generate_key_pairs()

        signer2 = Signer(self.user, signature=DummySignature)
        signer2.country_code = 'ID'
        signer2.full_name = "Adri"
        signer2.province = "DKI Jakarta"
        signer2.city = "Jakarta Selatan"
        signer2.address = "Jl. Raya Indah, No. 13"
        signer2.postal_code = "123456"
        signer2.location = 'Jakarta, Indonesia'
        signer2.email = 'adri@julo.co.id'
        keys = signer2.generate_key_pairs()

        self.assertTrue(signer2.storage.file_exists(keys['private_key_path']))
        self.assertTrue(signer2.storage.file_exists(keys['public_key_path']))

    def test_generate_key_pairs_exist_with_exception(self):
        signer = Signer(self.user, signature=DummySignature)
        signer.country_code = 'ID'
        signer.full_name = "Adri"
        signer.province = "DKI Jakarta"
        signer.city = "Jakarta Selatan"
        signer.address = "Jl. Raya Indah, No. 13"
        signer.postal_code = "123456"
        signer.location = 'Jakarta, Indonesia'
        signer.email = 'adri@julo.co.id'
        signer.generate_key_pairs()

        signer2 = Signer(self.user, signature=DummySignature)
        signer2.country_code = 'ID'
        signer2.full_name = "Adri"
        signer2.province = "DKI Jakarta"
        signer2.city = "Jakarta Selatan"
        signer2.address = "Jl. Raya Indah, No. 13"
        signer2.postal_code = "123456"
        signer2.location = 'Jakarta, Indonesia'
        signer2.email = 'adri@julo.co.id'
        with pytest.raises(DigitalSignatureException) as e:
            keys = signer2.generate_key_pairs(raise_exception=True)

        self.assertEqual(str(e.value), "Key pair exists.")

    def test_generate_key_pairs_missing_one(self):
        signer = Signer(self.user, signature=DummySignature)
        signer.country_code = 'ID'
        signer.full_name = "Adri"
        signer.province = "DKI Jakarta"
        signer.city = "Jakarta Selatan"
        signer.address = "Jl. Raya Indah, No. 13"
        signer.postal_code = "123456"
        signer.location = 'Jakarta, Indonesia'
        signer.email = 'adri@julo.co.id'
        keys = signer.generate_key_pairs()

        signer.storage.remove(keys['private_key_path'])

        signer2 = Signer(self.user, signature=DummySignature)
        signer2.country_code = 'ID'
        signer2.full_name = "Adri"
        signer2.province = "DKI Jakarta"
        signer2.city = "Jakarta Selatan"
        signer2.address = "Jl. Raya Indah, No. 13"
        signer2.postal_code = "123456"
        signer2.location = 'Jakarta, Indonesia'
        signer2.email = 'adri@julo.co.id'
        with pytest.raises(DigitalSignatureException) as e:
            signer2.generate_key_pairs(raise_exception=True)

        self.assertEqual(str(e.value), "Found invalid invalid key pairs.")

    def test_generate_key_pairs_encrypted_without_password(self):
        signer = Signer(self.user, signature=DummySignature)
        signer.should_encrypt_private_key = True
        signer.country_code = 'ID'
        signer.full_name = "Adri"
        signer.province = "DKI Jakarta"
        signer.city = "Jakarta Selatan"
        signer.address = "Jl. Raya Indah, No. 13"
        signer.postal_code = "123456"
        signer.location = 'Jakarta, Indonesia'
        signer.email = 'adri@julo.co.id'

        with pytest.raises(DigitalSignatureException) as e:
            signer.generate_key_pairs()

        self.assertEqual(str(e.value), "Password is required to encrypt private key.")

    def test_generate_key_pairs_read_the_public_one(self):
        signer = Signer(self.user, signature=DummySignature)
        signer.country_code = 'ID'
        signer.full_name = "Adri"
        signer.province = "DKI Jakarta"
        signer.city = "Jakarta Selatan"
        signer.address = "Jl. Raya Indah, No. 13"
        signer.postal_code = "123456"
        signer.location = 'Jakarta, Indonesia'
        signer.email = 'adri@julo.co.id'
        signer.generate_key_pairs()

        public_key = signer.public_key()
        self.assertIsInstance(public_key, bytes)
        self.assertTrue("-----BEGIN PUBLIC KEY-----" in public_key.decode('utf-8'))

    def test_generate_key_pairs_read_the_private_one(self):
        signer = Signer(self.user, signature=DummySignature)
        signer.country_code = 'ID'
        signer.full_name = "Adri"
        signer.province = "DKI Jakarta"
        signer.city = "Jakarta Selatan"
        signer.address = "Jl. Raya Indah, No. 13"
        signer.postal_code = "123456"
        signer.location = 'Jakarta, Indonesia'
        signer.email = 'adri@julo.co.id'
        signer.generate_key_pairs()

        private_key = signer.private_key()
        self.assertIsInstance(private_key, bytes)
        self.assertTrue("-----BEGIN RSA PRIVATE KEY-----" in private_key.decode('utf-8'))

    def test_generate_csr(self):
        signer = Signer(self.user, signature=DummySignature)
        signer.country_code = 'ID'
        signer.full_name = "Adri"
        signer.province = "DKI Jakarta"
        signer.city = "Jakarta Selatan"
        signer.address = "Jl. Raya Indah, No. 13"
        signer.postal_code = "123456"
        signer.location = 'Jakarta, Indonesia'
        signer.email = 'adri@julo.co.id'

        signer.generate_key_pairs()
        signer.generate_csr()

        self.assertTrue(
            os.path.isfile(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/{self.user.id}/user.csr")
        )

        self.assertTrue(signer.has_csr())


class TestCertificateAuthority(TestCase):
    def setUp(self) -> None:
        if os.path.exists(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/"):
            shutil.rmtree(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/")

        self.user = AuthUserFactory()

        signer = Signer(
            user=self.user,
            signature=DummySignature,
            key_name="test_1",
        )
        signer.country_code = 'ID'
        signer.full_name = "Akung"
        signer.province = "DKI Jakarta"
        signer.city = "Jakarta Selatan"
        signer.address = "Jl. Raya Indah, No. 13"
        signer.postal_code = "123456"
        signer.location = 'Jakarta, Indonesia'
        signer.email = 'akung@julo.co.id'

        signer.generate_key_pairs()
        signer.generate_csr()

        self.signer = signer

    def test_success_make_certificate(self):
        CertificateAuthority(
            private_key=ca_key, passphrase=ca_passphrase, certificate=ca_cert
        ).make_certificate(signer=self.signer)

        self.assertTrue(
            os.path.isfile(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/{self.user.id}/test_1.crt")
        )

    def test_success_make_certificate_with_chain(self):
        CertificateAuthority(
            private_key=ca_key, passphrase=ca_passphrase, certificate=ca_cert
        ).make_certificate(signer=self.signer, chain=True)

        self.assertTrue(
            os.path.isfile(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/{self.user.id}/test_1.crt")
        )


class TestSignature(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()

        if os.path.exists(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/"):
            shutil.rmtree(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/")

    def test_signature(self):
        signer = Signer(self.user, signature=DummySignature)

        self.assertEqual(signer.signature.field_name, f"Signer{self.user.id}Signature")
        self.assertEqual(signer.signature.page, 0)
        self.assertEqual(signer.signature.reason, "ada")
        self.assertEqual(signer.signature.box, (1, 2, 3, 4))


class TestDocument(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.document_model = DocumentFactory()

        if os.path.exists(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/"):
            shutil.rmtree(f"{settings.DIGITAL_SIGNATURE['BUCKET']}/keys/")

        settings.JULO_CERTIFICATE_AUTHORITY['PRIVATE_KEY'] = ca_key
        settings.JULO_CERTIFICATE_AUTHORITY['PASSPHRASE'] = ca_passphrase
        settings.JULO_CERTIFICATE_AUTHORITY['CERTIFICATE'] = ca_cert

    def test_add_signers(self):
        user2 = AuthUserFactory()

        signer1 = Signer(user=self.user, signature=DummySignature, key_name="test_1")
        signer2 = Signer(user=user2, signature=DummySignature, key_name="test_2")
        doc = Document(document=test_file)
        doc.add_signer(signer1)
        doc.add_signer(signer2)

        self.assertEqual(2, len(doc.signers))

    @patch.object(Document, '_get_timestamp_server', return_value=None)
    def test_sign_with_certificate_without_tsa(self, mock_timestamp):

        import socket
        import _socket
        import shutil
        from conftest import BlockedSocket

        socket.socket = _socket.socket

        signer = Signer(user=self.user, signature=DummySignature, key_name="test_1")
        signer.generate_key_pairs()

        signer.country_code = 'ID'
        signer.full_name = "Akung"
        signer.province = "DKI Jakarta"
        signer.city = "Jakarta Selatan"
        signer.address = "Jl. Raya Indah, No. 13"
        signer.postal_code = "123456"
        signer.location = 'Jakarta, Indonesia'

        signer.generate_csr()

        CertificateAuthority(
            private_key=ca_key, passphrase=ca_passphrase, certificate=ca_cert
        ).make_certificate(signer)

        # copy the test file, because it will removed
        _this_test_file = "static/pdf/uifaa9is8.pdf"
        shutil.copyfile(test_file, _this_test_file)

        doc = Document(document=_this_test_file)
        doc.add_signer(signer)
        path = doc.sign(with_certificate=True, with_tsa=False)

        self.assertIsNotNone(path)
        self.assertTrue(path.startswith('/tmp/pdf/'))
        assert os.path.isfile(path) == True
        # todo: assert hash changes, not sure how to assert it

        socket.socket = BlockedSocket

    def test_sign_with_hash_sha512(self):
        doc = Document(document=test_file)
        result = doc.sign_with_hash(hash_function="sha-512")
        self.assertEqual(len(result['hash']['sha512']), 128)

    def test_sign_with_using_unknown_hash(self):
        doc = Document(document=test_file)
        with pytest.raises(DigitalSignatureException) as e:
            doc.sign_with_hash(hash_function="abc123")

        self.assertEqual(str(e.value), "Unknown hash function.")

    def test_sign_with_cipher_pkcs1oeap(self):
        signer = Signer(user=self.user, signature=DummySignature, key_name="test_2")
        signer.generate_key_pairs()

        doc = Document(document=test_file)
        doc.add_signer(signer)
        result = doc.sign_with_hash(cipher="pkcs1-oaep")
        self.assertEqual(len(result['hash']['sha512']), 128)
        self.assertEqual(len(result['signatures']), 1)

    def test_sign_with_using_unknown_cipher(self):
        signer = Signer(user=self.user, signature=DummySignature, key_name="test_3")
        signer.generate_key_pairs()

        doc = Document(document=test_file)
        doc.add_signer(signer)
        with pytest.raises(DigitalSignatureException) as e:
            doc.sign_with_hash(cipher="abc123")

        self.assertEqual(str(e.value), "Unknown cipher.")

    def test_sign_with_certificate(self):
        pass
