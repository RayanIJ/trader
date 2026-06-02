import type { HealthStatus } from "@/lib/types";

const COLORS: Record<HealthStatus, string> = {
  OK: "bg-ok",
  DEGRADED: "bg-degraded",
  DOWN: "bg-down",
  UNKNOWN: "bg-gray-500",
};

export function StatusDot({ status }: { status: HealthStatus }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${COLORS[status] ?? "bg-gray-500"}`}
      aria-label={status}
    />
  );
}
