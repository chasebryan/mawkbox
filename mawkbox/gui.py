"""A single compact desktop workspace; all processing stays local."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path
from .signal import pack, modulate, write_wav, decode, RATE
from .video import render_video

BG, PANEL, RED, FG = '#090b0e', '#13161c', '#ff334f', '#edf0f4'


class Workspace:
    def __init__(self, root):
        self.root, self.events = root, queue.Queue()
        self.audio = None
        self.busy = False
        root.title('mawkbox')
        root.geometry('720x640')
        root.minsize(620, 600)
        root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TButton', background=PANEL, foreground=FG, padding=10)
        style.map('TButton', background=[('active', '#343841')])
        box = tk.Frame(root, bg=BG, padx=28, pady=22)
        box.pack(fill='both', expand=True)
        tk.Label(box, text='mawkbox', font=('TkDefaultFont', 26, 'bold'), bg=BG, fg=FG).pack(anchor='w')
        tk.Label(box, text='COMPOSE  /  ENCODE  /  RECOVER', bg=BG, fg='#858c98').pack(anchor='w', pady=(2, 18))
        tk.Label(box, text='MESSAGE', bg=BG, fg=FG).pack(anchor='w')
        self.message = tk.Text(box, height=5, bg=PANEL, fg=FG, insertbackground=RED, relief='flat', padx=12, pady=12, wrap='word')
        self.message.pack(fill='x', pady=(8, 12))
        self.message.insert('1.0', 'Good morning, NSA.')
        self.canvas = tk.Canvas(box, height=160, bg=BG, highlightthickness=1, highlightbackground='#282d36')
        self.canvas.pack(fill='x', pady=(0, 14))
        self.canvas.bind('<Configure>', lambda _: self.draw())
        self.plain = tk.BooleanVar(value=False)
        tk.Checkbutton(box, text='Plain encoding (no secrecy)', variable=self.plain, bg=BG, fg=FG,
                       selectcolor=PANEL, activebackground=BG, activeforeground=FG).pack(anchor='w')
        tk.Label(box, text='PASSPHRASE', bg=BG, fg='#858c98').pack(anchor='w', pady=(8, 4))
        self.password = tk.Entry(box, show='•', bg=PANEL, fg=FG, insertbackground=RED, relief='flat')
        self.password.pack(fill='x', ipady=8)
        row = tk.Frame(box, bg=BG)
        row.pack(fill='x', pady=(16, 12))
        self.buttons = []
        for text, action in [('Export WAV', lambda: self.export(False)), ('Export MP4 + WAV', lambda: self.export(True)), ('Decode file', self.open)]:
            button = ttk.Button(row, text=text, command=action)
            button.pack(side='left', padx=(0, 8))
            self.buttons.append(button)
        self.status = tk.StringVar(value='Ready. Encrypted by default. Audio and video stay on your computer.')
        tk.Label(box, textvariable=self.status, bg=BG, fg='#a3a9b3', wraplength=640, justify='left').pack(anchor='w')
        root.after(100, self.poll)

    def draw(self):
        c = self.canvas
        c.delete('all')
        width = max(c.winfo_width(), 100)
        c.create_text(16, 18, text='SIGNAL  /  4-FSK', fill='#858c98', anchor='w')
        c.create_line(16, 88, width-16, 88, fill='#342027')
        if self.audio is not None:
            segment = self.audio[RATE//10:RATE//10+720]
            points = []
            for i, value in enumerate(segment):
                points.extend((16+i*(width-32)/719, 88-float(value)*55))
            c.create_line(*points, fill=RED, width=2)
            c.create_text(16, 141, text=f'{len(self.audio)/RATE:.2f}s  /  48 kHz', fill='#858c98', anchor='w')
        else:
            c.create_line(16, 88, width-16, 88, fill=RED, width=2)

    def run(self, operation):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state='disabled')
        self.status.set('Processing…')
        def work():
            try:
                self.events.put(('ok', operation()))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            kind, value = self.events.get_nowait()
            self.busy = False
            for button in self.buttons:
                button.configure(state='normal')
            if kind == 'error':
                self.status.set(value)
            elif value[0] == 'decode':
                self.message.delete('1.0', 'end')
                self.message.insert('1.0', value[1])
                self.status.set('Message recovered successfully.')
            else:
                self.audio = value[1]
                self.draw()
                self.status.set(value[2])
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def export(self, video):
        suffix = '.mp4' if video else '.wav'
        name = filedialog.asksaveasfilename(defaultextension=suffix, filetypes=[('mawkbox output', '*'+suffix)])
        if not name:
            return
        message = self.message.get('1.0', 'end-1c')
        password = None if self.plain.get() else self.password.get()
        def operation():
            frame = pack(message, password)
            audio = modulate(frame)
            base = Path(name)
            wav = base.with_suffix('.wav')
            write_wav(wav, audio)
            base.with_suffix('.mawkbox').write_bytes(frame)
            if video:
                render_video(base.with_suffix('.mp4'), audio, wav)
            return ('export', audio, f'Exported {base.name} and companion files.')
        self.run(operation)

    def open(self):
        name = filedialog.askopenfilename(filetypes=[('mawkbox transmissions', '*.wav *.mp4 *.mawkbox'), ('All files', '*')])
        if name:
            password = self.password.get() or None
            self.run(lambda: ('decode', decode(name, password)))


def launch():
    root = tk.Tk()
    Workspace(root)
    root.mainloop()
