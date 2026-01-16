# WPMS Protocol Analysis

This document contains reverse engineering findings for the WPMS (Wind Power Monitoring System) communication protocols developed by Mita-Teknik A/S (Denmark).

## Overview

WPMS uses 9 protocol modules (DLLs) to communicate with different wind turbine controllers via modem/serial connections. The protocols are dynamically loaded by the WPMS Communication Engine (WPMSENG).

## Protocol Modules

| Module | Protocol | Target Systems | Config Files |
|--------|----------|----------------|--------------|
| PRTCL001 | **M-Net** | WP3000, IC1000 | WP3000.INI, WP3000.DAT |
| PRTCL002 | WP2000 Serial | MITA WP2000 | TBNSETUP.INI, TBNCFG.DAT |
| PRTCL003 | KK Protocol | KK controllers | KK.INI, KK.DAT |
| PRTCL004 | **FDV Protocol** | FDV systems | FDV.INI, FDV.DAT |
| PRTCL005 | S4 Protocol | S4 controllers | S4.INI, S4.DAT |
| PRTCL006 | Simulation | Recorded data playback | WPRECDAT.DAT |
| PRTCL007 | WP2000 Remote Display | WP2000 display | TBNSETUP.INI |
| PRTCL008 | **D-Net** (DirectNet) | D-Net devices | DRCTNET.INI |
| PRTCL009 | CC Protocol | CC controllers | CC.INI, CC.DAT |

## Protocol DLL Architecture

All protocol modules are 16-bit Windows DLLs (NE format) built with Borland C++ 4.53 using the Object Windows Library (OWL) 2.53.

### Exported API Functions

Each protocol DLL exports these standard functions:

| Function | Purpose |
|----------|---------|
| `WPMSENTRY` | Main entry point for protocol communication |
| `WPMSDATAASTEXT` | Convert retrieved data to text format |
| `WPMSEXECDATADIALOG` | Execute data dialog |
| `WPMSGETCOMMSTATS` | Get communication statistics |
| `WPMSGETERRORCODE` | Get last error code |
| `WPMSGETERRORCODECOUNT` | Get error count |
| `WPMSGETSTDERRORCODE` | Get standard error code |
| `WPMSGETFAULTSTACKSIZE` | Get fault stack size |
| `REMOTECOMMAND` | Send remote command to turbine |
| `REMOTEMMSCOMMAND` | Send MMS command |
| `REMOTEMMSCOMMANDSET` | Set MMS command |
| `REMOTEMMSCOMMANDRESULT` | Get MMS command result |
| `REMOTEDISPLAYCOMMAND` | Send display command |
| `REMOTEDISPLAYCOMMANDSET` | Set display command |
| `REMOTEDISPLAYGETSCREENDATA` | Get screen data |

## M-Net Protocol (PRTCL001)

M-Net is the primary protocol for WP3000 and IC1000 turbine controllers.

### Message Types

The protocol uses a request/reply pattern. From binary analysis:

**Request Messages:**
- Request define packet
- Request packet
- Request data
- Request multiple data
- Request write data
- Request datalog info
- Request datalog data
- Request log1000 info
- Request log1000 data
- Request serial no.
- Request alarm data (1:4, 2:4, 3:4, 4:4)
- Request alarm code

**Reply Messages:**
- Reply define packet
- Reply packet
- Reply data
- Reply multiple data
- Reply write data
- Reply datalog info / n/a
- Reply datalog data / n/a
- Reply log1000 info / n/a
- Reply log1000 data / n/a
- Reply serial no.
- Reply digital i/o text
- Reply analog i/o text
- Reply analog i/o unit text
- Reply alarm data (1:4 through 4:4)
- Reply alarm code
- Reply Acknowledge

### Packet Format

Based on debug logging format `"Send/Recv MNet packet %04x (%u) \"%s\""`:
- Packet type: 16-bit value (displayed as hex)
- Packet length: unsigned integer
- Packet name: string identifier

### Configuration Parameters

```ini
[WP3000]
PacketSendDelay=<ms>
FixedMNetPacketTimeOut=<ms>
MNetPacketTimeOutAdjust=<ms>
ExtraMNetPacketTimeOutStep=<ms>
DebugMNetPacketTypes=<0|1>
```

### Data Structures

Key C++ classes identified:
- `TMNetProtocol` - Main protocol handler
- `TDataItem` - Individual data point
- `TIArrayAsVector<TDataItem>` - Data item collection
- `TDevInstance` - Device instance

## FDV Protocol (PRTCL004)

### Packet Record Types

12 packet types identified (01-0C hex):
- `TProtRecFDV_01` through `TProtRecFDV_0C`
- Corresponding lifetimes: `RecLifeFDV_01` through `RecLifeFDV_0C`

## WP2000 Protocol (PRTCL002)

