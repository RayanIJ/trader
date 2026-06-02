// Visible stubs for dashboard sections delivered in later phases. Keeping them
// present (rather than hidden) makes the roadmap explicit in the UI.

export function PhasePlaceholder({
  title,
  phase,
  note,
}: {
  title: string;
  phase: string;
  note: string;
}) {
  return (
    <section className="rounded-lg border border-dashed border-panelborder bg-panel/40 p-4">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">
          {title}
        </h2>
        <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] font-semibold text-gray-400">
          {phase}
        </span>
      </div>
      <p className="text-xs text-gray-600">{note}</p>
    </section>
  );
}
