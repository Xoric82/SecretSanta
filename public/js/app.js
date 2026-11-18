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
  participants: [],        // array of user objects (adults + children)
  children: [],            // child profiles managed by the current user
  childrenAssignments: [], // [{ child_id, child_display_name, receiver_id, receiver_display_name, wishlist_count }]
  itemDialogOwnerId: null, // whose wishlist the item dialog is editing (self or a managed child)
  currentWishlist: null,   // { user, is_owner, items }
  requiresRegistrationCode: false,
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
      if (data.code === 'password_change_required' && state.currentUser && !state.currentUser.must_change_password) {
        state.currentUser.must_change_password = true;
        renderApp();
      }
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
  if (window.location.hash === hash) {
    // hashchange won't fire for the same hash, so render explicitly
    const { route, param } = parseHash();
    state.currentRoute = route;
    state.routeParam = param;
    updateView(() => renderApp());
  } else {
    window.location.hash = hash;
  }
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

  const mustChange = Boolean(state.currentUser.must_change_password);

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

  const childrenLink = document.createElement('a');
  childrenLink.href = '#children';
  childrenLink.textContent = 'Children 🧒';
  if (state.currentRoute === 'children') childrenLink.classList.add('active');

  if (!mustChange) nav.append(homeLink, myWishlistLink, familyLink, childrenLink);

  if (state.currentUser.role === 'organiser' && !mustChange) {
    const orgLink = document.createElement('a');
    orgLink.href = '#organiser';
    orgLink.textContent = 'Organiser ⚙️';
    if (state.currentRoute === 'organiser') orgLink.classList.add('active');
    nav.append(orgLink);
  }

  // User Chip (links to account page)
  const userChip = document.createElement('a');
  userChip.className = 'user-chip';
  userChip.href = '#account';
  userChip.title = 'My account';
  if (state.currentRoute === 'account') userChip.classList.add('active');

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
      state.children = [];
      state.childrenAssignments = [];
      state.participants = [];
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

  // After an organiser password reset, nothing else is available until a new password is chosen
  if (state.currentUser && state.currentUser.must_change_password) {
    renderPasswordView(true);
    return;
  }

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
    case 'account':
      if (!state.currentUser) {
        navigate('#login');
        return;
      }
      renderPasswordView(false);
      break;
    case 'children':
      if (!state.currentUser) {
        navigate('#login');
        return;
      }
      renderChildrenView();
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
      <div class="form-group" id="reg-passcode-group">
        <label class="form-label" for="reg-passcode">Family Passcode <span style="color: var(--color-primary); font-weight: bold;">*</span></label>
        <input class="form-input" type="password" id="reg-passcode" name="registration_code" autocomplete="off" placeholder="Enter the secret family code">
        <div class="form-hint">Enter the secret family code set by the organiser to join.</div>
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
    const passcodeInput = regForm.querySelector('#reg-passcode');
    if (passcodeInput) {
      passcodeInput.style.borderColor = '';
    }
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
      if (err.message && err.message.toLowerCase().includes('passcode')) {
        if (passcodeInput) {
          passcodeInput.focus();
          passcodeInput.style.borderColor = 'var(--color-danger)';
        }
      }
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
        <span>👥 In the draw: <strong>${drawParticipants().length}</strong></span>
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

  // Children's assignments (parent shops on their behalf)
  if (evt.is_drawn && state.childrenAssignments.length > 0) {
    const kidsSection = document.createElement('section');
    kidsSection.style.marginTop = '2rem';

    const kidsTitle = document.createElement('h2');
    kidsTitle.style.fontSize = '1.25rem';
    kidsTitle.style.marginBottom = '1rem';
    kidsTitle.textContent = "🧒 Your Children's Secret Santa Recipients";
    kidsSection.append(kidsTitle);

    const kidsGrid = document.createElement('div');
    kidsGrid.className = 'cards-grid';
    state.childrenAssignments.forEach(ca => {
      const card = document.createElement('a');
      card.className = 'member-card';
      card.href = `#wishlist/${ca.receiver_id}`;
      card.innerHTML = `
        <div class="member-info">
          <div class="member-avatar" style="background: #ffd166; color: #780000;">🎁</div>
          <div>
            <div class="member-name">${escapeHtml(ca.child_display_name)} is buying for</div>
            <div class="member-role"><strong>${escapeHtml(ca.receiver_display_name)}</strong></div>
          </div>
        </div>
        <div class="member-count">${ca.wishlist_count || 0} item${ca.wishlist_count === 1 ? '' : 's'} &rarr;</div>
      `;
      kidsGrid.append(card);
    });
    kidsSection.append(kidsGrid);
    app.append(kidsSection);
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
    <a href="#children" class="member-card">
      <div class="member-info">
        <div class="member-avatar" style="background: var(--color-gold);">🧒</div>
        <div>
          <div class="member-name">My Children</div>
          <div class="member-role">Add kids & manage their wishlists</div>
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
    // Parent managing a child's list: can edit items AND sees purchase status (the child never logs in)
    const isManagedChild = Boolean(data.can_manage && !isOwner);
    const canEdit = isOwner || isManagedChild;

    app.replaceChildren();

    const header = document.createElement('div');
    header.className = 'section-header';

    const titleDiv = document.createElement('div');
    const title = document.createElement('h1');
    title.className = 'section-title';
    title.textContent = isOwner ? '🎁 My Wishlist' : `🎁 ${data.user.display_name}'s Wishlist`;

    const subtitle = document.createElement('p');
    subtitle.className = 'section-subtitle';
    if (isOwner) {
      subtitle.textContent = 'Add gifts you would love to receive this year.';
    } else if (isManagedChild) {
      subtitle.textContent = `You manage this list for ${data.user.display_name}. Add their gift ideas below.`;
    } else if (data.user.is_child) {
      subtitle.textContent = `${data.user.display_name}'s list is looked after by ${data.user.parent_display_name || 'a parent'}. Browse their requests below.`;
    } else {
      subtitle.textContent = `Looking for a gift for ${data.user.display_name}? Browse their requests below.`;
    }

    titleDiv.append(title, subtitle);
    header.append(titleDiv);

    const headerActions = document.createElement('div');
    headerActions.className = 'organiser-actions';
    if (canEdit) {
      const addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.className = 'btn btn-primary';
      addBtn.innerHTML = '<span>+</span> Add Gift Idea';
      addBtn.addEventListener('click', () => openItemDialog(null, userId));
      headerActions.append(addBtn);
    }
    if (!isOwner) {
      const backLink = document.createElement('a');
      backLink.href = isManagedChild ? '#children' : '#family';
      backLink.className = 'btn btn-secondary';
      backLink.textContent = isManagedChild ? '← My Children' : '← All Family Members';
      headerActions.append(backLink);
    }
    header.append(headerActions);

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
    } else if (isManagedChild) {
      shieldBanner.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        <div>
          <strong>Parent View:</strong>
          Because ${escapeHtml(data.user.display_name)} doesn't log in, you can see which items have been purchased.
          <em>Keep it a secret from them until reveal day!</em>
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
          ${canEdit ? 'Add clothing sizes, hobby ideas, books, or store links to help their Secret Santa!' : `${escapeHtml(data.user.display_name)} hasn't added any items to their wishlist yet. Check back soon!`}
        </p>
      `;
      if (canEdit) {
        const addFirstBtn = document.createElement('button');
        addFirstBtn.type = 'button';
        addFirstBtn.className = 'btn btn-primary';
        addFirstBtn.textContent = isOwner ? 'Add Your First Item 🎁' : `Add ${data.user.display_name}'s First Item 🎁`;
        addFirstBtn.addEventListener('click', () => openItemDialog(null, userId));
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

      if (canEdit) {
        // Owner / managing-parent controls: Edit & Delete
        const actions = document.createElement('div');
        actions.style.display = 'flex';
        actions.style.gap = '0.5rem';

        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'btn btn-secondary btn-sm';
        editBtn.textContent = 'Edit';
        editBtn.addEventListener('click', () => openItemDialog(item, userId));

        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'btn btn-secondary btn-sm';
        delBtn.style.color = 'var(--color-danger)';
        delBtn.textContent = 'Delete';
        delBtn.addEventListener('click', async () => {
          if (confirm(`Remove "${item.title}" from ${isOwner ? 'your' : `${data.user.display_name}'s`} wishlist?`)) {
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
      }
      if (!isOwner) {
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
    renderWishlistView(userId, state.currentUser && state.currentUser.id === userId);
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
    const isMyChild = (state.currentUser && u.parent_id === state.currentUser.id);
    const subline = u.is_child
      ? (isMyChild ? 'Your child · managed by you' : `Child of ${u.parent_display_name || 'a family member'}`)
      : `@${u.username}`;

    card.innerHTML = `
      <div class="member-info">
        <div class="member-avatar" style="${isSelf ? 'background: var(--color-primary);' : (isAssigned ? 'background: #ffd166; color: #780000;' : '')}">
          ${isAssigned ? '⭐' : escapeHtml(u.display_name.charAt(0).toUpperCase())}
        </div>
        <div>
          <div class="member-name">
            ${escapeHtml(u.display_name)} ${isSelf ? '<span class="badge" style="background:var(--color-surface-hover);">You</span>' : ''}
            ${isAssigned ? '<span class="badge badge-priority">Your Match 🎁</span>' : ''}
            ${u.is_child ? '<span class="badge badge-child">🧒 Child</span>' : ''}
            ${u.in_draw === false ? '<span class="badge badge-excluded">Not in draw</span>' : ''}
          </div>
          <div class="member-role">${escapeHtml(subline)}</div>
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
// Account / Password View
// ==========================================

function renderPasswordView(forced) {
  const app = document.getElementById('app');
  const container = document.createElement('div');
  container.className = 'auth-container';

  container.innerHTML = `
    <div class="auth-header">
      <div class="empty-icon" aria-hidden="true">🔑</div>
      <h1 style="font-size: 1.5rem; font-weight: 700;">${forced ? 'Choose a New Password' : 'My Account'}</h1>
      <p style="color: var(--color-text-muted); font-size: 0.9375rem;">
        ${forced
          ? 'The organiser has reset your password. Please choose a new one to continue.'
          : `Signed in as <strong>${escapeHtml(state.currentUser.display_name)}</strong> (@${escapeHtml(state.currentUser.username)})`}
      </p>
    </div>
    <form id="password-form">
      ${forced ? '' : `
      <div class="form-group">
        <label class="form-label" for="pw-current">Current Password</label>
        <input class="form-input" type="password" id="pw-current" required autocomplete="current-password">
      </div>`}
      <div class="form-group">
        <label class="form-label" for="pw-new">New Password</label>
        <input class="form-input" type="password" id="pw-new" required minlength="4" autocomplete="new-password">
        <div class="form-hint">At least 4 characters. You'll stay signed in here; other devices will be signed out.</div>
      </div>
      <div class="form-group">
        <label class="form-label" for="pw-confirm">Confirm New Password</label>
        <input class="form-input" type="password" id="pw-confirm" required minlength="4" autocomplete="new-password">
      </div>
      <button type="submit" class="btn btn-primary" style="width: 100%; margin-top: 1.5rem;">
        ${forced ? 'Save & Continue 🎄' : 'Change Password'}
      </button>
    </form>
  `;
  app.append(container);

  const form = container.querySelector('#password-form');
  const newInput = form.querySelector('#pw-new');
  const confirmInput = form.querySelector('#pw-confirm');
  confirmInput.addEventListener('input', () => confirmInput.setCustomValidity(''));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (newInput.value !== confirmInput.value) {
      confirmInput.setCustomValidity('Passwords do not match');
      confirmInput.reportValidity();
      return;
    }
    const body = { new_password: newInput.value };
    if (!forced) body.current_password = form.querySelector('#pw-current').value;
    try {
      const res = await api('/api/account/password', { method: 'POST', body: JSON.stringify(body) });
      state.currentUser = res.user;
      showToast(forced ? 'Password saved. Welcome! 🎄' : 'Password changed', 'success');
      await refreshState();
      navigate('#home');
    } catch (err) {
      showToast(err.message || 'Could not change password', 'error');
    }
  });

  (forced ? newInput : form.querySelector('#pw-current')).focus();
}

// ==========================================
// My Children View (child profiles managed by this login)
// ==========================================

function buildDrawToggle(user, isDrawn) {
  const label = document.createElement('label');
  label.className = 'toggle-row';

  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = user.in_draw !== false;
  checkbox.disabled = isDrawn;

  const text = document.createElement('span');
  text.textContent = 'Include in Secret Santa draw';

  checkbox.addEventListener('change', async () => {
    checkbox.disabled = true;
    try {
      await api(`/api/users/${user.id}/draw`, {
        method: 'POST',
        body: JSON.stringify({ in_draw: checkbox.checked })
      });
      showToast(
        checkbox.checked ? `${user.display_name} is in the draw 🎲` : `${user.display_name} won't be in the draw`,
        'success'
      );
      await refreshState();
      renderApp();
    } catch (err) {
      checkbox.checked = !checkbox.checked;
      checkbox.disabled = false;
      showToast(err.message || 'Could not update draw inclusion', 'error');
    }
  });

  label.append(checkbox, text);
  return label;
}

function renderChildrenView() {
  const app = document.getElementById('app');
  const isDrawn = Boolean(state.event && state.event.is_drawn);

  const header = document.createElement('div');
  header.className = 'section-header';
  header.innerHTML = `
    <div>
      <h1 class="section-title">🧒 My Children</h1>
      <p class="section-subtitle">Add children who don't have their own login. You manage their wishlists and choose whether they take part in the draw.</p>
    </div>
  `;
  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'btn btn-primary';
  addBtn.innerHTML = '<span>+</span> Add Child';
  addBtn.addEventListener('click', () => openChildDialog());
  header.append(addBtn);
  app.append(header);

  if (isDrawn) {
    const lock = document.createElement('div');
    lock.className = 'shield-notice lock-notice';
    lock.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
      </svg>
      <div>
        <strong>Names have been drawn.</strong>
        You can still edit wishlists, but changing who's in the draw (or removing a child who is in it) needs the organiser to reset the draw first.
      </div>
    `;
    app.append(lock);
  }

  const children = state.children || [];
  if (children.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML = `
      <div class="empty-icon">🧒</div>
      <p class="empty-title">No children added yet</p>
      <p class="empty-desc">Add a child to give them their own wishlist. They won't need a username or password — you look after it for them.</p>
    `;
    const addFirst = document.createElement('button');
    addFirst.type = 'button';
    addFirst.className = 'btn btn-primary';
    addFirst.textContent = 'Add Your First Child 🧒';
    addFirst.addEventListener('click', () => openChildDialog());
    empty.append(addFirst);
    app.append(empty);
    return;
  }

  const grid = document.createElement('div');
  grid.className = 'cards-grid';

  children.forEach(child => {
    const card = document.createElement('article');
    card.className = 'item-card child-card';

    const top = document.createElement('div');
    top.className = 'item-card-top';
    const name = document.createElement('h2');
    name.className = 'item-title';
    name.textContent = child.display_name;
    const badges = document.createElement('div');
    badges.className = 'item-badges';
    const countBadge = document.createElement('span');
    countBadge.className = 'badge badge-child';
    countBadge.textContent = `${child.wishlist_count || 0} item${child.wishlist_count === 1 ? '' : 's'}`;
    badges.append(countBadge);
    top.append(name, badges);

    const meta = document.createElement('div');
    meta.className = 'child-meta';
    meta.append(buildDrawToggle(child, isDrawn));

    const assignment = state.childrenAssignments.find(a => a.child_id === child.id);
    if (assignment) {
      const line = document.createElement('div');
      line.className = 'child-assignment';
      line.append('🎁 Buying for: ');
      const link = document.createElement('a');
      link.href = `#wishlist/${assignment.receiver_id}`;
      link.textContent = assignment.receiver_display_name;
      line.append(link);
      meta.append(line);
    } else if (isDrawn && child.in_draw) {
      const line = document.createElement('div');
      line.className = 'child-assignment';
      line.textContent = '⏳ No recipient assigned';
      meta.append(line);
    }

    const footer = document.createElement('div');
    footer.className = 'item-footer';

    const manage = document.createElement('a');
    manage.className = 'btn btn-primary btn-sm';
    manage.href = `#wishlist/${child.id}`;
    manage.textContent = 'Manage Wishlist';

    const rename = document.createElement('button');
    rename.type = 'button';
    rename.className = 'btn btn-secondary btn-sm';
    rename.textContent = 'Rename';
    rename.addEventListener('click', () => openChildDialog(child));

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn btn-secondary btn-sm';
    remove.style.color = 'var(--color-danger)';
    remove.textContent = 'Remove';
    remove.addEventListener('click', async () => {
      if (!confirm(`Remove ${child.display_name} and their whole wishlist? This can't be undone.`)) return;
      try {
        await api(`/api/children/${child.id}`, { method: 'DELETE' });
        showToast(`${child.display_name} removed`, 'info');
        await refreshState();
        renderApp();
      } catch (err) {
        showToast(err.message || 'Could not remove child', 'error');
      }
    });

    footer.append(manage, rename, remove);
    card.append(top, meta, footer);
    grid.append(card);
  });

  app.append(grid);
}

