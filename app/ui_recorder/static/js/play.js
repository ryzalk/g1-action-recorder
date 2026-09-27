/* Play action: a saved action or a motion file into the shared player, and saving an arm from a paused frame. */

class PlayTab {
  constructor() {
    this.savedSelect = document.getElementById("play-saved");
    this.fileInput = document.getElementById("play-file");
    this.drop = document.querySelector('[data-page="play"] [data-drop]');
    this.captureName = document.getElementById("capture-name");
    this.captureButton = document.getElementById("capture-save");
  }

  start() {
    document.getElementById("play-saved-button").addEventListener("click", (event) => this.playSaved(event.currentTarget));
    this.fileInput.addEventListener("change", () => this.load(this.fileInput.files[0]));
    this.drop.addEventListener("dragover", (event) => event.preventDefault());
    this.drop.addEventListener("drop", (event) => {
      event.preventDefault();
      this.load(event.dataTransfer.files[0]);
    });
    this.captureButton.addEventListener("click", () => this.capture());
    document.addEventListener("recorder:playback", (event) => {
      this.captureButton.disabled = event.detail.state !== "paused";
    });
    onTabShown("play", () => this.refresh());
  }

  async refresh() {
    const listing = await api("GET", "/api/actions");
    fillSelect(this.savedSelect, [{ options: listing.compiled.map((name) => ({ value: name, text: name })) }], "Choose a saved action…");
  }

  async playSaved(button) {
    if (!this.savedSelect.value) {
      toast("Choose a saved action first", "error");
      return;
    }
    await run(button, () => api("POST", "/api/playback/play", { name: this.savedSelect.value }));
  }

  async load(file) {
    if (!file) return;
    const query = new URLSearchParams({ filename: file.name });
    const snapshot = await run(null, () => api("POST", `/api/playback/import?${query}`, file));
    this.fileInput.value = "";
    if (snapshot) toast(`Opened ${file.name} as ${snapshot.source} · ${snapshot.count} frames, ${snapshot.duration.toFixed(1)} s. Press play.`);
  }

  async capture() {
    const name = this.captureName.value.trim();
    if (!name) {
      toast("Enter a pose name first", "error");
      this.captureName.focus();
      return;
    }
    const poseType = document.querySelector('input[name="capture-kind"]:checked').value;
    const result = await run(this.captureButton, () => saveOrReplace(name, (overwrite) =>
      api("POST", "/api/playback/capture", { pose_type: poseType, name, overwrite })));
    const labels = { left_arm: "left-arm", right_arm: "right-arm", composed: "composed" };
    if (result) toast(`Saved ${result.name} (${labels[poseType]} pose)`);
  }
}

document.addEventListener("DOMContentLoaded", () => new PlayTab().start());
