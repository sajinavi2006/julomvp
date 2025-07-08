from django.test import TestCase

from juloserver.moengage.models import MoengageUpload
from juloserver.moengage.tests.factories import MoengageUploadFactory


class TestMoengageUpload(TestCase):
    def test_set_attributes(self):
        # Check during assignment.
        moengage_upload = MoengageUpload()
        moengage_upload.attributes = {'attribute': '1'}
        self.assertIsNone(moengage_upload.attributes)

        # Check during creation.
        moengage_upload = MoengageUpload({'attribute': '1'})
        self.assertIsNone(moengage_upload.attributes)

        # Check during data update
        moengage_upload = MoengageUploadFactory()
        moengage_upload.update_safely(attributes={'attribute': '1'})
        self.assertIsNone(moengage_upload.attributes)
