import { notFound } from "next/navigation";
import { Layers, SlidersHorizontal } from "lucide-react";

import { TriggerRunButton } from "@/components/TriggerRunButton";
import { SpotlightCard } from "@/components/SpotlightCard";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ThemePage({
  params,
}: {
  params: Promise<{ themeId: string }>;
}) {
  const { themeId } = await params;
  const theme = await api.getTheme(themeId).catch(() => null);
  if (!theme) notFound();

  return (
    <div>
      <div className="theme-head">
        <div>
          <div className="hero-eyebrow">Theme profile</div>
          <h1 className="hero-title gradient-text">{theme.name}</h1>
          <p className="hero-lead">{theme.definition}</p>
        </div>
        <TriggerRunButton themeId={themeId} />
      </div>
      <div className="theme-detail-grid">
        <SpotlightCard className="panel panel-pad">
          <div className="panel-heading">
            <div className="icon-box">
              <Layers size={15} aria-hidden />
            </div>
            <div className="panel-title">Sub-exposures</div>
          </div>
          <div className="chip-row" style={{ marginTop: 0 }}>
            {theme.config.sub_exposures.map((sub) => (
              <span key={sub} className="chip">
                {sub}
              </span>
            ))}
          </div>
        </SpotlightCard>
        <SpotlightCard className="panel panel-pad">
          <div className="panel-heading">
            <div className="icon-box">
              <SlidersHorizontal size={15} aria-hidden />
            </div>
            <div className="panel-title">Factor weights</div>
          </div>
          <div className="weight-list">
            {Object.entries(theme.config.factor_weights).map(([name, weight]) => (
              <div className="weight-row" key={name}>
                <span className="weight-name">{name}</span>
                <span className="weight-value">{weight.toFixed(2)}</span>
                <div className="weight-track">
                  <div
                    className="weight-fill"
                    style={{ width: `${Math.max(0, Math.min(100, weight * 100))}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </SpotlightCard>
      </div>
    </div>
  );
}
