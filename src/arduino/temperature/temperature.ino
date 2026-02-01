#include <Wire.h>
#include <WiFiS3.h>
#include <DHT11.h>

// ===================== WIFI 및 서버 설정 =====================
const char* WIFI_SSID = "kdk";
const char* WIFI_PASS = "12345678";

IPAddress SERVER_IP(192, 168, 1, 111);
const uint16_t SERVER_PORT = 5000;

const uint32_t SEND_INTERVAL_MS = 2000; // 2초 간격으로 온습도 전송 (DHT11 권장)
// ============================================================

// ===================== 센서 설정 (DHT11) =====================
DHT11 dht11(2); // DHT11 on Digital Pin 2
// ============================================================

WiFiClient client;

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
  Serial.print("Env device connecting to ");
  Serial.print(SERVER_IP);
  Serial.print(":");
  Serial.println(SERVER_PORT);

  if (client.connect(SERVER_IP, SERVER_PORT)) {
    Serial.println("TCP connected.");
    return true;
  } else {
    Serial.println("TCP connection failed.");
    return false;
  }
}

void stopTCP() {
  if (client.connected()) {
    client.stop();
    Serial.println("TCP disconnected.");
  }
}


void setup() {
  Serial.begin(9600);
  delay(300);

  connectWiFi();
  
  // Auto-connect to server on startup
  if (connectTCPOnce()) {
    Serial.println("Auto-connected to server. Starting continuous ENV streaming...");
  }
}

void loop() {
  // Reconnect if disconnected
  static uint32_t lastReconnectMs = 0;
  if (!client.connected() && millis() - lastReconnectMs > 2000) {
    lastReconnectMs = millis();
    connectTCPOnce();
  }
  if (!client.connected()) {
    delay(100);
    return;
  }

  // Send interval
  uint32_t now = millis();
  static uint32_t lastSendMs = 0;
  if (now - lastSendMs >= SEND_INTERVAL_MS) {
    lastSendMs = now;
    
    int temperature = 0;
    int humidity = 0;
    int result = dht11.readTemperatureHumidity(temperature, humidity);

    if (result == 0) {
      // Send as 'ENV:TEMP,HUMI'
      client.print("ENV:");
      client.print(temperature);
      client.print(",");
      client.println(humidity);
      
      Serial.print("Sent: ENV:");
      Serial.print(temperature);
      Serial.print(",");
      Serial.println(humidity);
    } else {
      Serial.print("DHT11 Error: ");
      Serial.println(DHT11::getErrorString(result));
    }
  }
}
