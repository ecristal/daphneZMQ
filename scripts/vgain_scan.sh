#!/bin/bash

# This script is used to perform a vgain scan with DAPHNE V3
# usage: source vgain_scan.sh -output_folder <output_folder> -vgain_list <vgain_list>
#        or: source vgain_scan.sh -output_folder <output_folder> -range "[init, step, end]"
# example: source vgain_scan.sh -output_folder /path/to/output -vgain_list [0 , 500, 1000, 1500, 2000]
#          source vgain_scan.sh -output_folder /path/to/output -range "[3000, -100, 2800]" -channel 16 17 18 19

function print_help() {
    echo "Usage: source vgain_scan.sh -output_folder <output_folder> -vgain_list <vgain_list> | -range \"[init, step, end]\""
    echo "                               -channel <ch0> [ch1 ch2 ...] -bias <bias> -trim <trim> -bias_control <bias_control>"
    echo "                               -ip <ip_addr> -port <port> -L <L> -N <N> [-software_trigger] [-multi_channel]"
    echo
    echo "Examples:"
    echo "  source vgain_scan.sh -output_folder /path/to/output -vgain_list [0, 500, 1000, 1500, 2000] -channel 1 -bias 31.5 -trim 2000 -bias_control 55.0"
    echo "  source vgain_scan.sh -output_folder /path/to/output -range \"[3000, -100, 2800]\" -channel 16 17 18 19 -L 2048 -N 30000 -ip 127.0.0.1 -port 50001 -software_trigger -multi_channel"
}

SW_trigger=false
multi_channel=false
channel_list=()

while [[ $# > 0 ]]; do
    case $1 in
        -output_folder)
            output_folder="$2"
            shift 2
            ;;
        -vgain_list)
            vgain_list="$2"
            shift 2
            ;;
        -channel)
            # consume "-channel"
            shift
            # collect all subsequent non-option arguments as channels
            while [[ $# -gt 0 && "$1" != -* ]]; do
                channel_list+=("$1")
                shift
            done

            if [[ ${#channel_list[@]} -eq 0 ]]; then
                echo "ERROR: -channel needs at least one channel number"
                print_help
                return 1
            fi

            # use the first channel as reference (for AFE computation etc.)
            channel="${channel_list[0]}"

            # if more than one channel is given, assume multi-channel mode
            if (( ${#channel_list[@]} > 1 )); then
                multi_channel=true
            fi
            ;;
        -bias)
            bias="$2"
            shift 2
            ;;
        -trim)
            trim="$2"
            shift 2
            ;;
        -bias_control)
            bias_control="$2"
            shift 2
            ;;
        -ip)
            ip_addr="$2"
            shift 2
            ;;
        -port)
            port="$2"
            shift 2
            ;;
        -N)
            N="$2"
            shift 2
            ;;
        -L)
            L="$2"
            shift 2
            ;;
        -range)
            range="$2"
            shift 2
            ;;
        -software_trigger)
            SW_trigger=true
            shift
            ;;
        -multi_channel)
            multi_channel=true
            shift
            ;;
        -h|--help)
            print_help
            return 0
            ;;
        *)
            echo "Unknown option: $1"
            print_help
            return 1
            ;;
    esac
done

if [[ -z "$output_folder" || -z "$channel" || -z "$port" || -z "$ip_addr" || -z "$N" || -z "$L" ]]; then
    echo "Error: Missing required arguments. Use -h for help."
    print_help
    return 1
fi

# Ensure output folder exists otherwise create it
mkdir -p "$output_folder"

# ----------------------------------------------------------
# VGAIN LIST / RANGE HANDLING
# ----------------------------------------------------------
if [[ -n "$vgain_list" && -n "$range" ]]; then
    echo "ERROR: You cannot use both -vgain_list AND -range."
    return 1
elif [[ -n "$vgain_list" ]]; then
    echo "Using explicit vgain_list: $vgain_list"

    cleaned=$(echo "$vgain_list" | tr -d '[],')

    read -a vgain_array <<< "$cleaned"

