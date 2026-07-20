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
