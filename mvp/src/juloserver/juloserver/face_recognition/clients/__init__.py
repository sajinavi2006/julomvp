from theia import AWSRekognitionClient, FaceCollectionService, FaceRecognitionService
from juloserver.face_recognition.clients.face_matching import (
    FaceRecognitionServiceV1Patch,
    AWSRekognitionClientV1patch,
)


def get_face_recognition_service(aws_settings, face_recognition_settings):
    aws_rekognition = AWSRekognitionClient(aws_settings)
    return FaceRecognitionService(client=aws_rekognition, settings=face_recognition_settings)


def get_face_collection_service(aws_settings):
    aws_rekognition = AWSRekognitionClient(aws_settings)
    return FaceCollectionService(client=aws_rekognition)


def get_face_recognition_service_v1_patch(aws_settings, face_recognition_settings):
    """
    THIS IS A TEMPORARY PATCH TO BE USED INSTEAD OF get_face_recognition_service
    SPECIFICALLY FOR compare_faces
    """
    aws_rekognition = AWSRekognitionClientV1patch(aws_settings)
    return FaceRecognitionServiceV1Patch(client=aws_rekognition, settings=face_recognition_settings)
