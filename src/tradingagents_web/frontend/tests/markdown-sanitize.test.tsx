import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "../src/components/Markdown";

describe("Markdown sanitization", () => {
  it("does not render executable script tags", () => {
    const { container } = render(
      <Markdown>{"<script>alert(1)</script>\n\nsafe text"}</Markdown>,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(/safe text/)).toBeInTheDocument();
  });

  it("does not keep javascript: links", () => {
    render(<Markdown>{"[click](javascript:alert(1))"}</Markdown>);
    const link = screen.queryByRole("link");
    expect(link?.getAttribute("href") ?? "").not.toMatch(/^javascript:/i);
  });
});
