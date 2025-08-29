from django.shortcuts import render
from django.http import HttpResponse
from accounts.decorators import user_is_approved
# Create your views here.

@user_is_approved
def calculator_landing_page(request):
    return render(request, 'calculator/landing_page.html')

def calculator(request):
    
    # Input area (기존)
    age = request.GET.get('age')
    height = request.GET.get('height')
    weight = request.GET.get('weight')
    
    nep_conc = request.GET.get('nep_conc')
    nep_dr = request.GET.get('nep_dr')
    
    epi_conc = request.GET.get('epi_conc')
    epi_dr = request.GET.get('epi_dr')
    
    dopa_conc = request.GET.get('dopa_conc')
    dopa_dr = request.GET.get('dopa_dr')
    
    dobu_conc = request.GET.get('dobu_conc')
    dobu_dr = request.GET.get('dobu_dr')
    
    ntg_conc = request.GET.get('ntg_conc')
    ntg_dr = request.GET.get('ntg_dr')
    
    snp_conc = request.GET.get('snp_conc')
    snp_dr = request.GET.get('snp_dr')
    
    vaso_conc = request.GET.get('vaso_conc')
    vaso_dr1 = request.GET.get('vaso_dr1')
    vaso_dr2 = request.GET.get('vaso_dr2')
    
    ppf_conc = request.GET.get('ppf_conc')
    
    rftn_conc = request.GET.get('rftn_conc')
    
    suftn_conc = request.GET.get('suftn_conc')
    
    txa_conc = request.GET.get('txa_conc')
    
    
    # Output area (기존)
    nep_result = 0
    epi_result = 0
    dopa_result = 0
    dobu_result = 0
    ntg_result = 0
    snp_result = 0
    vaso_result1 = 0
    vaso_result2 = 0
    ppf_result1 = 0
    ppf_result2 = 0
    rftn_result1 = 0
    rftn_result2 = 0
    suftn_result1 = 0
    suftn_result2 = 0
    txa_result1 = 0
    txa_result2 = 0

    
    ## Calculation area for existing drugs
    # NEP Calculation
    if weight and nep_conc and nep_dr:
        weight = int(weight)
        nep_conc = float(nep_conc)
        nep_dr = float(nep_dr)
        nep_result = 60 * weight * nep_dr / nep_conc
    else:
        nep_result = "Please fill all the fields!!"
        
    # EPI Calculation
    if weight and epi_conc and epi_dr:
        weight = int(weight)
        epi_conc = float(epi_conc)
        epi_dr = float(epi_dr)
        epi_result = 60 * weight * epi_dr / epi_conc
    else:
        epi_result = "Please fill all the fields!!"
        
    # DOPA Calculation
    if weight and dopa_conc and dopa_dr:
        weight = int(weight)
        dopa_conc = float(dopa_conc)
        dopa_dr = float(dopa_dr)
        dopa_result = (60 * weight * dopa_dr) / (dopa_conc * 1000)
    else:
        dopa_result = "Please fill all the fields!!"
        
    # DOBU Calculation
    if weight and dobu_conc and dobu_dr:
        weight = int(weight)
        dobu_conc = float(dobu_conc)
        dobu_dr = float(dobu_dr)
        dobu_result = (60 * weight * dobu_dr) / (dobu_conc * 1000)
    else:
        dobu_result = "Please fill all the fields!!"
        
    # NTG Calculation
    if weight and ntg_conc and ntg_dr:
        weight = int(weight)
        ntg_conc = float(ntg_conc)
        ntg_dr = float(ntg_dr)
        ntg_result = (60 * weight * ntg_dr) / (ntg_conc * 1000)
    else:
        ntg_result = "Please fill all the fields!!"
        
    # SNP Calculation
    if weight and snp_conc and snp_dr:
        weight = int(weight)
        snp_conc = float(snp_conc)
        snp_dr = float(snp_dr)
        snp_result = (60 * weight * snp_dr) / (snp_conc * 1000)
    else:
        snp_result = "Please fill all the fields!!"
    
    # VASO Calculation
    if weight and vaso_conc and vaso_dr1 and vaso_dr2:
        vaso_conc = float(vaso_conc)
        vaso_dr1 = float(vaso_dr1)
        vaso_dr2 = float(vaso_dr2)
        vaso_result1 = (60 * vaso_dr1) / vaso_conc
        vaso_result2 = (weight * vaso_dr2) / vaso_conc
    else:
        vaso_result1 = "Please fill all the fields!!"
        vaso_result2 = "Please fill all the fields!!"

    # PPF Calculation
    if weight and ppf_conc:
        ppf_conc = float(ppf_conc)
        ppf_result1 = (weight * 6) / ppf_conc
        ppf_result2 = (weight * 12) / ppf_conc
    else:
        ppf_result1 = "Please fill all the fields!!"
        ppf_result2 = "Please fill all the fields!!"

    # RFTN Calculation
    if weight and rftn_conc:
        rftn_conc = float(rftn_conc)
        rftn_result1 = (weight * 0.1) / rftn_conc
        rftn_result2 = (weight * 1) / rftn_conc
    else:
        rftn_result1 = "Please fill all the fields!!"
        rftn_result2 = "Please fill all the fields!!"

    # SUFTN Calculation
    if weight and suftn_conc:
        suftn_conc = float(suftn_conc)
        suftn_result1 = (weight * 0.5) / suftn_conc
        suftn_result2 = (weight * 1.5) / suftn_conc
    else:
        suftn_result1 = "Please fill all the fields!!"
        suftn_result2 = "Please fill all the fields!!"

    # TXA Calculation
    if weight and txa_conc:
        txa_conc = float(txa_conc)
        txa_result1 = (weight * 10 * 3) / txa_conc
        txa_result2 = (weight * 1) / txa_conc
    else:
        txa_result1 = "Please fill all the fields!!"
        txa_result2 = "Please fill all the fields!!"
        
        
    ## New Drugs Calculations
    
    # Calcium Gluconate (하나의 카드에서 Bolus + Continuous 함께 계산)
    ca_conc = request.GET.get('ca_conc')    # mg/mL
    ca_bolus = request.GET.get('ca_bolus')  # g (예: 1~2g)
    ca_dr = request.GET.get('ca_dr')        # mg/kg/hr
    if weight and ca_conc:
        weight_val = float(weight)
        ca_conc_val = float(ca_conc)

        # Bolus 계산
        #   - Bolus(g) → mg 단위로 변환 후 농도(mg/mL)로 나누어 mL 계산
        if ca_bolus:
            try:
                ca_bolus_val = float(ca_bolus)
                # (g → mg) = (ca_bolus_val * 1000)
                ca_bolus_result = (ca_bolus_val * 1000) / ca_conc_val
            except:
                ca_bolus_result = "Invalid input!"
        else:
            ca_bolus_result = "Please fill all fields for bolus"

        # Continuous Infusion 계산
        #   - (체중 × mg/kg/hr) / 농도(mg/mL) = mL/hr
        if ca_dr:
            try:
                ca_dr_val = float(ca_dr)
                ca_cont_result = (weight_val * ca_dr_val) / ca_conc_val
            except:
                ca_cont_result = "Invalid input!"
        else:
            ca_cont_result = "Please fill all fields for continuous infusion"

    else:
        ca_bolus_result = "Please fill all the fields!!"
        ca_cont_result = "Please fill all the fields!!"


        
    # Magnesium Sulfate (Bolus + Continuous)
    mg_conc = request.GET.get('mg_conc')       # 농도, 단위: mg/mL (기본값: 200)
    mg_bolus = request.GET.get('mg_bolus')     # Bolus 용량, 단위: g (예: 1~2 g)
    mg_infusion = request.GET.get('mg_infusion') # Continuous Infusion 용량, 단위: g/hr (예: 1~2 g/hr)
    
    if mg_conc:
        try:
            mg_conc_val = float(mg_conc)
        except:
            mg_conc_val = 0
    else:
        mg_conc_val = 0
    # Bolus 계산: (g -> mg) 후 mg/mL로 나누어 주입 부피(ml) 산출
    if mg_bolus and mg_conc_val:
        try:
            mg_bolus_val = float(mg_bolus)
            mg_bolus_result = (mg_bolus_val * 1000) / mg_conc_val
        except:
            mg_bolus_result = "Invalid input!"
    else:
        mg_bolus_result = "Please fill all fields for bolus"

    # Continuous Infusion 계산: (g/hr -> mg/hr) 후 mg/mL로 나누어 주입 속도(ml/hr) 산출
    if mg_infusion and mg_conc_val:
        try:
            mg_infusion_val = float(mg_infusion)
            mg_infusion_result = (mg_infusion_val * 1000) / mg_conc_val
        except:
            mg_infusion_result = "Invalid input!"
    else:
        mg_infusion_result = "Please fill all fields for continuous infusion"

        
    # Sodium Bicarbonate (Bolus, mEq/kg)
    sbic_conc = request.GET.get('sbic_conc')
    sbic_dr = request.GET.get('sbic_dr')
    if weight and sbic_conc and sbic_dr:
        weight = float(weight)
        sbic_conc = float(sbic_conc)  # 기본값: 1 (mEq/mL)
        sbic_dr = float(sbic_dr)      # mEq/kg
        sbic_result = (weight * sbic_dr) / sbic_conc
    else:
        sbic_result = "Please fill all the fields!!"
        
    # Phenylephrine (Bolus)
    phen_conc = request.GET.get('phen_conc')
    phen_bolus = request.GET.get('phen_bolus')
    if weight and phen_conc and phen_bolus:
        try:
            weight_val = float(weight)  # 필요없지만, 통일성 위해 변환
            phen_conc_val = float(phen_conc)  # 기본값 100 (mcg/mL)
            phen_bolus_val = float(phen_bolus)  # 입력: 50~100 mcg
            phen_bolus_result = phen_bolus_val / phen_conc_val  # 결과: mL
        except:
            phen_bolus_result = "Invalid input!"
    else:
        phen_bolus_result = "Please fill all the fields!!"
    # Phenylephrine (Continuous infusion)
    phen_dr = request.GET.get('phen_dr')
    if weight and phen_conc and phen_dr:
        try:
            weight_val = float(weight)
            phen_conc_val = float(phen_conc)  # 100 mcg/mL
            phen_dr_val = float(phen_dr)      # mcg/kg/min, 범위: 0.1–0.5
            phen_cont_result = (60 * weight_val * phen_dr_val) / phen_conc_val  # mL/hr 계산
        except:
            phen_cont_result = "Invalid input!"
    else:
        phen_cont_result = "Please fill all the fields!!"
        
    # Dantrolene: Bolus 및 Continuous Infusion 계산
    dant_conc = request.GET.get('dant_conc')   # mg/mL, 기본값: 20
    dant_infusion = request.GET.get('dant_infusion')  # mg/kg/hr, (예: 0.25~0.5)
    # 고정된 볼루스 dose (mg/kg)
    dant_bolus_dose = 2.5  
    dant_max_dose = 10.0   # 최대 누적 투여량 (mg/kg)
    
    if weight and dant_conc:
        weight_val = float(weight)
        dant_conc_val = float(dant_conc)
        # 한 bolus 투여 시 부피 (mL) = (체중 × 2.5 mg/kg) ÷ (20 mg/mL)
        dant_bolus_result = (weight_val * dant_bolus_dose) / dant_conc_val
        # 최대 누적 bolus 부피 (mL) = (체중 × 10 mg/kg) ÷ (20 mg/mL)
        dant_max_result = (weight_val * dant_max_dose) / dant_conc_val
    else:
        dant_bolus_result = "Please fill all the fields!!"
        dant_max_result = "Please fill all the fields!!"
    # Continuous Infusion 계산: (체중 × infusion rate (mg/kg/hr)) ÷ (20 mg/mL)
    if weight and dant_conc and dant_infusion:
        try:
            weight_val = float(weight)
            dant_conc_val = float(dant_conc)
            dant_infusion_rate = float(dant_infusion)
            dant_infusion_result = (weight_val * dant_infusion_rate) / dant_conc_val  # mL/hr
        except:
            dant_infusion_result = "Invalid input!"
    else:
        dant_infusion_result = "Please fill all fields for continuous infusion"
        
    # Lidocaine (Bolus + Continuous Infusion)
    lido_conc = request.GET.get('lido_conc')      # mg/mL, 기본값: 20
    lido_bolus = request.GET.get('lido_bolus')    # 볼루스 용량, 단위: mg/kg (예: 1–1.5)
    lido_infusion = request.GET.get('lido_infusion')  # 연속 주입 용량, 단위: mg/min (예: 1–4)
    
    if weight and lido_conc:
        weight_val = float(weight)
        lido_conc_val = float(lido_conc)
        
        # Bolus 계산: 총 용량(mg) = weight × lido_bolus (mg/kg)
        # 투여 부피(mL) = (총 용량(mg)) ÷ (농도 (mg/mL))
        if lido_bolus:
            try:
                lido_bolus_val = float(lido_bolus)
                lido_bolus_result = (weight_val * lido_bolus_val) / lido_conc_val
            except:
                lido_bolus_result = "Invalid input!"
        else:
            lido_bolus_result = "Please fill bolus fields!"
        
        # Continuous infusion 계산:
        # Infusion 시 투여 부피 (mL/min) = (투여 속도 (mg/min)) ÷ (농도 (mg/mL))
        # mL/hr = mL/min × 60
        if lido_infusion:
            try:
                lido_infusion_val = float(lido_infusion)
                lido_infusion_result = (lido_infusion_val / lido_conc_val) * 60
            except:
                lido_infusion_result = "Invalid input!"
        else:
            lido_infusion_result = "Please fill infusion fields!"
    else:
        lido_bolus_result = "Please fill all fields!!"
        lido_infusion_result = "Please fill all fields!!"
        
    # Atropine: Bolus 및 Continuous (Atropine은 주로 bolus로 사용됨)
    # 고정 농도: 0.5 mg/mL, 권장 bolus: 0.5 mg (한 번 투여 시), 최대 3 mg까지
    atropine_conc = request.GET.get('atropine_conc') or "0.5"  # mg/mL
    atropine_bolus = request.GET.get('atropine_bolus') or "0.5"  # mg, 한 번 투여 용량

    try:
        atropine_conc_val = float(atropine_conc)
        atropine_bolus_val = float(atropine_bolus)
        # 한 bolus 투여 시 주입 부피 (mL)
        atropine_bolus_result = atropine_bolus_val / atropine_conc_val
        # 최대 누적 투여 시 주입 부피 (mL)
        atropine_max_result = 3.0 / atropine_conc_val
        # Continuous infusion은 적용하지 않음
        atropine_cont_result = "Not applicable"
    except:
        atropine_bolus_result = "Invalid input!"
        atropine_max_result = "Invalid input!"
        atropine_cont_result = "Not applicable"

        
    # Amiodarone (Bolus + Infusion)
    amio_conc = request.GET.get('amio_conc')
    amio_bolus = request.GET.get('amio_bolus')
    amio_infusion = request.GET.get('amio_infusion')
    if weight and amio_conc and amio_bolus and amio_infusion:
        weight = float(weight)
        amio_conc = float(amio_conc)      # 기본값 예: 1.5 (mg/mL)
        amio_bolus = float(amio_bolus)    # mg/kg (loading dose)
        amio_infusion = float(amio_infusion)  # mg/kg/min (maintenance)
        amio_result_bolus = (weight * amio_bolus) / amio_conc
        amio_result_infusion = (60 * weight * amio_infusion) / amio_conc
    else:
        amio_result_bolus = "Please fill all the fields!!"
        amio_result_infusion = "Please fill all the fields!!"
        
    return render(request, 'calculator/calculator.html', {
        'nep_result': nep_result,
        'epi_result': epi_result,
        'dopa_result': dopa_result,
        'dobu_result': dobu_result,
        'ntg_result': ntg_result,
        'snp_result': snp_result,
        'vaso_result1': vaso_result1,
        'vaso_result2': vaso_result2,
        'ppf_result1': ppf_result1,
        'ppf_result2': ppf_result2,
        'rftn_result1': rftn_result1,
        'rftn_result2': rftn_result2,
        'suftn_result1': suftn_result1,
        'suftn_result2': suftn_result2,
        'txa_result1': txa_result1,
        'txa_result2': txa_result2,
        # New drugs results
        'ca_bolus_result': ca_bolus_result,
        'ca_cont_result': ca_cont_result,
        'mg_bolus_result': mg_bolus_result,
        'mg_infusion_result': mg_infusion_result,
        'sbic_result': sbic_result,
        'phen_bolus_result': phen_bolus_result,
        'phen_cont_result': phen_cont_result,
        'dant_bolus_result': dant_bolus_result,
        'dant_max_result': dant_max_result,
        'dant_infusion_result': dant_infusion_result,
        'lido_bolus_result': lido_bolus_result,
        'lido_infusion_result': lido_infusion_result,
        'atropine_bolus_result': atropine_bolus_result,
        'atropine_max_result': atropine_max_result,
        'atropine_cont_result': atropine_cont_result,
        'amio_result_bolus': amio_result_bolus,
        'amio_result_infusion': amio_result_infusion,
    })
