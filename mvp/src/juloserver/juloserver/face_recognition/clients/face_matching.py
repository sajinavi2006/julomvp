import time
import logging
from theia.face_recognition.responses import FaceRecognitionResponse
from theia import FaceRecognitionService, AWSRekognitionClient


logger = logging.getLogger(__name__)


# THIS IS A TEMPORARY PATCH, WILL BE REMOVED ONCE THEIA CODE IS PATCHED
class FaceRecognitionServiceV1Patch(FaceRecognitionService):
    """
    Patch for FaceRecognitionService
    """

    def __init__(self, client, settings):
        super().__init__(client, settings)
        self.version = self.version + '-patch20240320'

    def compare_faces(self, image_bytes_reference, image_bytes_target):
        """
        Compares two faces and returns a similarity score between them.
        """

        (client_response, client_latency, client_version) = self.client.compare_faces(
            image_bytes_reference, image_bytes_target
        )

        try:
            start_time = time.time()
            service_response = {}
            if len(client_response['SourceImageFace']) < 1:
                reference_face_bbox = None
                reference_face_confidence = None
            else:
                reference_face_bbox = client_response['SourceImageFace']['BoundingBox']
                reference_face_confidence = client_response['SourceImageFace']['Confidence']

                service_response['reference_face'] = {
                    'reference_face_bbox': reference_face_bbox,
                    'reference_face_confidence': reference_face_confidence,
                }

            service_response['matched_faces'] = []

            if len(client_response['FaceMatches']) >= 1:
                for i in range(len(client_response['FaceMatches'])):
                    matched_face_bbox = client_response['FaceMatches'][i]['Face']['BoundingBox']
                    matched_face_confidence = client_response['FaceMatches'][i]['Face'][
                        'Confidence'
                    ]
                    similarity = client_response['FaceMatches'][i]['Similarity']

                    service_response['matched_faces'].append(
                        {
                            'matched_face_bbox': matched_face_bbox,
                            'matched_face_confidence': matched_face_confidence,
                            'similarity': similarity,
                        }
                    )

            end_time = time.time()
            service_latency = (end_time - start_time) * 1000

        except Exception as e:
            logger.exception('Error in compare_faces | {}'.format(e))

        return FaceRecognitionResponse(
            client_response=client_response,
            client_latency=client_latency,
            client_version=client_version,
            service_response=service_response,
            service_latency=service_latency,
            service_version=self.version,
            configs=self.configs,
            context={
                'image_bytes': None,
            },
        )


class AWSRekognitionClientV1patch(AWSRekognitionClient):
    def __init__(
        self,
        settings,
    ):
        super().__init__(settings)
        self.version = self.version + '-patch20240415'

    def compare_faces(self, image_bytes_reference, image_bytes_target):
        """
        Compares two faces and outputs similarity score between them.
        """
        start_time = time.time()

        params = {
            'SimilarityThreshold': self.settings['face_comparison_threshold'],
            'SourceImage': {'Bytes': image_bytes_reference},
            'TargetImage': {'Bytes': image_bytes_target},
        }

        response = self.client.compare_faces(**params)

        end_time = time.time()
        latency = (end_time - start_time) * 1000
        return (response, latency, self.version)
