"use client";

import { ArrowRight, Boxes, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api, Theme } from "@/lib/api";
import { SpotlightCard } from "./SpotlightCard";

interface ThemeListProps {
  themes: Theme[];
}

export function ThemeList({ themes }: ThemeListProps) {
  const router = useRouter();
  const [runningId, setRunningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runTheme(theme: Theme) {
    setRunningId(theme.theme_id);
    setError(null);
    try {
      const result = await api.triggerRun(theme.theme_id);
      if (!result.run_id) {
        throw new Error("Run response is missing run_id");
      }
      router.push(`/run/${result.run_id}`);
    } catch (err) {
      setRunningId(null);
      setError(err instanceof Error ? err.message : "Failed to start run");
    }
  }

  if (themes.length === 0) {
    return (
      <div className="panel empty-state">
        <Boxes size={22} className="empty-icon" aria-hidden />
        <span>No themes yet.</span>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      {error ? (
        <div className="form-error" role="alert">
          {error}
        </div>
      ) : null}
      {themes.map((theme) => (
        <SpotlightCard key={theme.theme_id} className="panel theme-card">
          <div className="theme-card-row">
            <div className="theme-card-main">
              <div className="theme-name">{theme.name}</div>
              <div className="theme-definition">{theme.definition}</div>
              <div className="chip-row">
                {theme.config.sub_exposures.map((sub) => (
                  <span key={sub} className="chip">
                    {sub}
                  </span>
                ))}
              </div>
            </div>
            <div className="card-actions">
              <button
                className="btn btn-primary"
                onClick={() => void runTheme(theme)}
                disabled={runningId === theme.theme_id}
              >
                <Play size={15} aria-hidden />
                {runningId === theme.theme_id ? "Starting..." : "Run"}
              </button>
              <button className="btn" onClick={() => router.push(`/theme/${theme.theme_id}`)}>
                Open
                <ArrowRight size={15} aria-hidden />
              </button>
            </div>
          </div>
        </SpotlightCard>
      ))}
    </div>
  );
}
