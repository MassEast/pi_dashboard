#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Test script for HC-SR505 PIR Sensor
Run this to verify your sensor connection before running the full dashboard
"""

import time
import sys
from pir_sensor import PIRSensor

def print_header():
    print("\n" + "="*50)
    print("   HC-SR505 PIR Sensor Test")
    print("="*50 + "\n")

def test_sensor(gpio_pin=17):
    """Test PIR sensor on specified GPIO pin"""
    
    print(f"Testing PIR Sensor on GPIO{gpio_pin}...")
    print("This test will run for 30 seconds.")
    print("Wave your hand in front of the sensor to test motion detection.\n")
    
    motion_count = 0
    
    def motion_callback():
        nonlocal motion_count
        motion_count += 1
        print(f"  [MOTION #{motion_count}] Motion detected at {time.strftime('%H:%M:%S')}")
    
    try:
        # Create and start sensor
        sensor = PIRSensor(gpio_pin=gpio_pin, motion_callback=motion_callback)
        sensor.start()
        
        print(f"✓ Sensor initialized successfully\n")
        print("Monitoring motion for 30 seconds...\n")
        
        test_start = time.time()
        while time.time() - test_start < 30:
            status = "🔴 Motion detected" if sensor.is_motion_detected() else "⚪ No motion"
            print(f"\r{status}", end="", flush=True)
            time.sleep(0.1)
        
        print("\n\n" + "-"*50)
        print(f"Test completed!")
        print(f"Total motion events detected: {motion_count}")
        
        if motion_count > 0:
            print("✓ Sensor is working correctly!")
        else:
            print("⚠ No motion detected. Check:")
            print("  - Sensor wiring")
            print("  - GPIO pin number")
            print("  - Sensor power (usually needs 5V)")
        
        sensor.stop()
        print("-"*50 + "\n")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("\nSetup required:")
        print("  1. Install RPi.GPIO: pip install RPi.GPIO")
        print("  2. Verify sensor wiring on GPIO{gpio_pin}")
        print("  3. Run this test from Raspberry Pi")
        return False
    
    return motion_count > 0

if __name__ == "__main__":
    print_header()
    
    # Get GPIO pin from command line or use default
    gpio_pin = 17
    if len(sys.argv) > 1:
        try:
            gpio_pin = int(sys.argv[1])
            print(f"Using GPIO pin: {gpio_pin}\n")
        except ValueError:
            print(f"Invalid GPIO pin: {sys.argv[1]}")
            print(f"Using default GPIO pin: {gpio_pin}\n")
    
    success = test_sensor(gpio_pin)
    sys.exit(0 if success else 1)
