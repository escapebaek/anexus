// 성인 마취 약물 계산기 (예전 escapebaek.github.io/anesthesia-calculator 에서 옮김)
function calculateAll() {
  const weight = parseFloat(document.getElementById("weight").value);
  if (!weight || weight <= 0) {
    alert("Please enter a valid patient weight.");
    return;
  }

  const getValue = (id) => parseFloat(document.getElementById(id).value);

  // --- Calculations ---
  updateResult(
    "nep",
    (60 * weight * getValue("nep_dr")) / getValue("nep_conc")
  );
  updateResult(
    "epi",
    (60 * weight * getValue("epi_dr")) / getValue("epi_conc")
  );
  updateResult(
    "dopa",
    (60 * weight * getValue("dopa_dr")) / (getValue("dopa_conc") * 1000)
  );
  updateResult(
    "dobu",
    (60 * weight * getValue("dobu_dr")) / (getValue("dobu_conc") * 1000)
  );
  updateResult(
    "ntg",
    (60 * weight * getValue("ntg_dr")) / (getValue("ntg_conc") * 1000)
  );
  updateResult(
    "snp",
    (60 * weight * getValue("snp_dr")) / (getValue("snp_conc") * 1000)
  );
  updateResult(
    "vaso1",
    (60 * getValue("vaso_dr1")) / getValue("vaso_conc")
  );
  updateResult(
    "vaso2",
    (weight * getValue("vaso_dr2")) / getValue("vaso_conc")
  );
  updateResult("ppf1", (weight * 6) / getValue("ppf_conc"));
  updateResult("ppf2", (weight * 12) / getValue("ppf_conc"));
  updateResult("rftn1", (weight * 0.1 * 60) / getValue("rftn_conc"));
  updateResult("rftn2", (weight * 1 * 60) / getValue("rftn_conc"));
  updateResult("suftn1", (weight * 0.5) / getValue("suftn_conc"));
  updateResult("suftn2", (weight * 1.5) / getValue("suftn_conc"));
  updateResult("txa1", (weight * 10 * 3) / getValue("txa_conc"));
  updateResult("txa2", (weight * 1) / getValue("txa_conc"));
  updateResult(
    "ca_bolus",
    (getValue("ca_bolus") * 1000) / getValue("ca_conc")
  );
  updateResult(
    "ca_cont",
    (weight * getValue("ca_dr")) / getValue("ca_conc")
  );
  updateResult(
    "mg_bolus",
    (getValue("mg_bolus") * 1000) / getValue("mg_conc")
  );
  updateResult(
    "mg_infusion",
    (getValue("mg_infusion") * 1000) / getValue("mg_conc")
  );
  updateResult(
    "sbic",
    (weight * getValue("sbic_dr")) / getValue("sbic_conc")
  );
  updateResult(
    "phen_bolus",
    getValue("phen_bolus") / getValue("phen_conc")
  );
  updateResult(
    "phen_cont",
    (60 * weight * getValue("phen_dr")) / getValue("phen_conc")
  );
  updateResult("dant_bolus", (weight * 2.5) / getValue("dant_conc"));
  updateResult("dant_max", (weight * 10.0) / getValue("dant_conc"));
  updateResult(
    "dant_vial",
    Math.ceil((weight * 2.5) / 20)
  );
  updateResult(
    "dant_infusion",
    (weight * getValue("dant_infusion")) / getValue("dant_conc")
  );
  updateResult(
    "lido_bolus",
    (weight * getValue("lido_bolus")) / getValue("lido_conc")
  );
  updateResult(
    "lido_infusion",
    (getValue("lido_infusion") / getValue("lido_inf_conc")) * 60
  );
  updateResult(
    "atropine_bolus",
    getValue("atropine_bolus") / getValue("atropine_conc")
  );
  updateResult("atropine_max", 3.0 / getValue("atropine_conc"));
  // Amiodarone — 성인 ACLS: 체중과 무관한 고정 용량
  updateResult(
    "amio_load_vol",
    getValue("amio_load") / getValue("amio_load_conc")
  );
  updateResult(
    "amio_load_rate",
    (getValue("amio_load") / getValue("amio_load_conc")) *
      (60 / getValue("amio_load_min"))
  );
  updateResult("amio_inf1", (1 * 60) / getValue("amio_conc"));
  updateResult("amio_inf2", (0.5 * 60) / getValue("amio_conc"));
}

