/* Map page, the 2D map: stacked layer images, zoom and pan, pixel <-> world, the cursor readout, tour points.
   Ported from map-editor's map_canvas.js. */

const mapViewport = document.getElementById("map-viewport");
const mapStage = document.getElementById("map-stage");
const mapOverlay = document.getElementById("map-overlay");

// Pixel coordinates start at the grid's top-left corner (continuous; row 0 is the top); screen = pan + pixel × zoom.
const mapView = {
  width: 0, height: 0, resolution: 0.05, originX: 0, originY: 0,
  zoom: 1, panX: 0, panY: 0, tourPoints: [], showTour: true, showCandidates: true,
  // The building's main direction (radians, counter-clockwise in the world frame), for snapping and rectangles.
  mainDirection: 0,
  // Until the user zooms or pans, a change in the viewport's size fits the map again.
  autoFit: true,
  loaded: false,
};
// The current grid's raw values (RGBA expanded), for the cursor readout and snapping to walls.
let gridPixels = null;

function setMapView(info) {
  Object.assign(mapView, {
    width: info.width, height: info.height, resolution: info.resolution, originX: info.origin[0], originY: info.origin[1],
    tourPoints: info.tour_points, mainDirection: (info.main_direction_deg * Math.PI) / 180, loaded: true,
  });
  mapStage.style.width = `${info.width}px`;
  mapStage.style.height = `${info.height}px`;
  for (const image of mapStage.querySelectorAll("img")) {
    image.width = info.width;
    image.height = info.height;
  }
}

// World (metres) -> continuous pixel; floored, it matches the server's OccupancyGrid.world_to_pixel.
function worldToPixel(x, y) {
  return { col: (x - mapView.originX) / mapView.resolution, row: mapView.height - (y - mapView.originY) / mapView.resolution };
}

function pixelToWorld(col, row) {
  return { x: mapView.originX + col * mapView.resolution, y: mapView.originY + (mapView.height - row) * mapView.resolution };
}

function screenToPixel(clientX, clientY) {
  const rect = mapViewport.getBoundingClientRect();
  return { col: (clientX - rect.left - mapView.panX) / mapView.zoom, row: (clientY - rect.top - mapView.panY) / mapView.zoom };
}

function pixelToScreen(col, row) {
  return { x: mapView.panX + col * mapView.zoom, y: mapView.panY + row * mapView.zoom };
}

function worldToScreen(x, y) {
  const pixel = worldToPixel(x, y);
  return pixelToScreen(pixel.col, pixel.row);
}

function eventToWorld(event) {
  const pixel = screenToPixel(event.clientX, event.clientY);
  return pixelToWorld(pixel.col, pixel.row);
}

function applyTransform() {
  mapStage.style.transform = `translate(${mapView.panX}px, ${mapView.panY}px) scale(${mapView.zoom})`;
  const centimetres = (mapView.resolution * 100) / mapView.zoom;
  document.getElementById("map-zoom-level").textContent = `${Math.round(mapView.zoom * 100)}% · 1 px ≈ ${centimetres.toFixed(1)} cm`;
  drawOverlay();
}

function fitView() {
  const rect = mapViewport.getBoundingClientRect();
  // Hidden (another page is shown): nothing to fit to yet.
  if (!mapView.loaded || rect.width === 0 || rect.height === 0) return;
  mapView.autoFit = true;
  mapView.zoom = Math.min(rect.width / mapView.width, rect.height / mapView.height) * 0.95;
  mapView.panX = (rect.width - mapView.width * mapView.zoom) / 2;
  mapView.panY = (rect.height - mapView.height * mapView.zoom) / 2;
  applyTransform();
}

function zoomAround(x, y, factor) {
  const zoom = Math.min(40, Math.max(0.3, mapView.zoom * factor));
  mapView.panX = x - ((x - mapView.panX) * zoom) / mapView.zoom;
  mapView.panY = y - ((y - mapView.panY) * zoom) / mapView.zoom;
  mapView.zoom = zoom;
  mapView.autoFit = false;
  applyTransform();
}

// An image replaced by a newer address before it decoded is aborted by the browser: superseded, not failed.
async function loadLayer(image, url) {
  image.src = url;
  try {
    await image.decode();
  } catch (error) {
    if (image.getAttribute("src") === url) throw error;
  }
}

function readGridPixels(image) {
  const canvas = document.createElement("canvas");
  canvas.width = mapView.width;
  canvas.height = mapView.height;
  const context = canvas.getContext("2d");
  context.drawImage(image, 0, 0);
  gridPixels = context.getImageData(0, 0, mapView.width, mapView.height).data;
}

// Tour points and candidate outlines are drawn on the overlay; the other layers are images.
function setLayerVisible(name, visible) {
  if (name === "tour" || name === "candidates") {
    mapView[name === "tour" ? "showTour" : "showCandidates"] = visible;
    drawOverlay();
    return;
  }
  document.getElementById(`map-layer-${name}`).classList.toggle("hidden", !visible);
}

// The overlay is redrawn in screen pixels, so lines and text stay sharp at any zoom.
function drawOverlay() {
  const ratio = window.devicePixelRatio || 1;
  const rect = mapViewport.getBoundingClientRect();
  mapOverlay.width = rect.width * ratio;
  mapOverlay.height = rect.height * ratio;
  const context = mapOverlay.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, rect.width, rect.height);
  if (!mapView.loaded) return;
  if (mapView.showCandidates) drawCandidates(context);
  if (mapView.showTour) drawTourPoints(context);
  drawToolShapes(context);
  drawCompass(context, rect.width);
}

