from builtins import range, object
from faker.providers.internet import Provider
import random
import string


class JuloFakerProvider(Provider):
    def random_email(self):
        random_addition = ''.join(
            random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits)
            for _ in range(8))

        return (self.user_name() + "_" + random_addition).lower() + "@" + self.free_email_domain()

    def random_username(self):
        random_addition = ''.join(
            random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits)
            for _ in range(8))

        email = (self.user_name() + "_" + random_addition).lower() + "@" + self.free_email_domain()

        email_length = len(email)

        return email[email_length - 29:] if email_length > 29 else email


class ObjectMock(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