function updateResult(baseId, value) {
  const resultEl = document.getElementById(baseId + "_result");
  const itemEl = document.getElementById(baseId + "_result_item");

  if (resultEl && !isNaN(value) && value !== Infinity) {
    resultEl.textContent =
      baseId === "dant_vial" ? String(value) : value.toFixed(2);
    if (itemEl) {
      itemEl.classList.add("is-result");
    }
  } else if (resultEl) {
    resultEl.textContent = "-";
    if (itemEl) {
      itemEl.classList.remove("is-result");
    }
  }
}

// ===== MIX (조제 방법) =====
// 농도 입력값에 맞춰 "앰플 + 희석액 = 총량" 을 자동 계산합니다.
//  amt/unit/vol : 앰플(바이알) 1개의 약물량·단위·부피 (분말이면 vol 0)
//  n            : 표준 조제에 쓰는 앰플 수
//  cu           : 농도 입력칸의 단위 (…/ml)
//  dil          : 희석액
//  std          : 표준 조제 (참고: anesthesia-manual 병동/ICU 기준)
//  syr          : 50ml 시린지 조제법도 함께 표시
const MIX = {
  nep_conc: { amt: 4, unit: "mg", vol: 4, n: 1, cu: "mcg", label: "4mg/4ml amp", dil: "D5W", syr: true,
    std: "1@ + D5W 196ml = 200ml (20mcg/ml)" },
  epi_conc: { amt: 1, unit: "mg", vol: 1, n: 1, cu: "mcg", label: "1mg/1ml amp", dil: "NS", syr: true,
    std: "1@ + NS 49ml = 50ml (20mcg/ml)" },
  dopa_conc: { amt: 200, unit: "mg", vol: 5, n: 1, cu: "mg", label: "200mg/5ml amp", dil: "D5W", syr: true,
    std: "1@ + D5W 195ml = 200ml (1mg/ml) · premix 400mg/200ml(2mg/ml) 그대로" },
  dobu_conc: { amt: 250, unit: "mg", vol: 5, n: 1, cu: "mg", label: "250mg/5ml amp", dil: "D5W", syr: true,
    std: "1@ + D5W 245ml = 250ml (1mg/ml) · premix 500mg/250ml(2mg/ml) 그대로" },
  ntg_conc: { amt: 50, unit: "mg", vol: 50, n: 1, cu: "mg", label: "50mg/50ml vial", dil: "D5W", syr: true,
    std: "1ⓥ + D5W 200ml = 250ml (0.2mg/ml)", note: "non-PVC bag·line" },
  snp_conc: { amt: 50, unit: "mg", vol: 2, n: 1, cu: "mg", label: "50mg/2ml vial", dil: "D5W", syr: true,
    std: "1ⓥ + D5W 248ml = 250ml (0.2mg/ml)", note: "only D5W · 차광" },
  vaso_conc: { amt: 20, unit: "unit", vol: 1, n: 1, cu: "unit", label: "20unit/1ml amp", dil: "NS (또는 D5W)", syr: true,
    std: "1@ + NS 99ml = 100ml (0.2unit/ml)" },
  ppf_conc: { neat: true, cu: "mg",
    std: "원액 사용 — 1% 10mg/ml · 2% 20mg/ml (희석하지 않음)" },
  rftn_conc: { amt: 1, unit: "mg", vol: 0, n: 1, cu: "mcg", label: "1mg vial(분말)", dil: "NS",
    std: "1ⓥ(1mg) + NS 50ml = 50ml (20mcg/ml)" },
  suftn_conc: { amt: 250, unit: "mcg", vol: 5, n: 1, cu: "mcg", label: "250mcg/5ml amp", dil: "NS",
    std: "1@ + NS 45ml = 50ml (5mcg/ml)" },
  txa_conc: { amt: 500, unit: "mg", vol: 5, n: 2, cu: "mg", label: "500mg/5ml vial", dil: "NS",
    std: "2ⓥ + NS 90ml = 100ml (10mg/ml)" },
  ca_conc: { amt: 2, unit: "g", vol: 20, n: 1, cu: "mg", label: "2g/20ml amp", dil: "NS 또는 D5W",
    std: "10% 원액(100mg/ml) 또는 동량 희석", note: "Bicarbonate와 혼합 금지(침전)" },
  mg_conc: { amt: 2, unit: "g", vol: 20, n: 1, cu: "mg", label: "10% 2g/20ml amp", dil: "NS 또는 D5W",
    std: "10% 원액(100mg/ml) · C.I.는 희석" },
  sbic_conc: { amt: 20, unit: "mEq", vol: 20, n: 1, cu: "mEq", label: "8.4% 20mEq/20ml", dil: "NS 또는 D5W",
    std: "원액(1mEq/ml) 또는 동량 희석(0.5mEq/ml)", note: "Ca·catecholamine과 같은 라인 금지" },
  phen_conc: { amt: 10, unit: "mg", vol: 1, n: 1, cu: "mcg", label: "10mg/1ml vial", dil: "NS", syr: true,
    std: "1ⓥ + NS 99ml = 100ml (100mcg/ml)" },
  dant_conc: { amt: 20, unit: "mg", vol: 0, n: 1, cu: "mg", label: "20mg vial(분말)", dil: "멸균주사용수",
    std: "1ⓥ(20mg) + 멸균주사용수 60ml (0.333mg/ml)", note: "NS·D5W로 재구성 금지 — 멸균주사용수만" },
  lido_conc: { amt: 400, unit: "mg", vol: 20, n: 1, cu: "mg", label: "2% 400mg/20ml", dil: "D5W", title: "Bolus",
    std: "원액 2%(20mg/ml) 그대로" },
  lido_inf_conc: { amt: 400, unit: "mg", vol: 20, n: 1, cu: "mg", label: "2% 400mg/20ml", dil: "D5W", title: "C.I.",
    std: "1ⓥ + D5W 80ml = 100ml (4mg/ml)" },
  atropine_conc: { amt: 0.5, unit: "mg", vol: 1, n: 1, cu: "mg", label: "0.5mg/1ml amp", dil: "NS",
    std: "원액 그대로 IV push" },
  amio_load_conc: { amt: 150, unit: "mg", vol: 3, n: 1, cu: "mg", label: "150mg/3ml amp", dil: "D5W", title: "Load",
    std: "1@ + D5W 97ml = 100ml (1.5mg/ml) · 10분 이상", note: "only D5W" },
  amio_conc: { amt: 150, unit: "mg", vol: 3, n: 6, cu: "mg", label: "150mg/3ml amp", dil: "D5W", title: "C.I.",
    std: "6@ + D5W 432ml = 450ml (2mg/ml)", note: "only D5W · &gt;2mg/ml은 중심정맥" }
};

