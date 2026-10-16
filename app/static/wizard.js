/* 분석 마법사 — 입력 폼 로직(교차로·주차·복합용도·대행업체) + 단계 이동 + 결과 대시보드 전환 */
const BOOT = JSON.parse(document.getElementById("boot").textContent);
const ROLES = BOOT.roles;
const $ = (id) => document.getElementById(id);

function ixHtml() {
  return `
  <fieldset class="ix">
    <legend>교차로</legend>
    <div class="grid">
      <div><label>교차로명 *</label><input class="ix-name" maxlength="60"></div>
      <div><label>신호주기(초) *</label><input class="ix-cycle" type="number" min="1" step="any"></div>
      <div><label>교통량 조사 첨두시</label><select class="ix-peak"><option value="pm">PM 첨두</option><option value="am">AM 첨두</option></select></div>
    </div>
    <div class="small muted" style="margin-top:8px">접근로(차로군)별 — 교통량·포화교통류율은 현장조사/편람 값, 사업 배분율은 해당 접근로에 실리는 사업 유발 첨두교통량 비율</div>
    <div class="aps"></div>
    <div class="actions">
      <button type="button" class="btn small add-ap">+ 접근로 추가</button>
      <button type="button" class="btn small del-ix">교차로 삭제</button>
    </div>
  </fieldset>`;
}
function apHtml() {
  return `
  <div class="row ap">
    <div><label>접근로명</label><input class="ap-name" maxlength="30"></div>
    <div><label>교통량(대/시)</label><input class="ap-vol" type="number" min="0" step="any"></div>
    <div><label>포화교통류율(대/시)</label><input class="ap-sat" type="number" min="1" step="any" value="1800"></div>
    <div><label>녹색시간(초)</label><input class="ap-green" type="number" min="1" step="any"></div>
    <div><label>사업 배분율(%)</label><input class="ap-share" type="number" min="0" max="100" step="any" value="0"></div>
    <button type="button" class="btn small del-ap" aria-label="접근로 삭제">삭제</button>
  </div>`;
}
function staffHtml() {
  const roles = ROLES.map(r => `<label><input type="checkbox" class="st-role" value="${r}"> ${r}</label>`).join("");
  return `
  <div class="staff st">
    <div><label>성명</label><input class="st-name"></div>
    <div><label>소속</label><input class="st-aff"></div>
    <div><label>직책</label><input class="st-pos"></div>
    <div><label>근무기간</label><input class="st-per"></div>
    <div><label>자격명·번호</label><input class="st-qual"></div>
    <button type="button" class="btn small del-st">삭제</button>
    <div class="roles">${roles}
      <label><input type="checkbox" class="st-reg" checked> 등록 기술인력</label></div>
  </div>`;
}
function addIx(data) {
  const wrap = document.createElement("div"); wrap.innerHTML = ixHtml();
  const el = wrap.firstElementChild; $("intersections").appendChild(el);
  el.querySelector(".add-ap").onclick = () => addAp(el);
  el.querySelector(".del-ix").onclick = () => el.remove();
  if (data) {
    el.querySelector(".ix-name").value = data.name; el.querySelector(".ix-cycle").value = data.cycle;
    el.querySelector(".ix-peak").value = data.peak; data.aps.forEach(a => addAp(el, a));
  } else { addAp(el); }
  return el;
}
function addAp(ix, d) {
  const wrap = document.createElement("div"); wrap.innerHTML = apHtml();
  const el = wrap.firstElementChild; ix.querySelector(".aps").appendChild(el);
  el.querySelector(".del-ap").onclick = () => el.remove();
  if (d) { el.querySelector(".ap-name").value = d.name; el.querySelector(".ap-vol").value = d.vol;
    el.querySelector(".ap-sat").value = d.sat; el.querySelector(".ap-green").value = d.green; el.querySelector(".ap-share").value = d.share; }
}
function addStaff() {
  const wrap = document.createElement("div"); wrap.innerHTML = staffHtml();
  const el = wrap.firstElementChild; $("staff").appendChild(el);
  el.querySelector(".del-st").onclick = () => el.remove();
}
$("addIx").onclick = () => addIx();
$("addStaff").onclick = addStaff;

const num = (v) => (v === "" || v === null || v === undefined ? null : Number(v));
const triState = (v) => (v === "yes" ? true : v === "no" ? false : null);

// 사업 유형·복합용도
const USES = BOOT.uses;
function addUse() {
  const row = document.createElement("div"); row.className = "use-row";
  row.style.cssText = "display:grid;gap:8px;grid-template-columns:2fr 1fr auto;align-items:end;margin:6px 0";
  row.innerHTML = `<div><label>용도</label><select class="use-key">${USES.map(u => `<option value="${u.key}">${u.label}</option>`).join("")}</select></div>
    <div><label>면적(㎡)</label><input class="use-area" type="number" min="1" step="any"></div>
    <button type="button" class="btn small del-use">삭제</button>`;
  $("uses").appendChild(row);
  row.querySelector(".del-use").onclick = () => row.remove();
}
$("addUse").onclick = addUse;
function addUnit(d) {
  const row = document.createElement("div"); row.className = "unit-row";
  row.style.cssText = "display:grid;gap:8px;grid-template-columns:1fr 1fr auto;align-items:end;margin:6px 0";
  row.innerHTML = `<div><label>세대당 전용면적(㎡)</label><input class="ut-area" type="number" min="1" step="any"></div>
    <div><label>세대수</label><input class="ut-hh" type="number" min="1" step="1"></div>
    <button type="button" class="btn small del-unit">삭제</button>`;
  $("unitTypes").appendChild(row);
  row.querySelector(".del-unit").onclick = () => row.remove();
  if (d) { row.querySelector(".ut-area").value = d[0]; row.querySelector(".ut-hh").value = d[1]; }
}
$("addUnit").onclick = () => addUnit();
function fillSampleParking() {  // 1,500세대 샘플: 59㎡ 300 + 84㎡ 900 + 114㎡ 300
  $("unitTypes").innerHTML = ""; [[59, 300], [84, 900], [114, 300]].forEach(addUnit);
  $("planned").value = 2000;
}
function syncKind() {
  const k = $("kind").value;
  document.querySelectorAll(".expOnly").forEach(e => e.style.display = k === "expansion" ? "" : "none");
  document.querySelectorAll(".chgOnly").forEach(e => e.style.display = k === "new" ? "none" : "");
  $("gfa").required = false;
}
$("kind").onchange = syncKind; syncKind();

