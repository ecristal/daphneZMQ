#!/bin/bash

# This script is used to perform a vgain scan with DAPHNE V3
# usage: source vgain_scan.sh -output_folder <output_folder> -vgain_list <vgain_list>
# source vgain_scan.sh -h to print help message
# example: source vgain_scan.sh -output_folder /path/to/output -vgain_list [0 , 500, 1000, 1500, 2000]

function print_help() {
    echo "Usage: source vgain_scan.sh -output_folder <output_folder> -vgain_list <vgain_list> -channel <channel> -bias <bias> -trim <trim> -bias_control <bias_control>"
    echo "Example: source vgain_scan.sh -output_folder /path/to/output -vgain_list [0, 500, 1000, 1500, 2000] -channel 1 -bias 31.5 -trim 2000 -bias_control 55.0"
}

while [[ $# -gt 0 ]]; do
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
            channel="$2"
            shift 2
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

if [[ -z "$output_folder" || -z "$vgain_list" || -z "$channel" ]]; then
    echo "Error: Missing required arguments. Please provide -output_folder, -vgain_list, and -channel. Use -h for help."
    print_help
    return 1
fi

# Ensure output folder exists otherwise create it
mkdir -p "$output_folder"

# Convert vgain_list from string to array
vgain_array=($(echo "$vgain_list" | tr -d '[]' | tr ',' ' '))

# Configuring bias and trim values
if [[ -z "$bias" ]]; then
    bias=0.0  # Default value if not provided
fi
if [[ -z "$trim" ]]; then
    trim=0  # Default value if not provided
fi
if [[ -z "$bias_control" ]]; then
    bias_control=0.0  # Default value if not provided
fi
# Configure vgain and trim for the specified channel
#echo "Configuring vbias and trim for channel: $channel with bias: $bias, trim: $trim, bias_control: $bias_control"
# Call the Python script to configure vbias and trim
#python ./../client/protobuf_configure_vbias_trim.py -ip 193.206.157.36 -port 9000 -channel "$channel" -bias "$bias" -trim "$trim" -bias_control "$bias_control"

# Loop through each vgain value and run the scan
for vgain in "${vgain_array[@]}"; do
    echo "Configuring scan with vgain: $vgain"
    # First, configure daphne with current vgain, replace -vgain with actual vgain value
    # now create the filename for the output file
    output_file_folder="${output_folder}/vgain_${vgain}"
    mkdir -p "${output_file_folder}"
    output_file="${output_file_folder}/channel_${channel}.dat"
    # store the output stream in a log file
    log_file="${output_file_folder}/config.txt"
    python ./../client/protobuf_configure_daphne.py -ip 193.206.157.36 -port 9000 -vgain "$vgain" -ch_offset 2275 -align_afes -lpf_cutoff 10 -pga_clamp_level '0 dBFS' -pga_gain_control '24 dB' -lna_gain_control '12 dB' -lna_input_clamp auto &> "$log_file"
    # Run the scan and save the output to the file
    echo "Running scan with vgain: $vgain"
    python ./../client/protobuf_acquire_channel.py -ip 193.206.157.36 -channel "$channel" -L 2048 -N 10000 -filename "$output_file" -software_trigger
    # Compress the output file using 7z with mid compression level
    echo "Compressing output file: $output_file"
    # the output final should not have an extension prefix .dat and delete the original .dat file
    output_file_o="${output_file%.dat}"  # Remove .dat extension for compression
    7z a -mx=2 "${output_file_o}.7z" "$output_file"
    rm "$output_file"
done
echo "Vgain scan completed. All output files are stored in: $output_folder"
#echo "Turning off vgain and trim configuration for channel: $channel"
#python ./../client/protobuf_configure_vgain_trim.py -ip 193.206.157.36 -port 9000 -channel "$channel" -bias 0 -trim 0 -bias_control 0