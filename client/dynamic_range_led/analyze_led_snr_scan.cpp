#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace fs = std::filesystem;

struct Options {
  fs::path run_dir;
  std::vector<fs::path> supplement_run_dirs;
  fs::path output_dir;
  std::vector<int> channels;
  int waveform_len = 0;
  int reference_intensity = 0;
  int search_start = 96;
  int search_stop = 220;
  int baseline_margin = 12;
  int baseline_len = 100;
  int pre_samples = 4;
  int post_samples = 12;
  int max_integration_len = 40;
  double threshold_frac = 0.10;
  double pre_pulse_reject_sigma = 5.0;
  double target_zero_fraction = 0.50;
  double min_peak_separation = 1.5;
  int hist_bins = 240;
  int max_plot_peaks = 6;
  int peak_window_pre = -1;
  int peak_window_post = -1;
  int post_peak_offset = 8;
  double pre_activity_frac = -1.0;
  double pre_activity_floor = -1.0;
  double post_activity_frac = -1.0;
  double post_activity_floor = -1.0;
};

struct ChannelWindow {
  int channel = 0;
  int reference_intensity = 0;
  int baseline_start = 0;
  int baseline_stop = 0;
  int onset_index = 0;
  int peak_index = 0;
  int integrate_start = 0;
  int integrate_stop = 0;
};

struct ChargeStats {
  std::vector<double> signal_charges;
  std::vector<double> pedestal_charges;
  double sample_sigma = 0.0;
  double pedestal_sigma = 0.0;
  double pedestal_center_before_shift = 0.0;
  std::size_t n_waveforms = 0;
  std::size_t n_clean_waveforms = 0;
  std::size_t n_rejected_baseline_activity = 0;
  std::size_t n_rejected_peak_window = 0;
  std::size_t n_rejected_pre_activity = 0;
  std::size_t n_rejected_post_activity = 0;
  int pedestal_integrate_start = 0;
  int pedestal_integrate_stop = 0;
};

struct PeakFit {
  bool ok = false;
  double amplitude = 0.0;
  double mean = 0.0;
  double sigma = 0.0;
};

struct HistogramData {
  double xmin = 0.0;
  double xmax = 0.0;
  double bin_width = 0.0;
  std::vector<double> centers;
  std::vector<double> counts;
};

struct PointResult {
  bool ok = false;
  bool has_histogram = false;
  int channel = 0;
  int intensity = 0;
  fs::path point_dir;
  double snr = 0.0;
  double snr_combined = 0.0;
  double zero_fraction = 0.0;
  double selection_score = std::numeric_limits<double>::infinity();
  double first_peak_mean = 0.0;
  double first_peak_sigma = 0.0;
  double pedestal_sigma = 0.0;
  double sample_sigma = 0.0;
  double pedestal_center_before_shift = 0.0;
  std::size_t n_waveforms = 0;
  std::size_t n_clean_waveforms = 0;
  std::size_t n_rejected_baseline_activity = 0;
  std::size_t n_rejected_peak_window = 0;
  std::size_t n_rejected_pre_activity = 0;
  std::size_t n_rejected_post_activity = 0;
  int n_detected_peaks = 0;
  HistogramData hist;
  std::vector<PeakFit> fits;
};

[[noreturn]] void usage() {
  std::cerr
      << "Usage: analyze_led_snr_scan <run_dir> [--supplement-run-dir DIR] [--output-dir DIR]\n"
      << "                            [--channels 4,5,6] [--waveform-len N] [--reference-intensity I]\n"
      << "                            [--peak-window-pre N] [--peak-window-post N]\n"
      << "                            [--pre-activity-frac F --pre-activity-floor A]\n"
      << "                            [--post-activity-frac F --post-activity-floor A]\n";
  throw std::runtime_error("invalid arguments");
}

std::vector<int> parse_int_list(const std::string& text) {
  std::vector<int> values;
  std::stringstream ss(text);
  std::string token;
  while (std::getline(ss, token, ',')) {
    token.erase(std::remove_if(token.begin(), token.end(), ::isspace), token.end());
    if (!token.empty()) {
      values.push_back(std::stoi(token));
    }
  }
  return values;
}

bool activity_cut_enabled(double frac, double floor) {
  return frac >= 0.0 || floor >= 0.0;
}

bool exceeds_activity_cut(double value, double peak_amp, double frac, double floor) {
  if (!(value > 0.0)) {
    return false;
  }
  const bool frac_enabled = frac >= 0.0;
  const bool floor_enabled = floor >= 0.0;
  if (!frac_enabled && !floor_enabled) {
    return false;
  }
  const bool above_frac = frac_enabled && value > frac * std::max(peak_amp, 1.0);
  const bool above_floor = floor_enabled && value > floor;
  if (frac_enabled && floor_enabled) {
    return above_frac && above_floor;
  }
  return frac_enabled ? above_frac : above_floor;
}

bool peak_window_cut_enabled(const Options& opt) {
  return opt.peak_window_pre >= 0 || opt.peak_window_post >= 0;
}

