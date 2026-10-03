// 소아 마취 계산기 (예전 escapebaek.github.io/pediatric-anesthesia-calculator 에서 옮김)
// ===== Drug configurations =====
//  cu    : 용량·농도의 질량 단위 (mg / mcg) — 농도 입력칸은 cu/ml
//  conc  : 기본 농도 (조제 후 주사기 농도)
//  doses : 1회 용량. d = 체중당 용량, max = 1회 상한(cu),
//          pick(w, age) 가 있으면 체중·나이에 따라 { d | fixed, l } 을 고름,
//          over = 분 단위 주입 시간 (loading 속도 ml/hr 표시)
//  inf   : 지속주입 (Rate 입력 → ml/hr). conc 가 있으면 별도 주사기 농도
//  mix   : 조제 방법 (아래 mixText 참고)
//  ageWarn : [{ lt: 나이(세), msg }] — 해당 나이 미만이면 카드에 경고 표시
//  용량·조제 기준: anesthesia-manual 소아 탭(부서 기준) + 일반 소아 참고값
const DRUGS = [
  {
    id: "propofol", name: "Propofol (PPF, 1%)", icon: "fa-syringe", cat: "induction",
    cu: "mg", conc: 10,
    doses: [{ l: "2 mg/kg", d: 2 }, { l: "2.5 mg/kg", d: 2.5 }],
    info: "Induction 2–2.5 mg/kg (영아는 요구량 ↑ 2.5–3)",
    caution: "허가상 <b>만 3세 미만 유도</b>는 자료 부족. 소아 ICU 진정 적응증 없음(PRIS). Fentanyl 병용 시 서맥. 주사통 → Lidocaine 0.5 mg/kg 선투여. 계란·대두 알레르기 확인.",
    ageWarn: [{ lt: 3, msg: "⚠ 3세 미만 유도 — 허가 외 사용" }],
    mix: { neat: true, std: "원액 사용 — 1% 10mg/ml (2% 20mg/ml) · 희석하지 않음" }
  },
  {
    id: "tpt", name: "Thiopental (TPT)", icon: "fa-syringe", cat: "induction",
    cu: "mg", conc: 25,
    doses: [{ l: "5 mg/kg", d: 5 }, { l: "6 mg/kg", d: 6 }],
    info: "Induction 5–6 mg/kg · 신생아 3–4 mg/kg",
    caution: "신생아·영아는 단백결합 ↓·분포용적 ↑ → <b>신생아 3–4, 영아 5–8 mg/kg</b>. 급속 주입 시 저혈압·무호흡. 혈관외 유출 시 조직 괴사.",
    mix: { amt: 500, unit: "mg", vol: 0, n: 1, cu: "mg", label: "500mg 분말", dil: "증류수",
      std: "1ⓥ(500mg) + 증류수 20ml = 25mg/ml" }
  },
  {
    id: "ketamine", name: "Ketamine", icon: "fa-syringe", cat: "induction",
    cu: "mg", conc: 50,
    doses: [{ l: "1 mg/kg", d: 1 }, { l: "2 mg/kg", d: 2 }],
    info: "IV 1–2 mg/kg (IM 4–5 mg/kg)",
    caution: "분비물 ↑ → 항콜린제 고려. 두개내압·안압 상승 우려 환자 주의. 원액 50mg/ml 은 소아에서 부피가 작아 <b>10mg/ml 희석</b>이 계량에 유리.",
    mix: { amt: 500, unit: "mg", vol: 10, n: 1, cu: "mg", label: "500mg/10ml", dil: "NS", syr: 10,
      std: "원액 50mg/ml · 소아 희석 원액 1ml + NS 4ml = 10mg/ml" }
  },
  {
    id: "roc", name: "Rocuronium (ROC)", icon: "fa-capsules", cat: "muscle",
    cu: "mg", conc: 10,
    doses: [{ l: "0.6 mg/kg", d: 0.6 }, { l: "0.2 mg/kg (유지)", d: 0.2 }],
    info: "Intubation 0.6 mg/kg · RSI 1–1.2 mg/kg",
    caution: "<b>신생아 포함 전 연령</b> 사용. 영아는 발현이 빠르고 지속시간이 길어짐. Sugammadex 로 역전.",
    mix: { amt: 50, unit: "mg", vol: 5, n: 1, cu: "mg", label: "50mg/5ml",
      dil: "NS", std: "원액 50mg/5ml = 10mg/ml (희석 없음)" }
  },
  {
    id: "vecuronium", name: "Vecuronium", icon: "fa-capsules", cat: "muscle",
    cu: "mg", conc: 1,
    doses: [{ l: "0.1 mg/kg", d: 0.1 }, { l: "0.12 mg/kg", d: 0.12 }],
    info: "Intubation 0.1 mg/kg (부서 0.12) · 발현 ~3분",
    caution: "<b>생후 7주 미만 자료 부족.</b> 7주–1세는 더 민감하고 회복이 ~1.5배 느림. 간기능 저하 시 회복 지연.",
    mix: { amt: 4, unit: "mg", vol: 0, n: 1, cu: "mg", label: "4mg 분말", dil: "증류수",
      std: "1ⓥ(4mg) + 증류수 4ml = 1mg/ml (10mg ⓥ 이면 10ml)" }
  },
  {
    id: "succinylcholine", name: "Succinylcholine (SCC)", icon: "fa-capsules", cat: "muscle",
    cu: "mg", conc: 20,
    doses: [{
      pick: (w, age) => (age < 1 ? { d: 2, l: "2 mg/kg (영아)" } : { d: 1.5, l: "1.5 mg/kg" }),
      max: 150
    }],
    info: "IV: 영아(<1세) 2 mg/kg · 소아 1–2 mg/kg · IM 4 mg/kg",
    caution: "<b>소아 routine 사용 지양</b> — 미진단 근이영양증에서 고칼륨혈증성 심정지 (FDA boxed warning). 응급 기도·후두경련에 사용. 서맥 → Atropine 전처치 고려. MH 유발.",
    mix: { amt: 100, unit: "mg", vol: 5, n: 1, cu: "mg", label: "100mg/5ml",
      dil: "NS", std: "원액 20mg/ml (희석 없음)" }
  },
  {
    id: "sugammadex", name: "Sugammadex (Bridion)", icon: "fa-capsules", cat: "muscle",
    cu: "mg", conc: 100,
    doses: [
      { l: "2 mg/kg (TOF ≥2)", d: 2 },
      { l: "4 mg/kg (PTC 1–2)", d: 4 },
      { l: "16 mg/kg (즉시)", d: 16 }
    ],
    info: "근이완 감시 결과(TOF/PTC)로 용량 선택",
    caution: "허가 연령 <b>만 2세 이상</b>. 초경 이후 여아: 경구피임약 효과 7일간 감소 안내.",
    ageWarn: [{ lt: 2, msg: "⚠ 2세 미만 — 자료 부족 (허가 외)" }],
    mix: { amt: 200, unit: "mg", vol: 2, n: 1, cu: "mg", label: "200mg/2ml", dil: "NS", syr: 10,
      std: "원액 100mg/ml · 소량이면 1ml + NS 9ml = 10mg/ml" }
  },
  {
    id: "fentanyl", name: "Fentanyl (FTN)", icon: "fa-band-aid", cat: "analgesic",
    cu: "mcg", conc: 50,
    doses: [{ l: "1 mcg/kg", d: 1 }, { l: "2 mcg/kg", d: 2 }],
    info: "1–2 mcg/kg",
    caution: "허가상 <b>만 2세 이상</b>. 신생아·영아는 청소율 ↓ → 감량 및 술후 무호흡 감시. 급속 정주 시 흉벽 경직.",
    ageWarn: [{ lt: 2, msg: "⚠ 2세 미만 — 감량·무호흡 감시" }],
    mix: { amt: 100, unit: "mcg", vol: 2, n: 1, cu: "mcg", label: "100mcg/2ml", dil: "NS", syr: 10,
      std: "원액 50mcg/ml · 소량이면 1ml + NS 4ml = 10mcg/ml" }
  },
  {
    id: "remifentanil", name: "Remifentanil (RFTN)", icon: "fa-band-aid", cat: "analgesic",
    cu: "mcg", conc: 20,
    doses: [{ l: "Bolus 0.5 mcg/kg", d: 0.5 }],
    inf: { l: "Rate (mcg/kg/min)", def: 0.2, step: 0.01, perMin: true },
    info: "C.I. 0.05–0.5 mcg/kg/min (부서 시작 0.2) · Bolus 0.5–1 mcg/kg 30–60초",
    caution: "<b>신생아부터</b> 사용. 에스터 분해 — 축적 없음. Minto 모델은 성인 전용 → 15세 미만은 dose rate 로 설정. 중단 시 진통이 급격히 사라지므로 다른 진통제를 미리 준비.",
    mix: { amt: 1, unit: "mg", vol: 0, n: 1, cu: "mcg", label: "1mg 분말", dil: "NS", syr: 50,
      std: "1ⓥ(1mg) + NS 50ml = 20mcg/ml" }
  },
  {
    id: "sufentanil", name: "Sufentanil (SFTN)", icon: "fa-band-aid", cat: "analgesic",
    cu: "mcg", conc: 5,
    doses: [{ l: "0.1 mcg/kg (짧은 수술)", d: 0.1 }, { l: "0.2 mcg/kg (기본)", d: 0.2 }],
    inf: {
      l: "Rate (mcg/kg/hr)", def: 0.3, step: 0.05, perMin: false, conc: 1,
      mix: { amt: 50, unit: "mcg", vol: 1, n: 1, cu: "mcg", label: "50mcg/1ml", dil: "NS", title: "C.I.",
        std: "30kg 미만 50mcg/1ml + NS 49ml = 1mcg/ml · 30kg 이상 250mcg/5ml + NS 45ml = 5mcg/ml" }
    },
    info: "Bolus 0.1–0.2 mcg/kg · C.I. 0.1–1.5 mcg/kg/hr (시작 0.3)",
    caution: "Fentanyl 보다 역가 5–10배 → <b>소량 계량 오류가 그대로 과량</b>. Bolus 주사기(5mcg/ml)와 C.I. 주사기 농도가 다를 수 있으니 라벨 확인. 장시간 주입 시 종료 1시간 전 감량.",
    mix: { amt: 50, unit: "mcg", vol: 1, n: 1, cu: "mcg", label: "50mcg/1ml", dil: "NS", title: "Bolus", syr: 10,
      std: "50mcg/1ml + NS 9ml = 5mcg/ml" }
  },
  {
    id: "nalbuphine", name: "Nalbuphine", icon: "fa-band-aid", cat: "analgesic",
    cu: "mg", conc: 10,
    doses: [{ l: "0.1 mg/kg", d: 0.1, max: 20 }, { l: "0.2 mg/kg", d: 0.2, max: 20 }],
    info: "0.1–0.2 mg/kg · 1회 최대 20 mg",
    caution: "혼합 작용제(κ 작용·μ 길항) — 다른 μ 작용제의 진통을 일부 역전시킬 수 있음. 천장 효과가 있음.",
    mix: { amt: 10, unit: "mg", vol: 1, n: 1, cu: "mg", label: "10mg/1ml", dil: "NS", syr: 10,
      std: "원액 10mg/ml · 소량이면 1ml + NS 9ml = 1mg/ml" }
  },
  {
    id: "morphine", name: "Morphine", icon: "fa-band-aid", cat: "analgesic",
    cu: "mg", conc: 1,
    doses: [{ l: "0.05 mg/kg", d: 0.05 }, { l: "0.1 mg/kg", d: 0.1 }],
    info: "0.05–0.1 mg/kg · 6개월 미만 0.025–0.05 mg/kg",
    caution: "<b>6개월 미만·신생아는 청소율 ↓ → 감량</b> 및 호흡 감시. 히스타민 유리.",
    mix: { amt: 10, unit: "mg", vol: 1, n: 1, cu: "mg", label: "10mg/1ml", dil: "NS", syr: 10,
      std: "10mg/1ml + NS 9ml = 1mg/ml" }
  },
  {
    id: "profa", name: "Profa (Acetaminophen IV)", icon: "fa-band-aid", cat: "analgesic",
    cu: "mg", conc: 10,
    doses: [{
      pick: (w) =>
        w <= 10 ? { d: 7.5, l: "7.5 mg/kg (≤10kg)" }
        : w <= 50 ? { d: 15, l: "15 mg/kg" }
        : { fixed: 1000, l: "1000 mg (>50kg)" },
      max: 1000
    }],
    info: "≤10kg 7.5 mg/kg · 10–50kg 15 mg/kg · >50kg 1g · 15분 주입",
    caution: "1일 최대: ≤10kg 30 mg/kg · 10–33kg 60 mg/kg(≤2g) · 33–50kg 60 mg/kg(≤3g). 다른 acetaminophen 제제와 <b>중복 투여 금지</b>.",
    mix: { neat: true, std: "1000mg/100ml 원액 = 10mg/ml (희석 없음) · 필요량만 뽑아 15분 주입" }
  },
  {
    id: "denogan", name: "Denogan (Propacetamol)", icon: "fa-pills", cat: "analgesic",
    cu: "mg", conc: 200,
    doses: [{ l: "30 mg/kg (=APAP 15)", d: 30, max: 2000 }],
    info: "30 mg/kg (= Acetaminophen 15 mg/kg) · 6시간 간격 · 1일 최대 120 mg/kg",
    caution: "Propacetamol 2 mg = Acetaminophen 1 mg. Profa 등 acetaminophen 제제와 <b>중복 금지</b>.",
    mix: { amt: 1000, unit: "mg", vol: 0, n: 1, cu: "mg", label: "1g 분말", dil: "전용 용해액",
      std: "1ⓥ(1g) + 전용 용해액 5ml = 200mg/ml → NS 또는 D5W 에 희석해 15분 주입" }
  },
  {
    id: "midazolam", name: "Midazolam (MDZ)", icon: "fa-moon", cat: "sedation",
    cu: "mg", conc: 1,
    doses: [{ l: "0.05 mg/kg", d: 0.05 }, { l: "0.1 mg/kg", d: 0.1 }],
    info: "IV 0.05–0.1 mg/kg · 총량 6개월–5세 ≤6 mg, 6–12세 ≤10 mg",
    caution: "<b>신생아 급속 정주 금기</b> — 2–5분에 걸쳐 투여. 조산아·신생아는 벤질알코올 무함유 제형 확인. 역설적 흥분이 비교적 흔함.",
    mix: { amt: 15, unit: "mg", vol: 3, n: 1, cu: "mg", label: "15mg/3ml", dil: "NS", syr: 10,
      std: "5mg/5ml 앰플은 원액 1mg/ml · 15mg/3ml 은 1@ + NS 12ml = 1mg/ml" }
  },
  {
    id: "dexmedetomidine", name: "Dexmedetomidine (DEX)", icon: "fa-moon", cat: "sedation",
    cu: "mcg", conc: 4,
    doses: [{ l: "Loading 1 mcg/kg", d: 1, over: 10 }],
    inf: { l: "Rate (mcg/kg/hr)", def: 0.5, step: 0.1, perMin: false },
    info: "Loading 0.5–1 mcg/kg <b>10분</b> → 유지 0.2–1 mcg/kg/hr",
    caution: "허가: 비삽관 소아 1개월–18세 비침습 시술 진정 — 전신마취 보조는 허가 외. <b>서맥·저혈압</b>: 급속 bolus 금지. 원액(100mcg/ml)을 그대로 쓰지 말 것.",
    ageWarn: [{ lt: 1 / 12, msg: "⚠ 1개월 미만 — 허가 외" }],
    mix: { amt: 200, unit: "mcg", vol: 2, n: 1, cu: "mcg", label: "200mcg/2ml", dil: "NS", syr: 50,
      std: "200mcg/2ml + NS 48ml = 4mcg/ml · 저체중아 1mcg/ml" }
  },
  {
    id: "atropine", name: "Atropine", icon: "fa-heartbeat", cat: "emergency",
    cu: "mg", conc: 0.5,
    doses: [{ l: "0.02 mg/kg", d: 0.02, max: 0.5 }],
    info: "0.02 mg/kg · 1회 최대 0.5 mg (청소년 1 mg)",
    caution: "PALS 최소 0.1 mg 권고는 근거가 약함 — 5kg 미만은 최소용량 적용 시 체중당 과량. 기관 지침 확인.",
    mix: { amt: 0.5, unit: "mg", vol: 1, n: 1, cu: "mg", label: "0.5mg/1ml", dil: "NS", syr: 10,
      std: "원액 0.5mg/ml · CPR 지침 1ml + NS 4ml = 0.1mg/ml (0.2 ml/kg)" }
  },
  {
    id: "glycopyrrolate", name: "Glycopyrrolate", icon: "fa-heartbeat", cat: "emergency",
    cu: "mg", conc: 0.2,
    doses: [{ l: "0.01 mg/kg", d: 0.01, max: 0.2 }],
    info: "0.01 mg/kg · 20kg 이상 1@ (0.2 mg)",
    caution: "BBB 통과 안 함 → 중추 항콜린 증상 적음. Atropine 투여 시 생략.",
    mix: { amt: 0.2, unit: "mg", vol: 1, n: 1, cu: "mg", label: "0.2mg/1ml", dil: "NS",
      std: "원액 0.2mg/ml (희석 없음)" }
  },
  {
    id: "lidocaine", name: "Lidocaine (1%)", icon: "fa-heartbeat", cat: "emergency",
    cu: "mg", conc: 10,
    doses: [
      { l: "0.5 mg/kg (PPF 주사통)", d: 0.5, max: 30 },
      { l: "1 mg/kg (부정맥)", d: 1, max: 100 }
    ],
    info: "Propofol 주사통 0.5 mg/kg (최대 30 mg) · VF/pVT 1 mg/kg",
    caution: "국소마취제 총량(4.5 mg/kg, epi 병용 7 mg/kg)에 합산. 신생아·영아는 반복 투여 시 축적.",
    mix: { amt: 400, unit: "mg", vol: 20, n: 1, cu: "mg", label: "2% 400mg/20ml", dil: "NS",
      std: "1% 원액 10mg/ml · 2% 제형이면 NS 로 1:1 희석" }
  },
  {
    id: "epinephrine", name: "Epinephrine (CPR)", icon: "fa-heart", cat: "emergency",
    cu: "mcg", conc: 100,
    doses: [{ l: "10 mcg/kg (IV/IO)", d: 10, max: 1000 }],
    info: "CPR 0.01 mg/kg (0.1 ml/kg of 1:10,000) · 최대 1 mg · 3–5분마다",
    caution: "IV/IO 는 반드시 <b>1:10,000 (100mcg/ml)</b> 로 희석. Anaphylaxis IM 은 원액 1mg/ml 0.01 mg/kg (최대 0.3 mg, 허벅지 전외측).",
    mix: { amt: 1, unit: "mg", vol: 1, n: 1, cu: "mcg", label: "1mg/1ml", dil: "NS", syr: 10,
      std: "1mg/1ml + NS 9ml = 100mcg/ml (1:10,000)" }
  },
  {
    id: "dexamethasone", name: "Dexamethasone", icon: "fa-pills", cat: "emergency",
    cu: "mg", conc: 5,
    doses: [
      { l: "0.15 mg/kg (유도, ≤5mg)", d: 0.15, max: 5 },
      { l: "0.15 mg/kg (T&A, ≤10mg)", d: 0.15, max: 10 }
    ],
    info: "PONV 0.15 mg/kg · 유도용 최대 5 mg · T&A 최대 10 mg",
    caution: "종양융해증후군 위험군(백혈병·림프종 의심)·활동성 감염은 투여 전 확인.",
    mix: { amt: 5, unit: "mg", vol: 1, n: 1, cu: "mg", label: "5mg/1ml", dil: "NS",
      std: "원액 5mg/ml (희석 없음)" }
  },
  {
    id: "ondansetron", name: "Ondansetron", icon: "fa-pills", cat: "emergency",
    cu: "mg", conc: 2,
    doses: [{ l: "0.1 mg/kg", d: 0.1, max: 4 }],
    info: "0.1 mg/kg · 최대 4 mg · 30초 이상 (2–5분)",
    caution: "생후 1개월 이상. QT 연장 — 급속 정주 피함.",
    ageWarn: [{ lt: 1 / 12, msg: "⚠ 1개월 미만 — 허가 외" }],
    mix: { amt: 4, unit: "mg", vol: 2, n: 1, cu: "mg", label: "4mg/2ml", dil: "NS",
      std: "원액 4mg/2ml = 2mg/ml (희석 없음)" }
  }
];

