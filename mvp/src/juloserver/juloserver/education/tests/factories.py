from builtins import object
from faker import Faker
from factory import SubFactory
from factory import LazyAttribute
from factory.django import DjangoModelFactory

from juloserver.julo.tests.factories import LoanFactory
from juloserver.account.tests.factories import AccountFactory
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory

from juloserver.education.models import (
    School,
    StudentRegister,
    LoanStudentRegister,
    StudentRegisterHistory,
)

fake = Faker()


class SchoolFactory(DjangoModelFactory):
    class Meta(object):
        model = School

    name = LazyAttribute(lambda o: fake.name())
    city = LazyAttribute(lambda o: fake.name())
    is_active = True
    is_verified = True


class StudentRegisterFactory(DjangoModelFactory):
    class Meta(object):
        model = StudentRegister

    account = SubFactory(AccountFactory)
    school = SubFactory(SchoolFactory)
    bank_account_destination = SubFactory(BankAccountDestinationFactory)
    student_fullname = LazyAttribute(lambda o: fake.name())
    note = "1111111111"
    is_deleted = False


class LoanStudentRegisterFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanStudentRegister

    student_register = SubFactory(StudentRegisterFactory)
    loan = SubFactory(LoanFactory)


class StudentRegisterHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = StudentRegisterHistory
