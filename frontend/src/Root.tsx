import App from "./App";
import EvaluationApp from "./evaluation/EvaluationApp";
import { useHashRoute } from "./lib/router";

/**
 * Screen switcher.
 *
 * Two independent surfaces share the bundle: the research console (light,
 * document-like, one question at a time) and the evaluation dashboard (dark,
 * dense, many runs at once). They share no state and no chrome — only the
 * link that moves between them — so the split lives here rather than in a
 * shared layout that neither screen would fit comfortably.
 */
export default function Root() {
  const [path] = useHashRoute();

  if (path.startsWith("/evaluation")) {
    return <EvaluationApp />;
  }

  return <App />;
}
