// 성인·소아 계산기 토글: 환자 정보(나이·키·체중)는 그대로 두고 약물 카드만 바꿈.
// 고른 모드는 주소(?mode=adult|ped)와 이 브라우저(localStorage)에 기억함.
(function () {
  const root = document.querySelector(".calc");
  const buttons = root.querySelectorAll(".cx-mode-btn");
  const hint = document.getElementById("modeHint");
  const TITLES = { adult: "Drug Calculator", ped: "Pediatric Calculator" };
  const PED_AGE = 15; // 이보다 어리면 성인 모드에서 소아 모드를 권함

  function remember(mode) {
    try { localStorage.setItem("calc-mode", mode); } catch (e) { /* 저장 못 해도 동작 */ }
  }

  function updateHint() {
    const age = parseFloat(document.getElementById("age").value);
    hint.hidden = !(root.dataset.mode === "adult" && age >= 0 && age < PED_AGE);
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
      remember(mode);
      if (document.getElementById("weight").value) calculate();
    }
    updateHint();
  }

  function calculate() {
    if (root.dataset.mode === "ped") window.PedCalc.calculateAll();
    else window.AdultCalc.calculateAll();
  }

  buttons.forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  hint.addEventListener("click", () => setMode("ped"));
  document.getElementById("age").addEventListener("input", updateHint);

  // 주소에 mode 가 없으면 이 브라우저에서 마지막으로 쓴 모드
  let initial = root.dataset.mode;
  if (!new URLSearchParams(window.location.search).has("mode")) {
    try { initial = localStorage.getItem("calc-mode") || initial; } catch (e) { /* 기본값 */ }
  }
  setMode(initial, { initial: true });

  window.CalcPage = { calculate, setMode };
})();
