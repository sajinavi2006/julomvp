import logging
import datetime
from io import BytesIO
import operator
import requests
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from PIL import Image as PILImage
from typing import Dict, Any, Union, List
from urllib.parse import urlparse

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.application_flow.constants import ApplicationRiskyDecisions
from juloserver.application_flow.models import (
    ApplicationRiskyCheck,
    ApplicationRiskyDecision,
)
from juloserver.face_recognition.clients import (
    get_face_collection_service,
    get_face_recognition_service,
    get_face_recognition_service_v1_patch,
)
from juloserver.face_recognition.constants import (
    ImageType,
    FaceMatchingCheckConst,
    StoreFraudFaceConst,
)
from juloserver.face_recognition.models import (
    AwsRecogResponse,
    FaceCollection,
    FaceImageResult,
    FaceRecommenderResult,
    FaceSearchProcess,
    FaceSearchResult,
    IndexedFace,
    FraudFaceSearchProcess,
    FraudFaceRecommenderResult,
    FraudFaceSearchResult,
    IndexedFaceFraud,
    FaceMatchingCheck,
    FaceMatchingResults,
    FaceMatchingResult,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    AddressGeolocation,
    Application,
    Customer,
    Device,
    FeatureSetting,
    Image,
    ImageMetadata,
)
from juloserver.julo.utils import ImageUtil
from juloserver.pii_vault.constants import PiiSource
from juloserver.portal.object.app_status.utils import ExtJsonSerializer
from django.utils import timezone


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class CheckFaceSimilarity(object):
    def __init__(self, application):
        self.application = application
        self.face_recognition_config = self.get_face_recognition_config()
        self.fraud_face_match_config = self.get_fraud_face_match_config()

    def check_face_similarity(self):
        from juloserver.application_flow.tasks import application_tag_tracking_task

        if not self.face_recognition_config:
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_similar_face', 0
            )
            return False

        self.face_image_result = FaceImageResult.objects.filter(application=self.application).last()

        if not self.face_image_result:
            return False

        result = False
        if self.face_recognition_config:
            self.face_search_process = FaceSearchProcess.objects.filter(
                application=self.application
            ).last()

            if self.face_image_result.passed_filter and not self.face_search_process:
                self.face_search_process = FaceSearchProcess.objects.create(
                    application=self.application, status='pending'
                )
                result = self.face_search()

            if self.fraud_face_match_config:
                self.fraud_face_search_process = FraudFaceSearchProcess.objects.filter(
                    application=self.application
                ).last()

                if self.face_image_result.passed_filter and not self.fraud_face_search_process:
                    self.fraud_face_search_process = FraudFaceSearchProcess.objects.create(
                        application=self.application, status='pending'
                    )
                    result = self.fraud_face_search()
            else:
                application_tag_tracking_task(
                    self.application.id, None, None, None, 'is_fraud_face_match', 0
                )
                return False
        return result

    def face_search(self):
        from juloserver.application_flow.tasks import application_tag_tracking_task
        from juloserver.face_recognition.tasks import (
            store_aws_response_data,
            store_matched_faces_data,
        )

        if self.face_search_process.status != 'pending':
            return False

        parameters = self.face_recognition_config.parameters

        face_recognition_service = get_face_recognition_service(
            parameters['aws_settings'], parameters['face_recognition_settings']
        )

        face_collection = FaceCollection.objects.filter(
            face_collection_name='face_collection_x105', status='active'
        ).last()

        image = Image.objects.get_or_none(pk=self.face_image_result.image.id)
        if not image:
            self.face_search_process.update_safely(status='not_found')
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_similar_face', -1
            )
            return False

        image.refresh_from_db()

        if not image.image_url:
            self.face_search_process.update_safely(status='not_found')
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_similar_face', -1
            )
            return False

        response = requests.get(image.image_url, stream=True)
        # image_bytes = convert_image_to_bytes(response.raw)
        image_resize_handler = ImageUtil(response.raw)
        try:
            # the limit in face recognition service is 5242880, with the tolerance is 5,
            # so we can set the target file size around 4900000
            image_bytes = image_resize_handler.resize_image(
                4900000, 5, ImageUtil.ResizeResponseType.BYTES, 10
            )
        except Exception as e:
            sentry_client.captureException()
            raise e

        try:
            face_search = face_recognition_service.search_face(
                image_bytes, face_collection.face_collection_name
            )
        except Exception as err:
            sentry_client.captureException()
            logger.exception('face_recognition_face_search_error|err={}'.format(err))
            self.face_search_process.update_safely(status='not_found')
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_similar_face', -1
            )
            return False

        service_response, service_latency, service_version = face_search.get_service_response()
        service_configs = face_search.get_configs()

        task_param = [image.id, face_search.get_client_response(), 'image_search']
        store_aws_response_data.delay(*task_param)

        if not service_response["matched_faces"]:
            self.face_search_process.update_safely(status='not_found')
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_similar_face', -1
            )
            return True

        matched_image_counter = 0
        for face_matched in service_response['matched_faces']:
            matched_image = Image.objects.get_or_none(pk=face_matched['image_id'])
            if matched_image:
                matched_application = Application.objects.get_or_none(pk=matched_image.image_source)
                if matched_application.customer_id != self.application.customer_id:
                    matched_image_counter += 1

        if matched_image_counter == 0:
            self.face_search_process.update_safely(status='not_found')
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_similar_face', -1
            )
            return True

        decision_name = ApplicationRiskyDecisions.NO_DV_BYPASS
        decision = ApplicationRiskyDecision.objects.get(decision_name=decision_name)

        risky_check = ApplicationRiskyCheck.objects.filter(application=self.application).last()
        if risky_check:
            update_data = {'is_similar_face_suspicious': True}
            if not self.application.is_julo_starter():
                update_data['decision'] = decision

            risky_check.update_safely(**update_data)

        task_param = [
            service_response,
            service_latency,
            service_configs,
            self.face_search_process.id,
            face_collection.id,
            self.face_image_result.id,
            self.application.customer_id,
        ]
        store_matched_faces_data.delay(*task_param)

        application_tag_tracking_task(self.application.id, None, None, None, 'is_similar_face', 1)

        return True

    def get_face_recognition_config(self):
        face_recognition = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.FACE_RECOGNITION, is_active=True
        ).last()

        return face_recognition

    def get_fraud_face_match_config(self):
        fraud_face_match = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH, is_active=True
        ).last()

        return fraud_face_match

    def fraud_face_search(self):
        from juloserver.application_flow.tasks import application_tag_tracking_task
        from juloserver.face_recognition.tasks import (
            store_aws_response_data,
            store_matched_fraud_faces_data,
        )

        if self.fraud_face_search_process.status != 'pending':
            return False

        parameters = self.face_recognition_config.parameters

        face_recognition_service = get_face_recognition_service(
            parameters['aws_settings'], parameters['face_recognition_settings']
        )

        face_collection = FaceCollection.objects.get(
            face_collection_name='face_collection_fraud', status='active'
        )

        image = Image.objects.get_or_none(pk=self.face_image_result.image.id)
        if not image:
            self.fraud_face_search_process.update_safely(status='not_found')
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_fraud_face_match', -1
            )
            return False

        image.refresh_from_db()

        if not image.image_url:
            self.fraud_face_search_process.update_safely(status='not_found')
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_fraud_face_match', -1
            )
            return False

        response = requests.get(image.image_url, stream=True)
        # image_bytes = convert_image_to_bytes(response.raw)
        image_resize_handler = ImageUtil(response.raw)
        try:
            # the limit in face recognition service is 5242880, with the tolerance is 5,
            # so we can set the target file size around 4900000
            image_bytes = image_resize_handler.resize_image(
                4900000, 5, ImageUtil.ResizeResponseType.BYTES, 10
            )
        except Exception as e:
            sentry_client.captureException()
            raise e

        try:
            face_search = face_recognition_service.search_face(
                image_bytes, face_collection.face_collection_name
            )
        except Exception as err:
            sentry_client.captureException()
            logger.exception(
                {'task': 'fraud_face_search', 'exception': 'fraud face search error', 'error': err}
            )
            self.fraud_face_search_process.update_safely(status='exception')
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_fraud_face_match', -1
            )
            return False

        service_response, service_latency, service_version = face_search.get_service_response()
        service_configs = face_search.get_configs()

        task_param = [image.id, face_search.get_client_response(), 'image_search']
        store_aws_response_data.delay(*task_param)

        if not service_response["matched_faces"]:
            self.fraud_face_search_process.update_safely(status='not_found')
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_fraud_face_match', -1
            )
            return True

        matched_image_counter = 0
        for face_matched in service_response['matched_faces']:
            logical_operator = self.fraud_face_match_config.parameters['fraud_face_match_settings'][
                'logical_operator'
            ]
            comparison_functions = {
                "<=": operator.le,
                "<": operator.lt,
                ">=": operator.ge,
                ">": operator.gt,
            }
            result = comparison_functions.get(logical_operator, lambda x, y: False)(
                face_matched['similarity'],
                self.fraud_face_match_config.parameters['fraud_face_match_settings'][
                    'similarity_threshold'
                ],
            )
            if result:
                matched_image = Image.objects.get_or_none(pk=face_matched['image_id'])
                if matched_image:
                    matched_application = Application.objects.get_or_none(
                        pk=matched_image.image_source
                    )
                    if matched_application.customer_id != self.application.customer_id:
                        matched_image_counter += 1
            else:
                service_response['matched_faces'].remove(face_matched)

            logger.info(
                {
                    'action': 'fraud_face_search',
                    'similarity threshold result': result,
                    'matched_face': service_response['matched_faces'],
                    'message': 'Similarity score threshold check.',
                }
            )

        if matched_image_counter == 0:
            self.fraud_face_search_process.update_safely(status='not_found')
            application_tag_tracking_task(
                self.application.id, None, None, None, 'is_fraud_face_match', -1
            )
            return True

        decision_name = ApplicationRiskyDecisions.NO_DV_BYPASS
        decision = ApplicationRiskyDecision.objects.get(decision_name=decision_name)

        risky_check = ApplicationRiskyCheck.objects.filter(application=self.application).last()
        if risky_check:
            update_data = {'is_fraud_face_suspicious': True}
            if not self.application.is_julo_starter():
                update_data['decision'] = decision

            risky_check.update_safely(**update_data)

        task_param = [
            service_response,
            service_latency,
            service_configs,
            self.fraud_face_search_process.id,
            face_collection.id,
            self.face_image_result.id,
            self.application.customer_id,
            self.application.id,
        ]
        store_matched_fraud_faces_data.delay(*task_param)

        application_tag_tracking_task(
            self.application.id, None, None, None, 'is_fraud_face_match', 1
        )

        return True


