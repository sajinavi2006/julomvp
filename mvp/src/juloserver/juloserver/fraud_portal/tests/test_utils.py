from django.test import TestCase
from mock import Mock

from juloserver.fraud_portal.utils import (
    is_1xx_status,
    is_2xx_status,
    is_3xx_status,
    is_4xx_status,
    is_5xx_status,
    is_valid_application_id,
    is_valid_email,
    is_valid_phone,
    cvs_rows_exceeded_limit,
    is_csv_extension,
    get_or_none_object,
)

from django.test import TestCase
from io import StringIO

from juloserver.fraud_security.models import FraudHighRiskAsn
from juloserver.fraud_security.tests.factories import FraudHighRiskAsnFactory

class TestIs1XXStatus(TestCase):
    def test_happy_path_str(self):
        for i in range(100, 200):
            self.assertTrue(is_1xx_status(str(i)))

    def test_happy_path_int(self):
        for i in range(100, 200):
            self.assertTrue(is_1xx_status(i))

    def test_sad_path_none(self):
        self.assertFalse(is_1xx_status(None))

    def test_sad_path(self):
        self.assertFalse(is_1xx_status(69))


class TestIs2XXStatus(TestCase):
    def test_happy_path_str(self):
        for i in range(200, 300):
            self.assertTrue(is_2xx_status(str(i)))

    def test_happy_path_int(self):
        for i in range(200, 300):
            self.assertTrue(is_2xx_status(i))

    def test_sad_path_none(self):
        self.assertFalse(is_2xx_status(None))

    def test_sad_path(self):
        self.assertFalse(is_2xx_status(69))


class TestIs3XXStatus(TestCase):
    def test_happy_path_str(self):
        for i in range(300, 400):
            self.assertTrue(is_3xx_status(str(i)))

    def test_happy_path_int(self):
        for i in range(300, 400):
            self.assertTrue(is_3xx_status(i))

    def test_sad_path_none(self):
        self.assertFalse(is_3xx_status(None))

    def test_sad_path(self):
        self.assertFalse(is_3xx_status(69))


class TestIs4XXStatus(TestCase):
    def test_happy_path_str(self):
        for i in range(400, 500):
            self.assertTrue(is_4xx_status(str(i)))

    def test_happy_path_int(self):
        for i in range(400, 500):
            self.assertTrue(is_4xx_status(i))

    def test_sad_path_none(self):
        self.assertFalse(is_4xx_status(None))

    def test_sad_path(self):
        self.assertFalse(is_4xx_status(69))


class TestIs5XXStatus(TestCase):
    def test_happy_path_str(self):
        for i in range(500, 600):
            self.assertTrue(is_5xx_status(str(i)))

    def test_happy_path_int(self):
        for i in range(500, 600):
            self.assertTrue(is_5xx_status(i))

    def test_sad_path_none(self):
        self.assertFalse(is_5xx_status(None))

    def test_sad_path(self):
        self.assertFalse(is_5xx_status(69))


class TestIsValidApplicationId(TestCase):
    def test_happy_path_str(self):
        self.assertTrue(is_valid_application_id('2000000000'))

    def test_happy_path_int(self):
        self.assertTrue(is_valid_application_id(2000000000))

    def test_sad_path_none(self):
        self.assertFalse(is_valid_application_id(None))

    def test_sad_path(self):
        self.assertFalse(is_valid_application_id('69'))


class TestIsValidEmail(TestCase):
    def test_happy_path(self):
        self.assertTrue(is_valid_email('test@example.com'))

    def test_sad_path_none(self):
        self.assertFalse(is_valid_email(None))

    def test_sad_path(self):
        self.assertFalse(is_valid_email('invalid_email'))


class TestIsValidPhone(TestCase):
    def test_happy_path_str(self):
        self.assertTrue(is_valid_phone('081234567890'))

    def test_happy_path_int(self):
        self.assertFalse(is_valid_phone(81234567890))

    def test_sad_path_none(self):
        self.assertFalse(is_valid_phone(None))

    def test_sad_path(self):
        self.assertFalse(is_valid_phone('invalid_phone'))


class TestCvsRowsExceededLimit(TestCase):

    def generate_csv_content(self, num_rows):
        # Generate CSV content with a specified number of rows
        header = "column1,column2,column3\n"
        rows = "\n".join([f"value1_{i},value2_{i},value3_{i}" for i in range(num_rows)])
        return header + rows

    def test_empty_csv(self):
        csv_content = self.generate_csv_content(0)
        decoded_file = StringIO(csv_content)
        result = cvs_rows_exceeded_limit(decoded_file)
        self.assertFalse(result)

    def test_csv_with_fewer_than_200_rows(self):
        csv_content = self.generate_csv_content(199)
        decoded_file = StringIO(csv_content)
        result = cvs_rows_exceeded_limit(decoded_file)
        self.assertFalse(result)

    def test_csv_with_exactly_200_rows(self):
        csv_content = self.generate_csv_content(200)
        decoded_file = StringIO(csv_content)
        result = cvs_rows_exceeded_limit(decoded_file)
        self.assertTrue(result)

    def test_csv_with_more_than_200_rows(self):
        csv_content = self.generate_csv_content(201)
        decoded_file = StringIO(csv_content)
        result = cvs_rows_exceeded_limit(decoded_file)
        self.assertTrue(result)


class TestIsCsvExtension(TestCase):
    
    def test_csv_extension_lowercase(self):
        mock_file = Mock()
        mock_file.name = "testfile.csv"
        self.assertTrue(is_csv_extension(mock_file))
    
    def test_csv_extension_uppercase(self):
        mock_file = Mock()
        mock_file.name = "testfile.CSV"
        self.assertTrue(is_csv_extension(mock_file))

    def test_non_csv_extension(self):
        mock_file = Mock()
        mock_file.name = "testfile.txt"
        self.assertFalse(is_csv_extension(mock_file))

    def test_no_extension(self):
        mock_file = Mock()
        mock_file.name = "testfile"
        self.assertFalse(is_csv_extension(mock_file))

    def test_mixed_case_extension(self):
        mock_file = Mock()
        mock_file.name = "testfile.CsV"
        self.assertTrue(is_csv_extension(mock_file))

    def test_hidden_file_with_csv_extension(self):
        mock_file = Mock()
        mock_file.name = ".hiddenfile.csv"
        self.assertTrue(is_csv_extension(mock_file))

    def test_hidden_file_without_csv_extension(self):
        mock_file = Mock()
        mock_file.name = ".hiddenfile.txt"
        self.assertFalse(is_csv_extension(mock_file))


class TestGetOrNoneObject(TestCase):
    
    def setUp(self):
        FraudHighRiskAsnFactory(id=30, name='asn123')
        FraudHighRiskAsnFactory(id=31, name='asn456')
    
    def test_object_exists(self):
        asn = get_or_none_object(FraudHighRiskAsn, id=30)
        self.assertIsNotNone(asn)
        self.assertEqual(asn.id,30)
        self.assertEqual(asn.name, 'asn123')
    
    def test_object_does_not_exist(self):
        asn = get_or_none_object(FraudHighRiskAsn, id=32)
        self.assertIsNone(asn)
    
    def test_multiple_filter_criteria(self):
        asn = get_or_none_object(FraudHighRiskAsn, id=31, name='asn456')
        self.assertIsNotNone(asn)
        self.assertEqual(asn.id, 31)
        self.assertEqual(asn.name, 'asn456')

    def test_incorrect_multiple_filter_criteria(self):
        asn = get_or_none_object(FraudHighRiskAsn, id=31, name='asn123')
        self.assertIsNone(asn)
