// Integer-factor reduction that reproduces PIL's Image.resize(..., LANCZOS) on an RGB image
// (separable, horizontal pass first, 8-bit intermediate), or a plain box average.
#include <algorithm>
#include <cmath>

#include "internal.hpp"

namespace scad::render::detail {
namespace {

double sinc(double x) {
  if (x == 0.0)
    return 1.0;
  x *= kPi;
  return std::sin(x) / x;
}

double lanczos3(double x) {
  return (-3.0 < x && x < 3.0) ? sinc(x) * sinc(x / 3.0) : 0.0;
}

struct Taps {
  std::vector<int> first, count;
  std::vector<std::vector<float>> weights;
};

Taps make_taps(int in_size, int out_size, Resolve mode) {
  const double scale = static_cast<double>(in_size) / out_size;
  Taps t;
  t.first.resize(static_cast<std::size_t>(out_size));
  t.count.resize(static_cast<std::size_t>(out_size));
  t.weights.resize(static_cast<std::size_t>(out_size));
  const double support = (mode == Resolve::Lanczos ? 3.0 : 0.5) * scale;
  for (int xx = 0; xx < out_size; ++xx) {
    const double center = (xx + 0.5) * scale;
    int xmin = static_cast<int>(center - support + 0.5);
    int xmax = static_cast<int>(center + support + 0.5);
    xmin = std::max(xmin, 0);
    xmax = std::min(xmax, in_size);
    std::vector<float> w;
    double total = 0;
    for (int x = xmin; x < xmax; ++x) {
      const double arg = (x - center + 0.5) / scale;
      const double v = mode == Resolve::Lanczos ? lanczos3(arg) : 1.0;
      w.push_back(static_cast<float>(v));
      total += v;
    }
    for (float& v : w)
      v = static_cast<float>(v / total);
    t.first[static_cast<std::size_t>(xx)] = xmin;
    t.count[static_cast<std::size_t>(xx)] = xmax - xmin;
    t.weights[static_cast<std::size_t>(xx)] = std::move(w);
  }
  return t;
}

inline std::uint8_t clip8(float v) {
  return static_cast<std::uint8_t>(std::clamp(std::floor(v + 0.5f), 0.0f, 255.0f));
}

}  // namespace

void reduce(const std::uint8_t* src, int src_w, int src_h, int factor, Resolve mode, std::uint8_t* dst, int threads) {
  const int dw = src_w / factor, dh = src_h / factor;
  if (factor == 1) {
    std::copy(src, src + static_cast<std::size_t>(src_w) * static_cast<std::size_t>(src_h) * 4, dst);
    return;
  }
  const Taps xt = make_taps(src_w, dw, mode), yt = make_taps(src_h, dh, mode);
  std::vector<std::uint8_t> tmp(static_cast<std::size_t>(dw) * static_cast<std::size_t>(src_h) * 4);
  parallel_for(src_h, threads, [&](int y) {
    const std::uint8_t* row = src + static_cast<std::size_t>(y) * static_cast<std::size_t>(src_w) * 4;
    std::uint8_t* out = tmp.data() + static_cast<std::size_t>(y) * static_cast<std::size_t>(dw) * 4;
    for (int x = 0; x < dw; ++x) {
      const auto& w = xt.weights[static_cast<std::size_t>(x)];
      const std::uint8_t* p = row + static_cast<std::size_t>(xt.first[static_cast<std::size_t>(x)]) * 4;
      float acc[3] = {0, 0, 0};
      for (std::size_t k = 0; k < w.size(); ++k)
        for (int c = 0; c < 3; ++c)
          acc[c] += w[k] * p[4 * k + static_cast<std::size_t>(c)];
      for (int c = 0; c < 3; ++c)
        out[4 * x + c] = clip8(acc[c]);
      out[4 * x + 3] = 255;
    }
  });
  parallel_for(dh, threads, [&](int y) {
    const auto& w = yt.weights[static_cast<std::size_t>(y)];
    const int first = yt.first[static_cast<std::size_t>(y)];
    std::uint8_t* out = dst + static_cast<std::size_t>(y) * static_cast<std::size_t>(dw) * 4;
    for (int x = 0; x < dw; ++x) {
      float acc[3] = {0, 0, 0};
      for (std::size_t k = 0; k < w.size(); ++k) {
        const std::uint8_t* p = tmp.data() + (static_cast<std::size_t>(first) + k) * static_cast<std::size_t>(dw) * 4 +
                                static_cast<std::size_t>(x) * 4;
        for (int c = 0; c < 3; ++c)
          acc[c] += w[k] * p[c];
      }
      for (int c = 0; c < 3; ++c)
        out[4 * x + c] = clip8(acc[c]);
      out[4 * x + 3] = 255;
    }
  });
}

}  // namespace scad::render::detail
