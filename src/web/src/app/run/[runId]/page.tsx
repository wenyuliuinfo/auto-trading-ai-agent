import { notFound } from "next/navigation";

import { RunMonitor } from "@/components/RunMonitor";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function RunPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  const status = await api.getRun(runId).catch(() => null);
  if (!status) notFound();
  return <RunMonitor runId={runId} initialStatus={status} />;
}