elif [[ -n "$range" ]]; then
    echo "Using range: $range"

    cleaned=$(echo "$range" | tr -d '[],')

    read init step end <<< "$cleaned"

    # ------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------

    # Check init and end limits
    if (( init < 0 || init > 4000 )); then
        echo "ERROR: init value ($init) must be between 0 and 4000"
        return 1
    fi

    if (( end < 0 || end > 4000 )); then
        echo "ERROR: end value ($end) must be between 0 and 4000"
        return 1
    fi

    # Step cannot be zero
    if (( step == 0 )); then
        echo "ERROR: step cannot be zero"
        return 1
    fi

    # Step magnitude cannot exceed the difference
    diff=$(( end - init ))
    abs_diff=${diff#-}        # absolute value

    abs_step=${step#-}        # absolute value
    if (( abs_step > abs_diff )); then
        echo "ERROR: |step| ($abs_step) cannot be greater than |end-init| ($abs_diff)"
        return 1
    fi

    # ------------------------------------------------------
    # BUILD vgain_array
    # ------------------------------------------------------
    vgain_array=()

    if (( step > 0 )); then
        # Ascending
        for ((v = init; v <= end; v += step)); do
            vgain_array+=("$v")
        done
    else
        # Descending
        for ((v = init; v >= end; v += step)); do
            vgain_array+=("$v")
        done
    fi

    echo "Generated vgain_array: ${vgain_array[*]}"

else
    echo "ERROR: You must specify either -vgain_list or -range."
    return 1
fi

# ----------------------------------------------------------
# BIAS / TRIM DEFAULTS
# ----------------------------------------------------------
if [[ -z "$bias" ]]; then
    bias=0.0  # Default value if not provided
fi
if [[ -z "$trim" ]]; then
    trim=0  # Default value if not provided
fi
if [[ -z "$bias_control" ]]; then
    bias_control=0.0  # Default value if not provided
fi

# AFE from reference channel
AFE=$(( channel / 8 ))

if [[ "$SW_trigger" == true ]]; then
    software_trigger_flag="-software_trigger"
else
    software_trigger_flag=""
fi

# ----------------------------------------------------------
# MAIN LOOP OVER VGAIN
# ----------------------------------------------------------
for vgain in "${vgain_array[@]}"; do
    echo "Configuring scan with vgain: $vgain"

    # create folder for this vgain
    output_file_folder="${output_folder}/vgain_${vgain}"
    mkdir -p "${output_file_folder}"
    output_file="${output_file_folder}/channel_${channel}.dat"
    log_file="${output_file_folder}/config.txt"

    # Configure vgain (AFE from first channel)
    #python ./../client/protobuf_configure_vgain.py \
    #    -ip "${ip_addr}" \
    #    -port "$port" \
    #    -afe "$AFE" \
    #    -vgain_value "$vgain" &> "$log_file"

    echo "Running scan with vgain: $vgain"

    if [[ "$multi_channel" == false ]]; then
        # Single-channel acquisition
	# Configure vgain (AFE from first channel)
        # python ./../client/protobuf_configure_vgain.py \
        #     -ip "${ip_addr}" \
        #     -port "$port" \
        #     -afe "$AFE" \
        #     -vgain_value "$vgain" &> "$log_file"


        # python ./../client/protobuf_acquire_channel.py \
        #     -ip "${ip_addr}" \
        #     -port "$port" \
        #     -channel "$channel" \
        #     -L "$L" \
        #     -N "$N" \
        #     -foldername "${output_file_folder}/" \
        #     -chunk 10 \
        #     -compression_format 7z \
        #     -debug \
        #     $software_trigger_flag
    else
        # Multi-channel acquisition: pass the full list
        # Configure vgain (AFE from first channel)
    	#python ./../client/protobuf_configure_vgain.py \
        #-ip "${ip_addr}" \
        #-port "$port" \
	    #-afe "$AFE" \
        #-configure_all \
        #-vgain_value "$vgain" &> "$log_file"
        python3 ./../configure_fe_min_v2.py \
            -ip "${ip_addr}" \
            -port "$port" \
            -vgain "$vgain" \
            -ch_offset 2275 \
            -lpf_cutoff 10 \
            -pga_clamp_level '0 dBFS' \
            -pga_gain_control '24 dB' \
            -lna_gain_control '12 dB' \
            -lna_input_clamp auto  \
            --full \
            -align_afes \
            --adc_resolution 0 &> "$log_file"

        python3 ./../client/protobuf_acquire_list_channels.py \
            -ip "${ip_addr}" \
            -port "$port" \
            -foldername "${output_file_folder}" \
            -channel_list "${channel_list[@]}" \
            -L "$L" \
            -N "$N" \
            $software_trigger_flag
    fi
done

echo "Vgain scan completed. All output files are stored in: $output_folder"

# restore vgain to default (example: 1800) for the reference AFE
AFE=$(( channel / 8 ))
python3 ./../configure_fe_min_v2.py \
    -ip "${ip_addr}" \
    -port "$port" \
    -vgain 1800 \
    -ch_offset 2275 \
    -lpf_cutoff 10 \
    -pga_clamp_level '0 dBFS' \
    -pga_gain_control '24 dB' \
    -lna_gain_control '12 dB' \
    -lna_input_clamp auto  \
    --full \
    -align_afes \
    --adc_resolution 0 &> "$log_file"