function buildPayload() {
  const kind = $("kind").value;
  const p = {
    project: { name: $("name").value.trim(), address: $("address").value.trim(), land_use: "apartment",
      households: num($("households").value), gross_floor_area_m2: num($("gfa").value), floors: num($("floors").value),
      project_kind: kind,
      other_uses: [...document.querySelectorAll(".use-row")].map(r => ({ use: r.querySelector(".use-key").value,
        area_m2: num(r.querySelector(".use-area").value) })).filter(u => u.area_m2 !== null),
      existing_gfa_m2: kind === "expansion" ? num($("exGfa").value) : null,
      expansion_gfa_m2: kind === "expansion" ? num($("exAdd").value) : null,
      prior_expansion_gfa_m2: kind === "expansion" ? (num($("exPrior").value) || 0) : 0,
      existing_evaluated: kind === "new" ? null : triState($("exEval").value),
      in_evaluated_district: triState($("inDistrict").value),
      years_since_completion: kind === "new" ? null : num($("yrs").value),
      request_abbreviated: $("reqAbbr").checked,
      overview: { permit_laws: $("ov_laws").value.trim(), project_period: $("ov_period").value.trim(),
        urban_planning: $("ov_plan").value.trim(), actual_use: $("ov_use").value.trim(), site_area_m2: num($("ov_site").value),
        building_coverage_pct: num($("ov_bcr").value), floor_area_ratio_pct: num($("ov_far").value),
        basement_floors: num($("ov_base").value), entrances: num($("ov_ent").value), parking_self: num($("ov_pself").value),
        parking_mechanical: num($("ov_pmech").value), parking_accessible: num($("ov_pacc").value),
        parking_women: num($("ov_pwom").value), parking_compact: num($("ov_pcmp").value), parking_tour_bus: num($("ov_ptour").value) },
      unit_types: [...document.querySelectorAll(".unit-row")].map(r => ({ exclusive_area_m2: num(r.querySelector(".ut-area").value),
        households: num(r.querySelector(".ut-hh").value) })).filter(u => u.exclusive_area_m2 !== null && u.households !== null),
      planned_parking_spaces: num($("planned").value), parking_demand_per_household: num($("pdem").value),
      parking_demand_source: $("psrc").value.trim(), rate_basis: $("rateEvidence").checked ? "evidence" : "provisional", rate_direction: $("rdir").value,
      car_occupancy: num($("occ").value), car_occupancy_source: $("occsrc").value.trim(),
      rate_overrides: stripNull({ person_trips_per_household: num($("ro_trips").value), car_share_pct: num($("ro_car").value), taxi_share_pct: num($("ro_taxi").value), bus_share_pct: num($("ro_bus").value),
        subway_share_pct: num($("ro_sub").value), other_share_pct: num($("ro_oth").value),
        am_in_pct: num($("ro_ami").value), am_out_pct: num($("ro_amo").value), pm_in_pct: num($("ro_pmi").value), pm_out_pct: num($("ro_pmo").value),
        source: $("ro_src").value.trim() }),
      min_green_s: num($("mingreen").value), cycle_search_min_s: num($("cmin").value), cycle_search_max_s: num($("cmax").value) },
    background_growth_rate: num($("growth").value) === null ? null : num($("growth").value) / 100,
    intersections: [],
    agency: null,
    use_llm: $("use_llm").checked,
    access_code: $("access_code") ? $("access_code").value : "",
  };
  document.querySelectorAll(".ix").forEach(ix => {
    const name = ix.querySelector(".ix-name").value.trim();
    const aps = [...ix.querySelectorAll(".ap")].map(a => ({
      name: a.querySelector(".ap-name").value.trim(), volume: num(a.querySelector(".ap-vol").value),
      saturation_flow: num(a.querySelector(".ap-sat").value), green_time: num(a.querySelector(".ap-green").value),
      project_share: (num(a.querySelector(".ap-share").value) || 0) / 100,
    })).filter(a => a.name || a.volume !== null || a.green_time !== null);
    if (name || aps.length) p.intersections.push({ name, cycle: num(ix.querySelector(".ix-cycle").value),
      peak: ix.querySelector(".ix-peak").value, approaches: aps });
  });
  // 입력 방식에 따라 한쪽만 보낸다(숨겨진 쪽의 기본 빈 카드가 섞이지 않도록)
  if (document.querySelector('input[name="mode"]:checked').value === "detail") p.intersections = [];
  else p.detailed_intersections = [];
  if (document.querySelector('input[name="mode"]:checked').value === "detail") p.detailed_intersections = buildDetailed();
  const ag = { agency_name: $("ag_name").value, registration_no: $("ag_regno").value, registration_date: $("ag_regdate").value,
    lead_name: $("ag_lead").value, submission_date: $("ag_submit").value, service_period: $("ag_period").value,
    printer: $("ag_printer").value, concept_design_firm: $("ag_concept").value, agency_address: $("ag_addr").value,
    agency_phone: $("ag_phone").value, client_name: $("cl_name").value, client_address: $("cl_addr").value,
    client_phone: $("cl_phone").value, receipt_no: $("ag_receipt").value, management_no: $("ag_mgmt").value,
    review_type: $("ag_rtype").value, change_count: num($("ag_rcount").value) || 0, review_stage: $("ag_stage").value,
    stage_count: num($("ag_scount").value) || 0, cost_basis_attached: $("ag_cost").checked, contract_copy_attached: $("ag_contract").checked,
    staff: [...document.querySelectorAll(".st")].map(s => ({ name: s.querySelector(".st-name").value.trim(),
      affiliation: s.querySelector(".st-aff").value, position: s.querySelector(".st-pos").value,
      period: s.querySelector(".st-per").value, qualification: s.querySelector(".st-qual").value,
      roles: [...s.querySelectorAll(".st-role:checked")].map(c => c.value), registered: s.querySelector(".st-reg").checked }))
      .filter(s => s.name) };
  const anyText = Object.entries(ag).some(([k, v]) => !["review_type", "review_stage"].includes(k) && ((typeof v === "string" && v.trim()) || (k === "staff" && v.length) || v === true || (typeof v === "number" && v > 0)));
  if (anyText) p.agency = ag;
  return p;
}

