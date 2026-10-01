"""Bounded video streaming into Tk, with windowless FFplay audio output."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time

from PIL import Image

WIDTH, HEIGHT, FPS = 640, 360, 24
MAX_DURATION = 90


@dataclass(frozen=True)
class Media:
    path: Path
    duration: float
    video: bool
    audio: bool


def require_tool(name):
    if not shutil.which(name):
        raise RuntimeError(f'{name} is missing. Install the full FFmpeg package (macOS: brew install ffmpeg).')


def inspect_media(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('Media file does not exist.')
    if path.suffix.lower() not in ('.mp4', '.wav'):
        raise ValueError('Open a WAV or MP4 file for playback.')
    require_tool('ffprobe')
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                             'format=duration:stream=codec_type', '-of', 'json', str(path)],
                            capture_output=True, timeout=15)
    if result.returncode:
        raise ValueError('Cannot open media: ' + result.stderr.decode(errors='replace')[-400:])
    data = json.loads(result.stdout)
    duration = float(data.get('format', {}).get('duration', 0))
    streams = {s.get('codec_type') for s in data.get('streams', [])}
    if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
        raise ValueError('Playback supports files up to 90 seconds with a known duration.')
    if not streams.intersection(('video', 'audio')):
        raise ValueError('This file has no playable audio or video.')
    return Media(path, duration, 'video' in streams, 'audio' in streams)


class Player:
    """Control from the Tk thread; a worker supplies at most two video frames.

    Pause/seek restart the audio and video decoders at the saved position. This
    works on macOS, Linux and Windows without native window embedding or signals.
    """
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.media = None
        self.state = 'idle'
        self.video_enabled = False
        self.frames = queue.Queue(maxsize=2)
        self._offset = 0.0
        self._started = None
        self._stop = threading.Event()
        self._thread = None
        self._video = None
        self._audio = None
        self._errors = {}

    @property
    def position(self):
        elapsed = self.clock() - self._started if self._started is not None else 0
        return min(self.media.duration if self.media else 0, self._offset + elapsed)

    def load(self, media):
        self.stop()
        self.media = media
        self.state = 'ready'
        self.video_enabled = media.video

    def _process(self, command, video=False):
        errors = tempfile.TemporaryFile()
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE if video else subprocess.DEVNULL,
                                       stderr=errors)
        except Exception:
            errors.close()
            raise
        self._errors[process] = errors
        return process

    def _error(self, process):
        errors = self._errors[process]
        errors.seek(0)
        return errors.read().decode(errors='replace')[-400:]

    def _halt(self):
        self._stop.set()
        for process in (self._audio, self._video):
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=.3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
        if self._thread is not None:
            self._thread.join(timeout=.3)
        if self._video is not None and (self._thread is None or not self._thread.is_alive()):
            self._video.stdout.close()
        self._thread = self._audio = self._video = None
        for errors in self._errors.values():
            errors.close()
        self._errors.clear()
        while not self.frames.empty():
            try:
                self.frames.get_nowait()
            except queue.Empty:
                break

    def _start_video(self, position, single=False):
        require_tool('ffmpeg')
        command = ['ffmpeg', '-v', 'error', '-nostdin', '-ss', f'{position:.6f}',
                   '-i', str(self.media.path), '-map', '0:v:0', '-an', '-vf',
                   f'fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2',
                   '-pix_fmt', 'rgb24', '-f', 'rawvideo']
        if single:
            command += ['-frames:v', '1']
        command += ['pipe:1']
        self._video = self._process(command, video=True)
        return self._video

    def _pump(self, process, stop, origin, single):
        size = WIDTH * HEIGHT * 3
        index = 0
        try:
            while not stop.is_set():
                data = process.stdout.read(size)
                if len(data) != size:
                    break
                if not single and stop.wait(max(0, origin + index/FPS - self.clock())):
                    break
                if stop.is_set():
                    break
                # Keep the latest two frames, rather than buffering the video.
                if self.frames.full():
                    try:
                        self.frames.get_nowait()
                    except queue.Empty:
                        pass
                self.frames.put_nowait(data)
                index += 1
        finally:
            process.stdout.close()

    def _reader(self, process, single=False):
        self._thread = threading.Thread(target=self._pump,
                                        args=(process, self._stop, self.clock(), single), daemon=True)
        self._thread.start()

    def play(self, position=None, video=True):
        if self.media is None:
            raise ValueError('Open or export a transmission first.')
        if not video and not self.media.audio:
            raise ValueError('This file has no audio track.')
        target = self.position if position is None else float(position)
        if self.state == 'ended' and position is None:
            target = 0
        self._halt()
        self._offset = max(0, min(target, self.media.duration))
        self._started = None
        self._stop = threading.Event()
        self.video_enabled = video and self.media.video
        try:
            if self.video_enabled:
                self._start_video(self._offset)
            if self.media.audio:
                require_tool('ffplay')
                self._audio = self._process(['ffplay', '-hide_banner', '-loglevel', 'error',
                                             '-nostats', '-nodisp', '-vn', '-autoexit',
                                             '-ss', f'{self._offset:.6f}', '-i', str(self.media.path)])
            self._started = self.clock()
            self.state = 'playing'
            if self._video is not None:
                self._reader(self._video)
        except Exception:
            self._halt()
            self.state = 'error'
            raise

    def pause(self):
        if self.state == 'playing':
            position = self.position
            self._halt()
            self._offset, self._started, self.state = position, None, 'paused'

    def resume(self):
        if self.state == 'paused':
            self.play(video=self.video_enabled)

    def seek(self, position):
        if self.media is None:
            return
        target = max(0, min(float(position), max(0, self.media.duration - .001)))
        if self.state == 'playing':
            self.play(target, self.video_enabled)
        else:
            self._halt()
            self._offset, self._started, self.state = target, None, 'paused'
            if self.video_enabled:
                self._stop = threading.Event()
                self._reader(self._start_video(target, single=True), single=True)

    def stop(self):
        self._halt()
        self._offset, self._started = 0, None
        self.state = 'ready' if self.media else 'idle'

    def tick(self):
        frame = None
        while True:
            try:
                frame = self.frames.get_nowait()
            except queue.Empty:
                break
        for process in (self._audio, self._video):
            if process is not None and process.poll() not in (None, 0):
                error = self._error(process)
                self._halt()
                self._started, self.state = None, 'error'
                raise RuntimeError('Playback failed: ' + (error or 'cannot open the media or audio device.'))
        if self.state == 'playing':
            finished = self._audio.poll() == 0 if self._audio is not None else self.position >= self.media.duration
            if finished:
                self._halt()
                self._offset, self._started, self.state = self.media.duration, None, 'ended'
        return Image.frombytes('RGB', (WIDTH, HEIGHT), frame) if frame is not None else None

    def close(self):
        self.stop()
