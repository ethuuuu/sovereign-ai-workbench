# Demo run sheet

About nine minutes. Run `python scripts/preflight.py` immediately before.
Green on all five, or do not start.

**0. Open cold (30s).** Wi-Fi off, visibly. Show the top bar: endpoint on
loopback, models loaded, external calls 0. Run `pytest tests/test_no_egress.py`
live — it takes two seconds and anyone in the room can check it.

**1. Model auto-selection (90s).** Two requests back to back.
- *"Summarise the key safety clauses in the hot work permit SOP."* → trace
  shows `document_drafting`, routed to the general model.
- *"Write a Python function to compute pipe wall thickness per ASME B31.3
  and test it."* → trace shows `code_generation`, routed to the coder model.

Same system, no user input on model choice, reason string on screen both times.

**2. Agentic task end to end (3m).** Upload the scanned inspection report.
The trace runs visibly: ingest and OCR, extract findings, search the
knowledge base for the governing clause, draft the approval note, verify,
write the `.docx`. Open the file in Word on stage.

**3. Coding task verified in the sandbox (2m).** Ask for something with a
real edge case — a flow-rate calculation with unit conversion. The model
writes it, the sandbox runs the tests, one fails, the traceback comes back,
it repairs, tests pass. Say beforehand that the failure is the interesting
part.

**4. Multimodal (90s).** Upload a P&ID crop. Ask what equipment is shown and
what the title block says. State the limit out loud — tags and title blocks
yes, full line tracing no.

**5. Close (30s).** Back to the bar: external calls still 0. Open the audit
log and scroll it. "This is what the compliance officer gets."

## Hygiene

- Pre-warm the models. Cold first-token latency will kill the pacing.
- Pre-ingest the knowledge base. Never index live.
- Keep a screen recording of a full successful run on the machine. If the
  live run fails, show the recording and keep talking. Do not debug in
  front of a panel.
- Keep a known-good `.docx` and `.xlsx` from a previous run on the desktop.
