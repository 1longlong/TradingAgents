import { ui, useUILanguage } from "../i18n/ui";
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getAnnouncements } from "../api/backtestClient";
import { Icon } from "./Icon";

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
  useUILanguage();
  const { t } = useTranslation();
  const [open, setOpen] = useState(requireAttention);

  useEffect(() => {
    if (!requireAttention) setOpen(false);
  }, [requireAttention]);

  if (announcements.length === 0) return null;

  return (
    <>
      <div className="report-state-banner" role="status">
        <Icon name="bell" />
        <div>
          <strong>{t("announcements.title")}</strong>
          {announcements.map((announcement, index) => (
            <p key={index}>{ui(announcement)}</p>
          ))}
        </div>
      </div>

      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-card">
            <Dialog.Title className="dialog-title">
              {t("announcements.title")}
            </Dialog.Title>
            <Dialog.Description className="dialog-description">
              {announcements.map((announcement, index) => (
                <span key={index} className="block">
                  {ui(announcement)}
                </span>
              ))}
            </Dialog.Description>
            <div className="modal-actions">
              <button
                type="button"
                className="button primary"
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
  useUILanguage();
  const [acknowledged, setAcknowledged] = useState(false);
  const query = useQuery({
    queryKey: ["announcements"],
    queryFn: getAnnouncements,
    retry: false,
  });
  const data = query.data;
  if (!data || !data.require_attention || acknowledged) return null;
  return (
    <Announcements
      announcements={data.announcements}
      requireAttention={Boolean(data.require_attention) && !acknowledged}
      onAcknowledge={() => setAcknowledged(true)}
    />
  );
}