const ICON_CLASS = {
  induction: "c-induction", muscle: "c-muscle", analgesic: "c-analgesic",
  sedation: "c-sedation", emergency: "c-emergency"
};

// ===== Card rendering =====
function concInputHtml(inputId, value, cu) {
  return `
        <div class="cx-input">
          <label>Conc (${cu}/ml)</label>
          <input type="number" id="${inputId}" data-conc="${cu}/ml" value="${value}" step="0.1" min="0" />
        </div>`;
}

function doseItemHtml(drugId, i, label) {
  return `
        <div class="cx-res" id="${drugId}_d${i}_item">
          <div class="cx-res-label"><i class="fas fa-tint"></i> <span id="${drugId}_d${i}_label">${label}</span></div>
          <div class="cx-dual" id="${drugId}_d${i}">
            <span class="cx-dose">-</span>
            <span class="cx-vol">-</span>
          </div>
        </div>`;
}

// MIX 는 접힌 상태로 시작 — 필요할 때 펼쳐 봅니다
function mixBoxHtml(inputId, m) {
  return `<details class="cx-mix"><summary><span class="cx-mix-h">MIX${m.title ? " · " + m.title : ""}</span>조제 방법</summary><div id="${inputId}_mix"></div></details>`;
}

function cardHtml(drug) {
  let body = concInputHtml(drug.id + "_conc", drug.conc, drug.cu);
  const results = drug.doses
    .map((dz, i) => doseItemHtml(drug.id, i, dz.l || "Dose"))
    .join("");

  let infHtml = "";
  if (drug.inf) {
    const inf = drug.inf;
    infHtml = `
      <div class="cx-card-body">
        <div class="cx-section">C.I. (지속주입)</div>
        ${inf.conc ? concInputHtml(drug.id + "_inf_conc", inf.conc, drug.cu) : ""}
        <div class="cx-input">
          <label>${inf.l}</label>
          <input type="number" id="${drug.id}_inf_rate" value="${inf.def}" step="${inf.step}" min="0" />
        </div>
      </div>
      ${inf.mix ? mixBoxHtml(drug.id + "_inf_conc", inf.mix) : ""}`;
  }

  return `
    <div class="cx-card" data-drug="${drug.id}">
      <div class="cx-card-head">
        <div class="cx-icon ${ICON_CLASS[drug.cat]}"><i class="fas ${drug.icon}"></i></div>
        <h3>${drug.name}</h3>
      </div>
      <div class="cx-card-body">${body}
      </div>
      ${mixBoxHtml(drug.id + "_conc", drug.mix)}
      ${infHtml}
      <p class="cx-info">${drug.info}</p>
      <div class="cx-age" id="${drug.id}_age_flag"></div>
      ${drug.caution ? `<details class="cx-caution"><summary>주의 · 연령</summary><p>${drug.caution}</p></details>` : ""}
      <div class="cx-results">${results}${drug.inf ? `
        <div class="cx-res" id="${drug.id}_inf_item">
          <div class="cx-res-label"><i class="fas fa-tachometer-alt"></i> C.I. (ml/hr)</div>
          <div class="cx-res-value" id="${drug.id}_inf">-</div>
        </div>` : ""}
      </div>
    </div>`;
}

