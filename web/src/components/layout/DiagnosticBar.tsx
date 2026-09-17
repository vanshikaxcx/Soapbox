import { useSearchParams } from "react-router-dom";
import { useDiagnosticTraces } from "../../api/ApiProvider";

/** Visible only with `?diagnostic=1` - never shown to an ordinary shopper by default. */
export function DiagnosticBar() {
  const [searchParams] = useSearchParams();
  const traces = useDiagnosticTraces();
  if (searchParams.get("diagnostic") !== "1") {
    return null;
  }
  return (
    <aside className="pp-diagnostic-bar" aria-label="Diagnostic request trace">
      <h2>Diagnostic mode</h2>
      <ul>
        {traces.map((trace, index) => (
          <li key={`${trace.requestId ?? "no-request-id"}-${index}`}>
            {trace.method} {trace.path} → {trace.status} ({trace.durationMs}ms)
            {trace.requestId !== undefined && <span> · {trace.requestId}</span>}
          </li>
        ))}
      </ul>
    </aside>
  );
}
