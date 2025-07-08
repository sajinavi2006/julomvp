from builtins import object
from rest_framework import serializers
from rest_framework.serializers import HyperlinkedModelSerializer

from ..apiv1.serializers import PartialAllowedModelSerializer
from ..julo.statuses import ApplicationStatusCodes
from ..apiv2.utils import custom_error_messages_for_required
from ..apiv2.services import get_latest_app_version

from ..julo.utils import verify_nik
from ..julo.models import Customer, Loan, Application, CreditScore, Image, ProductLine, Offer, PartnerPurchaseItem, PaymentMethod


class RegisterSerializer(serializers.Serializer):
    # App Params
    app_version = serializers.CharField(required=False)

    # registration params
    ktp = serializers.CharField(required=True, error_messages=custom_error_messages_for_required("Username"))

    # Device params
    gcm_reg_id = serializers.CharField(required=True,
                                       error_messages=custom_error_messages_for_required("gcm_reg_id"))
    android_id = serializers.CharField(required=True,
                                       error_messages=custom_error_messages_for_required("android_id"))
    imei = serializers.CharField(required=False, allow_blank=True)

    # Geolocation params
    latitude = serializers.FloatField(required=True,
                                      error_messages=custom_error_messages_for_required("latitude", type="Float"))
    longitude = serializers.FloatField(required=True,
                                       error_messages=custom_error_messages_for_required("longitude", type="Float"))

    # emial
    email = serializers.CharField(required=False)

    # AppsFlyer
    appsflyer_device_id = serializers.CharField(required=False)
    advertising_id = serializers.CharField(required=False)

    def validate(self, data):
        if not data.get('app_version'):
            data['app_version'] = get_latest_app_version()

        if not verify_nik(data.get('ktp')):
            raise serializers.ValidationError({"username": "NIK Tidak Valid"})

        if not data.get('dependent'):
            data['dependent'] = 0

        if data.get('email'):
            existing = Customer.objects.filter(email__iexact=data['email'])
            if existing:
                raise serializers.ValidationError("Email already registered")

        return data


class AcceptActivationSerializer(serializers.Serializer):
    is_sphp_signed = serializers.BooleanField(required=True)


class CustomerSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Customer
        # we don't want to show all fields to client.
        exclude = (
            'id', 'is_email_verified', 'country', 'email_verification_key', 'advertising_id', 'can_reapply_date',
            'email_key_exp_date', 'reset_password_key', 'is_phone_verified', 'appsflyer_device_id',
            'reset_password_exp_date', 'user', 'is_review_submitted', 'disabled_reapply_date',
            'potential_skip_pv_dv', 'google_access_token', 'google_refresh_token'
        )


class LoanSerializer(PartialAllowedModelSerializer):
    cashback_monthly = serializers.ReadOnlyField()
    late_fee_amount = serializers.ReadOnlyField()
    interest_rate_monthly = serializers.ReadOnlyField()
    loan_status_label = serializers.ReadOnlyField()

    class Meta(object):
        model = Loan
        fields = ('loan_status_label', 'loan_amount', 'cdate', 'loan_duration', 'first_installment_amount',
                  'installment_amount', 'cycle_day', 'late_fee_amount', 'interest_rate_monthly', 'cashback_monthly')

    def validate(self, data):
        """
        Check that only cycle_day_request can be updated.
        """
        editable_field = 'cycle_day_requested'
        error_message = "Only %s can be updated" % editable_field
        if len(data) != 1:
            raise serializers.ValidationError(error_message)
        if editable_field not in data:
            raise serializers.ValidationError(error_message)
        return data


class ApplicationSerializer(PartialAllowedModelSerializer):

    status = serializers.SerializerMethodField()
    partner_name = serializers.ReadOnlyField()

    class Meta(object):
        model = Application
        fields = ('application_xid', 'ktp', 'status', 'partner_name', 'dob', 'gender', 'mobile_phone_1',
                  'has_whatsapp_1', 'app_version')

    def get_status(self, app):
        from .services import get_application_status
        return get_application_status(app)

    def validate_is_document_submitted(self, value):
        """
        Validate this field can only be passed when:
        * creating an application and NOT setting the value to true
        * updating an application and setting the value to true
        * the application is in a certain state

        Note: validation should be moved to models layer
        """
        if self.instance is None:
            if value in serializers.BooleanField.TRUE_VALUES:
                raise serializers.ValidationError(
                    "Setting it to true is not allowed")
        else:
            if value in serializers.BooleanField.FALSE_VALUES:
                raise serializers.ValidationError(
                    "Setting it to false is not allowed")
            if not self.instance.can_mark_document_submitted():
                raise serializers.ValidationError(
                    "Application not in the right state")
        return value

    def validate_is_sphp_signed(self, value):
        """
        Validate this field can only be passed when:
        * creating an application and NOT setting the value to true
        * updating an application and setting the value to true
        * the application is in a certain state

        Note: validation should be moved to models layer
        """
        if self.instance is None:
            if value in serializers.BooleanField.TRUE_VALUES:
                raise serializers.ValidationError(
                    "Setting it to true is not allowed")
        else:
            if value in serializers.BooleanField.FALSE_VALUES:
                raise serializers.ValidationError(
                    "Setting it to false is not allowed")
            if not self.instance.can_mark_sphp_signed():
                raise serializers.ValidationError(
                    "Application not in the right state")
        return value