def get_face_search_status(application_id):
    from juloserver.application_flow.tasks import application_tag_tracking_task

    application = Application.objects.get_or_none(pk=application_id)
    if application.is_grab():
        return "skipped"

    face_recognition = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_RECOGNITION, is_active=True
    ).last()

    if not face_recognition:
        return "inactive"

    face_image_result = FaceImageResult.objects.filter(application=application_id).last()

    if not face_image_result:
        application_tag_tracking_task(application.id, None, None, None, 'is_similar_face', 0)
        return "skipped"

    if not face_image_result.passed_filter:
        application_tag_tracking_task(application.id, None, None, None, 'is_similar_face', 0)
        return "skipped"

    face_search_process = FaceSearchProcess.objects.filter(application=application_id).last()

    if not face_search_process:
        application_tag_tracking_task(application.id, None, None, None, 'is_similar_face', 0)
        return "skipped"

    face_recommender_result = FaceRecommenderResult.objects.filter(
        application_id=application_id
    ).last()

    if face_recommender_result:
        return "checked"

    return face_search_process.status


def submit_face_recommender_evaluation(application, recommendation):
    data_context = None
    if "data_context" in recommendation:
        data_context = recommendation['data_context']

    is_match = False
    image = None
    match_application_id = None
    apply_date = None
    geo_location_distance = None
    address = None
    provinsi = None
    kabupaten = None
    kecamatan = None
    kelurahan = None
    nik = None
    email = None
    full_name = None
    birth_place = None
    dob = None
    bank_name = None
    bank_account_name = None
    bank_account_number = None
    device_name = None
    android_id = None
    face_search_result = None
    device = None

    if recommendation['is_match']:
        is_match = recommendation['is_match']

    if recommendation['image']:
        image = recommendation['image']

    if recommendation['application']:
        match_application_id = recommendation['application']

    if recommendation['apply_date']:
        apply_date = recommendation['apply_date']

    if recommendation['geolocation']:
        geo_location_distance = recommendation['geolocation']

    if recommendation['address']:
        address = recommendation['address']

    if recommendation['provinsi']:
        provinsi = recommendation['provinsi']

    if recommendation['kabupaten']:
        kabupaten = recommendation['kabupaten']

    if recommendation['kecamatan']:
        kecamatan = recommendation['kecamatan']

    if recommendation['kelurahan']:
        kelurahan = recommendation['kelurahan']

    if recommendation['nik']:
        nik = recommendation['nik']

    if recommendation['email']:
        email = recommendation['email']

    if recommendation['full_name']:
        full_name = recommendation['full_name']

    if recommendation['birth_place']:
        birth_place = recommendation['birth_place']

    if recommendation['dob']:
        dob = recommendation['dob'].strip()

    if recommendation['bank_name']:
        bank_name = recommendation['bank_name']

    if recommendation['bank_account_name']:
        bank_account_name = recommendation['bank_account_name']

    if recommendation['bank_account_number']:
        bank_account_number = recommendation['bank_account_number']

    if recommendation['device_name']:
        device_name = recommendation['device_name']

    if recommendation['android_id']:
        android_id = recommendation['android_id']

    if data_context == 'similar_face':
        face_recognition = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.FACE_RECOGNITION, is_active=True
        ).last()

        if not face_recognition:
            return False

        if image:
            face_search_result = FaceSearchResult.objects.filter(matched_face_image_id=image).last()

        if android_id:
            device = Device.objects.filter(android_id=android_id).last()

        FaceRecommenderResult.objects.create(
            face_search_result=face_search_result,
            application=application,
            is_match=is_match,
            match_application_id=match_application_id,
            apply_date=apply_date,
            geo_location_distance=geo_location_distance,
            address=address,
            provinsi=provinsi,
            kabupaten=kabupaten,
            kecamatan=kecamatan,
            kelurahan=kelurahan,
            nik=nik,
            email=email,
            full_name=full_name,
            birth_place=birth_place,
            dob=dob,
            bank_name=bank_name,
            bank_account_name=bank_account_name,
            bank_account_number=bank_account_number,
            device=device,
            device_name=device_name,
        )

        return True
    elif data_context == 'fraud_face':
        fraud_face_match = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH, is_active=True
        ).last()

        if not fraud_face_match:
            return False

        if image:
            fraud_face_search_result = FraudFaceSearchResult.objects.filter(
                matched_face_image_id=image
            ).last()

        if android_id:
            device = Device.objects.filter(android_id=android_id).last()

        FraudFaceRecommenderResult.objects.create(
            fraud_face_search_result=fraud_face_search_result,
            application=application,
            is_match=is_match,
            match_application_id=match_application_id,
            apply_date=apply_date,
            geo_location_distance=geo_location_distance,
            address=address,
            provinsi=provinsi,
            kabupaten=kabupaten,
            kecamatan=kecamatan,
            kelurahan=kelurahan,
            nik=nik,
            email=email,
            full_name=full_name,
            birth_place=birth_place,
            dob=dob,
            bank_name=bank_name,
            bank_account_name=bank_account_name,
            bank_account_number=bank_account_number,
            device=device,
            device_name=device_name,
        )

        return True


