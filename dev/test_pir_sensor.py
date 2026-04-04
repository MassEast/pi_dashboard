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

def test_sensor_raw(gpio_pin=17):
    """Raw sensor state test - shows what the GPIO is actually reading"""
    
    if not GPIO_AVAILABLE:
        print("✗ Error: RPi.GPIO not available")
        print("This test must be run on a Raspberry Pi")
        return False
    
    print(f"Raw GPIO{gpio_pin} State Test")
    print("="*50)
    print("Shows actual GPIO pin state for 10 seconds")
    print("(The sensor may need 30-60 seconds to stabilize after power-on)\n")
    
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(gpio_pin, GPIO.IN)
        print(f"✓ GPIO{gpio_pin} initialized\n")
        print("Raw state reading (0=no motion, 1=motion):")
        print("-"*50)
        
        test_start = time.time()
        state_counts = {0: 0, 1: 0}
        
        while time.time() - test_start < 10:
            state = GPIO.input(gpio_pin)
            state_counts[state] += 1
            timestamp = time.strftime('%H:%M:%S')
            print(f"[{timestamp}] GPIO state: {state}", end="\r")
            time.sleep(0.2)
        
        print("\n" + "-"*50)
        print(f"State 0 (no motion): {state_counts[0]} times")
        print(f"State 1 (motion):    {state_counts[1]} times")
        
        if state_counts[1] > state_counts[0] * 2:
            print("\n⚠️  Sensor seems to be triggering constantly!")
            print("Possible issues:")
            print("  - Sensor not properly settled (wait 30-60s after power-on)")
            print("  - Wiring problem or voltage issue")
            print("  - Sensor pointing at heat source (warm object)")
        
        GPIO.cleanup(gpio_pin)
        return True
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        try:
            GPIO.cleanup()
        except:
            pass
        return False

def test_sensor_debounced(gpio_pin=17):
    """Test with debouncing to filter noise"""
    
    if not GPIO_AVAILABLE:
        print("✗ Error: RPi.GPIO not available")
        return False
    
    print(f"\nMotion Detection Test (with debouncing)")
    print("="*50)
    print("Testing for 30 seconds.")
    print("Wave your hand in front of the sensor.\n")
    
    motion_count = 0
    last_state = 0
    last_motion_time = 0
    debounce = 1.0  # Increased debounce to 1 second
    
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(gpio_pin, GPIO.IN)
        print("Monitoring for motion...\n")
        
        test_start = time.time()
        state_changes = []
        
        while time.time() - test_start < 30:
            current_state = GPIO.input(gpio_pin)
            current_time = time.time()
            
            # Detect rising edge (motion start) with debouncing
            if current_state == 1 and last_state == 0:
                if current_time - last_motion_time > debounce:
                    motion_count += 1
                    timestamp = time.strftime('%H:%M:%S')
                    elapsed = int(current_time - test_start)
                    print(f"  [{elapsed}s] MOTION #{motion_count} at {timestamp}")
                    state_changes.append((elapsed, 'MOTION'))
                    last_motion_time = current_time
            
            # Detect falling edge (motion end)
            elif current_state == 0 and last_state == 1:
                elapsed = int(current_time - test_start)
                print(f"  [{elapsed}s] Motion ended")
                state_changes.append((elapsed, 'END'))
            
            last_state = current_state
            time.sleep(0.1)
        
        print("\n" + "-"*50)
        print(f"Test completed!")
        print(f"Total motion events detected: {motion_count}")
        
        if motion_count > 0:
            print("✓ Sensor is working correctly!")
        else:
            print("⚠ No motion detected. Make sure to:")
            print("  - Wait 30-60 seconds after powering on the sensor")
            print("  - Wave your hand directly in front of the sensor")
            print("  - Check the wiring (VCC→5V, GND→GND, OUT→GPIO)")
        
        GPIO.cleanup(gpio_pin)
        return motion_count > 0
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
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
    
    # First: show raw state
    test_sensor_raw(gpio_pin)
    
    # Second: test with debouncing
    input("\nPress ENTER to start motion detection test (with debouncing)...")
    success = test_sensor_debounced(gpio_pin)
    
