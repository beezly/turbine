"""Offline tests for the hidden-login 0x0001 "Reply Acknowledge" quirk.

Context: a live turbinepi deploy attempt on 2026-10-25 observed the
controller replying to hidden login (REQ_LOGIN / 0x13A1) requests with the
generic 0x0001 "Reply Acknowledge" type instead of echoing 0x13A1 (see
docs/DEPLOYMENT_REPORT_2026-10-25.md). These tests pin down the resulting
send_packet behaviour with offline fixtures only -- no hardware, no network,
no serial device -- and guard against the quirk silently widening to the
standard (control) login or to a bare generic-ACK-means-success shortcut.
"""
from unittest.mock import Mock

import pytest

import mnet
from mnet import Mnet, MnetPacket, MnetDecodeError, MnetLoginRejectedError

from tests.test_protocol_recovery import FakeDevice


DEST = b'\x02'


def _frame(packet_type: bytes, data: bytes = b''):
    """A frame from the controller (0x02) addressed back to us (0x01)."""
    return bytes(MnetPacket(b'\x01', b'\x02', packet_type, len(data), data))


def _mnet():
    """Mnet client addressed as 0x01 talking to a device at DEST (0x02)."""
    return Mnet(FakeDevice(), id=b'\x01')


class TestHiddenLoginAckQuirk:
    """REQ_LOGIN (0x13A1) accepts the hardware-observed 0x0001 ack."""

    def test_hidden_login_accepts_observed_0001_ack(self):
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REPLY_ACK))
        response = client.send_packet(DEST, Mnet.REQ_LOGIN, b'login-data')
        assert response.packet_type == Mnet.REPLY_ACK

    def test_hidden_login_still_accepts_documented_echo(self):
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REQ_LOGIN))
        response = client.send_packet(DEST, Mnet.REQ_LOGIN, b'login-data')
        assert response.packet_type == Mnet.REQ_LOGIN

    def test_hidden_login_still_rejects_documented_negative(self):
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REPLY_NOT_LOGGED_IN))
        with pytest.raises(MnetLoginRejectedError):
            client.send_packet(DEST, Mnet.REQ_LOGIN, b'login-data')

    def test_hidden_login_rejects_unrelated_wrong_type(self):
        """A reply type with no documented or observed relationship to login
        (e.g. a stray data reply) must still raise, not be silently accepted."""
        client = _mnet()
        client.device = FakeDevice(_frame(b'\x0c\x29', data=b'\x00'))
        with pytest.raises(MnetDecodeError, match='packet type mismatch'):
            client.send_packet(DEST, Mnet.REQ_LOGIN, b'login-data')

    def test_hidden_login_rejects_bad_crc_even_if_type_would_match(self):
        """A corrupted frame must fail CRC validation before packet-type
        validation is ever reached -- the 0x0001 allowance must never mask
        a transport-level framing/CRC error."""
        client = _mnet()
        good = bytearray(_frame(Mnet.REPLY_ACK))
        # Corrupt one of the two CRC bytes (offset -3, before the EOT byte).
        good[-3] ^= 0xFF
        client.device = FakeDevice(bytes(good))
        with pytest.raises(mnet.MnetFrameError):
            client.send_packet(DEST, Mnet.REQ_LOGIN, b'login-data')

    def test_standard_login_does_not_inherit_the_quirk(self):
        """No hardware evidence exists for REQ_LOGIN_STANDARD replying with
        0x0001; it must remain strict (exact echo or 0x1390 only)."""
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REPLY_ACK))
        with pytest.raises(MnetDecodeError, match='packet type mismatch'):
            client.send_packet(DEST, Mnet.REQ_LOGIN_STANDARD, b'login-data')

    def test_standard_login_still_accepts_documented_echo(self):
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REQ_LOGIN_STANDARD))
        response = client.send_packet(DEST, Mnet.REQ_LOGIN_STANDARD, b'login-data')
        assert response.packet_type == Mnet.REQ_LOGIN_STANDARD

    def test_standard_login_still_rejects_documented_negative(self):
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REPLY_NOT_LOGGED_IN))
        with pytest.raises(MnetLoginRejectedError):
            client.send_packet(DEST, Mnet.REQ_LOGIN_STANDARD, b'login-data')

    def test_generic_ack_is_not_treated_as_universal_login_success(self):
        """Guard against over-broad fixes: 0x0001 must only be a valid login
        reply for the specific REQ_LOGIN mapping, never as a fallback for
        every request type (e.g. a plain data request)."""
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REPLY_ACK))
        with pytest.raises(MnetDecodeError, match='packet type mismatch'):
            client.send_packet(DEST, Mnet.REQ_DATA, b'\x9c\x43')
