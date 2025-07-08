from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment
from juloserver.customer_module.services.customer_related import (
    get_ongoing_account_deletion_request,
)
from juloserver.customer_module.services.pii_vault import detokenize_sync_object_model
from juloserver.cx_external_party.constants import (
    ALLOWLISTED_EMAIL_DOMAIN,
    ERROR_MESSAGE,
)
from juloserver.cx_external_party.crypto import get_crypto
from juloserver.cx_external_party.helpers import parse_human_date
from juloserver.cx_external_party.models import CXExternalParty
from juloserver.cx_external_party.services import (
    get_history_list,
)
from juloserver.julo.models import (
    CustomerWalletHistory,
    Image,
    Loan,
    Payment,
    PaymentMethod,
)
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType


class ExternalPartySerializer(serializers.ModelSerializer):
    class Meta(object):
        model = CXExternalParty
        fields = ('id', 'name', 'expiry_date', 'cdate', 'udate')


class UserTokenSerializer(serializers.Serializer):
    token = serializers.ReadOnlyField()
    identifier = serializers.CharField(
        error_messages={
            "required": ERROR_MESSAGE.USER_EXTERNAL_PARTY_IDENTIFIER_REQUIRED,
            "blank": ERROR_MESSAGE.USER_EXTERNAL_PARTY_IDENTIFIER_REQUIRED,
            "null": ERROR_MESSAGE.USER_EXTERNAL_PARTY_IDENTIFIER_REQUIRED,
        }
    )
    user_exp = serializers.CharField(required=False, allow_blank=True)

    def validate_identifier(self, identifier):
        try:
            domain_name = identifier.split("@")[1]
        except IndexError:
            raise ValidationError(ERROR_MESSAGE.USER_IDENTIFIER_MUST_BE_EMAIL)
        if domain_name not in ALLOWLISTED_EMAIL_DOMAIN:
            raise ValidationError(ERROR_MESSAGE.USER_IDENTIFIER_NOT_VALID)

        auth_user = User.objects.filter(email=identifier).first()
        if not auth_user:
            raise ValidationError(ERROR_MESSAGE.USER_APPLICATION_NOT_FOUND)

        if not auth_user.is_staff:
            raise ValidationError(ERROR_MESSAGE.USER_IDENTIFIER_NOT_ALLOWED)

        return identifier

    def validate_user_exp(self, user_exp=None):
        today = timezone.localtime(timezone.now()).replace(tzinfo=None).replace(microsecond=0)
        user_expiry_date = today + timedelta(days=1)
        exp_timestamp = datetime.strptime(str(user_expiry_date), "%Y-%m-%d %H:%M:%S").timestamp()
        if not user_exp:
            user_exp = exp_timestamp
        else:
            user_exp = float(user_exp)
            today_timestamp = datetime.strptime(str(today), "%Y-%m-%d %H:%M:%S").timestamp()
            if user_exp > exp_timestamp or user_exp < today_timestamp:
                raise ValidationError(ERROR_MESSAGE.USER_EXTERNAL_PARTY_EXPIRY_TIME)

        return user_exp

    def create(self, validated_data):
        identifier = validated_data["identifier"]
        if "user_exp" not in validated_data:
            validated_data["user_exp"] = self.validate_user_exp()

        user_exp = validated_data["user_exp"]
        key = self.context.get("key")
        payload = {"api_key": key, "identifier": identifier, "user_exp": user_exp}
        data, user_token = get_crypto().assign_user_token(payload)

        result = {
            "token": user_token,
            "identifier": data["_identifier"],
            "user_exp": data["_exp"],
        }
        return result


