import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";

import i18n from "../src/i18n";
import { unimplemented } from "./iteration3-support";

type AnnouncementsProps = {
  announcements: string[];
  requireAttention: boolean;
  onAcknowledge?: () => void;
};

type AnnouncementsModule = {
  Announcements: (props: AnnouncementsProps) => ReactElement;
};

const modules = import.meta.glob<AnnouncementsModule>(
  "../src/components/Announcements.tsx",
);

async function loadAnnouncements(): Promise<AnnouncementsModule> {
  const loader = modules["../src/components/Announcements.tsx"];
  if (!loader) unimplemented("src/components/Announcements.tsx");
  return loader();
}

function renderAnnouncements(
  Announcements: AnnouncementsModule["Announcements"],
  props: AnnouncementsProps,
) {
  return render(
    <I18nextProvider i18n={i18n}>
      <Announcements {...props} />
    </I18nextProvider>,
  );
}

describe("Announcements", () => {
  it("renders non-blocking announcements as a banner", async () => {
    const { Announcements } = await loadAnnouncements();
    render(
      <I18nextProvider i18n={i18n}>
        <Announcements
          announcements={["Scheduled maintenance"]}
          requireAttention={false}
        />
      </I18nextProvider>,
    );
    expect(screen.getByText(/Scheduled maintenance/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("blocks on require_attention until acknowledged", async () => {
    const { Announcements } = await loadAnnouncements();
    const onAcknowledge = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <Announcements
          announcements={["Read this"]}
          requireAttention
          onAcknowledge={onAcknowledge}
        />
      </I18nextProvider>,
    );

    const dialog =
      screen.queryByRole("alertdialog") ?? screen.queryByRole("dialog");
    expect(dialog).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /acknowledge/i }));
    expect(onAcknowledge).toHaveBeenCalledTimes(1);
  });

  it("renders announcement markup as inert text", async () => {
    const { Announcements } = await loadAnnouncements();
    const { container } = renderAnnouncements(Announcements, {
      announcements: ["<script>alert(1)</script>", "<img src=x onerror=1>"],
      requireAttention: false,
    });
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/alert\(1\)/)).toBeInTheDocument();
  });
});
