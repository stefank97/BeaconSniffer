#include <Arduino.h>
#include "oneMeterCalibration.h"

namespace OneMeterCalibration {

    static constexpr const int RSSI_SAMPLE_COUNT = 100;
    int rssiSamplesArray[RSSI_SAMPLE_COUNT];
    size_t rssiSampleIndex = 0;
    bool rssiSamplesReady = false;

    void addRssiSample(int rssi) {
    if (rssiSampleIndex >= RSSI_SAMPLE_COUNT) {
      return;
    }

    rssiSamplesArray[rssiSampleIndex] = rssi;
    rssiSampleIndex++;

    if (rssiSampleIndex == RSSI_SAMPLE_COUNT) {
      rssiSamplesReady = true;
    }
  }

  int calculateMedianRssi() {
    int sortedSamples[RSSI_SAMPLE_COUNT];

    for (size_t i = 0; i < RSSI_SAMPLE_COUNT; i++) {
      sortedSamples[i] = rssiSamplesArray[i];
    }

    for (size_t i = 0; i < RSSI_SAMPLE_COUNT - 1; i++) {
      for (size_t j = i + 1; j < RSSI_SAMPLE_COUNT; j++) {
        if (sortedSamples[j] < sortedSamples[i]) {
          int temp = sortedSamples[i];
          sortedSamples[i] = sortedSamples[j];
          sortedSamples[j] = temp;
        }
      }
    }

    return (sortedSamples[49] + sortedSamples[50]) / 2;
    }

    bool checkRssiSamplesReady(){
        return rssiSamplesReady;
    }

    void reset(){
        rssiSampleIndex = 0;
        rssiSamplesReady = false;
    }
}
