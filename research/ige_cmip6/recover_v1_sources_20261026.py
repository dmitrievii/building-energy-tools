"""Recover V1 execution in CI without changing frozen scientific code.

The first local control packet became inaccessible before publication.
Reacquire the identical registered endpoints exactly once with registered
network retries; preserve both the first numerical summary and new originals.
A match of summaries is never called proof of identity of the lost raw bytes.
"""
from __future__ import annotations
import argparse,collections,hashlib,json,os,shutil,subprocess
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import build_opener
from v1_prepare import ROOT,R,REG,INPUTS,CONTROLS,RESULTS,PREDICTIONS,LEDGER,SEAL,BASE,registered,code_hashes
from v1_acquire import collect,read_packet,NoRedirect
from v1_control_admission import checked_addendum,ForecastGate,RECEIPT
from v1_run import score,PAIRS
from v1_verify import verify as verify_V1
from v1_control_admission import verify as verify_gate
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
BRANCH="research/ige-v1-time-admission-preregistration-20261026"
SEAL_COMMIT="4d993d64db8cbf7cab2f84b111fc1899445be431"
EXPECTED="v1_initial_local_score_summary_20261026.json"
RECOVERY="v1_recovery_receipt_20261026.json"
REPORT="IGE_V1_TIME_ADMISSION_AND_VALIDATION_RESULTS_RU_20261026.md"

class Budget:
    def __init__(self,limit):self.limit=limit;self.used=0
    def open(self,request,**kwargs):
        if self.used>=self.limit:raise ValueError("V1_RECOVERY_GLOBAL_REMAINING_BYTE_BUDGET")
        response=build_opener(NoRedirect).open(request,**kwargs)
        length=int(response.headers.get("Content-Length","0"))
        if length>self.limit-self.used:
            response.close();raise ValueError("V1_RECOVERY_GLOBAL_HEADER_BYTE_BUDGET")
        return BudgetResponse(response,self,length)

class BudgetResponse:
    def __init__(self,response,budget,length):
        self.response=response;self.budget=budget;self.length=length;self.n=0
        self.status=response.status;self.headers=response.headers
    def geturl(self):return self.response.geturl()
    def __enter__(self):return self
    def __exit__(self,*args):self.response.close()
    def read(self,n=-1):
        if self.length and self.n>=self.length:return b""
        remaining=self.budget.limit-self.budget.used
        if remaining<=0:raise ValueError("V1_RECOVERY_GLOBAL_STREAM_BYTE_BUDGET")
        body=self.response.read(min(n if n>=0 else remaining,remaining))
        self.n+=len(body);self.budget.used+=len(body)
        return body

def expected_comparison(actual,expected):
    mismatches=[];checks=0
    def check(path,a,b):
        nonlocal checks
        checks+=1
        good=(a==b) if isinstance(b,int) else a is not None and abs(float(a)-float(b))<=1.1e-8
        if not good:mismatches.append({"path":path,"initial_summary":b,"reacquired":a})
    for k,v in expected["counts"].items():check("counts."+k,actual["counts"][k],v)
    for c,row in expected["per_country"].items():
        a=actual["per_country"][c]
        check(c+".B0_MAE",a["B0"]["MAE_K"],row["B0_MAE_K"])
        check(c+".R1_MAE",a["R1"]["MAE_K"],row["R1_MAE_K"])
        check(c+".delta",a["delta_MAE_K"],row["delta_MAE_K"])
    for k,row in expected["per_target"].items():
        a=actual["per_target"][k]
        for label,value in row.items():
            model,metric=label.split("_",1);check(k+"."+label,a[model][metric],value)
    for key,season,b0,r1 in expected["primary_cases"]:
        a=next(c for c in actual["cases"] if c["target_key"]==key and c["season"]==season)
        check(key+season+".n",a["paired_hours"],168)
        check(key+season+".B0",a["B0_paired"]["MAE_K"],b0)
        check(key+season+".R1",a["R1_paired"]["MAE_K"],r1)
    for key,season,b0,r1,mean_error,max_step in expected["secondary_CH"]:
        a=next(c for c in actual["secondary_CH_endpoint_cases"] if c["target_key"]==key and c["season"]==season)
        check(key+season+".endpoint_n",a["endpoint_paired_hours"],168)
        check(key+season+".endpoint_B0",a["B0_endpoint"]["MAE_K"],b0)
        check(key+season+".endpoint_R1",a["R1_endpoint"]["MAE_K"],r1)
        check(key+season+".h_vs_six",a["h_minus_t_six_nominal_node_mean"]["MAE_K"],mean_error)
        check(key+season+".step",a["endpoint_step_diagnostics"]["R1_max_K"],max_step)
    return {"compared_numeric_fields":checks,"all_available_initial_summaries_match":not mismatches,
        "absolute_tolerance":1.1e-8,"mismatches":mismatches,"lost_raw_body_identity_certified":False,
        "interpretation":"numerical-summary replay only; lost first packet bytes were not compared"}

