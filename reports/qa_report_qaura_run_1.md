# QA Report for QAura Run 1

---

**Generated at:** 2026-06-26T17:50:27.750539+00:00

---

## Executive Summary
The test run for the QAura Demo Store completed with most functionality working as expected. Out of 12 tests, 11 passed successfully, while 1 test failed due to an issue in the order calculation logic. The critical path of the application remains intact, ensuring core functionality is unaffected.

---

## Execution Metrics

| Metric               | Value |
|----------------------|-------|
| Total Tests          | 12    |
| Passed               | 11    |
| Failed               | 1     |
| Blocked              | 0     |
| Duration (ms)        | 350   |
| Critical Path Success| True  |

---

## Coverage Confidence

**Overall Confidence Score:** 0.92

### Per-Component Scores

| Component                 | Score |
|--------------------------|-------|
| Order Calculation Logic  | 0.92  |

### Identified Gaps
- No significant coverage gaps were identified in this run.

---

## Anomaly Log

| ID       | Component                 | Classification       | Root Cause Hypothesis                                                                                     |
|----------|---------------------------|----------------------|-----------------------------------------------------------------------------------------------------------|
| ANOM-001 | Order Calculation Logic   | APPLICATION_DEFECT   | The order total calculation logic is incorrectly applying discounts or taxes when the discount exceeds the subtotal. This results in an incorrect final amount. |

---

## Risk Verdict
**PASS_WITH_WARNINGS** – The critical path remains successful, but a non-critical defect was identified in the order calculation logic.