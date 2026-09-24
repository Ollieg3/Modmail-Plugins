# ⚡ Sticky Panel for Modmail

> **Note:** Development for this plugin was AI-assisted. 

A dynamic, interactive ticket control panel plugin for Discord Modmail bots that automatically keeps control buttons and category dropdowns pinned to the bottom of active ticket threads.

---

## Features
* **Auto-Sticking Panel:** Automatically reposts and deletes old panels whenever bot messages are sent inside active Modmail threads, keeping controls easily accessible at the bottom.
* **Smart Filtering:** Strictly restricts itself to active Modmail thread channels and ignores normal user/staff chat spam to keep the server clean.
* **Interactive Buttons:** Execute custom bot commands or snippets instantly with configured color styles and row layouts.
* **Category Dropdowns:** Move threads between categories seamlessly straight from the panel menu.
* **Fully Configurable:** Easily add, remove, or preview panels and buttons directly via Discord admin commands using interactive modals and dropdown menus.

---

## Installation

1. Save the plugin code into your bot's plugins or cogs directory (e.g., `sticky_panel.py`).
2. Load the cog/plugin through your bot's setup.
3. Enable and configure the plugin using the administrator commands below.

---

## Commands

All configuration commands require **Administrator** permissions:

* `?stickypanel` — View current sticky panel settings, status, and configured buttons.
* `?stickypanel enable` — Enables the sticky panel listener.
* `?stickypanel disable` — Disables the sticky panel listener.
* `?stickypanel preview` — Sends a preview of the panel embed and buttons in the current channel.
* `?stickypanel addbutton` — Opens an interactive modal to add or edit an action button.
* `?stickypanel removebutton` — Opens a dropdown selector to remove an existing custom button.
* `?stickypanel addcategory` — Opens an interactive modal to add a category dropdown option.
* `?stickypanel removecategory` — Opens a dropdown selector to remove an existing category option.

---

## Configuration

The plugin automatically generates a `sticky_panel_config.json` file in your root directory to save your settings, buttons, and categories safely across bot restarts.
