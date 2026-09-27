/* Build action: an ordered list of base (and composed) poses with move and hold times, framed by the home pose. */

class ActionTab {
  constructor() {
    this.openSelect = document.getElementById("action-open");
    this.nameInput = document.getElementById("action-name");
    this.body = document.getElementById("action-steps");
    this.addSelect = document.getElementById("action-add-pose");
    this.sampleHz = document.getElementById("action-sample-hz");
    this.saved = document.getElementById("action-saved");
    this.steps = [];
    this.returnSeconds = 1.0;
    this.defaultMove = 1.0;
    this.home = "";
  }

  start() {
    document.getElementById("action-new").addEventListener("click", () => this.load({ name: "", steps: [], return_seconds: this.defaultMove }));
    document.getElementById("action-add").addEventListener("click", () => this.add());
    document.getElementById("action-preview").addEventListener("click", (event) => this.preview(event.currentTarget));
    document.getElementById("action-save").addEventListener("click", (event) => this.save(event.currentTarget));
    this.openSelect.addEventListener("change", () => this.open());
    onTabShown("action", () => this.refresh());
  }

  async refresh() {
    const listing = await api("GET", "/api/actions");
    this.home = listing.home;
    this.defaultMove = listing.default_move_seconds;
    if (!this.sampleHz.value) this.sampleHz.value = listing.sample_hz;
    fillSelect(this.openSelect, [{ options: listing.actions.map((name) => ({ value: name, text: name })) }], "Open a saved action…");
    const byType = (type) => listing.choices.filter((choice) => choice.pose_type === type)
      .map((choice) => ({ value: `${choice.pose_type}/${choice.pose_name}`, text: choice.pose_name }));
    fillSelect(this.addSelect, [{ label: "Base", options: byType("base") }, { label: "Composed", options: byType("composed") }],
      "Choose a pose to add…");
    this.render();
  }

  async open() {
    if (!this.openSelect.value) return;
    const editor = await run(null, () => api("GET", `/api/actions/${encodeURIComponent(this.openSelect.value)}`));
    if (editor) this.load(editor);
  }

  load(editor) {
    this.nameInput.value = editor.name;
    this.steps = editor.steps.map((step) => ({ ...step }));
    this.returnSeconds = editor.return_seconds;
    // An opened action is already saved: offer its export straight away.
    this.showSaved(editor.name && editor.has_npz ? editor.name : null);
    if (!editor.name) this.openSelect.value = "";
    this.render();
  }

  add() {
    if (!this.addSelect.value) {
      toast("Choose a pose to add first", "error");
      return;
    }
    const [type, name] = this.addSelect.value.split("/");
    this.steps.push({ pose_type: type, pose_name: name, move_seconds: this.defaultMove, hold_seconds: 0 });
    this.render();
    this.show(type, name);
  }

  show(type, name) {
    run(null, () => api("POST", `/api/poses/${type}/${encodeURIComponent(name)}/show`));
  }

  render() {
    const rows = [this.fixedRow(1, "Start", null)];
    this.steps.forEach((step, index) => rows.push(this.stepRow(step, index)));
    rows.push(this.fixedRow(this.steps.length + 2, "Return", this.returnSeconds));
    this.body.replaceChildren(...rows);
    document.getElementById("action-count").textContent = `${this.steps.length} pose${this.steps.length === 1 ? "" : "s"}`;
    const total = this.steps.reduce((sum, step) => sum + Number(step.move_seconds) + Number(step.hold_seconds), 0) + Number(this.returnSeconds);
    document.getElementById("action-total").textContent = total.toFixed(1);
  }

  fixedRow(number, label, moveSeconds) {
    const row = this.row(number);
    row.className = "text-gray-400";
    const pose = this.cell("", "py-2.5");
    pose.innerHTML = '<span class="inline-flex items-center gap-x-1.5"><svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></span>';
    pose.firstChild.append(`${label} · ${this.home}`);
    row.append(pose);
    const move = this.cell("", "py-1.5 pe-2");
    if (moveSeconds !== null) {
      move.append(this.secondsInput(moveSeconds, 0.1, (value) => { this.returnSeconds = value; }));
    }
    row.append(move, this.cell(""), this.cell(""));
    return row;
  }

