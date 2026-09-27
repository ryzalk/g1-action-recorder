/* Speech · BytePlus and Speech · MiniMax: a script editor with toned parts, pauses and sound tags, generated into one WAV. */

// Strong / soft colour per BytePlus subcategory (in the order presets list them) and per MiniMax emotion.
const TONE_PALETTE = [["#2563EB", "#DBEAFE"], ["#0D9488", "#CCFBF1"], ["#D97706", "#FEF3C7"], ["#7C3AED", "#EDE9FE"],
  ["#DB2777", "#FCE7F3"], ["#059669", "#D1FAE5"], ["#DC2626", "#FEE2E2"], ["#4F46E5", "#E0E7FF"], ["#CA8A04", "#FEF9C3"],
  ["#0891B2", "#CFFAFE"], ["#9333EA", "#F3E8FF"], ["#EA580C", "#FFEDD5"]];
const EMOTION_COLORS = { neutral: "#9AA0A6", happy: "#E0A800", sad: "#5A7FBF", angry: "#C84C4C", fearful: "#7A6C9D",
  disgusted: "#6E8B5E", surprised: "#F2994A", fluent: "#3FA3AF" };
const PAUSE_ICON = '<svg class="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>';
const PROVIDER_NAMES = { byteplus: "BytePlus", minimax: "MiniMax" };
const PLAY_ICON = '<svg class="size-3.5" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l12.5-7.5z"/></svg>';
const STOP_ICON = '<svg class="size-3.5" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12"/></svg>';

let speechOptions = null;
let speechPages = {};

function colorFor(group) {
  if (EMOTION_COLORS[group]) return [EMOTION_COLORS[group], `${EMOTION_COLORS[group]}29`];
  const groups = [...new Set(speechOptions.voice_direction.presets.map((preset) => preset.subcategory))];
  const index = groups.indexOf(group);
  return index < 0 ? ["#6B7280", "#F3F4F6"] : TONE_PALETTE[index % TONE_PALETTE.length];
}

class SpeechPage {
  constructor(root) {
    this.root = root;
    this.provider = root.dataset.provider;
    this.find = (selector) => root.querySelector(selector);
    this.editor = this.find("[data-editor]");
    this.card = this.find("[data-script-card]");
    this.panel = this.find("[data-tone-panel]");
    this.range = null;          // the last selection inside the editor
    this.target = null;         // what the tone panel edits: {span} or {range}
    this.draft = null;          // the tone being edited
    this.planTimer = null;
    this.promptTimer = null;
    this.loaded = false;
  }

