"""Save transmissions without depending on media inspection or playback."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from .playback import Media
from .signal import pack, modulate, write_wav, RATE


@dataclass(frozen=True)
class ExportResult:
    media: Media
    audio: np.ndarray
    files: tuple[Path, ...]


def export_transmission(path, message, password=None, video=False):
    frame = pack(message, password)
    audio = modulate(frame)
    suffix = '.mp4' if video else '.wav'
    output = Path(path).absolute()
    if output.suffix.lower() != suffix:
        output = output.with_name(output.name + suffix)
    wav = output.with_suffix('.wav') if video else output
    native = output.with_suffix('.mawkbox')
    write_wav(wav, audio)
    native.write_bytes(frame)
    files = (wav, native)
    if video:
        from .video import render_video
        render_video(output, audio, wav)
        files = (output, *files)
    # We generated this audio, so its format/duration are already known.
    # Successful WAV saving must not depend on ffprobe or a speaker device.
    return ExportResult(Media(output, len(audio)/RATE, video, True), audio, files)
