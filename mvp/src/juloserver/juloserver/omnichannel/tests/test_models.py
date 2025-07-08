import json
import unittest
from datetime import datetime
from decimal import Decimal

from numpy import int64

from juloserver.omnichannel.models import CustomerAttribute, OmnichannelCustomer


class TestCustomerAttribute(unittest.TestCase):
    def setUp(self):
        self.customer_attribute = CustomerAttribute(
            account_id=123,
            customer_xid="123abc",
            customer_id=int64(456),
            sms_firstname="John",
            email="john.doe@example.com",
            fcm_reg_id="fcmRegId123",
            mobile_phone="1234567890",
            timezone_offset=3600,
            mobile_phone_2="0987654321",
            full_name="John Doe",
            first_name="John",
            last_name="Doe",
            title_long="Mr.",
            title="Mr.",
            name_with_title="Mr. John Doe",
            company_name="Doe Industries",
            company_phone_number="1234567890",
            position_employees="Manager",
            spouse_name="Jane Doe",
            spouse_mobile_phone="1234567890",
            kin_name="Emily Doe",
            kin_relationship="Sister",
            kin_mobile_phone="1234567890",
            address_full="123 Main St, Anytown, Anystate",
            city="Anytown",
            gender="Male",
            dob=datetime(1990, 1, 1),
            age=30,
            payday=10,
            loan_purpose="Home Renovation",
            is_autodebet=True,
            is_j1_customer=False,
            bank_code="XYZ123",
            bank_code_text="Bank XYZ",
            bank_name="Bank XYZ",
            va_method_name="Method XYZ",
            va_number="1234567890123456",
            va_bca="1234567890",
            va_permata="1234567890",
            va_maybank="1234567890",
            va_alfamart="9876543210",
            va_indomaret="1122334455",
            va_mandiri="5566778899",
            product_line_code="PL123",
            collection_segment="SegmentA",
            customer_bucket_type="Type1",
            cashback_new_scheme_experiment_group=True,
            active_liveness_score=0.95,
            passive_liveness_score=0.85,
            heimdall_score=0.75,
            orion_score=0.65,
            fpgw=1.23,
            shopee_score_status="Active",
            shopee_score_list_type="TypeB",
            total_loan_amount=5000,
            application_similarity_score=Decimal(0.5),
            mycroft_score=0.4,
            credit_score="700",
            is_risky=False,
            total_cashback_earned=100,
            cashback_amount=50,
            cashback_counter=2,
            cashback_due_date_slash="2023-12-31",
            refinancing_prerequisite_amount=3000,
            refinancing_status="Eligible",
            refinancing_expire_date=datetime(2023, 12, 31).date(),
            zip_code="12345",
            uninstall_indicator="No",
            fdc_risky=False,
            sms_primary_va_name="PrimaryVA",
            sms_primary_va_number="123456789012",
            last_call_agent="Agent007",
            last_call_status="Successful",
            is_email_blocked=False,
            is_sms_blocked=False,
            is_one_way_robocall_blocked=False,
            partner_name="Partner XYZ",
            google_calendar_url="https://calendar.google.com/event?eid=abc123",
            account_payment=[],
            dialer_blacklisted_permanent=False,
            dialer_blacklisted_expiry_date=datetime(2025, 12, 31).date(),
        )

    def test_to_json_dict(self):
        result = self.customer_attribute.to_json_dict()

        self.assertIsInstance(result, dict)
        self.assertEqual(result['customer_id'], 456)
        self.assertEqual(result['customer_xid'], '123abc')

    def test_json_dumps(self):
        json_dict = self.customer_attribute.to_json_dict()
        result = json.dumps(json_dict)

        self.assertIsInstance(result, str)


class TestOmnichannelCustomer(unittest.TestCase):
    def setUp(self):
        self.customer_attribute = CustomerAttribute(customer_id=1, customer_xid='xid')
        self.now = datetime.now()
        self.omnichannel_customer = OmnichannelCustomer(
            customer_id='1', updated_at=self.now, customer_attribute=self.customer_attribute
        )

    def test_invalid_type(self):
        # Arrange
        with self.assertRaises(TypeError):
            OmnichannelCustomer(customer_id=1, updated_at='now')

    def test_to_dict(self):
        # Act
        result = self.omnichannel_customer.to_dict()

        # Assert
        self.assertIsInstance(result, dict)
        self.assertEqual(result['updated_at'], self.now)
        self.assertEqual(result['customer_id'], '1')
        self.assertEqual(result['customer_attribute']['customer_id'], 1)
        self.assertEqual(result['customer_attribute']['customer_xid'], 'xid')

    def test_to_json_dict(self):
        # Act
        result = self.omnichannel_customer.to_json_dict()

        # Assert
        self.assertIsInstance(result, dict)
        self.assertEqual(result['updated_at'], int(self.now.timestamp()))
        self.assertEqual(result['customer_id'], '1')
        self.assertIsInstance(result['customer_attribute'], dict)
