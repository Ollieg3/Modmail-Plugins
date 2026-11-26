# Support Panel for Modmail

A Modmail plugin that adds a dropdown menu so users can pick a support topic and open a ticket.

---

## Features

* **Category Dropdown** Lets users pick from a menu to open a ticket,
* **Open DM and Ticket Checks** Stops users with an open ticket from making another one, and checks that DMs are open first.
* **Category Routing** Sends new tickets into a chosen category channel ID on your staff server.
* **Auto Commands** Runs a command, alias, or snippet inside the new ticket channel after it opens.
* **Easy Setup and Edits** Set up the panel step by step or change parts of it later.
* **Saved Settings** Saves your setup to a file and keeps the dropdown working after bot restarts.

---

## Commands

* **?supportsetup** Run the step by step setup for colors, title, text, options, and posting.
* **?supportpanel** Show the current panel settings and options.
* **?supportpanel send #channel** Post the dropdown panel in a channel or the current channel.
* **?supportedit** Show all edit commands.
* **?supportedit color #hex or default** Change the embed color.
* **?supportedit title text or default** Change the embed title.
* **?supportedit description text** Change the embed text.
* **?supportedit alias option command or clear** Set or clear the auto command for an option.
* **?supportedit option option field value or clear** Change one part of an option like label, desc, emoji, or category.
* **?supportedit addoption label | desc | emoji | category_id | alias** Add a new dropdown option.
* **?supportedit removeoption option** Remove a dropdown option by number or name.

---

## Installation

Add the plugin to your Modmail bot

```text
?plugin add Ollieg3/Modmail-Plugins/dropdown_menu
