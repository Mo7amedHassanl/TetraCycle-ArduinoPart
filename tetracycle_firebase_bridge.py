import serial
import json
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import argparse
import os
import threading
import signal
import sys

# Firebase config
FIREBASE_URL = 'https://loayapp-58fa1-default-rtdb.firebaseio.com/'
# Update credential path to make sure it's found
CRED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'firebase_credentials.json')
SENSOR_DB_PATH = '/tetracycle_sensor_data'
CONTROL_DB_PATH = '/tetracycle_control'

running = True
serial_lock = threading.Lock()

# Current status tracking for sensors
current_status = {
    'ph': 0,
    'turbidity': 0,
    'tds': 0,
    'pumps': [0, 0],
    'servo': 0,
    'system': 0
}
status_lock = threading.Lock()

def signal_handler(sig, frame):
    """Handle shutdown signals more safely to prevent reentrant calls."""
    global running
    # Set the running flag to False to trigger clean shutdown
    running = False
    # Use sys.stderr directly to avoid potential reentrant calls with print()
    sys.stderr.write("\nProgram shutdown initiated...\n")
    sys.stderr.flush()

def parse_arguments():
    parser = argparse.ArgumentParser(description='Read sensor data from Arduino and upload to Firebase')
    parser.add_argument('--port', '-p', type=str, required=True, help='Serial port (e.g., COM3, /dev/ttyUSB0)')
    parser.add_argument('--baud', '-b', type=int, default=9600, help='Baud rate (default: 9600)')
    parser.add_argument('--interval', '-i', type=int, default=1, help='Upload interval in seconds (default: 1)')
    parser.add_argument('--reconnect', '-r', action='store_true', help='Enable automatic reconnection')
    return parser.parse_args()