$("sample").onclick = () => {
  document.querySelector('input[name="mode"][value="simple"]').checked = true; setMode();  // 간이 입력 샘플
  $("name").value = "샘플 단지"; $("address").value = "서울특별시 OO구 OO동"; $("households").value = 1500;
  $("gfa").value = 180000; $("floors").value = 25; $("growth").value = 2;
  fillSampleParking();
  $("intersections").innerHTML = "";
  addIx({ name: "A교차로", cycle: 120, peak: "pm", aps: [
    { name: "N", vol: 400, sat: 1800, green: 40, share: 40 }, { name: "E", vol: 500, sat: 1800, green: 40, share: 10 } ] });
};
/* ───────── 편람 상세 입력 ───────── */
const fld = (label, cls, extra = "") => `<div><label>${label}</label><input class="${cls}" ${extra}></div>`;
const num0 = (label, cls, val = "", extra = "") => fld(label, cls, `type="number" step="any" value="${val}" ${extra}`);
const sel = (label, cls, opts) => `<div><label>${label}</label><select class="${cls}">${opts.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select></div>`;

function dixHtml() {
  return `
  <fieldset class="dix">
    <legend>상세 교차로</legend>
    <div class="grid">
      ${fld("교차로명 *", "dx-name", 'maxlength="60"')}
      ${num0("신호주기 C(초) *", "dx-cycle", "", 'min="1"')}
      ${num0("첨두시간계수 PHF", "dx-phf", "0.95", 'min="0.1" max="1"')}
      ${sel("교통량 조사 첨두시", "dx-peak", [["pm", "PM 첨두"], ["am", "AM 첨두"]])}
    </div>
    <div class="csvbox">
      <label class="btn small">교통량 조사 CSV 불러오기<input type="file" class="csv-file" accept=".csv,.txt,text/csv" hidden></label>
      <a class="small" href="/static/count_template.csv" download>CSV 양식 받기</a>
      <span class="muted small">15분 단위 이동류별 교통량에서 첨두시·PHF·접근로 교통량을 채워요. 엑셀은 CSV로 저장해 올리세요.</span>
      <div class="csv-out small" role="status" aria-live="polite"></div>
    </div>
    <h3 style="margin-top:12px">현시 <span class="muted small">(녹색신호시간 G + 황색, 신호 순서대로)</span></h3>
    <div class="dphases"></div>
    <button type="button" class="btn small add-ph">+ 현시 추가</button>
    <h3 style="margin-top:12px">접근로</h3>
    <div class="daps"></div>
    <div class="actions">
      <button type="button" class="btn small add-dap">+ 접근로 추가</button>
      <button type="button" class="btn small del-dix">교차로 삭제</button>
    </div>
  </fieldset>`;
}
function phHtml() {
  return `<div class="dph">${num0("녹색신호시간 G(초)", "ph-g", "", 'min="1"')}${num0("황색(초)", "ph-y", "3", 'min="0"')}
    <div></div><button type="button" class="btn small del-ph">삭제</button></div>`;
}
function dapHtml() {
  return `
  <div class="dap">
    <div class="g3">
      ${fld("접근로명 *", "dp-name", 'maxlength="30" placeholder="예: EB"')}
      ${sel("교차로 형태", "dp-topo", [["four_way", "네갈래"], ["t_no_left", "세갈래: 직진·우회전만"], ["t_no_right", "세갈래: 직진·좌회전만"], ["y_dedicated", "세갈래: 전용 좌·우회전"]])}
      ${sel("좌회전 CASE", "dp-case", [["1", "1 양방보호·전용 1차로"], ["2", "2 양방보호·전용 2차로"], ["3", "3 비보호·전용 1차로"], ["4", "4 직좌동시·공용 1차로"], ["5", "5 직좌동시·맨 왼쪽 전용+공용(N에 전용 포함)"], ["6", "6 비보호·공용 1차로"]])}
      ${num0("차로수 N (전용 좌회전 제외 · CASE 5는 포함)", "dp-lanes", "2", 'min="1" step="1"')}
      ${num0("좌회전 (vph)", "dp-vl", "0", 'min="0"')}
      ${num0("직진 (vph)", "dp-vt", "0", 'min="0"')}
      ${num0("우회전 (vph)", "dp-vr", "0", 'min="0"')}
      ${sel("직진·우회전 현시", "dp-phase", [["0", "현시 1"]])}
      ${sel("전용 좌회전 현시(CASE 1·2)", "dp-lphase", [["", "해당 없음"]])}
      ${sel("맞은편 접근로(비보호 좌회전)", "dp-opp", [["", "직접 입력"]])}
      ${num0("사업 배분율 좌(%)", "dp-sl", "0", 'min="0" max="100"')}
      ${num0("사업 배분율 직(%)", "dp-st", "0", 'min="0" max="100"')}
      ${num0("사업 배분율 우(%)", "dp-sr", "0", 'min="0" max="100"')}
    </div>
    <details><summary class="small">세부 조건 (U턴·곡선반경·차로폭·중차량·노변마찰·연동…)</summary>
      <div class="g3">
        ${sel("설계속도 직접 입력(km/h)", "dp-dspd", [["", "모름(도로 기능으로 정함)"], ["30", "30"], ["40", "40"], ["50", "50"], ["60", "60"], ["70", "70"], ["80", "80"]])}
        ${sel("도로 기능(설계속도, 도시지역)", "dp-road", [["", "모름(집산도로 50km/h 가정)"], ["arterial", "주간선도로 80km/h"], ["sub_arterial", "보조간선도로 60km/h"], ["collector", "집산도로 50km/h"], ["local", "국지도로 40km/h"]])}
        ${num0("대향직진 Vo (맞은편 미지정 시)", "dp-vo", "0", 'min="0"')}
        ${num0("U턴 (vph)", "dp-u", "0", 'min="0"')}
        ${num0("좌회전 곡선반경(m)", "dp-rad", "25", 'min="1"')}
        ${num0("차로폭(m)", "dp-lw", "3.0", 'min="1"')}
        ${num0("경사(%)", "dp-grade", "0")}
        ${num0("중차량(%)", "dp-heavy", "0", 'min="0" max="100"')}
        ${num0("전용 좌회전 차로수(Y형)", "dp-ll", "1", 'min="0" step="1"')}
        ${num0("전용 우회전 차로수(Y형)", "dp-rl", "1", 'min="0" step="1"')}
        ${num0("이면도로 진입 Ven (vph)", "dp-ven", "0", 'min="0"')}
        ${num0("이면도로 진출 Vex (vph)", "dp-vex", "0", 'min="0"')}
        ${num0("버스 정차대수 (vph)", "dp-vb", "0", 'min="0"')}
        ${num0("정지선~버스정류장(m)", "dp-bl", "75", 'min="0"')}
        ${sel("버스 정차 유형", "dp-bc", [["small", "소: 주택지역"], ["medium", "중: 업무·상업·전철역 주변"], ["large", "대: 이용객 많음"], ["bay", "별도 버스승차대"]])}
        ${num0("노상주차 활동 (vph)", "dp-pkv", "0", 'min="0"')}
        ${num0("횡단보행자 (인/시, 양방향)", "dp-ped", "0", 'min="0"')}
        ${num0("보행 녹색시간 Gp(초)", "dp-gp", "0", 'min="0"')}
        ${num0("상류 링크 길이(m)", "dp-link", "0", 'min="0"')}
        ${num0("순행속도(kph)", "dp-spd", "0", 'min="0"')}
        ${num0("옵셋(초)", "dp-off", "0")}
        ${fld("초기 대기차량 Qb(대) — 차로군=대수, 쉼표 구분", "dp-qb", 'placeholder="예: 공용LT=40"')}
      </div>
      <p class="muted small">차로군 이름: 전용LT, 공용LT, 실질LT, 실질RT, 공용RT, 직진, 통합, 전용RT. 현장에서 관측한 값만 입력하세요(계획분석은 비워 둠 — 편람은 0으로 간주).</p>
      <div class="g3">
        <label class="chk"><input type="checkbox" class="dp-chan"> 우회전 교통섬(도류화)</label>
        <label class="chk"><input type="checkbox" class="dp-pk"> 노상주차 허용</label>
        <label class="chk"><input type="checkbox" class="dp-coord"> 신호 연동 구간(PF 적용)</label>
      </div>
    </details>
    <div class="actions"><button type="button" class="btn small del-dap">접근로 삭제</button></div>
  </div>`;
}
const fromHtml = (html) => { const w = document.createElement("div"); w.innerHTML = html.trim(); return w.firstElementChild; };