function openChildDialog(existingChild = null) {
  const dialog = document.getElementById('child-dialog');
  const form = document.getElementById('child-form');
  if (!dialog || !form) return;

  form.reset();
  const isDrawn = Boolean(state.event && state.event.is_drawn);
  const inDrawGroup = form.querySelector('#child-in-draw-group');
  const inDrawBox = form.querySelector('#child-in-draw');

  if (existingChild) {
    document.getElementById('child-dialog-title').textContent = `Rename ${existingChild.display_name}`;
    form.querySelector('#child-id').value = existingChild.id;
    form.querySelector('#child-name').value = existingChild.display_name;
    form.querySelector('#child-submit-btn').textContent = 'Save';
    inDrawGroup.hidden = true;
  } else {
    document.getElementById('child-dialog-title').textContent = 'Add a Child';
    form.querySelector('#child-id').value = '';
    form.querySelector('#child-submit-btn').textContent = 'Add Child';
    inDrawGroup.hidden = false;
    // After the draw, new children can only be added outside the draw
    inDrawBox.checked = !isDrawn;
    inDrawBox.disabled = isDrawn;
  }

  dialog.showModal();
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
  const participantCount = drawParticipants().length;

  panel.innerHTML = `
    <div class="organiser-panel-header">
      <div>
        <h2 style="font-size: 1.25rem; font-weight: 700; margin-bottom: 0.25rem;">
          ${isDrawn ? '✅ Secret Santa Draw is Active!' : '🎲 Ready to Draw Names?'}
        </h2>
        <p style="color: var(--color-text-muted); font-size: 0.9375rem;">
          ${isDrawn 
            ? `Names were drawn on ${new Date(state.event.drawn_at).toLocaleDateString()}. Each family member can view their secret recipient.`
            : `${participantCount} of ${state.participants.length} people are in the draw. You need at least 2 people to draw.`}
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
  listTitle.textContent = `Participants Roster (${participantCount} in draw / ${state.participants.length} total)`;
  app.append(listTitle);

  const rosterHint = document.createElement('p');
  rosterHint.className = 'section-subtitle';
  rosterHint.style.marginBottom = '1rem';
  rosterHint.textContent = isDrawn
    ? 'Draw inclusion is locked while names are drawn. Reset the draw to change who takes part.'
    : 'Untick anyone who should have a wishlist but not take part in the draw.';
  app.append(rosterHint);

  const rosterGrid = document.createElement('div');
  rosterGrid.className = 'cards-grid';

  state.participants.forEach(u => {
    const card = document.createElement('div');
    card.className = 'item-card child-card';
    const roleBadge = u.is_child
      ? '<span class="badge badge-child">🧒 child</span>'
      : `<span class="badge ${u.role === 'organiser' ? 'badge-priority' : ''}">${escapeHtml(u.role)}</span>`;
    const identity = u.is_child
      ? `Managed by <strong>${escapeHtml(u.parent_display_name || 'unknown')}</strong>`
      : `Username: <code>@${escapeHtml(u.username)}</code>`;
    card.innerHTML = `
      <div class="item-card-top">
        <div style="font-weight: 700; font-size: 1.0625rem;">${escapeHtml(u.display_name)}</div>
        ${roleBadge}
      </div>
      <div style="color: var(--color-text-subtle); font-size: 0.875rem; margin-bottom: 0.5rem;">
        ${identity}
      </div>
      <div style="font-size: 0.9375rem; color: var(--color-text-muted); margin-bottom: 0.75rem;">
        Wishlist items added: <strong>${u.wishlist_count || 0}</strong>
      </div>
    `;
    card.append(buildDrawToggle(u, isDrawn));
    if (!u.is_child) card.append(buildAccountControls(u));
    rosterGrid.append(card);
  });

  app.append(rosterGrid);
}

function buildAccountControls(u) {
  const wrap = document.createElement('div');
  const sec = u.security || {};
  const isSelf = state.currentUser && u.id === state.currentUser.id;

  const badges = document.createElement('div');
  badges.className = 'item-badges';
  badges.style.marginTop = '0.75rem';
  if (sec.is_locked) {
    const b = document.createElement('span');
    b.className = 'badge badge-locked';
    const until = new Date(sec.locked_until).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    b.textContent = `🔒 Locked until ${until}`;
    b.title = 'Too many failed sign-in attempts';
    badges.append(b);
  } else if (sec.failed_logins > 0) {
    const b = document.createElement('span');
    b.className = 'badge badge-reset';
    b.textContent = `⚠️ ${sec.failed_logins} failed sign-in${sec.failed_logins === 1 ? '' : 's'}`;
    badges.append(b);
  }
  if (sec.must_change_password) {
    const b = document.createElement('span');
    b.className = 'badge badge-reset';
    b.textContent = '🔑 Temporary password';
    b.title = 'Will be asked to choose a new password at next sign-in';
    badges.append(b);
  }
  if (badges.childElementCount) wrap.append(badges);

  const actions = document.createElement('div');
  actions.className = 'account-actions';

  if (isSelf) {
    const link = document.createElement('a');
    link.href = '#account';
    link.className = 'btn btn-secondary btn-sm';
    link.textContent = 'Change my password';
    actions.append(link);
    wrap.append(actions);
    return wrap;
  }

  if (sec.is_locked) {
    const unlockBtn = document.createElement('button');
    unlockBtn.type = 'button';
    unlockBtn.className = 'btn btn-secondary btn-sm';
    unlockBtn.textContent = '🔓 Unlock';
    unlockBtn.addEventListener('click', async () => {
      try {
        await api(`/api/admin/users/${u.id}/unlock`, { method: 'POST' });
        showToast(`${u.display_name} can sign in again`, 'success');
        await refreshState();
        renderApp();
      } catch (err) {
        showToast(err.message || 'Could not unlock account', 'error');
      }
    });
    actions.append(unlockBtn);
  }

  const resetBtn = document.createElement('button');
  resetBtn.type = 'button';
  resetBtn.className = 'btn btn-secondary btn-sm';
  resetBtn.textContent = '🔑 Reset password';
  resetBtn.addEventListener('click', async () => {
    if (!confirm(`Reset ${u.display_name}'s password? Their current password will stop working and they'll be signed out everywhere.`)) return;
    try {
      const res = await api(`/api/admin/users/${u.id}/reset-password`, { method: 'POST' });
      showTempPassword(res);
      await refreshState();
      renderApp();
    } catch (err) {
      showToast(err.message || 'Could not reset password', 'error');
    }
  });
  actions.append(resetBtn);

  wrap.append(actions);
  return wrap;
}

function showTempPassword(res) {
  const dialog = document.getElementById('temp-password-dialog');
  if (!dialog) return;
  document.getElementById('temp-password-intro').textContent =
    `Give ${res.display_name} (username @${res.username}) this temporary password:`;
  document.getElementById('temp-password-value').textContent = res.temporary_password;
  dialog.showModal();
}

// ==========================================
// Dialog Logic (Add/Edit Item, Settings, Draw)
// ==========================================

function openItemDialog(existingItem = null, ownerId = null) {
  const dialog = document.getElementById('item-dialog');
  const titleEl = document.getElementById('item-dialog-title');
  const form = document.getElementById('item-form');
  if (!dialog || !form) return;

  form.reset();
  state.itemDialogOwnerId = ownerId ?? (state.currentUser && state.currentUser.id);
  const isForChild = state.currentUser && state.itemDialogOwnerId !== state.currentUser.id;
  const childName = isForChild && state.currentWishlist ? state.currentWishlist.user.display_name : '';
  form.querySelector('#item-owner-id').value = state.itemDialogOwnerId || '';

  if (existingItem) {
    titleEl.textContent = isForChild ? `Edit ${childName}'s Item` : 'Edit Wishlist Item';
    form.querySelector('#item-id').value = existingItem.id;
    form.querySelector('#item-title').value = existingItem.title || '';
    form.querySelector('#item-price').value = existingItem.price || '';
    form.querySelector('#item-url').value = existingItem.url || '';
    form.querySelector('#item-desc').value = existingItem.description || '';
    form.querySelector('#item-priority').value = existingItem.priority || 1;
  } else {
    titleEl.textContent = isForChild ? `Add Item for ${childName}` : 'Add Wishlist Item';
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
  form.querySelector('#setting-avoid-household').checked = evt.avoid_household !== 0;

  dialog.showModal();
}

