"""
Importing the app must not load torch.

torch and transformers are installed -- docling resolves to
docling-slim[standard], which requires torch, torchvision and
docling-ibm-models, and docling-ibm-models requires transformers. Nothing
in the served request path uses either: the cross-encoder is the only
consumer, it imports sentence_transformers inside load_model(), and the
flag that reaches it is set in exactly one place (evaluation_routes),
which portfolio mode does not mount.

They were being imported anyway. langchain_core.language_models.base
feature-detects transformers at module scope:

    try:
        from transformers import GPT2TokenizerFast
        _HAS_TRANSFORMERS = True
    except ImportError:
        _HAS_TRANSFORMERS = False

That probe keys on the package being *installed*, not on anything asking
for it, so `import langchain_openai` pulled the whole stack in. Measured
at 404.5MB resident to import backend.main against 235.3MB with
transformers hidden -- on a 512MB instance that is the difference between
~130MB of headroom and ~300MB, and Render was OOM-restarting the preprod
API under ordinary concurrency.

This is the same failure chunking.py already documents for
langchain_text_splitters. It came back through a different door, which is
why the guard is tested rather than left as a comment.
"""
import json
import os
import subprocess
import sys

import pytest


def _import_and_report(module: str) -> dict:
    """Import `module` in a clean interpreter, report what came with it."""
    program = (
        "import sys, json\n"
        f"import {module}\n"
        "print(json.dumps({"
        "    'torch': 'torch' in sys.modules,"
        "    'transformers': 'transformers' in sys.modules,"
        "}))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env={**os.environ, "DEPLOYMENT_MODE": "portfolio"},
        timeout=300,
    )

    assert result.returncode == 0, (
        f"importing {module} failed:\n{result.stderr[-2000:]}"
    )

    return json.loads(result.stdout.strip().splitlines()[-1])


class TestTheAppDoesNotPayForTorch:
    def test_importing_main_does_not_load_torch(self):
        loaded = _import_and_report("backend.main")

        assert not loaded["torch"], (
            "importing backend.main loaded torch; the guard in "
            "backend/__init__.py is not running early enough, or something "
            "now imports transformers on purpose"
        )

    def test_importing_main_does_not_load_transformers(self):
        loaded = _import_and_report("backend.main")

        assert not loaded["transformers"], (
            "importing backend.main loaded transformers"
        )

    def test_the_graph_alone_does_not_load_torch(self):
        """
        The narrower chain, so a failure says which half moved:
        financial_routes is the only router portfolio mode mounts.
        """
        loaded = _import_and_report("backend.api.financial_routes")

        assert not loaded["torch"]


class TestTheRerankerStillWorks:
    def test_sentence_transformers_is_still_importable(self):
        """
        The guard hides transformers for the duration of one import and
        then removes itself. If it did not, full mode would lose the
        cross-encoder -- sentence_transformers imports transformers, and a
        permanently blocked module would turn reranking into a silent
        no-op via cross_encoder's own except-and-degrade path.
        """
        program = (
            "import backend\n"
            "import transformers\n"
            "print('ok')\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            timeout=300,
        )

        assert result.returncode == 0, (
            "the guard outlived the import it was meant to scope:\n"
            f"{result.stderr[-2000:]}"
        )
