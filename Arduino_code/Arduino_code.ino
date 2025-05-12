#include <LiquidCrystal_I2C.h>
#include <avr/wdt.h>
#include <Servo.h>
#include <Arduino.h>
#include <ArduinoJson.h>

Servo myServo;
LiquidCrystal_I2C lcd(0x27, 16, 2);

//  Pins 
const int ledPin1 = 12;
const int ledPin2 = 13;
const int buttonPin = 2;

//  State Flags 
bool systemStarted = false;
bool reachedLimit = false;
bool servoMoved = false;
bool inElkammar = true;
bool finalDisplayed = false;

//  TDS
float tdsValue = 1180.0;
const float tdsLimit = 457.0;

const unsigned long updateInterval = 1000;
const unsigned long lcdUpdateInterval = 3000;
unsigned long lastUpdate = 0;
unsigned long lastLCDUpdate = 0;
unsigned long finalTime = 0;
unsigned long startTime = 0;

const unsigned long intervals[] = {90000, 188000, 288000, 360000, 432000, 512000, 645000};
const float rates[] = {30.51, 0.905, 1.294, 1.545, 0.134, 0.242, 0.3693};
unsigned long intervalStarts[8];

//  Turbidity 
float turbidityValue = 553.0;
const float turbidityLimit = 27.0;
const unsigned long turbIntervals[] = {60000, 120000, 180000, 240000, 300000};
const float turbRates[] = {1.2, 0.9, 0.65, 0.47, 0.31};
unsigned long turbIntervalStarts[6];

//  pH 
float pHValue = 9.5;
const float pHLimit = 7.4;
const unsigned long phIntervals[] = {60000, 120000, 180000, 240000, 300000};
const float phRates[] = {0.03, 0.025, 0.021, 0.018, 0.015};
unsigned long phIntervalStarts[6];

// For sensor data upload
unsigned long lastSerialUpload = 0;
const unsigned long serialUploadInterval = 1000;

// For command processing
String inputBuffer = "";
bool cmdComplete = false;

// Declare these at the top of the file with other globals
bool pumpState1 = false; // Track pump1 state
bool pumpState2 = false; // Track pump2 state
bool servoState = false; // Track servo state

void setup() {
  Serial.begin(9600);
  delay(500);  // Give time for serial to initialize
  Serial.println("Arduino started!");
  wdt_disable();

  myServo.attach(9);
  myServo.write(0);  // Initialize servo position
  
  lcd.init();
  lcd.backlight();

  pinMode(ledPin1, OUTPUT);
  pinMode(ledPin2, OUTPUT);
  pinMode(buttonPin, INPUT_PULLUP);

  digitalWrite(ledPin1, LOW);
  digitalWrite(ledPin2, LOW);
  
  // Initialize state tracking variables
  pumpState1 = false;
  pumpState2 = false;
  servoState = false;

  lcd.setCursor(0, 0);
  lcd.print("Have A Better");
  lcd.setCursor(0, 1);
  lcd.print("LIFE With....");

  intervalStarts[0] = 0;
  for (int i = 0; i < 7; i++) {
    intervalStarts[i + 1] = intervalStarts[i] + intervals[i];
  }

  turbIntervalStarts[0] = 0;
  for (int i = 0; i < 5; i++) {
    turbIntervalStarts[i + 1] = turbIntervalStarts[i] + turbIntervals[i];
  }

  phIntervalStarts[0] = 0;
  for (int i = 0; i < 5; i++) {
    phIntervalStarts[i + 1] = phIntervalStarts[i] + phIntervals[i];
  }
  
  // Reset all state
  systemStarted = false;
  reachedLimit = false;
  servoMoved = false;
  inElkammar = true;
  finalDisplayed = false;
  
  // Send initial status after setup
  Serial.println("DEBUG: Initialization complete");
  Serial.println("DEBUG: Sending initial status");
  sendCurrentStatus();
}

