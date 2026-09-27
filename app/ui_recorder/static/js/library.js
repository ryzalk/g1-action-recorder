/* Library: every saved action and pose in one table per kind, what uses what, delete to data/.trash, import and export. */

const LIBRARY_KINDS = { base: "Base", left_arm: "Left arm", right_arm: "Right arm", composed: "Composed" };

class LibraryTab {
  constructor() {
    this.head = document.getElementById("library-head");
    this.rows = document.getElementById("library-rows");
    this.note = document.getElementById("library-note");
    this.tabs = [...document.querySelectorAll("[data-library-tab]")];
    this.poseFile = document.getElementById("library-pose-file");
    this.actionFile = document.getElementById("library-action-file");
    this.exportLink = document.getElementById("library-export");
    this.kind = "actions";
    this.listing = null;
    // Actions ticked for export; kept while the page is open.
    this.selected = new Set();
  }

  start() {
    for (const tab of this.tabs) {
      tab.addEventListener("click", () => {
        this.kind = tab.dataset.libraryTab;
        this.render();
      });
    }
    this.poseFile.addEventListener("change", () => this.importFile(this.poseFile, "poses", (result) => this.poseMessage(result)));
    this.actionFile.addEventListener("change", () => this.importFile(this.actionFile, "actions", (result) => this.actionMessage(result)));
    onTabShown("library", () => this.refresh());
  }

  async refresh() {
    this.listing = await api("GET", "/api/library");
    const names = new Set(this.listing.actions.map((action) => action.name));
    for (const name of this.selected) if (!names.has(name)) this.selected.delete(name);
    this.render();
  }

  render() {
    const listing = this.listing;
    for (const tab of this.tabs) {
      const kind = tab.dataset.libraryTab;
      tab.dataset.active = String(kind === this.kind);
      tab.querySelector("[data-count]").textContent = (kind === "actions" ? listing.actions : listing.poses[kind]).length;
    }
    this.exportLink.hidden = this.kind !== "actions";
    if (this.kind === "actions") {
      this.table([[this.selectAllBox(), "Name"], "Poses", "Length", "Compiled", ""], listing.actions.map((action) => this.actionRow(action)));
      this.note.textContent = "Tick one, several or all actions and Export selected: one .zip with actions/ and poses/ laid out like data/. Import action takes that .zip.";
      this.showSelection();
      return;
    }
    const poses = listing.poses[this.kind];
    const columns = ["Name", "Made from", "Used by", "Part of", ""];
    this.table(columns, poses.map((pose) => this.poseRow(pose)));
    this.note.textContent = `${LIBRARY_KINDS[this.kind]} poses. A pose is one .json file; Import pose takes one at a time.`;
  }

  table(columns, rows) {
    const head = document.createElement("tr");
    columns.forEach((title, index) => {
      const cell = document.createElement("th");
      if (typeof title === "string") cell.textContent = title;
      else cell.append(this.withBox(title[0], title[1]));
      cell.className = `px-4 py-2.5 font-semibold ${index === columns.length - 1 ? "text-end" : "text-start"}`;
      head.append(cell);
    });
    this.head.replaceChildren(head);
    if (rows.length === 0) {
      const empty = document.createElement("tr");
      empty.innerHTML = `<td colspan="${columns.length}" class="px-4 py-8 text-center text-gray-400">None saved</td>`;
      rows = [empty];
    }
    this.rows.replaceChildren(...rows);
  }

  row(cells) {
    const row = document.createElement("tr");
    row.className = "hover:bg-gray-50";
    cells.forEach((content, index) => {
      const cell = document.createElement("td");
      cell.className = `px-4 py-2.5 align-middle ${index === 0 ? "font-medium text-gray-900" : "text-gray-600"} ${index === cells.length - 1 ? "text-end" : ""}`;
      if (typeof content === "string") cell.textContent = content;
      else cell.append(...content);
      row.append(cell);
    });
    return row;
  }

