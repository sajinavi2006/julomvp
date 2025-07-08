from django.test.testcases import TestCase

from juloserver.application_form.models import CustomerClaim
from juloserver.application_form.services import ClaimerService
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    CustomerFactory,
    StatusLookupFactory,
)


class TestClaimerService(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()

    def test_claim_using_nik_has_same_nik_in_general_method(self):
        nik = '0220020202900001'
        self.customer.update_safely(nik=None)

        # First create fake customer that has same NIK with current customer
        fake_customer = CustomerFactory(nik=nik)
        self.assertEqual(fake_customer.nik, nik)

        # The new customer already registered but with no nik information.
        # In the middle of process this new customer want to claim the NIK.
        claimer = ClaimerService(self.customer)
        claimer.claim_using(nik=nik)

        fake_customer.refresh_from_db()

        self.assertFalse(fake_customer.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer.nik)
        self.assertEqual(self.customer.nik, nik)

        # Check the customer claim table
        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )

    def test_claim_using_nik_has_same_nik_in_specific_method_combination(self):
        nik = '0220020202900001'
        self.customer.update_safely(nik=None)
        fake_customer = CustomerFactory(nik=nik)
        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik_or_email(nik=nik)
        fake_customer.refresh_from_db()

        self.assertFalse(fake_customer.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer.nik)
        self.assertEqual(self.customer.nik, nik)

        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )

    def test_claim_using_nik_has_same_nik_in_specific_method(self):
        nik = '0220020202900001'
        self.customer.update_safely(nik=None)
        fake_customer = CustomerFactory(nik=nik)
        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik(nik)
        fake_customer.refresh_from_db()

        self.assertFalse(fake_customer.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer.nik)
        self.assertEqual(self.customer.nik, nik)

        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )

    def test_claim_using_nik_no_same_nik_in_general_method(self):
        nik = '0220020202900002'
        self.customer.update_safely(nik=None)
        claimer = ClaimerService(self.customer)
        claimer.claim_using(nik=nik)

        self.assertTrue(self.customer.is_active)

        # The customer has None NIK because updating process happening after reclaim process
        self.assertIsNone(self.customer.nik)

        self.assertFalse(
            CustomerClaim.objects.filter(
                customer=self.customer,
            ).exists()
        )

    def test_claim_using_nik_no_same_nik_in_specific_method(self):
        nik = '0220020202900002'
        self.customer.update_safely(nik=None)
        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik(nik=nik)

        self.assertTrue(self.customer.is_active)
        self.assertIsNone(self.customer.nik)

        self.assertFalse(
            CustomerClaim.objects.filter(
                customer=self.customer,
            ).exists()
        )

    def test_claim_using_nik_no_same_nik_in_specific_method_combination(self):
        nik = '0220020202900002'
        self.customer.update_safely(nik=None)
        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik_or_email(nik=nik)

        self.assertTrue(self.customer.is_active)
        self.assertIsNone(self.customer.nik)

        self.assertFalse(
            CustomerClaim.objects.filter(
                customer=self.customer,
            ).exists()
        )

    def test_claim_using_email_has_same_email_in_general_method(self):
        email = 'testclaimemail@gmail.com'
        self.customer.update_safely(email=None)
        fake_customer = CustomerFactory(email=email)
        claimer = ClaimerService(self.customer)
        claimer.claim_using(email=email)

        fake_customer.refresh_from_db()

        self.assertFalse(fake_customer.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer.email)
        self.assertEqual(self.customer.email, email)

        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )

    def test_claim_using_email_has_same_email_in_specific_method(self):
        email = 'testclaimemail@gmail.com'
        self.customer.update_safely(email=None)
        fake_customer = CustomerFactory(email=email)
        claimer = ClaimerService(self.customer)
        claimer.claim_using_email(email)

        fake_customer.refresh_from_db()

        self.assertFalse(fake_customer.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer.email)
        self.assertEqual(self.customer.email, email)

        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )

    def test_claim_using_email_has_same_email_in_specific_method_combination(self):
        email = 'testclaimemail@gmail.com'
        self.customer.update_safely(email=None)
        fake_customer = CustomerFactory(email=email)
        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik_or_email(email=email)

        fake_customer.refresh_from_db()

        self.assertFalse(fake_customer.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer.email)
        self.assertEqual(self.customer.email, email)

        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )

    def test_claim_using_email_no_same_email_in_general_method(self):
        email = 'testclaimemail@gmail.com'
        self.customer.update_safely(email=None)
        claimer = ClaimerService(self.customer)
        claimer.claim_using(email=email)

        self.assertTrue(self.customer.is_active)
        self.assertIsNone(self.customer.email)

    def test_claim_using_email_no_same_email_in_specific_method(self):
        email = 'testclaimemail@gmail.com'
        self.customer.update_safely(email=None)
        claimer = ClaimerService(self.customer)
        claimer.claim_using_email(email)

        self.assertTrue(self.customer.is_active)
        self.assertIsNone(self.customer.email)

        self.assertFalse(
            CustomerClaim.objects.filter(
                customer=self.customer,
            ).exists()
        )

    def test_claim_using_email_no_same_email_in_specific_method_combination(self):
        email = 'testclaimemail@gmail.com'
        self.customer.update_safely(email=None)
        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik_or_email(email=email)

        self.assertTrue(self.customer.is_active)
        self.assertIsNone(self.customer.email)
        self.assertFalse(
            CustomerClaim.objects.filter(
                customer=self.customer,
            ).exists()
        )

    def test_claim_using_nik_and_email__both_belongs_to_one_user(self):
        self.customer.update_safely(email=None, nik=None)

        fake_customer = CustomerFactory(nik='2020000202200002', email='testclaimed@gmail.com')
        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik_or_email(nik='2020000202200002', email='testclaimed@gmail.com')

        fake_customer.refresh_from_db()

        self.assertFalse(fake_customer.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer.nik)
        self.assertIsNone(fake_customer.email)
        self.assertEqual(self.customer.nik, '2020000202200002')
        self.assertEqual(self.customer.email, 'testclaimed@gmail.com')

        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )

    def test_claim_using_nik_and_email__each_belongs_to_different_user(self):
        self.customer.update_safely(email=None, nik=None)

        fake_customer_nik = CustomerFactory(nik='2020000202200001', email='testclaimed@gmail.com')
        fake_customer_email = CustomerFactory(
            nik='2020000202200002', email='testclaimed+x@gmail.com'
        )

        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik_or_email(nik='2020000202200002', email='testclaimed@gmail.com')

        fake_customer_nik.refresh_from_db()
        fake_customer_email.refresh_from_db()

        self.assertFalse(fake_customer_nik.is_active)
        self.assertFalse(fake_customer_email.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer_nik.nik)
        self.assertIsNone(fake_customer_email.nik)
        self.assertIsNone(fake_customer_nik.email)
        self.assertIsNone(fake_customer_email.email)
        self.assertEqual(self.customer.nik, '2020000202200002')
        self.assertEqual(self.customer.email, 'testclaimed@gmail.com')

        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer_nik
            ).exists()
        )
        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer_email
            ).exists()
        )

    def test_claim_using_nik_but_customer_already_has_nik(self):
        from juloserver.application_form.services import ClaimError

        nik = '0220020202900002'
        self.customer.update_safely(email=None, nik='0220080202900002')
        with self.assertRaises(ClaimError) as context:
            claimer = ClaimerService(self.customer)
            claimer.claim_using(nik=nik)

        self.assertEqual(
            str(context.exception), 'Current customer already has NIK, cannot replace it.'
        )

    def test_claim_using_email_but_customer_already_has_email(self):
        from juloserver.application_form.services import ClaimError

        email = 'testclaimemail@gmail.com'
        self.customer.update_safely(nik=None, email='rohman@julo.co.id')

        with self.assertRaises(ClaimError) as context:
            claimer = ClaimerService(self.customer)
            claimer.claim_using_nik_or_email(email=email)
        self.assertEqual(
            str(context.exception), 'Current customer already has email, cannot replace it.'
        )

    def test_claim_using_nik_email_but_customer_already_has_both(self):
        from juloserver.application_form.services import ClaimError

        email = 'testclaimemail@gmail.com'
        nik = '0220020202900002'

        self.customer.update_safely(nik='0220080202900002', email='rohman@julo.co.id')

        with self.assertRaises(ClaimError) as context:
            claimer = ClaimerService(self.customer)
            claimer.claim_using_nik_or_email(email=email, nik=nik)
        self.assertEqual(
            str(context.exception), 'Current customer already has NIK, cannot replace it.'
        )

    def test_without_anything_passed(self):
        with self.assertRaises(ValueError) as context:
            claimer = ClaimerService(self.customer)
            claimer.claim_using_nik_or_email(email=None, nik=None)
        self.assertEqual(
            str(context.exception), 'One or both between NIK and email must be filled.'
        )

    def test_candidate_claimed_customer_has_2_applications_x100(self):
        nik = '0220020202900001'
        self.customer.update_safely(nik=None)
        fake_customer = CustomerFactory(nik=nik)
        form_created_status = StatusLookupFactory(status_code=100)
        app1 = ApplicationFactory(customer=fake_customer)
        app2 = ApplicationFactory(customer=fake_customer)
        app1.application_status = form_created_status
        app2.application_status = form_created_status
        app1.save()
        app2.save()

        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik_or_email(nik=nik)

        fake_customer.refresh_from_db()
        self.assertFalse(fake_customer.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer.nik)
        self.assertEqual(self.customer.nik, nik)

        # Check the customer claim table
        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )

    def test_candidate_claimed_customer_has_2_applications_one_in_x100(self):
        nik = '0220020202900001'
        self.customer.update_safely(nik=None)
        fake_customer = CustomerFactory(nik=nik)
        form_created_status = StatusLookupFactory(status_code=100)
        form_submitted_status = StatusLookupFactory(status_code=105)
        app1 = ApplicationFactory(customer=fake_customer)
        app2 = ApplicationFactory(customer=fake_customer)
        app1.application_status = form_created_status
        app2.application_status = form_submitted_status
        app1.save()
        app2.save()

        from juloserver.application_form.services import ClaimError

        with self.assertRaises(ClaimError) as context:
            claimer = ClaimerService(self.customer)
            claimer.claim_using_nik_or_email(nik=nik)
        self.assertEqual(
            str(context.exception),
            'One of candidate claimed customer comes from restricted application status code 105.',
        )

    def test_candidate_claimed_customer_has_application_in_100(self):
        nik = '0220020202900001'
        self.customer.update_safely(nik=None)
        fake_customer = CustomerFactory(nik=nik)
        form_created_status = StatusLookupFactory(status_code=100)
        app = ApplicationFactory(customer=fake_customer)
        app.application_status = form_created_status
        app.save()

        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik_or_email(nik=nik)

        fake_customer.refresh_from_db()

        self.assertFalse(fake_customer.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer.nik)
        self.assertEqual(self.customer.nik, nik)

        # Check the customer claim table
        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )

    def test_candidate_claimed_customer_has_application_in_106_from_100(self):
        nik = '0220020202900001'
        self.customer.update_safely(nik=None)
        fake_customer = CustomerFactory(nik=nik)
        expired_status = StatusLookupFactory(status_code=106)
        application = ApplicationFactory(customer=fake_customer)
        application.application_status = expired_status
        application.save()
        ApplicationHistoryFactory(application_id=application.id, status_old=100, status_new=106)

        claimer = ClaimerService(self.customer)
        claimer.claim_using_nik_or_email(nik=nik)

        fake_customer.refresh_from_db()

        self.assertFalse(fake_customer.is_active)
        self.assertTrue(self.customer.is_active)
        self.assertIsNone(fake_customer.nik)
        self.assertEqual(self.customer.nik, nik)

        # Check the customer claim table
        self.assertTrue(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )

    def test_candidate_claimed_customer_has_application_in_106_from_120(self):
        from juloserver.julo.models import StatusLookup

        nik = '0220020202900001'
        self.customer.update_safely(nik=None)
        fake_customer = CustomerFactory(nik=nik)
        expired_status = StatusLookup.objects.filter(status_code=106).get()
        application = ApplicationFactory(customer=fake_customer)
        application.application_status = expired_status
        application.save()
        ApplicationHistoryFactory(application_id=application.id, status_old=120, status_new=106)

        from juloserver.application_form.services import ClaimError

        with self.assertRaises(ClaimError) as context:
            claimer = ClaimerService(self.customer)
            claimer.claim_using_nik_or_email(nik=nik)

        # fake_customer.refresh_from_db()
        #
        # self.assertFalse(fake_customer.is_active)
        # self.assertTrue(self.customer.is_active)
        # self.assertIsNone(fake_customer.nik)
        # self.assertEqual(self.customer.nik, nik)

        # Check the customer claim table
        self.assertFalse(
            CustomerClaim.objects.filter(
                customer=self.customer, claimed_customer=fake_customer
            ).exists()
        )
