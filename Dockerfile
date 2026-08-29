FROM python:3.13-slim

WORKDIR /code

# System libraries OpenCV links against.
#
# Docling pulls in opencv-python through its table-structure model, and
# the wheel links libxcb.so.1, libGL.so.1 and libglib -- none of which
# python:3.13-slim ships. Without them `import cv2` raises at the moment
# the first document is parsed, which also leaves Docling reporting "no
# OCR engine found", because rapidocr imports cv2 too.
#
# Verified with ldd rather than guessed: every one of these is named in
# cv2's link table. (opencv-python-headless would remove the need for
# them and shrink the image, but it means overriding a transitive
# dependency Docling declares itself.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libxcb1 \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

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

# Bake Docling's layout, table and OCR weights in, for the same reason.
#
# The ingestion worker parses an uploaded filing the moment it lands. If
# the models are not already here it downloads them mid-message, which
# means the first upload after every deploy is slow and needs reachable
# network to a third party -- and a Fargate task in a private subnet may
# not have one.
RUN uv run docling-tools models download layout tableformer rapidocr

COPY . .

CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]