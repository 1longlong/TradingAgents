import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "../src/components/Markdown";

// REQ-WEB-009/021, ADR-003, INV-WEB-012: containment keeps table semantics and sanitization.
describe("Markdown report tables", () => {
  it("keeps every column inside a keyboard-accessible scroll region", () => {
    const headers = Array.from({ length: 12 }, (_, index) => `Column ${index}`);
    const table = `| ${headers.join(" | ")} |\n| ${headers.map(() => "---").join(" | ")} |\n| ${headers.map(() => "Long evidence " + "x".repeat(200)).join(" | ")} |`;
    const { container } = render(<Markdown>{table}</Markdown>);
    const region = container.querySelector(".markdown-table-scroll")!;
    expect(region).toHaveAttribute("role", "region");
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region.querySelectorAll("th")).toHaveLength(12);
    expect(region.querySelectorAll("td")).toHaveLength(12);
    expect(region.querySelector("td")?.textContent).toContain("x".repeat(200));
  });

  it("still removes unsafe HTML and URLs inside table cells", () => {
    const { container } = render(
      <Markdown>
        {
          "| Evidence | Link |\n| --- | --- |\n| <script>alert(1)</script> | [unsafe](javascript:alert(1)) |"
        }
      </Markdown>,
    );
    expect(
      container.querySelector(".markdown-table-scroll table"),
    ).not.toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(
      container.querySelector("a")?.getAttribute("href") ?? "",
    ).not.toMatch(/^javascript:/i);
  });
});

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
