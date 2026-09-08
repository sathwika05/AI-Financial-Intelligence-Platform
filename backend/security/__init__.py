"""Request-path security for the analyst query endpoint.

Every layer here is measured in microseconds against a pipeline that takes
roughly 10 to 45 seconds, so the cost of running them is not the thing to weigh.
What matters is false positives: this endpoint takes finance questions, and
a filter that blocks a legitimate one costs an answer.
"""
