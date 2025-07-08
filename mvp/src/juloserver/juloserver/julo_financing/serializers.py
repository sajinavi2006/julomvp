from rest_framework import serializers

from juloserver.julo_financing.services.core_services import (
    is_julo_financing_category_id_valid,
    is_julo_financing_product_id_valid,
)
from juloserver.julo_financing.services.core_services import is_province_supported


class CategoryIdSerializer(serializers.Serializer):
    category_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_category_id(self, value):
        if value is not None and not is_julo_financing_category_id_valid(value):
            raise serializers.ValidationError("Category not found")
        return value


class UserInfoSerializer(serializers.Serializer):
    full_name = serializers.CharField()
    phone_number = serializers.CharField()
    address = serializers.CharField()
    address_detail = serializers.CharField()
    available_limit = serializers.IntegerField()
    province_name = serializers.CharField()


class SaleTagSerializer(serializers.Serializer):
    image_url = serializers.CharField()
    primary = serializers.BooleanField()
    tag_name = serializers.CharField()


class ProductItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    price = serializers.IntegerField()
    display_installment_price = serializers.CharField()
    thumbnail_url = serializers.URLField()
    sale_tags = SaleTagSerializer(many=True, required=False)


class ProductListSerializer(serializers.Serializer):
    user_info = UserInfoSerializer()
    products = ProductItemSerializer(many=True)


class ProductDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    price = serializers.IntegerField()
    display_installment_price = serializers.CharField()
    description = serializers.CharField()
    images = serializers.ListField(child=serializers.URLField())
    sale_tags = SaleTagSerializer(many=True, required=False)


class JFinancingLoanCalculationSerializer(serializers.Serializer):
    j_financing_product_id = serializers.IntegerField(required=True)
    loan_amount_request = serializers.IntegerField(required=True, min_value=0)
    province_name = serializers.CharField(required=True)

    def validate_j_financing_product_id(self, j_financing_product_id):
        if not is_julo_financing_product_id_valid(j_financing_product_id):
            raise serializers.ValidationError("Product not found")

        return j_financing_product_id

    def validate_province_name(self, province_name):
        if not is_province_supported(province_name):
            raise serializers.ValidationError("Province not supported")

        return province_name
