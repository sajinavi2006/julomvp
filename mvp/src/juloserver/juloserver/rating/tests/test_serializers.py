from copy import deepcopy
from django.test import TestCase
from juloserver.rating.serializers import RatingSerializer
from juloserver.rating.models import RatingFormTypeEnum, RatingSourceEnum


class TestRatingSerializer(TestCase):
    def test_happy_path_rating_form_unknown(self):
        data = {
            "rating": 5,
            "description": "ini adalah deskripsi",
        }

        serializer = RatingSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_happy_path_rating_form_b(self):
        data = {
            "rating": 5,
            "description": "ini adalah deskripsi",
            "csat_score": 5,
            "csat_detail": "ini adalah deskripsi",
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_b.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_happy_path_rating_form_c(self):
        data = {
            "rating": 5,
            "description": "ini adalah deskripsi",
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_c.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_happy_path_application_rejected_pre_enhancement(self):
        data = {
            "rating": 5,
            "description": "ini adalah deskripsi",
        }

        serializer = RatingSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_invalid_rating_form_b_rating(self):
        data = {
            "rating": 6,
            "description": "ini adalah deskripsi",
            "csat_score": 5,
            "csat_detail": "ini adalah deskripsi",
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_b.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_rating_form_b_no_rating(self):
        data = {
            "description": "ini adalah deskripsi",
            "csat_score": 5,
            "csat_detail": "ini adalah deskripsi",
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_b.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_rating_form_b_description(self):
        data = {
            "rating": 5,
            "description": "ini adalah deskripsi yang sangat panjang sekali dan sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat very long",
            "csat_score": 5,
            "csat_detail": "ini adalah deskripsi",
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_b.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_rating_form_b_csat_score(self):
        data = {
            "rating": 5,
            "description": "ini adalah deskripsi",
            "csat_score": 6,
            "csat_detail": "ini adalah deskripsi",
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_b.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_rating_form_b_csat_detail(self):
        data = {
            "rating": 5,
            "description": "ini adalah deskripsi",
            "csat_score": 5,
            "csat_detail": "ini adalah deskripsi yang sangat panjang sekali dan sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat very long",
            "csat_score": 5,
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_b.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_rating_form_c_rating(self):
        data = {
            "rating": 6,
            "description": "ini adalah deskripsi",
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_c.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_rating_form_c_description(self):
        data = {
            "rating": 5,
            "description": "ini adalah deskripsi yang sangat panjang sekali dan sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat sangat very long",
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_c.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_rating_form(self):
        data = {
            "rating": 5,
            "description": "ini adalah deskripsi",
            "rating_form": 999,
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_happy_path_form_type_d(self):
        data = {
            "csat_score": 5,
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_d.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_invalid_form_type_d(self):
        data = {
            "csat_score": 6,
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_d.value,
            "csat_detail": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_form_type_d_2(self):
        data = {
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_d.value,
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_form_type_d_3(self):
        data = {
            "csat_score": 5,
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_d.value,
            "rating": 5,
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_invalid_form_type_d_4(self):
        data = {
            "csat_score": 5,
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_d.value,
            "description": "ini adalah deskripsi",
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_valid_form_type_d_with_csat_detail(self):
        data = {
            "csat_score": 4,
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_d.value,
            "csat_detail": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        }

        serializer = RatingSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_invalid_form_type_d_with_csat_detail(self):
        data = {
            "csat_score": 5,
            "source": RatingSourceEnum.loan_success.value,
            "rating_form": RatingFormTypeEnum.type_d.value,
            "csat_detail": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        }

        serializer = RatingSerializer(data=data)
        self.assertFalse(serializer.is_valid())
