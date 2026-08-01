import {
  CircleX,
  FileAudio2,
  FileVideo2,
  FolderOpen,
  UploadCloud,
} from "lucide-react";
import { motion } from "motion/react";
import { chooseRecording } from "../lib/backend";
import { SUPPORTED_EXTENSIONS } from "../types";
import { Button, cn } from "./ui";

export function RecordingPicker({
  value,
  onChange,
  dragging,
}: {
  value: string;
  onChange: (value: string) => void;
  dragging: boolean;
}) {
  const filename = value.split(/[\\/]/).pop() ?? value;
  const extension = filename.split(".").pop()?.toLowerCase() ?? "";
  const video = ["mp4", "mov", "mkv", "webm"].includes(extension);
  const valid = !value || SUPPORTED_EXTENSIONS.includes(extension);

  async function browse() {
    const path = await chooseRecording();
    if (path) onChange(path);
  }

  if (value) {
    return (
      <motion.div
        className={cn("recording-selected", !valid && "recording-invalid")}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="file-icon">
          {video ? <FileVideo2 size={25} /> : <FileAudio2 size={25} />}
        </div>
        <div className="file-copy">
          <strong title={filename}>{filename}</strong>
          <span title={value}>{value}</span>
          {!valid && <em>Этот формат пока не поддерживается</em>}
        </div>
        <Button variant="ghost" size="small" onClick={browse}>
          Заменить
        </Button>
        <button
          type="button"
          className="icon-button"
          aria-label="Убрать запись"
          onClick={() => onChange("")}
        >
          <CircleX size={18} />
        </button>
      </motion.div>
    );
  }

  return (
    <motion.button
      type="button"
      className={cn("drop-zone", dragging && "drop-zone-active")}
      onClick={browse}
      animate={dragging ? { scale: 1.006 } : { scale: 1 }}
    >
      <span className="drop-illustration">
        <span className="drop-icon-back">
          <FolderOpen size={28} />
        </span>
        <span className="drop-icon-front">
          <UploadCloud size={27} />
        </span>
      </span>
      <span className="drop-title">
        {dragging ? "Отпустите файл здесь" : "Перетащите запись сюда"}
      </span>
      <span className="drop-subtitle">
        или нажмите, чтобы выбрать аудио или видео
      </span>
      <span className="format-list">
        MP4 · M4A · MP3 · WAV · MOV · MKV · до 5 часов
      </span>
    </motion.button>
  );
}
