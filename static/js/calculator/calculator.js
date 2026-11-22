// 성인·소아 계산기 공통 화면 기능 (계산식은 drug.js / pediatric.js)
//  1) 토글: 환자 정보(나이·키·체중)는 그대로 두고 약물 카드만 바꿈. 모드는 주소(?mode=)와 브라우저에 기억
//  2) 종류 칩: 지금 모드의 약물 묶음(.cx-group)으로 바로 이동, 보고 있는 묶음 표시
//  3) 내 농도: 바꾼 조제 농도는 이 브라우저에 기억 (기본값으로 되돌리기 가능)
//  4) 범위 경고: 권장 범위(data-range)를 벗어나거나 농도가 기본값과 자릿수만큼 다르면 입력칸에 경고
(function () {
  const root = document.querySelector(".calc");
  const buttons = root.querySelectorAll(".cx-mode-btn");
  const hint = document.getElementById("modeHint");
  const chips = document.getElementById("calcChips");
  const concNote = document.getElementById("concNote");
  const TITLES = { adult: "Drug Calculator", ped: "Pediatric Calculator" };
  const GRID = { adult: "adultGrid", ped: "drugGrid" };
  const PED_AGE = 15;          // 이보다 어리면 성인 모드에서 소아 모드를 권함
  const CONC_KEY = "calc-conc-v1";
  const FAR = 5;               // 권장 범위에서 이 배수 이상 벗어나면 자릿수 실수로 보고 빨간 경고
  const CONC_FAR = 10;         // 농도는 희석해 쓰는 경우가 많아(예: Ketamine 50→10) 자릿수 하나(10배)부터만
  let ready = false;

  // ---------- 저장 (막혀 있어도 계산기는 그대로 동작) ----------
  function load(key, fallback) {
    let v = null;
    try { v = localStorage.getItem(key); } catch (e) { return fallback; }
    if (v === null) return fallback;
    try { return JSON.parse(v); } catch (e) { return v; }   // 예전에 글자 그대로 저장한 값 (calc-mode)
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 저장 못 해도 동작 */ }
  }

  const currentGrid = () => document.getElementById(GRID[root.dataset.mode]);

  // ---------- 1) 토글 ----------
  function updateHint() {
    const age = parseFloat(document.getElementById("age").value);
    hint.hidden = !(root.dataset.mode === "adult" && age >= 0 && age < PED_AGE);
  }

  function calculate() {
    if (root.dataset.mode === "ped") window.PedCalc.calculateAll();
    else window.AdultCalc.calculateAll();
  }

  function setMode(mode, opts) {
    mode = mode === "ped" ? "ped" : "adult";
    root.dataset.mode = mode;
    buttons.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.mode === mode)));
    document.title = TITLES[mode] + " · ANExUS";
    if (!(opts && opts.initial)) {
      const url = new URL(window.location.href);
      url.searchParams.set("mode", mode);
      history.replaceState(null, "", url);
      save("calc-mode", mode);
      if (document.getElementById("weight").value) calculate();
    }
    updateHint();
    if (ready) { buildChips(); updateConcNote(); }
  }

  // ---------- 2) 종류 칩 ----------
  function buildChips() {
    const groups = [...currentGrid().querySelectorAll(".cx-group")];
    chips.innerHTML = groups.map((g) =>
      `<button type="button" class="cx-chip" data-cat="${g.dataset.cat}" data-target="${g.id}">` +
      `${g.dataset.label}<small>${g.querySelectorAll(".cx-card").length}</small></button>`).join("");
    markActiveChip();
  }

  function markActiveChip() {
    const groups = [...currentGrid().querySelectorAll(".cx-group")];
    const line = chips.getBoundingClientRect().bottom + 24;
    let active = groups[0];
    groups.forEach((g) => { if (g.getBoundingClientRect().top <= line) active = g; });
    // 페이지 끝이라 마지막 묶음이 위로 못 올라오면, 화면에 들어온 마지막 묶음을 표시
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
      groups.forEach((g) => { if (g.getBoundingClientRect().top < window.innerHeight * 0.6) active = g; });
    }
    chips.querySelectorAll(".cx-chip").forEach((c) => {
      const on = active && c.dataset.target === active.id;
      c.classList.toggle("is-active", on);
      if (on && chips.scrollWidth > chips.clientWidth) {
        // 모바일: 칩 줄이 가로로 넘치면 보고 있는 칩이 보이게
        const left = c.offsetLeft - chips.clientWidth / 2 + c.clientWidth / 2;
        chips.scrollTo({ left, behavior: "smooth" });
      }
    });
  }

  chips.addEventListener("click", (e) => {
    const chip = e.target.closest(".cx-chip");
    if (!chip) return;
    const group = document.getElementById(chip.dataset.target);
    const top = group.getBoundingClientRect().top + window.scrollY - chips.getBoundingClientRect().height
      - (parseFloat(getComputedStyle(chips).top) || 0) - 8;
    window.scrollTo({ top, behavior: "smooth" });
  });

  let scrollTick = false;
  window.addEventListener("scroll", () => {
    if (scrollTick) return;
    scrollTick = true;
    requestAnimationFrame(() => { scrollTick = false; markActiveChip(); });
  }, { passive: true });

  // ---------- 3) 내 농도 ----------
  const isConc = (el) => el.matches && el.matches(".cx-groups input[id$='_conc']");
  const concInputs = () => [...root.querySelectorAll(".cx-groups input[id$='_conc']")];

  function storeConc(input) {
    const saved = load(CONC_KEY, {});
    const value = parseFloat(input.value);
    if (!(value > 0) || value === parseFloat(input.defaultValue)) delete saved[input.id];
    else saved[input.id] = value;
    save(CONC_KEY, saved);
    updateConcNote();
  }

  function updateConcNote() {
    const n = currentGrid().querySelectorAll(".cx-input.is-custom").length;
    document.getElementById("concCount").textContent = n;
    concNote.hidden = n === 0;
  }

  function resetConc() {
    const saved = load(CONC_KEY, {});
    currentGrid().querySelectorAll(".cx-groups input[id$='_conc']").forEach((input) => {
      input.value = input.defaultValue;
      delete saved[input.id];
      checkInput(input);
    });
    save(CONC_KEY, saved);
    updateConcNote();
    window.AdultCalc.updateMixes();
    window.PedCalc.updateMixes();
    if (root.dataset.mode === "ped" || document.getElementById("weight").value) calculate();
  }
  document.getElementById("concReset").addEventListener("click", resetConc);

  // ---------- 4) 범위 경고 ----------
  const num = (x) => String(+x.toFixed(4));

  function warnBox(input) {
    const wrap = input.closest(".cx-input");
    let box = wrap.nextElementSibling;
    if (!box || !box.classList.contains("cx-warn")) {
      box = document.createElement("p");
      box.className = "cx-warn";
      box.setAttribute("role", "status");
      wrap.after(box);
    }
    return box;
  }

  function checkInput(input) {
    const wrap = input.closest(".cx-input");
    if (!wrap) return;
    const value = parseFloat(input.value);
    let level = "", text = "";
    if (input.dataset.range && value > 0) {
      const [lo, hi] = input.dataset.range.split(",").map(Number);
      if (value > hi * FAR || value < lo / FAR) {
        level = "danger";
        text = `권장 ${num(lo)}–${num(hi)} 에서 크게 벗어났어요 · 자릿수 확인`;
      } else if (value > hi || value < lo) {
        level = "warn";
        text = `권장 범위 ${num(lo)}–${num(hi)} 밖이에요`;
      }
    }
    if (isConc(input)) {
      const def = parseFloat(input.defaultValue);
      const custom = value > 0 && value !== def;
      wrap.classList.toggle("is-custom", custom);
      if (custom && (value >= def * CONC_FAR || value <= def / CONC_FAR)) {
        level = "danger";
        text = `기본 농도 ${num(def)} 의 ${num(value / def)}배예요 · 자릿수 확인`;
      }
    }
    wrap.classList.toggle("is-warn", level === "warn");
    wrap.classList.toggle("is-danger", level === "danger");
    const existing = wrap.nextElementSibling && wrap.nextElementSibling.classList.contains("cx-warn")
      ? wrap.nextElementSibling : null;
    if (!level) { if (existing) existing.remove(); return; }
    const box = existing || warnBox(input);
    box.className = "cx-warn is-" + level;
    box.innerHTML = `<i class="fas fa-exclamation-${level === "danger" ? "circle" : "triangle"}"></i> ${text}`;
  }

  root.addEventListener("input", (e) => {
    if (!e.target.matches(".cx-groups input")) return;
    checkInput(e.target);
    if (isConc(e.target)) storeConc(e.target);
  });
  root.addEventListener("change", (e) => {   // 소아 농도 설정 창에서 저장한 값
    if (!isConc(e.target)) return;
    checkInput(e.target);
    storeConc(e.target);
  });

  // ---------- 시작 ----------
  buttons.forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  hint.addEventListener("click", () => setMode("ped"));
  document.getElementById("age").addEventListener("input", updateHint);

  // 주소에 mode 가 없으면 이 브라우저에서 마지막으로 쓴 모드
  let initial = root.dataset.mode;
  if (!new URLSearchParams(window.location.search).has("mode")) initial = load("calc-mode", initial);
  setMode(initial, { initial: true });

  // 소아 카드는 pediatric.js 가 DOMContentLoaded 에 그리므로 그 뒤에 (이 스크립트가 마지막에 등록됨)
  document.addEventListener("DOMContentLoaded", () => {
    const saved = load(CONC_KEY, {});
    concInputs().forEach((input) => {
      if (saved[input.id] > 0) input.value = saved[input.id];
    });
    root.querySelectorAll(".cx-groups input").forEach(checkInput);
    window.AdultCalc.updateMixes();
    window.PedCalc.updateMixes();
    window.PedCalc.calculateAll();
    ready = true;
    buildChips();
    updateConcNote();
  });

  window.CalcPage = { calculate, setMode };
})();