void loop() {
  unsigned long currentTime = millis();

  // Process any incoming serial commands
  processSerialCommands();

  // Output sensor values as JSON every second for consistent updates
  if (currentTime - lastSerialUpload >= serialUploadInterval) {
    lastSerialUpload = currentTime;
    sendCurrentStatus();
  }

  // Check if system has started (button pressed)
  if (!systemStarted) {
    if (digitalRead(buttonPin) == LOW) {
      delay(100);
      if (digitalRead(buttonPin) == LOW) {
        systemStarted = true;

        lcd.clear();
        lcd.setCursor(4, 0);
        lcd.print("tetra cycle 2.0");
        digitalWrite(ledPin1, LOW);
        digitalWrite(ledPin2, LOW);
        lastUpdate = currentTime;
        lastLCDUpdate = currentTime;
        startTime = currentTime;
      }
    }
    return;
  }

  if (inElkammar && currentTime - lastUpdate < 10000) {
    return;
  }

  if (inElkammar && currentTime - lastUpdate >= 10000) {
    inElkammar = false;
    lcd.clear();
    digitalWrite(ledPin1, LOW);
    digitalWrite(ledPin2, LOW);
    lastUpdate = currentTime;
    lastLCDUpdate = currentTime;
  }

  if (!inElkammar && !reachedLimit && currentTime - lastUpdate >= updateInterval) {
    unsigned long runTime = currentTime - startTime;
    float elapsedTime = (currentTime - lastUpdate) / 1000.0;

    int currentInterval = -1;
    for (int i = 0; i < 7; i++) {
      if (runTime >= intervalStarts[i] && runTime < intervalStarts[i + 1]) {
        currentInterval = i;
        break;
      }
    }

    if (currentInterval >= 0 && currentInterval < 7) {
      tdsValue -= rates[currentInterval] * elapsedTime;
      if (tdsValue <= tdsLimit) {
        tdsValue = tdsLimit;
        reachedLimit = true;
        finalTime = (currentTime - startTime) / 1000;  
        digitalWrite(ledPin1, LOW); 
        digitalWrite(ledPin2, LOW);
        if (!servoMoved) {
          myServo.write(180);
          servoMoved = true;
        }
      }
    }

    int turbInterval = -1;
    for (int i = 0; i < 5; i++) {
      if (runTime >= turbIntervalStarts[i] && runTime < turbIntervalStarts[i + 1]) {
        turbInterval = i;
        break;
      }
    }
    if (turbInterval >= 0 && turbInterval < 5) {
      turbidityValue -= turbRates[turbInterval] * elapsedTime;
      if (turbidityValue < turbidityLimit) turbidityValue = turbidityLimit;
    }

    int phInterval = -1;
    for (int i = 0; i < 5; i++) {
      if (runTime >= phIntervalStarts[i] && runTime < phIntervalStarts[i + 1]) {
        phInterval = i;
        break;
      }
    }
    if (phInterval >= 0 && phInterval < 5) {
      pHValue -= phRates[phInterval] * elapsedTime;
      if (pHValue < pHLimit) pHValue = pHLimit;
    }

    lastUpdate = currentTime;
  }

  if (!inElkammar && !reachedLimit && currentTime - lastLCDUpdate >= lcdUpdateInterval) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("TDS:");
    lcd.print((int)tdsValue);

    lcd.setCursor(10, 0);
    lcd.print("pH:");
    lcd.print(pHValue, 2);

    lcd.setCursor(0, 1);
    lcd.print("Turb:");
    lcd.print((int)turbidityValue);
    lcd.print(" NTU");

    lastLCDUpdate = currentTime;
  }

  if (reachedLimit && !finalDisplayed) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("TDS: ");
    lcd.print((int)tdsValue);
    lcd.setCursor(0, 1);
    lcd.print("pH: ");
    lcd.print(pHValue, 2);
    lcd.print(" T:");
    lcd.print((int)turbidityValue);
    delay(3000);

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Cycle Time:");
    lcd.setCursor(0, 1);
    lcd.print(finalTime-10);
    lcd.print(" sec");

    finalDisplayed = true;  
  }
}

// Function to send a specific command response
void sendCommandResponse(const char* command_type, int value) {
  Serial.print("{\"");
  Serial.print(command_type);
  Serial.print("\":");
  Serial.print(value);
  
  // For pump commands, include both the specific pump and the full status
  if (strcmp(command_type, "pump1") == 0 || strcmp(command_type, "pump2") == 0) {
    Serial.print(",\"pumps\":[");
    Serial.print(pumpState1 ? 1 : 0);  // Use the state variable
    Serial.print(",");
    Serial.print(pumpState2 ? 1 : 0);  // Use the state variable
    Serial.print("]");
  }
  
  Serial.println("}");
}

