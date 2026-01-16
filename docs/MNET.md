# M-Net Protocol (PRTCL001)

## Overview

M-Net is the primary communication protocol for WP3000 and IC1000 wind turbine controllers. It uses a request/reply pattern over serial connections (modem or direct).

## Protocol Architecture

### WPMSENTRY Dispatcher

The main entry point `WPMSENTRY` (1010:a414) handles these command codes:

| Code | Hex | Function | Purpose |
|------|-----|----------|---------|
| 10 | 0x0A | FUN_1010_a386 | Data retrieval |
| 11 | 0x0B | FUN_1010_a3d9 | Data processing |
| 20 | 0x14 | FUN_1010_9eb0 | Create connection |
| 21 | 0x15 | FUN_1010_9fa5 | Destroy connection |
| 31 | 0x1F | FUN_1010_9ff3 | Configuration |
| 32 | 0x20 | FUN_1010_a0fb | String lookup |
| 33 | 0x21 | FUN_1010_a279 | Data iteration |
| 34 | 0x22 | FUN_1010_a085 | Reset/clear |

### Connection Management

- Up to 16 simultaneous connections supported
- Connection slots stored at DAT_1050_7854/7856 (array of 32-bit handles)
- Each connection has a ~0x700 byte state structure

## Configuration Parameters

Read from INI file by FUN_1010_b035:

| Parameter | Default | Description |
|-----------|---------|-------------|
| PCNode | 251 (0xFB) | PC node address in M-Net network |
| PacketSendDelay | 50ms | Delay between packet transmissions |
| MaxRetries | 3 | Maximum retry attempts |
| MaxAlarmRetries | 6 | Maximum alarm retry attempts |
| FixedMNetPacketTimeOut | 0 | Fixed timeout (0=adaptive) |
| MNetPacketTimeOutAdjust | 8 | Timeout adjustment factor |
| ExtraMNetPacketTimeOutStep | 1000ms | Additional timeout per retry |
| MaxDataItemCount | 19 | Maximum data items per request |
| HiddenLogin | 0 | Enable hidden login mode |
| DebugMNetPacketTypes | 0 | Enable packet type logging |
| ConvertAlarmState | 1 | Convert alarm states |

## Message Types

Located at 1050:1877 in the binary:

| Type | Request | Reply |
|------|---------|-------|
| 1 | Request define packet | Reply define packet |
| 2 | Request packet | Reply packet |
| 3 | Request data | Reply data |
| 4 | Request multiple data | Reply multiple data |
| 5 | Request write data | Reply write data |
| 6 | Request datalog info | Reply datalog info / n/a |
| 7 | Request datalog data | Reply datalog data / n/a |
| 8 | Request log1000 info | Reply log1000 info / n/a |
| 9 | Request log1000 data | Reply log1000 data / n/a |
| 10 | Get digital i/o text | Reply digital i/o text |
| 11 | Get analog i/o text | Reply analog i/o text |
| 12 | Get analog i/o unit text | Reply analog i/o unit text |
| 13 | Request serial no. | Reply serial no. |
| 14 | Remote login | Remote hidden login / Remote logout / Remote not logged in |
| 15 | Request alarm data (1:4) | Reply alarm data (1:4) |
| 16 | Request alarm data (2:4) | Reply alarm data (2:4) |
| 17 | Request alarm data (3:4) | Reply alarm data (3:4) |
| 18 | Request alarm data (4:4) | Reply alarm data (4:4) |
| 19 | Acknowledge alarm | Reply Acknowledge |
| 20 | Request alarm code | Reply alarm code |

## Debug Logging Format

```
Send MNet packet %04x (%u) "%s"
Recv MNet packet %04x (%u) "%s"
```

- First field: 16-bit packet type (hex)
- Second field: Packet length (unsigned decimal)
- Third field: Message type name string

## Data Point ID Mapping

FUN_1010_0a29 handles data point ID to internal type mapping:

| ID Range | Decimal | Internal Type | Description |
|----------|---------|---------------|-------------|
| 0x4e2a-0x4e2b | 20010-20011 | 12 | Status codes |
| 0x4e3e | 20030 | Special | Flag 0x100 |
| 0x4e85-0x4e87 | 20101-20103 | x100 multiplier | |
| 0x4e89-0x4e8b | 20105-20107 | x100+1 multiplier | |
| 0x7603 | 30211 | 50000 | |
| 0x7604 | 30212 | 50000 | x100+10 |
| 0x7605 | 30213 | 50000 | x100+20 |
| 0x760d-0x760f | 30221-30223 | 50000 | Various offsets |
| 0x84d0 | 34000 | - | Weather data |
| 0x9c41-0x9c42 | 40001-40002 | - | Production/Wind speed |
| 0xf232 | 62002 | Flag 0x20000 | |
| 0xf23a | 62010 | Flag 0x4000 | |
| 0xf244 | 62020 | Flag 0x8000 | |
| 0xf24e | 62030 | Flag 0x10000 | |
| 62000 | 62000 | Flag 0x10 | |

## Access Control

Data point access is controlled by:
- DAT_1050_10ce - General data access flag
- DAT_1050_10d0 - Special function access flag
- DAT_1050_10d2 - Weather data access flag (34000)
- DAT_1050_10d6 - Extended data access flag
- DAT_1050_10d8 - Configuration access flag
- DAT_1050_10da - Advanced feature flag

Access validation uses `TMitaKey::ConfirmAccess()` for protected data points.

## Key Functions

### Discovered and Named Functions

| Address | Function | Purpose |
|---------|----------|---------|
| 1010:a414 | WPMSENTRY | Main dispatcher (command codes 0x0A-0x22) |
| 1010:9eb0 | MNet_CreateConnection | Create new connection |
| 1010:9fa5 | MNet_DestroyConnection | Destroy connection |
| 1010:15ae | MNet_InitProtocolHandler | Protocol handler initialization |
| 1010:9ac5 | MNet_ProcessDataItem | Data processing handler |
| 1010:087e | MNet_InitDataItem | Initialize TDataItem structure |
| 1010:0a29 | MNet_MapDataPointID | Data point ID to internal type mapper |
| 1010:b035 | MNet_LoadConfig | Configuration loader from INI file |
| 1010:9ff3 | MNet_Configure | Configuration handler |
| 1010:a0fb | MNet_StringLookup | String lookup by ID |
| 1010:a279 | MNet_DataIteration | Data iteration |
| 1010:a085 | MNet_ResetClear | Reset/clear handler |
| 1010:ac5c | REMOTECOMMAND | Remote command dispatch |
| 1010:ba13 | MNet_FindInCollection | Search collection for item |
| 1010:b95a | MNet_AddToCollection | Add item to collection |
| 1010:b5de | MNet_ResizeArray | Resize dynamic array |
| 1010:1d47 | MNet_TriggerCallback | Invoke callback function |

### Packet Handling Functions (Confirmed via Ghidra Decompilation)

| Address | Function | Purpose |
|---------|----------|---------|
| 1010:0000 | MNet_GetPacketTypeName | Map packet type code to name string |
| 1010:03da | MNet_BuildPacket | Construct outgoing packet |
| 1010:0472 | MNet_FinalizeCRC | Calculate and append CRC to packet |
| 1010:04d4 | MNet_ResetPacketBuffer | Reset packet buffer state |
| 1010:0539 | MNet_ValidatePacket | Validate incoming packet (SOF/EOF/CRC) |
| 1010:07f3 | MNet_SendPacket | Transmit packet via serial port |
| 1010:39c8 | MNet_ReceivePacket | Receive and dispatch packet |
| 1010:1d84 | MNet_SelectHandlerTable | Select function table based on operation |
| 1010:3e2a | MNet_BuildLoginPacket | Construct login request packet |

**Note:** 163+ additional undiscovered functions exist in segment 1010 (identified by Borland prologue pattern `45 55 8B EC 1E 8E D8`).

## C++ Classes

- `TMNetProtocol` - Main protocol handler class
- `TDataItem` - Individual data point container
- `TDevInstance` - Device instance management
- `TIArrayAsVector<TDataItem>` - Data item collection

## Packet Format

Based on reverse engineering of `MNet_ValidatePacket` (1010:0539) and `MNet_FinalizeCRC` (1010:0472):

### Wire Format (Serial Line)

```
+------+------+------+------+------+------+---------+----------+----------+------+
| SOF  | SRC  | DST  | TYPE | TYPE | LEN  | PAYLOAD | CRC_HI   | CRC_LO   | EOF  |
| 0x01 | addr | addr | (hi) | (lo) | (n)  | n bytes |          |          | 0x04 |
+------+------+------+------+------+------+---------+----------+----------+------+
byte 0   1      2      3      4      5     6..5+n     6+n        7+n       8+n
```

### Field Details

| Byte | Size | Field | Description |
|------|------|-------|-------------|
| 0 | 1 | SOF | Start of Frame marker: `0x01` |
| 1 | 1 | SRC | Source node address (turbine typically 0x01) |
| 2 | 1 | DST | Destination node address (PC default: 0xFB/251) |
| 3-4 | 2 | TYPE | Packet type code (big-endian, see table below) |
| 5 | 1 | LEN | Payload length (0-255 bytes) |
| 6 to 5+n | n | PAYLOAD | Message-specific data |
| 6+n | 1 | CRC_HI | CRC-CCITT high byte |
| 7+n | 1 | CRC_LO | CRC-CCITT low byte |
| 8+n | 1 | EOF | End of Frame marker: `0x04` |

**Total packet size:** 9 + payload length bytes

### CRC Coverage

CRC-CCITT is calculated over bytes 1 through 5+n (inclusive):
- Source address (1 byte)
- Destination address (1 byte)
- Packet type (2 bytes)
- Payload length (1 byte)
- Payload data (n bytes)

**Excludes:** SOF (byte 0), CRC itself, and EOF

```c
crc = CRC16_Calculate(0, packet + 1, 5 + payload_length);
```

### Internal Buffer Layout

The session object maintains packet buffers at these offsets:
- **Outgoing buffer:** session + 0x266 (bytes 0-1 are internal state)
- **Incoming buffer:** session + 0x47c (bytes 0-1 are internal state)
- **Buffer counter:** buffer + 0x212 (tracks bytes received)

Wire packet data starts at buffer offset 2 (SOF marker).

### Packet Type Codes

16-bit codes (big-endian) mapped by `MNet_GetPacketTypeName` (1010:0000):