function refreshDix(dix) {
  const n = dix.querySelectorAll(".dph").length;
  const phOpts = Array.from({ length: n }, (_, i) => `<option value="${i}">현시 ${i + 1}</option>`).join("");
  const names = [...dix.querySelectorAll(".dap .dp-name")].map(e => e.value.trim()).filter(Boolean);
  dix.querySelectorAll(".dap").forEach(ap => {
    const me = ap.querySelector(".dp-name").value.trim();
    [[".dp-phase", phOpts], [".dp-lphase", `<option value="">해당 없음</option>` + phOpts]].forEach(([c, o]) => {
      const s = ap.querySelector(c), keep = s.value; s.innerHTML = o; if ([...s.options].some(x => x.value === keep)) s.value = keep;
    });
    const so = ap.querySelector(".dp-opp"), keep = so.value;
    so.innerHTML = `<option value="">직접 입력</option>` + names.filter(x => x !== me).map(x => `<option value="${x}">${x}</option>`).join("");
    if ([...so.options].some(x => x.value === keep)) so.value = keep;
  });
}
function addPhase(dix, g, y) {
  const el = fromHtml(phHtml()); dix.querySelector(".dphases").appendChild(el);
  el.querySelector(".del-ph").onclick = () => { el.remove(); refreshDix(dix); };
  if (g !== undefined) { el.querySelector(".ph-g").value = g; el.querySelector(".ph-y").value = y; }
  refreshDix(dix);
}
function addDap(dix, d) {
  const el = fromHtml(dapHtml()); dix.querySelector(".daps").appendChild(el);
  el.querySelector(".del-dap").onclick = () => { el.remove(); refreshDix(dix); };
  el.querySelector(".dp-name").addEventListener("input", () => refreshDix(dix));
  refreshDix(dix);
  if (d) Object.entries(d).forEach(([cls, v]) => { const e = el.querySelector("." + cls); if (e) { if (e.type === "checkbox") e.checked = !!v; else e.value = v; } });
  refreshDix(dix);
  return el;
}
function addDix(d) {
  const el = fromHtml(dixHtml()); $("dintersections").appendChild(el);
  el.querySelector(".add-ph").onclick = () => addPhase(el);
  el.querySelector(".add-dap").onclick = () => addDap(el);
  el.querySelector(".del-dix").onclick = () => el.remove();
  el.querySelector(".csv-file").addEventListener("change", (ev) => loadCounts(el, ev.target));
  if (d) {
    el.querySelector(".dx-name").value = d.name; el.querySelector(".dx-cycle").value = d.cycle;
    el.querySelector(".dx-phf").value = d.phf; el.querySelector(".dx-peak").value = d.peak;
    d.phases.forEach(([g, y]) => addPhase(el, g, y)); d.aps.forEach(a => addDap(el, a));
  } else { addPhase(el); addDap(el); }
  return el;
}
$("addDix").onclick = () => addDix();

