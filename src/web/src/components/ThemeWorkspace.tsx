"use client";

import { useState } from "react";
import { Layers } from "lucide-react";

import { Theme } from "@/lib/api";
import { ThemeForm } from "./ThemeForm";
import { ThemeList } from "./ThemeList";

interface ThemeWorkspaceProps {
  initialThemes: Theme[];
}

export function ThemeWorkspace({ initialThemes }: ThemeWorkspaceProps) {
  const [themes, setThemes] = useState(initialThemes);

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="hero-eyebrow">
            <Layers size={13} aria-hidden />
            Theme research
          </div>
          <h1 className="hero-title gradient-text">Themes</h1>
        </div>
        <span className="metric-chip">{themes.length} saved</span>
      </div>
      <div className="workspace-grid">
        <ThemeForm
          onCreated={(theme) => setThemes((current) => [theme, ...current])}
        />
        <ThemeList themes={themes} />
      </div>
    </div>
  );
}
