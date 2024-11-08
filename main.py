import os
import json
import shutil
import ftplib
import threading
import subprocess
import mimetypes
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import ttkbootstrap as ttk
from tkinterdnd2 import DND_FILES, TkinterDnD

class FTPClient:
    def __init__(self):
        self.root = TkinterDnD.Tk()
        
        self.style = ttk.Style()
        self.style.theme_use("darkly")
        
        self.root.title("FTP Client")
        self.root.geometry("1000x700")
        
        self.ftp = None
        self.current_remote_dir = "/"
        self.current_local_dir = str(Path.home())
        self.transfer_queue = []
        self.is_connected = False
        
        self.saved_servers = self.load_saved_servers()
        self.setup_ui()
        self.setup_bindings()
        self.refresh_local_files()

    def format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"

    def load_saved_servers(self):
        config_path = Path.home() / '.ftp_client' / 'servers.json'
        if config_path.exists():
            try:
                with open(config_path) as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def browse_local_directory(self):
        directory = filedialog.askdirectory(
            initialdir=self.current_local_dir,
            title="Select Directory"
        )
        if directory:
            self.current_local_dir = directory
            self.local_path_var.set(directory)
            self.refresh_local_files()

    def on_local_drop(self, event):
        files = event.data
        if isinstance(files, str):
            files = files.split()
        
        for file in files:
            file = file.strip('{}')
            if os.path.exists(file):
                try:
                    dest_path = os.path.join(self.current_local_dir, os.path.basename(file))
                    if os.path.isfile(file):
                        shutil.copy2(file, dest_path)
                    elif os.path.isdir(file):
                        if os.path.exists(dest_path):
                            if not messagebox.askyesno("Confirm Replace", 
                                f"Directory {os.path.basename(file)} already exists. Replace it?"):
                                continue
                            shutil.rmtree(dest_path)
                        shutil.copytree(file, dest_path)
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to copy {file}: {str(e)}")
        
        self.refresh_local_files()
        return event.action

    def on_remote_drop(self, event):
        if not self.is_connected:
            messagebox.showerror("Error", "Not connected to server")
            return event.action

        files = event.data
        if isinstance(files, str):
            files = files.split()
        
        for file in files:
            file = file.strip('{}')
            if os.path.exists(file):
                self.queue_transfer('upload', [file])
        
        return event.action

    def on_local_double_click(self, event):
        selection = self.local_tree.selection()
        if not selection:
            return
            
        item = selection[0]
        name = self.local_tree.item(item)['text']
        if name == "..":
            self.current_local_dir = os.path.dirname(self.current_local_dir)
        else:
            path = os.path.join(self.current_local_dir, name)
            if os.path.isdir(path):
                self.current_local_dir = path
                
        self.refresh_local_files()

    def on_remote_double_click(self, event):
        if not self.is_connected:
            return
            
        selection = self.remote_tree.selection()
        if not selection:
            return
            
        item = selection[0]
        name = self.remote_tree.item(item)['text']
        
        try:
            if name == "..":
                self.ftp.cwd("..")
            else:
                self.ftp.cwd(name)
            
            self.current_remote_dir = self.ftp.pwd()
            self.refresh_remote_files()
        except ftplib.error_perm:
            pass

    def on_local_path_change(self, *args):
        path = self.local_path_var.get()
        if os.path.exists(path) and os.path.isdir(path):
            self.current_local_dir = path
            self.refresh_local_files()

    def on_remote_path_change(self, *args):
        if not self.is_connected:
            return
            
        path = self.remote_path_var.get()
        try:
            self.ftp.cwd(path)
            self.current_remote_dir = self.ftp.pwd()
            self.refresh_remote_files()
        except:
            pass

    def setup_ui(self):
        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.setup_toolbar()
        self.setup_quickconnect()
        self.setup_connection_panel()
        self.setup_main_panel()

    def setup_toolbar(self):
        toolbar = ttk.Frame(self.main_container)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        
        actions = [
            ("Refresh", self.refresh_all, "refresh"),
            ("New Folder", self.create_folder, "folder-plus"),
            ("Delete", self.delete_selected, "trash"),
            ("Upload", self.queue_upload, "upload"),
            ("Download", self.queue_download, "download"),
        ]
        
        for text, command, icon in actions:
            btn = ttk.Button(
                toolbar,
                text=text,
                command=command,
                style="primary.TButton",
                compound="left"
            )
            btn.pack(side=tk.LEFT, padx=2)

    def setup_quickconnect(self):
        quick_frame = ttk.LabelFrame(self.main_container, text="Quick Connect", padding=5)
        quick_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(quick_frame, text="Host:").pack(side=tk.LEFT)
        self.host_var = tk.StringVar()
        ttk.Entry(quick_frame, textvariable=self.host_var).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(quick_frame, text="Port:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value="21")
        ttk.Entry(quick_frame, textvariable=self.port_var, width=6).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(quick_frame, text="Username:").pack(side=tk.LEFT)
        self.username_var = tk.StringVar()
        ttk.Entry(quick_frame, textvariable=self.username_var).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(quick_frame, text="Password:").pack(side=tk.LEFT)
        self.password_var = tk.StringVar()
        ttk.Entry(quick_frame, textvariable=self.password_var, show="*").pack(side=tk.LEFT, padx=5)
        
        ttk.Button(quick_frame, text="Connect", command=self.quick_connect).pack(side=tk.LEFT, padx=5)

    def setup_connection_panel(self):
        conn_frame = ttk.LabelFrame(self.main_container, text="Connection", padding=5)
        conn_frame.pack(fill=tk.X, pady=(0, 5))

        server_frame = ttk.Frame(conn_frame)
        server_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(server_frame, text="Saved Servers:").pack(side=tk.LEFT)
        self.server_combo = ttk.Combobox(
            server_frame, 
            values=list(self.saved_servers.keys()),
            state="readonly"
        )
        self.server_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        btn_frame = ttk.Frame(conn_frame)
        btn_frame.pack(fill=tk.X, pady=2)
        
        ttk.Button(btn_frame, text="Connect", command=self.connect_to_server).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Disconnect", command=self.disconnect).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Save Server", command=self.save_server).pack(side=tk.LEFT, padx=2)

    def setup_main_panel(self):
        main_frame = ttk.Frame(self.main_container)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        left_panel = ttk.Frame(main_frame)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.setup_local_browser(ttk.LabelFrame(left_panel, text="Local Files", padding=5))
        self.setup_remote_browser(ttk.LabelFrame(right_panel, text="Remote Files", padding=5))
        self.setup_queue_panel(ttk.LabelFrame(main_frame, text="Transfer Queue", padding=5))

    def setup_local_browser(self, parent):
        parent.pack(fill=tk.BOTH, expand=True)
        
        nav_frame = ttk.Frame(parent)
        nav_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(nav_frame, text="Path: ").pack(side=tk.LEFT)
        self.local_path_var = tk.StringVar(value=self.current_local_dir)
        path_entry = ttk.Entry(nav_frame, textvariable=self.local_path_var)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Button(nav_frame, text="Browse", command=self.browse_local_directory).pack(side=tk.LEFT, padx=5)
        
        browser_frame = ttk.Frame(parent)
        browser_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ("name", "size", "type", "modified")
        self.local_tree = ttk.Treeview(
            browser_frame,
            columns=columns,
            show="headings",
            selectmode="extended"
        )
        
        self.local_tree.drop_target_register(DND_FILES)
        self.local_tree.drag_source_register(1, DND_FILES)
        self.local_tree.dnd_bind('<<Drop>>', self.on_local_drop)
        
        self.local_tree.heading("name", text="Name", command=lambda: self.treeview_sort_column(self.local_tree, "name", False))
        self.local_tree.heading("size", text="Size", command=lambda: self.treeview_sort_column(self.local_tree, "size", False))
        self.local_tree.heading("type", text="Type", command=lambda: self.treeview_sort_column(self.local_tree, "type", False))
        self.local_tree.heading("modified", text="Modified", command=lambda: self.treeview_sort_column(self.local_tree, "modified", False))
        
        self.local_tree.column("name", width=200, minwidth=150)
        self.local_tree.column("size", width=100, minwidth=80)
        self.local_tree.column("type", width=100, minwidth=80)
        self.local_tree.column("modified", width=150, minwidth=120)
        
        vsb = ttk.Scrollbar(browser_frame, orient="vertical", command=self.local_tree.yview)
        hsb = ttk.Scrollbar(browser_frame, orient="horizontal", command=self.local_tree.xview)
        self.local_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        self.local_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        
        browser_frame.grid_columnconfigure(0, weight=1)
        browser_frame.grid_rowconfigure(0, weight=1)

    def setup_remote_browser(self, parent):
        parent.pack(fill=tk.BOTH, expand=True)
        
        nav_frame = ttk.Frame(parent)
        nav_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(nav_frame, text="Path: ").pack(side=tk.LEFT)
        self.remote_path_var = tk.StringVar(value="/")
        path_entry = ttk.Entry(nav_frame, textvariable=self.remote_path_var)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        browser_frame = ttk.Frame(parent)
        browser_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ("name", "size", "type", "modified", "permissions")
        self.remote_tree = ttk.Treeview(
            browser_frame,
            columns=columns,
            show="headings",
            selectmode="extended"
        )
        
        self.remote_tree.drop_target_register(DND_FILES)
        self.remote_tree.drag_source_register(1, DND_FILES)
        self.remote_tree.dnd_bind('<<Drop>>', self.on_remote_drop)
        
        self.remote_tree.heading("name", text="Name", command=lambda: self.treeview_sort_column(self.remote_tree, "name", False))
        self.remote_tree.heading("size", text="Size", command=lambda: self.treeview_sort_column(self.remote_tree, "size", False))
        self.remote_tree.heading("type", text="Type", command=lambda: self.treeview_sort_column(self.remote_tree, "type", False))
        self.remote_tree.heading("modified", text="Modified", command=lambda: self.treeview_sort_column(self.remote_tree, "modified", False))
        self.remote_tree.heading("permissions", text="Permissions")
        
        self.remote_tree.column("name", width=200, minwidth=150)
        self.remote_tree.column("size", width=100, minwidth=80)
        self.remote_tree.column("type", width=100, minwidth=80)
        self.remote_tree.column("modified", width=150, minwidth=120)
        self.remote_tree.column("permissions", width=100, minwidth=80)
        
        vsb = ttk.Scrollbar(browser_frame, orient="vertical", command=self.remote_tree.yview)
        hsb = ttk.Scrollbar(browser_frame, orient="horizontal", command=self.remote_tree.xview)
        self.remote_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        self.remote_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        
        browser_frame.grid_columnconfigure(0, weight=1)
        browser_frame.grid_rowconfigure(0, weight=1)

    def setup_queue_panel(self, parent):
        parent.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        columns = ("file", "size", "status", "speed", "progress")
        self.queue_tree = ttk.Treeview(
            parent,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        
        self.queue_tree.heading("file", text="File")
        self.queue_tree.heading("size", text="Size")
        self.queue_tree.heading("status", text="Status")
        self.queue_tree.heading("speed", text="Speed")
        self.queue_tree.heading("progress", text="Progress")
        
        self.queue_tree.column("file", width=200)
        self.queue_tree.column("size", width=80)
        self.queue_tree.column("status", width=80)
        self.queue_tree.column("speed", width=80)
        self.queue_tree.column("progress", width=80)
        
        vsb = ttk.Scrollbar(parent, orient="vertical", command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=vsb.set)
        
        self.queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def setup_bindings(self):
        self.local_tree.bind('<Double-1>', self.on_local_double_click)
        self.remote_tree.bind('<Double-1>', self.on_remote_double_click)
        self.local_path_var.trace('w', self.on_local_path_change)
        self.remote_path_var.trace('w', self.on_remote_path_change)
        self.root.bind('<F5>', lambda e: self.refresh_all())
        self.root.bind('<Delete>', lambda e: self.delete_selected())
        self.root.bind('<Control-c>', lambda e: self.queue_download())
        self.root.bind('<Control-v>', lambda e: self.queue_upload())
        
        self.local_tree.bind('<Button-3>', self.show_local_context_menu)
        self.remote_tree.bind('<Button-3>', self.show_remote_context_menu)
        
        self.setup_context_menus()

    def setup_context_menus(self):
        self.local_context_menu = tk.Menu(self.root, tearoff=0)
        self.local_context_menu.add_command(label="Open", command=self.open_local_file)
        self.local_context_menu.add_command(label="Upload", command=self.queue_upload)
        self.local_context_menu.add_separator()
        self.local_context_menu.add_command(label="Copy Path", command=self.copy_local_path)
        self.local_context_menu.add_separator()
        self.local_context_menu.add_command(label="New Folder", command=self.create_folder)
        self.local_context_menu.add_command(label="Rename", command=self.rename_local)
        self.local_context_menu.add_command(label="Delete", command=self.delete_selected)
        self.local_context_menu.add_separator()
        self.local_context_menu.add_command(label="Refresh", command=self.refresh_local_files)

        self.remote_context_menu = tk.Menu(self.root, tearoff=0)
        self.remote_context_menu.add_command(label="Download", command=self.queue_download)
        self.remote_context_menu.add_separator()
        self.remote_context_menu.add_command(label="Copy Path", command=self.copy_remote_path)
        self.remote_context_menu.add_separator()
        self.remote_context_menu.add_command(label="New Folder", command=self.create_folder)
        self.remote_context_menu.add_command(label="Rename", command=self.rename_remote)
        self.remote_context_menu.add_command(label="Delete", command=self.delete_selected)
        self.remote_context_menu.add_separator()
        self.remote_context_menu.add_command(label="Refresh", command=self.refresh_remote_files)

    def show_local_context_menu(self, event):
        try:
            self.local_tree.selection_set(self.local_tree.identify_row(event.y))
            self.local_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.local_context_menu.grab_release()

    def show_remote_context_menu(self, event):
        if not self.is_connected:
            return
        try:
            self.remote_tree.selection_set(self.remote_tree.identify_row(event.y))
            self.remote_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.remote_context_menu.grab_release()

    def open_local_file(self):
        selected = self.local_tree.selection()
        if not selected:
            return
            
        item = selected[0]
        path = os.path.join(self.current_local_dir, self.local_tree.item(item)['text'])
        if os.path.isfile(path):
            try:
                if os.name == 'nt':  
                    os.startfile(path)
                elif os.name == 'posix':  
                    subprocess.call(('xdg-open', path))
            except Exception as e:
                messagebox.showerror("Error", f"Failed to open file: {str(e)}")

    def copy_local_path(self):
        selected = self.local_tree.selection()
        if not selected:
            return
            
        item = selected[0]
        path = os.path.join(self.current_local_dir, self.local_tree.item(item)['text'])
        self.root.clipboard_clear()
        self.root.clipboard_append(path)

    def copy_remote_path(self):
        selected = self.remote_tree.selection()
        if not selected:
            return
            
        item = selected[0]
        name = self.remote_tree.item(item)['text']
        path = os.path.join(self.current_remote_dir, name).replace('\\', '/')
        self.root.clipboard_clear()
        self.root.clipboard_append(path)

    def rename_local(self):
        selected = self.local_tree.selection()
        if not selected:
            return
            
        item = selected[0]
        old_name = self.local_tree.item(item)['text']
        new_name = simpledialog.askstring("Rename", "Enter new name:", initialvalue=old_name)
        
        if new_name and new_name != old_name:
            old_path = os.path.join(self.current_local_dir, old_name)
            new_path = os.path.join(self.current_local_dir, new_name)
            try:
                os.rename(old_path, new_path)
                self.refresh_local_files()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to rename: {str(e)}")

    def rename_remote(self):
        if not self.is_connected:
            return
            
        selected = self.remote_tree.selection()
        if not selected:
            return
            
        item = selected[0]
        old_name = self.remote_tree.item(item)['text']
        new_name = simpledialog.askstring("Rename", "Enter new name:", initialvalue=old_name)
        
        if new_name and new_name != old_name:
            try:
                self.ftp.rename(old_name, new_name)
                self.refresh_remote_files()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to rename: {str(e)}")

    def refresh_all(self):
        self.refresh_local_files()
        if self.is_connected:
            self.refresh_remote_files()

    def refresh_local_files(self):
        for item in self.local_tree.get_children():
            self.local_tree.delete(item)
        
        try:
            if self.current_local_dir != str(Path.home()):
                parent = os.path.dirname(self.current_local_dir)
                self.local_tree.insert('', 'end', text="..", values=("..", "", "Parent Directory", ""))
            
            entries = []
            for entry in os.scandir(self.current_local_dir):
                try:
                    stats = entry.stat()
                    size = stats.st_size if entry.is_file() else ""
                    modified = datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M')
                    file_type = 'Directory' if entry.is_dir() else (mimetypes.guess_type(entry.name)[0] or 'File')
                    
                    entries.append((
                        entry.name,
                        self.format_size(size) if size != "" else "",
                        file_type,
                        modified,
                        entry.is_dir()   
                    ))
                except Exception as e:
                    print(f"Error processing {entry.name}: {e}")

            entries.sort(key=lambda x: (not x[4], x[0].lower()))
            
            for entry in entries:
                self.local_tree.insert('', 'end', text=entry[0], values=entry[:-1])
                    
            self.local_path_var.set(self.current_local_dir)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh local files: {str(e)}")

    def refresh_remote_files(self):
        if not self.is_connected:
            return
            
        try:
            for item in self.remote_tree.get_children():
                self.remote_tree.delete(item)
            
            if self.current_remote_dir != "/":
                self.remote_tree.insert('', 'end', text="..", values=("..", "", "Parent Directory", "", ""))
            
            self.ftp.cwd(self.current_remote_dir)
            file_list = []
            self.ftp.retrlines('LIST', file_list.append)
            
            entries = []
            for line in file_list:
                try:
                    parts = line.split(None, 8)
                    if len(parts) < 9:
                        continue
                        
                    permissions = parts[0]
                    size = int(parts[4])
                    date = ' '.join(parts[5:8])
                    name = parts[8]
                    
                    if name in ('.', '..'):
                        continue
                    
                    file_type = 'Directory' if permissions.startswith('d') else 'File'
                    
                    entries.append((
                        name,
                        self.format_size(size) if file_type != 'Directory' else "",
                        file_type,
                        date,
                        permissions,
                        file_type == 'Directory'
                    ))
                except Exception as e:
                    print(f"Error parsing remote file listing: {e}")
            
            entries.sort(key=lambda x: (not x[5], x[0].lower()))
            
            for entry in entries:
                self.remote_tree.insert('', 'end', text=entry[0], values=entry[:-1])
                    
            self.remote_path_var.set(self.current_remote_dir)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh remote files: {str(e)}")

    def quick_connect(self):
        try:
            self.ftp = ftplib.FTP()
            self.ftp.connect(
                self.host_var.get(),
                int(self.port_var.get())
            )
            self.ftp.login(
                self.username_var.get(),
                self.password_var.get()
            )
            self.is_connected = True
            self.current_remote_dir = "/"
            self.refresh_remote_files()
            messagebox.showinfo("Success", "Connected successfully!")
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            self.is_connected = False

    def connect_to_server(self):
        selected = self.server_combo.get()
        if not selected:
            messagebox.showerror("Error", "Please select a server")
            return
            
        server_info = self.saved_servers[selected]
        try:
            self.ftp = ftplib.FTP()
            self.ftp.connect(server_info['host'], int(server_info['port']))
            self.ftp.login(server_info['username'], server_info['password'])
            self.is_connected = True
            self.current_remote_dir = "/"
            self.refresh_remote_files()
            messagebox.showinfo("Success", "Connected successfully!")
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            self.is_connected = False

    def disconnect(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except:
                pass
            finally:
                self.ftp = None
                self.is_connected = False
                for item in self.remote_tree.get_children():
                    self.remote_tree.delete(item)

    def save_server(self):
        name = simpledialog.askstring("Save Server", "Enter a name for this server:")
        if not name:
            return
            
        self.saved_servers[name] = {
            'host': self.host_var.get(),
            'port': self.port_var.get(),
            'username': self.username_var.get(),
            'password': self.password_var.get()
        }
        
        self.server_combo['values'] = list(self.saved_servers.keys())
        
        config_path = Path.home() / '.ftp_client' / 'servers.json'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(config_path, 'w') as f:
                json.dump(self.saved_servers, f)
            messagebox.showinfo("Success", "Server saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save server: {str(e)}")

    def create_folder(self):
        folder_name = simpledialog.askstring("New Folder", "Enter folder name:")
        if not folder_name:
            return

        if self.local_tree.focus():
            try:
                new_path = os.path.join(self.current_local_dir, folder_name)
                os.makedirs(new_path)
                self.refresh_local_files()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create local folder: {str(e)}")
        
        elif self.remote_tree.focus() and self.is_connected:
            try:
                self.ftp.mkd(folder_name)
                self.refresh_remote_files()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create remote folder: {str(e)}")

    def delete_selected(self):
        if self.local_tree.focus():
            selected = self.local_tree.selection()
            if not selected:
                return
                
            if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete the selected items?"):
                for item in selected:
                    path = os.path.join(self.current_local_dir, self.local_tree.item(item)['text'])
                    try:
                        if os.path.isdir(path):
                            shutil.rmtree(path)
                        else:
                            os.remove(path)
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to delete {path}: {str(e)}")
                self.refresh_local_files()
                
        elif self.remote_tree.focus() and self.is_connected:
            selected = self.remote_tree.selection()
            if not selected:
                return
                
            if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete the selected items?"):
                for item in selected:
                    name = self.remote_tree.item(item)['text']
                    try:
                        self.ftp.delete(name)
                    except:
                        try:
                            self.ftp.rmd(name)
                        except Exception as e:
                            messagebox.showerror("Error", f"Failed to delete {name}: {str(e)}")
                self.refresh_remote_files()

    def queue_upload(self):
        if not self.is_connected:
            messagebox.showerror("Error", "Not connected to server")
            return
            
        selected = self.local_tree.selection()
        if not selected:
            return
            
        for item in selected:
            file_path = os.path.join(self.current_local_dir, self.local_tree.item(item)['text'])
            self.queue_transfer('upload', [file_path])

    def queue_download(self):
        if not self.is_connected:
            messagebox.showerror("Error", "Not connected to server")
            return
            
        selected = self.remote_tree.selection()
        if not selected:
            return
            
        for item in selected:
            file_name = self.remote_tree.item(item)['text']
            self.queue_transfer('download', [file_name])

    def queue_transfer(self, direction, files):
        for file in files:
            self.transfer_queue.append({
                'direction': direction,
                'source': file,
                'status': 'queued',
                'progress': 0,
                'speed': '0 KB/s'
            })
        self.update_queue_display()
        if len(self.transfer_queue) == 1:
            self.process_queue()

    def process_queue(self):
        if not self.transfer_queue:
            return
        transfer = self.transfer_queue[0]
        threading.Thread(target=self.process_transfer, args=(transfer,)).start()

    def process_transfer(self, transfer):
        try:
            if transfer['direction'] == 'upload':
                if os.path.isfile(transfer['source']):
                    with open(transfer['source'], 'rb') as f:
                        filename = os.path.basename(transfer['source'])
                        self.ftp.storbinary(f'STOR {filename}', f)
            else:   
                local_path = os.path.join(self.current_local_dir, transfer['source'])
                with open(local_path, 'wb') as f:
                    self.ftp.retrbinary(f'RETR {transfer["source"]}', f.write)
            
            self.refresh_all()
            
        except Exception as e:
            messagebox.showerror("Transfer Error", str(e))
        finally:
            if self.transfer_queue:
                self.transfer_queue.pop(0)
            self.update_queue_display()
            self.process_queue()

    def update_queue_display(self):
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
            
        for transfer in self.transfer_queue:
            self.queue_tree.insert('', 'end', values=(
                transfer['source'],
                '0 KB',
                transfer['status'],
                transfer['speed'],
                f"{transfer['progress']}%"
            ))

    def treeview_sort_column(self, tree, col, reverse):
        l = [(tree.set(k, col), k) for k in tree.get_children('')]
        l.sort(reverse=reverse)
        
        for index, (val, k) in enumerate(l):
            tree.move(k, '', index)
            
        tree.heading(col, command=lambda: self.treeview_sort_column(tree, col, not reverse))

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = FTPClient()
    app.run()
