import asyncio
import json


MAX_MESSAGE_BYTES = 1000000


# Server and client send one JSON object per line.
# This is easier than designing a binary protocol.


async def send_json(writer, message):
    data = json.dumps(message, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("network message is too large")
    writer.write(data + b"\n")
    await writer.drain()


async def receive_json(reader):
    raw = await reader.readline()
    if not raw:
        raise ConnectionError("connection closed")
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("network message is too large")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value