const MASS = { mcg: 0.001, mg: 1, g: 1000 };
function convUnit(v, from, to) {
  if (from === to) return v;
  if (MASS[from] && MASS[to]) return (v * MASS[from]) / MASS[to];
  return NaN; // unit·mEq 는 서로 환산 불가
}
const fmt = (x) =>
  String(x >= 20 ? Math.round(x * 10) / 10 : Math.round(x * 100) / 100);

function mixText(m, conc) {
  const std = '<span class="cx-mix-sub">표준: ' + m.std + (m.note ? " · " + m.note : "") + "</span>";
  if (!(conc > 0)) return "농도를 입력하세요" + std;
  if (m.neat) return "<b>원액 사용</b>" + std;

  const amtTotal = convUnit(m.amt * m.n, m.unit, m.cu);
  const total = amtTotal / conc;
  const drugVol = m.vol * m.n;
  const ampTxt = m.n + (m.vol > 0 && !/vial/.test(m.label) ? "@" : "ⓥ") + "(" + m.label + ")";
  let line;
  if (m.vol > 0 && Math.abs(total - drugVol) < drugVol * 0.001) {
    line = "<b>원액 그대로</b> (" + m.label + ")";
  } else if (total < drugVol) {
    const stock = convUnit(m.amt, m.unit, m.cu) / m.vol;
    line = '<span class="cx-mix-warn">⚠ 원액 농도가 ' + fmt(stock) + " " + m.cu +
      "/ml 이므로 그보다 진하게 조제할 수 없습니다</span>";
  } else {
    line = "<b>" + ampTxt + " + " + m.dil + " " + fmt(total - drugVol) + "ml</b> = 총 " + fmt(total) + "ml";
  }
  // 50ml 시린지 조제 (앰플 일부만 사용)
  let syr = "";
  if (m.syr && m.vol > 0) {
    const stock = convUnit(m.amt, m.unit, m.cu) / m.vol;
    const draw = (conc * 50) / stock;
    if (draw < 50 && Math.abs(total - 50) > 0.5) {
      syr = '<span class="cx-mix-sub">50ml 시린지: 원액 ' + fmt(draw) + "ml + " + m.dil + " " + fmt(50 - draw) + "ml</span>";
    }
  }
  return line + syr + std;
}

