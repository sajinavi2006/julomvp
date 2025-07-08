from __future__ import unicode_literals

from builtins import object

from django.contrib.postgres.fields import JSONField
from django.db import models

from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)


class KTPOCRModelManager(GetInstanceMixin, JuloModelManager):
    pass


class KTPOCRModel(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = KTPOCRModelManager()


class OCRImageResult(KTPOCRModel):
    id = models.AutoField(db_column='ocr_image_result_id', primary_key=True)
    application = models.ForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id'
    )
    image = models.ForeignKey('julo.Image', models.DO_NOTHING, db_column='image_id')
    is_blurry = models.BooleanField(default=False)
    is_dark = models.BooleanField(default=False)
    is_glary = models.BooleanField(default=False)
    opencv_data = JSONField(default=dict)
    opencv_config = JSONField(default=dict)
    coordinates = JSONField(default=dict, blank=True, null=True)

    class Meta(object):
        db_table = 'ocr_image_result'


class OCRProcess(KTPOCRModel):
    id = models.AutoField(db_column='ocr_process_id', primary_key=True)
    detection_latency_ms = models.FloatField(null=True, blank=True, default=None)
    transcription_latency_ms = models.FloatField(null=True, blank=True, default=None)
    juloocr_version = models.CharField(max_length=50, null=True, blank=True)
    detection_version = models.CharField(max_length=50, null=True, blank=True)
    transcription_version = models.CharField(max_length=50, null=True, blank=True)
    detection_logic_version = models.CharField(max_length=50, null=True, blank=True)
    transcription_logic_version = models.CharField(max_length=50, null=True, blank=True)
    ocr_config = JSONField(default=dict)
    status = models.TextField(null=True, blank=True, default=None)

    class Meta(object):
        db_table = 'ocr_process'


class OCRImageAutomlRequest(KTPOCRModel):
    id = models.AutoField(db_column='ocr_image_automl_request_id', primary_key=True)
    ocr_image_result = models.OneToOneField(
        OCRImageResult, models.DO_NOTHING, db_column='ocr_image_result_id'
    )
    response_url = models.CharField(max_length=200, null=True, blank=True)
    status = models.TextField(null=True, default=None)
    api_latency_ms = models.FloatField(null=True, blank=True, default=None)
    ocr_process = models.OneToOneField(OCRProcess, models.DO_NOTHING, db_column='ocr_process_id')

    class Meta(object):
        db_table = 'ocr_image_automl_request'


class OCRImageObject(KTPOCRModel):
    id = models.AutoField(db_column='ocr_image_object_id', primary_key=True)
    ocr_image_automl_request = models.ForeignKey(
        OCRImageAutomlRequest, models.DO_NOTHING, db_column='ocr_image_automl_request_id'
    )
    label = models.CharField(max_length=100)
    confidence = models.FloatField()
    x_min = models.FloatField()
    y_min = models.FloatField()
    x_max = models.FloatField()
    y_max = models.FloatField()

    class Meta(object):
        db_table = 'ocr_image_object'


class OcrImageGVORCRequest(KTPOCRModel):
    id = models.AutoField(db_column='ocr_image_gvocr_request_id', primary_key=True)
    ocr_image_result = models.OneToOneField(
        OCRImageResult, models.DO_NOTHING, db_column='ocr_image_result_id'
    )
    response_url = models.CharField(max_length=200, null=True, blank=True)
    status = models.TextField(null=True, default=None)
    api_latency_ms = models.FloatField(null=True, blank=True, default=None)
    ocr_process = models.OneToOneField(OCRProcess, models.DO_NOTHING, db_column='ocr_process_id')

    class Meta(object):
        db_table = 'ocr_image_gvocr_request'


class OCRImageTranscription(KTPOCRModel):
    id = models.AutoField(db_column='ocr_image_transcription_id', primary_key=True)
    ocr_image_gvocr_request = models.ForeignKey(
        OcrImageGVORCRequest, models.DO_NOTHING, db_column='ocr_image_gvocr_request_id'
    )
    ocr_image_object = models.ForeignKey(
        OCRImageObject, models.DO_NOTHING, db_column='ocr_image_object_id'
    )
    label = models.CharField(max_length=100)
    transcription = models.TextField(null=True)
    raw_transcription = models.TextField(null=True)
    raw_transcription_conf_scores = JSONField(default=dict)
    eligible = models.BooleanField(default=None)

    class Meta(object):
        db_table = 'ocr_image_transcription'
