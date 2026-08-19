// 本番: Cloudflare Containers (tsugaku-navi-backend) にデプロイしたバックエンド。
// GSI版モデル・ハッカソン特典(Workers Paid相当、2026-09-30頃まで)を利用。
// 旧HuggingFace Spaces版(niikun-tsugaku-navi-backend.hf.space、OSM版モデル)から移行。
// ローカル検証時は 'http://localhost:8787/ask' 'http://localhost:8787/score' に戻すこと。
const AI_BACKEND_URL = 'https://tsugaku-navi-backend.tokyo-odh-097.workers.dev/ask';
const AI_SCORE_URL = 'https://tsugaku-navi-backend.tokyo-odh-097.workers.dev/score'; // 地図を即座に描画するための軽量エンドポイント(Claude API呼び出しなし)

const state = {
    map: null,
    accidentsData: null,
    accidentMarkers: null,
    accidentHeatLayer: null,
    schoolsLayer: null,
    homeMarker: null,
    schoolMarker: null,
    routingControl: null,
    mode: null,
    lastRouteCoordinates: null,
    aiRiskLayer: null,
    aiAccidentLayer: null,
    aiFactsMarkers: [],
    crossingMarkers: [],
    narrowRoadLines: []
};

// この上限より高いズームでのみ、個別事故マーカー(タップで詳細)を表示する。
// それ未満はヒートマップだけにして、初期表示(市区町村スケール)で地図が
// 「生きている」感じになるようにする。
const MARKER_DETAIL_MIN_ZOOM = 15;

// ルート距離が直線距離の何倍を超えたら「遠回りかもしれない」ヒントを出すか。
// OSRM公開ルーターの歩行者プロファイルは、細街路が入り組んだ地域(歌舞伎町等)で
// 実際より遠回りな経路を返すことがあるが、ルーティング自体は直せない(公開デモ
// ルーターの挙動)ため、目安の注意書きだけ出す(1.8倍は普通の街区の曲がり
// くねりでは超えにくい値として設定)。
const DETOUR_RATIO_THRESHOLD = 1.8;

// 全域の過去事故ヒートマップは常時表示する。個別マーカー(タップで詳細)だけ、
// ズームが浅いうちは隠す(数千件を一度に描くと重いうえ見づらいため)。
function updateBaseAccidentLayerVisibility() {
    if (!state.map.hasLayer(state.accidentHeatLayer)) {
        state.map.addLayer(state.accidentHeatLayer);
    }
    const showMarkers = state.map.getZoom() >= MARKER_DETAIL_MIN_ZOOM;
    if (showMarkers && !state.map.hasLayer(state.accidentMarkers)) {
        state.map.addLayer(state.accidentMarkers);
    } else if (!showMarkers && state.map.hasLayer(state.accidentMarkers)) {
        state.map.removeLayer(state.accidentMarkers);
    }
}

