import logging
import time
import re
from builtins import object, str
from datetime import datetime
from io import BytesIO

import cv2
from dateutil import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from django.db.models import Max
from django.utils import timezone
from juloocr import (
    AutomlClient,
    GoogleVisionClient,
    ObjectDetectionService,
    TextRecognitionService,
)
from PIL import Image as PILImage
from django.db import (
    transaction,
)

from juloserver.application_flow.services2.open_cv import (
    build_image_arrays,
    crop_based_on_edge_detection,
    image_check_blur,
    image_check_dark,
    image_check_glare,
    is_ktp_detected,
    scale_down_image,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    FeatureSetting,
    Image,
    ImageMetadata,
    MobileFeatureSetting,
    Application,
    ExperimentSetting,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import (
    upload_file_to_oss,
    clean_string_from_special_chars,
)
from juloserver.julo.exceptions import ForbiddenError

from juloserver.application_form.models import (
    OcrKtpResult,
    OcrKtpMetaData,
    OcrKtpMetaDataAttribute,
    OcrKtpMetaDataValue,
)

from .constants import (
    APPLICATION_FIELDS_TYPE,
    APPLICATION_KEY_MAPPING,
    GENDER_MAPPING,
    OCRProcessMsg,
    OCRAPIResponseStatus,
    OCRFileUploadConst,
)
from .models import (
    OCRImageAutomlRequest,
    OcrImageGVORCRequest,
    OCRImageObject,
    OCRImageResult,
    OCRImageTranscription,
)
from .models import OCRProcess as OCRProcessModel
from .serializers import OpenCVDataSerializer
from .utils import remove_local_file, text_upload_handle_media
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.exceptions import JuloException
from juloserver.ocr.clients import get_ocr_client
from juloserver.ocr.exceptions import OCRBadRequestException
from juloserver.account.models import ExperimentGroup
from juloserver.julo.constants import ExperimentConst
from juloserver.ocr.constants import OCRKTPExperimentConst
from juloserver.ocr.exceptions import OCRKTPExperimentException
from juloserver.ocr.serializers import KtpOCRResultSerializer
from juloserver.julo.utils import ratio_of_similarity

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

logger = logging.getLogger(__name__)
juloLog = JuloLog(__name__)
sentry_client = get_julo_sentry_client()


class OCRProcess(object):
    def __init__(self, application_id, ktp_image, raw_ktp_image, ktp_image_result):
        self.application_id = application_id
        self.raw_ktp_image = raw_ktp_image
        self.ktp_image = ktp_image
        self.ktp_image_result = ktp_image_result

    def run_ocr_process(self):
        from juloserver.ocr.tasks import store_ocr_data

        # upload image on async task
        image = self.store_ktp_image()
        ocr_image_result_id, can_process, validation_results = self.store_image_result(image.id)
        can_retry = True
        application_data = {}

        if not can_process:
            return application_data, can_retry

        ocr_config = get_ocr_setting()
        (
            text_detection_response,
            text_detection_result,
            text_recognition_response,
            text_recognition_result,
            status_msg,
        ) = self.get_ocr_result(ocr_config)

        task_param = [
            ocr_image_result_id,
            text_detection_response,
            text_detection_result,
            text_recognition_response,
            text_recognition_result,
            status_msg,
            ocr_config,
            self.application_id,
            image.id,
        ]
        store_ocr_data.delay(*task_param)

        can_retry = text_detection_result is None
        application_data = self.transform_application_data(text_recognition_result)
        return application_data, can_retry

    def run_ocr_process_with_open_cv(self, image_metadata=None):
        from juloserver.ocr.tasks import store_ocr_data

        # upload image on async task
        image = self.store_ktp_image(image_metadata=image_metadata)
        ocr_image_result_id, can_process, validation_results = self.store_image_result(image.id)
        application_data = {}
        image_response = {
            'image_id': image.id,
        }

        if not can_process and validation_results:

            return application_data, validation_results, image_response

        ocr_config = get_ocr_setting()
        (
            text_detection_response,
            text_detection_result,
            text_recognition_response,
            text_recognition_result,
            status_msg,
        ) = self.get_ocr_result(ocr_config)

        task_param = [
            ocr_image_result_id,
            text_detection_response,
            text_detection_result,
            text_recognition_response,
            text_recognition_result,
            status_msg,
            ocr_config,
            self.application_id,
            image.id,
        ]
        store_ocr_data.delay(*task_param)

        application_data = self.transform_application_data(text_recognition_result)

        return application_data, validation_results, image_response

    def transform_application_data(self, application_data):
        result = application_data
        predictions = application_data.get('data', {}).get('predictions')
        if predictions:
            result = {'address': {}, 'personal_info': {}}
            for data in predictions:
                if data['pred']:
                    converted_key = APPLICATION_KEY_MAPPING.get(data['class'])
                    if not converted_key or not data.get('eligible', 'check_later'):
                        continue

                    if converted_key in APPLICATION_FIELDS_TYPE['address']:
                        info_type = 'address'
                    else:
                        info_type = 'personal_info'

                    if converted_key == 'tempat_tanggal_lahir':
                        birthplace, dob = data['pred']['pob'], data['pred']['dob']
                        if birthplace['eligible']:
                            result[info_type]['birthplace'] = birthplace['data']
                        if dob['eligible']:
                            result[info_type]['dob'] = dob['data']
                    elif converted_key == 'gender':
                        result[info_type][converted_key] = GENDER_MAPPING[data['pred'].lower()]
                    else:
                        result[info_type][converted_key] = data['pred']

            if len(result['address']) < 2:
                result['address'] = {}
            if len(result['personal_info']) < 2:
                result['personal_info'] = {}

        return result

    def store_ktp_image(self, image_metadata=None, is_upload_image=True):
        from juloserver.julo.tasks import upload_image

        image = Image()
        image.image_type = 'ktp_ocr'
        image.image_source = self.application_id
        image.save()

        image.image.save(self.ktp_image.name, self.ktp_image)
        if image_metadata:
            ImageMetadata.objects.create(
                image_id=image.id, application_id=self.application_id, **image_metadata
            )
        if is_upload_image:
            upload_image.delay(image.id, False)
        # move cursor to start of file
        self.ktp_image.seek(0)

        if self.raw_ktp_image:
            # store raw ktp image
            raw_ktp_image = Image()
            raw_ktp_image.image_type = 'raw_ktp_ocr'
            raw_ktp_image.image_source = self.application_id
            raw_ktp_image.save()

            raw_ktp_image.image.save(self.raw_ktp_image.name, self.raw_ktp_image)
            upload_image.delay(raw_ktp_image.id, False)

        return image

    def store_image_result(self, image_id):
        opencv_data, threshold, coordinates = self.ktp_image_result
        is_blurry = opencv_data.get('is_blurry')
        is_dark = opencv_data.get('is_dark')
        is_glary = opencv_data.get('is_glary')
        ocr_image_result = OCRImageResult.objects.create(
            application_id=self.application_id,
            image_id=image_id,
            is_blurry=is_blurry,
            is_dark=is_dark,
            is_glary=is_glary,
            opencv_data=opencv_data,
            opencv_config=threshold,
            coordinates=coordinates,
        )
        can_process = not (is_glary or is_dark or is_blurry)
        validation_results = None
        if not can_process:
            validation_results = {'is_blurry': is_blurry, 'is_dark': is_dark, 'is_glary': is_glary}
        return ocr_image_result.id, can_process, validation_results

    def get_ocr_result(self, ocr_config):
        ktp_image_bytes = self.ktp_image.read()
        object_detection_settings = ocr_config['object_detection']
        text_recognition_settings = ocr_config['text_recognition']
        status_msg = OCRProcessMsg.DONE
        ocr_raw_response = ({}, 0, 0)
        predictions = {}

        object_predictions, automl_response, objects, status = self.get_object_detection(
            ktp_image_bytes, object_detection_settings
        )
        if not status:
            status_msg = OCRProcessMsg.DETECTOR_FAILED
            return automl_response, objects, ocr_raw_response, predictions, status_msg

        personal_info_filter = objects.get('data', {}).get('personal_info_filter')
        if not personal_info_filter:
            # should be update a status in future
            status_msg = OCRProcessMsg.FILTER_FAILED
            return automl_response, objects, ocr_raw_response, predictions, status_msg

        ocr_raw_response, predictions, status = self.get_text_recognition(
            ktp_image_bytes, object_predictions, text_recognition_settings
        )
        if not status:
            status_msg = OCRProcessMsg.RECOGNITION_FAILED

        return automl_response, objects, ocr_raw_response, predictions, status_msg

    def get_object_detection(self, ktp_image_bytes, object_detection_settings):
        automl_response = ({}, 0, 0)
        objects = {}
        status = True
        object_predictions = None

        try:
            automl_client = AutomlClient(
                credentials_path=settings.GOOGLE_CREDENTIALS_PATH,
                project_id=settings.OCR_PROJECT_ID,
                model_id=settings.OCR_MODEL_ID,
            )
            # initializing the text detection client
            object_detection_service = ObjectDetectionService(client=automl_client)

            # calling method to detect objects
            object_detection_response = object_detection_service.detect(
                ktp_image_bytes, object_detection_settings
            )
            object_predictions = object_detection_response.get_predictions()

            automl_response = object_detection_response.get_client_response()
            objects = object_detection_response.get_detection_result()
        except Exception as error:
            status = False
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.error(
                {
                    'action': 'object_detection_service',
                    'error': str(error),
                    'data': {'application_id': self.application_id},
                }
            )

        return object_predictions, automl_response, objects, status

    def get_text_recognition(self, ktp_image_bytes, object_predictions, text_recognition_settings):
        ocr_raw_response = ({}, 0, 0)
        predictions = {}
        status = True

        try:
            gv_client = GoogleVisionClient()
            text_recognition_service = TextRecognitionService(client=gv_client)

            text_recognition_response = text_recognition_service.recognize(
                ktp_image_bytes, object_predictions, text_recognition_settings
            )

            text_recognition_response.get_predictions()

            ocr_raw_response = text_recognition_response.get_client_response()
            predictions = text_recognition_response.get_recognition_result()
        except Exception as error:
            status = False
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.error(
                {
                    'action': 'get_ocr_result',
                    'error': str(error),
                    'data': {'application_id': self.application_id},
                }
            )

        return ocr_raw_response, predictions, status


class ProcessVerifyKTP(object):
    def __init__(self, application):
        detokenized_application = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [{'customer_xid': application.customer.customer_xid, 'object': application}],
            force_get_local_data=True,
        )
        self.application = detokenized_application[0]
        self.prediction_data = None

    def process_verify_ktp(self):
        self.prediction_data = self.load_prediction_data()
        if self.prediction_data and self.dob_checking():
            self.nik_checking()
            self.applicant_name_checking()
            self.pob_checking()
            self.address_checking()
            self.dob_in_ktp_checking()
            self.area_in_ktp_checking()

    def nik_checking(self):
        ktp = self.prediction_data.get('nik')
        if ktp and ktp == self.application.ktp:
            self.update_application_checklist('ktp')
            return True
        return False

    def applicant_name_checking(self):
        fullname = self.prediction_data.get('nama')
        if fullname and fullname.lower() == self.application.fullname.lower():
            self.update_application_checklist('fullname')
            return True
        return False

    def dob_checking(self):
        from juloserver.julo.services import process_application_status_change

        dob_str = self.prediction_data.get('dob')
        dob_dt = None
        if dob_str:
            dob_dt = datetime.strptime(dob_str, "%d-%m-%Y").date()
        if dob_dt and dob_dt == self.application.dob:
            today = timezone.localtime(timezone.now()).date()
            current_age = relativedelta.relativedelta(today, dob_dt).years
            if 21 <= current_age <= 59:
                self.update_application_checklist('dob')
                return True

            process_application_status_change(
                self.application.id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                "application_date_of_birth",
            )
            return False

        return True

    def pob_checking(self):
        pob = self.prediction_data.get('pob')
        birth_place = self.application.birth_place or ''
        if pob and pob.lower() == birth_place.lower():
            self.update_application_checklist('birth_place')
            return True
        return False

    def address_checking(self):
        if self.application.address_same_as_ktp:
            address_provinsi = self.prediction_data.get('provinsi')
            address_kabupaten = self.prediction_data.get('kabupaten')
            address_street_num = self.prediction_data.get('alamat')
            address_kelurahan = self.prediction_data.get('kelurahan')
            address_kecamatan = self.prediction_data.get('kecamatan')

            provinsi_checking = (
                address_provinsi
                and address_provinsi.lower() == self.application.address_provinsi.lower()
            )

            kabupaten_checking = (
                address_kabupaten
                and address_kabupaten.lower() == self.application.address_kabupaten.lower()
            )

            street_num_checking = (
                address_street_num
                and address_street_num.lower() == self.application.address_street_num.lower()
            )

            kelurahan_checking = (
                address_kelurahan
                and address_kelurahan.lower() == self.application.address_kelurahan.lower()
            )

            kecamatan_checking = (
                address_kecamatan
                and address_kecamatan.lower() == self.application.address_kecamatan.lower()
            )

            if (
                provinsi_checking
                and kabupaten_checking
                and street_num_checking
                and kelurahan_checking
                and kecamatan_checking
            ):
                self.update_application_checklist('address_street_num')
                return True

        return False

    def dob_in_ktp_checking(self):
        dob_in_ktp = self.application.ktp[6:12]
        prediction_dob = self.prediction_data.get('dob')
        jenis_kelamin = self.prediction_data.get('jenis_kelamin')
        if prediction_dob and jenis_kelamin:
            prediction_dob = prediction_dob.replace('-', '')
            prediction_dob = prediction_dob[:4] + prediction_dob[-2:]
            if self.application.gender == 'Wanita':
                prediction_dob = '%s%s' % (str(int(prediction_dob[0]) + 4), prediction_dob[1:])
            if prediction_dob == dob_in_ktp:
                self.update_application_checklist('dob_in_nik', 'sd')
                return True
        return False

    def area_in_ktp_checking(self):
        address_kelurahan = self.prediction_data.get('kelurahan')
        address_kecamatan = self.prediction_data.get('kecamatan')

        kelurahan_checking = (
            address_kelurahan
            and address_kelurahan.lower() == self.application.address_kelurahan.lower()
        )

        kecamatan_checking = (
            address_kecamatan
            and address_kecamatan.lower() == self.application.address_kecamatan.lower()
        )

        if kelurahan_checking and kecamatan_checking:
            kodepos_in_ktp = self.application.ktp[:5]
            if self.application.address_kodepos == kodepos_in_ktp:
                self.update_application_checklist('area_in_nik', 'sd')
                return True

        return False

    def update_application_checklist(self, field_name, group='dv'):
        from juloserver.julo.services import update_application_checklist_data

        data = {'field_name': field_name, 'group': group, 'value': True}
        update_application_checklist_data(self.application, data)

    def load_prediction_data(self):
        result = {}
        last_records = OCRImageTranscription.objects.filter(
            ocr_image_gvocr_request__ocr_image_result__application_id=self.application.id,
        ).aggregate(last_records=Max('ocr_image_gvocr_request_id'))['last_records']

        transcription_data = OCRImageTranscription.objects.filter(
            ocr_image_gvocr_request__ocr_image_result__application_id=self.application.id,
            eligible=True,
            ocr_image_gvocr_request_id=last_records,
        ).values_list('label', 'transcription')
        for key, value in transcription_data:
            result.update({key: value})

        return result


