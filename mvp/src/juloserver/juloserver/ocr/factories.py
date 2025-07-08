from builtins import object

from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.julo.tests.factories import ApplicationFactory, ImageFactory

from .models import (
    OCRImageAutomlRequest,
    OcrImageGVORCRequest,
    OCRImageObject,
    OCRImageResult,
    OCRImageTranscription,
    OCRProcess,
)


class OCRImageResultFactory(DjangoModelFactory):
    class Meta(object):
        model = OCRImageResult

    application = SubFactory(ApplicationFactory)
    image = SubFactory(ImageFactory)


class OCRProcessFactory(DjangoModelFactory):
    class Meta(object):
        model = OCRProcess


class OCRImageAutomlRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = OCRImageAutomlRequest

    ocr_image_result = SubFactory(OCRImageResultFactory)
    status = 'Success'
    ocr_process = SubFactory(OCRProcessFactory)


class OCRImageObjectFactory(DjangoModelFactory):
    class Meta(object):
        model = OCRImageObject

    ocr_image_automl_request = SubFactory(OCRImageAutomlRequestFactory)
    confidence = 1
    x_min = 1
    y_min = 2
    x_max = 3
    y_max = 4


class OcrImageGVORCRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = OcrImageGVORCRequest

    ocr_image_result = SubFactory(OCRImageResultFactory)
    status = 'Success'
    ocr_process = SubFactory(OCRProcessFactory)


class OCRImageTranscriptionFactory(DjangoModelFactory):
    class Meta(object):
        model = OCRImageTranscription

    ocr_image_gvocr_request = SubFactory(OcrImageGVORCRequestFactory)
    ocr_image_object = SubFactory(OCRImageObjectFactory)
    raw_transcription_conf_scores = []
