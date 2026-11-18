/**
 * Secret Santa App - Modern Web Client
 * Following Google Chrome Modern Web Guidance (MWG):
 * - ES Modules
 * - View Transitions API for seamless state updates
 * - Native <dialog> (showModal / close)
 * - Semantic DOM construction & XSS-safe textContent rendering
 * - Accessible Live Announcer (aria-live)
 * - Hash-based client routing
 */

// Application State
const state = {
  currentUser: null,       // { id, username, display_name, role }
  event: null,             // { event_name, budget_limit, reveal_date, rules_note, is_drawn }
  assignment: null,        // { receiver_id, receiver_display_name, wishlist_count }
  participants: [],        // array of user objects
  currentWishlist: null,   // { user, is_owner, items }
  currentRoute: 'home',
  routeParam: null
};

// ==========================================
// Accessibility & Toast Notifications
// ==========================================

function announce(message) {
  const liveEl = document.getElementById('live-announcer');
  if (liveEl) {
    liveEl.textContent = '';
    // slight tick to ensure screen readers detect change
    setTimeout(() => { liveEl.textContent = message; }, 50);
  }
}

function showToast(message, type = 'info') {
  announce(message);
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.25s ease-out';
    setTimeout(() => toast.remove(), 250);
  }, 3500);
}

// ==========================================
// API Client Layer
// ==========================================

async function api(endpoint, options = {}) {
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    },
    ...options
  };

  try {
    const res = await fetch(endpoint, config);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || `HTTP error ${res.status}`);
    }
    return data;
  } catch (err) {
    console.error(`API Error on ${endpoint}:`, err);
    throw err;
  }
}

// ==========================================
// Modal Helpers (Modern Native <dialog>)
// ==========================================

function setupDialog(dialogId) {
  const dialog = document.getElementById(dialogId);
  if (!dialog) return;

  // Close when clicking outside dialog window (on the ::backdrop)
  dialog.addEventListener('click', (e) => {
    const rect = dialog.getBoundingClientRect();
    const isInDialog = (
      rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
      rect.left <= e.clientX && e.clientX <= rect.left + rect.width
    );
    if (!isInDialog) {
      dialog.close();
    }
  });

  // Close buttons with data-action="close-dialog"
  dialog.querySelectorAll('[data-action="close-dialog"]').forEach(btn => {
    btn.addEventListener('click', () => dialog.close());
  });
}

// ==========================================
// Routing & State Transitions
// ==========================================

function navigate(hash) {
  window.location.hash = hash;
}

function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, '') || 'home';
  const parts = raw.split('/');
  return {
    route: parts[0] || 'home',
    param: parts[1] || null
  };
}

// Wrapped with native View Transitions API if supported
function updateView(renderFn) {
  if (document.startViewTransition) {
    document.startViewTransition(() => renderFn());
  } else {
    renderFn();
  }
}

// ==========================================
// View Rendering
// ==========================================

function renderNav() {
  const nav = document.getElementById('main-nav');
  const badge = document.getElementById('header-event-badge');
  if (badge && state.event) {
    badge.textContent = state.event.event_name;
  }

  nav.replaceChildren();

  if (!state.currentUser) {
    const loginLink = document.createElement('a');
    loginLink.href = '#login';
    loginLink.textContent = 'Log In';
    if (state.currentRoute === 'login') loginLink.classList.add('active');

    const registerLink = document.createElement('a');
    registerLink.href = '#register';
    registerLink.textContent = 'Register';
    registerLink.className = 'btn btn-primary btn-sm';
    if (state.currentRoute === 'register') registerLink.classList.add('active');

    nav.append(loginLink, registerLink);
    return;
  }

  // Logged-in navigation
  const homeLink = document.createElement('a');
  homeLink.href = '#home';
  homeLink.textContent = 'Dashboard';
  if (state.currentRoute === 'home') homeLink.classList.add('active');

  const myWishlistLink = document.createElement('a');
  myWishlistLink.href = '#my-wishlist';
  myWishlistLink.textContent = 'My Wishlist 🎁';
  if (state.currentRoute === 'my-wishlist') myWishlistLink.classList.add('active');

  const familyLink = document.createElement('a');
  familyLink.href = '#family';
  familyLink.textContent = 'Family Lists 🎄';
  if (state.currentRoute === 'family') familyLink.classList.add('active');

  nav.append(homeLink, myWishlistLink, familyLink);

  if (state.currentUser.role === 'organiser') {
    const orgLink = document.createElement('a');
    orgLink.href = '#organiser';
    orgLink.textContent = 'Organiser ⚙️';
    if (state.currentRoute === 'organiser') orgLink.classList.add('active');
    nav.append(orgLink);
  }

  // User Chip
  const userChip = document.createElement('div');
  userChip.className = 'user-chip';

  const avatar = document.createElement('span');
  avatar.className = 'user-avatar';
  avatar.textContent = state.currentUser.display_name.charAt(0).toUpperCase();

  const nameSpan = document.createElement('span');
  nameSpan.textContent = state.currentUser.display_name;

  userChip.append(avatar, nameSpan);

  // Logout button
  const logoutBtn = document.createElement('button');
  logoutBtn.type = 'button';
  logoutBtn.title = 'Sign Out';
  logoutBtn.textContent = '🚪';
  logoutBtn.addEventListener('click', async () => {
    try {
      await api('/api/logout', { method: 'POST' });
      state.currentUser = null;
      state.assignment = null;
      showToast('Signed out successfully', 'info');
      navigate('#login');
    } catch (err) {
      showToast('Error signing out', 'error');
    }
  });

  nav.append(userChip, logoutBtn);
}

