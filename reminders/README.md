# ⏰ Reminders for Modmail

> **Note:** Development for this plugin was AI-assisted. 

A lightweight, feature-rich reminder plugin for Discord Modmail bots that allows staff to set quick or natural-language reminders for themselves or other team members directly inside active tickets.

---

## Features
* **Natural Language & Relative Time:** Supports traditional relative durations (`30m`, `2h`, `1d`) as well as human-readable dates and times (`tomorrow 3pm`, `next Tuesday 4pm`).
* **Staff Delegation:** Easily set reminders for yourself or assign follow-ups to another team member by mentioning them (`-remind @user <time> <message>`).
* **Dual Delivery Alerts:** Automatically dispatches an alert ping inside the ticket channel *and* a direct message (DM) to the target user when the timer expires.
* **Persistent Storage:** Safely saves all active reminders to a local JSON file so nothing is lost during bot restarts.
* **Simple Management:** List all pending reminders in the current ticket channel or cancel them instantly using a unique 6-digit ID.

---

## Commands

* **`-remind <time> <message>`** — Set a reminder for yourself (e.g., `-remind 30m Check logs`).
* **`-remind @user <time> <message>`** — Set a reminder for another staff member (e.g., `-remind @Alex tomorrow 3pm Follow up`).
* **`-reminders`** — View active reminders set in the current channel.
* **`-delremind <id>`** — Cancel a pending reminder using its ID.

---

## Installation

```text
?plugins add Ollieg3/Modmail-Plugins/reminders