class CustomerInfoSerializer(serializers.Serializer):
    customer_id = serializers.ReadOnlyField(source="id")
    application_id = serializers.ReadOnlyField(
        source="get_active_or_last_application.id", default=""
    )
    application_number = serializers.ReadOnlyField(
        source="get_active_or_last_application.application_number", default=""
    )
    application_status = serializers.ReadOnlyField(
        source="get_active_or_last_application.status", default=""
    )
    application_pline = serializers.ReadOnlyField(
        source="get_active_or_last_application.product_line.product_line_type", default=""
    )
    application_partner_name = serializers.ReadOnlyField(
        source="get_active_or_last_application.partner.name", default=""
    )
    application_udate = serializers.ReadOnlyField(
        source="get_active_or_last_application.udate", default=""
    )
    email = serializers.SerializerMethodField()
    fullname = serializers.SerializerMethodField()
    account_status = serializers.ReadOnlyField(
        source="get_active_or_last_application.account.status_id", default=None
    )
    is_active = serializers.ReadOnlyField(default="")
    is_deleted = serializers.ReadOnlyField(
        source="get_active_or_last_application.is_deleted", default=None
    )
    is_request_deletion = serializers.SerializerMethodField()

    def get_is_request_deletion(self, obj):
        return True if get_ongoing_account_deletion_request(obj) else False

    def get_email(self, obj):
        if not obj.email:
            return ""

        detokenized_cust = detokenize_sync_object_model(
            PiiSource.CUSTOMER, PiiVaultDataType.PRIMARY, [obj], ["email"]
        )[0]
        return detokenized_cust.email

    def get_fullname(self, obj):
        if not obj.fullname:
            return ""

        detokenized_cust = detokenize_sync_object_model(
            PiiSource.CUSTOMER, PiiVaultDataType.PRIMARY, [obj], ["fullname"]
        )[0]
        return detokenized_cust.fullname


class SecurityInfoSerializer(serializers.Serializer):
    fullname = serializers.ReadOnlyField(source="get_active_or_last_application.fullname")
    dob = serializers.ReadOnlyField(source="get_active_or_last_application.dob")
    mother_maiden_name = serializers.ReadOnlyField()
    bank_name = serializers.ReadOnlyField(source="get_active_or_last_application.bank_name")
    bank_account_name = serializers.ReadOnlyField(
        source="get_active_or_last_application.name_in_bank"
    )
    bank_account_number = serializers.ReadOnlyField(
        source="get_active_or_last_application.bank_account_number"
    )
    phone = serializers.ReadOnlyField(source="get_active_or_last_application.mobile_phone_1")
    credit_limit = serializers.SerializerMethodField()
    email = serializers.ReadOnlyField(source="get_active_or_last_application.email")

    def get_credit_limit(self, obj):
        credit_limit = None
        try:
            account_limit = obj.get_active_or_last_application.account.accountlimit_set.last()
            credit_limit = account_limit.set_limit
        except AttributeError:
            pass

        return credit_limit


class AppDcoumentVerifySerializer(serializers.ModelSerializer):
    class Meta:
        model = Image
        fields = (
            "image_source",
            "image_type",
            "image_url",
            "image_url_api",
            "thumbnail_url",
            "image_status",
            "application_id",
            "public_image_url",
            "static_image_url",
        )


class CustomerPersonalDataSerializer(serializers.Serializer):
    fullname = serializers.ReadOnlyField(source="get_active_or_last_application.fullname")
    nik = serializers.ReadOnlyField(source="get_active_or_last_application.ktp")
    dob = serializers.ReadOnlyField(source="get_active_or_last_application.dob")
    age = serializers.SerializerMethodField()
    address = serializers.ReadOnlyField(source="get_active_or_last_application.complete_addresses")
    app_version = serializers.ReadOnlyField(source="get_active_or_last_application.app_version")
    referral_code = serializers.ReadOnlyField(source="get_active_or_last_application.referral_code")
    credit_score = serializers.ReadOnlyField(
        source="get_active_or_last_application.creditscore.score"
    )
    credit_score_message = serializers.ReadOnlyField(
        source="get_active_or_last_application.creditscore.message"
    )

    def get_age(self, obj):
        from dateutil.relativedelta import relativedelta

        dob = obj.get_active_or_last_application.dob
        if not dob:
            return None

        return relativedelta(datetime.today(), dob).years


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = PaymentMethod
        fields = (
            'payment_method_code',
            'payment_method_name',
            'bank_code',
            'virtual_account',
            'is_primary',
        )