function initMap() {
    // ズームボタンは左上のヘッダーカードと重ならないよう右下に出す。
    state.map = L.map('map', { zoomControl: false }).setView([35.6895, 139.6917], 12);
    L.control.zoom({ position: 'bottomright' }).addTo(state.map);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19
    }).addTo(state.map);

    state.accidentMarkers = L.markerClusterGroup({
        maxClusterRadius: 50,
        spiderfyOnMaxZoom: true,
        showCoverageOnHover: false,
        zoomToBoundsOnClick: true
    });

    // 事故マーカー(■)はL.marker(divIcon)なのでmarkerPane(z-index:600)に描画される。
    // AIコメントの円マーカー(危険地点・横断歩道)はL.circleMarker(SVG)なので、
    // 既定ではoverlayPane(z-index:400)に描画され、markerPaneより下になる。
    // 事故が密集している場所では■が常に〇の上に来てクリックを奪ってしまうため、
    // markerPaneより上(tooltipPane:650より下)に専用ペインを作り、AIコメントの
    // 円マーカーをそちらに描画することで、事故が密集していても必ず上に来て
    // クリックできるようにする。
    state.map.createPane('aiCommentPane');
    state.map.getPane('aiCommentPane').style.zIndex = 620;


    // 過去の事故の密度ヒートマップ。ページを開いた瞬間から、どのあたりが
    // 危ないかが一目でわかるように常時表示する(AIの予測ヒートマップとは
    // 色を変えて区別する: こちらは青→赤、AI予測は緑→赤)。
    state.accidentHeatLayer = L.heatLayer([], {
        radius: 22,
        blur: 18,
        maxZoom: 17,
        gradient: { 0.2: '#5B8DEF', 0.4: '#8E44AD', 0.65: '#E67E22', 1.0: '#C0392B' }
    });

    state.aiRiskLayer = L.heatLayer([], {
        radius: 35,
        blur: 25,
        maxZoom: 18,
        max: 1.0,
        gradient: { 0.15: '#4CAF50', 0.4: '#F1C40F', 0.65: '#E67E22', 0.9: '#C0392B' }
    });
    state.aiAccidentLayer = L.layerGroup();
    // 新宿区の区立小中学校(東京都オープンデータカタログ経由、40校のみ)。
    // 件数が少ないため、事故ヒートマップと違ってズームに関係なく常時表示する。
    state.schoolsLayer = L.layerGroup();

    state.map.addLayer(state.accidentHeatLayer);
    state.map.addLayer(state.aiRiskLayer);
    state.map.addLayer(state.aiAccidentLayer);
    state.map.addLayer(state.schoolsLayer);
    state.map.on('click', handleMapClick);

    // ズームが浅いうち(市区町村スケール)はヒートマップだけにして地図をすっきり見せ、
    // 近所スケールまで寄ったら個別マーカー(タップで詳細)を追加表示する。
    // さらに、AIのけっか(ルートしぼりこみのヒートマップ・マーカー)を表示している間は
    // 全域の過去事故レイヤーを隠す(同じ事故が二重に見えてごちゃごちゃになるため)。
    state.map.on('zoomend', updateBaseAccidentLayerVisibility);
    updateBaseAccidentLayerVisibility();

    // #mapをposition:absoluteのフローティングレイアウトにしたことで、初期化の
    // タイミングによってはLeafletがコンテナのサイズを正しく取得できず、
    // 地図がつぶれて表示されることがある(Leafletのよくある落とし穴)。
    // レイアウト確定後に明示的にサイズを再計算させて防ぐ。
    window.addEventListener('resize', () => state.map.invalidateSize());
    setTimeout(() => state.map.invalidateSize(), 100);
    setTimeout(() => state.map.invalidateSize(), 500);
}

// 事故履歴(■)とAIのコメント(〇)を形で明確に区別するための正方形マーカー。
// Leafletのcircle系(circleMarker)は円しか描けないため、divIconで四角いdivを描く。
function createSquareMarker(lat, lon, { size, color, fillColor, weight = 1, fillOpacity = 0.8 }) {
    const icon = L.divIcon({
        className: 'square-marker-icon',
        html: `<div style="width:100%;height:100%;background:${fillColor};opacity:${fillOpacity};border:${weight}px solid ${color};box-sizing:border-box;"></div>`,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
        popupAnchor: [0, -size / 2]
    });
    return L.marker([lat, lon], { icon });
}

async function loadAccidentData() {
    try {
        const response = await fetch('accidents.geojson');
        const data = await response.json();
        state.accidentsData = data;

        const heatPoints = data.features.map(feature => {
            const [lon, lat] = feature.geometry.coordinates;
            return [lat, lon, 0.5];
        });
        state.accidentHeatLayer.setLatLngs(heatPoints);

        data.features.forEach(feature => {
            const [lon, lat] = feature.geometry.coordinates;
            const props = feature.properties;

            const marker = createSquareMarker(lat, lon, {
                size: 10,
                fillColor: '#e74c3c',
                color: '#c0392b',
                weight: 1,
                fillOpacity: 0.6
            });

            const popupContent = `
                <div style="min-width: 200px; font-size: 0.9rem;">
                    <strong style="color: #C85A4C;">⚠️ じこがおきたばしょ</strong><br>
                    <strong>いつ:</strong> ${props.year}ねん${props.month}がつ${props.day}にち ${props.hour}:${props.minute}<br>
                    <strong>ひるよる:</strong> ${getDayNightLabel(props.day_night)}<br>
                    <strong>てんき:</strong> ${getWeatherLabel(props.weather)}<br>
                    <strong>なくなったひと:</strong> ${props.deaths}にん<br>
                    <strong>けがをしたひと:</strong> ${props.injuries}にん
                </div>
            `;

            marker.bindPopup(popupContent);
            state.accidentMarkers.addLayer(marker);
        });
    } catch (error) {
        console.error('事故データの読み込みに失敗しました:', error);
        document.getElementById('result-area').innerHTML = '<span class="warning-text">エラー: データの読み込みに失敗しました</span>';
    }
}

