#!/usr/bin/env python3
"""
MediaDownloader v3.0 — GTK4 / libadwaita
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, Gio, GdkPixbuf, Gdk

import threading
import subprocess
import shutil
import os
import json
import base64
from pathlib import Path
from datetime import datetime

# ─── Icono SVG embebido ──────────────────────────────────────────────────────
APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#7c6af7"/>
      <stop offset="100%" stop-color="#a78bfa"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="14" fill="url(#bg)"/>
  <!-- flecha de descarga -->
  <line x1="32" y1="10" x2="32" y2="38" stroke="white" stroke-width="5"
        stroke-linecap="round"/>
  <polyline points="18,26 32,42 46,26" fill="none" stroke="white"
            stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  <!-- barra inferior -->
  <rect x="14" y="50" width="36" height="5" rx="2.5" fill="white" opacity="0.85"/>
</svg>"""

CONFIG_DIR   = Path.home() / ".config" / "media-downloader"
CONFIG_FILE  = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"download_path": str(Path.home() / "Downloads"), "notify": True}

def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass
    return []

def save_history(h):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(h[-100:], indent=2))

def send_notification(title, body):
    try:
        subprocess.run(["notify-send", "-i", "folder-download",
                        "-t", "4000", title, body], capture_output=True)
    except Exception:
        pass

def install_ytdlp(callback):
    def _run():
        methods = [
            ["pip3", "install", "--quiet", "--break-system-packages", "yt-dlp"],
            ["pip3", "install", "--quiet", "yt-dlp"],
            ["pip",  "install", "--quiet", "yt-dlp"],
        ]
        for cmd in methods:
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=120)
                if r.returncode == 0 and shutil.which("yt-dlp"):
                    GLib.idle_add(callback, True, cmd[0])
                    return
            except Exception:
                pass
        url  = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
        dest = "/usr/local/bin/yt-dlp"
        for dl in [["wget", "-qO", dest, url], ["curl", "-sSL", url, "-o", dest]]:
            try:
                r = subprocess.run(dl, capture_output=True, timeout=120)
                if r.returncode == 0:
                    os.chmod(dest, 0o755)
                    GLib.idle_add(callback, True, dl[0])
                    return
            except Exception:
                pass
        GLib.idle_add(callback, False, "")
    threading.Thread(target=_run, daemon=True).start()


