add_executable(hdmezz_driver_tests
  hdmezz_driver_tests.cpp
)
target_link_libraries(hdmezz_driver_tests PRIVATE daphne_i2c_hw)
if(MSVC)
  target_compile_options(hdmezz_driver_tests PRIVATE /W4)
else()
  target_compile_options(hdmezz_driver_tests PRIVATE -Wall -Wextra -Wpedantic)
endif()
add_test(NAME hdmezz_driver_unit COMMAND hdmezz_driver_tests)
set_tests_properties(hdmezz_driver_unit PROPERTIES LABELS unit)

add_executable(fpga_reg_dict_tests
  fpga_reg_dict_tests.cpp
  ${CMAKE_CURRENT_SOURCE_DIR}/../srcs/FpgaRegDict.cpp
)
target_include_directories(fpga_reg_dict_tests PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/../srcs
)
if(MSVC)
  target_compile_options(fpga_reg_dict_tests PRIVATE /W4)
else()
  target_compile_options(fpga_reg_dict_tests PRIVATE -Wall -Wextra -Wpedantic)
endif()
add_test(NAME fpga_reg_dict_unit COMMAND fpga_reg_dict_tests)
set_tests_properties(fpga_reg_dict_unit PROPERTIES LABELS unit)

add_executable(spybuffer_readout_inhibit_guard_tests
  spybuffer_readout_inhibit_guard_tests.cpp
)
target_include_directories(spybuffer_readout_inhibit_guard_tests PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/../srcs
)
if(MSVC)
  target_compile_options(spybuffer_readout_inhibit_guard_tests PRIVATE /W4)
else()
  target_compile_options(spybuffer_readout_inhibit_guard_tests PRIVATE
    -Wall -Wextra -Wpedantic
  )
endif()
add_test(
  NAME spybuffer_readout_inhibit_guard_unit
  COMMAND spybuffer_readout_inhibit_guard_tests
)
set_tests_properties(
  spybuffer_readout_inhibit_guard_unit
  PROPERTIES LABELS unit
)

find_package(PythonInterp QUIET)
if(PYTHONINTERP_FOUND)
  add_test(
    NAME spybuffer_ramp_validation_unit
    COMMAND
      ${PYTHON_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/test_spybuffer_ramp_validation.py
  )
  set_tests_properties(
    spybuffer_ramp_validation_unit
    PROPERTIES LABELS unit
  )

  add_test(
    NAME afe_pattern_validation_unit
    COMMAND
      ${PYTHON_EXECUTABLE}
      ${CMAKE_CURRENT_SOURCE_DIR}/test_afe_pattern_validation.py
  )
  set_tests_properties(
    afe_pattern_validation_unit
    PROPERTIES LABELS unit
  )
endif()

if(DAPHNE_ENABLE_HARDWARE_TESTS AND CMAKE_SYSTEM_NAME STREQUAL "Linux")
  add_executable(i2c_hdmezz_smoke
    i2c_hdmezz_smoke.cpp
  )
  target_link_libraries(i2c_hdmezz_smoke PRIVATE daphne_i2c_hw)
  add_test(NAME i2c_hdmezz_smoke
           COMMAND i2c_hdmezz_smoke /dev/i2c-2 0)
  set_tests_properties(i2c_hdmezz_smoke PROPERTIES
    LABELS "hardware;i2c"
    RUN_SERIAL TRUE
  )
endif()