function renderCards() {
  document.getElementById("drugGrid").innerHTML = DRUGS.map(cardHtml).join("");
}

// ===== MIX (조제 방법) — 성인 계산기와 같은 방식 =====
// 농도 입력값에 맞춰 "앰플 + 희석액 = 총량" 을 자동 계산합니다.
//  amt/unit/vol : 앰플(바이알) 1개의 약물량·단위·부피 (분말이면 vol 0)
//  n            : 조제에 쓰는 앰플 수
//  cu           : 농도 입력칸의 단위 (…/ml)
//  dil          : 희석액
//  std          : 표준 조제 (anesthesia-manual 소아 탭 기준)
//  syr          : 해당 부피(ml) 시린지 조제법도 함께 표시
//  neat         : 원액 사용 약물
const MASS = { mcg: 0.001, mg: 1, g: 1000 };
function convUnit(v, from, to) {
  if (from === to) return v;
  if (MASS[from] && MASS[to]) return (v * MASS[from]) / MASS[to];
  return NaN;
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
  const ampTxt = m.n + (m.vol > 0 ? "@" : "ⓥ") + "(" + m.label + ")";
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
  // 시린지 조제 (앰플 일부만 사용)
  let syr = "";
  if (m.syr && m.vol > 0) {
    const stock = convUnit(m.amt, m.unit, m.cu) / m.vol;
    const draw = (conc * m.syr) / stock;
    if (draw < m.syr && Math.abs(total - m.syr) > 0.5) {
      syr = '<span class="cx-mix-sub">' + m.syr + "ml 시린지: 원액 " + fmt(draw) + "ml + " + m.dil + " " +
        fmt(m.syr - draw) + "ml</span>";
    }
  }
  return line + syr + std;
}

