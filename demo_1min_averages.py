#!/usr/bin/env python3
"""
Demo script showing the new 1-minute averaged data collection in turbine monitor.

This demonstrates the enhanced data collection that now includes both current
values and 1-minute averages for grid power and voltage measurements.
"""

import json
from datetime import datetime

# Mock data that would come from the turbine
mock_turbine_data = {
    'wind_speed_mps': 12.3,
    'rotor_rpm': 28.5,
    'generator_rpm': 1650.0,
    'power_W': 2850.0,
    'l1v': 242.0,
    'l2v': 241.0,
    'l3v': 240.0,
    'status_message': 'Running',
    # New 1-minute averaged values
    'power_W_1min': 2720.0,
    'l1v_1min': 241.5,
    'l2v_1min': 240.8,
    'l3v_1min': 239.9
}

def display_data():
    """Display both current and 1-minute averaged data."""
    print("🌪️  Wind Turbine Monitor - Enhanced Data Display")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    print("📊 CURRENT VALUES:")
    print(f"  Wind Speed:     {mock_turbine_data['wind_speed_mps']:6.1f} m/s")
    print(f"  Grid Power:     {mock_turbine_data['power_W']:6.0f} W")
    print(f"  Rotor RPM:      {mock_turbine_data['rotor_rpm']:6.0f}")
    print(f"  Generator RPM:  {mock_turbine_data['generator_rpm']:6.0f}")
    print(f"  L1 Voltage:     {mock_turbine_data['l1v']:6.0f} V")
    print(f"  L2 Voltage:     {mock_turbine_data['l2v']:6.0f} V")
    print(f"  L3 Voltage:     {mock_turbine_data['l3v']:6.0f} V")
    print()
    
    print("📈 1-MINUTE AVERAGES:")
    print(f"  Grid Power:     {mock_turbine_data['power_W_1min']:6.0f} W")
    print(f"  L1 Voltage:     {mock_turbine_data['l1v_1min']:6.1f} V")
    print(f"  L2 Voltage:     {mock_turbine_data['l2v_1min']:6.1f} V")
    print(f"  L3 Voltage:     {mock_turbine_data['l3v_1min']:6.1f} V")
    print()
    
    print("📊 COMPARISON:")
    power_diff = mock_turbine_data['power_W'] - mock_turbine_data['power_W_1min']
    l1v_diff = mock_turbine_data['l1v'] - mock_turbine_data['l1v_1min']
    l2v_diff = mock_turbine_data['l2v'] - mock_turbine_data['l2v_1min']
    l3v_diff = mock_turbine_data['l3v'] - mock_turbine_data['l3v_1min']
    
    print(f"  Power Difference:   {power_diff:+6.0f} W")
    print(f"  L1V Difference:     {l1v_diff:+6.1f} V")
    print(f"  L2V Difference:     {l2v_diff:+6.1f} V")
    print(f"  L3V Difference:     {l3v_diff:+6.1f} V")
    print()
    
    print(f"Status: {mock_turbine_data['status_message']}")
    print()
    
    print("💡 MQTT Payload:")
    print(json.dumps(mock_turbine_data, indent=2))

if __name__ == '__main__':
    display_data()