| Code | Hex | Message Type |
|------|-----|--------------|
| 1 | 0x0001 | Reply Acknowledge |
| 3050 | 0x0BEA | Acknowledge alarm |
| 3051 | 0x0BEB | Request alarm code |
| 3052 | 0x0BEC | Reply alarm code |
| 3067 | 0x0BFB | Request alarm data (1:4) |
| 3068 | 0x0BFC | Reply alarm data (1:4) |
| 3069 | 0x0BFD | Request alarm data (2:4) |
| 3070 | 0x0BFE | Reply alarm data (2:4) |
| 3071 | 0x0BFF | Request alarm data (3:4) |
| 3072 | 0x0C00 | Reply alarm data (3:4) |
| 3073 | 0x0C01 | Request alarm data (4:4) |
| 3074 | 0x0C02 | Reply alarm data (4:4) |
| 3106 | 0x0C22 | Request define packet |
| 3107 | 0x0C23 | Reply define packet |
| 3108 | 0x0C24 | Request packet |
| 3109 | 0x0C25 | Reply packet |
| 3110 | 0x0C26 | Undefined |
| 3112 | 0x0C28 | Request data |
| 3113 | 0x0C29 | Reply data |
| 3114 | 0x0C2A | Request multiple data |
| 3115 | 0x0C2B | Reply multiple data |
| 3116 | 0x0C2C | Request write data |
| 3117 | 0x0C2D | Reply write data |
| 3118 | 0x0C2E | Request serial no. |
| 3119 | 0x0C2F | Reply serial no. |
| 5006 | 0x138E | Remote login |
| 5007 | 0x138F | Remote logout |
| 5008 | 0x1390 | Remote not logged in |
| 5009 | 0x1391 | Reply log1000 data n/a |
| 5010 | 0x1392 | Reply log1000 data |
| 5011 | 0x1393 | Request log1000 data |
| 5012 | 0x1394 | Reply log1000 info n/a |
| 5013 | 0x1395 | Reply log1000 info |
| 5014 | 0x1396 | Request log1000 info |
| 5015 | 0x1397 | Reply datalog data n/a |
| 5016 | 0x1398 | Reply datalog data |
| 5017 | 0x1399 | Request datalog data |
| 5018 | 0x139A | Reply datalog info n/a |
| 5019 | 0x139B | Reply datalog info |
| 5020 | 0x139C | Request datalog info |
| 5025 | 0x13A1 | Remote hidden login |
| 5027 | 0x13A3 | Get digital i/o text |
| 5028 | 0x13A4 | Reply digital i/o text |
| 5029 | 0x13A5 | Get analog i/o text |
| 5030 | 0x13A6 | Reply analog i/o text |
| 5031 | 0x13A7 | Get analog i/o unit text |
| 5032 | 0x13A8 | Reply analog i/o unit text |

### Example Packets

**Request Data (message type 3):**
```
01 01 FB 0C 28 04 [4 bytes payload] [CRC-HI] [CRC-LO] 04
│  │  │  │  │  │
│  │  │  │  │  └─ Payload length = 4
│  │  │  └──┴──── Type = 0x0C28 (Request data)
│  │  └────────── Destination = 0xFB (PC)
│  └───────────── Source = 0x01 (Turbine)
└──────────────── SOF marker
```

**Reply Data (message type 3):**
```
01 FB 01 0C 29 XX [XX bytes payload] [CRC-HI] [CRC-LO] 04
│  │  │  │  │
│  │  │  └──┴──── Type = 0x0C29 (Reply data)
│  │  └────────── Destination = 0x01 (Turbine)
│  └───────────── Source = 0xFB (PC)
└──────────────── SOF marker
```

### Debug Format

The debug logging format `"Send/Recv MNet packet %04x (%u) \"%s\""` shows:
- **%04x**: 16-bit packet type in hex
- **%u**: Packet length in decimal bytes
- **%s**: Message type name string from lookup table

## CRC Algorithm

**Location:** `CRC16_Calculate` at 1048:0000

### Algorithm Details

- **Type:** CRC-16 with 256-entry lookup table
- **Polynomial:** **CRC-CCITT (0x1021)** ✓ Confirmed
- **Table Address:** 1050:4728 (512 bytes, file offset 0x30128)
- **Initial Value:** 0x0000
- **Byte Order:** Big-endian (high byte stored first in packet)

### CRC Table Verification

First 8 table entries match standard CRC-CCITT:
```
Index:  0      1      2      3      4      5      6      7
Value:  0x0000 0x1021 0x2042 0x3063 0x4084 0x50A5 0x60C6 0x70E7
```

### Assembly Implementation

```asm
; CRC16_Calculate(initial, buffer, segment, length)
; Returns: AX = 16-bit CRC
loop:
    MOV DL, ES:[BX]           ; Load byte from buffer
    INC BX                     ; Next byte
    XOR DL, AH                 ; XOR with CRC high byte
    XOR DH, DH                 ; Clear DH
    MOV SI, DX                 ; SI = table index (0-255)
    SHL SI, 1                  ; SI *= 2 (word table)
    MOV DX, [SI + 0x4728]      ; Lookup in CRC table
    MOV AH, AL                 ; Shift CRC: AH = AL
    XOR AL, AL                 ; AL = 0
    XOR AX, DX                 ; XOR with table value
    LOOP loop                  ; Repeat for all bytes
```

### CRC Scope

CRC is calculated over `(Length + 5)` bytes starting at offset 3:
- Includes: Node address, payload, and some header bytes
- Excludes: SOF marker (0x01), CRC itself, EOF marker (0x04)

### Validation (from MNet_ValidatePacket)

```c
crc = CRC16_Calculate(0, buffer + 3, segment, length + 5);
if ((crc >> 8) != buffer[length + 8]) return ERROR_INVALID_CRC;  // High byte
if ((crc & 0xFF) != buffer[length + 9]) return ERROR_INVALID_CRC; // Low byte
```

### Error Codes

| Code | Meaning |
|------|---------|
| 0 | Success / Node mismatch |
| 1 | Empty buffer |
| 2 | Buffer too small (< 9 bytes) |
| 4 | **Invalid CRC** |
| 5 | Invalid length / Missing EOF |
| 6 | Packet accepted |

### Serial I/O Layer

Communication is handled by `WPMSSHRD.DLL` via ordinal imports:
- `TComm::Write` - Thin wrapper around Windows `WRITECOMM` API
- `TComm::Read` - Handles COM port reading with buffering
- Checksum/CRC is **NOT** calculated in WPMSSHRD - it's done in PRTCL001.DLL before calling TComm

### COM Port Routing (TComm::Write)

```cpp
if (port < 1000) {
    // Direct COM port via WRITECOMM
} else if (port < 2000) {
    // Inter-process via SENDMESSAGE
} else {
    // Cross-comm via XCOM_Write
}
```

## Error Messages

Error resource strings identified:
- "Serial Number: Wrong packet type returned"
- "Q1: Wrong packet type returned"
- "Q2: Wrong packet type returned"
- "Q3: Wrong packet type returned"
- "Q4: Wrong packet type returned"
- "Alarm ACK: Wrong packet type returned"
- " invalid packet length"
- " invalid CRC"

## Ghidra Analysis Notes

### Improving Decompilation Quality

The following techniques help improve Ghidra's analysis of this 16-bit NE binary:

1. **Set Function Prototypes** - Use `set_function_prototype` to declare parameter types
   - Helps decompiler understand data flow
   - Propagates type information to callers/callees

2. **Create Undiscovered Functions** - Many functions not found by auto-analysis
   - Search for Borland prologue: `45 55 8B EC 1E 8E D8` (INC BP; PUSH BP; MOV BP,SP; PUSH DS; MOV DS,AX)
   - Manually create functions at discovered addresses

3. **Define Data Structures** - Create struct types for:
   - `TMNetProtocol` (~0x700 bytes per connection)
   - `TDataItem` (~0x64 bytes)
   - Function pointer tables at 1050:1369

4. **Cross-Reference Limitations**
   - Ghidra xrefs don't work well for 16-bit far segment references
   - Use binary grep to find string/constant references

### Function Pointer Tables

Protocol handlers are called indirectly via pointers stored in session objects:
- Offset 0x69a: Primary packet handler
- Offset 0x69c: Secondary handler
- Offset 0x69e: Callback handler
- Offset 0x6a0: Error handler

Pointers are loaded from 1050:1369-136f during `MNet_InitProtocolHandler`.

## Login and Authentication

### Message Type 14 - Remote Login

Login uses message type 14 with these variants:
- **0x138e** (5006): Standard remote login request
- **0x13a1** (5025): Hidden login request (when `HiddenLogin` INI parameter is non-zero)

### Login Responses

| Response | Meaning |
|----------|---------|
| Remote login | Login successful |
| Remote hidden login | Hidden login successful |
| Remote logout | Logged out |
| Remote not logged in | Login required |

### Login Flow

1. Client sends message type 14 with manufacturer code
2. Server validates code and password
3. Server returns login status
4. On success, function pointer table switches to authenticated mode (DAT_1050_13a1-13a7)

### Login State Machine

The protocol handler at `FUN_1010_3825` manages login states:
- **State 0**: Initial - check packet type, send login if 0x138e
- **State 1**: Waiting - check timeout against `DAT_1050_5294`
- **State 2**: Processing - update function pointers on success

## Manufacturer Login Codes

The M-Net protocol uses manufacturer-specific login codes (100-140) with associated passwords stored at segment 1050:0320.

### Complete Manufacturer Table

