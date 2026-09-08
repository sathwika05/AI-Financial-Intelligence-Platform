"""
Keep torch out of a process that never asks for it.

langchain_core.language_models.base feature-detects transformers at module
scope, with a bare try/import, to decide whether it can offer GPT-2 token
counting:

    try:
        from transformers import GPT2TokenizerFast
        _HAS_TRANSFORMERS = True
    except ImportError:
        _HAS_TRANSFORMERS = False

The probe keys on transformers being *installed*, not on anything wanting
it. It is installed here transitively -- docling resolves to
docling-slim[standard], which requires torch, torchvision and
docling-ibm-models, and docling-ibm-models requires transformers -- so the
probe always succeeded and `import langchain_openai` loaded transformers
and torch on every start. 404.5MB resident to import backend.main, against
235.3MB without them.

Nothing served uses either. The cross-encoder is the only consumer and it
imports sentence_transformers inside load_model(); the flag that reaches
it is set in one place, evaluation_routes, which portfolio mode does not
mount. So the 512MB preprod instance spent ~170MB holding a library it
could not reach, and Render OOM-restarted it under ordinary concurrency.

Hiding transformers for the duration of that one import leaves
_HAS_TRANSFORMERS False. The only thing that costs is
BaseLanguageModel.get_num_tokens falling back to a character heuristic,
which nothing in this codebase calls -- token counts come from the
provider, through usage_tracker.

The guard removes itself afterwards, so full mode's reranker still works:
sentence_transformers imports transformers, and a permanently blocked
module would turn reranking into a silent no-op through cross_encoder's
own except-and-degrade path.

This is the second time this has happened. chunking.py documents the
first, through langchain_text_splitters, and fixed it by deferring the
import it owned. This one is inside a third-party module at its own import
time, so there is nothing local to defer -- hence a guard, and a test
(test_app_imports_without_torch.py) rather than a comment.
"""
from __future__ import annotations

import sys

# The module whose import-time probe is the thing being scoped. Importing
# it here, deliberately, is what pins _HAS_TRANSFORMERS to False before any
# langchain entry point can pin it to True.
_PROBING_MODULE = "langchain_core.language_models.base"

_HIDDEN = "transformers"


class _HideModule:
    """A meta-path finder that refuses one package and defers on the rest."""

    def __init__(self, name: str):
        self._name = name
        self._prefix = f"{name}."

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self._name or fullname.startswith(self._prefix):
            # The import system does not catch this; it surfaces at the
            # import statement, which is where langchain_core's except
            # clause is waiting.
            raise ImportError(
                f"{fullname} is hidden while {_PROBING_MODULE} is imported"
            )

        # Every other name: no opinion, let the real finders answer.
        return None


def hide_transformers_from_langchain() -> None:
    """Import langchain_core's LLM base with transformers hidden."""
    if _PROBING_MODULE in sys.modules:
        # Something imported it first and the flag is already decided.
        # Blocking now would achieve nothing and only cost an import.
        return

    if _HIDDEN in sys.modules:
        # Already loaded on purpose. Hiding it would be a lie, and the
        # memory is spent either way.
        return

    finder = _HideModule(_HIDDEN)

    sys.meta_path.insert(0, finder)

    try:
        __import__(_PROBING_MODULE)
    except ImportError:
        # langchain_core is not installed, or moved this module. Either way
        # there is nothing to guard and an app that needs it will fail on
        # its own import with a better message than this one could give.
        pass
    finally:
        sys.meta_path.remove(finder)