// 新宿区教育機関一覧(東京都オープンデータカタログサイト、自治体標準データセット、CC BY 4.0)。
// 「がっこうをきめる」の検索対象そのもの(区立小中学校)を地図上に見える化することで、
// 通学路の起点・終点になりうる場所を事前に把握できるようにする。
async function loadSchoolsData() {
    try {
        const response = await fetch('schools.geojson');
        const data = await response.json();

        data.features.forEach(feature => {
            const [lon, lat] = feature.geometry.coordinates;
            const props = feature.properties;

            const marker = L.circleMarker([lat, lon], {
                radius: 5,
                color: '#1D4ED8',
                fillColor: '#2563EB',
                weight: 1.5,
                fillOpacity: 0.85
            });

            marker.bindPopup(`
                <div style="min-width: 160px; font-size: 0.9rem;">
                    <strong style="color: #1D4ED8;">🏫 ${props.name}</strong><br>
                    <strong>しゅるい:</strong> ${props.type}<br>
                    <strong>ばしょ:</strong> ${props.ward}${props.address}
                </div>
            `);
            state.schoolsLayer.addLayer(marker);
        });
    } catch (error) {
        console.error('学校データの読み込みに失敗しました:', error);
    }
}

function handleMapClick(e) {
    const { lat, lng } = e.latlng;

    if (state.mode === 'home') {
        createHomeMarker(lat, lng);
        clearMode();
        updatePinStatus('つぎは「がっこうをきめる」ボタンをおしてね');
    } else if (state.mode === 'school') {
        createSchoolMarker(lat, lng);
        clearMode();
        setupRouting();
    } else {
        updatePinStatus('まず「おうちをきめる」か「がっこうをきめる」ボタンをおしてね');
    }
}

function createHomeMarker(lat, lng) {
    if (state.homeMarker) state.map.removeLayer(state.homeMarker);

    const icon = L.divIcon({
        html: '<div style="font-size: 40px; line-height: 1;">🏡</div>',
        iconSize: [44, 44],
        iconAnchor: [22, 44],
        popupAnchor: [0, -44],
        className: 'custom-marker-icon'
    });

    state.homeMarker = L.marker([lat, lng], { icon, draggable: true }).addTo(state.map);
    state.homeMarker.bindPopup('<strong>🏡 おうち</strong>').openPopup();

    state.homeMarker.on('dragend', () => {
        if (state.schoolMarker && state.routingControl) {
            state.routingControl.setWaypoints([
                state.homeMarker.getLatLng(),
                state.schoolMarker.getLatLng()
            ]);
        }
    });
}

function createSchoolMarker(lat, lng) {
    if (state.schoolMarker) state.map.removeLayer(state.schoolMarker);

    const icon = L.divIcon({
        html: '<div style="font-size: 40px; line-height: 1;">🏫</div>',
        iconSize: [44, 44],
        iconAnchor: [22, 44],
        popupAnchor: [0, -44],
        className: 'custom-marker-icon'
    });

    state.schoolMarker = L.marker([lat, lng], { icon, draggable: true }).addTo(state.map);
    state.schoolMarker.bindPopup('<strong>🏫 がっこう</strong>').openPopup();

    state.schoolMarker.on('dragend', () => {
        if (state.homeMarker && state.routingControl) {
            state.routingControl.setWaypoints([
                state.homeMarker.getLatLng(),
                state.schoolMarker.getLatLng()
            ]);
        }
    });
}