class OpenCVProcess(object):
    def __init__(self, raw_ktp_image, manual_ktp_image, application_id, retries, config=None):
        self.raw_ktp_image = raw_ktp_image
        self.manual_ktp_image = manual_ktp_image
        self.application_id = application_id
        self.retries = retries
        self.config = config or self.get_open_cv_config()
        self._convert_image_in_mem_file()

    def _convert_image_in_mem_file(self):
        if isinstance(self.raw_ktp_image, TemporaryUploadedFile):
            logger.info(
                'convert_raw_ktp_image_to_in_mem|application_id={}'.format(self.application_id)
            )
            self.raw_ktp_image = convert_temporary_to_inmem_file(self.raw_ktp_image)
        if isinstance(self.manual_ktp_image, TemporaryUploadedFile):
            logger.info(
                'convert_manual_ktp_image_to_in_mem|'
                'application_id={}'.format(self.application_id)
            )
            self.manual_ktp_image = convert_temporary_to_inmem_file(self.manual_ktp_image)

    def initiate_open_cv(self):
        raw_ktp_array, manual_ktp_array = build_image_arrays(
            self.raw_ktp_image, self.manual_ktp_image
        )
        if raw_ktp_array is None or manual_ktp_array is None:
            return None, False, None, self.get_processing_error_response()
        cropped_ktp_array, crop_coordinates = crop_based_on_edge_detection(image=raw_ktp_array)
        is_ktp = False if cropped_ktp_array is None else is_ktp_detected(cropped_ktp_array)
        logger.info(
            'initiate_open_cv|is_ktp={}, application_id={}'.format(is_ktp, self.application_id)
        )
        if is_ktp:
            final_ktp_array = cropped_ktp_array
            ktp_image_output = self.numpy_array_to_image_file(
                final_ktp_array, 'PNG', self.manual_ktp_image
            )
        else:
            final_ktp_array = manual_ktp_array
            ktp_image_output = self.manual_ktp_image
        if not self.config:
            open_cv_inactive_response = self.get_early_response(ktp_image_output)
            return None, False, None, open_cv_inactive_response
        last_ocr_result = OCRImageResult.objects.filter(application_id=self.application_id).last()
        if last_ocr_result and self.retries >= self.config.parameters['number_of_tries']:
            if (
                self.retries == last_ocr_result.opencv_data['number_of_retries']
                or self.retries > self.config.parameters['number_of_tries']
            ):
                null_retry_response = self.get_early_response(ktp_image_output)
                return None, False, None, null_retry_response
        if final_ktp_array is None:
            return None, False, None, self.get_processing_error_response()
        is_valid, params = self.validate_image(final_ktp_array, crop_coordinates)
        return ktp_image_output, is_valid, params, None

    def get_early_response(self, cropped_ktp_final):
        image = self.store_ktp_image(cropped_ktp_final)
        response = {
            'retries_left': 0,
            'image': {'image_id': image.id},
            'is_open_cv_active': True if self.config else False,
        }
        return response

    def get_processing_error_response(self):
        response = {'error': 'Foto tidak dapat diproses, silahkan ulangi'}
        return response

    def store_ktp_image(self, cropped_ktp_final):
        from juloserver.julo.tasks import upload_image

        image = Image()
        image.image_type = 'ktp_self_preview'
        image.image_source = self.application_id
        image.save()
        image.image.save(cropped_ktp_final.name, cropped_ktp_final)
        upload_image.delay(image.id, False)
        return image

    def numpy_array_to_image_file(self, numpy_image, output_format, upload_file):
        success, image_bytes = cv2.imencode('.jpg', numpy_image)
        io_file = BytesIO(image_bytes)
        pil_image = PILImage.open(io_file)

        output_file = InMemoryUploadedFile(
            file=io_file,
            field_name=upload_file.field_name,
            name=upload_file.name,
            content_type=upload_file.content_type,
            size=pil_image.tell,
            content_type_extra=upload_file.content_type_extra,
            charset=None,
        )
        return output_file

    def get_open_cv_config(self):
        open_cv_config = MobileFeatureSetting.objects.filter(
            feature_name='ocr_opencv_setting', is_active=True
        ).last()
        return open_cv_config

    def check_blur(self, ktp_image, config, scaled_image=None):
        is_blur, blur_value = image_check_blur(ktp_image, config['threshold'], scaled_image)
        return is_blur, blur_value

    def check_dark(self, ktp_image, config, scaled_image=None):
        kwargs = {
            'limit_black_bin': config['lower_bin'],
            'black_pct': config['lower_limit'],
            'limit_white_bin': config['upper_bin'],
            'white_pct': config['upper_limit'],
        }
        is_dark, dark_value = image_check_dark(image=ktp_image, scaled_image=scaled_image, **kwargs)
        return is_dark, dark_value

    def check_glare(self, ktp_image, config, scaled_image=None):
        is_glare, glare_value = image_check_glare(
            ktp_image, config['threshold'], config['percentage_limit'], scaled_image
        )
        return is_glare, glare_value

    def validate_image(self, ktp_image, crop_coordinates):
        config = self.config.parameters
        ktp_image_orig, ktp_image_scaled = scale_down_image(ktp_image)
        is_blur, blur_value = self.check_blur(ktp_image_orig, config['blur'], ktp_image_scaled)
        is_dark, dark_value = self.check_dark(ktp_image_orig, config['dark'], ktp_image_scaled)
        is_glare, glare_value = self.check_glare(ktp_image_orig, config['glare'], ktp_image_scaled)
        is_valid = True
        if True in {is_blur, is_dark, is_glare}:
            is_valid = False
        opencv_data = {
            'is_dark': is_dark,
            'is_glary': is_glare,
            'is_blurry': is_blur,
            'blur_value': blur_value,
            'dark_value': dark_value,
            'glare_value': glare_value,
            'number_of_retries': self.retries,
        }
        response = {
            'opencv_data': opencv_data,
            'threshold': config,
            'coordinates': crop_coordinates,
        }
        return is_valid, response