def initialize_firebase():
    print(f"Looking for Firebase credentials at: {CRED_PATH}")
    if not os.path.exists(CRED_PATH):
        print(f"ERROR: Firebase credentials file '{CRED_PATH}' not found!")
        # Print current working directory for debugging
        print(f"Current working directory: {os.getcwd()}")
        print(f"Contents of current directory: {os.listdir(os.getcwd())}")
        parent_dir = os.path.dirname(os.getcwd())
        print(f"Contents of parent directory: {os.listdir(parent_dir)}")
        exit(1)
    
    try:
        print(f"Reading credential file...")
        cred = credentials.Certificate(CRED_PATH)
        print(f"Initializing Firebase with URL: {FIREBASE_URL}")
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_URL})
        print("Firebase initialized successfully.")
    except Exception as e:
        print(f"Error during Firebase initialization: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

def open_serial(port, baud):
    try:
        ser = serial.Serial(port, baud, timeout=1)
        print(f"Connected to {port} at {baud} baud")
        time.sleep(2)
        return ser
    except serial.SerialException as e:
        print(f"Error opening serial port: {e}")
        return None

def close_serial(ser):
    if ser and ser.is_open:
        ser.close()
        print("Serial connection closed")

def update_status(data):
    """Update the current status dictionary with received data"""
    global current_status
    with status_lock:
        if 'ph' in data:
            current_status['ph'] = data['ph']
            
        if 'turbidity' in data:
            current_status['turbidity'] = data['turbidity']
            
        if 'tds' in data:
            current_status['tds'] = data['tds']
        
        # Handle pump values
        if 'pumps' in data:
            current_status['pumps'] = data['pumps']
        
        # Direct pump values might also be sent (especially in responses to commands)
        if 'pump1' in data:
            # Ensure pumps array exists
            if 'pumps' not in current_status:
                current_status['pumps'] = [0, 0]
            # Update pump1 value (first element in pumps array)
            current_status['pumps'][0] = 1 if data['pump1'] else 0
            print(f"DEBUG: Updated pump1 status to {current_status['pumps'][0]}")
            
        if 'pump2' in data:
            # Ensure pumps array exists
            if 'pumps' not in current_status:
                current_status['pumps'] = [0, 0]
            # Update pump2 value (second element in pumps array)
            current_status['pumps'][1] = 1 if data['pump2'] else 0
            print(f"DEBUG: Updated pump2 status to {current_status['pumps'][1]}")
            
        if 'servo' in data:
            current_status['servo'] = data['servo']
            
        if 'system' in data:
            current_status['system'] = data['system']

def send_command_to_arduino(ser, command):
    """Send a command to Arduino over serial with proper locking"""
    with serial_lock:
        try:
            if not ser or not ser.is_open:
                print("ERROR: Serial connection is not open")
                return False
                
            # Make sure values are integers, as Arduino expects integers (0 or 1)
            formatted_command = {}
            for key in command:
                if key in ['pump1', 'pump2', 'servo', 'system']:
                    # Convert any value to either 0 or 1
                    value = 1 if command[key] else 0
                    formatted_command[key] = value
            
            # Skip if no commands to send
            if not formatted_command:
                print("WARNING: No valid commands to send")
                return False
                
            # Special handling for pump commands - log additional details
            if 'pump1' in formatted_command or 'pump2' in formatted_command:
                print(f"DEBUG: Sending pump command: pump1={formatted_command.get('pump1', 'not set')}, pump2={formatted_command.get('pump2', 'not set')}")
            
            command_json = json.dumps(formatted_command) + '\n'
            print(f"DEBUG: Writing to serial: {command_json.strip()}")
            
            # Flush any pending input before sending command
            if ser.in_waiting:
                ser.read(ser.in_waiting)
                
            # Send command
            ser.write(command_json.encode('utf-8'))
            ser.flush()  # Ensure data is sent immediately
            print(f"Sent command to Arduino: {formatted_command}")
            
            # Wait for response (can be increased if needed)
            time.sleep(0.5)  # Increased wait time for Arduino to process
            
            # Check if data is available to read after sending command
            response_received = False
            response_data = None
            start_time = time.time()
            
            while time.time() - start_time < 2.0:  # Wait up to 2 seconds for response
                if ser.in_waiting:
                    try:
                        raw_data = ser.read(ser.in_waiting).decode('utf-8', errors='replace')
                        print(f"DEBUG: Received from Arduino: {raw_data}")
                        
                        # Check if we got valid JSON in the response
                        if '{' in raw_data and '}' in raw_data:
                            start_idx = raw_data.find('{')
                            end_idx = raw_data.find('}', start_idx) + 1
                            json_str = raw_data[start_idx:end_idx]
                            
                            try:
                                response_data = json.loads(json_str)
                                print(f"DEBUG: Parsed response: {response_data}")
                                response_received = True
                                
                                # Update our status tracking with the response
                                update_status(response_data)
                                break
                            except json.JSONDecodeError:
                                print(f"Warning: Received invalid JSON: {json_str}")
                        else:
                            print(f"Received non-JSON response: {raw_data}")
                    except Exception as e:
                        print(f"Error reading response: {e}")
                        
                time.sleep(0.1)
                
            if not response_received:
                print("WARNING: No valid JSON response from Arduino after command")
            
            return True
        except Exception as e:
            print(f"Error sending command to Arduino: {e}")
            import traceback
            traceback.print_exc()
            return False

def control_listener(ser):
    """Listen for changes in the control database path and send commands to Arduino.
    Uses polling instead of continuous streaming to avoid socket permission issues."""
    control_ref = db.reference(CONTROL_DB_PATH)
    
    # Store previous control state to track changes
    previous_control = {
        'pump1': 0,
        'pump2': 0,
        'servo': 0,
        'system': 0
    }
    
    # Get initial values from Firebase
    print("DEBUG: Getting initial control values from Firebase...")
    try:
        current_values = control_ref.get()
        if current_values:
            print(f"DEBUG: Initial control values: {current_values}")
            # Apply initial values
            command = {}
            for key in ['pump1', 'pump2', 'servo', 'system']:
                if key in current_values:
                    previous_control[key] = current_values[key]
                    command[key] = current_values[key]
            
            if command:
                print(f"DEBUG: Sending initial control values to Arduino: {command}")
                send_command_to_arduino(ser, command)
    except Exception as e:
        print(f"DEBUG: Error getting initial control values: {e}")
    
    print("Firebase control polling started (checking for changes every 2 seconds)")
    
    # Keep polling while running
    while running:
        try:
            # Use polling instead of continuous streaming to avoid socket issues
            time.sleep(2)  # Poll every 2 seconds
            
            # Get current values
            current_values = control_ref.get()
            if not current_values:
                continue
                
            # Track changes and send commands
            changed = False
            command = {}
            
            # Check for changes in control values
            for key in ['pump1', 'pump2', 'servo', 'system']:
                if key in current_values:
                    value = int(current_values[key]) if current_values[key] is not None else 0
                    
                    # Force to 0 or 1
                    value = 1 if value else 0
                    
                    if value != previous_control[key]:
                        previous_control[key] = value
                        command[key] = value
                        changed = True
                        print(f"DEBUG: Value changed: {key}={value}")
            
            if changed:
                print(f"Control change detected: {command}")
                
                # For system changes, ensure we're sending a full command with the correct value
                if 'system' in command:
                    print(f"DEBUG: System command value: {command['system']} (type: {type(command['system']).__name__})")
                    
                result = send_command_to_arduino(ser, command)
                print(f"Command sent successfully: {result}")
                
                # Wait a moment for Arduino to process the command
                time.sleep(0.5)
                
                # Verify the current values match what we sent
                with status_lock:
                    status_string = []
                    for key in command:
                        if key == 'pump1':
                            status_string.append(f"Pump1: sent={command[key]}, current={current_status['pumps'][0]}")
                        elif key == 'pump2':
                            status_string.append(f"Pump2: sent={command[key]}, current={current_status['pumps'][1]}")
                        elif key in ['servo', 'system']:
                            status_string.append(f"{key.capitalize()}: sent={command[key]}, current={current_status[key]}")
                    
                    print(f"Status after command: {', '.join(status_string)}")
                
                # Update the timestamp in Firebase
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                control_ref.update({'last_updated': now})
                
        except Exception as e:
            print(f"Error in control listener polling: {e}")
            # Don't immediately retry on error - wait for next poll
            time.sleep(5)

def read_and_upload_data(ser, upload_interval):
    """Read sensor data from Arduino without uploading to Firebase.
    This function now only handles reading from the serial port and updating the current_status."""
    
    # Use static variables to maintain state between calls
    if not hasattr(read_and_upload_data, "buffer"):
        read_and_upload_data.buffer = ''
        read_and_upload_data.error_count = 0
    
    try:
        if not ser.is_open:
            raise Exception("Serial port is not open")
            
        if ser.in_waiting:
            raw_data = ser.read(ser.in_waiting).decode('utf-8', errors='replace')
            read_and_upload_data.buffer += raw_data
            
            # Debug output of raw data when issues occur
            if '{' in read_and_upload_data.buffer and '}' not in read_and_upload_data.buffer and len(read_and_upload_data.buffer) > 100:
                # Reset buffer if it seems corrupted
                read_and_upload_data.buffer = read_and_upload_data.buffer[read_and_upload_data.buffer.rfind('{'):]
                if len(read_and_upload_data.buffer) > 100:
                    read_and_upload_data.buffer = ''  # If still too large, just reset it
                return
            
            while '{' in read_and_upload_data.buffer and '}' in read_and_upload_data.buffer:
                try:
                    start_idx = read_and_upload_data.buffer.find('{')
                    end_idx = read_and_upload_data.buffer.find('}', start_idx) + 1
                    json_str = read_and_upload_data.buffer[start_idx:end_idx]
                    read_and_upload_data.buffer = read_and_upload_data.buffer[end_idx:]
                    
                    # Skip processing if very short or very long
                    if len(json_str) < 5 or len(json_str) > 500:
                        continue
                        
                    data = json.loads(json_str)
                    
                    # Reset error count when we get valid JSON
                    read_and_upload_data.error_count = 0
                    
                    # Update our status tracking
                    update_status(data)
                    
                except json.JSONDecodeError:
                    # Limit error messages to prevent flooding the console
                    current_time = time.time()
                    read_and_upload_data.error_count += 1
                    
                    # Only report errors periodically to avoid output flooding
                    if read_and_upload_data.error_count % 1000 == 0:  # Report every 1000 errors
                        print(f"JSON parsing errors detected: {read_and_upload_data.error_count} errors so far")
                        
                        # After many errors, clear the buffer
                        if read_and_upload_data.error_count > 10000:
                            read_and_upload_data.buffer = ''
                            break
                except Exception as e:
                    print(f"Error processing JSON data: {str(e)}")
            
            # Process any remaining non-JSON data if buffer is getting too large
            if len(read_and_upload_data.buffer) > 500:  # Reduced to avoid large buffer buildups
                # Just clear the buffer if it's too large and doesn't have proper JSON
                if '{' not in read_and_upload_data.buffer or '}' not in read_and_upload_data.buffer:
                    read_and_upload_data.buffer = ''
                else:
                    # Keep only from the last opening brace
                    read_and_upload_data.buffer = read_and_upload_data.buffer[read_and_upload_data.buffer.rfind('{'):]
        
    except Exception as e:
        # Don't use traceback or complex printing that might cause reentrant calls
        print(f"Error in read_and_upload_data: {str(e)}")
        read_and_upload_data.error_count += 1
        # Return to allow main loop to handle error

def initialize_control_values():
    """Initialize the control values in Firebase if they don't exist"""
    control_ref = db.reference(CONTROL_DB_PATH)
    default_values = {
        'pump1': 0,
        'pump2': 0,
        'servo': 0,
        'system': 0,
        'last_updated': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Get existing data
    control_data = control_ref.get()
    
    # If path doesn't exist or is missing values, initialize them
    if not control_data:
        control_ref.set(default_values)
        print("Initialized control values in Firebase")
    else:
        # Check if any required fields are missing
        update_needed = False
        update_values = {}
        
        for key, value in default_values.items():
            if key not in control_data:
                update_values[key] = value
                update_needed = True
                
        if update_needed:
            control_ref.update(update_values)
            print(f"Updated missing control values in Firebase: {update_values}")
            
    # Make sure the last_updated field is current
    control_ref.update({'last_updated': datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

def test_firebase_connectivity():
    """Test Firebase connectivity and database rules."""
    print("Testing Firebase connectivity...")
    # Try to read from a test location
    test_ref = db.reference('/test')
    try:
        print("Testing read access...")
        test_data = test_ref.get()
        print(f"Read test successful. Data: {test_data}")
    except Exception as e:
        print(f"Read test failed: {e}")
        
    # Try to write to a test location
    try:
        print("Testing write access...")
        test_ref.set({"test_value": "test", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        print("Write test successful.")
    except Exception as e:
        print(f"Write test failed: {e}")
        print("This suggests your database rules are restricting access.")
        print("Please check your Firebase console and update your rules to allow read/write.")
        print("Recommended test rules: { 'rules': { '.read': true, '.write': true } }")

def reset_serial_port(ser):
    """Attempt to reset the serial port to recover from communication issues."""
    if ser and ser.is_open:
        try:
            # Close the port
            ser.close()
            print("Serial port closed for reset")
            time.sleep(1)  # Wait a moment
            
            # Reopen with same settings
            port = ser.port
            baud = ser.baudrate
            ser.open()
            print(f"Serial port {port} reopened at {baud} baud")
            time.sleep(2)  # Allow Arduino to reset
            return True
        except Exception as e:
            print(f"Error resetting serial port: {e}")
            return False
    return False

def main():
    global running
    args = parse_arguments()
    signal.signal(signal.SIGINT, signal_handler)
    try:
        initialize_firebase()
        
        # Test Firebase connectivity
        test_firebase_connectivity()
        
        # Initialize control values if needed
        initialize_control_values()
        
        ser = open_serial(args.port, args.baud)
        if not ser:
            print("Failed to connect to Arduino. Exiting.")
            return
        
        # Track serial errors for potential reset
        serial_errors = 0
        last_reset_time = time.time()
        last_firebase_update = time.time()
        last_sensor_upload = time.time()
        last_control_sync = time.time()
        
        # Run main loop handling both serial reading and Firebase polling
        print("Starting main loop - handling both serial and Firebase...")
        while running:
            try:
                # Check if we need to reset the serial port
                current_time = time.time()
                if serial_errors > 100 and current_time - last_reset_time > 60:  # More than 100 errors and at least 60 seconds since last reset
                    print("Too many serial errors, attempting to reset serial connection...")
                    if reset_serial_port(ser):
                        serial_errors = 0
                        last_reset_time = current_time
                        print("Serial port reset successful")
                    else:
                        print("Serial port reset failed")
                
                # Process serial data
                try:
                    # Call the read function which handles reading from serial
                    read_and_upload_data(ser, args.interval)
                    
                    # Check if it's time to upload sensor data (every 1 second)
                    if current_time - last_sensor_upload >= 1.0:
                        with status_lock:
                            # Create a sensor data object for upload
                            sensor_data = {
                                'ph': current_status.get('ph', 0),
                                'tds': current_status.get('tds', 0),
                                'turbidity': current_status.get('turbidity', 0)
                            }
                            
                            # Generate timestamp key and upload
                            timestamp_key = datetime.now().strftime("%Y%m%d%H%M%S")
                            sensor_ref = db.reference(SENSOR_DB_PATH)
                            sensor_ref.child(timestamp_key).set(sensor_data)
                            print(f"Uploaded to Firebase: {sensor_data}")
                            
                            # Display current states for debugging
                            print(f"States - Pump1: {current_status['pumps'][0]}, Pump2: {current_status['pumps'][1]}, Servo: {current_status['servo']}, System: {current_status['system']}")
                            
                            last_sensor_upload = current_time
                            
                            # Also sync control values every 5 seconds
                            if current_time - last_control_sync >= 5.0:
                                try:
                                    # Update control values in Firebase based on actual values from Arduino
                                    control_ref = db.reference(CONTROL_DB_PATH)
                                    control_updates = {
                                        'pump1': current_status['pumps'][0],
                                        'pump2': current_status['pumps'][1],
                                        'servo': current_status['servo'],
                                        'system': current_status['system'],
                                        'last_updated': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    }
                                    
                                    # Only update if there's a change
                                    control_ref.update(control_updates)
                                    last_control_sync = current_time
                                    print(f"Synced control values to Firebase: {control_updates}")
                                except Exception as e:
                                    print(f"Error syncing control values: {e}")
                    
                except Exception as e:
                    serial_errors += 1
                    print(f"Error processing serial data: {e}")
                
                # Check Firebase for control updates (every 2 seconds)
                if current_time - last_firebase_update >= 2.0:
                    try:
                        control_ref = db.reference(CONTROL_DB_PATH)
                        current_values = control_ref.get()
                        
                        if current_values:
                            # Process control values
                            process_control_values(ser, current_values)
                            
                        last_firebase_update = current_time
                    except Exception as e:
                        print(f"Error checking Firebase: {e}")
                
                # Small delay to prevent CPU overuse
                time.sleep(0.05)
                
            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(1)
                
    except Exception as e:
        print(f"Error in main: {e}")
    finally:
        if 'ser' in locals():
            close_serial(ser)

def process_control_values(ser, current_values):
    """Process control values from Firebase and send commands to Arduino if changed."""
    # Use a static variable to store previous control values
    if not hasattr(process_control_values, "previous_control"):
        process_control_values.previous_control = {
            'pump1': None,
            'pump2': None,
            'servo': None,
            'system': None
        }
    
    # Track changes and send commands
    changed = False
    command = {}
    
    # Check for changes in control values
    for key in ['pump1', 'pump2', 'servo', 'system']:
        if key in current_values:
            try:
                # Convert to integer, handling None and non-integer values
                if current_values[key] is None:
                    value = 0
                else:
                    # Force non-zero values to 1, and zero to 0
                    value = 1 if int(current_values[key]) else 0
                
                # Compare with previous value, treating None as different
                if process_control_values.previous_control[key] is None or value != process_control_values.previous_control[key]:
                    process_control_values.previous_control[key] = value
                    command[key] = value
                    changed = True
                    print(f"DEBUG: Value changed: {key}={value}")
            except (ValueError, TypeError) as e:
                print(f"ERROR: Invalid value for {key}: {current_values[key]} - {str(e)}")
                # Set to default value (0) if there's an error
                if process_control_values.previous_control[key] is None:
                    process_control_values.previous_control[key] = 0
    
    if changed:
        print(f"Control change detected: {command}")
        
        # For system changes, ensure we're sending a full command with the correct value
        if 'system' in command:
            print(f"DEBUG: System command value: {command['system']} (type: {type(command['system']).__name__})")
        if 'pump1' in command:
            print(f"DEBUG: Pump1 command value: {command['pump1']} (type: {type(command['pump1']).__name__})")
        if 'pump2' in command:
            print(f"DEBUG: Pump2 command value: {command['pump2']} (type: {type(command['pump2']).__name__})")
            
        result = send_command_to_arduino(ser, command)
        print(f"Command sent successfully: {result}")
        
        # Wait a moment for Arduino to process the command
        time.sleep(0.5)
        
        # Verify the current values match what we sent
        with status_lock:
            status_string = []
            for key in command:
                if key == 'pump1':
                    # Check what we have in current_status
                    actual_value = current_status['pumps'][0] if 'pumps' in current_status and len(current_status['pumps']) > 0 else "unknown"
                    status_string.append(f"Pump1: sent={command[key]}, current={actual_value}")
                elif key == 'pump2':
                    # Check what we have in current_status
                    actual_value = current_status['pumps'][1] if 'pumps' in current_status and len(current_status['pumps']) > 1 else "unknown"
                    status_string.append(f"Pump2: sent={command[key]}, current={actual_value}")
                elif key in ['servo', 'system']:
                    status_string.append(f"{key.capitalize()}: sent={command[key]}, current={current_status.get(key, 'unknown')}")
            
            print(f"Status after command: {', '.join(status_string)}")
            
            # Debug current_status content
            print(f"DEBUG: Full current_status: {current_status}")
        
        # Update the timestamp in Firebase
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        control_ref = db.reference(CONTROL_DB_PATH)
        
        # Update all control values in Firebase to match what we sent
        updates = {'last_updated': now}
        for key, value in command.items():
            updates[key] = value
            
        control_ref.update(updates)

if __name__ == '__main__':
    main() 