function setupRouting() {
    if (!state.homeMarker || !state.schoolMarker) return;

    if (state.routingControl) {
        state.map.removeControl(state.routingControl);
        state.routingControl = null;
    }

    updatePinStatus('ルートを計算中...');
    setControlsCollapsed(true); // おうち・がっこう両方きまったので操作パネルをたたんで地図を広く使う
    document.getElementById('route-detour-hint').hidden = true;

    const profile = document.getElementById('route-mode').value;

    state.routingControl = L.Routing.control({
        waypoints: [
            state.homeMarker.getLatLng(),
            state.schoolMarker.getLatLng()
        ],
        createMarker: () => null,
        show: false,
        collapsible: false,
        fitSelectedRoutes: false,
        routeWhileDragging: false,
        addWaypoints: false,
        lineOptions: {
            styles: [{ color: '#FF69B4', weight: 5, opacity: 0.85, dashArray: '12, 8' }]
        },
        router: L.Routing.osrmv1({
            serviceUrl: 'https://router.project-osrm.org/route/v1',
            profile
        })
    }).addTo(state.map);

    state.routingControl.on('routesfound', (e) => {
        const route = e.routes[0];
        const distanceKm = (route.summary.totalDistance / 1000).toFixed(2);
        updatePinStatus(`ルート: ${distanceKm} km — マークはうごかせるよ ✨`);
        calculateNearbyAccidents(route.coordinates);
        state.lastRouteCoordinates = route.coordinates.map(c => [c.lat, c.lng]);
        document.getElementById('ai-ask-btn').disabled = false;

        // 直線距離に対してルートが極端に長い場合、公開ルーターが遠回りな経路を
        // 返している可能性を目安として伝える(ルーティング自体は直せないため)。
        const straightLineM = state.homeMarker.getLatLng().distanceTo(state.schoolMarker.getLatLng());
        const detourHint = document.getElementById('route-detour-hint');
        if (straightLineM > 0 && route.summary.totalDistance / straightLineM > DETOUR_RATIO_THRESHOLD) {
            const ratio = (route.summary.totalDistance / straightLineM).toFixed(1);
            detourHint.textContent = `🔀 このルートは遠回りしているかもしれません（直線距離の約${ratio}倍）`;
            detourHint.hidden = false;
        } else {
            detourHint.hidden = true;
        }
    });

    state.routingControl.on('routingerror', () => {
        updatePinStatus('ルートが見つかりませんでした。別の場所を選んでみてね');
    });
}

function distanceToLineSegment(point, start, end) {
    const x = point.lat, y = point.lng;
    const x1 = start.lat, y1 = start.lng;
    const x2 = end.lat, y2 = end.lng;

    const C = x2 - x1, D = y2 - y1;
    const lenSq = C * C + D * D;
    const param = lenSq !== 0 ? ((x - x1) * C + (y - y1) * D) / lenSq : -1;

    let xx, yy;
    if (param < 0) { xx = x1; yy = y1; }
    else if (param > 1) { xx = x2; yy = y2; }
    else { xx = x1 + param * C; yy = y1 + param * D; }

    return point.distanceTo(L.latLng(xx, yy));
}

function calculateNearbyAccidents(coordinates) {
    if (!state.accidentsData || coordinates.length < 2) return;

    const buffer = 70;
    const bufDeg = buffer / 111000;

    let minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity;
    coordinates.forEach(c => {
        if (c.lat < minLat) minLat = c.lat;
        if (c.lat > maxLat) maxLat = c.lat;
        if (c.lng < minLng) minLng = c.lng;
        if (c.lng > maxLng) maxLng = c.lng;
    });
    minLat -= bufDeg; maxLat += bufDeg;
    minLng -= bufDeg * 1.4; maxLng += bufDeg * 1.4;

    let count = 0;
    state.accidentsData.features.forEach(feature => {
        const [lon, lat] = feature.geometry.coordinates;
        if (lat < minLat || lat > maxLat || lon < minLng || lon > maxLng) return;

        const pos = L.latLng(lat, lon);
        for (let i = 0; i < coordinates.length - 1; i++) {
            const s = L.latLng(coordinates[i].lat, coordinates[i].lng);
            const e = L.latLng(coordinates[i + 1].lat, coordinates[i + 1].lng);
            if (distanceToLineSegment(pos, s, e) <= buffer) {
                count++;
                break;
            }
        }
    });

    displayResult(count);
}

function displayResult(count) {
    let message, className = '';
    if (count === 0) {
        message = '⭐ すごい！ このみちはとってもあんぜんだよ！';
    } else if (count < 10) {
        message = `😊 このみちには <strong>${count}かい</strong> のじこがあったよ。きをつけてあるこうね！`;
    } else if (count < 30) {
        message = `⚠️ このみちには <strong>${count}かい</strong> のじこがあったよ。ちゅういしてね！`;
        className = 'warning-text';
    } else {
        message = `🚨 このみちには <strong>${count}かい</strong> もじこがあったよ！べつのみちをさがしてみよう！`;
        className = 'warning-text';
    }
    document.getElementById('result-area').innerHTML = `<div class="result-text ${className}">${message}</div>`;
}

