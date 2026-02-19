set(DAPHNE_DEPS_MODULE_DIR "${CMAKE_CURRENT_LIST_DIR}")

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

  # Note: CMAKE_CURRENT_LIST_DIR is dynamic and changes inside functions to the
  # caller's list directory; use the module directory captured at include time.
  set(_lock "${DAPHNE_DEPS_MODULE_DIR}/../deps/deps.lock.cmake")
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
  # Some standalone prefixes ship a protoc binary without an embedded RUNPATH,
  # so wrap it with the local lib search path to keep configure/build deterministic.
  if(EXISTS "${_prefix}/bin/protoc")
    set(_protoc_bin "${_prefix}/bin/protoc")
    set(_protoc_lib_dirs "")
    foreach(_lib_dir "${_prefix}/lib" "${_prefix}/lib64")
      if(IS_DIRECTORY "${_lib_dir}")
        list(APPEND _protoc_lib_dirs "${_lib_dir}")
      endif()
    endforeach()

    if(_protoc_lib_dirs)
      string(REPLACE ";" ":" _protoc_lib_path "${_protoc_lib_dirs}")
      file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/_deps")
      set(_protoc_wrapper "${CMAKE_BINARY_DIR}/_deps/daphne-protoc.sh")
      file(WRITE "${_protoc_wrapper}"
        "#!/bin/sh\n"
        "set -eu\n"
        "export LD_LIBRARY_PATH=\"${_protoc_lib_path}\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}\"\n"
        "exec \"${_protoc_bin}\" \"\$@\"\n"
      )
      execute_process(COMMAND chmod +x "${_protoc_wrapper}")
      set(Protobuf_PROTOC_EXECUTABLE "${_protoc_wrapper}" CACHE FILEPATH "" FORCE)
      message(STATUS "Using protoc wrapper: ${_protoc_wrapper}")
    else()
      set(Protobuf_PROTOC_EXECUTABLE "${_protoc_bin}" CACHE FILEPATH "" FORCE)
    endif()
  endif()

  message(STATUS "Using deps tarball: ${_tgz}")
  message(STATUS "Deps prefix: ${_prefix}")
endfunction()