class PaymentSerializer(serializers.ModelSerializer):
    dpd = serializers.ReadOnlyField(source="get_dpd")
    payment_method = serializers.SerializerMethodField()

    class Meta(object):
        model = Payment
        fields = (
            'due_amount',
            'dpd',
            'late_fee_amount',
            'status',
            'cashback_earned',
            'paid_amount',
            'payment_method',
        )

    def get_payment_method(self, obj):
        customer_id = self.context.get('customer_id')
        payment_method = PaymentMethod.objects.filter(customer=customer_id, is_primary=True).last()
        payment_method = PaymentMethodSerializer(payment_method).data
        return payment_method


class CustomerWalletSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = CustomerWalletHistory
        fields = ('change_reason',)


class LoanSerializer(serializers.ModelSerializer):
    product_type = serializers.ReadOnlyField(source='transaction_method.fe_display_name')
    payments = serializers.SerializerMethodField()
    fund_transfer_ts = serializers.SerializerMethodField()
    wallets = serializers.SerializerMethodField()

    class Meta(object):
        model = Loan
        fields = (
            'loan_status',
            'product_type',
            'fund_transfer_ts',
            'payments',
            'wallets',
        )

    def get_fund_transfer_ts(self, obj):
        date = parse_human_date(obj.fund_transfer_ts)
        return date

    def get_payments(self, obj):
        customer_id = self.context.get('customer_id')
        payments = Payment.objects.filter(loan=obj).all()
        payment = PaymentSerializer(
            payments,
            context={
                'customer_id': customer_id,
            },
            many=True,
        ).data
        return payment

    def get_wallets(self, obj):
        customer_id = self.context.get('customer_id')
        wallets = CustomerWalletHistory.objects.filter(customer_id=customer_id, loan=obj).order_by(
            '-id'
        )
        wallets = wallets.exclude(change_reason__contains='_old').order_by('-id')
        wallets = CustomerWalletSerializer(
            wallets,
            many=True,
        ).data
        return wallets


class AccountPaymentSerializer(serializers.ModelSerializer):
    dpd = serializers.ReadOnlyField()

    class Meta(object):
        model = AccountPayment
        fields = (
            'status',
            'due_amount',
            'late_fee_amount',
            'dpd',
            'paid_amount',
        )


class CustomerLoanPaymentSerializer(serializers.Serializer):
    application_status_notes = serializers.SerializerMethodField()
    credit_score = serializers.ReadOnlyField(
        source="get_active_or_last_application.creditscore.score"
    )
    credit_score_message = serializers.ReadOnlyField(
        source="get_active_or_last_application.creditscore.message"
    )
    customer_name = serializers.ReadOnlyField(source="get_active_or_last_application.fullname")
    birthdate = serializers.ReadOnlyField(source="get_active_or_last_application.dob")
    mother_maiden_name = serializers.ReadOnlyField()
    can_reapply_date = serializers.SerializerMethodField()
    loan = serializers.SerializerMethodField()

    def get_application_status_notes(self, obj):
        user_status_history = get_history_list(obj)
        return user_status_history

    def get_can_reapply_date(self, obj):
        date = parse_human_date(obj.can_reapply_date)
        return date

    def get_loan(self, obj):
        account = Account.objects.filter(customer_id=obj.id).first()
        if not account:
            return []

        all_Loans = account.loan_set
        if not all_Loans:
            return []

        loan = LoanSerializer(
            all_Loans,
            context={
                'customer_id': obj.id,
            },
            many=True,
        ).data
        return loan