function updatePinStatus(text) {
    document.getElementById('pin-status').textContent = text;
}

function setMode(mode) {
    state.mode = mode;
    document.getElementById('home-mode-btn').classList.toggle('active', mode === 'home');
    document.getElementById('school-mode-btn').classList.toggle('active', mode === 'school');
    updatePinStatus(
        mode === 'home' ? 'ちずをクリックして「おうち」をきめてね 🏡' :
        'ちずをクリックして「がっこう」をきめてね 🏫'
    );
}

function clearMode() {
    state.mode = null;
    document.getElementById('home-mode-btn').classList.remove('active');
    document.getElementById('school-mode-btn').classList.remove('active');
}

function clearAiMapLayers() {
    if (state.aiRiskLayer) state.aiRiskLayer.setLatLngs([]);
    if (state.aiAccidentLayer) state.aiAccidentLayer.clearLayers();
    state.aiFactsMarkers.forEach(m => state.map.removeLayer(m));
    state.aiFactsMarkers = [];
    state.crossingMarkers.forEach(m => state.map.removeLayer(m));
    state.crossingMarkers = [];
    state.narrowRoadLines.forEach(l => state.map.removeLayer(l));
    state.narrowRoadLines = [];
    document.getElementById('ai-legend').hidden = true;
}

function resetAll() {
    if (state.homeMarker) { state.map.removeLayer(state.homeMarker); state.homeMarker = null; }
    if (state.schoolMarker) { state.map.removeLayer(state.schoolMarker); state.schoolMarker = null; }
    if (state.routingControl) { state.map.removeControl(state.routingControl); state.routingControl = null; }
    clearMode();
    updatePinStatus('まず「おうちをきめる」ボタンをおしてね');
    document.getElementById('route-detour-hint').hidden = true;
    document.getElementById('result-area').innerHTML = '';
    state.lastRouteCoordinates = null;
    document.getElementById('ai-ask-btn').disabled = true;
    document.getElementById('ai-answer-area').innerHTML = '';
    clearAiMapLayers();

    // 操作パネルを開き直す(setupRouting側でたたんだ状態を元に戻す)。
    setControlsCollapsed(false);
}

// おうち・がっこうボタンの操作パネルをたたむ/ひろげる。両方のピンを置き終えたら
// 自動でたたんで地図を広く使えるようにする(setupRoutingから呼ばれる)。
function setControlsCollapsed(collapsed) {
    const buttons = document.getElementById('controls-buttons');
    const btn = document.getElementById('controls-toggle-btn');
    buttons.hidden = collapsed;
    btn.classList.toggle('active', !collapsed);
    btn.setAttribute('aria-expanded', String(!collapsed));
}

// カテゴリ(risk_model.pyのCATEGORY_LABELSと対応)をヒートマップの強さ(0〜1)に変換する。
// 生の予測件数は稀に大きく外れ値になる(駅前など)ため、表示にはカテゴリを使う。
const CATEGORY_HEAT_WEIGHT = { '安全': 0.15, 'やや注意': 0.4, '要注意': 0.65, '危険': 0.9 };

// OSMの道路種別(highway=タグ)をやさしい日本語に置き換える。
const ROAD_TYPE_LABELS = {
    primary: '大きな幹線道路',
    trunk: '大きな幹線道路',
    secondary: 'やや大きな道路',
    tertiary: '少し広い道路',
    residential: '住宅街の道路',
    service: 'せまい道・私道',
    unclassified: 'ふつうの生活道路'
};

