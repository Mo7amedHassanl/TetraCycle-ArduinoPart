# Tetracycle Arduino-Firebase Bridge

This directory contains the bridge script and Arduino code for the Tetracycle water treatment system.

## Overview

- The Arduino code simulates a water treatment process and outputs sensor values (pH, turbidity, TDS) as well as pump and servo states over serial every second.
- The Python script (`tetracycle_firebase_bridge.py`) reads these values from the Arduino and uploads them to Firebase Realtime Database.
- The system supports bidirectional control: the Android app can control pumps, servo, and system state through Firebase, and the bridge script sends these commands to the Arduino.
- The system maintains consistent state across the Arduino, Python bridge, and Firebase database.

---

## Setup

### 1. Hardware
- Upload `Arduino_code.ino` to your Arduino board.
- **Important**: You need to install the following libraries in your Arduino IDE:
  - ArduinoJson (version 6.x): Tools → Manage Libraries → Search for "ArduinoJson" → Install
  - LiquidCrystal_I2C: Tools → Manage Libraries → Search for "LiquidCrystal I2C" → Install
  - Servo: Usually included with Arduino IDE
- Connect the board to your computer via USB.

### 2. Firebase
- Create a Firebase project (or use the provided one).
- Download the service account key for your project and save it as `firebase_credentials.json` in this directory.
- Set your Realtime Database rules to allow read/write (for testing):
  ```json
  {
    "rules": {
      ".read": true,
      ".write": true
    }
  }
  ```

### 3. Python Environment
- Install dependencies:
  ```sh
  pip install pyserial firebase-admin
  ```

---

## Running the Bridge Script

From the `tetracycle` directory, run:
```sh
python tetracycle_firebase_bridge.py --port COM6
```
Replace `COM6` with your Arduino's serial port.

- The script will print sensor values as it uploads them every second.
- All sensor data, pump states, and servo position will be uploaded to Firebase.
- Any changes to the control values in Firebase will be sent to the Arduino.
- The script will periodically sync the Arduino's current state back to Firebase.

---

## Firebase Data Structure

### Sensor Data
- Uploaded to `/tetracycle_sensor_data` as timestamped entries:
  ```json
  {
    "ph": 7.12,
    "turbidity": 123.4,
    "tds": 456.7
  }
  ```

### Control Data
- The system is controlled by setting values in `/tetracycle_control`:
  ```json
  {
    "pump1": 0,
    "pump2": 0,
    "servo": 0,
    "system": 0,
    "last_updated": "2024-05-07 13:32:59"
  }
  ```

#### Control Parameters
| Parameter  | Values       | Description                        |
|------------|-------------|------------------------------------|
| `pump1`    | 0 or 1      | Controls pump 1 (LED 1) on/off     |
| `pump2`    | 0 or 1      | Controls pump 2 (LED 2) on/off     |
| `servo`    | 0 or 1      | Controls servo position (0° or 180°)|
| `system`   | 0 or 1      | 1 = Start the system, 0 = Reset    |

**Example:**
To turn on pump 1, set:
```json
{
  "pump1": 1
}
```

To move the servo to position 180°:
```json
{
  "servo": 1
}
```

---

## Key Features

### Reliable State Management
- The system maintains persistent state for pumps, servo, and system across power cycles.
- When the Arduino receives a command, it stores the state in memory and reflects it in hardware.
- Every JSON response from Arduino includes the current states of all components.
- The Python bridge synchronizes with Firebase every 5 seconds to ensure database consistency.

### Error Handling
- The system can recover from communication errors and buffer overflows automatically.
- If the serial connection experiences issues, it will attempt to reset the connection.
- JSON parsing errors are handled gracefully with buffer reset mechanisms.
- The system will not lose control state due to communication errors.

### Real-time Updates
- Sensor values are collected and uploaded every second.
- Control commands are processed immediately when received from Firebase.
- The Arduino sends status updates every second for consistent state tracking.
- All state changes are confirmed in both directions with acknowledgment.

### Software Architecture
- The Python bridge uses a single-threaded polling model to avoid socket permission issues.
- The Arduino tracks component states separately from hardware states for consistent reporting.
- Command processing in Arduino uses the ArduinoJson library for reliable JSON parsing.
- System, pump, and servo states are maintained independently to avoid interference.

---

## Bidirectional Updates
- When you change a value in Firebase (via the Android app), the command is sent to the Arduino.
- When the Arduino processes a command, it reports back its current state.
- The Python bridge updates Firebase to keep the database in sync with the hardware.
- This creates a bidirectional link where both the database and the hardware stay in sync.

### Android App Integration
- The Android app has 4 cards, one for each control parameter.
- When a card is clicked, it toggles the corresponding control value in Firebase.
- The bridge script detects these changes and sends commands to the Arduino.
- The Arduino processes these commands, updates its state, and sends confirmation.

---

## Troubleshooting
- If you see `Unauthorized request`, check your credentials and database rules.
- If no sensor values are uploaded, make sure the Arduino is outputting JSON to serial and the correct port is used.
- Only one program can use the Arduino serial port at a time.
- If commands aren't being processed correctly, check the output for any error messages.
- If control values reset unexpectedly, ensure the state tracking variables are properly maintained.
- For socket permission errors on Windows, make sure no firewall is blocking the connection.

---

## Files
- `Arduino_code/Arduino_code.ino` — Arduino code for the Tetracycle system
- `tetracycle_firebase_bridge.py` — Python bridge script
- `firebase_credentials.json` — Firebase service account key (keep this private!) 