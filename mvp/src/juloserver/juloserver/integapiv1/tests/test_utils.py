from django.test import TestCase
import base64
from juloserver.integapiv1.utils import (
    generate_signature_asymmetric,
    verify_asymmetric_signature,
)


class TestSignatureFunctions(TestCase):

    def setUp(self):
        # Replace these keys with your actual keys for testing
        self.private_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAxbPcN5FesqsJS0qVjEjwKG9Z1qpEh1TAOesK3D4L2uQnUJlD
l4645xMdVZaF/E3CxX7hc6XgbP9XUMi0rY97d5IChGyRo+kZ+R6q2FhAtaScaxrO
pYtRBnLpIjeL6RVR3BNs9Wdf6XU8lGOUz0qQzWsjwWuUyzJnEiZsrzZokOco8xdy
LM8PkdXHnxW23tHKptfG1fzY5ExWLelDMsWiyzU0xOReaCPFBwRjL6vbrASjBcVX
yUvFfxQlSP1oQrC7XyrV3OwviwagEg7KheXS80wcafTA1MiowmmEZk5J/VrN6AvB
j/12HnLUoAj4WantfGeUEFZn0NlV2+6WTYh13wIDAQABAoIBAB1QFqWyixzomR8t
ttCu+9Sy9doLMs/x8/JidCDFnlJdI6sink/5XFb+kYngIIuRKADKWDkibg0bKuIS
cB+Pt5m571+dDVcFN9GlB2W+aBHGj16eAeevqVrQbNqi676qZ5G+25fjNOhTdqD1
xtmZT7D1Yr7J6azbE0cwpUqxQX3CVXhUh20FEN/p0Ef81a1JLecAcJaFxEmPJQhm
tgMMG8QqVUjwaOCLf81TWnK3zPMvGBBDFR9gU4R7Qq/5ZckJffhA/kudtL/CDwy/
/s44qjyX2rXOpfPxFqOHW5qunJxKZkPnbRmfQN/s/kSbjEUwgPl9G2CoXXr0CHfw
Etbm3/kCgYEA80OAGmWWB3lEMZ67V4MOG5mwyrJAQsKq87IHNIpbMUXcz2zdlEA3
uQcFJs5UuCoBTR0JG+TE/za40wpdyZBBuX7Wjlz2NUYuwQTM++7cWXoLCWTgtW5c
u6uvdyV2FNrWMSGrvNmOhwKAGzbjpkKTzIrLKhC+8PBQPd0UCMBx1+sCgYEA0A2y
lzQzlLPv0acrkLNXREtYXgpvgRlYtT9SQJARvicoQCm+0YHvW3Z+zp9nbdRDRRCe
X9DjHlxpW+hCrdWSQe3YcMstbOmj0UcwlrSO2aDSpugP96AXSfDQyNUw2kw/yHlm
w0TZJXSUAb1nX0vWFAjfOt9TOcX3NQd0VoQPMN0CgYAr5XhOSxqBir5lfdEsf3ei
P1+JlBTIdzxF8VAfiP/fqk2oGGr7f4MOnletovniqaHGeoDUSbnKm+NKIcq+vos9
n8eztM6w2lNBfU5H/9g/RSiMr2llE98j9l0ZUOc36C1SfFLzJwbzEd5wCr2VmNn2
xOzYUGFENPkl0Kj201M3tQKBgHPzvl3QxRKSOg0hWwFZQkCYsVYwALb1ll/lO4Uq
BglxL1ibK3L+NJVH9CJZ6r3mN9uNCIckFwA7xqhnSIozZkECOseaJOX3TMp9H5JO
bPLTU7Ob0BJVEcWuxd24G3L+Xenv5xrbCx5522cg1TTiQhyGWUspXevr7fuK/Qae
sQytAoGBAIAKpwbx6UlqoxIkVh6VdQx5/C1u8M8FU3f65B1io44roRZZxtcLHLOX
4hiNn3MvsQ1zlsfmwMKN/nrpoiBMbYTT+BVw+u4YlhCGbmxEBD4iYVnm7d754Q/q
Av8FuKlGob2FxcDOvXdaFAbNsN9fMufOQlZqX3Sc2AY5YCGr2Mll
-----END RSA PRIVATE KEY-----"""

        self.public_key = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxbPcN5FesqsJS0qVjEjw
KG9Z1qpEh1TAOesK3D4L2uQnUJlDl4645xMdVZaF/E3CxX7hc6XgbP9XUMi0rY97
d5IChGyRo+kZ+R6q2FhAtaScaxrOpYtRBnLpIjeL6RVR3BNs9Wdf6XU8lGOUz0qQ
zWsjwWuUyzJnEiZsrzZokOco8xdyLM8PkdXHnxW23tHKptfG1fzY5ExWLelDMsWi
yzU0xOReaCPFBwRjL6vbrASjBcVXyUvFfxQlSP1oQrC7XyrV3OwviwagEg7KheXS
80wcafTA1MiowmmEZk5J/VrN6AvBj/12HnLUoAj4WantfGeUEFZn0NlV2+6WTYh1
3wIDAQAB
-----END PUBLIC KEY-----"""

        self.string_to_sign = '{"test": "test1"}'

    def test_signature_verification(self):
        signature = generate_signature_asymmetric(self.private_key, self.string_to_sign)
        result = verify_asymmetric_signature(self.public_key, signature, self.string_to_sign)
        self.assertTrue(result)

    def test_signature_verification_invalid(self):
        invalid_signature = base64.b64encode(b"InvalidSignature").decode()
        result = verify_asymmetric_signature(self.public_key, invalid_signature,
                                             self.string_to_sign)
        self.assertFalse(result)
