"""Google lokal dan persetujuan: DB sementara, provider/SMTP/Docker dimock."""

from __future__ import annotations

import asyncio
import datetime as dt
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, create_engine, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import deps
from app.api.routers import api_router, devbox_ssh, google_auth, interactive, sso, users
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.ratelimit import SlidingWindowRateLimiter
from app.core.schema_sync import _column_ddl, sync_additive_schema
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.models.notification import Notification
from app.models.user import User, UserRole, google_subject_index
from app.services import google_auth as google_service, local_access, user_policy
from app.services.sso import SsoError, SsoIdentity

PASSWORD = "Test-Only-Google-Flow!728"


class GoogleAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        for key, value in {
            "FIRST_ADMIN_EMAIL": "root@example.org", "SSO_ONLY_LOGIN": True,
            "LOGIN_GATE_SUPERADMIN": "test-root", "LOGIN_GATE_ADMIN": "test-admin",
            "GOOGLE_CLIENT_ID": "test-client", "GOOGLE_CLIENT_SECRET": "test-only-client",
            "AUTH_COOKIE_SECURE": False, "AUTH_REFRESH_COOKIE_ENABLED": True,
            "APP_PUBLIC_URL": "http://testserver",
            "API_V1_PREFIX": "",
        }.items():
            stack.enter_context(patch.object(settings, key, value))
        stack.enter_context(patch.object(
            google_auth, "_limiter", SlidingWindowRateLimiter(100, 60, 60),
        ))
        self.provision = stack.enter_context(patch.object(
            local_access.provision, "provision_user", new_callable=AsyncMock,
        ))
        self.deprovision = stack.enter_context(patch.object(
            local_access.provision, "deprovision_user", new_callable=AsyncMock,
        ))
        self.drop_sessions = stack.enter_context(patch.object(
            local_access.kernel_manager, "drop_user_sessions", new_callable=AsyncMock,
        ))
        self.stop_devbox = stack.enter_context(patch.object(
            local_access.devbox_manager, "shutdown_user", new_callable=AsyncMock,
        ))
        stack.enter_context(patch.object(
            users.accounts_svc, "send_credentials_email", new_callable=AsyncMock,
        ))
        deps._auth_active_cache.clear()
        self.addCleanup(deps._auth_active_cache.clear)
        tmp = stack.enter_context(tempfile.TemporaryDirectory(prefix="ch-google-test-"))
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp}/accounts.db", poolclass=NullPool,
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)

        async def prepare() -> None:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            hashed = hash_password(PASSWORD)
            async with self.sessions() as session:
                session.add_all([
                    User(id=1, name="Root", email="root@example.org",
                         hashed_password=hashed, role=UserRole.mahasiswa, can_admin=False),
                    User(id=2, name="Admin", email="admin@example.org",
                         hashed_password=hashed, role=UserRole.admin, can_admin=True),
                    User(id=3, name="Campus", email="campus@example.org", sso_sub="campus-sub",
                         hashed_password=hashed, role=UserRole.mahasiswa),
                    User(id=4, name="Local", email="local@example.org", username="CHlocal",
                         google_sub="google-local", hashed_password=hashed,
                         role=UserRole.mahasiswa, is_local=True),
                    User(id=5, name="Banned", email="banned@example.org", google_sub="google-banned",
                         hashed_password=hashed, role=UserRole.dosen, is_local=True, is_active=False),
                    User(id=6, name="Admin student hat", email="hat@example.org",
                         hashed_password=hashed, role=UserRole.dosen, can_admin=True),
                    User(id=7, name="Inactive admin", email="disabled-admin@example.org",
                         hashed_password=hashed, role=UserRole.admin, can_admin=True, is_active=False),
                ])
                await session.flush()
                for uid in range(1, 8):
                    account = await session.get(User, uid)
                    account.session_token = f"test-sid-{uid}"
                await session.commit()
        asyncio.run(prepare())

        async def test_db():
            async with self.sessions() as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise

        app = FastAPI()
        app.include_router(api_router)
        app.dependency_overrides[get_db] = test_db

        @app.get("/dashboard-auth")
        async def dashboard(user: User = Depends(deps.get_current_session_user)):
            return {"id": user.id}

        @app.get("/feature-auth")
        async def feature(user: User = Depends(deps.get_current_active_user)):
            return {"id": user.id}

        @app.get("/poll")
        async def poll(uid: int = Depends(deps.require_authenticated)):
            return {"id": uid}

        self.client = stack.enter_context(TestClient(app))

    def headers(self, uid: int = 4) -> dict[str, str]:
        token = create_access_token(str(uid), "mahasiswa", f"test-sid-{uid}")
        return {"Authorization": f"Bearer {token}"}

    def google_login(self, email: str = "local@example.org", sub: str = "google-local"):
        start = self.client.get("/auth/google/login", follow_redirects=False)
        self.assertEqual(start.status_code, 302, start.text)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        with patch.object(
            google_auth.google_auth, "complete_login", new_callable=AsyncMock,
            return_value=google_service.GoogleIdentity(sub, email, "Google User"),
        ):
            return self.client.get(
                "/auth/google/callback", params={"code": "test-code", "state": state},
                follow_redirects=False,
            )

    def request(self) -> int:
        response = self.client.post("/access-requests", headers=self.headers(), json={
            "reason": "Memerlukan notebook untuk penelitian.",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_google_signup_is_active_but_locked_without_provisioning(self) -> None:
        response = self.google_login("new@example.org", "google-new")
        token = parse_qs(urlparse(response.headers["location"]).fragment)["access_token"][0]
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200, me.text)
        self.assertTrue(me.json()["is_active"])
        self.assertTrue(me.json()["is_local"])
        self.assertTrue(me.json()["is_google"])
        self.assertFalse(me.json()["access_approved"])
        self.assertFalse(me.json()["is_sso"])
        self.assertEqual(me.json()["role"], "mahasiswa")
        self.provision.assert_not_awaited()
        cookie = response.headers.get_list("set-cookie")
        self.assertTrue(any("HttpOnly" in c and settings.AUTH_REFRESH_COOKIE_NAME in c for c in cookie))

    def test_google_existing_subject_reuses_identity_and_replaces_session(self) -> None:
        response = self.google_login()
        self.assertIn("access_token=", response.headers["location"])
        self.assertEqual(self.client.get("/auth/me", headers=self.headers()).status_code, 401)
        self.assertEqual(self.client.post("/auth/refresh", json={
            "refresh_token": create_refresh_token("4", "mahasiswa", "test-sid-4", 10),
        }, headers={"Cookie": ""}).status_code, 401)
        self.assertEqual(self.client.post("/auth/refresh", json={}).status_code, 200)

    def test_google_never_links_email_or_allows_banned_account(self) -> None:
        for email, sub in [
            ("campus@example.org", "unrelated-sub"),
            ("root@example.org", "root-sub"),
            ("local@example.org", "another-sub"),
            ("banned@example.org", "google-banned"),
        ]:
            with self.subTest(email=email):
                response = self.google_login(email, sub)
                self.assertIn("#error=", response.headers["location"])
                self.assertNotIn("access_token", response.headers["location"])

    def test_google_configuration_pkce_cookie_state_and_error_handling(self) -> None:
        self.assertEqual(self.client.get("/auth/google/status").json(), {"configured": True})
        start = self.client.get("/auth/google/login", follow_redirects=False)
        query = parse_qs(urlparse(start.headers["location"]).query)
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["scope"], ["openid email profile"])
        tx = jwt.decode(self.client.cookies.get("ch_google_tx"), settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        self.assertNotEqual(query["code_challenge"][0], tx["verifier"])
        self.assertEqual(query["nonce"][0], tx["nonce"])
        self.assertIn("HttpOnly", start.headers["set-cookie"])
        with patch.object(google_service, "complete_login", new_callable=AsyncMock) as complete:
            wrong = self.client.get("/auth/google/callback?code=test&state=wrong", follow_redirects=False)
            self.assertIn("#error=", wrong.headers["location"])
            complete.assert_not_awaited()
        with patch.object(settings, "GOOGLE_CLIENT_SECRET", ""):
            self.assertEqual(self.client.get("/auth/google/status").json(), {"configured": False})
            self.assertEqual(self.client.get("/auth/google/login").status_code, 503)
        self.client.cookies.set("ch_google_tx", jwt.encode({
            "type": "google_tx", "state": "old", "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1),
        }, settings.SECRET_KEY, algorithm=settings.ALGORITHM), path="/")
        expired = self.client.get("/auth/google/callback?code=test&state=old", follow_redirects=False)
        self.assertIn("#error=", expired.headers["location"])

    def test_google_rate_limit_stays_blocked(self) -> None:
        with patch.object(google_auth, "_limiter", SlidingWindowRateLimiter(2, 60, 60)):
            self.assertEqual(self.client.get("/auth/google/login", follow_redirects=False).status_code, 302)
            for _ in range(3):
                response = self.client.get("/auth/google/login", follow_redirects=False)
                self.assertEqual(response.status_code, 429)
                self.assertIn("retry-after", response.headers)

    def test_pending_session_dashboard_refresh_and_notifications_are_available(self) -> None:
        for path in ("/auth/me", "/dashboard-auth", "/poll", "/system/announcement",
                     "/system/capabilities", "/jobs/usage", "/jobs/usage/daily",
                     "/monitoring/overview", "/monitoring/system", "/notifications", "/access-requests"):
            with self.subTest(path=path):
                response = self.client.get(path, headers=self.headers())
                self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post("/auth/refresh", json={
            "refresh_token": create_refresh_token("4", "mahasiswa", "test-sid-4", 10),
        }).status_code, 200)
        self.assertFalse(deps._auth_active_cache[4][2])
        with patch.object(deps, "AsyncSessionLocal", self.sessions):
            self.assertFalse(asyncio.run(deps.session_active(4, "test-sid-4")))
        with patch.object(devbox_ssh, "AsyncSessionLocal", self.sessions):
            self.assertFalse(asyncio.run(devbox_ssh._akun_aktif(4)))
            self.assertTrue(asyncio.run(devbox_ssh._akun_aktif(3)))

    def test_all_compute_storage_job_and_feedback_endpoints_are_locked(self) -> None:
        for path in (
            "/feature-auth", "/jobs", "/jobs/42", "/jobs/queue", "/jobs/pools",
            "/interactive/sessions", "/interactive/workspace",
            "/interactive/workspace/quota", "/interactive/workspace/trash",
            "/devbox", "/devbox/desktop-setup", "/feedback/mine",
        ):
            with self.subTest(path=path):
                response = self.client.get(path, headers=self.headers())
                self.assertEqual(response.status_code, 403, response.text)
                self.assertIn("terkunci", response.json()["detail"])
        for path in ("/interactive/sessions", "/devbox/start", "/jobs/folder/init", "/feedback"):
            with self.subTest(path=path):
                response = self.client.post(path, headers=self.headers(), json={})
                self.assertEqual(response.status_code, 403, response.text)
        with patch.object(interactive, "AsyncSessionLocal", self.sessions):
            websocket = MagicMock()
            websocket.query_params = {"token": self.headers()["Authorization"].split()[1]}
            self.assertIsNone(asyncio.run(interactive._ws_authenticate(websocket)))

    def test_request_notifies_every_active_admin_entitlement_atomically(self) -> None:
        self.request()
        async def recipients():
            async with self.sessions() as session:
                return list(await session.scalars(select(Notification.user_id).where(
                    Notification.type == "access_request",
                )))
        self.assertEqual(sorted(asyncio.run(recipients())), [1, 2, 6])
        response = self.client.post("/access-requests", headers=self.headers(), json={"reason": "Duplicate request"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(asyncio.run(recipients())), 3)
        self.assertEqual(self.client.post("/access-requests", headers=self.headers(), json={"reason": "     "}).status_code, 400)
        self.assertEqual(self.client.get("/access-requests", headers=self.headers(3)).status_code, 403)

    def test_admin_can_approve_dosen_and_unlock_without_invalidating_local_session(self) -> None:
        request_id = self.request()
        self.client.get("/poll", headers=self.headers())
        response = self.client.post(f"/access-requests/{request_id}/decision", headers=self.headers(2), json={
            "approved": True, "role": "dosen", "note": "Disetujui untuk penelitian.",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(4, deps._auth_active_cache)
        me = self.client.get("/auth/me", headers=self.headers()).json()
        self.assertTrue(me["access_approved"])
        self.assertEqual(me["role"], "dosen")
        self.assertEqual(self.client.get("/feature-auth", headers=self.headers()).status_code, 200)
        self.provision.assert_awaited_once_with(4)
        own = self.client.get("/access-requests", headers=self.headers()).json()
        self.assertEqual(own[0]["status"], "approved")
        notifications = self.client.get("/notifications", headers=self.headers()).json()
        self.assertTrue(any(n["type"] == "access_decision" for n in notifications))
        self.assertEqual(self.client.post(f"/access-requests/{request_id}/decision", headers=self.headers(2), json={
            "approved": True, "role": "dosen",
        }).status_code, 409)
        async def policy():
            async with self.sessions() as session:
                local = await session.get(User, 4)
                campus = await session.get(User, 3)
                campus.role = local.role
                await session.flush()
                return await user_policy.effective(session, 4), await user_policy.effective(session, 3)
        self.assertEqual(*asyncio.run(policy()))

    def test_reject_then_retry_and_manual_approval_use_same_workflow(self) -> None:
        request_id = self.request()
        self.assertEqual(self.client.post(f"/access-requests/{request_id}/decision", headers=self.headers(2), json={
            "approved": False, "note": "Jelaskan kebutuhan lebih detail.",
        }).status_code, 200)
        self.provision.assert_not_awaited()
        self.stop_devbox.assert_not_awaited()
        next_id = self.request()
        self.assertNotEqual(next_id, request_id)
        grant = self.client.put("/access-requests/users/4", headers=self.headers(2), json={
            "approved": True, "role": "mahasiswa",
        })
        self.assertEqual(grant.status_code, 200, grant.text)
        self.assertEqual(self.client.get("/access-requests", headers=self.headers()).json()[0]["status"], "approved")
        self.client.get("/poll", headers=self.headers())
        revoke = self.client.put("/access-requests/users/4", headers=self.headers(2), json={
            "approved": False,
        })
        self.assertEqual(revoke.status_code, 200, revoke.text)
        self.assertEqual(self.client.get("/dashboard-auth", headers=self.headers()).status_code, 200)
        self.assertEqual(self.client.get("/feature-auth", headers=self.headers()).status_code, 403)
        self.stop_devbox.assert_awaited_once()
        self.drop_sessions.assert_awaited_once_with(4)

    def test_approval_requires_explicit_non_admin_role_and_admin_actor(self) -> None:
        request_id = self.request()
        for payload in ({"approved": True}, {"approved": True, "role": "admin"}):
            response = self.client.post(f"/access-requests/{request_id}/decision", headers=self.headers(2), json=payload)
            self.assertEqual(response.status_code, 400, response.text)
        for uid in (3, 4, 6):
            self.assertEqual(self.client.put("/access-requests/users/4", headers=self.headers(uid), json={
                "approved": True, "role": "dosen",
            }).status_code, 403)
        self.assertEqual(self.client.put("/access-requests/users/3", headers=self.headers(2), json={
            "approved": True, "role": "dosen",
        }).status_code, 400)
        self.assertEqual(self.client.put("/access-requests/users/5", headers=self.headers(2), json={
            "approved": True, "role": "dosen",
        }).status_code, 400)

    def test_local_password_creation_reset_and_cross_door_login_are_rejected(self) -> None:
        self.assertEqual(self.client.post("/users", headers=self.headers(2), json={
            "name": "Local", "email": "new@example.org", "is_local": True,
        }).status_code, 400)
        self.assertEqual(self.client.post("/users/4/reset-password", headers=self.headers(2)).status_code, 400)
        self.assertEqual(self.client.patch("/users/4", headers=self.headers(2), json={
            "password": PASSWORD,
        }).status_code, 400)
        for path in ("/auth/login", "/auth/local/login"):
            response = self.client.post(path, data={"username": "local@example.org", "password": PASSWORD})
            self.assertIn(response.status_code, (401, 403))
        admin = self.client.post("/auth/login", data={
            "username": "admin@example.org", "password": PASSWORD, "client_secret": "test-admin",
        })
        self.assertEqual(admin.status_code, 200, admin.text)
        self.assertEqual(self.client.post("/auth/login", data={
            "username": "campus@example.org", "password": PASSWORD,
        }).status_code, 403)

    def test_account_disable_is_separate_from_approval(self) -> None:
        response = self.client.patch("/users/4", headers=self.headers(2), json={"is_active": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers()).status_code, 401)
        self.assertEqual(self.client.patch("/users/4", headers=self.headers(2), json={
            "is_active": True, "role": "mahasiswa",
        }).status_code, 200)
        self.provision.assert_not_awaited()
        response = self.google_login()
        token = parse_qs(urlparse(response.headers["location"]).fragment)["access_token"][0]
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertTrue(me["is_active"])
        self.assertFalse(me["access_approved"])

    def test_campus_does_not_link_local_google_identity(self) -> None:
        async def check():
            async with self.sessions() as session:
                identity = SsoIdentity(
                    sub="new-campus", email="local@example.org", name="Campus",
                    preferred_username="campus", roles=["dosen"],
                )
                user, reason = await sso._upsert_user(session, identity)
                self.assertIsNone(user)
                self.assertIn("/welcome/user", reason)
                local = await session.get(User, 4)
                self.assertIsNone(local.sso_sub)
                self.assertEqual(local.google_sub, "google-local")
        asyncio.run(check())


class GoogleTokenTests(unittest.TestCase):
    def test_real_signed_google_claims_validate_issuer_audience_nonce_and_expiry(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwks = MagicMock()
        jwks.get_signing_key_from_jwt.return_value.key = key.public_key()
        response = MagicMock()
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        base = {
            "iss": "https://accounts.google.com", "aud": "test-web-client",
            "nonce": "test-nonce", "sub": "google-sub", "email": "me@example.org",
            "email_verified": True, "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=2),
        }
        with patch.object(settings, "GOOGLE_CLIENT_ID", "test-web-client"), \
             patch.object(google_service.httpx, "AsyncClient", return_value=context), \
             patch("app.services.sso._jwk_client", return_value=jwks):
            for changes, allowed in [
                ({}, True), ({"iss": "accounts.google.com"}, True),
                ({"iss": "https://other.example.org"}, False),
                ({"aud": "another-client"}, False), ({"nonce": "wrong"}, False),
                ({"email_verified": False}, False),
                ({"exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)}, False),
            ]:
                with self.subTest(changes=changes):
                    response.json.return_value = {"id_token": jwt.encode({**base, **changes}, key, algorithm="RS256")}
                    if allowed:
                        self.assertEqual(asyncio.run(google_service.complete_login("code", "verifier", "test-nonce")).sub, "google-sub")
                    else:
                        with self.assertRaises(google_service.GoogleAuthError):
                            asyncio.run(google_service.complete_login("code", "verifier", "test-nonce"))

    def complete(self, claims: dict, *, error: Exception | None = None):
        response = MagicMock()
        response.json.return_value = {"id_token": "test-id-token"}
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(google_service.httpx, "AsyncClient", return_value=context), patch.object(
            google_service, "_verify_jwt", return_value=claims, side_effect=error,
        ) as verify:
            result = asyncio.run(google_service.complete_login("code", "verifier", "nonce"))
            self.assertEqual(verify.call_args.kwargs["nonce"], "nonce")
            self.assertEqual(verify.call_args.kwargs["audience"], settings.GOOGLE_CLIENT_ID)
            self.assertEqual(client.post.await_args.kwargs["data"]["code_verifier"], "verifier")
            return result

    def test_verified_identity_normalizes_email(self) -> None:
        identity = self.complete({
            "sub": "stable-sub", "email": "My.Email@GMAIL.COM",
            "email_verified": True, "name": "Google Name",
        })
        self.assertEqual(identity.email, "my.email@gmail.com")

    def test_unverified_missing_identity_wrong_nonce_and_invalid_jwt_are_rejected(self) -> None:
        for claims in ({}, {"sub": "s", "email": "x@example.org", "email_verified": False},
                       {"sub": "", "email": "x@example.org", "email_verified": True}):
            with self.subTest(claims=claims), self.assertRaises(google_service.GoogleAuthError):
                self.complete(claims)
        for error in (SsoError("nonce mismatch"), jwt.InvalidAudienceError(), jwt.InvalidSignatureError()):
            with self.subTest(error=type(error)), self.assertRaises(google_service.GoogleAuthError):
                self.complete({}, error=error)


class GoogleSchemaTests(unittest.TestCase):
    def test_additive_columns_preserve_existing_users_and_index_is_idempotent(self) -> None:
        old = MetaData()
        additions = {"is_local", "google_sub", "access_approved"}
        Table("users", old, *[
            Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable)
            for c in User.__table__.columns if c.name not in additions
        ])
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            old.create_all(conn)
            conn.execute(text(
                "INSERT INTO users (id, name, email, hashed_password, role, is_active, can_admin, created_at) "
                "VALUES (1, 'Existing', 'existing@example.org', 'hash', 'admin', 1, 1, CURRENT_TIMESTAMP)"
            ))
            self.assertEqual(set(sync_additive_schema(conn, Base.metadata)), {f"users.{c}" for c in additions})
            google_subject_index.create(conn, checkfirst=True)
            google_subject_index.create(conn, checkfirst=True)
            self.assertEqual(conn.execute(text(
                "SELECT is_local, access_approved, google_sub, is_active, can_admin FROM users WHERE id=1"
            )).one(), (0, 0, None, 1, 1))
            self.assertEqual(sync_additive_schema(conn, Base.metadata), [])
        self.assertIn("DEFAULT false NOT NULL", _column_ddl(User.__table__.c.access_approved, postgresql.dialect()))


if __name__ == "__main__":
    unittest.main()
