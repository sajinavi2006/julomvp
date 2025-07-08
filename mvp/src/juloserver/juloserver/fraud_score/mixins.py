import json
import logging
import traceback
from django.contrib.postgres.fields import JSONField
from juloserver.fraud_score.fraud_pii_masking_services import FraudPIIMaskingRepository
from juloserver.julo.models import FeatureSetting
from juloserver.fraud_score.constants import FeatureNameConst
from juloserver.julo.clients import get_julo_sentry_client


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class FraudPIIMaskingModelMixin(object):
    """
    This is the mixin for models that want to implement masking for PII field.
    For each models that inherit this mixin, should add class-level field: FRAUD_PII_MASKING_FIELDS.
    This field contains dictionary of the model field that want to mask and list of
    tuple containing type of pii field and list of keys to get the value from dict.
    Note that, this mixin limited to model field that implement JSONField or
    string/text field with json-like value. Currently, the implementation support
    only several PII: name, email, and phone_number
    For Example
    ```python
    FRAUD_PII_MASKING_FIELDS = {
        "raw_response": [
            ("phone_number", ["data", "phone", "basic", "phoneNumber"])
        ]
    }
    ```
    which will mask the `raw_response` field that possibly contains value:
    ```json
    {
        "data": {
            "phone": {
                "basic": {
                    "phoneNumber": 62812356478
                }
            }
        }
    }
    ```
    will be masked to:
    ```json
    {
        "data": {
            "phone": {
                "basic": {
                    "phoneNumber": 62812***478
                }
            }
        }
    }
    ```
    the *** is configurable in feature setting.
    """

    FRAUD_PII_MASKING_FIELDS = {}

    def get_fraud_pii_masking_fields(self):
        """
        We can override this method if we want to implement
        custom get field rather than using constant
        on class-level variable
        """
        if not hasattr(self, 'FRAUD_PII_MASKING_FIELDS'):
            return {}
        return self.FRAUD_PII_MASKING_FIELDS

    def mask_data_pre_save(self):
        feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.FRAUD_PII_MASKING, is_active=True
        )

        if not feature_setting:
            return

        if feature_setting and feature_setting.parameters:
            tables = feature_setting.parameters.get('tables')
            if not tables or (tables and not tables.get(self._meta.db_table)):
                return

        fraud_pii_fields = self.get_fraud_pii_masking_fields()
        if not fraud_pii_fields or (fraud_pii_fields and not isinstance(fraud_pii_fields, dict)):
            return

        maskingapp = FraudPIIMaskingRepository(feature_setting=feature_setting.parameters)
        for field, item in fraud_pii_fields.items():
            data = getattr(self, field, None)
            if not data:
                continue
            if not isinstance(data, dict) and isinstance(data, str):
                # data can come from TextField, not only JsonField
                # so need to transform it into python dictionary
                try:
                    data = json.loads(data)
                except Exception:
                    try:
                        data = eval(data)
                        if not isinstance(data, dict):
                            continue
                    except Exception:
                        continue
                if not data or not isinstance(data, dict):
                    continue
            for feature_config, key_path in item:
                maskingapp.dig_and_set_dict_data(
                    feature_config=feature_config,
                    dict_to_dig=data,
                    path_key=key_path,
                    current_idx=0,
                    total_length=len(key_path),
                )
            if self._meta.get_field(field).__class__ != JSONField:
                setattr(self, field, json.dumps(data))
                continue
            setattr(self, field, data)

    def save(self, *args, **kwargs):
        is_error = False
        err_value = None
        try:
            # make sure that masking process
            # will not block the save
            self.mask_data_pre_save()
        except Exception:
            sentry_client.captureException()
            is_error = True
            err_value = traceback.format_exc()

        super().save(*args, **kwargs)

        if is_error:
            # need to manually retroload
            # if masking process is error
            # so we should expose the table
            # and id to log
            if not self.pk:
                self.refresh_from_db()
            logger.error(
                {
                    'action': 'error_store_pii_masking_data',
                    'db_table': self._meta.db_table,
                    'id': self.id,
                    'error': str(err_value or ''),
                }
            )
            return

        logger.info(
            {
                'action': 'success_store_pii_masking_data',
                'db_table': self._meta.db_table,
                'id': self.pk,
            }
        )
