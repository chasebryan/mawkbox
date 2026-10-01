"""The red trace is drawn from the same PCM samples exported as audio."""
import math
import subprocess
from PIL import Image, ImageDraw
from .signal import RATE

WIDTH, HEIGHT, FPS = 800, 450, 24


def render_frame(audio, index):
    image = Image.new('RGB', (WIDTH, HEIGHT), '#090b0e')
    draw = ImageDraw.Draw(image)
    draw.text((32, 26), 'mawkbox', fill='#f1f3f5')
    draw.text((32, 54), 'AUDIO TRANSMISSION', fill='#717782')
    draw.line((32, 92, WIDTH-32, 92), fill='#272b32')
    draw.line((32, 225, WIDTH-32, 225), fill='#342027')
    start = int(index / FPS * RATE)
    # A 15 ms oscilloscope window, preserving the real tone waveform.
    segment = audio[start:start + 720]
    points = [(32 + i * (WIDTH-64) / 719, 225 - float(value) * 105) for i, value in enumerate(segment)]
    if len(points) > 1:
        draw.line(points, fill='#ff334f', width=2)
    draw.line((32, 358, WIDTH-32, 358), fill='#272b32')
    draw.text((32, 384), '4-FSK   /   200 SYMBOLS/S   /   48 kHz', fill='#9096a0')
    draw.text((650, 384), f'{index/FPS:06.2f}s', fill='#ff334f')
    return image


def render_video(path, audio, wav_path):
    command = ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', 'pipe:0', '-i', str(wav_path),
               '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
               '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-shortest', str(path)]
    # A temporary file prevents stderr pipe backpressure while feeding frames.
    import tempfile
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors) as process:
            try:
                for index in range(math.ceil(len(audio) / RATE * FPS)):
                    process.stdin.write(render_frame(audio, index).tobytes())
            except BrokenPipeError:
                pass
            finally:
                process.stdin.close()
            code = process.wait(timeout=120)
        if code:
            errors.seek(0)
            raise ValueError('Video export failed: ' + errors.read().decode(errors='replace')[-500:])
