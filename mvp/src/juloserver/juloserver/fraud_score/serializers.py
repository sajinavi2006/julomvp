import logging
from builtins import object
from collections import OrderedDict

from django.utils import timezone
from rest_framework import serializers

from juloserver.fraud_score.constants import BonzaConstants, TrustGuardConst
from juloserver.fraud_score.models import SeonFingerprint
from juloserver.julo.models import Loan, Application, AddressGeolocation, Payment

logger = logging.getLogger(__name__)


def format_mobile_phone(phone_number):
    if phone_number.startswith('0'):
        return phone_number.replace('0', '+62', 1)
    elif phone_number.startswith('62'):
        return phone_number.replace('62', '+62', 1)
    elif phone_number.startswith('+62'):
        return phone_number
    else:
        return '+62' + phone_number


def fetch_android_id(customer):
    device = customer.device_set.last()
    if device and device.android_id not in [None, '']:
        return device.android_id
    login_attempt = customer.loginattempt_set.last()
    if login_attempt and login_attempt.android_id not in [None, '']:
        return login_attempt.android_id
    return None


class CoordinatesSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class UserSerializer(serializers.Serializer):
    user_id = serializers.CharField(source='customer_id')


class PhoneNumberSerializer(serializers.Serializer):
    phone_number = serializers.SerializerMethodField()

    def get_phone_number(self, obj):
        if obj.mobile_phone_1:
            return format_mobile_phone(obj.mobile_phone_1)
        return obj.mobile_phone_1


class EmergencyContactSerializer(serializers.Serializer):
    name = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()

    def get_name(self, obj):
        source = self.context.get('source', None)
        if source:
            return getattr(obj, source + '_name')
        return None

    def get_phone_number(self, obj):
        source = self.context.get('source', None)
        if source:
            phone_number = getattr(obj, source + '_mobile_phone')
            return format_mobile_phone(phone_number)
        return None


class KtpSerializer(serializers.Serializer):
    ktp_no = serializers.CharField(source='ktp')
    fullname = serializers.CharField()
    dob = serializers.DateField()
    gender = serializers.CharField()
    birth_place = serializers.CharField()
    marital_status = serializers.CharField()


class ApplicationSerializer(serializers.ModelSerializer):
    application_id = serializers.CharField(source='id')
    customer_credit_limit = serializers.SerializerMethodField()
    application_status = serializers.CharField(source='application_status.status')

    def to_representation(self, instance):
        result = super(ApplicationSerializer, self).to_representation(instance)
        data = OrderedDict([(key, result[key]) for key in result if result[key] is not None])
        for field in BonzaConstants.APPLICATION_PHONE_FIELDS:
            if data.get(field):
                data[field] = format_mobile_phone(data.get(field))
        return data

    def get_customer_credit_limit(self, instance):
        customer = instance.customer
        if hasattr(customer, 'customercreditlimit'):
            return customer.customercreditlimit.customer_credit_limit
        return None

    class Meta(object):
        model = Application
        fields = BonzaConstants.APPLICATION_FIELDS


class BonzaApplicationAPISerializer(serializers.Serializer):
    app = serializers.SerializerMethodField()
    coordinates = serializers.SerializerMethodField()
    ip = serializers.SerializerMethodField()
    timestamp = serializers.SerializerMethodField()

    def to_representation(self, instance):
        data = super(BonzaApplicationAPISerializer, self).to_representation(instance)
        data['event'] = ApplicationSerializer(instance).data
        data['email'] = {
            'email': instance.customer.email if not instance.email else instance.email}
        data['phone_number'] = PhoneNumberSerializer(self.instance).data
        data['ktp'] = KtpSerializer(self.instance).data
        data['user'] = UserSerializer(self.instance).data
        emergency_contact_sources = [('1', 'kin'), ('2', 'close_kin'), ('3', 'spouse')]
        for num, source in dict(emergency_contact_sources).items():
            if getattr(instance, source + '_name') and getattr(instance, source + '_mobile_phone'):
                data['emergency_contact_' + num] = EmergencyContactSerializer(
                    instance, context={'source': source}).data
        return data

    def get_app(self, obj):
        customer = obj.customer
        android_id = fetch_android_id(customer)
        return {'device_id': android_id}

    def get_coordinates(self, obj):
        geolocation = AddressGeolocation.objects.filter(
            application=obj).last()
        if not geolocation:
            customer = obj.customer
            device = customer.device_set.last()
            if device:
                geolocation = device.devicegeolocation_set.last()
        if not geolocation:
            geolocation = obj.customer.loginattempt_set.last()
        if geolocation:
            return CoordinatesSerializer(geolocation).data
        return None, None

    def get_ip(self, obj):
        device_ip = obj.customer.deviceiphistory_set.last()
        ip_address = device_ip.ip_address if device_ip else None
        return {'ip_address': ip_address}

    def get_timestamp(self, obj):
        return timezone.localtime(timezone.now())


