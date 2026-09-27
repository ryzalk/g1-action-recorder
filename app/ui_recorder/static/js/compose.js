/* Compose pose: a base plus optional saved arms, previewed on every change; saved as a base pose or one arm of it. */

const COMPOSE_SAVE_NOTES = {
  base: "Saves the whole robot: waist and both arms.",
  left_arm: "Saves only the left arm of what the robot shows.",
  right_arm: "Saves only the right arm of what the robot shows.",
};
const COMPOSE_OPEN_GROUPS = [["base", "Base"], ["left_arm", "Left arm"], ["right_arm", "Right arm"], ["composed", "Composed"]];

class ComposeTab {
  constructor() {
    this.root = document.querySelector('[data-page="compose"]');
    this.openSelect = document.getElementById("compose-open");
    this.base = document.getElementById("compose-base");
    this.left = document.getElementById("compose-left");
    this.right = document.getElementById("compose-right");
    this.nameInput = document.getElementById("compose-name");
    this.saveButton = document.getElementById("compose-save");
    this.home = "";
    this.made = [];
  }

  start() {
    for (const select of [this.base, this.left, this.right]) select.addEventListener("change", () => this.preview());
    for (const radio of this.root.querySelectorAll('input[name="compose-kind"]')) radio.addEventListener("change", () => this.showKind());
    this.openSelect.addEventListener("change", () => this.open());
    this.saveButton.addEventListener("click", () => this.save());
    document.getElementById("compose-new").addEventListener("click", () => this.startNew());
    this.showKind();
    onTabShown("compose", () => this.refresh());
  }

  kind() {
    return this.root.querySelector('input[name="compose-kind"]:checked').value;
  }

  setKind(kind) {
    this.root.querySelector(`input[name="compose-kind"][value="${kind}"]`).checked = true;
    this.showKind();
  }

  showKind() {
    this.root.querySelector("[data-save-as-note]").textContent = COMPOSE_SAVE_NOTES[this.kind()];
  }

  async refresh() {
    const { names, home, compositions } = await api("GET", "/api/poses");
    const options = (items) => [{ options: items.map((name) => ({ value: name, text: name })) }];
    this.home = home;
    this.made = compositions;
    // Open lists the poses made here, of any type, so their parts can be changed and saved again.
    const opened = this.openSelect.value;
    const lists = COMPOSE_OPEN_GROUPS.map(([type, title]) => ({
      label: title,
      options: compositions.filter((made) => made.pose_type === type).map((made) => ({ value: `${type}/${made.name}`, text: made.name })),
    })).filter((list) => list.options.length);
    fillSelect(this.openSelect, lists, "Open a pose made here…");
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
    this.setKind("base");
    this.preview();
  }

  composition() {
    return { base: this.base.value, left_arm: this.left.value, right_arm: this.right.value };
  }

  async preview() {
    if (this.base.value) await run(null, () => api("POST", "/api/poses/compose/preview", this.composition()));
  }

  async open() {
    if (!this.openSelect.value) return;
    const [type, name] = this.openSelect.value.split("/");
    const made = this.made.find((item) => item.pose_type === type && item.name === name);
    const selects = { base: this.base, left_arm: this.left, right_arm: this.right };
    for (const [part, select] of Object.entries(selects)) {
      select.value = made.source_parts[part] || "";
      // A deleted part is no longer an option; show the placeholder rather than a blank select.
      if (select.selectedIndex < 0) select.value = "";
    }
    this.nameInput.value = name;
    this.setKind(type === "composed" ? "base" : type);
    const labels = { base: "base", left_arm: "left arm", right_arm: "right arm" };
    const missing = Object.entries(made.source_parts).filter(([part, value]) => selects[part].value !== value);
    if (missing.length) {
      // Show the pose as saved: a part may have been replaced or deleted since.
      await run(null, () => api("POST", `/api/poses/${type}/${encodeURIComponent(name)}/show`));
      const parts = missing.map(([part, value]) => `${value} (${labels[part]})`).join(", ");
      toast(`${parts} ${missing.length === 1 ? "is" : "are"} no longer saved. The robot shows ${name} as saved.`, "info");
      return;
    }
    this.preview();
  }

  async save() {
    const name = this.nameInput.value.trim();
    if (!this.base.value || !name) {
      toast(name ? "Choose a base pose first" : "Enter a pose name first", "error");
      return;
    }
    const kind = this.kind();
    const result = await run(this.saveButton, () => saveOrReplace(name, (overwrite) =>
      api("POST", "/api/poses/compose", { ...this.composition(), name, overwrite, pose_type: kind })));
    if (result) {
      toast(`Saved ${result.name} (${{ base: "base", left_arm: "left-arm", right_arm: "right-arm" }[kind]} pose)`);
      await this.refresh();
      this.openSelect.value = `${kind}/${result.name}`;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => new ComposeTab().start());
