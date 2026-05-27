#include <Arduino.h>
#include "oneMeterCalibration.h"

namespace OneMeterCalibration {

    static constexpr const int RSSI_SAMPLE_MAX = 100;
    int RssiSampleSize = 100; 
    int rssiSamplesArray[RSSI_SAMPLE_MAX];
    size_t rssiSampleIndex = 0;
    bool rssiSamplesReady = false;

    void addRssiSample(int rssi) {
    if (rssiSampleIndex >= RssiSampleSize) {
      return;
    }

    rssiSamplesArray[rssiSampleIndex] = rssi;
    rssiSampleIndex++;

    if (rssiSampleIndex >= RssiSampleSize) {
      rssiSamplesReady = true;
    }
  }

  int calculateMedianRssi() {
    int sortedSamples[RssiSampleSize];

    for (size_t i = 0; i < RssiSampleSize; i++) {
      sortedSamples[i] = rssiSamplesArray[i];
    }

    for (size_t i = 0; i < RssiSampleSize - 1; i++) {
      for (size_t j = i + 1; j < RssiSampleSize; j++) {
        if (sortedSamples[j] < sortedSamples[i]) {
          int temp = sortedSamples[i];
          sortedSamples[i] = sortedSamples[j];
          sortedSamples[j] = temp;
        }
      }
    }

    if (RssiSampleSize % 2 == 0) {
      return (sortedSamples[(RssiSampleSize / 2) - 1] + sortedSamples[RssiSampleSize / 2]) / 2;
    }

    return sortedSamples[RssiSampleSize / 2];    
  }

  bool checkRssiSamplesReady(){
    return rssiSamplesReady;
  }

  void reset(){
    rssiSampleIndex = 0;
    rssiSamplesReady = false;
  }

  void setRssiSampleSize(uint8_t size){
    if(size > RSSI_SAMPLE_MAX){
      Serial.printf("RssiSampleSize max %d.", RSSI_SAMPLE_MAX);
      return;
    }

    RssiSampleSize = size;
  }
}
