import json
from pathlib import Path
import sys
import types
import unittest


class _Again(Exception):
    pass


class _ZmqError(Exception):
    pass


# v2_client only needs these symbols when a socket is injected.
sys.modules["zmq"] = types.SimpleNamespace(
    Again=_Again,
    ZMQError=_ZmqError,
    DEALER=1,
    IDENTITY=2,
    LINGER=3,
    RCVTIMEO=4,
    SNDTIMEO=5,
    RCVMORE=6,
)

CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

from v2_client import V2Client  # noqa: E402


class _Envelope:
    def __init__(self):
        self.version = 0
        self.dir = 0
        self.type = 0
        self.payload = b""
        self.task_id = 0
        self.msg_id = 0
        self.correl_id = 0
        self.route = ""
        self.timestamp_ns = 0

    def SerializeToString(self):
        fields = vars(self).copy()
        fields["payload"] = self.payload.hex()
        return json.dumps(fields).encode()

    def ParseFromString(self, payload):
        fields = json.loads(payload.decode())
        fields["payload"] = bytes.fromhex(fields["payload"])
        for name, value in fields.items():
            setattr(self, name, value)


class _Proto:
    DIR_REQUEST = 0
    DIR_RESPONSE = 1
    ControlEnvelopeV2 = _Envelope


class _Socket:
    def __init__(self, response_type=207, correl_delta=0):
        self.response_type = response_type
        self.correl_delta = correl_delta
        self.request = None
        self.reply = None

    def send(self, payload):
        self.request = _Envelope()
        self.request.ParseFromString(payload)
        response = _Envelope()
        response.version = 2
        response.dir = _Proto.DIR_RESPONSE
        response.type = self.response_type
        response.payload = b"reply"
        response.correl_id = self.request.msg_id + self.correl_delta
        self.reply = response.SerializeToString()

    def recv(self):
        return self.reply

    def getsockopt(self, option):
        return 0


class V2ClientTests(unittest.TestCase):
    def test_request_populates_and_checks_v2_envelope(self):
        socket = _Socket()
        client = V2Client(
            _Proto,
            "unused",
            0,
            route="mezz/4",
            socket=socket,
        )
        response = client.request(206, b"request", 207)
        self.assertEqual(response.payload, b"reply")
        self.assertEqual(socket.request.version, 2)
        self.assertEqual(socket.request.dir, _Proto.DIR_REQUEST)
        self.assertEqual(socket.request.type, 206)
        self.assertEqual(socket.request.payload, b"request")
        self.assertEqual(socket.request.route, "mezz/4")
        self.assertNotEqual(socket.request.msg_id, 0)

    def test_request_rejects_wrong_response_type(self):
        client = V2Client(_Proto, "unused", 0, socket=_Socket(999))
        with self.assertRaisesRegex(RuntimeError, "Unexpected response type"):
            client.request(206, b"request", 207)

    def test_request_rejects_bad_correlation(self):
        client = V2Client(
            _Proto,
            "unused",
            0,
            socket=_Socket(correl_delta=1),
        )
        with self.assertRaisesRegex(RuntimeError, "correlation mismatch"):
            client.request(206, b"request", 207)


if __name__ == "__main__":
    unittest.main()
