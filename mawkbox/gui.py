"""A single compact desktop workspace; all processing stays local."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk
from .exports import export_transmission
from .playback import Player, inspect_media
from .signal import validate_message, decode, read_audio, RATE

BG, PANEL, RED, FG = '#090b0e', '#13161c', '#ff334f', '#edf0f4'


def timestamp(seconds):
    return f'{int(seconds)//60:02d}:{seconds%60:04.1f}'


class Workspace:
    def __init__(self, root):
        self.root, self.events = root, queue.Queue()
        self.player = Player()
        self.audio = None
        self.busy = False
        self.closed = False
        self.dragging = False
        self._photo = None
        self._video_frame = None
        root.title('mawkbox')
        root.geometry('740x740')
        root.minsize(680, 700)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TButton', background=PANEL, foreground=FG, padding=8)
        style.map('TButton', background=[('active', '#343841')])
        box = tk.Frame(root, bg=BG, padx=24, pady=18)
        box.pack(fill='both', expand=True)
        footer = tk.Frame(box, bg=BG)
        footer.pack(side='bottom', fill='x', pady=(8, 0))
        tk.Label(box, text='mawkbox', font=('TkDefaultFont', 24, 'bold'), bg=BG, fg=FG).pack(anchor='w')
        tk.Label(box, text='COMPOSE  /  PLAY  /  RECOVER', bg=BG, fg='#858c98').pack(anchor='w', pady=(2, 12))
        tk.Label(box, text='MESSAGE', bg=BG, fg=FG).pack(anchor='w')
        self.message = tk.Text(box, height=3, bg=PANEL, fg=FG, insertbackground=RED, relief='flat', padx=12, pady=10, wrap='word')
        self.message.pack(fill='x', pady=(6, 10))
        self.message.insert('1.0', 'Good morning, NSA.')
        self.canvas = tk.Canvas(box, height=210, bg=BG, highlightthickness=1, highlightbackground='#282d36')
        self.canvas.pack(fill='x', pady=(0, 8))
        self.canvas.bind('<Configure>', lambda _: self.draw())
        transport = tk.Frame(box, bg=BG)
        transport.pack(fill='x')
        self.transport = []
        for text, action in [('Play video', lambda: self.play(True)), ('Play audio', lambda: self.play(False)),
                             ('Pause', self.pause), ('Stop', self.stop)]:
            button = ttk.Button(transport, text=text, command=action, state='disabled')
            button.pack(side='left', padx=(0, 6))
            self.transport.append(button)
        self.autoplay = tk.BooleanVar(value=True)
        tk.Checkbutton(transport, text='Autoplay', variable=self.autoplay, bg=BG, fg=FG,
                       selectcolor=PANEL, activebackground=BG, activeforeground=FG).pack(side='right')
        timeline = tk.Frame(box, bg=BG)
        timeline.pack(fill='x', pady=(6, 8))
        self.seek_value = tk.DoubleVar(value=0)
        self.seek_slider = ttk.Scale(timeline, from_=0, to=1, variable=self.seek_value, state='disabled')
        self.seek_slider.pack(side='left', fill='x', expand=True)
        self.seek_slider.bind('<ButtonPress-1>', lambda _: setattr(self, 'dragging', True))
        self.seek_slider.bind('<ButtonRelease-1>', self.seek)
        self.seek_slider.bind('<KeyRelease>', self.seek)
        self.time_label = tk.StringVar(value='00:00.0 / 00:00.0')
        tk.Label(timeline, textvariable=self.time_label, bg=BG, fg='#858c98').pack(side='right', padx=(10, 0))
        self.plain = tk.BooleanVar(value=False)
        tk.Checkbutton(box, text='Plain encoding (no secrecy)', variable=self.plain, bg=BG, fg=FG,
                       selectcolor=PANEL, activebackground=BG, activeforeground=FG).pack(anchor='w')
        tk.Label(box, text='PASSPHRASE', bg=BG, fg='#858c98').pack(anchor='w', pady=(6, 4))
        self.password = tk.Entry(box, show='•', bg=PANEL, fg=FG, insertbackground=RED, relief='flat')
        self.password.pack(fill='x', ipady=6)
        row = tk.Frame(footer, bg=BG)
        row.pack(fill='x', pady=(4, 8))
        self.buttons = []
        for text, action in [('Export WAV', lambda: self.export(False)), ('Export MP4 + WAV', lambda: self.export(True)),
                             ('Open media', self.open_media), ('Decode file', self.open)]:
            button = ttk.Button(row, text=text, command=action)
            button.pack(side='left', padx=(0, 6))
            self.buttons.append(button)
        self.status = tk.StringVar(value='Ready. Open or export a transmission to play it here.')
        self.saved_file = tk.StringVar(value='No export yet.')
        self.receipt = tk.Entry(footer, textvariable=self.saved_file, state='readonly', relief='flat',
                                readonlybackground=BG, fg='#7ebf99')
        self.receipt.pack(fill='x', pady=(0, 4))
        tk.Label(footer, textvariable=self.status, bg=BG, fg='#a3a9b3', wraplength=670, justify='left').pack(anchor='w')
        self._poll_id = root.after(30, self.poll)

    def draw(self):
        c = self.canvas
        c.delete('all')
        width, height = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        if self._video_frame is not None and self.player.video_enabled:
            frame = self._video_frame.copy()
            frame.thumbnail((width-4, height-4), Image.Resampling.LANCZOS)
            self._photo = ImageTk.PhotoImage(frame)
            c.create_image(width/2, height/2, image=self._photo)
            return
        c.create_text(16, 18, text='AUDIO SIGNAL  /  4-FSK', fill='#858c98', anchor='w')
        center = height/2
        c.create_line(16, center, width-16, center, fill='#342027')
        if self.audio is not None:
            start = int(self.player.position * RATE) if self.player.state in ('playing', 'paused') else RATE//10
            segment = self.audio[start:start+720]
            points = []
            for i, value in enumerate(segment):
                points.extend((16+i*(width-32)/719, center-float(value)*(height*.30)))
            if len(points) > 3:
                c.create_line(*points, fill=RED, width=2)
        else:
            c.create_line(16, center, width-16, center, fill=RED, width=2)

    def controls(self):
        media = self.player.media
        self.transport[0].configure(state='normal' if media and media.video and not self.busy else 'disabled')
        self.transport[1].configure(state='normal' if media and media.audio and not self.busy else 'disabled')
        self.transport[2].configure(text='Resume' if self.player.state == 'paused' else 'Pause',
                                    state='normal' if self.player.state in ('playing', 'paused') else 'disabled')
        self.transport[3].configure(state='normal' if media else 'disabled')
        self.seek_slider.configure(state='normal' if media and not self.busy else 'disabled', to=media.duration if media else 1)

    def play(self, video):
        try:
            self._video_frame = None
            self.player.play(0, video=video)
            self.status.set(f'Playing {self.player.media.path.name}' + (' (audio only).' if not video else '.'))
        except Exception as exc:
            self.status.set(str(exc))
        self.controls()
        self.draw()

    def pause(self):
        try:
            if self.player.state == 'paused':
                self.player.resume()
            else:
                self.player.pause()
        except Exception as exc:
            self.status.set(str(exc))
        self.controls()

    def stop(self):
        self.player.stop()
        self.seek_value.set(0)
        self._video_frame = None
        self.controls()
        self.draw()

    def seek(self, _=None):
        self.dragging = False
        try:
            self.player.seek(self.seek_value.get())
        except Exception as exc:
            self.status.set(str(exc))
        self.controls()
        self.draw()

    def run(self, operation, error_title=None):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state='disabled')
        self.controls()
        self.status.set('Processing…')
        def work():
            try:
                self.events.put(('ok', operation()))
            except Exception as exc:
                self.events.put(('error', (str(exc), error_title)))
        threading.Thread(target=work, daemon=True).start()

    def load_media(self, media, audio):
        self.player.load(media)
        self.audio, self._video_frame = audio, None
        self.seek_value.set(0)
        self.controls()
        self.draw()
        if self.autoplay.get():
            self.play(media.video)

    def poll(self):
        if self.closed:
            return
        try:
            kind, value = self.events.get_nowait()
            self.busy = False
            for button in self.buttons:
                button.configure(state='normal')
            if kind == 'error':
                error, title = value
                self.status.set(error)
                if title:
                    messagebox.showerror(title, error, parent=self.root)
            elif value[0] == 'decode':
                self.message.delete('1.0', 'end')
                self.message.insert('1.0', value[1])
                self.status.set('Message recovered successfully.')
            elif value[0] == 'export':
                result = value[1]
                self.saved_file.set(f'Last saved: {result.media.path}')
                self.status.set('Export complete.')
                self.load_media(result.media, result.audio)
            else:
                self.status.set(value[3])
                self.load_media(value[1], value[2])
        except queue.Empty:
            pass
        previous = self.player.state
        try:
            frame = self.player.tick()
            if frame is not None:
                self._video_frame = frame
                self.draw()
            elif self.player.state == 'playing' and not self.player.video_enabled:
                self.draw()
        except Exception as exc:
            self.status.set(str(exc))
        if self.player.state == 'ended' and previous != 'ended':
            self.status.set('Playback finished. Press Play to replay.')
        duration = self.player.media.duration if self.player.media else 0
        if not self.dragging:
            self.seek_value.set(self.player.position)
        self.time_label.set(f'{timestamp(self.player.position)} / {timestamp(duration)}')
        self.controls()
        self._poll_id = self.root.after(30, self.poll)

    def export(self, video):
        if self.busy:
            return
        message = self.message.get('1.0', 'end-1c')
        password = None if self.plain.get() else self.password.get()
        try:
            validate_message(message, password)
        except ValueError as exc:
            self.status.set(str(exc))
            messagebox.showerror('Cannot export', str(exc), parent=self.root)
            if password == '':
                self.password.focus_set()
            else:
                self.message.focus_set()
            return
        suffix = '.mp4' if video else '.wav'
        try:
            name = filedialog.asksaveasfilename(parent=self.root, title='Export MP4' if video else 'Export WAV',
                                                initialfile='transmission'+suffix, defaultextension=suffix,
                                                filetypes=[('MP4 video' if video else 'WAV audio', '*'+suffix)])
        except tk.TclError as exc:
            self.status.set(str(exc))
            messagebox.showerror('Cannot open save dialog', str(exc), parent=self.root)
            return
        if not name:
            self.status.set('Export cancelled.')
            return
        self.stop()
        self.run(lambda: ('export', export_transmission(name, message, password, video)), error_title='Export failed')

    def open_media(self):
        name = filedialog.askopenfilename(filetypes=[('Playable transmissions', '*.wav *.mp4')])
        if name:
            self.stop()
            def operation():
                media = inspect_media(name)
                audio = read_audio(media.path) if media.audio else None
                return ('media', media, audio, f'Opened {media.path.name}.')
            self.run(operation)

    def open(self):
        name = filedialog.askopenfilename(filetypes=[('mawkbox transmissions', '*.wav *.mp4 *.mawkbox'), ('All files', '*')])
        if name:
            password = self.password.get() or None
            self.run(lambda: ('decode', decode(name, password)))

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.root.after_cancel(self._poll_id)
        self.player.close()
        self.root.destroy()


def launch():
    root = tk.Tk()
    Workspace(root)
    root.mainloop()