// Top right: the main direction θ₀ and θ₀ + 90° as two crossing lines.
function drawCompass(context, width) {
  const centre = { x: width - 34, y: 34 };
  context.save();
  context.fillStyle = "rgba(255, 255, 255, 0.9)";
  context.strokeStyle = "#e5e7eb";
  context.beginPath();
  context.arc(centre.x, centre.y, 24, 0, Math.PI * 2);
  context.fill();
  context.stroke();
  context.lineWidth = 2;
  for (const [angle, colour] of [[mapView.mainDirection, "#2563eb"], [mapView.mainDirection + Math.PI / 2, "#94a3b8"]]) {
    context.strokeStyle = colour;
    context.beginPath();
    context.moveTo(centre.x - Math.cos(angle) * 18, centre.y + Math.sin(angle) * 18);
    context.lineTo(centre.x + Math.cos(angle) * 18, centre.y - Math.sin(angle) * 18);
    context.stroke();
  }
  context.fillStyle = "#1e3a8a";
  context.font = "11px ui-sans-serif, system-ui, sans-serif";
  context.textAlign = "center";
  context.fillText(`θ₀ ${((mapView.mainDirection * 180) / Math.PI).toFixed(1)}°`, centre.x, centre.y + 38);
  context.restore();
}

function drawTourPoints(context) {
  context.font = "12px ui-sans-serif, system-ui, sans-serif";
  for (const point of mapView.tourPoints) {
    const screen = worldToScreen(point.x, point.y);
    // World y points up, screen y down: the heading's y flips.
    const headX = screen.x + Math.cos(point.yaw) * 16;
    const headY = screen.y - Math.sin(point.yaw) * 16;
    context.strokeStyle = "#2563eb";
    context.fillStyle = "#2563eb";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(screen.x, screen.y);
    context.lineTo(headX, headY);
    context.stroke();
    context.beginPath();
    context.arc(screen.x, screen.y, 5, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = "#1e3a8a";
    context.fillText(`${point.name} (${point.x}, ${point.y})`, screen.x + 8, screen.y - 8);
  }
}

function showCursor(event) {
  const pixel = screenToPixel(event.clientX, event.clientY);
  const world = pixelToWorld(pixel.col, pixel.row);
  const col = Math.floor(pixel.col);
  const row = Math.floor(pixel.row);
  const inside = col >= 0 && col < mapView.width && row >= 0 && row < mapView.height;
  document.getElementById("map-cursor-world").textContent = `x ${world.x.toFixed(2)}  y ${world.y.toFixed(2)} m`;
  document.getElementById("map-cursor-pixel").textContent = inside ? `row ${row}  col ${col}` : "off the grid";
  document.getElementById("map-cursor-value").textContent = inside && gridPixels ? `value ${gridPixels[(row * mapView.width + col) * 4]}` : "value —";
}

// The wheel zooms around the cursor. The left button belongs to the tool (panning with Pan); right or middle drag always pans.
function bindPanZoom() {
  let drag = null;
  mapViewport.addEventListener("wheel", (event) => {
    event.preventDefault();
    const rect = mapViewport.getBoundingClientRect();
    zoomAround(event.clientX - rect.left, event.clientY - rect.top, Math.pow(1.0015, -event.deltaY));
    showCursor(event);
  }, { passive: false });
  mapViewport.addEventListener("pointerdown", (event) => {
    if (!mapView.loaded) return;
    mapViewport.setPointerCapture(event.pointerId);
    if (event.button === 0 && activeTool !== "pan") {
      toolPointerDown(event);
      return;
    }
    drag = { x: event.clientX, y: event.clientY, panX: mapView.panX, panY: mapView.panY };
    mapViewport.style.cursor = "grabbing";
  });
  mapViewport.addEventListener("pointermove", (event) => {
    if (!mapView.loaded) return;
    showCursor(event);
    if (!drag) {
      toolPointerMove(event);
      return;
    }
    mapView.panX = drag.panX + event.clientX - drag.x;
    mapView.panY = drag.panY + event.clientY - drag.y;
    mapView.autoFit = false;
    applyTransform();
  });
  mapViewport.addEventListener("pointerup", (event) => {
    if (!drag) {
      toolPointerUp(event);
      return;
    }
    drag = null;
    mapViewport.style.cursor = activeTool === "pan" ? "" : "crosshair";
  });
  // When the browser takes the pointer (window switch, touch gesture) no pointerup comes: drop the half stroke.
  mapViewport.addEventListener("pointercancel", () => {
    if (toolDragging) cancelDrawing();
    drag = null;
  });
  mapViewport.addEventListener("dblclick", toolDoubleClick);
  mapViewport.addEventListener("contextmenu", (event) => event.preventDefault());
  for (const [id, factor] of [["map-zoom-in", 1.25], ["map-zoom-out", 0.8]]) {
    const button = document.getElementById(id);
    // The zoom buttons sit on the map: their clicks must not start a shape.
    button.addEventListener("pointerdown", (event) => event.stopPropagation());
    button.addEventListener("click", () => {
      const rect = mapViewport.getBoundingClientRect();
      zoomAround(rect.width / 2, rect.height / 2, factor);
    });
  }
  // The viewport changes size with the window and when the page first shows; window.resize covers only the first.
  new ResizeObserver(() => (mapView.autoFit ? fitView() : drawOverlay())).observe(mapViewport);
}
