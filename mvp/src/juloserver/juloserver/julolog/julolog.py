import logging
import json
import inspect

from juloserver.julo.services2.fraud_check import get_client_ip_from_request


class JuloLog:

    def __init__(self, available_name=None):
        """
        CRITICAL level
            Caused the server cant handle requests
            or in other way the function no longer working
        ERROR level
            Caused some function is not properly working,
            but not impacted to another function
        WARNING level
            Indicated something unexpected happened in the application.
            Such a problem or situation that might be disturb one of the processes
        INFO level
            Standar log information that indicating something happened in the application

        Use to logging:

        # Define
        julolog = JuloLog()

        log_data = {"application": application.id, "message": "Prepopulate Form"}
        julolog.info(message=log_data, request=request)

        -- or --

        log_data = {"application": application.id, "message": "Prepopulate Form"}
        julolog.info(log_data, request=request)

        -- or --

        julolog.info(message="Prepopulate form", request=request)

        -- or --

        julolog.info(message="Prepopulate form")

        -- or --

        julolog.info("Prepopulate form")

        Example result:
        # {"action": "juloserver.julolog.julolog", "level": "INFO",
        #  "message": "Prepopulate Form", "url": "/api/registration-flow/v1/prepopulate-form",
        #  "application": "xxxxx"}

        Refer documentation:
        https://docs.google.com/document/d/1lQJi3uCem_Xj3-uRsY8DXCtU2shXSpUtk32osOL2S60/edit#
        """

        self.log_level = None
        self.name = __name__ if not available_name else available_name

        self.log = logging.getLogger(self.name)

    def info(self, message, request=None, *args, **kwargs):

        self.log_level = "INFO"
        log_data = self._construct_log_data(message, request)
        self.log.info(log_data, *args, **kwargs)

    def warning(self, message, request=None, *args, **kwargs):

        self.log_level = "WARNING"
        log_data = self._construct_log_data(message, request)
        self.log.warning(log_data, *args, **kwargs)

    def warn(self, message, request=None, *args, **kwargs):

        self.warning(message, request, *args, **kwargs)

    def debug(self, message, request=None, *args, **kwargs):

        self.log_level = "DEBUG"
        log_data = self._construct_log_data(message, request)
        self.log.debug(log_data, *args, **kwargs)

    def error(self, message, request=None, *args, **kwargs):

        self.log_level = "ERROR"
        log_data = self._construct_log_data(message, request)
        self.log.error(log_data, *args, **kwargs)

    def critical(self, message, request=None, *args, **kwargs):

        self.log_level = "CRITICAL"
        log_data = self._construct_log_data(message, request)
        self.log.critical(log_data, *args, **kwargs)

    def _construct_log_data(self, message, request=None):
        """
        Re-structure log data
        """

        basic_dict = {
            "action": self.name,
            "level": self.log_level,
            "message": message,
            "url": get_url_logging(request),
            "ip_address": get_ip_address(request),
            "func_name": self.set_func_name()
        }

        # check for message is dict
        if isinstance(message, dict):
            # check key "message" is exists or not
            if 'message' not in message:
                message['message'] = None
            full_dict = {**basic_dict, **message}
        else:
            basic_dict['message'] = message
            full_dict = {**basic_dict}

        log_data = json.dumps(full_dict, default=str)
        return log_data

    @staticmethod
    def set_func_name():
        """
        For generate function_name by execution process / call function
        """
        try:
            return inspect.stack()[3][3] if inspect.stack()[3] else None
        except IndexError:
            return None


def get_url_logging(request):
    """
    Get URL Logging
    """

    if request is None or request.get_host() is None:
        return None

    return "{0}://{1}{2}".\
        format(request.scheme,
               request.get_host(),
               request.path)


def get_ip_address(request):
    """
    Get IP Address for request
    """

    if request is None:
        return None

    return get_client_ip_from_request(request)


def get_model_class(model_class):

    return str(model_class.__class__) if model_class is not None else None
