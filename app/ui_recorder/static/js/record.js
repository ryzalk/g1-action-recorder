/* Record pose: 17 sliders in degrees. Open lists every pose; Save as decides which groups are edited and what Save writes. */

const POSE_TYPES = {
  composed: { label: "composed", groups: ["waist", "left_arm", "right_arm"] },
  left_arm: { label: "left-arm", groups: ["left_arm"] },
  right_arm: { label: "right-arm", groups: ["right_arm"] },
};
// Open lists these, in this order. An arm pose saves again as that arm; a base or composed one as composed.
const OPEN_GROUPS = [["base", "Base"], ["composed", "Composed"], ["left_arm", "Left arm"], ["right_arm", "Right arm"]];

class RecordTab {
  constructor() {
    this.root = document.querySelector('[data-page="record"]');
    this.rows = [...this.root.querySelectorAll("[data-joint]")];
    this.cards = [...this.root.querySelectorAll("[data-group]")];
    this.openSelect = document.getElementById("record-open");
    this.nameInput = document.getElementById("record-name");
    this.saveButton = document.getElementById("record-save");
    this.names = { base: [], composed: [], left_arm: [], right_arm: [] };
    this.values = {};
    // While a slider is held, incoming state must not move it under the pointer.
    this.held = null;
  }

  start() {
    for (const row of this.rows) {
      const joint = row.dataset.joint;
      const slider = row.querySelector("[data-slider]");
      const number = row.querySelector("[data-number]");
      row.querySelector("[data-joint-reset]")?.addEventListener("click", () => this.setJoint(joint, Number(row.dataset.home)));
      slider.addEventListener("pointerdown", () => { this.held = joint; });
      slider.addEventListener("pointerup", () => { this.held = null; });
      slider.addEventListener("input", () => this.setJoint(joint, Number(slider.value) / DEGREES_PER_RADIAN));
      number.addEventListener("change", () => {
        const clamped = Math.min(Number(number.max), Math.max(Number(number.min), Number(number.value) || 0));
        this.setJoint(joint, clamped / DEGREES_PER_RADIAN);
      });
    }
    for (const button of this.root.querySelectorAll("[data-reset]")) {
      button.addEventListener("click", () => this.reset(button.dataset.reset));
    }
    for (const button of this.root.querySelectorAll("[data-mirror]")) {
      button.addEventListener("click", () => this.mirror(button));
    }
    for (const radio of this.root.querySelectorAll('input[name="record-kind"]')) {
      radio.addEventListener("change", () => this.showKind());
    }
    this.openSelect.addEventListener("change", () => this.open());
    document.getElementById("record-new").addEventListener("click", () => this.startNew());
    this.saveButton.addEventListener("click", () => this.save());
    robotLink.on("robot", (state) => this.showState(state.joint_positions));
    onTabShown("record", () => this.refresh());
  }

  kind() {
    return this.root.querySelector('input[name="record-kind"]:checked').value;
  }

  async refresh() {
    const { names, home_values: home } = await api("GET", "/api/poses");
    this.names = names;
    // Reset goes back to the saved home pose, which can be replaced here or in the Library.
    for (const row of this.rows) row.dataset.home = home[row.dataset.joint];
    const opened = this.openSelect.value;
    const lists = OPEN_GROUPS.map(([type, title]) => ({
      label: title, options: this.names[type].map((name) => ({ value: `${type}/${name}`, text: name })),
    })).filter((list) => list.options.length);
    fillSelect(this.openSelect, lists, "Open a saved pose…");
    this.openSelect.value = opened;
    if (this.openSelect.selectedIndex < 0) this.openSelect.value = "";
    this.showKind();
  }

  setKind(kind) {
    this.root.querySelector(`input[name="record-kind"][value="${kind}"]`).checked = true;
    this.showKind();
  }

  showKind() {
    // The other arm folds away when an arm is saved. The waist always shows, locked: a composed pose takes
    // it from its base, and an arm pose doesn't keep it.
    const { label, groups } = POSE_TYPES[this.kind()];
    for (const card of this.cards) {
      const saved = groups.includes(card.dataset.group);
      const waist = card.dataset.group === "waist";
      card.dataset.collapsed = String(!saved && !waist);
      card.dataset.unsaved = String(waist);
      card.querySelector("[data-collapsed-note]").textContent = `Not part of a ${label} pose`;
      card.querySelector("[data-unsaved-note]").textContent = "Shown only";
    }
  }

  // A pose type (left_arm, right_arm, composed) or one card (waist, left_arm, right_arm).
  groupJoints(group) {
    const groups = POSE_TYPES[group]?.groups || [group];
    return this.rows.filter((row) => groups.includes(row.closest("[data-group]").dataset.group));
  }

  setJoint(joint, radians) {
    this.values[joint] = radians;
    this.showJoint(joint, radians);
    robotLink.sendJoints({ [joint]: radians });
  }

  showState(positions) {
    for (const row of this.rows) {
      const joint = row.dataset.joint;
      if (joint === this.held) continue;
      this.values[joint] = positions[joint];
      this.showJoint(joint, positions[joint]);
    }
  }

  showJoint(joint, radians) {
    const row = this.rows.find((candidate) => candidate.dataset.joint === joint);
    const degrees = (radians * DEGREES_PER_RADIAN).toFixed(1);
    if (joint !== this.held) row.querySelector("[data-slider]").value = degrees;
    row.querySelector("[data-number]").value = degrees;
    // Already at concierge_init: nothing to reset. (The waist has no reset: it is set by the base pose.)
    const reset = row.querySelector("[data-joint-reset]");
    if (reset) reset.disabled = Math.abs(radians - Number(row.dataset.home)) < 1e-4;
  }

  reset(group) {
    const home = Object.fromEntries(this.groupJoints(group).map((row) => [row.dataset.joint, Number(row.dataset.home)]));
    Object.assign(this.values, home);
    robotLink.sendJoints(home);
  }

  startNew() {
    // Back to the home pose with nothing opened and no name.
    this.reset("composed");
    this.openSelect.value = "";
    this.nameInput.value = "";
    this.nameInput.focus();
  }

  async mirror(button) {
    const source = button.dataset.mirror;
    const joints = Object.fromEntries(this.groupJoints(source).map((row) => [row.dataset.joint, this.values[row.dataset.joint]]));
    const result = await run(button, () => api("POST", "/api/poses/mirror", { source, joint_positions: joints }));
    if (result) toast(`Copied to the ${source === "left_arm" ? "right" : "left"} arm (mirrored)`, "info");
  }

  async open() {
    if (!this.openSelect.value) return;
    const [type, name] = this.openSelect.value.split("/");
    const result = await run(null, () => api("POST", `/api/poses/${type}/${encodeURIComponent(name)}/show`));
    if (!result) return;
    this.nameInput.value = name;
    this.setKind(type === "base" ? "composed" : type);
  }

  async save() {
    const kind = this.kind();
    const name = this.nameInput.value.trim();
    if (!name) {
      toast("Enter a pose name first", "error");
      this.nameInput.focus();
      return;
    }
    const joints = Object.fromEntries(this.groupJoints(kind).map((row) => [row.dataset.joint, this.values[row.dataset.joint]]));
    const result = await run(this.saveButton, () => saveOrReplace(name, (overwrite) =>
      api("POST", "/api/poses", { pose_type: kind, name, joint_positions: joints, overwrite })));
    if (result) {
      toast(`Saved ${result.name} (${POSE_TYPES[kind].label} pose)`);
      await this.refresh();
      this.openSelect.value = `${kind}/${result.name}`;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => new RecordTab().start());
