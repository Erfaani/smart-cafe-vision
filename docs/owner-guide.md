# Owner's guide

This page is for you if you run the café, not the computer. It assumes
someone has already installed Smart Café Vision on a computer at your
venue and connected your cameras — if that hasn't happened yet, that part
is technical setup and is covered in [installation.md](installation.md)
instead, written for whoever does that for you.

Everything below is what you do once it's running.

---

## What this actually does

Cameras you already have watch the room and count people — how many are
here, and how long each one stays. It does **not** recognise faces, does
**not** know anyone's name, and does **not** save video. It sees a person
as a moving box for as long as they're in frame, times how long that box
sticks around, and then forgets it the moment they leave. Nothing about a
specific customer is ever kept.

Two things come out of that counting:

- **A dashboard**, for you and your staff, showing how busy you are right
  now and over time.
- **A screen in the café** (optional), showing customers something playful
  — how busy it is, how long people tend to stay, a message you wrote.

## Signing in

Open the dashboard's web address in a browser (whoever installed it will
have given you this — it looks like `http://192.168.1.50:3000` or similar,
or a proper address if you have one). Enter the email and password you
were given. If it's your first time, change your password straightaway:
click your name in the top-right corner to open **Your account**.

If the page won't load at all, see [Troubleshooting](#troubleshooting)
before assuming something is broken.

## Finding your way around

The left-hand menu has four groups.

**Overview** — the front page. At a glance: is everything connected, how
busy you are right now, and any warnings that need your attention.

**Live** — what's happening right now.
- *Live cameras* — a live preview from each camera.
- *Customers* — everyone currently in the room, and how long they've been
  there, colour-coded (green means just arrived, sliding to red the longer
  someone stays).
- *Tables* — which tables are currently occupied, if you've set up table
  tracking (see [Setting up tables](#setting-up-tables) below).

**Insights** — *Analytics*: trends over days, weeks, or months. Busiest
hours, average visit length, how full you get at your peak.

**Configuration** — everything you set up once and rarely touch again.
- *Cameras* — add, edit, or remove a camera; test that one is connecting
  properly.
- *Public display* — turn the café-facing screen on or off, and adjust
  what it shows.
- *Messages* — the rotating line of text shown on the public display (see
  below).
- *Staff* — who can sign in to this dashboard, and with what level of
  access.
- *Café settings* — your café's name and logo, timezone, seating capacity,
  the colours used for how-long-they've-stayed, and your customer-facing
  privacy notice.

## Setting up a new camera

1. **Configuration → Cameras → Add camera.**
2. Fill in the camera's network address (your installer or the camera's
   manual will have this) and, if the camera needs a login, its username
   and password.
3. Click **Test** before saving. It tells you plainly if something's
   wrong — camera unreachable, wrong password, wrong address — rather
   than a vague error.
4. Save, then make sure it's switched to **Enabled**. Within about 15
   seconds it should start showing a live preview.

**A camera by itself only counts what's in frame — it doesn't yet know
where your door is.** To actually count people entering and leaving, open
that camera from **Cameras** and draw a line across your doorway on its
image (an arrow shows which direction counts as "coming in"). Without
this line, that camera won't contribute to your Customers or Analytics
numbers.

## Setting up tables

If you want to know which tables are occupied and for how long, open a
camera from **Cameras → Tables** and draw a rectangle over each table on
its image, the same way you drew the entrance line above.

This works best from a camera mounted **directly overhead** a table — it
can then be confident about who's actually seated there. A camera mounted
on the wall, looking at a table from an angle, can only approximate: a
person standing near the table can register the same as one sitting down.
When you add or edit a camera, there's a setting for how it's mounted
(**overhead** / **wall-mounted** / unknown) — set this honestly, and the
Tables page will show a caveat automatically wherever the reading is only
an approximation, so you're never shown a confident-looking number that
isn't one.

## The public display

A screen in the café (a TV, a tablet, anything with a browser) can show a
rotating, customer-facing view: how busy you are, a light-hearted "longest
visit today" moment, and any messages you've written. It cycles through
these automatically — nothing for anyone to click.

To turn it on, point that screen's browser at your display address (shown
on **Configuration → Public display**, something like
`http://192.168.1.50:3000/display/your-cafe-name`). No one needs to sign
in on that screen — it's meant to be public, the same way a menu board is.

