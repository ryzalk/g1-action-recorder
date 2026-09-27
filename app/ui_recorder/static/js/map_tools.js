/* Map page, drawing tools: pointer input -> world geometry (metres); the shape being drawn and the one waiting
   for confirmation are drawn on the overlay. Ported from map-editor's edit_tools.js. */

// kind decides the gesture: drag kinds are pressed and dragged, click kinds are clicked point by point.
// The server takes two geometries only: a polygon, or a polyline with width_m.
const TOOLS = {
  pan: { hint: "Drag to pan, scroll to zoom" },
  lasso_erase: { action: "erase", kind: "lasso", hint: "Lasso: drag around the ghost, release to preview · right drag pans" },
  rect_erase: { action: "erase", kind: "rect", hint: "Drag a rectangle, release to preview · right drag pans" },
  brush_erase: { action: "erase", kind: "brush", hint: "Brush over it, release to preview · right drag pans" },
  polyline_wall: { action: "obstacle", kind: "polyline", hint: "Click to add points, double-click or Enter to finish, Esc cancels · Shift: no snapping" },
  polygon_fill: { action: "obstacle", kind: "polygon", hint: "Click to add points, double-click or Enter to fill, Esc cancels · Shift: no snapping" },
  rect_fill: { action: "obstacle", kind: "rect", hint: "Drag a rectangle, release to fill · Shift: no snapping" },
  obstacle_brush: { action: "obstacle", kind: "brush", hint: "Brush, release to fill · right drag pans" },
  // A candidate's Clear / Fill: no button; the shape is the candidate's outline, with preview and history as usual.
  candidate_erase: { action: "erase", kind: "polygon", hint: "" },
  candidate_fill: { action: "obstacle", kind: "polygon", hint: "" },
};
const DRAG_KINDS = new Set(["lasso", "rect", "brush"]);

let activeTool = "pan";
let toolPoints = [];      // vertices of the shape being drawn, world metres
let toolCursor = null;    // the (snapped) cursor, for the rubber band of click tools
let toolDragging = false;
let snapMark = null;      // where the last snap landed, drawn as a small ring
let lastClick = { time: 0, x: 0, y: 0 };
let snapRadius = 0.15;
// Vertices of shapes applied this session; a new wall can join them.
let committedVertices = [];
// An erase drawn and waiting for confirmation: { tool, geometry, request, preview }, set and cleared by map_page.js.
let pendingShape = null;

function mapInput(id) {
  return document.getElementById(id);
}

function selectTool(name) {
  activeTool = name;
  toolPoints = [];
  toolDragging = false;
  snapMark = null;
  lastClick = { time: 0, x: 0, y: 0 };
  for (const button of document.querySelectorAll("[data-tool]")) button.dataset.active = String(button.dataset.tool === name);
  document.getElementById("map-tool-hint").textContent = TOOLS[name].hint;
  mapViewport.style.cursor = name === "pan" ? "" : "crosshair";
  drawOverlay();
}

function toolPointerDown(event) {
  const kind = TOOLS[activeTool].kind;
  const world = snapped(eventToWorld(event), event);
  if (pendingShape) runInOrder(cancelEdit);
  if (DRAG_KINDS.has(kind)) {
    toolPoints = [world];
    toolDragging = true;
    return;
  }
  // The second click of a double-click only finishes; it adds no point (snapped, it may not land on the first).
  const again = event.timeStamp - lastClick.time < 400 && Math.hypot(event.clientX - lastClick.x, event.clientY - lastClick.y) < 5;
  lastClick = { time: event.timeStamp, x: event.clientX, y: event.clientY };
  if (again) return;
  toolPoints.push(world);
  drawOverlay();
}

function toolPointerMove(event) {
  if (activeTool === "pan") return;
  const kind = TOOLS[activeTool].kind;
  const world = snapped(eventToWorld(event), event);
  toolCursor = world;
  if (toolDragging && kind === "rect") {
    toolPoints = [toolPoints[0], world];
  } else if (toolDragging) {
    // A new point only after 3 screen pixels, so lasso and brush point counts don't depend on the zoom.
    const last = worldToScreen(toolPoints.at(-1).x, toolPoints.at(-1).y);
    const now = worldToScreen(world.x, world.y);
    if (Math.hypot(now.x - last.x, now.y - last.y) > 3) toolPoints.push(world);
  }
  drawOverlay();
}

function toolPointerUp() {
  if (!toolDragging) return;
  toolDragging = false;
  finishShape();
}

function toolDoubleClick() {
  const kind = TOOLS[activeTool].kind;
  if (kind !== "polyline" && kind !== "polygon") return;
  toolPoints = dedupePoints(toolPoints);
  finishShape();
}

