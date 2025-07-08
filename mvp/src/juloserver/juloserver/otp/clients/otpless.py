from builtins import object

import requests

from django.conf import settings


class JuloOTPLessClient(object):
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret

    def send_otp(self, phone_number, redirect_uri, device_id, otpless_expiry_time):
        """
        send request to otpless to generate authorization
        """

        url = settings.JULO_OTPLESS_BASE_URL + '/auth/v1/authorize'
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "mobile_number": phone_number,
            "redirect_uri": redirect_uri,
            "device_id": device_id,
            "expiry": otpless_expiry_time,
        }

        response = requests.request("GET", url, params=params)
        return response

    def validate_otp(self, otp_code):
        """
        validate otp sent by user to get auth_code for retrieval of the user information
        """

        url = settings.JULO_OTPLESS_BASE_URL + '/auth/v1/token'
        data = {
            "grant_type": "code",
            "code": otp_code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        response = requests.request("POST", url, json=data)
        return response

    def verify_user_info(self, otpless_auth_code):
        """
        retrieve user information for authorization purpose, comparing information from
        Whatsapp button click with inputted user information to our side from Julo app
        """

        url = settings.JULO_OTPLESS_BASE_URL + '/auth/v1/userinfo'
        headers = {'Authorization': 'Bearer ' + otpless_auth_code}

        response = requests.request("POST", url, headers=headers)
        return response
