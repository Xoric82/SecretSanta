# Family Secret Santa: Project Overview

A self-hosted Secret Santa web app for one family, running on a Proxmox homelab behind Caddy or Nginx Proxy Manager at `santa.xoric.co.uk`. This document records what has been built, how it fits together, and what is still open. For install and deployment steps, see [README.md](README.md).

---

## 1. Original requirements and their status

| Requirement | Status | Where |
|---|---|---|
| Users can register and log in | ✅ Done | `create_user`, `authenticate_user` in [database.py](database.py); `/api/register` and `/api/login` |
| Users create a wishlist | ✅ Done | `wishlist_items` table; add, edit and delete items in the UI |
| Users view other users' wishlists | ✅ Done | **Family Lists** page, `GET /api/wishlist/<id>` |
| Organiser role triggers the draw | ✅ Done | The first registered user becomes `organiser`. `POST /api/draw` is limited to the organiser. |
| Random recipient that is never yourself | ✅ Done | Single-cycle draw (§5) |
| Mark items on other lists as purchased | ✅ Done | `POST /api/wishlist/<item>/purchase`, which toggles the mark |
| The owner never sees purchase status, but everyone else does | ✅ Done | Enforced in the API and database layer, not only in the UI (§6) |
| Lightweight database | ✅ Done | SQLite in WAL mode, using only the standard library |
| Web client follows Chrome Modern Web Guidance | ✅ Mostly | Native `<dialog>`, View Transitions, `:has()`, `:user-invalid`, `color-scheme`, ES modules, `aria-live`. The views still use a lot of inline styles and `innerHTML` templates. |
| **Next step:** a parent creates *n* children and manages their lists | ✅ Done (this change) | §4 |
| **Next step:** children can be selectively included in the draw | ✅ Done (this change) | §4 |

Additional features that were already built: a family registration passcode (`REGISTRATION_PASSPHRASE` in `.env`), event settings (name, budget, reveal date, rules note), a draw reset, a Dockerfile and compose file, a systemd unit, and a Caddyfile.

---

## 2. Architecture

Nothing needs to be installed. The app runs on Python 3.8+ using only the standard library. The frontend is plain HTML, CSS and JavaScript with no build step.

```
Browser (SPA, hash routing)
   │  fetch() JSON  +  HttpOnly session cookie
   ▼
server.py   ThreadingHTTPServer
   │        - serves /public (static files, SPA fallback)
   │        - /api/* REST routes, auth and permission checks
   ▼
database.py sqlite3 (WAL, foreign keys ON)
   │        - schema + idempotent migrations
   │        - all business rules: draw, privacy masking, ownership
   ▼
secretsanta.db
```

| File | Purpose |
|---|---|
| [server.py](server.py) | HTTP server, routing, sessions and cookies, static file serving, and security headers |
| [database.py](database.py) | Schema, migrations, auth (PBKDF2-SHA256 with 100k iterations), draw algorithm, wishlist and purchase logic, child profiles |
| [public/index.html](public/index.html) | Page shell and every `<dialog>`: item, draw, reset, settings, child |
| [public/js/app.js](public/js/app.js) | SPA state, hash router, and the views: landing, auth, dashboard, wishlist, family, children, organiser |
| [public/css/styles.css](public/css/styles.css) | Design tokens with light and dark themes, and component styles |
| [manage.py](manage.py) | Command-line admin tool: `list`, `unlock <user>` and `reset-password <user>`, for when the organiser is the one locked out |
| [test_database.py](test_database.py), [test_server.py](test_server.py) | `unittest` suites for the database layer and an end-to-end HTTP test |
| `Dockerfile`, `docker-compose.yml`, `secretsanta.service`, `Caddyfile`, `.env.example` | Deployment files |

Configuration comes from environment variables or `.env`: `PORT` (default 8082), `HOST`, `SECRETSANTA_DB`, `REGISTRATION_PASSPHRASE` and `COOKIE_SECURE` (`auto`, `true` or `false`).

---

## 3. Data model

```
users ─┬─< wishlist_items ──< purchases (item_id PK → one buyer per item)
       │        (user_id)        (buyer_id → users)
       ├─< sessions
       ├─< assignments (giver_id PK, receiver_id; CHECK giver != receiver)
       └─< users (parent_id → child profiles)          event_settings (single row, id = 1)
```

