import time
import base64

from rest_framework import serializers
from django.conf import settings
from juloserver.julo.utils import get_file_from_oss
from juloserver.julo.models import Image
from juloserver.face_recognition.constants import ImageType


# AsliRi Dukcapil
class DukcapilApplicationSerializer(serializers.Serializer):
    trx_id = serializers.SerializerMethodField()
    name = serializers.CharField(source='fullname')
    birthdate = serializers.SerializerMethodField()
    birthplace = serializers.CharField(source='birth_place')
    files_photo = serializers.SerializerMethodField()

    def validate_nik(self, value):
        from juloserver.pii_vault.constants import PiiSource
        from juloserver.partnership.utils import partnership_detokenize_sync_object_model
        from juloserver.julo.product_lines import ProductLineCodes

        application = self.context.get('application')
        if application.product_line_code == ProductLineCodes.AXIATA_WEB:
            partnership_customer_data = application.partnership_customer_data
            customer_xid = application.customer.customer_xid
            # Detokenize partnership customer data
            detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
                PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                partnership_customer_data,
                customer_xid,
                ['nik'],
            )
            value = detokenize_partnership_customer_data.nik

        return value

    def get_trx_id(self, object):
        return str(object.id) + 'ts' + str(int(time.time()))

    def get_birthdate(self, object):
        if object.dob:
            return object.dob.strftime('%d-%m-%Y')
        else:
            return None

    def get_files_photo(self, object):
        image = Image.objects.filter(
            image_source=object.id, image_type=ImageType.CROP_SELFIE
        ).last()
        if not image:
            return None

        image_file = get_file_from_oss(settings.OSS_MEDIA_BUCKET, image.url)
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')

        return base64_image

    def get_address(self, object):
        return object.complete_addresses


# Official Dukcapil
class DukcapilOfficialVerifySerializer(serializers.Serializer):
    IP_USER = serializers.SerializerMethodField()
    NIK = serializers.CharField(source='ktp')
    NAMA_LGKP = serializers.CharField(source='fullname')
    ALAMAT = serializers.SerializerMethodField()
    TMPT_LHR = serializers.CharField(source='birth_place')
    TGL_LHR = serializers.SerializerMethodField()
    JENIS_KLMIN = serializers.SerializerMethodField()
    STATUS_KAWIN = serializers.SerializerMethodField()
    TRESHOLD = serializers.SerializerMethodField()
    JENIS_PKRJN = serializers.CharField(required=False, source='job_type')
    KAB_NAME = serializers.CharField(required=False, source='address_kabupaten')
    KEC_NAME = serializers.CharField(required=False, source='address_kecamatan')
    KEL_NAME = serializers.CharField(required=False, source='address_kelurahan')
    PROP_NAME = serializers.CharField(required=False, source='address_provinsi')
    NO_KAB = serializers.CharField(required=False)
    NO_KEC = serializers.CharField(required=False)
    NO_KEL = serializers.CharField(required=False)
    NO_PROP = serializers.CharField(required=False)
    NO_RT = serializers.CharField(required=False)
    NO_RW = serializers.CharField(required=False)
    PDDK_AKH = serializers.CharField(required=False)
    NO_KK = serializers.CharField(required=False)

    def get_IP_USER(self, object):
        return '192.168.0.1'

    def get_ALAMAT(self, object):
        return object.address_street_num

    def get_TGL_LHR(self, object):
        if object.dob:
            return object.dob.strftime('%d-%m-%Y')
        else:
            return None

    def get_JENIS_KLMIN(self, object):
        if object.gender_mintos == 'M':
            return 'Laki-Laki'
        else:
            return 'Perempuan'

    def get_STATUS_KAWIN(self, object):
        if object.marital_status == 'Lajang':
            return 'BELUM KAWIN'
        else:
            return 'KAWIN'

    def get_TRESHOLD(self, object):
        return '90'


class DukcapilOfficialStoreSerializer(serializers.Serializer):
    NIK = serializers.CharField(source='ktp')
    param = serializers.SerializerMethodField()

    def get_param(self, obj):
        return [
            {
                'CUSTOMER_ID': obj.customer.generated_customer_xid,
            }
        ]


class BureauApplicationPhoneSerializer(serializers.Serializer):
    phoneNumber = serializers.SerializerMethodField()
    countryCode = serializers.SerializerMethodField()

    def get_phoneNumber(self, obj):
        phone = obj.mobile_phone_1
        if phone:
            if phone.startswith('62'):
                return phone
            if phone.startswith('0'):
                return '62' + phone[1:]
            if phone.startswith('+62'):
                return phone[1:]
            return '62' + phone
        return phone

    def get_countryCode(self, obj):
        return 'ID'


class BureauApplicationEmailSerializer(serializers.Serializer):
    email = serializers.CharField()


class BureauApplicationMobileIntelligenceSerializer(serializers.Serializer):
    phoneNumber = serializers.SerializerMethodField()
    email = serializers.CharField()
    firstName = serializers.SerializerMethodField()
    lastName = serializers.SerializerMethodField()
    dateOfBirth = serializers.CharField(source='dob')
    address = serializers.SerializerMethodField()
    city = serializers.CharField(source='address_kabupaten')
    country = serializers.SerializerMethodField()
    postalCode = serializers.CharField(source='address_kodepos')
    state = serializers.CharField(source='address_provinsi')

    def get_phoneNumber(self, obj):
        phone = obj.mobile_phone_1
        if phone:
            if phone.startswith('62'):
                return phone
            if phone.startswith('0'):
                return '62' + phone[1:]
            if phone.startswith('+62'):
                return phone[1:]
            return '62' + phone
        return phone

    def get_firstName(self, obj):
        first_name, last_name = obj.split_name
        return first_name

    def get_lastName(self, obj):
        first_name, last_name = obj.split_name
        return last_name

    def get_address(self, obj):
        return obj.full_address

    def get_country(self, obj):
        return 'Indonesia'


class BureauSessionFetchSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    device_scan_success = serializers.BooleanField()
    application_id = serializers.CharField()