function renderApp() {
  renderNav();
  const app = document.getElementById('app');
  app.replaceChildren();

  // Route dispatch
  switch (state.currentRoute) {
    case 'login':
      renderAuthView('login');
      break;
    case 'register':
      renderAuthView('register');
      break;
    case 'my-wishlist':
      if (!state.currentUser) {
        navigate('#login');
        return;
      }
      renderWishlistView(state.currentUser.id, true);
      break;
    case 'wishlist':
      if (!state.currentUser) {
        navigate('#login');
        return;
      }
      const targetId = parseInt(state.routeParam, 10);
      if (isNaN(targetId)) {
        navigate('#family');
        return;
      }
      renderWishlistView(targetId, targetId === state.currentUser.id);
      break;
    case 'family':
      if (!state.currentUser) {
        navigate('#login');
        return;
      }
      renderFamilyDirectoryView();
      break;
    case 'organiser':
      if (!state.currentUser || state.currentUser.role !== 'organiser') {
        navigate('#home');
        return;
      }
      renderOrganiserView();
      break;
    case 'home':
    default:
      if (!state.currentUser) {
        renderLandingView();
      } else {
        renderDashboardView();
      }
      break;
  }
}

// ==========================================
// Views
// ==========================================

function renderLandingView() {
  const app = document.getElementById('app');

  const hero = document.createElement('div');
  hero.className = 'event-banner';
  hero.style.textAlign = 'center';
  hero.style.justifyContent = 'center';
  hero.style.paddingBlock = '3rem';

  hero.innerHTML = `
    <div style="max-width: 600px; margin: auto;">
      <h1 style="font-size: 2.25rem; margin-bottom: 0.75rem;">🎄 Family Secret Santa</h1>
      <p style="font-size: 1.125rem; opacity: 0.95; margin-bottom: 1.5rem;">
        Welcome to our family gift exchange! Create your wishlist, view each other's ideas, and keep purchased gifts a complete surprise until reveal day.
      </p>
      <div style="display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap;">
        <a href="#register" class="btn btn-primary" style="background: #ffffff; color: #1b4332; font-size: 1.0625rem; font-weight: 700; padding: 0.75rem 1.75rem; border-radius: 9999px;">
          Join the Family Gift Exchange 🎁
        </a>
        <a href="#login" class="btn btn-secondary" style="background: rgba(255,255,255,0.15); border-color: rgba(255,255,255,0.3); color: #fff; padding: 0.75rem 1.75rem; border-radius: 9999px;">
          I Already Have an Account
        </a>
      </div>
    </div>
  `;

  app.append(hero);
}

