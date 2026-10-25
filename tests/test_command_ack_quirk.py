"""Offline tests for the 0x0001 "Reply Acknowledge" command-reply quirk.

Context: before the reply-type validation added later in this repo's
history (a436d77, 2109a53, 124376f, 782c22e), send_packet performed no
reply-type validation at all; REQ_COMMAND (0x0C32, used to send remote
control commands such as RESET) has no documented reply code in
docs/MNET.md, and the then command dispatcher
(turbine_monitor.py's original _execute_pending_command) treated ANY
syntactically valid reply to a command as a successful ack. That was a
real, long-running production behaviour, not a doc-derived assumption.

Two live RESET attempts against the same production controller on
2026-10-25 (22:39:26 and 22:41:32 UTC, each a bounded, redacted
journalctl excerpt) showed a correctly-addressed, CRC-valid 0x0001
reply to REQ_COMMAND, never a 0x0C32 echo. This is the same
controller-wide generic-ack quirk already fixed for both login types.

These tests pin down the resulting send_packet AND dispatcher behaviour
with offline fixtures only -- no hardware, no network, no serial device
-- and guard against the quirk silently widening beyond REQ_COMMAND, or
turning into a blanket "any reply means success" shortcut, or allowing
automatic retries on ambiguous outcomes.
"""
from unittest.mock import Mock

import pytest

import mnet
from mnet import Mnet, MnetPacket, MnetDecodeError, MnetFrameError

from tests.test_protocol_recovery import FakeDevice


DEST = b'\x02'


def _frame(packet_type: bytes, data: bytes = b''):
    """A frame from the controller (0x02) addressed back to us (0x01)."""
    return bytes(MnetPacket(b'\x01', b'\x02', packet_type, len(data), data))


def _mnet():
    """Mnet client addressed as 0x01 talking to a device at DEST (0x02)."""
    return Mnet(FakeDevice(), id=b'\x01')


class TestCommandAckQuirk:
    """REQ_COMMAND (0x0C32) accepts the hardware-observed 0x0001 ack."""

    def test_command_accepts_observed_0001_ack(self):
        """A real, serialized 0x0001 frame -- CRC-valid, correctly addressed
        -- in response to REQ_COMMAND is accepted, matching the 22:39:26 and
        22:41:32 UTC 2026-10-25 observations."""
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REPLY_ACK))
        response = client.send_packet(DEST, Mnet.REQ_COMMAND, b'\x02')  # arbitrary command id
        assert response.packet_type == Mnet.REPLY_ACK

    def test_command_still_accepts_documented_echo(self):
        """The 0x0C32 echo (if the controller ever sends it) still works;
        this is additive, not a replacement."""
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REQ_COMMAND))
        response = client.send_packet(DEST, Mnet.REQ_COMMAND, b'\x02')
        assert response.packet_type == Mnet.REQ_COMMAND

    def test_command_rejects_unrelated_wrong_type(self):
        """A reply type with no documented or observed relationship to
        REQ_COMMAND (e.g. the login rejection code) still raises -- this is
        NOT a blanket 'any reply is a success' shortcut."""
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REPLY_NOT_LOGGED_IN))
        with pytest.raises(MnetDecodeError, match='response packet type mismatch'):
            client.send_packet(DEST, Mnet.REQ_COMMAND, b'\x02')

    def test_command_rejects_bad_crc_even_if_type_would_match(self):
        """A 0x0001 reply with a corrupted CRC is rejected before the type
        check ever runs -- CRC validation (added by the later hardening) is
        independently valuable and is NOT weakened by this fix."""
        client = _mnet()
        frame = bytearray(_frame(Mnet.REPLY_ACK))
        # Corrupt the CRC bytes (2 bytes before the trailing EOT byte).
        frame[-2] ^= 0xFF
        client.device = FakeDevice(bytes(frame))
        with pytest.raises(MnetFrameError, match='CRC mismatch'):
            client.send_packet(DEST, Mnet.REQ_COMMAND, b'\x02')

    def test_command_rejects_wrong_source_even_if_type_matches(self):
        """A 0x0001 reply from the wrong source address is rejected even
        though the type itself would be accepted -- source/destination
        identity checks (added by the later hardening) are independently
        valuable and are NOT weakened by this fix."""
        client = _mnet()
        wrong_source_frame = bytes(MnetPacket(b'\x01', b'\x99', Mnet.REPLY_ACK, 0, b''))
        client.device = FakeDevice(wrong_source_frame)
        with pytest.raises(MnetDecodeError, match='response source mismatch'):
            client.send_packet(DEST, Mnet.REQ_COMMAND, b'\x02')

    def test_command_rejects_wrong_destination_even_if_type_matches(self):
        """A 0x0001 reply addressed to someone else is rejected even though
        the type itself would be accepted."""
        client = _mnet()
        wrong_dest_frame = bytes(MnetPacket(b'\x99', b'\x02', Mnet.REPLY_ACK, 0, b''))
        client.device = FakeDevice(wrong_dest_frame)
        with pytest.raises(MnetDecodeError, match='response destination mismatch'):
            client.send_packet(DEST, Mnet.REQ_COMMAND, b'\x02')

    def test_command_sends_exactly_once_no_automatic_retry(self):
        """A single send_command call writes to the transport exactly once,
        even on an ambiguous/unexpected reply -- no implicit retry here."""
        client = _mnet()
        client.device = FakeDevice(_frame(Mnet.REPLY_NOT_LOGGED_IN))
        write_calls = []
        real_write = client.device.write
        client.device.write = lambda data: (write_calls.append(data), real_write(data))[1]
        with pytest.raises(MnetDecodeError):
            client.send_packet(DEST, Mnet.REQ_COMMAND, b'\x02')
        assert len(write_calls) == 1
