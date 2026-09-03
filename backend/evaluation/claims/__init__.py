"""
Claim-level grounding: what the answer asserted, and whether the evidence
supports it.

Separate from the RAGAS evaluator, and deliberately outside the benchmark's
pass/fail. RAGAS scores an answer as a whole against a judge's notion of
faithfulness; this counts individual assertions and reports how many the
run's own evidence supports. The second number is the one a financial
system is actually accountable for.
"""
