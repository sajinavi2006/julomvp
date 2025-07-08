from rest_framework import serializers
from juloserver.rating.models import RatingFormTypeEnum, RatingSourceEnum
from typing import Union


class RatingSerializer(serializers.Serializer):
    rating = serializers.IntegerField(required=False, default=None, allow_null=True)
    description = serializers.CharField(required=False, default=None, allow_null=True)
    csat_score = serializers.IntegerField(required=False, default=None, allow_null=True)
    csat_detail = serializers.CharField(required=False, default=None, allow_null=True)
    source = serializers.IntegerField(required=False, default=None, allow_null=True)
    rating_form = serializers.IntegerField(required=False, default=None, allow_null=True)

    def validate(self, data):
        serializer = self.get_serializer(data)
        serializer.is_valid(raise_exception=True)

        return data

    def get_serializer(self, data):
        rating_form = RatingFormTypeEnum(data.get('rating_form'))

        if rating_form == RatingFormTypeEnum.type_b:
            return RatingSerializerTypeB(data=data)

        if rating_form == RatingFormTypeEnum.type_c:
            return RatingSerializerTypeC(data=data)

        if rating_form == RatingFormTypeEnum.type_d:
            return RatingSerializerTypeD(data=data)

        return RatingSerializerDefault(data=data)

    def validate_rating_form(self, value):
        if value not in [enum.value for enum in RatingFormTypeEnum]:
            raise serializers.ValidationError('Rating form tidak valid')

        return value

    def validate_source(self, value):
        if value not in [enum.value for enum in RatingSourceEnum]:
            raise serializers.ValidationError('Rating source tidak valid')

        return value


class RatingSerializerDefault(serializers.Serializer):
    rating = serializers.IntegerField(required=False, default=None, allow_null=True)
    description = serializers.CharField(required=False, default=None, allow_null=True)
    csat_score = serializers.IntegerField(required=False, default=None, allow_null=True)
    csat_detail = serializers.CharField(required=False, default=None, allow_null=True)
    source = serializers.IntegerField(required=False, default=None, allow_null=True)
    rating_form = serializers.IntegerField(required=False, default=None, allow_null=True)

    def validate_rating(self, value):
        if value is None:
            raise serializers.ValidationError('Rating tidak boleh kosong')

        if value < 1 or value > 5:
            raise serializers.ValidationError('Rating harus diantara 1 sampai 5')

        return value

    def validate_description(self, value):
        if value is None:
            return None

        desc = value.strip()
        if len(desc) > 160:
            raise serializers.ValidationError('Panjang deskripsi maksimal 160 karakter')

        return value

    def validate_csat_score(self, value):
        if value:
            raise serializers.ValidationError('Rating csat harus kosong')

        return value

    def validate_csat_detail(self, value):
        if value:
            raise serializers.ValidationError('Deskripsi csat harus kosong')

        return value


class RatingSerializerTypeB(serializers.Serializer):
    rating = serializers.IntegerField(required=False, default=None, allow_null=True)
    description = serializers.CharField(required=False, default=None, allow_null=True)
    csat_score = serializers.IntegerField(required=False, default=None, allow_null=True)
    csat_detail = serializers.CharField(required=False, default=None, allow_null=True)
    source = serializers.IntegerField(required=False, default=None, allow_null=True)
    rating_form = serializers.IntegerField(required=False, default=None, allow_null=True)

    def validate(self, data):
        errors = {}

        if data.get('csat_score') == 5:
            errors['rating'] = self._validate_rating(data.get('rating'))
            errors['description'] = self._validate_description(data.get('description'))
        else:
            errors['rating'] = self._validate_no_rating(data.get('rating'))
            errors['description'] = self._validate_no_description(data.get('description'))

        errors = {key: value for key, value in errors.items() if value is not None}
        if errors:
            raise serializers.ValidationError(errors)

        return data

    def _validate_no_rating(self, rating) -> Union[str, None]:
        if rating:
            return 'Rating harus kosong'

        return None

    def _validate_no_description(self, description) -> Union[str, None]:
        if description:
            return 'Deskripsi harus kosong'

        return None

    def _validate_rating(self, value) -> Union[str, None]:
        if value is None:
            return 'Rating tidak boleh kosong'

        if value < 1 or value > 5:
            return 'Rating harus diantara 1 sampai 5'

        return None

    def _validate_description(self, value) -> Union[str, None]:
        if value is None:
            return None

        desc = value.strip()
        if len(desc) > 160:
            return 'Panjang deskripsi maksimal 160 karakter'

        return None

    def validate_csat_score(self, value):
        if value is None:
            return serializers.ValidationError('Rating csat tidak boleh kosong')

        if value < 1 or value > 5:
            raise serializers.ValidationError('Rating csat harus diantara 1 sampai 5')

        return value

    def validate_csat_detail(self, value):
        if value is None:
            return None

        desc = value.strip()
        if len(desc) > 160:
            raise serializers.ValidationError('Panjang deskripsi maksimal 160 karakter')

        return value


