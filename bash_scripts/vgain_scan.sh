#!/bin/bash

# Sweep DAPHNE V3 AFE bias (outer loop) and VGAIN (inner loop), calibrate the
# channel pedestal at every point, and acquire waveforms.

print_help() {
    cat <<'EOF'
Usage:
  source vgain_scan.sh -output_folder DIR -channel CH [CH ...] -ip IP -port PORT -L SAMPLES -N WAVEFORMS \
      (-vgain_list LIST | -vgain_range RANGE | -range RANGE | -vgain VALUE) \
      (-bias_list LIST | -bias_range RANGE | -bias VALUE) [options]

At least one dimension must be a sweep (a list or range). If only one
dimension is swept, the other one is held fixed. Fixed defaults are bias=0.0
and vgain=1800.

Sweep syntax:
  -vgain_list "[1800, 2000, 2200]"    Explicit VGAIN DAC values
  -vgain_range "[1800, 100, 2200]"   Inclusive [start, step, end]
  -range RANGE                         Backward-compatible VGAIN range alias
  -bias_list "[30.0, 31.0, 32.0]"    Explicit bias values
  -bias_range "[30.0, 0.5, 32.0]"    Inclusive [start, step, end]
  -vgain VALUE                         Fixed VGAIN for a bias-only scan
  -bias VALUE                          Fixed bias for a VGAIN-only scan

Configuration options:
  -trim VALUE              Channel TRIM DAC code (default: 0)
  -bias_control VALUE      Global bias-control value (default: 0.0)
  -set_as_DAC              Interpret bias and bias-control as DAC codes;
                           without it they are interpreted as volts. TRIM and
                           VGAIN are always DAC codes.
  -pedestal VALUE          Target pedestal ADC code (default: 8192)

Acquisition options:
  -trigger_source software|external|timing|all  (default: external)
  -route ROUTE             EnvelopeV2 route (default: mezz/0)
  --timeout-ms MS          Client timeout (default: 30000)
  -multi_channel           Accepted for backward compatibility; channel count
                           is inferred automatically.

Examples:
  # VGAIN-only scan at a fixed bias
  source vgain_scan.sh -output_folder data -vgain_range "[1800,100,2200]" \
      -bias 31.5 -trim 2000 -bias_control 55.0 -channel 16 17 -L 2048 -N 1000 -ip 127.0.0.1 -port 50001

  # Bias-only scan at a fixed VGAIN, with bias values expressed as DAC codes
  source vgain_scan.sh -output_folder data -bias_list "[700,750,800]" \
      -vgain 2000 -set_as_DAC -trim 2000 -bias_control 740 -channel 16 17 -L 2048 -N 1000 -ip 127.0.0.1 -port 50001

  # Nested bias/VGAIN scan
  source vgain_scan.sh -output_folder data -bias_range "[30,0.5,31]" \
      -vgain_list "[1800,2000]" -channel 16 17 -L 2048 -N 1000 -ip 127.0.0.1 -port 50001
EOF
}

fail() {
    echo "ERROR: $*" >&2
    return 1
}