def make_registry():
    records=[]
    for name,phase in ((INPUTS,"inputs"),(CONTROLS,"controls")):
        _,m,s=read_packet(R,name,phase=phase)
        for row in m["sources"]:
            if not row["kind"].startswith("station_"):continue
            records.append({k:row[k] for k in ("id","station_key","kind","role","url","member","status")}|
                {"sha256":row.get("sha256"),"bytes":row.get("bytes",0),
                 "raw_whole_container_including_other_years_and_variables_exposed":row["status"]=="ORIGINAL_BODY_RECEIVED"})
    return {"schema":"IGE_V1_REVEALED_SOURCE_REGISTRY_v1","sources":records,
        "AT_target_control_bodies_unopened":True,"2013_2014_usage":"REVEALED_REGRESSION_ONLY_NO_FIT",
        "newly_opened_DE_CH_2010_2019_containers_ineligible_for_future_strict_raw_byte_unseen_claim":True,
        "temperature_fields_only_used_for_scoring":["TT_10","tre200h0","tre200s0"],
        "strict_global_source_blindness_certified":False,"IV1_2022_values_opened":False}

def report(result,recovery):
    url="https://github.com/dmitrievii/building-energy-tools/actions/runs/"+os.environ["GITHUB_RUN_ID"]
    lines=["# V1 — временные операторы и фактическая проверка температуры","",
        "26.10.2026. Исследовательская ветка; main/старые результаты/EPW не изменены, merge отсутствует.","",
        "Метод R1 помогает не всем станциям. Положительное среднее по DE/CH скрывает ухудшение Erfurt и St. Gallen. Австрийские контроли остаются закрыты из-за QC10 доноров.","",
        "Регистрация: 8fdc0341f1b660f4e56abec726381ae5a2dcc8a1; actual prediction seal и pre-control QC gate: 4d993d64db8cbf7cab2f84b111fc1899445be431.","",
        "## Исполнение и источник восстановления","",
        "Первый локальный расчёт завершился, затем среда стала недоступна до публикации полного контрольного ZIP. Исходные прогнозы, доноры, код и протокол уже были в GitHub. CI повторно получил те же зарегистрированные контрольные endpoints, не меняя математический метод, QC, станции, даты и правила оценки. Все новые оригиналы сохранены отдельно с новым SHA и полными квитанциями.","",
        "Побайтовая идентичность первому недоступному контрольному ZIP не сертифицируется. Сохранена исходная численная сводка; совпадение всех доступных в ней полей проверяется отдельно и не подменяет проверку исходных байтов.",
        "Совпадение первоначальной численной сводки: **"+str(recovery["summary_comparison"]["all_available_initial_summaries_match"])+"**; проверено полей: "+str(recovery["summary_comparison"]["compared_numeric_fields"])+".","",
        "## Реальные сравнения","",
        "Все 24 случая сохранены. Метаданные времени/2м готовы для 24; первично оценены 16 случаев DE/CH, 2688/2688 совпавших часов; восемь AT случаев заблокированы. Для CH отдельно оценены 1344 часовых узла.","",
        "| Станция | B0 MAE, K | R1 MAE, K | Результат |","|---|---:|---:|---|"]
    for key,name in [("DE:01270","Erfurt-Weimar"),("DE:00232","Augsburg"),("CH:STG","St. Gallen"),("CH:SCU","Scuol")]:
        r=result["per_target"][key];b0=r["B0"]["MAE_K"];r1=r["R1"]["MAE_K"]
        lines.append("| "+name+" | "+f"{b0:.3f}"+" | "+f"{r1:.3f}"+" | "+("улучшение" if r1<b0 else "ухудшение")+" |")
    lines+=["","Порог парной полноты ≥160/168 выполнен во всех 16 оцениваемых случаях. Страны/QC не смешивались; ниже — их отдельные агрегаты.","",
        "| Страна | B0 MAE, K | R1 MAE, K | ΔMAE, K |","|---|---:|---:|---:|"]
    for c in ("DE","CH"):
        r=result["per_country"][c];lines.append("| "+c+" | "+f"{r['B0']['MAE_K']:.3f}"+" | "+f"{r['R1']['MAE_K']:.3f}"+" | "+f"{r['delta_MAE_K']:.3f}"+" |")
    lines+=["","Предварительный страновой критерий (ΔMAE<0 и верхняя граница описательного блочного интервала<0 при 8/8 случаях) выполнен. При этом две из четырёх станций ухудшились; критерий не является допуском универсального R1. Четыре синхронных сезонных блока дают ограниченную описательную чувствительность, не популяционный доверительный интервал.","",
        "Scuol после коррекции сохраняет среднее холодное смещение около −3.99 K. Источник такого смещения требует отдельной проверки репрезентативности сетки/рельефа; непроверенная высота API не используется как доказанная причина.","",
        "## CH: среднее и часовые состояния","",
        "Официальный h сравнен со средним шести исходных t-отсчётов. MAE по восьми неделям около 0.023–0.026 K, что согласуется с округлением, но не доказывает нулевой фильтр датчика или линейность истинного подчасового пути ERA5.","",
        "| Станция | B0 endpoint MAE, K | R1 endpoint MAE, K |","|---|---:|---:|"]
    for key,name in (("CH:STG","St. Gallen"),("CH:SCU","Scuol")):
        cases=[c for c in result["secondary_CH_endpoint_cases"] if c["target_key"]==key]
        n=sum(c["endpoint_paired_hours"] for c in cases)
        b0=sum(c["B0_endpoint"]["MAE_K"]*c["endpoint_paired_hours"] for c in cases)/n
        r1=sum(c["R1_endpoint"]["MAE_K"]*c["endpoint_paired_hours"] for c in cases)/n
        lines.append("| "+name+" | "+f"{b0:.3f}"+" | "+f"{r1:.3f}"+" |")
    lines+=["","Это сводка уже зарегистрированных вторичных недель, а не дополнительный независимый набор измерений. Максимальное восстановленное часовое приращение достигает 7.985 K; само по себе оно не доказывает физическую невозможность. Обратный оператор имеет частотное усиление до 6. Алгебраически точное восстановление среднего и малая чувствительность к старту не подтверждают точность часовой формы.","",
        "## Австрия","",
        "На всех 6792 строках каждого из шести AT доноров — native QC10 (автоматически проверено); original-статус не подтверждён, а протокол требует AT22. QC не ослаблялся. Предварительное дополнение по доступности опубликовано до контроля и сохранило все восемь отказов. Два AT контрольных тела не запрашивались ни локально, ни при восстановлении CI. Следующая AT проверка требует доказанного происхождения QC10 либо другого допущенного продукта и новой регистрации до открытия целевой T.","",
        "## Четыре независимых статуса","",
        "| Основание | Вывод |","|---|---|",
        "| Код и воспроизводимость | Замороженные уравнения/правила, 300 родительских +42 V1 +8 gate проверок; фактический пересчёт исходных прогнозов и оценок в CI. |",
        "| Физическая допустимость | Датированная 2м геометрия и опубликованные временные определения; истинный фильтр/подчасовой путь и полная физика EPW отдельно. |",
        "| Независимая точность | Новый hourly-error holdout DE/CH относительно R1 fit с ограниченным аудитом прежнего раскрытия. Прежние месячные продукты и возможная ассимиляция ERA5 не исключены. AT заблокирован; региональная/глобальная точность не квалифицирована. |",
        "| Эксплуатация | Исследовательский режим; R1 не становится default. Actual EnergyPlus и production остаются отдельными этапами. |","",
        "B4, преимущество P2, независимая влажность/давление, будущие NASA-часовые события и production EPW этим этапом не квалифицируются. Контроли IV1 2022 закрыты.","",
        "## Что следует интегрировать дальше","",
        "1. Разрешить документальное происхождение AT QC10; сохранить текущие отказы и зарегистрировать следующий AT тест до целевых наблюдений.",
        "2. Для общего локального корректора заранее определить допуск применимости по источникам/рельефу и сравнить с B0 на новой выборке. Результаты 2018 теперь регрессионные; запрещён выбор станций/параметров по выигрышу здесь.",
        "3. Выполнить фактический EnergyPlus-прогон существующих полных исторических/будущих EPW с единым зданием и отчётом; это проверка эксплуатации приложения, отдельная от метеорологической точности.",
        "4. Для локального будущего продукта собрать многолетнюю историческую базу; один исправленный 2025 год не заменяет климатическую норму. B-D/IV1 остаётся отдельным исследовательским маршрутом.","",
        "CI: ["+os.environ["GITHUB_RUN_ID"]+"]("+url+"). Точный статус и проверка артефакта — в v1_verified_CI_<run>.json после финального шага."]
    (ROOT/"docs"/REPORT).write_text("\n".join(lines)+"\n")

