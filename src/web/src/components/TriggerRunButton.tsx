"use client";

import { Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/api";

export function TriggerRunButton({ themeId }: { themeId: string }) {
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const result = await api.triggerRun(themeId);
      if (!result.run_id) {
        throw new Error("Run response is missing run_id");
      }
      router.push(`/run/${result.run_id}`);
    } catch (err) {
      setStarting(false);
      setError(err instanceof Error ? err.message : "Failed to start run");
    }
  }

  return (
    <>
      <button className="btn btn-primary" onClick={() => void start()} disabled={starting}>
        <Play size={15} aria-hidden />
        {starting ? "Starting..." : "Start run"}
      </button>
      {error ? (
        <div className="form-error" role="alert">
          {error}
        </div>
      ) : null}
    </>
  );
}