  stepRow(step, index) {
    const row = this.row(index + 2);
    const pose = this.cell("", "py-1.5");
    const showButton = document.createElement("button");
    showButton.type = "button";
    showButton.className = "block max-w-full truncate text-start font-medium text-gray-800 hover:text-blue-600";
    showButton.textContent = step.pose_name;
    showButton.title = "Show this pose";
    showButton.addEventListener("click", () => this.show(step.pose_type, step.pose_name));
    pose.append(showButton);
    const move = this.cell("", "py-1.5 pe-2");
    move.append(this.secondsInput(step.move_seconds, 0.1, (value) => { step.move_seconds = value; }));
    const hold = this.cell("", "py-1.5 pe-2");
    hold.append(this.secondsInput(step.hold_seconds, 0, (value) => { step.hold_seconds = value; }));
    const tools = this.cell("", "py-1.5 pe-3");
    tools.className += " flex justify-end gap-x-0.5";
    tools.append(this.tool("↑", "Move up", index === 0, () => this.swap(index, index - 1)),
      this.tool("↓", "Move down", index === this.steps.length - 1, () => this.swap(index, index + 1)),
      this.tool("✕", "Remove", false, () => { this.steps.splice(index, 1); this.render(); }));
    row.append(pose, move, hold, tools);
    return row;
  }

  row(number) {
    const row = document.createElement("tr");
    row.append(this.cell(String(number), "py-2 ps-4 tabular-nums text-gray-500"));
    return row;
  }

  cell(text, className = "") {
    const cell = document.createElement("td");
    cell.className = className;
    cell.textContent = text;
    return cell;
  }

  secondsInput(value, minimum, onChange) {
    const input = document.createElement("input");
    input.type = "number";
    input.min = String(minimum);
    input.step = "0.1";
    input.value = String(value);
    input.className = "w-full rounded-lg border border-gray-200 px-2 py-1 text-end text-[13px] tabular-nums [appearance:textfield] focus:border-blue-500 focus:outline-hidden [&::-webkit-inner-spin-button]:appearance-none";
    input.addEventListener("change", () => {
      onChange(Math.max(minimum, Number(input.value) || minimum));
      this.render();
    });
    return input;
  }

  tool(symbol, label, disabled, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = symbol;
    button.title = label;
    button.setAttribute("aria-label", label);
    button.disabled = disabled;
    button.className = "size-6 rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-900 disabled:opacity-30";
    button.addEventListener("click", onClick);
    return button;
  }

  swap(from, to) {
    [this.steps[from], this.steps[to]] = [this.steps[to], this.steps[from]];
    this.render();
  }

  draft(overwrite = false) {
    return { name: this.nameInput.value.trim(), steps: this.steps, return_seconds: Number(this.returnSeconds),
      sample_hz: Number(this.sampleHz.value), overwrite };
  }

  async preview(button) {
    await run(button, () => api("POST", "/api/actions/preview", this.draft()));
  }

  showSaved(name) {
    // The export carries the definition, the trajectory and the poses: what the robot needs to play it.
    this.saved.classList.toggle("hidden", !name);
    this.saved.classList.toggle("flex", Boolean(name));
    if (!name) return;
    const link = this.saved.querySelector("a");
    link.href = `/api/library/actions/${encodeURIComponent(name)}/export`;
    link.download = `${name}.zip`;
  }

  async save(button) {
    const name = this.nameInput.value.trim();
    if (!name) {
      toast("Enter an action name first", "error");
      this.nameInput.focus();
      return;
    }
    const result = await run(button, () => saveOrReplace(name, (overwrite) => api("POST", "/api/actions", this.draft(overwrite))));
    if (!result) return;
    toast(`Saved ${result.name}: definition and trajectory · ${result.samples} frames, ${result.seconds.toFixed(1)} s`, "success",
      { href: result.export_url, text: "Export .zip" });
    this.showSaved(result.name);
    await this.refresh();
    this.openSelect.value = result.name;
  }
}

document.addEventListener("DOMContentLoaded", () => new ActionTab().start());