function renderAuthView(initialTab = 'login') {
  const app = document.getElementById('app');

  const container = document.createElement('div');
  container.className = 'auth-container';

  container.innerHTML = `
    <div class="auth-header">
      <svg class="auth-icon" viewBox="0 0 64 64" aria-hidden="true">
        <rect x="10" y="24" width="44" height="34" rx="4" fill="#c1121f" />
        <rect x="7" y="16" width="50" height="10" rx="3" fill="#d90429" />
        <rect x="28" y="16" width="8" height="42" fill="#ffd166" />
        <rect x="10" y="37" width="44" height="8" fill="#ffd166" />
        <circle cx="32" cy="16" r="4" fill="#ffb703" />
      </svg>
      <h1 style="font-size: 1.5rem; font-weight: 700;" id="auth-title">Welcome Family!</h1>
      <p style="color: var(--color-text-muted); font-size: 0.9375rem;" id="auth-subtitle">Sign in to your Secret Santa wishlist</p>
    </div>

    <div class="auth-tabs" role="tablist">
      <button type="button" class="auth-tab ${initialTab === 'login' ? 'active' : ''}" id="tab-login" role="tab" aria-selected="${initialTab === 'login'}">Log In</button>
      <button type="button" class="auth-tab ${initialTab === 'register' ? 'active' : ''}" id="tab-register" role="tab" aria-selected="${initialTab === 'register'}">Register</button>
    </div>

    <!-- Login Form -->
    <form id="login-form" style="display: ${initialTab === 'login' ? 'block' : 'none'};">
      <div class="form-group">
        <label class="form-label" for="login-username">Username</label>
        <input class="form-input" type="text" id="login-username" name="username" required autocomplete="username" placeholder="e.g. grandpa_bob">
      </div>
      <div class="form-group">
        <label class="form-label" for="login-password">Password</label>
        <input class="form-input" type="password" id="login-password" name="password" required autocomplete="current-password">
      </div>
      <button type="submit" class="btn btn-primary" style="width: 100%; margin-top: 1.5rem;">Sign In 🎅</button>
    </form>

    <!-- Register Form -->
    <form id="register-form" style="display: ${initialTab === 'register' ? 'block' : 'none'};">
      <div class="form-group">
        <label class="form-label" for="reg-display-name">Your Real Name</label>
        <input class="form-input" type="text" id="reg-display-name" name="display_name" required placeholder="e.g. Uncle John, Sarah">
        <div class="form-hint">This is the name family members will see on wishlists.</div>
      </div>
      <div class="form-group">
        <label class="form-label" for="reg-username">Choose a Username</label>
        <input class="form-input" type="text" id="reg-username" name="username" required minlength="3" autocomplete="username" placeholder="e.g. sarah24">
      </div>
      <div class="form-group">
        <label class="form-label" for="reg-password">Password</label>
        <input class="form-input" type="password" id="reg-password" name="password" required minlength="4" autocomplete="new-password">
      </div>
      <button type="submit" class="btn btn-primary" style="width: 100%; margin-top: 1.5rem;">Create Account 🎁</button>
      <p style="font-size: 0.8125rem; color: var(--color-text-subtle); text-align: center; margin-top: 0.75rem;">
        Note: The first person to register becomes the Organiser!
      </p>
    </form>
  `;

  app.append(container);

  // Tab switching
  const tabLogin = container.querySelector('#tab-login');
  const tabRegister = container.querySelector('#tab-register');
  const loginForm = container.querySelector('#login-form');
  const regForm = container.querySelector('#register-form');
  const authTitle = container.querySelector('#auth-title');
  const authSubtitle = container.querySelector('#auth-subtitle');

  tabLogin.addEventListener('click', () => {
    tabLogin.classList.add('active');
    tabLogin.setAttribute('aria-selected', 'true');
    tabRegister.classList.remove('active');
    tabRegister.setAttribute('aria-selected', 'false');
    loginForm.style.display = 'block';
    regForm.style.display = 'none';
    authTitle.textContent = 'Welcome Back!';
    authSubtitle.textContent = 'Sign in to access your wishlist and assignments';
  });

  tabRegister.addEventListener('click', () => {
    tabRegister.classList.add('active');
    tabRegister.setAttribute('aria-selected', 'true');
    tabLogin.classList.remove('active');
    tabLogin.setAttribute('aria-selected', 'false');
    regForm.style.display = 'block';
    loginForm.style.display = 'none';
    authTitle.textContent = 'Join Secret Santa';
    authSubtitle.textContent = 'Register to join your family gift exchange';
  });

  // Login submission
  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(loginForm);
    try {
      const res = await api('/api/login', {
        method: 'POST',
        body: JSON.stringify(Object.fromEntries(formData))
      });
      state.currentUser = res.user;
      showToast(`Welcome back, ${res.user.display_name}! 🎄`, 'success');
      await refreshState();
      navigate('#home');
    } catch (err) {
      showToast(err.message || 'Login failed', 'error');
    }
  });

  // Register submission
  regForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(regForm);
    try {
      const res = await api('/api/register', {
        method: 'POST',
        body: JSON.stringify(Object.fromEntries(formData))
      });
      state.currentUser = res.user;
      const roleMsg = res.user.role === 'organiser' ? ' (You are the Organiser!)' : '';
      showToast(`Account created! Welcome, ${res.user.display_name}${roleMsg} 🎁`, 'success');
      await refreshState();
      navigate('#home');
    } catch (err) {
      showToast(err.message || 'Registration failed', 'error');
    }
  });
}

