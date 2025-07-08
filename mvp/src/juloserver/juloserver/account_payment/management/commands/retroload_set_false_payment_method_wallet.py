from django.core.management.base import BaseCommand
import semver

from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.models import PaymentMethod
from juloserver.julo.services2.payment_method import get_bank_code_by_bank_name
from juloserver.julo.banks import BankCodes
from juloserver.account_payment.constants import OLD_APP_VERSION


class Command(BaseCommand):
    help = "Change primary for wallet payment method"

    def handle(self, *args, **options):
        payment_methods = PaymentMethod.objects.filter(
            payment_method_code__in={PaymentMethodCodes.DANA, PaymentMethodCodes.GOPAY,
                                     PaymentMethodCodes.GOPAY_TOKENIZATION, PaymentMethodCodes.OVO},
            is_primary=True
        )
        for payment_method in payment_methods.iterator():
            account = payment_method.customer.account
            if not account:
                continue
            app_version = account.app_version
            application = account.application_set.only('id', 'app_version', 'bank_name').last()
            if not application:
                continue
            app_version = app_version or application.app_version
            try:
                is_old_app_version = semver.match(app_version, "<={}".format(OLD_APP_VERSION))
            except TypeError as e:
                self.stdout.write(
                    self.style.ERROR(
                        "account id {} Error check app version {}".format(account.id, str(e))
                    )
                )
                continue
            if not is_old_app_version:
                continue
            payment_method.update_safely(is_primary=False)
            bank_payment_method = PaymentMethod.objects.filter(
                customer=payment_method.customer,
                bank_code=get_bank_code_by_bank_name(application.bank_name)
            ).last()
            if not bank_payment_method:
                bank_payment_method = PaymentMethod.objects.filter(
                    customer=payment_method.customer,
                    bank_code=BankCodes.PERMATA
                ).last()
            bank_payment_method.update_safely(is_primary=True)
        self.stdout.write(
            self.style.SUCCESS("Successfully change primary for wallet payment method")
        )