| Code | Manufacturer | Password |
|------|--------------|----------|
| 100 | Nordex GmbH | wI4tsGD |
| 101 | Micon A/S | hkGdteJsn |
| 102 | Nordic WP | hhYt6&rvZ |
| 103 | HSW | Hgyf%ydrTu0)mNp |
| 104 | Tacke Wind | IsGjaTgy |
| 105 | BGE | gYF Gyf j90d782 |
| 106 | Pehr | yx566 r8kxd3w |
| 107 | Fuhrländer | bNsF&Qg( |
| 108 | Home1 | wfgfs#&xsdfED |
| 109 | Südwind | %/(gTRsd57w |
| 110 | Ellgard | 43jkb fgklh |
| 117 | RivaCalzoni | #mk&65 |
| 118 | DeWind | %&'#sG5GFde3 |
| 119 | Protec | /&HFUdgh4833 |
| 120 | RES | QfgvU6!(dyEhC 2 |
| 121 | WinCon | djssj2882jus |
| 122 | Jeumont | KH9!pp)dxxs |
| 123 | Desarollos | %q=34as! |
| 124 | Iran Roads | 9ik,{02s# |
| 125 | (reserved) | k;Msiu!##8sk445 |
| 126 | Jacobs Energie | 0333**we82jsnqw |
| 127 | Suzlon | (0sd)/%%222ksse |
| 128 | BWD | +34HJAiwqw&&?@? |
| 129 | Vergnet | CCs/$sjklQQdgfg |
| 130 | Wavegen | ::A[[987Mrk9924 |
| 131 | Gaia Wind | fkYu))12221QQaa |
| 132 | WinWinD | **23920JHlssiw4 |
| 133 | CITA | !##VsssVVWq9023 |
| 134 | (reserved) | +@ssQQ(ha)ssQXX |
| 135 | (reserved) | &&71002YHgiqPPq |
| 136-140 | (reserved) | (see binary) |
| Master | Mita-Teknik A/S | (no password) |

**Note:** Login strings at 1050:2b80 provide display names: "Login 100 Nordex", "Login 101 NEG Micon", etc.

## Remote Command Protocol

### REMOTECOMMAND Function (1010:ac5c)

Commands are queued asynchronously via the `REMOTECOMMAND` export:

```c
int REMOTECOMMAND(int param1, int param2, long param3, int param4,
                  int param5, char param6, int param7, int param8);
```

Parameters are stored at:
- `DAT_1050_10ea` - Command code (param7)
- `DAT_1050_10ec` - Command subcode (param8)
- `DAT_1050_10ee` - Command flag (param6)
- `DAT_1050_10ef` - Command data pointer (param3)
- `DAT_1050_10f3` - Additional data (copied from param4/param5)

Returns 1 if command queued successfully, 0 if queue full.

### REMOTEMMSCOMMAND Function (1010:accb)

A secondary command channel parallel to REMOTECOMMAND. "MMS" meaning unknown - possibly "Maintenance Mode System" or "Manual Mode System".

```c
int REMOTEMMSCOMMAND(int param1, int param2, long param3, int param4,
                     int param5, char param6, int param7, int param8);
```

Parameters are stored at:
- `DAT_1050_1338` - Command code (param7)
- `DAT_1050_133a` - Command subcode (param8)
- `DAT_1050_133c` - Command flag (param6)
- `DAT_1050_1343` - Command data pointer (param3)
- `DAT_1050_1347` - Additional data (copied from param4/param5)
- `DAT_1050_135f` - param2
- `DAT_1050_1363` - param1
- `DAT_1050_1365` - Result flag (0 initially, set on completion)

Returns 1 if command queued successfully, 0 if queue full (DAT_1050_10ea >= 0).

**Related Functions:**
- `REMOTEMMSCOMMANDSET(flag)` - Sets read-only mode flag (DAT_1050_133d)
- `REMOTEMMSCOMMANDRESULT(&result)` - Retrieves result from DAT_1050_1367

**Handler:** FUN_1010_8616 (via DAT_1050_1379 table)

**Status:** This API is exported but **UNUSED** by standard WPMS applications.

**Comprehensive Search Results:**
A search across all extracted WPMS executables and DLLs confirms:
- **REMOTECOMMAND** - Called by: CTLPANEL.EXE, PARKCTRL.EXE, PARKSRV.EXE
- **REMOTEDISPLAYCOMMAND** - Called by: RMTDSPLY.EXE (for WP3000 remote display)
- **REMOTEMMSCOMMAND** - **No callers found** in any WPMS application

The MMS command API appears to be reserved functionality that was never utilized in standard WPMS deployments. It may have been intended for OEM integrations, specific WP3000 controller variants, or future features that were never implemented.

**SS323/WPSHELL Analysis (January 2026):**
Analysis of the SS323 field service tool (WPSHELL.EXE) confirms MMS was never implemented:
- No "MMS" strings found in WPSHELL.EXE
- No REMOTEMMSCOMMAND references in any SS323 module
- SS323 uses the same M-Net protocol as WPMS but without any MMS capability

This provides additional evidence that MMS support was planned but abandoned across both WPMS and SS323 product lines.

### Command Processing

The main dispatcher (`WPMSENTRY`) checks active command queues:
- `DAT_1050_110c` - Display commands (REMOTEDISPLAYCOMMAND)
- `DAT_1050_10ea` - Remote commands (REMOTECOMMAND)
- `DAT_1050_1338` - MMS commands (REMOTEMMSCOMMAND)

Different function pointer tables are loaded based on active command type.

## CRC Finalization

The function `FUN_1010_0472` (renamed: `MNet_FinalizeCRC`) adds CRC to packets:

```c
void MNet_FinalizeCRC(byte* packet) {
    uint16_t len = packet[7];
    uint16_t crc = CRC16_Calculate(0, packet + 3, len + 5);
    packet[len + 8] = crc >> 8;    // High byte
    packet[len + 9] = crc & 0xFF;  // Low byte
}
```

## Serial Number Encoding System

The turbine serial number is used to derive XOR keys for encoding/decoding packet payloads. This provides basic obfuscation of the wire protocol.

### Key Derivation (Segment 1008)

The 4-byte serial number (obtained via message type 13) is transformed into encryption keys:

**FUN_1008_0000** - 6-byte key derivation:
```c
void DeriveKeys6(byte* serial) {
    key[0] = serial[1] + serial[2] ^ serial[3];
    key[1] = (serial[1] & serial[0]) + serial[1];
    key[2] = serial[3] + serial[2] & serial[2];
    key[3] = (serial[3] ^ serial[0]) + serial[1];
    key[4] = serial[1];
    key[5] = (serial[2] & serial[1]) + serial[3];
}
```

**FUN_1008_0178** - 3-byte key derivation:
```c
void DeriveKeys3(byte* serial) {
    key[0] = serial[3] + serial[0];
    key[1] = serial[1] + serial[3];
    key[2] = serial[2] + serial[3];
}
```

**FUN_1008_028c** - 4-byte key derivation:
```c
void DeriveKeys4(byte* serial) {
    key[0] = (serial[2] & serial[1]) + serial[3];
    key[1] = (serial[3] | serial[2]) ^ serial[1];
    key[2] = (serial[1] ^ serial[3]) + serial[2];
    key[3] = serial[1] + serial[0] & serial[1];
}
```

### Encoding/Decoding Functions

The protocol uses multiple encoding variants with different key lengths, magic constants, and algorithms. All functions are in segment 1008. Function names shown were discovered in Ghidra (likely from debug symbols or manual renaming).

**Named Encoding Functions (confirmed via Ghidra search):**

| Function | Address | Type | Key Cycle | Magic | Algorithm |
|----------|---------|------|-----------|-------|-----------|
| SerialXOR_Encode6 | 1008:0116 | Encode | 6 bytes | 0x6b | `out = (in + 0x6b) ^ key[i] - prev_out` |
| SerialXOR_Decode3 | 1008:0220 | Decode | 3 bytes | none | `out = in ^ (key[i] + prev_in)` (CBC) |
| SerialXOR_Decode4 | 1008:030b | Decode | 4 bytes | 0xa9 | `out = in - (key[i] ^ prev_in) ^ 0xa9` |
| SerialXOR_Encode4 | 1008:0377 | Encode | 4 bytes | 0xa9 | `out = (in ^ 0xa9) + (key[i] ^ prev_out)` |
| SerialXOR_Encode5 | 1008:045b | Encode | 5 bytes | none | XOR with key cycle |
| SerialXOR_Decode5 | 1008:04bb | Decode | 5 bytes | none | XOR with key cycle |
| SerialXOR_Encode4_Magic5A | 1008:060b | Encode | 4 bytes | 0x5a | `out = (in ^ 0x5a) + (key[i] ^ prev_out)` |
| SerialXOR_Encode4_Magic37 | 1008:0757 | Encode | 4 bytes | 0x37 | `out = (key[i] + prev_in + in) ^ 0x37` |
| SerialXOR_Encode6_Magic74 | 1008:0867 | Encode | 6 bytes | 0x74 | `out = (in ^ 0x74) - (key[i] + prev_out)` |
| SerialXOR_Encode4_Magic45 | 1008:0999 | Encode | 4 bytes | 0x45 | XOR/add variant |
| SerialXOR_Decode4_Magic45 | 1008:09fb | Decode | 4 bytes | 0x45 | XOR/subtract variant |
| SerialXOR_Encode5_Magic87 | 1008:0b02 | Encode | 5 bytes | 0x87 | `out = ((key[i] + prev_in) ^ in) + 0x87` |
| SerialXOR_Decode5_Magic79 | 1008:0b69 | Decode | 5 bytes | 0x79 | Inverse of Encode5_Magic87 |

**Additional Encoding Variants (from decompilation):**

| Address | Type | Key Cycle | Magic | Algorithm |
|---------|------|-----------|-------|-----------|
| 1008:00ae | Encode | 6 bytes | 0x95 | `out = ((key[i] - prev_out) ^ in) + 0x95` |
| 1008:059c | Decode | 4 bytes | 0x5a | `out = (in - (key[i] ^ prev_in)) ^ 0x5a` |
| 1008:06ef | Encode | 4 bytes | 0x37 | `out = (key[i] + prev_in + in) ^ 0x37` |
| 1008:08cf | Decode | 6 bytes | 0x74 | `out = (in ^ 0x74) - (key[i] + prev_out)` |
| 1008:0c3f | Encode | 4 bytes | none | `out = (key[i] ^ prev_out) + in` |
| 1008:0c9f | Decode | 4 bytes | none | `out = in - (key[i] ^ prev_in)` |
| 1008:0db9 | Encode | 6 bytes | 0x97 | `out = ((key[i] - prev_in) ^ in) + 0x97` |
| 1008:0e21 | Encode | 6 bytes | 0x69 | `out = (in + 0x69) ^ (key[i] - prev_out)` |
| 1008:1056 | Decode | 4 bytes | none | `out = in - (key[i] ^ prev_out)` |
| 1008:10b8 | Encode | 4 bytes | none | `out = in + (key[i] ^ prev_in)` |
| 1008:1566 | Decode | 4 bytes | 0x23 | `out = in - (key[i] ^ prev_in) ^ 0x23` |
| 1008:15d1 | Encode | 4 bytes | 0x23 | `out = (in ^ 0x23) + (key[i] ^ prev_out)` |
| 1008:16b3 | Decode | 4 bytes | 0x41 | `out = in - (key[i] ^ prev_in) ^ 0x41` |
| 1008:171e | Encode | 4 bytes | 0x41 | `out = (in ^ 0x41) + (key[i] ^ prev_out)` |
| 1008:17e8 | Encode | 4 bytes | 0x11 | `out = (key[i] + prev_out + 0x11) ^ in` |
| 1008:184a | Decode | 4 bytes | 0x11 | `out = in ^ (key[i] + prev_in + 0x11)` |
| 1008:1934 | Decode | 5 bytes | 0x90 | `out = (in - (key[i] ^ prev_in)) + 0x90` |
| 1008:1999 | Encode | 5 bytes | 0x70 | `out = in + (key[i] ^ prev_out) + 0x70` |
| 1008:1a9c | Decode | 5 bytes | 0x6a | `out = ((key[i] - prev_in) ^ in) + 0x6a` |
| 1008:1b04 | Encode | 5 bytes | 0x96 | `out = (in + 0x96) ^ (key[i] - prev_out)` |
| 1008:1be6 | Encode | 4 bytes | 0xa2 | `out = (key[i] + prev_in + in) ^ 0xa2` |
| 1008:1c4e | Decode | 4 bytes | 0xa2 | `out = (in ^ 0xa2) - (key[i] + prev_out)` |
| 1008:1d3b | Encode | 5 bytes | 0x55 | `out = (key[i] + prev_out) ^ in ^ 0x55` |
| 1008:1e9e | Decode | 5 bytes | 0x89 | `out = ((key[i] - prev_in) ^ in) + 0x89` |
| 1008:2dbe | Encode | 5 bytes | 0x50 | `out = ((key[i] - prev_in) ^ in) + 0x50` |

**Encoding Function Patterns:**

The encoding functions follow consistent patterns:

1. **Basic XOR-CBC (3-byte key):** `key_byte = key[i % 3] + prev_ciphertext; out = in ^ key_byte`
2. **Add-XOR (4-byte key):** `out = (in ^ MAGIC) + (key[i % 4] ^ prev_out)`
3. **XOR-Add (4-byte key):** `out = (key[i % 4] + prev_in + in) ^ MAGIC`
4. **Complex (5/6-byte key):** Various combinations of XOR, add, subtract with magic constants

**Magic Byte Summary:**

| Magic | Key Size | Usage |
|-------|----------|-------|
| 0x11 | 4 bytes | Added to combined key+prev |
| 0x23 | 4 bytes | Post-XOR value |
| 0x37 | 4 bytes | Post-XOR value |
| 0x41 | 4 bytes | Post-XOR value |
| 0x45 | 4 bytes | Post-XOR value |
| 0x50 | 5 bytes | Post-add value |
| 0x55 | 5 bytes | Post-XOR value |
| 0x5a | 4 bytes | Post-XOR value |
| 0x69 | 6 bytes | Pre-add value |
| 0x6a | 5 bytes | Post-add value |
| 0x6b | 6 bytes | Pre-add value |
| 0x70 | 5 bytes | Post-add value |
| 0x74 | 6 bytes | Post-XOR value |
| 0x79 | 5 bytes | Decode magic |
| 0x87 | 5 bytes | Post-add value |
| 0x89 | 5 bytes | Post-add value |
| 0x90 | 5 bytes | Post-add value |
| 0x95 | 6 bytes | Post-add value |
| 0x96 | 5 bytes | Pre-add value |
| 0x97 | 6 bytes | Post-add value |
| 0xa2 | 4 bytes | Post-XOR value |
| 0xa9 | 4 bytes | Pre/Post-XOR value (default) |

### Key Derivation Functions

Multiple key derivation functions exist for each key length, using different formulas. All take a 4-byte serial number as input and derive the encryption key stored at DAT_1050_4cc2-4cc7.

**Named Key Derivation Functions (confirmed via Ghidra search):**

| Function | Address | Key Length | Output Range | Description |
|----------|---------|------------|--------------|-------------|
| SerialKey_Derive3 | 1008:0178 | 3 bytes | 4cc2-4cc4 | Primary 3-byte derivation |
| SerialKey_Derive4 | 1008:028c | 4 bytes | 4cc2-4cc5 | Primary 4-byte derivation |
| SerialKey_Derive4_Alt | 1008:0523 | 4 bytes | 4cc2-4cc5 | Alternative formula |
| SerialKey_Derive4_AltEntry | 1008:0520 | 4 bytes | 4cc2-4cc5 | Entry point for Alt |
| SerialKey_Derive4_Alt2 | 1008:0673 | 4 bytes | 4cc2-4cc5 | Second alternative |
| SerialKey_Derive4_Alt2Entry | 1008:066f | 4 bytes | 4cc2-4cc5 | Entry point for Alt2 |
| SerialKey_Derive4_Alt3 | 1008:0934 | 4 bytes | 4cc2-4cc5 | Third alternative |
| SerialKey_Derive4_Alt3Entry | 1008:0931 | 4 bytes | 4cc2-4cc5 | Entry point for Alt3 |
| SerialKey_Derive5 | 1008:03db | 5 bytes | 4cc2-4cc6 | Primary 5-byte derivation |
| SerialKey_Derive5_Entry | 1008:03d9 | 5 bytes | 4cc2-4cc6 | Entry point for Derive5 |
| SerialKey_Derive5_Alt | 1008:0a6b | 5 bytes | 4cc2-4cc6 | Alternative formula |
| SerialKey_Derive5_AltEntry | 1008:0a6a | 5 bytes | 4cc2-4cc6 | Entry point for Alt |
| SerialKey_Derive6 | 1008:0000 | 6 bytes | 4cc2-4cc7 | Primary 6-byte derivation |
| SerialKey_Derive6_Alt | 1008:0003 | 6 bytes | 4cc2-4cc7 | Alternative formula |
| SerialKey_Derive6_Alt2 | 1008:07bb | 6 bytes | 4cc2-4cc7 | Second alternative |
| SerialKey_Derive6_Alt2Entry | 1008:07b9 | 6 bytes | 4cc2-4cc7 | Entry point for Alt2 |

**Additional Key Derivation Variants (unnamed, from decompilation):**

| Address | Key Length | Output Range | Notes |
|---------|------------|--------------|-------|
| 1008:0bce | 4 bytes | 4cc2-4cc5 | Yet another variant |
| 1008:0d0e | 6 bytes | 4cc2-4cc7 | Yet another variant |
| 1008:0e86 | 5 bytes | 4cc2-4cc6 | Yet another variant |
| 1008:0fe2 | 4 bytes | 4cc2-4cc5 | Yet another variant |
| 1008:1127 | 5 bytes | 4cc2-4cc6 | Yet another variant |
| 1008:14e6 | 4 bytes | 4cc2-4cc5 | Used with magic 0x23 |
| 1008:1636 | 4 bytes | 4cc2-4cc5 | Used with magic 0x41 |
| 1008:1783 | 4 bytes | 4cc2-4cc5 | Used with magic 0x11 |
| 1008:18bc | 5 bytes | 4cc2-4cc6 | Used with magic 0x90/0x70 |
| 1008:1a0a | 5 bytes | 4cc2-4cc6 | Used with magic 0x6a |
| 1008:1b69 | 4 bytes | 4cc2-4cc5 | Used with magic 0xa2 |
| 1008:1cb3 | 5 bytes | 4cc2-4cc6 | Used with magic 0x55 |
| 1008:1e0c | 5 bytes | 4cc2-4cc6 | Used with magic 0x89 |

**Key Storage Location:**
- Keys are stored at `DAT_1050_4cc2` through `DAT_1050_4cc7` (6 bytes maximum)
- 3-byte keys use 4cc2-4cc4
- 4-byte keys use 4cc2-4cc5
- 5-byte keys use 4cc2-4cc6
- 6-byte keys use 4cc2-4cc7

### Message Type to Encoding Mapping

The encoding scheme varies by message type. Each message builder function calls a specific encoding variant. Based on code analysis:

| Message Type | Encoding Likely Used | Notes |
|--------------|---------------------|-------|
| 3 (Request data) | 3-byte key | Simple data requests |
| 4 (Request multiple data) | 3-byte key | Batch data requests |
| 5 (Write data) | 4-byte key | Write operations use stronger encoding |
| 6-7 (Datalog) | 4 or 5-byte key | Log data transfers |
| 8-9 (Log1000) | 4 or 5-byte key | High-resolution log data |
| 10-12 (I/O text) | 3-byte key | Text label retrieval |
| 13 (Serial number) | **None** | Serial number is sent in cleartext |
| 14 (Login) | 4 or 6-byte key | Authentication uses stronger encoding |
| 15-18 (Alarm data) | 4-byte key | Alarm records |
| 19 (Alarm ACK) | 3-byte key | Simple acknowledgment |
| 20 (Alarm code) | 3-byte key | Alarm code lookup |

**Note:** The exact message type to encoding mapping requires wire protocol capture to confirm, as Ghidra's cross-reference analysis doesn't work reliably for 16-bit far segment calls.

### Decode Example (FUN_1008_0220)

```c
void XOR_Decode3(byte* buffer, int length, byte* serial) {
    DeriveKeys3(serial);  // Initialize key[0..2] from serial

    int key_index = 0;
    byte prev_byte = 0;

    for (int i = 0; i < length; i++) {
        byte key_byte = key[key_index] + prev_byte;
        prev_byte = buffer[i];
        buffer[i] ^= key_byte;

        key_index = (key_index + 1) % 3;  // Cycle through 3 keys
    }
}
```

### Protocol Flow

1. Client requests turbine serial number (message type 13)
2. Turbine responds with 4-byte serial number
3. Client derives XOR keys from serial number
4. All subsequent data payloads are decoded using derived keys
5. Different message types may use different encoding schemes (3, 4, or 6-byte key cycles)

### Key Storage

Keys are stored at runtime addresses:
- `DAT_1050_4cc2` through `DAT_1050_4cc7` (6 bytes)

## Alarm Handling System

### Overview

M-Net uses a 4-part alarm retrieval scheme for efficient transfer of alarm data over slow modem connections. Alarm data is split across message types 15-18, with acknowledgment (type 19) and alarm code lookup (type 20) as separate operations.

### Alarm Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| MaxAlarmRetries | 6 | Maximum retry attempts for alarm operations (vs 3 for normal data) |
| AlarmTimeOutAdjust | 3 | Timeout multiplier for alarm packets |
| ConvertAlarmState | 1 | Convert alarm states to standard format |

### Alarm Message Types

| Type | Request | Reply | Description |
|------|---------|-------|-------------|
| 15 | Request alarm data (1:4) | Reply alarm data (1:4) | First quarter of alarm data |
| 16 | Request alarm data (2:4) | Reply alarm data (2:4) | Second quarter of alarm data |
| 17 | Request alarm data (3:4) | Reply alarm data (3:4) | Third quarter of alarm data |
| 18 | Request alarm data (4:4) | Reply alarm data (4:4) | Fourth quarter of alarm data |
| 19 | Acknowledge alarm | Reply Acknowledge | Confirm alarm receipt |
| 20 | Request alarm code | Reply alarm code | Lookup alarm code description |

### 4-Part Alarm Transfer

Alarm data is split into 4 parts to:
1. Reduce packet size over slow modem links
2. Allow partial retransmission on errors
3. Enable progress indication during transfers

The client requests each part sequentially (1:4 → 2:4 → 3:4 → 4:4), waiting for each reply before proceeding. On error, only the failed part needs retransmission.

### Alarm Acknowledgment Flow

```
Client                          Turbine
   |                               |
   |-- Request alarm data (1:4) -->|
   |<-- Reply alarm data (1:4) ----|
   |-- Request alarm data (2:4) -->|
   |<-- Reply alarm data (2:4) ----|
   |-- Request alarm data (3:4) -->|
   |<-- Reply alarm data (3:4) ----|
   |-- Request alarm data (4:4) -->|
   |<-- Reply alarm data (4:4) ----|
   |                               |
   |-- Acknowledge alarm --------->|
   |<-- Reply Acknowledge ---------|
```

### Alarm Database Tables

Two database tables store alarm information:

| Table | Purpose |
|-------|---------|
| ALARM | Individual turbine alarm records |
| PRKALARM | Park-level aggregated alarm data |

Referenced at segment 1050:1844 (ALARM) and 1050:1850 (PRKALARM).

### Error Handling

| Error Message | Cause |
|---------------|-------|
| "Alarm ACK: Wrong packet type returned" | Unexpected response to acknowledgment |
| "Alarm reception failed. Park ID: %s" | Failed to retrieve alarm data from park |

### Retry Logic

Alarm operations use `MaxAlarmRetries` (default: 6) instead of the standard `MaxRetries` (default: 3), providing more resilience for critical alarm data.

The timeout for alarm packets is extended by `AlarmTimeOutAdjust` multiplier, typically:
```c
alarmTimeout = baseTimeout * AlarmTimeOutAdjust;  // e.g., 3x normal timeout
```

### State Conversion

When `ConvertAlarmState=1` (default), raw alarm states from the turbine controller are converted to standardized values for consistent display across different turbine models.

## Payload Formats

This section documents the exact payload byte layout for each message type, derived from reverse engineering the packet builder functions in PRTCL001.DLL.

### Message Type 3: Request Data (0x0C28)

**Purpose:** Request a single data point value from the turbine.

**Request Payload (4 bytes):**
```
+--------+--------+--------+--------+
| ID_HI1 | ID_LO1 | ID_HI2 | ID_LO2 |
+--------+--------+--------+--------+
  byte 0    1        2        3
```

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0-1 | 2 | ID Part 1 | Data point ID high word (byte-swapped) |
| 2-3 | 2 | ID Part 2 | Data point ID low word (byte-swapped) |

**Reply Payload:** Contains the requested data value (format varies by data type).

### Message Type 4: Request Multiple Data (0x0C2A)

**Purpose:** Request multiple data point values in a single packet.

**Builder Function:** `MNet_BuildRequestMultipleData` (1010:4de2)

**Request Payload (1 + 4n bytes):**
```
+-------+--------+--------+--------+--------+--------+--------+--------+--------+---
| COUNT | ID1_H1 | ID1_L1 | ID1_H2 | ID1_L2 | ID2_H1 | ID2_L1 | ID2_H2 | ID2_L2 |...
+-------+--------+--------+--------+--------+--------+--------+--------+--------+---
 byte 0     1        2        3        4        5        6        7        8
```

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | COUNT | Number of data points requested (max: `DAT_1050_52aa`) |
| 1-4 | 4 | ID[0] | First data point ID (4 bytes, byte-swapped) |
| 5-8 | 4 | ID[1] | Second data point ID |
| ... | 4 | ID[n] | Additional data point IDs |

**ID Byte Order (from TDataItem structure):**
```c
payload[0] = dataItem[0x3b];  // ID byte 3 (swapped)
payload[1] = dataItem[0x3a];  // ID byte 2 (swapped)
payload[2] = dataItem[0x3d];  // ID byte 1 (swapped)
payload[3] = dataItem[0x3c];  // ID byte 0 (swapped)
```

**Reply Payload (0x0C2B):** Contains count byte followed by data values for each requested item.

### Message Type 5: Request Write Data (0x0C2C)

**Purpose:** Write one or more data point values to the turbine.

**Builder Function:** `MNet_BuildRequestWriteData` (1010:4a5b)

**Request Payload (8n bytes):**
```
+--------+--------+--------+--------+--------+--------+--------+--------+---
| ID1_H1 | ID1_L1 | ID1_H2 | ID1_L2 | VAL1_3 | VAL1_2 | VAL1_1 | VAL1_0 |...
+--------+--------+--------+--------+--------+--------+--------+--------+---
 byte 0     1        2        3        4        5        6        7
```

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0-3 | 4 | ID | Data point ID (byte-swapped, same format as request data) |
| 4-7 | 4 | VALUE | 32-bit value to write (byte-swapped, big-endian) |

**Per-Item Layout (8 bytes each):**
```c
payload[0] = dataItem[0x3b];  // ID byte 3
payload[1] = dataItem[0x3a];  // ID byte 2
payload[2] = dataItem[0x3d];  // ID byte 1
payload[3] = dataItem[0x3c];  // ID byte 0
payload[4] = dataItem[0x41];  // Value byte 3 (MSB)
payload[5] = dataItem[0x40];  // Value byte 2
payload[6] = dataItem[0x3f];  // Value byte 1
payload[7] = dataItem[0x3e];  // Value byte 0 (LSB)
```

**Reply Payload (0x0C2D):** Acknowledgment of write operation.

### Message Type 13: Request Serial Number (0x0C2E)

**Purpose:** Request the turbine's serial number (used for XOR key derivation).

**Request Payload:** Empty (length = 0)

**Reply Payload (4 bytes):**
```
+--------+--------+--------+--------+
| SER_0  | SER_1  | SER_2  | SER_3  |
+--------+--------+--------+--------+
```

The 4-byte serial number is used to derive XOR encryption keys (see Serial Number Encoding System section).

### Message Type 14: Remote Login (0x138E)

**Purpose:** Authenticate with the turbine using manufacturer credentials.

**Builder Function:** `MNet_BuildLoginPacket` (1010:3e2a)

**Request Payload:** Contains manufacturer code and optional password.

**Login Code Mapping (from switch table):**
```c
switch(manufacturer_index) {
    case 0:  code = 100 (0x64);  // Nordex GmbH
    case 1:  code = 101 (0x65);  // Micon A/S
    case 2:  code = 102 (0x66);  // Nordic WP
    case 3:  code = 103 (0x67);  // HSW
    case 4:  code = 104 (0x68);  // Tacke Wind
    case 5:  code = 105 (0x69);  // BGE
    case 6:  code = 106 (0x6a);  // Pehr
    case 7:  code = 107 (0x6b);  // Fuhrländer
    case 8:  code = 108 (0x6c);  // Home1
    case 9:  code = 109 (0x6d);  // Südwind
    case 10: code = 1   (0x01);  // Special (Master key)
    case 11: code = 110 (0x6e);  // Ellgard
    case 12: code = 117 (0x75);  // RivaCalzoni
    case 13: code = 118 (0x76);  // DeWind
    case 14: code = 119 (0x77);  // Protec
    case 15: code = 120 (0x78);  // RES
    case 16: code = 121 (0x79);  // WinCon
    case 17: code = 122 (0x7a);  // Jeumont
    case 18: code = 123 (0x7b);  // Desarollos
    case 19: code = 124 (0x7c);  // Iran Roads
    case 20: code = 125 (0x7d);  // (reserved)
    case 21: code = 126 (0x7e);  // Jacobs Energie
    case 22: code = 127 (0x7f);  // Suzlon
    case 23: code = 128 (0x80);  // BWD
    case 24: code = 129 (0x81);  // Vergnet
    case 25: code = 130 (0x82);  // Wavegen
    case 26: code = 131 (0x83);  // Gaia Wind
    case 27: code = 132 (0x84);  // WinWinD
    case 28: code = 133 (0x85);  // CITA
    case 29: code = 134 (0x86);  // (reserved)
    case 30: code = 135 (0x87);  // (reserved)
    case 31: code = 136 (0x88);  // (reserved)
    case 32: code = 137 (0x89);  // (reserved)
    case 33: code = 138 (0x8a);  // (reserved)
    case 34: code = 139 (0x8b);  // (reserved)
    case 35: code = 140 (0x8c);  // (reserved)
}
```

**Reply Types:**
- `0x138E` (5006): Login successful
- `0x13A1` (5025): Hidden login successful
- `0x138F` (5007): Logged out
- `0x1390` (5008): Not logged in (authentication failed)

### Message Type 6-7: Datalog Operations

**Builder Functions:** `FUN_1010_5bb6` (datalog info), `FUN_1010_5fe1` (datalog data)

**Request Datalog Info (0x139C):**

Request payload contains:
- Data point ID identifying which datalog to retrieve

**Reply Datalog Info (0x139B):**

Reply contains information about available logs. If no data is available, reply type 0x139A ("Reply datalog info n/a") is returned instead.

**Request Datalog Data (0x1399):**

After receiving datalog info, data is requested in chunks:
- Chunk size: 128 bytes (0x80)
- Multiple requests may be needed for large logs

**Reply Datalog Data (0x1398):**

Data is returned in chunks with:
- Chunk index (byte 0)
- Total size indicator
- Data bytes (up to 128 per packet)

If no data is available, reply type 0x1397 ("Reply datalog data n/a") is returned.

### Message Type 8-9: Log1000 Operations

**Builder Functions:** `FUN_1010_6362` (log1000 info), `FUN_1010_65bc` (log1000 data), `FUN_1010_7147` (log1000 data request)

Log1000 is a specialized logging format for high-resolution data storage (1000 samples).

**Request Log1000 Info (0x1396):**

Request payload contains data point ID for log request.

**Reply Log1000 Info (0x1395):**

Contains log metadata. If unavailable, returns 0x1394 ("Reply log1000 info n/a").

**Request Log1000 Data (0x1393):**

**Reply Log1000 Data (0x1392):**

Data records (0x30 = 48 bytes each) contain:
- Timestamp (4 bytes, offset 0-3)
- 10 data values (4 bytes each, offsets 4-43)
- Status flags (4 bytes, offsets 44-47)

**Data Type Conversion (from FUN_1010_72d8):**

Note: The table below shows the decompiled Windows client spec vs actual turbine behavior.

| Type Code | Decompiled Spec | Actual Implementation | Notes |
|-----------|-----------------|----------------------|-------|
| 1, 2 | uint8 → float | int8 → float | Signed byte in practice |
| 3 | int16 → float | int16 → float | Correct |
| 4 | uint16 → float | uint16 → float | Correct |
| 5 | int32 → float | int32 → float | Correct |
| 6 | int32 → float | uint32 → float | Timestamps (positive since 1980) |
| 7 | float32 | uint32 → float | Not IEEE 754 in practice |
| 10 | uint8 → float | int8 → float | Same as type 1/2 |

**Scaling Operations:**

Note: Decompiled spec differs from actual behavior for some operations.

| Op Code | Decompiled Spec | Actual Implementation | Notes |
|---------|-----------------|----------------------|-------|
| 0 | no conversion | no conversion | Pass-through |
| 1 | value / scale | value / 10^scale | Scale is exponent |
| 2 | value / scale | value / scale | Direct division |
| 3 | value * scale | value * scale | Direct multiplication |
| 4 | value * scale | value * 10^scale | Scale is exponent |
| 5 | value * scale | value / 10^scale | Division, not multiplication! |

### Message Types 15-18: Alarm Data

**Handler Function:** `FUN_1010_6ce9` (alarm data parser)

Alarm data is transferred in 4 parts to handle large alarm histories efficiently over slow modem links.

**Request Alarm Data (1:4) - 0x0BFB:**
**Request Alarm Data (2:4) - 0x0BFD:**
**Request Alarm Data (3:4) - 0x0BFF:**
**Request Alarm Data (4:4) - 0x0C01:**

Request payloads are typically empty or contain minimal identifier data.

**Reply Alarm Data Structure:**

Each reply contains alarm records. The parser at `FUN_1010_6ce9` extracts:

**Alarm Record Format (0x68 = 104 bytes per record):**

```
+--------+--------+--------+--------+--------+--------+--------+--------+
| TIME_3 | TIME_2 | TIME_1 | TIME_0 | CODE_1 | CODE_0 | DUR_HI | DUR_LO |
+--------+--------+--------+--------+--------+--------+--------+--------+
  byte 0    1        2        3        4        5        6        7

+--------+--------+-------------------------------------------+
| EXT_HI | EXT_LO |  16 x 2-byte values (32 bytes total)      |
+--------+--------+-------------------------------------------+
  byte 8    9       bytes 10-41

+-------------------------------------------+-------------------+
|  10 x 2-byte values (20 bytes total)      |  10 x 4-byte vals |
+-------------------------------------------+-------------------+
  bytes 42-61                                 bytes 62-101

+--------+--------+
| FLAGS  | FLAGS  |
+--------+--------+
  102      103
```

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0x00-0x03 | 4 | Timestamp | Alarm timestamp (byte-swapped) |
| 0x04-0x05 | 2 | Alarm Code | Alarm type identifier |
| 0x06-0x07 | 2 | Duration | Alarm duration |
| 0x08-0x09 | 2 | Extended | Extended alarm info |
| 0x0a-0x29 | 32 | Data Block 1 | 16 x 2-byte values |
| 0x2a-0x3d | 20 | Data Block 2 | 10 x 2-byte values |
| 0x3e-0x65 | 40 | Data Block 3 | 10 x 4-byte values |
| 0x66-0x67 | 2 | Flags | Alarm flags |

**Alarm Acknowledge (0x0BEA):**

After receiving all 4 parts, send acknowledgment to confirm receipt.

**Request Alarm Code (0x0BEB):**

**Builder Function:** `FUN_1010_7f90`

Request details about a specific alarm code. Reply (0x0BEC) contains alarm description text.

### Message Types 10-12: I/O Text Operations

**Request Digital I/O Text (0x13A3):**

**Builder Function:** `FUN_1010_79a4`

Request text labels for digital I/O points. Maximum 16 retries.

**Request Analog I/O Text (0x13A5):**

**Builder Function:** `FUN_1010_7b93`

Request text labels for analog I/O points. Maximum 11 retries.

**Request Analog I/O Unit Text (0x13A7):**

**Builder Function:** `FUN_1010_7d82`

Request unit labels (e.g., "kW", "°C") for analog I/O points.

### TDataItem Structure Offsets

The internal `TDataItem` structure (~0x64 bytes) contains:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0x2a-0x2d | 4 | Response data | Received data value |
| 0x2e-0x31 | 4 | Config pointer | Configuration reference |
| 0x32-0x35 | 4 | Group ID | Data item group identifier |
| 0x38 | 2 | Error count | Transmission error counter |
| 0x3a-0x3d | 4 | Data point ID | 5-digit data point identifier |
| 0x3e-0x41 | 4 | Write value | Value to write (for write requests) |
| 0x42-0x43 | 2 | State | Item state flags |
| 0x44-0x47 | 4 | Timestamp | Last update time |
| 0x5e-0x61 | 4 | Status flags | Bitfield for item status |
| 0x62-0x63 | 2 | Retry count | Retry counter for this item |

**Status Flag Bits (offset 0x5e):**
- Bit 0 (0x01): Data valid
- Bit 1 (0x02): Pending send
- Bit 2 (0x04): Awaiting response
- Bit 3 (0x08): Error state
- Bit 7 (0x80): Timeout flag
- Bit 13 (0x2000): Write operation
- Bit 15 (0x8000): Special handling

## Message Sequence Examples

### Basic Data Read Sequence

```
PC (0xFB)                           Turbine (0x01)
    |                                    |
    |-- Request serial no (0x0C2E) ----->|
    |<-- Reply serial no (0x0C2F) -------|  (4 bytes: serial number)
    |                                    |
    |-- Remote login (0x138E) ---------->|  (manufacturer code + password)
    |<-- Remote login (0x138E) ----------|  (success)
    |                                    |
    |-- Request multiple data (0x0C2A) ->|  (count + data point IDs)
    |<-- Reply multiple data (0x0C2B) ---|  (count + values)
    |                                    |
```

### Data Write Sequence

```
PC (0xFB)                           Turbine (0x01)
    |                                    |
    |-- Request write data (0x0C2C) ---->|  (ID + value pairs)
    |<-- Reply write data (0x0C2D) ------|  (acknowledgment)
    |                                    |
```

### Complete Polling Cycle

```
1. Connect to turbine (modem dial / serial open)
2. Request serial number (for XOR key derivation)
3. Login with manufacturer credentials
4. Request multiple data points (batch read)
5. Process responses (apply XOR decoding)
6. Optionally write configuration changes
7. Disconnect
```

## Remote Display Protocol

M-Net includes built-in remote display functionality that allows monitoring turbine controller screens over the serial link. This is separate from the dedicated PRTCL007 (WP2000 Remote Display) module.

### Exported Functions

| Export | Address | Purpose |
|--------|---------|---------|
| `REMOTEDISPLAYCOMMAND` | 1010:addb | Queue a display command to the turbine |
| `REMOTEDISPLAYCOMMANDSET` | 1010:ad64 | Set read-only mode flag |
| `REMOTEDISPLAYGETSCREENDATA` | 1010:ada1 | Retrieve the 255-byte screen buffer |

### Display Command Storage

Commands are stored at these addresses before transmission:

| Address | Size | Field | Description |
|---------|------|-------|-------------|
| DAT_1050_110c | 2 | Command ID | Display command identifier (0xFFFF = none) |
| DAT_1050_110e | 2 | Command Type | Sub-command type (0xc03, 0xc04, 0xc05) |
| DAT_1050_1110 | 1 | Command Data | Command-specific data byte |
| DAT_1050_1111 | 2 | Read-Only Flag | 0 = read-write mode, non-zero = read-only |

### Display Command Types

| Command Code | Request | Reply | Description |
|--------------|---------|-------|-------------|
| 0xc03 | 0xc03 | 0x0001 | Basic display query |
| 0xc04 | 0xc04 | 0xc06 | Display command type 2 |
| 0xc05 | 0xc05 | 0xc07 | Display command type 3 |
| 0xc2e | 0xc2e | 0xc2f | Screen data request (shared with serial no.) |

**Note:** The packet type codes 0xc2e/0xc2f (3118/3119) are shared with the serial number request/reply messages. The command type byte in the payload differentiates the operation.

### Handler Function Table

The protocol uses function pointer tables to manage display operations:

| Table Entry | Address | Handler | Purpose |
|-------------|---------|---------|---------|
| DAT_1050_1371 | 1010:82A9 | FUN_1010_82ac | Display command handler |
| DAT_1050_1379 | 1010:8613 | FUN_1010_8616 | MMS command handler |
| DAT_1050_1381 | 1010:88F7 | FUN_1010_88fa | Remote command handler |
| DAT_1050_1389 | 1010:8B82 | FUN_1010_8b85 | Alarm handler |
| DAT_1050_1391 | 1010:468D | - | Default data handler |

### Screen Data Buffer

The screen buffer contains turbine controller display data:

| Offset | Size | Description |
|--------|------|-------------|
| session + 0x1238 | 255 bytes | Screen character data |

**Retrieval:** `REMOTEDISPLAYGETSCREENDATA` copies 255 bytes (0xFF) from session offset 0x1238 to the caller's buffer using `memcpy` (Ordinal_144).

### Screen Buffer Format Analysis

**Buffer Size:** 255 bytes total

**Display Dimensions:** 4 rows × 40 columns (160 characters)

This matches standard industrial LCD/VFD displays used in WP3000 turbine controllers. The 4×40 character layout is common for industrial control panels.

**Buffer Layout:**

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 160 | Character data (4 rows × 40 columns) |
| 0xA0 | 95 | Metadata/status/padding |

**Row Organization:**

| Row | Offset | Size | Description |
|-----|--------|------|-------------|
| 1 | 0x00 | 40 | Top line (status/title) |
| 2 | 0x28 | 40 | Second line |
| 3 | 0x50 | 40 | Third line |
| 4 | 0x78 | 40 | Bottom line (menu/commands) |

**Display Configuration (WPMS.INI):**
```ini
[RemoteDisplay]
FontName=Terminal    ; Windows Terminal font (monospace)
FontSize=<size>      ; Font size in points
```

**Font:** The RMTDSPLY.EXE application uses the Windows "Terminal" font which provides fixed-width characters suitable for rendering the 4×40 character grid.

### Display Command Flow

```
PC (Client)                         Turbine Controller
    |                                       |
    |-- REMOTEDISPLAYCOMMAND(cmd_data) -----|  (queue command locally)
    |                                       |
    |-- Request packet (0xc2e) ------------>|  (send display request)
    |<-- Reply packet (0xc2f) --------------|  (receive screen data)
    |                                       |
    |-- REMOTEDISPLAYGETSCREENDATA() -------|  (read 255-byte buffer)
    |                                       |
```

### Read-Only Mode

When `REMOTEDISPLAYCOMMANDSET` sets the read-only flag (DAT_1050_1111 != 0):
- The display handler takes an alternate code path
- Different handler function pointers are loaded (from 0x1669-0x166f vs 0x1679-0x167f)
- Write/control operations are disabled

### Display Handler Implementation (FUN_1010_82ac)

```c
void DisplayCommandHandler(session) {
    if (DAT_1050_1111 != 0) {
        // Read-only mode: skip sending, use alternate handlers
        session->handler_table = read_only_handlers;
        return;
    }

    // Build display request packet
    MNet_BuildPacket(
        0x1008,                    // Segment
        session + 0x266,           // Output buffer
        0xc2e,                     // Packet type (display request)
        DAT_1050_1110,             // Command data byte
        0,                         // No extra data
        0                          // Data length = 0
    );

    session->expected_reply = 0xc2f;  // Set expected reply type
    session->handler_table = reply_handlers;
}
```

### RMTDSPLY.EXE Client Application

The `RMTDSPLY.EXE` application (16-bit Windows 3.x, OWL-based) provides a graphical remote display client for both WP2000 and WP3000 controllers.

**Application Architecture:**

| Class | Purpose |
|-------|---------|
| `TWP3000TermWin` | WP3000 terminal display window |
| `TWP3000Window` | WP3000 main application window |
| `TWP2000TermWin` | WP2000 terminal display window |
| `TWP2000Window` | WP2000 main application window |
| `TProtocolCll` | Protocol DLL interface wrapper |

**Protocol Selection:**

- **WP3000 (M-Net)**: Uses `REMOTEDISPLAYCOMMAND`, `REMOTEDISPLAYCOMMANDSET`, `REMOTEDISPLAYGETSCREENDATA` from PRTCL001.DLL
- **WP2000**: Uses `REMOTEDISPLAYSEND`, `REMOTEDISPLAYRECEIVE` from PRTCL002.DLL or PRTCL007.DLL

**Display Mode Versions:**

The version number in display mode names (e.g., "WP3000 Rmt.Dsp. r/w - 101") corresponds to the manufacturer login code:

| Mode | Manufacturer | WP2000 | WP3000 |
|------|--------------|--------|--------|
| 100 | Nordex | ✓ | ✓ |
| 101 | NEG Micon | ✓ | ✓ |
| 102 | Nordic WP | - | ✓ |
| 103 | HSW | ✓ | ✓ |
| 104 | Tacke | ✓ | ✓ |
| 105 | Hydro Power | - | ✓ |
| 106 | Pehr | - | ✓ |
| 107 | Fuhrländer | - | ✓ |
| 108 | Home-1 | - | ✓ |
| 109 | Südwind | - | ✓ |
| 110 | Ellgard | - | ✓ |
| 117 | RivaCalzoni | - | ✓ |
| 118 | DeWind | - | ✓ |
| 119 | pro+pro | - | ✓ |
| 120 | RES | - | ✓ |
| 121 | WinCon | - | ✓ |
| 122 | Jeumont | - | ✓ |
| 123 | Desarollos | - | ✓ |
| 124 | Iran Roads | - | ✓ |
| 125 | WTN | - | ✓ |
| 126 | Jacobs Energie | - | ✓ |
| 127 | Suzlon | - | ✓ |
| 128 | BWD | - | ✓ |
| 129 | Vergnet | - | ✓ |
| 130 | Wavegen | - | ✓ |
| 131 | Gaia Wind | - | ✓ |
| 132 | WinWinD | - | ✓ |
| 133 | CITA | - | ✓ |
| 134 | (reserved) | - | ✓ |
| 135 | (reserved) | - | ✓ |

**Note:** WP2000 supports only modes 100, 101, 103, 104 while WP3000 supports all modes 100-135. Each mode is available in read-only (r/o) and read-write (r/w) variants.

**Configuration Parameters (WPMS.INI):**

```ini
[RemoteDisplay:WP3000]
KeySendDelay=<ms>      ; Delay between simulated key presses
KeyBeep=<0|1>          ; Enable key press beep
KeySimIntv=<ms>        ; Key simulation interval

[RemoteDisplay:WP2000]
KeySendDelay=<ms>
KeyBeep=<0|1>
```

**Features:**
- Screen capture to clipboard ("Captured printout has been put in the Clipboard")
- Read-only mode prevents accidental configuration changes
- HASP dongle required (`TMitaKey` class) for access rights validation
- Park/Turbine selection dialog for multi-turbine environments

**Keyboard Input Mechanism:**

Keyboard input to the remote display is sent via `REMOTEDISPLAYCOMMAND`:

1. **Windows Key Events** - The `TWP3000TermWin` class captures WM_KEYDOWN messages
2. **Key Encoding** - Key codes are converted to turbine controller button values
3. **Command Queuing** - `REMOTEDISPLAYCOMMAND(key_code)` queues the key press
4. **Transmission** - Key is sent as the command data byte (DAT_1050_1110) in packet type 0xc2e
5. **Timing** - `KeySendDelay` controls delay between consecutive key presses
6. **Simulation** - `KeySimIntv` controls key repeat/simulation interval

**Keyboard Conflict Handling:**

If the local operator is using the turbine controller keyboard, the remote display receives a rejection and displays:
> "Remote display has been denied access because of local keyboard operation. Try again?"

**Read-Only Mode:**

When `REMOTEDISPLAYCOMMANDSET` sets read-only mode (r/o), keyboard input is disabled and only screen viewing is permitted.

**Key Code Analysis:**

Based on reverse engineering of `REMOTEDISPLAYCOMMAND` (1010:addb):

```c
if (DAT_1050_110c < 0) {
    DAT_1050_110c = param_7;   // Command ID
    DAT_1050_110e = param_8;   // Command Type
    DAT_1050_1110 = param_6;   // Key code (1 byte)
    // ... store other parameters
    return 1;
}
return 0;  // Queue full
```

- **Key value storage:** `DAT_1050_1110` (1 byte, offset 0x1110 in data segment)
- **Packet transmission:** Key code is sent in packet type 0xc2e payload
- **Queue check:** Returns 0 if command queue is full (DAT_1050_110c >= 0)

**Key Code Encoding:**

The RMTDSPLY.EXE client (`TWP3000TermWin` class) captures WM_KEYDOWN messages and passes a key code value to `REMOTEDISPLAYCOMMAND`. The encoding appears to be **direct pass-through** - no explicit mapping table was found in either PRTCL001.DLL or RMTDSPLY.EXE.

**Possible Interpretations:**

1. **Windows VK codes** - Virtual key codes passed directly (0x25-0x28 for arrows, etc.)
2. **Turbine button codes** - Controller-specific values (likely 1-20 for simple keypads)
3. **Encoded values** - Some transformation applied by the terminal window class

**WP3000 Controller Keypad (Typical):**

Industrial wind turbine controllers typically have 8-16 buttons:
| Button | Likely Code | Function |
|--------|-------------|----------|
| Up | 1 or 0x26 | Navigate up |
| Down | 2 or 0x28 | Navigate down |
| Left | 3 or 0x25 | Navigate left |
| Right | 4 or 0x27 | Navigate right |
| Enter | 5 or 0x0D | Confirm/Select |
| Escape | 6 or 0x1B | Cancel/Back |
| F1 | 7 or 0x70 | Function 1 |
| F2 | 8 or 0x71 | Function 2 |

**Note:** Exact key code mapping requires wire protocol capture or access to WP3000 controller documentation. The release notes mention WP2000 has a "type-ahead keybuffer" (v5.40), suggesting buffered key input.

**Error Messages:**
- "You have no access rights for running the remote display on the selected turbine" - Missing manufacturer login or HASP authorization
- "Remote display has been denied access because of local keyboard operation" - Local operator is using the turbine controller

### Related Protocols

For more comprehensive remote display functionality:
- **PRTCL007** (WP2000 Remote Display) - Dedicated remote display protocol with multiple versions:
  - WP2000 Rmt.Dsp. r/o - 100/101/103/104 (read-only)
  - WP2000 Rmt.Dsp. r/w - 100/101/103/104 (read-write)
  - WP2000 WS Data Access

- **PRTCL002** (WP2000 Serial) - Contains `REMOTEDISPLAYSEND` and `REMOTEDISPLAYRECEIVE` exports

## Protocol Reimplementation Checklist

Based on reverse engineering findings, the following components are needed to reimplement M-Net:

| Component | Status | Notes |
|-----------|--------|-------|
| Packet framing | ✅ Complete | SOF=0x01, SRC, DST, TYPE(2), LEN, PAYLOAD, CRC(2), EOF=0x04 |
| CRC-CCITT | ✅ Complete | Polynomial 0x1021, table at 1050:4728, coverage: bytes 1 to 5+len |
| Packet validation | ✅ Complete | MNet_ValidatePacket returns error codes 1-6 |
| Packet type codes | ✅ Complete | 40+ types documented with hex values |
| Request data payload | ✅ Complete | 4 bytes per data point ID (byte-swapped) |
| Request multiple data | ✅ Complete | Count byte + 4 bytes per ID |
| Request write data | ✅ Complete | 8 bytes per item (ID + value, byte-swapped) |
| Login packet | ✅ Complete | 36 manufacturer codes documented (100-140) |
| XOR encoding | ✅ Complete | 3/4/5/6-byte key cycles, 40+ variants with full algorithms |
| Encoding dispatch | ✅ Complete | Manufacturer-based dispatch via FUN_1008_2e9d; 36 manufacturer codes (100-140) |
| Serial number request | ✅ Complete | Empty request, 4-byte reply |
| Alarm handling | ✅ Complete | 4-part transfer, 104-byte records |
| Alarm record format | ✅ Complete | 0x68 bytes: timestamp, code, duration, data |
| Log1000 format | ✅ Complete | 48-byte records with type conversion |
| Datalog operations | ✅ Complete | Chunked transfer (128 bytes/chunk) |
| I/O text operations | ✅ Complete | Digital, analog, and unit text |
| Response parsing | ✅ Complete | All major reply formats documented |
| Remote display | ✅ Complete | 255-byte screen buffer, packet types 0xc2e/0xc2f |
| Screen buffer format | ✅ Complete | 4×40 chars (160 bytes) + 95 bytes metadata |
| Keyboard input | ✅ Complete | API documented; likely direct VK pass-through |
| Packet handler functions | ✅ Complete | 9 core functions identified and documented |

## Further Research Needed

### Resolved Items

1. ~~**CRC Algorithm**~~ - ✓ **RESOLVED**: CRC-CCITT (0x1021) with lookup table at 1050:4728
2. ~~**Frame Delimiters**~~ - ✓ **RESOLVED**: SOF=0x01, EOF=0x04
3. ~~**Response Decoding**~~ - ✓ **RESOLVED**: XOR cipher using serial number-derived keys
4. ~~**Alarm Handling**~~ - ✓ **RESOLVED**: 4-part transfer scheme documented
5. ~~**Packet Structure**~~ - ✓ **RESOLVED**: Complete byte-level format from MNet_ValidatePacket
6. ~~**Packet Type Codes**~~ - ✓ **RESOLVED**: 40+ message type codes mapped
7. ~~**Login Packet Payload**~~ - ✓ **RESOLVED**: 36 manufacturer codes (100-140) documented
8. ~~**Request/Write Payloads**~~ - ✓ **RESOLVED**: Complete byte layouts documented
9. ~~**Alarm Data Format**~~ - ✓ **RESOLVED**: 104-byte record structure documented
10. ~~**Datalog Payload Format**~~ - ✓ **RESOLVED**: Chunked transfer format documented
11. ~~**Packet Handler Functions**~~ - ✓ **RESOLVED**: 9 core functions identified via Ghidra
12. ~~**Remote Display Key Codes**~~ - ✓ **RESOLVED**: Likely direct VK pass-through; API fully documented

### Remaining Items

1. **Wire Protocol Capture** - Serial capture would:
   - Verify which encoding variant is used for each message type in practice
   - Document actual key code values in use

2. ~~**Remote Display Screen Format**~~ - ✅ **RESOLVED**:
   - Display is 4 rows × 40 columns (160 characters)
   - Standard industrial LCD/VFD layout
   - 95 bytes of metadata/status after character data

3. ~~**Encoding Variant Selection Logic**~~ - ✅ **RESOLVED**:
   - Encoding variant is selected based on **manufacturer code** (100-140)
   - FUN_1008_2e9d dispatches encoding functions from manufacturer table
   - Each manufacturer has specific encode/decode function pair
   - See "Manufacturer-Based Encoding Dispatch" section below

## Manufacturer-Based Encoding Dispatch

### Overview

**Key Discovery:** The user's theory that "the encoding variant depends upon the manufacturer of the turbine" has been **confirmed** through reverse engineering. Each of the 36 supported manufacturers (codes 100-140, plus code 1 for Mita-Teknik master) has its own dedicated encode/decode function pair.

### Dispatch Mechanism

**Dispatcher Function:** `FUN_1008_2e9d` (segment 1008, offset 0x2e9d)

```c
void FUN_1008_2e9d(uint16_t cs, uint32_t manufacturer_code,
                   void** encode_func_ptr, uint16_t seg1,
                   void** decode_func_ptr, uint16_t seg2)
{
    // Check if HASP dongle is installed
    if (TMitaKey_MitaKeyInstalled()) {
        if (manufacturer_code == 1) {
            // Mita-Teknik master key - no encoding
            return;
        }

        // Validate manufacturer code range: 100-135 (0x64-0x87)
        if (manufacturer_code < 100 || manufacturer_code > 135) {
            return;
        }

        // Verify HASP access for this manufacturer
        uint32_t hasp_code = *(uint32_t*)(manufacturer_code * 16 - 0x5b0);
        if (!TMitaKey_ConfirmAccess(hasp_code)) {
            return;
        }
    }

    // Load manufacturer name string pointer
    DAT_1050_008c = *(char**)(manufacturer_code * 16 - 0x5ac);

    // Load encode function pointer from manufacturer table
    *encode_func_ptr = *(void**)(manufacturer_code * 16 - 0x5a8);

    // Load decode function pointer from manufacturer table
    *decode_func_ptr = *(void**)(manufacturer_code * 16 - 0x5a4);
}
```

### Manufacturer Table Structure

The manufacturer table is located in segment 1050. Each entry is **16 bytes**:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| code*16 - 0x5b0 | 4 | HASP Code | Access code for HASP dongle validation |
| code*16 - 0x5ac | 2 | String Offset | Manufacturer name string offset |
| code*16 - 0x5aa | 2 | String Segment | Manufacturer name string segment |
| code*16 - 0x5a8 | 2 | Encode Offset | Encoding function offset |
| code*16 - 0x5a6 | 2 | Encode Segment | Encoding function segment |
| code*16 - 0x5a4 | 2 | Decode Offset | Decoding function offset |
| code*16 - 0x5a2 | 2 | Decode Segment | Decoding function segment |

**Example - Manufacturer 100 (Nordex):**
```
Table entry offset: 100 * 16 = 0x640
HASP code at:      0x640 - 0x5b0 = 0x90
String pointer at: 0x640 - 0x5ac = 0x94 (segment:offset)
Encode pointer at: 0x640 - 0x5a8 = 0x98 (segment:offset)
Decode pointer at: 0x640 - 0x5a4 = 0x9c (segment:offset)
```

### Session Object Storage

When `FUN_1008_2e9d` is called, the encoding function pointers are stored in the session object:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| session + 0x692 | 4 | Encode Function | Far pointer to encoding function |
| session + 0x696 | 4 | Decode Function | Far pointer to decoding function |

### Call Sites

**1. Login Packet Builder** (`MNet_BuildLoginPacket` @ 1010:3e2a):
```c
void MNet_BuildLoginPacket(session) {
    uint32_t manufacturer_code;

    // Map UI index (0-35) to manufacturer code (100-140 or 1)
    switch(session->manufacturer_index) {
        case 0:  manufacturer_code = 100; break;  // Nordex
        case 1:  manufacturer_code = 101; break;  // NEG Micon
        case 10: manufacturer_code = 1;   break;  // Mita-Teknik master
        // ... (see Message Type 14 section)
    }

    // Set up encoding functions for this manufacturer
    FUN_1008_2e9d(manufacturer_code,
                  &session[0x692],  // encode function pointer
                  &session[0x696]); // decode function pointer
}
```

**2. Request Multiple Data Builder** (`MNet_BuildRequestMultipleData` @ 1010:4de2):
```c
void MNet_BuildRequestMultipleData(session, data_items) {
    // Get manufacturer code from first data item (offset 0x2e)
    uint32_t manufacturer_code = data_item->config[0x2e];

    // Set up encoding functions for this manufacturer
    FUN_1008_2e9d(manufacturer_code,
                  &session[0x692],
                  &session[0x696]);
}
```

### Manufacturer Code Sources

The manufacturer code can come from two sources:

1. **Login Selection** - User selects manufacturer from UI dropdown (mapped via switch table)
2. **Data Item Configuration** - Each data item stores its manufacturer code at offset 0x2e in the TDataItem structure

This allows different data items from different manufacturers to use their correct encoding schemes within the same session.

### Encoding Function Pairs by Manufacturer

**Confirmed via binary analysis** - Function pointers extracted from NE relocation table at file offset 0x34140. Each manufacturer has a dedicated encode/decode function pair.

| Code | Manufacturer | Key Size | Magic | Encode Function | Algorithm Pattern |
|------|--------------|----------|-------|-----------------|-------------------|
| 100 | Nordex | 6-byte | 0x95 | 1008:00ae | `((key-prev)^in)+magic` |
| 101 | NEG Micon | 3-byte | none | 1008:01bf | `in^(key+prev)` (pure CBC) |
| 102 | Nordic WP | 4-byte | 0xa9 | 1008:030c | `(in^magic)+(key^prev)` |
| 103 | HSW | 5-byte | none | 1008:045c | `(key^prev)+in` |
| 104 | Tacke | 4-byte | 0x5a | 1008:059c | `(in^magic)+(key^prev)` |
| 105 | Hydro Power | 4-byte | 0x37 | 1008:06ef | `(key+prev+in)^magic` |
| 106 | Pehr | 6-byte | 0x74 | 1008:0867 | `(in^magic)-(key+prev)` |
| 107 | Fuhrländer | 4-byte | 0x45 | 1008:0999 | XOR/subtract variant |
| 108 | Home-1 | 5-byte | 0x87 | 1008:0b01 | `((key+prev)^in)+magic` |
| 109 | Südwind | 4-byte | none | 1008:0c3f | `in-(key^prev)` |
| 110 | Ellgard | 6-byte | 0x97 | 1008:0db9 | `((key-prev)^in)+magic` |
| 117 | RivaCalzoni | 5-byte | 0x42 | 1008:0f18 | `((key-prev)^in)+magic` |
| 118 | DeWind | 4-byte | none | 1008:1056 | `in-(key^prev)` |
| 119 | pro+pro | 5-byte | 0x43 | 1008:11af | `(key+prev)^in^magic` |
| 120 | RES | 5-byte | 0x68 | 1008:12f8 | `(in-(key^prev))+magic` |
| 121 | WinCon | 3-byte | none | 1008:1416 | `in^(key+prev)` (pure CBC) |
| 122 | Jeumont | 4-byte | 0x23 | 1008:1566 | `(in^magic)+(key^prev)` |
| 123 | Desarollos | 4-byte | 0x41 | 1008:16b3 | `(in^magic)+(key^prev)` |
| 124 | Iran Roads | 4-byte | 0x11 | 1008:17e8 | `(key+prev+magic)^in` |
| 125 | WTN | 5-byte | 0x90 | 1008:1934 | `(in-(key^prev))+magic` |
| 126 | Jacobs Energie | 5-byte | 0x6a | 1008:1a9c | `((key-prev)^in)+magic` |
| 127 | Suzlon | 4-byte | 0xa2 | 1008:1be6 | `(key+prev+in)^magic` |
| 128 | BWD | 5-byte | 0x55 | 1008:1d3b | `(key+prev)^in^magic` |
| 129 | Vergnet | 5-byte | 0x89 | 1008:1e9e | `((key-prev)^in)+magic` |
| 130 | Wavegen | 5-byte | 0x4c | 1008:1ffd | `in+(key^prev)+magic` |
| 131 | Gaia Wind | 5-byte | 0x34 | 1008:215c | `((key-prev)^in)+magic` |
| 132 | WinWinD | 5-byte | 0x12 | 1008:22bb | `((key-prev)^in)+magic` |
| 133 | CITA | 5-byte | 0x54 | 1008:241a | `((key-prev)^in)+magic` |
| 134-140 | (reserved) | 5-6 byte | — | 1008:257f+ | (reserved slots) |

**Algorithm Pattern Legend:**
- `key` = derived key byte at current index
- `prev` = previous ciphertext byte (CBC chaining)
- `in` = input plaintext byte
- `magic` = constant magic byte for XOR/addition

### Security Implications

1. **Manufacturer Isolation** - Each manufacturer's encoding is independent, preventing cross-manufacturer data access
2. **HASP Validation** - Access to each manufacturer's encoding requires valid HASP dongle authorization
3. **Serial Number Binding** - The encoding key is derived from the turbine serial number, binding the session to a specific turbine
4. **Obfuscation, Not Encryption** - The XOR-based encoding provides obfuscation but is not cryptographically secure

### Verification

To verify the encoding for a specific manufacturer:

1. Calculate table offset: `manufacturer_code * 16 - 0x5a8` for encode, `- 0x5a4` for decode
2. Read the 4-byte far pointer from segment 1050 at that offset
3. Decompile the function at the pointer address
4. The function should match one of the 40+ documented encoding variants

**Example verification for Nordex (100):**
```
Encode pointer offset: 100 * 16 - 0x5a8 = 0x98
Read 4 bytes at 1050:0098 → e.g., 0377:1008 (SerialXOR_Encode4)
Decode pointer offset: 100 * 16 - 0x5a4 = 0x9c
Read 4 bytes at 1050:009c → e.g., 030b:1008 (SerialXOR_Decode4)
```
