# 🎄 Family Secret Santa

A simple, private, self-hosted Secret Santa web application designed specifically for families and homelab environments (e.g. Proxmox LXC/VM with Caddy as the reverse proxy).

Built with **native Modern Web Standards** following [Google Chrome's Modern Web Guidance](https://github.com/GoogleChrome/modern-web-guidance) and backed by a lightweight, zero-configuration **SQLite** database.

---

## ✨ Features

- **User Accounts & Roles:**
  - Simple registration & login with secure password hashing (`PBKDF2-HMAC-SHA256`).
  - The first family member to register automatically becomes the **Organiser**.
- **Wishlist Management:**
  - Add items with titles, details, size/color notes, store links, price estimates, and priority ratings.
  - Edit or delete items anytime.
- **Strict Secret Santa Privacy Shield:**
  - Users can view any other family member's wishlist and mark items as **Purchased** (or unmark if bought by mistake).
  - **The owner of the wishlist NEVER sees which items have been purchased or who bought them.** This privacy is enforced strictly at the database/API level, so even inspecting network traffic will never spoil the surprise!
  - Other family members can see what has already been purchased, preventing duplicate gifts.
- **Fair & Guaranteed Secret Santa Draw:**
  - Uses a single-cycle derangement algorithm (Hamiltonian cycle): $P(i) \neq i$.
  - Everyone gives exactly one gift and receives exactly one gift.
  - No one is ever assigned to themselves.
  - Eliminates isolated two-person closed loops.
  - Even the organiser does not see other members' matches in the UI, keeping the secret safe for everyone.
- **Modern Web Standards (Google Chrome Modern Web Guidance):**
  - Native `<dialog>` elements for modals (`showModal()` & `close()`) with native `::backdrop` styling.
  - Modern CSS: CSS Custom Properties, fluid `clamp()` typography, CSS Grid & Flexbox, and CSS `:has()` relational selectors.
  - Accessible form validation with `:user-invalid`.
  - Automatic Light & Dark mode support via `color-scheme: light dark`.
  - Native **View Transitions API** for silky smooth state changes.
  - Screen reader accessibility with live announcements (`aria-live="polite"`).
  - Zero heavy frontend dependencies (no bloated JS bundles, no complex compilation step).

---

## 🚀 Quick Start (Local Run)

The application has **zero external package dependencies** — it runs directly with Python 3.8+ using only Python standard library modules (`http.server`, `sqlite3`, `hashlib`, `secrets`, `json`).

```bash
# 1. Clone or navigate to the directory
cd SecretSanta

# 2. Start the server
python3 server.py
```

Open your browser at **[http://localhost:8080](http://localhost:8080)**.

The first account you register will automatically be given the `organiser` role.

---

## 🧪 Running Automated Tests

Run the test suites for database logic and end-to-end API flows:

```bash
# Database unit tests (matching fairness, privacy rules, CRUD)
python3 test_database.py

# Full API & server integration tests
python3 test_server.py
```

---

## 🏠 Hosting on Homelab (Proxmox + Caddy)

### Option A: Running with Docker Compose (Recommended)

If you run Docker in a Proxmox LXC or VM:

1. Clone or copy this repository to your server:
   ```bash
   git clone <repo-url> /opt/secretsanta
   cd /opt/secretsanta
   ```

2. Start the container:
   ```bash
   docker compose up -d
   ```
   Data is stored in `./data/secretsanta.db` and persists across container updates.

---

### Option B: Running directly with systemd (Debian/Ubuntu Proxmox LXC)

If you run a lightweight Debian or Ubuntu LXC container without Docker:

1. Copy the project to `/opt/secretsanta`:
   ```bash
   mkdir -p /opt/secretsanta/data
   cp -r * /opt/secretsanta/
   chown -R www-data:www-data /opt/secretsanta
   ```

2. Install and enable the systemd service:
   ```bash
   cp /opt/secretsanta/secretsanta.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now secretsanta
   ```

3. Check status:
   ```bash
   systemctl status secretsanta
   ```

---

### Caddy Configuration

Add the following block to your `/etc/caddy/Caddyfile` on your Caddy host:

```caddyfile
santa.yourfamilydomain.com {
    # Reverse proxy to Secret Santa port 8080
    reverse_proxy 127.0.0.1:8080 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }

    # Security headers
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "strict-origin-when-cross-origin"
    }

    encode zstd gzip
}
```

Reload Caddy:
```bash
sudo systemctl reload caddy
```

Caddy will automatically provision and renew Let's Encrypt / ZeroSSL TLS certificates.

---

## 🔒 Security & Privacy Details

1. **Wishlist Purchase Secrecy:**
   - The query returning wishlist items dynamically masks purchase information if `viewer_id == target_user_id`:
   ```python
   # Owner never sees purchase status or buyer
   item["is_purchased"] = None
   item["buyer_name"] = None
   ```
   - Owners cannot mark their own wishlist items as purchased.
2. **Password Security:**
   - Passwords hashed with `PBKDF2-HMAC-SHA256` using 100,000 rounds and a 16-byte cryptographically random salt per user.
3. **Session Cookies:**
   - Issued with `HttpOnly`, `SameSite=Lax`, and a 30-day expiration window.
4. **SQLite Concurrency:**
   - Enabled Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) and enforced Foreign Key constraints (`PRAGMA foreign_keys = ON;`) for high concurrency without database lock contention.
