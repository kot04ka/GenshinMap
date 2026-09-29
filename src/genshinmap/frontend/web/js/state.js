// Общее состояние страницы и перевод координат игры в координаты Leaflet.
let META, LABELS = [], POINTS_BY_LABEL = {}, REGIONS = [], COLLECTED = new Set();
let PROBABLE = new Set();     // подмножество COLLECTED: «вероятно собрано»
const labelById = {};
const regionById = {};
const pointInfo = new Map();  // pid -> [x, y, labelId, area] (для перехода к точке)
const enabled = new Set();    // включённые label_id
const markerByPoint = {};     // pid -> {marker,labelId,x,y} (только видимые)
const rowByLabel = {};        // label_id -> {row, cb, cnt, bar, group}
const groupEls = {};          // имя группы -> {el, cb, cnt, labels:[id]}
const markerLayer = L.layerGroup();
const regionLayer = L.layerGroup();
const anchorLayer = L.layerGroup();
const heatLayer = L.layerGroup();
let ANCHORS = [], heatOn = false;
let bridge = null, map = null;
let hideCollected = false;
let activeRegion = null;      // area_id или null (весь мир)
let follow = false;           // карта следует за игроком
let playerMarker = null, lastPlayer = null, followBtn = null, meBtn = null;
let CONTENT_BOUNDS = null;
let lastRenderInfo = { shown: 0, inView: 0, thinned: false };

// Порядок групп в панели: сначала навигация и сокровища, в конце противники/метки.
const GROUP_ORDER = ['Телепорт', 'Сокровища', 'Сокровища с загадкой', 'Опыт', 'Ценные предметы',
  'Местная диковинка', 'Инвентарь / ресурсы', 'Руда', 'Древесина', 'Животные', 'Рыбалка',
  'Противники', 'Метки'];

// --- координаты: игровые (x,y) -> пиксель картинки -> latLng Leaflet ---
function toLatLng(x, y) {
  return [-(META.origin[1] + y), META.origin[0] + x];   // ось Y вниз
}
function bboxToBounds(b) {  // [x0,y0,x1,y1] в мировых -> LatLngBounds
  return L.latLngBounds(toLatLng(b[0], b[1]), toLatLng(b[2], b[3]));
}