**It never shows real camera footage**, even on this public screen — just
a simple animated dot for each person, coloured by how long they've been
there. Nobody in the room can be identified by looking at it.

### Writing messages

**Configuration → Messages** — add a short line (English, and Persian if
you want it), like *"Did you know our beans are roasted locally?"* It
joins the rotation on the public display. Keep it general — a fun fact, a
specials board, a thank-you — never anything that singles out a specific
person or table. Turn a message off with the **Active/Disabled** toggle
without deleting it, if you want to pause it for a while.

## Managing staff accounts

**Configuration → Staff** — add an account for anyone who needs to see the
dashboard: their email, a temporary password, and a role.

| Role | Can do |
|---|---|
| Owner | Everything |
| Manager | Everything within your café — cameras, staff, café settings |
| Staff | View live data and analytics only, no settings |
| Viewer | Same as Staff — read-only |

`Staff` and `Viewer` currently behave identically (both read-only); `Viewer`
exists as a separate option for a future finer-grained distinction. Give
someone the lowest role that covers what they need — a barista checking how
busy it is only needs **Staff**.

**If someone forgets their password**, there's no "forgot password" email
link — the system doesn't send email at all, on purpose, so it keeps
working even with no internet connection. Instead, on the Staff page,
click **Reset password** next to their name. A new password appears once,
on screen — write it down or read it to them immediately, because it
won't be shown again. They should change it to something only they know
the moment they sign in.

**Removing someone.** Click **Deactivate** rather than trying to delete
them — this immediately stops them signing in, while keeping the record
of who did what. You cannot deactivate your own account (so you can never
accidentally lock yourself out) — ask another owner or manager to do it
if you're leaving.

## Café settings

**Configuration → Café settings** covers:

- **Name and logo** — shown on the public display.
- **Seating capacity** — used to calculate "how full" as a percentage.
- **Timezone** — makes sure "today's" numbers reset at your actual
  midnight, not somewhere else's.
- **Stay-time colours** — the green-to-red scale used everywhere a
  customer's time in the café is shown. The default (green under 30
  minutes, amber by 30, red by an hour) suits most cafés; adjust it if
  your venue naturally has longer or shorter visits.
- **Privacy notice** — the text shown to customers (on the public display
  and printed as in-venue signage) explaining that the camera system is
  anonymous. Edit it if your venue has specific local wording
  requirements — see [privacy.md](privacy.md).

## What this system does *not* do

Worth knowing so you can answer a customer's question confidently:

- It does not recognise faces or match a return visitor to their last
  visit.
- It does not save video. Camera footage is processed the instant it
  arrives and then thrown away — nothing is written to a hard drive.
- It cannot tell staff or customers apart by name — it only sees
  anonymous, moving boxes.
- Nothing leaves the building. All of this runs on the computer at your
  venue; none of your customers' movement data is sent anywhere online
  (unless you've specifically asked your technician to turn on optional
  crash reporting, which never includes camera data — see
  [production.md](production.md)).

Full detail, including what to tell a data-protection inspector, is in
[privacy.md](privacy.md).

## Troubleshooting

**A camera shows "offline" or "disconnected."** Check its power and
network cable (or wifi) first — that's the cause the great majority of the
time. If it's plugged in and still not connecting, click **Test** on that
camera in **Configuration → Cameras** for a specific reason.

**The dashboard won't load at all, for anyone.** The computer running the
system may be off or restarting. Check it's powered on. If it is and the
dashboard still won't load, this is a job for your technician.

**A camera is connected but not counting anyone.** Check that camera has
an entrance line drawn on it (**Cameras** → that camera → **Zones**) — a
camera with no line drawn shows a live preview but doesn't contribute to
your customer count.

**Table occupancy looks wrong on one camera.** Check that camera's mount
type is set correctly (overhead vs. wall-mounted) under **Cameras** — a
wall-mounted camera's table readings are only ever an approximation; that
is expected, not a fault.

**Everything looks fine but the numbers seem off just after opening or
just before closing.** Check the café's timezone under **Café settings** —
a wrong timezone shifts when "today" starts and ends.

### When to call your technician instead

Everything above is something you can handle yourself. Call whoever set
the system up for you if:

- the computer itself won't turn on or is making unusual noises,
- you need a new camera physically installed or wired,
- you want the system moved to new hardware or reinstalled,
- or anything in [installation.md](installation.md) or
  [production.md](production.md) — those pages assume technical
  familiarity this one deliberately doesn't.
