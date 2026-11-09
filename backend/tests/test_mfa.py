"""Tes layanan 2FA/TOTP (app/services/mfa.py) — logika murni, tanpa DB."""

from types import SimpleNamespace
from unittest import TestCase, main

import pyotp

from app.services import mfa


def _fake_user(**kw):
    base = dict(
        id=1,
        email="admin@example.com",
        username="CHadmin",
        mfa_enabled=False,
        totp_secret=None,
        mfa_recovery_codes=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TotpTests(TestCase):
    def test_secret_is_valid_base32(self):
        secret = mfa.generate_secret()
        self.assertIsInstance(secret, str)
        self.assertGreaterEqual(len(secret), 16)
        # Harus bisa dipakai pyotp tanpa error.
        pyotp.TOTP(secret).now()

    def test_verify_accepts_current_code(self):
        secret = mfa.generate_secret()
        code = pyotp.TOTP(secret).now()
        self.assertTrue(mfa.verify_totp(secret, code))

    def test_verify_rejects_wrong_and_empty(self):
        secret = mfa.generate_secret()
        self.assertFalse(mfa.verify_totp(secret, "000000"))
        self.assertFalse(mfa.verify_totp(secret, ""))
        self.assertFalse(mfa.verify_totp(secret, "abcdef"))
        self.assertFalse(mfa.verify_totp(None, "123456"))

    def test_provisioning_uri_contains_issuer_and_secret(self):
        user = _fake_user()
        secret = mfa.generate_secret()
        uri = mfa.provisioning_uri(user, secret)
        self.assertTrue(uri.startswith("otpauth://totp/"))
        self.assertIn(secret, uri)
        self.assertIn("ComputeHub", uri)

    def test_qr_svg_data_uri(self):
        user = _fake_user()
        secret = mfa.generate_secret()
        uri = mfa.provisioning_uri(user, secret)
        data = mfa.qr_svg_data_uri(uri)
        self.assertTrue(data.startswith("data:image/svg+xml;base64,"))


class RecoveryCodeTests(TestCase):
    def test_generate_returns_plain_and_hashes(self):
        plain, hashed = mfa.generate_recovery_codes()
        self.assertEqual(len(plain), mfa.RECOVERY_CODE_COUNT)
        self.assertEqual(len(hashed), mfa.RECOVERY_CODE_COUNT)
        # Hash tidak boleh sama dengan teks (tersimpan ter-hash).
        for p, h in zip(plain, hashed):
            self.assertNotEqual(p, h)

    def test_consume_valid_code_once(self):
        plain, hashed = mfa.generate_recovery_codes()
        user = _fake_user(mfa_recovery_codes=list(hashed))
        first = plain[0]
        self.assertTrue(mfa.consume_recovery_code(user, first))
        # Sekali pakai: kode sama tak bisa dipakai lagi.
        self.assertFalse(mfa.consume_recovery_code(user, first))
        self.assertEqual(len(user.mfa_recovery_codes), mfa.RECOVERY_CODE_COUNT - 1)

    def test_consume_is_case_insensitive(self):
        plain, hashed = mfa.generate_recovery_codes()
        user = _fake_user(mfa_recovery_codes=list(hashed))
        self.assertTrue(mfa.consume_recovery_code(user, plain[0].upper()))

    def test_consume_rejects_unknown(self):
        _, hashed = mfa.generate_recovery_codes()
        user = _fake_user(mfa_recovery_codes=list(hashed))
        self.assertFalse(mfa.consume_recovery_code(user, "dead-beef0"))
        self.assertFalse(mfa.consume_recovery_code(user, ""))

    def test_disable_clears_everything(self):
        _, hashed = mfa.generate_recovery_codes()
        user = _fake_user(
            mfa_enabled=True, totp_secret="ABC", mfa_recovery_codes=list(hashed),
            mfa_enrolled_at="now",
        )
        mfa.disable(user)
        self.assertFalse(user.mfa_enabled)
        self.assertIsNone(user.totp_secret)
        self.assertIsNone(user.mfa_recovery_codes)
        self.assertIsNone(user.mfa_enrolled_at)


if __name__ == "__main__":
    main()
