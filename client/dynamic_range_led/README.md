# LED Dynamic Range Bundle

This bundle contains the per-vgain channel-offset configs derived from the dark scans.

Files:
- `per_channel_closest_offsets_target_2000_combined.csv`: merged per-channel best offset to target 2000 ADC.
- `summary_by_vgain_target_2000_combined.csv`: merged summary by vgain.
- `per_channel_target2k_vgainXXXX.json`: configure_fe_from_output inputs for each vgain.

Headless configure command example from `~/repo/daphne-server`:
```bash
./utils/run_client_via_tunnel.sh daphne-13 client/configure_fe_from_output.py client/dynamic_range_led/per_channel_target2k_vgain2000.json
```

Headless capture command example from `~/repo/daphne-server`:
```bash
./utils/run_client_via_tunnel.sh daphne-13 client/protobuf_acquire_list_channels.py --osc_mode -foldername client/dynamic_range_led/runs/vgain2000_led_sat -channel_list 4,5,6,7,12,13,14,15,18,19,21 -N 64 -L 2048 --timeout_ms 30000
```

Dark-scan summary:

| vgain | selected offsets | avg mean | avg abs error to 2000 | class |
| --- | --- | ---: | ---: | --- |
| 500 | 2150,2200 | 1099.7 | 1259.9 | poor |
| 750 | 2150,2200 | 1744.0 | 827.6 | marginal |
| 1000 | 2100,2150 | 1859.1 | 622.1 | marginal |
| 1250 | 2050,2100 | 2012.3 | 503.0 | marginal |
| 1500 | 2000 | 2098.6 | 341.4 | usable |
| 1750 | 1800,1900 | 2354.2 | 483.1 | usable |
| 2000 | 1700 | 1874.5 | 185.0 | best |
| 2250 | 1400,1500 | 1979.2 | 153.1 | best |
| 2500 | 1000,1100 | 1997.4 | 121.1 | best |
| 2750 | 0 | 2977.2 | 977.2 | marginal |
| 3000 | 200,300 | 4049.9 | 2049.9 | poor |

Practical note:
- `vgain 2750` and `vgain 3000` do not reach a 2000-ADC pedestal target even at the minimum scanned offsets.
- If the LED is strongly saturating, start with `vgain 1500, 1750, 2000, 2250, 2500`.

Generated configs:
- `per_channel_target2k_vgain0500.json`
- `per_channel_target2k_vgain0750.json`
- `per_channel_target2k_vgain1000.json`
- `per_channel_target2k_vgain1250.json`
- `per_channel_target2k_vgain1500.json`
- `per_channel_target2k_vgain1750.json`
- `per_channel_target2k_vgain2000.json`
- `per_channel_target2k_vgain2250.json`
- `per_channel_target2k_vgain2500.json`
- `per_channel_target2k_vgain2750.json`
- `per_channel_target2k_vgain3000.json`