def get_similar_faces_data(application):
    similar_faces_data = {}

    face_recognition = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_RECOGNITION, is_active=True
    ).last()

    if not face_recognition:
        return similar_faces_data

    similar_faces_data['code'] = '01'
    similar_faces_data['result'] = 'successful!'

    if application:
        detokenized_application = detokenize_pii_antifraud_data(
            PiiSource.APPLICATION, [application]
        )[0]
        similar_faces_data['customer_application_id'] = application.id
        similar_faces_data['customer_cdate'] = application.cdate
        similar_faces_data['customer_address_street_num'] = application.address_street_num
        similar_faces_data['customer_address_provinsi'] = application.address_provinsi
        similar_faces_data['customer_address_kabupaten'] = application.address_kabupaten
        similar_faces_data['customer_address_kecamatan'] = application.address_kecamatan
        similar_faces_data['customer_address_kelurahan'] = application.address_kelurahan
        similar_faces_data['customer_ktp'] = detokenized_application.ktp
        similar_faces_data['customer_email'] = detokenized_application.email
        similar_faces_data['customer_fullname'] = detokenized_application.fullname
        similar_faces_data['customer_birth_place'] = application.birth_place
        similar_faces_data['customer_dob'] = application.dob
        similar_faces_data['customer_bank_name'] = application.bank_name
        similar_faces_data['customer_bank_account_name'] = application.name_in_bank
        similar_faces_data['customer_bank_account_number'] = application.bank_account_number

    data_geo_customer = AddressGeolocation.objects.filter(application_id=application).last()
    if data_geo_customer:
        similar_faces_data['customer_geo_app'] = data_geo_customer.application_id
        similar_faces_data['customer_geo_data_lat'] = data_geo_customer.latitude
        similar_faces_data['customer_geo_data_lon'] = data_geo_customer.longitude

    data_device_customer = Device.objects.get_or_none(pk=application.device.id)
    if data_device_customer:
        similar_faces_data['customer_android_id'] = data_device_customer.android_id
        similar_faces_data['customer_device_name'] = data_device_customer.device_model_name

    image_customer = Image.objects.filter(
        image_source=application.id, image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
    )
    if image_customer:
        results_customer = ExtJsonSerializer().serialize(
            image_customer, props=['image_url', 'image_ext'], fields=('image_type',)
        )
        similar_faces_data['customer_image'] = results_customer

    parameters = face_recognition.parameters

    matched_faces_limit = parameters["max_face_matches"]

    search_result = FaceSearchResult.objects.select_related("face_search_process").filter(
        face_search_process__application_id=application
    )[:matched_faces_limit]

    indexed_face = IndexedFace.objects.filter(
        image__in=search_result.values('matched_face_image_id')
    )
    if not indexed_face:
        image_selfie = Image.objects.filter(pk__in=search_result.values('matched_face_image_id'))
        results_matched_selfie = ExtJsonSerializer().serialize(
            image_selfie, props=['image_url', 'image_ext'], fields=('image_source',)
        )
        applications = image_selfie.values('image_source')
    else:
        results_matched_selfie = ExtJsonSerializer().serialize(
            indexed_face,
            props=['image_url', 'image_ext'],
            fields=(
                'application',
                'image',
            ),
        )
        applications = indexed_face.values('application')

    similar_faces_data['matched_selfie'] = results_matched_selfie

    image_matched = Image.objects.filter(
        image_source__in=applications,
        image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ],
        image_type__in=['ktp_self', 'ktp'],
    )
    if image_matched:
        results_matched_ktp = ExtJsonSerializer().serialize(
            image_matched,
            props=['image_url', 'image_ext'],
            fields=(
                'image_type',
                'image_source',
            ),
        )
        similar_faces_data['matched_ktp'] = results_matched_ktp

    image_matched_data = Application.objects.filter(pk__in=applications)
    if image_matched_data:
        results_matched_data = ExtJsonSerializer().serialize(
            image_matched_data,
            props=[''],
            fields=(
                'application_status',
                'cdate',
                'address_street_num',
                'address_provinsi',
                'address_kabupaten',
                'address_kecamatan',
                'address_kelurahan',
                'ktp',
                'email',
                'fullname',
                'birth_place',
                'dob',
                'bank_name',
                'name_in_bank',
                'bank_account_number',
                'device',
            ),
        )
        similar_faces_data['data_matched_image'] = results_matched_data

    data_geo_matched = AddressGeolocation.objects.filter(application_id__in=applications)
    if data_geo_matched:
        results_matched_geo_data = ExtJsonSerializer().serialize(
            data_geo_matched, props=[''], fields=('latitude', 'longitude', 'application')
        )
        similar_faces_data['geo_data_matched_image'] = results_matched_geo_data
    else:
        similar_faces_data['geo_data_matched_image'] = None

    data_device_matched = Device.objects.filter(id__in=image_matched_data.values('device_id'))
    if data_device_matched:
        results_matched_device_data = ExtJsonSerializer().serialize(
            data_device_matched, props=[''], fields=('android_id', 'device_model_name')
        )
        similar_faces_data['device_data_matched_image'] = results_matched_device_data
    else:
        similar_faces_data['device_data_matched_image'] = None

    return similar_faces_data


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


