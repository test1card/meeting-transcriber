import * as Dialog from "@radix-ui/react-dialog";
import { Cloud, LockKeyhole, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "./ui";

export function ConsentDialog({
  open,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (remember: boolean) => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild>
              <motion.div
                className="dialog-overlay"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              />
            </Dialog.Overlay>
            <Dialog.Content asChild>
              <motion.div
                className="dialog-content"
                initial={{ opacity: 0, y: 12, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.98 }}
              >
                <Dialog.Close className="icon-button dialog-close" aria-label="Закрыть">
                  <X size={18} />
                </Dialog.Close>
                <div className="dialog-icon">
                  <Cloud size={24} />
                </div>
                <Dialog.Title className="dialog-title">
                  Обработка текста через DeepSeek
                </Dialog.Title>
                <Dialog.Description className="dialog-description">
                  Аудио и видео останутся на этом компьютере. Во внешний API
                  будет отправлен только распознанный текст для сверки,
                  редактирования и подготовки документов.
                </Dialog.Description>
                <div className="privacy-row">
                  <LockKeyhole size={18} />
                  <span>Ключ API не сохраняется в документах или журнале.</span>
                </div>
                <div className="dialog-actions">
                  <Dialog.Close asChild>
                    <Button variant="secondary">Отмена</Button>
                  </Dialog.Close>
                  <Button onClick={() => onConfirm(false)}>
                    Разрешить один раз
                  </Button>
                  <Button variant="primary" onClick={() => onConfirm(true)}>
                    Разрешить и запомнить
                  </Button>
                </div>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}
