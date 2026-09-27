/* Compose pose: a base plus optional saved arms, previewed on every change; saved as a composed pose with its picture. */

class ComposeTab {
  constructor() {
    this.openSelect = document.getElementById("compose-open");
    this.base = document.getElementById("compose-base");
    this.left = document.getElementById("compose-left");
    this.right = document.getElementById("compose-right");
    this.nameInput = document.getElementById("compose-name");
    this.saveButton = document.getElementById("compose-save");
    this.picture = document.getElementById("compose-picture");
    this.home = "";
  }

  start() {
    for (const select of [this.base, this.left, this.right]) select.addEventListener("change", () => this.preview());
    this.openSelect.addEventListener("change", () => this.open());
    this.saveButton.addEventListener("click", () => this.save());
    document.getElementById("compose-new").addEventListener("click", () => this.startNew());
    onTabShown("compose", () => this.refresh());
  }

  async refresh() {
    const { names, home } = await api("GET", "/api/poses");
    const options = (items) => [{ options: items.map((name) => ({ value: name, text: name })) }];
    this.home = home;
    const opened = this.openSelect.value;
    fillSelect(this.openSelect, options(names.composed), "Open a composed pose…");
    this.openSelect.value = opened;
    if (this.openSelect.selectedIndex < 0) this.openSelect.value = "";
    fillSelect(this.base, options(names.base), "Choose a base pose");
    fillSelect(this.left, options(names.left_arm), "Keep the base's left arm");
    fillSelect(this.right, options(names.right_arm), "Keep the base's right arm");
    if (!this.base.value) this.base.value = home;
    // The robot should show what the form says as soon as the tab opens.
    this.preview();
  }

  startNew() {
    // The home base with its own arms, nothing opened, no name.
    this.openSelect.value = "";
    this.base.value = this.home;
    this.left.value = "";
    this.right.value = "";
    this.nameInput.value = "";
    this.showPicture(null);
    this.preview();
  }

  composition() {
    return { base: this.base.value, left_arm: this.left.value, right_arm: this.right.value };
  }

  async preview() {
    if (this.base.value) await run(null, () => api("POST", "/api/poses/compose/preview", this.composition()));
  }

  showPicture(name) {
    // The picture stored with the saved pose; a new ?t= after each save so the browser shows the new one.
    this.picture.hidden = !name;
    if (!name) return;
    this.picture.querySelector("img").src = `/api/poses/composed/${encodeURIComponent(name)}/preview.png?t=${Date.now()}`;
    this.picture.querySelector("[data-picture-name]").textContent = name;
  }

  async open() {
    const name = this.openSelect.value;
    if (!name) return;
    // Show the pose as saved: a part may have been replaced or deleted since it was composed.
    const pose = await run(null, () => api("POST", `/api/poses/composed/${encodeURIComponent(name)}/show`));
    if (!pose) return;
    const selects = { base: this.base, left_arm: this.left, right_arm: this.right };
    for (const [type, select] of Object.entries(selects)) {
      select.value = pose.source_parts[type] || "";
      // A deleted part is no longer an option; show the placeholder rather than a blank select.
      if (select.selectedIndex < 0) select.value = "";
    }
    this.nameInput.value = name;
    this.showPicture(name);
    const labels = { base: "base", left_arm: "left arm", right_arm: "right arm" };
    const missing = Object.entries(pose.source_parts).filter(([type, part]) => selects[type].value !== part);
    if (missing.length) {
      const parts = missing.map(([type, part]) => `${part} (${labels[type]})`).join(", ");
      toast(`${parts} ${missing.length === 1 ? "is" : "are"} no longer saved. The robot shows ${name} as saved.`, "info");
    }
  }

  async save() {
    const name = this.nameInput.value.trim();
    if (!this.base.value || !name) {
      toast(name ? "Choose a base pose first" : "Enter a name for the composed pose", "error");
      return;
    }
    const result = await run(this.saveButton, () => saveOrReplace(name, (overwrite) =>
      api("POST", "/api/poses/compose", { ...this.composition(), name, overwrite })));
    if (result) {
      toast(`Saved ${result.name} (composed pose, with its picture)`);
      await this.refresh();
      this.openSelect.value = result.name;
      this.showPicture(result.name);
    }
  }
}

document.addEventListener("DOMContentLoaded", () => new ComposeTab().start());
