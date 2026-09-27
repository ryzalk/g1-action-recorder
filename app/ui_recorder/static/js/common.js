/* Shared helpers: API calls, toasts, the confirm dialog, select filling, and which page is shown. */

const DEGREES_PER_RADIAN = 180 / Math.PI;

function detailText(detail) {
  // FastAPI validation errors arrive as a list; our own errors as one string.
  if (Array.isArray(detail)) {
    return detail.map((item) => `${item.loc[item.loc.length - 1]}: ${item.msg}`).join("; ");
  }
  return detail || "";
}

async function api(method, url, body) {
  const options = { method, headers: { Accept: "application/json" } };
  if (body instanceof Blob) {
    options.body = body;
    options.headers["Content-Type"] = "application/octet-stream";
  } else if (body !== undefined) {
    options.body = JSON.stringify(body);
    options.headers["Content-Type"] = "application/json";
  }
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(detailText(data.detail) || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function toast(message, kind = "success", link = null) {
  const styles = {
    success: ["border-green-200 bg-green-50 text-green-800", "M20 6 9 17l-5-5"],
    error: ["border-red-200 bg-red-50 text-red-800", "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0"],
    warning: ["border-amber-200 bg-amber-50 text-amber-800", "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0"],
    info: ["border-blue-200 bg-blue-50 text-blue-800", "M12 16v-4M12 8h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0"],
  };
  const [colors, path] = styles[kind];
  const item = document.createElement("div");
  item.className = `pointer-events-auto flex items-start gap-x-2.5 rounded-xl border px-3.5 py-2.5 text-[13px] shadow-sm ${colors}`;
  item.setAttribute("role", kind === "error" ? "alert" : "status");
  item.innerHTML = `<svg class="mt-0.5 size-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"/></svg>`;
  const text = document.createElement("div");
  text.className = "min-w-0 break-words";
  text.append(Object.assign(document.createElement("p"), { textContent: message }));
  if (link) {
    const anchor = Object.assign(document.createElement("a"), { href: link.href, textContent: link.text, download: "" });
    anchor.className = "mt-0.5 inline-block text-xs font-medium text-blue-700 underline";
    text.append(anchor);
  }
  item.append(text);
  const area = document.getElementById("toasts");
  area.append(item);
  // A burst of messages (undo, redo, an edit) keeps only the latest three on screen.
  while (area.children.length > 3) area.firstElementChild.remove();
  setTimeout(() => item.remove(), kind === "error" ? 8000 : 4500);
}

function confirmDialog({ title, text = "", ok = "OK", danger = false }) {
  // Resolves true for the main button (or Enter), false for Cancel or Esc.
  const dialog = document.getElementById("confirm-dialog");
  const icon = dialog.querySelector("[data-icon]");
  icon.className = `flex size-10 shrink-0 items-center justify-center rounded-full ${danger ? "bg-red-50 text-red-600" : "bg-amber-50 text-amber-700"}`;
  icon.innerHTML = danger
    ? '<svg class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>'
    : '<svg class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>';
  dialog.querySelector("[data-title]").textContent = title;
  dialog.querySelector("[data-text]").textContent = text;
  const okButton = dialog.querySelector("[data-ok]");
  okButton.textContent = ok;
  okButton.classList.toggle("bg-red-600", danger);
  okButton.classList.toggle("hover:bg-red-700", danger);
  okButton.classList.toggle("bg-blue-600", !danger);
  okButton.classList.toggle("hover:bg-blue-700", !danger);
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
  });
}

async function saveOrReplace(name, send) {
  // send(overwrite) does the request; a 409 means the name is taken, so ask once and retry.
  // Without a name the server's 409 text is the question (an import names everything it would replace).
  try {
    return await send(false);
  } catch (error) {
    if (error.status !== 409) throw error;
    const question = name
      ? { title: `Replace “${name}”?`, text: "Something with this name already exists. Saving replaces it." }
      : { title: "Replace what's already saved?", text: error.message };
    if (!(await confirmDialog({ ...question, ok: "Replace" }))) return null;
    return await send(true);
  }
}

async function run(button, task) {
  // Disable the button while its request runs and show any failure as a toast.
  if (button) button.disabled = true;
  try {
    return await task();
  } catch (error) {
    toast(error.message, "error");
    return null;
  } finally {
    if (button) button.disabled = false;
  }
}

function fillSelect(select, groups, placeholder) {
  // groups: [{label, options: [{value, text}]}]; a group without label adds plain options.
  const kept = select.value;
  select.replaceChildren(...(placeholder === null ? [] : [new Option(placeholder, "")]));
  for (const group of groups) {
    const parent = group.label ? document.createElement("optgroup") : select;
    if (group.label) {
      parent.label = group.label;
      select.append(parent);
    }
    for (const option of group.options) parent.append(new Option(option.text, option.value));
  }
  if ([...select.options].some((option) => option.value === kept)) select.value = kept;
}

function onTabShown(pageId, callback) {
  document.addEventListener("recorder:tab", (event) => {
    if (event.detail === pageId) callback();
  });
}

function currentPage() {
  return document.querySelector("[data-page]:not(.hidden)")?.dataset.page;
}

function showPage(pageId) {
  const section = document.querySelector(`[data-page="${pageId}"]`) || document.querySelector('[data-page="record"]');
  pageId = section.dataset.page;
  for (const page of document.querySelectorAll("[data-page]")) {
    page.classList.toggle("hidden", page !== section);
    page.classList.toggle("flex", page === section);
  }
  // The robot view belongs to the four workflow pages; the others take the full width.
  document.getElementById("stage").hidden = section.dataset.wide === "true";
  for (const link of document.querySelectorAll("[data-nav]")) link.dataset.active = String(link.dataset.nav === pageId);
  const group = document.querySelector('[data-nav-group="speech"]');
  group.dataset.active = String(pageId.startsWith("speech-"));
  document.getElementById("page-select").value = pageId;
  document.getElementById("page-title").textContent = section.dataset.title;
  document.getElementById("page-hint").textContent = section.dataset.hint;
  document.getElementById("audio-badge").hidden = !pageId.startsWith("speech-");
  document.title = `${section.dataset.title} · G1 Concierge Studio`;
  if (location.hash !== `#${pageId}`) history.replaceState(null, "", `#${pageId}`);
  document.dispatchEvent(new CustomEvent("recorder:tab", { detail: pageId }));
}

document.addEventListener("keydown", (event) => {
  // Enter in a name field presses its Save button, as it would in a form.
  if (event.key === "Enter" && event.target.dataset.enter) {
    document.getElementById(event.target.dataset.enter).click();
  }
});

window.addEventListener("hashchange", () => showPage(location.hash.slice(1)));

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("page-select").addEventListener("change", (event) => { location.hash = event.target.value; });
  // After every page script's own DOMContentLoaded handler, so they hear which page opens first.
  setTimeout(() => showPage(location.hash.slice(1) || "record"));
});
