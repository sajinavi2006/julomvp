from builtins import object

import factory
from factory.django import DjangoModelFactory
from factory import SubFactory
from juloserver.autodebet.models import (
    AutodebetAPILog,
    AutodebetAccount,
    AutodebetBenefit,
    AutodebetBenefitDetail,
    AutodebetBenefitCounter,
    AutodebetBRITransaction,
    AutodebetMandiriAccount,
    AutodebetMandiriTransaction,
    AutodebetDanaTransaction,
    AutodebetDeactivationSurveyQuestion,
    AutodebetDeactivationSurveyAnswer,
    AutodebetDeactivationSurveyUserAnswer,
    AutodebetPaymentOffer,
    AutodebetOvoTransaction,
)
from juloserver.account.tests.factories import AccountwithApplicationFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    PaymentFactory,
)
from juloserver.dana_linking.tests.factories import DanaWalletAccountFactory
from juloserver.ovo.tests.factories import OvoWalletAccountFactory
from juloserver.autodebet.constants import (
    AutodebetDANAPaymentResultStatusConst,
    AutodebetOVOPaymentResultStatusConst,
)

class AutodebetBenefitFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetBenefit

    benefit_type = ""
    benefit_value = ""
    is_benefit_used = False

    @factory.lazy_attribute
    def account_id(self):
        account = AccountwithApplicationFactory()
        return account.id


class AutodebetBenefitDetailFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetBenefitDetail

    autodebet_benefit = SubFactory(AutodebetBenefitFactory)
    payment = SubFactory(PaymentFactory)
    benefit_value = None

    @factory.lazy_attribute
    def account_payment_id(self):
        account = AccountPaymentFactory()
        return account.id


class AutodebetBenefitCounterFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetBenefitCounter

    name = ""
    counter = 1


class AutodebetAccountFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetAccount

    account = SubFactory(AccountwithApplicationFactory)
    vendor = "BCA"
    is_use_autodebet = False
    registration_ts = None
    activation_ts = None
    failed_ts = None
    failed_reason = ""
    is_deleted_autodebet = False
    deleted_request_ts = None
    deleted_success_ts = None
    deleted_failed_ts = None
    deleted_failed_reason = ""
    request_id = ""
    verification = ""
    db_account_no = ""
    retry_count = 0


class AutodebetAPILogFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetAPILog

    request_type = ""
    http_status_code = 400
    request = None
    response = None
    error_message = None

    @factory.lazy_attribute
    def application_id(self):
        application = ApplicationFactory()
        return application.id

    @factory.lazy_attribute
    def account_id(self):
        account = AccountwithApplicationFactory()
        return account.id

    @factory.lazy_attribute
    def account_payment_id(self):
        account_payment = AccountPaymentFactory()
        return account_payment.id


class AutodebetBRITransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetBRITransaction

    autodebet_account = SubFactory(AutodebetAccountFactory)
    account_payment = SubFactory(AccountPaymentFactory)
    status = 'INITIAL'


class AutodebetMandiriAccountFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetMandiriAccount

    autodebet_account = SubFactory(AutodebetAccountFactory)
    bank_card_token = '1234567890'


class AutodebetMandiriTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetMandiriTransaction

    autodebet_mandiri_account = SubFactory(AutodebetMandiriAccountFactory)
    amount = 100000
    original_partner_reference_no = '1234567890'


class AutodebetDanaTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetDanaTransaction

    dana_wallet_account = SubFactory(DanaWalletAccountFactory)
    account_payment = SubFactory(AccountPaymentFactory)
    original_partner_reference_no = '1234567890'
    original_reference_no = '1234567890'
    amount = 100000
    status = AutodebetDANAPaymentResultStatusConst.PENDING


class AutodebetOvoTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetOvoTransaction

    ovo_wallet_account = SubFactory(OvoWalletAccountFactory)
    account_payment_id = 12345
    original_partner_reference_no = '1234567890'
    original_reference_no = '1234567890'
    amount = 100000
    status = AutodebetOVOPaymentResultStatusConst.PENDING

class AutodebetDeactivationSurveyQuestionFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetDeactivationSurveyQuestion

    question = 'Kenapa kamu mau nonaktifkan autodebit?'


class AutodebetDeactivationSurveyAnswerFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetDeactivationSurveyAnswer

    question = SubFactory(AutodebetDeactivationSurveyQuestionFactory)
    answer = 'Tidak menggunakan autodebit lagi'
    order = 1


class AutodebetDeactivationSurveyUserAnswer(DjangoModelFactory):
    class Meta(object):
        model = AutodebetDeactivationSurveyUserAnswer

    account_id = 123
    autodebet_account_id = 123
    question = 'Kenapa kamu mau nonaktifkan autodebit?'
    answer = 'Tidak menggunakan autodebit lagi'


class AutodebetPaymentOfferFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetPaymentOffer

    account_id = 123
    counter = True
    is_should_show = True