def store_object_detector_request(
    ocr_image_result_id, object_detector_response, ocr_process_id, application_id, image_id
):
    object_detector_raw_response, automl_latency, _version = object_detector_response

    ocr_image_automl_request = OCRImageAutomlRequest.objects.create(
        ocr_image_result_id=ocr_image_result_id,
        ocr_process_id=ocr_process_id,
        api_latency_ms=automl_latency,
    )

    if object_detector_raw_response:
        oss_path = 'ocr/ktp/app_{}/img_{}/object_detector'.format(application_id, image_id)
        file_name = 'automl_response.txt'
        oss_file_url = upload_object_detector_to_oss(
            oss_path, object_detector_raw_response, file_name
        )
        ocr_image_automl_request.response_url = oss_file_url
        ocr_image_automl_request.save()
    return ocr_image_automl_request.id


def store_object_detector(object_detector_request_id, object_detector_result):
    result = {}
    for data in object_detector_result['data']['predictions']:
        ocr_image_object = OCRImageObject.objects.create(
            ocr_image_automl_request_id=object_detector_request_id,
            label=data['label'],
            confidence=data['confidence'],
            x_min=data['xmin'],
            y_min=data['ymin'],
            x_max=data['xmax'],
            y_max=data['ymax'],
        )
        result[data['label']] = ocr_image_object.id

    return result


