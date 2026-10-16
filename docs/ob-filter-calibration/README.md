# OB4/OB2 calibration: before and after

These figures compare original master 404f72f with calibrated implementation 5e4f15b.
Dashed curves are before calibration; solid curves are after.

- **Cutoff response:** identical FREQ 32/64/96, RESO 0, both outputs. This shows how
  the cutoff position changes at the same knob setting.
- **Resonance response:** matched nominal 1 kHz stage cutoff, RESO 0/32/64/78,
  both outputs. This isolates the change in resonance and bass loss.
- **Control mappings:** full cutoff and feedback laws, with oscillation thresholds.

PNG files are previews; SVG files are scalable figures. The PDF contains all three pages.

The response curves use each revision's analytical small-signal model. Markers come
from its native C step response with the existing linear validation flag, disabling
saturation and seed. All response curves are below self-oscillation. These are
implementation comparisons, not hardware measurements or reference-plugin captures.
The control-map figure is calculated and does not represent an oscillation spectrum.

The fixed x0.25 output gain is removed equally from every response curve. Resonance
curves retain their bass loss. Nominal cutoff is a stage corner, not the complete
filter's -3 dB point. Native C uses 8.8 control interpolation, so minor coefficient
and interpolation differences remain.

Across 28 plotted native/model comparisons, the maximum checked discrepancy above
-45 dB was 0.0306 dB. Below that level fixed-point quantization can dominate the FFT.
The verification JSON records source hashes, exact control positions and check results.
Physical listening and nonlinear self-oscillation spectra are outside these figures.

This reference branch holds review assets separately from the implementation PR.