class RatingSerializerTypeC(serializers.Serializer):
    rating = serializers.IntegerField(required=False, default=None, allow_null=True)
    description = serializers.CharField(required=False, default=None, allow_null=True)
    csat_score = serializers.IntegerField(required=False, default=None, allow_null=True)
    csat_detail = serializers.CharField(required=False, default=None, allow_null=True)
    source = serializers.IntegerField(required=False, default=None, allow_null=True)
    rating_form = serializers.IntegerField(required=False, default=None, allow_null=True)

    def validate_rating(self, value):
        if value is None:
            raise serializers.ValidationError('Rating tidak boleh kosong')

        if value < 1 or value > 5:
            raise serializers.ValidationError('Rating harus diantara 1 sampai 5')

        return value

    def validate_description(self, value):
        if value is None:
            return None

        desc = value.strip()
        if len(desc) > 160:
            raise serializers.ValidationError('Panjang deskripsi maksimal 160 karakter')

        return value

    def validate_csat_score(self, value):
        if value:
            raise serializers.ValidationError('Rating csat harus kosong')

        return value

    def validate_csat_detail(self, value):
        if value:
            raise serializers.ValidationError('Deskripsi csat harus kosong')

        return value


class RatingSerializerTypeD(serializers.Serializer):
    rating = serializers.IntegerField(required=False, default=None, allow_null=True)
    description = serializers.CharField(required=False, default=None, allow_null=True)
    csat_score = serializers.IntegerField(required=False, default=None, allow_null=True)
    csat_detail = serializers.CharField(required=False, default=None, allow_null=True)
    source = serializers.IntegerField(required=False, default=None, allow_null=True)
    rating_form = serializers.IntegerField(required=False, default=None, allow_null=True)
    source = serializers.IntegerField(required=False, default=None, allow_null=True)

    def validate(self, data):
        errors = {}

        if data.get('csat_score') < 5:
            errors['csat_detail'] = self._validate_csat_detail(data.get('csat_detail'))
        else:
            errors['csat_detail'] = self._validate_no_csat_detail(data.get('csat_detail'))

        errors = {key: value for key, value in errors.items() if value is not None}
        if errors:
            raise serializers.ValidationError(errors)

        return data

    def validate_csat_score(self, value):
        if value is None:
            raise serializers.ValidationError('Rating csat tidak boleh kosong')

        if value < 1 or value > 5:
            raise serializers.ValidationError('Rating csat harus diantara 1 sampai 5')

        return value

    def validate_description(self, value):
        if value:
            raise serializers.ValidationError('Deskripsi harus kosong')

        return value

    def validate_rating(self, value):
        if value:
            raise serializers.ValidationError('Rating harus kosong')

        return value

    def _validate_csat_detail(self, value) -> Union[str, None]:
        if value is None:
            return None

        desc = value.strip()
        if len(desc) > 160:
            raise serializers.ValidationError('Panjang deskripsi maksimal 160 karakter')

        return None

    def _validate_no_csat_detail(self, description) -> Union[str, None]:
        if description:
            return 'Deskripsi harus kosong'

        return None
