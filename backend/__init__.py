# Runs before any backend module, which is the only placement that works:
# the thing being prevented happens at langchain_core's own import time,
# and main.py is not the only entry point -- the worker and the tests
# import backend.* directly.
#
# See _transformers_guard for what this is and why it is not a comment.
from backend._transformers_guard import hide_transformers_from_langchain

hide_transformers_from_langchain()