function updateMixes() {
  DRUGS.forEach((drug) => {
    const pairs = [[drug.id + "_conc", drug.mix]];
    if (drug.inf && drug.inf.mix) pairs.push([drug.id + "_inf_conc", drug.inf.mix]);
    pairs.forEach(([inputId, m]) => {
      const el = document.getElementById(inputId + "_mix");
      const input = document.getElementById(inputId);
      if (el && input && m) el.innerHTML = mixText(m, parseFloat(input.value));
    });
  });
}

// ===== Airway =====
const floorHalf = (x) => Math.floor(x * 2) / 2;
const r1 = (x) => Math.round(x * 10) / 10;

function calculateAirway(age, height, weight) {
  const set = (id, v) => (document.getElementById(id).textContent = v);
  const note = [];

  if (age >= 1) {
    // Cole 공식 (만 1–12세): uncuffed 4 + age/4, cuffed 3.5 + age/4
    // 튜브는 0.5 단위 → 계산값 이하의 가장 가까운 크기, ±0.5 함께 준비
    const unc = 4 + age / 4;
    const cuf = 3.5 + age / 4;
    set("ett_uncuffed", floorHalf(unc).toFixed(1) + " mm");
    set("ett_cuffed", floorHalf(cuf).toFixed(1) + " mm");
    set("ett_depth", r1(12 + age / 2) + " cm");
    note.push("ID 계산 " + r1(cuf) + "(c)/" + r1(unc) + "(u) · ±0.5 함께 준비");
    if (age > 12) note.push("12세 초과 — 성인 기준도 확인");
  } else if (age >= 0 && !isNaN(age)) {
    // 1세 미만: 나이 공식 대신 체중 기준
    const unc = weight > 0 && weight < 3 ? 3.0 : 3.5;
    set("ett_uncuffed", unc.toFixed(1) + " mm");
    set("ett_cuffed", unc === 3.0 ? "-" : "3.0 mm");
    // 깊이: 5kg 이하 체중 + 6 (Tochen), 그 외 3 × ID
    set("ett_depth", r1(weight > 0 && weight <= 5 ? weight + 6 : 3 * unc) + " cm");
    note.push("1세 미만 — 체중 기준 (깊이: ≤5kg 체중+6, 그 외 3×ID)");
  } else {
    set("ett_uncuffed", "-");
    set("ett_cuffed", "-");
    set("ett_depth", "-");
  }

  // C-line 깊이 (Andropoulos 2001, Rt IJ·SCV, RA 위 SVC):
  //  키 ≤100cm → 키/10 − 1,  키 >100cm → 키/10 − 2
  if (height > 0) {
    set("c_line", r1(height / 10 - (height <= 100 ? 1 : 2)) + " cm");
  } else {
    set("c_line", "-");
  }
  document.getElementById("airway_note").textContent = note.join(" · ");
}