Supports multiple remote display variants:
- WP2000 Rmt.Dsp. r/o - 100 (read-only, version 100)
- WP2000 Rmt.Dsp. r/w - 100 (read-write, version 100)
- WP2000 Rmt.Dsp. r/o - 101
- WP2000 Rmt.Dsp. r/w - 101
- WP2000 Rmt.Dsp. r/o - 103
- WP2000 Rmt.Dsp. r/w - 103
- WP2000 Rmt.Dsp. r/o - 104
- WP2000 Rmt.Dsp. r/w - 104

## Communication Layer

### Low-Level API (WPMSSHRD.DLL)

```cpp
// TComm class - Serial communication
TComm::Read(int port, void* buffer, int length)
TComm::Write(int port, const void* buffer, int length)
TComm::Flush(int port, int flags)
TComm::GetBaudrate(int port)
TComm::GetError(int port, COMSTAT* stat)
TComm::GetBytesRead()
TComm::GetBytesWritten()

// Cross-communication functions
XCOM_SetDTR(int port, int state)
XCOM_IsConnected(int port)
XCOM_Write(int port, const void* data, int length)
XCOM_GetBaudRate(int port)
XCOM_GetInQueueCount(int port)
XCOM_Flush(int port, int flags)
XCOM_MakeCall(int port, const char* number)
```

### Modem Communication

Direct AT command control via COM ports (1-9). Modem initialization strings stored in DEVICES.DAT.

**Supported protocols:**
- Analog modem (V.32bis, V.34, etc.)
- ISDN X.75
- ISDN V.110
- TAPI (via WPMSTAPI gateway)

## Data Point Identification

Data points are identified by 5-digit numeric IDs defined in DATAID.DAT.

### ID Ranges

| Range | Category | Example |
|-------|----------|---------|
| 20xxx | System/Status | 20021=System codes, 20101=Status list |
| 24xxx | Sensors | 24001=Yaw pressure, 24008=Pitch angle |
| 30xxx | Counters/Operations | 30001=Production G1, 30050=Operation time |
| 34xxx | Weather | 34000=Weather Data |
| 40xxx | Measurements | 40001=Production, 40002=Wind speed |

### Data Types (second field in DATAID.DAT)

| Type | Description |
|------|-------------|
| 0 | Status/Events |
| 1 | Analog values (float) |
| 2 | Counters/Timers |
| 3 | Production counters |
| 10 | Digital output |
| 11 | Digital input |
| 30 | Weather data |

### Sample Data Points

```
40103=1,Temperature, outside
40002=1,Wind speed
40211=1,Rotor revs.
40212=1,Generator revs.
40213=1,Yaw direction
40285=1,Grid power
40286=1,Grid frequency
30050=2,Turbine operation time
30001=3,Production G1
```

## Supported Turbine Manufacturers

Based on TBNCFG.DAT configuration:

| Manufacturer | Models |
|--------------|--------|
| Mita-Teknik Demo | 30kW - 3000kW WP3000 |
| NEG Micon | N27, N43, N54, N60, NM series |
| Made | M530, M570, M600, M700, M750, M1500, M1800, M2300 |
| HSW | 250, 600, 1000 |
| TW | 60, 80, 250, 500, 600 |
| Fuhrlander | 800, 1000 |
| HydroPower | 10kW - 100kW |

## Hardware Protection

License enforcement via hardware dongles:
- **HASP** - Parallel port or USB dongle
- **Dallas/TMEX Button** (DS1425) - 1-Wire device

Key classes:
- `TMitaKey` - HASP dongle interface
- `TTMEXButton` - Dallas button interface

## Ghidra Analysis Results

Analysis performed with Ghidra 11.4.3. Project saved at `ghidra_project/WPMS_Protocol`.

### Automated Analysis Tools

**New:** The `ghidra_scripts/` directory contains automated tools for 16-bit binary analysis:

- **`wpms_function_recovery.py`** - Automatically detects DS register value and creates missing functions
- **`wpms_verify_analysis.py`** - Validates analysis quality and reports statistics
- **Quick Start Guide:** See `ghidra_scripts/QUICKSTART.md` for step-by-step instructions

These scripts solve the two main challenges with 16-bit Borland C++ analysis:
1. Missing function detection (finds Borland prologue signature `55 89 E5`)
2. Broken data XREFs (sets DS register context for proper address resolution)

**Before automation:** 20-40 functions detected, minimal data cross-references
**After automation:** 200-400+ functions detected, hundreds of working XREFs

### Key Function Addresses (PRTCL001.DLL - M-Net)

| Address | Function | Description |
|---------|----------|-------------|
| 0x1010a414 | WPMSENTRY | Main protocol entry/dispatcher |
| 0x1010a642 | WPMSDATAASTEXT | Convert data to text format |
| 0x1010ac5c | REMOTECOMMAND | Execute remote turbine command |
| 0x1010accb | REMOTEMMSCOMMAND | MMS protocol command |
| 0x1010ad64 | REMOTEDISPLAYCOMMANDSET | Set display command |
| 0x1010addb | REMOTEDISPLAYCOMMAND | Execute display command |
| 0x101003b5 | WPMSGETCOMMSTATS | Get communication statistics |