// After a shape ends or is cancelled, the next click starts a new one; it can't be a double-click's second half.
function finishShape() {
  const geometry = toGeometry(activeTool, toolPoints);
  const kind = TOOLS[activeTool].kind;
  toolPoints = [];
  snapMark = null;
  lastClick = { time: 0, x: 0, y: 0 };
  drawOverlay();
  const tool = activeTool;
  if (geometry) runInOrder(() => onShapeFinished(tool, geometry));
  else if (kind === "polyline" || kind === "polygon") toast(kind === "polyline" ? "A wall needs at least two points" : "A polygon needs at least three points", "warning");
}

function cancelDrawing() {
  toolPoints = [];
  toolDragging = false;
  snapMark = null;
  lastClick = { time: 0, x: 0, y: 0 };
  drawOverlay();
}

// Snapping: first nearby end points (vertices applied before, the polygon's first point), then existing walls
// (occupied cells) for a start point or rectangle corner; failing both, click tools lock the angle to θ₀.
// Lasso and brush never snap; Shift turns all of it off.
function snapped(world, event) {
  snapMark = null;
  const kind = TOOLS[activeTool].kind;
  if (event.shiftKey || kind === "lasso" || kind === "brush") return world;
  const clicking = kind === "polyline" || kind === "polygon";
  if (mapInput("map-snap-point").checked) {
    const vertex = nearestVertex(world, [...committedVertices, ...(clicking ? toolPoints.slice(0, 1) : [])]);
    if (vertex) {
      snapMark = vertex;
      return vertex;
    }
    const startingShape = !clicking || toolPoints.length === 0;
    const wall = startingShape ? nearestOccupied(world) : null;
    if (wall) {
      snapMark = wall;
      return wall;
    }
  }
  if (mapInput("map-snap-angle").checked && clicking && toolPoints.length > 0) return angleSnapped(toolPoints.at(-1), world);
  return world;
}

function nearestVertex(world, vertices) {
  let best = null;
  let bestDistance = snapRadius;
  for (const vertex of vertices) {
    const distance = Math.hypot(vertex.x - world.x, vertex.y - world.y);
    if (distance <= bestDistance) {
      best = vertex;
      bestDistance = distance;
    }
  }
  return best;
}

// The nearest occupied cell centre within the snap radius, so a new wall joins an old one without a gap.
function nearestOccupied(world) {
  if (!gridPixels) return null;
  const pixel = worldToPixel(world.x, world.y);
  const reach = Math.ceil(snapRadius / mapView.resolution);
  let best = null;
  let bestDistance = snapRadius;
  for (let row = Math.floor(pixel.row) - reach; row <= Math.floor(pixel.row) + reach; row++) {
    for (let col = Math.floor(pixel.col) - reach; col <= Math.floor(pixel.col) + reach; col++) {
      if (row < 0 || col < 0 || row >= mapView.height || col >= mapView.width) continue;
      if (gridPixels[(row * mapView.width + col) * 4] !== 0) continue;
      const centre = pixelToWorld(col + 0.5, row + 0.5);
      const distance = Math.hypot(centre.x - world.x, centre.y - world.y);
      if (distance <= bestDistance) {
        best = centre;
        bestDistance = distance;
      }
    }
  }
  return best;
}

// Lock last -> world to θ₀ + k·90° (or 45° when chosen); the length is the cursor's projection on it.
function angleSnapped(last, world) {
  const step = mapInput("map-snap-diagonal").checked ? Math.PI / 4 : Math.PI / 2;
  const angle = Math.atan2(world.y - last.y, world.x - last.x);
  const direction = mapView.mainDirection + Math.round((angle - mapView.mainDirection) / step) * step;
  const length = (world.x - last.x) * Math.cos(direction) + (world.y - last.y) * Math.sin(direction);
  return { x: last.x + length * Math.cos(direction), y: last.y + length * Math.sin(direction) };
}

function dedupePoints(points) {
  const kept = [];
  for (const point of points) {
    const last = kept.at(-1);
    const near = last && Math.hypot(point.x - last.x, point.y - last.y) < mapView.resolution / 2;
    if (!near) kept.push(point);
  }
  return kept;
}

// A rectangle's two sides: measured in the frame turned by θ₀ when "Rectangles along θ₀" is on, else along the axes.
function rectFrame(start, end) {
  const angle = mapInput("map-rect-aligned").checked ? mapView.mainDirection : 0;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  return { cos, sin, u: dx * cos + dy * sin, v: -dx * sin + dy * cos };
}

function rectToPolygon(start, end) {
  const { cos, sin, u, v } = rectFrame(start, end);
  const corner = (a, b) => [start.x + a * cos - b * sin, start.y + a * sin + b * cos];
  return [corner(0, 0), corner(u, 0), corner(u, v), corner(0, v)];
}