def store_text_recognition_request(
    ocr_image_result_id, text_recognition_response, ocr_process_id, application_id, image_id
):
    text_recognition_raw_response, gg_vision_latency, _version = text_recognition_response

    ocr_image_gvorc_request = OcrImageGVORCRequest.objects.create(
        ocr_image_result_id=ocr_image_result_id,
        ocr_process_id=ocr_process_id,
        api_latency_ms=gg_vision_latency,
    )

    if text_recognition_raw_response:
        oss_path = 'ocr/ktp/app_{}/img_{}/text_recognition'.format(application_id, image_id)
        file_name = 'google_vision_response.txt'
        oss_file_url = upload_object_detector_to_oss(
            oss_path, text_recognition_raw_response, file_name
        )
        ocr_image_gvorc_request.response_url = oss_file_url
        ocr_image_gvorc_request.save()
    return ocr_image_gvorc_request.id


def store_text_recognition(
    text_recognition_request_id, object_detector_ids, text_recognition_result
):
    def new_record(label, object_label, pred, raw_pred, confidence, eligible):
        return OCRImageTranscription(
            ocr_image_gvocr_request_id=text_recognition_request_id,
            ocr_image_object_id=object_detector_ids[object_label],
            label=label,
            transcription=pred,
            raw_transcription_conf_scores=confidence,
            eligible=eligible,
            raw_transcription=raw_pred,
        )

    bulk_data = []
    for data in text_recognition_result['data']['predictions']:
        if data['class'] == 'tempat_tanggal_lahir':
            for birth_key, birth_data in list(data['pred'].items()):
                bulk_data.append(
                    new_record(
                        birth_key,
                        data['class'],
                        birth_data['data'],
                        data['raw_pred'],
                        data['ocr_confidence'],
                        birth_data['eligible'],
                    )
                )
        else:
            bulk_data.append(
                new_record(
                    data['class'],
                    data['class'],
                    data['pred'],
                    data['raw_pred'],
                    data['ocr_confidence'],
                    data['eligible'],
                )
            )

    OCRImageTranscription.objects.bulk_create(bulk_data)


