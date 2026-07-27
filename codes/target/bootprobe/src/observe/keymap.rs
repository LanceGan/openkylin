//! Character → Linux evdev key-code mapping for uinput injection.
//!
//! Only lowercase ASCII letters and digits are supported by design: the
//! test password is constrained to that charset (spec §10) so injection is
//! independent of keyboard layout (QWERTY scancode positions).

/// `KEY_ENTER` from `<linux/input-event-codes.h>`.
pub const KEY_ENTER: u16 = 28;

/// evdev codes are contiguous along physical QWERTY rows.
const ROWS: [(&str, u16); 3] = [
    ("qwertyuiop", 16), // KEY_Q..KEY_P
    ("asdfghjkl", 30),  // KEY_A..KEY_L
    ("zxcvbnm", 44),    // KEY_Z..KEY_M
];

/// evdev key code for one password character; `None` outside `[a-z0-9]`.
pub fn keycode_for(character: char) -> Option<u16> {
    match character {
        '0' => return Some(11),                                      // KEY_0
        '1'..='9' => return Some(character as u16 - '1' as u16 + 2), // KEY_1..KEY_9
        _ => {}
    }
    for (row, first) in ROWS {
        if let Some(index) = row.find(character) {
            return Some(first + u16::try_from(index).expect("row index fits in u16"));
        }
    }
    None
}

/// Key sequence for a full login: every password character, then Enter.
/// `None` if any character falls outside the supported charset.
pub fn login_keycodes(password: &str) -> Option<Vec<u16>> {
    let mut codes: Vec<u16> = password.chars().map(keycode_for).collect::<Option<_>>()?;
    codes.push(KEY_ENTER);
    Some(codes)
}

/// Every key code the virtual keyboard must register (charset + Enter).
pub fn all_supported_keycodes() -> Vec<u16> {
    let mut codes: Vec<u16> = "abcdefghijklmnopqrstuvwxyz0123456789"
        .chars()
        .filter_map(keycode_for)
        .collect();
    codes.push(KEY_ENTER);
    codes
}