/* ───────── 교통량 조사 CSV 불러오기 (서버가 첨두시·PHF를 계산, 화면은 채우기만) ───────── */
async function readCsvText(file) {
  const buf = await file.arrayBuffer();
  try { return new TextDecoder("utf-8", { fatal: true }).decode(buf); }
  catch (_) { return new TextDecoder("euc-kr").decode(buf); }  // 엑셀 한국어 CSV(CP949)
}
function csvMessage(box, text, bad) {
  box.textContent = ""; const s = document.createElement("span"); s.textContent = text; if (bad) s.className = "csv-bad"; box.appendChild(s);
}
async function loadCounts(dix, input) {
  const box = dix.querySelector(".csv-out"), file = input.files[0];
  input.value = "";
  if (!file) return;
  if (file.size > 2_000_000) return csvMessage(box, "파일이 너무 커요(최대 2MB).", true);
  csvMessage(box, "읽는 중…");
  try {
    const r = await fetch("/api/counts/parse", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: await readCsvText(file) }) });
    const j = await r.json();
    if (!r.ok) return csvMessage(box, j.detail || "읽지 못했어요.", true);
    showCounts(dix, box, j);
  } catch (_) { csvMessage(box, "파일을 읽지 못했어요. 다시 시도해 주세요.", true); }
}
function showCounts(dix, box, j) {
  box.textContent = "";
  const head = document.createElement("div");
  head.textContent = `접근로 ${j.approaches.length}개(${j.approaches.join(", ")}), ${j.rows}행` + (j.days > 1 ? `, ${j.days}일 평균` : "") + " — 적용할 첨두를 고르세요.";
  box.appendChild(head);
  ["am", "pm"].forEach(k => {
    const pk = j.peaks[k]; if (!pk) return;
    const b = document.createElement("button"); b.type = "button"; b.className = "btn small csv-apply";
    b.textContent = `${k.toUpperCase()} 첨두 ${pk.start}~${pk.end} 적용 (합계 ${pk.total.toLocaleString("ko-KR")}대/시, PHF ${pk.phf.toFixed(2)})`;
    b.onclick = () => applyCounts(dix, box, k, pk);
    box.appendChild(b);
  });
  (j.warnings || []).forEach(w => { const p = document.createElement("div"); p.className = "muted"; p.textContent = "※ " + w; box.appendChild(p); });
}
function applyCounts(dix, box, key, pk) {
  dix.querySelector(".dx-phf").value = pk.phf; dix.querySelector(".dx-peak").value = key;
  const blank = (ap) => !ap.querySelector(".dp-name").value.trim() && ["dp-vl", "dp-vt", "dp-vr"].every(c => !Number(ap.querySelector("." + c).value));
  let added = 0;
  Object.entries(pk.approaches).forEach(([name, v]) => {
    const vals = { "dp-vl": v.v_left, "dp-vt": v.v_through, "dp-vr": v.v_right, "dp-u": v.u_turn };
    if (v.heavy_pct !== undefined) vals["dp-heavy"] = v.heavy_pct;
    const aps = [...dix.querySelectorAll(".dap")];
    let ap = aps.find(a => a.querySelector(".dp-name").value.trim().toLowerCase() === name.toLowerCase()) || aps.find(blank);
    if (ap) {
      ap.querySelector(".dp-name").value = name;
      Object.entries(vals).forEach(([c, x]) => { ap.querySelector("." + c).value = x; });
      refreshDix(dix);
    } else { addDap(dix, { "dp-name": name, ...vals }); added++; }
  });
  csvMessage(box, `${key.toUpperCase()} 첨두 ${pk.start}~${pk.end} 교통량과 PHF ${pk.phf.toFixed(2)}를 채웠어요. ` +
    "차로수·좌회전 CASE·현시는 CSV에 없으니 접근로마다 확인해 주세요" + (added ? `(새로 만든 접근로 ${added}개 포함).` : "."));
}

function stripNull(o) { Object.keys(o).forEach(k => { if (o[k] === null || o[k] === "" || (typeof o[k] === "number" && Number.isNaN(o[k]))) delete o[k]; }); return o; }
const val = (ap, c) => ap.querySelector("." + c).value;
const chk = (ap, c) => ap.querySelector("." + c).checked;

function parseQueue(text) {  // "공용LT=40, 실질RT=5" → {공용LT: 40, 실질RT: 5} (잘못된 항목은 무시하지 않고 NaN으로 서버가 거부)
  const q = {};
  text.split(",").map(s => s.trim()).filter(Boolean).forEach(pair => {
    const [k, v] = pair.split("=").map(s => s.trim());
    if (k) q[k] = Number(v);
  });
  return Object.keys(q).length ? q : null;
}

function buildDetailed() {
  return [...document.querySelectorAll(".dix")].map(dx => {
    const phases = [...dx.querySelectorAll(".dph")].map(p => stripNull({ green: num(p.querySelector(".ph-g").value), yellow: num(p.querySelector(".ph-y").value) }));
    const approaches = [...dx.querySelectorAll(".dap")].map(ap => stripNull({
      name: val(ap, "dp-name").trim(), topology: val(ap, "dp-topo"), left_case: Number(val(ap, "dp-case")),
      lanes: num(val(ap, "dp-lanes")), v_left: num(val(ap, "dp-vl")), v_through: num(val(ap, "dp-vt")), v_right: num(val(ap, "dp-vr")),
      phase: Number(val(ap, "dp-phase") || 0), left_phase: val(ap, "dp-lphase") === "" ? null : Number(val(ap, "dp-lphase")),
      opposing: val(ap, "dp-opp") || null, opposing_through: num(val(ap, "dp-vo")), u_turn: num(val(ap, "dp-u")),
      left_radius_m: num(val(ap, "dp-rad")), lane_width_m: num(val(ap, "dp-lw")), grade_pct: num(val(ap, "dp-grade")),
      heavy_pct: num(val(ap, "dp-heavy")), left_lanes: num(val(ap, "dp-ll")), right_lanes: num(val(ap, "dp-rl")),
      entering_vph: num(val(ap, "dp-ven")), exiting_vph: num(val(ap, "dp-vex")), bus_stops_vph: num(val(ap, "dp-vb")),
      bus_distance_m: num(val(ap, "dp-bl")), bus_class: val(ap, "dp-bc"), parking_allowed: chk(ap, "dp-pk"),
      parking_vph: num(val(ap, "dp-pkv")), ped_per_hour: num(val(ap, "dp-ped")), ped_green_s: num(val(ap, "dp-gp")),
      right_channelized: chk(ap, "dp-chan"), coordinated: chk(ap, "dp-coord"), link_length_m: num(val(ap, "dp-link")),
      speed_kph: num(val(ap, "dp-spd")), offset_s: num(val(ap, "dp-off")),
      initial_queue: parseQueue(val(ap, "dp-qb")), road_class: val(ap, "dp-road") || null, design_speed_kph: val(ap, "dp-dspd") ? Number(val(ap, "dp-dspd")) : null,
      project_share_left: (num(val(ap, "dp-sl")) || 0) / 100, project_share_through: (num(val(ap, "dp-st")) || 0) / 100,
      project_share_right: (num(val(ap, "dp-sr")) || 0) / 100,
    }));
    return stripNull({ name: dx.querySelector(".dx-name").value.trim(), cycle: num(dx.querySelector(".dx-cycle").value),
      phf: num(dx.querySelector(".dx-phf").value), peak: dx.querySelector(".dx-peak").value, phases, approaches });
  }).filter(d => d.name || d.cycle != null  // 이름·주기·녹색시간·접근로 이름/교통량 중 하나도 안 채운 기본 빈 카드는 보내지 않는다
    || (d.phases || []).some(p => p.green != null)
    || (d.approaches || []).some(a => a.name || a.v_left > 0 || a.v_through > 0 || a.v_right > 0));
}

