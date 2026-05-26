#ifndef ONE_METER_CALIBRATION_H
#define ONE_METER_CALIBRATION_H

namespace OneMeterCalibration {

    void addRssiSample(int rssi);
    int calculateMedianRssi();
    bool checkRssiSamplesReady();
    void reset();

}

#endif