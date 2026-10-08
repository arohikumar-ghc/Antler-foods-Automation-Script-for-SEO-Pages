# Antler CMS — UI Investigation (Phase 4, Step 10)

Verified investigation of the real Antler CMS used to build the Antler Foods SEO
automation. Evidence comes from **live read-only DOM inspection** and a
**Playwright codegen recording**, both against the production app using the
**Renovo** restaurant.

> **Credentials:** never stored here or in code. The automation reads
> `ANTLER_EMAIL` / `ANTLER_PASSWORD` / `ANTLER_BASE_URL` from `.env` only.
> The codegen recording contained hard-coded credentials purely as a Playwright
> artifact; they were redacted and never committed.

Status legend: ✅ verified · ⚠️ fragile (needs cleanup) · ❓ unknown / not captured.

---

## 1. Environment overview

- **App:** `https://app.tryantler.com` — a multi-tenant restaurant management
  dashboard ("Antler Dashboard" / "Antler Foods").
- **Framework (observed):** React single-page app, Tailwind CSS utility
  classes, client-side routing. Many controls expose stable `id` attributes and
  good accessible roles/names — far friendlier than Food Amigo's Ant Design.
- **Login page title:** "Admin Sign In - Antler Foods".
- **Anti-bot:** Cloudflare **Turnstile** is present on the login page. In
  managed mode it auto-passed in testing (login succeeded without solving a
  visible challenge).
- **Test tenant:** **Renovo** (`restaurant_id=804fb796-1876-4e6b-874b-b4c5f95dc140`).

---

## 2. Authentication flow ✅

1. `GET {base}/login`.
2. Fill **Email Address** → `#email-address` (role: textbox "Email Address").
3. Fill **Password** → `#password` (role: textbox "Password").
4. **Cloudflare Turnstile** iframe present (`iframe[src*='challenges.cloudflare.com']`).
   Auto-passed in managed mode; the recording clicked its body but a token was
   not required for success. ⚠️ The iframe `src` carries a per-session token and
   must never be hard-coded.
5. Click **Sign In** (role: button "Sign In").
6. **Success:** URL changes from `/login` to `/dashboard/admin/home`
   (title "Dashboard - Antler Foods"). This URL change is the login-success
   signal. ✅
7. **MFA/OTP/SSO:** none observed — plain email/password. ✅
8. **Redirect vs popup:** redirect-based (no popup). Unauthenticated access to a
   dashboard URL redirects to `/login?next=<path>`.
9. **Wrong-credential error state:** ❓ not captured (never submitted bad
   credentials). Must be investigated before relying on error handling.

---

## 3. Navigation flow ✅

Sidebar sections (buttons): **HOME, ORDERS & SALES, MENU, WEBSITE, MARKETING,
GROWTH, SETTINGS**.

Path to SEO page management:
1. Select a restaurant (see §4).
2. Click **WEBSITE** (role: button "Website") to expand the section.
3. Click **Pages** (role: link "Pages") →
   `/dashboard/admin/website/pages-settings`.

The WEBSITE group also contains: Forms, Navbar Settings, Global Style,
Announcement Bar, Footer Settings, Popup Settings, Domain Settings, QR Codes,
Blog Posts, Our Locations, Inject Code. **SEO pages live under Pages.**

**Editor-ready indicator:** presence of the **Add Section** button in the page
editor. ✅

---

## 4. Tenant / site behavior ✅

Antler is **multi-tenant** — all work happens in the context of a selected
restaurant.

- A **"Search restaurant…"** textbox (top of the app) filters restaurants.
- Typing a name shows suggestion **buttons**; clicking one selects it.
- After selection, **every dashboard URL carries
  `?restaurant_id=<uuid>&restaurant_name=<name>`**, and the full WEBSITE sidebar
  appears. This query-string tenancy means the automation can navigate directly
  to `/dashboard/admin/website/pages-settings?restaurant_id=...&restaurant_name=...`
  once the id is known.
