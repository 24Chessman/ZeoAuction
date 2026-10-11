"""#92: authenticated handshake, connection limits, ping/pong and protocol errors."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.support import ALICE, AUCTION, client, token, url


def closed_with(session) -> int:
    with pytest.raises(WebSocketDisconnect) as closed:
        session.receive_json()
    return closed.value.code


@pytest.mark.parametrize("path", ["/ws", "/api/v1/ws"])
def test_a_valid_token_connects_and_pings(path):
    with client() as test, test.websocket_connect(url(path=path)) as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_the_token_can_travel_as_a_bearer_header():
    headers = {"Authorization": f"Bearer {token()}"}
    with client() as test, test.websocket_connect("/ws", headers=headers) as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


@pytest.mark.parametrize(
    "path",
    ["/ws", "/ws?access_token=not-a-jwt", f"/ws?access_token={token()}tampered"],
)
def test_missing_or_invalid_tokens_close_with_4401(path):
    with client() as test, test.websocket_connect(path) as ws:
        assert closed_with(ws) == 4401
    metrics = test.get("/metrics").text
    assert 'ws_handshakes_rejected_total{reason="token"}' in metrics


def test_an_expired_token_closes_with_4401():
    old = token(now=datetime.now(UTC) - timedelta(hours=1))
    with client() as test, test.websocket_connect(f"/ws?access_token={old}") as ws:
        assert closed_with(ws) == 4401


def test_subscribing_after_the_token_expired_closes_with_4401():
    with client() as test, test.websocket_connect(url()) as ws:
        hub = test.app.state.hub
        (connection,) = hub.rooms.of_user(ALICE)
        connection.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        ws.send_json({"type": "subscribe", "auction_id": AUCTION})
        assert closed_with(ws) == 4401


def test_connections_per_user_are_capped():
    with client(max_connections_per_user=2) as test, \
            test.websocket_connect(url()), test.websocket_connect(url()), \
            test.websocket_connect(url()) as third:
        assert closed_with(third) == 4429
        with test.websocket_connect(url(uuid4())) as other_user:
            other_user.send_json({"type": "ping"})
            assert other_user.receive_json() == {"type": "pong"}


def test_closing_frees_the_slot():
    with client(max_connections_per_user=1) as test:
        with test.websocket_connect(url()):
            pass
        with test.websocket_connect(url()) as again:
            again.send_json({"type": "ping"})
            assert again.receive_json() == {"type": "pong"}
        assert test.app.state.hub.rooms.connections_of(ALICE) == 0


def test_flooding_closes_with_4429():
    with client(max_messages_per_second=3) as test, test.websocket_connect(url()) as ws:
        for _ in range(3):
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
        ws.send_json({"type": "ping"})
        assert closed_with(ws) == 4429


def test_silence_closes_with_4408():
    with client(idle_timeout_seconds=0.05) as test, test.websocket_connect(url()) as ws:
        assert closed_with(ws) == 4408


@pytest.mark.parametrize(
    "message",
    [
        {"type": "teleport"},
        {"type": "subscribe"},
        {"type": "subscribe", "auction_id": "not-a-uuid"},
        {"type": "subscribe", "auction_id": AUCTION, "last_seq": "7"},
        {"type": "unsubscribe"},
        [1, 2, 3],
    ],
)
def test_malformed_messages_get_an_error_and_keep_the_connection(message):
    with client() as test, test.websocket_connect(url()) as ws:
        ws.send_json(message)
        assert ws.receive_json()["code"] == "BAD_REQUEST"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_non_json_text_is_an_error():
    with client() as test, test.websocket_connect(url()) as ws:
        ws.send_text("hello")
        assert ws.receive_json()["code"] == "BAD_REQUEST"


def test_rooms_per_connection_are_capped():
    with client(max_subscriptions=1) as test, test.websocket_connect(url()) as ws:
        ws.send_json({"type": "subscribe", "auction_id": AUCTION})
        second = str(uuid4())
        ws.send_json({"type": "subscribe", "auction_id": second})
        refused = ws.receive_json()
        assert (refused["code"], refused["auction_id"]) == ("RATE_LIMITED", second)


def test_connection_gauge_tracks_open_sockets():
    with client() as test:
        with test.websocket_connect(url()) as ws:
            ws.send_json({"type": "ping"})
            ws.receive_json()
            assert "ws_connections 1.0" in test.get("/metrics").text
        assert "ws_connections 0.0" in test.get("/metrics").text
