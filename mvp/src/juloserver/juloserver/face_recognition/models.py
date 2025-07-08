from __future__ import unicode_literals

import os
from builtins import object

from django.conf import settings
from django.contrib.postgres.fields import JSONField
from django.db import models

from juloserver.julo.models import Application, Customer, Device, Image, PIIType
from juloserver.julo.utils import get_oss_presigned_url
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julocore.data.models import TimeStampedModel
from juloserver.face_recognition.constants import FaceMatchingCheckConst
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager


class FaceImageResult(TimeStampedModel):
    id = models.AutoField(db_column='face_image_result_id', primary_key=True)
    application = BigForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    image = models.OneToOneField(Image, models.DO_NOTHING, db_column='image_id')
    sharpness = models.IntegerField()
    brightness = models.IntegerField()
    detected_faces = models.IntegerField()
    passed_filter = models.BooleanField(default=False)
    latency = models.IntegerField()
    is_alive = models.BooleanField(default=False)
    configs = JSONField(default=dict)

    class Meta(object):
        db_table = 'face_image_result'

    def __str__(self):
        """Visual identification"""
        return "face_image_result ({}) application ({})".format(self.id, self.application)


class FaceCollection(TimeStampedModel):
    id = models.AutoField(db_column='face_collection_id', primary_key=True)
    face_collection_name = models.TextField()
    status = models.TextField()

    class Meta(object):
        db_table = 'face_collection'

    def __str__(self):
        """Visual identification"""
        return "face_collection ({}) status {}".format(self.id, self.status)


class FaceSearchProcess(TimeStampedModel):
    id = models.AutoField(db_column='face_search_process_id', primary_key=True)
    application = BigForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    status = models.TextField()

    class Meta(object):
        db_table = 'face_search_process'

    def __str__(self):
        """Visual identification"""
        return "face_search_process ({})".format(self.id)


class FaceSearchResult(TimeStampedModel):
    id = models.AutoField(db_column='face_search_result_id', primary_key=True)
    searched_face_image_id = models.ForeignKey(
        FaceImageResult, models.DO_NOTHING, db_column='face_image_result_id'
    )
    matched_face_image_id = models.ForeignKey(
        Image, models.DO_NOTHING, db_column='image_id', default=0
    )
    search_face_confidence = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    similarity = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    face_collection = models.ForeignKey(
        FaceCollection, models.DO_NOTHING, db_column='face_collection_id', null=True
    )
    latency = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    configs = JSONField(default=dict)
    face_search_process = models.ForeignKey(
        FaceSearchProcess, models.DO_NOTHING, db_column='face_search_process_id'
    )

    class Meta(object):
        db_table = 'face_search_result'

    def __str__(self):
        """Visual identification"""
        return "face_search_result ({})".format(self.id)


class AwsRecogResponse(TimeStampedModel):
    id = models.AutoField(db_column='aws_recog_response_id', primary_key=True)
    image_id = models.ForeignKey(
        Image, models.DO_NOTHING, db_column='image_id', blank=True, null=True
    )
    raw_response = models.TextField()
    raw_response_type = models.TextField()

    class Meta(object):
        db_table = 'aws_recog_response'

    def __str__(self):
        """Visual identification"""
        return "aws_recog_response ({})".format(self.id)


class IndexedFace(TimeStampedModel):
    id = models.AutoField(db_column='indexed_face_id', primary_key=True)
    face_collection = models.ForeignKey(
        FaceCollection, models.DO_NOTHING, db_column='face_collection_id'
    )
    image = models.ForeignKey(Image, models.DO_NOTHING, db_column='julo_image_id', default=0)
    application = BigForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    customer = BigForeignKey(Customer, models.DO_NOTHING, db_column='customer_id')
    collection_face_id = models.TextField(default='-')
    collection_image_id = models.TextField(default='-')
    collection_image_url = models.CharField(max_length=200, default='/')
    match_status = models.TextField(default='active')
    application_status_code = models.TextField()
    latency = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)

    class Meta(object):
        db_table = 'indexed_face'

    def __str__(self):
        """Visual identification"""
        return "indexed_face ({})".format(self.id)

    @property
    def image_url(self):
        if self.collection_image_url == '' or self.collection_image_url is None:
            return None
        return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.collection_image_url)

    @property
    def image_ext(self):
        name, extension = os.path.splitext(self.collection_image_url)
        return extension.lower()