def check_image_quality_and_upload(selfie_image, application, customer, image_metadata=None):
    from juloserver.face_recognition.tasks import (
        store_aws_response_data,
        upload_face_recognition_image,
    )

    if isinstance(selfie_image, TemporaryUploadedFile):
        selfie_image = convert_temporary_to_inmem_file(selfie_image)

    face_image_result_count = FaceImageResult.objects.filter(application=application).count()
    if face_image_result_count > 0:
        face_image_result_passed = FaceImageResult.objects.filter(application=application).last()

        if face_image_result_passed.passed_filter:
            return True, "Your application already have an uploaded passed image."

    if application.is_grab():
        image = upload_selfie_image(selfie_image, application.id, 'selfie', metadata=image_metadata)
        if selfie_image:
            upload_selfie_image(selfie_image, application.id, 'crop_selfie')
        return True, image.id

    face_recognition = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_RECOGNITION, is_active=True
    ).last()

    if not face_recognition:
        image = upload_selfie_image(
            selfie_image, application.id, ImageType.SELFIE, metadata=image_metadata
        )
        if selfie_image:
            upload_selfie_image(selfie_image, application.id, ImageType.CROP_SELFIE)
        return True, image.id

    parameters = face_recognition.parameters
    max_retry_count = parameters['max_retry_count']

    retries_left = max_retry_count - face_image_result_count
    if retries_left == 0:
        image = upload_selfie_image(
            selfie_image, application.id, ImageType.SELFIE, metadata=image_metadata
        )
        if selfie_image:
            upload_selfie_image(selfie_image, application.id, ImageType.CROP_SELFIE)
        return True, image.id

    # image = convert_image_to_bytes(selfie_image)
    image_resize_handler = ImageUtil(selfie_image)
    try:
        # the limit in face recognition service is 5242880, with the tolerance is 5,
        # so we can set the target file size around 4900000
        image_bytes = image_resize_handler.resize_image(
            4900000, 5, ImageUtil.ResizeResponseType.BYTES, 10
        )
    except Exception:
        sentry_client.captureException()
        return False, ''

    face_recognition_service = get_face_recognition_service(
        parameters['aws_settings'], parameters['face_recognition_settings']
    )
    face_and_quality_response = face_recognition_service.detect_face_and_quality(image_bytes)

    (
        service_response,
        service_latency,
        service_version,
    ) = face_and_quality_response.get_service_response()
    service_configs = face_and_quality_response.get_configs()

    image = upload_selfie_image(
        selfie_image, application.id, ImageType.SELFIE, metadata=image_metadata
    )

    crop_image_bytes = face_and_quality_response.get_image_bytes()

    crop_image = get_image_from_bytes(crop_image_bytes, selfie_image)
    crop_image = upload_selfie_image(crop_image, application.id, ImageType.CROP_SELFIE, False)

    FaceImageResult.objects.create(
        application=application,
        sharpness=service_response['quality']['sharpness'],
        brightness=service_response['quality']['brightness'],
        detected_faces=service_response['detected_faces'],
        passed_filter=service_response['passes_filter'],
        latency=service_latency,
        configs=service_configs,
        image=crop_image,
    )

    task_param = [image.id, face_and_quality_response.get_client_response(), 'image_result']
    store_aws_response_data.delay(*task_param)

    if not service_response['passes_filter']:
        return False, image.id

    face_collection = FaceCollection.objects.filter(
        face_collection_name='face_collection_x105', status='active'
    ).last()

    aws_settings = parameters['aws_settings']

    task_param = [
        crop_image.id,
        face_collection.id,
        application.id,
        customer.id,
        aws_settings,
        False,
    ]

    upload_face_recognition_image.delay(*task_param)

    return True, image.id


def process_indexed_face(image_id, face_collection_id, application_id, customer_id, aws_settings):
    image = Image.objects.get_or_none(pk=image_id)
    face_collection = FaceCollection.objects.get(pk=face_collection_id)

    context = {'collection_name': face_collection.face_collection_name, 'julo_image_id': image.id}

    response = requests.get(image.image_url, stream=True)
    # image_bytes = convert_image_to_bytes(response.raw)
    image_resize_handler = ImageUtil(response.raw)
    try:
        # the limit in face recognition service is 5242880, with the tolerance is 5,
        # so we can set the target file size around 4900000
        image_bytes = image_resize_handler.resize_image(
            4900000, 5, ImageUtil.ResizeResponseType.BYTES, 10
        )
    except Exception as e:
        sentry_client.captureException()
        raise e

    face_collection_service = get_face_collection_service(aws_settings)

    indexed_response = face_collection_service.add_face_to_collection(image_bytes, context)

    indexed_client_response = indexed_response.get_client_response()

    (
        indexed_service_response,
        indexed_latency,
        indexed_version,
    ) = indexed_response.get_service_response()

    AwsRecogResponse.objects.create(
        raw_response=indexed_client_response, raw_response_type='indexed_faces'
    )

    application = Application.objects.get_or_none(pk=application_id)
    customer = Customer.objects.get_or_none(pk=customer_id)
    IndexedFace.objects.create(
        face_collection=face_collection,
        image=image,
        application=application,
        customer=customer,
        collection_face_id=indexed_service_response['collection_face_id'],
        collection_image_id=indexed_service_response['collection_image_id'],
        collection_image_url=image.url,
        match_status=indexed_service_response['match_status'],
        application_status_code=application.status,
        latency=indexed_latency,
    )


def upload_selfie_image(image, application, image_type, oss_upload=True, metadata=None):
    from juloserver.julo.tasks import upload_image

    new_image = Image()
    new_image.image_type = image_type
    new_image.image_source = application
    new_image.save()
    new_image.image.save(new_image.full_image_name(image.name), image)

    if metadata:
        ImageMetadata.objects.create(image_id=new_image.id, application_id=application, **metadata)
    if oss_upload:
        upload_image.apply_async(
            (
                new_image.id,
                False,
                True,
            ),
            queue='high',
            routing_key='high',
        )
    return new_image


def convert_image_to_bytes(selfie_image, image_format='PNG'):
    pil_im = PILImage.open(selfie_image)
    image_bytes_array = BytesIO()
    pil_im.save(image_bytes_array, format=image_format)
    return image_bytes_array.getvalue()