// Vertices -> geometry, for drawing and for the request alike.
function shapeOf(kind, points) {
  const coords = points.map((point) => [point.x, point.y]);
  if (kind === "rect") return { polygon: rectToPolygon(points[0], points.at(-1)) };
  if (kind === "brush") return { polyline: coords, width_m: Number(mapInput("map-brush-radius").value) * 2 };
  if (kind === "polyline") return { polyline: coords, width_m: Number(mapInput("map-wall-width").value) };
  return { polygon: coords };
}

// Input that makes no shape (lasso under 3 points, a flat rectangle, a wall under 2 points) gives null: no request.
function toGeometry(tool, points) {
  const kind = TOOLS[tool].kind;
  const distinct = dedupePoints(points).length;
  const frame = points.length === 2 ? rectFrame(points[0], points[1]) : null;
  const enough = {
    brush: points.length >= 1,
    polyline: distinct >= 2,
    rect: frame !== null && Math.abs(frame.u) > 1e-6 && Math.abs(frame.v) > 1e-6,
    lasso: distinct >= 3,
    polygon: distinct >= 3,
  };
  if (!enough[kind]) return null;
  // A click without moving is a dab too: the point twice, drawn as a disc by the server.
  return shapeOf(kind, kind === "brush" && points.length === 1 ? [points[0], points[0]] : points);
}

// After a successful edit its vertices are kept, so later walls can snap to them.
function rememberVertices(geometry) {
  const points = geometry.polygon ?? geometry.polyline;
  committedVertices.push(...points.map(([x, y]) => ({ x, y })));
}

// Overlay: the shape waiting for confirmation (dashed), the shape being drawn (click tools rubber-band to the
// cursor, with a measurement), the snap ring.
function drawToolShapes(context) {
  if (pendingShape) drawGeometry(context, pendingShape.geometry, TOOLS[pendingShape.tool].action, true);
  if (activeTool === "pan") return;
  if (snapMark) drawSnapMark(context, snapMark);
  if (toolPoints.length === 0) return;
  const kind = TOOLS[activeTool].kind;
  const clicking = kind === "polyline" || kind === "polygon";
  const points = clicking && toolCursor ? [...toolPoints, toolCursor] : toolPoints;
  drawGeometry(context, shapeOf(kind, points), TOOLS[activeTool].action, false);
  if (clicking && toolCursor) drawMeasure(context, toolPoints.at(-1), toolCursor);
  if (kind === "rect" && points.length === 2) drawRectSize(context, points[0], points[1]);
}

function drawGeometry(context, geometry, action, pending) {
  const stroke = action === "erase" ? "#2563eb" : "#111827";
  const fill = action === "erase" ? "rgba(37, 99, 235, 0.22)" : "rgba(17, 24, 39, 0.35)";
  context.save();
  context.setLineDash(pending ? [6, 4] : []);
  context.beginPath();
  const points = geometry.polygon ?? geometry.polyline;
  points.forEach(([x, y], index) => {
    const screen = worldToScreen(x, y);
    if (index === 0) context.moveTo(screen.x, screen.y);
    else context.lineTo(screen.x, screen.y);
  });
  if (geometry.polygon) {
    context.closePath();
    context.fillStyle = fill;
    context.fill();
    context.strokeStyle = stroke;
    context.lineWidth = 1.5;
    context.stroke();
  } else {
    context.strokeStyle = fill;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.lineWidth = Math.max(2, (geometry.width_m / mapView.resolution) * mapView.zoom);
    context.stroke();
  }
  context.restore();
}

function drawSnapMark(context, world) {
  const screen = worldToScreen(world.x, world.y);
  context.save();
  context.strokeStyle = "#f59e0b";
  context.lineWidth = 2;
  context.beginPath();
  context.arc(screen.x, screen.y, 7, 0, Math.PI * 2);
  context.stroke();
  context.restore();
}

function drawMeasure(context, from, to) {
  const length = Math.hypot(to.x - from.x, to.y - from.y);
  const angle = ((Math.atan2(to.y - from.y, to.x - from.x) * 180) / Math.PI + 360) % 360;
  drawLabel(context, to, `${length.toFixed(2)} m  ${angle.toFixed(1)}°`);
}

function drawRectSize(context, start, end) {
  const { u, v } = rectFrame(start, end);
  drawLabel(context, end, `${Math.abs(u).toFixed(2)} × ${Math.abs(v).toFixed(2)} m`);
}

function drawLabel(context, world, text) {
  const screen = worldToScreen(world.x, world.y);
  context.font = "12px ui-monospace, monospace";
  const width = context.measureText(text).width;
  context.fillStyle = "rgba(255, 255, 255, 0.9)";
  context.fillRect(screen.x + 10, screen.y + 10, width + 8, 18);
  context.fillStyle = "#111827";
  context.fillText(text, screen.x + 14, screen.y + 23);
}
