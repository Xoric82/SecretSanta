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

Open your browser at **[http://localhost:8082](http://localhost:8082)**.

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

## 🏠 Homelab Deployment: Dedicated Proxmox LXC + Nginx Proxy Manager (NPM)

Target External Host: **`santa.xoric.co.uk`**

### 1. Create the Dedicated Proxmox LXC Container
1. In Proxmox VE, create a new LXC container:
   - **Template:** Debian 12 (Bookworm) or Ubuntu 24.04/22.04 LTS.
   - **Resources:** 1 Core, 512 MB RAM, 4 GB Disk (plenty of room for SQLite and logs).
   - **Network:** Assign a static internal IP (e.g., `192.168.1.50/24`) with your gateway and DNS.
2. Start the LXC container and open its console.

### 2. Install Secret Santa in the LXC Container
In your LXC terminal:

```bash
# 1. Ensure git & python3 are installed
apt update && apt install -y git python3

# 2. Clone the repository into /opt/secretsanta
git clone https://github.com/Xoric82/SecretSanta.git /opt/secretsanta
cd /opt/secretsanta

# 3. Create persistent data directory and set permissions
mkdir -p /opt/secretsanta/data
chown -R www-data:www-data /opt/secretsanta

# 4. Install and enable the systemd service
cp /opt/secretsanta/secretsanta.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now secretsanta

# 5. Verify it's active and listening on port 8082
systemctl status secretsanta
```

The service is now running in the background and listening on port `8082`.

---

### 3. Route via Nginx Proxy Manager (NPM)

Open your Nginx Proxy Manager web admin dashboard:

1. Go to **Hosts** &rarr; **Proxy Hosts** &rarr; click **Add Proxy Host**.
2. **Details Tab**:
   - **Domain Names:** `santa.xoric.co.uk`
   - **Scheme:** `http`
   - **Forward Hostname / IP:** `<LXC-IP>` (e.g. `192.168.1.50` or container hostname)
   - **Forward Port:** `8082`
   - **Cache Assets:** `ON` (optional, improves performance)
   - **Block Common Exploits:** `ON`
   - **Websockets Support:** `ON`
3. **SSL Tab**:
   - **SSL Certificate:** *Request a new SSL Certificate*
   - **Force SSL:** `ON`
   - **HTTP/2 Support:** `ON`
   - **HSTS Enabled:** `ON`
   - Enter your email and agree to Let's Encrypt ToS.
4. Click **Save**.

Your family can now visit **`https://santa.xoric.co.uk`** securely from any phone, tablet, or PC!

---

### Alternative: Caddy Reverse Proxy Configuration

If routing through Caddy instead of NPM, add this block to your `/etc/caddy/Caddyfile`:

```caddyfile
santa.xoric.co.uk {
    reverse_proxy 127.0.0.1:8082 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "strict-origin-when-cross-origin"
    }

    encode zstd gzip
}
```
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
