---
phase: quick
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - prediction.py
  - tests/test_prediction.py
autonomous: true

must_haves:
  truths:
    - "PATTERN_WEIGHTS reflect backtest-measured edges (adl_divergence highest at 3.0, volume_accumulation 2.5, others 0.5-1.0)"
    - "obv_divergence is removed from pattern detector list and PATTERN_WEIGHTS"
    - "Combo bonus system rewards adl_divergence or volume_accumulation co-firing with other patterns"
    - "Volume gate specifically requires adl_divergence OR volume_accumulation (not just any volume-category pattern)"
    - "All existing tests pass, new prediction tests pass"
  artifacts:
    - path: "prediction.py"
      provides: "Calibrated pattern weights, combo bonus, updated volume gate"
    - path: "tests/test_prediction.py"
      provides: "Tests for weight calibration, combo bonus, volume gate logic"
---

<objective>
Calibrate prediction.py pattern weights using 50,000-observation backtest results.

Purpose: Replace intuition-based pattern weights with data-driven weights from walk-forward backtesting. Add combo bonus system that captures the 12-18pp edge when adl_divergence co-fires with other patterns.
Output: Updated prediction.py with calibrated weights, combo bonus, tightened volume gate; new test file.
</objective>

<execution_context>
@.planning/quick/260426-kqf-calibrate-prediction-py-pattern-weights-/260426-kqf-PLAN.md
</execution_context>

<context>
@prediction.py
@tests/conftest.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Calibrate weights, remove obv_divergence, add combo bonus, update volume gate</name>
  <files>prediction.py</files>
  <action>
Make these specific changes to prediction.py:

1. **Update PATTERN_WEIGHTS** (line ~132) to reflect measured backtest edges:
```python
PATTERN_WEIGHTS = {
    "adl_divergence":      3.0,   # star pattern: 59.8% hit, +5.3pp edge
    "volume_accumulation": 2.5,   # strong: 57.6% hit, +3.2pp edge
    "higher_lows":         0.8,   # weak solo, strong in combos with adl
    "keltner_squeeze":     0.8,   # weak solo, strong in combos with adl
    "relative_strength":   0.8,   # weak solo, strong in combos with adl
    "fair_value_gap":      0.5,   # no edge solo (54.4% = baseline)
    "macd_launch_zone":    0.5,   # negative solo edge, but best combo partner with adl
}
```
Remove "obv_divergence" from the dict entirely.

2. **Remove obv_divergence from the pattern detector list** in `predict()` function (line ~962).
Delete the line: `detect_obv_divergence(df),`
Also remove the corresponding reason-builder in the reasons block (~line 1053-1054).

3. **Add combo bonus constant and function** after PATTERN_WEIGHTS:
```python
# Combo bonus: measured 2-3 pattern confluence edges from 50k-observation backtest
# adl_divergence combos produce +5pp to +18pp edge above baseline
COMBO_BONUS_CORE = {"adl_divergence", "volume_accumulation"}
COMBO_BONUS_MULTIPLIER = 1.5  # 50% bonus when a core pattern co-fires with others
```

4. **Apply combo bonus in the scoring section** of `predict()` (after the weighted_score loop, around line ~990). After computing `weighted_score`, add:
```python
# Combo bonus: when adl_divergence or volume_accumulation co-fires with
# other patterns, apply multiplicative bonus (backtest shows +5-18pp edge)
active_names = {p.name for p in active_patterns}
core_active = active_names & COMBO_BONUS_CORE
non_core_active = active_names - COMBO_BONUS_CORE
if core_active and non_core_active:
    combo_multiplier = 1.0 + (COMBO_BONUS_MULTIPLIER - 1.0) * len(core_active)
    weighted_score *= combo_multiplier
```

5. **Update volume gate** in `predict()` (~line 978). Change from checking any volume-category pattern to specifically requiring adl_divergence or volume_accumulation:
```python
# Gate 2: Volume gate — must have adl_divergence or volume_accumulation
# (backtest shows only these two have real volume edge; other volume-category
# patterns like obv_divergence had 0 fires)
core_volume = {p.name for p in active_patterns} & {"adl_divergence", "volume_accumulation"}
if not core_volume:
    return None
```

