"""tkinter UI for offline MP3 transcription."""

from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
from tkinter import (
    END,
    BooleanVar,
    StringVar,
    Tk,
    filedialog,
    messagebox,
    ttk,
)
from tkinter.scrolledtext import ScrolledText

from app.transcriber import transcribe
from app.vocal_separator import cleanup_path, separate_vocals

MODE_MEETING = "會議講話"
MODE_SONG = "歌曲（帶伴奏）"


class TranscriptionApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("MP3 離線轉文字")
        self.root.minsize(720, 520)
        self.root.geometry("820x600")

        self.file_path = StringVar(value="")
        self.mode = StringVar(value=MODE_MEETING)
        self.status = StringVar(
            value="請開啟音檔。首次使用會下載模型（之後可完全離線）。"
        )
        self.busy = BooleanVar(value=False)
        self._msg_queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None

        self._build()
        self.root.after(100, self._poll_queue)

    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        tip = ttk.Label(
            main,
            text=(
                "離線轉寫：會議可直接轉；歌曲模式會先分離人聲再轉寫。"
                "支援中英混合。建議本機已安裝 FFmpeg。"
            ),
            wraplength=760,
            justify="left",
        )
        tip.pack(fill="x", **pad)

        file_row = ttk.Frame(main)
        file_row.pack(fill="x", **pad)
        ttk.Button(file_row, text="開啟檔案", command=self._open_file).pack(
            side="left"
        )
        self.file_label = ttk.Label(file_row, textvariable=self.file_path)
        self.file_label.pack(side="left", padx=10, fill="x", expand=True)

        mode_row = ttk.Frame(main)
        mode_row.pack(fill="x", **pad)
        ttk.Label(mode_row, text="模式：").pack(side="left")
        ttk.Radiobutton(
            mode_row, text=MODE_MEETING, variable=self.mode, value=MODE_MEETING
        ).pack(side="left", padx=6)
        ttk.Radiobutton(
            mode_row, text=MODE_SONG, variable=self.mode, value=MODE_SONG
        ).pack(side="left", padx=6)

        action_row = ttk.Frame(main)
        action_row.pack(fill="x", **pad)
        self.start_btn = ttk.Button(
            action_row, text="開始轉檔", command=self._start
        )
        self.start_btn.pack(side="left")
        self.progress = ttk.Progressbar(
            action_row, orient="horizontal", mode="determinate", maximum=100
        )
        self.progress.pack(side="left", fill="x", expand=True, padx=12)

        ttk.Label(main, textvariable=self.status).pack(fill="x", **pad)

        ttk.Label(main, text="轉寫結果：").pack(anchor="w", padx=12)
        self.text = ScrolledText(main, wrap="word", height=18, font=("Microsoft JhengHei UI", 11))
        self.text.pack(fill="both", expand=True, padx=12, pady=6)

        btn_row = ttk.Frame(main)
        btn_row.pack(fill="x", **pad)
        ttk.Button(btn_row, text="複製全文", command=self._copy_text).pack(
            side="left"
        )
        ttk.Button(btn_row, text="另存為 .txt", command=self._save_text).pack(
            side="left", padx=8
        )

    def _set_busy(self, busy: bool) -> None:
        self.busy.set(busy)
        state = "disabled" if busy else "normal"
        self.start_btn.configure(state=state)

    def _open_file(self) -> None:
        if self.busy.get():
            return
        path = filedialog.askopenfilename(
            title="選擇音檔",
            filetypes=[
                ("音訊檔", "*.mp3 *.wav *.m4a *.flac *.ogg"),
                ("MP3", "*.mp3"),
                ("WAV", "*.wav"),
                ("所有檔案", "*.*"),
            ],
        )
        if path:
            self.file_path.set(path)
            self.status.set(f"已選擇：{Path(path).name}")

    def _start(self) -> None:
        if self.busy.get():
            return
        path = self.file_path.get().strip()
        if not path:
            messagebox.showwarning("尚未選檔", "請先按「開啟檔案」選擇音檔。")
            return
        if not Path(path).is_file():
            messagebox.showerror("檔案不存在", f"找不到檔案：\n{path}")
            return

        self._set_busy(True)
        self.progress["value"] = 0
        self.text.delete("1.0", END)
        self.status.set("準備轉檔…")
        mode = self.mode.get()

        self._worker = threading.Thread(
            target=self._run_job,
            args=(path, mode),
            daemon=True,
        )
        self._worker.start()

    def _run_job(self, path: str, mode: str) -> None:
        vocals_path: Path | None = None
        try:

            def on_progress(value: float, message: str) -> None:
                self._msg_queue.put(
                    ("progress", max(0.0, min(100.0, value * 100.0)), message)
                )

            audio_for_asr = path
            if mode == MODE_SONG:
                # 歌曲：人聲分離 40% +（載入模型 + 轉寫）60%
                vocals_path = separate_vocals(
                    path,
                    progress_offset=0.0,
                    progress_span=0.40,
                    on_progress=on_progress,
                )
                audio_for_asr = str(vocals_path)
                asr_offset, asr_span = 0.40, 0.60
            else:
                # 會議：載入模型 + 轉寫 共 100%
                asr_offset, asr_span = 0.0, 1.0

            text = transcribe(
                audio_for_asr,
                model_size="small",
                progress_offset=asr_offset,
                progress_span=asr_span,
                on_progress=on_progress,
            )
            self._msg_queue.put(("done", text))
        except Exception as exc:  # noqa: BLE001 - surface any worker failure in UI
            detail = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            self._msg_queue.put(("error", str(exc), detail))
        finally:
            cleanup_path(vocals_path)

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, value, message = msg
                    self.progress["value"] = value
                    self.status.set(message)
                elif kind == "done":
                    _, text = msg
                    self.text.delete("1.0", END)
                    self.text.insert("1.0", text or "(沒有辨識到語音內容)")
                    self.progress["value"] = 100
                    self.status.set("轉檔完成")
                    self._set_busy(False)
                elif kind == "error":
                    _, err, detail = msg
                    self.status.set("轉檔失敗")
                    self._set_busy(False)
                    messagebox.showerror(
                        "轉檔失敗",
                        f"{err}\n\n若為歌曲/MP3 讀取問題，請確認已安裝 FFmpeg 並加入 PATH。",
                    )
                    print(detail)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _copy_text(self) -> None:
        content = self.text.get("1.0", END).strip()
        if not content:
            messagebox.showinfo("複製", "文字框是空的。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.status.set("已複製到剪貼簿")

    def _save_text(self) -> None:
        content = self.text.get("1.0", END).strip()
        if not content:
            messagebox.showinfo("另存", "文字框是空的。")
            return
        default_name = "transcript.txt"
        src = self.file_path.get().strip()
        if src:
            default_name = f"{Path(src).stem}.txt"
        out = filedialog.asksaveasfilename(
            title="另存轉寫結果",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("文字檔", "*.txt"), ("所有檔案", "*.*")],
        )
        if not out:
            return
        Path(out).write_text(content, encoding="utf-8")
        self.status.set(f"已儲存：{out}")


def run_app() -> None:
    root = Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:  # noqa: BLE001
        pass
    TranscriptionApp(root)
    root.mainloop()
