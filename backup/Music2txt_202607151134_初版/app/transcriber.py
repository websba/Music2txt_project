"""faster-whisper transcription helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from faster_whisper import WhisperModel

ProgressCallback = Callable[[float, str], None]

_model: Optional[WhisperModel] = None
_model_name: Optional[str] = None


def get_model(model_size: str = "small") -> WhisperModel:
    """Load and cache a Whisper model (CPU / int8)."""
    global _model, _model_name
    if _model is None or _model_name != model_size:
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
        _model_name = model_size
    return _model


def transcribe(
    audio_path: str | Path,
    *,
    model_size: str = "small",
    progress_offset: float = 0.0,
    progress_span: float = 1.0,
    on_progress: Optional[ProgressCallback] = None,
) -> str:
    """
    Transcribe an audio file with automatic language detection.

    Progress is reported in [progress_offset, progress_offset + progress_span].
    """
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到音檔：{path}")

    if on_progress:
        on_progress(progress_offset, "載入 Whisper 模型中…")

    model = get_model(model_size)

    if on_progress:
        on_progress(progress_offset + progress_span * 0.15, "開始轉寫…")

    segments_gen, info = model.transcribe(
        str(path),
        language=None,
        task="transcribe",
        vad_filter=True,
        beam_size=5,
    )

    duration = float(info.duration or 0.0)
    texts: list[str] = []
    last_end = 0.0

    for segment in segments_gen:
        text = (segment.text or "").strip()
        if text:
            texts.append(text)
        last_end = max(last_end, float(segment.end or 0.0))
        if on_progress and duration > 0:
            ratio = min(1.0, last_end / duration)
            # Reserve first 15% of span for model load
            value = progress_offset + progress_span * (0.15 + 0.85 * ratio)
            on_progress(value, f"轉寫中… {last_end:.0f}/{duration:.0f} 秒")

    if on_progress:
        on_progress(progress_offset + progress_span, "轉寫完成")

    return "\n".join(texts).strip()
