"""Optional desktop control window. Existing command-line entry points remain available."""
import json
import os
from pathlib import Path
import queue
import sys
import threading
import webbrowser

if sys.version_info < (3, 10):
    raise SystemExit('Use Python 3.10 or newer for the editor host.')

from strike_remapper.host import Host, lan_addresses, pairing_matrix


def main():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        raise SystemExit('The launcher needs Python with Tk. You can still run python strike_remap.py, or the Wi-Fi command in docs/WIFI_EDITOR.md.')

    config_dir = Path(os.environ.get('APPDATA') or Path.home() / '.config') / 'StrikeRemapper'
    config_path = config_dir / 'launcher.json'
    try:
        config = json.loads(config_path.read_text('utf-8'))
        if not isinstance(config, dict):
            config = {}
    except (OSError, ValueError):
        config = {}
    window = tk.Tk()
    window.title('Strike Remapper · Host')
    window.geometry('720x760')
    window.minsize(600, 650)
    window.configure(bg='#151916')
    style = ttk.Style(window)
    style.theme_use('clam')
    style.configure('.', background='#151916', foreground='#d8ded4', font=('TkDefaultFont', 11))
    style.configure('TButton', padding=9, background='#283127')
    style.configure('TEntry', fieldbackground='#0f1310', foreground='#e8ebdf')
    style.configure('TCheckbutton', background='#151916')
    host = Host()
    results = queue.Queue()
    busy = False
    library = tk.StringVar(value=str(config.get('library') or Path.home() / 'Documents/Strike Remapper/library'))
    address = tk.StringVar(value=str(config.get('address') or ''))
    wifi = tk.BooleanVar(value=False)
    status = tk.StringVar(value='Stopped · Your library stays on this computer')
    frame = ttk.Frame(window, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='STRIKE REMAPPER', font=('TkDefaultFont', 22, 'bold'), foreground='#d8b567').pack(anchor='w')
    ttk.Label(frame, text='Open here. Pair your iPad. Keep your library.', padding=(0, 8, 0, 20)).pack(anchor='w')
    ttk.Label(frame, text='Library folder').pack(anchor='w')
    folder_row = ttk.Frame(frame)
    folder_row.pack(fill='x', pady=(5, 10))
    entry = ttk.Entry(folder_row, textvariable=library)
    entry.pack(side='left', fill='x', expand=True)
    def choose_folder():
        chosen = filedialog.askdirectory(title='Choose your existing library or an empty folder')
        if chosen:
            library.set(chosen)
    browse = ttk.Button(folder_row, text='Choose…', command=choose_folder)
    browse.pack(side='left', padx=(8, 0))
    ttk.Label(frame, text='Already have a library? Choose its folder. Nothing is moved automatically.', wraplength=650).pack(anchor='w')
    wifi_check = ttk.Checkbutton(frame, text='Allow iPad / iPhone on my trusted Wi-Fi', variable=wifi)
    wifi_check.pack(anchor='w', pady=(18, 6))
    ttk.Label(frame, text='This computer’s Wi-Fi IPv4 address (only needed for pairing)').pack(anchor='w')
    addresses = lan_addresses()
    if not address.get() and addresses:
        address.set(addresses[0])
    address_entry = ttk.Combobox(frame, textvariable=address, values=addresses)
    address_entry.pack(fill='x', pady=6)
    ttk.Label(frame, textvariable=status, wraplength=650, foreground='#d8b567').pack(anchor='w', pady=12)
    actions = ttk.Frame(frame)
    actions.pack(fill='x')
    qr = tk.Canvas(frame, width=260, height=260, bg='#151916', highlightthickness=0)
    qr.pack(pady=(14, 0))
    pairing_note = ttk.Label(frame, text='Enable Wi-Fi, then Start to show your pairing code.', wraplength=650)
    pairing_note.pack()

    def refresh():
        start.configure(state='disabled' if busy or host.running else 'normal')
        stop.configure(state='normal' if host.running and not busy else 'disabled')
        for control in (entry, browse, wifi_check, address_entry):
            control.configure(state='disabled' if busy or host.running else 'normal')
        for control in (open_editor, copy_link):
            control.configure(state='normal' if host.running and not busy else 'disabled')
        qr.delete('all')
        if host.pair_url:
            matrix = pairing_matrix(host.pair_url)
            size = len(matrix)
            scale = max(3, 260 // (size + 8))
            total = (size + 8) * scale
            qr.configure(width=total, height=total, bg='white')
            for y, row in enumerate(matrix):
                for x, dark in enumerate(row):
                    if dark:
                        qr.create_rectangle((x+4)*scale, (y+4)*scale, (x+5)*scale, (y+5)*scale, fill='black', width=0)
            pairing_note.configure(text='Scan with your iPad/iPhone camera on the same Wi-Fi. The link grants editor access. Keep this computer awake; use HTTP.')
        else:
            qr.configure(bg='#151916')
            pairing_note.configure(text='Wi-Fi is off.' if host.running else 'Enable Wi-Fi, then Start to show your pairing code.')

    def run_async(action, done):
        nonlocal busy
        busy = True
        refresh()
        def worker():
            try:
                action()
                results.put((done, None))
            except Exception as exc:
                results.put((done, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def started():
        status.set('Running · Open the editor below, or scan to pair')
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            tmp = config_path.with_suffix('.tmp')
            tmp.write_text(json.dumps({'library':str(host.library), 'address':address.get()}), 'utf-8')
            tmp.replace(config_path)
        except OSError:
            status.set('Running · Folder preference could not be saved; choose it again next time')

    def start_host():
        root, bind = library.get(), address.get().strip() if wifi.get() else None
        if wifi.get() and not bind:
            messagebox.showerror('Choose an address', 'Enter this computer’s private Wi-Fi IPv4 address.')
            return
        status.set('Starting…')
        run_async(lambda: host.start(root, bind), started)

    def stop_host(closing=False):
        status.set('Saving recovery and stopping…')
        def stopped():
            status.set('Stopped · Recovery copies and library files are kept')
            if closing:
                window.destroy()
        run_async(host.stop, stopped)

    def copy_text(value):
        window.clipboard_clear()
        window.clipboard_append(value)

    start = ttk.Button(actions, text='Start', command=start_host)
    start.pack(side='left')
    stop = ttk.Button(actions, text='Stop', command=stop_host)
    stop.pack(side='left', padx=6)
    open_editor = ttk.Button(actions, text='Open editor', command=lambda: webbrowser.open(host.pair_url or host.url))
    open_editor.pack(side='left')
    copy_link = ttk.Button(actions, text='Copy link', command=lambda: copy_text(host.pair_url or host.url))
    copy_link.pack(side='left', padx=6)
    ttk.Button(frame, text='Copy diagnostics (no pairing token)', command=lambda: copy_text(host.diagnostics())).pack(anchor='w', pady=10)

    def poll():
        nonlocal busy
        try:
            done, error = results.get_nowait()
        except queue.Empty:
            pass
        else:
            busy = False
            if error:
                status.set('Action failed · ' + error)
                messagebox.showerror('Editor host', error + '\nIf the port is occupied, stop the other editor first. No other process was stopped.')
            else:
                done()
            try:
                exists = window.winfo_exists()
            except tk.TclError:
                return
            if exists:
                refresh()
        if window.winfo_exists():
            window.after(100, poll)

    def close():
        if busy:
            return
        if host.running:
            stop_host(closing=True)
        else:
            window.destroy()
    window.protocol('WM_DELETE_WINDOW', close)
    refresh()
    window.after(100, poll)
    window.mainloop()


if __name__ == '__main__':
    main()
