from __future__ import unicode_literals

import logging
import re
from builtins import object

from django.contrib.auth import authenticate
from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework.serializers import (
    BooleanField,
    HyperlinkedModelSerializer,
    ModelSerializer,
)

from juloserver.apiv2.utils import application_have_facebook_data
from juloserver.cfs.constants import EtlJobType

from ..julo.formulas import compute_weekly_payment_installment
from ..julo.models import (
    AddressGeolocation,
    Application,
    ApplicationOriginal,
    AppVersionHistory,
    Collateral,
    Customer,
    Device,
    DeviceGeolocation,
    DeviceScrapedData,
    FacebookData,
    Image,
    Loan,
    Offer,
    PartnerAddress,
    PartnerReferral,
    Payment,
    PaymentMethod,
    ProductLine,
    ProductLookup,
    SiteMapJuloWeb,
    VoiceRecord,
)
from ..julo.product_lines import ProductLineCodes
from juloserver.apiv1.constants import UPLOAD_IMAGE_GENERAL_ERROR

logger = logging.getLogger(__name__)


class FacebookUserTokenSerializer(serializers.Serializer):

    facebook_token = serializers.CharField(label=_("Facebook User Access Token"))

    facebook_id = serializers.CharField(label=_("Facebook ID"))

    fullname = serializers.CharField(label=_("Full name"))

    # Optional parameters

    email = serializers.CharField(required=False, label=_("Email"))

    dob = serializers.CharField(required=False, label=_("Birthday"))

    gender = serializers.CharField(required=False, label=_("Gender"))

    # Test parameters

    verify = serializers.BooleanField(required=False, default=True)
    timestamped = serializers.BooleanField(required=False)

    def validate(self, attrs):

        user = authenticate(**attrs)

        if user is None:
            msg = _('Unable to log in with provided credentials.')
            raise serializers.ValidationError(msg)

        if not user.is_active:
            msg = _('User account is disabled.')
            raise serializers.ValidationError(msg)

        attrs['user'] = user
        return attrs


class CustomerExcludedMeta(object):
    """
    Custom Meta class that excludes the 'customer' field so that the API's
    OPTION request will not return the list of customer.
    """

    exclude = ('customer',)


class PartialAllowedModelSerializer(serializers.ModelSerializer):
    def __init__(self, instance=None, data=empty, **kwargs):

        # This allows sending partial data for PUT requests
        kwargs['partial'] = True
        super(PartialAllowedModelSerializer, self).__init__(instance=instance, data=data, **kwargs)


class ApplicationSerializer(PartialAllowedModelSerializer):

    device_id = serializers.IntegerField(read_only=True)
    status = serializers.ReadOnlyField()
    product_line_code = serializers.IntegerField(read_only=True)
    partner_name = serializers.ReadOnlyField()
    mantri_id = serializers.IntegerField(read_only=True)
    can_show_status = serializers.ReadOnlyField()
    loc_id = serializers.IntegerField(read_only=True)
    have_facebook_data = serializers.SerializerMethodField()
    customer_mother_maiden_name = serializers.ReadOnlyField()
    onboarding_id = serializers.IntegerField(read_only=True)

    class Meta(CustomerExcludedMeta):
        model = Application
        exclude = CustomerExcludedMeta.exclude + (
            'device',
            'application_status',
            'product_line',
            'partner',
            'mantri',
            'workflow',
            'line_of_credit',
            'customer_credit_limit',
            'account',
            'name_bank_validation',
            'merchant',
            'company',
            'onboarding',
        )

    def get_have_facebook_data(self, obj):
        return application_have_facebook_data(obj)

    def validate_is_document_submitted(self, value):
        """
        Validate this field can only be passed when:
        * creating an application and NOT setting the value to true
        * updating an application and setting the value to true
        * the application is in a certain state

        Note: validation should be moved to models layer
        """
        if self.instance is None:
            if value in BooleanField.TRUE_VALUES:
                raise serializers.ValidationError("Setting it to true is not allowed")
        else:
            if value in BooleanField.FALSE_VALUES:
                raise serializers.ValidationError("Setting it to false is not allowed")
            if not self.instance.can_mark_document_submitted():
                raise serializers.ValidationError("Application not in the right state")
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
            if value in BooleanField.TRUE_VALUES:
                raise serializers.ValidationError("Setting it to true is not allowed")
        else:
            if value in BooleanField.FALSE_VALUES:
                raise serializers.ValidationError("Setting it to false is not allowed")
            if not self.instance.can_mark_sphp_signed():
                raise serializers.ValidationError("Application not in the right state")
        return value


class ApplicationOriginalSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = ApplicationOriginal
        fields = "__all__"


class DeviceSerializer(serializers.ModelSerializer):
    class Meta(CustomerExcludedMeta):
        model = Device


class FacebookDataSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = FacebookData


class CustomerSerializer(serializers.ModelSerializer):
    is_loc_shown = serializers.ReadOnlyField()
    display_referral_code = serializers.SerializerMethodField()

    class Meta(object):
        model = Customer
        # we don't want to show all fields to client.
        exclude = (
            'is_email_verified',
            'country',
            'email_verification_key',
            'email_key_exp_date',
            'reset_password_key',
            'reset_password_exp_date',
            'user',
        )

    @staticmethod
    def get_display_referral_code(customer):
        from juloserver.referral.services import show_referral_code

        display = show_referral_code(customer)
        return display


class AddressGeolocationSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = AddressGeolocation


class DeviceGeolocationSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = DeviceGeolocation


class ProductLookupSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = ProductLookup


