from datetime import datetime
from rest_framework import serializers
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.core.constants import JWTErrorConstant
from juloserver.user_action_logs.models import MobileUserActionLog


class CustomMobileUserActionLogSerializer(object):

    def __init__(self, data, many=False):
        self.data = data
        self.many = many
        self.valid_data = []
        self.errors = []
        self.error_exist = False

    def is_valid(self):
        self._validate()
        if not self.error_exist:
            return True
        return False

    @property
    def validated_data(self):
        return self.valid_data

    def _validate(self):
        for datum in self.data:
            self.valid_data.append(self._validate_datum(datum))

    def _is_null_or_blank(self, item):
        if item is None or item == "":
            return True
        return False

    def _is_integer(self, item):
        if item is None or item == "":
            return None, True
        if isinstance(item, int):
            return item, True
        if item.isnumeric():
            return int(item), True
        return item, False

    def _validate_datum(self, datum):
        error = {
            "request": datum,
            "reason": {},
            "message": ""
        }

        mandatory_fields = ('date',
                           'appVersion',
                           'deviceBrand',
                           'androidApiLevel',
                           'sessionId',
                           'activityCounter',
                           'module',
                           'activity',
                           'event'
                           )

        for mandatory_field in mandatory_fields:
            if mandatory_field in datum and \
                    not self._is_null_or_blank(datum[mandatory_field]):
                continue
            error["reason"][mandatory_field] = ["is mandatory"]

        numeric_fields = ('customerID',
                          'applicationID',
                          'androidApiLevel',
                          'activityCounter'
                          )
        for numeric_field in numeric_fields:
            item, valid = self._is_integer(datum.get(numeric_field))
            if not valid:
                error["reason"][numeric_field] = ["must be numeric"]
            datum[numeric_field] = item

        if not 'date' in error:
            try:
                datum['date'] = datetime.strptime(datum['date'], '%d-%m-%YT%H:%M:%S.%f%z')
            except ValueError:
                    error["reason"]["date"] = {"invalid time format"}

        if error["reason"]:
            self.error_exist = True
            self.errors.append(error)
            return
        return self._casting_datum(datum)

    def _casting_datum(self, datum):
        datum['log_ts'] = datum.pop('date')
        datum['customer_id'] = datum.pop('customerID', None)
        datum['application_id'] = datum.pop('applicationID', None)
        datum['app_version'] = datum.pop('appVersion')
        datum['android_id'] = datum.pop('androidID', None)
        datum['gcm_reg_id'] = datum.pop('gcmRegId', None)
        datum['device_brand'] = datum.pop('deviceBrand')
        datum['device_model'] = datum.pop('deviceModel', None)
        datum['android_api_level'] = datum.pop('androidApiLevel')
        datum['session_id'] = datum.pop('sessionId')
        datum['activity_counter'] = datum.pop('activityCounter')
        return datum


class MobileUserActionLogSerializer(serializers.Serializer):
    date = serializers.DateTimeField(
        source='log_ts', input_formats=['%d-%m-%YT%H:%M:%S.%f%z'])
    customerID = serializers.IntegerField(
        source='customer_id', allow_null=True)
    applicationID = serializers.IntegerField(
        source='application_id', allow_null=True)
    appVersion = serializers.CharField(source='app_version')
    androidID = serializers.CharField(
        source='android_id', allow_null=True, allow_blank=True)
    gcmRegId = serializers.CharField(
        source='gcm_reg_id', allow_null=True, allow_blank=True)
    deviceBrand = serializers.CharField(source='device_brand')
    deviceModel = serializers.CharField(
        source='device_model', allow_null=True, allow_blank=True)
    androidApiLevel = serializers.IntegerField(source='android_api_level')
    sessionId = serializers.CharField(source='session_id')
    activityCounter = serializers.IntegerField(source='activity_counter')
    module = serializers.CharField()
    activity = serializers.CharField()
    fragment = serializers.CharField(allow_null=True, allow_blank=True)
    view = serializers.CharField(allow_null=True, allow_blank=True)
    event = serializers.CharField()
    extra_params = serializers.JSONField(required=False)


class MobileUserActionLogModelSerializer(serializers.ModelSerializer):
    date = serializers.DateTimeField(
        source='log_ts', input_formats=['%d-%m-%YT%H:%M:%S.%f%z'])
    customerID = serializers.IntegerField(
        source='customer_id', allow_null=True)
    applicationID = serializers.IntegerField(
        source='application_id', allow_null=True)
    appVersion = serializers.CharField(source='app_version')
    androidID = serializers.CharField(
        source='android_id', allow_null=True, allow_blank=True)
    gcmRegId = serializers.CharField(
        source='gcm_reg_id', allow_null=True, allow_blank=True)
    deviceBrand = serializers.CharField(source='device_brand')
    deviceModel = serializers.CharField(
        source='device_model', allow_null=True, allow_blank=True)
    androidApiLevel = serializers.IntegerField(source='android_api_level')
    sessionId = serializers.CharField(source='session_id')
    activityCounter = serializers.IntegerField(source='activity_counter')
    module = serializers.CharField()
    activity = serializers.CharField()
    fragment = serializers.CharField(allow_null=True, allow_blank=True)
    view = serializers.CharField(allow_null=True, allow_blank=True)
    event = serializers.CharField()
    extra_params = serializers.JSONField(required=False)
    class Meta:
        model = MobileUserActionLog
        fields = ('date',
                  'customerID',
                  'applicationID',
                  'appVersion',
                  'androidID',
                  'gcmRegId',
                  'deviceBrand',
                  'deviceModel',
                  'androidApiLevel',
                  'sessionId',
                  'activityCounter',
                  'module',
                  'activity',
                  'fragment',
                  'component',
                  'event',
                  'extra_params'
                  )


class WebUserActionLogSerializer(serializers.Serializer):
    date = serializers.DateTimeField()
    module = serializers.CharField()
    element = serializers.CharField()
    application_id = serializers.IntegerField(required=False, allow_null=True)
    event = serializers.CharField()
    user_identifier_id = serializers.CharField(required=False)
    product = serializers.CharField(required=False)
    attributes = serializers.JSONField(required=False)

    def validate(self, attrs):
        product = attrs.get('product', None)
        application_id = attrs.get('application_id')
        if product != str(ProductLineCodes.GRAB) and not application_id:
            raise serializers.ValidationError(JWTErrorConstant.APPLICATION_ID_REQUIRED)

        return super().validate(attrs)


class AgentAssignWebUserActionLogSerializer(serializers.Serializer):
    date = serializers.DateTimeField()
    module = serializers.CharField()
    element = serializers.CharField()
    event = serializers.CharField()
    application_xid = serializers.IntegerField()
    token = serializers.CharField(
        max_length=64,
        required=False,
        allow_null=True,
        allow_blank=True,
    )
