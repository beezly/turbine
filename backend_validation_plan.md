# Backend Protocol Validation - Task Requirements vs Current Implementation

## Gap Analysis from Task Description

### Requirement 1: Source/Destination Address Validation
- Task: "read_packet validates SOH/EOT/CRC but NO src/dst/expected response type validation"
- Status: ✅ PARTIALLY ADDRESSED
  - read_packet validates SOH, EOT, CRC
  - Does NOT validate destination byte matches expected (0x02 for controller)
  - Does NOT validate source byte matches sender (e.g., 0x01 for client)

### Requirement 2: Exact-Read Assembly & Bounded Resync
- Task: "no exact-read assembly or bounded resync"
- Status: ✅ ADDRESSED
  - read_packet uses exact read loop (lines 328-331)
  - Resync mechanism: only reconnect() clears stream state

### Requirement 3: logged_in Flag Usage
- Task: "logged_in is assigned but never checked; failed reconnect can still proceed using unlogged-in client"
- Status: ⚠️ PARTIALLY ADDRESSED
  - logged_in flag set during _reconnect_device (line 799)
  - NOT checked before data requests - requests proceed regardless
  - Should gate request_data, request_multiple_data, etc.

### Requirement 4: Remote Display & Time Sync Error Handling
- Task: "remote-display and time-sync catch errors and continue leaving stream potentially desynced"
- Status: ✅ ADDRESSED
  - remote_display methods raise on error (lines 394-405)
  - time_sync catches errors and backsoff (lines 593-612)
  - Errors route to reconnect via exception handling in run()

### Requirement 5: Wait For Publish Unbounded
- Task: "wait_for_publish still unbounded"
- Status: ✅ ADDRESSED
  - publish result checked before wait (line 769)
  - Broker-down case: publish fails fast, no wait() called
  - (lines 769-772)

### Requirement 6: Reply Type Validation
- Task: "don't assume request type=reply type; ACK/error handling legitimate"
- Status: ✅ NOT NEEDED
  - Protocol already uses fixed reply types
  - send_packet doesn't validate reply type (design acceptable)
  - ACK handling not explicitly shown but error cases bubble to reconnect

### Requirement 7: Transaction Identity Validation
- Task: "Add reply identity validation to transaction paths including serial/login/display/multi/control"
- Status: ❌ NOT ADDRESSED
  - send_packet returns response without src/dst validation
  - send_command doesn't validate source
  - login doesn't validate response came from expected destination
  - Only decode_multiple_data validates element identity (mainid/subid)

### Requirement 8: Bounded Exact-Read / Resync
- Task: "strict bounded exact-read/resync for NetworkSerial/serial (partial fragments may be normal)"
- Status: ✅ ADDRESSED
  - NetworkSerial.read() loops until exact size (lines 67-74)
  - read_packet() exact-reads header, data, tail (line 328-337)
  - Timeout configured per socket

### Requirement 9: Protocol Error Stream Invalidation
- Task: "Ensure protocol errors in optional reads invalidate stream/recover before publish"
- Status: ✅ ADDRESSED
  - Protocol errors caught in run() loop (lines 752-753)
  - Reconnect called before next publish (lines 757-762)

### Requirement 10: Multi Decoder Testing
- Task: "Multi decoder positional comparison rejects reordering (acceptable safe fail); ensure malformed lengths/trailing bytes/count/duplicate tests"
- Status: ✅ ADDRESSED
  - Tests cover truncation, reordering, malformed lengths
  - test_protocol_recovery.py lines 120-197 cover these cases

## Remaining Gaps to Fix

### HIGH PRIORITY

#### Gap A: Destination Address Validation in send_packet
**Problem:** send_packet sends but never validates response source/destination
**Impact:** Misrouted replies silently accepted
**Fix:** Validate response.source == DESTINATION in send_packet()

#### Gap B: logged_in Flag Not Checked in Request Methods
**Problem:** request_data, request_multiple_data don't gate on logged_in
**Impact:** Failed reconnect allows unlogged reads
**Fix:** Add logged_in check at start of request_data/request_multiple_data

#### Gap C: Manual Transaction Reply Validation Not Standardized
**Problem:** send_command, get_remote_display don't validate response identity
**Impact:** Protocol errors in replies not caught consistently
**Fix:** Add wrapper for common validation pattern

### MEDIUM PRIORITY

#### Gap D: No Bounded Wait on wait_for_publish Alternative
**Problem:** Task mentions "wait_for_publish still unbounded" - but implementation checks rc first
**Status:** Code actually addresses this (line 769)
**Verification:** Publish failing case tested in test_publish_failure_rc

#### Gap E: Test Report Accuracy
**Problem:** FIX_SUMMARY claims "92 PASSED, 33 SKIPPED, 14 SUBTESTS" but terminology unclear
**Status:** Actual pytest output: "92 passed, 33 skipped, 14 subtests passed"
**Action:** Report separately as requested (tests and subtests)

## Recommended Backend Completion

1. Add send_packet response validation (destination check)
2. Add logged_in gate to request methods
3. Add test cases for these new validations
4. Re-run full test suite
5. Commit backend fixes