class ApplicationStatusSerializer(PartialAllowedModelSerializer):
    score_val = None
    message_val = None
    status = serializers.SerializerMethodField()
    credit_score = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()
    loan_status = serializers.SerializerMethodField()
    can_reapply = serializers.SerializerMethodField()
    can_reapply_date = serializers.SerializerMethodField()

    class Meta(object):
        model = Application
        fields = (
            'application_xid',
            'status',
            'app_version',
            'credit_score',
            'message',
            'loan_status',
            'can_reapply',
            'can_reapply_date')

    def get_credit_score(self, app):
        from juloserver.sdk.services import get_application_rejection_message
        from juloserver.sdk.services import get_credit_score_partner
        credit_score = get_credit_score_partner(app.id)
        if credit_score:
            self.score_val = credit_score.score
            self.message_val = get_application_rejection_message(credit_score.score, app)
            return credit_score.score

    def get_message(self, app):
        return self.message_val

    def get_loan_status(self, app):
        try:
            return app.loan.loan_status_label
        except Exception:
            return None

    def get_can_reapply(self, app):
        customer = app.customer
        return customer.can_reapply

    def get_can_reapply_date(self, app):
        can_reapply_date = app.customer.can_reapply_date
        can_reapply = app.customer.can_reapply
        if can_reapply == False:
            return can_reapply_date if can_reapply_date else 0
        else:
            return None

    def get_status(self, app):
        from .services import get_application_status
        return get_application_status(app)


class ApplicationPartnerUpdateSerializer(serializers.ModelSerializer):
    def validate(self, data):
        if data.get('payday', 1) > 28:
            data['payday'] = 28

        if not data.get('app_version'):
            data['app_version'] = get_latest_app_version()

        if not data.get('income_1'):
            data['income_1'] = 0

        if not data.get('income_2'):
            data['income_2'] = 0

        if not data.get('income_3'):
            data['income_3'] = 0

        if not data.get('monthly_income'):
            data['monthly_income'] = 0

        return data

    class Meta(object):
        model = Application
        exclude = ('id', 'application_status', 'device', 'product_line', 'partner', 'mantri', 'workflow',
                   'line_of_credit', 'customer', 'customer_credit_limit', 'merchant')

    def validate_email(self, value):
        return value.strip().lower()


class CreditScoreSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = CreditScore
        fields = ('score', 'message', 'credit_limit')


# "image" field is not included since we have url
class ImageSerializer(HyperlinkedModelSerializer):
    class Meta(object):
        model = Image
        fields = (
            'id', 'cdate', 'udate', 'image_source',
            'image_type', 'url', 'thumbnail_url',
            'image_status', 'image_url_api', 'thumbnail_url_api'
        )


class ProductLineSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = ProductLine
        exclude = ('handler', 'default_workflow', 'product_profile')


class OfferSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Offer
        exclude = ('application', 'id', 'product', 'offer_number')


class PartnerPurchaseItemSerializer(serializers.ModelSerializer):
    def create(self, validated_data):
        if not validated_data.get('product_code'):
            return PartnerPurchaseItem.objects.create(**validated_data)

    class Meta(object):
        model = PartnerPurchaseItem
        exclude = ('id', 'device_trade', )


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = PaymentMethod
        exclude = ('cdate', 'udate', 'id', 'line_of_credit', 'loan', 'is_preferred')


class SdkLogSerializer(serializers.Serializer):
    application_xid = serializers.CharField(required=True)
    app_version = serializers.CharField(required=True)
    nav_log_ts = serializers.CharField(required=True)
    action = serializers.CharField(required=True)
    device_model_name = serializers.CharField(required=True)