// ==========================================
// Initialization & Global Event Listeners
// ==========================================

function initDialogListeners() {
  ['item-dialog', 'draw-dialog', 'reset-dialog', 'settings-dialog', 'child-dialog', 'temp-password-dialog'].forEach(setupDialog);

  // Copy temporary password (Clipboard API needs a secure context; fall back to selecting the text)
  const copyBtn = document.getElementById('copy-temp-password-btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', async () => {
      const valueEl = document.getElementById('temp-password-value');
      try {
        await navigator.clipboard.writeText(valueEl.textContent);
        showToast('Copied to clipboard', 'success');
      } catch {
        const range = document.createRange();
        range.selectNodeContents(valueEl);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        showToast('Selected. Press Ctrl+C / Cmd+C to copy', 'info');
      }
    });
  }

  // Clear the temporary password from the DOM once the dialog is closed
  const tempDialog = document.getElementById('temp-password-dialog');
  if (tempDialog) {
    tempDialog.addEventListener('close', () => {
      document.getElementById('temp-password-value').textContent = '';
    });
  }

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

      const ownerId = state.itemDialogOwnerId || (state.currentUser && state.currentUser.id);
      const isSelf = state.currentUser && ownerId === state.currentUser.id;
      if (!isSelf) data.user_id = ownerId;

      try {
        if (itemId) {
          await api(`/api/wishlist/${itemId}`, { method: 'PUT', body: JSON.stringify(data) });
          showToast('Wishlist item updated! 🎁', 'success');
        } else {
          await api('/api/wishlist', { method: 'POST', body: JSON.stringify(data) });
          showToast(isSelf ? 'Item added to your wishlist! 🎁' : 'Item added to their wishlist! 🎁', 'success');
        }
        document.getElementById('item-dialog').close();
        if (state.currentUser) {
          renderWishlistView(ownerId, isSelf);
        }
      } catch (err) {
        showToast(err.message || 'Error saving item', 'error');
      }
    });
  }

  // Child add / rename form
  const childForm = document.getElementById('child-form');
  if (childForm) {
    childForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const childId = childForm.querySelector('#child-id').value;
      const displayName = childForm.querySelector('#child-name').value.trim();
      try {
        if (childId) {
          await api(`/api/children/${childId}`, {
            method: 'PUT',
            body: JSON.stringify({ display_name: displayName })
          });
          showToast('Name updated', 'success');
        } else {
          await api('/api/children', {
            method: 'POST',
            body: JSON.stringify({
              display_name: displayName,
              in_draw: childForm.querySelector('#child-in-draw').checked
            })
          });
          showToast(`${displayName} added! Now add some gift ideas 🎁`, 'success');
        }
        document.getElementById('child-dialog').close();
        await refreshState();
        renderApp();
      } catch (err) {
        showToast(err.message || 'Could not save child', 'error');
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
        rules_note: settingsForm.querySelector('#setting-rules').value.trim(),
        avoid_household: settingsForm.querySelector('#setting-avoid-household').checked
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

function drawParticipants() {
  return (state.participants || []).filter(u => u.in_draw !== false);
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
    state.children = meData.children || [];
    state.childrenAssignments = meData.children_assignments || [];
    state.event = meData.event;
    if (meData.requires_registration_code !== undefined) {
      state.requiresRegistrationCode = Boolean(meData.requires_registration_code);
    }

    const eventData = await api('/api/event');
    state.participants = eventData.participants || [];
    if (eventData.requires_registration_code !== undefined) {
      state.requiresRegistrationCode = Boolean(eventData.requires_registration_code);
    }
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