def get_image_from_bytes(image_bytes, image):
    io_file = BytesIO(image_bytes)
    pil_image = PILImage.open(io_file)

    output_file = InMemoryUploadedFile(
        file=io_file,
        field_name=image.field_name,
        name="crop_" + image.name,
        content_type=image.content_type,
        size=pil_image.tell,
        content_type_extra=image.content_type_extra,
        charset=None,
    )
    return output_file


def get_fraud_face_match_status(application_id):
    from juloserver.application_flow.tasks import application_tag_tracking_task

    application = Application.objects.get_or_none(pk=application_id)
    if application.is_grab():
        return "skipped"

    fraud_face_match = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH, is_active=True
    ).last()

    if not fraud_face_match:
        return "inactive"

    face_image_result = FaceImageResult.objects.filter(application=application_id).last()

    if not face_image_result:
        application_tag_tracking_task(application.id, None, None, None, 'is_fraud_face_match', 0)
        return "skipped"

    if not face_image_result.passed_filter:
        application_tag_tracking_task(application.id, None, None, None, 'is_fraud_face_match', 0)
        return "skipped"

    fraud_face_search_process = FraudFaceSearchProcess.objects.filter(
        application=application_id
    ).last()

    if not fraud_face_search_process:
        application_tag_tracking_task(application.id, None, None, None, 'is_fraud_face_match', 0)
        return "skipped"

    fraud_face_recommender_result = FraudFaceRecommenderResult.objects.filter(
        application_id=application_id
    ).last()

    if fraud_face_recommender_result:
        return "checked"

    return fraud_face_search_process.status


def get_similar_fraud_faces_data(application):
    fraud_faces_data = {}

    fraud_face_match = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH, is_active=True
    ).last()

    if not fraud_face_match:
        return fraud_faces_data

    fraud_faces_data['code'] = '01'
    fraud_faces_data['result'] = 'successful!'

    if application:
        detokenized_application = detokenize_pii_antifraud_data(
            PiiSource.APPLICATION, [application]
        )[0]
        fraud_faces_data['customer_application_id'] = application.id
        fraud_faces_data['customer_cdate'] = application.cdate
        fraud_faces_data['customer_address_street_num'] = application.address_street_num
        fraud_faces_data['customer_address_provinsi'] = application.address_provinsi
        fraud_faces_data['customer_address_kabupaten'] = application.address_kabupaten
        fraud_faces_data['customer_address_kecamatan'] = application.address_kecamatan
        fraud_faces_data['customer_address_kelurahan'] = application.address_kelurahan
        fraud_faces_data['customer_ktp'] = detokenized_application.ktp
        fraud_faces_data['customer_email'] = detokenized_application.email
        fraud_faces_data['customer_fullname'] = detokenized_application.fullname
        fraud_faces_data['customer_birth_place'] = application.birth_place
        fraud_faces_data['customer_dob'] = application.dob
        fraud_faces_data['customer_bank_name'] = application.bank_name
        fraud_faces_data['customer_bank_account_name'] = application.name_in_bank
        fraud_faces_data['customer_bank_account_number'] = application.bank_account_number

    data_geo_customer = AddressGeolocation.objects.filter(application_id=application).last()
    if data_geo_customer:
        fraud_faces_data['customer_geo_app'] = data_geo_customer.application_id
        fraud_faces_data['customer_geo_data_lat'] = data_geo_customer.latitude
        fraud_faces_data['customer_geo_data_lon'] = data_geo_customer.longitude

    data_device_customer = Device.objects.get_or_none(pk=application.device.id)
    if data_device_customer:
        fraud_faces_data['customer_android_id'] = data_device_customer.android_id
        fraud_faces_data['customer_device_name'] = data_device_customer.device_model_name

    image_customer = Image.objects.filter(
        image_source=application.id, image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
    )
    if image_customer:
        results_customer = ExtJsonSerializer().serialize(
            image_customer, props=['image_url', 'image_ext'], fields=('image_type',)
        )
        fraud_faces_data['customer_image'] = results_customer

    parameters = fraud_face_match.parameters

    matched_faces_limit = parameters['fraud_face_match_settings']["max_face_matches"]

    fraud_face_search_result = FraudFaceSearchResult.objects.select_related(
        "face_search_process"
    ).filter(face_search_process__application_id=application)[:matched_faces_limit]

    fraud_indexed_face = IndexedFaceFraud.objects.filter(
        image__in=fraud_face_search_result.values('matched_face_image_id')
    )
    if not fraud_indexed_face:
        image_selfie = Image.objects.filter(
            pk__in=fraud_face_search_result.values('matched_face_image_id')
        )
        results_matched_selfie = ExtJsonSerializer().serialize(
            image_selfie, props=['image_url', 'image_ext'], fields=('image_source',)
        )
        applications = image_selfie.values('image_source')
    else:
        results_matched_selfie = ExtJsonSerializer().serialize(
            fraud_indexed_face,
            props=['image_url', 'image_ext'],
            fields=(
                'application',
                'image',
            ),
        )
        applications = fraud_indexed_face.values('application')

    fraud_faces_data['matched_selfie'] = results_matched_selfie

    image_matched = Image.objects.filter(
        image_source__in=applications,
        image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ],
        image_type__in=['ktp_self', 'ktp'],
    )
    if image_matched:
        results_matched_ktp = ExtJsonSerializer().serialize(
            image_matched,
            props=['image_url', 'image_ext'],
            fields=(
                'image_type',
                'image_source',
            ),
        )
        fraud_faces_data['matched_ktp'] = results_matched_ktp

    image_matched_data = Application.objects.filter(pk__in=applications)
    if image_matched_data:
        results_matched_data = ExtJsonSerializer().serialize(
            image_matched_data,
            props=[''],
            fields=(
                'application_status',
                'cdate',
                'address_street_num',
                'address_provinsi',
                'address_kabupaten',
                'address_kecamatan',
                'address_kelurahan',
                'ktp',
                'email',
                'fullname',
                'birth_place',
                'dob',
                'bank_name',
                'name_in_bank',
                'bank_account_number',
                'device',
            ),
        )
        fraud_faces_data['data_matched_image'] = results_matched_data

    data_geo_matched = AddressGeolocation.objects.filter(application_id__in=applications)
    if data_geo_matched:
        results_matched_geo_data = ExtJsonSerializer().serialize(
            data_geo_matched, props=[''], fields=('latitude', 'longitude', 'application')
        )
        fraud_faces_data['geo_data_matched_image'] = results_matched_geo_data
    else:
        fraud_faces_data['geo_data_matched_image'] = None

    data_device_matched = Device.objects.filter(id__in=image_matched_data.values('device_id'))
    if data_device_matched:
        results_matched_device_data = ExtJsonSerializer().serialize(
            data_device_matched, props=[''], fields=('android_id', 'device_model_name')
        )
        fraud_faces_data['device_data_matched_image'] = results_matched_device_data
    else:
        fraud_faces_data['device_data_matched_image'] = None

    return fraud_faces_data


