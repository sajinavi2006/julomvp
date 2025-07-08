import csv
import logging
from juloserver.face_recognition.tasks import process_single_row_data
from juloserver.face_recognition.services import get_face_collection_fraudster_face_match
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    FeatureSetting,
)


logger = logging.getLogger(__name__)


def process_fraudster_csv_file(file_path):
    face_collection = get_face_collection_fraudster_face_match()
    face_recognition = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_RECOGNITION, is_active=True
    ).last()
    parameters = face_recognition.parameters
    aws_settings = parameters['aws_settings']
    with open(file_path, 'r') as csv_file:
        datareader = csv.reader(csv_file)
        for index, row in enumerate(datareader):
            if index == 0:
                continue
            process_single_row_data.delay(index, row, face_collection, aws_settings)
