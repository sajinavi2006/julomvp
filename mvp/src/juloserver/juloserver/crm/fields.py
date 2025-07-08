import datetime
import pytz

from django.utils import timezone
from rest_framework import serializers, ISO_8601
from rest_framework.settings import api_settings

from juloserver.utilities.services import valid_datetime


class DateTimeTimezoneAwareField(serializers.DateTimeField):
    def enforce_timezone(self, value):
        """
        Picking from
        https://github.com/encode/django-rest-framework/blob/a45432b54de88b28bd2e6db31acfe3dbcfc748dd/rest_framework/fields.py#L1147

        When `self.default_timezone` is `None`, always return naive datetimes.
        When `self.default_timezone` is not `None`, always return aware datetimes.
        """
        field_timezone = self.timezone if hasattr(self, 'timezone') else self.default_timezone()

        if field_timezone is not None:
            if timezone.is_aware(value):
                try:
                    return value.astimezone(field_timezone)
                except OverflowError:
                    self.fail('overflow')
            try:
                dt = timezone.make_aware(value, field_timezone)
                # When the resulting datetime is a ZoneInfo instance, it won't necessarily
                # throw given an invalid datetime, so we need to specifically check.
                if not valid_datetime(dt):
                    self.fail('make_aware', timezone=field_timezone)
                return dt
            except Exception as e:
                if pytz and isinstance(e, pytz.exceptions.InvalidTimeError):
                    self.fail('make_aware', timezone=field_timezone)
                raise e
        elif (field_timezone is None) and timezone.is_aware(value):
            return timezone.make_naive(value, datetime.timezone.utc)
        return value

    def to_representation(self, value):
        if not value:
            return None

        output_format = getattr(self, 'format', api_settings.DATETIME_FORMAT)

        if output_format is None or isinstance(value, str):
            return value

        value = self.enforce_timezone(value)

        if output_format.lower() == ISO_8601:
            value = value.isoformat()
            if value.endswith('+00:00'):
                value = value[:-6] + 'Z'
            return value
        return value.strftime(output_format)