- A **"Clear selected restaurant"** button resets the selection.
- Renovo id: `804fb796-1876-4e6b-874b-b4c5f95dc140`.

---

## 5. Page existence behavior ✅

The Pages screen is a **table**: columns `PAGE | URL SLUG | STATUS | VISIBILITY
| UPDATED | ACTIONS`.

- Pages are identified by **Page Name** and a unique **URL slug** (e.g.
  `/about`). Internally each page also has a `page_id` UUID (visible in the
  editor URL).
- **STATUS:** `Draft` or `Published`. **VISIBILITY:** Nav / Footer tags.
- Row **ACTIONS** (icon buttons, identified by `title`):
  - **Publish** / **Unpublish**
  - **Edit page**
  - **View page**
  - **Delete page** — **only on user-created pages**. The 6 built-in **System**
    pages (Catering, About, Menu, Location, Contact, Home) have **no delete**,
    and Menu additionally shows "Menu page cannot be edited here" (disabled).
- **Idempotency approach:** read the table rows and match on URL slug (primary)
  or Page Name. No dedicated search box on this table was found; matching is
  done by scanning rows.

---

## 6. Page creation flow ✅

1. Click **Create Page** (role: button "Create Page") → opens a modal.
2. Modal fields (stable ids):
   - **Page Name\*** → `#name` (placeholder "About Us")
   - **URL Slug\*** → `#url_slug` (placeholder "about-us"; auto-derived from
     name if left blank)
   - **Meta Title** → `#meta_title` (label "Meta Title(0/60)")
   - **Meta Description** → `#meta_description` (label "Meta Description(0/160)")
   - **Open Graph Image** → "Choose Image from Gallery" / "Generate with AI"
   - **Keywords** → `#keywords` (optional)
   - **Published** → `#modal_published` (checkbox)
   - **Show in Navbar** → `#modal_show_on_navbar` (checkbox)
   - **Show in Footer** → `#modal_show_on_footer` (checkbox)
3. Submit: the modal's **Create Page** button (scope to the form:
   `form >> role=button[name="Create Page"]` — there are two "Create Page"
   buttons on screen: the list header and the modal submit).
4. **Creation persists immediately** and returns to the Pages list; the new row
   appears (as **Draft** when Published is unchecked). ✅
5. **SEO metadata is captured at creation time** here (Meta Title/Description),
   and is also editable later via the editor SEO panel (§8).

**Separate edit mode:** yes. After creation, open the page via **Edit page**
→ `/admin/page-settings?...&page_id=...` (the section-based editor).

---

## 7. Basic information fields ✅

Two places set basic info:
- **Create modal:** `#name`, `#url_slug` (see §6).
- **Editor → Page Settings → Edit:** `#page-name-input`, `#page-slug-input`,
  with **Cancel** / **Save** buttons and Navbar/Footer visibility checkboxes.

---

## 8. SEO fields ✅

Two entry points:
- **Create modal** (`#meta_title`, `#meta_description`, `#keywords`) — set at
  creation.
- **Editor → SEO panel** (header **SEO** button, role: button "SEO"): fields are
  anchored by placeholder (no ids):
  - **Meta Title** → placeholder "Your page title for search engines"
  - **Meta Description** → placeholder "A brief description of your page content
    for search results"
  - **Meta Keywords** → placeholder "food, dining, delivery, catering, online
    ordering"
  - **Social Sharing Image** (see §9)
  - Live **SEO Preview** (Google Search Result + Social Media Preview).

**Persistence check:** reload the editor / revisit the SEO panel and read the
field values; the pages table also reflects the Meta Title under the page name.

---

## 9. Social fields ⚠️ (important divergence from Food Amigo)