def process_fraud_indexed_face(
    image_id, face_collection_id, application_id, customer_id, aws_settings
):
    image = Image.objects.get(pk=image_id)
    face_collection = FaceCollection.objects.get(pk=face_collection_id)

    context = {'collection_name': face_collection.face_collection_name, 'julo_image_id': image.id}

    response = requests.get(image.image_url, stream=True)
    # image_bytes = convert_image_to_bytes(response.raw)
    image_resize_handler = ImageUtil(response.raw)
    try:
        # the limit in face recognition service is 5242880, with the tolerance is 5,
        # so we can set the target file size around 4900000
        image_bytes = image_resize_handler.resize_image(
            4900000, 5, ImageUtil.ResizeResponseType.BYTES, 10
        )
    except Exception as e:
        sentry_client.captureException()
        raise e

    face_collection_service = get_face_collection_service(aws_settings)

    indexed_response = face_collection_service.add_face_to_collection(image_bytes, context)

    indexed_client_response = indexed_response.get_client_response()

    (
        indexed_service_response,
        indexed_latency,
        indexed_version,
    ) = indexed_response.get_service_response()

    AwsRecogResponse.objects.create(
        raw_response=indexed_client_response, raw_response_type='fraud_indexed_faces'
    )

    application = Application.objects.get_or_none(pk=application_id)
    customer = Customer.objects.get_or_none(pk=customer_id)
    logger.info(
        {
            'action': 'process_fraud_indexed_face',
            'data': {
                'indexed_service_response': indexed_service_response,
                'image': image,
                'application': application,
                'face_collection': face_collection,
            },
        }
    )
    IndexedFaceFraud.objects.create(
        face_collection=face_collection,
        image=image,
        application=application,
        customer=customer,
        collection_face_id=indexed_service_response['collection_face_id'],
        collection_image_id=indexed_service_response['collection_image_id'],
        collection_image_url=image.url,
        match_status=indexed_service_response['match_status'],
        application_status_code=application.status,
        latency=indexed_latency,
    )


def get_similar_and_fraud_face_time_limit(application_id):
    date_now = timezone.now()
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SIMILAR_AND_FRAUD_FACE_TIME_LIMIT, is_active=True
    ).last()

    if not feature_setting:
        return None

    face_search_process = FaceSearchProcess.objects.filter(application=application_id).last()
    fraud_face_search_process = FraudFaceSearchProcess.objects.filter(
        application=application_id
    ).last()

    face_search_duration = datetime.timedelta()
    fraud_face_search_duration = datetime.timedelta()
    if face_search_process:
        face_search_duration = date_now - face_search_process.udate

    if fraud_face_search_process:
        fraud_face_search_duration = date_now - fraud_face_search_process.udate

    difference = max(face_search_duration, fraud_face_search_duration)

    total_seconds = difference.total_seconds()
    face_search_process_date_in_minutes = total_seconds / 60
    if face_search_process_date_in_minutes == 0:
        return 0
    pending_status_wait_time_limit_in_minutes = feature_setting.parameters[
        'pending_status_wait_time_limit_in_minutes'
    ]

    similar_and_fraud_face_time_limit = (
        pending_status_wait_time_limit_in_minutes - face_search_process_date_in_minutes
    )
    if similar_and_fraud_face_time_limit < 0:
        return 0
    else:
        return similar_and_fraud_face_time_limit


def do_all_face_matching(
    application_id: int,
) -> List[bool]:
    """
    This function is part of the fraud mitigation attempt
        where we compare various faces to flag applications,
        aimed to help agents document verification process.
    It triggers ALL of the face matching result for a given application ID.

    Parameters:
        application_id (int): The ID of the application.

    Returns:
        List[bool]: True if the face matching process is successful, False otherwise.
    """

    face_matching_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_MATCHING_CHECK, is_active=True
    ).last()
    if not face_matching_fs:
        return True, True

    selfie_x_ktp = check_selfie_to_ktp_matching(application_id, face_matching_fs)
    selfie_x_liveness = check_selfie_to_liveness_matching(application_id, face_matching_fs)

    return selfie_x_ktp, selfie_x_liveness


def do_face_matching(
    application_id: int,
    process: FaceMatchingCheckConst.Process,
) -> bool:
    """
    This function is part of the fraud mitigation attempt
        where we compare various faces to flag applications,
        aimed to help agents document verification process.
    It triggers the face matching result for a given application ID, ONLY for a given proccess.

    Parameters:
        application_id (int): The ID of the application.
        process (FaceMatchingCheckConst.Process): The process to be checked.

    Returns:
        bool: True if the face matching process is successful, False otherwise.
    """

    face_matching_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_MATCHING_CHECK, is_active=True
    ).last()
    if not face_matching_fs:
        return True

    if process == FaceMatchingCheckConst.Process.selfie_x_ktp:
        return check_selfie_to_ktp_matching(application_id, face_matching_fs)
    elif process == FaceMatchingCheckConst.Process.selfie_x_liveness:
        return check_selfie_to_liveness_matching(application_id, face_matching_fs)

    return True


def check_selfie_to_ktp_matching(
    application_id: int,
    face_matching_fs: FeatureSetting,
) -> bool:
    """
    Check the similarity between the Selfie image and the KTP image for a given application.

    Args:
        application_id (int): The ID of the application.
        face_matching_fs (FeatureSetting): The feature setting for face similarity.

    Returns:
        bool: True if the check is successful, False otherwise.
    """

    fs_const = FaceMatchingCheckConst.FeatureSetting
    fs_params = face_matching_fs.parameters

    if not fs_params.get(fs_const.parameter_selfie_x_ktp).get('is_active'):
        return True

    if is_face_matching_check_done(
        application_id,
        FaceMatchingCheckConst.Process.selfie_x_ktp,
    ):
        return True

    face_matching_check = FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=FaceMatchingCheckConst.Process.selfie_x_ktp.value,
    ).last()
    if not face_matching_check:
        face_matching_check = FaceMatchingCheck.objects.create(
            application_id=application_id,
            process=FaceMatchingCheckConst.Process.selfie_x_ktp.value,
            reference_image=None,
            target_image=None,
            status=FaceMatchingCheckConst.Status.in_progress.value,
        )

    threshold = fs_params[fs_const.parameter_selfie_x_ktp].get('similarity_threshold')

    selfie_image = Image.objects.filter(
        image_source=application_id, image_type=ImageType.CROP_SELFIE
    ).last()
    if not selfie_image:
        return False

    ktp_image = Image.objects.filter(
        image_source=application_id, image_type=ImageType.KTP_SELF
    ).last()
    if not ktp_image:
        return False

    selfie_image_bytes = get_image_bytes_from_url(selfie_image.image_url)
    if not selfie_image_bytes:
        return False

    ktp_image_bytes = get_image_bytes_from_url(ktp_image.image_url)
    if not ktp_image_bytes:
        return False

    similarity_score = get_face_matching_score(
        source_image=selfie_image_bytes,
        target_image=ktp_image_bytes,
    )
    if similarity_score is None:
        return False

    status = (
        FaceMatchingCheckConst.Status.passed
        if similarity_score >= threshold
        else FaceMatchingCheckConst.Status.not_passed
    )

    face_matching_check.reference_image = selfie_image
    face_matching_check.target_image = ktp_image
    face_matching_check.status = status.value
    face_matching_check.metadata = {
        "config_used": fs_params,
        "similarity_score": similarity_score,
    }
    face_matching_check.save(
        update_fields=[
            'reference_image',
            'target_image',
            'status',
            'metadata',
        ]
    )

    return True