  chips(names, empty = "—") {
    if (names.length === 0) return [Object.assign(document.createElement("span"), { className: "text-gray-300", textContent: empty })];
    const wrap = document.createElement("span");
    wrap.className = "flex flex-wrap gap-1";
    for (const name of names) {
      wrap.append(Object.assign(document.createElement("span"), {
        className: "rounded-md bg-blue-50 px-1.5 py-0.5 text-xs font-medium text-blue-700", textContent: name,
      }));
    }
    return [wrap];
  }

  badge(text, className) {
    const badge = Object.assign(document.createElement("span"), { textContent: text });
    badge.className = `inline-flex items-center gap-x-1 rounded-md px-1.5 py-0.5 text-xs font-medium ${className}`;
    return badge;
  }

  button(text, className, onClick) {
    const button = Object.assign(document.createElement("button"), { type: "button", textContent: text });
    button.className = `rounded-lg px-2 py-1 text-xs font-medium hover:bg-gray-100 disabled:opacity-40 ${className}`;
    button.addEventListener("click", () => onClick(button));
    return button;
  }

  // ---- choosing actions to export together ----
  checkbox(label) {
    const box = Object.assign(document.createElement("input"), { type: "checkbox" });
    box.className = "size-4 shrink-0 rounded border-gray-300 text-blue-600 focus:ring-blue-500";
    box.setAttribute("aria-label", label);
    return box;
  }

  withBox(box, text) {
    const wrap = document.createElement("label");
    wrap.className = "flex cursor-pointer items-center gap-x-3";
    wrap.append(box, Object.assign(document.createElement("span"), { textContent: text }));
    return wrap;
  }

  selectAllBox() {
    const box = this.checkbox("Select all actions");
    box.dataset.selectAll = "";
    box.addEventListener("change", () => {
      for (const action of this.listing.actions) {
        if (box.checked) this.selected.add(action.name);
        else this.selected.delete(action.name);
      }
      for (const row of this.rows.querySelectorAll("[data-select]")) row.checked = box.checked;
      this.showSelection();
    });
    return box;
  }

  showSelection() {
    const names = this.listing.actions.map((action) => action.name).filter((name) => this.selected.has(name));
    const all = this.head.querySelector("[data-select-all]");
    if (all) {
      all.checked = names.length > 0 && names.length === this.listing.actions.length;
      all.indeterminate = names.length > 0 && !all.checked;
    }
    this.exportLink.setAttribute("aria-disabled", String(names.length === 0));
    this.exportLink.querySelector("[data-label]").textContent = names.length ? `Export selected (${names.length})` : "Export selected";
    const query = new URLSearchParams(names.map((name) => ["names", name]));
    this.exportLink.href = names.length ? `/api/library/actions/export?${query}` : "#";
  }

  actionRow(action) {
    const box = this.checkbox(`Select ${action.name}`);
    box.dataset.select = action.name;
    box.checked = this.selected.has(action.name);
    box.addEventListener("change", () => {
      if (box.checked) this.selected.add(action.name);
      else this.selected.delete(action.name);
      this.showSelection();
    });
    const exportLink = Object.assign(document.createElement("a"), {
      href: `/api/library/actions/${encodeURIComponent(action.name)}/export`, download: `${action.name}.zip`, textContent: "Export",
    });
    exportLink.className = "rounded-lg px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100";
    const remove = this.button("Delete", "text-red-600", (button) => this.deleteAction(button, action.name));
    const compiled = action.compiled ? this.badge("✓ Compiled", "bg-green-50 text-green-700") : this.badge("Not compiled", "bg-amber-50 text-amber-700");
    return this.row([[this.withBox(box, action.name)], String(action.poses), `${action.seconds.toFixed(1)} s`, [compiled], [exportLink, remove]]);
  }