**Antler has NO dedicated social *title* or social *description* text fields.**
The SEO **Meta Title** and **Meta Description** double as the social/open-graph
preview (shown in the "Social Media Preview"). The only social-specific control
is an **Open Graph / "Social Sharing Image"** chooser
(role: button "Choose Image from Gallery", also "Generate with AI").

**Implication for the data model:** `social_title` / `social_description` have no
target UI in Antler. The automation should map SEO title/description to the
social preview (which Antler does automatically) and treat social image as part
of the deferred image phase.

---

## 10. Content / body structure ✅

Content is **section-based**. The editor shows **Active Sections** (drag to
reorder) and an **Add Section** control (empty pages show **"Add Your First
Section"**).

**Add Section → section-type catalog** (categories, each with layout variants):
Hero · **Customizable** · Menu · Gallery · Location Tracker · Google Review ·
YouTube/Video · **FAQ** · Scrolling Text · Timeline · Custom Code/iFrame ·
Form Display.

Our body-content requirement maps to the **Customizable** category
("Create custom content sections with professional layout options"). Selecting
it opens `/admin/custom-section-settings?...&new_section=true` with fields
(anchored by placeholder; plain inputs, not rich text):
- **Headline** → placeholder "Enter headline"  → maps to our `title`
- **Subheadline** → placeholder "Enter subheadline" → maps to our `subtitle`
- **Description** → placeholder "Enter description" (textarea) → maps to our
  `description`
- Plus: Background Image, Primary/Secondary CTA (Label + Link), Typography &
  Animation.
- **Save:** button **"Save Custom Section Settings"**. ✅

⚠️ The recording selected the Customizable category via a **positional** locator
(`div:nth-child(2) > .mb-3 > .flex > .h-4`). Prefer the category **heading text
"Customizable"** instead (recorded fallback kept).

---

## 11. FAQ structure ✅

FAQ is a **section type** (category "FAQ" — "Manage frequently asked questions";
layouts: Accordion, Grid, Two Column). Selecting it opens
`/admin/faq-settings?...&new_section=true` with:
- Section-level: **Section Title** (placeholder "Frequently Asked Questions"),
  **Section Subtitle**, **Description**.
- **FAQ Management**: **Add FAQ** button (role: button "Add FAQ") appends an
  empty item. Each item has:
  - **Question** → placeholder "Enter your question here..."
  - **Answer** → placeholder "Enter the answer here..." (textarea)
- **Multiple FAQs:** click **Add FAQ** again; address items by index
  (`.nth(0)`, `.nth(1)`, …). The recording added **3** items this way. ✅
- **Save:** button **"Create FAQ Section"** (saves the whole section at once —
  FAQ items are **not** saved individually). ✅

---

## 12. Save / publish behavior ✅ / ❓

- **Per-section save:** each section has its own save
  (**Save Custom Section Settings**, **Create FAQ Section**); Page Settings has
  **Save**. There is **no single global "save everything"** button.
- **Publish:** a **Publish** control exists both in the editor header and per row
  (Publish/Unpublish). Pages are **Draft** until published; Draft pages are not
  publicly visible — making a draft the safe state for testing.
- **Autosave:** not confirmed; treat each section's explicit Save as required.
- **Success indicator / toast:** ❓ not reliably captured — must be investigated
  to implement robust post-save verification. For now, verification can reload
  the editor / re-read the pages table.
- **Navigation away before saving:** not formally tested; assume unsaved section
  edits are lost (standard for this kind of editor).

---

## 13. Recovery behavior

- **Clean editor state** is reached by navigating directly to
  `/dashboard/admin/website/pages-settings?restaurant_id=...&restaurant_name=...`,
  or via the editor **Back** button (role: button "Back").
- The tenant context must be present on the URL; otherwise the app redirects to
  login/home. Direct URL navigation with the `restaurant_id` query is the most
  stable reset.

---

## 14. Selector map

Authoritative, machine-readable values live in
`antler_seo/automation/selectors.py`. Summary of the most important ones:

| Logical name | Strategy | Value | Verified | Notes |
|---|---|---|---|---|
| auth.email_field | css | `#email-address` | ✅ | fallback role "Email Address" |
| auth.password_field | css | `#password` | ✅ | fallback role "Password" |
| auth.login_button | role | button "Sign In" | ✅ | |
| auth.turnstile_iframe | css | `iframe[src*='challenges.cloudflare.com']` | ⚠️ | per-session token; usually auto-passes |
| auth.login_success_indicator | url | `/dashboard/admin/home` | ✅ | |
| auth.login_error_indicator | — | — | ❓ | not captured |
| navigation.restaurant_search | placeholder | "Search restaurant..." | ✅ | |
| navigation.restaurant_option | role | button "{restaurant_name}" | ✅ | e.g. "Renovo" |
| navigation.website_nav | role | button "Website" | ✅ | |
| navigation.pages_link | role | link "Pages" | ✅ | |
| navigation.editor_ready_indicator | role | button "Add Section" | ✅ | |
| page.create_page_button | role | button "Create Page" | ✅ | |
| page.create_modal_name | css | `#name` | ✅ | |
| page.create_modal_slug | css | `#url_slug` | ✅ | |
| page.create_modal_meta_title | css | `#meta_title` | ✅ | |
| page.create_modal_meta_description | css | `#meta_description` | ✅ | |
| page.create_submit | css | `form >> button "Create Page"` | ✅ | avoid header button |
| page.row_edit_button | css | `button[title='Edit page']` | ✅ | scope per row |
| page.row_delete_button | css | `button[title='Delete page']` | ✅ | user pages only |
| page.delete_confirm_button | role | button "Delete Page" | ✅ | |
| seo.seo_panel_button | role | button "SEO" | ✅ | |
| seo.seo_panel_meta_title | placeholder | "Your page title for search engines" | ✅ | |
| seo.seo_panel_meta_description | placeholder | "A brief description…search results" | ✅ | |
| social.social_title_field | — | — | ❓ | NOT PRESENT in Antler |
| social.social_description_field | — | — | ❓ | NOT PRESENT in Antler |
| social.social_image_gallery_button | role | button "Choose Image from Gallery" | ✅ | image phase (deferred) |
| content.add_first_section_button | role | button "Add Your First Section" | ✅ | empty-state |
| content.add_section_button | role | button "Add Section" | ✅ | |
| content.customizable_category | text | "Customizable" | ⚠️ | recording used nth-child |
| content.customizable_headline | placeholder | "Enter headline" | ✅ | → title |
| content.customizable_subheadline | placeholder | "Enter subheadline" | ✅ | → subtitle |
| content.customizable_description | placeholder | "Enter description" | ✅ | → description |
| content.customizable_save | role | button "Save Custom Section Settings" | ✅ | |
| faq.faq_category | text | "FAQ" | ⚠️ | recording used nth-child |
| faq.add_faq_item_button | role | button "Add FAQ" | ✅ | |
| faq.faq_question_field | placeholder | "Enter your question here..." | ✅ | use .nth(i) |
| faq.faq_answer_field | placeholder | "Enter the answer here..." | ✅ | use .nth(i) |
| faq.faq_save | role | button "Create FAQ Section" | ✅ | |
| finalization.publish_button | role | button "Publish" | ✅ | |
| finalization.section_drag_handle | title | "Drag this section to reorder" | ⚠️ | reorder only |
| finalization.success_indicator | — | — | ❓ | toast not captured |

### Fragile selectors to clean before production
- `content.customizable_category` & `faq.faq_category` — recording used
  **positional** `div:nth-child(N) > .mb-3 > .flex > .h-4`. Replace with the
  category **heading text** ("Customizable" / "FAQ"). Fallbacks retained.
- `auth.turnstile_iframe` — `src` holds a per-session token; match on
  `src*='challenges.cloudflare.com'` only, and prefer not interacting unless a
  visible challenge appears.
- Any `.flex.items-center.rounded-xl` picker chain from the first recording —
  **do not use**; use the "Search restaurant…" placeholder instead.
- Volatile accessible names containing live counters (e.g.
  "Meta Title(0/60)") — prefer the stable `#meta_title` / `#meta_description`
  ids over role-name.

---

## 15. Unknowns (not captured)

1. **Wrong-credential error UI** on login.
2. **Save-success toast/notification** text/selector (needed for strong
   post-save verification).
3. **Customizable layout picker** — a specific layout variant was chosen in the
   recording via a positional selector; the mapping of layout name → selector is
   not yet stable.
4. **Open Graph / Social Sharing Image** gallery flow internals (deferred with
   the image phase).
5. **Slug-collision behavior** — what the UI does when creating a page whose slug
   already exists (two drafts with `/renovo` coexisted, so duplicates may be
   allowed; needs confirmation).
6. **Autosave** / data-loss-on-navigate behavior.

---

## 16. Risks

- **Turnstile** could, under stricter configuration, present a real challenge
  and block automated login. Mitigation: run non-headless and allow manual
  solve; detect and surface rather than bypass.
- **Positional selectors** for section categories are brittle; must be replaced
  with text-based selectors.
- **No global save** means partial-save states are real — the per-section status
  model (already in `models.py`) is the right fit.
- **Slug uniqueness not enforced visibly** — the automation must do its own
  duplicate-slug / existing-page check before creating (idempotency).
- **Social fields absent** — the blueprint's social step must be re-scoped to
  "SEO doubles as social + optional OG image", not separate social text fields.

---

## 17. Recommendations for Steps 11–16

1. **Step 11 (login):** goto `/login`; fill `#email-address`, `#password`; click
   "Sign In"; wait for URL `**/dashboard/admin/home`. Treat Turnstile as
   auto-pass; if a visible challenge or staying on `/login` is detected, stop and
   report (non-headless manual solve). Read credentials from `.env` only.
2. **Step 12 (navigation / tenant):** implement `select_restaurant(name)` via the
   "Search restaurant…" box + suggestion button; capture `restaurant_id` from the
   URL and thereafter navigate directly to pages-settings with the query string.
3. **Step 13 (page existence):** load pages-settings, scan table rows, match on
   URL slug (normalized) then Page Name. Return exists/not-exists; skip on match.
4. **Step 14 (create page):** open Create Page modal; fill `#name`, `#url_slug`,
   `#meta_title`, `#meta_description`; set `#modal_published` deliberately;
   submit the **form-scoped** Create Page button; verify the new row appears.
5. **Step 15 (basic info + SEO):** since the create modal already captures basic
   info **and** SEO metadata, Steps 14–15 can be fused; add the editor SEO panel
   path for updates. Verify by re-reading the row / SEO panel.
6. **Step 16 (content + FAQ):** open the editor; **Add Section → Customizable**
   (select by heading text, not nth-child) → fill Headline/Subheadline/
   Description → **Save Custom Section Settings**; then **Add Section → FAQ** →
   **Add FAQ** per item (index-addressed) → **Create FAQ Section**.
7. **Cross-cutting:** build everything through the central
   `antler_seo/automation/selectors.py`; replace ⚠️ fragile entries first; add a
   real **post-save verification** once the success-toast selector is known;
   keep **social** mapped to SEO + deferred image; use the **Delete page** flow
   only for test cleanup, never on System pages.

---

## Test content created during investigation — and cleanup

The codegen recording and one exploratory create **did** persist draft pages on
Renovo (both named "Renovo", slug `/renovo`, **Draft**, not public). Both were
**deleted** at the end of the investigation via the **Delete page → Delete Page**
flow. Renovo was confirmed back to its original **6 System pages**
(Catering, About, Menu, Location, Contact, Home) with no leftover test content.
No System/production pages were modified.