function renderDashboardView() {
  const app = document.getElementById('app');

  // Event Banner
  const banner = document.createElement('section');
  banner.className = 'event-banner';

  const evt = state.event || {};
  banner.innerHTML = `
    <div class="event-info">
      <h1>${escapeHtml(evt.event_name || 'Family Secret Santa')}</h1>
      <div class="event-meta">
        ${evt.budget_limit ? `<span>💰 Budget: <strong>${escapeHtml(evt.budget_limit)}</strong></span>` : ''}
        ${evt.reveal_date ? `<span>📅 Reveal Date: <strong>${escapeHtml(evt.reveal_date)}</strong></span>` : ''}
        <span>👥 Participants: <strong>${state.participants.length}</strong></span>
      </div>
      ${evt.rules_note ? `<p style="margin-top: 0.75rem; font-size: 0.9375rem; opacity: 0.9;">${escapeHtml(evt.rules_note)}</p>` : ''}
    </div>
  `;
  app.append(banner);

  // Secret Santa Assignment Reveal Card!
  if (evt.is_drawn && state.assignment) {
    const assignCard = document.createElement('section');
    assignCard.className = 'assignment-card';
    assignCard.innerHTML = `
      <div class="assignment-details">
        <h2>Your Secret Santa Recipient</h2>
        <div class="recipient-name">
          🎁 ${escapeHtml(state.assignment.receiver_display_name)}
        </div>
        <p>Shhh! Keep this a secret. Check out their wishlist to find the perfect gift!</p>
      </div>
      <div class="assignment-actions">
        <button type="button" id="view-assigned-btn">
          View ${escapeHtml(state.assignment.receiver_display_name)}'s Wishlist (${state.assignment.wishlist_count || 0} items) &rarr;
        </button>
      </div>
    `;

    assignCard.querySelector('#view-assigned-btn').addEventListener('click', () => {
      navigate(`#wishlist/${state.assignment.receiver_id}`);
    });

    app.append(assignCard);
  } else if (!evt.is_drawn) {
    const pendingCard = document.createElement('div');
    pendingCard.className = 'empty-state';
    pendingCard.style.borderColor = 'var(--color-gold-border)';
    pendingCard.style.backgroundColor = 'var(--color-gold-light)';
    pendingCard.innerHTML = `
      <div class="empty-icon">⏳</div>
      <p class="empty-title" style="color: var(--color-gold);">Names have not been drawn yet</p>
      <p class="empty-desc" style="color: var(--color-text-muted);">
        Add your gift ideas to your wishlist while the organiser waits for everyone in the family to register!
      </p>
      <a href="#my-wishlist" class="btn btn-primary">Edit My Wishlist 🎁</a>
    `;
    app.append(pendingCard);
  }

  // Quick Action Links
  const quickActions = document.createElement('div');
  quickActions.style.display = 'grid';
  quickActions.style.gridTemplateColumns = 'repeat(auto-fit, minmax(240px, 1fr))';
  quickActions.style.gap = '1.25rem';
  quickActions.style.marginTop = '2rem';

  quickActions.innerHTML = `
    <a href="#my-wishlist" class="member-card">
      <div class="member-info">
        <div class="member-avatar" style="background: var(--color-primary);">🎁</div>
        <div>
          <div class="member-name">My Wishlist</div>
          <div class="member-role">Add & manage your gift requests</div>
        </div>
      </div>
      <span>&rarr;</span>
    </a>
    <a href="#family" class="member-card">
      <div class="member-info">
        <div class="member-avatar" style="background: var(--color-festive-green);">👥</div>
        <div>
          <div class="member-name">Family Wishlists</div>
          <div class="member-role">Browse ideas & mark items bought</div>
        </div>
      </div>
      <span>&rarr;</span>
    </a>
  `;
  app.append(quickActions);
}

// ==========================================
// Wishlist View (Own or Other Member)
// ==========================================

