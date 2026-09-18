"""Demucs vocal separation helpers."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

from demucs.api import Separator, save_audio

ProgressCallback = Callable[[float, str], None]

_separator: Optional[Separator] = None
_separator_name: Optional[str] = None


def _get_separator(model_name: str = "htdemucs") -> Separator:
    global _separator, _separator_name
    if _separator is None or _separator_name != model_name:
        _separator = Separator(model=model_name, device="cpu", progress=False)
        _separator_name = model_name
    return _separator


def separate_vocals(
    audio_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    model_name: str = "htdemucs",
    progress_offset: float = 0.0,
    progress_span: float = 1.0,
    on_progress: Optional[ProgressCallback] = None,
) -> Path:
    """
    Separate vocals from a mixed track and return path to vocals wav.

    Caller is responsible for deleting the returned file / output_dir when done.
    """
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到音檔：{path}")

    last_ratio = 0.0

    def _demucs_callback(info: dict) -> None:
        nonlocal last_ratio
        if on_progress is None:
            return
        audio_length = info.get("audio_length") or 0
        offset = info.get("segment_offset") or 0
        if audio_length <= 0:
            return
        ratio = min(1.0, float(offset) / float(audio_length))
        if ratio < last_ratio:
            return
        last_ratio = ratio
        # Map demucs work into 20%–85% of the assigned span
        value = progress_offset + progress_span * (0.2 + 0.65 * ratio)
        on_progress(value, "分離人聲中…")

    if on_progress:
        on_progress(progress_offset, "載入 Demucs 模型中…")

    separator = _get_separator(model_name)
    separator.update_parameter(callback=_demucs_callback)

    if on_progress:
        on_progress(progress_offset + progress_span * 0.15, "讀取音軌中…")

    _origin, stems = separator.separate_audio_file(path)
    if "vocals" not in stems:
        raise RuntimeError(f"模型未提供 vocals 音軌，可用：{list(stems.keys())}")

    if on_progress:
        on_progress(progress_offset + progress_span * 0.9, "匯出人聲檔中…")

    if output_dir is None:
        out_root = Path(tempfile.mkdtemp(prefix="music2txt_vocals_"))
    else:
        out_root = Path(output_dir)
        out_root.mkdir(parents=True, exist_ok=True)

    vocals_path = out_root / f"{path.stem}_vocals.wav"
    save_audio(stems["vocals"], str(vocals_path), samplerate=separator.samplerate)

    if on_progress:
        on_progress(progress_offset + progress_span, "人聲分離完成")

    return vocals_path


def cleanup_path(path: str | Path | None) -> None:
    """Remove a temp file or its parent temp directory when safe."""
    if path is None:
        return
    p = Path(path)
    try:
        if p.is_file():
            parent = p.parent
            p.unlink(missing_ok=True)
            if parent.name.startswith("music2txt_vocals_"):
                shutil.rmtree(parent, ignore_errors=True)
        elif p.is_dir() and p.name.startswith("music2txt_vocals_"):
            shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass
