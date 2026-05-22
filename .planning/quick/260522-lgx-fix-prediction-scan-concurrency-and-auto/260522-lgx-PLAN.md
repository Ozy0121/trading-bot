---
type: quick
tasks: 2
autonomous: true
files_modified:
  - routes/scanner.py
  - routes/trading.py
---

<objective>
Fix two bugs in the prediction system: (1) prediction scan endpoint has no concurrency guard allowing unlimited parallel threads, (2) autotrade endpoint silently succeeds but filters out all predictions due to overly strict confidence >= 8 requirement.

Purpose: Prevent resource exhaustion from duplicate scans and make autotrade actually place orders when user clicks the button.
Output: Both endpoints behave correctly - scan rejects duplicate runs, autotrade pre-validates and uses relaxed filtering.
</objective>

<context>
@routes/scanner.py
@routes/trading.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add concurrency guard to prediction scan endpoint</name>
  <files>routes/scanner.py</files>
  <action>
Add a module-level threading.Event flag (or Lock) to routes/scanner.py to prevent concurrent prediction scans.

Implementation:
1. At module level (near the top, after imports): add `_prediction_running = threading.Event()`
2. In `api_predictions_run()`, BEFORE spawning the thread:
   - Check `if _prediction_running.is_set(): return jsonify({"ok": False, "message": "Prediction scan already running."}), 409`
   - Set the flag: `_prediction_running.set()`
3. Inside `_do()`:
   - Wrap the entire body in try/finally
   - In the `finally` block: `_prediction_running.clear()`
4. Keep the existing try/except for error handling inside the try block of the new try/finally

This ensures only one prediction scan thread runs at a time. The 409 response lets the frontend show a "scan in progress" message instead of spawning duplicates.
  </action>
  <verify>
    <automated>python -c "import routes.scanner; print('import ok')"</automated>
  </verify>
  <done>Clicking "Run Prediction Scan" while a scan is already running returns 409 with message. Only one scan thread runs at a time. Flag is always cleared on completion or failure.</done>
</task>

<task type="auto">
  <name>Task 2: Fix autotrade silent failure - relax filter and pre-validate</name>
  <files>routes/trading.py</files>
  <action>
Fix the autotrade endpoint in two ways:

1. RELAX THE FILTER (line 484-486): Change the `ready` list comprehension to:
   - Remove `confidence >= 8` requirement entirely
   - Keep stage filter but expand to include "accumulation" stage as well:
     `ready = [p for p in preds_list if p.get("stage") in ("launch_zone", "pre_breakout", "accumulation")]`
   - Sort by confidence descending so highest-confidence picks go first:
     `ready.sort(key=lambda x: x.get("confidence", 0), reverse=True)`

2. PRE-VALIDATE BEFORE RETURNING (before spawning thread):
   - After the confirm check, read predictions from shared_state snapshot
   - Check if any predictions exist at all: if not, return 400 with "No predictions available. Run a prediction scan first."
   - Apply the same stage filter to check qualifying count
   - If zero qualifying predictions: return 400 with message like "No predictions qualify for auto-trade (need stage: launch_zone, pre_breakout, or accumulation). Found N predictions but none in tradeable stages."
   - If qualifying exist, include count in success response: `{"ok": True, "message": f"Placing up to {min(max_orders, len(qualifying))} order(s) from {len(qualifying)} qualifying predictions..."}`

3. ADD RESULT LOGGING: After the placed loop, add a progress.push_log or update shared_state with the result count so dashboard can show "Auto-trade: placed 2/3 orders" instead of silence.

Do NOT add a concurrency guard here - auto-trade is fast and PDT limits naturally cap it.
  </action>
  <verify>
    <automated>python -c "import routes.trading; print('import ok')"</automated>
  </verify>
  <done>Autotrade endpoint returns 400 with helpful message when no qualifying predictions exist. When predictions qualify, orders are placed for launch_zone/pre_breakout/accumulation stage stocks sorted by confidence. User gets accurate feedback about what will happen.</done>
</task>

</tasks>

<verification>
1. `python -c "import routes.scanner; import routes.trading"` -- both modules import cleanly
2. Manual test: Start server, run prediction scan, click button again immediately -- should get 409
3. Manual test: With predictions loaded, click autotrade -- should either place orders or return 400 with reason
</verification>

<success_criteria>
- Prediction scan endpoint rejects concurrent runs with 409
- Autotrade endpoint pre-validates and returns 400 with helpful message when no predictions qualify
- Autotrade uses relaxed stage filter (launch_zone, pre_breakout, accumulation) without confidence gate
- No silent failures -- user always gets meaningful feedback
</success_criteria>