def create_or_update_ocr_process(data):
    ocr_process = OCRProcessModel.objects.create(**data)
    return ocr_process.id


def get_ocr_setting():
    ocr_config = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.OCR_SETTING, is_active=True
    )

    return ocr_config.parameters


def upload_object_detector_to_oss(oss_path, data, file_name):
    local_file_path, remote_file_path = text_upload_handle_media(data, oss_path, file_name)
    upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_file_path, remote_file_path)
    remove_local_file(local_file_path)
    return remote_file_path


def save_ktp_to_application_document(image_id, applicaton_id, customer_id):
    image = Image.objects.get(id=image_id)
    image_source_id = image.image_source
    if image_source_id:
        application = Application.objects.get_or_none(pk=image_source_id)
        if application and application.customer.id != customer_id:
            raise ForbiddenError()

    if image.image_type == 'ktp_self_preview':
        image.image_type = 'ktp_self'
        image.image_source = applicaton_id
        image.save()
    elif image.image_type == 'ktp_ocr':
        if image.url == '':
            for retry in range(2):
                image.refresh_from_db()
                if not image.url == '':
                    break
                time.sleep(1)
        new_image = Image()
        new_image.image_type = 'ktp_self'
        new_image.image_source = applicaton_id
        new_image.service = "oss"
        new_image.url = image.url
        new_image.save()
        image_id = new_image.id
    return {'image_id': image_id}