# ─── Ventana principal ───────────────────────────────────────────────────────

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="MediaDownloader")
        self.set_default_size(740, 680)
        self.set_resizable(False)

        self.cfg     = load_config()
        self.history = load_history()
        self.process = None
        self.downloading = False
        self.ytdlp_ok = False

        self._build_ui()
        self._check_ytdlp()

    # ── Construcción de UI ────────────────────────────────────────────────

    def _build_ui(self):
        # Toast overlay como raíz
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # ToolbarView
        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        # HeaderBar
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title="MediaDownloader",
            subtitle="Descarga video y música de cualquier plataforma"))

        # Botón historial
        hist_btn = Gtk.Button(label="Historial")
        hist_btn.set_icon_name("document-open-recent-symbolic")
        hist_btn.add_css_class("flat")
        hist_btn.connect("clicked", self._show_history)
        header.pack_start(hist_btn)

        # Botón actualizar yt-dlp
        upd_btn = Gtk.Button(label="Actualizar yt-dlp")
        upd_btn.set_icon_name("software-update-available-symbolic")
        upd_btn.add_css_class("flat")
        upd_btn.connect("clicked", self._update_ytdlp)
        header.pack_end(upd_btn)

        toolbar_view.add_top_bar(header)

        # Contenido principal con scroll
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar_view.set_content(scroll)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(20)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)
        scroll.set_child(main_box)

        # ── URL ──────────────────────────────────────────────────────────
        url_group = Adw.PreferencesGroup(title="URL")
        url_group.set_description("Pega el enlace del video, canción o lista")
        main_box.append(url_group)

        url_row = Adw.EntryRow(title="https://…")
        url_row.set_show_apply_button(False)
        self.url_entry = url_row
        url_group.add(url_row)

        # Botón pegar debajo del grupo
        paste_btn = Gtk.Button(label="✂  Pegar desde portapapeles")
        paste_btn.add_css_class("pill")
        paste_btn.set_halign(Gtk.Align.START)
        paste_btn.connect("clicked", self._paste_url)
        main_box.append(paste_btn)

        # ── Tipo de descarga ──────────────────────────────────────────────
        type_group = Adw.PreferencesGroup(title="Tipo de descarga")
        main_box.append(type_group)

        # Toggle video/audio
        self.toggle_video = Gtk.ToggleButton(label="🎬  Video")
        self.toggle_audio = Gtk.ToggleButton(label="🎵  Solo Audio")
        self.toggle_audio.set_group(self.toggle_video)
        self.toggle_video.set_active(True)
        self.toggle_video.add_css_class("suggested-action")
        self.toggle_video.connect("toggled", self._on_mode_toggle)
        self.toggle_audio.connect("toggled", self._on_mode_toggle)

        toggle_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toggle_box.set_homogeneous(True)
        toggle_box.append(self.toggle_video)
        toggle_box.append(self.toggle_audio)
        toggle_box.set_margin_bottom(4)

        type_group.add(toggle_box)

        # Playlist
        pl_row = Adw.ActionRow(title="Descargar lista completa",
                               subtitle="Descarga toda la playlist si la URL es una lista")
        self.pl_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        pl_row.add_suffix(self.pl_switch)
        pl_row.set_activatable_widget(self.pl_switch)
        type_group.add(pl_row)

        # ── Calidad y formato ─────────────────────────────────────────────
        opt_group = Adw.PreferencesGroup(title="Calidad y formato")
        main_box.append(opt_group)

        # Calidad
        quality_row = Adw.ActionRow(title="Calidad")
        self.quality_combo = Gtk.DropDown.new_from_strings(
            ["Mejor disponible", "1080p", "720p", "480p", "360p"])
        self.quality_combo.set_valign(Gtk.Align.CENTER)
        quality_row.add_suffix(self.quality_combo)
        opt_group.add(quality_row)

        # Formato
        format_row = Adw.ActionRow(title="Formato")
        self.format_combo = Gtk.DropDown.new_from_strings(
            ["MP4", "MKV", "WEBM"])
        self.format_combo.set_valign(Gtk.Align.CENTER)
        format_row.add_suffix(self.format_combo)
        opt_group.add(format_row)
        self.format_row = format_row

        # Notificaciones
        notif_row = Adw.ActionRow(title="Notificaciones de escritorio",
                                  subtitle="Avisar al completar cada descarga")
        self.notif_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.notif_switch.set_active(self.cfg.get("notify", True))
        self.notif_switch.connect("state-set", self._save_prefs)
        notif_row.add_suffix(self.notif_switch)
        notif_row.set_activatable_widget(self.notif_switch)
        opt_group.add(notif_row)

        # ── Carpeta destino ───────────────────────────────────────────────
        dest_group = Adw.PreferencesGroup(title="Destino")
        main_box.append(dest_group)

        dest_row = Adw.ActionRow(
            title="Carpeta de descarga",
            subtitle=self.cfg.get("download_path", str(Path.home() / "Downloads")))
        self.dest_row = dest_row
        folder_btn = Gtk.Button(icon_name="folder-open-symbolic",
                                valign=Gtk.Align.CENTER)
        folder_btn.add_css_class("flat")
        folder_btn.connect("clicked", self._choose_dir)
        dest_row.add_suffix(folder_btn)
        dest_group.add(dest_row)

        # ── Progreso ──────────────────────────────────────────────────────
        prog_group = Adw.PreferencesGroup(title="Progreso")
        main_box.append(prog_group)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_pulse_step(0.06)
        self.progress_bar.set_margin_start(8)
        self.progress_bar.set_margin_end(8)
        self.progress_bar.set_margin_top(4)
        prog_group.add(self.progress_bar)

        self.status_row = Adw.ActionRow(title="Listo para descargar")
        self.status_row.add_css_class("property")
        prog_group.add(self.status_row)

        # Log
        log_frame = Gtk.Frame()
        log_frame.add_css_class("card")
        log_sw = Gtk.ScrolledWindow()
        log_sw.set_min_content_height(120)
        log_sw.set_max_content_height(120)
        log_sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.log_buffer = Gtk.TextBuffer()
        self.log_view   = Gtk.TextView(buffer=self.log_buffer,
                                       editable=False, cursor_visible=False,
                                       monospace=True, wrap_mode=Gtk.WrapMode.WORD)
        self.log_view.set_margin_start(8)
        self.log_view.set_margin_end(8)
        self.log_view.set_margin_top(6)
        self.log_view.set_margin_bottom(6)
        log_sw.set_child(self.log_view)
        log_frame.set_child(log_sw)
        prog_group.add(log_frame)

        # ── Botones acción ────────────────────────────────────────────────
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        action_box.set_halign(Gtk.Align.CENTER)
        action_box.set_margin_top(4)
        main_box.append(action_box)

        self.dl_btn = Gtk.Button(label="⬇  Descargar")
        self.dl_btn.add_css_class("suggested-action")
        self.dl_btn.add_css_class("pill")
        self.dl_btn.set_size_request(180, 44)
        self.dl_btn.connect("clicked", self._start_download)
        action_box.append(self.dl_btn)

        self.cancel_btn = Gtk.Button(label="✕  Cancelar")
        self.cancel_btn.add_css_class("destructive-action")
        self.cancel_btn.add_css_class("pill")
        self.cancel_btn.set_size_request(130, 44)
        self.cancel_btn.set_sensitive(False)
        self.cancel_btn.connect("clicked", self._cancel)
        action_box.append(self.cancel_btn)

        # Timer para pulsar barra
        self._pulse_timer = None

    # ── yt-dlp ───────────────────────────────────────────────────────────

    def _check_ytdlp(self):
        if shutil.which("yt-dlp"):
            self.ytdlp_ok = True
            self._set_status("yt-dlp y ffmpeg listos ✓")
            return
        self._set_status("⚙ Instalando yt-dlp en segundo plano…")
        self._log("yt-dlp no encontrado. Instalando automáticamente…\n")
        install_ytdlp(self._on_ytdlp_done)

    def _on_ytdlp_done(self, ok, method):
        if ok:
            self.ytdlp_ok = True
            self._set_status("yt-dlp listo ✓")
            self._log(f"✅ yt-dlp instalado ({method})\n")
            self.toast("yt-dlp instalado correctamente")
        else:
            self._set_status("⚠ yt-dlp no disponible — instálalo con pip3")
            self._log("❌ No se pudo instalar yt-dlp automáticamente.\n"
                      "   Ejecuta: pip3 install yt-dlp\n")
        return False

    def _update_ytdlp(self, *_):
        if not shutil.which("yt-dlp"):
            self.toast("yt-dlp aún no está instalado")
            return
        self._log("\n🔄 Actualizando yt-dlp…\n")
        self._start_pulse()
        def _do():
            r = subprocess.run(["yt-dlp", "-U"], capture_output=True, text=True)
            GLib.idle_add(self._log, r.stdout + r.stderr + "\n")
            GLib.idle_add(self._stop_pulse)
            GLib.idle_add(self.toast, "yt-dlp actualizado ✓")
        threading.Thread(target=_do, daemon=True).start()

    # ── Helpers UI ───────────────────────────────────────────────────────

    def _set_status(self, text):
        self.status_row.set_title(text)

    def _log(self, text):
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end, text)
        # scroll al final
        adj = self.log_view.get_parent().get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    def _log_clear(self):
        self.log_buffer.set_text("")

    def toast(self, msg):
        self.toast_overlay.add_toast(Adw.Toast(title=msg, timeout=3))

    def _start_pulse(self):
        self._stop_pulse()
        self._pulse_timer = GLib.timeout_add(80, self._pulse_cb)

    def _pulse_cb(self):
        self.progress_bar.pulse()
        return True

    def _stop_pulse(self):
        if self._pulse_timer:
            GLib.source_remove(self._pulse_timer)
            self._pulse_timer = None
        self.progress_bar.set_fraction(0)
        return False

    # ── Acciones ─────────────────────────────────────────────────────────

    def _on_mode_toggle(self, btn):
        if not btn.get_active():
            return
        if self.toggle_video.get_active():
            self.format_combo.set_model(
                Gtk.StringList.new(["MP4", "MKV", "WEBM"]))
        else:
            self.format_combo.set_model(
                Gtk.StringList.new(["MP3", "M4A", "OPUS", "FLAC", "WAV"]))
        self.format_combo.set_selected(0)

    def _paste_url(self, *_):
        clipboard = self.get_clipboard()
        clipboard.read_text_async(None, self._on_clipboard_text)

    def _on_clipboard_text(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
            if text:
                self.url_entry.set_text(text.strip())
        except Exception:
            pass

    def _choose_dir(self, *_):
        dialog = Gtk.FileDialog(title="Seleccionar carpeta de destino")
        dialog.select_folder(self, None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                path = folder.get_path()
                self.dest_row.set_subtitle(path)
                self.cfg["download_path"] = path
                save_config(self.cfg)
        except Exception:
            pass

    def _save_prefs(self, *_):
        self.cfg["notify"] = self.notif_switch.get_active()
        save_config(self.cfg)
        return False

    def _get_mode(self):
        return "video" if self.toggle_video.get_active() else "audio"

    def _get_quality(self):
        labels = ["best", "1080", "720", "480", "360"]
        idx = self.quality_combo.get_selected()
        return labels[idx] if idx < len(labels) else "best"

    def _get_format(self):
        item = self.format_combo.get_selected_item()
        return item.get_string().lower() if item else "mp4"

    def _build_cmd(self, url):
        out   = self.cfg.get("download_path", str(Path.home() / "Downloads"))
        mode  = self._get_mode()
        q     = self._get_quality()
        fmt   = self._get_format()
        pl    = self.pl_switch.get_active()

        cmd = ["yt-dlp", "--newline"]
        cmd += ["--yes-playlist" if pl else "--no-playlist"]

        tpl = (f"{out}/%(playlist_title)s/%(title)s.%(ext)s" if pl
               else f"{out}/%(title)s.%(ext)s")

        if mode == "audio":
            cmd += ["-x", "--audio-format", fmt]
            if q != "best":
                cmd += ["--audio-quality", f"{q}k"]
        else:
            # Correcto para todos los contenedores video:
            # 1) Intentar mejor video+audio disponible
            # 2) Remuxear/recodificar al formato deseado
            if q == "best":
                f_sel = "bestvideo+bestaudio/best"
            else:
                f_sel = f"bestvideo[height<={q}]+bestaudio/best[height<={q}]/best"
            cmd += ["-f", f_sel, "--merge-output-format", fmt]

        cmd += ["-o", tpl, url]
        return cmd, fmt

    def _start_download(self, *_):
        if not self.ytdlp_ok and not shutil.which("yt-dlp"):
            self.toast("yt-dlp aún no está listo, espera unos segundos")
            return
        url = self.url_entry.get_text().strip()
        if not url:
            self.toast("Ingresa una URL primero")
            return
        if not url.startswith(("http://", "https://")):
            self.toast("La URL debe comenzar con http:// o https://")
            return

        os.makedirs(self.cfg.get("download_path",
                    str(Path.home() / "Downloads")), exist_ok=True)

        self.downloading = True
        self.dl_btn.set_sensitive(False)
        self.cancel_btn.set_sensitive(True)
        self._log_clear()
        self._set_status("Descargando…")
        self._start_pulse()
        self._current_url = url

        cmd, fmt = self._build_cmd(url)
        self._current_fmt = fmt
        self._log("$ " + " ".join(cmd) + "\n\n")
        threading.Thread(target=self._run, args=(cmd,), daemon=True).start()

    def _run(self, cmd):
        try:
            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1)
            for line in self.process.stdout:
                GLib.idle_add(self._log, line)
            self.process.wait()
            GLib.idle_add(self._finish, self.process.returncode)
        except FileNotFoundError:
            GLib.idle_add(self._log, "\n❌ yt-dlp no encontrado.\n")
            GLib.idle_add(self._finish, 1)

    def _finish(self, rc):
        self._stop_pulse()
        self.downloading = False
        self.dl_btn.set_sensitive(True)
        self.cancel_btn.set_sensitive(False)

        url = getattr(self, "_current_url", "")
        fmt = getattr(self, "_current_fmt", "")

        if rc == 0:
            self._set_status("✓ Descarga completada")
            self._log("\n✅ ¡Descarga completada!\n")
            self.toast("Descarga completada ✓")
            entry = {
                "url":  url, "mode": self._get_mode(),
                "fmt":  fmt,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "dest": self.cfg.get("download_path", ""),
            }
            self.history.append(entry)
            save_history(self.history)
            if self.notif_switch.get_active():
                send_notification("MediaDownloader",
                                  f"Descarga completada ({fmt.upper()})")
        elif rc in (-9, -15):
            self._set_status("Cancelado")
        else:
            self._set_status(f"❌ Error (código {rc})")
            self._log(f"\n❌ Error (código {rc})\n")
            self.toast(f"Error en la descarga (código {rc})")
            if self.notif_switch.get_active():
                send_notification("MediaDownloader", "La descarga falló")
        return False

    def _cancel(self, *_):
        if self.process and self.downloading:
            self.process.terminate()
            self._log("\n⚠ Descarga cancelada.\n")

    # ── Historial ─────────────────────────────────────────────────────────

    def _show_history(self, *_):
        win = Adw.Window(title="Historial", transient_for=self, modal=True)
        win.set_default_size(680, 420)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        win.set_content(box)

        hdr = Adw.HeaderBar()
        hdr.set_title_widget(Gtk.Label(label="Historial de descargas"))
        box.append(hdr)

        if not self.history:
            empty = Adw.StatusPage(
                title="Sin historial",
                description="Las descargas completadas aparecerán aquí",
                icon_name="document-open-recent-symbolic")
            box.append(empty)
        else:
            scroll = Gtk.ScrolledWindow(vexpand=True)
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            box.append(scroll)

            list_box = Gtk.ListBox()
            list_box.add_css_class("boxed-list")
            list_box.set_margin_start(16)
            list_box.set_margin_end(16)
            list_box.set_margin_top(16)
            list_box.set_margin_bottom(8)
            list_box.set_selection_mode(Gtk.SelectionMode.NONE)
            scroll.set_child(list_box)

            for entry in reversed(self.history):
                row = Adw.ActionRow(
                    title=entry.get("url", ""),
                    subtitle=f"{entry.get('date','')}  •  "
                             f"{entry.get('mode','').upper()}  •  "
                             f"{entry.get('fmt','').upper()}")
                list_box.append(row)

            btn_row = Gtk.Box(spacing=8)
            btn_row.set_margin_start(16)
            btn_row.set_margin_end(16)
            btn_row.set_margin_bottom(16)
            btn_row.set_margin_top(8)
            box.append(btn_row)

            clear_btn = Gtk.Button(label="🗑  Borrar historial")
            clear_btn.add_css_class("destructive-action")
            clear_btn.add_css_class("pill")

            def clear(*_):
                dialog = Adw.AlertDialog(
                    heading="¿Borrar historial?",
                    body="Esta acción no se puede deshacer.")
                dialog.add_response("cancel", "Cancelar")
                dialog.add_response("delete", "Borrar")
                dialog.set_response_appearance(
                    "delete", Adw.ResponseAppearance.DESTRUCTIVE)
                def _on_resp(d, resp):
                    if resp == "delete":
                        self.history.clear()
                        save_history(self.history)
                        win.close()
                        self.toast("Historial borrado")
                dialog.connect("response", _on_resp)
                dialog.present(win)

            clear_btn.connect("clicked", clear)
            btn_row.append(clear_btn)

        win.present()


# ─── Aplicación ─────────────────────────────────────────────────────────────

class MediaDownloaderApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.MediaDownloader",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.connect("activate", self._on_activate)

    def _on_activate(self, app):
        # CSS mínimo
        css = Gtk.CssProvider()
        css.load_from_string("""
            .log-view { font-family: monospace; font-size: 9pt; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Icono de la app desde SVG embebido
        try:
            loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
            loader.write(APP_ICON_SVG.encode())
            loader.close()
            pixbuf = loader.get_pixbuf()
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self.get_windows()  # ensure window list ready
        except Exception:
            texture = None

        win = MainWindow(self)

        if texture:
            try:
                win.set_icon(pixbuf)
            except Exception:
                pass

        win.present()


if __name__ == "__main__":
    import sys
    app = MediaDownloaderApp()
    sys.exit(app.run(sys.argv))