// ===== Drug doses =====
function readConc(id) {
  const el = document.getElementById(id);
  const v = el ? parseFloat(el.value) : NaN;
  return v > 0 ? v : NaN;
}

function setDose(drugId, i, text1, text2) {
  const el = document.getElementById(drugId + "_d" + i);
  const item = document.getElementById(drugId + "_d" + i + "_item");
  el.querySelector(".cx-dose").innerHTML = text1;
  el.querySelector(".cx-vol").textContent = text2;
  item.classList.toggle("is-result", text1 !== "-");
}

function calculateDrug(drug, weight, age) {
  const conc = readConc(drug.id + "_conc");
  const hasW = weight > 0;

  drug.doses.forEach((dz, i) => {
    let perKg = dz.d, label = dz.l, fixed = null;
    if (dz.pick) {
      const p = dz.pick(weight, age);
      perKg = p.d; label = p.l; fixed = p.fixed != null ? p.fixed : null;
    }
    document.getElementById(drug.id + "_d" + i + "_label").textContent = label;

    if (!hasW || isNaN(conc)) {
      setDose(drug.id, i, "-", "-");
      return;
    }
    let total = fixed != null ? fixed : weight * perKg;
    let capped = false;
    if (dz.max && total > dz.max) {
      total = dz.max;
      capped = true;
    }
    const vol = total / conc;
    let volTxt = vol.toFixed(2) + " ml";
    if (dz.over) volTxt += " · " + (vol * 60 / dz.over).toFixed(1) + " ml/hr×" + dz.over + "분";
    setDose(drug.id, i,
      total.toFixed(2) + " " + drug.cu + (capped ? '<span class="cx-cap">MAX</span>' : ""),
      volTxt);
  });

  if (drug.inf) {
    const infConc = drug.inf.conc ? readConc(drug.id + "_inf_conc") : conc;
    const rate = parseFloat(document.getElementById(drug.id + "_inf_rate").value);
    const el = document.getElementById(drug.id + "_inf");
    const item = document.getElementById(drug.id + "_inf_item");
    if (hasW && infConc > 0 && rate >= 0) {
      const mlhr = (rate * weight * (drug.inf.perMin ? 60 : 1)) / infConc;
      el.textContent = mlhr.toFixed(2);
      item.classList.add("is-result");
    } else {
      el.textContent = "-";
      item.classList.remove("is-result");
    }
  }

  const flag = document.getElementById(drug.id + "_age_flag");
  const w = (drug.ageWarn || []).find((a) => age >= 0 && age < a.lt);
  flag.textContent = w ? w.msg : "";
  flag.classList.toggle("is-show", !!w);
}

