#include "server_controller/monitoring.hpp"

#include <chrono>
#include <iostream>
#include <thread>

#include "Daphne.hpp"

namespace daphne_sc {
namespace {

void i2c_2_monitor_thread(Daphne& daphne, std::chrono::milliseconds period) {
  while (true) {
    try {
      if (!daphne.isI2C_2_device_configuring.load()) {
        auto* hd = daphne.getHDMezzDriver();
        if (hd) {
          for(size_t i = 0; i < 5; i++){
            if(hd->isAfeBlockEnabled(i)){
              daphne.HDMezz_5V_voltage[i].store(hd->readRailVoltage5V(i));
              daphne.HDMezz_5V_current[i].store(hd->readRailCurrent5V(i));
              daphne.HDMezz_3V3_voltage[i].store(hd->readRailVoltage3V3(i));
              daphne.HDMezz_3V3_current[i].store(hd->readRailCurrent3V3(i));
              daphne.HDMezz_5V_power[i].store(hd->readRailPower5V(i));
              daphne.HDMezz_3V3_power[i].store(hd->readRailPower3V3(i));
            }
          }
        }
      }
    } catch (const std::exception& e) {
      std::cerr << "I2C_2 monitor error: " << e.what() << std::endl;
    }

    std::this_thread::sleep_for(period);
  }
}

void i2c_1_monitor_thread(Daphne& daphne, std::chrono::milliseconds period) {
  bool warned_missing_adc = false;
  while (true) {
    try {
      if (!daphne.isI2C_1_device_configuring.load() && !daphne.user_vbias_voltage_request.load()) {
        auto* adc0x10 = daphne.getADS7138_Driver_addr_0x10();
        auto* adc0x17 = daphne.getADS7138_Driver_addr_0x17();
        if (!adc0x10 || !adc0x17) {
          if (!warned_missing_adc) {
            std::cerr << "ADS7138 drivers not available; skipping I2C_1 monitor." << std::endl;
            warned_missing_adc = true;
          }
          std::this_thread::sleep_for(std::chrono::seconds(1));
          continue;
        }

        daphne.is_vbias_voltage_monitor_reading.store(true);
        std::vector<double> adc_values_0x10 = adc0x10->readData(7);
        std::vector<double> adc_values_0x17 = adc0x17->readData(3);
        daphne.is_vbias_voltage_monitor_reading.store(false);

        if (adc_values_0x10.size() >= 7) {
          daphne._3V3PDS_voltage.store(adc_values_0x10[0] * 2.0);
          daphne._1V8PDS_voltage.store(adc_values_0x10[1] * 2.0);
          daphne._VBIAS_0_voltage.store(adc_values_0x10[2] * 39.314);
          daphne._VBIAS_1_voltage.store(adc_values_0x10[3] * 39.314);
          daphne._VBIAS_2_voltage.store(adc_values_0x10[4] * 39.314);
          daphne._VBIAS_3_voltage.store(adc_values_0x10[5] * 39.314);
          daphne._VBIAS_4_voltage.store(adc_values_0x10[6] * 39.314);
        }

        if (adc_values_0x17.size() >= 3) {
          daphne._1V8A_voltage.store(adc_values_0x17[0] * 2.0);
          daphne._3V3A_voltage.store(adc_values_0x17[1] * 2.0);
          daphne._n5VA_voltage.store(adc_values_0x17[2] * (-2.0));
        }
      }
    } catch (const std::exception& e) {
      daphne.is_vbias_voltage_monitor_reading.store(false);
      std::cerr << "I2C_1 monitor error: " << e.what() << std::endl;
    }

    std::this_thread::sleep_for(period);
  }
}

}  // namespace

std::vector<std::thread> start_monitoring(Daphne& daphne, const MonitoringOptions& options) {
  std::vector<std::thread> threads;
  threads.emplace_back(i2c_1_monitor_thread, std::ref(daphne), options.period);
  threads.emplace_back(i2c_2_monitor_thread, std::ref(daphne), options.period);
  return threads;
}

}  // namespace daphne_sc