def check_selfie_to_liveness_matching(
    application_id: int,
    face_matching_fs: FeatureSetting,
) -> bool:
    """
    Check the similarity between the Selfie image and the Liveness image for a given application.

    Args:
        application_id (int): The ID of the application.
        face_matching_fs (FeatureSetting): The feature setting for face similarity.

    Returns:
        bool: True if the check is successful, False otherwise.
    """

    fs_const = FaceMatchingCheckConst.FeatureSetting
    fs_params = face_matching_fs.parameters

    if not fs_params.get(fs_const.parameter_selfie_x_liveness).get('is_active'):
        return True

    if is_face_matching_check_done(
        application_id,
        FaceMatchingCheckConst.Process.selfie_x_liveness,
    ):
        return True

    face_matching_check = FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=FaceMatchingCheckConst.Process.selfie_x_liveness.value,
    ).last()
    if not face_matching_check:
        face_matching_check = FaceMatchingCheck.objects.create(
            application_id=application_id,
            process=FaceMatchingCheckConst.Process.selfie_x_liveness.value,
            reference_image=None,
            target_image=None,
            status=FaceMatchingCheckConst.Status.in_progress.value,
        )

    threshold = fs_params[fs_const.parameter_selfie_x_liveness].get('similarity_threshold')

    liveness_image_type = ImageType.ACTIVE_LIVENESS_TOP_LEFT
    liveness_image = Image.objects.filter(
        image_source=application_id, image_type=liveness_image_type
    ).last()
    if not liveness_image:
        liveness_image_type = ImageType.SELFIE_CHECK_LIVENESS
        liveness_image = Image.objects.filter(
            image_source=application_id, image_type=liveness_image_type
        ).last()

    if not liveness_image:
        face_matching_check.status = FaceMatchingCheckConst.Status.skipped.value
        face_matching_check.metadata = {
            "config_used": fs_params,
            "remarks": "skipped due to missing liveness image",
        }
        face_matching_check.save(
            update_fields=[
                'status',
                'metadata',
            ]
        )
        return True

    logger.info(
        {
            'action': 'check_selfie_to_liveness_matching',
            'application_id': application_id,
            'source liveness image': liveness_image_type,
            'message': 'liveness image found',
        }
    )

    selfie_image = Image.objects.filter(
        image_source=application_id, image_type=ImageType.CROP_SELFIE
    ).last()
    if not selfie_image:
        return False

    liveness_image_bytes = get_image_bytes_from_url(liveness_image.image_url)
    if not liveness_image_bytes:
        return False

    selfie_image_bytes = get_image_bytes_from_url(selfie_image.image_url)
    if not selfie_image_bytes:
        return False

    similarity_score = get_face_matching_score(
        source_image=liveness_image_bytes,
        target_image=selfie_image_bytes,
    )
    if similarity_score is None:
        return False

    status = (
        FaceMatchingCheckConst.Status.passed
        if similarity_score >= threshold
        else FaceMatchingCheckConst.Status.not_passed
    )

    face_matching_check.reference_image = selfie_image
    face_matching_check.target_image = liveness_image
    face_matching_check.status = status.value
    face_matching_check.metadata = {
        "config_used": fs_params,
        "similarity_score": similarity_score,
    }
    face_matching_check.save(
        update_fields=[
            'reference_image',
            'target_image',
            'status',
            'metadata',
        ]
    )

    return True


def get_face_matching_score(
    source_image: bytes,
    target_image: bytes,
) -> float:
    """
    This function serves as a call wrapper.
    The similarity score between the faces is returned if the comparison is successful.
    If any error occurs during the process, None is returned.

    Args:
        source_image (bytes): The source face image in bytes format.
        target_image (bytes): The target face image in bytes format.

    Returns:
        float: The similarity score between the two face images.
               Returns None if an error occurs.

    """

    face_recognition_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_RECOGNITION, is_active=True
    ).last()

    if not face_recognition_fs:
        return None

    face_recognition_svc = get_face_recognition_service_v1_patch(
        face_recognition_fs.parameters['aws_settings'],
        face_recognition_fs.parameters['face_recognition_settings'],
    )

    try:
        raw_res = face_recognition_svc.compare_faces(
            source_image,
            target_image,
        )
    except Exception as e:
        sentry_client.captureException()
        logger.exception('get_face_matching_score_error | err={}'.format(e))
        return None

    res, _, _ = raw_res.get_service_response()

    matched_faces = res.get('matched_faces')
    if matched_faces is None:
        return None

    # result should only have 1 matching face
    if len(matched_faces) != 1:
        return 0

    return matched_faces[0].get('similarity')


def get_image_bytes_from_url(
    url: str,
) -> bytes:
    """
    Retrieves the image bytes from the given URL and returns them.
    The limit in face recognition service is 5242880, with the tolerance is 5,
        so we can set the target file size around 4900000

    Args:
        url (str): The URL of the image to retrieve.

    Returns:
        bytes: The image bytes if the retrieval is successful, None otherwise.
    """
    if not is_valid_url(url):
        return None

    response = requests.get(url, stream=True)
    if not response.ok:
        return None

    image_resize_handler = ImageUtil(response.raw)
    try:
        image_bytes = image_resize_handler.resize_image(
            4900000, 5, ImageUtil.ResizeResponseType.BYTES, 10
        )
    except Exception as e:
        sentry_client.captureException()
        logger.exception('get_image_bytes_from_url_error | err={}'.format(e))
        return None

    return image_bytes


def get_face_matching_result(
    application_id: int,
) -> Union[FaceMatchingResults, None]:
    """
    Retrieves the face matching result for a given application ID.

    Args:
        application_id (int): The ID of the application.

    Returns:
        Union[FaceMatchingResults, None]: The face matching result if successful, None otherwise.
    """

    face_matching_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_MATCHING_CHECK, is_active=True
    ).last()
    if not face_matching_fs:
        return FaceMatchingResults()

    fs_const = FaceMatchingCheckConst.FeatureSetting
    fs_params = face_matching_fs.parameters

    selfie_x_ktp_data = get_selfie_to_ktp_face_matching_result(
        application_id, fs_params.get(fs_const.parameter_selfie_x_ktp).get('is_active')
    )

    selfie_x_liveness_data = get_selfie_to_liveness_face_matching_result(
        application_id, fs_params.get(fs_const.parameter_selfie_x_liveness).get('is_active')
    )

    return FaceMatchingResults(
        selfie_x_ktp=selfie_x_ktp_data,
        selfie_x_liveness=selfie_x_liveness_data,
    )