async function renderWishlistView(userId, isOwner) {
  const app = document.getElementById('app');

  // Loading indicator
  app.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">🎁</div>
      <p class="empty-title">Loading Wishlist...</p>
    </div>
  `;

  try {
    const data = await api(`/api/wishlist/${userId}`);
    state.currentWishlist = data;

    app.replaceChildren();

    const header = document.createElement('div');
    header.className = 'section-header';

    const titleDiv = document.createElement('div');
    const title = document.createElement('h1');
    title.className = 'section-title';
    title.textContent = isOwner ? '🎁 My Wishlist' : `🎁 ${data.user.display_name}'s Wishlist`;

    const subtitle = document.createElement('p');
    subtitle.className = 'section-subtitle';
    subtitle.textContent = isOwner
      ? 'Add gifts you would love to receive this year.'
      : `Looking for a gift for ${data.user.display_name}? Browse their requests below.`;

    titleDiv.append(title, subtitle);
    header.append(titleDiv);

    if (isOwner) {
      const addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.className = 'btn btn-primary';
      addBtn.innerHTML = '<span>+</span> Add Gift Idea';
      addBtn.addEventListener('click', () => openItemDialog());
      header.append(addBtn);
    } else {
      const backLink = document.createElement('a');
      backLink.href = '#family';
      backLink.className = 'btn btn-secondary';
      backLink.textContent = '← All Family Members';
      header.append(backLink);
    }

    app.append(header);

    // CRITICAL SECRET SANTA SHIELD BANNER
    const shieldBanner = document.createElement('div');
    shieldBanner.className = 'shield-notice';

    if (isOwner) {
      shieldBanner.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        <div>
          <strong>Secret Santa Privacy Shield Active:</strong>
          To keep your gifts a total surprise until reveal day, you will never see which items on this list have been marked as purchased!
        </div>
      `;
    } else {
      shieldBanner.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 16v-4"/>
          <path d="M12 8h.01"/>
        </svg>
        <div>
          <strong>Secret Gifting:</strong>
          Mark items you've bought so other family members avoid duplicate gifts. 
          <em>${escapeHtml(data.user.display_name)} will never be able to see that an item was purchased!</em>
        </div>
      `;
    }
    app.append(shieldBanner);

    // Items list
    const items = data.items || [];
    if (items.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.innerHTML = `
        <div class="empty-icon">📝</div>
        <p class="empty-title">${isOwner ? 'Your wishlist is empty' : 'No items yet'}</p>
        <p class="empty-desc">
          ${isOwner ? 'Add clothing sizes, hobby ideas, books, or store links to help your Secret Santa!' : `${data.user.display_name} hasn't added any items to their wishlist yet. Check back soon!`}
        </p>
      `;
      if (isOwner) {
        const addFirstBtn = document.createElement('button');
        addFirstBtn.type = 'button';
        addFirstBtn.className = 'btn btn-primary';
        addFirstBtn.textContent = 'Add Your First Item 🎁';
        addFirstBtn.addEventListener('click', () => openItemDialog());
        empty.append(addFirstBtn);
      }
      app.append(empty);
      return;
    }

    const grid = document.createElement('div');
    grid.className = 'cards-grid';

    items.forEach(item => {
      const card = document.createElement('article');
      card.className = 'item-card';

      // Top row: Title and Badges
      const top = document.createElement('div');
      top.className = 'item-card-top';

      const titleEl = document.createElement('h2');
      titleEl.className = 'item-title';
      titleEl.textContent = item.title;

      const badges = document.createElement('div');
      badges.className = 'item-badges';

      if (item.priority === 2) {
        const prioBadge = document.createElement('span');
        prioBadge.className = 'badge badge-priority';
        prioBadge.textContent = '⭐ Top Pick';
        badges.append(prioBadge);
      }

      // If NOT owner and purchased, show badge
      if (!isOwner && item.is_purchased) {
        const purchBadge = document.createElement('span');
        purchBadge.className = 'badge badge-purchased';
        purchBadge.textContent = item.is_bought_by_viewer ? '✓ Purchased by You' : '✓ Purchased';
        badges.append(purchBadge);
      }

      top.append(titleEl, badges);
      card.append(top);

      // Price
      if (item.price) {
        const priceEl = document.createElement('div');
        priceEl.className = 'item-price';
        priceEl.textContent = item.price;
        card.append(priceEl);
      }

      // Description
      if (item.description) {
        const descEl = document.createElement('p');
        descEl.className = 'item-description';
        descEl.textContent = item.description;
        card.append(descEl);
      }

      // External URL Link
      if (item.url) {
        const link = document.createElement('a');
        link.className = 'item-url';
        link.href = item.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.innerHTML = '<span>🔗</span> View Product Link &nearr;';
        card.append(link);
      }

      // Footer
      const footer = document.createElement('div');
      footer.className = 'item-footer';

      if (isOwner) {
        // Owner controls: Edit & Delete
        const actions = document.createElement('div');
        actions.style.display = 'flex';
        actions.style.gap = '0.5rem';

        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'btn btn-secondary btn-sm';
        editBtn.textContent = 'Edit';
        editBtn.addEventListener('click', () => openItemDialog(item));

        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'btn btn-secondary btn-sm';
        delBtn.style.color = 'var(--color-danger)';
        delBtn.textContent = 'Delete';
        delBtn.addEventListener('click', async () => {
          if (confirm(`Remove "${item.title}" from your wishlist?`)) {
            try {
              await api(`/api/wishlist/${item.id}`, { method: 'DELETE' });
              showToast('Item deleted', 'info');
              renderWishlistView(userId, isOwner);
            } catch (err) {
              showToast(err.message, 'error');
            }
          }
        });

        actions.append(editBtn, delBtn);
        footer.append(actions);
      } else {
        // Non-owner controls: Mark as Purchased / Unmark
        const buyBtn = document.createElement('button');
        buyBtn.type = 'button';
        buyBtn.className = 'purchase-btn';

        if (!item.is_purchased) {
          buyBtn.classList.add('action-buy');
          buyBtn.textContent = '🎁 Mark as Purchased';
          buyBtn.addEventListener('click', async () => {
            await handleTogglePurchase(item.id, userId);
          });
        } else if (item.is_bought_by_viewer) {
          buyBtn.classList.add('action-unbuy');
          buyBtn.textContent = '✓ Purchased by You (Click to Undo)';
          buyBtn.title = 'Did you buy this by mistake? Click to unmark.';
          buyBtn.addEventListener('click', async () => {
            await handleTogglePurchase(item.id, userId);
          });
        } else {
          buyBtn.classList.add('action-locked');
          buyBtn.disabled = true;
          buyBtn.textContent = `🔒 Purchased by ${item.buyer_name || 'someone'}`;
        }

        footer.append(buyBtn);
      }

      card.append(footer);
      grid.append(card);
    });

    app.append(grid);

  } catch (err) {
    app.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <p class="empty-title">Error loading wishlist</p>
        <p class="empty-desc">${escapeHtml(err.message)}</p>
        <button type="button" class="btn btn-secondary" onclick="window.history.back()">Go Back</button>
      </div>
    `;
  }
}

