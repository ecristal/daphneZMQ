<# 
.SYNOPSIS
    Perform a vgain scan with DAPHNE V3 (Windows/PowerShell).

.DESCRIPTION
    Mirrors the original Bash script behavior. Accepts a bracketed vgain list 
    string like "[2200, 2150, 2100]" to resemble the Bash usage.

.EXAMPLE
    .\vgain_scan.ps1 -OutputFolder "C:\path\to\output" -VGainList "[2200, 2150, 2100]" -Channel 24
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [switch] $Help,

    [Parameter(Mandatory=$false)]
    [string] $OutputFolder,

    # Accept the same bracketed string the Bash script used, e.g. "[2200, 2150, 2100]"
    [Parameter(Mandatory=$false)]
    [string] $VGainList,

    [Parameter(Mandatory=$false)]
    [int] $Channel,

    [Parameter(Mandatory=$false)]
    [double] $Bias = 0.0,

    [Parameter(Mandatory=$false)]
    [int] $Trim = 0,

    [Parameter(Mandatory=$false)]
    [double] $BiasControl = 0.0
)

function Show-Help {
    Write-Host "Usage: .\vgain_scan.ps1 -OutputFolder <output_folder> -VGainList <vgain_list> -Channel <channel> [-Bias <bias>] [-Trim <trim>] [-BiasControl <bias_control>] [-Help]"
    Write-Host 'Example: .\vgain_scan.ps1 -OutputFolder "C:\path\to\output" -VGainList "[0, 500, 1000, 1500, 2000]" -Channel 1 -Bias 31.5 -Trim 2000 -BiasControl 55.0'
}

if ($Help) { Show-Help; return }

# Validate required args
if ([string]::IsNullOrWhiteSpace($OutputFolder) -or
    [string]::IsNullOrWhiteSpace($VGainList) -or
    -not $PSBoundParameters.ContainsKey('Channel')) {
    Write-Error "Missing required arguments. Provide -OutputFolder, -VGainList, and -Channel. Use -Help for usage."
    Show-Help
    exit 1
}

# Ensure output folder exists
New-Item -ItemType Directory -Path $OutputFolder -Force | Out-Null

# Convert VGainList string "[a, b, c]" -> array
$vgainArray = $VGainList.Trim()
$vgainArray = $vgainArray -replace '^\[|\]$', ''  # strip brackets
$vgainArray = $vgainArray -split '\s*,\s*'        # split by comma
$vgainArray = $vgainArray | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

# Optional initial configuration (bias/trim). Uncomment to enable.
# Write-Host "Configuring vbias/trim for channel $Channel with bias=$Bias, trim=$Trim, bias_control=$BiasControl"
# & python "..\client\protobuf_configure_vbias_trim.py" `
#     -ip 193.206.157.36 -port 9000 `
#     -channel $Channel -bias $Bias -trim $Trim -bias_control $BiasControl

foreach ($vgain in $vgainArray) {
    Write-Host "Configuring scan with vgain: $vgain"

    $outputFileFolder = Join-Path $OutputFolder ("vgain_{0}" -f $vgain)
    New-Item -ItemType Directory -Path $outputFileFolder -Force | Out-Null

    $outputFile = Join-Path $outputFileFolder ("channel_{0}.dat" -f $Channel)
    $logFile    = Join-Path $outputFileFolder "config.txt"

    # Configure vgain (logs to config.txt)
    & python "..\client\protobuf_configure_vgain.py" `
        -ip 192.168.137.2 -port 9000 `
        -afe 3 -vgain_value $vgain *> $logFile

    Write-Host "Running scan with vgain: $vgain"

    # Acquire data (foldername wants a trailing slash; use backslash on Windows)
    $folderWithSlash = "$outputFileFolder\"
    & python "..\client\protobuf_acquire_channel.py" `
        -ip 192.168.137.2 -port 9000 `
        -channel $Channel `
        -L 2048 -N 30000 `
        -foldername $folderWithSlash `
        -chunk 10 `
        -compress `
        -compression_format 7z `
        -debug
}

Write-Host "Vgain scan completed. All output files are stored in: $OutputFolder"

# Optional cleanup to disable bias/trim. Uncomment if needed.
# Write-Host "Turning off vgain and trim configuration for channel: $Channel"
# & python "..\client\protobuf_configure_vgain_trim.py" `
#     -ip 193.206.157.36 -port 9000 `
#     -channel $Channel -bias 0 -trim 0 -bias_control 0