def process_ktp_ocr(raw_ktp_image, ktp_image, application, retries, image_metadata):
    open_cv_client = OpenCVProcess(raw_ktp_image, ktp_image, application.id, retries)
    validated_ktp_image, is_valid, param, early_return_res = open_cv_client.initiate_open_cv()

    if early_return_res:
        if 'error' in early_return_res:
            return 'failed', early_return_res
        else:
            return 'success', early_return_res

    try:
        opencv_data = param.get('opencv_data', {})
        threshold = param.get('threshold', {})
        coordinates = param.get('coordinates', {})
    except (ValueError, AttributeError):
        return 'failed', {'param': "Not json format"}

    if not opencv_data or not threshold:
        return 'failed', {'param': "This field must contain valid data"}
    opencv_data_serializer = OpenCVDataSerializer(data=opencv_data)
    if not opencv_data_serializer.is_valid():
        return 'failed', {'param': "OpenCV data is invalid"}

    ocr_process = OCRProcess(
        application.id, validated_ktp_image, raw_ktp_image, [opencv_data, threshold, coordinates]
    )
    application_data, validation_results, image_res = ocr_process.run_ocr_process_with_open_cv(
        image_metadata=image_metadata
    )

    retries_left = int(open_cv_client.config.parameters['number_of_tries']) - retries

    if not application_data:
        return 'success', {
            'retries_left': retries_left,
            'validation_results': validation_results,
            'image': image_res,
            'validation_success': False if validation_results else True,
            'ocr_success': False,
            'is_open_cv_active': True if open_cv_client.config else False,
        }

    return 'success', {
        'retries_left': retries_left,
        'application': application_data,
        'image': image_res,
        'validation_success': True,
        'ocr_success': True,
        'is_open_cv_active': True if open_cv_client.config else False,
    }


def get_ocr_opencv_setting():
    open_cv_config = MobileFeatureSetting.objects.filter(
        feature_name='ocr_opencv_setting', is_active=True
    ).last()
    return open_cv_config


def convert_temporary_to_inmem_file(temp_file: TemporaryUploadedFile, field_name=None):
    file_data = temp_file.read()
    return InMemoryUploadedFile(
        file=BytesIO(file_data),  # Use BytesIO to wrap the file data
        field_name=field_name,
        name=temp_file.name,
        content_type=temp_file.content_type,
        size=len(file_data),
        charset=temp_file.charset,
        content_type_extra=temp_file.content_type_extra,
    )


@sentry_client.capture_exceptions
def get_threshold_ocr_setting(return_parameters=True, application_id=None):
    """
    The application_id parameter is optional, so can easy to track by our log.
    """

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.KTP_OCR_THRESHOLD_VALUE
    ).last()

    if not setting or not setting.is_active:
        juloLog.error(
            {
                'message': 'Feature setting for OCR is not found or inactive',
                'feature_name': FeatureNameConst.KTP_OCR_THRESHOLD_VALUE,
                'application_id': application_id,
            }
        )
        return None

    if not setting.parameters:
        error_message = 'Feature setting with parameters is empty even the setting is active!'
        juloLog.error(
            {
                'message': error_message,
                'feature_name': FeatureNameConst.KTP_OCR_THRESHOLD_VALUE,
                'application_id': application_id,
            }
        )
        raise JuloException(error_message)

    juloLog.info(
        {
            'message': 'success getting configuration',
            'application_id': application_id,
            'feature_name': FeatureNameConst.KTP_OCR_THRESHOLD_VALUE,
            'parameters': str(setting.parameters),
        }
    )

    if return_parameters:
        return setting.parameters

    return setting


def store_image_and_process_ocr(ocr_process: OCRProcess, image_metadata):
    from juloserver.ocr.tasks import upload_ktp_image_and_trigger_ocr

    # upload image on async task
    image = ocr_process.store_ktp_image(image_metadata=image_metadata, is_upload_image=False)
    ocr_image_result_id, can_process, validation_results = ocr_process.store_image_result(image.id)
    image_response = {
        'image_id': image.id,
    }

    is_feature_active = False
    process_ocr = False
    feature_setting_params = get_threshold_ocr_setting(application_id=ocr_process.application_id)
    if feature_setting_params:
        is_feature_active = True
        process_ocr = can_process

    logger.info(
        'store_image_and_process_ocr_triggering_ocr_process'
        '|image_id={}, process_ocr={}'.format(image.id, process_ocr)
    )
    upload_ktp_image_and_trigger_ocr.delay(
        image.id,
        process_ocr,
        thumbnail=True,
        deleted_if_last_image=False,
        ocr_params=feature_setting_params,
    )

    return is_feature_active, can_process, ocr_image_result_id, image_response, validation_results


def process_opencv(raw_ktp_image, ktp_image, application, retries):
    config = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.NEW_OPENCV_KTP, is_active=True
    ).last()
    open_cv_client = OpenCVProcess(raw_ktp_image, ktp_image, application.id, retries, config)
    validated_ktp_image, is_valid, param, early_return_res = open_cv_client.initiate_open_cv()

    if early_return_res:
        if 'error' in early_return_res:
            return OCRAPIResponseStatus.FAIL, early_return_res, None, validated_ktp_image, []
        else:
            return OCRAPIResponseStatus.SUCCESS, early_return_res, None, validated_ktp_image, []

    try:
        opencv_data = param.get('opencv_data', {})
        threshold = param.get('threshold', {})
        coordinates = param.get('coordinates', {})
    except (ValueError, AttributeError):
        logger.exception('process_opencv_invalid_params|param={}'.format(param))
        return OCRAPIResponseStatus.FAIL, 'process failed', None, []

    if not opencv_data or not threshold:
        return OCRAPIResponseStatus.FAIL, 'process failed', None, []

    opencv_data_serializer = OpenCVDataSerializer(data=opencv_data)
    if not opencv_data_serializer.is_valid():
        return OCRAPIResponseStatus.FAIL, 'process failed', None, []

    retries_left = int(open_cv_client.config.parameters['number_of_tries']) - retries

    return (
        OCRAPIResponseStatus.SUCCESS,
        early_return_res,
        retries_left,
        validated_ktp_image,
        [opencv_data, threshold, coordinates],
    )


