from rest_framework import serializers

from juloserver.landing_page_api.constants import CareerExtraDataConst
from juloserver.landing_page_api.models import FAQItem, LandingPageCareer, LandingPageSection
from juloserver.customer_module.models import WebAccountDeletionRequest
from juloserver.employee_financing.serializers import verify_nik

class ParentFAQItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQItem
        fields = ['id', 'title', 'type']


class FAQItemSerializer(serializers.ModelSerializer):
    parent = ParentFAQItemSerializer(many=False)

    class Meta:
        model = FAQItem
        fields = ['id', 'title', 'parent', 'slug', 'rich_text',
                  'visible', 'type', 'order_priority']


class LandingPageCareerListSerializer(serializers.ModelSerializer):
    type = serializers.ReadOnlyField()
    vacancy = serializers.ReadOnlyField()
    experience = serializers.ReadOnlyField()
    location = serializers.ReadOnlyField()
    salary = serializers.ReadOnlyField()

    class Meta:
        model = LandingPageCareer
        fields = [
                     'id', 'title', 'category', 'skills', 'published_date', 'is_active', 'cdate', 'udate'
                 ] + LandingPageCareer.extra_data_fields


class LandingPageCareerSerializer(LandingPageCareerListSerializer):
    class Meta:
        model = LandingPageCareer
        fields = [
                     'id', 'title', 'category', 'skills', 'published_date', 'is_active', 'cdate', 'udate',
                     'rich_text'
                 ] + LandingPageCareer.extra_data_fields


class LandingPageSectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LandingPageSection
        fields = ['id', 'name', 'rich_text', 'cdate', 'udate']

class DeleteAccountRequestSerializer(serializers.Serializer):

    full_name = serializers.CharField(required=True, max_length=100)
    nik = serializers.CharField(required=True)
    phone_number = serializers.CharField(required=True)
    email_address = serializers.EmailField(required=True)
    reason = serializers.CharField(required=True)
    details = serializers.CharField(required=True, min_length=40, max_length=500)
    image_ktp = serializers.FileField(required=True)
    image_selfie = serializers.FileField(required=True)

    def validate_nik(self, value):
        if not value.isnumeric():
            raise serializers.ValidationError("invalid nik")

        if not verify_nik(value):
            raise serializers.ValidationError("invalid nik")

    def validate_phone_number(self, value):
        max_length = 15
        if value[0] == '+':
            max_length = 16
        
        if len(value) > max_length:
            raise serializers.ValidationError("invalid phone number") 
        
        return value

    def validate_reason(self, value):
        if value not in [enum[0] for enum in WebAccountDeletionRequest.reason_enums]:
            raise serializers.ValidationError("invalid enum value")

        return value

    def validate_image_ktp(self, value):
        if value.size > 5000000:
            raise serializers.ValidationError("image size too large")
        
        ext = value.name.split('.')[-1]
        if ext not in ['jpg', 'jpeg', 'png', 'pdf']:
            raise serializers.ValidationError("invalid file extension")

        return value
    
    def validate_image_selfie(self, value):
        if value.size > 5000000:
            raise serializers.ValidationError("image size too large")
        
        ext = value.name.split('.')[-1]
        if ext not in ['jpg', 'jpeg', 'png', 'pdf']:
            raise serializers.ValidationError("invalid file extension")

        return value


class ConsentWithdrawalRequestSerializer(DeleteAccountRequestSerializer):
    pass
