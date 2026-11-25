"""Web push messages to the browsers and home screen apps of the users (iPhone from iOS 16.4 on).

Off until `KBI_PUSH__SUBJECT` is set. The VAPID key is generated once and kept in the data folder,
so subscriptions keep working across restarts.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import Engine
from sqlmodel import Session, select

from core.config import Settings
from db.models import PushSubscription

log = logging.getLogger(__name__)

KEY_FILE = "vapid_private.pem"


def validate_endpoint(endpoint: str) -> str:
    """Subscriptions must not turn the server into a relay to arbitrary/internal URLs."""
    url = urlsplit(endpoint)
    host = url.hostname or ""
    allowed = host in {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"}
    allowed = allowed or host.endswith(".push.apple.com") or host.endswith(".notify.windows.com")
    if (url.scheme != "https" or not allowed or url.port not in (None, 443)
            or url.username is not None or url.password is not None or url.fragment
            or any(c.isspace() for c in endpoint) or "\\" in endpoint):
        raise ValueError("Unsupported push endpoint; use an HTTPS browser push service.")
    return endpoint


def _load_or_create_key(settings: Settings) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    if settings.push.vapid_private_key:
        return settings.push.vapid_private_key.get_secret_value().encode()
    path: Path = settings.data_dir / KEY_FILE
    if path.exists():
        return path.read_bytes()
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pem)
    path.chmod(0o600)
    log.info("Generated a new VAPID key for push messages in %s", path)
    return pem


def _public_key(pem: bytes) -> str:
    """The application server key the browser needs, URL-safe base64 of the uncompressed point."""
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(pem, password=None)
    raw = key.public_key().public_bytes(  # type: ignore[union-attr]
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def subscription_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


class PushService:
    def __init__(self, settings: Settings, engine: Engine):
        self.settings = settings
        self.engine = engine
        self._pem: bytes | None = None
        self.public_key: str | None = None
        if settings.push.subject:
            try:
                self._pem = _load_or_create_key(settings)
                self.public_key = _public_key(self._pem)
            except Exception:
                log.exception("Push messages are off, the VAPID key could not be loaded")

    @property
    def enabled(self) -> bool:
        return self.public_key is not None

    def subscribe(self, user_id: str, endpoint: str, p256dh: str, auth: str) -> None:
        validate_endpoint(endpoint)
        with Session(self.engine) as session:
            session.merge(
                PushSubscription(
                    id=subscription_id(endpoint), user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth
                )
            )
            session.commit()

    def unsubscribe(self, user_id: str, endpoint: str) -> None:
        with Session(self.engine) as session:
            row = session.get(PushSubscription, subscription_id(endpoint))
            if row is not None and row.user_id == user_id:
                session.delete(row)
                session.commit()

    def count(self, user_id: str) -> int:
        with Session(self.engine) as session:
            return len(session.exec(select(PushSubscription.id).where(PushSubscription.user_id == user_id)).all())

    async def send(self, user_id: str, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
        """Sends a message to every device of the user. Returns how many got it."""
        if not self.enabled:
            return 0
        return await asyncio.to_thread(self._send, user_id, title, body, url, tag)

    def _send(self, user_id: str, title: str, body: str, url: str, tag: str | None) -> int:
        from cryptography.hazmat.primitives import serialization
        from pywebpush import WebPushException, webpush
        from requests import Session as HttpSession

        assert self._pem is not None
        key = serialization.load_pem_private_key(self._pem, password=None)
        der = key.private_bytes(  # type: ignore[union-attr]
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        vapid_key = base64.urlsafe_b64encode(der).rstrip(b"=").decode()
        payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
        delivered = 0
        with Session(self.engine) as session, HttpSession() as http:
            http.max_redirects = 0
            rows = session.exec(select(PushSubscription).where(PushSubscription.user_id == user_id)).all()
            for row in rows:
                try:
                    validate_endpoint(row.endpoint) # Also reject unsafe subscriptions stored before this check.
                    webpush(
                        subscription_info={"endpoint": row.endpoint, "keys": {"p256dh": row.p256dh, "auth": row.auth}},
                        data=payload,
                        vapid_private_key=vapid_key,
                        vapid_claims={"sub": self.settings.push.subject or ""},
                        ttl=6 * 3600,
                        timeout=10,
                        requests_session=http,
                    )
                    delivered += 1
                except WebPushException as e:
                    status = e.response.status_code if e.response is not None else None
                    if status in (404, 410):
                        ### The device unsubscribed or the app was removed from the home screen
                        session.delete(row)
                    else:
                        log.warning("Push message to %s failed: %s", user_id, e)
                except Exception as e:  # noqa: BLE001 - a broken device must not stop the others
                    log.warning("Push message to %s failed: %s", user_id, e)
            session.commit()
        return delivered