function updateMixes() {
  Object.keys(MIX).forEach((id) => {
    const el = document.getElementById(id + "_mix");
    const input = document.getElementById(id);
    if (!el || !input) return;
    el.innerHTML = mixText(MIX[id], parseFloat(input.value));
    const summary = el.parentElement.querySelector("summary");
    if (summary) summary.textContent = "MIX 조제법" + (MIX[id].title ? " · " + MIX[id].title : "");
  });
}

// 약물 사진: static/img/drugs/약물ID.jpg (경로 앞부분은 페이지의 data-img-base)
const IMG_BASE = document.querySelector(".calc").dataset.imgBase;
const drugImages = {
  'nep': { name: 'Norepinephrine (NEP)', image: 'images/nep.jpg' },
  'epi': { name: 'Epinephrine (EPI)', image: 'images/epi.jpg' },
  'dopa': { name: 'Dopamine (DOPA)', image: 'images/dopa.jpg' },
  'dobu': { name: 'Dobutamine (DOBU)', image: 'images/dobu.jpg' },
  'ntg': { name: 'Nitroglycerin (NTG)', image: 'images/ntg.jpg' },
  'snp': { name: 'Nitroprusside (SNP)', image: 'images/snp.jpg' },
  'vaso': { name: 'Vasopressin (VASO)', image: 'images/vaso.jpg' },
  'ppf': { name: 'Propofol (PPF)', image: 'images/ppf.jpg' },
  'rftn': { name: 'Remifentanil (RFTN)', image: 'images/rftn.jpg' },
  'suftn': { name: 'Sufentanil (SuFTN)', image: 'images/suftn.jpg' },
  'txa': { name: 'Tranexamic Acid (TXA)', image: 'images/txa.jpg' },
  'ca': { name: 'Calcium Gluconate', image: 'images/ca.jpg' },
  'mg': { name: 'Magnesium Sulfate', image: 'images/mg.jpg' },
  'sbic': { name: 'Sodium Bicarbonate', image: 'images/sbic.jpg' },
  'phen': { name: 'Phenylephrine', image: 'images/phen.jpg' },
  'dant': { name: 'Dantrolene', image: 'images/dant.jpg' },
  'lido': { name: 'Lidocaine', image: 'images/lido.jpg' },
  'atropine': { name: 'Atropine', image: 'images/atropine.jpg' },
  'amio': { name: 'Amiodarone', image: 'images/amio.jpg' }
};

function openDrugModal(drugId) {
  const drug = drugImages[drugId];
  if (!drug) return;
  const src = IMG_BASE + drug.image.replace("images/", "");

  const modal = document.getElementById('drugModal');
  const title = document.getElementById('drugModalTitle');
  const body = document.getElementById('drugModalBody');

  title.textContent = drug.name;

  // 이미지 로드 시도
  const img = new Image();
  img.onload = function() {
    body.innerHTML = `<img src="${src}" alt="${drug.name}">`;
  };
  img.onerror = function() {
    // 이미지가 없을 경우 플레이스홀더 표시
    body.innerHTML = `
      <div class="cx-placeholder">
        <i class="fas fa-image"></i>
        <p>이미지가 아직 등록되지 않았습니다</p>
        <small>${drugId}.jpg</small>
      </div>
    `;
  };
  img.src = src;

  modal.classList.add('is-open');
  document.body.style.overflow = 'hidden';
}

function closeDrugModal() {
  const modal = document.getElementById('drugModal');
  modal.classList.remove('is-open');
  document.body.style.overflow = '';
}

function closeDrugModalOnOverlay(event) {
  if (event.target.id === 'drugModal') {
    closeDrugModal();
  }
}

// ESC 키로 모달 닫기
document.addEventListener('keydown', function(event) {
  if (event.key === 'Escape') {
    closeDrugModal();
  }
});

document.addEventListener("DOMContentLoaded", function () {
  const inputs = document.querySelectorAll(".calc input");
  let calculationTimeout;

  updateMixes();

  inputs.forEach((input) => {
    input.addEventListener("input", () => {
      updateMixes();
      clearTimeout(calculationTimeout);
      calculationTimeout = setTimeout(() => {
        if (document.getElementById("weight").value) {
          calculateAll();
        }
      }, 300);
    });
  });
});