Options parse_args(int argc, char** argv) {
  if (argc < 2) {
    usage();
  }

  Options opt;
  bool have_run_dir = false;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto require_value = [&](const std::string& flag) -> std::string {
      if (i + 1 >= argc) {
        throw std::runtime_error("missing value for " + flag);
      }
      return argv[++i];
    };

    if (arg == "--supplement-run-dir") {
      opt.supplement_run_dirs.push_back(fs::path(require_value(arg)));
    } else if (arg == "--output-dir") {
      opt.output_dir = fs::path(require_value(arg));
    } else if (arg == "--channels") {
      opt.channels = parse_int_list(require_value(arg));
    } else if (arg == "--waveform-len") {
      opt.waveform_len = std::stoi(require_value(arg));
    } else if (arg == "--reference-intensity") {
      opt.reference_intensity = std::stoi(require_value(arg));
    } else if (arg == "--search-start") {
      opt.search_start = std::stoi(require_value(arg));
    } else if (arg == "--search-stop") {
      opt.search_stop = std::stoi(require_value(arg));
    } else if (arg == "--baseline-margin") {
      opt.baseline_margin = std::stoi(require_value(arg));
    } else if (arg == "--baseline-len") {
      opt.baseline_len = std::stoi(require_value(arg));
    } else if (arg == "--pre-samples") {
      opt.pre_samples = std::stoi(require_value(arg));
    } else if (arg == "--post-samples") {
      opt.post_samples = std::stoi(require_value(arg));
    } else if (arg == "--max-integration-len") {
      opt.max_integration_len = std::stoi(require_value(arg));
    } else if (arg == "--threshold-frac") {
      opt.threshold_frac = std::stod(require_value(arg));
    } else if (arg == "--pre-pulse-reject-sigma") {
      opt.pre_pulse_reject_sigma = std::stod(require_value(arg));
    } else if (arg == "--target-zero-fraction") {
      opt.target_zero_fraction = std::stod(require_value(arg));
    } else if (arg == "--min-peak-separation") {
      opt.min_peak_separation = std::stod(require_value(arg));
    } else if (arg == "--hist-bins") {
      opt.hist_bins = std::stoi(require_value(arg));
    } else if (arg == "--max-plot-peaks") {
      opt.max_plot_peaks = std::stoi(require_value(arg));
    } else if (arg == "--peak-window-pre") {
      opt.peak_window_pre = std::stoi(require_value(arg));
    } else if (arg == "--peak-window-post") {
      opt.peak_window_post = std::stoi(require_value(arg));
    } else if (arg == "--post-peak-offset") {
      opt.post_peak_offset = std::stoi(require_value(arg));
    } else if (arg == "--pre-activity-frac") {
      opt.pre_activity_frac = std::stod(require_value(arg));
    } else if (arg == "--pre-activity-floor") {
      opt.pre_activity_floor = std::stod(require_value(arg));
    } else if (arg == "--post-activity-frac") {
      opt.post_activity_frac = std::stod(require_value(arg));
    } else if (arg == "--post-activity-floor") {
      opt.post_activity_floor = std::stod(require_value(arg));
    } else if (!arg.empty() && arg[0] == '-') {
      throw std::runtime_error("unknown argument: " + arg);
    } else if (!have_run_dir) {
      opt.run_dir = fs::path(arg);
      have_run_dir = true;
    } else {
      throw std::runtime_error("unexpected positional argument: " + arg);
    }
  }

  if (!have_run_dir) {
    usage();
  }
  if (opt.output_dir.empty()) {
    opt.output_dir = opt.run_dir / "cpp_snr_scan";
  }
  return opt;
}