def get_selfie_to_ktp_face_matching_result(
    application_id: int,
    fs_active: bool,
) -> FaceMatchingResult:
    """
    Retrieves the face matching result for a given application ID.

    Args:
        application_id (int): The ID of the application.

    Returns:
        FaceMatchingResult: The face matching result.
    """

    if not fs_active:
        return FaceMatchingResult()

    face_matching_check = FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=FaceMatchingCheckConst.Process.selfie_x_ktp.value,
    ).last()
    if not face_matching_check:
        return FaceMatchingResult(
            is_feature_active=True,
        )

    return FaceMatchingResult(
        is_feature_active=True,
        is_agent_verified=face_matching_check.is_agent_verified,
        status=FaceMatchingCheckConst.Status(face_matching_check.status),
    )


def get_selfie_to_liveness_face_matching_result(
    application_id: int,
    fs_active: bool,
) -> FaceMatchingResult:
    """
    Retrieves the face matching result for a given application ID.

    Args:
        application_id (int): The ID of the application.

    Returns:
        FaceMatchingResult: The face matching result.
    """

    if not fs_active:
        return FaceMatchingResult()

    face_matching_check = FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=FaceMatchingCheckConst.Process.selfie_x_liveness.value,
    ).last()
    if not face_matching_check:
        return FaceMatchingResult(
            is_feature_active=True,
        )

    return FaceMatchingResult(
        is_feature_active=True,
        is_agent_verified=face_matching_check.is_agent_verified,
        status=FaceMatchingCheckConst.Status(face_matching_check.status),
    )


def mark_face_matching_failed(
    application_id: int,
    process: FaceMatchingCheckConst.Process,
    remarks: str = None,
) -> None:
    """
    Marks the face matching process as failed for a given application ID.

    Args:
        application_id (int): The ID of the application.
        process (str): The process to mark as failed.
        remarks (str, optional): The remarks for the failed process.
    """

    face_matching_check = FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=process.value,
    ).last()
    if not face_matching_check:
        return

    if remarks:
        face_matching_check.metadata['remarks'] = remarks

    face_matching_check.status = FaceMatchingCheckConst.Status.not_passed.value
    face_matching_check.save(
        update_fields=[
            'metadata',
            'status',
        ]
    )


def update_face_matching_status(
    application_id: int,
    process: FaceMatchingCheckConst.Process,
    status: FaceMatchingCheckConst.Status,
    is_agent_verified: bool = False,
    remarks: str = None,
) -> Union[Dict[str, Any], None]:
    """
    Update the face matching status for a given application and process.

    Args:
        application_id (int): The ID of the application.
        process (int): The process to update the status for.
        status (FaceMatchingCheckConst.Status): The new status value.
        is_agent_verified (bool, optional): Whether the update was verified by an agent.
            Defaults to False.
        remarks (str, optional): Remarks for the update. Defaults to None.

    Returns:
        Union[Dict[str, Any], None]: The updated status if successful, None otherwise.
    """

    if not status:
        return None

    face_matching_check = FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=process.value,
    ).last()
    if not face_matching_check:
        return None

    if remarks:
        face_matching_check.metadata['update_reason'] = remarks

    face_matching_check.is_agent_verified = is_agent_verified
    face_matching_check.status = status.value
    face_matching_check.save(
        update_fields=[
            'metadata',
            'status',
            'is_agent_verified',
        ]
    )

    return {
        process.string_val: {
            'status': face_matching_check.status,
            'is_agent_verified': face_matching_check.is_agent_verified,
        },
    }


def is_face_matching_check_done(
    application_id: int,
    process: FaceMatchingCheckConst.Process,
) -> bool:
    return FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=process.value,
        status__in=[
            FaceMatchingCheckConst.Status.passed.value,
            FaceMatchingCheckConst.Status.not_passed.value,
            FaceMatchingCheckConst.Status.skipped.value,
        ],
    ).exists()


def is_face_matching_agent_verified(
    application_id: int,
    process: FaceMatchingCheckConst.Process,
) -> bool:

    face_matching = FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=process.value,
    ).last()
    if not face_matching:
        return False

    return face_matching.is_agent_verified


def get_face_collection_fraudster_face_match():
    if not FaceCollection.objects.filter(face_collection_name='face_collection_fraud').exists():
        face_collection_obj = FaceCollection.objects.create(
            face_collection_name='face_collection_fraud', status='active'
        )
        return face_collection_obj
    return FaceCollection.objects.get(face_collection_name='face_collection_fraud')


def store_fraud_face(
    application_id: int = None,
    customer_id: int = None,
    change_reason: str = None,
) -> bool:
    """
    Stores applicant's face to our fraud face list.

    Args:
        application_id (int): The ID of the application.
        customer_id (int): The ID of the customer.
        change_reason (str, optional): The reason for the change. Defaults to None.

    Returns:
        bool: True if the fraud face is stored successfully, False otherwise.

    TODO:
    - decouple call by application_id and customer_id
    """

    if application_id is None and customer_id is None:
        return False

    store_fraud_face_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FRAUD_FACE_STORING, is_active=True
    ).last()
    if not store_fraud_face_fs:
        return True

    x440_change_reasons = store_fraud_face_fs.parameters.get(
        StoreFraudFaceConst.FeatureSetting.parameter_x440_change_reasons, []
    )
    if change_reason is not None and change_reason not in x440_change_reasons:
        return True

    if customer_id:
        application = Application.objects.filter(customer_id=customer_id).last()
    else:
        application = Application.objects.filter(id=application_id).last()

    if not application:
        return True

    if not application.is_julo_one_or_starter():
        return True

    if IndexedFaceFraud.objects.filter(application_id=application_id).exists():
        return True

    face_collection = get_face_collection_fraudster_face_match()

    face_recognition_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_RECOGNITION, is_active=True
    ).last()
    if not face_recognition_fs:
        return True

    images = []

    selfie_image = Image.objects.filter(
        image_source=application.id, image_type=ImageType.SELFIE
    ).last()
    images.append(selfie_image)

    crop_selfie_image = Image.objects.filter(
        image_source=application.id, image_type=ImageType.CROP_SELFIE
    ).last()
    images.append(crop_selfie_image)

    if not selfie_image and not crop_selfie_image:
        return True

    parameters = face_recognition_fs.parameters
    aws_settings = parameters['aws_settings']

    for image in images:
        if not image:
            continue

        try:
            process_fraud_indexed_face(
                image.id,
                face_collection.id,
                application.id,
                application.customer.id,
                aws_settings,
            )
        except Exception as e:
            logger.info('store_fraud_face_error|application_id={}|err={}'.format(application_id, e))
            return False

    return True


def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False
