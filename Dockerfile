FROM python:3.13-slim

WORKDIR /code

RUN pip install uv

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen

# Bake the cross-encoder weights into the image.
#
# Otherwise the first question of the first run with the cross-encoder
# enabled pays for the download, and the container needs reachable network
# to a third party in the middle of a benchmark. Sits above `COPY . .` so
# editing source does not invalidate this layer.
RUN uv run python -c "from sentence_transformers import CrossEncoder; \
    CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

COPY . .

CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]