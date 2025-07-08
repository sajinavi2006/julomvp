from rest_framework import serializers

from juloserver.julo.models import Application


class ReapplyApplicationSerializer(serializers.ModelSerializer):
    status = serializers.ReadOnlyField()

    class Meta(object):
        model = Application
        fields = (
            'mobile_phone_1',
            'fullname',
            'dob',
            'gender',
            'ktp',
            'email',
            'id',
            'marital_status',
            'spouse_name',
            'spouse_mobile_phone',
            'close_kin_name',
            'close_kin_mobile_phone',
            'bank_name',
            'bank_account_number',
            'address_kabupaten',
            'address_kecamatan',
            'address_kelurahan',
            'address_kodepos',
            'address_provinsi',
            'address_street_num',
            'job_description',
            'job_industry',
            'job_start',
            'job_type',
            'payday',
            'company_name',
            'company_phone_number',
            'monthly_expenses',
            'monthly_income',
            'total_current_debt',
            'status',
            'birth_place',
            'last_education',
            'home_status',
            'occupied_since',
            'dependent',
            'monthly_housing_cost'
        )


class ReapplySerializer(serializers.Serializer):
    mother_maiden_name = serializers.CharField(required=False)
    app_version = serializers.CharField(required=False)
    device_id = serializers.CharField(required=False)


class JuloStarterReapplySerializer(ReapplySerializer):
    pass
