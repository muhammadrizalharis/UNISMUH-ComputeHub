import datetime as dt
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, main
from unittest.mock import AsyncMock

from app.api.routers.auth import heartbeat


class HeartbeatTests(IsolatedAsyncioTestCase):
    async def test_first_beat_records_last_seen(self) -> None:
        user = SimpleNamespace(last_seen_at=None)
        session = SimpleNamespace(commit=AsyncMock())
        resp = await heartbeat(session=session, current_user=user)
        self.assertEqual(resp.status_code, 204)
        self.assertIsNotNone(user.last_seen_at)
        session.commit.assert_awaited_once()

    async def test_frequent_beats_are_throttled(self) -> None:
        recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=10)
        user = SimpleNamespace(last_seen_at=recent)
        session = SimpleNamespace(commit=AsyncMock())
        await heartbeat(session=session, current_user=user)
        self.assertEqual(user.last_seen_at, recent)
        session.commit.assert_not_awaited()

    async def test_naive_old_timestamp_is_refreshed(self) -> None:
        old = dt.datetime.utcnow() - dt.timedelta(minutes=5)
        user = SimpleNamespace(last_seen_at=old)
        session = SimpleNamespace(commit=AsyncMock())
        await heartbeat(session=session, current_user=user)
        self.assertNotEqual(user.last_seen_at, old)
        session.commit.assert_awaited_once()


if __name__ == "__main__":
    main()
