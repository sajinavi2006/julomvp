from copy import deepcopy
import json
from django.test import TestCase

from juloserver.fraud_score.constants import FeatureNameConst, FraudPIIFieldTypeConst
from juloserver.fraud_score.fraud_pii_masking_services import FraudPIIMaskingRepository
from juloserver.julo.models import FeatureSetting


class TestFraudPIIMaskingRepository(TestCase):
    def setUp(self):
        self.feature_setting = {
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
            },
            "tables": {
                'juicy_score_result': True,
                'grab_defence_entity': True,
                'grab_defence_predict_event_result': True,
                'seon_fraud_raw_result': True,
                'monnai_phone_social_insight': True,
                'monnai_phone_basic_insight': True,
                'monnai_insight_raw_result': True,
                'monnai_email_social_insight': True,
                'monnai_email_basic_insight': True,
                'bureau_email_social': True,
                'bureau_mobile_intelligence': True,
                'bureau_phone_social': True,
            },
        }
        self.feature = FeatureSetting.objects.get_or_create(
            feature_name=FeatureNameConst.FRAUD_PII_MASKING,
            is_active=True,
            parameters=self.feature_setting,
        )
        self.base_repo = FraudPIIMaskingRepository(self.feature_setting)
        self.deafult_map_native = {
            FraudPIIFieldTypeConst.EMAIL: "testjulo@julo.co.id",
            FraudPIIFieldTypeConst.PHONE_NUMBER: "082134567891",
            FraudPIIFieldTypeConst.NAME: "Test Julo Test",
        }
        self.deafult_map_mask = {
            FraudPIIFieldTypeConst.EMAIL: "tes**ulo@julo.co.id",
            FraudPIIFieldTypeConst.PHONE_NUMBER: "0821*****891",
            FraudPIIFieldTypeConst.NAME: "Tes***********",
        }

    def test_get_fraud_regex_pattern_from_config(self):
        fs = deepcopy(self.feature_setting)
        fs.update(
            {
                "first_name": {
                    "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                    "start": 3,
                    "end": 0,
                    "is_active": True,
                    "masking_character": "*",
                    "masking_space": True,
                }
            }
        )
        repo = FraudPIIMaskingRepository(fs)
        self.assertEqual(
            "(?<=^.{3}).*(?=.{0}$)",
            repo.get_fraud_regex_pattern_from_config(
                repo.feature_setting.get(FraudPIIFieldTypeConst.NameField.FIRST_NAME)
            ),
        )
        self.assertEqual(
            "(?<=^.{4}).*(?=.{1}$)",
            repo.get_fraud_regex_pattern_from_config(
                fs.get(FraudPIIFieldTypeConst.NameField.FIRST_NAME), 4, 1
            ),
        )

    def test_mask(self):
        self.assertEqual("value", self.base_repo.mask("feature1", "value"))
        self.assertEqual(
            "value",
            FraudPIIMaskingRepository({"feature1": {"is_active": False}}).mask("feature1", "value"),
        )
        self.assertEqual(
            "value",
            FraudPIIMaskingRepository({"feature1": {"is_active": True}}).mask("feature1", "value"),
        )
        self.assertEqual(
            "value",
            FraudPIIMaskingRepository(
                {
                    "feature1": {
                        "regex_pattern": "",
                        "start": 4,
                        "end": 3,
                        "is_active": True,
                        "masking_character": "*",
                    }
                }
            ).mask("feature1", "value"),
        )
        self.assertEqual(
            "0896*****992",
            FraudPIIMaskingRepository(
                {
                    "feature1": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 4,
                        "end": 3,
                        "is_active": True,
                        "masking_character": "*",
                    }
                }
            ).mask("feature1", "089612345992"),
        )
        self.assertEqual(
            "Ai**",
            FraudPIIMaskingRepository(
                {
                    "feature1": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 3,
                        "end": 0,
                        "is_active": True,
                        "masking_character": "*",
                    }
                }
            ).mask("feature1", "Ai"),
        )
        self.assertEqual(
            "Ai**",
            FraudPIIMaskingRepository(
                {
                    "feature1": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 3,
                        "end": 1,
                        "is_active": True,
                        "masking_character": "*",
                    }
                }
            ).mask("feature1", "Ai"),
        )
        self.assertEqual(
            "A*",
            FraudPIIMaskingRepository(
                {
                    "feature1": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 3,
                        "end": 1,
                        "is_active": True,
                        "masking_character": "*",
                    }
                }
            ).mask("feature1", "A"),
        )
        self.assertEqual(
            "W**k",
            FraudPIIMaskingRepository(
                {
                    "feature1": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 3,
                        "end": 1,
                        "is_active": True,
                        "masking_character": "*",
                    }
                }
            ).mask("feature1", "Work"),
        )
        self.assertEqual(
            "W***",
            FraudPIIMaskingRepository(
                {
                    "feature1": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 4,
                        "end": 0,
                        "is_active": True,
                        "masking_character": "*",
                    }
                }
            ).mask("feature1", "Work"),
        )
        self.assertEqual(
            "***k",
            FraudPIIMaskingRepository(
                {
                    "feature1": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 0,
                        "end": 4,
                        "is_active": True,
                        "masking_character": "*",
                    }
                }
            ).mask("feature1", "Work"),
        )
        self.assertEqual(
            "****",
            FraudPIIMaskingRepository(
                {
                    "feature1": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 0,
                        "end": 0,
                        "is_active": True,
                        "masking_character": "*",
                    }
                }
            ).mask("feature1", "Work"),
        )

    def test_dig_and_set_dict_data(self):
        feature_config = FraudPIIFieldTypeConst.PHONE_NUMBER
        path_key = ["data", "phone", "basic", "phoneNumber"]
        dict_to_dig = {"data": {"phone": {"basic": {"phoneNumber": "089671234567"}}}}
        self.base_repo.dig_and_set_dict_data(
            feature_config, dict_to_dig, path_key, 0, len(path_key)
        )
        self.assertDictEqual(
            dict_to_dig, {"data": {"phone": {"basic": {"phoneNumber": "0896*****567"}}}}
        )
        feature_config = FraudPIIFieldTypeConst.EMAIL
        path_key = ["email"]
        dict_to_dig = {"email": "testjulo@julo.co.id"}
        self.base_repo.dig_and_set_dict_data(
            feature_config, dict_to_dig, path_key, 0, len(path_key)
        )
        self.assertDictEqual(dict_to_dig, {"email": "tes**ulo@julo.co.id"})

    def test_mask_space_from_name(self):
        self.assertEqual(
            "test*",
            FraudPIIMaskingRepository({"first_name": {"masking_space": True}}).mask_space_from_name(
                "first_name", "test"
            ),
        )
        self.assertEqual(
            "test ",
            FraudPIIMaskingRepository(
                {"first_name": {"masking_space": False}}
            ).mask_space_from_name("first_name", "test"),
        )

    def test_process_name_masking(self):
        self.assertEqual(
            "tes**************", self.base_repo.process_name_masking("testo testo testo")
        )
        self.assertEqual(
            "te***",
            FraudPIIMaskingRepository(
                {
                    "first_name": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 2,
                        "end": 0,
                        "is_active": True,
                        "masking_character": "*",
                        "masking_space": True,
                    }
                }
            ).process_name_masking("testo"),
        )
        self.assertEqual(
            "te*** te***",
            FraudPIIMaskingRepository(
                {
                    "first_name": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 2,
                        "end": 0,
                        "is_active": True,
                        "masking_character": "*",
                        "masking_space": False,
                    },
                    "last_name": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 2,
                        "end": 0,
                        "is_active": True,
                        "masking_character": "*",
                    },
                }
            ).process_name_masking("testo testo"),
        )
        self.assertEqual(
            "te*** te*** te***",
            FraudPIIMaskingRepository(
                {
                    "first_name": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 2,
                        "end": 0,
                        "is_active": True,
                        "masking_character": "*",
                        "masking_space": False,
                    },
                    "middle_name": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 2,
                        "end": 0,
                        "is_active": True,
                        "masking_character": "*",
                        "masking_space": False,
                    },
                    "last_name": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 2,
                        "end": 0,
                        "is_active": True,
                        "masking_character": "*",
                    },
                }
            ).process_name_masking("testo testo testo"),
        )
        self.assertEqual(
            "te********* te***",
            FraudPIIMaskingRepository(
                {
                    "first_name": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 2,
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
                        "masking_space": False,
                    },
                    "last_name": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 2,
                        "end": 0,
                        "is_active": True,
                        "masking_character": "*",
                    },
                }
            ).process_name_masking("testo testo testo"),
        )
        self.assertEqual(
            "te*************to",
            FraudPIIMaskingRepository(
                {
                    "first_name": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 2,
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
                        "end": 2,
                        "is_active": True,
                        "masking_character": "*",
                    },
                }
            ).process_name_masking("testo testo testo"),
        )

    def test_process_email_masking(self):
        self.assertEqual(
            "tes**ulo@julo.co.id", self.base_repo.process_email_masking("testjulo@julo.co.id")
        )
        self.assertEqual("inv******ail", self.base_repo.process_email_masking("invalidemail"))
        self.assertEqual(
            "tes***lo@julo.co.id",
            FraudPIIMaskingRepository(
                {
                    "email": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 3,
                        "end": 3,
                        "is_active": True,
                        "masking_character": "*",
                        "mask_at": True,
                        "mask_domain": False,
                    }
                }
            ).process_email_masking("testjulo@julo.co.id"),
        )
        self.assertEqual(
            "tes*****@*******.id",
            FraudPIIMaskingRepository(
                {
                    "email": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 3,
                        "end": 3,
                        "is_active": True,
                        "masking_character": "*",
                        "mask_at": False,
                        "mask_domain": True,
                    }
                }
            ).process_email_masking("testjulo@julo.co.id"),
        )
        self.assertEqual(
            "tes*************.id",
            FraudPIIMaskingRepository(
                {
                    "email": {
                        "regex_pattern": "(?<=^.{<start>}).*(?=.{<end>}$)",
                        "start": 3,
                        "end": 3,
                        "is_active": True,
                        "masking_character": "*",
                        "mask_at": True,
                        "mask_domain": True,
                    }
                }
            ).process_email_masking("testjulo@julo.co.id"),
        )

    def test_process_phone_number_masking(self):
        self.assertEqual(
            "0821*****789", self.base_repo.process_phone_number_masking("082123456789")
        )
        self.assertEqual(
            "62821*****789", self.base_repo.process_phone_number_masking("6282123456789")
        )
        self.assertEqual(
            "+62821*****789", self.base_repo.process_phone_number_masking("+6282123456789")
        )
        self.assertEqual("62", self.base_repo.process_phone_number_masking("62"))

    def dig_and_set_dict_factory(
        self,
        feature_config,
        dict_to_dig_native,
        dict_to_dig_mask,
        path_key,
        current_idx,
        total_length,
    ):
        if current_idx == total_length - 1:
            dict_to_dig_native[path_key[current_idx]] = self.deafult_map_native[feature_config]
            dict_to_dig_mask[path_key[current_idx]] = self.deafult_map_mask[feature_config]
            return

        if not dict_to_dig_native.__contains__(path_key[current_idx]):
            dict_to_dig_native[path_key[current_idx]] = {}
            dict_to_dig_mask[path_key[current_idx]] = {}

        self.dig_and_set_dict_factory(
            feature_config,
            dict_to_dig_native[path_key[current_idx]],
            dict_to_dig_mask[path_key[current_idx]],
            path_key,
            current_idx + 1,
            total_length,
        )

    def __test_save_model(self, model_cls, model_factory, **factory_kwargs):
        for field, items in model_cls.FRAUD_PII_MASKING_FIELDS.items():
            native_data = {}
            mask_data = {}
            for pii_key, key_path in items:
                self.dig_and_set_dict_factory(
                    pii_key, native_data, mask_data, key_path, 0, len(key_path)
                )
            model_mock = model_factory(**factory_kwargs)
            setattr(model_mock, field, native_data)
            model_mock.save()
            data = getattr(model_mock, field)
            if not isinstance(data, dict):
                try:
                    data = json.loads(data)
                except Exception:
                    data = eval(data)
            self.assertDictEqual(data, mask_data)

    def test_save_model_juicy_score_result(self):
        from juloserver.fraud_score.models import JuicyScoreResult
        from juloserver.fraud_score.tests.factories import JuicyScoreResultFactory

        self.__test_save_model(JuicyScoreResult, JuicyScoreResultFactory)

    def test_save_model_grab_defence_entity(self):
        from juloserver.fraud_score.models import GrabDefenceEntity
        from juloserver.fraud_score.tests.factories import GrabDefenceEntityFactory

        self.__test_save_model(GrabDefenceEntity, GrabDefenceEntityFactory, attributes={})

    def test_save_model_grab_defence_predict_event_result(self):
        from juloserver.fraud_score.models import GrabDefencePredictEventResult
        from juloserver.fraud_score.tests.factories import (
            GrabDefencePredictEventResultPIIMaskFactory,
        )

        self.__test_save_model(
            GrabDefencePredictEventResult, GrabDefencePredictEventResultPIIMaskFactory
        )

    def test_save_model_seon_fraud_raw_result(self):
        from juloserver.fraud_score.models import SeonFraudRawResult
        from juloserver.fraud_score.tests.factories import SeonFraudRawResultFactory

        self.__test_save_model(SeonFraudRawResult, SeonFraudRawResultFactory)

    def test_save_model_monnai_phone_social_insight(self):
        from juloserver.fraud_score.models import MonnaiPhoneSocialInsight
        from juloserver.fraud_score.tests.factories import MonnaiPhoneSocialInsightFactory

        self.__test_save_model(MonnaiPhoneSocialInsight, MonnaiPhoneSocialInsightFactory)

    def test_save_model_monnai_phone_basic_insight(self):
        from juloserver.fraud_score.models import MonnaiPhoneBasicInsight
        from juloserver.fraud_score.tests.factories import MonnaiPhoneBasicInsightFactory

        self.__test_save_model(MonnaiPhoneBasicInsight, MonnaiPhoneBasicInsightFactory)

    def test_save_model_monnai_insight_raw_result(self):
        from juloserver.fraud_score.models import MonnaiInsightRawResult
        from juloserver.fraud_score.tests.factories import MonnaiInsightRawResultFactory

        fields = MonnaiInsightRawResult.FRAUD_PII_MASKING_FIELDS
        MonnaiInsightRawResult.FRAUD_PII_MASKING_FIELDS['raw'] = fields['raw'][:8]
        self.__test_save_model(MonnaiInsightRawResult, MonnaiInsightRawResultFactory)
        MonnaiInsightRawResult.FRAUD_PII_MASKING_FIELDS['raw'] = fields['raw'][8:]
        self.__test_save_model(MonnaiInsightRawResult, MonnaiInsightRawResultFactory)
        MonnaiInsightRawResult.FRAUD_PII_MASKING_FIELDS = fields

    def test_save_model_monnai_email_social_insight(self):
        from juloserver.fraud_score.models import MonnaiEmailSocialInsight
        from juloserver.fraud_score.tests.factories import MonnaiEmailSocialInsightFactory

        self.__test_save_model(MonnaiEmailSocialInsight, MonnaiEmailSocialInsightFactory)

    def test_save_model_bureau_email_social(self):
        from juloserver.personal_data_verification.models import BureauEmailSocial
        from juloserver.personal_data_verification.tests.factories import BureauEmailSocialFactory

        self.__test_save_model(BureauEmailSocial, BureauEmailSocialFactory)

    def test_save_model_bureau_mobile_intelligence(self):
        from juloserver.personal_data_verification.models import BureauMobileIntelligence
        from juloserver.personal_data_verification.tests.factories import (
            BureauMobileIntelligenceFactory,
        )

        self.__test_save_model(BureauMobileIntelligence, BureauMobileIntelligenceFactory)

    def test_save_model_bureau_phone_social(self):
        from juloserver.personal_data_verification.models import BureauPhoneSocial
        from juloserver.personal_data_verification.tests.factories import BureauPhoneSocialFactory

        self.__test_save_model(BureauPhoneSocial, BureauPhoneSocialFactory)