class LoanSerializer(serializers.ModelSerializer):
    loan_transaction_id = serializers.CharField(source='id')
    application_id = serializers.CharField(source='application_id2')
    loan_status = serializers.CharField(source='loan_status.status')

    def to_representation(self, instance):
        result = super(LoanSerializer, self).to_representation(instance)
        return OrderedDict([(key, result[key]) for key in result if result[key] is not None])

    class Meta(object):
        model = Loan
        fields = BonzaConstants.LOAN_TRANSACTION_FIELDS


class BonzaLoanTransactionAPISerializer(serializers.Serializer):
    app = serializers.SerializerMethodField()
    coordinates = serializers.SerializerMethodField()
    ip = serializers.SerializerMethodField()
    timestamp = serializers.SerializerMethodField()

    def to_representation(self, instance):
        data = super(BonzaLoanTransactionAPISerializer, self).to_representation(instance)
        data['event'] = LoanSerializer(instance).data
        data['user'] = UserSerializer(instance).data
        return data

    def get_app(self, obj):
        customer = obj.customer
        android_id = fetch_android_id(customer)
        return {'device_id': android_id}

    def get_coordinates(self, obj):
        geolocation = None
        device = obj.customer.device_set.last()
        if device:
            geolocation = device.devicegeolocation_set.filter(reason='transaction').last()
            if not geolocation:
                geolocation = device.devicegeolocation_set.last()
        if not geolocation and obj.account:
            application = obj.account.last_application
            if application:
                geolocation = AddressGeolocation.objects.filter(
                    application=application).last()
        if not geolocation:
            geolocation = obj.customer.loginattempt_set.last()
        if geolocation:
            return CoordinatesSerializer(geolocation).data
        return None, None

    def get_ip(self, obj):
        device_ip = obj.customer.deviceiphistory_set.last()
        ip_address = device_ip.ip_address if device_ip else None
        return {'ip_address': ip_address}

    def get_timestamp(self, obj):
        return timezone.localtime(timezone.now())


class PaymentSerializer(serializers.ModelSerializer):
    loan_payment_id = serializers.CharField(source='id')
    loan_transaction_id = serializers.CharField(source='loan_id')

    def to_representation(self, instance):
        result = super(PaymentSerializer, self).to_representation(instance)
        return OrderedDict([(key, result[key]) for key in result if result[key] is not None])

    class Meta(object):
        model = Payment
        fields = BonzaConstants.LOAN_PAYMENT_FIELDS


class BonzaLoanPaymentAPISerializer(serializers.Serializer):
    app = serializers.SerializerMethodField()
    coordinates = serializers.SerializerMethodField()
    ip = serializers.SerializerMethodField()
    timestamp = serializers.SerializerMethodField()

    def to_representation(self, instance):
        data = super(BonzaLoanPaymentAPISerializer, self).to_representation(instance)
        data['event'] = PaymentSerializer(instance).data
        data['user'] = UserSerializer(instance.loan).data
        return data

    def get_app(self, obj):
        customer = obj.loan.customer
        android_id = fetch_android_id(customer)
        return {'device_id': android_id}

    def get_coordinates(self, obj):
        geolocation = None
        device = obj.loan.customer.device_set.last()
        if device:
            geolocation = device.devicegeolocation_set.filter(reason='transaction').last()
            if not geolocation:
                geolocation = device.devicegeolocation_set.last()
        if not geolocation and obj.loan.account:
            application = obj.loan.account.last_application
            if application:
                geolocation = AddressGeolocation.objects.filter(
                    application=application).last()
        if not geolocation:
            geolocation = obj.loan.customer.loginattempt_set.last()
        if geolocation:
            return CoordinatesSerializer(geolocation).data
        return None, None

    def get_ip(self, obj):
        device_ip = obj.loan.customer.deviceiphistory_set.last()
        ip_address = device_ip.ip_address if device_ip else None
        return {'ip_address': ip_address}

    def get_timestamp(self, obj):
        return timezone.localtime(timezone.now())


