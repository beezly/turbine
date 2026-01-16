# M-Net Set Time Command Analysis

## Summary

The "Set Time" function in WPMS sends a **Write Data** command (`0x0C2C`) to update the turbine controller's clock.

## Captured Packets

Two set time commands were captured on 2026-01-16:

| Timestamp | Full Packet (hex) |
|-----------|-------------------|
| 18:20:16 | `02 fb 0c 2c 08 c3 53 00 01 56 9b db 5d 7d 2a 04` |
| 18:22:59 | `02 fb 0c 2c 08 c3 53 00 01 56 9b dc 00 6f e5 04` |

## Packet Structure

```
┌─────┬─────┬───────────┬─────┬─────────────────────┬─────────────────────┬───────────┬─────┐
│ STX │ SRC │ MSG TYPE  │ LEN │ DATA POINT ID       │ TIME VALUE          │ CRC       │ EOT │
│ 02  │ fb  │ 0c 2c     │ 08  │ c3 53 00 01         │ 56 9b XX XX         │ XX XX     │ 04  │
└─────┴─────┴───────────┴─────┴─────────────────────┴─────────────────────┴───────────┴─────┘
```

### Field Breakdown

| Offset | Size | Value | Description |
|--------|------|-------|-------------|
| 0 | 1 | `02` | STX - Start of transmission |
| 1 | 1 | `fb` | Source address (0xFB = PC/Master) |
| 2-3 | 2 | `0c 2c` | Message type 0x0C2C = **Request Write Data** |
| 4 | 1 | `08` | Payload length (8 bytes) |
| 5-8 | 4 | `c3 53 00 01` | Data point ID (byte-swapped) - **Time Register** |
| 9-12 | 4 | `56 9b XX XX` | Time value (see below) |
| 13-14 | 2 | varies | CRC-CCITT checksum |
| 15 | 1 | `04` | EOT - End of transmission |

## Time Value Format

The 4-byte time value is a **32-bit seconds counter** (big-endian, as per M-Net byte ordering):

| Packet | Time Value (hex) | Decimal | Real Time |
|--------|------------------|---------|-----------|
| First | `56 9b db 5d` | 1,453,054,813 | 18:20:16 |
| Second | `56 9b dc 00` | 1,453,054,976 | 18:22:59 |

### Verification

- **Difference**: 1,453,054,976 - 1,453,054,813 = **163 seconds**
- **Elapsed time**: 18:22:59 - 18:20:16 = 2 min 43 sec = **163 seconds**
- **Match confirmed**: The value is a linear seconds counter

### Epoch: 1980-01-01 00:00:00 UTC (CONFIRMED)

From the Python implementation in `turbine/mnet.py` (line 459-461):

```python
def timestamp_to_datetime(self, timestamp: int, adjust: bool = True) -> datetime.datetime:
    """Convert timestamp to datetime (epoch: 1980-01-01)."""
    epoch = datetime.datetime(1980, 1, 1, tzinfo=datetime.timezone.utc)
```

### Verification

| Packet | Timestamp | Decoded Time | Log Time | Delta |
|--------|-----------|--------------|----------|-------|
| First | 0x569bdb5d (1,453,054,813) | 2026-01-16 18:20:13 UTC | 18:20:16 | 3 sec |
| Second | 0x569bdc00 (1,453,054,976) | 2026-01-16 18:22:56 UTC | 18:22:59 | 3 sec |

The 3-second offset is likely due to transmission/logging delay.

### Format Summary

```
Time Value: 32-bit unsigned integer (big-endian)
Unit: Seconds since 1980-01-01 00:00:00 UTC
Range: 0 to 4,294,967,295 (covers until ~2116)
```

## Protocol Context

### Message Type 0x0C2C - Request Write Data

From the M-Net protocol documentation (MNET.md):

```
Purpose: Write one or more data point values to the turbine.

Payload Format (8 bytes per item):
+--------+--------+--------+--------+--------+--------+--------+--------+
| ID1_H1 | ID1_L1 | ID1_H2 | ID1_L2 | VAL_3  | VAL_2  | VAL_1  | VAL_0  |
+--------+--------+--------+--------+--------+--------+--------+--------+
  byte 0     1        2        3        4        5        6        7
```

The ID bytes are **byte-swapped** according to the protocol spec:
```c
payload[0] = dataItem[0x3b];  // ID byte 3
payload[1] = dataItem[0x3a];  // ID byte 2
payload[2] = dataItem[0x3d];  // ID byte 1
payload[3] = dataItem[0x3c];  // ID byte 0
```

### Data Point ID: Controller Time (CONFIRMED)

From the Python implementation in `turbine/mnet.py` (line 83):

```python
DATA_ID_CONTROLLER_TIME = b'\xc3\x53'
```

The wire format `c3 53 00 01` breaks down as:
- `c3 53` = Data ID for controller time (matches `DATA_ID_CONTROLLER_TIME`)
- `00 01` = Sub-ID (likely 0x0001 for write operations)

From DATAID.DAT:
```
20006=0,Turbine controller time
```

## Comparison with Normal Polling

The set time command (`0x0C2C`) differs from normal polling commands:

| Command | Message Type | Purpose |
|---------|--------------|---------|
| `02 fb 0c 2e ...` | 0x0C2E | Request Serial Number (status) |
| `02 fb 0c 2a ...` | 0x0C2A | Request Data (read values) |
| `02 fb 13 8e ...` | 0x138E | Remote Login (authentication) |
| **`02 fb 0c 2c ...`** | **0x0C2C** | **Request Write Data (set time)** |

## CRC Calculation

The CRC is calculated using CRC-CCITT:
- Polynomial: 0x1021
- Initial value: 0xFFFF
- Covers bytes 1 through (4 + payload_length)

Example CRC values:
- First packet: `7d 2a`
- Second packet: `6f e5`

## Implementation Notes

To send a set time command:

1. Build packet with:
   - STX: `02`
   - Source: `fb` (PC)
   - Message type: `0c 2c`
   - Length: `08`
   - Time register ID: `c3 53 00 01`
   - Encoded time value: 4 bytes
   - Calculate CRC over bytes 1-12
   - EOT: `04`

2. Send and wait for acknowledgment (message type `0x0C2D`)

## Resolved Questions

1. **Epoch**: Confirmed as **1980-01-01 00:00:00 UTC** (from `turbine/mnet.py`)
2. **Data point ID**: Confirmed as `\xc3\x53` = `DATA_ID_CONTROLLER_TIME` (from `turbine/mnet.py`)

## Open Questions

1. **Timezone handling**: The implementation uses UTC - does the turbine store/display in UTC or local time?
2. **Response format**: What does the `0x0C2D` reply contain (acknowledgment details)?
3. **Sub-ID meaning**: What does the `00 01` sub-ID represent in write operations?

---

**Document Version:** 1.0
**Created:** 2026-01-16
**Based on:** Live capture from ser2net logs on turbinepi.local