def trigger_new_ocr_process(ktp_image_id, ocr_params):
    image = Image.objects.get(id=ktp_image_id)
    image_url = image.image_url
    application = (
        Application.objects.filter(id=image.image_source).values('id', 'application_xid').last()
    )
    unique_id = application.get('application_xid')
    if not application or not unique_id:
        raise JuloException(
            'trigger_new_ocr_process_application_not_found'
            '|application_id={}, image_id={}, unique_id={}'.format(
                image.image_source, image.id, unique_id
            )
        )

    ocr_client = get_ocr_client()
    ocr_params['ktp_url'] = image_url
    ktp_ocr_result = OcrKtpResult.objects.create(application_id=application.get('id'))
    try:
        result = ocr_client.submit_ktp_ocr(ocr_params, unique_id)
    except OCRBadRequestException as e:
        logger.error(
            'trigger_new_ocr_process_bad_request|image_id={}, error={}'.format(ktp_image_id, str(e))
        )

        return None

    ktp_ocr_result = store_ktp_ocr_result(ktp_ocr_result, result['data']['results'])
    storing_meta_data_ocr_ktp(ocr_ktp_result=ktp_ocr_result, response=result)

    return ktp_ocr_result


def store_ktp_ocr_result(ktp_ocr_result: OcrKtpResult, result):

    data = process_clean_data_from_raw_response(result)
    if not data:
        return ktp_ocr_result

    ktp_ocr_result.update_safely(refresh=False, **data)

    return ktp_ocr_result


def process_clean_data_from_raw_response(result):

    raw_date_of_birth = result.get('date_of_birth', {}).get('value')
    raw_date_of_birth = clean_string_from_special_chars(raw_date_of_birth)
    date_of_birth = None
    if raw_date_of_birth:
        try:
            date_object = datetime.strptime(raw_date_of_birth, "%d-%m-%Y")
            # Format the datetime object into "YYYY-MM-DD" format
            date_of_birth = date_object.strftime("%Y-%m-%d")
        except Exception as e:
            logger.error(
                'store_ktp_ocr_result_wrong_dob_format|dob={}, error={}'.format(
                    raw_date_of_birth, str(e)
                )
            )
            date_of_birth = None

    data_to_update = {
        'religion': result.get('religion', {}).get('value'),
        'address': result.get('address', {}).get('value'),
        'blood_group': result.get('blood_group', {}).get('value'),
        'gender': result.get('gender', {}).get('value'),
        'district': result.get('district', {}).get('value'),
        'nik': result.get('nik', {}).get('value'),
        'fullname': result.get('fullname', {}).get('value'),
        'province': result.get('province', {}).get('value'),
        'city': result.get('city', {}).get('value'),
        'place_of_birth': result.get('place_of_birth', {}).get('value'),
        'date_of_birth': date_of_birth,
        'rt_rw': result.get('rt_rw', {}).get('value'),
        'administrative_village': result.get('administrative_village', {}).get('value'),
        'marital_status': result.get('marital_status', {}).get('value'),
        'job': result.get('job', {}).get('value'),
        'nationality': result.get('nationality', {}).get('value'),
        'valid_until': result.get('valid_until', {}).get('value'),
    }

    clean_data = clean_data_ocr_from_original(data_to_update)
    serializer = KtpOCRResultSerializer(clean_data)

    return serializer.data


def process_new_ktp_ocr_for_application(application, raw_ktp_image, ktp_image, image_metadata):
    last_ocr_result = OCRImageResult.objects.filter(application_id=application.id).last()
    last_retries = 0 if not last_ocr_result else last_ocr_result.opencv_data['number_of_retries']
    status, early_return, retries_left, validated_ktp_image, opencv_processed_data = process_opencv(
        raw_ktp_image, ktp_image, application, last_retries + 1
    )
    if early_return:
        return status, early_return

    pre_ocr_process = OCRProcess(
        application.id, validated_ktp_image, raw_ktp_image, opencv_processed_data
    )
    (
        is_ocr_active,
        can_process,
        ocr_image_result_id,
        image_response,
        validation_results,
    ) = store_image_and_process_ocr(pre_ocr_process, image_metadata)

    result = {
        'retries_left': retries_left,
        'validation_results': validation_results,
        'image': image_response,
        'validation_success': False if validation_results else True,
        'ocr_success': True if can_process else False,
        'is_open_cv_active': True,
        'is_ocr_active': is_ocr_active,
    }

    return OCRAPIResponseStatus.SUCCESS, result


