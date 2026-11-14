"""
palettier.watch — Real-time GNOME/D-Bus/file monitoring and polling fallback.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from palettier.state import (
    DEBOUNCE_SECONDS,
    RPM_WAIT_POLL_SECONDS,
    RPM_WAIT_TIMEOUT_SECONDS,
    is_package_transaction_active,
)
from palettier.sync import update_theme
from palettier.wallpaper import get_current_wallpaper_path

resync_source_id: list[int | None] = [None]
_fallback_timer_lock = threading.Lock()
_fallback_timer: list[threading.Timer | None] = [None]


def cancel_pending_resync() -> None:
    """Cancel any pending debounce timer (GLib or fallback threading.Timer)."""
    if resync_source_id[0] is not None:
        try:
            import gi

            gi.require_version("GLib", "2.0")
            from gi.repository import GLib

            GLib.source_remove(resync_source_id[0])
        except Exception:
            pass
        resync_source_id[0] = None

    with _fallback_timer_lock:
        if _fallback_timer[0] is not None:
            _fallback_timer[0].cancel()
            _fallback_timer[0] = None


def trigger_wallpaper_resync(
    reason: str = "suspend resume",
    delay_seconds: float = DEBOUNCE_SECONDS,
    wallpaper_path: Path | str | None = None,
) -> None:
    """
    Schedule a debounced theme sync (default 2.0s) to consolidate signal bursts
    from dbus-broker, dconf, and inotify before evaluating desktop state.
    """
    delay = max(1.5, float(delay_seconds))

    try:
        import gi

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib

        if resync_source_id[0] is not None:
            GLib.source_remove(resync_source_id[0])
            resync_source_id[0] = None

        wait_ctx: dict[str, object] = {"logged": False, "deadline": None}

        def _do_resync():
            if is_package_transaction_active():
                if wait_ctx["deadline"] is None:
                    wait_ctx["deadline"] = time.monotonic() + RPM_WAIT_TIMEOUT_SECONDS
                if time.monotonic() >= float(wait_ctx["deadline"]):
                    print("[!] Timed out waiting for RPM/DNF transaction to finish.")
                    resync_source_id[0] = None
                    return GLib.SOURCE_REMOVE
                if not wait_ctx["logged"]:
                    print("[*] RPM/DNF transaction in progress. Waiting before evaluating state...")
                    wait_ctx["logged"] = True
                resync_source_id[0] = GLib.timeout_add(int(RPM_WAIT_POLL_SECONDS * 1000), _do_resync)
                return GLib.SOURCE_REMOVE

            resync_source_id[0] = None
            print(f"\n[*] [{reason}] Evaluating wallpaper state...")
            update_theme(wallpaper_path=wallpaper_path)
            return GLib.SOURCE_REMOVE

        resync_source_id[0] = GLib.timeout_add(int(delay * 1000), _do_resync)
    except Exception:
        with _fallback_timer_lock:
            if _fallback_timer[0] is not None:
                _fallback_timer[0].cancel()

            def _do_fallback_resync() -> None:
                with _fallback_timer_lock:
                    _fallback_timer[0] = None
                print(f"\n[*] [{reason}] Evaluating wallpaper state...")
                update_theme(wallpaper_path=wallpaper_path)

            timer = threading.Timer(delay, _do_fallback_resync)
            timer.daemon = True
            _fallback_timer[0] = timer
            timer.start()


def watch_mode() -> None:
    """Real-time daemon listening to GNOME GSettings, file changes, and D-Bus events."""
    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib
    except ImportError:
        print("[!] PyGObject (gi) not found. Falling back to periodic polling mode.")
        polling_mode()
        return

    print("[*] Starting real-time wallpaper watcher...")
    update_theme()

    loop = GLib.MainLoop()
    current_monitors: dict[str, object] = {"file": None, "path": None}

    def setup_wallpaper_file_monitor(wp_path: Path | None) -> None:
        """Monitor the wallpaper file in case an external tool overwrites it in place."""
        if not wp_path or not wp_path.exists():
            return
        if current_monitors["path"] == wp_path:
            return

        if current_monitors["file"] is not None:
            try:
                current_monitors["file"].cancel()  # type: ignore[union-attr]
            except Exception:
                pass
            current_monitors["file"] = None

        current_monitors["path"] = wp_path
        try:
            gfile = Gio.File.new_for_path(str(wp_path))
            f_mon = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)

            def on_file_changed(mon, f, of, ev):
                if ev in (Gio.FileMonitorEvent.CHANGED, Gio.FileMonitorEvent.CHANGES_DONE_HINT):
                    trigger_wallpaper_resync(
                        reason="Wallpaper file modified",
                        delay_seconds=DEBOUNCE_SECONDS,
                    )

            f_mon.connect("changed", on_file_changed)
            current_monitors["file"] = f_mon
        except Exception:
            pass

    initial_wp = get_current_wallpaper_path()
    setup_wallpaper_file_monitor(initial_wp)

    try:
        bg_settings = Gio.Settings.new("org.gnome.desktop.background")
        iface_settings = Gio.Settings.new("org.gnome.desktop.interface")

        def on_bg_changed(settings, key):
            new_wp = get_current_wallpaper_path()
            setup_wallpaper_file_monitor(new_wp)
            trigger_wallpaper_resync(
                reason=f"Wallpaper change detected ({key})",
                delay_seconds=DEBOUNCE_SECONDS,
            )

        bg_settings.connect("changed::picture-uri", on_bg_changed)
        bg_settings.connect("changed::picture-uri-dark", on_bg_changed)
        iface_settings.connect("changed::color-scheme", on_bg_changed)
        print("[*] GNOME Desktop (GSettings) event listener enabled.")
    except Exception as e:
        print(f"[*] Direct GSettings listener unavailable ({e}).")

    try:
        sys_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        if sys_bus:

            def on_prepare_for_sleep(conn, sender, path, iface, signal, params, user_data):
                try:
                    going_to_sleep = params.get_child_value(0).get_boolean()
                    if not going_to_sleep:
                        print("\n[*] [D-Bus] System resume from suspend detected!")
                        trigger_wallpaper_resync(
                            reason="Suspend Resume",
                            delay_seconds=DEBOUNCE_SECONDS,
                        )
                except Exception as e:
                    print(f"[!] Error handling PrepareForSleep: {e}")

            sys_bus.signal_subscribe(
                "org.freedesktop.login1",
                "org.freedesktop.login1.Manager",
                "PrepareForSleep",
                "/org/freedesktop/login1",
                None,
                Gio.DBusSignalFlags.NONE,
                on_prepare_for_sleep,
                None,
            )
            print("[*] Systemd-logind D-Bus suspend listener enabled.")
    except Exception as e:
        print(f"[*] D-Bus suspend listener unavailable ({e}).")

    try:
        session_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        if session_bus:

            def on_screensaver_changed(conn, sender, path, iface, signal, params, user_data):
                try:
                    is_active = params.get_child_value(0).get_boolean()
                    if not is_active:
                        print("\n[*] [D-Bus] Screen unlock detected!")
                        trigger_wallpaper_resync(
                            reason="Screen Unlock",
                            delay_seconds=DEBOUNCE_SECONDS,
                        )
                except Exception as e:
                    print(f"[!] Error handling ScreenSaver signal: {e}")

            for ss_iface in ("org.gnome.ScreenSaver", "org.freedesktop.ScreenSaver"):
                session_bus.signal_subscribe(
                    None,
                    ss_iface,
                    "ActiveChanged",
                    None,
                    None,
                    Gio.DBusSignalFlags.NONE,
                    on_screensaver_changed,
                    None,
                )
            print("[*] Screen unlock listener enabled.")
    except Exception as e:
        print(f"[*] ScreenSaver listener unavailable ({e}).")

    last_tick_time = [time.monotonic()]

    def check_time_jump():
        now = time.monotonic()
        elapsed = now - last_tick_time[0]
        last_tick_time[0] = now
        if elapsed > 5.0:
            print(f"\n[*] [Timer] Resume detected via monotonic time jump ({elapsed:.1f}s elapsed)!")
            trigger_wallpaper_resync(
                reason="Suspend Resume (Time Jump)",
                delay_seconds=DEBOUNCE_SECONDS,
            )
        return GLib.SOURCE_CONTINUE

    GLib.timeout_add_seconds(1, check_time_jump)

    print("[*] Watching for wallpaper and color-scheme changes.")
    print("[*] Press Ctrl+C to stop.")
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n[*] Watcher stopped.")


def polling_mode() -> None:
    """Fallback mode polling wallpaper file timestamps periodically."""
    print("[*] Polling mode active. Checking every 2 seconds...")
    last_wp = get_current_wallpaper_path()
    last_mtime = last_wp.stat().st_mtime if last_wp and last_wp.exists() else 0
    last_tick = time.monotonic()
    update_theme()

    try:
        while True:
            now = time.monotonic()
            if now - last_tick > 6.0:
                print(f"\n[*] [Polling] Resume detected ({now - last_tick:.1f}s elapsed)!")
                time.sleep(1)
                update_theme()
            last_tick = time.monotonic()

            curr_wp = get_current_wallpaper_path()
            curr_mtime = curr_wp.stat().st_mtime if curr_wp and curr_wp.exists() else 0

            if curr_wp != last_wp or (curr_mtime != last_mtime and curr_mtime > 0):
                last_wp = curr_wp
                last_mtime = curr_mtime
                print("\n[*] Wallpaper change detected!")
                update_theme()

            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[*] Watcher stopped.")
