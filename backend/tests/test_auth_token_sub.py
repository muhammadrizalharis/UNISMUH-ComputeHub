"""Token dengan klaim `sub` bukan angka harus ditolak 401, bukan galat 500."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from fastapi import HTTPException

from app.core.security import create_access_token


class _NoDb:
    async def get(self, *_args, **_kwargs):
        raise AssertionError("DB tidak boleh disentuh untuk token tak sah")


class _FakeWebSocket:
    def __init__(self, token: str) -> None:
        self.query_params = {"token": token}


class NonNumericSubjectTest(unittest.TestCase):
    def test_http_auth_rejects_non_numeric_sub_with_401(self) -> None:
        from app.api.deps import get_current_user

        token = create_access_token("muhammadrizalharis", "admin", "sid-x")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_user(token=token, session=_NoDb()))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_websocket_auth_rejects_non_numeric_sub(self) -> None:
        from app.api.routers import interactive

        token = create_access_token("muhammadrizalharis", "admin", "sid-x")
        with mock.patch.object(interactive, "AsyncSessionLocal", side_effect=AssertionError):
            user = asyncio.run(interactive._ws_authenticate(_FakeWebSocket(token)))
        self.assertIsNone(user)


if __name__ == "__main__":
    unittest.main()