| Table | Key columns |
|---|---|
| `users` | `username` (unique, case-insensitive), `display_name`, `password_hash`, `salt`, `role` (`organiser` or `user`), **`parent_id`** (NULL for adults, the parent's id for children), **`in_draw`** (0/1, default 1), **`failed_logins`**, **`locked_until`**, **`must_change_password`** |
| `wishlist_items` | `user_id`, `title`, `description`, `url`, `price`, `priority` (1 = normal, 2 = top pick) |
| `purchases` | `item_id` (PK), `buyer_id`, `purchased_at` |
| `assignments` | `giver_id` (PK), `receiver_id`, `assigned_at` |
| `event_settings` | `event_name`, `budget_limit`, `reveal_date`, `rules_note`, `is_drawn`, `drawn_at`, **`avoid_household`** (default 1) |

Columns in **bold** were added after the first release (children, then account security). `init_db()` runs `_migrate()`, which adds them with `ALTER TABLE` to an existing database, so an existing `secretsanta.db` upgrades in place on the next start without losing data.

---

## 4. Child profiles (new)

### What a parent can do
- Open the **Children 🧒** page and add any number of children (capped at 20 per parent as an abuse limit). Each child needs only a name.
- Rename or remove a child. Removing a child deletes their wishlist, purchase marks and assignment through cascading deletes.
- **Manage Wishlist** opens the child's list in *parent view*, where the parent can add, edit and delete items. The parent also sees which items have been bought, because the child never logs in and someone has to coordinate their presents.
- Tick or untick **Include in Secret Santa draw** for each child, either when adding the child or later.
- After the draw, the dashboard shows "**Emma is buying for Bob**" so the parent can shop on the child's behalf.

### What everyone else sees
- On **Family Lists**, children have a 🧒 *Child* badge, "Child of <parent>", and a *Not in draw* badge if they are excluded. Anyone can open a child's list and mark items as purchased, exactly as for an adult.

### What the organiser sees
- The roster lists adults and children, with "Managed by <parent>" on each child and an inclusion checkbox for **everyone**, adults included. The organiser can, for example, exclude a relative who only wants a wishlist.
- **Event Settings → Keep households apart** (on by default).

### Design decisions
- **Children are rows in `users` with a `parent_id`**, not a separate table. Wishlists, purchases, assignments and the privacy masking then work for children without any new code paths.
- **Children cannot log in.** Each child gets an internal placeholder username and a random, unusable password. `authenticate_user` also rejects any row with a `parent_id`, and the API returns `username: null` for children.
- **Draw rules:**
  - A child is **never** assigned to give to their own parent. The parent would see "Emma → you" and learn who their own Santa is.
  - When *Keep households apart* is on, nobody is matched inside their household, defined as one parent plus the children they manage. Two adults who live together are separate households, because the app has no link between adult accounts.
- **Inclusion is frozen once names are drawn.** Toggling inclusion, adding a child who is in the draw, or removing a child who is in the draw returns a clear error until the organiser resets. Without this, the draw could end up with a gap in the cycle. A child added *outside* the draw can still be created after the draw.
- **Permissions:** parents control their own children. The organiser can toggle inclusion for anyone but cannot edit other people's children's wishlists.

### New and changed API

| Method and path | Who | Purpose |
|---|---|---|
| `GET /api/children` | signed in | List my children |
| `POST /api/children` `{display_name, in_draw}` | signed in | Create a child |
| `PUT /api/children/<id>` `{display_name}` | parent | Rename |
| `DELETE /api/children/<id>` | parent | Remove the child and their list |
| `POST /api/users/<id>/draw` `{in_draw: bool}` | parent (own children) or organiser (anyone) | Include or exclude from the draw |
| `POST /api/wishlist` `{…, user_id}` | owner or parent | `user_id` is optional; it adds the item to a managed child's list |
| `PUT` / `DELETE /api/wishlist/<item>` | owner or parent | Now also allowed for a child's items |
| `GET /api/wishlist/<id>` | **signed in** | Now also returns `can_manage`, `user.is_child`, `user.parent_display_name` and `user.in_draw` |
| `GET /api/me` | signed in | Now also returns `children` and `children_assignments` |
| `POST /api/event/update` | organiser | Accepts `avoid_household` |

---

## 5. The draw algorithm

`perform_secret_santa_draw()` in [database.py](database.py):

1. Takes everyone with `in_draw = 1`, adults and children. At least 2 are required.
2. If *Keep households apart* is on and one household is more than half of the participants, a valid draw is impossible. It fails at once with a message that suggests what to change.
3. `_find_gift_cycle()` searches for a **single Hamiltonian cycle** (A→B→C→…→A) using `secrets.SystemRandom`, with randomised backtracking and a feasibility check for pruning. A single cycle means nobody draws themselves, everyone gives once and receives once, and there are no closed two-person swaps unless n = 2.
4. Writes `assignments` and sets `is_drawn`. Each user's `/api/me` returns only their own recipient, plus their children's recipients for a parent. Nobody, including the organiser, can see the full set of pairings.

The tests run 50 draws with mixed households and assert that the rules hold every time. They also cover the impossible cases (one dominant household, or a parent with one child) to confirm they fail with a message instead of producing a bad draw.

---

## 6. Privacy and security model

- **Purchase secrecy:** `get_wishlist()` returns `is_purchased: null` and `buyer_name: null` whenever `viewer == owner`, so the hidden data never reaches the owner's browser. Owners cannot mark their own items as purchased.
- **Sign-in now required to read wishlists (fixed in this change):** previously `GET /api/wishlist/<id>` accepted anonymous requests and treated them as a non-owner viewer. Anyone, *including the list's owner in a private window*, could see what had been bought and by whom. It now returns 401 without a session. `/api/event` also no longer returns the participant list to anonymous visitors.
- Passwords are hashed with PBKDF2-HMAC-SHA256, 100k iterations and a per-user salt.
- **Session cookie:** a random 32-byte token in an `HttpOnly; SameSite=Lax` cookie lasting 30 days. `Secure` is added when the proxy reports HTTPS (`X-Forwarded-Proto`), or always or never with `COOKIE_SECURE`. The token is not returned in JSON bodies. API responses are `Cache-Control: no-store`. Expired sessions are purged at startup and on each login.
- **Lockout:** 5 failed sign-ins lock an account for 30 minutes. Each attempt is reserved inside a `BEGIN IMMEDIATE` transaction *before* the password is checked, so concurrent guesses can't go beyond the limit (a test fires 20 at once). The organiser can unlock an account early. Unknown usernames still pay the hashing cost, so response timing doesn't reveal which usernames exist.
- **Organiser password reset:** generates a 12-character temporary password from an unambiguous character set, shown to the organiser once. It also clears any lock and signs the user out everywhere. Until they choose a new password, that user's session can only reach `/api/me`, `/api/logout` and `/api/account/password`. Every other endpoint returns `403 password_change_required`, and the UI shows only the change-password screen.
- **Changing your own password** (My Account) requires the current password, except straight after a reset. It also signs out your other sessions.
- The family passcode on registration is compared in constant time. The server sends the `nosniff`, `X-Frame-Options` and `Referrer-Policy` security headers.

---

## 7. Review findings

### Fixed in this change
| Issue | Fix |
|---|---|
| Anonymous users could read any wishlist with its purchase status and buyer names, which defeated the core secrecy rule | Signing in is now required for wishlist and participant endpoints |
| `POST /api/draw` would silently reshuffle an active draw. The UI hid the button, but the API allowed the call. | The API now returns 409 and asks for a reset first |
| A non-numeric `priority` crashed the request handler without a JSON error | Priority is now parsed safely and falls back to 1 |
| A JSON body that is not an object (for example `[]`) crashed handlers | It is now rejected as an invalid body |
| The README had a duplicated, broken Caddy code block | Removed |
| The server tests shared one database across tests, so the results depended on test order | Each test now gets a fresh database |

### Fixed in the account-security change
| Issue | Fix |
|---|---|
| No way to recover a forgotten password | The organiser resets it to a temporary password and the user must change it at next sign-in. Users can change their own password. `manage.py` covers the organiser's own account. |
| The session cookie had no `Secure` flag, and the token was also returned in the JSON body | `Secure` is added over HTTPS (configurable), and the token is removed from response bodies |
| Unlimited password guessing | 5 failed attempts give a 30-minute lock that the organiser can lift, and concurrent guesses can't get extra tries |
| Expired sessions were never deleted | They are purged at startup and on each login |

### Still open (suggested next steps, roughly by value)
1. **The organiser can't remove or rename a user, or hand over the organiser role.**
2. **Registration isn't rate-limited.** The family passcode protects it, but the passcode itself can be guessed without limit. A per-IP limit would need the real client IP from the proxy (`X-Forwarded-For`).
3. **Lockout can be used to annoy.** Anyone who knows a username can lock that account for 30 minutes. This is the expected trade-off of per-account lockout, and the organiser can unlock it. The minimum password length is still 4 characters.
4. **No request body size limit.** `Content-Length` is trusted as sent.
5. **Frontend polish:** `updateView()` does not handle the View Transition promise, so an unhandled rejection is logged when a transition is skipped. Many views use inline styles. The Family Lists page has no search or sort.
6. **No way to link two adult accounts as one household,** for example partners. *Keep households apart* currently covers only a parent and their children.

---

## 8. Running and testing

```bash
python3 server.py              # http://localhost:8082
python3 test_database.py       # 11 tests: auth, privacy, draw, children, households, migration, lockout, resets
python3 test_server.py         # 6 tests: end-to-end API, children, passcode, cookie flags, lockout, forced change
```

The new UI views were also checked in headless Chrome against a seeded database: the Children page, the parent and outsider views of a child's list, Family Lists, the organiser roster, and the post-draw dashboard and Children page.