async function handleTogglePurchase(itemId, userId) {
  try {
    const res = await api(`/api/wishlist/${itemId}/purchase`, { method: 'POST' });
    if (res.status === 'purchased') {
      showToast('Item marked as purchased! 🎁', 'success');
    } else {
      showToast('Item unmarked', 'info');
    }
    renderWishlistView(userId, false);
  } catch (err) {
    showToast(err.message || 'Error updating purchase status', 'error');
  }
}

// ==========================================
// Family Directory View
// ==========================================

function renderFamilyDirectoryView() {
  const app = document.getElementById('app');

  const header = document.createElement('div');
  header.className = 'section-header';
  header.innerHTML = `
    <div>
      <h1 class="section-title">🎄 Family Wishlists</h1>
      <p class="section-subtitle">Select a family member to see what they would love for Secret Santa.</p>
    </div>
  `;
  app.append(header);

  const users = state.participants || [];
  if (users.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML = `
      <div class="empty-icon">👥</div>
      <p class="empty-title">No family members registered yet</p>
    `;
    app.append(empty);
    return;
  }

  const grid = document.createElement('div');
  grid.className = 'cards-grid';

  users.forEach(u => {
    const card = document.createElement('a');
    card.className = 'member-card';
    card.href = `#wishlist/${u.id}`;

    const isSelf = (state.currentUser && state.currentUser.id === u.id);
    const isAssigned = (state.assignment && state.assignment.receiver_id === u.id);

    card.innerHTML = `
      <div class="member-info">
        <div class="member-avatar" style="${isSelf ? 'background: var(--color-primary);' : (isAssigned ? 'background: #ffd166; color: #780000;' : '')}">
          ${isAssigned ? '⭐' : escapeHtml(u.display_name.charAt(0).toUpperCase())}
        </div>
        <div>
          <div class="member-name">
            ${escapeHtml(u.display_name)} ${isSelf ? '<span class="badge" style="background:var(--color-surface-hover);">You</span>' : ''}
            ${isAssigned ? '<span class="badge badge-priority">Your Match 🎁</span>' : ''}
          </div>
          <div class="member-role">@${escapeHtml(u.username)}</div>
        </div>
      </div>
      <div class="member-count">
        ${u.wishlist_count || 0} item${(u.wishlist_count === 1) ? '' : 's'} &rarr;
      </div>
    `;

    grid.append(card);
  });

  app.append(grid);
}

// ==========================================
// Organiser Control View
// ==========================================

