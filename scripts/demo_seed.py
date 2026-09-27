"""Put sample material in the workspace so a demo has something to chew on.

Replace these with real documents from the problem statement's issuing
organisation before judging -- a generic sample reads as a generic entry.
"""

from __future__ import annotations

from config import resolve_path

SAMPLE_INSPECTION = """INSPECTION REPORT - PUMP HOUSE 2
Report no: IR/2026/0912        Date: 12 September 2026
Inspector: [name]              Unit: Crude Distillation

1. Pump P-104B: bearing vibration measured 7.4 mm/s RMS against an alert
   limit of 4.5 mm/s. Trending upward over three readings.
2. Suction line SL-104: insulation damaged over approximately 2 m near
   the support at grid E-7. Surface corrosion visible.
3. Pressure gauge PG-1042: calibration sticker expired 30 June 2026.
4. Housekeeping: oil accumulation under P-104B drip tray.

Recommended: schedule bearing replacement at next available shutdown;
re-insulate SL-104; recalibrate PG-1042 before next run.
"""


def main() -> None:
    root = resolve_path("workspace") / "demo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "inspection_report.txt").write_text(SAMPLE_INSPECTION, encoding="utf-8")
    print(f"Seeded demo material in {root}")
    print("Add a scanned PDF and a P&ID crop here before the run.")


if __name__ == "__main__":
    main()