  start() {
    document.addEventListener("selectionchange", () => this.trackSelection());
    this.editor.addEventListener("input", () => this.changed());
    this.editor.addEventListener("paste", (event) => {
      // Plain text only: formatting from elsewhere must not look like a tone.
      event.preventDefault();
      document.execCommand("insertText", false, event.clipboardData.getData("text/plain"));
    });
    this.editor.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        document.execCommand("insertLineBreak");
      }
    });
    this.editor.addEventListener("click", (event) => {
      const span = event.target.closest("[data-tone]");
      if (span && window.getSelection().isCollapsed) this.openTone({ span });
    });
    this.find("[data-tone-button]").addEventListener("click", () => {
      if (this.range && !this.range.collapsed) this.openTone({ range: this.range.cloneRange() });
    });
    for (const button of this.root.querySelectorAll("[data-menu-button]")) {
      button.addEventListener("click", () => this.toggleMenu(button));
    }
    for (const button of this.root.querySelectorAll("[data-pause-choice]")) {
      button.addEventListener("click", () => this.insertChip({ type: "pause", seconds: Number(button.dataset.pauseChoice) }));
    }
    this.find("[data-pause-insert]").addEventListener("click", () => {
      const seconds = Number(this.find("[data-pause-custom]").value);
      if (!(seconds > 0 && seconds <= speechOptions.max_pause_seconds)) {
        toast(`A pause is 0.01 to ${speechOptions.max_pause_seconds} seconds`, "error");
        return;
      }
      this.insertChip({ type: "pause", seconds });
    });
    this.find("[data-tone-close]").addEventListener("click", () => this.closeTone());
    this.find("[data-tone-cancel]").addEventListener("click", () => this.closeTone());
    this.find("[data-tone-apply]").addEventListener("click", () => this.applyTone());
    this.find("[data-tone-remove]").addEventListener("click", () => this.removeTone());
    for (const tab of this.root.querySelectorAll("[data-side-tab]")) tab.addEventListener("click", () => this.showSide(tab.dataset.sideTab));
    for (const input of this.root.querySelectorAll("[data-setting]")) {
      input.addEventListener("input", () => {
        const number = this.find(`[data-setting-number="${input.dataset.setting}"]`);
        if (number) number.value = input.value;
        if (input.dataset.setting === "model") this.changed();
      });
    }
    for (const number of this.root.querySelectorAll("[data-setting-number]")) {
      number.addEventListener("change", () => {
        const slider = this.find(`[data-setting="${number.dataset.settingNumber}"]`);
        slider.value = Math.min(Number(slider.max), Math.max(Number(slider.min), Number(number.value) || 0));
        number.value = slider.value;
      });
    }
    this.bindVoicePanel();
    this.find("[data-generate]").addEventListener("click", (event) => this.generate(event.currentTarget));
    document.addEventListener("pointerdown", (event) => {
      // A click elsewhere closes an open menu, as a dropdown would.
      for (const menu of this.root.querySelectorAll("[data-menu]:not(.hidden)")) {
        const button = this.find(`[data-menu-button="${menu.dataset.menu}"]`);
        if (!menu.contains(event.target) && !button.contains(event.target)) this.hideMenu(menu);
      }
    });
    onTabShown(`speech-${this.provider}`, () => refreshSpeech());
  }

  // ---- loading and settings ----
  setup() {
    const options = speechOptions[this.provider];
    this.setVoice(options.default_voice);
    if (this.provider === "minimax") {
      fillSelect(this.find('[data-setting="model"]'), [{ options: options.models.map((model) => ({ value: model.id, text: model.label ? `${model.id} · ${model.label}` : model.id })) }], null);
      this.find('[data-setting="model"]').value = options.default_model;
      fillSelect(this.find('[data-setting="language"]'), [{ options: options.languages.map((language) => ({ value: language.id, text: language.label })) }], null);
      const tags = this.find("[data-sound-tags]");
      tags.replaceChildren(...options.sound_tags.map((tag) => {
        const button = Object.assign(document.createElement("button"), { type: "button", textContent: tag });
        button.className = "rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 hover:border-violet-300 hover:bg-violet-50 hover:text-violet-700";
        button.addEventListener("click", () => this.insertChip({ type: "sound", tag }));
        return button;
      }));
      this.buildEmotions();
    } else {
      this.buildPresetPicker();
    }
    this.showSide("settings");
    this.loaded = true;
  }

  show(clips) {
    if (!this.loaded) this.setup();
    const configured = speechOptions[this.provider].configured;
    const banner = this.find("[data-not-configured]");
    banner.classList.toggle("hidden", configured);
    banner.classList.toggle("flex", !configured);
    this.find("[data-generate]").disabled = !configured;
    this.renderClips(clips);
    this.changed();
  }

  settings() {
    const settings = {};
    for (const input of this.root.querySelectorAll("[data-setting]")) {
      const key = input.dataset.setting;
      settings[key] = input.type === "checkbox" ? input.checked : input.tagName === "SELECT" ? input.value : Number(input.value);
    }
    return settings;
  }

  voice() {
    return this.chosenVoice?.id || "";
  }

  // ---- voices: the card in Settings and the panel with every voice ----
  bindVoicePanel() {
    this.voiceList = null;
    this.voiceFilter = { language: "", gender: "", scenario: "" };
    const dialog = this.find("[data-voice-dialog]");
    this.find("[data-voice-open]").addEventListener("click", () => this.openVoices());
    this.find("[data-voice-play]").addEventListener("click", (event) => this.playSample(this.chosenVoice, event.currentTarget));
    for (const selector of ["[data-voice-close]", "[data-voice-done]"]) this.find(selector).addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => this.stopSample());
    this.find("[data-voice-search]").addEventListener("input", () => this.renderVoices());
    for (const button of this.root.querySelectorAll("[data-voice-gender]")) {
      button.addEventListener("click", () => {
        this.voiceFilter.gender = button.dataset.voiceGender;
        this.renderVoices();
      });
    }
    this.find("[data-voice-scenario]")?.addEventListener("change", (event) => {
      this.voiceFilter.scenario = event.target.value;
      this.renderVoices();
    });
    this.find("[data-voice-manual-use]").addEventListener("click", () => {
      const id = this.find("[data-voice-manual]").value.trim();
      if (!id) {
        toast("Type the Voice ID first", "error");
        return;
      }
      const known = this.voiceList?.voices.find((voice) => voice.id === id);
      this.setVoice(known || { id, name: id, language: "", gender: "", description: "Voice ID typed in", sample_url: null });
      dialog.close();
    });
    this.find("[data-voice-audio]").addEventListener("ended", () => this.stopSample());
  }

  setVoice(voice) {
    this.chosenVoice = voice;
    const initials = voice.name.split(/[\s_()-]+/).filter(Boolean).slice(0, 2).map((word) => word[0].toUpperCase()).join("");
    this.find("[data-voice-avatar]").textContent = initials || "?";
    this.find("[data-voice-name]").textContent = voice.name;
    const meta = [voice.language ? `Speaks ${voice.language}` : "", voice.gender, voice.id !== voice.name ? voice.id : ""];
    this.find("[data-voice-meta]").textContent = meta.filter(Boolean).join(" · ");
    this.find("[data-voice-play]").disabled = !voice.sample_url;
    if (this.voiceList) this.renderVoices();
  }

  async openVoices() {
    const dialog = this.find("[data-voice-dialog]");
    dialog.showModal();
    if (!this.voiceList) {
      this.find("[data-voice-list]").innerHTML = '<p class="col-span-2 py-10 text-center text-sm text-gray-400">Loading voices…</p>';
      this.voiceList = await run(null, () => api("GET", `/api/speech/voices/${this.provider}`));
      if (!this.voiceList) return;
      this.find("[data-voice-source]").textContent = `List: ${this.voiceList.source}.`;
      const scenarios = [...new Set(this.voiceList.voices.map((voice) => voice.scenario).filter(Boolean))];
      const select = this.find("[data-voice-scenario]");
      if (select) fillSelect(select, [{ options: scenarios.map((name) => ({ value: name, text: name })) }], "All scenarios");
    }
    this.renderVoices();
    // The chosen voice in view, so the list opens where the user left it.
    this.find("[data-voice-list] [data-selected=true]")?.scrollIntoView({ block: "center" });
  }

  renderVoices() {
    const list = this.voiceList;
    if (!list) return;
    const filter = this.voiceFilter;
    const query = this.find("[data-voice-search]").value.trim().toLowerCase();
    const languages = this.find("[data-voice-languages]");
    languages.replaceChildren(...[["", list.voices.length], ...list.languages].map(([language, count]) => {
      const chip = Object.assign(document.createElement("button"), { type: "button" });
      chip.dataset.voiceLanguage = language;
      chip.className = `rounded-full border px-2.5 py-0.5 text-xs font-medium ${language === filter.language ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"}`;
      chip.textContent = `${language || "All languages"} ${count}`;
      chip.addEventListener("click", () => {
        filter.language = language;
        this.renderVoices();
      });
      return chip;
    }));
    for (const button of this.root.querySelectorAll("[data-voice-gender]")) button.dataset.active = String(button.dataset.voiceGender === filter.gender);
    const shown = list.voices.filter((voice) => (!filter.language || voice.language === filter.language)
      && (!filter.gender || voice.gender === filter.gender) && (!filter.scenario || voice.scenario === filter.scenario)
      && (!query || `${voice.name} ${voice.id} ${voice.description} ${voice.language}`.toLowerCase().includes(query)));
    this.find("[data-voice-count]").textContent = `${shown.length} of ${list.voices.length}`;
    const grid = this.find("[data-voice-list]");
    if (shown.length === 0) {
      grid.innerHTML = '<p class="col-span-2 py-10 text-center text-sm text-gray-400">No voice matches</p>';
      return;
    }
    grid.replaceChildren(...shown.map((voice) => this.voiceRow(voice)));
  }

  voiceRow(voice) {
    const chosen = voice.id === this.chosenVoice?.id;
    const row = document.createElement("div");
    row.dataset.selected = String(chosen);
    row.dataset.voiceId = voice.id;
    row.className = `flex cursor-pointer gap-x-3 rounded-[10px] border bg-white p-3 hover:border-blue-300 ${chosen ? "border-blue-600 ring-1 ring-blue-600" : "border-gray-200"}`;
    const play = Object.assign(document.createElement("button"), { type: "button" });
    play.dataset.samplePlay = "";
    play.className = "flex size-9 shrink-0 items-center justify-center rounded-full border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40";
    play.title = "Hear this voice";
    play.setAttribute("aria-label", `Hear ${voice.name}`);
    play.innerHTML = PLAY_ICON;
    play.disabled = !voice.sample_url;
    play.addEventListener("click", (event) => {
      event.stopPropagation();
      this.playSample(voice, play);
    });
    const text = document.createElement("div");
    text.className = "min-w-0 flex-1";
    const head = document.createElement("div");
    head.className = "flex flex-wrap items-center gap-1.5";
    head.append(Object.assign(document.createElement("span"), { className: "text-sm font-semibold text-gray-900", textContent: voice.name }));
    const badge = (label, colors) => Object.assign(document.createElement("span"), { className: `rounded-md px-1.5 py-0.5 text-[11px] font-medium ${colors}`, textContent: label });
    head.append(badge(`Speaks ${voice.language}`, "bg-blue-50 text-blue-700"));
    if (voice.gender) head.append(badge(voice.gender, voice.gender === "Female" ? "bg-pink-50 text-pink-700" : "bg-sky-50 text-sky-700"));
    if (voice.scenario) head.append(badge(voice.scenario, "bg-gray-100 text-gray-600"));
    if (voice.group === "My voices") head.append(badge("My voice", "bg-violet-50 text-violet-700"));
    if (chosen) head.append(badge("✓ Chosen", "bg-blue-600 text-white"));
    text.append(head,
      Object.assign(document.createElement("p"), { className: "mt-1 line-clamp-2 text-xs text-gray-600", textContent: voice.description }),
      Object.assign(document.createElement("p"), { className: "mt-0.5 truncate font-mono text-[11px] text-gray-400", textContent: voice.id }));
    row.append(play, text);
    row.addEventListener("click", () => this.setVoice(voice));
    row.addEventListener("dblclick", () => this.find("[data-voice-dialog]").close());
    return row;
  }

  async playSample(voice, button) {
    const audio = this.find("[data-voice-audio]");
    if (this.playing === voice.id) {
      this.stopSample();
      return;
    }
    this.stopSample();
    this.playing = voice.id;
    this.playingButton = button;
    button.innerHTML = '<span class="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"></span>';
    try {
      // Samples are files made ahead of time; fetch first so a missing one can say why.
      const response = await fetch(voice.sample_url);
      if (!response.ok) throw new Error(detailText((await response.json().catch(() => ({}))).detail) || `No sample (${response.status})`);
      const source = URL.createObjectURL(await response.blob());
      if (this.playing !== voice.id) return;
      audio.src = source;
      await audio.play();
      button.innerHTML = STOP_ICON;
    } catch (error) {
      toast(error.message, "error");
      this.stopSample();
    }
  }

  stopSample() {
    this.find("[data-voice-audio]").pause();
    if (this.playingButton) this.playingButton.innerHTML = PLAY_ICON;
    this.playing = null;
    this.playingButton = null;
  }

  showSide(tab) {
    for (const button of this.root.querySelectorAll("[data-side-tab]")) button.dataset.active = String(button.dataset.sideTab === tab);
    for (const pane of this.root.querySelectorAll("[data-side]")) pane.classList.toggle("hidden", pane.dataset.side !== tab);
  }

  // ---- the editor: DOM <-> parts ----
  parts(root = this.editor) {
    const parts = [];
    const pushText = (text, tone, pace) => {
      if (!text) return;
      const last = parts.at(-1);
      if (last && last.type === "text" && JSON.stringify([last.tone, last.pace]) === JSON.stringify([tone, pace])) last.text += text;
      else parts.push({ type: "text", text, tone, pace });
    };
    const walk = (node, tone, pace) => {
      for (const child of node.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) pushText(child.data, tone, pace);
        else if (child.dataset?.pause) parts.push({ type: "pause", seconds: Number(child.dataset.pause) });
        else if (child.dataset?.sound) parts.push({ type: "sound", tag: child.dataset.sound });
        else if (child.tagName === "BR") pushText("\n", tone, pace);
        else if (child.dataset?.tone) walk(child, JSON.parse(child.dataset.tone), child.dataset.pace ? Number(child.dataset.pace) : undefined);
        else {
          if ((child.tagName === "DIV" || child.tagName === "P") && parts.length) pushText("\n", tone, pace);
          walk(child, tone, pace);
        }
      }
    };
    walk(root, undefined, undefined);
    return parts.map((part) => Object.fromEntries(Object.entries(part).filter(([, value]) => value !== undefined)));
  }

  render(parts) {
    this.editor.replaceChildren(...parts.map((part) => this.node(part)));
  }

  node(part) {
    if (part.type === "pause") return this.chip("pause", part.seconds, `${PAUSE_ICON}${part.seconds}s`, "border-gray-300 bg-gray-100 text-gray-600");
    if (part.type === "sound") return this.chip("sound", part.tag, `(${part.tag})`, "border-violet-200 bg-violet-50 text-violet-700");
    if (!part.tone) return document.createTextNode(part.text);
    const span = document.createElement("span");
    span.dataset.tone = JSON.stringify(part.tone);
    if (part.pace) span.dataset.pace = String(part.pace);
    const { label, group } = this.describe(part.tone, part.pace);
    const [strong, soft] = colorFor(group);
    span.dataset.label = label;
    span.style.setProperty("--strong", strong);
    span.style.setProperty("--soft", soft);
    span.className = "box-decoration-clone cursor-pointer rounded-md bg-(--soft) py-1 pe-1 ps-0.5 before:me-1.5 before:rounded before:bg-(--strong) before:px-1.5 before:py-0.5 before:align-[1px] before:text-[11px] before:font-semibold before:text-white before:content-[attr(data-label)] data-[editing=true]:outline-2 data-[editing=true]:outline-blue-600";
    span.textContent = part.text;
    return span;
  }

  chip(kind, value, html, colors) {
    const chip = document.createElement("span");
    chip.contentEditable = "false";
    chip.dataset[kind] = String(value);
    chip.className = `mx-0.5 inline-flex select-none items-center gap-x-1 rounded-md border px-1.5 py-px align-[1px] text-xs font-medium ${colors}`;
    chip.innerHTML = html;
    return chip;
  }

  describe(tone, pace) {
    // The label and colour group a toned part shows; BytePlus says the preset name, or 自定义 once changed.
    if (this.provider === "minimax") {
      const label = tone.emotion[0].toUpperCase() + tone.emotion.slice(1) + (pace ? ` ${pace}×` : "");
      return { label, group: tone.emotion };
    }
    const preset = speechOptions.voice_direction.presets.find((candidate) => candidate.id === tone.preset_id);
    const same = preset && Object.keys(preset.style).every((key) => JSON.stringify(preset.style[key]) === JSON.stringify(tone.style?.[key] ?? preset.style[key]));
    return { label: preset && same ? preset.name : "自定义", group: preset ? preset.subcategory : "custom" };
  }

  trackSelection() {
    const selection = window.getSelection();
    if (!selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!this.editor.contains(range.commonAncestorContainer)) return;
    this.range = range.cloneRange();
    const hasText = !range.collapsed && range.toString().trim() !== "";
    const button = this.find("[data-tone-button]");
    button.disabled = !hasText;
    button.title = hasText ? "" : "Select text first";
  }

  changed() {
    const parts = this.parts();
    const characters = parts.filter((part) => part.type === "text").reduce((sum, part) => sum + part.text.length, 0);
    this.find("[data-count]").textContent = `${characters.toLocaleString()} / ${speechOptions.max_characters.toLocaleString()} characters`;
    clearTimeout(this.planTimer);
    this.planTimer = setTimeout(() => this.plan(parts), 400);
  }

  async plan(parts) {
    // A dry run: how many requests Generate would send, or why it can't.
    const summary = this.find("[data-summary-text]");
    const texts = parts.filter((part) => part.type === "text" && part.text.trim());
    if (texts.length === 0) {
      summary.textContent = "Nothing to generate yet.";
      summary.parentElement.classList.remove("text-amber-700");
      return;
    }
    try {
      const { requests } = await api("POST", "/api/speech/plan", { provider: this.provider, parts, model: this.settings().model });
      const speech = requests.filter((request) => request.kind === "speech").length;
      const pauses = parts.filter((part) => part.type === "pause").length;
      const tags = parts.filter((part) => part.type === "sound").length;
      const bits = [`${texts.length} part${texts.length === 1 ? "" : "s"}`, `${pauses} pause${pauses === 1 ? "" : "s"}`];
      if (tags) bits.push(`${tags} sound tag${tags === 1 ? "" : "s"}`);
      summary.textContent = `${bits.join(" · ")} → ${speech} request${speech === 1 ? "" : "s"} to ${PROVIDER_NAMES[this.provider]}, joined into one WAV`;
      summary.parentElement.classList.remove("text-amber-700");
    } catch (error) {
      summary.textContent = error.message;
      summary.parentElement.classList.add("text-amber-700");
    }
  }

  insertChip(part) {
    // At the cursor (or after the selection); without one, at the end.
    const chip = this.node(part);
    let range = this.range && this.editor.contains(this.range.commonAncestorContainer) ? this.range.cloneRange() : null;
    if (!range) {
      range = document.createRange();
      range.selectNodeContents(this.editor);
    }
    range.collapse(false);
    // Inside a toned part the chip splits it; it must not sit inside the span.
    const span = range.startContainer.parentElement?.closest("[data-tone]");
    if (span && this.editor.contains(span)) {
      const after = document.createRange();
      after.setStart(range.startContainer, range.startOffset);
      after.setEndAfter(span.lastChild);
      const tail = after.extractContents();
      const copy = span.cloneNode(false);
      copy.append(...tail.childNodes);
      span.after(chip, copy);
      if (!copy.textContent) copy.remove();
    } else {
      range.insertNode(chip);
    }
    // The cursor goes right after the new chip, so the next pause or tag lands after it.
    const caret = document.createRange();
    caret.setStartAfter(chip);
    caret.collapse(true);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(caret);
    this.range = caret.cloneRange();
    for (const menu of this.root.querySelectorAll("[data-menu]")) this.hideMenu(menu);
    this.changed();
  }

  toggleMenu(button) {
    const menu = this.find(`[data-menu="${button.dataset.menuButton}"]`);
    const opening = menu.classList.contains("hidden");
    for (const other of this.root.querySelectorAll("[data-menu]")) this.hideMenu(other);
    if (!opening) return;
    const cardBox = this.card.getBoundingClientRect();
    const box = button.getBoundingClientRect();
    menu.style.left = `${Math.min(box.left - cardBox.left, cardBox.width - menu.offsetWidth - 12)}px`;
    menu.style.top = `${box.bottom - cardBox.top + 6}px`;
    menu.classList.remove("hidden");
    menu.style.left = `${Math.max(12, Math.min(box.left - cardBox.left, cardBox.width - menu.offsetWidth - 12))}px`;
    button.dataset.open = "true";
  }

  hideMenu(menu) {
    menu.classList.add("hidden");
    this.find(`[data-menu-button="${menu.dataset.menu}"]`).dataset.open = "false";
  }

  // ---- the tone panel ----
  openTone(target) {
    this.closeTone();
    this.target = target;
    let text;
    if (target.span) {
      target.span.dataset.editing = "true";
      text = target.span.textContent;
      this.draft = { tone: JSON.parse(target.span.dataset.tone), pace: target.span.dataset.pace ? Number(target.span.dataset.pace) : null };
    } else {
      if (target.range.cloneContents().querySelector("[data-pause],[data-sound]")) {
        toast("Select text only; pauses and sound tags keep their own place", "warning");
        return;
      }
      text = target.range.toString();
      const vd = speechOptions.voice_direction;
      this.draft = this.provider === "byteplus"
        ? { tone: { preset_id: vd.default_preset_id, style: { ...vd.presets.find((preset) => preset.id === vd.default_preset_id).style } }, pace: null }
        : { tone: { emotion: "neutral" }, pace: null };
    }
    this.find("[data-quote]").textContent = `“${text.trim()}”`;
    this.find("[data-tone-remove]").classList.toggle("invisible", !target.span);
    this.find("[data-tone-apply]").textContent = target.span ? "Apply" : "Apply to selection";
    if (this.provider === "byteplus") this.showDirection(true);
    else this.showEmotion();
    const cardBox = this.card.getBoundingClientRect();
    const box = (target.span || target.range).getBoundingClientRect();
    this.anchor = { left: box.left - cardBox.left, bottom: box.bottom - cardBox.top };
    this.panel.classList.replace("hidden", "flex");
    this.find("[data-tone-button]").dataset.open = "true";
    this.placePanel();
  }

  placePanel() {
    // Under the text it is about, kept inside the card; when it grows (Advanced), it moves up, then scrolls.
    if (this.panel.classList.contains("hidden")) return;
    const height = this.card.clientHeight;
    this.panel.style.maxHeight = "";
    const left = Math.max(12, Math.min(this.anchor.left, this.card.clientWidth - this.panel.offsetWidth - 12));
    let top = this.anchor.bottom + 8;
    if (top + this.panel.scrollHeight > height - 8) top = Math.max(8, height - this.panel.scrollHeight - 8);
    this.panel.style.left = `${left}px`;
    this.panel.style.top = `${top}px`;
    this.panel.style.maxHeight = `${height - top - 8}px`;
  }

  closeTone() {
    this.panel.classList.replace("flex", "hidden");
    this.find("[data-tone-button]").dataset.open = "false";
    for (const span of this.editor.querySelectorAll("[data-editing]")) delete span.dataset.editing;
    this.target = null;
  }

  applyTone() {
    const { tone, pace } = this.draft;
    if (this.target.span) {
      this.target.span.dataset.tone = JSON.stringify(tone);
      if (pace) this.target.span.dataset.pace = String(pace);
      else delete this.target.span.dataset.pace;
    } else {
      const range = this.target.range;
      const span = document.createElement("span");
      span.dataset.tone = JSON.stringify(tone);
      if (pace) span.dataset.pace = String(pace);
      span.textContent = range.toString();
      range.deleteContents();
      range.insertNode(span);
    }
    this.closeTone();
    // Rebuilt from the parts: a tone set inside another splits it, neighbours with the same tone join.
    this.render(this.parts());
    this.changed();
  }

  removeTone() {
    if (this.target?.span) this.target.span.replaceWith(document.createTextNode(this.target.span.textContent));
    this.closeTone();
    this.render(this.parts());
    this.changed();
  }

  // MiniMax: eight emotions and a pace for this part.
  buildEmotions() {
    const grid = this.find("[data-emotions]");
    grid.replaceChildren(...speechOptions.minimax.emotions.map((emotion) => {
      const button = Object.assign(document.createElement("button"), { type: "button" });
      button.dataset.emotion = emotion;
      button.className = "flex items-center gap-x-2 rounded-lg border border-gray-200 px-2.5 py-2 text-[13px] font-medium text-gray-800 hover:bg-gray-50 data-[active=true]:border-blue-600 data-[active=true]:bg-blue-50 data-[active=true]:ring-1 data-[active=true]:ring-blue-600";
      button.innerHTML = `<span class="size-2.5 rounded-full" style="background:${EMOTION_COLORS[emotion]}"></span>`;
      button.append(emotion[0].toUpperCase() + emotion.slice(1));
      button.addEventListener("click", () => {
        this.draft.tone = { emotion };
        this.showEmotion();
      });
      return button;
    }));
    const paceOn = this.find("[data-pace-on]");
    const pace = this.find("[data-pace]");
    paceOn.addEventListener("change", () => {
      this.draft.pace = paceOn.checked ? Number(pace.value) : null;
      this.showEmotion();
    });
    pace.addEventListener("input", () => {
      this.draft.pace = Number(pace.value);
      this.showEmotion();
    });
  }

  showEmotion() {
    for (const button of this.root.querySelectorAll("[data-emotion]")) button.dataset.active = String(button.dataset.emotion === this.draft.tone.emotion);
    const on = this.draft.pace !== null;
    this.find("[data-pace-on]").checked = on;
    this.find("[data-pace]").disabled = !on;
    if (on) this.find("[data-pace]").value = this.draft.pace;
    this.find("[data-pace-value]").textContent = on ? `${this.draft.pace.toFixed(2)}×` : "clip speed";
  }

  // BytePlus: category → subcategory → preset, the nine fields under Advanced, and the prompt it makes.
  buildPresetPicker() {
    const vd = speechOptions.voice_direction;
    const categories = [...new Set(vd.presets.map((preset) => preset.category))];
    fillSelect(this.find("[data-category]"), [{ options: categories.map((category) => ({ value: category, text: category })) }], null);
    this.find("[data-preset-count]").textContent = vd.presets.length;
    this.find("[data-category]").addEventListener("change", (event) => {
      this.subcategory = vd.presets.find((preset) => preset.category === event.target.value).subcategory;
      this.find("[data-preset-search]").value = "";
      this.showPresets();
    });
    this.find("[data-preset-search]").addEventListener("input", () => this.showPresets());
    this.find("[data-advanced]").addEventListener("toggle", () => this.placePanel());
    const fields = this.find("[data-fields]");
    const titles = { emotion: "Emotion", intensity: "Intensity", social_tone: "Social tone", communicative_intent: "Intent",
      mental_state: "Mental state · up to 2", voice_texture: "Voice texture · up to 2", pace: "Pace", pitch: "Pitch", energy: "Energy" };
    fields.replaceChildren(...Object.entries(titles).map(([field, title]) => {
      const wrap = document.createElement("div");
      const multi = vd.multi_fields.includes(field);
      if (multi) wrap.className = "col-span-2";
      wrap.append(Object.assign(document.createElement("p"), { className: "mb-1.5 text-xs font-medium text-gray-600", textContent: title }));
      if (multi) {
        const chips = document.createElement("div");
        chips.className = "flex flex-wrap gap-1";
        for (const { value, label } of vd.fields[field]) {
          const chip = Object.assign(document.createElement("button"), { type: "button", textContent: label });
          chip.dataset.field = field;
          chip.dataset.value = value;
          chip.className = "rounded-full border border-gray-200 px-2.5 py-0.5 text-xs font-medium text-gray-600 hover:bg-gray-50 data-[active=true]:border-blue-600 data-[active=true]:bg-blue-50 data-[active=true]:text-blue-700";
          chip.addEventListener("click", () => this.toggleValue(field, value));
          chips.append(chip);
        }
        wrap.append(chips);
      } else {
        const select = document.createElement("select");
        select.dataset.field = field;
        select.className = "block w-full rounded-lg border border-gray-200 px-2.5 py-1.5 text-[13px] text-gray-800 focus:border-blue-500 focus:outline-hidden";
        for (const { value, label } of vd.fields[field]) select.append(new Option(label, value));
        select.addEventListener("change", () => {
          this.draft.tone.style[field] = select.value;
          this.showDirection(false);
        });
        wrap.append(select);
      }
      return wrap;
    }));
  }

  toggleValue(field, value) {
    const values = [...(this.draft.tone.style[field] || [])];
    const index = values.indexOf(value);
    if (index >= 0) values.splice(index, 1);
    else if (values.length >= 2) {
      toast("Two at most; take one off first", "warning");
      return;
    } else values.push(value);
    this.draft.tone.style[field] = values;
    this.showDirection(false);
  }

  choosePreset(preset) {
    this.draft.tone = { preset_id: preset.id, style: JSON.parse(JSON.stringify(preset.style)) };
    this.subcategory = preset.subcategory;
    this.showDirection(true);
  }

  showDirection(syncPicker) {
    const vd = speechOptions.voice_direction;
    const preset = vd.presets.find((candidate) => candidate.id === this.draft.tone.preset_id);
    if (syncPicker && preset) {
      this.find("[data-category]").value = preset.category;
      this.subcategory = preset.subcategory;
      this.find("[data-preset-search]").value = "";
    }
    this.showPresets();
    for (const control of this.root.querySelectorAll("[data-fields] [data-field]")) {
      const current = this.draft.tone.style[control.dataset.field];
      if (control.tagName === "SELECT") control.value = current;
      else control.dataset.active = String((current || []).includes(control.dataset.value));
    }
    requestAnimationFrame(() => this.placePanel());
    const custom = this.describe(this.draft.tone).label === "自定义";
    this.find("[data-custom]").classList.toggle("hidden", !custom);
    clearTimeout(this.promptTimer);
    this.promptTimer = setTimeout(async () => {
      const result = await run(null, () => api("POST", "/api/speech/direction", this.draft.tone));
      if (result) this.find("[data-prompt]").textContent = result.prompt;
    }, 150);
  }

  showPresets() {
    const vd = speechOptions.voice_direction;
    const category = this.find("[data-category]").value;
    const query = this.find("[data-preset-search]").value.trim();
    const subcategories = [...new Set(vd.presets.filter((preset) => preset.category === category).map((preset) => preset.subcategory))];
    if (!subcategories.includes(this.subcategory)) this.subcategory = subcategories[0];
    const subs = this.find("[data-subcategories]");
    subs.hidden = query !== "";
    subs.replaceChildren(...subcategories.map((name) => {
      const chip = Object.assign(document.createElement("button"), { type: "button", textContent: name });
      chip.className = `rounded-full border px-2.5 py-0.5 text-xs font-medium ${name === this.subcategory ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`;
      chip.addEventListener("click", () => {
        this.subcategory = name;
        this.showPresets();
      });
      return chip;
    }));
    const shown = query
      ? vd.presets.filter((preset) => `${preset.name} ${preset.category} ${preset.subcategory} ${preset.scene_prompt}`.includes(query))
      : vd.presets.filter((preset) => preset.category === category && preset.subcategory === this.subcategory);
    const grid = this.find("[data-presets]");
    if (shown.length === 0) {
      grid.innerHTML = '<p class="col-span-2 py-2 text-center text-xs text-gray-400">No preset matches</p>';
      return;
    }
    grid.replaceChildren(...shown.map((preset) => {
      const card = Object.assign(document.createElement("button"), { type: "button" });
      const active = preset.id === this.draft.tone.preset_id;
      card.className = `rounded-[10px] border px-2.5 py-2 text-start hover:bg-gray-50 ${active ? "border-blue-600 bg-blue-50 ring-1 ring-blue-600" : "border-gray-200"}`;
      const title = document.createElement("span");
      title.className = "flex items-center gap-x-1.5 text-[13px] font-semibold text-gray-900";
      title.innerHTML = `<span class="size-2 rounded-full" style="background:${colorFor(preset.subcategory)[0]}"></span>`;
      title.append(preset.name);
      const line = Object.assign(document.createElement("span"), {
        className: "mt-0.5 line-clamp-2 block text-xs text-gray-500",
        textContent: query ? `${preset.category} · ${preset.subcategory}` : (preset.scene_prompt || "Tone only, no scene line"),
      });
      card.append(title, line);
      card.addEventListener("click", () => this.choosePreset(preset));
      return card;
    }));
  }

  // ---- generate and clips ----
  async generate(button) {
    const name = this.find("[data-name]").value.trim();
    const parts = this.parts();
    if (!parts.some((part) => part.type === "text" && part.text.trim())) {
      toast("Type what the robot should say first", "error");
      return;
    }
    if (!name) {
      toast("Enter a clip name first", "error");
      this.find("[data-name]").focus();
      return;
    }
    const voice = this.voice();
    if (!voice) {
      toast("Enter the Voice ID", "error");
      return;
    }
    const request = { name, provider: this.provider, voice, parts, ...this.settings() };
    const clip = await run(button, () => saveOrReplace(name, (overwrite) => api("POST", "/api/speech", { ...request, overwrite })));
    if (!clip) return;
    toast(`Generated ${clip.name} · ${clip.duration_seconds.toFixed(2)} s from ${clip.requests} request${clip.requests === 1 ? "" : "s"}`);
    await refreshSpeech();
    this.showSide("clips");
  }

  renderClips(clips) {
    this.find("[data-clip-count]").textContent = clips.length;
    const list = this.find("[data-clips]");
    if (clips.length === 0) {
      list.innerHTML = '<p class="px-4 py-10 text-center text-xs text-gray-400">No clips yet. Clips you generate appear here.</p>';
      return;
    }
    list.replaceChildren(...clips.map((clip) => this.clipRow(clip)));
  }

  clipRow(clip) {
    const url = `/api/speech/${encodeURIComponent(clip.name)}/audio?v=${encodeURIComponent(clip.created_at)}`;
    const row = document.createElement("div");
    row.className = "space-y-2 px-4 py-3";
    const header = document.createElement("div");
    header.className = "flex items-center gap-x-2";
    const title = Object.assign(document.createElement("span"), { className: "truncate text-sm font-semibold text-gray-900", textContent: clip.name });
    const badge = Object.assign(document.createElement("span"), { textContent: PROVIDER_NAMES[clip.provider] });
    badge.className = `rounded-md px-1.5 py-0.5 text-[11px] font-medium ${clip.provider === "minimax" ? "bg-violet-50 text-violet-700" : "bg-blue-50 text-blue-700"}`;
    const edit = Object.assign(document.createElement("button"), { type: "button", textContent: "Edit" });
    edit.className = "ms-auto rounded-md px-1.5 py-0.5 text-xs font-medium text-gray-600 hover:bg-gray-100";
    edit.title = "Load this script, voice and name into the editor";
    edit.addEventListener("click", () => speechPages[clip.provider].load(clip));
    const download = Object.assign(document.createElement("a"), { href: url, download: clip.wav_filename, textContent: "Download" });
    download.className = "rounded-md px-1.5 py-0.5 text-xs font-medium text-gray-600 hover:bg-gray-100";
    const remove = Object.assign(document.createElement("button"), { type: "button", textContent: "Delete" });
    remove.className = "rounded-md px-1.5 py-0.5 text-xs font-medium text-red-600 hover:bg-red-50";
    remove.addEventListener("click", () => this.remove(clip.name));
    header.append(title, badge, edit, download, remove);
    const meta = Object.assign(document.createElement("p"), { className: "text-xs text-gray-500" });
    meta.textContent = `${clip.duration_seconds.toFixed(2)} s · ${clip.voice_name}${clip.older ? " · older clip" : ` · ${clip.requests} request${clip.requests === 1 ? "" : "s"}`}`;
    const script = document.createElement("p");
    script.className = "line-clamp-3 text-[13px] leading-6 text-gray-700";
    for (const part of clip.script) {
      if (part.type === "pause") script.append(Object.assign(document.createElement("span"), { className: "mx-0.5 rounded bg-gray-100 px-1 text-[11px] text-gray-500", textContent: `${part.seconds}s` }));
      else if (part.type === "sound") script.append(Object.assign(document.createElement("span"), { className: "mx-0.5 rounded bg-violet-50 px-1 text-[11px] text-violet-700", textContent: `(${part.tag})` }));
      else if (part.group) {
        const span = Object.assign(document.createElement("span"), { className: "rounded px-0.5", textContent: part.text, title: part.label });
        span.style.background = colorFor(part.group)[1];
        script.append(span);
      } else script.append(part.text);
    }
    const audio = Object.assign(document.createElement("audio"), { controls: true, preload: "none", src: url });
    audio.className = "h-8 w-full";
    row.append(header, meta, script, audio);
    return row;
  }

  load(clip) {
    // Back into its own page's editor, with its voice and settings, so it can be changed and generated again.
    location.hash = `#speech-${this.provider}`;
    if (clip.older) {
      this.render([{ type: "text", text: clip.text }]);
    } else {
      this.render(clip.script.map(({ label, group, ...part }) => part));
    }
    this.setVoice(clip.voice_info);
    for (const [key, value] of Object.entries(clip.settings || {})) {
      const input = this.find(`[data-setting="${key}"]`);
      if (!input) continue;
      if (input.type === "checkbox") input.checked = value;
      else input.value = value;
      const number = this.find(`[data-setting-number="${key}"]`);
      if (number) number.value = value;
    }
    this.find("[data-name]").value = clip.name;
    this.showSide("settings");
    this.changed();
  }

  async remove(name) {
    const confirmed = await confirmDialog({ title: `Delete “${name}”?`, text: "Its WAV file is deleted too.", ok: "Delete", danger: true });
    if (!confirmed) return;
    if (await run(null, () => api("DELETE", `/api/speech/${encodeURIComponent(name)}`))) {
      toast(`Deleted ${name}`);
      refreshSpeech();
    }
  }
}

async function refreshSpeech() {
  const listing = await api("GET", "/api/speech");
  speechOptions = listing;
  for (const provider of ["byteplus", "minimax"]) {
    const dot = document.querySelector(`[data-provider-dot="${provider}"]`);
    const configured = listing[provider].configured;
    dot.className = `size-1.5 rounded-full ${configured ? "bg-green-500" : "bg-gray-300"}`;
    dot.title = configured ? "Set up" : "No API key";
  }
  for (const page of Object.values(speechPages)) page.show(listing.clips);
}

document.addEventListener("DOMContentLoaded", () => {
  for (const root of document.querySelectorAll("[data-page^='speech-']")) {
    const page = new SpeechPage(root);
    speechPages[page.provider] = page;
    page.start();
  }
  // The sidebar dots show which provider has a key on every page, not only on Speech.
  refreshSpeech().catch(() => {});
});