function renderOrganiserView() {
  const app = document.getElementById('app');

  const header = document.createElement('div');
  header.className = 'section-header';
  header.innerHTML = `
    <div>
      <h1 class="section-title">⚙️ Organiser Dashboard</h1>
      <p class="section-subtitle">Manage the family Secret Santa draw and event details.</p>
    </div>
  `;
  app.append(header);

  const panel = document.createElement('section');
  panel.className = 'organiser-panel';

  const isDrawn = Boolean(state.event && state.event.is_drawn);
  const participantCount = state.participants.length;

  panel.innerHTML = `
    <div class="organiser-panel-header">
      <div>
        <h2 style="font-size: 1.25rem; font-weight: 700; margin-bottom: 0.25rem;">
          ${isDrawn ? '✅ Secret Santa Draw is Active!' : '🎲 Ready to Draw Names?'}
        </h2>
        <p style="color: var(--color-text-muted); font-size: 0.9375rem;">
          ${isDrawn 
            ? `Names were drawn on ${new Date(state.event.drawn_at).toLocaleDateString()}. Each family member can view their secret recipient.`
            : `${participantCount} participant${participantCount === 1 ? '' : 's'} registered so far. You need at least 2 people to draw.`}
        </p>
      </div>
      <div class="organiser-actions" id="org-action-buttons">
        <button type="button" class="btn btn-secondary" id="open-settings-btn">⚙️ Edit Event Settings</button>
        ${!isDrawn 
          ? `<button type="button" class="btn btn-primary" id="open-draw-btn" ${participantCount < 2 ? 'disabled' : ''}>
               Trigger Draw 🎲
             </button>`
          : `<button type="button" class="btn btn-danger" id="open-reset-btn">
               Reset Draw ⚠️
             </button>`
        }
      </div>
    </div>
  `;

  // Attach button events
  const openDrawBtn = panel.querySelector('#open-draw-btn');
  if (openDrawBtn) {
    openDrawBtn.addEventListener('click', () => {
      const countEl = document.getElementById('draw-dialog-count');
      if (countEl) countEl.textContent = `Current participants: ${participantCount}`;
      const dialog = document.getElementById('draw-dialog');
      if (dialog) dialog.showModal();
    });
  }

  const openResetBtn = panel.querySelector('#open-reset-btn');
  if (openResetBtn) {
    openResetBtn.addEventListener('click', () => {
      const dialog = document.getElementById('reset-dialog');
      if (dialog) dialog.showModal();
    });
  }

  const openSettingsBtn = panel.querySelector('#open-settings-btn');
  if (openSettingsBtn) {
    openSettingsBtn.addEventListener('click', () => {
      openSettingsDialog();
    });
  }

  app.append(panel);

  // Participant Table / List
  const listTitle = document.createElement('h2');
  listTitle.style.fontSize = '1.25rem';
  listTitle.style.marginBottom = '1rem';
  listTitle.textContent = `Participants Roster (${participantCount})`;
  app.append(listTitle);

  const rosterGrid = document.createElement('div');
  rosterGrid.className = 'cards-grid';

  state.participants.forEach(u => {
    const card = document.createElement('div');
    card.className = 'item-card';
    card.innerHTML = `
      <div class="item-card-top">
        <div style="font-weight: 700; font-size: 1.0625rem;">${escapeHtml(u.display_name)}</div>
        <span class="badge ${u.role === 'organiser' ? 'badge-priority' : ''}">${escapeHtml(u.role)}</span>
      </div>
      <div style="color: var(--color-text-subtle); font-size: 0.875rem; margin-bottom: 0.5rem;">
        Username: <code>@${escapeHtml(u.username)}</code>
      </div>
      <div style="font-size: 0.9375rem; color: var(--color-text-muted);">
        Wishlist items added: <strong>${u.wishlist_count || 0}</strong>
      </div>
    `;
    rosterGrid.append(card);
  });

  app.append(rosterGrid);
}

// ==========================================
// Dialog Logic (Add/Edit Item, Settings, Draw)
// ==========================================

function openItemDialog(existingItem = null) {
  const dialog = document.getElementById('item-dialog');
  const titleEl = document.getElementById('item-dialog-title');
  const form = document.getElementById('item-form');
  if (!dialog || !form) return;

  form.reset();

  if (existingItem) {
    titleEl.textContent = 'Edit Wishlist Item';
    form.querySelector('#item-id').value = existingItem.id;
    form.querySelector('#item-title').value = existingItem.title || '';
    form.querySelector('#item-price').value = existingItem.price || '';
    form.querySelector('#item-url').value = existingItem.url || '';
    form.querySelector('#item-desc').value = existingItem.description || '';
    form.querySelector('#item-priority').value = existingItem.priority || 1;
  } else {
    titleEl.textContent = 'Add Wishlist Item';
    form.querySelector('#item-id').value = '';
  }

  dialog.showModal();
}

