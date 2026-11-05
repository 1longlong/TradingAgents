import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getAnnouncements } from "../api/backtestClient";

type AnnouncementsProps = {
  announcements: string[];
  requireAttention: boolean;
  onAcknowledge?: () => void;
};

export function Announcements({
  announcements,
  requireAttention,
  onAcknowledge,
}: AnnouncementsProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(requireAttention);

  useEffect(() => {
    if (!requireAttention) setOpen(false);
  }, [requireAttention]);

  if (announcements.length === 0) return null;

  return (
    <>
      <section
        role="status"
        className="mb-6 rounded-md border border-cyan-500/40 bg-cyan-500/10 px-4 py-3 text-sm text-cyan-100"
      >
        <h2 className="mb-1 font-medium">{t("announcements.title")}</h2>
        <ul className="space-y-1">
          {announcements.map((announcement, index) => (
            <li key={index}>{announcement}</li>
          ))}
        </ul>
      </section>

      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-slate-950/80" />
          <Dialog.Content className="fixed left-1/2 top-1/2 w-[min(32rem,90vw)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-slate-700 bg-slate-900 p-6 text-slate-100 shadow-xl">
            <Dialog.Title className="text-lg font-semibold text-slate-100">
              {t("announcements.title")}
            </Dialog.Title>
            <Dialog.Description className="mt-3 space-y-2 text-sm text-slate-300">
              {announcements.map((announcement, index) => (
                <span key={index} className="block">
                  {announcement}
                </span>
              ))}
            </Dialog.Description>
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                className="rounded-md bg-cyan-400 px-3 py-1.5 text-sm font-medium text-slate-950"
                onClick={() => {
                  setOpen(false);
                  onAcknowledge?.();
                }}
              >
                {t("announcements.acknowledge")}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

export function AnnouncementsGate() {
  const [acknowledged, setAcknowledged] = useState(false);
  const query = useQuery({
    queryKey: ["announcements"],
    queryFn: getAnnouncements,
    retry: false,
  });
  const data = query.data;
  if (!data) return null;
  return (
    <Announcements
      announcements={data.announcements}
      requireAttention={Boolean(data.require_attention) && !acknowledged}
      onAcknowledge={() => setAcknowledged(true)}
    />
  );
}
