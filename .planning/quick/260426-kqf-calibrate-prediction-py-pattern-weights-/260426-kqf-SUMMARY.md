# Quick Task 260426-kqf: Calibrate prediction.py pattern weights

**Completed:** 2026-04-26
**Status:** Done

## Changes

### prediction.py
- **Updated PATTERN_WEIGHTS** from intuition-based to data-driven values calibrated from 50k-observation backtest:
  - adl_divergence: 1.5 → 3.0 (star pattern, +5.3pp edge)
  - volume_accumulation: 1.5 → 2.5 (+3.2pp edge)
  - higher_lows: 1.3 → 0.8 (noise solo, combo amplifier)
  - keltner_squeeze: 2.0 → 0.8 (noise solo, combo amplifier)
  - relative_strength: 0.8 → 0.8 (unchanged)
  - fair_value_gap: 1.2 → 0.5 (no solo edge)
  - macd_launch_zone: 1.0 → 0.5 (negative solo edge, best combo partner)
- **Removed obv_divergence** from pattern detector list (0 fires in 50k observations)
- **Added combo bonus system**: COMBO_BONUS_CORE and COMBO_BONUS_MULTIPLIER (1.5x) reward adl_divergence/volume_accumulation co-firing with other patterns (backtest shows +5-18pp edge)
- **Tightened volume gate**: now requires adl_divergence OR volume_accumulation specifically (not just any volume-category pattern)
- **Updated module docstring** with backtest provenance and data-driven weight listing

### tests/test_prediction.py (new)
- 5 tests: weight calibration, combo constants, volume gate rejection/acceptance, obv_divergence removal

### tests/test_pattern_backtester.py (fixes)
- Fixed pre-existing test bugs: `edge` → `edge_vs_baseline`, `momentum` → `momentum_top20_sma_filter`, removed invalid `forward_days` kwarg

## Test Results
- 190 tests pass (0 failures)
