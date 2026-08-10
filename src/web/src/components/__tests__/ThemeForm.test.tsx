import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThemeForm } from "../ThemeForm";

describe("ThemeForm", () => {
  it("posts a theme without a factor_weights field", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        theme_id: "abc",
        name: "Grid",
        definition: "def",
        config: {},
        created_at: "now",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const onCreated = vi.fn();
    render(<ThemeForm onCreated={onCreated} />);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Grid" } });
    fireEvent.change(screen.getByLabelText("Definition"), { target: { value: "Grid def" } });
    fireEvent.change(screen.getByLabelText("Sub-exposures (comma separated)"), {
      target: { value: "smart_grid, utilities" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create theme/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.sub_exposures).toEqual(["smart_grid", "utilities"]);
    expect(body).not.toHaveProperty("factor_weights");
    vi.unstubAllGlobals();
  });
});
