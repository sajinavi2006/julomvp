from rest_framework import serializers


class RegionSerializer(serializers.Serializer):
    province = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    district = serializers.SerializerMethodField()
    sub_district = serializers.SerializerMethodField()
    zipcode = serializers.SerializerMethodField()

    def get_province(self, obj):
        return str(obj['province'] or '')

    def get_city(self, obj):
        return str(obj['city'] or '')

    def get_district(self, obj):
        return str(obj['district'] or '')

    def get_sub_district(self, obj):
        return str(obj['sub_district'] or '')

    def get_zipcode(self, obj):
        return str(obj['zipcode'] or '')
