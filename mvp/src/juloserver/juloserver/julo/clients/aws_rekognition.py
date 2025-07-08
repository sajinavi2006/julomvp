from builtins import str
from future import standard_library
standard_library.install_aliases()
from builtins import object
import boto3
import logging

from juloserver.julo.exceptions import JuloException
from botocore.exceptions import ClientError
from juloserver.julo.models import (FaceRecognition,
                                    Application,
                                    AwsFaceRecogLog,
                                    DigitalSignatureFaceResult,
                                    ApplicationHistory,
                                    Image)
from juloserver.julo.services2 import get_customer_service
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.julo.utils import get_file_from_oss
from django.conf import settings
import time
from juloserver.julo.tasks import send_alert_notification_face_recog_through_slack, set_off_face_recognition
import urllib.request, urllib.parse, urllib.error
import os
import tempfile

logger = logging.getLogger(__name__)

class JuloFaceRekognition(object):
    def __init__(self, aws_access_key_id, aws_secret_access_key, collection,
        quality_filter, max_faces, region_name):
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.collection = collection
        self.region_name = region_name
        self.quality_filter = quality_filter
        self.max_faces = max_faces

        session = boto3.Session(
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.region_name)

        self.rekognition = session.client('rekognition')

    def add_collection(self):
        """
        Create collection for IndexFaces.
        :return: json representation of the result.
        """
        response = self.rekognition.create_collection(CollectionId=self.collection)
        logger.info({
            'action': 'rekognition - add_collection',
            'CollectionId': self.collection,
            'response': response,
        })

        return response

    def list_collections(self):
        """
        List collection from IndexFaces.
        :return: list representation of the list collections.
        """
        response = self.rekognition.list_collections()

        logger.info({
            'action': 'rekognition - list_collections',
            'response': response,
        })

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return response['CollectionIds']

    def describe_collection(self):
        """
        Describe collection from IndexFaces.
        :return: json representation of the result.
        """

        response = self.rekognition.describe_collection(CollectionId=self.collection)
        logger.info({
            'action': 'rekognition - describe_collection',
            'CollectionId': self.collection,
            'response': response,
        })

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return response

    def delete_collection(self):
        """
        Delete collection from IndexFaces.
        :return: Boolean representation delete status
        """
        response = self.rekognition.delete_collection(CollectionId=self.collection)
        logger.info({
            'action': 'rekognition - delete_collection',
            'CollectionId': self.collection,
            'response': response,
        })

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return True

        return False

    def delete_faces(self, face_ids):
        """
        Delete faces of IndexFaces.
        :param next_token: contains list of string face_id
        :return: List Object representation faces deleted
        """
        params = {
            'CollectionId': self.collection,
            'FaceIds': face_ids
        }
        response = self.rekognition.delete_faces(**params)
        logger.info({
            'action': 'rekognition - delete_faces',
            'params': params,
            'response': response,
        })

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return response['DeletedFaces']

    def add_faces(self, image, external_image_id):
        """
        Add faces to IndexFaces
        :param image: contains object of Byte image with format {'Bytes': image_bytes}
        :param image_external_id: contains data of image_id that julo have
        :return: Object representation face
        """
        params = {
            'CollectionId': self.collection,
            'Image': image,
            'ExternalImageId': external_image_id,
            'MaxFaces': self.max_faces,
            'QualityFilter': self.quality_filter,
        }

        response = self.rekognition.index_faces(**params)
        logger.info({
            'action': 'rekognition - add_faces',
            'params': params,
            'response': response,
        })

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            # delete FaceRecords if return more than 1
            response['FaceRecordsStatus'] = True
            response['UnindexedStatus'] = False
            if len(response['FaceRecords']) > 1 or len(response['FaceRecords']) == 0:
                if len(response['FaceRecords']) > 1:
                    face_ids = []
                    for face in response['FaceRecords']:
                        face_ids.append(face['Face']['FaceId'])

                    self.delete_faces(face_ids)
                response['FaceRecordsStatus'] = False

            if len(response['UnindexedFaces']) > 0:
                response['UnindexedStatus'] = True

        elif response['ResponseMetadata']['HTTPStatusCode'] == 500:
            response['FaceRecordsStatus'] = False
            set_off_face_recognition.delay()

            send_alert_notification_face_recog_through_slack.delay()

        return response

    def list_faces(self, next_token=None, limit=10):
        """
        List faces of IndexFaces.
        :param next_token: contains NextToken for get nextpage
        :param limit: contains integer for limit perpage
        :return: List Object representation faces
        """

        params = {
            'CollectionId': self.collection,
            'MaxResults': limit
        }
        if next_token:
            params['NextToken'] = next_token

        response = self.rekognition.list_faces(**params)
        logger.info({
            'action': 'rekognition - list_faces',
            'params': params,
            'response': response,
        })

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return response['Faces']

    def search_faces_by_id(self, face_id, threshold=None, max_faces=10):
        """
        Find faces by id from IndexFaces
        :param face_id: contains string representation face id
        :param threshold: contains interger for threshold
        :param max_faces: contains integer for limit result response
        :return: List Object representation result faces
        """
        params = {
            'CollectionId': self.collection,
            'FaceId': face_id,
            'MaxFaces': max_faces
        }

        if threshold:
            params['FaceMatchThreshold'] = threshold

        response = self.rekognition.search_faces(**params)
        logger.info({
            'action': 'rekognition - search_faces_by_id',
            'params': params,
            'response': response,
        })

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return response['FaceMatches']

    def search_faces_by_image(self, image, threshold=None, max_faces=10):
        """
        Find faces by image from IndexFaces
        :param image: contains object of Byte image with format {'Bytes': image_bytes}
        :param threshold: contains interger for threshold
        :param max_faces: contains integer for limit result response
        :return: List Object representation result faces
        """
        params = {
            'CollectionId': self.collection,
            'Image': image,
            'MaxFaces': max_faces
        }

        if threshold:
            params['FaceMatchThreshold'] = threshold

        response = self.rekognition.search_faces_by_image(**params)
        logger.info({
            'action': 'rekognition - search_faces_by_image',
            'params': params,
            'response': response,
        })

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return response['FaceMatches']

    def detect_faces_by_image(self, image):
        """
        Detect faces to know how many faces are on photo
        :param image: contains object of Byte image with format {'Bytes': image_bytes}
        :return: List Object representation detected faces on photo
        """
        params = {
            'Image': image
        }

        response = self.rekognition.detect_faces(**params)
        logger.info({
            'action': 'rekognition - detect_faces_by_image',
            'params': params,
            'response': response,
        })

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return response['FaceDetails']

    def run_index_face(self, application_id, repeat_face_recog=True, skip_pv_dv=False):
        from ..services import process_application_status_change
        from juloserver.julo.constants import FaceRecognition as FaceRecognitionSetting

        application = Application.objects.get_or_none(pk=application_id)
        application_131 = ApplicationHistory.objects.filter(application=application,
                                                            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED).count()
        if application_131 > 3:
            if application.status == ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT and repeat_face_recog:
                process_application_status_change(application_id, ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                                                  change_reason='Passed KTP Check')
                return
            else:
                return {
                    'passed': False,
                    'new_status_code': ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                    'change_reason': 'Passed KTP Check',
                }
        customer = application.customer

        # get cropped selfie
        max_retry = 8
        retry = 0
        retry_delay = 2
        while retry <= max_retry:
            image = Image.objects.filter(image_source=application.id,
                                         image_type='crop_selfie',
                                         url__isnull=False).last()
            if not image:
                logger.info({
                    'action': 'run_index_faces',
                    'application_id': application.id,
                    'message': 'image crop selfie not found'
                })
                if application.status == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
                    return

            try:
                filename = os.path.join(tempfile.gettempdir(), "crop_selfie_{}.jpg".format(application.id))
                urllib.request.urlretrieve(image.image_url, filename)
                oss_image = open(filename, 'rb')
                break
            except Exception as error:
                logger.info({
                    'action': 'run_index_faces',
                    'application_id': application.id,
                    'message': 'image not found in oss',
                    'error': str(error),
                })
                # max retry = 8
                if retry < 8:
                    time.sleep(retry_delay)
                    retry_delay = retry_delay * 2
                    retry += 1
                else:
                    if application.status == ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT:
                        process_application_status_change(
                            application_id,
                            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                            'failed upload selfie image'
                        )
                        return
                    elif application.status == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
                        return {
                            'passed': False,
                            'new_status_code': ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
                            'change_reason': 'Passed KTP check & failed upload selfie image',
                        }

        params = {
            'image': {'Bytes': oss_image.read()},
            'external_image_id': '{}-{}'.format(application.id, application.customer.id)
        }

        faces = self.add_faces(**params)
        if os.path.exists(filename):
            logger.info({
                'action': 'deleting_local_crop_selfie_image',
                'filename': filename,
                'application_id': application_id
            })
            os.remove(filename)
        digital_signature_face_result = DigitalSignatureFaceResult.objects.create(
            face_recognition_provider=FaceRecognitionSetting.AWS)
        threshold = FaceRecognition.objects.filter(feature_name='IndexStorage Threshold').first()
        aws_log = AwsFaceRecogLog.objects.create(
            image=image,
            customer=customer,
            application=application,
            raw_response=faces,
            is_indexed=faces['FaceRecordsStatus'],
            brightness_threshold=threshold.brightness,
            sharpness_threshold=threshold.sharpness,
            digital_signature_face_result=digital_signature_face_result,
        )
        application_history_147 = ApplicationHistory.objects.filter(
            application=application,
            status_new=ApplicationStatusCodes.DIGISIGN_FACE_FAILED).first()
        customer_service = get_customer_service()
        if faces['ResponseMetadata']['HTTPStatusCode'] == 500:
            new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
            change_reason = 'Passed KTP Check'
            if not skip_pv_dv:
                if not repeat_face_recog:
                    return
            else:
                result_bypass = customer_service.do_high_score_full_bypass_or_iti_bypass(application_id)
                if result_bypass:
                    new_status_code = result_bypass['new_status_code']
                    change_reason = result_bypass['change_reason']
            application.refresh_from_db()
            if application.status != ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                process_application_status_change(application_id, new_status_code,
                                                  change_reason=change_reason)
            return
        if faces['FaceRecordsStatus'] and not faces['UnindexedFaces']:
            aws_log.face_id = faces['FaceRecords'][0]['Face']['FaceId']
            brightness = faces['FaceRecords'][0]['FaceDetail']['Quality']['Brightness']
            sharpness = faces['FaceRecords'][0]['FaceDetail']['Quality']['Sharpness']
            new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
            change_reason = 'Passed Face Check'
            if threshold.brightness <= brightness and threshold.sharpness <= sharpness:
                aws_log.is_quality_check_passed = True
            else:
                aws_log.is_quality_check_passed = False
                change_reason = FaceRecognitionSetting.BAD_IMAGE_QUALITY
                new_status_code = ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
                if not application_history_147 and repeat_face_recog:
                    process_application_status_change(application.id,
                                                      new_status_code,
                                                      change_reason=change_reason)

            aws_log.save()
            # change status code to 121 if application status 1311 and quality_passed true
            if application.status == ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT \
                    and aws_log.is_quality_check_passed or skip_pv_dv:
                new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                change_reason = 'Passed Face Check'
                result_bypass = customer_service.do_high_score_full_bypass_or_iti_bypass(application_id)
                if result_bypass:
                    new_status_code = result_bypass['new_status_code']
                    change_reason = result_bypass['change_reason']
                application.refresh_from_db()
                if application.status != ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                    process_application_status_change(application.id,
                                                      new_status_code,
                                                      change_reason=change_reason)
                return
            else:
                return {
                    'passed': aws_log.is_quality_check_passed,
                    'new_status_code': new_status_code,
                    'change_reason': change_reason,
                }
        else:
            if not faces['FaceRecordsStatus'] and not faces['UnindexedFaces']:
                change_reason = FaceRecognitionSetting.NO_FACE_FOUND
            elif faces['UnindexedFaces']:
                change_reason = FaceRecognitionSetting.NO_FACE_AND_BAD_IMAGE_QUALITY
            application_status_code = ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED

            if not application_history_147 and repeat_face_recog:
                process_application_status_change(application.id,
                                                  application_status_code,
                                                  change_reason=change_reason)
            return {
                'passed': aws_log.is_quality_check_passed,
                'new_status_code': application_status_code,
                'change_reason': change_reason,
            }
