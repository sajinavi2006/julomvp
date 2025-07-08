import re

from juloserver.fraud_score.constants import FraudPIIFieldTypeConst


class FraudPIIMaskingRepository:
    """
    Main logic for Anti Fraud PII Masking.
    `feature_setting` is parameter from Feature Setting table.
    Here is the example of parameter:
    ```python
    feature_setting = {
        "first_name": {
            "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
            "start": 3,
            "end": 0,
            "is_active": True,
            "masking_character": "*",
            "masking_space": True,
        },
        "middle_name": {
            "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
            "start": 0,
            "end": 0,
            "is_active": True,
            "masking_character": "*",
            "masking_space": True,
        },
        "last_name": {
            "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
            "start": 0,
            "end": 0,
            "is_active": True,
            "masking_character": "*",
        },
        "phone_number": {
            "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
            "start": 4,
            "end": 3,
            "is_active": True,
            "masking_character": "*",
        },
        "email": {
            "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
            "start": 3,
            "end": 3,
            "is_active": True,
            "masking_character": "*",
            "mask_at": False,
            "mask_domain": False,
        }
    }
    ```
    """

    def __init__(self, feature_setting):
        self.feature_setting = feature_setting
        self.mask_results = {}  # cache the mask result to dict

    def dig_and_set_dict_data(
        self, feature_config, dict_to_dig, path_key, current_idx, total_length
    ):
        """
        This is the main function to mask value in dict.
        Given the list of keys `path_key`, this function
        will dig the `dig_to_dict` and set the masked value in place
        """
        if current_idx == total_length - 1:
            if not isinstance(dict_to_dig, dict):
                return
            if not dict_to_dig.__contains__(path_key[current_idx]):
                return
            value_to_mask = dict_to_dig.get(path_key[current_idx])
            if not value_to_mask:
                return
            if not (isinstance(value_to_mask, str) or isinstance(value_to_mask, int)):
                return
            value_to_mask = str(value_to_mask)
            mask_res = self.mask_results.get(value_to_mask)
            if mask_res:
                dict_to_dig[path_key[current_idx]] = mask_res
                return
            mask_func = getattr(
                self, "process_{feature_config}_masking".format(feature_config=feature_config)
            )
            dict_to_dig[path_key[current_idx]] = mask_func(value_to_mask)
            self.mask_results[value_to_mask] = dict_to_dig[path_key[current_idx]]
            return

        if not isinstance(dict_to_dig, dict):
            return

        self.dig_and_set_dict_data(
            feature_config,
            dict_to_dig.get(path_key[current_idx]),
            path_key,
            current_idx + 1,
            total_length,
        )

    def get_fraud_regex_pattern_from_config(self, feature_setting_config, start=None, end=None):
        regex_pattern = feature_setting_config.get("regex_pattern") or ""

        if start is None:
            start = feature_setting_config.get("start")

        if end is None:
            end = feature_setting_config.get("end")

        return regex_pattern.replace("<start>", str(start)).replace("<end>", str(end))

    def mask(self, feature_config, value_to_mask):
        conf = self.feature_setting.get(feature_config, {}) or {}
        if not conf:
            return value_to_mask
        if conf and not (conf.get("is_active", False) or False):
            return value_to_mask
        if not (
            conf.__contains__("regex_pattern")
            and conf.__contains__("start")
            and conf.__contains__("end")
        ):
            return value_to_mask

        masking_character = conf.get("masking_character", "*") or "*"
        regex_pattern = self.get_fraud_regex_pattern_from_config(conf)
        if not regex_pattern:
            return value_to_mask

        start = conf.get("start")
        end = conf.get("end")
        val_len = len(value_to_mask)
        char_len = val_len - start - end
        if char_len <= 0:
            if val_len == 1 or val_len == 2:
                return value_to_mask + masking_character * val_len

            max_len = val_len // 2
            start = min(start, max_len - 1)
            end = min(end, max_len - 1)
            char_len = val_len - start - end
            regex_pattern = self.get_fraud_regex_pattern_from_config(conf, start, end)

        return re.sub(regex_pattern, masking_character * char_len, value_to_mask)

    def mask_space_from_name(self, feature_key, name):
        fk = self.feature_setting.get(feature_key)
        if fk and fk.get("masking_space"):
            return name + (fk.get("masking_character") or "*")
        return name + " "

    def process_name_masking(self, value_to_mask):
        split_name = value_to_mask.split(' ')
        len_name = len(split_name)

        if len_name == 1:
            return self.mask(FraudPIIFieldTypeConst.NameField.FIRST_NAME, value_to_mask)

        if len_name == 2:
            first, last = split_name
            first = self.mask(FraudPIIFieldTypeConst.NameField.FIRST_NAME, first)
            return self.mask_space_from_name(
                FraudPIIFieldTypeConst.NameField.FIRST_NAME, first
            ) + self.mask(FraudPIIFieldTypeConst.NameField.LAST_NAME, last)

        if len_name >= 3:
            first = self.mask_space_from_name(
                FraudPIIFieldTypeConst.NameField.FIRST_NAME,
                self.mask(FraudPIIFieldTypeConst.NameField.FIRST_NAME, split_name[0]),
            )
            for middle in split_name[1:-1]:
                first += self.mask_space_from_name(
                    FraudPIIFieldTypeConst.NameField.MIDDLE_NAME,
                    self.mask(FraudPIIFieldTypeConst.NameField.MIDDLE_NAME, middle),
                )
            return first + self.mask(FraudPIIFieldTypeConst.NameField.LAST_NAME, split_name[-1])

        return value_to_mask

    def process_email_masking(self, value_to_mask):
        email_conf = self.feature_setting.get(FraudPIIFieldTypeConst.EMAIL)
        email_split = value_to_mask.split("@")
        len_email = len(email_split)

        if len_email == 1:
            return self.mask(FraudPIIFieldTypeConst.EMAIL, value_to_mask)

        if len_email > 1:
            email = email_split[0]
            mask_at = "@" in value_to_mask and email_conf.get("mask_at")
            if mask_at:
                email += "@"

            domain = "".join(email_split[1:])
            if not email_conf.get("mask_domain"):
                email = self.mask(FraudPIIFieldTypeConst.EMAIL, email)
                if mask_at:
                    return email + domain
                return email + "@" + domain

            email = self.mask(FraudPIIFieldTypeConst.EMAIL, email + domain)
            if mask_at:
                return email

            len_divider = -1 * len(domain)
            return email[:len_divider] + "@" + email[len_divider:]

        return value_to_mask

    def process_phone_number_masking(self, value_to_mask):
        if len(value_to_mask) < 3:
            return value_to_mask

        prefix = value_to_mask[:3]
        if prefix == "+62":
            return "+6" + self.mask(FraudPIIFieldTypeConst.PHONE_NUMBER, value_to_mask[2:])

        if prefix[:2] == "62":
            return "6" + self.mask(FraudPIIFieldTypeConst.PHONE_NUMBER, value_to_mask[1:])

        if prefix[0] == "+":
            return "+" + self.mask(FraudPIIFieldTypeConst.PHONE_NUMBER, value_to_mask[1:])

        return self.mask(FraudPIIFieldTypeConst.PHONE_NUMBER, value_to_mask)

    def process_ktp_masking(self, value_to_mask):
        return self.mask(FraudPIIFieldTypeConst.KTP, value_to_mask)
