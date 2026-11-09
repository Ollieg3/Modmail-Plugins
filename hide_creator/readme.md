# 🔒 Hide Ticket Creator for Modmail
. 

A simple security plugin that hides new ticket channels from the user who made them. It keeps the user blocked even if staff move the ticket to a different category or sync permissions.

---

## Features
* **Instant Hide:** Locks out the user as soon as a ticket channel is made.
* **Stays Hidden:** Keeps the block active if staff move the ticket to another category or reset permissions.
* **Auto Detection:** Reads user IDs right from the channel details so it never loses track after a bot restart.
* **Full Lock:** Blocks viewing, reading, and sending messages in the server channel.
* **Easy Toggles:** Turn the feature on or off using simple commands.

---

## Commands

* **`?hidecreator`** — Check if the plugin is on or off.
* **`?hidecreator enable`** — Turn on automatic hiding.
* **`?hidecreator disable`** — Turn off automatic hiding.

---

## Installation

```text
?plugins add Ollieg3/Modmail-Plugins/hide_creator