function buildPointFactsPopupHtml(facts) {
    const osm = facts.osm || {};
    const roadLabel = ROAD_TYPE_LABELS[osm.dominant_road_type] || '道路の情報なし';
    const lines = [`🛣️ 道路のタイプ: ${roadLabel}`];
    lines.push(osm.signal_count > 0
        ? `🚦 信号機: 近くに${osm.signal_count}か所(いちばん近くて${Math.round(osm.signal_nearest_m)}m)`
        : `🚦 信号機: 近くにはないよ`);
    lines.push(osm.crossing_count > 0
        ? `🚸 横断歩道: 近くに${osm.crossing_count}か所(いちばん近くて${Math.round(osm.crossing_nearest_m)}m)`
        : `🚸 横断歩道: 近くにはないよ`);
    if (facts.has_sightline && facts.sightline) {
        lines.push(`👀 見通し: 平均${Math.round(facts.sightline.mean_sightline_m)}m先まで見える(いちばん悪い方向は${Math.round(facts.sightline.worst_direction_sightline_m)}m)`);
    }
    return `<strong>🔍 このばしょについて</strong><br>${lines.join('<br>')}`;
}

// 横断地点の分類ごとの色。既存のカテゴリ配色(緑〜赤のヒートマップ)・事故マーカー(青)・
// 事実情報マーカー(赤橙)と衝突しない色を選んでいる。
const CROSSING_STYLE = {
    signal: { color: '#0E9F8E', radius: 6, label: '信号のある横断歩道' },       // 落ち着いた緑
    marked: { color: '#F0A020', radius: 7, label: '信号のない横断歩道' },       // 目立つ黄色
    unmarked: { color: '#D6249F', radius: 8, label: '横断歩道のないところ' }    // もっとも目立つマゼンタ
};

function buildCrossingPopupHtml(c) {
    if (!c.has_marked_crossing) {
        return `<strong>🚧 ${CROSSING_STYLE.unmarked.label}</strong><br>ここは横断歩道のないところで道をわたります。とくに気をつけてね`;
    }
    if (c.has_signal) {
        return `<strong>🚦 ${CROSSING_STYLE.signal.label}</strong><br>信号をまもってわたろう`;
    }
    return `<strong>🚸 ${CROSSING_STYLE.marked.label}</strong><br>みぎひだりをよく見てわたろう`;
}

function renderAiMapLayers(riskPoints, accidentPoints, riskyPointsFacts, routeCrossings, narrowRoadSegments) {
    clearAiMapLayers();

    const heatPoints = (riskPoints || []).map(p => [p.lat, p.lon, CATEGORY_HEAT_WEIGHT[p.category] ?? 0.5]);
    state.aiRiskLayer.setLatLngs(heatPoints);

    // 事故履歴(■)は全域レイヤーと同じ赤で統一する。ルート沿いの事故か
    // 全域の事故かで色を分けていたが、同じ「事故があった場所」なので
    // 色を分ける意味がなかった(見た目が違うだけでユーザーには紛らわしい)。
    (accidentPoints || []).forEach(p => {
        createSquareMarker(p.lat, p.lon, {
            size: 12,
            color: '#c0392b',
            weight: 2,
            fillColor: '#e74c3c',
            fillOpacity: 0.9
        })
            .bindPopup(`<strong style="color: #C85A4C;">⚠️ じこがおきたばしょ</strong><br>${p.year}ねん${p.month}がつ${p.day}にち（${p.day_night}）`)
            .addTo(state.aiAccidentLayer);
    });

    // 危険度が高い区間ごとに事実情報マーカーを置く(最大3件、risk_model.py側で選定済み)。
    // AIがコメント(ポップアップ)を持つ地点はすべて点滅させ、タップできることに
    // 気づきやすくする。いちばんのおすすめ地点(i===0)は大きさ・濃さで目立たせる。
    (riskyPointsFacts || []).forEach((entry, i) => {
        const marker = L.circleMarker([entry.lat, entry.lon], {
            radius: i === 0 ? 10 : 8,
            color: '#C0392B',
            weight: i === 0 ? 3 : 2,
            fillColor: '#E67E22',
            fillOpacity: i === 0 ? 0.6 : 0.4,
            className: 'ai-facts-marker-pulse',
            pane: 'aiCommentPane' // 事故マーカー(■, markerPane)より上に来るようにする
        })
            .bindPopup(buildPointFactsPopupHtml(entry.facts))
            .addTo(state.map);
        state.aiFactsMarkers.push(marker);
    });

    // 実際に道路を横切る地点。住宅街の細い道の下に描く前に、まず細い道のライン(あれば)を敷く。
    (narrowRoadSegments || []).forEach(seg => {
        const line = L.polyline(
            [[seg.start_lat, seg.start_lon], [seg.end_lat, seg.end_lon]],
            { color: '#8E6FBF', weight: 8, opacity: 0.4, dashArray: '2, 6' }
        ).addTo(state.map);
        state.narrowRoadLines.push(line);
    });

    // 横断歩道・信号などの交通情報マーカーも、事実情報マーカーと同様に点滅させて
    // タップできる(AIのコメントがある)ことに気づきやすくする。
    (routeCrossings || []).forEach(c => {
        const style = !c.has_marked_crossing ? CROSSING_STYLE.unmarked
            : c.has_signal ? CROSSING_STYLE.signal
            : CROSSING_STYLE.marked;
        const marker = L.circleMarker([c.lat, c.lon], {
            radius: style.radius,
            color: '#FFFFFF',
            weight: 2,
            fillColor: style.color,
            fillOpacity: 0.95,
            className: 'ai-facts-marker-pulse',
            pane: 'aiCommentPane' // 事故マーカー(■, markerPane)より上に来るようにする
        })
            .bindPopup(buildCrossingPopupHtml(c))
            .addTo(state.map);
        state.crossingMarkers.push(marker);
    });

    if ((riskPoints && riskPoints.length) || (accidentPoints && accidentPoints.length)) {
        document.getElementById('ai-legend').hidden = false;
    }
}