function setMode() {
  const detail = document.querySelector('input[name="mode"]:checked').value === "detail";
  $("detailMode").hidden = !detail; $("simpleMode").hidden = detail;
}
document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener("change", setMode));

$("sampleFour").onclick = () => {  // 접근로 4개·현시 3개: 개선 시나리오(차로 증설·전용 좌회전·주기 조정)가 여러 개 나오는 예
  $("name").value ||= "샘플 단지"; $("address").value ||= "서울특별시 OO구 OO동"; $("households").value ||= 1500;
  $("gfa").value ||= 180000; $("growth").value = 2;
  if (Number($("households").value) === 1500) fillSampleParking();
  $("dintersections").innerHTML = "";
  const base = { "dp-topo": "four_way", "dp-sl": 3, "dp-st": 10, "dp-sr": 2 };
  const dx = addDix({ name: "사거리 샘플", cycle: 120, phf: 0.95, peak: "pm", phases: [[40, 3], [40, 3], [25, 3]], aps: [
    { ...base, "dp-name": "EB", "dp-case": "6", "dp-lanes": 3, "dp-vl": 120, "dp-vt": 900, "dp-vr": 200, "dp-phase": "0" },
    { ...base, "dp-name": "WB", "dp-case": "6", "dp-lanes": 3, "dp-vl": 100, "dp-vt": 800, "dp-vr": 150, "dp-phase": "0" },
    { ...base, "dp-name": "NB", "dp-case": "4", "dp-lanes": 2, "dp-vl": 150, "dp-vt": 700, "dp-vr": 120, "dp-phase": "1" },
    { ...base, "dp-name": "SB", "dp-case": "4", "dp-lanes": 2, "dp-vl": 140, "dp-vt": 650, "dp-vr": 100, "dp-phase": "1" }] });
  const [eb, wb] = dx.querySelectorAll(".dap");  // 맞은편 접근로는 두 접근로가 모두 생긴 뒤에 지정할 수 있다
  eb.querySelector(".dp-opp").value = "WB"; wb.querySelector(".dp-opp").value = "EB";
};

$("sampleHcm").onclick = () => {
  $("name").value ||= "샘플 단지"; $("address").value ||= "서울특별시 OO구 OO동"; $("households").value ||= 1500;
  $("gfa").value ||= 180000; $("growth").value ||= 2;
  if (Number($("households").value) === 1500) fillSampleParking();  // 세대수를 바꿨다면 주택형 합계가 어긋나므로 채우지 않음
  $("dintersections").innerHTML = "";
  addDix({ name: "A도로×B도로", cycle: 120, phf: 0.95, peak: "pm", phases: [[45, 3], [20, 3], [46, 3]], aps: [{
    "dp-name": "EB", "dp-topo": "four_way", "dp-case": "6", "dp-lanes": 3, "dp-vl": 90, "dp-vt": 600, "dp-vr": 320,
    "dp-phase": "0", "dp-vo": 600, "dp-rad": 12, "dp-lw": 3.3, "dp-heavy": 5, "dp-ven": 23, "dp-vex": 20, "dp-vb": 11,
    "dp-bl": 30, "dp-bc": "medium", "dp-pk": true, "dp-pkv": 10, "dp-ped": 400, "dp-gp": 40,
    "dp-coord": true, "dp-link": 400, "dp-spd": 50, "dp-off": 10, "dp-qb": "공용LT=40",
    "dp-sl": 20, "dp-st": 30, "dp-sr": 10 }] });
};

addIx();
addDix();
setMode();
if ($("logout")) $("logout").onclick = async () => { await fetch("/api/logout", { method: "POST" }); location.href = "/login"; };

/* ═════════ 단계별 마법사 · 결과 대시보드 전환 ═════════ */
const LAST = 5;
let step = 1;
const panels = [...document.querySelectorAll(".panel[data-step]")];
const stepBtns = [...document.querySelectorAll(".st-item")];
const val1 = (id) => { const e = $(id); return e && String(e.value).trim() !== ""; };
const n1 = (id) => (val1(id) ? Number(($(id)).value) : null);
const nf = (x, d = 0) => Number(x).toLocaleString("ko-KR", { maximumFractionDigits: d });

const FIELDS = {
  1: ["name", "address", "households", "gfa", "floors", "ov_laws", "ov_period", "ov_plan", "ov_use", "ov_site", "ov_bcr", "ov_far", "ov_base", "ov_ent"],
  4: ["ag_name", "ag_regno", "ag_regdate", "ag_lead", "ag_submit", "ag_period", "ag_printer", "ag_concept", "ag_addr", "ag_phone", "cl_name", "cl_addr", "cl_phone", "ag_receipt", "ag_mgmt"],
};
const PARK_DETAIL = ["ov_pself", "ov_pmech", "ov_pacc", "ov_pwom", "ov_pcmp", "ov_ptour"];

