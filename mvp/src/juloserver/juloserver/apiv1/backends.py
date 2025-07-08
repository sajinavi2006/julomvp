from __future__ import unicode_literals

import logging
import time
from builtins import object, str

import facebook

# from django.contrib.auth.models import User
from juloserver.julo.models import AuthUser as User
from django.utils.translation import gettext as _
from rest_framework import exceptions

from ..julo.exceptions import JuloDeprecated
from ..julo.models import Customer, FacebookData

logger = logging.getLogger(__name__)


class ApiV1Backend(object):
    def authenticate(self, **request_attrs):
        """Check the token (by default) and return or create a User.

        Args:
            request_attrs: a group of keyword arguments from the request.
        Returns:
            The User object or None
        """

        api_required_attrs = ('facebook_id', 'facebook_token')
        for attr in api_required_attrs:
            if attr not in request_attrs:
                # Any request that fails the other authentication backends will
                # reach here. For example, when logging in to the admin page.
                # In that case, do nothing by returning None
                return None

        #######################################################################
        # At this point, we know the request is from the API
        #######################################################################

        if request_attrs['verify']:
            self.verify_with_facebook(**request_attrs)

        # Used only for testing, timestamp the username so that a new user is
        # always created.
        if request_attrs['timestamped']:
            username = '_'.join([request_attrs['facebook_id'], str(int(time.time()))])
        else:
            username = request_attrs['facebook_id']

        try:
            user = User.objects.get(username=username)
            logger.info("User with username=%s found" % username)

        except User.DoesNotExist:
            user = self.register_user(username=username, **request_attrs)
        return user

    def verify_with_facebook(self, **request_attrs):
        """Connect to facebook's me endpoint to retrieve the user's facebook
        info to verify the token is authentic.

        Args:
            request_attrs: a group of keyword arguments from the request.
        Returns:
            None
        """
        graph = facebook.GraphAPI(access_token=request_attrs['facebook_token'])
        try:
            endpoint = 'me'
            me = graph.get_object(id=endpoint)
            logger.debug("Connected to facebook endpoint=%s" % endpoint)

        except facebook.GraphAPIError as gae:
            msg = _(str(gae))
            raise exceptions.AuthenticationFailed(msg)

        if me['id'] != request_attrs['facebook_id']:
            msg = _("Unable to authenticate with the access token.")
            raise exceptions.AuthenticationFailed(msg)

        logger.info("Token for facebook_id=%s verified" % request_attrs['facebook_id'])

    def register_user(self, username, **request_attrs):
        """
        DEPRECATED, DO NOT USE
        Register the user using information from facebook.

        Note:
            The username is using facebook id.

            Since the info does not include password (a required field
            to create a user), the password is auto-generated based on username
            and fullname.
        Args:
            username: a unique username.
            request_attrs: a group of keyword arguments for additional
                facebook info being passed.
        Returns:
            The User object
        """
        raise JuloDeprecated("julo.backends.ApiV1Backend.register_user is deprecated")
        facebook_data_fields = ['facebook_id', 'fullname', 'email', 'dob', 'gender']
        attrs = {}
        for field in facebook_data_fields:
            if field in request_attrs:
                attrs[field] = request_attrs[field]

        password = '_'.join([username, attrs['fullname']])
        user = User(username=username, password=password)
        user.clean_fields()
        logger.debug("Validated inputs to register user username=%s" % username)

        logger.debug("Registering new user with username=%s" % username)
        user = User.objects.create_user(username=username, password=password)
        if 'email' in attrs:  # if email provided in the parameter
            email = attrs['email']
        else:  # no email provided
            email = None
        customer = Customer.objects.create(user=user, email=email)
        logger.info("User with username=%s registered" % username)
        logger.info("Customer with customerid=%d registered" % customer.id)

        for key in attrs:
            logger.debug("Associating facebook data=%s with username=%s" % (key, username))
        facebook_data = FacebookData(customer=customer, **attrs)
        facebook_data.save()
        logger.info("Facebook data saved with username=%s" % username)
        return user
