#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Test script for HC-SR505 PIR Sensor
Run this to verify your sensor connection before running the full dashboard
"""

import time
import sys
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning("RPi.GPIO not available - this test must run on Raspberry Pi")

def print_header():
    print("\n" + "="*50)
    print("   HC-SR505 PIR Sensor Test")
    print("="*50 + "\n")

def test_sensor(gpio_pin=17):
    """Test PIR sensor on specified GPIO pin"""
    
    if not GPIO_AVAILABLE:
        print("✗ Error: RPi.GPIO not available")
        print("This test must be run on a Raspberry Pi")
        return False
    
    print(f"Testing PIR Sensor on GPIO{gpio_pin}...")
    print("This test will run for 30 seconds.")
    print("Wave your hand in front of the sensor to test motion detection.\n")
    
    motion_count = 0
    last_state = 0
    last_motion_time = 0
    debounce = 0.5
    
    try:
        # Initialize GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(gpio_pin, GPIO.IN)
        print(f"✓ GPIO{gpio_pin} initialized successfully\n")
        print("Monitoring motion for 30 seconds...\n")
        
        test_start = time.time()
        while time.time() - test_start < 30:
            current_state = GPIO.input(gpio_pin)
            current_time = time.time()
            
            # Detect rising edge (motion start)
            if current_state == 1 and last_state == 0:
                if current_time - last_motion_time > debounce:
                    motion_count += 1
                    timestamp = time.strftime('%H:%M:%S')
                    print(f"  [MOTION #{motion_count}] Motion detected at {timestamp}")
                    last_motion_time = current_time
            
            status = "🔴 Motion detected" if current_state == 1 else "⚪ No motion"
            print(f"\r{status}", end="", flush=True)
            
            last_state = current_state
            time.sleep(0.1)
        
        print("\n\n" + "-"*50)
        print(f"Test completed!")
        print(f"Total motion events detected: {motion_count}")
        
        if motion_count > 0:
            print("✓ Sensor is working correctly!")
            result = True
        else:
            print("⚠ No motion detected. Check:")
            print("  - Sensor wiring (VCC→5V, GND→GND, OUT→GPIO)")
            print("  - GPIO pin number")
            print("  - Sensor power supply")
            result = False
        
        GPIO.cleanup(gpio_pin)
        print("-"*50 + "\n")
        return result
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("\nTroubleshooting:")
        print("  1. Make sure you have RPi.GPIO installed: pip install RPi.GPIO")
        print("  2. Verify sensor wiring on GPIO{gpio_pin}")
        print("  3. Run with sudo if you get permission errors: sudo python3 test_pir_sensor.py")
        try:
            GPIO.cleanup()
        except:
            pass
        return False

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
