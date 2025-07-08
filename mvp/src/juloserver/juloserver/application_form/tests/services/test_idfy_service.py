import pytest
from mock import patch
from datetime import datetime
from django.test import TestCase

from juloserver.julo.models import Application
from juloserver.application_form.models import IdfyCallBackLog

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    IdfyCallBackLogFactory,
    WorkflowFactory,
    ImageFactory,
)
from juloserver.application_form.services.idfy_service import (
    compare_application_data_idfy,
    edited_data_comparison,
    transform_data_from_video_call,
)
from juloserver.application_form.constants import LabelFieldsIDFyConst
from juloserver.julo.constants import WorkflowConst
from juloserver.application_form.constants import ApplicationEditedConst


class TestCompareApplicationData(TestCase):
    def setUp(self) -> None:
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(workflow=self.workflow)
        self.application.application_status_id = 105
        self.application.save()

        self.callback_log_data = {
            "change_log": [],
            "changed": False,
            "extraction_output": {
                "agama": "ISLAM",
                "alamat": "LK.VI JUA JUA",
                "berlaku_hingga": "",
                "gol_darah": "",
                "jenis_kelamin": "LAKI-LAKI",
                "kecamatan": "KAYU AGUNG",
                "kel_desa": "JUA JUA",
                "kewarganegaraan": "WNI",
                "kota_or_kabupaten": "OGAN KOMERING ILIR",
                "nama": "TARMIDI HENGKI WUAYA",
                "nik": "1602050702860001",
                "pekerjaan": "WIRASWASTA",
                "provinci": "SUMATERA SELATAN",
                "rt_rw": "007/000",
                "status_perkawinan": "KAWIN",
                "tempat": "PALEMBANG",
                "tgl_lahir": "1986-02-07",
            },
        }

        self.callback_log = IdfyCallBackLogFactory(
            application_id=self.application.id,
            callback_log=self.callback_log_data,
            status='completed',
        )

    def test_compare_application_data_to_idfy(self):
        # case same data
        compare_fields = ApplicationEditedConst.APPLICATION_FIELDS_MAPPING
        for field in compare_fields:
            setattr(
                self.application,
                compare_fields[field],
                self.callback_log_data['extraction_output'][field],
            )
        self.application.dob = datetime.strptime("1986-02-07", "%Y-%m-%d").date()
        self.application.save()

        is_different, different_data = compare_application_data_idfy(self.application)
        self.assertEqual(is_different, False)

        # case different text data
        self.application.gender = 'Wanita'
        self.application.marital_status = 'Lajang'
        self.application.dob = datetime.strptime("1999-02-07", "%Y-%m-%d").date()
        self.application.save()

        is_different, different_data = compare_application_data_idfy(self.application)
        self.assertEqual(is_different, True)
        self.assertEqual(len(different_data), 3)
        self.assertIn('status_perkawinan', different_data)
        self.assertIn('jenis_kelamin', different_data)
        self.assertIn('tgl_lahir', different_data)

        self.application.dob = datetime.strptime("1986-02-07", "%Y-%m-%d").date()
        self.application.save()

        is_different, different_data = compare_application_data_idfy(self.application)
        self.assertNotIn('tgl_lahir', different_data)

    def test_transform_data_callback_log_is_none(self):

        # set if extration is empty
        self.callback_log_data['extraction_output'] = {}
        self.callback_log.callback_log = self.callback_log_data
        self.callback_log.save()

        _, different_data = compare_application_data_idfy(self.application)
        data_video_call, is_match_job = transform_data_from_video_call(self.application)

        self.assertIsNone(data_video_call)
        self.assertFalse(is_match_job)

    def test_transform_data_callback_log(self):

        job_type_target = 'Programmer'

        # change job type to Petani (we not have mapping for this)
        self.application.update_safely(job_type=job_type_target)
        _, different_data = compare_application_data_idfy(self.application)
        data_video_call, is_match_job = transform_data_from_video_call(self.application)

        self.assertIn('pekerjaan', different_data)
        self.assertFalse(is_match_job)

        # case change application job type to correct and callback is correct
        self.application.update_safely(job_type='Pegawai swasta')
        self.callback_log_data['extraction_output']['pekerjaan'] = job_type_target
        self.callback_log.callback_log = self.callback_log_data
        self.callback_log.save()

        _, different_data = compare_application_data_idfy(self.application)
        data_video_call, is_match_job = transform_data_from_video_call(self.application)

        self.assertIn('pekerjaan', different_data)
        self.assertTrue(is_match_job)

        # pekerjaan is empty
        self.callback_log_data['extraction_output']['pekerjaan'] = ""
        self.callback_log.callback_log = self.callback_log_data
        self.callback_log.save()

        _, different_data = compare_application_data_idfy(self.application)
        data_video_call, is_match_job = transform_data_from_video_call(self.application)

        self.assertIn('pekerjaan', different_data)
        self.assertTrue(is_match_job)


class TestEditedDataComparison(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.application.application_status_id = 105
        self.application.birth_place = 'Asgard'
        self.application.save()

        self.different_data = [
            'tempat',
            'tgl_lahir',
        ]

        self.image_ktp = ImageFactory(image_source=self.application.id, image_type='ktp_self')
        self.image_selfie = ImageFactory(image_source=self.application.id, image_type='selfie')

    def test_edited_data_comparison_service(self):
        edited_data = edited_data_comparison(self.application, self.different_data)
        for field in self.different_data:
            self.assertTrue(edited_data[field]['is_different'])
