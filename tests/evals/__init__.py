"""Golden-file evaluation tests for LLM pipeline agents.

These tests call live Azure AI Foundry agents and validate their outputs
against structural invariants and pre-captured golden inputs.

They are marked with ``@pytest.mark.eval`` and require:

1. Pre-captured golden inputs in ``data/golden/<workbook_name>/``
2. A running Azure AI Foundry project (``PROJECT_ENDPOINT`` env var)

Run only eval tests::

    pytest -m eval

Capture or refresh golden inputs from sample workbooks::

    python -m tests.evals.capture_golden_inputs
"""
