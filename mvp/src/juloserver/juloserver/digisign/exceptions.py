from juloserver.julo.exceptions import JuloException


class DigisignNotRegisteredException(JuloException):
    pass


class DigitallySignedRegistrationException(JuloException):
    pass
