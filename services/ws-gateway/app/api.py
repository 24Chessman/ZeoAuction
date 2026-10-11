"""The WebSocket endpoint (SDD 7.8): ``/ws`` (the SPA's default) and ``/api/v1/ws``.

Client -> server: ``subscribe {auction_id, last_seq}``, ``unsubscribe {auction_id}``, ``ping``.
Server -> client: ``price_update``, ``outbid``, ``auction_extended``, ``auction_closed``,
``notification``, ``pong``, and ``error`` for a refused client message.
"""

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.connections import CLOSE_IDLE, HandshakeRefused, Hub, error, token_from, wait_closed

router = APIRouter(tags=["websocket"])


async def serve(websocket: WebSocket) -> None:
    hub: Hub = websocket.app.state.hub
    await websocket.accept()
    try:
        connection = hub.open(websocket, token_from(websocket.query_params, websocket.headers))
    except HandshakeRefused as refused:
        await websocket.close(refused.code, refused.reason)
        return
    writer = asyncio.create_task(connection.write_loop(), name=f"ws-writer-{connection.id}")
    try:
        while connection.close_code is None:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(),
                                             timeout=hub.limits.idle_timeout_seconds)
            except TimeoutError:
                connection.close(CLOSE_IDLE)
                break
            try:
                message = json.loads(raw)
            except ValueError:
                connection.send(error("BAD_REQUEST", "Messages must be JSON"))
                continue
            await hub.handle(connection, message)
    except (WebSocketDisconnect, RuntimeError):
        pass  # the client went away (or the socket closed under us)
    finally:
        hub.release(connection)
        if connection.close_code is not None:
            # Let the writer flush what is queued and send the close frame.
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(writer), timeout=1.0)
        await wait_closed(writer)


@router.websocket("/ws")
async def websocket_root(websocket: WebSocket) -> None:
    await serve(websocket)


@router.websocket("/api/v1/ws")
async def websocket_versioned(websocket: WebSocket) -> None:
    await serve(websocket)