  poseRow(pose) {
    let end;
    if (pose.home) end = this.badge("Start and end of every action", "bg-gray-100 text-gray-500");
    else if (pose.used_by.length) end = this.badge("In use", "bg-gray-100 text-gray-500");
    else end = this.button("Delete", "text-red-600", (button) => this.deletePose(button, pose));
    if (end.tagName === "SPAN") {
      end.insertAdjacentHTML("afterbegin", '<svg class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>');
    }
    // Poses saved from Compose name their parts; recorded ones show a dash.
    const parts = pose.made_from || {};
    const arms = [["left_arm", "left"], ["right_arm", "right"]].filter(([type]) => parts[type]).map(([type, side]) => `${side} ${parts[type]}`);
    const madeFrom = [parts.base, ...arms].filter(Boolean).join(" + ") || "—";
    return this.row([pose.name, madeFrom, this.chips(pose.used_by), this.chips(pose.part_of), [end]]);
  }

  async deleteAction(button, name) {
    const confirmed = await confirmDialog({ title: `Delete action “${name}”?`, text: "Its JSON and NPZ move to data/.trash.", ok: "Delete", danger: true });
    if (!confirmed) return;
    if (await run(button, () => api("DELETE", `/api/library/actions/${encodeURIComponent(name)}`))) {
      toast(`Moved ${name} to data/.trash`);
      this.refresh();
    }
  }

  async deletePose(button, pose) {
    let text = "It moves to data/.trash.";
    if (pose.part_of.length === 1) text += ` ${pose.part_of[0]}, made from it, keeps its own copy of the values.`;
    if (pose.part_of.length > 1) text += ` ${pose.part_of.join(", ")}, made from it, keep their own copies of the values.`;
    const confirmed = await confirmDialog({ title: `Delete pose “${pose.name}”?`, text, ok: "Delete", danger: true });
    if (!confirmed) return;
    const url = `/api/library/poses/${this.kind}/${encodeURIComponent(pose.name)}`;
    if (await run(button, () => api("DELETE", url))) {
      toast(`Moved ${pose.name} to data/.trash`);
      this.refresh();
    }
  }

  async importFile(input, kind, message) {
    const file = input.files[0];
    // Clear it, so choosing the same file again still fires change.
    input.value = "";
    if (!file) return;
    const url = (overwrite) => `/api/library/${kind}/import?filename=${encodeURIComponent(file.name)}&overwrite=${overwrite}`;
    const result = await run(null, () => saveOrReplace(null, (overwrite) => api("POST", url(overwrite), file)));
    if (result) {
      toast(message(result), result.status === "unchanged" ? "info" : "success");
      this.refresh();
    }
  }

  poseMessage(result) {
    const label = `${result.pose_type}/${result.name}`;
    if (result.status === "unchanged") return `${label} is already saved, nothing changed`;
    return `${result.status === "added" ? "Added" : "Replaced"} ${label}`;
  }

  actionMessage(result) {
    const names = result.actions.map((action) => action.name);
    const what = names.length === 1 ? names[0] : `${names.length} actions`;
    if (result.status === "unchanged" && result.poses_added.length === 0) return `${what} ${names.length === 1 ? "is" : "are"} already saved, nothing changed`;
    const count = (items, verb) => `${items.length} pose${items.length === 1 ? "" : "s"} ${verb}`;
    const parts = [];
    if (names.length > 1) {
      for (const verb of ["added", "replaced", "unchanged"]) {
        const n = result.actions.filter((action) => action.status === verb).length;
        if (n) parts.push(`${n} ${verb === "unchanged" ? "kept" : verb}`);
      }
    }
    if (result.poses_added.length) parts.push(count(result.poses_added, "added"));
    if (result.poses_replaced.length) parts.push(count(result.poses_replaced, "replaced"));
    const verb = names.length > 1 ? "Imported" : { added: "Added", replaced: "Replaced", unchanged: "Kept" }[result.status];
    return `${verb} ${what}${parts.length ? ` · ${parts.join(", ")}` : ""}`;
  }
}

document.addEventListener("DOMContentLoaded", () => new LibraryTab().start());
