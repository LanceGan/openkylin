//! Virtual keyboard via /dev/uinput — types the real password into the real
//! greeter, driving genuine PAM authentication (no autologin shortcut).
#![cfg(target_os = "linux")]

use std::fs::File;
use std::thread::sleep;
use std::time::Duration;

use anyhow::{Context, Result};
use input_linux::{
    EventKind, EventTime, InputEvent, InputId, Key, KeyEvent, KeyState, SynchronizeEvent,
    SynchronizeKind, UInputHandle,
};

use crate::observe::keymap;

/// X11/libinput need a moment to enumerate a hot-plugged keyboard.
const DEVICE_SETTLE: Duration = Duration::from_millis(500);
/// Inter-key delay — far slower than the input pipeline, far faster than a human.
const KEY_DELAY: Duration = Duration::from_millis(50);

pub struct UinputKeyboard {
    handle: UInputHandle<File>,
}

impl UinputKeyboard {
    /// Open /dev/uinput and create the virtual device.
    ///
    /// This doubles as the injection self-check required by the
    /// Tlogin-ready gate (spec §4.2): success here proves keystrokes can be
    /// delivered.  Requires root — the kbl-observe.service unit provides it.
    pub fn create() -> Result<Self> {
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open("/dev/uinput")
            .context("open /dev/uinput failed (observer must run as root)")?;
        let handle = UInputHandle::new(file);
        handle.set_evbit(EventKind::Key).context("EV_KEY")?;
        handle.set_evbit(EventKind::Synchronize).context("EV_SYN")?;
        for code in keymap::all_supported_keycodes() {
            let key = Key::from_code(code).context("unmapped key code")?;
            handle.set_keybit(key).context("UI_SET_KEYBIT")?;
        }
        let id = InputId {
            bustype: input_linux::sys::BUS_VIRTUAL,
            vendor: 0x4b42,  // "KB"
            product: 0x4c50, // "LP"
            version: 1,
        };
        handle
            .create(&id, b"kbl-bootprobe-virtual-keyboard", 0, &[])
            .context("UI_DEV_CREATE failed")?;
        sleep(DEVICE_SETTLE);
        Ok(Self { handle })
    }

    /// Type the password followed by Enter — exactly once.  The caller must
    /// never retry a failed login (account-lockout protection, spec §8).
    pub fn type_password_and_enter(&mut self, password: &str) -> Result<()> {
        let codes = keymap::login_keycodes(password)
            .context("password contains characters outside [a-z0-9]")?;
        for code in codes {
            let key = Key::from_code(code).context("unmapped key code")?;
            self.emit(key, KeyState::PRESSED)?;
            sleep(KEY_DELAY);
            self.emit(key, KeyState::RELEASED)?;
            sleep(KEY_DELAY);
        }
        Ok(())
    }

    fn emit(&mut self, key: Key, state: KeyState) -> Result<()> {
        let time = EventTime::new(0, 0);
        let events = [
            *InputEvent::from(KeyEvent::new(time, key, state)).as_raw(),
            *InputEvent::from(SynchronizeEvent::new(time, SynchronizeKind::Report, 0)).as_raw(),
        ];
        self.handle.write(&events).context("uinput write failed")?;
        Ok(())
    }
}

impl Drop for UinputKeyboard {
    fn drop(&mut self) {
        let _ = self.handle.dev_destroy();
    }
}