function calculateAll() {
  const age = parseFloat(document.getElementById("age").value);
  const height = parseFloat(document.getElementById("height").value);
  const weight = parseFloat(document.getElementById("weight").value);

  calculateAirway(age, height, weight);
  DRUGS.forEach((drug) => calculateDrug(drug, weight, age));
}

// ===== Concentration settings modal =====
function openSettings() {
  const settingsContainer = document.getElementById("concentrationSettings");
  let html = "";
  DRUGS.forEach((drug) => {
    const ids = [[drug.id + "_conc", drug.name + (drug.inf && drug.inf.conc ? " (Bolus)" : "")]];
    if (drug.inf && drug.inf.conc) ids.push([drug.id + "_inf_conc", drug.name + " (C.I.)"]);
    ids.forEach(([inputId, label]) => {
      const input = document.getElementById(inputId);
      html += `
      <div class="cx-conc-row">
        <span class="cx-conc-label">${label}</span>
        <input type="number" class="cx-conc-input" data-target="${inputId}"
               value="${input.value}" step="0.1" min="0">
        <span class="cx-conc-unit">${input.dataset.conc}</span>
      </div>`;
    });
  });
  settingsContainer.innerHTML = html;
  document.getElementById("settingsModal").classList.add("is-open");
}

function closeSettings() {
  document.getElementById("settingsModal").classList.remove("is-open");
}

function saveSettings() {
  document.querySelectorAll(".cx-modal .cx-conc-input").forEach((input) => {
    const value = parseFloat(input.value);
    if (value > 0) document.getElementById(input.dataset.target).value = value;
  });
  closeSettings();
  updateMixes();
  calculateAll();
}

// Real-time calculation
document.addEventListener("DOMContentLoaded", function () {
  renderCards();
  let calculationTimeout;

  document.querySelectorAll(".cx-panel input, .cx-grid input").forEach((input) => {
    input.addEventListener("input", () => {
      updateMixes();
      clearTimeout(calculationTimeout);
      calculationTimeout = setTimeout(calculateAll, 300);
    });
  });

  updateMixes();
  calculateAll();
});

// Close modal when clicking outside / ESC
window.addEventListener("click", function (event) {
  if (event.target === document.getElementById("settingsModal")) closeSettings();
});
document.addEventListener("keydown", function (event) {
  if (event.key === "Escape") closeSettings();
});
