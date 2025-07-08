import logging
from builtins import object, str

from django import db
from django.contrib.auth.models import User
from django.core import exceptions
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _
from phonenumber_field.validators import validate_international_phonenumber
from rest_framework.serializers import (
    CharField,
    IntegerField,
    ModelSerializer,
    Serializer,
    ValidationError,
)

from juloserver.julo.models import (
    Application,
    Customer,
    Partner,
    PartnerAddress,
    PartnerLoan,
    PartnerReferral,
    PartnerTransaction,
    PartnerTransactionItem,
)
from juloserver.julo.utils import check_email

logger = logging.getLogger(__name__)


class PartnerSerializer(ModelSerializer):
    class Meta(object):
        model = Partner
        fields = ('name',)


class PartnerTransactionItemSerializer(ModelSerializer):
    class Meta(object):
        model = PartnerTransactionItem
        exclude = ('partner_transaction', 'id', 'cdate', 'udate')


class PartnerAddressSerializer(ModelSerializer):
    class Meta(object):
        model = PartnerAddress
        exclude = ('partner_referral', 'partner_transaction', 'id', 'cdate', 'udate')


class PartnerTransactionSerializer(ModelSerializer):
    address = PartnerAddressSerializer(required=False)
    transaction_items = PartnerTransactionItemSerializer(many=True, required=False)

    class Meta(object):
        model = PartnerTransaction
        exclude = ('partner_referral', 'id', 'cdate', 'udate')


class PartnerReferralSerializer(ModelSerializer):
    transactions = PartnerTransactionSerializer(many=True, required=False)
    addresses = PartnerAddressSerializer(many=True, required=False)
    partner = PartnerSerializer(required=False)

    class Meta(object):
        model = PartnerReferral
        exclude = ('customer', 'id', 'cdate', 'udate')

    def create(self, validated_data):

        with db.transaction.atomic():

            transactions = []
            if 'transactions' in validated_data:
                transactions = validated_data.pop('transactions')

            addresses = []
            if 'addresses' in validated_data:
                addresses = validated_data.pop('addresses')

            if 'mobile_phone' in validated_data:
                validated_data = self.set_mobile_phone_1(validated_data)

            validated_data = self.set_pre_exist(validated_data)
            partner_referral = super(PartnerReferralSerializer, self).create(validated_data)
            logger.info(
                {'status': 'partner_referral_created', 'email': validated_data['cust_email']}
            )

            for address in addresses:
                self.validate_address(address)

                address = PartnerAddress.objects.create(
                    partner_referral=partner_referral, **address
                )
                logger.info(
                    {'status': 'partner_address_created', 'email': validated_data['cust_email']}
                )

            transaction_items = []
            for transaction in transactions:
                if 'transaction_items' in transaction:
                    transaction_items = transaction.pop('transaction_items')

                address = None
                if 'address' in transaction:
                    address = transaction.pop('address')

                partner_transaction = PartnerTransaction.objects.create(
                    partner_referral=partner_referral, **transaction
                )
                logger.info(
                    {'status': 'partner_transaction_created', 'email': validated_data['cust_email']}
                )

                if address is not None:
                    self.validate_address(address)

                    PartnerAddress.objects.create(
                        partner_transaction=partner_transaction, **address
                    )
                    logger.info(
                        {
                            'status': 'partner_transaction_address_created',
                            'email': validated_data['cust_email'],
                        }
                    )

                for transaction_item in transaction_items:
                    PartnerTransactionItem.objects.create(
                        partner_transaction=partner_transaction, **transaction_item
                    )
                    logger.info(
                        {
                            'status': 'partner_transaction_item_created',
                            'email': validated_data['cust_email'],
                        }
                    )
            partner_referral.refresh_from_db()
        return partner_referral

    def validate_address(self, address):
        """If at least 1 field is provided
        then address_type shouldn't be null
        """
        address_fields = [
            'address_street_num',
            'address_provinsi',
            'address_kabupaten',
            'address_kecamatan',
            'address_kelurahan',
            'address_kodepos',
        ]
        if any(address_field in address for address_field in address_fields):
            if 'address_type' not in address or not bool(address["address_type"]):
                raise ValidationError("address_type can not be null or empty")

    def set_pre_exist(self, validated_data):
        cust_email = validated_data['cust_email']
        if cust_email:
            cust_email = cust_email.lower()

        customer = Customer.objects.filter(
            Q(email=cust_email) | Q(nik=validated_data['cust_nik'])
        ).exists()
        partner_referral = PartnerReferral.objects.filter(
            Q(cust_email=cust_email) | Q(cust_nik=validated_data['cust_nik'])
        ).exists()

        if partner_referral or customer:
            validated_data['pre_exist'] = True
        else:
            validated_data['pre_exist'] = False
        return validated_data

    def set_mobile_phone_1(self, validated_data):
        validated_data['mobile_phone_1'] = validated_data['mobile_phone']
        return validated_data


class RegistrationSerializer(Serializer):

    username = CharField(label=_("Username"))
    password = CharField(label=_("Password"))
    email = CharField(label=_("Email"), required=False)
    phone = CharField(label=_("Phone"), required=False)

    def validate_username(self, value):
        try:
            username = value.lower().strip()
            User.objects.get(username=username)
            logger.error({'status': 'validation_failed', 'field': 'username', 'value': value})
            raise ValidationError("Username is taken")
        except User.DoesNotExist:
            value = username
            return value

    def validate_email(self, value):
        email_valid = check_email(value)
        if not email_valid:
            logger.error({'status': 'validation_failed', 'field': 'email', 'value': value})
            raise ValidationError("Email is not valid")
        return value

    def validate_phone(self, value):
        try:
            validate_international_phonenumber(value)
        except exceptions.ValidationError as ve:
            logger.error({'status': 'validation_failed', 'field': 'phone', 'value': value})
            raise ValidationError(str(ve))
        return value


class LoginSerializer(Serializer):
    username = CharField(label=_("Username"))
    password = CharField(label=_("Password"))


class PartnerLoanSerializer(ModelSerializer):
    class Meta(object):
        model = PartnerLoan


class PartnerTransactionSerializer(Serializer):
    amount = IntegerField(label=_("Amount"))
    type_transaction = CharField(label=_("Type"))

    def validate_amount(self, value):
        if value < 1:
            logger.error({'status': 'validation_failed', 'field': 'amount', 'value': value})
            raise ValidationError("amount invalid")
        return value

    def validate_type_transaction(self, value):
        if value not in {'deposit', 'withdraw'}:
            logger.error(
                {'status': 'validation_failed', 'field': 'type_transaction', 'value': value}
            )
            raise ValidationError("type invalid")
        return value


class ApplicationUpdateSerializer(ModelSerializer):
    class Meta(object):
        model = Application
        fields = ('new_mobile_phone', 'loan_amount_request', 'loan_duration_request')
