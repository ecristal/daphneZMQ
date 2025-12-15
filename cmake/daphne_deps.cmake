function(daphne_sha256 file_path out_var)
  if(NOT EXISTS "${file_path}")
    message(FATAL_ERROR "Missing file: ${file_path}")
  endif()
  file(SHA256 "${file_path}" _sum)
  set(${out_var} "${_sum}" PARENT_SCOPE)
endfunction()

function(daphne_extract_tgz tgz_path out_prefix_dir)
  if(NOT EXISTS "${tgz_path}")
    message(FATAL_ERROR "Missing deps tarball: ${tgz_path}")
  endif()

  get_filename_component(_name "${tgz_path}" NAME_WE)
  set(_dest "${CMAKE_BINARY_DIR}/_deps/${_name}")
  set(_stamp "${_dest}/.extracted.stamp")

  if(NOT EXISTS "${_stamp}")
    file(MAKE_DIRECTORY "${_dest}")
    execute_process(
      COMMAND "${CMAKE_COMMAND}" -E tar xzf "${tgz_path}"
      WORKING_DIRECTORY "${_dest}"
      RESULT_VARIABLE _rv
    )
    if(NOT _rv EQUAL 0)
      message(FATAL_ERROR "Failed to extract deps tarball: ${tgz_path}")
    endif()
    file(WRITE "${_stamp}" "ok\n")
  endif()

  # Convention: tarball contains a single top-level folder named "prefix/".
  set(_prefix "${_dest}/prefix")
  if(NOT IS_DIRECTORY "${_prefix}")
    message(FATAL_ERROR "Deps tarball does not contain expected top-level 'prefix/' folder: ${tgz_path}")
  endif()

  set(${out_prefix_dir} "${_prefix}" PARENT_SCOPE)
endfunction()

function(daphne_use_locked_deps)
  set(options)
  set(oneValueArgs TARBALL_DIR)
  set(multiValueArgs)
  cmake_parse_arguments(ARG "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

  if(NOT ARG_TARBALL_DIR)
    message(FATAL_ERROR "daphne_use_locked_deps requires TARBALL_DIR")
  endif()

  set(_lock "${CMAKE_CURRENT_LIST_DIR}/../deps/deps.lock.cmake")
  if(NOT EXISTS "${_lock}")
    message(FATAL_ERROR "Missing deps lock file: ${_lock}")
  endif()
  include("${_lock}")

  if(NOT DEFINED DAPHNE_DEPS_TARBALL_NAME OR NOT DEFINED DAPHNE_DEPS_TARBALL_SHA256)
    message(FATAL_ERROR "deps.lock.cmake must define DAPHNE_DEPS_TARBALL_NAME and DAPHNE_DEPS_TARBALL_SHA256")
  endif()

  set(_tgz "${ARG_TARBALL_DIR}/${DAPHNE_DEPS_TARBALL_NAME}")
  if(NOT EXISTS "${_tgz}")
    message(FATAL_ERROR
      "Expected deps tarball not found:\n"
      "  ${_tgz}\n"
      "Put the tarball in that directory or set -DDAPHNE_DEPS_TARBALL_DIR=..."
    )
  endif()

  daphne_sha256("${_tgz}" _sum)
  if(NOT _sum STREQUAL DAPHNE_DEPS_TARBALL_SHA256)
    message(FATAL_ERROR
      "Deps tarball SHA256 mismatch.\n"
      "Expected: ${DAPHNE_DEPS_TARBALL_SHA256}\n"
      "Actual:   ${_sum}\n"
      "File:     ${_tgz}\n"
      "You likely have the wrong version of the deps tarball."
    )
  endif()

  daphne_extract_tgz("${_tgz}" _prefix)

  # Prefer the extracted prefix for find_package/find_library.
  list(PREPEND CMAKE_PREFIX_PATH "${_prefix}")
  set(CMAKE_PREFIX_PATH "${CMAKE_PREFIX_PATH}" PARENT_SCOPE)

  # Help FindProtobuf in environments where multiple protoc/libprotobuf exist.
  if(EXISTS "${_prefix}/bin/protoc")
    set(Protobuf_PROTOC_EXECUTABLE "${_prefix}/bin/protoc" CACHE FILEPATH "" FORCE)
  endif()

  message(STATUS "Using deps tarball: ${_tgz}")
  message(STATUS "Deps prefix: ${_prefix}")
endfunction()