function openSettingsDialog() {
  const dialog = document.getElementById('settings-dialog');
  const form = document.getElementById('settings-form');
  if (!dialog || !form) return;

  const evt = state.event || {};
  form.querySelector('#setting-event-name').value = evt.event_name || 'Family Secret Santa';
  form.querySelector('#setting-budget').value = evt.budget_limit || '';
  form.querySelector('#setting-date').value = evt.reveal_date || '';
  form.querySelector('#setting-rules').value = evt.rules_note || '';

  dialog.showModal();
}

// ==========================================
// Initialization & Global Event Listeners
// ==========================================

function initDialogListeners() {
  ['item-dialog', 'draw-dialog', 'reset-dialog', 'settings-dialog'].forEach(setupDialog);

  // Wishlist item form submission
  const itemForm = document.getElementById('item-form');
  if (itemForm) {
    itemForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const itemId = itemForm.querySelector('#item-id').value;
      const data = {
        title: itemForm.querySelector('#item-title').value.trim(),
        price: itemForm.querySelector('#item-price').value.trim(),
        url: itemForm.querySelector('#item-url').value.trim(),
        description: itemForm.querySelector('#item-desc').value.trim(),
        priority: parseInt(itemForm.querySelector('#item-priority').value, 10)
      };

      try {
        if (itemId) {
          await api(`/api/wishlist/${itemId}`, { method: 'PUT', body: JSON.stringify(data) });
          showToast('Wishlist item updated! 🎁', 'success');
        } else {
          await api('/api/wishlist', { method: 'POST', body: JSON.stringify(data) });
          showToast('Item added to your wishlist! 🎁', 'success');
        }
        document.getElementById('item-dialog').close();
        if (state.currentUser) {
          renderWishlistView(state.currentUser.id, true);
        }
      } catch (err) {
        showToast(err.message || 'Error saving item', 'error');
      }
    });
  }

  // Draw Confirm Button
  const confirmDrawBtn = document.getElementById('confirm-draw-btn');
  if (confirmDrawBtn) {
    confirmDrawBtn.addEventListener('click', async () => {
      try {
        const res = await api('/api/draw', { method: 'POST' });
        document.getElementById('draw-dialog').close();
        showToast(`🎉 Secret Santa names drawn for ${res.participant_count} family members!`, 'success');
        await refreshState();
        renderApp();
      } catch (err) {
        showToast(err.message || 'Error drawing names', 'error');
      }
    });
  }

  // Reset Confirm Button
  const confirmResetBtn = document.getElementById('confirm-reset-btn');
  if (confirmResetBtn) {
    confirmResetBtn.addEventListener('click', async () => {
      try {
        await api('/api/draw/reset', { method: 'POST' });
        document.getElementById('reset-dialog').close();
        showToast('Secret Santa assignments have been reset', 'info');
        await refreshState();
        renderApp();
      } catch (err) {
        showToast(err.message || 'Error resetting draw', 'error');
      }
    });
  }

  // Settings Form Submission
  const settingsForm = document.getElementById('settings-form');
  if (settingsForm) {
    settingsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const data = {
        event_name: settingsForm.querySelector('#setting-event-name').value.trim(),
        budget_limit: settingsForm.querySelector('#setting-budget').value.trim(),
        reveal_date: settingsForm.querySelector('#setting-date').value.trim(),
        rules_note: settingsForm.querySelector('#setting-rules').value.trim()
      };

      try {
        const res = await api('/api/event/update', { method: 'POST', body: JSON.stringify(data) });
        state.event = res.event;
        document.getElementById('settings-dialog').close();
        showToast('Event settings updated!', 'success');
        renderApp();
      } catch (err) {
        showToast(err.message || 'Error updating settings', 'error');
      }
    });
  }
}

// Helper to escape HTML characters
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

async function refreshState() {
  try {
    const meData = await api('/api/me');
    state.currentUser = meData.user;
    state.assignment = meData.assignment;
    state.event = meData.event;

    const eventData = await api('/api/event');
    state.participants = eventData.participants || [];
  } catch (err) {
    console.error('State refresh failed:', err);
  }
}

// Routing Listener
window.addEventListener('hashchange', () => {
  const { route, param } = parseHash();
  state.currentRoute = route;
  state.routeParam = param;
  updateView(() => renderApp());
});

// Initial boot
async function init() {
  initDialogListeners();
  await refreshState();

  const { route, param } = parseHash();
  state.currentRoute = route;
  state.routeParam = param;

  updateView(() => renderApp());
}

init();