@sentry_client.capture_exceptions
def stored_and_check_experiment_data(data, customer):

    group_name, customer_id_growthbook = None, None

    customer_id = customer.id if customer else None
    experiment = ExperimentSetting.objects.filter(code=ExperimentConst.KTP_OCR_EXPERIMENT).last()
    if not experiment:
        error_message = 'Experiment Setting {} is not found'.format(
            ExperimentConst.KTP_OCR_EXPERIMENT
        )
        logger.warning(
            {
                'message': error_message,
                'customer_id': customer_id,
            }
        )
        raise OCRKTPExperimentException(error_message)

    if not customer_id:
        error_message = 'Invalid Request customer id is empty'
        logger.warning(
            {
                'message': error_message,
                'experiment_setting': ExperimentConst.KTP_OCR_EXPERIMENT,
                'customer_id': customer_id,
            }
        )
        raise OCRKTPExperimentException(error_message)

    data_result = data.get('result', None)
    if data_result:
        # get group name data
        group_name = data_result.get(OCRKTPExperimentConst.KEY_GROUP_NAME, None)

        # remove if have double quotes
        group_name = group_name.replace('"', '')

        # get has value id
        customer_id_growthbook = data_result.get(OCRKTPExperimentConst.KEY_CUSTOMER_ID, None)

    if not group_name or str(customer_id_growthbook) != str(customer_id):
        error_message = 'Invalid group name or customer_id from Growthbook'
        logger.warning(
            {
                'message': error_message,
                'experiment_setting': ExperimentConst.KTP_OCR_EXPERIMENT,
                'customer_id': customer_id,
                'group_name': group_name,
                'customer_id_growthbook': customer_id_growthbook,
            }
        )
        raise OCRKTPExperimentException(error_message)

    application = customer.application_set.last()
    experiment_group = ExperimentGroup.objects.filter(
        application=application,
        experiment_setting=experiment,
    ).exists()
    if not experiment_group:
        logger.info(
            {
                'message': 'trying insert to table ExperimentGroup',
                'customer_id': customer_id,
                'group_name': group_name,
                'experiment': ExperimentConst.KTP_OCR_EXPERIMENT,
            }
        )
        ExperimentGroup.objects.create(
            experiment_setting=experiment,
            application=application,
            customer=customer,
            source=OCRKTPExperimentConst.GROWTHBOOK,
            group=group_name,
        )

    return True


def storing_meta_data_ocr_ktp(ocr_ktp_result: OcrKtpResult, response) -> bool:

    ocr_meta_data_attribute = OcrKtpMetaDataAttribute.objects.all()
    if not ocr_meta_data_attribute or not response:
        logger.error(
            {
                'message': 'Invalid process is empty ocr_meta_data_attribute or response',
            }
        )
        return False

    response_data = response.get('data', None)
    if not response_data:
        logger.error(
            {
                'message': 'Invalid process is empty response data',
                'ocr_ktp_result': ocr_ktp_result.id,
            }
        )
        return False

    application_xid = response_data.get('unique_id')
    application = Application.objects.filter(application_xid=application_xid).last()
    if not application:
        logger.error(
            {
                'message': 'Invalid process application is not found',
                'ocr_ktp_result': ocr_ktp_result.id,
            }
        )
        return False

    with transaction.atomic(using='onboarding_db'):

        ocr_ktp_meta_data = OcrKtpMetaData.objects.create(
            application_id=application.id,
            ocr_ktp_result_id=ocr_ktp_result.id,
            request_id=response_data.get('request_id', None),
            fill_rate=response_data.get('fill_rate', None),
            vendor_fill_rate=response_data.get('vendor_fill_rate', None),
        )

        for item_attribute in ocr_meta_data_attribute:
            values = response_data['results'][item_attribute.attribute_name]
            OcrKtpMetaDataValue.objects.create(
                ocr_ktp_meta_data=ocr_ktp_meta_data,
                ocr_ktp_meta_data_attribute=item_attribute,
                threshold_value=values.get('threshold_value', None),
                confidence_value=values.get('vendor_confidence_value', None),
                existed_in_raw=values.get('existed_in_raw', False),
                threshold_passed=values.get('threshold_passed', False),
            )

    logger.info(
        {
            'message': 'Storing meta data OCR KTP',
            'ocr_ktp_result': ocr_ktp_result.id,
            'application': application.id,
            'response': str(response),
        }
    )

    return True


def validate_file_name(file):
    filename = file.name
    allowed_extensions = [ext.lstrip('.') for ext in OCRFileUploadConst.ALLOWED_IMAGE_EXTENSIONS]

    # Check if the filename contains only allowed characters
    if not re.match(OCRFileUploadConst.ALLOWED_CHARACTER_PATTERN, filename):
        raise ValidationError("Filename contains invalid characters")

    # Check if the file extension is allowed
    ext = filename.split('.')[-1].lower()
    if ext not in allowed_extensions:
        raise ValidationError("Unsupported file type: {}".format(ext))

    return file


def similarity_value(
    list_values: [], value_check, threshold, return_upper_text=True, return_original=True
):

    temp_data = []
    ratio_selection = []
    for item_target in list_values:
        ratio = ratio_of_similarity(item_target, value_check)
        if ratio >= threshold:
            list_of_ratio = {'value': item_target, 'ratio': ratio}
            temp_data.append(list_of_ratio)
            ratio_selection.append(ratio)

    if len(ratio_selection) == 0 or len(temp_data) == 0:
        # return default result
        return value_check if return_original else None

    high_ratio = max(ratio_selection)
    value = getting_value_from_ratio(high_ratio, temp_data)
    if not value:
        logger.info(
            {
                'message': 'process similarity value based on ratio',
                'ratio_selection': ratio_selection,
                'temp_data': temp_data,
                'threshold': threshold,
                'value': value,
            }
        )
        # if value is none back to default value if return_original = True
        return value_check if return_original else None

    if return_upper_text:
        value = str(value).upper()

    return value


def getting_value_from_ratio(target_ratio, data):
    for item in data:
        if target_ratio == item['ratio']:
            return item['value']

    return None


def get_config_similarity():

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SIMILARITY_CHECK_APPLICATION_DATA,
        is_active=True,
    ).last()

    if not setting:
        return False, None

    return True, setting.parameters


def clean_data_ocr_from_original(raw_data):

    if not raw_data:
        return raw_data

    for field in raw_data:
        raw_data[field] = clean_string_from_special_chars(raw_data[field])

    return raw_data