class BonzaLoanTransactionScoringAPISerializer(serializers.Serializer):
    user_id = serializers.CharField(source='customer_id')
    coordinates = serializers.SerializerMethodField()

    def to_representation(self, instance):
        data = super(BonzaLoanTransactionScoringAPISerializer, self).to_representation(instance)
        email, phone_number = None, None
        if instance.account:
            email = instance.account.last_application.email
            phone_number = instance.account.last_application.mobile_phone_1
        email = instance.customer.email if not email else email
        phone_number = instance.customer.phone if not phone_number else phone_number
        data['device_id'] = fetch_android_id(instance.customer)
        data['email'] = email
        data['phone_number'] = format_mobile_phone(phone_number)
        return data

    def get_coordinates(self, obj):
        geolocation = None
        device = obj.customer.device_set.last()
        if device:
            geolocation = device.devicegeolocation_set.filter(reason='transaction').last()
            if not geolocation:
                geolocation = device.devicegeolocation_set.last()
        if not geolocation and obj.account:
            application = obj.account.last_application
            if application:
                geolocation = AddressGeolocation.objects.filter(
                    application=application).last()
        if not geolocation:
            geolocation = obj.customer.loginattempt_set.last()
        if geolocation:
            return CoordinatesSerializer(geolocation).data
        return None, None


class BonzaInhousePredictionAPISerializer(serializers.ModelSerializer):
    cdate_loan = serializers.CharField(source='cdate')
    transaction_method_id = serializers.CharField()
    customer_id = serializers.CharField()
    loan_id = serializers.CharField(source='id')
    loan_status_code = serializers.CharField(source='loan_status_id')
    application_id = serializers.SerializerMethodField()
    available_limit = serializers.SerializerMethodField()
    first_limit = serializers.SerializerMethodField()

    class Meta(object):
        model = Loan
        fields = BonzaConstants.LOAN_PREDICTION_FIELDS

    def get_available_limit(self, instance):
        if instance.account:
            account_limt = instance.account.accountlimit_set.last()
            if account_limt:
                return str(account_limt.available_limit)
            return '0'
        return '0'

    def get_first_limit(self, instance):
        account = instance.account
        if account and account.accountlimit_set.last():
            account_limit_history = (
                account.accountlimit_set.last().accountlimithistory_set.order_by('cdate').first()
            )
            if account_limit_history:
                return account_limit_history.value_new
        return ''

    def get_application_id(self, instance):
        account = instance.account
        if account and account.last_application:
            return str(account.last_application.id)
        elif instance.application_id:
            return str(instance.application_id)
        return ''


class SeonFingerprintSerializer(serializers.ModelSerializer):
    customer_id = serializers.IntegerField(required=False, allow_null=True)
    trigger = serializers.CharField(required=True)
    ip_address = serializers.IPAddressField(required=False, allow_null=True)
    sdk_fingerprint_hash = serializers.CharField(required=False, allow_null=True)
    target_type = serializers.CharField(required=True)
    target_id = serializers.CharField(required=True)

    class Meta(object):
        model = SeonFingerprint


class JuicyScoreRequestSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)
    session_id = serializers.CharField(required=True)


class TrustGuardRequestSerializer(serializers.Serializer):
    EVENT_TYPE_CHOICES = [
        (TrustGuardConst.EventType.OPEN_APP[0], 'Open App'),
        (TrustGuardConst.EventType.LOGIN[0], 'Login'),
        (TrustGuardConst.EventType.TRANSACTION[0], 'Transaction'),
        (TrustGuardConst.EventType.APPLICATION[0], 'Application'),
    ]
    application_id = serializers.IntegerField(required=True)
    black_box = serializers.CharField(required=True)
    event_type = serializers.ChoiceField(required=False, choices=EVENT_TYPE_CHOICES)


class TrustGuardBlackboxRequestSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(required=True)
    black_box = serializers.CharField(required=True)
