import "./RetrievalPipelineDiagram.css";

/**
 * The retrieval path this run actually took.
 *
 * The run head reports the pipeline as a pill reading "RRF + CE", which
 * names the arm without saying what it did. Two stages are optional and
 * they compose, so the interesting thing about a run is which boxes were
 * in the path — drawn dim when the flags left them out.
 */
export function RetrievalPipelineDiagram({
  run,
}: {
  run: { rrf_enabled?: boolean; cross_encoder_enabled?: boolean };
}) {
  const rrf = Boolean(run.rrf_enabled);
  const crossEncoder = Boolean(run.cross_encoder_enabled);

  // Lexical retrieval exists only to give fusion a second ranking to fuse.
  const stages = [
    { key: "vector", label: "pgvector", detail: "dense top-k", on: true },
    { key: "bm25", label: "BM25", detail: "corpus-wide lexical", on: rrf },
    { key: "rrf", label: "RRF", detail: "fuse by rank", on: rrf },
    {
      key: "ce",
      label: "Cross-encoder",
      detail: "ms-marco-MiniLM-L-6-v2",
      on: crossEncoder,
    },
    { key: "answer", label: "Evidence", detail: "to the graph", on: true },
  ];

  return (
    <div className="ev-pipe">
      <ol className="ev-pipe__flow">
        {stages.map((stage, index) => (
          <li
            key={stage.key}
            className={`ev-pipe__stage${
              stage.on ? "" : " ev-pipe__stage--off"
            }`}
          >
            <div className="ev-pipe__box">
              <span className="ev-pipe__label">{stage.label}</span>
              <span className="ev-pipe__detail">{stage.detail}</span>
            </div>

            {index < stages.length - 1 && (
              <span className="ev-pipe__arrow" aria-hidden="true">
                &rarr;
              </span>
            )}
          </li>
        ))}
      </ol>

      <p className="ev-pipe__caption">{captionFor(rrf, crossEncoder)}</p>
    </div>
  );
}


/** Says which stages ran, rather than describing the styling. */
function captionFor(rrf: boolean, crossEncoder: boolean): string {
  if (rrf && crossEncoder) {
    return "Full pipeline: every stage ran.";
  }

  if (rrf) {
    return "Fusion only. The cross-encoder rerank was disabled.";
  }

  if (crossEncoder) {
    return "Rerank only. Lexical retrieval and fusion were disabled.";
  }

  return "Baseline: dense retrieval only. Neither optional stage ran.";
}
