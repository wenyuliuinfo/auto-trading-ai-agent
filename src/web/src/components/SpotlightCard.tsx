"use client";

import type { CSSProperties, MouseEvent, ReactNode } from "react";
import { useCallback, useRef } from "react";

interface SpotlightCardProps {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}

export function SpotlightCard({
  children,
  className = "",
  style,
}: SpotlightCardProps) {
  const ref = useRef<HTMLDivElement>(null);

  const handleMouseMove = useCallback((event: MouseEvent<HTMLDivElement>) => {
    const element = ref.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    element.style.setProperty("--spotlight-x", `${event.clientX - rect.left}px`);
    element.style.setProperty("--spotlight-y", `${event.clientY - rect.top}px`);
  }, []);

  return (
    <div
      ref={ref}
      className={`spotlight-card ${className}`.trim()}
      style={style}
      onMouseMove={handleMouseMove}
    >
      {children}
    </div>
  );
}
