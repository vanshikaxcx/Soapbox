/**
 * Also what renders for a resource that exists but isn't owned by the
 * signed-in shopper - the API conceals that distinction as a 404
 * (SPEC/AGENTS.md), and the UI must not un-conceal it with different copy.
 */
export function NotFoundPage() {
  return (
    <div className="pp-page">
      <h1>Not found</h1>
      <p>We couldn't find that. It may not exist, or it may not be available to you.</p>
    </div>
  );
}