6. **Update module docstring** (lines 1-23) to reflect new data-driven weights and remove obv_divergence from the pattern library listing. Mention the backtest source (50k observations, 200 stocks, 250 days).
  </action>
  <verify>
    <automated>python -c "import prediction; print('PATTERN_WEIGHTS:', prediction.PATTERN_WEIGHTS); assert 'obv_divergence' not in prediction.PATTERN_WEIGHTS; assert prediction.PATTERN_WEIGHTS['adl_divergence'] == 3.0; assert prediction.PATTERN_WEIGHTS['volume_accumulation'] == 2.5; assert hasattr(prediction, 'COMBO_BONUS_CORE'); print('OK')"</automated>
  </verify>
  <done>
  - PATTERN_WEIGHTS has 7 entries (no obv_divergence), adl_divergence=3.0, volume_accumulation=2.5
  - obv_divergence removed from detect list and reasons
  - COMBO_BONUS_CORE and COMBO_BONUS_MULTIPLIER constants exist
  - Combo bonus applied in scoring when core pattern co-fires
  - Volume gate checks specifically for adl_divergence or volume_accumulation
  - Module docstring updated with backtest provenance
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add prediction tests for calibrated weights, combo bonus, and volume gate</name>
  <files>tests/test_prediction.py</files>
  <behavior>
    - Test: PATTERN_WEIGHTS contains correct data-driven values and excludes obv_divergence
    - Test: Volume gate rejects predictions that have volume-category patterns but NOT adl_divergence or volume_accumulation (e.g., only obv_divergence if it were still present)
    - Test: Volume gate accepts predictions when adl_divergence fires
    - Test: Volume gate accepts predictions when volume_accumulation fires
    - Test: Combo bonus increases weighted_score when adl_divergence co-fires with relative_strength vs when relative_strength fires alone
    - Test: predict() does not call detect_obv_divergence (removed from detector list)
  </behavior>
  <action>
Create tests/test_prediction.py. Build test DataFrames with enough bars (60+ rows of OHLCV) to pass the trend filter. Use unittest.mock.patch to control which patterns fire:

1. **test_pattern_weights_calibrated**: Assert PATTERN_WEIGHTS keys match expected set (7 patterns, no obv_divergence), assert adl_divergence=3.0 and volume_accumulation=2.5.

2. **test_volume_gate_requires_core_volume**: Patch all detectors to return detected=False except for `detect_higher_lows` (category="price") and `detect_relative_strength` (category="momentum"). Call predict() and assert it returns None (no core volume pattern).

3. **test_volume_gate_accepts_adl_divergence**: Patch `detect_adl_divergence` to return detected=True plus `detect_higher_lows` detected=True. Patch `_compute_historical_accuracy` to return valid results. Assert predict() returns a Prediction (not None).

4. **test_combo_bonus_amplifies_score**: Patch `detect_adl_divergence` + `detect_relative_strength` both detected=True. Capture the confidence. Then patch only `detect_relative_strength` detected=True (with adl=False). Compare confidences -- the combo version should be higher.

5. **test_obv_divergence_not_in_detectors**: Import predict, inspect the source or mock detect_obv_divergence and verify it is never called during predict().

Helper: Create a `_make_uptrending_df(n=80)` fixture that generates synthetic OHLCV data with SMA20 > SMA50 and price above SMA20.
  </action>
  <verify>
    <automated>python -m pytest tests/test_prediction.py -x -v 2>&1 | tail -30</automated>
  </verify>
  <done>All 5 tests pass. Tests validate calibrated weights, combo bonus behavior, volume gate strictness, and obv_divergence removal.</done>
</task>

</tasks>

<verification>
1. `python -m pytest tests/test_prediction.py -x -v` -- all new tests pass
2. `python -m pytest tests/ -x --timeout=60` -- all existing tests still pass
3. `python -c "from prediction import predict, PATTERN_WEIGHTS; print(PATTERN_WEIGHTS)"` -- confirms weights loaded correctly
</verification>

<success_criteria>
- prediction.py weights reflect backtest data (adl_divergence=3.0 highest, volume_accumulation=2.5 second)
- obv_divergence completely removed (0 fires in 50k observations)
- Combo bonus rewards adl_divergence/volume_accumulation confluence with other patterns
- Volume gate specifically requires adl_divergence or volume_accumulation
- All tests green
</success_criteria>

<output>
After completion, create `.planning/quick/260426-kqf-calibrate-prediction-py-pattern-weights-/260426-kqf-SUMMARY.md`
</output>
