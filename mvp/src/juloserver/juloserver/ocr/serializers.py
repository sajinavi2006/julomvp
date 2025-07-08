from __future__ import unicode_literals
import re
from django.core.exceptions import ValidationError
from rest_framework import serializers

from juloserver.face_recognition.serializers import ImageMetadataSerializer
from juloserver.liveness_detection.serializers import validate_file_size
from juloserver.ocr.constants import OCRFileUploadConst
from juloserver.application_form.models import OcrKtpResult
from juloserver.julolog.julolog import JuloLog
from juloserver.application_form.constants import SimilarityTextConst
from juloserver.apiv3.models import ProvinceLookup, CityLookup, DistrictLookup, SubDistrictLookup

logger = JuloLog(__name__)


def validate_file_name(value):
    filename = value.name
    allowed_extensions = [ext.lstrip('.') for ext in OCRFileUploadConst.ALLOWED_IMAGE_EXTENSIONS]

    if not re.match(OCRFileUploadConst.ALLOWED_CHARACTER_PATTERN, filename):
        raise ValidationError("Filename contains invalid characters")

    ext = filename.split('.')[-1].lower()
    if ext not in allowed_extensions:
        raise ValidationError("Unsupported file type: {}".format(ext))

    return value


class OpenCVDataSerializer(serializers.Serializer):
    is_blurry = serializers.BooleanField()
    is_dark = serializers.BooleanField()
    is_glary = serializers.BooleanField()


class KTPOCRResultSerializer(ImageMetadataSerializer):
    image = serializers.ImageField(
        required=True,
        validators=[validate_file_name],
    )
    raw_image = serializers.ImageField(
        required=False,
        validators=[validate_file_name],
    )
    retries = serializers.IntegerField(required=True)


class NewKTPOCRResultSerializer(ImageMetadataSerializer):
    image = serializers.ImageField(
        required=True,
        validators=[validate_file_size, validate_file_name],
    )
    raw_image = serializers.ImageField(
        required=True,
        validators=[validate_file_size, validate_file_name],
    )


class KTPOCRExperimentResultSerializer(serializers.Serializer):

    value = serializers.CharField(required=True)
    hash_value = serializers.CharField(required=True)


class KTPOCRExperimentSerializer(serializers.Serializer):

    key = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    active = serializers.BooleanField()


class KTPOCRExperimentDataSerializer(serializers.Serializer):

    experiment = KTPOCRExperimentSerializer()
    result = KTPOCRExperimentResultSerializer()


class KtpOCRResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = OcrKtpResult
        fields = (
            'address',
            'gender',
            'district',
            'nik',
            'fullname',
            'province',
            'place_of_birth',
            'city',
            'date_of_birth',
            'rt_rw',
            'administrative_village',
            'marital_status',
            'religion',
            'blood_group',
            'job',
            'nationality',
            'valid_until',
        )

    def similarity_process(
        self, threshold, list_values, value_check, process_name, return_original=True
    ):

        from juloserver.ocr.services import similarity_value

        new_value = similarity_value(
            list_values=list_values,
            value_check=value_check,
            threshold=threshold,
            return_original=return_original,
        )
        logger.info(
            {
                'message': 'Similarity process {}'.format(process_name),
                'origin_value': value_check,
                'new_value': new_value,
                'threshold': threshold,
            }
        )

        return new_value

    def clean_data(self, data):
        from juloserver.ocr.services import get_config_similarity
        nik_regex = re.compile(r'^[0-9]{16}$')
        raw_data = {key: (value if value != '' else None) for key, value in data.items()}
        is_active_feature, parameters = get_config_similarity()

        field_mapping = {
            "administrative_village": "sub_district",
            "district": "district",
            "city": "city",
            "province": "province",
        }

        if raw_data.get('nik') and not nik_regex.fullmatch(raw_data['nik']):
            logger.warning(
                {'message': '[NIK] set as null for OCR response', 'origin_value': raw_data['nik']}
            )
            raw_data['nik'] = None

        if not is_active_feature:
            return raw_data

        skip_smaller_areas = False
        areas = {'province', 'city', 'district', 'administrative_village'}

        def process_if_not_null(
            field, lookup_model, parent_field=None, parent_value=None, key_threshold=None
        ):
            nonlocal skip_smaller_areas, areas

            # Convert empty string to None
            if raw_data.get(field) == '':
                raw_data[field] = None

            # Set all smaller area to none if skip_smaller_areas = True
            if skip_smaller_areas:
                for small_field in areas:
                    raw_data[small_field] = None
                return False

            # If the field is missing or None, trigger skipping logic
            if not raw_data.get(field):
                skip_smaller_areas = True
                for small_field in areas:
                    raw_data[small_field] = None
                return False

            # Process area
            if not self.process_area(
                raw_data,
                field,
                lookup_model,
                field_mapping,
                parameters,
                parent_field=parent_field,
                parent_value=parent_value,
                key_threshold=key_threshold,
            ):
                skip_smaller_areas = True
                raw_data[field] = None
                return True

            # Mark the field as processed
            areas.discard(field)
            return True

        # Gender processing logic
        if 'gender' in raw_data and raw_data['gender']:
            threshold = parameters.get(SimilarityTextConst.KEY_THRESHOLD_GENDER)
            if threshold:
                raw_data['gender'] = self.similarity_process(
                    threshold,
                    SimilarityTextConst.GENDER_LIST_OCR,
                    str(raw_data['gender']).upper(),
                    'gender',
                )

        # Process areas sequentially
        if process_if_not_null(
            'province', ProvinceLookup, key_threshold=SimilarityTextConst.KEY_THRESHOLD_PROVINCE
        ):
            if process_if_not_null(
                'city',
                CityLookup,
                'province__province',
                raw_data.get('province'),
                SimilarityTextConst.KEY_THRESHOLD_CITY,
            ):
                if process_if_not_null(
                    'district',
                    DistrictLookup,
                    'city__city',
                    raw_data.get('city'),
                    SimilarityTextConst.KEY_THRESHOLD_DISTRICT,
                ):
                    process_if_not_null(
                        'administrative_village',
                        SubDistrictLookup,
                        'district__district',
                        raw_data.get('district'),
                        SimilarityTextConst.KEY_THRESHOLD_VILLAGE,
                    )

        return raw_data

    def process_area(
        self,
        raw_data,
        ocr_field_name,
        lookup_model,
        field_mapping,
        parameters,
        parent_field=None,
        parent_value=None,
        key_threshold=None,
    ):
        internal_field_name = field_mapping.get(ocr_field_name, ocr_field_name)
        threshold = parameters.get(key_threshold)
        if not threshold:
            return False

        value = raw_data.get(ocr_field_name, '').upper()
        queryset = lookup_model.objects.filter(is_active=True)
        if parent_field and parent_value:
            queryset = queryset.filter(
                **{"{}__icontains".format(parent_field): parent_value.upper()}
            )
        area_list = list(queryset.values_list(internal_field_name, flat=True))
        area_list = [item.upper() for item in area_list]

        new_value = self.similarity_process(
            threshold, area_list, value, ocr_field_name, return_original=False
        )
        raw_data[ocr_field_name] = new_value
        if new_value:
            return True

        logger.info(
            {
                'action': 'process_area',
                'message': '{} not found'.format(ocr_field_name),
                'value': value,
                'address': raw_data.get('address'),
            }
        )

        return False

    def to_representation(self, instance):
        raw_data = super().to_representation(instance)
        data = self.clean_data(raw_data)

        return data