class FaceRecommenderResultManager(PIIVaultModelManager):
    pass


class FaceRecommenderResult(PIIVaultModel):
    PII_FIELDS = ['nik', 'email', 'full_name']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'antifraud_pii_vault'

    id = models.AutoField(db_column='face_recommender_result_id', primary_key=True)
    face_search_result = models.ForeignKey(
        FaceSearchResult,
        models.DO_NOTHING,
        db_column='face_search_result_id',
        blank=True,
        null=True,
    )
    application = BigForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    is_match = models.BooleanField(default=False)
    match_application_id = models.IntegerField(blank=True, null=True)
    apply_date = models.DateField(blank=True, null=True)
    geo_location_distance = models.TextField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    provinsi = models.TextField(blank=True, null=True)
    kabupaten = models.TextField(blank=True, null=True)
    kecamatan = models.TextField(blank=True, null=True)
    kelurahan = models.TextField(blank=True, null=True)
    nik = models.TextField(blank=True, null=True)
    email = models.TextField(blank=True, null=True)
    full_name = models.TextField(blank=True, null=True)
    birth_place = models.TextField(blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    bank_name = models.TextField(blank=True, null=True)
    bank_account_name = models.TextField(blank=True, null=True)
    bank_account_number = models.TextField(blank=True, null=True)
    device = models.ForeignKey(
        Device, models.DO_NOTHING, db_column='device_id', blank=True, null=True
    )
    device_name = models.TextField(blank=True, null=True)
    nik_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    full_name_tokenized = models.TextField(blank=True, null=True)

    objects = FaceRecommenderResultManager()

    class Meta(object):
        db_table = 'face_recommender_result'


class IndexedFaceFraud(TimeStampedModel):
    id = models.AutoField(db_column='indexed_face_fraud_id', primary_key=True)
    face_collection = models.ForeignKey(
        FaceCollection, models.DO_NOTHING, db_column='face_collection_id'
    )
    image = models.ForeignKey(Image, models.DO_NOTHING, db_column='julo_image_id', default=0)
    application = BigForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    customer = BigForeignKey(Customer, models.DO_NOTHING, db_column='customer_id')
    collection_face_id = models.TextField(default='-')
    collection_image_id = models.TextField(default='-')
    collection_image_url = models.CharField(max_length=200, default='/')
    match_status = models.TextField(default='active')
    application_status_code = models.TextField()
    latency = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)

    class Meta(object):
        db_table = 'indexed_face_fraud'

    def __str__(self):
        """Visual identification"""
        return "indexed_face_fraud ({})".format(self.id)

    @property
    def image_url(self):
        if self.collection_image_url == '' or self.collection_image_url is None:
            return None
        return get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, self.collection_image_url)

    @property
    def image_ext(self):
        name, extension = os.path.splitext(self.collection_image_url)
        return extension.lower()


class FraudFaceSearchProcess(TimeStampedModel):
    id = models.AutoField(db_column='fraud_face_search_process_id', primary_key=True)
    application = BigForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    status = models.TextField()

    class Meta(object):
        db_table = 'fraud_face_search_process'

    def __str__(self):
        """Visual identification"""
        return "fraud_face_search_process ({})".format(self.id)


class FraudFaceSearchResult(TimeStampedModel):
    id = models.AutoField(db_column='fraud_face_search_result_id', primary_key=True)
    searched_face_image_id = models.ForeignKey(
        FaceImageResult, models.DO_NOTHING, db_column='face_image_result_id'
    )
    matched_face_image_id = models.ForeignKey(
        Image, models.DO_NOTHING, db_column='image_id', default=0
    )
    search_face_confidence = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    similarity = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    face_collection = models.ForeignKey(
        FaceCollection, models.DO_NOTHING, db_column='face_collection_id', null=True
    )
    latency = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    configs = JSONField(default=dict)
    face_search_process = models.ForeignKey(
        FraudFaceSearchProcess, models.DO_NOTHING, db_column='fraud_face_search_process_id'
    )

    class Meta(object):
        db_table = 'fraud_face_search_result'

    def __str__(self):
        """Visual identification"""
        return "fraud_face_search_result ({})".format(self.id)


