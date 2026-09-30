import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Theme } from "@/lib/api";
import { ThemeList } from "../ThemeList";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const theme: Theme = {
  theme_id: "theme-1",
  name: "Grid",
  definition: "Transmission and storage",
  config: {
    sub_exposures: ["smart_grid", "utilities", "battery_storage"],
    factor_weights: { growth: 1.0 },
    screens: {},
    weighting_scheme: "equal_weight",
    validator_enabled: true,
  },
  created_at: "2026-09-29T00:00:00Z",
};

describe("ThemeList", () => {
  it("deletes a theme after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => undefined,
    });
    vi.stubGlobal("fetch", fetchMock);
    const onDeleted = vi.fn();

    render(<ThemeList themes={[theme]} onDeleted={onDeleted} />);
    fireEvent.click(screen.getByRole("button", { name: /delete grid/i }));

    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("theme-1"));
    expect(fetchMock).toHaveBeenCalledWith(
      "/themes/theme-1",
      expect.objectContaining({ method: "DELETE" }),
    );
    vi.unstubAllGlobals();
  });
});