async function askAiTeacher() {
    if (!state.homeMarker || !state.schoolMarker) return;

    const btn = document.getElementById('ai-ask-btn');
    const answerArea = document.getElementById('ai-answer-area');
    btn.disabled = true;
    btn.textContent = '考え中... 🤔';
    clearAiMapLayers();

    const home = state.homeMarker.getLatLng();
    const school = state.schoolMarker.getLatLng();
    const requestBody = JSON.stringify({
        home: { lat: home.lat, lon: home.lng },
        school: { lat: school.lat, lon: school.lng },
        route: state.lastRouteCoordinates
    });

    // ①軽量エンドポイント(Claude API呼び出しなし、1秒程度)で先に地図・カテゴリを描画する。
    // 説明文(②)は数秒〜十数秒かかるため、無言の待機を防ぐ。
    answerArea.innerHTML = '<div class="ai-loading"><div class="ai-spinner"></div><div>🗺️ きけんなばしょをさがしているよ…</div></div>';
    try {
        const scoreResponse = await fetch(AI_SCORE_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: requestBody
        });
        const scoreData = await scoreResponse.json();
        if (scoreData.risk_points) {
            renderAiMapLayers(scoreData.risk_points, scoreData.accident_points, scoreData.risky_points_facts, scoreData.route_crossings, scoreData.narrow_road_segments);
        }
    } catch (error) {
        // ①が失敗しても②(説明文)は試みる。地図が出ないだけで致命的ではない。
    }

    // ②説明文(Claude API呼び出し、数秒〜十数秒)。①が失敗していても地図以外は継続する。
    answerArea.innerHTML = '<div class="ai-loading"><div class="ai-spinner"></div><div>🤖 AIが せつめいをつくっているよ…</div></div>';
    try {
        const response = await fetch(AI_BACKEND_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: requestBody
        });
        const data = await response.json();

        const box = document.createElement('div');
        box.className = 'ai-answer-text';
        if (data.answer) {
            box.textContent = data.answer;
            // ①が失敗していた場合に備え、②の結果でも地図を描画し直す。
            renderAiMapLayers(data.risk_points, data.accident_points, data.risky_points_facts, data.route_crossings, data.narrow_road_segments);
        } else {
            box.classList.add('ai-answer-error');
            box.textContent = `説明文は取得できなかったけど、地図の危険度は上に出ているよ。エラー: ${data.error || '不明'}`;
        }
        answerArea.replaceChildren(box);
    } catch (error) {
        answerArea.innerHTML = '<div class="ai-answer-text ai-answer-error">説明文を取得できなかったけど、地図の危険度は上に出ているよ。バックエンドが起動しているか確認してね。</div>';
    } finally {
        btn.disabled = false;
        btn.textContent = '🤖 AIにきいてみる';
    }
}

function getDayNightLabel(code) {
    return { '12': '昼間', '22': '夜間' }[code] || code;
}

function getWeatherLabel(code) {
    return { '1': '晴', '2': '曇', '3': '雨', '4': '霧', '5': '雪' }[code] || code;
}