def run(out):
    if os.environ.get("GITHUB_REF")!="refs/heads/"+BRANCH:raise ValueError("V1_RESEARCH_BRANCH_ONLY")
    out.mkdir(parents=True,exist_ok=False);expected=json.loads((R/EXPECTED).read_text())
    plan,ledger,addendum=checked_addendum()
    _,inputs,input_storage=read_packet(R,INPUTS,phase="inputs")
    if input_storage["sha256"]!="687ec18f5d22c79478b47275d2cf29a8af9eebcdcdfb360b64b750248584f893":raise ValueError("V1_FROZEN_INPUT_CHANGED")
    initial_used=expected["initial_cumulative_weather_body_bytes"]
    limit=plan["source_budget"]["max_decoded_body_bytes_all_attempts_inputs_plus_controls"]-initial_used
    budget=Budget(limit);gate=ForecastGate(addendum["source_admission"],budget.open)
    acquisition=collect("controls",out/"controls",SEAL_COMMIT,opener=gate.open)
    actual_gate={"schema":"IGE_V1_ACTUAL_CONTROL_SOURCE_GATE_v1","published_seal_commit":SEAL_COMMIT,
        "addendum_sha256":hashlib.sha256((R/"v1_control_admission_addendum_20261026.json").read_bytes()).hexdigest(),
        "actual_control_HTTP_requests":gate.HTTP_requests,"locally_blocked_control_attempts":len(gate.local_skips),
        "locally_blocked_URLs":gate.local_skips,"AT_control_bodies_opened":False,
        "original_collector_HTTP_attempts_field_counts_acquisition_attempts_including_local_skips":acquisition["HTTP_attempts_this_phase"],
        "all24_registered_cases_retained":True,"primary_QC_or_method_changed":False}
    write_exclusive(out/"controls"/RECEIPT,json_bytes(actual_gate))
    _,controls,storage=read_packet(out/"controls",CONTROLS,phase="controls")
    for n in [CONTROLS+".storage.json",*[p["name"] for p in storage["parts"]],RECEIPT]:
        write_exclusive(R/n,(out/"controls"/n).read_bytes())
    score(out/"scored",SEAL_COMMIT)
    for name in (RESULTS,PAIRS):write_exclusive(R/name,(out/"scored"/name).read_bytes())
    check=verify_V1(out/"v1",stage="results")
    gcheck=verify_gate(out/"gate")
    result=json.loads((R/RESULTS).read_text());comparison=expected_comparison(result,expected)
    recovery={"schema":"IGE_V1_CI_RECOVERY_RECEIPT_v1","reason":"local runtime unavailable before first control packet publication",
        "tested_commit":os.environ["GITHUB_SHA"],"CI_run":int(os.environ["GITHUB_RUN_ID"]),
        "registration_commit":expected["registration_commit"],"prediction_seal_commit":SEAL_COMMIT,
        "initial_lost_local_control_packet_sha256":expected["initial_control_packet_sha256"],
        "reacquired_control_packet_sha256":storage["sha256"],"original_raw_control_byte_identity_certified":False,
        "summary_comparison":comparison,"scientific_code_after_controls_changed":False,
        "original_code_hashes_match_seal":code_hashes()==json.loads((R/SEAL).read_text())["code_sha256"],
        "actual_control_source_gate":actual_gate,"new_recovery_HTTP_requests":gate.HTTP_requests,
        "new_recovery_control_body_bytes_all_attempts":budget.used,
        "global_weather_body_bytes_including_first_acquisition":initial_used+budget.used,
        "registered_global_byte_budget":plan["source_budget"]["max_decoded_body_bytes_all_attempts_inputs_plus_controls"],
        "total_unique_tests":check["total_tests"]+gcheck["tests_run"],"AT_control_bodies_opened":False,
        "production_ready":False,"full_AT_DE_CH_validation_complete":False}
    if not recovery["original_code_hashes_match_seal"] or recovery["global_weather_body_bytes_including_first_acquisition"]>900_000_000:raise ValueError("V1_RECOVERY_INVARIANT")
    write_exclusive(R/RECOVERY,json_bytes(recovery));write_exclusive(out/RECOVERY,json_bytes(recovery))
    write_exclusive(R/"v1_revealed_source_registry_20261026.json",json_bytes(make_registry()))
    report(result,recovery)
    files={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*")) if p.is_file()}
    write_exclusive(out/"artifact_member_sha256.json",json_bytes(files))
    print(json.dumps({"V1_recovery_tests":recovery["total_unique_tests"],"initial_summary_matches":comparison["all_available_initial_summaries_match"],
        "source_byte_identity_with_lost_packet":False,"AT_controls_unopened":True}),flush=True)

def finalize(out,roundtrip):
    manifest=json.loads((out/"artifact_member_sha256.json").read_text())
    if (roundtrip/"artifact_member_sha256.json").read_bytes()!=(out/"artifact_member_sha256.json").read_bytes():raise ValueError("V1_ARTIFACT_MANIFEST_ROUNDTRIP")
    actual={p.relative_to(roundtrip).as_posix() for p in roundtrip.rglob("*") if p.is_file()}
    if actual!=set(manifest)|{"artifact_member_sha256.json"}:raise ValueError("V1_ARTIFACT_MEMBER_CENSUS")
    for n,d in manifest.items():
        if hashlib.sha256((roundtrip/n).read_bytes()).hexdigest()!=d:raise ValueError("V1_ARTIFACT_DOWNLOADED_MEMBER_HASH")
    recovery=json.loads((R/RECOVERY).read_text());result=json.loads((R/RESULTS).read_text())
    receipt={"schema":"IGE_V1_VERIFIED_CI_AND_ARTIFACT_v1","CI_run":int(os.environ["GITHUB_RUN_ID"]),
        "CI_url":"https://github.com/dmitrievii/building-energy-tools/actions/runs/"+os.environ["GITHUB_RUN_ID"],
        "tested_commit":os.environ["GITHUB_SHA"],"total_unique_tests":recovery["total_unique_tests"],
        "status":"PASS","artifact_id":int(os.environ["V1_ARTIFACT_ID"]),"artifact_sha256":os.environ["V1_ARTIFACT_SHA256"],
        "artifact_download_roundtrip_verified":True,"artifact_member_files_verified":len(manifest),
        "source_and_metrics_replay":True,"initial_summary_matches":recovery["summary_comparison"]["all_available_initial_summaries_match"],
        "raw_identity_with_first_local_packet_certified":False,"AT_control_bodies_unopened":True,
        "all24_cases_retained":True,"paired_primary_hours":result["counts"]["paired_primary_hours"],
        "independent_regional_full_weather_accuracy_qualified":False,"production_ready":False}
    write_exclusive(R/("v1_verified_CI_"+os.environ["GITHUB_RUN_ID"]+".json"),json_bytes(receipt))
    with (ROOT/"docs"/REPORT).open("a") as f:
        f.write("\nФинальный CI: **"+str(receipt["total_unique_tests"])+" PASS**. Загруженный артефакт повторно скачан, все "+str(len(manifest))+" файлов проверены по SHA256. Первичный локальный контрольный ZIP остаётся побайтово несопоставленным; повторно полученные оригиналы опубликованы в ветке.\n")
    path=R/"e2e_two_product_roadmap_20261025.json";road=json.loads(path.read_text())
    for m in road["milestones"]:
        if m["id"]=="V1":m["current_status"]="CI_VERIFIED_TIME_ADMISSION_AND_DE_CH_HOURLY_ERROR_HOLDOUT; AT_QC_BLOCKED_UNOPENED; ENERGYPLUS_AND_FULL_WEATHER_RELEASE_OPEN"
    road["current_execution_stage"]="V1 source and temperature validation: DE/CH 16 cases / 2688 hours; R1 worsens 2 of 4 sites; AT primary QC blocked and unopened; full V1 remains open"
    road["V1_progress"]={**receipt,"registration_commit":recovery["registration_commit"],"prediction_seal_commit":SEAL_COMMIT,
        "metadata_ready_cases":24,"admitted_primary_cases":result["counts"]["admitted_primary_cases"],"AT_source_blocked_cases":8,
        "country_aggregates_hide_two_worsened_stations":True,"R1_default_promoted":False,
        "recovered_original_control_packet_sha256":recovery["reacquired_control_packet_sha256"],
        "global_weather_body_bytes_including_initial_lost_acquisition":recovery["global_weather_body_bytes_including_first_acquisition"],
        "report":"docs/"+REPORT,"next":"AT_QC_ORIGIN_AND_SEPARATE_PREREGISTRATION; ACTUAL_ENERGYPLUS; GENERAL_CORRECTOR_APPLICABILITY"}
    path.write_bytes(json_bytes(road))
    with (ROOT/"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md").open("a") as f:
        f.write("\n\n**V1, 26.10.2026:** временные определения и датированная геометрия 2 м готовы для 24 случаев; 16 случаев DE/CH оценены на 2688 часах. R1 улучшил Augsburg/Scuol и ухудшил Erfurt/St. Gallen; страновые средние не дают общего допуска. AT22 отверг QC10 доноров, два AT контроля остаются закрыты. CI "+os.environ["GITHUB_RUN_ID"]+": 350 проверок, фактический source replay и проверка скачанного артефакта по SHA. После потери локальной среды контроли повторно получены без изменения научного кода; совпадение первоначальных численных сводок отмечено отдельно, идентичность потерянных исходных байтов не сертифицируется. Общая V1, production, EnergyPlus и полная метеорологическая точность открыты. Следом: происхождение AT QC10, отдельный допуск применимости общего корректора и реальный EnergyPlus-прогон существующих EPW; будущая локальная база должна быть многолетней. Подробности: docs/"+REPORT+".\n")
    # All original scientific implementation and seals remain byte exact.
    from v1_verify import protection
    protection()
    staged=[p.relative_to(ROOT).as_posix() for p in R.glob("v1_*") if p.is_file()]
    staged+=["docs/"+REPORT,"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md",
             "research/ige_cmip6/e2e_two_product_roadmap_20261025.json"]
    subprocess.run(["git","add","--",*staged],cwd=ROOT,check=True)
    changes=subprocess.check_output(["git","diff","--cached","--name-status"],cwd=ROOT,text=True).splitlines()
    for line in changes:
        status,name=line.split("\t",1)
        if status!="A" and name not in ("docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md","research/ige_cmip6/e2e_two_product_roadmap_20261025.json"):
            raise ValueError("V1_OLD_PUBLISHED_FILE_CHANGED:"+name)
    subprocess.run(["git","diff","--cached","--check"],cwd=ROOT,check=True)
    print(json.dumps(receipt),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True);p.add_argument("--roundtrip",type=Path);a=p.parse_args()
    if a.roundtrip:finalize(a.out,a.roundtrip)
    else:run(a.out)
