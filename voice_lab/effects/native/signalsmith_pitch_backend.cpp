#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

#include "signalsmith-stretch/signalsmith-stretch.h"

namespace py = pybind11;

class SignalsmithPitchBackend {
public:
	SignalsmithPitchBackend(int sampleRate, int blockSize, int channels)
		: sampleRate(sampleRate), blockSize(blockSize), channels(channels),
			input(channels, std::vector<float>(blockSize, 0.0f)),
			output(channels, std::vector<float>(blockSize, 0.0f)),
			inputPtrs(channels, nullptr),
			outputPtrs(channels, nullptr) {
		if (sampleRate <= 0) throw std::runtime_error("sample_rate must be positive");
		if (blockSize <= 0) throw std::runtime_error("block_size must be positive");
		if (channels != 1) throw std::runtime_error("only mono processing is supported");
		stretch.presetCheaper(channels, static_cast<float>(sampleRate), false);
		stretch.setTransposeSemitones(0.0f);
		stretch.setFormantSemitones(0.0f, false);
		updatePointers();
	}

	void set_semitones(float semitones) {
		if (!std::isfinite(semitones)) throw std::runtime_error("semitones must be finite");
		this->semitones = semitones;
		stretch.setTransposeSemitones(semitones);
	}

	void set_formant_semitones(float semitones) {
		if (!std::isfinite(semitones)) throw std::runtime_error("formant semitones must be finite");
		this->formantSemitones = semitones;
		stretch.setFormantSemitones(semitones, false);
	}

	void set_formant_factor(float factor) {
		if (!std::isfinite(factor) || factor <= 0.0f) throw std::runtime_error("formant factor must be finite and positive");
		this->formantSemitones = 12.0f * std::log2(factor);
		stretch.setFormantFactor(factor, false);
	}

	py::array_t<float> process(py::array_t<float, py::array::c_style | py::array::forcecast> samples) {
		py::buffer_info info = samples.request();
		if (info.ndim != 1) throw std::runtime_error("samples must be mono with shape (frames,)");
		if (info.shape[0] != blockSize) throw std::runtime_error("samples length must match block_size");

		auto *source = static_cast<float *>(info.ptr);
		std::copy(source, source + blockSize, input[0].begin());
		std::fill(output[0].begin(), output[0].end(), 0.0f);

		stretch.process(inputPtrs.data(), blockSize, outputPtrs.data(), blockSize);

		py::array_t<float> result(blockSize);
		py::buffer_info resultInfo = result.request();
		auto *dest = static_cast<float *>(resultInfo.ptr);
		std::copy(output[0].begin(), output[0].end(), dest);
		return result;
	}

	void reset() {
		stretch.reset();
		stretch.setTransposeSemitones(semitones);
		stretch.setFormantSemitones(formantSemitones, false);
	}

	int latency_frames() const {
		return stretch.inputLatency() + stretch.outputLatency();
	}

	int input_latency_frames() const {
		return stretch.inputLatency();
	}

	int output_latency_frames() const {
		return stretch.outputLatency();
	}

	void close() {}

private:
	void updatePointers() {
		for (int channel = 0; channel < channels; ++channel) {
			inputPtrs[channel] = input[channel].data();
			outputPtrs[channel] = output[channel].data();
		}
	}

	int sampleRate;
	int blockSize;
	int channels;
	float semitones = 0.0f;
	float formantSemitones = 0.0f;
	signalsmith::stretch::SignalsmithStretch<float> stretch;
	std::vector<std::vector<float>> input;
	std::vector<std::vector<float>> output;
	std::vector<float *> inputPtrs;
	std::vector<float *> outputPtrs;
};

PYBIND11_MODULE(_signalsmith_pitch, module) {
	py::class_<SignalsmithPitchBackend>(module, "SignalsmithPitchBackend")
		.def(py::init<int, int, int>())
		.def("set_semitones", &SignalsmithPitchBackend::set_semitones)
		.def("set_formant_semitones", &SignalsmithPitchBackend::set_formant_semitones)
		.def("set_formant_factor", &SignalsmithPitchBackend::set_formant_factor)
		.def("process", &SignalsmithPitchBackend::process)
		.def("reset", &SignalsmithPitchBackend::reset)
		.def("latency_frames", &SignalsmithPitchBackend::latency_frames)
		.def("input_latency_frames", &SignalsmithPitchBackend::input_latency_frames)
		.def("output_latency_frames", &SignalsmithPitchBackend::output_latency_frames)
		.def("close", &SignalsmithPitchBackend::close);
}