class FraudFaceRecommenderResultManager(PIIVaultModelManager):
    pass


class FraudFaceRecommenderResult(PIIVaultModel):
    PII_FIELDS = ['nik', 'email', 'full_name']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'antifraud_pii_vault'

    id = models.AutoField(db_column='fraud_face_recommender_result_id', primary_key=True)
    fraud_face_search_result = models.ForeignKey(
        FraudFaceSearchResult,
        models.DO_NOTHING,
        db_column='fraud_face_search_result_id',
        blank=True,
        null=True,
    )
    application = BigForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    is_match = models.BooleanField(default=False)
    match_application_id = models.IntegerField(blank=True, null=True)
    apply_date = models.DateField(blank=True, null=True)
    geo_location_distance = models.TextField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    provinsi = models.TextField(blank=True, null=True)
    kabupaten = models.TextField(blank=True, null=True)
    kecamatan = models.TextField(blank=True, null=True)
    kelurahan = models.TextField(blank=True, null=True)
    nik = models.TextField(blank=True, null=True)
    email = models.TextField(blank=True, null=True)
    full_name = models.TextField(blank=True, null=True)
    birth_place = models.TextField(blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    bank_name = models.TextField(blank=True, null=True)
    bank_account_name = models.TextField(blank=True, null=True)
    bank_account_number = models.TextField(blank=True, null=True)
    device = models.ForeignKey(
        Device, models.DO_NOTHING, db_column='device_id', blank=True, null=True
    )
    device_name = models.TextField(blank=True, null=True)
    nik_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    full_name_tokenized = models.TextField(blank=True, null=True)

    objects = FraudFaceRecommenderResultManager()

    class Meta(object):
        db_table = 'fraud_face_recommender_result'


class FaceMatchingCheck(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column='face_matching_check_id')
    application = BigForeignKey(
        Application, on_delete=models.DO_NOTHING, db_column='application_id', db_constraint=False
    )
    process = models.SmallIntegerField()
    reference_image = BigForeignKey(
        Image,
        models.DO_NOTHING,
        db_column='reference_image_id',
        db_constraint=False,
        related_name='reference_face_matching_checks',
        null=True,
        blank=True,
    )
    target_image = BigForeignKey(
        Image,
        models.DO_NOTHING,
        db_column='target_image_id',
        db_constraint=False,
        related_name='target_face_matching_checks',
        null=True,
        blank=True,
    )
    status = models.SmallIntegerField(default=0)
    is_agent_verified = models.BooleanField(default=False)
    metadata = JSONField(blank=True, null=True)

    class Meta:
        db_table = 'face_matching_check'


class FaceMatchingResult:
    def __init__(
        self,
        is_feature_active: bool = False,
        is_agent_verified: bool = False,
        status: FaceMatchingCheckConst.Status = FaceMatchingCheckConst.Status.not_triggered,
    ):
        self.is_feature_active = is_feature_active
        self.is_agent_verified = is_agent_verified
        self.status = status

    def to_dict(
        self,
    ):
        if not self.is_feature_active:
            return {
                "is_feature_active": self.is_feature_active,
            }

        return {
            "is_feature_active": self.is_feature_active,
            "is_agent_verified": self.is_agent_verified,
            "status": self.status.value,
        }


class FaceMatchingResults:
    def __init__(
        self,
        selfie_x_ktp: FaceMatchingResult = FaceMatchingResult(),
        selfie_x_liveness: FaceMatchingResult = FaceMatchingResult(),
    ):
        self.selfie_x_ktp = selfie_x_ktp
        self.selfie_x_liveness = selfie_x_liveness

    def to_dict(
        self,
    ):
        process_const = FaceMatchingCheckConst.Process
        return {
            process_const.selfie_x_ktp.string_val: self.selfie_x_ktp.to_dict(),
            process_const.selfie_x_liveness.string_val: self.selfie_x_liveness.to_dict(),
        }