async function geocodeAddress(query) {
    const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=1&countrycodes=jp&accept-language=ja`;
    const res = await fetch(url, { headers: { 'Accept-Language': 'ja' } });
    const data = await res.json();
    return data.length > 0 ? { lat: parseFloat(data[0].lat), lon: parseFloat(data[0].lon), name: data[0].display_name } : null;
}

async function handleSearch() {
    const query = document.getElementById('search-input').value.trim();
    if (!query) return;

    const btn = document.getElementById('search-btn');
    btn.textContent = '検索中...';
    btn.disabled = true;

    try {
        const result = await geocodeAddress(query);
        if (result) {
            state.map.flyTo([result.lat, result.lon], 15, { duration: 1.2 });
            updatePinStatus(`📍 ${result.name.split(',')[0]} に移動しました`);
        } else {
            updatePinStatus('住所が見つかりませんでした。別のキーワードを試してみてね');
        }
    } catch {
        updatePinStatus('検索に失敗しました。ネットワークを確認してね');
    } finally {
        btn.textContent = '検索';
        btn.disabled = false;
    }
}

async function initApp() {
    // ボタンのイベント登録は、地図初期化(initMap)やデータ読込より先に行う。
    // 理由: 以前、initMap内でCDN読み込み失敗などにより例外が発生すると、
    // それ以降のaddEventListener呼び出しが一つも実行されず、画面上は表示されて
    // いるのにどのボタンをクリックしても無反応になる不具合があった。
    // イベント登録を先に済ませておけば、地図側で何が起きてもボタンは機能する。
    document.getElementById('home-mode-btn').addEventListener('click', () => setMode('home'));
    document.getElementById('school-mode-btn').addEventListener('click', () => setMode('school'));
    document.getElementById('reset-btn').addEventListener('click', resetAll);
    document.getElementById('ai-ask-btn').addEventListener('click', askAiTeacher);
    document.getElementById('search-btn').addEventListener('click', handleSearch);
    document.getElementById('search-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleSearch();
    });
    document.getElementById('search-toggle-btn').addEventListener('click', () => {
        const bar = document.getElementById('search-bar');
        const btn = document.getElementById('search-toggle-btn');
        const isOpen = !bar.hidden;
        bar.hidden = isOpen;
        btn.classList.toggle('active', !isOpen);
        if (!isOpen) document.getElementById('search-input').focus();
    });
    document.getElementById('route-mode').addEventListener('change', () => {
        if (state.homeMarker && state.schoolMarker) setupRouting();
    });
    document.getElementById('controls-toggle-btn').addEventListener('click', () => {
        const buttons = document.getElementById('controls-buttons');
        setControlsCollapsed(!buttons.hidden);
    });
    document.getElementById('info-panel-toggle').addEventListener('click', () => {
        const panel = document.getElementById('info-panel');
        const btn = document.getElementById('info-panel-toggle');
        const collapsed = panel.classList.toggle('collapsed');
        btn.textContent = collapsed ? '﹀' : '︿';
        btn.setAttribute('aria-expanded', String(!collapsed));
    });
    document.getElementById('sidebar-toggle-btn').addEventListener('click', () => {
        const collapsed = document.body.classList.toggle('sidebar-collapsed');
        const btn = document.getElementById('sidebar-toggle-btn');
        btn.textContent = collapsed ? '›' : '‹';
        btn.setAttribute('aria-expanded', String(!collapsed));
        // 幅が変わるトランジション(0.2s)が終わってから、Leafletに地図サイズを
        // 再計算させる(以前squished mapの原因になった、コンテナサイズ変更後の
        // invalidateSize()呼び忘れと同じ理由)。
        if (state.map) {
            setTimeout(() => state.map.invalidateSize(), 250);
        }
    });

    try {
        initMap();
    } catch (error) {
        // 地図の初期化に失敗しても(例: CDNの読み込み失敗)、ボタン操作自体は
        // 上で登録済みなので機能する。ユーザーには理由がわかるよう表示する。
        console.error('地図の初期化に失敗しました:', error);
        updatePinStatus('地図の読み込みに失敗しました。ページを再読み込みしてね');
        return;
    }
    await loadAccidentData();
    await loadSchoolsData();
}

document.addEventListener('DOMContentLoaded', initApp);
