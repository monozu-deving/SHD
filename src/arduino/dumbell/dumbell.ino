#include <Wire.h>
#include "I2Cdev.h"
#include "MPU6050_6Axis_MotionApps20.h"
#include <WiFiS3.h>

// ===================== WIFI 설정 =====================
const char* WIFI_SSID = "kdk";
const char* WIFI_PASS = "12345678";

IPAddress SERVER_IP(10, 15, 95, 100);
const uint16_t SERVER_PORT = 5000;

const uint32_t SEND_INTERVAL_MS = 20; // 50Hz
// ====================================================

// ===================== 버튼 설정 =====================
#define BUTTON_PIN 3
// bool sendingEnabled = false; // 제거됨

bool lastButtonReading = HIGH;
bool buttonState = HIGH;
uint32_t lastDebounceTime = 0;
const uint32_t DEBOUNCE_MS = 40;
// ====================================================

// ===================== MPU / DMP 설정 =====================
MPU6050 mpu;

#define INTERRUPT_PIN 2
volatile bool mpuInterrupt = false;
void dmpDataReady() { mpuInterrupt = true; }

bool dmpReady = false;
uint8_t mpuIntStatus;
uint8_t devStatus;
uint16_t packetSize;
uint16_t fifoCount;
uint8_t fifoBuffer[64];

VectorInt16 aa;
VectorInt16 gg;
// ========================================================

WiFiClient client;
uint32_t lastSendMs = 0;

void connectWiFi() {
  Serial.print("WiFi connecting to ");
  Serial.println(WIFI_SSID);

  while (WiFi.begin(WIFI_SSID, WIFI_PASS) != WL_CONNECTED) {
    Serial.print(".");
    delay(500);
  }
  Serial.println("\nWiFi connected.");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
}

bool connectTCPOnce() {
  Serial.print("TCP connecting to ");
  Serial.print(SERVER_IP);
  Serial.print(":");
  Serial.println(SERVER_PORT);

  if (client.connect(SERVER_IP, SERVER_PORT)) {
    Serial.println("TCP connected.");
    return true;
  } else {
    Serial.println("TCP connect failed.");
    return false;
  }
}

void stopTCP() {
  if (client.connected()) {
    client.stop();
    Serial.println("TCP disconnected.");
  }
}

// 버튼 처리(눌렀을 때 세트 상태 토글)
bool setInProgress = false;

void handleButtonToggle() {
  bool reading = digitalRead(BUTTON_PIN);

  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > DEBOUNCE_MS) {
    if (reading != buttonState) {
      buttonState = reading;

      // INPUT_PULLUP: 눌렀을 때 LOW
      if (buttonState == LOW) {
        // 버튼 클릭 시 세트 상태 토글
        setInProgress = !setInProgress;
        Serial.print("Set Toggled (Always Streaming) -> ");
        Serial.println(setInProgress ? "IN PROGRESS" : "STOPPED");
      }
    }
  }

  lastButtonReading = reading;
}

void setup() {
  Serial.begin(115200);
  delay(300);

  // 버튼 (D3 - GND)
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // I2C
  Wire.begin();
  Wire.setClock(400000);

  // WiFi
  connectWiFi();

  // MPU init
  Serial.println("Initializing MPU6050...");
  mpu.initialize();
  pinMode(INTERRUPT_PIN, INPUT);

  Serial.println(mpu.testConnection() ? "MPU6050 OK" : "MPU6050 FAIL");

  Serial.println("Initializing DMP...");
  devStatus = mpu.dmpInitialize();

  mpu.setXGyroOffset(220);
  mpu.setYGyroOffset(76);
  mpu.setZGyroOffset(-85);
  mpu.setZAccelOffset(1788);

  if (devStatus == 0) {
    mpu.setDMPEnabled(true);
    attachInterrupt(digitalPinToInterrupt(INTERRUPT_PIN), dmpDataReady, RISING);
    mpuIntStatus = mpu.getIntStatus();

    dmpReady = true;
    packetSize = mpu.dmpGetFIFOPacketSize();
    Serial.print("DMP ready. packetSize=");
    Serial.println(packetSize);
    Serial.println("Press button on D3 to toggle sending (ON/OFF).");
  } else {
    Serial.print("DMP init failed code=");
    Serial.println(devStatus);
  }
}

void loop() {
  if (!dmpReady) return;

  // 버튼 토글 처리 (세트 상태만 관리)
  handleButtonToggle();

  // 상시 연결 유지 시도 (자동 연결)
  static uint32_t lastReconnectMs = 0;
  if (!client.connected() && millis() - lastReconnectMs > 2000) {
    lastReconnectMs = millis();
    Serial.println("Attempting automatic TCP connection...");
    connectTCPOnce();
  }
  if (!client.connected()) return;

  // 전송 주기 제한 (상시 전송)
  uint32_t now = millis();
  if (now - lastSendMs >= SEND_INTERVAL_MS) {
    lastSendMs = now;

    // DMP 데이터 기다리기
    while (!mpuInterrupt && fifoCount < packetSize) {
      fifoCount = mpu.getFIFOCount();
    }

    mpuInterrupt = false;
    mpuIntStatus = mpu.getIntStatus();
    fifoCount = mpu.getFIFOCount();

    // FIFO overflow 처리
    if ((mpuIntStatus & 0x10) || fifoCount == 1024) {
      mpu.resetFIFO();
      fifoCount = 0;
      return;
    }

    // DMP data ready
    if (mpuIntStatus & 0x02) {
      while (fifoCount < packetSize) fifoCount = mpu.getFIFOCount();

      mpu.getFIFOBytes(fifoBuffer, packetSize);
      fifoCount -= packetSize;

      mpu.dmpGetAccel(&aa, fifoBuffer);
      mpu.dmpGetGyro(&gg, fifoBuffer);

      // CSV 전송
      client.print(aa.x); client.print(",");
      client.print(aa.y); client.print(",");
      client.print(aa.z); client.print(",");
      client.print(gg.x); client.print(",");
      client.print(gg.y); client.print(",");
      client.print(gg.z); client.print(",");
      client.println(setInProgress ? 1 : 0); // 7번째 열: 세트 진행 상태
    }
  }
}