std::string read_text(const fs::path& path) {
  std::ifstream in(path);
  if (!in) {
    throw std::runtime_error("failed to open " + path.string());
  }
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

std::string flatten_json(std::string text) {
  for (char& ch : text) {
    if (ch == '\n' || ch == '\r' || ch == '\t') {
      ch = ' ';
    }
  }
  return text;
}

int extract_json_int(const std::string& text, const std::string& key, int fallback = 0) {
  const std::regex pattern("\"" + key + "\"\\s*:\\s*([0-9]+)");
  std::smatch match;
  if (std::regex_search(text, match, pattern)) {
    return std::stoi(match[1].str());
  }
  return fallback;
}

std::vector<int> extract_json_int_array(const std::string& text, const std::string& key) {
  const std::regex pattern("\"" + key + "\"\\s*:\\s*\\[([^\\]]*)\\]");
  std::smatch match;
  if (!std::regex_search(text, match, pattern)) {
    return {};
  }
  return parse_int_list(match[1].str());
}

bool metadata_is_analyzed(const fs::path& path) {
  const std::string text = read_text(path);
  return text.find("\"status\": \"analyzed\"") != std::string::npos;
}

std::map<int, fs::path> gather_analyzed_points(const std::vector<fs::path>& run_dirs) {
  std::map<int, fs::path> chosen;
  for (const fs::path& run_dir : run_dirs) {
    const fs::path points_dir = run_dir / "points";
    if (!fs::is_directory(points_dir)) {
      continue;
    }
    for (const auto& entry : fs::directory_iterator(points_dir)) {
      if (!entry.is_directory()) {
        continue;
      }
      const std::string name = entry.path().filename().string();
      if (name.rfind("intensity_", 0) != 0) {
        continue;
      }
      const fs::path metadata_path = entry.path() / "metadata.json";
      if (!fs::exists(metadata_path) || !metadata_is_analyzed(metadata_path)) {
        continue;
      }
      const int intensity = std::stoi(name.substr(std::string("intensity_").size()));
      chosen[intensity] = entry.path();
    }
  }
  return chosen;
}

std::vector<int16_t> load_channel_waves(const fs::path& path, int waveform_len) {
  std::ifstream in(path, std::ios::binary);
  if (!in) {
    throw std::runtime_error("failed to open raw waveform file " + path.string());
  }
  in.seekg(0, std::ios::end);
  const std::streamsize nbytes = in.tellg();
  in.seekg(0, std::ios::beg);
  if (nbytes <= 0 || nbytes % static_cast<std::streamsize>(sizeof(uint16_t)) != 0) {
    throw std::runtime_error("invalid waveform file size for " + path.string());
  }
  std::vector<uint16_t> raw(static_cast<std::size_t>(nbytes / sizeof(uint16_t)));
  in.read(reinterpret_cast<char*>(raw.data()), nbytes);
  std::vector<int16_t> out(raw.size());
  for (std::size_t i = 0; i < raw.size(); ++i) {
    out[i] = static_cast<int16_t>(raw[i]);
  }
  if (out.size() % static_cast<std::size_t>(waveform_len) != 0) {
    throw std::runtime_error("waveform count not divisible by waveform_len for " + path.string());
  }
  return out;
}

double median_of(std::vector<double> values) {
  if (values.empty()) {
    return 0.0;
  }
  const std::size_t mid = values.size() / 2;
  std::nth_element(values.begin(), values.begin() + mid, values.end());
  double med = values[mid];
  if (values.size() % 2 == 0) {
    std::nth_element(values.begin(), values.begin() + mid - 1, values.end());
    med = 0.5 * (med + values[mid - 1]);
  }
  return med;
}

double robust_sigma(std::vector<double> values) {
  if (values.empty()) {
    return 0.0;
  }
  const double med = median_of(values);
  for (double& v : values) {
    v = std::fabs(v - med);
  }
  const double mad = median_of(values);
  double sigma = 1.4826 * mad;
  if (sigma <= 0.0) {
    double sum = 0.0;
    for (double v : values) {
      sum += v * v;
    }
    sigma = std::sqrt(sum / static_cast<double>(values.size()));
  }
  return std::max(sigma, 1e-9);
}

double quantile_copy(std::vector<double> values, double q) {
  if (values.empty()) {
    return 0.0;
  }
  q = std::clamp(q, 0.0, 1.0);
  const std::size_t idx = static_cast<std::size_t>(q * static_cast<double>(values.size() - 1));
  std::nth_element(values.begin(), values.begin() + idx, values.end());
  return values[idx];
}

std::vector<double> smooth_boxcar(const std::vector<double>& values, int half_window) {
  std::vector<double> out(values.size(), 0.0);
  for (std::size_t i = 0; i < values.size(); ++i) {
    const std::size_t lo = (i < static_cast<std::size_t>(half_window)) ? 0 : i - half_window;
    const std::size_t hi = std::min(values.size() - 1, i + static_cast<std::size_t>(half_window));
    double sum = 0.0;
    for (std::size_t j = lo; j <= hi; ++j) {
      sum += values[j];
    }
    out[i] = sum / static_cast<double>(hi - lo + 1);
  }
  return out;
}

ChannelWindow derive_window_from_mean(const std::vector<int16_t>& raw, int waveform_len, int channel, int reference_intensity, const Options& opt) {
  const std::size_t n_waves = raw.size() / static_cast<std::size_t>(waveform_len);
  std::vector<double> mean(waveform_len, 0.0);
  for (std::size_t i = 0; i < n_waves; ++i) {
    const int16_t* row = raw.data() + i * static_cast<std::size_t>(waveform_len);
    for (int j = 0; j < waveform_len; ++j) {
      mean[j] += static_cast<double>(row[j]);
    }
  }
  for (double& v : mean) {
    v /= static_cast<double>(n_waves);
  }

  const int s_lo = std::clamp(opt.search_start, 0, waveform_len - 2);
  const int s_hi = std::clamp(opt.search_stop, s_lo + 2, waveform_len);
  std::vector<double> rough_base(mean.begin(), mean.begin() + std::max(32, s_lo));
  const double rough_baseline = median_of(rough_base);
  std::vector<double> signal(s_hi - s_lo, 0.0);
  for (int i = s_lo; i < s_hi; ++i) {
    signal[i - s_lo] = mean[i] - rough_baseline;
  }
  const std::vector<double> smooth = smooth_boxcar(signal, 2);
  const auto peak_it = std::max_element(smooth.begin(), smooth.end());
  if (peak_it == smooth.end() || *peak_it <= 0.0) {
    throw std::runtime_error("failed to find positive mean pulse for channel " + std::to_string(channel));
  }
  const int peak_rel = static_cast<int>(std::distance(smooth.begin(), peak_it));
  const int peak_index = s_lo + peak_rel;
  double baseline_sum = 0.0;
  for (double v : rough_base) {
    const double d = v - rough_baseline;
    baseline_sum += d * d;
  }
  const double baseline_rms = std::sqrt(baseline_sum / std::max<std::size_t>(1, rough_base.size()));
  const double threshold = std::max(opt.threshold_frac * *peak_it, 4.0 * baseline_rms);

  int left = peak_rel;
  while (left > 0 && smooth[left] > threshold) {
    --left;
  }
  int right = peak_rel;
  while (right + 1 < static_cast<int>(smooth.size()) && smooth[right] > threshold) {
    ++right;
  }

  const int onset_index = s_lo + left;
  const int return_index = s_lo + right;
  const int baseline_stop = std::max(24, onset_index - opt.baseline_margin);
  const int baseline_start = std::max(0, baseline_stop - opt.baseline_len);
  const int integrate_start = std::max(0, onset_index - opt.pre_samples);
  int integrate_stop = std::min(waveform_len, return_index + opt.post_samples);
  integrate_stop = std::min(integrate_stop, integrate_start + std::max(8, opt.max_integration_len));
  if (integrate_stop <= integrate_start) {
    integrate_stop = std::min(waveform_len, integrate_start + std::max(8, opt.post_samples));
  }

  ChannelWindow window;
  window.channel = channel;
  window.reference_intensity = reference_intensity;
  window.baseline_start = baseline_start;
  window.baseline_stop = baseline_stop;
  window.onset_index = onset_index;
  window.peak_index = peak_index;
  window.integrate_start = integrate_start;
  window.integrate_stop = integrate_stop;
  return window;
}

ChargeStats measure_charge_stats(const std::vector<int16_t>& raw, int waveform_len, const ChannelWindow& window, const Options& opt) {
  const std::size_t n_waves = raw.size() / static_cast<std::size_t>(waveform_len);
  const int signal_len = window.integrate_stop - window.integrate_start;
  const int ped_stop = window.baseline_stop;
  const int ped_start = std::max(window.baseline_start, ped_stop - signal_len);
  const int search_start = std::max(window.baseline_stop, window.integrate_start - 32);
  const int search_stop = std::max(search_start + 1, std::min(
      waveform_len,
      std::max(window.integrate_stop + 64, window.peak_index + std::max(opt.peak_window_post, opt.post_peak_offset) + 16)));

  std::vector<double> signal_raw;
  std::vector<double> pedestal_raw;
  std::vector<double> baseline_max_abs;
  std::vector<double> early_max;
  std::vector<double> late_max;
  std::vector<double> peak_amp;
  std::vector<int> peak_index;
  std::vector<double> baseline_samples;
  signal_raw.reserve(n_waves);
  pedestal_raw.reserve(n_waves);
  baseline_max_abs.reserve(n_waves);
  early_max.reserve(n_waves);
  late_max.reserve(n_waves);
  peak_amp.reserve(n_waves);
  peak_index.reserve(n_waves);
  baseline_samples.reserve(n_waves * static_cast<std::size_t>(window.baseline_stop - window.baseline_start));

  std::vector<double> tmp_baseline(static_cast<std::size_t>(window.baseline_stop - window.baseline_start));
  for (std::size_t i = 0; i < n_waves; ++i) {
    const int16_t* row = raw.data() + i * static_cast<std::size_t>(waveform_len);
    for (int j = window.baseline_start; j < window.baseline_stop; ++j) {
      tmp_baseline[static_cast<std::size_t>(j - window.baseline_start)] = static_cast<double>(row[j]);
    }
    const double baseline = median_of(tmp_baseline);

    double max_abs = 0.0;
    double signal_sum = 0.0;
    double pedestal_sum = 0.0;
    for (int j = window.baseline_start; j < window.baseline_stop; ++j) {
      const double v = static_cast<double>(row[j]) - baseline;
      baseline_samples.push_back(v);
      max_abs = std::max(max_abs, std::fabs(v));
    }
    for (int j = window.integrate_start; j < window.integrate_stop; ++j) {
      signal_sum += static_cast<double>(row[j]) - baseline;
    }
    for (int j = ped_start; j < ped_stop; ++j) {
      pedestal_sum += static_cast<double>(row[j]) - baseline;
    }

    double waveform_peak_amp = -std::numeric_limits<double>::infinity();
    int waveform_peak_index = search_start;
    for (int j = search_start; j < search_stop; ++j) {
      const double v = static_cast<double>(row[j]) - baseline;
      if (v > waveform_peak_amp) {
        waveform_peak_amp = v;
        waveform_peak_index = j;
      }
    }

    double waveform_early_max = 0.0;
    for (int j = window.baseline_stop; j < window.integrate_start; ++j) {
      waveform_early_max = std::max(waveform_early_max, static_cast<double>(row[j]) - baseline);
    }

    const int late_start = std::min(search_stop, std::max(window.integrate_stop, waveform_peak_index + std::max(0, opt.post_peak_offset)));
    double waveform_late_max = 0.0;
    for (int j = late_start; j < search_stop; ++j) {
      waveform_late_max = std::max(waveform_late_max, static_cast<double>(row[j]) - baseline);
    }

    signal_raw.push_back(signal_sum);
    pedestal_raw.push_back(pedestal_sum);
    baseline_max_abs.push_back(max_abs);
    early_max.push_back(waveform_early_max);
    late_max.push_back(waveform_late_max);
    peak_amp.push_back(waveform_peak_amp);
    peak_index.push_back(waveform_peak_index);
  }

  ChargeStats stats;
  stats.n_waveforms = n_waves;
  stats.sample_sigma = robust_sigma(baseline_samples);
  stats.pedestal_integrate_start = ped_start;
  stats.pedestal_integrate_stop = ped_stop;

  const bool any_shape_cut =
      peak_window_cut_enabled(opt) ||
      activity_cut_enabled(opt.pre_activity_frac, opt.pre_activity_floor) ||
      activity_cut_enabled(opt.post_activity_frac, opt.post_activity_floor);
  const double threshold = opt.pre_pulse_reject_sigma * stats.sample_sigma;
  const int peak_lo = (opt.peak_window_pre >= 0) ? (window.peak_index - opt.peak_window_pre) : std::numeric_limits<int>::min() / 4;
  const int peak_hi = (opt.peak_window_post >= 0) ? (window.peak_index + opt.peak_window_post) : std::numeric_limits<int>::max() / 4;
  for (std::size_t i = 0; i < n_waves; ++i) {
    const bool reject_baseline = baseline_max_abs[i] >= threshold;
    const bool reject_peak_window =
        peak_window_cut_enabled(opt) && (peak_index[i] < peak_lo || peak_index[i] > peak_hi);
    const bool reject_pre_activity =
        exceeds_activity_cut(early_max[i], peak_amp[i], opt.pre_activity_frac, opt.pre_activity_floor);
    const bool reject_post_activity =
        exceeds_activity_cut(late_max[i], peak_amp[i], opt.post_activity_frac, opt.post_activity_floor);

    if (reject_baseline) {
      ++stats.n_rejected_baseline_activity;
    }
    if (reject_peak_window) {
      ++stats.n_rejected_peak_window;
    }
    if (reject_pre_activity) {
      ++stats.n_rejected_pre_activity;
    }
    if (reject_post_activity) {
      ++stats.n_rejected_post_activity;
    }
    if (reject_baseline || reject_peak_window || reject_pre_activity || reject_post_activity) {
      continue;
    }
    stats.signal_charges.push_back(signal_raw[i]);
    stats.pedestal_charges.push_back(pedestal_raw[i]);
  }
  if (stats.signal_charges.empty() && !any_shape_cut) {
    stats.signal_charges = signal_raw;
    stats.pedestal_charges = pedestal_raw;
  }
  stats.n_clean_waveforms = stats.signal_charges.size();

  stats.pedestal_center_before_shift = median_of(stats.pedestal_charges);
  for (double& v : stats.signal_charges) {
    v -= stats.pedestal_center_before_shift;
  }
  for (double& v : stats.pedestal_charges) {
    v -= stats.pedestal_center_before_shift;
  }
  stats.pedestal_sigma = robust_sigma(stats.pedestal_charges);
  return stats;
}

HistogramData make_histogram(const std::vector<double>& charges, int nbins, double xmin, double xmax) {
  HistogramData hist;
  hist.xmin = xmin;
  hist.xmax = xmax;
  hist.bin_width = (xmax - xmin) / static_cast<double>(nbins);
  hist.centers.resize(static_cast<std::size_t>(nbins));
  hist.counts.assign(static_cast<std::size_t>(nbins), 0.0);
  for (int i = 0; i < nbins; ++i) {
    hist.centers[static_cast<std::size_t>(i)] = xmin + (static_cast<double>(i) + 0.5) * hist.bin_width;
  }
  for (double v : charges) {
    if (v < xmin || v >= xmax) {
      continue;
    }
    const int bin = static_cast<int>((v - xmin) / hist.bin_width);
    if (bin >= 0 && bin < nbins) {
      hist.counts[static_cast<std::size_t>(bin)] += 1.0;
    }
  }
  return hist;
}

std::vector<int> detect_peak_bins(const HistogramData& hist, double min_x, int max_peaks) {
  const std::vector<double> smooth = smooth_boxcar(hist.counts, 2);
  const double max_count = *std::max_element(smooth.begin(), smooth.end());
  const double threshold = std::max(3.0, 0.01 * max_count);

  std::vector<int> bins;
  int last_bin = -999;
  for (int i = 1; i + 1 < static_cast<int>(smooth.size()); ++i) {
    if (hist.centers[static_cast<std::size_t>(i)] < min_x) {
      continue;
    }
    if (smooth[static_cast<std::size_t>(i)] < threshold) {
      continue;
    }
    if (smooth[static_cast<std::size_t>(i)] >= smooth[static_cast<std::size_t>(i - 1)] &&
        smooth[static_cast<std::size_t>(i)] > smooth[static_cast<std::size_t>(i + 1)]) {
      if (i - last_bin < 5) {
        continue;
      }
      bins.push_back(i);
      last_bin = i;
      if (static_cast<int>(bins.size()) >= max_peaks) {
        break;
      }
    }
  }
  return bins;
}

bool solve_linear_3x3(double a[3][4], double out[3]) {
  for (int col = 0; col < 3; ++col) {
    int pivot = col;
    for (int row = col + 1; row < 3; ++row) {
      if (std::fabs(a[row][col]) > std::fabs(a[pivot][col])) {
        pivot = row;
      }
    }
    if (std::fabs(a[pivot][col]) < 1e-12) {
      return false;
    }
    if (pivot != col) {
      for (int k = col; k < 4; ++k) {
        std::swap(a[col][k], a[pivot][k]);
      }
    }
    const double scale = a[col][col];
    for (int k = col; k < 4; ++k) {
      a[col][k] /= scale;
    }
    for (int row = 0; row < 3; ++row) {
      if (row == col) {
        continue;
      }
      const double factor = a[row][col];
      for (int k = col; k < 4; ++k) {
        a[row][k] -= factor * a[col][k];
      }
    }
  }
  out[0] = a[0][3];
  out[1] = a[1][3];
  out[2] = a[2][3];
  return true;
}

PeakFit fit_peak_quadratic_log(const HistogramData& hist, int peak_bin, int left_bin, int right_bin) {
  (void)peak_bin;
  PeakFit fit;
  double s0 = 0.0, s1 = 0.0, s2 = 0.0, s3 = 0.0, s4 = 0.0;
  double t0 = 0.0, t1 = 0.0, t2 = 0.0;
  for (int i = left_bin; i <= right_bin; ++i) {
    const double y = hist.counts[static_cast<std::size_t>(i)];
    if (y <= 0.0) {
      continue;
    }
    const double x = hist.centers[static_cast<std::size_t>(i)];
    const double w = y;
    const double ly = std::log(y);
    s0 += w;
    s1 += w * x;
    s2 += w * x * x;
    s3 += w * x * x * x;
    s4 += w * x * x * x * x;
    t0 += w * ly;
    t1 += w * x * ly;
    t2 += w * x * x * ly;
  }
  double a[3][4] = {
      {s0, s1, s2, t0},
      {s1, s2, s3, t1},
      {s2, s3, s4, t2},
  };
  double coeff[3] = {0.0, 0.0, 0.0};
  if (!solve_linear_3x3(a, coeff)) {
    return fit;
  }
  const double c0 = coeff[0];
  const double c1 = coeff[1];
  const double c2 = coeff[2];
  if (!(c2 < 0.0)) {
    return fit;
  }
  const double sigma = std::sqrt(-1.0 / (2.0 * c2));
  const double mean = c1 * sigma * sigma;
  const double amp = std::exp(c0 + mean * mean / (2.0 * sigma * sigma));
  fit.ok = std::isfinite(amp) && std::isfinite(mean) && std::isfinite(sigma) && sigma > 0.0;
  fit.amplitude = amp;
  fit.mean = mean;
  fit.sigma = sigma;
  return fit;
}

std::vector<PeakFit> fit_detected_peaks(const HistogramData& hist, const std::vector<int>& peak_bins, double sigma0) {
  std::vector<PeakFit> fits;
  fits.reserve(peak_bins.size());
  for (std::size_t i = 0; i < peak_bins.size(); ++i) {
    int left = std::max(0, peak_bins[i] - static_cast<int>(std::ceil(2.5 * sigma0 / hist.bin_width)));
    int right = std::min(static_cast<int>(hist.counts.size()) - 1, peak_bins[i] + static_cast<int>(std::ceil(2.5 * sigma0 / hist.bin_width)));
    if (i > 0) {
      left = std::max(left, (peak_bins[i - 1] + peak_bins[i]) / 2);
    }
    if (i + 1 < peak_bins.size()) {
      right = std::min(right, (peak_bins[i] + peak_bins[i + 1]) / 2);
    }
    fits.push_back(fit_peak_quadratic_log(hist, peak_bins[i], left, right));
  }
  return fits;
}

PointResult analyze_point_channel(const fs::path& point_dir, int intensity, int channel, int waveform_len, const ChannelWindow& window, const Options& opt) {
  PointResult result;
  result.channel = channel;
  result.intensity = intensity;
  result.point_dir = point_dir;

  const std::vector<int16_t> raw = load_channel_waves(point_dir / "raw" / ("channel_" + std::to_string(channel) + ".dat"), waveform_len);
  const ChargeStats stats = measure_charge_stats(raw, waveform_len, window, opt);
  result.pedestal_sigma = stats.pedestal_sigma;
  result.sample_sigma = stats.sample_sigma;
  result.pedestal_center_before_shift = stats.pedestal_center_before_shift;
  result.n_waveforms = stats.n_waveforms;
  result.n_clean_waveforms = stats.n_clean_waveforms;
  result.n_rejected_baseline_activity = stats.n_rejected_baseline_activity;
  result.n_rejected_peak_window = stats.n_rejected_peak_window;
  result.n_rejected_pre_activity = stats.n_rejected_pre_activity;
  result.n_rejected_post_activity = stats.n_rejected_post_activity;

  if (stats.signal_charges.empty() || !(stats.pedestal_sigma > 0.0)) {
    return result;
  }

  const double xmin = std::min(quantile_copy(stats.signal_charges, 0.001), -4.0 * stats.pedestal_sigma);
  const double xmax = std::max({quantile_copy(stats.signal_charges, 0.997), 6.0 * stats.pedestal_sigma, 50.0});
  const HistogramData hist = make_histogram(stats.signal_charges, opt.hist_bins, xmin, xmax);
  result.hist = hist;
  result.has_histogram = true;
  if (stats.signal_charges.size() < 200) {
    return result;
  }
  const std::vector<int> peak_bins = detect_peak_bins(hist, 0.5 * stats.pedestal_sigma, opt.max_plot_peaks);
  result.n_detected_peaks = static_cast<int>(peak_bins.size());
  if (peak_bins.empty()) {
    return result;
  }

  const std::vector<PeakFit> fits = fit_detected_peaks(hist, peak_bins, stats.pedestal_sigma);
  result.fits = fits;
  if (fits.empty() || !fits.front().ok || !(fits.front().mean > 0.0)) {
    return result;
  }

  result.first_peak_mean = fits.front().mean;
  result.first_peak_sigma = fits.front().sigma;
  result.snr = result.first_peak_mean / std::max(result.pedestal_sigma, 1e-9);
  result.snr_combined =
      result.first_peak_mean /
      std::sqrt(std::max(1e-9, result.pedestal_sigma * result.pedestal_sigma +
                                   result.first_peak_sigma * result.first_peak_sigma));
  const double threshold = 0.5 * result.first_peak_mean;
  std::size_t n_zero = 0;
  for (double charge : stats.signal_charges) {
    if (charge < threshold) {
      ++n_zero;
    }
  }
  result.zero_fraction = static_cast<double>(n_zero) / static_cast<double>(stats.signal_charges.size());
  result.selection_score =
      std::fabs(result.zero_fraction - opt.target_zero_fraction) +
      std::max(0.0, opt.min_peak_separation - result.snr);
  result.ok = std::isfinite(result.snr) && result.snr > 0.0;
  return result;
}

void write_summary_csv(const fs::path& path, const std::vector<PointResult>& rows) {
  std::ofstream out(path);
  out << "channel,intensity,point_dir,snr,snr_combined,zero_fraction,selection_score,first_peak_mean,first_peak_sigma,pedestal_sigma,sample_sigma,pedestal_center_before_shift,n_waveforms,n_clean_waveforms,n_rejected_baseline_activity,n_rejected_peak_window,n_rejected_pre_activity,n_rejected_post_activity,n_detected_peaks,ok\n";
  out << std::fixed << std::setprecision(6);
  for (const auto& row : rows) {
    out << row.channel << ','
        << row.intensity << ','
        << '"' << row.point_dir.string() << '"' << ','
        << row.snr << ','
        << row.snr_combined << ','
        << row.zero_fraction << ','
        << row.selection_score << ','
        << row.first_peak_mean << ','
        << row.first_peak_sigma << ','
        << row.pedestal_sigma << ','
        << row.sample_sigma << ','
        << row.pedestal_center_before_shift << ','
        << row.n_waveforms << ','
        << row.n_clean_waveforms << ','
        << row.n_rejected_baseline_activity << ','
        << row.n_rejected_peak_window << ','
        << row.n_rejected_pre_activity << ','
        << row.n_rejected_post_activity << ','
        << row.n_detected_peaks << ','
        << (row.ok ? "true" : "false") << '\n';
  }
}

void write_best_csv(const fs::path& path, const std::map<int, PointResult>& best) {
  std::ofstream out(path);
  out << "channel,intensity,point_dir,snr,snr_combined,zero_fraction,selection_score,first_peak_mean,first_peak_sigma,pedestal_sigma,sample_sigma,pedestal_center_before_shift,n_waveforms,n_clean_waveforms,n_rejected_baseline_activity,n_rejected_peak_window,n_rejected_pre_activity,n_rejected_post_activity,n_detected_peaks\n";
  out << std::fixed << std::setprecision(6);
  for (const auto& [channel, row] : best) {
    out << channel << ','
        << row.intensity << ','
        << '"' << row.point_dir.string() << '"' << ','
        << row.snr << ','
        << row.snr_combined << ','
        << row.zero_fraction << ','
        << row.selection_score << ','
        << row.first_peak_mean << ','
        << row.first_peak_sigma << ','
        << row.pedestal_sigma << ','
        << row.sample_sigma << ','
        << row.pedestal_center_before_shift << ','
        << row.n_waveforms << ','
        << row.n_clean_waveforms << ','
        << row.n_rejected_baseline_activity << ','
        << row.n_rejected_peak_window << ','
        << row.n_rejected_pre_activity << ','
        << row.n_rejected_post_activity << ','
        << row.n_detected_peaks << '\n';
  }
}

void write_windows_json(const fs::path& path, const std::map<int, ChannelWindow>& windows) {
  std::ofstream out(path);
  out << "{\n";
  bool first = true;
  for (const auto& [channel, w] : windows) {
    if (!first) {
      out << ",\n";
    }
    first = false;
    out << "  \"" << channel << "\": {\n"
        << "    \"channel\": " << w.channel << ",\n"
        << "    \"reference_intensity\": " << w.reference_intensity << ",\n"
        << "    \"baseline_start\": " << w.baseline_start << ",\n"
        << "    \"baseline_stop\": " << w.baseline_stop << ",\n"
        << "    \"onset_index\": " << w.onset_index << ",\n"
        << "    \"peak_index\": " << w.peak_index << ",\n"
        << "    \"integrate_start\": " << w.integrate_start << ",\n"
        << "    \"integrate_stop\": " << w.integrate_stop << "\n"
        << "  }";
  }
  out << "\n}\n";
}

void write_histogram_csv(
    const fs::path& path,
    const HistogramData& hist,
    const std::vector<PeakFit>& fits,
    int max_columns) {
  std::ofstream out(path);
  out << "x,count,total_fit";
  for (int i = 0; i < max_columns; ++i) {
    out << ",peak_" << (i + 1);
  }
  out << "\n";
  out << std::fixed << std::setprecision(6);
  for (std::size_t i = 0; i < hist.centers.size(); ++i) {
    double total = 0.0;
    std::vector<double> comps(static_cast<std::size_t>(max_columns), 0.0);
    for (int p = 0; p < max_columns && p < static_cast<int>(fits.size()); ++p) {
      if (!fits[static_cast<std::size_t>(p)].ok) {
        continue;
      }
      const PeakFit& fit = fits[static_cast<std::size_t>(p)];
      const double z = (hist.centers[i] - fit.mean) / std::max(fit.sigma, 1e-9);
      comps[static_cast<std::size_t>(p)] = fit.amplitude * std::exp(-0.5 * z * z);
      total += comps[static_cast<std::size_t>(p)];
    }
    out << hist.centers[i] << ',' << hist.counts[i] << ',' << total;
    for (double comp : comps) {
      out << ',' << comp;
    }
    out << "\n";
  }
}

std::string padded_intensity(int intensity) {
  std::string text = std::to_string(intensity);
  if (text.size() < 4) {
    text = std::string(4 - text.size(), '0') + text;
  }
  return text;
}

fs::path histogram_csv_path(const fs::path& out_dir, int channel, int intensity) {
  return out_dir / "all_histograms" /
         ("ch" + (channel < 10 ? std::string("0") : std::string("")) + std::to_string(channel) +
          "_intensity_" + padded_intensity(intensity) + "_histogram.csv");
}

void write_best_point_outputs(const Options& opt, const ChannelWindow& window, const PointResult& best_row) {
  const std::vector<int16_t> raw = load_channel_waves(best_row.point_dir / "raw" / ("channel_" + std::to_string(best_row.channel) + ".dat"), opt.waveform_len);
  const ChargeStats stats = measure_charge_stats(raw, opt.waveform_len, window, opt);
  const double xmin = std::min(quantile_copy(stats.signal_charges, 0.001), -3.0 * stats.pedestal_sigma);
  const double xmax = std::max({quantile_copy(stats.signal_charges, 0.997), best_row.first_peak_mean * (opt.max_plot_peaks + 0.75), 50.0});
  const HistogramData hist = make_histogram(stats.signal_charges, opt.hist_bins, xmin, xmax);
  const std::vector<int> peak_bins = detect_peak_bins(hist, 0.5 * stats.pedestal_sigma, opt.max_plot_peaks);
  const std::vector<PeakFit> fits = fit_detected_peaks(hist, peak_bins, stats.pedestal_sigma);

  const fs::path csv_path = opt.output_dir / ("best_ch" + (best_row.channel < 10 ? std::string("0") : std::string("")) +
                                              std::to_string(best_row.channel) + "_intensity_" +
                                              padded_intensity(best_row.intensity) + "_histogram.csv");
  write_histogram_csv(csv_path, hist, fits, opt.max_plot_peaks);
}

void write_all_point_histograms(const Options& opt, const std::vector<PointResult>& rows) {
  fs::create_directories(opt.output_dir / "all_histograms");
  for (const auto& row : rows) {
    if (!row.has_histogram) {
      continue;
    }
    write_histogram_csv(
        histogram_csv_path(opt.output_dir, row.channel, row.intensity),
        row.hist,
        row.fits,
        opt.max_plot_peaks);
  }
}

bool better_by_score(const PointResult& candidate, const PointResult& current) {
  if (candidate.selection_score < current.selection_score - 1e-9) {
    return true;
  }
  if (candidate.selection_score > current.selection_score + 1e-9) {
    return false;
  }
  if (candidate.snr > current.snr + 1e-9) {
    return true;
  }
  if (candidate.snr < current.snr - 1e-9) {
    return false;
  }
  return candidate.intensity < current.intensity;
}

int main(int argc, char** argv) {
  try {
    Options opt = parse_args(argc, argv);
    opt.run_dir = fs::absolute(opt.run_dir);
    for (fs::path& p : opt.supplement_run_dirs) {
      p = fs::absolute(p);
    }
    opt.output_dir = fs::absolute(opt.output_dir);
    fs::create_directories(opt.output_dir);

    const std::string manifest_text = flatten_json(read_text(opt.run_dir / "scan_manifest.json"));
    if (opt.waveform_len <= 0) {
      opt.waveform_len = extract_json_int(manifest_text, "waveform_len", 1024);
    }
    if (opt.channels.empty()) {
      opt.channels = extract_json_int_array(manifest_text, "channels");
    }
    if (opt.channels.empty()) {
      throw std::runtime_error("failed to determine channel list");
    }

    std::vector<fs::path> run_dirs;
    run_dirs.push_back(opt.run_dir);
    run_dirs.insert(run_dirs.end(), opt.supplement_run_dirs.begin(), opt.supplement_run_dirs.end());
    const std::map<int, fs::path> points = gather_analyzed_points(run_dirs);
    if (points.empty()) {
      throw std::runtime_error("no analyzed points found");
    }

    const int reference_intensity = opt.reference_intensity > 0 ? opt.reference_intensity : points.rbegin()->first;
    if (!points.count(reference_intensity)) {
      throw std::runtime_error("reference intensity not found among analyzed points");
    }

    std::map<int, ChannelWindow> windows;
    for (int channel : opt.channels) {
      const fs::path ref_file = points.at(reference_intensity) / "raw" / ("channel_" + std::to_string(channel) + ".dat");
      const std::vector<int16_t> raw = load_channel_waves(ref_file, opt.waveform_len);
      windows[channel] = derive_window_from_mean(raw, opt.waveform_len, channel, reference_intensity, opt);
    }
    write_windows_json(opt.output_dir / "channel_windows.json", windows);

    std::vector<PointResult> all_rows;
    std::map<int, PointResult> best_by_channel;
    std::map<int, PointResult> max_snr_by_channel;
    for (const auto& [intensity, point_dir] : points) {
      for (int channel : opt.channels) {
        PointResult row = analyze_point_channel(point_dir, intensity, channel, opt.waveform_len, windows.at(channel), opt);
        all_rows.push_back(row);
        if (row.ok) {
          auto best_it = best_by_channel.find(channel);
          if (best_it == best_by_channel.end() || better_by_score(row, best_it->second)) {
            best_by_channel[channel] = row;
          }
          auto snr_it = max_snr_by_channel.find(channel);
          if (snr_it == max_snr_by_channel.end() || row.snr > snr_it->second.snr) {
            max_snr_by_channel[channel] = row;
          }
        }
      }
    }

    write_summary_csv(opt.output_dir / "summary_by_point_channel.csv", all_rows);
    write_best_csv(opt.output_dir / "best_by_channel.csv", best_by_channel);
    write_best_csv(opt.output_dir / "max_snr_by_channel.csv", max_snr_by_channel);
    write_all_point_histograms(opt, all_rows);
    for (const auto& [channel, best_row] : best_by_channel) {
      write_best_point_outputs(opt, windows.at(channel), best_row);
    }

    std::cout << "C++ LED SNR scan saved to " << opt.output_dir << "\n";
    std::cout << "Best-by-channel rows: " << best_by_channel.size() << "\n";
    return 0;
  } catch (const std::exception& exc) {
    std::cerr << "ERROR: " << exc.what() << "\n";
    return 1;
  }
}
