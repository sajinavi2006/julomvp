import factory
from factory import SubFactory

from juloserver.account.tests.factories import AccountFactory
from juloserver.fraud_security.constants import FraudApplicationBucketType
from juloserver.fraud_security.models import (
    FraudApplicationBucket,
    FraudBlacklistedCompany,
    FraudBlacklistedASN,
    FraudFlag,
    FraudHighRiskAsn,
    FraudVelocityModelGeohash,
    FraudVelocityModelGeohashBucket,
    FraudVelocityModelResultsCheck,
    FraudVerificationResults,
    SecurityWhitelist,
    FraudBlacklistedPostalCode,
    FraudBlacklistedGeohash5,
    FraudSwiftLimitDrainerAccount,
    FraudAppealTemporaryBlock,
    FraudTelcoMaidTemporaryBlock,
    FraudGdDeviceSharingAccount,
    BankNameVelocityThresholdHistory,
    FraudBlockAccount,
)
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CustomerFactory,
    StatusLookupFactory,
)


class SecurityWhitelistFactory(factory.DjangoModelFactory):
    class Meta:
        model = SecurityWhitelist

    customer = factory.SubFactory(CustomerFactory)


class FraudFlagFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudFlag


class FraudVelocityModelGeohashFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudVelocityModelGeohash

    geohash = 'qwertyui'
    risky_date = '2023-01-10'
    application = factory.SubFactory(ApplicationJ1Factory)


class FraudVelocityModelGeohashBucketFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudVelocityModelGeohashBucket

    geohash = 'qwertyui'


class FraudVelocityModelResultsCheckFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudVelocityModelResultsCheck

    is_fraud = False


class FraudVerificationResultsFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudVerificationResults

    application = factory.SubFactory(ApplicationJ1Factory)
    bucket = "factory bucket"
    reason = "factory reason"


class FraudApplicationBucketFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudApplicationBucket

    application = factory.SubFactory(
        ApplicationJ1Factory,
        application_status=factory.SubFactory(StatusLookupFactory, status_code=115),
    )
    type = FraudApplicationBucketType.SELFIE_IN_GEOHASH
    is_active = True


class FraudBlacklistedCompanyFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudBlacklistedCompany

    company_name = factory.sequence(lambda n: 'company_name_%d' % n)


class FraudBlacklistedASNFactory(factory.DjangoModelFactory):
    class Meta(object):
        model = FraudBlacklistedASN


class FraudHighRiskAsnFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudHighRiskAsn

    name = 'AS001 PT Dummy Indonesia'


class FraudBlacklistedPostalCodeFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudBlacklistedPostalCode

    postal_code = '12345'


class FraudBlacklistedGeohash5Factory(factory.DjangoModelFactory):
    class Meta:
        model = FraudBlacklistedGeohash5

    geohash5 = '12345'


class FraudSwiftLimitDrainerAccountFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudSwiftLimitDrainerAccount

    account = SubFactory(AccountFactory)


class FraudGdDeviceSharingAccountFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudGdDeviceSharingAccount

    account = SubFactory(AccountFactory)


class FraudTelcoMaidTemporaryBlockFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudTelcoMaidTemporaryBlock

    account = SubFactory(AccountFactory)


class FraudAppealTemporaryBlockFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudAppealTemporaryBlock

    account_id = 1


class BankNameVelocityThresholdHistoryFactory(factory.DjangoModelFactory):
    class Meta:
        model = BankNameVelocityThresholdHistory


class FraudBlockAccountFactory(factory.DjangoModelFactory):
    class Meta:
        model = FraudBlockAccount
