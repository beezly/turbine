# WPMS Hardware Protection System

## Overview

WPMS uses hardware dongles for license enforcement and access control. Two types are supported:

1. **HASP** - Parallel port or USB dongle (primary)
2. **Dallas/TMEX iButton** (DS1425) - 1-Wire device (secondary)

## TMitaKey Class

Located in segment 1030 (Code7), the `TMitaKey` class handles HASP dongle communication.

### Key Types

The dongle type is stored at offset 0x210 in the TMitaKey object:

| Value | Type |
|-------|------|
| 1 | Type 1 (basic) |
| 2 | Type 2 (standard) |
| 3 | Type 3 (super key) |

### HASP Service Codes

`TMitaKey::CallHasp` uses these service codes:

| Code | Hex | Purpose |
|------|-----|---------|
| 1 | 0x01 | Basic presence check |
| 6 | 0x06 | Read memory |
| 50 | 0x32 | Encode/decode |
| 51 | 0x33 | Get info |
| 70 | 0x46 | Extended read |
| 71 | 0x47 | Extended write |
| 72 | 0x48 | Time check |
| 73 | 0x49 | Time set |
| 76 | 0x4C | ID read |
| 77 | 0x4D | ID write |
| 78 | 0x4E | Status |

### Exported Methods

| Address | Method | Purpose |
|---------|--------|---------|
| 1030:0084 | $bctr | Constructor |
| 1030:0c67 | $bdtr | Destructor |
| 1030:0d06 | GetKeyTypeName | Get dongle type string |
| 1030:0d4d | LoadAccessCodes | Load codes from dongle |
| 1030:1019 | SaveAccessCodes | Save codes to dongle |
| 1030:12f5 | MitaKeyInstalled | Check dongle present |
| 1030:1323 | IsSuperKey | Check for admin key |
| 1030:1355 | HasTimeLimit | Check time expiry |
| 1030:13bb | SetKeyID | Set key identifier |
| 1030:1547 | SetKeyTime | Set expiry time |
| 1030:16f4 | GetKeyTime | Get expiry time |
| 1030:18b4 | GetSerialNumber | Get dongle serial |
| 1030:1a1e | ConfirmAccess | Verify access code |
| 1030:1abb | ConfirmAccessById | Verify by ID |
| 1030:1b05 | ConfirmAccessType | Verify by type |
| 1030:1bbf | ConfirmManCodeAccess | Manufacturer access |
| 1030:1c79 | GetAccessCode | Get stored code |
| 1030:1cad | GetFunctionNameOfCode | Get function name |
| 1030:1d36 | GetFunctionName | Get name by code |
| 1030:1d71 | PutAccessCode | Store access code |
| 1030:1dca | IsCodeEntryDisabled | Check if entry disabled |
| 1030:1e10 | EnableCodeEntry | Enable/disable entry |
| 1030:1e77 | ClearAccessCodes | Clear all codes |
| 1030:209b | GetClearCodeBase | Get base clear code |
| 1030:2105 | GetNextAvailableEntry | Get next free slot |
| 1030:216c | GetIndexOfCode | Find code index |
| 1030:21d6 | GetMaxAccessCodeCount | Get max codes |
| 1030:2250 | CallHasp | Direct HASP API |
| 1030:22fc | InitHaspKey | Initialize HASP |

## TTMEXButton Class

Located in segment 1038 (Code8), handles Dallas 1-Wire iButton devices.

### Button Types

```cpp
enum TButtonType {
    // Enumeration values determined by GetFamilyButtonCount
};
```

### Exported Methods

| Address | Method | Purpose |
|---------|--------|---------|
| 1038:0000 | $bctr | Constructor |
| 1038:0180 | $bdtr | Destructor |
| 1038:01c6 | GetFamilyButtonCount | Count buttons by type |
| 1038:0219 | SelectFamilyButton | Select specific button |
| 1038:02ad | GetSerialNumber | Get button serial |

### Communication Protocol

The 1-Wire protocol (FUN_1018_01d8) uses:
- Command 0xF0 - Reset/presence pulse
- 8x8 bit transfer pattern for data exchange
- Data stored at DAT_1050_2461 (8 bytes)

## Manufacturer Keys

License strings with embedded keys (found in data segment 1050):

| Offset | Manufacturer | Key Pattern |
|--------|--------------|-------------|
| 0x0320 | Nordex GmbH | wI4tsGD |
| 0x0334 | Micon A/S | hkGdteJsn |
| 0x0348 | Nordic WP | hhYt6&rvZ |
| 0x0370 | Tacke Wind | IsGjaTgy |
| 0x03e8 | Ellgard | 43jkb fgklh |
| 0x03fc | RivaCalzoni | #mk&65 |
| 0x040e | DeWind | %&'#sG5GFde3 |
| 0x0422 | Protec | /&HFUdgh4833 |
| 0x044a | WinCon | djssj2882jus |
| 0x0472 | Desarollos | %q=34as! |
| 0x05da | Mita-Teknik A/S | (master key) |

## Access Control Integration

Data point access is controlled via flags:

| Flag Address | Purpose |
|--------------|---------|
| DAT_1050_10ce | General data access |
| DAT_1050_10d0 | Special functions |
| DAT_1050_10d2 | Weather data (34000) |
| DAT_1050_10d6 | Extended data |
| DAT_1050_10d8 | Configuration access |
| DAT_1050_10da | Advanced features |

Protected data points call `TMitaKey::ConfirmAccess()` before granting access.

## 32-bit HASP Support

The code includes 32-bit HASP support via thunking:

```
kernel.dll imports:
- LoadLibraryEx32W
- FreeLibrary32W
- GetProcAddress32W
- CallProc32W
- GetVDMPointer32W

CALLNEWVDDHASP - VDD (Virtual Device Driver) for HASP
```

This enables 16-bit code to call 32-bit HASP DLLs on Windows NT/2000.
