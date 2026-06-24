"""
============================================================
  CareMate - Motor Diagnostic Test
  ============================================================
  Run this FIRST to verify all motors are working correctly
  before running person_following.py.

  Tests each direction individually with a 2-second hold.
  Run: python test_motors.py
============================================================
"""

import serial
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config


def run_test():
    print("=" * 50)
    print("  CareMate Motor Diagnostic Test")
    print("=" * 50)
    print(f"Connecting to {config.SERIAL_PORT} at {config.BAUD_RATE} baud...")

    try:
        ser = serial.Serial(config.SERIAL_PORT, config.BAUD_RATE, timeout=2)
    except serial.SerialException as e:
        print(f"ERROR: Cannot open serial port: {e}")
        print("Check: 1) Arduino is connected  2) SERIAL_PORT in config.py is correct")
        sys.exit(1)

    time.sleep(2)   # Wait for Arduino reset
    print("Connected!\n")

    tests = [
        ('F', "FORWARD  - Both motors should spin forward"),
        ('S', "STOP     - All motors should stop"),
        ('B', "BACKWARD - Both motors should spin backward"),
        ('S', "STOP"),
        ('L', "LEFT     - Left motors back, Right motors forward (spins LEFT)"),
        ('S', "STOP"),
        ('R', "RIGHT    - Left motors forward, Right motors back (spins RIGHT)"),
        ('S', "STOP"),
    ]

    for cmd, description in tests:
        print(f"  Testing: {description}")
        ser.write(cmd.encode())
        time.sleep(2)

    ser.write(b'S')
    ser.close()
    print("\nDiagnostic complete. All tests done.")
    print("If any motor direction is wrong, swap the wire pairs for that motor.")


if __name__ == "__main__":
    run_test()