// Function to process incoming serial commands
void processSerialCommands() {
  while (Serial.available() > 0) {
    char inChar = (char)Serial.read();
    
    // Add character to buffer with overflow protection
    if (inChar == '\n') {
      cmdComplete = true;
      Serial.print("DEBUG: Received command: ");
      Serial.println(inputBuffer);
    } else {
      // Prevent buffer overflow
      if (inputBuffer.length() < 200) {
        inputBuffer += inChar;
      } else {
        // Buffer overflow, reset and wait for next command
        Serial.println("DEBUG: Command buffer overflow, resetting");
        inputBuffer = "";
      }
    }
  }
  
  // Process command when complete
  if (cmdComplete) {
    // Try to parse as JSON
    StaticJsonDocument<200> doc;
    DeserializationError error = deserializeJson(doc, inputBuffer);
    
    if (!error) {
      Serial.println("DEBUG: JSON parsed successfully");
      bool commandProcessed = false;
      
      // Handle commands for pump1
      if (doc.containsKey("pump1")) {
        int pump1Value = doc["pump1"];
        commandProcessed = true;
        
        // Force to 0 or 1
        pump1Value = pump1Value ? 1 : 0;
        
        // Update state variable first
        pumpState1 = (pump1Value == 1);
        
        // Set the pump state
        digitalWrite(ledPin1, pumpState1 ? HIGH : LOW);
        Serial.print("Pump1 set to: ");
        Serial.println(pumpState1 ? 1 : 0);
        
        // Explicitly report the pump state
        Serial.print("DEBUG: Pump1 state is now: ");
        Serial.println(pumpState1 ? 1 : 0);
        
        // Send a specific command response
        sendCommandResponse("pump1", pumpState1 ? 1 : 0);
      }
      
      // Handle commands for pump2
      if (doc.containsKey("pump2")) {
        int pump2Value = doc["pump2"];
        commandProcessed = true;
        
        // Force to 0 or 1
        pump2Value = pump2Value ? 1 : 0;
        
        // Update state variable first
        pumpState2 = (pump2Value == 1);
        
        // Set the pump state
        digitalWrite(ledPin2, pumpState2 ? HIGH : LOW);
        Serial.print("Pump2 set to: ");
        Serial.println(pumpState2 ? 1 : 0);
        
        // Explicitly report the pump state
        Serial.print("DEBUG: Pump2 state is now: ");
        Serial.println(pumpState2 ? 1 : 0);
        
        // Send a specific command response
        sendCommandResponse("pump2", pumpState2 ? 1 : 0);
      }
      
      // Handle commands for servo
      if (doc.containsKey("servo")) {
        int servoValue = doc["servo"];
        commandProcessed = true;
        
        // Force to 0 or 1
        servoValue = servoValue ? 1 : 0;
        
        // Update state variable first
        servoState = (servoValue == 1);
        
        // Set the servo position based on state
        myServo.write(servoState ? 180 : 0);
        servoMoved = servoState;
        Serial.print("Servo set to: ");
        Serial.println(servoState ? "180" : "0");
        
        // Send a specific command response
        sendCommandResponse("servo", servoState ? 1 : 0);
      }
      
      // Handle system start
      if (doc.containsKey("system")) {
        int systemValue = doc["system"];
        commandProcessed = true;
        
        // Force to 0 or 1
        systemValue = systemValue ? 1 : 0;
        
        Serial.print("DEBUG: System command received: ");
        Serial.println(systemValue);
        
        if (systemValue == 1 && !systemStarted) {
          // Simulate button press to start system
          systemStarted = true;
          lcd.clear();
          lcd.setCursor(4, 0);
          lcd.print("tetra cycle 2.0");
          lastUpdate = millis();
          lastLCDUpdate = lastUpdate;
          startTime = lastUpdate;
          inElkammar = true;
          Serial.println("System started");
        } else if (systemValue == 0 && systemStarted) {
          // Reset the system
          systemStarted = false;
          reachedLimit = false;
          servoMoved = false;
          inElkammar = true;
          finalDisplayed = false;
          tdsValue = 1180.0;
          turbidityValue = 553.0;
          pHValue = 9.5;
          // Do NOT reset pump states when system resets
          // Only update display
          lcd.clear();
          lcd.setCursor(0, 0);
          lcd.print("Have A Better");
          lcd.setCursor(0, 1);
          lcd.print("LIFE With....");
          Serial.println("System reset");
        }
        
        // Send a specific command response
        sendCommandResponse("system", systemStarted ? 1 : 0);
      }
      
      if (commandProcessed) {
        // Send current status back after processing command
        Serial.println("DEBUG: Sending status after command");
        delay(50);  // Short delay to ensure serial output is completed
        sendCurrentStatus();
      } else {
        Serial.println("DEBUG: No recognized commands in JSON");
      }
    } else {
      Serial.print("JSON parsing error: ");
      Serial.println(error.c_str());
      Serial.print("Received: '");
      Serial.print(inputBuffer);
      Serial.println("'");
    }
    
    // Clear buffer and flag
    inputBuffer = "";
    cmdComplete = false;
  }
}

// Send current status as JSON
void sendCurrentStatus() {
  // Only send status if not in the middle of receiving a command
  if (cmdComplete) {
    return; // Don't send status while processing a command
  }
  
  // Create a simplified JSON with just essential information
  // Use a direct approach to avoid potential formatting issues
  Serial.print("{\"ph\":");
  Serial.print(pHValue, 2);
  Serial.print(",\"turbidity\":");
  Serial.print(turbidityValue, 2);
  Serial.print(",\"tds\":");
  Serial.print(tdsValue, 2);
  Serial.print(",\"pumps\":[");
  Serial.print(pumpState1 ? 1 : 0);  // Use the tracked state, not pin state
  Serial.print(",");
  Serial.print(pumpState2 ? 1 : 0);  // Use the tracked state, not pin state
  Serial.print("],\"servo\":");
  Serial.print(servoState ? 1 : 0);  // Use the tracked state, not servo position
  Serial.print(",\"system\":");
  Serial.print(systemStarted ? 1 : 0);
  
  // Include individual pump values for better detection
  Serial.print(",\"pump1\":");
  Serial.print(pumpState1 ? 1 : 0);  // Use the tracked state
  Serial.print(",\"pump2\":");
  Serial.print(pumpState2 ? 1 : 0);  // Use the tracked state
  
  Serial.println("}");
  
  // Add a small delay to prevent serial buffer overflow
  delay(50);
}