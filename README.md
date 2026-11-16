# 🖥️ RDP Switcher — Modern Dynamic Island Notch for Windows

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?style=for-the-badge&logo=windows)](https://github.com/romflasher3419-spec/rdp-switcher)
[![Architecture](https://img.shields.io/badge/Architecture-x64-black?style=for-the-badge)](https://github.com/romflasher3419-spec/rdp-switcher)
[![Release](https://img.shields.io/badge/Release-v2.0-00FFA3?style=for-the-badge)](https://github.com/romflasher3419-spec/rdp-switcher/releases)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

An ultra-sleek, iOS-style glossy **Dynamic Island notch** for switching between multiple Remote Desktop (`mstsc`, `msrdc`) sessions on Windows. Floats seamlessly at the top edge of your screen, even over full-screen RDP windows!

---

## ✨ Features

- 🏝️ **Liquid Glass Dynamic Island:** Collapses into a minimal capsule `( ◉ 3 RDP › )` at the top edge; expands smoothly on cursor hover into a full glass control dock.
- ⚡ **Instant 1-Click RDP Switch:** Brings any remote desktop session to the front, maximized, with zero lag.
- 🏷️ **Smart IP Badging:** Displays the exact remote server IP or machine name directly beneath each RDP button.
- ♾️ **Unlimited RDPs with Horizontal Scrolling:** Handles 1 to 50+ concurrent RDP windows with interactive `◀` and `▶` glass scroll arrows.
- 💻 **`[ My PC ]` Button:** Instantly minimizes active RDP sessions to return to your local host desktop.
- 🛑 **`[ Close All ]` Button:** Terminate all remote sessions simultaneously with a single click.
- 🚪 **`[ Exit ]` Button:** Clean, instant 1-click shutdown directly from the dock.
- 🔒 **Fullscreen Topmost Lock:** Never gets hidden under fullscreen Remote Desktop windows.
- ⌨️ **Global Hotkeys:**
  - `Ctrl + Alt + 0` $\rightarrow$ Return to **My PC**
  - `Ctrl + Alt + 1..9` $\rightarrow$ Switch directly to **RDP 1 through 9**
- 🎨 **Anti-Aliased Per-Pixel Rendering:** Crisp rounded corners with dark outer borders, glass gradient highlights, and active-session neon indicators.
- 📦 **100% Standalone & Portable:** Single `.exe` file — **NO Python, NO dependencies, NO admin rights required!**

---

## 🚀 Quick Start

### Option 1: Standalone Portable EXE (Recommended)
1. Download **`RDP_Switcher.exe`** from [Releases](https://github.com/romflasher3419-spec/rdp-switcher/releases).
2. Double-click `RDP_Switcher.exe`.
3. The compact notch will appear pinned to the top-left of your primary screen. Hover your cursor over it to reveal the full switcher!

### Option 2: Run from Python Source
Requires Python 3.8+ (Standard Library only — no `pip install` needed):
```bash
git clone https://github.com/romflasher3419-spec/rdp-switcher.git
cd rdp-switcher
pythonw rdp_switcher.py
```

---

## ⚙️ Configuration (`rdp_switcher_config.json`)

Place `rdp_switcher_config.json` in the same directory as `RDP_Switcher.exe` to customize your dock:

```json
{
  "ISLAND_ANCHOR": "left",
  "ISLAND_MARGIN_X": 20,
  "ISLAND_MARGIN_Y": 0,
  "ISLAND_EXPANDED_H": 66,
  "ISLAND_MAX_W": 0,
  "HOVER_PAD": 18,
  "HIDE_DELAY": 0,
  "INSTANT_HIDE": false,
  "ANIM_STEPS": 10,
  "ANIM_MS": 16,
  "REFRESH_MS": 1200,
  "POLL_MS": 40,
  "BTN_CORNER_R": 12,
  "BTN_BORDER_PX": 3,
  "BTN_RIM_DARKEN": 0.5,
  "MYPC_ENABLED": true,
  "MYPC_MODE": "rdp",
  "MYPC_HOTKEY": true,
  "MYPC_ACTIVATE_LOCAL": true,
  "CLOSEALL_ENABLED": true,
  "CLOSEALL_FOLLOWUP_MS": 300,
  "EXIT_ENABLED": true,
  "MAXIMIZE_ON_SWITCH": true,
  "ENABLE_HOTKEYS": true,
  "SORT_MODE": "hwnd",
  "ACTION_LOG": true,
  "RDP_PROCESSES": [
    "mstsc.exe",
    "msrdc.exe"
  ]
}
```

---

## 🛠️ Diagnostics

Run `check_rdp_windows.bat` to instantly view detected RDP windows, window titles, process IDs, and resolved IP addresses.

---

## 📄 License

MIT License — free for personal and commercial use. Developed by [romflasher3419-spec](https://github.com/romflasher3419-spec).