function unitRows() {
  return [...document.querySelectorAll(".unit-row")].map(r => ({ a: Number(r.querySelector(".ut-area").value), h: Number(r.querySelector(".ut-hh").value) }))
    .filter(u => u.a > 0 && u.h > 0);
}
function ixCount() {
  const detail = document.querySelector('input[name="mode"]:checked').value === "detail";
  return [...document.querySelectorAll(detail ? ".dix" : ".ix")].filter(el => {
    const name = el.querySelector(detail ? ".dx-name" : ".ix-name").value.trim();
    return name || [...el.querySelectorAll(detail ? ".dp-vl,.dp-vt,.dp-vr" : ".ap-vol")].some(i => Number(i.value) > 0);
  }).length;
}
function fillInfo(s) {
  if (s === 1) { const f = FIELDS[1].filter(val1).length; return { n: f, text: `${f}/${FIELDS[1].length} 입력`, done: val1("name") && val1("address") && val1("households") }; }
  if (s === 2) { const u = unitRows().length, d = PARK_DETAIL.filter(val1).length; return { n: u + d + (val1("planned") ? 1 : 0), text: u ? `주택형 ${u}종 · 세부 ${d}/6` : "주택형 미입력", done: u > 0 }; }
  if (s === 3) { const c = ixCount(); return { n: c, text: c ? `교차로 ${c}개` : "교차로 미입력(선택)", done: c > 0 }; }
  if (s === 4) { const f = FIELDS[4].filter(val1).length + document.querySelectorAll(".st-name").length; return { n: f, text: f ? `${f}개 입력` : "미입력(선택)", done: f > 0 }; }
  return { n: 0, text: "요약 후 분석", done: false };
}
function refreshFill() {
  stepBtns.forEach(b => {
    const s = Number(b.dataset.step), info = fillInfo(s);
    const small = b.querySelector("[data-fill]"); if (small) small.textContent = info.text;
    b.classList.toggle("done", s !== step && info.done && s < LAST);
  });
}
function showStep(n, noScroll) {
  step = Math.max(1, Math.min(LAST, n));
  panels.forEach(p => { p.hidden = Number(p.dataset.step) !== step; if (!p.hidden) { p.style.animation = "none"; p.offsetHeight; p.style.animation = ""; } });
  stepBtns.forEach(b => b.classList.toggle("active", Number(b.dataset.step) === step));
  $("prevBtn").style.visibility = step === 1 ? "hidden" : "visible";
  $("nextBtn").hidden = step === LAST;
  $("progTxt").textContent = `${step} / ${LAST} 단계`; $("progBar").style.width = (step / LAST * 100) + "%";
  if (step === LAST) renderSummary();
  refreshFill(); updateHints();
  if (!noScroll) window.scrollTo({ top: 0, behavior: "smooth" });
}
function validateStep1() {
  const bad = ["name", "address", "households"].filter(id => !val1(id) || (id === "households" && Number($(id).value) < 1));
  ["name", "address", "households"].forEach(id => $(id).classList.toggle("invalid", bad.includes(id)));
  if (bad.length) { showStep(1); $(bad[0]).focus(); $(bad[0]).reportValidity && $(bad[0]).reportValidity(); return false; }
  return true;
}
$("nextBtn").onclick = () => { if (step === 1 && !validateStep1()) return; showStep(step + 1); };
$("prevBtn").onclick = () => showStep(step - 1);
stepBtns.forEach(b => b.onclick = () => showStep(Number(b.dataset.step)));
$("form").addEventListener("keydown", (e) => {   // Enter로 실수로 제출되지 않게: 다음 단계로
  if (e.key === "Enter" && e.target.tagName === "INPUT" && !["checkbox", "radio"].includes(e.target.type)) { e.preventDefault(); if (step < LAST) $("nextBtn").click(); }
});
let raf = 0;
const scheduleRefresh = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => { refreshFill(); updateHints(); $("name").classList.remove("invalid"); }); };
$("form").addEventListener("input", scheduleRefresh);
$("form").addEventListener("change", scheduleRefresh);
new MutationObserver(scheduleRefresh).observe($("form"), { childList: true, subtree: true });

/* ── 실시간 미리보기 (최종 판정·계산은 서버가 한다) ── */
const SEOUL_THRESHOLD = 50000;
function setHint(id, cls, icon, title, text) {
  const el = $(id); el.className = "hint-card" + (cls ? " " + cls : "");
  el.querySelector(".hi").textContent = icon; el.querySelector("b").textContent = title; el.querySelector("p").textContent = text;
}
function legalParking(units) {
  let byArea = 0, byHh = 0;
  units.forEach(u => { byArea += u.a * u.h / (u.a <= 85 ? 75 : 65); byHh += u.h * (u.a <= 60 ? 0.7 : 1); });
  return Math.ceil(Math.max(byArea, byHh) - 1e-9);
}
function eligibilityPreview() {
  const kind = $("kind").value;
  if (kind === "expansion") {
    const ex = n1("exGfa"), add = n1("exAdd");
    if (!ex || !add) return null;
    const added = add + (n1("exPrior") || 0), ratio = added / ex, total = ex + added;
    const target = ratio > 0.3 || added >= SEOUL_THRESHOLD;
    return { target, short: `증축 합계 기존의 ${nf(ratio * 100)}%`, text: `증축 합계 ${nf(added)}㎡는 기존의 ${nf(ratio * 100)}% — ${target ? "30% 초과 또는 대상규모 이상이라 대상(준공+증축 합산 " + nf(total) + "㎡)" : "30% 이하이고 대상규모 미만이라 신규 평가 대상 아님"} (기존 건축물이 평가를 받고 준공된 경우 기준).` };
  }
  const g = n1("gfa"); if (!g) return null;
  const mult = g / SEOUL_THRESHOLD;
  return { target: g >= SEOUL_THRESHOLD, short: `연면적 ${nf(g)}㎡ · 기준의 ${nf(mult, 1)}배`, text: `연면적 ${nf(g)}㎡ — 서울시 기준 50,000㎡의 ${nf(mult, 1)}배로 ${g >= SEOUL_THRESHOLD ? "대상" : "대상 아님"}입니다. (복합용도 합산은 분석할 때 판정해요)` };
}
function updateHints() {
  if (!$("hintElig")) return;
  const e = eligibilityPreview();
  if (!e) setHint("hintElig", "", "⚖️", "대상 여부 미리보기", "연면적을 입력하면 서울시 기준(아파트 50,000㎡)과 비교해 알려드려요.");
  else setHint("hintElig", e.target ? "ok" : "warn", e.target ? "✅" : "⚠️", e.target ? "평가 대상이에요" : "평가 대상이 아닐 수 있어요", e.text);
  const u = unitRows();
  if (!u.length) { setHint("hintUnits", "", "🅿️", "법정 주차대수 미리보기", "주택형을 입력하면 예상 법정 대수를 보여드려요. (최종 계산은 분석 시 서버에서 해요.)"); return; }
  const hh = u.reduce((s, x) => s + x.h, 0), H = n1("households"), legal = legalParking(u), pl = n1("planned");
  if (H && hh !== H) { setHint("hintUnits", "bad", "❗", "세대수 합계가 맞지 않아요", `주택형별 세대수 합계 ${nf(hh)}세대 ≠ 사업 개요 세대수 ${nf(H)}세대 — 분석이 거부돼요.`); return; }
  let t = `예상 법정 주차대수 ${nf(legal)}대 (주택건설기준 규정 제27조, 특별시)`, cls = "";
  if (pl != null) { const pct = pl / legal * 100; t += ` · 계획 ${nf(pl)}대는 법정의 ${nf(pct)}%`; if (pl < legal) { cls = "bad"; t += " — 법정 미달"; } else if (pct > 130) { cls = "warn"; t += " — 권장 상한 130% 초과(사유 명시 필요)"; } else cls = "ok"; }
  setHint("hintUnits", cls, "🅿️", `법정 ${nf(legal)}대`, t);
}

