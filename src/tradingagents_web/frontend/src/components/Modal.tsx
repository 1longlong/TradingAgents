import { useEffect, useRef } from "react";
import { Icon } from "./Icon";
import type { ReactNode } from "react";

type ModalProps = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  closeLabel?: string;
};

export function Modal({
  open,
  title,
  onClose,
  children,
  className,
  closeLabel = "Close dialog",
}: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={`modal ${className ?? ""}`}
      aria-labelledby="modal-title"
      onClose={() => {
        if (open) onClose();
      }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      {open ? (
        <>
          <div className="modal-header">
            <h2 id="modal-title">{title}</h2>
            <button
              type="button"
              className="icon-button"
              aria-label={closeLabel}
              onClick={onClose}
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="modal-body">{children}</div>
        </>
      ) : null}
    </dialog>
  );
}
