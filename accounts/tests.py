import base64
import hashlib
import time

from django.test import TestCase, override_settings
from django.urls import reverse
from stellar_sdk import Keypair

from accounts.identity import SESSION_CHALLENGE_KEY
from accounts.models import WalletUser
from accounts.signing import decode_signature, verify_signature


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


class SigningHelperTests(TestCase):
    def setUp(self):
        self.kp = Keypair.random()
        self.msg = "Lowbid login abc 123"

    def test_sep53_scheme(self):
        sig = self.kp.sign_message(self.msg)
        self.assertEqual(verify_signature(self.kp.public_key, self.msg, sig), "sep53")

    def test_raw_scheme(self):
        sig = self.kp.sign(self.msg.encode())
        self.assertEqual(verify_signature(self.kp.public_key, self.msg, sig), "raw")

    def test_sha256_scheme(self):
        sig = self.kp.sign(hashlib.sha256(self.msg.encode()).digest())
        self.assertEqual(verify_signature(self.kp.public_key, self.msg, sig), "sha256")

    def test_wrong_key_fails(self):
        sig = Keypair.random().sign_message(self.msg)
        self.assertIsNone(verify_signature(self.kp.public_key, self.msg, sig))

    def test_decode_signature_accepts_base64_and_hex(self):
        sig = self.kp.sign_message(self.msg)
        self.assertEqual(decode_signature(b64(sig)), sig)
        self.assertEqual(decode_signature(sig.hex()), sig)
        self.assertIsNone(decode_signature("not-a-signature"))
        self.assertIsNone(decode_signature(b64(b"short")))


class WalletAuthFlowTests(TestCase):
    def setUp(self):
        self.kp = Keypair.random()
        self.challenge_url = reverse("accounts:challenge")
        self.verify_url = reverse("accounts:verify")

    def _challenge(self) -> str:
        resp = self.client.post(self.challenge_url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["message"].startswith("Lowbid login "))
        return data["message"]

    def _verify(self, address, signature, **extra):
        return self.client.post(
            self.verify_url,
            data={"address": address, "signature": signature, **extra},
            content_type="application/json",
        )

    def test_challenge_requires_post(self):
        self.assertEqual(self.client.get(self.challenge_url).status_code, 405)

    def test_login_with_sep53_signature(self):
        message = self._challenge()
        resp = self._verify(self.kp.public_key, b64(self.kp.sign_message(message)), next="/besoins/")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["created"])
        self.assertEqual(data["next"], "/besoins/")
        self.assertEqual(self.client.session["wallet_address"], self.kp.public_key)
        wallet = WalletUser.objects.get(stellar_address=self.kp.public_key)
        self.assertEqual(self.client.session["wallet_user_id"], wallet.pk)
        self.assertIsNotNone(wallet.last_login_at)
        self.assertNotIn(SESSION_CHALLENGE_KEY, self.client.session)

    def test_login_with_raw_signature(self):
        message = self._challenge()
        resp = self._verify(self.kp.public_key, b64(self.kp.sign(message.encode())))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["ok"])

    def test_second_login_reuses_wallet_user(self):
        message = self._challenge()
        self._verify(self.kp.public_key, b64(self.kp.sign_message(message)))
        self.client.post(reverse("accounts:logout"))
        message = self._challenge()
        resp = self._verify(self.kp.public_key, b64(self.kp.sign_message(message)))
        self.assertFalse(resp.json()["created"])
        self.assertEqual(WalletUser.objects.count(), 1)

    def test_bad_signature_is_400(self):
        message = self._challenge()
        other = Keypair.random()
        resp = self._verify(self.kp.public_key, b64(other.sign_message(message)))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "bad_signature")
        self.assertNotIn("wallet_address", self.client.session)
        self.assertEqual(WalletUser.objects.count(), 0)

    def test_garbage_signature_is_400(self):
        self._challenge()
        resp = self._verify(self.kp.public_key, "zzz")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_signature_encoding")

    def test_invalid_address_is_400(self):
        message = self._challenge()
        resp = self._verify("NOTANADDRESS", b64(self.kp.sign_message(message)))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_address")

    def test_verify_without_challenge_is_400(self):
        resp = self._verify(self.kp.public_key, b64(self.kp.sign_message("Lowbid login x 1")))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "no_challenge")

    @override_settings(WALLET_CHALLENGE_TTL_SECONDS=1)
    def test_expired_challenge_is_400(self):
        message = self._challenge()
        session = self.client.session
        session[SESSION_CHALLENGE_KEY]["ts"] = int(time.time()) - 60
        session.save()
        resp = self._verify(self.kp.public_key, b64(self.kp.sign_message(message)))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "challenge_expired")

    def test_offsite_next_is_dropped(self):
        message = self._challenge()
        resp = self._verify(self.kp.public_key, b64(self.kp.sign_message(message)), next="https://evil.example/")
        self.assertEqual(resp.json()["next"], "")

    def test_logout_clears_session_and_redirects(self):
        message = self._challenge()
        self._verify(self.kp.public_key, b64(self.kp.sign_message(message)))
        resp = self.client.post(reverse("accounts:logout"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("core:landing"))
        self.assertNotIn("wallet_address", self.client.session)

    def test_logout_json_for_fetch(self):
        resp = self.client.post(reverse("accounts:logout"), HTTP_ACCEPT="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])


class WalletRequiredTests(TestCase):
    def setUp(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware

        from accounts.decorators import wallet_required

        self.factory = RequestFactory()
        self.view = wallet_required(lambda request: HttpResponse("secret"))

        def with_session(request):
            SessionMiddleware(lambda r: None).process_request(request)
            request.session.save()
            return request

        self.with_session = with_session

    def test_anonymous_redirects_to_landing_with_next(self):
        request = self.with_session(self.factory.get("/besoins/nouveau/?x=1"))
        resp = self.view(request)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/?next=/besoins/nouveau/%3Fx%3D1")

    def test_anonymous_fetch_gets_401(self):
        request = self.with_session(self.factory.get("/besoins/nouveau/", HTTP_ACCEPT="application/json"))
        self.assertEqual(self.view(request).status_code, 401)

    def test_signed_in_passes(self):
        wallet = WalletUser.objects.create(stellar_address=Keypair.random().public_key)
        request = self.with_session(self.factory.get("/besoins/nouveau/"))
        request.session["wallet_user_id"] = wallet.pk
        request.session["wallet_address"] = wallet.stellar_address
        resp = self.view(request)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"secret")