class OfferSerializer(PartialAllowedModelSerializer):
    interest_rate_monthly = serializers.ReadOnlyField()
    loan_amount_received = serializers.ReadOnlyField()
    cashback_total_pct = serializers.ReadOnlyField()
    cashback_potential = serializers.ReadOnlyField()
    product = ProductLookupSerializer(many=False, read_only=True)

    class Meta(object):
        model = Offer
        exclude = ('application',)


class SiteMapArticleSerializer(PartialAllowedModelSerializer):
    label_name = serializers.ReadOnlyField()
    label_url = serializers.ReadOnlyField()

    class Meta(object):
        model = SiteMapJuloWeb
        fields = ('id', 'label_name', 'label_url')


class VoiceRecordSerializer(ModelSerializer):
    class Meta(object):
        model = VoiceRecord
        exclude = ("tmp_path",)


class VoiceRecordHyperSerializer(HyperlinkedModelSerializer):
    class Meta(object):
        model = VoiceRecord
        fields = (
            'cdate',
            'udate',
            'status',
            'presigned_url',
        )


# "image" field is not included since we have url
class ImageSerializer(HyperlinkedModelSerializer):
    application_id = serializers.ReadOnlyField()

    class Meta(object):
        model = Image
        fields = (
            'id',
            'cdate',
            'udate',
            'image_source',
            'image_type',
            'url',
            'thumbnail_url',
            'image_status',
            'image_url_api',
            'thumbnail_url_api',
            'application_id',
        )


class ScrapedDataSerializer(HyperlinkedModelSerializer):
    class Meta(object):
        model = DeviceScrapedData
        fields = ('id', 'cdate', 'udate', 'url', 'file_type')


class UserTokenSerializer(serializers.Serializer):
    username = serializers.CharField(label=_("Username"))
    password1 = serializers.CharField(label=_("Password 1"))
    password2 = serializers.CharField(label=_("Password 2"))
    email = serializers.CharField(label=_("Email"))


class EmailSerializer(serializers.Serializer):
    email = serializers.CharField(required=True)


class EmailPhoneNumberSerializer(serializers.Serializer):
    email = serializers.CharField(default='None')
    phone_number = serializers.CharField(default='None')
    nik = serializers.CharField(required=False)
    username = serializers.CharField(required=False)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(label=_("Username"))
    password = serializers.CharField(label=_("Password"))
    email = serializers.CharField(label=_("Email"))


class LoanSerializer(PartialAllowedModelSerializer):
    status = serializers.ReadOnlyField()
    cashback_monthly = serializers.ReadOnlyField()
    late_fee_amount = serializers.ReadOnlyField()
    interest_rate_monthly = serializers.ReadOnlyField()
    loan_status_label = serializers.ReadOnlyField()

    class Meta(CustomerExcludedMeta):
        model = Loan
        exclude = CustomerExcludedMeta.exclude + ('loan_status',)

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


class PaymentSerializer(serializers.ModelSerializer):
    status = serializers.ReadOnlyField()
    payment_status_label = serializers.ReadOnlyField()
    original_due_amount = serializers.ReadOnlyField()
    installment_interest = serializers.ReadOnlyField(source='convert_interest_to_round_sum')

    class Meta(object):
        model = Payment


class PartnerAddressSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = PartnerAddress


class PartnerReferralSerializer(serializers.ModelSerializer):
    addresses = PartnerAddressSerializer(many=True, read_only=True)
    product = ProductLookupSerializer(read_only=True)

    class Meta(object):
        model = PartnerReferral


class AppVersionHistorySerializer(serializers.ModelSerializer):
    class Meta(object):
        model = AppVersionHistory


class ProductLineSerializer(serializers.ModelSerializer):
    weekly_installment = serializers.SerializerMethodField()
    origination_fee_rate = serializers.SerializerMethodField()

    class Meta(object):
        model = ProductLine

    def get_weekly_installment(self, obj):
        result = None
        if obj.product_line_code in ProductLineCodes.grabfood():
            result = []
            # products = obj.productlookup_set.all()
            products = obj.productlookup_set.filter(eligible_amount__isnull=False)
            for product in products:
                (
                    principal,
                    derived_interest,
                    installment_amount,
                ) = compute_weekly_payment_installment(
                    product.eligible_amount, product.eligible_duration, product.interest_rate
                )
                result.append(
                    {
                        'loan_duration': product.eligible_duration,
                        'loan_amount': product.eligible_amount,
                        'installment': installment_amount,
                    }
                )
        return result

    def get_origination_fee_rate(self, obj):
        origination_fee_rate = getattr(obj, 'origination_fee_rate', None)
        if obj.product_profile:
            return obj.product_profile.max_origination_fee

        return origination_fee_rate


class CollateralSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Collateral


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = PaymentMethod


class BankScrapingStartSerializer(serializers.Serializer):
    page_type = serializers.ChoiceField(choices=[EtlJobType.CFS], required=False)


class ImageListCreateViewV1Serializer(serializers.Serializer):
    upload = serializers.ImageField(error_messages={'invalid_image': UPLOAD_IMAGE_GENERAL_ERROR})
    image_type = serializers.CharField()
    image_source = serializers.CharField()

    SAFE_STRING_REGEX = re.compile(r'^[a-zA-Z0-9._-]+$')

    def validate_upload(self, value):
        if not value:
            return value

        ext = value.name.split('.')[-1]
        if ext not in ['jpg', 'jpeg', 'png']:
            raise serializers.ValidationError(UPLOAD_IMAGE_GENERAL_ERROR)

        return value

    def validate_image_type(self, value):
        if not self.SAFE_STRING_REGEX.match(value):
            raise serializers.ValidationError("Invalid image_type")
        return value

    def validate_image_source(self, value):
        if not self.SAFE_STRING_REGEX.match(value):
            raise serializers.ValidationError("Invalid image_source")
        return value
