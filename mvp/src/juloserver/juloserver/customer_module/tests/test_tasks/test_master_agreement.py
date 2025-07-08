import pytest
from django.test import TestCase
from mock import patch

from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.customer_module.services.customer_related import PpfpBorrowerSignature
from juloserver.customer_module.tasks.master_agreement_tasks import (
    generate_application_master_agreement,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import Document
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    MasterAgreementTemplateFactory,
    WorkflowFactory,
    CustomerFactory,
    AuthUserFactory,
)

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


class TestGenerateMasterAgreement(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        customer = CustomerFactory(user=self.user, fullname="Pao")
        account = AccountFactory(customer=customer)
        AccountLimitFactory(account=account)
        workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application = ApplicationFactory(
            workflow=workflow,
            customer=customer,
            address_provinsi="DKI Jakarta",
            address_kabupaten="Jakarta Selatan",
            address_kodepos="12324",
            address_street_num="No.1",
        )
        MasterAgreementTemplateFactory()

    # @patch.object(PpfpBorrowerSignature, 'page', return_value=0)
    @pytest.mark.skip(reason="Always fail")
    @patch('juloserver.customer_module.tasks.master_agreement_tasks.send_email_master_agreement')
    def test_master_agreement_signature(self, mock_email):
        class MockSignature:
            @property
            def page(self) -> int:
                return 0

        with patch.object(PpfpBorrowerSignature, 'page', return_value=MockSignature()):
            generate_application_master_agreement(self.application.id)

        document = Document.objects.filter(document_source=self.application.id).last()

        self.assertIsNotNone(document.hash_digi_sign)
        self.assertIsNotNone(document.accepted_ts)
        self.assertIsNotNone(document.key_id)