### MNet Message Type Table (at 0x10501877)

| Type | Request | Reply |
|------|---------|-------|
| 1 | Request define packet | Reply define packet |
| 2 | Request packet | Reply packet |
| 3 | Request data | Reply data |
| 4 | Request multiple data | Reply multiple data |
| 5 | Request write data | Reply write data |
| 6 | Request datalog info | Reply datalog info |
| 7 | Request datalog data | Reply datalog data |
| 8 | Request log1000 info | Reply log1000 info |
| 9 | Request log1000 data | Reply log1000 data |
| 10 | Get digital i/o text | Reply digital i/o text |
| 11 | Get analog i/o text | Reply analog i/o text |
| 12 | Get analog i/o unit text | Reply analog i/o unit text |
| 13 | Request serial no. | Reply serial no. |
| 14 | Remote login | (various responses) |
| 15-18 | Request alarm data (1:4 - 4:4) | Reply alarm data |
| 19 | Acknowledge alarm | Reply Acknowledge |
| 20 | Request alarm code | Reply alarm code |

### Debug/Logging Format

```
Send MNet packet %04x (%u) "%s"
Recv MNet packet %04x (%u) "%s"
```

Packet type is 16-bit hex value, followed by length in bytes, then message type name.

### Hardware Protection Classes

- `TMitaKey` (0x10300084) - HASP dongle interface with access code management
- `TTMEXButton` (0x10380000) - Dallas 1-Wire/iButton interface (DS1425)

## Further Research Needed

1. **CRC Algorithm Isolation** - The CRC exists (confirmed by error strings) but needs further work:
   - Search for XOR/polynomial operations in packet builder functions
   - May require dynamic analysis or serial capture to identify
   - Common candidates: CRC-16-IBM (0x8005), CRC-CCITT (0x1021)

2. **Packet Structure Details** - Need actual protocol traces or more detailed binary analysis to determine:
   - Frame delimiters/sync bytes
   - Exact byte layout of each message type (1-20)
   - Field sizes for Type, Length, and CRC

3. **Wire Protocol Capture** - A serial port sniffer capturing actual WPMS-to-turbine communication would reveal:
   - Baud rate negotiation
   - Error handling/retransmission
   - Exact request/reply sequences

4. **Configuration File Formats** - Detailed analysis of:
   - WP3000.DAT binary structure
   - Protocol-specific INI parameters
   - Paradox database schema

## Tools for Further Analysis

- **IDA Pro** or **Ghidra** - For disassembling 16-bit NE executables
- **Serial port monitor** - To capture live protocol traces
- **DOSBox/Wine** - To run the original software
- **Paradox database tools** - To examine database files

## Detailed Protocol Documentation

See the `protocols/` directory for in-depth analysis:

- `protocols/MNET.md` - Detailed M-Net protocol documentation
- `protocols/HARDWARE_PROTECTION.md` - HASP dongle and iButton protection system

## Ghidra MCP Analysis Session Findings

### WPMSENTRY Dispatcher (1010:a414)

Command codes handled:
| Code | Function | Purpose |
|------|----------|---------|
| 0x0A | FUN_1010_a386 | Data retrieval |
| 0x0B | FUN_1010_a3d9 | Data processing |
| 0x14 | FUN_1010_9eb0 | Create connection |
| 0x15 | FUN_1010_9fa5 | Destroy connection |
| 0x1F | FUN_1010_9ff3 | Configuration |
| 0x20 | FUN_1010_a0fb | String lookup |
| 0x21 | FUN_1010_a279 | Data iteration |
| 0x22 | FUN_1010_a085 | Reset/clear |

### Configuration Loader (FUN_1010_b035)

Reads INI parameters including:
- `PCNode` = 251 (default PC address)
- `PacketSendDelay` = 50ms
- `MaxRetries` = 3
- `DebugMNetPacketTypes` = 0/1

### Data Point ID Mapper (FUN_1010_0a29)

Maps 5-digit data point IDs to internal types with access control checks.

### Checksum/CRC

**Update**: Analysis of WPMSSHRD.DLL confirms the checksum is **NOT** in the shared library. `TComm::Write` and `TComm::Read` are thin wrappers around Windows COM APIs (`WRITECOMM`, `READCOMM`, `SENDMESSAGE`).

The CRC/checksum is calculated in **PRTCL001.DLL** itself:
- Error string `" invalid CRC"` found at resource offset 1078:0087
- Error string `" invalid packet length"` found at resource offset 1078:0062
- Validation likely occurs in packet receive path

**CRC Algorithm Status**: The exact calculation routine has not been isolated - it's likely:
- Inline code within packet handler functions
- Or part of a larger packet builder routine
- Possibly CRC-16 (IBM or CCITT variant) or simple XOR checksum
