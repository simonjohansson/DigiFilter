#!/usr/bin/env python3
"""Check the private C control against the resistor model and scan schedule (host cc)."""
import ctypes
import math
from pathlib import Path
import subprocess
import tempfile

import ob1_model as M
import ob1_programmer as P
from ob1_check import build as host_kernel

ROOT = Path(__file__).resolve().parent.parent


def check_open_response(cutoff8):
    kernel = host_kernel()
    amplitude, count = 1 << 23, 4800
    buffer = (ctypes.c_int * 32)()
    for tap in (4, 2):
        for hz, maximum_loss in ((1000, 0.05), (5000, 0.2), (10000, 0.7), (15000, 2.3)):
            kernel.ob1_vcf_reset(0)
            output = []
            for start in range(0, 2 * count, 32):
                for i in range(32):
                    buffer[i] = round(amplitude * math.sin(2 * math.pi * hz * (start + i) / M.FS))
                kernel.ob1_vcf_run(tap, cutoff8, 0, buffer, 0)
                if start >= count:
                    output.extend(buffer)
            real = sum(y * math.cos(2 * math.pi * hz * i / M.FS) for i, y in enumerate(output))
            imag = sum(y * math.sin(2 * math.pi * hz * i / M.FS) for i, y in enumerate(output))
            gain = 2 * math.hypot(real, imag) / (count * amplitude * M.LEVEL)
            loss = -20 * math.log10(gain)
            assert -0.01 < loss < maximum_loss, (tap, hz, loss, maximum_loss)
            print('PASS: maximum FREQ, zero RESO/modulation, OB%d at %d Hz: %.3f dB loss' %
                  (tap, hz, loss))


def main():
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'control.c'
        library = Path(directory) / 'control.so'
        source.write_text('''#include <stddef.h>
#include "ob1_control.h"
_Static_assert(sizeof(struct ob1_control) == 12, "dispatcher stride");
_Static_assert(offsetof(struct ob1_control, fresh) == 8, "dispatcher fresh offset");
static struct ob1_control states[8] = {[0 ... 7] = {.fresh = 1}};
int cutoff(int word) { return ob1_knob_cutoff8(word); }
int step(int voice, int word) { return ob1_control_run(&states[voice], word); }
void reset(int voice) { states[voice].fresh = 1; }
unsigned int phase(int voice) { return states[voice].phase; }
''')
        subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-fPIC', '-I', str(ROOT), str(source), '-o', str(library)], check=True)
        c = ctypes.CDLL(str(library))
        c.cutoff.argtypes = [ctypes.c_int]
        c.step.argtypes = [ctypes.c_int, ctypes.c_int]
        c.reset.argtypes = [ctypes.c_int]
        c.phase.argtypes = [ctypes.c_int]
        c.phase.restype = ctypes.c_uint

        targets = []
        for word in range(0x7f01):
            actual = c.cutoff(word)
            assert abs(actual - P.knob_cutoff8(word)) <= 0.51, (word, actual)
            targets.append(actual)
        assert targets == sorted(targets)
        levels = sorted(set(targets))
        assert len(levels) == 64
        assert c.cutoff(-1) == levels[0] and c.cutoff(0x10000) == levels[-1]
        assert c.cutoff(0x7f00) == 0x7f00
        pitches = [M.corner_hz(fi8 / 256) for fi8 in levels]
        intervals = [1200 * math.log2(b / a) for a, b in zip(pitches, pitches[1:])]
        assert max(abs(interval - 100) for interval in intervals) < 0.7
        print('PASS: all FREQ words match the DAC model within 0.51 index LSB; 64 targets')
        print('Nominal base range: %.3f..%.3f Hz; adjacent intervals %.3f..%.3f cents' %
              (pitches[0], pitches[-1], min(intervals), max(intervals)))

        # Independent elapsed-time calculation: sample at the first block boundary after a scan.
        period = 22 * 89 / 126660
        held, last_scan, updates = None, -1, []
        for block in range(15000):
            word = (block * 193) % 0x7f01
            scan = math.floor((block * 32 / 48000) / period)
            if scan != last_scan:
                held, last_scan = c.cutoff(word), scan
                updates.append(block)
            assert c.step(0, word) == held, block
            assert c.phase(0) < 22 * 89 * 48000
        assert updates[1] == 24
        assert set(b - a for a, b in zip(updates, updates[1:])) == {23, 24}
        c.reset(0)
        assert c.step(0, 0) == c.cutoff(0) and c.phase(0) == 0
        for voice in range(1, 8):
            assert c.step(voice, voice * 4000) == c.cutoff(voice * 4000)
            assert c.phase(voice) == 0
        assert c.step(0, 0x7f00) == c.cutoff(0)
        print('PASS: ten seconds of scan timing, 23/24-block holds, reset and eight independent voices')
        check_open_response(c.cutoff(0x7f00))


if __name__ == '__main__':
    main()
