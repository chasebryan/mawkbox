import argparse
import sys
from getpass import getpass
from importlib import import_module
from pathlib import Path
from .signal import pack, modulate, write_wav, decode


def launch_gui():
    try:
        gui = import_module('.gui', __package__)
    except ModuleNotFoundError as exc:
        if exc.name not in ('tkinter', '_tkinter'):
            raise
        if sys.platform == 'darwin':
            version = f'{sys.version_info[0]}.{sys.version_info[1]}'
            hint = f'For Homebrew Python, run: brew install python-tk@{version}'
        elif sys.platform.startswith('linux'):
            hint = 'Install Tk for your Python: sudo apt install python3-tk (Debian/Ubuntu) or sudo dnf install python3-tkinter (Fedora).'
        else:
            hint = 'Install Python with Tcl/Tk support enabled, then recreate the virtual environment if you change Python installations.'
        raise RuntimeError(f'Tk is required for the desktop window. {hint}\nVerify with: python -m tkinter\nThen run mawkbox again.') from exc
    gui.launch()


def main():
    parser = argparse.ArgumentParser(description='mawkbox — text to audiovisual signal and back')
    sub = parser.add_subparsers(dest='command')
    encode = sub.add_parser('encode')
    encode.add_argument('message')
    encode.add_argument('-o', '--output', default='transmission')
    encode.add_argument('--plain', action='store_true', help='encode without encryption')
    encode.add_argument('--video', action='store_true', help='also export MP4')
    dec = sub.add_parser('decode')
    dec.add_argument('file')
    dec.add_argument('--plain', action='store_true', help='do not prompt for passphrase')
    sub.add_parser('gui')
    args = parser.parse_args()
    try:
        if args.command in (None, 'gui'):
            launch_gui()
        elif args.command == 'encode':
            password = None if args.plain else getpass('Passphrase: ')
            frame = pack(args.message, password)
            audio = modulate(frame)
            base = Path(args.output)
            base.with_suffix('.mawkbox').write_bytes(frame)
            wav = base.with_suffix('.wav')
            write_wav(wav, audio)
            if args.video:
                from .video import render_video
                render_video(base.with_suffix('.mp4'), audio, wav)
            print(f'Exported {base} (.mawkbox, .wav' + (', .mp4)' if args.video else ')'))
        else:
            print(decode(args.file, None if args.plain else getpass('Passphrase: ')))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f'mawkbox: {exc}\n')


if __name__ == '__main__':
    main()