require_value() {
    if [[ $# -lt 2 || -z "$2" ]]; then
        fail "option '$1' requires a value"
        return 1
    fi
}

parse_list() {
    local specification="$1"
    local -n destination="$2"
    local cleaned
    cleaned=$(printf '%s' "$specification" | tr '[],' '   ')
    read -r -a destination <<< "$cleaned"
    if (( ${#destination[@]} == 0 )); then
        fail "empty list: $specification"
        return 1
    fi
}

parse_triplet() {
    local specification="$1"
    local -n start_ref="$2"
    local -n step_ref="$3"
    local -n end_ref="$4"
    local cleaned extra
    cleaned=$(printf '%s' "$specification" | tr '[],' '   ')
    read -r start_ref step_ref end_ref extra <<< "$cleaned"
    if [[ -z "$start_ref" || -z "$step_ref" || -z "$end_ref" || -n "$extra" ]]; then
        fail "range must contain exactly [start, step, end]: $specification"
        return 1
    fi
}

build_integer_range() {
    local specification="$1"
    local -n destination="$2"
    local start step end
    parse_triplet "$specification" start step end || return 1
    if [[ ! "$start" =~ ^[0-9]+$ || ! "$step" =~ ^-?[0-9]+$ || ! "$end" =~ ^[0-9]+$ ]]; then
        fail "VGAIN range values must be integers: $specification"
        return 1
    fi
    if (( step == 0 )); then
        fail "VGAIN range step cannot be zero"
        return 1
    fi
    if (( (end > start && step < 0) || (end < start && step > 0) )); then
        fail "VGAIN range step points away from the end value: $specification"
        return 1
    fi
    destination=()
    local value count=0
    if (( step > 0 )); then
        for ((value = start; value <= end; value += step)); do
            destination+=("$value")
            ((++count > 10000)) && { fail "VGAIN range has more than 10000 points"; return 1; }
        done
    else
        for ((value = start; value >= end; value += step)); do
            destination+=("$value")
            ((++count > 10000)) && { fail "VGAIN range has more than 10000 points"; return 1; }
        done
    fi
}

build_decimal_range() {
    local specification="$1"
    local -n destination="$2"
    local start step end
    parse_triplet "$specification" start step end || return 1
    local generated
    if ! generated=$(awk -v start="$start" -v step="$step" -v end="$end" '
        BEGIN {
            number = "^[-+]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][-+]?[0-9]+)?$"
            if (start !~ number || step !~ number || end !~ number) exit 2
            start += 0; step += 0; end += 0
            if (step == 0) exit 3
            if ((end > start && step < 0) || (end < start && step > 0)) exit 4
            tolerance = (step < 0 ? -step : step) * 1e-9 + 1e-12
            count = 0
            if (step > 0) {
                for (value = start; value <= end + tolerance; value += step) {
                    printf "%.12g\n", value
                    if (++count > 10000) exit 5
                }
            } else {
                for (value = start; value >= end - tolerance; value += step) {
                    printf "%.12g\n", value
                    if (++count > 10000) exit 5
                }
            }
        }
    '); then
        fail "invalid bias range (use numeric [start, step, end] with a nonzero step directed toward end): $specification"
        return 1
    fi
    mapfile -t destination <<< "$generated"
}

validate_dac() {
    local value="$1" label="$2"
    if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < 0 || value > 4095 )); then
        fail "$label must be an integer DAC code in 0..4095 (got '$value')"
        return 1
    fi
}

validate_positive_integer() {
    local value="$1" label="$2"
    if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value <= 0 )); then
        fail "$label must be a positive integer (got '$value')"
        return 1
    fi
}

run_logged() {
    local log_file="$1" label="$2"
    shift 2
    {
        echo
        echo "===== $label ====="
        printf 'command:'
        printf ' %q' "$@"
        echo
    } >> "$log_file"
    if ! "$@" >> "$log_file" 2>&1; then
        echo "ERROR: $label failed; see $log_file" >&2
        return 1
    fi
}

scan_main() {
    local output_folder="" vgain_list="" vgain_range="" fixed_vgain=""
    local bias_list="" bias_range="" fixed_bias=""
    local trim="0" bias_control="0" ip_addr="" port="" N="" L=""
    local trigger_source_arg="" route="mezz/0" timeout_ms="30000"
    local pedestal="8192" set_as_dac=false legacy_software_trigger=false
    local python_bin="${DAPHNE_PYTHON:-python3}"
    local script_dir client_dir
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    client_dir="${script_dir}/../client"
    local -a channel_list=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -output_folder|--output-folder)
                require_value "$@" || return 1; output_folder="$2"; shift 2 ;;
            -vgain_list|--vgain-list)
                require_value "$@" || return 1; vgain_list="$2"; shift 2 ;;
            -vgain_range|--vgain-range|-range)
                require_value "$@" || return 1; vgain_range="$2"; shift 2 ;;
            -vgain|--vgain)
                require_value "$@" || return 1; fixed_vgain="$2"; shift 2 ;;
            -bias_list|--bias-list|-vbias_list|--vbias-list)
                require_value "$@" || return 1; bias_list="$2"; shift 2 ;;
            -bias_range|--bias-range|-vbias_range|--vbias-range)
                require_value "$@" || return 1; bias_range="$2"; shift 2 ;;
            -bias|--bias|-vbias|--vbias)
                require_value "$@" || return 1; fixed_bias="$2"; shift 2 ;;
            -channel|--channel)
                shift
                while [[ $# -gt 0 && "$1" != -* ]]; do
                    channel_list+=("$1")
                    shift
                done
                if (( ${#channel_list[@]} == 0 )); then
                    fail "-channel needs at least one channel number"
                    return 1
                fi
                ;;
            -trim|--trim)
                require_value "$@" || return 1; trim="$2"; shift 2 ;;
            -bias_control|--bias-control)
                require_value "$@" || return 1; bias_control="$2"; shift 2 ;;
            -set_as_DAC|--set-as-dac)
                set_as_dac=true; shift ;;
            -pedestal|--pedestal|-target_pedestal|--target-pedestal)
                require_value "$@" || return 1; pedestal="$2"; shift 2 ;;
            -ip|--ip)
                require_value "$@" || return 1; ip_addr="$2"; shift 2 ;;
            -port|--port)
                require_value "$@" || return 1; port="$2"; shift 2 ;;
            -N)
                require_value "$@" || return 1; N="$2"; shift 2 ;;
            -L)
                require_value "$@" || return 1; L="$2"; shift 2 ;;
            -trigger_source|--trigger-source)
                require_value "$@" || return 1; trigger_source_arg="$2"; shift 2 ;;
            -software_trigger|--software-trigger)
                legacy_software_trigger=true; shift ;;
            -route|--route|-r)
                require_value "$@" || return 1; route="$2"; shift 2 ;;
            --timeout-ms|--timeout_ms)
                require_value "$@" || return 1; timeout_ms="$2"; shift 2 ;;
            -multi_channel|--multi-channel)
                echo "WARNING: -multi_channel is no longer needed; selected channels are handled automatically." >&2
                shift ;;
            -h|--help)
                print_help; return 0 ;;
            *)
                fail "unknown option: $1"
                print_help
                return 1 ;;
        esac
    done

    if [[ -z "$output_folder" || -z "$ip_addr" || -z "$port" || -z "$N" || -z "$L" || ${#channel_list[@]} -eq 0 ]]; then
        fail "missing required arguments: output folder, channel(s), IP, port, N and L are required"
        print_help
        return 1
    fi
    validate_positive_integer "$port" "port" || return 1
    validate_positive_integer "$N" "N" || return 1
    validate_positive_integer "$L" "L" || return 1
    validate_positive_integer "$timeout_ms" "timeout" || return 1
    validate_dac "$trim" "trim" || return 1
    if [[ ! "$pedestal" =~ ^[0-9]+$ ]] || (( pedestal < 0 || pedestal > 16383 )); then
        fail "pedestal must be an integer ADC code in 0..16383 (got '$pedestal')"
        return 1
    fi

    local channel afe=-1 channel_afe
    local -A seen_channels=()
    for channel in "${channel_list[@]}"; do
        if [[ ! "$channel" =~ ^[0-9]+$ ]] || (( channel < 0 || channel > 39 )); then
            fail "channel must be an integer in 0..39 (got '$channel')"
            return 1
        fi
        if [[ -n "${seen_channels[$channel]:-}" ]]; then
            fail "channel $channel was specified more than once"
            return 1
        fi
        seen_channels[$channel]=1
        channel_afe=$((channel / 8))
        if (( afe < 0 )); then
            afe=$channel_afe
        elif (( channel_afe != afe )); then
            fail "all channels must belong to one AFE because bias and VGAIN are AFE-wide; channel ${channel_list[0]} is in AFE $afe but channel $channel is in AFE $channel_afe"
            return 1
        fi
    done

    if [[ "$legacy_software_trigger" == true ]]; then
        if [[ -n "$trigger_source_arg" && "$trigger_source_arg" != "software" ]]; then
            fail "-software_trigger conflicts with -trigger_source $trigger_source_arg"
            return 1
        fi
        echo "WARNING: -software_trigger is deprecated; use -trigger_source software" >&2
        trigger_source_arg="software"
    fi
    local trigger_source="${trigger_source_arg:-external}"
    case "$trigger_source" in
        software|external|timing|all) ;;
        *) fail "invalid trigger source '$trigger_source' (expected software, external, timing, or all)"; return 1 ;;
    esac

    local vgain_selectors=0 bias_selectors=0
    [[ -n "$vgain_list" ]] && ((++vgain_selectors))
    [[ -n "$vgain_range" ]] && ((++vgain_selectors))
    [[ -n "$fixed_vgain" ]] && ((++vgain_selectors))
    [[ -n "$bias_list" ]] && ((++bias_selectors))
    [[ -n "$bias_range" ]] && ((++bias_selectors))
    [[ -n "$fixed_bias" ]] && ((++bias_selectors))
    if (( vgain_selectors > 1 )); then
        fail "choose only one of -vgain_list, -vgain_range/-range, or -vgain"
        return 1
    fi
    if (( bias_selectors > 1 )); then
        fail "choose only one of -bias_list, -bias_range, or -bias"
        return 1
    fi
    if [[ -z "$vgain_list" && -z "$vgain_range" && -z "$bias_list" && -z "$bias_range" ]]; then
        fail "at least one scan is required: use a VGAIN or bias list/range"
        return 1
    fi

    local -a vgain_array bias_array
    local vgain_mode bias_mode
    if [[ -n "$vgain_list" ]]; then
        parse_list "$vgain_list" vgain_array || return 1
        vgain_mode="scan-list"
    elif [[ -n "$vgain_range" ]]; then
        build_integer_range "$vgain_range" vgain_array || return 1
        vgain_mode="scan-range"
    else
        vgain_array=("${fixed_vgain:-1800}")
        vgain_mode="fixed"
    fi
    if [[ -n "$bias_list" ]]; then
        parse_list "$bias_list" bias_array || return 1
        bias_mode="scan-list"
    elif [[ -n "$bias_range" ]]; then
        build_decimal_range "$bias_range" bias_array || return 1
        bias_mode="scan-range"
    else
        if [[ "$set_as_dac" == true ]]; then
            bias_array=("${fixed_bias:-0}")
        else
            bias_array=("${fixed_bias:-0.0}")
        fi
        bias_mode="fixed"
    fi

    local vgain bias
    for vgain in "${vgain_array[@]}"; do
        validate_dac "$vgain" "VGAIN" || return 1
    done
    if [[ "$set_as_dac" == true ]]; then
        validate_dac "$bias_control" "bias control" || return 1
        for bias in "${bias_array[@]}"; do
            validate_dac "$bias" "bias" || return 1
        done
    else
        local number_regex='^[-+]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][-+]?[0-9]+)?$'
        if [[ ! "$bias_control" =~ $number_regex ]]; then
            fail "bias control must be numeric (got '$bias_control')"
            return 1
        fi
        for bias in "${bias_array[@]}"; do
            if [[ ! "$bias" =~ $number_regex ]]; then
                fail "bias must be numeric (got '$bias')"
                return 1
            fi
        done
    fi

    mkdir -p "$output_folder" || { fail "could not create output folder '$output_folder'"; return 1; }
    local units="volts"
    [[ "$set_as_dac" == true ]] && units="DAC"
    echo "Channels: ${channel_list[*]} (AFE $afe)"
    echo "Bias points ($bias_mode, $units): ${bias_array[*]}"
    echo "VGAIN points ($vgain_mode, DAC): ${vgain_array[*]}"

    local bias_folder bias_log bias_readback
    local -a common_connection_args bias_args read_bias_args vgain_args pedestal_args read_all_args
    common_connection_args=(-ip "$ip_addr" -port "$port" -route "$route" --timeout-ms "$timeout_ms")

    for bias in "${bias_array[@]}"; do
        bias_folder="${output_folder}/vbias_${bias}"
        mkdir -p "$bias_folder" || { fail "could not create '$bias_folder'"; return 1; }
        bias_log="${bias_folder}/vbias_config.txt"
        : > "$bias_log"
        echo "Configuring AFE $afe bias=$bias $units and TRIM=$trim DAC for channels ${channel_list[*]}"

        for channel in "${channel_list[@]}"; do
            bias_args=("${common_connection_args[@]}" -channel "$channel" -bias "$bias" -trim "$trim" -bias_control "$bias_control")
            [[ "$set_as_dac" == true ]] && bias_args+=(--set-as-dac)
            run_logged "$bias_log" "configure bias/trim for channel $channel" \
                "$python_bin" "$client_dir/protobuf_configure_vbias_trim.py" "${bias_args[@]}" || return 1
        done

        read_bias_args=("${common_connection_args[@]}" -channel "${channel_list[@]}" -afe "$afe" --trim --bias --bias-control --compact)
        if ! bias_readback=$("$python_bin" "$client_dir/protobuf_read_configuration.py" "${read_bias_args[@]}" 2>&1); then
            {
                echo
                echo "===== verify bias/trim ====="
                echo "$bias_readback"
            } >> "$bias_log"
            fail "bias/TRIM verification failed for bias $bias; see $bias_log"
            return 1
        fi
        {
            echo
            echo "===== verified bias/trim readback ====="
            echo "$bias_readback"
        } >> "$bias_log"

        for vgain in "${vgain_array[@]}"; do
            local point_folder config_file final_readback
            point_folder="${bias_folder}/vgain_${vgain}"
            mkdir -p "$point_folder" || { fail "could not create '$point_folder'"; return 1; }
            config_file="${point_folder}/config.txt"
            {
                echo "scan_configuration"
                echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
                echo "channels=${channel_list[*]}"
                echo "afe=$afe"
                echo "number_of_waveforms=$N"
                echo "waveform_length=$L"
                echo "bias_requested=$bias"
                echo "bias_units=$units"
                echo "bias_control_requested=$bias_control"
                echo "trim_requested=$trim"
                echo "trim_units=DAC"
                echo "vgain_requested=$vgain"
                echo "vgain_units=DAC"
                echo "pedestal_target=$pedestal"
                echo "pedestal_method=regula_falsi"
                echo "pedestal_initial_offset=current"
                echo "trigger_source=$trigger_source"
                echo "route=$route"
                echo "bias_mode=$bias_mode"
                echo "vgain_mode=$vgain_mode"
                echo
                echo "===== verified bias/trim readback ====="
                echo "$bias_readback"
            } > "$config_file"

            echo "Configuring point bias=$bias $units, VGAIN=$vgain DAC"
            vgain_args=("${common_connection_args[@]}" -afe "$afe" -vgain_value "$vgain")
            run_logged "$config_file" "configure VGAIN" \
                "$python_bin" "$client_dir/protobuf_configure_vgain.py" "${vgain_args[@]}" || return 1

            pedestal_args=("${common_connection_args[@]}" -channel "${channel_list[@]}" --use-current-offset -target_pedestal "$pedestal" -method regula_falsi -L "$L")
            run_logged "$config_file" "configure pedestal OFFSETs" \
                "$python_bin" "$client_dir/protobuf_configure_pedestal_level.py" "${pedestal_args[@]}" || return 1

            read_all_args=("${common_connection_args[@]}" -channel "${channel_list[@]}" -afe "$afe" --offset --trim --bias --vgain --bias-control --compact)
            if ! final_readback=$("$python_bin" "$client_dir/protobuf_read_configuration.py" "${read_all_args[@]}" 2>&1); then
                {
                    echo
                    echo "===== final configuration verification ====="
                    echo "$final_readback"
                } >> "$config_file"
                fail "final configuration verification failed for bias $bias, VGAIN $vgain; see $config_file"
                return 1
            fi
            {
                echo
                echo "===== verified final hardware configuration ====="
                echo "$final_readback"
            } >> "$config_file"

            if ! "$python_bin" "$client_dir/protobuf_acquire_list_channels.py" \
                -ip "$ip_addr" \
                -port "$port" \
                -route "$route" \
                --timeout_ms "$timeout_ms" \
                -foldername "$point_folder" \
                -channel_list "${channel_list[@]}" \
                -L "$L" \
                -N "$N" \
                -chunk 10 \
                -debug \
                -compression_format 7z \
                -trigger_source "$trigger_source"; then
                fail "acquisition failed for bias $bias, VGAIN $vgain"
                return 1
            fi
        done
    done

    echo "Bias/VGAIN scan completed. All output files are stored in: $output_folder"
}

scan_main "$@"
scan_status=$?
return "$scan_status" 2>/dev/null || exit "$scan_status"