/* ── 확인 요약 ── */
function sumCard(small, b, span) {
  const d = document.createElement("div"); d.className = "sum";
  [["small", small], ["b", b], ["span", span]].forEach(([tag, txt]) => { const e = document.createElement(tag); e.textContent = txt; d.appendChild(e); });
  return d;
}
function renderSummary() {
  const g = $("summary"); g.innerHTML = "";
  const e = eligibilityPreview(), u = unitRows(), c = ixCount();
  g.append(
    sumCard("사업", $("name").value.trim() || "(사업명 없음)", `${$("address").value.trim() || "주소 미입력"} · ${val1("households") ? nf(n1("households")) + "세대" : "세대수 미입력"}`),
    sumCard("대상 판정(미리보기)", e ? (e.target ? "대상" : "대상 아님") : "연면적 필요", e ? e.short : "연면적을 입력하면 판정돼요"),
    sumCard("법정 주차(예상)", u.length ? nf(legalParking(u)) + "대" : "주택형 필요", val1("planned") ? `계획 ${nf(n1("planned"))}대` : "계획 주차대수 미입력"),
    sumCard("교차로", c ? c + "개" : "없음", c ? (document.querySelector('input[name="mode"]:checked').value === "detail" ? "편람 상세 입력" : "간이 입력") : "LOS·도표 없이 분석해요"),
    sumCard("개요·표지", `${FIELDS[1].slice(5).filter(val1).length + FIELDS[4].filter(val1).length}칸 입력`, "비운 칸은 보고서에 [기재 필요]로 남아요"),
  );
}

/* ── 샘플·초기화 ── */
function setVals(map) { Object.entries(map).forEach(([id, v]) => { const el = $(id); if (el) el.value = v; }); }
$("sampleAll").onclick = () => {
  document.querySelector('input[name="mode"][value="detail"]').checked = true; setMode();
  $("kind").value = "new"; syncKind();
  setVals({ name: "샘플 단지", address: "서울특별시 OO구 OO동 123", households: 1500, gfa: 180000, floors: 25, growth: 2,
    ov_laws: "건축법 제11조, 주택법 제15조", ov_period: "2027.1 ~ 2029.12", ov_plan: "제3종일반주거지역", ov_site: 30000, ov_bcr: 22, ov_far: 250,
    ov_base: 3, ov_ent: 2, ov_pself: 1800, ov_pmech: 200, ov_pacc: 40, ov_pwom: 60, ov_pcmp: 80, ov_ptour: 0,
    ag_name: "OO교통엔지니어링", ag_lead: "홍길동", cl_name: "OO주택(주)", cl_phone: "02-000-0000", ag_receipt: "2026-0001" });
  $("sampleHcm").onclick();
  showStep(5);
};
$("resetAll").onclick = () => {
  if (!confirm("입력한 내용을 모두 지울까요?")) return;
  $("form").reset();
  ["unitTypes", "uses", "staff", "dintersections", "intersections"].forEach(id => $(id).innerHTML = "");
  addIx(); addDix(); setMode(); syncKind(); showStep(1);
};

/* ── 실행·결과 전환 ── */
const wizardView = $("wizardView"), resultView = $("resultView"), out = $("result");
function toResult() { wizardView.hidden = true; resultView.hidden = false; window.scrollTo({ top: 0 }); }
function toWizard() { resultView.hidden = true; wizardView.hidden = false; window.scrollTo({ top: 0 }); showStep(5, true); }
const LOADING = `<div class="card loading" role="status"><div class="spinner"></div><h3>분석 중이에요…</h3>
  <p class="muted">대상 판정 → 교통량·서비스수준 계산 → 문서 조립 → 지침 점검 순서로 진행해요.<br>보통 몇 초, 실제 LLM을 켠 경우 수십 초가 걸려요.</p></div>`;
$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!validateStep1()) return;
  const btn = $("submit"), old = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> 분석 중…';
  out.innerHTML = LOADING; toResult();
  try {
    const res = await fetch("/ui/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildPayload()) });
    out.innerHTML = await res.text();
  } catch (err) {
    out.innerHTML = '<div class="card err" role="alert"><h2>서버에 연결할 수 없습니다</h2><p>잠시 후 다시 시도하세요.</p><button type="button" class="btn" data-action="edit">← 입력 수정</button></div>';
  } finally { btn.disabled = false; btn.innerHTML = old; window.scrollTo({ top: 0 }); }
});
out.addEventListener("click", (e) => {
  const t = e.target.closest(".tab, [data-tab-link]"), a = e.target.closest("[data-action]");
  if (a && a.dataset.action === "edit") return toWizard();
  if (a && a.dataset.action === "print") return window.print();
  if (!t) return;
  const id = t.dataset.tab || t.dataset.tabLink;
  out.querySelectorAll(".tab").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === id)));
  out.querySelectorAll(".pane").forEach(p => p.classList.toggle("on", p.dataset.pane === id));
  const tabs = out.querySelector(".tabs"); if (tabs) tabs.scrollIntoView({ behavior: "smooth", block: "start" });
});

showStep(1, true);
